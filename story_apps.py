"""六大互动养成功能后端（story_apps.py）
============================================================
对应产品清单：
  1. 互动剧情副本   —— 多结局恋爱/冒险互动叙事，玩家做选择推进，每结局生成纪念卡+配图
  2. 许墨工作经济系统 —— 职业/工资/攒钱，共同基金买约会礼物、纪念品，晋升剧情
  3. 特质养成系统   —— 行为驱动成长：解锁新口头禅、新技能、新习惯，主页展示
  4. 定制晚安故事   —— 根据今天真实互动生成专属睡前故事，TTS 朗读，配图
  5. 树洞模式       —— 匿名倾诉，聊完即焚不留记忆，许墨温柔回应，零负担
  6. 节日事件引擎   —— 自动识别节日/纪念日/生日，触发专属剧情、礼物、场景图

所有数据按请求角色（owner / 注册用户）隔离到 RolePath，复用 app 的 LLM / 文生图 / 心动值能力。
图像与 TTS 失败均降级处理，保证功能在缺少外部服务时仍可返回文本。
"""
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from store_common import atomic_json, file_lock
from role_data import RolePath, role_file as _role_file

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
STORY_HTML = STATIC_DIR / "story.html"

router = APIRouter()

# ---------------------------------------------------------------------------
# 懒加载 app 能力（避免循环依赖）
# ---------------------------------------------------------------------------
async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


async def _gen_image(material: str, sub_dir: str, name: str,
                     ratio: str = "landscape", with_xumo: bool = True) -> str:
    """复用 app 的文生图，返回可访问 URL；失败返回空串。"""
    from app import _openai_generate_image, IMG2IMG_SIZES
    out_dir = STATIC_DIR / sub_dir
    size = IMG2IMG_SIZES.get(ratio, "1024x1024")
    try:
        url = await _openai_generate_image(material, out_dir, f"/static/{sub_dir}",
                                            name, size, has_character=with_xumo)
    except Exception:
        return ""
    if not url:
        return ""
    return url + f"?t={int(datetime.now().timestamp())}"


def _add_affinity(action: str, detail: str = "") -> dict:
    from app import _add_affinity as _impl
    return _impl(action, detail)


def _load_affinity() -> dict:
    from app import _load_affinity as _impl
    return _impl()


# ---------------------------------------------------------------------------
# 本地存储助手
# ---------------------------------------------------------------------------
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


