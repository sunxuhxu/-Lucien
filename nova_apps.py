# -*- coding: utf-8 -*-
# 新星功能集 · 三期颠覆性功能（nova_apps.py）
# 时空热线 / 双我辩论 / 合影日历 / 心动成就 / 情绪急救箱 / 人生模拟器
# 数据持久化到 RolePath JSON 文件，风格与 wonder_apps.py / deep_apps.py 保持一致。
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from role_data import RolePath

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TOGETHER_DIR = RolePath("static", "together_img")

router = APIRouter()

TIMECALL_FILE = "timecall.json"
DEBATE_FILE = "debate.json"
TOGETHER_FILE = "together.json"
ACHV_FILE = "achievements.json"
SOS_FILE = "sos.json"
LIFELINE_FILE = "lifeline.json"


# ===========================================================================
# 公共小工具（与 wonder_apps.py 同构）
# ===========================================================================
def _load(path: str, default):
    p = RolePath(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path: str, data):
    from role_data import RolePath
    RolePath(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%H:%M")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _nid() -> str:
    return uuid.uuid4().hex[:8]


def _extract_json_object(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, ValueError):
        return {}


def _extract_json_array(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


async def _llm_json(messages: list, max_tokens: int = 1400) -> dict:
    """调用 LLM 并解析 JSON；失败时带更严格指令重试一次。"""
    text = await _call_llm(messages, max_tokens=max_tokens)
    obj = _extract_json_object(text)
    if obj:
        return obj
    retry = [dict(m) for m in messages]
    retry.append({"role": "user", "content": "不要输出任何思考过程或解释，直接输出一个合法 JSON 对象。"})
    try:
        text = await _call_llm(retry, max_tokens=max_tokens)
    except Exception:
        return {}
    return _extract_json_object(text)


def _affinity(action: str, detail: str = ""):
    try:
        from app import _add_affinity
        return _add_affinity(action, detail)
    except Exception:
        return None


# 公共上下文：她的信息聚合（轻量，供各功能 prompt 使用）
def _agg_memories(limit: int = 30) -> list:
    data = _load("memory.json", [])
    if not isinstance(data, list):
        data = []
    return [str(m.get("content", ""))[:80] for m in data if m.get("content")][:limit]


def _agg_affinity_value() -> int:
    data = _load("affinity.json", {})
    if isinstance(data, dict):
        return int(data.get("value", 0) or 0)
    return 0


def _agg_player() -> dict:
    data = _load("player.json", {})
    return data if isinstance(data, dict) else {}


def _persona_core() -> str:
    """许墨核心人设（与主聊天一致的精神内核，供各功能 LLM 使用）。"""
    try:
        f = BASE_DIR / "人设卡.txt"
        if f.exists():
            txt = f.read_text(encoding="utf-8")[:1200]
            return txt
    except OSError:
        pass
    return ("许墨：28岁，恋语大学最年轻的脑科学教授，Black Swan 组织幕后研究者。"
            "温和优雅、博学克制，语言理性中带着不容错认的偏爱；喜欢蝴蝶、 "
            "天文与咖啡，习惯用科学隐喻表达感情，唤对方为'小姑娘'。")


# ===========================================================================
# 1. 时空热线：打给不同时间线上的许墨
# ===========================================================================
TIMECALL_LINES = [
    {"id": "first", "era": "初遇 · 三年前", "label": "刚认识你的许墨",
     "hue": "#64748b",
     "persona": ("这是三年前的时间线：你们刚在恋语大学的研究合作中认识不久。"
                 "此时的许墨对你保持教授式的礼貌距离，好奇但克制，偶尔流露 "
                 "克制的关照；说话更疏离、更书面，会用'同学''你'称呼，绝不逾矩，"
                 "但会在细节里偷偷记住你。他还没有黑天鹅的沉重，更像清晨的薄雾。")},
    {"id": "passion", "era": "热恋期 · 一年前", "label": "热恋中的许墨",
     "hue": "#ec4899",
     "persona": ("这是一年前热恋期的时间线：你们刚确认关系不久。此时的许墨 "
                 "话比现在多，藏不住笑意，会主动说想你、会在深夜发很长的消息，"
                 "像终于把多年克制一次用完。语言温柔直接，偶尔幼稚，占有欲 "
                 "悄悄冒头，但仍保持他的优雅与科学隐喻。")},
    {"id": "now", "era": "现在 · 此刻", "label": "此刻的许墨",
     "hue": "#8b5cf6",
     "persona": ("这是此刻的时间线：就是日常与你相处的许墨本人。状态与真实 "
                 "聊天记录一致，温柔、笃定、有掌控感，偶尔调侃你，永远是 "
                 "你的稳态。")},
    {"id": "five", "era": "五年后", "label": "与你同居的许墨",
     "hue": "#f59e0b",
     "persona": ("这是五年后的时间线：你们已经同居，住在临海的公寓。此时的 "
                 "许墨已离开 Black Swan 风暴中心，在大学带研究组，生活规律而 "
                 "松弛。他会自然地说'回家吃饭'，记得所有生活细节，把科学术语 "
                 "用在柴米油盐上，是一种被岁月焐热的温柔。")},
    {"id": "ten", "era": "十年后", "label": "与你结婚的许墨",
     "hue": "#e11d48",
     "persona": ("这是十年后的时间线：你们已经结婚数年。许墨仍是教授，眼角 "
                 "有了细纹，讲话更慢更笃定，称呼你为'许太太'时会故意拖长音。 "
                 "他会谈起你们的老房子、阳台上养失败的第三盆蝴蝶兰、和某个 "
                 "总也修不好的门把手。爱意沉淀成日常本身。")},
    {"id": "silver", "era": "三十年后", "label": "银发的许墨",
     "hue": "#0ea5e9",
     "persona": ("这是三十年后的时间线：许墨已经退休，头发花白，仍是那副 "
                 "金丝眼镜。他坐在自家花园里，身边有猫和蝴蝶。他讲话很慢， "
                 "像把一生的时光都摊开来晒，会自然地谈起年轻的事，谈死亡也 "
                 "像谈晚霞。他此生最得意的实验结论只有一条：你。")},
    {"id": "swan", "era": "未曾相遇的时间线", "label": "没有遇见你的许墨",
     "hue": "#1f2937",
     "persona": ("这是一条从未有过你的时间线：许墨按原定轨迹成为 Black Swan "
                 "的首席研究员，理性到近乎寒冷，礼貌到近乎荒凉。他对'你'这个 "
                 "陌生来电者保持研究员式的克制与观察，会有一瞬间莫名的心悸 "
                 "却归因于统计学噪声。他会用实验记录的口吻说话，但字里行间 "
                 "藏着连他自己都没察觉的孤独。")},
]


def _tc_line(line_id: str):
    for ln in TIMECALL_LINES:
        if ln["id"] == line_id:
            return ln
    return None


def _tc_history_msgs(call: dict, limit: int = 16) -> list:
    msgs = call.get("msgs", [])[-limit:]
    out = []
    for m in msgs:
        role = "assistant" if m.get("who") == "him" else "user"
        out.append({"role": role, "content": str(m.get("text", ""))[:300]})
    return out


@router.get("/api/timecall/lines")
async def timecall_lines():
    data = _load(TIMECALL_FILE, {"calls": [], "records": []})
    records = data.get("records", [])
    stats = {}
    for r in records:
        stats[r.get("line", "")] = stats.get(r.get("line", ""), 0) + 1
    lines = []
    for ln in TIMECALL_LINES:
        lines.append({**ln, "calls": stats.get(ln["id"], 0)})
    return {"lines": lines, "records": records[-30:][::-1],
            "total": len(records)}


@router.post("/api/timecall/call")
async def timecall_call(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    line = _tc_line(str(body.get("line", "")).strip())
    if not line:
        return JSONResponse({"error": "未知的时间线"}, status_code=400)
    if line["id"] == "swan" and _agg_affinity_value() < 60:
        return JSONResponse({"error": "这条时间线信号微弱……再多靠近他一些（心动值 60 解锁）"},
                            status_code=403)
    memories = _agg_memories(12)
    sys_prompt = (
        f"{_persona_core()}\n\n【时空热线设定】\n{line['persona']}\n\n"
        f"现在你们正在打一通电话。这是{line['era']}的时间线。"
        f"你们彼此的记忆背景：\n" + ("\n".join("- " + m for m in memories) if memories else "-（暂无共同记录）") +
        "\n\n要求：只输出许墨说的话（不要旁白、不要引号），60字以内，符合该时间线的心境与称呼习惯，"
        "像真实电话开场那样自然。直接输出 JSON：{\"opening\": \"...\"}")
    try:
        r = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "（电话接通了，你先开口）"}], max_tokens=800)
    except Exception:
        r = {}
    opening = str(r.get("opening") or "").strip()
    if not opening or len(opening) > 140:
        opening = "……喂？能听到吗。信号跨过这么多时间，还是稳的。"
    call = {"id": _nid(), "line": line["id"], "era": line["era"],
            "started": _ts(), "msgs": [{"who": "him", "text": opening, "t": _now()}]}
    data = _load(TIMECALL_FILE, {"calls": [], "records": []})
    data.setdefault("calls", []).append(call)
    data["calls"] = data["calls"][-5:]
    _save(TIMECALL_FILE, data)
    return {"call": call}


