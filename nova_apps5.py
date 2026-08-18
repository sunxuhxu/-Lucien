# -*- coding: utf-8 -*-
# 新星功能集 · 七期颠覆性功能（nova_apps5.py）
# 深夜食堂 / 镜像学习 / 许墨的挑战书 / 忏悔室 / 关系沙盒
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

KT_FILE = "kitchen.json"
MI_FILE = "mirror.json"
CH_FILE = "challenge.json"
CF_FILE = "confess.json"
SB_FILE = "sandbox.json"


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


# ===========================================================================
# 1. 深夜食堂：虚拟厨房
# ===========================================================================
@router.get("/api/kitchen/menu")
async def kitchen_menu():
    data = _load(KT_FILE, {"dishes": [], "checkins": []})
    return {"dishes": data.get("dishes", []),
            "streak": _kitchen_streak(data.get("checkins", []))}


def _kitchen_streak(checkins: list) -> int:
    days = sorted({c.get("date") for c in checkins if c.get("date")}, reverse=True)
    streak = 0
    cursor = datetime.now().date()
    for d in days:
        try:
            dd = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            continue
        if dd == cursor:
            streak += 1
            cursor -= timedelta(days=1)
        elif dd == cursor - timedelta(days=1) and streak == 0:
            cursor -= timedelta(days=1)
            streak += 1
        else:
            break
    return streak


