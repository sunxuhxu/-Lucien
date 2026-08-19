"""三大生活类手机 App API：衣橱换装 / 工作助手（整理资料）/ 恋爱日记（打卡+定位+日记）。
数据持久化到角色目录 JSON（RolePath 按请求角色动态路由），风格与 creative_apps.py 保持一致。
"""
import json
import random
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()


# ---------------------------------------------------------------------------
# 公共工具（延迟导入避免与 app.py 循环依赖）
# ---------------------------------------------------------------------------

async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


def _system_prompt() -> str:
    from app import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _add_affinity(action: str, detail: str = "") -> dict:
    from app import _add_affinity as _impl
    return _impl(action, detail)


def _load(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path, data):
    atomic_json(path, data)


def _now() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# ===========================================================================
# 1. 衣橱 —— 给许墨换衣服：生成换装立绘并同步为当前头像
# ===========================================================================

WARDROBE_FILE = RolePath("wardrobe.json")
WARDROBE_DIR = None  # 运行时从 app.STATIC_DIR 派生


def _wardrobe_dir():
    global WARDROBE_DIR
    if WARDROBE_DIR is None:
        from app import STATIC_DIR
        WARDROBE_DIR = RolePath("static", "wardrobe")
    return WARDROBE_DIR


# 换装预设：衣着只允许黑白灰紫（遵循人设卡铁律），其余外貌锚点由 XUMO_LOOK_EN 保证
WARDROBE_OUTFITS = [
    {"id": "classic",    "name": "白衬衫 · 日常教授", "emoji": "👔",
     "desc": "白衬衫袖口轻挽＋深灰长裤，斯文又利落的办公室日常",
     "prompt": "wearing a crisp white dress shirt with the sleeves lightly rolled up, dark grey tailored trousers, black leather shoes, neat professor's office setting"},
    {"id": "purplecoat", "name": "深紫长风衣", "emoji": "🧥",
     "desc": "深紫色长风衣＋白衬衫，恋语市夜色的标志身影",
     "prompt": "wearing a deep purple long trench coat over a crisp white shirt, dark grey trousers, black leather shoes, rainy night city street with soft neon glow"},
    {"id": "cardigan",   "name": "深灰针织开衫", "emoji": "🧶",
     "desc": "深灰针织开衫＋浅灰内搭，图书馆午后的温度",
     "prompt": "wearing a dark grey knitted cardigan over a light grey sweater, black trousers, holding a book, warm university library setting"},
    {"id": "lab",        "name": "实验室白大褂", "emoji": "🔬",
     "desc": "白大褂＋白衬衫，B3 实验室里认真记录的许教授",
     "prompt": "wearing a white laboratory coat over a white shirt, dark trousers, holding a pen and clipboard, modern neuroscience laboratory setting with soft cool lighting"},
    {"id": "turtleneck", "name": "黑色高领毛衣", "emoji": "🖤",
     "desc": "黑色高领毛衣＋深灰大衣，克制又温柔的冬日",
     "prompt": "wearing a black turtleneck sweater under a dark grey long overcoat, black trousers, light snow outside the window, cozy evening room"},
    {"id": "suit",       "name": "深灰西装三件套", "emoji": "🤵",
     "desc": "深灰西装三件套＋暗紫细领带，正式场合的许教授",
     "prompt": "wearing an elegant dark grey three-piece suit with a subtle dark violet tie, polished leather shoes, formal conference hall setting"},
    {"id": "home",       "name": "家居休闲", "emoji": "🛋️",
     "desc": "纯白 T 恤＋深灰家居裤，家里最放松的样子",
     "prompt": "wearing a plain white t-shirt and soft dark grey loungewear pants, cozy warm home setting, holding a cup of black coffee"},
    {"id": "winter",     "name": "围巾大衣", "emoji": "🧣",
     "desc": "深灰大衣＋紫色羊毛围巾，初雪的恋语市街头",
     "prompt": "wearing a dark grey wool overcoat with a deep purple scarf, black trousers, falling snow and warm street lights in the background"},
]

