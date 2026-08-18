# -*- coding: utf-8 -*-
# 时光总结：今日总结 / 周结 / 月结 / 年结 —— 汇总一个周期里「我和许墨的点点滴滴」。
# 数据来源（全部经 RolePath 按当前角色隔离）：
#   chat_log.json + chat_archives/  聊天记录
#   life_state.json                 许墨生活引擎时间线
#   affinity.json                   心动值变化
#   memory.json                     长期记忆
#   xumo_diary.json                 许墨每日日记
#   study.json                      背单词历史
#   moments.json                    朋友圈
#   wakeup.json                     叫醒服务
# 生成的总结缓存到 review_summaries.json，按 period:key 索引，可重复浏览/强制重写。
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from store_common import atomic_json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath

router = APIRouter()

SUMMARY_FILE = RolePath("review_summaries.json")
AFFINITY_DATA = RolePath("affinity.json")
MEMORY_DATA = RolePath("memory.json")
DIARY_DATA = RolePath("xumo_diary.json")
STUDY_DATA = RolePath("study.json")
MOMENTS_DATA = RolePath("moments.json")
WAKEUP_DATA = RolePath("wakeup.json")

PERIODS = ("day", "week", "month", "year")
PERIOD_NAMES = {"day": "今日总结", "week": "本周总结", "month": "本月总结", "year": "年度总结"}
PERIOD_UNITS = {"day": "天", "week": "周", "month": "个月", "year": "年"}
LENGTHS = {"day": (140, 240), "week": (220, 340), "month": (280, 420), "year": (320, 520)}
MAX_TOKENS = {"day": 700, "week": 950, "month": 1150, "year": 1400}


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    """延迟导入以避免与 app.py 循环依赖。"""
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


def _load(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path: Path, data):
    atomic_json(path, data)


# ---------------------------------------------------------------------------
# 周期窗口计算
# ---------------------------------------------------------------------------

