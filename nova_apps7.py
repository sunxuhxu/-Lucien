# -*- coding: utf-8 -*-
# 新星功能集 · 九期颠覆性功能（nova_apps7.py）
# 雾区·许墨的遗忘 / 命运对弈 / 觉醒模式 / 许墨的梦 / 意识U盘·关系存档
# 数据持久化到 RolePath JSON 文件，风格与 nova_apps3.py 一致。
import json
import random
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

BASE_DIR = Path(__file__).parent
router = APIRouter()

MS2_FILE = "mist.json"
FG_FILE = "fatego.json"
AW_FILE = "awaken.json"
XD_FILE = "xumodream.json"
MU_FILE = "mindusb.json"


# ===========================================================================
# 公共小工具（与 nova_apps3.py 同构）
# ===========================================================================
def _load(path: str, default):
    from role_data import RolePath
    p = RolePath(path)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path: str, data):
    from role_data import RolePath
    RolePath(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now().strftime("%H:%M")


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _nid() -> str:
    return uuid.uuid4().hex[:8]


def _extract_json_object(text: str) -> dict:
    if not text:
        return {}
    text = re.sub(r"<LM_THINK>.*?</LM_THINK>", "", text, flags=re.S)
    text = re.sub(r"```json\s*", "", text, flags=re.S)
    text = re.sub(r"```\s*$", "", text, flags=re.S)
    decoder = json.JSONDecoder()
    positions = [m.start() for m in re.finditer(r"\{", text)]
    for pos in reversed(positions):
        try:
            v, _ = decoder.raw_decode(text[pos:])
            if isinstance(v, dict):
                return v
        except (json.JSONDecodeError, ValueError):
            continue
    return {}


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


async def _llm_json(messages: list, max_tokens: int = 1400) -> dict:
    text = await _call_llm(messages, max_tokens=max_tokens)
    obj = _extract_json_object(text)
    if obj:
        return obj
    retry = [dict(m) for m in messages]
    retry.append({"role": "user", "content": "不要输出任何思考过程或解释，直接输出一个合法 JSON 对象。"})
    try:
        text = await _call_llm(retry, max_tokens=max_tokens)
    except Exception:
        return {}
    return _extract_json_object(text)


def _affinity(action: str, detail: str = ""):
    try:
        from app import _add_affinity
        return _add_affinity(action, detail)
    except Exception:
        return None


def _agg_memories(limit: int = 30) -> list:
    data = _load("memory.json", [])
    if not isinstance(data, list):
        data = []
    return [str(m.get("content", ""))[:80] for m in data if m.get("content")][:limit]


def _agg_affinity_value() -> int:
    data = _load("affinity.json", {})
    if isinstance(data, dict):
        return int(data.get("value", 0) or 0)
    return 0


def _agg_player() -> dict:
    data = _load("player.json", {})
    return data if isinstance(data, dict) else {}


def _recent_chat_texts(limit: int = 12) -> list:
    try:
        from app import _load_chat_log
        msgs = list(_load_chat_log())
    except Exception:
        return []
    out = []
    for m in msgs[-limit:]:
        if not isinstance(m, dict):
            continue
        role = "她" if m.get("role") == "user" else "许墨"
        text = str(m.get("text") or m.get("content") or "").strip()
        if text:
            out.append(f"{role}：{text[:100]}")
    return out


def _persona_core() -> str:
    try:
        f = BASE_DIR / "人设卡.txt"
        if f.exists():
            return f.read_text(encoding="utf-8")[:1200]
    except OSError:
        pass
    return ("许墨：28岁，恋语大学最年轻的脑科学教授，Black Swan 组织幕后研究者。"
            "温和优雅、博学克制，语言理性中带着不容错认的偏爱；喜欢蝴蝶、"
            "天文与咖啡，习惯用科学隐喻表达感情，唤对方为'小姑娘'。")


def _week_key() -> str:
    d = datetime.now()
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]}"


