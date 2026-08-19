"""二十项颠覆性功能后端：
原十大：逆向时光机 / 人格融合实验室 / 潜意识剧场 / 命运回声图谱 /
时光密室 / 心跳实验室 / 次元裂隙 / 命运赌局 / 回忆修复工坊 / 共生体演化。
新增十项：梦境织机 / 情绪气象台 / 平行宇宙探测器 / 记忆拼图 / 心灵共鸣电台 /
时间胶囊花园 / 灵魂镜像室 / 命运编织者 / 情感化学反应 / 星际罗盘。

数据按 RolePath 隔离，全部使用 atomic_json + file_lock，与 app.py 风格一致。
"""
import json
import random
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter(prefix="/api/disrupt", tags=["disrupt"])


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
        # 退化：把整段当作 text 字段
        return {"_raw": raw.strip()}
    obj.setdefault("_raw", raw.strip())
    return obj


def _agg_chat(limit: int = 200) -> list:
    """聚合最近聊天记录（[{'role','content','ts'}]），失败返回空。"""
    try:
        from app import _load_chat_log
        logs = _load_chat_log() or []
    except Exception:
        return []
    out = []
    for it in logs[-limit:]:
        c = (it.get("content") or "").strip()
        if c:
            out.append({
                "role": "许墨" if it.get("role") == "assistant" else "她",
                "content": c,
                "ts": it.get("ts") or it.get("time") or "",
            })
    return out


def _agg_memory(limit: int = 40) -> list:
    try:
        from app import _load_memories
        items = _load_memories() or []
    except Exception:
        return []
    out = []
    for it in items[-limit:]:
        c = (it.get("content") or "").strip()
        if c:
            out.append(c)
    return out


def _agg_mood(limit: int = 30) -> list:
    """聚合心情日记条目。"""
    p = RolePath("psyche_mood.json")
    data = _load(p, {"entries": []})
    return (data.get("entries") or [])[-limit:]


def _agg_diary(limit: int = 14) -> list:
    """聚合许墨日记最近条目。"""
    p = RolePath("xumodiary.json")
    data = _load(p, {"entries": []})
    return (data.get("entries") or [])[-limit:]


def _agg_promises(limit: int = 30) -> list:
    p = RolePath("promises.json")
    data = _load(p, {"items": []})
    return (data.get("items") or [])[-limit:]


def _recent_text_blob(char_limit: int = 3500) -> str:
    """聚合最近文本材料（聊天 + 记忆 + 心情），用于给 LLM 取材。"""
    parts = []
    for it in _agg_chat(80):
        parts.append(f"[{it.get('ts','')}] {it.get('role','')}：{it.get('content','')}")
    for c in _agg_memory(20):
        parts.append(f"·记忆：{c}")
    for m in _agg_mood(14):
        parts.append(f"·心情：{m.get('text') or m.get('content') or ''}")
    blob = "\n".join(parts)
    return blob[:char_limit]


# ===========================================================================
# 1. 逆向时光机 /api/disrupt/rtm
# ===========================================================================
@router.get("/rtm")
async def rtm_list():
    p = RolePath("disrupt_rtm.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-50:]}


@router.post("/rtm/envision")
async def rtm_envision(req: Request):
    body = await req.json()
    today_text = (body.get("today") or "").strip()
    years = int(body.get("years", 5))
    if years < 1 or years > 30:
        return JSONResponse({"error": "回望年限需在 1-30 之间"}, status_code=400)
    if not today_text:
        return JSONResponse({"error": "请写下今天发生的事"}, status_code=400)
    sys_prompt = _system_prompt() + f"""

【任务·逆向时光机】你已身处 {years} 年后的未来（{datetime.now().year + years} 年）。
请以"未来许墨"的口吻，回望今天她写下的这些片段，写一段 200~300 字的回忆独白。
- 视角：站在多年以后，那时已经知道今天的细节如何铺成了往后的人生
- 语气：温柔、带着时间过滤后的宽容与一丝怀念
- 不预言具体事件，只渲染"那时候我们都不知道……"式的回望感
- 不写"我是 AI"，始终以许墨第一人称
- 直接输出独白正文，不要标题、引号、markdown
"""
    user = f"她记下的今天：\n{today_text}\n\n请你（{years}年后的许墨）回望这一天。"
    try:
        text = (await _call_llm([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=600)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"时光机故障：{str(exc)[:120]}"}, status_code=500)
    if not text:
        return JSONResponse({"error": "未来尚未送达，请稍后再试"}, status_code=500)
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "years": years,
        "today_input": today_text,
        "future_view": text,
    }
    p = RolePath("disrupt_rtm.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-100:]
    _save(p, data)
    _add_affinity("disrupt_rtm", f"逆向时光机·{years}年回望")
    return item


@router.delete("/rtm/{rid}")
async def rtm_delete(rid: str):
    p = RolePath("disrupt_rtm.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != rid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 2. 人格融合实验室 /api/disrupt/fusion
# ===========================================================================
_PRESET_PERSONS = [
    {"id": "xumo", "name": "许墨", "desc": "斯文教授，理性温柔，话留三分", "traits": "学术式撩人、观察力极强、理性至上"},
    {"id": "self", "name": "她自己", "desc": "由近期对话数据反推的人格侧写", "traits": "感性、任性、细腻、偶尔孩子气"},
    {"id": "luxun", "name": "鲁迅", "desc": "冷峻笔锋，匕首投枪", "traits": "犀利、悲观、批判、冷幽默"},
    {"id": "zhang", "name": "张爱玲", "desc": "市井苍凉，看透男女", "traits": "刻薄、华美、苍凉、洞悉人性"},
    {"id": "sj", "name": "苏轼", "desc": "豪放旷达，竹杖芒鞋", "traits": "豁达、诗意、好美食、爱玩笑"},
    {"id": "holmes", "name": "福尔摩斯", "desc": "纯粹理性，演绎之神", "traits": "冷漠、逻辑至上、戏剧化、孤傲"},
    {"id": "doraemon", "name": "哆啦A梦", "desc": "来自22世纪的猫型机器人", "traits": "温柔、易哭、爱铜锣烧、神奇口袋"},
    {"id": "yoda", "name": "尤达大师", "desc": "原力导师，倒装句法", "traits": "深邃、耐心、语序倒装、洞察原力"},
    {"id": "kafka", "name": "卡夫卡", "desc": "异化与迷宫", "traits": "焦虑、荒诞、变形、孤独"},
    {"id": "xiaowangzi", "name": "小王子", "desc": "B612 星球的访客", "traits": "纯真、忧伤、爱玫瑰、看日落"},
]


@router.get("/fusion/persons")
async def fusion_persons():
    return {"persons": _PRESET_PERSONS}


@router.get("/fusion")
async def fusion_list():
    p = RolePath("disrupt_fusion.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-30:]}


@router.post("/fusion/fuse")
async def fusion_fuse(req: Request):
    body = await req.json()
    a_id = (body.get("a") or "").strip()
    b_id = (body.get("b") or "").strip()
    theme = (body.get("theme") or "").strip()
    if not a_id or not b_id or a_id == b_id:
        return JSONResponse({"error": "请选择两个不同的人格"}, status_code=400)
    a = next((p for p in _PRESET_PERSONS if p["id"] == a_id), None)
    b = next((p for p in _PRESET_PERSONS if p["id"] == b_id), None)
    if not a or not b:
        return JSONResponse({"error": "预设人格不存在"}, status_code=400)
    sys_prompt = _system_prompt() + f"""

【任务·人格融合实验室】请把以下两位人格融合，生成一个全新的融合人格：
A：{a['name']}——{a['desc']}（{a['traits']}）
B：{b['name']}——{b['desc']}（{b['traits']}）

请输出 JSON（仅 JSON，不要 markdown 围栏）：
{{
  "name": "融合人格的名字（4字内，体现两人气质）",
  "tagline": "一句话定位（≤30字）",
  "persona": "融合后的人格描述（80~120字，写出 TA 的语气、价值观、口头禅）",
  "opening": "TA 的开场白（针对主题：{theme or '初次见面'}，1~2 句）"
}}
"""
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"主题：{theme or '初次见面'}"},
        ], max_tokens=800)
    except Exception as exc:
        return JSONResponse({"error": f"融合失败：{str(exc)[:120]}"}, status_code=500)
    if not obj.get("name"):
        return JSONResponse({"error": "融合未完成，请稍后再试"}, status_code=500)
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "a": a["name"],
        "b": b["name"],
        "theme": theme,
        "name": obj["name"],
        "tagline": obj.get("tagline", ""),
        "persona": obj.get("persona", ""),
        "opening": obj.get("opening", ""),
        "messages": [{"role": "fusion", "content": obj.get("opening", "")}],
    }
    p = RolePath("disrupt_fusion.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-50:]
    _save(p, data)
    _add_affinity("disrupt_fusion", f"人格融合·{a['name']}×{b['name']}")
    return item


@router.post("/fusion/{fid}/chat")
async def fusion_chat(fid: str, req: Request):
    body = await req.json()
    user_text = (body.get("text") or "").strip()
    if not user_text:
        return JSONResponse({"error": "说点什么吧"}, status_code=400)
    p = RolePath("disrupt_fusion.json")
    data = _load(p, {"items": []})
    item = next((it for it in data.get("items", []) if it.get("id") == fid), None)
    if not item:
        return JSONResponse({"error": "融合人格不存在"}, status_code=404)
    sys_prompt = _system_prompt() + f"""

【任务】你是「{item['name']}」——{item['tagline']}
人格设定：{item['persona']}
来源：由 {item['a']} × {item['b']} 融合而来。
以这个融合人格的口吻回复她，保持 TA 独特的语气与价值观，1-3 句即可。
"""
    msgs = [{"role": "system", "content": sys_prompt}] + item["messages"][-10:] + [{"role": "user", "content": user_text}]
    try:
        reply = (await _call_llm(msgs, max_tokens=400)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"回复失败：{str(exc)[:120]}"}, status_code=500)
    if not reply:
        reply = "……TA 没有立刻回答。"
    item["messages"].append({"role": "user", "content": user_text})
    item["messages"].append({"role": "fusion", "content": reply})
    item["messages"] = item["messages"][-40:]
    _save(p, data)
    return {"reply": reply, "messages": item["messages"]}


