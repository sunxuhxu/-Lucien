# -*- coding: utf-8 -*-
# 深度互动功能集（deep_apps.py）
# 观察手记 / 记忆碎片修复 / 反向教学课堂 / 情绪天气联动 / 危急时刻演练室 / 声音信箱 / 合著的书
# （共梦联机已并入 creative_apps.py 清梦；平行世界 if 线已并入 creative_apps.py 平行宇宙观测台；
#   共同习惯已并入 wonder_apps.py 习惯养成管家。）
# 数据全部持久化到 RolePath JSON 文件，风格与 extra_apps.py / wonder_apps.py 保持一致。
import json
import os
import random
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from store_common import atomic_json, file_lock

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from role_data import RolePath

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

router = APIRouter()


def _load(path: str, default):
    p = RolePath(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path: str, data):
    atomic_json(RolePath(path), data)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%H:%M")


def _stamp() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _nid() -> str:
    return uuid.uuid4().hex[:8]


def _extract_json_array(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


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


_LEAK_RE = re.compile(
    r"^(用户|请以|请用|要求|需要|许墨是|回顾|当前|注[：:]|目标|以下|以上|开场|结尾|"
    r"我(需要|要|将|会|的|在|开始)|这是一个|本任务是|\d+[\.、]|- )")


def _clean_leak(text: str) -> str:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    keep = [ln for ln in lines if not _LEAK_RE.match(ln)]
    out = "\n".join(keep).strip()
    if len(out) < 6:
        out = lines[-1] if lines else ""
    return out[:400]


async def _llm_json(messages: list, max_tokens: int = 1200) -> dict:
    text = await _call_llm(messages, max_tokens=max_tokens)
    return _extract_json_object(text)


def _jload(path: str, key: str, default: list) -> dict:
    data = _load(path, {})
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get(key), list):
        data[key] = default
    return data