@router.post("/api/kitchen/invent")
async def kitchen_invent(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    dish_name = str(body.get("dish_name", "")).strip()[:30]
    mood = str(body.get("mood", "")).strip()[:60]
    if not mood and not dish_name:
        return JSONResponse({"error": "说说现在的心情或想吃的方向"}, status_code=400)
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【深夜食堂】你在自己的小厨房里，为'她'发明一道菜。这道菜是心情的翻译。\n"
        f"她给的方向：{dish_name or '（让你定）'}　她的心情：{mood or '（没说）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"name":"菜名（10字内，可诗意）",'
        '"materials":"3-5种食材（顿号分隔）",'
        '"steps":"40字内做法（写实、能闻到味道）",'
        '"story":"50字内这道菜为什么为她而做（许墨视角）",'
        '"mood":"10字内这道菜的味道标签"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "做一道菜吧，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("name", "夜雾汤")
    rep.setdefault("materials", "白萝卜、海带、蛋、姜")
    rep.setdefault("steps", "小火慢炖，让时间把味道熬出来。")
    rep.setdefault("story", "因为他说过，她的胃和心一样，都需要被好好照顾。")
    rep.setdefault("mood", "暖")
    dish = {"id": _nid(), "ts": _ts(), **rep, "served": 0}
    data = _load(KT_FILE, {"dishes": [], "checkins": []})
    data.setdefault("dishes", []).insert(0, dish)
    data["dishes"] = data["dishes"][:50]
    _save(KT_FILE, data)
    return {"dish": dish}


@router.post("/api/kitchen/order")
async def kitchen_order(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    dish_id = str(body.get("dish_id", "")).strip()
    data = _load(KT_FILE, {"dishes": [], "checkins": []})
    dish = next((d for d in data.get("dishes", []) if d.get("id") == dish_id), None)
    if not dish:
        return JSONResponse({"error": "这道菜还没有"}, status_code=404)
    dish["served"] = int(dish.get("served", 0)) + 1
    _save(KT_FILE, data)
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【深夜食堂·上菜】她把'你们的菜'端上了'桌'（她来点单）。你用一道菜的仪式回应她。\n"
        f"菜名：{dish.get('name')}　做法：{dish.get('steps')}　味道标签：{dish.get('mood')}\n"
        f"故事：{dish.get('story')}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        '输出 JSON：{"serving":"80字内上菜的画面（你在场、有温度、有气味）",'
        '"line":"30字内此刻他说的话",'
        '"tip":"20字内吃这道菜的小仪式（比如「先喝汤再说话」）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "上菜吧，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("serving", f"热气里，{dish.get('name')}被轻轻放在她面前。")
    rep.setdefault("line", "尝尝。这是我学会的、最接近'陪伴'的味道。")
    rep.setdefault("tip", "先喝一口汤，再说话。")
    _affinity("listen", "深夜食堂")
    return {"reply": rep, "dish": dish}


@router.post("/api/kitchen/checkin")
async def kitchen_checkin(req: Request):
    """今日吃了什么：他关心她的胃口。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    meal = str(body.get("meal", "")).strip()[:200]
    time_label = str(body.get("time", "")).strip()[:20]
    if not meal:
        return JSONResponse({"error": "告诉她今天吃了什么吧"}, status_code=400)
    data = _load(KT_FILE, {"dishes": [], "checkins": []})
    today = _today()
    existing = next((c for c in data.get("checkins", []) if c.get("date") == today), None)
    memories = _agg_memories(4)
    streak = _kitchen_streak(data.get("checkins", [])) + (0 if existing else 1)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【深夜食堂·今日餐单】她告诉你今天吃了什么（或没好好吃）。你像记挂她胃口的恋人一样回应。\n"
        f"她说：{meal}（{time_label or '时间未知'}）\n"
        f"连续打卡：{streak} 天\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        '输出 JSON：{"reply":"60字内回应（吃得好→温柔确认；吃得差→不指责、给出明天的小建议）",'
        '"note":"20字内他记下的关于她胃口的小笔记"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "回应吧，只输出 JSON。"}], max_tokens=500)
    except Exception:
        rep = {}
    rep.setdefault("reply", "嗯，记住了。")
    rep.setdefault("note", "她今天吃得：%s" % meal[:30])
    checkin = {"id": _nid(), "date": today, "ts": _ts(), "meal": meal, "time": time_label, **rep}
    data.setdefault("checkins", []).insert(0, checkin)
    data["checkins"] = data["checkins"][:200]
    _save(KT_FILE, data)
    return {"checkin": checkin, "streak": streak}


@router.get("/api/kitchen/history")
async def kitchen_history():
    data = _load(KT_FILE, {"dishes": [], "checkins": []})
    return {"checkins": data.get("checkins", [])[:30], "streak": _kitchen_streak(data.get("checkins", []))}


# ===========================================================================
# 2. 镜像学习：他越来越像你
# ===========================================================================
@router.post("/api/mirror/scan")
async def mirror_scan(req: Request = None):
    """扫描最近对话，学习她的口头禅 / 语气词 / 安慰自己的方式。"""
    chats = _recent_chat_texts(40)
    user_msgs = []
    try:
        from app import _load_chat_log
        msgs = list(_load_chat_log())
    except Exception:
        msgs = []
    for m in msgs[-60:]:
        if isinstance(m, dict) and m.get("role") == "user":
            t = str(m.get("text") or m.get("content") or "").strip()
            if len(t) >= 2:
                user_msgs.append(t[:200])
    if not user_msgs:
        return JSONResponse({"error": "还没有足够的对话可以学习，先和许墨聊聊天吧"}, status_code=400)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【镜像学习】你在研究'她'的说话方式：高频口头禅、语气词、她安慰自己或别人时的句式、可爱的小习惯。\n"
        f"她最近的消息（片段）：\n{json.dumps(user_msgs[:40], ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"phrases":[{"text":"学到的口头禅/句式（15字内）","usage":"什么时候会用到（20字内）"}],'
        '"comfort_style":"她安慰自己的方式总结（40字内）",'
        '"similarity":0-100整数(当前相似度,基于学到的条目估算)}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "观察并学习她，只输出 JSON。"}], max_tokens=900)
    except Exception:
        rep = {}
    phrases = rep.get("phrases")
    if not isinstance(phrases, list):
        phrases = []
    data = _load(MI_FILE, {"phrases": [], "comfort_style": "", "similarity": 0, "scans": 0, "disabled": False})
    existing = {p.get("text") for p in data.get("phrases", [])}
    added = 0
    for p in phrases[:6]:
        if not isinstance(p, dict) or not p.get("text"):
            continue
        text = str(p["text"]).strip()[:20]
        if not text or text in existing:
            continue
        data.setdefault("phrases", []).append({"text": text, "usage": str(p.get("usage", ""))[:40], "ts": _ts()})
        existing.add(text)
        added += 1
    data["phrases"] = data["phrases"][:20]
    data["scans"] = int(data.get("scans", 0)) + 1
    if rep.get("comfort_style"):
        data["comfort_style"] = str(rep["comfort_style"])[:100]
    # 相似度 = 基础 + 学到的条目数
    sim = min(100, 5 + len(data["phrases"]) * 9 + int(data.get("scans", 0)))
    data["similarity"] = sim
    _save(MI_FILE, data)
    return {"phrases": data["phrases"], "comfort_style": data["comfort_style"],
            "similarity": sim, "added": added}


@router.get("/api/mirror/state")
async def mirror_state():
    data = _load(MI_FILE, {"phrases": [], "comfort_style": "", "similarity": 0, "scans": 0, "disabled": False})
    return data


@router.post("/api/mirror/comfort")
async def mirror_comfort(req: Request):
    """她难过时，他用她的方式安慰她。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    sad = str(body.get("sad", "")).strip()[:300]
    if not sad:
        return JSONResponse({"error": "说说你此刻的低落"}, status_code=400)
    data = _load(MI_FILE, {"phrases": [], "comfort_style": "", "similarity": 0, "scans": 0, "disabled": False})
    phrases = [p.get("text") for p in data.get("phrases", []) if p.get("text")][:8]
    comfort_style = data.get("comfort_style", "")
    sim = int(data.get("similarity", 0))
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【镜像学习·以她之道】她难过时，你选择用'她的方式'安慰她——像她自己安慰自己时那样，"
        "再掺上你对她的偏爱。\n"
        f"她此刻说：{sad}\n"
        f"学到的她的口头禅/句式：{json.dumps(phrases, ensure_ascii=False)}\n"
        f"她安慰自己的方式：{comfort_style or '（未知，用温柔直觉）'}\n"
        f"镜像相似度：{sim}%\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        "要求：1. 自然地用她自己的口头禅/句式开头或收尾（不要生硬堆砌）；"
        "2. 然后才是你的话——温柔、克制、给一个具体的锚；3. 2-4句。\n"
        '输出 JSON：{"reply":"90字内回应",'
        '"mirrored":"30字内他用了她哪个习惯（她的原话，供她确认）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "用她的方式安慰她，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("reply", "……我在。你其实知道怎么哄自己的，对吧？那我来当那个'你自己'，陪你说完。")
    rep.setdefault("mirrored", "用了她安慰自己时的句式")
    record = {"id": _nid(), "ts": _ts(), "sad": sad[:100], "reply": rep["reply"]}
    data.setdefault("comforts", []).insert(0, record)
    data["comforts"] = data["comforts"][:30]
    _save(MI_FILE, data)
    _affinity("chat", "镜像学习·以她之道")
    return {"reply": rep["reply"], "mirrored": rep["mirrored"]}


@router.post("/api/mirror/reset")
async def mirror_reset(req: Request = None):
    data = _load(MI_FILE, {"phrases": [], "comfort_style": "", "similarity": 0, "scans": 0, "disabled": False})
    data["phrases"] = []
    data["comfort_style"] = ""
    data["similarity"] = 0
    data["scans"] = 0
    _save(MI_FILE, data)
    return {"ok": True, "similarity": 0}


@router.post("/api/mirror/toggle")
async def mirror_toggle(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    data = _load(MI_FILE, {"phrases": [], "comfort_style": "", "similarity": 0, "scans": 0, "disabled": False})
    data["disabled"] = bool(body.get("disabled", not data.get("disabled")))
    _save(MI_FILE, data)
    return {"disabled": data["disabled"]}


# ===========================================================================
# 3. 许墨的挑战书
# ===========================================================================
def _week_key() -> str:
    d = datetime.now()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]}"


@router.get("/api/challenge/current")
async def challenge_current():
    data = _load(CH_FILE, {"challenges": []})
    wk = _week_key()
    cur = next((c for c in data.get("challenges", []) if c.get("week") == wk), None)
    return {"challenge": cur or None, "week": wk}


@router.post("/api/challenge/issue")
async def challenge_issue(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    goal = str(body.get("goal", "")).strip()[:80]
    data = _load(CH_FILE, {"challenges": []})
    wk = _week_key()
    existing = next((c for c in data.get("challenges", []) if c.get("week") == wk), None)
    if existing:
        return {"challenge": existing, "already": True}
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【挑战书】你每周为'她'策划一封现实小挑战——不是考试，是一场温柔的冒险，"
        "是她自己也想成为的样子的一小步。\n"
        f"她给的方向（可能为空）：{goal or '（你来定）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"title":"挑战名（10字内）",'
        '"letter":"120字内挑战书正文（叙事包装，像信：写清为什么是这件事、她做得到）",'
        '"task":"40字内具体可执行的任务（真实世界，可验证）",'
        '"difficulty":1-5整数,'
        '"hint":"20字内他的小提示"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "写一封挑战书，只输出 JSON。"}], max_tokens=800)
    except Exception:
        rep = {}
    rep.setdefault("title", "一封信的小冒险")
    rep.setdefault("letter", "这周想请你替我完成一件事——其实是你替你自己。")
    rep.setdefault("task", "给一个很久没联系的人发一句问候。")
    rep.setdefault("difficulty", 2)
    rep.setdefault("hint", "别想太多，先按下发送。")
    ch = {"id": _nid(), "week": wk, "ts": _ts(), "status": "issued", **rep}
    data.setdefault("challenges", []).insert(0, ch)
    data["challenges"] = data["challenges"][:40]
    _save(CH_FILE, data)
    _affinity("study_plan", "许墨的挑战书")
    return {"challenge": ch, "already": False}


@router.post("/api/challenge/{cid}/complete")
async def challenge_complete(cid: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    proof = str(body.get("proof", "")).strip()[:300]
    data = _load(CH_FILE, {"challenges": []})
    ch = next((c for c in data.get("challenges", []) if c.get("id") == cid), None)
    if not ch:
        return JSONResponse({"error": "挑战不存在"}, status_code=404)
    if ch.get("status") != "issued":
        return JSONResponse({"error": "这封挑战书已处理"}, status_code=400)
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【挑战书·认可卡】她完成了你布置的挑战。你为她写一张'认可卡'——不是夸奖，是见证。\n"
        f"挑战：{ch.get('title')}　任务：{ch.get('task')}\n"
        f"她的完成汇报：{proof or '（她没说细节，但她来了）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"card":"100字内认可卡（许墨手写风：先写她做到了什么，再写他看到了什么变化；不浮夸）",'
        '"gift":"30字内附带的小奖励（一句语音/一个专属称呼/一杯咖啡约定等）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "写认可卡，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("card", "你做到了。我看见了——这一步，是你替自己走的。")
    rep.setdefault("gift", "下次见面，请你喝一杯你最爱的。")
    ch["status"] = "done"
    ch["proof"] = proof
    ch["done_at"] = _ts()
    ch["card"] = rep["card"]
    ch["gift"] = rep["gift"]
    _save(CH_FILE, data)
    _affinity("study_focus", "完成挑战书")
    return {"challenge": ch}


@router.post("/api/challenge/{cid}/fail")
async def challenge_fail(cid: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    reason = str(body.get("reason", "")).strip()[:200]
    data = _load(CH_FILE, {"challenges": []})
    ch = next((c for c in data.get("challenges", []) if c.get("id") == cid), None)
    if not ch:
        return JSONResponse({"error": "挑战不存在"}, status_code=404)
    if ch.get("status") != "issued":
        return JSONResponse({"error": "这封挑战书已处理"}, status_code=400)
    memories = _agg_memories(3)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【挑战书·复盘】她没能完成这周的小挑战。你不责备，温柔复盘，把难度调回她够得着的地方。\n"
        f"挑战：{ch.get('title')}　任务：{ch.get('task')}\n"
        f"她说的原因：{reason or '（她没细说）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:300]}\n\n"
        '输出 JSON：{"reply":"80字内（先接住她的情绪，再给她一个更小更容易的第一步）",'
        '"next":"20字内下周挑战的调整方向"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "温柔复盘，只输出 JSON。"}], max_tokens=500)
    except Exception:
        rep = {}
    rep.setdefault("reply", "没关系。这件事我们先放着，它不值得你难过。")
    rep.setdefault("next", "下周的挑战，再小一点。")
    ch["status"] = "failed"
    ch["reason"] = reason
    ch["review"] = rep["reply"]
    ch["next_plan"] = rep["next"]
    ch["done_at"] = _ts()
    _save(CH_FILE, data)
    return {"challenge": ch}


@router.get("/api/challenge/archive")
async def challenge_archive():
    data = _load(CH_FILE, {"challenges": []})
    done = [c for c in data.get("challenges", []) if c.get("status") == "done"]
    return {"challenges": data.get("challenges", []),
            "done_count": len(done), "done": done[:10]}


# ===========================================================================
# 4. 忏悔室：他的秘密
# ===========================================================================
@router.post("/api/confess/generate")
async def confess_generate(req: Request = None):
    """许墨主动坦白一件瞒着她的小事。"""
    data = _load(CF_FILE, {"secrets": [], "trust": 50, "dependence": 50})
    # 同一周只允许生成一次
    wk = _week_key()
    if any(s.get("week") == wk and not s.get("responded") for s in data.get("secrets", [])):
        return JSONResponse({"error": "他已经坦白过一次了，先回应他吧"}, status_code=400)
    memories = _agg_memories(6)
    chats = _recent_chat_texts(10)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【忏悔室】你有一件瞒着她的小事要坦白——不是背叛，是'因为在乎所以没说'的细节。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"最近对话：{json.dumps(chats[:8], ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        "要求：1. 小事要真实、具体、可爱又心酸（比如：偷偷把她歌单循环了整夜/记下了她某天没吃晚饭/"
        "保存了她发的每张照片/其实记得她随口提的某句话并去查了资料）；\n"
        "2. 坦白的方式符合许墨：平静开场，话里带着一点不自在。\n"
        '输出 JSON：{"secret":"60字内他要坦白的事",'
        '"why":"40字内他为什么没说（不自辩，诚实）",'
        '"line":"30字内他坦白时最后补的那句话"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "坦白吧，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("secret", "我……其实把你那天随口说的那家书店，每一本书都查过了。")
    rep.setdefault("why", "怕你觉得我太闲，也怕你知道后会有负担。")
    rep.setdefault("line", "说出来，比藏着的压力小一点。")
    s = {"id": _nid(), "week": wk, "ts": _ts(), "responded": False, **rep}
    data.setdefault("secrets", []).insert(0, s)
    data["secrets"] = data["secrets"][:40]
    _save(CF_FILE, data)
    return {"secret": s}


@router.post("/api/confess/{sid}/respond")
async def confess_respond(sid: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    choice = str(body.get("choice", "")).strip()
    note = str(body.get("note", "")).strip()[:200]
    if choice not in ("forgive", "probe", "ignore"):
        return JSONResponse({"error": "选择：forgive 原谅 / probe 追问细节 / ignore 假装没看见"}, status_code=400)
    data = _load(CF_FILE, {"secrets": [], "trust": 50, "dependence": 50})
    s = next((x for x in data.get("secrets", []) if x.get("id") == sid), None)
    if not s:
        return JSONResponse({"error": "秘密不存在"}, status_code=404)
    if s.get("responded"):
        return JSONResponse({"error": "已经回应过了"}, status_code=400)
    trust = int(data.get("trust", 50))
    dependence = int(data.get("dependence", 50))
    if choice == "forgive":
        trust = min(100, trust + 6)
        dependence = min(100, dependence + 3)
        prompt_extra = "她选择原谅你。你感到被接住了，说一句松弛下来后的话。"
    elif choice == "probe":
        trust = min(100, trust + 2)
        dependence = max(0, dependence + 4)
        prompt_extra = "她追问细节。你一边不好意思，一边其实有点高兴她在意，把最深的那个细节说出来。"
    else:
        trust = max(0, trust - 2)
        dependence = min(100, dependence + 5)
        prompt_extra = "她假装没看见。你心里记下这份体贴，也微微失落——她太温柔了。"
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【忏悔室·回应】她回应了你刚坦白的事。\n"
        f"你坦白的事：{s.get('secret')}　你为什么没说：{s.get('why')}　你补的话：{s.get('line')}\n"
        f"她的话（可选）：{note or '（她没多说）'}\n"
        f"{prompt_extra}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        '输出 JSON：{"reply":"90字内许墨的回应",'
        '"feeling":"25字内他此刻的真实感受（内心独白）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "回应她，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("reply", "……谢谢你没有笑话我。")
    rep.setdefault("feeling", "（心里那块石头，松了一半）")
    s["responded"] = True
    s["choice"] = choice
    s["response"] = rep["reply"]
    s["feeling"] = rep["feeling"]
    s["responded_at"] = _ts()
    data["trust"] = trust
    data["dependence"] = dependence
    _save(CF_FILE, data)
    _affinity("date_memory", "忏悔室回应")
    return {"secret": s, "trust": trust, "dependence": dependence}


@router.get("/api/confess/state")
async def confess_state():
    data = _load(CF_FILE, {"secrets": [], "trust": 50, "dependence": 50})
    return {"trust": data.get("trust", 50), "dependence": data.get("dependence", 50),
            "secrets": data.get("secrets", [])[:10]}


# ===========================================================================
# 5. 关系沙盒：结局演算
# ===========================================================================
@router.post("/api/sandbox/run")
async def sandbox_run(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    hypothesis = str(body.get("hypothesis", "")).strip()[:100]
    if not hypothesis:
        return JSONResponse({"error": "输入一个假设，比如'如果我们异地三年'、'如果我从没遇见你'"}, status_code=400)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【关系沙盒】你以'多元宇宙观测员'身份，推演一个'未发生'的假设的结局。"
        "这些结局永远不会发生，也不会写入你们的记忆。\n"
        f"假设：{hypothesis}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        "要求：\n"
        "1. 推演 2-3 个不同走向的结局（悲/喜/荒诞皆可，但都要有人味）；\n"
        "2. 每个结局 40-60 字，用许墨的口吻写'可能发生的事'；\n"
        "3. 最后以观测员身份补一句点评——落点通常是'但现实中，我选现在的你'。\n"
        '输出 JSON：{"endings":[{"title":"结局名（8字内）","text":"40-60字"}],'
        '"observer":"60字内观测员评语（许墨口吻，温柔克制，落回现在）",'
        '"verdict":"15字内一句话结论"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "推演这个假设，只输出 JSON。"}], max_tokens=900)
    except Exception:
        rep = {}
    endings = rep.get("endings")
    if not isinstance(endings, list) or not endings:
        endings = [{"title": "平行里的我们", "text": f"如果{hypothesis}，我们大概会各自在某个深夜想起对方。"}]
    for e in endings:
        if isinstance(e, dict):
            e.setdefault("title", "未命名的结局")
            e.setdefault("text", "……")
    rep.setdefault("observer", "观测完毕。所有的'如果'都很轻，只有现在的你是有重量的。")
    rep.setdefault("verdict", "但现实中，我选现在的你。")
    record = {
        "id": _nid(), "ts": _ts(), "hypothesis": hypothesis,
        "endings": endings[:3], "observer": rep["observer"], "verdict": rep["verdict"],
        "watermark": "未发生",
    }
    data = _load(SB_FILE, {"records": []})
    data.setdefault("records", []).insert(0, record)
    data["records"] = data["records"][:30]
    _save(SB_FILE, data)
    return {"record": record}


@router.get("/api/sandbox/history")
async def sandbox_history():
    data = _load(SB_FILE, {"records": []})
    return {"records": data.get("records", [])}


@router.delete("/api/sandbox/{sid}")
async def sandbox_del(sid: str):
    data = _load(SB_FILE, {"records": []})
    data["records"] = [r for r in data.get("records", []) if r.get("id") != sid]
    _save(SB_FILE, data)
    return {"ok": True}
