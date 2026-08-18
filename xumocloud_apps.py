# -*- coding: utf-8 -*-
"""许墨云资料库 · 集成路由

把 xumocloud.com 的公开数据（COS 静态 JSON）爬下来，缓存到本地，
再以现有功能（语录 / 衣橱 / 合影日历 / 黑天鹅档案 / 浏览器搜索）能直接
消费的形式分发出去。

设计要点：
- 数据源：腾讯云 COS bucket（公开读 + Referer 白名单）
  base = https://project-bft-1309650365.cos.na-siliconvalley.myqcloud.com/xumo_cloud
- 鉴权：仅需在请求头带 Referer: https://xumocloud.com/，无需登录/token
- 缓存：JSON 元数据缓存到 .cache/xcloud/json/，TTL 6 小时
        媒体（图片/音频）代理转发，磁盘缓存上限 600MB（LRU 粗清）
- 不新建前端 app：所有数据以「补丁」形式注入到 app-quotes / app-wardrobe /
  app-together / app-bsfile / app-browser 的现有 DOM 里
"""
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

router = APIRouter()

# ---------------------------------------------------------------------------
# 常量与路径
# ---------------------------------------------------------------------------
COS_BASE = "https://project-bft-1309650365.cos.na-siliconvalley.myqcloud.com/xumo_cloud"
REFERER = "https://xumocloud.com/"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " \
             "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"

BASE_DIR = Path(__file__).parent
CACHE_DIR = BASE_DIR / ".cache" / "xcloud"
JSON_CACHE_DIR = CACHE_DIR / "json"
MEDIA_CACHE_DIR = CACHE_DIR / "media"
JSON_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

JSON_TTL = 6 * 3600           # JSON 目录缓存 6 小时
MEDIA_CACHE_MAX_BYTES = 600 * 1024 * 1024   # 媒体磁盘缓存上限 600MB

# ---------------------------------------------------------------------------
# JSON 缓存层
# ---------------------------------------------------------------------------
_json_lock = asyncio.Lock()


def _json_cache_path(rel: str) -> Path:
    """根据 COS 相对路径生成本地 JSON 缓存文件路径。"""
    safe = hashlib.sha1(rel.encode("utf-8")).hexdigest()
    return JSON_CACHE_DIR / f"{safe}.json"


async def _fetch_cos_json(rel: str, force_refresh: bool = False) -> Any:
    """拉取 COS 上的 directory.json，带本地缓存。rel 形如 'gallery/directory.json'。"""
    cache = _json_cache_path(rel)
    now = time.time()
    if not force_refresh and cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            ts = raw.get("_ts", 0) if isinstance(raw, dict) else 0
            if now - ts < JSON_TTL:
                return raw.get("_data")
        except (json.JSONDecodeError, OSError):
            pass

    url = f"{COS_BASE}/{rel}"
    headers = {"Referer": REFERER, "User-Agent": USER_AGENT}
    # trust_env=False：不走系统代理（http_proxy / https_proxy），
    # 直连 COS bucket，否则在开了代理的环境会因代理未启动而失败。
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as cli:
        r = await cli.get(url, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"COS {rel} 拉取失败：HTTP {r.status_code}")
        try:
            data = r.json()
        except Exception as e:
            raise RuntimeError(f"COS {rel} 解析失败：{e}")

    async with _json_lock:
        cache.write_text(
            json.dumps({"_ts": now, "_data": data}, ensure_ascii=False),
            encoding="utf-8",
        )
    return data


