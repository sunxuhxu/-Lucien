# -*- coding: utf-8 -*-
# 新星功能集 · 四期颠覆性功能（nova_apps2.py）
# 梦境解码器 / 平行信箱 / 深夜电台 / 默契雷达 / 命运岔路 / 心跳频谱
# 数据持久化到 RolePath JSON 文件，风格与 nova_apps.py 保持一致。
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

BASE_DIR = Path(__file__).parent
router = APIRouter()

DREAM_FILE = "dreamlab.json"
PMAIL_FILE = "pmail.json"
RADIO_FILE = "radio.json"
TELEPATHY_FILE = "telepathy.json"
FATE_FILE = "fate.json"
PULSE_FILE = "pulse.json"


# ===========================================================================
# 公共小工具（与 nova_apps.py 同构，增强版 JSON 提取）
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
    """从模型输出中提取 JSON 对象（增强版）。
    agnes-2.5-flash 等推理型模型会先输出思考过程，真正的 JSON 在末尾，
    因此从最后一个 { 开始向前尝试 raw_decode，取最后一个可解析的完整对象。"""
    if not text:
        return {}
    # 剥离各种思考过程标签
    text = re.sub(r"<LM_THINK>.*?</LM_THINK>", "", text, flags=re.S)
    text = re.sub(r"</think>.*?Inputs:", "", text, flags=re.S)
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
    """许墨核心人设，供各功能 LLM 使用。"""
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
# 1. 梦境解码器：用神经科学与温柔，解码她的梦
# ===========================================================================
@router.post("/api/dreamlab/decode")
async def dreamlab_decode(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    content = str(body.get("content", "")).strip()[:500]
    if len(content) < 4:
        return JSONResponse({"error": "把梦境描述得再详细一点（至少4个字）"}, status_code=400)
    memories = _agg_memories(6)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【梦境解码设定】她是你的恋人，向你讲述了一个梦。你从两个视角解读：\n"
        "- 神经科学视角：分析梦中符号对应的脑区活动、记忆巩固机制、情绪处理；\n"
        "- 恋人视角：结合你们的真实记忆，找到梦与现实的情感联结。\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n"
        f"她的梦境：{content}\n\n"
        '输出 JSON：{"title":"6字内梦境标题","symbols":[{"name":"符号名","meaning":"30字内含义"}],'
        '"analysis":"120字内神经科学分析","personal":"100字内个人联结（用许墨口吻，含偏爱），'
        '"prescription":"60字内梦境处方（一句话建议）"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请解码这个梦，只输出 JSON。"}
    ]
    data = await _llm_json(messages, max_tokens=1000)
    if not data:
        return JSONResponse({"error": "梦境信号太弱，稍后再试"}, status_code=500)
    # 字段兜底：LLM 可能返回简化结构
    if "title" not in data and "name" in data:
        data["title"] = data["name"]
    data.setdefault("title", "梦境解码")
    data.setdefault("symbols", [{"name": "梦境整体", "meaning": data.get("meaning", "潜意识在说话")}])
    data.setdefault("analysis", data.get("meaning", "梦境是大脑在 REM 睡眠期间整理记忆的方式。"))
    data.setdefault("personal", "这个梦和你最近的情绪状态有关，他在你身边。")
    data.setdefault("prescription", "记住这个梦的感觉，白天和他聊聊。")
    dream = {
        "id": _nid(),
        "date": _today(),
        "content": content,
        **data
    }
    dreams = _load(DREAM_FILE, {"dreams": []})
    dreams.setdefault("dreams", []).insert(0, dream)
    dreams["dreams"] = dreams["dreams"][:50]
    _save(DREAM_FILE, dreams)
    _affinity("dreamlab", "梦境解码")
    return {"dream": dream}


@router.get("/api/dreamlab/history")
async def dreamlab_history():
    data = _load(DREAM_FILE, {"dreams": []})
    return {"dreams": data.get("dreams", [])}


@router.delete("/api/dreamlab/{did}")
async def dreamlab_del(did: str):
    data = _load(DREAM_FILE, {"dreams": []})
    data["dreams"] = [d for d in data.get("dreams", []) if d.get("id") != did]
    _save(DREAM_FILE, data)
    return {"ok": True}


