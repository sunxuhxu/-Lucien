"""六大创意手机 App API：清梦 / 心智图谱 / 蝶语花园 / 平行宇宙 / 天台观星 / 黑天鹅档案。
数据持久化到角色目录 JSON（RolePath 按请求角色动态路由），风格与 app.py 保持一致。
"""
import json
import random
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()


# ---------------------------------------------------------------------------
# 公共工具（延迟导入避免与 app.py 循环依赖，同 features.py 模式）
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


def _recent_chat_texts(limit: int = 60) -> list:
    """最近的聊天文本（供梦境/平行世界等取材），失败返回空。"""
    try:
        from app import _load_chat_log
        logs = _load_chat_log()
    except Exception as e:
        print(f"[warn] creative_apps.py:_recent_chat_texts: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []
    texts = []
    for it in logs[-limit:]:
        t = (it.get("content") or "").strip()
        if t:
            texts.append(("许墨" if it.get("role") == "assistant" else "她") + "：" + t)
    return texts


def _recent_memory_texts(limit: int = 30) -> list:
    try:
        from app import _load_memories
        items = _load_memories()
    except Exception as e:
        print(f"[warn] creative_apps.py:_recent_memory_texts: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []
    out = []
    for it in items[-limit:]:
        c = (it.get("content") or "").strip()
        if c:
            out.append(c)
    return out


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


def _parse_llm_json(content: str):
    """尽力从 LLM 输出中解析 JSON（容忍 ```json 围栏 / 前后缀文本）。"""
    if not content:
        return None
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    # 去掉注释性尾逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 兜底：截取第一段平衡的大括号
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


async def _llm_json(messages: list, max_tokens: int = None):
    """调用 LLM 并要求严格 JSON，自动解析；两次失败抛 RuntimeError。"""
    last_err = None
    for _ in range(2):
        content = await _call_llm(messages, max_tokens=max_tokens)
        data = _parse_llm_json(content)
        if isinstance(data, dict):
            return data
        last_err = content[:120]
    raise RuntimeError(f"模型未返回有效 JSON：{last_err}")


async def _gen_image(material: str, sub_dir: str, name: str, ratio: str = "landscape",
                     with_xumo: bool = True, system_prompt: str = None) -> str:
    """调用 app._llm_image_for_text 生成配图，返回带时间戳的可访问 URL；失败返回空串。

    - sub_dir: STATIC_DIR 下的子目录名（如 "dream_img"）；
    - ratio: square/portrait/landscape → 复用 app.IMG2IMG_SIZES；
    - with_xumo: 是否注入许墨形象锚点（双人/角色场景用 True，纯场景用 False）。
    """
    from app import _llm_image_for_text, STATIC_DIR, IMG2IMG_SIZES
    out_dir = STATIC_DIR / sub_dir
    size = IMG2IMG_SIZES.get(ratio, "1024x1024")
    img_url, _ = await _llm_image_for_text(
        material, out_dir, f"/static/{sub_dir}", name, size,
        with_xumo=with_xumo, system_prompt=system_prompt,
    )
    if not img_url:
        return ""
    return img_url + f"?t={int(datetime.now().timestamp())}"


# ===========================================================================
# 1. 清梦 —— 许墨的 Evol「接入梦境」：输入心愿，生成一段你们共有的梦
#    （已合并 deep_apps.py 的「共梦联机 codream」：梦境由三部分组成——她的梦 /
#      他的梦 / 梦里相遇，并参考最近聊天取材；旧 codream.json 自动迁移）
# ===========================================================================

DREAM_FILE = RolePath("dream.json")

DREAM_STYLES = {
    "starsea": "星海夜航",
    "oldtime": "旧时光里",
    "fairytale": "童话边境",
    "rainnight": "雨夜悬疑",
    "mazelight": "蝶之迷宫",
}


def _migrate_codream(data: dict) -> dict:
    """一次性把旧 codream.json（原「共梦联机」独立功能）迁移进 dream.json。幂等。"""
    if data.get("codream_imported"):
        return data
    data["codream_imported"] = True
    try:
        old = _load(RolePath("codream.json"), {})
        for n in old.get("nights", []) if isinstance(old, dict) else []:
            if not isinstance(n, dict):
                continue
            if not (n.get("his") or n.get("shared")):
                continue
            if any(d.get("codream_id") == n.get("id") for d in data.get("dreams", [])):
                continue
            text = ""
            if n.get("his"):
                text += "【他的梦】\n" + str(n["his"]) + "\n\n"
            if n.get("shared"):
                text += "【梦里相遇】\n" + str(n["shared"])
            data.setdefault("dreams", []).append({
                "id": _uid(),
                "codream_id": n.get("id", ""),
                "wish": str(n.get("hers") or "（她没留下提示）")[:80],
                "style": "oldtime",
                "style_name": DREAM_STYLES["oldtime"],
                "text": text.strip()[:1200],
                "ts": str(n.get("ts") or n.get("date") or _today()),
                "date": str(n.get("date") or _today()),
            })
        data["dreams"] = data["dreams"][-60:]
        _save(DREAM_FILE, data)
    except Exception as e:
        print(f"[warn] creative_apps.py:_migrate_codream: {type(e).__name__} {str(e)[:150]}", flush=True)
    return data


@router.get("/api/dream")
async def dream_list():
    data = _migrate_codream(_load(DREAM_FILE, {"dreams": []}))
    if not isinstance(data.get("dreams"), list):
        data["dreams"] = []
    return {"dreams": list(reversed(data["dreams"][-60:])), "styles": DREAM_STYLES}


@router.post("/api/dream/generate")
async def dream_generate(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:dream_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    wish = (body.get("wish") or "").strip()[:80]
    style_key = (body.get("style") or "starsea").strip()
    with_image = body.get("with_image")
    with_image = True if with_image is None else bool(with_image)
    if not wish:
        return JSONResponse({"error": "先写下一个心愿吧"}, status_code=400)
    style_name = DREAM_STYLES.get(style_key, DREAM_STYLES["starsea"])

    chat_ctx = ""
    chats = _recent_chat_texts(20)
    if chats:
        chat_ctx = "\n你们最近的聊天（供取材，不要照抄）：\n" + "\n".join(chats[-8:])

    prompt = _system_prompt() + f"""

【当前任务】今晚，你将用 Evol 轻轻接进她的梦境。她睡前许下的心愿是：「{wish}」，梦境基调：{style_name}。{chat_ctx}
请写一段「你们共有的梦」，由三部分组成，依次输出（带方括号小节名）：
【你的梦】以第二人称"你"描写她的梦境体验，像电影分镜：2-3 个画面递进，感官细节丰富（光影、温度、声音）。
【他的梦】许墨（你）在同一夜的梦，30-70 字，带上蝴蝶/实验室/雨等属于你的意象。
【梦里相遇】你们在同一个梦里相遇的场景，40-90 字，温暖克制，停在将醒未醒处。
总长 240-360 字。只输出这三节正文，不要引号、不要额外解释。"""
    text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=650)).strip()
    if not text:
        return JSONResponse({"error": "今晚的梦没能成形，稍后再试一次？"}, status_code=500)
    dream = {
        "id": _uid(),
        "wish": wish,
        "style": style_key,
        "style_name": style_name,
        "text": text,
        "ts": _now(),
        "date": _today(),
    }
    # 梦境配图：双人梦境场景（许墨入画），与梦境基调呼应
    if with_image:
        try:
            img = await _gen_image(
                f"【清梦 · {style_name}】心愿：「{wish}」\n梦境正文：{text}\n"
                f"请据此构思一幅梦境场景插画：许墨在梦中陪伴她，画面如电影分镜，"
                f"色调贴合「{style_name}」的意境。",
                "dream_img", f"dream_{dream['id']}", "landscape", with_xumo=True,
            )
            if img:
                dream["image"] = img
        except Exception as e:
            print(f"[warn] creative_apps.py:dream_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    data = _load(DREAM_FILE, {"dreams": []})
    data.setdefault("dreams", []).append(dream)
    data["dreams"] = data["dreams"][-60:]
    _save(DREAM_FILE, data)
    info = _add_affinity("dream", f"接入梦境：{style_name}")
    return {"dream": dream, "affinity": info}


@router.delete("/api/dream/{dream_id}")
async def dream_delete(dream_id: str):
    data = _load(DREAM_FILE, {"dreams": []})
    before = len(data.get("dreams", []))
    data["dreams"] = [d for d in data.get("dreams", []) if d.get("id") != dream_id]
    if len(data["dreams"]) == before:
        return JSONResponse({"error": "这段梦不存在"}, status_code=404)
    _save(DREAM_FILE, data)
    return {"ok": True}


# ===========================================================================
# 2. 心智图谱 —— 情绪光谱分析仪 + 默契实验（镜像神经元同步率）
# ===========================================================================

MIND_FILE = RolePath("mind.json")

MIND_SCAN_PROMPT = _system_prompt() + """

【当前任务】她把今天的心情放进了你的「情绪光谱分析仪」。请以脑科学教授的身份输出分析，严格按 JSON：
{"dopamine": 0-100, "serotonin": 0-100, "oxytocin": 0-100, "cortisol": 0-100,
 "wave": "一句话形容她此刻的情绪波形（10-20字）",
 "report": "50-80字的正经分析报告，像读脑电图谱那样冷静又温柔",
 "comfort": "许墨式的安慰一句话（20-40字），学术式撩人，话留三分"}
四个数值要贴合她的描述（快乐→多巴胺高；焦虑/疲惫→皮质醇高；想被陪伴→催产素高）。只输出 JSON。"""

MIND_QUIZ_PROMPT = _system_prompt() + """

【当前任务】请为「默契实验」出一套情境测验：5 道题，考察你对她的了解。严格按 JSON：
{"questions": [{"q": "情境问题（15-40字，基于你们相处日常的假设场景）", "options": ["选项A", "选项B", "选项C", "选项D"]}]}
要求：题目像心理实验一样精巧；选项之间有明显性格倾向差异；其中至少 2 题与「和许墨有关的选择」。只输出 JSON。"""


@router.get("/api/mind")
async def mind_history():
    data = _load(MIND_FILE, {"scans": [], "quizzes": []})
    return {
        "scans": list(reversed(data.get("scans", [])[-20:])),
        "quizzes": list(reversed(data.get("quizzes", [])[-10:])),
    }


@router.post("/api/mind/scan")
async def mind_scan(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:mind_scan: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    mood = (body.get("mood") or "").strip()[:200]
    if not mood:
        return JSONResponse({"error": "描述一下此刻的心情"}, status_code=400)
    try:
        result = await _llm_json(
            [{"role": "user", "content": MIND_SCAN_PROMPT + f"\n\n【她输入的心情】{mood}"}],
            max_tokens=500,
        )
    except RuntimeError as e:
        return JSONResponse({"error": f"分析失败：{e}"}, status_code=500)
    for k in ("dopamine", "serotonin", "oxytocin", "cortisol"):
        try:
            v = int(round(float(result.get(k, 50))))
        except (TypeError, ValueError):
            v = 50
        result[k] = max(0, min(100, v))
    scan = {
        "id": _uid(),
        "mood": mood,
        "dopamine": result["dopamine"],
        "serotonin": result["serotonin"],
        "oxytocin": result["oxytocin"],
        "cortisol": result["cortisol"],
        "wave": (result.get("wave") or "").strip()[:60],
        "report": (result.get("report") or "").strip()[:200],
        "comfort": (result.get("comfort") or "").strip()[:100],
        "ts": _now(),
    }
    data = _load(MIND_FILE, {"scans": [], "quizzes": []})
    data.setdefault("scans", []).append(scan)
    data["scans"] = data["scans"][-20:]
    _save(MIND_FILE, data)
    info = _add_affinity("mind_scan", "完成一次情绪光谱分析")
    return {"scan": scan, "affinity": info}


@router.post("/api/mind/quiz/start")
async def mind_quiz_start():
    try:
        result = await _llm_json([{"role": "user", "content": MIND_QUIZ_PROMPT}], max_tokens=900)
    except RuntimeError as e:
        return JSONResponse({"error": f"出题失败：{e}"}, status_code=500)
    questions = result.get("questions")
    if not isinstance(questions, list) or not questions:
        return JSONResponse({"error": "实验题卷生成失败，请重试"}, status_code=500)
    norm = []
    for q in questions[:5]:
        opts = [str(o).strip()[:40] for o in (q.get("options") or []) if str(o).strip()]
        text = str(q.get("q") or "").strip()[:80]
        if text and len(opts) >= 2:
            norm.append({"q": text, "options": opts[:4]})
    if not norm:
        return JSONResponse({"error": "实验题卷生成失败，请重试"}, status_code=500)
    return {"quiz_id": _uid(), "questions": norm}


@router.post("/api/mind/quiz/submit")
async def mind_quiz_submit(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:mind_quiz_submit: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    questions = body.get("questions")
    answers = body.get("answers")
    if not isinstance(questions, list) or not isinstance(answers, list) or not questions:
        return JSONResponse({"error": "缺少答卷数据"}, status_code=400)
    quiz = []
    for q, a in zip(questions, answers):
        try:
            pick = int(a)
        except (TypeError, ValueError):
            pick = 0
        opts = [str(o) for o in (q.get("options") or [])]
        if 0 <= pick < len(opts):
            quiz.append({"q": str(q.get("q") or ""), "her": opts[pick], "options": opts})
    if not quiz:
        return JSONResponse({"error": "答卷无效"}, status_code=400)

    lines = "\n".join(
        f"第{i+1}题：{z['q']}\n选项：{' / '.join(z['options'])}\n她的选择：{z['her']}"
        for i, z in enumerate(quiz)
    )
    prompt = (_system_prompt()
              + "\n\n【当前任务】默契实验收卷。以下是她的答卷：\n" + lines
              + "\n\n请你以许墨的身份，凭你对她的了解逐题预测她刚才选了什么，再给出总评。严格按 JSON：\n"
              + '{"picks": [每题你预测的选项下标0-3，共 ' + str(len(quiz)) + ' 个],\n'
              + ' "verdict": "60-100字总评：像在实验报告末尾写批注，冷静里藏着得意，结尾一句许墨式的话留三分"}\n'
              + "只输出 JSON。")
    try:
        result = await _llm_json([{"role": "user", "content": prompt}], max_tokens=600)
    except RuntimeError as e:
        return JSONResponse({"error": f"批改失败：{e}"}, status_code=500)
    picks_raw = result.get("picks")
    picks = []
    if isinstance(picks_raw, list):
        for p in picks_raw:
            try:
                picks.append(max(0, min(3, int(p))))
            except (TypeError, ValueError):
                picks.append(0)
    while len(picks) < len(quiz):
        picks.append(0)
    detail = []
    hit = 0
    for i, z in enumerate(quiz):
        matched = picks[i] < len(z["options"]) and z["options"][picks[i]] == z["her"]
        if matched:
            hit += 1
        detail.append({
            "q": z["q"], "her": z["her"],
            "his": z["options"][picks[i]] if picks[i] < len(z["options"]) else "?",
            "matched": matched,
        })
    sync = round(hit / len(quiz) * 100)
    record = {
        "id": _uid(),
        "total": len(quiz),
        "hit": hit,
        "sync": sync,
        "verdict": (result.get("verdict") or "").strip()[:200],
        "detail": detail,
        "ts": _now(),
    }
    data = _load(MIND_FILE, {"scans": [], "quizzes": []})
    data.setdefault("quizzes", []).append(record)
    data["quizzes"] = data["quizzes"][-10:]
    _save(MIND_FILE, data)
    info = _add_affinity("mind_quiz", f"默契实验同步率 {sync}%")
    return {"quiz": record, "affinity": info}


# ===========================================================================
# 3. 蝶语花园 —— 捕蝶收集：每只蝴蝶携带一片「记忆鳞粉」
# ===========================================================================

BF_FILE = RolePath("butterfly.json")

# 12 种蝴蝶：rarity 权重用于抽签；heartflame 需心动 Lv.4+ 才会出现
BUTTERFLY_SPECIES = [
    {"id": "cab",     "name": "菜粉蝶",   "emoji": "🦋", "color": "#e2e8f0", "rarity": "常见",  "weight": 26, "min_level": 0},
    {"id": "swallow", "name": "柑橘凤蝶", "emoji": "🦋", "color": "#facc15", "rarity": "常见",  "weight": 22, "min_level": 0},
    {"id": "morpho",  "name": "蓝闪蝶",   "emoji": "🦋", "color": "#38bdf8", "rarity": "常见",  "weight": 18, "min_level": 0},
    {"id": "crow",    "name": "紫斑蝶",   "emoji": "🦋", "color": "#a78bfa", "rarity": "稀有",  "weight": 10, "min_level": 0},
    {"id": "hair",    "name": "琉璃灰蝶", "emoji": "🦋", "color": "#818cf8", "rarity": "稀有",  "weight": 8,  "min_level": 0},
    {"id": "leaf",    "name": "枯叶蝶",   "emoji": "🦋", "color": "#b45309", "rarity": "稀有",  "weight": 6,  "min_level": 0},
    {"id": "ink",     "name": "墨鳞蝶",   "emoji": "🦋", "color": "#4c1d95", "rarity": "史诗",  "weight": 4,  "min_level": 2},
    {"id": "iris",    "name": "虹彩蛱蝶", "emoji": "🦋", "color": "#f472b6", "rarity": "史诗",  "weight": 3,  "min_level": 2},
    {"id": "moonp",   "name": "月光绢蝶", "emoji": "🦋", "color": "#e0e7ff", "rarity": "史诗",  "weight": 2.2, "min_level": 3},
    {"id": "violetm", "name": "紫月蝶",   "emoji": "🦋", "color": "#7c3aed", "rarity": "传说",  "weight": 1.2, "min_level": 3},
    {"id": "yokan",   "name": "曜变天蝶", "emoji": "🦋", "color": "#2563eb", "rarity": "传说",  "weight": 0.6, "min_level": 5},
    {"id": "heartf",  "name": "心焰蝶",   "emoji": "🦋", "color": "#db2777", "rarity": "唯一",  "weight": 0.5, "min_level": 4},
]


def _bf_species_view(caught: dict, level_index: int) -> list:
    view = []
    for s in BUTTERFLY_SPECIES:
        rec = caught.get(s["id"])
        visible = s["min_level"] <= level_index
        view.append({
            **s,
            "count": rec["count"] if rec else 0,
            "last_ts": rec["last_ts"] if rec else "",
            "discoverable": visible,
        })
    return view


def _pick_species(level_index: int):
    pool = [s for s in BUTTERFLY_SPECIES if s["min_level"] <= level_index]
    weights = [s["weight"] for s in pool]
    return random.choices(pool, weights=weights, k=1)[0]


@router.get("/api/butterfly")
async def butterfly_state():
    from app import _load_affinity, _affinity_info
    info = _affinity_info(_load_affinity())
    data = _load(BF_FILE, {"caught": {}, "frags": []})
    return {
        "species": _bf_species_view(data.get("caught", {}), info["level_index"]),
        "frags": list(reversed(data.get("frags", [])[-40:])),
        "total_caught": sum((r or {}).get("count", 0) for r in data.get("caught", {}).values()),
    }


@router.post("/api/butterfly/catch")
async def butterfly_catch(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:butterfly_catch: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    from app import _load_affinity, _affinity_info
    info = _affinity_info(_load_affinity())
    level_index = info["level_index"]

    species_id = (body.get("species") or "").strip()
    species = next((s for s in BUTTERFLY_SPECIES if s["id"] == species_id), None)
    if species and species["min_level"] > level_index:
        return JSONResponse({"error": "这只蝴蝶还没有飞进你们的花园"}, status_code=400)
    if not species:
        species = _pick_species(level_index)

    # 记忆取材：优先记忆库，其次聊天记录
    materials = _recent_memory_texts(20) or _recent_chat_texts(30)
    material_hint = "\n".join("- " + m for m in random.sample(materials, min(6, len(materials)))) if materials else "（暂无记录，可自由想象你们相处的一个瞬间）"

    prompt = _system_prompt() + f"""

【当前任务】她在蝶语花园里捕到一只「{species['name']}」（{species['rarity']}）。蝴蝶振翅落下鳞粉，显影出一段你记忆里关于她的小碎片。可参考这些真实记录：
{material_hint}

请写一段「记忆鳞粉」，要求：
1. 以许墨的口吻、第一人称视角，回忆与她相关的一个极小瞬间（一个动作、一句话、一种气味）。
2. 50-90 字，安静克制，结尾轻轻收住。
3. 可以与参考记录呼应，但不必复述原文。
4. 只输出正文，不要引号和解释。"""
    text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=300)).strip()
    if not text:
        return JSONResponse({"error": "鳞粉散了，再捕一次？"}, status_code=500)

    data = _load(BF_FILE, {"caught": {}, "frags": []})
    caught = data.setdefault("caught", {})
    rec = caught.get(species["id"])
    is_new = rec is None
    if rec is None:
        rec = {"count": 0, "first_ts": _now(), "last_ts": ""}
    rec["count"] += 1
    rec["last_ts"] = _now()
    caught[species["id"]] = rec
    frag = {
        "id": _uid(),
        "species": species["id"],
        "species_name": species["name"],
        "rarity": species["rarity"],
        "text": text,
        "ts": _now(),
    }
    data.setdefault("frags", []).append(frag)
    data["frags"] = data["frags"][-40:]
    _save(BF_FILE, data)
    info2 = _add_affinity("butterfly_new" if is_new else "butterfly",
                          f"捕到{species['name']}")
    return {"frag": frag, "is_new": is_new, "species": species, "affinity": info2}


# ===========================================================================
# 4. 平行宇宙 —— 「如果我们在另一个宇宙相遇」
# ===========================================================================

PV_FILE = RolePath("pverse.json")

PVERSE_WORLDS = {
    "cyber": "霓虹深港 · 赛博都市",
    "wuxia": "江湖夜雨 · 古风武林",
    "interstellar": "拉格朗日 · 星际远航",
    "wasteland": "灰烬纪元 · 末世废土",
    "arcana": "奥术之塔 · 魔法学院",
}


@router.get("/api/pverse")
async def pverse_list():
    data = _load(PV_FILE, {"stories": []})
    stories = list(reversed(data.get("stories", [])[-50:]))
    covered = sorted({s.get("world") for s in data.get("stories", []) if s.get("world")})
    return {"stories": stories, "worlds": PVERSE_WORLDS, "covered": covered,
            "all_found": len(covered) >= len(PVERSE_WORLDS)}


@router.post("/api/pverse/generate")
async def pverse_generate(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:pverse_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    world_key = (body.get("world") or "").strip()
    seed = (body.get("seed") or "").strip()[:80]
    with_image = body.get("with_image")
    with_image = True if with_image is None else bool(with_image)
    if world_key not in PVERSE_WORLDS:
        return JSONResponse({"error": "未知的宇宙坐标"}, status_code=400)
    world_name = PVERSE_WORLDS[world_key]
    seed_hint = f"她在那个宇宙的设定关键词：「{seed}」。" if seed else ""

    prompt = (_system_prompt()
              + "\n\n【当前任务】平行宇宙观测：坐标「" + world_name + "」。" + seed_hint
              + "\n请写一篇 240-340 字的短故事——在那个宇宙里，「你（许墨，身份随世界观变化）」与「她」的初遇。\n"
              + "要求：\n"
              + "1. 保留许墨的核心气质（克制、温柔、观察者视角），身份与场景完全服从该世界观。\n"
              + "2. 有一个只属于该世界观的核心意象（机械义眼/剑穗/舷窗/辐射尘/魔杖光）。\n"
              + "3. 结尾一句点到即止的羁绊伏笔。\n"
              + '4. 严格按 JSON 输出：{"title": "故事标题（4-10字）", "text": "故事正文", "coord": "宇宙坐标编号，如 PVE-2717-Δ"}\n'
              + "只输出 JSON。")
    try:
        result = await _llm_json([{"role": "user", "content": prompt}], max_tokens=800)
    except RuntimeError as e:
        return JSONResponse({"error": f"跃迁失败：{e}"}, status_code=500)
    text = (result.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "那个宇宙暂时观测不到，再试一次？"}, status_code=500)
    story = {
        "id": _uid(),
        "world": world_key,
        "world_name": world_name,
        "seed": seed,
        "title": (result.get("title") or "无题").strip()[:20],
        "text": text[:600],
        "coord": (result.get("coord") or f"PVE-{random.randint(1000, 9999)}-Ω").strip()[:20],
        "ts": _now(),
    }
    # 平行宇宙配图：许墨（身份随世界观变化）与她在该宇宙的初遇场景
    if with_image:
        try:
            img = await _gen_image(
                f"【平行宇宙 · {world_name}】坐标：{story['coord']}\n"
                f"标题：{story['title']}\n故事正文：{text}\n"
                f"请据此构思一幅初遇场景插画：许墨的身份与着装完全服从「{world_name}」世界观，"
                f"但保留银框眼镜与深紫色（紫罗兰）眼眸等核心特征；画面要有该世界观的核心意象。",
                "pverse_img", f"pv_{story['id']}", "landscape", with_xumo=True,
            )
            if img:
                story["image"] = img
        except Exception as e:
            print(f"[warn] creative_apps.py:pverse_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    data = _load(PV_FILE, {"stories": []})
    covered = {s.get("world") for s in data.get("stories", [])}
    data.setdefault("stories", []).append(story)
    data["stories"] = data["stories"][-50:]
    _save(PV_FILE, data)
    info = _add_affinity("pverse", f"观测宇宙：{story['coord']}")
    return {"story": story, "new_world": world_key not in covered, "affinity": info}


@router.delete("/api/pverse/{story_id}")
async def pverse_delete(story_id: str):
    data = _load(PV_FILE, {"stories": []})
    before = len(data.get("stories", []))
    data["stories"] = [s for s in data.get("stories", []) if s.get("id") != story_id]
    if len(data["stories"]) == before:
        return JSONResponse({"error": "这段宇宙不存在"}, status_code=404)
    _save(PV_FILE, data)
    return {"ok": True}


# ===========================================================================
# 4b. 平行世界 if 线 —— 「如果当初……」（自 deep_apps.py 合并迁入，
#      与「平行宇宙」同属一个观测台：pverse 看异世界坐标，ifline 看同一世界的另一种可能）
# ===========================================================================

IFLINE_FILE = RolePath("ifline.json")
IFLINE_DIR_NAME = "ifline_img"

IFLINE_THEMES = [
    {"key": "unmet", "name": "如果那天你没有来", "desc": "他没有在恋语市遇见你，一切如常，只是实验室的灯总是多亮一会儿。"},
    {"key": "normal", "name": "如果他是普通人", "desc": "没有 Evol，没有 Black Swan，他只是一个会为论文失眠的年轻教授。"},
    {"key": "left", "name": "如果你离开了恋语市", "desc": "你搬去了另一座城市，他在显微镜前想你的频率比看标本还高。"},
    {"key": "ares", "name": "如果 Ares 没有遇见你", "desc": "他仍是组织的核心，直到某天档案里出现一张你多年前的照片。"},
    {"key": "childhood", "name": "如果你们是青梅竹马", "desc": "你们一起长大，他早早学会把奖状藏起来，只把蝴蝶分你一只。"},
    {"key": "rain", "name": "如果重逢在雨夜", "desc": "多年后你在雨夜推开那家旧书店的门，他正低头擦一副银框眼镜。"},
]

IFLINE_PROMPT = (
    "你是许墨。现在要构想一个「如果当初……」的平行世界：{theme}。\n"
    "要求：以许墨的口吻与视角写一段短剧场的文字，温柔克制、话留三分，保留他的学术式浪漫与伏笔习惯。"
    "输出 JSON：\n"
    '{"title":"标题（8-20字）","premise":"世界设定（30-60字）",'
    '"scenes":[{"who":"他/她","line":"台词或动作，20-45字"}...]（3-5 段，从相逢写到分别或重逢）,'
    '"ending":"他在这个世界最后一句心里话（20-50字）"}'
    "只输出 JSON。"
)

IFLINE_CARD_PROMPT = (
    "Illustrated novel key visual, anime style, the couple: a tall gentle male professor with "
    "silver-rimmed glasses, wavy dark purple hair, pale skin, wearing a white shirt, dark trousers "
    "and a long trench coat (character named Lucien), and a young woman beside him, emotional scene: "
    "{scene_en}, warm cinematic lighting, purple and violet color palette, butterfly motif, "
    "highly detailed, romantic atmosphere, masterpiece, vertical composition"
)


def _theme_desc(key: str) -> str:
    for t in IFLINE_THEMES:
        if t["key"] == key:
            return f"《{t['name']}》：{t['desc']}"
    return "一个许墨与她的平行世界"


def _scene_en(theme_key: str) -> str:
    return {
        "unmet": "they meet by chance outside a rainy university lab, an umbrella, first gaze",
        "normal": "a quiet campus library at dusk, he reads a book while she sits across the table",
        "left": "a train station platform, he holds a butterfly specimen box, reluctant farewell",
        "ares": "a dim archive room, he stares at an old photograph of her under a desk lamp",
        "childhood": "summer meadow, two children catching butterflies, a shared tin box",
        "rain": "an old bookstore on a rainy night, he looks up from polishing his glasses",
    }.get(theme_key, "a romantic encounter between Lucien and a young woman, purple lighting")


@router.get("/api/ifline")
async def ifline_list():
    data = _load(IFLINE_FILE, {"lines": []})
    return {"lines": list(reversed(data.get("lines", [])[-60:])), "themes": IFLINE_THEMES}


@router.post("/api/ifline/generate")
async def ifline_generate(req: Request):
    body = await req.json()
    key = (body.get("theme") or "").strip()
    if key not in [t["key"] for t in IFLINE_THEMES]:
        key = random.choice(IFLINE_THEMES)["key"]
    theme = _theme_desc(key)
    try:
        r = await _llm_json([{"role": "system", "content": IFLINE_PROMPT.replace("{theme}", theme)},
                             {"role": "user", "content": "开始构想这个平行世界吧。"}],
                            max_tokens=1400)
    except Exception as e:
        print(f"[warn] creative_apps.py:ifline_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        r = {}
    scenes = []
    for s in r.get("scenes") or []:
        if isinstance(s, dict) and s.get("line"):
            scenes.append({"who": "她" if s.get("who") == "她" else "他",
                           "line": str(s["line"]).strip()[:60]})
    if not scenes:
        scenes = [{"who": "他", "line": "如果那天我没有抬头，我们大概只是同一座城市里两个擦肩的陌生人。"},
                  {"who": "她", "line": "可你偏偏抬头了。"},
                  {"who": "他", "line": "所以我一直认为，概率是最不靠谱的东西——直到它把你还给我。"}]
    ending = str(r.get("ending") or "").strip()[:80]
    if not ending or "心里话（" in ending or ending.startswith("他在这个世界"):
        ending = "如果这是另一个我，他大概也会在某个深夜，想起一个从未真正见过的人。"
    item = {"id": _uid(), "theme_key": key, "theme": theme,
            "title": str(r.get("title") or "平行世界").strip()[:30],
            "premise": str(r.get("premise") or "").strip()[:120],
            "scenes": scenes,
            "ending": ending,
            "card": "", "ts": datetime.now().strftime("%Y-%m-%d %H:%M")}
    data = _load(IFLINE_FILE, {"lines": []})
    data.setdefault("lines", [])
    data["lines"].append(item)
    data["lines"] = data["lines"][-100:]
    _save(IFLINE_FILE, data)
    _add_affinity("ifline", f"平行世界 · {item['title']}")
    return {"line": item}


@router.post("/api/ifline/{lid}/card")
async def ifline_card(lid: str):
    data = _load(IFLINE_FILE, {"lines": []})
    item = next((x for x in data.get("lines", []) if x.get("id") == lid), None)
    if not item:
        return JSONResponse({"error": "该 if 线不存在"}, status_code=404)
    if item.get("card"):
        return {"card": item["card"], "cached": True}
    try:
        from app import _openai_generate_image, STATIC_DIR
        out_dir = STATIC_DIR / IFLINE_DIR_NAME
        out_dir.mkdir(parents=True, exist_ok=True)
        prompt = IFLINE_CARD_PROMPT.format(scene_en=_scene_en(item.get("theme_key", "")))
        url = await _openai_generate_image(prompt, out_dir, f"/static/{IFLINE_DIR_NAME}",
                                           item["id"], "1536x2048", has_character=True)
    except Exception as e:
        print(f"[warn] creative_apps.py:ifline_card: {type(e).__name__} {str(e)[:150]}", flush=True)
        url = None
    if not url:
        return JSONResponse({"error": "画卡生成失败（额度不足或服务未配置），可先收藏文字版"},
                            status_code=502)
    item["card"] = url
    _save(IFLINE_FILE, data)
    _add_affinity("ifline_card", f"为《{item['title']}》绘制平行世界卡面")
    return {"card": url, "cached": False}


@router.delete("/api/ifline/{lid}")
async def ifline_delete(lid: str):
    data = _load(IFLINE_FILE, {"lines": []})
    before = len(data.get("lines", []))
    data["lines"] = [x for x in data.get("lines", []) if x.get("id") != lid]
    if len(data["lines"]) == before:
        return JSONResponse({"error": "该 if 线不存在"}, status_code=404)
    _save(IFLINE_FILE, data)
    return {"ok": True}


# ===========================================================================
# 5. 天台观星 —— 星座讲解 + 流星许愿
# ===========================================================================

ASTRO_FILE = RolePath("astro.json")

ASTRO_CONSTELLATIONS = [
    {"id": "ori",  "name": "猎户座",   "months": [12, 1, 2],  "star": "参宿四", "brief": "冬夜最壮丽的猎人"},
    {"id": "tau",  "name": "金牛座",   "months": [11, 12, 1], "star": "毕宿五", "brief": "衔着昴星团的公牛"},
    {"id": "gem",  "name": "双子座",   "months": [12, 1, 2],  "star": "北河三", "brief": "一对永不分离的兄弟"},
    {"id": "can",  "name": "巨蟹座",   "months": [1, 2, 3],   "star": "柳宿增十", "brief": "最温柔的暗星群"},
    {"id": "leo",  "name": "狮子座",   "months": [2, 3, 4],   "star": "轩辕十四", "brief": "春夜之王的心脏"},
    {"id": "vir",  "name": "处女座",   "months": [3, 4, 5],   "star": "角宿一", "brief": "麦穗与纯白的少女"},
    {"id": "lib",  "name": "天秤座",   "months": [4, 5, 6],   "star": "氐宿四", "brief": "衡量心之所向的秤"},
    {"id": "sco",  "name": "天蝎座",   "months": [5, 6, 7],   "star": "心宿二", "brief": "燃烧的心脏之火"},
    {"id": "sgr",  "name": "射手座",   "months": [6, 7, 8],   "star": "箕宿三", "brief": "指向银心的弓箭"},
    {"id": "cap",  "name": "摩羯座",   "months": [7, 8, 9],   "star": "垒壁阵四", "brief": "攀登陡崖的海羊"},
    {"id": "aqu",  "name": "水瓶座",   "months": [8, 9, 10],  "star": "虚宿一", "brief": "倾注流水的少年"},
    {"id": "pis",  "name": "双鱼座",   "months": [9, 10, 11], "star": "右更二", "brief": "被维纳斯祝福的鱼"},
    {"id": "lyr",  "name": "天琴座",   "months": [6, 7, 8, 9], "star": "织女一", "brief": "仲夏夜的琴弦"},
    {"id": "aql",  "name": "天鹰座",   "months": [6, 7, 8, 9], "star": "河鼓二", "brief": "振翅的牛郎星"},
    {"id": "cyn",  "name": "天鹅座",   "months": [7, 8, 9],   "star": "天津四", "brief": "飞越银河的北十字"},
    {"id": "cas",  "name": "仙后座",   "months": [9, 10, 11, 12, 1, 2], "star": "王良四", "brief": "永恒的 W 形王冠"},
    {"id": "uma",  "name": "大熊座",   "months": [3, 4, 5, 6], "star": "玉衡", "brief": "北斗七星的勺柄"},
    {"id": "boo",  "name": "牧夫座",   "months": [4, 5, 6],   "star": "大角星", "brief": "追熊的牧人"},
]


@router.get("/api/astro")
async def astro_state():
    now_month = datetime.now().month
    visible = [c for c in ASTRO_CONSTELLATIONS if now_month in c["months"]]
    if not visible:
        visible = random.sample(ASTRO_CONSTELLATIONS, 3)
    data = _load(ASTRO_FILE, {"logs": [], "wishes": []})
    return {
        "month": now_month,
        "visible": visible,
        "all": ASTRO_CONSTELLATIONS,
        "logs": list(reversed(data.get("logs", [])[-30:])),
        "wishes": list(reversed(data.get("wishes", [])[-30:])),
    }


@router.post("/api/astro/story")
async def astro_story(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:astro_story: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    name = (body.get("constellation") or "").strip()[:20]
    with_image = body.get("with_image")
    with_image = True if with_image is None else bool(with_image)
    if not name:
        return JSONResponse({"error": "要指定一个星座"}, status_code=400)
    spec = next((c for c in ASTRO_CONSTELLATIONS if c["name"] == name), None)
    extra = f"（主星：{spec['star']}）" if spec else ""
    prompt = _system_prompt() + f"""

【当前任务】今晚你和她在恋语大学实验楼天台观星，望远镜对准了{name}{extra}。
请写一段「观星指南」，要求：
1. 150-240 字，先讲 1-2 个真实的天文细节（星等、距离、颜色或神话由来），再自然滑进一句许墨式的情话。
2. 像你握着她的手调整望远镜焦距时低声说的话，学术式撩人，一句即止。
3. 只输出正文，不要引号和解释。"""
    text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=500)).strip()
    if not text:
        return JSONResponse({"error": "云层太厚，稍后再试"}, status_code=500)
    log = {"id": _uid(), "constellation": name, "text": text, "ts": _now()}
    # 观星配图：天台夜空双人场景（许墨与她并肩观星），星空含该星座
    if with_image:
        try:
            img = await _gen_image(
                f"【天台观星 · {name}】{extra}\n观星指南：{text}\n"
                f"请据此构思一幅天台观星场景插画：许墨与她并肩站在恋语大学实验楼天台，"
                f"望远镜指向夜空中的{name}，星光与紫色夜色调呼应。",
                "astro_img", f"astro_{log['id']}", "landscape", with_xumo=True,
            )
            if img:
                log["image"] = img
        except Exception as e:
            print(f"[warn] creative_apps.py:astro_story: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    data = _load(ASTRO_FILE, {"logs": [], "wishes": []})
    data.setdefault("logs", []).append(log)
    data["logs"] = data["logs"][-30:]
    _save(ASTRO_FILE, data)
    info = _add_affinity("astro", f"一起看{name}")
    return {"log": log, "affinity": info}


@router.post("/api/astro/wish")
async def astro_wish(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:astro_wish: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    wish = (body.get("wish") or "").strip()[:100]
    if not wish:
        return JSONResponse({"error": "先悄悄说给星星听"}, status_code=400)
    prompt = _system_prompt() + f"""

【当前任务】观星时一颗流星划过，她许愿：「{wish}」。请以许墨的口吻回应她。
要求：30-60 字。不点破愿望，只许一个温柔的承诺或一句学术式情话（可涉及光年、概率、引力），话留三分。只输出回应正文。"""
    text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=200)).strip()
    if not text:
        return JSONResponse({"error": "流星走丢了，再试一次"}, status_code=500)
    rec = {"id": _uid(), "wish": wish, "reply": text, "ts": _now()}
    data = _load(ASTRO_FILE, {"logs": [], "wishes": []})
    data.setdefault("wishes", []).append(rec)
    data["wishes"] = data["wishes"][-30:]
    _save(ASTRO_FILE, data)
    info = _add_affinity("astro_wish", "对流星许愿")
    return {"wish": rec, "affinity": info}


# ===========================================================================
# 6. 黑天鹅档案 —— 随心动等级解锁的机密剧情档案
# ===========================================================================

BSF_FILE = RolePath("bsfile.json")

BSF_ARCHIVES = [
    {"code": "BS-001", "title": "观察日志 · 第 7 天", "type": "科研日志",
     "req": {"kind": "chat", "value": 1},   "req_desc": "与他有过一次对话"},
    {"code": "BS-017", "title": "实验记录 · 样本 L", "type": "实验记录",
     "req": {"kind": "level", "value": 2},  "req_desc": "心动达到 Lv.2 留意"},
    {"code": "BS-042", "title": "监控片段 · 东楼天台", "type": "监控记录",
     "req": {"kind": "chat", "value": 30},  "req_desc": "累计对话 30 条"},
    {"code": "BS-108", "title": "通讯记录 · 加密频道", "type": "加密通讯",
     "req": {"kind": "level", "value": 3},  "req_desc": "心动达到 Lv.3 信赖"},
    {"code": "BS-201", "title": "蝴蝶标本盒", "type": "证物笔记",
     "req": {"kind": "chat", "value": 80},  "req_desc": "累计对话 80 条"},
    {"code": "BS-277", "title": "心率异常报告", "type": "医学报告",
     "req": {"kind": "level", "value": 4},  "req_desc": "心动达到 Lv.4 暧昧"},
    {"code": "BS-333", "title": "未寄出的信", "type": "私人信件",
     "req": {"kind": "level", "value": 5},  "req_desc": "心动达到 Lv.5 心动"},
    {"code": "BS-999", "title": "「Ares」权限文件", "type": "组织机密",
     "req": {"kind": "level", "value": 6},  "req_desc": "心动达到 Lv.6 牵挂"},
]


def _bsf_progress() -> dict:
    """汇总解锁所需进度：聊天条数与心动等级。"""
    from app import _load_affinity, _affinity_info
    info = _affinity_info(_load_affinity())
    try:
        from app import _load_chat_log
        chat_count = len(_load_chat_log())
    except Exception as e:
        print(f"[warn] creative_apps.py:_bsf_progress: {type(e).__name__} {str(e)[:150]}", flush=True)
        chat_count = 0
    return {"level": info["level_index"], "level_name": info["level_name"],
            "affinity_value": info["value"], "chat_count": chat_count}


def _bsf_met(req: dict, prog: dict) -> bool:
    if req.get("kind") == "level":
        return prog["level"] >= int(req.get("value", 0))
    if req.get("kind") == "chat":
        return prog["chat_count"] >= int(req.get("value", 0))
    return False


@router.get("/api/bsfile")
async def bsfile_list():
    prog = _bsf_progress()
    data = _load(BSF_FILE, {"unlocked": {}})
    unlocked = data.get("unlocked", {})
    files = []
    for a in BSF_ARCHIVES:
        rec = unlocked.get(a["code"])
        files.append({
            **a,
            "unlocked": bool(rec),
            "unlocked_at": rec.get("ts", "") if rec else "",
            "text": rec.get("text", "") if rec else "",
            "image": rec.get("image", "") if rec else "",
        })
    files.sort(key=lambda f: f["unlocked"], reverse=False)
    files.sort(key=lambda f: f["code"])
    return {"files": files, "progress": prog,
            "unlocked_count": sum(1 for f in files if f["unlocked"])}


@router.post("/api/bsfile/unlock")
async def bsfile_unlock(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] creative_apps.py:bsfile_unlock: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    code = (body.get("code") or "").strip()
    with_image = body.get("with_image")
    with_image = True if with_image is None else bool(with_image)
    arch = next((a for a in BSF_ARCHIVES if a["code"] == code), None)
    if not arch:
        return JSONResponse({"error": "档案编号不存在"}, status_code=404)
    prog = _bsf_progress()
    data = _load(BSF_FILE, {"unlocked": {}})
    unlocked = data.setdefault("unlocked", {})
    if code in unlocked:
        return {"file": {**arch, "unlocked": True, "unlocked_at": unlocked[code].get("ts", ""),
                         "text": unlocked[code].get("text", ""),
                         "image": unlocked[code].get("image", "")}, "cached": True}
    if not _bsf_met(arch["req"], prog):
        return JSONResponse({"error": f"权限不足：{arch['req_desc']}", "need": arch["req_desc"]}, status_code=403)

    prompt = _system_prompt() + f"""

【当前任务】解密一份 Black Swan 组织流出的机密档案：编号 {arch['code']}「{arch['title']}」，文体：{arch['type']}。
请以该文体写 160-260 字的档案正文，要求：
1. 形式感拉满：按文体加时间戳/编号/密级抬头（如「实验记录 · 编号{arch['code']} · 密级：绝密」），正文克制、冷静、术语化。
2. 内容是关于「你（许墨/Ares）」与「她」之间的一条隐藏剧情线索：观测、异常数据、失控的心率、未说出口的部分，任选其一深挖。
3. 结尾留一个让人心头一紧的钩子（一行批注、一个待办、一句被划掉的话）。
4. 只输出档案正文。"""
    text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=500)).strip()
    if not text:
        return JSONResponse({"error": "解密中断，稍后再试"}, status_code=500)
    rec = {"text": text, "ts": _now()}
    # 档案配图：机密文档/证物氛围场景（无人像，点缀许墨意象：银框眼镜/蝴蝶标本/黑咖啡等）
    if with_image:
        try:
            img = await _gen_image(
                f"【黑天鹅档案 · {arch['code']}「{arch['title']}」】文体：{arch['type']}\n"
                f"档案正文：{text}\n"
                f"请据此构思一幅「机密档案/证物」氛围插画：像一张被偷拍或归档的照片——"
                f"桌面的机密文件、监控屏幕、实验记录本、蝴蝶标本盒、银框眼镜等许墨意象物件，"
                f"冷紫调与暗影，悬疑克制，不出现清晰人像。",
                "bsfile_img", f"bs_{code}", "portrait", with_xumo=False,
            )
            if img:
                rec["image"] = img
        except Exception as e:
            print(f"[warn] creative_apps.py:bsfile_unlock: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    unlocked[code] = rec
    _save(BSF_FILE, data)
    info = _add_affinity("bsfile", f"解密档案 {code}")
    return {"file": {**arch, "unlocked": True, "unlocked_at": rec["ts"], "text": text,
                     "image": rec.get("image", "")},
            "cached": False, "affinity": info}
