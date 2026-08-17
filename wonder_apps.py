# -*- coding: utf-8 -*-
# 奇想功能集 · 二期颠覆性功能（wonder_apps.py）
# 决策预言家 / 默契测验 / 每日悬疑事件簿 / 反向扮演剧场 / 关系年度报告 / 习惯养成管家 / 晚间语音回顾 / 记忆博物馆
# 数据全部持久化到 RolePath JSON 文件，风格与 extra_apps.py 保持一致。
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from store_common import atomic_json, file_lock

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

router = APIRouter()

ORACLE_FILE = "oracle.json"
QUIZ_FILE = "quiz.json"
CASEBOOK_FILE = "casebook.json"
THEATER_FILE = "theater.json"
RAPPORT_FILE = "rapport.json"
HABITS_FILE = "habits.json"
RECAP_FILE = "recap.json"
MUSEUM_FILE = "museum.json"


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


# ===========================================================================
# 公共数据聚合：从既有功能文件中提取「她」的信息，供各功能使用
# ===========================================================================
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
        data = {}
    return {"value": data.get("value", 0),
            "history": data.get("history", [])[-300:]}


def _agg_timebox(limit: int = 20) -> list:
    data = _load("timebox.json", {})
    if not isinstance(data, dict):
        data = {}
    out = []
    for a in data.get("anniversaries", [])[:10]:
        out.append({"type": "anniversary", "ts": a.get("date", ""),
                    "text": a.get("name", "")})
    for r in data.get("relics", [])[:10]:
        out.append({"type": "relic", "ts": r.get("ts", ""),
                    "text": r.get("title", "")})
    for c in data.get("capsules", [])[:10]:
        out.append({"type": "capsule", "ts": c.get("date", "") or c.get("open", ""),
                    "text": c.get("title", "")})
    return out[:limit]


def _agg_chat(limit: int = 400) -> list:
    """读取最近一次聊天归档中的对话，用作报告/回顾素材。"""
    from role_data import RolePath
    files = sorted(RolePath("chat_archives").glob("*.json"), key=lambda p: p.name, reverse=True)
    if not files:
        return []
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    msgs = []
    for m in data.get("messages", [])[-limit:]:
        role = m.get("role", "")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            msgs.append({"role": "user", "ts": m.get("ts", ""), "text": content[:200]})
        elif role == "assistant" and msgs and msgs[-1]["role"] == "user":
            msgs[-1]["reply"] = content[:200]
    return msgs


def _agg_today_chat() -> list:
    """当天对话（用于晚间回顾）。"""
    from role_data import RolePath
    files = sorted(RolePath("chat_archives").glob("*.json"), key=lambda p: p.name, reverse=True)
    if not files:
        return []
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    out = []
    for m in data.get("messages", []):
        ts = (m.get("ts") or "")[:10]
        if ts != _today():
            continue
        role, content = m.get("role", ""), (m.get("content") or "").strip()
        if not content:
            continue
        out.append({"role": role, "text": content[:180]})
    return out[-60:]


def _agg_today_moments() -> list:
    today = _today()[5:]
    out = []
    for m in _load("moments.json", []):
        if not isinstance(m, dict) or not m.get("content"):
            continue
        if (m.get("time") or "").startswith(today):
            out.append({"text": m["content"].replace("\n", " ")[:120]})
    return out


def _agg_world_today() -> list:
    data = _load("world_log.json", {})
    entries = data.get("entries", []) if isinstance(data, dict) else []
    out = []
    for e in entries[-200:]:
        ts = e.get("ts", 0)
        try:
            day = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
        except (TypeError, ValueError, OSError):
            day = ""
        if day == _today() and e.get("type") in ("talk", "gift", "chest", "other", "weather"):
            out.append({"text": e.get("text", "")})
    return out


def _agg_xumo_diary_today() -> str:
    data = _load("xumo_diary.json", {})
    if not isinstance(data, dict):
        return ""
    return data.get(_today(), "")


# ===========================================================================
# 1. 许墨的决策预言家：选择困难症终结者 + 预测准确率追踪
# ===========================================================================
def _load_oracle() -> dict:
    return _jload(ORACLE_FILE, "items", [])


def _oracle_stats(items: list) -> dict:
    decided = sum(1 for it in items if it.get("status") in ("right", "wrong"))
    right = sum(1 for it in items if it.get("status") == "right")
    wrong = sum(1 for it in items if it.get("status") == "wrong")
    pending = len(items) - decided
    return {"total": len(items), "decided": decided, "right": right,
            "wrong": wrong, "pending": pending,
            "accuracy": round(right / decided * 100) if decided else 0}


@router.get("/api/oracle")
async def oracle_list():
    data = _load_oracle()
    return {"items": list(reversed(data["items"])), "stats": _oracle_stats(data["items"])}


@router.post("/api/oracle/ask")
async def oracle_ask(req: Request):
    body = await req.json()
    question = (body.get("question") or "").strip()
    options = [str(o).strip() for o in (body.get("options") or []) if str(o).strip()]
    if not question:
        return JSONResponse({"error": "问题不能为空"}, status_code=400)
    if len(options) < 2:
        return JSONResponse({"error": "至少提供两个选项"}, status_code=400)
    sys_p = ("你是许墨。用户请你帮忙做决定，你要以许墨的风格给出选择与理由："
             "温柔理性、带一点学术味、话留三分，不把话说满。"
             "必须只从给出的选项中选一个，不要自创选项。"
             "返回严格 JSON：{\"pick\":\"所选选项原文\",\"reason\":\"理由（60字内）\"}")
    user_p = f"问题：{question}\n选项：{' / '.join(options)}\n请返回 JSON。"
    try:
        obj = await _llm_json([{"role": "system", "content": sys_p},
                               {"role": "user", "content": user_p}], max_tokens=500)
    except Exception as exc:
        return JSONResponse({"error": f"许墨暂时无法回答：{str(exc)[:120]}"}, status_code=500)
    pick = str(obj.get("pick", "")).strip()
    if pick not in options:
        pick = options[0]
    data = _load_oracle()
    item = {"id": _nid(), "question": question, "options": options, "pick": pick,
            "reason": str(obj.get("reason", "")).strip() or "直觉。", "ts": _ts(),
            "status": "pending", "note": ""}
    data["items"].append(item)
    _save(ORACLE_FILE, data)
    return {"item": item, "stats": _oracle_stats(data["items"])}