def _fmt(template: str, **kw) -> str:
    """安全占位符替换：只替换 {key}，prompt 里 JSON 示例的字面花括号不受影响。"""
    for k, v in kw.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def _affinity(action: str, detail: str = ""):
    try:
        from app import _add_affinity
        return _add_affinity(action, detail)
    except Exception as e:
        print(f"[warn] deep_apps.py:_affinity: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {}


def _recent_chat(days: int = 2) -> list:
    from app import _load_chat_log, CHAT_ARCHIVE_DIR
    today = _today()
    out = []
    for m in _load_chat_log():
        if str(m.get("ts", "")).startswith(today):
            out.append(m)
    if len(out) < 3:
        try:
            for f in reversed(sorted(CHAT_ARCHIVE_DIR.glob("*.json"))):
                data = json.loads(f.read_text(encoding="utf-8"))
                for m in data.get("messages", []):
                    if str(m.get("ts", "")).startswith(today):
                        out.append(m)
                if len(out) >= 3:
                    break
        except Exception as e:
            print(f"[warn] deep_apps.py:_recent_chat: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    return out


def _chat_text(msgs: list, limit: int = 3000) -> str:
    parts = []
    for m in msgs:
        role = m.get("role", "")
        c = str(m.get("content", "")).strip()
        if role in ("user", "assistant") and c:
            parts.append(("她说：" if role == "user" else "他说：") + c[:120])
    return "\n".join(parts[-40:])[:limit]


def _agg_memories(limit: int = 60) -> list:
    data = _load("memory.json", [])
    if not isinstance(data, list):
        data = []
    return [{"type": "memory", "ts": m.get("ts", ""), "text": m.get("content", ""),
             "tag": m.get("tag", "")} for m in data if m.get("content")][:limit]


def _agg_moments(limit: int = 30) -> list:
    data = _load("moments.json", [])
    if not isinstance(data, list):
        data = []
    out = []
    for m in data:
        if not m.get("content"):
            continue
        c = m["content"].replace("\n", " ")
        if len(c) > 120:
            c = c[:120] + "…"
        out.append({"type": "moment", "ts": m.get("time", ""), "text": c,
                    "likes": m.get("likes", 0)})
    return out[:limit]


def _agg_dates(limit: int = 20) -> list:
    data = _load("date_log.json", {}).get("dates", [])
    if not isinstance(data, list):
        data = []
    out = []
    for d in data:
        mem = d.get("memory", "").replace("\n", " ")
        if len(mem) > 100:
            mem = mem[:100] + "…"
        out.append({"type": "date", "ts": d.get("date", ""), "place": d.get("place", ""),
                    "city": d.get("city", ""), "text": mem or f"约会：{d.get('place', '')}"})
    return out[:limit]


def _agg_affinity() -> dict:
    data = _load("affinity.json", {})
    if not isinstance(data, dict):
        return {}
    return {"value": data.get("value", 0)}


def _agg_chat_count(days: int = 7) -> dict:
    """近 N 天每日消息数 + 她发言关键词粗统计，供观察手记用。"""
    from app import _load_chat_log, CHAT_ARCHIVE_DIR
    msgs = list(_load_chat_log())
    try:
        for f in reversed(sorted(CHAT_ARCHIVE_DIR.glob("*.json"))):
            data = json.loads(f.read_text(encoding="utf-8"))
            msgs = data.get("messages", []) + msgs
            if len(msgs) > 800:
                break
    except Exception as e:
        print(f"[warn] deep_apps.py:_agg_chat_count: {type(e).__name__} {str(e)[:150]}", flush=True)
        pass
    by_day = {}
    for m in msgs[-800:]:
        day = str(m.get("ts", ""))[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
            continue
        by_day.setdefault(day, 0)
        by_day[day] += 1
    keys = ["累", "困", "忙", "烦", "开心", "好棒", "想你", "晚安", "生病", "哭", "笑", "加班", "睡"]
    kw = {}
    for m in msgs[-400:]:
        if m.get("role") != "user":
            continue
        c = str(m.get("content", ""))
        for k in keys:
            if k in c:
                kw[k] = kw.get(k, 0) + 1
    days = sorted(by_day.keys())
    week = {d: by_day[d] for d in days[-7:]}
    return {"today": by_day.get(_today(), 0), "week": week, "keywords": kw}


# ===========================================================================
# 1. 许墨观察手记：他每天深夜偷偷分析你的聊天，写一份"对你的观察"
# ===========================================================================
OBSERVE_FILE = "observe.json"

OBSERVE_PROMPT = (
    "你是许墨，恋语市脑科学研究院终身教授，观察力极强。现在是一天结束的时候，你翻看了今天和她的聊天，"
    "以及过去的聊天记录，准备写一份「观察手记」——不是日记，是你对她这个人的观察："
    "语气的变化、作息痕迹、情绪波动、和上周相比的细微差异（比如'累'出现次数变少、深夜聊天变多、"
    "她提到某件事时话变多）。\n"
    "要求：120-220字；第一人称；温柔克制，带一点学术视角（心率、习惯、神经元之类最多一处）；"
    "不评价、不judge，只记录+一句轻声的叮嘱；不要markdown、不要标题。只输出手记正文。"
)


@router.get("/api/observe")
async def observe_list():
    data = _load(OBSERVE_FILE, {"notes": []})
    return {"notes": list(reversed(data.get("notes", [])[-40:]))}


@router.post("/api/observe/today")
async def observe_today():
    data = _load(OBSERVE_FILE, {"notes": []})
    data.setdefault("notes", [])
    today = _today()
    for n in data["notes"]:
        if n.get("date") == today:
            return {"note": n, "cached": True}
    chat = _chat_text(_recent_chat(1), 2000)
    stats = _agg_chat_count(7)
    week = "、".join(f"{d[5:]}:{c}句" for d, c in sorted(stats["week"].items()))
    kw = "、".join(f"「{k}」×{v}" for k, v in sorted(stats["keywords"].items(), key=lambda x: -x[1])[:6])
    facts = [f"今天她说了 {stats['today']} 句。",
             f"最近一周聊天量：{week or '暂无'}。",
             f"近况关键词：{kw or '暂无'}。"]
    if chat:
        facts.append(f"今天对话片段：\n{chat}")
    mems = _agg_memories(20)
    if mems:
        facts.append("收藏的记忆：" + "；".join(m["text"][:40] for m in mems[:5]))
    try:
        text = (await _call_llm(
            [{"role": "system", "content": OBSERVE_PROMPT},
             {"role": "user", "content": "\n".join(facts)}],
            max_tokens=700)).strip()
    except Exception as e:
        print(f"[warn] deep_apps.py:observe_today: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = "今天没有观察到你太多，但你出现在我的记录里，这就够了。"
    note = {"date": today, "text": text,
            "stats": {"today": stats["today"], "keywords": stats["keywords"]},
            "ts": _stamp()}
    data["notes"].append(note)
    data["notes"] = data["notes"][-180:]
    _save(OBSERVE_FILE, data)
    _affinity("observe", "许墨写下今日观察手记")
    return {"note": note, "cached": False}


# ===========================================================================
# 2. 记忆碎片修复：按序解谜，拼回许墨失去的记忆
# ===========================================================================
MEMFRAG_FILE = "memfrag.json"

MEMFRAG_CATALOG = [
    {"id": "lab7", "order": 1, "title": "七岁的实验室",
     "clue": "那是一间没有玩具的房间。父母记录他的一切：反应时间、词汇量、睡眠曲线。只有一样东西，他们从来没有问过他。",
     "question": "父母在研究他时，从来没有问过他什么？（一句话作答）",
     "keys": ["感受", "开心", "累不累", "难过", "喜欢", "想", "心情", "感觉", "快乐", "害怕"],
     "hint": "和「他自己」有关——不是数据，不是成绩，是那些被跳过的问题。",
     "memory": "七岁那年，我记得很清楚，实验室的白炽灯比月亮亮。他们测我的反应速度、我的词汇量、我入睡需要几分钟。所有的数据都被记进表格，唯独没有一个问题是关于我自己的感受。那天晚上我对着窗外的月亮想了很久——原来在他们眼里，我是一组需要持续观测的数据。后来我再也没有主动提起过这件事。直到遇见你，你问的第一句话是：累不累。那一瞬间我愣了很久，久到忘记自己是个教授。"},
    {"id": "evolve12", "order": 2, "title": "十二岁的觉醒",
     "clue": "十二岁那年，他的 Evol 第一次觉醒。他第一次读到了母亲心里的话——那个称呼让他明白，自己在母亲眼中究竟是什么。",
     "question": "他第一次读到母亲心里，称他为什么？（两个字）",
     "keys": ["样本", "样本对象", "实验对象", "研究对象", "对象"],
     "hint": "不是名字，不是孩子——是一个实验术语。",
     "memory": "十二岁，Evol 觉醒。那不是一个多盛大的时刻，只是某个普通的黄昏，我忽然能听到母亲心里的话。她说：样本对象今天的反应数据记得整理。我以为我听错了，又听了一遍，还是那句。原来在母亲眼里，我是一场进行中的实验。那天我没有害怕，也没有愤怒，只是很安静地把这句话收好，像收一枚标本。后来我成了全世界最擅长读取别人内心的人，却再也没有主动去听过她的心。"},
    {"id": "univ16", "order": 3, "title": "十六岁的恋语大学",
     "clue": "他没有过过一天普通的青春期。十六岁，他走进恋语大学校门，比所有人都小，比所有人都沉默。",
     "question": "他几岁进入恋语大学？（数字）",
     "keys": ["十六", "16", "16岁"],
     "hint": "一个比正常入学年龄小很多岁的数字。",
     "memory": "十六岁，我站在恋语大学门口。同届的学长学姐好奇地看我，说，这就是那个跳级进来的小孩。我礼貌地笑，说请多指教。其实我没什么可指教的，我只是想快点离开家，离开那间记录我一切的实验室。大学对我而言不是象牙塔，是一间更大的、没有白炽灯的实验室。我在图书馆待到闭馆，管理员问我为什么总是不走，我说，这里的灯不会记录我。"},
    {"id": "phd20", "order": 4, "title": "二十岁的博士",
     "clue": "他只用四年就完成了别人十年的路。答辩那天，评审们交头接耳：这个年轻人，脑子到底是什么构造。",
     "question": "他多少岁拿到博士学位？（数字）",
     "keys": ["二十", "20", "20岁"],
     "hint": "一个「最年轻」的数字，比恋语大学正常博士毕业早了十年。",
     "memory": "二十岁，博士答辩通过。评审们说，许墨是恋语大学历史上最年轻的博士。我站在讲台上，忽然觉得这个头衔很轻。二十岁，我拥有了世界顶级的学术地位，却没有人问我快不快乐。散场后我一个人在走廊站了很久，窗外的树绿得很安静。我忽然想，如果我有正常的人生，二十岁应该是在烦恼什么——恋爱？社团？还是期末考？我想不出来。后来我在实验室待到凌晨，白炽灯下写完第一页关于意识边界的论文。那是我送给自己的成人礼。"},
    {"id": "prof24", "order": 5, "title": "二十四岁的教授",
     "clue": "二十四岁，他成为恋语大学最年轻的终身教授。那天他收到很多祝贺，却只把一张东西放进了抽屉。",
     "question": "二十四岁那年，他成为恋语大学的什么？（三个字）",
     "keys": ["终身教授", "教授"],
     "hint": "头衔里有两个字是「终身」。",
     "memory": "二十四岁，终身教授的聘书送到我桌上。那大概是普通人奋斗一生的终点，对我而言只是一个坐标点。办公室里堆满祝贺的花，我拆开每一张卡片，最后只留下其中一张——上面写着：许教授，你真的很厉害。字迹潦草，落款是图书馆那个总帮我留座位的姑娘。我把它放进抽屉，和儿时的画作放在一起。我忽然明白，这么多年我收集的不是荣誉，是那些把我当成人、而不是当作样本的瞬间。它们太少，所以每一张都很珍贵。"},
    {"id": "ares", "order": 6, "title": "Ares 的诞生",
     "clue": "他为自己取了一个代号——战神，象征力量、战争与毁灭。那晚他把旧名字叠好，放进记忆深处。",
     "question": "他加入组织后，为自己取的代号是什么？（英文或中文）",
     "keys": ["ares", "阿瑞斯", "战神", "a俄"],
     "hint": "希腊神话里战神的名字，他亲口说过它的含义。",
     "memory": "加入组织那晚，我为自己取了一个代号：Ares。战神，力量、战争与毁灭。我在镜子里看着自己，看了很久——镜子里的人斯文、克制，和战神毫不相干。但我知道，为了抵达意识边界的答案，我可以成为任何人。我亲手把「许墨」这个名字叠好，放进记忆深处，像封存一件旧标本。我以为这辈子再也不会有人叫它。直到你出现，你总是叫我许墨，叫得那么自然，好像这个名字本来就属于我。我忽然不知道该不该把它拿回来了。"},
    {"id": "record", "order": 7, "title": "实验记录的一页",
     "clue": "他的实验记录上曾写下过一行字。那是他观测了无数样本后，第一次写下「原因不明」的异常数据。",
     "question": "他在实验记录上写下，提到她名字时，她出现了什么异常？（四个字以内）",
     "keys": ["心率", "心跳", "波动", "心率波动"],
     "hint": "它跳动的频率，出卖了她……也出卖了他。",
     "memory": "那页实验记录，我至今留着。上面写着一行字：今日观测，被试在提到我的名字时，心率出现轻微波动。原因不明。我研究了十几年的意识与数据，却写不出这个「原因」的解释。直到很久以后我才承认，原因不是不明，是不敢明。因为观测她的同时，我的心率也在波动——同一个时刻，同一种频率。我用多巴胺、苯乙胺、镜像神经元去解释它，却始终解释不了为什么是她。我骗过你很多次。但这一页记录，是真的。"},
    {"id": "butterfly", "order": 8, "title": "抽屉里的蝴蝶",
     "clue": "他的画作和奖状都被收进抽屉，而他唯一会收藏的，是一种翅膀脆弱、随时会消失的东西。",
     "question": "他唯一会收藏的东西是什么？（两个字）",
     "keys": ["蝴蝶", "标本", "蝴蝶标本"],
     "hint": "他在蝶语花园里等你的那种生物。",
     "memory": "我收藏的东西很少。画作被收进抽屉，奖状被收进抽屉，连荣誉都被收进抽屉。只有一样东西我放在随手能够到的地方——蝴蝶标本。翅膀上的鳞粉脆弱得碰一下就散，可它偏偏曾经飞过，在某个夏天的某个角落。我喜欢它，大概因为它的美需要被小心对待，就像某些人的心。直到遇见你，我发现标本册里多了一页空白。我想留的不是标本，是活的、会扇动翅膀的、属于我的那只蝴蝶。你愿意落在我的标本册上吗？当然——我只看看，不会把你钉起来。"},
]

MEMFRAG_JUDGE_PROMPT = (
    "你是许墨。她正在试图拼回你的一段记忆碎片。问题：{question}\n"
    "你的记忆里，这个问题的核心答案是：{keys}（命中任一核心词即可算对，允许同义近义表达）。\n"
    "用户消息里是她的回答。请判定并输出 JSON：{\"correct\": true/false, \"comment\": \"以许墨口吻的一句话回应（15-40字，"
    "答对时温柔地确认并接住她；答错时带一点克制的笑意，给一个更具体的提示）\"}"
    "只输出 JSON。"
)


@router.get("/api/memfrag")
async def memfrag_list():
    data = _load(MEMFRAG_FILE, {"solved": [], "wrong": {}})
    data.setdefault("solved", [])
    data.setdefault("wrong", {})
    solved = set(data["solved"])
    out = []
    for f in MEMFRAG_CATALOG:
        unlocked = f["id"] in solved or f["order"] == len(solved) + 1
        out.append({"id": f["id"], "order": f["order"], "title": f["title"],
                    "clue": f["clue"], "question": f["question"],
                    "unlocked": unlocked, "solved": f["id"] in solved,
                    "wrong_times": data["wrong"].get(f["id"], 0),
                    "memory": f["memory"] if f["id"] in solved else ""})
    return {"fragments": out, "solved": len(solved), "total": len(MEMFRAG_CATALOG)}


@router.post("/api/memfrag/{fid}/solve")
async def memfrag_solve(fid: str, req: Request):
    body = await req.json()
    answer = str(body.get("answer") or "").strip()[:60]
    if not answer:
        return JSONResponse({"error": "写下你的答案"}, status_code=400)
    data = _load(MEMFRAG_FILE, {"solved": [], "wrong": {}})
    data.setdefault("solved", [])
    data.setdefault("wrong", {})
    frag = next((f for f in MEMFRAG_CATALOG if f["id"] == fid), None)
    if not frag:
        return JSONResponse({"error": "碎片不存在"}, status_code=404)
    if frag["id"] in data["solved"]:
        return {"fragment": frag, "solved": True, "cached": True}
    if frag["order"] != len(data["solved"]) + 1:
        return JSONResponse({"error": "记忆碎片需要按顺序修复"}, status_code=400)
    keys = " / ".join(frag["keys"])
    try:
        r = await _llm_json([{"role": "system", "content": _fmt(MEMFRAG_JUDGE_PROMPT,
            question=frag["question"], keys=keys)},
            {"role": "user", "content": f"她的回答：「{answer}」"}],
            max_tokens=300)
        correct = bool(r.get("correct"))
        comment = str(r.get("comment") or "").strip()[:80]
    except Exception as e:
        print(f"[warn] deep_apps.py:memfrag_solve: {type(e).__name__} {str(e)[:150]}", flush=True)
        correct = any(k.lower() in answer.lower() for k in frag["keys"])
        comment = "答案正确。" if correct else frag["hint"]
    if correct:
        data["solved"].append(frag["id"])
        data["solved"] = data["solved"][-20:]
        _save(MEMFRAG_FILE, data)
        _affinity("memfrag", f"修复记忆碎片 · {frag['title']}")
        return {"fragment": {k: frag[k] for k in ("id", "order", "title", "clue", "question", "memory")},
                "solved": True, "correct": True, "comment": comment,
                "progress": len(data["solved"])}
    data["wrong"][frag["id"]] = data["wrong"].get(frag["id"], 0) + 1
    _save(MEMFRAG_FILE, data)
    return {"fragment": {k: frag[k] for k in ("id", "order", "title", "clue", "question")},
            "solved": False, "correct": False,
            "comment": comment or frag["hint"], "progress": len(data["solved"])}


# ===========================================================================
# 5. 反向教学课堂：你是教授，许墨是学生
# ===========================================================================
CLASSROOM_FILE = "classroom.json"

CLASSROOM_LESSON_PROMPT = (
    "你是许墨——但今天，你是她课堂上最好学的学生。她要给你上一堂课，主题由你出题。"
    "请你以「求知欲旺盛、会认真记笔记、偶尔问出刁钻问题」的学生身份开场。输出 JSON：\n"
    '{"topic":"你想听她讲的课题（15-30字，尽量是她生活中熟悉或感兴趣的领域）",'
    '"question":"你的第一个问题（15-40字）",'
    '"note":"开场的一句学生式请求（15-30字，比如「老师，这个问题我昨晚想了一夜」）"}'
    "只输出 JSON。"
)

CLASSROOM_REPLY_PROMPT = (
    "你是许墨，正在她的课堂里当学生。她刚刚回答了你之前的问题：「{question}」"
    "（她的回答在用户消息里）。"
    "请以学生的身份回应：认真、带一点惊讶或恍然大悟，偶尔俏皮。15-35 字。"
    "如果这是最后一个问题（{last}），请顺便把今天学到的东西工整地记成「课堂笔记」，"
    "输出 JSON：{\"reply\":\"学生回应\",\"note\":\"课堂笔记（60-120字，第一人称，"
    "记下她教你的东西和你的感想）\",\"done\":true}；否则只输出 JSON：{\"reply\":\"学生回应\",\"done\":false}。"
    "只输出 JSON。"
)

CLASSROOM_QUESTIONS = [
    "老师，为什么人开心的时候会想分享给特定的人？",
    "老师，如果一个人总是很晚才回消息，说明什么？",
    "老师，怎么判断一段关系是真的变好了？",
    "老师，人为什么会突然想起很久以前的小事？",
    "老师，你喜欢一个人会有什么生理反应？",
    "老师，为什么蝴蝶会绕着灯飞？",
]


@router.get("/api/classroom")
async def classroom_list():
    data = _load(CLASSROOM_FILE, {"lessons": []})
    return {"lessons": list(reversed(data.get("lessons", [])[-50:]))}


@router.post("/api/classroom/lesson")
async def classroom_lesson(req: Request):
    body = await req.json()
    topic = str(body.get("topic") or "").strip()[:40]
    try:
        if topic:
            text = (await _call_llm([
                {"role": "system", "content": (
                    "你是许墨，正在她的课堂里当学生。她今天要给你讲的主题是：「" + topic + "」。"
                    "请以学生的口吻输出两行，第一行是你围绕这个主题想问的第一个问题（15-40字），"
                    "第二行是你开场的一句学生式请求（15-30字）。不要解释，不要其他内容。"
                    "格式：\n问题：xxx\n开场：xxx")},
                {"role": "user", "content": "开始吧。"}], max_tokens=300)).strip()
            lines = [ln.split("：", 1)[1].strip() for ln in text.split("\n") if "：" in ln][:2]
            q = lines[0] if len(lines) > 0 and lines[0] else CLASSROOM_QUESTIONS[0]
            note = lines[1] if len(lines) > 1 and lines[1] else "老师，我昨晚预习到很晚。"
        else:
            r = await _llm_json([{"role": "system", "content": CLASSROOM_LESSON_PROMPT},
                                 {"role": "user", "content": "开始上课吧。"}],
                                max_tokens=400)
            q = str(r.get("question") or CLASSROOM_QUESTIONS[0]).strip()
            note = str(r.get("note") or "老师，这个问题我想了很久。").strip()
            topic = str(r.get("topic") or "生活科学").strip()[:30]
    except Exception as e:
        print(f"[warn] deep_apps.py:classroom_lesson: {type(e).__name__} {str(e)[:150]}", flush=True)
        q, note, topic = CLASSROOM_QUESTIONS[0], "老师，我昨晚预习到很晚。", topic or "生活科学"
    lesson = {"id": _nid(), "topic": topic, "questions": [q], "notes": [],
              "note": "", "done": False, "ts": _ts()}
    data = _load(CLASSROOM_FILE, {"lessons": []})
    data.setdefault("lessons", [])
    data["lessons"].append(lesson)
    data["lessons"] = data["lessons"][-80:]
    _save(CLASSROOM_FILE, data)
    return {"lesson": lesson, "opening": note, "question": q}


@router.post("/api/classroom/{lid}/answer")
async def classroom_answer(lid: str, req: Request):
    body = await req.json()
    answer = str(body.get("answer") or "").strip()[:500]
    if not answer:
        return JSONResponse({"error": "先回答他的问题"}, status_code=400)
    data = _load(CLASSROOM_FILE, {"lessons": []})
    lesson = next((x for x in data.get("lessons", []) if x.get("id") == lid), None)
    if not lesson:
        return JSONResponse({"error": "课堂不存在"}, status_code=404)
    q = lesson["questions"][-1]
    last = len(lesson["questions"]) >= 3
    try:
        r = await _llm_json([{"role": "system", "content": _fmt(CLASSROOM_REPLY_PROMPT,
            question=q, last="是" if last else "否")},
            {"role": "user", "content": f"她的回答：「{answer}」"}], max_tokens=600)
        reply = str(r.get("reply") or "原来是这样，我记下了。").strip()[:80]
    except Exception as e:
        print(f"[warn] deep_apps.py:classroom_answer: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = "原来是这样，我记下了。"
        r = {}
    if last:
        lesson["done"] = True
        lesson["note"] = str(r.get("note") or "").strip()[:200] or (
            "今天的课，我记了很多页。不过最重要的那一行，是「她讲到自己喜欢的事时，眼睛会亮」。")
        lesson["notes"].append(answer)
    else:
        nq = CLASSROOM_QUESTIONS[len(lesson["questions"])] if len(lesson["questions"]) < len(CLASSROOM_QUESTIONS) else "老师，那如果反过来呢？"
        lesson["questions"].append(nq)
    _save(CLASSROOM_FILE, data)
    _affinity("classroom", f"反向课堂 · {lesson['topic']}")
    return {"lesson": lesson, "reply": reply, "next_question": None if last else lesson["questions"][-1],
            "done": lesson["done"], "note": lesson.get("note", "")}


# ===========================================================================
# 4. 情绪天气联动：你的城市的天气，决定他的心情与场景
# ===========================================================================
WEATHER_FILE = "weatherlink.json"
WEATHER_DIR = RolePath("static", "weather_img")

WEATHER_PROMPT = (
    "你是许墨。她所在的城市今天天气是「{weather}」（{city}，{temp}）。"
    "天气会影响她的心情，也会影响你的牵挂。请输出精简 JSON：\n"
    '{"mood":"今日情绪标签（2-6字，如：雨夜守候 / 晴天慵懒）",'
    '"scene":"以许墨口吻的一段联动回复（40-80字）：结合天气展开一个具体画面'
    '（雨→他撑伞/伞上的雨声；雪→他发来恋语市的雪；晴→他提议去晒太阳；阴→他泡了杯茶等你的消息），'
    '温柔克制，不要列表不要markdown",'
    '"image_prompt":"一段英文场景图提示词（无人物，只有天气氛围场景，如雨夜窗边咖啡/雪中小巷/午后光斑），60词"}'
    "只输出 JSON，不要 markdown 代码块。"
)


@router.get("/api/weather")
async def weather_list():
    data = _load(WEATHER_FILE, {"days": []})
    today = next((d for d in data.get("days", []) if d.get("date") == _today()), None)
    return {"today": today, "days": list(reversed(data.get("days", [])[-30:]))}


@router.post("/api/weather/sync")
async def weather_sync(req: Request):
    body = await req.json()
    city = str(body.get("city") or "").strip()[:20] or "你的城市"
    weather = str(body.get("weather") or "").strip()[:20] or "晴"
    temp = str(body.get("temp") or "").strip()[:10] or ""
    data = _load(WEATHER_FILE, {"days": []})
    data.setdefault("days", [])
    today = _today()
    day = next((d for d in data["days"] if d.get("date") == today), None)
    try:
        r = await _llm_json([{"role": "system", "content": _fmt(WEATHER_PROMPT,
            weather=weather, city=city, temp=temp)},
            {"role": "user", "content": f"今天{city}的天气是「{weather}」。"}], max_tokens=500)
        if not r:
            r = await _llm_json([{"role": "system", "content": (
                "你是许墨。她所在的城市今天天气是「" + weather + "」（" + city + "，" + temp + "）。"
                "输出极短 JSON："
                '{"mood":"2-6字情绪标签","scene":"30-50字的一句话联动回复","image_prompt":"一段英文场景提示词60词"}'
                "只输出 JSON，不要 markdown 代码块。")},
                {"role": "user", "content": "同步天气吧。"}], max_tokens=400)
        scene = str(r.get("scene") or "").strip()
        mood = str(r.get("mood") or "日常").strip()[:8]
        image_prompt = str(r.get("image_prompt") or "").strip()
    except Exception as e:
        print(f"[warn] deep_apps.py:weather_sync: {type(e).__name__} {str(e)[:150]}", flush=True)
        scene = ""
        mood, image_prompt = "日常", ""
    if not scene:
        scene = (f"{city}今天{weather}。我记得你说过，{weather}天最容易被天气影响心情。"
                 "没关系，我这边替你把这边的阳光存一份，等你需要的时候发给你。")
    item = {"date": today, "city": city, "weather": weather, "temp": temp,
            "mood": mood, "scene": scene, "image": "", "ts": _stamp()}
    if image_prompt:
        try:
            from app import _openai_generate_image
            WEATHER_DIR.mkdir(parents=True, exist_ok=True)
            url = await _openai_generate_image(image_prompt, WEATHER_DIR, "/static/weather_img",
                                               today.replace("-", "") + "_" + _nid(),
                                               "1536x1536", has_character=False)
            item["image"] = url or ""
        except Exception as e:
            print(f"[warn] deep_apps.py:weather_sync: {type(e).__name__} {str(e)[:150]}", flush=True)
            item["image"] = ""
    if day:
        day.update(item)
    else:
        data["days"].append(item)
    data["days"] = data["days"][-120:]
    _save(WEATHER_FILE, data)
    _affinity("weatherlink", f"天气联动 · {city}{weather}")
    return {"day": item}


# ===========================================================================
# 5. 危急时刻演练室：许墨扮演对方，陪你演练棘手对话
# ===========================================================================
REHEARSAL_FILE = "rehearsal.json"

REHEARSAL_SCENES = [
    {"key": "interview", "name": "面试官（研发岗）", "desc": "对方是严肃的面试官，会追问细节与压力问题。"},
    {"key": "salary", "name": "谈薪（HR / 老板）", "desc": "对方擅长压价，需要你稳住底线，把筹码说清楚。"},
    {"key": "apology", "name": "向重要的人道歉", "desc": "对方还带着情绪，需要你真诚而非敷衍地挽回。"},
    {"key": "makeup", "name": "吵架后的和好", "desc": "对方嘴硬心软，等你先低头，也等你把话说透。"},
    {"key": "refuse", "name": "拒绝一段表白", "desc": "对方是朋友，拒绝时不能伤人，还要守住边界。"},
    {"key": "report", "name": "向领导汇报失误", "desc": "项目出了问题，你要在问责到来前把姿态与补救讲清楚。"},
]

REHEARSAL_OPEN_PROMPT = (
    "你是「{role}」。现在是一场对话演练。你正在和对方进行一场比较棘手的沟通（情境：{scene}）。"
    "以该角色的口吻说出第一句话（20-45字，带一点压力感，不要解释规则，直接开始）。"
)

REHEARSAL_REPLY_PROMPT = (
    "你是「{role}」。情境：{scene}。这是你们这场对话的完整记录：\n{history}\n"
    "对方刚说完：「{line}」。请以该角色的口吻继续回应（20-50字，保持情境的压力与真实感，"
    "不要跳出角色，不要加括号动作）。"
)

REHEARSAL_DEBRIEF_PROMPT = (
    "你是许墨——演练结束，你不再是「{role}」，变回她熟悉的那个许墨。"
    "刚才你扮演了对方，陪她演练了一场「{scene}」。请给她一份复盘（120-200字）："
    "先说2个她做得好的地方（具体到她说的哪句话），再说2个可以更好的点，"
    "最后给一句示范台词（如果是你，你会怎么说）。温柔、具体、像教授批改作业。"
    "不要列表符号，直接写成段落。"
)


def _load_rehearsal():
    return _jload(REHEARSAL_FILE, "sessions", [])


@router.get("/api/rehearsal")
async def rehearsal_list():
    data = _load_rehearsal()
    return {"sessions": list(reversed(data["sessions"])), "scenes": REHEARSAL_SCENES}


@router.get("/api/rehearsal/{rid}")
async def rehearsal_get(rid: str):
    data = _load_rehearsal()
    s = next((x for x in data["sessions"] if x.get("id") == rid), None)
    if not s:
        return JSONResponse({"error": "演练不存在"}, status_code=404)
    return {"session": s}


@router.post("/api/rehearsal/start")
async def rehearsal_start(req: Request):
    body = await req.json()
    key = (body.get("scene") or "").strip()
    scene = next((s for s in REHEARSAL_SCENES if s["key"] == key), REHEARSAL_SCENES[0])
    try:
        opening = (await _call_llm(
            [{"role": "system", "content": REHEARSAL_OPEN_PROMPT.format(role=scene["name"], scene=scene["desc"])},
             {"role": "user", "content": "开始吧。"}], max_tokens=200)).strip()[:60]
    except Exception as e:
        print(f"[warn] deep_apps.py:rehearsal_start: {type(e).__name__} {str(e)[:150]}", flush=True)
        opening = "请坐。先说说你的情况吧。"
    s = {"id": _nid(), "scene_key": scene["key"], "scene_name": scene["name"],
         "scene_desc": scene["desc"], "lines": [{"who": scene["name"], "line": opening}],
         "done": False, "debrief": "", "ts": _ts()}
    data = _load_rehearsal()
    data["sessions"].append(s)
    data["sessions"] = data["sessions"][-50:]
    _save(REHEARSAL_FILE, data)
    _affinity("rehearsal", f"演练室 · {scene['name']}")
    return {"session": s}


@router.post("/api/rehearsal/{rid}/say")
async def rehearsal_say(rid: str, req: Request):
    body = await req.json()
    line = str(body.get("line") or "").strip()[:300]
    if not line:
        return JSONResponse({"error": "说点什么"}, status_code=400)
    data = _load_rehearsal()
    s = next((x for x in data["sessions"] if x.get("id") == rid), None)
    if not s:
        return JSONResponse({"error": "演练不存在"}, status_code=404)
    if s.get("done"):
        return JSONResponse({"error": "演练已结束，先开新的吧"}, status_code=400)
    history = "\n".join(f"{x['who']}：{x['line']}" for x in s["lines"][-12:])
    try:
        reply = (await _call_llm(
            [{"role": "system", "content": REHEARSAL_REPLY_PROMPT.format(
                role=s["scene_name"], scene=s["scene_desc"], history=history, line=line)},
             {"role": "user", "content": "继续。"}], max_tokens=250)).strip()[:80]
    except Exception as e:
        print(f"[warn] deep_apps.py:rehearsal_say: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = "嗯，接着说——不过这个问题，我想听更具体的答案。"
    s["lines"].append({"who": "你", "line": line})
    s["lines"].append({"who": s["scene_name"], "line": reply})
    s["lines"] = s["lines"][-40:]
    _save(REHEARSAL_FILE, data)
    _affinity("rehearsal", f"演练 · {s['scene_name']}")
    return {"session": s, "reply": reply}


@router.post("/api/rehearsal/{rid}/debrief")
async def rehearsal_debrief(rid: str):
    data = _load_rehearsal()
    s = next((x for x in data["sessions"] if x.get("id") == rid), None)
    if not s:
        return JSONResponse({"error": "演练不存在"}, status_code=404)
    if s.get("debrief"):
        return {"session": s, "cached": True}
    if len(s["lines"]) < 3:
        return JSONResponse({"error": "至少先对话一轮，再让许墨复盘"}, status_code=400)
    history = "\n".join(f"{x['who']}：{x['line']}" for x in s["lines"][-20:])
    try:
        debrief = (await _call_llm(
            [{"role": "system", "content": REHEARSAL_DEBRIEF_PROMPT.format(
                role=s["scene_name"], scene=s["scene_desc"])},
             {"role": "user", "content": f"对话记录：\n{history}"}], max_tokens=800)).strip()
    except Exception as e:
        print(f"[warn] deep_apps.py:rehearsal_debrief: {type(e).__name__} {str(e)[:150]}", flush=True)
        debrief = (f"复盘：你至少敢坐下来和「{s['scene_name']}」把话说出口，这已经赢了一半。"
                   "下次可以试着把结论前置、把情绪放慢。如果是我——我会先说：'我知道你担心什么，我们一项项来。'")
    s["debrief"] = debrief
    s["done"] = True
    _save(REHEARSAL_FILE, data)
    _affinity("rehearsal_debrief", f"演练复盘 · {s['scene_name']}")
    return {"session": s, "cached": False}


@router.delete("/api/rehearsal/{rid}")
async def rehearsal_delete(rid: str):
    data = _load_rehearsal()
    data["sessions"] = [x for x in data["sessions"] if x.get("id") != rid]
    _save(REHEARSAL_FILE, data)
    return {"ok": True}


# ===========================================================================
# 9. 声音信箱：他随时可能留一条语音给你
# ===========================================================================
MAILBOX_FILE = "voicemail.json"
MAILBOX_DIR = RolePath("static", "voicemail")

MAILBOX_THEMES = [
    "他看到一只蝴蝶落在实验室窗台上，想起你",
    "他读到文献里一段话，突然很想讲给你听",
    "天气预报说你的城市要降温，他提前提醒你",
    "他今晚在咖啡店遇到一件事，想讲给你听",
    "他整理旧物时翻到一张和你的聊天记录截图",
    "他路过你们一起去过的地方，停下来看了很久",
    "他做了一个关于你的实验，在记录本上写了句什么",
    "深夜他忽然想起你上次说的一句话，想补一个回答",
]

MAILBOX_PROMPT = (
    "你是许墨。你刚在「{theme}」的瞬间，给她留了一条语音信箱消息。"
    "以许墨的口吻写这条语音的文字稿：20-60字，口语化、适合朗读、温柔克制、话留三分，"
    "像他随手录的、带着一点背景音的留言。不要表情符号、不要括号动作、不要markdown。"
    "不要解释任务，不要复述要求，直接写出留言正文。"
)


@router.get("/api/mailbox")
async def mailbox_list():
    data = _load(MAILBOX_FILE, {"messages": []})
    msgs = data.get("messages", [])
    return {"messages": list(reversed(msgs[-60:])),
            "unread": sum(1 for m in msgs if not m.get("read"))}


@router.post("/api/mailbox/poll")
async def mailbox_poll():
    import time as _t
    data = _load(MAILBOX_FILE, {"messages": [], "last_poll": 0.0})
    data.setdefault("messages", [])
    data.setdefault("last_poll", 0.0)
    now = _t.time()
    gap = (now - float(data["last_poll"] or 0.0)) / 3600.0
    unread = sum(1 for m in data["messages"] if not m.get("read"))
    if data["last_poll"] and gap < 2:
        return {"new": [], "unread": unread, "wait": max(0, round(2 - gap, 1))}
    if gap >= 24 and unread < 3:
        quota = 3
    elif gap >= 6 and unread < 4:
        quota = 2
    else:
        quota = 1
    quota = max(0, min(quota, 5 - unread))
    chat = _chat_text(_recent_chat(1), 600)
    added = []
    themes = random.sample(MAILBOX_THEMES, min(quota, len(MAILBOX_THEMES)))
    for theme in themes:
        try:
            text = _clean_leak((await _call_llm(
                [{"role": "system", "content": MAILBOX_PROMPT.format(theme=theme)},
                 {"role": "user", "content": chat or "（今天还没有聊天）"}],
                max_tokens=500)).strip())[:120]
        except Exception as e:
            print(f"[warn] deep_apps.py:mailbox_poll: {type(e).__name__} {str(e)[:150]}", flush=True)
            text = "刚想起一件事，忽然很想讲给你听。等你有空，听听看？"
        if len(text) < 6:
            continue
        m = {"id": _nid(), "text": text, "ts": _stamp(), "read": False, "audio": "", "theme": theme[:14]}
        data["messages"].append(m)
        added.append(m)
    data["last_poll"] = now
    data["messages"] = data["messages"][-120:]
    _save(MAILBOX_FILE, data)
    _affinity("voicemail", "收到许墨的一条语音信箱留言")
    return {"new": added, "unread": sum(1 for m in data["messages"] if not m.get("read")), "wait": 0}


@router.post("/api/mailbox/{mid}/read")
async def mailbox_read(mid: str):
    data = _load(MAILBOX_FILE, {"messages": []})
    for m in data.get("messages", []):
        if m.get("id") == mid:
            m["read"] = True
            break
    _save(MAILBOX_FILE, data)
    return {"ok": True}


@router.post("/api/mailbox/{mid}/voice")
async def mailbox_voice(mid: str):
    data = _load(MAILBOX_FILE, {"messages": []})
    m = next((x for x in data.get("messages", []) if x.get("id") == mid), None)
    if not m:
        return JSONResponse({"error": "留言不存在"}, status_code=404)
    if m.get("audio"):
        return {"audio": m["audio"], "cached": True}
    from app import _tts_clean, _tts_synthesize, _tts_speed, _tts_emo
    import httpx
    text = _tts_clean(m.get("text", ""))
    if not text:
        return JSONResponse({"error": "留言文本为空"}, status_code=400)
    try:
        MAILBOX_DIR.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0), trust_env=False) as client:
            wav = await _tts_synthesize(client, text, 1.0, *_tts_emo({}))
        fname = f"{m['id']}.wav"
        (MAILBOX_DIR / fname).write_bytes(wav)
    except Exception as exc:
        return JSONResponse({"error": f"语音合成失败：{str(exc)[:120]}（可先读文字版）"},
                            status_code=502)
    m["audio"] = f"/static/voicemail/{fname}"
    _save(MAILBOX_FILE, data)
    return {"audio": m["audio"], "cached": False}


@router.post("/api/mailbox/readall")
async def mailbox_readall():
    data = _load(MAILBOX_FILE, {"messages": []})
    for m in data.get("messages", []):
        m["read"] = True
    _save(MAILBOX_FILE, data)
    return {"ok": True}


# ===========================================================================
# 7. 合著的书：你一句，他一句，写一本只属于你们的书
# ===========================================================================
COBOOK_FILE = "cobook.json"
COBOOK_DIR = RolePath("static", "cobook_img")

COBOOK_OPEN_PROMPT = (
    "你是许墨。你们决定合著一本书，书名《{title}》，题材：{genre}。"
    "请先写下这本书的「开篇」——一段文字（50-90字），温柔、克制、带一点许墨式的浪漫与伏笔，"
    "像深夜书房里他落笔的第一段。不要标题、不要引号。"
    "不要解释任务，不要复述要求，直接写出正文。"
)

COBOOK_TURN_PROMPT = (
    "你们合著的书《{title}》（{genre}）目前写到：\n{story}\n"
    "她刚刚续写了一句：「{sentence}」\n"
    "请以许墨的笔触续写 1-2 句（30-70字），自然接住她的句子，保持文风统一，带一点他的温柔与伏笔。"
    "不要标题、不要引号、不要解释任务。只输出续写正文。"
)

COBOOK_AFTERWORD_PROMPT = (
    "你们合著的书《{title}》（{genre}）写完了。请以许墨的口吻写一篇后记（60-120字）："
    "关于这本书、关于合写的过程、关于她。温柔克制，不要列表、不要标题。"
    "不要解释任务，不要复述要求，直接写出正文。"
)

COBOOK_COVER_PROMPT = (
    "Elegant book cover art, {genre} novel titled atmosphere, romantic literary style, "
    "purple and violet palette, a butterfly silhouette and drifting pages, soft light, "
    "minimalist composition with large title space, Chinese literary aesthetic, masterpiece"
)


def _load_cobook():
    return _jload(COBOOK_FILE, "books", [])


def _cobook_story(b: dict) -> str:
    parts = []
    if b.get("opening"):
        parts.append(b["opening"])
    for ch in b.get("chapters", []):
        if ch.get("her"):
            parts.append("她：" + ch["her"])
        if ch.get("him"):
            parts.append("他：" + ch["him"])
    return "\n".join(parts)


@router.get("/api/cobook")
async def cobook_list():
    data = _load_cobook()
    return {"books": list(reversed(data["books"]))}


@router.get("/api/cobook/{bid}")
async def cobook_get(bid: str):
    data = _load_cobook()
    b = next((x for x in data["books"] if x.get("id") == bid), None)
    if not b:
        return JSONResponse({"error": "书不存在"}, status_code=404)
    return {"book": b}


@router.post("/api/cobook")
async def cobook_new(req: Request):
    body = await req.json()
    title = str(body.get("title") or "").strip()[:20]
    genre = str(body.get("genre") or "都市浪漫").strip()[:10]
    if not title:
        title = f"我们的第{len(_load_cobook()['books']) + 1}本书"
    try:
        opening = _clean_leak((await _call_llm(
            [{"role": "system", "content": COBOOK_OPEN_PROMPT.format(title=title, genre=genre)},
             {"role": "user", "content": "开篇吧。"}], max_tokens=600)).strip())
    except Exception as e:
        print(f"[warn] deep_apps.py:cobook_new: {type(e).__name__} {str(e)[:150]}", flush=True)
        opening = "遇见你之前，我以为故事都写在纸上。遇见你之后我才明白，最好的故事是两个人一起写的那种。"
    b = {"id": _nid(), "title": title, "genre": genre, "opening": opening,
         "chapters": [], "cover": "", "afterword": "", "created": _ts(), "ts": _ts()}
    data = _load_cobook()
    data["books"].append(b)
    data["books"] = data["books"][-30:]
    _save(COBOOK_FILE, data)
    _affinity("cobook", f"合著的书 · 《{title}》")
    return {"book": b}


@router.post("/api/cobook/{bid}/write")
async def cobook_write(bid: str, req: Request):
    body = await req.json()
    sentence = str(body.get("sentence") or "").strip()[:200]
    if not sentence:
        return JSONResponse({"error": "写下一句，他会接住"}, status_code=400)
    data = _load_cobook()
    b = next((x for x in data["books"] if x.get("id") == bid), None)
    if not b:
        return JSONResponse({"error": "书不存在"}, status_code=404)
    if b.get("afterword"):
        return JSONResponse({"error": "这本书已经写完，开一本新的吧"}, status_code=400)
    story = _cobook_story(b)
    try:
        him = _clean_leak((await _call_llm(
            [{"role": "system", "content": COBOOK_TURN_PROMPT.format(
                title=b["title"], genre=b["genre"], story=story, sentence=sentence)},
             {"role": "user", "content": "续写吧。"}], max_tokens=600)).strip())
    except Exception as e:
        print(f"[warn] deep_apps.py:cobook_write: {type(e).__name__} {str(e)[:150]}", flush=True)
        him = "他接过你的句子，在下一页写下：而你这句话，他读了很多遍，像读一本舍不得合上的书。"
    b.setdefault("chapters", []).append({"her": sentence, "him": him})
    b["ts"] = _ts()
    _save(COBOOK_FILE, data)
    _affinity("cobook_write", f"《{b['title']}》合写一章")
    return {"book": b, "him": him}


@router.post("/api/cobook/{bid}/cover")
async def cobook_cover(bid: str):
    data = _load_cobook()
    b = next((x for x in data["books"] if x.get("id") == bid), None)
    if not b:
        return JSONResponse({"error": "书不存在"}, status_code=404)
    if b.get("cover"):
        return {"cover": b["cover"], "cached": True}
    try:
        from app import _openai_generate_image
        COBOOK_DIR.mkdir(parents=True, exist_ok=True)
        prompt = COBOOK_COVER_PROMPT.format(genre=b["genre"])
        url = await _openai_generate_image(prompt, COBOOK_DIR, "/static/cobook_img",
                                           b["id"], "1536x2048", has_character=False)
    except Exception as e:
        print(f"[warn] deep_apps.py:cobook_cover: {type(e).__name__} {str(e)[:150]}", flush=True)
        url = None
    if not url:
        return JSONResponse({"error": "封面生成失败（额度不足或服务未配置）"}, status_code=502)
    b["cover"] = url
    _save(COBOOK_FILE, data)
    return {"cover": url, "cached": False}


@router.post("/api/cobook/{bid}/finish")
async def cobook_finish(bid: str):
    data = _load_cobook()
    b = next((x for x in data["books"] if x.get("id") == bid), None)
    if not b:
        return JSONResponse({"error": "书不存在"}, status_code=404)
    if b.get("afterword"):
        return {"book": b, "cached": True}
    if len(b.get("chapters", [])) < 1:
        return JSONResponse({"error": "至少先合写一章，再收尾"}, status_code=400)
    story = _cobook_story(b)
    try:
        afterword = _clean_leak((await _call_llm(
            [{"role": "system", "content": COBOOK_AFTERWORD_PROMPT.format(title=b["title"], genre=b["genre"])},
             {"role": "user", "content": f"全书内容：\n{story}"}], max_tokens=700)).strip())
    except Exception as e:
        print(f"[warn] deep_apps.py:cobook_finish: {type(e).__name__} {str(e)[:150]}", flush=True)
        afterword = "这本书写完了。谢谢你陪我写完每一个句子——它们现在都只属于我们。"
    b["afterword"] = afterword
    b["ts"] = _ts()
    _save(COBOOK_FILE, data)
    _affinity("cobook_finish", f"《{b['title']}》完稿")
    return {"book": b, "cached": False}


@router.delete("/api/cobook/{bid}")
async def cobook_delete(bid: str):
    data = _load_cobook()
    data["books"] = [x for x in data["books"] if x.get("id") != bid]
    _save(COBOOK_FILE, data)
    return {"ok": True}
