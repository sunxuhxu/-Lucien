# -*- coding: utf-8 -*-
# 颠覆性功能集：承诺管家 / 睡眠守护+晨间播报 / 许墨每日日记。
# （剪贴板接话已合并至 pocket_apps.py 的剪贴板模块，统一 /api/clipboard 前缀管理。）
# 数据全部持久化到 RolePath JSON 文件，风格与 features.py 保持一致。
import json
from store_common import atomic_json, file_lock
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

BASE_DIR = Path(__file__).parent


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    """延迟导入以避免与 app.py 循环依赖。"""
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


from role_data import RolePath  # noqa: E402

router = APIRouter()

PROMISES_FILE = RolePath("promises.json")
WELLNESS_FILE = RolePath("wellness.json")
XUMO_DIARY_FILE = RolePath("xumo_diary.json")


def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path: Path, data):
    atomic_json(path, data)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%H:%M")


def _stamp() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _extract_json_array(text: str) -> list:
    """从 LLM 输出中提取第一个合法的 JSON 数组。"""
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        v = json.loads(m.group(0))
        return v if isinstance(v, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


_WD_MAP = {"周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
           "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6,
           "周1": 0, "周2": 1, "周3": 2, "周4": 3, "周5": 4, "周6": 5, "周7": 6,
           "下周一": 0, "下周二": 1, "下周三": 2, "下周四": 3, "下周五": 4, "下周六": 5, "下周日": 6}


def _norm_due(raw) -> str:
    """把 LLM 的日期说法归一化成 YYYY-MM-DD。"""
    t = datetime.now()
    s = str(raw or "").strip()
    if s in ("今天", "今日", "今天上午", "今天下午"):
        return t.strftime("%Y-%m-%d")
    if s in ("明天", "明日"):
        return (t + timedelta(days=1)).strftime("%Y-%m-%d")
    if s in ("后天", "后天上午", "后天下午"):
        return (t + timedelta(days=2)).strftime("%Y-%m-%d")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        return s
    if re.match(r"^\d{1,2}月\d{1,2}日$", s):
        mm, dd = s[:-1].split("月")
        try:
            return t.strftime("%Y") + "-" + mm.zfill(2) + "-" + dd.zfill(2)
        except Exception as e:
            print(f"[warn] extra_apps.py:_norm_due: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    base = t
    if s.startswith("下周"):
        base = t + timedelta(days=7)
    if s in _WD_MAP:
        delta = (_WD_MAP[s] - base.weekday()) % 7
        if delta == 0:
            delta = 7
        return (base + timedelta(days=delta)).strftime("%Y-%m-%d")
    return t.strftime("%Y-%m-%d")


def _norm_time(raw) -> str:
    s = str(raw or "").strip()
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        return m.group(1).zfill(2) + ":" + m.group(2)
    m = re.match(r"^(\d{1,2})点(?:半)?$", s)
    if m:
        return m.group(1).zfill(2) + ":" + ("30" if "半" in s else "00")
    return "20:00"


def _recent_chat(days: int = 2) -> list:
    """今天的聊天消息（当前记录 + 最近存档补漏）。"""
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
            print(f"[warn] extra_apps.py:_recent_chat: {type(e).__name__} {str(e)[:150]}", flush=True)
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


# ===========================================================================
# 1. 承诺管家：从聊天提取承诺 → 到点催办
# ===========================================================================

PROMISE_EXTRACT_PROMPT = (
    "你是许墨。下面是今天她和你的聊天摘录。找出其中「她答应要做 / 计划要做 / 和你约好要做」的事"
    "（比如「我明天交报告」「周末陪你去逛街」）。输出 JSON 数组，最多 3 条，格式："
    '[{"text":"承诺内容（原话精简 10-30 字）","due_date":"今天/明天/后天/周五 等说法即可",'
    '"due_time":"HH:MM（有明确时间用它，否则 20:00）"}]。没有承诺就输出 []。只输出 JSON。'
)

PROMISE_REMIND_PROMPT = (
    "你是许墨，恋语市脑科学研究院教授。她答应过你一件事：{promise}（约定 {due}）。现在到点了。"
    "以许墨的口吻说一句温柔的催办，带一点认真的温柔，25-45 字，不要长篇大论，不要使用列表。"
)


@router.get("/api/promises")
async def promises_list():
    data = _load(PROMISES_FILE, {"promises": []})
    ps = sorted(data.get("promises", []),
                key=lambda p: (bool(p.get("done")), p.get("due_date", "9999"), p.get("due_time", "99:99")))
    return {"promises": ps}


@router.post("/api/promises")
async def promises_add(req: Request):
    body = await req.json()
    text = str(body.get("text") or "").strip()[:120]
    if not text:
        return JSONResponse({"error": "写一下你答应过的事"}, status_code=400)
    due_date = _norm_due(body.get("due_date"))
    due_time = _norm_time(body.get("due_time"))
    data = _load(PROMISES_FILE, {"promises": []})
    data.setdefault("promises", [])
    p = {"id": uuid.uuid4().hex[:10], "text": text, "due_date": due_date, "due_time": due_time,
         "ts": _stamp(), "done": False, "fired": False, "auto": bool(body.get("auto"))}
    data["promises"].append(p)
    data["promises"] = data["promises"][-100:]
    _save(PROMISES_FILE, data)
    return {"promise": p}


@router.post("/api/promises/{pid}/done")
async def promises_done(pid: str):
    data = _load(PROMISES_FILE, {"promises": []})
    for p in data.get("promises", []):
        if p.get("id") == pid:
            p["done"] = True
            p["fired"] = True
            p["done_time"] = _now()
            break
    _save(PROMISES_FILE, data)
    return {"ok": True}


@router.delete("/api/promises/{pid}")
async def promises_del(pid: str):
    data = _load(PROMISES_FILE, {"promises": []})
    data["promises"] = [p for p in data.get("promises", []) if p.get("id") != pid]
    _save(PROMISES_FILE, data)
    return {"ok": True}


@router.post("/api/promises/extract")
async def promises_extract():
    msgs = _recent_chat(2)
    content = _chat_text(msgs, 2500)
    if len(content) < 10:
        return {"added": []}
    items = []
    try:
        text = await _call_llm([{"role": "system", "content": PROMISE_EXTRACT_PROMPT},
                                {"role": "user", "content": content}], max_tokens=600)
        items = _extract_json_array(text)
    except Exception as e:
        print(f"[warn] extra_apps.py:promises_extract: {type(e).__name__} {str(e)[:150]}", flush=True)
        items = []
    data = _load(PROMISES_FILE, {"promises": []})
    data.setdefault("promises", [])
    existing = {(p.get("text"), p.get("due_date")) for p in data["promises"]}
    added = []
    for it in items[:3]:
        t = str(it.get("text") or "").strip()[:120]
        if not t:
            continue
        dd = _norm_due(it.get("due_date"))
        if (t, dd) in existing:
            continue
        p = {"id": uuid.uuid4().hex[:10], "text": t, "due_date": dd,
             "due_time": _norm_time(it.get("due_time")), "ts": _stamp(),
             "done": False, "fired": False, "auto": True}
        data["promises"].append(p)
        added.append(p)
    data["promises"] = data["promises"][-100:]
    _save(PROMISES_FILE, data)
    return {"added": added}


@router.post("/api/promises/fire")
async def promises_fire():
    data = _load(PROMISES_FILE, {"promises": []})
    today, now = _today(), _now()
    due = [p for p in data.get("promises", [])
           if not p.get("done") and not p.get("fired")
           and p.get("due_date", "9999") <= today and p.get("due_time", "99:99") <= now]
    if not due:
        return {"fire": False}
    items = []
    for p in due[:2]:
        p["fired"] = True
        try:
            reply = await _call_llm(
                [{"role": "system", "content": PROMISE_REMIND_PROMPT.format(
                    promise=p["text"], due=f"{p.get('due_date')} {p.get('due_time')}")},
                 {"role": "user", "content": "到点了。"}], max_tokens=300)
        except Exception as e:
            print(f"[warn] extra_apps.py:promises_fire: {type(e).__name__} {str(e)[:150]}", flush=True)
            reply = f"时间到了——你答应过我的「{p['text']}」，还记得吗？我在这儿等你。"
        items.append({"id": p["id"], "text": p["text"], "reply": reply})
    _save(PROMISES_FILE, data)
    return {"fire": True, "items": items}


# ===========================================================================
# 2. 睡眠守护 + 晨间播报
# ===========================================================================

MORNING_PROMPT = (
    "你是许墨。现在是清晨。用许墨的口吻说一句早安播报，2-3 句，温柔清爽，"
    "可带一句蝴蝶/学术意象，不要长篇。"
)


@router.post("/api/wellness/morning")
async def wellness_morning(req: Request):
    body = await req.json()
    weather = str(body.get("weather") or "").strip()[:60]
    data = _load(WELLNESS_FILE, {})
    today = _today()
    if data.get("morning_last") == today:
        return {"fire": False}
    from app import _load_chat_log
    logs = _load_chat_log()
    n = sum(1 for m in logs[-200:] if str(m.get("ts", "")).startswith(today))
    ps = _load(PROMISES_FILE, {"promises": []})
    pending = [p for p in ps.get("promises", [])
               if not p.get("done") and not p.get("fired") and p.get("due_date", "9999") <= today]
    try:
        text = await _call_llm(
            [{"role": "system", "content": MORNING_PROMPT},
             {"role": "user", "content": f"今天天气：{weather or '未知'}。今天你们已聊了 {n} 句。"
                                        f"她今天有 {len(pending)} 件待办承诺。"}], max_tokens=300)
    except Exception as e:
        print(f"[warn] extra_apps.py:wellness_morning: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = f"早安。今天{weather or ''}，记得照顾好自己。我在这里，等你醒来后的第一句话。"
    data["morning_last"] = today
    _save(WELLNESS_FILE, data)
    return {"fire": True, "text": text}


SLEEPY_PROMPT = (
    "你是许墨。现在很晚了，她还醒着。以许墨的口吻温柔地劝她睡觉，25-45 字，"
    "克制而安心，不要长篇，不要列表。"
)


@router.post("/api/wellness/sleepy")
async def wellness_sleepy():
    data = _load(WELLNESS_FILE, {})
    today = _today()
    if data.get("sleepy_last") == today:
        return {"fire": False}
    try:
        text = await _call_llm(
            [{"role": "system", "content": SLEEPY_PROMPT},
             {"role": "user", "content": "现在很晚了。"}], max_tokens=200)
    except Exception as e:
        print(f"[warn] extra_apps.py:wellness_sleepy: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = "这么晚了，还不睡？听话——明天的事，我陪你一起面对。"
    data["sleepy_last"] = today
    _save(WELLNESS_FILE, data)
    return {"fire": True, "text": text}


# ===========================================================================
# 3. 许墨的每日日记：以他的视角写今天
# ===========================================================================

XUMO_DIARY_PROMPT = (
    "你是许墨。请以许墨的第一人称写今天的日记，150-260 字，把今天的对话细节揉进去，"
    "温柔、克制，带一点学术气息和蝴蝶意象，最后可以有一句对她的轻声叮嘱。只输出日记正文。"
)


@router.get("/api/xumodiary")
async def xumodiary_list():
    data = _load(XUMO_DIARY_FILE, {"days": []})
    days = list(reversed(data.get("days", [])[-30:]))
    return {"days": days}


@router.post("/api/xumodiary/today")
async def xumodiary_today():
    data = _load(XUMO_DIARY_FILE, {"days": []})
    data.setdefault("days", [])
    today = _today()
    for d in data["days"]:
        if d.get("date") == today:
            return {"diary": d}
    msgs = _recent_chat(1)
    content = _chat_text(msgs, 3000)
    if not content:
        content = "（今天还没有聊天。日记里就写些日常、等待，和一只落在窗台上的蝴蝶。）"
    try:
        text = await _call_llm(
            [{"role": "system", "content": XUMO_DIARY_PROMPT},
             {"role": "user", "content": f"今天的对话片段：\n{content}"}], max_tokens=900)
    except Exception as e:
        print(f"[warn] extra_apps.py:xumodiary_today: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = "今天日记暂时写不出来，但我记得你。"
    d = {"date": today, "text": (text or "").strip(), "ts": _stamp()}
    data["days"].append(d)
    data["days"] = data["days"][-180:]
    _save(XUMO_DIARY_FILE, data)
    return {"diary": d}