# 换装立绘系统提示：强制「衣着按指定服装，其余锚点不变」
WARDROBE_IMG_PROMPT = """你是《恋与制作人》官方卡面绘制助手。请为许墨（Lucien）绘制一张「换装立绘」卡面。

【许墨形象锚点（必须逐字保留，只能修改其中衣着描述）】
"{xumo_look}"

【铁律】
1. 衣着以用户指定的那套服装为准（款式/颜色/细节逐项落实），把锚点里 "wearing a crisp white shirt with dark grey or deep purple layers ..." 整段替换为新服装的英文描述；外貌其他部分（银框眼镜、深紫眼眸、发型、脸型）一字不改。
2. 银色细框眼镜必须清晰出现在脸上，不得省略或虚化；瞳色深紫罗兰，严禁琥珀棕/灰/蓝瞳。
3. 服装颜色只允许黑白灰紫，严禁亮色。
4. 画风严禁 Q版/chibi 大头身。

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{{"image_prompt": "英文绘图提示词，100~170 词：完整许墨外貌锚点（衣着部分替换为指定服装描述）+ 指定服装细节 + 自然站姿 + 背景场景 + 日系乙女向精致立绘、厚涂+赛璐璐、柔和唯美光影、背景虚化光斑 + 冷紫调统一色调"}}"""