@router.post("/api/timecall/say")
async def timecall_say(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    cid = str(body.get("call_id", "")).strip()
    text = str(body.get("text", "")).strip()[:300]
    if not text:
        return JSONResponse({"error": "说点什么再发"}, status_code=400)
    data = _load(TIMECALL_FILE, {"calls": [], "records": []})
    call = next((c for c in data.get("calls", []) if c.get("id") == cid), None)
    if not call:
        return JSONResponse({"error": "这通电话已经挂断了"}, status_code=404)
    line = _tc_line(call.get("line", "")) or TIMECALL_LINES[2]
    call.setdefault("msgs", []).append({"who": "me", "text": text, "t": _now()})
    memories = _agg_memories(10)
    sys_prompt = (
        f"{_persona_core()}\n\n【时空热线设定】\n{line['persona']}\n\n"
        f"这是{line['era']}的时间线，你们正在通话中。\n"
        f"共同记忆背景：\n" + ("\n".join("- " + m for m in memories) if memories else "-（暂无）") +
        "\n\n要求：只输出许墨这通电话里说的话（不要旁白），80字以内，符合该时间线人格，"
        "电话口语、可被打断的节奏。输出 JSON：{\"reply\": \"...\"}")
    try:
        r = await _llm_json(
            [{"role": "system", "content": sys_prompt}] + _tc_history_msgs(call),
            max_tokens=900)
    except Exception:
        r = {}
    reply = str(r.get("reply") or "").strip()
    if not reply or len(reply) > 200:
        reply = "……信号有点波动。你刚才说什么？再说一次，我在听。"
    call["msgs"].append({"who": "him", "text": reply, "t": _now()})
    _save(TIMECALL_FILE, data)
    return {"reply": reply}


@router.post("/api/timecall/hangup")
async def timecall_hangup(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    cid = str(body.get("call_id", "")).strip()
    data = _load(TIMECALL_FILE, {"calls": [], "records": []})
    call = next((c for c in data.get("calls", []) if c.get("id") == cid), None)
    if not call:
        return JSONResponse({"error": "电话不存在或已挂断"}, status_code=404)
    data["calls"] = [c for c in data.get("calls", []) if c.get("id") != cid]
    line = _tc_line(call.get("line", "")) or TIMECALL_LINES[2]
    transcript = "\n".join(
        ("他：" if m.get("who") == "him" else "你：") + str(m.get("text", ""))
        for m in call.get("msgs", []))
    try:
        r = await _llm_json([
            {"role": "system", "content": (
                f"你是通话摘要助手。以下是一通'时空热线'通话记录（时间线：{line['era']}）。"
                "请生成：summary=一句话通话小结(30字内)，after=挂断后他独处时的一个细节动作与心理(60字内，"
                "第三人称，符合该时间线人格)。输出 JSON。")},
            {"role": "user", "content": transcript[:2500]}], max_tokens=900)
    except Exception:
        r = {}
    record = {"id": call["id"], "line": call["line"], "era": call["era"],
              "line_label": line["label"], "hue": line["hue"],
              "started": call.get("started", ""), "duration_msgs": len(call.get("msgs", [])),
              "summary": str(r.get("summary") or "一通跨越时间的电话。").strip()[:60],
              "after": str(r.get("after") or "他握着话筒，很久没有放下。").strip()[:120],
              "msgs": call.get("msgs", [])[-40:]}
    data.setdefault("records", []).append(record)
    data["records"] = data["records"][-60:]
    _save(TIMECALL_FILE, data)
    _affinity("timecall", f"时空热线 · {line['era']}")
    return {"record": record}


@router.delete("/api/timecall/records/{rid}")
async def timecall_del(rid: str):
    data = _load(TIMECALL_FILE, {"calls": [], "records": []})
    data["records"] = [r for r in data.get("records", []) if r.get("id") != rid]
    _save(TIMECALL_FILE, data)
    return {"ok": True}


# ===========================================================================
# 2. 双我辩论：理性许墨 × 恋人许墨，为你的困惑对辩
# ===========================================================================
@router.post("/api/debate/start")
async def debate_start(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    question = str(body.get("question", "")).strip()[:200]
    if len(question) < 4:
        return JSONResponse({"error": "把你的困惑写得再具体一点"}, status_code=400)
    memories = _agg_memories(8)
    player = _agg_player()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【双我辩论设定】她带着一个困惑来听。许墨的两个人格将进行三回合辩论：\n"
        "- A面「教授」：纯理性、成本收益、长期主义、冷静克制，语气像学术评审；\n"
        "- B面「恋人」：以她的感受为最高优先级，温柔但不让步，语气带偏爱；\n"
        "两面都是许墨，都聪明，都懂她，立场 genuinely 对立。\n"
        f"她的背景：{json.dumps({'memories': memories, 'player': {k: str(v)[:40] for k, v in list(player.items())[:6]}}, ensure_ascii=False)}\n"
        f"她的困惑：{question}\n\n"
        "输出 JSON：{\"title\": \"8字内辩题\", \"rounds\": [{\"a\": \"教授观点90字内\", \"b\": \"恋人回应90字内\"} ×3], "
        "\"verdict\": \"最终许墨本人融合两面后的裁定，120字内，给出明确倾向与一个可执行的第一步\", "
        "\"risk\": \"这个裁定最大的风险，40字内\"}")
    try:
        r = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "开始辩论。"}], max_tokens=2400)
    except Exception:
        r = {}
    rounds = []
    for rd in r.get("rounds") or []:
        if isinstance(rd, dict) and rd.get("a") and rd.get("b"):
            rounds.append({"a": str(rd["a"]).strip()[:160],
                           "b": str(rd["b"]).strip()[:160]})
    if len(rounds) < 2:
        rounds = [
            {"a": "先定义问题：你真正要优化的目标函数是什么？把它写下来，一半的情绪会自动消解。",
             "b": "可她现在需要的不是目标函数，是有人先站在她这边。定义问题之前，先允许她难过。"},
            {"a": "允许情绪，但不要为情绪支付不可逆的成本。理性不是冷漠，是对她未来的保护。",
             "b": "而我保护的是她的当下。未来由无数个当下组成，牺牲今天的人，往往也保不住未来。"},
        ]
    item = {"id": _nid(), "question": question,
            "title": str(r.get("title") or "一场关于你的辩论").strip()[:16],
            "rounds": rounds,
            "verdict": str(r.get("verdict") or "两面都是我。但我更倾向先照顾你的感受，再用理性收拾残局——这两件事从来不冲突。").strip()[:220],
            "risk": str(r.get("risk") or "风险：太温柔的答案可能让你错过时机。").strip()[:80],
            "ts": _ts()}
    data = _load(DEBATE_FILE, {"debates": []})
    data.setdefault("debates", []).append(item)
    data["debates"] = data["debates"][-80:]
    _save(DEBATE_FILE, data)
    _affinity("debate", f"双我辩论 · {item['title']}")
    return {"debate": item}