# ---------------------------------------------------------------------------
# 媒体代理：绕开 COS Referer 白名单 + 本地磁盘缓存
# ---------------------------------------------------------------------------
async def _media_cache_housekeep():
    """粗粒度 LRU 清理：当磁盘占用超上限，按最旧 mtime 删一半文件。"""
    try:
        files = list(MEDIA_CACHE_DIR.rglob("*"))
        files = [f for f in files if f.is_file()]
        total = sum(f.stat().st_size for f in files)
        if total <= MEDIA_CACHE_MAX_BYTES:
            return
        files.sort(key=lambda f: f.stat().st_mtime)
        for f in files[: max(1, len(files) // 2)]:
            try:
                f.unlink()
            except OSError:
                pass
    except Exception:
        pass


@router.get("/api/xcloud/media")
async def xcloud_media(u: str = ""):
    """媒体代理：传 u=完整 COS URL 或 u=COS 相对路径，回传二进制流。"""
    if not u:
        return JSONResponse({"error": "缺少 u 参数"}, status_code=400)
    # 仅允许 xumo_cloud bucket 与 xumocloud.com 自己的资源，防止 SSRF
    allowed_prefixes = (
        COS_BASE,
        "https://project-bft-1309650365.cos.na-siliconvalley.myqcloud.com/",
        "https://xumocloud.com/",
    )
    full = u if u.startswith("http") else f"{COS_BASE}/{u.lstrip('/')}"
    if not full.startswith(allowed_prefixes):
        return JSONResponse({"error": "不在白名单内的资源"}, status_code=400)

    # 计算本地缓存路径
    key = hashlib.sha1(full.encode("utf-8")).hexdigest()
    ext = ""
    for e in (".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp3", ".m4a", ".wav", ".ogg"):
        if full.lower().rsplit("?", 1)[0].endswith(e):
            ext = e
            break
    cache = MEDIA_CACHE_DIR / f"{key}{ext}"
    if cache.exists() and cache.stat().st_size > 0:
        # 命中缓存，直接转发磁盘文件
        def _iter():
            with open(cache, "rb") as f:
                while True:
                    chunk = f.read(64 * 1024)
                    if not chunk:
                        break
                    yield chunk
        return StreamingResponse(_iter(), media_type=_guess_media(ext))

    # 拉远端
    await _media_cache_housekeep()
    headers = {"Referer": REFERER, "User-Agent": USER_AGENT}
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True, trust_env=False) as cli:
            r = await cli.get(full, headers=headers)
            if r.status_code != 200:
                return JSONResponse({"error": f"上游 {r.status_code}"}, status_code=502)
            content = r.content
            ct = r.headers.get("content-type", _guess_media(ext))
    except Exception as e:
        return JSONResponse({"error": f"代理失败：{e}"}, status_code=502)

    # 写入缓存
    try:
        cache.write_bytes(content)
    except OSError:
        pass

    return StreamingResponse(iter([content]), media_type=ct)


def _guess_media(ext: str) -> str:
    return {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".gif": "image/gif",
        ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
        ".wav": "audio/wav", ".ogg": "audio/ogg",
    }.get(ext.lower(), "application/octet-stream")


def _proxy_url(src: str) -> str:
    """把 COS 直链转成本代理 URL，绕开 Referer 白名单。"""
    if not src:
        return ""
    if src.startswith("http"):
        return f"/api/xcloud/media?u={src}"
    # 相对 COS 路径
    return f"/api/xcloud/media?u={COS_BASE}/{src.lstrip('/')}"


# ---------------------------------------------------------------------------
# 数据适配：把 xumocloud 原始数据结构 → 现有 app 能直接消费的结构
# ---------------------------------------------------------------------------

def _paginate(items: list, page: int, page_size: int) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(int(page_size), 60))
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": end < total,
    }


