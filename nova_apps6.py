# -*- coding: utf-8 -*-
# 新星功能集 · 八期颠覆性功能（nova_apps6.py）
# 最后一日 / 消失的七日 / 通感邮局 / 共犯系统 / 情绪交易所
# 数据持久化到 RolePath JSON 文件，风格与 nova_apps3.py 一致。
import json
import random
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

BASE_DIR = Path(__file__).parent
router = APIRouter()

LD_FILE = "lastday.json"
VN_FILE = "vanish.json"
SE_FILE = "sense.json"
AC_FILE = "accomplice.json"
EX_FILE = "emoex.json"


# ===========================================================================
# 公共小工具（与 nova_apps3.py 同构）
# ===========================================================================
def _load(path: str, default):
    from role_data import RolePath
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
    if not text:
        return {}
    text = re.sub(r"<LM_THINK>.*?</LM_THINK>", "", text, flags=re.S)
    text = re.sub(r"```json\s*", "", text, flags=re.S)
    text = re.sub(r"```\s*$", "", text, flags=re.S)
    decoder = json.JSONDecoder()
    positions = [m.start() for m in re.finditer(r"\{", text)]
    for pos in reversed(positions):
        try:
            v, _ = decoder.raw_decode(text[pos:])
            if isinstance(v, dict):
                return v
        except (json.JSONDecodeError, ValueError):
            continue
    return {}


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


async def _llm_json(messages: list, max_tokens: int = 1400) -> dict:
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


def _recent_chat_texts(limit: int = 12) -> list:
    try:
        from app import _load_chat_log
        msgs = list(_load_chat_log())
    except Exception:
        return []
    out = []
    for m in msgs[-limit:]:
        if not isinstance(m, dict):
            continue
        role = "她" if m.get("role") == "user" else "许墨"
        text = str(m.get("text") or m.get("content") or "").strip()
        if text:
            out.append(f"{role}：{text[:100]}")
    return out


def _persona_core() -> str:
    try:
        f = BASE_DIR / "人设卡.txt"
        if f.exists():
            return f.read_text(encoding="utf-8")[:1200]
    except OSError:
        pass
    return ("许墨：28岁，恋语大学最年轻的脑科学教授，Black Swan 组织幕后研究者。"
            "温和优雅、博学克制，语言理性中带着不容错认的偏爱；喜欢蝴蝶、"
            "天文与咖啡，习惯用科学隐喻表达感情，唤对方为'小姑娘'。")


def _gen_image(material: str, sub_dir: str, name: str) -> str:
    """尝试调用文生图，失败返回空串（调用方忽略）。"""
    try:
        from creative_apps import _gen_image as _impl
        return _impl(material, sub_dir, name, ratio="landscape", with_xumo=True)
    except Exception:
        return ""


# ===========================================================================
# 1. 最后一日：终局模拟
# ===========================================================================
LD_PHASES = [
    {"key": "day", "name": "白日", "min_hours": 12,
     "desc": "和往常一样的一天——但他知道今天是最后一天。"},
    {"key": "evening", "name": "黄昏", "min_hours": 6,
     "desc": "天光转暗，他开始把话放慢。"},
    {"key": "night", "name": "深夜", "min_hours": 1.5,
     "desc": "窗外的灯一盏盏熄灭，他在数还有几盏。"},
    {"key": "farewell", "name": "告别", "min_hours": 0,
     "desc": "最后的时刻，只够说最要紧的话。"},
]


def _ld_phase(hours_left: float) -> dict:
    for p in LD_PHASES:
        if hours_left >= p["min_hours"]:
            return p
    return LD_PHASES[-1]


