"""多用户注册 / 登录 / 会话管理。

- 用户注册表：users.json（全局，不随角色隔离），每条记录含 pbkdf2 加盐口令哈希。
- 会话：HMAC-SHA256 签名的 cookie（xumo_sess = b64(username)|ts|sig），服务端不存状态。
- 与旧 owner 访问口令并存：access_gate 优先用注册会话，其次回退旧口令。

数据隔离：登录后 _role_ctx 被设为 username，RolePath / role_file 自动把数据
路由到 users_data/<username>/，实现多账号互不干扰。

Profile 扩展（2026-08-17）：
- 注册时可选填 nickname / avatar / birthday / gender
- 支持修改密码（旧密码校验）、更新 profile、注销所有会话
- 注册速率限制：同一 IP 在窗口期内最多 N 次
"""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from store_common import atomic_json, file_lock

BASE_DIR = Path(__file__).parent
USERS_FILE = BASE_DIR / "users.json"
USERS_DATA_DIR = BASE_DIR / "users_data"
SECRET_FILE = BASE_DIR / ".secret"

SESSION_COOKIE = "xumo_sess"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 天

USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fa5]{2,32}$")
PBKDF2_ROUNDS = 100_000

# Profile 字段白名单 + 校验规则
PROFILE_FIELDS = ("nickname", "avatar", "birthday", "gender")
NICKNAME_RE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9_\- ]{0,24}$")
BIRTHDAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
GENDER_VALUES = {"male", "female", "other", ""}
MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2MB

# 注册速率限制
REGISTER_RATE_LIMIT = 5       # 窗口期内最多注册次数
REGISTER_RATE_WINDOW = 60     # 窗口期（秒）

# 登录速率限制（双维度：IP + 账号，防暴力爆破 / 撞库）
LOGIN_RATE_LIMIT = 10         # 同一 IP 窗口期内最多尝试次数
LOGIN_ACCOUNT_LIMIT = 10      # 同一账号窗口期内最多尝试次数
LOGIN_RATE_WINDOW = 60        # 窗口期（秒）
LOGIN_COOLDOWN = 300          # 触发限流后的冷却时间（秒）

# 密码强度
MIN_PASSWORD_LEN = 8          # 商业级最低 8 位（NIST SP 800-63B）

# 常见弱密码黑名单（仅本地少量高频项，完整评估建议接 zxcvbn / HIBP）
WEAK_PASSWORDS = {
    "12345678", "123456789", "1234567890", "password", "password1",
    "qwerty123", "qwerty1234", "abc12345", "11111111", "00000000",
    "12312312", "iloveyou1", "admin123", "administrator", "letmein1",
    "welcome1", "monkey123", "dragon123", "1234567a", "1q2w3e4r",
}

_secret_cache = None
_users_cache = None
_users_cache_mtime = 0


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
    """读取用户表，带 mtime 缓存（避免每请求都做磁盘 IO）。"""
    global _users_cache, _users_cache_mtime
    try:
        mtime = USERS_FILE.stat().st_mtime
    except FileNotFoundError:
        _users_cache = []
        _users_cache_mtime = 0
        return []
    if _users_cache is not None and mtime == _users_cache_mtime:
        return _users_cache
    try:
        data = json.loads(USERS_FILE.read_text(encoding="utf-8"))
        users = data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        users = []
    _users_cache = users
    _users_cache_mtime = mtime
    return users


def _invalidate_cache() -> None:
    global _users_cache, _users_cache_mtime
    _users_cache = None
    _users_cache_mtime = 0


def _save_users(users: list) -> None:
    with file_lock(USERS_FILE):
        atomic_json(USERS_FILE, users)
    _invalidate_cache()


def _find_user(users: list, username: str) -> dict | None:
    for u in users:
        if u.get("username") == username:
            return u
    return None


def username_taken(username: str) -> bool:
    return _find_user(_load_users(), username) is not None


def users_exist() -> bool:
    return bool(_load_users())


