# -*- coding: utf-8 -*-
"""KataGo GTP 适配器：持久化进程，按需重建棋盘并 genmove。

调用约定：
    idx = katago_choose_move(moves, size, ai_color)
        moves: go_game.GoEngine.moves 列表，元素形如 {"x","y","color"} 或 {"pass":1,"color"}
        size : 9 或 13
        ai_color: BLACK=1 / WHITE=2（与 go_game.py 同步）
        返回 idx = y * size + x；若 KataGo 不可用或返回 resign/pass，返回 None

坐标映射（已与 static/index.html goDraw 校准）：
    go_game.py: idx = y * size + x，y=0 是棋盘顶端（行号 size），y=size-1 是底端（行号 1）
    GTP      : 列字母 = "ABCDEFGHJKLMNOPQRST"[x]，行号 = size - y
"""
import os
import re
import subprocess
import threading
import time

# --- 路径 -------------------------------------------------------------
_KATAGO_DIR = r"g:\xumo\katago"
_KATAGO_EXE = os.path.join(_KATAGO_DIR, "katago.exe")
_KATAGO_CFG = os.path.join(_KATAGO_DIR, "default_gtp.cfg")
_KATAGO_MODEL = os.path.join(_KATAGO_DIR, "default_model.bin.gz")

# 与 go_game.py 同步
BLACK, WHITE = 1, 2
_GTP_COLOR = {BLACK: "black", WHITE: "white"}
_LETTERS = "ABCDEFGHJKLMNOPQRST"  # 跳过 I


def _to_gtp_coord(x: int, y: int, size: int) -> str:
    """go_game (x, y) → GTP 字符串，如 (5, 2, 9) → 'F7'。"""
    return _LETTERS[x] + str(size - y)


def _from_gtp_coord(coord: str, size: int):
    """GTP 坐标 → (x, y)，如 'F6' / 'pass' / 'resign'。非法返回 None。"""
    coord = (coord or "").strip().lower()
    if coord in ("pass", "resign", ""):
        return None
    m = re.match(r"^([a-hj-z])(\d+)$", coord)
    if not m:
        return None
    letter, num = m.group(1), int(m.group(2))
    x = _LETTERS.index(letter.upper()) if letter.upper() in _LETTERS else -1
    if x < 0 or x >= size:
        return None
    if not (1 <= num <= size):
        return None
    y = size - num
    return x, y


# --- 持久进程 --------------------------------------------------------