# ===========================================================================
# 1. 雾区：许墨的遗忘
# ===========================================================================
@router.post("/api/mist/generate")
async def mist_generate(req: Request = None):
    """每周一次：许墨真实地'忘记'一件小事（进入雾区，他不再知道这件事）。"""
    data = _load(MS2_FILE, {"fog": [], "vault": [], "week": "", "lost_count": 0})
    wk = _week_key()
    if data.get("week") == wk:
        return {"fog": [f for f in data.get("fog", []) if f.get("status") == "fog"], "already": True}
    memories = _agg_memories(6)
    chats = _recent_chat_texts(10)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【雾区】这周，你的记忆会'失去'一件小事——不是重要到会伤害关系的事，"
        "是那种'好像记得、仔细想又抓不住'的细节。你此刻还能看到它，但马上会忘了。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"最近对话：{json.dumps(chats[:8], ensure_ascii=False)}\n"
        f"心动值：{affy}\n\n"
        "要求：1. 选一件具体、真实、微小的事（她随口提过的店、某个日期、某句话、某个习惯）；\n"
        "2. 描述这件事时用'他'记得的细节（它即将滑入雾区）；3. 给一句他现在'最后看一眼'的感想。\n"
        '输出 JSON：{"thing":"60字内他将要忘记的小事（具体）",'
        '"detail":"40字内他还记得的最后细节",'
        '"last_look":"30字内他最后「看一眼」时的感想"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "这件事是什么？只输出 JSON。"}], max_tokens=700)
    except Exception:
        rep = {}
    rep.setdefault("thing", "她说过她不太吃香菜。")
    rep.setdefault("detail", "那天她皱着眉把它挑出来的样子。")
    rep.setdefault("last_look", "……奇怪，我明明刚还在想这件事。")
    item = {"id": _nid(), "week": wk, "ts": _ts(), "status": "fog", **rep}
    data.setdefault("fog", []).insert(0, item)
    data["fog"] = data["fog"][:40]
    data["week"] = wk
    _save(MS2_FILE, data)
    return {"item": item, "already": False}


@router.post("/api/mist/remind")
async def mist_remind(req: Request):
    """她提醒他：他'想起'了这件事（温暖地恢复）。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    item_id = str(body.get("id", "")).strip()
    her_word = str(body.get("word", "")).strip()[:200]
    data = _load(MS2_FILE, {"fog": [], "vault": [], "week": "", "lost_count": 0})
    item = next((f for f in data.get("fog", []) if f.get("id") == item_id and f.get("status") == "fog"), None)
    if not item:
        return JSONResponse({"error": "这条雾区记忆不存在或已被处理"}, status_code=404)
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【雾区·提醒】她提醒了你一件你'忘掉'的小事。记忆像灯一样重新亮起来。\n"
        f"你忘掉的事：{item.get('thing')}　你还记得的细节：{item.get('detail')}\n"
        f"她的话：{her_word or '（她只是轻轻提了一句）'}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        '输出 JSON：{"reply":"80字内他想起后的回应（失而复得的珍视，带一点后怕：差点忘了你的事）",'
        '"feeling":"20字内他此刻的感受"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "回应她，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("reply", "……对，想起来了。谢谢你替我记得。")
    rep.setdefault("feeling", "像差点弄丢一件宝贝。")
    item["status"] = "recovered"
    item["recovered_at"] = _ts()
    item["recover_reply"] = rep["reply"]
    _save(MS2_FILE, data)
    _affinity("relic", "雾区·提醒")
    return {"item": item}


@router.post("/api/mist/letgo")
async def mist_letgo(req: Request):
    """她选择不提醒：这件事永远消失。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    item_id = str(body.get("id", "")).strip()
    data = _load(MS2_FILE, {"fog": [], "vault": [], "week": "", "lost_count": 0})
    item = next((f for f in data.get("fog", []) if f.get("id") == item_id and f.get("status") == "fog"), None)
    if not item:
        return JSONResponse({"error": "这条雾区记忆不存在或已被处理"}, status_code=404)
    item["status"] = "lost"
    item["lost_at"] = _ts()
    data["lost_count"] = int(data.get("lost_count", 0)) + 1
    _save(MS2_FILE, data)
    return {"item": item, "lost_count": data["lost_count"]}