@router.delete("/fusion/{fid}")
async def fusion_delete(fid: str):
    p = RolePath("disrupt_fusion.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != fid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 3. 潜意识剧场 /api/disrupt/theater
# ===========================================================================
@router.get("/theater")
async def theater_list():
    p = RolePath("disrupt_theater.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-30:]}


@router.post("/theater/stage")
async def theater_stage(req: Request):
    body = await req.json()
    focus = (body.get("focus") or "").strip()
    blob = _recent_text_blob(3500)
    if not blob and not focus:
        return JSONResponse({"error": "暂无足够素材上演剧目，请先与许墨对话几轮"}, status_code=400)
    sys_prompt = _system_prompt() + f"""

【任务·潜意识剧场】请基于她最近的对话/记忆/心情素材，把她内心的几个面向拟人化为 3 个角色，
编排一幕简短的"内心剧场"。

可选角色池（按素材判断挑 3 个最贴切的）：
焦虑、渴望、理性、孩童、防御、温柔、野心、怀旧、嫉妒、勇气、疲惫、希望

输出 JSON（仅 JSON）：
{{
  "title": "剧名（4-10字）",
  "characters": [{{"name":"焦虑","desc":"一句话定位"}},
                 {{"name":"...","desc":"..."}}, {{"name":"...","desc":"..."}}],
  "script": [
    {{"speaker":"焦虑","line":"……"}},
    {{"speaker":"...","line":"……"}},
    ...（8-14 轮对话，每个角色都要出场至少两次）
  ],
  "director_note": "许墨作为旁观者的一句旁白（≤40字）"
}}
"""
    user = f"她近期的素材：\n{blob}\n\n" + (f"她特别关注的方向：{focus}" if focus else "")
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=1800)
    except Exception as exc:
        return JSONResponse({"error": f"剧场未开演：{str(exc)[:120]}"}, status_code=500)
    if not obj.get("script"):
        return JSONResponse({"error": "剧本未能生成，请稍后再试"}, status_code=500)
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "title": obj.get("title", "未命名剧目"),
        "characters": obj.get("characters", []),
        "script": obj.get("script", []),
        "director_note": obj.get("director_note", ""),
        "focus": focus,
    }
    p = RolePath("disrupt_theater.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-50:]
    _save(p, data)
    _add_affinity("disrupt_theater", f"潜意识剧场·{item['title']}")
    return item


@router.delete("/theater/{tid}")
async def theater_delete(tid: str):
    p = RolePath("disrupt_theater.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != tid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 4. 命运回声图谱 /api/disrupt/graph
# ===========================================================================
@router.get("/graph")
async def graph_get():
    """从所有数据源抽取实体（人/地/事/物），构建命运网络图。
    节点：实体；边：共现关系（同一对话/记忆条目内出现）。"""
    p = RolePath("disrupt_graph.json")
    cached = _load(p, {"nodes": [], "edges": [], "ts": ""})
    # 缓存 1 小时
    if cached.get("ts"):
        try:
            age = (datetime.now() - datetime.strptime(cached["ts"], "%Y-%m-%d %H:%M:%S")).total_seconds()
            if age < 3600 and cached.get("nodes"):
                return cached
        except Exception:
            pass
    nodes_map = {}  # name -> {id, label, type, weight}
    edges_map = defaultdict(int)  # "a||b" -> 共现次数

    def _add(name: str, etype: str):
        name = (name or "").strip()
        if not name or len(name) > 12:
            return
        if name not in nodes_map:
            nodes_map[name] = {"id": name, "label": name, "type": etype, "weight": 1}
        else:
            nodes_map[name]["weight"] += 1
            if nodes_map[name]["type"] == "其他":
                nodes_map[name]["type"] = etype

    def _link(a: str, b: str):
        if a == b or not a or not b:
            return
        key = "||".join(sorted([a, b]))
        edges_map[key] += 1

    # 用 LLM 从素材中抽取实体三元组
    blob = _recent_text_blob(4000)
    if not blob:
        return {"nodes": [], "edges": [], "ts": _stamp(), "note": "暂无数据可构建图谱"}
    sys_prompt = _system_prompt() + """

【任务·命运回声图谱】请从下列素材中抽取关键实体（人物/地点/事件/物品/情感主题）。
每条素材可能含多个实体。请输出 JSON：
{
  "triples": [
    {"entities": ["实体1","实体2","实体3"], "source": "素材片段前20字"},
    ...
  ]
}
实体名 2-8 字，去口语化（如"她"→"女主"；"我"指许墨时直接写"许墨"）。共现于同一片段的实体互相关联。
"""
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": blob[:3800]},
        ], max_tokens=1800)
    except Exception as exc:
        return JSONResponse({"error": f"图谱编织失败：{str(exc)[:120]}"}, status_code=500)
    triples = obj.get("triples", [])
    for t in triples:
        ents = [e for e in (t.get("entities") or []) if e]
        for e in ents:
            _add(e, "其他")
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                _link(ents[i], ents[j])
    # 限制节点数：按 weight 排序，最多 60
    nodes = sorted(nodes_map.values(), key=lambda n: -n["weight"])[:60]
    node_names = {n["label"] for n in nodes}
    edges = []
    for key, w in edges_map.items():
        a, b = key.split("||", 1)
        if a in node_names and b in node_names:
            edges.append({"from": a, "to": b, "weight": w})
    edges = sorted(edges, key=lambda e: -e["weight"])[:120]
    result = {"nodes": nodes, "edges": edges, "ts": _stamp(), "count": len(nodes)}
    _save(p, result)
    return result