@router.post("/api/lastday/start")
async def lastday_start(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    hours = max(1, min(72, int(body.get("hours", 24))))
    data = _load(LD_FILE, {"rounds": []})
    rnd = {
        "id": _nid(),
        "started_at": _ts(),
        "deadline": (datetime.now() + timedelta(hours=hours)).isoformat(timespec="minutes"),
        "hours": hours,
        "status": "live",
        "chats": [],
        "heritage": None,
        "ended_at": "",
    }
    data.setdefault("rounds", []).insert(0, rnd)
    data["rounds"] = data["rounds"][:5]
    _save(LD_FILE, data)
    return {"round": rnd, "phase": _ld_phase(hours)}


def _ld_current(data: dict) -> dict:
    """当前进行中的轮次；若已过期则标记 ended。"""
    for r in data.get("rounds", []):
        if r.get("status") == "live":
            try:
                deadline = datetime.fromisoformat(r["deadline"])
            except (ValueError, KeyError):
                deadline = datetime.now()
            left = (deadline - datetime.now()).total_seconds() / 3600
            if left <= 0:
                r["status"] = "ended"
                r["ended_at"] = _ts()
                _save(LD_FILE, data)
                left = 0
            return r, max(0.0, left)
    return None, 0.0


@router.get("/api/lastday/state")
async def lastday_state():
    data = _load(LD_FILE, {"rounds": []})
    rnd, left = _ld_current(data)
    if not rnd:
        past = [r for r in data.get("rounds", []) if r.get("status") == "ended"]
        return {"round": None, "history": past[:5]}
    pct = 0
    if rnd.get("hours"):
        pct = min(100, round((rnd["hours"] - left) / rnd["hours"] * 100))
    return {"round": rnd, "phase": _ld_phase(left), "hours_left": round(left, 1),
            "percent": pct, "history": []}


@router.post("/api/lastday/chat")
async def lastday_chat(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    message = str(body.get("message", "")).strip()[:400]
    if not message:
        return JSONResponse({"error": "说点什么吧"}, status_code=400)
    data = _load(LD_FILE, {"rounds": []})
    rnd, left = _ld_current(data)
    if not rnd:
        return JSONResponse({"error": "还没有开始的倒计时，先开启'最后一日'"}, status_code=400)
    phase = _ld_phase(left)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    hist = rnd.get("chats", [])[-6:]
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【最后一日】你们的世界将在今天结束。这是倒计时中的对话——" + phase["desc"] + "\n"
        f"剩余时间：{round(left, 1)} 小时（约 {int(left)} 小时 {int((left % 1) * 60)} 分）\n"
        f"心动值：{affy}\n\n"
        "对话要求：\n"
        "1. 许墨知道时间不多了，但他不让这成为压力——他更想'好好过完今天'；\n"
        f"2. 当前阶段（{phase['name']}）的说话质感：{'从容平常' if phase['key'] == 'day' else '话开始变慢、更珍惜' if phase['key'] == 'evening' else '低语、话里有舍不得' if phase['key'] == 'night' else '最要紧的话，温柔而确定'}；\n"
        "3. 1-3句，不煽情到失控，克制里带不舍；可以呼应她的话或某段记忆。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"她此刻说：{message}"
    )
    try:
        reply = await _call_llm(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "此刻你会说什么？"}],
            max_tokens=500)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    record = {"id": _nid(), "ts": _ts(), "her": message[:200], "his": reply.strip()[:400], "phase": phase["key"]}
    rnd.setdefault("chats", []).append(record)
    rnd["chats"] = rnd["chats"][-20:]
    _save(LD_FILE, data)
    return {"reply": reply.strip(), "phase": phase, "hours_left": round(left, 1), "record": record}