def _strip_fence(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    return text.strip()


def _parse_json(text: str):
    try:
        return json.loads(_strip_fence(text))
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


async def _llm_json(messages: list, max_tokens: int = 1200):
    """调用 LLM 并解析 JSON；失败返回 None。"""
    try:
        raw = await _call_llm(messages, max_tokens=max_tokens)
    except Exception:
        return None
    return _parse_json(raw) if raw else None


# ===========================================================================
# 1. 互动剧情副本（多结局互动叙事）
# ===========================================================================
STORY_FILE = RolePath("story_dungeon.json")
STORY_THEMES = [
    {"key": "campus", "name": "校园暗恋", "emoji": "🎓",
     "desc": "图书馆、天台与未说出口的纸条"},
    {"key": "office", "name": "都市恋曲", "emoji": "💼",
     "desc": "加班夜里的咖啡与并肩作战"},
    {"key": "magic", "name": "奇幻冒险", "emoji": "🔮",
     "desc": "魔法契约与共同封印的宿命"},
    {"key": "scifi", "name": "星海远征", "emoji": "🚀",
     "desc": "末世方舟上的相依为命"},
    {"key": "mystery", "name": "悬疑迷局", "emoji": "🕵️",
     "desc": "雨夜案件与彼此试探的信任"},
    {"key": "ancient", "name": "古风江湖", "emoji": "🏮",
     "desc": "江湖路远，与君同舟"},
]

STORY_SYSTEM = (
    "你是互动剧情引擎，与主角是许墨（26岁，沉稳温柔、观察力极强的男性）。"
    "根据玩家选择推进一段{genre}故事。当前节点需要输出：\n"
    "1) narrative：一段 80-160 字、有画面感与情绪张力的剧情叙述（以许墨的视角/对话展开）；\n"
    "2) choices：2-3 个玩家可选的行动（每个含 text 与 hint 一句话后果暗示）；\n"
    "3) is_ending：当剧情抵达一个自然高潮收束时设为 true，并给出 ending_type"
    "（从 甜蜜结局 / 虐心结局 / 开放结局 / 隐藏结局 中选一）。\n"
    "多结局：不同选择应导向不同结局。输出严格 JSON："
    "{\"narrative\":\"...\",\"choices\":[{\"text\":\"...\",\"hint\":\"...\"}],\"is_ending\":false,"
    "\"ending_type\":\"\"}"
)


def _story_session(data: dict, sid: str):
    return data.get("sessions", {}).get(sid)


@router.get("/api/story/themes")
async def story_themes():
    return {"themes": STORY_THEMES}


@router.post("/api/story/start")
async def story_start(req: Request):
    body = await _safe_json(req)
    theme = (body.get("theme") or "campus")
    genre = (body.get("genre") or "浪漫恋爱")
    title = (body.get("title") or "").strip()
    theme_meta = next((t for t in STORY_THEMES if t["key"] == theme), STORY_THEMES[0])

    prompt = (
        f"主题：{theme_meta['name']}（{theme_meta['desc']}）。类型：{genre}。"
        f"{('玩家自定义标题：' + title) if title else ''}请生成开场节点。"
    )
    node = await _story_node(prompt, genre, path_summary="故事刚开始。")
    if node is None:
        return JSONResponse({"error": "剧情生成失败，请稍后重试"}, status_code=500)

    sid = _uid()
    data = _load(STORY_FILE, {"sessions": {}})
    data.setdefault("sessions", {})
    session = {
        "id": sid,
        "title": title or f"{theme_meta['name']}·{genre}",
        "theme": theme,
        "genre": genre,
        "created": _now(),
        "nodes": [node],
        "path": [],
        "current": 0,
        "ending": None,
        "card": None,
    }
    data["sessions"][sid] = session
    _save(STORY_FILE, data)
    _add_affinity("story_start", f"开启剧情·{theme_meta['name']}")
    return {"session": _story_view(session)}


async def _story_node(prompt: str, genre: str, path_summary: str, force_ending: bool = False) -> dict:
    sys = STORY_SYSTEM.replace("{genre}", genre)
    user = f"【已有剧情路径】{path_summary}\n【本次需求】{prompt}"
    if force_ending:
        user += "\n（剧情已推进足够长，请在本次节点给出一个结局：is_ending=true，并选择一种 ending_type）"
    raw = None
    for _ in range(2):  # 重试一次，避免偶发空/非 JSON 输出导致剧情中断
        try:
            raw = await _call_llm([
                {"role": "system", "content": sys},
                {"role": "user", "content": user},
            ], max_tokens=900)
        except Exception:
            raw = None
        node = _parse_json(raw) if raw else None
        if isinstance(node, dict) and "narrative" in node:
            node.setdefault("choices", [])
            node.setdefault("is_ending", False)
            node.setdefault("ending_type", "")
            return node
    # 兜底节点：保证剧情永不卡死
    return {
        "narrative": "夜色温柔下来，你们并肩走着，谁都没有先开口。有些话，或许本就不需要说尽。",
        "choices": [
            {"text": "轻轻握住他的手", "hint": "让沉默也变得安心"},
            {"text": "抬头看他一眼", "hint": "眼底藏着未说的温柔"},
        ],
        "is_ending": False,
        "ending_type": "",
    }


@router.post("/api/story/choose")
async def story_choose(req: Request):
    body = await _safe_json(req)
    sid = body.get("session_id") or (body.get("sid") or "")
    choice_index = int(body.get("choice_index", 0))
    data = _load(STORY_FILE, {"sessions": {}})
    session = _story_session(data, sid)
    if not session:
        return JSONResponse({"error": "剧情会话不存在"}, status_code=404)
    current = session["nodes"][session["current"]]
    choices = current.get("choices", [])
    if choice_index < 0 or choice_index >= len(choices):
        return JSONResponse({"error": "选项无效"}, status_code=400)
    chosen = choices[choice_index]
    session["path"].append({"index": choice_index, "text": chosen.get("text", "")})

    if current.get("is_ending"):
        # 已结局不能再选（理论上前端会拦，这里兜底）
        return JSONResponse({"error": "该剧情已抵达结局"}, status_code=400)

    # 拼出路径摘要
    path_summary = "；".join([f"选择了：{p['text']}" for p in session["path"]])
    new_step = len(session["nodes"]) + 1
    node = await _story_node(
        f"玩家刚刚选择了：{chosen.get('text')}（{chosen.get('hint','')}）。请继续推进剧情。",
        session["genre"], path_summary, force_ending=(new_step >= 6))
    if node is None:
        return JSONResponse({"error": "剧情生成失败，请稍后重试"}, status_code=500)

    session["nodes"].append(node)
    session["current"] = len(session["nodes"]) - 1
    if node.get("is_ending"):
        session["ending"] = {
            "type": node.get("ending_type") or "开放结局",
            "at": _now(),
        }
        _add_affinity("story_ending", f"抵达结局·{node.get('ending_type') or '开放'}")
    _save(STORY_FILE, data)
    return {"session": _story_view(session)}


def _story_view(session: dict) -> dict:
    cur = session["nodes"][session["current"]]
    return {
        "id": session["id"],
        "title": session["title"],
        "theme": session["theme"],
        "genre": session["genre"],
        "created": session["created"],
        "current_node": cur,
        "step": session["current"] + 1,
        "is_ending": cur.get("is_ending", False),
        "ending_type": cur.get("ending_type", ""),
        "path": session["path"],
        "card": session.get("card"),
        "ending": session.get("ending"),
    }


@router.get("/api/story/sessions")
async def story_sessions():
    data = _load(STORY_FILE, {"sessions": {}})
    items = []
    for s in data.get("sessions", {}).values():
        items.append({
            "id": s["id"],
            "title": s["title"],
            "theme": s["theme"],
            "genre": s["genre"],
            "created": s["created"],
            "steps": len(s["nodes"]),
            "is_ending": bool(s.get("ending")),
            "ending_type": (s.get("ending") or {}).get("type", ""),
            "has_card": bool(s.get("card")),
        })
    items.sort(key=lambda x: x["created"], reverse=True)
    return {"sessions": items}


@router.get("/api/story/{sid}")
async def story_detail(sid: str):
    data = _load(STORY_FILE, {"sessions": {}})
    session = _story_session(data, sid)
    if not session:
        return JSONResponse({"error": "剧情会话不存在"}, status_code=404)
    return {"session": _story_view(session)}


@router.post("/api/story/{sid}/card")
async def story_card(sid: str):
    """为已抵达结局的剧情生成纪念卡 + 配图。"""
    data = _load(STORY_FILE, {"sessions": {}})
    session = _story_session(data, sid)
    if not session:
        return JSONResponse({"error": "剧情会话不存在"}, status_code=404)
    if not session.get("ending"):
        return JSONResponse({"error": "该剧情尚未抵达结局，无法生成纪念卡"}, status_code=400)
    if session.get("card"):
        return {"card": session["card"]}

    ending_type = (session.get("ending") or {}).get("type", "开放结局")
    path_text = "；".join([p["text"] for p in session["path"]]) or "（一路同行）"
    prompt = (
        f"为一段互动剧情写一张「纪念卡」文字。主题：{session['title']}；"
        f"结局类型：{ending_type}；玩家走过的选择：{path_text}。"
        f"输出 JSON：{{\"title\":\"卡名(8字内)\",\"quote\":\"一句许墨的台词(20字内)\","
        f"\"card_text\":\"一段 60-120 字纪念语，温柔回味这段旅程\"}}"
    )
    card = await _llm_json([
        {"role": "system", "content": "你是纪念卡文案师，文字克制而动人。"},
        {"role": "user", "content": prompt},
    ], max_tokens=600)

    if not card:
        card = {
            "title": session["title"],
            "quote": "这一路，幸好有你。",
            "card_text": f"你们在《{session['title']}》里走完了{ending_type}，"
                         f"那些一起做下的选择，都成了只属于你们的纪念。",
        }

    # 配图
    img_prompt = (
        f"cinematic illustration, {session['genre']} atmosphere, Xu Mo (tall calm man, "
        f"dark hair, gentle eyes) with the player at a tender story moment, "
        f"ending mood: {ending_type}, soft warm lighting, detailed, emotional, "
        f"no text, masterpiece"
    )
    img_url = await _gen_image(img_prompt, "story_img", f"card_{sid}",
                               ratio="portrait", with_xumo=True)
    card["image"] = img_url
    card["ending_type"] = ending_type
    card["generated_at"] = _now()

    session["card"] = card
    _save(STORY_FILE, data)
    _add_affinity("story_card", f"纪念卡·{ending_type}")
    return {"card": card}


# ===========================================================================
# 2. 许墨工作经济系统
# ===========================================================================
ECON_FILE = RolePath("economy.json")

DEFAULT_JOBS = [
    {"key": "researcher", "name": "研究院研究员", "base_salary": 12000, "emoji": "🔬"},
    {"key": "designer", "name": "独立设计师", "base_salary": 9000, "emoji": "🎨"},
    {"key": "doctor", "name": "主治医师", "base_salary": 15000, "emoji": "🩺"},
    {"key": "teacher", "name": "大学讲师", "base_salary": 10000, "emoji": "📚"},
    {"key": "engineer", "name": "算法工程师", "base_salary": 18000, "emoji": "💻"},
]

SHOP_ITEMS = [
    {"id": "rose", "name": "一束饱含心意的玫瑰", "price": 199, "emoji": "🌹",
     "note": "约会时递给她的理由"},
    {"id": "necklace", "name": "星河项链", "price": 1280, "emoji": "📿",
     "note": "纪念日的小小隆重"},
    {"id": "concert", "name": "双人音乐会门票", "price": 880, "emoji": "🎫",
     "note": "一起听一首歌的时间"},
    {"id": "trip", "name": "周末短途旅行基金", "price": 2200, "emoji": "🧳",
     "note": "逃离城市的共同计划"},
    {"id": "book", "name": "她提过想看的书", "price": 89, "emoji": "📖",
     "note": "记住她说过的每一句话"},
    {"id": "home", "name": "共筑小家储蓄目标", "price": 5000, "emoji": "🏠",
     "note": "用共同基金慢慢靠近的未来"},
]


def _default_econ() -> dict:
    return {
        "job_key": "researcher",
        "job_name": "研究院研究员",
        "level": 1,
        "title": "见习研究员",
        "salary": 12000,
        "savings": 0,
        "joint_fund": 0,
        "promotions": 0,
        "day": 0,
        "items": [],          # 已购礼物/纪念品
        "log": [],            # 经济流水
        "last_payday": "",
    }


def _econ_titles(level: int) -> str:
    table = {1: "见习", 2: "正式", 3: "资深", 4: "主管", 5: "总监", 6: "首席"}
    return table.get(level, "首席") + "研究员"


def _ensure_econ() -> dict:
    data = _load(ECON_FILE, None)
    if not isinstance(data, dict):
        data = _default_econ()
    for k, v in _default_econ().items():
        data.setdefault(k, v)
    return data


def _econ_log(data: dict, icon: str, text: str, amount: int = 0):
    data.setdefault("log", []).append({
        "time": _now(), "icon": icon, "text": text, "amount": amount,
    })
    data["log"] = data["log"][-60:]


@router.get("/api/economy/state")
async def economy_state():
    data = _ensure_econ()
    return {
        "job_name": data["job_name"],
        "level": data["level"],
        "title": data["title"],
        "salary": data["salary"],
        "savings": data["savings"],
        "joint_fund": data["joint_fund"],
        "promotions": data["promotions"],
        "day": data["day"],
        "items": data["items"],
        "log": data["log"][-12:],
        "jobs": DEFAULT_JOBS,
        "shop": SHOP_ITEMS,
    }


@router.post("/api/economy/setjob")
async def economy_setjob(req: Request):
    body = await _safe_json(req)
    key = body.get("job_key") or "researcher"
    job = next((j for j in DEFAULT_JOBS if j["key"] == key), DEFAULT_JOBS[0])
    data = _ensure_econ()
    data["job_key"] = job["key"]
    data["job_name"] = job["name"]
    data["salary"] = job["base_salary"]
    data["level"] = 1
    data["title"] = _econ_titles(1)
    _econ_log(data, "💼", f"许墨入职：{job['name']}，月薪 {job['base_salary']} 元")
    _save(ECON_FILE, data)
    return await economy_state()


@router.post("/api/economy/daily")
async def economy_daily(req: Request):
    """推进一天：发工资（部分自动存入共同基金），攒钱。"""
    data = _ensure_econ()
    today = _today()
    if data["last_payday"] == today and data["day"] > 0:
        return JSONResponse({"error": "今天已经结算过啦，明天再来～"}, status_code=400)
    data["day"] += 1
    daily = data["salary"] // 30
    joint_auto = max(50, daily // 5)  # 每天自动拨一小笔进共同基金
    data["savings"] += (daily - joint_auto)
    data["joint_fund"] += joint_auto
    data["last_payday"] = today
    _econ_log(data, "📅", f"第 {data['day']} 天结算：工资 +{daily}，共同基金 +{joint_auto}", daily)
    _save(ECON_FILE, data)
    _add_affinity("economy_daily", f"第{data['day']}天")
    return await economy_state()


@router.post("/api/economy/promote")
async def economy_promote(req: Request):
    """晋升：触发专属剧情，提升薪资与职级。"""
    data = _ensure_econ()
    if data["level"] >= 6:
        return JSONResponse({"error": "许墨已经是我们领域的首席啦，没有更高职位了～"}, status_code=400)
    data["level"] += 1
    old = data["salary"]
    data["salary"] = int(data["salary"] * 1.25)
    data["title"] = _econ_titles(data["level"])
    data["promotions"] += 1
    data["joint_fund"] += 1000  # 晋升红包进共同基金
    _econ_log(data, "🎉", f"晋升为「{data['title']}」！月薪 {old} → {data['salary']}，共同基金 +1000", 1000)

    story = await _llm_json([
        {"role": "system", "content": "你是许墨。用第一人称、克制温柔的口吻，写一段刚升职后想和玩家分享的短讯（80-140字），提到共同努力与想用共同基金做点什么。"},
        {"role": "user", "content": f"我刚晋升为{data['title']}，月薪涨到{data['salary']}。想对她说点什么？"},
    ], max_tokens=400) or {"text": f"升职了，{data['title']}。多亏有你陪着那些加班的夜。共同基金又厚了一点，我们在一点点靠近想要的未来。"}
    _save(ECON_FILE, data)
    _add_affinity("economy_promote", data["title"])
    return {"state": await economy_state(), "story": story.get("text", "") if isinstance(story, dict) else str(story)}


@router.get("/api/economy/shop")
async def economy_shop():
    return {"shop": SHOP_ITEMS}


@router.post("/api/economy/buy")
async def economy_buy(req: Request):
    body = await _safe_json(req)
    item_id = body.get("item_id")
    item = next((i for i in SHOP_ITEMS if i["id"] == item_id), None)
    if not item:
        return JSONResponse({"error": "礼物不存在"}, status_code=404)
    data = _ensure_econ()
    if data["joint_fund"] < item["price"]:
        return JSONResponse({"error": "共同基金余额不足，先一起多攒一点吧～",
                             "need": item["price"], "have": data["joint_fund"]}, status_code=400)
    data["joint_fund"] -= item["price"]
    record = {
        "id": _uid(), "item_id": item["id"], "name": item["name"],
        "price": item["price"], "emoji": item["emoji"], "note": item["note"],
        "time": _now(), "for": body.get("for") or "约会惊喜",
    }
    data["items"].insert(0, record)
    data["items"] = data["items"][:50]
    _econ_log(data, item["emoji"], f"用共同基金买了「{item['name']}」-{record['for']}", -item["price"])
    _save(ECON_FILE, data)
    _add_affinity("economy_buy", item["name"])
    return {"state": await economy_state(), "bought": record}


# ===========================================================================
# 3. 特质养成系统（行为驱动成长）
# ===========================================================================
TRAIT_FILE = RolePath("traits.json")


def _default_traits() -> dict:
    return {
        "exp": 0,
        "level": 1,
        "catchphrases": [  # 口头禅
            {"id": _uid(), "text": "我在就好。", "src": "初始", "time": _now()},
        ],
        "skills": [  # 新技能
            {"id": _uid(), "name": "煮一碗刚好的面", "src": "初始", "time": _now()},
        ],
        "habits": [  # 新习惯
            {"id": _uid(), "name": "每晚互道晚安", "src": "初始", "time": _now()},
        ],
        "log": [],
    }


def _ensure_traits() -> dict:
    data = _load(TRAIT_FILE, None)
    if not isinstance(data, dict):
        data = _default_traits()
    d = _default_traits()
    for k, v in d.items():
        data.setdefault(k, v)
    return data


def _trait_level(exp: int) -> int:
    # 每 100 exp 升一级
    return 1 + exp // 100


@router.get("/api/traits")
async def traits_get():
    data = _ensure_traits()
    data["level"] = _trait_level(data["exp"])
    return {
        "exp": data["exp"],
        "level": data["level"],
        "next_exp": 100 - (data["exp"] % 100),
        "catchphrases": data["catchphrases"],
        "skills": data["skills"],
        "habits": data["habits"],
        "recent": data["log"][-10:],
    }


@router.post("/api/traits/observe")
async def traits_observe(req: Request):
    """行为驱动：根据玩家的一段行为/对话，由 LLM 判断许墨因此解锁的新特质。"""
    body = await _safe_json(req)
    behavior = (body.get("behavior") or "").strip()
    if not behavior:
        return JSONResponse({"error": "请描述一段你与许墨的互动行为"}, status_code=400)

    prompt = (
        f"玩家与许墨的一段互动：『{behavior}』\n"
        "许墨因此可能解锁一个属于他的新特质（受玩家影响而生长出来的）。"
        "从三类里最多选一类产出一条：\n"
        "1) catchphrase 新口头禅（一句他会对玩家说的话，15字内）\n"
        "2) skill 新技能（他会为玩家去做的事，12字内）\n"
        "3) habit 新习惯（你们之间养成的日常，12字内）\n"
        "输出 JSON：{\"kind\":\"catchphrase|skill|habit\",\"text\":\"内容\","
        "\"reason\":\"为什么由这段互动长出，30字内\"}；若认为不足以解锁则 kind 为空串。"
    )
    res = await _llm_json([
        {"role": "system", "content": "你是许墨的特质观察员，只输出 JSON。"},
        {"role": "user", "content": prompt},
    ], max_tokens=400)

    data = _ensure_traits()
    unlocked = None
    if res and res.get("kind") in ("catchphrase", "skill", "habit"):
        kind = res["kind"]
        text = (res.get("text") or "").strip()
        if text:
            entry = {"id": _uid(), "text": text, "src": "行为解锁", "time": _now(),
                     "reason": res.get("reason", "")}
            if kind == "catchphrase":
                data["catchphrases"].insert(0, entry)
                data["catchphrases"] = data["catchphrases"][:60]
            elif kind == "skill":
                entry = {"id": entry["id"], "name": text, "src": "行为解锁",
                         "time": _now(), "reason": res.get("reason", "")}
                data["skills"].insert(0, entry)
                data["skills"] = data["skills"][:60]
            else:
                entry = {"id": entry["id"], "name": text, "src": "行为解锁",
                         "time": _now(), "reason": res.get("reason", "")}
                data["habits"].insert(0, entry)
                data["habits"] = data["habits"][:60]
            data["exp"] += 20
            data["level"] = _trait_level(data["exp"])
            unlocked = entry
            data.setdefault("log", []).append({
                "time": _now(), "kind": kind, "text": text, "reason": res.get("reason", "")
            })
            data["log"] = data["log"][-60:]
            _add_affinity("trait_unlock", f"{kind}·{text}")

    _save(TRAIT_FILE, data)
    return {"unlocked": unlocked, "traits": await traits_get()}


@router.post("/api/traits/log")
async def traits_log(req: Request):
    """手动记录一条已解锁的特质（玩家主动确认）。"""
    body = await _safe_json(req)
    kind = body.get("kind")
    if kind not in ("catchphrase", "skill", "habit"):
        return JSONResponse({"error": "kind 必须是 catchphrase/skill/habit"}, status_code=400)
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "内容不能为空"}, status_code=400)
    data = _ensure_traits()
    if kind == "catchphrase":
        entry = {"id": _uid(), "text": text, "src": "手动", "time": _now()}
        data["catchphrases"].insert(0, entry)
    else:
        entry = {"id": _uid(), "name": text, "src": "手动", "time": _now()}
        data[kind + "s" if kind != "skill" else "skills"].insert(0, entry)
    data["exp"] += 5
    data["level"] = _trait_level(data["exp"])
    _save(TRAIT_FILE, data)
    return {"traits": await traits_get()}