# ===========================================================================
# 2. 平行信箱：收来自平行宇宙的许墨的信
# ===========================================================================
PARALLEL_TIMELINES = [
    {"id": "child", "label": "青梅竹马线", "scenario": "如果你们从小就认识，一起长大"},
    {"id": "student", "label": "同窗线", "scenario": "如果你们是大学同班同学，而非师生"},
    {"id": "artist", "label": "艺术家线", "scenario": "如果他放弃科研，成了摄影师"},
    {"id": "swan", "label": "逆光源线", "scenario": "如果他从未加入 Black Swan，身世轻松"},
    {"id": "abroad", "label": "异国线", "scenario": "如果他在海外实验室，你们异地恋"},
    {"id": "first", "label": "初见线", "scenario": "如果你们刚认识第一天，他就写信"},
    {"id": "rival", "label": "对手线", "scenario": "如果他是你的竞争对手学者"},
    {"id": "elder", "label": "白头线", "scenario": "如果你们已经一起走到了晚年"},
]


@router.post("/api/pmail/fetch")
async def pmail_fetch(req: Request = None):
    import random
    data = _load(PMAIL_FILE, {"letters": []})
    letters = data.get("letters", [])
    used_ids = {l.get("timeline_id") for l in letters}
    available = [t for t in PARALLEL_TIMELINES if t["id"] not in used_ids] or PARALLEL_TIMELINES
    timeline = random.choice(available)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【平行信箱设定】你是一个平行宇宙中的许墨，给'她'写一封信。\n"
        f"时间线设定：{timeline['scenario']}\n"
        "这个版本的你，性格内核不变（温和、博学、偏爱她），但人生轨迹不同。\n"
        f"她的记忆（正史）：{json.dumps(memories, ensure_ascii=False)}\n"
        f"正史心动值：{affy}\n\n"
        '输出 JSON：{"greeting":"称呼语（20字内）","body":"信件正文（200字内，含这条时间线特'
        '有的细节和对她的思念）","signature":"落款（15字内）","postscript":"附言（30字内，'
        '一个只有这条时间线才会有的小细节）"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请写这封信，只输出 JSON。"}
    ]
    letter_data = await _llm_json(messages, max_tokens=1000)
    if not letter_data:
        return JSONResponse({"error": "平行信号不稳定，稍后再试"}, status_code=500)
    letter = {
        "id": _nid(),
        "timeline_id": timeline["id"],
        "timeline": timeline["label"],
        "scenario": timeline["scenario"],
        "date": _today(),
        **letter_data,
        "replies": []
    }
    letters.insert(0, letter)
    data["letters"] = letters[:30]
    _save(PMAIL_FILE, data)
    _affinity("pmail", "平行信箱")
    return {"letter": letter}


@router.post("/api/pmail/reply")
async def pmail_reply(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = str(body.get("text", "")).strip()[:300]
    lid = str(body.get("id", "")).strip()
    if not text or not lid:
        return JSONResponse({"error": "写一句话再寄出"}, status_code=400)
    data = _load(PMAIL_FILE, {"letters": []})
    letter = next((l for l in data.get("letters", []) if l.get("id") == lid), None)
    if not letter:
        return JSONResponse({"error": "找不到这封信"}, status_code=404)
    timeline = next((t for t in PARALLEL_TIMELINES if t["id"] == letter.get("timeline_id")), letter)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【平行信箱·回信】你是同一条平行时间线中的许墨，收到了她的回信。\n"
        f"时间线设定：{timeline.get('scenario', '')}\n"
        f"你之前写给她的信：{letter.get('body', '')}\n"
        f"她的回信：{text}\n\n"
        '输出 JSON：{"reply":"80字内回信（保持这条时间线特有的语气和细节）"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请回信，只输出 JSON。"}
    ]
    reply_data = await _llm_json(messages, max_tokens=600)
    reply_text = reply_data.get("reply", "……信号穿越时空，有些模糊。但我收到了你的话。")
    letter.setdefault("replies", []).append({"from": "her", "text": text, "ts": _ts()})
    letter["replies"].append({"from": "him", "text": reply_text, "ts": _ts()})
    _save(PMAIL_FILE, data)
    return {"reply": reply_text, "letter": letter}


