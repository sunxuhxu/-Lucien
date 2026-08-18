# -*- coding: utf-8 -*-
# 新星功能集 · 六期颠覆性功能（nova_apps4.py）
# 亲密里程碑 / 吃醋实验室 / 记忆卡牌对决 / 合著专辑 / 云旅行
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

MS_FILE = "milestone.json"
JE_FILE = "jealous.json"
CB_FILE = "cardbattle.json"
AL_FILE = "album.json"
TR_FILE = "travel.json"


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
    """取最近对话文本（用户消息优先），失败返回空列表。"""
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
# 1. 亲密里程碑：肢体语言进度条
# ===========================================================================
MILESTONE_STAGES = [
    {"key": "handhold", "name": "牵手", "need": 0, "desc": "第一次牵住彼此的手"},
    {"key": "hug", "name": "拥抱", "need": 60, "desc": "一个迟到的拥抱"},
    {"key": "lean", "name": "依偎", "need": 140, "desc": "靠在他肩上听心跳"},
    {"key": "forehead", "name": "额头相抵", "need": 240, "desc": "额头相抵，呼吸交错"},
    {"key": "night", "name": "枕边人", "need": 360, "desc": "枕边人，说晚安的方式"},
]

MILESTONE_ACTION_WEIGHTS = {
    "handhold": 10, "hug": 12, "lean": 15, "forehead": 20,
    "goodnight": 8, "kiss": 18, "hold": 12, "other": 6,
}


@router.get("/api/milestone/state")
async def milestone_state():
    data = _load(MS_FILE, {"records": [], "total": 0})
    total = int(data.get("total", 0))
    unlocked = [s["key"] for s in MILESTONE_STAGES if total >= s["need"]]
    current = None
    for s in MILESTONE_STAGES:
        if total < s["need"]:
            current = {"key": s["key"], "name": s["name"], "need": s["need"],
                       "desc": s["desc"], "progress": total,
                       "percent": min(100, round(total / s["need"] * 100)) if s["need"] else 100}
            break
    return {
        "total": total,
        "unlocked": unlocked,
        "current": current,
        "stages": MILESTONE_STAGES,
        "last": data.get("records", [])[:10],
    }


