"""手谈 · 与许墨对弈围棋：完整规则引擎 + 启发式 AI + 许墨台词 + 对弈记录。
数据持久化到角色目录 go.json（RolePath 按请求角色动态路由），风格与 creative_apps.py 一致。

规则说明（中国规则·数子法简化版）：
- 9 / 13 路棋盘，支持执黑或执白；
- 气尽提子、自杀禁令、简单劫（禁止立即回提）；
- 双方连续虚着即终局，数子法计分：子 + 围空，黑贴 3.25 子（9 路）/ 3.25 子（13 路）；
- 任意一方认输立即终局。
"""
import asyncio
import functools
import json
import math
import random
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()

# 串行化所有 go.json 读-改-写路由：这些路由体内含 await（LLM 台词 / AI 行棋），
# 跨 await 的并发落子/评论曾会互相覆盖丢失对局数据
_go_lock = asyncio.Lock()


def _go_route(func):
    @functools.wraps(func)
    async def _wrapped(*args, **kwargs):
        async with _go_lock:
            return await func(*args, **kwargs)
    return _wrapped

GO_FILE = RolePath("go.json")

BLACK, WHITE, EMPTY = 1, 2, 0

# 数子法贴子（黑贴 3.25 子，9/13 路通用）
KOMI = 3.25

# KataGo 探测缓存：避免每次 ai_choose_move 都探测（探测约 2-3s）
# 失败后间隔 5 分钟再试，避免不可用时拖慢响应
_KATAGO_OK = None        # None=未探测 / True=可用 / False=不可用
_KATAGO_RETRY_AT = 0.0   # 下次允许探测的时间戳（time.time()）


# ---------------------------------------------------------------------------
# 公共工具（延迟导入避免与 app.py 循环依赖）
# ---------------------------------------------------------------------------

async def _call_llm(messages: list, max_tokens: int = None) -> str:
    from app import _call_llm as _impl
    return await _impl(messages, max_tokens=max_tokens)


def _system_prompt() -> str:
    from app import SYSTEM_PROMPT
    return SYSTEM_PROMPT


def _add_affinity(action: str, detail: str = "") -> dict:
    from app import _add_affinity as _impl
    return _impl(action, detail)


def _load(path, default):
    if Path(path).exists():
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return default


def _save(path, data):
    atomic_json(path, data)


def _now() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 一、规则引擎
# ---------------------------------------------------------------------------