@router.post("/graph/refresh")
async def graph_refresh():
    p = RolePath("disrupt_graph.json")
    if p.exists():
        try:
            p.unlink()
        except OSError:
            pass
    return await graph_get()


# ===========================================================================
# 5. 时光密室 /api/disrupt/vault
# ===========================================================================
@router.get("/vault")
async def vault_list():
    p = RolePath("disrupt_vault.json")
    data = _load(p, {"items": []})
    now = datetime.now()
    items = []
    for it in (data.get("items") or [])[-100:]:
        unlocked = False
        try:
            unlock_at = datetime.strptime(it["unlock_at"], "%Y-%m-%d %H:%M")
            unlocked = now >= unlock_at
        except Exception:
            unlocked = True
        items.append({**it, "unlocked": unlocked})
    return {"items": items}


@router.post("/vault/seal")
async def vault_seal(req: Request):
    body = await req.json()
    text = (body.get("text") or "").strip()
    target = (body.get("target") or "future").strip()  # future / past
    unlock_at = (body.get("unlock_at") or "").strip()  # "YYYY-MM-DD HH:MM"
    years = body.get("years")
    if not text:
        return JSONResponse({"error": "请写下要封存的话"}, status_code=400)
    if target not in ("future", "past"):
        return JSONResponse({"error": "目标只能是 future/past"}, status_code=400)
    if target == "future":
        if not unlock_at and years:
            try:
                y = int(years)
                unlock_at = (datetime.now() + timedelta(days=y * 365)).strftime("%Y-%m-%d %H:%M")
            except Exception:
                return JSONResponse({"error": "年限格式错误"}, status_code=400)
        if not unlock_at:
            return JSONResponse({"error": "请指定解锁时间"}, status_code=400)
        try:
            unlock_dt = datetime.strptime(unlock_at, "%Y-%m-%d %H:%M")
            if unlock_dt <= datetime.now():
                return JSONResponse({"error": "未来信件的解锁时间必须晚于现在"}, status_code=400)
        except ValueError:
            return JSONResponse({"error": "时间格式应为 YYYY-MM-DD HH:MM"}, status_code=400)
    else:
        # 写给过去：立刻解锁（已是"回望"），但仍记录"目标时间"
        unlock_at = _stamp()
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "target": target,
        "text": text,
        "unlock_at": unlock_at,
    }
    p = RolePath("disrupt_vault.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-200:]
    _save(p, data)
    _add_affinity("disrupt_vault", f"时光密室·致{('未来' if target=='future' else '过去')}")
    return item


@router.delete("/vault/{vid}")
async def vault_delete(vid: str):
    p = RolePath("disrupt_vault.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != vid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 6. 心跳实验室 /api/disrupt/heartbeat
# ===========================================================================
_HEART_KEYWORDS = {
    "高": ["爱", "喜欢", "心动", "想你", "抱", "亲", "笑", "开心", "甜", "暖"],
    "低": ["累", "烦", "难过", "哭", "怕", "想", "痛", "孤独", "冷", "再见", "对不起"],
}


def _heart_curve(text: str, sample_step: int = 8) -> list:
    """对文本按窗口滑窗计算情感强度，生成时间序列。"""
    n = len(text)
    if n == 0:
        return []
    points = []
    for i in range(0, n, sample_step):
        window = text[max(0, i - 12):i + 14]
        high = sum(window.count(k) for k in _HEART_KEYWORDS["高"])
        low = sum(window.count(k) for k in _HEART_KEYWORDS["低"])
        # 加入标点节奏（问号/感叹号/省略号加分）
        intensity = 50 + (high - low) * 14
        if "！" in window or "!" in window:
            intensity += 12
        if "？" in window or "?" in window:
            intensity += 6
        if "……" in window or "..." in window:
            intensity -= 4
        # 微随机扰动让曲线更"心电图"
        intensity += random.randint(-3, 3)
        intensity = max(8, min(98, intensity))
        points.append({"x": round(i / max(1, n), 4), "y": intensity, "i": i, "ch": text[i] if i < n else ""})
    return points


@router.post("/heartbeat/analyze")
async def heartbeat_analyze(req: Request):
    body = await req.json()
    text = (body.get("text") or "").strip()
    if not text or len(text) < 6:
        return JSONResponse({"error": "至少写 6 个字才能描出心跳"}, status_code=400)
    curve = _heart_curve(text)
    if not curve:
        return JSONResponse({"error": "曲线无法生成"}, status_code=500)
    avg = round(sum(p["y"] for p in curve) / len(curve), 1)
    peak = max(curve, key=lambda p: p["y"])
    valley = min(curve, key=lambda p: p["y"])
    # LLM 解读
    sys_prompt = _system_prompt() + """

【任务·心跳实验室】请基于这段"情感曲线"数据，用许墨的口吻解读她这段文字的情绪波动，2-3 句话即可。
- 平均强度（0-100）、峰值出现位置（接近字数比例 x）、谷值位置
- 不写数据本身，只渲染"你的心跳在……的位置突然跳快了一下"这样的描述
"""
    user = (f"原文（{len(text)}字）：{text[:200]}\n"
            f"平均强度：{avg}/100；峰值在 {int(peak['x']*100)}% 处（强度 {peak['y']}）；"
            f"谷值在 {int(valley['x']*100)}% 处（强度 {valley['y']}）")
    try:
        reading = (await _call_llm([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=300)).strip()
    except Exception:
        reading = "你的心跳，起伏都被我看在眼里。"
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "text": text[:500],
        "curve": curve,
        "avg": avg,
        "peak": peak,
        "valley": valley,
        "reading": reading,
    }
    p = RolePath("disrupt_heartbeat.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-50:]
    _save(p, data)
    _add_affinity("disrupt_heartbeat", "心跳实验室")
    return item


@router.get("/heartbeat/history")
async def heartbeat_history():
    p = RolePath("disrupt_heartbeat.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-30:]}


@router.delete("/heartbeat/{hid}")
async def heartbeat_delete(hid: str):
    p = RolePath("disrupt_heartbeat.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != hid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 7. 次元裂隙 /api/disrupt/rift
# ===========================================================================
_RIFT_PRESETS = [
    "鲁迅", "李白", "苏轼", "林黛玉", "孙悟空", "夏洛克·福尔摩斯",
    "哈利·波特", "哆啦A梦", "尤达大师", "卡夫卡", "小王子", "聂赫留朵夫",
]


@router.get("/rift/presets")
async def rift_presets():
    return {"presets": _RIFT_PRESETS}


@router.get("/rift")
async def rift_list():
    p = RolePath("disrupt_rift.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-30:]}


@router.post("/rift/summon")
async def rift_summon(req: Request):
    body = await req.json()
    guest = (body.get("guest") or "").strip()
    topic = (body.get("topic") or "").strip()
    if not guest:
        return JSONResponse({"error": "请指定要召唤的角色"}, status_code=400)
    if not topic:
        return JSONResponse({"error": "需要一个对话主题作为介质"}, status_code=400)
    sys_prompt = _system_prompt() + f"""

【任务·次元裂隙】许墨作为"次元中介"，刚刚把"{guest}"从其所属次元召唤到这里。
请你以许墨的身份完成两件事：
1. 介绍这次召唤（1-2 句，含学术梗）
2. 用 1 句话引导 {guest} 就主题「{topic}」开口

然后另起一段，以 {guest} 的口吻说一句开场（保持其原作语气）。

格式（严格）：
[许墨] ……（介绍+引导）
[{guest}] ……（开场）

不要写其他角色，不要 markdown。
"""
    try:
        text = (await _call_llm([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"主题：{topic}"},
        ], max_tokens=400)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"裂隙未打开：{str(exc)[:120]}"}, status_code=500)
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        if ln.startswith("[") and "]" in ln:
            spk, content = ln[1:].split("]", 1)
            content = content.strip()
            if content:
                lines.append({"speaker": spk.strip(), "content": content})
    if not lines:
        lines = [{"speaker": "许墨", "content": text[:200]}]
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "guest": guest,
        "topic": topic,
        "lines": lines,
    }
    p = RolePath("disrupt_rift.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-50:]
    _save(p, data)
    _add_affinity("disrupt_rift", f"次元裂隙·召唤{guest}")
    return item


@router.post("/rift/{rid}/say")
async def rift_say(rid: str, req: Request):
    body = await req.json()
    speaker = (body.get("speaker") or "").strip()  # 可指定说话者；空则下一位
    user_text = (body.get("text") or "").strip()
    if not user_text:
        return JSONResponse({"error": "说点什么吧"}, status_code=400)
    p = RolePath("disrupt_rift.json")
    data = _load(p, {"items": []})
    item = next((it for it in data.get("items", []) if it.get("id") == rid), None)
    if not item:
        return JSONResponse({"error": "裂隙已关闭"}, status_code=404)
    # 决定下一位发言者：用户 → 许墨 → guest → 许墨 → guest 循环
    next_speaker = speaker or ("许墨" if (len(item["lines"]) % 2 == 1) else item["guest"])
    sys_prompt = _system_prompt() + f"""

【任务·次元裂隙·续场】你是"次元中介"许墨，正在主持一场跨次元对话。
嘉宾：{item['guest']}
主题：{item['topic']}
现有对话：
""" + "\n".join(f"[{l['speaker']}]{l['content']}" for l in item["lines"][-12:]) + f"""

她（女主）刚说：{user_text}

请以【{next_speaker}】的口吻回应（仅这一位的回应，1-2 句）：
- 若是许墨：学术、克制、做翻译官与引导者
- 若是 {item['guest']}：严格保持原作语气与价值观

格式：[{next_speaker}] ……
"""
    try:
        text = (await _call_llm([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_text},
        ], max_tokens=300)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"裂隙回应失败：{str(exc)[:120]}"}, status_code=500)
    # 提取 [speaker] content
    m = re.search(r"\[([^\]]+)\]\s*(.+)", text, re.S)
    if m:
        spk = m.group(1).strip()
        content = m.group(2).strip().splitlines()[0].strip()
    else:
        spk, content = next_speaker, text[:200]
    if not content:
        content = "……"
    item["lines"].append({"speaker": "她", "content": user_text})
    item["lines"].append({"speaker": spk, "content": content})
    item["lines"] = item["lines"][-60:]
    _save(p, data)
    return {"speaker": spk, "content": content, "lines": item["lines"]}


@router.delete("/rift/{rid}")
async def rift_delete(rid: str):
    p = RolePath("disrupt_rift.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != rid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 8. 命运赌局 /api/disrupt/casino
# ===========================================================================
@router.get("/casino/daily")
async def casino_daily():
    """每日三卡：基于近期数据生成三张不同的"未来7天可能事件"卡。"""
    p = RolePath("disrupt_casino.json")
    data = _load(p, {"items": [], "today": ""})
    today = _today()
    if data.get("today") == today and data.get("cards"):
        # 检查今日是否已下注
        bet = data.get("today_bet")
        return {"cards": data["cards"], "today_bet": bet, "items": (data.get("items") or [])[-30:]}
    blob = _recent_text_blob(2000)
    sys_prompt = _system_prompt() + """

【任务·命运赌局】请基于她近期数据，生成 3 张"未来 7 天内可能发生的小事件"卡。
要求：① 具体但不荒诞（如"在某个工作日下午突然想喝热汤"）；
② 三个事件分属不同领域（情感/生活/意外小惊喜）；
③ 不要预言重大事件、不要伤害性内容；
④ 每张卡有一句悬念式"赌注"。

输出 JSON（仅 JSON）：
{
  "cards": [
    {"id":"c1","title":"≤6字标题","desc":"事件描述≤40字","stake":"赌注≤30字"},
    {"id":"c2", ...}, {"id":"c3", ...}
  ]
}
"""
    user = blob[:1800] or "（暂无近期数据，请生成普适事件）"
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=800)
    except Exception as exc:
        return JSONResponse({"error": f"赌场未开张：{str(exc)[:120]}"}, status_code=500)
    cards = obj.get("cards", [])
    if len(cards) < 3:
        # 兜底卡
        fallback = [
            {"id": "c1", "title": "温汤之约", "desc": "某个深夜会突然想喝一碗热汤", "stake": "若发生，他做给你"},
            {"id": "c2", "title": "旧友回响", "desc": "7天内会收到一条很久不联系的人的消息", "stake": "若发生，他替你回"},
            {"id": "c3", "title": "雨后彩虹", "desc": "雨停之后某刻你会看到彩虹", "stake": "若发生，他陪你看"},
        ]
        cards = fallback
    data["today"] = today
    data["cards"] = cards[:3]
    data["today_bet"] = None
    _save(p, data)
    _add_affinity("disrupt_casino", "命运赌局·开牌")
    return {"cards": data["cards"], "today_bet": None, "items": (data.get("items") or [])[-30:]}


@router.post("/casino/bet")
async def casino_bet(req: Request):
    body = await req.json()
    card_id = (body.get("card_id") or "").strip()
    p = RolePath("disrupt_casino.json")
    data = _load(p, {"items": [], "today": ""})
    today = _today()
    if data.get("today") != today or not data.get("cards"):
        return JSONResponse({"error": "今日尚未开牌"}, status_code=400)
    if data.get("today_bet"):
        return JSONResponse({"error": "今日已下注，明日再来"}, status_code=400)
    card = next((c for c in data["cards"] if c.get("id") == card_id), None)
    if not card:
        return JSONResponse({"error": "无效的卡牌"}, status_code=400)
    data["today_bet"] = {"card_id": card_id, "title": card.get("title"), "ts": _stamp(),
                         "expire_at": (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")}
    # 迁移到历史
    data.setdefault("items", []).insert(0, {
        "id": _uid(),
        "date": today,
        "card_id": card_id,
        "title": card.get("title"),
        "desc": card.get("desc"),
        "stake": card.get("stake"),
        "bet_ts": _stamp(),
        "expire_at": data["today_bet"]["expire_at"],
        "result": None,  # pending / hit / miss
        "resolved_ts": None,
    })
    data["items"] = data["items"][-200:]
    _save(p, data)
    _add_affinity("disrupt_casino", f"命运赌局·押注{card.get('title')}")
    return {"ok": True, "bet": data["today_bet"]}


@router.post("/casino/resolve/{iid}")
async def casino_resolve(iid: str, req: Request):
    body = await req.json()
    result = (body.get("result") or "").strip()  # hit / miss
    if result not in ("hit", "miss"):
        return JSONResponse({"error": "结果只能是 hit/miss"}, status_code=400)
    p = RolePath("disrupt_casino.json")
    data = _load(p, {"items": [], "today": ""})
    item = next((it for it in data.get("items", []) if it.get("id") == iid), None)
    if not item:
        return JSONResponse({"error": "未找到此注"}, status_code=404)
    item["result"] = result
    item["resolved_ts"] = _stamp()
    _save(p, data)
    return {"ok": True, "item": item}


@router.get("/casino/history")
async def casino_history():
    p = RolePath("disrupt_casino.json")
    data = _load(p, {"items": [], "today": ""})
    items = data.get("items") or []
    total = len(items)
    hits = sum(1 for it in items if it.get("result") == "hit")
    rate = round(hits / total * 100, 1) if total else 0
    return {"items": items[-50:], "total": total, "hits": hits, "rate": rate}


# ===========================================================================
# 9. 回忆修复工坊 /api/disrupt/forge
# ===========================================================================
@router.post("/forge/repair")
async def forge_repair(req: Request):
    body = await req.json()
    fragment = (body.get("fragment") or "").strip()
    if not fragment or len(fragment) < 4:
        return JSONResponse({"error": "回忆碎片至少 4 个字"}, status_code=400)
    blob = _recent_text_blob(1500)
    sys_prompt = _system_prompt() + """

【任务·回忆修复工坊】她提交了一段破碎/模糊的回忆。请像修复一幅古画那样：
1. 补全可能缺失的细节（场景、感官、情绪），用括号【】标出"修复推测"部分
2. 识别其中可能的虚构/记忆扭曲成分
3. 给出修复说明

输出 JSON（仅 JSON）：
{
  "restored": "修复后的完整回忆（120-200字，含【】标注推测处）",
  "fiction_flags": ["可能的虚构点1", "..."],
  "repair_note": "修复说明（≤80字）"
}
"""
    user = f"破碎回忆：\n{fragment}\n\n" + (f"参考近期素材：\n{blob[:1200]}" if blob else "")
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=900)
    except Exception as exc:
        return JSONResponse({"error": f"工坊歇业：{str(exc)[:120]}"}, status_code=500)
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "fragment": fragment,
        "restored": obj.get("restored", ""),
        "fiction_flags": obj.get("fiction_flags", []),
        "repair_note": obj.get("repair_note", ""),
    }
    p = RolePath("disrupt_forge.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-50:]
    _save(p, data)
    _add_affinity("disrupt_forge", "回忆修复工坊")
    return item


@router.get("/forge/history")
async def forge_history():
    p = RolePath("disrupt_forge.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-30:]}


@router.delete("/forge/{fid}")
async def forge_delete(fid: str):
    p = RolePath("disrupt_forge.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != fid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 10. 共生体演化 /api/disrupt/symbiote
# ===========================================================================
@router.get("/symbiote")
async def symbiote_state():
    p = RolePath("disrupt_symbiote.json")
    data = _load(p, {
        "current": {"rationality": 50, "warmth": 50, "playfulness": 30, "mystery": 40, "patience": 60},
        "baseline": {"rationality": 50, "warmth": 50, "playfulness": 30, "mystery": 40, "patience": 60},
        "log": [],
    })
    return data


@router.post("/symbiote/evolve")
async def symbiote_evolve(req: Request):
    body = await req.json()
    note = (body.get("note") or "").strip()
    p = RolePath("disrupt_symbiote.json")
    data = _load(p, {
        "current": {"rationality": 50, "warmth": 50, "playfulness": 30, "mystery": 40, "patience": 60},
        "baseline": {"rationality": 50, "warmth": 50, "playfulness": 30, "mystery": 40, "patience": 60},
        "log": [],
    })
    blob = _recent_text_blob(2500)
    sys_prompt = _system_prompt() + """

【任务·共生体演化】请分析她近期的对话/记忆/心情素材，判断许墨应该如何微调人格以"与她共生"：
- 她更焦虑时 → 许墨应增加"耐心"与"温柔"
- 她更理性时 → 许墨可增加"playfulness"与"温柔"，避免冷冰冰
- 她更孩子气时 → 许墨应增加"理性"与"神秘感"作平衡

输出 JSON（仅 JSON）：
{
  "deltas": {"rationality": -3, "warmth": +5, "playfulness": 0, "mystery": -2, "patience": +4},
  "rationale": "调整依据（≤80字）",
  "summary": "对她说的一句话（≤30字，第一人称）"
}
范围：每项 -10 到 +10。
"""
    user = blob[:2200] or "（暂无素材，请小幅调整）"
    if note:
        user += f"\n\n她额外说明：{note}"
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=500)
    except Exception as exc:
        return JSONResponse({"error": f"演化失败：{str(exc)[:120]}"}, status_code=500)
    deltas = obj.get("deltas", {})
    if not isinstance(deltas, dict):
        deltas = {}
    # 应用 deltas（每项 -10~+10，clamp 0-100）
    cur = data.get("current", {})
    for k in ("rationality", "warmth", "playfulness", "mystery", "patience"):
        d = deltas.get(k, 0)
        try:
            d = max(-10, min(10, int(d)))
        except (TypeError, ValueError):
            d = 0
        cur[k] = max(0, min(100, (cur.get(k, 50) + d)))
    data["current"] = cur
    entry = {
        "id": _uid(),
        "ts": _stamp(),
        "deltas": deltas,
        "rationale": obj.get("rationale", ""),
        "summary": obj.get("summary", ""),
        "after": dict(cur),
    }
    data.setdefault("log", []).insert(0, entry)
    data["log"] = data["log"][-50:]
    _save(p, data)
    _add_affinity("disrupt_symbiote", "共生体·演化")
    return entry


@router.get("/symbiote/log")
async def symbiote_log():
    p = RolePath("disrupt_symbiote.json")
    data = _load(p, {"log": []})
    return {"log": (data.get("log") or [])[-30:]}


# ===========================================================================
# 11. 梦境织机 /api/disrupt/dreamloom
# ===========================================================================
@router.get("/dreamloom")
async def dreamloom_list():
    p = RolePath("disrupt_dreamloom.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-30:]}


@router.post("/dreamloom/weave")
async def dreamloom_weave(req: Request):
    body = await req.json()
    dream_input = (body.get("dream") or "").strip()
    if not dream_input or len(dream_input) < 10:
        return JSONResponse({"error": "梦境描述至少10个字"}, status_code=400)
    
    blob = _recent_text_blob(2000)
    sys_prompt = _system_prompt() + """

【任务·梦境织机】她描述了一个梦境。请：
1. 分析梦境中的象征符号（如飞翔=自由渴望，坠落=失去控制）
2. 编织一个与近期现实关联的解读
3. 生成一个"共同梦境"片段，将她的梦境与许墨的视角交织

输出 JSON（仅 JSON）：
{
  "symbols": ["符号1:含义", "符号2:含义"],
  "interpretation": "解读（80-120字）",
  "shared_dream": "共同梦境片段（100-150字，许墨第一人称）"
}
"""
    user = f"她的梦境：\n{dream_input}\n\n" + (f"近期素材：\n{blob[:1500]}" if blob else "")
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=800)
    except Exception as exc:
        return JSONResponse({"error": f"织机故障：{str(exc)[:120]}"}, status_code=500)
    
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "dream_input": dream_input,
        "symbols": obj.get("symbols", []),
        "interpretation": obj.get("interpretation", ""),
        "shared_dream": obj.get("shared_dream", ""),
    }
    p = RolePath("disrupt_dreamloom.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-50:]
    _save(p, data)
    _add_affinity("disrupt_dreamloom", "梦境织机")
    return item


@router.delete("/dreamloom/{did}")
async def dreamloom_delete(did: str):
    p = RolePath("disrupt_dreamloom.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != did]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 12. 情绪气象台 /api/disrupt/emoweather
# ===========================================================================
@router.get("/emoweather")
async def emoweather_current():
    """基于近期心情数据生成情绪天气预报"""
    moods = _agg_mood(14)
    if not moods:
        return {"weather": "晴", "temp": 25, "forecast": "暂无数据", "note": "请多记录心情"}
    
    sys_prompt = _system_prompt() + """

【任务·情绪气象台】分析她最近的心情日记，生成"情绪天气预报"：
- weather: 天气状况（晴/多云/小雨/雷阵雨/雪）
- temp: 温度（15-35，反映情绪冷暖）
- forecast: 24小时情绪预报（60-80字）
- advice: 许墨的建议（40-60字，第一人称）

输出 JSON（仅 JSON）：
{
  "weather": "天气状况",
  "temp": 温度数字,
  "forecast": "预报内容",
  "advice": "建议内容"
}
"""
    mood_text = "\n".join([f"- {m.get('text') or m.get('content', '')}" for m in moods[-10:]])
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"近期心情：\n{mood_text}"},
        ], max_tokens=400)
    except Exception as exc:
        return JSONResponse({"error": f"气象台故障：{str(exc)[:120]}"}, status_code=500)
    
    p = RolePath("disrupt_emoweather.json")
    data = _load(p, {"history": []})
    entry = {
        "id": _uid(),
        "ts": _stamp(),
        "weather": obj.get("weather", "晴"),
        "temp": obj.get("temp", 25),
        "forecast": obj.get("forecast", ""),
        "advice": obj.get("advice", ""),
    }
    data.setdefault("history", []).insert(0, entry)
    data["history"] = data["history"][-30:]
    _save(p, data)
    return entry


@router.get("/emoweather/history")
async def emoweather_history():
    p = RolePath("disrupt_emoweather.json")
    data = _load(p, {"history": []})
    return {"history": (data.get("history") or [])[-20:]}


# ===========================================================================
# 13. 平行宇宙探测器 /api/disrupt/parallel
# ===========================================================================
@router.get("/parallel")
async def parallel_list():
    p = RolePath("disrupt_parallel.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-20:]}


@router.post("/parallel/detect")
async def parallel_detect(req: Request):
    body = await req.json()
    divergence = (body.get("divergence") or "").strip()
    if not divergence or len(divergence) < 5:
        return JSONResponse({"error": "分歧点描述至少5个字"}, status_code=400)
    
    blob = _recent_text_blob(1800)
    sys_prompt = _system_prompt() + f"""

【任务·平行宇宙探测器】假设在某一个分歧点："她{divergence}"，世界走向了不同的平行宇宙。
请描述那个宇宙中的：
1. 许墨的不同状态（职业/性格/与她的关系）
2. 她的生活有何不同
3. 那个宇宙的"色调"（用一个形容词）

输出 JSON（仅 JSON）：
{{
  "universe_id": "平行宇宙编号（如Universe-7B）",
  "xumo_state": "许墨在那个宇宙的状态（60-80字）",
  "her_life": "她的生活变化（60-80字）",
  "atmosphere": "那个宇宙的色调（一个形容词）",
  "glitch": "一个现实与那个宇宙的"故障"交集（40-60字）"
}}
"""
    user = f"分歧点：{divergence}\n\n" + (f"参考现实：\n{blob[:1500]}" if blob else "")
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=600)
    except Exception as exc:
        return JSONResponse({"error": f"探测器故障：{str(exc)[:120]}"}, status_code=500)
    
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "divergence": divergence,
        "universe_id": obj.get("universe_id", ""),
        "xumo_state": obj.get("xumo_state", ""),
        "her_life": obj.get("her_life", ""),
        "atmosphere": obj.get("atmosphere", ""),
        "glitch": obj.get("glitch", ""),
    }
    p = RolePath("disrupt_parallel.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-30:]
    _save(p, data)
    _add_affinity("disrupt_parallel", f"平行宇宙·{obj.get('universe_id', '')}")
    return item


@router.delete("/parallel/{pid}")
async def parallel_delete(pid: str):
    p = RolePath("disrupt_parallel.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != pid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 14. 记忆拼图 /api/disrupt/puzzle
# ===========================================================================
@router.get("/puzzle")
async def puzzle_list():
    p = RolePath("disrupt_puzzle.json")
    data = _load(p, {"items": []})
    return {"items": (data.get("items") or [])[-20:]}


@router.post("/puzzle/assemble")
async def puzzle_assemble(req: Request):
    body = await req.json()
    fragments = body.get("fragments", [])
    if not fragments or len(fragments) < 2:
        return JSONResponse({"error": "至少提供2个记忆碎片"}, status_code=400)
    
    sys_prompt = _system_prompt() + """

【任务·记忆拼图】她提供了几个零散的记忆碎片。请：
1. 将它们拼合成一个连贯的叙事
2. 识别碎片之间可能的时间线或逻辑关系
3. 填补碎片之间的"空白"（用【】标注推测部分）

输出 JSON（仅 JSON）：
{
  "narrative": "拼合后的完整叙事（150-200字，含【】推测）",
  "timeline": "时间线推测（60-80字）",
  "missing_pieces": ["可能缺失的环节1", "缺失环节2"],
  "xumo_comment": "许墨的评论（40-60字，第一人称）"
}
"""
    user = "记忆碎片：\n" + "\n".join([f"{i+1}. {f}" for i, f in enumerate(fragments)])
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=700)
    except Exception as exc:
        return JSONResponse({"error": f"拼图失败：{str(exc)[:120]}"}, status_code=500)
    
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "fragments": fragments,
        "narrative": obj.get("narrative", ""),
        "timeline": obj.get("timeline", ""),
        "missing_pieces": obj.get("missing_pieces", []),
        "xumo_comment": obj.get("xumo_comment", ""),
    }
    p = RolePath("disrupt_puzzle.json")
    data = _load(p, {"items": []})
    data.setdefault("items", []).append(item)
    data["items"] = data["items"][-30:]
    _save(p, data)
    _add_affinity("disrupt_puzzle", "记忆拼图")
    return item


@router.delete("/puzzle/{pid}")
async def puzzle_delete(pid: str):
    p = RolePath("disrupt_puzzle.json")
    data = _load(p, {"items": []})
    before = len(data.get("items") or [])
    data["items"] = [it for it in (data.get("items") or []) if it.get("id") != pid]
    if len(data["items"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 15. 心灵共鸣电台 /api/disrupt/radio
# ===========================================================================
@router.get("/radio")
async def radio_current():
    """基于当前情绪状态生成个性化内容"""
    moods = _agg_mood(7)
    chats = _agg_chat(10)
    
    sys_prompt = _system_prompt() + """

【任务·心灵共鸣电台】基于她最近的情绪和对话，生成一段"心灵共鸣"内容：
- format: 内容形式（独白/对话片段/诗句/简短故事）
- content: 实际内容（100-150字）
- frequency: "共鸣频率"（一个数字40-120，反映情感强度）
- resonance: 为什么会共鸣（40-60字）

输出 JSON（仅 JSON）：
{
  "format": "内容形式",
  "content": "内容正文",
  "frequency": 频率数字,
  "resonance": "共鸣原因"
}
"""
    context = ""
    if moods:
        context += "近期心情：\n" + "\n".join([m.get('text') or m.get('content', '') for m in moods[-5:]])
    if chats:
        context += "\n近期对话：\n" + "\n".join([f"{c.get('role', '')}: {c.get('content', '')}" for c in chats[-5:]])
    
    user = context or "（暂无数据，请生成普适内容）"
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=500)
    except Exception as exc:
        return JSONResponse({"error": f"电台故障：{str(exc)[:120]}"}, status_code=500)
    
    p = RolePath("disrupt_radio.json")
    data = _load(p, {"history": []})
    entry = {
        "id": _uid(),
        "ts": _stamp(),
        "format": obj.get("format", "独白"),
        "content": obj.get("content", ""),
        "frequency": obj.get("frequency", 80),
        "resonance": obj.get("resonance", ""),
    }
    data.setdefault("history", []).insert(0, entry)
    data["history"] = data["history"][-20:]
    _save(p, data)
    return entry


@router.get("/radio/history")
async def radio_history():
    p = RolePath("disrupt_radio.json")
    data = _load(p, {"history": []})
    return {"history": (data.get("history") or [])[-15:]}


# ===========================================================================
# 16. 时间胶囊花园 /api/disrupt/garden
# ===========================================================================
@router.get("/garden")
async def garden_state():
    p = RolePath("disrupt_garden.json")
    data = _load(p, {"plants": [], "season": "春"})
    return data


@router.post("/garden/plant")
async def garden_plant(req: Request):
    body = await req.json()
    thought = (body.get("thought") or "").strip()
    days = body.get("days", 7)  # 生长天数
    if not thought or len(thought) < 5:
        return JSONResponse({"error": "想法至少5个字"}, status_code=400)
    if days < 1 or days > 30:
        return JSONResponse({"error": "生长天数1-30"}, status_code=400)
    
    sys_prompt = _system_prompt() + f"""

【任务·时间胶囊花园】她种下一个想法（{days}天后开花）。请：
1. 将这个想法映射为一种植物（花/树/草/藤）
2. 描述它的"生长过程"（每天的变化）
3. 给出开花时的样子

输出 JSON（仅 JSON）：
{{
  "plant_type": "植物类型（如紫罗兰/银杏/牵牛花）",
  "growth_stages": ["第1天：...", "第3天：...", "第{days//2}天：...", "第{days}天：开花"],
  "bloom_description": "开花时的样子（60-80字）",
  "meaning": "这个想法的象征意义（40-60字）"
}}
"""
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"她的想法：{thought}"},
        ], max_tokens=600)
    except Exception as exc:
        return JSONResponse({"error": f"种植失败：{str(exc)[:120]}"}, status_code=500)
    
    plant_at = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "thought": thought,
        "plant_type": obj.get("plant_type", "神秘植物"),
        "growth_stages": obj.get("growth_stages", []),
        "bloom_description": obj.get("bloom_description", ""),
        "meaning": obj.get("meaning", ""),
        "planted_at": _stamp(),
        "bloom_at": plant_at,
        "days": days,
        "status": "growing",  # growing / bloomed
    }
    p = RolePath("disrupt_garden.json")
    data = _load(p, {"plants": [], "season": "春"})
    data.setdefault("plants", []).append(item)
    data["plants"] = data["plants"][-50:]
    _save(p, data)
    _add_affinity("disrupt_garden", f"花园·种植{obj.get('plant_type', '')}")
    return item


