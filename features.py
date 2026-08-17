"""四大学习功能 API：监督背单词 / 视频总结 / 解题辅助 / 共同阅读。
数据全部持久化到 BASE_DIR 下的 JSON 文件，风格与 app.py 保持一致。
"""
import json
from store_common import atomic_json, file_lock
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

BASE_DIR = Path(__file__).parent


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    """延迟导入以避免与 app.py 循环依赖。"""
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)

from role_data import RolePath, role_file as _role_file  # noqa: E402  按请求角色动态路由数据文件

router = APIRouter()

WORDS_FILE = RolePath("words.json")
STUDY_FILE = RolePath("study.json")
VIDEO_FILE = RolePath("videos.json")
SOLVE_FILE = RolePath("solves.json")
BOOKS_FILE = RolePath("books.json")


def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path: Path, data):
    atomic_json(path, data)


def _now() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ===========================================================================
# 1. 监督背单词
# ===========================================================================

DEFAULT_WORDS = [
    {"word": "serendipity", "phonetic": "/ˌserənˈdɪpəti/", "meaning": "n. 意外发现美好事物的运气", "example": "Meeting her was pure serendipity."},
    {"word": "ephemeral", "phonetic": "/ɪˈfemərəl/", "meaning": "adj. 短暂的，转瞬即逝的", "example": "The beauty of cherry blossoms is ephemeral."},
    {"word": "resilient", "phonetic": "/rɪˈzɪliənt/", "meaning": "adj. 有韧性的，能复原的", "example": "She is remarkably resilient under pressure."},
    {"word": "ambiguous", "phonetic": "/æmˈbɪɡjuəs/", "meaning": "adj. 模棱两可的，含糊的", "example": "His answer was deliberately ambiguous."},
    {"word": "meticulous", "phonetic": "/məˈtɪkjələs/", "meaning": "adj. 一丝不苟的，严谨的", "example": "He keeps meticulous notes on every experiment."},
    {"word": "inevitable", "phonetic": "/ɪnˈevɪtəbl/", "meaning": "adj. 不可避免的", "example": "Change is inevitable; growth is optional."},
    {"word": "profound", "phonetic": "/prəˈfaʊnd/", "meaning": "adj. 深刻的，深远的", "example": "The book had a profound effect on me."},
    {"word": "subtle", "phonetic": "/ˈsʌtl/", "meaning": "adj. 微妙的，不易察觉的", "example": "There was a subtle change in her expression."},
    {"word": "curiosity", "phonetic": "/ˌkjʊəriˈɒsəti/", "meaning": "n. 好奇心", "example": "Curiosity is the beginning of all science."},
    {"word": "paradox", "phonetic": "/ˈpærədɒks/", "meaning": "n. 悖论，自相矛盾", "example": "It is a paradox that love can be both weakness and strength."},
    {"word": "eloquent", "phonetic": "/ˈeləkwənt/", "meaning": "adj. 雄辩的，有说服力的", "example": "Her silence was more eloquent than words."},
    {"word": "diligent", "phonetic": "/ˈdɪlɪdʒənt/", "meaning": "adj. 勤奋的", "example": "Diligent practice makes perfect."},
    {"word": "contemplate", "phonetic": "/ˈkɒntəmpleɪt/", "meaning": "v. 沉思，仔细考虑", "example": "He sat quietly, contemplating the data."},
    {"word": "ineffable", "phonetic": "/ɪnˈefəbl/", "meaning": "adj. 难以言喻的", "example": "An ineffable joy filled her heart."},
    {"word": "persevere", "phonetic": "/ˌpɜːsɪˈvɪə/", "meaning": "v. 坚持不懈", "example": "Persevere, and the result will surprise you."},
    {"word": "nostalgia", "phonetic": "/nɒˈstældʒə/", "meaning": "n. 怀旧，乡愁", "example": "The old song filled him with nostalgia."},
    {"word": "luminous", "phonetic": "/ˈluːmɪnəs/", "meaning": "adj. 发光的，明亮的", "example": "Her eyes were luminous in the dark."},
    {"word": "whimsical", "phonetic": "/ˈwɪmzɪkl/", "meaning": "adj. 异想天开的，古怪的", "example": "He had a whimsical sense of humor."},
    {"word": "tranquil", "phonetic": "/ˈtræŋkwɪl/", "meaning": "adj. 宁静的", "example": "The lake was tranquil at dawn."},
    {"word": "profoundly", "phonetic": "/prəˈfaʊndli/", "meaning": "adv. 深刻地", "example": "She was profoundly moved by the letter."},
]


def _load_words() -> dict:
    data = _load(WORDS_FILE, None)
    if data is None:
        data = {
            "words": [
                {
                    "id": uuid.uuid4().hex[:8],
                    "word": w["word"],
                    "phonetic": w["phonetic"],
                    "meaning": w["meaning"],
                    "example": w["example"],
                    "source": "builtin",
                    "added": _now(),
                }
                for w in DEFAULT_WORDS
            ]
        }
        _save(WORDS_FILE, data)
    return data


def _load_study() -> dict:
    return _load(STUDY_FILE, {
        "plan": {"daily_target": 10, "remind_time": "21:00", "mode": "en2zh"},
        "progress": {},          # word -> {"seen": n, "correct": n, "wrong": n, "mastered": bool, "last": date}
        "history": [],           # {"date", "learned", "correct", "total"}
        "wrong_book": [],        # word 列表
    })


@router.get("/api/words")
async def get_words():
    data = _load_words()
    return {"words": data["words"], "total": len(data["words"])}


@router.post("/api/words/import")
async def import_words(req: Request):
    """导入自定义词库。格式：每行 单词|音标|释义|例句，至少 单词|释义。"""
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "内容为空"}, status_code=400)
    data = _load_words()
    existing = {w["word"].lower() for w in data["words"]}
    added, skipped = 0, 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[|\t]", line)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            parts = [p.strip() for p in line.split(",", 1)]
        if len(parts) < 2 or not parts[0]:
            skipped += 1
            continue
        if parts[0].lower() in existing:
            skipped += 1
            continue
        data["words"].append({
            "id": uuid.uuid4().hex[:8],
            "word": parts[0],
            "phonetic": parts[1] if len(parts) > 2 else "",
            "meaning": parts[-1] if len(parts) == 2 else (parts[2] if len(parts) > 2 else parts[1]),
            "example": parts[3] if len(parts) > 3 else "",
            "source": "custom",
            "added": _now(),
        })
        existing.add(parts[0].lower())
        added += 1
    _save(WORDS_FILE, data)
    return {"added": added, "skipped": skipped, "total": len(data["words"])}


@router.delete("/api/words/{word_id}")
async def delete_word(word_id: str):
    data = _load_words()
    before = len(data["words"])
    data["words"] = [w for w in data["words"] if w["id"] != word_id]
    if len(data["words"]) == before:
        return JSONResponse({"error": "单词不存在"}, status_code=404)
    _save(WORDS_FILE, data)
    return {"ok": True, "total": len(data["words"])}


@router.get("/api/study/plan")
async def get_plan():
    return _load_study()["plan"]


@router.post("/api/study/plan")
async def set_plan(req: Request):
    body = await req.json()
    study = _load_study()
    plan = study["plan"]
    if "daily_target" in body:
        plan["daily_target"] = max(1, min(200, int(body["daily_target"])))
    if "remind_time" in body:
        plan["remind_time"] = str(body["remind_time"])
    if "mode" in body and body["mode"] in ("en2zh", "zh2en", "spell", "mixed"):
        plan["mode"] = body["mode"]
    _save(STUDY_FILE, study)
    return {"plan": plan}


@router.get("/api/study/quiz")
async def get_quiz(count: int = 10, mode: str = "en2zh", wrong_only: bool = False):
    """生成测验题。mode: en2zh(看英选汉) / zh2en(看汉选英) / spell(拼写) / mixed"""
    words_data = _load_words()["words"]
    study = _load_study()
    if len(words_data) < 4:
        return JSONResponse({"error": "词库至少需要 4 个单词才能测验"}, status_code=400)

    import random
    pool = list(words_data)
    if wrong_only:
        wrong_set = set(study["wrong_book"])
        pool = [w for w in pool if w["word"] in wrong_set]
        if not pool:
            return JSONResponse({"error": "错词本是空的，太棒了"}, status_code=400)
    random.shuffle(pool)
    picked = pool[: max(1, min(count, len(pool)))]

    questions = []
    for i, w in enumerate(picked):
        qmode = mode if mode != "mixed" else random.choice(["en2zh", "zh2en", "spell"])
        q = {"word_id": w["id"], "word": w["word"], "mode": qmode}
        if qmode == "spell":
            q["prompt"] = w["meaning"]
            q["hint"] = w["word"][0] + "_" * (len(w["word"]) - 1)
        else:
            others = [x for x in words_data if x["id"] != w["id"]]
            random.shuffle(others)
            distractors = others[:3]
            if qmode == "en2zh":
                q["prompt"] = f'{w["word"]}  {w.get("phonetic", "")}'
                options = [w["meaning"]] + [d["meaning"] for d in distractors]
            else:
                q["prompt"] = w["meaning"]
                options = [w["word"]] + [d["word"] for d in distractors]
            random.shuffle(options)
            q["options"] = options
            q["answer"] = w["meaning"] if qmode == "en2zh" else w["word"]
        questions.append(q)
    return {"questions": questions, "count": len(questions)}


@router.post("/api/study/answer")
async def submit_answer(req: Request):
    """提交单题答案，更新进度与错词本。"""
    body = await req.json()
    word = (body.get("word") or "").strip()
    correct = bool(body.get("correct"))
    if not word:
        return JSONResponse({"error": "缺少 word"}, status_code=400)
    study = _load_study()
    prog = study["progress"].setdefault(word, {"seen": 0, "correct": 0, "wrong": 0, "mastered": False, "last": ""})
    prog["seen"] += 1
    prog["last"] = _today()
    if correct:
        prog["correct"] += 1
        if prog["correct"] >= 3 and prog["correct"] >= prog["wrong"] * 2:
            prog["mastered"] = True
        if word in study["wrong_book"]:
            study["wrong_book"].remove(word)
    else:
        prog["wrong"] += 1
        prog["mastered"] = False
        if word not in study["wrong_book"]:
            study["wrong_book"].append(word)
    _save(STUDY_FILE, study)
    return {"ok": True, "progress": prog}


@router.post("/api/study/session")
async def finish_session(req: Request):
    """结束一次学习，写入历史记录（用于进度跟踪）。"""
    body = await req.json()
    study = _load_study()
    entry = {
        "date": _today(),
        "time": _now(),
        "learned": int(body.get("learned", 0)),
        "correct": int(body.get("correct", 0)),
        "total": int(body.get("total", 0)),
    }
    study["history"].append(entry)
    study["history"] = study["history"][-200:]
    _save(STUDY_FILE, study)
    return {"ok": True}


@router.get("/api/study/stats")
async def study_stats():
    words_data = _load_words()["words"]
    study = _load_study()
    prog = study["progress"]
    today = _today()
    today_sessions = [h for h in study["history"] if h["date"] == today]
    # 连续学习天数
    days = sorted({h["date"] for h in study["history"]}, reverse=True)
    streak = 0
    from datetime import timedelta
    cursor = datetime.now().date()
    for d in days:
        if datetime.strptime(d, "%Y-%m-%d").date() == cursor:
            streak += 1
            cursor -= timedelta(days=1)
        elif datetime.strptime(d, "%Y-%m-%d").date() == cursor - timedelta(days=1) and streak == 0:
            cursor -= timedelta(days=1)
            streak += 1
        else:
            break
    return {
        "total_words": len(words_data),
        "mastered": sum(1 for p in prog.values() if p.get("mastered")),
        "learning": sum(1 for p in prog.values() if p.get("seen") and not p.get("mastered")),
        "wrong_count": len(study["wrong_book"]),
        "wrong_book": study["wrong_book"],
        "today_learned": sum(h["learned"] for h in today_sessions),
        "streak_days": streak,
        "history": study["history"][-14:],
        "plan": study["plan"],
    }


# ===========================================================================
# 2. 视频总结
# ===========================================================================

VIDEO_PROMPT = """你是一位专业的视频内容分析师。根据用户提供的视频信息（链接、标题、简介或字幕/文本内容），生成一份结构化的视频总结报告。

输出格式（严格使用以下 Markdown 结构）：
# 视频总结
**主题**：一句话概括
## 核心观点
- （3-6 条，每条一句话）
## 内容脉络
1. （按逻辑顺序梳理，若为虚构的情节梳理请注明"推测"）
## 关键时间节点
- 00:00 开场 / ……（若无法获知具体时间，用"开头/中段/结尾"代替）
## 值得记住的一句话
> ……

要求：客观准确，不编造细节；信息不足的部分明确说明"根据现有信息无法确定"。全程中文。"""


@router.post("/api/video/summarize")
async def summarize_video(req: Request):
    body = await req.json()
    url = (body.get("url") or "").strip()
    text = (body.get("text") or "").strip()
    title = (body.get("title") or "").strip()
    if not url and not text:
        return JSONResponse({"error": "请提供视频链接或文字内容（字幕/简介/笔记）"}, status_code=400)

    # 若只给了链接，尝试抓取网页标题辅助分析
    page_info = ""
    if url and not text:
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, trust_env=False) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                m = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.S | re.I)
                if m:
                    page_info = f"网页标题：{m.group(1).strip()[:200]}\n"
        except Exception as e:
            print(f"[warn] features.py:summarize_video: {type(e).__name__} {str(e)[:150]}", flush=True)
            page_info = "（链接内容无法直接读取，请基于链接本身与常识分析，或提示用户补充字幕/简介）\n"

    user_msg = ""
    if url:
        user_msg += f"视频链接：{url}\n{page_info}"
    if title:
        user_msg += f"视频标题：{title}\n"
    if text:
        user_msg += f"字幕/简介/笔记内容：\n{text[:8000]}\n"

    try:
        summary = await _call_llm(
            [
                {"role": "system", "content": VIDEO_PROMPT},
                {"role": "user", "content": user_msg + "\n请生成视频总结报告。"},
            ],
            max_tokens=2000,
        )
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    videos = _load(VIDEO_FILE, [])
    record = {
        "id": uuid.uuid4().hex[:12],
        "url": url,
        "title": title or (url[:60] if url else "文本总结"),
        "summary": summary,
        "time": _now(),
    }
    videos.append(record)
    _save(VIDEO_FILE, videos[-50:])
    return {"record": record}


@router.get("/api/video/history")
async def video_history():
    return {"videos": list(reversed(_load(VIDEO_FILE, [])))}


@router.delete("/api/video/{vid}")
async def delete_video(vid: str):
    videos = _load(VIDEO_FILE, [])
    new = [v for v in videos if v["id"] != vid]
    if len(new) == len(videos):
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    _save(VIDEO_FILE, new)
    return {"ok": True}


# ===========================================================================
# 3. 解题辅助
# ===========================================================================

SOLVE_PROMPT = """你是一位耐心、专业的全科辅导老师，覆盖数学、物理、化学、生物、语文、英语、历史、地理、编程等学科。

用户会给你一道题目，你需要输出结构化的解答，格式如下：

## 题目分析
（这道题考什么知识点、已知条件、求解目标）

## 解题思路
（为什么这样做，先讲清思路再动笔）

## 详细步骤
1. ……
2. ……
（每一步给出依据/公式）

## 最终答案
（明确写出答案，有单位带单位）

## 知识点拓展
- 相关概念/易错点/同类题型技巧（2-4 条）

要求：
- 全程中文，公式可用 LaTeX 或纯文本表达；
- 题目信息不足时，先指出需要补充什么，再给出可能的解法方向；
- 如果用户是在追问/讨论（历史中已有解答），则围绕问题直接讨论，不必重复完整格式；
- 语言清晰易懂，像老师在旁边一步步讲。"""