# ----------------------------- Profile 校验 -----------------------------
def _sanitize_profile(profile: dict | None) -> dict:
    """过滤并校验 profile 字段，返回合法字段组成的 dict（仅含允许的 key）。"""
    out = {}
    if not isinstance(profile, dict):
        return out
    nickname = (profile.get("nickname") or "").strip()
    if nickname and not NICKNAME_RE.match(nickname):
        raise ValueError("昵称为 1-24 位中英文/数字/空格")
    if nickname:
        out["nickname"] = nickname
    avatar = (profile.get("avatar") or "").strip()
    if avatar:
        if not avatar.startswith(("http://", "https://", "/static/", "/api/auth/avatar/", "data:")):
            raise ValueError("头像须为 http(s) 链接、data URL 或本地路径")
        out["avatar"] = avatar
    birthday = (profile.get("birthday") or "").strip()
    if birthday:
        if not BIRTHDAY_RE.match(birthday):
            raise ValueError("生日格式应为 YYYY-MM-DD")
        out["birthday"] = birthday
    gender = (profile.get("gender") or "").strip()
    if gender and gender not in {"male", "female", "other"}:
        raise ValueError("性别取值非法")
    if gender:
        out["gender"] = gender
    return out


def save_avatar(username: str, data_url: str) -> str:
    """把 data URL 形式的头像保存到 users_data/<user>/avatar/<hash>.<ext>，
    返回可直接用于 <img src> 的相对路径（如 /static/users_data/<user>/avatar/xxx.png）。
    """
    if not data_url.startswith("data:"):
        raise ValueError("头像必须为 data URL")
    # 解析 data:image/png;base64,XXXX
    try:
        header, b64 = data_url.split(",", 1)
        mime = header.split(":")[1].split(";")[0]  # image/png
        ext_map = {
            "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
            "image/webp": "webp", "image/gif": "gif",
        }
        ext = ext_map.get(mime, "png")
        raw = base64.b64decode(b64)
    except Exception as e:
        raise ValueError(f"头像解码失败：{e}")
    if len(raw) > MAX_AVATAR_BYTES:
        raise ValueError(f"头像过大（>{MAX_AVATAR_BYTES // 1024}KB）")
    # 深度防御：用 magic byte 校验真实文件类型，而非仅信任 data URL header 里的 MIME，
    # 挡住伪造 MIME 的恶意/损坏文件
    is_png = raw[:8] == b"\x89PNG\r\n\x1a\n"
    is_jpg = raw[:3] == b"\xff\xd8\xff"
    is_gif = raw[:6] in (b"GIF87a", b"GIF89a")
    is_webp = len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
    if not (is_png or is_jpg or is_gif or is_webp):
        raise ValueError("头像文件格式非法（仅支持 PNG/JPG/GIF/WEBP）")
    h = hashlib.sha256(raw).hexdigest()[:16]
    user_dir = USERS_DATA_DIR / username
    avatar_dir = user_dir / "avatar"
    avatar_dir.mkdir(parents=True, exist_ok=True)
    # 清掉旧头像（同名前缀都删掉）
    for old in avatar_dir.glob("*"):
        try:
            old.unlink()
        except OSError:
            pass
    fname = f"{h}.{ext}"
    (avatar_dir / fname).write_bytes(raw)
    # 头像由 /api/auth/avatar/<username> 端点流式返回（避免暴露整个 users_data 目录）
    # 带 v 参数防缓存（更换头像后立即生效）
    return f"/api/auth/avatar/{username}?v={h}"


def get_avatar_path(username: str) -> Path | None:
    """返回该用户当前头像的磁盘路径（avatar 目录下最新的一张）。无头像返回 None。"""
    if not USERNAME_RE.match(username or ""):
        return None
    avatar_dir = USERS_DATA_DIR / username / "avatar"
    if not avatar_dir.exists():
        return None
    files = sorted(avatar_dir.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# ----------------------------- 注册 / 登录 -----------------------------
def _validate_password(password: str) -> None:
    """密码强度校验：长度 + 弱密码黑名单。不满足抛 ValueError。"""
    pw = password or ""
    if len(pw) < MIN_PASSWORD_LEN:
        raise ValueError(f"密码至少 {MIN_PASSWORD_LEN} 位")
    if pw.lower() in WEAK_PASSWORDS:
        raise ValueError("密码过于简单，请更换更强的密码")


def register_user(username: str, password: str, profile: dict | None = None) -> dict:
    """注册新用户。失败抛 ValueError（调用方转 HTTP 错误）。"""
    username = (username or "").strip()
    password = password or ""
    if not USERNAME_RE.match(username):
        raise ValueError("用户名需为 2-32 位中英文、数字或下划线")
    _validate_password(password)
    if username_taken(username):
        raise ValueError("该用户名已被占用")
    safe_profile = _sanitize_profile(profile)
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    user = {
        "username": username,
        "salt": salt,
        "hash": dk.hex(),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sess_revoked_at": 0,  # 历史会话全部作废的时间点；0 表示未作废
        "profile": safe_profile,
    }
    users = _load_users()
    users.append(user)
    _save_users(users)
    return {"username": username, "profile": safe_profile}


def verify_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    u = _find_user(_load_users(), username)
    if not u:
        return False
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        (password or "").encode("utf-8"),
        u.get("salt", "").encode("utf-8"),
        PBKDF2_ROUNDS,
    )
    return hmac.compare_digest(dk.hex(), u.get("hash", ""))