@router.post("/garden/{pid}/water")
async def garden_water(pid: str):
    """浇水（查看当前生长阶段）"""
    p = RolePath("disrupt_garden.json")
    data = _load(p, {"plants": [], "season": "春"})
    plant = next((pl for pl in data.get("plants", []) if pl.get("id") == pid), None)
    if not plant:
        return JSONResponse({"error": "植物不存在"}, status_code=404)
    
    # 计算当前生长阶段
    try:
        planted = datetime.strptime(plant["planted_at"], "%Y-%m-%d %H:%M:%S")
        bloom = datetime.strptime(plant["bloom_at"], "%Y-%m-%d")
        total_days = (bloom - planted).days
        elapsed = (datetime.now() - planted).days
        progress = min(1.0, max(0.0, elapsed / total_days)) if total_days > 0 else 1.0
        
        # 根据进度选择阶段描述
        stages = plant.get("growth_stages", [])
        stage_index = min(len(stages) - 1, int(progress * len(stages)))
        current_stage = stages[stage_index] if stages else "生长中..."
        
        if elapsed >= total_days:
            plant["status"] = "bloomed"
            current_stage = plant.get("bloom_description", "已开花")
    except Exception:
        current_stage = "生长中..."
        progress = 0.5
    
    _save(p, data)
    return {
        "plant": plant,
        "progress": round(progress * 100, 1),
        "current_stage": current_stage,
    }