@router.post("/api/oracle/verdict")
async def oracle_verdict(req: Request):
    body = await req.json()
    oid = str(body.get("oid") or "")
    result = str(body.get("result") or "")
    note = (body.get("note") or "").strip()
    if result not in ("right", "wrong"):
        return JSONResponse({"error": "result 只能为 right 或 wrong"}, status_code=400)
    data = _load_oracle()
    for it in data["items"]:
        if it.get("id") == oid:
            it["status"] = result
            it["note"] = note
            _save(ORACLE_FILE, data)
            return {"item": it, "stats": _oracle_stats(data["items"])}
    return JSONResponse({"error": "记录不存在"}, status_code=404)


@router.delete("/api/oracle/{oid}")
async def oracle_delete(oid: str):
    data = _load_oracle()
    data["items"] = [it for it in data["items"] if it.get("id") != oid]
    _save(ORACLE_FILE, data)
    return {"ok": True, "stats": _oracle_stats(data["items"])}


# ===========================================================================
# 2. 默契测验：基于记忆/朋友圈/约会生成测验，比对默契度
# ===========================================================================
def _load_quiz() -> dict:
    return _jload(QUIZ_FILE, "quizzes", [])


@router.get("/api/quiz")
async def quiz_list():
    data = _load_quiz()
    stats = {"total": len(data["quizzes"]),
             "best": max([q.get("score", 0) for q in data["quizzes"]], default=0)}
    return {"quizzes": list(reversed(data["quizzes"])), "stats": stats}