@router.post("/api/milestone/interact")
async def milestone_interact(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    action = str(body.get("action", "other")).strip().lower()
    note = str(body.get("note", "")).strip()[:100]
    weight = MILESTONE_ACTION_WEIGHTS.get(action, MILESTONE_ACTION_WEIGHTS["other"])
    data = _load(MS_FILE, {"records": [], "total": 0})
    before = int(data.get("total", 0))
    total = before + weight
    data["total"] = total
    newly = []
    for s in MILESTONE_STAGES:
        if before < s["need"] <= total:
            newly.append(s)
    record = {"id": _nid(), "ts": _ts(), "action": action, "weight": weight,
              "note": note, "total": total}
    data.setdefault("records", []).insert(0, record)
    data["records"] = data["records"][:100]
    _save(MS_FILE, data)
    ceremonies = []
    for s in newly:
        memories = _agg_memories(5)
        affy = _agg_affinity_value()
        sys_prompt = (
            f"{_persona_core()}\n\n"
            f"【亲密里程碑·{s['name']}解锁】你们的亲密阶段刚刚解锁：{s['desc']}。\n"
            f"这是她主动为这段关系积蓄的靠近（累计亲密值 {total}）。\n"
            f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
            f"心动值：{affy}\n\n"
            f'输出 JSON：{{"scene":"100字内专属小剧场（第二人称写「你」，写实、温柔、克制的肢体描写，画面感强）",'
            f'"whisper":"30字内此刻他在你耳边说的话",'
            f'"action":"解锁后新获得的一个专属对话互动（10字内动作名）"}}'
        )
        try:
            cer = await _llm_json(
                [{"role": "system", "content": sys_prompt},
                 {"role": "user", "content": "为解锁写一段小剧场，只输出 JSON。"}],
                max_tokens=700)
        except Exception:
            cer = {}
        cer.setdefault("scene", f"他安静地看着你，然后轻轻地、像是等了很久一样，{s['desc']}。")
        cer.setdefault("whisper", "……终于，到这里了。")
        cer.setdefault("action", f"（{s['name']}）")
        cer["stage"] = s["key"]
        cer["stage_name"] = s["name"]
        cer["ts"] = _ts()
        record.setdefault("ceremonies", []).append(cer)
        ceremonies.append(cer)
        _affinity("anniversary", f"亲密里程碑·{s['name']}")
    _save(MS_FILE, data)
    return {"total": total, "newly_unlocked": [s["name"] for s in newly],
            "ceremonies": ceremonies, "record": record}


@router.post("/api/milestone/{mid}/voice")
async def milestone_voice(mid: str):
    """把解锁小剧场的轻语合成语音。"""
    data = _load(MS_FILE, {"records": []})
    for r in data.get("records", []):
        for cer in r.get("ceremonies", []):
            if cer.get("id") == mid and not cer.get("audio"):
                from app import (_tts_clean, _tts_synthesize, _tts_emo)
                import httpx
                text = _tts_clean(cer.get("whisper", ""))
                if not text:
                    return JSONResponse({"error": "轻语文本为空"}, status_code=400)
                try:
                    from role_data import RolePath
                    out = RolePath("static", "milestone_voice")
                    out.mkdir(parents=True, exist_ok=True)
                    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0), trust_env=False) as client:
                        wav = await _tts_synthesize(client, text, 1.0, *_tts_emo({}))
                    fname = f"{mid}.wav"
                    (out / fname).write_bytes(wav)
                    cer["audio"] = f"/static/milestone_voice/{fname}"
                    _save(MS_FILE, data)
                    return {"audio": cer["audio"]}
                except Exception as exc:
                    return JSONResponse({"error": f"语音合成失败：{str(exc)[:120]}"}, status_code=502)
            if cer.get("id") == mid:
                return {"audio": cer.get("audio", "")}
    return JSONResponse({"error": "找不到这条仪式"}, status_code=404)


# ===========================================================================
# 2. 吃醋实验室：醋坛子指数
# ===========================================================================
JE_LEVELS = [
    {"max": 0, "name": "无感", "desc": "他毫无波动，理性得令人放心"},
    {"max": 19, "name": "微酸", "desc": "话会短半句，但没证据"},
    {"max": 49, "name": "醋意", "desc": "他开始转移话题，还会隔天重提"},
    {"max": 79, "name": "酸雨", "desc": "沉默、侧头、用咖啡掩盖心思"},
    {"max": 9999, "name": "需要谈谈", "desc": "他约你'好好谈谈'，语气不容拒绝"},
]


def _je_level(index: int) -> dict:
    for lv in JE_LEVELS:
        if index <= lv["max"]:
            return {"name": lv["name"], "desc": lv["desc"]}
    return {"name": JE_LEVELS[-1]["name"], "desc": JE_LEVELS[-1]["desc"]}