def delete_user(username: str) -> bool:
    """删除用户记录及其数据目录（用于注册失败回滚等场景）。"""
    username = (username or "").strip()
    users = _load_users()
    original_len = len(users)
    users = [u for u in users if u.get("username") != username]
    if len(users) == original_len:
        return False
    _save_users(users)
    user_dir = USERS_DATA_DIR / username
    if user_dir.exists():
        import shutil
        try:
            shutil.rmtree(user_dir)
        except OSError:
            pass
    return True


# ----------------------------- Profile 读写 -----------------------------
def get_user_profile(username: str) -> dict | None:
    """返回安全 profile（不含 salt/hash）；用户不存在返回 None。"""
    u = _find_user(_load_users(), username)
    if not u:
        return None
    return {
        "username": u["username"],
        "nickname": u.get("profile", {}).get("nickname", ""),
        "avatar": u.get("profile", {}).get("avatar", ""),
        "birthday": u.get("profile", {}).get("birthday", ""),
        "gender": u.get("profile", {}).get("gender", ""),
        "created_at": u.get("created_at", ""),
    }


def get_user_role(username: str) -> str:
    """返回用户角色：admin / user。用户不存在返回 "user"。"""
    u = _find_user(_load_users(), username)
    if not u:
        return "user"
    return (u.get("role") or "user")


def is_admin(username: str) -> bool:
    """该用户是否为最高管理员。"""
    return get_user_role(username) == "admin"


def list_users() -> list:
    """返回所有注册用户的脱敏信息（不含 salt/hash）。"""
    out = []
    for u in _load_users():
        username = u.get("username", "")
        prof = get_user_profile(username)
        if not prof:
            continue
        prof["role"] = get_user_role(username)
        prof["updated_at"] = u.get("updated_at", "")
        out.append(prof)
    return out