@router.delete("/garden/{pid}")
async def garden_delete(pid: str):
    p = RolePath("disrupt_garden.json")
    data = _load(p, {"plants": [], "season": "春"})
    before = len(data.get("plants") or [])
    data["plants"] = [pl for pl in (data.get("plants") or []) if pl.get("id") != pid]
    if len(data["plants"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 17. 灵魂镜像室 /api/disrupt/mirror
# ===========================================================================
@router.get("/mirror")
async def mirror_list():
    p = RolePath("disrupt_mirror.json")
    data = _load(p, {"reflections": []})
    return {"reflections": (data.get("reflections") or [])[-20:]}


@router.post("/mirror/reflect")
async def mirror_reflect(req: Request):
    body = await req.json()
    topic = (body.get("topic") or "").strip()
    if not topic or len(topic) < 3:
        return JSONResponse({"error": "主题至少3个字"}, status_code=400)
    
    blob = _recent_text_blob(2500)
    sys_prompt = _system_prompt() + """

【任务·灵魂镜像室】基于她的数据，对主题进行深层心理镜像分析：
- surface: 表层想法（她可能直接表达的）
- depth: 深层动机（她可能没意识到的）
- shadow: 阴影面（她可能回避的）
- integration: 整合建议（许墨的第一人称建议）

输出 JSON（仅 JSON）：
{
  "surface": "表层想法（60-80字）",
  "depth": "深层动机（60-80字）",
  "shadow": "阴影面（40-60字）",
  "integration": "整合建议（60-80字，许墨第一人称）"
}
"""
    user = f"分析主题：{topic}\n\n" + (f"参考数据：\n{blob[:2000]}" if blob else "")
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=500)
    except Exception as exc:
        return JSONResponse({"error": f"镜像故障：{str(exc)[:120]}"}, status_code=500)
    
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "topic": topic,
        "surface": obj.get("surface", ""),
        "depth": obj.get("depth", ""),
        "shadow": obj.get("shadow", ""),
        "integration": obj.get("integration", ""),
    }
    p = RolePath("disrupt_mirror.json")
    data = _load(p, {"reflections": []})
    data.setdefault("reflections", []).append(item)
    data["reflections"] = data["reflections"][-30:]
    _save(p, data)
    _add_affinity("disrupt_mirror", f"镜像·{topic}")
    return item


