"""许墨功能推荐引擎：上下文、偏好、时段、反馈、冷却与业务域多样性。"""
from __future__ import annotations

import math
from datetime import datetime


DOMAIN_GROUPS = {
    "关系": "affinity ourstory moments memory quotes promises xumodiary review dates chathist diary letter habits together achv pet wish phone sms timebox call mode_a".split(),
    "生活": "notes ledger together-shop clock weather listen photos codraw watch wardrobe radio planner work clip browser go lab mode_h".split(),
    "成长": "words coach video solve reading cowrite img2img spark".split(),
    "世界": "world dream pverse astro bsfile mode_g".split(),
    "心境": "mind bfly deep debate oracle sos lifeline div".split(),
    "实验": "timecall nradio pmail telepathy fate pulse subconscious capsule empath noracle whisper mixer rtm fusion theater fateecho vault pulselab rift wager relic symbiote dreamloom emoweather parallel puzzle dradio garden mirror weaver alchemy compass dreamlab".split(),
    "平台": ["extensions"],
}
APP_DOMAIN = {app: domain for domain, apps in DOMAIN_GROUPS.items() for app in apps}

TIME_BUCKETS = {
    "late_night": ["nradio", "dream", "listen", "diary", "letter", "sos"],
    "morning": ["clock", "weather", "planner", "words", "coach", "radio"],
    "workday": ["work", "planner", "notes", "coach", "words", "reading"],
    "afternoon": ["solve", "reading", "video", "cowrite", "world", "go"],
    "evening": ["listen", "watch", "dates", "moments", "diary", "world"],
}

CONTEXT_RULES = {
    "难过": (["难过", "伤心", "委屈", "崩溃", "想哭", "痛苦"], ["sos", "deep", "diary", "listen"]),
    "焦虑": (["焦虑", "紧张", "不安", "担心", "害怕", "压力"], ["sos", "planner", "notes", "deep"]),
    "疲惫": (["好累", "疲惫", "困了", "没精神", "乏力"], ["listen", "dream", "nradio", "clock"]),
    "开心": (["开心", "高兴", "太好了", "兴奋", "哈哈"], ["moments", "photos", "dates", "together"]),
    "工作": (["工作", "项目", "待办", "计划", "办公", "截止"], ["planner", "work", "notes", "coach"]),
    "学习": (["学习", "复习", "作业", "课程", "考试", "背单词"], ["coach", "words", "reading", "solve", "video"]),
    "创作": (["写作", "文章", "画画", "创作", "灵感", "润色"], ["cowrite", "img2img", "codraw", "spark"]),
    "放松": (["休息", "放松", "无聊", "陪我", "散步", "看电影"], ["listen", "world", "watch", "radio", "dream"]),
    "联系": (["想他", "想你", "打电话", "发消息", "写信", "约会"], ["call", "sms", "letter", "dates", "diary"]),
}

CORE_FALLBACK = ["affinity", "moments", "planner", "listen", "world", "diary", "coach", "deep", "dreamlab", "extensions"]


def _time_bucket(hour: int) -> str:
    if hour < 5:
        return "late_night"
    if hour < 9:
        return "morning"
    if hour < 14:
        return "workday"
    if hour < 18:
        return "afternoon"
    return "evening"


def _keyword_hits(text: str, keywords: list[str]) -> float:
    text = (text or "").lower()
    if not text:
        return 0.0
    hits = 0.0
    seen = set()
    for keyword in sorted(keywords, key=len, reverse=True):
        keyword = str(keyword).strip().lower()
        if keyword and keyword not in seen and keyword in text:
            seen.add(keyword)
            hits += 1.0 if len(keyword) >= 2 else 0.35
    return min(4.0, hits)


def _context(text: str) -> tuple[str, list[str]]:
    best_name, best_apps, best_hits = "", [], 0
    for name, (keywords, apps) in CONTEXT_RULES.items():
        hits = sum(1 for keyword in keywords if keyword in text)
        if hits > best_hits:
            best_name, best_apps, best_hits = name, apps, hits
    return best_name, best_apps


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _reason(details: dict, context_name: str, hour: int) -> str:
    if details.get("user_keyword", 0) > 0:
        return "回应你刚才提到的事"
    if details.get("context", 0) > 0 and context_name:
        return f"许墨注意到你现在有些{context_name}"
    if details.get("preference", 0) > 0.8:
        return "按你最近常用的功能推荐"
    if details.get("time", 0) > 0:
        return "适合现在这个时段"
    if details.get("explore", 0) > 0:
        return "换一个你较少体验的功能"
    return "结合你最近的使用情况"