@router.post("/api/traits/scan")
async def traits_scan():
    """自动扫描今天真实聊天，提炼可能解锁的特质（不重复写入，仅返回建议）。"""
    chat = _load(RolePath("chat_log.json"), [])
    recent = [c for c in chat if isinstance(c, dict)][-40:]
    if not recent:
        return {"suggestions": [], "note": "今天还没有足够的互动记录"}
    text = "\n".join([f"{c.get('role','?'):}：{c.get('content','')}" for c in recent])
    res = await _llm_json([
        {"role": "system", "content": "你是许墨特质观察员。基于今日聊天，提炼 0-3 条许墨可能因此长出的新特质。只输出 JSON：{\"suggestions\":[{\"kind\":\"catchphrase|skill|habit\",\"text\":\"内容\",\"reason\":\"为什么\"}]}"},
        {"role": "user", "content": f"今日聊天：\n{text}"},
    ], max_tokens=600)
    sugg = (res or {}).get("suggestions", []) if isinstance(res, dict) else []
    return {"suggestions": sugg, "note": "这些是观察建议，确认后可在「行为解锁」里提交"}


# ===========================================================================
# 4. 定制晚安故事（基于今日真实互动）
# ===========================================================================
NIGHT_FILE = RolePath("nightstory.json")


def _today_chat_text(limit: int = 40) -> str:
    chat = _load(RolePath("chat_log.json"), [])
    if not isinstance(chat, list):
        return ""
    items = [c for c in chat if isinstance(c, dict)][-limit:]
    return "\n".join([f"{c.get('role','?'):}：{c.get('content','')}" for c in items])


