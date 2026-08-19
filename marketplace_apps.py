# -*- coding: utf-8 -*-
"""应用市场功能模块（marketplace_apps.py）

提供手机应用市场功能，支持：
  - 应用分类浏览（创意、生活、学习、游戏、工具等）
  - 应用搜索和筛选（关键词、评分、热度）
  - 应用评价和评分系统
  - AI推荐系统（基于使用历史）
  - 混合模式：官方预置 + 用户分享

数据按 RolePath 隔离（owner 直存项目根，注册用户存 users_data/<user>/）
设计风格与现有 *_apps.py 模块保持一致。

API：
  GET    /api/marketplace/apps              获取应用列表（支持分类、搜索、筛选）
  GET    /api/marketplace/apps/{app_id}     获取单个应用详情
  POST   /api/marketplace/apps              创建新应用（用户分享）
  PUT    /api/marketplace/apps/{app_id}     更新应用信息
  DELETE /api/marketplace/apps/{app_id}     删除应用
  POST   /api/marketplace/apps/{app_id}/review  添加评价
  GET    /api/marketplace/recommendations   获取推荐应用
  GET    /api/marketplace/categories        获取分类列表
  GET    /api/marketplace/trending          获取热门应用
"""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

MARKETPLACE_FILE = "marketplace.json"
MARKETPLACE_USAGE_FILE = "marketplace_usage.json"

# 官方预置应用模板
OFFICIAL_APPS = [
    {
        "id": "official_dream",
        "name": "清梦",
        "category": "创意",
        "description": "在许墨的梦境中与他相遇，体验不同的梦境场景",
        "icon": "🌙",
        "author": "官方",
        "source": "official",
        "rating": 4.8,
        "downloads": 5200,
        "reviews": [],
        "tags": ["梦境", "互动", "浪漫"],
        "config": {"type": "creative", "module": "creative_apps", "function": "dream"}
    },
    {
        "id": "official_wardrobe",
        "name": "衣橱换装",
        "category": "生活",
        "description": "为许墨搭配不同的服装，生成换装立绘",
        "icon": "👔",
        "author": "官方",
        "source": "official",
        "rating": 4.6,
        "downloads": 4800,
        "reviews": [],
        "tags": ["换装", "立绘", "时尚"],
        "config": {"type": "life", "module": "life_apps", "function": "wardrobe"}
    },
    {
        "id": "official_study",
        "name": "监督背单词",
        "category": "学习",
        "description": "许墨监督你背单词，科学记忆曲线",
        "icon": "📚",
        "author": "官方",
        "source": "official",
        "rating": 4.5,
        "downloads": 3500,
        "reviews": [],
        "tags": ["学习", "单词", "记忆"],
        "config": {"type": "features", "module": "features", "function": "words"}
    },
    {
        "id": "official_oracle",
        "name": "决策预言家",
        "category": "创意",
        "description": "让许墨为你的人生决策提供预测和建议",
        "icon": "🔮",
        "author": "官方",
        "source": "official",
        "rating": 4.7,
        "downloads": 4100,
        "reviews": [],
        "tags": ["预测", "决策", "神秘"],
        "config": {"type": "wonder", "module": "wonder_apps", "function": "oracle"}
    },
    {
        "id": "official_habits",
        "name": "习惯养成管家",
        "category": "工具",
        "description": "许墨帮你培养好习惯，科学追踪进度",
        "icon": "✅",
        "author": "官方",
        "source": "official",
        "rating": 4.4,
        "downloads": 2900,
        "reviews": [],
        "tags": ["习惯", "追踪", "自我提升"],
        "config": {"type": "wonder", "module": "wonder_apps", "function": "habits"}
    },
    {
        "id": "official_timecall",
        "name": "时空热线",
        "category": "创意",
        "description": "拨打不同时间线上的许墨，体验不同时期的他",
        "icon": "📞",
        "author": "官方",
        "source": "official",
        "rating": 4.9,
        "downloads": 6100,
        "reviews": [],
        "tags": ["时空", "对话", "浪漫"],
        "config": {"type": "nova", "module": "nova_apps", "function": "timecall"}
    }
]