# ---------------------------------------------------------------------------
# 1. 语录 · 注入 app-quotes（音频原声语音库）
#    数据源：audio/voice/directory.json
#    字段：{id, category, title, audio, subcategory, background, bond[], textPath}
# ---------------------------------------------------------------------------
@router.get("/api/xcloud/quotes")
async def xcloud_quotes(page: int = 1, page_size: int = 30, q: str = ""):
    """许墨原声语音库：把官方音频语音 → app-quotes 能直接渲染的卡片。"""
    try:
        raw = await _fetch_cos_json("audio/voice/directory.json")
    except Exception as e:
        return JSONResponse({"error": f"语音库拉取失败：{e}"}, status_code=502)
    items = raw if isinstance(raw, list) else []
    out: List[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        bonds = it.get("bond") or []
        text = " · ".join(str(b) for b in bonds if b) if bonds else (it.get("title") or "")
        if q and q.lower() not in str(text).lower() and q.lower() not in str(it.get("title", "")).lower():
            continue
        out.append({
            "id": f"xcv_{it.get('id') or ''}",
            "kind": "voice",
            "title": it.get("title") or "",
            "text": text,
            "audio": _proxy_url(it.get("audio") or ""),
            "background": _proxy_url(it.get("background") or ""),
            "subcategory": it.get("subcategory") or "",
            "source": "许墨云 · 原声语音库",
        })
    return _paginate(out, page, page_size)


# ---------------------------------------------------------------------------
# 2. 衣橱 · 注入 app-wardrobe（官方衣橱）
#    数据源：daily/wardrobe/directory.json
#    字段：{id, name, src, contributor, desc?}
# ---------------------------------------------------------------------------
@router.get("/api/xcloud/wardrobe")
async def xcloud_wardrobe(page: int = 1, page_size: int = 30, q: str = ""):
    """官方衣橱：把 xumocloud 的衣橱图 → app-wardrobe 能直接渲染的格子。"""
    try:
        raw = await _fetch_cos_json("daily/wardrobe/directory.json")
    except Exception as e:
        return JSONResponse({"error": f"衣橱拉取失败：{e}"}, status_code=502)
    items = raw if isinstance(raw, list) else []
    out: List[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name") or ""
        desc = it.get("desc") or ""
        if q and q.lower() not in str(name).lower() and q.lower() not in str(desc).lower():
            continue
        out.append({
            "id": f"xcw_{it.get('id') or ''}",
            "name": name,
            "desc": desc,
            "img": _proxy_url(it.get("src") or ""),
            "contributor": it.get("contributor") or "",
            "source": "许墨云 · 官方衣橱",
        })
    return _paginate(out, page, page_size)


# ---------------------------------------------------------------------------
# 3. 合影日历 · 注入 app-together（全球生贺地图）
#    数据源：shenghe/directory.json
#    字段：{id, name, category, time, country, province, city, cities[]?, organizer, link}
# ---------------------------------------------------------------------------
@router.get("/api/xcloud/shenghe")
async def xcloud_shenghe(page: int = 1, page_size: int = 60, q: str = ""):
    """全球生贺地图：把生贺事件 → 合影日历能渲染的标记点。"""
    try:
        raw = await _fetch_cos_json("shenghe/directory.json")
    except Exception as e:
        return JSONResponse({"error": f"生贺拉取失败：{e}"}, status_code=502)
    items = raw if isinstance(raw, list) else []
    out: List[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("name") or ""
        city = it.get("city") or ""
        province = it.get("province") or ""
        country = it.get("country") or ""
        loc = " · ".join(x for x in [country, province, city] if x)
        if q:
            ql = q.lower()
            if ql not in str(name).lower() and ql not in str(loc).lower():
                continue
        out.append({
            "id": f"xcs_{it.get('id') or ''}",
            "name": name,
            "category": it.get("category") or "",
            "time": it.get("time") or "",
            "location": loc,
            "country": country,
            "province": province,
            "city": city,
            "organizer": it.get("organizer") or "",
            "link": it.get("link") or "",
            "source": "许墨云 · 全球生贺地图",
        })
    # 时间倒序（新的在前）
    out.sort(key=lambda x: x.get("time", ""), reverse=True)
    return _paginate(out, page, page_size)


# ---------------------------------------------------------------------------
# 4. 黑天鹅档案 · 注入 app-bsfile（角色传闻秘事）
#    数据源：character/characterFacts/directory.json
#    字段：{id, author, content[]}
# ---------------------------------------------------------------------------
@router.get("/api/xcloud/secret")
async def xcloud_secret(page: int = 1, page_size: int = 40, q: str = ""):
    """角色传闻秘事：把官方秘事 → app-bsfile 能直接渲染的档案条目。"""
    try:
        raw = await _fetch_cos_json("character/characterFacts/directory.json")
    except Exception as e:
        return JSONResponse({"error": f"秘事拉取失败：{e}"}, status_code=502)
    items = raw if isinstance(raw, list) else []
    out: List[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        contents = it.get("content") or []
        if isinstance(contents, str):
            contents = [contents]
        text = "\n".join(str(c) for c in contents if c)
        if q and q.lower() not in str(text).lower():
            continue
        out.append({
            "id": f"xcsf_{it.get('id') or ''}",
            "code": f"XC-{str(it.get('id') or '').zfill(3)}",
            "title": f"传闻秘事 · {it.get('author') or '匿名'}",
            "type": "传闻秘事",
            "text": text,
            "author": it.get("author") or "",
            "source": "许墨云 · 角色秘事",
            "unlocked": True,
        })
    return _paginate(out, page, page_size)


# ---------------------------------------------------------------------------
# 5. 浏览器搜索 · 注入 app-browser（全局搜索）
#    数据源：聚合多个 directory.json 做服务端检索（search-index.json 若有则优先）
# ---------------------------------------------------------------------------
@router.get("/api/xcloud/search")
async def xcloud_search(q: str = "", page: int = 1, page_size: int = 30):
    """全站搜索：跨图鉴 / 语音 / 衣橱 / 生贺 / 秘事 / 角色简介做关键字检索。"""
    q = (q or "").strip()
    if not q:
        return _paginate([], page, page_size)
    ql = q.lower()
    out: List[dict] = []

    async def _scan(rel: str, mapper):
        try:
            data = await _fetch_cos_json(rel)
        except Exception:
            return
        items = data if isinstance(data, list) else ([data] if isinstance(data, dict) else [])
        for it in items:
            if not isinstance(it, dict):
                continue
            rec = mapper(it)
            if not rec:
                continue
            title = str(rec.get("title") or "")
            text = str(rec.get("text") or "")
            if ql in title.lower() or ql in text.lower():
                out.append(rec)

    # 并行扫描所有数据源
    await asyncio.gather(
        _scan("gallery/directory.json", lambda it: {
            "title": it.get("title") or "图鉴",
            "text": it.get("quote") or "",
            "category": "图鉴 · " + (it.get("category") or ""),
            "url": "",
            "img": _proxy_url(it.get("src") or ""),
        }),
        _scan("audio/voice/directory.json", lambda it: {
            "title": it.get("title") or "语音",
            "text": " · ".join(str(b) for b in (it.get("bond") or []) if b),
            "category": "原声语音 · " + (it.get("subcategory") or ""),
            "url": _proxy_url(it.get("audio") or ""),
        }),
        _scan("audio/secret/directory.json", lambda it: {
            "title": it.get("title") or "秘事",
            "text": " · ".join(str(b) for b in (it.get("bond") or []) if b),
            "category": "视听 · 传闻秘事 · " + (it.get("subcategory") or ""),
            "url": _proxy_url(it.get("audio") or ""),
        }),
        _scan("daily/wardrobe/directory.json", lambda it: {
            "title": it.get("name") or "衣橱",
            "text": it.get("desc") or ("贡献者：" + (it.get("contributor") or "")),
            "category": "日常 · 官方衣橱",
            "url": _proxy_url(it.get("src") or ""),
        }),
        _scan("shenghe/directory.json", lambda it: {
            "title": it.get("name") or "生贺",
            "text": " · ".join(str(x) for x in [it.get("time"), it.get("city"), it.get("organizer")] if x),
            "category": "生贺 · " + (it.get("category") or ""),
            "url": it.get("link") or "",
        }),
        _scan("character/characterFacts/directory.json", lambda it: {
            "title": "传闻秘事 · " + (it.get("author") or "匿名"),
            "text": "\n".join(str(c) for c in (it.get("content") or []) if c),
            "category": "角色 · 传闻秘事",
            "url": "",
        }),
        _scan("character/characterDescription/directory.json", lambda it: {
            "title": "角色简介",
            "text": it if isinstance(it, str) else str(it),
            "category": "角色 · 简介",
            "url": "",
        }),
        _scan("character/characterGrowth/directory.json", lambda it: {
            "title": "成长经历",
            "text": it if isinstance(it, str) else str(it),
            "category": "角色 · 成长经历",
            "url": "",
        }),
        _scan("about/directory.json", lambda it: {
            "title": "关于许墨云",
            "text": str(it.get("introduction") or "") + " · " + str(it.get("claim") or ""),
            "category": "关于",
            "url": "https://xumocloud.com/",
        }),
    )
    # 截断长文本
    for r in out:
        if len(r["text"]) > 220:
            r["text"] = r["text"][:220] + "…"
    return _paginate(out, page, page_size)


# ---------------------------------------------------------------------------
# 6. 图鉴（备用入口 · 不挂单独 app，仅作为搜索结果的图片预览来源）
#    数据源：gallery/directory.json
#    字段：{id, src, title, quote, category, date}
# ---------------------------------------------------------------------------
@router.get("/api/xcloud/gallery")
async def xcloud_gallery(category: str = "", year: str = "", q: str = "",
                         page: int = 1, page_size: int = 12):
    try:
        raw = await _fetch_cos_json("gallery/directory.json")
    except Exception as e:
        return JSONResponse({"error": f"图鉴拉取失败：{e}"}, status_code=502)
    items = raw if isinstance(raw, list) else []
    out: List[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        if category and str(it.get("category", "")).lower() != category.lower():
            continue
        date = it.get("date") or ""
        if year and not str(date).startswith(str(year)):
            continue
        title = str(it.get("title") or "")
        quote = str(it.get("quote") or "")
        if q:
            ql = q.lower()
            if ql not in title.lower() and ql not in quote.lower():
                continue
        out.append({
            "id": f"xcg_{it.get('id') or ''}",
            "title": title,
            "quote": quote,
            "category": it.get("category") or "",
            "date": date,
            "img": _proxy_url(it.get("src") or ""),
            "source": "许墨云 · 图鉴",
        })
    return _paginate(out, page, page_size)


# ---------------------------------------------------------------------------
# 7. 总览：给前端一个汇总接口，用于诊断/欢迎信息
# ---------------------------------------------------------------------------
@router.get("/api/xcloud/overview")
async def xcloud_overview():
    """返回各模块缓存状态与计数，用于调试。"""
    info: Dict[str, Any] = {}
    for key, rel in [
        ("gallery", "gallery/directory.json"),
        ("voice", "audio/voice/directory.json"),
        ("wardrobe", "daily/wardrobe/directory.json"),
        ("shenghe", "shenghe/directory.json"),
        ("secret", "character/characterFacts/directory.json"),
    ]:
        try:
            data = await _fetch_cos_json(rel)
            count = len(data) if isinstance(data, list) else 1
            info[key] = {"count": count, "ok": True}
        except Exception as e:
            info[key] = {"count": 0, "ok": False, "error": str(e)[:100]}
    return {"base": COS_BASE, "modules": info}