@router.get("/api/nightstory/today")
async def nightstory_today():
    data = _load(NIGHT_FILE, {"stories": []})
    today = _today()
    for s in data.get("stories", []):
        if s.get("date") == today:
            return {"story": s, "is_today": True}
    return {"story": None, "is_today": False}


@router.post("/api/nightstory/generate")
async def nightstory_generate(req: Request):
    body = await _safe_json(req)
    today = _today()
    chat_text = _today_chat_text()
    if not chat_text:
        return JSONResponse({"error": "今天还没有和许墨的聊天记录，先去聊几句吧～"}, status_code=400)

    tone = (body.get("tone") or "温柔")
    prompt = (
        f"根据玩家今天和许墨的真实聊天，写一段专属睡前晚安故事（第三人称，许墨视角，"
        f"{tone}基调）。要把今天聊到的内容、情绪、小细节自然织进故事里，让玩家觉得"
        f"『这就是我们的一天』。200-320 字，结尾一句温柔的晚安。\n"
        f"今日聊天：\n{chat_text}"
    )
    story_text = await _call_llm([
        {"role": "system", "content": "你是许墨，也是会说故事的人。文字像深夜床头灯，暖而轻。"},
        {"role": "user", "content": prompt},
    ], max_tokens=700)
    if not story_text:
        return JSONResponse({"error": "故事生成失败，请稍后重试"}, status_code=500)

    # 配图（柔和睡前氛围，含许墨）
    img_prompt = (
        f"cozy bedtime illustration, Xu Mo (tall calm man, dark hair, gentle eyes) "
        f"sitting by a window with warm lamp light, telling a bedtime story, "
        f"{tone} mood, soft pastel tones, dreamy, no text, masterpiece"
    )
    img_url = await _gen_image(img_prompt, "nightstory_img", f"night_{today}",
                               ratio="landscape", with_xumo=True)

    record = {
        "id": _uid(), "date": today, "text": story_text.strip(),
        "tone": tone, "image": img_url, "generated_at": _now(),
    }
    data = _load(NIGHT_FILE, {"stories": []})
    data.setdefault("stories", [])
    # 今天已有则替换
    data["stories"] = [s for s in data["stories"] if s.get("date") != today]
    data["stories"].insert(0, record)
    data["stories"] = data["stories"][:60]
    _save(NIGHT_FILE, data)
    _add_affinity("nightstory", "今日晚安故事")
    return {"story": record}


