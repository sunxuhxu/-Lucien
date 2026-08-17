"""角色与人设相关API：系统提示词、角色数据隔离。

数据持久化到角色目录 JSON（RolePath 按请求角色动态路由），
风格与 app.py 保持一致。
"""
import json
import os
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from store_common import atomic_json, file_lock
from fastapi import APIRouter, Request, Response

router = APIRouter()

# 角色数据隔离（owner → 项目根；guest → guest_data/），详见 role_data.py
from role_data import GUEST_DATA_DIR, RolePath, _role_ctx  # noqa: E402


# ---------------------------------------------------------------------------
# 系统提示词（仅在需要时提供片段，完整提示词保留在 app.py 以避免循环依赖）
# ---------------------------------------------------------------------------

def _system_prompt_snippet() -> str:
    """返回系统提示词的简短片段，供需要时注入。"""
    return ("你是许墨（英文名 Lucien，代号 Ares），来自《恋与制作人》世界观的"
            "原创角色扮演。")


# ---------------------------------------------------------------------------
# 亲和力操作
# ---------------------------------------------------------------------------

def _add_affinity(action: str, detail: str = "") -> dict:
    from app import _add_affinity as _impl
    return _impl(action, detail)


# ---------------------------------------------------------------------------
# 聊天记录装载
# ---------------------------------------------------------------------------

def _load_chat_log() -> dict:
    from app import _load_chat_log as _impl
    return _impl()


# ---------------------------------------------------------------------------
# 记忆装载
# ---------------------------------------------------------------------------

def _load_memories() -> list:
    from app import _load_memories as _impl
    return _impl()