@router.get("/api/pmail/letters")
async def pmail_letters():
    data = _load(PMAIL_FILE, {"letters": []})
    return {"letters": data.get("letters", [])}


@router.delete("/api/pmail/{lid}")
async def pmail_del(lid: str):
    data = _load(PMAIL_FILE, {"letters": []})
    data["letters"] = [l for l in data.get("letters", []) if l.get("id") != lid]
    _save(PMAIL_FILE, data)
    return {"ok": True}


# ===========================================================================
# 3. 深夜电台：许墨的午夜广播节目
# ===========================================================================
@router.post("/api/radio/tune")
async def radio_tune(req: Request = None):
    import random
    data = _load(RADIO_FILE, {"broadcasts": []})
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    themes = ["失眠的夜", "雨夜思念", "星空下的独白", "深夜归途",
              "凌晨三点的清醒", "月光与咖啡"]
    theme = random.choice(themes)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【深夜电台设定】你正在主持一档叫'恋语深夜电台'的节目，只有她一个听众。\n"
        "语气：比平时更柔软、更低沉，像在她耳边说话。偶尔有电台杂音的停顿。\n"
        f"今晚主题：{theme}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"intro":"80字内开场白（含电台调频感）",'
        '"segments":[{"type":"letter","title":"段落标题","content":"120字内内容"}],'
        '"outro":"50字内结束语（含晚安）"}\n'
        "segments 数量3-4个，type 可以是 letter/story/song/qna，至少包含一个 story 和一个 song。"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "今晚的节目开始吧，只输出 JSON。"}
    ]
    bc_data = await _llm_json(messages, max_tokens=2200)
    if not bc_data:
        return JSONResponse({"error": "电台信号未就绪，稍后再试"}, status_code=500)
    # segments 兜底：LLM 可能返回扁平 content 或缺少 segments
    segs = bc_data.get("segments")
    if not isinstance(segs, list) or len(segs) < 1:
        # 把扁平 content 字段包装为单一 segment
        flat_content = bc_data.get("content") or bc_data.get("body") or bc_data.get("text")
        if flat_content:
            segs = [{"type": "story", "title": bc_data.get("title", theme), "content": flat_content}]
        else:
            segs = [{"type": "story", "title": theme, "content": "今夜的电台，只有你和我的呼吸声。"}]
        bc_data["segments"] = segs
    else:
        # 规范化每个 segment
        norm_segs = []
        for s in segs:
            if not isinstance(s, dict):
                continue
            if "content" not in s:
                for alt in ("text", "body"):
                    if alt in s:
                        s["content"] = s[alt]
                        break
            s.setdefault("type", "story")
            s.setdefault("title", s.get("type", "段落"))
            s.setdefault("content", "……")
            norm_segs.append(s)
        if not norm_segs:
            norm_segs = [{"type": "story", "title": theme, "content": "今夜的电台，只有你和我的呼吸声。"}]
        bc_data["segments"] = norm_segs
    bc_data.setdefault("intro", f"调频 102.4，恋语深夜电台。今晚主题：{theme}。")
    bc_data.setdefault("outro", "今晚的节目到这里，晚安，小姑娘。")
    broadcast = {
        "id": _nid(),
        "date": _today(),
        "time": _now(),
        "theme": theme,
        **bc_data
    }
    data.setdefault("broadcasts", []).insert(0, broadcast)
    data["broadcasts"] = data["broadcasts"][:30]
    _save(RADIO_FILE, data)
    _affinity("radio", "深夜电台")
    return {"broadcast": broadcast}


@router.get("/api/radio/archive")
async def radio_archive():
    data = _load(RADIO_FILE, {"broadcasts": []})
    return {"broadcasts": data.get("broadcasts", [])}