def _load_wardrobe() -> dict:
    data = _load(WARDROBE_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("records", [])   # 换装记录（最新在前）
    data.setdefault("current", None)  # {outfit_id, name, img, ts}
    return data


def _register_as_avatar(img_path: Path, name: str) -> str:
    """把生成的换装图注册进头像库并设为当前头像，返回头像 id。"""
    from app import _xumo_avatar_load, _xumo_avatar_save, _xumo_avatar_bump, XUMO_AVATAR_UPLOADS_DIR
    state = _xumo_avatar_load()
    up_id = uuid.uuid4().hex[:12]
    ext = img_path.suffix or ".png"
    dest = XUMO_AVATAR_UPLOADS_DIR / f"{up_id}{ext}"
    shutil.copyfile(img_path, dest)
    state.setdefault("uploads", []).append({
        "id": up_id,
        "name": name,
        "url": f"/static/xumo_avatar/{up_id}{ext}",
        "path": str(dest),
        "mime": "png" if ext == ".png" else "jpeg",
        "ext": ext,
        "time": datetime.now().strftime("%m-%d %H:%M"),
    })
    state["active_id"] = up_id
    _xumo_avatar_bump(state)
    _xumo_avatar_save(state)
    return up_id


@router.get("/api/wardrobe")
async def wardrobe_list():
    data = _load_wardrobe()
    return {
        "outfits": WARDROBE_OUTFITS,
        "current": data.get("current"),
        "records": list(data.get("records", []))[:60],
    }


@router.post("/api/wardrobe/wear")
async def wardrobe_wear(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] life_apps.py:wardrobe_wear: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    outfit_id = (body.get("outfit") or "").strip()
    outfit = next((o for o in WARDROBE_OUTFITS if o["id"] == outfit_id), None)
    if not outfit:
        return JSONResponse({"error": "衣橱里没有这套衣服"}, status_code=400)

    from app import IMG2IMG_SIZES, _llm_image_for_text, ImageQuotaError
    rec_id = _uid()
    out_dir = _wardrobe_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        img_url, _ = await _llm_image_for_text(
            f"【衣橱换装】请让许墨穿上这套衣服：{outfit['name']}（{outfit['desc']}）\n"
            f"服装细节：{outfit['prompt']}\n"
            f"画幅：竖版半身立绘，构图以人物为中心，衣着细节清晰可见。",
            out_dir, "/static/wardrobe", f"wear_{rec_id}",
            IMG2IMG_SIZES.get("portrait", "1536x2048"),
            with_xumo=True, system_prompt=WARDROBE_IMG_PROMPT,
        )
    except ImageQuotaError as e:
        return JSONResponse({"error": str(e)}, status_code=429)
    except Exception as e:
        print(f"[warn] life_apps.py:wardrobe_wear: {type(e).__name__} {str(e)[:150]}", flush=True)
        img_url = None
    if not img_url:
        return JSONResponse({"error": "裁缝铺的机器卡住了，稍后再试一次？"}, status_code=500)
    img_url = img_url + f"?t={int(datetime.now().timestamp())}"

    # 同步为当前头像（聊天/通话/朋友圈等所有场景立即生效）
    local_path = None
    try:
        rel = img_url.split("?")[0].lstrip("/")
        if rel.startswith("static/"):
            local_path = Path(app_static_dir()) / rel[len("static/"):]
    except Exception as e:
        print(f"[warn] life_apps.py:wardrobe_wear: {type(e).__name__} {str(e)[:150]}", flush=True)
        local_path = None
    if local_path is not None and local_path.exists():
        avatar_id = _register_as_avatar(local_path, f"衣橱 · {outfit['name']}")
    else:
        avatar_id = ""

    record = {
        "id": rec_id,
        "outfit_id": outfit["id"],
        "name": outfit["name"],
        "emoji": outfit["emoji"],
        "desc": outfit["desc"],
        "img": img_url,
        "avatar_id": avatar_id,
        "ts": _now(),
    }
    data = _load_wardrobe()
    data["current"] = {k: record[k] for k in ("outfit_id", "name", "emoji", "desc", "img", "ts")}
    data.setdefault("records", []).insert(0, record)
    data["records"] = data["records"][:60]
    _save(WARDROBE_FILE, data)

    info = _add_affinity("wardrobe", f"换装 · {outfit['name']}")
    from app import _xumo_avatar_load
    return {"record": record, "affinity": info, "avatar_version": _xumo_avatar_load().get("version", 1)}


def app_static_dir():
    from app import STATIC_DIR
    return STATIC_DIR


@router.post("/api/wardrobe/set")
async def wardrobe_set(req: Request):
    """把衣橱里某条换装记录重新穿回（设为当前头像）。"""
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] life_apps.py:wardrobe_set: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    rec_id = (body.get("id") or "").strip()
    data = _load_wardrobe()
    rec = next((r for r in data.get("records", []) if r.get("id") == rec_id), None)
    if not rec:
        return JSONResponse({"error": "这套衣服不在了"}, status_code=404)
    from app import _xumo_avatar_load, _xumo_avatar_save, _xumo_avatar_bump
    state = _xumo_avatar_load()
    if rec.get("avatar_id") and any(u.get("id") == rec["avatar_id"] for u in state.get("uploads", [])):
        state["active_id"] = rec["avatar_id"]
    else:
        # 头像记录已丢失：重新注册
        local = Path(app_static_dir()) / rec["img"].split("?")[0].lstrip("/")
        if not local.exists():
            return JSONResponse({"error": "立绘文件已丢失，请重新生成"}, status_code=404)
        rec["avatar_id"] = _register_as_avatar(local, f"衣橱 · {rec['name']}")
    _xumo_avatar_bump(state)
    _xumo_avatar_save(state)
    data["current"] = {k: rec[k] for k in ("outfit_id", "name", "emoji", "desc", "img", "ts")}
    _save(WARDROBE_FILE, data)
    return {"ok": True, "record": rec, "avatar_version": state.get("version", 1)}


# ===========================================================================
# 2. 工作助手 —— 帮她一起整理许墨的研究资料
# ===========================================================================

WORK_FILE = RolePath("work.json")

WORK_CATEGORIES = [
    {"key": "data",     "name": "实验数据",   "emoji": "📊"},
    {"key": "paper",    "name": "论文草稿",   "emoji": "📄"},
    {"key": "meeting",  "name": "会议纪要",   "emoji": "📝"},
    {"key": "lesson",   "name": "教案讲义",   "emoji": "📚"},
    {"key": "student",  "name": "学生作业",   "emoji": "🎓"},
    {"key": "fund",     "name": "基金申报",   "emoji": "🏦"},
    {"key": "lab",      "name": "实验室采购", "emoji": "🧪"},
]