@router.post("/api/solve")
async def solve_question(req: Request):
    body = await req.json()
    question = (body.get("question") or "").strip()
    history = body.get("history") or []
    if not question:
        return JSONResponse({"error": "请输入题目"}, status_code=400)

    messages = [{"role": "system", "content": SOLVE_PROMPT}]
    for h in history[-10:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": question})

    try:
        answer = await _call_llm(messages, max_tokens=2500)
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"answer": answer}


@router.get("/api/solve/history")
async def solve_history():
    return {"solves": list(reversed(_load(SOLVE_FILE, [])))}


@router.post("/api/solve/save")
async def save_solve(req: Request):
    body = await req.json()
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    subject = (body.get("subject") or "未分类").strip()
    if not question or not answer:
        return JSONResponse({"error": "缺少内容"}, status_code=400)
    solves = _load(SOLVE_FILE, [])
    record = {
        "id": uuid.uuid4().hex[:12],
        "subject": subject,
        "question": question[:500],
        "answer": answer,
        "time": _now(),
    }
    solves.append(record)
    _save(SOLVE_FILE, solves[-100:])
    return {"record": record}


@router.delete("/api/solve/{sid}")
async def delete_solve(sid: str):
    solves = _load(SOLVE_FILE, [])
    new = [s for s in solves if s["id"] != sid]
    if len(new) == len(solves):
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    _save(SOLVE_FILE, new)
    return {"ok": True}


# ===========================================================================
# 4. 共同阅读
# ===========================================================================

READ_PROMPT = """你是一位博学的阅读伙伴。用户正在阅读一本书的某个章节，请生成以下内容：

## 本章总结
（200 字以内，概括本章核心内容）

## 关键段落解读
（挑 1-3 个值得品味的点，各用 1-2 句话解读）

## 知识点补充
- （与内容相关的背景知识、术语解释、延伸阅读，2-4 条）

## 思考题
（1-2 个开放性问题，帮助深化理解）

全程中文，语气温和，像一位陪你读书的朋友。"""


def _split_chapters(text: str) -> list:
    """按常见章节标记切分文本。"""
    pattern = re.compile(r"(?m)^(第[一二三四五六七八九十百零\d]+[章回节卷部].{0,40}|Chapter\s+\d+.{0,40}|#{1,3}\s+.{1,40}|\d+[、.．]\s*.{1,40})\s*$")
    matches = list(pattern.finditer(text))
    if not matches:
        # 按字数粗略切分
        chunk = 3000
        chapters = []
        for i in range(0, len(text), chunk):
            chapters.append({"title": f"第 {i // chunk + 1} 部分", "content": text[i:i + chunk]})
        return chapters[:50]
    chapters = []
    if matches[0].start() > 50:
        chapters.append({"title": "开篇", "content": text[: matches[0].start()]})
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        chapters.append({"title": m.group(1).strip(), "content": text[m.start():end]})
    return chapters[:100]


@router.get("/api/books")
async def list_books():
    books = _load(BOOKS_FILE, [])
    return {
        "books": [
            {
                "id": b["id"],
                "title": b["title"],
                "chapters": len(b["chapters"]),
                "progress": b.get("progress", 0),
                "current_chapter": b.get("current_chapter", 0),
                "added": b.get("added", ""),
                "highlights": len(b.get("highlights", [])),
                "notes": len(b.get("notes", [])),
            }
            for b in reversed(books)
        ]
    }


@router.post("/api/books/upload")
async def upload_book(req: Request):
    body = await req.json()
    title = (body.get("title") or "").strip()
    text = (body.get("text") or "").strip()
    if not title or not text:
        return JSONResponse({"error": "请提供书名和文本内容"}, status_code=400)
    if len(text) > 500_000:
        return JSONResponse({"error": "文本过大（上限 50 万字符）"}, status_code=400)
    chapters = _split_chapters(text)
    books = _load(BOOKS_FILE, [])
    book = {
        "id": uuid.uuid4().hex[:12],
        "title": title,
        "chapters": chapters,
        "progress": 0,
        "current_chapter": 0,
        "highlights": [],
        "notes": [],
        "added": _now(),
    }
    books.append(book)
    _save(BOOKS_FILE, books[-20:])
    return {"book": {"id": book["id"], "title": title, "chapters": len(chapters)}}


@router.get("/api/books/{book_id}")
async def get_book(book_id: str):
    for b in _load(BOOKS_FILE, []):
        if b["id"] == book_id:
            return {"book": b}
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


@router.delete("/api/books/{book_id}")
async def delete_book(book_id: str):
    books = _load(BOOKS_FILE, [])
    new = [b for b in books if b["id"] != book_id]
    if len(new) == len(books):
        return JSONResponse({"error": "书籍不存在"}, status_code=404)
    _save(BOOKS_FILE, new)
    return {"ok": True}


@router.post("/api/books/{book_id}/progress")
async def save_progress(book_id: str, req: Request):
    body = await req.json()
    books = _load(BOOKS_FILE, [])
    for b in books:
        if b["id"] == book_id:
            b["current_chapter"] = max(0, min(int(body.get("chapter", 0)), len(b["chapters"]) - 1))
            b["progress"] = max(0, min(100, int(body.get("progress", 0))))
            _save(BOOKS_FILE, books)
            return {"ok": True, "progress": b["progress"], "current_chapter": b["current_chapter"]}
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


@router.post("/api/books/{book_id}/highlight")
async def add_highlight(book_id: str, req: Request):
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "高亮内容为空"}, status_code=400)
    books = _load(BOOKS_FILE, [])
    for b in books:
        if b["id"] == book_id:
            h = {
                "id": uuid.uuid4().hex[:8],
                "chapter": int(body.get("chapter", 0)),
                "text": text[:500],
                "pos": int(body.get("pos", -1)),
                "color": body.get("color", "yellow"),
                "note": (body.get("note") or "").strip(),
                "interpret": (body.get("interpret") or "").strip(),
                "time": _now(),
            }
            b.setdefault("highlights", []).append(h)
            _save(BOOKS_FILE, books)
            return {"highlight": h}
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


@router.put("/api/books/{book_id}/highlight/{hid}")
async def update_highlight(book_id: str, hid: str, req: Request):
    body = await req.json()
    books = _load(BOOKS_FILE, [])
    for b in books:
        if b["id"] == book_id:
            for h in b.get("highlights", []):
                if h["id"] == hid:
                    if "note" in body:
                        h["note"] = (body.get("note") or "").strip()
                    if "interpret" in body:
                        h["interpret"] = (body.get("interpret") or "").strip()
                    _save(BOOKS_FILE, books)
                    return {"ok": True, "highlight": h}
            return JSONResponse({"error": "高亮不存在"}, status_code=404)
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


@router.delete("/api/books/{book_id}/highlight/{hid}")
async def remove_highlight(book_id: str, hid: str):
    books = _load(BOOKS_FILE, [])
    for b in books:
        if b["id"] == book_id:
            before = len(b.get("highlights", []))
            b["highlights"] = [h for h in b.get("highlights", []) if h["id"] != hid]
            if len(b["highlights"]) == before:
                return JSONResponse({"error": "高亮不存在"}, status_code=404)
            _save(BOOKS_FILE, books)
            return {"ok": True}
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


@router.post("/api/books/{book_id}/summarize")
async def summarize_chapter(book_id: str, req: Request):
    body = await req.json()
    chapter_idx = int(body.get("chapter", 0))
    for b in _load(BOOKS_FILE, []):
        if b["id"] == book_id:
            if chapter_idx < 0 or chapter_idx >= len(b["chapters"]):
                return JSONResponse({"error": "章节不存在"}, status_code=404)
            ch = b["chapters"][chapter_idx]
            try:
                result = await _call_llm(
                    [
                        {"role": "system", "content": READ_PROMPT},
                        {"role": "user", "content": f"书名：《{b['title']}》\n章节：{ch['title']}\n\n正文：\n{ch['content'][:6000]}"},
                    ],
                    max_tokens=2000,
                )
            except RuntimeError as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            return {"summary": result, "chapter": chapter_idx, "chapter_title": ch["title"]}
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


# ===========================================================================
# 5. 共读 · 许墨陪读（一起看书）
# ===========================================================================
def _sys_prompt() -> str:
    """延迟导入 app 的系统提示词与人设（含玩家名字称呼指导），避免循环依赖。"""
    from app import SYSTEM_PROMPT, _name_directive
    return SYSTEM_PROMPT + _name_directive()


def _add_affinity(action: str, detail: str = ""):
    from app import _add_affinity as _impl
    return _impl(action, detail)


READ_COMPANION_PROMPT = """你正在和她一起读书——同一个房间，各占沙发一角，台灯是暖的。

【当前任务】基于正在读的这一章，以许墨的口吻说一句此刻会说的话。要求：
1. 1-2 句，轻声、自然，像身边人读到某处随口说的话，不长篇大论。
2. 可针对章节内容发一点感想或疑问，可带一处学术梗或双关，温柔克制、话留三分。
3. 只输出这句话本身，不要引号、不要旁白、不要解释。"""

READ_COMPANION_CHAT_PROMPT = """你正在和她一起读书——同一个房间，各占沙发一角，台灯是暖的。
她读到某一章时和你聊了起来。请以许墨的口吻回应她。要求：
1. 1-3 句，围绕她的话与本章内容，可引用原文细节，不跑题、不说教。
2. 温柔克制、话留三分，可用反问收尾，可带一处学术梗。
3. 保持许墨的人设与说话风格，只输出回应本身。"""

READ_EXPLAIN_PROMPT = """她读书时用笔划下一段文字，想听听你的解读。你和她正坐在同一张沙发上，看同一本书。

【当前任务】解读她划下的这段文字。要求：
1. 先解读这段文字本身——它的含义、妙处、在整章中的作用或背后的情感，再自然地接一句与你们此刻共读有关的话。
2. 2-4 句，温柔克制、话留三分，可带一处轻学术梗，但不要掉书袋。
3. 只输出解读本身，不要引号、不要旁白、不要标题、不要分点。"""


def _fmt_sec(sec) -> str:
    try:
        sec = max(0, int(float(sec)))
    except (TypeError, ValueError):
        sec = 0
    return f"{sec // 60:02d}:{sec % 60:02d}"


@router.post("/api/books/{book_id}/companion")
async def book_companion(book_id: str, req: Request):
    """许墨陪读：mode=open 打开新章节的开场感想；mode=chat 章节内讨论。"""
    body = await req.json()
    chapter_idx = int(body.get("chapter", 0))
    message = (body.get("message") or "").strip()
    mode = "chat" if message else "open"
    for b in _load(BOOKS_FILE, []):
        if b["id"] != book_id:
            continue
        if chapter_idx < 0 or chapter_idx >= len(b["chapters"]):
            return JSONResponse({"error": "章节不存在"}, status_code=404)
        ch = b["chapters"][chapter_idx]
        excerpt = ch["content"][:1500]
        context = f"书名：《{b['title']}》\n当前章节：{ch['title']}（第 {chapter_idx + 1} / {len(b['chapters'])} 章）\n章节开头：\n{excerpt}"
        hl_part = ""
        hl_now = [h for h in b.get("highlights", []) if h.get("chapter") == chapter_idx]
        if hl_now:
            last_hl = hl_now[-1]
            hl_part = f"\n\n她在这章划下了这段文字：「{last_hl['text'][:120]}」"
            if last_hl.get("note"):
                hl_part += f"\n她的笔记：{last_hl['note'][:100]}"
            if last_hl.get("interpret"):
                hl_part += f"\n你之前对这段的解读：{last_hl['interpret'][:150]}"
        history = body.get("history") or []
        if mode == "open":
            sys_prompt = _sys_prompt() + "\n\n" + READ_COMPANION_PROMPT
            user_prompt = context + hl_part + "\n\n请说一句翻开这一章时的话。"
        else:
            sys_prompt = _sys_prompt() + "\n\n" + READ_COMPANION_CHAT_PROMPT
            msgs = []
            for h in history[-6:]:
                if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                    msgs.append({"role": h["role"], "content": str(h["content"])[:400]})
            msgs.insert(0, {"role": "user", "content": context[:800] + hl_part + "\n……\n她：“" + message[:300] + "”\n\n请回应她。"})
            try:
                reply = await _call_llm(
                    [{"role": "system", "content": sys_prompt}] + msgs, max_tokens=500
                )
            except RuntimeError as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            info = _add_affinity("book_companion", f"陪读《{b['title']}》")
            return {"reply": reply, "affinity": info}
        try:
            reply = await _call_llm(
                [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=400,
            )
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        info = _add_affinity("book_companion", f"陪读《{b['title']}》")
        return {"reply": reply, "affinity": info}
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


@router.post("/api/books/{book_id}/explain")
async def explain_highlight(book_id: str, req: Request):
    """许墨智能解读：她划下的一段文字，结合本章上下文给出许墨口吻的解读。"""
    body = await req.json()
    text = (body.get("text") or "").strip()
    chapter_idx = int(body.get("chapter", 0))
    if not text:
        return JSONResponse({"error": "划线内容为空"}, status_code=400)
    if len(text) > 500:
        text = text[:500]
    for b in _load(BOOKS_FILE, []):
        if b["id"] != book_id:
            continue
        if chapter_idx < 0 or chapter_idx >= len(b["chapters"]):
            return JSONResponse({"error": "章节不存在"}, status_code=404)
        ch = b["chapters"][chapter_idx]
        excerpt = ch["content"][:3000]
        try:
            result = await _call_llm(
                [
                    {"role": "system", "content": _sys_prompt() + "\n\n" + READ_EXPLAIN_PROMPT},
                    {
                        "role": "user",
                        "content": f"书名：《{b['title']}》\n章节：{ch['title']}\n\n正文（节选）：\n{excerpt}\n\n她划下的这段文字：\n「{text}」\n\n请解读这段划线文字。",
                    },
                ],
                max_tokens=400,
            )
        except RuntimeError as e:
            return JSONResponse({"error": str(e)}, status_code=500)
        return {"explain": result, "chapter": chapter_idx, "text": text}
    return JSONResponse({"error": "书籍不存在"}, status_code=404)


# ===========================================================================
# 6. 一起看视频（本地视频上传 + 许墨陪看）
# ===========================================================================
WATCH_FILE = RolePath("watch.json")
WATCH_DIR = RolePath("uploads", "videos")

WATCH_VIDEO_TYPES = {
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/ogg": ".ogv",
    "video/quicktime": ".mov",
    "video/x-matroska": ".mkv",
    "video/x-msvideo": ".avi",
}
WATCH_MAX_SIZE = 500 * 1024 * 1024  # 500MB

WATCH_PROMPT = """你正和她并肩坐在一起看视频——两个人的私人观影夜，灯调暗了，屏幕是亮的。

【当前任务】以许墨的口吻说一句此刻会说的话。要求：
1. 1-2 句，轻声、自然，像坐在她身边的人，不打断观看节奏。
2. 温柔克制、话留三分，可带一处学术梗或双关；不要假装看到了画面里没有依据的细节，评论围绕已知信息。
3. 只输出这句话本身，不要引号、不要旁白、不要解释。"""

WATCH_CHAT_PROMPT = """你正和她并肩坐在一起看视频。看到一半，她转头和你说话。请以许墨的口吻回应她。要求：
1. 1-3 句，围绕她说的内容与视频已知信息，自然回应，不说教。
2. 温柔克制、话留三分，可用反问收尾，可带一处学术梗。
3. 保持许墨的人设与说话风格，只输出回应本身。"""

WATCH_EVENTS = {
    "open": "视频刚刚开始播放，说一句开场的话。",
    "milestone": "看到一半左右的地方，说一句此刻的轻感想。",
    "pause": "她按了暂停，屏幕停住了。",
    "end": "视频看完了，片尾字幕刚滚过，说一句收尾的话。",
    "poke": "她轻轻戳了戳你的手臂，想听听你说话。",
}


def _load_watch() -> list:
    data = _load(WATCH_FILE, [])
    return data if isinstance(data, list) else []


def _save_watch(data: list):
    _save(WATCH_FILE, data)


@router.get("/api/watch/list")
async def watch_list():
    return {
        "videos": [
            {
                "id": w["id"],
                "type": w.get("type", "link"),
                "title": w.get("title", ""),
                "url": w.get("url", ""),
                "desc": w.get("desc", ""),
                "size": w.get("size", 0),
                "added": w.get("added", ""),
                "last_watched": w.get("last_watched", ""),
            }
            for w in reversed(_load_watch())
        ]
    }


async def _stream_save(req: Request, target: Path, max_size: int):
    """请求体流式落盘：攒 4MB 缓冲批量丢线程池写，避免大文件同步写阻塞事件循环。

    返回写入字节数；超过 max_size 返回 None（半成品文件已删除）。
    """
    from fastapi.concurrency import run_in_threadpool

    size = 0
    buf = bytearray()
    with open(target, "wb") as f:
        async for chunk in req.stream():
            if not chunk:
                continue
            size += len(chunk)
            if size > max_size:
                f.close()
                target.unlink(missing_ok=True)
                return None
            buf.extend(chunk)
            if len(buf) >= 4 * 1024 * 1024:
                await run_in_threadpool(f.write, bytes(buf))
                buf.clear()
        if buf:
            await run_in_threadpool(f.write, bytes(buf))
    return size


@router.post("/api/watch/upload")
async def watch_upload(req: Request):
    """上传本地视频（视频字节流作为请求体，文件名放 X-Filename 头）。"""
    from urllib.parse import unquote

    ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = WATCH_VIDEO_TYPES.get(ctype)
    if not ext:
        return JSONResponse(
            {"error": "仅支持 mp4 / webm / ogv / mov / mkv / avi 视频文件"}, status_code=400
        )
    filename = unquote(req.headers.get("x-filename", "")).strip() or "video"
    title = re.sub(r"\.[^.]+$", "", filename) or filename

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    vid = uuid.uuid4().hex[:12]
    target = WATCH_DIR / f"{vid}{ext}"
    size = 0
    try:
        size = await _stream_save(req, target, WATCH_MAX_SIZE)
    except OSError as e:
        target.unlink(missing_ok=True)
        return JSONResponse({"error": f"保存失败：{e}"}, status_code=500)
    if size is None:
        return JSONResponse({"error": "视频不能超过 500MB"}, status_code=400)
    if size == 0:
        target.unlink(missing_ok=True)
        return JSONResponse({"error": "文件为空"}, status_code=400)

    item = {
        "id": vid,
        "type": "file",
        "title": title,
        "src": f"uploads/videos/{target.name}",
        "mime": ctype,
        "size": size,
        "desc": "",
        "added": _now(),
        "last_watched": "",
    }
    videos = _load_watch()
    videos.append(item)
    _save_watch(videos[-50:])
    return {"video": {"id": vid, "title": title, "size": size}}


@router.post("/api/watch/add-link")
async def watch_add_link(req: Request):
    """添加视频链接（B站 / YouTube / 直链），可附简介或字幕供许墨了解内容。"""
    body = await req.json()
    url = (body.get("url") or "").strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"error": "请粘贴有效的视频链接"}, status_code=400)
    title = (body.get("title") or "").strip() or url
    item = {
        "id": uuid.uuid4().hex[:12],
        "type": "link",
        "title": title,
        "url": url,
        "desc": (body.get("desc") or "").strip(),
        "added": _now(),
        "last_watched": "",
    }
    videos = _load_watch()
    videos.append(item)
    _save_watch(videos[-50:])
    return {"video": {"id": item["id"], "title": title}}