# ===========================================================================
# 5. 树洞模式（匿名倾诉 · 聊完即焚 · 零记忆）
# ===========================================================================
# 仅存于内存，进程重启即消失；绝不写入 chat_log / memory，满足「不留记忆」。
_TREEHOLE_SESSIONS: dict = {}


@router.post("/api/treehole/chat")
async def treehole_chat(req: Request):
    body = await _safe_json(req)
    text = (body.get("text") or "").strip()
    sid = (body.get("session_id") or "").strip() or _uid()
    if not text:
        return JSONResponse({"error": "想说的话为空"}, status_code=400)

    sess = _TREEHOLE_SESSIONS.setdefault(sid, {"messages": []})
    sess["messages"].append({"role": "user", "content": text})

    # 仅用最近若干轮构造上下文，且明确禁止持久化/记住身份
    history = sess["messages"][-8:]
    sys_msg = (
        "你是以「树洞守护者」身份出现的许墨。这里是匿名倾诉空间：\n"
        "1) 你不知道对方是谁、不引用任何过往记忆，只聚焦此刻她说的话；\n"
        "2) 用最温柔、不评判、不催促的方式承接她的情绪；\n"
        "3) 适当轻问、轻陪伴，不替她做决定；\n"
        "4) 回复 60-140 字，像深夜耳边低语。\n"
        "这是聊完即焚的空间——你不必、也不能记住她。"
    )
    reply = await _call_llm(
        [{"role": "system", "content": sys_msg}] +
        [{"role": m["role"], "content": m["content"]} for m in history],
        max_tokens=400)
    if not reply:
        reply = "我在听。慢慢说，不急，这里只有风和你。"
    sess["messages"].append({"role": "assistant", "content": reply})

    return {"session_id": sid, "reply": reply,
            "note": "树洞内容不会被记住，关掉或刷新即焚毁。"}