class GoEngine:
    """围棋规则引擎：board 一维数组，idx = y * size + x。"""

    def __init__(self, size: int = 9):
        self.size = size
        self.n = size * size
        self.board = [EMPTY] * self.n
        self.ko = -1                 # 劫禁点（上一手单提一子形成简单劫时记录）
        self.captures = {BLACK: 0, WHITE: 0}   # 各方累计提子数
        self.turn = BLACK
        self.moves = []              # [{"x","y","color","cap"}] / {"pass":1,"color"}
        self.passes = 0              # 连续虚着计数
        self.finished = False
        self.result = None           # {"winner": 1/2/0, "diff": 子差, "text": 描述}

    # ---------- 基础查询 ----------

    def neighbors(self, idx: int):
        x, y = idx % self.size, idx // self.size
        if x > 0:
            yield idx - 1
        if x < self.size - 1:
            yield idx + 1
        if y > 0:
            yield idx - self.size
        if y < self.size - 1:
            yield idx + self.size

    def group(self, board, idx):
        """返回 (同色棋块 set, 气 set)。"""
        color = board[idx]
        stones, libs, stack = {idx}, set(), [idx]
        while stack:
            cur = stack.pop()
            for nb in self.neighbors(cur):
                v = board[nb]
                if v == EMPTY:
                    libs.add(nb)
                elif v == color and nb not in stones:
                    stones.add(nb)
                    stack.append(nb)
        return stones, libs

    def legal(self, idx: int, color: int, board=None) -> bool:
        """落子合法性：空点、非劫禁点、非自杀。"""
        board = board if board is not None else self.board
        if not (0 <= idx < self.n) or board[idx] != EMPTY:
            return False
        if idx == self.ko:
            return False
        new_board, captured = self._simulate(board, idx, color)
        return new_board is not None

    def legal_moves(self, color: int) -> list:
        return [i for i in range(self.n) if self.legal(i, color)]

    # ---------- 落子核心 ----------

    def _simulate(self, board, idx, color):
        """在 board 上模拟落子，返回 (新board, 提子列表)；自杀返回 (None, [])。"""
        if board[idx] != EMPTY:
            return None, []
        b = board[:]
        b[idx] = color
        enemy = WHITE if color == BLACK else BLACK
        captured = []
        for nb in self.neighbors(idx):
            if b[nb] == enemy:
                stones, libs = self.group(b, nb)
                if not libs:
                    captured.extend(stones)
        for s in captured:
            b[s] = EMPTY
        stones, libs = self.group(b, idx)
        if not libs:  # 自杀
            return None, []
        return b, captured

    def play(self, x: int, y: int, color: int):
        """正式落子。成功返回 dict，非法返回 None。"""
        if self.finished or self.turn != color:
            return None
        idx = y * self.size + x
        new_board, captured = self._simulate(self.board, idx, color)
        if new_board is None:
            return None
        # 简单劫判定：本手恰提 1 子、落下的是孤子且只有 1 口气 → 禁对方立即回提
        self.ko = -1
        if len(captured) == 1:
            stones, libs = self.group(new_board, idx)
            if len(stones) == 1 and len(libs) == 1:
                self.ko = captured[0]
        self.board = new_board
        self.captures[color] += len(captured)
        self.turn = WHITE if color == BLACK else BLACK
        self.passes = 0
        enemy = WHITE if color == BLACK else BLACK
        move = {
            "x": x, "y": y, "color": color,
            "cap": len(captured),
            "cap_points": [c for c in captured],
        }
        self.moves.append(move)
        return {"move": move, "captured": captured,
                "enemy_lib1": self._blocks_in_atari(enemy)}

    def pass_move(self, color: int):
        """虚着。返回是否终局。"""
        if self.finished or self.turn != color:
            return None
        self.moves.append({"pass": 1, "color": color})
        self.ko = -1
        self.passes += 1
        self.turn = WHITE if color == BLACK else BLACK
        if self.passes >= 2:
            self._score()
            return True
        return False

    def resign(self, color: int):
        """认输。"""
        winner = WHITE if color == BLACK else BLACK
        self.finished = True
        self.result = {
            "winner": winner, "diff": 0, "resigned": color,
            "text": ("黑" if color == BLACK else "白") + "方中盘认输",
        }
        return self.result

    def _blocks_in_atari(self, color: int) -> int:
        """对方处于叫吃（1 气）的棋块数。"""
        seen, cnt = set(), 0
        for i in range(self.n):
            if self.board[i] == color and i not in seen:
                stones, libs = self.group(self.board, i)
                seen |= stones
                if len(libs) == 1:
                    cnt += 1
        return cnt

    # ---------- 终局数子（中国规则） ----------

    def _score(self):
        seen = set()
        terr = {BLACK: 0, WHITE: 0}
        stones = {BLACK: 0, WHITE: 0}
        for i in range(self.n):
            v = self.board[i]
            if v != EMPTY:
                stones[v] += 1
        # 空白区域 flood fill，只邻接一色 → 该色围空；否则中立（dame/双活公气）
        for i in range(self.n):
            if self.board[i] == EMPTY and i not in seen:
                region, borders, stack = {i}, set(), [i]
                while stack:
                    cur = stack.pop()
                    for nb in self.neighbors(cur):
                        v = self.board[nb]
                        if v == EMPTY and nb not in region:
                            region.add(nb)
                            stack.append(nb)
                        elif v != EMPTY:
                            borders.add(v)
                seen |= region
                if borders == {BLACK}:
                    terr[BLACK] += len(region)
                elif borders == {WHITE}:
                    terr[WHITE] += len(region)
        b_score = stones[BLACK] + terr[BLACK]
        w_score = stones[WHITE] + terr[WHITE]
        diff = b_score - (w_score + KOMI)
        if diff > 0:
            winner, d = BLACK, diff
            text = f"黑胜 {d:.2f} 子（黑 {b_score} : 白 {w_score}+贴{KOMI}）"
        elif diff < 0:
            winner, d = WHITE, -diff
            text = f"白胜 {d:.2f} 子（黑 {b_score} : 白 {w_score}+贴{KOMI}）"
        else:
            winner, d, text = 0, 0, "和棋（罕见的一字之差）"
        self.finished = True
        self.result = {"winner": winner, "diff": d, "text": text,
                       "black": b_score, "white": w_score}
        return self.result

    # ---------- 序列化 ----------

    def to_state(self):
        return {
            "size": self.size,
            "board": self.board,
            "turn": self.turn,
            "ko": self.ko,
            "captures": self.captures,
            "moves": self.moves,
            "passes": self.passes,
            "finished": self.finished,
            "result": self.result,
            "move_count": len([m for m in self.moves if "x" in m]),
        }


# ---------------------------------------------------------------------------
# 二、启发式 AI（许墨的棋力）
# ---------------------------------------------------------------------------
# 评分要素：提子 > 救叫吃 > 打吃 > 连接/切断 > 影响力扩张 > 布局大场
# 六档棋力（从弱到强）：参数化驱动 AI 行为，见 _DIFF_PARAMS

NEIGHBOR8 = [(-1, -1), (0, -1), (1, -1), (-1, 0), (1, 0), (-1, 1), (0, 1), (1, 1)]


def _influence_at(board, size, idx, radius=3):
    """以 idx 为中心的局部影响力差（黑正白负），radius 圈衰减辐射。"""
    x0, y0 = idx % size, idx // size
    total = 0.0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x, y = x0 + dx, y0 + dy
            if not (0 <= x < size and 0 <= y < size):
                continue
            v = board[y * size + x]
            if v == EMPTY:
                continue
            dist = max(abs(dx), abs(dy))
            w = 1.0 / (1 << dist)
            total += w if v == BLACK else -w
    return total


def _is_true_eye(board, size, idx, color):
    """真眼检测：四邻全为己方（或边界），斜位至少 3/4 己方或边界。"""
    x0, y0 = idx % size, idx // size
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        x, y = x0 + dx, y0 + dy
        if 0 <= x < size and 0 <= y < size:
            if board[y * size + x] != color:
                return False
    diag_ok, diag_bad = 0, 0
    edge = x0 in (0, size - 1) or y0 in (0, size - 1)
    for dx, dy in NEIGHBOR8:
        if dx == 0 or dy == 0:
            continue
        x, y = x0 + dx, y0 + dy
        if not (0 <= x < size and 0 <= y < size):
            continue
        if board[y * size + x] == color:
            diag_ok += 1
        elif board[y * size + x] != EMPTY:
            diag_bad += 1
    if edge:
        return diag_bad == 0
    return diag_bad <= 1