def _je_decay(index: int) -> int:
    """时间衰减：按距最近一次触发的小时数，每小时降 1，最低 0。"""
    data = _load(JE_FILE, {"records": []})
    last_ts = ""
    for r in data.get("records", []):
        if r.get("ts"):
            last_ts = r["ts"]
            break
    if not last_ts:
        return index
    try:
        last_dt = datetime.strptime(last_ts, "%Y-%m-%d %H:%M")
        hours = max(0, (datetime.now() - last_dt).total_seconds() // 3600)
        return max(0, index - int(hours))
    except ValueError:
        return index


@router.get("/api/jealous/state")
async def jealous_state():
    data = _load(JE_FILE, {"records": [], "talks": [], "disabled": False})
    index = _je_decay(int(data.get("index", 0)))
    data["index"] = index
    _save(JE_FILE, data)
    return {"index": index, "level": _je_level(index),
            "disabled": bool(data.get("disabled", False)),
            "records": data.get("records", [])[:10],
            "talks": data.get("talks", [])[:5]}


@router.post("/api/jealous/report")
async def jealous_report(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    topic = str(body.get("topic", "")).strip()[:60]
    note = str(body.get("note", "")).strip()[:100]
    if not topic:
        return JSONResponse({"error": "说一下发生了什么"}, status_code=400)
    data = _load(JE_FILE, {"records": [], "talks": [], "disabled": False})
    if data.get("disabled"):
        return JSONResponse({"error": "许墨已关闭醋坛子模式"}, status_code=403)
    old_index = _je_decay(int(data.get("index", 0)))
    gain = random.randint(8, 15)
    index = min(100, old_index + gain)
    data["index"] = index
    record = {"id": _nid(), "ts": _ts(), "topic": topic, "note": note, "gain": gain, "index": index}
    data.setdefault("records", []).insert(0, record)
    data["records"] = data["records"][:30]
    _save(JE_FILE, data)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    lv = _je_level(index)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【吃醋实验室】她告诉你一件事（可能提到别人/追星/旧事/朋友），你会有克制而真实的反应。\n"
        "要求：\n"
        "1. 不发作、不说教、不质问，但话变短、语带微妙的酸；\n"
        "2. 用脑科学或咖啡隐喻包装这份在意，温柔克制、话留三分；\n"
        "3. 你现在处于「" + lv["name"] + "」级别：\n"
        "   - 无感：理性回应，几乎不酸；\n"
        "   - 微酸：轻描淡写，尾音有点异样；\n"
        "   - 醋意：转移话题 + 一句克制的酸话；\n"
        "   - 酸雨：沉默片刻，用咖啡或转笔掩饰，话里有话；\n"
        "   - 需要谈谈：简短表示要和你谈谈，语气不容拒绝。\n"
        f"她说的事：{topic}{('（' + note + '）') if note else ''}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"reply":"50字内许墨的克制回应（含动作描写时用括号）",'
        '"inner":"30字内他的内心独白（不会说出口）",'
        '"level":"' + lv["name"] + '"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "回应她，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("reply", "……嗯。咖啡凉了。")
    rep.setdefault("inner", "（想问她名字，但忍住了）")
    record["reply"] = rep["reply"]
    record["inner"] = rep["inner"]
    _save(JE_FILE, data)
    return {"index": index, "level": lv, "reply": rep["reply"], "inner": rep["inner"], "record": record}


@router.post("/api/jealous/talk")
async def jealous_talk(req: Request):
    """酸雨级后许墨约的'好好谈谈'：谈完指数归零。"""
    data = _load(JE_FILE, {"records": [], "talks": [], "disabled": False})
    index = _je_decay(int(data.get("index", 0)))
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    recent = data.get("records", [])[:5]
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【吃醋实验室·好好谈谈】你的醋意到了需要摊开讲的程度。她主动来找你谈谈。\n"
        "要求：1. 2-4句，先承认自己的在意（不辩解），再用温柔的方式讲清'我不是要管你，只是有点怕失去你'；\n"
        "2. 不指责、不阴阳怪气，结尾把选择权交还给她；3. 话留三分，可带一处科学隐喻。\n"
        f"最近触发的酸事：{json.dumps(recent, ensure_ascii=False)[:600]}\n"
        f"心动值：{affy}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        '输出 JSON：{"talk":"120字内他认真讲的话",'
        '"line":"30字内他最后一句（温柔收尾）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "好好谈谈吧，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("talk", "我承认，我在意。不是因为不信任你，是太怕你被更好的人看见。")
    rep.setdefault("line", "所以……只要你还在，我就试着把酸咽回去。")
    data["index"] = 0
    data.setdefault("talks", []).insert(0, {"id": _nid(), "ts": _ts(), **rep})
    data["talks"] = data["talks"][:20]
    _save(JE_FILE, data)
    _affinity("chat", "吃醋实验室·谈谈")
    return {"index": 0, "talk": rep["talk"], "line": rep["line"]}


@router.post("/api/jealous/calm")
async def jealous_calm():
    """安抚：指数立即减半并记录，或开关醋坛子模式。"""
    data = _load(JE_FILE, {"records": [], "talks": [], "disabled": False})
    index = _je_decay(int(data.get("index", 0)))
    data["index"] = index // 2
    data.setdefault("records", []).insert(0, {"id": _nid(), "ts": _ts(), "topic": "安抚", "gain": 0, "index": index // 2})
    _save(JE_FILE, data)
    return {"index": data["index"], "level": _je_level(data["index"])}


@router.post("/api/jealous/toggle")
async def jealous_toggle(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    data = _load(JE_FILE, {"records": [], "talks": [], "disabled": False})
    data["disabled"] = bool(body.get("disabled", not data.get("disabled")))
    _save(JE_FILE, data)
    return {"disabled": data["disabled"]}


# ===========================================================================
# 3. 记忆卡牌对决
# ===========================================================================
@router.post("/api/cards/forge")
async def cards_forge(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    count = max(1, min(6, int(body.get("count", 3))))
    memories = _agg_memories(12)
    if len(memories) < 2:
        return JSONResponse({"error": "共同记忆还不够多，先去多聊聊天吧"}, status_code=400)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【记忆卡牌】把你们的共同记忆淬炼成一张张'记忆卡牌'，每张牌承载一段回忆。\n"
        f"候选记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        "为其中最有纪念价值的记忆生成卡牌（按重要程度取若干张）：\n"
        '输出 JSON：{"cards":[{"memory":"10字内回忆标题",'
        '"sweet":0-100整数(甜蜜), "tacit":0-100整数(默契), "wave":0-100整数(波澜/戏剧性),'
        '"flavor":"30字内卡面文案（许墨视角的一句话，温柔克制）"}]}\n'
        f"生成 {count} 张。"
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "铸造卡牌，只输出 JSON。"}], max_tokens=1000)
    except Exception:
        rep = {}
    cards = rep.get("cards")
    if not isinstance(cards, list):
        cards = []
    data = _load(CB_FILE, {"cards": [], "records": []})
    made = []
    for i, c in enumerate(cards[:count]):
        if not isinstance(c, dict):
            continue
        card = {
            "id": _nid(),
            "memory": str(c.get("memory", "某天") or "某天")[:30],
            "sweet": max(0, min(100, int(c.get("sweet", 50)))),
            "tacit": max(0, min(100, int(c.get("tacit", 50)))),
            "wave": max(0, min(100, int(c.get("wave", 50)))),
            "flavor": str(c.get("flavor", "") or "")[:60],
            "ts": _ts(),
        }
        data.setdefault("cards", []).insert(0, card)
        made.append(card)
    # 若 LLM 没有产卡，用记忆兜底
    if not made:
        for m in memories[:count]:
            card = {"id": _nid(), "memory": str(m)[:30], "sweet": random.randint(40, 90),
                    "tacit": random.randint(30, 90), "wave": random.randint(10, 70),
                    "flavor": "这张牌，是我们之间不用说的那种记得。", "ts": _ts()}
            data.setdefault("cards", []).insert(0, card)
            made.append(card)
    data["cards"] = data["cards"][:40]
    _save(CB_FILE, data)
    return {"cards": made, "total": len(data.get("cards", []))}


@router.get("/api/cards/deck")
async def cards_deck():
    data = _load(CB_FILE, {"cards": [], "records": []})
    return {"cards": data.get("cards", []),
            "stats": {"total": len(data.get("cards", [])),
                      "battles": len(data.get("records", []))}}


@router.delete("/api/cards/{cid}")
async def cards_del(cid: str):
    data = _load(CB_FILE, {"cards": [], "records": []})
    before = len(data.get("cards", []))
    data["cards"] = [c for c in data.get("cards", []) if c.get("id") != cid]
    if len(data["cards"]) == before:
        return JSONResponse({"error": "卡牌不存在"}, status_code=404)
    _save(CB_FILE, data)
    return {"ok": True}


@router.post("/api/cards/battle")
async def cards_battle(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    her_ids = body.get("her", []) or []
    him_ids = body.get("him", []) or []
    data = _load(CB_FILE, {"cards": [], "records": []})
    all_cards = data.get("cards", [])
    by_id = {c["id"]: c for c in all_cards}
    her_cards = [by_id.get(i) for i in her_ids if by_id.get(i)]
    him_cards = [by_id.get(i) for i in him_ids if by_id.get(i)]
    if len(her_cards) < 1 or len(him_cards) < 1:
        return JSONResponse({"error": "双方至少各选一张卡牌"}, status_code=400)
    her_cards, him_cards = her_cards[:3], him_cards[:3]
    def _power(cards):
        return sum(int(c.get("sweet", 50)) + int(c.get("tacit", 50)) + int(c.get("wave", 50)) for c in cards)
    hp, pp = _power(her_cards), _power(him_cards)
    her_win = hp + random.randint(-25, 25) >= pp + random.randint(-25, 25)
    winner = "her" if her_win else "him"
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    def _card_view(c):
        return {"memory": c.get("memory"), "sweet": c.get("sweet"), "tacit": c.get("tacit"),
                "wave": c.get("wave"), "flavor": c.get("flavor")}
    her_view = json.dumps([_card_view(c) for c in her_cards], ensure_ascii=False)
    him_view = json.dumps([_card_view(c) for c in him_cards], ensure_ascii=False)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【记忆卡牌对决】她和你用你们的记忆卡牌对局。战斗其实是回忆的共鸣——"
        "每一回合的'攻防'都是某段回忆在闪光。\n"
        f"她的卡：{her_view}\n"
        f"我的卡：{him_view}\n"
        f"本局胜者：{'她' if winner == 'her' else '许墨'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"narration":"150字内对局描述（把牌面数值写成回忆的交锋，有画面感）",'
        '"winner_line":"胜者视角40字内的话（若她赢：许墨宠溺地认输；若他赢：许墨温柔地收手）",'
        '"recount":"80字内胜者讲的一段回忆（第一人称「我」，讲那张最亮的卡背后的故事）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "开一局吧，只输出 JSON。"}], max_tokens=900)
    except Exception:
        rep = {}
    rep.setdefault("narration", "你们亮出彼此的牌，回忆在桌面上交相辉映。")
    rep.setdefault("winner_line", "这局，算你赢了——因为想起你，我总是先退让。")
    rep.setdefault("recount", "还记得那天吗？风很大，你笑得很轻。")
    record = {
        "id": _nid(), "ts": _ts(),
        "her": her_cards, "him": him_cards,
        "her_power": hp, "him_power": pp,
        "winner": winner, **rep,
    }
    data.setdefault("records", []).insert(0, record)
    data["records"] = data["records"][:30]
    _save(CB_FILE, data)
    _affinity("mind_quiz", "记忆卡牌对决")
    return {"record": record}


@router.get("/api/cards/records")
async def cards_records():
    data = _load(CB_FILE, {"cards": [], "records": []})
    return {"records": data.get("records", [])}


# ===========================================================================
# 4. 合著专辑：你们的歌
# ===========================================================================
ALBUM_STEPS = ["主歌一", "副歌一", "主歌二", "副歌二", "尾声"]


@router.post("/api/album/start")
async def album_start(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    mood = str(body.get("mood", "")).strip()[:60]
    style = str(body.get("style", "")).strip()[:40]
    if not mood:
        return JSONResponse({"error": "说说这首歌的感觉（比如'雨夜'、'初雪'、'吵架后和好'）"}, status_code=400)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【合著专辑】你和她在共同写一首歌。你写第一段主歌，她写副歌，交替完成。\n"
        f"主题感觉：{mood}{('，风格：' + style) if style else ''}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        "要求：主歌一 2-4 句，克制、画面感强、可带一句学术/天文意象；不要副歌式重复；押韵自然。\n"
        '输出 JSON：{"title_hint":"10字内歌名候选（未定稿）",'
        '"verse":"主歌一歌词（2-4句）",'
        '"why":"20字内他为什么写这句（许墨视角）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "开始写吧，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("title_hint", "未定")
    rep.setdefault("verse", "雨落在旧窗台，像我们没说出口的对白。")
    rep.setdefault("why", "因为他记得她在雨里说过的话。")
    song = {
        "id": _nid(), "ts": _ts(), "mood": mood, "style": style,
        "title": None, "title_hint": rep["title_hint"],
        "verses": [{"who": "xumo", "step": ALBUM_STEPS[0], "text": rep["verse"],
                    "why": rep["why"], "ts": _ts()}],
        "status": "writing", "sample_audio": "",
    }
    data = _load(AL_FILE, {"songs": []})
    data.setdefault("songs", []).insert(0, song)
    data["songs"] = data["songs"][:20]
    _save(AL_FILE, data)
    return {"song": song}


@router.post("/api/album/{sid}/verse")
async def album_verse(sid: str, req: Request):
    """她写下一句，许墨接下一段；轮到尾声则完成整首歌。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = str(body.get("text", "")).strip()[:300]
    if not text:
        return JSONResponse({"error": "写一句歌词吧"}, status_code=400)
    data = _load(AL_FILE, {"songs": []})
    song = next((s for s in data.get("songs", []) if s.get("id") == sid), None)
    if not song:
        return JSONResponse({"error": "歌曲不存在"}, status_code=404)
    if song.get("status") != "writing":
        return JSONResponse({"error": "这首歌已经完成"}, status_code=400)
    idx = len(song.get("verses", []))
    song.setdefault("verses", []).append({"who": "her", "step": ALBUM_STEPS[idx], "text": text, "ts": _ts()})
    # 轮到许墨接
    next_idx = idx + 1
    if next_idx >= len(ALBUM_STEPS):
        # 全部完成
        song["status"] = "done"
        song["finished_at"] = _ts()
        _save(AL_FILE, data)
        _affinity("listen", "合著专辑完成")
        return {"song": song, "done": True, "reply": None}
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【合著专辑·接力】她在写你们的歌。轮到你接下一段。\n"
        f"歌名候选：{song.get('title_hint')}　主题：{song.get('mood')}{('　风格：' + song.get('style')) if song.get('style') else ''}\n"
        f"已有歌词：\n" + "\n".join(f"{ALBUM_STEPS[i]}：{v['text']}" for i, v in enumerate(song.get('verses', []))) + "\n"
        f"她刚写的：{text}\n"
        f"你的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        f"现在写「{ALBUM_STEPS[next_idx]}」（2-4句）：\n"
        "1. 呼应她的句子（接住情绪或意象），可转韵但保持自然；\n"
        "2. 克制温柔，可带一处科学/天文意象；\n"
        '3. 若这一步是"尾声"，写收束全曲的 1-2 句，并给出最终歌名。\n'
        '输出 JSON：{"verse":"歌词",'
        '"why":"20字内为什么这样接（许墨视角）",'
        '"title":"仅尾声时给出最终歌名，否则空串"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "接下去吧，只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("verse", "……而我在雨里等了很久，等你来收伞。")
    rep.setdefault("why", "想让她知道，她的每一句他都会接住。")
    rep.setdefault("title", "")
    song.setdefault("verses", []).append({"who": "xumo", "step": ALBUM_STEPS[next_idx],
                                          "text": rep["verse"], "why": rep["why"], "ts": _ts()})
    if next_idx == len(ALBUM_STEPS) - 1:
        song["status"] = "done"
        song["finished_at"] = _ts()
        song["title"] = rep["title"] or song.get("title_hint")
        _save(AL_FILE, data)
        _affinity("listen", "合著专辑完成")
        return {"song": song, "done": True, "reply": rep}
    _save(AL_FILE, data)
    return {"song": song, "done": False, "reply": rep}


@router.post("/api/album/{sid}/sample")
async def album_sample(sid: str):
    """把副歌合成为语音小样。"""
    data = _load(AL_FILE, {"songs": []})
    song = next((s for s in data.get("songs", []) if s.get("id") == sid), None)
    if not song:
        return JSONResponse({"error": "歌曲不存在"}, status_code=404)
    if song.get("sample_audio"):
        return {"audio": song["sample_audio"], "cached": True}
    verses = song.get("verses", [])
    if not verses:
        return JSONResponse({"error": "还没有歌词"}, status_code=400)
    from app import (_tts_clean, _tts_synthesize, _tts_emo)
    import httpx
    # 取副歌或最后一段唱
    chorus = next((v for v in reversed(verses) if "副歌" in v.get("step", "")), None) or verses[-1]
    text = _tts_clean(chorus.get("text", ""))
    if not text:
        return JSONResponse({"error": "歌词为空"}, status_code=400)
    try:
        from role_data import RolePath
        out = RolePath("static", "album_samples")
        out.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0), trust_env=False) as client:
            wav = await _tts_synthesize(client, text, 0.95, *_tts_emo({"emotion": "tender"}))
        fname = f"{sid}.wav"
        (out / fname).write_bytes(wav)
        song["sample_audio"] = f"/static/album_samples/{fname}"
        _save(AL_FILE, data)
        return {"audio": song["sample_audio"], "cached": False}
    except Exception as exc:
        return JSONResponse({"error": f"语音小样失败：{str(exc)[:120]}（歌曲本身已保存）"}, status_code=502)


@router.get("/api/album/list")
async def album_list():
    data = _load(AL_FILE, {"songs": []})
    return {"songs": data.get("songs", [])}


@router.delete("/api/album/{sid}")
async def album_del(sid: str):
    data = _load(AL_FILE, {"songs": []})
    data["songs"] = [s for s in data.get("songs", []) if s.get("id") != sid]
    _save(AL_FILE, data)
    return {"ok": True}


# ===========================================================================
# 5. 云旅行：一起走世界
# ===========================================================================
TRAVEL_CITIES = [
    {"name": "京都", "country": "日本", "tags": ["古寺", "枫叶", "和纸灯"], "line": "祇园的灯笼亮起来时，风是慢的。"},
    {"name": "巴黎", "country": "法国", "tags": ["塞纳河", "咖啡馆", "旧书摊"], "line": "左岸的雨里，有没写完的情诗。"},
    {"name": "大理", "country": "中国", "tags": ["洱海", "苍山", "白族小院"], "line": "洱海的风会把心事吹得很远，再吹回来。"},
    {"name": "冰岛", "country": "冰岛", "tags": ["极光", "黑沙滩", "温泉"], "line": "这里的夜足够长，长到能看完一整场极光。"},
    {"name": "伊斯坦布尔", "country": "土耳其", "tags": ["海峡", "蓝色清真寺", "市集"], "line": "博斯普鲁斯的晚霞，是两种大陆共用的黄昏。"},
    {"name": "拉萨", "country": "中国", "tags": ["高原", "转经筒", "酥油茶"], "line": "海拔高了，心跳声会变得很清晰。"},
    {"name": "马尔代夫", "country": "马尔代夫", "tags": ["环礁", "玻璃海", "落日帆"], "line": "海水清到能看见时间沉底的样子。"},
    {"name": "罗马", "country": "意大利", "tags": ["许愿池", "废墟", "gelato"], "line": "在许愿池扔硬币的人，都想要同一个答案。"},
    {"name": "哈尔滨", "country": "中国", "tags": ["雪雕", "冰灯", "中央大街"], "line": "零下二十度的呼吸，会结成看得见的形状。"},
    {"name": "上海", "country": "中国", "tags": ["外滩", "梧桐", "弄堂"], "line": "梧桐树影里，这座城其实很慢。"},
    {"name": "皇后镇", "country": "新西兰", "tags": ["湖泊", "雪山", "星空"], "line": "南半球的星空，是倒着写的情书。"},
    {"name": "敦煌", "country": "中国", "tags": ["莫高窟", "鸣沙山", "月牙泉"], "line": "沙鸣的时候，千年前的壁画也在轻轻呼吸。"},
]


@router.get("/api/travel/cities")
async def travel_cities():
    data = _load(TR_FILE, {"visits": []})
    visited = {v["city"] for v in data.get("visits", [])}
    cities = [dict(c, visited=c["name"] in visited) for c in TRAVEL_CITIES]
    return {"cities": cities}


@router.post("/api/travel/visit")
async def travel_visit(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    city = str(body.get("city", "")).strip()
    wish = str(body.get("wish", "")).strip()[:80]
    info = next((c for c in TRAVEL_CITIES if c["name"] == city), None)
    if not info:
        return JSONResponse({"error": "还没有这个城市，先选一个目的地吧"}, status_code=400)
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【云旅行·当地陪】你们'一起'到了" + city + "（她在线打卡，你以当地人的身份陪她逛）。\n"
        "你是那里的'熟客'，用游客听不到的视角带她走。\n"
        f"城市：{info['name']}（{info['country']}）　特色：{'、'.join(info['tags'])}\n"
        f"她的愿望：{wish or '（没有特别愿望，就是想和你走走）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"greeting":"40字内当地口吻的开场（一句方言口音的话+翻译）",'
        '"scene":"100字内带她走过的一处地方（写实、有细节、你在场）",'
        '"legend":"60字内只属于这里的传说或冷知识",'
        '"food":"30字内本地美食（他会记得她口味的细节）",'
        '"line":"30字内此刻他对她说的一句话"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "带她逛逛吧，只输出 JSON。"}], max_tokens=900)
    except Exception:
        rep = {}
    rep.setdefault("greeting", "（用当地话打了个招呼）欢迎来" + city + "。")
    rep.setdefault("scene", f"你们沿着{info['tags'][0]}慢慢走，风把他的话吹得忽远忽近。")
    rep.setdefault("legend", "这里有个说法：一起看过的人，会一直记得同一种光。")
    rep.setdefault("food", "本地小吃，配一杯热饮正好。")
    rep.setdefault("line", "以后，我们真的来一次。")
    visit = {
        "id": _nid(), "city": city, "country": info["country"],
        "tags": info["tags"], "wish": wish, "ts": _ts(), **rep,
        "promise": "",
    }
    data = _load(TR_FILE, {"visits": []})
    data.setdefault("visits", []).insert(0, visit)
    data["visits"] = data["visits"][:50]
    _save(TR_FILE, data)
    _affinity("date_plan", f"云旅行·{city}")
    return {"visit": visit}


@router.get("/api/travel/journal")
async def travel_journal():
    data = _load(TR_FILE, {"visits": []})
    return {"visits": data.get("visits", []), "total": len(data.get("visits", [])),
            "countries": len({v.get("country") for v in data.get("visits", []) if v.get("country")})}


@router.post("/api/travel/{vid}/promise")
async def travel_promise(vid: str, req: Request):
    """把'以后一起去'变成一条正式约定。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    promise = str(body.get("promise", "")).strip()[:120]
    data = _load(TR_FILE, {"visits": []})
    visit = next((v for v in data.get("visits", []) if v.get("id") == vid), None)
    if not visit:
        return JSONResponse({"error": "行程不存在"}, status_code=404)
    visit["promise"] = promise or f"以后一起去{visit['city']}"
    _save(TR_FILE, data)
    _affinity("anniversary", f"旅行约定·{visit['city']}")
    return {"visit": visit}