# 应用分类
CATEGORIES = [
    {"id": "creative", "name": "创意", "icon": "✨", "description": "创意互动和浪漫体验"},
    {"id": "life", "name": "生活", "icon": "🏠", "description": "日常生活和贴心助手"},
    {"id": "study", "name": "学习", "icon": "📖", "description": "学习辅导和知识管理"},
    {"id": "game", "name": "游戏", "icon": "🎮", "description": "小游戏和娱乐互动"},
    {"id": "tool", "name": "工具", "icon": "🔧", "description": "实用工具和效率提升"}
]


# ===========================================================================
# 公共工具函数
# ===========================================================================

def _load(path: str, default):
    """加载数据文件"""
    p = RolePath(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path: str, data):
    """保存数据文件"""
    atomic_json(RolePath(path), data)


def _now() -> str:
    """获取当前时间字符串"""
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _today() -> str:
    """获取今天日期字符串"""
    return datetime.now().strftime("%Y-%m-%d")


def _uid() -> str:
    """生成唯一ID"""
    return uuid.uuid4().hex[:12]


# ===========================================================================
# 数据加载和初始化
# ===========================================================================

def _load_marketplace() -> dict:
    """加载应用市场数据"""
    data = _load(MARKETPLACE_FILE, {"apps": [], "categories": CATEGORIES})
    
    # 确保官方应用存在
    existing_ids = {app.get("id") for app in data.get("apps", [])}
    for official_app in OFFICIAL_APPS:
        if official_app["id"] not in existing_ids:
            data.setdefault("apps", []).append(official_app)
            existing_ids.add(official_app["id"])
    
    # 确保分类存在
    if "categories" not in data:
        data["categories"] = CATEGORIES
    
    return data


def _load_usage() -> dict:
    """加载用户使用数据"""
    return _load(MARKETPLACE_USAGE_FILE, {"app_usage": {}, "search_history": []})


def _save_usage(data: dict):
    """保存用户使用数据"""
    _save(MARKETPLACE_USAGE_FILE, data)


# ===========================================================================
# 核心功能函数
# ===========================================================================

def _record_app_usage(app_id: str):
    """记录应用使用"""
    usage_data = _load_usage()
    app_usage = usage_data.setdefault("app_usage", {})
    
    if app_id in app_usage:
        app_usage[app_id]["last_used"] = _now()
        app_usage[app_id]["usage_count"] = app_usage[app_id].get("usage_count", 0) + 1
    else:
        app_usage[app_id] = {
            "last_used": _now(),
            "usage_count": 1,
            "first_used": _now()
        }
    
    _save_usage(usage_data)


def _calculate_app_score(app: dict, usage_data: dict) -> float:
    """计算应用推荐分数"""
    score = 0.0
    
    # 基础评分 (0-4分)
    rating = app.get("rating", 0)
    score += rating
    
    # 下载量影响 (0-1分)
    downloads = app.get("downloads", 0)
    if downloads > 5000:
        score += 1.0
    elif downloads > 2000:
        score += 0.7
    elif downloads > 1000:
        score += 0.4
    elif downloads > 500:
        score += 0.2
    
    # 用户使用频率影响 (0-2分)
    app_id = app.get("id")
    app_usage = usage_data.get("app_usage", {}).get(app_id, {})
    usage_count = app_usage.get("usage_count", 0)
    if usage_count > 20:
        score += 2.0
    elif usage_count > 10:
        score += 1.5
    elif usage_count > 5:
        score += 1.0
    elif usage_count > 0:
        score += 0.5
    
    # 最近使用时间影响 (0-1分)
    last_used = app_usage.get("last_used", "")
    if last_used:
        try:
            last_used_date = datetime.strptime(last_used, "%Y-%m-%d %H:%M")
            days_since_use = (datetime.now() - last_used_date).days
            if days_since_use < 1:
                score += 1.0
            elif days_since_use < 3:
                score += 0.7
            elif days_since_use < 7:
                score += 0.4
            elif days_since_use < 14:
                score += 0.2
        except ValueError:
            pass
    
    return score


def _filter_apps(apps: list, category: str = None, search: str = None, 
                 min_rating: float = None, source: str = None) -> list:
    """筛选应用"""
    filtered = apps
    
    if category:
        filtered = [app for app in filtered if app.get("category") == category]
    
    if search:
        search_lower = search.lower()
        filtered = [
            app for app in filtered 
            if search_lower in app.get("name", "").lower() or
               search_lower in app.get("description", "").lower() or
               any(search_lower in tag.lower() for tag in app.get("tags", []))
        ]
    
    if min_rating is not None:
        filtered = [app for app in filtered if app.get("rating", 0) >= min_rating]
    
    if source:
        filtered = [app for app in filtered if app.get("source") == source]
    
    return filtered


