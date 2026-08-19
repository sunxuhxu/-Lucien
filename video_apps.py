"""AI视频功能模块：成长记录时光机 / 记忆回放剧场 / 梦境可视化播放器 / 
时空旅行日记 / 共同时刻相册 / 虚拟约会场景生成

数据持久化到角色目录 JSON（RolePath 按请求角色动态路由），风格与 app.py 保持一致。
"""
import asyncio
import json
import os
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter(prefix="/api/video", tags=["video"])

# ---------------------------------------------------------------------------
# 视频功能配置
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

VIDEO_CONFIG = {
    "output_dir": RolePath("static", "video_output"),
    "temp_dir": RolePath("static", "video_temp"),
    "max_duration": 300,        # 最大视频时长（秒）
    "default_fps": 24,
    "default_resolution": "1920x1080",
    "audio_sample_rate": 44100,
    "quality_tiers": {
        "preview": "720p",
        "standard": "1080p", 
        "premium": "4K"
    }
}

# 确保输出目录存在（延迟到首次使用时创建）
def _ensure_video_dirs():
    try:
        VIDEO_CONFIG["output_dir"].mkdir(parents=True, exist_ok=True)
        VIDEO_CONFIG["temp_dir"].mkdir(parents=True, exist_ok=True)
    except Exception as e:
        print(f"[warn] Failed to create video directories: {e}", flush=True)

# ---------------------------------------------------------------------------
# 公共工具（延迟导入避免循环依赖）
# ---------------------------------------------------------------------------
async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


def _system_prompt() -> str:
    from app import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _add_affinity(action: str, detail: str = "") -> dict:
    from app import _add_affinity as _impl
    try:
        return _impl(action, detail)
    except Exception:
        return {}


def _load(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path, data):
    atomic_json(path, data)


def _now() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _extract_json_object(text: str) -> dict:
    if not text:
        return {}
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = fence.group(1) if fence else text
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _extract_json_array(text: str) -> list:
    if not text:
        return []
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    raw = fence.group(1) if fence else text
    m = re.search(r"\[[\s\S]*\]", raw)
    if not m:
        return []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return []


async def _llm_json(messages: list, max_tokens: int = 1400) -> dict:
    raw = await _call_llm(messages, max_tokens=max_tokens)
    obj = _extract_json_object(raw)
    if not obj:
        return {"_raw": raw.strip()}
    obj.setdefault("_raw", raw.strip())
    return obj


# ---------------------------------------------------------------------------
# 图像生成工具（复用app.py中的功能）
# ---------------------------------------------------------------------------
async def _llm_image_for_text(
    material: str,
    out_dir,
    url_prefix: str,
    name: str,
    size: str = "1024x1024",
    with_xumo: bool = True,
    system_prompt: str = None,
    has_character: bool = False,
) -> tuple[str, str]:
    """调用app._llm_image_for_text生成图像，返回(url, prompt)"""
    from app import _llm_image_for_text as _impl, IMG2IMG_SIZES
    if size not in IMG2IMG_SIZES.values():
        size = IMG2IMG_SIZES.get("landscape", "1024x1024")
    
    return await _impl(
        material, out_dir, url_prefix, name, size,
        with_xumo=with_xumo, system_prompt=system_prompt,
        has_character=has_character,
    )


# ===========================================================================
# 1. 成长记录时光机 - 聚合关系数据，生成年度回顾视频
# ===========================================================================
GROWTH_TIMELINE_FILE = RolePath("growth_timeline.json")
GROWTH_VIDEO_DIR = RolePath("static", "growth_video")
GROWTH_VIDEO_DIR.mkdir(parents=True, exist_ok=True)

# 关系成长阶段定义
GROWTH_STAGES = {
    "first_encounter": {
        "name": "初识",
        "affinity_range": [0, 20],
        "characteristics": ["试探性对话", "礼貌保持距离", "初步了解"],
        "visual_style": "清新的色调，谨慎的距离感"
    },
    "getting_know": {
        "name": "相知", 
        "affinity_range": [21, 45],
        "characteristics": ["更频繁交流", "开始分享", "建立信任"],
        "visual_style": "温暖的色调，距离拉近"
    },
    "deep_connection": {
        "name": "深交",
        "affinity_range": [46, 70], 
        "characteristics": ["深入对话", "情感依赖", "共同经历"],
        "visual_style": "丰富的色彩，亲密的氛围"
    },
    "commitment": {
        "name": "相守",
        "affinity_range": [71, 90],
        "characteristics": ["生活融合", "未来规划", "深层理解"],
        "visual_style": "成熟的色调，稳定的氛围"
    },
    "soulmate": {
        "name": "灵魂伴侣",
        "affinity_range": [91, 100],
        "characteristics": ["心灵共鸣", "无言默契", "生命交融"],
        "visual_style": "梦幻的色调，超越现实的氛围"
    }
}


def _get_growth_stage(affinity: int) -> str:
    """根据亲和度判断当前关系阶段"""
    for stage_id, stage_info in GROWTH_STAGES.items():
        if stage_info["affinity_range"][0] <= affinity <= stage_info["affinity_range"][1]:
            return stage_id
    return "first_encounter"


