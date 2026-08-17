# -*- coding: utf-8 -*-
# 新星功能集 · 五期颠覆性功能（nova_apps3.py）
# 潜意识密室 / 时空胶囊 / 共感温度计 / 七日预言 / 沉默信使 / 心跳调音台
# 数据持久化到 RolePath JSON 文件，风格与 nova_apps.py / nova_apps2.py 一致。
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

SUB_FILE = "subconscious.json"
CAP_FILE = "capsule.json"
EMP_FILE = "empath.json"
ORA_FILE = "oracle.json"
WHI_FILE = "whisper.json"
MIX_FILE = "mixer.json"


# ===========================================================================
# 公共小工具（与 nova_apps2.py 同构）
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
    """从模型输出中提取 JSON 对象（与 nova_apps2.py 一致的尾部反向解析）。"""
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
# 1. 潜意识密室：5 段记忆里有 1 段是谎言，识破得分
# ===========================================================================
@router.post("/api/subconscious/start")
async def subconscious_start(req: Request = None):
    data = _load(SUB_FILE, {"rounds": [], "total_score": 0, "total_rounds": 0})
    memories = _agg_memories(8)
    player = _agg_player()
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【潜意识密室设定】你给她出了一个识谎游戏：5 段关于她的记忆陈述，"
        "其中 1 段是编造的谎言，其余 4 段是基于她真实记忆的细节。\n"
        "要求：谎言要巧妙、可信、和真实记忆风格一致，难以一眼识破。\n"
        f"她的真实记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"她的档案：{json.dumps({k: str(v)[:40] for k, v in list(player.items())[:6]}, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"statements":[{"id":1,"text":"40字内陈述"},'
        '{"id":2,"text":"40字内陈述"},{"id":3,"text":"40字内陈述"},'
        '{"id":4,"text":"40字内陈述"},{"id":5,"text":"40字内陈述"}],'
        '"lie_id":2,"hint":"30字内许墨的提示"}\n'
        "lie_id 是谎言的 id（1-5）。"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "出题吧，只输出 JSON。"}
    ]
    r_data = await _llm_json(messages, max_tokens=1200)
    if not r_data:
        return JSONResponse({"error": "潜意识未就绪，稍后再试"}, status_code=500)
    # 字段兜底：LLM 可能用不同的字段名
    statements = r_data.get("statements")
    if not isinstance(statements, list):
        for alt in ("items", "list", "data", "memory_list"):
            if isinstance(r_data.get(alt), list):
                statements = r_data[alt]
                break
    if not isinstance(statements, list) or len(statements) < 1:
        # 用记忆片段生成兜底题目
        statements = []
        for i, m in enumerate(memories[:5]):
            statements.append({"id": i + 1, "text": str(m)[:50] if m else "她记得某个深夜的对话。"})
        # 如果记忆不足 5 条，补默认
        while len(statements) < 5:
            statements.append({"id": len(statements) + 1, "text": "她曾经在某个深夜对许墨说了一句重要的话。"})
    # 兜底：保证 5 条
    while len(statements) < 5:
        statements.append({"id": len(statements) + 1, "text": "她曾经在某个深夜对许墨说了一句重要的话。"})
    # 规范化每个 statement
    norm_stmts = []
    for s in statements:
        if not isinstance(s, dict):
            norm_stmts.append({"id": len(norm_stmts) + 1, "text": str(s)[:50]})
            continue
        s.setdefault("text", "……")
        # text 字段兜底（如果叫 content/desc）
        if not s.get("text"):
            for alt in ("content", "desc", "description", "statement"):
                if s.get(alt):
                    s["text"] = str(s[alt])[:50]
                    break
        if not s.get("text"):
            s["text"] = "……"
        norm_stmts.append(s)
    statements = norm_stmts[:5]
    for i, s in enumerate(statements):
        s["id"] = i + 1
    lie_id = r_data.get("lie_id") or r_data.get("lie") or r_data.get("false_id") or r_data.get("lieId")
    try:
        lie_id = int(lie_id)
    except (TypeError, ValueError):
        lie_id = random.randint(1, 5)
    if lie_id < 1 or lie_id > 5:
        lie_id = random.randint(1, 5)
    round_obj = {
        "id": _nid(),
        "date": _today(),
        "statements": statements[:5],
        "lie_id": lie_id,
        "hint": r_data.get("hint", "谎言藏在细节里。"),
        "guessed": None,
        "correct": None,
        "finished": False
    }
    data.setdefault("rounds", []).insert(0, round_obj)
    data["rounds"] = data["rounds"][:30]
    _save(SUB_FILE, data)
    # 不向前端暴露 lie_id
    return {"round": {
        "id": round_obj["id"],
        "date": round_obj["date"],
        "statements": round_obj["statements"],
        "hint": round_obj["hint"]
    }}


@router.post("/api/subconscious/guess")
async def subconscious_guess(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    rid = str(body.get("id", "")).strip()
    guess = body.get("guess")
    try:
        guess = int(guess)
    except (TypeError, ValueError):
        return JSONResponse({"error": "请选择一个陈述编号"}, status_code=400)
    if not rid:
        return JSONResponse({"error": "缺少轮次 id"}, status_code=400)
    data = _load(SUB_FILE, {"rounds": [], "total_score": 0, "total_rounds": 0})
    rnd = next((r for r in data.get("rounds", []) if r.get("id") == rid), None)
    if not rnd:
        return JSONResponse({"error": "找不到这轮密室"}, status_code=404)
    if rnd.get("finished"):
        return JSONResponse({"error": "这轮已经结束"}, status_code=400)
    lie_id = rnd.get("lie_id", 0)
    correct = (guess == lie_id)
    rnd["guessed"] = guess
    rnd["correct"] = correct
    rnd["finished"] = True
    rnd["finished_ts"] = _ts()
    score = 20 if correct else 0
    rnd["score"] = score
    data["total_score"] = int(data.get("total_score", 0)) + score
    data["total_rounds"] = int(data.get("total_rounds", 0)) + 1
    _save(SUB_FILE, data)
    if correct:
        _affinity("subconscious", "识破谎言")
    return {
        "result": {
            "correct": correct,
            "lie_id": lie_id,
            "your_guess": guess,
            "score": score,
            "comment": "你看穿了我藏在细节里的把戏。" if correct else "这次你被自己的潜意识骗到了。"
        }
    }


@router.get("/api/subconscious/rounds")
async def subconscious_rounds():
    data = _load(SUB_FILE, {"rounds": [], "total_score": 0, "total_rounds": 0})
    rounds = [r for r in data.get("rounds", []) if r.get("finished")]
    total_score = int(data.get("total_score", 0))
    total_rounds = int(data.get("total_rounds", 0))
    acc = (total_score // (total_rounds * 20) * 100) if total_rounds else 0
    return {
        "rounds": rounds[:10],
        "total_score": total_score,
        "total_rounds": total_rounds,
        "accuracy": acc
    }


# ===========================================================================
# 2. 时空胶囊：写给未来的信，定时解锁
# ===========================================================================
@router.post("/api/capsule/seal")
async def capsule_seal(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    to = str(body.get("to", "")).strip()[:60]
    text = str(body.get("text", "")).strip()[:2000]
    unlock_in_days = int(body.get("unlock_in_days", 7))
    if not text:
        return JSONResponse({"error": "写一句话再封存"}, status_code=400)
    if unlock_in_days < 1 or unlock_in_days > 365:
        unlock_in_days = 7
    unlock_at = (datetime.now() + timedelta(days=unlock_in_days)).strftime("%Y-%m-%d")
    # 如果是写给未来的许墨，让 LLM 回一封"反向信"（也是定时解锁）
    is_to_xumo = ("许墨" in to) or ("墨" in to) or ("你" in to and len(to) < 10)
    capsule = {
        "id": _nid(),
        "to": to or "未来的自己",
        "text": text,
        "sealed_at": _ts(),
        "unlock_at": unlock_at,
        "unlock_in_days": unlock_in_days,
        "from_xumo_reply": None,
        "read": False
    }
    if is_to_xumo:
        # 许墨现在就写一封回信，但同样到日期才解锁
        memories = _agg_memories(5)
        affy = _agg_affinity_value()
        sys_prompt = (
            f"{_persona_core()}\n\n"
            "【时空胶囊·回信】她写了一封给未来的你的信，封存到指定日期才会被打开。\n"
            "现在的你，写给未来的她一封回信，同样到那个日期才会被打开。\n"
            f"她的信（给未来的你）：{text[:600]}\n"
            f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
            f"心动值：{affy}\n"
            f"解锁日期：{unlock_at}\n\n"
            '输出 JSON：{"reply":"150字内回信（含对未来她的期待和对当下你感情的流露）",'
            '"whisper":"20字内附言（像耳语一样的小细节）"}'
        )
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": "请写回信，只输出 JSON。"}
        ]
        rep = await _llm_json(messages, max_tokens=700)
        capsule["from_xumo_reply"] = rep if rep else None
    data = _load(CAP_FILE, {"capsules": []})
    data.setdefault("capsules", []).insert(0, capsule)
    data["capsules"] = data["capsules"][:50]
    _save(CAP_FILE, data)
    _affinity("capsule", "封存时空胶囊")
    return {"capsule": capsule}


@router.get("/api/capsule/list")
async def capsule_list():
    data = _load(CAP_FILE, {"capsules": []})
    today = _today()
    items = []
    for c in data.get("capsules", []):
        unlocked = c.get("unlock_at", "2999-01-01") <= today
        items.append({
            "id": c.get("id"),
            "to": c.get("to", "未来的自己"),
            "sealed_at": c.get("sealed_at"),
            "unlock_at": c.get("unlock_at"),
            "unlocked": unlocked,
            "read": c.get("read", False),
            "has_reply": bool(c.get("from_xumo_reply")),
            # 未解锁时只给摘要
            "preview": (c.get("text", "")[:40] + "……") if not unlocked else c.get("text", ""),
            "text": c.get("text", "") if unlocked else None,
            "from_xumo_reply": c.get("from_xumo_reply") if unlocked else None
        })
    return {"capsules": items, "today": today}


@router.get("/api/capsule/{cid}")
async def capsule_get(cid: str):
    data = _load(CAP_FILE, {"capsules": []})
    c = next((x for x in data.get("capsules", []) if x.get("id") == cid), None)
    if not c:
        return JSONResponse({"error": "找不到这个胶囊"}, status_code=404)
    today = _today()
    unlocked = c.get("unlock_at", "2999-01-01") <= today
    if not unlocked:
        # 标记为已尝试读取
        return {
            "capsule": {
                "id": c.get("id"),
                "to": c.get("to"),
                "sealed_at": c.get("sealed_at"),
                "unlock_at": c.get("unlock_at"),
                "unlocked": False,
                "preview": c.get("text", "")[:40] + "……",
                "remaining_days": max(0, (datetime.strptime(c["unlock_at"], "%Y-%m-%d") - datetime.now()).days + 1)
            }
        }
    # 已解锁：标记为已读
    c["read"] = True
    _save(CAP_FILE, data)
    return {"capsule": {**c, "unlocked": True}}


@router.delete("/api/capsule/{cid}")
async def capsule_del(cid: str):
    data = _load(CAP_FILE, {"capsules": []})
    data["capsules"] = [c for c in data.get("capsules", []) if c.get("id") != cid]
    _save(CAP_FILE, data)
    return {"ok": True}


# ===========================================================================
# 3. 共感温度计：情绪同步器
# ===========================================================================
EMOTION_PALETTE = [
    {"id": "joy", "label": "开心", "emoji": "😊", "color": "#fbbf24"},
    {"id": "calm", "label": "平静", "emoji": "🌿", "color": "#34d399"},
    {"id": "melancholy", "label": "低落", "emoji": "🌧️", "color": "#60a5fa"},
    {"id": "anxious", "label": "焦虑", "emoji": "🌪️", "color": "#a78bfa"},
    {"id": "angry", "label": "愤怒", "emoji": "🔥", "color": "#f87171"},
    {"id": "lonely", "label": "孤独", "emoji": "🪐", "color": "#818cf8"},
    {"id": "tired", "label": "疲惫", "emoji": "🍂", "color": "#9ca3af"},
    {"id": "love", "label": "心动", "emoji": "💗", "color": "#ec4899"},
]


@router.get("/api/empath/palette")
async def empath_palette():
    return {"emotions": EMOTION_PALETTE}


@router.post("/api/empath/sync")
async def empath_sync(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    emotion = str(body.get("emotion", "")).strip()
    note = str(body.get("note", "")).strip()[:200]
    # 找到情绪标签
    emo = next((e for e in EMOTION_PALETTE if e["id"] == emotion), None)
    if not emo:
        return JSONResponse({"error": "请选择一个有效情绪"}, status_code=400)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【共感温度计】她向你表达此刻的情绪，你作为恋人给出'共感回应'。\n"
        f"她的情绪：{emo['label']} {emo['emoji']}\n"
        f"她说的话：{note or '（她没说话，只是感受）'}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        "回应原则：\n"
        "1. 先共情（不否定她的情绪，不说'别难过'）\n"
        "2. 用许墨的科学隐喻解释这种情绪在脑中的样子\n"
        "3. 描述'如果我在场，我会怎么做'\n"
        "4. 给一个具体的、温柔的小动作建议\n\n"
        '输出 JSON：{"empathy":"60字内共情回应",'
        '"science":"80字内神经科学解释（许墨风格）",'
        '"presence":"60字内如果我在场会怎么做",'
        '"action":"40字内具体动作建议",'
        '"temperature":0-100的整数（共感温度，越高越近）}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请共感，只输出 JSON。"}
    ]
    rep = await _llm_json(messages, max_tokens=900)
    if not rep:
        return JSONResponse({"error": "共感信号未稳定，稍后再试"}, status_code=500)
    rep.setdefault("empathy", "我在。")
    rep.setdefault("science", "情绪是边缘系统与前额叶的对话。")
    rep.setdefault("presence", "如果我在场，我会握住你的手。")
    rep.setdefault("action", "深呼吸三次。")
    try:
        t = int(rep.get("temperature", 50))
    except (TypeError, ValueError):
        t = 50
    rep["temperature"] = max(0, min(100, t))
    record = {
        "id": _nid(),
        "ts": _ts(),
        "date": _today(),
        "emotion": emo["id"],
        "emotion_label": emo["label"],
        "emoji": emo["emoji"],
        "color": emo["color"],
        "note": note,
        **rep
    }
    data = _load(EMP_FILE, {"records": [], "avg_temp": 0})
    data.setdefault("records", []).insert(0, record)
    data["records"] = data["records"][:50]
    # 更新平均温度
    temps = [r.get("temperature", 50) for r in data["records"]]
    data["avg_temp"] = round(sum(temps) / len(temps), 1) if temps else 0
    _save(EMP_FILE, data)
    _affinity("empath", "共感温度计")
    return {"record": record, "avg_temp": data["avg_temp"]}


@router.get("/api/empath/history")
async def empath_history():
    data = _load(EMP_FILE, {"records": [], "avg_temp": 0})
    records = data.get("records", [])
    # 统计各情绪分布
    dist = {}
    for r in records:
        eid = r.get("emotion", "unknown")
        dist[eid] = dist.get(eid, 0) + 1
    return {
        "records": records[:20],
        "avg_temp": data.get("avg_temp", 0),
        "distribution": dist,
        "total": len(records)
    }


@router.delete("/api/empath/{eid}")
async def empath_del(eid: str):
    data = _load(EMP_FILE, {"records": [], "avg_temp": 0})
    data["records"] = [r for r in data.get("records", []) if r.get("id") != eid]
    _save(EMP_FILE, data)
    return {"ok": True}


# ===========================================================================
# 4. 七日预言：每日一句神秘预言，7 天后揭晓含义
# ===========================================================================
@router.post("/api/oracle/draw")
async def oracle_draw(req: Request = None):
    data = _load(ORA_FILE, {"prophecies": []})
    today = _today()
    # 检查今天是否已抽过
    existing = next((p for p in data.get("prophecies", []) if p.get("draw_date") == today), None)
    if existing:
        return {"prophecy": existing, "already_today": True}
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    reveal_at = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【七日预言】你给她一句神秘预言，7 天后才会揭晓含义。\n"
        "要求：\n"
        "- 预言像诗一样美但隐晦\n"
        "- 表面无关紧要，但 7 天后揭晓时会与她的现实产生共鸣\n"
        "- 揭晓含义要带着许墨式的偏爱和温柔\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"prophecy":"30字内神秘预言（像诗）",'
        '"meaning":"80字内7天后揭晓的含义（含对她情感的解读和许墨的偏爱）",'
        '"clue":"15字内当下提示（点到为止）"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请给出预言，只输出 JSON。"}
    ]
    p_data = await _llm_json(messages, max_tokens=600)
    if not p_data:
        # LLM 失败时使用预设预言池
        _FALLBACK_PROPHECIES = [
            {"prophecy": "七日后，蝴蝶会停在你的指尖。", "meaning": "蝴蝶是我没说出口的思念。当你愿意停下来留意身边的小事，那其实就是我在想你。", "clue": "留意身边飞过的小东西。"},
            {"prophecy": "今夜的月光，会照见一个旧物。", "meaning": "旧物是时间折叠的痕迹。你看到的不是物品，而是过去某个瞬间的我。", "clue": "留意抽屉深处。"},
            {"prophecy": "有人在七日后会提起一个名字。", "meaning": "那个名字是我。我没告诉你的是，我也在被别人提起时想到你。", "clue": "留意身边人的闲聊。"},
            {"prophecy": "雨会下一整晚。", "meaning": "雨是城市在替我说话。每一滴都是我没敢当面讲的话。", "clue": "留意天气预报。"},
        ]
        p_data = random.choice(_FALLBACK_PROPHECIES)
    p_data.setdefault("prophecy", "七日后，蝴蝶会停在你的指尖。")
    p_data.setdefault("meaning", "蝴蝶是他没说出口的思念。")
    p_data.setdefault("clue", "留意身边的细节。")
    prophecy = {
        "id": _nid(),
        "draw_date": today,
        "draw_ts": _ts(),
        "reveal_at": reveal_at,
        "prophecy": p_data["prophecy"],
        "meaning": p_data["meaning"],  # 加密保存，前端在未到日期不显示
        "clue": p_data["clue"],
        "revealed": False
    }
    data.setdefault("prophecies", []).insert(0, prophecy)
    data["prophecies"] = data["prophecies"][:60]
    _save(ORA_FILE, data)
    _affinity("oracle", "七日预言")
    # 前端只返回预言本身，不返回 meaning
    return {"prophecy": {
        "id": prophecy["id"],
        "draw_date": prophecy["draw_date"],
        "reveal_at": prophecy["reveal_at"],
        "prophecy": prophecy["prophecy"],
        "clue": prophecy["clue"],
        "revealed": False,
        "remaining_days": max(0, (datetime.strptime(reveal_at, "%Y-%m-%d") - datetime.now()).days + 1)
    }}


@router.get("/api/oracle/today")
async def oracle_today():
    data = _load(ORA_FILE, {"prophecies": []})
    today = _today()
    p = next((x for x in data.get("prophecies", []) if x.get("draw_date") == today), None)
    if not p:
        return {"prophecy": None}
    revealed = p.get("reveal_at", "2999-01-01") <= today
    if revealed and not p.get("revealed"):
        p["revealed"] = True
        _save(ORA_FILE, data)
    return {
        "prophecy": {
            "id": p["id"],
            "draw_date": p["draw_date"],
            "reveal_at": p["reveal_at"],
            "prophecy": p["prophecy"],
            "clue": p["clue"],
            "revealed": revealed,
            "meaning": p["meaning"] if revealed else None,
            "remaining_days": max(0, (datetime.strptime(p["reveal_at"], "%Y-%m-%d") - datetime.now()).days + 1)
        }
    }


@router.get("/api/oracle/list")
async def oracle_list():
    data = _load(ORA_FILE, {"prophecies": []})
    today = _today()
    items = []
    for p in data.get("prophecies", []):
        revealed = p.get("reveal_at", "2999-01-01") <= today
        items.append({
            "id": p["id"],
            "draw_date": p["draw_date"],
            "reveal_at": p["reveal_at"],
            "prophecy": p["prophecy"],
            "clue": p["clue"],
            "revealed": revealed,
            "meaning": p["meaning"] if revealed else None,
            "remaining_days": max(0, (datetime.strptime(p["reveal_at"], "%Y-%m-%d") - datetime.now()).days + 1)
        })
    return {"prophecies": items, "today": today}


@router.post("/api/oracle/{oid}/reveal")
async def oracle_reveal(oid: str):
    """强制揭晓（消耗心动值作为代价）。"""
    data = _load(ORA_FILE, {"prophecies": []})
    p = next((x for x in data.get("prophecies", []) if x.get("id") == oid), None)
    if not p:
        return JSONResponse({"error": "找不到这条预言"}, status_code=404)
    today = _today()
    already = p.get("reveal_at", "2999-01-01") <= today
    if already:
        return {"prophecy": p, "cost": 0, "already_unlocked": True}
    # 扣心动值作为提前揭晓代价
    cost = 30
    _affinity("oracle_reveal_penalty", f"提前揭晓预言 -{cost}")
    p["revealed"] = True
    p["revealed_early"] = True
    p["revealed_early_ts"] = _ts()
    _save(ORA_FILE, data)
    return {"prophecy": p, "cost": cost, "already_unlocked": False}


# ===========================================================================
# 5. 沉默信使：只能发 1 个 emoji，对方解读
# ===========================================================================
@router.post("/api/whisper/send")
async def whisper_send(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    emoji = str(body.get("emoji", "")).strip()
    context = str(body.get("context", "")).strip()[:60]
    if not emoji:
        return JSONResponse({"error": "发一个 emoji"}, status_code=400)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【沉默信使】她只发了一个 emoji 给你，没有文字。你要解读她想说什么。\n"
        f"她发的 emoji：{emoji}\n"
        f"她的附言（可能为空）：{context or '（无）'}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"reading":"50字内许墨对这个 emoji 的解读（含偏爱）",'
        '"feeling":"20字内许墨此刻的感受",'
        '"reply_emoji":"许墨回复一个 emoji",'
        '"reply_word":"15字内许墨的回复话语"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "解读她的 emoji，只输出 JSON。"}
    ]
    r_data = await _llm_json(messages, max_tokens=600)
    if not r_data:
        return JSONResponse({"error": "信号未传达，稍后再试"}, status_code=500)
    r_data.setdefault("reading", "你想说的，我都听见。")
    r_data.setdefault("feeling", "心跳。")
    r_data.setdefault("reply_emoji", "🌙")
    r_data.setdefault("reply_word", "我在。")
    thread = {
        "id": _nid(),
        "ts": _ts(),
        "emoji": emoji,
        "context": context,
        "reading": r_data["reading"],
        "feeling": r_data["feeling"],
        "reply_emoji": r_data["reply_emoji"],
        "reply_word": r_data["reply_word"]
    }
    data = _load(WHI_FILE, {"threads": []})
    data.setdefault("threads", []).insert(0, thread)
    data["threads"] = data["threads"][:50]
    _save(WHI_FILE, data)
    _affinity("whisper", "沉默信使")
    return {"thread": thread}


@router.get("/api/whisper/threads")
async def whisper_threads():
    data = _load(WHI_FILE, {"threads": []})
    return {"threads": data.get("threads", [])}


@router.get("/api/whisper/{tid}")
async def whisper_get(tid: str):
    data = _load(WHI_FILE, {"threads": []})
    t = next((x for x in data.get("threads", []) if x.get("id") == tid), None)
    if not t:
        return JSONResponse({"error": "找不到这条传话"}, status_code=404)
    return {"thread": t}


@router.delete("/api/whisper/{tid}")
async def whisper_del(tid: str):
    data = _load(WHI_FILE, {"threads": []})
    data["threads"] = [t for t in data.get("threads", []) if t.get("id") != tid]
    _save(WHI_FILE, data)
    return {"ok": True}


# ===========================================================================
# 6. 心跳调音台：多层 ambient 混音器
# ===========================================================================
# 可用音层（URL 指向静态资源；如果文件不存在前端会优雅降级到静音）
MIXER_LAYERS = [
    {"id": "rain", "label": "雨声", "icon": "🌧️", "color": "#60a5fa",
     "desc": "恋语市的春雨", "url": "/static/ambient/rain.mp3", "default_vol": 60},
    {"id": "cafe", "label": "咖啡馆", "icon": "☕", "color": "#a78bfa",
     "desc": "他常去的那家店", "url": "/static/ambient/cafe.mp3", "default_vol": 40},
    {"id": "piano", "label": "钢琴", "icon": "🎹", "color": "#f59e0b",
     "desc": "他偶尔弹的旋律", "url": "/static/ambient/piano.mp3", "default_vol": 50},
    {"id": "fire", "label": "壁炉", "icon": "🔥", "color": "#f87171",
     "desc": "冬夜的温暖", "url": "/static/ambient/fire.mp3", "default_vol": 30},
    {"id": "ocean", "label": "海浪", "icon": "🌊", "color": "#34d399",
     "desc": "你们去过的海岸", "url": "/static/ambient/ocean.mp3", "default_vol": 45},
    {"id": "night", "label": "虫鸣夜", "icon": "🌙", "color": "#818cf8",
     "desc": "恋语市郊的夏夜", "url": "/static/ambient/night.mp3", "default_vol": 35},
    {"id": "wind", "label": "风铃", "icon": "🎐", "color": "#f472b6",
     "desc": "他家阳台的风铃", "url": "/static/ambient/wind.mp3", "default_vol": 40},
    {"id": "heartbeat", "label": "心跳", "icon": "💗", "color": "#ec4899",
     "desc": "他的心率（与心动值同步）", "url": "/static/ambient/heartbeat.mp3", "default_vol": 25},
]


@router.get("/api/mixer/layers")
async def mixer_layers():
    affy = _agg_affinity_value()
    # 心跳层音量随心动值动态变化
    layers = []
    for L in MIXER_LAYERS:
        layer = dict(L)
        if L["id"] == "heartbeat":
            layer["default_vol"] = min(80, 20 + affy // 30)
        layers.append(layer)
    return {"layers": layers, "affinity": affy}


@router.post("/api/mixer/preset")
async def mixer_save_preset(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = str(body.get("name", "")).strip()[:30]
    vols = body.get("vols", {})
    if not name:
        return JSONResponse({"error": "给这个预设起个名字"}, status_code=400)
    if not isinstance(vols, dict):
        vols = {}
    preset = {
        "id": _nid(),
        "name": name,
        "ts": _ts(),
        "vols": {k: int(v) for k, v in vols.items() if isinstance(v, (int, float))},
        # 同时记录当时的氛围描述（可选）
        "scene": str(body.get("scene", "")).strip()[:80]
    }
    data = _load(MIX_FILE, {"presets": []})
    data.setdefault("presets", []).insert(0, preset)
    data["presets"] = data["presets"][:30]
    _save(MIX_FILE, data)
    return {"preset": preset}


@router.get("/api/mixer/presets")
async def mixer_presets():
    data = _load(MIX_FILE, {"presets": []})
    return {"presets": data.get("presets", [])}


@router.delete("/api/mixer/{pid}")
async def mixer_del_preset(pid: str):
    data = _load(MIX_FILE, {"presets": []})
    data["presets"] = [p for p in data.get("presets", []) if p.get("id") != pid]
    _save(MIX_FILE, data)
    return {"ok": True}


@router.post("/api/mixer/scene")
async def mixer_gen_scene(req: Request):
    """根据当前混音组合，让许墨描述一个对应的场景。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    vols = body.get("vols", {})
    if not isinstance(vols, dict):
        vols = {}
    active_layers = [L for L in MIXER_LAYERS if vols.get(L["id"], 0) > 0]
    if not active_layers:
        return JSONResponse({"error": "先调出一些声音"}, status_code=400)
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    layer_desc = ", ".join(f"{L['label']}({vols.get(L['id'], 0)})" for L in active_layers)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【心跳调音台·场景生成】她组合了一些环境音，你根据这些声音描述一个具体的场景。\n"
        f"声音层：{layer_desc}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        "输出 JSON：{\"scene\":\"80字内场景（含许墨在场，第二人称'你'）\","
        "\"mood\":\"15字内氛围\",\"line\":\"30字内许墨此刻对你说的话\"}"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请描述场景，只输出 JSON。"}
    ]
    rep = await _llm_json(messages, max_tokens=600)
    if not rep:
        return JSONResponse({"error": "场景未浮现，稍后再试"}, status_code=500)
    rep.setdefault("scene", "你和许墨共处一个安静的午后。")
    rep.setdefault("mood", "宁静")
    rep.setdefault("line", "你听，这就是我们。")
    return {"scene": rep}