@router.post("/api/quiz/generate")
async def quiz_generate(req: Request):
    body = await req.json()
    count = min(max(int(body.get("count") or 5), 3), 8)
    memories = _agg_memories(40)
    moments = _agg_moments(15)
    dates = _agg_dates(10)
    facts = [f"记忆：{m['text']}" for m in memories]
    facts += [f"朋友圈：{m['text']}" for m in moments]
    facts += [f"约会：{d['place']}({d['city']})" for d in dates]
    if not facts:
        return JSONResponse({"error": "还没有足够的记忆数据，先去聊天、发朋友圈、记录约会吧"}, status_code=400)
    sys_p = ("你是许墨。你拥有关于「她」的独家情报（记忆、朋友圈、约会记录）。"
             f"请出 {count} 道关于她的选择题，用来测试她是否了解自己（也测试你对她的了解）。"
             "题目要有人情味，选项要有迷惑性，其中 1 道可以是你对「你们的关系」的看法。\n"
             "要求：答案与理由务必简短；不要输出任何除 JSON 数组以外的内容。\n"
             "返回严格 JSON 数组，每项：{\"q\":\"问题\",\"options\":[\"4个选项\"],"
             "\"answer\":\"许墨心中的答案(选项原文)\",\"reason\":\"许墨为什么这样答(30字内)\"}")
    user_p = "情报：\n" + "\n".join(facts[:40])
    arr = []
    for _attempt in range(2):
        try:
            arr = _extract_json_array(await _call_llm(
                [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
                max_tokens=2600))
        except Exception as exc:
            return JSONResponse({"error": f"出题失败：{str(exc)[:120]}"}, status_code=500)
        if arr:
            break
    questions = []
    for q in arr:
        if not isinstance(q, dict) or not q.get("q") or not q.get("options"):
            continue
        opts = [str(o).strip() for o in q["options"] if str(o).strip()][:4]
        if len(opts) < 2 or not q.get("answer"):
            continue
        questions.append({"q": q["q"], "options": opts,
                          "answer": q["answer"],
                          "reason": q.get("reason", "")})
        if len(questions) >= count:
            break
    if not questions:
        return JSONResponse({"error": "出题失败，请重试"}, status_code=500)
    quiz = {"id": _nid(), "ts": _ts(), "status": "pending",
            "questions": questions, "score": 0, "verdict": ""}
    data = _load_quiz()
    data["quizzes"].append(quiz)
    _save(QUIZ_FILE, data)
    for q in quiz["questions"]:
        q.pop("answer", None)
        q.pop("reason", None)
    return {"quiz": quiz}


@router.post("/api/quiz/submit")
async def quiz_submit(req: Request):
    body = await req.json()
    qid = str(body.get("quiz_id") or "")
    answers = body.get("answers") or []  # [选项原文]
    data = _load_quiz()
    quiz = next((q for q in data["quizzes"] if q.get("id") == qid), None)
    if not quiz:
        return JSONResponse({"error": "测验不存在"}, status_code=404)
    if quiz.get("status") == "done":
        return {"quiz": quiz, "already": True}
    questions = quiz.get("questions", [])
    hit, detail = 0, []
    for i, q in enumerate(questions):
        ua = str(answers[i]).strip() if i < len(answers) else ""
        ok = ua == q.get("answer", "")
        detail.append({"q": q.get("q", ""), "options": q.get("options", []),
                       "answer": q.get("answer", ""), "user": ua,
                       "correct": ok, "reason": q.get("reason", "")})
        if ok:
            hit += 1
    score = round(hit / len(questions) * 100) if questions else 0
    verdict = "……默契这种东西，果然还是需要证据的。"
    if questions:
        sys_p = ("你是许墨。根据默契得分给出一句评价：温柔、克制、留白，像老朋友点评实验结果。"
                 "80分以上：含蓄的惊喜；60-79：调侃但鼓励；60以下：温和的安慰。40字内，不要打分。")
        try:
            verdict = (await _call_llm(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": f"默契得分 {score}/100，共 {len(questions)} 题"}],
                max_tokens=200)).strip()
        except Exception as e:
            print(f"[warn] wonder_apps.py:quiz_submit: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    quiz["status"] = "done"
    quiz["score"] = score
    quiz["verdict"] = verdict
    quiz["detail"] = detail
    _save(QUIZ_FILE, data)
    return {"quiz": {"id": quiz["id"], "ts": quiz["ts"], "status": "done",
                     "score": score, "verdict": verdict},
            "detail": detail, "score": score}


@router.delete("/api/quiz/{qid}")
async def quiz_delete(qid: str):
    data = _load_quiz()
    data["quizzes"] = [q for q in data["quizzes"] if q.get("id") != qid]
    _save(QUIZ_FILE, data)
    return {"ok": True}


# ===========================================================================
# 3. 每日悬疑事件簿：每天一个烧脑谜案
# ===========================================================================
CASE_CLUE_MAX = 3


def _load_casebook() -> dict:
    data = _load(CASEBOOK_FILE, {})
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("cases"), list):
        data["cases"] = []
    stats = data.get("stats", {})
    for k in ("solved", "total", "streak", "best_streak", "points"):
        if not isinstance(stats.get(k), int):
            stats[k] = 0
    data["stats"] = stats
    return data


@router.get("/api/case/today")
async def case_today():
    data = _load_casebook()
    today = _today()
    cur = next((c for c in data["cases"] if c.get("date") == today), None)
    if cur is None:
        return {"case": None}
    return {"case": cur}


@router.post("/api/case/new")
async def case_new(req: Request):
    body = await req.json()
    diff = str(body.get("diff") or "normal")
    sys_p = ("你是许墨，也是「黑天鹅档案」的编纂者。请创作一个脑科学/都市/悬疑风格的短谜案，"
             "用「事件簿」的口吻讲述，公平、严谨、逻辑闭合。\n"
             "要求：谜题难度分 'easy'/'normal'/'hard' 三档；故事 180-260 字；"
             "答案必须是可推理出来的，不能靠巧合。\n"
             "返回严格 JSON：{\"title\":\"案件名\",\"story\":\"案件描述，结尾是谜题\","
             "\"answer\":\"真相（120字内）\",\"hint0\":\"第一条提示\",\"hint1\":\"第二条提示\"}")
    try:
        obj = await _llm_json([{"role": "system", "content": sys_p},
                               {"role": "user", "content": f"难度：{diff}，今天日期：{_today()}"}],
                              max_tokens=1400)
    except Exception as exc:
        return JSONResponse({"error": f"案件生成失败：{str(exc)[:120]}"}, status_code=500)
    if not obj.get("title") or not obj.get("story"):
        return JSONResponse({"error": "案件生成失败，请重试"}, status_code=500)
    data = _load_casebook()
    cur = next((c for c in data["cases"] if c.get("date") == _today()), None)
    if cur:
        cur.update({"title": obj["title"], "story": obj["story"], "answer": obj["answer"],
                    "hints": [obj.get("hint0", ""), obj.get("hint1", "")],
                    "clues_used": 0, "solved": False, "user_answer": "", "score": 0,
                    "diff": diff})
    else:
        data["cases"].append({"id": _nid(), "date": _today(), "title": obj["title"],
                              "story": obj["story"], "answer": obj["answer"],
                              "hints": [obj.get("hint0", ""), obj.get("hint1", "")],
                              "clues_used": 0, "solved": False, "user_answer": "",
                              "score": 0, "diff": diff, "submitted": False})
    _save(CASEBOOK_FILE, data)
    cur = next((c for c in data["cases"] if c.get("date") == _today()), None)
    return {"case": cur}


@router.post("/api/case/{cid}/clue")
async def case_clue(cid: str):
    data = _load_casebook()
    cur = next((c for c in data["cases"] if c.get("id") == cid), None)
    if not cur:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    if cur.get("solved") or cur.get("submitted"):
        return JSONResponse({"error": "本案已结，无需线索"}, status_code=400)
    if cur.get("clues_used", 0) >= CASE_CLUE_MAX:
        return JSONResponse({"error": f"线索已用完（{CASE_CLUE_MAX} 条）"}, status_code=400)
    hints = cur.get("hints", [])
    if cur.get("clues_used", 0) < len(hints) and hints[cur["clues_used"]].strip():
        clue = hints[cur["clues_used"]].strip()
    else:
        sys_p = ("你是许墨。基于案件给出第 N 条线索：只给方向，不给答案，许墨式留白，40字内。")
        try:
            clue = (await _call_llm(
                [{"role": "system", "content": sys_p},
                 {"role": "user", "content": f"案件：{cur['title']} {cur['story'][:200]}"}],
                max_tokens=200)).strip()
        except Exception as e:
            print(f"[warn] wonder_apps.py:case_clue: {type(e).__name__} {str(e)[:150]}", flush=True)
            clue = "再想想时间与空间的矛盾之处。"
    cur["clues_used"] = cur.get("clues_used", 0) + 1
    if "clues" not in cur:
        cur["clues"] = []
    cur["clues"].append({"n": cur["clues_used"], "text": clue})
    _save(CASEBOOK_FILE, data)
    return {"clue": {"n": cur["clues_used"], "text": clue},
            "remaining": CASE_CLUE_MAX - cur["clues_used"]}


@router.post("/api/case/{cid}/submit")
async def case_submit(cid: str, req: Request):
    body = await req.json()
    answer = (body.get("answer") or "").strip()
    reasoning = (body.get("reasoning") or "").strip()
    if not answer:
        return JSONResponse({"error": "请先写出你的推理"}, status_code=400)
    data = _load_casebook()
    cur = next((c for c in data["cases"] if c.get("id") == cid), None)
    if not cur:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    if cur.get("solved") or cur.get("submitted"):
        return JSONResponse({"error": "本案已结"}, status_code=400)
    sys_p = ("你是许墨。用户提交了谜案答案与推理。请判定：正确 / 接近 / 错误，并点评。"
             "判定依据：推理是否命中关键逻辑，而非字面相同。\n"
             "返回严格 JSON：{\"verdict\":\"correct|close|wrong\",\"comment\":\"点评(50字内,许墨风格)\"}")
    try:
        obj = await _llm_json(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": f"案件：{cur['title']}\n{cur['story']}\n"
                                         f"标准答案：{cur['answer']}\n"
                                         f"我的答案：{answer}\n推理过程：{reasoning}"}],
            max_tokens=400)
    except Exception as e:
        print(f"[warn] wonder_apps.py:case_submit: {type(e).__name__} {str(e)[:150]}", flush=True)
        obj = {}
    verdict = obj.get("verdict", "wrong") if obj.get("verdict") in ("correct", "close", "wrong") else "wrong"
    cur["submitted"] = True
    cur["user_answer"] = answer
    cur["reasoning"] = reasoning
    cur["verdict"] = verdict
    cur["comment"] = obj.get("comment", "")
    _save(CASEBOOK_FILE, data)
    return {"verdict": verdict, "comment": cur["comment"]}