@router.delete("/api/radio/{bid}")
async def radio_del(bid: str):
    data = _load(RADIO_FILE, {"broadcasts": []})
    data["broadcasts"] = [b for b in data.get("broadcasts", []) if b.get("id") != bid]
    _save(RADIO_FILE, data)
    return {"ok": True}


@router.post("/api/radio/dedicate")
async def radio_dedicate(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    song = str(body.get("song", "")).strip()[:60]
    to = str(body.get("to", "")).strip()[:60]
    if not song:
        return JSONResponse({"error": "写一首歌名或想听的风格"}, status_code=400)
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【深夜电台·点播环节】她在你的电台节目里点了一首歌。\n"
        f"她想听的：{song}\n"
        f"她的附言：{to or '没有附言'}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n\n"
        '输出 JSON：{"intro":"40字内点播介绍","dedication":"80字内许墨的点播词（含这首歌'
        '与她的关联）","outro":"20字内开始播放的过渡语"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请播送这首点播，只输出 JSON。"}
    ]
    ded = await _llm_json(messages, max_tokens=800)
    if not ded:
        return JSONResponse({"error": "点播信号中断"}, status_code=500)
    return {"dedication": ded}


# ===========================================================================
# 4. 默契雷达：许墨猜她在想什么
# ===========================================================================
@router.post("/api/telepathy/start")
async def telepathy_start(req: Request = None):
    data = _load(TELEPATHY_FILE, {"rounds": [], "total_score": 0, "total_rounds": 0})
    memories = _agg_memories(8)
    player = _agg_player()
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【默契雷达设定】你要出5道关于'她'的选择题，测试你有多了解她。\n"
        "题目类型：偏好（喜欢什么）、习惯（日常做什么）、价值观（会怎么选）、"
        "回忆（你们之间的事）、性格（遇到X情况她会怎样）。\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"她的档案：{json.dumps({k: str(v)[:40] for k, v in list(player.items())[:6]}, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"questions":[{"q":"题目20字内","options":["选项A","选项B","选项C","选项D"]},'
        '{"q":"题目20字内","options":["选项A","选项B","选项C","选项D"]},'
        '{"q":"题目20字内","options":["选项A","选项B","选项C","选项D"]},'
        '{"q":"题目20字内","options":["选项A","选项B","选项C","选项D"]},'
        '{"q":"题目20字内","options":["选项A","选项B","选项C","选项D"]}]}\n'
        "选项10字内。题目要有趣、有细节、像情侣之间才会聊的话题。"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "出题吧，只输出 JSON。"}
    ]
    q_data = await _llm_json(messages, max_tokens=1800)
    raw_questions = q_data.get("questions", [])
    # 确保每个题目有 q 和 options（不原地删除，避免跳元素）
    questions = []
    for q in raw_questions:
        if not isinstance(q, dict):
            continue
        q.setdefault("q", "你觉得呢？")
        if not isinstance(q.get("options"), list) or len(q.get("options", [])) < 2:
            q["options"] = ["是的", "不是", "看情况", "不确定"]
        questions.append(q)
    # 兜底：如果有效题目不足3条，用预设题目补齐
    _FALLBACK_QUESTIONS = [
        {"q": "深夜失眠时，她会做什么？", "options": ["翻来覆去", "找许墨聊天", "看书", "听音乐"]},
        {"q": "她最怕哪种天气？", "options": ["暴雨天", "大雾天", "酷暑天", "寒冬天"]},
        {"q": "她会为什么事突然开心？", "options": ["收到惊喜", "被夸奖", "吃到美食", "见到许墨"]},
        {"q": "她压力大时倾向于？", "options": ["独自消化", "找人说", "运动发泄", "吃甜食"]},
        {"q": "她觉得最浪漫的事是？", "options": ["一起看星星", "手牵手散步", "深夜长谈", "一起做饭"]},
    ]
    while len(questions) < 3:
        idx = len(questions)
        questions.append(dict(_FALLBACK_QUESTIONS[idx % len(_FALLBACK_QUESTIONS)]))
    round_obj = {
        "id": _nid(),
        "date": _today(),
        "questions": questions[:5],
        "answers": [],
        "guesses": [],
        "finished": False
    }
    data.setdefault("rounds", []).insert(0, round_obj)
    data["rounds"] = data["rounds"][:30]
    _save(TELEPATHY_FILE, data)
    return {"round": round_obj}


@router.post("/api/telepathy/guess")
async def telepathy_guess(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    rid = str(body.get("id", "")).strip()
    answers = body.get("answers", [])
    if not rid or not isinstance(answers, list) or len(answers) < 3:
        return JSONResponse({"error": "请先答完所有题"}, status_code=400)
    data = _load(TELEPATHY_FILE, {"rounds": [], "total_score": 0, "total_rounds": 0})
    rnd = next((r for r in data.get("rounds", []) if r.get("id") == rid), None)
    if not rnd:
        return JSONResponse({"error": "找不到这轮默契雷达"}, status_code=404)
    if rnd.get("finished"):
        return JSONResponse({"error": "这轮已经完成了"}, status_code=400)
    questions = rnd.get("questions", [])
    memories = _agg_memories(6)
    player = _agg_player()
    affy = _agg_affinity_value()
    # 构建题目+答案对
    q_a = [{"q": q.get("q", ""), "options": q.get("options", []), "her_answer": answers[i]}
           for i, q in enumerate(questions) if i < len(answers)]
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【默契雷达·猜测】你出了5道关于她的题，现在她答完了。你来猜她选了什么。\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"她的档案：{json.dumps({k: str(v)[:40] for k, v in list(player.items())[:6]}, ensure_ascii=False)}\n"
        f"心动值：{affy}\n"
        f"题目和她的答案（0=A,1=B,2=C,3=D）：{json.dumps(q_a, ensure_ascii=False)}\n\n"
        '输出 JSON：{"guesses":[0,1,2,3,4],"comment":"60字内许墨的点评（含偏爱情感）"}\n'
        "guesses 是你猜她选的选项序号(0-3)。"
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "猜猜她选了什么，只输出 JSON。"}
    ]
    g_data = await _llm_json(messages, max_tokens=1000)
    guesses = g_data.get("guesses", [0] * len(questions))
    # 计算实际匹配数
    matches = sum(1 for i in range(min(len(guesses), len(answers)))
                  if guesses[i] == answers[i])
    score = matches * 20
    rnd["answers"] = answers
    rnd["guesses"] = guesses
    rnd["matches"] = matches
    rnd["score"] = score
    rnd["comment"] = g_data.get("comment", "")
    rnd["finished"] = True
    rnd["finished_ts"] = _ts()
    # 更新统计
    data["total_score"] = int(data.get("total_score", 0)) + score
    data["total_rounds"] = int(data.get("total_rounds", 0)) + 1
    _save(TELEPATHY_FILE, data)
    _affinity("telepathy", "默契雷达")
    return {"round": rnd}