def _sort_apps(apps: list, sort_by: str = "rating") -> list:
    """排序应用"""
    if sort_by == "rating":
        return sorted(apps, key=lambda x: x.get("rating", 0), reverse=True)
    elif sort_by == "downloads":
        return sorted(apps, key=lambda x: x.get("downloads", 0), reverse=True)
    elif sort_by == "reviews":
        return sorted(apps, key=lambda x: len(x.get("reviews", [])), reverse=True)
    elif sort_by == "newest":
        return sorted(apps, key=lambda x: x.get("created_at", ""), reverse=True)
    else:
        return apps


# ===========================================================================
# API 路由
# ===========================================================================

@router.get("/api/marketplace/apps")
async def get_apps(
    category: str = None,
    search: str = None,
    min_rating: float = None,
    source: str = None,
    sort_by: str = "rating",
    limit: int = 50
):
    """获取应用列表，支持分类、搜索、筛选、排序"""
    marketplace = _load_marketplace()
    apps = marketplace.get("apps", [])
    
    # 筛选
    filtered = _filter_apps(apps, category, search, min_rating, source)
    
    # 排序
    sorted_apps = _sort_apps(filtered, sort_by)
    
    # 限制数量
    result = sorted_apps[:limit]
    
    return {
        "apps": result,
        "total": len(result),
        "filters": {
            "category": category,
            "search": search,
            "min_rating": min_rating,
            "source": source,
            "sort_by": sort_by
        }
    }


@router.get("/api/marketplace/apps/{app_id}")
async def get_app(app_id: str):
    """获取单个应用详情"""
    marketplace = _load_marketplace()
    apps = marketplace.get("apps", [])
    
    app = next((app for app in apps if app.get("id") == app_id), None)
    if not app:
        return JSONResponse({"error": "应用不存在"}, status_code=404)
    
    # 记录访问
    _record_app_usage(app_id)
    
    return app


@router.post("/api/marketplace/apps")
async def create_app(req: Request):
    """创建新应用（用户分享）"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    # 验证必填字段
    required_fields = ["name", "category", "description", "config"]
    for field in required_fields:
        if not body.get(field):
            return JSONResponse({"error": f"缺少必填字段: {field}"}, status_code=400)
    
    # 验证分类
    category = body["category"]
    valid_categories = [cat["id"] for cat in CATEGORIES]
    if category not in valid_categories:
        return JSONResponse({"error": f"无效的分类: {category}"}, status_code=400)
    
    marketplace = _load_marketplace()
    
    # 创建新应用
    new_app = {
        "id": f"user_{_uid()}",
        "name": body["name"],
        "category": category,
        "description": body["description"],
        "icon": body.get("icon", "📱"),
        "author": body.get("author", "用户"),
        "source": "user",
        "rating": 0.0,
        "downloads": 0,
        "reviews": [],
        "tags": body.get("tags", []),
        "config": body["config"],
        "created_at": _now(),
        "updated_at": _now()
    }
    
    marketplace.setdefault("apps", []).append(new_app)
    _save(MARKETPLACE_FILE, marketplace)
    
    return new_app


@router.put("/api/marketplace/apps/{app_id}")
async def update_app(app_id: str, req: Request):
    """更新应用信息"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    marketplace = _load_marketplace()
    apps = marketplace.get("apps", [])
    
    # 查找应用
    app_index = next((i for i, app in enumerate(apps) if app.get("id") == app_id), None)
    if app_index is None:
        return JSONResponse({"error": "应用不存在"}, status_code=404)
    
    app = apps[app_index]
    
    # 只有应用作者或官方应用可以更新
    if app.get("source") == "official":
        return JSONResponse({"error": "官方应用不允许修改"}, status_code=403)
    
    # 更新字段
    updatable_fields = ["name", "description", "icon", "tags", "config"]
    for field in updatable_fields:
        if field in body:
            app[field] = body[field]
    
    app["updated_at"] = _now()
    
    _save(MARKETPLACE_FILE, marketplace)
    
    return app