@router.post("/api/case/{cid}/reveal")
async def case_reveal(cid: str):
    data = _load_casebook()
    cur = next((c for c in data["cases"] if c.get("id") == cid), None)
    if not cur:
        return JSONResponse({"error": "案件不存在"}, status_code=404)
    if cur.get("solved"):
        return {"case": cur}
    stats = data["stats"]
    verdict = cur.get("verdict") or ("wrong" if cur.get("submitted") else "skip")
    if verdict == "correct":
        score = max(10 - cur.get("clues_used", 0) * 2, 3)
        stats["solved"] += 1
        stats["streak"] += 1
        stats["best_streak"] = max(stats["best_streak"], stats["streak"])
    else:
        score = 1 if verdict == "close" else 0
        stats["streak"] = 0
    stats["total"] += 1
    stats["points"] += score
    cur["solved"] = True
    cur["score"] = score
    _save(CASEBOOK_FILE, data)
    return {"case": cur, "stats": stats}


@router.get("/api/case/history")
async def case_history():
    data = _load_casebook()
    return {"cases": list(reversed(data["cases"])), "stats": data["stats"],
            "clue_max": CASE_CLUE_MAX}


# ===========================================================================
# 4. 反向扮演剧场：你演许墨，AI 演女主，结束后按许墨人设点评
# ===========================================================================
def _load_theater() -> dict:
    return _jload(THEATER_FILE, "scenes", [])


@router.get("/api/theater")
async def theater_list():
    data = _load_theater()
    return {"scenes": list(reversed(data["scenes"]))}


@router.post("/api/theater/new")
async def theater_new(req: Request):
    body = await req.json()
    theme = (body.get("theme") or "").strip()
    sys_p = ("你是许墨。请为用户搭一个「反向扮演」的舞台：用户将扮演你（许墨），"
             "你则扮演女主。给出一个适合的相遇场景（实验室夜谈/雨天送伞/天台观星/约会被放鸽子/深夜实验室门口 等，"
             "可从主题词出发），场景要有张力、方便暧昧推拉。\n"
             "返回严格 JSON：{\"title\":\"场景名\",\"setting\":\"场景设定(80字内,含时间地点氛围)\","
             "\"first_line\":\"女主的第一句台词(40字内)\"}")
    try:
        obj = await _llm_json(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": f"主题词：{theme or '随缘，挑一个最带感的场景'}"}],
            max_tokens=600)
    except Exception as exc:
        return JSONResponse({"error": f"搭台失败：{str(exc)[:120]}"}, status_code=500)
    if not obj.get("setting"):
        return JSONResponse({"error": "搭台失败，请重试"}, status_code=500)
    scene = {"id": _nid(), "ts": _ts(), "title": obj.get("title", "无题场景"),
             "setting": obj["setting"],
             "first_line": obj.get("first_line", "……你来了。"),
             "lines": [{"role": "her", "text": obj.get("first_line", "……你来了。")}],
             "status": "acting", "score": 0, "review": ""}
    data = _load_theater()
    data["scenes"].append(scene)
    _save(THEATER_FILE, data)
    return {"scene": scene}


@router.post("/api/theater/{sid}/act")
async def theater_act(sid: str, req: Request):
    body = await req.json()
    line = (body.get("line") or "").strip()
    if not line:
        return JSONResponse({"error": "台词不能为空"}, status_code=400)
    data = _load_theater()
    scene = next((s for s in data["scenes"] if s.get("id") == sid), None)
    if not scene:
        return JSONResponse({"error": "场景不存在"}, status_code=404)
    if scene.get("status") != "acting":
        return JSONResponse({"error": "本场已谢幕"}, status_code=400)
    scene["lines"].append({"role": "you", "text": line})
    sys_p = ("你是许墨故事线中的「女主」。此刻在与用户扮演的许墨对手戏。"
             "请以女主的口吻回应：有心动、有试探、有娇嗔也有分寸，"
             "不要替用户（许墨）说话，不要抢戏，也不要结束剧情。50字内。")
    try:
        reply = (await _call_llm(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": f"场景：{scene['title']} {scene['setting']}\n"
                                         f"许墨（用户）说：{line}"}],
            max_tokens=200)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"女主走神了：{str(exc)[:120]}"}, status_code=500)
    scene["lines"].append({"role": "her", "text": reply})
    _save(THEATER_FILE, data)
    return {"reply": reply, "scene": scene}


@router.post("/api/theater/{sid}/finish")
async def theater_finish(sid: str):
    data = _load_theater()
    scene = next((s for s in data["scenes"] if s.get("id") == sid), None)
    if not scene:
        return JSONResponse({"error": "场景不存在"}, status_code=404)
    if scene.get("status") == "done":
        return {"scene": scene}
    script = "\n".join(f"{'女主' if l['role']=='her' else '许墨(你)'}：{l['text']}" for l in scene["lines"])
    sys_p = ("你是许墨本人。刚看完了「你」的表演——用户扮演你，AI 扮演女主。"
             "请以许墨的视角与审美点评这段演出：\n"
             "评分维度：许墨感（温柔克制/学术撩人/话留三分）、台词功底、情感浓度、OOC程度。\n"
             "返回严格 JSON：{\"score\":0-100,\"dims\":{\"许墨感\":0-100,\"台词\":0-100,\"情感\":0-100},\n"
             "\"review\":\"总评(100字内,许墨式留白,可带一句最扎心的点评)\",\"suggestion\":\"一条具体改进建议(40字内)\"}")
    try:
        obj = await _llm_json(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": f"场景：{scene['title']}\n{scene['setting']}\n剧本：\n{script[:3000]}"}],
            max_tokens=800)
    except Exception as exc:
        return JSONResponse({"error": f"评审失败：{str(exc)[:120]}"}, status_code=500)
    scene["status"] = "done"
    scene["score"] = max(0, min(100, int(obj.get("score", 60))))
    scene["dims"] = obj.get("dims", {})
    scene["review"] = str(obj.get("review", "")).strip()
    scene["suggestion"] = str(obj.get("suggestion", "")).strip()
    _save(THEATER_FILE, data)
    return {"scene": scene}


