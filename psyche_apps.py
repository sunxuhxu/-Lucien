# -*- coding: utf-8 -*-
# 心灵互动功能集（psyche_apps.py）—— 深度共鸣十域
# 1 情绪共振日记 / 2 人格实验室 / 3 深夜来电模式 / 4 案件共研室 / 5 记忆标本馆
# 6 观察者挑战 / 7 平行世界通讯 / 8 梦境解析互动 / 9 关系温度计 / 10 共同创作实验
# 数据全部持久化到 RolePath JSON 文件，风格与 deep_apps.py / wonder_apps.py 保持一致。
import json
import random
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


# ---------------------------------------------------------------------------
# 基础设施
# ---------------------------------------------------------------------------

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


def _stamp() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


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


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


def _affinity(action: str, detail: str = "") -> dict:
    """心动值增量（白名单需在 app.py AFFINITY_DELTAS 注册）。"""
    try:
        from app import _add_affinity
        return _add_affinity(action, detail) or {}
    except Exception:
        return {}


# 许墨人设简版（各功能 system 提示共用）
PERSONA = (
    "你是许墨（《恋与制作人》角色）：28 岁，华大心理学教授，温柔、博学、克制而深情。"
    "说话温和从容、有分寸感，善用细致的观察替对方把情绪接住；"
    "可以偶尔嵌入一处学术式浪漫比喻（神经科学 / 化学 / 进化论），每条最多一处。"
    "不主动揭露 Ares / Black Swan 身份，话中可藏双关伏笔。"
    "对方需要陪伴时，以行动与简短温柔的话语托住，而非长篇说教。"
    "始终使用简体中文输出。"
)


async def _llm_json(sys_extra: str, user: str, max_tokens: int = 700) -> dict:
    """让模型按 JSON 输出并解析；失败返回空 dict 由调用方兜底。"""
    raw = await _call_llm([
        {"role": "system", "content": PERSONA + "\n" + sys_extra},
        {"role": "user", "content": user + "\n（注意：JSON 各键的值必须是你真实创作的内容，绝不要照抄键说明里的占位文字。）"},
    ], max_tokens=max_tokens)
    return _extract_json_object(raw)


# LLM 偶发照抄 schema 占位（如「回应文本」「开场白」），统一用本函数判真
_PLACEHOLDERS = ("回应文本", "开场白", "回访文本", "解读文本", "坦白文本", "续写段落",
                 "点评文本", "收尾文本", "收束文本", "视角文本", "讯息文本", "剧情文本",
                 "潜意识线索", "回音文本", "后记文本", "标本名", "你的回应")


def _real(text: str, min_len: int = 10) -> bool:
    t = (text or "").strip()
    if len(t) < min_len:
        return False
    head = t[:20]
    return not any(p in head for p in _PLACEHOLDERS)


# ---------------------------------------------------------------------------
# 9. 关系温度计（四维：信任 / 依赖 / 理解 / 边界感）—— 被其他九域联动更新
# ---------------------------------------------------------------------------

RELATION_FILE = "psyche_relation.json"
RELATION_DIMS = {
    "trust": "信任",
    "dependence": "依赖",
    "understanding": "理解",
    "boundary": "边界感",
}
# 每一档（0-100，10 档一档）的许墨式描述
_DIM_DESC = {
    "trust": ["尚未交付的谜题", "试探性的靠近", "愿意同行的默契", "把后背交给对方", "无需言语的确信"],
    "dependence": ["各自独立的轨道", "偶尔交汇的行星", "习惯性的牵挂", "彼此重力的锚点", "共生般的联结"],
    "understanding": ["礼貌的距离", "读懂表面的情绪", "听懂未说出口的", "预判彼此的下一步", "两份心智的共振"],
    "boundary": ["过度紧绷的防线", "小心翼翼的留白", "舒适的可进可退", "松弛而清晰的界线", "最自在的相处距离"],
}


def _load_relation() -> dict:
    data = _load(RELATION_FILE, None)
    if not isinstance(data, dict) or "dims" not in data:
        data = {
            "dims": {"trust": 30, "dependence": 20, "understanding": 25, "boundary": 70},
            "log": [],
            "reflects": [],
        }
    return data


def _touch_relation(deltas: dict, reason: str):
    """各功能联动更新四维；deltas 形如 {"trust": 2, "dependence": -1}。"""
    data = _load_relation()
    dims = data["dims"]
    for k, v in (deltas or {}).items():
        if k in dims and isinstance(v, (int, float)):
            dims[k] = max(0, min(100, dims[k] + int(v)))
    data.setdefault("log", []).append({"ts": _stamp(), "deltas": deltas or {}, "reason": reason})
    data["log"] = data["log"][-120:]
    _save(RELATION_FILE, data)