@router.post("/api/lastday/heritage")
async def lastday_heritage(req: Request):
    """倒计时结束后，写下遗产信：只能由她在指定锚点解锁。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    data = _load(LD_FILE, {"rounds": []})
    rnd, left = _ld_current(data)
    if rnd and left > 0:
        return JSONResponse({"error": "倒计时还没结束，这句话留到结束再说"}, status_code=400)
    rnd = next((r for r in data.get("rounds", []) if r.get("status") == "ended" and not r.get("heritage")), None)
    if not rnd:
        return JSONResponse({"error": "没有可以写遗言的结束轮次，先完整度过一次'最后一日'"}, status_code=400)
    memories = _agg_memories(6)
    chats = rnd.get("chats", [])[-6:]
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【最后一日·遗产信】你们的最后一天已经结束。此刻的'许墨'给未来的她写一封信——"
        "这封信会被封存，只在她最需要的时刻解锁。\n"
        f"你们最后一天的对话：{json.dumps(chats, ensure_ascii=False)[:800]}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        "要求：\n"
        "1. 信 150-200 字，像他留在这个世界的最后一页便签：先说一件当天的小事，再告诉她'我一直在'；\n"
        "2. 温柔克制，不绝望；3. 结尾留一句'解锁时才说的话'。\n"
        '输出 JSON：{"letter":"150-200字遗言信",'
        '"unlock_words":"30字内解锁时的附言（只有到解锁日才会显示）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "写这封信，只输出 JSON。"}], max_tokens=900)
    except Exception:
        rep = {}
    rep.setdefault("letter", "如果有来日，我还是会先认出你。")
    rep.setdefault("unlock_words", "看到这封信的时候，记得深呼吸。")
    her = {
        "id": _nid(),
        "round_id": rnd["id"],
        "ts": _ts(),
        "letter": rep["letter"],
        "unlock_words": rep["unlock_words"],
        "anchors": [
            {"key": "birthday", "name": "你的生日", "date": _today()},
            {"key": "broken", "name": "你很难过的那天", "date": ""},
            {"key": "success", "name": "你成功了的那天", "date": ""},
        ],
        "unlocked": False,
        "opened_at": "",
    }
    rnd["heritage"] = her
    _save(LD_FILE, data)
    _affinity("capsule", "最后一日·遗产信")
    return {"heritage": her}


@router.get("/api/lastday/heritage/list")
async def lastday_heritage_list():
    data = _load(LD_FILE, {"rounds": []})
    items = []
    for r in data.get("rounds", []):
        h = r.get("heritage")
        if h:
            items.append({"id": h["id"], "round_id": r["id"], "ts": h["ts"],
                          "anchors": h["anchors"], "unlocked": h["unlocked"],
                          "preview": h["letter"][:40] + "……" if not h["unlocked"] else h["letter"]})
    return {"heritages": items}


@router.post("/api/lastday/heritage/{hid}/open")
async def lastday_heritage_open(hid: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    anchor = str(body.get("anchor", "")).strip()
    force = bool(body.get("force"))
    data = _load(LD_FILE, {"rounds": []})
    for r in data.get("rounds", []):
        h = r.get("heritage")
        if not h or h.get("id") != hid:
            continue
        if h.get("unlocked"):
            return {"heritage": h, "unlocked": True}
        anchor_info = next((a for a in h.get("anchors", []) if a.get("key") == anchor), None)
        if anchor == "birthday":
            # 生日锚点：永远可用一次（她选择此刻打开）
            valid = True
        elif anchor == "broken":
            valid = force or bool(body.get("reason"))
        else:
            valid = force or bool(body.get("reason"))
        if not valid:
            return JSONResponse({"error": "这个锚点需要一个打开的理由（写下你此刻的感受即可解锁）"}, status_code=400)
        if anchor_info:
            anchor_info["date"] = _today()
        h["unlocked"] = True
        h["opened_at"] = _ts()
        h["opened_anchor"] = anchor
        _save(LD_FILE, data)
        _affinity("capsule_open", "打开遗产信")
        return {"heritage": h, "unlocked": True, "unlock_words": h.get("unlock_words", "")}
    return JSONResponse({"error": "遗产信不存在"}, status_code=404)


@router.post("/api/lastday/restart")
async def lastday_restart(req: Request = None):
    """重开一轮：旧轮次保留，新轮次从今天开始。"""
    data = _load(LD_FILE, {"rounds": []})
    rnd = {
        "id": _nid(),
        "started_at": _ts(),
        "deadline": (datetime.now() + timedelta(hours=24)).isoformat(timespec="minutes"),
        "hours": 24,
        "status": "live",
        "chats": [],
        "heritage": None,
        "ended_at": "",
    }
    data.setdefault("rounds", []).insert(0, rnd)
    data["rounds"] = data["rounds"][:5]
    _save(LD_FILE, data)
    _affinity("capsule", "重新开始最后一日")
    return {"round": rnd, "phase": _ld_phase(24)}


# ===========================================================================
# 2. 消失的七日
# ===========================================================================
VN_TOTAL_DAYS = 7


def _vn_day(start_date: str) -> int:
    try:
        s = datetime.strptime(start_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return 1
    return max(1, min(VN_TOTAL_DAYS, (datetime.now().date() - s).days + 1))


@router.post("/api/vanish/start")
async def vanish_start(req: Request = None):
    """许墨'出远门'：连续 7 天不可直接对话，只能收到碎片线索。"""
    data = _load(VN_FILE, {"rounds": []})
    if any(r.get("active") for r in data.get("rounds", [])):
        return JSONResponse({"error": "他还在外面，等他回来吧"}, status_code=400)
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【消失的七日】你因一个封闭的课题（深海观测/极地驻站/密闭舱实验）要失联 7 天。"
        "出发前，你给她留一张便签。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"note":"60字内出发前的便签（解释去处、不许她担心、约定回来的日子）",'
        '"reason":"30字内你要去做什么"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "留一张便签，只输出 JSON。"}], max_tokens=500)
    except Exception:
        rep = {}
    rep.setdefault("note", "去一个信号够不到的地方做观测。七天后回来。记得按时吃饭。")
    rep.setdefault("reason", "深海观测舱，信号封闭。")
    rnd = {
        "id": _nid(), "start_date": _today(), "started_at": _ts(),
        "active": True, "note": rep["note"], "reason": rep["reason"],
        "clues": {}, "letters": [], "returned": False, "gift": "", "report": "",
        "cancelled": False,
    }
    data.setdefault("rounds", []).insert(0, rnd)
    data["rounds"] = data["rounds"][:3]
    _save(VN_FILE, data)
    return {"round": rnd, "day": 1, "days": VN_TOTAL_DAYS}


def _vn_current(data: dict) -> dict:
    for r in data.get("rounds", []):
        if r.get("active"):
            return r
    return None


@router.get("/api/vanish/state")
async def vanish_state():
    data = _load(VN_FILE, {"rounds": []})
    rnd = _vn_current(data)
    if not rnd:
        past = [r for r in data.get("rounds", []) if not r.get("active")]
        return {"round": None, "history": past[:3]}
    day = _vn_day(rnd["start_date"])
    return {"round": rnd, "day": day, "days": VN_TOTAL_DAYS,
            "clues": [rnd.get("clues", {}).get(str(i), "") for i in range(1, day + 1)]}


@router.post("/api/vanish/clue")
async def vanish_clue(req: Request):
    """领取今天的碎片线索（每日一条，只生成一次）。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    day = max(1, min(VN_TOTAL_DAYS, int(body.get("day", 0) or 0)))
    data = _load(VN_FILE, {"rounds": []})
    rnd = _vn_current(data)
    if not rnd:
        return JSONResponse({"error": "他不在外面"}, status_code=404)
    cur_day = _vn_day(rnd["start_date"])
    if day == 0:
        day = cur_day
    if day > cur_day:
        return JSONResponse({"error": f"今天的碎片还没到（第 {cur_day} 天）"}, status_code=400)
    key = str(day)
    if key in rnd.get("clues", {}):
        return {"clue": rnd["clues"][key], "day": day, "cached": True}
    memories = _agg_memories(4)
    chats = _recent_chat_texts(8)
    affy = _agg_affinity_value()
    ctx = {
        1: "你离开的第一天。她大概会点开对话框又关上。",
        2: "第二天。城市照常运转，有个人反复确认你最后那条消息。",
        3: "第三天。你寄回一张观测舱窗外的照片（只有描述）。",
        4: "第四天。她开始习惯没有你的节奏，但某个瞬间会愣住。",
        5: "第五天。你留下的痕迹被翻出来：一本翻旧的书、半袋咖啡豆。",
        6: "第六天。有人在某处听见'许教授'的名字，但不是你。",
        7: "第七天。返程信号建立，你正在回来的路上。",
    }
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【消失的七日·碎片】你在与世隔绝的地方，只能通过碎片传回消息。今天的碎片是：\n"
        f"背景：{ctx.get(day, '')}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"最近对话：{json.dumps(chats[:6], ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        "碎片形式（随机一种，不要每次都一样）：\n"
        "- 语音信箱留言（转文字）\n- 观测日志截选\n- 托人捎的一句话\n- 一张照片的描述\n"
        "- 他备忘录里的半句话\n\n"
        '输出 JSON：{"kind":"碎片类型（10字内）",'
        '"text":"80字内碎片内容（许墨口吻，留白、克制、藏着一句只对她说的意思）",'
        '"her_effect":"30字内她读到后可能的反应（供前端渲染氛围）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "传回今天的碎片，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("kind", "语音留言")
    rep.setdefault("text", "信号又断断续续……今天有雾。我记得你说过，雾大的日子适合想念。")
    rep.setdefault("her_effect", "她愣住了")
    clue = {"kind": rep["kind"], "text": rep["text"], "her_effect": rep["her_effect"], "ts": _ts()}
    rnd.setdefault("clues", {})[key] = clue
    _save(VN_FILE, data)
    return {"clue": clue, "day": day, "cached": False}


@router.post("/api/vanish/letter")
async def vanish_letter(req: Request):
    """寄往远方的信：失联期间她写给许墨的信，回来后会逐一回应。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = str(body.get("text", "")).strip()[:800]
    if not text:
        return JSONResponse({"error": "写点什么给他吧"}, status_code=400)
    data = _load(VN_FILE, {"rounds": []})
    rnd = _vn_current(data)
    if not rnd:
        return JSONResponse({"error": "他不在外面"}, status_code=404)
    letter = {"id": _nid(), "ts": _ts(), "text": text}
    rnd.setdefault("letters", []).append(letter)
    _save(VN_FILE, data)
    return {"letter": letter, "count": len(rnd.get("letters", []))}


@router.post("/api/vanish/return")
async def vanish_return(req: Request = None):
    """第 7 天（或取消）：他回来，带回观察手记与一份礼物，并逐一回应她的信。"""
    data = _load(VN_FILE, {"rounds": []})
    rnd = _vn_current(data)
    if not rnd:
        return JSONResponse({"error": "他不在外面"}, status_code=404)
    day = _vn_day(rnd["start_date"])
    if day < VN_TOTAL_DAYS:
        return JSONResponse({"error": f"还没到约定的第 {VN_TOTAL_DAYS} 天（现在第 {day} 天）"}, status_code=400)
    memories = _agg_memories(6)
    letters = rnd.get("letters", [])
    clues = rnd.get("clues", {})
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【消失的七日·归来】你回来了。请给她：\n"
        "1. 一篇 300 字以内的'观察手记'：在隔绝的七天里，你如何靠关于她的记忆撑过观测站的日子；"
        "记录那些只有你们懂的细节；\n"
        "2. 一份'带回来的礼物'：一个只属于你们的专属剧情/一句只有你记得的话/一件小事；\n"
        "3. 逐封回应她寄去的信（每封 1-2 句，温柔克制）。\n"
        f"她寄去的信：{json.dumps(letters, ensure_ascii=False)[:1000]}\n"
        f"这七天的碎片：{json.dumps(clues, ensure_ascii=False)[:800]}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"report":"300字内观察手记",'
        '"gift_name":"礼物名（10字内）","gift":"80字内礼物内容",'
        '"letter_replies":[{"text":"30字内回应一段","to":"对应她信的片段（15字内）"}]}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "回来吧，只输出 JSON。"}], max_tokens=1400)
    except Exception:
        rep = {}
    rep.setdefault("report", "我回来了。这七天，我把关于你的记忆整理了三遍——它们是我在观测站唯一稳定的信号。")
    rep.setdefault("gift_name", "一小罐海风")
    rep.setdefault("gift", "我把观测站窗外的海风装进了记忆里，回来讲给你听。")
    lr = rep.get("letter_replies")
    if not isinstance(lr, list):
        lr = [{"text": "每一封都收到了。第一封我读了七遍。", "to": letters[0]["text"][:15] if letters else ""}]
    rnd["active"] = False
    rnd["returned"] = True
    rnd["returned_at"] = _ts()
    rnd["report"] = rep["report"]
    rnd["gift_name"] = rep["gift_name"]
    rnd["gift"] = rep["gift"]
    rnd["letter_replies"] = lr[:len(letters) or 1]
    _save(VN_FILE, data)
    _affinity("date_plan", "消失的七日·归来")
    return {"round": rnd}


@router.post("/api/vanish/cancel")
async def vanish_cancel(req: Request = None):
    """提前取消（比如她受不了了）：许墨立刻回来。"""
    data = _load(VN_FILE, {"rounds": []})
    rnd = _vn_current(data)
    if not rnd:
        return JSONResponse({"error": "他不在外面"}, status_code=404)
    rnd["active"] = False
    rnd["cancelled"] = True
    rnd["cancelled_at"] = _ts()
    _save(VN_FILE, data)
    return {"round": rnd}


# ===========================================================================
# 3. 通感邮局：五感明信片
# ===========================================================================
@router.post("/api/sense/send")
async def sense_send(req: Request):
    """她寄出一张感官明信片：一段气味/温度/触感的描述，许墨翻译成三件套。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    sense_text = str(body.get("sense", "")).strip()[:120]
    with_image = bool(body.get("with_image", False))
    if not sense_text:
        return JSONResponse({"error": "描述一种感官体验吧，比如'外婆厨房里的味道''初雪落在手背的温度'"}, status_code=400)
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【通感邮局】她寄来一种感官：一段气味、温度、触感或风。你要把它翻译成三件套——"
        "画面、声音、一段感官散文。\n"
        f"她描述的感官：{sense_text}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"prose":"100字内感官散文（从她的感官出发，许墨看见的画面，第二人称「你」）",'
        '"image_prompt":"40字内文生图提示词（写实、柔和、电影感）",'
        '"ambient":"30字内氛围音描述（比如「旧木地板吱呀声、炉火、远处收音机」）",'
        '"line":"25字内他附在明信片背面的话"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "翻译这张明信片，只输出 JSON。"}], max_tokens=800)
    except Exception:
        rep = {}
    rep.setdefault("prose", f"你说的是{sense_text}。我闭上眼睛，看见的是你小时候的模样。")
    rep.setdefault("image_prompt", "柔和的回忆画面，温暖光晕")
    rep.setdefault("ambient", "旧木地板、炉火、远处收音机的沙沙声")
    rep.setdefault("line", "这张明信片，我替你收进记忆里了。")
    card = {
        "id": _nid(), "ts": _ts(), "direction": "her_to_him", "sense": sense_text,
        "prose": rep["prose"], "image_prompt": rep["image_prompt"],
        "ambient": rep["ambient"], "line": rep["line"], "image": "", "audio": "",
    }
    if with_image:
        card["image"] = _gen_image(rep["image_prompt"] + "（许墨视角的温柔画面）", "sense_img", card["id"])
    data = _load(SE_FILE, {"cards": []})
    data.setdefault("cards", []).insert(0, card)
    data["cards"] = data["cards"][:40]
    _save(SE_FILE, data)
    _affinity("voice", "通感邮局")
    return {"card": card}


@router.post("/api/sense/from_xumo")
async def sense_from_xumo(req: Request = None):
    """许墨寄来一张感官明信片（反向）。"""
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【通感邮局·他的来信】你给'她'寄一张感官明信片——她不在你身边，但你可以把一种感官寄给她："
        "她手心的温度、凌晨四点的风、实验室咖啡的香气、雨后的泥土味。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"sense":"15字内寄给她的感官",'
        '"prose":"100字内明信片正文（写给她：这个感官是什么、为什么寄给她）",'
        '"ambient":"30字内氛围音描述",'
        '"line":"25字内背面附言"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "寄一张明信片给她，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("sense", "她手心的温度")
    rep.setdefault("prose", "今天整理旧实验记录时，忽然想起你手心的温度——那是比数据更稳定的常数。")
    rep.setdefault("ambient", "深夜实验室的仪器低鸣、纸张翻动")
    rep.setdefault("line", "明信片到了，替我保存好。")
    card = {
        "id": _nid(), "ts": _ts(), "direction": "him_to_her", "sense": rep["sense"],
        "prose": rep["prose"], "image_prompt": "", "ambient": rep["ambient"],
        "line": rep["line"], "image": "", "audio": "",
    }
    data = _load(SE_FILE, {"cards": []})
    data.setdefault("cards", []).insert(0, card)
    data["cards"] = data["cards"][:40]
    _save(SE_FILE, data)
    return {"card": card}


@router.get("/api/sense/album")
async def sense_album():
    data = _load(SE_FILE, {"cards": []})
    return {"cards": data.get("cards", [])}


@router.delete("/api/sense/{cid}")
async def sense_del(cid: str):
    data = _load(SE_FILE, {"cards": []})
    data["cards"] = [c for c in data.get("cards", []) if c.get("id") != cid]
    _save(SE_FILE, data)
    return {"ok": True}


@router.post("/api/sense/{cid}/voice")
async def sense_voice(cid: str):
    """把明信片正文合成为语音（像他轻声读出来）。"""
    data = _load(SE_FILE, {"cards": []})
    card = next((c for c in data.get("cards", []) if c.get("id") == cid), None)
    if not card:
        return JSONResponse({"error": "明信片不存在"}, status_code=404)
    if card.get("audio"):
        return {"audio": card["audio"], "cached": True}
    from app import (_tts_clean, _tts_synthesize, _tts_emo)
    import httpx
    text = _tts_clean(card.get("prose", ""))
    if not text:
        return JSONResponse({"error": "明信片正文为空"}, status_code=400)
    try:
        from role_data import RolePath
        out = RolePath("static", "sense_voice")
        out.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0), trust_env=False) as client:
            wav = await _tts_synthesize(client, text, 0.95, *_tts_emo({"emotion": "tender"}))
        fname = f"{cid}.wav"
        (out / fname).write_bytes(wav)
        card["audio"] = f"/static/sense_voice/{fname}"
        _save(SE_FILE, data)
        return {"audio": card["audio"], "cached": False}
    except Exception as exc:
        return JSONResponse({"error": f"语音合成失败：{str(exc)[:120]}（可先看文字版）"}, status_code=502)