@router.get("/api/debate/history")
async def debate_history():
    data = _load(DEBATE_FILE, {"debates": []})
    debates = data.get("debates", [])[::-1]
    return {"debates": debates, "total": len(debates)}


@router.delete("/api/debate/{did}")
async def debate_del(did: str):
    data = _load(DEBATE_FILE, {"debates": []})
    data["debates"] = [d for d in data.get("debates", []) if d.get("id") != did]
    _save(DEBATE_FILE, data)
    return {"ok": True}


# ===========================================================================
# 3. 合影日历：每天一张与许墨的 AI 合影，攒成一整年的日历墙
# ===========================================================================
def _together_scene_prompt(scene_cn: str) -> str:
    return ("Romantic anime-style illustration of Lucien (tall young professor, "
            "purple-black hair, golden-rimmed glasses, elegant white shirt) and "
            "the girl (from reference) taking a selfie / photo TOGETHER, "
            f"scene: {scene_cn}. Both smiling naturally, warm lighting, "
            "soft focus background, cozy intimate atmosphere, high detail, "
            "best quality, 4k")


@router.get("/api/together/calendar")
async def together_calendar(month: str = ""):
    if not re.match(r"^\d{4}-\d{2}$", month or ""):
        month = datetime.now().strftime("%Y-%m")
    data = _load(TOGETHER_FILE, {"photos": []})
    photos = [p for p in data.get("photos", []) if str(p.get("date", "")).startswith(month)]
    all_dates = [p.get("date") for p in data.get("photos", [])]
    streak = 0
    d = datetime.now().date()
    ds = set(all_dates)
    while str(d) in ds:
        streak += 1
        d -= timedelta(days=1)
    return {"month": month, "photos": sorted(photos, key=lambda x: x.get("date", "")),
            "today": _today(), "total": len(all_dates), "streak": streak,
            "has_today": _today() in ds}