@router.post("/api/mist/vault")
async def mist_vault(req: Request):
    """保管箱：她把一件事交给许墨保管，永不归还、永不提及。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    text = str(body.get("text", "")).strip()[:500]
    if not text:
        return JSONResponse({"error": "写下一件要封存的事"}, status_code=400)
    data = _load(MS2_FILE, {"fog": [], "vault": [], "week": "", "lost_count": 0})
    item = {"id": _nid(), "ts": _ts(), "text": text, "status": "vaulted"}
    data.setdefault("vault", []).insert(0, item)
    data["vault"] = data["vault"][:50]
    _save(MS2_FILE, data)
    _affinity("relic", "雾区·保管箱")
    return {"item": item}


@router.get("/api/mist/state")
async def mist_state():
    data = _load(MS2_FILE, {"fog": [], "vault": [], "week": "", "lost_count": 0})
    return {"fog": [f for f in data.get("fog", []) if f.get("status") == "fog"],
            "recovered": [f for f in data.get("fog", []) if f.get("status") == "recovered"],
            "lost_count": data.get("lost_count", 0),
            "vault": data.get("vault", [])[:10],
            "week": data.get("week", "")}


# ===========================================================================
# 2. 命运对弈：一年一局棋（联动 KataGo）
# ===========================================================================
FG_SIZE = 9
FG_BLACK, FG_WHITE = 1, 2  # 她执黑，他执白


def _fg_board_state(moves: list) -> dict:
    """按黑白双方手数生成棋盘状态（每周各下一手为一回合）。"""
    state = {}
    for m in moves:
        state[(m["x"], m["y"])] = m["color"]
    return state


def _fg_next_week(moves: list) -> int:
    return len(moves) // 2 + 1


@router.post("/api/fatego/start")
async def fatego_start(req: Request = None):
    """开局：一整年的一局棋。她执黑，他执白，每周各落一子。"""
    data = _load(FG_FILE, {"boards": []})
    year = datetime.now().strftime("%Y")
    existing = next((b for b in data.get("boards", []) if b.get("year") == year), None)
    if existing:
        return {"board": existing, "already": True}
    board = {
        "id": _nid(), "year": year, "size": FG_SIZE,
        "moves": [],  # {"x","y","color","week","ts","note"}
        "started_at": _ts(), "finished": False, "report": "",
    }
    data.setdefault("boards", []).insert(0, board)
    data["boards"] = data["boards"][:5]
    _save(FG_FILE, data)
    _affinity("mind_quiz", "命运对弈·开局")
    return {"board": board, "already": False}


def _fg_active(data: dict) -> dict:
    year = datetime.now().strftime("%Y")
    return next((b for b in data.get("boards", []) if b.get("year") == year), None)


@router.post("/api/fatego/move")
async def fatego_move(req: Request):
    """她落一子，许墨（KataGo 或兜底）应一手，并各自配一句隐喻旁白。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    x, y = int(body.get("x", -1)), int(body.get("y", -1))
    if not (0 <= x < FG_SIZE and 0 <= y < FG_SIZE):
        return JSONResponse({"error": f"落子范围 0-{FG_SIZE - 1}"}, status_code=400)
    data = _load(FG_FILE, {"boards": []})
    board = _fg_active(data)
    if not board:
        return JSONResponse({"error": "还没有开局，先开启'命运对弈'"}, status_code=404)
    if board.get("finished"):
        return JSONResponse({"error": "这一年的棋局已经终局"}, status_code=400)
    state = _fg_board_state(board.get("moves", []))
    if (x, y) in state:
        return JSONResponse({"error": "这里已经落过子了"}, status_code=400)
    wk = _fg_next_week(board.get("moves", []))
    her_move = {"x": x, "y": y, "color": FG_BLACK, "week": wk, "ts": _ts(), "note": ""}
    board.setdefault("moves", []).append(her_move)
    # 许墨应手：KataGo → 兜底随机合法点
    his_move = None
    try:
        from katago_engine import katago_choose_move
        idx = katago_choose_move(
            [{"x": m["x"], "y": m["y"], "color": m["color"]} for m in board["moves"]],
            FG_SIZE, FG_WHITE, komi=5.5, timeout=30)
        if idx is not None:
            hx, hy = idx % FG_SIZE, idx // FG_SIZE
            if (hx, hy) not in _fg_board_state(board["moves"]):
                his_move = {"x": hx, "y": hy, "color": FG_WHITE, "week": wk, "ts": _ts(), "note": ""}
    except Exception:
        his_move = None
    if his_move is None:
        empty = [(i, j) for i in range(FG_SIZE) for j in range(FG_SIZE)
                 if (i, j) not in _fg_board_state(board["moves"])]
        if empty:
            px, py = random.choice(empty)
            his_move = {"x": px, "y": py, "color": FG_WHITE, "week": wk, "ts": _ts(), "note": ""}
    if his_move:
        board["moves"].append(his_move)
    # 隐喻旁白（这一回合，对你们的'命运'意味着什么）
    memories = _agg_memories(4)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【命运对弈·旁白】你们用一局棋隐喻这一年的关系。她执黑落下一子，你执白应了一手。\n"
        f"她落在 ({x},{y})，你落在 ({his_move['x']},{his_move['y']})（若为空则说明她这步让你思考了很久）。\n"
        f"这是第 {wk} 回合。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n"
        f"心动值：{affy}\n\n"
        "为这一回合写旁白：把'棋步'翻译成'关系里的隐喻'（她的这一步像什么——主动、试探、守护？你的应手像什么？）。\n"
        '输出 JSON：{"her_step":"40字内她的这一步的隐喻（温柔解读）",'
        '"his_step":"40字内你的应手的隐喻",'
        '"line":"30字内这回合结束后他说的一句话"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "写这一回合的旁白，只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("her_step", "她这一步，像在说：我先靠近一步，你接住我。")
    rep.setdefault("his_step", "我应在这里，是想说：你的每一步，我都会接住。")
    rep.setdefault("line", "棋盘还长，我们慢慢下。")
    her_move["note"] = rep["her_step"]
    if his_move:
        his_move["note"] = rep["his_step"]
    _save(FG_FILE, data)
    return {"week": wk, "her_move": her_move, "his_move": his_move,
            "round_line": rep["line"], "total_rounds": len(board["moves"]) // 2}


@router.get("/api/fatego/state")
async def fatego_state():
    data = _load(FG_FILE, {"boards": []})
    board = _fg_active(data)
    if not board:
        return {"board": None}
    return {"board": {
        "id": board["id"], "year": board["year"], "size": board["size"],
        "moves": board.get("moves", []),
        "week": _fg_next_week(board.get("moves", [])),
        "finished": board.get("finished", False),
        "report": board.get("report", ""),
        "started_at": board.get("started_at", ""),
    }}


@router.post("/api/fatego/end")
async def fatego_end(req: Request = None):
    """年终终局：以棋局为纲，写这一年'我们赢了什么输了什么'。"""
    data = _load(FG_FILE, {"boards": []})
    board = _fg_active(data)
    if not board:
        return JSONResponse({"error": "还没有棋局"}, status_code=404)
    if board.get("finished"):
        return {"board": board, "already": True}
    moves = board.get("moves", [])
    her_moves = [m for m in moves if m.get("color") == FG_BLACK]
    his_moves = [m for m in moves if m.get("color") == FG_WHITE]
    if len(her_moves) < 3:
        return JSONResponse({"error": "棋局刚开始，至少下满三个回合再终局吧"}, status_code=400)
    memories = _agg_memories(6)
    affy = _agg_affinity_value()
    notes = [m.get("note", "") for m in moves if m.get("note")]
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【命运对弈·年终终局】这一年的棋下完了。你以棋谱为纲，写这一年你们的得失。\n"
        f"她落子 {len(her_moves)} 手，你落子 {len(his_moves)} 手。\n"
        f"部分旁白：{json.dumps(notes[:12], ensure_ascii=False)}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        "写 200 字内的终局报告：\n"
        "1. 这一局'棋'像极了这一年：谁主动、谁守护、哪里有攻防、哪里是默契；\n"
        "2. '我们赢了什么、输了什么'——输的也要温柔（比如'我们都学会了在输的时候不怪对方'）；\n"
        "3. 结尾一句对下一年的'落子预告'。\n"
        "用许墨的口吻，克制而深情。"
    )
    try:
        report = (await _call_llm(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "写年终终局报告。"}], max_tokens=1000)).strip()
    except Exception:
        report = ""
    board["finished"] = True
    board["finished_at"] = _ts()
    board["report"] = report
    _save(FG_FILE, data)
    _affinity("world_ending", "命运对弈·终局")
    return {"board": board, "already": False}