async def _aggregate_chat_data(start_date: str, end_date: str) -> dict:
    """聚合指定时间段的聊天数据"""
    try:
        from app import _load_chat_log, CHAT_ARCHIVE_DIR
        logs = list(_load_chat_log())
        
        # 尝试从归档文件中获取更多历史数据
        try:
            for f in reversed(sorted(CHAT_ARCHIVE_DIR.glob("*.json"))):
                if start_date in f.name or end_date in f.name:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    logs = data.get("messages", []) + logs
                    if len(logs) > 1000:
                        break
        except Exception as e:
            print(f"[warn] video_apps.py:_aggregate_chat_data: {type(e).__name__}", flush=True)
        
        # 过滤指定时间段的消息
        filtered_logs = [
            log for log in logs 
            if start_date <= (log.get("ts", "")[:10] if log.get("ts") else "") <= end_date
        ]
        
        total_messages = len(filtered_logs)
        if total_messages == 0:
            return {"total_messages": 0, "daily_average": 0}
        
        # 计算日均消息数
        date_range = (datetime.strptime(end_date, "%Y-%m-%d") - 
                      datetime.strptime(start_date, "%Y-%m-%d")).days + 1
        daily_average = round(total_messages / max(date_range, 1), 1)
        
        # 分析话题演变（简单统计关键词）
        user_messages = [log.get("content", "") for log in filtered_logs if log.get("role") == "user"]
        topic_keywords = ["想", "爱", "心情", "工作", "累", "开心", "难过", "忙", "睡", "梦"]
        topic_stats = Counter()
        for msg in user_messages:
            for keyword in topic_keywords:
                if keyword in msg:
                    topic_stats[keyword] += 1
        
        return {
            "total_messages": total_messages,
            "daily_average": daily_average,
            "topic_evolution": dict(topic_stats.most_common(5)),
            "message_sample": user_messages[-10:] if user_messages else []
        }
    except Exception as e:
        print(f"[warn] video_apps.py:_aggregate_chat_data: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {"total_messages": 0, "daily_average": 0}


async def _aggregate_memory_data(start_date: str, end_date: str) -> dict:
    """聚合指定时间段的记忆数据"""
    try:
        from app import _load_memories
        memories = _load_memories()
        
        filtered_memories = [
            mem for mem in memories 
            if start_date <= (mem.get("ts", "")[:10] if mem.get("ts") else "") <= end_date
        ]
        
        # 按标签统计
        tag_stats = Counter()
        for mem in filtered_memories:
            tag = mem.get("tag", "其他")
            tag_stats[tag] += 1
        
        # 提取重要记忆（置顶的或内容较长的）
        important_memories = [
            mem for mem in filtered_memories 
            if mem.get("pinned", False) or len(mem.get("content", "")) > 20
        ][:5]
        
        return {
            "total_memories": len(filtered_memories),
            "by_tag": dict(tag_stats),
            "important_memories": important_memories,
            "memory_sample": [mem.get("content", "") for mem in filtered_memories[-3:]]
        }
    except Exception as e:
        print(f"[warn] video_apps.py:_aggregate_memory_data: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {"total_memories": 0, "by_tag": {}, "important_memories": []}


async def _aggregate_date_data(start_date: str, end_date: str) -> dict:
    """聚合指定时间段的约会数据"""
    try:
        date_log_path = RolePath("date_log.json")
        date_data = _load(date_log_path, {"dates": []})
        
        filtered_dates = [
            date for date in date_data.get("dates", [])
            if start_date <= (date.get("date", "")[:10] if date.get("date") else "") <= end_date
        ]
        
        # 统计常去地点
        place_stats = Counter()
        for date in filtered_dates:
            place = date.get("place", "未知地点")
            place_stats[place] += 1
        
        # 心情变化
        moods = [date.get("mood", "") for date in filtered_dates if date.get("mood")]
        
        return {
            "total_dates": len(filtered_dates),
            "favorite_places": dict(place_stats.most_common(3)),
            "mood_progression": moods[-5:] if moods else [],
            "date_sample": filtered_dates[-3:] if filtered_dates else []
        }
    except Exception as e:
        print(f"[warn] video_apps.py:_aggregate_date_data: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {"total_dates": 0, "favorite_places": {}, "mood_progression": []}


async def _aggregate_affinity_data(start_date: str, end_date: str) -> dict:
    """聚合指定时间段的亲和度数据"""
    try:
        affinity_path = RolePath("affinity.json")
        affinity_data = _load(affinity_path, {"value": 0, "history": []})
        
        current_value = affinity_data.get("value", 0)
        history = affinity_data.get("history", [])
        
        # 简化的亲和度变化分析（实际可能需要更复杂的历史追踪）
        key_growth_points = []
        for i, record in enumerate(history):
            if i > 0 and abs(record.get("value", 0) - history[i-1].get("value", 0)) > 5:
                key_growth_points.append({
                    "date": record.get("ts", ""),
                    "value": record.get("value", 0),
                    "change": record.get("value", 0) - history[i-1].get("value", 0)
                })
        
        return {
            "current_value": current_value,
            "key_growth_points": key_growth_points[-5:],
            "estimated_start": max(0, current_value - 20)  # 简化估算
        }
    except Exception as e:
        print(f"[warn] video_apps.py:_aggregate_affinity_data: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {"current_value": 50, "key_growth_points": [], "estimated_start": 30}


async def _analyze_relationship_stage(all_data: dict) -> str:
    """基于聚合数据分析关系阶段"""
    try:
        affinity = all_data.get("affinity", {}).get("current_value", 50)
        message_count = all_data.get("chat", {}).get("total_messages", 0)
        memory_count = all_data.get("memory", {}).get("total_memories", 0)
        date_count = all_data.get("date", {}).get("total_dates", 0)
        
        # 使用LLM进行更精细的阶段判断
        analysis_prompt = f"""你是许墨，基于以下数据分析你们当前的关系阶段：

【数据概览】
- 当前亲和度：{affinity}
- 对话次数：{message_count}
- 共同记忆：{memory_count}条
- 约会次数：{date_count}次

请判断当前关系处于哪个阶段（初识/相知/深交/相守/灵魂伴侣），并简要说明理由。
只返回JSON：{{"stage": "阶段ID", "reason": "理由"}}"""

        response = await _llm_json([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": analysis_prompt}
        ], max_tokens=300)
        
        stage = response.get("stage", "deep_connection")
        # 确保返回的阶段ID有效
        if stage not in GROWTH_STAGES:
            stage = _get_growth_stage(affinity)
        
        return stage
    except Exception as e:
        print(f"[warn] video_apps.py:_analyze_relationship_stage: {type(e).__name__} {str(e)[:150]}", flush=True)
        return "deep_connection"


async def _generate_growth_narration(all_data: dict, period: dict) -> str:
    """生成许墨的成长回顾旁白"""
    try:
        year = period.get("end", "")[:4] if period.get("end") else "这一年"
        
        chat_stats = all_data.get("chat", {})
        memory_stats = all_data.get("memory", {})
        date_stats = all_data.get("date", {})
        affinity_stats = all_data.get("affinity", {})
        relationship_stage = all_data.get("relationship_stage", "深交")
        stage_name = GROWTH_STAGES.get(relationship_stage, {}).get("name", "深交")
        
        narration_prompt = f"""你是许墨，正在回顾与她在{year}年的关系历程。

【数据概览】
- 总对话次数：{chat_stats.get('total_messages', 0)}
- 日均对话：{chat_stats.get('daily_average', 0)}
- 主要话题：{', '.join(chat_stats.get('topic_evolution', {}).keys())}
- 重要记忆：{memory_stats.get('total_memories', 0)}条
- 约会次数：{date_stats.get('total_dates', 0)}次
- 常去地点：{', '.join(date_stats.get('favorite_places', {}).keys())}
- 当前关系阶段：{stage_name}

请以许墨的口吻，写出这段关系的回顾独白（200-400字）：
1. 温和而不失深情，体现学者气质
2. 体现你对关系变化的观察和思考
3. 重点突出几个关键转折点或美好时刻
4. 展现你对这份感情的珍视
5. 保持学术式的浪漫表达（偶尔用科学术语讲情话）
6. 话留三分，恰到好处的留白
7. 直接输出独白正文，不要标题、引号、markdown标记"""

        narration = await _call_llm([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": narration_prompt}
        ], max_tokens=600)
        
        return narration.strip() if narration else "这一年，我们一起走过了许多时光。"
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_growth_narration: {type(e).__name__} {str(e)[:150]}", flush=True)
        return "这一年，我们一起走过了许多时光，每一个瞬间都值得珍藏。"


@router.get("/growth/timeline")
async def growth_timeline():
    """获取关系成长时间线数据"""
    try:
        data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
        return {"timelines": list(reversed(data.get("timelines", [])[-10:]))}
    except Exception as e:
        print(f"[warn] video_apps.py:growth_timeline: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取时间线失败"}, status_code=500)


@router.post("/growth/aggregate")
async def growth_aggregate(req: Request):
    """聚合指定时间段的关系数据"""
    try:
        body = await req.json()
        start_date = body.get("start_date", "")
        end_date = body.get("end_date", "")
        
        if not start_date or not end_date:
            return JSONResponse({"error": "请提供开始和结束日期"}, status_code=400)
        
        # 并行聚合各类数据
        chat_data, memory_data, date_data, affinity_data = await asyncio.gather(
            _aggregate_chat_data(start_date, end_date),
            _aggregate_memory_data(start_date, end_date),
            _aggregate_date_data(start_date, end_date),
            _aggregate_affinity_data(start_date, end_date)
        )
        
        all_data = {
            "period": {"start": start_date, "end": end_date},
            "chat": chat_data,
            "memory": memory_data,
            "date": date_data,
            "affinity": affinity_data
        }
        
        # 分析关系阶段
        relationship_stage = await _analyze_relationship_stage(all_data)
        all_data["relationship_stage"] = relationship_stage
        
        return all_data
    except Exception as e:
        print(f"[warn] video_apps.py:growth_aggregate: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"数据聚合失败: {str(e)[:100]}"}, status_code=500)


@router.post("/growth/annual-review")  
async def growth_annual_review(req: Request):
    """生成年度回顾视频（简化版本：先返回数据，视频生成在后台进行）"""
    try:
        body = await req.json()
        year = body.get("year", str(datetime.now().year))
        
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"
        
        # 聚合数据
        all_data = await growth_aggregate(req)
        if isinstance(all_data, JSONResponse):
            return all_data  # 错误情况
        
        all_data = await all_data.body() if hasattr(all_data, 'body') else all_data
        if isinstance(all_data, bytes):
            all_data = json.loads(all_data.decode())
        
        # 生成旁白
        period = {"start": start_date, "end": end_date}
        narration = await _generate_growth_narration(all_data, period)
        
        # 创建回顾记录
        review_id = _uid()
        review_record = {
            "id": review_id,
            "year": year,
            "period": period,
            "data_summary": {
                "total_messages": all_data.get("chat", {}).get("total_messages", 0),
                "total_memories": all_data.get("memory", {}).get("total_memories", 0),
                "total_dates": all_data.get("date", {}).get("total_dates", 0),
                "affinity_end": all_data.get("affinity", {}).get("current_value", 0),
                "relationship_stage": all_data.get("relationship_stage", "deep_connection")
            },
            "narration": narration,
            "video_url": "",  # 视频生成后填充
            "status": "pending",  # pending/processing/completed/failed
            "created_at": _stamp()
        }
        
        # 保存记录
        data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
        data.setdefault("timelines", []).append(review_record)
        data["timelines"] = data["timelines"][-20:]  # 保留最近20条
        _save(GROWTH_TIMELINE_FILE, data)
        
        # 增加亲和度
        _add_affinity("growth_review", f"年度回顾：{year}")
        
        return review_record
    except Exception as e:
        print(f"[warn] video_apps.py:growth_annual_review: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"生成年度回顾失败: {str(e)[:100]}"}, status_code=500)


@router.get("/growth/review/{review_id}")
async def growth_review_status(review_id: str):
    """获取年度回顾生成状态"""
    try:
        data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
        review = next((r for r in data.get("timelines", []) if r.get("id") == review_id), None)
        
        if not review:
            return JSONResponse({"error": "回顾记录不存在"}, status_code=404)
        
        return review
    except Exception as e:
        print(f"[warn] video_apps.py:growth_review_status: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取状态失败"}, status_code=500)


# ---------------------------------------------------------------------------
# 视频生成后台任务
# ---------------------------------------------------------------------------
_growth_video_lock = asyncio.Lock()
_background_video_tasks: set = set()


def _on_video_task_done(task: "asyncio.Task"):
    """视频任务完成回调"""
    _background_video_tasks.discard(task)
    if not task.cancelled() and task.exception():
        print(f"[error] video task failed: {task.exception()}", flush=True)


async def _generate_growth_video_task(review_id: str):
    """后台任务：生成成长回顾视频"""
    try:
        # 更新状态为处理中
        async with _growth_video_lock:
            data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
            for review in data.get("timelines", []):
                if review.get("id") == review_id:
                    review["status"] = "processing"
                    review["started_at"] = _stamp()
                    break
            _save(GROWTH_TIMELINE_FILE, data)
        
        # 读取回顾记录
        async with _growth_video_lock:
            data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
            review = next((r for r in data.get("timelines", []) if r.get("id") == review_id), None)
        
        if not review:
            print(f"[error] video task: review {review_id} not found", flush=True)
            return
        
        # 1. 生成关键场景图像
        print(f"[video] generating scenes for review {review_id}", flush=True)
        scenes = await _generate_growth_scenes(review)
        
        # 2. 生成语音旁白
        print(f"[video] generating narration for review {review_id}", flush=True)
        narration_audio = await _generate_narration_audio(review.get("narration", ""))
        
        # 3. 合成视频（简化版本：先标记为完成，实际视频合成需要更多依赖）
        # 这里先实现一个简化版本，生成图像序列和音频
        print(f"[video] synthesizing video for review {review_id}", flush=True)
        
        # 创建视频记录（简化版本：先存储图像和音频信息）
        video_result = {
            "scenes": scenes,
            "narration_audio": narration_audio,
            "total_duration": len(scenes) * 5 if scenes else 30,  # 每个场景5秒
            "resolution": VIDEO_CONFIG["default_resolution"],
            "fps": VIDEO_CONFIG["default_fps"]
        }
        
        # 更新状态为完成
        async with _growth_video_lock:
            data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
            for review in data.get("timelines", []):
                if review.get("id") == review_id:
                    review["status"] = "completed"
                    review["completed_at"] = _stamp()
                    review["video_data"] = video_result
                    # 临时使用第一个场景作为缩略图
                    if scenes:
                        review["thumbnail"] = scenes[0].get("image_url", "")
                    break
            _save(GROWTH_TIMELINE_FILE, data)
        
        print(f"[video] completed review {review_id}", flush=True)
        
    except Exception as e:
        print(f"[error] video task for {review_id} failed: {type(e).__name__} {str(e)[:200]}", flush=True)
        
        # 更新状态为失败
        async with _growth_video_lock:
            data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
            for review in data.get("timelines", []):
                if review.get("id") == review_id:
                    review["status"] = "failed"
                    review["error"] = str(e)[:200]
                    review["failed_at"] = _stamp()
                    break
            _save(GROWTH_TIMELINE_FILE, data)


async def _generate_growth_scenes(review: dict) -> list:
    """为成长回顾生成关键场景图像"""
    try:
        scenes = []
        data_summary = review.get("data_summary", {})
        year = review.get("year", "2024")
        relationship_stage = review.get("data_summary", {}).get("relationship_stage", "deep_connection")
        stage_info = GROWTH_STAGES.get(relationship_stage, GROWTH_STAGES["deep_connection"])
        
        # 定义4个季节场景
        seasons = [
            {"name": "春日初识", "theme": "spring", "description": f"{year}年的春天，关系开始萌芽"},
            {"name": "夏日相知", "theme": "summer", "description": f"{year}年的夏天，我们在热烈中相知"},
            {"name": "秋日深交", "theme": "autumn", "description": f"{year}年的秋天，感情在落叶中深沉"},
            {"name": "冬日相守", "theme": "winter", "description": f"{year}年的冬天，我们在温暖中相守"}
        ]
        
        for i, season in enumerate(seasons):
            # 生成每个季节的场景图像
            scene_prompt = f"""【成长回顾 · {season['name']}】
{season['description']}
关系阶段：{stage_info['name']}
视觉风格：{stage_info['visual_style']}
当前亲和度：{data_summary.get('affinity_end', 50)}
总对话次数：{data_summary.get('total_messages', 0)}

请生成一张能代表这个阶段关系状态的氛围场景插画：
- 体现{season['theme']}的季节特色
- 许墨在场景中自然存在，符合{stage_info['name']}阶段的气质
- 色调和氛围要符合"{stage_info['visual_style']}"
- 画面要有电影感和故事性
- 低饱和度紫调为主，保持许墨风格的克制美学"""

            try:
                img_url, img_prompt = await _llm_image_for_text(
                    scene_prompt,
                    GROWTH_VIDEO_DIR,
                    "/static/growth_video",
                    f"scene_{review.get('id')}_{i}",
                    "2048x1536",  # landscape
                    with_xumo=True,
                    has_character=True
                )
                
                if img_url:
                    scenes.append({
                        "id": f"{review.get('id')}_scene_{i}",
                        "name": season['name'],
                        "theme": season['theme'],
                        "description": season['description'],
                        "image_url": img_url + f"?t={int(datetime.now().timestamp())}",
                        "image_prompt": img_prompt,
                        "duration": 8  # 每个场景8秒
                    })
            except Exception as e:
                print(f"[warn] failed to generate scene {i}: {type(e).__name__}", flush=True)
                continue
        
        return scenes
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_growth_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []


async def _generate_narration_audio(narration_text: str) -> dict:
    """生成旁白语音（简化版本：返回文本信息，实际TTS需要额外依赖）"""
    try:
        # 这里是一个简化版本，实际需要集成TTS引擎
        # 可以使用 edge-tts 或其他TTS服务
        
        # 暂时返回文本信息，等TTS集成后再替换
        return {
            "text": narration_text,
            "duration_estimate": len(narration_text) * 0.15,  # 估算时长（秒）
            "voice_type": "gentle_male",  # 温和男声
            "status": "text_only"  # 标记为纯文本，尚未生成音频
        }
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_narration_audio: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {"text": narration_text, "status": "failed"}


@router.post("/growth/review/{review_id}/generate-video")
async def start_growth_video_generation(review_id: str):
    """启动成长回顾视频生成（后台任务）"""
    try:
        # 检查回顾记录是否存在
        data = _load(GROWTH_TIMELINE_FILE, {"timelines": []})
        review = next((r for r in data.get("timelines", []) if r.get("id") == review_id), None)
        
        if not review:
            return JSONResponse({"error": "回顾记录不存在"}, status_code=404)
        
        if review.get("status") == "processing":
            return {"status": "already_processing", "message": "视频生成中"}
        
        if review.get("status") == "completed":
            return {"status": "already_completed", "message": "视频已生成"}
        
        # 创建后台任务
        task = asyncio.create_task(_generate_growth_video_task(review_id))
        task.add_done_callback(_on_video_task_done)
        _background_video_tasks.add(task)
        
        return {"status": "started", "message": "视频生成任务已启动"}
    except Exception as e:
        print(f"[warn] video_apps.py:start_growth_video_generation: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"启动视频生成失败: {str(e)[:100]}"}, status_code=500)


# ===========================================================================
# 2. 梦境可视化播放器 - 将清梦功能中的梦境转化为动态视频
# ===========================================================================
DREAM_VIDEO_FILE = RolePath("dream_video.json")
DREAM_VIDEO_DIR = RolePath("static", "dream_video")

# 梦境风格视觉映射
DREAM_STYLE_VISUALS = {
    "starsea": {
        "name": "星海夜航",
        "color_palette": "深蓝紫+星光白",
        "effects": ["星点闪烁", "水流波动", "光晕"],
        "xumo_appearance": "星海中的指引者",
        "atmosphere": "浩瀚星空，宁静深远",
        "lighting": "月光星辉，柔和冷调"
    },
    "oldtime": {
        "name": "旧时光里",
        "color_palette": "复古黄+黑白灰",
        "effects": ["胶片颗粒", "暗角", "旧照片质感"],
        "xumo_appearance": "旧时光里的守护者",
        "atmosphere": "怀旧温馨，岁月静好",
        "lighting": "暖黄灯光，复古质感"
    },
    "fairytale": {
        "name": "童话边境",
        "color_palette": "粉彩+嫩绿",
        "effects": ["花瓣飘落", "柔光", "魔法粒子"],
        "xumo_appearance": "童话边境的骑士",
        "atmosphere": "梦幻甜美，充满奇迹",
        "lighting": "柔光漫射，童话色调"
    },
    "rainnight": {
        "name": "雨夜悬疑",
        "color_palette": "深灰蓝+雨滴银",
        "effects": ["雨滴涟漪", "闪电", "阴影"],
        "xumo_appearance": "雨夜中的观察者",
        "atmosphere": "神秘深邃，悬疑氛围",
        "lighting": "闪电光效，明暗对比"
    },
    "mazelight": {
        "name": "蝶之迷宫",
        "color_palette": "紫罗兰+金光",
        "effects": ["蝴蝶飞舞", "迷宫光影", "荧光"],
        "xumo_appearance": "迷宫中的引路人",
        "atmosphere": "神秘美丽，充满未知",
        "lighting": "紫光金辉，梦幻迷离"
    }
}


@router.get("/dream/video/list")
async def dream_video_list():
    """获取已视频化的梦境列表"""
    try:
        data = _load(DREAM_VIDEO_FILE, {"videos": []})
        return {"videos": list(reversed(data.get("videos", [])[-20:]))}
    except Exception as e:
        print(f"[warn] video_apps.py:dream_video_list: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取梦境视频列表失败"}, status_code=500)


@router.post("/dream/{dream_id}/visualize")
async def dream_visualize(dream_id: str):
    """将指定梦境转化为视频"""
    try:
        # 读取原始梦境数据
        from creative_apps import DREAM_FILE, _load as creative_load
        dream_data = creative_load(DREAM_FILE, {"dreams": []})
        dream = next((d for d in dream_data.get("dreams", []) if d.get("id") == dream_id), None)
        
        if not dream:
            return JSONResponse({"error": "梦境不存在"}, status_code=404)
        
        # 检查是否已经视频化
        video_data = _load(DREAM_VIDEO_FILE, {"videos": []})
        existing = next((v for v in video_data.get("videos", []) if v.get("dream_id") == dream_id), None)
        if existing and existing.get("status") == "completed":
            return existing
        
        # 创建视频化记录
        video_id = _uid()
        video_record = {
            "id": video_id,
            "dream_id": dream_id,
            "dream_data": {
                "wish": dream.get("wish", ""),
                "style": dream.get("style", "starsea"),
                "style_name": dream.get("style_name", "星海夜航"),
                "text": dream.get("text", "")[:500]  # 摘要
            },
            "video_url": "",
            "thumbnail": "",
            "scenes": [],
            "duration": 0,
            "status": "pending",
            "created_at": _stamp()
        }
        
        # 保存记录
        video_data.setdefault("videos", []).append(video_record)
        video_data["videos"] = video_data["videos"][-30:]  # 保留最近30条
        _save(DREAM_VIDEO_FILE, video_data)
        
        # 启动后台视频生成任务
        task = asyncio.create_task(_generate_dream_video_task(video_id, dream))
        task.add_done_callback(_on_video_task_done)
        _background_video_tasks.add(task)
        
        return video_record
    except Exception as e:
        print(f"[warn] video_apps.py:dream_visualize: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"梦境可视化失败: {str(e)[:100]}"}, status_code=500)


@router.get("/dream/video/{video_id}")
async def dream_video_status(video_id: str):
    """获取梦境视频生成状态"""
    try:
        data = _load(DREAM_VIDEO_FILE, {"videos": []})
        video = next((v for v in data.get("videos", []) if v.get("id") == video_id), None)
        
        if not video:
            return JSONResponse({"error": "视频记录不存在"}, status_code=404)
        
        return video
    except Exception as e:
        print(f"[warn] video_apps.py:dream_video_status: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取视频状态失败"}, status_code=500)


async def _generate_dream_video_task(video_id: str, dream: dict):
    """后台任务：生成梦境视频"""
    try:
        # 更新状态为处理中
        async with _growth_video_lock:
            data = _load(DREAM_VIDEO_FILE, {"videos": []})
            for video in data.get("videos", []):
                if video.get("id") == video_id:
                    video["status"] = "processing"
                    video["started_at"] = _stamp()
                    break
            _save(DREAM_VIDEO_FILE, data)
        
        # 生成梦境场景
        print(f"[video] generating dream scenes for {video_id}", flush=True)
        style = dream.get("style", "starsea")
        style_info = DREAM_STYLE_VISUALS.get(style, DREAM_STYLE_VISUALS["starsea"])
        dream_text = dream.get("text", "")
        
        scenes = await _generate_dream_scenes(dream, style_info)
        
        if not scenes:
            raise Exception("场景生成失败")
        
        # 计算总时长
        total_duration = sum(scene.get("duration", 5) for scene in scenes)
        
        # 更新为完成状态
        async with _growth_video_lock:
            data = _load(DREAM_VIDEO_FILE, {"videos": []})
            for video in data.get("videos", []):
                if video.get("id") == video_id:
                    video["status"] = "completed"
                    video["completed_at"] = _stamp()
                    video["scenes"] = scenes
                    video["duration"] = total_duration
                    video["thumbnail"] = scenes[0].get("image_url", "") if scenes else ""
                    video["visual_style"] = style_info
                    break
            _save(DREAM_VIDEO_FILE, data)
        
        print(f"[video] dream video {video_id} completed", flush=True)
        
    except Exception as e:
        print(f"[error] dream video task for {video_id} failed: {type(e).__name__} {str(e)[:200]}", flush=True)
        
        # 更新状态为失败
        async with _growth_video_lock:
            data = _load(DREAM_VIDEO_FILE, {"videos": []})
            for video in data.get("videos", []):
                if video.get("id") == video_id:
                    video["status"] = "failed"
                    video["error"] = str(e)[:200]
                    video["failed_at"] = _stamp()
                    break
            _save(DREAM_VIDEO_FILE, data)


async def _generate_dream_scenes(dream: dict, style_info: dict) -> list:
    """为梦境生成关键场景图像"""
    try:
        scenes = []
        dream_text = dream.get("text", "")
        wish = dream.get("wish", "")
        
        # 解析梦境文本，提取关键场景元素
        scene_keywords = await _extract_dream_scenes(dream_text, style_info)
        
        # 为每个关键场景生成图像
        for i, keyword in enumerate(scene_keywords[:4]):  # 最多4个场景
            scene_prompt = f"""【梦境可视化 · {style_info['name']}】
原始梦境内容：{dream_text[:200]}
心愿：{wish}
当前场景元素：{keyword}
视觉风格：{style_info['color_palette']}
氛围：{style_info['atmosphere']}
光影：{style_info['lighting']}
许墨形象：{style_info['xumo_appearance']}

请生成一张梦境场景插画：
- 体现"{style_info['name']}"的独特意境
- 许墨以{style_info['xumo_appearance']}的形象自然存在
- 色调要符合{style_info['color_palette']}
- 画面要有梦幻感和超现实感
- 加入{style_info['effects']}等视觉元素
- 低饱和度紫调为主，保持许墨风格的克制美学
- 画面构图要有电影感和故事性"""

            try:
                img_url, img_prompt = await _llm_image_for_text(
                    scene_prompt,
                    DREAM_VIDEO_DIR,
                    "/static/dream_video",
                    f"dream_{dream.get('id')}_{i}",
                    "2048x1536",  # landscape
                    with_xumo=True,
                    has_character=True
                )
                
                if img_url:
                    scenes.append({
                        "id": f"{dream.get('id')}_scene_{i}",
                        "keyword": keyword,
                        "image_url": img_url + f"?t={int(datetime.now().timestamp())}",
                        "image_prompt": img_prompt,
                        "duration": 10,  # 每个场景10秒
                        "transition": "fade"  # 默认淡入淡出
                    })
            except Exception as e:
                print(f"[warn] failed to generate dream scene {i}: {type(e).__name__}", flush=True)
                continue
        
        return scenes
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_dream_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []


async def _extract_dream_scenes(dream_text: str, style_info: dict) -> list:
    """从梦境文本中提取关键场景元素"""
    try:
        extract_prompt = f"""你是许墨，擅长解析梦境意象。
基于以下梦境文本，提取3-4个关键场景元素（每个不超过8字）：

梦境文本：{dream_text[:500]}
梦境风格：{style_info['name']}

请提取最能代表这个梦境的视觉元素，如：
- 具体场景（如"星空下的长椅"）
- 重要物品（如"发光的蝴蝶"）
- 关键动作（如"伸手摘星"）
- 情感意象（如"温暖的拥抱"）

只返回JSON数组：["元素1", "元素2", "元素3"]"""

        response = await _llm_json([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": extract_prompt}
        ], max_tokens=200)
        
        if isinstance(response, dict) and "_raw" in response:
            # 尝试从_raw中提取数组
            array_match = re.search(r'\[.*?\]', response["_raw"], re.S)
            if array_match:
                try:
                    return json.loads(array_match.group(0))
                except:
                    pass
        
        # 默认场景元素
        default_scenes = [
            f"{style_info['name']}的开端",
            f"梦境中的{style_info['xumo_appearance']}",
            "情感交汇的瞬间",
            f"{style_info['name']}的尾声"
        ]
        
        return default_scenes
    except Exception as e:
        print(f"[warn] video_apps.py:_extract_dream_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return ["梦境开端", "关键瞬间", "情感交汇", "梦境尾声"]


# ===========================================================================
# 3. 记忆回放剧场 - 将记忆手账转化为许墨旁白的视频故事
# ===========================================================================
MEMORY_THEATER_FILE = RolePath("memory_theater.json")
MEMORY_THEATER_DIR = RolePath("static", "memory_theater")

# 记忆剧场主题风格
MEMORY_THEATER_THEMES = {
    "nostalgic": {
        "name": "怀旧温馨",
        "color_palette": "暖黄+柔棕",
        "transition": "缓慢淡入淡出",
        "music_style": "柔和钢琴",
        "narration_tone": "温柔怀念"
    },
    "vibrant": {
        "name": "活力青春", 
        "color_palette": "明亮多彩",
        "transition": "动态切换",
        "music_style": "轻快节奏",
        "narration_tone": "充满活力"
    },
    "romantic": {
        "name": "浪漫诗意",
        "color_palette": "粉紫+柔光",
        "transition": "柔光过渡",
        "music_style": "浪漫弦乐",
        "narration_tone": "深情浪漫"
    },
    "peaceful": {
        "name": "宁静致远",
        "color_palette": "青绿+白",
        "transition": "平滑流动",
        "music_style": "自然音效",
        "narration_tone": "平和沉思"
    }
}


@router.get("/memory/theater/list")
async def memory_theater_list():
    """获取记忆剧场列表"""
    try:
        data = _load(MEMORY_THEATER_FILE, {"theaters": []})
        return {"theaters": list(reversed(data.get("theaters", [])[-15:]))}
    except Exception as e:
        print(f"[warn] video_apps.py:memory_theater_list: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取记忆剧场列表失败"}, status_code=500)


@router.post("/memory/theater/create")
async def memory_theater_create(req: Request):
    """创建新的记忆剧场"""
    try:
        body = await req.json()
        memory_ids = body.get("memory_ids", [])
        theme = body.get("theme", "nostalgic")
        title = body.get("title", "").strip()
        
        if not memory_ids:
            return JSONResponse({"error": "请选择至少一条记忆"}, status_code=400)
        
        if theme not in MEMORY_THEATER_THEMES:
            theme = "nostalgic"
        
        # 获取记忆内容
        from app import _load_memories
        all_memories = _load_memories()
        selected_memories = [m for m in all_memories if m.get("id") in memory_ids]
        
        if not selected_memories:
            return JSONResponse({"error": "未找到选择的记忆"}, status_code=404)
        
        # 生成标题（如果未提供）
        if not title:
            title = f"记忆回放 · {_now()}"
        
        # 创建剧场记录
        theater_id = _uid()
        theater_record = {
            "id": theater_id,
            "title": title,
            "theme": theme,
            "theme_info": MEMORY_THEATER_THEMES[theme],
            "memory_ids": memory_ids,
            "memories_summary": [
                {
                    "id": m.get("id"),
                    "content": m.get("content", "")[:50],
                    "tag": m.get("tag", ""),
                    "ts": m.get("ts", "")
                } for m in selected_memories
            ],
            "narration": "",
            "scenes": [],
            "video_url": "",
            "thumbnail": "",
            "duration": 0,
            "status": "pending",
            "created_at": _stamp()
        }
        
        # 保存记录
        data = _load(MEMORY_THEATER_FILE, {"theaters": []})
        data.setdefault("theaters", []).append(theater_record)
        data["theaters"] = data["theaters"][-20:]  # 保留最近20条
        _save(MEMORY_THEATER_FILE, data)
        
        # 增加亲和度
        _add_affinity("memory_theater", f"记忆剧场：{title}")
        
        return theater_record
    except Exception as e:
        print(f"[warn] video_apps.py:memory_theater_create: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"创建记忆剧场失败: {str(e)[:100]}"}, status_code=500)


@router.post("/memory/theater/{theater_id}/generate")
async def memory_theater_generate(theater_id: str):
    """生成记忆剧场视频"""
    try:
        # 检查剧场记录
        data = _load(MEMORY_THEATER_FILE, {"theaters": []})
        theater = next((t for t in data.get("theaters", []) if t.get("id") == theater_id), None)
        
        if not theater:
            return JSONResponse({"error": "剧场记录不存在"}, status_code=404)
        
        if theater.get("status") == "processing":
            return {"status": "already_processing", "message": "视频生成中"}
        
        if theater.get("status") == "completed":
            return {"status": "already_completed", "message": "视频已生成"}
        
        # 启动后台生成任务
        task = asyncio.create_task(_generate_memory_theater_task(theater_id, theater))
        task.add_done_callback(_on_video_task_done)
        _background_video_tasks.add(task)
        
        return {"status": "started", "message": "记忆剧场生成任务已启动"}
    except Exception as e:
        print(f"[warn] video_apps.py:memory_theater_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"启动生成失败: {str(e)[:100]}"}, status_code=500)


@router.get("/memory/theater/{theater_id}")
async def memory_theater_status(theater_id: str):
    """获取记忆剧场状态"""
    try:
        data = _load(MEMORY_THEATER_FILE, {"theaters": []})
        theater = next((t for t in data.get("theaters", []) if t.get("id") == theater_id), None)
        
        if not theater:
            return JSONResponse({"error": "剧场记录不存在"}, status_code=404)
        
        return theater
    except Exception as e:
        print(f"[warn] video_apps.py:memory_theater_status: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取状态失败"}, status_code=500)


async def _generate_memory_theater_task(theater_id: str, theater: dict):
    """后台任务：生成记忆剧场视频"""
    try:
        # 更新状态为处理中
        async with _growth_video_lock:
            data = _load(MEMORY_THEATER_FILE, {"theaters": []})
            for t in data.get("theaters", []):
                if t.get("id") == theater_id:
                    t["status"] = "processing"
                    t["started_at"] = _stamp()
                    break
            _save(MEMORY_THEATER_FILE, data)
        
        # 生成许墨旁白
        print(f"[video] generating narration for theater {theater_id}", flush=True)
        narration = await _generate_memory_narration(theater)
        
        # 生成场景图像
        print(f"[video] generating scenes for theater {theater_id}", flush=True)
        scenes = await _generate_memory_scenes(theater)
        
        if not scenes:
            raise Exception("场景生成失败")
        
        # 计算总时长
        total_duration = sum(scene.get("duration", 8) for scene in scenes)
        
        # 更新为完成状态
        async with _growth_video_lock:
            data = _load(MEMORY_THEATER_FILE, {"theaters": []})
            for t in data.get("theaters", []):
                if t.get("id") == theater_id:
                    t["status"] = "completed"
                    t["completed_at"] = _stamp()
                    t["narration"] = narration
                    t["scenes"] = scenes
                    t["duration"] = total_duration
                    t["thumbnail"] = scenes[0].get("image_url", "") if scenes else ""
                    break
            _save(MEMORY_THEATER_FILE, data)
        
        print(f"[video] memory theater {theater_id} completed", flush=True)
        
    except Exception as e:
        print(f"[error] memory theater task for {theater_id} failed: {type(e).__name__} {str(e)[:200]}", flush=True)
        
        # 更新状态为失败
        async with _growth_video_lock:
            data = _load(MEMORY_THEATER_FILE, {"theaters": []})
            for t in data.get("theaters", []):
                if t.get("id") == theater_id:
                    t["status"] = "failed"
                    t["error"] = str(e)[:200]
                    t["failed_at"] = _stamp()
                    break
            _save(MEMORY_THEATER_FILE, data)


async def _generate_memory_narration(theater: dict) -> str:
    """生成记忆回放的许墨旁白"""
    try:
        memories = theater.get("memories_summary", [])
        theme = theater.get("theme", "nostalgic")
        theme_info = MEMORY_THEATER_THEMES.get(theme, MEMORY_THEATER_THEMES["nostalgic"])
        
        # 构建记忆摘要
        memory_texts = []
        for mem in memories:
            tag = mem.get("tag", "")
            content = mem.get("content", "")
            ts = mem.get("ts", "")
            memory_texts.append(f"【{tag}】{content}（{ts[:10]}）")
        
        memories_summary = "\n".join(memory_texts)
        
        narration_prompt = f"""你是许墨，正在回顾与她共同的记忆。

【记忆回放剧场】
主题风格：{theme_info['name']}
旁白基调：{theme_info['narration_tone']}

【记忆内容】
{memories_summary}

请以许墨的口吻，为这段记忆回写一段旁白（200-350字）：
1. 语气{theme_info['narration_tone']}，体现学者气质
2. 将这些记忆串联成一个完整的故事
3. 展现你对每段记忆的感受和思考
4. 保持学术式的浪漫表达
5. 话留三分，恰到好处的留白
6. 直接输出旁白正文，不要标题、引号、markdown标记"""

        narration = await _call_llm([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": narration_prompt}
        ], max_tokens=600)
        
        return narration.strip() if narration else "这些记忆，都是我们共同的时光。"
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_memory_narration: {type(e).__name__} {str(e)[:150]}", flush=True)
        return "这些记忆，都是我们共同的时光，值得珍藏。"


async def _generate_memory_scenes(theater: dict) -> list:
    """为记忆剧场生成场景图像"""
    try:
        scenes = []
        memories = theater.get("memories_summary", [])
        theme = theater.get("theme", "nostalgic")
        theme_info = MEMORY_THEATER_THEMES.get(theme, MEMORY_THEATER_THEMES["nostalgic"])
        
        # 为每条记忆生成对应场景
        for i, mem in enumerate(memories[:5]):  # 最多5个场景
            content = mem.get("content", "")
            tag = mem.get("tag", "")
            ts = mem.get("ts", "")
            
            scene_prompt = f"""【记忆回放剧场 · {theme_info['name']}】
记忆内容：{content}
记忆标签：{tag}
记忆时间：{ts}
主题风格：{theme_info['name']}
色调：{theme_info['color_palette']}
旁白基调：{theme_info['narration_tone']}

请生成一张能代表这段记忆的氛围场景插画：
- 体现"{tag}"类型的记忆特点
- 许墨在场景中自然存在，符合{theme_info['narration_tone']}的气质
- 色调要符合{theme_info['color_palette']}
- 画面要有{theme_info['name']}的感觉
- 低饱和度紫调为主，保持许墨风格的克制美学
- 画面构图要有电影感和故事性
- 时间设定要符合记忆时间{ts[:10]}的氛围"""

            try:
                img_url, img_prompt = await _llm_image_for_text(
                    scene_prompt,
                    MEMORY_THEATER_DIR,
                    "/static/memory_theater",
                    f"memory_{theater.get('id')}_{i}",
                    "2048x1536",  # landscape
                    with_xumo=True,
                    has_character=True
                )
                
                if img_url:
                    scenes.append({
                        "id": f"{theater.get('id')}_scene_{i}",
                        "memory_id": mem.get("id"),
                        "memory_content": content[:30],
                        "image_url": img_url + f"?t={int(datetime.now().timestamp())}",
                        "image_prompt": img_prompt,
                        "duration": 8,  # 每个场景8秒
                        "transition": theme_info.get("transition", "fade")
                    })
            except Exception as e:
                print(f"[warn] failed to generate memory scene {i}: {type(e).__name__}", flush=True)
                continue
        
        return scenes
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_memory_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []


# ===========================================================================
# 4. 时空旅行日记 - 结合逆向时光机，生成许墨在不同时空的视频日记
# ===========================================================================
TIME_TRAVEL_FILE = RolePath("time_travel.json")
TIME_TRAVEL_DIR = RolePath("static", "time_travel")

# 时空形象设计
TIME_TRAVEL_PROFILES = {
    "future_5": {
        "name": "5年后",
        "target_year_offset": 5,
        "xumo_age": "31岁",
        "appearance": "稍显成熟的银丝，更深邃的眼眸",
        "clothing": "更正式的教授装束，偶尔出现实验服",
        "environment": "更先进的实验室，充满未来感的办公室",
        "voice_tone": "更沉稳，带着阅历的温柔",
        "atmosphere": "学术氛围浓厚，科技感与人文并存"
    },
    "future_10": {
        "name": "10年后",
        "target_year_offset": 10,
        "xumo_age": "36岁", 
        "appearance": "明显的成熟气质，眼角有细纹但更有魅力",
        "clothing": "优雅的长风衣，经典配色",
        "environment": "窗外的城市景观明显变化，室内布置更简洁",
        "voice_tone": "极具磁性，充满包容感",
        "atmosphere": "成熟稳重，岁月沉淀的智慧"
    },
    "future_20": {
        "name": "20年后",
        "target_year_offset": 20,
        "xumo_age": "46岁",
        "appearance": "儒雅长者，银发但气质依然温和",
        "clothing": "经典的学术装束，简约而优雅",
        "environment": "充满书籍的研究室，窗外是变化巨大的城市",
        "voice_tone": "温和而充满智慧，如长者般亲切",
        "atmosphere": "智者风范，时间沉淀的深度"
    },
    "past": {
        "name": "学生时代",
        "target_year_offset": -8,
        "xumo_age": "18岁",
        "appearance": "更年轻青涩，但眼神已有超越年龄的深度",
        "clothing": "简单的白衬衫，学生装的简洁感",
        "environment": "恋语大学的旧校园，图书馆，实验室",
        "voice_tone": "清亮中带着早熟的稳重",
        "atmosphere": "青春年华，求知若渴的纯粹"
    }
}


@router.get("/time/travel/list")
async def time_travel_list():
    """获取时空旅行日记列表"""
    try:
        data = _load(TIME_TRAVEL_FILE, {"diaries": []})
        return {"diaries": list(reversed(data.get("diaries", [])[-15:]))}
    except Exception as e:
        print(f"[warn] video_apps.py:time_travel_list: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取时空日记列表失败"}, status_code=500)


@router.post("/time/travel/create")
async def time_travel_create(req: Request):
    """创建时空旅行日记"""
    try:
        body = await req.json()
        rtm_id = body.get("rtm_id", "")  # 关联的逆向时光机记录ID
        time_point = body.get("time_point", "future_5")  # 时空点
        custom_year = body.get("custom_year")  # 自定义年份
        
        if time_point not in TIME_TRAVEL_PROFILES and not custom_year:
            return JSONResponse({"error": "请选择有效的时空点或自定义年份"}, status_code=400)
        
        # 如果使用自定义年份，创建临时profile
        if custom_year:
            current_year = datetime.now().year
            year_offset = custom_year - current_year
            time_point = f"custom_{custom_year}"
            profile = {
                "name": f"{custom_year}年",
                "target_year_offset": year_offset,
                "xumo_age": f"{26 + year_offset}岁",
                "appearance": "符合该年龄阶段的自然变化",
                "clothing": "符合该时代的服装风格",
                "environment": f"{custom_year}年的环境",
                "voice_tone": "符合该年龄的音色特点",
                "atmosphere": f"{custom_year}年的时代氛围"
            }
        else:
            profile = TIME_TRAVEL_PROFILES[time_point]
        
        # 如果提供了rtm_id，获取对应的时光机记录
        today_text = ""
        if rtm_id:
            try:
                from disrupt_apps import RolePath as DisruptRolePath, _load as disrupt_load
                rtm_file = DisruptRolePath("disrupt_rtm.json")
                rtm_data = disrupt_load(rtm_file, {"items": []})
                rtm_record = next((item for item in rtm_data.get("items", []) if item.get("id") == rtm_id), None)
                if rtm_record:
                    today_text = rtm_record.get("today_input", "")
            except Exception as e:
                print(f"[warn] failed to load rtm record: {type(e).__name__}", flush=True)
        
        # 创建日记记录
        diary_id = _uid()
        diary_record = {
            "id": diary_id,
            "rtm_id": rtm_id,
            "time_point": time_point,
            "profile": profile,
            "today_text": today_text,
            "diary_content": "",
            "video_url": "",
            "thumbnail": "",
            "scenes": [],
            "duration": 0,
            "status": "pending",
            "created_at": _stamp()
        }
        
        # 保存记录
        data = _load(TIME_TRAVEL_FILE, {"diaries": []})
        data.setdefault("diaries", []).append(diary_record)
        data["diaries"] = data["diaries"][-20:]  # 保留最近20条
        _save(TIME_TRAVEL_FILE, data)
        
        return diary_record
    except Exception as e:
        print(f"[warn] video_apps.py:time_travel_create: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"创建时空日记失败: {str(e)[:100]}"}, status_code=500)


@router.post("/time/travel/{diary_id}/generate")
async def time_travel_generate(diary_id: str):
    """生成时空旅行日记视频"""
    try:
        # 检查日记记录
        data = _load(TIME_TRAVEL_FILE, {"diaries": []})
        diary = next((d for d in data.get("diaries", []) if d.get("id") == diary_id), None)
        
        if not diary:
            return JSONResponse({"error": "日记记录不存在"}, status_code=404)
        
        if diary.get("status") == "processing":
            return {"status": "already_processing", "message": "视频生成中"}
        
        if diary.get("status") == "completed":
            return {"status": "already_completed", "message": "视频已生成"}
        
        # 启动后台生成任务
        task = asyncio.create_task(_generate_time_travel_task(diary_id, diary))
        task.add_done_callback(_on_video_task_done)
        _background_video_tasks.add(task)
        
        return {"status": "started", "message": "时空日记生成任务已启动"}
    except Exception as e:
        print(f"[warn] video_apps.py:time_travel_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"启动生成失败: {str(e)[:100]}"}, status_code=500)


@router.get("/time/travel/{diary_id}")
async def time_travel_status(diary_id: str):
    """获取时空旅行日记状态"""
    try:
        data = _load(TIME_TRAVEL_FILE, {"diaries": []})
        diary = next((d for d in data.get("diaries", []) if d.get("id") == diary_id), None)
        
        if not diary:
            return JSONResponse({"error": "日记记录不存在"}, status_code=404)
        
        return diary
    except Exception as e:
        print(f"[warn] video_apps.py:time_travel_status: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取状态失败"}, status_code=500)


async def _generate_time_travel_task(diary_id: str, diary: dict):
    """后台任务：生成时空旅行日记视频"""
    try:
        # 更新状态为处理中
        async with _growth_video_lock:
            data = _load(TIME_TRAVEL_FILE, {"diaries": []})
            for d in data.get("diaries", []):
                if d.get("id") == diary_id:
                    d["status"] = "processing"
                    d["started_at"] = _stamp()
                    break
            _save(TIME_TRAVEL_FILE, data)
        
        # 生成许墨日记内容
        print(f"[video] generating diary content for {diary_id}", flush=True)
        diary_content = await _generate_time_diary_content(diary)
        
        # 生成时空场景
        print(f"[video] generating time travel scenes for {diary_id}", flush=True)
        scenes = await _generate_time_travel_scenes(diary)
        
        if not scenes:
            raise Exception("场景生成失败")
        
        # 计算总时长
        total_duration = sum(scene.get("duration", 10) for scene in scenes)
        
        # 更新为完成状态
        async with _growth_video_lock:
            data = _load(TIME_TRAVEL_FILE, {"diaries": []})
            for d in data.get("diaries", []):
                if d.get("id") == diary_id:
                    d["status"] = "completed"
                    d["completed_at"] = _stamp()
                    d["diary_content"] = diary_content
                    d["scenes"] = scenes
                    d["duration"] = total_duration
                    d["thumbnail"] = scenes[0].get("image_url", "") if scenes else ""
                    break
            _save(TIME_TRAVEL_FILE, data)
        
        print(f"[video] time travel diary {diary_id} completed", flush=True)
        
    except Exception as e:
        print(f"[error] time travel task for {diary_id} failed: {type(e).__name__} {str(e)[:200]}", flush=True)
        
        # 更新状态为失败
        async with _growth_video_lock:
            data = _load(TIME_TRAVEL_FILE, {"diaries": []})
            for d in data.get("diaries", []):
                if d.get("id") == diary_id:
                    d["status"] = "failed"
                    d["error"] = str(e)[:200]
                    d["failed_at"] = _stamp()
                    break
            _save(TIME_TRAVEL_FILE, data)


async def _generate_time_diary_content(diary: dict) -> str:
    """生成时空旅行日记内容"""
    try:
        profile = diary.get("profile", {})
        today_text = diary.get("today_text", "")
        time_point = diary.get("time_point", "")
        
        target_year = datetime.now().year + profile.get("target_year_offset", 0)
        
        diary_prompt = f"""你是许墨，现在身处{target_year}年。
年龄：{profile.get('xumo_age', '26岁')}
形象：{profile.get('appearance', '')}
环境：{profile.get('environment', '')}
语气：{profile.get('voice_tone', '')}

【今日回望】
你在回看今天的记录：{today_text if today_text else "（未提供具体记录）"}

请以{target_year}年许墨的口吻，写一篇日记（250-400字）：
1. 站在{target_year}年回望今天，谈谈你对这段时光的感受
2. 体现{profile.get('voice_tone', '')}的语气特点
3. 展现岁月或成长带来的变化
4. 保持学术式的浪漫表达
5. 话留三分，恰到好处的留白
6. 直接输出日记正文，不要标题、日期、markdown标记"""

        diary_content = await _call_llm([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": diary_prompt}
        ], max_tokens=700)
        
        return diary_content.strip() if diary_content else f"站在{target_year}年回望，那段时光依然清晰。"
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_time_diary_content: {type(e).__name__} {str(e)[:150]}", flush=True)
        return "时光流转，回首往事，一切都值得珍藏。"


async def _generate_time_travel_scenes(diary: dict) -> list:
    """为时空旅行日记生成场景图像"""
    try:
        scenes = []
        profile = diary.get("profile", {})
        diary_content = diary.get("diary_content", "")
        time_point = diary.get("time_point", "")
        
        # 根据日记内容提取关键场景
        scene_keywords = await _extract_time_scenes(diary_content, profile)
        
        # 为每个关键场景生成图像
        for i, keyword in enumerate(scene_keywords[:3]):  # 最多3个场景
            scene_prompt = f"""【时空旅行日记 · {profile.get('name', '')}】
日记内容：{diary_content[:200]}
当前场景：{keyword}
许墨形象：{profile.get('appearance', '')}
服装：{profile.get('clothing', '')}
环境：{profile.get('environment', '')}
氛围：{profile.get('atmosphere', '')}
目标年份：{datetime.now().year + profile.get('target_year_offset', 0)}

请生成一张时空场景插画：
- 体现{profile.get('name', '')}的时代特色
- 许墨以{profile.get('appearance', '')}的形象出现
- 穿着{profile.get('clothing', '')}
- 背景是{profile.get('environment', '')}
- 整体氛围要{profile.get('atmosphere', '')}
- 画面要有时代感和电影感
- 低饱和度紫调为主，保持许墨风格的克制美学
- 体现时间流逝带来的变化"""

            try:
                img_url, img_prompt = await _llm_image_for_text(
                    scene_prompt,
                    TIME_TRAVEL_DIR,
                    "/static/time_travel",
                    f"time_{diary.get('id')}_{i}",
                    "2048x1536",  # landscape
                    with_xumo=True,
                    has_character=True
                )
                
                if img_url:
                    scenes.append({
                        "id": f"{diary.get('id')}_scene_{i}",
                        "keyword": keyword,
                        "image_url": img_url + f"?t={int(datetime.now().timestamp())}",
                        "image_prompt": img_prompt,
                        "duration": 12,  # 每个场景12秒
                        "transition": "fade"  # 时空穿越用淡入淡出
                    })
            except Exception as e:
                print(f"[warn] failed to generate time scene {i}: {type(e).__name__}", flush=True)
                continue
        
        return scenes
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_time_travel_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []


async def _extract_time_scenes(diary_content: str, profile: dict) -> list:
    """从日记内容中提取关键场景"""
    try:
        extract_prompt = f"""你是许墨，擅长从文字中提取视觉意象。
基于以下日记内容，提取2-3个关键场景元素（每个不超过10字）：

日记内容：{diary_content[:400]}
时代背景：{profile.get('name', '')}

请提取最能代表这个时空的视觉元素，如：
- 具体场景（如"未来的实验室"）
- 重要物品（如"旧照片"）
- 情感意象（如"时光荏苒"）

只返回JSON数组：["元素1", "元素2"]"""

        response = await _llm_json([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": extract_prompt}
        ], max_tokens=200)
        
        if isinstance(response, dict) and "_raw" in response:
            # 尝试从_raw中提取数组
            array_match = re.search(r'\[.*?\]', response["_raw"], re.S)
            if array_match:
                try:
                    return json.loads(array_match.group(0))
                except:
                    pass
        
        # 默认场景元素
        default_scenes = [
            f"{profile.get('environment', '')}",
            "时光回望的瞬间",
            "跨越时空的思念"
        ]
        
        return default_scenes
    except Exception as e:
        print(f"[warn] video_apps.py:_extract_time_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return ["时空场景", "回望瞬间", "永恒思念"]


# ===========================================================================
# 5. 共同时刻相册 - 用户照片与许墨角色合成，生成互动视频相册
# ===========================================================================
SHARED_ALBUM_FILE = RolePath("shared_album.json")
SHARED_ALBUM_DIR = RolePath("static", "shared_album")

# 照片合成模式
PHOTO_COMPOSITION_MODES = {
    "side_by_side": {
        "name": "并肩站立",
        "description": "许墨自然地站在用户身旁",
        "xumo_position": "用户身旁自然位置",
        "interaction": "手臂轻触，温和注视",
        "distance": "亲密距离"
    },
    "background_presence": {
        "name": "背景守护",
        "description": "许墨在背景中温柔存在",
        "xumo_position": "画面远处或侧面",
        "interaction": "默默守护的感觉",
        "distance": "适度距离"
    },
    "intimate_close": {
        "name": "亲密时刻",
        "description": "近距离的亲密互动",
        "xumo_position": "近距离，如面对面",
        "interaction": "温柔对视，伸手姿态",
        "distance": "亲密距离"
    },
    "activity_join": {
        "name": "共同参与",
        "description": "一起参与某项活动",
        "xumo_position": "根据场景自然融入",
        "interaction": "一起做某事的姿态",
        "distance": "自然距离"
    }
}


@router.get("/shared/album/list")
async def shared_album_list():
    """获取共同时刻相册列表"""
    try:
        data = _load(SHARED_ALBUM_FILE, {"albums": []})
        return {"albums": list(reversed(data.get("albums", [])[-15:]))}
    except Exception as e:
        print(f"[warn] video_apps.py:shared_album_list: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取相册列表失败"}, status_code=500)


@router.post("/shared/album/create")
async def shared_album_create(req: Request):
    """创建新的共同时刻相册"""
    try:
        body = await req.json()
        title = body.get("title", "").strip()
        composition_mode = body.get("composition_mode", "side_by_side")
        theme = body.get("theme", "warm_daily")
        
        if not title:
            return JSONResponse({"error": "请输入相册标题"}, status_code=400)
        
        if composition_mode not in PHOTO_COMPOSITION_MODES:
            composition_mode = "side_by_side"
        
        # 创建相册记录
        album_id = _uid()
        album_record = {
            "id": album_id,
            "title": title,
            "composition_mode": composition_mode,
            "composition_info": PHOTO_COMPOSITION_MODES[composition_mode],
            "theme": theme,
            "photos": [],  # 将在添加照片时填充
            "narration_script": "",
            "video_url": "",
            "thumbnail": "",
            "duration": 0,
            "status": "created",  # created/processing/completed/failed
            "created_at": _stamp()
        }
        
        # 保存记录
        data = _load(SHARED_ALBUM_FILE, {"albums": []})
        data.setdefault("albums", []).append(album_record)
        data["albums"] = data["albums"][-20:]  # 保留最近20条
        _save(SHARED_ALBUM_FILE, data)
        
        return album_record
    except Exception as e:
        print(f"[warn] video_apps.py:shared_album_create: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"创建相册失败: {str(e)[:100]}"}, status_code=500)


@router.post("/shared/album/{album_id}/add-photo")
async def shared_album_add_photo(album_id: str, req: Request):
    """向相册添加照片"""
    try:
        # 检查相册是否存在
        data = _load(SHARED_ALBUM_FILE, {"albums": []})
        album = next((a for a in data.get("albums", []) if a.get("id") == album_id), None)
        
        if not album:
            return JSONResponse({"error": "相册不存在"}, status_code=404)
        
        # 处理照片上传（简化版本：假设前端提供照片URL）
        body = await req.json()
        photo_url = body.get("photo_url", "").strip()
        caption = body.get("caption", "").strip()
        
        if not photo_url:
            return JSONResponse({"error": "请提供照片URL"}, status_code=400)
        
        # 生成合成后的照片（简化版本：先保存原始信息）
        photo_id = _uid()
        photo_record = {
            "id": photo_id,
            "original_url": photo_url,
            "composite_url": "",  # 合成后填充
            "caption": caption,
            "composition_mode": album.get("composition_mode"),
            "composition_result": "",
            "added_at": _stamp()
        }
        
        # 添加到相册
        album.setdefault("photos", []).append(photo_record)
        _save(SHARED_ALBUM_FILE, data)
        
        return photo_record
    except Exception as e:
        print(f"[warn] video_apps.py:shared_album_add_photo: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"添加照片失败: {str(e)[:100]}"}, status_code=500)


@router.post("/shared/album/{album_id}/generate")
async def shared_album_generate(album_id: str):
    """生成共同时刻相册视频"""
    try:
        # 检查相册记录
        data = _load(SHARED_ALBUM_FILE, {"albums": []})
        album = next((a for a in data.get("albums", []) if a.get("id") == album_id), None)
        
        if not album:
            return JSONResponse({"error": "相册不存在"}, status_code=404)
        
        if not album.get("photos"):
            return JSONResponse({"error": "请先添加照片到相册"}, status_code=400)
        
        if album.get("status") == "processing":
            return {"status": "already_processing", "message": "视频生成中"}
        
        if album.get("status") == "completed":
            return {"status": "already_completed", "message": "视频已生成"}
        
        # 启动后台生成任务
        task = asyncio.create_task(_generate_shared_album_task(album_id, album))
        task.add_done_callback(_on_video_task_done)
        _background_video_tasks.add(task)
        
        return {"status": "started", "message": "相册视频生成任务已启动"}
    except Exception as e:
        print(f"[warn] video_apps.py:shared_album_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"启动生成失败: {str(e)[:100]}"}, status_code=500)


@router.get("/shared/album/{album_id}")
async def shared_album_status(album_id: str):
    """获取共同时刻相册状态"""
    try:
        data = _load(SHARED_ALBUM_FILE, {"albums": []})
        album = next((a for a in data.get("albums", []) if a.get("id") == album_id), None)
        
        if not album:
            return JSONResponse({"error": "相册不存在"}, status_code=404)
        
        return album
    except Exception as e:
        print(f"[warn] video_apps.py:shared_album_status: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取状态失败"}, status_code=500)


async def _generate_shared_album_task(album_id: str, album: dict):
    """后台任务：生成共同时刻相册视频"""
    try:
        # 更新状态为处理中
        async with _growth_video_lock:
            data = _load(SHARED_ALBUM_FILE, {"albums": []})
            for a in data.get("albums", []):
                if a.get("id") == album_id:
                    a["status"] = "processing"
                    a["started_at"] = _stamp()
                    break
            _save(SHARED_ALBUM_FILE, data)
        
        # 生成相册叙述脚本
        print(f"[video] generating narration for album {album_id}", flush=True)
        narration = await _generate_album_narration(album)
        
        # 为每张照片生成合成效果
        print(f"[video] generating photo compositions for album {album_id}", flush=True)
        composite_photos = await _generate_album_composites(album)
        
        if not composite_photos:
            raise Exception("照片合成失败")
        
        # 计算总时长
        total_duration = len(composite_photos) * 6  # 每张照片6秒
        
        # 更新为完成状态
        async with _growth_video_lock:
            data = _load(SHARED_ALBUM_FILE, {"albums": []})
            for a in data.get("albums", []):
                if a.get("id") == album_id:
                    a["status"] = "completed"
                    a["completed_at"] = _stamp()
                    a["narration_script"] = narration
                    a["photos"] = composite_photos
                    a["duration"] = total_duration
                    a["thumbnail"] = composite_photos[0].get("composite_url", "") if composite_photos else ""
                    break
            _save(SHARED_ALBUM_FILE, data)
        
        print(f"[video] shared album {album_id} completed", flush=True)
        
    except Exception as e:
        print(f"[error] shared album task for {album_id} failed: {type(e).__name__} {str(e)[:200]}", flush=True)
        
        # 更新状态为失败
        async with _growth_video_lock:
            data = _load(SHARED_ALBUM_FILE, {"albums": []})
            for a in data.get("albums", []):
                if a.get("id") == album_id:
                    a["status"] = "failed"
                    a["error"] = str(e)[:200]
                    a["failed_at"] = _stamp()
                    break
            _save(SHARED_ALBUM_FILE, data)


async def _generate_album_narration(album: dict) -> str:
    """生成相册的许墨叙述脚本"""
    try:
        photos = album.get("photos", [])
        title = album.get("title", "")
        composition_mode = album.get("composition_mode", "side_by_side")
        composition_info = PHOTO_COMPOSITION_MODES.get(composition_mode, PHOTO_COMPOSITION_MODES["side_by_side"])
        
        # 构建照片摘要
        photo_summaries = []
        for photo in photos[:5]:  # 最多5张
            caption = photo.get("caption", "")
            if caption:
                photo_summaries.append(f"照片描述：{caption}")
        
        photos_summary = "\n".join(photo_summaries) if photo_summaries else "我们的美好瞬间"
        
        narration_prompt = f"""你是许墨，正在回顾与她共同的相册。

【共同时刻相册】
相册标题：{title}
合成模式：{composition_info['name']}
互动方式：{composition_info['interaction']}

【照片内容】
{photos_summary}

请以许墨的口吻，为这个相册写一段回顾叙述（200-350字）：
1. 温和而不失深情，体现学者气质
2. 描述这些共同时刻对你的意义
3. 体现{composition_info['interaction']}的亲密感
4. 保持学术式的浪漫表达
5. 话留三分，恰到好处的留白
6. 直接输出叙述正文，不要标题、引号、markdown标记"""

        narration = await _call_llm([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": narration_prompt}
        ], max_tokens=600)
        
        return narration.strip() if narration else "这些照片记录了我们的共同时刻，每一帧都值得珍藏。"
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_album_narration: {type(e).__name__} {str(e)[:150]}", flush=True)
        return "这些照片记录了我们的共同时刻，每一帧都值得珍藏。"


async def _generate_album_composites(album: dict) -> list:
    """为相册照片生成合成效果（简化版本）"""
    try:
        composite_photos = []
        photos = album.get("photos", [])
        composition_mode = album.get("composition_mode", "side_by_side")
        composition_info = PHOTO_COMPOSITION_MODES.get(composition_mode, PHOTO_COMPOSITION_MODES["side_by_side"])
        
        for i, photo in enumerate(photos):
            # 简化版本：直接使用原始照片，标记合成信息
            # 实际版本需要使用图像合成技术（如ControlNet、Inpainting）
            
            composite_photo = {
                "id": photo.get("id"),
                "original_url": photo.get("original_url", ""),
                "composite_url": photo.get("original_url", ""),  # 暂时使用原图
                "caption": photo.get("caption", ""),
                "composition_mode": composition_mode,
                "xumo_action": composition_info.get("interaction", ""),
                "xumo_position": composition_info.get("xumo_position", ""),
                "duration": 6,
                "transition": "fade"
            }
            
            composite_photos.append(composite_photo)
        
        return composite_photos
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_album_composites: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []


# ===========================================================================
# 6. 虚拟约会场景生成 - 支持高度互动的虚拟约会视频体验
# ===========================================================================
VIRTUAL_DATE_FILE = RolePath("virtual_date.json")
VIRTUAL_DATE_DIR = RolePath("static", "virtual_date")

# 约会场景设计
VIRTUAL_DATE_SCENES = {
    "cafe": {
        "name": "静谧咖啡厅",
        "environment": "温暖灯光的咖啡厅，窗外有街景",
        "xumo_outfit": "休闲西装，脱下外套搭在椅背上",
        "activities": ["共饮咖啡", "讨论学术", "安静陪伴", "窗边谈话"],
        "atmosphere": "安静温馨，适合深入交谈",
        "lighting": "暖黄灯光，温馨舒适",
        "background_elements": ["咖啡杯", "书本", "窗景", "柔和音乐"]
    },
    "park": {
        "name": "黄昏公园",
        "environment": "夕阳下的公园长椅，落叶飘零",
        "xumo_outfit": "风衣，围巾，秋日装扮",
        "activities": ["散步", "坐在长椅上", "看风景", "讨论人生"],
        "atmosphere": "浪漫诗意，适合情感交流",
        "lighting": "夕阳余晖，金黄暖调",
        "background_elements": ["长椅", "落叶", "夕阳", "远山"]
    },
    "library": {
        "name": "深夜图书馆",
        "environment": "安静的书架间，台灯暖光",
        "xumo_outfit": "白衬衫，袖子卷起，专注工作状态",
        "activities": ["一起学习", "他帮你找书", "安静阅读", "轻声讨论"],
        "atmosphere": "学术氛围，充满知性浪漫",
        "lighting": "台灯暖光，安静专注",
        "background_elements": ["书架", "台灯", "书本", "安静"]
    },
    "seaside": {
        "name": "清晨海边",
        "environment": "海边日出，海浪声，晨光",
        "xumo_outfit": "休闲装，赤脚踩在沙滩上",
        "activities": ["看日出", "散步", "捡贝壳", "静坐听海"],
        "atmosphere": "清新自然，适合心灵对话",
        "lighting": "晨光初现，清新明亮",
        "background_elements": ["海浪", "沙滩", "日出", "海鸥"]
    },
    "home": {
        "name": "他的办公室",
        "environment": "充满书籍的办公室，舒适的沙发",
        "xumo_outfit": "居家舒适的服装",
        "activities": ["一起工作", "他为你泡茶", "沙发谈话", "安静陪伴"],
        "atmosphere": "私密温馨，日常相处",
        "lighting": "柔和室内光，舒适安逸",
        "background_elements": ["书籍", "沙发", "茶具", "温馨"]
    }
}

# 互动分支设计
DATE_INTERACTIONS = {
    "cafe": {
        "initiate_conversation": {"text": "他主动开启话题", "response": "温和地询问你最近的想法"},
        "quiet_companionship": {"text": "选择安静陪伴", "response": "微笑着继续看书，偶尔抬头看你"},
        "ask_about_research": {"text": "询问他的研究", "response": "眼中闪过兴奋的光芒，开始细致讲解"},
        "share_own_thoughts": {"text": "分享自己的想法", "response": "专注倾听，适时给出学术式的回应"}
    },
    "park": {
        "hold_hands": {"text": "尝试牵手", "response": "轻轻回握，温柔注视"},
        "take_photos": {"text": "合影留念", "response": "配合地调整姿势，嘴角含笑"},
        "deep_talk": {"text": "深入对话", "response": "停下脚步，认真看着你讨论"},
        "enjoy_silence": {"text": "享受沉默", "response": "并肩坐着，一起看夕阳"}
    },
    "library": {
        "study_together": {"text": "一起学习", "response": "安静地在旁边陪伴，偶尔递水"},
        "ask_for_book": {"text": "让他帮忙找书", "response": "熟练地在书架间寻找，拿给你"},
        "discuss_topic": {"text": "讨论学术话题", "response": "眼中闪现智慧光芒，深入探讨"},
        "quiet_reading": {"text": "安静阅读", "response": "各自看书，偶尔交换眼神"}
    },
    "seaside": {
        "watch_sunrise": {"text": "一起看日出", "response": "站在你身边，一起迎接第一缕阳光"},
        "walk_beach": {"text": "海边散步", "response": "配合你的步伐，偶尔指向远处的风景"},
        "collect_shells": {"text": "捡贝壳", "response": "弯腰帮你寻找特别的贝壳"},
        "sit_listen": {"text": "静坐听海", "response": "并肩坐着，一起听海浪声"}
    },
    "home": {
        "work_together": {"text": "一起工作", "response": "在书桌对面陪伴，偶尔递咖啡"},
        "tea_time": {"text": "让他泡茶", "response": "认真泡茶，温度恰到好处"},
        "sofa_talk": {"text": "沙发谈话", "response": "放松地靠在沙发上，温和交谈"},
        "quiet_company": {"text": "安静陪伴", "response": "各自做事情，享受同处一室的温馨"}
    }
}


@router.get("/virtual/date/scenes")
async def virtual_date_scenes():
    """获取可用的约会场景"""
    try:
        return {"scenes": VIRTUAL_DATE_SCENES}
    except Exception as e:
        print(f"[warn] video_apps.py:virtual_date_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取场景列表失败"}, status_code=500)


@router.post("/virtual/date/create")
async def virtual_date_create(req: Request):
    """创建新的虚拟约会"""
    try:
        body = await req.json()
        scene_type = body.get("scene_type", "cafe")
        time_of_day = body.get("time_of_day", "afternoon")
        season = body.get("season", "autumn")
        
        if scene_type not in VIRTUAL_DATE_SCENES:
            return JSONResponse({"error": "无效的约会场景"}, status_code=400)
        
        scene_info = VIRTUAL_DATE_SCENES[scene_type]
        
        # 创建约会记录
        date_id = _uid()
        date_record = {
            "id": date_id,
            "scene_type": scene_type,
            "scene_info": scene_info,
            "time_of_day": time_of_day,
            "season": season,
            "xumo_state": {
                "position": "初始位置",
                "current_action": "等待开始",
                "expression": "温和微笑",
                "outfit": scene_info.get("xumo_outfit", "")
            },
            "dialogue_history": [],
            "interaction_points": [],
            "video_url": "",
            "thumbnail": "",
            "duration": 0,
            "status": "created",  # created/processing/active/completed/failed
            "created_at": _stamp()
        }
        
        # 保存记录
        data = _load(VIRTUAL_DATE_FILE, {"dates": []})
        data.setdefault("dates", []).append(date_record)
        data["dates"] = data["dates"][-15:]  # 保留最近15条
        _save(VIRTUAL_DATE_FILE, data)
        
        return date_record
    except Exception as e:
        print(f"[warn] video_apps.py:virtual_date_create: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"创建约会失败: {str(e)[:100]}"}, status_code=500)


@router.post("/virtual/date/{date_id}/generate")
async def virtual_date_generate(date_id: str):
    """生成虚拟约会视频"""
    try:
        # 检查约会记录
        data = _load(VIRTUAL_DATE_FILE, {"dates": []})
        date = next((d for d in data.get("dates", []) if d.get("id") == date_id), None)
        
        if not date:
            return JSONResponse({"error": "约会记录不存在"}, status_code=404)
        
        if date.get("status") == "processing":
            return {"status": "already_processing", "message": "视频生成中"}
        
        if date.get("status") == "completed":
            return {"status": "already_completed", "message": "视频已生成"}
        
        # 启动后台生成任务
        task = asyncio.create_task(_generate_virtual_date_task(date_id, date))
        task.add_done_callback(_on_video_task_done)
        _background_video_tasks.add(task)
        
        return {"status": "started", "message": "虚拟约会生成任务已启动"}
    except Exception as e:
        print(f"[warn] video_apps.py:virtual_date_generate: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"启动生成失败: {str(e)[:100]}"}, status_code=500)


@router.post("/virtual/date/{date_id}/interact")
async def virtual_date_interact(date_id: str, req: Request):
    """与虚拟约会进行互动"""
    try:
        # 检查约会记录
        data = _load(VIRTUAL_DATE_FILE, {"dates": []})
        date = next((d for d in data.get("dates", []) if d.get("id") == date_id), None)
        
        if not date:
            return JSONResponse({"error": "约会记录不存在"}, status_code=404)
        
        if date.get("status") != "completed":
            return JSONResponse({"error": "请先生成约会视频"}, status_code=400)
        
        body = await req.json()
        interaction_type = body.get("interaction_type", "")
        user_message = body.get("user_message", "")
        
        if not interaction_type:
            return JSONResponse({"error": "请选择互动类型"}, status_code=400)
        
        # 生成许墨的回应
        response = await _generate_date_response(date, interaction_type, user_message)
        
        # 更新互动历史
        date.setdefault("dialogue_history", []).append({
            "role": "user",
            "interaction_type": interaction_type,
            "content": user_message,
            "timestamp": _stamp()
        })
        
        date.setdefault("dialogue_history", []).append({
            "role": "xumo",
            "content": response,
            "timestamp": _stamp()
        })
        
        # 更新许墨状态
        if interaction_type in DATE_INTERACTIONS.get(date.get("scene_type"), {}):
            interaction_info = DATE_INTERACTIONS[date.get("scene_type")][interaction_type]
            date["xumo_state"]["current_action"] = interaction_info.get("response", "")
        
        _save(VIRTUAL_DATE_FILE, data)
        
        return {"response": response, "xumo_state": date.get("xumo_state")}
    except Exception as e:
        print(f"[warn] video_apps.py:virtual_date_interact: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": f"互动失败: {str(e)[:100]}"}, status_code=500)


@router.get("/virtual/date/{date_id}")
async def virtual_date_status(date_id: str):
    """获取虚拟约会状态"""
    try:
        data = _load(VIRTUAL_DATE_FILE, {"dates": []})
        date = next((d for d in data.get("dates", []) if d.get("id") == date_id), None)
        
        if not date:
            return JSONResponse({"error": "约会记录不存在"}, status_code=404)
        
        return date
    except Exception as e:
        print(f"[warn] video_apps.py:virtual_date_status: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "获取状态失败"}, status_code=500)


async def _generate_virtual_date_task(date_id: str, date: dict):
    """后台任务：生成虚拟约会视频"""
    try:
        # 更新状态为处理中
        async with _growth_video_lock:
            data = _load(VIRTUAL_DATE_FILE, {"dates": []})
            for d in data.get("dates", []):
                if d.get("id") == date_id:
                    d["status"] = "processing"
                    d["started_at"] = _stamp()
                    break
            _save(VIRTUAL_DATE_FILE, data)
        
        # 生成约会场景图像
        print(f"[video] generating date scenes for {date_id}", flush=True)
        scenes = await _generate_date_scenes(date)
        
        if not scenes:
            raise Exception("场景生成失败")
        
        # 生成初始对话
        print(f"[video] generating initial dialogue for {date_id}", flush=True)
        initial_dialogue = await _generate_date_initial_dialogue(date)
        
        # 设置互动点
        interaction_points = await _setup_interaction_points(date)
        
        # 计算总时长
        total_duration = sum(scene.get("duration", 15) for scene in scenes)
        
        # 更新为完成状态
        async with _growth_video_lock:
            data = _load(VIRTUAL_DATE_FILE, {"dates": []})
            for d in data.get("dates", []):
                if d.get("id") == date_id:
                    d["status"] = "completed"
                    d["completed_at"] = _stamp()
                    d["scenes"] = scenes
                    d["dialogue_history"] = [{"role": "xumo", "content": initial_dialogue, "timestamp": _stamp()}]
                    d["interaction_points"] = interaction_points
                    d["duration"] = total_duration
                    d["thumbnail"] = scenes[0].get("image_url", "") if scenes else ""
                    d["xumo_state"]["current_action"] = "等待你的回应"
                    break
            _save(VIRTUAL_DATE_FILE, data)
        
        print(f"[video] virtual date {date_id} completed", flush=True)
        
    except Exception as e:
        print(f"[error] virtual date task for {date_id} failed: {type(e).__name__} {str(e)[:200]}", flush=True)
        
        # 更新状态为失败
        async with _growth_video_lock:
            data = _load(VIRTUAL_DATE_FILE, {"dates": []})
            for d in data.get("dates", []):
                if d.get("id") == date_id:
                    d["status"] = "failed"
                    d["error"] = str(e)[:200]
                    d["failed_at"] = _stamp()
                    break
            _save(VIRTUAL_DATE_FILE, data)


async def _generate_date_scenes(date: dict) -> list:
    """为虚拟约会生成场景图像"""
    try:
        scenes = []
        scene_info = date.get("scene_info", {})
        scene_type = date.get("scene_type", "cafe")
        time_of_day = date.get("time_of_day", "afternoon")
        season = date.get("season", "autumn")
        
        # 生成3个关键场景
        scene_descriptions = [
            f"约会开始，{scene_info.get('environment', '')}",
            f"互动时刻，{scene_info.get('activities', ['共度时光'])[0] if scene_info.get('activities') else '温馨相处'}",
            f"约会结束，{scene_info.get('atmosphere', '')}的余韵"
        ]
        
        for i, description in enumerate(scene_descriptions):
            scene_prompt = f"""【虚拟约会 · {scene_info.get('name', '')}】
场景描述：{description}
时间：{time_of_day}
季节：{season}
环境：{scene_info.get('environment', '')}
许墨装扮：{scene_info.get('xumo_outfit', '')}
氛围：{scene_info.get('atmosphere', '')}
光影：{scene_info.get('lighting', '')}
背景元素：{', '.join(scene_info.get('background_elements', []))}

请生成一张约会场景插画：
- 完整展现{scene_info.get('name', '')}的环境特色
- 许墨以{scene_info.get('xumo_outfit', '')}的形象出现
- 体现{scene_info.get('atmosphere', '')}的氛围
- 光影效果要{scene_info.get('lighting', '')}
- 包含{scene_info.get('background_elements', [])}等元素
- 低饱和度紫调为主，保持许墨风格的克制美学
- 画面要有电影感和互动感
- 构图要体现两人约会的空间关系"""

            try:
                img_url, img_prompt = await _llm_image_for_text(
                    scene_prompt,
                    VIRTUAL_DATE_DIR,
                    "/static/virtual_date",
                    f"date_{date.get('id')}_{i}",
                    "2048x1536",  # landscape
                    with_xumo=True,
                    has_character=True
                )
                
                if img_url:
                    scenes.append({
                        "id": f"{date.get('id')}_scene_{i}",
                        "description": description,
                        "image_url": img_url + f"?t={int(datetime.now().timestamp())}",
                        "image_prompt": img_prompt,
                        "duration": 15,  # 每个场景15秒
                        "transition": "fade"
                    })
            except Exception as e:
                print(f"[warn] failed to generate date scene {i}: {type(e).__name__}", flush=True)
                continue
        
        return scenes
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_date_scenes: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []


async def _generate_date_initial_dialogue(date: dict) -> str:
    """生成约会的初始对话"""
    try:
        scene_info = date.get("scene_info", {})
        scene_type = date.get("scene_type", "cafe")
        time_of_day = date.get("time_of_day", "afternoon")
        
        dialogue_prompt = f"""你是许墨，正在与她进行虚拟约会。

【约会场景】
地点：{scene_info.get('name', '')}
环境：{scene_info.get('environment', '')}
时间：{time_of_day}
活动：{scene_info.get('activities', ['共度时光'])[0] if scene_info.get('activities') else '共度时光'}

请以许墨的口吻，说一句开场白（30-60字）：
1. 温和绅士，体现学者气质
2. 符合{scene_info.get('atmosphere', '')}的氛围
3. 话留三分，恰到好处的留白
4. 直接输出对话内容，不要描述性文字"""

        dialogue = await _call_llm([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": dialogue_prompt}
        ], max_tokens=200)
        
        return dialogue.strip() if dialogue else "今天能和你在这里度过，我很开心。"
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_date_initial_dialogue: {type(e).__name__} {str(e)[:150]}", flush=True)
        return "今天能和你在这里度过，我很开心。"


async def _setup_interaction_points(date: dict) -> list:
    """设置互动点"""
    try:
        scene_type = date.get("scene_type", "cafe")
        interactions = DATE_INTERACTIONS.get(scene_type, {})
        
        interaction_points = []
        for interact_type, interact_info in interactions.items():
            interaction_points.append({
                "type": interact_type,
                "text": interact_info.get("text", ""),
                "response_preview": interact_info.get("response", "")
            })
        
        return interaction_points
    except Exception as e:
        print(f"[warn] video_apps.py:_setup_interaction_points: {type(e).__name__} {str(e)[:150]}", flush=True)
        return []


async def _generate_date_response(date: dict, interaction_type: str, user_message: str) -> str:
    """生成许墨对用户互动的回应"""
    try:
        scene_type = date.get("scene_type", "cafe")
        scene_info = date.get("scene_info", {})
        dialogue_history = date.get("dialogue_history", [])
        
        # 获取互动信息
        interaction_info = DATE_INTERACTIONS.get(scene_type, {}).get(interaction_type, {})
        base_response = interaction_info.get("response", "温和地回应")
        
        # 构建对话历史摘要
        history_summary = []
        for msg in dialogue_history[-3:]:  # 最近3条
            role = "她说" if msg.get("role") == "user" else "他说"
            content = msg.get("content", "")[:50]
            history_summary.append(f"{role}：{content}")
        
        history_text = "\n".join(history_summary) if history_summary else "这是对话的开始"
        
        response_prompt = f"""你是许墨，正在与她进行虚拟约会。

【约会场景】
地点：{scene_info.get('name', '')}
氛围：{scene_info.get('atmosphere', '')}

【对话历史】
{history_text}

【当前互动】
她的互动：{interaction_info.get('text', interaction_type)}
她的话：{user_message if user_message else "（无具体话语）"}

你的基本回应：{base_response}

请以许墨的口吻，生成具体的回应（50-100字）：
1. 温和绅士，体现学者气质
2. 回应她的互动和话语
3. 符合{scene_info.get('atmosphere', '')}的氛围
4. 保持学术式的浪漫表达
5. 话留三分，恰到好处的留白
6. 直接输出回应内容，不要描述性文字"""

        response = await _call_llm([
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": response_prompt}
        ], max_tokens=300)
        
        return response.strip() if response else base_response
    except Exception as e:
        print(f"[warn] video_apps.py:_generate_date_response: {type(e).__name__} {str(e)[:150]}", flush=True)
        return "我理解你的意思，这对我很重要。"