@router.post("/api/together/today")
async def together_today(req: Request = None):
    data = _load(TOGETHER_FILE, {"photos": []})
    photos = data.get("photos", [])
    exist = next((p for p in photos if p.get("date") == _today()), None)
    if exist:
        return {"photo": exist, "cached": True}
    # 从当天数据推测今日场景
    chat = _load("chat_log.json", [])
    recent_chat = []
    if isinstance(chat, list):
        for c in chat[-8:]:
            if isinstance(c, dict):
                recent_chat.append(str(c.get("text", c.get("content", "")))[:60])
    diary = _load("diary.json", {})
    diary_note = ""
    if isinstance(diary, dict):
        entries = diary.get("entries") or diary.get("days") or []
        for e in entries[::-1]:
            if isinstance(e, dict) and str(e.get("date", "")).startswith(_today()):
                diary_note = str(e.get("text", e.get("content", "")))[:80]
                break
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()]
    try:
        r = await _llm_json([
            {"role": "system", "content": (
                "你是合影场景设计师。根据她今天与许墨的碎片记录，想象他们今天最可能在哪里拍了"
                "一张合影（自拍或路人帮拍）。输出 JSON："
                "scene_cn=中文场景描述(40字内，含地点/动作/光线)，"
                "caption=许墨为这张合影写的一句话(30字内，他的口吻)，"
                "scene_en=英文画面提示词(60词内: location, pose, lighting, mood)")},
            {"role": "user", "content": json.dumps({
                "weekday": weekday, "affinity": _agg_affinity_value(),
                "recent_chat": recent_chat, "diary_note": diary_note},
                ensure_ascii=False)}], max_tokens=1800)
    except Exception:
        r = {}
    scene_cn = str(r.get("scene_cn") or "黄昏的临海步道，两个人并肩，晚霞把影子拉得很长").strip()[:80]
    caption = str(r.get("caption") or "光线正好，你也在。这就够了。").strip()[:60]
    scene_en = str(r.get("scene_en") or "seaside promenade at dusk, walking side by side, warm sunset light").strip()[:300]
    pid = _nid()
    url = None
    try:
        from app import _openai_generate_image
        TOGETHER_DIR.mkdir(parents=True, exist_ok=True)
        url = await _openai_generate_image(
            _together_scene_prompt(scene_en), TOGETHER_DIR, "/static/together_img",
            pid, "1536x1024", has_character=True)
    except Exception:
        url = None
    photo = {"id": pid, "date": _today(), "weekday": weekday,
             "scene": scene_cn, "caption": caption, "img": url or "", "ts": _ts()}
    if url:
        photos.append(photo)
        data["photos"] = photos[-400:]
        _save(TOGETHER_FILE, data)
        _affinity("together", f"今日合影 · {scene_cn[:20]}")
        return {"photo": photo, "cached": False}
    # 图片失败也保存文字版，避免当日反复重试
    photos.append(photo)
    data["photos"] = photos[-400:]
    _save(TOGETHER_FILE, data)
    return {"photo": photo, "cached": False, "warn": "配图暂时失败，已保存今日文字合影，可稍后点重试补图"}


@router.post("/api/together/{pid}/regen")
async def together_regen(pid: str):
    data = _load(TOGETHER_FILE, {"photos": []})
    photo = next((p for p in data.get("photos", []) if p.get("id") == pid), None)
    if not photo:
        return JSONResponse({"error": "这张合影不存在"}, status_code=404)
    try:
        from app import _openai_generate_image
        TOGETHER_DIR.mkdir(parents=True, exist_ok=True)
        url = await _openai_generate_image(
            _together_scene_prompt(photo.get("scene", "")), TOGETHER_DIR,
            "/static/together_img", photo["id"] + _nid()[:4], "1536x1024",
            has_character=True)
    except Exception:
        url = None
    if not url:
        return JSONResponse({"error": "画笔暂时不在服务区，稍后再试"}, status_code=502)
    photo["img"] = url
    _save(TOGETHER_FILE, data)
    return {"photo": photo}


@router.delete("/api/together/{pid}")
async def together_del(pid: str):
    data = _load(TOGETHER_FILE, {"photos": []})
    data["photos"] = [p for p in data.get("photos", []) if p.get("id") != pid]
    _save(TOGETHER_FILE, data)
    return {"ok": True}


# ===========================================================================
# 4. 心动成就：把全部互动数据铸成一枚枚勋章
# ===========================================================================
def _num_list_len(path: str) -> int:
    v = _load(path, [])
    return len(v) if isinstance(v, list) else 0


def _num_dict_count(path: str, *keys) -> int:
    v = _load(path, {})
    if not isinstance(v, dict):
        return 0
    for k in keys:
        if isinstance(v.get(k), list):
            return len(v[k])
    return 0


def _achv_stats() -> dict:
    tts_log = _load("tts_log.json", [])
    if isinstance(tts_log, dict):
        tts_log = tts_log.get("records", []) or tts_log.get("logs", [])
    go = _load("go.json", {})
    go_games = len(go.get("games", [])) if isinstance(go, dict) else 0
    timebox = _load("timebox.json", {})
    caps = len(timebox.get("capsules", [])) if isinstance(timebox, dict) else 0
    annivs = len(timebox.get("anniversaries", [])) if isinstance(timebox, dict) else 0
    study = _load("study.json", {})
    sessions = len(study.get("sessions", [])) if isinstance(study, dict) else 0
    words = _load("words.json", {})
    word_n = len(words.get("words", words.get("list", []))) if isinstance(words, dict) else _num_list_len("words.json")
    world_log = _load("world_log.json", {})
    wl = len(world_log.get("entries", [])) if isinstance(world_log, dict) else _num_list_len("world_log.json")
    butterfly = _load("butterfly.json", {})
    flies = len(butterfly.get("caught", butterfly.get("collection", []))) if isinstance(butterfly, dict) else 0
    return {
        "chat": _num_list_len("chat_log.json"),
        "affinity": _agg_affinity_value(),
        "moments": _num_list_len("moments.json"),
        "memories": _num_list_len("memory.json"),
        "quotes": _num_list_len("quotes.json"),
        "diary": _num_dict_count("diary.json", "entries", "days"),
        "dreams": _num_dict_count("dream.json", "dreams", "records", "items"),
        "butterfly": flies,
        "img2img": _num_dict_count("img2img.json", "history", "works", "items"),
        "voice": len(tts_log) if isinstance(tts_log, list) else 0,
        "go": go_games,
        "capsules": caps,
        "anniversaries": annivs,
        "study": sessions,
        "words": word_n,
        "world": wl,
        "dates": _num_dict_count("date_log.json", "logs", "dates", "entries"),
        "books": _num_dict_count("books.json", "books", "items"),
        "solves": _num_dict_count("solves.json", "records", "items", "history"),
        "letters": _num_dict_count("letter.json", "letters", "items") or _num_dict_count("letters.json", "letters"),
        "timecall": _num_dict_count("timecall.json", "records"),
        "debate": _num_dict_count("debate.json", "debates"),
        "together": _num_dict_count("together.json", "photos"),
        "lifeline": _num_dict_count("lifeline.json", "lives"),
        "sos": _num_dict_count("sos.json", "records"),
    }