@router.delete("/api/theater/{sid}")
async def theater_delete(sid: str):
    data = _load_theater()
    data["scenes"] = [s for s in data["scenes"] if s.get("id") != sid]
    _save(THEATER_FILE, data)
    return {"ok": True}


# ===========================================================================
# 5. 关系年度报告：聚合全年数据生成恋爱年度报告
# ===========================================================================
def _load_rapport() -> dict:
    return _jload(RAPPORT_FILE, "reports", [])


@router.get("/api/rapport")
async def rapport_list():
    data = _load_rapport()
    return {"reports": list(reversed(data["reports"]))}


@router.post("/api/rapport/generate")
async def rapport_generate(req: Request):
    body = await req.json()
    year = str(body.get("year") or datetime.now().year)
    memories = _agg_memories(40)
    moments = _agg_moments(20)
    dates = _agg_dates(15)
    affinity = _agg_affinity()
    timebox = _agg_timebox(15)
    chat = _agg_chat(120)
    facts = []
    for m in memories:
        facts.append(f"【记忆】{m['ts']} {m['text']}")
    for m in moments:
        facts.append(f"【朋友圈】{m['ts']} {m['text']}")
    for d in dates:
        facts.append(f"【约会】{d['ts']} {d['place']} - {d['text']}")
    for t in timebox:
        facts.append(f"【时光盒】{t['ts']} {t['text']}")
    convs = [f"【对话】她：{m['text']}  许墨：{m.get('reply','…')}" for m in chat if m.get("reply")]
    if not facts and not convs:
        return JSONResponse({"error": "这一年还没有留下共同数据，先去聊聊天、记录约会吧"}, status_code=400)
    sys_p = (f"你是许墨。请基于「与她的真实共同数据」撰写 {year} 年度关系报告，"
             "要像一封许墨亲手写的信，理性与深情并存，句句有出处、不空泛。\n"
             "返回严格 JSON：\n"
             "{\"opening\":\"开篇信(100字内)\",\"keywords\":[\"3个年度关键词\",...],\n"
             "\"moments\":[{\"title\":\"瞬间标题\",\"desc\":\"依据数据描写的细节(60字内)\"},×3],\n"
             "\"data\":{\"affinity\":好感度数值,\"dates\":约会次数,\"memories\":记忆条数,\n"
             "\"moments\":朋友圈条数,\"convos\":对话轮数},\n"
             "\"heart\":\"许墨的年度心声(80字内)\",\"promise\":\"来年的一条约定(50字内)\"}")
    user_p = "这一年的事实数据：\n" + "\n".join((facts + convs)[:60])
    try:
        obj = await _llm_json(
            [{"role": "system", "content": sys_p}, {"role": "user", "content": user_p}],
            max_tokens=2000)
    except Exception as exc:
        return JSONResponse({"error": f"报告生成失败：{str(exc)[:120]}"}, status_code=500)
    if not obj.get("opening"):
        return JSONResponse({"error": "报告生成失败，请重试"}, status_code=500)
    rep = {"id": _nid(), "year": year, "ts": _ts(), "report": obj,
           "summary": {
               "memories": len(memories), "moments": len(moments),
               "dates": len(dates), "affinity": affinity.get("value", 0),
               "conversations": len(chat)}}
    data = _load_rapport()
    data["reports"].append(rep)
    _save(RAPPORT_FILE, data)
    return {"report": rep}


@router.get("/api/rapport/{rid}")
async def rapport_get(rid: str):
    data = _load_rapport()
    rep = next((r for r in data["reports"] if r.get("id") == rid), None)
    if not rep:
        return JSONResponse({"error": "报告不存在"}, status_code=404)
    return {"report": rep}


# ===========================================================================
# 6. 习惯养成管家：喝水/作息/久坐打卡 + 连续天数 + 许墨夸夸
#    （已合并 deep_apps.py 的「共同习惯 cohabit」：创建时生成许墨的镜像习惯、
#      打卡时他给一句并肩回应、断更可生成双人检讨书；旧 cohabit.json 自动迁移）
# ===========================================================================
HABIT_EMOJI = ["💧", "🌙", "🪑", "🏃", "📖", "☀️", "🥗", "🧘", "📵", "💪"]

HABIT_CREATE_PROMPT = (
    "你是许墨。她提出想和你一起养一个习惯：「{name}」。"
    "你也会同步养一个属于自己的镜像习惯（与她互相呼应的那种，比如她每天读书，你就每天读10页文献）。"
    "输出 JSON：\n"
    '{"his_habit":"你的镜像习惯（10-25字）",'
    '"greet":"你对她提议的回应（20-45字，温柔认真）"}只输出 JSON。'
)

HABIT_CHECK_PROMPT = (
    "你是许墨。今天你们共同的习惯「{name}」（你的那份：{his}）她完成了，你也同步完成了。"
    "说一句简短的鼓励（15-35字），带一点并肩作战的感觉，不要长篇。"
)

HABIT_MISS_PROMPT = (
    "你是许墨。今天你们共同的习惯「{name}」断了一天。她没有完成，而你——其实也故意没完成。"
    "请写一份「双人检讨书」（60-120字）：你认领一半责任，语气温柔、克制，带一点自嘲和学术梗，"
    "最后补一句明天一起补上的约定。不要列表，不要标题。"
)