# 资料池：一批待整理的研究资料（标题 + 类型 + 一句话备注）
WORK_DOC_POOL = [
    {"title": "Evol 素提取实验 · 第17批数据", "type": "data", "note": "3 组对照，每组 8 个样本，文件编号 17-A/B/C"},
    {"title": "冬眠相关脑区 fMRI 原始数据", "type": "data", "note": "36 名被试，未预处理，共 8.2 GB"},
    {"title": "记忆突触可塑性综述（初稿）", "type": "paper", "note": "差结论部分与参考文献，第 3 章红笔标注过"},
    {"title": "睡眠与记忆巩固 · 审稿意见回函", "type": "paper", "note": "两位审稿人意见 + 回复草稿，有一处数据需要复核"},
    {"title": "神经科学组会纪要 07-21", "type": "meeting", "note": "三个项目进度汇报，下周要出的方案没写总结"},
    {"title": "B3 实验室安全培训纪要", "type": "meeting", "note": "危险化学品清单更新，两份签名表未归档"},
    {"title": "神经科学导论 · 第6章课件", "type": "lesson", "note": "突触传递章节，缺三张示意图与课后习题"},
    {"title": "EEG 实验设计讲义（修订版）", "type": "lesson", "note": "第 4 讲勘误未同步，页码对不上"},
    {"title": "研究生课程论文批改（23 份）", "type": "student", "note": "评语已写，缺成绩登记表"},
    {"title": "开题报告评审意见 ×6", "type": "student", "note": "两份需要补充修改建议，其余可直接返回"},
    {"title": "NSFC 面上项目申请书（2026）", "type": "fund", "note": "预算表与正文不符，合作单位盖章缺一份"},
    {"title": "青年基金预算表", "type": "fund", "note": "差差旅费明细，单位公章未盖"},
    {"title": "试剂采购清单与三家报价单", "type": "lab", "note": "抗体价格差异 30%，需要比价后定标"},
    {"title": "冷冻离心机维修记录", "type": "lab", "note": "报修单已提交，缺保修卡复印件"},
    {"title": "文献管理库导出 · 2026-07", "type": "paper", "note": "312 条条目，重复条目约 40 条待去重"},
    {"title": "蝴蝶行为学观察日志", "type": "data", "note": "实验楼天台的蝴蝶观测记录，与他的私人研究有关"},
    {"title": "认知心理学课程教案 · 第8讲", "type": "lesson", "note": "课后思考题答案还没整理"},
    {"title": "实验器材借用登记表", "type": "lab", "note": "三台示波器的归还日期已过"},
]

WORK_SESSION_TITLES = [
    "Black Swan 资料室 · 本周归档",
    "恋语大学研究院 · 月终资料整理",
    "B3 实验室 · 项目资料归位",
    "许墨的办公桌 · 午后整理",
]

WORK_STATS_FILE = RolePath("work_stats.json")