ACHIEVEMENTS = [
    # —— 初识 · 与他有关的一切开始 ——
    {"id": "hello", "cat": "初识", "icon": "👋", "name": "初次通话", "desc": "与他交换 10 条消息", "stat": "chat", "target": 10},
    {"id": "talker", "cat": "初识", "icon": "💬", "name": "话痨小姐", "desc": "累计 100 条消息", "stat": "chat", "target": 100},
    {"id": "chatterbox", "cat": "初识", "icon": "📻", "name": "午夜电台常客", "desc": "累计 500 条消息", "stat": "chat", "target": 500},
    {"id": "first_beat", "cat": "初识", "icon": "💜", "name": "心动初值", "desc": "心动值达到 50", "stat": "affinity", "target": 50},
    {"id": "beat_200", "cat": "初识", "icon": "💗", "name": "持续心动", "desc": "心动值达到 200", "stat": "affinity", "target": 200},
    {"id": "beat_600", "cat": "初识", "icon": "💞", "name": "心动过速", "desc": "心动值达到 600", "stat": "affinity", "target": 600},
    {"id": "beat_1500", "cat": "初识", "icon": "❤️‍🔥", "name": "心动永久产权", "desc": "心动值达到 1500", "stat": "affinity", "target": 1500},
    # —— 日常 · 把日子过成诗 ——
    {"id": "moments_5", "cat": "日常", "icon": "🌇", "name": "朋友圈常驻嘉宾", "desc": "他的朋友圈累计 5 条动态", "stat": "moments", "target": 5},
    {"id": "moments_20", "cat": "日常", "icon": "📸", "name": "时刻记录者", "desc": "朋友圈累计 20 条动态", "stat": "moments", "target": 20},
    {"id": "mem_10", "cat": "日常", "icon": "🧠", "name": "记忆管理员", "desc": "保存 10 条记忆", "stat": "memories", "target": 10},
    {"id": "mem_40", "cat": "日常", "icon": "🗂️", "name": "共同记忆库", "desc": "保存 40 条记忆", "stat": "memories", "target": 40},
    {"id": "quote_8", "cat": "日常", "icon": "📖", "name": "语录收藏家", "desc": "收藏 8 条他的语录", "stat": "quotes", "target": 8},
    {"id": "diary_7", "cat": "日常", "icon": "💌", "name": "七日之约", "desc": "写下 7 篇恋爱日记", "stat": "diary", "target": 7},
    {"id": "voice_10", "cat": "日常", "icon": "🔊", "name": "声控", "desc": "收听 10 次他的语音", "stat": "voice", "target": 10},
    {"id": "date_5", "cat": "日常", "icon": "🗺️", "name": "城市漫游者", "desc": "记录 5 次约会", "stat": "dates", "target": 5},
    {"id": "capsule_1", "cat": "日常", "icon": "🕰️", "name": "时间胶囊封存官", "desc": "封存 1 枚时光胶囊", "stat": "capsules", "target": 1},
    {"id": "anniv_1", "cat": "日常", "icon": "🎂", "name": "纪念日守护者", "desc": "记下 1 个纪念日", "stat": "anniversaries", "target": 1},
    # —— 学习 · 与他并肩变好 ——
    {"id": "study_5", "cat": "学习", "icon": "🎓", "name": "专注五段", "desc": "完成 5 次专注学习", "stat": "study", "target": 5},
    {"id": "study_20", "cat": "学习", "icon": "📚", "name": "长期主义者", "desc": "完成 20 次专注学习", "stat": "study", "target": 20},
    {"id": "words_50", "cat": "学习", "icon": "🔤", "name": "词汇量+50", "desc": "词库收录 50 个单词", "stat": "words", "target": 50},
    {"id": "books_2", "cat": "学习", "icon": "📗", "name": "共读伙伴", "desc": "书架上有 2 本书", "stat": "books", "target": 2},
    {"id": "solve_10", "cat": "学习", "icon": "🧮", "name": "题海同渡", "desc": "一起解 10 道题", "stat": "solves", "target": 10},
    # —— 创意 · 灵感的黑天鹅 ——
    {"id": "dream_3", "cat": "创意", "icon": "🌙", "name": "造梦师", "desc": "记录 3 个梦", "stat": "dreams", "target": 3},
    {"id": "bfly_5", "cat": "创意", "icon": "🦋", "name": "追蝶人", "desc": "蝶语花园捕获 5 只蝴蝶", "stat": "butterfly", "target": 5},
    {"id": "i2i_5", "cat": "创意", "icon": "🖼️", "name": "画境常客", "desc": "画境创作 5 幅作品", "stat": "img2img", "target": 5},
    {"id": "go_3", "cat": "创意", "icon": "⚫", "name": "手谈三局", "desc": "与他下 3 局围棋", "stat": "go", "target": 3},
    {"id": "letters_3", "cat": "创意", "icon": "✉️", "name": "见字如面", "desc": "收到 3 封他的信", "stat": "letters", "target": 3},
    # —— 世界 · 恋语市的旅人 ——
    {"id": "world_30", "cat": "世界", "icon": "🗺️", "name": "城市观察员", "desc": "世界日志累计 30 条", "stat": "world", "target": 30},
    {"id": "world_100", "cat": "世界", "icon": "🏙️", "name": "恋语市市民", "desc": "世界日志累计 100 条", "stat": "world", "target": 100},
    # —— 新星 · 只属于这个版本 ——
    {"id": "tc_1", "cat": "新星", "icon": "☎️", "name": "跨时通话", "desc": "完成 1 通时空热线", "stat": "timecall", "target": 1},
    {"id": "tc_5", "cat": "新星", "icon": "🌀", "name": "时间旅行者", "desc": "完成 5 通时空热线", "stat": "timecall", "target": 5},
    {"id": "deb_1", "cat": "新星", "icon": "⚖️", "name": "法庭旁听", "desc": "旁听 1 场双我辩论", "stat": "debate", "target": 1},
    {"id": "tg_7", "cat": "新星", "icon": "📅", "name": "合影七连拍", "desc": "累计 7 张合影", "stat": "together", "target": 7},
    {"id": "tg_30", "cat": "新星", "icon": "🎞️", "name": "一整面照片墙", "desc": "累计 30 张合影", "stat": "together", "target": 30},
    {"id": "life_1", "cat": "新星", "icon": "🧬", "name": "第一人生", "desc": "完整推演 1 段人生", "stat": "lifeline", "target": 1},
    {"id": "life_3", "cat": "新星", "icon": "♾️", "name": "轮回者", "desc": "推演 3 段人生", "stat": "lifeline", "target": 3},
    {"id": "sos_1", "cat": "新星", "icon": "🫂", "name": "被接住的人", "desc": "使用 1 次情绪急救箱", "stat": "sos", "target": 1},
]