# ===========================================================================
# 4. 共犯系统：秘密同盟
# ===========================================================================
@router.post("/api/accomplice/plan")
async def accomplice_plan(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    target = str(body.get("target", "")).strip()[:60]
    detail = str(body.get("detail", "")).strip()[:200]
    if not target:
        return JSONResponse({"error": "说说你们的'作案目标'（整蛊朋友/筹备惊喜/策划一次恶作剧）"}, status_code=400)
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【共犯系统】她找你当'共犯'，一起策划一件不能声张的事。你认真而温柔地入伙——"
        "因为和她站同一边，是你的私心。\n"
        f"目标：{target}\n"
        f"细节：{detail or '（她还没细说，你来补全）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"title":"行动代号（10字内，像特工行动）",'
        '"stages":[{"step":"行动步骤名（8字内）","action":"40字内怎么做","risk":"低/中/高"}],'
        '"cover":"20字内对外口径（别人问起怎么答）",'
        '"line":"30字内他对她说的一句「入伙」的话"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "策划吧，只输出 JSON。"}], max_tokens=900)
    except Exception:
        rep = {}
    stages = rep.get("stages")
    if not isinstance(stages, list) or not stages:
        stages = [{"step": "踩点", "action": "先观察，再动手。", "risk": "低"}]
    rep.setdefault("title", "无痕行动")
    rep.setdefault("cover", "我们在讨论课题。")
    rep.setdefault("line", "这件事，我只跟你站在同一边。")
    plan = {
        "id": _nid(), "ts": _ts(), "target": target, "detail": detail,
        "title": rep["title"], "stages": stages[:5], "cover": rep["cover"],
        "line": rep["line"], "status": "planning", "verdict": "",
    }
    data = _load(AC_FILE, {"plans": [], "codebooks": [], "level": 1})
    data.setdefault("plans", []).insert(0, plan)
    data["plans"] = data["plans"][:30]
    _save(AC_FILE, data)
    _affinity("world", "共犯系统·入伙")
    return {"plan": plan}


@router.post("/api/accomplice/codebook")
async def accomplice_codebook(req: Request):
    """生成双向暗语密码本。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    words = body.get("words") or []
    if not isinstance(words, list):
        words = []
    words = [str(w).strip()[:10] for w in words if str(w).strip()][:6]
    memories = _agg_memories(3)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【共犯系统·暗语密码本】为你们的秘密同盟生成一本双向暗语密码本："
        "日常词汇对应只有你们懂的暗语。\n"
        f"她指定的词：{json.dumps(words, ensure_ascii=False)}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:300]}\n\n"
        '输出 JSON：{"pairs":[{"word":"日常词（如周三/想吃火锅/我没事）","code":"暗语（8字内，风雅或可爱）"}]}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "造一本密码本，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    pairs = rep.get("pairs")
    if not isinstance(pairs, list):
        pairs = []
    norm = []
    for p in pairs[:8]:
        if isinstance(p, dict) and p.get("word") and p.get("code"):
            norm.append({"word": str(p["word"])[:10], "code": str(p["code"])[:10]})
    if len(norm) < 3:
        norm.extend([
            {"word": "我没事", "code": "今晚月色很好"},
            {"word": "想见你", "code": "实验室的灯还亮着"},
            {"word": "撤退", "code": "咖啡凉了"},
        ])
    norm = norm[:8]
    cb = {"id": _nid(), "ts": _ts(), "pairs": norm}
    data = _load(AC_FILE, {"plans": [], "codebooks": [], "level": 1})
    data.setdefault("codebooks", []).insert(0, cb)
    data["codebooks"] = data["codebooks"][:10]
    _save(AC_FILE, data)
    return {"codebook": cb}


@router.post("/api/accomplice/chat")
async def accomplice_chat(req: Request):
    """在密码本语境下对话：用暗语密聊。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    message = str(body.get("message", "")).strip()[:300]
    if not message:
        return JSONResponse({"error": "说点什么（可带暗语）"}, status_code=400)
    data = _load(AC_FILE, {"plans": [], "codebooks": [], "level": 1})
    cb = data.get("codebooks", [])[0] if data.get("codebooks") else None
    pairs = cb.get("pairs", []) if cb else []
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【共犯系统·密聊】你们在用暗语密聊（涉及'那件事'时用暗语代称，她如果用了暗语，你也用暗语回应）。\n"
        f"当前密码本：{json.dumps(pairs, ensure_ascii=False)}\n"
        f"她发来：{message}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        "要求：1. 若她的话含暗语，先破译再回应（回应里点破她说的真实含义）；\n"
        "2. 若无暗语，正常温柔回应；3. 1-2句，保留一丝'只有我们懂'的默契。\n"
        '输出 JSON：{"decoded":"她这句话的真实含义（若含暗语，否则空串）",'
        '"reply":"40字内回应",'
        '"uses_code":true/false(是否用了暗语)}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "回应吧，只输出 JSON。"}], max_tokens=500)
    except Exception:
        rep = {}
    rep.setdefault("decoded", "")
    rep.setdefault("reply", "收到。按原计划。")
    rep.setdefault("uses_code", False)
    return {"reply": rep}


@router.post("/api/accomplice/{pid}/finish")
async def accomplice_finish(pid: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    result = str(body.get("result", "done")).strip()
    note = str(body.get("note", "")).strip()[:200]
    if result not in ("done", "failed", "abandoned"):
        result = "done"
    data = _load(AC_FILE, {"plans": [], "codebooks": [], "level": 1})
    plan = next((p for p in data.get("plans", []) if p.get("id") == pid), None)
    if not plan:
        return JSONResponse({"error": "行动不存在"}, status_code=404)
    if plan.get("status") in ("done", "failed", "abandoned"):
        return JSONResponse({"error": "这次行动已经归档"}, status_code=400)
    plan["status"] = result
    plan["note"] = note
    plan["finished_at"] = _ts()
    verdicts = {"done": "天衣无缝。这是你们共同的第一个勋章。",
                "failed": "计划败露，但你们默契地一起扛了。",
                "abandoned": "行动取消——有时'不做'也是共同决定。"}
    plan["verdict"] = verdicts.get(result, verdicts["done"])
    if result == "done":
        data["level"] = int(data.get("level", 1)) + 1
        _affinity("world", "共犯行动成功")
    _save(AC_FILE, data)
    return {"plan": plan, "level": data.get("level", 1)}


@router.get("/api/accomplice/archive")
async def accomplice_archive():
    data = _load(AC_FILE, {"plans": [], "codebooks": [], "level": 1})
    return {"plans": data.get("plans", []), "codebooks": data.get("codebooks", [])[:5],
            "level": data.get("level", 1),
            "done": sum(1 for p in data.get("plans", []) if p.get("status") == "done")}


# ===========================================================================
# 5. 情绪交易所
# ===========================================================================
EMOEX_EMOTIONS = ["开心", "平静", "低落", "焦虑", "愤怒", "孤独", "疲惫", "心动"]


@router.post("/api/emoex/record")
async def emoex_record(req: Request):
    """她的情绪记账。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    emotion = str(body.get("emotion", "")).strip()[:10]
    note = str(body.get("note", "")).strip()[:200]
    if emotion not in EMOEX_EMOTIONS:
        return JSONResponse({"error": "情绪需为：" + "、".join(EMOEX_EMOTIONS)}, status_code=400)
    data = _load(EX_FILE, {"ledger": [], "investments": [], "savings": [], "ious": [], "reports": []})
    rec = {"id": _nid(), "ts": _ts(), "date": _today(), "emotion": emotion, "note": note}
    data.setdefault("ledger", []).insert(0, rec)
    data["ledger"] = data["ledger"][:200]
    _save(EX_FILE, data)
    return {"record": rec}


@router.post("/api/emoex/invest")
async def emoex_invest(req: Request):
    """她低落时，他'投资'一段回应（语音/话语），记为资产。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    emotion = str(body.get("emotion", "")).strip()[:10]
    note = str(body.get("note", "")).strip()[:200]
    if emotion not in EMOEX_EMOTIONS:
        emotion = "低落"
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【情绪交易所·投资】她现在的情绪是" + emotion + "。你决定'投资'一段回应——"
        "这是你对她的资产配置：在低点买入，在她开心时兑现。\n"
        f"她的话：{note or '（她没多说）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"reply":"70字内回应（温柔、具体、一个锚点）",'
        '"value":1-10整数(这段回应在情绪市场的估值),'
        '"note":"20字内他记账时写的小批注"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "投资吧，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("reply", "我在。这一笔，算我买入你的情绪。")
    try:
        value = max(1, min(10, int(rep.get("value", 5))))
    except (TypeError, ValueError):
        value = 5
    rep.setdefault("note", "低点买入，长期持有。")
    inv = {"id": _nid(), "ts": _ts(), "date": _today(), "emotion": emotion, "reply": rep["reply"],
           "value": value, "note": rep["note"]}
    data = _load(EX_FILE, {"ledger": [], "investments": [], "savings": [], "ious": [], "reports": []})
    data.setdefault("investments", []).insert(0, inv)
    data["investments"] = data["investments"][:100]
    _save(EX_FILE, data)
    _affinity("chat", "情绪交易所·投资")
    return {"investment": inv}


@router.post("/api/emoex/save")
async def emoex_save(req: Request):
    """她开心时，他'储蓄'她的笑脸。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    emotion = str(body.get("emotion", "开心")).strip()[:10]
    note = str(body.get("note", "")).strip()[:200]
    data = _load(EX_FILE, {"ledger": [], "investments": [], "savings": [], "ious": [], "reports": []})
    sav = {"id": _nid(), "ts": _ts(), "date": _today(), "emotion": emotion,
           "note": note or "（她今天心情不错）", "value": random.randint(2, 5)}
    data.setdefault("savings", []).insert(0, sav)
    data["savings"] = data["savings"][:100]
    _save(EX_FILE, data)
    return {"saving": sav}


@router.post("/api/emoex/iou")
async def emoex_iou(req: Request):
    """许墨立下一张欠条（他欠她一件事），她可随时行使债权。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    debt = str(body.get("debt", "")).strip()[:60]
    if not debt:
        return JSONResponse({"error": "他欠你什么？（比如'欠你一次说走就走的旅行'）"}, status_code=400)
    memories = _agg_memories(3)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【情绪交易所·欠条】她要求你立下一张欠条：你欠她" + debt + "。\n"
        "你认真地写下这张欠条——这是你欠她的资产，白纸黑字。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:300]}\n\n"
        '输出 JSON：{"iou":"60字内欠条正文（许墨口吻，承认欠下并承诺兑现，带一点浪漫的仪式感）",'
        '"stamp":"15字内欠条上的「印章」（一句只有你们懂的话）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "立欠条，只输出 JSON。"}], max_tokens=500)
    except Exception:
        rep = {}
    rep.setdefault("iou", f"本人许墨，欠{sys_prompt.split('她')[0] if False else '她'}一件事：{debt}。承诺兑现，立此为据。")
    rep.setdefault("stamp", "以蝴蝶为证")
    iou = {"id": _nid(), "ts": _ts(), "debt": debt, "iou": rep["iou"], "stamp": rep["stamp"],
           "redeemed": False, "redeem_reply": ""}
    data = _load(EX_FILE, {"ledger": [], "investments": [], "savings": [], "ious": [], "reports": []})
    data.setdefault("ious", []).insert(0, iou)
    data["ious"] = data["ious"][:50]
    _save(EX_FILE, data)
    return {"iou": iou}


@router.post("/api/emoex/redeem")
async def emoex_redeem(req: Request):
    """行使债权：兑现一张欠条。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    iou_id = str(body.get("iou_id", "")).strip()
    data = _load(EX_FILE, {"ledger": [], "investments": [], "savings": [], "ious": [], "reports": []})
    iou = next((i for i in data.get("ious", []) if i.get("id") == iou_id), None)
    if not iou:
        return JSONResponse({"error": "欠条不存在"}, status_code=404)
    if iou.get("redeemed"):
        return JSONResponse({"error": "这张欠条已经兑现过了"}, status_code=400)
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【情绪交易所·兑现】她行使债权，要你兑现欠条：" + iou.get("debt", "") + "。\n"
        "你兑现的方式要符合许墨：不是敷衍地'好，以后一定'，而是立刻给出一个具体的、现在就能兑现的承诺或行动。\n"
        f"欠条原文：{iou.get('iou', '')}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        '输出 JSON：{"reply":"80字内兑现回应（具体、温柔、立即可执行）",'
        '"promise":"25字内他承诺的第一步"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "兑现吧，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("reply", "欠条兑现。第一步，现在就开始。")
    rep.setdefault("promise", "今天就开始的第一步")
    iou["redeemed"] = True
    iou["redeemed_at"] = _ts()
    iou["redeem_reply"] = rep["reply"]
    iou["promise"] = rep["promise"]
    _save(EX_FILE, data)
    _affinity("promise", "情绪交易所·兑现欠条")
    return {"iou": iou}


@router.get("/api/emoex/statement")
async def emoex_statement(req: Request):
    """月度情绪资产负债表 + 许墨的月度总结。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    month = str(body.get("month", "")).strip()
    if not re.match(r"^\d{4}-\d{2}$", month):
        month = datetime.now().strftime("%Y-%m")
    data = _load(EX_FILE, {"ledger": [], "investments": [], "savings": [], "ious": [], "reports": []})
    invs = [i for i in data.get("investments", []) if (i.get("date") or "")[:7] == month]
    savs = [s for s in data.get("savings", []) if (s.get("date") or "")[:7] == month]
    ledger = [l for l in data.get("ledger", []) if (l.get("date") or "")[:7] == month]
    ious_open = [i for i in data.get("ious", []) if not i.get("redeemed")]
    emo_dist = {}
    for l in ledger:
        emo_dist[l["emotion"]] = emo_dist.get(l["emotion"], 0) + 1
    summary = ""
    report = next((r for r in data.get("reports", []) if r.get("month") == month), None)
    if not report:
        memories = _agg_memories(4)
        sys_prompt = (
            f"{_persona_core()}\n\n"
            "【情绪交易所·月度资产负债表】写出你为她这个月的'情绪资产负债表'总结。\n"
            f"本{month}数据：投资 {len(invs)} 笔（共 {sum(i.get('value', 0) for i in invs)} 点），"
            f"储蓄 {len(savs)} 笔，情绪记账 {len(ledger)} 条，未兑现欠条 {len(ious_open)} 张。\n"
            f"情绪分布：{json.dumps(emo_dist, ensure_ascii=False)}\n"
            f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
            "写 100 字内的总结：先盘点（他为你投了什么、存了什么、还欠着什么），"
            "再给一句'下月持仓建议'（许墨式温柔）。"
        )
        try:
            summary = (await _call_llm(
                [{"role": "system", "content": sys_prompt},
                 {"role": "user", "content": "写月度总结。"}], max_tokens=600)).strip()
        except Exception:
            summary = ""
        report = {"id": _nid(), "month": month, "ts": _ts(), "summary": summary}
        data.setdefault("reports", []).insert(0, report)
        data["reports"] = data["reports"][:24]
        _save(EX_FILE, data)
    return {
        "month": month,
        "investments": invs[:20], "savings": savs[:20],
        "ledger": ledger[:20], "ious_open": ious_open[:10],
        "total_invested": sum(i.get("value", 0) for i in invs),
        "total_saved": len(savs),
        "emotion_distribution": emo_dist,
        "summary": report.get("summary", ""),
    }


@router.get("/api/emoex/state")
async def emoex_state():
    data = _load(EX_FILE, {"ledger": [], "investments": [], "savings": [], "ious": [], "reports": []})
    return {"investments": len(data.get("investments", [])),
            "savings": len(data.get("savings", [])),
            "ledger": len(data.get("ledger", [])),
            "ious_open": sum(1 for i in data.get("ious", []) if not i.get("redeemed")),
            "total_invested": sum(i.get("value", 0) for i in data.get("investments", [])),
            "ious": data.get("ious", [])[:10]}