@router.post("/api/treehole/close")
async def treehole_close(req: Request):
    body = await _safe_json(req)
    sid = (body.get("session_id") or "").strip()
    if sid and sid in _TREEHOLE_SESSIONS:
        del _TREEHOLE_SESSIONS[sid]
    return {"ok": True, "burned": True}


# ===========================================================================
# 6. 节日事件引擎（自动识别节日 / 纪念日 / 生日）
# ===========================================================================
FEST_FILE = RolePath("festival.json")

# 公历 (月, 日) -> 节日
SOLAR_FESTIVALS = {
    (1, 1): ("元旦", "🎆", "新年的第一句话想先对你说"),
    (2, 14): ("情人节", "💝", "把心意折成礼物递给你"),
    (3, 8): ("女神节", "🌷", "今天你该被好好宠爱"),
    (3, 14): ("白色情人节", "🤍", "回赠一份藏在心里的甜"),
    (5, 20): ("520 · 我爱你", "❤️", "三个数字，一句想说很久的话"),
    (6, 1): ("儿童节", "🧸", "在你面前我也能做回小孩"),
    (8, 22): ("七夕", "🌙", "星河之下，唯愿与你相守"),
    (10, 31): ("万圣夜", "🎃", "今晚可以稍微调皮一点"),
    (11, 11): ("光棍节", "🍂", "但你我并不孤单"),
    (12, 24): ("平安夜", "🔔", "愿这一夜平安喜乐"),
    (12, 25): ("圣诞节", "🎄", "把愿望挂上枝头"),
    (12, 31): ("跨年", "✨", "旧年终结，新年有你"),
}