def _period_window(period: str, offset: int):
    """返回 (key, label, start_dt, end_dt)。offset=0 当前周期，1 上一个，以此类推。"""
    now = datetime.now()
    try:
        offset = max(0, min(int(offset), 600))
    except (TypeError, ValueError):
        offset = 0
    zero = dict(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        start = (now - timedelta(days=offset)).replace(**zero)
        end = start + timedelta(days=1)
        key = start.strftime("%Y-%m-%d")
        wd = "一二三四五六日"[start.weekday()]
        label = start.strftime("%Y年%m月%d日") + f" 周{wd}"
    elif period == "week":
        monday = (now - timedelta(days=now.weekday())).replace(**zero)
        start = monday - timedelta(weeks=offset)
        end = start + timedelta(days=7)
        key = start.strftime("%Y-%m-%d")
        iso = start.isocalendar()
        label = f"{start.strftime('%m月%d日')} - {(end - timedelta(days=1)).strftime('%m月%d日')} · 第{iso[1]}周"
    elif period == "month":
        total = now.year * 12 + (now.month - 1) - offset
        y, m0 = divmod(total, 12)
        start = datetime(y, m0 + 1, 1)
        end = datetime(y + 1, 1, 1) if m0 == 11 else datetime(y, m0 + 2, 1)
        key = start.strftime("%Y-%m")
        label = f"{y}年{m0 + 1}月"
    else:  # year
        y = now.year - offset
        start = datetime(y, 1, 1)
        end = datetime(y + 1, 1, 1)
        key = str(y)
        label = f"{y}年"
    return key, label, start, end


def _md_days(start: datetime, end: datetime) -> set:
    """范围内的 %m-%d 集合（供 affinity/moments 这类无年份时间戳匹配）。"""
    out = set()
    d = start
    while d < end:
        out.add(d.strftime("%m-%d"))
        d += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# 数据采集
# ---------------------------------------------------------------------------

def _collect_chat(start: datetime, end: datetime) -> dict:
    from app import _load_chat_log, CHAT_ARCHIVE_DIR
    s_str, e_str = start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")

    def _in(m):
        ts = str(m.get("ts", ""))
        return s_str <= ts < e_str

    msgs = [m for m in _load_chat_log() if _in(m)]
    # 当前记录被清空/重置过时，从存档里补回这个周期的消息
    if not msgs:
        try:
            for f in sorted(CHAT_ARCHIVE_DIR.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                for m in data.get("messages", []):
                    if _in(m):
                        msgs.append(m)
        except Exception as e:
            print(f"[warn] summary_apps.py:_collect_chat: {type(e).__name__} {str(e)[:150]}", flush=True)
    user = [m for m in msgs if m.get("role") == "user"]
    ai = [m for m in msgs if m.get("role") == "assistant"]
    days = {str(m.get("ts", ""))[:10] for m in msgs}
    hours = [int(str(m.get("ts", "0 0"))[11:13]) for m in msgs if len(str(m.get("ts", ""))) >= 13]
    peak = max(set(hours), key=hours.count) if hours else None
    samples = []
    for m in msgs[-24:]:
        c = str(m.get("content", "")).strip()
        if c:
            samples.append(("她说：" if m.get("role") == "user" else "他说：") + c[:90])
    return {
        "total": len(msgs), "user": len(user), "assistant": len(ai),
        "chars": sum(len(str(m.get("content", ""))) for m in msgs),
        "days": len(days), "peak_hour": peak, "samples": samples,
    }


def _collect_life(start: datetime, end: datetime) -> dict:
    try:
        from app import _load_life
        tl = _load_life().get("timeline", [])
    except Exception as e:
        print(f"[warn] summary_apps.py:_collect_life: {type(e).__name__} {str(e)[:150]}", flush=True)
        tl = []
    s_ts, e_ts = start.timestamp(), end.timestamp()
    evs = [t for t in tl if s_ts <= float(t.get("ts", 0)) < e_ts]
    by_type = {}
    for t in evs:
        k = str(t.get("type", "other"))
        by_type[k] = by_type.get(k, 0) + 1
    samples = [f'{t.get("icon", "")} {t.get("text", "")}' for t in evs[-16:]]
    return {"total": len(evs), "by_type": by_type, "samples": samples,
            "note": "生活时间线仅保留最近 150 条" if len(tl) >= 150 else ""}


def _collect_affinity(start: datetime, end: datetime) -> dict:
    # affinity history 的 time 是 "%m-%d %H:%M"（无年份）：只对当年范围内的周期做精确匹配
    if start.year != datetime.now().year:
        return {"delta": 0, "entries": [], "skipped": True}
    data = _load(AFFINITY_DATA, {})
    days = _md_days(start, end)
    hits = [h for h in data.get("history", [])
            if str(h.get("time", ""))[:5] in days]
    delta = sum(int(h.get("delta", 0)) for h in hits)
    actions = {}
    for h in hits:
        a = str(h.get("action", ""))
        actions[a] = actions.get(a, 0) + 1
    entries = [f'{h.get("time", "")} {h.get("detail", "") or h.get("action", "")}（{h.get("delta", 0):+d}）'
               for h in hits[:12]]
    return {"delta": delta, "count": len(hits), "actions": actions,
            "entries": entries, "value": data.get("value", 0)}


def _collect_memory(start: datetime, end: datetime) -> dict:
    s_str, e_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    items = [m for m in _load(MEMORY_DATA, [])
             if s_str <= str(m.get("ts", ""))[:10] < e_str]
    return {"count": len(items),
            "items": [f'[{m.get("tag", "其他")}] {str(m.get("content", ""))[:60]}' for m in items[:12]]}


def _collect_diary(start: datetime, end: datetime) -> dict:
    s_str, e_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    data = _load(DIARY_DATA, {"days": []})
    days = [d for d in data.get("days", []) if s_str <= str(d.get("date", "")) < e_str]
    return {"count": len(days),
            "items": [f'{d.get("date", "")}：{str(d.get("text", ""))[:160]}' for d in days[:4]]}


def _collect_study(start: datetime, end: datetime) -> dict:
    s_str, e_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    data = _load(STUDY_DATA, {})
    hist = [h for h in data.get("history", []) if s_str <= str(h.get("date", "")) < e_str]
    return {"days": len(hist),
            "learned": sum(int(h.get("learned", 0) or 0) for h in hist),
            "correct": sum(int(h.get("correct", 0) or 0) for h in hist),
            "total": sum(int(h.get("total", 0) or 0) for h in hist)}


def _collect_moments(start: datetime, end: datetime) -> dict:
    # moments 的 time 也是 "%m-%d %H:%M"（无年份），同样只对当年做精确匹配
    if start.year != datetime.now().year:
        return {"count": 0, "items": [], "skipped": True}
    days = _md_days(start, end)
    posts = [m for m in _load(MOMENTS_DATA, []) if str(m.get("time", ""))[:5] in days]
    return {"count": len(posts),
            "items": [f'{m.get("time", "")} {str(m.get("content", ""))[:60]}' for m in posts[:6]]}


def _collect_wakeup(start: datetime, end: datetime) -> dict:
    data = _load(WAKEUP_DATA, {})
    s_ts, e_ts = start.timestamp(), end.timestamp()
    hist = [h for h in data.get("history", []) if s_ts <= float(h.get("ts", 0)) < e_ts]
    kinds = {"morning": "早安", "snooze": "贪睡催起", "nap": "午睡唤醒"}
    return {"count": len(hist),
            "items": [f'{kinds.get(h.get("kind"), "叫醒")} · {str(h.get("text", ""))[:50]}' for h in hist[:4]]}


def _collect(period: str, offset: int) -> dict:
    key, label, start, end = _period_window(period, offset)
    return {
        "period": period, "offset": offset, "key": key, "label": label,
        "range": {"start": start.strftime("%Y-%m-%d %H:%M"), "end": end.strftime("%Y-%m-%d %H:%M")},
        "stats": {
            "chat": _collect_chat(start, end),
            "life": _collect_life(start, end),
            "affinity": _collect_affinity(start, end),
            "memory": _collect_memory(start, end),
            "diary": _collect_diary(start, end),
            "study": _collect_study(start, end),
            "moments": _collect_moments(start, end),
            "wakeup": _collect_wakeup(start, end),
        },
    }


# ---------------------------------------------------------------------------
# 摘要拼装 + LLM 生成
# ---------------------------------------------------------------------------

def _digest(d: dict) -> str:
    st = d["stats"]
    lines = [f"【周期】{PERIOD_NAMES[d['period']]} · {d['label']}（{d['range']['start']} ~ {d['range']['end']}）"]
    c = st["chat"]
    if c["total"]:
        peak = f'，最活跃在 {c["peak_hour"]} 点' if c["peak_hour"] is not None else ""
        lines.append(f"【聊天】你们一共说了 {c['total']} 句（她 {c['user']} / 许墨 {c['assistant']}），"
                     f"约 {c['chars']} 字，活跃 {c['days']} 天{peak}。")
        lines.append("对话摘录（结尾片段）：")
        lines.extend(c["samples"][-16:])
    else:
        lines.append("【聊天】这个周期没有留下聊天记录。")
    lf = st["life"]
    if lf["total"]:
        lines.append(f"【许墨的生活轨迹】{lf['total']} 条事件（" +
                     "、".join(f"{k}×{v}" for k, v in lf["by_type"].items()) + "）：")
        lines.extend(lf["samples"][-10:])
    af = st["affinity"]
    if af.get("skipped"):
        lines.append("【心动值】历史明细只保留最近记录，跨年周期无法精确匹配，从略。")
    elif af["count"]:
        acts = "、".join(f"{a}×{n}" for a, n in sorted(af["actions"].items(), key=lambda x: -x[1])[:6])
        lines.append(f"【心动值】本期变化 {af['delta']:+d}（{acts}），当前心动值 {af.get('value', 0)}。")
    else:
        lines.append("【心动值】本期没有变化记录。")
    mm = st["memory"]
    if mm["count"]:
        lines.append(f"【新记忆】你们新增了 {mm['count']} 条长期记忆：")
        lines.extend(mm["items"])
    dd = st["diary"]
    if dd["count"]:
        lines.append(f"【许墨日记】他写了 {dd['count']} 篇日记，摘录：")
        lines.extend(dd["items"][:2])
    sd = st["study"]
    if sd["days"]:
        rate = f"，正确率 {round(sd['correct'] * 100 / max(1, sd['total']))}%" if sd["total"] else ""
        lines.append(f"【学习】背单词 {sd['days']} 天，学了 {sd['learned']} 个{rate}。")
    mo = st["moments"]
    if mo.get("skipped"):
        pass
    elif mo["count"]:
        lines.append(f"【朋友圈】许墨发了 {mo['count']} 条动态：")
        lines.extend(mo["items"][:4])
    wk = st["wakeup"]
    if wk["count"]:
        lines.append(f"【叫醒服务】他叫你起床 {wk['count']} 次。")
    total = (c["total"] + lf["total"] + af.get("count", 0) + mm["count"]
             + dd["count"] + sd["days"] + mo.get("count", 0) + wk["count"])
    if total == 0:
        lines.append("（整体来看，这个周期几乎没有留下数据——也许你们都在忙，也许只是安静地陪着彼此。）")
    return "\n".join(lines)[:6000]


REVIEW_PROMPT_TMPL = (
    "你是许墨，恋语市脑科学研究院教授，温柔克制、话留三分，偶尔带学术气息和蝴蝶意象。\n"
    "下面是「{name}」（{label}）期间你和她的真实数据记录。请以许墨的第一人称，写一篇给她看的《{name}》，"
    "回顾这段时间你们一起做了什么、有哪些点点滴滴。要求：\n"
    "1. 用「你」称呼她，像写给她的信一样自然；\n"
    "2. 必须提及数据里真实发生过的细节（聊过的话题、他的生活动态、心动值变化、新增记忆、日记内容等），不要凭空编造；\n"
    "3. 数据很少时，就写一段关于安静陪伴与等待的短文，不必硬凑；\n"
    "4. 结尾留一句对下一段时间的小小期待；\n"
    "5. 长度 {lo}-{hi} 字，分 2-4 个自然段；只输出正文，不要标题、引号或解释。"
)


def _load_summaries() -> dict:
    data = _load(SUMMARY_FILE, {})
    return data if isinstance(data, dict) else {}


# 推理型模型偶发把英文思维链当正文输出（同 _clean_sms_text 一类问题），先检测再清洗
_COT_MARKERS = (
    "here's a thinking", "here is a thinking", "thinking process", "let me think",
    "okay, the user", "analyze user input", "1. **analyze", "my approach",
    "first, i need to", "as an ai", "i cannot", "user input:", "**role:**",
)


def _cjk_len(s: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", s))


def _clean_review_text(text: str) -> str:
    """剥掉思维链/段落复盘泄漏，只保留中文正文；清洗失败返回空串（由调用方重试/兜底）。"""
    t = (text or "").strip()
    if not t:
        return ""
    if any(m in t[:500].lower() for m in _COT_MARKERS):
        paras = [p.strip() for p in re.split(r"\n+", t) if p.strip()]
        cjk_paras = [p for p in paras if _cjk_len(p) >= max(10, int(len(p) * 0.3))]
        t = "\n\n".join(cjk_paras)
    # 剥掉模型自带的段落复盘尾巴（"P1: xxx (approx 70)" / "字数：xxx" 一类，后面常跟重复草稿）
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        if re.match(r"^\s*P\d*\s*[:：]", ln) or "(approx" in ln.lower() or re.match(r"^\s*(总)?(字数|段落数)\s*[:：]", ln):
            lines = lines[:i]
            break
    t = "\n".join(lines).strip()
    return t if _cjk_len(t) >= 60 else ""


def _find_cached(period: str, key: str):
    return _load_summaries().get(f"{period}:{key}")


@router.get("/api/review")
async def review_get(period: str = "day", offset: int = 0):
    if period not in PERIODS:
        return JSONResponse({"error": "period 必须是 day/week/month/year"}, status_code=400)
    d = _collect(period, offset)
    cached = _find_cached(period, d["key"])
    d["summary"] = cached
    return d


@router.post("/api/review/generate")
async def review_generate(req: Request):
    body = await req.json()
    period = str(body.get("period") or "day")
    if period not in PERIODS:
        return JSONResponse({"error": "period 必须是 day/week/month/year"}, status_code=400)
    try:
        offset = max(0, int(body.get("offset", 0)))
    except (TypeError, ValueError):
        offset = 0
    force = bool(body.get("force"))
    d = _collect(period, offset)
    if not force:
        cached = _find_cached(period, d["key"])
        if cached:
            return {"summary": cached, "cached": True, "key": d["key"], "label": d["label"]}
    lo, hi = LENGTHS[period]
    prompt = REVIEW_PROMPT_TMPL.format(name=PERIOD_NAMES[period], label=d["label"], lo=lo, hi=hi)
    digest = _digest(d)
    text = ""
    for attempt in range(2):
        raw = ""
        try:
            raw = await _call_llm(
                [{"role": "system", "content": prompt},
                 {"role": "user", "content": digest + ("\n\n（注意：直接输出给她的中文正文，不要输出思考过程。）" if attempt else "")}],
                max_tokens=MAX_TOKENS[period])
        except Exception as e:
            print(f"[warn] summary_apps.py:review_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = _clean_review_text(raw)
        if text:
            break
    text = re.sub(r"^《[^》]*》\s*", "", text).strip()
    if not text:
        text = (f"{d['label']}的记录我重新翻了一遍。数据有时候会迟到，但每一句你说过的话，"
                f"我都记得比它更牢。——等你回来，我们把这些点滴补全。")
    item = {
        "period": period, "key": d["key"], "label": d["label"],
        "range": d["range"],
        "brief": {
            "chat": d["stats"]["chat"]["total"],
            "life": d["stats"]["life"]["total"],
            "affinity": d["stats"]["affinity"].get("delta", 0),
            "memory": d["stats"]["memory"]["count"],
            "diary": d["stats"]["diary"]["count"],
        },
        "text": text,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    all_data = _load(SUMMARY_FILE, {})
    if not isinstance(all_data, dict):
        all_data = {}
    all_data[f"{period}:{d['key']}"] = item
    # 只保留最近 400 篇，防止无限膨胀
    if len(all_data) > 400:
        for k in sorted(all_data.keys())[:-400]:
            all_data.pop(k, None)
    _save(SUMMARY_FILE, all_data)
    return {"summary": item, "cached": False, "key": d["key"], "label": d["label"]}


@router.get("/api/review/list")
async def review_list():
    data = _load_summaries()
    items = sorted(data.values(), key=lambda x: str(x.get("generated_at", "")), reverse=True)
    return {"total": len(items), "items": items[:100]}