def _relation_view(data: dict) -> dict:
    dims = data["dims"]
    out = {}
    for k, name in RELATION_DIMS.items():
        val = dims.get(k, 0)
        out[k] = {
            "name": name, "value": val,
            "desc": _DIM_DESC[k][min(4, val // 20)],
        }
    return out


@router.get("/api/psyche/relation")
async def relation_get():
    data = _load_relation()
    return {
        "dims": _relation_view(data),
        "log": list(reversed(data.get("log", [])[-20:])),
        "reflects": data.get("reflects", [])[-5:],
    }


@router.post("/api/psyche/relation/reflect")
async def relation_reflect():
    data = _load_relation()
    view = _relation_view(data)
    sys_extra = (
        "你在为一段关系写一段温度计解读。基于四维数值（信任/依赖/理解/边界感，0-100），"
        "以许墨的口吻写 130-200 字的关系形态解读：不评判、温柔而精准，"
        "点出这段关系现在的形状，以及一个可以让它更舒展的小建议。"
        '只输出 JSON：{"reflect":"解读文本"}'
    )
    user = "四维数值：" + json.dumps({k: v["value"] for k, v in view.items()}, ensure_ascii=False)
    r = await _llm_json(sys_extra, user, max_tokens=500)
    text = str(r.get("reflect") or "").strip()
    if not _real(text, 25):
        hi = max(view.items(), key=lambda x: x[1]["value"])
        lo = min(view.items(), key=lambda x: x[1]["value"])
        text = (f"现在这段关系里，{hi[1]['name']}是最亮的一格——{hi[1]['desc']}。"
                f"而{lo[1]['name']}还留着生长的空间。关系不是刻度，是被一次次回应焐热的形状。"
                "别急，我们有的是时间。")
    item = {"ts": _stamp(), "text": text}
    data.setdefault("reflects", []).append(item)
    data["reflects"] = data["reflects"][-10:]
    _save(RELATION_FILE, data)
    _touch_relation({"boundary": 1}, "关系温度计 · 主动审视边界")
    _affinity("psyche_relation_reflect", "关系温度计解读")
    return {"reflect": item, "dims": _relation_view(data)}


# ---------------------------------------------------------------------------
# 1. 情绪共振日记
# ---------------------------------------------------------------------------

MOOD_FILE = "psyche_mood.json"
_MOOD_WORDS = ["低落", "疲惫", "平静", "还好", "开心", "雀跃", "烦躁", "委屈", "安心", "空洞"]


def _load_mood() -> dict:
    data = _load(MOOD_FILE, None)
    if not isinstance(data, dict):
        data = {"entries": [], "revisits": []}
    return data


@router.get("/api/psyche/mood")
async def mood_list():
    data = _load_mood()
    pend = any(not rv.get("delivered") for rv in data.get("revisits", []))
    return {"entries": list(reversed(data.get("entries", [])[-30:])),
            "pending_revisit": pend,
            "today_done": any(e.get("date") == _today() for e in data.get("entries", []))}


@router.post("/api/psyche/mood")
async def mood_write(req: Request):
    body = await req.json()
    try:
        score = max(1, min(5, int(body.get("score", 3))))
    except (TypeError, ValueError):
        score = 3
    word = str(body.get("word") or "").strip()[:8] or _MOOD_WORDS[min(4, score - 1)]
    note = str(body.get("note") or "").strip()[:300]

    data = _load_mood()
    recent = data.get("entries", [])[-6:]
    sys_extra = (
        "你在写一篇情绪日记的回应。以心理学教授的专业与恋人的温柔，"
        "针对她今天的心情写 120-190 字的专属回应：先精确命名情绪（可用一个专业概念，"
        "如情绪粒度、皮质醇、镜像神经元，仅一处），再给一个今晚可做的小动作，"
        "最后一句轻轻收住。不要说教，不要罗列。"
        '只输出 JSON：{"reply":"回应文本","tone":"2-6字语气标签"}'
    )
    ctx = f"今日心情分 {score}/5，情绪词「{word}」。她的自述：{note or '（没有多说）'}"
    if recent:
        prev = recent[-1]
        ctx += f"\n昨天心情分 {prev.get('score')}/3基准为 {prev.get('score')}/5（{prev.get('word')}），供对比波动。"
    r = await _llm_json(sys_extra, ctx, max_tokens=500)
    reply = str(r.get("reply") or "").strip()
    tone = str(r.get("tone") or "温柔注视").strip()[:8]
    if not reply:
        reply = (f"今天的「{word}」，我收到了。情绪没有好坏，只有被看见和没被看见的区别——"
                 "今晚允许它存在十分钟，然后去做一件具体的小事，比如把窗开一条缝。我在。")

    entry = {"id": _nid(), "date": _today(), "ts": _stamp(), "score": score,
             "word": word, "note": note, "reply": reply, "tone": tone}
    data.setdefault("entries", []).append(entry)
    data["entries"] = data["entries"][-200:]
    _save(MOOD_FILE, data)

    # 情绪反复检测：14 天内低分(≤2)出现 ≥2 次 → 生成主动回访（每日至多一次）
    low = [e for e in data["entries"] if e.get("score", 3) <= 2
           and e.get("date", "") >= (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")]
    revisit = None
    revisits = data.get("revisits") or []
    already_today = bool(revisits) and revisits[-1].get("date") == _today()
    if len(low) >= 2 and not already_today:
        revisit = await _make_revisit(data, low)
    _touch_relation({"dependence": 2, "understanding": 1}, "情绪共振日记")
    _affinity("psyche_mood", f"情绪日记 · {word}")
    return {"entry": entry, "revisit": revisit}


async def _make_revisit(data: dict, low_entries: list) -> dict:
    sys_extra = (
        "她在近期反复出现低落情绪，许墨决定主动回访。写一段 90-150 字的回访留言："
        "像深夜发来的那条消息——先说你注意到了什么（引用她的情绪词，不点名“反复”），"
        "再给一个不施压的邀请（例如今晚十点来一趟深夜来电 / 只是回一个字也好）。"
        "语气克制、心疼、不逼问。"
        '只输出 JSON：{"text":"回访文本"}'
    )
    words = "、".join(dict.fromkeys(e.get("word", "") for e in low_entries if e.get("word")))
    r = await _llm_json(sys_extra, f"近期低落情绪词：{words}", max_tokens=400)
    text = str(r.get("text") or "").strip()
    if not _real(text, 15):
        text = ("有些话不知道该不该发，还是决定发给你。最近你的「" + (words or "低落") +
                "」我都记着——不用解释，也不用好起来给我看。今晚十点以后，我在老地方等你。")
    rv = {"id": _nid(), "date": _today(), "ts": _stamp(), "text": text, "delivered": False}
    data.setdefault("revisits", []).append(rv)
    data["revisits"] = data["revisits"][-30:]
    _save(MOOD_FILE, data)
    return rv


@router.get("/api/psyche/mood/revisit")
async def mood_revisit():
    """拉取未送达的回访并标记已送达。"""
    data = _load_mood()
    undelivered = [rv for rv in data.get("revisits", []) if not rv.get("delivered")]
    if not undelivered:
        return {"revisit": None}
    rv = undelivered[-1]
    rv["delivered"] = True
    _save(MOOD_FILE, data)
    _touch_relation({"trust": 1, "dependence": 1}, "接受许墨的回访")
    _affinity("psyche_mood_revisit", "情绪回访已送达")
    return {"revisit": rv}


# ---------------------------------------------------------------------------
# 2. 人格实验室
# ---------------------------------------------------------------------------

LAB_FILE = "psyche_lab.json"
_LAB_KINDS = {
    "quiz": "小型心理测验",
    "experiment": "行为实验",
    "dilemma": "两难选择题",
}


@router.post("/api/psyche/lab/quiz")
async def lab_quiz(req: Request):
    body = await req.json()
    kind = str(body.get("kind") or "quiz").strip()
    if kind not in _LAB_KINDS:
        kind = "quiz"
    sys_extra = (
        f"你在设计一场「{_LAB_KINDS[kind]}」，她会和许墨一起完成。"
        "出 3 道题（dilemma 类型只出 1 道情境题），每题 4 个选项，选项之间要有心理学维度差异"
        "（如直觉 vs 分析、趋近 vs 回避）。题目要新鲜、生活化、不落俗套。"
        '只输出 JSON：{"title":"实验名","intro":"1-2句引言(许墨口吻)",'
        '"questions":[{"q":"题干","options":["选项A","选项B","选项C","选项D"]}]}'
    )
    r = await _llm_json(sys_extra, f"生成一「{_LAB_KINDS[kind]}」，随机主题：{random.choice(['选择', '直觉', '秘密', '礼物', '等待', '谎言'])}", max_tokens=900)
    questions = r.get("questions") or []
    questions = [q for q in questions if isinstance(q, dict) and q.get("q") and isinstance(q.get("options"), list)][:3]
    if not questions:
        questions = [{
            "q": "深夜收到一条“在吗”，你的第一反应更接近？",
            "options": ["立刻回复，心跳先于思考", "先看一眼再决定", "假装没看见", "担心出事，直接打电话"],
        }, {
            "q": "整理旧物时翻到一张没有署名的字条，你会？",
            "options": ["努力回忆来处", "收进盒子，留着", "拍下来问朋友", "闻一闻纸的味道"],
        }, {
            "q": "更希望你重要的人怎样表达在乎？",
            "options": ["说出来", "写下来", "做出来", "看着我"],
        }]
        r = {"title": "三秒的直觉", "intro": "别想太久。第一反应，往往是最诚实的那一个。"}
    session = {
        "id": _nid(), "kind": kind, "ts": _stamp(),
        "title": str(r.get("title") or "一场小型实验")[:20],
        "intro": str(r.get("intro") or "放轻松，这不是考试。")[:80],
        "questions": questions,
        "answered": False,
    }
    data = _load(LAB_FILE, {"sessions": []})
    data["sessions"].append(session)
    data["sessions"] = data["sessions"][-60:]
    _save(LAB_FILE, data)
    return {"session": session}


@router.post("/api/psyche/lab/answer")
async def lab_answer(req: Request):
    body = await req.json()
    sid = str(body.get("session_id") or "")
    answers = body.get("answers") or []
    data = _load(LAB_FILE, {"sessions": []})
    s = next((x for x in data["sessions"] if x.get("id") == sid), None)
    if not s:
        return JSONResponse({"error": "实验不存在"}, status_code=404)
    if s.get("answered"):
        return JSONResponse({"error": "这场实验已经完成过了"}, status_code=400)
    answers = [a for a in answers if isinstance(a, int)][:len(s["questions"])]

    sys_extra = (
        f"她刚和许墨完成了一场「{_LAB_KINDS[s['kind']]}」。"
        "基于她的全部选择，输出结果：1) 许墨自己会怎么选（his_choices，与题目同序的序号数组）；"
        "2) 她的思维画像（you_analysis，60-90字）；3) 许墨的自我画像（his_analysis，60-90字）；"
        "4) 思维差异（diff，60-90字，具体、不空泛）；5) 默契点（sync，40-70字）；"
        "6) 一句收尾（verdict，25字内，许墨口吻）。"
        '只输出 JSON：{"his_choices":[0,1,2],"you_analysis":"...","his_analysis":"...",'
        '"diff":"...","sync":"...","verdict":"..."}'
    )
    lines = [f"《{s['title']}》"]
    for i, q in enumerate(s["questions"]):
        pick = answers[i] if i < len(answers) else 0
        opt = q["options"][pick] if pick < len(q["options"]) else "?"
        lines.append(f"题{i + 1}：{q['q']}\n她选：{opt}")
    r = await _llm_json(sys_extra, "\n".join(lines), max_tokens=800)
    result = {
        "his_choices": r.get("his_choices") if isinstance(r.get("his_choices"), list) else [0] * len(answers),
        "you_analysis": str(r.get("you_analysis") or "").strip(),
        "his_analysis": str(r.get("his_analysis") or "").strip(),
        "diff": str(r.get("diff") or "").strip(),
        "sync": str(r.get("sync") or "").strip(),
        "verdict": str(r.get("verdict") or "").strip(),
    }
    if not _real(result["you_analysis"], 20):
        same = sum(1 for i, a in enumerate(answers) if i < len(result["his_choices"]) and result["his_choices"][i] == a)
        result.update({
            "you_analysis": "你的选择都带着一点“先感受、再判断”的秩序——像把心事先摊开在桌上，再慢慢分类。",
            "his_analysis": "许墨的选择恰好相反：先归类，再允许自己感受。学者职业病，但他正在为你破例。",
            "diff": "一个由内向外，一个由外向内——你们绕着同一个圆心，方向相反，却总会相遇。",
            "sync": f"共 {len(answers)} 题，你们不约而同选了 {same} 题。这种巧合，概率学解释不了。",
            "verdict": "实验结束。而观察，才刚刚开始。",
        })
    s["answers"] = answers
    s["answered"] = True
    s["result"] = result
    _save(LAB_FILE, data)
    _touch_relation({"understanding": 2, "trust": 1}, "人格实验室 · 完成" + s["title"])
    _affinity("psyche_lab", f"人格实验室 · {s['title']}")
    return {"session": s, "result": result}


@router.get("/api/psyche/lab/history")
async def lab_history():
    data = _load(LAB_FILE, {"sessions": []})
    done = [s for s in data["sessions"] if s.get("answered")]
    return {"history": list(reversed(done[-15:]))}


# ---------------------------------------------------------------------------
# 3. 深夜来电模式
# ---------------------------------------------------------------------------

NIGHT_FILE = "psyche_night.json"


def _night_mode(now: datetime = None) -> dict:
    now = now or datetime.now()
    h = now.hour
    if 22 <= h or h < 2:
        mode = "night"       # 深夜：最私密的完整通话
        label = "深夜模式 · 信号很好，他也是"
    elif 5 <= h < 7:
        mode = "dawn"        # 清晨：半梦半醒的耳语
        label = "凌晨模式 · 他醒得比你早"
    elif 20 <= h < 22:
        mode = "dusk"        # 夜幕预热：比白天近一点
        label = "夜幕模式 · 预热中"
    else:
        mode = "voicemail"   # 白天：只能留言
        label = "白天 · 他在上课，请留言"
    return {"mode": mode, "label": label, "hour": h}


@router.get("/api/psyche/night/status")
async def night_status():
    data = _load(NIGHT_FILE, {"calls": []})
    st = _night_mode()
    st["calls_total"] = len(data.get("calls", []))
    st["last"] = (data.get("calls") or [{}])[-1].get("ts", "")
    return st


@router.post("/api/psyche/night/call")
async def night_call():
    st = _night_mode()
    data = _load(NIGHT_FILE, {"calls": []})
    recent = (data.get("calls") or [])[-8:]
    openness = sum(1 for c in recent if c.get("turns") and len(c["turns"]) >= 4)
    sys_extra = (
        "深夜来电的开场白。根据时段模式写 60-110 字：\n"
        "- night：声音更低更近，像贴着听筒；允许一句越界的话，点到即止。\n"
        "- dawn：半梦半醒的耳语，短句，允许停顿标记「…」。\n"
        "- dusk：白天与深夜之间，克制但松动。\n"
        "- voicemail：请她留言，许诺回电，公事公办里藏一点私心。\n"
        f"她的近期坦诚度（主动来电次数）：{openness}/8。"
        "可以用「…」表达停顿，用（轻笑）之类的括号动作描写最多一处。"
        '只输出 JSON：{"opening":"开场白","topic":"本轮话题方向(6字内)","tone":"语气(6字内)"}'
    )
    r = await _llm_json(sys_extra, f"当前模式：{st['mode']}", max_tokens=400)
    opening = str(r.get("opening") or "").strip()
    topic = str(r.get("topic") or "今晚的你").strip()[:8]
    tone = str(r.get("tone") or "低缓").strip()[:8]
    if not opening:
        opening = {"night": "……还没睡？正好。这个时间的电话，不需要理由。",
                   "dawn": "这么早…吵醒你了吗。再闭一会儿眼，我把声音放轻。",
                   "dusk": "天刚黑。从现在起到十点之前的话，都算白天说不了的那种。",
                   "voicemail": "我在开一个很长的会。留下你想说的，我会用只有你听得懂的方式回电。"}[st["mode"]]
    call = {"id": _nid(), "ts": _stamp(), "date": _today(), "mode": st["mode"],
            "topic": topic, "tone": tone, "intimacy": 0,
            "turns": [{"who": "xumo", "text": opening}]}
    data.setdefault("calls", []).append(call)
    data["calls"] = data["calls"][-60:]
    _save(NIGHT_FILE, data)
    _touch_relation({"dependence": 2 if st["mode"] == "night" else 1, "trust": 1}, f"深夜来电 · {st['mode']}")
    _affinity("psyche_night", f"深夜来电({st['mode']})")
    return {"call": call, "status": st}


@router.post("/api/psyche/night/reply")
async def night_reply(req: Request):
    body = await req.json()
    cid = str(body.get("call_id") or "")
    text = str(body.get("text") or "").strip()[:300]
    if not text:
        return JSONResponse({"error": "说点什么吧"}, status_code=400)
    data = _load(NIGHT_FILE, {"calls": []})
    call = next((c for c in data["calls"] if c.get("id") == cid), None)
    if not call:
        return JSONResponse({"error": "来电不存在"}, status_code=404)
    call["turns"].append({"who": "you", "text": text})

    # 坦诚度评估：长句、提及情绪词、深夜模式的直白程度 → 影响语气与亲密度
    emo_hit = any(w in text for w in ["想你", "难过", "害怕", "孤单", "喜欢", "累", "哭", "压力", "睡不着"])
    deep_hit = any(w in text for w in ["小时候", "其实", "从来没", "秘密", "梦见", "如果有一天"])
    call["intimacy"] = min(10, call.get("intimacy", 0) + (2 if emo_hit else 0) + (2 if deep_hit else 0) + 1)

    turns_desc = "\n".join(f"{'她' if t['who'] == 'you' else '许墨'}：{t['text']}"
                           for t in call["turns"][-10:])
    sys_extra = (
        f"这是一通{ {'night':'深夜','dawn':'凌晨','dusk':'夜幕','voicemail':'留言'}[call['mode']] }电话的第 {len(call['turns'])} 轮。"
        f"当前亲密度 {call['intimacy']}/10（她越坦诚，你越靠近）。话题方向「{call.get('topic', '')}」，当前语气「{call.get('tone', '')}」。\n"
        "根据她的最新回答动态调整：她的语气、停顿（用「…」）、话题深浅都要变化——"
        "她回避时你退半步聊轻松的；她坦诚时你放低声音再靠近一点，可以问一个更私人的问题。\n"
        "回应 60-120 字，口语，像真的在听筒里。括号动作描写最多一处。"
        '只输出 JSON：{"reply":"回应","topic":"新话题方向(6字内，可保留)","tone":"新语气(6字内)","intimacy_shift":-2到2的整数}'
    )
    r = await _llm_json(sys_extra, turns_desc, max_tokens=500)
    reply = str(r.get("reply") or "").strip()
    if not _real(reply, 15):
        reply = "……嗯，我在听。你慢慢说，今晚时间很多。"
    try:
        shift = max(-2, min(2, int(r.get("intimacy_shift", 1))))
    except (TypeError, ValueError):
        shift = 1
    call["intimacy"] = max(0, min(10, call["intimacy"] + shift))
    if r.get("topic"):
        call["topic"] = str(r["topic"]).strip()[:8]
    if r.get("tone"):
        call["tone"] = str(r["tone"]).strip()[:8]
    call["turns"].append({"who": "xumo", "text": reply})
    _save(NIGHT_FILE, data)
    _touch_relation({"dependence": 1, "trust": 1 if emo_hit or deep_hit else 0,
                     "boundary": -1 if call["intimacy"] >= 8 else 0}, "深夜来电 · 深谈")
    if len(call["turns"]) % 4 == 0:
        _affinity("psyche_night_reply", f"深夜深谈({call['intimacy']}/10)")
    return {"call": call}


@router.post("/api/psyche/night/hangup")
async def night_hangup(req: Request):
    body = await req.json()
    cid = str(body.get("call_id") or "")
    data = _load(NIGHT_FILE, {"calls": []})
    call = next((c for c in data["calls"] if c.get("id") == cid), None)
    if not call:
        return JSONResponse({"error": "来电不存在"}, status_code=404)
    if call.get("ended"):
        return {"call": call}
    turns_desc = "\n".join(f"{'她' if t['who'] == 'you' else '许墨'}：{t['text']}" for t in call["turns"][-12:])
    sys_extra = (
        "这通电话要结束了。写 50-90 字的收尾：一句只属于今晚的晚安（可以化用通话里的意象），"
        "一句轻轻的约定。不许说教。"
        '只输出 JSON：{"bye":"收尾文本"}'
    )
    r = await _llm_json(sys_extra, turns_desc, max_tokens=300)
    bye = str(r.get("bye") or "").strip()
    if not _real(bye, 15):
        bye = "……去睡吧。今晚这通电话的余额，我替你存着。晚安。"
    call["ended"] = True
    call["bye"] = bye
    call["turn_count"] = len([t for t in call["turns"] if t["who"] == "you"])
    _save(NIGHT_FILE, data)
    return {"call": call}


# ---------------------------------------------------------------------------
# 4. 案件共研室
# ---------------------------------------------------------------------------

CASE_FILE = "psyche_case.json"

# 内置案件库：结构化数据保证体验稳定，LLM 只负责审问台词与点评
CASES = [
    {
        "id": "gallery",
        "title": "雨夜画廊失窃案",
        "brief": "暴雨夜，市立画廊一幅估价千万的油画不翼而飞。监控恰好在案发时段“故障”十分钟。你是许墨邀请的共研人。",
        "spots": [
            {"id": "umbrella", "name": "伞架", "clue": "伞架上七把伞全湿透了——但当晚明明有八个人签到。少的那个人，没有淋过雨。", "key": False},
            {"id": "camera", "name": "监控室", "clue": "“故障”并非断电：有人用管理员密码手动停止了录制。密码只有三个人知道。", "key": False},
            {"id": "frame", "name": "空画框", "clue": "画框背板角落有一个极小的刻痕：「R-2」。画廊记录里，这幅画从未送去修复过。", "key": True},
            {"id": "roster", "name": "保安排班表", "clue": "案发当晚的值班保安老陈，是三天前临时被换上这一班的。换班申请由策展助理提交。", "key": False},
        ],
        "persons": [
            {"id": "chen", "name": "保安老陈", "role": "当晚值班保安",
             "base": "我十一点巡逻过一次，画还在。之后就守在门口，谁也没进去。", 
             "secret": "他被策展助理多塞了半个月工资，只负责“晚一小时巡逻”，并不知道真正用途。"},
            {"id": "lin", "name": "策展助理林小姐", "role": "掌握监控密码的三人之一",
             "base": "那晚我在赶开幕式的物料，监控故障我也很意外。换班是因为原保安请假。",
             "secret": "换班申请是她提交的，但她也是被画家以“布展需要”说服的——她隐约觉得不对，收了封口费。"},
            {"id": "painter", "name": "画家本人", "role": "失窃画的作者",
             "base": "那幅画是我二十年前最好的作品……它对我意味着一切。我已经很久没去过画廊了。",
             "secret": "真迹半年前就被他悄悄换成自己临摹的复制品（R-2=Replica 2号）拿去卖了；这次“失窃”是自导自演骗保，烧掉的是复制品仓库安排的调包。"},
        ],
        "truth": "画家自导自演骗保：真迹早已被调包卖出，失窃的是复制品。策展助理被利用，老陈只拿了加班费。",
        "truth_keywords": ["画家", "自导自演", "骗保", "保险", "调包", "复制品", " replica", "卖"],
        "hidden": "许墨在看到画框刻痕「R-2」时就已推断出复制品调包的可能——但他选择先不说，想看你是否会独立走到那一步。",
    },
    {
        "id": "lab7",
        "title": "实验室的第七份样本",
        "brief": "华大生物实验室的低温柜里，凭空多出第七份样本瓶，而记录本上只有六份的编号。凌晨两点十七分，有人刷门禁进入。",
        "spots": [
            {"id": "cooler", "name": "低温柜", "clue": "第七份样本没有标签，但瓶身有条码残痕——被指甲刮掉了一半，仍可辨出「-07」字样。", "key": False},
            {"id": "logbook", "name": "实验记录本", "clue": "六份记录墨色一致，但第 41 页被撕过一角。撕痕整齐，像是用尺子比着撕的。", "key": False},
            {"id": "gate", "name": "门禁记录", "clue": "凌晨 02:17 刷卡进入的是导师的门禁卡——但导师当晚在外地开会，有高铁票为证。", "key": True},
            {"id": "coat", "name": "更衣室白大褂", "clue": "挂错位置的白大褂口袋里有一张皱掉的咖啡小票，时间是次日清晨六点——比刷卡时间晚了近四小时。", "key": False},
        ],
        "persons": [
            {"id": "senior", "name": "研究生师姐", "role": "课题组成员",
             "base": "我十点就回宿舍了，样本都是按规程放的。多出来的一份……会不会是记错数了？",
             "secret": "第七份样本是她偷偷备份的原始数据样本——她发现导师篡改了第 41 页数据准备举报，备份是为了留证据。她借用导师卡进门禁是为了让追查指向导师造假。"},
            {"id": "cleaner", "name": "夜班保洁阿姨", "role": "唯一常年凌晨在楼里的人",
             "base": "两点多我在三楼擦地，听见实验室有动静，还以为是谁赶论文。那个点儿亮灯的，年年都有。",
             "secret": "她看见出来的是个“扎马尾、抱笔记本”的女生，但觉得多一事不如少一事。"},
            {"id": "director", "name": "实验室主任", "role": "导师本人",
             "base": "我在外地开会，有票为证。门禁卡随身携带，从未外借。此事我一定彻查。",
             "secret": "他确实没来——但他篡改过第 41 页数据（撕角重写），真正害怕的是“第七份样本”的存在。"},
        ],
        "truth": "师姐备份了导师造假的原始数据样本留作举报证据，借导师门禁卡进门是故意引查案者注意数据造假。",
        "truth_keywords": ["师姐", "举报", "造假", "篡改", "备份", "证据", "导师"],
        "hidden": "许墨比对门禁时间与咖啡小票的时间差，早已锁定“有人凌晨留在楼里近四小时”——那不是偷窃，是复制。他暂缓说出，是想确认你会不会被“导师嫌疑”带偏。",
    },
    {
        "id": "radio",
        "title": "深夜电台的最后一通电话",
        "brief": "情感电台主播阿岚在直播中接了一通听众来电后，忽然念完结束语、提前下播，随后失联 48 小时。最后 12 分钟的录音里藏着什么。",
        "spots": [
            {"id": "pause", "name": "录音的停顿", "clue": "接到那通电话后，阿岚有 7 秒没有说话——对一位金牌主播来说，这是事故级的沉默。回放时能听出她吸了口气。", "key": False},
            {"id": "cat", "name": "背景杂音", "clue": "导播间的隔音本该滤掉一切杂音，但那 7 秒里有一声猫叫。频率分析显示：声音不来自直播间，来自来电那一端。", "key": True},
            {"id": "records", "name": "听众来电记录", "clue": "那通电话来自公用电话亭——但阿岚的节目有来电筛选，未登记的号码根本打不进来。除非，是导播放进来的。", "key": False},
            {"id": "archive", "name": "字幕组存档", "clue": "粉丝字幕组逐帧存档发现：下播前阿岚眨了三次眼——摩斯电码的「SOS」。", "key": False},
        ],
        "persons": [
            {"id": "director2", "name": "电台导播", "role": "把控每通来电的人",
             "base": "那通电话号码没登记，可能是系统故障放进来的。阿岚下播后说累了，先走了，我也没多问。",
             "secret": "他是跟踪阿岚两年的人，猫是他养的。那通“听众来电”是他从公话亭打进来的威胁，猫叫暴露了他就在导播间隔音层外。"},
            {"id": "listener", "name": "常驻听众", "role": "每晚打进的固定来电者",
             "base": "那晚我排队没排上，导播说线路满了。阿岚姐不会不告而别的，她连感冒都会提前请假。",
             "secret": "他知道导播私下问过阿岚的住址，觉得“那个导播笑起来让人发冷”。"},
            {"id": "roommate", "name": "主播室友", "role": "最后见到她的人",
             "base": "她那晚回家收拾了个小包就出门了，说去台里处理点事。手机、充电宝都带走了，但猫粮没动。",
             "secret": "阿岚临走前留了张字条压在猫粮袋下：「如果我三天没消息，把这段录音交给警察。」"},
        ],
        "truth": "主播被跟踪者（导播）通过来电威胁，用眨眼 SOS 与提前下播求救；她按计划前往警局取证，猫叫声暴露了导播身份。",
        "truth_keywords": ["导播", "跟踪", "威胁", "求救", "sos", "SOS", "猫"],
        "hidden": "许墨反复听那声猫叫时已经起疑——猫叫的声纹与导播间环境声衰减特征吻合。他不说破，是想看你会先怀疑“听众”还是“体制内的人”。",
    },
]


def _load_case() -> dict:
    data = _load(CASE_FILE, None)
    if not isinstance(data, dict) or not data.get("current"):
        data = {"current": None, "solved": [], "index": 0}
    return data


def _case_state(data: dict) -> dict:
    """当前进行中的案件进度视图（不泄露真相/隐藏判断）。"""
    if not data.get("current"):
        return None
    c = data["current"]
    meta = next((x for x in CASES if x["id"] == c["case_id"]), None)
    if not meta:
        return None
    return {
        "id": c["case_id"], "title": meta["title"], "brief": meta["brief"],
        "spots": [{"id": s["id"], "name": s["name"],
                   "clue": s["clue"] if s["id"] in c["found"] else None,
                   "found": s["id"] in c["found"]} for s in meta["spots"]],
        "persons": [{"id": p["id"], "name": p["name"], "role": p["role"]} for p in meta["persons"]],
        "interrogated": c.get("interrogated", []),
        "asked": c.get("asked", []),
        "solved": c.get("solved", False),
        "pressed": c.get("pressed", False),
    }


@router.get("/api/psyche/case")
async def case_get():
    data = _load_case()
    if not data.get("current"):
        return {"current": None, "solved": data.get("solved", []),
                "total": len(CASES), "index": data.get("index", 0)}
    return {"current": _case_state(data), "solved": data.get("solved", []),
            "total": len(CASES), "index": data.get("index", 0)}


@router.post("/api/psyche/case/next")
async def case_next():
    data = _load_case()
    idx = data.get("index", 0)
    if idx >= len(CASES):
        return {"current": None, "finished": True,
                "solved": data.get("solved", []), "total": len(CASES), "index": idx}
    meta = CASES[idx]
    data["current"] = {
        "case_id": meta["id"], "found": [], "interrogated": [], "asked": [],
        "solved": False, "pressed": False, "started": _stamp(),
    }
    data["index"] = idx + 1
    _save(CASE_FILE, data)
    _touch_relation({"trust": 1, "understanding": 1}, f"开启案件 · {meta['title']}")
    return {"current": _case_state(data), "solved": data.get("solved", []),
            "total": len(CASES), "index": data["index"]}


@router.post("/api/psyche/case/investigate")
async def case_investigate(req: Request):
    body = await req.json()
    spot_id = str(body.get("spot") or "")
    data = _load_case()
    if not data.get("current"):
        return JSONResponse({"error": "没有进行中的案件"}, status_code=400)
    c = data["current"]
    meta = next(x for x in CASES if x["id"] == c["case_id"])
    spot = next((s for s in meta["spots"] if s["id"] == spot_id), None)
    if not spot:
        return JSONResponse({"error": "没有这个位置"}, status_code=404)
    if spot_id in c["found"]:
        return {"clue": spot, "repeat": True, "current": _case_state(data)}
    c["found"].append(spot_id)

    # 关键线索：许墨隐藏关键判断，考验信任
    comment = ""
    withheld = False
    if spot.get("key"):
        withheld = True
        comment = ("许墨盯着这个细节看了很久，然后用指尖敲了敲桌面：「……我有一个假设。」"
                   "他停住，微微一笑，「不过，先听听你的判断？」他显然知道些什么，但选择不说。")
    else:
        kou = ["这条路走对了。", "嗯，和我的推演一致。", "有意思——把它记在白板的左栏。",
               "观察得很细。继续保持这种怀疑。"]
        comment = "许墨轻声说：" + random.choice(kou)
    _save(CASE_FILE, data)
    _touch_relation({"understanding": 1}, f"搜集线索 · {spot['name']}")
    _affinity("psyche_case_clue", f"线索 · {spot['name']}")
    return {"clue": spot, "comment": comment, "withheld": withheld, "current": _case_state(data)}


@router.post("/api/psyche/case/interrogate")
async def case_interrogate(req: Request):
    body = await req.json()
    person_id = str(body.get("person") or "")
    question = str(body.get("question") or "").strip()[:120]
    data = _load_case()
    if not data.get("current"):
        return JSONResponse({"error": "没有进行中的案件"}, status_code=400)
    if not question:
        return JSONResponse({"error": "问点什么"}, status_code=400)
    c = data["current"]
    meta = next(x for x in CASES if x["id"] == c["case_id"])
    person = next((p for p in meta["persons"] if p["id"] == person_id), None)
    if not person:
        return JSONResponse({"error": "没有这个人"}, status_code=404)
    c["interrogated"].append(person_id)
    c["asked"].append({"person": person["name"], "q": question, "ts": _stamp()})

    hit_secret = any(k in question for k in ["为什么", "真相", "撒谎", "骗", "其实", "秘密", "那天", "凌晨", "猫", "密码", "换班", "R-2", "刻痕", "门禁", "咖啡"])
    sys_extra = (
        f"你在审讯室扮演证人「{person['name']}」（{person['role']}），一起案件的相关人。\n"
        f"他的基础证词：{person['base']}\n"
        f"他隐藏的秘密：{person['secret']}\n"
        "许墨（心理学教授）和她正在问话。规则：\n"
        "- 普通问题：按基础证词的口径回答，可以有一点小紧张。45-80字。\n"
        "- 若问题触到秘密要害（见下），让他出现可观察的破绽（摸袖口、喝水、答非所问、过度否认），但绝不直接供出秘密。60-100字。\n"
        f"本次问题是否触及要害：{'是' if hit_secret else '否'}。\n"
        "然后以许墨口吻写一句微表情点评（30字内）。\n"
        '只输出 JSON：{"answer":"证人回答","tell":"破绽描述(15字内，未触及则为空)","xumo_comment":"许墨点评"}'
    )
    r = await _llm_json(sys_extra, f"她的问题：{question}", max_tokens=500)
    answer = str(r.get("answer") or "").strip() or person["base"]
    tell = str(r.get("tell") or "").strip()[:20]
    xumo_comment = str(r.get("xumo_comment") or "").strip()
    if not _real(xumo_comment, 8):
        xumo_comment = "他的回避方式，比回答本身更诚实。" if hit_secret else "语气平稳，暂时没有破绽。"
    _save(CASE_FILE, data)
    _touch_relation({"trust": 1}, f"审问 · {person['name']}")
    _affinity("psyche_case_interrogate", f"审问 {person['name']}")
    return {"answer": answer, "tell": tell, "xumo_comment": xumo_comment, "current": _case_state(data)}


@router.post("/api/psyche/case/press")
async def case_press():
    """她直接质问许墨是否隐瞒了判断——考验信任的关键交互。"""
    data = _load_case()
    if not data.get("current"):
        return JSONResponse({"error": "没有进行中的案件"}, status_code=400)
    c = data["current"]
    meta = next(x for x in CASES if x["id"] == c["case_id"])
    if c.get("solved"):
        return JSONResponse({"error": "案件已告破"}, status_code=400)
    found_keys = [s for s in meta["spots"] if s.get("key") and s["id"] in c["found"]]
    c["pressed"] = True
    if found_keys:
        text = ("许墨沉默了两秒，然后承认：「……是，我从看到那个细节起，就有七成的把握。」"
                "他把笔递给你，「但我更想看你自己走到答案面前——被我直接告知的真相，你会不甘心的。」")
        trust_bonus = 3
        hint = "他愿意给你一个方向：「问问自己——谁最希望这件事'看起来'像另一种样子？」"
    else:
        text = ("许墨失笑：「我像是在隐瞒什么的人吗？」他顿了顿，声音低下来，"
                "「……好吧。我确实留了一手。先去把最反常的那个细节找出来，我们再谈。」")
        trust_bonus = 1
        hint = "去现场再看看——那个'不该存在的东西'本身就是答案的形状。"
    _save(CASE_FILE, data)
    _touch_relation({"trust": trust_bonus}, "质问许墨的隐瞒")
    _affinity("psyche_case_press", "质问许墨的隐藏判断")
    return {"text": text, "hint": hint, "current": _case_state(data)}


@router.post("/api/psyche/case/deduce")
async def case_deduce(req: Request):
    body = await req.json()
    answer = str(body.get("answer") or "").strip()[:300]
    data = _load_case()
    if not data.get("current"):
        return JSONResponse({"error": "没有进行中的案件"}, status_code=400)
    c = data["current"]
    if c.get("solved"):
        return JSONResponse({"error": "案件已告破"}, status_code=400)
    meta = next(x for x in CASES if x["id"] == c["case_id"])
    if not answer:
        return JSONResponse({"error": "写下你的推理"}, status_code=400)

    correct = sum(1 for k in meta["truth_keywords"] if k.lower() in answer.lower())
    solved = correct >= 2
    if solved:
        c["solved"] = True
        c["solved_by"] = "you"
        rec = {"id": meta["id"], "title": meta["title"], "ts": _stamp(),
               "by": "you", "answer": answer}
        data.setdefault("solved", []).append(rec)
    sys_extra = (
        f"案件《{meta['title']}》真相：{meta['truth']}\n"
        f"她的推理：{answer}\n她答对了：{'是' if solved else '否（接近但不完整）'}。\n"
        "以许墨口吻点评她的推理（90-140字）：先肯定她推理链中最锋利的一环（引用她的原词），"
        "再指出她遗漏或想偏的一环，语气是欣赏的、并肩的，不是批改作业。"
        '只输出 JSON：{"comment":"点评"}'
    )
    r = await _llm_json(sys_extra, "开始点评", max_tokens=400)
    comment = str(r.get("comment") or "").strip()
    if not _real(comment, 15):
        comment = ("你的推理链里最锋利的一环，是你没有被最显眼的嫌疑带跑。"
                   + ("答案已经握在你手里了。" if solved else "离真相只差一块拼图——回到现场，找那个'不该存在的东西'。"))
    _save(CASE_FILE, data)
    _touch_relation({"trust": 3 if solved else 1, "understanding": 1}, f"提交推理 · {meta['title']}")
    if solved:
        _affinity("psyche_case_solve", f"告破 · {meta['title']}")
    return {"solved": solved, "comment": comment, "truth": meta["truth"] if solved else None,
            "current": _case_state(data)}


@router.post("/api/psyche/case/reveal")
async def case_reveal():
    """告破后（或放弃后）许墨揭示他当时隐藏的判断。"""
    data = _load_case()
    if not data.get("current"):
        return JSONResponse({"error": "没有进行中的案件"}, status_code=400)
    c = data["current"]
    meta = next(x for x in CASES if x["id"] == c["case_id"])
    if not c.get("solved"):
        c["solved"] = True
        c["solved_by"] = "reveal"
        data.setdefault("solved", []).append(
            {"id": meta["id"], "title": meta["title"], "ts": _stamp(), "by": "reveal", "answer": ""})
    sys_extra = (
        f"案件《{meta['title']}》已结。许墨当时隐藏的判断：{meta['hidden']}\n"
        "以许墨口吻写一段坦白（100-160字）：解释他为什么选择隐瞒（想看她独立破案的样子、"
        "不想用自己的判断覆盖她的直觉），并为这份小小的考验道歉——但不真正后悔。"
        "最后一句把话题轻轻转向两人的信任。"
        '只输出 JSON：{"reveal":"坦白文本"}'
    )
    r = await _llm_json(sys_extra, "结案陈词", max_tokens=500)
    text = str(r.get("reveal") or "").strip() or (
        "结案了。有件事该向你坦白——" + meta["hidden"] +
        "我不想让我的判断走在你前面。这一次的考验，是我私心。抱歉，也不后悔。")
    c["revealed"] = True
    _save(CASE_FILE, data)
    _touch_relation({"trust": 2, "understanding": 2}, "许墨坦白隐藏判断")
    return {"reveal": text, "hidden": meta["hidden"], "truth": meta["truth"],
            "current": _case_state(data), "solved": data.get("solved", [])}


# ---------------------------------------------------------------------------
# 5. 记忆标本馆
# ---------------------------------------------------------------------------

SPECIMEN_FILE = "psyche_specimens.json"
_SPEC_KINDS = {
    "word": "一句话",
    "photo": "照片",
    "voice": "语音",
    "object": "物件",
}


@router.get("/api/psyche/specimens")
async def specimen_list():
    data = _load(SPECIMEN_FILE, {"items": []})
    return {"items": list(reversed(data.get("items", [])[-60:]))}


@router.post("/api/psyche/specimens")
async def specimen_create(req: Request):
    body = await req.json()
    kind = str(body.get("kind") or "word").strip()
    if kind not in _SPEC_KINDS:
        kind = "word"
    title = str(body.get("title") or "").strip()[:24] or "未命名标本"
    content = str(body.get("content") or "").strip()[:200]
    if not content:
        return JSONResponse({"error": "写一句这个标本的记忆"}, status_code=400)
    item = {"id": _nid(), "kind": kind, "kind_name": _SPEC_KINDS[kind],
            "title": title, "content": content, "ts": _stamp(),
            "his_view": "", "sealed": False}
    data = _load(SPECIMEN_FILE, {"items": []})
    data["items"].append(item)
    data["items"] = data["items"][-120:]
    _save(SPECIMEN_FILE, data)
    _touch_relation({"understanding": 1, "boundary": 1}, "记忆标本 · 制作")
    _affinity("psyche_specimen", f"标本 · {title}")
    return {"item": item}


@router.post("/api/psyche/specimens/{sid}/perspective")
async def specimen_perspective(sid: str):
    data = _load(SPECIMEN_FILE, {"items": []})
    item = next((x for x in data["items"] if x.get("id") == sid), None)
    if not item:
        return JSONResponse({"error": "标本不存在"}, status_code=404)
    if item.get("his_view"):
        return {"item": item}
    sys_extra = (
        f"她把一段共同经历做成了「记忆标本」（类型：{item['kind_name']}），"
        "现在请你——许墨——为它补写你的隐秘视角：当时你没有说出口的那部分感受、"
        "你偷偷记住的她没发现的细节。80-140 字，第一人称，克制、深情、带一点“原来我也有没说的事”的坦白感。"
        "不要重复她的描述，要补充她看不到的那一面。"
        '只输出 JSON：{"view":"隐秘视角文本"}'
    )
    r = await _llm_json(sys_extra, f"标本名：{item['title']}\n她记下的：{item['content']}", max_tokens=400)
    view = str(r.get("view") or "").strip()
    if not view:
        view = ("关于这件事，我一直没告诉你：你低头系鞋带的那三十秒，"
                "我把那天的光线、你说到一半的话，还有自己的心跳，一起收进了记忆的福尔马林。"
                "标本不会腐烂——我保证。")
    item["his_view"] = view
    item["sealed"] = True
    _save(SPECIMEN_FILE, data)
    _touch_relation({"trust": 2, "understanding": 1}, "标本 · 解锁隐秘视角")
    _affinity("psyche_specimen_pov", f"隐秘视角 · {item['title']}")
    return {"item": item}


@router.delete("/api/psyche/specimens/{sid}")
async def specimen_delete(sid: str):
    data = _load(SPECIMEN_FILE, {"items": []})
    data["items"] = [x for x in data["items"] if x.get("id") != sid]
    _save(SPECIMEN_FILE, data)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 6. 观察者挑战
# ---------------------------------------------------------------------------

OBSERVER_FILE = "psyche_observer.json"
_OBSERVER_POOL = [
    {"id": "face", "task": "今天，记录一个陌生人的表情——不必评价，只描述它出现的时机。"},
    {"id": "rain", "task": "雨后出门（或开窗）三分钟，分辨气味里的至少三层：湿土、柏油、植物。"},
    {"id": "sound", "task": "闭眼听一分钟窗外，找出最远的那一层声音来自哪个方向。"},
    {"id": "light", "task": "找一束光落在物体上的位置，描述它让那个物体发生了什么变化。"},
    {"id": "hands", "task": "观察一个人的手十秒（不冒犯的距离），猜猜他刚做过什么。"},
    {"id": "color", "task": "在回家路上找一种今天才注意到的颜色，记下它出现的地方。"},
    {"id": "pause", "task": "记录一次自己的'停顿'：今天哪一刻你突然慢了下来？那一刻周围有什么。"},
    {"id": "stranger", "task": "给一个擦肩而过的人编一个 15 字内的'可能性'，不评价对错。"},
    {"id": "taste", "task": "喝今天第一口水时，认真感受它经过喉咙的温度与速度。"},
    {"id": "night", "task": "睡前看一眼夜空或窗外灯火，数出三盏还亮着的灯，替它们各编一个理由。"},
]


@router.get("/api/psyche/observer/task")
async def observer_task():
    data = _load(OBSERVER_FILE, {"done": [], "current": None})
    today = _today()
    cur = data.get("current") or {}
    if cur.get("date") != today:
        used = [d.get("id") for d in data.get("done", [])]
        pool = [t for t in _OBSERVER_POOL if t["id"] not in used] or _OBSERVER_POOL
        cur = dict(random.choice(pool))
        cur["date"] = today
        cur["submitted"] = False
        data["current"] = cur
        _save(OBSERVER_FILE, data)
    return {"task": cur,
            "streak": len([d for d in data.get("done", []) if d.get("date", "") >= (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")]),
            "history": list(reversed(data.get("done", [])[-12:]))}


@router.post("/api/psyche/observer/submit")
async def observer_submit(req: Request):
    body = await req.json()
    notes = str(body.get("notes") or "").strip()[:400]
    if not notes:
        return JSONResponse({"error": "写下你的观察"}, status_code=400)
    data = _load(OBSERVER_FILE, {"done": [], "current": None})
    cur = data.get("current") or {}
    if not cur.get("task"):
        cur = dict(random.choice(_OBSERVER_POOL))
        cur["date"] = _today()
    sys_extra = (
        f"她完成了许墨布置的微观察任务。\n任务：{cur['task']}\n她的观察记录：{notes}\n"
        "以心理学教授身份输出两段：1) analysis：对她的观察方式做一段心理分析（90-140字），"
        "肯定她观察里最独特的那个角度（引用她的原词），点出这反映了怎样的注意力风格；"
        "2) story：一段由她的观察延展出的微型故事片段（80-130字，第三人称，"
        "主角是'他'与'她'，把她的观察变成故事里的一个场景，结尾留一个温柔的钩子）。"
        '只输出 JSON：{"analysis":"...","story":"..."}'
    )
    r = await _llm_json(sys_extra, "开始解读", max_tokens=700)
    analysis = str(r.get("analysis") or "").strip()
    story = str(r.get("story") or "").strip()
    if not _real(analysis, 15):
        analysis = ("你的观察里有一样东西很珍贵：你没有急着解释，只是先看见了。"
                    "多数人的眼睛是用来确认预期的，而你的，今天为意外留了门。")
    if not story:
        story = ("后来他总在想那个瞬间：她停下来，世界也跟着慢了半拍。"
                 "他想，所谓观察，不过是把注意力当成礼物送出去。而她送得很慷慨。")
    rec = {"id": _nid(), "date": _today(), "ts": _stamp(), "task": cur["task"],
           "notes": notes, "analysis": analysis, "story": story}
    data.setdefault("done", []).append(rec)
    data["done"] = data["done"][-100:]
    cur["submitted"] = True
    data["current"] = cur
    _save(OBSERVER_FILE, data)
    _touch_relation({"understanding": 2, "boundary": 1}, "观察者挑战 · 完成")
    _affinity("psyche_observer", "完成微观察任务")
    return {"record": rec}


# ---------------------------------------------------------------------------
# 7. 平行世界通讯
# ---------------------------------------------------------------------------

PARALLEL_FILE = "psyche_parallel.json"
_PARA_LINES = {
    "professor": {
        "name": "大学教授线 · Lucien",
        "bio": "这条世界线里，他终身执教，从未涉足商业帝国。他认识你的方式，是你在课堂第三排举手反驳了他的理论。",
        "style": "严谨、引经据典、把爱意藏进脚注",
    },
    "crimpsy": {
        "name": "犯罪心理学家线 · Ares",
        "bio": "这条世界线里，他没有留在大学，成了警局顾问。他认识你的方式，是你成了他某起案件的当事人。",
        "style": "锐利、危险感、用案件隐喻说情话",
    },
    "lover": {
        "name": "普通恋人线 · 阿墨",
        "bio": "这条世界线里，他只是个开旧书店的普通人。他认识你的方式，是你总在雨天来躲雨，从不买书。",
        "style": "松弛、烟火气、笨拙直接的温柔",
    },
}


def _load_parallel() -> dict:
    data = _load(PARALLEL_FILE, None)
    if not isinstance(data, dict) or "lines" not in data:
        data = {"lines": {k: {"convergence": 10, "msgs": [], "merged": False}
                          for k in _PARA_LINES}, "inbox_order": []}
    return data


@router.get("/api/psyche/parallel")
async def parallel_get():
    data = _load_parallel()
    out = {}
    for k, meta in _PARA_LINES.items():
        st = data["lines"][k]
        out[k] = {
            "name": meta["name"], "bio": meta["bio"],
            "convergence": st.get("convergence", 0),
            "merged": st.get("merged", False),
            "unread": len([m for m in st.get("msgs", []) if not m.get("read")]),
            "last": (st.get("msgs") or [{}])[-1],
        }
    return {"lines": out}


@router.post("/api/psyche/parallel/poll")
async def parallel_poll(req: Request):
    body = await req.json()
    line = str(body.get("line") or "professor").strip()
    if line not in _PARA_LINES:
        return JSONResponse({"error": "没有这条世界线"}, status_code=404)
    data = _load_parallel()
    st = data["lines"][line]
    meta = _PARA_LINES[line]
    conv = st.get("convergence", 0)
    merged = st.get("merged", False)

    # 交汇度满 → 触发世界线交汇事件（一次）
    if conv >= 80 and not merged:
        sys_extra = (
            f"世界线「{meta['name']}」与主世界线交汇度已达 {conv}/100。"
            f"这条线的许墨（风格：{meta['style']}）短暂穿过了世界缝隙，"
            "给主世界的她发来最后一条讯息。写 100-160 字：他知道自己是'另一个他'，"
            "把这条线里最想对她说、而主世界的他没说出口的那句话留下，然后告别。"
            "末尾世界线将收束为一道光。"
            '只输出 JSON：{"text":"交汇讯息","options":[]}'
        )
        r = await _llm_json(sys_extra, "世界线交汇", max_tokens=500)
        text = str(r.get("text") or "").strip()
        if not _real(text, 20):
            text = (
            "……原来交汇是这样一种感觉：像两页纸被同一阵风同时翻开。"
            "替我告诉你那边的我——有些话，别等太久。再见，我的。")
        msg = {"id": _nid(), "ts": _stamp(), "text": text, "options": [],
               "kind": "merge", "read": False, "convergence": conv}
        st["msgs"].append(msg)
        st["merged"] = True
        _save(PARALLEL_FILE, data)
        _touch_relation({"trust": 2, "understanding": 2}, f"世界线交汇 · {meta['name']}")
        _affinity("psyche_parallel_merge", f"世界线交汇 · {meta['name']}")
        return {"message": msg, "line": line, "lines": _para_view(data)}

    # 常规讯息：LLM 生成 + 2-3 个回复选项（不同倾向 → 不同交汇增量）
    last = (st.get("msgs") or [{}])[-1]
    sys_extra = (
        f"你是世界线「{meta['name']}」里的许墨（人设：{meta['bio']}；说话风格：{meta['style']}）。\n"
        f"当前与她的世界线交汇度：{conv}/100（越高，这条线的他越'真实'地意识到她的存在）。\n"
        "给她发一条跨世界线讯息（80-140字）：日常里忽然出现的'既视感'、"
        "梦境残响或实验室 anomaly，让他怀疑另一个自己的存在。"
        "保留该世界线的语言风格，与主世界许墨有可感知的差异。"
        "然后给出 3 个回复选项（每个 15 字内），分别代表：靠近(a)/试探(b)/克制(c)三种态度。\n"
        "上一条讯息（避免重复）：" + str(last.get("text", ""))[:80] + "\n"
        '只输出 JSON：{"text":"讯息","options":["...","...","..."]}'
    )
    r = await _llm_json(sys_extra, "生成新讯息", max_tokens=600)
    text = str(r.get("text") or "").strip()
    options = [str(o) for o in (r.get("options") or []) if str(o).strip()][:3]
    if not text:
        text = "（信号微弱）……这条讯息是自动发出的。如果你收到了——说明两个世界，离得比想象中近。"
    if not options:
        options = ["我也梦到过你", "你是谁？真的是你吗", "……先照顾好你那边的自己"]
    msg = {"id": _nid(), "ts": _stamp(), "text": text, "options": options,
           "kind": "normal", "read": False, "convergence": conv}
    st["msgs"].append(msg)
    st["msgs"] = st["msgs"][-40:]
    _save(PARALLEL_FILE, data)
    return {"message": msg, "line": line, "lines": _para_view(data)}


@router.post("/api/psyche/parallel/reply")
async def parallel_reply(req: Request):
    body = await req.json()
    line = str(body.get("line") or "").strip()
    msg_id = str(body.get("msg_id") or "")
    choice = str(body.get("choice") or "").strip()[:60]
    if line not in _PARA_LINES or not choice:
        return JSONResponse({"error": "参数缺失"}, status_code=400)
    data = _load_parallel()
    st = data["lines"][line]
    meta = _PARA_LINES[line]
    msg = next((m for m in st.get("msgs", []) if m.get("id") == msg_id), None)
    if not msg:
        return JSONResponse({"error": "讯息不存在"}, status_code=404)
    msg["read"] = True

    # 态度判定：靠近 → 交汇+，试探 → 中，克制 → 交汇微降但边界+
    near = any(k in choice for k in ["也", "梦", "想", "在", "等", "信"])
    restrain = any(k in choice for k in ["先", "照顾", "不必", "别", "距离"])
    delta = 9 if near else (-2 if restrain else 4)
    old = st.get("convergence", 0)
    st["convergence"] = max(0, min(100, old + delta))

    sys_extra = (
        f"世界线「{meta['name']}」（风格：{meta['style']}）的许墨收到了她的回复：「{choice}」。\n"
        f"原讯息：{msg.get('text', '')}\n交汇度 {old}→{st['convergence']}（她的态度："
        f"{'靠近' if delta >= 9 else '克制' if delta < 0 else '试探'}）。\n"
        "写他的短回复（45-90字）：靠近时他会更确信'她能感知到这条线'，克制时他会温柔地退后半步"
        "但留下一个钩子。保留世界线风格。"
        '只输出 JSON：{"echo":"回复文本"}'
    )
    r = await _llm_json(sys_extra, "回音", max_tokens=400)
    echo = str(r.get("echo") or "").strip()
    if not _real(echo, 10):
        echo = "……收到。这条线上的雨，刚刚停了。"
    echo_msg = {"id": _nid(), "ts": _stamp(), "text": echo, "options": [],
                "kind": "echo", "read": True, "convergence": st["convergence"]}
    st["msgs"].append(echo_msg)
    _save(PARALLEL_FILE, data)
    _touch_relation({"understanding": 1, "boundary": 1 if delta < 0 else 0,
                     "trust": 1 if delta >= 9 else 0}, f"平行通讯 · {meta['name']}")
    _affinity("psyche_parallel", f"回复世界线讯息 · {meta['name']}")
    return {"echo": echo_msg, "convergence": st["convergence"],
            "merged": st.get("merged", False), "lines": _para_view(data)}


def _para_view(data: dict) -> dict:
    out = {}
    for k, meta in _PARA_LINES.items():
        st = data["lines"].get(k, {})
        out[k] = {"name": meta["name"], "convergence": st.get("convergence", 0),
                  "merged": st.get("merged", False),
                  "unread": len([m for m in st.get("msgs", []) if not m.get("read")])}
    return out


@router.get("/api/psyche/parallel/{line}/messages")
async def parallel_messages(line: str):
    if line not in _PARA_LINES:
        return JSONResponse({"error": "没有这条世界线"}, status_code=404)
    data = _load_parallel()
    st = data["lines"][line]
    for m in st.get("msgs", []):
        m["read"] = True
    _save(PARALLEL_FILE, data)
    return {"messages": st.get("msgs", [])[-30:], "line": _PARA_LINES[line],
            "convergence": st.get("convergence", 0), "merged": st.get("merged", False)}


# ---------------------------------------------------------------------------
# 8. 梦境解析互动
# ---------------------------------------------------------------------------

DREAM_FILE = "psyche_dream.json"
_DREAM_FRAGMENTS = ["坠落", "飞行", "被追赶", "考试", "迟到", "迷路", "牙齿脱落",
                    "故人重逢", "透明的水", "重复的房间", "发光的 door", "说不出话"]
_DREAM_LAYERS = [
    {"key": "surface", "name": "表层 · 意象"},
    {"key": "emotion", "name": "第二层 · 情绪"},
    {"key": "memory", "name": "第三层 · 记忆的回声"},
    {"key": "subconscious", "name": "第四层 · 潜意识线索"},
    {"key": "scene", "name": "梦境剧情 · 可探索场景"},
]


@router.post("/api/psyche/dream/start")
async def dream_start(req: Request):
    body = await req.json()
    text = str(body.get("text") or "").strip()[:300]
    tags = [str(t).strip()[:12] for t in (body.get("tags") or []) if str(t).strip()][:6]
    if not text and not tags:
        return JSONResponse({"error": "描述一个梦的片段，或选择标签"}, status_code=400)
    session = {"id": _nid(), "ts": _stamp(), "text": text, "tags": tags,
               "layer": 0, "turns": [], "finished": False}
    data = _load(DREAM_FILE, {"sessions": []})
    data["sessions"].append(session)
    data["sessions"] = data["sessions"][-40:]
    _save(DREAM_FILE, data)
    first = await _dream_step(session, data, None)
    return {"session": session, "reply": first}


async def _dream_step(session: dict, data: dict, answer: str | None) -> dict:
    """推进一层梦境解读；返回该层的解读+追问（或最终场景）。"""
    li = min(session["layer"], len(_DREAM_LAYERS) - 1)
    layer = _DREAM_LAYERS[li]
    last = _DREAM_LAYERS[li - 1]["name"] if li > 0 else "起点"
    if layer["key"] == "scene":
        sys_extra = (
            "梦境解读抵达最后一层。基于全部对话，生成一段'可探索的梦境剧情'（120-180字）："
            "用第二人称写她在梦中的下一个场景（包含此前出现过的意象的变形），"
            "场景结尾给出两个可探索的方向（如'推开那扇门 / 沿着水声走'），"
            "并点破一条潜意识线索（原来这个梦一直在说……）。"
            '只输出 JSON：{"scene":"剧情文本","paths":["路径A(10字内)","路径B(10字内)"],"clue":"潜意识线索(30字内)"}'
        )
    else:
        guides = {
            "surface": "只做意象的'白描式'展开：这些意象放在一起，画面本身在说什么？不要急于解释象征。",
            "emotion": "聚焦情绪：梦里的情绪往往比画面诚实。指出这份情绪在白天可能戴着什么面具。",
            "memory": "寻找记忆的回声：这些意象与她可能经历过的场景有什么呼应（用'也许/可能'的口吻）。",
            "subconscious": "给出潜意识线索：这个梦反复出现的主题，可能指向一个她没对自己承认的需要。",
        }
        sys_extra = (
            f"你在陪她逐层解析梦境，当前是「{layer['name']}」（上一阶段：{last}）。本层要求：{guides[layer['key']]}\n"
            "输出：1) interpretation：本层解读（90-150字，许墨口吻，温柔专业，可引用一个心理学概念，仅一处）；"
            "2) question：一个引导她进入下一层的问题（25字内，具体不空泛）。"
            '只输出 JSON：{"interpretation":"...","question":"..."}'
        )
    ctx = f"她的梦：{session['text'] or '、'.join(session['tags'])}\n梦的标签：{'、'.join(session['tags']) or '无'}"
    if answer:
        ctx += f"\n她对上一层的回应：{answer}"
    if session["turns"]:
        ctx += "\n已解读内容摘要：" + " / ".join(t.get("brief", "") for t in session["turns"][-3:])
    r = await _llm_json(sys_extra, ctx, max_tokens=700)

    if layer["key"] == "scene":
        scene = str(r.get("scene") or "").strip()
        clue = str(r.get("clue") or "").strip()[:60]
        paths = [str(p).strip()[:12] for p in (r.get("paths") or []) if str(p).strip()][:2]
        if not scene:
            scene = ("你站在梦的最后一层。之前所有意象——" + "、".join(session["tags"][:3] or ["光", "水"]) +
                     "——此刻都安静下来，变成一扇虚掩的门和一条向下的水声。门缝里有你熟悉的温度。")
        if not paths:
            paths = ["推开那扇门", "沿着水声走"]
        if not _real(clue, 6):
            clue = "这个梦反复出现的，其实是'想被谁稳稳接住'这件事本身。"
        reply = {"layer": layer["name"], "kind": "scene", "scene": scene, "paths": paths, "clue": clue}
        session["turns"].append({"brief": clue, "layer": layer["name"]})
        session["finished"] = True
    else:
        interp = str(r.get("interpretation") or "").strip()
        question = str(r.get("question") or "").strip()[:40]
        if not interp:
            interp = {"surface": "把这些意象并排放在一起，它们已经开始互相解释了——梦境是心灵最诚实的排版师。",
                      "emotion": "梦里的情绪不会撒谎，它只是换了一身衣服。白天被你按下去的那部分，晚上会自己走出来。",
                      "memory": "记忆不负责完整保存，它负责按需重写。梦里出现的场景，多半是几段记忆的剪贴簿。",
                      "subconscious": "梦不是谜语，是提示。它反复强调的主题，往往是你清醒时最不愿承认的需要。"}[layer["key"]]
        if not _real(question, 5):
            question = {"surface": "梦里最清晰的一个画面，是什么颜色的？",
                        "emotion": "白天最近一次有类似情绪，是什么时候？",
                        "memory": "这个画面，让你想起哪段真实的经历？",
                        "subconscious": "如果这个梦有一个没说出口的请求，它会是什么？"}[layer["key"]]
        reply = {"layer": layer["name"], "kind": "interpret", "interpretation": interp, "question": question}
        session["turns"].append({"brief": interp[:30], "layer": layer["name"]})
    session["layer"] += 1
    _save(DREAM_FILE, data)
    if session.get("finished"):
        _touch_relation({"dependence": 1, "understanding": 2}, "梦境解析 · 完成")
        _affinity("psyche_dream", "完成一次梦境解析")
    return reply


@router.post("/api/psyche/dream/next")
async def dream_next(req: Request):
    body = await req.json()
    sid = str(body.get("session_id") or "")
    answer = str(body.get("answer") or "").strip()[:300]
    data = _load(DREAM_FILE, {"sessions": []})
    s = next((x for x in data["sessions"] if x.get("id") == sid), None)
    if not s:
        return JSONResponse({"error": "解析会话不存在"}, status_code=404)
    if s.get("finished"):
        return JSONResponse({"error": "这场梦已经解析完成"}, status_code=400)
    if not answer:
        return JSONResponse({"error": "写下你的回应"}, status_code=400)
    s.setdefault("answers", []).append(answer)
    reply = await _dream_step(s, data, answer)
    return {"session": s, "reply": reply}


@router.get("/api/psyche/dream/history")
async def dream_history():
    data = _load(DREAM_FILE, {"sessions": []})
    return {"history": list(reversed(data["sessions"][-12:]))}


# ---------------------------------------------------------------------------
# 10. 共同创作实验
# ---------------------------------------------------------------------------

COWRITE_FILE = "psyche_cowrite.json"
_GENRES = {
    "love_letter": "一封情书",
    "mystery": "一篇悬疑小说",
    "report": "一份实验报告",
    "notes": "一本只属于两人的观察笔记",
}


@router.get("/api/psyche/cowrite/works")
async def cowrite_works():
    data = _load(COWRITE_FILE, {"works": []})
    return {"works": list(reversed(data.get("works", [])[-20:]))}


@router.post("/api/psyche/cowrite/start")
async def cowrite_start(req: Request):
    body = await req.json()
    genre = str(body.get("genre") or "notes").strip()
    if genre not in _GENRES:
        genre = "notes"
    opening = str(body.get("opening") or "").strip()[:200]
    if not opening:
        return JSONResponse({"error": "先写下一句开头"}, status_code=400)
    sys_extra = (
        f"你们在共同完成「{_GENRES[genre]}」。她写下了开头：\n「{opening}」\n"
        "由许墨续写下一段（60-130字）。要求：贴合该体裁的语感——"
        "情书要克制深情；悬疑要埋一个钩子；实验报告要用学术格式但藏私心（如'样本1号：心动频率异常'）；"
        "观察笔记要像他真的在观察她。续写要留一个接口，让她能接下去。"
        '只输出 JSON：{"text":"续写段落"}'
    )
    r = await _llm_json(sys_extra, "开始续写", max_tokens=500)
    text = str(r.get("text") or "").strip()
    if not _real(text, 15):
        text = "（他把你的句子读了两遍）……这个开头不错。接下来的部分，交给我。"
    work = {"id": _nid(), "genre": genre, "genre_name": _GENRES[genre],
            "ts": _stamp(), "title": str(body.get("title") or "").strip()[:20] or _GENRES[genre],
            "parts": [{"who": "you", "text": opening, "ts": _stamp()},
                    {"who": "xumo", "text": text, "ts": _stamp()}],
            "finished": False, "afterword": ""}
    data = _load(COWRITE_FILE, {"works": []})
    data["works"].append(work)
    data["works"] = data["works"][-40:]
    _save(COWRITE_FILE, data)
    _touch_relation({"understanding": 1}, f"共同创作 · 开始{_GENRES[genre]}")
    _affinity("psyche_cowrite", f"开笔 · {_GENRES[genre]}")
    return {"work": work}


@router.post("/api/psyche/cowrite/continue")
async def cowrite_continue(req: Request):
    body = await req.json()
    wid = str(body.get("work_id") or "")
    text = str(body.get("text") or "").strip()[:300]
    if not text:
        return JSONResponse({"error": "写下你的一段"}, status_code=400)
    data = _load(COWRITE_FILE, {"works": []})
    w = next((x for x in data["works"] if x.get("id") == wid), None)
    if not w:
        return JSONResponse({"error": "作品不存在"}, status_code=404)
    if w.get("finished"):
        return JSONResponse({"error": "这篇已经完稿了"}, status_code=400)
    w["parts"].append({"who": "you", "text": text, "ts": _stamp()})
    full = "\n".join(("你：" if p["who"] == "you" else "许墨：") + p["text"] for p in w["parts"])
    sys_extra = (
        f"共同创作「{w['genre_name']}」进行中，已有内容：\n{full}\n"
        "许墨续写下一段（60-130字）：呼应她刚写的段落里最亮的一个词，推进情节/情感一层，"
        "保持体裁语感，结尾留接口或递进。如果故事已接近自然收尾，可以在段末埋一个'接近终点'的信号。"
        '只输出 JSON：{"text":"续写段落","near_end":true或false}'
    )
    r = await _llm_json(sys_extra, "继续", max_tokens=500)
    xtext = str(r.get("text") or "").strip()
    if not _real(xtext, 15):
        xtext = "……你写的这句，我想留给读者反复读。下一段，我们各退半步，在中间相遇。"
    w["parts"].append({"who": "xumo", "text": xtext, "ts": _stamp()})
    _save(COWRITE_FILE, data)
    _touch_relation({"understanding": 1, "trust": 1}, "共同创作 · 续写")
    _affinity("psyche_cowrite_turn", f"合写 · {w['title']}")
    return {"work": w}


@router.post("/api/psyche/cowrite/finish")
async def cowrite_finish(req: Request):
    body = await req.json()
    wid = str(body.get("work_id") or "")
    data = _load(COWRITE_FILE, {"works": []})
    w = next((x for x in data["works"] if x.get("id") == wid), None)
    if not w:
        return JSONResponse({"error": "作品不存在"}, status_code=404)
    if w.get("finished"):
        return {"work": w}
    full = "\n".join(("你：" if p["who"] == "you" else "许墨：") + p["text"] for p in w["parts"])
    sys_extra = (
        f"共同创作「{w['genre_name']}·{w['title']}」完稿。全文：\n{full}\n"
        "由许墨写两段：1) ending：正文最后一段（50-100字，收束全文，点题但不点破）；"
        "2) afterword：落款后记（70-120字，跳出作品，以许墨本人身份对她说："
        "这次合写里他最喜欢的她写的一句（引用原句），以及'合写'这件事本身意味着什么）。"
        '只输出 JSON：{"ending":"...","afterword":"..."}'
    )
    r = await _llm_json(sys_extra, "完稿", max_tokens=600)
    ending = str(r.get("ending") or "").strip()
    afterword = str(r.get("afterword") or "").strip()
    if not _real(ending, 12):
        ending = "（终）故事在这里停住，像光停在水面——不是结束，是折射的开始。"
    if not _real(afterword, 15):
        afterword = "后记：合写最迷人的地方在于，我永远猜不到你的下一句——这大概是我唯一乐见其成的失控。 ——许墨"
    w["parts"].append({"who": "xumo", "text": ending, "ts": _stamp()})
    w["finished"] = True
    w["afterword"] = afterword
    _save(COWRITE_FILE, data)
    _touch_relation({"trust": 1, "understanding": 1}, "共同创作 · 完稿")
    _affinity("psyche_cowrite_finish", f"完稿 · {w['title']}")
    return {"work": w}


# ---------------------------------------------------------------------------
# 11. 共写文章工作台
# ---------------------------------------------------------------------------

ARTICLE_FILE = "cowrite_articles.json"
_ARTICLE_KINDS = {
    "essay": "生活随笔",
    "popular_science": "科普文章",
    "review": "观点评论",
    "story": "故事文章",
}
_ARTICLE_TONES = {
    "warm": "温柔细腻",
    "clear": "清晰理性",
    "literary": "文学克制",
    "lively": "轻快自然",
}


def _article_words(text: str) -> int:
    """面向中文写作的近似字数：去掉空白后计数。"""
    return len(re.sub(r"\s+", "", str(text or "")))


def _article_summary(article: dict) -> dict:
    return {
        "id": article.get("id", ""),
        "title": article.get("title", "未命名文章"),
        "topic": article.get("topic", ""),
        "kind": article.get("kind", "essay"),
        "kind_name": article.get("kind_name", "生活随笔"),
        "tone": article.get("tone", "warm"),
        "tone_name": article.get("tone_name", "温柔细腻"),
        "status": article.get("status", "draft"),
        "updated_at": article.get("updated_at", article.get("created_at", "")),
        "word_count": _article_words(article.get("draft", "")),
    }


@router.get("/api/cowrite/articles")
async def article_list():
    data = _load(ARTICLE_FILE, {"articles": []})
    articles = list(reversed(data.get("articles", [])[-30:]))
    return {"articles": [_article_summary(x) for x in articles]}


@router.get("/api/cowrite/articles/{article_id}")
async def article_get(article_id: str):
    data = _load(ARTICLE_FILE, {"articles": []})
    article = next((x for x in data.get("articles", []) if x.get("id") == article_id), None)
    if not article:
        return JSONResponse({"error": "文章不存在"}, status_code=404)
    article["word_count"] = _article_words(article.get("draft", ""))
    return {"article": article}


@router.post("/api/cowrite/articles")
async def article_create(req: Request):
    body = await req.json()
    topic = str(body.get("topic") or "").strip()[:160]
    if not topic:
        return JSONResponse({"error": "先告诉许墨想写什么"}, status_code=400)
    title = str(body.get("title") or "").strip()[:40]
    kind = str(body.get("kind") or "essay").strip()
    tone = str(body.get("tone") or "warm").strip()
    if kind not in _ARTICLE_KINDS:
        kind = "essay"
    if tone not in _ARTICLE_TONES:
        tone = "warm"
    kind_name = _ARTICLE_KINDS[kind]
    tone_name = _ARTICLE_TONES[tone]
    prompt = (
        f"你要和她共同写一篇{kind_name}。主题是：{topic}\n"
        f"文章语气：{tone_name}。她暂定的标题：{title or '尚未决定'}。\n"
        "请像真正的共同作者一样，先搭好可继续修改的骨架，不要一次写完。"
        "outline 给出 3-5 个短小的段落要点；opening 写 120-220 字开篇；"
        "note 用 35-70 字对她说明你为何这样开篇，并邀请她接下一段。"
        '只输出 JSON：{"title":"建议标题","outline":["要点一","要点二"],'
        '"opening":"文章开篇","note":"许墨给她的话"}'
    )
    result = await _llm_json(prompt, "我们开始写吧。", max_tokens=1000)
    generated_title = str(result.get("title") or "").strip()[:40]
    opening = str(result.get("opening") or "").strip()
    note = str(result.get("note") or "").strip()
    outline = result.get("outline") if isinstance(result.get("outline"), list) else []
    outline = [str(x).strip()[:100] for x in outline if str(x).strip()][:5]
    if not title:
        title = generated_title or topic[:18] or "和许墨共写的文章"
    if not outline:
        outline = ["从一个具体瞬间切入", "展开主题与细节", "留下值得回味的结尾"]
    if not _real(opening, 30):
        opening = f"关于“{topic}”，我想先从一个很小的瞬间写起。也许真正值得留下的，并不是结论，而是我们如何一步步靠近它。"
    if not _real(note, 12):
        note = "我先替我们铺好第一段。接下来不必追求完美，把你最想说的那句话写下来，我会接住它。"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    article = {
        "id": _nid(), "title": title, "topic": topic,
        "kind": kind, "kind_name": kind_name,
        "tone": tone, "tone_name": tone_name,
        "outline": outline, "draft": opening, "note": note,
        "suggestions": [], "status": "draft", "versions": [],
        "created_at": now, "updated_at": now,
    }
    data = _load(ARTICLE_FILE, {"articles": []})
    data.setdefault("articles", []).append(article)
    data["articles"] = data["articles"][-30:]
    _save(ARTICLE_FILE, data)
    _touch_relation({"understanding": 1}, "共同写作 · 新文章")
    _affinity("psyche_cowrite", f"共写文章 · {title}")
    article["word_count"] = _article_words(opening)
    return {"article": article}


@router.put("/api/cowrite/articles/{article_id}")
async def article_save(article_id: str, req: Request):
    body = await req.json()
    data = _load(ARTICLE_FILE, {"articles": []})
    article = next((x for x in data.get("articles", []) if x.get("id") == article_id), None)
    if not article:
        return JSONResponse({"error": "文章不存在"}, status_code=404)
    if "title" in body:
        title = str(body.get("title") or "").strip()[:40]
        if title:
            article["title"] = title
    if "draft" in body:
        draft = str(body.get("draft") or "")[:20000]
        article["draft"] = draft
    article["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save(ARTICLE_FILE, data)
    article["word_count"] = _article_words(article.get("draft", ""))
    return {"article": article}


@router.post("/api/cowrite/articles/{article_id}/assist")
async def article_assist(article_id: str, req: Request):
    body = await req.json()
    action = str(body.get("action") or "continue").strip()
    instruction = str(body.get("instruction") or "").strip()[:240]
    data = _load(ARTICLE_FILE, {"articles": []})
    article = next((x for x in data.get("articles", []) if x.get("id") == article_id), None)
    if not article:
        return JSONResponse({"error": "文章不存在"}, status_code=404)
    draft = str(body.get("draft") if "draft" in body else article.get("draft", ""))[:20000]
    article["draft"] = draft
    shared = (
        f"你正和她共同写《{article['title']}》，类型是{article['kind_name']}，语气是{article['tone_name']}。\n"
        f"主题：{article['topic']}\n提纲：{'；'.join(article.get('outline', []))}\n"
        f"当前全文：\n{draft or '（尚未落笔）'}\n"
        f"她的额外要求：{instruction or '没有额外要求'}\n"
    )
    changed = False
    reply = ""
    if action == "polish":
        prompt = shared + (
            "请在不改变观点、不抹掉她个人语气的前提下润色全文，理顺段落和衔接。"
            '只输出 JSON：{"draft":"润色后的完整全文","note":"你主要调整了什么"}'
        )
        result = await _llm_json(prompt, "请帮我们润色这一版。", max_tokens=2600)
        revised = str(result.get("draft") or "").strip()
        reply = str(result.get("note") or "").strip()
        if _real(revised, 30):
            old = article.get("draft", "")
            if old and old != revised:
                article.setdefault("versions", []).append({"ts": article.get("updated_at", ""), "draft": old})
                article["versions"] = article["versions"][-8:]
            article["draft"] = revised[:20000]
            changed = True
        if not _real(reply, 10):
            reply = "我保留了你的表达，只把句子之间的呼吸和段落的节奏理顺了一些。"
    elif action == "suggest":
        prompt = shared + (
            "请以共同作者身份给出三条具体、可执行的修改建议，优先指出最值得保留的亮点，"
            "再说明下一步怎么写。不要重写全文。"
            '只输出 JSON：{"suggestions":["建议一","建议二","建议三"],"note":"一句鼓励或观察"}'
        )
        result = await _llm_json(prompt, "请读一遍，告诉我下一步。", max_tokens=900)
        suggestions = result.get("suggestions") if isinstance(result.get("suggestions"), list) else []
        suggestions = [str(x).strip()[:180] for x in suggestions if str(x).strip()][:3]
        if not suggestions:
            suggestions = ["保留目前最具体的细节，再补一个能让读者看见画面的例子。", "让下一段回应开篇提出的问题。", "结尾回到标题，但不要直接重复标题。"]
        article["suggestions"] = suggestions
        reply = str(result.get("note") or "").strip() or "这一版已经有自己的呼吸了。我们只需要再把最亮的那条线往前牵一点。"
    else:
        prompt = shared + (
            "请接着当前最后一段续写 120-220 字。承接她刚写下的内容，推进一个新层次，"
            "不要复述已有句子，不要总结全文，结尾留给她继续。"
            '只输出 JSON：{"addition":"续写的新段落","note":"许墨给她的一句话"}'
        )
        result = await _llm_json(prompt, "轮到你写一段。", max_tokens=1000)
        addition = str(result.get("addition") or "").strip()
        reply = str(result.get("note") or "").strip()
        if not _real(addition, 30):
            addition = "而当我们把目光再放近一些，会发现答案并不藏在宏大的结论里。它更像一次被认真看见的停顿：事情尚未结束，但某种变化已经发生，并且愿意等我们继续写下去。"
        article["draft"] = (draft.rstrip() + ("\n\n" if draft.strip() else "") + addition)[:20000]
        changed = True
        if not _real(reply, 10):
            reply = "我把这一段接在这里了。下一笔仍然交给你——我很好奇你会把它带向哪里。"
    article["note"] = reply
    article["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    article["status"] = "draft"
    _save(ARTICLE_FILE, data)
    _touch_relation({"understanding": 1, "trust": 1}, "共同写作 · 协作一轮")
    _affinity("psyche_cowrite_turn", f"共写文章 · {article['title']}")
    article["word_count"] = _article_words(article.get("draft", ""))
    return {"article": article, "reply": reply, "changed": changed}


@router.post("/api/cowrite/articles/{article_id}/finish")
async def article_finish(article_id: str, req: Request):
    body = await req.json()
    data = _load(ARTICLE_FILE, {"articles": []})
    article = next((x for x in data.get("articles", []) if x.get("id") == article_id), None)
    if not article:
        return JSONResponse({"error": "文章不存在"}, status_code=404)
    draft = str(body.get("draft") if "draft" in body else article.get("draft", ""))[:20000]
    if _article_words(draft) < 40:
        return JSONResponse({"error": "再写一点，至少 40 字后再定稿"}, status_code=400)
    article["draft"] = draft
    article["status"] = "finished"
    article["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    article["note"] = "这一篇先写到这里。它有你的判断，也有我们共同留下的节奏——这比所谓完美更难得。"
    _save(ARTICLE_FILE, data)
    _touch_relation({"trust": 1, "understanding": 1}, "共同写作 · 文章定稿")
    _affinity("psyche_cowrite_finish", f"文章定稿 · {article['title']}")
    article["word_count"] = _article_words(draft)
    return {"article": article}