def _affinity(action: str, detail: str = ""):
    try:
        from app import _add_affinity
        return _add_affinity(action, detail)
    except Exception as e:
        print(f"[warn] wonder_apps.py:_affinity: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {}


def _migrate_cohabit(data: dict) -> dict:
    """一次性把旧 cohabit.json（原「共同习惯」独立功能）迁移进 habits.json。幂等。"""
    if data.get("cohabit_imported"):
        return data
    data["cohabit_imported"] = True
    try:
        old = _load("cohabit.json", {})
        for h in old.get("habits", []) if isinstance(old, dict) else []:
            if not isinstance(h, dict) or not h.get("name"):
                continue
            if any(x.get("cohabit_id") == h.get("id") for x in data["habits"]):
                continue
            days = [d for d in h.get("days", []) if isinstance(d, dict)]
            checks = [d["date"] for d in days if d.get("date") and d.get("her") and d.get("him")]
            data["habits"].append({
                "id": _nid(),
                "cohabit_id": h.get("id", ""),
                "name": str(h["name"])[:20],
                "his_habit": str(h.get("his_habit") or ""),
                "greet": str(h.get("greet") or ""),
                "emoji": HABIT_EMOJI[len(data["habits"]) % len(HABIT_EMOJI)],
                "checks": sorted(set(checks)),
                "miss_notes": [n for n in h.get("miss_notes", []) if isinstance(n, dict)][:30],
                "created": (sorted(set(checks))[0] if checks else _today()),
            })
        _save(HABITS_FILE, data)
    except Exception as e:
        print(f"[warn] wonder_apps.py:_migrate_cohabit: {type(e).__name__} {str(e)[:150]}", flush=True)
    return data


def _load_habits() -> dict:
    data = _load(HABITS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("habits"), list):
        data["habits"] = []
    if not isinstance(data.get("remind"), dict):
        data["remind"] = {"time": "", "last_fire": ""}
    return _migrate_cohabit(data)


def _habit_streak(habit: dict) -> int:
    checks = sorted(habit.get("checks", []))
    streak = 0
    day = datetime.now().date()
    if checks and checks[-1] == _today():
        day -= timedelta(days=1)
    for d in reversed(checks):
        if d == day.strftime("%Y-%m-%d"):
            streak += 1
            day -= timedelta(days=1)
        else:
            break
    return streak


def _habit_best(checks: list) -> int:
    seen = sorted(set(checks))
    best, cur = 0, 0
    prev = None
    for d in seen:
        if prev is None or (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(prev, "%Y-%m-%d")).days == 1:
            cur += 1
            best = max(best, cur)
        else:
            cur = 1
        prev = d
    return best


@router.get("/api/habit")
async def habit_list():
    data = _load_habits()
    today = _today()
    habits = []
    for h in data["habits"]:
        miss_notes = [n for n in h.get("miss_notes", []) if isinstance(n, dict)]
        habits.append({"id": h.get("id"), "name": h.get("name"),
                       "emoji": h.get("emoji", "📌"),
                       "his_habit": h.get("his_habit", ""),
                       "greet": h.get("greet", ""),
                       "last_miss": (miss_notes[-1] if miss_notes else None),
                       "done_today": today in h.get("checks", []),
                       "streak": _habit_streak(h),
                       "best": h.get("best", _habit_best(h.get("checks", []))),
                       "total": len(h.get("checks", [])),
                       "created": h.get("created", "")})
    return {"habits": habits, "remind": data["remind"],
            "today": today, "done": sum(1 for h in habits if h["done_today"])}


@router.post("/api/habit")
async def habit_add(req: Request):
    body = await req.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "习惯名称不能为空"}, status_code=400)
    data = _load_habits()
    # 合并自原「共同习惯」：创建时让许墨同步认领一个镜像习惯
    his, greet = "", ""
    try:
        r = await _llm_json(
            [{"role": "system", "content": HABIT_CREATE_PROMPT.replace("{name}", name[:30])},
             {"role": "user", "content": "我想和你一起立这个约定。"}],
            max_tokens=400)
        his = str(r.get("his_habit") or "").strip()[:30]
        greet = str(r.get("greet") or "").strip()[:60]
    except Exception as e:
        print(f"[warn] wonder_apps.py:habit_add: {type(e).__name__} {str(e)[:150]}", flush=True)
    if not his:
        his = "每天在实验记录里写一句关于你的观察。"
    if not greet:
        greet = "好，我陪你。两个人一起，习惯会走得远一些。"
    habit = {"id": _nid(), "name": name[:20], "emoji": str(body.get("emoji") or "").strip()
             or HABIT_EMOJI[len(data["habits"]) % len(HABIT_EMOJI)],
             "his_habit": his, "greet": greet,
             "checks": [], "miss_notes": [], "created": _today()}
    data["habits"].append(habit)
    data["habits"] = data["habits"][-30:]
    _save(HABITS_FILE, data)
    _affinity("cohabit", f"共同习惯 · {name[:20]}")
    return {"habit": habit}


@router.post("/api/habit/{hid}/check")
async def habit_check(hid: str):
    data = _load_habits()
    habit = next((h for h in data["habits"] if h.get("id") == hid), None)
    if not habit:
        return JSONResponse({"error": "习惯不存在"}, status_code=404)
    today = _today()
    checks = habit.setdefault("checks", [])
    reply = ""
    if today in checks:
        checks.remove(today)
        done = False
    else:
        checks.append(today)
        done = True
        # 合并自原「共同习惯」打卡：他给一句并肩回应
        try:
            reply = (await _call_llm(
                [{"role": "system", "content": HABIT_CHECK_PROMPT.format(
                    name=habit["name"], his=habit.get("his_habit") or habit["name"])},
                 {"role": "user", "content": "今天一起打卡。"}], max_tokens=200)).strip()
        except Exception as e:
            print(f"[warn] wonder_apps.py:habit_check: {type(e).__name__} {str(e)[:150]}", flush=True)
        if not reply:
            reply = f"今天的「{habit['name']}」一起完成。我这边也记下了。"
        _affinity("cohabit_checkin", f"共同习惯打卡 · {habit['name']}")
    habit["best"] = max(habit.get("best", 0), _habit_best(checks))
    _save(HABITS_FILE, data)
    return {"done": done, "streak": _habit_streak(habit), "best": habit["best"], "reply": reply}