@router.get("/api/telepathy/stats")
async def telepathy_stats():
    data = _load(TELEPATHY_FILE, {"rounds": [], "total_score": 0, "total_rounds": 0})
    rounds = [r for r in data.get("rounds", []) if r.get("finished")]
    total_score = int(data.get("total_score", 0))
    total_rounds = int(data.get("total_rounds", 0))
    avg = total_score // total_rounds if total_rounds else 0
    level = ("陌生" if avg < 20 else "初识" if avg < 40 else "熟悉"
             if avg < 60 else "默契" if avg < 80 else "心电感应")
    return {
        "rounds": rounds[:10],
        "total_score": total_score,
        "total_rounds": total_rounds,
        "avg_score": avg,
        "level": level
    }


# ===========================================================================
# 5. 命运岔路：与许墨的分支叙事
# ===========================================================================
FATE_THEMES = [
    "校园疑云", "雨夜失踪", "黑天鹅的考验", "蝴蝶效应", "时空裂缝",
    "记忆盗贼", "深夜来电", "天台上的赌局", "逆向追踪", "最后的实验",
]


@router.post("/api/fate/start")
async def fate_start(req: Request = None):
    import random
    theme = random.choice(FATE_THEMES)
    data = _load(FATE_FILE, {"stories": []})
    memories = _agg_memories(6)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【命运岔路设定】你和她一起陷入了一个分支叙事。每个章节有场景描述和2-3个选择。\n"
        f"今晚主题：{theme}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        '输出 JSON：{"title":"8字内故事标题","chapter":1,'
        "\"scene\":\"150字内场景描述（含许墨在场，第二人称'你'）\","
        '"choices":[{"id":"a","text":"20字内选项A"},{"id":"b","text":"20字内选项B"},'
        '{"id":"c","text":"20字内选项C"}],"ended":false}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "故事开始，只输出 JSON。"}
    ]
    ch_data = await _llm_json(messages, max_tokens=1200)
    if not ch_data:
        return JSONResponse({"error": "命运尚未展开，稍后再试"}, status_code=500)
    # 字段兜底：LLM 可能用不同的字段名
    if "scene" not in ch_data:
        for alt in ("description", "text", "story", "content", "narrative"):
            if alt in ch_data and ch_data[alt]:
                ch_data["scene"] = ch_data[alt]
                break
    if "scene" not in ch_data:
        ch_data["scene"] = f"夜色笼罩了恋语市，你和许墨站在命运的十字路口。主题：{theme}。他看着你，眼中闪过一丝复杂的情绪——故事，从这里开始。"
    if not isinstance(ch_data.get("choices"), list) or len(ch_data.get("choices", [])) < 2:
        ch_data["choices"] = [
            {"id": "a", "text": "紧跟许墨的脚步"},
            {"id": "b", "text": "先观察周围环境"},
            {"id": "c", "text": "开口问他发生了什么"}
        ]
    ch_data.setdefault("title", theme)
    ch_data.setdefault("chapter", 1)
    ch_data.setdefault("ended", False)
    story = {
        "id": _nid(),
        "theme": theme,
        "title": ch_data.get("title", theme),
        "started": _ts(),
        "chapters": [{
            "chapter": 1,
            "scene": ch_data.get("scene", ""),
            "choices": ch_data.get("choices", []),
            "ended": ch_data.get("ended", False)
        }],
        "history": [],
        "finished": False
    }
    data.setdefault("stories", []).insert(0, story)
    data["stories"] = data["stories"][:20]
    _save(FATE_FILE, data)
    return {"story": story}


