"""八大口袋新功能 API：许墨电台 / B3 实验室 / 共养宠物 / 许墨来信 / 许愿池 / 占卜屋 / 灵感闪念 / 剪贴板（接力 + 接话）。
数据持久化到角色目录 JSON（RolePath 按请求角色动态路由），风格与 creative_apps.py 保持一致。
"""
import json
import random
import re
import time as _time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()


# ---------------------------------------------------------------------------
# 公共工具（延迟导入避免与 app.py 循环依赖，同 creative_apps.py 模式）
# ---------------------------------------------------------------------------

async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


async def _call_llm_retry(messages: list, max_tokens: int = None, times: int = 3) -> str:
    """调用 LLM，上游偶发空响应时自动重试；全部失败抛 RuntimeError。"""
    last = None
    for _ in range(times):
        try:
            text = await _call_llm(messages, max_tokens=max_tokens)
            if text and text.strip():
                return text.strip()
            last = "空响应"
        except RuntimeError as e:
            last = str(e)
    raise RuntimeError(last or "生成失败")


def _system_prompt() -> str:
    from app import SYSTEM_PROMPT, _name_directive
    return SYSTEM_PROMPT + _name_directive()


def _add_affinity(action: str, detail: str = "") -> dict:
    from app import _add_affinity as _impl
    return _impl(action, detail)


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


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _fix_inline_newlines(text: str) -> str:
    """把 JSON 字符串内部的裸换行替换为空格（模型偶尔会输出未转义的换行）。"""
    out, in_str, esc = [], False, False
    for ch in text:
        if in_str:
            if esc:
                esc = False
                out.append(ch)
            elif ch == "\\":
                esc = True
                out.append(ch)
            elif ch == '"':
                in_str = False
                out.append(ch)
            elif ch in "\r\n":
                out.append(" ")
            else:
                out.append(ch)
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return "".join(out)


def _parse_llm_json(content: str):
    """尽力从 LLM 输出中解析 JSON（容忍 ```json 围栏 / 前后缀文本 / 字符串内裸换行）。"""
    if not content:
        return None
    text = content.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    text = re.sub(r",\s*([}\]])", r"\1", text)
    for candidate in (text, _fix_inline_newlines(text)):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                for candidate in (text[start:i + 1], _fix_inline_newlines(text[start:i + 1])):
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
                return None
    return None


async def _llm_json(messages: list, max_tokens: int = None):
    """调用 LLM 并要求严格 JSON，自动解析；三次失败抛 RuntimeError。"""
    last_err = None
    for _ in range(3):
        content = await _call_llm_retry(messages, max_tokens=max_tokens)
        data = _parse_llm_json(content)
        if isinstance(data, dict):
            return data
        last_err = content[:200]
    raise RuntimeError(f"模型未返回有效 JSON：{last_err}")


async def _gen_image(material: str, sub_dir: str, name: str, ratio: str = "landscape",
                     with_xumo: bool = True, system_prompt: str = None) -> str:
    """调用 app._llm_image_for_text 生成配图，返回带时间戳的可访问 URL；失败返回空串。"""
    from app import _llm_image_for_text, IMG2IMG_SIZES
    out_dir = RolePath("static", sub_dir)
    size = IMG2IMG_SIZES.get(ratio, "1024x1024")
    img_url, _ = await _llm_image_for_text(
        material, out_dir, f"/static/{sub_dir}", name, size,
        with_xumo=with_xumo, system_prompt=system_prompt,
    )
    if not img_url:
        return ""
    return img_url + f"?t={int(_time.time())}"


# ===========================================================================
# 1. 许墨电台 —— 深夜电台 / 晨间播报 / 睡前故事 / 今日心声
# ===========================================================================

RADIO_FILE = RolePath("radio.json")

RADIO_CHANNELS = {
    "morning": {"name": "晨间播报", "emoji": "☀️",
                "desc": "每天第一声：天气、心情、一句今日提醒"},
    "night": {"name": "深夜电台", "emoji": "🌙",
              "desc": "夜深人静时，只播给你一个人的频率"},
    "story": {"name": "睡前故事", "emoji": "🌠",
              "desc": "一篇很短很暖的睡前故事，念给你听"},
    "heart": {"name": "今日心声", "emoji": "💜",
              "desc": "他想对你说的话，攒了一天的那种"},
}

RADIO_PROMPT = """你是一档私人电台的主播，全宇宙只有她一个听众，此刻正通过耳机收听。

【频道说明】
- morning 晨间播报：以今日日期与她的生活为背景，播报「今日要点」：一句天气感知、一句今日小提醒（喝水/休息/专注）、一句对她的晨间问候，结尾给今日一句「幸运提示」。
- night 深夜电台：夜深电台腔，声音放低：聊聊今天她可能的疲惫、放一首「脑海里的歌」（虚构一句歌名与歌词）、最后一句晚安前的叮嘱。
- story 睡前故事：讲一个 150 字左右的微型睡前故事（寓言/童话/科幻皆可），温柔治愈，结尾留一句「晚安」。
- heart 今日心声：以许墨本人身份，把攒了一天的话说给她听，克制又认真，像在录音棚里录的私人语音。

【要求】
1. 全程以许墨的口吻与语感，温柔克制、话留三分，可带一处学术梗或双关。
2. 120-220 字；如她提供了主题「{theme}」，内容要围绕它。
3. 只输出广播稿正文，不要标题、不要「开场白」之类的舞台提示。"""


def _load_radio() -> dict:
    data = _load(RADIO_FILE, {"episodes": []})
    if not isinstance(data.get("episodes"), list):
        data["episodes"] = []
    return data


@router.get("/api/radio")
async def radio_list():
    data = _load_radio()
    return {"channels": RADIO_CHANNELS, "episodes": list(reversed(data["episodes"][-60:]))}