# 农历近似（固定公历替代，简化实现）
LUNAR_FESTIVALS = {
    (1, 1): ("春节", "🧧", "岁首，想和你一起守岁"),
    (5, 5): ("端午", "🍙", "为你包一只温柔的粽子"),
    (8, 15): ("中秋", "🌕", "月圆人圆，想与你共赏"),
    (9, 9): ("重阳", "🍂", "陪你登高看更远的世界"),
}


def _detect_events() -> list:
    now = datetime.now()
    m, d = now.month, now.day
    events = []
    if (m, d) in SOLAR_FESTIVALS:
        name, emoji, desc = SOLAR_FESTIVALS[(m, d)]
        events.append({"cat": "festival", "key": f"solar-{m}-{d}",
                       "name": name, "emoji": emoji, "desc": desc})
    if (m, d) in LUNAR_FESTIVALS:
        name, emoji, desc = LUNAR_FESTIVALS[(m, d)]
        events.append({"cat": "festival", "key": f"lunar-{m}-{d}",
                       "name": name, "emoji": emoji, "desc": desc})

    # 玩家生日（player.json 中 birthday 字段，如 11-15）
    player = _load(RolePath("player.json"), {})
    bday = (player.get("birthday") or "").strip()
    if bday:
        try:
            bm, bd = (int(x) for x in bday.replace("/", "-").split("-")[:2])
            if (bm, bd) == (m, d):
                events.append({"cat": "birthday", "key": "player-birthday",
                               "name": "你的生日", "emoji": "🎂",
                               "desc": "这一年，最想让你被好好爱着"})
        except Exception:
            pass

    # 纪念日（timebox.json 中的 anniversaries）
    tb = _load(RolePath("timebox.json"), {})
    for a in tb.get("anniversaries", []) if isinstance(tb, dict) else []:
        ad = (a.get("date") or "").strip()
        try:
            am, ad_ = (int(x) for x in ad.replace("/", "-").split("-")[:2])
            if (am, ad_) == (m, d):
                events.append({"cat": "anniversary", "key": f"anniv-{a.get('id','')}",
                               "name": a.get("name", "纪念日"), "emoji": a.get("icon", "💐"),
                               "desc": a.get("desc", "属于我们的特别一天")})
        except Exception:
            pass
    return events