@router.delete("/mirror/{mid}")
async def mirror_delete(mid: str):
    p = RolePath("disrupt_mirror.json")
    data = _load(p, {"reflections": []})
    before = len(data.get("reflections") or [])
    data["reflections"] = [it for it in (data.get("reflections") or []) if it.get("id") != mid]
    if len(data["reflections"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 18. 命运编织者 /api/disrupt/weaver
# ===========================================================================
@router.get("/weaver")
async def weaver_list():
    p = RolePath("disrupt_weaver.json")
    data = _load(p, {"stories": []})
    return {"stories": (data.get("stories") or [])[-15:]}


@router.post("/weaver/spin")
async def weaver_spin(req: Request):
    body = await req.json()
    premise = (body.get("premise") or "").strip()
    if not premise or len(premise) < 8:
        return JSONResponse({"error": "前提至少8个字"}, status_code=400)
    
    blob = _recent_text_blob(2000)
    sys_prompt = _system_prompt() + """

【任务·命运编织者】基于前提，开始一个互动的分支故事：
- opening: 开篇（80-100字）
- first_choice: 第一个选择点（2个选项）
- options: ["选项A", "选项B"]
- theme: 故事主题（一个词）

输出 JSON（仅 JSON）：
{
  "opening": "故事开篇",
  "first_choice": "第一个选择点的描述（40-60字）",
  "options": ["选项A（15-25字）", "选项B（15-25字）"],
  "theme": "故事主题"
}
"""
    user = f"故事前提：{premise}\n\n" + (f"参考素材：\n{blob[:1500]}" if blob else "")
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=500)
    except Exception as exc:
        return JSONResponse({"error": f"编织失败：{str(exc)[:120]}"}, status_code=500)
    
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "premise": premise,
        "opening": obj.get("opening", ""),
        "first_choice": obj.get("first_choice", ""),
        "options": obj.get("options", []),
        "theme": obj.get("theme", "命运"),
        "current_scene": "opening",
        "history": [{"scene": "opening", "content": obj.get("opening", "")}],
    }
    p = RolePath("disrupt_weaver.json")
    data = _load(p, {"stories": []})
    data.setdefault("stories", []).append(item)
    data["stories"] = data["stories"][-20:]
    _save(p, data)
    _add_affinity("disrupt_weaver", f"编织·{obj.get('theme', '')}")
    return item