class _KataGoProc:
    """单例 KataGo GTP 进程：线程安全，进程崩溃自愈。"""

    _lock = threading.Lock()
    _proc = None
    _last_use = 0.0

    @classmethod
    def _ensure(cls):
        """启动进程（如未启动）。返回 (stdin, stdout)。失败抛异常。"""
        if cls._proc is not None and cls._proc.poll() is None:
            return cls._proc.stdin, cls._proc.stdout
        # 启动新进程
        if not os.path.exists(_KATAGO_EXE):
            raise RuntimeError(f"未找到 katago.exe: {_KATAGO_EXE}")
        if not os.path.exists(_KATAGO_MODEL):
            raise RuntimeError(f"未找到模型文件: {_KATAGO_MODEL}")
        # logToStderr=false → stderr 启动后基本安静；Tuner 首次可能输出
        proc = subprocess.Popen(
            [_KATAGO_EXE, "gtp", "-config", _KATAGO_CFG, "-model", _KATAGO_MODEL],
            cwd=_KATAGO_DIR,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
        cls._proc = proc
        # 等待 "GTP ready, beginning main protocol loop"（最多 180s，首次需调优）
        t0 = time.time()
        while time.time() - t0 < 180:
            if proc.poll() is not None:
                cls._proc = None
                raise RuntimeError(f"KataGo 启动失败 exit={proc.returncode}")
            # 不读 stderr 主线程，靠 stdout 响应 protocol_version 探测
            # KataGo GTP ready 后会响应 GTP 命令
            # 直接发 protocol_version 探测，带 30s 超时
            try:
                r = cls._send_once(proc, "protocol_version", timeout=30)
                if r is not None and "2" in r:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            try:
                proc.kill()
            except Exception:
                pass
            cls._proc = None
            raise RuntimeError("KataGo 启动超时（180s 内未响应 protocol_version）")
        cls._last_use = time.time()
        return cls._proc.stdin, cls._proc.stdout

    @staticmethod
    def _send_once(proc, line, timeout=30):
        """向指定 proc 发送命令并读取响应。返回首行响应内容（去除 '= '/'? ' 前缀）。"""
        stdin, stdout = proc.stdin, proc.stdout
        stdin.write(line + "\n")
        stdin.flush()
        out_lines = []
        t0 = time.time()
        while time.time() - t0 < timeout:
            line = stdout.readline()
            if not line:
                return None
            line = line.rstrip("\n")
            out_lines.append(line)
            # GTP 响应以 "= " 或 "? " 开头，空行结束
            if line.strip() == "" and any(o.startswith("=") or o.startswith("?") for o in out_lines):
                break
        if not out_lines:
            return None
        first = out_lines[0]
        if first.startswith("?"):
            return None  # 错误响应
        if first.startswith("="):
            return first[2:].strip()
        return first.strip()

    @classmethod
    def send(cls, line, timeout=30):
        """线程安全地发送命令。返回响应内容（无 '= ' 前缀）。失败返回 None。"""
        with cls._lock:
            try:
                stdin, stdout = cls._ensure()
            except RuntimeError as e:
                print(f"[katago] ensure failed: {e}", flush=True)
                return None
            cls._last_use = time.time()
            try:
                return cls._send_once(cls._proc, line, timeout=timeout)
            except Exception as e:
                print(f"[katago] send '{line}' exception: {e}", flush=True)
                # 进程可能死了，清理
                try:
                    if cls._proc:
                        cls._proc.kill()
                except Exception:
                    pass
                cls._proc = None
                return None

    @classmethod
    def close(cls):
        with cls._lock:
            if cls._proc and cls._proc.poll() is None:
                try:
                    cls._send_once(cls._proc, "quit", timeout=3)
                except Exception:
                    pass
                try:
                    cls._proc.terminate()
                    cls._proc.wait(timeout=3)
                except Exception:
                    try:
                        cls._proc.kill()
                    except Exception:
                        pass
            cls._proc = None


# --- 公开接口 --------------------------------------------------------

def katago_available() -> bool:
    """探测 KataGo 是否可用（发一条 protocol_version）。"""
    r = _KataGoProc.send("protocol_version", timeout=15)
    return r is not None and r.strip().startswith("2")


def katago_choose_move(moves, size: int, ai_color: int, komi: float = 5.5, timeout: int = 30):
    """按当前局面让 KataGo 生成一步。

    返回 idx = y * size + x；若 KataGo 选择 pass/resign 或不可用，返回 None。
    """
    gtp_color = _GTP_COLOR.get(ai_color)
    if gtp_color is None:
        return None
    # 1. 重置棋盘
    if _KataGoProc.send("boardsize " + str(size), timeout=15) is None:
        return None
    if _KataGoProc.send("clear_board", timeout=15) is None:
        return None
    if _KataGoProc.send(f"komi {komi}", timeout=15) is None:
        return None
    # 2. 重放 moves（play 命令）
    for m in moves:
        c = _GTP_COLOR.get(m.get("color"))
        if c is None:
            continue
        if "pass" in m:
            if _KataGoProc.send(f"play {c} pass", timeout=10) is None:
                return None
            continue
        x = m.get("x")
        y = m.get("y")
        if x is None or y is None:
            continue
        coord = _to_gtp_coord(x, y, size)
        if _KataGoProc.send(f"play {c} {coord}", timeout=10) is None:
            # 该手可能非法（被自方规则限制），尝试 undo 或直接放弃
            print(f"[katago] replay failed: {c} {coord}", flush=True)
            return None
    # 3. 让 KataGo 生成一步
    r = _KataGoProc.send(f"genmove {gtp_color}", timeout=timeout)
    if r is None:
        return None
    r = r.strip().lower()
    if r in ("pass", "resign") or not r:
        return None
    xy = _from_gtp_coord(r, size)
    if xy is None:
        print(f"[katago] bad genmove coord: {r!r}", flush=True)
        return None
    x, y = xy
    return y * size + x


def katago_close():
    """关闭持久进程（应用退出时调用）。"""
    _KataGoProc.close()