def _load_work() -> dict:
    data = _load(WORK_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("sessions", [])
    return data


def _load_work_stats() -> dict:
    stats = _load(WORK_STATS_FILE, {})
    if not isinstance(stats, dict):
        stats = {}
    stats.setdefault("total_sorted", 0)
    stats.setdefault("total_sessions", 0)
    return stats


@router.get("/api/work")
async def work_list():
    data = _load_work()
    stats = _load_work_stats()
    sessions = list(data.get("sessions", []))[-20:]
    return {
        "categories": WORK_CATEGORIES,
        "sessions": list(reversed(sessions)),
        "active_session": next((s for s in sessions if not s.get("finished")), None),
        "stats": stats,
    }


def _new_work_session() -> dict:
    docs = random.sample(WORK_DOC_POOL, k=min(6, len(WORK_DOC_POOL)))
    return {
        "id": _uid(),
        "title": random.choice(WORK_SESSION_TITLES),
        "created_ts": _now(),
        "docs": [
            {
                "id": _uid(),
                "title": d["title"],
                "type": d["type"],
                "note": d["note"],
                "status": "unsorted",
                "category": "",
                "summary": "",
            }
            for d in docs
        ],
        "finished": False,
        "thanks": "",
    }


@router.post("/api/work/start")
async def work_start():
    data = _load_work()
    # 未完成的批次先收尾，避免堆叠
    for s in data.get("sessions", []):
        if not s.get("finished"):
            s["finished"] = True
            s["thanks"] = "（上一批资料留在了桌上，她后来自己收拾好了）"
    session = _new_work_session()
    data.setdefault("sessions", []).append(session)
    data["sessions"] = data["sessions"][-60:]
    _save(WORK_FILE, data)
    return {"session": session}


@router.post("/api/work/doc/{doc_id}/sort")
async def work_doc_sort(doc_id: str, req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] life_apps.py:work_doc_sort: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    category = (body.get("category") or "").strip()
    cat = next((c for c in WORK_CATEGORIES if c["key"] == category), None)
    if not cat:
        return JSONResponse({"error": "未知的分类抽屉"}, status_code=400)

    data = _load_work()
    session = next((s for s in data.get("sessions", []) if not s.get("finished")), None)
    if not session:
        return JSONResponse({"error": "桌上还没有待整理的资料，先开一批新的"}, status_code=400)
    doc = next((d for d in session.get("docs", []) if d.get("id") == doc_id), None)
    if not doc:
        return JSONResponse({"error": "这份资料不在这批里"}, status_code=404)
    if doc.get("status") == "sorted":
        return JSONResponse({"error": "这份资料已经归好类了"}, status_code=400)
    doc["status"] = "sorted"
    doc["category"] = category
    doc["sorted_ts"] = _now()
    _save(WORK_FILE, data)

    stats = _load_work_stats()
    stats["total_sorted"] = stats.get("total_sorted", 0) + 1
    _save(WORK_STATS_FILE, stats)

    done = sum(1 for d in session.get("docs", []) if d.get("status") == "sorted")
    info = _add_affinity("work_organize", f"整理资料 · {doc['title']}")
    return {"doc": doc, "done": done, "total": len(session.get("docs", [])), "affinity": info}


@router.post("/api/work/doc/{doc_id}/summarize")
async def work_doc_summarize(doc_id: str):
    """让许墨把某份资料讲给她听（LLM 摘要 + 一句点评）。"""
    data = _load_work()
    session = next((s for s in data.get("sessions", []) if not s.get("finished")), None)
    if not session:
        return JSONResponse({"error": "没有可读的资料"}, status_code=400)
    doc = next((d for d in session.get("docs", []) if d.get("id") == doc_id), None)
    if not doc:
        return JSONResponse({"error": "这份资料不在这批里"}, status_code=404)
    cat = next((c for c in WORK_CATEGORIES if c["key"] == doc["type"]), None)
    cat_name = cat["name"] if cat else "资料"

    prompt = (_system_prompt()
              + f"\n\n【当前任务】她在帮你整理工作资料。她拿起一份资料请你讲给她听：「{doc['title']}」（{cat_name}）\n"
              + f"资料备注：{doc['note']}\n"
              + "请以许墨的口吻用 60-90 字讲清楚这份资料是什么、为什么重要，最后一句可带一点许墨式的温柔（话留三分）。只输出正文，不要标题和引号。")
    try:
        text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=300)).strip()
    except Exception as e:
        print(f"[warn] life_apps.py:work_doc_summarize: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = ""
    if not text:
        return JSONResponse({"error": "他今天嗓子有点哑，稍后再试"}, status_code=500)
    doc["summary"] = text
    _save(WORK_FILE, data)
    return {"doc": doc}


@router.post("/api/work/finish")
async def work_finish():
    data = _load_work()
    session = next((s for s in data.get("sessions", []) if not s.get("finished")), None)
    if not session:
        return JSONResponse({"error": "没有进行中的整理任务"}, status_code=400)
    docs = session.get("docs", [])
    unsorted = [d for d in docs if d.get("status") != "sorted"]
    if unsorted:
        return JSONResponse({"error": f"还有 {len(unsorted)} 份资料没有归类"}, status_code=400)

    cats = {}
    for d in docs:
        cats.setdefault(d["category"], 0)
        cats[d["category"]] += 1
    cat_desc = "、".join(
        f"{next((c['name'] for c in WORK_CATEGORIES if c['key'] == k), k)}×{v}" for k, v in cats.items()
    )
    prompt = (_system_prompt()
              + f"\n\n【当前任务】她帮许墨整理完了一整批工作资料，共 {len(docs)} 份，分类情况：{cat_desc}。\n"
              + "请以许墨的口吻写一段 50-90 字的道谢与感慨：温柔、克制、带一点学者的认真，"
              + "可以点出某一两份具体资料的名字，结尾一句许墨式的温柔（话留三分）。只输出正文，不要标题和引号。")
    try:
        thanks = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=300)).strip()
    except Exception as e:
        print(f"[warn] life_apps.py:work_finish: {type(e).__name__} {str(e)[:150]}", flush=True)
        thanks = ""
    if not thanks:
        thanks = "整理得比我想象中还利落。谢谢你，这些资料放在我桌上，比实验数据还让人安心。"

    session["finished"] = True
    session["finished_ts"] = _now()
    session["thanks"] = thanks
    _save(WORK_FILE, data)

    stats = _load_work_stats()
    stats["total_sessions"] = stats.get("total_sessions", 0) + 1
    _save(WORK_STATS_FILE, stats)

    info = _add_affinity("work_finish", f"整理完一批资料 · {session['title']}")
    return {"session": session, "affinity": info}