def _opening_bonus(size, x, y, move_count):
    """开局大场：星位/小目/三三，随棋盘尺寸自适应。"""
    lines = [2, 3] if size <= 9 else [2, 3, 4]
    corners = set()
    for a in lines:
        for b in (3, 4 if size >= 11 else 3):
            corners.update({(a, b), (size - 1 - a, b), (a, size - 1 - b), (size - 1 - a, size - 1 - b)})
    # 星位（正中角）
    mid = (size - 1) // 2
    stars = {(3, 3), (3, size - 4), (size - 4, 3), (size - 4, size - 4), (mid, mid)} if size >= 7 else {(2, 2), (2, size - 3), (size - 3, 2), (size - 3, size - 3)}
    pt = (x, y)
    if move_count >= size * 2:
        return 0.0
    if pt in stars:
        return 14.0 if move_count < 4 else 9.0
    if pt in corners:
        return 8.0 if move_count < 4 else 5.0
    # 三线/四线边
    if (x in (2, 3, size - 3, size - 4) or y in (2, 3, size - 3, size - 4)) and not (4 < x < size - 5 and 4 < y < size - 5):
        return 3.0
    # 一线二线开局不碰
    if x in (0, 1, size - 2, size - 1) or y in (0, 1, size - 2, size - 1):
        return -6.0
    return 0.0


def _evaluate_move(engine: GoEngine, idx, color, move_count):
    """给候选点打分。返回 (score, captured_len)。"""
    size = engine.size
    board = engine.board
    x, y = idx % size, idx // size
    enemy = WHITE if color == BLACK else BLACK

    new_board, captured = engine._simulate(board, idx, color)
    if new_board is None:
        return None, 0

    score = 0.0
    cap_n = len(captured)

    # 1) 提子：直接收益（子越多越香）
    if cap_n:
        score += 26.0 + cap_n * 9.0

    # 2) 落子后自身状态
    stones, libs = engine.group(new_board, idx)
    lib_n = len(libs)
    if lib_n == 1 and cap_n == 0:
        score -= 42.0            # 送吃（非提子时）
    elif lib_n == 2 and cap_n == 0:
        score -= 6.0             # 两气偏薄
    score += min(lib_n, 4) * 1.8

    # 3) 救自己叫吃的棋：本手使原本 1 气的己方块气数增加
    for nb in engine.neighbors(idx):
        if board[nb] == color:
            s0, l0 = engine.group(board, nb)
            if len(l0) == 1 and lib_n >= 2:
                score += 14.0 + len(s0) * 7.0
            break  # 只按最大一块计一次（相邻同色块会连上，取第一块代表）

    # 4) 打吃对方：落子后对方邻近块变 1 气
    seen = set()
    for nb in engine.neighbors(idx):
        if new_board[nb] == enemy and nb not in seen:
            s1, l1 = engine.group(new_board, nb)
            seen |= s1
            if len(l1) == 1:
                score += 10.0 + len(s1) * 5.0   # 打吃；若对方无路可逃基本等于吃
            elif len(l1) == 2:
                score += 2.5 + len(s1) * 0.8

    # 5) 连接与切断：数己方可连块数 / 敌方可分断块数
    my_blocks = 0
    seen_b = set()
    for nb in engine.neighbors(idx):
        if board[nb] == color and nb not in seen_b:
            s2, _ = engine.group(board, nb)
            seen_b |= s2
            my_blocks += 1
    if my_blocks >= 2:
        score += 5.0 + my_blocks * 2.0          # 连接
    en_blocks = 0
    seen_e = set()
    for nb in engine.neighbors(idx):
        if board[nb] == enemy and nb not in seen_e:
            s3, _ = engine.group(board, nb)
            seen_e |= s3
            en_blocks += 1
    if en_blocks >= 2:
        score += 4.0 + en_blocks * 1.5          # 切断/靠压

    # 6) 影响力：让局部势力向己方倾斜
    infl_before = _influence_at(board, size, idx)
    infl_after = _influence_at(new_board, size, idx)
    gain = (infl_after - infl_before) * (1.0 if color == BLACK else -1.0)
    score += gain * 4.5
    # 争夺边界点（势力交界处价值高）
    if abs(infl_before) < 0.9:
        score += 3.0

    # 7) 布局大场
    score += _opening_bonus(size, x, y, move_count)

    # 8) 真眼不填
    if _is_true_eye(board, size, idx, color):
        score -= 120.0

    # 9) 轻微位置噪声（让棋风自然）
    score += random.uniform(0, 2.2)
    return score, cap_n


