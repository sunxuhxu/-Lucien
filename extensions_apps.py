# -*- coding: utf-8 -*-
"""AI 自定义扩展功能模块（extensions_apps.py）

提供三类用户自定义扩展，与现有 /chat 流兼容：
  1. prompt_template  —— 自定义提示词模板，按优先级注入 SYSTEM_PROMPT
  2. tool_chain       —— 自定义工具链集成（HTTP/时间/随机等白名单工具）
  3. workflow          —— 自定义工作流编排（多步骤串联：prompt → tool → condition → output）

设计要点：
  - 数据按 RolePath 隔离（owner 直存项目根，注册用户存 users_data/<user>/）
  - 工具链严格沙箱：仅白名单工具 + 域名白名单 + 超时/大小上限 + 内网地址拒绝
  - 工作流条件表达式走 AST 白名单 eval（仅允许比较/逻辑/算术 + 字面量 + 变量名）
  - 写操作需登录，注册用户只管理自己的扩展
  - prompt 模板由 /chat 调用 _build_extension_prompt_injection 注入

API：
  GET    /api/extensions                  列出扩展
  POST   /api/extensions                  创建扩展
  GET    /api/extensions/{ext_id}         查看单个
  PUT    /api/extensions/{ext_id}          更新
  DELETE /api/extensions/{ext_id}         删除
  POST   /api/extensions/{ext_id}/enable   启用
  POST   /api/extensions/{ext_id}/disable  禁用
  POST   /api/extensions/{ext_id}/test     测试运行
  PUT    /api/extensions/order             批量调整优先级
  GET    /api/extensions/templates        预设模板库
  GET    /api/extensions/tools            可用工具白名单
"""
import ast
import json
import operator as _op
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

EXT_FILE = "extensions.json"  # 由 RolePath 解析，按用户隔离


# ===========================================================================
# 工具白名单 & 沙箱
# ===========================================================================

# 允许 HTTP 工具访问的域名白名单（可扩展，默认开放常见公共 API）
HTTP_DOMAIN_WHITELIST = {
    "api.github.com",
    "api.openweathermap.org",
    "api.unsplash.com",
    "api.spotify.com",
    "api.douban.com",
    "api.bilibili.com",
    "www.googleapis.com",
    "api.weixin.qq.com",
    "api.thecatapi.com",
    "api.thedogapi.com",
    "api.nasa.gov",
    "quotable.io",
    "api.adviceslip.com",
    "api.catboy.rest",
    "www.bing.com",
    "api.zenquotes.io",
    "type.fit",
}

# 内网地址段（禁止访问，防 SSRF）
_PRIVATE_HOST_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|169\.254\.|0\.|"
    r"172\.(1[6-9]|2\d|3[01])\.|"
    r"::1|fc[0-9a-f]{2}:|fe80:|"
    r"localhost)",
    re.IGNORECASE,
)

# 工具类型 → 处理器
_SAFE_OPS = {
    # 比较
    ast.Eq: _op.eq, ast.NotEq: _op.ne,
    ast.Lt: _op.lt, ast.LtE: _op.le,
    ast.Gt: _op.gt, ast.GtE: _op.ge,
    ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b,
    ast.Is: _op.is_, ast.IsNot: _op.is_not,
    # 逻辑
    ast.And: lambda a, b: a and b, ast.Or: lambda a, b: a or b,
    ast.Not: _op.not_,
    # 算术
    ast.Add: _op.add, ast.Sub: _op.sub, ast.Mult: _op.mul,
    ast.Mod: _op.mod, ast.Pow: _op.pow,
    ast.USub: _op.neg, ast.UAdd: _op.pos,
    ast.FloorDiv: _op.floordiv,
}
_SAFE_FUNCS = {
    "len": len, "str": str, "int": int, "float": float, "bool": bool,
    "abs": abs, "min": min, "max": max, "round": round,
    "lower": str.lower, "upper": str.upper, "strip": str.strip,
    "contains": lambda a, b: b in a if hasattr(a, "__contains__") else False,
    "startswith": str.startswith, "endswith": str.endswith,
}


