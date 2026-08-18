"""统一的 JSON 存储底层：原子写 + 按文件粒度的线程锁。

背景：原先 40+ 处 _save_* 直接 open("w") 覆盖写，进程崩溃/并发写会产生
半截 JSON；且读-改-写无锁，并发请求互相覆盖丢数据。

用法：
    from store_common import atomic_json, file_lock

    atomic_json(path, data)            # 原子写（tmp + os.replace + fsync）
    with file_lock(path):              # 同步读-改-写临界区（跨 app.py / 各 *_apps.py）
        data = load(path)
        ...
        atomic_json(path, data)

兼容 str / pathlib.Path / role_data.RolePath（后者经 __fspath__ 解析，
锁与临时文件按解析后的真实路径归一，owner 与注册用户天然隔离）。
"""
import json
import os
import threading
from pathlib import Path

_LOCKS: dict = {}
_LOCKS_GUARD = threading.Lock()


def _key(path) -> str:
    """把 str/Path/RolePath 归一成稳定字符串键（锁粒度 = 真实文件路径）。"""
    return os.fspath(path) if hasattr(path, "__fspath__") else str(path)


def file_lock(path):
    """获取按文件路径索引的 threading.RLock（懒创建，进程内全局唯一）。

    用可重入锁：任何在 `with file_lock(X):` 内部又调用 `file_lock(X)` 的
    代码（如临界区里的工具函数）都不会死锁，提升后续扩展的健壮性。

    说明：FastAPI async 路由默认全部跑在事件循环线程上，threading.RLock
    足以串行化同一文件的所有读-改-写；对 run_in_threadpool/asyncio.to_thread
    里跑的同步代码同样有效。
    """
    key = _key(path)
    with _LOCKS_GUARD:
        lk = _LOCKS.get(key)
        if lk is None:
            lk = threading.RLock()
            _LOCKS[key] = lk
        return lk


def atomic_json(path, data, indent: int = 2):
    """原子写 JSON：先写临时文件再 os.replace，避免半截文件。

    与原 `json.dump(..., ensure_ascii=False, indent=2)` 输出格式一致，
    保证已有数据文件 diff 最小。
    """
    real = Path(os.fspath(path))
    real.parent.mkdir(parents=True, exist_ok=True)
    tmp = real.with_name(real.name + f".tmp{os.getpid()}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, real)
    finally:
        # replace 成功后 tmp 已不存在；异常时清理残留，避免堆积 .tmp 文件
        try:
            tmp.unlink()
        except OSError:
            pass