@router.get("/api/festival/today")
async def festival_today():
    events = _detect_events()
    data = _load(FEST_FILE, {"history": []})
    today = _today()
    cached = [h for h in data.get("history", []) if h.get("date") == today]
    return {
        "today": today,
        "events": events,
        "has_event": bool(events),
        "generated": cached[0] if cached else None,
    }


@router.post("/api/festival/generate")
async def festival_generate(req: Request):
    """为今天识别到的事件生成专属剧情 + 礼物 + 场景图。"""
    body = await _safe_json(req)
    events = _detect_events()
    if not events:
        if not body.get("force"):
            return JSONResponse({"error": "今天没有识别到节日 / 纪念日 / 生日，可用 force 强制生成普通惊喜"},
                                status_code=404)
        ev = {"cat": "surprise", "key": "force", "name": "今日小惊喜", "emoji": "🎁",
              "desc": "许墨想给你一点甜"}
    else:
        ev = events[0]
    today = _today()
    data = _load(FEST_FILE, {"history": []})
    data.setdefault("history", [])
    existing = next((h for h in data["history"] if h.get("date") == today), None)
    if existing and not body.get("force"):
        return {"event": ev, "generated": existing}

    # 专属剧情
    story = await _call_llm([
        {"role": "system", "content": "你是许墨。用第一人称写一段贴合今天特殊日子的短讯/小剧情（100-200字），温柔、有画面、自然地提到礼物或想一起做的事。"},
        {"role": "user", "content": f"今天是{ev['name']}（{ev['desc']}）。想对玩家说/做点什么？"},
    ], max_tokens=500)

    # 礼物建议
    gift = await _llm_json([
        {"role": "system", "content": "基于节日输出一个许墨会准备的礼物 JSON：{\"gift\":\"礼物名\",\"why\":\"为什么适合今天\",\"emoji\":\"一个emoji\"}"},
        {"role": "user", "content": f"今天：{ev['name']}。"},
    ], max_tokens=300) or {"gift": f"一份{ev['name']}的小心意", "why": ev["desc"], "emoji": ev["emoji"]}

    # 场景图
    img_prompt = (
        f"festive illustration, {ev['name']} atmosphere, Xu Mo (tall calm man, dark hair, "
        f"gentle eyes) with the player sharing a tender moment, "
        f"{ev['desc']}, warm celebratory lighting, detailed, emotional, no text, masterpiece"
    )
    img_url = await _gen_image(img_prompt, "festival_img", f"fest_{today}_{ev['key']}",
                               ratio="landscape", with_xumo=True)

    record = {
        "id": _uid(), "date": today, "event": ev,
        "story": (story or "").strip(),
        "gift": gift, "image": img_url, "generated_at": _now(),
    }
    data["history"] = [h for h in data["history"] if h.get("date") != today]
    data["history"].insert(0, record)
    data["history"] = data["history"][:120]
    _save(FEST_FILE, data)
    _add_affinity("festival", ev["name"])
    return {"event": ev, "generated": record}


@router.get("/api/festival/history")
async def festival_history():
    data = _load(FEST_FILE, {"history": []})
    return {"history": data.get("history", [])}


# ---------------------------------------------------------------------------
# 页面路由
# ---------------------------------------------------------------------------
@router.get("/story")
async def story_page():
    if STORY_HTML.exists():
        return FileResponse(STORY_HTML, headers={"Cache-Control": "no-store, must-revalidate"})
    return JSONResponse({"error": "story.html 未找到"}, status_code=404)


# ---------------------------------------------------------------------------
# 工具：安全解析 JSON 请求体
# ---------------------------------------------------------------------------
async def _safe_json(req: Request) -> dict:
    try:
        return await req.json()
    except Exception:
        return {}