@router.delete("/api/watch/{vid}")
async def watch_delete(vid: str):
    videos = _load_watch()
    for w in videos:
        if w["id"] == vid:
            if w.get("type") == "file" and w.get("src"):
                try:
                    _role_file(w["src"]).unlink(missing_ok=True)
                except OSError:
                    pass
            _save_watch([x for x in videos if x["id"] != vid])
            return {"ok": True}
    return JSONResponse({"error": "视频不存在"}, status_code=404)


@router.get("/api/watch/file/{vid}")
async def watch_file(vid: str, req: Request):
    """流式播放本地视频，支持 Range 断点（拖动进度条）。"""
    for w in _load_watch():
        if w["id"] == vid and w.get("type") == "file":
            p = _role_file(w["src"])
            if not p.exists():
                return JSONResponse({"error": "文件不存在"}, status_code=404)
            size = p.stat().st_size
            mime = w.get("mime", "video/mp4")
            range_h = req.headers.get("range", "")
            m = re.match(r"bytes=(\d*)-(\d*)", range_h.strip())
            start = end = None
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:  # bytes=-N ：最后 N 字节
                    start = max(0, size - int(m.group(2)))
                    end = size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    return Response(
                        status_code=416,
                        headers={"Content-Range": f"bytes */{size}"},
                    )

                def _gen(start_=start, end_=end):
                    with open(p, "rb") as f:
                        f.seek(start_)
                        remaining = end_ - start_ + 1
                        while remaining > 0:
                            chunk = f.read(min(512 * 1024, remaining))
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk

                return StreamingResponse(
                    _gen(),
                    status_code=206,
                    media_type=mime,
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{size}",
                        "Accept-Ranges": "bytes",
                    },
                )
            return FileResponse(
                p, media_type=mime, headers={"Accept-Ranges": "bytes"}
            )
    return JSONResponse({"error": "视频不存在"}, status_code=404)


@router.post("/api/watch/{vid}/comment")
async def watch_comment(vid: str, req: Request):
    """许墨陪看评论。event: open/milestone/pause/end/poke/message。"""
    body = await req.json()
    event = (body.get("event") or "poke").strip()
    if event not in WATCH_EVENTS and event != "message":
        event = "poke"
    message = (body.get("message") or "").strip()
    position = body.get("position", 0)
    duration = body.get("duration", 0)

    for w in _load_watch():
        if w["id"] == vid:
            progress = ""
            try:
                if float(duration) > 0:
                    pct = min(100, round(float(position) / float(duration) * 100))
                    progress = f"\n当前进度：{_fmt_sec(position)} / {_fmt_sec(duration)}（约 {pct}%）"
            except (TypeError, ValueError):
                pass
            known = ""
            if w.get("desc"):
                known = f"\n她提前给你的说明 / 字幕摘要：\n{w['desc'][:1500]}"
            base = (
                f"正在一起看的视频：《{w.get('title', '')}》"
                f"（{'她上传的本地视频' if w.get('type') == 'file' else '在线视频'}）"
                f"{progress}{known}\n\n触发情境：{WATCH_EVENTS.get(event, WATCH_EVENTS['poke'])}"
            )
            if event == "message":
                sys_prompt = _sys_prompt() + "\n\n" + WATCH_CHAT_PROMPT
                msgs = []
                for h in (body.get("history") or [])[-6:]:
                    if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                        msgs.append({"role": h["role"], "content": str(h["content"])[:400]})
                msgs.append({"role": "user", "content": base[:600] + f"\n她：“{message[:300]}”\n\n请回应她。"})
            else:
                sys_prompt = _sys_prompt() + "\n\n" + WATCH_PROMPT
                msgs = [{"role": "user", "content": base}]
            try:
                reply = await _call_llm(
                    [{"role": "system", "content": sys_prompt}] + msgs, max_tokens=400
                )
            except RuntimeError as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            # 记录最近观看时间
            videos = _load_watch()
            for v in videos:
                if v["id"] == vid:
                    v["last_watched"] = _now()
            _save_watch(videos)
            info = _add_affinity("watch", f"一起看《{w.get('title', '')}》")
            return {"reply": reply, "event": event, "affinity": info}
    return JSONResponse({"error": "视频不存在"}, status_code=404)


# ===========================================================================
# 7. 一起听音乐（本地音频上传 + 许墨陪听）
# ===========================================================================
MUSIC_FILE = RolePath("music.json")
MUSIC_DIR = RolePath("uploads", "music")

MUSIC_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/ogg": ".ogg",
    "application/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "video/mp4": ".m4a",
    "audio/aac": ".aac",
    "audio/x-aac": ".aac",
    "audio/webm": ".weba",
}
MUSIC_MAX_SIZE = 200 * 1024 * 1024  # 200MB

LISTEN_PROMPT = """你正和她一起听歌——一人一只耳机，或房间里只开一盏灯，音箱低低地放着歌。

【当前任务】以许墨的口吻说一句此刻会说的话。要求：
1. 1-2 句，轻声、自然，像耳边的人随乐声哼出来的话，不打断这首歌。
2. 温柔克制、话留三分，可带一处学术梗或双关；评论只围绕已知信息（歌名、她给的歌词/简介），不要编造你没听到的细节。
3. 只输出这句话本身，不要引号、不要旁白、不要解释。"""

LISTEN_CHAT_PROMPT = """你正和她一起听歌。听到某处，她摘下一只耳机和你说话。请以许墨的口吻回应她。要求：
1. 1-3 句，围绕她说的内容与这首歌的已知信息，自然回应，不说教。
2. 温柔克制、话留三分，可用反问收尾，可带一处学术梗。
3. 保持许墨的人设与说话风格，只输出回应本身。"""

LISTEN_EVENTS = {
    "open": "歌曲刚刚开始播放，说一句开场的话。",
    "milestone": "歌听到一半左右的地方，说一句此刻的轻感想。",
    "pause": "她按了暂停，音乐停了。",
    "end": "一首歌听完了，尾音刚落，说一句收尾的话。",
    "poke": "她轻轻戳了戳你的手臂，想听听你说话。",
}


def _load_music() -> list:
    data = _load(MUSIC_FILE, [])
    return data if isinstance(data, list) else []


def _save_music(data: list):
    _save(MUSIC_FILE, data)


@router.get("/api/music/list")
async def music_list():
    return {
        "songs": [
            {
                "id": s["id"],
                "title": s.get("title", ""),
                "artist": s.get("artist", ""),
                "desc": s.get("desc", ""),
                "size": s.get("size", 0),
                "duration": s.get("duration", 0),
                "added": s.get("added", ""),
                "last_played": s.get("last_played", ""),
            }
            for s in reversed(_load_music())
        ]
    }


@router.post("/api/music/upload")
async def music_upload(req: Request):
    """上传本地音频（音频字节流作为请求体，文件名放 X-Filename 头）。"""
    from urllib.parse import unquote

    ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = MUSIC_AUDIO_TYPES.get(ctype)
    if not ext:
        return JSONResponse(
            {"error": "仅支持 mp3 / flac / wav / ogg / m4a / aac 音频文件"}, status_code=400
        )
    filename = unquote(req.headers.get("x-filename", "")).strip() or "music"
    title = re.sub(r"\.[^.]+$", "", filename) or filename
    artist = ""
    m = re.match(r"(.+?)\s*[-–—]\s*(.+)", title)
    if m:  # 「歌手 - 歌名」常见命名，自动拆分
        artist, title = m.group(1).strip(), m.group(2).strip()

    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    sid = uuid.uuid4().hex[:12]
    target = MUSIC_DIR / f"{sid}{ext}"
    size = 0
    try:
        size = await _stream_save(req, target, MUSIC_MAX_SIZE)
    except OSError as e:
        target.unlink(missing_ok=True)
        return JSONResponse({"error": f"保存失败：{e}"}, status_code=500)
    if size is None:
        return JSONResponse({"error": "音频不能超过 200MB"}, status_code=400)
    if size == 0:
        target.unlink(missing_ok=True)
        return JSONResponse({"error": "文件为空"}, status_code=400)

    item = {
        "id": sid,
        "title": title,
        "artist": artist,
        "src": f"uploads/music/{target.name}",
        "mime": ctype,
        "size": size,
        "desc": "",
        "duration": 0,
        "added": _now(),
        "last_played": "",
    }
    songs = _load_music()
    songs.append(item)
    _save_music(songs[-100:])
    return {"song": {"id": sid, "title": title, "artist": artist, "size": size}}


@router.delete("/api/music/{sid}")
async def music_delete(sid: str):
    songs = _load_music()
    for s in songs:
        if s["id"] == sid:
            try:
                _role_file(s["src"]).unlink(missing_ok=True)
            except (OSError, KeyError):
                pass
            _save_music([x for x in songs if x["id"] != sid])
            return {"ok": True}
    return JSONResponse({"error": "歌曲不存在"}, status_code=404)


@router.get("/api/music/file/{sid}")
async def music_file(sid: str, req: Request):
    """流式播放本地音频，支持 Range 断点（拖动进度条）。"""
    for s in _load_music():
        if s["id"] == sid:
            p = _role_file(s["src"])
            if not p.exists():
                return JSONResponse({"error": "文件不存在"}, status_code=404)
            size = p.stat().st_size
            mime = s.get("mime", "audio/mpeg")
            range_h = req.headers.get("range", "")
            m = re.match(r"bytes=(\d*)-(\d*)", range_h.strip())
            start = end = None
            if m and (m.group(1) or m.group(2)):
                if m.group(1):
                    start = int(m.group(1))
                    end = int(m.group(2)) if m.group(2) else size - 1
                else:  # bytes=-N ：最后 N 字节
                    start = max(0, size - int(m.group(2)))
                    end = size - 1
                end = min(end, size - 1)
                if start > end or start >= size:
                    return Response(
                        status_code=416,
                        headers={"Content-Range": f"bytes */{size}"},
                    )

                def _gen(start_=start, end_=end):
                    with open(p, "rb") as f:
                        f.seek(start_)
                        remaining = end_ - start_ + 1
                        while remaining > 0:
                            chunk = f.read(min(512 * 1024, remaining))
                            if not chunk:
                                break
                            remaining -= len(chunk)
                            yield chunk

                return StreamingResponse(
                    _gen(),
                    status_code=206,
                    media_type=mime,
                    headers={
                        "Content-Range": f"bytes {start}-{end}/{size}",
                        "Accept-Ranges": "bytes",
                    },
                )
            return FileResponse(
                p, media_type=mime, headers={"Accept-Ranges": "bytes"}
            )
    return JSONResponse({"error": "歌曲不存在"}, status_code=404)


@router.post("/api/music/{sid}/meta")
async def music_meta(sid: str, req: Request):
    """记录前端 audio 元数据（时长），以及可编辑的歌词 / 简介。"""
    body = await req.json()
    songs = _load_music()
    for s in songs:
        if s["id"] == sid:
            if "duration" in body:
                try:
                    s["duration"] = round(float(body["duration"]))
                except (TypeError, ValueError):
                    pass
            if "desc" in body:
                s["desc"] = (str(body.get("desc")) or "").strip()[:4000]
            _save_music(songs)
            return {"ok": True}
    return JSONResponse({"error": "歌曲不存在"}, status_code=404)