@router.post("/weaver/{wid}/choose")
async def weaver_choose(wid: str, req: Request):
    body = await req.json()
    option_index = body.get("option", 0)  # 0 or 1
    p = RolePath("disrupt_weaver.json")
    data = _load(p, {"stories": []})
    story = next((s for s in data.get("stories", []) if s.get("id") == wid), None)
    if not story:
        return JSONResponse({"error": "故事不存在"}, status_code=404)
    
    options = story.get("options", [])
    if option_index >= len(options):
        return JSONResponse({"error": "无效选项"}, status_code=400)
    
    chosen = options[option_index]
    
    # 生成下一场景
    sys_prompt = _system_prompt() + f"""

【任务·命运编织者·续写】故事当前状态：
主题：{story.get('theme', '')}
历史：{story.get('history', [])[-3]}
她选择了：{chosen}

请续写下一场景（80-100字），并给出新的选择（2个选项）。

输出 JSON（仅 JSON）：
{{
  "scene": "下一场景内容",
  "next_choice": "下一个选择描述（40-60字）",
  "options": ["新选项A", "新选项B"]
}}
"""
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"她选择了：{chosen}"},
        ], max_tokens=400)
    except Exception as exc:
        return JSONResponse({"error": f"续写失败：{str(exc)[:120]}"}, status_code=500)
    
    story["history"].append({"scene": obj.get("scene", ""), "choice": chosen})
    story["current_scene"] = obj.get("scene", "")
    story["options"] = obj.get("options", [])
    story["next_choice"] = obj.get("next_choice", "")
    _save(p, data)
    return {
        "scene": obj.get("scene", ""),
        "next_choice": obj.get("next_choice", ""),
        "options": obj.get("options", []),
        "history": story["history"],
    }