ACHV_REWARD = 3  # 每枚成就奖励心动值（与 AFFINITY_DELTAS.achv 一致）


@router.get("/api/achv/list")
async def achv_list():
    stats = _achv_stats()
    data = _load(ACHV_FILE, {"claimed": []})
    claimed = data.get("claimed", []) if isinstance(data, dict) else []
    items = []
    unlocked_n = 0
    for a in ACHIEVEMENTS:
        val = int(stats.get(a["stat"], 0) or 0)
        prog = min(1.0, val / max(1, a["target"]))
        unlocked = val >= a["target"]
        if unlocked:
            unlocked_n += 1
        items.append({**a, "value": val, "progress": round(prog * 100, 1),
                      "unlocked": unlocked,
                      "claimed": a["id"] in claimed,
                      "reward": ACHV_REWARD})
    cats = []
    for c in ["初识", "日常", "学习", "创意", "世界", "新星"]:
        cs = [i for i in items if i["cat"] == c]
        cats.append({"cat": c, "items": cs,
                     "unlocked": sum(1 for i in cs if i["unlocked"])})
    level = 1 + unlocked_n // 4
    return {"cats": cats, "total": len(items), "unlocked": unlocked_n,
            "level": level, "level_name": f"恋爱研究员 Lv.{level}",
            "claimed_n": len([c for c in claimed])}


@router.post("/api/achv/claim")
async def achv_claim(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    aid = str(body.get("aid", "")).strip()
    achv = next((a for a in ACHIEVEMENTS if a["id"] == aid), None)
    if not achv:
        return JSONResponse({"error": "未知成就"}, status_code=404)
    stats = _achv_stats()
    if int(stats.get(achv["stat"], 0) or 0) < achv["target"]:
        return JSONResponse({"error": "还没有达成这枚成就"}, status_code=400)
    data = _load(ACHV_FILE, {"claimed": []})
    claimed = data.get("claimed", []) if isinstance(data, dict) else []
    if aid in claimed:
        return JSONResponse({"error": "这枚勋章已经领过了"}, status_code=400)
    claimed.append({"id": aid, "ts": _ts()})
    data["claimed"] = claimed
    _save(ACHV_FILE, data)
    _affinity("achv", f"解锁成就 · {achv['name']}")
    return {"ok": True, "reward": ACHV_REWARD,
            "name": achv["name"], "icon": achv["icon"]}


# ===========================================================================
# 5. 情绪急救箱：一键接通他的安抚频道
# ===========================================================================
SOS_MOODS = [
    {"id": "anxious", "name": "焦虑", "icon": "🌀", "desc": "事情堆着，心悬着"},
    {"id": "sad", "name": "难过", "icon": "🌧️", "desc": "说不清，就是低落"},
    {"id": "angry", "name": "愤怒", "icon": "🔥", "desc": "委屈和火气一起上来"},
    {"id": "lonely", "name": "孤独", "icon": "🌑", "desc": "周围很吵，只有我安静"},
    {"id": "panic", "name": "恐慌", "icon": "🌊", "desc": "心跳很快，停不下来"},
    {"id": "insomnia", "name": "失眠", "icon": "🌗", "desc": "很累了，但睡不着"},
    {"id": "empty", "name": "空虚", "icon": "🫧", "desc": "什么都提不起劲"},
]


@router.get("/api/sos/moods")
async def sos_moods():
    return {"moods": SOS_MOODS}


@router.post("/api/sos/help")
async def sos_help(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    mood_id = str(body.get("mood", "")).strip()
    mood = next((m for m in SOS_MOODS if m["id"] == mood_id), None)
    if not mood:
        return JSONResponse({"error": "请选择一种情绪"}, status_code=400)
    try:
        intensity = max(1, min(5, int(body.get("intensity", 3))))
    except (TypeError, ValueError):
        intensity = 3
    note = str(body.get("note", "")).strip()[:120]
    memories = _agg_memories(6)
    sys_prompt = (
        f"{_persona_core()}\n\n【情绪急救箱设定】她现在情绪需要立刻被接住。她的状态：{mood['name']}"
        f"（强度{intensity}/5）。补充说明：{note or '（没有多说）'}。\n"
        f"你们的关系记忆：\n" + ("\n".join("- " + m for m in memories) if memories else "-（暂无）") +
        "\n\n请生成一份急救方案，要求：不说教、不敷衍、不堆大道理；先共情再行动；"
        "强度越高，语气越稳越慢。输出 JSON：\n"
        "greet: 他接通后说的第一句话(50字内，像深夜接起电话)\n"
        "steps: 3步急救行动，每步{title:10字内, detail:50字内}，第1步永远是呼吸/落地类的身体动作\n"
        "note: 他手写给你的一张短笺(70字内，落款'——许墨')\n"
        "voice: 一段适合读出来的安抚语音稿(110字内，口语、慢、有停顿感)\n"
        "tomorrow: 明天醒来他会发来的一句话(30字内)")
    try:
        r = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "……（她按下了呼叫键）"}], max_tokens=1800)
    except Exception:
        r = {}
    steps = []
    for s in r.get("steps") or []:
        if isinstance(s, dict) and s.get("title"):
            steps.append({"title": str(s["title"]).strip()[:20],
                          "detail": str(s.get("detail", "")).strip()[:90]})
    if len(steps) < 3:
        steps = [
            {"title": "先呼吸", "detail": "跟着节奏：吸气4秒，屏住7秒，呼气8秒。我在，不用急。"},
            {"title": "落地", "detail": "说出你眼前5样东西的名字。把注意力借给此刻的房间。"},
            {"title": "交给我", "detail": "把最沉的那件事说给我，或者先不说也可以。我们有一整夜。"},
        ]
    item = {"id": _nid(), "mood": mood["name"], "mood_id": mood["id"],
            "icon": mood["icon"], "intensity": intensity, "note": note,
            "greet": str(r.get("greet") or "……我在。慢慢说，或者先不说，我陪你坐一会儿。").strip()[:90],
            "steps": steps,
            "note_card": str(r.get("note") or "情绪不是故障，是信号。你不需要立刻好起来，我会等。 ——许墨").strip()[:140],
            "voice": str(r.get("voice") or "别怕。把肩膀放下来，我在这里，哪儿也不去。慢慢呼吸，跟着我……很好，就是这样。").strip()[:200],
            "tomorrow": str(r.get("tomorrow") or "醒来记得喝温水。昨晚的你，已经很勇敢了。").strip()[:60],
            "ts": _ts()}
    data = _load(SOS_FILE, {"records": []})
    data.setdefault("records", []).append(item)
    data["records"] = data["records"][-60:]
    _save(SOS_FILE, data)
    _affinity("sos", f"情绪急救 · {mood['name']}")
    return {"plan": item}