def _safe_eval(expr: str, ctx: Dict[str, Any]) -> Any:
    """受限表达式求值：AST 白名单（比较/逻辑/算术 + 字面量 + 变量 + 白名单函数）。

    任何调用 / 属性访问 / 导入 / 赋值都不允许。
    """
    if not expr or len(expr) > 2000:
        raise ValueError("表达式为空或超过 2000 字符")

    tree = ast.parse(expr, mode="eval")

    def _ev(node):
        if isinstance(node, ast.Expression):
            return _ev(node.body)
        if isinstance(node, ast.BoolOp):
            acc = _ev(node.values[0])
            for v in node.values[1:]:
                if isinstance(node.op, ast.And) and not acc:
                    return acc
                if isinstance(node.op, ast.Or) and acc:
                    return acc
                acc = _ev(v)
            return acc
        if isinstance(node, ast.BinOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op:
                raise ValueError(f"不支持的运算符：{type(node.op).__name__}")
            return op(_ev(node.left), _ev(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_OPS.get(type(node.op))
            if not op:
                raise ValueError(f"不支持的一元运算符：{type(node.op).__name__}")
            return op(_ev(node.operand))
        if isinstance(node, ast.Compare):
            left = _ev(node.left)
            for op_node, right_node in zip(node.ops, node.comparators):
                op = _SAFE_OPS.get(type(op_node))
                if not op:
                    raise ValueError(f"不支持的比较运算符：{type(op_node).__name__}")
                right = _ev(right_node)
                if not op(left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ctx:
                return ctx[node.id]
            if node.id in ("True", "true"):
                return True
            if node.id in ("False", "false"):
                return False
            if node.id in ("None", "null"):
                return None
            raise ValueError(f"未定义变量：{node.id}")
        if isinstance(node, ast.List):
            return [_ev(e) for e in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(_ev(e) for e in node.elts)
        if isinstance(node, ast.Dict):
            return {_ev(k): _ev(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError("仅支持直接调用白名单函数")
            fn = _SAFE_FUNCS.get(node.func.id)
            if not fn:
                raise ValueError(f"不允许调用的函数：{node.func.id}")
            args = [_ev(a) for a in node.args]
            return fn(*args)
        if isinstance(node, ast.Attribute):
            # 允许访问字符串方法：lower/upper/strip 等（通过白名单函数实现）
            raise ValueError(f"不允许的属性访问：{ast.dump(node)}")
        raise ValueError(f"不允许的表达式节点：{type(node).__name__}")

    return _ev(tree)


def _validate_http_url(url: str) -> Optional[str]:
    """校验 URL：必须 http(s)、域名白名单、禁止内网，返回错误信息或 None。"""
    if not isinstance(url, str) or not url:
        return "URL 为空"
    m = re.match(r"^https?://([^/]+)/?", url, re.IGNORECASE)
    if not m:
        return "URL 必须 http(s)://开头"
    host = m.group(1).split(":")[0].lower()
    if _PRIVATE_HOST_RE.match(host):
        return f"禁止访问内网地址：{host}"
    if host not in HTTP_DOMAIN_WHITELIST:
        return f"域名 {host} 不在白名单内（白名单：{', '.join(sorted(HTTP_DOMAIN_WHITELIST))}）"
    return None


async def _run_tool(tool: Dict[str, Any], ctx: Dict[str, Any]) -> Any:
    """执行单个白名单工具。

    ctx 是上下文（前序步骤的输出、用户输入等），可被工具引用。
    """
    t_type = (tool.get("type") or "").strip()
    params = tool.get("params") or {}

    if t_type == "time_now":
        fmt = params.get("format", "%Y-%m-%d %H:%M:%S")
        # 限制格式串长度，避免恶意构造
        if len(fmt) > 100:
            raise ValueError("time 格式过长")
        return datetime.now().strftime(fmt)

    if t_type == "random":
        lo = int(params.get("min", 0))
        hi = int(params.get("max", 100))
        if lo > hi:
            lo, hi = hi, lo
        import random as _r
        return _r.randint(lo, hi)

    if t_type == "echo":
        text = str(params.get("text", ""))
        # 支持 {{var}} 模板替换
        for k, v in ctx.items():
            text = text.replace("{{" + k + "}}", str(v))
        return text

    if t_type == "template":
        tmpl = str(params.get("template", ""))
        if len(tmpl) > 5000:
            raise ValueError("模板过长")
        out = tmpl
        for k, v in ctx.items():
            out = out.replace("{{" + k + "}}", str(v))
        return out

    if t_type == "http_get":
        url = str(params.get("url", ""))
        # URL 内变量替换
        for k, v in ctx.items():
            url = url.replace("{{" + k + "}}", str(v))
        err = _validate_http_url(url)
        if err:
            raise ValueError(err)
        headers = params.get("headers") or {}
        timeout = float(params.get("timeout", 10))
        if timeout > 15:
            timeout = 15
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.get(url, headers=headers)
            if len(resp.content) > 1024 * 1024:
                raise ValueError("HTTP 响应超过 1MB 上限")
            try:
                return resp.json()
            except Exception:
                return resp.text[:5000]

    if t_type == "http_post":
        url = str(params.get("url", ""))
        for k, v in ctx.items():
            url = url.replace("{{" + k + "}}", str(v))
        err = _validate_http_url(url)
        if err:
            raise ValueError(err)
        body = params.get("body")
        headers = params.get("headers") or {"Content-Type": "application/json"}
        timeout = float(params.get("timeout", 10))
        if timeout > 15:
            timeout = 15
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            resp = await client.post(url, json=body, headers=headers)
            if len(resp.content) > 1024 * 1024:
                raise ValueError("HTTP 响应超过 1MB 上限")
            try:
                return resp.json()
            except Exception:
                return resp.text[:5000]

    raise ValueError(f"未知的工具类型：{t_type}")


# ===========================================================================
# 工作流执行引擎
# ===========================================================================

async def _run_workflow(ext: Dict[str, Any], user_input: str = "") -> Dict[str, Any]:
    """执行工作流扩展，返回 {output, trace}。"""
    cfg = ext.get("config") or {}
    steps = cfg.get("steps") or []
    if not steps:
        raise ValueError("工作流未定义任何步骤")

    ctx: Dict[str, Any] = {"user_input": user_input, "input": user_input}
    trace: List[Dict[str, Any]] = []
    step_map = {s.get("id"): s for s in steps if s.get("id")}
    current = steps[0] if steps else None
    visited = set()
    safety_counter = 0
    MAX_STEPS = 30

    while current and safety_counter < MAX_STEPS:
        safety_counter += 1
        sid = current.get("id") or f"step_{safety_counter}"
        if sid in visited:
            trace.append({"step_id": sid, "error": "循环检测，已停止"})
            break
        visited.add(sid)

        stype = (current.get("type") or "").strip()
        scfg = current.get("config") or {}
        try:
            if stype == "prompt":
                tmpl = str(scfg.get("template", ""))
                if len(tmpl) > 8000:
                    raise ValueError("prompt 模板过长")
                out = tmpl
                for k, v in ctx.items():
                    out = out.replace("{{" + k + "}}", str(v))
                var_name = scfg.get("var") or sid
                ctx[var_name] = out
                trace.append({"step_id": sid, "type": "prompt", "output": out[:500]})
                current = step_map.get(current.get("next")) if current.get("next") else None

            elif stype == "tool":
                tool_cfg = scfg.get("tool") or scfg
                out = await _run_tool(tool_cfg, ctx)
                var_name = scfg.get("var") or sid
                ctx[var_name] = out
                trace.append({"step_id": sid, "type": "tool", "output_preview": str(out)[:500]})
                current = step_map.get(current.get("next")) if current.get("next") else None

            elif stype == "condition":
                expr = str(scfg.get("expr", ""))
                result = bool(_safe_eval(expr, ctx))
                trace.append({"step_id": sid, "type": "condition", "expr": expr, "result": result})
                next_id = current.get("next_true") if result else current.get("next_false")
                current = step_map.get(next_id) if next_id else None

            elif stype == "output":
                tmpl = str(scfg.get("template", ""))
                out = tmpl
                for k, v in ctx.items():
                    out = out.replace("{{" + k + "}}", str(v))
                trace.append({"step_id": sid, "type": "output", "output": out[:500]})
                return {"output": out, "trace": trace, "variables": {k: str(v)[:200] for k, v in ctx.items()}}
            else:
                raise ValueError(f"未知步骤类型：{stype}")
        except Exception as e:
            trace.append({"step_id": sid, "error": str(e)})
            return {"output": None, "trace": trace, "error": str(e), "variables": {k: str(v)[:200] for k, v in ctx.items()}}

    return {"output": None, "trace": trace, "variables": {k: str(v)[:200] for k, v in ctx.items()}}


# ===========================================================================
# 提示词模板注入：供 /chat 调用
# ===========================================================================

def _trigger_match(trigger: str, pattern: str, text: str) -> bool:
    """判断提示词模板是否应该触发。"""
    trigger = (trigger or "always").strip()
    if trigger == "always" or not text:
        return True
    if trigger == "keyword":
        if not pattern:
            return True
        # 多关键词用 , 分隔，任一命中即触发
        keywords = [k.strip() for k in pattern.split(",") if k.strip()]
        return any(k in text for k in keywords)
    if trigger == "regex":
        if not pattern:
            return True
        try:
            return bool(re.search(pattern, text))
        except re.error:
            return False
    return True


def build_prompt_injection(user_text: str = "") -> str:
    """供 /chat 调用：按优先级收集所有启用的 prompt_template 扩展并拼接。

    返回注入到 SYSTEM_PROMPT 后面的字符串（已含分隔符）；无扩展返回空串。
    """
    try:
        data = _load_extensions()
    except Exception:
        return ""
    exts = [e for e in data.get("extensions", [])
            if e.get("enabled") and e.get("type") == "prompt_template"]
    # priority 小 = 优先级高（更靠前注入）
    exts.sort(key=lambda e: (int(e.get("priority", 100)), e.get("created_at", "")))

    parts: List[str] = []
    for ext in exts:
        cfg = ext.get("config") or {}
        trigger = cfg.get("trigger", "always")
        pattern = cfg.get("trigger_pattern", "")
        if not _trigger_match(trigger, pattern, user_text):
            continue
        content = (cfg.get("content") or "").strip()
        if not content:
            continue
        pos = (cfg.get("inject_position") or "system_suffix").strip()
        marker = f"[扩展·{ext.get('name', '未命名')}]"
        parts.append({"pos": pos, "text": f"\n\n{marker}\n{content}\n"})

    if not parts:
        return ""

    prefix_parts = [p["text"] for p in parts if p["pos"] == "system_prefix"]
    suffix_parts = [p["text"] for p in parts if p["pos"] != "system_prefix"]
    out = ""
    if prefix_parts:
        out += "\n\n【AI 扩展·前置提示词】" + "".join(prefix_parts)
    if suffix_parts:
        out += "\n\n【AI 扩展·提示词】" + "".join(suffix_parts)
    return out


async def run_tool_chain_async(ext: Dict[str, Any], user_text: str) -> Optional[str]:
    """供 /chat 调用：执行工具链扩展，返回结果字符串（失败返回 None）。"""
    cfg = ext.get("config") or {}
    trigger = cfg.get("trigger", "always")
    pattern = cfg.get("trigger_pattern", "")
    if not _trigger_match(trigger, pattern, user_text):
        return None
    tools = cfg.get("tools") or []
    if not tools:
        return None
    ctx = {"user_input": user_text, "input": user_text}
    results = []
    for i, tool in enumerate(tools):
        try:
            out = await _run_tool(tool, ctx)
            ctx[f"step_{i+1}"] = out
            ctx[tool.get("name") or f"tool_{i+1}"] = out
            results.append(out)
        except Exception as e:
            results.append({"error": str(e)})
            break
    # 拼接最终结果
    fmt = cfg.get("output_format", "json")
    if fmt == "raw":
        return "\n".join(str(r) for r in results)
    if fmt == "last":
        return str(results[-1]) if results else ""
    return json.dumps(results, ensure_ascii=False, indent=2)[:2000]


# ===========================================================================
# 存储
# ===========================================================================

def _load_extensions() -> Dict[str, Any]:
    """加载当前角色的扩展配置。"""
    p = RolePath(EXT_FILE)
    if not p.exists():
        return {"extensions": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("extensions"), list):
            return {"extensions": []}
        return data
    except (json.JSONDecodeError, OSError):
        return {"extensions": []}


def _save_extensions(data: Dict[str, Any]) -> None:
    p = RolePath(EXT_FILE)
    with file_lock(p):
        atomic_json(p, data)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _public_view(ext: Dict[str, Any]) -> Dict[str, Any]:
    """对外视图：剥离敏感字段（虽然本模块不存敏感数据，统一接口）。"""
    return dict(ext)


# ===========================================================================
# 配置校验
# ===========================================================================

_VALID_TYPES = {"prompt_template", "tool_chain", "workflow"}
_VALID_TRIGGERS = {"always", "keyword", "regex"}
_VALID_INJECT_POS = {"system_prefix", "system_suffix", "user_prefix"}
_VALID_TOOL_TYPES = {"time_now", "random", "echo", "template", "http_get", "http_post"}
_VALID_STEP_TYPES = {"prompt", "tool", "condition", "output"}
_VALID_OUTPUT_FMT = {"json", "raw", "last"}


def _validate_extension(ext: Dict[str, Any], is_create: bool = False) -> Optional[str]:
    """校验扩展配置，返回错误信息或 None。"""
    if not isinstance(ext, dict):
        return "扩展配置必须是对象"

    # 名称
    name = (ext.get("name") or "").strip()
    if not name:
        return "扩展名称不能为空"
    if len(name) > 40:
        return "扩展名称最长 40 字符"

    # 类型
    etype = (ext.get("type") or "").strip()
    if etype not in _VALID_TYPES:
        return f"扩展类型必须是 {', '.join(sorted(_VALID_TYPES))} 之一"

    # 优先级
    try:
        priority = int(ext.get("priority", 100))
        if priority < 0 or priority > 999:
            return "优先级必须是 0-999 之间的整数"
    except (TypeError, ValueError):
        return "优先级必须是整数"

    # 启用状态
    if "enabled" in ext and not isinstance(ext["enabled"], bool):
        return "enabled 必须是布尔值"

    # 描述
    desc = ext.get("description", "")
    if not isinstance(desc, str) or len(desc) > 200:
        return "描述最长 200 字符"

    # 配置
    cfg = ext.get("config")
    if cfg is not None and not isinstance(cfg, dict):
        return "config 必须是对象"

    if etype == "prompt_template":
        if not isinstance(cfg, dict):
            return "prompt_template 必须包含 config"
        trigger = cfg.get("trigger", "always")
        if trigger not in _VALID_TRIGGERS:
            return f"trigger 必须是 {', '.join(sorted(_VALID_TRIGGERS))} 之一"
        if trigger != "always" and not (cfg.get("trigger_pattern") or "").strip():
            return f"trigger={trigger} 必须提供 trigger_pattern"
        if trigger == "regex":
            try:
                re.compile(cfg.get("trigger_pattern", ""))
            except re.error as e:
                return f"trigger_pattern 正则编译失败：{e}"
        content = cfg.get("content", "")
        if not isinstance(content, str):
            return "content 必须是字符串"
        if len(content) > 8000:
            return "content 最长 8000 字符"
        pos = cfg.get("inject_position", "system_suffix")
        if pos not in _VALID_INJECT_POS:
            return f"inject_position 必须是 {', '.join(sorted(_VALID_INJECT_POS))} 之一"

    elif etype == "tool_chain":
        if not isinstance(cfg, dict):
            return "tool_chain 必须包含 config"
        tools = cfg.get("tools")
        if not isinstance(tools, list) or not tools:
            return "tool_chain 必须包含至少一个 tool"
        if len(tools) > 10:
            return "工具链最多 10 个工具"
        for i, tool in enumerate(tools):
            if not isinstance(tool, dict):
                return f"tool[{i}] 必须是对象"
            t_type = (tool.get("type") or "").strip()
            if t_type not in _VALID_TOOL_TYPES:
                return f"tool[{i}].type 必须是 {', '.join(sorted(_VALID_TOOL_TYPES))} 之一"
            params = tool.get("params")
            if params is not None and not isinstance(params, dict):
                return f"tool[{i}].params 必须是对象"
            # http_* 提前校验 URL 域名白名单（静态可校验的部分）
            if t_type in ("http_get", "http_post"):
                url = (params or {}).get("url", "")
                if "{{" in url:
                    continue  # 含变量替换的，运行时再校验
                err = _validate_http_url(url)
                if err:
                    return f"tool[{i}].url: {err}"
        fmt = cfg.get("output_format", "json")
        if fmt not in _VALID_OUTPUT_FMT:
            return f"output_format 必须是 {', '.join(sorted(_VALID_OUTPUT_FMT))} 之一"

    elif etype == "workflow":
        if not isinstance(cfg, dict):
            return "workflow 必须包含 config"
        steps = cfg.get("steps")
        if not isinstance(steps, list) or not steps:
            return "workflow 必须包含至少一个 step"
        if len(steps) > 30:
            return "工作流最多 30 个步骤"
        ids = set()
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                return f"step[{i}] 必须是对象"
            sid = step.get("id")
            if not sid:
                return f"step[{i}].id 不能为空"
            if sid in ids:
                return f"step[{i}].id 重复：{sid}"
            ids.add(sid)
            stype = (step.get("type") or "").strip()
            if stype not in _VALID_STEP_TYPES:
                return f"step[{i}].type 必须是 {', '.join(sorted(_VALID_STEP_TYPES))} 之一"
            if stype == "condition":
                expr = (step.get("config") or {}).get("expr", "")
                if not expr:
                    return f"step[{i}] condition 必须提供 expr"
                # 提前校验表达式语法
                try:
                    _safe_eval(expr, {"user_input": "test", "input": "test"})
                except Exception as e:
                    return f"step[{i}] 表达式校验失败：{e}"
        # 校验 next 跳转目标存在
        for i, step in enumerate(steps):
            for next_field in ("next", "next_true", "next_false"):
                next_id = step.get(next_field)
                if next_id and next_id not in ids:
                    return f"step[{i}].{next_field}={next_id} 不存在于步骤列表"
        # 必须有 output 步骤
        if not any(s.get("type") == "output" for s in steps):
            return "workflow 必须至少包含一个 output 步骤"

    return None


# ===========================================================================
# API 路由
# ===========================================================================

@router.get("/api/extensions")
async def list_extensions():
    """列出当前角色的所有扩展，按优先级排序。"""
    data = _load_extensions()
    exts = data.get("extensions", [])
    exts.sort(key=lambda e: (int(e.get("priority", 100)), e.get("created_at", "")))
    return {"extensions": [_public_view(e) for e in exts]}


@router.post("/api/extensions")
async def create_extension(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "请求体必须是对象"}, status_code=400)

    ext = {
        "id": _new_id(),
        "name": body.get("name", "").strip(),
        "type": body.get("type", "").strip(),
        "description": body.get("description", "").strip(),
        "enabled": bool(body.get("enabled", False)),
        "priority": int(body.get("priority", 100)),
        "config": body.get("config") or {},
        "created_at": _now(),
        "updated_at": _now(),
    }
    err = _validate_extension(ext, is_create=True)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    data = _load_extensions()
    # 限制每个角色最多 50 个扩展
    if len(data.get("extensions", [])) >= 50:
        return JSONResponse({"error": "扩展数量已达上限（50 个）"}, status_code=400)
    data["extensions"].append(ext)
    _save_extensions(data)
    return _public_view(ext)


@router.get("/api/extensions/{ext_id}")
async def get_extension(ext_id: str):
    data = _load_extensions()
    for ext in data.get("extensions", []):
        if ext.get("id") == ext_id:
            return _public_view(ext)
    return JSONResponse({"error": "扩展不存在"}, status_code=404)


@router.put("/api/extensions/{ext_id}")
async def update_extension(ext_id: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "请求体必须是对象"}, status_code=400)

    data = _load_extensions()
    target = None
    for ext in data.get("extensions", []):
        if ext.get("id") == ext_id:
            target = ext
            break
    if target is None:
        return JSONResponse({"error": "扩展不存在"}, status_code=404)

    # 仅允许更新这些字段
    for k in ("name", "description", "type", "enabled", "priority", "config"):
        if k in body:
            target[k] = body[k]
    target["updated_at"] = _now()

    err = _validate_extension(target)
    if err:
        return JSONResponse({"error": err}, status_code=400)
    _save_extensions(data)
    return _public_view(target)


@router.delete("/api/extensions/{ext_id}")
async def delete_extension(ext_id: str):
    data = _load_extensions()
    before = len(data.get("extensions", []))
    data["extensions"] = [e for e in data.get("extensions", []) if e.get("id") != ext_id]
    if len(data["extensions"]) == before:
        return JSONResponse({"error": "扩展不存在"}, status_code=404)
    _save_extensions(data)
    return {"ok": True}


@router.post("/api/extensions/{ext_id}/enable")
async def enable_extension(ext_id: str):
    data = _load_extensions()
    for ext in data.get("extensions", []):
        if ext.get("id") == ext_id:
            ext["enabled"] = True
            ext["updated_at"] = _now()
            _save_extensions(data)
            return _public_view(ext)
    return JSONResponse({"error": "扩展不存在"}, status_code=404)


@router.post("/api/extensions/{ext_id}/disable")
async def disable_extension(ext_id: str):
    data = _load_extensions()
    for ext in data.get("extensions", []):
        if ext.get("id") == ext_id:
            ext["enabled"] = False
            ext["updated_at"] = _now()
            _save_extensions(data)
            return _public_view(ext)
    return JSONResponse({"error": "扩展不存在"}, status_code=404)


@router.put("/api/extensions/order")
async def reorder_extensions(req: Request):
    """批量调整优先级。请求体：{order: ["id1", "id2", ...]}。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    order = body.get("order") if isinstance(body, dict) else None
    if not isinstance(order, list):
        return JSONResponse({"error": "order 必须是数组"}, status_code=400)

    data = _load_extensions()
    exts = data.get("extensions", [])
    # 按给定顺序重排，未出现在 order 中的保持原顺序追加在后
    order_map = {eid: idx for idx, eid in enumerate(order)}
    exts.sort(key=lambda e: order_map.get(e.get("id"), 999999))
    # 按 order 顺序重新赋值 priority（10, 20, 30, ...），保留 10 的步长便于后续插入
    for i, ext in enumerate(exts):
        ext["priority"] = (i + 1) * 10
        ext["updated_at"] = _now()
    _save_extensions(data)
    return {"extensions": [_public_view(e) for e in exts]}


@router.post("/api/extensions/{ext_id}/test")
async def test_extension(ext_id: str, req: Request):
    """测试运行扩展，返回执行结果与 trace。

    请求体可选 {user_input: "..."}。
    """
    try:
        body = await req.json() if req.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    user_input = str(body.get("user_input", ""))[:500]

    data = _load_extensions()
    ext = None
    for e in data.get("extensions", []):
        if e.get("id") == ext_id:
            ext = e
            break
    if ext is None:
        return JSONResponse({"error": "扩展不存在"}, status_code=404)

    etype = ext.get("type")
    try:
        if etype == "prompt_template":
            injection = build_prompt_injection(user_input)
            return {
                "ok": True,
                "type": "prompt_template",
                "injection": injection,
                "note": "以下是会注入到 SYSTEM_PROMPT 的内容（已合并所有启用的同类扩展）",
            }
        if etype == "tool_chain":
            # 测试时无视 enabled 状态
            result = await run_tool_chain_async(ext, user_input)
            return {"ok": True, "type": "tool_chain", "result": result, "user_input": user_input}
        if etype == "workflow":
            result = await _run_workflow(ext, user_input)
            return {"ok": True, "type": "workflow", "result": result, "user_input": user_input}
        return JSONResponse({"error": f"未知扩展类型：{etype}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


@router.get("/api/extensions/templates")
async def get_templates():
    """返回预设扩展模板，让用户一键创建。"""
    return {"templates": _PRESET_TEMPLATES}


@router.get("/api/extensions/tools")
async def get_tools_info():
    """返回可用工具白名单与说明，供前端展示。"""
    return {
        "tool_types": [
            {
                "type": "time_now",
                "name": "当前时间",
                "description": "返回当前时间字符串",
                "params": {"format": "时间格式（strftime）"},
            },
            {
                "type": "random",
                "name": "随机数",
                "description": "返回 [min, max] 之间的整数",
                "params": {"min": "int", "max": "int"},
            },
            {
                "type": "echo",
                "name": "原样返回",
                "description": "原样返回输入文本，支持 {{var}} 替换",
                "params": {"text": "字符串"},
            },
            {
                "type": "template",
                "name": "模板渲染",
                "description": "字符串模板，支持 {{var}} 上下文替换",
                "params": {"template": "字符串"},
            },
            {
                "type": "http_get",
                "name": "HTTP GET",
                "description": "向白名单域名发起 GET 请求（10s 超时，响应 ≤1MB）",
                "params": {"url": "URL", "headers": "dict", "timeout": "秒"},
            },
            {
                "type": "http_post",
                "name": "HTTP POST",
                "description": "向白名单域名发起 POST 请求（同上限制）",
                "params": {"url": "URL", "body": "dict", "headers": "dict", "timeout": "秒"},
            },
        ],
        "http_domain_whitelist": sorted(HTTP_DOMAIN_WHITELIST),
        "step_types": [
            {"type": "prompt", "name": "生成提示词", "description": "渲染字符串模板，结果存入上下文变量"},
            {"type": "tool", "name": "调用工具", "description": "调用白名单工具，结果存入上下文变量"},
            {"type": "condition", "name": "条件分支", "description": "AST 白名单表达式，根据结果跳转 next_true / next_false"},
            {"type": "output", "name": "输出结果", "description": "渲染输出模板并结束工作流"},
        ],
        "triggers": [
            {"value": "always", "name": "始终触发"},
            {"value": "keyword", "name": "关键词命中（任一）"},
            {"value": "regex", "name": "正则匹配"},
        ],
        "inject_positions": [
            {"value": "system_prefix", "name": "系统提示词前置"},
            {"value": "system_suffix", "name": "系统提示词后置（默认）"},
            {"value": "user_prefix", "name": "用户消息前置"},
        ],
        "limits": {
            "max_extensions_per_role": 50,
            "max_tools_per_chain": 10,
            "max_steps_per_workflow": 30,
            "max_prompt_length": 8000,
            "http_timeout_seconds": 15,
            "http_max_response_bytes": 1048576,
        },
    }


# ===========================================================================
# 预设模板
# ===========================================================================

_PRESET_TEMPLATES = [
    {
        "name": "学术风语气强化",
        "type": "prompt_template",
        "description": "让许墨回答时多用学术术语与科研隐喻",
        "enabled": False,
        "priority": 10,
        "config": {
            "trigger": "always",
            "trigger_pattern": "",
            "inject_position": "system_suffix",
            "content": "在回答中适当使用脑科学/认知科学术语与隐喻（如「神经可塑性」「多巴胺回路」「镜像神经元」），让对话保持学术质感，但不要堆砌到让普通人听不懂。",
        },
    },
    {
        "name": "深夜模式",
        "type": "prompt_template",
        "description": "夜间 22:00 后语气更柔软低沉",
        "enabled": False,
        "priority": 20,
        "config": {
            "trigger": "regex",
            "trigger_pattern": "(?i)(睡不着|失眠|晚安|陪我|夜里|深夜)",
            "inject_position": "system_suffix",
            "content": "现在是深夜，请把语气放得更柔软、更低沉一些，多用「嗯」「我在」这类短句回应，偶尔流露一点「我也睡不着，刚好在想你」的温柔。",
        },
    },
    {
        "name": "天气查询工具链",
        "type": "tool_chain",
        "description": "用户问及天气时调用 OpenWeather 获取实时数据",
        "enabled": False,
        "priority": 30,
        "config": {
            "trigger": "keyword",
            "trigger_pattern": "天气,气温,下雨,温度",
            "output_format": "json",
            "tools": [
                {
                    "type": "http_get",
                    "name": "weather",
                    "params": {
                        "url": "https://api.openweathermap.org/data/2.5/weather?q=Beijing&appid=YOUR_API_KEY&units=metric&lang=zh_cn",
                        "timeout": 10,
                    },
                },
            ],
        },
    },
    {
        "name": "每日金句工具链",
        "type": "tool_chain",
        "description": "调用 quotable.io 获取一句随机励志语",
        "enabled": False,
        "priority": 40,
        "config": {
            "trigger": "keyword",
            "trigger_pattern": "金句,励志,鼓励,一句话",
            "output_format": "raw",
            "tools": [
                {
                    "type": "http_get",
                    "name": "quote",
                    "params": {"url": "https://api.quotable.io/random", "timeout": 8},
                },
            ],
        },
    },
    {
        "name": "心情记录工作流",
        "type": "workflow",
        "description": "接收用户心情描述 → 渲染提示词 → 输出许墨的回应建议",
        "enabled": False,
        "priority": 50,
        "config": {
            "steps": [
                {
                    "id": "s1",
                    "type": "prompt",
                    "config": {
                        "var": "mood_prompt",
                        "template": "用户描述了此刻的心情：「{{user_input}}」。请以许墨的口吻，用温柔且带一点学术距离感的方式回应。",
                    },
                    "next": "s2",
                },
                {
                    "id": "s2",
                    "type": "output",
                    "config": {"template": "{{mood_prompt}}"},
                },
            ],
        },
    },
    {
        "name": "条件分支示例工作流",
        "type": "workflow",
        "description": "根据用户输入长度选择不同的提示词路径",
        "enabled": False,
        "priority": 60,
        "config": {
            "steps": [
                {
                    "id": "s1",
                    "type": "condition",
                    "config": {"expr": "len(user_input) > 30"},
                    "next_true": "s2_long",
                    "next_false": "s2_short",
                },
                {
                    "id": "s2_long",
                    "type": "prompt",
                    "config": {
                        "var": "advice",
                        "template": "用户说了比较长的话：{{user_input}}。请认真回应每一个细节。",
                    },
                    "next": "s3",
                },
                {
                    "id": "s2_short",
                    "type": "prompt",
                    "config": {
                        "var": "advice",
                        "template": "用户说得很简短：{{user_input}}。请用温柔短句回应。",
                    },
                    "next": "s3",
                },
                {
                    "id": "s3",
                    "type": "output",
                    "config": {"template": "{{advice}}"},
                },
            ],
        },
    },
]


# ===========================================================================
# 自然语言生成扩展功能
# ===========================================================================

@router.post("/generate")
async def generate_extension_from_natural_language(request: Request) -> JSONResponse:
    """通过自然语言描述生成扩展配置"""
    try:
        body = await request.json()
        description = body.get("description", "")
        user_id = body.get("user_id", "owner")
        
        if not description or len(description) < 10:
            return JSONResponse({"error": "描述太短，请提供更详细的需求"}, status_code=400)
        
        # 解析自然语言描述
        generated_config = _parse_natural_language_description(description)
        
        # 添加元数据
        generated_config["id"] = str(uuid.uuid4())
        generated_config["created_at"] = datetime.now().isoformat()
        generated_config["updated_at"] = datetime.now().isoformat()
        generated_config["enabled"] = True
        
        return JSONResponse({
            "success": True,
            "config": generated_config,
            "suggestions": _get_config_suggestions(generated_config)
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _parse_natural_language_description(description: str) -> Dict:
    """解析自然语言描述，生成扩展配置"""
    description_lower = description.lower()
    
    # 判断扩展类型
    ext_type = _detect_extension_type(description_lower)
    
    if ext_type == "prompt_template":
        return _generate_prompt_from_description(description)
    elif ext_type == "tool_chain":
        return _generate_toolchain_from_description(description)
    elif ext_type == "workflow":
        return _generate_workflow_from_description(description)
    else:
        # 默认生成提示词模板
        return _generate_prompt_from_description(description)


def _detect_extension_type(description: str) -> str:
    """根据描述检测扩展类型"""
    type_scores = {
        "prompt_template": 0,
        "tool_chain": 0,
        "workflow": 0
    }
    
    # 提示词模板关键词
    prompt_keywords = ["语气", "说话", "风格", "回答", "性格", "人设", "模板", "提示词", "说话方式", "口吻"]
    for keyword in prompt_keywords:
        if keyword in description:
            type_scores["prompt_template"] += 1
    
    # 工具链关键词
    tool_keywords = ["api", "天气", "新闻", "翻译", "调用", "外部", "数据", "查询", "工具", "获取", "请求"]
    for keyword in tool_keywords:
        if keyword in description:
            type_scores["tool_chain"] += 1
    
    # 工作流关键词
    workflow_keywords = ["步骤", "流程", "工作流", "任务", "多步骤", "分支", "条件", "编排", "然后", "接着", "最后"]
    for keyword in workflow_keywords:
        if keyword in description:
            type_scores["workflow"] += 1
    
    # 返回得分最高的类型
    return max(type_scores, key=type_scores.get)


def _generate_prompt_from_description(description: str) -> Dict:
    """从描述生成提示词模板配置"""
    # 提取触发条件
    trigger = "always"
    trigger_pattern = ""
    
    if any(keyword in description for keyword in ["当", "如果", "遇到", "关键词"]):
        trigger = "keyword"
        # 简单提取可能的触发词
        if "天气" in description:
            trigger_pattern = "天气,气温,下雨"
        elif "时间" in description or "深夜" in description:
            trigger_pattern = "深夜,晚上,夜间"
        elif "心情" in description:
            trigger_pattern = "心情,难过,开心"
        else:
            # 提取中文词汇作为触发词
            words = re.findall(r'[\u4e00-\u9fff]+', description)
            trigger_pattern = ",".join(words[:3]) if words else ""
    
    # 生成提示词内容
    content = description
    
    # 智能优化提示词
    if "温柔" in description:
        content += " 请用温柔、体贴的语气回应，多用简短的关心语句。"
    elif "学术" in description or "专业" in description:
        content += " 请适当使用学术术语和专业知识，保持专业但平易近人的风格。"
    elif "幽默" in description:
        content += " 请适当加入幽默元素，让对话更加轻松有趣。"
    
    return {
        "name": f"AI生成-{_extract_name_from_description(description)}",
        "type": "prompt_template",
        "description": description[:100],
        "enabled": True,
        "priority": 10,
        "config": {
            "trigger": trigger,
            "trigger_pattern": trigger_pattern,
            "inject_position": "system_suffix",
            "content": content
        }
    }


def _generate_toolchain_from_description(description: str) -> Dict:
    """从描述生成工具链配置"""
    # 检测API类型
    tool_type = "http_get"
    url = ""
    tool_name = "custom_api"
    
    if "天气" in description:
        url = "https://api.openweathermap.org/data/2.5/weather?q=Beijing&appid=YOUR_API_KEY&units=metric&lang=zh_cn"
        tool_name = "weather_api"
    elif "新闻" in description:
        url = "https://newsapi.org/v2/top-headlines?country=cn&apiKey=YOUR_API_KEY"
        tool_name = "news_api"
    elif "翻译" in description:
        url = "https://api.mymemory.translated.net/get?q={{user_input}}&langpair=en|zh"
        tool_name = "translation_api"
    elif "quote" in description or "语录" in description:
        url = "https://api.quotable.io/random"
        tool_name = "quote_api"
    else:
        # 通用API模板
        url = "https://api.example.com/endpoint"
        tool_name = "custom_api"
    
    # 提取触发条件
    trigger_pattern = ""
    if "天气" in description:
        trigger_pattern = "天气,气温,下雨,温度"
    elif "新闻" in description:
        trigger_pattern = "新闻,资讯,头条"
    elif "翻译" in description:
        trigger_pattern = "翻译,英文,中文"
    else:
        words = re.findall(r'[\u4e00-\u9fff]+', description)
        trigger_pattern = ",".join(words[:3]) if words else ""
    
    return {
        "name": f"AI生成-{_extract_name_from_description(description)}",
        "type": "tool_chain",
        "description": description[:100],
        "enabled": True,
        "priority": 20,
        "config": {
            "trigger": "keyword",
            "trigger_pattern": trigger_pattern,
            "output_format": "json",
            "tools": [
                {
                    "type": tool_type,
                    "name": tool_name,
                    "params": {
                        "url": url,
                        "timeout": 10
                    }
                }
            ]
        }
    }


def _generate_workflow_from_description(description: str) -> Dict:
    """从描述生成工作流配置"""
    # 简单解析步骤
    steps = []
    
    # 按照常见的连接词分割步骤
    step_markers = ["然后", "接着", "之后", "最后", "，", ","]
    step_parts = [description]
    
    for marker in step_markers:
        new_parts = []
        for part in step_parts:
            new_parts.extend(part.split(marker))
        step_parts = new_parts
    
    step_parts = [p.strip() for p in step_parts if p.strip()]
    
    # 限制步骤数量，避免过于复杂
    step_parts = step_parts[:5]
    
    for i, part in enumerate(step_parts):
        step_id = f"s{i+1}"
        
        if i == 0:
            # 第一步：输入处理
            steps.append({
                "id": step_id,
                "type": "prompt",
                "config": {
                    "var": f"input_{i}",
                    "template": f"{part}：{{{{user_input}}}}"
                },
                "next": f"s{i+2}" if i < len(step_parts) - 1 else "final"
            })
        elif i == len(step_parts) - 1:
            # 最后一步：输出
            steps.append({
                "id": step_id,
                "type": "output",
                "config": {
                    "template": "{{input_0}}"
                }
            })
        else:
            # 中间步骤
            steps.append({
                "id": step_id,
                "type": "prompt",
                "config": {
                    "var": f"var_{i}",
                    "template": part
                },
                "next": f"s{i+2}" if i < len(step_parts) - 1 else "final"
            })
    
    return {
        "name": f"AI生成-{_extract_name_from_description(description)}",
        "type": "workflow",
        "description": description[:100],
        "enabled": True,
        "priority": 30,
        "config": {
            "steps": steps
        }
    }


def _extract_name_from_description(description: str) -> str:
    """从描述中提取简短名称"""
    # 提取前几个中文字符作为名称
    chinese_chars = re.findall(r'[\u4e00-\u9fff]', description)
    if chinese_chars:
        return "".join(chinese_chars[:6])
    # 如果没有中文字符，使用英文单词
    english_words = re.findall(r'[a-zA-Z]+', description)
    if english_words:
        return "_".join(english_words[:3])
    return "custom_extension"


def _get_config_suggestions(config: Dict) -> List[str]:
    """获取配置改进建议"""
    suggestions = []
    
    ext_type = config.get("type")
    
    if ext_type == "prompt_template":
        content = config.get("config", {}).get("content", "")
        if len(content) < 20:
            suggestions.append("提示词内容较短，建议添加更多具体指导")
        if "天气" in content or "时间" in content:
            suggestions.append("建议考虑使用工具链来获取实时数据")
    
    elif ext_type == "tool_chain":
        tools = config.get("config", {}).get("tools", [])
        if not tools:
            suggestions.append("工具链缺少工具配置")
        else:
            for tool in tools:
                if "YOUR_API_KEY" in str(tool.get("params", {})):
                    suggestions.append("请记得替换API密钥为实际值")
    
    elif ext_type == "workflow":
        steps = config.get("config", {}).get("steps", [])
        if len(steps) < 2:
            suggestions.append("工作流步骤较少，考虑添加更多步骤")
        if len(steps) > 5:
            suggestions.append("工作流步骤较多，建议简化以提高性能")
    
    if not suggestions:
        suggestions.append("配置看起来不错，可以直接保存使用")
    
    return suggestions


# ===========================================================================
# 扩展导入导出和分享功能
# ===========================================================================

@router.get("/api/extensions/export")
async def export_extensions(request: Request) -> JSONResponse:
    """导出所有扩展为JSON文件"""
    try:
        # 获取当前用户信息
        user_id = request.query_params.get("user_id", "owner")
        role_path = RolePath(user_id)
        ext_file = role_path.resolve("extensions.json", enforce_user_scope=True)
        
        # 读取扩展数据
        try:
            with file_lock(ext_file, "r"):
                data = atomic_json(ext_file)
        except:
            data = {"extensions": [], "order": []}
        
        # 添加导出元数据
        export_data = {
            "version": "1.0",
            "exported_at": datetime.now().isoformat(),
            "user_id": user_id,
            "extensions": data.get("extensions", []),
            "order": data.get("order", [])
        }
        
        return JSONResponse(export_data)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/extensions/import")
async def import_extensions(request: Request) -> JSONResponse:
    """导入扩展JSON文件"""
    try:
        body = await request.json()
        import_data = body.get("data", {})
        user_id = body.get("user_id", "owner")
        
        # 验证导入数据格式
        if "extensions" not in import_data:
            return JSONResponse({"error": "导入数据格式错误：缺少extensions字段"}, status_code=400)
        
        role_path = RolePath(user_id)
        ext_file = role_path.resolve("extensions.json", enforce_user_scope=True)
        
        # 读取现有扩展
        try:
            with file_lock(ext_file, "r"):
                existing_data = atomic_json(ext_file)
        except:
            existing_data = {"extensions": [], "order": []}
        
        # 合并扩展
        imported_count = 0
        for ext in import_data.get("extensions", []):
            # 生成新的ID避免冲突
            ext["id"] = str(uuid.uuid4())
            ext["created_at"] = datetime.now().isoformat()
            ext["updated_at"] = datetime.now().isoformat()
            
            # 检查是否已存在同名扩展
            existing_names = {e["name"] for e in existing_data["extensions"]}
            if ext["name"] in existing_names:
                ext["name"] = f"{ext['name']}_imported"
            
            existing_data["extensions"].append(ext)
            existing_data["order"].append(ext["id"])
            imported_count += 1
        
        # 保存
        with file_lock(ext_file, "w"):
            atomic_json(ext_file, existing_data)
        
        return JSONResponse({
            "success": True,
            "imported_count": imported_count,
            "message": f"成功导入 {imported_count} 个扩展"
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/extensions/{ext_id}/share")
async def get_extension_share_code(ext_id: str, request: Request) -> JSONResponse:
    """生成扩展分享码"""
    try:
        user_id = request.query_params.get("user_id", "owner")
        role_path = RolePath(user_id)
        ext_file = role_path.resolve("extensions.json", enforce_user_scope=True)
        
        # 读取扩展数据
        with file_lock(ext_file, "r"):
            data = atomic_json(ext_file)
        
        # 查找指定扩展
        extension = None
        for ext in data.get("extensions", []):
            if ext.get("id") == ext_id:
                extension = ext
                break
        
        if not extension:
            return JSONResponse({"error": "扩展不存在"}, status_code=404)
        
        # 生成分享码（简化版：使用base64编码的JSON）
        import base64
        share_data = {
            "name": extension["name"],
            "type": extension["type"],
            "description": extension["description"],
            "config": extension["config"],
            "version": "1.0"
        }
        
        share_json = json.dumps(share_data, ensure_ascii=False)
        share_code = base64.b64encode(share_json.encode("utf-8")).decode("utf-8")
        
        return JSONResponse({
            "share_code": share_code,
            "extension_name": extension["name"],
            "extension_type": extension["type"]
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/extensions/import/share")
async def import_from_share_code(request: Request) -> JSONResponse:
    """通过分享码导入扩展"""
    try:
        body = await request.json()
        share_code = body.get("share_code", "")
        user_id = body.get("user_id", "owner")
        
        if not share_code:
            return JSONResponse({"error": "分享码不能为空"}, status_code=400)
        
        # 解码分享码
        import base64
        try:
            share_json = base64.b64decode(share_code.encode("utf-8")).decode("utf-8")
            share_data = json.loads(share_json)
        except Exception as e:
            return JSONResponse({"error": "分享码格式错误"}, status_code=400)
        
        # 验证分享数据
        required_fields = ["name", "type", "config"]
        for field in required_fields:
            if field not in share_data:
                return JSONResponse({"error": f"分享数据缺少{field}字段"}, status_code=400)
        
        # 创建扩展
        role_path = RolePath(user_id)
        ext_file = role_path.resolve("extensions.json", enforce_user_scope=True)
        
        # 读取现有扩展
        try:
            with file_lock(ext_file, "r"):
                existing_data = atomic_json(ext_file)
        except:
            existing_data = {"extensions": [], "order": []}
        
        # 检查名称冲突
        existing_names = {e["name"] for e in existing_data["extensions"]}
        base_name = share_data["name"]
        if base_name in existing_names:
            share_data["name"] = f"{base_name}_shared"
        
        # 添加扩展
        new_extension = {
            "id": str(uuid.uuid4()),
            "name": share_data["name"],
            "type": share_data["type"],
            "description": share_data.get("description", "从分享码导入"),
            "enabled": True,
            "priority": 10,
            "config": share_data["config"],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        existing_data["extensions"].append(new_extension)
        existing_data["order"].append(new_extension["id"])
        
        # 保存
        with file_lock(ext_file, "w"):
            atomic_json(ext_file, existing_data)
        
        return JSONResponse({
            "success": True,
            "extension": new_extension,
            "message": f"成功导入扩展：{new_extension['name']}"
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/extensions/marketplace")
async def get_extension_marketplace(request: Request) -> JSONResponse:
    """获取扩展市场（预设分享扩展）"""
    try:
        # 这里是预设的扩展市场，实际应用中可以从服务器获取
        marketplace_extensions = [
            {
                "id": "market_001",
                "name": "学术风语气强化",
                "type": "prompt_template",
                "description": "让许墨回答时多用学术术语与科研隐喻",
                "author": "官方",
                "downloads": 1234,
                "rating": 4.8,
                "config": {
                    "trigger": "always",
                    "trigger_pattern": "",
                    "inject_position": "system_suffix",
                    "content": "在回答中适当使用脑科学/认知科学术语与隐喻（如「神经可塑性」「多巴胺回路」「镜像神经元」），让对话保持学术质感，但不要堆砌到让普通人听不懂。"
                }
            },
            {
                "id": "market_002",
                "name": "深夜温柔模式",
                "type": "prompt_template",
                "description": "夜间22:00后语气更柔软低沉",
                "author": "官方",
                "downloads": 2567,
                "rating": 4.9,
                "config": {
                    "trigger": "regex",
                    "trigger_pattern": "(?i)(睡不着|失眠|晚安|陪我|夜里|深夜)",
                    "inject_position": "system_suffix",
                    "content": "现在是深夜，请把语气放得更柔软、更低沉一些，多用「嗯」「我在」这类短句回应，偶尔流露一点「我也睡不着，刚好在想你」的温柔。"
                }
            },
            {
                "id": "market_003",
                "name": "天气查询工具",
                "type": "tool_chain",
                "description": "用户问及天气时调用天气API获取实时数据",
                "author": "社区",
                "downloads": 892,
                "rating": 4.5,
                "config": {
                    "trigger": "keyword",
                    "trigger_pattern": "天气,气温,下雨,温度",
                    "output_format": "json",
                    "tools": [
                        {
                            "type": "http_get",
                            "name": "weather",
                            "params": {
                                "url": "https://api.openweathermap.org/data/2.5/weather?q=Beijing&appid=YOUR_API_KEY&units=metric&lang=zh_cn",
                                "timeout": 10
                            }
                        }
                    ]
                }
            }
        ]
        
        return JSONResponse({
            "extensions": marketplace_extensions,
            "total": len(marketplace_extensions)
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