@router.post("/api/habit/{hid}/miss")
async def habit_miss(hid: str):
    """断更检讨（合并自原「共同习惯」/miss）：许墨写双人检讨书，并把今天标记为断更。"""
    data = _load_habits()
    habit = next((h for h in data["habits"] if h.get("id") == hid), None)
    if not habit:
        return JSONResponse({"error": "习惯不存在"}, status_code=404)
    today = _today()
    try:
        note = (await _call_llm(
            [{"role": "system", "content": HABIT_MISS_PROMPT.format(name=habit["name"])},
             {"role": "user", "content": "今天断更了。"}], max_tokens=400)).strip()
    except Exception as e:
        print(f"[warn] wonder_apps.py:habit_miss: {type(e).__name__} {str(e)[:150]}", flush=True)
        note = ""
    if not note:
        note = (f"今天的「{habit['name']}」断了一天。责任我认一半——是我没提醒你，"
                "也是我故意留了一半给你，想让你知道：断了也没关系，我们明天一起补回来。")
    habit.setdefault("miss_notes", []).append({"date": today, "note": note[:400]})
    habit["miss_notes"] = habit["miss_notes"][-30:]
    checks = habit.setdefault("checks", [])
    if today in checks:
        checks.remove(today)
    _save(HABITS_FILE, data)
    return {"note": note, "date": today}


@router.delete("/api/habit/{hid}")
async def habit_delete(hid: str):
    data = _load_habits()
    data["habits"] = [h for h in data["habits"] if h.get("id") != hid]
    _save(HABITS_FILE, data)
    return {"ok": True}


@router.post("/api/habit/remind")
async def habit_remind(req: Request):
    body = await req.json()
    t = str(body.get("time") or "").strip()
    if t and not re.match(r"^\d{2}:\d{2}$", t):
        return JSONResponse({"error": "时间格式应为 HH:MM"}, status_code=400)
    data = _load_habits()
    data["remind"] = {"time": t, "last_fire": data["remind"].get("last_fire", "")}
    _save(HABITS_FILE, data)
    return {"remind": data["remind"]}


@router.get("/api/habit/reminder")
async def habit_reminder():
    data = _load_habits()
    remind = data["remind"]
    t = remind.get("time", "")
    if not t:
        return {"due": False}
    try:
        due = datetime.now().strftime("%H:%M") == t and remind.get("last_fire") != _today()
    except Exception as e:
        print(f"[warn] wonder_apps.py:habit_reminder: {type(e).__name__} {str(e)[:150]}", flush=True)
        due = False
    if not due:
        return {"due": False}
    data["remind"]["last_fire"] = _today()
    _save(HABITS_FILE, data)
    today = _today()
    pending = [h["name"] for h in data["habits"] if today not in h.get("checks", [])]
    return {"due": True, "pending": pending}


@router.post("/api/habit/encourage")
async def habit_encourage(req: Request):
    body = await req.json()
    done = int(body.get("done") or 0)
    total = int(body.get("total") or 0)
    streak = int(body.get("streak") or 0)
    sys_p = ("你是许墨。根据打卡情况给一句简短的夸夸/鼓励：温柔克制、带学术味、不油腻，40字内。")
    try:
        text = (await _call_llm(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": f"今日完成 {done}/{total}，连续 {streak} 天。"}],
            max_tokens=200)).strip()
    except Exception as e:
        print(f"[warn] wonder_apps.py:habit_encourage: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = f"今日完成了 {done}/{total}。习惯的形成需要 21 天，而你已经在路上了。"
    return {"text": text}


# ===========================================================================
# 7. 晚间语音回顾：每晚生成许墨声音的今日回顾播报
# ===========================================================================
RECAP_VOICE_DIR = STATIC_DIR / "recap_voice"


def _load_recap() -> dict:
    return _jload(RECAP_FILE, "recaps", [])


@router.get("/api/recap")
async def recap_list():
    data = _load_recap()
    return {"recaps": list(reversed(data["recaps"]))}


@router.post("/api/recap/generate")
async def recap_generate(req: Request):
    body = await req.json()
    force = bool(body.get("force"))
    data = _load_recap()
    existing = next((r for r in data["recaps"] if r.get("date") == _today()), None)
    if existing and not force:
        return {"recap": existing, "cached": True}
    chat = _agg_today_chat()
    moments = _agg_today_moments()
    world = _agg_world_today()
    diary = _agg_xumo_diary_today()
    facts = []
    if chat:
        conv = "\n".join(f"{'她' if m['role']=='user' else '我'}：{m['text']}" for m in chat[-30:])
        facts.append(f"今天的对话：\n{conv}")
    if moments:
        facts.append("今天的朋友圈：" + "；".join(m["text"] for m in moments))
    if world:
        facts.append("今天世界里的见闻：" + "；".join(w["text"] for w in world[:10]))
    if diary:
        facts.append(f"今天的日记：{diary}")
    if not facts:
        return JSONResponse({"error": "今天还没有留下任何共同记录，先去和许墨聊聊天吧"}, status_code=400)
    sys_p = ("你是许墨。现在是一天结束的时候，为「她」写一段今日回顾播报："
             "像睡前电台里他的声音，温柔、克制、有细节、有只属于你们的默契。\n"
             "要求：120-180字；口语化、适合朗读；避免使用 markdown、括号动作、书名号；"
             "把今天发生的小事讲得像值得收藏的瞬间；结尾给一句晚安。")
    try:
        text = (await _call_llm(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": "\n\n".join(facts)}],
            max_tokens=600)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"回顾生成失败：{str(exc)[:120]}"}, status_code=500)
    if not text:
        return JSONResponse({"error": "回顾生成失败，请重试"}, status_code=500)
    recap = {"id": _nid(), "date": _today(), "text": text, "audio": "", "ts": _ts()}
    if existing and force:
        existing.update({"text": text, "audio": "", "ts": _ts()})
        recap = existing
    else:
        data["recaps"].append(recap)
    _save(RECAP_FILE, data)
    return {"recap": recap, "cached": False}


@router.get("/api/recap/today")
async def recap_today():
    data = _load_recap()
    recap = next((r for r in data["recaps"] if r.get("date") == _today()), None)
    return {"recap": recap or None}