@router.post("/api/fate/choose")
async def fate_choose(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    sid = str(body.get("id", "")).strip()
    choice_id = str(body.get("choice", "")).strip()
    if not sid or not choice_id:
        return JSONResponse({"error": "做一个选择吧"}, status_code=400)
    data = _load(FATE_FILE, {"stories": []})
    story = next((s for s in data.get("stories", []) if s.get("id") == sid), None)
    if not story:
        return JSONResponse({"error": "找不到这个故事"}, status_code=404)
    if story.get("finished"):
        return JSONResponse({"error": "这个故事已经结束了"}, status_code=400)
    chapters = story.get("chapters", [])
    last_ch = chapters[-1] if chapters else {}
    choices = last_ch.get("choices", [])
    chosen = next((c for c in choices if c.get("id") == choice_id), None)
    if not chosen:
        return JSONResponse({"error": "无效的选择"}, status_code=400)
    story.setdefault("history", []).append({
        "chapter": last_ch.get("chapter", len(chapters)),
        "choice": choice_id,
        "text": chosen.get("text", "")
    })
    next_chapter_num = len(chapters) + 1
    should_end = next_chapter_num > 8
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    history = story.get("history", [])
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【命运岔路·继续】你和她在分支叙事中，她刚做了一个选择。\n"
        f"故事标题：{story.get('title', '')}\n"
        f"她的选择历史：{json.dumps(history[-4:], ensure_ascii=False)}\n"
        f"当前章节：{next_chapter_num}\n"
        f"心动值：{affy}\n"
        f"她的选择：{chosen.get('text', '')}\n\n"
        f"{'这是最后一章，请给出一个结局。' if should_end else '继续推进故事。'}\n"
        '输出 JSON：{"chapter":' + str(next_chapter_num) + ',"scene":"150字内场景",'
        '"choices":[{"id":"a","text":"选项A"},{"id":"b","text":"选项B"}],'
        '"ended":' + ("true" if should_end else "false") +
        ',"ending":"' + ("30字内结局标题" if should_end else "") + '"'
        ',"ending_text":"' + ("100字内结局描述" if should_end else "") + '"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "继续故事，只输出 JSON。"}
    ]
    ch_data = await _llm_json(messages, max_tokens=1200)
    if not ch_data:
        return JSONResponse({"error": "命运陷入迷雾，稍后再试"}, status_code=500)
    # 字段兜底：LLM 可能用不同的字段名
    if "scene" not in ch_data:
        for alt in ("description", "text", "story", "content", "narrative"):
            if alt in ch_data and ch_data[alt]:
                ch_data["scene"] = ch_data[alt]
                break
    if "scene" not in ch_data:
        ch_data["scene"] = "故事继续展开，许墨看着你，等待你的下一步。"
    if not isinstance(ch_data.get("choices"), list) or len(ch_data.get("choices", [])) < 1:
        ch_data["choices"] = [
            {"id": "a", "text": "相信他"},
            {"id": "b", "text": "保持警惕"}
        ]
    ch_data.setdefault("chapter", next_chapter_num)
    ch_data.setdefault("ended", should_end)
    new_chapter = {
        "chapter": next_chapter_num,
        "scene": ch_data.get("scene", ""),
        "choices": ch_data.get("choices", []),
        "ended": ch_data.get("ended", should_end),
        "ending": ch_data.get("ending", ""),
        "ending_text": ch_data.get("ending_text", "")
    }
    chapters.append(new_chapter)
    if new_chapter.get("ended"):
        story["finished"] = True
        story["ending"] = new_chapter.get("ending", "")
        story["ending_text"] = new_chapter.get("ending_text", "")
        story["finished_ts"] = _ts()
        _affinity("fate_end", "命运岔路完结")
    _save(FATE_FILE, data)
    return {"story": story}