@router.get("/api/sos/history")
async def sos_history():
    data = _load(SOS_FILE, {"records": []})
    records = data.get("records", [])[::-1]
    return {"records": records[:30], "total": len(records)}


# ===========================================================================
# 6. 人生模拟器：与许墨推演一整个人生
# ===========================================================================
LIFELINE_STAGES = [
    {"age": 27, "label": "两年后"}, {"age": 29, "label": "四年后"},
    {"age": 32, "label": "七年后"}, {"age": 35, "label": "十年后"},
    {"age": 40, "label": "十五年后"}, {"age": 47, "label": "二十年后"},
    {"age": 55, "label": "二十八年后"}, {"age": 65, "label": "三十八年后"},
]

LIFE_EFFECTS = {"bond": "羁绊", "career": "共同事业", "regret": "遗憾"}


def _life_sysprompt(life: dict) -> str:
    player = _agg_player()
    her_name = str(player.get("name", "") or "她")[:12]
    history = life.get("history", [])
    hist_txt = ""
    for h in history[-6:]:
        eff = "、".join(f"{LIFE_EFFECTS.get(k, k)}{v:+d}" for k, v in (h.get("effects") or {}).items())
        hist_txt += f"\n- {h.get('stage_label', '')}：她选了「{h.get('choice', '')}」({eff})"
    return (
        f"{_persona_core()}\n\n【人生模拟器设定】你在为她推演一个与许墨相伴的人生剧本。"
        f"主角：{her_name}与许墨。当前属性：羁绊{life.get('bond', 50)}、共同事业{life.get('career', 20)}、"
        f"遗憾{life.get('regret', 0)}（0-100）。已发生的抉择：{hist_txt or '（刚刚开始）'}\n"
        "要求：真实、克制、有烟火气，允许遗憾存在；每个选择都有代价，没有完美选项；"
        "许墨始终是许墨——温柔、理性、把她的自由看得比占有更重。\n"
        "输出 JSON：\n"
        "title: 本阶段标题(12字内)\n"
        "scene: 本阶段场景描写(110字内，第二人称'你'视角，有画面感)\n"
        "choices: 3个选项，每个{label:14字内, hint:18字内的代价暗示, effects:{bond/career/regret: -12~+12整数}}\n"
        "（effects 至多写 2 项，且必须有正有负或零和）")


def _stage_of(node_idx: int) -> dict:
    return LIFELINE_STAGES[min(node_idx, len(LIFELINE_STAGES) - 1)]


async def _life_next_node(life: dict):
    idx = len(life.get("history", []))
    if idx >= len(LIFELINE_STAGES):
        return None  # 该进入结局
    stage = _stage_of(idx)
    try:
        r = await _llm_json([
            {"role": "system", "content": _life_sysprompt(life)},
            {"role": "user", "content": f"请生成「{stage['label']}」({stage['age']}岁)的人生节点。"}],
            max_tokens=2200)
    except Exception:
        r = {}
    choices = []
    for c in r.get("choices") or []:
        if isinstance(c, dict) and c.get("label"):
            eff = {}
            for k, v in (c.get("effects") or {}).items():
                if k in ("bond", "career", "regret"):
                    try:
                        eff[k] = max(-12, min(12, int(v)))
                    except (TypeError, ValueError):
                        pass
            choices.append({"label": str(c["label"]).strip()[:18],
                            "hint": str(c.get("hint", "")).strip()[:30], "effects": eff})
    if len(choices) < 3:
        choices = [
            {"label": "留在恋语市，守着熟悉的一切", "hint": "安稳，但可能错过远方", "effects": {"bond": 6, "career": -2}},
            {"label": "跟他去更远的地方", "hint": "辽阔，但一切重来", "effects": {"bond": 4, "career": 8, "regret": 3}},
            {"label": "各自冷静一段时间", "hint": "自由，但距离会留下痕迹", "effects": {"bond": -6, "regret": 5}},
        ]
    return {"title": str(r.get("title") or "人生的十字路口").strip()[:16],
            "stage_label": stage["label"], "age": stage["age"],
            "scene": str(r.get("scene") or "又是一年。窗外的事像潮水，你站在岸边，要决定下一程的方向。").strip()[:220],
            "choices": choices}