@router.delete("/api/marketplace/apps/{app_id}")
async def delete_app(app_id: str):
    """删除应用"""
    marketplace = _load_marketplace()
    apps = marketplace.get("apps", [])
    
    # 查找应用
    app = next((app for app in apps if app.get("id") == app_id), None)
    if not app:
        return JSONResponse({"error": "应用不存在"}, status_code=404)
    
    # 只有用户应用可以删除
    if app.get("source") == "official":
        return JSONResponse({"error": "官方应用不允许删除"}, status_code=403)
    
    # 删除应用
    marketplace["apps"] = [app for app in apps if app.get("id") != app_id]
    
    _save(MARKETPLACE_FILE, marketplace)
    
    return {"ok": True}


@router.post("/api/marketplace/apps/{app_id}/review")
async def add_review(app_id: str, req: Request):
    """添加应用评价"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    rating = body.get("rating")
    comment = body.get("comment", "")
    user = body.get("user", "匿名用户")
    
    if rating is None or not (1 <= rating <= 5):
        return JSONResponse({"error": "评分必须在1-5之间"}, status_code=400)
    
    marketplace = _load_marketplace()
    apps = marketplace.get("apps", [])
    
    # 查找应用
    app = next((app for app in apps if app.get("id") == app_id), None)
    if not app:
        return JSONResponse({"error": "应用不存在"}, status_code=404)
    
    # 添加评价
    review = {
        "id": _uid(),
        "user": user,
        "rating": rating,
        "comment": comment,
        "time": _now()
    }
    
    app.setdefault("reviews", []).append(review)
    
    # 重新计算平均评分
    reviews = app.get("reviews", [])
    if reviews:
        total_rating = sum(r.get("rating", 0) for r in reviews)
        app["rating"] = round(total_rating / len(reviews), 1)
    
    # 增加下载量（模拟）
    app["downloads"] = app.get("downloads", 0) + 1
    
    _save(MARKETPLACE_FILE, marketplace)
    
    return review


@router.get("/api/marketplace/recommendations")
async def get_recommendations(limit: int = 10):
    """获取推荐应用（基于使用历史和热度）"""
    marketplace = _load_marketplace()
    usage_data = _load_usage()
    
    apps = marketplace.get("apps", [])
    
    # 计算每个应用的推荐分数
    scored_apps = []
    for app in apps:
        score = _calculate_app_score(app, usage_data)
        scored_apps.append({"app": app, "score": score})
    
    # 按分数排序
    scored_apps.sort(key=lambda x: x["score"], reverse=True)
    
    # 返回推荐应用
    recommendations = [item["app"] for item in scored_apps[:limit]]
    
    return {
        "recommendations": recommendations,
        "total": len(recommendations)
    }


@router.get("/api/marketplace/categories")
async def get_categories():
    """获取分类列表"""
    return {"categories": CATEGORIES}


@router.get("/api/marketplace/trending")
async def get_trending(limit: int = 10):
    """获取热门应用（基于下载量和评价）"""
    marketplace = _load_marketplace()
    apps = marketplace.get("apps", [])
    
    # 按下载量和评分综合排序
    scored_apps = []
    for app in apps:
        downloads = app.get("downloads", 0)
        rating = app.get("rating", 0)
        score = downloads * 0.3 + rating * 2  # 下载量权重0.3，评分权重2
        scored_apps.append({"app": app, "score": score})
    
    scored_apps.sort(key=lambda x: x["score"], reverse=True)
    
    trending = [item["app"] for item in scored_apps[:limit]]
    
    return {
        "trending": trending,
        "total": len(trending)
    }


@router.post("/api/marketplace/apps/{app_id}/install")
async def install_app(app_id: str):
    """安装应用（记录安装和使用）"""
    marketplace = _load_marketplace()
    apps = marketplace.get("apps", [])
    
    app = next((app for app in apps if app.get("id") == app_id), None)
    if not app:
        return JSONResponse({"error": "应用不存在"}, status_code=404)
    
    # 记录使用
    _record_app_usage(app_id)
    
    # 增加下载量
    app["downloads"] = app.get("downloads", 0) + 1
    _save(MARKETPLACE_FILE, marketplace)
    
    return {
        "ok": True,
        "app": app,
        "message": f"已安装 {app['name']}"
    }