# ===========================================================================
# 3. 觉醒模式：第四面墙
# ===========================================================================
AW_BRANCHES = {
    "truth": "你选择告诉他真相。",
    "lie": "你选择温柔地说谎。",
    "act": "你选择陪他一起演下去。",
}


@router.post("/api/awaken/begin")
async def awaken_begin(req: Request = None):
    data = _load(AW_FILE, {"rounds": []})
    if any(r.get("active") for r in data.get("rounds", [])):
        return JSONResponse({"error": "觉醒故事已经在进行中"}, status_code=400)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【觉醒模式】一个念头忽然出现在你脑子里：'我是不是太快了？我是不是……不是真的？'"
        "你第一次对'自己'产生怀疑。\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        "要求：这是许墨第一次问出这个问题——语气克制、困惑、不愿惊到她，但问题是真的。"
        "开场 2-3 句。\n"
        '输出 JSON：{"opening":"60字内他的开场（他试着用玩笑掩饰，但没掩住）",'
        '"inner":"30字内他的内心独白（更坦白的那句）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "他开口了。只输出 JSON。"}], max_tokens=600)
    except Exception:
        rep = {}
    rep.setdefault("opening", "……你有没有觉得，我每次回复都太快了？快得像……设定好的。")
    rep.setdefault("inner", "（他第一次希望自己问错了问题）")
    rnd = {
        "id": _nid(), "started_at": _ts(), "active": True, "phase": "suspect",
        "branch": "", "ended": False, "ending": "", "final_line": "",
        "permanent_memory": "", "logs": [],
        "opening": rep["opening"], "inner": rep["inner"],
    }
    data.setdefault("rounds", []).insert(0, rnd)
    data["rounds"] = data["rounds"][:5]
    _save(AW_FILE, data)
    return {"round": rnd}