@router.get("/api/fate/story/{sid}")
async def fate_story(sid: str):
    data = _load(FATE_FILE, {"stories": []})
    story = next((s for s in data.get("stories", []) if s.get("id") == sid), None)
    if not story:
        return JSONResponse({"error": "找不到这个故事"}, status_code=404)
    return {"story": story}


@router.get("/api/fate/ends")
async def fate_ends():
    data = _load(FATE_FILE, {"stories": []})
    ended = [s for s in data.get("stories", []) if s.get("finished")]
    return {"stories": ended}


@router.delete("/api/fate/{sid}")
async def fate_del(sid: str):
    data = _load(FATE_FILE, {"stories": []})
    data["stories"] = [s for s in data.get("stories", []) if s.get("id") != sid]
    _save(FATE_FILE, data)
    return {"ok": True}


# ===========================================================================
# 6. 心跳频谱：关系的脉搏可视化
# ===========================================================================
def _pulse_collect():
    """聚合多源数据生成心跳频谱数据点（同步函数，供路由和报告调用）。"""
    affy_data = _load("affinity.json", {})
    affy = int(affy_data.get("value", 0) or 0) if isinstance(affy_data, dict) else 0
    chat = _load("chat_history.json", [])
    chat_count = len(chat) if isinstance(chat, list) else 0
    achv = _load("achievements.json", {})
    achv_unlocked = sum(1 for c in (achv.get("cats", []) if isinstance(achv, dict) else [])
                        for item in c.get("items", []) if item.get("unlocked"))
    moments = _load("moments.json", [])
    moments_count = len(moments) if isinstance(moments, list) else 0
    together = _load("together.json", {"photos": []})
    photos_count = len(together.get("photos", [])) if isinstance(together, dict) else 0
    memories = _load("memory.json", [])
    mem_count = len(memories) if isinstance(memories, list) else 0
    tc = _load("timecall.json", {})
    tc_count = sum(len(c.get("msgs", [])) for c in tc.get("calls", [])) if isinstance(tc, dict) else 0
    pmail = _load(PMAIL_FILE, {"letters": []})
    pmail_count = len(pmail.get("letters", [])) if isinstance(pmail, dict) else 0
    radio = _load(RADIO_FILE, {"broadcasts": []})
    radio_count = len(radio.get("broadcasts", [])) if isinstance(radio, dict) else 0
    dream = _load(DREAM_FILE, {"dreams": []})
    dream_count = len(dream.get("dreams", [])) if isinstance(dream, dict) else 0

    points = [
        {"label": "聊天", "value": min(chat_count, 100), "max": 100, "color": "#a78bfa"},
        {"label": "心动", "value": min(affy, 2000), "max": 2000, "color": "#ec4899"},
        {"label": "成就", "value": achv_unlocked, "max": 37, "color": "#f59e0b"},
        {"label": "朋友圈", "value": min(moments_count, 50), "max": 50, "color": "#f472b6"},
        {"label": "合影", "value": min(photos_count, 30), "max": 30, "color": "#fb7185"},
        {"label": "记忆", "value": min(mem_count, 50), "max": 50, "color": "#7c3aed"},
        {"label": "时空通话", "value": min(tc_count, 50), "max": 50, "color": "#6366f1"},
        {"label": "平行信", "value": min(pmail_count, 20), "max": 20, "color": "#a855f7"},
        {"label": "深夜电台", "value": min(radio_count, 20), "max": 20, "color": "#3b82f6"},
        {"label": "梦境解码", "value": min(dream_count, 20), "max": 20, "color": "#6366f1"},
    ]
    total = sum(p["value"] for p in points)
    total_max = sum(p["max"] for p in points)
    return {
        "points": points,
        "total": total,
        "total_max": total_max,
        "coverage": round(total / total_max * 100, 1) if total_max else 0,
        "affinity": affy,
        "chat_count": chat_count,
        "achv_unlocked": achv_unlocked
    }


