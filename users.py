"""多用户注册 / 登录 / 会话管理。

- 用户注册表：users.json（全局，不随角色隔离），每条记录含 pbkdf2 加盐口令哈希。
- 会话：HMAC-SHA256 签名的 cookie（xumo_sess = username|ts|sig），服务端不存状态。
- 与旧 owner/guest 访问口令并存：access_gate 优先用注册会话，其次回退旧口令。

数据隔离：登录后 _role_ctx 被设为 username，RolePath / role_file 自动把数据
路由到 users_data/<username>/，实现多账号互不干扰。
"""
import hashlib
import hmac
import json
import re
import secrets
import time
from pathlib import Path

from store_common import atomic_json

BASE_DIR = Path(__file__).parent
USERS_FILE = BASE_DIR / "users.json"
SECRET_FILE = BASE_DIR / ".secret"

SESSION_COOKIE = "xumo_sess"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 天

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,32}$")
PBKDF2_ROUNDS = 100_000

_secret_cache = None


def _secret() -> str:
    global _secret_cache
    if _secret_cache is None:
        if SECRET_FILE.exists():
            _secret_cache = SECRET_FILE.read_text(encoding="utf-8").strip()
        if not _secret_cache:
            _secret_cache = secrets.token_hex(32)
            SECRET_FILE.write_text(_secret_cache, encoding="utf-8")
    return _secret_cache


def _sign(value: str) -> str:
    return hmac.new(_secret().encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


# ----------------------------- 用户表读写 -----------------------------
def _load_users() -> list:
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_users(users: list) -> None:
    atomic_json(USERS_FILE, users)


def username_taken(username: str) -> bool:
    return any(u.get("username") == username for u in _load_users())


def users_exist() -> bool:
    return bool(_load_users())


def register_user(username: str, password: str) -> dict:
    """注册新用户。失败抛 ValueError（调用方转 HTTP 错误）。"""
    username = (username or "").strip()
    password = password or ""
    if not USERNAME_RE.match(username):
        raise ValueError("用户名需为 2-32 位中英文、数字或下划线")
    if len(password) < 6:
        raise ValueError("密码至少 6 位")
    if username_taken(username):
        raise ValueError("该用户名已被占用")
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    user = {
        "username": username,
        "salt": salt,
        "hash": dk.hex(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    users = _load_users()
    users.append(user)
    _save_users(users)
    return {"username": username}


def verify_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    for u in _load_users():
        if u.get("username") == username:
            dk = hashlib.pbkdf2_hmac(
                "sha256",
                (password or "").encode("utf-8"),
                u.get("salt", "").encode("utf-8"),
                PBKDF2_ROUNDS,
            )
            return hmac.compare_digest(dk.hex(), u.get("hash", ""))
    return False


# ----------------------------- 会话签名 -----------------------------
def make_session(username: str) -> str:
    """生成带签名、带过期时间的会话令牌。"""
    ts = str(int(time.time()))
    payload = f"{username}|{ts}"
    return f"{payload}|{_sign(payload)}"


def parse_session(token: str) -> str | None:
    """校验会话令牌，有效且未过期返回 username，否则 None。"""
    if not token or token.count("|") != 2:
        return None
    username, ts, sig = token.split("|")
    if not hmac.compare_digest(sig, _sign(f"{username}|{ts}")):
        return None
    try:
        if int(time.time()) - int(ts) > SESSION_MAX_AGE:
            return None
    except ValueError:
        return None
    return username
