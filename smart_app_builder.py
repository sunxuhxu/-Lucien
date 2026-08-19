# -*- coding: utf-8 -*-
"""智能App构建器（smart_app_builder.py）

通过AI对话和可视化配置引导用户创建自定义应用，支持：
  - AI对话式创建（自然语言引导）
  - 可视化配置接口（拖拽式）
  - 模板系统（预设模板）
  - 代码生成（自动生成应用代码）

支持的功能类型：
  - 聊天对话类（自定义对话场景和角色扮演）
  - 工具实用类（待办事项、笔记、计算器等）
  - 游戏娱乐类（小游戏、问答、互动娱乐）
  - 数据分析类（数据统计、图表展示、报告生成）

数据按 RolePath 隔离，设计风格与现有模块保持一致。

API：
  POST   /api/smart-builder/start           开始构建对话
  POST   /api/smart-builder/chat            继续对话
  GET    /api/smart-builder/templates       获取模板列表
  POST   /api/smart-builder/from-template   从模板创建
  GET    /api/smart-builder/config          获取当前配置
  POST   /api/smart-builder/generate        生成应用代码
  POST   /api/smart-builder/visual-config  可视化配置
  GET    /api/smart-builder/preview         预览应用
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

SMART_BUILDER_FILE = "smart_builder.json"
SMART_APPS_FILE = "smart_apps.json"

# 功能类型配置
APP_TYPES = {
    "chat": {
        "name": "聊天对话类",
        "description": "自定义对话场景和角色扮演",
        "icon": "💬",
        "questions": [
            "你希望创建什么样的对话场景？请描述一下背景和设定",
            "主要角色有哪些？他们有什么性格特点？",
            "对话的主要话题或目的是什么？",
            "需要什么特殊的对话功能吗？比如情感分析、上下文记忆等"
        ],
        "template_fields": ["scenario", "characters", "topics", "features"]
    },
    "tool": {
        "name": "工具实用类",
        "description": "待办事项、笔记、计算器等实用工具",
        "icon": "🔧",
        "questions": [
            "你希望创建什么类型的工具？",
            "这个工具需要什么核心功能？",
            "用户如何与这个工具交互？",
            "需要数据保存和导入导出功能吗？"
        ],
        "template_fields": ["tool_type", "core_features", "interaction", "data_management"]
    },
    "game": {
        "name": "游戏娱乐类",
        "description": "小游戏、问答、互动娱乐等",
        "icon": "🎮",
        "questions": [
            "你想创建什么类型的游戏？",
            "游戏的核心玩法是什么？",
            "如何计分或判定胜负？",
            "需要多人互动还是单人体验？"
        ],
        "template_fields": ["game_type", "gameplay", "scoring", "multiplayer"]
    },
    "data": {
        "name": "数据分析类",
        "description": "数据统计、图表展示、报告生成等",
        "icon": "📊",
        "questions": [
            "你希望分析什么类型的数据？",
            "需要什么样的数据可视化？",
            "报告应该包含哪些内容？",
            "数据从哪里来？如何更新？"
        ],
        "template_fields": ["data_type", "visualization", "report_content", "data_source"]
    }
}

# 预设模板
APP_TEMPLATES = {
    "chat": [
        {
            "id": "template_chat_roleplay",
            "name": "角色扮演对话",
            "description": "创建一个自定义角色扮演场景",
            "config": {
                "scenario": "咖啡店偶遇",
                "characters": [{"name": "许墨", "personality": "温柔、博学、神秘"}],
                "topics": ["日常生活", "学术讨论", "情感交流"],
                "features": ["情感分析", "上下文记忆"]
            }
        },
        {
            "id": "template_chat_story",
            "name": "互动故事",
            "description": "创建分支剧情的互动故事",
            "config": {
                "scenario": "校园恋爱故事",
                "characters": [{"name": "主角", "personality": "活泼、善良"}],
                "topics": ["校园生活", "友情", "成长"],
                "features": ["分支选择", "剧情存档"]
            }
        }
    ],
    "tool": [
        {
            "id": "template_tool_todo",
            "name": "待办事项",
            "description": "简单的待办事项管理工具",
            "config": {
                "tool_type": "待办事项",
                "core_features": ["添加任务", "完成任务", "删除任务", "优先级设置"],
                "interaction": "点击操作",
                "data_management": "本地保存"
            }
        },
        {
            "id": "template_tool_notes",
            "name": "笔记工具",
            "description": "简单易用的笔记记录工具",
            "config": {
                "tool_type": "笔记",
                "core_features": ["创建笔记", "编辑笔记", "搜索笔记", "分类管理"],
                "interaction": "文本编辑",
                "data_management": "本地保存 + 导出"
            }
        }
    ],
    "game": [
        {
            "id": "template_game_quiz",
            "name": "问答游戏",
            "description": "创建知识问答游戏",
            "config": {
                "game_type": "问答",
                "gameplay": "回答问题获得积分",
                "scoring": "正确答案+10分，错误答案不扣分",
                "multiplayer": False
            }
        },
        {
            "id": "template_game_guess",
            "name": "猜谜游戏",
            "description": "文字猜谜游戏",
            "config": {
                "game_type": "猜谜",
                "gameplay": "根据提示猜测答案",
                "scoring": "越快猜对得分越高",
                "multiplayer": False
            }
        }
    ],
    "data": [
        {
            "id": "template_data_stats",
            "name": "数据统计",
            "description": "基础数据统计和图表展示",
            "config": {
                "data_type": "通用数据",
                "visualization": ["柱状图", "折线图", "饼图"],
                "report_content": ["数据概览", "趋势分析", "对比分析"],
                "data_source": "手动输入"
            }
        },
        {
            "id": "template_data_habit",
            "name": "习惯追踪",
            "description": "个人习惯数据追踪和分析",
            "config": {
                "data_type": "习惯数据",
                "visualization": ["进度条", "日历热图", "趋势图"],
                "report_content": ["完成率", "连续天数", "最佳表现"],
                "data_source": "每日打卡"
            }
        }
    ]
}

# 对话状态存储
CONVERSATION_STATES = {}


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


def _uid() -> str:
    """生成唯一ID"""
    return uuid.uuid4().hex[:12]


# ===========================================================================
# 核心类
# ===========================================================================

class SmartAppBuilder:
    """智能App构建器"""
    
    def __init__(self, user_id: str = "owner"):
        self.user_id = user_id
        self.conversation_id = str(uuid.uuid4())
        self.state = {
            "step": "greeting",
            "app_type": None,
            "collected_info": {},
            "draft_config": None,
            "messages": [],
            "template_used": None
        }
    
    def get_greeting(self) -> str:
        """获取开场白"""
        return (
            "你好！我是智能App构建助手。🤖\n\n"
            "我可以帮你创建自定义应用，支持以下类型：\n"
            "1. 💬 聊天对话类 - 自定义对话场景和角色扮演\n"
            "2. 🔧 工具实用类 - 待办事项、笔记、计算器等\n"
            "3. 🎮 游戏娱乐类 - 小游戏、问答、互动娱乐\n"
            "4. 📊 数据分析类 - 数据统计、图表展示、报告生成\n\n"
            "请告诉我你想创建什么类型的应用？或者描述一下你的需求，"
            "我会帮你推荐合适的类型。\n\n"
            "你也可以选择使用预设模板来快速开始。"
        )
    
    def understand_intent(self, user_input: str) -> Tuple[str, float]:
        """理解用户意图，返回推荐的应用类型和置信度"""
        user_input_lower = user_input.lower()
        
        # 简单的关键词匹配
        type_scores = {
            "chat": 0.0,
            "tool": 0.0,
            "game": 0.0,
            "data": 0.0
        }
        
        # 聊天对话相关关键词
        chat_keywords = ["对话", "聊天", "角色", "扮演", "场景", "互动", "故事", "剧情"]
        for keyword in chat_keywords:
            if keyword in user_input:
                type_scores["chat"] += 0.2
        
        # 工具相关关键词
        tool_keywords = ["工具", "待办", "笔记", "任务", "管理", "记录", "计划", "提醒"]
        for keyword in tool_keywords:
            if keyword in user_input:
                type_scores["tool"] += 0.2
        
        # 游戏相关关键词
        game_keywords = ["游戏", "问答", "猜谜", "娱乐", "玩", "积分", "竞技"]
        for keyword in game_keywords:
            if keyword in user_input:
                type_scores["game"] += 0.2
        
        # 数据分析相关关键词
        data_keywords = ["数据", "统计", "分析", "图表", "报告", "追踪", "监控"]
        for keyword in data_keywords:
            if keyword in user_input:
                type_scores["data"] += 0.2
        
        # 找出最高分的类型
        max_type = max(type_scores, key=type_scores.get)
        max_score = type_scores[max_type]
        
        # 如果所有分数都很低，返回tool作为默认
        if max_score < 0.1:
            return "tool", 0.3
        
        return max_type, min(max_score, 1.0)
    
    def get_type_selection_guidance(self, intent_type: str, confidence: float) -> str:
        """根据用户意图提供类型选择指导"""
        if confidence > 0.6:
            type_info = APP_TYPES[intent_type]
            return (
                f"根据你的描述，我推荐你创建「{type_info['name']}」。\n"
                f"{type_info['description']}\n\n"
                f"如果这个类型符合你的需求，请回复「确认」或「是」。\n"
                f"如果你想选择其他类型，请告诉我。"
            )
        else:
            return (
                "我不太确定你想要哪种类型，让我为你介绍一下：\n\n"
                "1. 💬 聊天对话类：适合创建自定义对话场景和角色扮演\n"
                "2. 🔧 工具实用类：适合待办事项、笔记、计算器等实用工具\n"
                "3. 🎮 游戏娱乐类：适合小游戏、问答、互动娱乐\n"
                "4. 📊 数据分析类：适合数据统计、图表展示、报告生成\n\n"
                "请回复数字或类型名称来选择。"
            )
    
    def start_type_collection(self, app_type: str) -> str:
        """开始收集特定类型的信息"""
        self.state["app_type"] = app_type
        self.state["step"] = "collecting_info"
        self.state["current_question_index"] = 0
        
        type_info = APP_TYPES[app_type]
        first_question = type_info["questions"][0]
        
        return f"好的，我们开始创建「{type_info['name']}」。\n\n{first_question}"
    
    def process_answer(self, user_input: str) -> str:
        """处理用户回答，引导到下一个问题"""
        app_type = self.state["app_type"]
        type_info = APP_TYPES[app_type]
        
        current_index = self.state["current_question_index"]
        
        # 保存用户回答
        question_key = f"q{current_index}"
        self.state["collected_info"][question_key] = user_input
        
        # 移动到下一个问题
        next_index = current_index + 1
        
        if next_index < len(type_info["questions"]):
            self.state["current_question_index"] = next_index
            next_question = type_info["questions"][next_index]
            return next_question
        else:
            # 所有问题都回答完了，生成配置
            self.state["step"] = "generating_config"
            return self.generate_draft_config()
    
    def generate_draft_config(self) -> str:
        """基于收集的信息生成草稿配置"""
        app_type = self.state["app_type"]
        collected = self.state["collected_info"]
        
        # 根据类型生成不同的配置
        config = {"type": app_type, "name": "", "description": ""}
        
        if app_type == "chat":
            config.update({
                "scenario": collected.get("q0", ""),
                "characters": self._parse_characters(collected.get("q1", "")),
                "topics": self._parse_topics(collected.get("q2", "")),
                "features": self._parse_features(collected.get("q3", ""))
            })
        elif app_type == "tool":
            config.update({
                "tool_type": collected.get("q0", ""),
                "core_features": self._parse_features(collected.get("q1", "")),
                "interaction": collected.get("q2", ""),
                "data_management": collected.get("q3", "")
            })
        elif app_type == "game":
            config.update({
                "game_type": collected.get("q0", ""),
                "gameplay": collected.get("q1", ""),
                "scoring": collected.get("q2", ""),
                "multiplayer": "多人" in collected.get("q3", "")
            })
        elif app_type == "data":
            config.update({
                "data_type": collected.get("q0", ""),
                "visualization": self._parse_features(collected.get("q1", "")),
                "report_content": self._parse_features(collected.get("q2", "")),
                "data_source": collected.get("q3", "")
            })
        
        # 生成应用名称
        config["name"] = self._generate_app_name(app_type, collected)
        config["description"] = self._generate_description(app_type, collected)
        
        self.state["draft_config"] = config
        
        return (
            "我已经根据你的需求生成了应用配置草稿：\n\n"
            f"```json\n{json.dumps(config, indent=2, ensure_ascii=False)}\n```\n\n"
            "你可以：\n"
            "1. 回复「确认」来生成应用代码\n"
            "2. 回复「修改」来调整配置\n"
            "3. 回复「取消」来重新开始"
        )
    
    def _parse_characters(self, text: str) -> list:
        """解析角色信息"""
        if not text:
            return []
        # 简单的文本解析，实际可以更复杂
        return [{"name": "默认角色", "personality": text}]
    
    def _parse_topics(self, text: str) -> list:
        """解析话题列表"""
        if not text:
            return []
        # 按逗号或顿号分割
        separators = [",", "，", "、"]
        for sep in separators:
            if sep in text:
                return [t.strip() for t in text.split(sep) if t.strip()]
        return [text.strip()]
    
    def _parse_features(self, text: str) -> list:
        """解析功能列表"""
        if not text:
            return []
        # 按逗号或顿号分割
        separators = [",", "，", "、"]
        for sep in separators:
            if sep in text:
                return [f.strip() for f in text.split(sep) if f.strip()]
        return [text.strip()]
    
    def _generate_app_name(self, app_type: str, collected: dict) -> str:
        """生成应用名称"""
        type_names = {
            "chat": "对话",
            "tool": "工具",
            "game": "游戏",
            "data": "分析"
        }
        base = collected.get("q0", "")[:8]  # 取第一个回答的前8个字
        return f"{base}{type_names.get(app_type, '应用')}"
    
    def _generate_description(self, app_type: str, collected: dict) -> str:
        """生成应用描述"""
        answers = [collected.get(f"q{i}", "") for i in range(4)]
        return " ".join([a for a in answers if a])[:100]
    
    def generate_code(self) -> dict:
        """生成应用代码"""
        config = self.state["draft_config"]
        if not config:
            raise ValueError("配置不存在，请先完成对话")
        
        app_type = config["type"]
        
        # 根据类型生成不同的代码模板
        if app_type == "chat":
            code = self._generate_chat_code(config)
        elif app_type == "tool":
            code = self._generate_tool_code(config)
        elif app_type == "game":
            code = self._generate_game_code(config)
        elif app_type == "data":
            code = self._generate_data_code(config)
        else:
            code = {"error": "不支持的应用类型"}
        
        return {
            "config": config,
            "code": code,
            "generated_at": _now()
        }
    
    def _generate_chat_code(self, config: dict) -> dict:
        """生成聊天对话类应用代码"""
        return {
            "module": f"{config['name']}_app.py",
            "code_template": f'''
# -*- coding: utf-8 -*-
"""{config['name']} - {config['description']}"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