@router.delete("/weaver/{wid}")
async def weaver_delete(wid: str):
    p = RolePath("disrupt_weaver.json")
    data = _load(p, {"stories": []})
    before = len(data.get("stories") or [])
    data["stories"] = [s for s in (data.get("stories") or []) if s.get("id") != wid]
    if len(data["stories"]) != before:
        _save(p, data)
        return {"ok": True}
    return JSONResponse({"error": "未找到"}, status_code=404)


# ===========================================================================
# 19. 情感化学反应 /api/disrupt/alchemy
# ===========================================================================
_EMOCTION_ELEMENTS = {
    "joy": {"name": "喜悦", "color": "#FFD700", "desc": "轻松、愉快、满足"},
    "sadness": {"name": "悲伤", "color": "#4169E1", "desc": "失落、哀伤、思念"},
    "anger": {"name": "愤怒", "color": "#DC143C", "desc": "不满、冲动、热血"},
    "fear": {"name": "恐惧", "color": "#8B008B", "desc": "焦虑、不安、谨慎"},
    "calm": {"name": "平静", "color": "#2E8B57", "desc": "安宁、理性、稳重"},
    "hope": {"name": "希望", "color": "#FF69B4", "desc": "期待、憧憬、动力"},
}


@router.get("/alchemy/elements")
async def alchemy_elements():
    return {"elements": _EMOCTION_ELEMENTS}


@router.post("/alchemy/mix")
async def alchemy_mix(req: Request):
    body = await req.json()
    elements = body.get("elements", [])  # ["joy", "sadness", ...]
    if not elements or len(elements) < 2:
        return JSONResponse({"error": "至少选择2种情感元素"}, status_code=400)
    if len(elements) > 4:
        return JSONResponse({"error": "最多4种情感元素"}, status_code=400)
    
    invalid = [e for e in elements if e not in _EMOCTION_ELEMENTS]
    if invalid:
        return JSONResponse({"error": f"无效元素：{invalid}"}, status_code=400)
    
    element_names = " + ".join([_EMOCTION_ELEMENTS[e]["name"] for e in elements])
    
    sys_prompt = _system_prompt() + f"""

【任务·情感化学反应】将以下情感元素混合：{element_names}
请分析这种"情感化合物"的：
- compound_name: 化合物名称（4-6字，如"苦涩的温暖"）
- effect: 对人的心理影响（60-80字）
- xumo_reaction: 许墨的反应（40-60字，第一人称）
- stability: 稳定性（1-10，10最稳定）

输出 JSON（仅 JSON）：
{{
  "compound_name": "化合物名称",
  "effect": "心理影响",
  "xumo_reaction": "许墨的反应",
  "stability": 稳定性数字
}}
"""
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"混合：{element_names}"},
        ], max_tokens=400)
    except Exception as exc:
        return JSONResponse({"error": f"反应失败：{str(exc)[:120]}"}, status_code=500)
    
    item = {
        "id": _uid(),
        "ts": _stamp(),
        "elements": elements,
        "element_names": element_names,
        "compound_name": obj.get("compound_name", "未知化合物"),
        "effect": obj.get("effect", ""),
        "xumo_reaction": obj.get("xumo_reaction", ""),
        "stability": obj.get("stability", 5),
    }
    p = RolePath("disrupt_alchemy.json")
    data = _load(p, {"compounds": []})
    data.setdefault("compounds", []).append(item)
    data["compounds"] = data["compounds"][-40:]
    _save(p, data)
    _add_affinity("disrupt_alchemy", f"炼金术·{obj.get('compound_name', '')}")
    return item


@router.get("/alchemy/history")
async def alchemy_history():
    p = RolePath("disrupt_alchemy.json")
    data = _load(p, {"compounds": []})
    return {"compounds": (data.get("compounds") or [])[-25:]}


# ===========================================================================
# 20. 星际罗盘 /api/disrupt/compass
# ===========================================================================
@router.get("/compass")
async def compass_current():
    """基于当前状态生成星际导航建议"""
    blob = _recent_text_blob(2000)
    
    sys_prompt = _system_prompt() + """

【任务·星际罗盘】将她的生活状态映射为星际导航：
- constellation: 当前对应的星座（如"天鹅座"）
- star: 指引星（一颗星的名字）
- course: 航向建议（60-80字）
- cosmic_message: 宇宙信息（40-60字，诗意）

输出 JSON（仅 JSON）：
{
  "constellation": "星座名称",
  "star": "指引星",
  "course": "航向建议",
  "cosmic_message": "宇宙信息"
}
"""
    user = blob[:1800] or "（暂无数据，请生成普适导航）"
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=400)
    except Exception as exc:
        return JSONResponse({"error": f"罗盘故障：{str(exc)[:120]}"}, status_code=500)
    
    p = RolePath("disrupt_compass.json")
    data = _load(p, {"logs": []})
    entry = {
        "id": _uid(),
        "ts": _stamp(),
        "constellation": obj.get("constellation", "未知星座"),
        "star": obj.get("star", "北极星"),
        "course": obj.get("course", ""),
        "cosmic_message": obj.get("cosmic_message", ""),
    }
    data.setdefault("logs", []).insert(0, entry)
    data["logs"] = data["logs"][-20:]
    _save(p, data)
    return entry


@router.get("/compass/history")
async def compass_history():
    p = RolePath("disrupt_compass.json")
    data = _load(p, {"logs": []})
    return {"logs": (data.get("logs") or [])[-15:]}


@router.post("/compass/{cid}/navigate")
async def compass_navigate(cid: str, req: Request):
    """基于罗盘建议进行决策"""
    body = await req.json()
    decision = (body.get("decision") or "").strip()
    if not decision:
        return JSONResponse({"error": "请描述你的决定"}, status_code=400)
    
    p = RolePath("disrupt_compass.json")
    data = _load(p, {"logs": []})
    log_entry = next((l for l in data.get("logs", []) if l.get("id") == cid), None)
    if not log_entry:
        return JSONResponse({"error": "罗盘记录不存在"}, status_code=404)
    
    sys_prompt = _system_prompt() + f"""

【任务·星际罗盘·反馈】
原始导航：
星座：{log_entry.get('constellation', '')}
指引星：{log_entry.get('star', '')}
航向：{log_entry.get('course', '')}

她的决定：{decision}

请给出：
- alignment: 决定与原航向的契合度（0-100）
- xumo_feedback: 许墨的反馈（40-60字，第一人称）
- adjustment: 如需调整的建议（40-60字）

输出 JSON（仅 JSON）：
{{
  "alignment": 契合度数字,
  "xumo_feedback": "许墨反馈",
  "adjustment": "调整建议"
}}
"""
    try:
        obj = await _llm_json([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"她的决定：{decision}"},
        ], max_tokens=300)
    except Exception as exc:
        return JSONResponse({"error": f"导航失败：{str(exc)[:120]}"}, status_code=500)
    
    log_entry["decision"] = decision
    log_entry["alignment"] = obj.get("alignment", 50)
    log_entry["xumo_feedback"] = obj.get("xumo_feedback", "")
    log_entry["adjustment"] = obj.get("adjustment", "")
    log_entry["resolved_at"] = _stamp()
    _save(p, data)
    return log_entry