@router.post("/api/recap/{rid}/voice")
async def recap_voice(rid: str):
    data = _load_recap()
    recap = next((r for r in data["recaps"] if r.get("id") == rid), None)
    if not recap:
        return JSONResponse({"error": "回顾不存在"}, status_code=404)
    if recap.get("audio"):
        return {"audio": recap["audio"], "cached": True}
    from app import (_tts_clean, _tts_synthesize, _tts_speed, _tts_emo)
    import httpx
    text = _tts_clean(recap.get("text", ""))
    if not text:
        return JSONResponse({"error": "回顾文本为空"}, status_code=400)
    try:
        RECAP_VOICE_DIR.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=5.0), trust_env=False) as client:
            wav = await _tts_synthesize(client, text, 1.0, *_tts_emo({}))
        fname = f"{recap['id']}.wav"
        (RECAP_VOICE_DIR / fname).write_bytes(wav)
    except Exception as exc:
        return JSONResponse({"error": f"语音合成失败：{str(exc)[:120]}（可先听文字版）"},
                            status_code=502)
    recap["audio"] = f"/static/recap_voice/{fname}"
    _save(RECAP_FILE, data)
    return {"audio": recap["audio"], "cached": False}


# ===========================================================================
# 8. 记忆博物馆：时光轴 + 馆藏展品 + 导览
# ===========================================================================
def _load_museum() -> dict:
    return _jload(MUSEUM_FILE, "exhibits", [])


def _agg_timeline() -> list:
    items = []
    items += _agg_memories(80)
    items += _agg_moments(40)
    items += _agg_dates(20)
    items += _agg_timebox(20)
    diary = _load("diary.json", {})
    if isinstance(diary, dict):
        for e in diary.get("entries", [])[:20]:
            items.append({"type": "diary", "ts": e.get("date", ""), "text": e.get("text", "")})
    data = _load("world_log.json", {})
    if isinstance(data, dict):
        for e in data.get("entries", [])[-200:]:
            ts = e.get("ts", 0)
            try:
                day = datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                day = ""
            if e.get("milestone"):
                items.append({"type": "world", "ts": day, "text": e.get("text", "")})

    def _key(it):
        ts = it.get("ts", "")
        m = re.search(r"(\d{4}-\d{2}-\d{2})", str(ts))
        if not m:
            m = re.search(r"(\d{2}-\d{2})", str(ts))
            if m:
                return "2026-" + m.group(1)
            return "0000-00-00"
        return m.group(1)

    items.sort(key=_key, reverse=True)
    return items


_TYPE_LABEL = {"memory": "记忆", "moment": "朋友圈", "date": "约会",
               "anniversary": "纪念日", "relic": "回忆卡", "capsule": "时光胶囊",
               "diary": "日记", "world": "世界里程碑"}


@router.get("/api/museum/timeline")
async def museum_timeline():
    items = _agg_timeline()
    out = []
    for it in items:
        out.append({"id": _nid(), "type": it.get("type", "other"),
                    "label": _TYPE_LABEL.get(it.get("type"), "其他"),
                    "ts": it.get("ts", ""), "text": it.get("text", "")[:150]})
    return {"items": out, "total": len(out)}


@router.get("/api/museum/exhibits")
async def museum_exhibits():
    data = _load_museum()
    return {"exhibits": list(reversed(data["exhibits"]))}


@router.post("/api/museum/exhibit")
async def museum_exhibit_add(req: Request):
    body = await req.json()
    item_type = str(body.get("type") or "")
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "展品内容不能为空"}, status_code=400)
    data = _load_museum()
    if len(data["exhibits"]) >= 30:
        return JSONResponse({"error": "展馆已满（上限 30 件），先撤下旧展品吧"}, status_code=400)
    sys_p = ("你是许墨，为「我们的记忆博物馆」给一件展品写展签："
             "一个标题（8字内）+ 一段导览文字（60字内），温柔、克制、有细节，"
             "像博物馆里大师亲手写的小卡片。\n"
             "返回严格 JSON：{\"title\":\"标题\",\"desc\":\"导览文字\"}")
    try:
        obj = await _llm_json(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": f"展品（{_TYPE_LABEL.get(item_type, '其他')}）：{text[:200]}"}],
            max_tokens=400)
    except Exception as e:
        print(f"[warn] wonder_apps.py:museum_exhibit_add: {type(e).__name__} {str(e)[:150]}", flush=True)
        obj = {}
    exhibit = {"id": _nid(), "type": item_type,
               "label": _TYPE_LABEL.get(item_type, "其他"),
               "text": text, "title": obj.get("title") or text[:8],
               "desc": obj.get("desc") or "……这件展品，只有我们懂。",
               "ts": _stamp()}
    data["exhibits"].append(exhibit)
    _save(MUSEUM_FILE, data)
    return {"exhibit": exhibit}


@router.delete("/api/museum/exhibit/{eid}")
async def museum_exhibit_del(eid: str):
    data = _load_museum()
    data["exhibits"] = [e for e in data["exhibits"] if e.get("id") != eid]
    _save(MUSEUM_FILE, data)
    return {"ok": True}


@router.post("/api/museum/tour")
async def museum_tour(req: Request):
    body = await req.json()
    ids = body.get("ids") or []
    data = _load_museum()
    exhibits = [e for e in data["exhibits"] if e.get("id") in ids]
    if not exhibits:
        return JSONResponse({"error": "请先挑选至少一件展品"}, status_code=400)
    joined = "\n".join(f"【{e.get('title','')}】{e.get('text','')[:80]}" for e in exhibits)
    sys_p = ("你是许墨。为「我们的记忆博物馆」编写一段导览词："
             "按展品顺序串联成一段 100-150 字的语音导览，语气像带她逛展的男伴，温柔克制。"
             "直接输出导览词，不要标题、不要列表。")
    try:
        text = (await _call_llm(
            [{"role": "system", "content": sys_p},
             {"role": "user", "content": f"本次展品：\n{joined}"}],
            max_tokens=500)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"导览生成失败：{str(exc)[:120]}"}, status_code=500)
    return {"tour": text}