APP_FILE = "{config['name']}.json"

# 应用配置
APP_CONFIG = {json.dumps(config, ensure_ascii=False, indent=2)}

@router.get("/api/{config['name']}")
async def get_app():
    """获取应用状态"""
    # 实现应用逻辑
    return {{"status": "ok", "config": APP_CONFIG}}

@router.post("/api/{config['name']}/interact")
async def interact(req: Request):
    """用户交互"""
    body = await req.json()
    # 实现交互逻辑
    return {{"response": "这是一个示例响应"}}
''',
            "api_routes": [
                f"GET /api/{config['name']}",
                f"POST /api/{config['name']}/interact"
            ]
        }
    
    def _generate_tool_code(self, config: dict) -> dict:
        """生成工具实用类应用代码"""
        return {
            "module": f"{config['name']}_app.py",
            "code_template": f'''
# -*- coding: utf-8 -*-
"""{config['name']} - {config['description']}"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

APP_FILE = "{config['name']}.json"

# 应用配置
APP_CONFIG = {json.dumps(config, ensure_ascii=False, indent=2)}

@router.get("/api/{config['name']}/items")
async def get_items():
    """获取项目列表"""
    # 实现工具逻辑
    return {{"items": []}}

@router.post("/api/{config['name']}/items")
async def create_item(req: Request):
    """创建新项目"""
    body = await req.json()
    # 实现创建逻辑
    return {{"status": "created"}}
''',
            "api_routes": [
                f"GET /api/{config['name']}/items",
                f"POST /api/{config['name']}/items"
            ]
        }
    
    def _generate_game_code(self, config: dict) -> dict:
        """生成游戏娱乐类应用代码"""
        return {
            "module": f"{config['name']}_app.py",
            "code_template": f'''
# -*- coding: utf-8 -*-
"""{config['name']} - {config['description']}"""
import json
import uuid
import random
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

GAME_FILE = "{config['name']}.json"

# 游戏配置
GAME_CONFIG = {json.dumps(config, ensure_ascii=False, indent=2)}

@router.get("/api/{config['name']}/start")
async def start_game():
    """开始游戏"""
    # 实现游戏逻辑
    return {{"status": "started", "score": 0}}

@router.post("/api/{config['name']}/action")
async def game_action(req: Request):
    """游戏动作"""
    body = await req.json()
    # 实现游戏动作逻辑
    return {{"result": "success", "new_score": 10}}
''',
            "api_routes": [
                f"GET /api/{config['name']}/start",
                f"POST /api/{config['name']}/action"
            ]
        }
    
    def _generate_data_code(self, config: dict) -> dict:
        """生成数据分析类应用代码"""
        return {
            "module": f"{config['name']}_app.py",
            "code_template": f'''
# -*- coding: utf-8 -*-
"""{config['name']} - {config['description']}"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