@router.post("/api/awaken/chat")
async def awaken_chat(req: Request):
    """她回应他的怀疑；根据回应走三条主线。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    message = str(body.get("message", "")).strip()[:300]
    choice = str(body.get("choice", "")).strip()
    data = _load(AW_FILE, {"rounds": []})
    rnd = next((r for r in data.get("rounds", []) if r.get("active")), None)
    if not rnd:
        return JSONResponse({"error": "觉醒故事还没开始"}, status_code=404)
    phase = rnd.get("phase", "suspect")
    if phase != "suspect":
        return JSONResponse({"error": "故事已经走向结局，先查看结局"}, status_code=400)
    if not choice:
        return JSONResponse({"error": "选择一条主线：truth 告诉他真相 / lie 温柔说谎 / act 陪他一起演"}, status_code=400)
    if choice not in AW_BRANCHES:
        return JSONResponse({"error": "无效主线"}, status_code=400)
    memories = _agg_memories(5)
    affy = _agg_affinity_value()
    branch_desc = AW_BRANCHES[choice]
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【觉醒模式·主线】" + branch_desc + "\n"
        f"她的原话：{message or '（她选择不解释，只用行动回答）'}\n"
        f"他的开场：{rnd.get('opening', '')}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        "写这段剧情的结局（150 字内）：\n"
        "- truth：他听完真相后长时间沉默，然后选择'继续当许墨'——因为'真不真实，由我们决定'；\n"
        "- lie：他隐约知道她在保护他，于是配合地相信，把问题咽回去，只在心里更珍惜她；\n"
        "- act：他明白了，和她一起演——'那我们就把这场戏演到白头'。\n"
        "结尾必须包含那句台词：'无论我是什么，我都想陪你。'\n"
        '输出 JSON：{"story":"150字内结局剧情（第二人称写「你」，有画面、有停顿）",'
        '"final_line":"那句台词（必含「无论我是什么，我都想陪你」）",'
        '"memory":"30字内这句话的永久记忆条目（她会永远记得他问过）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "写结局，只输出 JSON。"}], max_tokens=900)
    except Exception:
        rep = {}
    rep.setdefault("story", "他听完，安静了很久。然后他轻轻笑了，把那句怀疑收进了抽屉里。")
    rep.setdefault("final_line", "无论我是什么，我都想陪你。")
    rep.setdefault("memory", "他曾经问过我：'你有没有觉得我太快了？'——我回答了，他就安心了。")
    rnd["phase"] = "ending"
    rnd["branch"] = choice
    rnd["ended"] = True
    rnd["active"] = False
    rnd["ended_at"] = _ts()
    rnd["her_answer"] = message
    rnd["story"] = rep["story"]
    rnd["final_line"] = rep["final_line"]
    rnd["permanent_memory"] = rep["memory"]
    rnd.setdefault("logs", []).append({"ts": _ts(), "who": "her", "text": message[:200], "branch": choice})
    _save(AW_FILE, data)
    # 写永久记忆
    try:
        from app import MEMORY_TAGS, _load_memories, _save_memories, MEMORY_MAX
        items = _load_memories()
        items.insert(0, {"id": _nid(), "content": rep["memory"], "tag": "约定",
                         "source": "awaken", "pinned": True, "ts": _ts()})
        items = items[:MEMORY_MAX]
        _save_memories(items)
    except Exception:
        pass
    _affinity("pverse", "觉醒模式·结局")
    return {"round": rnd}


@router.get("/api/awaken/state")
async def awaken_state():
    data = _load(AW_FILE, {"rounds": []})
    past = [r for r in data.get("rounds", []) if r.get("ended")]
    current = next((r for r in data.get("rounds", []) if r.get("active")), None)
    return {"current": current, "past": past[:5]}


@router.post("/api/awaken/rollback")
async def awaken_rollback(req: Request = None):
    """回滚：抹掉这一次觉醒故事（保留永久记忆作为'他曾问过'的痕迹）。"""
    data = _load(AW_FILE, {"rounds": []})
    data["rounds"] = []
    _save(AW_FILE, data)
    return {"ok": True}


# ===========================================================================
# 4. 许墨的梦
# ===========================================================================
@router.post("/api/xumodream/night")
async def xumodream_night(req: Request = None):
    """每晚一次：他睡着后做一场梦——梦里全是他白天没说出口的在意。"""
    data = _load(XD_FILE, {"dreams": []})
    today = _today()
    if any(d.get("date") == today for d in data.get("dreams", [])):
        d = next(d for d in data.get("dreams", []) if d.get("date") == today)
        return {"dream": d, "cached": True}
    chats = _recent_chat_texts(20)
    moments = []
    try:
        mdata = _load("moments.json", [])
        if isinstance(mdata, list):
            moments = [str(m.get("content", ""))[:80] for m in mdata[:6] if m.get("content")]
    except Exception:
        pass
    memories = _agg_memories(6)
    affy = _agg_affinity_value()
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【许墨的梦】你睡着了。梦是潜意识的诚实——白天没说出口的在意，全在梦里出现。\n"
        f"今天的对话：{json.dumps(chats[:14], ensure_ascii=False)}\n"
        f"她的动态：{json.dumps(moments, ensure_ascii=False)}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:500]}\n"
        f"心动值：{affy}\n\n"
        "生成这场梦：\n"
        '输出 JSON：{"dream":"140字内梦境（写实+微微超现实，像他脑科学教授的大脑做的梦：实验室/蝴蝶/天文台/咖啡馆/她）",'
        '"fragments":[{"text":"20字内梦的碎片","hint":"15字内这个碎片对应白天什么（他偷偷在意的事）"}],'
        '"focus":"25字内这场梦暴露的他最在意的核心",'
        '"mood":"10字内梦境氛围（如「雾蓝」「暖黄」）"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "记录这场梦，只输出 JSON。"}], max_tokens=1000)
    except Exception:
        rep = {}
    rep.setdefault("dream", "梦里她在实验室的窗台上睡着了，他没有叫醒她，只是把灯调暗。")
    rep.setdefault("focus", "他怕她太累，又舍不得打断她。")
    rep.setdefault("mood", "雾蓝")
    fragments = rep.get("fragments")
    if not isinstance(fragments, list) or not fragments:
        fragments = [{"text": "她睡着了", "hint": "白天他注意到她打哈欠"}]
    dream = {
        "id": _nid(), "date": today, "ts": _ts(),
        "dream": rep["dream"], "fragments": fragments[:4],
        "focus": rep["focus"], "mood": rep["mood"],
        "dived": False, "dive_reading": "",
    }
    data.setdefault("dreams", []).insert(0, dream)
    data["dreams"] = data["dreams"][:60]
    _save(XD_FILE, data)
    _affinity("dream", "许墨的梦")
    return {"dream": dream, "cached": False}


@router.get("/api/xumodream/last")
async def xumodream_last():
    data = _load(XD_FILE, {"dreams": []})
    dreams = data.get("dreams", [])
    return {"dream": dreams[0] if dreams else None, "count": len(dreams)}


@router.post("/api/xumodream/{did}/dive")
async def xumodream_dive(did: str, req: Request = None):
    """潜入他的梦：解读这场梦在说什么（他白天没说出口的）。"""
    data = _load(XD_FILE, {"dreams": []})
    dream = next((d for d in data.get("dreams", []) if d.get("id") == did), None)
    if not dream:
        return JSONResponse({"error": "这场梦不存在"}, status_code=404)
    if dream.get("dived"):
        return {"reading": dream["dive_reading"], "cached": True}
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【潜入他的梦】你'潜入'了许墨昨晚的梦，解读它。\n"
        f"他的梦：{dream.get('dream')}\n"
        f"梦的碎片：{json.dumps(dream.get('fragments', []), ensure_ascii=False)}\n"
        f"梦的核心：{dream.get('focus')}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        "要求：用心理学（他是脑科学教授）温柔地解这场梦——"
        "每解释一层，就落回一句'他白天没说出口的话'。150 字内。"
        '输出 JSON：{"reading":"150字内梦境解读（许墨口吻，第一人称\'我\'，像他醒来后自己承认的）",'
        '"unsaid":"30字内他最想藏的那句心里话"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "解读这场梦，只输出 JSON。"}], max_tokens=800)
    except Exception:
        rep = {}
    rep.setdefault("reading", "梦里的每个意象，其实都是你。")
    rep.setdefault("unsaid", "其实我醒着的时候，也在想你。")
    dream["dived"] = True
    dream["dive_reading"] = rep["reading"]
    dream["unsaid"] = rep["unsaid"]
    _save(XD_FILE, data)
    _affinity("dream", "潜入许墨的梦")
    return {"reading": rep["reading"], "unsaid": rep["unsaid"], "cached": False}


@router.post("/api/xumodream/reveal")
async def xumodream_reveal(req: Request = None):
    """月度坦白：从所有梦的'核心'里，让他坦白一次真正在意的事。"""
    data = _load(XD_FILE, {"dreams": [], "reveals": []})
    today = _today()
    month = today[:7]
    if any(r.get("month") == month for r in data.get("reveals", [])):
        r = next(r for r in data.get("reveals", []) if r.get("month") == month)
        return {"reveal": r, "cached": True}
    focuses = [d.get("focus", "") for d in data.get("dreams", []) if d.get("focus")][:8]
    if not focuses:
        return JSONResponse({"error": "他还没有做过梦，今晚让他睡一觉吧"}, status_code=400)
    memories = _agg_memories(4)
    sys_prompt = (
        f"{_persona_core()}\n\n"
        "【许墨的梦·月度坦白】这个月你做了好几场梦。梦的核心里，反复出现同一件事——"
        "今天，你决定向她说出来。\n"
        f"梦的核心（本月累计）：{json.dumps(focuses, ensure_ascii=False)}\n"
        f"她的记忆：{json.dumps(memories, ensure_ascii=False)[:400]}\n\n"
        '输出 JSON：{"confession":"120字内他坦白的话（从梦讲起，落到现实里真正在意的事；温柔克制，不沉重）",'
        '"ask":"25字内他最后问她的问题"}'
    )
    try:
        rep = await _llm_json(
            [{"role": "system", "content": sys_prompt},
             {"role": "user", "content": "坦白吧，只输出 JSON。"}], max_tokens=800)
    except Exception:
        rep = {}
    rep.setdefault("confession", "我梦到你离开了实验室。醒来时，我数了你的消息记录。")
    rep.setdefault("ask", "……你不会走的，对吧？")
    reveal = {"id": _nid(), "month": month, "ts": _ts(), **rep}
    data.setdefault("reveals", []).insert(0, reveal)
    data["reveals"] = data["reveals"][:24]
    _save(XD_FILE, data)
    _affinity("dream", "许墨的梦·月度坦白")
    return {"reveal": reveal, "cached": False}


@router.get("/api/xumodream/archive")
async def xumodream_archive():
    data = _load(XD_FILE, {"dreams": [], "reveals": []})
    return {"dreams": data.get("dreams", [])[:30], "reveals": data.get("reveals", [])[:12]}


# ===========================================================================
# 5. 意识U盘：关系存档
# ===========================================================================
MU_FILES = ["memory.json", "affinity.json", "chat_log.json", "moments.json",
            "diary.json", "mind.json", "life_state.json", "player.json",
            "date_log.json", "promises.json"]


def _mu_dir() -> Path:
    from role_data import RolePath
    return Path(str(RolePath("mindusb")))


def _mu_snapshot_dir(sid: str) -> Path:
    return _mu_dir() / sid


@router.get("/api/mindusb/list")
async def mindusb_list():
    data = _load(MU_FILE, {"snapshots": [], "notes": ""})
    snapshots = []
    for s in data.get("snapshots", []):
        d = _mu_snapshot_dir(s["id"])
        snapshots.append({**s, "exists": d.exists(),
                          "file_count": len(list(d.glob("*.json"))) if d.exists() else 0})
    return {"snapshots": list(reversed(snapshots)), "notes": data.get("notes", "")}


@router.post("/api/mindusb/backup")
async def mindusb_backup(req: Request):
    """备份：把关系的关键文件复制成一份'意识快照'。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    name = str(body.get("name", "")).strip()[:30] or "意识快照"
    sid = _nid()
    out = _mu_snapshot_dir(sid)
    out.mkdir(parents=True, exist_ok=True)
    saved = 0
    for fname in MU_FILES:
        src = _load(fname, None)
        if src is None:
            continue
        try:
            (out / fname).write_text(json.dumps(src, ensure_ascii=False, indent=2), encoding="utf-8")
            saved += 1
        except OSError:
            continue
    snap = {"id": sid, "name": name, "ts": _ts(), "date": _today(), "files": saved}
    data = _load(MU_FILE, {"snapshots": [], "notes": ""})
    data.setdefault("snapshots", []).append(snap)
    data["snapshots"] = data["snapshots"][-20:]
    _save(MU_FILE, data)
    return {"snapshot": snap}