def _life_apply(life: dict, choice: dict):
    for k, v in (choice.get("effects") or {}).items():
        if k in ("bond", "career"):
            life[k] = max(0, min(100, life.get(k, 50) + v))
        elif k == "regret":
            life["regret"] = max(0, min(100, life.get("regret", 0) + v))


async def _life_ending(life: dict):
    history = life.get("history", [])
    choices_txt = "\n".join(f"- {h.get('stage_label', '')}：{h.get('choice', '')}" for h in history)
    try:
        r = await _llm_json([
            {"role": "system", "content": (
                f"{_persona_core()}\n【人生模拟器·终章】请为这段人生写终章。她的一生抉择：{choices_txt}\n"
                f"终局属性：羁绊{life.get('bond', 50)}、共同事业{life.get('career', 20)}、遗憾{life.get('regret', 0)}。\n"
                "输出 JSON：\n"
                "ending_title: 结局名(10字内，像小说章节名)\n"
                "ending: 终章场景(150字内，65岁的黄昏视角，回望这一生)\n"
                "memoir_title: 回忆录书名(8字内)\n"
                "memoir: 回忆录正文(240字内，第三人称，把所有选择的意义收拢，最后一句必须是许墨说的一句话)\n"
                "medal: 一枚人生勋章名(8字内)")},
            {"role": "user", "content": "写下终章。"}], max_tokens=2400)
    except Exception:
        r = {}
    ending = {
        "ending_title": str(r.get("ending_title") or "漫长的告别").strip()[:14],
        "ending": str(r.get("ending") or "黄昏的时候，你坐在花园里。蝴蝶落在他的旧毛衣上，像一封迟到的信。这一生不完美，但每一程都有他。").strip()[:260],
        "memoir_title": str(r.get("memoir_title") or "与许墨的一生").strip()[:12],
        "memoir": str(r.get("memoir") or "后来的人们问她，这一生最重要的决定是哪一个。她想了很久，说：每一个。因为每一个岔路口，那个人都在。许墨说：'概率不为零的事，就值得用一生去验证。你就是那个概率。'").strip()[:400],
        "medal": str(r.get("medal") or "一生一人").strip()[:10],
        "bond": life.get("bond", 50), "career": life.get("career", 20),
        "regret": life.get("regret", 0),
    }
    return ending


@router.post("/api/lifeline/start")
async def lifeline_start(req: Request = None):
    data = _load(LIFELINE_FILE, {"lives": []})
    lives = data.get("lives", [])
    cur = next((l for l in lives if not l.get("finished")), None)
    if cur:
        return JSONResponse({"error": "上一段人生还没有走完，先完成它或提前写好终章"},
                            status_code=400)
    life = {"id": _nid(), "started": _ts(), "finished": False,
            "bond": 50, "career": 20, "regret": 0,
            "history": [], "node": None, "ending": None}
    node = await _life_next_node(life)
    life["node"] = node
    lives.append(life)
    data["lives"] = lives[-40:]
    _save(LIFELINE_FILE, data)
    return {"life": life}


@router.get("/api/lifeline/current")
async def lifeline_current():
    data = _load(LIFELINE_FILE, {"lives": []})
    life = next((l for l in data.get("lives", []) if not l.get("finished")), None)
    return {"life": life}


@router.post("/api/lifeline/choose")
async def lifeline_choose(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    idx = body.get("idx")
    data = _load(LIFELINE_FILE, {"lives": []})
    life = next((l for l in data.get("lives", []) if not l.get("finished")), None)
    if not life:
        return JSONResponse({"error": "当前没有进行中的人生"}, status_code=404)
    node = life.get("node") or {}
    choices = node.get("choices", [])
    try:
        ci = int(idx)
        choice = choices[ci]
    except (TypeError, ValueError, IndexError):
        return JSONResponse({"error": "无效的选择"}, status_code=400)
    _life_apply(life, choice)
    life.setdefault("history", []).append({
        "stage_label": node.get("stage_label", ""), "age": node.get("age"),
        "title": node.get("title", ""), "scene": node.get("scene", ""),
        "choice": choice.get("label", ""), "effects": choice.get("effects", {})})
    if len(life["history"]) >= len(LIFELINE_STAGES):
        ending = await _life_ending(life)
        life["ending"] = ending
        life["finished"] = True
        life["node"] = None
        _save(LIFELINE_FILE, data)
        _affinity("lifeline_end", f"走完一生 · {ending['ending_title']}")
        return {"life": life, "ended": True}
    nxt = await _life_next_node(life)
    life["node"] = nxt
    _save(LIFELINE_FILE, data)
    return {"life": life, "ended": False}


@router.post("/api/lifeline/finish")
async def lifeline_finish(req: Request = None):
    data = _load(LIFELINE_FILE, {"lives": []})
    life = next((l for l in data.get("lives", []) if not l.get("finished")), None)
    if not life:
        return JSONResponse({"error": "当前没有进行中的人生"}, status_code=404)
    if len(life.get("history", [])) < 2:
        return JSONResponse({"error": "至少走过两个节点，才够写终章"}, status_code=400)
    ending = await _life_ending(life)
    life["ending"] = ending
    life["finished"] = True
    life["node"] = None
    _save(LIFELINE_FILE, data)
    _affinity("lifeline_end", f"提前写好终章 · {ending['ending_title']}")
    return {"life": life, "ended": True}


@router.get("/api/lifeline/lives")
async def lifeline_lives():
    data = _load(LIFELINE_FILE, {"lives": []})
    lives = [l for l in data.get("lives", []) if l.get("finished")][::-1]
    return {"lives": lives[:24], "total": len(lives)}


@router.delete("/api/lifeline/lives/{lid}")
async def lifeline_del(lid: str):
    data = _load(LIFELINE_FILE, {"lives": []})
    data["lives"] = [l for l in data.get("lives", []) if l.get("id") != lid]
    _save(LIFELINE_FILE, data)
    return {"ok": True}