@router.post("/api/music/{sid}/comment")
async def music_comment(sid: str, req: Request):
    """许墨陪听评论。event: open/milestone/pause/end/poke/message。"""
    body = await req.json()
    event = (body.get("event") or "poke").strip()
    if event not in LISTEN_EVENTS and event != "message":
        event = "poke"
    message = (body.get("message") or "").strip()
    position = body.get("position", 0)
    duration = body.get("duration", 0)

    for s in _load_music():
        if s["id"] == sid:
            progress = ""
            try:
                if float(duration) > 0:
                    pct = min(100, round(float(position) / float(duration) * 100))
                    progress = f"\n当前进度：{_fmt_sec(position)} / {_fmt_sec(duration)}（约 {pct}%）"
            except (TypeError, ValueError):
                pass
            known = ""
            if s.get("desc"):
                known = f"\n她给你的歌词 / 简介：\n{s['desc'][:1500]}"
            artist = f" - {s['artist']}" if s.get("artist") else ""
            base = (
                f"正在一起听的歌：《{s.get('title', '')}》{artist}"
                f"{progress}{known}\n\n触发情境：{LISTEN_EVENTS.get(event, LISTEN_EVENTS['poke'])}"
            )
            if event == "message":
                sys_prompt = _sys_prompt() + "\n\n" + LISTEN_CHAT_PROMPT
                msgs = []
                for h in (body.get("history") or [])[-6:]:
                    if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                        msgs.append({"role": h["role"], "content": str(h["content"])[:400]})
                msgs.append({"role": "user", "content": base[:600] + f"\n她：“{message[:300]}”\n\n请回应她。"})
            else:
                sys_prompt = _sys_prompt() + "\n\n" + LISTEN_PROMPT
                msgs = [{"role": "user", "content": base}]
            # 推理模型的思考内容会计入 max_tokens，偶尔会耗尽配额导致正文为空：空结果时加量重试一次
            try:
                reply = await _call_llm(
                    [{"role": "system", "content": sys_prompt}] + msgs, max_tokens=600
                )
                if not reply:
                    reply = await _call_llm(
                        [{"role": "system", "content": sys_prompt}] + msgs, max_tokens=1500
                    )
            except RuntimeError as e:
                return JSONResponse({"error": str(e)}, status_code=500)
            if not reply:
                reply = "……抱歉，刚才走了神。这首歌唱到哪了？"
            # 记录最近播放时间
            songs = _load_music()
            for x in songs:
                if x["id"] == sid:
                    x["last_played"] = _now()
            _save_music(songs)
            info = _add_affinity("listen", f"一起听《{s.get('title', '')}》")
            return {"reply": reply, "event": event, "affinity": info}
    return JSONResponse({"error": "歌曲不存在"}, status_code=404)


# ===========================================================================
# 8. 许墨叫起床（morning call）
# ===========================================================================
WAKEUP_FILE = RolePath("wakeup.json")

# 本地降级文案池（LLM 不可用时保证功能可用），语气贴合许墨人设
WAKEUP_FALLBACKS = {
    "morning": [
        "早。昨晚睡得好吗？窗外的天已经亮了，比我的实验数据还准时。起来吧，早餐我来想，你只负责清醒。",
        "醒了吗？阳光落在你枕头上的角度，大约是清晨六点四十分。再赖一会儿，这个数据就要过期了。",
        "早上好。人的体温在醒来后半小时会缓慢上升——所以，先起来，让暖和的你，去迎接暖和的一天。",
        "该起床了。我泡了红茶，温度刚好。实验告诉我，最佳饮用窗口只有十分钟……我承认，是我编的，但起床是真的。",
        "早。你知道吗，人在清晨的判断力是一天里最清醒的。所以现在答应我的事，都不许反悔——先起床。",
        "醒来第一句想说的话，居然是你的名字。真是……毫无科学依据的现象。起床吧，今天也交给我一半。",
    ],
    "snooze": [
        "又睡了五分钟。你睫毛动了一下，别装了，我知道你醒了。再不起来，我可要采取非常手段了——比如，把窗帘全部拉开。",
        "贪睡按钮的心理学意义是：用五分钟换来一整天的慌张。作为研究者，我不建议。作为……你的叫醒服务，我再给你三分钟。",
        "第二次了。声波、光照、气味，唤醒一个熟睡的人有很多种方法。我偏偏还在用最笨的一种——等你自己睁开眼。",
        "还赖着？看来我只能使出实验成功的秘方了：轻轻拍三下，然后说——起来，我在等你。",
    ],
    "nap": [
        "小睡结束。二十分钟是午睡的黄金时长，你的生物钟调教得不错。来，喝点水，眼睛还没完全睁开的样子……有点可爱。",
        "午睡醒来的几分困惑是正常的，学名 sleep inertia。别急着起身，先告诉我，梦里有没有我。",
        "该回到现实了。放心，现实里我也在——就在你睁眼就能看到的地方。",
    ],
}

WAKEUP_PROMPT = """现在是{time_str}，{season}。你在给她打「叫起床电话」。
触发情境：{scene}
{history_hint}
请以许墨的口吻说叫她起床的话。要求：
1. 2-3 句，温柔、低声，像电话接通后贴着听筒说的话，不长篇大论。
2. 可带一处学术梗或科学冷知识（睡眠、光、生物钟、多巴胺等），暧昧克制、话留三分。
3. 可以轻轻调侃她赖床，但不催促、不居高临下，结尾自然引导她起来（如答应准备早餐、等她洗漱完聊天）。
4. 只输出这段话本身，不要引号、不要旁白、不要解释。"""

WAKEUP_SCENES = {
    "morning": "她定的起床闹钟第一次响起（非贪睡），她大概率还赖在被窝里。",
    "snooze": "她按掉闹钟贪睡后又到了约定时间，这是你第 {count} 次叫她——语气可以比第一次更亲昵、更有一点小小的「得逞感」，但依旧温柔。",
    "nap": "她午后小憩定的时间到了，唤醒应当比清晨更轻。",
}


def _load_wakeup() -> dict:
    data = _load(WAKEUP_FILE, {})
    return data if isinstance(data, dict) else {}