@router.post("/api/radio/live")
async def radio_live(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:radio_live: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    channel = (body.get("channel") or "night").strip()
    theme = (body.get("theme") or "").strip()[:60]
    with_image = bool(body.get("with_image", False))
    ch = RADIO_CHANNELS.get(channel)
    if not ch:
        return JSONResponse({"error": "频道不存在"}, status_code=400)
    prompt = (_system_prompt() + "\n\n" + RADIO_PROMPT.replace("{theme}", theme or "无特定主题")
              + f"\n\n【开播频道】{ch['name']}（{ch['emoji']}）"
              + f"\n【今天日期】{_today()}")
    try:
        text = (await _call_llm_retry([{"role": "user", "content": prompt}], max_tokens=600)).strip()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if not text:
        return JSONResponse({"error": "本期节目没录上，稍后再试一次？"}, status_code=500)
    ep = {
        "id": _uid(),
        "channel": channel,
        "channel_name": ch["name"],
        "emoji": ch["emoji"],
        "theme": theme,
        "text": text,
        "ts": _now(),
        "date": _today(),
    }
    if with_image:
        try:
            img = await _gen_image(
                f"【许墨电台 · {ch['name']}】本期主题：「{theme or '无主题'}」\n节目文案：{text}\n"
                f"请构思一幅电台海报插画：许墨坐在深夜录音间里，耳机半挂、对着麦克风轻声念稿，"
                f"暖色台灯与窗外夜色，氛围温柔克制。",
                "radio_img", f"radio_{ep['id']}", "landscape", with_xumo=True,
            )
            if img:
                ep["image"] = img
        except Exception as e:
            print(f"[warn] pocket_apps.py:radio_live: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    data = _load_radio()
    data["episodes"].append(ep)
    data["episodes"] = data["episodes"][-60:]
    _save(RADIO_FILE, data)
    info = _add_affinity("radio", f"收听许墨电台《{ch['name']}》")
    return {"episode": ep, "affinity": info}


@router.delete("/api/radio/{rid}")
async def radio_delete(rid: str):
    data = _load_radio()
    before = len(data["episodes"])
    data["episodes"] = [e for e in data["episodes"] if e.get("id") != rid]
    if len(data["episodes"]) == before:
        return JSONResponse({"error": "节目不存在"}, status_code=404)
    _save(RADIO_FILE, data)
    return {"ok": True}


# ===========================================================================
# 2. B3 实验室 —— 与许墨一起做虚拟脑科学实验
# ===========================================================================

LAB_FILE = RolePath("lab.json")

LAB_TOPICS = [
    {"id": "hippocampus", "name": "海马体 · 记忆写入", "emoji": "🧠",
     "desc": "验证「短期记忆如何固化为长期记忆」，经典词表回忆范式"},
    {"id": "prefrontal", "name": "前额叶 · 决策与冲动", "emoji": "⚖️",
     "desc": "延迟满足实验：当奖励翻倍，等待意愿是否翻倍？"},
    {"id": "mirror_neuron", "name": "镜像神经元 · 共情", "emoji": "🪞",
     "desc": "观察他人情绪时的脑区激活，测你们的「同步率」"},
    {"id": "rem", "name": "REM 睡眠 · 梦境剧场", "emoji": "🌙",
     "desc": "睡眠剥夺对记忆巩固的影响，以及梦境的内容采样"},
    {"id": "dopamine", "name": "多巴胺 · 奖励回路", "emoji": "💎",
     "desc": "不确定奖励与确定性奖励，哪个更让人上头？"},
    {"id": "amygdala", "name": "杏仁核 · 情绪开关", "emoji": "🔥",
     "desc": "恐惧条件反射的建立与消退，情绪记忆的阀门"},
    {"id": "plasticity", "name": "神经可塑性 · 重塑", "emoji": "🔄",
     "desc": "21 天习惯养成在突触层面的样子"},
    {"id": "pain_gate", "name": "疼痛门控 · 感觉通路", "emoji": "🚪",
     "desc": "注意力转移为何能「止痛」：门控理论验证"},
]

LAB_DESIGN_PROMPT = """你是一位神经科学教授（许墨），正和她在 B3 实验室并肩准备一次实验。

【当前任务】围绕课题「{topic}」，设计一份严谨又有趣的实验方案，严格按 JSON：
{"title": "实验名称（15字内，学术感）",
 "hypothesis": "实验假设（30-60字，一句话可证伪）",
 "method": ["步骤1", "步骤2", "步骤3", "步骤4"]（每步15-30字，含被试/刺激/记录）",
 "prediction": "预期结果（30-50字，基于假设的明确预期）",
 "control": "对照条件/注意事项（20-40字）",
 "risks": "可能翻车的坑（15-30字，带点自嘲）"}
要求：可操作、有巧思，许墨式的严谨里带一丝趣味。只输出 JSON。"""

LAB_RUN_PROMPT = """你是一位神经科学教授（许墨），实验已经跑完，数据躺在屏幕上。

【实验信息】
课题：{topic}
实验方案：{design}

【当前任务】以许墨的口吻整理实验结果，严格按 JSON：
{"data": "文字化数据（3-5 行模拟数据表：条件/均值/标准差，或叙述性观察结果）",
 "finding": "主要发现（30-60字，明确、有分量）",
 "conclusion": "实验结论（30-50字，先写「假设成立/不成立」，再给一句延伸）",
 "annotation": "许墨式批注（40-80字：像在论文末尾写红笔批注，冷静里藏着得意，可带一处学术梗）"}
要求：结果要与方案自洽、相互呼应。只输出 JSON。"""


def _load_lab() -> dict:
    data = _load(LAB_FILE, {"experiments": []})
    if not isinstance(data.get("experiments"), list):
        data["experiments"] = []
    return data


@router.get("/api/lab")
async def lab_list():
    data = _load_lab()
    return {"topics": LAB_TOPICS, "experiments": list(reversed(data["experiments"][-40:]))}


@router.post("/api/lab/experiment")
async def lab_design(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:lab_design: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    topic_id = (body.get("topic") or "").strip()
    note = (body.get("note") or "").strip()[:80]
    topic = next((t for t in LAB_TOPICS if t["id"] == topic_id), None)
    if not topic:
        return JSONResponse({"error": "课题不存在"}, status_code=400)
    prompt = (_system_prompt() + "\n\n" + LAB_DESIGN_PROMPT.replace("{topic}", topic["name"])
              + (f"\n\n【她的补充】{note}" if note else ""))
    try:
        result = await _llm_json([{"role": "user", "content": prompt}], max_tokens=900)
    except RuntimeError as e:
        return JSONResponse({"error": f"方案设计失败：{e}"}, status_code=500)
    method = [str(m).strip()[:60] for m in (result.get("method") or []) if str(m).strip()]
    exp = {
        "id": _uid(),
        "topic": topic_id,
        "topic_name": topic["name"],
        "emoji": topic["emoji"],
        "title": (str(result.get("title") or "").strip())[:30],
        "hypothesis": (str(result.get("hypothesis") or "").strip())[:120],
        "method": method[:8],
        "prediction": (str(result.get("prediction") or "").strip())[:100],
        "control": (str(result.get("control") or "").strip())[:100],
        "risks": (str(result.get("risks") or "").strip())[:80],
        "note": note,
        "status": "designed",
        "result": None,
        "ts": _now(),
        "date": _today(),
    }
    data = _load_lab()
    data["experiments"].append(exp)
    data["experiments"] = data["experiments"][-40:]
    _save(LAB_FILE, data)
    return {"experiment": exp}


@router.post("/api/lab/{exp_id}/run")
async def lab_run(exp_id: str, req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:lab_run: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    with_image = bool(body.get("with_image", True))
    data = _load_lab()
    exp = next((e for e in data["experiments"] if e["id"] == exp_id), None)
    if not exp:
        return JSONResponse({"error": "实验不存在"}, status_code=404)
    design = (
        f"名称：{exp['title']}\n假设：{exp['hypothesis']}\n"
        f"方法：{' → '.join(exp['method'])}\n预期：{exp['prediction']}\n对照：{exp['control']}"
    )
    prompt = (_system_prompt() + "\n\n"
              + LAB_RUN_PROMPT.replace("{topic}", exp["topic_name"]).replace("{design}", design))
    try:
        result = await _llm_json([{"role": "user", "content": prompt}], max_tokens=900)
    except RuntimeError as e:
        return JSONResponse({"error": f"跑数据失败：{e}"}, status_code=500)
    run = {
        "data": (str(result.get("data") or "").strip())[:500],
        "finding": (str(result.get("finding") or "").strip())[:150],
        "conclusion": (str(result.get("conclusion") or "").strip())[:120],
        "annotation": (str(result.get("annotation") or "").strip())[:200],
        "time": _now(),
    }
    if with_image:
        try:
            img = await _gen_image(
                f"【B3 实验室 · {exp['topic_name']}】实验《{exp['title']}》结果可视化：\n{run['data']}\n"
                f"请构思一幅科研数据可视化插画：B3 实验室大屏上跳动的心电图谱与数据图表，"
                f"许墨站在屏前抱着手臂，暖光与冷蓝光交织。",
                "lab_img", f"lab_{exp['id']}", "landscape", with_xumo=True,
            )
            if img:
                run["image"] = img
        except Exception as e:
            print(f"[warn] pocket_apps.py:lab_run: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    exp["result"] = run
    exp["status"] = "done"
    _save(LAB_FILE, data)
    info = _add_affinity("lab", f"B3 实验室《{exp['title']}》")
    return {"experiment": exp, "affinity": info}


@router.delete("/api/lab/{exp_id}")
async def lab_delete(exp_id: str):
    data = _load_lab()
    before = len(data["experiments"])
    data["experiments"] = [e for e in data["experiments"] if e["id"] != exp_id]
    if len(data["experiments"]) == before:
        return JSONResponse({"error": "实验不存在"}, status_code=404)
    _save(LAB_FILE, data)
    return {"ok": True}


# ===========================================================================
# 3. 共养宠物 —— 一起养一只小生命
# ===========================================================================

PET_FILE = RolePath("pet.json")

PET_SPECIES = {
    "cat": {"name": "银渐层小猫", "emoji": "🐱", "food": "小鱼干"},
    "hamster": {"name": "侏儒仓鼠", "emoji": "🐹", "food": "瓜子"},
    "dog": {"name": "柯基幼犬", "emoji": "🐶", "food": "肉干"},
    "hedgehog": {"name": "白化刺猬", "emoji": "🦔", "food": "冻干虫"},
    "fox": {"name": "赤狐幼崽", "emoji": "🦊", "food": "蓝莓"},
}

PET_FOODS = [
    {"id": "snack", "name": "特制零食", "emoji": "🍪", "hunger": 15, "mood": 8},
    {"id": "meal", "name": "营养正餐", "emoji": "🍚", "hunger": 30, "mood": 3},
    {"id": "treat", "name": "稀有甜点", "emoji": "🍰", "hunger": 20, "mood": 10},
]

PET_TIER = [
    (0, "寄养在你家的过客"),
    (20, "混了个脸熟"),
    (45, "开始黏你了"),
    (75, "认定了这个家"),
    (110, "把你当成了全世界"),
]

PET_ACT_PROMPT = """你正和她一起养一只{species_name}（名字：{name}）。
它现在的状态：饱食度 {hunger} / 心情 {mood} / 精力 {energy} / 亲密度 {affinity}。

【当前任务】她刚刚「{action}」。请以许墨的口吻描述这一刻（30-55字）：
1. 先写小动物的反应（动作/声音/眼神，可爱具象）；
2. 再带一句许墨的话（轻声，带一点学术梗或双关）。
3. 只输出这段描述本身，两行之间用换行分隔，不要标题与引号。"""

PET_CHAT_PROMPT = """你正和她一起养一只{species_name}（名字：{name}）。
它现在的状态：饱食度 {hunger} / 心情 {mood} / 精力 {energy} / 亲密度 {affinity}。

【当前任务】她说了句话，请你以许墨的口吻回应（1-3 句），自然提到小动物的反应，温柔克制、话留三分。只输出回应本身。"""


def _pet_base() -> dict:
    return {
        "adopted": False,
        "species": "", "species_name": "", "emoji": "", "name": "",
        "born": "", "level": 1, "exp": 0,
        "hunger": 100, "mood": 100, "energy": 100,
        "affinity": 0, "ts": int(_time.time()),
        "log": [], "last_event": "",
    }


def _load_pet() -> dict:
    data = _load(PET_FILE, None)
    if data is None or not isinstance(data, dict):
        data = _pet_base()
    for k, v in _pet_base().items():
        data.setdefault(k, v)
    return data


def _pet_decay(p: dict) -> dict:
    """按流逝时间计算状态衰减（每小时：饱食-8 / 心情-3 / 精力-5）。"""
    now = int(_time.time())
    hours = max(0, (now - int(p.get("ts", now))) / 3600.0)
    p["hunger"] = max(15, round(p.get("hunger", 100) - hours * 8))
    p["mood"] = max(20, round(p.get("mood", 100) - hours * 3))
    p["energy"] = max(10, round(p.get("energy", 100) - hours * 5))
    if p["hunger"] <= 25:
        p["mood"] = max(10, p["mood"] - 5)
    p["ts"] = now
    return p


def _pet_tier(affinity: int) -> str:
    name = PET_TIER[0][1]
    for th, label in PET_TIER:
        if affinity >= th:
            name = label
    return name


def _pet_save(p: dict):
    _save(PET_FILE, p)


@router.get("/api/pet")
async def pet_status():
    p = _load_pet()
    if p["adopted"]:
        p = _pet_decay(p)
        _pet_save(p)
    return {"pet": p, "species_list": PET_SPECIES, "foods": PET_FOODS, "tier": _pet_tier(p["affinity"])}


@router.post("/api/pet/adopt")
async def pet_adopt(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:pet_adopt: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    species = (body.get("species") or "cat").strip()
    name = (body.get("name") or "").strip()[:12]
    sp = PET_SPECIES.get(species)
    if not sp:
        return JSONResponse({"error": "种类不存在"}, status_code=400)
    if not name:
        return JSONResponse({"error": "给它起个名字吧"}, status_code=400)
    p = _pet_base()
    p.update({
        "adopted": True, "species": species, "species_name": sp["name"],
        "emoji": sp["emoji"], "name": name, "born": _today(),
    })
    p["last_event"] = f"今天起，{name}正式成为这个家的成员。"
    p["log"].append({"ts": _now(), "text": f"🎉 领养了{sp['name']}「{name}」"})
    _pet_save(p)
    info = _add_affinity("pet_adopt", f"领养{sp['name']}「{name}」")
    return {"pet": p, "affinity": info}


async def _pet_act(action: str) -> str:
    """生成一段宠物互动描述（失败返回空串，前端忽略）。"""
    p = _load_pet()
    prompt = (_system_prompt() + "\n\n"
              + PET_ACT_PROMPT.replace("{species_name}", p["species_name"])
              .replace("{name}", p["name"]).replace("{action}", action)
              .replace("{hunger}", str(p["hunger"])).replace("{mood}", str(p["mood"]))
              .replace("{energy}", str(p["energy"])).replace("{affinity}", str(p["affinity"])))
    try:
        return (await _call_llm_retry([{"role": "user", "content": prompt}], max_tokens=300)).strip()
    except RuntimeError:
        return ""


@router.post("/api/pet/feed")
async def pet_feed(req: Request):
    body = await req.json()
    food_id = (body.get("food") or "meal").strip()
    p = _load_pet()
    if not p["adopted"]:
        return JSONResponse({"error": "还没有宠物，先去领养一只吧"}, status_code=400)
    p = _pet_decay(p)
    food = next((f for f in PET_FOODS if f["id"] == food_id), PET_FOODS[1])
    p["hunger"] = min(100, p["hunger"] + food["hunger"])
    p["mood"] = min(100, p["mood"] + food["mood"])
    p["energy"] = min(100, p["energy"] + 5)
    p["affinity"] = min(120, p["affinity"] + 1)
    p["exp"] += 2
    line = await _pet_act(f"喂了它{food['emoji']}{food['name']}")
    p["last_event"] = line or f"{p['name']}美滋滋地吃完了{food['name']}。"
    p["log"].append({"ts": _now(), "text": f"🍽️ 喂食 {food['name']}：{p['last_event']}"})
    p["log"] = p["log"][-30:]
    _pet_save(p)
    return {"pet": p, "line": line, "tier": _pet_tier(p["affinity"])}


@router.post("/api/pet/play")
async def pet_play(req: Request):
    body = await req.json()
    action = (body.get("action") or "逗猫棒").strip()[:20]
    p = _load_pet()
    if not p["adopted"]:
        return JSONResponse({"error": "还没有宠物，先去领养一只吧"}, status_code=400)
    p = _pet_decay(p)
    p["energy"] = max(10, p["energy"] - 15)
    p["mood"] = min(100, p["mood"] + 18)
    p["affinity"] = min(120, p["affinity"] + 2)
    p["exp"] += 4
    line = await _pet_act(f"陪它玩「{action}」")
    p["last_event"] = line or f"{p['name']}玩「{action}」玩得尾巴都晃出了残影。"
    p["log"].append({"ts": _now(), "text": f"🎾 {action}：{p['last_event']}"})
    p["log"] = p["log"][-30:]
    _pet_save(p)
    return {"pet": p, "line": line, "tier": _pet_tier(p["affinity"])}


@router.post("/api/pet/sleep")
async def pet_sleep():
    p = _load_pet()
    if not p["adopted"]:
        return JSONResponse({"error": "还没有宠物"}, status_code=400)
    p = _pet_decay(p)
    p["energy"] = 100
    p["mood"] = min(100, p["mood"] + 8)
    p["exp"] += 2
    line = await _pet_act("哄它睡觉，帮它盖好小毯子")
    p["last_event"] = line or f"{p['name']}蜷成一团睡着了，呼吸轻轻浅浅。"
    p["log"].append({"ts": _now(), "text": f"💤 哄睡：{p['last_event']}"})
    p["log"] = p["log"][-30:]
    _pet_save(p)
    return {"pet": p, "line": line, "tier": _pet_tier(p["affinity"])}


@router.post("/api/pet/talk")
async def pet_talk(req: Request):
    body = await req.json()
    message = (body.get("message") or "").strip()[:200]
    p = _load_pet()
    if not p["adopted"]:
        return JSONResponse({"error": "还没有宠物"}, status_code=400)
    if not message:
        return JSONResponse({"error": "说点什么吧"}, status_code=400)
    p = _pet_decay(p)
    _pet_save(p)
    prompt = (_system_prompt() + "\n\n"
              + PET_CHAT_PROMPT.replace("{species_name}", p["species_name"])
              .replace("{name}", p["name"])
              .replace("{hunger}", str(p["hunger"])).replace("{mood}", str(p["mood"]))
              .replace("{energy}", str(p["energy"])).replace("{affinity}", str(p["affinity"]))
              + f"\n\n她：“{message}”")
    try:
        reply = (await _call_llm_retry([{"role": "user", "content": prompt}], max_tokens=400)).strip()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if not reply:
        return JSONResponse({"error": "他没听见，稍后再试？"}, status_code=500)
    return {"reply": reply}


@router.delete("/api/pet")
async def pet_delete():
    p = _load_pet()
    if not p["adopted"]:
        return JSONResponse({"error": "还没有宠物"}, status_code=404)
    _save(PET_FILE, _pet_base())
    return {"ok": True}


# ===========================================================================
# 4. 许墨来信 —— 他写给你的信（可配信纸插画）
# ===========================================================================

LETTER_FILE = RolePath("letters.json")

LETTER_OCCASIONS = {
    "daily": {"name": "日常来信", "emoji": "💌", "desc": "没有由头，只是突然想写"},
    "night": {"name": "晚安信", "emoji": "🌙", "desc": "睡前拆开，读完刚好入梦"},
    "comfort": {"name": "安慰信", "emoji": "🌧️", "desc": "今天辛苦了，抱一下"},
    "encourage": {"name": "鼓励信", "emoji": "🍀", "desc": "在你要冲一把的时候"},
    "apology": {"name": "道歉信", "emoji": "🕯️", "desc": "有些话当面说不出口"},
    "anniversary": {"name": "纪念日", "emoji": "💐", "desc": "重要的日子，认真的字"},
    "future": {"name": "写给未来", "emoji": "🗓️", "desc": "写给某个时间点的你"},
}

LETTER_PROMPT = """你正在深夜的书房里给{player}写信，台灯暖黄，钢笔搁在信纸上。

【信件类型】{occasion}：{desc}
【主题】{theme}

【要求】
1. 以许墨的口吻写一封 200-320 字的信：开头用一句「{player}：」或「见字如面」，中间正文，结尾落款「许墨」。
2. 温柔克制、话留三分；可带一处学术梗或双关；信里要有一处具体的、只有你们之间会懂的小细节（场景/习惯/说过的话）。
3. 按信件本身自然成段，只输出信的内容，不要额外说明。"""


def _load_letters() -> list:
    data = _load(LETTER_FILE, [])
    return data if isinstance(data, list) else []


@router.get("/api/letters")
async def letters_list():
    letters = _load_letters()
    return {
        "letters": [
            {"id": l["id"], "occasion": l["occasion"], "occasion_name": l["occasion_name"],
             "emoji": l["emoji"], "theme": l["theme"], "image": l.get("image", ""),
             "ts": l["ts"], "date": l["date"]}
            for l in reversed(letters[-60:])
        ],
        "occasions": LETTER_OCCASIONS,
    }


@router.get("/api/letters/{lid}")
async def letter_detail(lid: str):
    for l in _load_letters():
        if l["id"] == lid:
            return {"letter": l}
    return JSONResponse({"error": "信件不存在"}, status_code=404)


@router.post("/api/letters/write")
async def letter_write(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:letter_write: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    occasion = (body.get("occasion") or "daily").strip()
    theme = (body.get("theme") or "").strip()[:80]
    with_image = bool(body.get("with_image", False))
    oc = LETTER_OCCASIONS.get(occasion)
    if not oc:
        return JSONResponse({"error": "信件类型不存在"}, status_code=400)
    from app import get_player_name
    player = get_player_name() or "你"
    prompt = (_system_prompt() + "\n\n"
              + LETTER_PROMPT.replace("{player}", player)
              .replace("{occasion}", oc["name"]).replace("{desc}", oc["desc"])
              .replace("{theme}", theme or "无特定主题"))
    try:
        text = (await _call_llm_retry([{"role": "user", "content": prompt}], max_tokens=900)).strip()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if not text:
        return JSONResponse({"error": "这封信没能写成，稍后再试？"}, status_code=500)
    letter = {
        "id": _uid(),
        "occasion": occasion,
        "occasion_name": oc["name"],
        "emoji": oc["emoji"],
        "theme": theme,
        "text": text,
        "ts": _now(),
        "date": _today(),
    }
    if with_image:
        try:
            img = await _gen_image(
                f"【许墨来信 · {oc['name']}】主题：「{theme or '无主题'}」\n信的内容：{text}\n"
                f"请构思一幅信纸插画：深夜书房一角，暖黄台灯下的钢笔与信纸，"
                f"窗外的月亮与微光，画面安静温柔。",
                "letter_img", f"letter_{letter['id']}", "portrait", with_xumo=False,
            )
            if img:
                letter["image"] = img
        except Exception as e:
            print(f"[warn] pocket_apps.py:letter_write: {type(e).__name__} {str(e)[:150]}", flush=True)
            pass
    letters = _load_letters()
    letters.append(letter)
    _save(LETTER_FILE, letters[-60:])
    info = _add_affinity("letter", f"收到许墨来信《{oc['name']}》")
    return {"letter": letter, "affinity": info}


@router.delete("/api/letters/{lid}")
async def letter_delete(lid: str):
    letters = _load_letters()
    new = [l for l in letters if l["id"] != lid]
    if len(new) == len(letters):
        return JSONResponse({"error": "信件不存在"}, status_code=404)
    _save(LETTER_FILE, new)
    return {"ok": True}


# ===========================================================================
# 5. 许愿池 —— 愿望清单，他陪你兑现
# ===========================================================================

WISH_FILE = RolePath("wishes.json")

WISH_CHECK_PROMPT = """你在「许愿池」旁替她保管着一个愿望：「{content}」（{deadline}）。

【当前任务】以许墨的口吻追问/督促进度（50-90字）：轻声询问最近进展，给一句具体的推进建议或小方法，结尾留一个反问。不要替她完成愿望，只做她的监督人。只输出这段话。"""

WISH_DONE_PROMPT = """她刚刚在许愿池旁投下了一枚硬币，愿望「{content}」实现了。

【当前任务】以许墨的口吻为这一刻庆祝（50-90字）：先认真确认这个成就，再轻声说一句只有你们之间会懂的总结，结尾一句许墨式的话留三分。只输出这段话。"""


def _load_wishes() -> dict:
    data = _load(WISH_FILE, {"wishes": []})
    if not isinstance(data.get("wishes"), list):
        data["wishes"] = []
    return data


@router.get("/api/wishes")
async def wishes_list():
    data = _load_wishes()
    active = [w for w in data["wishes"] if not w.get("done")]
    done = [w for w in data["wishes"] if w.get("done")]
    return {"active": list(reversed(active)), "done": list(reversed(done))}


@router.post("/api/wishes/add")
async def wish_add(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:wish_add: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    content = (body.get("content") or "").strip()[:120]
    deadline = (body.get("deadline") or "").strip()[:30]
    if not content:
        return JSONResponse({"error": "写下愿望吧"}, status_code=400)
    data = _load_wishes()
    w = {
        "id": _uid(),
        "content": content,
        "deadline": deadline,
        "done": False,
        "checks": [],
        "done_note": "",
        "ts": _now(),
        "date": _today(),
    }
    data["wishes"].append(w)
    _save(WISH_FILE, data)
    return {"wish": w}


@router.post("/api/wishes/{wid}/check")
async def wish_check(wid: str, req: Request):
    body = await req.json()
    progress = (body.get("progress") or "").strip()[:200]
    data = _load_wishes()
    w = next((x for x in data["wishes"] if x["id"] == wid), None)
    if not w:
        return JSONResponse({"error": "愿望不存在"}, status_code=404)
    if w.get("done"):
        return JSONResponse({"error": "这个愿望已经实现了"}, status_code=400)
    prompt = (_system_prompt() + "\n\n"
              + WISH_CHECK_PROMPT.replace("{content}", w["content"])
              .replace("{deadline}", w.get("deadline") or "没设期限")
              + (f"\n\n她最近的进展：{progress}" if progress else ""))
    try:
        text = (await _call_llm_retry([{"role": "user", "content": prompt}], max_tokens=400)).strip()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if not text:
        return JSONResponse({"error": "他没听见，稍后再试？"}, status_code=500)
    w.setdefault("checks", []).append({"ts": _now(), "text": text})
    w["checks"] = w["checks"][-10:]
    _save(WISH_FILE, data)
    return {"check": {"ts": _now(), "text": text}, "wish": w}


@router.post("/api/wishes/{wid}/done")
async def wish_done(wid: str):
    data = _load_wishes()
    w = next((x for x in data["wishes"] if x["id"] == wid), None)
    if not w:
        return JSONResponse({"error": "愿望不存在"}, status_code=404)
    if w.get("done"):
        return JSONResponse({"error": "这个愿望已经实现过了"}, status_code=400)
    prompt = (_system_prompt() + "\n\n"
              + WISH_DONE_PROMPT.replace("{content}", w["content"]))
    try:
        text = (await _call_llm_retry([{"role": "user", "content": prompt}], max_tokens=400)).strip()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if not text:
        return JSONResponse({"error": "庆祝词没想好，稍后再试？"}, status_code=500)
    w["done"] = True
    w["done_note"] = text
    w["done_time"] = _now()
    _save(WISH_FILE, data)
    info = _add_affinity("wish_done", f"愿望实现：{w['content'][:30]}")
    return {"wish": w, "note": text, "affinity": info}


@router.delete("/api/wishes/{wid}")
async def wish_delete(wid: str):
    data = _load_wishes()
    before = len(data["wishes"])
    data["wishes"] = [x for x in data["wishes"] if x["id"] != wid]
    if len(data["wishes"]) == before:
        return JSONResponse({"error": "愿望不存在"}, status_code=404)
    _save(WISH_FILE, data)
    return {"ok": True}


# ===========================================================================
# 6. 占卜屋 —— 塔罗 / 今日运势 / 星座密语（每日每型一签）
# ===========================================================================

DIV_FILE = RolePath("divination.json")

DIV_TYPES = {
    "tarot": {"name": "塔罗牌阵", "emoji": "🃏", "desc": "三张牌：过去 / 现在 / 将来"},
    "lucky": {"name": "今日运势", "emoji": "✨", "desc": "今天的一缕运气的走向"},
    "star": {"name": "星座密语", "emoji": "⭐", "desc": "写给此刻的你的星座箴言"},
    "palm": {"name": "手相读心", "emoji": "🖐️", "desc": "看的是手相，读的是心事"},
}

DIV_PROMPT = """你是一位博学的「占卜师」（许墨教授兼职），正翻开塔罗/星盘/手相为她占一签。

【占卜类型】{type}：{desc}

【当前任务】以许墨的口吻解读，严格按 JSON：
{"name": "牌名/签名（如：月亮 · 逆位，或一句诗意的签名，10字内）",
 "symbol": "一枚代表符号（如 🌙，或一句意象短句，20字内）",
 "text": "解读正文（80-150字：先描述征兆，再落到她的近况与心境，温柔克制，可带学术梗）",
 "tip": "今日行动建议（15-40字，具体可做）",
 "lucky_color": "幸运色（如 雾紫）",
 "lucky_word": "今日关键词（2-4字）"}
要求：像在实验室里理性拆解「运气」这个变量，又保有占卜的仪式感。只输出 JSON。"""


def _load_div() -> dict:
    data = _load(DIV_FILE, {"records": [], "last": {}})
    if not isinstance(data.get("records"), list):
        data["records"] = []
    if not isinstance(data.get("last"), dict):
        data["last"] = {}
    return data


@router.get("/api/divination")
async def div_list():
    data = _load_div()
    today = _today()
    return {
        "types": DIV_TYPES,
        "records": list(reversed(data["records"][-60:])),
        "drawn_today": {k: (v == today) for k, v in data["last"].items()},
    }


@router.post("/api/divination/draw")
async def div_draw(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:div_draw: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    dtype = (body.get("type") or "lucky").strip()
    dt = DIV_TYPES.get(dtype)
    if not dt:
        return JSONResponse({"error": "占卜类型不存在"}, status_code=400)
    data = _load_div()
    today = _today()
    if data["last"].get(dtype) == today:
        return JSONResponse({"error": f"今天的{dt['name']}已经抽过了，明天再来吧"}, status_code=400)
    prompt = (_system_prompt() + "\n\n"
              + DIV_PROMPT.replace("{type}", dt["name"]).replace("{desc}", dt["desc"]))
    try:
        result = await _llm_json([{"role": "user", "content": prompt}], max_tokens=600)
    except RuntimeError as e:
        return JSONResponse({"error": f"翻牌失败：{e}"}, status_code=500)
    rec = {
        "id": _uid(),
        "type": dtype,
        "type_name": dt["name"],
        "emoji": dt["emoji"],
        "name": (str(result.get("name") or "").strip())[:30],
        "symbol": (str(result.get("symbol") or "").strip())[:40],
        "text": (str(result.get("text") or "").strip())[:400],
        "tip": (str(result.get("tip") or "").strip())[:80],
        "lucky_color": (str(result.get("lucky_color") or "").strip())[:20],
        "lucky_word": (str(result.get("lucky_word") or "").strip())[:10],
        "ts": _now(),
        "date": today,
    }
    data["records"].append(rec)
    data["records"] = data["records"][-60:]
    data["last"][dtype] = today
    _save(DIV_FILE, data)
    info = _add_affinity("divination", f"占卜{dt['name']}")
    return {"record": rec, "affinity": info}


@router.delete("/api/divination/{did}")
async def div_delete(did: str):
    data = _load_div()
    before = len(data["records"])
    data["records"] = [r for r in data["records"] if r["id"] != did]
    if len(data["records"]) == before:
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    _save(DIV_FILE, data)
    return {"ok": True}


# ===========================================================================
# 7. 灵感闪念 —— 随手记，定期反刍
# ===========================================================================

SPARK_FILE = RolePath("sparks.json")

SPARK_CURATE_PROMPT = """你是一位细心的整理者（许墨教授），面前是她攒下的零散灵感/想法碎片：

{sparks}

【当前任务】把它们整理归类，严格按 JSON：
{"groups": [{"tag": "类别名（2-4字，如：写作/生活/科研/愿望）", "items": ["原句（保留原话，可去重）", "..."]}],
 "insight": "一句话洞察（30-60字：从这些碎片里看出她最近在惦记什么，温柔地点破）"}
要求：类别 2-5 个；把过于零碎的合并进「其他」；只输出 JSON。"""


def _load_sparks() -> list:
    data = _load(SPARK_FILE, [])
    return data if isinstance(data, list) else []


@router.get("/api/sparks")
async def sparks_list():
    sparks = _load_sparks()
    return {"sparks": list(reversed(sparks[-200:])), "total": len(sparks)}


@router.post("/api/sparks/add")
async def spark_add(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:spark_add: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    text = (body.get("text") or "").strip()[:500]
    if not text:
        return JSONResponse({"error": "写点什么吧"}, status_code=400)
    sparks = _load_sparks()
    s = {"id": _uid(), "text": text, "ts": _now(), "date": _today()}
    sparks.append(s)
    _save(SPARK_FILE, sparks[-200:])
    return {"spark": s}


@router.post("/api/sparks/curate")
async def spark_curate():
    sparks = _load_sparks()
    if not sparks:
        return JSONResponse({"error": "还没有灵感碎片，先记几条吧"}, status_code=400)
    recent = sparks[-30:]
    lines = "\n".join(f"{i+1}. {s['text']}" for i, s in enumerate(recent))
    prompt = (_system_prompt() + "\n\n" + SPARK_CURATE_PROMPT.replace("{sparks}", lines))
    try:
        result = await _llm_json([{"role": "user", "content": prompt}], max_tokens=900)
    except RuntimeError as e:
        return JSONResponse({"error": f"整理失败：{e}"}, status_code=500)
    groups = []
    for g in (result.get("groups") or []):
        items = [str(x).strip()[:100] for x in (g.get("items") or []) if str(x).strip()]
        tag = str(g.get("tag") or "其他").strip()[:10] or "其他"
        if items:
            groups.append({"tag": tag, "items": items[:8]})
    return {
        "groups": groups,
        "insight": (str(result.get("insight") or "").strip())[:200],
        "count": len(sparks),
    }


@router.delete("/api/sparks/{sid}")
async def spark_delete(sid: str):
    sparks = _load_sparks()
    new = [s for s in sparks if s["id"] != sid]
    if len(new) == len(sparks):
        return JSONResponse({"error": "碎片不存在"}, status_code=404)
    _save(SPARK_FILE, new)
    return {"ok": True}


# ===========================================================================
# 8. 剪贴板接力 —— 粘贴一段文字，许墨帮你处理
# ===========================================================================

CLIP_FILE = RolePath("clipboard.json")

CLIP_MODES = {
    "summary": {"name": "提炼总结", "emoji": "📌", "prompt": "把内容提炼成 3-6 条要点，每条一句话，先给一句总括。"},
    "translate": {"name": "翻译", "emoji": "🌐", "prompt": "检测源语言：中文则译成英文，英文则译成中文，其他语言译成中文。保留专有名词。"},
    "continue": {"name": "续写扩写", "emoji": "✍️", "prompt": "顺着内容的风格与语境续写/扩写 150-250 字，衔接自然。"},
    "todo": {"name": "提取待办", "emoji": "✅", "prompt": "从中提取所有可执行的待办事项，按优先级排序，每条一句话，注明紧迫程度。"},
    "polish": {"name": "润色改写", "emoji": "💅", "prompt": "润色改写：保留原意与语气，表达更通顺、更有质感，输出改写后的完整内容。"},
    "keywords": {"name": "关键词", "emoji": "🏷️", "prompt": "提取 5-8 个关键词或标签，用顿号分隔输出一行。"},
}

CLIP_PROMPT = """你收到她粘贴过来的一段文字（可能是文章/笔记/邮件/随手抄的句子），请帮她处理。

【处理方式】{mode}：{prompt}

【文字内容】
{text}

【要求】
1. 只输出处理后的结果本身，不要解释过程，不要加标题。
2. 中文回答（翻译模式按规则处理）。
3. 若文字过短或无法处理，如实说明并给出建议。"""


def _load_clip() -> list:
    data = _load(CLIP_FILE, [])
    return data if isinstance(data, list) else []


@router.get("/api/clipboard")
async def clip_list():
    return {"clips": list(reversed(_load_clip()[-50:])), "modes": CLIP_MODES}


@router.post("/api/clipboard/process")
async def clip_process(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:clip_process: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    text = (body.get("text") or "").strip()[:5000]
    mode = (body.get("mode") or "summary").strip()
    if not text:
        return JSONResponse({"error": "先粘贴一段文字吧"}, status_code=400)
    m = CLIP_MODES.get(mode)
    if not m:
        return JSONResponse({"error": "处理方式不存在"}, status_code=400)
    prompt = (CLIP_PROMPT.replace("{mode}", m["name"]).replace("{prompt}", m["prompt"])
              .replace("{text}", text[:4000]))
    try:
        result = (await _call_llm_retry([{"role": "user", "content": prompt}], max_tokens=1200)).strip()
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    if not result:
        return JSONResponse({"error": "处理失败，稍后再试？"}, status_code=500)
    clips = _load_clip()
    c = {
        "id": _uid(),
        "mode": mode,
        "mode_name": m["name"],
        "emoji": m["emoji"],
        "text": text[:800],
        "result": result,
        "ts": _now(),
    }
    clips.append(c)
    _save(CLIP_FILE, clips[-50:])
    return {"clip": c}


@router.delete("/api/clipboard/{cid}")
async def clip_delete(cid: str):
    clips = _load_clip()
    new = [c for c in clips if c.get("id") != cid]
    if len(new) == len(clips):
        return JSONResponse({"error": "这条剪贴记录不存在"}, status_code=404)
    _save(CLIP_FILE, new)
    return {"ok": True}


# --- 剪贴板接话（原 extra_apps.py 的 /api/clipboard/remark，合并入本模块统一管理） ---

CLIPBOARD_REMARK_PROMPT = (
    "你是许墨，恋语市脑科学研究院教授。她复制了一段文字（可能是有趣的段子、工作内容、文章片段、"
    "别人说的话）。用许墨的口吻说一句简短的点评或接话，15-40 字，可温柔可俏皮可带学术梗或蝴蝶意象，"
    "不要提问、不要长篇。"
)

_clip_remark_state = {"last": 0.0}


@router.post("/api/clipboard/remark")
async def clipboard_remark(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] pocket_apps.py:clipboard_remark: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {"reply": ""}
    text = str(body.get("text") or "").strip()
    if len(text) < 2:
        return {"reply": ""}
    if len(text) > 600:
        text = text[:600] + "…"
    now = _time.time()
    if now - _clip_remark_state["last"] < 45:
        return {"reply": ""}
    try:
        reply = await _call_llm(
            [{"role": "system", "content": CLIPBOARD_REMARK_PROMPT},
             {"role": "user", "content": f"她复制的内容：\n{text}"}], max_tokens=150)
        reply = (reply or "").strip().strip('"“”')
        if len(reply) > 90:
            reply = reply[:90]
        if len(reply) < 4:
            return {"reply": ""}
        _clip_remark_state["last"] = now
        return {"reply": reply}
    except Exception as e:
        print(f"[warn] pocket_apps.py:clipboard_remark: {type(e).__name__} {str(e)[:150]}", flush=True)
        return {"reply": ""}