def rank_recommendations(
    catalog: dict,
    behavior: dict | None = None,
    user_text: str = "",
    reply: str = "",
    limit: int = 3,
    now: datetime | None = None,
    surface: str = "chat",
) -> list[dict]:
    """返回经过多样性与冷却处理的推荐条目。"""
    behavior = behavior or {}
    now = now or datetime.now()
    combined = f"{user_text} {reply}".lower()
    context_name, context_apps = _context(combined)
    time_apps = TIME_BUCKETS[_time_bucket(now.hour)]
    usage = behavior.get("app_usage", {}) if isinstance(behavior.get("app_usage", {}), dict) else {}
    feedback = behavior.get("feedback", {}) if isinstance(behavior.get("feedback", {}), dict) else {}
    time_key = f"{now.hour // 3 * 3}-{(now.hour // 3 + 1) * 3 - 1}点"
    time_pattern = behavior.get("time_patterns", {}).get(time_key, {})
    recent_recs = behavior.get("recommendation_history", [])[-80:]

    domain_counts = {}
    for app, data in usage.items():
        domain = APP_DOMAIN.get(app, "其他")
        count = data.get("count", data.get("usage_count", 0)) if isinstance(data, dict) else int(data or 0)
        domain_counts[domain] = domain_counts.get(domain, 0) + count
    max_domain_count = max(domain_counts.values(), default=1)

    scored = []
    for key, info in catalog.items():
        if key == "settings":
            continue
        details = {}
        user_hits = _keyword_hits(user_text, info.get("kw", []))
        reply_hits = _keyword_hits(reply, info.get("kw", []))
        if user_hits:
            details["user_keyword"] = user_hits * 4.0
        if reply_hits:
            details["reply_keyword"] = reply_hits * 1.1
        if key in context_apps:
            details["context"] = 3.2 - context_apps.index(key) * 0.35
        if key in time_apps:
            details["time"] = 1.2 - time_apps.index(key) * 0.08

        usage_data = usage.get(key, {})
        count = usage_data.get("count", usage_data.get("usage_count", 0)) if isinstance(usage_data, dict) else int(usage_data or 0)
        if count:
            details["preference"] = min(2.0, math.log1p(count) * 0.45)
        domain = APP_DOMAIN.get(key, "其他")
        if domain_counts.get(domain):
            details["domain_affinity"] = 0.7 * domain_counts[domain] / max_domain_count
        if isinstance(time_pattern, dict) and time_pattern.get(key):
            details["time_preference"] = min(0.9, math.log1p(time_pattern[key]) * 0.3)

        app_feedback = feedback.get(key, {}) if isinstance(feedback.get(key, {}), dict) else {}
        positive = int(app_feedback.get("likes", 0) or 0)
        negative = int(app_feedback.get("dislikes", 0) or 0) + int(app_feedback.get("dismisses", 0) or 0)
        if positive:
            details["positive_feedback"] = min(1.8, positive * 0.6)
        if negative:
            explicitly_named = str(info.get("name", "")).lower() in (user_text or "").lower()
            penalty = 20.0 if negative >= 3 and not explicitly_named else min(8.0, negative * 2.5)
            details["negative_feedback"] = -penalty

        cooldown = 0.0
        for rec in recent_recs:
            if rec.get("app") != key:
                continue
            ts = _parse_time(rec.get("time", ""))
            if not ts:
                continue
            age_hours = max(0.0, (now - ts).total_seconds() / 3600)
            cooldown += 2.2 if age_hours < 6 else (0.8 if age_hours < 48 else 0.0)
        if cooldown:
            details["cooldown"] = -min(4.0, cooldown)
        if not count and not user_hits and key not in context_apps:
            details["explore"] = 0.25
        if surface == "recbar" and key in CORE_FALLBACK:
            details["core"] = 0.45

        score = sum(details.values())
        if user_hits or key in context_apps or surface == "recbar" or score >= 0.75:
            scored.append({
                "key": key,
                "score": score,
                "details": details,
                "domain": domain,
                "explicit": user_hits > 0,
                "reason": _reason(details, context_name, now.hour),
            })

    scored.sort(key=lambda item: (-item["score"], item["key"]))
    selected, domain_slots = [], {}
    for candidate in scored:
        domain = candidate["domain"]
        if domain_slots.get(domain, 0) >= 1 and not candidate["explicit"]:
            continue
        selected.append(candidate)
        domain_slots[domain] = domain_slots.get(domain, 0) + 1
        if len(selected) >= limit:
            break
    if len(selected) < limit:
        selected_keys = {item["key"] for item in selected}
        for candidate in scored:
            if candidate["key"] not in selected_keys:
                selected.append(candidate)
                selected_keys.add(candidate["key"])
                if len(selected) >= limit:
                    break

    top = max((item["score"] for item in selected), default=1.0)
    for item in selected:
        item["confidence"] = round(max(0.05, min(0.99, item["score"] / max(1.0, top))), 2)
    return selected


def record_impressions(behavior: dict, items: list[dict], surface: str, now: datetime | None = None) -> dict:
    """记录推荐曝光；同一入口同一 App 在 30 分钟内只记一次。"""
    now = now or datetime.now()
    history = behavior.setdefault("recommendation_history", [])
    for item in items:
        app = item.get("app") or item.get("key")
        duplicate = False
        for old in reversed(history[-30:]):
            if old.get("app") != app or old.get("surface") != surface:
                continue
            ts = _parse_time(old.get("time", ""))
            if ts and (now - ts).total_seconds() < 1800:
                duplicate = True
            break
        if not duplicate:
            history.append({"app": app, "surface": surface, "time": now.isoformat(timespec="seconds")})
    behavior["recommendation_history"] = history[-300:]
    return behavior