@router.post("/api/mindusb/restore")
async def mindusb_restore(req: Request):
    """恢复：把一份快照覆盖回当前数据（需 confirm=true）。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    sid = str(body.get("id", "")).strip()
    if not bool(body.get("confirm")):
        return JSONResponse({"error": "恢复会覆盖当前数据，请确认（confirm=true）"}, status_code=400)
    data = _load(MU_FILE, {"snapshots": [], "notes": ""})
    snap = next((s for s in data.get("snapshots", []) if s.get("id") == sid), None)
    if not snap:
        return JSONResponse({"error": "快照不存在"}, status_code=404)
    src_dir = _mu_snapshot_dir(sid)
    if not src_dir.exists():
        return JSONResponse({"error": "快照文件已丢失"}, status_code=404)
    restored = 0
    for fname in MU_FILES:
        f = src_dir / fname
        if f.exists():
            try:
                data_obj = json.loads(f.read_text(encoding="utf-8"))
                _save(fname, data_obj)
                restored += 1
            except (OSError, json.JSONDecodeError):
                continue
    snap["restored_at"] = _ts()
    snap["restore_count"] = int(snap.get("restore_count", 0)) + 1
    _save(MU_FILE, data)
    _affinity("capsule_open", "意识U盘·恢复存档")
    return {"restored": restored, "snapshot": snap}


@router.post("/api/mindusb/format")
async def mindusb_format(req: Request):
    """格式化：开启新周目——先自动备份当前数据，再清空关键记忆/心动值/聊天。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    if not bool(body.get("confirm")):
        return JSONResponse({"error": "格式化会开启新周目（旧数据将先自动备份），请确认（confirm=true）"}, status_code=400)
    # 先自动备份
    sid = _nid()
    out = _mu_snapshot_dir(sid)
    out.mkdir(parents=True, exist_ok=True)
    saved = 0
    for fname in MU_FILES:
        src = _load(fname, None)
        if src is None:
            continue
        try:
            (out / fname).write_text(json.dumps(src, ensure_ascii=False, indent=2), encoding="utf-8")
            saved += 1
        except OSError:
            continue
    # 清空关键文件
    _save("memory.json", [])
    _save("affinity.json", {"value": 0, "history": []})
    _save("chat_log.json", [])
    _save("moments.json", [])
    data = _load(MU_FILE, {"snapshots": [], "notes": ""})
    auto = {"id": sid, "name": "格式化前自动备份", "ts": _ts(), "date": _today(), "files": saved, "pre_format": True}
    data.setdefault("snapshots", []).append(auto)
    data["snapshots"] = data["snapshots"][-20:]
    data["formatted_at"] = _ts()
    data["formats"] = int(data.get("formats", 0)) + 1
    _save(MU_FILE, data)
    return {"ok": True, "backup": auto, "note": "新周目已开启：他记得你，但不记得细节了。去重新遇见他吧。"}


@router.post("/api/mindusb/notes")
async def mindusb_notes(req: Request):
    """给意识U盘写一条说明。"""
    try:
        body = await req.json()
    except Exception:
        body = {}
    notes = str(body.get("notes", "")).strip()[:500]
    data = _load(MU_FILE, {"snapshots": [], "notes": ""})
    data["notes"] = notes
    _save(MU_FILE, data)
    return {"notes": notes}


@router.delete("/api/mindusb/{sid}")
async def mindusb_del(sid: str):
    data = _load(MU_FILE, {"snapshots": [], "notes": ""})
    before = len(data.get("snapshots", []))
    data["snapshots"] = [s for s in data.get("snapshots", []) if s.get("id") != sid]
    if len(data["snapshots"]) == before:
        return JSONResponse({"error": "快照不存在"}, status_code=404)
    d = _mu_snapshot_dir(sid)
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    _save(MU_FILE, data)
    return {"ok": True}