# ===========================================================================
# 3. 恋爱日记 —— 每天一起打卡 + 写日记 + 许墨实时定位
# ===========================================================================

DIARY_FILE = RolePath("diary.json")

DIARY_CHECKIN_PROMPT = _system_prompt() + """

【当前任务】这是「恋爱日记」的每日打卡。她刚刚按下打卡按钮，标记了今天也和你在一起。
请以许墨的口吻回一句打卡祝福（30-55 字）：温柔克制，话留三分，可以呼应今天的天气或心情，结尾轻轻落在「明天也」的约定上。只输出正文，不要标题和引号。"""

DIARY_ENTRY_PROMPT = _system_prompt() + """

【当前任务】她在「恋爱日记」里写下了一段今天的日记，请你以许墨的口吻认真回应（45-85 字）：
1. 先接住她日记里的某个具体细节（一个动作、一句话、一个场景），证明你读得很仔细；
2. 再写一句许墨式的温柔回应，学术式撩人或话留三分；
3. 不要复述整篇日记，不要评价性空话。只输出正文，不要标题和引号。"""


def _load_diary() -> dict:
    data = _load(DIARY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("checks", [])
    data.setdefault("entries", [])
    data.setdefault("anniv", "")
    return data


def _diary_streak(checks: list) -> int:
    """连续打卡天数：从今天或昨天往前数。"""
    days = {c.get("date") for c in checks}
    streak = 0
    cursor = datetime.now().date()
    if cursor.strftime("%Y-%m-%d") not in days:
        cursor -= timedelta(days=1)  # 今天没打卡也允许保 streak
    while cursor.strftime("%Y-%m-%d") in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


@router.get("/api/diary")
async def diary_list():
    data = _load_diary()
    checks = data.get("checks", [])
    today = _today()
    today_check = next((c for c in reversed(checks) if c.get("date") == today), None)
    anniv = data.get("anniv") or (checks[0]["date"] if checks else today)
    try:
        days_together = (datetime.now().date() - datetime.strptime(anniv, "%Y-%m-%d").date()).days + 1
    except (ValueError, TypeError):
        days_together = 1
    return {
        "today_checked": bool(today_check),
        "today_reply": today_check.get("reply", "") if today_check else "",
        "checks": list(reversed(checks[-366:])),
        "entries": list(reversed(data.get("entries", [])[-60:])),
        "streak": _diary_streak(checks),
        "total_checks": len(checks),
        "anniv": anniv,
        "days_together": max(1, days_together),
    }


@router.post("/api/diary/checkin")
async def diary_checkin():
    data = _load_diary()
    today = _today()
    if any(c.get("date") == today for c in data.get("checks", [])):
        old = next(c for c in reversed(data.get("checks", [])) if c.get("date") == today)
        return {"check": old, "cached": True}
    try:
        reply = (await _call_llm([{"role": "user", "content": DIARY_CHECKIN_PROMPT}], max_tokens=200)).strip()
    except Exception as e:
        print(f"[warn] life_apps.py:diary_checkin: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = ""
    if not reply:
        reply = "今天也记下了。明天，我们还会在一起。"
    check = {"date": today, "ts": _now(), "reply": reply}
    data.setdefault("checks", []).append(check)
    if not data.get("anniv"):
        data["anniv"] = today
    data["checks"] = data["checks"][-366:]
    _save(DIARY_FILE, data)
    info = _add_affinity("diary_checkin", "恋爱日记 · 每日打卡")
    return {"check": check, "cached": False, "affinity": info}


@router.post("/api/diary/entry")
async def diary_entry(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] life_apps.py:diary_entry: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    text = (body.get("text") or "").strip()[:500]
    if not text:
        return JSONResponse({"error": "先写点什么吧"}, status_code=400)
    prompt = DIARY_ENTRY_PROMPT + f"\n\n【她今天的日记】{text}"
    try:
        reply = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=300)).strip()
    except Exception as e:
        print(f"[warn] life_apps.py:diary_entry: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = ""
    if not reply:
        reply = "这段话我读了好几遍。今天你心里那些起起伏伏，我都收好了。"
    entry = {"id": _uid(), "date": _today(), "ts": _now(), "text": text, "reply": reply}
    data = _load_diary()
    data.setdefault("entries", []).append(entry)
    data["entries"] = data["entries"][-60:]
    _save(DIARY_FILE, data)
    info = _add_affinity("diary_entry", "恋爱日记 · 写下今天")
    return {"entry": entry, "affinity": info}


@router.delete("/api/diary/{entry_id}")
async def diary_delete(entry_id: str):
    data = _load_diary()
    before = len(data.get("entries", []))
    data["entries"] = [e for e in data.get("entries", []) if e.get("id") != entry_id]
    if len(data["entries"]) == before:
        return JSONResponse({"error": "这篇日记不存在"}, status_code=404)
    _save(DIARY_FILE, data)
    return {"ok": True}


@router.get("/api/diary/location")
async def diary_location():
    """许墨的实时定位：优先取自主生活引擎状态，否则回退静态时间表。"""
    try:
        from app import _load_life
        st = _load_life().get("state")
    except Exception as e:
        print(f"[warn] life_apps.py:diary_location: {type(e).__name__} {str(e)[:150]}", flush=True)
        st = None
    if st:
        return {
            "place": st.get("place", "恋语市"),
            "scene": st.get("scene", ""),
            "activity": st.get("activity", ""),
            "mood": st.get("mood", ""),
            "emoji": st.get("emoji", "🦋"),
            "since": st.get("since_str", ""),
            "source": "live",
        }
    # 回退：静态时间表
    from app import STATUS_SEGMENTS
    now = datetime.now()
    for s, e, scene, activity, mood, emoji in STATUS_SEGMENTS:
        if s <= now.hour < e:
            place = scene.split(" · ")[0] if " · " in scene else "恋语市"
            return {
                "place": place,
                "scene": scene,
                "activity": activity,
                "mood": mood,
                "emoji": emoji,
                "since": "",
                "source": "static",
            }
    return {
        "place": "恋语市",
        "scene": "恋语市 · 研究院办公室",
        "activity": "整理课题资料",
        "mood": "沉稳",
        "emoji": "📚",
        "since": "",
        "source": "static",
    }