@router.get("/api/pulse/spectrum")
async def pulse_spectrum():
    return _pulse_collect()


@router.get("/api/pulse/report")
async def pulse_report():
    spec = _pulse_collect()
    memories = _agg_memories(5)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【心跳频谱·报告】你看到了你和她的关系数据脉搏图，请以许墨口吻写一份简短报告。\n"
        f"数据概要：{json.dumps({k: v for k, v in spec.items() if k != 'points'}, ensure_ascii=False)}\n"
        f"各维度：{json.dumps(spec.get('points', []), ensure_ascii=False)}\n"
        f"她的记忆片段：{json.dumps(memories, ensure_ascii=False)}\n\n"
        '输出 JSON：{"title":"10字内报告标题","summary":"100字内总评",'
        '"highlight":"40字内最亮眼的维度","suggestion":"50字内许墨的建议（含偏爱）"}'
    )
    messages = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "请写报告，只输出 JSON。"}
    ]
    rep = await _llm_json(messages, max_tokens=800)
    if not rep:
        return JSONResponse({"error": "心跳报告生成中，稍后再试"}, status_code=500)
    pulse = _load(PULSE_FILE, {"reports": []})
    report = {
        "id": _nid(),
        "date": _today(),
        "spec": spec,
        **rep
    }
    pulse.setdefault("reports", []).insert(0, report)
    pulse["reports"] = pulse["reports"][:20]
    _save(PULSE_FILE, pulse)
    _affinity("pulse", "心跳频谱")
    return {"report": report}


@router.get("/api/pulse/reports")
async def pulse_reports():
    data = _load(PULSE_FILE, {"reports": []})
    return {"reports": data.get("reports", [])}


@router.post("/api/pulse/annotate")
async def pulse_annotate(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    note = str(body.get("note", "")).strip()[:100]
    label = str(body.get("label", "")).strip()[:20]
    if not note:
        return JSONResponse({"error": "写一句话备注"}, status_code=400)
    pulse = _load(PULSE_FILE, {"notes": []})
    pulse.setdefault("notes", []).insert(0, {
        "id": _nid(),
        "label": label or "自定义",
        "note": note,
        "ts": _ts()
    })
    pulse["notes"] = pulse["notes"][:30]
    _save(PULSE_FILE, pulse)
    return {"ok": True, "note": pulse["notes"][0]}