def update_user_profile(username: str, profile: dict) -> dict:
    """部分更新 profile（仅允许白名单字段）。返回更新后的 profile。"""
    safe = _sanitize_profile(profile)
    users = _load_users()
    u = _find_user(users, username)
    if not u:
        raise ValueError("用户不存在")
    cur = dict(u.get("profile", {}))
    cur.update(safe)
    u["profile"] = cur
    u["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_users(users)
    return get_user_profile(username)


def change_password(username: str, old_password: str, new_password: str) -> bool:
    """修改密码：先校验旧密码，再写入新 salt+hash，并作废所有旧会话。
    返回 True 表示成功；失败抛 ValueError。"""
    if not verify_user(username, old_password):
        raise ValueError("旧密码错误")
    _validate_password(new_password or "")
    if (new_password or "") == old_password:
        raise ValueError("新密码不能与旧密码相同")
    users = _load_users()
    u = _find_user(users, username)
    if not u:
        raise ValueError("用户不存在")
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", new_password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ROUNDS)
    u["salt"] = salt
    u["hash"] = dk.hex()
    u["pwd_changed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    # 改密后所有旧会话立即失效（parse_session 会按 sess_revoked_at 拒绝）
    u["sess_revoked_at"] = int(time.time())
    _save_users(users)
    return True


def revoke_all_sessions(username: str) -> None:
    """作废该用户的所有现有会话：把 sess_revoked_at 设为当前时间。
    新签发的会话 ts >= 该时间，不受影响；旧会话 ts < 该时间，会被 parse_session 拒绝。
    """
    users = _load_users()
    u = _find_user(users, username)
    if not u:
        raise ValueError("用户不存在")
    u["sess_revoked_at"] = int(time.time())
    u["sessions_revoked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    _save_users(users)


# ----------------------------- 会话签名 -----------------------------
def _b64enc(s: str) -> str:
    return base64.urlsafe_b64encode(s.encode("utf-8")).decode("ascii")


def _b64dec(s: str) -> str | None:
    try:
        return base64.urlsafe_b64decode(s.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def make_session(username: str) -> str:
    """生成带签名、带过期时间的会话令牌。
    username 经 URL-safe base64 编码，避免中文用户名在 HTTP cookie 头触发 latin-1 编码错误。
    """
    ts = str(int(time.time()))
    payload = f"{_b64enc(username)}|{ts}"
    return f"{payload}|{_sign(payload)}"


def parse_session(token: str) -> str | None:
    """校验会话令牌：签名 + 过期 + 该用户 sess_revoked_at。
    有效且未过期返回 username，否则 None。兼容旧版未编码的 ASCII 用户名令牌。
    """
    if not token or token.count("|") != 2:
        return None
    user_part, ts, sig = token.split("|")
    payload = f"{user_part}|{ts}"
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    username = _b64dec(user_part)
    if username is None:
        username = user_part  # 兼容旧版未编码令牌
    try:
        ts_int = int(ts)
    except ValueError:
        return None
    if int(time.time()) - ts_int > SESSION_MAX_AGE:
        return None
    # 检查用户是否已注销所有会话 / 改密
    u = _find_user(_load_users(), username)
    if not u:
        return None
    revoked_at = int(u.get("sess_revoked_at", 0) or 0)
    if revoked_at and ts_int < revoked_at:
        return None
    return username


# ----------------------------- 注册速率限制 -----------------------------
_register_hits: dict = defaultdict(deque)


def check_register_rate(ip: str) -> tuple[bool, int]:
    """滑动窗口限流：返回 (允许, retry_after 秒)。
    每窗口期 REGISTER_RATE_WINDOW 秒内最多 REGISTER_RATE_LIMIT 次。
    """
    now = time.time()
    q = _register_hits[ip]
    while q and q[0] < now - REGISTER_RATE_WINDOW:
        q.popleft()
    if len(q) >= REGISTER_RATE_LIMIT:
        retry = int(REGISTER_RATE_WINDOW - (now - q[0])) + 1
        return False, max(retry, 1)
    q.append(now)
    return True, 0


# ----------------------------- 登录速率限制 -----------------------------
_login_ip_hits: dict = defaultdict(deque)
_login_acct_hits: dict = defaultdict(deque)
_login_cooldown_until: dict = defaultdict(float)


def check_login_rate(ip: str, username: str) -> tuple[bool, int]:
    """登录双维度滑动窗口限流：同一 IP、同一账号各限 LOGIN_*_LIMIT 次/窗口期。

    触发限流后进入 LOGIN_COOLDOWN 秒冷却（IP 与账号两个维度都拦截），
    返回 (允许, retry_after 秒)。成功登录由调用方调用 reset_login_rate 清零。
    """
    now = time.time()
    # 冷却期优先：命中后整段冷却，不再细算窗口
    until = max(_login_cooldown_until.get(ip, 0.0), _login_cooldown_until.get(username, 0.0))
    if now < until:
        return False, int(until - now) + 1

    def _slide(q, limit):
        while q and q[0] < now - LOGIN_RATE_WINDOW:
            q.popleft()
        return len(q) >= limit

    ip_blocked = _slide(_login_ip_hits[ip], LOGIN_RATE_LIMIT)
    acct_blocked = _slide(_login_acct_hits[username], LOGIN_ACCOUNT_LIMIT)
    if ip_blocked or acct_blocked:
        _login_cooldown_until[ip] = now + LOGIN_COOLDOWN
        _login_cooldown_until[username] = now + LOGIN_COOLDOWN
        return False, LOGIN_COOLDOWN

    _login_ip_hits[ip].append(now)
    _login_acct_hits[username].append(now)
    return True, 0


def reset_login_rate(ip: str, username: str) -> None:
    """登录成功后清零该 IP / 账号的失败计数。"""
    _login_ip_hits.pop(ip, None)
    _login_acct_hits.pop(username, None)
    _login_cooldown_until.pop(ip, None)
    _login_cooldown_until.pop(username, None)
