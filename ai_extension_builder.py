# -*- coding: utf-8 -*-
"""AI对话式扩展构建器 (ai_extension_builder.py)

通过自然语言对话引导用户创建自定义扩展，支持：
  - 对话式需求收集和参数配置
  - AI理解用户意图并生成扩展配置
  - 智能推荐扩展类型和模板
  - 实时预览和调整扩展配置
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

# 扩展类型描述和引导问题
EXTENSION_TYPES = {
    "prompt_template": {
        "name": "提示词模板",
        "description": "自定义系统提示词，改变AI的说话风格和回答方式",
        "questions": [
            "你希望AI在什么情况下使用这个提示词？",
            "你希望AI说什么样的话？请描述一下你想要的语气或内容",
            "这个提示词是否需要特定触发条件？比如关键词或时间"
        ],
        "example": "让AI在深夜时语气更温柔，多用短句回应"
    },
    "tool_chain": {
        "name": "工具链",
        "description": "集成外部API工具，让AI可以获取实时数据或执行操作",
        "questions": [
            "你希望AI调用什么外部服务？比如天气、新闻、翻译等",
            "需要什么触发条件来启动这个工具链？",
            "希望AI如何处理工具返回的数据？"
        ],
        "example": "用户问天气时自动调用天气API获取实时信息"
    },
    "workflow": {
        "name": "工作流",
        "description": "编排多个步骤的复杂任务，支持条件判断和循环",
        "questions": [
            "这个工作流要完成什么任务？",
            "需要哪些步骤？请按顺序描述",
            "是否需要根据不同条件走不同的分支？"
        ],
        "example": "接收用户心情 → 分析 → 生成许墨的回应建议"
    }
}

# 对话状态存储
CONVERSATION_STATES = {}


class ExtensionBuilder:
    """AI对话式扩展构建器"""
    
    def __init__(self, user_id: str = "owner"):
        self.user_id = user_id
        self.role_path = RolePath(user_id)
        self.conversation_id = str(uuid.uuid4())
        self.state = {
            "step": "greeting",
            "extension_type": None,
            "collected_info": {},
            "draft_config": None,
            "messages": []
        }
    
    def get_greeting(self) -> str:
        """获取开场白"""
        return (
            "你好！我是许墨的扩展构建助手。🦋\n\n"
            "我可以帮你创建自定义扩展来增强许墨的能力。\n\n"
            "目前支持三种扩展类型：\n"
            "1. 提示词模板 - 改变AI的说话风格\n"
            "2. 工具链 - 集成外部API服务\n"
            "3. 工作流 - 编排复杂的多步骤任务\n\n"
            "请告诉我你想创建哪种类型的扩展？或者描述一下你的需求，"
            "我会帮你推荐合适的类型。"
        )
    
    def understand_intent(self, user_input: str) -> Tuple[str, float]:
        """理解用户意图，返回推荐的扩展类型和置信度"""
        user_input_lower = user_input.lower()
        
        # 简单的关键词匹配
        type_scores = {
            "prompt_template": 0.0,
            "tool_chain": 0.0,
            "workflow": 0.0
        }
        
        # 提示词相关关键词
        prompt_keywords = ["语气", "说话", "风格", "回答", "性格", "人设", "模板", "提示词"]
        for keyword in prompt_keywords:
            if keyword in user_input:
                type_scores["prompt_template"] += 0.2
        
        # 工具链相关关键词
        tool_keywords = ["api", "天气", "新闻", "翻译", "调用", "外部", "数据", "查询", "工具"]
        for keyword in tool_keywords:
            if keyword in user_input:
                type_scores["tool_chain"] += 0.2
        
        # 工作流相关关键词
        workflow_keywords = ["步骤", "流程", "工作流", "任务", "多步骤", "分支", "条件", "编排"]
        for keyword in workflow_keywords:
            if keyword in user_input:
                type_scores["workflow"] += 0.2
        
        # 找出最高分的类型
        max_type = max(type_scores, key=type_scores.get)
        max_score = type_scores[max_type]
        
        # 如果所有分数都很低，返回workflow作为默认
        if max_score < 0.1:
            return "workflow", 0.3
        
        return max_type, min(max_score, 1.0)
    
    def get_type_selection_guidance(self, intent_type: str, confidence: float) -> str:
        """根据用户意图提供类型选择指导"""
        if confidence > 0.6:
            ext_info = EXTENSION_TYPES[intent_type]
            return (
                f"根据你的描述，我推荐你创建「{ext_info['name']}」。\n"
                f"{ext_info['description']}\n\n"
                f"例如：{ext_info['example']}\n\n"
                f"如果这个类型符合你的需求，请回复「确认」或「是」。\n"
                f"如果你想选择其他类型，请告诉我。"
            )
        else:
            return (
                "我不太确定你想要哪种类型，让我为你介绍一下：\n\n"
                "1. 提示词模板：适合改变AI说话风格或回答方式\n"
                "   例如：让AI在深夜时语气更温柔\n\n"
                "2. 工具链：适合需要调用外部API获取数据的场景\n"
                "   例如：查询天气、获取新闻等\n\n"
                "3. 工作流：适合复杂的多步骤任务\n"
                "   例如：心情分析 → 生成回应建议\n\n"
                "请回复数字或类型名称来选择。"
            )
    
    def start_type_collection(self, ext_type: str) -> str:
        """开始收集特定类型的信息"""
        self.state["extension_type"] = ext_type
        self.state["step"] = "collecting_info"
        self.state["current_question_index"] = 0
        
        ext_info = EXTENSION_TYPES[ext_type]
        first_question = ext_info["questions"][0]
        
        return f"好的，我们开始创建「{ext_info['name']}」。\n\n{first_question}"
    
    def process_answer(self, user_input: str) -> str:
        """处理用户回答，引导到下一个问题"""
        ext_type = self.state["extension_type"]
        ext_info = EXTENSION_TYPES[ext_type]
        
        current_index = self.state["current_question_index"]
        
        # 保存用户回答
        question_key = f"q{current_index}"
        self.state["collected_info"][question_key] = user_input
        
        # 移动到下一个问题
        next_index = current_index + 1
        
        if next_index < len(ext_info["questions"]):
            self.state["current_question_index"] = next_index
            next_question = ext_info["questions"][next_index]
            return next_question
        else:
            # 所有问题都回答完了，生成配置
            self.state["step"] = "generating_config"
            return self.generate_draft_config()
    
    def generate_draft_config(self) -> str:
        """基于收集的信息生成草稿配置"""
        ext_type = self.state["extension_type"]
        collected = self.state["collected_info"]
        
        # 根据类型生成不同的配置
        if ext_type == "prompt_template":
            config = self._generate_prompt_template_config(collected)
        elif ext_type == "tool_chain":
            config = self._generate_tool_chain_config(collected)
        elif ext_type == "workflow":
            config = self._generate_workflow_config(collected)
        else:
            config = {}
        
        self.state["draft_config"] = config
        
        return (
            "我已经根据你的需求生成了扩展配置草稿：\n\n"
            f"```json\n{json.dumps(config, indent=2, ensure_ascii=False)}\n```\n\n"
            "你可以：\n"
            "1. 回复「确认」来保存这个扩展\n"
            "2. 回复「修改」来调整配置\n"
            "3. 回复「取消」来重新开始"
        )
    
    def _generate_prompt_template_config(self, collected: Dict) -> Dict:
        """生成提示词模板配置"""
        # 从收集的信息中提取关键内容
        q0_answer = collected.get("q0", "")  # 使用场景
        q1_answer = collected.get("q1", "")  # 语气内容
        q2_answer = collected.get("q2", "")  # 触发条件
        
        # 智能判断触发类型
        trigger = "always"
        trigger_pattern = ""
        
        if any(keyword in q2_answer for keyword in ["关键词", "当", "如果", "遇到"]):
            trigger = "keyword"
            # 简单提取关键词
            if "，" in q2_answer or "," in q2_answer:
                trigger_pattern = q2_answer.replace("关键词", "").replace("当", "").replace("如果", "").replace("遇到", "").strip()
            else:
                trigger_pattern = q2_answer
        elif any(keyword in q2_answer for keyword in ["时间", "深夜", "早上", "晚上"]):
            trigger = "regex"
            trigger_pattern = q2_answer
        
        # 生成提示词内容
        content = q1_answer if q1_answer else "请根据用户需求调整回答风格"
        
        return {
            "name": f"自定义提示词-{datetime.now().strftime('%m%d%H%M')}",
            "type": "prompt_template",
            "description": q0_answer[:100] if q0_answer else "用户自定义提示词模板",
            "enabled": True,
            "priority": 10,
            "config": {
                "trigger": trigger,
                "trigger_pattern": trigger_pattern,
                "inject_position": "system_suffix",
                "content": content
            }
        }
    
    def _generate_tool_chain_config(self, collected: Dict) -> Dict:
        """生成工具链配置"""
        q0_answer = collected.get("q0", "")  # 外部服务
        q1_answer = collected.get("q1", "")  # 触发条件
        q2_answer = collected.get("q2", "")  # 数据处理
        
        # 智能判断API类型
        tool_type = "http_get"
        url = ""
        
        if "天气" in q0_answer:
            url = "https://api.openweathermap.org/data/2.5/weather?q=Beijing&appid=YOUR_API_KEY&units=metric&lang=zh_cn"
        elif "新闻" in q0_answer:
            url = "https://newsapi.org/v2/top-headlines?country=cn&apiKey=YOUR_API_KEY"
        elif "翻译" in q0_answer:
            url = "https://api.mymemory.translated.net/get?q=hello&langpair=en|zh"
        else:
            url = "https://api.example.com/endpoint"
        
        # 提取触发关键词
        trigger_pattern = q1_answer.replace("触发", "").replace("当", "").replace("如果", "").strip()
        
        return {
            "name": f"自定义工具链-{datetime.now().strftime('%m%d%H%M')}",
            "type": "tool_chain",
            "description": q0_answer[:100] if q0_answer else "用户自定义工具链",
            "enabled": True,
            "priority": 20,
            "config": {
                "trigger": "keyword",
                "trigger_pattern": trigger_pattern,
                "output_format": "json",
                "tools": [
                    {
                        "type": tool_type,
                        "name": "custom_tool",
                        "params": {
                            "url": url,
                            "timeout": 10
                        }
                    }
                ]
            }
        }
    
    def _generate_workflow_config(self, collected: Dict) -> Dict:
        """生成工作流配置"""
        q0_answer = collected.get("q0", "")  # 任务描述
        q1_answer = collected.get("q1", "")  # 步骤描述
        q2_answer = collected.get("q2", "")  # 条件分支
        
        # 简单解析步骤
        steps = []
        step_descriptions = [s.strip() for s in q1_answer.split("，") if s.strip()] if q1_answer else ["默认步骤"]
        
        for i, desc in enumerate(step_descriptions):
            step_id = f"s{i+1}"
            if i == 0:
                # 第一步通常是prompt
                steps.append({
                    "id": step_id,
                    "type": "prompt",
                    "config": {
                        "var": f"var_{i}",
                        "template": f"{desc}：{{{{user_input}}}}"
                    },
                    "next": f"s{i+2}" if i < len(step_descriptions) - 1 else "final"
                })
            elif i == len(step_descriptions) - 1:
                # 最后一步是output
                steps.append({
                    "id": step_id,
                    "type": "output",
                    "config": {
                        "template": "{{var_0}}"
                    }
                })
            else:
                # 中间步骤
                steps.append({
                    "id": step_id,
                    "type": "prompt",
                    "config": {
                        "var": f"var_{i}",
                        "template": desc
                    },
                    "next": f"s{i+2}" if i < len(step_descriptions) - 1 else "final"
                })
        
        return {
            "name": f"自定义工作流-{datetime.now().strftime('%m%d%H%M')}",
            "type": "workflow",
            "description": q0_answer[:100] if q0_answer else "用户自定义工作流",
            "enabled": True,
            "priority": 30,
            "config": {
                "steps": steps
            }
        }
    
    def save_extension(self) -> Dict:
        """保存扩展到文件"""
        if not self.state["draft_config"]:
            raise ValueError("没有可保存的配置")
        
        config = self.state["draft_config"]
        ext_file = self.role_path.resolve("extensions.json", enforce_user_scope=True)
        
        # 读取现有扩展
        try:
            with file_lock(ext_file, "r"):
                existing_data = atomic_json(ext_file)
        except:
            existing_data = {"extensions": [], "order": []}
        
        # 生成唯一ID
        ext_id = str(uuid.uuid4())
        config["id"] = ext_id
        config["created_at"] = datetime.now().isoformat()
        config["updated_at"] = datetime.now().isoformat()
        
        # 添加到扩展列表
        existing_data["extensions"].append(config)
        existing_data["order"].append(ext_id)
        
        # 保存
        with file_lock(ext_file, "w"):
            atomic_json(ext_file, existing_data)
        
        return config
    
    def reset(self):
        """重置构建器状态"""
        self.state = {
            "step": "greeting",
            "extension_type": None,
            "collected_info": {},
            "draft_config": None,
            "messages": []
        }


# ===========================================================================
# API 路由
# ===========================================================================

@router.post("/builder/start")
async def start_conversation(request: Request) -> JSONResponse:
    """开始新的扩展构建对话"""
    try:
        body = await request.json()
        user_id = body.get("user_id", "owner")
        
        builder = ExtensionBuilder(user_id)
        conversation_id = builder.conversation_id
        
        CONVERSATION_STATES[conversation_id] = builder
        
        return JSONResponse({
            "conversation_id": conversation_id,
            "message": builder.get_greeting(),
            "step": "greeting"
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/builder/chat")
async def chat(request: Request) -> JSONResponse:
    """继续对话"""
    try:
        body = await request.json()
        conversation_id = body.get("conversation_id")
        user_input = body.get("user_input", "")
        
        if conversation_id not in CONVERSATION_STATES:
            return JSONResponse({"error": "对话不存在，请重新开始"}, status_code=404)
        
        builder = CONVERSATION_STATES[conversation_id]
        step = builder.state["step"]
        
        response = ""
        
        if step == "greeting":
            # 理解用户意图
            intent_type, confidence = builder.understand_intent(user_input)
            
            # 检查用户是否直接指定了类型
            if user_input in ["1", "提示词模板", "prompt_template"]:
                intent_type = "prompt_template"
                confidence = 1.0
            elif user_input in ["2", "工具链", "tool_chain"]:
                intent_type = "tool_chain"
                confidence = 1.0
            elif user_input in ["3", "工作流", "workflow"]:
                intent_type = "workflow"
                confidence = 1.0
            
            if confidence > 0.8 or user_input in ["确认", "是", "yes"]:
                response = builder.start_type_collection(intent_type)
            else:
                response = builder.get_type_selection_guidance(intent_type, confidence)
        
        elif step == "collecting_info":
            if user_input in ["取消", "cancel"]:
                builder.reset()
                response = builder.get_greeting()
            else:
                response = builder.process_answer(user_input)
        
        elif step == "generating_config":
            if user_input in ["确认", "保存", "save", "yes"]:
                saved_config = builder.save_extension()
                del CONVERSATION_STATES[conversation_id]
                response = f"扩展已保存！扩展ID: {saved_config['id']}\n\n你可以在扩展管理页面查看和管理这个扩展。"
            elif user_input in ["修改", "edit"]:
                builder.state["step"] = "collecting_info"
                builder.state["current_question_index"] = 0
                ext_type = builder.state["extension_type"]
                ext_info = EXTENSION_TYPES[ext_type]
                response = f"好的，让我们重新配置。{ext_info['questions'][0]}"
            elif user_input in ["取消", "cancel"]:
                del CONVERSATION_STATES[conversation_id]
                response = "已取消。你可以重新开始创建扩展。"
            else:
                response = "请回复「确认」保存、「修改」调整或「取消」重新开始"
        
        return JSONResponse({
            "conversation_id": conversation_id,
            "message": response,
            "step": builder.state["step"],
            "draft_config": builder.state.get("draft_config")
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/builder/templates")
async def get_builder_templates() -> JSONResponse:
    """获取扩展类型模板信息"""
    return JSONResponse({
        "types": EXTENSION_TYPES
    })


@router.post("/builder/validate")
async def validate_config(request: Request) -> JSONResponse:
    """验证扩展配置"""
    try:
        body = await request.json()
        config = body.get("config", {})
        
        errors = []
        
        # 基本字段验证
        if not config.get("name"):
            errors.append("缺少扩展名称")
        if not config.get("type"):
            errors.append("缺少扩展类型")
        if config.get("type") not in EXTENSION_TYPES:
            errors.append(f"不支持的扩展类型: {config.get('type')}")
        
        # 类型特定验证
        ext_type = config.get("type")
        if ext_type == "prompt_template":
            if not config.get("config", {}).get("content"):
                errors.append("提示词模板缺少content字段")
        elif ext_type == "tool_chain":
            if not config.get("config", {}).get("tools"):
                errors.append("工具链缺少tools字段")
        elif ext_type == "workflow":
            if not config.get("config", {}).get("steps"):
                errors.append("工作流缺少steps字段")
        
        return JSONResponse({
            "valid": len(errors) == 0,
            "errors": errors
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)