"""按请求角色动态路由数据文件：owner → 项目根；
已注册用户 → users_data/<username>/ 下同名文件（多用户数据隔离）。

由 access_gate 中间件在每个请求开始时 _role_ctx.set(scope)；
scope 取值：
  - "owner"       : 项目根（默认 / 旧主人口令登录）
  - "<username>"  : users_data/<username>/（注册用户，按账号隔离）
无请求上下文（启动 / 后台任务）默认 owner。
"""
import contextvars
from pathlib import Path

BASE_DIR = Path(__file__).parent
USERS_DATA_DIR = BASE_DIR / "users_data"
_role_ctx = contextvars.ContextVar("request_role", default="owner")


def _scope_root(scope: str) -> Path:
    """返回当前 scope 对应的数据根目录，并确保目录存在。"""
    if scope == "owner":
        return BASE_DIR
    # 注册用户：users_data/<username>
    p = USERS_DATA_DIR / scope
    p.mkdir(parents=True, exist_ok=True)
    return p


def role_root() -> Path:
    """当前请求上下文下的数据根目录（供快照 / 导出遍历）。"""
    return _scope_root(_role_ctx.get())


class RolePath:
    """兼容常用 Path 接口（exists/read_text/write_text/write_bytes/glob/mkdir/unlink/除法拼接），
    open() 经 __fspath__ 亦可直接使用；每次调用按当前角色实时解析。
    """

    def __init__(self, *parts):
        self._parts = parts

    def _path(self) -> Path:
        rel = Path(*self._parts)
        if _role_ctx.get() == "owner":
            return BASE_DIR / rel
        # 注册用户：数据隔离到 users_data/<username>/
        p = USERS_DATA_DIR / _role_ctx.get() / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def __fspath__(self):
        return str(self._path())

    def __str__(self):
        return str(self._path())

    def __truediv__(self, other):
        return self._path() / other

    def exists(self):
        return self._path().exists()

    def read_text(self, *args, **kwargs):
        return self._path().read_text(*args, **kwargs)

    def write_text(self, *args, **kwargs):
        return self._path().write_text(*args, **kwargs)

    def write_bytes(self, *args, **kwargs):
        return self._path().write_bytes(*args, **kwargs)

    def glob(self, pattern):
        return self._path().glob(pattern)

    def mkdir(self, *args, **kwargs):
        return self._path().mkdir(*args, **kwargs)

    def unlink(self, *args, **kwargs):
        return self._path().unlink(*args, **kwargs)


def role_file(rel_src: str) -> Path:
    """按当前请求角色解析相对路径文件（上传的视频/音乐等）。"""
    if _role_ctx.get() == "owner":
        return BASE_DIR / rel_src
    return USERS_DATA_DIR / _role_ctx.get() / rel_src