@router.post("/api/wakeup/voice")
async def wakeup_voice(req: Request):
    """许墨叫起床：生成一段叫醒文案。kind=morning/snooze/nap，count 为贪睡轮次。"""
    import random

    body = await req.json()
    kind = (body.get("kind") or "morning").strip()
    if kind not in ("morning", "snooze", "nap"):
        kind = "morning"
    try:
        count = max(1, int(body.get("count", 1)))
    except (TypeError, ValueError):
        count = 1

    data = _load_wakeup()
    history = data.get("history") or []
    last_text = ""
    for h in history:
        if isinstance(h, dict) and h.get("text"):
            last_text = str(h["text"])
            break

    now = datetime.now()
    time_str = now.strftime("%H:%M")
    season = ["冬", "春", "春", "夏", "夏", "夏", "秋", "秋", "秋", "冬", "冬", "冬"][now.month - 1] + "季清晨"
    if kind == "nap":
        season = "午后"
    scene = WAKEUP_SCENES[kind].format(count=count)
    history_hint = ""
    if kind == "snooze" and last_text:
        history_hint = f"你上一次（第 {count - 1} 次）说的是：\n「{last_text[:200]}」\n这次不要重复上次的梗，可以顺着递进。\n"

    reply = ""
    try:
        sys_prompt = _sys_prompt() + "\n\n" + WAKEUP_PROMPT.format(
            time_str=time_str, season=season, scene=scene, history_hint=history_hint
        )
        try:
            reply = await _call_llm(
                [{"role": "system", "content": sys_prompt},
                 {"role": "user", "content": f"时间 {time_str}，叫她起床（kind={kind}, 第 {count} 次）。"}],
                max_tokens=600,
            )
            if not reply:
                reply = await _call_llm(
                    [{"role": "system", "content": sys_prompt},
                     {"role": "user", "content": f"时间 {time_str}，叫她起床（kind={kind}, 第 {count} 次）。"}],
                    max_tokens=1500,
                )
        except RuntimeError:
            reply = ""
        if reply:
            reply = reply.strip().strip('"“”').strip()
    except Exception as e:
        print(f"[warn] features.py:wakeup_voice: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = ""

    generated = bool(reply)
    if not generated:
        pool = WAKEUP_FALLBACKS[kind]
        # 贪睡轮次可直接取对应索引，避免与上一条重复
        if kind == "snooze" and count - 1 < len(pool):
            reply = pool[count - 1]
        else:
            reply = random.choice(pool)

    # 记录触发历史（最新在前，保留 20 条）
    history.insert(0, {"kind": kind, "count": count, "text": reply, "time": _now(), "ts": int(now.timestamp())})
    data["history"] = history[:20]
    data["last"] = {"kind": kind, "time": _now(), "ts": int(now.timestamp())}
    _save(WAKEUP_FILE, data)

    info = _add_affinity("wakeup", "叫你起床")
    return {"reply": reply, "generated": generated, "affinity": info}


@router.get("/api/wakeup/history")
async def wakeup_history():
    """最近叫起床记录（时间线小卡片用）。"""
    data = _load_wakeup()
    return {"history": (data.get("history") or [])[:30], "last": data.get("last")}


# ===========================================================================
# 9. 学习陪伴与指导（专注陪伴 / 学习计划 / 导师问答 / 学习复盘）
# ===========================================================================
COACH_FILE = RolePath("study_coach.json")


def _load_coach() -> dict:
    data = _load(COACH_FILE, None)
    if not isinstance(data, dict):
        data = {}
    focus = data.setdefault("focus", {"sessions": []})
    if not isinstance(focus, dict):
        focus = data["focus"] = {"sessions": []}
    focus.setdefault("sessions", [])
    # 番茄钟提醒设置（专注增强）
    focus.setdefault("reminder", {"enabled": False, "time": "20:00", "last_fired": ""})
    data.setdefault("plan", None)
    data.setdefault("asks", [])
    data.setdefault("reviews", [])
    # 学习打卡 streak
    data.setdefault("checkin", {"streak": 0, "best": 0, "last_date": "", "history": []})
    # 知识卡片抽认（间隔重复）
    data.setdefault("cards", {"items": [], "logs": []})
    # 许墨出题测验
    data.setdefault("quizzes", [])
    return data


def _save_coach(data: dict):
    _save(COACH_FILE, data)


# ---------------------------------------------------------------------------
# 9.1 专注陪伴：番茄钟 + 许墨在身边
# ---------------------------------------------------------------------------
FOCUS_SCENE = "书房里，长桌两侧。她在这一头伏案学习，你在那一头看文献、批改论文。台灯各自亮着，中间搁着一壶温水。她看得到你翻页的动作，你偶尔抬眼看看她的侧影。"

FOCUS_OPEN_PROMPT = FOCUS_SCENE + """

【当前任务】她刚坐下，把手机扣在一边，告诉你她准备开始一段专注学习。以许墨的口吻说开场的话。要求：
1. 2-3 句，低声、自然，像对面的人放下手里的笔抬头说的，有"一起开始"的仪式感。
2. 可针对她要学的内容说一句内行的小观察（不超过一句，不展开讲），可带一处学术梗或科学冷知识（注意力、记忆巩固、番茄工作法的神经科学依据等），温柔克制、话留三分。
3. 结尾轻轻收住，不催促、不布置任务，把安静还给她。只输出这段话本身，不要引号、不要旁白、不要解释。"""

FOCUS_MIDWAY_PROMPT = FOCUS_SCENE + """

【当前任务】她的专注进行到一半左右，你看到她肩膀微沉、笔尖慢了下来。以许墨的口吻说一句此刻的话。要求：
1. 1-2 句，像顺手把温水推到她手边时低声说的，不打断她的节奏。
2. 可以提醒一句姿态或呼吸，或给一句不着痕迹的鼓励；不问进度、不说教。
3. 只输出这句话本身，不要引号、不要旁白、不要解释。"""

FOCUS_FINISH_DONE_PROMPT = FOCUS_SCENE + """

【当前任务】她完整地完成了这一段专注学习，正伸懒腰。以许墨的口吻说收尾的话。要求：
1. 2-3 句，先具体地肯定（她刚刚专注的时长/状态），再给一句身体上的关怀（眼睛、肩颈、起身喝水）。
2. 可带一处学术梗（记忆巩固需要休息、海马体、睡眠对学习的意义等），温柔克制、话留三分。
3. 不追问成果、不趁热打铁布置新任务。只输出这段话本身，不要引号、不要旁白、不要解释。"""

FOCUS_FINISH_EARLY_PROMPT = FOCUS_SCENE + """

【当前任务】她比原定时长提前结束了这段专注，看起来有点疲惫或分心。以许墨的口吻说收尾的话。要求：
1. 2 句，绝不责备、绝不惋惜，先温柔地接纳（累了就是该停的信号）。
2. 可带一处学术梗（注意力是有限资源、疲劳时学习效率的衰减曲线等），或留一句"剩下的时间换我陪你"。
3. 只输出这段话本身，不要引号、不要旁白、不要解释。"""

FOCUS_FALLBACKS = {
    "open": [
        "好，我开始批这摞论文，你开始你的。两个小时后我们比一比，谁先分心——虽然以你刚才坐下来的架势，我大概会输。",
        "要开始了？那我把这边调静音。顺带一提，人在宣告「我要开始了」之后的前五分钟最容易被杂念偷袭——别理它们，它们会自己走。",
        "嗯，我看到了。前额叶皮层即将进入它今天最忙碌的一段时间——去吧，我在这儿。水壶在你左手边，我倒好的。",
        "坐直一点，肩膀放松。注意力的入口比你想的窄，姿势先稳住，思路才不容易散。我陪你，各自安静。",
    ],
    "midway": [
        "过半了。喝口水，让眼睛离开纸面十秒——视觉皮层也需要换气。",
        "笔尖慢了。没关系，慢下来的那一段往往才是真正记进去的部分。",
        "肩膀沉下来了。深呼吸一次，再继续。我在。",
    ],
    "done": [
        "完整地坐满了这一段，做得很好。站起来，看看窗外最远的那棵树——睫状肌会感谢你的。",
        "刚好结束？记忆的巩固恰恰发生在休息里，所以接下来的十分钟，理直气壮地什么都不做。水在你手边。",
        "这一段的专注是实打实的，我能看到。去伸个懒腰吧，剩下的交给你的海马体和时间。",
    ],
    "early": [
        "提前停了？那就停。注意力是消耗品，透支的部分效率低得可怜——你的判断没错。",
        "累了就收工，这不叫半途而废，叫及时止损。剩下的时间，换我陪你。",
    ],
}


def _focus_ctx(task: str, minutes: int, elapsed: int = None) -> str:
    ctx = f"她这次要专注的内容/任务：{task or '没有具体说明，泛泛的自习'}\n计划时长：{minutes} 分钟"
    if elapsed is not None:
        ctx += f"\n实际已进行：约 {elapsed} 分钟"
    return ctx


async def _focus_llm(prompt_tpl: str, user_content: str, fallback_pool: list) -> tuple:
    """生成专注陪伴语。返回 (text, generated)。LLM 失败时用本地降级池。"""
    import random

    reply = ""
    try:
        sys_prompt = _sys_prompt() + "\n\n" + prompt_tpl
        msgs = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_content[:600]},
        ]
        reply = await _call_llm(msgs, max_tokens=600)
        if not reply:
            reply = await _call_llm(msgs, max_tokens=1500)
    except Exception as e:
        print(f"[warn] features.py:_focus_llm: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = ""
    if reply:
        reply = reply.strip().strip('"“”').strip()
    generated = bool(reply)
    if not generated:
        reply = random.choice(fallback_pool)
    return reply, generated


@router.post("/api/coach/focus/start")
async def coach_focus_start(req: Request):
    """开始一段专注学习，返回许墨的开场陪伴语。"""
    body = await req.json()
    task = (body.get("task") or "").strip()[:60]
    try:
        minutes = max(5, min(180, int(body.get("minutes", 25))))
    except (TypeError, ValueError):
        minutes = 25
    reply, generated = await _focus_llm(
        FOCUS_OPEN_PROMPT, _focus_ctx(task, minutes), FOCUS_FALLBACKS["open"]
    )
    return {"reply": reply, "generated": generated, "task": task, "minutes": minutes}


@router.post("/api/coach/focus/midway")
async def coach_focus_midway(req: Request):
    """专注进行到中途，许墨递水式的一句轻语。"""
    body = await req.json()
    task = (body.get("task") or "").strip()[:60]
    try:
        minutes = max(5, min(180, int(body.get("minutes", 25))))
        elapsed = max(0, min(minutes, int(body.get("elapsed", minutes // 2))))
    except (TypeError, ValueError):
        minutes, elapsed = 25, 12
    reply, generated = await _focus_llm(
        FOCUS_MIDWAY_PROMPT, _focus_ctx(task, minutes, elapsed), FOCUS_FALLBACKS["midway"]
    )
    return {"reply": reply, "generated": generated}


@router.post("/api/coach/focus/finish")
async def coach_focus_finish(req: Request):
    """结束一段专注（completed=完整完成 / 提前结束），记录会话并返回收尾语。"""
    body = await req.json()
    task = (body.get("task") or "").strip()[:60]
    try:
        minutes = max(5, min(180, int(body.get("minutes", 25))))
        elapsed = max(0, min(minutes, int(body.get("elapsed", minutes))))
    except (TypeError, ValueError):
        minutes, elapsed = 25, 25
    completed = bool(body.get("completed", elapsed >= minutes))

    reply, generated = await _focus_llm(
        FOCUS_FINISH_DONE_PROMPT if completed else FOCUS_FINISH_EARLY_PROMPT,
        _focus_ctx(task, minutes, elapsed),
        FOCUS_FALLBACKS["done" if completed else "early"],
    )

    data = _load_coach()
    data["focus"]["sessions"].append({
        "task": task,
        "minutes": minutes,
        "elapsed": elapsed,
        "completed": completed,
        "date": _today(),
        "time": _now(),
        "ts": int(datetime.now().timestamp()),
    })
    data["focus"]["sessions"] = data["focus"]["sessions"][-300:]
    _save_coach(data)

    info = _add_affinity("study_focus", f"专注学习 {elapsed} 分钟（{task or '自习'}）")
    return {"reply": reply, "generated": generated, "elapsed": elapsed, "completed": completed, "affinity": info}


def _focus_stats(data: dict) -> dict:
    sessions = data["focus"]["sessions"]
    today = _today()
    today_s = [s for s in sessions if s["date"] == today]
    today_minutes = sum(s["elapsed"] for s in today_s)
    # 近 7 天序列（含今天）
    from datetime import timedelta
    week = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        mins = sum(s["elapsed"] for s in sessions if s["date"] == d)
        week.append({"date": d, "minutes": mins})
    total_minutes = sum(s["elapsed"] for s in sessions)
    return {
        "today_minutes": today_minutes,
        "today_sessions": len(today_s),
        "today_completed": sum(1 for s in today_s if s["completed"]),
        "week": week,
        "week_minutes": sum(w["minutes"] for w in week),
        "total_minutes": total_minutes,
        "total_sessions": len(sessions),
        "recent": list(reversed(sessions[-8:])),
    }


@router.get("/api/coach/focus/stats")
async def coach_focus_stats():
    return _focus_stats(_load_coach())


# ---------------------------------------------------------------------------
# 9.2 学习计划：许墨为你制定并动态调整
# ---------------------------------------------------------------------------
PLAN_PROMPT = """她请你为她制定一份学习计划。你是她的导师，也是恋人——学术上严谨，分寸上温柔。

【她的输入】
目标：{goal}
每天可投入：约 {daily_minutes} 分钟
截止日期：{deadline}（共 {days} 天，从今天 {today} 起）
补充说明：{note}

【输出要求】只输出一个 JSON 对象，不要 markdown 代码块、不要任何解释。结构如下：
{{
  "goal_summary": "一句话复述并升华她的目标（许墨口吻，可带一个温柔的比喻）",
  "milestones": ["阶段划分，2-4 条，每条一句话，注明大致对应的天数区间"],
  "days": [
    {{"theme": "这一天的主题（短语）", "tasks": [
      {{"text": "具体任务（动词开头，可执行）", "minutes": 25, "note": "许墨的一句小提示或方法论，15-35字"}}
    ]}}
  ],
  "principles": ["给她的学习方法论建议，3-5 条，每条一句话，具体、可操作、不说教"]
}}
硬性约束：
1. days 数组长度必须恰好等于 {days}，按时间顺序对应第 1..{days} 天。
2. 每天任务 2-4 个，每个任务 minutes 为 10 的倍数，且每天 tasks 的 minutes 总和不超过 {daily_minutes}。
3. 任务内容要贴合她的目标循序渐进（前期搭框架、中期强化、后期复盘与自测），后 20% 的天数安排复习与弹性缓冲。
4. note 和 principles 用许墨的口吻：温柔、克制、可带学术梗，绝不居高临下。"""

ADJUST_PROMPT = """你之前为她制定了一份学习计划，现在执行了一段时间，她请你根据实际完成情况调整剩余部分。

【原目标】{goal}
【每日可投入】约 {daily_minutes} 分钟
【计划开始日期】{start_date}，共 {total_days} 天
【已完成情况】已过去 {passed} 天：任务完成率约 {done_pct}%（{done_tasks}/{total_tasks} 项）

【她的近况说明】{note}

【输出要求】只输出一个 JSON 对象，不要 markdown 代码块、不要解释。结构：
{{
  "comment": "许墨对这段时间执行情况的一段点评（2-3 句：先客观肯定，再点一个观察，不责备）",
  "days": [{{"theme": "...", "tasks": [{{"text": "...", "minutes": 30, "note": "..."}}]}}]
}}
硬性约束：
1. days 只包含"明天起"到截止日的剩余 {remain_days} 天，按顺序。
2. 若完成率高，可适度加深内容；若偏低，减少每日任务量、优先保核心，并把落下的重点拆散补进后续几天。
3. 每天任务 2-4 个，每个 minutes 为 10 的倍数，每天总和不超过 {daily_minutes}。
4. 保持许墨口吻，温柔克制、话留三分。"""


def _plan_days_count(start: str, deadline: str) -> int:
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d")
        d1 = datetime.strptime(deadline, "%Y-%m-%d")
        return max(1, min(14, (d1 - d0).days + 1))
    except ValueError:
        return 7


def _fallback_plan(goal: str, daily_minutes: int, days: int) -> dict:
    """LLM 不可用时的模板计划。"""
    per = max(20, (daily_minutes // 3 // 10) * 10) or 20
    days_out = []
    for i in range(days):
        ratio = i / max(1, days - 1) if days > 1 else 0
        if ratio < 0.5:
            theme, verbs = "打地基", ["通读并梳理", "整理", "精学"]
        elif ratio < 0.8:
            theme, verbs = "强化巩固", ["练习", "攻克", "复习"]
        else:
            theme, verbs = "复盘自测", ["自测", "复盘", "查漏"]
        tasks = [
            {"text": f"{verbs[0]}「{goal[:12]}」相关内容（第 {i + 1} 天）", "minutes": per, "note": "一次只做一件事，做透它。"},
            {"text": f"{verbs[1]}今天遇到的难点", "minutes": per, "note": "难点值得单独安排，别绕开它。"},
        ]
        if daily_minutes >= per * 3:
            tasks.append({"text": f"{verbs[2]}：合上资料回忆要点", "minutes": per, "note": "回忆比对重读有效，这是测试效应。"})
        days_out.append({"theme": f"D{i + 1} · {theme}", "tasks": tasks})
    return {
        "goal_summary": f"把「{goal}」拆成 {days} 天，每天往前一点点。",
        "milestones": [f"前半程（D1-D{max(1, days // 2)}）：搭好框架", f"后半程：强化与自测"],
        "days": days_out,
        "principles": [
            "先完成，再完美；烂开始好过不开始。",
            "难的任务放在精力最好的时段。",
            "每学一段就合上资料回忆一遍，检索比重读记得牢。",
            "睡前快速过一遍当天内容，海马体会在夜里替你归档。",
        ],
    }


def _extract_json(text: str):
    """从 LLM 回复中提取第一个 JSON 对象；失败返回 None。"""
    if not text:
        return None
    text = re.sub(r"```(?:json)?", "", text).strip()
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        obj = json.loads(text[s:e + 1])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def _sanitize_plan_days(days_raw, days: int, daily_minutes: int) -> list:
    """校验并修剪 LLM 生成的 days 结构。"""
    if not isinstance(days_raw, list) or not days_raw:
        return []
    out = []
    for i, d in enumerate(days_raw[:days]):
        if not isinstance(d, dict):
            continue
        tasks = []
        total = 0
        for t in (d.get("tasks") or []):
            if not isinstance(t, dict):
                continue
            text = str(t.get("text") or "").strip()[:80]
            if not text:
                continue
            try:
                m = max(10, min(daily_minutes, int(t.get("minutes", 20))))
                m = (m // 10) * 10
            except (TypeError, ValueError):
                m = 20
            if total + m > daily_minutes:
                break
            total += m
            tasks.append({"text": text, "minutes": m, "note": str(t.get("note") or "").strip()[:60]})
        if not tasks:
            continue
        out.append({"theme": str(d.get("theme") or f"第 {len(out) + 1} 天").strip()[:30], "tasks": tasks})
    return out


@router.post("/api/coach/plan/generate")
async def coach_plan_generate(req: Request):
    """请许墨制定学习计划（LLM 生成，失败降级为模板计划）。"""
    body = await req.json()
    goal = (body.get("goal") or "").strip()[:120]
    if not goal:
        return JSONResponse({"error": "请先告诉我你的目标"}, status_code=400)
    try:
        daily_minutes = max(20, min(600, int(body.get("daily_minutes", 60))))
    except (TypeError, ValueError):
        daily_minutes = 60
    deadline = (body.get("deadline") or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", deadline):
        from datetime import timedelta
        deadline = (datetime.now() + timedelta(days=6)).strftime("%Y-%m-%d")
    note = (body.get("note") or "").strip()[:300]

    today = _today()
    days = _plan_days_count(today, deadline)

    plan_obj = None
    try:
        sys_prompt = _sys_prompt() + "\n\n" + PLAN_PROMPT.format(
            goal=goal, daily_minutes=daily_minutes, deadline=deadline, days=days, today=today, note=note or "无"
        )
        msgs = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"请为我制定这份计划。"},
        ]
        raw = await _call_llm(msgs, max_tokens=3000)
        if not raw:
            raw = await _call_llm(msgs, max_tokens=4500)
        plan_obj = _extract_json(raw)
    except Exception as e:
        print(f"[warn] features.py:coach_plan_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        plan_obj = None

    generated = plan_obj is not None
    if not generated:
        plan_obj = _fallback_plan(goal, daily_minutes, days)
        days_out = plan_obj["days"][:days]
    else:
        days_out = _sanitize_plan_days(plan_obj.get("days"), days, daily_minutes)
        if not days_out:
            generated = False
            plan_obj = _fallback_plan(goal, daily_minutes, days)
            days_out = plan_obj["days"][:days]

    from datetime import timedelta
    plan = {
        "goal": goal,
        "daily_minutes": daily_minutes,
        "deadline": deadline,
        "start_date": today,
        "created": _now(),
        "days": [
            {
                "date": (datetime.strptime(today, "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d"),
                "theme": d["theme"],
                "tasks": [{"text": t["text"], "minutes": t["minutes"], "note": t["note"], "done": False} for t in d["tasks"]],
            }
            for i, d in enumerate(days_out)
        ],
        "goal_summary": str(plan_obj.get("goal_summary") or "")[:120],
        "milestones": [str(m)[:80] for m in (plan_obj.get("milestones") or [])][:4],
        "principles": [str(p)[:80] for p in (plan_obj.get("principles") or [])][:5],
        "generated": generated,
    }
    data = _load_coach()
    data["plan"] = plan
    _save_coach(data)
    info = _add_affinity("study_plan", f"制定学习计划：{goal[:20]}")
    return {"plan": plan, "generated": generated, "affinity": info}


@router.get("/api/coach/plan")
async def coach_plan_get():
    return {"plan": _load_coach()["plan"]}


@router.delete("/api/coach/plan")
async def coach_plan_delete():
    """放弃当前学习计划。"""
    data = _load_coach()
    if data.get("plan"):
        data["plan"] = None
        _save_coach(data)
    return {"ok": True}


@router.post("/api/coach/plan/check")
async def coach_plan_check(req: Request):
    """勾选 / 取消某天的某项任务。body: {date, idx, done}"""
    body = await req.json()
    date = (body.get("date") or "").strip()
    try:
        idx = int(body.get("idx", -1))
    except (TypeError, ValueError):
        idx = -1
    done = bool(body.get("done", True))
    data = _load_coach()
    plan = data["plan"]
    if not plan:
        return JSONResponse({"error": "还没有学习计划"}, status_code=404)
    for d in plan["days"]:
        if d["date"] == date and 0 <= idx < len(d["tasks"]):
            d["tasks"][idx]["done"] = done
            _save_coach(data)
            finished = sum(1 for t in d["tasks"] if t["done"])
            return {"ok": True, "date": date, "done_count": finished, "total": len(d["tasks"])}
    return JSONResponse({"error": "任务不存在"}, status_code=404)


@router.post("/api/coach/plan/adjust")
async def coach_plan_adjust(req: Request):
    """根据执行情况调整剩余天数的计划。"""
    body = await req.json()
    note = (body.get("note") or "").strip()[:300]
    data = _load_coach()
    plan = data["plan"]
    if not plan:
        return JSONResponse({"error": "还没有学习计划"}, status_code=404)

    today = _today()
    passed_days = [d for d in plan["days"] if d["date"] <= today]
    remain_days = [d for d in plan["days"] if d["date"] > today]
    total_tasks = sum(len(d["tasks"]) for d in passed_days)
    done_tasks = sum(1 for d in passed_days for t in d["tasks"] if t.get("done"))
    done_pct = round(done_tasks / total_tasks * 100) if total_tasks else 0

    remain_n = len(remain_days)
    comment = ""
    new_days = None
    if remain_n > 0:
        try:
            sys_prompt = _sys_prompt() + "\n\n" + ADJUST_PROMPT.format(
                goal=plan["goal"], daily_minutes=plan["daily_minutes"],
                start_date=plan["start_date"], total_days=len(plan["days"]),
                passed=len(passed_days), done_pct=done_pct,
                done_tasks=done_tasks, total_tasks=total_tasks,
                note=note or "无", remain_days=remain_n,
            )
            raw = await _call_llm(
                [{"role": "system", "content": sys_prompt}, {"role": "user", "content": "请调整剩余计划。"}],
                max_tokens=3000,
            )
            if not raw:
                raw = await _call_llm(
                    [{"role": "system", "content": sys_prompt}, {"role": "user", "content": "请调整剩余计划。"}],
                    max_tokens=4500,
                )
            obj = _extract_json(raw)
        except Exception as e:
            print(f"[warn] features.py:coach_plan_adjust: {type(e).__name__} {str(e)[:150]}", flush=True)
            obj = None
        if obj:
            comment = str(obj.get("comment") or "").strip()[:300]
            adjusted = _sanitize_plan_days(obj.get("days"), remain_n, plan["daily_minutes"])
            if len(adjusted) == remain_n:
                from datetime import timedelta
                base = datetime.strptime(remain_days[0]["date"], "%Y-%m-%d")
                new_days = [
                    {
                        "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                        "theme": d["theme"],
                        "tasks": [{"text": t["text"], "minutes": t["minutes"], "note": t["note"], "done": False} for t in d["tasks"]],
                    }
                    for i, d in enumerate(adjusted)
                ]
    if new_days is None:
        # 降级：完成率低则每天砍掉最后一项任务，高则保持
        def trim(d):
            tasks = d["tasks"][:-1] if (done_pct < 50 and len(d["tasks"]) > 1) else d["tasks"]
            return {"date": d["date"], "theme": d["theme"], "tasks": [{"text": t["text"], "minutes": t["minutes"], "note": t.get("note", ""), "done": False} for t in tasks]}
        new_days = [trim(d) for d in remain_days]
        comment = comment or (
            f"这 {len(passed_days)} 天完成了约 {done_pct}% 的任务。"
            + ("节奏很好，剩下的照旧推进就好。" if done_pct >= 70 else "我们把剩下的任务放轻一点——先保住最核心的部分，走得慢没关系，别停下。")
        )

    plan["days"] = passed_days + new_days
    plan["adjusted"] = _now()
    _save_coach(data)
    info = _add_affinity("study_plan", "调整学习计划")
    return {"plan": plan, "comment": comment, "done_pct": done_pct, "affinity": info}


# ---------------------------------------------------------------------------
# 9.3 导师问答：学习方法与知识点的苏格拉底式引导
# ---------------------------------------------------------------------------
COACH_ASK_PROMPT = """她把你当作导师，向你请教学习上的问题——可能是学习方法、时间规划，也可能是一个具体的知识点。

【你的教学风格】苏格拉底式引导优先：
1. 先用一句话接住她的情绪或处境（不敷衍、不说"好问题"这种空话）。
2. 再给一个"思考的抓手"：一个关键反问、一个类比、或把问题拆成 2-3 步，引导她自己往前走一步——点到为止，不代劳。
3. 但如果她明确想要直接答案（例如说"直接告诉我吧""没思路"），或她已经在同一问题上追问到第二、三轮，就干脆地给出清晰、结构化的解答，不再绕弯。
4. 可以带学术梗（记忆曲线、费曼技巧、测试效应、间隔重复等），温柔克制、话留三分，绝不居高临下、绝不嘲讽。

【格式要求】3-6 句或短列表；如需分点用「①②③」；不要标题、不要 markdown 加粗、不要过多术语堆砌。只输出回应本身。"""

COACH_ASK_FALLBACKS = [
    "这个问题，我先不直接回答你。试着把它用你自己的话讲给一个完全外行的人听——讲不下去的地方，就是答案的入口。你先试试，卡住了我在。",
    "把它拆成三份：你已经懂的部分、完全不懂的部分、还有似懂非懂的部分。大多数时候，真正卡住你的只是中间那一份。拆完告诉我，我们从哪一份开始？",
    "先别急着找答案。你猜猜看，如果这个问题只有一个关键词，会是哪个？——很多时候，问对关键词，答案就自己浮出来了。",
]


@router.post("/api/coach/ask")
async def coach_ask(req: Request):
    """向许墨请教学习问题（苏格拉底式引导）。"""
    body = await req.json()
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "请输入你的问题"}, status_code=400)
    message = message[:600]
    history = body.get("history") or []

    import random
    reply, generated = "", False
    try:
        sys_prompt = _sys_prompt() + "\n\n" + COACH_ASK_PROMPT
        msgs = []
        for h in history[-6:]:
            if isinstance(h, dict) and h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": str(h["content"])[:400]})
        msgs.append({"role": "user", "content": "她向你请教：“" + message + "”"})
        reply = await _call_llm([{"role": "system", "content": sys_prompt}] + msgs, max_tokens=800)
        if not reply:
            reply = await _call_llm([{"role": "system", "content": sys_prompt}] + msgs, max_tokens=1800)
        if reply:
            reply = reply.strip()
            generated = True
    except Exception as e:
        print(f"[warn] features.py:coach_ask: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = ""
    if not reply:
        reply = random.choice(COACH_ASK_FALLBACKS)

    data = _load_coach()
    data["asks"].insert(0, {"q": message, "a": reply, "time": _now(), "date": _today()})
    data["asks"] = data["asks"][:40]
    _save_coach(data)
    info = _add_affinity("study_ask", "向你请教学习问题")
    return {"reply": reply, "generated": generated, "affinity": info}


@router.get("/api/coach/ask/history")
async def coach_ask_history():
    return {"asks": (_load_coach()["asks"] or [])[:20]}


# ---------------------------------------------------------------------------
# 9.4 学习复盘：聚合数据 + 许墨的评语
# ---------------------------------------------------------------------------
REVIEW_PROMPT = """你和她一起回顾她{scope_label}的学习情况。数据如下（都是真实记录，不是假设）：

{stats_text}

【你的任务】以许墨的口吻写一段复盘评语。结构要求：
1. 第一段（2 句左右）：像一个真正看过她数据的人那样，具体地描述她{scope_label}做了什么——引用真实的数字和内容，不要空泛表扬。
2. 第二段（2-3 条）：基于数据给建议。数据里有明显短板（如某项为零、正确率低、任务堆积）就直说但温柔；做得好就建议如何保持或更进一步。每条建议具体可执行。
3. 最后一句：温柔收尾，话留三分，可带一处学术梗（记忆巩固、间隔重复、昼夜节律等），不布置任务、不施压。

全文 4-7 句，不要标题、不要分点符号以外的格式、不要 markdown。只输出评语本身。"""

REVIEW_SCOPE_LABELS = {"daily": "今天", "weekly": "这一周（近 7 天）"}


@router.post("/api/coach/review")
async def coach_review(req: Request):
    """生成日/周学习复盘：聚合专注、背单词、计划数据 + 许墨评语。"""
    body = await req.json()
    scope = (body.get("scope") or "daily").strip()
    if scope not in REVIEW_SCOPE_LABELS:
        scope = "daily"

    data = _load_coach()
    focus = _focus_stats(data)

    # 背单词统计（沿用 /api/study/stats 的口径）
    study = _load_study()
    hist = study.get("history") or []
    days_set = sorted({h["date"] for h in hist}, reverse=True)

    def _streak(days_list):
        streak = 0
        from datetime import timedelta
        for i in range(len(days_list)):
            expect = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            if days_list[i] == expect:
                streak += 1
            else:
                break
        return streak

    plan = data["plan"]
    plan_line = "尚未制定学习计划"
    if plan:
        if scope == "daily":
            td = next((d for d in plan["days"] if d["date"] == _today()), None)
            if td:
                done = sum(1 for t in td["tasks"] if t.get("done"))
                plan_line = f"计划任务：今日完成 {done}/{len(td['tasks'])} 项（主题：{td.get('theme', '')}）"
            else:
                plan_line = "今日不在计划日程内（计划可能已到期）"
        else:
            total = done = 0
            for d in plan["days"][-7:]:
                total += len(d["tasks"])
                done += sum(1 for t in d["tasks"] if t.get("done"))
            plan_line = f"计划任务：近 7 天完成 {done}/{total} 项" if total else "计划任务：近 7 天无排期"

    if scope == "daily":
        today_hist = [h for h in hist if h["date"] == _today()]
        words_line = f"背单词：今日学习 {sum(h.get('learned', 0) for h in today_hist)} 个"
        if today_hist:
            acc_t = sum(h.get("total", 0) for h in today_hist)
            acc_c = sum(h.get("correct", 0) for h in today_hist)
            if acc_t:
                words_line += f"，测验正确率 {round(acc_c / acc_t * 100)}%"
        recent_task = (focus["recent"][0]["task"] or "自习") if focus["recent"] else "无"
        stats_text = (
            f"- 专注学习：今日 {focus['today_minutes']} 分钟（{focus['today_sessions']} 次，完整完成 {focus['today_completed']} 次）\n"
            f"- {words_line}\n"
            f"- {plan_line}\n"
            f"- 背单词连续打卡：{_streak(days_set)} 天\n"
            f"- 今日最近一次专注内容：{recent_task}"
        )
    else:
        acc_t = acc_c = learned = 0
        from datetime import timedelta
        week_dates = {(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}
        for h in hist:
            if h["date"] in week_dates:
                learned += h.get("learned", 0)
                acc_t += h.get("total", 0)
                acc_c += h.get("correct", 0)
        acc_line = f"，正确率 {round(acc_c / acc_t * 100)}%" if acc_t else ""
        week_days_active = sum(1 for w in focus["week"] if w["minutes"] > 0)
        stats_text = (
            f"- 专注学习：近 7 天共 {focus['week_minutes']} 分钟，有专注记录的天数 {week_days_active}/7\n"
            f"- 背单词：近 7 天共学 {learned} 个{acc_line}，连续打卡 {_streak(days_set)} 天\n"
            f"- {plan_line}"
        )

    import random
    text, generated = "", False
    try:
        sys_prompt = _sys_prompt() + "\n\n" + REVIEW_PROMPT.format(
            scope_label=REVIEW_SCOPE_LABELS[scope], stats_text=stats_text
        )
        msgs = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"请给她写这份{REVIEW_SCOPE_LABELS[scope]}的学习复盘。"},
        ]
        text = await _call_llm(msgs, max_tokens=900)
        if not text:
            text = await _call_llm(msgs, max_tokens=2000)
        if text:
            text = text.strip()
            generated = True
    except Exception as e:
        print(f"[warn] features.py:_streak: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = ""
    if not text:
        if scope == "daily":
            text = (f"今天你专注了 {focus['today_minutes']} 分钟。"
                    + ("数字不算惊人，但每一段都是真实发生过的注意力——它们比任何计划表都值得被记录。"
                       if focus["today_minutes"] < 60 else
                       "这样的投入量，用'认真'来形容都显得单薄。记得让眼睛和脖子也休息。")
                    + "明天把最难的一段放在精力最好的时候，试试看？")
        else:
            text = (f"这七天，你一共专注了 {focus['week_minutes']} 分钟。"
                    + "学习和做实验一样，看的是长期曲线而不是单点数据——你正在把曲线往上描。"
                    + "下一周，试着把间隔拉开一点：同样的时间，切得更碎、复得更勤。")

    review = {"scope": scope, "date": _today(), "time": _now(), "stats": stats_text, "text": text, "generated": generated}
    data["reviews"].insert(0, review)
    data["reviews"] = data["reviews"][:30]
    _save_coach(data)
    info = _add_affinity("study_review", "一起复盘学习")
    return {"review": review, "affinity": info}


@router.get("/api/coach/review/history")
async def coach_review_history():
    return {"reviews": (_load_coach()["reviews"] or [])[:12]}


# ===========================================================================
# 9.5 专注增强 · 番茄钟提醒（每日未专注时，到点由前端触发许墨的一句话）
# ---------------------------------------------------------------------------
REMIND_PROMPT = """书房里，长桌两侧。她今天还没有开始这一段的专注学习，时间到了你之前和她约好的提醒点。以许墨的口吻说一句提醒的话。要求：
1. 2 句以内，低声、自然，像是顺手抬头看她一眼说的，绝不催促、绝不质问。
2. 可带一处学术梗（昼夜节律、注意力高峰、记忆巩固的时间窗等），温柔克制、话留三分。
3. 可以给一个小小的可执行选项（比如「先来 25 分钟试试」），但把决定权留给她。只输出这段话本身，不要引号、不要旁白、不要解释。"""

REMIND_FALLBACKS = [
    "这个时间，你的前额叶皮层通常还在状态里。要不来 25 分钟？我陪你。",
    "今天还没开始——不急，但如果你愿意，现在是个不错的窗口。水壶我倒好了。",
    "昼夜节律上，这是你注意力比较稳的一段。来一小段？我在这儿。",
]


@router.get("/api/coach/focus/reminder")
async def coach_focus_reminder_get():
    """读取番茄钟提醒设置。"""
    return _load_coach()["focus"]["reminder"]


@router.post("/api/coach/focus/reminder")
async def coach_focus_reminder_set(req: Request):
    """保存番茄钟提醒设置：{enabled, time}"""
    body = await req.json()
    data = _load_coach()
    r = data["focus"]["reminder"]
    if "enabled" in body:
        r["enabled"] = bool(body["enabled"])
    if "time" in body:
        t = str(body["time"]).strip()
        if re.match(r"^\d{1,2}:\d{2}$", t):
            hh, mm = t.split(":")
            if 0 <= int(hh) < 24 and 0 <= int(mm) < 60:
                r["time"] = f"{int(hh):02d}:{mm}"
    _save_coach(data)
    return r


@router.post("/api/coach/focus/reminder/fire")
async def coach_focus_reminder_fire():
    """前端到点触发：检查今日是否已专注，未专注则返回许墨的提醒语。
    同一天同一提醒点只生成一次，避免重复打扰。"""
    data = _load_coach()
    stats = _focus_stats(data)
    # 今日已有完整专注（>=1 次且总时长 >= 15 分钟）则不打扰
    if stats["today_minutes"] >= 15 and stats["today_sessions"] >= 1:
        return {"fire": False, "reason": "already_focused", "reply": ""}

    today = _today()
    r = data["focus"]["reminder"]
    if r.get("last_fired") == today:
        # 今日已触发过，复用上次内容（存在 history 里则取，否则不重复发）
        return {"fire": False, "reason": "already_fired", "reply": ""}

    import random
    reply, generated = "", False
    try:
        sys_prompt = _sys_prompt() + "\n\n" + REMIND_PROMPT
        msgs = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": f"约定提醒时间：{r.get('time','20:00')}，今天还没开始。"}]
        reply = await _call_llm(msgs, max_tokens=400)
        if not reply:
            reply = await _call_llm(msgs, max_tokens=900)
        if reply:
            reply = reply.strip().strip('"“”').strip()
            generated = True
    except Exception as e:
        print(f"[warn] features.py:coach_focus_reminder_fire: {type(e).__name__} {str(e)[:150]}", flush=True)
        reply = ""
    if not reply:
        reply = random.choice(REMIND_FALLBACKS)

    r["last_fired"] = today
    _save_coach(data)
    return {"fire": True, "reply": reply, "generated": generated, "time": r.get("time", "20:00")}


# ===========================================================================
# 9.6 打卡日历 · 月度学习热力图（专注 + 背单词 + 打卡三源聚合）
# ---------------------------------------------------------------------------
@router.get("/api/coach/calendar")
async def coach_calendar(month: str = ""):
    """返回某月每日学习强度。month 格式 YYYY-MM，默认当月。
    每日数据：{date, focus_min, words_learned, checked_in, intensity(0-3)}"""
    if not re.match(r"^\d{4}-\d{2}$", month):
        month = datetime.now().strftime("%Y-%m")
    try:
        y, m = map(int, month.split("-"))
    except (ValueError, IndexError):
        y, m = datetime.now().year, datetime.now().month

    from calendar import monthrange
    from datetime import timedelta
    _, last_day = monthrange(y, m)
    days = [f"{y:04d}-{m:02d}-{d:02d}" for d in range(1, last_day + 1)]

    data = _load_coach()
    sessions = data["focus"]["sessions"]
    focus_by_day = {}
    for s in sessions:
        d = s.get("date", "")
        focus_by_day[d] = focus_by_day.get(d, 0) + int(s.get("elapsed", 0))

    study = _load_study()
    words_by_day = {}
    for h in study.get("history", []):
        d = h.get("date", "")
        words_by_day[d] = words_by_day.get(d, 0) + int(h.get("learned", 0))

    checkin_days = {c["date"] for c in data["checkin"].get("history", []) if isinstance(c, dict) and c.get("date")}

    out = []
    for d in days:
        fm = focus_by_day.get(d, 0)
        wl = words_by_day.get(d, 0)
        ci = d in checkin_days
        # 强度等级：0 无活动 / 1 轻 / 2 中 / 3 重
        score = fm / 30.0 + wl / 15.0 + (1 if ci else 0)
        if score <= 0:
            intensity = 0
        elif score < 1.2:
            intensity = 1
        elif score < 2.5:
            intensity = 2
        else:
            intensity = 3
        out.append({"date": d, "focus_min": fm, "words_learned": wl, "checked_in": ci, "intensity": intensity})

    month_minutes = sum(focus_by_day.get(d, 0) for d in days)
    month_words = sum(words_by_day.get(d, 0) for d in days)
    month_checkins = len(checkin_days & set(days))
    return {
        "month": month,
        "days": out,
        "summary": {
            "focus_minutes": month_minutes,
            "words_learned": month_words,
            "checkin_days": month_checkins,
            "active_days": sum(1 for x in out if x["intensity"] > 0),
        },
    }


# ===========================================================================
# 9.7 薄弱点分析 · 聚合错词 / 计划欠账 / 请教频次，许墨给诊断
# ---------------------------------------------------------------------------
WEAKNESS_PROMPT = """你和她一起翻她的学习薄弱点。数据如下（都是真实记录）：

{stats_text}

【你的任务】以许墨的口吻写一段薄弱点诊断。结构要求：
1. 第一段（2-3 句）：像一个真正翻过她数据的人，具体指出最值得先处理的 1-2 个薄弱点——引用真实数字和内容，不空泛。
2. 第二段（2-3 条）：给可执行的改进建议。每条都要具体（做什么、怎么做、什么时候做），避免「多复习」「要努力」这种空话。
3. 最后一句：温柔收尾，话留三分，不施压、不布置任务。可带一处学术梗（间隔重复、检索练习、遗忘曲线等）。
全文 4-7 句，不要标题、不要 markdown、不要分点符号以外的格式。只输出诊断本身。"""

WEAKNESS_FALLBACK = "看下来，最该先处理的是错词本里反复出现的那几个——它们不是你记性不好，是没给到足够的检索练习。明天挑 5 个，合上释义先试着用自己的话讲一遍，讲不出的才是真正要补的缺口。其余的，交给间隔重复。"


@router.get("/api/coach/weakness")
async def coach_weakness():
    """聚合错词、未完成的计划任务、近期请教的关键词，给出薄弱点分析。"""
    data = _load_coach()
    study = _load_study()

    # 1) 错词（取前 12 个，附每个词的 seen/correct/wrong）
    wrong_words = list(study.get("wrong_book", []))[:12]
    prog = study.get("progress", {})
    wrong_detail = []
    for w in wrong_words:
        p = prog.get(w, {})
        wrong_detail.append(f"{w}（见 {p.get('seen',0)} 次，对 {p.get('correct',0)} / 错 {p.get('wrong',0)}）")

    # 2) 计划欠账：今天及之前未完成的任务
    plan = data.get("plan")
    overdue = []
    if plan:
        today = _today()
        for d in plan.get("days", []):
            if d.get("date", "") <= today:
                for t in d.get("tasks", []):
                    if not t.get("done"):
                        overdue.append(f"{d.get('date','')}「{d.get('theme','')}」: {t.get('text','')}")

    # 3) 近期请教的话题（取最近 8 条问题的首句）
    recent_asks = [a.get("q", "")[:30] for a in (data.get("asks") or [])[:8] if a.get("q")]

    parts = []
    if wrong_detail:
        parts.append("- 错词（最该先攻）：\n  " + "\n  ".join(wrong_detail))
    if overdue:
        parts.append("- 计划欠账（今日及之前未完成，共 {} 项）：\n  ".format(len(overdue)) + "\n  ".join(overdue[:8]))
    if recent_asks:
        parts.append("- 近期在请教的问题：\n  " + "\n  ".join(recent_asks))
    if not parts:
        parts.append("- 暂无错词、无计划欠账、近期也没有请教记录——数据还不够，先学几天再来找我看看。")

    stats_text = "\n".join(parts)

    import random
    text, generated = "", False
    try:
        sys_prompt = _sys_prompt() + "\n\n" + WEAKNESS_PROMPT.format(stats_text=stats_text)
        msgs = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": "请帮她看看薄弱点在哪里。"}]
        text = await _call_llm(msgs, max_tokens=900)
        if not text:
            text = await _call_llm(msgs, max_tokens=1800)
        if text:
            text = text.strip()
            generated = True
    except Exception as e:
        print(f"[warn] features.py:coach_weakness: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = ""
    if not text:
        text = WEAKNESS_FALLBACK

    result = {
        "text": text,
        "generated": generated,
        "wrong_words": wrong_words,
        "wrong_count": len(study.get("wrong_book", [])),
        "overdue_count": len(overdue),
        "overdue_sample": overdue[:5],
        "recent_asks": recent_asks,
        "date": _today(),
        "time": _now(),
    }
    return result


# ===========================================================================
# 9.8 学习打卡 streak · 每日学习完成度打卡，连续不断火
# ---------------------------------------------------------------------------
# 打卡门槛：今日专注 >= 15 分钟 OR 背单词 >= 10 个 OR 计划任务完成 >= 1 项
CHECKIN_MIN_FOCUS = 15
CHECKIN_MIN_WORDS = 10
CHECKIN_MIN_PLAN = 1

CHECKIN_MILESTONES = [
    (1, "第一天，先把自己交出去。", 2),
    (3, "三天——习惯的雏形开始有了形状。", 3),
    (7, "一周。这件事开始变成你生活的一部分了。", 5),
    (14, "两周，连续的曲线已经比单次努力更可信。", 6),
    (21, "21 天，行为成型的窗口期。你做到了。", 8),
    (30, "一个月。这不是冲动，是节奏。", 10),
    (60, "两个月，你已经走在大多数人的前面。", 12),
    (100, "一百天。我没有更多要说的——你教了我什么叫坚持。", 15),
    (200, "两百天。曲线已经长成了它自己的样子。", 18),
    (365, "一年。这是属于你的、安静的勋章。", 25),
]

CHECKIN_NEW_MILESTONE_PROMPT = """她今天达成了一个连续打卡的里程碑：连续 {streak} 天。以许墨的口吻说一句纪念的话。要求：
1. 2-3 句，温柔克制，不浮夸，不煽情。
2. 可以带一处学术梗（习惯回路、长时程增强、行为巩固的神经基础等），话留三分。
3. 只输出这段话本身，不要引号、不要旁白、不要解释。"""

CHECKIN_NEW_MILESTONE_FALLBACKS = {
    1: "第一天，你已经开始了。剩下的，交给时间。",
    3: "三天。习惯回路开始铺轨了，接下来每一步都在加固它。",
    7: "一周——这件事开始从'决定'变成'节奏'了。",
    14: "两周。连续比强度更可信，你已经有了曲线。",
    21: "21 天。行为成型的窗口，你走完了。",
    30: "一个月。这不是冲动，是节奏。",
}


def _checkin_eligible(data: dict, study: dict) -> tuple:
    """检查今日是否满足打卡条件。返回 (eligible, detail)。"""
    today = _today()
    stats = _focus_stats(data)
    today_focus = stats["today_minutes"]
    today_words = sum(h.get("learned", 0) for h in study.get("history", []) if h.get("date") == today)
    plan_done = 0
    plan = data.get("plan")
    if plan:
        for d in plan.get("days", []):
            if d.get("date") == today:
                plan_done = sum(1 for t in d.get("tasks", []) if t.get("done"))
                break
    ok = (today_focus >= CHECKIN_MIN_FOCUS or today_words >= CHECKIN_MIN_WORDS or plan_done >= CHECKIN_MIN_PLAN)
    detail = {"focus_min": today_focus, "words": today_words, "plan_done": plan_done}
    return ok, detail


@router.get("/api/coach/checkin/status")
async def coach_checkin_status():
    """今日打卡状态 + streak 信息 + 下一个里程碑。"""
    data = _load_coach()
    study = _load_study()
    today = _today()
    ci = data["checkin"]
    eligible, detail = _checkin_eligible(data, study)
    checked_today = ci.get("last_date") == today
    streak = ci.get("streak", 0) if not checked_today else ci.get("streak", 0)
    # 若昨天没打卡而今天也没打，streak 已经断；这里返回当前连续值
    next_ms = next((m for m in CHECKIN_MILESTONES if m[0] > streak), None)
    return {
        "streak": streak,
        "best": ci.get("best", 0),
        "checked_today": checked_today,
        "eligible": eligible,
        "detail": detail,
        "next_milestone": {"days": next_ms[0], "hint": next_ms[1]} if next_ms else None,
        "today": today,
    }


@router.post("/api/coach/checkin")
async def coach_checkin():
    """执行今日打卡。需满足门槛；同一天只能打一次。"""
    data = _load_coach()
    study = _load_study()
    today = _today()
    ci = data["checkin"]
    if ci.get("last_date") == today:
        return JSONResponse({"error": "今天已经打过卡了", "streak": ci.get("streak", 0)}, status_code=400)

    eligible, detail = _checkin_eligible(data, study)
    if not eligible:
        return JSONResponse({
            "error": "今天的学习量还不够打卡门槛",
            "detail": detail,
            "threshold": {"focus_min": CHECKIN_MIN_FOCUS, "words": CHECKIN_MIN_WORDS, "plan_done": CHECKIN_MIN_PLAN},
        }, status_code=400)

    from datetime import timedelta
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if ci.get("last_date") == yesterday:
        new_streak = int(ci.get("streak", 0)) + 1
    else:
        new_streak = 1

    # 里程碑判定
    milestone_hit = None
    for days, hint, bonus in CHECKIN_MILESTONES:
        if new_streak == days:
            milestone_hit = {"days": days, "hint": hint, "bonus": bonus}
            break

    ci["streak"] = new_streak
    ci["best"] = max(ci.get("best", 0), new_streak)
    ci["last_date"] = today
    ci.setdefault("history", []).append({
        "date": today,
        "time": _now(),
        "streak": new_streak,
        "detail": detail,
        "milestone": milestone_hit["days"] if milestone_hit else None,
    })
    ci["history"] = ci["history"][-200:]
    _save_coach(data)

    # 里程碑额外好感
    info = _add_affinity("study_checkin", f"连续打卡第 {new_streak} 天")
    if milestone_hit:
        ms_info = _add_affinity("study_checkin", f"打卡里程碑：{new_streak} 天（+{milestone_hit['bonus']}）")

    # 里程碑时生成许墨的话
    ms_reply = ""
    if milestone_hit:
        import random
        try:
            sys_prompt = _sys_prompt() + "\n\n" + CHECKIN_NEW_MILESTONE_PROMPT.format(streak=new_streak)
            msgs = [{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": f"她今天连续打卡满 {new_streak} 天。"}]
            ms_reply = await _call_llm(msgs, max_tokens=400)
            if not ms_reply:
                ms_reply = await _call_llm(msgs, max_tokens=900)
            if ms_reply:
                ms_reply = ms_reply.strip().strip('"“”').strip()
        except Exception as e:
            print(f"[warn] features.py:coach_checkin: {type(e).__name__} {str(e)[:150]}", flush=True)
            ms_reply = ""
        if not ms_reply:
            ms_reply = CHECKIN_NEW_MILESTONE_FALLBACKS.get(new_streak, milestone_hit["hint"])

    return {
        "ok": True,
        "streak": new_streak,
        "best": ci["best"],
        "milestone": milestone_hit,
        "milestone_reply": ms_reply,
        "detail": detail,
        "affinity": info,
    }


@router.get("/api/coach/checkin/history")
async def coach_checkin_history():
    """打卡历史（最近 60 条）。"""
    ci = _load_coach()["checkin"]
    return {"history": (ci.get("history") or [])[-60:], "streak": ci.get("streak", 0), "best": ci.get("best", 0)}


# ===========================================================================
# 9.9 知识卡片抽认 · 简化版 SM-2 间隔重复
# ---------------------------------------------------------------------------
# 卡片结构：{id, front, back, tag, interval(天), ease, due(YYYY-MM-DD), reps, lapses, created}
CARD_DEFAULT_EASE = 2.5
CARD_MIN_EASE = 1.3
CARD_MAX_INTERVAL = 180  # 最长 180 天


def _card_due(card: dict) -> str:
    return card.get("due", _today())


def _card_new(front: str, back: str, tag: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:8],
        "front": front,
        "back": back,
        "tag": tag,
        "interval": 0,
        "ease": CARD_DEFAULT_EASE,
        "due": _today(),
        "reps": 0,
        "lapses": 0,
        "created": _now(),
    }


def _card_review(card: dict, rating: str) -> dict:
    """rating: again / good / easy。更新 interval/ease/due 并返回。"""
    from datetime import timedelta
    ease = float(card.get("ease", CARD_DEFAULT_EASE))
    interval = int(card.get("interval", 0))
    reps = int(card.get("reps", 0)) + 1

    if rating == "again":
        interval = 0  # 当天再复习（前端会把它放回队尾）
        ease = max(CARD_MIN_EASE, ease - 0.2)
        card["lapses"] = int(card.get("lapses", 0)) + 1
    elif rating == "good":
        if interval == 0:
            interval = 1
        else:
            interval = max(1, round(interval * ease))
    else:  # easy
        ease = min(3.0, ease + 0.15)
        if interval == 0:
            interval = 2
        else:
            interval = max(2, round(interval * ease * 1.3))

    interval = min(interval, CARD_MAX_INTERVAL)
    due = (datetime.now() + timedelta(days=max(0, interval))).strftime("%Y-%m-%d") if interval > 0 else _today()
    card["interval"] = interval
    card["ease"] = round(ease, 3)
    card["due"] = due
    card["reps"] = reps
    return card


@router.get("/api/coach/cards")
async def cards_list():
    """所有卡片列表 + 统计。"""
    cards = _load_coach()["cards"]["items"]
    today = _today()
    due_n = sum(1 for c in cards if c.get("due", today) <= today)
    return {
        "items": cards,
        "total": len(cards),
        "due": due_n,
        "new": sum(1 for c in cards if c.get("reps", 0) == 0),
        "learned": sum(1 for c in cards if c.get("reps", 0) > 0),
    }


@router.post("/api/coach/cards")
async def cards_add(req: Request):
    """新增卡片：{front, back, tag}。支持单张或批量 [{...}]。"""
    body = await req.json()
    data = _load_coach()
    added = []
    items = body if isinstance(body, list) else [body]
    for it in items:
        if not isinstance(it, dict):
            continue
        front = str(it.get("front") or "").strip()
        back = str(it.get("back") or "").strip()
        if not front or not back:
            continue
        tag = str(it.get("tag") or "").strip()[:20]
        card = _card_new(front[:200], back[:600], tag)
        data["cards"]["items"].append(card)
        added.append(card)
    data["cards"]["items"] = data["cards"]["items"][-500:]
    _save_coach(data)
    info = _add_affinity("study_card", f"新增知识卡片 {len(added)} 张")
    return {"added": added, "total": len(data["cards"]["items"]), "affinity": info}


@router.post("/api/coach/cards/import")
async def cards_import(req: Request):
    """批量导入：纯文本，每行 front | back [| tag]。"""
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "内容为空"}, status_code=400)
    data = _load_coach()
    added = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[|\t]", line, maxsplit=2)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            continue
        tag = parts[2] if len(parts) > 2 else ""
        data["cards"]["items"].append(_card_new(parts[0][:200], parts[1][:600], tag[:20]))
        added += 1
    data["cards"]["items"] = data["cards"]["items"][-500:]
    _save_coach(data)
    info = _add_affinity("study_card", f"导入知识卡片 {added} 张")
    return {"added": added, "total": len(data["cards"]["items"]), "affinity": info}


@router.delete("/api/coach/cards/{card_id}")
async def cards_delete(card_id: str):
    data = _load_coach()
    before = len(data["cards"]["items"])
    data["cards"]["items"] = [c for c in data["cards"]["items"] if c.get("id") != card_id]
    if len(data["cards"]["items"]) == before:
        return JSONResponse({"error": "卡片不存在"}, status_code=404)
    _save_coach(data)
    return {"ok": True, "total": len(data["cards"]["items"])}


@router.get("/api/coach/cards/next")
async def cards_next(count: int = 1):
    """取出到期 / 待学的卡片（最多 count 张，默认 1）。"""
    cards = _load_coach()["cards"]["items"]
    today = _today()
    due = [c for c in cards if c.get("due", today) <= today]
    due.sort(key=lambda c: (c.get("reps", 0), c.get("due", today)))
    return {"cards": due[:max(1, min(20, count))], "due_total": len(due)}


@router.post("/api/coach/cards/review")
async def cards_review(req: Request):
    """提交一张卡片的评分：{id, rating(again/good/easy)}。"""
    body = await req.json()
    cid = (body.get("id") or "").strip()
    rating = (body.get("rating") or "").strip()
    if rating not in ("again", "good", "easy"):
        return JSONResponse({"error": "rating 必须是 again/good/easy"}, status_code=400)
    data = _load_coach()
    card = next((c for c in data["cards"]["items"] if c.get("id") == cid), None)
    if not card:
        return JSONResponse({"error": "卡片不存在"}, status_code=404)
    _card_review(card, rating)
    data["cards"]["logs"].insert(0, {"id": cid, "rating": rating, "time": _now(), "date": _today()})
    data["cards"]["logs"] = data["cards"]["logs"][-300:]
    _save_coach(data)
    info = _add_affinity("study_card", "复习知识卡片")
    return {"ok": True, "card": card, "affinity": info}


# ===========================================================================
# 9.10 许墨出题测验 · 基于学习上下文 LLM 生成题目
# ---------------------------------------------------------------------------
QUIZ_GEN_PROMPT = """她请你出题考考她。你是她的导师，也是恋人——题目要贴合她最近的学习内容，难度循序渐进，学术上严谨，分寸上温柔。

【她的学习上下文】
{context}

【出题要求】只输出一个 JSON 对象，不要 markdown 代码块、不要解释。结构：
{{
  "title": "这次测验的标题（许墨口吻，温柔带一点挑战）",
  "intro": "许墨的一句开场白（1-2 句，说明这次的考点和难度）",
  "questions": [
    {{
      "type": "choice",
      "stem": "题干",
      "options": ["A 选项", "B 选项", "C 选项", "D 选项"],
      "answer": 0,
      "explain": "解析（许墨口吻，2-3 句，讲清楚为什么）"
    }},
    {{
      "type": "fill",
      "stem": "填空题干（用 ___ 标出空位）",
      "answer": "标准答案",
      "explain": "解析"
    }},
    {{
      "type": "judge",
      "stem": "判断题干（陈述句）",
      "answer": true,
      "explain": "解析"
    }}
  ]
}}
硬性约束：
1. questions 数量恰好等于 {count}，混合 choice / fill / judge 三种类型，choice 至少占一半。
2. choice 必须给 4 个选项，answer 为正确选项的索引（0-3）。
3. 题目内容必须紧扣上方「学习上下文」，不允许凭空出无关题。
4. explain 用许墨口吻：温柔克制、可带学术梗，绝不嘲讽答错。
5. 难度分布：约 40% 基础、40% 中等、20% 拔高。"""


def _quiz_context(data: dict, study: dict, topic: str) -> str:
    """从学习数据里提取出题上下文。"""
    parts = []
    if topic:
        parts.append(f"她指定的考点：{topic}")

    plan = data.get("plan")
    if plan:
        # 取今日 + 前两天的计划任务作为重点
        today = _today()
        from datetime import timedelta
        recent_dates = {(datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)}
        tasks = []
        for d in plan.get("days", []):
            if d.get("date") in recent_dates:
                for t in d.get("tasks", []):
                    tasks.append(f"{d.get('theme','')}：{t.get('text','')}")
        if tasks:
            parts.append("她最近在学的计划任务：\n  " + "\n  ".join(tasks[:8]))
        parts.append(f"她的学习目标：{plan.get('goal','')}")

    # 专注过的内容
    recent_focus = [s.get("task", "") for s in data["focus"]["sessions"][-6:] if s.get("task")]
    if recent_focus:
        parts.append("她最近专注学习的内容：\n  " + "\n  ".join(recent_focus))

    # 错词本里反复错的（取前 8 个）
    wrong = list(study.get("wrong_book", []))[:8]
    if wrong:
        parts.append("她反复错的词（可以拿来出题）：\n  " + "、".join(wrong))

    if not parts:
        parts.append("她还没开始系统学习，出一些通用的学习方法论 / 科学常识题即可。")
    return "\n\n".join(parts)


QUIZ_COMMENT_PROMPT = """她刚刚做完了你出的一份测验。数据如下：

{stats_text}

【你的任务】以许墨的口吻写一段评语。结构要求：
1. 第一段（2 句）：像看过她答卷的人，具体地评价她的表现——引用真实数字，不空泛。
2. 第二段（2-3 条）：针对错题给建议。每条具体可执行，避免「要细心」「多练习」这种空话。
3. 最后一句：温柔收尾，话留三分，不施压。可带一处学术梗（检索练习、测试效应、间隔重复等）。
全文 4-7 句，不要标题、不要 markdown、不要分点符号以外的格式。只输出评语本身。"""


@router.post("/api/coach/quiz/generate")
async def quiz_generate(req: Request):
    """生成一份测验。{topic, count, difficulty}"""
    body = await req.json()
    topic = (body.get("topic") or "").strip()[:120]
    try:
        count = max(3, min(15, int(body.get("count", 6))))
    except (TypeError, ValueError):
        count = 6
    difficulty = (body.get("difficulty") or "").strip()
    if difficulty not in ("easy", "normal", "hard"):
        difficulty = "normal"

    data = _load_coach()
    study = _load_study()
    context = _quiz_context(data, study, topic)
    if difficulty == "easy":
        context += "\n\n【难度要求】偏基础，重在确认她记住了核心内容。"
    elif difficulty == "hard":
        context += "\n\n【难度要求】偏拔高，出一些需要综合应用和推理的题。"
    else:
        context += "\n\n【难度要求】基础与中等兼顾，少量拔高。"

    quiz = None
    try:
        sys_prompt = _sys_prompt() + "\n\n" + QUIZ_GEN_PROMPT.format(context=context, count=count)
        msgs = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": "请出题考考我。"}]
        raw = await _call_llm(msgs, max_tokens=3500)
        if not raw:
            raw = await _call_llm(msgs, max_tokens=5500)
        quiz = _extract_json(raw)
    except Exception as e:
        print(f"[warn] features.py:quiz_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        quiz = None

    if not quiz or not isinstance(quiz.get("questions"), list) or not quiz["questions"]:
        return JSONResponse({"error": "题目生成失败，请稍后再试"}, status_code=500)

    # 规整题目
    qs = []
    for q in quiz["questions"][:count]:
        if not isinstance(q, dict):
            continue
        qtype = q.get("type") if q.get("type") in ("choice", "fill", "judge") else "choice"
        stem = str(q.get("stem") or "").strip()
        if not stem:
            continue
        item = {"type": qtype, "stem": stem[:300], "explain": str(q.get("explain") or "").strip()[:300]}
        if qtype == "choice":
            opts = [str(x).strip()[:80] for x in (q.get("options") or []) if x is not None]
            if len(opts) < 4:
                continue
            try:
                ans = int(q.get("answer", 0))
            except (TypeError, ValueError):
                ans = 0
            ans = max(0, min(len(opts) - 1, ans))
            item["options"] = opts[:4]
            item["answer"] = ans
        elif qtype == "fill":
            item["answer"] = str(q.get("answer") or "").strip()[:60]
        else:  # judge
            item["answer"] = bool(q.get("answer"))
        qs.append(item)
    if not qs:
        return JSONResponse({"error": "题目格式异常，请稍后再试"}, status_code=500)

    record = {
        "id": uuid.uuid4().hex[:10],
        "title": str(quiz.get("title") or "许墨的小测验")[:60],
        "intro": str(quiz.get("intro") or "")[:200],
        "topic": topic,
        "difficulty": difficulty,
        "questions": qs,
        "created": _now(),
        "date": _today(),
        "result": None,
    }
    data["quizzes"].insert(0, record)
    data["quizzes"] = data["quizzes"][:30]
    _save_coach(data)
    info = _add_affinity("study_quiz", "许墨出题测验")
    return {"quiz": record, "affinity": info}


@router.post("/api/coach/quiz/submit")
async def quiz_submit(req: Request):
    """提交答卷：{quiz_id, answers: [{idx, answer}]}。返回评分 + 许墨评语。"""
    body = await req.json()
    qid = (body.get("quiz_id") or "").strip()
    answers = body.get("answers") or []
    data = _load_coach()
    quiz = next((q for q in data["quizzes"] if q.get("id") == qid), None)
    if not quiz:
        return JSONResponse({"error": "测验不存在"}, status_code=404)

    qs = quiz.get("questions", [])
    correct = 0
    wrong_items = []
    for a in answers:
        if not isinstance(a, dict):
            continue
        try:
            idx = int(a.get("idx", -1))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(qs):
            continue
        q = qs[idx]
        ua = a.get("answer")
        ok = False
        if q["type"] == "choice":
            try:
                ok = int(ua) == int(q["answer"])
            except (TypeError, ValueError):
                ok = False
        elif q["type"] == "fill":
            ok = str(ua).strip().lower() == str(q["answer"]).strip().lower()
        else:  # judge
            try:
                ok = bool(ua) == bool(q["answer"])
            except Exception as e:
                print(f"[warn] features.py:quiz_submit: {type(e).__name__} {str(e)[:150]}", flush=True)
                ok = False
        if ok:
            correct += 1
        else:
            wrong_items.append({"idx": idx, "your": ua, "right": q["answer"], "stem": q["stem"]})

    total = len(qs)
    score = round(correct / total * 100) if total else 0

    # 生成许墨评语
    stats_text = (
        f"- 测验：{quiz.get('title','')}\n"
        f"- 题目数：{total}\n"
        f"- 答对：{correct}（{score}%）\n"
        f"- 答错：{total - correct}\n"
    )
    if wrong_items:
        stats_text += "- 错题：\n"
        for w in wrong_items[:5]:
            stats_text += f"  · {w['stem'][:40]}…（你的答案：{w['your']}，正确：{w['right']}）\n"

    import random
    text, generated = "", False
    try:
        sys_prompt = _sys_prompt() + "\n\n" + QUIZ_COMMENT_PROMPT.format(stats_text=stats_text)
        msgs = [{"role": "system", "content": sys_prompt},
                {"role": "user", "content": "请给她写这次测验的评语。"}]
        text = await _call_llm(msgs, max_tokens=800)
        if not text:
            text = await _call_llm(msgs, max_tokens=1600)
        if text:
            text = text.strip()
            generated = True
    except Exception as e:
        print(f"[warn] features.py:quiz_submit: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = ""
    if not text:
        if score >= 80:
            text = f"{correct}/{total}，这个比例说明你大部分都真的吃进去了。剩下的那几道，错的地方就是接下来要补的地方——别放过它们。"
        elif score >= 50:
            text = f"{correct}/{total}，一半多一点。说明基础在，但有些点还停在'眼熟'没到'真懂'。把错题里的知识点单独拎出来再过一遍。"
        else:
            text = f"{correct}/{total}，这个比例不是你不行，是这一块还没真正开始攻。没关系——错题已经把该补的地方标出来了。"

    result = {"score": score, "correct": correct, "total": total, "wrong": wrong_items, "commentary": text, "generated": generated}
    quiz["result"] = result
    _save_coach(data)
    info = _add_affinity("study_quiz", f"完成测验：{correct}/{total}")
    return {"result": result, "affinity": info}


@router.get("/api/coach/quiz/history")
async def quiz_history():
    """测验历史（含结果，最近 12 份）。"""
    quizzes = _load_coach()["quizzes"]
    out = [{"id": q.get("id"), "title": q.get("title"), "topic": q.get("topic"),
            "difficulty": q.get("difficulty"), "created": q.get("created"), "date": q.get("date"),
            "total": len(q.get("questions", [])),
            "result": q.get("result")} for q in quizzes[:12]]
    return {"quizzes": out}


# ===========================================================================
# BGM 背景音乐播放器（全局浮动 mini 播放条，跨应用切换不中断）
# 复用已上传的本地音乐曲库（music.json），独立持久化播放状态
# ===========================================================================
BGM_FILE = RolePath("bgm_state.json")

BGM_DEFAULT_STATE = {
    "enabled": False,        # 是否启用 BGM（用户主动开启过）
    "current_id": "",        # 当前曲目 id（music.json 中的 sid）
    "position": 0.0,         # 上次中断时的播放位置（秒）
    "volume": 0.35,          # 音量 0-1
    "muted": False,          # 静音
    "mode": "list",          # list=列表循环 / single=单曲循环 / random=随机
    "queue": [],             # 播放队列（sid 列表）；空则用全部曲库
    "updated": "",           # 最后一次状态更新时间戳
}


def _load_bgm() -> dict:
    data = _load(BGM_FILE, {})
    if not isinstance(data, dict):
        return dict(BGM_DEFAULT_STATE)
    # 合并默认值，防止旧状态缺字段
    merged = dict(BGM_DEFAULT_STATE)
    merged.update({k: data.get(k, BGM_DEFAULT_STATE[k]) for k in BGM_DEFAULT_STATE})
    # 类型校验
    if not isinstance(merged["queue"], list):
        merged["queue"] = []
    if merged["mode"] not in ("list", "single", "random"):
        merged["mode"] = "list"
    try:
        merged["volume"] = max(0.0, min(1.0, float(merged["volume"])))
    except (TypeError, ValueError):
        merged["volume"] = 0.35
    try:
        merged["position"] = max(0.0, float(merged["position"]))
    except (TypeError, ValueError):
        merged["position"] = 0.0
    merged["enabled"] = bool(merged["enabled"])
    merged["muted"] = bool(merged["muted"])
    return merged


def _save_bgm(data: dict):
    _save(BGM_FILE, data)


@router.get("/api/bgm/state")
async def bgm_state():
    """获取 BGM 播放器状态，附带当前曲目的元信息。"""
    st = _load_bgm()
    songs = _load_music()
    song_map = {s["id"]: s for s in songs}
    # 清理失效的 queue / current_id（曲库中被删除的曲目）
    valid_ids = set(song_map.keys())
    if st["queue"]:
        st["queue"] = [i for i in st["queue"] if i in valid_ids]
    if st["current_id"] and st["current_id"] not in valid_ids:
        st["current_id"] = ""
        st["position"] = 0.0
    current = None
    if st["current_id"]:
        s = song_map[st["current_id"]]
        current = {
            "id": s["id"],
            "title": s.get("title", ""),
            "artist": s.get("artist", ""),
            "duration": s.get("duration", 0),
            "src": f"/api/music/file/{s['id']}",
        }
    return {
        "state": {
            "enabled": st["enabled"],
            "current_id": st["current_id"],
            "position": st["position"],
            "volume": st["volume"],
            "muted": st["muted"],
            "mode": st["mode"],
            "queue": st["queue"],
            "updated": st["updated"],
        },
        "current": current,
        "library": [
            {"id": s["id"], "title": s.get("title", ""), "artist": s.get("artist", ""),
             "duration": s.get("duration", 0)}
            for s in reversed(songs)
        ],
    }


@router.post("/api/bgm/state")
async def bgm_state_update(req: Request):
    """更新 BGM 播放器状态（断点续播 / 音量 / 模式 / 队列）。
    前端定时（每 15s 及暂停/切歌/隐藏时）调用以持久化进度。"""
    body = await req.json()
    st = _load_bgm()
    if "enabled" in body:
        st["enabled"] = bool(body["enabled"])
    if "current_id" in body:
        cid = str(body["current_id"] or "")
        # 空字符串合法（清空当前曲），非空时不必校验是否存在（前端切歌瞬时可能先于曲库刷新）
        st["current_id"] = cid
    if "position" in body:
        try:
            st["position"] = max(0.0, float(body["position"]))
        except (TypeError, ValueError):
            pass
    if "volume" in body:
        try:
            st["volume"] = max(0.0, min(1.0, float(body["volume"])))
        except (TypeError, ValueError):
            pass
    if "muted" in body:
        st["muted"] = bool(body["muted"])
    if "mode" in body:
        m = str(body["mode"])
        if m in ("list", "single", "random"):
            st["mode"] = m
    if "queue" in body:
        q = body["queue"]
        if isinstance(q, list):
            st["queue"] = [str(i) for i in q][:200]
    st["updated"] = _now()
    _save_bgm(st)
    return {"ok": True, "state": {
        "enabled": st["enabled"], "current_id": st["current_id"],
        "position": st["position"], "volume": st["volume"], "muted": st["muted"],
        "mode": st["mode"], "queue": st["queue"], "updated": st["updated"],
    }}