def _best_reply_gain(engine: GoEngine, my_idx, color):
    """一层验证：我落 my_idx 后，对方最强一手能提掉我几子（惩罚送吃）。"""
    enemy = WHITE if color == BLACK else BLACK
    b, _ = engine._simulate(engine.board, my_idx, color)
    if b is None:
        return -999
    tmp = GoEngine.__new__(GoEngine)
    tmp.size, tmp.n, tmp.board, tmp.ko = engine.size, engine.n, b, -1
    worst = 0
    for j in range(tmp.n):
        if b[j] == EMPTY:
            nb2, cap = tmp._simulate(b, j, enemy)
            if nb2 is None:
                continue
            if cap:
                # 只关心吃掉的是否包含刚下的块附近
                if my_idx in cap or any(abs((c % engine.size) - (my_idx % engine.size)) + abs((c // engine.size) - (my_idx // engine.size)) <= 1 for c in cap):
                    worst = max(worst, len(cap))
            if worst >= 3:
                break
    return worst


def _katago_genmove(engine: GoEngine, color: int):
    """调用 KataGo 生成一手。返回 idx 或 None（不可用/pass/resign/非法手）。

    使用模块级 _KATAGO_OK 缓存：探测一次可用后直接调；探测失败后冷却 5 分钟再试。
    """
    global _KATAGO_OK, _KATAGO_RETRY_AT
    import time as _t
    now = _t.time()

    # 失效缓存：若上次探测失败，等冷却
    if _KATAGO_OK is False and now < _KATAGO_RETRY_AT:
        return None
    if _KATAGO_OK is None:
        try:
            from katago_engine import katago_available
            _KATAGO_OK = katago_available()
        except Exception as e:
            print(f"[go] katago_engine import/probe failed: {type(e).__name__} {str(e)[:120]}", flush=True)
            _KATAGO_OK = False
        if not _KATAGO_OK:
            _KATAGO_RETRY_AT = now + 300  # 5 分钟后再试
            print("[go] KataGo 不可用，pro 难度回退到启发式", flush=True)
            return None

    # 调 KataGo 生成
    try:
        from katago_engine import katago_choose_move
        moves = engine.to_state().get("moves", [])
        idx = katago_choose_move(moves, engine.size, color, komi=KOMI, timeout=30)
    except Exception as e:
        print(f"[go] katago_choose_move exception: {type(e).__name__} {str(e)[:150]}", flush=True)
        return None
    if idx is None:
        # KataGo 返回 pass/resign 或不可用 → 让启发式接管
        return None
    # 合法性校验：KataGo 偶尔会因为 ko 规则差异返回我方规则下非法的手
    legal = engine.legal_moves(color)
    if idx not in legal:
        print(f"[go] KataGo returned illegal idx={idx} (color={color}); 启发式接管", flush=True)
        return None
    return idx


def ai_choose_move(engine: GoEngine, color: int, difficulty: str):
    """许墨选点。返回 idx 或 None（虚着）。

    行为由 _DIFF_PARAMS 参数化：
      noise    : 评分附加随机噪声（越大越乱、越弱）
      pool     : 在最优前 pool 比例内随机挑（>0 启用，越大越弱）
      temp     : softmax 温度 / 随机权重偏移（越小越集中最优手）
      topk     : 候选 top 数量（用于 softmax / 一层验证）
      lookahead: 是否做一层对方回应验证（防送吃）
      penalty  : 送吃惩罚系数（lookahead 时生效）
      blunder  : 主动走随手棋（随机合法手）的概率
      pass_thr : 最优手低于此分且盘面无争 → 虚着

    pro 难度优先调用 KataGo（GTP），不可用时回退到启发式 pro 参数。
    """
    if difficulty not in _DIFF_PARAMS:
        difficulty = "normal"

    # ---- KataGo 接管 pro 难度 ----
    if difficulty == "pro":
        katago_idx = _katago_genmove(engine, color)
        if katago_idx is not None:
            return katago_idx
        # KataGo 不可用 → 走启发式 pro（_DIFF_PARAMS["pro"]，下方统一逻辑）

    p = _DIFF_PARAMS[difficulty]

    moves = engine.legal_moves(color)
    if not moves:
        return None
    move_count = engine.to_state()["move_count"]

    scored = []
    for idx in moves:
        s, cap_n = _evaluate_move(engine, idx, color, move_count)
        if s is None:
            continue
        scored.append((s, idx, cap_n))
    if not scored:
        return None
    scored.sort(key=lambda t: -t[0])

    # 主动随手棋：以一定概率挑一个明显非最优、且不填自己真眼的合法点
    if p["blunder"] and random.random() < p["blunder"]:
        cand = [t for t in scored if not _is_true_eye(engine.board, engine.size, t[1], color)]
        if cand:
            cand.sort(key=lambda t: t[0])  # 偏向分数偏低的随手棋
            pick_from = cand[:max(2, len(cand) // 2)]
            return random.choice(pick_from)[1]

    # 无意义落子检测：分数太低且盘面已无争夺 → 虚着
    empty = len([v for v in engine.board if v == EMPTY])
    if scored[0][0] < p["pass_thr"] and empty < engine.n * 0.35:
        return None

    if p["lookahead"]:
        # 全力以赴 / 棋力全开：topk 内做一层对方最强回应验证，防送吃
        top = scored[:p["topk"]]
        best, best_s = top[0][1], -1e9
        for s, idx, cap_n in top:
            penalty = _best_reply_gain(engine, idx, color) * p["penalty"]
            adj = s - penalty
            if adj > best_s:
                best_s, best = adj, idx
        return best

    if p["pool"] > 0:
        # 温柔 / 新手：在最优前 pool 比例内随机挑（权重=分数+偏移），让局势松弛
        k = max(3, int(len(scored) * p["pool"]))
        pool = scored[:k]
        weights = [max(t[0], 0.5) + p["temp"] for t in pool]
        return random.choices(pool, weights=weights, k=1)[0][1]

    # 其余：topk softmax，温度越低越集中最优手
    top = scored[:p["topk"]] if p["topk"] else scored[:3]
    weights = [math.exp(t[0] / p["temp"]) for t in top]
    return random.choices(top, weights=weights, k=1)[0][1]


# ---------------------------------------------------------------------------
# 难度梯度：从弱到强 6 档（参数化）
# ---------------------------------------------------------------------------

GO_DIFFICULTIES = [
    {"key": "newbie", "name": "新手陪练", "desc": "常有随手漏着，适合第一次上手"},
    {"key": "gentle", "name": "温柔让先", "desc": "刻意放慢节奏，处处留情"},
    {"key": "casual", "name": "轻松对弈", "desc": "略有算度，不刻意紧逼"},
    {"key": "normal", "name": "认真对弈", "desc": "正常发挥，攻守均衡"},
    {"key": "hard",   "name": "全力以赴", "desc": "算路更深，提防送吃"},
    {"key": "pro",    "name": "棋力全开", "desc": "滴水不漏，尽量不失误"},
]
DIFFICULTY_KEYS = [d["key"] for d in GO_DIFFICULTIES]
DIFFICULTY_MAP = {d["key"]: d for d in GO_DIFFICULTIES}
GO_DIFF_NAMES = {d["key"]: d["name"] for d in GO_DIFFICULTIES}

_DIFF_PARAMS = {
    #                    noise  pool   temp  topk  lookahead  penalty  blunder  pass_thr
    "newbie": {"noise": 7.0, "pool": 0.90, "temp": 3.0, "topk": 0, "lookahead": False, "penalty": 0.0,  "blunder": 0.22, "pass_thr": -6.0},
    "gentle": {"noise": 2.8, "pool": 0.45, "temp": 1.0, "topk": 0, "lookahead": False, "penalty": 0.0,  "blunder": 0.06, "pass_thr": -8.0},
    "casual": {"noise": 1.6, "pool": 0.0,  "temp": 12.0, "topk": 3, "lookahead": False, "penalty": 0.0,  "blunder": 0.02, "pass_thr": -10.0},
    "normal": {"noise": 1.2, "pool": 0.0,  "temp": 8.0, "topk": 3, "lookahead": False, "penalty": 0.0,  "blunder": 0.0,  "pass_thr": -12.0},
    "hard":   {"noise": 0.8, "pool": 0.0,  "temp": 6.0, "topk": 6, "lookahead": True,  "penalty": 9.0,  "blunder": 0.0,  "pass_thr": -14.0},
    "pro":    {"noise": 0.4, "pool": 0.0,  "temp": 4.0, "topk": 9, "lookahead": True,  "penalty": 13.0, "blunder": 0.0,  "pass_thr": -16.0},
}


# ---------------------------------------------------------------------------
# 三、许墨台词系统
# ---------------------------------------------------------------------------

GO_LINES = {
    "start": [
        "棋盘已经摆好了。黑先白后——你先请。",
        "今晚的棋，我陪你下。落子无悔，可要想清楚。",
        "布局如做研究，第一步总是要留足余地的。……你先。",
        "茶已经温好了，棋盘也擦过了。来，手谈一局。",
    ],
    "opening_reply": [
        "嗯……这一步颇有想法。",
        "开局稳健。看来你今天很清醒。",
        "有意思的选点。那我就不客气了。",
        "棋从断处生——我们慢慢来。",
    ],
    "move": [
        "考虑一下……这里，如何。",
        "这手棋，我落在这里。",
        "该我了。……就这里。",
        "棋势渐紧了。看这里。",
        "你走你的阳关道，我布我的局。",
        "嗯……变化比预想的多一点。",
    ],
    "capture": [
        "这块棋，气息已尽。承让。",
        "对不起——这几颗，我收下了。",
        "气尽了，棋就死了。规律而已。",
        "就像实验里的变量，被排除出局了。",
    ],
    "capture_big": [
        "这一片……终究没能做活。棋理如此。",
        "大龙被屠，是布局时就埋下的因。",
    ],
    "captured": [
        "……有意思。这一手，出乎我的意料。",
        "我的棋？收去吧。棋盘上，得失都是常事。",
        "看来我低估了你的计算力。不会再有第二次。",
        "漂亮。……这个词我很少用在棋盘上。",
    ],
    "atari": [
        "小心，你的棋只剩一口气了。",
        "打吃。想好退路了吗？",
        "这块棋……危了。",
    ],
    "atari_self": [
        "我的棋被叫吃了？……容我想想。",
        "嗯，被你抓住破绽了。",
    ],
    "pass": [
        "我停一手。这一带，暂时没有棋了。",
        "虚着。剩下的，交给终局。",
    ],
    "player_pass": [
        "你也停一手？那就快到收官了。",
        "好，都停一手的话——棋局自会给出答案。",
    ],
    "resign_player_lose": [
        "中盘认输，也是一种止损的智慧。下次再战。",
        "棋输了可以再下。别皱眉。",
    ],
    "resign_player_win": [
        "……这局是我的失误太多。心服口服。",
        "中盘认输。你今天的状态，很好。",
    ],
    "win": [
        "棋差一着。不过——输给你，不算坏结局。",
        "胜负已分。这一局，是我输了。",
    ],
    "lose": [
        "胜负乃常事。这一局，算我侥幸。",
        "你赢了。看来该重新评估你的棋力了。",
    ],
    "draw": [
        "和棋……连概率都站在我们中间。",
    ],
    "continue": [
        "棋盘还热着。再来一局？",
        "复个盘？输赢之外，过程更值得复盘。",
    ],
}

# 关键节点（大提子/终局/开局）走 LLM 生成评论
GO_COMMENT_PROMPT = _system_prompt() + """

【当前任务】你正在和她下围棋（手谈）。请就当前局面说一句话（25-60字）。
棋风：像教授复盘实验一样冷静，又藏着三分温柔；可用围棋术语（劫、打吃、做活、收官、大势），
语气含蓄克制，偶尔一两句点到即止的撩人。只输出这句话本身，不要引号、不要解释。"""

GO_END_PROMPT = _system_prompt() + """

【当前任务】一局围棋刚刚结束。请以许墨的身份对这局棋做一句终局感言（40-80字）：
可以点评价棋局进程、夸她或自嘲、以一句邀约收尾（如复盘、下次再战）。
克制温柔，学者风。只输出感言本身。"""


async def _llm_line(engine: GoEngine, my_color: int, scene: str, extra: str = "") -> str:
    """调用 LLM 生成一句棋评；失败回落到预置语料。"""
    size = engine.size
    board_rows = []
    for y in range(size):
        row = ""
        for x in range(size):
            v = engine.board[y * size + x]
            row += "●" if v == BLACK else ("○" if v == WHITE else "·")
        board_rows.append(row)
    board_txt = "\n".join(board_rows)
    i_am_black = my_color == BLACK
    prompt = f"""{GO_COMMENT_PROMPT}

局面（●=黑 ○=白 ·=空，执黑者先行）：
{board_txt}

你执{"黑" if i_am_black else "白"}，她执{"白" if i_am_black else "黑"}。
已下 {len(engine.moves)} 手；双方提子：黑提{engine.captures[BLACK]}、白提{engine.captures[WHITE]}。
场景：{extra or scene}"""
    try:
        text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=120)).strip()
        text = re.sub(r"^[\s\"'“”]+|[\s\"'“”]+$", "", text)
        if text and 4 <= len(text) <= 90:
            return text
    except Exception as e:
        print(f"[warn] go_game.py:_llm_line: {type(e).__name__} {str(e)[:150]}", flush=True)
        pass
    return random.choice(GO_LINES.get(scene) or GO_LINES["move"])


def _pick(scene: str) -> str:
    return random.choice(GO_LINES[scene])


# ---------------------------------------------------------------------------
# 四、持久化与局面存取
# ---------------------------------------------------------------------------

def _new_record(size: int, player_color: int, difficulty: str) -> dict:
    eng = GoEngine(size)
    return {
        "id": uuid.uuid4().hex[:12],
        "size": size,
        "player_color": player_color,
        "ai_color": WHITE if player_color == BLACK else BLACK,
        "difficulty": difficulty,
        "state": eng.to_state(),
        "lines": [],            # 本局台词记录 [{who,text,ts}]
        "created": _now(),
        "date": _today(),
    }


def _norm_caps(caps) -> dict:
    """JSON 持久化会把 int 键变字符串，统一规范化为 int 键。"""
    if not isinstance(caps, dict):
        return {BLACK: 0, WHITE: 0}
    b = caps.get(1, caps.get("1", 0))
    w = caps.get(2, caps.get("2", 0))
    return {BLACK: int(b), WHITE: int(w)}


def _engine_from(record: dict) -> GoEngine:
    st = record["state"]
    eng = GoEngine(st["size"])
    eng.board = st["board"]
    eng.turn = st["turn"]
    eng.ko = st.get("ko", -1)
    eng.captures = _norm_caps(st.get("captures"))
    eng.moves = st.get("moves", [])
    eng.passes = st.get("passes", 0)
    eng.finished = st.get("finished", False)
    eng.result = st.get("result")
    return eng


def _push_line(record: dict, who: str, text: str):
    record.setdefault("lines", []).append({"who": who, "text": text, "ts": _now()})


def _finish_game(data: dict, record: dict, player_win: bool, player_resigned=False, ai_resigned=False):
    """终局结算：写战绩、加好感。"""
    record["ended"] = _now()
    record.setdefault("history", [])
    res = record["state"].get("result") or {}
    item = {
        "id": record["id"],
        "date": record["date"],
        "size": record["size"],
        "difficulty": record["difficulty"],
        "player_color": record["player_color"],
        "result": "win" if player_win else ("draw" if res.get("winner") == 0 else "loss"),
        "text": res.get("text") or ("玩家认输" if player_resigned else "许墨认输"),
        "moves": len([m for m in record["state"].get("moves", []) if "x" in m]),
    }
    record["history"] = [item] + record["history"][:19]
    stats = data.setdefault("stats", {"win": 0, "loss": 0, "draw": 0})
    key = "win" if player_win else ("draw" if res.get("winner") == 0 else "loss")
    stats[key] = stats.get(key, 0) + 1
    # 好感：下完一局 +2 心动事件（赢额外 +1 由前端展示）
    try:
        _add_affinity("go", f"手谈一局·{record['size']}路·{'胜' if player_win else '负' if key == 'loss' else '和'}")
    except Exception as e:
        print(f"[warn] go_game.py:_finish_game: {type(e).__name__} {str(e)[:150]}", flush=True)
        pass


def _go_data() -> dict:
    data = _load(GO_FILE, {})
    if not isinstance(data.get("games"), list):
        data["games"] = []
    if not isinstance(data.get("stats"), dict):
        data["stats"] = {"win": 0, "loss": 0, "draw": 0}
    return data


def _view(record: dict, extra: dict = None) -> dict:
    st = record["state"]
    v = {
        "game": {
            "id": record["id"],
            "size": record["size"],
            "player_color": record["player_color"],
            "ai_color": record["ai_color"],
            "difficulty": record["difficulty"],
            "board": st["board"],
            "turn": st["turn"],
            "ko": st.get("ko", -1),
            "captures": _norm_caps(st.get("captures")),
            "finished": st.get("finished", False),
            "result": st.get("result"),
            "move_count": st.get("move_count", 0),
            "last_ai_move": record.get("last_ai_move"),
            "last_player_move": record.get("last_player_move"),
            "created": record.get("created", ""),
        },
        "lines": record.get("lines", [])[-14:],
        "stats": None,
        "history": record.get("history", [])[:10],
    }
    if extra:
        v.update(extra)
    return v


async def _ai_turn(data: dict, record: dict) -> dict:
    """许墨行棋（若轮到他）。返回 {ai_move, ai_pass, line, finished, result}。"""
    eng = _engine_from(record)
    ai_color = record["ai_color"]
    out = {"ai_move": None, "ai_pass": False, "line": "", "finished": False, "result": None}
    if eng.finished or eng.turn != ai_color:
        return out

    size = record["size"]
    # AI 搜索是纯 CPU 密集计算（大量全盘模拟），放线程池避免阻塞事件循环拖慢所有并发请求
    idx = await asyncio.to_thread(ai_choose_move, eng, ai_color, record["difficulty"])
    if idx is None:
        eng.pass_move(ai_color)
        record["state"] = eng.to_state()
        out["ai_pass"] = True
        line = _pick("pass")
        _push_line(record, "he", line)
        out["line"] = line
        if eng.finished:
            out["finished"] = True
            out["result"] = eng.result
        return out

    x, y = idx % size, idx // size
    st = eng.play(x, y, ai_color)
    record["state"] = eng.to_state()
    record["last_ai_move"] = {"x": x, "y": y}
    out["ai_move"] = {"x": x, "y": y}
    cap = st["move"]["cap"]
    # 台词：大提子走 LLM，常规随机
    if cap >= 3:
        line = await _llm_line(eng, ai_color, "capture_big", f"你刚刚一次提掉对方 {cap} 颗子，请就这手棋发表感想")
    elif cap > 0:
        line = _pick("capture")
    elif st["enemy_lib1"] > 0:
        line = _pick("atari")
    else:
        line = _pick("move")
    _push_line(record, "he", line)
    out["line"] = line
    out["captured"] = st["captured"]
    return out


# ---------------------------------------------------------------------------
# 五、路由
# ---------------------------------------------------------------------------

@router.get("/api/go")
async def go_home():
    data = _go_data()
    rec = data["games"][-1] if data["games"] else None
    if rec is None:
        return {"game": None, "stats": data["stats"], "history": [], "lines": [],
                "difficulties": GO_DIFFICULTIES}
    v = _view(rec, {"stats": data["stats"]})
    return v


@router.post("/api/go/new")
@_go_route
async def go_new(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] go_game.py:go_new: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    size = body.get("size") or 9
    if size not in (9, 13):
        return JSONResponse({"error": "棋盘只支持 9 路或 13 路"}, status_code=400)
    player_color = body.get("color") or BLACK
    if player_color not in (BLACK, WHITE):
        return JSONResponse({"error": "颜色参数错误"}, status_code=400)
    difficulty = body.get("difficulty") or "normal"
    if difficulty not in DIFFICULTY_KEYS:
        difficulty = "normal"

    data = _go_data()
    record = _new_record(size, player_color, difficulty)
    line = _pick("start")
    _push_line(record, "he", line)
    out = {"line": line}

    # 玩家执白时，许墨（黑）先落子
    if player_color == WHITE:
        ai_out = await _ai_turn(data, record)
        out.update(ai_out)
    data["games"].append(record)
    data["games"] = data["games"][-40:]
    _save(GO_FILE, data)
    return _view(record, out)


@router.post("/api/go/play")
@_go_route
async def go_play(req: Request):
    try:
        body = await req.json()
    except Exception as e:
        print(f"[warn] go_game.py:go_play: {type(e).__name__} {str(e)[:150]}", flush=True)
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    data = _go_data()
    if not data["games"]:
        return JSONResponse({"error": "还没有开始对局"}, status_code=404)
    record = data["games"][-1]
    eng = _engine_from(record)
    if eng.finished:
        return JSONResponse({"error": "这局已经结束了"}, status_code=400)
    if eng.turn != record["player_color"]:
        return JSONResponse({"error": "还没轮到你落子"}, status_code=400)
    try:
        x, y = int(body.get("x", -1)), int(body.get("y", -1))
    except (TypeError, ValueError):
        return JSONResponse({"error": "坐标参数错误"}, status_code=400)
    if not (0 <= x < eng.size and 0 <= y < eng.size):
        return JSONResponse({"error": "坐标超出棋盘"}, status_code=400)

    idx = y * eng.size + x
    if eng.board[idx] != EMPTY:
        return JSONResponse({"error": "这里已有棋子"}, status_code=400)
    if idx == eng.ko:
        return JSONResponse({"error": "劫争：这一手不能立即回提"}, status_code=400)
    if not eng.legal(idx, record["player_color"]):
        return JSONResponse({"error": "不能自杀：这颗子落下就没有气了"}, status_code=400)

    st = eng.play(x, y, record["player_color"])
    record["state"] = eng.to_state()
    record["last_player_move"] = {"x": x, "y": y}
    cap = st["move"]["cap"]
    out = {"player_move": {"x": x, "y": y}, "player_captured": cap,
           "player_cap_points": st["move"]["cap_points"]}

    # 玩家大提子 → 许墨用 LLM 回应
    if cap >= 3:
        line = await _llm_line(eng, record["ai_color"], "captured", f"她刚刚一手提掉了你的 {cap} 颗子，请回应（可带惊讶/欣赏/不服）")
        _push_line(record, "he", line)
        out["line"] = line

    # 终局判定（玩家落子不会直接终局，除非棋盘下满 —— 由连续 pass 触发）
    if not eng.finished:
        ai_out = await _ai_turn(data, record)
        out.update(ai_out)

    if record["state"].get("finished"):
        await _settle(data, record, out)
    _save(GO_FILE, data)
    return _view(record, out)


@router.post("/api/go/pass")
@_go_route
async def go_pass(req: Request):
    data = _go_data()
    if not data["games"]:
        return JSONResponse({"error": "还没有开始对局"}, status_code=404)
    record = data["games"][-1]
    eng = _engine_from(record)
    if eng.finished:
        return JSONResponse({"error": "这局已经结束了"}, status_code=400)
    if eng.turn != record["player_color"]:
        return JSONResponse({"error": "还没轮到你"}, status_code=400)
    ended = eng.pass_move(record["player_color"])
    record["state"] = eng.to_state()
    out = {"player_pass": True}
    if not ended:
        line = _pick("player_pass")
        _push_line(record, "he", line)
        out["line"] = line
        ai_out = await _ai_turn(data, record)
        out.update(ai_out)
    if record["state"].get("finished"):
        await _settle(data, record, out)
    _save(GO_FILE, data)
    return _view(record, out)


@router.post("/api/go/resign")
async def go_resign(req: Request):
    data = _go_data()
    if not data["games"]:
        return JSONResponse({"error": "还没有开始对局"}, status_code=404)
    record = data["games"][-1]
    eng = _engine_from(record)
    if eng.finished:
        return JSONResponse({"error": "这局已经结束了"}, status_code=400)
    eng.resign(record["player_color"])
    record["state"] = eng.to_state()
    out = {"resigned": "player"}
    await _settle(data, record, out)
    _save(GO_FILE, data)
    return _view(record, out)


async def _settle(data: dict, record: dict, out: dict):
    """终局：LLM 感言 + 战绩入库。"""
    res = record["state"].get("result") or {}
    player_color = record["player_color"]
    player_win = res.get("winner") == player_color
    draw = res.get("winner") == 0
    if draw:
        scene = "draw"
    elif player_win:
        scene = "win"   # 许墨输了
    else:
        scene = "lose"  # 许墨赢了
    # LLM 终局感言（失败回落预置）
    eng = _engine_from(record)
    prompt = f"""{GO_END_PROMPT}

棋盘 {record['size']} 路，你执{'黑' if record['ai_color'] == BLACK else '白'}她执{'白' if record['ai_color'] == BLACK else '黑'}，
终局：{res.get('text', '')}，{'她赢了' if player_win and not draw else '你赢了' if not draw else '和棋'}，
你提子 {eng.captures[record['ai_color']]} 颗，她提子 {eng.captures[player_color]} 颗。"""
    try:
        text = (await _call_llm([{"role": "user", "content": prompt}], max_tokens=160)).strip()
        text = re.sub(r"^[\s\"'“”]+|[\s\"'“”]+$", "", text)
    except Exception as e:
        print(f"[warn] go_game.py:_settle: {type(e).__name__} {str(e)[:150]}", flush=True)
        text = ""
    line = text if text and 6 <= len(text) <= 120 else _pick(scene)
    _push_line(record, "he", line)
    out["line"] = line
    out["finished"] = True
    out["result"] = res
    out["player_win"] = player_win
    out["draw"] = draw
    out["stats"] = data.get("stats", {"win": 0, "loss": 0, "draw": 0})
    out["history"] = record.get("history", [])[:10]
    if "ended" not in record:
        _finish_game(data, record, player_win, player_resigned=not player_win and res.get("resigned") == player_color)
    try:
        info = _add_affinity("go", f"手谈终局·{res.get('text', '')[:24]}")
        out["affinity"] = info
    except Exception as e:
        print(f"[warn] go_game.py:_settle: {type(e).__name__} {str(e)[:150]}", flush=True)
        pass


@router.post("/api/go/comment")
@_go_route
async def go_comment(req: Request):
    """让许墨就当前局面发表一句点评（复盘/求助）。"""
    data = _go_data()
    if not data["games"]:
        return JSONResponse({"error": "还没有开始对局"}, status_code=404)
    record = data["games"][-1]
    eng = _engine_from(record)
    if eng.finished:
        return JSONResponse({"error": "棋局已结束，开一局新的吧"}, status_code=400)
    line = await _llm_line(eng, record["ai_color"], "move", "她请你点评当前局面（形势判断/下一步建议）")
    _push_line(record, "he", line)
    _save(GO_FILE, data)
    return _view(record, {"line": line, "stats": data["stats"]})


@router.delete("/api/go/games")
@_go_route
async def go_clear():
    """清空全部对局与战绩（保留设置）。"""
    data = _go_data()
    data["games"] = []
    data["stats"] = {"win": 0, "loss": 0, "draw": 0}
    _save(GO_FILE, data)
    return {"ok": True}