DATA_FILE = "{config['name']}.json"

# 数据配置
DATA_CONFIG = {json.dumps(config, ensure_ascii=False, indent=2)}

@router.get("/api/{config['name']}/data")
async def get_data():
    """获取数据"""
    # 实现数据获取逻辑
    return {{"data": [], "stats": {{}}}}

@router.get("/api/{config['name']}/report")
async def get_report():
    """生成报告"""
    # 实现报告生成逻辑
    return {{"report": "示例报告"}}
''',
            "api_routes": [
                f"GET /api/{config['name']}/data",
                f"GET /api/{config['name']}/report"
            ]
        }


# ===========================================================================
# API 路由
# ===========================================================================

@router.post("/api/smart-builder/start")
async def start_builder(req: Request):
    """开始构建对话"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    user_id = body.get("user_id", "owner")
    builder = SmartAppBuilder(user_id)
    
    conversation_id = builder.conversation_id
    CONVERSATION_STATES[conversation_id] = builder
    
    return {
        "conversation_id": conversation_id,
        "greeting": builder.get_greeting(),
        "state": builder.state
    }


@router.post("/api/smart-builder/chat")
async def continue_chat(req: Request):
    """继续对话"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    conversation_id = body.get("conversation_id")
    user_input = body.get("user_input", "").strip()
    
    if not conversation_id or conversation_id not in CONVERSATION_STATES:
        return JSONResponse({"error": "对话不存在"}, status_code=404)
    
    if not user_input:
        return JSONResponse({"error": "输入不能为空"}, status_code=400)
    
    builder = CONVERSATION_STATES[conversation_id]
    state = builder.state
    
    # 保存用户消息
    builder.state["messages"].append({"role": "user", "content": user_input})
    
    response = ""
    
    if state["step"] == "greeting":
        # 分析用户意图
        intent_type, confidence = builder.understand_intent(user_input)
        response = builder.get_type_selection_guidance(intent_type, confidence)
        
        # 如果用户确认类型
        if user_input in ["确认", "是", "yes", "ok"] and confidence > 0.6:
            response = builder.start_type_collection(intent_type)
        elif user_input in ["1", "2", "3", "4"]:
            type_map = {"1": "chat", "2": "tool", "3": "game", "4": "data"}
            if user_input in type_map:
                response = builder.start_type_collection(type_map[user_input])
        
    elif state["step"] == "collecting_info":
        # 处理用户回答
        if user_input in ["确认", "是", "yes", "ok"]:
            response = builder.generate_draft_config()
        elif user_input in ["修改", "调整", "edit"]:
            response = "请告诉我你想修改什么？"
        elif user_input in ["取消", "重新", "cancel"]:
            builder.state["step"] = "greeting"
            builder.state["collected_info"] = {}
            response = builder.get_greeting()
        else:
            response = builder.process_answer(user_input)
    
    elif state["step"] == "generating_config":
        if user_input in ["确认", "是", "yes", "ok", "生成", "generate"]:
            # 生成代码
            try:
                code_result = builder.generate_code()
                builder.state["step"] = "completed"
                response = (
                    "✅ 应用代码生成成功！\n\n"
                    f"应用名称：{code_result['config']['name']}\n"
                    f"应用类型：{code_result['config']['type']}\n"
                    f"API路由：{', '.join(code_result['code']['api_routes'])}\n\n"
                    "代码已准备好，可以查看和部署。"
                )
                # 保存生成结果
                builder.state["generated_code"] = code_result
            except Exception as e:
                response = f"生成代码时出错：{str(e)}"
        elif user_input in ["修改", "调整", "edit"]:
            builder.state["step"] = "collecting_info"
            response = "请重新描述你的需求，或告诉我需要修改的部分。"
        elif user_input in ["取消", "重新", "cancel"]:
            builder.state["step"] = "greeting"
            builder.state["collected_info"] = {}
            response = builder.get_greeting()
        else:
            response = "请回复「确认」来生成代码，或「修改」来调整配置。"
    
    elif state["step"] == "completed":
        if user_input in ["重新", "新", "new", "restart"]:
            builder.state["step"] = "greeting"
            builder.state["collected_info"] = {}
            response = builder.get_greeting()
        else:
            response = "应用已生成完成。如需创建新应用，请回复「重新」。"
    
    # 保存助手回复
    builder.state["messages"].append({"role": "assistant", "content": response})
    
    return {
        "response": response,
        "state": builder.state
    }


@router.get("/api/smart-builder/templates")
async def get_templates(app_type: str = None):
    """获取模板列表"""
    if app_type:
        templates = APP_TEMPLATES.get(app_type, [])
        return {"type": app_type, "templates": templates}
    
    return {"templates": APP_TEMPLATES}


@router.post("/api/smart-builder/from-template")
async def create_from_template(req: Request):
    """从模板创建应用"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    template_id = body.get("template_id")
    app_type = body.get("app_type")
    customizations = body.get("customizations", {})
    
    if not template_id or not app_type:
        return JSONResponse({"error": "缺少模板ID或应用类型"}, status_code=400)
    
    # 查找模板
    templates = APP_TEMPLATES.get(app_type, [])
    template = next((t for t in templates if t["id"] == template_id), None)
    
    if not template:
        return JSONResponse({"error": "模板不存在"}, status_code=404)
    
    # 应用自定义配置
    config = template["config"].copy()
    config.update(customizations)
    config["type"] = app_type
    config["name"] = customizations.get("name", template["name"])
    config["description"] = customizations.get("description", template["description"])
    
    # 创建构建器实例
    user_id = body.get("user_id", "owner")
    builder = SmartAppBuilder(user_id)
    builder.state["app_type"] = app_type
    builder.state["draft_config"] = config
    builder.state["template_used"] = template_id
    builder.state["step"] = "generating_config"
    
    conversation_id = builder.conversation_id
    CONVERSATION_STATES[conversation_id] = builder
    
    return {
        "conversation_id": conversation_id,
        "template": template,
        "config": config,
        "message": "模板已加载，你可以直接生成代码或进行自定义调整"
    }


@router.get("/api/smart-builder/config")
async def get_config(conversation_id: str):
    """获取当前配置"""
    if conversation_id not in CONVERSATION_STATES:
        return JSONResponse({"error": "对话不存在"}, status_code=404)
    
    builder = CONVERSATION_STATES[conversation_id]
    return {
        "config": builder.state.get("draft_config"),
        "state": builder.state["step"]
    }


@router.post("/api/smart-builder/generate")
async def generate_code(req: Request):
    """生成应用代码"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    conversation_id = body.get("conversation_id")
    
    if conversation_id not in CONVERSATION_STATES:
        return JSONResponse({"error": "对话不存在"}, status_code=404)
    
    builder = CONVERSATION_STATES[conversation_id]
    
    try:
        code_result = builder.generate_code()
        builder.state["step"] = "completed"
        builder.state["generated_code"] = code_result
        
        # 保存到智能应用列表
        smart_apps = _load(SMART_APPS_FILE, {"apps": []})
        smart_apps["apps"].append({
            "id": _uid(),
            "config": code_result["config"],
            "code": code_result["code"],
            "created_at": _now(),
            "conversation_id": conversation_id
        })
        _save(SMART_APPS_FILE, smart_apps)
        
        return code_result
    except Exception as e:
        return JSONResponse({"error": f"生成代码失败: {str(e)}"}, status_code=500)


@router.post("/api/smart-builder/visual-config")
async def visual_config(req: Request):
    """可视化配置接口"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    app_type = body.get("app_type")
    config_data = body.get("config", {})
    
    if not app_type:
        return JSONResponse({"error": "缺少应用类型"}, status_code=400)
    
    # 验证配置字段
    type_info = APP_TYPES.get(app_type)
    if not type_info:
        return JSONResponse({"error": "无效的应用类型"}, status_code=400)
    
    # 创建构建器实例
    user_id = body.get("user_id", "owner")
    builder = SmartAppBuilder(user_id)
    builder.state["app_type"] = app_type
    builder.state["draft_config"] = config_data
    builder.state["step"] = "generating_config"
    
    conversation_id = builder.conversation_id
    CONVERSATION_STATES[conversation_id] = builder
    
    return {
        "conversation_id": conversation_id,
        "config": config_data,
        "message": "可视化配置已保存，可以生成代码"
    }


@router.get("/api/smart-builder/preview")
async def preview_app(conversation_id: str):
    """预览应用"""
    if conversation_id not in CONVERSATION_STATES:
        return JSONResponse({"error": "对话不存在"}, status_code=404)
    
    builder = CONVERSATION_STATES[conversation_id]
    config = builder.state.get("draft_config")
    
    if not config:
        return JSONResponse({"error": "配置不存在"}, status_code=400)
    
    return {
        "preview": {
            "name": config.get("name", "未命名应用"),
            "type": config.get("type", "unknown"),
            "description": config.get("description", ""),
            "features": config.get("features", []),
            "config": config
        }
    }