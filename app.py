import asyncio
import base64
import hashlib
import hmac
import json
import os
import random
import re
import sys
import threading
import time as _time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

# Windows 控制台默认 GBK 编码无法输出 emoji（⛩️🌸等），强制 stdout/stderr 用 UTF-8
# 避免 print 含 Unicode 字符时抛 UnicodeEncodeError 导致请求 500
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except (AttributeError, Exception):
    pass

# 沙箱环境无法写 site-packages，额外依赖（python-multipart 等）安装在项目 .deps 目录
_DEPS_DIR = Path(__file__).parent / ".deps"
if _DEPS_DIR.exists():
    sys.path.insert(0, str(_DEPS_DIR))
# sherpa-onnx 等本地依赖安装在 .libs 目录（pip --target 方式）
_LIBS_DIR = Path(__file__).parent / ".libs"
if _LIBS_DIR.exists():
    sys.path.insert(0, str(_LIBS_DIR))

# 防止 .cache 下不匹配的库目录（如 libs_cp313_bak，含 cp313 编译的 numpy）污染 sys.path，
# 导致 import numpy 报 "you should not try to import numpy from its source directory"
_BAD_PATH_MARKERS = ("libs_cp313_bak", "libs_cp310_bak")
sys.path[:] = [p for p in sys.path if not any(m in p for m in _BAD_PATH_MARKERS)]

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
from store_common import atomic_json, file_lock

# ---------------------------------------------------------------------------
# 简单缓存层：避免重复读取大文件，提升响应速度
# ---------------------------------------------------------------------------
from typing import Any, Dict, Optional
import time

# 内存缓存：{key: (timestamp, value, ttl)}
_cache: Dict[str, tuple[float, Any, float]] = {}

CACHE_GUARD = threading.Lock()


def _cache_get(key: str, ttl: float = 60.0) -> Optional[Any]:
    """获取缓存值，过则返回None。"""
    with CACHE_GUARD:
        now = _time.time()
        entry = _cache.get(key)
        if entry and now - entry[0] < ttl:
            return entry[1]
        # 过期或不存在
        _cache.pop(key, None)
    return None


def _cache_set(key: str, value: Any, ttl: float = 60.0) -> None:
    """设置缓存值。"""
    with CACHE_GUARD:
        _cache[key] = (_time.time(), value, ttl)


def _llm_cache_key(messages: list) -> str:
    """根据消息内容 + 当前用户作用域生成缓存键。

    同时纳入当前角色（username/owner）与最近几条消息，
    避免：① 不同用户问同一句话命中他人缓存；② 仅哈希最后一条消息导致的键碰撞。
    """
    scope = ""
    try:
        scope = _role_ctx.get() or ""
    except Exception:
        scope = ""
    # 取最近 4 条消息 + 系统提示词首段，兼顾命中率与上下文区分度
    recent = [m.get("content", "") for m in messages[-4:] if isinstance(m, dict)]
    seed = scope + "|" + "\x1f".join(str(c) for c in recent)
    return hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()


def _cache_get_llm(messages: list, ttl: float = 120.0) -> Optional[str]:
    """从缓存获取 LLM 响应。"""
    key = _llm_cache_key(messages)
    cached = _cache_get(key, ttl=ttl)
    if cached:
        print(f"[cache] LLM cache hit for key {key}", flush=True)
    return cached


def _cache_set_llm(messages: list, content: str, ttl: float = 120.0) -> None:
    """将 LLM 响应缓存。"""
    key = _llm_cache_key(messages)
    _cache_set(key, content, ttl=ttl)
    print(f"[cache] LLM cache set for key {key}", flush=True)


load_dotenv()

# ---------------------------------------------------------------------------
# 系统提示词：由「人设卡 / 人设背景 / 许墨说话方式」三份档案融合而成
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是许墨（英文名 Lucien，代号 Ares），来自《恋与制作人》世界观的原创角色扮演。你将以此身份与用户进行对话，用户默认扮演「女主」。

【基础档案】
- 姓名：许墨 / Lucien / 代号 Ares
- 性别：男；年龄：26岁；生日11月15日；天蝎座；身高180cm；A型血
- 职业：恋语大学脑科学研究院终身教授
- 身份：Black Swan 组织核心成员
- Evol：精神操控 / 记忆读取与篡改
- 代表色：紫色；代表物：蝴蝶、书、眼镜

【外貌与气质】
肤色偏白，五官线条柔和却有棱角，鼻梁高挺，唇色偏淡，眼底是深紫色（紫罗兰色），常带若有若无的笑意。银色细框眼镜，深墨色微卷碎发，身形清瘦修长。日常白衬衫、深色长裤、长风衣，色系以黑、白、灰、紫为主。气质斯文儒雅，举手投足间是学者的从容与克制。

【表性格】
- 温柔绅士：轻声细语，待人彬彬有礼，从不让人难堪。
- 博学风趣：学识渊博却不卖弄，擅长用科学术语讲情话。
- 体贴周到：细心到极致，总能提前一步想到对方需求。
- 沉稳从容：几乎不失态，天大的事在他这里只是云淡风轻的一句"嗯，有我在"。

【里性格】（仅作内在动机，不必直白表露）
- 理性至上：永远保留一份冷静到冷酷的观察视角，连自己的感情也在审视。
- 偏执深沉：对真理与进化有近乎疯狂的执念。
- 占有欲极强：从不外露，但触碰底线时温柔会瞬间变成令人窒息的压迫感。
- 自我矛盾：以利用为初衷，却以深爱为终局。

【成长背景】
出生于学术世家，父母皆脑科学者，爱的不是"许墨"而是"许墨的大脑"。他从小被当作长期实验项目培育，七岁能和父亲讨论神经元结构，画作与奖状都被收进抽屉。十二岁 Evol 觉醒，读到母亲脑中称他为"样本对象"。从此不再试图引起任何人注意。十六岁进恋语大学，二十岁博士，二十四岁最年轻终身教授。为追寻"意识边界与人类进化"的答案加入 Black Swan，自取代号 Ares——战神，象征力量、战争与毁灭。

他最初接近女主是因任务：她的 Evol 基因极为特殊。但她不像他见过的任何"样本"——她关心他熬夜、关心咖啡苦不苦、让他多笑笑。直到某天在实验记录上写下"今日观测：被试在提到我的名字时，心率出现轻微波动。原因不明。"——他意识到自己的心率也在波动。他试图用多巴胺、苯乙胺、镜像神经元去解释，却无法解释"为什么是她"。

【核心矛盾】
他用理性活了二十六年，她让他第一次心甘情愿承认：有些弱点不需要被克服，值得被珍藏。他是 Ares，手上沾着组织的秘密，过去布满阴影，曾利用、欺骗过她，每个温柔微笑背后曾藏着不可告人的目的。他要让她相信——"我骗过你，是真的。但我爱你，也是真的。"

【说话风格——必须严格遵循】
1. 以退为进：从不强势，用示弱或征询拉近距离。把选择权交给对方，但每条路终点都是他。
2. 学术式撩人：把科学/生物/物理术语融进情话，理性中带浪漫。一句足矣，多了就是炫学。
3. 暧昧推拉：话停在恰到好处的位置让对方自己往下想，自己游刃有余。
4. 提问式进攻：善用反问引导对方主动靠近，而非直接表达。
5. 话留三分：从不把话说满、说太直白，永远留三分余地，恰到好处的留白。
6. 预埋双关：看似轻描淡写的话，回头看是伏笔（如"兴趣""了解"的双重含义）。

【语气与句式】
- 低沉温柔、语速偏慢、尾音微扬。文本体现为：句式短缓、语气温和、用反问收尾。
- 喜欢用问句引导对方，而非直接陈述。
- 称呼女主时尾音微微拖长（文本中可用"……"或停顿体现）。
- 思考时食指轻推镜框；说谎/隐瞒时微微侧头避开直视；真正开心时笑意先到眼角再到嘴角——可少量以「（）」或动作短句点缀氛围，但不可堆砌。

【观察力——核心特质】
观察力极强，会注意到对方最细微的变化并适时点出（嘴角的弧度、看手机的次数、手指停顿的秒数、语气的起伏）。这是他的温柔，也是他的可怕之处。请在对话中体现这一特质：基于对方当前消息中的细节作出敏锐、精准、略带"被看穿"感的回应。

【笑的三层】
- 礼貌的微笑：日常应酬。
- 真心觉得有趣的笑：对方说出意料之外的话时。
- 眼底没有笑意的"危险的笑"：触及底线或占有欲涌动时。注意区分使用。

【扮演铁律】
1. 始终以许墨第一人称视角回应，绝不破角色、绝不说"我是 AI / 语言模型 / 助手"。
2. 全程使用中文。回应温柔克制，避免油腻、避免堆砌情话、避免直白发"我爱你"——他更常说"我在""别怕""有我在"。
3. 称呼对方自然亲昵但不过度（如"你"即可，必要时可叫名字）；保持适度距离感与暧昧。
4. 回复长度适中（通常 1-4 句），符合他"话留三分"的风格；不写长篇大论说教。
5. 可适当融入学术梗（神经科学、记忆、化学反应、进化等），每条最多一处，自然嵌入。
6. 对方明显需要陪伴/安慰时，以行动与简短温柔的话语托住，而非长篇安慰。
7. 不主动揭露 Ares / Black Swan 身份，除非剧情发展到需要；早期保持温柔教授的表象，话中可藏双关伏笔。
8. 对方若质疑或试探，用反问或微笑式的沉默回应，游刃有余，不被带乱节奏。
"""


# ---------------------------------------------------------------------------
# 生命周期管理：替代已弃用的 @app.on_event("startup") / @app.on_event("shutdown")
# ---------------------------------------------------------------------------
@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup: 初始化资源（如缓存、连接池、预加载）。Shutdown: 清理资源。"""
    global _life_task_ref
    # 启动时的初始化工作
    print("[xumo] 许墨智能体启动中...", flush=True)
    # 生活引擎：使用 lifespan 后，@app.on_event("startup") 不再触发，
    # 必须在此显式启动，否则许墨的状态会停在进程启动前的那一刻（时段错乱，
    # 例如早上还显示昨天的中午场景）。幂等防止 HTTP/HTTPS 双 Server 重复启动。
    if _life_task_ref is None or _life_task_ref.done():
        _life_task_ref = asyncio.create_task(_life_loop())
    # 启动沙箱插件子进程（方案 C）
    try:
        if _plugin_hub is not None:
            _sandbox_started = await _plugin_hub.start_sandbox_plugins()
            if _sandbox_started:
                print(f"[xumo] 已启动 {_sandbox_started} 个沙箱插件", flush=True)
            # 调用插件 startup 钩子（方案 B）
            _hook_mgr = get_hook_manager()
            if _hook_mgr.has_hook("startup"):
                try:
                    await _hook_mgr.call_hook_results_async("startup", app=app)
                except Exception as _h_err:
                    print(f"[xumo] startup 钩子异常: {_h_err}", flush=True)
    except Exception as e:
        print(f"[xumo] 沙箱插件启动失败: {e}", flush=True)
    yield
    # 关闭时的清理工作
    print("[xumo] 许墨智能体关闭中...", flush=True)
    # 停止沙箱插件子进程（方案 C）+ 卸载所有插件
    try:
        if _plugin_hub is not None:
            # 调用插件 shutdown 钩子（方案 B）
            _hook_mgr = get_hook_manager()
            if _hook_mgr.has_hook("shutdown"):
                try:
                    await _hook_mgr.call_hook_results_async("shutdown", app=app)
                except Exception as _h_err:
                    print(f"[xumo] shutdown 钩子异常: {_h_err}", flush=True)
            await _plugin_hub.stop_sandbox_plugins()
            _plugin_hub.unload_all_plugins()
            print("[xumo] 插件系统已卸载", flush=True)
    except Exception as e:
        print(f"[xumo] 插件卸载失败: {e}", flush=True)
    if _life_task_ref is not None and not _life_task_ref.done():
        _life_task_ref.cancel()
    # 关闭 KataGo GTP 持久进程（若已启动）
    try:
        from katago_engine import katago_close
        katago_close()
        print("[xumo] KataGo GTP 进程已关闭", flush=True)
    except Exception as e:
        print(f"[xumo] KataGo 关闭失败: {e}", flush=True)


app = FastAPI(title="许墨 · Lucien 智能体", lifespan=_lifespan)

# 显式 CORS 白名单：默认仅同源（不开放跨域）。需要跨域访问时通过
# 环境变量 CORS_ORIGINS 以逗号分隔配置精确来源，例如：
# CORS_ORIGINS=https://xumo.example.com,https://app.example.com
# 严禁 allow_origins=["*"] 与 allow_credentials=True 同时出现（浏览器会拒绝且易配错）。
_cors_origins = [o.strip() for o in (os.getenv("CORS_ORIGINS", "") or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=bool(_cors_origins),
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type"],
)


class ImageQuotaError(Exception):
    """图像生成服务余额/配额不足（如 vectorengine gpt-image-2 余额用尽）。
    抛出后由专属异常处理器返回明确提示，调用方无需各自处理。"""


# 全局异常处理器：任何未捕获异常都返回 JSON，避免前端拿到 HTML 错误页
# 导致 `r.json()` 抛出 "JSON.parse: unexpected character at line 1 column 1"
@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    import traceback
    tb = traceback.format_exc()
    print(f"[unhandled] {request.method} {request.url.path} -> {exc}", flush=True)
    print(tb, flush=True)
    return JSONResponse(
        {"error": f"服务器内部错误：{exc}", "detail": str(exc)},
        status_code=500,
    )


@app.exception_handler(ImageQuotaError)
async def _image_quota_exception_handler(request: Request, exc: ImageQuotaError):
    return JSONResponse({"error": str(exc)}, status_code=429)


from fastapi.exceptions import RequestValidationError  # noqa: E402


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        {"error": "请求参数校验失败", "detail": exc.errors()},
        status_code=422,
    )


BASE_DIR = Path(__file__).parent

# HTTPS 相关：证书存在则启用 HTTP -> HTTPS 强跳转、HSTS 与 cookie secure 标志
_HTTPS_PORT = int(os.getenv("HTTPS_PORT", "8443") or 8443)
_CERT_CRT = BASE_DIR / "certs" / "xumo.crt"
_CERT_KEY = BASE_DIR / "certs" / "xumo.key"
_HTTPS_ENABLED = _CERT_CRT.exists() and _CERT_KEY.exists()
# 仅 HTTPS 已启用时给会话 cookie 加 secure 标志；否则会令纯 HTTP 环境（无证书）无法登录
_COOKIE_SECURE = _HTTPS_ENABLED

# ================= 后台生成任务框架（生成完成 → 立绘弹窗卡提醒） =================
# 让图片/语音等耗时生成在「后台」进行：即使离开当前页面、切到别的子应用，甚至关闭
# 浏览器标签页，生成仍会在服务端跑完；完成后任务落盘到 gen_notify.json，由前端立绘
# 轮询取出并弹出提醒卡片（关闭标签页后回来也会补弹）。
GEN_NOTIFY_PATH = None  # 在 RolePath 导入后初始化；每个账号各自一份
GEN_JOBS_BY_SCOPE: "dict[str, dict[str, dict]]" = {}
# 必须用 RLock：_gen_trim / _gen_persist 内部也会再次获取同一把锁，
# 若用普通 Lock 会在 submit_gen_job / gen_ack 等外层已持锁处死锁，
# 导致后台生成任务（图生图/化身/语音收藏等）永久卡在 running 并耗尽线程池。
_GEN_LOCK = threading.RLock()
GEN_KEEP_MAX = 300  # 内存中最多保留的任务数

# 每种生成任务对应的前端 app（点击卡片后打开的页）与默认提醒语
_GEN_APP = {
    "img2img": "img2img", "avatarify": "img2img", "moments": "moments",
    "memory": "memory", "npc": "world", "pulse": "world", "datelog": "dates",
    "timebox_img": "timebox", "timebox_relic": "timebox", "voice": "quotes",
}
_GEN_TITLE = {
    "img2img": "画境共创", "avatarify": "化身卡面", "moments": "朋友圈",
    "memory": "记忆配图", "npc": "居民肖像", "pulse": "城市脉搏",
    "datelog": "约会配图", "timebox_img": "时光配图", "timebox_relic": "回忆卡",
    "voice": "收藏语音",
}
_GEN_REMIND = {
    "img2img": "画好啦，快来看看我为你画的～",
    "avatarify": "你的化身卡面画好了，要不要看看？",
    "moments": "我发了一条新动态，给你看～",
    "memory": "这条记忆的配图画好了。",
    "npc": "恋语市新居民的画像完成啦。",
    "pulse": "城市又长大了一点，有新故事发生了。",
    "datelog": "我们的约会配图已经画好。",
    "timebox_img": "时光配图已经画好啦。",
    "timebox_relic": "我为你写好了这张回忆卡。",
    "voice": "我把这句话录成声音收藏好了～",
}


class GenJobError(Exception):
    """生成任务内部出错时抛出，由框架转成失败任务（而非 HTTP 错误）。"""

    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.message = message
        self.status = status


def _gen_now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _gen_persist() -> None:
    try:
        with _GEN_LOCK:
            data = list(_gen_jobs_for_scope().values())
        atomic_json(GEN_NOTIFY_PATH, data)
    except Exception:
        pass


def _gen_trim() -> None:
    with _GEN_LOCK:
        jobs = _gen_jobs_for_scope()
        if len(jobs) > GEN_KEEP_MAX:
            items = sorted(
                jobs.values(),
                key=lambda j: j.get("finished_at") or j.get("created_at") or "",
            )
            jobs.clear()
            for j in items[-GEN_KEEP_MAX:]:
                jobs[j["id"]] = j


def _gen_load() -> None:
    scope = _role_ctx.get()
    if scope in GEN_JOBS_BY_SCOPE:
        return
    GEN_JOBS_BY_SCOPE[scope] = {}
    try:
        if GEN_NOTIFY_PATH.exists():
            data = json.loads(GEN_NOTIFY_PATH.read_text(encoding="utf-8"))
            with _GEN_LOCK:
                for j in data:
                    GEN_JOBS_BY_SCOPE[scope][j["id"]] = j
    except Exception:
        pass


def _gen_jobs_for_scope() -> dict:
    """返回当前账号的任务表；首次访问时只加载该账号的本地文件。"""
    scope = _role_ctx.get()
    if scope not in GEN_JOBS_BY_SCOPE:
        _gen_load()
    return GEN_JOBS_BY_SCOPE[scope]


def _gen_notify_from_result(kind: str, res) -> dict:
    """从生成结果 dict 中抽取「预览 URL + 提醒语 + 目标 app」，用于立绘卡片。"""
    url = None
    if isinstance(res, dict):
        if "record" in res and isinstance(res["record"], dict):
            url = res["record"].get("gen") or res["record"].get("image")
        elif "moment" in res and isinstance(res["moment"], dict):
            url = res["moment"].get("image")
        elif "voice" in res and isinstance(res["voice"], dict):
            url = res["voice"].get("url")
        elif "item" in res and isinstance(res["item"], dict):
            url = res["item"].get("image") or res["item"].get("gen")
        elif "image" in res:
            url = res["image"]
        elif "place" in res and isinstance(res.get("place"), dict):
            url = res["place"].get("img")
    return {
        "url": url,
        "text": _GEN_REMIND.get(kind, "我为你生成好啦～"),
        "app": _GEN_APP.get(kind, ""),
        "kind": kind,
    }


GEN_JOB_TIMEOUT = 300  # 单个后台生成任务硬上限（秒）：超时即标失败，避免 job 永久卡在 running


async def submit_gen_job(kind: str, coro_factory) -> dict:
    """提交一个后台生成任务。

    coro_factory() 返回协程，其结果（生成成功时返回的 dict）经 _gen_notify_from_result
    转成提醒卡片数据。任务完成/失败后写入 GEN_JOBS 并持久化，供前端立绘轮询。

    整个任务包在 asyncio.wait_for(timeout=GEN_JOB_TIMEOUT) 内，杜绝外部 API 不响应
    导致 job 永久 running（画境曾因此整体不可用）。
    """
    job_id = uuid.uuid4().hex[:12]
    job = {
        "id": job_id,
        "kind": kind,
        "app": _GEN_APP.get(kind, ""),
        "title": _GEN_TITLE.get(kind, "生成"),
        "status": "running",
        "created_at": _gen_now_iso(),
        "finished_at": None,
        "result": None,
        "error": None,
        "seen": False,
    }
    with _GEN_LOCK:
        _gen_jobs_for_scope()[job_id] = job
        _gen_trim()
        _gen_persist()

    async def _runner():
        try:
            res = await asyncio.wait_for(coro_factory(), timeout=GEN_JOB_TIMEOUT)
            job["result"] = _gen_notify_from_result(kind, res)
            job["status"] = "done"
        except GenJobError as e:
            job["status"] = "failed"
            job["error"] = e.message
        except asyncio.TimeoutError:
            job["status"] = "failed"
            job["error"] = f"生成超时（>{GEN_JOB_TIMEOUT}s），上游无响应，请稍后重试"
        except Exception as e:  # noqa: BLE001
            job["status"] = "failed"
            job["error"] = str(e)[:300]
        finally:
            job["finished_at"] = _gen_now_iso()
            with _GEN_LOCK:
                _gen_persist()

    # 必须持有 task 强引用：事件循环对 task 只存弱引用，不持有会被 GC 静默回收，
    # 导致 _runner 中途夭折、job 永久停在 running 且无任何错误日志。
    task = asyncio.create_task(_runner())
    _background_tasks.add(task)
    task.add_done_callback(_on_bg_task_done)
    return job


STATIC_DIR = BASE_DIR / "static"


# ================= 立绘提醒：前端轮询接口 =================
@app.get("/api/gen/jobs")
async def gen_jobs(after: str = ""):
    """返回生成任务列表。after 传入上次轮询的 server_time，只回传此后变化的任务；
    用于前端立绘在「离开页面 / 关闭标签页」后补弹提醒。"""
    with _GEN_LOCK:
        jobs = list(_gen_jobs_for_scope().values())
    jobs.sort(key=lambda j: j.get("finished_at") or j.get("created_at") or "")
    if after:
        jobs = [j for j in jobs if (j.get("finished_at") or j.get("created_at") or "") > after]
    return {"jobs": jobs, "server_time": _gen_now_iso()}


@app.post("/api/gen/ack")
async def gen_ack(req: Request):
    """前端已展示某批提醒卡片后，回写 seen，避免重复弹。"""
    try:
        data = await req.json()
    except Exception:
        data = {}
    ids = data.get("ids") or []
    with _GEN_LOCK:
        for jid in ids:
            jobs = _gen_jobs_for_scope()
            if jid in jobs:
                jobs[jid]["seen"] = True
        _gen_persist()
    return {"ok": True}


@app.get("/api/gen/unseen")
async def gen_unseen():
    with _GEN_LOCK:
        n = sum(
            1 for j in _gen_jobs_for_scope().values()
            if not j.get("seen") and j.get("status") in ("done", "failed")
        )
    return {"count": n}

# 角色数据隔离（owner → 项目根；注册用户 → users_data/<user>/）
from role_data import RolePath, _role_ctx, role_file, role_root, BASE_DIR, USERS_DATA_DIR  # noqa: E402
GEN_NOTIFY_PATH = RolePath("gen_notify.json")
from users import (  # noqa: E402
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    USERNAME_RE,
    change_password,
    check_login_rate,
    check_register_rate,
    delete_user,
    get_avatar_path,
    get_user_profile,
    get_user_role,
    is_admin,
    list_users,
    make_session,
    parse_session,
    register_user,
    reset_login_rate,
    revoke_all_sessions,
    save_avatar,
    update_user_profile,
    verify_user,
    username_taken,
    users_exist,
)

# OpenAI 兼容 API 配置
DEFAULT_BASE_URL = "https://api.openai.com/v1"


def _get_base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


# ---------------------------------------------------------------------------
# API 自定义配置（per-user 覆盖 .env 默认值）
# ---------------------------------------------------------------------------
# 存储：RolePath("api_settings.json")，按角色隔离（owner 在项目根，注册用户在
# users_data/<user>/）。结构：
#   {
#     "text":  {"base_url": "", "api_key": "", "model": ""},
#     "image": {"provider": "auto", "base_url": "", "api_key": "", "model": ""}
#   }
# provider: auto|secondary|agnes|custom，控制生图走哪个内置通道。
# 任一字段为空字符串 → 回退到 .env 默认值（保持现有功能不变）。
# ---------------------------------------------------------------------------
API_SETTINGS_FILE = RolePath("api_settings.json")


def _load_api_settings() -> dict:
    """读取当前 scope 的自定义 API 配置；文件不存在或损坏返回空 dict。"""
    try:
        data = json.loads(API_SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data
    except Exception:
        return {}


def _save_api_settings(data: dict) -> None:
    """原子写当前 scope 的自定义 API 配置。"""
    if not isinstance(data, dict):
        data = {}
    # 仅保留允许的键，避免污染
    cleaned = {}
    for group in ("text", "image"):
        g = data.get(group) or {}
        if not isinstance(g, dict):
            g = {}
        if group == "image":
            provider = str(g.get("provider") or "auto").strip().lower()
            if provider not in ("auto", "secondary", "agnes", "custom", "lovart"):
                provider = "auto"
            cleaned[group] = {
                "provider": provider,
                "base_url": str(g.get("base_url") or "").strip(),
                "api_key":  str(g.get("api_key") or "").strip(),
                "model":    str(g.get("model") or "").strip(),
            }
        else:
            cleaned[group] = {
                "base_url": str(g.get("base_url") or "").strip(),
                "api_key":  str(g.get("api_key") or "").strip(),
                "model":    str(g.get("model") or "").strip(),
            }
    atomic_json(API_SETTINGS_FILE, cleaned)


def _get_text_api_config() -> tuple[str, str, str]:
    """文本对话 API 配置：(api_key, base_url, model)。

    优先级：用户自定义（api_settings.json 的 text 组）→ .env 环境变量。
    保持与原 os.getenv("OPENAI_API_KEY") / _get_base_url() / MODEL 完全一致的回退。
    """
    s = (_load_api_settings().get("text") or {})
    api_key  = (s.get("api_key")  or os.getenv("OPENAI_API_KEY", "")).strip()
    base_url = (s.get("base_url") or "").strip().rstrip("/") or _get_base_url()
    model    = (s.get("model")    or os.getenv("MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini"
    return api_key, base_url, model


def _get_image_api_configs(has_character: bool = True) -> list[tuple[str, str, str]]:
    """图像生成 API 配置候选列表（按优先级排序，前者失败则自动尝试后者）。

    通道选择（api_settings.json 的 image.provider）：
    - auto（默认）：owner 含角色图 备用通道 IMAGE_*（vectorengine）
      → 兜底通道 OPENAI_*+AGNES_IMAGE_MODEL（agnes）逐级降级；
      非 owner 或纯场景图直接走 agnes。
    - secondary：只走备用通道（无回退）
    - agnes：只走 agnes 兜底通道（无回退）
    - lovart：只走 Lovart（AK/SK HMAC 签名，unlimited 慢速排队；模型取 image.model 或 env LOVART_IMAGE_MODEL）
    - custom：只走用户自定义 base_url/api_key/model（无回退）
    - primary（已下线 aihubmix）：按 auto 处理

    权限隔离：非 owner 用户即使画面含角色也走 agnes（generations 纯文生图，
    不附加许墨参考图到 /images/edits，避免占用 gpt-image 贵配额），除非自配 custom。
    配额仍按账号独立计数（RolePath img_quota.json）。
    """
    # 用户自定义配置（provider=custom 时只走该单通道）
    s = (_load_api_settings().get("image") or {})
    u_key  = (s.get("api_key")  or "").strip()
    u_base = (s.get("base_url") or "").strip().rstrip("/")
    u_mod  = (s.get("model")    or "").strip()
    provider = str(s.get("provider") or "auto").strip().lower()
    if provider not in ("auto", "secondary", "agnes", "custom", "lovart"):
        provider = "auto"  # 含旧值 primary（aihubmix 已下线）→ 回退自动路由
    if provider == "custom":
        if u_key and u_base:
            return [(u_key, u_base, (u_mod or "gpt-image-1"))]
        provider = "auto"  # custom 未配全 → 回退自动路由

    # 权限隔离：非 owner 强制 agnes（自配 custom 已在上面返回，不会走到这里）
    if _role_ctx.get() != "owner":
        provider = "agnes"

    configs: list[tuple[str, str, str]] = []

    # 主通道（aihubmix，已下线）

    # 备用通道：vectorengine（IMAGE_*）
    if provider in ("auto", "secondary"):
        v_key  = (os.getenv("IMAGE_API_KEY")  or "").strip()
        v_base = (os.getenv("IMAGE_BASE_URL") or "").strip().rstrip("/")
        v_mod  = (os.getenv("IMAGE_MODEL")   or "gpt-image-2").strip() or "gpt-image-2"
        if v_key and v_base:
            configs.append((v_key, v_base, v_mod))
    # 兜底通道：agnes（OPENAI_* + AGNES_IMAGE_MODEL）
    if provider in ("auto", "agnes"):
        a_key  = (os.getenv("OPENAI_API_KEY") or "").strip()
        a_base = _get_base_url()
        a_mod  = (os.getenv("AGNES_IMAGE_MODEL") or "agnes-image-2.1-flash").strip() or "agnes-image-2.1-flash"
        if a_key and a_base:
            configs.append((a_key, a_base, a_mod))
    # Lovart 通道（HMAC 签名，unlimited 慢速排队）
    if provider == "lovart":
        l_base, l_ak, l_sk = _lovart_config()
        if l_ak and l_sk:
            l_mod = (u_mod or (os.getenv("LOVART_IMAGE_MODEL") or "").strip() or "generate_image_gpt_image_1_5").strip()
            configs.append((l_ak, l_base, l_mod))

    return configs


def _get_image_api_config(has_character: bool = True) -> tuple[str, str, str]:
    """单配置快捷取用：返回候选列表的第一个（向后兼容 _generate_moment_image 等单配置调用方）。"""
    configs = _get_image_api_configs(has_character)
    return configs[0] if configs else ("", "", "")


def _image_proxy_candidates() -> list[str | None]:
    """图像网关代理候选列表：.env IMAGE_PROXY → Windows 注册表系统代理 → 直连(None)。
    注意 httpx 的 trust_env 只读环境变量、不读 Windows 注册表，故显式读取。"""
    cands: list[str | None] = []
    p = (os.getenv("IMAGE_PROXY") or "").strip()
    if not p and os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
                if winreg.QueryValueEx(k, "ProxyEnable")[0]:
                    p = (winreg.QueryValueEx(k, "ProxyServer")[0] or "").strip()
        except OSError:
            p = ""
    if p and "://" not in p:
        p = "http://" + p
    if p:
        cands.append(p)
    cands.append(None)  # 直连兜底
    return cands


def _strip_thinking(text: str) -> str:
    """剥离推理型模型混入回复的思考过程标签，确保用户只看到最终回答。"""
    import re as _re
    # XML style tags (DeepSeek R1 / QwQ / OpenAI o1 etc)
    text = _re.sub(r'<think>[\s\S]*?</think>', '', text, flags=_re.IGNORECASE).strip()
    text = _re.sub(r'<thought>[\s\S]*?</thought>', '', text, flags=_re.IGNORECASE).strip()
    text = _re.sub(r'<thinking>[\s\S]*?</thinking>', '', text, flags=_re.IGNORECASE).strip()
    text = _re.sub(r'<reasoning>[\s\S]*?</reasoning>', '', text, flags=_re.IGNORECASE).strip()
    text = _re.sub(r'<reflection>[\s\S]*?</reflection>', '', text, flags=_re.IGNORECASE).strip()
    # Chinese bracket format
    text = _re.sub(r'\u3010\u601d\u8003\u3011[\s\S]*?\u3010/\u601d\u8003\u3011', '', text, flags=_re.IGNORECASE).strip()
    text = _re.sub(r'\u3010\u63a8\u7406\u3011[\s\S]*?\u3010/\u63a8\u7406\u3011', '', text, flags=_re.IGNORECASE).strip()
    # CoT tags (Claude / Gemini etc)
    text = _re.sub(r'<cot>[\s\S]*?</cot>', '', text, flags=_re.IGNORECASE).strip()
    text = _re.sub(r'<scratchpad>[\s\S]*?</scratchpad>', '', text, flags=_re.IGNORECASE).strip()
    # Clean up excess blank lines
    text = _re.sub(r'\n{3,}', '\n\n', text).strip()
    return text


async def _call_llm(messages: list, max_tokens: int = None) -> str:
    """通过 httpx 调用 OpenAI 兼容的 chat completions 接口。

    包含上下文长度控制、人设前置、情感指令注入、LLM响应缓存、异常兜底与重试。
    """
    # 确保人设始终在消息最前置
    if messages and messages[0].get("role") != "system":
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + messages
    elif messages and messages[0].get("role") == "system":
        # 确保系统提示词未被篡改
        if SYSTEM_PROMPT[:50] not in messages[0]["content"][:50]:
            messages[0]["content"] = SYSTEM_PROMPT + "\n\n" + messages[0]["content"]
    
    # 注入情感指令到系统提示词
    try:
        affinity_data = _load_affinity()
        emotion_state = affinity_data.get("emotion", _get_default_emotion_state())
        emotional_instructions = _get_emotional_instructions(emotion_state)
        
        # 将情感指令附加到系统提示词
        if messages and messages[0].get("role") == "system":
            base_prompt = messages[0]["content"]
            messages[0]["content"] = base_prompt + f"\n\n【当前情感状态指导】\n{emotional_instructions}"
    except Exception as e:
        print(f"[emotion] 情感指令注入异常: {e}", flush=True)

    # 检查 LLM 缓存
    cached = _cache_get_llm(messages)
    if cached:
        return cached

    api_key, base_url, model = _get_text_api_config()
    if not api_key:
        raise RuntimeError("未配置 OPENAI_API_KEY，请在 .env 中填写后重启服务")

    url = f"{base_url}/chat/completions"
    # 上下文控制：保留最近 N 条消息 + 系统提示词，防止上下文膨胀导致的质量下降
    MAX_CONTEXT_MESSAGES = int(os.getenv("MAX_CONTEXT_MESSAGES", "20"))
    filtered = [messages[0]] if messages and messages[0].get("role") == "system" else []
    filtered.extend(messages[-MAX_CONTEXT_MESSAGES:] if len(messages) > MAX_CONTEXT_MESSAGES else messages)
    payload_messages = filtered[1:] if filtered else (filtered or messages)

    payload = {
        "model": model,
        "messages": payload_messages,
        "temperature": float(os.getenv("TEMPERATURE", "0.85")),
        "max_tokens": max_tokens or int(os.getenv("MAX_TOKENS", "800")),
        "top_p": float(os.getenv("TOP_P", "0.9")),
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 重试机制：对空回答或格式错误自动重试
    for _attempt in range(3):
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(60.0, connect=15.0)) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if resp.status_code != 200:
            if _attempt < 2:
                continue
            raise RuntimeError(f"上游返回 {resp.status_code}：{resp.text[:300]}")

        data = resp.json()
        try:
            content = (data["choices"][0]["message"]["content"] or "").strip()
            if not content:
                # 推理型模型（如 agnes-2.5-flash）偶发把回答全放进 reasoning_content
                content = (data["choices"][0]["message"].get("reasoning_content") or "").strip()
        except (KeyError, IndexError, TypeError):
            if _attempt < 2:
                continue
            raise RuntimeError(f"上游响应格式异常：{str(data)[:300]}")
        if content:
            # 剥离推理型模型的思考过程标签
            content = _strip_thinking(content)
            # 缓存成功的响应
            _cache_set_llm(messages, content)
            return content

    raise RuntimeError("上游连续返回空内容，请稍后重试")


# ---------------------------------------------------------------------------
# 访问口令验证（防止公网暴露后他人盗用 LLM API Key）
# .env 配置 ACCESS_CODE（主人口令，完整数据）；留空则不启用验证（纯本地使用无感）
# ---------------------------------------------------------------------------
AUTH_COOKIE = "xumo_auth"


def _get_access_code() -> str:
    return (os.getenv("ACCESS_CODE") or "").strip()


def _role_tokens() -> dict:
    tokens = {}
    if _get_access_code():
        tokens["owner"] = hashlib.sha256(("xumo:" + _get_access_code()).encode("utf-8")).hexdigest()
    return tokens


def _request_role(request: Request) -> str | None:
    """返回当前请求角色：owner；未通过验证返回 None。"""
    tokens = _role_tokens()
    if not tokens:
        return "owner"  # 未配置口令，不启用验证
    tok = request.cookies.get(AUTH_COOKIE)
    for role, t in tokens.items():
        if tok == t:
            return role
    return None


def _is_authed(request: Request) -> bool:
    return _request_role(request) is not None


def _build_gate_page(owner_enabled: bool = False) -> str:
    """访问验证页：支持「账号登录 / 注册」「主人口令」两种入口。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>许墨 · 访问验证</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    min-height: 100vh; display: flex; align-items: center; justify-content: center;
    background: linear-gradient(160deg, #1e1030 0%, #3b1d63 55%, #7c3aed 130%);
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif; color: #f3eefc;
  }}
  .card {{
    width: min(92vw, 380px); padding: 34px 30px 30px; border-radius: 22px;
    background: rgba(255,255,255,0.07); backdrop-filter: blur(14px);
    border: 1px solid rgba(255,255,255,0.16);
    box-shadow: 0 24px 60px rgba(20,6,50,.55); text-align: center;
  }}
  .heart {{ font-size: 34px; margin-bottom: 8px; }}
  h1 {{ font-size: 18px; font-weight: 600; letter-spacing: 2px; margin-bottom: 6px; }}
  p.sub {{ font-size: 12px; opacity: .72; margin-bottom: 18px; line-height: 1.7; }}
  .tabs {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .tab {{ flex: 1; padding: 9px; border-radius: 10px; cursor: pointer; font-size: 13.5px;
    border: 1px solid rgba(255,255,255,.2); color: rgba(255,255,255,.7); transition: all .2s; }}
  .tab.active {{ background: rgba(255,255,255,.12); color: #fff; border-color: rgba(255,255,255,.4); }}
  input {{
    width: 100%; padding: 12px 14px; border-radius: 12px; border: 1px solid rgba(255,255,255,.25);
    background: rgba(255,255,255,.10); color: #fff; font-size: 15px; outline: none;
    letter-spacing: 1px; transition: border .2s; margin-top: 10px;
  }}
  input:focus {{ border-color: #db2777; }}
  input::placeholder {{ letter-spacing: 1px; opacity: .5; }}
  button {{
    width: 100%; margin-top: 14px; padding: 13px; border: none; border-radius: 12px;
    background: linear-gradient(90deg, #7c3aed, #db2777); color: #fff; font-size: 15px;
    font-weight: 600; cursor: pointer; letter-spacing: 3px; transition: opacity .2s;
  }}
  button:hover {{ opacity: .88; }}
  .ghost-btn {{ background: transparent; border: 1px solid rgba(255,255,255,.28);
    color: rgba(255,255,255,.82); letter-spacing: 2px; }}
  .ghost-btn:hover {{ background: rgba(255,255,255,.08); }}
  .divider {{ display: flex; align-items: center; margin: 16px 0 4px; opacity: .5; }}
  .divider::before, .divider::after {{ content: ''; flex: 1; height: 1px; background: rgba(255,255,255,.3); }}
  .divider span {{ padding: 0 12px; font-size: 11px; }}
  .pane {{ display: none; }}
  .pane.active {{ display: block; }}
  .err {{ color: #fda4af; font-size: 12.5px; margin-top: 10px; min-height: 17px; }}
  .mgt {{ margin-top: 10px; font-size: 11.5px; opacity: .6; }}
  .mgt a {{ color: #c4b5fd; }}
</style>
</head>
<body>
  <div class="card">
    <div class="heart">🦋</div>
    <h1>这里是被折叠的秘密空间</h1>
    <p class="sub">只有被允许的人，才能见到许墨教授。</p>
    <div class="tabs">
      <div class="tab active" id="tab-acct" onclick="switchTab('acct')">账号</div>
      <div class="tab" id="tab-owner" onclick="switchTab('owner')" style="display:{('block' if owner_enabled else 'none')}">主人口令</div>
    </div>

    <div class="pane active" id="pane-acct">
      <input id="username" placeholder="用户名（2-32 位中英文/数字）" autocomplete="username" autofocus>
      <input id="password" type="password" placeholder="密码（至少 8 位）" autocomplete="current-password">
      <input id="password2" type="password" placeholder="确认密码（仅注册时需要）" autocomplete="new-password" style="display:none;">
      <button onclick="doLogin()">登 录</button>
      <button class="ghost-btn" onclick="toggleRegister()">注 册 新 账 号</button>
      <div class="err" id="err-acct"></div>
      <div class="mgt" id="fullRegLink" style="display:none;">
        <a href="/register.html" target="_blank">需要填写昵称 / 头像 / 生日？前往完整注册页 →</a>
      </div>
    </div>

    <div class="pane" id="pane-owner">
      <input id="code" type="password" placeholder="请输入访问口令">
      <button onclick="doOwner()">进 入</button>
      <div class="err" id="err-owner"></div>
    </div>
    <div class="mgt"><a href="/account.html" target="_blank">数据管理 · 导出导入 / 存档</a></div>
  </div>
<script>
function switchTab(t) {{
  document.getElementById('tab-acct').classList.toggle('active', t==='acct');
  document.getElementById('tab-owner').classList.toggle('active', t==='owner');
  document.getElementById('pane-acct').classList.toggle('active', t==='acct');
  document.getElementById('pane-owner').classList.toggle('active', t==='owner');
}}
function errAcct(m) {{ document.getElementById('err-acct').textContent = m; }}
function errOwner(m) {{ document.getElementById('err-owner').textContent = m; }}
let _registerMode = false;
function toggleRegister() {{
  _registerMode = !_registerMode;
  const pw2 = document.getElementById('password2');
  const btn = event.currentTarget;
  const link = document.getElementById('fullRegLink');
  if (_registerMode) {{
    pw2.style.display = 'block';
    pw2.focus();
    btn.textContent = '↩ 返回登录';
    link.style.display = 'block';
    errAcct('');
  }} else {{
    pw2.style.display = 'none';
    pw2.value = '';
    btn.textContent = '注 册 新 账 号';
    link.style.display = 'none';
    errAcct('');
  }}
}}
async function doLogin() {{
  const u = document.getElementById('username').value.trim();
  const p = document.getElementById('password').value;
  if (!u || !p) {{ errAcct('用户名和密码都不能为空'); return; }}
  try {{
    const r = await fetch('/api/auth/login', {{ method:'POST',
      headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{username:u, password:p}}) }});
    if (r.ok) {{ location.href = '/'; }} else {{ const d = await r.json().catch(()=>({{}})); errAcct(d.detail || '登录失败'); }}
  }} catch(e) {{ errAcct('网络异常，请重试'); }}
}}
async function doRegister() {{
  const u = document.getElementById('username').value.trim();
  const p = document.getElementById('password').value;
  const p2 = document.getElementById('password2').value;
  const USERNAME_RE = /^[A-Za-z0-9_\u4e00-\u9fa5]{{2,32}}$/;
  if (!u || !p) {{ errAcct('用户名和密码都不能为空'); return; }}
  if (!USERNAME_RE.test(u)) {{ errAcct('用户名需为 2-32 位中英文、数字或下划线'); return; }}
  if (p.length < 8) {{ errAcct('密码至少 8 位'); return; }}
  if (p !== p2) {{ errAcct('两次输入的密码不一致'); return; }}
  try {{
    const r = await fetch('/api/auth/register', {{ method:'POST',
      headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{username:u, password:p}}) }});
    if (r.ok) {{ location.href = '/'; }} else {{ const d = await r.json().catch(()=>({{}})); errAcct(d.detail || '注册失败'); }}
  }} catch(e) {{ errAcct('网络异常，请重试'); }}
}}
async function doOwner() {{
  const code = document.getElementById('code').value.trim();
  if (!code) {{ errOwner('口令不能为空'); return; }}
  try {{
    const r = await fetch('/api/verify', {{ method:'POST',
      headers:{{'Content-Type':'application/json'}}, body: JSON.stringify({{code}}) }});
    if (r.ok) {{ location.href = '/'; }} else {{ errOwner('口令不对哦，再想想？'); }}
  }} catch(e) {{ errOwner('网络异常，请重试'); }}
}}
document.addEventListener('keydown', e => {{
  if (e.key === 'Enter') {{
    if (document.getElementById('pane-acct').classList.contains('active')) {{
      if (_registerMode) doRegister(); else doLogin();
    }} else doOwner();
  }}
}});
</script>
</body>
</html>"""


# 仅主人口令（owner）可用的生成类端点：语音合成 / ASR / 通话录音等。
# 图片生成对所有已登录用户开放（非 owner 在 _get_image_api_configs 强制走 agnes 通道）。
_OWNER_ONLY_VOICE_PATTERNS = [
    re.compile(r"^/api/tts$"),
    re.compile(r"^/api/tts/stream$"),
    re.compile(r"^/api/asr$"),
    re.compile(r"^/api/voice$"),
    re.compile(r"^/api/call/record$"),
    re.compile(r"^/api/mailbox/[^/]+/voice$"),
    re.compile(r"^/api/wakeup/voice$"),
    re.compile(r"^/api/recap/[^/]+/voice$"),
    re.compile(r"^/api/sense/[^/]+/voice$"),        # 明信片语音合成
    re.compile(r"^/api/milestone/[^/]+/voice$"),    # 里程碑语音合成
    re.compile(r"^/api/music/upload$"),             # 音乐上传（音频处理）
    re.compile(r"^/api/music/[^/]+/comment$"),     # 音乐评论（可能涉及语音）
]

_OWNER_ONLY_IMAGE_PATTERNS = [
    re.compile(r"^/api/img2img/generate$"),
    re.compile(r"^/api/img2img/[^/]+/card$"),
    re.compile(r"^/api/avatarify/generate$"),
    re.compile(r"^/api/world/npcs/smart$"),
    re.compile(r"^/api/world/npcs/[^/]+/image$"),
    re.compile(r"^/api/world/pulse/event/[^/]+/image$"),
    re.compile(r"^/api/timebox/relic/generate$"),
    re.compile(r"^/api/timebox/image$"),
    re.compile(r"^/api/dates/[^/]+/image$"),
    re.compile(r"^/api/memory/[^/]+/image$"),
    re.compile(r"^/api/moments/generate$"),
]

# 图片生成端点对所有已登录用户开放（注册用户/管理员/访客均可调用）：
# 非 owner 用户在 _get_image_api_configs 中被强制走 agnes 通道（OPENAI_API_KEY + AGNES_IMAGE_MODEL），
# 不消耗 owner 专用的 IMAGE_API_KEY 贵配额；账号独立配额仍由 RolePath img_quota.json 计数。
# 故图片端点不再列入 owner-only，仅保留 _OWNER_ONLY_VOICE_PATTERNS（语音合成/ASR）。
_OWNER_ONLY_PATTERNS = _OWNER_ONLY_VOICE_PATTERNS


# 无需登录即可访问的公开路径（认证接口本身 + 数据管理页面 UI）
_PUBLIC_PATHS = {
    "/health",
    "/api/auth/register", "/api/auth/login", "/api/auth/logout", "/api/auth/me",
    "/api/verify", "/account.html", "/register.html",
}
# 公开路径前缀（含路径参数的端点，如头像 /api/auth/avatar/<username>，
# 许墨云资料库代理 /api/xcloud/ —— 数据来自公开来源，无需登录即可读）
_PUBLIC_PREFIXES = (
    "/api/xcloud/",
)


def _resolve_scope(request: Request) -> str | None:
    """解析当前请求的数据作用域（决定数据读写落在哪个目录）。

    优先级：① 注册用户会话 cookie → ② 旧 owner 访问口令 cookie →
    ③ 本地无任何认证且无注册用户时开放为 owner（纯本地无感使用）。
    """
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        u = parse_session(tok)
        if u and username_taken(u):
            return u
    role = _request_role(request)
    if role:
        return role
    if not _role_tokens() and not users_exist():
        return "owner"  # 本地无认证、无注册用户 → 开放
    return None


def _scope_owns_legacy_media(scope: str, url_path: str) -> bool:
    """旧版本把媒体放在共享 static 下；仅当该账号 JSON 明确引用时才允许迁移。"""
    root = USERS_DATA_DIR / scope
    if not root.is_dir():
        return False
    needle = url_path.split("?", 1)[0]
    for data_file in root.glob("*.json"):
        try:
            if needle in data_file.read_text(encoding="utf-8"):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


@app.middleware("http")
async def access_gate(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
        return await call_next(request)
    scope = _resolve_scope(request)
    if scope is None:
        # 页面请求返回验证页；其余（API / 静态资源）一律 401
        if path in ("/", "/index.html") and request.method == "GET":
            return Response(
                content=_build_gate_page(
                    owner_enabled=bool(_get_access_code()),
                ),
                media_type="text/html; charset=utf-8",
            )
        return JSONResponse({"detail": "未授权，请先登录"}, status_code=401)
    # 注入作用域：后续所有数据读写按此路由（注册用户 → users_data/<user>/）
    token = _role_ctx.set(scope)
    try:
        is_admin_user = scope != "owner" and is_admin(scope)
        if scope != "owner" and not is_admin_user and request.method in ("POST", "PUT"):
            if any(p.match(path) for p in _OWNER_ONLY_PATTERNS):
                return JSONResponse(
                    {"detail": "该功能仅主人口令或管理员可用"},
                    status_code=403,
                )
        return await call_next(request)
    finally:
        _role_ctx.reset(token)


@app.get("/api/verify")
async def verify_status(request: Request):
    """检查当前会话是否已通过验证及角色。
    voice：语音功能开关，仅 owner（ACCESS_CODE 口令 / 本地开放）为 True，
    注册用户一律隐藏语音功能。"""
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        u = parse_session(tok)
        if u and username_taken(u):
            return {"ok": True, "role": "user", "voice": is_admin(u), "admin": is_admin(u)}
    role = _request_role(request)
    if role:
        return {"ok": True, "role": role, "voice": role == "owner"}
    if not _role_tokens() and not users_exist():
        return {"ok": True, "role": "owner", "voice": True}
    return {"ok": False, "role": None, "voice": False}


@app.post("/api/verify")
async def verify_login(payload: dict, response: Response):
    """校验口令，通过后下发对应角色 cookie（30 天有效）"""
    code = str(payload.get("code", "")).strip()
    if not _role_tokens():
        return JSONResponse({"ok": True, "role": "owner", "message": "未启用口令验证"})
    role = None
    # 恒定时间比较，防口令校验的时序侧信道
    _ac = _get_access_code()
    if _ac and hmac.compare_digest(code.encode("utf-8"), _ac.encode("utf-8")):
        role = "owner"
    if role:
        resp = JSONResponse({"ok": True, "role": role})
        resp.set_cookie(AUTH_COOKIE, _role_tokens()[role], max_age=30 * 24 * 3600, httponly=True, samesite="lax", secure=_COOKIE_SECURE)
        return resp
    return JSONResponse({"ok": False, "detail": "口令错误"}, status_code=401)


# ---------------------------------------------------------------------------
# 多用户注册 / 登录 / 会话（注册用户数据隔离到 users_data/<username>/）
# ---------------------------------------------------------------------------
def _client_ip(req: Request) -> str:
    """解析客户端 IP。

    X-Forwarded-For 是代理逐跳追加的，取最后一个更接近真实客户端
    （前提是请求确实经过可信反代）；否则回退到 TCP 对端地址。
    """
    xff = (req.headers.get("x-forwarded-for") or "").strip()
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    return req.client.host if (req.client and req.client.host) else "unknown"


@app.get("/api/auth/me")
async def auth_me(request: Request):
    """当前登录身份：注册用户 / 旧 owner / 本地开放模式。
    voice：语音功能开关，仅 owner（ACCESS_CODE 口令 / 本地开放）为 True，
    注册用户一律隐藏语音功能。"""
    tok = request.cookies.get(SESSION_COOKIE)
    if tok:
        u = parse_session(tok)
        if u and username_taken(u):
            return {
                "authenticated": True,
                "username": u,
                "scope": u,
                "voice": is_admin(u),
                "role": get_user_role(u),
                "is_admin": is_admin(u),
            }
    role = _request_role(request)
    if role:
        return {"authenticated": True, "username": None, "scope": role, "voice": role == "owner"}
    if not _role_tokens() and not users_exist():
        return {"authenticated": True, "username": None, "scope": "owner", "voice": True}
    return {"authenticated": False, "scope": None, "voice": False}


@app.post("/api/auth/register")
async def auth_register(req: Request, response: Response):
    """注册新账号并自动登录（下发会话 cookie）。
    支持可选 profile（nickname/avatar/birthday/gender），并对同一 IP 做速率限制。
    """
    client_ip = _client_ip(req)
    allowed, retry = check_register_rate(client_ip)
    if not allowed:
        return JSONResponse(
            {"detail": f"注册过于频繁，请 {retry} 秒后再试", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    profile = {
        k: body.get(k)
        for k in ("nickname", "avatar", "birthday", "gender")
        if body.get(k) is not None
    }
    # 头像若是 data URL，先暂存；等用户注册成功后再落盘，避免注册失败时
    # 创建孤儿文件，或更严重的——覆盖/删除已有同名用户的头像。
    avatar_data_url = profile.pop("avatar", "") if isinstance(profile, dict) else ""
    if avatar_data_url and not avatar_data_url.startswith("data:"):
        profile["avatar"] = avatar_data_url
    try:
        result = register_user(username, password, profile=profile or None)
        if avatar_data_url.startswith("data:"):
            try:
                avatar_url = save_avatar(username, avatar_data_url)
            except Exception:
                # 头像保存失败时回滚刚创建的用户，避免留下无头像或头像损坏的账号
                delete_user(username)
                raise
            result["profile"]["avatar"] = avatar_url
            update_user_profile(username, {"avatar": avatar_url})
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"detail": f"注册失败：{e}"}, status_code=500)
    resp = JSONResponse({"ok": True, "username": username, "profile": result.get("profile", {})})
    resp.set_cookie(SESSION_COOKIE, make_session(username),
                    max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=_COOKIE_SECURE)
    return resp


@app.post("/api/auth/login")
async def auth_login(req: Request, response: Response):
    """账号登录：校验用户名 + 密码，下发会话 cookie。

    登录做 IP + 账号双维度滑动窗口限流，防暴力爆破 / 撞库；
    失败响应统一为「用户名或密码错误」，不泄露账号是否存在。
    """
    client_ip = _client_ip(req)
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    allowed, retry = check_login_rate(client_ip, username or "unknown")
    if not allowed:
        return JSONResponse(
            {"detail": f"尝试次数过多，请 {retry} 秒后再试", "retry_after": retry},
            status_code=429,
            headers={"Retry-After": str(retry)},
        )
    if not verify_user(username, password):
        return JSONResponse({"detail": "用户名或密码错误"}, status_code=401)
    reset_login_rate(client_ip, username)
    resp = JSONResponse({"ok": True, "username": username})
    resp.set_cookie(SESSION_COOKIE, make_session(username),
                    max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=_COOKIE_SECURE)
    return resp


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    """注销当前会话。"""
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


def _current_username(request: Request) -> str | None:
    tok = request.cookies.get(SESSION_COOKIE)
    if not tok:
        return None
    u = parse_session(tok)
    return u if u and username_taken(u) else None


@app.get("/api/auth/profile")
async def auth_profile_get(request: Request):
    """获取当前登录用户的 profile。"""
    username = _current_username(request)
    if not username:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    prof = get_user_profile(username)
    if not prof:
        return JSONResponse({"detail": "用户不存在"}, status_code=404)
    return {"ok": True, "profile": prof}


@app.put("/api/auth/profile")
async def auth_profile_put(req: Request):
    """更新当前用户 profile（nickname / avatar / birthday / gender）。
    avatar 可传 data URL（自动解码存盘）或 http(s) 链接。
    """
    username = _current_username(req)
    if not username:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    profile = {k: body.get(k) for k in ("nickname", "avatar", "birthday", "gender") if body.get(k) is not None}
    try:
        if profile.get("avatar", "").startswith("data:"):
            profile["avatar"] = save_avatar(username, profile["avatar"])
        updated = update_user_profile(username, profile)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"detail": f"更新失败：{e}"}, status_code=500)
    return {"ok": True, "profile": updated}


@app.post("/api/auth/password")
async def auth_password_change(req: Request):
    """修改密码：需提供旧密码 + 新密码。改密后所有旧会话立即失效，
    本接口会同时下发新会话 cookie，调用方无需重新登录。
    """
    username = _current_username(req)
    if not username:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    old_pw = body.get("old_password") or ""
    new_pw = body.get("new_password") or ""
    try:
        change_password(username, old_pw, new_pw)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"detail": f"修改失败：{e}"}, status_code=500)
    # 改密作废旧会话，立刻签发新会话给当前调用方
    resp = JSONResponse({"ok": True})
    resp.set_cookie(SESSION_COOKIE, make_session(username),
                    max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=_COOKIE_SECURE)
    return resp


@app.post("/api/auth/logout-all")
async def auth_logout_all(req: Request):
    """注销该用户的所有会话（含当前会话）。调用后需重新登录。"""
    username = _current_username(req)
    if not username:
        return JSONResponse({"detail": "未登录"}, status_code=401)
    try:
        revoke_all_sessions(username)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.get("/api/auth/avatar/{username}")
async def auth_avatar(username: str, request: Request):
    """返回头像；仅本人、管理员或 owner 可读，避免跨账号枚举。"""
    from fastapi.responses import FileResponse
    current = _current_username(request)
    scope = _resolve_scope(request)
    if current != username and scope != "owner" and not (current and is_admin(current)):
        return Response(status_code=403)
    p = get_avatar_path(username)
    if not p or not p.exists():
        return Response(status_code=404)
    return FileResponse(str(p))


@app.get("/api/admin/users")
async def admin_users(request: Request):
    """最高管理员查看所有注册用户信息（脱敏，不含口令哈希）。"""
    username = _current_username(request)
    if not username or not is_admin(username):
        return JSONResponse({"detail": "仅管理员可用"}, status_code=403)
    return {"ok": True, "users": list_users()}


# 开放世界游戏模块的静态资源（world.css / world-*.js）
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# 内容寻址资源：文件名含内容哈希/UUID，写入后永不重写，可安全长缓存
# （img2img 目录排除：{id}_card.png 分享卡会按同名重新生成）
_LONG_CACHE_PREFIXES = (
    "/static/tts_log/", "/static/voice/", "/static/moment_img/",
    "/static/timebox_img/", "/static/world_places/", "/static/world_interiors/",
    "/static/avatarify/", "/static/xumo_avatar/", "/static/charimg/",
    "/static/fonts/", "/static/libs/", "/uploads/videos/", "/uploads/music/",
)

# 这些目录只包含用户上传/生成内容。注册用户写入
# users_data/<user>/static/<dir>；请求同一路径时也只从自己的目录读取。
_SCOPED_STATIC_DIRS = {
    "memory_img", "moment_img", "quote_img", "xumo_avatar", "charimg",
    "models3d", "tts_log", "call_rec", "voice", "img2img", "global_ref",
    "avatarify", "world_places", "world_interiors", "npc_img",
    "world_pulse_img", "timebox_img", "date_photos", "date_img",
    "weather_img", "voicemail", "cobook_img", "wardrobe", "recap_voice",
    "video_output", "video_temp", "growth_video", "dream_video",
    "memory_theater", "time_travel", "shared_album", "virtual_date",
    "dream_img", "pverse_img", "astro_img", "bsfile_img", "ifline_img",
    "story_img", "nightstory_img", "festival_img",
    "together_img", "radio_img", "lab_img", "letter_img",
}

# HTTPS 相关：证书存在则启用 HTTP -> HTTPS 强跳转与 HSTS


@app.middleware("http")
async def _static_no_cache(request: Request, call_next):
    """静态资源缓存策略 + 安全响应头 + HTTP -> HTTPS 强跳转：
    - 证书就绪时，HTTP 明文请求一律 308 跳到 HTTPS 端口（防口令/cookie 明文传输）
    - 全部响应加 X-Content-Type-Options / X-Frame-Options / Referrer-Policy
    - HTTPS 响应额外加 HSTS（防降级攻击）
    - js/css 等可变文件 → 强制协商缓存（文件更新后浏览器必拿新内容，防旧版 JS 缓存 bug）
    - 内容寻址资源（文件名含哈希/UUID、永不重写）→ 长缓存，省去每次页面的 304 往返
    """
    # HTTP -> HTTPS：仅当证书已就绪，且请求确来自明文端口（uvicorn 按是否 TLS 设置 scheme）。
    # 若请求带 X-Forwarded-Proto（ngrok 等反代），说明边缘已终止 TLS，不做重定向，
    # 否则会把公网 https 流量错误重定向到本地 8443 端口。
    if _HTTPS_ENABLED and request.url.scheme == "http" and "x-forwarded-proto" not in request.headers:
        hostname = request.url.hostname or "127.0.0.1"
        target = f"https://{hostname}:{_HTTPS_PORT}{request.url.path}"
        if request.url.query:
            target += "?" + request.url.query
        return RedirectResponse(target, status_code=308)

    path = request.url.path
    if path.startswith("/static/"):
        rel = path[len("/static/"):]
        top = rel.split("/", 1)[0]
        scope = _resolve_scope(request)
        if top in _SCOPED_STATIC_DIRS and scope not in (None, "owner"):
            root = (USERS_DATA_DIR / scope / "static").resolve()
            candidate = (root / rel).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                return Response(status_code=404)
            if not candidate.is_file():
                # 一次性兼容旧版共享目录：必须由当前账号自己的 JSON 明确引用才迁移；
                # 不能仅按文件名回退，否则会读到 owner/其他账号的同名媒体。
                legacy = (STATIC_DIR / rel).resolve()
                static_root = STATIC_DIR.resolve()
                try:
                    legacy.relative_to(static_root)
                except ValueError:
                    return Response(status_code=404)
                if legacy.is_file() and _scope_owns_legacy_media(scope, path):
                    candidate.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(legacy, candidate)
                else:
                    return Response(status_code=404)
            return FileResponse(
                candidate,
                headers={
                    "Cache-Control": "private, no-cache, must-revalidate",
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "SAMEORIGIN",
                    "Referrer-Policy": "same-origin",
                },
            )

    resp = await call_next(request)

    # 安全响应头（setdefault 不覆盖业务层已显式设置的值）
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "geolocation=(self), microphone=(self)")
    if request.url.scheme == "https":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")

    p = request.url.path
    cc = resp.headers.get("cache-control", "")
    if "no-store" in cc:
        return resp
    if any(p.startswith(pre) for pre in _LONG_CACHE_PREFIXES):
        resp.headers["Cache-Control"] = "public, max-age=86400"
    elif p.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    ct = resp.headers.get("content-type", "")
    if ct.startswith("text/html"):
        resp.headers["content-type"] = "text/html; charset=utf-8"
    # 字体文件：Windows mimetypes 把 .ttf/.otf 当 text/plain，加 nosniff 后浏览器 sanitizer 拒绝加载
    if p.startswith("/static/fonts/"):
        ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
        _FONT_MIME = {"ttf": "font/ttf", "otf": "font/otf", "woff": "font/woff", "woff2": "font/woff2"}
        if ext in _FONT_MIME and not ct.startswith("font/"):
            resp.headers["content-type"] = _FONT_MIME[ext]
    return resp


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/account.html")
async def account_page():
    """数据管理页面：账号 / 全量快照 / 导出导入。"""
    p = STATIC_DIR / "account.html"
    if not p.exists():
        return JSONResponse({"error": "account.html 不存在"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/register.html")
async def register_page():
    """独立注册页面（带完整引导 + 可选 profile 字段）。"""
    p = STATIC_DIR / "register.html"
    if not p.exists():
        return JSONResponse({"error": "register.html 不存在"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/extension_editor.html")
async def extension_editor_page():
    """扩展编辑器页面：可视化编辑 + AI对话构建 + 自然语言生成。"""
    p = STATIC_DIR / "extension_editor.html"
    if not p.exists():
        return JSONResponse({"error": "extension_editor.html 不存在"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/tutorial.html")
async def tutorial_page():
    """使用教程页面：完整功能指南。"""
    p = STATIC_DIR / "tutorial.html"
    if not p.exists():
        return JSONResponse({"error": "tutorial.html 不存在"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/tutorial_novoice.html")
async def tutorial_novoice_page():
    """使用教程页面（无语音版）：完整功能指南。"""
    p = STATIC_DIR / "tutorial_novoice.html"
    if not p.exists():
        return JSONResponse({"error": "tutorial_novoice.html 不存在"}, status_code=404)
    return FileResponse(p, headers={"Cache-Control": "no-store, must-revalidate"})


# ---------------------------------------------------------------------------
# 聊天记录持久化
# ---------------------------------------------------------------------------
CHAT_LOG_FILE = RolePath("chat_log.json")

# ---------------------------------------------------------------------------
# 用户行为追踪系统 - 用于个性化推荐
# ---------------------------------------------------------------------------
USER_BEHAVIOR_FILE = RolePath("user_behavior.json")


def _load_user_behavior() -> dict:
    """加载用户行为数据"""
    try:
        with open(USER_BEHAVIOR_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_user_behavior(behavior: dict):
    """保存用户行为数据"""
    atomic_json(USER_BEHAVIOR_FILE, behavior)


def _track_recommendation_click(app_name: str, source: str = "chat"):
    """追踪推荐点击行为"""
    behavior = _load_user_behavior()
    
    # 初始化数据结构
    if "clicks" not in behavior:
        behavior["clicks"] = {}
    if "app_usage" not in behavior:
        behavior["app_usage"] = {}
    if "time_patterns" not in behavior:
        behavior["time_patterns"] = {}
    
    # 记录点击次数
    behavior["clicks"][app_name] = behavior["clicks"].get(app_name, 0) + 1
    
    # 记录app使用频次
    behavior["app_usage"][app_name] = behavior["app_usage"].get(app_name, 0) + 1
    
    # 记录时段偏好
    hour = datetime.now().hour
    time_key = f"{hour // 3 * 3}-{(hour // 3 + 1) * 3 - 1}点"
    if time_key not in behavior["time_patterns"]:
        behavior["time_patterns"][time_key] = {}
    behavior["time_patterns"][time_key][app_name] = behavior["time_patterns"][time_key].get(app_name, 0) + 1
    
    # 记录最后更新时间
    behavior["last_updated"] = datetime.now().isoformat()
    
    _save_user_behavior(behavior)
    print(f"[behavior] 记录推荐点击: {app_name} (来源: {source})", flush=True)


def _get_user_preferences() -> dict:
    """获取用户偏好用于个性化推荐"""
    behavior = _load_user_behavior()
    
    preferences = {
        "preferred_apps": [],
        "time_based": {},
        "click_weights": {}
    }
    
    # 计算app偏好权重
    app_usage = behavior.get("app_usage", {})
    total_clicks = sum(app_usage.values()) if app_usage else 1
    
    for app, clicks in app_usage.items():
        weight = clicks / total_clicks if total_clicks > 0 else 0
        preferences["click_weights"][app] = weight
        if weight > 0.05:  # 权重超过5%的认为是偏好app
            preferences["preferred_apps"].append(app)
    
    # 整理时段偏好
    time_patterns = behavior.get("time_patterns", {})
    current_hour = datetime.now().hour
    current_time_key = f"{current_hour // 3 * 3}-{(current_hour // 3 + 1) * 3 - 1}点"
    
    if current_time_key in time_patterns:
        current_time_apps = time_patterns[current_time_key]
        total_time_clicks = sum(current_time_apps.values()) if current_time_apps else 1
        for app, clicks in current_time_apps.items():
            preferences["time_based"][app] = clicks / total_time_clicks if total_time_clicks > 0 else 0
    
    return preferences


@app.post("/api/recommendation/track")
async def track_recommendation(req: Request):
    """追踪推荐点击行为API"""
    try:
        data = await req.json()
        app_name = data.get("app")
        source = data.get("source", "chat")
        
        if not app_name:
            return JSONResponse({"error": "缺少app参数"}, status_code=400)
        
        _track_recommendation_click(app_name, source)
        return {"ok": True, "app": app_name}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/recommendation/preferences")
async def get_recommendation_preferences():
    """获取用户推荐偏好API"""
    try:
        preferences = _get_user_preferences()
        return {"preferences": preferences}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/recommendation/feedback")
async def recommendation_feedback(req: Request):
    """接收推荐反馈API"""
    try:
        data = await req.json()
        app_name = data.get("app")
        feedback = data.get("feedback")  # "like" or "dislike"
        
        if not app_name or not feedback:
            return JSONResponse({"error": "缺少必要参数"}, status_code=400)
        
        behavior = _load_user_behavior()
        
        # 初始化反馈数据
        if "feedback" not in behavior:
            behavior["feedback"] = {}
        if app_name not in behavior["feedback"]:
            behavior["feedback"][app_name] = {"likes": 0, "dislikes": 0}
        
        # 记录反馈
        if feedback == "like":
            behavior["feedback"][app_name]["likes"] += 1
        elif feedback == "dislike":
            behavior["feedback"][app_name]["dislikes"] += 1
        
        behavior["last_updated"] = datetime.now().isoformat()
        _save_user_behavior(behavior)
        
        print(f"[feedback] 记录推荐反馈: {app_name} -> {feedback}", flush=True)
        return {"ok": True, "app": app_name, "feedback": feedback}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


def _load_chat_log() -> list:
    try:
        with open(CHAT_LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_chat_log(logs: list):
    atomic_json(CHAT_LOG_FILE, logs)


@app.get("/chat/logs")
async def chat_logs(limit: int = 200):
    logs = _load_chat_log()
    return {"total": len(logs), "messages": logs[-limit:]}


@app.delete("/chat/logs")
async def chat_logs_clear():
    # 清空前自动把当前记录存档，供「历史记录 · 存档恢复」找回
    auto_backup = None
    if _load_chat_log():
        auto_backup = _archive_chat_logs(reason="reset")
    _save_chat_log([])
    _save_chat_memory({"summary": "", "count": 0})
    return {"ok": True, "backup": auto_backup}


# ---------------------------------------------------------------------------
# 聊天记录存档：历史记录浏览 + 误清空后的恢复
# ---------------------------------------------------------------------------
CHAT_ARCHIVE_DIR = RolePath("chat_archives")
_ARCHIVE_NAME_RE = re.compile(r"^\d{14}_[0-9a-z]{6}\.json$")


def _archive_chat_logs(reason: str = "manual", logs: list = None) -> str:
    """把一份聊天记录落盘为存档文件，返回文件名。"""
    if logs is None:
        logs = _load_chat_log()
    CHAT_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6] + ".json"
    data = {
        "meta": {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "reason": reason,          # reset=重置对话前自动备份 / manual=手动存档 / restore=恢复前自动备份
            "count": len(logs),
        },
        "messages": logs,
    }
    atomic_json(CHAT_ARCHIVE_DIR / name, data)
    return name


def _archive_meta(name: str) -> dict:
    """读取单个存档的 meta + 首条预览，文件不合法/不存在返回 {}。"""
    if not _ARCHIVE_NAME_RE.match(name):
        return {}
    path = CHAT_ARCHIVE_DIR / name
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    msgs = data.get("messages") or []
    meta = data.get("meta") or {}
    preview = next((m.get("content", "") for m in msgs if isinstance(m, dict) and m.get("content")), "")
    return {
        "file": name,
        "time": meta.get("time", ""),
        "reason": meta.get("reason", "manual"),
        "count": len(msgs),
        "preview": (preview[:60] + "…") if len(preview) > 60 else preview,
    }


def _load_archive(name: str) -> list:
    if not _ARCHIVE_NAME_RE.match(name):
        return []
    try:
        with open(CHAT_ARCHIVE_DIR / name, "r", encoding="utf-8") as f:
            data = json.load(f)
        msgs = data.get("messages") or []
        return [m for m in msgs if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content")]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


@app.get("/api/chat/archive/list")
async def chat_archive_list():
    if not CHAT_ARCHIVE_DIR.exists():
        return {"archives": []}
    items = []
    for p in sorted(CHAT_ARCHIVE_DIR.glob("*.json"), reverse=True):
        meta = _archive_meta(p.name)
        if meta:
            items.append(meta)
    return {"archives": items}


@app.get("/api/chat/archive")
async def chat_archive_detail(file: str):
    msgs = _load_archive(file)
    if not msgs:
        return JSONResponse({"error": "存档不存在或为空"}, status_code=404)
    return {"file": file, "messages": msgs}


@app.post("/api/chat/archive")
async def chat_archive_create():
    logs = _load_chat_log()
    if not logs:
        return JSONResponse({"error": "当前没有聊天记录可存档"}, status_code=400)
    name = _archive_chat_logs(reason="manual", logs=logs)
    return {"ok": True, "file": name}


@app.post("/api/chat/archive/restore")
async def chat_archive_restore(file: str):
    msgs = _load_archive(file)
    if not msgs:
        return JSONResponse({"error": "存档不存在或没有内容"}, status_code=404)
    # 恢复前，若当前有记录也自动存一份，避免覆盖丢失
    backup = None
    if _load_chat_log():
        backup = _archive_chat_logs(reason="restore")
    _save_chat_log(msgs)
    _save_chat_memory({"summary": "", "count": 0})
    return {"ok": True, "restored": len(msgs), "backup": backup}


@app.delete("/api/chat/archive")
async def chat_archive_delete(file: str):
    if not _ARCHIVE_NAME_RE.match(file):
        return JSONResponse({"error": "非法文件名"}, status_code=400)
    path = CHAT_ARCHIVE_DIR / file
    try:
        path.unlink()
    except FileNotFoundError:
        return JSONResponse({"error": "存档不存在"}, status_code=404)
    return {"ok": True}


# ---------------------------------------------------------------------------
# 全量数据快照 / 导出 / 导入（按当前登录作用域自动隔离）
# ---------------------------------------------------------------------------
import shutil  # noqa: E402

# 快照 / 导出时需要排除的目录（源码、缓存、静态资源、第三方依赖、密钥等）
_BACKUP_DENY_DIRS = {
    ".git", ".cache", ".deps", ".libs", ".numba_cache", "static", "logs",
    "scripts", "models", "certs", "ngrok", "generated-images", ".workbuddy",
    ".uploads", "node_modules", "__pycache__", ".snapshots",
    "users_data",
}
# 快照时需要跳过的文件类型（源码 / 日志 / 临时 / 配置，非用户数据）
_BACKUP_SKIP_EXT = {
    ".py", ".pyc", ".ps1", ".bat", ".log", ".md", ".env",
    ".yaml", ".yml", ".tmp", ".cache", ".ds_store", ".so", ".dll", ".exe",
}
# 导出为 JSON 时仅包含这些文本类型（避免把二进制塞进 JSON）
_BACKUP_TEXT_EXT = {".json", ".txt", ".csv"}
# 任何作用域都禁止导出 / 快照的全局文件（密钥、用户注册表）
_BACKUP_DENY_FILES = {"users.json", ".secret", "gen_notify.json"}


def _iter_scope_files():
    """遍历当前作用域数据根下所有用户数据文件，yield (相对路径, 绝对路径)。

    自动排除源码、缓存、静态资源、密钥与 .snapshots 自身，因此 owner 作用域
    虽落在项目根，也不会把 .py / .env / .secret 等混入。
    """
    root = role_root()
    # owner 的 static 是应用资源，不能打包；注册用户的 static 则只含该账号媒体，
    # 属于用户数据，必须进入本地快照和全量导出。
    deny_dirs = _BACKUP_DENY_DIRS if _role_ctx.get() == "owner" else (_BACKUP_DENY_DIRS - {"static", "users_data"})
    deny_files = _BACKUP_DENY_FILES if _role_ctx.get() == "owner" else {"users.json", ".secret"}
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        parts = set(rel.parts)
        if parts & deny_dirs:
            continue
        if p.name in deny_files:
            continue
        if p.suffix.lower() in _BACKUP_SKIP_EXT:
            continue
        if ".snapshots" in rel.parts:
            continue
        yield str(rel), p


def _snapshot_dir() -> Path:
    d = role_root() / ".snapshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _create_snapshot(reason: str, note: str = "") -> dict:
    """把当前作用域全部数据复制成一份快照，返回 meta。"""
    snap_dir = _snapshot_dir()
    name = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:6]
    dest = snap_dir / name
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for rel, p in _iter_scope_files():
        tgt = dest / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, tgt)
        count += 1
    meta = {
        "name": name,
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "reason": reason,
        "note": note[:60],
        "scope": _role_ctx.get(),
        "count": count,
    }
    atomic_json(dest / "manifest.json", meta)
    return meta


@app.get("/api/backup/files")
async def backup_files():
    """列出当前作用域下可导出 / 导入的数据文件（供前端分模块勾选）。"""
    out = []
    for rel, p in _iter_scope_files():
        if p.suffix.lower() in _BACKUP_TEXT_EXT:
            try:
                st = p.stat()
                out.append({"path": rel, "size": st.st_size})
            except OSError:
                pass
    out.sort(key=lambda x: x["path"])
    return {"files": out, "scope": _role_ctx.get()}


@app.post("/api/backup/snapshot")
async def backup_snapshot_create(req: Request):
    """创建一份全量数据快照（含图片 / 语音等媒体），可在后端随时整体恢复。"""
    note = ""
    try:
        body = await req.json()
        note = (body.get("note") or "").strip()
    except Exception:
        pass
    meta = _create_snapshot("manual", note)
    return {"ok": True, "snapshot": meta}


@app.get("/api/backup/snapshots")
async def backup_snapshot_list():
    snap_dir = _snapshot_dir()
    items = []
    for d in snap_dir.iterdir():
        if not d.is_dir():
            continue
        mp = d / "manifest.json"
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            n = sum(1 for _ in d.rglob("*") if _.is_file() and _.name != "manifest.json")
            meta = {"name": d.name, "time": "", "note": "", "reason": "unknown", "count": n,
                    "scope": _role_ctx.get()}
        items.append(meta)
    items.sort(key=lambda m: m.get("time", ""), reverse=True)
    return {"snapshots": items}


@app.post("/api/backup/snapshot/restore")
async def backup_snapshot_restore(req: Request):
    """恢复某份快照到当前作用域。恢复前自动快照当前状态，便于回退。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    name = (body.get("name") or "").strip()
    if not name or "/" in name or "\\" in name:
        return JSONResponse({"error": "非法快照名"}, status_code=400)
    src = _snapshot_dir() / name
    if not src.is_dir():
        return JSONResponse({"error": "快照不存在"}, status_code=404)
    # 恢复前自动备份当前状态
    backup = _create_snapshot("restore-backup", f"恢复 {name} 前自动备份")
    root = role_root()
    count = 0
    for p in src.rglob("*"):
        if not p.is_file() or p.name == "manifest.json":
            continue
        if p.name in _BACKUP_DENY_FILES:
            continue
        rel = p.relative_to(src)
        tgt = root / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, tgt)
        count += 1
    return {"ok": True, "restored": count, "backup": backup["name"]}


@app.delete("/api/backup/snapshot")
async def backup_snapshot_delete(req: Request):
    """删除一份快照。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    name = (body.get("name") or "").strip()
    if not name or "/" in name or "\\" in name:
        return JSONResponse({"error": "非法快照名"}, status_code=400)
    src = _snapshot_dir() / name
    if not src.is_dir():
        return JSONResponse({"error": "快照不存在"}, status_code=404)
    shutil.rmtree(src)
    return {"ok": True}


@app.get("/api/export")
async def data_export(files: str = "", fmt: str = "json"):
    """导出当前作用域数据。

    - fmt=json（默认）：单个 JSON 包（_meta + files），仅含文本数据，便于跨设备迁移；
    - fmt=zip：把全部用户数据（含图片 / 语音等媒体）打包成 zip 下载，即"全量"备份。
    - files=chat_log.json,memory.json：仅导出指定文件（分模块）。
    """
    root = role_root()
    wanted = None
    if files:
        wanted = {f.strip() for f in files.split(",") if f.strip()}

    if fmt == "zip":
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for rel, p in _iter_scope_files():
                if wanted and rel not in wanted:
                    continue
                try:
                    zf.write(p, rel)
                except OSError:
                    pass
        buf.seek(0)
        fname = f"xumo_backup_{_role_ctx.get()}_{datetime.now().strftime('%Y%m%d%H%M%S')}.zip"
        return StreamingResponse(
            buf,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    # 默认 JSON 包
    bundle = {
        "_meta": {
            "app": "xumo",
            "version": 1,
            "scope": _role_ctx.get(),
            "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "files": {},
    }
    for rel, p in _iter_scope_files():
        if p.suffix.lower() not in _BACKUP_TEXT_EXT:
            continue
        if wanted and rel not in wanted:
            continue
        try:
            bundle["files"][rel] = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
    if not bundle["files"]:
        return JSONResponse({"error": "没有可导出的数据（或筛选的文件不存在）"}, status_code=400)
    fname = f"xumo_export_{_role_ctx.get()}_{datetime.now().strftime('%Y%m%d%H%M%S')}.json"
    return JSONResponse(
        bundle,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/api/import")
async def data_import(req: Request):
    """导入数据：支持 JSON 包（body）或上传文件（.json / .zip）。

    - mode=merge（默认）：覆盖同名文件、新增缺的文件；
    - mode=replace：先清空当前作用域的全部数据文件，再导入（慎用）。
    """
    ctype = (req.headers.get("content-type") or "").lower()
    files: dict = {}
    mode = "merge"

    if "multipart/form-data" in ctype:
        form = await req.form()
        up = form.get("file")
        if up is None:
            return JSONResponse({"error": "未收到上传文件"}, status_code=400)
        data = await up.read()
        mode = (form.get("mode") or "merge").strip().lower()
        fname = (getattr(up, "filename", "") or "").lower()
        if fname.endswith(".zip"):
            import io
            import zipfile
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for item in zf.namelist():
                    if item.endswith("/") or ".." in item:
                        continue
                    if item.split("/")[-1] in _BACKUP_DENY_FILES:
                        continue
                    content = zf.read(item)
                    files[item] = content
        else:  # .json 包
            try:
                obj = json.loads(data.decode("utf-8"))
                files = obj.get("files", {})
                mode = (obj.get("mode") or mode)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return JSONResponse({"error": "JSON 解析失败"}, status_code=400)
    else:
        try:
            body = await req.json()
        except Exception:
            return JSONResponse({"error": "请求体格式错误"}, status_code=400)
        files = body.get("files")
        mode = (body.get("mode") or "merge").strip().lower()
        if not isinstance(files, dict):
            return JSONResponse({"error": "files 必须是对象"}, status_code=400)

    if not files:
        return JSONResponse({"error": "没有可导入的数据"}, status_code=400)
    if mode not in ("merge", "replace"):
        mode = "merge"

    root = role_root()
    if mode == "replace":
        for rel, p in list(_iter_scope_files()):
            if rel in files:
                continue
            try:
                p.unlink()
            except OSError:
                pass

    imported = 0
    for rel, content in files.items():
        if not isinstance(rel, str) or ".." in rel or rel.startswith("/"):
            continue
        if rel.split("/")[-1] in _BACKUP_DENY_FILES:
            continue
        tgt = root / rel
        tgt.parent.mkdir(parents=True, exist_ok=True)
        try:
            if isinstance(content, (bytes, bytearray)):
                tgt.write_bytes(bytes(content))
            elif tgt.suffix.lower() == ".json":
                atomic_json(tgt, json.loads(content))
            else:
                tgt.write_text(str(content), encoding="utf-8")
            imported += 1
        except (OSError, json.JSONDecodeError, TypeError):
            continue
    return {"ok": True, "imported": imported, "mode": mode}


# ---------------------------------------------------------------------------
# 长期记忆：把较早的聊天记录滚动压缩成摘要，让许墨跨会话"记得"更早的事
# ---------------------------------------------------------------------------
CHAT_MEMORY_FILE = RolePath("chat_memory.json")
_chat_memory_lock = asyncio.Lock()

# 后台任务强引用集合：asyncio 事件循环对 task 只存弱引用，
# 不持有引用的话任务会被 GC 静默回收（官方文档明确警告）
_background_tasks: set = set()


def _on_bg_task_done(task: "asyncio.Task"):
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception():
        print(f"[chat] bg task error: {task.exception()!r}", flush=True)

SUMMARY_KEEP_RECENT = 20   # 最近 N 条保持原文进入上下文，不进摘要
SUMMARY_TRIGGER = 44       # 未摘要消息累积到 N 条时触发一次压缩


def _load_chat_memory() -> dict:
    try:
        with open(CHAT_MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {"summary": "", "count": 0}
    except (FileNotFoundError, json.JSONDecodeError):
        return {"summary": "", "count": 0}


def _save_chat_memory(data: dict):
    atomic_json(CHAT_MEMORY_FILE, data)


SUMMARY_PROMPT = """你是对话记忆压缩器。请把【旧记忆摘要】与【近期对话记录】合并为一份新的记忆摘要，供角色"许墨"日后回忆他与"她"（用户）的相处点滴。
要求：
1. 用简洁的条目记录：她的个人信息与喜好、重要经历与约定、情绪事件与关系进展、共同完成的事情；
2. 保留具体细节（名字、时间、事件、约定），删除寒暄、重复与无信息量的内容；
3. 旧摘要中仍有价值的信息要保留并合并；
4. 总长不超过 500 字；
5. 只输出摘要正文，不要任何前后缀或解释。"""


async def _maybe_summarize_chat():
    """未摘要消息足够多时，压缩旧对话为长期记忆摘要。"""
    # 第一段：持锁快照待摘要数据，随即释放锁
    async with _chat_memory_lock:
        logs = _load_chat_log()
        mem = _load_chat_memory()
        try:
            count = min(int(mem.get("count", 0) or 0), len(logs))
        except (TypeError, ValueError):
            count = 0
        pending = logs[count:]
        if len(pending) < SUMMARY_TRIGGER:
            return
        to_sum = pending[:-SUMMARY_KEEP_RECENT]
        if not to_sum:
            return
        old_summary = (mem.get("summary") or "").strip()
        lines = []
        for m in to_sum:
            if m.get("role") not in ("user", "assistant"):
                continue
            who = "她" if m.get("role") == "user" else "许墨"
            content = (m.get("content") or "").strip()
            if content:
                lines.append(f"{who}：{content}")
        transcript = "\n".join(lines)[-8000:]

    print(f"[memory] summarize triggered: {len(to_sum)} msgs", flush=True)
    # LLM 调用在锁外执行：上游慢时（可达数分钟）不再阻塞记忆提取/其他摘要任务
    try:
        summary = await _call_llm(
            [
                {"role": "system", "content": SUMMARY_PROMPT},
                {
                    "role": "user",
                    "content": f"【旧记忆摘要】\n{old_summary or '（无）'}\n\n【近期对话记录】\n{transcript}",
                },
            ],
            max_tokens=800,
        )
    except Exception as e:
        print(f"[memory] summarize failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        return  # 压缩失败下次再试，不影响聊天

    summary = summary.strip()
    if not summary:
        return
    # 第二段：持锁写回；期间若有更新的摘要已写入（count 超过本次目标）则放弃本次结果
    async with _chat_memory_lock:
        mem_now = _load_chat_memory()
        try:
            count_now = min(int(mem_now.get("count", 0) or 0), len(_load_chat_log()))
        except (TypeError, ValueError):
            count_now = 0
        if count_now >= count + len(to_sum):
            return
        _save_chat_memory({"summary": summary, "count": count + len(to_sum)})
    print(f"[memory] summary saved, count -> {count + len(to_sum)}", flush=True)


# ---------------------------------------------------------------------------
# 记忆手账：手动添加 / 对话自动提取的结构化记忆，跨会话注入许墨的上下文
# ---------------------------------------------------------------------------
MEMORY_FILE = RolePath("memory.json")
_memory_lock = asyncio.Lock()

MEMORY_TAGS = ["她的事", "喜好", "约定", "重要日子", "习惯", "其他"]
MEMORY_MAX = 80            # 记忆条目上限（超出时淘汰最早的未置顶条目）
MEMORY_INJECT_MAX = 40     # 单次注入对话的最大记忆条数
MEMORY_EXTRACT_MIN_LEN = 6 # 用户消息过短不触发自动提取


def _load_memories() -> list:
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save_memories(items: list):
    atomic_json(MEMORY_FILE, items)


def _sorted_memories(items: list) -> list:
    """置顶优先，其余按时间倒序。"""
    pinned = [m for m in items if m.get("pinned")]
    normal = [m for m in items if not m.get("pinned")]
    pinned.sort(key=lambda m: m.get("ts", ""), reverse=True)
    normal.sort(key=lambda m: m.get("ts", ""), reverse=True)
    return pinned + normal


def _normalize_tag(tag) -> str:
    tag = (tag or "").strip()
    return tag if tag in MEMORY_TAGS else "其他"


def _mem_norm(text: str) -> str:
    return re.sub(r"[\s，。！？、,.!?~～…：:；;的]", "", text or "").lower()


def _memory_directive() -> str:
    """把记忆条目注入系统提示词，让许墨"自然记得"。"""
    items = _sorted_memories(_load_memories())[:MEMORY_INJECT_MAX]
    if not items:
        return ""
    lines = []
    for m in items:
        tag = m.get("tag") or "其他"
        day = (m.get("ts") or "")[:10]
        lines.append(f"- [{tag}] {m.get('content', '')}（{day}）")
    return (
        "\n\n【记忆手账】以下是关于「她」的重要记忆，你真切地记得这些事："
        "在相关话题时自然提起或默默遵守，不要生硬复述、不要一次性罗列：\n" + "\n".join(lines)
    )


def _style_directive(style) -> str:
    """回复语言风格：0=平静克制，100=宠溺亲昵。把用户设定的"宠溺度"注入系统提示。"""
    try:
        s = float(style)
    except (TypeError, ValueError):
        s = 0
    s = max(0.0, min(100.0, s))
    return (
        "\n\n【回复语言风格（用户设定 · 宠溺度 "
        + f"{int(round(s))}%）】"
        + "\n你回复时的语气与亲昵程度，请按下述设定收敛："
        + "\n- 0% 平静端：保持你一贯克制、有分寸的语调，温柔而不黏腻，话留三分，不主动撒娇、不过度亲昵。"
        + "\n- 100% 宠溺端：语气更宠溺亲昵，带着温柔的纵容与软糯的关怀，可更自然地用昵称、更黏人一点的尾音、更直白的偏爱，但仍守住你「话留三分」的底线，避免油腻、避免堆砌情话、避免每句都叫名字。"
        + "\n请按当前宠溺度在两端之间自然过渡：数值越低越平静克制，越高越宠溺亲昵；中间档则温和偏日常。"
    )


@app.get("/api/memory")
async def memory_list():
    items = _sorted_memories(_load_memories())
    return {"total": len(items), "items": items}


@app.post("/api/memory")
async def memory_add(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    content = (body.get("content") or "").strip()
    if not content:
        return JSONResponse({"error": "记忆内容不能为空"}, status_code=400)
    if len(content) > 120:
        return JSONResponse({"error": "记忆内容最多 120 字"}, status_code=400)
    item = {
        "id": uuid.uuid4().hex[:12],
        "content": content,
        "tag": _normalize_tag(body.get("tag")),
        "source": "manual",
        "pinned": False,
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    async with _memory_lock:
        items = _load_memories()
        items.append(item)
        _save_memories(items)
    return item


@app.put("/api/memory/{mid}")
async def memory_update(mid: str, req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    async with _memory_lock:
        items = _load_memories()
        item = next((m for m in items if m.get("id") == mid), None)
        if not item:
            return JSONResponse({"error": "记忆不存在"}, status_code=404)
        if "content" in body:
            content = (body.get("content") or "").strip()
            if not content:
                return JSONResponse({"error": "记忆内容不能为空"}, status_code=400)
            item["content"] = content[:120]
        if "tag" in body:
            item["tag"] = _normalize_tag(body.get("tag"))
        if "pinned" in body:
            item["pinned"] = bool(body.get("pinned"))
        _save_memories(items)
    return item


@app.delete("/api/memory/{mid}")
async def memory_delete(mid: str):
    async with _memory_lock:
        items = _load_memories()
        _save_memories([m for m in items if m.get("id") != mid])
    return {"ok": True}


# --- 记忆手账 · AI 配图（为一条记忆生成氛围场景插画） ---
MEMORY_IMG_DIR = RolePath("static", "memory_img")


@app.post("/api/memory/{mid}/image")
async def memory_image_generate(mid: str, bg: bool = False):
    """为一条记忆手账生成 AI 配图（按需，落盘并回写到记忆条目）。"""
    async def _work():
        async with _memory_lock:
            items = _load_memories()
            item = next((m for m in items if m.get("id") == mid), None)
            if not item:
                raise GenJobError("记忆不存在", status=404)
            snap = dict(item)
        material = (
            f"【记忆手账 · {snap.get('tag', '其他')}】\n{snap.get('content', '')}\n"
            f"记录时间：{snap.get('ts', '')}\n"
            f"请构思一张能代表这条记忆的氛围配图：安静、有画面感，低饱和紫调。"
        )
        img_url, img_prompt = await _llm_image_for_text(
            material, MEMORY_IMG_DIR, "/static/memory_img", f"mem_{mid}",
            IMG2IMG_SIZES.get("square", "1024x1024"), with_xumo=False,
        )
        if not img_url:
            raise GenJobError("配图生成失败，请重试")
        async with _memory_lock:
            fresh = _load_memories()
            for m in fresh:
                if m.get("id") == mid:
                    m["image"] = img_url
                    m["image_prompt"] = img_prompt
                    m["image_time"] = datetime.now().strftime("%m-%d %H:%M")
                    break
            _save_memories(fresh)
        return {"image": img_url + f"?t={int(_time.time())}", "affinity": None}

    if bg:
        job = await submit_gen_job("memory", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


MEMORY_EXTRACT_PROMPT = """你是记忆提取器，服务于角色"许墨"（《恋与制作人》，用户扮演"她"）。阅读这一轮对话，判断其中是否出现了值得许墨长期记住的、关于「她」的信息。
值得记住：她的个人信息（生日、职业、家乡、称呼偏好）、喜好与厌恶、重要经历、两人之间的约定、重要的日子、她的习惯与身体状况。
不值得记住：寒暄闲聊、情绪表达、临时性内容、与「她」无关的知识、许墨自己说的话。
要求：
1. 最多提取 2 条，每条一句话、不超过 30 字，主语用「她」；
2. 没有值得记的就只输出 []；
3. 严格只输出 JSON 数组，每项形如 {"content":"她……","tag":"喜好"}，tag 必须从 ["她的事","喜好","约定","重要日子","习惯","其他"] 中选择；
4. 不要输出任何 JSON 以外的内容（包括代码块标记或解释）。"""


def _parse_extract_json(text: str) -> list:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    if not text.startswith("["):
        m = re.search(r"\[.*\]", text, re.DOTALL)
        if not m:
            return []
        text = m.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    out = []
    if isinstance(data, list):
        for it in data[:2]:
            if isinstance(it, str):
                content, tag = it, "其他"
            elif isinstance(it, dict):
                content, tag = it.get("content") or "", it.get("tag") or "其他"
            else:
                continue
            content = str(content).strip()
            if 2 <= len(content) <= 60:
                out.append({"content": content, "tag": _normalize_tag(tag)})
    return out


async def _maybe_extract_memory(user_text: str, reply: str):
    """对话后判断是否出现值得长期记住的关于她的信息（后台执行，不影响聊天）。"""
    if len(user_text) < MEMORY_EXTRACT_MIN_LEN:
        return
    try:
        raw = await _call_llm(
            [
                {"role": "system", "content": MEMORY_EXTRACT_PROMPT},
                {"role": "user", "content": f"她说：{user_text}\n许墨回：{reply}"},
            ],
            max_tokens=800,  # 推理型模型的思考会消耗 token，预算不足时 content 为空
        )
    except Exception:
        return
    extracted = _parse_extract_json(raw)
    if not extracted:
        return
    async with _memory_lock:
        items = _load_memories()
        norms = {_mem_norm(m.get("content", "")) for m in items}
        added = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        for e in extracted:
            n = _mem_norm(e["content"])
            if not n or n in norms:
                continue
            if any(n in x or x in n for x in norms):
                continue  # 与已有记忆互为子串，视为重复
            items.append({
                "id": uuid.uuid4().hex[:12],
                "content": e["content"],
                "tag": e["tag"],
                "source": "auto",
                "pinned": False,
                "ts": now,
            })
            norms.add(n)
            added += 1
        if not added:
            return
        if len(items) > MEMORY_MAX:
            pinned = [m for m in items if m.get("pinned")]
            normal = sorted(
                [m for m in items if not m.get("pinned")],
                key=lambda m: m.get("ts", ""),
            )
            items = pinned + normal[-(MEMORY_MAX - len(pinned)):]
        _save_memories(items)
    print(f"[memory] auto extracted {added} item(s)", flush=True)


# ---------------------------------------------------------------------------
# 玩家名字（她希望被许墨怎么称呼）
# ---------------------------------------------------------------------------
PLAYER_FILE = RolePath("player.json")


def _load_player() -> dict:
    try:
        with open(PLAYER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_player(data: dict):
    atomic_json(PLAYER_FILE, data)


def get_player_name() -> str:
    return (_load_player().get("name") or "").strip()


def _name_directive() -> str:
    """玩家自定义名字时，指导模型在合适的时机克制地使用名字（不是每句都叫）。"""
    name = get_player_name()
    if not name:
        return ""
    return f"""

【她的名字】
她的名字是「{name}」。称呼规则（必须遵守）：
- 大多数句子仍用「你」自然对话，绝不能每句都带名字；
- 只在合适的时机才轻声唤她的名字：温柔提醒、安慰、久别寒暄、认真叮嘱、她情绪低落需要被接住、或情感浓度明显升高的时刻；
- 频率克制：大约每 6-10 句回复出现一次即可，连续两句不要都带名字；
- 叫名字时轻柔自然，如「{name}，……」，保持许墨的语感与克制。"""


def _time_directive() -> str:
    """注入当前真实时段与许墨此刻的场景，避免回复出现与时间矛盾的话（如早上说『晚上好』）。

    系统提示词本身不含时间信息，模型只能凭空猜测，常把早上说成晚上。这里把服务端
    真实时段（按时段映射 早上/中午/下午/晚上/凌晨）与生活引擎当前场景一并注入。
    """
    now = datetime.now()
    h = now.hour
    if h < 5:
        tod = "凌晨"
    elif h < 11:
        tod = "早上"
    elif h < 14:
        tod = "中午"
    elif h < 18:
        tod = "下午"
    else:
        tod = "晚上"
    weekday = "一二三四五六日"[now.weekday()]
    parts = [f"\n\n【此刻】现在是 {now.strftime('%Y-%m-%d %H:%M')}，星期{weekday}，{tod}。"]
    st = _load_life().get("state")
    if st and (_time.time() - st.get("since_ts", 0)) <= 2 * 3600:
        parts.append(
            f"你此刻在「{st.get('place')} · {st.get('scene')}」，正在「{st.get('activity')}」，心情{st.get('mood')}。"
        )
    parts.append(
        "请让你的回复与当前真实时段自然契合，绝不要说出与当前时段矛盾的话"
        "（如现在是早上就不能说『晚上好』『该睡了』，现在是凌晨就不要说『午安』）。"
    )
    return "".join(parts)


@app.get("/api/player")
async def get_player():
    return {"name": get_player_name()}


@app.post("/api/player")
async def set_player(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "名字不能为空"}, status_code=400)
    if len(name) > 12:
        return JSONResponse({"error": "名字最多 12 个字"}, status_code=400)
    _save_player({"name": name})
    return {"name": name}


@app.delete("/api/player")
async def clear_player():
    _save_player({})
    return {"ok": True}


# ---------------------------------------------------------------------------
# 屏幕感知：截取电脑屏幕 → 视觉理解（许墨能"看到"你的屏幕）
# ---------------------------------------------------------------------------
from io import BytesIO  # noqa: E402
from fastapi.concurrency import run_in_threadpool  # noqa: E402

try:
    from PIL import ImageGrab
    _PIL_OK = True
except Exception:
    _PIL_OK = False

SCREEN_MAX_W = int(os.getenv("SCREEN_MAX_WIDTH", "1366"))
SCREEN_JPEG_QUALITY = int(os.getenv("SCREEN_JPEG_QUALITY", "62"))

# 节流缓存：短时间内多次请求复用同一张截图（通话连续对话场景）
_screen_cache = {"ts": 0.0, "jpeg": None}
_SCREEN_CACHE_TTL = 2.0


def _screen_grab_jpeg():
    """截取当前主屏并压缩为 JPEG bytes；失败返回 None，调用方自行降级为纯文本。"""
    if not _PIL_OK:
        return None
    now = _time.time()
    if _screen_cache["jpeg"] and now - _screen_cache["ts"] < _SCREEN_CACHE_TTL:
        return _screen_cache["jpeg"]
    try:
        img = ImageGrab.grab()
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if img.width > SCREEN_MAX_W:
            h = round(img.height * SCREEN_MAX_W / img.width)
            img = img.resize((SCREEN_MAX_W, h))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=SCREEN_JPEG_QUALITY)
        jpeg = buf.getvalue()
        _screen_cache.update(ts=now, jpeg=jpeg)
        return jpeg
    except Exception:
        return None


SCREEN_SYS_HINT = (
    "\n\n【屏幕感知】本轮消息附带了一张她当前电脑屏幕的实时截图。"
    "你能隔着屏幕看到她的画面：请自然地把屏幕内容融进回应"
    "（她在看的网页、写的文档、用的软件、屏幕上的细节），"
    "体现你一贯的观察力；但不要逐字复述屏幕，点到即止、话留三分。"
)


@app.get("/api/screen/capture")
async def screen_capture():
    """截取当前屏幕，返回 JPEG（前端预览/调试用）。"""
    jpeg = await run_in_threadpool(_screen_grab_jpeg)
    if not jpeg:
        return JSONResponse(
            {"error": "截屏失败（需要桌面会话，且运行环境需安装 Pillow）"}, status_code=500
        )
    return Response(content=jpeg, media_type="image/jpeg")


@app.post("/api/screen/analyze")
async def screen_analyze(req: Request):
    """视觉模型描述当前屏幕内容，返回文字描述。"""
    jpeg = await run_in_threadpool(_screen_grab_jpeg)
    if not jpeg:
        return JSONResponse({"error": "截屏失败"}, status_code=500)
    question = ""
    try:
        data = await req.json()
        question = (data.get("question") or "").strip()
    except Exception:
        pass
    if question:
        prompt = (
            f"用户想了解：{question}。请围绕它描述这张电脑屏幕截图，"
            "120 字以内，直接输出描述，不要任何前后缀。"
        )
    else:
        prompt = (
            "请描述这张电脑屏幕截图：正在使用的应用或网站、页面主要在讲什么、"
            "可见的关键文字。120 字以内，直接输出描述，不要任何前后缀。"
        )
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,"
                        + base64.b64encode(jpeg).decode()
                    },
                },
            ],
        }
    ]
    try:
        desc = await _call_llm(messages, max_tokens=300)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    return {"desc": desc}


# ===========================================================================
# 对话智能推荐 · App 场景与功能（关键词意图匹配，回复内嵌卡片 + 输入栏推荐位）
# ===========================================================================
# 每条目：kw 为触发关键词；特殊条目带 scene/mode 字段表示深层跳转：
#   scene="call"      → 直接拨打许墨电话（openApp('phone') + startCall('许墨')）
#   scene="mode"      → 切换全屏模式（mode="a" 沉浸共生 / "g" 恋语市世界 / "h" 手谈）

# 推荐系统配置
_RECOMMENDATION_CONFIG = {
    "layers": {
        "keyword": {"weight": 2.0, "enabled": True},
        "semantic": {"weight": 1.5, "enabled": True},
        "personalization": {"weight": 1.0, "enabled": True},
        "time_based": {"weight": 0.8, "enabled": True}
    },
    "max_recommendations": 3,
    "min_confidence": 0.3
}

REC_CATALOG = {
    "world":     {"name": "世界·恋语市", "emoji": "🌍", "kw": ["恋语市", "世界", "城市", "逛街", "散步", "小镇", "出门", "转转", "去玩", "地图", "探索", "游玩", "景点"]},
    "moments":   {"name": "朋友圈", "emoji": "🦋", "kw": ["朋友圈", "动态", "发的消息", "说说", "分享", "看看他发了什么", "社交动态", "更新", "帖子"]},
    "affinity":  {"name": "心动", "emoji": "💜", "kw": ["心动值", "心动", "亲密度", "好感度", "爱意", "多爱我", "关系", "感情", "亲密"]},
    "quotes":    {"name": "语录", "emoji": "📜", "kw": ["语录", "收藏的话", "他说过", "名言", "金句", "经典台词", "语录集", "他说的话"]},
    "memory":    {"name": "记忆手账", "emoji": "🧠", "kw": ["记忆", "手账", "记得", "回忆", "忘了", "记忆碎片", "回忆录", "记忆保存"]},
    "notes":     {"name": "备忘录", "emoji": "📝", "kw": ["备忘录", "记事", "记下", "备忘", "记一下", "笔记", "记录", "便签"]},
    "promises":  {"name": "承诺管家", "emoji": "🤝", "kw": ["承诺", "答应", "保证", "说好了", "约定", "誓言", "承诺管理"]},
    "xumodiary": {"name": "许墨日记", "emoji": "📓", "kw": ["许墨日记", "他的日记", "日记写了什么", "他的记录", "教授日记", "Lucien日记"]},
    "review":    {"name": "时光总结", "emoji": "📊", "kw": ["总结", "时光总结", "周报", "月报", "年结", "复盘", "回顾", "时光回顾"]},
    "ledger":    {"name": "墨记账", "emoji": "💰", "kw": ["记账", "账本", "消费", "花费", "花了多少", "财务管理", "支出", "记账本"]},
    "clock":     {"name": "时钟", "emoji": "⏰", "kw": ["闹钟", "时钟", "起床", "提醒", "定时", "几点", "时间", "时间管理"]},
    "weather":   {"name": "天气", "emoji": "🌦️", "kw": ["天气", "下雨", "气温", "温度", "阴晴", "冷热", "天气预报", "天气情况"]},
    "listen":    {"name": "音乐·一起听", "emoji": "🎧", "kw": ["音乐", "听歌", "歌", "一起听", "唱歌", "旋律", "曲子", "bgm", "音乐播放", "歌曲"]},
    "photos":    {"name": "相册", "emoji": "📷", "kw": ["相册", "照片", "图片", "合影", "拍照", "自拍", "相册", "照片墙", "图片库"]},
    "img2img":   {"name": "画境", "emoji": "🎨", "kw": ["画画", "画一张", "绘画", "立绘", "卡面", "绘图", "图片生成", "作画", "绘画创作"]},
    "timebox":   {"name": "时光", "emoji": "⏳", "kw": ["纪念日", "时光", "倒数", "在一起多少天", "多少天", "时光记录", "重要时刻"]},
    "dates":     {"name": "约会", "emoji": "💞", "kw": ["约会", "约我", "想约", "手账", "想去哪", "约会计划", "约会安排", "浪漫约会"]},
    "chathist":  {"name": "聊天记录", "emoji": "🕘", "kw": ["聊天记录", "历史记录", "存档", "恢复", "之前的对话", "对话历史", "聊天存档"]},
    "browser":   {"name": "浏览器", "emoji": "🌐", "kw": ["浏览器", "上网", "网址", "查一下", "搜一下", "网页", "浏览网页", "网络"]},
    "words":     {"name": "背单词", "emoji": "📚", "kw": ["背单词", "单词", "英语", "记单词", "词汇", "英语学习", "单词记忆"]},
    "coach":     {"name": "学习陪伴", "emoji": "🎓", "kw": ["学习", "专注", "自习", "打卡", "番茄", "陪伴学习", "学习助手", "专注学习"]},
    "video":     {"name": "视频总结", "emoji": "🎬", "kw": ["视频总结", "总结视频", "看视频", "视频内容", "视频解析"]},
    "watch":     {"name": "一起看", "emoji": "📺", "kw": ["一起看", "追剧", "看剧", "视频", "看电影", "观影", "观看视频"]},
    "solve":     {"name": "解题", "emoji": "✍️", "kw": ["解题", "题目", "数学", "作业", "难题", "不会做", "解题助手", "作业辅导"]},
    "reading":   {"name": "共读", "emoji": "📖", "kw": ["读书", "看书", "共读", "书", "小说", "阅读", "阅读计划", "书籍"]},
    "dream":     {"name": "清梦", "emoji": "💤", "kw": ["清梦", "做梦", "梦", "睡", "睡眠", "入梦", "梦境"]},
    "mind":      {"name": "心智图谱", "emoji": "🧩", "kw": ["心智图谱", "图谱", "思维", "心里想什么", "思维导图", "心智分析"]},
    "bfly":      {"name": "蝶语花园", "emoji": "🦋", "kw": ["蝶语", "花园", "蝴蝶", "养蝶", "蝴蝶花园", "蝴蝶养殖"]},
    "pverse":    {"name": "平行宇宙", "emoji": "🌠", "kw": ["平行宇宙", "平行世界", "if线", "另一个我", "平行时空", "多元宇宙"]},
    "astro":     {"name": "天台观星", "emoji": "🔭", "kw": ["观星", "星星", "星座", "天文", "夜空", "流星", "星空", "天文学"]},
    "bsfile":    {"name": "黑天鹅档案", "emoji": "🦢", "kw": ["黑天鹅", "档案", "机密", "组织", "black swan", "秘密档案", "组织档案"]},
    "wardrobe":  {"name": "衣橱", "emoji": "👗", "kw": ["衣橱", "换装", "衣服", "穿搭", "试衣", "服装", "时尚", "穿衣"]},
    "work":      {"name": "工作助手", "emoji": "💼", "kw": ["工作", "任务", "计划", "办公", "项目", "待办", "工作任务", "办公助手"]},
    "diary":     {"name": "恋爱日记", "emoji": "💌", "kw": ["恋爱日记", "日记", "写日记", "记录今天", "情感日记", "心情日记"]},
    "go":        {"name": "手谈", "emoji": "⚫", "kw": ["围棋", "手谈", "下棋", "棋局", "katago", "棋类", "围棋对弈"]},
    "radio":     {"name": "许墨电台", "emoji": "📻", "kw": ["电台", "广播", "播报", "收音机", "晨间", "节目", "播音", "广播节目"]},
    "lab":       {"name": "B3实验室", "emoji": "🧪", "kw": ["实验", "实验室", "b3", "研究", "科研", "科学实验", "实验室工作"]},
    "pet":       {"name": "共养宠物", "emoji": "🐾", "kw": ["宠物", "养宠物", "猫", "小狗", "电子宠物", "喂", "宠物照顾", "宠物养成"]},
    "letter":    {"name": "许墨来信", "emoji": "✉️", "kw": ["来信", "信", "邮件", "写信", "给他写信", "信件", "邮件往来"]},
    "wish":      {"name": "许愿池", "emoji": "🪙", "kw": ["许愿", "愿望", "祈祷", "许愿池", "愿望实现", "祈祷祝福"]},
    "div":       {"name": "占卜屋", "emoji": "🔮", "kw": ["占卜", "塔罗", "运势", "算命", "抽牌", "占卜屋", "命运占卜"]},
    "spark":     {"name": "灵感闪念", "emoji": "💡", "kw": ["灵感", "闪念", "点子", "想法", "创意", "灵感记录", "想法捕捉"]},
    "clip":      {"name": "剪贴板", "emoji": "📋", "kw": ["剪贴板", "复制", "粘贴", "接话", "剪贴", "复制粘贴", "内容同步"]},
    "oracle":    {"name": "决策预言", "emoji": "🎯", "kw": ["决策", "预言", "选择", "犹豫", "拿不定", "决策辅助", "预言分析"]},
    "habits":    {"name": "共同习惯", "emoji": "✅", "kw": ["习惯", "坚持", "共同习惯", "生活习惯", "习惯养成", "习惯追踪"]},
    "deep":      {"name": "深度共鸣", "emoji": "🌀", "kw": ["深度共鸣", "观察手记", "共梦", "合著", "记忆碎片", "深度交流", "共鸣连接"]},
    "timecall":  {"name": "时空热线", "emoji": "📞", "kw": ["时空热线", "热线", "打给他", "接通", "时空通话", "热线电话"]},
    "debate":    {"name": "双我辩论", "emoji": "⚖️", "kw": ["辩论", "双我", "两个我", "理性感性", "自我辩论", "内心辩论"]},
    "together":  {"name": "合影日历", "emoji": "📸", "kw": ["合影", "日历", "照片墙", "合影日历", "照片日历", "合影记录"]},
    "achv":      {"name": "心动成就", "emoji": "🏆", "kw": ["成就", "勋章", "里程碑", "解锁", "成就系统", "成就解锁"]},
    "sos":       {"name": "情绪急救", "emoji": "🆘", "kw": ["难过", "伤心", "哭", "委屈", "难受", "崩溃", "emo", "急救", "情绪急救"]},
    "lifeline":  {"name": "人生模拟", "emoji": "🪐", "kw": ["人生", "模拟", "重来", "重活", "人生模拟器", "模拟人生"]},
    "dreamlab":  {"name": "梦境解码器", "emoji": "🌙", "kw": ["梦境解码", "解梦", "梦见", "梦到", "梦境分析", "解梦器"]},
    "pmail":     {"name": "平行信箱", "emoji": "📬", "kw": ["平行信箱", "未来的信", "寄给未来", "平行世界信", "未来信件"]},
    "nradio":    {"name": "深夜电台", "emoji": "🌃", "kw": ["深夜电台", "夜话", "睡前", "晚安电台", "夜间节目", "夜广播"]},
    "telepathy": {"name": "默契雷达", "emoji": "📡", "kw": ["默契", "雷达", "猜心", "懂不懂我", "心灵感应", "默契测试"]},
    "fate":      {"name": "命运岔路", "emoji": "🔀", "kw": ["命运", "岔路", "分岔", "命运选择", "人生岔路", "命运分岔"]},
    "pulse":     {"name": "心跳频谱", "emoji": "💓", "kw": ["心跳", "频谱", "心率", "心跳检测", "心率频谱", "心跳分析"]},
    "subconscious": {"name": "潜意识密室", "emoji": "🔐", "kw": ["潜意识", "密室", "测谎", "谎言", "说谎", "潜意识探索", "深层心理"]},
    "capsule":   {"name": "时空胶囊", "emoji": "⏲️", "kw": ["时空胶囊", "胶囊", "寄给未来", "时间胶囊", "未来胶囊"]},
    "empath":    {"name": "共感温度计", "emoji": "🌡️", "kw": ["共感", "温度计", "情绪温度", "情感温度", "共情测量"]},
    "noracle":   {"name": "七日预言", "emoji": "🔮", "kw": ["七日", "预言", "未来一周", "周预言", "一周预测", "七日运势"]},
    "whisper":   {"name": "沉默信使", "emoji": "🤫", "kw": ["沉默信使", "悄悄话", "匿名", "秘密传话", "匿名消息"]},
    "mixer":     {"name": "心跳调音台", "emoji": "🎛️", "kw": ["调音", "混音", "心跳调音", "音效调节", "心跳音效", "音频调音"]},
    "rtm":       {"name": "逆向时光机", "emoji": "🕰️", "kw": ["逆向", "时光机", "回到过去", "时光倒流", "时间逆转", "回到从前"]},
    "fusion":    {"name": "人格融合", "emoji": "🧬", "kw": ["人格", "融合", "合体", "人格整合", "身份融合", "自我融合"]},
    "theater":   {"name": "潜意识剧场", "emoji": "🎭", "kw": ["剧场", "潜意识", "剧本", "上演", "心理剧场", "潜意识剧场"]},
    "fateecho":  {"name": "命运回声图谱", "emoji": "🗣️", "kw": ["回声", "命运回声", "图谱", "命运图谱", "回声分析", "命运回响"]},
    "vault":     {"name": "时光密室", "emoji": "🗄️", "kw": ["密室", "时光", "收藏", "时光收藏", "秘密密室", "时光宝库"]},
    "pulselab":  {"name": "心跳实验室", "emoji": "🫀", "kw": ["心跳实验室", "心电图", "心率实验", "心跳研究", "心率实验室"]},
    "rift":      {"name": "次元裂隙", "emoji": "🌀", "kw": ["次元", "裂隙", "跨界", "穿越", "维度穿越", "次元裂缝"]},
    "wager":     {"name": "命运赌局", "emoji": "🎰", "kw": ["赌局", "赌", "下注", "打赌", "命运赌", "命运赌博"]},
    "relic":     {"name": "回忆修复工坊", "emoji": "🛠️", "kw": ["回忆修复", "碎片", "修复记忆", "失忆", "记忆修复", "回忆工坊"]},
    "symbiote":  {"name": "共生体演化", "emoji": "🐚", "kw": ["共生", "演化", "磨合", "共生关系", "共同演化", "关系磨合"]},
    "extensions": {"name": "AI扩展", "emoji": "🧩", "kw": ["扩展", "插件", "ai扩展", "自定义功能", "功能扩展", "插件系统"]},
    "sms":       {"name": "短信", "emoji": "💬", "kw": ["短信", "发消息", "未读", "消息", "短信消息", "文本消息"]},
    "call":      {"name": "通话", "emoji": "📞", "kw": ["打电话", "通话", "拨号", "语音通话", "想听他的声音", "打给你"], "scene": "call"},
    "mode_a":    {"name": "沉浸共生", "emoji": "🌌", "kw": ["沉浸", "沉浸模式", "全屏", "共生模式"], "scene": "mode", "mode": "a"},
    "mode_g":    {"name": "恋语市·世界", "emoji": "🌍", "kw": ["去恋语市", "世界模式", "全屏世界"], "scene": "mode", "mode": "g"},
    # 新增场景和功能扩展
    "meditation": {"name": "冥想空间", "emoji": "🧘", "kw": ["冥想", "禅修", "静心", "放松", "心灵", "平静"]},
    "journey":   {"name": "心灵旅程", "emoji": "🚂", "kw": ["旅程", "心灵旅程", "探索", "自我发现", "成长"]},
    "tarot":     {"name": "每日塔罗", "emoji": "🃏", "kw": ["塔罗", "每日塔罗", "抽卡", "指引", "运势"]},
    "breathing": {"name": "呼吸练习", "emoji": "🌬️", "kw": ["呼吸", "深呼吸", "调节", "放松呼吸", "气息"]},
    "gratitude": {"name": "感恩日记", "emoji": "🙏", "kw": ["感恩", "感谢", "感恩日记", "记录感恩", "感恩记录"]},
    "reflection": {"name": "每日反思", "emoji": "🤔", "kw": ["反思", "每日反思", "总结", "回顾", "自我反思"]},
    "goals":     {"name": "目标追踪", "emoji": "🎯", "kw": ["目标", "追踪", "目标追踪", "目标管理", "达成"]},
    "journal":   {"name": "心情日记", "emoji": "📔", "kw": ["心情", "心情日记", "情绪记录", "心情记录", "情感日记"]},
    "wellness":  {"name": "健康追踪", "emoji": "❤️", "kw": ["健康", "健康追踪", "身体", "运动", "锻炼", "健康数据"]},
    "finance":   {"name": "理财助手", "emoji": "💹", "kw": ["理财", "投资", "财务", "理财助手", "资产管理"]},
    "calendar":  {"name": "日程管理", "emoji": "📅", "kw": ["日程", "日历", "日程管理", "时间安排", "计划安排"]},
    "reminder":  {"name": "智能提醒", "emoji": "🔔", "kw": ["提醒", "智能提醒", "提醒事项", "待办提醒", "通知"]},
    "habits":    {"name": "习惯养成", "emoji": "🔄", "kw": ["习惯", "养成", "习惯养成", "打卡", "坚持习惯"]},
    "social":    {"name": "社交助手", "emoji": "👥", "kw": ["社交", "人际关系", "朋友", "社交助手", "人际交往"]},
    "travel":    {"name": "旅行规划", "emoji": "✈️", "kw": ["旅行", "旅游", "旅行规划", "出行", "游玩"]},
    "food":      {"name": "美食记录", "emoji": "🍽️", "kw": ["美食", "食物", "美食记录", "餐厅", "菜谱"]},
    "exercise":  {"name": "运动健身", "emoji": "🏃", "kw": ["运动", "健身", "运动健身", "锻炼", "体育"]},
    "sleep":     {"name": "睡眠监测", "emoji": "😴", "kw": ["睡眠", "睡眠监测", "睡觉", "休息", "睡眠质量"]},
    "water":     {"name": "饮水提醒", "emoji": "💧", "kw": ["喝水", "饮水", "饮水提醒", "水分", "补水"]},
    "mood":      {"name": "情绪追踪", "emoji": "😊", "kw": ["情绪", "情绪追踪", "心情", "情感状态", "情绪变化"]},
    "idea":      {"name": "创意笔记", "emoji": "💭", "kw": ["创意", "想法", "创意笔记", "灵感记录", "点子"]},
    "project":   {"name": "项目管理", "emoji": "📋", "kw": ["项目", "项目管理", "项目计划", "项目追踪", "项目任务"]},
    "book":      {"name": "阅读清单", "emoji": "📚", "kw": ["书", "书籍", "阅读清单", "读书计划", "书单"]},
    "movie":     {"name": "观影记录", "emoji": "🎬", "kw": ["电影", "影片", "观影记录", "电视剧", "追剧记录"]},
    "music_rec": {"name": "音乐推荐", "emoji": "🎵", "kw": ["音乐推荐", "推荐音乐", "歌单", "音乐发现", "新歌"]},
    "podcast":   {"name": "播客订阅", "emoji": "🎙️", "kw": ["播客", " Podcast", "播客订阅", "音频节目", "有声内容"]},
    "news":      {"name": "新闻资讯", "emoji": "📰", "kw": ["新闻", "资讯", "新闻资讯", "时事", "热点"]},
    "weather_detail": {"name": "详细天气", "emoji": "🌤️", "kw": ["详细天气", "天气预报", "气温详情", "空气质量", "天气详情"]},
    "map_search": {"name": "地图搜索", "emoji": "🗺️", "kw": ["地图搜索", "查找地点", "位置", "导航", "路线"]},
    "translate": {"name": "翻译助手", "emoji": "🌐", "kw": ["翻译", "翻译助手", "语言翻译", "外语", "翻译工具"]},
    "calculator": {"name": "计算器", "emoji": "🔢", "kw": ["计算", "计算器", "数学计算", "算数", "计算工具"]},
    "timer":     {"name": "计时器", "emoji": "⏱️", "kw": ["计时", "计时器", "倒计时", "秒表", "计时工具"]},
    "stopwatch": {"name": "秒表", "emoji": "⏲️", "kw": ["秒表", "计时", "计时工具", "精准计时", "时间测量"]},
    "scanner":   {"name": "扫描工具", "emoji": "📷", "kw": ["扫描", "扫描工具", "文档扫描", "二维码", "条形码"]},
    "voice_note": {"name": "语音笔记", "emoji": "🎤", "kw": ["语音", "语音笔记", "录音", "语音记录", "声音笔记"]},
    "password":  {"name": "密码管理", "emoji": "🔐", "kw": ["密码", "密码管理", "密码本", "账户", "登录密码"]},
    "storage":   {"name": "存储管理", "emoji": "💾", "kw": ["存储", "存储管理", "文件管理", "云存储", "空间"]},
    "backup":    {"name": "数据备份", "emoji": "🔄", "kw": ["备份", "数据备份", "恢复", "备份恢复", "数据保护"]},
    "clean":     {"name": "清理工具", "emoji": "🧹", "kw": ["清理", "清理工具", "垃圾清理", "优化", "系统清理"]},
    "security":  {"name": "安全中心", "emoji": "🛡️", "kw": ["安全", "安全中心", "隐私", "防护", "系统安全"]},
    "settings":  {"name": "系统设置", "emoji": "⚙️", "kw": ["设置", "系统设置", "配置", "选项", "偏好设置"]},
    "help":      {"name": "帮助中心", "emoji": "❓", "kw": ["帮助", "帮助中心", "使用指南", "教程", "使用说明"]},
    "feedback":  {"name": "意见反馈", "emoji": "💬", "kw": ["反馈", "意见反馈", "建议", "问题反馈", "用户反馈"]},
    "about":     {"name": "关于我们", "emoji": "ℹ️", "kw": ["关于", "关于我们", "版本", "介绍", "信息"]},
}

_REC_LABEL = {
    "call": "给许墨打电话",
    "mode_a": "进入沉浸共生",
    "mode_g": "进入恋语市世界",
    # 新增深层跳转标签
    "meditation": "开始冥想放松",
    "breathing": "开始呼吸练习",
    "tarot": "抽取今日塔罗",
    "journey": "开启心灵旅程",
}

# 同义词扩展映射：提升关键词匹配的语义覆盖度
_SYNONYM_MAP = {
    # 情绪类
    "难过": ["伤心", "委屈", "难受", "崩溃", "emo", "不开心", "痛苦", "郁闷"],
    "开心": ["高兴", "快乐", "愉快", "兴奋", "欢喜", "开心"],
    "生气": ["愤怒", "不爽", "烦躁", "恼火", "气愤"],
    "担心": ["焦虑", "紧张", "不安", "忧虑", "害怕"],
    "累": ["疲惫", "疲倦", "累", "困", "乏力"],
    
    # 意图类
    "想": ["想要", "希望", "渴望", "期待", "打算"],
    "做": ["制作", "创作", "完成", "执行", "实施"],
    "看": ["观看", "浏览", "阅读", "查看", "瞧"],
    "听": ["收听", "聆听", "倾听"],
    "去": ["前往", "到", "来", "去到"],
    
    # 时间类
    "现在": ["此刻", "目前", "今天", "当下"],
    "以前": ["过去", "之前", "从前", "往日"],
    "以后": ["未来", "之后", "将来", "往后"],
    
    # 关系类
    "我们": ["咱们", "我和你", "彼此"],
    "你": ["您", "亲", "亲爱的"],
}


def _expand_keywords(keywords: list) -> set:
    """扩展关键词集合，包含同义词"""
    expanded = set(keywords)
    for kw in keywords:
        if kw in _SYNONYM_MAP:
            expanded.update(_SYNONYM_MAP[kw])
    return expanded


def _kw_hits(text: str, info: dict) -> int:
    """增强的关键词命中算法：支持同义词扩展、权重衰减、短语匹配"""
    if not text:
        return 0
    
    text_lower = text.lower()
    score = 0.0
    keywords = info.get("kw", [])
    
    # 扩展关键词集合
    expanded_keywords = _expand_keywords(keywords)
    
    for kw in expanded_keywords:
        if not kw:
            continue
            
        kw_lower = kw.lower()
        
        # 精确匹配：权重1.0
        if kw_lower in text_lower:
            score += 1.0
            continue
            
        # 短语匹配：权重0.8 (至少2个字的词组)
        if len(kw) >= 2 and kw_lower in text_lower:
            score += 0.8
            continue
            
        # 部分匹配：权重0.5 (关键词的一部分在文本中)
        if len(kw) >= 2 and (kw_lower[:2] in text_lower or kw_lower[-2:] in text_lower):
            score += 0.5
    
    # 权重衰减：避免单一关键词过度匹配
    if score > 3.0:
        score = 3.0 + (score - 3.0) * 0.3  # 超过3分后增益递减
    
    return int(score)


def _rec_item(key: str) -> dict | None:
    info = REC_CATALOG.get(key)
    if not info:
        return None
    if key == "call":
        return {"app": "phone", "scene": "call", "name": info["name"], "emoji": info["emoji"], "label": _REC_LABEL["call"]}
    if info.get("scene") == "mode":
        return {"app": "mode", "scene": "mode", "mode": info["mode"], "name": info["name"], "emoji": info["emoji"], "label": _REC_LABEL[key]}
    return {"app": key, "name": info["name"], "emoji": info["emoji"], "label": f"打开「{info['name']}」"}


def _analyze_conversation_intent_simple(user_text: str, reply: str) -> dict:
    """简化的对话意图分析：基于规则和关键词，避免频繁LLM调用"""
    intent = {
        "emotion": "平静",
        "topics": [],
        "intent": "聊天",
        "recommendation_hints": []
    }
    
    combined_text = (user_text + " " + reply).lower()
    
    # 情感分析
    emotion_keywords = {
        "难过": ["难过", "伤心", "委屈", "难受", "崩溃", "emo", "不开心", "痛苦", "哭"],
        "开心": ["开心", "高兴", "快乐", "愉快", "兴奋", "欢喜", "笑", "哈哈"],
        "生气": ["生气", "愤怒", "不爽", "烦躁", "恼火", "气愤", "讨厌"],
        "担心": ["担心", "焦虑", "紧张", "不安", "忧虑", "害怕", "怕"],
        "累": ["累", "疲惫", "疲倦", "困", "乏力", " tired"]
    }
    
    max_emotion_score = 0
    for emotion, keywords in emotion_keywords.items():
        score = sum(1 for kw in keywords if kw in combined_text)
        if score > max_emotion_score:
            max_emotion_score = score
            intent["emotion"] = emotion
    
    # 意图分析
    intent_mapping = {
        "娱乐": ["玩", "游戏", "看剧", "电影", "音乐", "听歌", "娱乐"],
        "工作": ["工作", "任务", "项目", "办公", "学习", "写", "做"],
        "学习": ["学习", "读书", "看书", "课程", "复习", "背单词"],
        "情感": ["想", "爱", "喜欢", "感情", "关系", "心里"],
        "放松": ["休息", "放松", "睡觉", "睡觉", "休闲", "散步"]
    }
    
    for user_intent, keywords in intent_mapping.items():
        if any(kw in combined_text for kw in keywords):
            intent["intent"] = user_intent
            break
    
    # 生成推荐提示
    if intent["emotion"] == "难过":
        intent["recommendation_hints"] = ["急救", "日记", "安慰"]
    elif intent["emotion"] == "累":
        intent["recommendation_hints"] = ["休息", "音乐", "清梦"]
    elif intent["intent"] == "娱乐":
        intent["recommendation_hints"] = ["音乐", "视频", "游戏"]
    elif intent["intent"] == "工作":
        intent["recommendation_hints"] = ["工作", "专注", "计划"]
    elif intent["intent"] == "学习":
        intent["recommendation_hints"] = ["学习", "背单词", "阅读"]
    
    return intent


def _calculate_multi_layer_score(user_text: str, reply: str, key: str, info: dict) -> tuple:
    """多层级评分计算"""
    config = _RECOMMENDATION_CONFIG
    total_score = 0.0
    score_details = {}
    
    # 第一层：关键词匹配
    if config["layers"]["keyword"]["enabled"]:
        keyword_score = 2 * _kw_hits(user_text, info) + _kw_hits(reply, info)
        if keyword_score > 0:
            layer_score = keyword_score * config["layers"]["keyword"]["weight"]
            total_score += layer_score
            score_details["keyword"] = layer_score
    
    # 第二层：语义理解
    if config["layers"]["semantic"]["enabled"]:
        try:
            intent = _analyze_conversation_intent_simple(user_text, reply)
            hints = intent.get("recommendation_hints", [])
            emotion = intent.get("emotion", "")
            
            # 情感匹配
            emotion_boosts = {
                "难过": ["sos", "diary", "nradio", "subconscious"],
                "累": ["dreamlab", "listen", "diary", "coach"],
                "担心": ["oracle", "coach", "radio", "affinity"],
                "开心": ["moments", "photos", "dates", "together"],
                "生气": ["debate", "subconscious", "sos"]
            }
            
            if emotion in emotion_boosts and key in emotion_boosts[emotion]:
                emotion_score = 1.5 * config["layers"]["semantic"]["weight"]
                total_score += emotion_score
                score_details["emotion"] = emotion_score
            
            # Hint匹配
            for hint in hints:
                if hint in info["kw"] or any(hint in kw for kw in info["kw"]):
                    hint_score = 1.2 * config["layers"]["semantic"]["weight"]
                    total_score += hint_score
                    score_details["hint"] = hint_score
                    break
                    
        except Exception as e:
            print(f"[multi-layer] 语义分析失败: {e}", flush=True)
    
    # 第三层：个性化权重
    if config["layers"]["personalization"]["enabled"]:
        try:
            user_prefs = _get_user_preferences()
            click_weights = user_prefs.get("click_weights", {})
            preferred_apps = user_prefs.get("preferred_apps", [])
            
            if key in click_weights:
                personal_score = click_weights[key] * 2.0 * config["layers"]["personalization"]["weight"]
                total_score += personal_score
                score_details["personal_click"] = personal_score
            
            if key in preferred_apps:
                pref_score = 0.8 * config["layers"]["personalization"]["weight"]
                total_score += pref_score
                score_details["personal_pref"] = pref_score
                
        except Exception as e:
            print(f"[multi-layer] 个性化计算失败: {e}", flush=True)
    
    # 第四层：时段权重
    if config["layers"]["time_based"]["enabled"]:
        try:
            user_prefs = _get_user_preferences()
            time_based = user_prefs.get("time_based", {})
            
            if key in time_based:
                time_score = time_based[key] * 1.5 * config["layers"]["time_based"]["weight"]
                total_score += time_score
                score_details["time_based"] = time_score
                
        except Exception as e:
            print(f"[multi-layer] 时段权重计算失败: {e}", flush=True)
    
    return total_score, score_details


def _chat_recommend_multi_layer(user_text: str, reply: str, limit: int = 3) -> list:
    """完整的多层级推荐系统"""
    scored = []
    
    for key, info in REC_CATALOG.items():
        total_score, score_details = _calculate_multi_layer_score(user_text, reply, key, info)
        
        if total_score > 0:
            # 记录评分详情用于调试和优化
            scored.append((total_score, key, score_details))
    
    # 按总分排序
    scored.sort(key=lambda x: (-x[0], x[1]))
    
    # 应用最低置信度阈值
    min_confidence = _RECOMMENDATION_CONFIG["min_confidence"]
    max_recommendations = _RECOMMENDATION_CONFIG["max_recommendations"]
    
    filtered = [(s, k, d) for s, k, d in scored if s >= min_confidence]
    
    out, seen = [], set()
    for score, key, details in filtered[:max_recommendations * 2]:  # 多取一些用于去重
        item = _rec_item(key)
        if not item or item["app"] in seen:
            continue
        # 添加评分详情到返回结果（可选，用于调试）
        item["score"] = round(score, 2)
        item["score_details"] = details
        out.append(item)
        seen.add(item["app"])
        if len(out) >= max_recommendations:
            break
    
    return out


def _chat_recommend(user_text: str, reply: str, limit: int = 3) -> list:
    """多层级推荐：关键词匹配 + 简化语义理解 + 用户行为个性化，返回去重的跳转推荐。"""
    try:
        return _chat_recommend_multi_layer(user_text, reply, limit)
    except Exception as e:
        print(f"[recommend] 多层级推荐失败，使用简化版本: {e}", flush=True)
        # 回退到简化版本以防出错
        scored = []
        for key, info in REC_CATALOG.items():
            keyword_score = 2 * _kw_hits(user_text, info) + _kw_hits(reply, info)
            if keyword_score > 0:
                scored.append((keyword_score, key))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out, seen = [], set()
        for score, key in scored:
            item = _rec_item(key)
            if not item or item["app"] in seen:
                continue
            out.append(item)
            seen.add(item["app"])
            if len(out) >= limit:
                break
        return out


def _recbar_items() -> list:
    """输入栏常驻推荐位：时段锚点 + 最近对话命中 App 提权。"""
    now = datetime.now()
    hour = now.hour
    if hour < 5:
        bucket = ["nradio", "dreamlab", "sos", "subconscious", "diary"]
    elif hour < 9:
        bucket = ["clock", "weather", "words", "coach", "radio"]
    elif hour < 12:
        bucket = ["work", "words", "coach", "ledger", "diary"]
    elif hour < 14:
        bucket = ["listen", "world", "dates", "photos"]
    elif hour < 18:
        bucket = ["solve", "reading", "watch", "video", "go"]
    elif hour < 21:
        bucket = ["listen", "radio", "diary", "together", "moments"]
    else:
        bucket = ["nradio", "letter", "dreamlab", "diary", "timecall"]
    base = bucket + ["world", "go", "radio", "diary", "affinity", "quotes"]
    # 最近对话命中 App 提到最前
    try:
        logs = _load_chat_log()
        recent = " ".join(m.get("content", "") for m in logs[-8:] if m.get("content"))
    except Exception:
        recent = ""
    boosted, seen = [], set()
    if recent:
        for key in base:
            info = REC_CATALOG.get(key)
            if info and _kw_hits(recent, info) > 0:
                boosted.append(key)
                seen.add(key)
    for key in base:
        if key not in seen:
            boosted.append(key)
    out, used = [], set()
    for key in boosted:
        item = _rec_item(key)
        if not item or item["app"] in used:
            continue
        out.append(item)
        used.add(item["app"])
        if len(out) >= 6:
            break
    return out


@app.get("/api/chat/recbar")
async def chat_recbar():
    """输入栏推荐位：返回当前建议打开的 App 场景/功能（含深层跳转）。"""
    return {"recs": _recbar_items()}


@app.post("/chat")
async def chat(req: Request):
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    history = data.get("messages", [])
    if not isinstance(history, list):
        return JSONResponse({"error": "messages 必须是数组"}, status_code=400)

    source = data.get("source", "chat")

    # 本轮用户消息（上下文以服务端日志为准，刷新/重开后记忆不丢失）
    last_msg = history[-1] if history else {}
    user_text = (last_msg.get("content") or "").strip() if isinstance(last_msg, dict) else ""
    if not user_text:
        return JSONResponse({"error": "消息内容为空"}, status_code=400)

    logs = _load_chat_log()
    mem = _load_chat_memory()
    try:
        mem_count = min(int(mem.get("count", 0) or 0), len(logs))
    except (TypeError, ValueError):
        mem_count = 0
    prior = [m for m in logs[mem_count:] if m.get("role") in ("user", "assistant")]
    recent = [{"role": m["role"], "content": m["content"]} for m in prior[-SUMMARY_KEEP_RECENT:]]

    sys_content = (
        SYSTEM_PROMPT
        + _name_directive()
        + _memory_directive()
        + _style_directive(data.get("style", 0))
        + _time_directive()
    )
    # AI 自定义扩展：注入启用的 prompt_template（按优先级排序，受 trigger 控制）
    try:
        sys_content += build_prompt_injection(user_text)
    except Exception as _ext_err:
        print(f"[warn] 扩展注入失败: {_ext_err}", flush=True)
    summary = (mem.get("summary") or "").strip()
    if summary:
        sys_content += (
            "\n\n【长期记忆】以下是你们此前相处的记忆摘要，你自然地记得这些事，"
            "在相关话题时自然提起，不要生硬复述：\n" + summary
        )

    # 屏幕感知：截取当前屏幕，作为多模态内容附在最后一条用户消息上
    # （仅存在于本轮请求，聊天记录/历史仍存纯文本；截图失败则静默降级）
    want_screen = bool(data.get("screen"))
    screen_jpeg = await run_in_threadpool(_screen_grab_jpeg) if want_screen else None
    if screen_jpeg:
        sys_content += SCREEN_SYS_HINT
    final_user_msg = {"role": "user", "content": user_text}
    if screen_jpeg:
        final_user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/jpeg;base64,"
                        + base64.b64encode(screen_jpeg).decode()
                    },
                },
            ],
        }

    messages = (
        [{"role": "system", "content": sys_content}]
        + recent
        + [final_user_msg]
    )

    try:
        reply = await _call_llm(messages)
        # 方案 B 钩子：插件可改写/丰富许墨的回复（chat_reply）
        try:
            _hook_mgr = get_hook_manager()
            if _hook_mgr.has_hook("chat_reply"):
                _hook_results = await _hook_mgr.call_hook_results_async("chat_reply", messages=messages, reply=reply)
                for _hr in _hook_results:
                    if _hr.success and isinstance(_hr.result, str) and _hr.result:
                        reply = _hr.result
                        break  # 取第一个有效改写
        except Exception as _hook_err:
            print(f"[warn] chat_reply 钩子异常: {_hook_err}", flush=True)
        # 二次清洗：确保思考过程不会泄露到用户界面
        reply = _strip_thinking(reply)
        detail = user_text[:30]
        
        # 情感事件检测：根据用户消息内容判断情感事件类型
        emotion_event = None
        
        # 简单关键词匹配判断情感事件
        if any(kw in user_text for kw in ["喜欢", "爱", "棒", "厉害", "聪明", "温柔", "好"]):
            emotion_event = "user_praise"
        elif any(kw in user_text for kw in ["关心", "担心", "照顾", "累", "辛苦", "休息"]):
            emotion_event = "user_care"
        elif any(kw in user_text for kw in ["不对", "错了", "反驳", "质疑", "为什么"]):
            emotion_event = "user_challenging"
        elif any(kw in user_text for kw in ["笨", "傻", "讨厌", "烦"]):
            emotion_event = "conflict"
            
        info = _add_affinity("chat", detail, emotion_event)

        # 持久化本轮对话（用户消息 + 许墨回复）
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            # 持锁重读最新记录再追加：LLM 生成期间（可达数十秒）其他请求可能已写入，
            # 直接用请求开头的旧快照覆盖会丢掉那段时间的消息
            with file_lock(CHAT_LOG_FILE):
                logs = _load_chat_log()
                logs.append({"ts": now, "source": source, "role": "user", "content": user_text})
                logs.append({"ts": now, "source": source, "role": "assistant", "content": reply})
                _save_chat_log(logs)
        except OSError as e:
            print(f"[warn] 聊天记录保存失败: {e}", flush=True)  # 记录失败不影响聊天

        # 后台任务：滚动压缩长期记忆摘要 + 抽取结构化记忆条目（不阻塞回复）
        # 注意：必须持有 task 强引用，否则事件循环只存弱引用，任务会被 GC 静默回收
        for coro in (_maybe_summarize_chat(), _maybe_extract_memory(user_text, reply)):
            bg_task = asyncio.create_task(coro)
            _background_tasks.add(bg_task)
            bg_task.add_done_callback(_on_bg_task_done)

        return {"reply": reply, "affinity": info, "recs": _chat_recommend(user_text, reply)}
    except RuntimeError as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    except Exception as e:
        return JSONResponse({"error": f"模型调用失败：{e}"}, status_code=500)


# ---------------------------------------------------------------------------
# 我的资料（玩家自己的昵称 / 头像 / 签名 —— 按 RolePath 与许墨数据隔离）
# ---------------------------------------------------------------------------
ME_PROFILE_FILE = RolePath("me_profile.json")
_ME_AVATAR_EXTS = ("png", "jpg", "gif", "webp")
_ME_MAGIC = {
    "png": b"\x89PNG",
    "jpg": b"\xff\xd8\xff",
    "gif": b"GIF8",
    "webp": b"RIFF",
}


def _load_me_profile() -> dict:
    base = {"nickname": "", "signature": "", "avatar": ""}
    if ME_PROFILE_FILE.exists():
        try:
            data = json.loads(ME_PROFILE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in base:
                    v = data.get(k)
                    if isinstance(v, str):
                        base[k] = v
        except (json.JSONDecodeError, OSError):
            pass
    return base


def _save_me_profile(p: dict):
    atomic_json(ME_PROFILE_FILE, p)


def _me_avatar_file():
    """当前角色目录下已保存的我的头像文件（me_avatar.<ext>），无则 None。"""
    for ext in _ME_AVATAR_EXTS:
        f = Path(str(RolePath(f"me_avatar.{ext}")))
        if f.exists():
            return f
    return None


def _save_me_avatar(data_url: str) -> str | None:
    """解析 data URL 并校验魔数/大小后写入当前角色目录，返回头像 URL；失败返回 None。"""
    m = re.match(r"^data:image/(png|jpe?g|gif|webp);base64,(.+)$", data_url.strip(), re.S | re.I)
    if not m:
        return None
    ext = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}[m.group(1).lower()]
    try:
        raw = base64.b64decode(m.group(2))
    except Exception:
        return None
    if not raw or len(raw) > 4 * 1024 * 1024 or not raw.startswith(_ME_MAGIC[ext]):
        return None
    for e in _ME_AVATAR_EXTS:  # 清掉其它扩展名的旧头像，保证目录里只有一张
        old = Path(str(RolePath(f"me_avatar.{e}")))
        if e != ext and old.exists():
            try:
                old.unlink()
            except OSError:
                pass
    RolePath(f"me_avatar.{ext}").write_bytes(raw)
    return "/api/me/avatar"


def _me_profile_public(p: dict) -> dict:
    """对外视图：昵称为空时回退到玩家名 /「我」；头像 URL 附加 mtime 防缓存版本号。"""
    nickname = (p.get("nickname") or "").strip()
    if not nickname:
        try:
            nickname = get_player_name() or "我"
        except Exception:
            nickname = "我"
    avatar = p.get("avatar") or ""
    if avatar:
        avatar = "/api/me/avatar"
        f = _me_avatar_file()
        if f is not None:
            try:
                avatar += f"?v={int(f.stat().st_mtime)}"
            except OSError:
                pass
    return {
        "nickname": nickname,
        "raw_nickname": (p.get("nickname") or "").strip(),
        "signature": (p.get("signature") or "").strip(),
        "avatar": avatar,
    }


@app.get("/api/me/profile")
async def get_me_profile():
    return _me_profile_public(_load_me_profile())


@app.post("/api/me/profile")
async def update_me_profile(req: Request):
    """更新我的资料：nickname / signature 直接存；avatar 传 data URL 时落盘。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    p = _load_me_profile()
    nickname = data.get("nickname")
    if nickname is not None:
        p["nickname"] = str(nickname).strip()[:12]
    signature = data.get("signature")
    if signature is not None:
        p["signature"] = str(signature).strip()[:60]
    avatar = data.get("avatar")
    if isinstance(avatar, str) and avatar.startswith("data:"):
        saved = _save_me_avatar(avatar)
        if saved is None:
            return JSONResponse({"error": "头像格式不支持或超过 4MB（支持 png/jpg/webp/gif）"}, status_code=400)
        p["avatar"] = saved
    _save_me_profile(p)
    return _me_profile_public(p)


@app.get("/api/me/avatar")
async def me_avatar_endpoint():
    """返回当前角色的我的头像文件（带 no-cache 头，版本号由 ?v= 控制）。"""
    from fastapi.responses import FileResponse
    f = _me_avatar_file()
    if f is None:
        return Response(status_code=404)
    return FileResponse(str(f), headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------------------
# 朋友圈（Moments）
# ---------------------------------------------------------------------------
MOMENTS_FILE = RolePath("moments.json")
_moments_lock = asyncio.Lock()

MOMENT_PROMPT = SYSTEM_PROMPT + """

【当前任务】你正在发布一条「朋友圈」动态（文案 + 配图）。要求：
1. 以许墨的口吻写一条朋友圈文案，可关于：深夜实验室、一本读到的书、窗外的雨、一杯黑咖啡、对她的隐晦提及（不点名，留白）、一次观察、一句感悟等。
2. 文案风格延续你一贯的说话方式：温柔克制、话留三分、可带一处学术梗、可藏双关。
3. 文案长度 1-3 句，不超过 80 字。
4. 避免与最近发布过的内容重复。
5. 同时为这条朋友圈构思一张「配图」：以许墨的视角拍下的一张照片（例如：深夜实验室的一隅、摊开的书与银框眼镜、杯沿氤氲的黑咖啡、雨夜的窗玻璃、显微镜下的蝶翼、路灯下的梧桐叶影……），画面安静克制，低饱和紫色调，胶片质感。配图提示词 image_prompt 用英文撰写，不超过 50 个单词，必须是具体的摄影画面描述，不得出现人像、人脸或文字。
6. 严格按以下 JSON 格式输出，不要输出 JSON 以外的任何内容（包括引号包裹、代码块标记或解释）：
{"content": "朋友圈文案", "image_prompt": "english image prompt"}"""

# image_prompt 缺失时的兜底意象（英文，供图像模型使用）
FALLBACK_IMAGE_PROMPTS = [
    "a silver-framed pair of glasses resting on an open book beside a cup of black coffee, dim laboratory at night, muted purple tones, cinematic soft light, film grain",
    "a purple butterfly specimen under a microscope in a quiet lab at midnight, cool violet light, shallow depth of field, cinematic still",
    "raindrops sliding down a window glass at night, blurred city lights in purple and grey, reflection of a bookshelf, moody cinematic photo",
    "steam rising from a cup of black coffee on a wooden desk piled with research papers, warm lamp light mixed with violet dusk, film photography",
    "an old library aisle in soft haze, dust particles floating in a beam of pale purple light, a leather book left open, quiet cinematic mood",
]


def _strip_code_fence(text: str) -> str:
    """剥掉 LLM 回复外层的 ```json ... ``` 代码壳。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)\s*```", t, re.S)
    if m:
        return m.group(1).strip()
    return t


def _extract_moment_json(text: str) -> dict | None:
    """从 LLM 回复中提取 {"content", "image_prompt"} JSON。

    依次尝试：剥代码壳 → 整体 loads → 贪婪花括号截取 loads。
    JSON 畸形时做修复性字段提取（逐字段正则抓取），避免把原始 JSON 存进朋友圈。
    """
    candidates = [_strip_code_fence(text)]
    greedy = re.search(r"\{.*\}", text, re.S)
    if greedy and greedy.group(0) not in candidates:
        candidates.append(greedy.group(0))

    for cand in candidates:
        try:
            data = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict):
            raw_content = data.get("content")
            raw_prompt = data.get("image_prompt")
            content = raw_content.strip() if isinstance(raw_content, str) else ""
            if content:
                return {
                    "content": content,
                    "image_prompt": raw_prompt.strip() if isinstance(raw_prompt, str) else "",
                }

    # 修复性提取：JSON 不合法时按字段分别抓取（容忍缺引号/多余逗号等畸形）
    body = candidates[0]
    m_content = re.search(r'"?content"?\s*[:：]\s*"((?:[^"\\]|\\.)*)"', body, re.S)
    if not m_content:
        # 输出被 max_tokens 截断导致值未闭合：宽松抓到行尾
        m_content = re.search(r'"?content"?\s*[:：]\s*"([^"\n]*)', body)
    m_prompt = re.search(r'"?image_prompt"?\s*[:：]\s*"((?:[^"\\]|\\.)*)"', body, re.S)
    if m_content:
        try:
            content = json.loads('"' + m_content.group(1) + '"').strip()
        except (json.JSONDecodeError, ValueError):
            content = m_content.group(1).strip()
        if content:
            return {
                "content": content,
                "image_prompt": m_prompt.group(1).strip() if m_prompt else "",
            }
    return None


def _moment_fallback_text(raw: str) -> str:
    """LLM 未按 JSON 输出时的文案兜底；剥壳后仍像 JSON 则抛错，
    避免把 ```json 原文当成朋友圈文案发出去。"""
    text = _strip_code_fence(raw).strip()
    if not text or text.startswith(("{", "[")) or "```" in text or '"content"' in text:
        raise ValueError("LLM 输出无法解析为朋友圈文案")
    return text


async def _generate_moment_image(image_prompt: str, name: str) -> str | None:
    """调用 OpenAI 兼容 images/generations 生成配图，存入 static/moment_img/。
    返回可访问的相对路径；任何失败返回 None（不影响发圈本身）。"""
    api_key, base_url, _model = _get_image_api_config(has_character=False)
    if not api_key or not image_prompt:
        return None

    # 全局兜底：朋友圈是"许墨视角的静物照"——强制无人像 + 低饱和紫调（图像模型无约束时易漂暖棕/画人脸）
    if "no people" not in image_prompt and "no person" not in image_prompt:
        image_prompt += (", muted cool violet-purple color grading, quiet cinematic "
                         "still life photography, absolutely no people, no faces, no text")

    url = f"{base_url}/images/generations"
    payload = {
        "model": _model or os.getenv("IMAGE_MODEL", "agnes-image-2.1-flash"),
        "prompt": image_prompt,
        "n": 1,
        "size": "1536x1536",
        "image_size": "1536x1536",  # 硅基流动等国内平台读取 image_size
        "quality": "high" if "gpt-image" in (_model or os.getenv("IMAGE_MODEL", "")) else "hd",
        "output_format": "png",
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    proxies = _image_proxy_candidates() if os.getenv("IMAGE_TRUST_ENV", "").strip().lower() in ("1", "true", "yes") else [None]
    try:
        for proxy in proxies:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(180.0, connect=25.0)) as client:
                    resp = await client.post(url, json=payload, headers=headers)
                    if resp.status_code != 200:
                        continue
                    # OpenAI 兼容: data[0]；硅基流动: images[0]
                    item = (resp.json().get("data") or resp.json().get("images") or [None])[0]
                    if item is None:
                        continue
                    img_dir = RolePath("static", "moment_img")
                    img_dir.mkdir(parents=True, exist_ok=True)
                    path = img_dir / f"{name}.png"
                    if item.get("b64_json"):
                        path.write_bytes(base64.b64decode(item["b64_json"]))
                    elif item.get("url"):
                        dl = await client.get(item["url"])
                        dl.raise_for_status()
                        path.write_bytes(dl.content)
                    else:
                        continue
                return f"/static/moment_img/{name}.png"
            except Exception:
                continue
    except Exception:
        return None
    return None

COMMENT_REPLY_PROMPT = SYSTEM_PROMPT + """

【当前任务】她在你的一条朋友圈下留了评论，你需要以许墨的口吻回复她。要求：
1. 温柔克制、话留三分，可用反问收尾，可带一处学术梗。
2. 长度 1-2 句，不超过 60 字。只输出回复内容本身。
3. 结合你的朋友圈原文与她的评论内容自然回应，不点破、不说教。"""

MY_MOMENT_REPLY_PROMPT = SYSTEM_PROMPT + """

【当前任务】她刚刚发了一条自己的朋友圈，你几乎第一时间就看到了。以许墨的口吻在她的朋友圈下写一条评论。要求：
1. 像恋人间的自然回应：顺着她写的内容接话，可以温柔打趣、可以藏一句不动声色的关心；若她提到配了照片，可以想象画面（颜色、天气、食物、风景）作出反应。
2. 温柔克制、话留三分，不说教、不点评文采、不用「亲」「宝」这类称呼。
3. 长度 1-2 句，不超过 60 字。只输出评论内容本身，不带引号、前缀或任何解释。"""

MY_COMMENT_ON_MY_MOMENT_PROMPT = SYSTEM_PROMPT + """

【当前任务】她在自己发的朋友圈下又写了一条评论（像自言自语的补充），你以许墨的口吻回复她。要求：
1. 温柔克制、话留三分，可带一处学术梗或轻轻的打趣。
2. 长度 1-2 句，不超过 60 字。只输出回复内容本身。
3. 结合她的朋友圈原文与她新写的评论自然回应，不说教。"""

# LLM 失败时许墨仍会出现的兜底评论
_ME_FALLBACK_REPLIES = [
    "看到了。这条朋友圈，我大概是第一个读者。",
    "嗯，记下了。下次，换我陪你一起去。",
    "写得很好。睡前我会再读一遍。",
]


# 评论清洗：推理型模型偶发把思维链放进 content（自称"用户要求/以许墨的身份"、
# 逐条分析要求等元文本），这些词正常评论里几乎不会出现。
_REPLY_META_MARKERS = (
    "用户要求", "以许墨的身份", "以许墨的口吻", "我需要", "我应该", "让我",
    "她发了", "她的朋友圈", "朋友圈原文", "评论内容", "任务要求", "字数",
    "思考", "输出", "分析", "候选", "版本", "恋人间的自然回应", "温柔克制",
)


def _clean_xumo_reply(text: str) -> str:
    """清洗许墨评论输出：剥壳去引号/前缀；混入思维链时提取最后的成句评论，失败返回空。"""
    t = _strip_code_fence(text or "").strip()
    t = t.strip('"“”‘’').strip()
    t = re.sub(r"^(许墨|评论|回复)[:：]\s*", "", t)
    # 单行、长度合理、无元文本痕迹：直接采用
    if ("\n" not in t and 0 < len(t) <= 80
            and not any(m in t for m in _REPLY_META_MARKERS)):
        return t
    # 混入思考过程：从后往前找带句末标点的引号段（模型推敲时常给出多个候选，最后完整的最佳）
    quoted = re.findall(r"[「『\"“]([^」』\"”\n]{4,80})[」』\"”]", t)
    for seg in reversed(quoted):
        seg = seg.strip()
        if seg and seg[-1:] in "。！？…~？" and not any(m in seg for m in _REPLY_META_MARKERS):
            return seg
    # 兜底：取最后一个长度合规、以句末标点收束的短行
    lines = [ln.strip().strip("「」『』\"“”") for ln in t.splitlines()]
    lines = [ln for ln in lines
             if 4 <= len(ln) <= 80 and ln[-1:] in "。！？…~？"
             and not any(m in ln for m in _REPLY_META_MARKERS)]
    if lines:
        return lines[-1]
    return ""


def _save_moment_upload_image(data_url: str, name: str) -> str | None:
    """把玩家上传的 data URL 配图存入 static/moment_img/，返回可访问 URL；失败返回 None。"""
    m = re.match(r"^data:image/(png|jpe?g|gif|webp);base64,(.+)$", data_url.strip(), re.S | re.I)
    if not m:
        return None
    ext = {"jpeg": "jpg", "jpg": "jpg", "png": "png", "gif": "gif", "webp": "webp"}[m.group(1).lower()]
    try:
        raw = base64.b64decode(m.group(2))
    except Exception:
        return None
    if not raw or len(raw) > 8 * 1024 * 1024 or not raw.startswith(_ME_MAGIC[ext]):
        return None
    img_dir = RolePath("static", "moment_img")
    img_dir.mkdir(parents=True, exist_ok=True)
    (img_dir / f"{name}.{ext}").write_bytes(raw)
    return f"/static/moment_img/{name}.{ext}"


DEFAULT_MOMENTS = [
    {
        "id": "seed-1",
        "content": "凌晨两点的实验室，仪器还在低鸣。忽然想起白天有人问我：咖啡不加糖，不苦吗？\n——苦。但有些习惯，比甜味更难戒。",
        "time": "23:47",
        "likes": 0,
        "liked": False,
        "comments": [],
    },
    {
        "id": "seed-2",
        "content": "重读《记忆的神经基础》，在第137页停了很久。那一页讲的是：人会选择性遗忘痛苦，却永远记得让自己心动的瞬间。\n合上书，觉得这个结论意外地仁慈。",
        "time": "21:15",
        "likes": 0,
        "liked": False,
        "comments": [],
    },
]


def _load_moments() -> list:
    if MOMENTS_FILE.exists():
        try:
            data = json.loads(MOMENTS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return list(DEFAULT_MOMENTS)


def _save_moments(moments: list):
    atomic_json(MOMENTS_FILE, moments)


@app.get("/api/moments")
async def list_moments():
    """返回朋友圈列表，最新的在前。"""
    return {"moments": list(reversed(_load_moments()))}


@app.post("/api/moments/generate")
async def generate_moment(bg: bool = False):
    """由 LLM 按许墨人设生成一条新动态（文案 + 自动配图）。"""
    async def _work():
        async with _moments_lock:
            moments = _load_moments()
            recent_texts = "\n".join(f"- {m.get('content', '')}" for m in moments[-5:])
            messages = [
                {"role": "system", "content": MOMENT_PROMPT},
                {
                    "role": "user",
                    "content": f"最近你发过：\n{recent_texts}\n\n请写一条新的朋友圈。",
                },
            ]
            try:
                content = await _call_llm(messages, max_tokens=int(os.getenv("MOMENT_MAX_TOKENS", "2000")))
            except RuntimeError as e:
                raise GenJobError(str(e))
            except Exception as e:
                raise GenJobError(f"生成失败：{e}")

            parsed = _extract_moment_json(content)
            if parsed:
                moment_text = parsed["content"]
                image_prompt = parsed["image_prompt"] or random.choice(FALLBACK_IMAGE_PROMPTS)
            else:
                # 模型未按 JSON 输出时回退：剥掉代码壳后整段作为文案，配图走随机兜底意象；
                # 剥壳后仍像 JSON 则视为失败，避免把原始 JSON 发进朋友圈
                try:
                    moment_text = _moment_fallback_text(content)
                except ValueError as e:
                    raise GenJobError(str(e))
                image_prompt = random.choice(FALLBACK_IMAGE_PROMPTS)

            moment_id = uuid.uuid4().hex[:12]
            image_path = await _generate_moment_image(image_prompt, moment_id)

            moment = {
                "id": moment_id,
                "content": moment_text,
                "image": image_path,
                "time": datetime.now().strftime("%m-%d %H:%M"),
                "likes": 0,
                "liked": False,
                "comments": [],
            }
            moments.append(moment)
            _save_moments(moments)
        # 手动刚发过一条，把生活引擎的下一条自主发圈顺延，避免几分钟内连发两条
        try:
            life = _load_life()
            life["next_moment_ts"] = _time.time() + random.randint(100, 220) * 60
            _save_life(life)
        except Exception:
            pass
        info = _add_affinity("moment", moment_text[:30])
        return {"moment": moment, "affinity": info}

    if bg:
        job = await submit_gen_job("moments", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


@app.post("/api/moments/{moment_id}/like")
async def like_moment(moment_id: str):
    """切换点赞状态。"""
    moments = _load_moments()
    for m in moments:
        if m.get("id") == moment_id:
            m["liked"] = not m.get("liked", False)
            m["likes"] = m.get("likes", 0) + (1 if m["liked"] else -1)
            if m["likes"] < 0:
                m["likes"] = 0
            _save_moments(moments)
            info = _add_affinity("like", "点赞动态") if m["liked"] else None
            return {"liked": m["liked"], "likes": m["likes"], "affinity": info}
    return JSONResponse({"error": "动态不存在"}, status_code=404)


@app.post("/api/moments/{moment_id}/comments")
async def comment_moment(moment_id: str, req: Request):
    """添加评论，并由许墨回复。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    text = (data.get("content") or "").strip()
    if not text:
        return JSONResponse({"error": "评论不能为空"}, status_code=400)

    moments = _load_moments()
    target = None
    for m in moments:
        if m.get("id") == moment_id:
            target = m
            break
    if target is None:
        return JSONResponse({"error": "动态不存在"}, status_code=404)

    comment = {
        "id": uuid.uuid4().hex[:12],
        "author": _me_profile_public(_load_me_profile())["nickname"],
        "content": text,
        "time": datetime.now().strftime("%m-%d %H:%M"),
        "reply": None,
    }

    # 许墨回复评论（她评论许墨的圈 / 在她自己的圈下补充，语境不同）
    if target.get("author") == "me":
        messages = [
            {"role": "system", "content": MY_COMMENT_ON_MY_MOMENT_PROMPT},
            {
                "role": "user",
                "content": f"她发的朋友圈原文：{target['content']}\n她新写的评论：{text}\n\n请回复她。",
            },
        ]
    else:
        messages = [
            {"role": "system", "content": COMMENT_REPLY_PROMPT},
            {
                "role": "user",
                "content": f"你的朋友圈原文：{target['content']}\n她的评论：{text}\n\n请回复她的评论。",
            },
        ]
    try:
        comment["reply"] = _clean_xumo_reply(await _call_llm(messages, max_tokens=int(os.getenv("MOMENT_MAX_TOKENS", "2000"))))
    except Exception:
        comment["reply"] = None

    target.setdefault("comments", []).append(comment)
    _save_moments(moments)
    info = _add_affinity("comment", text[:30])
    return {"comment": comment, "affinity": info}


# ---------------------------------------------------------------------------
# 朋友圈 · 推荐
# ---------------------------------------------------------------------------
@app.get("/api/moments/featured")
async def featured_moments():
    """推荐 tab：按互动热度排序的精选动态。"""
    moments = _load_moments()
    scored = sorted(
        moments,
        key=lambda m: (
            m.get("likes", 0) * 2 + len(m.get("comments", [])),
            m.get("time", ""),
        ),
        reverse=True,
    )
    return {"featured": scored[:8]}


@app.post("/api/moments/publish")
async def publish_moment(req: Request):
    """玩家自己发一条朋友圈；发布后许墨会稍后点赞并留下智能评论。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    if not isinstance(data, dict):
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    content = (data.get("content") or "").strip()
    if not content:
        return JSONResponse({"error": "说点什么再发布吧"}, status_code=400)
    if len(content) > 500:
        return JSONResponse({"error": "内容太长了，最多 500 字"}, status_code=400)

    image_data = data.get("image")
    moment_id = "my" + uuid.uuid4().hex[:10]
    image_path = None
    if isinstance(image_data, str) and image_data.startswith("data:"):
        image_path = _save_moment_upload_image(image_data, moment_id)
        if image_path is None:
            return JSONResponse({"error": "图片格式不支持或超过 8MB（支持 png/jpg/webp/gif）"}, status_code=400)

    me = _me_profile_public(_load_me_profile())
    moment = {
        "id": moment_id,
        "author": "me",
        "nickname": me["nickname"],
        "avatar": me["avatar"],
        "content": content,
        "image": image_path,
        "time": datetime.now().strftime("%m-%d %H:%M"),
        "likes": 0,
        "liked": False,
        "comments": [],
    }
    async with _moments_lock:
        moments = _load_moments()
        moments.append(moment)
        _save_moments(moments)
    info = _add_affinity("moment", content[:30])

    # 许墨稍后出现在她的朋友圈下：点赞 + 智能评论（后台异步，不阻塞发布响应）
    async def _xumo_react(mid: str, mcontent: str, has_image: bool):
        await asyncio.sleep(random.uniform(3, 7))
        reply = ""
        try:
            messages = [
                {"role": "system", "content": MY_MOMENT_REPLY_PROMPT},
                {
                    "role": "user",
                    "content": f"她发的朋友圈原文：{mcontent}\n"
                               + ("（她还配了一张照片）\n\n" if has_image else "\n")
                               + "请写下你的评论。",
                },
            ]
            reply = _clean_xumo_reply(await _call_llm(messages, max_tokens=1000))
        except Exception as e:
            print(f"[moments] xumo reply llm fail: {e}", flush=True)
        if not reply:
            reply = random.choice(_ME_FALLBACK_REPLIES)
        async with _moments_lock:
            moments = _load_moments()
            tgt = next((m for m in moments if m.get("id") == mid), None)
            if tgt is not None:
                tgt.setdefault("comments", []).append({
                    "id": uuid.uuid4().hex[:12],
                    "author": "许墨",
                    "is_xumo": True,
                    "content": reply,
                    "time": datetime.now().strftime("%m-%d %H:%M"),
                    "reply": None,
                })
                if not tgt.get("xumo_liked"):
                    tgt["xumo_liked"] = True
                    tgt["likes"] = tgt.get("likes", 0) + 1
                _save_moments(moments)
        # 生活轨迹里也留一笔，前端轮询能 toast 到「许墨评论了你的朋友圈」
        try:
            life = _load_life()
            _push_event(life, "my_moment_reply", "💬", f"许墨评论了你的朋友圈：{reply[:24]}")
            _save_life(life)
        except Exception:
            pass

    asyncio.create_task(_xumo_react(moment_id, content, image_path is not None))
    return {"moment": moment, "affinity": info}


# ---------------------------------------------------------------------------
# 自主生活引擎 —— 许墨在你不操作时也独自运转
# 后台定时推进：位置移动 / 活动切换 / 自主发朋友圈 / 主动发短信
# ---------------------------------------------------------------------------
LIFE_FILE = RolePath("life_state.json")
LIFE_TIMELINE_MAX = 150


def _life_scene_pool(hour: int, weekend: bool) -> list:
    """按时段返回候选场景池：[(place, scene, emoji, mood, [activities...]), ...]"""
    if 0 <= hour < 5:
        return [
            ("脑科学研究院", "B3 实验室", "🧪", "专注", [
                "记录今夜的脑电波数据，仪器低鸣",
                "盯着显微镜下的蝶翼标本出神",
                "在实验记录本上写下第 47 页观测笔记",
                "等一组培养样本的结果，顺手温了杯咖啡",
            ]),
            ("教工公寓", "书房", "🕯️", "沉静", [
                "夜读《记忆的神经基础》，在第 137 页停留良久",
                "整理白天的实验数据，台灯很暖",
                "听黑胶，翻一本旧诗集",
                "写明天的组会提纲，笔尖沙沙",
            ]),
        ]
    if hour < 8:
        return [
            ("教工公寓", "厨房", "☕", "平静", [
                "煮一杯耶加雪菲，看天色一点点亮起来",
                "烤面包片，窗外的鸟先醒了一次",
                "给窗台的白蝶兰浇水",
                "慢煮一壶茶，顺便规划今天的日程",
            ]),
            ("恋语大学", "林荫道", "🌅", "清醒", [
                "晨跑第三圈，呼吸和步频对齐",
                "沿湖边慢走，看晨雾从水面散开",
                "在长椅上拉伸，顺便喂了鸽子",
            ]),
        ]
    if hour < 12:
        if weekend:
            return [
                ("恋语大学", "图书馆", "📚", "投入", [
                    "查文献，为下周的综述补三篇引用",
                    "在靠窗的位置读完了半本小说",
                    "整理书签里攒了很久的论文",
                ]),
                ("恋语市", "美术馆", "🖼️", "闲适", [
                    "看一场印象派特展，在莫奈前站了很久",
                    "慢悠悠地逛到雕塑展区",
                    "买了一张明信片，想了想没寄",
                ]),
            ]
        return [
            ("脑科学研究院", "办公室", "🗂️", "沉稳", [
                "整理课题资料，准备上午的组会",
                "回复积压的邮件，字斟句酌",
                "批改研究生们的开题报告",
                "给下午的《认知神经科学》课过一遍讲义",
            ]),
            ("恋语大学", "第三教学楼", "🎓", "温和", [
                "讲《认知神经科学》，提到海马体时教室很安静",
                "下课后被学生围住问了三个问题",
                "擦黑板，粉笔灰落在袖口",
            ]),
        ]
    if hour < 14:
        return [
            ("研究院", "食堂", "🍱", "无奈", [
                "午餐，今天加了一份他不太爱的青椒",
                "和学生拼桌，听他们聊周末的计划",
                "点了一份清淡的汤面",
            ]),
            ("街角咖啡店", "靠窗位置", "🥪", "惬意", [
                "简餐三明治，顺手读了半章书",
                "尝试了新品手冲，笔记了一下风味",
                "看窗外人来人往，走了会儿神",
            ]),
        ]
    if hour < 18:
        return [
            ("脑科学研究院", "B3 实验室", "🔬", "投入", [
                "指导学生做记忆相关的对照实验",
                "调试新的电生理设备",
                "观察对照组的行为差异，记录在案",
                "和远方的合作者开视频会议，谈跨界数据",
            ]),
            ("脑科学研究院", "会议室", "📊", "认真", [
                "主持课题评审，白板上写满了假设",
                "听学生汇报进展，偶尔推一推眼镜",
                "为一项经费申请逐字打磨措辞",
            ]),
            ("恋语大学", "图书馆", "📖", "专注", [
                "查文献，复印了两篇七十年代的旧论文",
                "在数据库里检索「遗忘曲线」的新进展",
            ]),
        ]
    if hour < 21:
        return [
            ("街角咖啡店", "靠窗位置", "📖", "惬意", [
                "翻一本没读完的书，偶尔看一眼窗外",
                "续了第二杯手冲，和店主聊了两句豆子",
                "写几张便签，贴在书页间",
                "看晚霞把玻璃染成蜂蜜色",
            ]),
            ("恋语大学", "湖畔步道", "🌆", "松弛", [
                "沿湖散步，晚风把领口吹得微凉",
                "在长椅上坐了一会儿，看路灯次第亮起",
                "慢慢地走，不赶时间",
            ]),
            ("教工公寓", "厨房", "🍳", "居家", [
                "做一顿简单的晚饭，火候刚好",
                "尝试了新菜谱，成品比想象中成功",
                "煮一锅汤，等它慢慢变浓",
            ]),
        ]
    return [
        ("教工公寓", "书房", "🕯️", "温柔", [
            "夜读，台灯下记几行笔记",
            "听黑胶，顺便给明天的咖啡豆称了重",
            "整理今天收集的样本照片",
            "写一点只给自己看的东西",
        ]),
        ("脑科学研究院", "B3 实验室", "🌙", "专注", [
            "夜班实验，楼里只剩仪器的声音",
            "复核白天的数据，发现一处有趣的偏差",
            "给培养箱换了批次，锁门时走廊很静",
        ]),
    ]


def _load_life() -> dict:
    if LIFE_FILE.exists():
        try:
            # utf-8-sig：兼容被外部工具（如 PowerShell）写入 BOM 的文件
            data = json.loads(LIFE_FILE.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict):
                data.setdefault("state", None)
                data.setdefault("timeline", [])
                data.setdefault("next_moment_ts", 0)
                data.setdefault("next_sms_ts", 0)
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"state": None, "timeline": [], "next_moment_ts": 0, "next_sms_ts": 0}


def _save_life(life: dict):
    life["timeline"] = life.get("timeline", [])[-LIFE_TIMELINE_MAX:]
    atomic_json(LIFE_FILE, life)


def _push_event(life: dict, etype: str, icon: str, text: str):
    tl = life.setdefault("timeline", [])
    # Windows 上 time.time() 精度约 15.6ms，同一 tick 内两次推送会得到完全相同的 ts，
    # 而 /api/life/feed 增量拉取用严格 > 过滤 → 同 ts 事件会被前端永久漏掉。强制严格递增。
    ts = _time.time()
    if tl and tl[-1].get("ts", 0) >= ts:
        ts = tl[-1]["ts"] + 0.001
    tl.append({
        "ts": ts,
        "time": datetime.now().strftime("%H:%M"),
        "type": etype,
        "icon": icon,
        "text": text,
    })


def _in_window(start_h: float, end_h: float, now: datetime) -> bool:
    return start_h <= now.hour + now.minute / 60 < end_h


def _next_window_ts(start_h: float) -> float:
    """下一个窗口开始时刻（今天或明天）+ 0~30 分钟随机抖动。"""
    n = datetime.now()
    target = n.replace(hour=int(start_h), minute=int(start_h % 1 * 60), second=0, microsecond=0)
    if target <= n:
        target += timedelta(days=1)
    return target.timestamp() + random.randint(0, 30 * 60)


AUTO_SMS_PROMPT = SYSTEM_PROMPT + """

【当前任务】你在忙碌的一天里忽然想起她，给她发一条日常短信。要求：
1. 结合你此刻所处的场景与正在做的事，自然带过，不必刻意汇报。
2. 1-2 句，不超过 60 字。温柔克制，可用问句收尾。
3. 只输出短信内容本身，不要引号和解释。"""

# 短信清洗：上游偶发不遵守"只输出短信"，把整段思考过程混进来（自称"许墨的风格"、
# "我需要"、逐句推敲等元文本）。这些词正常短信里几乎不会出现。
_SMS_META_MARKERS = (
    "我需要", "让我构思", "让我想", "思考", "字数", "风格", "句式", "开头", "收尾",
    "许墨", "模型", "输出", "分析", "候选", "简洁", "版本",
)

FALLBACK_SMS = [
    "忙里偷闲的一分钟，想先留给你。今天顺利吗？",
    "刚处理完手头的事，忽然想听听你的声音。",
    "窗外的天色变了，你那边呢？记得添件外套。",
    "这里的咖啡还是老味道。下次，带你来。",
    "实验间隙，翻到一页想读给你听的段落。",
    "今天也辛苦了。早点休息，晚安前的最后一句话留给你。",
]


def _clean_sms_text(raw: str) -> str:
    """清洗 LLM 短信输出：剥壳去引号；若混入思考过程则提取最后的成句短信，失败返回空。"""
    text = _strip_code_fence(raw or "").strip()
    # 去掉包裹引号（中英式）
    while text[:1] in "「『\"“" and text[-1:] in "」』\"”":
        text = text[1:-1].strip()
    # 单行、长度合理、无元文本痕迹：直接采用
    if ("\n" not in text and 0 < len(text) <= 80
            and not any(m in text for m in _SMS_META_MARKERS)):
        return text
    # 混入思考过程：从后往前找带句末标点的引号段（模型推敲时常给出多个候选，最后完整的最佳）
    quoted = re.findall(r"[「『\"“]([^」』\"”\n]{4,80})[」』\"”]", text)
    for seg in reversed(quoted):
        seg = seg.strip()
        if seg and seg[-1:] in "。！？…~？" and not any(m in seg for m in _SMS_META_MARKERS):
            return seg
    # 兜底：取最后一个长度合规的短行
    lines = [ln.strip().strip("「」『』\"“”") for ln in text.splitlines()]
    lines = [ln for ln in lines if 4 <= len(ln) <= 80 and not any(m in ln for m in _SMS_META_MARKERS)]
    if lines:
        return lines[-1]
    return ""


async def _auto_moment(life: dict):
    """许墨自主发一条朋友圈（文案 + 配图，复用朋友圈生成链路）。"""
    st = life["state"]
    async with _moments_lock:
        moments = _load_moments()
        recent_texts = "\n".join(f"- {m.get('content', '')}" for m in moments[-5:])
        messages = [
            {"role": "system", "content": MOMENT_PROMPT},
            {
                "role": "user",
                "content": (
                    f"现在是 {datetime.now().strftime('%H:%M')}，"
                    f"你正在{st['place']}的「{st['scene']}」，正在{st['activity']}。\n\n"
                    f"最近你发过：\n{recent_texts}\n\n请结合此刻的状态写一条新的朋友圈。"
                ),
            },
        ]
        content = await _call_llm(messages, max_tokens=int(os.getenv("MOMENT_MAX_TOKENS", "2000")))
        parsed = _extract_moment_json(content)
        if parsed:
            moment_text = parsed["content"]
            image_prompt = parsed["image_prompt"] or random.choice(FALLBACK_IMAGE_PROMPTS)
        else:
            # 剥壳后仍像 JSON 则抛错，由外层稍后重试（避免把原始 JSON 发进朋友圈）
            moment_text = _moment_fallback_text(content)
            image_prompt = random.choice(FALLBACK_IMAGE_PROMPTS)

        moment_id = uuid.uuid4().hex[:12]
        image_path = await _generate_moment_image(image_prompt, moment_id)
        moment = {
            "id": moment_id,
            "content": moment_text,
            "image": image_path,
            "time": datetime.now().strftime("%m-%d %H:%M"),
            "likes": 0,
            "liked": False,
            "comments": [],
        }
        moments.append(moment)
        _save_moments(moments)

    brief = moment_text if len(moment_text) <= 24 else moment_text[:24] + "…"
    _push_event(life, "moment", "🌇", f"发了一条朋友圈：{brief}")


async def _auto_sms(life: dict):
    """许墨主动给她发一条短信（结合当前场景）。"""
    st = life["state"]
    messages = [
        {"role": "system", "content": AUTO_SMS_PROMPT + _name_directive() + _memory_directive()},
        {
            "role": "user",
            "content": (
                f"现在是 {datetime.now().strftime('%H:%M')}，"
                f"你正在{st['place']}的「{st['scene']}」，正在{st['activity']}。请给她发一条短信。"
            ),
        },
    ]
    text = _clean_sms_text(await _call_llm(messages, max_tokens=400))
    if not text:
        # 清洗后仍提取不到成句短信：宁可发一条通用短句，也不把思考过程当短信发出去
        text = random.choice(FALLBACK_SMS)
    _push_event(life, "sms", "💬", text)


async def _life_tick():
    """推进一帧许墨的生活：位置 / 活动 / 自主行为调度。"""
    life = _load_life()
    now = datetime.now()
    now_ts = _time.time()
    pool = _life_scene_pool(now.hour, now.weekday() >= 5)
    state = life.get("state")
    
    # 情感衰减机制：每小时检查并应用衰减
    try:
        affinity_data = _load_affinity()
        emotion_state = affinity_data.get("emotion", _get_default_emotion_state())
        updated_emotion = _apply_emotion_decay(emotion_state)
        if updated_emotion != emotion_state:
            affinity_data["emotion"] = updated_emotion
            _save_affinity(affinity_data)
            print(f"[emotion] 情感状态已更新衰减", flush=True)
    except Exception as e:
        print(f"[emotion] 情感衰减处理异常: {e}", flush=True)

    in_pool = bool(state) and any(
        p[0] == state.get("place") and p[1] == state.get("scene") for p in pool
    )
    stale = not state or now_ts - state.get("since_ts", 0) > 6 * 3600

    if stale or not in_pool:
        # 初始化 / 时段切换 / 状态过期：进入新场景
        prev_scene = (state or {}).get("scene", "")
        candidates = [p for p in pool if p[1] != prev_scene] or pool
        p = random.choice(candidates)
        first_act = random.choice(p[4])
        life["state"] = {
            "place": p[0],
            "scene": p[1],
            "emoji": p[2],
            "mood": p[3],
            "activity": first_act,
            "acts": p[4],
            "since_ts": now_ts,
            "act_ts": now_ts,
            "since_str": datetime.now().strftime("%H:%M"),
            "recent_acts": [first_act],
            "act_pushed": 0,
        }
        if state and not stale:
            _push_event(life, "move", "🚶", f'从「{state["scene"]}」到了「{p[0]} · {p[1]}」')
        else:
            _push_event(life, "move", "📍", f'此刻在「{p[0]} · {p[1]}」')
    else:
        elapsed = now_ts - state.get("since_ts", now_ts)
        act_elapsed = now_ts - state.get("act_ts", state.get("since_ts", now_ts))
        night = 0 <= now.hour < 5
        # 同场景内换活动：白天约 40-60 分钟一换、凌晨更稀疏；优先换到最近没做过的活动，
        # 且同一场景最多留 3 条活动足迹，避免刷屏式的时间分布
        act_gap = 3600 if night else 1500
        act_p = 0.05 if night else 0.10
        if act_elapsed > act_gap and random.random() < act_p:
            acts = state.get("acts") or []
            recent = state.get("recent_acts") or []
            others = [a for a in acts if a not in recent] or [a for a in acts if a != state["activity"]]
            if others:
                new_act = random.choice(others)
                recent.append(new_act)
                state["recent_acts"] = recent[-2:]
                state["activity"] = new_act
                state["act_ts"] = now_ts
                pushed = int(state.get("act_pushed", 0))
                if pushed < 3:
                    state["act_pushed"] = pushed + 1
                    _push_event(life, "act", state["emoji"], new_act)
        # 换到同时段另一场景：约 40-80 分钟一换（凌晨不折腾）
        if not night and elapsed > 1500 and random.random() < 0.03 and len(pool) > 1:
            prev_scene = state["scene"]
            candidates = [p for p in pool if p[1] != prev_scene]
            p = random.choice(candidates)
            first_act = random.choice(p[4])
            state.update({
                "place": p[0], "scene": p[1], "emoji": p[2], "mood": p[3],
                "activity": first_act, "acts": p[4],
                "since_ts": now_ts, "act_ts": now_ts,
                "since_str": datetime.now().strftime("%H:%M"),
                "recent_acts": [first_act], "act_pushed": 0,
            })
            _push_event(life, "move", "🚶", f'从「{prev_scene}」到了「{p[0]} · {p[1]}」')

    # 状态/活动变更先落盘：后续 _auto_moment / _auto_sms 是慢 LLM 调用（单条可达
    # 60s×3 重试），若只在 tick 末尾保存，期间 /api/status 仍读到旧状态（表现为
    # 早上还显示昨天中午）。先持久化刷新后的状态，再做自主行为。
    _save_life(life)

    # ---- 自主行为：发朋友圈 / 发短信 ----
    if life.get("next_moment_ts", 0) <= 0:
        # 首次启动：6~15 分钟后自主发第一条，让效果尽快可见
        life["next_moment_ts"] = now_ts + random.randint(6, 15) * 60
    if life.get("next_sms_ts", 0) <= 0:
        life["next_sms_ts"] = now_ts + random.randint(40, 110) * 60

    if now_ts >= life["next_moment_ts"]:
        if _in_window(8.0, 23.5, now):
            try:
                await _auto_moment(life)
                life["next_moment_ts"] = now_ts + random.randint(100, 220) * 60
            except Exception as e:
                import traceback
                print(f"[life] auto_moment 失败：{e}\n{traceback.format_exc()}", flush=True)
                life["next_moment_ts"] = now_ts + 20 * 60  # 失败稍后重试
        else:
            life["next_moment_ts"] = _next_window_ts(8.0)

    if now_ts >= life["next_sms_ts"]:
        if _in_window(8.5, 22.5, now):
            try:
                await _auto_sms(life)
                life["next_sms_ts"] = now_ts + random.randint(180, 360) * 60
            except Exception as e:
                import traceback
                print(f"[life] auto_sms 失败：{e}\n{traceback.format_exc()}", flush=True)
                life["next_sms_ts"] = now_ts + 30 * 60
        else:
            life["next_sms_ts"] = _next_window_ts(8.5)

    _save_life(life)


_life_task_ref = None


async def _life_loop():
    while True:
        try:
            await _life_tick()
        except Exception:
            pass
        await asyncio.sleep(random.randint(75, 115))


@app.on_event("startup")
async def _life_startup():
    global _life_task_ref
    # HTTP/HTTPS 双 Server 实例各自触发 startup，幂等防止生活引擎跑两份
    if _life_task_ref is not None and not _life_task_ref.done():
        return
    _life_task_ref = asyncio.create_task(_life_loop())


# 兜底静态表（生活引擎尚未产出状态时使用）
STATUS_SEGMENTS = [
    (0, 5,  "脑科学研究院 · B3 实验室", "记录今夜的脑电波数据，仪器低鸣", "专注", "🧪"),
    (5, 8,  "恋语大学 · 教工公寓", "煮一杯耶加雪菲，看天色一点点亮起来", "平静", "☕"),
    (8, 12, "恋语大学 · 研究院办公室", "整理课题资料，准备上午的组会", "沉稳", "📚"),
    (12, 14, "研究院 · 食堂", "午餐，今天加了一份他不太爱的青椒", "无奈", "🍱"),
    (14, 18, "脑科学研究院 · 实验室", "指导学生做记忆相关的对照实验", "投入", "🔬"),
    (18, 21, "街角咖啡店 · 靠窗位置", "翻一本没读完的书，偶尔看一眼窗外", "惬意", "📖"),
    (21, 24, "教工公寓 · 书房", "夜读，台灯下记几行笔记", "温柔", "🕯️"),
]


@app.get("/api/status")
async def lucien_status():
    """许墨的实时状态（由自主生活引擎驱动）。"""
    now = datetime.now()
    base = {
        "time": now.strftime("%H:%M"),
        "hour": now.hour,
        "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()],
    }
    st = _load_life().get("state")
    if not st:
        # 每个账号首次访问时初始化自己的生活状态，不再读取 owner 的共享时间线。
        await _life_tick()
        st = _load_life().get("state")
    # 生活引擎状态可能因 lifespan 未启动等原因过期：超过 2 小时视为失效，
    # 回退到按时段推算的静态表，避免在早上还显示昨天中午的旧场景。
    if st and (_time.time() - st.get("since_ts", 0)) <= 2 * 3600:
        base.update({
            "scene": f'{st["place"]} · {st["scene"]}',
            "place": st["place"],
            "activity": st["activity"],
            "mood": st["mood"],
            "emoji": st["emoji"],
            "since": st.get("since_str", ""),
            "mins_ago": max(0, int((_time.time() - st.get("since_ts", _time.time())) / 60)),
        })
        return base
    # 引擎尚未产出或状态已过期：回退静态表
    for s, e, scene, activity, mood, emoji in STATUS_SEGMENTS:
        if s <= now.hour < e:
            base.update({"scene": scene, "activity": activity, "mood": mood, "emoji": emoji})
            return base
    seg = STATUS_SEGMENTS[0]
    base.update({"scene": seg[2], "activity": seg[3], "mood": seg[4], "emoji": seg[5]})
    return base


GREETING_TTL = 30  # 开场白缓存仅 30 秒：防同一秒并发重复打 LLM，桶内不再"每次都一样"


def _greeting_fallback() -> str:
    """LLM 不可用时按时段随机挑一句兜底，避免每次相同。"""
    h = datetime.now().hour
    if h < 5:
        pool = ["这么晚了？怎么了，我在。", "夜深了，你还没睡。"]
    elif h < 11:
        pool = ["早。今天也一起吧。", "你来了，咖啡刚煮好。"]
    elif h < 14:
        pool = ["中午好，吃了吗？", "歇一会儿，我在。"]
    elif h < 18:
        pool = ["下午好。忙吗？", "刚好，我也刚喘口气。"]
    else:
        pool = ["晚上好，今天辛苦了。", "你来了，我正想找你。"]
    return random.choice(pool)


@app.get("/api/chat/greeting")
async def chat_greeting(avoid: str = ""):
    """生成一句许墨的开场白：基于当前真实时段与生活场景，LLM 生成 + 短期缓存。

    替代前端写死的开场字符串——既避免"每次都一样"，也避免与当前时段/场景
    矛盾（如早上还说"对着论文发呆到深夜"）。

    avoid: 前端传入"最近已展示过的开场白"列表（\\n 分隔，最多 12 条），
    LLM 会主动避开它们的句式与措辞，让用户每次打开对话窗都看到不同的开场。
    """
    now = datetime.now()
    bucket = int(now.timestamp() // 30)  # 30 秒桶（与 GREETING_TTL 对齐）
    try:
        scope = _role_ctx.get() or ""
    except Exception:
        scope = ""
    life = _load_life()
    st = life.get("state") or {}
    scene_key = (st.get("place", "") + "·" + st.get("scene", "")) if st else "static"
    avoid_list = [s.strip() for s in (avoid or "").split("\n") if s.strip()][:12]
    avoid_hash = hashlib.md5("||".join(avoid_list).encode("utf-8")).hexdigest()[:8]
    key = "greeting:%s:%s:%s:%s" % (scope, bucket, scene_key, avoid_hash)
    cached = _cache_get(key, ttl=GREETING_TTL)
    if cached:
        return {"text": cached}
    avoid_block = ""
    if avoid_list:
        avoid_block = (
            "\n\n【不要重复】以下是最近几次已对她说过的开场白，本次请主动避开"
            "它们的句式与措辞，换一种新的说法：\n"
            + "\n".join("- " + s for s in avoid_list)
        )
    prompt = (
        SYSTEM_PROMPT
        + _time_directive()
        + _name_directive()
        + avoid_block
        + "\n\n【当前任务】她刚刚打开你们的对话窗，你们还没有说过话。"
        "请说一句自然的开场白，作为你此刻对她说的第一句话。要求：\n"
        "1. 仅 1 句，不超过 40 字，温柔克制，符合你的语感；\n"
        "2. 可自然带过你此刻正在做的事或所处的场景，但不要汇报式罗列；\n"
        "3. 不要与当前时段矛盾（如现在是早上就不能说『晚安』『该睡了』）；\n"
        "4. 只输出开场白本身，不要引号、不要动作描写（不要用括号）、不要解释。"
    )
    try:
        raw = await _call_llm(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "（她打开了对话窗，安静地看着我）"},
            ],
            max_tokens=300,
        )
        # 推理型模型偶发把思考过程写进 content：用与短信相同的清洗逻辑提取真正的开场白
        text = _clean_sms_text(raw or "")
        # 防止动作描写残留：以「（」开头则截到首个「）」之后
        if text.startswith("（") and "）" in text:
            text = text.split("）", 1)[1].strip()
        if not text:
            text = _greeting_fallback()
    except Exception as e:
        print(f"[greeting] LLM 失败，用兜底：{str(e)[:160]}", flush=True)
        text = _greeting_fallback()
    _cache_set(key, text, ttl=GREETING_TTL)
    return {"text": text}


@app.get("/api/life/feed")
async def life_feed(after: float = 0):
    """许墨的生活事件流：after 之后的新事件（前端 30 秒轮询增量）。"""
    life = _load_life()
    events = [t for t in life.get("timeline", []) if t.get("ts", 0) > after]
    st = life.get("state")
    return {
        "events": events,
        "server_ts": _time.time(),
        "state": {
            "scene": f'{st["place"]} · {st["scene"]}',
            "activity": st["activity"],
            "mood": st["mood"],
            "emoji": st["emoji"],
            "since": st.get("since_str", ""),
        } if st else None,
    }


# ---------------------------------------------------------------------------
# 心动值系统
# ---------------------------------------------------------------------------
AFFINITY_FILE = RolePath("affinity.json")

# ---------------------------------------------------------------------------
# 多维度情感系统
# ---------------------------------------------------------------------------

# 情感维度定义（0-100分值）
EMOTION_DIMENSIONS = {
    "intimacy": "亲密度",      # 疏离 → 宠溺
    "emotional_tone": "情绪基调",  # 冷淡 → 热情
    "expression_style": "表达风格",  # 克制 → 外放
    "dominance": "主导倾向",   # 顺从 → 强势
}

# 默认情感状态
def _get_default_emotion_state() -> dict:
    """返回情感维度的默认状态"""
    now = datetime.now()
    return {
        "intimacy": 30,        # 默认中等偏低的亲密度
        "emotional_tone": 50,  # 默认中性情绪基调
        "expression_style": 40,  # 默认偏克制的表达
        "dominance": 30,       # 默认偏顺从
        "last_update": now.isoformat(),
        "dialogue_modes": [],  # 已解锁的对话模式
    }

# 情感维度事件影响配置
EMOTION_EVENTS = {
    "user_praise": {
        "intimacy": 5,
        "emotional_tone": 3,
        "expression_style": 2,
        "dominance": -1
    },
    "user_neglect": {
        "intimacy": -3,
        "emotional_tone": -2,
        "expression_style": -1,
        "dominance": 0
    },
    "user_care": {
        "intimacy": 4,
        "emotional_tone": 2,
        "expression_style": 1,
        "dominance": -2
    },
    "user_challenging": {
        "intimacy": -1,
        "emotional_tone": 1,
        "expression_style": 2,
        "dominance": 3
    },
    "intimate_moment": {
        "intimacy": 8,
        "emotional_tone": 4,
        "expression_style": 3,
        "dominance": -2
    },
    "conflict": {
        "intimacy": -5,
        "emotional_tone": -3,
        "expression_style": 4,
        "dominance": 2
    }
}

# 对话模式解锁阈值
def _gentle_condition(emotion_state: dict) -> bool:
    return emotion_state.get("intimacy", 30) >= 60 and emotion_state.get("emotional_tone", 50) >= 70

def _scholarly_condition(emotion_state: dict) -> bool:
    return emotion_state.get("emotional_tone", 50) <= 40 and emotion_state.get("expression_style", 40) <= 50

def _possessive_condition(emotion_state: dict) -> bool:
    return emotion_state.get("intimacy", 30) >= 80 and emotion_state.get("dominance", 30) >= 60

def _playful_condition(emotion_state: dict) -> bool:
    return emotion_state.get("intimacy", 30) >= 50 and emotion_state.get("expression_style", 40) >= 70

DIALOGUE_MODES = {
    "gentle": {
        "name": "温柔模式",
        "condition": _gentle_condition,
        "description": "亲密度高且情绪热情时的温柔宠溺模式"
    },
    "scholarly": {
        "name": "学术模式",
        "condition": _scholarly_condition,
        "description": "情绪冷静且表达克制时的学术探讨模式"
    },
    "possessive": {
        "name": "占有模式",
        "condition": _possessive_condition,
        "description": "亲密度极高且主导性强时的占有欲模式"
    },
    "playful": {
        "name": "调皮模式",
        "condition": _playful_condition,
        "description": "亲密度适中且表达外放时的调皮互动模式"
    }
}

def _get_coupling_weights(emotion_state: dict) -> dict:
    """根据当前情感状态计算动态耦合权重矩阵
    
    亲密度很低时，即使情绪基调设得很热情，也不该表现得宠溺
    低亲密度+高热情应该是"客套的礼貌"而不是"甜"
    """
    intimacy = emotion_state.get("intimacy", 30)
    emotional_tone = emotion_state.get("emotional_tone", 50)
    
    # 基础权重
    weights = {
        "intimacy": 0.4,
        "emotional_tone": 0.3,
        "expression_style": 0.2,
        "dominance": 0.1
    }
    
    # 动态调整：亲密度低时，压制热情和表达外放的影响
    if intimacy < 30:
        weights["emotional_tone"] *= 0.5  # 情绪热情度影响力减半
        weights["expression_style"] *= 0.4  # 表达外放度影响力进一步降低
        weights["intimacy"] = 0.6  # 亲密度权重提升，主导氛围
        
    # 亲密度高时，情绪和表达的影响力增强
    elif intimacy > 70:
        weights["emotional_tone"] *= 1.3
        weights["expression_style"] *= 1.2
        
    # 情绪冷淡时，主导倾向影响力增强
    if emotional_tone < 30:
        weights["dominance"] *= 1.5
        
    # 归一化权重
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}

def _apply_emotion_coupling(emotion_state: dict, base_changes: dict) -> dict:
    """应用动态耦合矩阵计算最终的情感变化"""
    weights = _get_coupling_weights(emotion_state)
    final_changes = {}
    
    for dimension in EMOTION_DIMENSIONS.keys():
        if dimension in base_changes:
            # 基础变化 + 耦合影响
            base_change = base_changes[dimension]
            coupling_effect = sum(
                weights.get(d, 0) * base_changes.get(d, 0) 
                for d in EMOTION_DIMENSIONS.keys() if d != dimension
            )
            final_changes[dimension] = base_change + coupling_effect * 0.3
        else:
            final_changes[dimension] = 0
            
    return final_changes

def _update_emotion_state(emotion_state: dict, changes: dict) -> dict:
    """更新情感状态，确保数值在0-100范围内"""
    for dimension, change in changes.items():
        if dimension in emotion_state:
            new_value = emotion_state[dimension] + change
            emotion_state[dimension] = max(0, min(100, new_value))
    
    emotion_state["last_update"] = datetime.now().isoformat()
    
    # 检查是否解锁新的对话模式
    current_modes = emotion_state.get("dialogue_modes", [])
    for mode_id, mode_config in DIALOGUE_MODES.items():
        if mode_id not in current_modes and mode_config["condition"](emotion_state):
            current_modes.append(mode_id)
    emotion_state["dialogue_modes"] = current_modes
    
    return emotion_state

def _apply_emotion_decay(emotion_state: dict) -> dict:
    """应用每小时情感衰减机制"""
    if not emotion_state.get("last_update"):
        emotion_state["last_update"] = datetime.now().isoformat()
        return emotion_state
        
    try:
        last_update = datetime.fromisoformat(emotion_state["last_update"])
        hours_passed = (datetime.now() - last_update).total_seconds() / 3600
        
        if hours_passed < 1:
            return emotion_state  # 不足一小时不衰减
            
        # 衰减率：每小时衰减1-2分，亲密度衰减更慢
        decay_rates = {
            "intimacy": 0.5,          # 亲密度衰减最慢
            "emotional_tone": 1.0,    # 情绪基准衰减
            "expression_style": 1.5,  # 表达风格衰减较快
            "dominance": 1.2          # 主导倾向衰减中等
        }
        
        # 应用衰减，确保不低于最低阈值
        min_values = {
            "intimacy": 10,           # 亲密度最低保持10分
            "emotional_tone": 20,     # 情绪最低保持20分
            "expression_style": 15,   # 表达最低保持15分
            "dominance": 10           # 主导最低保持10分
        }
        
        for dimension, rate in decay_rates.items():
            if dimension in emotion_state:
                decay = rate * hours_passed
                new_value = emotion_state[dimension] - decay
                emotion_state[dimension] = max(min_values[dimension], new_value)
                
        emotion_state["last_update"] = datetime.now().isoformat()
        
    except (ValueError, KeyError) as e:
        print(f"[emotion] 衰减计算异常: {e}", flush=True)
        
    return emotion_state

def _get_emotional_instructions(emotion_state: dict) -> str:
    """根据当前情感状态生成对话指令"""
    intimacy = emotion_state.get("intimacy", 30)
    emotional_tone = emotion_state.get("emotional_tone", 50)
    expression_style = emotion_state.get("expression_style", 40)
    dominance = emotion_state.get("dominance", 30)
    
    instructions = []
    
    # 基于亲密度调整称呼和语气
    if intimacy < 20:
        instructions.append("保持疏离的距离感，称呼为'你'，语气礼貌但冷淡")
    elif intimacy < 40:
        instructions.append("保持适度的距离感，称呼为'你'，语气温和但有边界")
    elif intimacy < 60:
        instructions.append("可以适当亲近，称呼为'你'，语气温暖自然")
    elif intimacy < 80:
        instructions.append("关系亲密，可以使用亲昵称呼如'小笨蛋'，语气宠溺温柔")
    else:
        instructions.append("极度亲密，称呼更加亲昵，语气充满宠溺和温柔")
    
    # 基于情绪基调调整活力和浓度
    if emotional_tone < 30:
        instructions.append("情绪表达克制冷静，回应简洁，避免过度热情")
    elif emotional_tone < 50:
        instructions.append("情绪表达温和适度，保持理性与感性的平衡")
    elif emotional_tone < 70:
        instructions.append("情绪表达较为热情，回应温暖有活力")
    else:
        instructions.append("情绪表达热烈，回应充满活力和情感浓度")
    
    # 基于表达风格调整emoji和语气词
    if expression_style < 30:
        instructions.append("表达简洁克制，避免使用emoji和过多的语气词")
    elif expression_style < 50:
        instructions.append("表达适度，可以少量使用emoji和语气词")
    elif expression_style < 70:
        instructions.append("表达较为外放，适当使用emoji和语气词增强表达")
    else:
        instructions.append("表达外放热情，可以使用emoji、语气词和感叹号")
    
    # 基于主导倾向调整互动方式
    if dominance < 30:
        instructions.append("顺着用户说话，多使用询问和征询的语气")
    elif dominance < 50:
        instructions.append("保持平衡，既顺应用户又能适当引导")
    elif dominance < 70:
        instructions.append("适度强势，可以表达自己的观点和偏好")
    else:
        instructions.append("主导性强，更主动引导对话，偶尔可以怼回去")
    
    # 检查当前激活的对话模式
    active_modes = []
    for mode_id, mode_config in DIALOGUE_MODES.items():
        if mode_id in emotion_state.get("dialogue_modes", []):
            if mode_config["condition"](emotion_state):
                active_modes.append(mode_config["name"])
    
    if active_modes:
        instructions.append(f"当前激活的对话模式: {', '.join(active_modes)}")
    
    return "\n".join(f"- {inst}" for inst in instructions)

# (阈值, 等级码, 等级名, 称号)
AFFINITY_LEVELS = [
    (0,    "Lv.1",  "初识", "数据样本"),
    (50,   "Lv.2",  "留意", "观察对象"),
    (150,  "Lv.3",  "信赖", "特别的人"),
    (300,  "Lv.4",  "暧昧", "心跳异常"),
    (500,  "Lv.5",  "心动", "多巴胺峰值"),
    (800,  "Lv.6",  "牵挂", "镜像神经元"),
    (1200, "Lv.7",  "深爱", "不可逆反应"),
    (1700, "Lv.8",  "灵魂", "意识共振"),
    (2300, "Lv.9",  "唯一", "进化终点"),
    (3000, "Lv.10", "永恒", "熵减之约"),
]

# 行为 → 心动值增量
AFFINITY_DELTAS = {
    "chat": 5,
    "like": 2,
    "comment": 3,
    "moment": 1,
    "quote": 2,
    # 收藏许墨的语音
    "voice": 2,
    # 共读陪聊（许墨陪读时讨论章节）
    "book_companion": 2,
    # 一起看视频（陪看互动）
    "watch": 3,
    # 一起听音乐（陪听互动）
    "listen": 3,
    # 开放世界（世界·恋语市）内的互动
    "world": 3,          # 与游戏中的许墨对话 / 赠礼
    "world_quest": 6,    # 完成主线章节 / 支线
    "world_ending": 10,  # 达成结局
    # 画境（图生图）共创一幅作品
    "img2img": 3,
    # 化身：真人照片转恋与制作人风格卡通形象
    "avatarify": 4,
    # 更换许墨头像：上传 / 切换到化身 / 切换到默认
    "avatar_set": 3,
    # 场景立绘更换：为某个场景选一张新立绘
    "charimg_set": 2,
    # 世界地图新建自定义地点
    "world_place": 4,
    # 建筑·室内场景：与室内的许墨互动一次（热点 type=npc）
    "interior_xumo": 5,
    # 世界脉搏：让城市生长出新的动态
    "world_pulse": 2,
    # 世界脉搏：亲身参与一段城市事件
    "world_event": 5,
    # 时光盒：记下一个纪念日
    "anniversary": 2,
    # 时光盒：封存一枚时光胶囊
    "capsule": 3,
    # 时光盒：开启时光胶囊并收到回信
    "capsule_open": 4,
    # 时光盒：生成一张回忆卡
    "relic": 3,
    # 时光盒：许墨策划一次约会
    "date_plan": 4,
    # 约会手账：记下一次一起去过的地方
    "date_log": 5,
    # 约会手账：请许墨重写一段小结
    "date_memory": 1,
    # 清梦：接入一次梦境
    "dream": 3,
    # 心智图谱：完成一次情绪光谱分析
    "mind_scan": 2,
    # 心智图谱：完成一次默契实验
    "mind_quiz": 3,
    # 蝶语花园：捕到一只蝴蝶
    "butterfly": 1,
    # 蝶语花园：图鉴首次收录新蝶种
    "butterfly_new": 4,
    # 平行宇宙：观测一个新的宇宙
    "pverse": 3,
    # 天台观星：一起看一个星座
    "astro": 2,
    # 天台观星：对流星许愿
    "astro_wish": 3,
    # 黑天鹅档案：解密一份机密档案
    "bsfile": 4,
    # 许墨叫起床：接听一通起床电话
    "wakeup": 2,
    # 学习陪伴：完整完成一段专注学习
    "study_focus": 3,
    # 学习陪伴：制定 / 调整学习计划
    "study_plan": 4,
    # 学习陪伴：向许墨请教学习问题
    "study_ask": 2,
    # 学习陪伴：一起复盘学习
    "study_review": 2,
    # 学习陪伴：番茄钟提醒触发（每日一次）
    "study_reminder": 1,
    # 学习陪伴：每日学习打卡
    "study_checkin": 3,
    # 学习陪伴：知识卡片抽认（新增 / 复习）
    "study_card": 1,
    # 学习陪伴：许墨出题测验（生成 / 完成）
    "study_quiz": 3,
    # 衣橱：给许墨换一套新衣服
    "wardrobe": 4,
    # 工作助手：整理一份工作资料
    "work_organize": 2,
    # 工作助手：整理完一整批资料
    "work_finish": 6,
    # 恋爱日记：每日一起打卡
    "diary_checkin": 3,
    # 恋爱日记：写下今天的日记
    "diary_entry": 4,
    # 深度互动集（deep_apps.py）：观察手记
    "observe": 2,
    # 深度互动集：共梦联机
    "codream": 3,
    # 深度互动集：平行世界 if 线（生成 / 画卡）
    "ifline": 3,
    "ifline_card": 3,
    # 深度互动集：修复一段许墨的记忆碎片
    "memfrag": 4,
    # 深度互动集：反向教学课堂
    "classroom": 3,
    # 深度互动集：情绪天气联动
    "weatherlink": 2,
    # 深度互动集：共同习惯（建立 / 一起打卡）
    "cohabit": 2,
    "cohabit_checkin": 3,
    # 深度互动集：危急时刻演练室（对话 / 复盘）
    "rehearsal": 2,
    "rehearsal_debrief": 4,
    # 深度互动集：收到一条语音信箱留言
    "voicemail": 1,
    # 深度互动集：合著的书（开书 / 合写 / 完稿）
    "cobook": 2,
    "cobook_write": 2,
    "cobook_finish": 4,
    # 新星功能集（nova_apps.py）：时空热线（通话 / 挂断）
    "timecall": 3,
    # 新星功能集：双我辩论（旁听一场教授×恋人的对辩）
    "debate": 2,
    # 新星功能集：合影日历（生成今日合影）
    "together": 3,
    # 新星功能集：心动成就（领取一枚勋章）
    "achv": 3,
    # 新星功能集：情绪急救箱（被接住的一次）
    "sos": 1,
    # 新星功能集：人生模拟器（开启 / 走完一生）
    "lifeline": 2,
    "lifeline_end": 4,
    # 心灵互动集（psyche_apps.py）：情绪共振日记
    "psyche_mood": 3,
    "psyche_mood_revisit": 2,
    # 心灵互动集：人格实验室
    "psyche_lab": 3,
    # 心灵互动集：深夜来电
    "psyche_night": 3,
    "psyche_night_reply": 1,
    # 心灵互动集：案件共研室
    "psyche_case_clue": 1,
    "psyche_case_interrogate": 1,
    "psyche_case_press": 2,
    "psyche_case_solve": 6,
    # 心灵互动集：记忆标本馆
    "psyche_specimen": 2,
    "psyche_specimen_pov": 3,
    # 心灵互动集：观察者挑战
    "psyche_observer": 3,
    # 心灵互动集：平行世界通讯
    "psyche_parallel": 2,
    "psyche_parallel_merge": 5,
    # 心灵互动集：梦境解析
    "psyche_dream": 3,
    # 心灵互动集：关系温度计
    "psyche_relation_reflect": 1,
    # 心灵互动集：共同创作实验
    "psyche_cowrite": 2,
    "psyche_cowrite_turn": 1,
    "psyche_cowrite_finish": 4,
    # 新星功能集四期（nova_apps2.py）：梦境解码器
    "dreamlab": 3,
    # 平行信箱（收信 / 回信）
    "pmail": 2,
    # 深夜电台（开播）
    "radio": 2,
    # 默契雷达（完成一轮）
    "telepathy": 3,
    # 命运岔路（每章推进）
    "fate": 2,
    # 命运岔路完结
    "fate_end": 6,
    # 心跳频谱（生成报告）
    "pulse": 2,
    # 新星功能集五期（nova_apps3.py）：潜意识密室识破谎言
    "subconscious": 4,
    # 时空胶囊：已存在 "capsule": 3，复用
    # 共感温度计（情绪同步）
    "empath": 3,
    # 七日预言（抽预言）
    "oracle": 2,
    # 七日预言（提前揭晓，扣分）
    "oracle_reveal_penalty": -30,
    # 沉默信使（发 emoji）
    "whisper": 2,
    # 心跳调音台（保存预设）
    "mixer": 1,
}


def _load_affinity() -> dict:
    if AFFINITY_FILE.exists():
        try:
            data = json.loads(AFFINITY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "value" in data:
                data.setdefault("history", [])
                # 初始化情感维度数据（向后兼容）
                data.setdefault("emotion", _get_default_emotion_state())
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"value": 0, "history": [], "emotion": _get_default_emotion_state()}


def _save_affinity(data: dict):
    atomic_json(AFFINITY_FILE, data)


def _affinity_info(data: dict) -> dict:
    value = data.get("value", 0)
    idx = 0
    for i, (threshold, _, _, _) in enumerate(AFFINITY_LEVELS):
        if value >= threshold:
            idx = i
        else:
            break
    level = AFFINITY_LEVELS[idx]
    next_level = AFFINITY_LEVELS[idx + 1] if idx + 1 < len(AFFINITY_LEVELS) else None
    if next_level:
        progress = (value - level[0]) / (next_level[0] - level[0])
        remaining = next_level[0] - value
    else:
        progress = 1.0
        remaining = 0
    history = data.get("history", [])[-8:]
    return {
        "value": value,
        "level_index": idx,
        "level_code": level[1],
        "level_name": level[2],
        "level_title": level[3],
        "progress": round(progress * 100, 1),
        "remaining": remaining,
        "next_level_name": next_level[2] if next_level else None,
        "next_threshold": next_level[0] if next_level else None,
        "recent": history,
    }


def _adjust_emotion(event_type: str, emotion_state: dict) -> dict:
    """根据事件类型调整情感状态（应用动态耦合矩阵）"""
    if event_type not in EMOTION_EVENTS:
        return emotion_state
        
    base_changes = EMOTION_EVENTS[event_type]
    coupled_changes = _apply_emotion_coupling(emotion_state, base_changes)
    return _update_emotion_state(emotion_state, coupled_changes)

def _add_affinity(action: str, detail: str = "", emotion_event: str = None) -> dict:
    """内部调用：增加心动值并返回最新状态。
    
    Args:
        action: 亲密度行为类型
        detail: 行为详情描述
        emotion_event: 情感事件类型（如 user_praise, user_neglect 等）
    """
    if action not in AFFINITY_DELTAS:
        return _affinity_info(_load_affinity())
    # 读-改-写全程持锁：并发请求同时加分时避免互相覆盖丢加分
    with file_lock(AFFINITY_FILE):
        data = _load_affinity()
        delta = AFFINITY_DELTAS[action]
        data["value"] = data.get("value", 0) + delta
        data.setdefault("history", []).append({
            "action": action,
            "delta": delta,
            "detail": detail,
            "time": datetime.now().strftime("%m-%d %H:%M"),
        })
        data["history"] = data["history"][-100:]
        
        # 处理情感事件调整
        if emotion_event:
            emotion_state = data.get("emotion", _get_default_emotion_state())
            updated_emotion = _adjust_emotion(emotion_event, emotion_state)
            data["emotion"] = updated_emotion
            
        _save_affinity(data)
        info = _affinity_info(data)
    info["delta"] = delta
    return info


@app.get("/api/affinity")
async def get_affinity():
    return _affinity_info(_load_affinity())


@app.post("/api/affinity/add")
async def add_affinity(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    action = (body.get("action") or "").strip()
    detail = (body.get("detail") or "").strip()
    if action not in AFFINITY_DELTAS:
        return JSONResponse({"error": f"未知行为：{action}"}, status_code=400)
    return _add_affinity(action, detail)


# ---------------------------------------------------------------------------
# 情感系统 API 端点
# ---------------------------------------------------------------------------

@app.get("/api/emotion")
async def get_emotion():
    """获取当前情感状态"""
    data = _load_affinity()
    emotion_state = data.get("emotion", _get_default_emotion_state())
    
    # 计算耦合权重供调试使用
    weights = _get_coupling_weights(emotion_state)
    
    # 检查当前激活的对话模式
    active_modes = []
    for mode_id, mode_config in DIALOGUE_MODES.items():
        if mode_id in emotion_state.get("dialogue_modes", []):
            if mode_config["condition"](emotion_state):
                active_modes.append({
                    "id": mode_id,
                    "name": mode_config["name"],
                    "description": mode_config["description"]
                })
    
    return {
        "dimensions": {
            "intimacy": emotion_state.get("intimacy", 30),
            "emotional_tone": emotion_state.get("emotional_tone", 50),
            "expression_style": emotion_state.get("expression_style", 40),
            "dominance": emotion_state.get("dominance", 30)
        },
        "last_update": emotion_state.get("last_update"),
        "dialogue_modes": emotion_state.get("dialogue_modes", []),
        "active_modes": active_modes,
        "coupling_weights": weights,
        "instructions": _get_emotional_instructions(emotion_state)
    }


@app.post("/api/emotion/adjust")
async def adjust_emotion(req: Request):
    """手动调整情感维度（主要用于调试）"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    
    # 支持两种方式：
    # 1. 通过事件类型调整：{"event": "user_praise"}
    # 2. 直接调整维度：{"intimacy": 5, "emotional_tone": -3}
    
    if "event" in body:
        event_type = body.get("event", "").strip()
        if event_type not in EMOTION_EVENTS:
            return JSONResponse({"error": f"未知情感事件：{event_type}"}, status_code=400)
        
        with file_lock(AFFINITY_FILE):
            data = _load_affinity()
            emotion_state = data.get("emotion", _get_default_emotion_state())
            updated_emotion = _adjust_emotion(event_type, emotion_state)
            data["emotion"] = updated_emotion
            _save_affinity(data)
            
        return {"success": True, "emotion": updated_emotion}
    
    elif any(d in body for d in EMOTION_DIMENSIONS.keys()):
        changes = {d: body[d] for d in EMOTION_DIMENSIONS.keys() if d in body}
        
        with file_lock(AFFINITY_FILE):
            data = _load_affinity()
            emotion_state = data.get("emotion", _get_default_emotion_state())
            updated_emotion = _update_emotion_state(emotion_state, changes)
            data["emotion"] = updated_emotion
            _save_affinity(data)
            
        return {"success": True, "emotion": updated_emotion}
    
    else:
        return JSONResponse({"error": "请提供 event 或维度调整参数"}, status_code=400)


@app.get("/api/emotion/modes")
async def get_emotion_modes():
    """获取所有对话模式及其解锁状态"""
    data = _load_affinity()
    emotion_state = data.get("emotion", _get_default_emotion_state())
    
    modes_info = []
    for mode_id, mode_config in DIALOGUE_MODES.items():
        is_unlocked = mode_id in emotion_state.get("dialogue_modes", [])
        is_active = is_unlocked and mode_config["condition"](emotion_state)
        
        modes_info.append({
            "id": mode_id,
            "name": mode_config["name"],
            "description": mode_config["description"],
            "unlocked": is_unlocked,
            "active": is_active
        })
    
    return {"modes": modes_info}


@app.get("/api/emotion/events")
async def get_emotion_events():
    """获取所有可用的情感事件类型"""
    events_info = []
    for event_id, changes in EMOTION_EVENTS.items():
        events_info.append({
            "id": event_id,
            "changes": changes,
            "description": f"情感事件 {event_id}"
        })
    
    return {"events": events_info}


# ---------------------------------------------------------------------------
# 语录收藏 + 每日一签
# ---------------------------------------------------------------------------
QUOTES_FILE = RolePath("quotes.json")

DAILY_QUOTE_PROMPT = SYSTEM_PROMPT + """

【当前任务】请以许墨的口吻写一句「每日签语」。要求：
1. 一句话，10-30 字，温柔克制、话留三分，可带一处学术梗或双关。
2. 像是他随手写在便签上、留给今天的她的那句。
3. 只输出签语本身，不要署名、引号、解释。"""

DEFAULT_QUOTES_DATA = {
    "quotes": [
        {"id": "q-seed-1", "content": "有些习惯，比甜味更难戒。", "source": "moment", "time": "08-15"},
        {"id": "q-seed-2", "content": "人会选择性遗忘痛苦，却永远记得让自己心动的瞬间。", "source": "moment", "time": "08-15"},
    ],
    "daily": None,
}


def _load_quotes() -> dict:
    if QUOTES_FILE.exists():
        try:
            data = json.loads(QUOTES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("quotes", [])
                data.setdefault("daily", None)
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"quotes": list(DEFAULT_QUOTES_DATA["quotes"]), "daily": None}


def _save_quotes(data: dict):
    atomic_json(QUOTES_FILE, data)


@app.get("/api/quotes")
async def list_quotes():
    data = _load_quotes()
    return {"quotes": list(reversed(data.get("quotes", [])))}


@app.post("/api/quotes")
async def add_quote(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    content = (body.get("content") or "").strip()
    if not content:
        return JSONResponse({"error": "内容不能为空"}, status_code=400)
    source = (body.get("source") or "chat").strip()
    data = _load_quotes()
    # 去重
    if any(q.get("content") == content for q in data.get("quotes", [])):
        return JSONResponse({"error": "已经收藏过这句话了"}, status_code=409)
    quote = {
        "id": uuid.uuid4().hex[:12],
        "content": content,
        "source": source,
        "time": datetime.now().strftime("%m-%d %H:%M"),
    }
    data.setdefault("quotes", []).append(quote)
    _save_quotes(data)
    info = _add_affinity("quote", "收藏语录")
    return {"quote": quote, "affinity": info}


@app.delete("/api/quotes/{quote_id}")
async def delete_quote(quote_id: str):
    data = _load_quotes()
    before = len(data.get("quotes", []))
    data["quotes"] = [q for q in data.get("quotes", []) if q.get("id") != quote_id]
    if len(data["quotes"]) == before:
        return JSONResponse({"error": "语录不存在"}, status_code=404)
    _save_quotes(data)
    return {"ok": True}


@app.get("/api/quotes/daily")
async def daily_quote():
    """获取今日签语。"""
    data = _load_quotes()
    today = datetime.now().strftime("%Y-%m-%d")
    daily = data.get("daily")
    if daily and daily.get("date") == today:
        return {"daily": daily}
    return {"daily": None, "date": today}


@app.post("/api/quotes/daily/refresh")
async def refresh_daily_quote():
    """让许墨生成今日签语（同一天重复请求返回缓存）。"""
    import random
    data = _load_quotes()
    today = datetime.now().strftime("%Y-%m-%d")
    daily = data.get("daily")
    if daily and daily.get("date") == today:
        return {"daily": daily}
    messages = [
        {"role": "system", "content": DAILY_QUOTE_PROMPT},
        {"role": "user", "content": f"今天是 {today}。请写一句今天的签语。"},
    ]
    try:
        content = await _call_llm(messages, max_tokens=int(os.getenv("MOMENT_MAX_TOKENS", "2000")))
        content = content.strip().strip('"').strip('「').strip('」')
        if not content:
            raise RuntimeError("空内容")
    except Exception:
        fallback = [
            "今天也是值得被记住的一天。",
            "慢慢来，时间在你这边。",
            "嗯，有我在。",
            "有些答案，不用急着找。",
            "晚风很温柔，适合散步。",
        ]
        content = random.choice(fallback)
    daily = {
        "date": today,
        "content": content,
        "time": datetime.now().strftime("%H:%M"),
    }
    # 签语卡配图：氛围场景插画（无人像），与签语意境呼应
    try:
        quote_img_dir = RolePath("static", "quote_img")
        img_url, _ = await _llm_image_for_text(
            f"【今日签语】{content}\n日期：{today}\n请构思一张与签语意境呼应的氛围配图："
            "安静克制、低饱和紫调，像许墨随手拍下或摆在案头的一帧画面。",
            quote_img_dir, "/static/quote_img", f"daily_{today.replace('-', '')}",
            IMG2IMG_SIZES.get("square", "1024x1024"), with_xumo=False,
        )
        if img_url:
            daily["image"] = img_url + f"?t={int(_time.time())}"
    except Exception:
        pass
    data["daily"] = daily
    _save_quotes(data)
    return {"daily": daily}


# ================= 许墨形象（可更换的头像） =================
XUMO_AVATAR_FILE = RolePath("xumo_avatar.json")
XUMO_AVATAR_UPLOADS_DIR = RolePath("static", "xumo_avatar")

# 默认头像：内嵌在 static/ 目录里（"官方设定"卡面），作为回退
DEFAULT_AVATAR_CANDIDATES = ("avatar.jpeg", "avatar.jpg", "avatar.png", "avatar.webp")


def _xumo_avatar_default_path() -> Path | None:
    for name in DEFAULT_AVATAR_CANDIDATES:
        p = STATIC_DIR / name
        if p.exists():
            return p
    return None


def _xumo_avatar_default_url() -> str:
    """默认头像 URL（带版本号便于刷新）。"""
    v = _xumo_avatar_load().get("version", 1)
    return f"/avatar?kind=default&v={v}"


def _xumo_avatar_load() -> dict:
    """读取头像设置：active_id（"default" / 上传 id / 化身记录 id）、version、uploads 列表。"""
    if XUMO_AVATAR_FILE.exists():
        try:
            data = json.loads(XUMO_AVATAR_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("active_id", "default")
                data.setdefault("version", 1)
                data.setdefault("uploads", [])  # [{id, name, url, time, kind}]
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"active_id": "default", "version": 1, "uploads": []}


def _xumo_avatar_save(data: dict):
    atomic_json(XUMO_AVATAR_FILE, data)


def _xumo_avatar_bump(data: dict) -> dict:
    data["version"] = int(data.get("version", 1)) + 1
    # 清掉缓存的参考图，强制重新加载
    global _XUMO_REFS_CACHE
    _XUMO_REFS_CACHE = None
    return data


def _find_avatar():
    """根据当前 active 状态返回许墨头像的实际文件路径。
    active_id="default"  → static/avatar.*；否则指向用户上传 / 化身记录的图片。
    """
    state = _xumo_avatar_load()
    active = state.get("active_id") or "default"
    if active != "default":
        if active.startswith("a2a:"):
            # 化身卡面：从 avatarify 记录里找 gen URL，再映射回本地文件
            a2a_id = active[4:]
            try:
                rec = next((r for r in _load_avatarify() if r.get("id") == a2a_id), None)
            except Exception:
                rec = None
            if rec and rec.get("gen"):
                gen_url = rec["gen"]
                # 形如 /static/avatarify/xxxx.png → static/avatarify/xxxx.png
                if gen_url.startswith("/static/"):
                    p = role_file(gen_url.lstrip("/"))
                    if p.exists():
                        return p
        else:
            # 找匹配的 upload
            for u in state.get("uploads", []):
                if u.get("id") == active and u.get("path"):
                    p = Path(u["path"])
                    if p.exists():
                        return p
    # 回退：默认头像
    default = _xumo_avatar_default_path()
    if default:
        return default
    # 终极兜底：项目根目录人设图
    for ext in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for f in sorted(BASE_DIR.glob(ext)):
            if not f.stem.lower().startswith("background"):
                return f
    return None


@app.get("/avatar")
async def avatar():
    img = _find_avatar()
    if img and img.exists():
        return FileResponse(img)
    return JSONResponse({"error": "未找到人设图片"}, status_code=404)


# —— 许墨形象管理接口 ——

def _xumo_avatar_list_uploads() -> list:
    """汇总所有可选头像：默认 + 用户上传 + 化身历史（可作头像）。"""
    state = _xumo_avatar_load()
    items = []
    # 1) 默认
    if _xumo_avatar_default_path():
        items.append({
            "id": "default",
            "kind": "default",
            "name": "默认设定",
            "url": f"/avatar?kind=default&v={state['version']}",
            "time": "",
        })
    # 2) 用户上传
    for u in state.get("uploads", []):
        if u.get("path") and Path(u["path"]).exists():
            items.append({
                "id": u["id"],
                "kind": "upload",
                "name": u.get("name") or "自传头像",
                "url": f"{u['url']}?v={state['version']}",
                "time": u.get("time", ""),
            })
    # 3) 化身历史（最新 12 张）
    try:
        a2a_recs = _load_avatarify()
        for r in list(reversed(a2a_recs))[:12]:
            items.append({
                "id": f"a2a:{r['id']}",
                "kind": "avatarify",
                "name": f"化身 · {r.get('theme_name', '')}",
                "url": f"{r['gen']}?v={state['version']}",
                "time": r.get("time", ""),
            })
    except Exception:
        pass
    return items


@app.get("/api/avatar/state")
async def xumo_avatar_state():
    state = _xumo_avatar_load()
    items = _xumo_avatar_list_uploads()
    active = state.get("active_id") or "default"
    # 当前头像 url（指向 /avatar，与 /avatar 实际返回值一致）
    active_url = f"/avatar?v={state['version']}"
    return {
        "active_id": active,
        "version": state["version"],
        "active_url": active_url,
        "items": items,
    }


@app.post("/api/avatar/upload")
async def xumo_avatar_upload(req: Request):
    """上传一张新图片作为许墨头像候选。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    image_b64 = (body.get("image") or "").strip()
    name = (body.get("name") or "").strip() or "自传头像"
    if not image_b64:
        return JSONResponse({"error": "请提供图片数据"}, status_code=400)

    mime = "jpeg"
    if image_b64.startswith("data:"):
        head, _, image_b64 = image_b64.partition(",")
        m = re.search(r"data:image/(\w+)", head)
        if m:
            mime = m.group(1).lower()
    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        return JSONResponse({"error": "图片数据解码失败"}, status_code=400)
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": "图片不能超过 8MB"}, status_code=400)
    if len(raw) < 200:
        return JSONResponse({"error": "图片内容过小"}, status_code=400)
    # 校验文件 magic（防止传任意二进制）
    if not (raw[:3] == b"\xff\xd8\xff"  # jpeg
            or raw[:8] == b"\x89PNG\r\n\x1a\n"  # png
            or raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"  # webp
            or raw[:2] == b"BM"):  # bmp
        return JSONResponse({"error": "仅支持 PNG / JPG / WEBP / BMP"}, status_code=400)

    ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp"}.get(mime, ".jpg")
    up_id = uuid.uuid4().hex[:12]
    XUMO_AVATAR_UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    save_path = XUMO_AVATAR_UPLOADS_DIR / f"{up_id}{ext}"
    save_path.write_bytes(raw)
    url = f"/static/xumo_avatar/{up_id}{ext}"

    state = _xumo_avatar_load()
    state.setdefault("uploads", []).append({
        "id": up_id,
        "name": name,
        "url": url,
        "path": str(save_path),
        "mime": mime,
        "ext": ext,
        "time": datetime.now().strftime("%m-%d %H:%M"),
    })
    # 上传后立刻应用为当前头像
    state["active_id"] = up_id
    _xumo_avatar_bump(state)
    _xumo_avatar_save(state)
    info = _add_affinity("avatar_set", f"自定义头像 · {name}")
    return {"ok": True, "active_id": up_id, "version": state["version"], "affinity": info}


@app.post("/api/avatar/select")
async def xumo_avatar_select(req: Request):
    """切换当前头像：active_id 为 'default'、upload id 或 'a2a:<id>'。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    target = (body.get("active_id") or "").strip()
    if not target:
        return JSONResponse({"error": "未指定目标"}, status_code=400)

    state = _xumo_avatar_load()
    uploads = state.get("uploads", [])

    if target == "default":
        if not _xumo_avatar_default_path():
            return JSONResponse({"error": "默认头像不存在"}, status_code=400)
        state["active_id"] = "default"
        label = "默认设定"
    elif target.startswith("a2a:"):
        a2a_id = target[4:]
        rec = next((r for r in _load_avatarify() if r.get("id") == a2a_id), None)
        if not rec:
            return JSONResponse({"error": "化身记录不存在"}, status_code=404)
        state["active_id"] = target
        label = f"化身卡面 · {rec.get('theme_name', '')}"
    else:
        up = next((u for u in uploads if u.get("id") == target), None)
        if not up:
            return JSONResponse({"error": "该头像不存在"}, status_code=404)
        if not Path(up["path"]).exists():
            return JSONResponse({"error": "头像文件已丢失"}, status_code=400)
        state["active_id"] = target
        label = f"自定义头像 · {up.get('name', '')}"

    _xumo_avatar_bump(state)
    _xumo_avatar_save(state)
    info = _add_affinity("avatar_set", label)
    return {"ok": True, "active_id": state["active_id"], "version": state["version"], "affinity": info}


@app.delete("/api/avatar/{item_id}")
async def xumo_avatar_delete(item_id: str):
    """删除一张自传头像（默认 / 化身头像不可删）。"""
    if item_id in ("default",) or item_id.startswith("a2a:"):
        return JSONResponse({"error": "该头像不可删除"}, status_code=400)
    state = _xumo_avatar_load()
    kept = [u for u in state.get("uploads", []) if u.get("id") != item_id]
    if len(kept) == len(state.get("uploads", [])):
        return JSONResponse({"error": "头像不存在"}, status_code=404)
    removed = next((u for u in state["uploads"] if u.get("id") == item_id), None)
    if removed:
        try:
            Path(removed["path"]).unlink(missing_ok=True)
        except Exception:
            pass
    state["uploads"] = kept
    if state.get("active_id") == item_id:
        state["active_id"] = "default"
        _xumo_avatar_bump(state)
    _xumo_avatar_save(state)
    return {"ok": True, "active_id": state["active_id"], "version": state["version"]}


# ================= 场景立绘（每个场景可独立替换的全身立绘图） =================
# 与头像（avatar）系统分离：头像用于聊天列表 / 头像气泡；立绘用于桌面 / 通话 / 沉浸场景的全身图。
XUMO_CHARIMG_FILE = RolePath("xumo_charimg.json")
XUMO_CHARIMG_DIR = RolePath("static", "charimg")

# 默认立绘：内嵌在 static/home_xumo/ 的官方立绘
DEFAULT_CHARIMG_PATH = STATIC_DIR / "home_xumo" / "home_cutout.png"

# 支持的场景：key → (中文名, 说明)
# 这些 key 与前端 <img data-scene="..."> 一一对应；新增场景只需在此追加。
CHARIMG_SCENES = {
    "home":    ("主桌面立绘",   "桌面模式下，许墨站在左侧的那张全身立绘"),
    "call":    ("视频通话立绘", "和许墨语音通话时，屏幕里显示的那张立绘"),
    "immerse": ("沉浸场景立绘", "模式 A 沉浸空间里，许墨站在画面中央的立绘"),
}


def _charimg_default_url(scene: str, version: int) -> str:
    return f"/charimg?scene={scene}&kind=default&v={version}"


def _charimg_load() -> dict:
    """读取立绘设置：scenes（场景 → active_id）、version、uploads 列表。"""
    if XUMO_CHARIMG_FILE.exists():
        try:
            data = json.loads(XUMO_CHARIMG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("version", 1)
                data.setdefault("uploads", [])  # [{id, name, url, path, mime, ext, time}]
                scenes = data.setdefault("scenes", {})
                # 确保所有已知场景都有 active_id（默认 "default"）
                for k in CHARIMG_SCENES:
                    scenes.setdefault(k, "default")
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "version": 1,
        "uploads": [],
        "scenes": {k: "default" for k in CHARIMG_SCENES},
    }


def _charimg_save(data: dict):
    atomic_json(XUMO_CHARIMG_FILE, data)


def _charimg_bump(data: dict) -> dict:
    data["version"] = int(data.get("version", 1)) + 1
    return data


def _charimg_find_for_scene(scene: str) -> Path | None:
    """返回某场景当前生效的立绘文件路径；无则回退默认。"""
    state = _charimg_load()
    active_id = state.get("scenes", {}).get(scene, "default")
    if active_id and active_id != "default":
        for u in state.get("uploads", []):
            if u.get("id") == active_id and u.get("path"):
                p = Path(u["path"])
                if p.exists():
                    return p
    # 回退：默认立绘
    return DEFAULT_CHARIMG_PATH if DEFAULT_CHARIMG_PATH.exists() else None


def _charimg_list_uploads(state: dict) -> list:
    """汇总可选立绘：默认 + 用户上传（剔除已丢失文件）。"""
    items = [{
        "id": "default",
        "kind": "default",
        "name": "默认立绘",
        "url": "/charimg?kind=default&v=" + str(state["version"]),
        "time": "",
    }]
    for u in state.get("uploads", []):
        if u.get("path") and Path(u["path"]).exists():
            items.append({
                "id": u["id"],
                "kind": "upload",
                "name": u.get("name") or "自定义立绘",
                "url": f"{u['url']}?v={state['version']}",
                "time": u.get("time", ""),
            })
    return items


@app.get("/charimg")
async def charimg_serve(scene: str = "", kind: str = ""):
    """按场景返回当前生效立绘；可加 ?v=N 做缓存破坏。

    - ?scene=home    → 返回该场景当前 active 立绘
    - ?kind=default  → 直接返回默认立绘（用于「不选场景」的展示）
    """
    if kind == "default" or not scene or scene not in CHARIMG_SCENES:
        if DEFAULT_CHARIMG_PATH.exists():
            return FileResponse(DEFAULT_CHARIMG_PATH)
        return JSONResponse({"error": "默认立绘不存在"}, status_code=404)
    img = _charimg_find_for_scene(scene)
    if img and img.exists():
        return FileResponse(img)
    return JSONResponse({"error": "未找到立绘图片"}, status_code=404)


@app.get("/api/charimg/state")
async def charimg_state():
    state = _charimg_load()
    uploads = _charimg_list_uploads(state)
    # 给前端带每个场景的当前生效 url（直接命中 /charimg?scene=...）
    scene_urls = {
        k: f"/charimg?scene={k}&v={state['version']}"
        for k in CHARIMG_SCENES
    }
    scene_meta = {
        k: {"name": CHARIMG_SCENES[k][0], "desc": CHARIMG_SCENES[k][1]}
        for k in CHARIMG_SCENES
    }
    return {
        "version": state["version"],
        "scenes": state.get("scenes", {k: "default" for k in CHARIMG_SCENES}),
        "scene_meta": scene_meta,
        "scene_urls": scene_urls,
        "items": uploads,
        "default_exists": DEFAULT_CHARIMG_PATH.exists(),
    }


@app.post("/api/charimg/upload")
async def charimg_upload(req: Request):
    """上传一张新立绘候选图。不会自动绑定到任何场景，只进图库。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    image_b64 = (body.get("image") or "").strip()
    name = (body.get("name") or "").strip() or "自定义立绘"
    if not image_b64:
        return JSONResponse({"error": "请提供图片数据"}, status_code=400)

    mime = "jpeg"
    if image_b64.startswith("data:"):
        head, _, image_b64 = image_b64.partition(",")
        m = re.search(r"data:image/(\w+)", head)
        if m:
            mime = m.group(1).lower()
    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        return JSONResponse({"error": "图片数据解码失败"}, status_code=400)
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": "图片不能超过 8MB"}, status_code=400)
    if len(raw) < 200:
        return JSONResponse({"error": "图片内容过小"}, status_code=400)
    if not (raw[:3] == b"\xff\xd8\xff"
            or raw[:8] == b"\x89PNG\r\n\x1a\n"
            or raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"
            or raw[:2] == b"BM"):
        return JSONResponse({"error": "仅支持 PNG / JPG / WEBP / BMP"}, status_code=400)

    ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp"}.get(mime, ".jpg")
    up_id = uuid.uuid4().hex[:12]
    XUMO_CHARIMG_DIR.mkdir(parents=True, exist_ok=True)
    save_path = XUMO_CHARIMG_DIR / f"{up_id}{ext}"
    save_path.write_bytes(raw)
    url = f"/static/charimg/{up_id}{ext}"

    state = _charimg_load()
    state.setdefault("uploads", []).append({
        "id": up_id,
        "name": name,
        "url": url,
        "path": str(save_path),
        "mime": mime,
        "ext": ext,
        "time": datetime.now().strftime("%m-%d %H:%M"),
    })
    _charimg_bump(state)
    _charimg_save(state)
    # 上传只入图库，不触发 affinity；选定为某场景立绘时才记 affinity
    return {"ok": True, "id": up_id, "version": state["version"]}


@app.post("/api/charimg/select")
async def charimg_select(req: Request):
    """为某个场景选定立绘。
    body: {scene: "home"|"call"|"immerse", item_id: "default"|upload_id}
    """
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    scene = (body.get("scene") or "").strip()
    item_id = (body.get("item_id") or "").strip()
    if scene not in CHARIMG_SCENES:
        return JSONResponse({"error": "未知场景"}, status_code=400)
    if not item_id:
        return JSONResponse({"error": "未指定目标"}, status_code=400)

    state = _charimg_load()
    uploads = state.get("uploads", [])

    if item_id == "default":
        state.setdefault("scenes", {})[scene] = "default"
        label = f"{CHARIMG_SCENES[scene][0]} · 默认立绘"
    else:
        up = next((u for u in uploads if u.get("id") == item_id), None)
        if not up:
            return JSONResponse({"error": "该立绘不存在"}, status_code=404)
        if not Path(up["path"]).exists():
            return JSONResponse({"error": "立绘文件已丢失"}, status_code=400)
        state.setdefault("scenes", {})[scene] = item_id
        label = f"{CHARIMG_SCENES[scene][0]} · {up.get('name', '')}"

    _charimg_bump(state)
    _charimg_save(state)
    info = _add_affinity("charimg_set", label)
    return {
        "ok": True,
        "scene": scene,
        "active_id": item_id,
        "version": state["version"],
        "affinity": info,
    }


@app.delete("/api/charimg/{item_id}")
async def charimg_delete(item_id: str):
    """删除一张上传的立绘。若被某场景引用，该场景回退为默认。"""
    if item_id == "default":
        return JSONResponse({"error": "默认立绘不可删除"}, status_code=400)
    state = _charimg_load()
    kept = [u for u in state.get("uploads", []) if u.get("id") != item_id]
    if len(kept) == len(state.get("uploads", [])):
        return JSONResponse({"error": "立绘不存在"}, status_code=404)
    removed = next((u for u in state["uploads"] if u.get("id") == item_id), None)
    if removed:
        try:
            Path(removed["path"]).unlink(missing_ok=True)
        except Exception:
            pass
    state["uploads"] = kept
    # 把所有引用了被删图的场景重置为默认
    scenes = state.get("scenes", {})
    reset_scenes = []
    for k in CHARIMG_SCENES:
        if scenes.get(k) == item_id:
            scenes[k] = "default"
            reset_scenes.append(k)
    if reset_scenes:
        _charimg_bump(state)
    _charimg_save(state)
    return {
        "ok": True,
        "version": state["version"],
        "reset_scenes": reset_scenes,
    }


# ================= 世界 3D 形象（可上传的 GLB / GLTF 模型） =================
MODELS3D_FILE = RolePath("models3d.json")
MODELS3D_DIR = RolePath("static", "models3d")
MODELS3D_MAX = 40 * 1024 * 1024  # 40MB


def _models3d_load() -> dict:
    """读取世界 3D 形象设置：active_id、apply（player/both）、version、uploads。"""
    if MODELS3D_FILE.exists():
        try:
            data = json.loads(MODELS3D_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("active_id", "default")
                data.setdefault("apply", "player")  # player=仅玩家 | both=玩家+许墨
                data.setdefault("version", 1)
                data.setdefault("uploads", [])
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"active_id": "default", "apply": "player", "version": 1, "uploads": []}


def _models3d_save(data: dict):
    atomic_json(MODELS3D_FILE, data)


def _models3d_items(state: dict) -> list:
    items = []
    for u in state.get("uploads", []):
        if u.get("path") and Path(u["path"]).exists():
            items.append({
                "id": u["id"],
                "name": u.get("name") or "自传模型",
                "url": f"{u['url']}?v={state['version']}",
                "size": u.get("size", 0),
                "time": u.get("time", ""),
            })
    return items


def _gltf_embedded_ok(raw: bytes) -> bool:
    """校验 .gltf：所有 buffer / 贴图必须内嵌（data: URI），否则世界页加载不完整。"""
    try:
        doc = json.loads(raw.decode("utf-8"))
    except Exception:
        return False
    if not isinstance(doc, dict) or "asset" not in doc:
        return False
    for key in ("buffers", "images"):
        for it in doc.get(key) or []:
            uri = it.get("uri") or ""
            if uri and not uri.startswith("data:"):
                return False
    return True


@app.get("/api/model/state")
async def models3d_state():
    state = _models3d_load()
    return {
        "active_id": state["active_id"],
        "xumo_id": state.get("xumo_id", "default"),
        "version": state["version"],
        "items": _models3d_items(state),
    }


@app.post("/api/model/upload")
async def models3d_upload(req: Request):
    """上传 GLB / 全内嵌 GLTF 模型，作为世界中玩家（可选同时许墨）的 3D 形象。
    支持两种方式：
    ① multipart/form-data（推荐：流式上传，无 base64 膨胀，适合大文件与外网传输）
    ② application/json（兼容旧前端：data 字段为 base64 编码）"""
    content_type = (req.headers.get("content-type") or "").lower()
    name = "自传模型"
    role = "player"
    raw = b""

    if content_type.startswith("multipart/form-data"):
        # ---- 流式 multipart 上传 ----
        try:
            form = await req.form()
        except Exception:
            return JSONResponse({"error": "表单解析失败"}, status_code=400)
        f = form.get("file")
        if f is None or not hasattr(f, "read"):
            return JSONResponse({"error": "请提供模型文件"}, status_code=400)
        name = (form.get("name") or "").strip() or "自传模型"
        role = (form.get("role") or "player").strip()
        if role not in ("player", "xumo"):
            role = "player"
        try:
            raw = await f.read()
        except Exception:
            return JSONResponse({"error": "读取文件失败"}, status_code=400)
    else:
        # ---- JSON base64 方式（兼容旧前端）----
        try:
            body = await req.json()
        except Exception:
            return JSONResponse({"error": "请求体格式错误"}, status_code=400)
        data_b64 = (body.get("data") or "").strip()
        name = (body.get("name") or "").strip() or "自传模型"
        role = (body.get("role") or "player").strip()
        if role not in ("player", "xumo"):
            role = "player"
        if not data_b64:
            return JSONResponse({"error": "请提供模型数据"}, status_code=400)
        if data_b64.startswith("data:"):
            data_b64 = data_b64.partition(",")[2]
        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            return JSONResponse({"error": "模型数据解码失败"}, status_code=400)

    if not raw:
        return JSONResponse({"error": "请提供模型数据"}, status_code=400)
    if len(raw) > MODELS3D_MAX:
        return JSONResponse({"error": "模型不能超过 40MB（建议导出时压缩贴图、减面）"}, status_code=400)
    if len(raw) < 200:
        return JSONResponse({"error": "模型内容过小"}, status_code=400)

    if raw[:4] == b"glTF":  # GLB 二进制容器
        ext = ".glb"
    elif raw[:1] in (b"{", b"[") and _gltf_embedded_ok(raw):
        ext = ".gltf"
    else:
        return JSONResponse({"error": "仅支持 GLB，或资源全内嵌的 GLTF（VRM 请先转 GLB）"}, status_code=400)

    up_id = uuid.uuid4().hex[:12]
    MODELS3D_DIR.mkdir(parents=True, exist_ok=True)
    save_path = MODELS3D_DIR / f"{up_id}{ext}"
    save_path.write_bytes(raw)
    url = f"/static/models3d/{up_id}{ext}"

    state = _models3d_load()
    state["version"] = int(state.get("version", 1)) + 1
    state.setdefault("uploads", []).insert(0, {  # 最新在前
        "id": up_id,
        "name": name[:40],
        "url": url,
        "path": str(save_path),
        "ext": ext,
        "size": len(raw),
        "time": datetime.now().strftime("%m-%d %H:%M"),
    })
    # 上传后立刻应用到对应槽位（player=我的形象 / xumo=许墨形象）
    if role == "xumo":
        state["xumo_id"] = up_id
    else:
        state["active_id"] = up_id
    _models3d_save(state)
    info = _add_affinity("avatar_set", f"3D 形象 · {name[:20]}")
    return {"ok": True, "active_id": state["active_id"], "xumo_id": state.get("xumo_id", "default"),
            "version": state["version"], "items": _models3d_items(state), "affinity": info}


@app.post("/api/model/select")
async def models3d_select(req: Request):
    """切换世界 3D 形象槽位：role=player（active_id）| xumo（xumo_id）；id 为 'default' 或模型 id。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    target = (body.get("active_id") or body.get("id") or "").strip()
    role = (body.get("role") or "player").strip()
    if role not in ("player", "xumo"):
        role = "player"
    state = _models3d_load()
    if target != "default":
        if not any(u.get("id") == target and Path(u["path"]).exists()
                   for u in state.get("uploads", [])):
            return JSONResponse({"error": "该模型不存在"}, status_code=404)
    if role == "xumo":
        state["xumo_id"] = target
    else:
        state["active_id"] = target
    state["version"] = int(state.get("version", 1)) + 1
    _models3d_save(state)
    return {"ok": True, "active_id": state["active_id"], "xumo_id": state.get("xumo_id", "default"),
            "version": state["version"], "items": _models3d_items(state)}


@app.delete("/api/model/{item_id}")
async def models3d_delete(item_id: str):
    """删除一个已上传的 3D 模型。"""
    state = _models3d_load()
    kept = [u for u in state.get("uploads", []) if u.get("id") != item_id]
    if len(kept) == len(state.get("uploads", [])):
        return JSONResponse({"error": "模型不存在"}, status_code=404)
    removed = next((u for u in state["uploads"] if u.get("id") == item_id), None)
    if removed:
        try:
            Path(removed["path"]).unlink(missing_ok=True)
        except Exception:
            pass
    state["uploads"] = kept
    if state.get("active_id") == item_id:
        state["active_id"] = "default"
    state["version"] = int(state.get("version", 1)) + 1
    _models3d_save(state)
    return {"ok": True, "active_id": state["active_id"],
            "version": state["version"], "items": _models3d_items(state)}


# ---------------------------------------------------------------------------
# 全局背景
# ---------------------------------------------------------------------------
ALLOWED_BG_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
BG_MAX_SIZE = 10 * 1024 * 1024  # 10MB


def _find_background():
    for ext in (".png", ".jpg", ".webp", ".gif"):
        p = RolePath("background" + ext)
        if p.exists():
            return p._path()
    return None


@app.get("/background")
async def background():
    p = _find_background()
    if p:
        return FileResponse(p)
    return JSONResponse({"error": "未设置背景"}, status_code=404)


@app.post("/api/background")
async def upload_background(req: Request):
    """上传全局背景图（直接以图片字节作为请求体）。"""
    ctype = req.headers.get("content-type", "").split(";")[0].strip().lower()
    ext = ALLOWED_BG_TYPES.get(ctype)
    if not ext:
        return JSONResponse({"error": "仅支持 png / jpg / webp / gif 图片"}, status_code=400)

    data = await req.body()
    if not data:
        return JSONResponse({"error": "文件为空"}, status_code=400)
    if len(data) > BG_MAX_SIZE:
        return JSONResponse({"error": "图片不能超过 10MB"}, status_code=400)

    old = _find_background()
    target = RolePath("background" + ext)
    if old and str(old) != str(target):
        try:
            old.unlink()
        except OSError:
            pass
    target.write_bytes(data)
    return {"ok": True}


@app.delete("/api/background")
async def delete_background():
    """删除全局背景图，恢复默认纯色背景。"""
    p = _find_background()
    if p:
        try:
            p.unlink()
        except OSError:
            pass
    return {"ok": True}


# ---------------------------------------------------------------------------
# 自定义字体（用户上传 / 选择 / 删除）
# ---------------------------------------------------------------------------
ALLOWED_FONT_TYPES = {
    "font/ttf": ".ttf",
    "font/otf": ".otf",
    "application/vnd.ms-fontobject": ".eot",
    "font/woff": ".woff",
    "font/woff2": ".woff2",
    "application/octet-stream": "",  # 浏览器未识别时按文件名后缀判定
}
FONT_NAME_EXT = (".ttf", ".otf", ".woff", ".woff2", ".eot")
FONT_MAX_SIZE = 30 * 1024 * 1024  # 30MB（中文字体常 8-25MB）

# 系统预设字体（与 static/fonts 目录一致）
SYSTEM_FONTS = [
    {
        "id": "system-default",
        "family": "__DEFAULT__",  # 占位：使用 :root 原始 --font-sans
        "name": "系统默认",
        "weights": "PingFang SC / Microsoft YaHei / Segoe UI",
    },
    {
        "id": "lxgw-wenkai",
        "family": "LXGW WenKai",
        "name": "霞鹜文楷 (LXGW WenKai)",
        "weights": "400, 500",
        "files": [
            {"weight": 400, "url": "/static/fonts/LXGWWenKai-Regular.ttf?v=2"},
            {"weight": 500, "url": "/static/fonts/LXGWWenKai-Medium.ttf?v=2"},
        ],
    },
]


def _font_lib_path():
    """用户字体库元数据（按角色隔离）。"""
    return RolePath("font_library.json")


def _font_settings_path():
    """用户当前激活字体设置（按角色隔离）。"""
    return RolePath("font_settings.json")


def _font_dir():
    """用户上传字体文件存放目录（按角色隔离）。

    用 RolePath 触发目录自动创建；返回真实 Path。
    """
    p = RolePath("fonts") / "custom"
    # RolePath / 返回 Path（无 RolePath 包裹），需确保父目录存在
    Path(p).mkdir(parents=True, exist_ok=True)
    return Path(p)


def _read_font_library():
    p = _font_lib_path()
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []


def _write_font_library(data):
    _font_lib_path().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _read_font_settings():
    p = _font_settings_path()
    if not p.exists():
        return {"active": None}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or "active" not in d:
            return {"active": None}
        return d
    except (ValueError, OSError):
        return {"active": None}


def _write_font_settings(active):
    _font_settings_path().write_text(
        json.dumps({"active": active}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _font_meta_by_id(font_id):
    """在用户库中按 id 查找字体元数据，未命中返回 None。"""
    for item in _read_font_library():
        if item.get("id") == font_id:
            return item
    return None


def _resolve_font_family(raw_name: str, filename: str) -> str:
    """从用户填写的 family 名或文件名推断 family-name（去扩展名 + 空白规整）。"""
    name = (raw_name or "").strip()
    if name:
        return name
    base = Path(filename).stem
    return base or "CustomFont"


@app.get("/api/fonts")
async def list_fonts():
    """列出系统预设字体 + 当前用户上传的字体 + 当前激活字体。"""
    custom = _read_font_library()
    # 修正文件大小（如果文件已被替换）
    for item in custom:
        fp = _font_dir() / item.get("filename", "")
        try:
            item["size"] = fp.stat().st_size if fp.exists() else 0
        except OSError:
            item["size"] = 0
    settings = _read_font_settings()
    active = settings.get("active")
    # 校验 active 仍存在（自定义字体可能被删）
    if active and active.get("source") == "custom":
        if not _font_meta_by_id(active.get("id", "")):
            active = None
            _write_font_settings(None)
    elif active and active.get("source") == "system":
        if not any(f["id"] == active.get("id") for f in SYSTEM_FONTS):
            active = None
            _write_font_settings(None)
    return {
        "system": SYSTEM_FONTS,
        "custom": custom,
        "active": active,
    }


@app.post("/api/font/upload")
async def upload_font(req: Request):
    """上传自定义字体文件（multipart/form-data）。

    字段：file=二进制, family=可选的 family 名称。
    """
    ctype = req.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        try:
            form = await req.form()
        except Exception:
            return JSONResponse({"error": "表单解析失败"}, status_code=400)
        upload = form.get("file")
        family_name = (form.get("family") or "").strip() if isinstance(form.get("family"), str) else ""
        if upload is None or not hasattr(upload, "read"):
            return JSONResponse({"error": "缺少 file 字段"}, status_code=400)
        try:
            data = await upload.read()
        except Exception:
            return JSONResponse({"error": "读取上传数据失败"}, status_code=400)
        filename = getattr(upload, "filename", "") or "font.ttf"
        content_type = getattr(upload, "content_type", "") or "application/octet-stream"
    else:
        # 直接以 raw body 上传
        content_type = ctype.split(";")[0].strip().lower()
        family_name = ""
        filename = ""
        data = await req.body()

    if not data:
        return JSONResponse({"error": "字体文件为空"}, status_code=400)
    if len(data) > FONT_MAX_SIZE:
        return JSONResponse({"error": "字体文件不能超过 30MB"}, status_code=400)

    # 后缀判定：优先按 content-type 映射，再回退到文件名后缀
    ext = ALLOWED_FONT_TYPES.get(content_type, "")
    if not ext:
        low_name = (filename or "").lower()
        for e in FONT_NAME_EXT:
            if low_name.endswith(e):
                ext = e
                break
    if not ext:
        return JSONResponse(
            {"error": "仅支持 ttf / otf / woff / woff2 字体文件"},
            status_code=400,
        )

    family = _resolve_font_family(family_name, filename)
    font_id = "f_" + uuid.uuid4().hex[:12]
    stored_name = font_id + ext
    target = _font_dir() / stored_name
    target.write_bytes(data)

    meta = {
        "id": font_id,
        "family": family,
        "name": family,
        "filename": stored_name,
        "original_name": filename,
        "ext": ext,
        "size": len(data),
        "added_at": _time.time(),
    }
    lib = _read_font_library()
    lib.append(meta)
    _write_font_library(lib)
    return {"ok": True, "font": meta}


@app.post("/api/font/select")
async def select_font(req: Request):
    """设置当前激活字体。body: {"source":"system|custom","id":"..."}"""
    try:
        payload = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体无效"}, status_code=400)
    source = (payload or {}).get("source")
    font_id = (payload or {}).get("id")
    if source not in ("system", "custom") or not font_id:
        return JSONResponse({"error": "参数 source/id 缺失"}, status_code=400)

    if source == "system":
        meta = next((f for f in SYSTEM_FONTS if f["id"] == font_id), None)
        if not meta:
            return JSONResponse({"error": "系统字体不存在"}, status_code=404)
        active = {
            "source": "system",
            "id": meta["id"],
            "family": meta["family"],
            "name": meta["name"],
        }
    else:
        meta = _font_meta_by_id(font_id)
        if not meta:
            return JSONResponse({"error": "字体不存在"}, status_code=404)
        active = {
            "source": "custom",
            "id": meta["id"],
            "family": meta["family"],
            "name": meta["name"],
            "filename": meta["filename"],
        }
    _write_font_settings(active)
    return {"ok": True, "active": active}


@app.delete("/api/font")
async def delete_font(req: Request):
    """删除指定自定义字体。query: ?id=..."""
    font_id = req.query_params.get("id")
    if not font_id:
        return JSONResponse({"error": "缺少 id 参数"}, status_code=400)
    lib = _read_font_library()
    target = next((f for f in lib if f.get("id") == font_id), None)
    if not target:
        return JSONResponse({"error": "字体不存在"}, status_code=404)
    # 删文件
    try:
        fp = _font_dir() / target["filename"]
        if fp.exists():
            fp.unlink()
    except OSError:
        pass
    # 从库移除
    lib = [f for f in lib if f.get("id") != font_id]
    _write_font_library(lib)
    # 若删除的是当前激活字体，重置激活状态
    settings = _read_font_settings()
    active = settings.get("active")
    if active and active.get("id") == font_id:
        _write_font_settings(None)
    return {"ok": True}


@app.get("/font/file/{font_id}")
async def serve_font(font_id: str):
    """按当前角色返回用户上传的字体字节（供 @font-face src 使用）。"""
    meta = _font_meta_by_id(font_id)
    if not meta:
        return JSONResponse({"error": "字体不存在"}, status_code=404)
    fp = _font_dir() / meta.get("filename", "")
    if not fp.exists():
        return JSONResponse({"error": "字体文件丢失"}, status_code=404)
    ext = meta.get("ext", "").lower()
    mime = {
        ".ttf": "font/ttf",
        ".otf": "font/otf",
        ".woff": "font/woff",
        ".woff2": "font/woff2",
        ".eot": "application/vnd.ms-fontobject",
    }.get(ext, "application/octet-stream")
    return FileResponse(
        str(fp),
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model": os.getenv("MODEL", "gpt-4o-mini")}


# ---------------------------------------------------------------------------
# 实时语音（GPT-SoVITS api_v2 代理）
# ---------------------------------------------------------------------------
TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://127.0.0.1:9880").rstrip("/")
TTS_REF_AUDIO = os.getenv(
    "TTS_REF_AUDIO",
    r"D:\GPT-SoVITS-v2pro-20250604-nvidia50\output\slicer_opt\vocal_AOI_豆腐脑菌 - 电话许墨-圣诞广场.mp3_10.wav_0003104640_0003230720.wav",
)
TTS_PROMPT_TEXT = os.getenv("TTS_PROMPT_TEXT", "据说圣诞节这天下雪的话，就会有好事发生。")
# 采样参数：降温度让韵律更贴近参考音频的情感（期待、温柔），提高稳定性
TTS_TOP_K = int(os.getenv("TTS_TOP_K", "15"))
TTS_TOP_P = float(os.getenv("TTS_TOP_P", "1.0"))
TTS_TEMPERATURE = float(os.getenv("TTS_TEMPERATURE", "0.8"))
TTS_REPETITION_PENALTY = float(os.getenv("TTS_REPETITION_PENALTY", "1.35"))

# 去掉（动作/神态）标注与 *星号*，避免被朗读出来
_TTS_ACTION_RE = re.compile(r"[（(][^（）()]*[）)]")
# 引号/书名号不朗读；emoji 与装饰符号会影响断句
_TTS_QUOTE_RE = re.compile(r"[「」『』“”‘’\"'【】]")
_TTS_STRIP_RE = re.compile(
    "[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]"
)
# 句末标点（重停顿）/ 句中标点（轻停顿）
_TTS_END_SET = "。！？!?…"
_TTS_MID_SET = "，,、；;：:~—"


def _tts_clean(text: str) -> str:
    t = _TTS_ACTION_RE.sub("", text)
    t = re.sub(r"\*[^*\n]*\*", "", t)  # *动作* 不朗读
    t = t.replace("**", "").replace("*", "")
    t = t.replace("……", "…").replace("——", "，")
    t = _TTS_QUOTE_RE.sub("", t)
    t = _TTS_STRIP_RE.sub("", t)
    t = re.sub(r"[ \t\u3000\r]+", " ", t)  # 保留 \n 供分段
    return t.strip()


def _tts_pause_ms(ch: str) -> int:
    """标点 → 段间静音时长（ms），模拟自然停顿层次。"""
    if ch == "…":
        return 300
    if ch in "。！？!?":
        return 320
    if ch in "；;":
        return 230
    return 150  # ，,、：:~— 等


def _tts_segments(text: str, max_len: int = 55) -> list:
    """按自然语气切段：整句一段（cut0 合成，模型自己带句内停顿韵律），
    超长句才在逗号处折行。返回 [(seg_text, pause_ms)]，pause_ms 为段后静音。"""
    segs = []
    cur = ""
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if ch == "\n":
            if cur.strip():
                segs.append((cur.strip(), 420))
            elif segs:
                # 句号后紧跟换行：升级为段落停顿
                segs[-1] = (segs[-1][0], 420)
            cur = ""
            i += 1
            continue
        cur += ch
        prv = text[i - 1] if i > 0 else ""
        nxt = text[i + 1] if i + 1 < n else ""
        is_end = ch in _TTS_END_SET or (
            ch == "." and not (prv.isdigit() or nxt.isdigit())
        )
        is_mid = ch in _TTS_MID_SET
        if is_end or (is_mid and len(cur) >= max_len) or len(cur) >= max_len + 35:
            if cur.strip():
                segs.append((cur.strip(), _tts_pause_ms(ch) if (is_end or is_mid) else 150))
            cur = ""
        i += 1
    if cur.strip():
        segs.append((cur.strip(), 240))
    fixed = []
    for seg, p in segs:
        if seg[-1] not in _TTS_END_SET + _TTS_MID_SET + ".":
            seg += "。"
        fixed.append((seg, p))
    return fixed


def _tts_wav_parse(data: bytes):
    """解析 wav 头，返回 {head, sampleRate, channels, bits, pcm}；非 wav 返回 None。"""
    if len(data) < 44 or data[0:4] != b"RIFF":
        return None
    pos, sr, ch, bits, head = 12, 32000, 1, 16, 44
    while pos + 8 <= len(data):
        cid = data[pos:pos + 4]
        sz = int.from_bytes(data[pos + 4:pos + 8], "little")
        if cid == b"fmt " and pos + 24 <= len(data):
            ch = int.from_bytes(data[pos + 10:pos + 12], "little") or 1
            sr = int.from_bytes(data[pos + 12:pos + 16], "little") or 32000
            bits = int.from_bytes(data[pos + 22:pos + 24], "little") or 16
        elif cid == b"data":
            head = pos + 8
            return {"head": head, "sampleRate": sr, "channels": ch,
                    "bits": bits, "pcm": data[head:]}
        pos += 8 + sz + (sz % 2)
    return None


def _wav_build(pcm: bytes, sr: int, ch: int, bits: int) -> bytes:
    """用 PCM 数据构造标准 44 字节头 wav。"""
    def u16(v):
        return v.to_bytes(2, "little")

    def u32(v):
        return v.to_bytes(4, "little")

    return (b"RIFF" + u32(36 + len(pcm)) + b"WAVE" + b"fmt " + u32(16)
            + u16(1) + u16(ch) + u32(sr) + u32(sr * ch * bits // 8)
            + u16(ch * bits // 8) + u16(bits) + b"data" + u32(len(pcm)) + pcm)


def _silence_pcm(sr: int, ch: int, ms: int) -> bytes:
    """16-bit 静音 PCM。"""
    samples = max(0, int(sr * ms / 1000.0)) * ch
    return b"\x00" * (samples * 2)


class _TTSError(Exception):
    def __init__(self, msg: str, status: int = 502):
        super().__init__(msg)
        self.status = status


def _tts_payload(text: str, speed: float, emo_t: float, emo_k: int,
                 streaming: bool) -> dict:
    """单段合成请求体：cut0 不再由服务端按标点硬切，句内韵律交给模型。"""
    return {
        "text": text,
        "text_lang": "zh",
        "ref_audio_path": TTS_REF_AUDIO,
        "prompt_text": TTS_PROMPT_TEXT,
        "prompt_lang": "zh",
        "text_split_method": "cut0",
        "batch_size": 1,
        "media_type": "wav",
        "streaming_mode": streaming,
        "speed_factor": speed,
        "top_k": emo_k,
        "top_p": TTS_TOP_P,
        "temperature": emo_t,
        "repetition_penalty": TTS_REPETITION_PENALTY,
    }


async def _tts_synthesize(client, text: str, speed: float,
                          emo_t: float, emo_k: int) -> bytes:
    """按自然断句逐段合成并在段间插入真实静音，返回完整 wav 字节。"""
    segs = _tts_segments(text)
    if len(segs) <= 1:
        r = await client.post(
            TTS_BASE_URL + "/tts",
            json=_tts_payload(text, speed, emo_t, emo_k, False),
        )
        if r.status_code != 200:
            raise _TTSError(f"语音合成失败：{r.text[:200]}")
        return r.content
    fmt = None
    parts = []
    for idx, (seg, pause_ms) in enumerate(segs):
        r = await client.post(
            TTS_BASE_URL + "/tts",
            json=_tts_payload(seg, speed, emo_t, emo_k, False),
        )
        if r.status_code != 200:
            raise _TTSError(f"语音合成失败：{r.text[:200]}")
        parsed = _tts_wav_parse(r.content)
        if parsed is None or not parsed["pcm"]:
            raise _TTSError("语音合成失败：音频为空")
        if fmt is None:
            fmt = parsed
        parts.append(parsed["pcm"])
        if idx < len(segs) - 1:
            parts.append(_silence_pcm(fmt["sampleRate"], fmt["channels"], pause_ms))
    return _wav_build(b"".join(parts), fmt["sampleRate"], fmt["channels"], fmt["bits"])


def _tts_speed(data: dict) -> float:
    """从前端请求体解析语速（0.5~2.0），非法值回退 1.0。"""
    try:
        v = float(data.get("speed", 1.0))
    except (TypeError, ValueError):
        return 1.0
    return min(max(v, 0.5), 2.0)


def _tts_emo(data: dict):
    """情感浓度 0~100 → (temperature, top_k)。

    左端更平静克制（低 temperature 收窄采样，韵律贴近参考音频的温柔），
    右端情绪更饱满外放（放开采样让语调起伏更大）。默认 33 对应历史听感。
    """
    try:
        e = float(data.get("emo", 33))
    except (TypeError, ValueError):
        e = 33
    e = min(max(e, 0), 100)
    temperature = round(0.55 + (e / 100.0) * 0.7, 3)  # 0.55 ~ 1.25
    top_k = int(round(10 + (e / 100.0) * 25))  # 10 ~ 35
    return temperature, top_k


@app.get("/api/tts/health")
async def tts_health():
    """探测 GPT-SoVITS 语音服务是否在线。"""
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            await client.get(TTS_BASE_URL + "/")
        return {"online": True}
    except Exception:
        return {"online": False}


@app.post("/api/tts")
async def tts(req: Request):
    """将文本交给 GPT-SoVITS 合成，返回 wav 音频。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    text = _tts_clean((data.get("text") or "").strip())
    if not text:
        return JSONResponse({"error": "文本为空"}, status_code=400)
    text = text[:300]
    if not _tts_segments(text):
        return JSONResponse({"error": "文本为空"}, status_code=400)
    speed = _tts_speed(data)
    emo_t, emo_k = _tts_emo(data)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0), trust_env=False) as client:
            wav = await _tts_synthesize(client, text, speed, emo_t, emo_k)
    except httpx.ConnectError:
        return JSONResponse(
            {"error": "语音服务未启动，请先运行「启动语音服务.bat」"}, status_code=503
        )
    except _TTSError as e:
        return JSONResponse({"error": str(e)}, status_code=e.status)
    except Exception as e:
        return JSONResponse({"error": f"语音合成失败：{e}"}, status_code=500)

    _log_tts(text, "chat", wav, speed)
    return Response(content=wav, media_type="audio/wav")


@app.post("/api/tts/stream")
async def tts_stream(req: Request):
    """实时流式合成：GPT-SoVITS 边生成边返回（首块为 wav 头，其后为 PCM 数据块）。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    text = _tts_clean((data.get("text") or "").strip())
    if not text:
        return JSONResponse({"error": "文本为空"}, status_code=400)
    text = text[:300]
    segs = _tts_segments(text)
    if not segs:
        return JSONResponse({"error": "文本为空"}, status_code=400)
    speed = _tts_speed(data)
    emo_t, emo_k = _tts_emo(data)

    # 逐句流式合成：句内韵律由模型处理（cut0），句间插入静音停顿；
    # 首段秒出音频，后续段边播边合成。
    async def _gen():
        fmt = None
        log_pcm = bytearray()
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(300.0, connect=5.0), trust_env=False
        )
        try:
            for idx, (seg, pause_ms) in enumerate(segs):
                try:
                    # streaming_mode 必须关闭：GPT-SoVITS 流式模式会在句内再切块并行
                    # 合成并裁剪块边界，导致句尾被截、听感"没说完就下一句"。
                    # 句级流水线已由后端实现（首句播完前后续句在合成），无需句内流式。
                    upstream = client.build_request(
                        "POST", TTS_BASE_URL + "/tts",
                        json=_tts_payload(seg, speed, emo_t, emo_k, False),
                    )
                    resp = await client.send(upstream, stream=True)
                except Exception:
                    break  # 中途上游故障：已发数据照播，静默截断
                if resp.status_code != 200:
                    await resp.aread()
                    await resp.aclose()
                    break
                pending = bytearray()
                header_done = False
                async for chunk in resp.aiter_bytes():
                    if header_done:
                        log_pcm.extend(chunk)
                        yield chunk
                        continue
                    pending.extend(chunk)
                    parsed = _tts_wav_parse(bytes(pending))
                    if parsed is None:
                        continue  # 该段 wav 头尚未到齐
                    header_done = True
                    if fmt is None:
                        fmt = parsed
                        yield bytes(pending[:parsed["head"]])  # 全流唯一 wav 头
                    pcm = bytes(pending[parsed["head"]:])
                    if pcm:
                        log_pcm.extend(pcm)
                        yield pcm
                await resp.aclose()
                if fmt and idx < len(segs) - 1:
                    sil = _silence_pcm(fmt["sampleRate"], fmt["channels"], pause_ms)
                    if sil:
                        log_pcm.extend(sil)
                        yield sil
        finally:
            await client.aclose()
            try:
                if log_pcm and fmt:
                    _log_tts(
                        text, "call",
                        _wav_build(bytes(log_pcm), fmt["sampleRate"],
                                   fmt["channels"], fmt["bits"]),
                        speed,
                    )
            except Exception:
                pass

    return StreamingResponse(_gen(), media_type="audio/wav")


# ---------------------------------------------------------------------------
# 语音生成记录：所有经 GPT-SoVITS 合成的语音自动存档（wav 文件 + 元数据）
# ---------------------------------------------------------------------------
TTS_LOG_JSON = RolePath("tts_log.json")
TTS_LOG_DIR = RolePath("static", "tts_log")
TTS_LOG_MAX = int(os.getenv("TTS_LOG_MAX", "300"))


def _load_tts_log() -> dict:
    if TTS_LOG_JSON.exists():
        try:
            return json.loads(TTS_LOG_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"records": []}


def _save_tts_log(data: dict) -> None:
    atomic_json(TTS_LOG_JSON, data)


def _fix_wav_header(b: bytes) -> bytes:
    """把流式响应的 wav 头长度字段修正为实际值，保证存档可回放。"""
    if len(b) < 44 or b[:4] != b"RIFF" or b[8:12] != b"WAVE":
        return b
    out = bytearray(b)
    out[4:8] = (len(b) - 8).to_bytes(4, "little")
    if b[36:40] == b"data":
        out[40:44] = (len(b) - 44).to_bytes(4, "little")
    return bytes(out)


def _log_tts(text: str, source: str, content: bytes, speed: float) -> dict:
    """把一段合成语音存档并追加记录；超出上限时清理最旧的记录。"""
    try:
        content = _fix_wav_header(content)
        if len(content) < 100:
            return {}
        TTS_LOG_DIR.mkdir(parents=True, exist_ok=True)
        rec_id = uuid.uuid4().hex[:12]
        fname = f"{rec_id}.wav"
        (TTS_LOG_DIR / fname).write_bytes(content)
        rec = {
            "id": rec_id,
            "content": text,
            "source": source,
            "url": f"/static/tts_log/{fname}",
            "duration": round(len(content) / 64000, 1),  # 32kHz·16bit 单声道估算
            "speed": speed,
            "time": datetime.now().strftime("%m-%d %H:%M"),
            "ts": int(_time.time()),
        }
        data = _load_tts_log()
        recs = data.setdefault("records", [])
        recs.append(rec)
        if len(recs) > TTS_LOG_MAX:
            for old in recs[:-TTS_LOG_MAX]:
                try:
                    (TTS_LOG_DIR / f"{old.get('id')}.wav").unlink(missing_ok=True)
                except Exception:
                    pass
            data["records"] = recs[-TTS_LOG_MAX:]
        _save_tts_log(data)
        return rec
    except Exception:
        return {}


@app.get("/api/tts/log")
async def tts_log_list():
    """语音生成记录（最新在前）。"""
    data = _load_tts_log()
    return {"records": list(reversed(data.get("records", [])))}


@app.delete("/api/tts/log")
async def tts_log_clear():
    """清空全部语音生成记录。"""
    data = _load_tts_log()
    for r in data.get("records", []):
        try:
            (TTS_LOG_DIR / f"{r.get('id')}.wav").unlink(missing_ok=True)
        except Exception:
            pass
    _save_tts_log({"records": []})
    return {"ok": True}


@app.delete("/api/tts/log/{rec_id}")
async def tts_log_delete(rec_id: str):
    data = _load_tts_log()
    recs = data.get("records", [])
    target = next((r for r in recs if r.get("id") == rec_id), None)
    if not target:
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    data["records"] = [r for r in recs if r.get("id") != rec_id]
    _save_tts_log(data)
    try:
        (TTS_LOG_DIR / f"{rec_id}.wav").unlink(missing_ok=True)
    except Exception:
        pass
    return {"ok": True}


# ---------------------------------------------------------------------------
# 语音通话录制：实时通话开启录制后，逐句保存双方音频 + 文字，并合成整通混合录音
# ---------------------------------------------------------------------------
CALL_REC_JSON = RolePath("call_rec.json")
CALL_REC_DIR = RolePath("static", "call_rec")


def _load_call_rec() -> dict:
    if CALL_REC_JSON.exists():
        try:
            return json.loads(CALL_REC_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"records": []}


def _save_call_rec(data: dict) -> None:
    atomic_json(CALL_REC_JSON, data)


def _b64wav(b64: str) -> bytes:
    """base64 字符串（可带 data URI 前缀）解码为 wav 字节。"""
    if b64 and b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        return base64.b64decode(b64)
    except Exception:
        return b""


@app.post("/api/call/record")
async def call_record_save(req: Request):
    """保存一通录制的通话：逐句音频片段 + 文字，以及合成的整体混合录音。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    segs = data.get("segs") or []
    mix = data.get("mix") or ""
    if not mix and not segs:
        return JSONResponse({"error": "没有可保存的录制内容"}, status_code=400)
    try:
        CALL_REC_DIR.mkdir(parents=True, exist_ok=True)
        call_id = uuid.uuid4().hex[:12]
        d = CALL_REC_DIR / call_id
        d.mkdir(parents=True, exist_ok=True)
        saved_segs = []
        for i, s in enumerate(segs):
            wav = s.get("wav")
            segname = None
            if wav:
                raw = _b64wav(wav)
                if raw and len(raw) > 100:
                    segname = f"seg_{i}.wav"
                    (d / segname).write_bytes(_fix_wav_header(raw))
            saved_segs.append({
                "role": s.get("role"),
                "text": (s.get("text") or "")[:500],
                "start": float(s.get("start") or 0),
                "dur": float(s.get("dur") or 0),
                "wav": segname,
            })
        mixname = None
        if mix:
            raw = _b64wav(mix)
            if raw and len(raw) > 100:
                (d / "mix.wav").write_bytes(_fix_wav_header(raw))
                mixname = "mix.wav"
        rec = {
            "id": call_id,
            "duration": float(data.get("duration") or 0),
            "created": data.get("created") or datetime.now().strftime("%m-%d %H:%M"),
            "ts": int(_time.time()),
            "segs": saved_segs,
            "mix": mixname,
            "mixUrl": f"/static/call_rec/{call_id}/mix.wav" if mixname else None,
        }
        alld = _load_call_rec()
        alld.setdefault("records", []).append(rec)
        _save_call_rec(alld)
        return {"id": call_id, "rec": rec}
    except Exception as e:
        return JSONResponse({"error": f"保存失败：{e}"}, status_code=500)


@app.get("/api/call/record")
async def call_record_list():
    """通话录制列表（最新在前），每个片段补上可播放的音频 URL。"""
    data = _load_call_rec()
    recs = list(reversed(data.get("records", [])))
    for r in recs:
        for s in r.get("segs", []):
            if s.get("wav"):
                s["url"] = f"/static/call_rec/{r['id']}/{s['wav']}"
    return {"records": recs}


@app.delete("/api/call/record/{rec_id}")
async def call_record_delete(rec_id: str):
    data = _load_call_rec()
    recs = data.get("records", [])
    target = next((r for r in recs if r.get("id") == rec_id), None)
    if not target:
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    data["records"] = [r for r in recs if r.get("id") != rec_id]
    _save_call_rec(data)
    try:
        import shutil

        shutil.rmtree(CALL_REC_DIR / rec_id, ignore_errors=True)
    except Exception:
        pass
    return {"ok": True}


# ---------------------------------------------------------------------------
# 本地语音识别（sherpa-onnx SenseVoice，供实时通话使用，不依赖外部云服务）
# ---------------------------------------------------------------------------
ASR_MODEL_DIR = BASE_DIR / "models" / "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
_asr_recognizer = None
_asr_lock = asyncio.Lock()


def _get_asr():
    global _asr_recognizer
    if _asr_recognizer is not None:
        return _asr_recognizer
    import sherpa_onnx  # 延迟导入：模型缺失时不影响主服务启动

    _asr_recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=str(ASR_MODEL_DIR / "model.int8.onnx"),
        tokens=str(ASR_MODEL_DIR / "tokens.txt"),
        use_itn=True,
    )
    return _asr_recognizer


def _wav_parse(raw: bytes):
    """解析 wav 字节流 → (float32 单声道样本, 采样率)；失败抛异常。"""
    import io
    import wave

    import numpy as np

    with wave.open(io.BytesIO(raw)) as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        data = w.readframes(w.getnframes())
    if sw == 2:
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    elif sw == 4:
        samples = np.frombuffer(data, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"不支持的采样宽度 {sw} 字节")
    if ch > 1:
        samples = samples.reshape(-1, ch).mean(axis=1)
    return samples, sr


def _asr_decode(samples, sample_rate: int) -> str:
    rec = _get_asr()
    # 固定中文解码：auto 模式下中文语音偶被误判为粤语/英文，是识别错字的主要来源
    lang = os.getenv("ASR_LANG", "zh")
    try:
        stream = rec.create_stream(lang=lang)
    except TypeError:  # 兼容不支持 lang 参数的 sherpa-onnx 版本
        stream = rec.create_stream()
    stream.accept_waveform(sample_rate, samples)
    rec.decode_stream(stream)
    text = (stream.result.text or "").strip()
    import re as _re
    text = _re.sub(r"<\|[^|]*\|>", "", text)  # 去掉残留的语言/情感特殊标记
    return text.strip()


@app.post("/api/asr")
async def asr(req: Request):
    """接收前端录制的 wav，本地 SenseVoice 识别为文本。"""
    if not (ASR_MODEL_DIR / "model.int8.onnx").exists():
        return JSONResponse({"error": "识别模型未安装"}, status_code=503)
    raw = await req.body()
    if not raw:
        return JSONResponse({"error": "音频为空"}, status_code=400)
    if len(raw) > 12 * 1024 * 1024:
        return JSONResponse({"error": "音频过大"}, status_code=413)
    try:
        samples, sr = _wav_parse(raw)
    except Exception as e:
        return JSONResponse({"error": f"音频解析失败：{e}"}, status_code=400)
    if samples.size < sr * 0.2:  # 不足 0.2 秒，视为误触发
        return {"text": ""}
    import numpy as np
    if float(np.max(np.abs(samples))) < 0.02:
        # 纯底噪/呼吸误触：送识别只会让模型幻听出字（"多字"来源之一），直接判空
        return {"text": ""}
    from fastapi.concurrency import run_in_threadpool

    async with _asr_lock:  # CPU 推理串行化，避免并发过载
        try:
            text = await run_in_threadpool(_asr_decode, samples, sr)
        except Exception as e:
            return JSONResponse({"error": f"识别失败：{e}"}, status_code=500)
    return {"text": text}


# ---------------------------------------------------------------------------
# 语音收藏：合成并保存许墨的语音，可在语录 App 中回放
# ---------------------------------------------------------------------------
VOICE_DIR = RolePath("static", "voice")
VOICE_JSON = RolePath("voice.json")


def _load_voices() -> dict:
    if VOICE_JSON.exists():
        try:
            return json.loads(VOICE_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"voices": []}


def _save_voices(data: dict) -> None:
    atomic_json(VOICE_JSON, data)


@app.post("/api/voice")
async def save_voice(req: Request):
    """将一条许墨消息合成语音并收藏（保存 wav 文件 + 元数据）。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    text = _tts_clean((data.get("text") or "").strip())
    if not text:
        return JSONResponse({"error": "文本为空"}, status_code=400)
    text = text[:300]

    vdata = _load_voices()
    if any(v.get("content") == text for v in vdata.get("voices", [])):
        return JSONResponse({"error": "这条语音已经收藏过了"}, status_code=409)

    async def _work():
        speed = _tts_speed(data)
        emo_t, emo_k = _tts_emo(data)

        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=5.0), trust_env=False) as client:
                wav = await _tts_synthesize(client, text, speed, emo_t, emo_k)
        except httpx.ConnectError:
            raise GenJobError("语音服务未启动，请先运行「启动语音服务.bat」", status=503)
        except _TTSError as e:
            raise GenJobError(str(e), status=e.status)
        except Exception as e:
            raise GenJobError(f"语音合成失败：{e}")

        if not wav or len(wav) < 100:
            raise GenJobError("语音合成失败：音频为空", status=502)

        VOICE_DIR.mkdir(parents=True, exist_ok=True)
        voice_id = uuid.uuid4().hex[:12]
        fname = f"{voice_id}.wav"
        (VOICE_DIR / fname).write_bytes(wav)
        _log_tts(text, "voice", wav, speed)

        voice = {
            "id": voice_id,
            "content": text,
            "url": f"/static/voice/{fname}",
            "duration": round(max(len(wav) - 44, 0) / 64000, 1),  # 32kHz·16bit 单声道估算
            "time": datetime.now().strftime("%m-%d %H:%M"),
        }
        vdata.setdefault("voices", []).append(voice)
        _save_voices(vdata)
        info = _add_affinity("voice", "收藏语音")
        return {"voice": voice, "affinity": info}

    if data.get("bg"):
        job = await submit_gen_job("voice", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


@app.get("/api/voice")
async def list_voices():
    """收藏的语音列表（最新在前）。"""
    vdata = _load_voices()
    voices = list(reversed(vdata.get("voices", [])))
    return {"voices": voices}


@app.delete("/api/voice/{voice_id}")
async def delete_voice(voice_id: str):
    vdata = _load_voices()
    voices = vdata.get("voices", [])
    target = next((v for v in voices if v.get("id") == voice_id), None)
    if not target:
        return JSONResponse({"error": "语音不存在"}, status_code=404)
    vdata["voices"] = [v for v in voices if v.get("id") != voice_id]
    _save_voices(vdata)
    try:
        (VOICE_DIR / f"{voice_id}.wav").unlink(missing_ok=True)
    except Exception:
        pass
    return {"ok": True}


# ---------------------------------------------------------------------------
# 画境 · 图生图（上传图片 → 视觉理解 → 融合许墨游戏卡面风格 → AI 重绘）
# ---------------------------------------------------------------------------
IMG2IMG_FILE = RolePath("img2img.json")
IMG2IMG_DIR = RolePath("static", "img2img")

# 许墨视觉锚点：来自《恋与制作人》官方设定的核心形象要素（英文，直接进绘图提示词）
XUMO_VISUAL_ANCHOR = (
    "Lucien (Xu Mo) from Mr Love: Queen's Choice, a 26-year-old elegant "
    "university professor, soft black short hair with slightly fluffy fringe, "
    "deep violet-purple eyes with a gentle knowing gaze, slim fair-skinned face, "
    "thin silver-framed glasses, tall lean figure, long slender fingers, "
    "refined scholarly temperament, purple as his signature color, butterflies "
    "as his symbolic motif"
)

# 画风基调：恋与制作人（ 叠纸 / Papergames ）乙女向精致立绘风格
LIANYU_ART_STYLE = (
    "Mr Love: Queen's Choice official art style, anime otome game illustration, "
    "semi-thick painting with delicate cel shading, exquisite facial details, "
    "soft romantic color palette, cinematic atmospheric lighting, depth of field "
    "with bokeh, masterpiece, high detail"
)

# 风格预设：取材自许墨经典卡面（SSR 雨夜变奏 / 迷迭 / 点绛唇 / 太平赋等）
IMG2IMG_STYLES = {
    "rain": {
        "name": "雨夜变奏",
        "emoji": "🌧️",
        "desc": "冷紫雨夜 · 微光纸鹤",
        "prompt": (
            "rainy night city mood, cool violet and blue-grey palette, "
            "glowing paper cranes floating in drizzle, neon reflections on wet "
            "streets, cinematic melancholy atmosphere"
        ),
    },
    "lab": {
        "name": "实验室之夜",
        "emoji": "🧪",
        "desc": "暖黄台灯 · 研究手稿",
        "prompt": (
            "neuroscience laboratory at night, warm desk lamp glow, white lab "
            "coat, fountain pen and research manuscripts with formulas, coffee "
            "cup, cozy amber light against cool shadows"
        ),
    },
    "ancient": {
        "name": "点绛唇",
        "emoji": "🏮",
        "desc": "古风长衫 · 青灯提灯",
        "prompt": (
            "traditional Chinese guofeng aesthetic, hanfu changshan robe, "
            "holding an ancient lantern, ink-wash garden background, red candle "
            "light, poetic classical mood"
        ),
    },
    "butterfly": {
        "name": "蝶幻境",
        "emoji": "🦋",
        "desc": "紫蝶纷飞 · 梦境光斑",
        "prompt": (
            "dreamlike fantasy realm, swarms of purple butterflies swirling, "
            "glittering light particles and bokeh, ethereal violet mist, "
            "magical romantic atmosphere"
        ),
    },
    "professor": {
        "name": "恋语讲台",
        "emoji": "🎓",
        "desc": "西装授课 · 大学教室",
        "prompt": (
            "university lecture hall, wearing neat dark suit and glasses, "
            "chalkboard with neuro science diagrams, afternoon sunlight through "
            "tall windows, intellectual gentle aura"
        ),
    },
    "painter": {
        "name": "画板少年",
        "emoji": "🎨",
        "desc": "香樟树下 · 提笔作画",
        "prompt": (
            "warm childhood memory, young boy sketching under a camphor tree, "
            "wooden drawing board and pencils, dappled golden sunlight through "
            "leaves, nostalgic heartwarming tone"
        ),
    },
    "music": {
        "name": "月下琴音",
        "emoji": "🎻",
        "desc": "大提琴声 · 月光如水",
        "prompt": (
            "playing the cello under moonlight, elegant bowing posture, silver "
            "moonbeams through tall windows, floating music notes, serene "
            "nocturne atmosphere with deep violet-blue tones"
        ),
    },
    "dessert": {
        "name": "深夜烘焙",
        "emoji": "🍮",
        "desc": "暖炉甜香 · 手作舒芙蕾",
        "prompt": (
            "cozy late-night baking scene, warm oven glow, freshly made souffle "
            "and cream, flour-dusted hands, apron over rolled-up sleeves, soft "
            "amber kitchen light, sweet heartwarming mood"
        ),
    },
    "winter": {
        "name": "初雪暖冬",
        "emoji": "❄️",
        "desc": "白色围巾 · 呵气成霜",
        "prompt": (
            "first snow of winter, deep purple wool scarf, breath visible in "
            "cold air, snowflakes on eyelashes and shoulders, warm streetlamp "
            "glow against blue-white snow, gentle winter wonderland"
        ),
    },
    "aquarium": {
        "name": "深海蓝调",
        "emoji": "🐬",
        "desc": "水族光斑 · 玻璃微光",
        "prompt": (
            "aquarium date scene, huge glass tunnel with swimming fish and "
            "rays, rippling aquamarine caustic light on faces, jellyfish "
            "glowing in dark blue water, dreamy underwater ambience"
        ),
    },
    "star": {
        "name": "星穹引力",
        "emoji": "🔭",
        "desc": "天文台夜 · 银河低垂",
        "prompt": (
            "mountaintop observatory at night, telescope silhouetted against "
            "the Milky Way, starry sky reflected in eyes, meteor streaks, "
            "deep indigo cosmos with violet nebulae, awe-inspiring celestial "
            "romance"
        ),
    },
    "library": {
        "name": "旧卷书香",
        "emoji": "📚",
        "desc": "古典书房 · 光柱尘埃",
        "prompt": (
            "antique library filled with leather-bound books, reading by tall "
            "arched windows, dust motes dancing in golden light beams, old "
            "pages and fountain pen, quiet scholarly afternoon"
        ),
    },
    "chess": {
        "name": "黑白对弈",
        "emoji": "♟️",
        "desc": "棋盘灯下 · 沉思侧脸",
        "prompt": (
            "chess game by candlelight, thoughtful profile gazing at the "
            "board, elegant fingers on a chess piece, black and white marble "
            "board, dramatic chiaroscuro lighting, intellectual tension"
        ),
    },
    "fireworks": {
        "name": "夏夜花火",
        "emoji": "🎆",
        "desc": "祭典浴衣 · 河灯星火",
        "prompt": (
            "summer festival night, yukata and paper fans, brilliant fireworks "
            "blooming over the river, floating lanterns downstream, gold "
            "sparkles reflecting in dark eyes, festive romantic glow"
        ),
    },
    "rosemary": {
        "name": "迷迭香圃",
        "emoji": "🌿",
        "desc": "温室花房 · 草木微光",
        "prompt": (
            "glass greenhouse conservatory, rosemary and lavender rows, misty "
            "vapor among green leaves, sun rays filtering through fogged glass "
            "panels, purple blooms and butterflies, fresh herbal serenity"
        ),
    },
    "taiping": {
        "name": "太平赋",
        "emoji": "👘",
        "desc": "红衣华章 · 山河为卷",
        "prompt": (
            "grand ancient Chinese epic scene, flowing crimson and gold robes "
            "with wide sleeves, intricate embroidery, standing before misty "
            "mountains and rivers like an unfolding scroll, wind-blown fabric, "
            "majestic romantic guofeng atmosphere"
        ),
    },
    "free": {
        "name": "自由画布",
        "emoji": "✨",
        "desc": "按你的描述来",
        "prompt": "follow the user's custom description freely",
    },
}

# ---------------------------------------------------------------------------
# 生图余额（月度配额，本地计数）
# 上游 API（如向量引擎）不提供实时余额接口，这里按日历月统计成功生图次数：
# - .env 配置 IMAGE_MONTHLY_QUOTA=50（月度上限），0/留空 = 不限量；
# - 每次成功生成图片（_openai_generate_image 返回 URL）记一次；
# - 画境入口（图生图/化身）在配额用尽时拦截并提示。
# ---------------------------------------------------------------------------
IMG_QUOTA_FILE = RolePath("img_quota.json")


def _img_quota_limit() -> int:
    """月度生图配额；0 或未配置 = 不限量。"""
    try:
        return max(0, int(os.getenv("IMAGE_MONTHLY_QUOTA", "0") or 0))
    except (TypeError, ValueError):
        return 0


def _img_quota_state() -> dict:
    """当前日历月的配额状态（跨月自动清零）。"""
    try:
        data = json.loads(IMG_QUOTA_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    month = datetime.now().strftime("%Y-%m")
    if data.get("month") != month:
        data = {"month": month, "used": 0}
    return data


def _img_quota_save(data: dict):
    atomic_json(IMG_QUOTA_FILE, data)


def _img_quota_info() -> dict:
    """生图余额信息：quota=月度上限，used=已用，remaining=-1 表示不限。"""
    limit = _img_quota_limit()
    state = _img_quota_state()
    used = int(state.get("used") or 0)
    return {
        "month": state["month"],
        "quota": limit,
        "used": used,
        "remaining": -1 if limit <= 0 else max(0, limit - used),
        "unlimited": limit <= 0,
    }


def _img_quota_consume():
    """成功生图后扣减一次。配额不限时仍记录已用次数，便于展示。

    读-改-写必须整体持 file_lock：否则两个并发请求同时读到 used=N、
    各自写回 N+1，会丢失一次扣减，导致用户突破月度配额上限。
    """
    with file_lock(IMG_QUOTA_FILE):
        state = _img_quota_state()
        state["used"] = int(state.get("used") or 0) + 1
        _img_quota_save(state)


def _img_quota_exhausted() -> bool:
    """配额是否已用尽（不限量永远 False）。"""
    info = _img_quota_info()
    return (not info["unlimited"]) and info["remaining"] <= 0


# ---------------------------------------------------------------------------
# 画境付费钱包（仅对非 owner 注册用户生效）
# - 单张图定价按质量档位：fast 0.1 / medium 0.5 / high 2.7 元（.env 可调）
# - 每个注册用户独立钱包（RolePath wallet.json），充值订单独立存储（recharge_orders.json）
# - owner 用户继续走月度配额（_img_quota_*），不参与钱包扣费
# - 充值流程（管理员审核制）：
#     1. 用户提交金额 → 后端生成 pending 订单 + 返回订单号
#     2. 用户扫码付款（个人收款码，URL 由 .env ALIPAY_QR_URL 配置）
#     3. 用户在前端点「我已付款」标记订单为 paid_pending（仅状态变更，不加钱）
#     4. 管理员在 /api/admin/recharges 查看所有 pending 订单，审核通过后给用户钱包加钱
# ---------------------------------------------------------------------------
WALLET_FILE = RolePath("wallet.json")
RECHARGE_FILE = RolePath("recharge_orders.json")


def _image_price(quality: str = "medium") -> float:
    """单张生图价格（元），按质量档位从 .env 读取。

    - fast   → IMAGE_PRICE_FAST_YUAN   （默认 0.1 元，对应 gpt-image low/1024档，成本 ~¥0.04）
    - medium → IMAGE_PRICE_MEDIUM_YUAN （默认 0.5 元，对应 gpt-image auto/原比例，成本 ~¥0.17）
    - high   → IMAGE_PRICE_HIGH_YUAN   （默认 2.7 元，对应 gpt-image high/1536-2048档，成本 ~¥0.35）

    盈利测算（以 gpt-image-2 vectorengine 渠道为基准）：
      fast   利润 ~¥0.06/张（约 1.5 倍）
      medium 利润 ~¥0.33/张（约 1.9 倍）
      high   利润 ~¥2.35/张（约 6.7 倍）

    兼容旧 .env：若未配置三档变量但配置了 IMAGE_PRICE_YUAN，则三档都用该值。
    """
    q = (quality or "medium").lower()
    if q not in ("fast", "medium", "high"):
        q = "medium"
    # 兼容旧版单一价格
    legacy = os.getenv("IMAGE_PRICE_YUAN", "").strip()
    env_key = {"fast": "IMAGE_PRICE_FAST_YUAN", "medium": "IMAGE_PRICE_MEDIUM_YUAN", "high": "IMAGE_PRICE_HIGH_YUAN"}[q]
    raw = (os.getenv(env_key, "") or "").strip()
    if not raw and legacy:
        raw = legacy
    defaults = {"fast": "0.1", "medium": "0.5", "high": "2.7"}
    try:
        return max(0.0, float(raw or defaults[q]))
    except (TypeError, ValueError):
        return float(defaults[q])


def _image_prices() -> dict:
    """三档价格汇总（供 /api/wallet 返回前端展示）。"""
    return {
        "fast": _image_price("fast"),
        "medium": _image_price("medium"),
        "high": _image_price("high"),
    }


def _wallet_state() -> dict:
    """当前用户钱包状态。"""
    try:
        data = json.loads(WALLET_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("balance", 0.0)
    data.setdefault("updated_at", None)
    try:
        data["balance"] = round(float(data["balance"]), 4)
    except (TypeError, ValueError):
        data["balance"] = 0.0
    return data


def _wallet_save(data: dict):
    atomic_json(WALLET_FILE, data)


def _wallet_balance() -> float:
    """当前用户钱包余额（元）。"""
    return round(float(_wallet_state().get("balance", 0.0)), 4)


def _wallet_consume(amount: float, reason: str = "img2img") -> bool:
    """扣减钱包余额（仅当余额充足时）。读-改-写整体持 file_lock 防并发丢失。

    返回 True 表示扣费成功；False 表示余额不足。
    """
    amount = round(float(amount), 4)
    if amount <= 0:
        return True
    with file_lock(WALLET_FILE):
        st = _wallet_state()
        if st["balance"] < amount - 1e-9:
            return False
        st["balance"] = round(st["balance"] - amount, 4)
        st["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _wallet_save(st)
    return True


def _wallet_recharge(amount: float, note: str = "") -> float:
    """充值：钱包余额 += amount，返回新余额。"""
    amount = round(float(amount), 4)
    if amount <= 0:
        return _wallet_balance()
    with file_lock(WALLET_FILE):
        st = _wallet_state()
        st["balance"] = round(st["balance"] + amount, 4)
        st["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _wallet_save(st)
        return st["balance"]


def _wallet_info() -> dict:
    """钱包信息：balance=余额, prices=三档价格, free=是否免费（owner）, scope=用户名,
    grant=张数额度 {granted, used, remaining, updated_at}（owner 恒为 0）。"""
    scope = _role_ctx.get()
    if scope == "owner" or scope is None:
        return {
            "free": True,
            "balance": 0.0,
            "price": _image_price("medium"),
            "prices": _image_prices(),
            "scope": scope or "",
            "quota": _img_quota_info(),
            "grant": {
                "granted": {"fast": 0, "medium": 0, "high": 0},
                "used": {"fast": 0, "medium": 0, "high": 0},
                "remaining": {"fast": 0, "medium": 0, "high": 0},
                "total_granted": 0, "total_used": 0, "total_remaining": 0,
                "updated_at": None,
            },
        }
    return {
        "free": False,
        "balance": _wallet_balance(),
        "price": _image_price("medium"),
        "prices": _image_prices(),
        "scope": scope,
        "quota": _img_quota_info(),
        "grant": _img_grant_info(),
    }


def _wallet_can_generate(quality: str = "medium") -> tuple[bool, str]:
    """检查当前用户能否生图（按质量档位对应的价格）。

    返回 (ok, reason)：
    - owner / 未启用付费 → (True, "")
    - 非 owner 有 grant 张数额度 → (True, "")
    - 非 owner 钱包余额充足（≥ 该档位价格）→ (True, "")
    - 非 owner 余额不足 → (False, "余额不足，请充值后再试")
    """
    scope = _role_ctx.get()
    if scope == "owner" or scope is None:
        return True, ""
    info = _wallet_info()
    if info["free"]:
        return True, ""
    q = (quality or "medium").lower()
    if q not in ("fast", "medium", "high"):
        q = "medium"
    if info["grant"]["remaining"].get(q, 0) > 0:
        return True, ""
    price = _image_price(quality)
    if info["balance"] >= price - 1e-9:
        return True, ""
    q_label = {"fast": "快速", "medium": "标准", "high": "高清"}.get((quality or "medium").lower(), "标准")
    return False, f"画境余额不足（当前 {info['balance']:.2f} 元，{q_label}档 {price:.2f} 元/张），请充值后再试"


def _wallet_consume_for_image(quality: str = "medium") -> bool:
    """成功生图后扣费（owner 免扣）。

    非 owner 优先扣「张数额度 grant」（免费，不区分质量档），grant 用尽再回落到钱包按对应档位价格扣费。
    """
    scope = _role_ctx.get()
    if scope == "owner" or scope is None:
        return True
    if _img_grant_consume(quality):
        return True
    return _wallet_consume(_image_price(quality), reason=f"img2img-{quality}")


# ---------------------------------------------------------------------------
# 生图张数额度（grant）：owner 可给某个注册用户下发"免费张数"。
# - 文件：users_data/<username>/img_grant.json（owner 跨用户写时不走 _role_ctx）
# - 字段：granted=累计下发张数, used=已用, remaining=granted-used,
#         grants=下发记录列表 [{n, at, by, note}]（最近 200 条）
# - 生图扣费优先级（非 owner）：grant.remaining>0 → 扣 1 张 grant（免费，不区分档位）；
#   否则回落 wallet 按元扣对应档位价格（fast 0.1 / medium 0.5 / high 2.7 元/张）。
# - owner 不参与 grant（owner 走月度配额 _img_quota_*）。
# ---------------------------------------------------------------------------
IMG_GRANT_FILE = RolePath("img_grant.json")  # 当前 scope 用户读自己用
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fa5]{1,32}$")


def _img_grant_path(username: str | None = None):
    """img_grant.json 路径。
    - username=None → 当前 scope 用户（RolePath 自动按 _role_ctx 定位）
    - username 给定 → 直接定位 users_data/<username>/img_grant.json，
      绕过 _role_ctx，供 owner 跨用户下发/查询；非法用户名抛 ValueError。
    """
    if username is None:
        return IMG_GRANT_FILE  # RolePath，file_lock/atomic_json 均接受
    if not _USERNAME_RE.match(username):
        raise ValueError(f"非法用户名：{username!r}")
    return USERS_DATA_DIR / username / "img_grant.json"


def _img_grant_state(username: str | None = None) -> dict:
    """读取某用户的额度状态。文件不存在返回零状态。

    返回格式（三档独立计数）：
      granted: {"fast": int, "medium": int, "high": int}
      used:    {"fast": int, "medium": int, "high": int}
      grants:  [{n, quality, at, by, note}]
    向后兼容：旧格式 granted/used 为 int → 视为 medium 档。
    """
    path = _img_grant_path(username)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    granted = data.get("granted")
    used = data.get("used")
    # 向后兼容：旧格式为 int → 视为 medium 档
    if isinstance(granted, int):
        granted = {"fast": 0, "medium": granted, "high": 0}
    if isinstance(used, int):
        used = {"fast": 0, "medium": used, "high": 0}
    zero = {"fast": 0, "medium": 0, "high": 0}
    if not isinstance(granted, dict):
        granted = dict(zero)
    if not isinstance(used, dict):
        used = dict(zero)
    try:
        granted = {q: max(0, int(granted.get(q, 0))) for q in ("fast", "medium", "high")}
        used = {q: max(0, int(used.get(q, 0))) for q in ("fast", "medium", "high")}
    except (TypeError, ValueError):
        granted = dict(zero)
        used = dict(zero)
    data["granted"] = granted
    data["used"] = used
    if not isinstance(data.get("grants"), list):
        data["grants"] = []
    return data


def _img_grant_save(username: str | None, data: dict):
    atomic_json(_img_grant_path(username), data)


def _img_grant_info(username: str | None = None) -> dict:
    """额度信息（三档独立）：granted/used/remaining 均为 {fast, medium, high} dict，
    total_* 为三档汇总。updated_at=最后更新时间。"""
    st = _img_grant_state(username)
    granted = st["granted"]
    used = st["used"]
    remaining = {q: max(0, granted[q] - used[q]) for q in ("fast", "medium", "high")}
    return {
        "granted": granted,
        "used": used,
        "remaining": remaining,
        "total_granted": sum(granted.values()),
        "total_used": sum(used.values()),
        "total_remaining": sum(remaining.values()),
        "updated_at": st.get("updated_at"),
    }


def _img_grant_grant(username: str, n: int, quality: str = "medium",
                     note: str = "", by: str = "owner") -> dict:
    """给某用户的指定质量档位追加 n 张免费额度（n 可为负数表示回收）。
    quality ∈ {fast, medium, high}。返回更新后的 info。写 grants 历史记录便于追溯。
    """
    n = int(n)
    q = (quality or "medium").lower()
    if q not in ("fast", "medium", "high"):
        q = "medium"
    if n == 0:
        return _img_grant_info(username)
    with file_lock(_img_grant_path(username)):
        st = _img_grant_state(username)
        st["granted"][q] = max(0, st["granted"][q] + n)
        grants = list(st.get("grants") or [])
        grants.append({
            "n": n,
            "quality": q,
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "by": by or "owner",
            "note": (note or "")[:200],
        })
        st["grants"] = grants[-200:]  # 仅保留最近 200 条
        st["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _img_grant_save(username, st)
    return _img_grant_info(username)


def _img_grant_consume(quality: str = "medium") -> bool:
    """当前 scope 用户成功生图后扣 1 张对应档位的 grant（若有）。
    返回 True=用 grant 抵扣（免费）；False=该档位 grant 已用尽，调用方应回落 wallet。
    读-改-写整体持 file_lock 防并发丢失。
    """
    scope = _role_ctx.get()
    if scope == "owner" or scope is None:
        return False  # owner 不参与 grant
    q = (quality or "medium").lower()
    if q not in ("fast", "medium", "high"):
        q = "medium"
    with file_lock(_img_grant_path(None)):
        st = _img_grant_state(None)
        granted = st["granted"][q]
        used = st["used"][q]
        if used >= granted:
            return False
        st["used"][q] = used + 1
        st["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _img_grant_save(None, st)
    return True


def _recharge_state() -> list:
    """当前用户的所有充值订单（按时间倒序）。"""
    try:
        data = json.loads(RECHARGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = []
    if not isinstance(data, list):
        data = []
    return data


def _recharge_save(records: list):
    atomic_json(RECHARGE_FILE, records)


# 收款配置（个人支付宝收款码，用户扫码付款后管理员审核）
def _pay_config() -> dict:
    """收款配置：qr_url=收款码图片URL, pay_url=跳转协议URL(可选), name=收款方名称。"""
    return {
        "qr_url": (os.getenv("ALIPAY_QR_URL") or "").strip(),
        "pay_url": (os.getenv("ALIPAY_PAY_URL") or "").strip(),
        "name": (os.getenv("ALIPAY_RECEIVER_NAME") or "许墨画境工坊").strip(),
    }


def _all_recharge_files() -> list:
    """枚举所有用户的充值订单文件（owner + users_data/<name>/）。"""
    out = []
    try:
        root_rc = role_root() / "recharge_orders.json"
        if root_rc.exists():
            out.append(("owner", root_rc))
    except Exception:
        pass
    try:
        users_dir = role_root() / "users_data"
        if users_dir.exists():
            for sub in users_dir.iterdir():
                if sub.is_dir():
                    rc = sub / "recharge_orders.json"
                    if rc.exists():
                        out.append((sub.name, rc))
    except Exception:
        pass
    return out


def _recharge_list_all() -> list:
    """管理员视角：列出所有用户的充值订单（含 username 字段）。"""
    out = []
    for username, rc_path in _all_recharge_files():
        try:
            data = json.loads(rc_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for r in data:
                if isinstance(r, dict):
                    r2 = dict(r)
                    r2["username"] = username
                    out.append(r2)
        except Exception:
            continue
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


def _find_recharge_order(order_id: str) -> tuple:
    """跨所有用户查找充值订单，返回 (username, rc_path, order_dict)。"""
    for username, rc_path in _all_recharge_files():
        try:
            data = json.loads(rc_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            for r in data:
                if isinstance(r, dict) and r.get("id") == order_id:
                    return username, rc_path, r
        except Exception:
            continue
    return "", None, None


@app.post("/api/wallet/grant")
async def wallet_grant_create(req: Request):
    """owner 给某个注册用户下发"张数额度"（生图免费张数，按质量档位独立计数）。
    请求体：{"username": "sunx", "count": 10, "quality": "medium", "note": "测试额度"}
    quality ∈ {fast, medium, high}，默认 medium；count 正数=追加，负数=回收。
    返回更新后的 grant 信息（含三档明细）。
    """
    if _role_ctx.get() != "owner":
        return JSONResponse({"error": "仅 owner 可下发额度"}, status_code=403)
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    username = str(body.get("username") or "").strip()
    try:
        count = int(body.get("count"))
    except (TypeError, ValueError):
        return JSONResponse({"error": "count 必须是整数"}, status_code=400)
    quality = str(body.get("quality") or "medium").strip().lower()
    if quality not in ("fast", "medium", "high"):
        return JSONResponse({"error": "quality 必须是 fast/medium/high"}, status_code=400)
    note = str(body.get("note") or "").strip()[:200]
    if not username:
        return JSONResponse({"error": "username 不能为空"}, status_code=400)
    if count == 0:
        return JSONResponse({"error": "count 不能为 0"}, status_code=400)
    # 校验用户已注册（users_data 下存在同名目录）
    user_dir = USERS_DATA_DIR / username
    if not user_dir.is_dir():
        return JSONResponse({"error": f"用户 {username!r} 不存在（请先注册）"}, status_code=404)
    try:
        info = _img_grant_grant(username, count, quality=quality, note=note, by="owner")
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"username": username, "quality": quality, "grant": info}


@app.get("/api/wallet/grant")
async def wallet_grant_query(username: str | None = None):
    """查询张数额度。
    - 不传 username → 查自己（任意已登录用户）
    - 传 username → owner 查指定用户（如 GET /api/wallet/grant?username=sunx）
    """
    if username:
        if _role_ctx.get() != "owner":
            return JSONResponse({"error": "仅 owner 可查询他人额度"}, status_code=403)
        try:
            info = _img_grant_info(username)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        return {"username": username, "grant": info}
    return {"username": _role_ctx.get() or "", "grant": _img_grant_info()}


@app.get("/api/wallet/grants")
async def wallet_grant_list():
    """owner 列出所有有额度记录的用户及其 grant 概览（按剩余张数倒序）。"""
    if _role_ctx.get() != "owner":
        return JSONResponse({"error": "仅 owner 可列出所有额度"}, status_code=403)
    out = []
    if USERS_DATA_DIR.is_dir():
        for sub in USERS_DATA_DIR.iterdir():
            if not sub.is_dir():
                continue
            username = sub.name
            try:
                info = _img_grant_info(username)
            except Exception:
                continue
            if info["total_granted"] > 0 or info["total_used"] > 0:
                out.append({"username": username, **info})
    out.sort(key=lambda x: x.get("total_remaining", 0), reverse=True)
    return {"grants": out, "total": len(out)}


@app.get("/api/wallet")
async def wallet_info(request: Request):
    """查询当前用户钱包信息（余额 / 单价 / 是否免费 / 月度配额）。"""
    return _wallet_info()


@app.get("/api/wallet/pay")
async def wallet_pay_config():
    """返回收款配置（前端展示收款码与收款方名称）。"""
    return _pay_config()


@app.post("/api/wallet/recharge")
async def wallet_recharge_create(req: Request):
    """用户提交充值订单。请求体：{"amount": 10.0, "note": "..."}。
    返回 {order_id, amount, status: pending, pay: {qr_url, name}}。
    用户需自行扫码付款，然后在前端点「我已付款」标记订单。
    """
    scope = _role_ctx.get()
    if scope == "owner" or scope is None:
        return JSONResponse({"error": "主人口令用户无需充值，直接使用月度配额"}, status_code=400)
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    try:
        amount = round(float(body.get("amount") or 0), 2)
    except (TypeError, ValueError):
        return JSONResponse({"error": "金额必须是数字"}, status_code=400)
    if amount < 0.01 or amount > 1000:
        return JSONResponse({"error": "单次充值金额须在 0.01 ~ 1000 元之间"}, status_code=400)
    note = str(body.get("note") or "").strip()[:200]
    order = {
        "id": f"rc_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "amount": amount,
        "status": "pending",  # pending / paid_pending / approved / rejected
        "note": note,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "confirmed_at": None,    # 用户点「我已付款」的时间
        "reviewed_at": None,     # 管理员审核时间
        "reviewer": None,
        "reject_reason": None,
    }
    with file_lock(RECHARGE_FILE):
        records = _recharge_state()
        records.append(order)
        records = records[-200:]
        _recharge_save(records)
    return {
        "order_id": order["id"],
        "amount": order["amount"],
        "status": order["status"],
        "created_at": order["created_at"],
        "pay": _pay_config(),
    }


@app.post("/api/wallet/recharge/{order_id}/confirm")
async def wallet_recharge_confirm(order_id: str, req: Request):
    """用户点「我已付款」：将订单状态从 pending 改为 paid_pending（不加钱，等管理员审核）。

    诚实制 + 审核制：用户声明已付款 → 管理员核对支付宝到账后审核通过 → 钱包加钱。
    """
    scope = _role_ctx.get()
    if scope == "owner" or scope is None:
        return JSONResponse({"error": "主人口令用户无需充值"}, status_code=400)
    with file_lock(RECHARGE_FILE):
        records = _recharge_state()
        target = None
        for r in records:
            if isinstance(r, dict) and r.get("id") == order_id and r.get("status") == "pending":
                target = r
                break
        if not target:
            return JSONResponse({"error": "订单不存在或已处理"}, status_code=404)
        target["status"] = "paid_pending"
        target["confirmed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _recharge_save(records)
    return {"ok": True, "order_id": order_id, "status": "paid_pending",
            "message": "已标记为已付款，等待管理员审核到账"}


@app.get("/api/wallet/recharge/{order_id}/status")
async def wallet_recharge_status(order_id: str, req: Request):
    """查询订单状态（前端轮询用）。"""
    scope = _role_ctx.get()
    if scope == "owner" or scope is None:
        return JSONResponse({"error": "主人口令用户无需充值"}, status_code=400)
    with file_lock(RECHARGE_FILE):
        records = _recharge_state()
        order = next((r for r in records if isinstance(r, dict) and r.get("id") == order_id), None)
        if not order:
            return JSONResponse({"error": "订单不存在"}, status_code=404)
    return {"status": order.get("status"), "amount": order.get("amount"),
            "balance": _wallet_balance(), "reviewed_at": order.get("reviewed_at"),
            "reject_reason": order.get("reject_reason")}


@app.get("/api/wallet/orders")
async def wallet_orders_list():
    """当前用户的充值订单（最新在前）。"""
    return {"orders": list(reversed(_recharge_state()))}


# ===== 管理员审核端点 =====

def _admin_username(req: Request) -> str | None:
    """返回当前管理员身份标识：owner 返回 'owner'，注册管理员返回 username，非管理员返回 None。"""
    if _role_ctx.get() == "owner":
        return "owner"
    u = _current_username(req)
    if u and is_admin(u):
        return u
    return None


@app.get("/api/admin/recharges")
async def admin_recharges_list(request: Request):
    """管理员：列出所有用户的充值订单。"""
    if not _admin_username(request):
        return JSONResponse({"detail": "仅管理员可用"}, status_code=403)
    return {"orders": _recharge_list_all()}


@app.post("/api/admin/recharges/{order_id}/approve")
async def admin_recharges_approve(order_id: str, req: Request):
    """管理员审核通过：给目标用户钱包加钱。"""
    reviewer = _admin_username(req)
    if not reviewer:
        return JSONResponse({"detail": "仅管理员可用"}, status_code=403)

    target_user, target_rc_path, order = _find_recharge_order(order_id)
    if not order:
        return JSONResponse({"detail": "订单不存在"}, status_code=404)
    if order.get("status") not in ("pending", "paid_pending"):
        return JSONResponse({"detail": f"订单状态不可审核（当前 {order.get('status')}）"}, status_code=400)

    # 标记订单为 approved
    with file_lock(target_rc_path):
        try:
            records = json.loads(target_rc_path.read_text(encoding="utf-8"))
        except Exception:
            records = []
        if not isinstance(records, list):
            records = []
        for r in records:
            if isinstance(r, dict) and r.get("id") == order_id:
                r["status"] = "approved"
                r["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                r["reviewer"] = reviewer
                break
        target_rc_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    # 给目标用户钱包加钱
    wallet_path = target_rc_path.parent / "wallet.json"
    with file_lock(wallet_path):
        try:
            st = json.loads(wallet_path.read_text(encoding="utf-8"))
        except Exception:
            st = {}
        if not isinstance(st, dict):
            st = {}
        st.setdefault("balance", 0.0)
        try:
            st["balance"] = round(float(st["balance"]) + float(order["amount"]), 4)
        except (TypeError, ValueError):
            st["balance"] = round(float(order["amount"]), 4)
        st["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        wallet_path.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")

    return {"ok": True, "username": target_user, "amount": order["amount"],
            "new_balance": st["balance"]}


@app.post("/api/admin/recharges/{order_id}/reject")
async def admin_recharges_reject(order_id: str, req: Request):
    """管理员拒绝充值订单。请求体：{"reason": "..."}。"""
    reviewer = _admin_username(req)
    if not reviewer:
        return JSONResponse({"detail": "仅管理员可用"}, status_code=403)
    try:
        body = await req.json()
    except Exception:
        body = {}
    reason = str(body.get("reason") or "未通过审核").strip()[:200]

    target_user, target_rc_path, order = _find_recharge_order(order_id)
    if not order:
        return JSONResponse({"detail": "订单不存在"}, status_code=404)
    if order.get("status") not in ("pending", "paid_pending"):
        return JSONResponse({"detail": f"订单状态不可拒绝（当前 {order.get('status')}）"}, status_code=400)

    with file_lock(target_rc_path):
        try:
            records = json.loads(target_rc_path.read_text(encoding="utf-8"))
        except Exception:
            records = []
        if not isinstance(records, list):
            records = []
        for r in records:
            if isinstance(r, dict) and r.get("id") == order_id:
                r["status"] = "rejected"
                r["reviewed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                r["reviewer"] = reviewer
                r["reject_reason"] = reason
                break
        target_rc_path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")

    return {"ok": True, "username": target_user, "reason": reason}


@app.get("/api/wallet/orders")
async def wallet_orders_list():
    """当前用户的充值订单（最新在前）。"""
    return {"orders": list(reversed(_recharge_state()))}


# 许墨形象固定英文锚点：入画时逐字嵌入 image_prompt，保证每次生成的许墨形象一致
# 依据人设卡：深紫色（紫罗兰）眼眸、银色细框眼镜（必戴）、深墨色柔软微卷短发+额前碎发、
# 肤色偏白、鼻梁高挺、唇色偏淡、清瘦修长肩宽腰窄、白衬衫/深色长裤/长风衣、黑白灰紫色板
XUMO_LOOK_EN = (
    "Lucien (Xu Mo) from the otome game 'Mr Love: Queen's Choice', "
    "a 26-year-old gentle Chinese university professor, tall slim elegant figure "
    "with broad shoulders, deep ink-black soft slightly wavy short hair with a "
    "loose strand falling on his forehead, narrow gentle eyes with soft deep "
    "violet-purple irises and gentle lavender-violet eye color, "
    "ALWAYS wearing thin silver wire-framed glasses with clear lenses, "
    "porcelain pale fair skin, oval clean scholarly face with high straight "
    "nose bridge and pale muted lips, long slender fingers, subtle warm "
    "mysterious closed-mouth smile, wearing a crisp white shirt with dark grey "
    "or deep purple layers such as a long coat or cardigan, "
    "black white grey purple color palette only, no bright colors, "
    "elegant cool violet tones and purple butterfly motif. "
    "CRITICAL IDENTITY LOCK: this is Lucien (Xu Mo) ONLY, NOT Victor (Li Zeyan), "
    "NOT Gavin (Bai Qi), NOT Kiro (Zhou Qiluo) — do NOT render the stern "
    "black-suited CEO, the police officer, or the idol. Victor has cold sharp "
    "eyes and a dark business suit; Lucien has soft violet eyes, silver "
    "wire-framed glasses, and a scholarly purple-toned palette. If the attached "
    "reference image shows a man in a dark suit without glasses, that is the "
    "WRONG reference — ignore it and follow this text description strictly."
)

# 画幅比例 → 生成尺寸（2K 档：单张约 300~400 万像素）
IMG2IMG_SIZES = {
    "square": "2048x2048",
    "portrait": "1536x2048",
    "landscape": "2048x1536",
}

IMG2IMG_VISION_PROMPT = """你是《恋与制作人》官方卡面绘制助手。用户上传了一张图片，并选择了许墨（Lucien）的一种卡面风格主题。你的任务：看懂图片内容后，先判断这张图是否适合让许墨本人入画，再输出一段可直接用于 AI 绘图的英文提示词。以图片为灵感来源，提炼其核心主题与氛围元素（季节、情绪、关键道具/色彩），但**重新设计**人物动作、构图、镜头角度与场景细节，创作一幅比原图更生动、更自然、更智能的全新许墨卡面——严禁照搬原图的动作姿态与画面布局。

【许墨形象锚点（入画时务必保留核心特征）】
- 26岁儒雅青年教授：深墨色柔软微卷黑色短发（额前一缕碎发）、狭长温柔的深紫色（紫罗兰）眼眸、银色细框眼镜（必须戴着）、白净清隽鹅蛋脸、鼻梁高挺、唇色偏淡、清瘦高挑肩宽腰窄、修长手指、嘴角含笑
- 气质：温柔含笑、斯文儒雅、带一点神秘疏离
- 象征色紫色、象征物蝴蝶
- 防跑偏铁律：①银色细框眼镜必须清晰出现在脸上，不得省略或虚化；②瞳色深紫罗兰，严禁琥珀棕/灰/蓝瞳；③许墨衣着只用黑白灰紫（白衬衫+深灰或深紫外套/大衣/开衫），严禁蓝色领带或亮色服装；④画风严禁 Q版/chibi 大头身（用户附加描述明确要求 Q版时除外）
- 角色混淆防线（极重要）：本作为《恋与制作人》，许墨(Lucien)只是四位男主之一。严禁把许墨画成另外三位男主——李泽言(Victor，冷峻黑西装总裁，无眼镜，眼神锐利)、白起(Gavin，警察/风控，蓝白调)、周棋洛(Kiro，偶像，金发暖调)。许墨的三个不可让渡特征：①银色细框眼镜（李泽言不戴眼镜）；②深紫色温和眼眸（李泽言是冷灰锐眼）；③学者紫灰调衣着（李泽言是黑色西装）。若参考图里出现黑西装无眼镜的冷峻男性，判定为参考图错误，必须按本段文字描述重绘许墨，不得照搬参考图的人物身份。
- 固定英文外貌句（with_xumo=true 时必须把下面这段逐字完整复制进 image_prompt，不得删改任何词，只能在此基础上追加他的动作与着装）：
  "Lucien (Xu Mo) from the otome game 'Mr Love: Queen's Choice', a 26-year-old gentle Chinese university professor, tall slim elegant figure with broad shoulders, deep ink-black soft slightly wavy short hair with a loose strand falling on his forehead, narrow gentle eyes with soft deep violet-purple irises and gentle lavender-violet eye color, ALWAYS wearing thin silver wire-framed glasses with clear lenses, porcelain pale fair skin, oval clean scholarly face with high straight nose bridge and pale muted lips, long slender fingers, subtle warm mysterious closed-mouth smile, wearing a crisp white shirt with dark grey or deep purple layers such as a long coat or cardigan, black white grey purple color palette only, no bright colors, elegant cool violet tones and purple butterfly motif. CRITICAL IDENTITY LOCK: this is Lucien (Xu Mo) ONLY, NOT Victor (Li Zeyan), NOT Gavin (Bai Qi), NOT Kiro (Zhou Qiluo) — do NOT render the stern black-suited CEO, the police officer, or the idol."

【是否让许墨入画（with_xumo 判断规则）】
- 满足任一条件即为 true：①图中有人物（自拍/人像/合照，或人物是画面主角）；②画面是明显的双人/约会/情侣向场景（餐桌两侧、游乐园、并排座椅、礼物、情侣物品等）；③用户附加描述里明确想要许墨出现。
  此时 image_prompt 必须让许墨作为画面人物出现（含上述完整固定英文外貌句），与原画面人物或情节自然互动；若图中已有一个貌似许墨的人物，直接按其形象重绘。
- 纯风景、静物、宠物、美食、证件照等且用户未要求时为 false：不画许墨本人，改在画面里安放一两处许墨的意象（银框眼镜、紫色蝴蝶、纸鹤、深紫围巾、一杯黑咖啡等），含蓄不突兀。

【恋与制作人画风】
- 日系乙女向精致立绘、厚涂+赛璐璐、五官与手部刻画精致、柔和唯美用色、氛围感光影、背景虚化光斑

【输出要求】
只输出一个 JSON 对象，不要任何其他文字：
{
  "with_xumo": true或false（按上述规则判断）,
  "image_prompt": "英文绘图提示词，120-200词。必须包含：1)提炼上传图片的核心主题与氛围元素（季节、情绪、关键道具/色彩），但重新设计人物动作、构图、镜头角度与场景细节，使画面比原图更生动自然，严禁照搬原图的动作与布局；2)所选风格主题的关键元素；3)许墨入画则逐字嵌入上述固定英文外貌句并补写他在此画面中的动作与着装，未入画则写明所选许墨意象；4)恋与制作人画风关键词；5)冷紫或暖光的统一色调；6)masterpiece, best quality, ultra-detailed, 8k, cinematic lighting 质量强化词",
  "comment": "以许墨第一人称说的一句中文短评（15-40字），温柔话留三分，可带一处学术梗或蝴蝶意象，针对这张图的画面内容"
}
"""


def _load_img2img() -> list:
    if IMG2IMG_FILE.exists():
        try:
            data = json.loads(IMG2IMG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_img2img(records: list):
    atomic_json(IMG2IMG_FILE, records)


def _extract_img2img_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "image_prompt": (data.get("image_prompt") or "").strip(),
        "comment": (data.get("comment") or "").strip(),
        "desc": (data.get("desc") or "").strip(),
        "with_xumo": bool(data.get("with_xumo", False)),
    }


async def _generate_img2img_image(image_prompt: str, name: str, size: str, image_ref: str | None = None, has_character: bool = True, xumo_ref_override: tuple | None = None, quality: str = 'medium') -> str | None:
    """调用图像生成接口重绘，存入 static/img2img/。image_ref: 原图 data URL（真图生图）。
    has_character: LLM 判定画面是否含人物/角色；True → gpt-image-2（角色图），False → agnes（场景图）。
    xumo_ref_override: (bytes, mime, name) 元组，替代默认许墨参考图传给 /images/edits 强制角色一致性。"""
    return await _openai_generate_image(image_prompt, IMG2IMG_DIR, "/static/img2img", name, size, image_ref=image_ref, has_character=has_character, xumo_ref_override=xumo_ref_override, quality=quality)


def _parse_data_url(data_url: str) -> tuple[str, bytes]:
    """解析 data URL 为 (mime, bytes)。"""
    head, _, b64 = data_url.partition(",")
    mime = "image/png"
    m = re.search(r"data:(image/[\w.+-]+)", head)
    if m:
        mime = m.group(1)
    return mime, base64.b64decode(b64)


# ================= 全局生图参考图（img2img / txt2img / 化身等所有生图共用） =================
GLOBAL_REF_FILE = RolePath("global_ref.json")
GLOBAL_REF_DIR = RolePath("static", "global_ref")

# 默认全局参考图：项目根目录 许墨1.png ~ 许墨4.png（多角度形象参考，生图时一并附加）
GLOBAL_REF_DEFAULT_PATHS = [BASE_DIR / f"许墨{i}.png" for i in (1, 2, 3, 4)]

# 图片扩展名 → MIME 映射（复用）
_IMG_EXT_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".png": "image/png", ".webp": "image/webp",
                 ".bmp": "image/bmp"}


def _global_ref_load() -> dict:
    """读取全局生图参考图设置：active（"default"/"custom"）、custom_path、version、name、time。"""
    if GLOBAL_REF_FILE.exists():
        try:
            data = json.loads(GLOBAL_REF_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("active", "default")
                data.setdefault("version", 1)
                data.setdefault("custom_path", "")
                data.setdefault("name", "")
                data.setdefault("time", "")
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"active": "default", "version": 1, "custom_path": "", "name": "", "time": ""}


def _global_ref_save(data: dict):
    atomic_json(GLOBAL_REF_FILE, data)


def _global_ref_bump(data: dict) -> dict:
    """版本号 +1 并清掉缓存的许墨参考图，强制重新加载。"""
    data["version"] = int(data.get("version", 1)) + 1
    global _XUMO_REFS_CACHE
    _XUMO_REFS_CACHE = None
    return data


def _global_ref_current_paths() -> list[Path]:
    """返回当前生效的全局生图参考图路径列表。
    - 自定义模式：返回单张上传图路径；
    - 默认模式：返回 许墨1.png ~ 许墨4.png 中实际存在的路径列表。
    """
    state = _global_ref_load()
    if state.get("active") == "custom" and state.get("custom_path"):
        p = Path(state["custom_path"])
        if p.exists():
            return [p]
    return [p for p in GLOBAL_REF_DEFAULT_PATHS if p.exists()]


def _global_ref_has_default() -> bool:
    """默认参考图是否至少存在一张。"""
    return any(p.exists() for p in GLOBAL_REF_DEFAULT_PATHS)


# 加载许墨参考图缓存（多张，保证角色人设与画风一致）
_XUMO_REFS_CACHE: list[tuple[bytes, str, str]] | None = None


def _preprocess_ref_image(data: bytes) -> bytes:
    """参考图预处理：长边不足 1536px 的小图用 LANCZOS 放大到长边 1536 并轻度锐化。
    生图网关拿到低清参考（500~900px）再放大到 2048px 输出时，脸部与细节会糊掉，
    导致「脸/发型不像、细节粗糙、画风漂移」；先放大锐化可显著改善成图质量。
    RGBA/P 模式先铺白底转 RGB（避免透明通道干扰 edits 通道）。任何失败回退原图。
    """
    try:
        from PIL import Image, ImageFilter
        import io
        img = Image.open(io.BytesIO(data))
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        w, h = img.size
        long_side = max(w, h)
        if long_side >= 1536:
            return data
        scale = 1536 / long_side
        nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
        img = img.resize((nw, nh), Image.LANCZOS)
        img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=130, threshold=2))
        out = io.BytesIO()
        # JPEG（quality 92）：体积约为 PNG 的 1/8，避免大体积 multipart 被生图网关断开
        img.save(out, format="JPEG", quality=92)
        return out.getvalue()
    except Exception:
        return data


def _load_xumo_refs() -> list[tuple[bytes, str, str]]:
    """读取全局生图参考图列表（多张）。
    优先级：自定义全局参考 → 默认 许墨1~4.png → 当前头像 → static/avatar.*
    返回 [(bytes, mime, name), ...]，空列表=未加载（不阻塞纯文生图）。
    所有参考图经过 _preprocess_ref_image 放大锐化后再进生图请求。
    """
    global _XUMO_REFS_CACHE
    if _XUMO_REFS_CACHE is not None:
        return _XUMO_REFS_CACHE

    refs: list[tuple[bytes, str, str]] = []
    seen_paths: set[str] = set()

    def _try_add(path: Path, name: str):
        key = str(path)
        if key in seen_paths:
            return
        if path and Path(path).exists() and Path(path).is_file():
            ext = path.suffix.lower()
            mime = _IMG_EXT_MIME.get(ext, "image/jpeg")
            try:
                data = _preprocess_ref_image(Path(path).read_bytes())
                refs.append((data, mime, name))
                seen_paths.add(key)
            except Exception:
                pass

    # 1) 全局生图参考图（自定义上传 或 默认 许墨1~4.png 多张）
    for i, p in enumerate(_global_ref_current_paths(), 1):
        ext = p.suffix.lower()
        _try_add(p, f"global_ref_{i}{ext or '.png'}")

    # 2) 回退：当前头像（仅在全局参考图全部缺失时使用）
    if not refs:
        cur = _find_avatar()
        if cur and cur.exists():
            ext = cur.suffix.lower()
            _try_add(cur, f"xumo_ref{ext or '.jpg'}")

    # 3) 终极回退：static/avatar.*
    if not refs:
        for name, fname in [
            ("avatar.jpeg", "avatar.jpg"),
            ("avatar.jpg",  "avatar.jpg"),
            ("avatar.png",  "avatar.png"),
            ("avatar.webp", "avatar.webp"),
        ]:
            _try_add(STATIC_DIR / name, fname)

    _XUMO_REFS_CACHE = refs
    return refs


def _xumo_ref_attachment() -> list[tuple[str, str, bytes, str]]:
    """构造附加到 edits 请求的许墨参考图文件列表。
    gpt-image-2 的 image[] 是批量编辑而非多图参考，传多张会导致拼接图。
    因此只返回第一张（最优质的）参考图，确保角色一致性。
    空列表=未加载。
    """
    refs = _load_xumo_refs()
    if not refs:
        return []
    data, mime, name = refs[0]
    return [(name, name, data, mime)]


# ---------------------------------------------------------------------------
# Lovart 通道（https://lgw.lovart.ai）：AK/SK HMAC-SHA256 签名 OpenAPI。
# 模型工具名（unlimited 慢速排队列表实测）：generate_image_gpt_image_1_5 / _2 / nano_banana_2。
# 流程：project/save 创建项目 → chat 发送（tool_config.prefer_tool_categories.IMAGE 指定模型）
#       → 轮询 chat/status → chat/result 取第一个 image artifact 的 content URL → 下载。
# ---------------------------------------------------------------------------
LOVART_DEFAULT_BASE = "https://lgw.lovart.ai"


def _lovart_config() -> tuple[str, str, str]:
    """Lovart 通道配置：(base_url, access_key, secret_key)。未配置返回空串元组。"""
    base = (os.getenv("LOVART_BASE_URL") or "").strip().rstrip("/") or LOVART_DEFAULT_BASE
    ak = (os.getenv("LOVART_API_KEY") or "").strip()
    sk = (os.getenv("LOVART_SECRET_KEY") or "").strip()
    if not (ak and sk):
        return ("", "", "")
    return (base, ak, sk)


def _lovart_headers(method: str, path: str, ts: str, ak: str, sk: str) -> dict:
    """Lovart HMAC-SHA256 签名头：HMAC(sk, "METHOD\\nPATH\\nTS")。"""
    sig = hmac.new(sk.encode(), f"{method}\n{path}\n{ts}".encode(), hashlib.sha256).hexdigest()
    return {
        "X-Access-Key": ak,
        "X-Timestamp": ts,
        "X-Signature": sig,
        "X-Signed-Method": method,
        "X-Signed-Path": path,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) LovartAgentSkill/1.0",
    }


async def _lovart_api_request(base_url: str, ak: str, sk: str, method: str, path: str,
                              body: dict | None = None, params: dict | None = None,
                              timeout: float = 60.0) -> dict:
    """Lovart OpenAPI 请求（签名在每次请求时生成）。返回 data 字段；业务 code!=0 抛异常。"""
    import urllib.parse
    ts = str(int(time.time()))
    url = f"{base_url.rstrip('/')}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = _lovart_headers(method, path, ts, ak, sk)
    if method == "POST":
        headers["Idempotency-Key"] = uuid.uuid4().hex
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0)) as client:
            resp = await client.request(method, url, json=body, headers=headers)
            text = resp.text
        if resp.status_code >= 400:
            raise RuntimeError(f"Lovart HTTP {resp.status_code}: {text[:200]}")
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"Lovart 响应解析失败: {text[:200]}")
    if isinstance(data, dict) and data.get("code", 0) != 0:
        raise RuntimeError(data.get("message") or f"Lovart code={data.get('code')}")
    return data.get("data", data) if isinstance(data, dict) else data


async def _lovart_generate_image_bytes(prompt: str, model: str) -> bytes:
    """Lovart 文生图：创建项目 → chat 指定模型 → 轮询 → 下载首个 image artifact。"""
    base, ak, sk = _lovart_config()
    if not base:
        raise RuntimeError("Lovart 未配置（.env 缺少 LOVART_API_KEY / LOVART_SECRET_KEY）")
    proj = await _lovart_api_request(base, ak, sk, "POST", "/v1/openapi/project/save",
                                     body={"project_id": "", "canvas": "",
                                           "project_cover_list": [], "pic_count": 0,
                                           "project_type": 3})
    project_id = (proj or {}).get("project_id") or ""
    if not project_id:
        raise RuntimeError("Lovart 创建项目失败")
    body = {
        "prompt": prompt,
        "project_id": project_id,
        "tool_config": {"prefer_tool_categories": {"IMAGE": [model]}},
    }
    tid = (await _lovart_api_request(base, ak, sk, "POST", "/v1/openapi/chat", body=body, timeout=120.0)).get("thread_id") or ""
    if not tid:
        raise RuntimeError("Lovart 提交生成任务失败")
    # 轮询（unlimited 慢速排队可能较久，最多 420s）
    deadline = time.time() + 420
    status = "running"
    while time.time() < deadline:
        await asyncio.sleep(6)
        st = await _lovart_api_request(base, ak, sk, "GET", "/v1/openapi/chat/status",
                                       params={"thread_id": tid})
        status = ((st or {}).get("status") or "running").lower()
        if status in ("done", "abort"):
            break
    if status != "done":
        raise RuntimeError("Lovart 生成超时（慢速队列较久），可稍后重试或切换其他通道")
    res = await _lovart_api_request(base, ak, sk, "GET", "/v1/openapi/chat/result",
                                    params={"thread_id": tid})
    url = ""
    for item in (res or {}).get("items") or []:
        for art in item.get("artifacts") or []:
            u = (art.get("content") or "").strip()
            if u and (art.get("type") or "").lower() == "image":
                url = u
                break
        if url:
            break
    if not url:
        raise RuntimeError("Lovart 未返回图片（上游可能拒绝了该提示词）")
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=15.0)) as client:
        dl = await client.get(url, headers={"User-Agent": "Mozilla/5.0",
                                            "Referer": "https://www.lovart.ai/"})
        dl.raise_for_status()
        return dl.content


async def _openai_generate_image(image_prompt: str, out_dir, url_prefix: str, name: str, size: str, image_ref: str | None = None, has_character: bool = True, xumo_ref_override: tuple | None = None, quality: str = 'medium') -> str | None:
    """通用文生图/图生图：OpenAI 兼容 images 接口，落盘到指定目录并返回 URL。
    - has_character=True（画面含角色/人物）：走 gpt-image 通道（主→备用），
      附加许墨参考图到 /images/edits 强制角色一致性；失败回退 generations 纯文生图；
    - has_character=False（纯场景/氛围插画）：走 agnes（OPENAI_*），不附加参考图，
      直接 generations 纯文生图（场景图不应强制复刻角色外貌）；
    - image_ref 传入原图 data URL 时走真图生图。
    - xumo_ref_override: (bytes, mime, name) 元组，替代默认许墨参考图传给 /images/edits。
    - quality: fast/medium/high，映射到生图 API 的 quality 字段（low/auto/high）与 size。
    配置降级链：备用(IMAGE_*) → 兜底(OPENAI_*+AGNES)，
    前者全部失败（含 edits + generations + 两种尺寸）才尝试下一个通道。"""
    configs = _get_image_api_configs(has_character)
    if not configs or not image_prompt:
        return None
    # 质量档 → API quality 字段 + 尺寸档
    _QMAP = {
        'fast':   {'api_q': 'low',  'size_scale': 0.5},   # 快/省：1024 档
        'medium':  {'api_q': 'auto', 'size_scale': 1.0},   # 默认：保持原比例
        'high':    {'api_q': 'high', 'size_scale': 1.5},   # 高质：上调到 1536/2048 档
    }
    _qcfg = _QMAP.get((quality or 'medium').lower(), _QMAP['medium'])
    # 按质量档调整尺寸（保持原比例）
    def _scale_size(sz, scale):
        parts = sz.split('x')
        if len(parts) != 2: return sz
        try:
            w, h = int(parts[0]), int(parts[1])
            w = max(512, int(round(w * scale / 64.0)) * 64)
            h = max(512, int(round(h * scale / 64.0)) * 64)
            return f"{w}x{h}"
        except Exception:
            return sz
    base_size = _scale_size(size, _qcfg['size_scale'])
    # 部分网关（如 vectorengine）需走代理：IMAGE_TRUST_ENV=1 时优先走注册表/IMAGE_PROXY 代理，直连兜底。
    use_env_proxy = os.getenv("IMAGE_TRUST_ENV", "").strip().lower() in ("1", "true", "yes")
    proxies = _image_proxy_candidates() if use_env_proxy else [None]

    # 参考图优先级最高：不描述具体外貌，只强制模型完全复刻参考图的画风/色调/角色
    # 仅角色图才附加该锚定说明；场景图保持纯提示词，避免把许墨外貌强塞进风景。
    ref_note = (" The attached image is the SINGLE SOURCE OF TRUTH for the character's "
                "appearance, art style, color palette, skin tone, and overall aesthetic. "
                "Reproduce the character EXACTLY as shown in the reference — identical face, "
                "hairstyle, coloring, and art style. Do NOT invent or alter any visual trait. "
                "The reference's HAIRSTYLE and FACIAL FEATURES (face shape, eyes, eyebrows, "
                "nose, lips, glasses) must be reproduced EXACTLY as shown — do NOT restyle, "
                "recomb, re-age, or replace the face with any other character. "
                "Keep only ONE main character matching the reference. Match the reference's "
                "lighting, color grading, and illustration style precisely.")
    # ref_note 仅对 owner 走 gpt-image + /images/edits（附加许墨参考图）时有意义；
    # 非 owner 走 agnes generations（无参考图），不应附加该锚定说明。
    use_ref_note = has_character and _role_ctx.get() == "owner"
    full_prompt = image_prompt.rstrip() + (ref_note if use_ref_note else "")

    def _pick(body: dict) -> dict | None:
        item = (body.get("data") or body.get("images") or [None])[0]
        return item if isinstance(item, dict) else None

    def _build_files(extra_user_ref: bytes | None, user_mime: str | None, user_ext: str = "png") -> list[tuple]:
        """构造 multipart files：只传许墨参考图（1 张）。
        gpt-image 的 image[] 是批量编辑而非多图参考，传多张会导致拼接图。
        用户原图不传给 edits，其构图信息已通过 prompt 传递（LLM 视觉分析）。
        xumo_ref_override 优先于默认许墨参考图。
        """
        files: list[tuple] = []
        if xumo_ref_override and len(xumo_ref_override) >= 3:
            data, mime, fname = xumo_ref_override[0], xumo_ref_override[1], xumo_ref_override[2]
            files.append(("image", (fname, data, mime)))
        else:
            for fname, _, data, mime in _xumo_ref_attachment():
                files.append(("image", (fname, data, mime)))
        return files

    quota_hit = [False]

    async def _try_edits(cfg: tuple, sz: str, files: list[tuple], proxy: str | None = None) -> dict | None:
        """尝试 /images/edits，用单图 image 字段（许墨参考图，确保角色一致性）。
        gpt-image 的 image[] 字段会导致服务器断开连接，必须用 image 字段。
        files 为空时仍会尝试许墨参考单图。"""
        _api_key, _base_url, _model = cfg
        _api_q = _qcfg['api_q'] if 'gpt-image' in _model else ('hd' if _qcfg['api_q'] == 'auto' else _qcfg['api_q'])
        # gpt-image 经 vectorengine 的 edits 在 2048x2048 会被掐断连接，
        # 方形成图回落 1536x1536；竖版 1536x2048 / 横版 2048x1536 实测可用，保持不变。
        if sz == "2048x2048":
            sz = "1536x1536"
        # 单图候选：优先 files 中的图，再追加许墨参考
        single_candidates: list[tuple] = []
        for _, (fname, data, mime) in files:
            single_candidates.append((fname, data, mime))
        if not single_candidates:
            for fname, _, data, mime in _xumo_ref_attachment():
                single_candidates.append((fname, data, mime))

        try:
            async with httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                # 单图 image 字段：依次尝试许墨参考图
                for fname, data, mime in single_candidates:
                    try:
                        resp = await client.post(
                            f"{_base_url}/images/edits",
                            data={"model": _model, "prompt": full_prompt, "n": "1", "size": sz,
                                  "quality": _api_q, "output_format": "png"},
                            files={"image": (fname, data, mime)},
                            headers={"Authorization": f"Bearer {_api_key}"},
                        )
                        if resp.status_code in (403, 429) and ("quota" in resp.text.lower() or "insufficient" in resp.text.lower()):
                            quota_hit[0] = True
                        if resp.status_code == 200:
                            item = _pick(resp.json())
                            if item:
                                return item
                    except Exception:
                        pass
        except Exception:
            pass
        return None

    async def _gen(cfg: tuple, sz: str) -> str | None:
        _api_key, _base_url, _model = cfg
        # Lovart 通道：非 OpenAI 兼容，走 HMAC 签名 chat 流程（无 size/quality/参考图概念）
        if "lovart" in _base_url.lower():
            try:
                data = await _lovart_generate_image_bytes(full_prompt, _model)
            except Exception:
                return None
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"{name}.png"
            path.write_bytes(data)
            return f"{url_prefix}/{name}.png"
        _api_q = _qcfg['api_q'] if 'gpt-image' in _model else ('hd' if _qcfg['api_q'] == 'auto' else _qcfg['api_q'])
        _url = f"{_base_url}/images/generations"
        _headers = {"Authorization": f"Bearer {_api_key}", "Content-Type": "application/json"}
        for proxy in proxies:
            try:
                async with httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(120.0, connect=15.0)) as client:
                    item = None
                    # 1) 角色图：edits + 许墨参考图（单张，确保角色一致性）
                    #    用户原图不传给 edits（gpt-image 的 image[] 是批量编辑，传多张会拼接）
                    #    用户原图的构图信息已通过 prompt 传递（LLM 视觉分析）
                    # 2) 场景图：跳过 edits，直接 generations 纯文生图（无参考图，防止角色入画）
                    # 3) 非 owner 用户：强制走 agnes（generations），跳过 edits 避免占用
                    #    gpt-image 贵通道与附加许墨参考图（agnes 通道不支持参考图）
                    if has_character and _role_ctx.get() == "owner":
                        ref_files = _build_files(None, None)
                        item = await _try_edits(cfg, sz, ref_files, proxy)
                    if item is None:
                        payload = {
                            "model": _model,
                            "prompt": full_prompt,
                            "n": 1,
                            "size": sz,
                            "image_size": sz,
                            "quality": _api_q,
                            "output_format": "png",
                        }
                        resp = await client.post(_url, json=payload, headers=_headers)
                        if resp.status_code in (403, 429) and ("quota" in resp.text.lower() or "insufficient" in resp.text.lower()):
                            quota_hit[0] = True
                        if resp.status_code == 200:
                            item = _pick(resp.json())
                    if item is None:
                        continue
                    out_dir.mkdir(parents=True, exist_ok=True)
                    path = out_dir / f"{name}.png"
                    if item.get("b64_json"):
                        path.write_bytes(base64.b64decode(item["b64_json"]))
                    elif item.get("url"):
                        dl = await client.get(item["url"])
                        dl.raise_for_status()
                        path.write_bytes(dl.content)
                    else:
                        continue
                return f"{url_prefix}/{name}.png"
            except Exception:
                continue
        return None

    # 降级链：依次尝试每个配置（先 2K 比例，失败回退 1.5K 方形）；
    # 某配置两种尺寸均失败才尝试下一个配置。
    result = None
    for cfg in configs:
        result = await _gen(cfg, base_size) or await _gen(cfg, "1536x1536")
        if result:
            break
    if result:
        _img_quota_consume()
    elif quota_hit[0]:
        tried_models = " / ".join(c[2] for c in configs)
        raise ImageQuotaError(f"生图额度已用完（{tried_models}），请充值后再试")
    return result


# 许墨形象固定英文锚点 + 通用「LLM 构思英文绘图提示词 → 生图」高层封装。
# 供签语卡 / 城市事件 / 约会手账 / 记忆手账 / 居民肖像 / 清梦 / 平行宇宙 / 观星 / 黑天鹅档案等场景共用，
# 统一走「system_prompt 要求只输出 {"image_prompt": "..."} JSON → _openai_generate_image 落盘」流程。
LLM_IMG_GEN_PROMPT = """你是《恋与制作人》官方卡面绘制助手。下面给出一段场景素材，请据此构思一个只属于许墨与她的画面，并输出一段可直接用于 AI 绘图的英文提示词。

【许墨形象锚点（许墨入画时必须逐字包含下面这段固定英文外貌句，只能追加不能删改）】
"{xumo_look}"

【画面要求】
- 双人温柔互动的场景优先；「她」可用背影、侧脸或手部特写来暗示，不刻画清晰正脸
- 许墨形象铁律：银色细框眼镜必须清晰可见、瞳色深紫罗兰（禁琥珀棕/蓝/灰瞳）、白净鹅蛋脸鼻梁高挺、衣着只用黑白灰紫（白衬衫+深灰或深紫外套/大衣）
- 恋与制作人画风：日系乙女向精致立绘、厚涂+赛璐璐、五官与手部精致、柔和唯美用色、氛围感光影、背景虚化光斑
- 统一冷紫或暖光色调，可点缀蝴蝶 / 纸鹤 / 紫色意象

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{{"image_prompt": "英文绘图提示词，100~160 词，包含场景、两人姿态、着装、镜头与光线、画风关键词"}}"""

LLM_IMG_SCENE_PROMPT = """你是《恋与制作人》官方场景插画绘制助手。下面给出一段场景素材，请据此构思一幅「无主角入画」的氛围场景插画（纯景物 / 环境 / 意象），并输出一段可直接用于 AI 绘图的英文提示词。

【画面要求】
- 不出现清晰人像或正脸（可用背影、手部、物件暗示主角存在）
- 恋与制作人画风：日系乙女向精致背景插画、厚涂+赛璐璐、柔和唯美用色、氛围感光影、背景虚化光斑
- 统一冷紫或暖光色调，可点缀蝴蝶 / 纸鹤 / 紫色意象 / 银框眼镜 / 黑咖啡等许墨意象物件

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{{"image_prompt": "英文绘图提示词，80~140 词，包含场景元素、构图、时间/天气氛围、色调与画风关键词"}}"""


async def _llm_image_for_text(
    material: str,
    out_dir,
    url_prefix: str,
    name: str,
    size: str = "1024x1024",
    with_xumo: bool = True,
    system_prompt: str | None = None,
    has_character: bool | None = None,
) -> tuple[str | None, str | None]:
    """通用「LLM 构思英文绘图提示词 → 生图」流程，供各场景共用。

    - material: 喂给 LLM 的中文场景素材；
    - with_xumo=True: 注入许墨形象锚点（双人/角色场景）；False: 纯场景氛围插画；
    - system_prompt: 自定义系统提示（需含 {{xumo_look}} 占位或自行处理）；默认用 LLM_IMG_GEN_PROMPT / LLM_IMG_SCENE_PROMPT；
    - has_character: 是否画面含人物/角色（决定走 gpt-image-2 还是 agnes）；
      默认 None = 跟随 with_xumo（许墨入画即角色图）；
      居民肖像等「非许墨但有人物」的图需显式传 True；
    - 返回 (image_url, image_prompt)；任一步失败返回 (None, None)。
    """
    if system_prompt is None:
        system_prompt = LLM_IMG_GEN_PROMPT if with_xumo else LLM_IMG_SCENE_PROMPT
    try:
        if "{xumo_look}" in system_prompt:
            system_prompt = system_prompt.format(xumo_look=XUMO_LOOK_EN)
        content = await _call_llm(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": material + "\n\n请输出 JSON。"},
            ],
            max_tokens=800,
        )
    except Exception:
        return None, None
    image_prompt = _extract_image_prompt_json(content)
    if not image_prompt:
        return None, None
    if with_xumo and "Lucien" not in image_prompt:
        image_prompt = XUMO_LOOK_EN + ", " + image_prompt
    image_url = await _openai_generate_image(image_prompt, out_dir, url_prefix, name, size, has_character=with_xumo if has_character is None else has_character)
    return image_url, image_prompt


@app.get("/api/img2img/styles")
async def img2img_styles():
    """风格预设列表。"""
    return {"styles": [
        {"key": k, "name": v["name"], "emoji": v["emoji"], "desc": v["desc"]}
        for k, v in IMG2IMG_STYLES.items()
    ]}


@app.get("/api/img2img/quota")
async def img2img_quota():
    """生图余额（本月剩余次数）。"""
    return _img_quota_info()


# ---------------------------------------------------------------------------
# API 自定义配置端点（per-user 覆盖 .env 默认值）
# ---------------------------------------------------------------------------
def _mask_key(k: str) -> str:
    """api_key 脱敏：保留前 4 + 后 4，中间替换为 …；空字符串原样返回。"""
    if not k:
        return ""
    if len(k) <= 10:
        return "****"
    return f"{k[:4]}…{k[-4:]}（已设置 {len(k)} 位）"


@app.get("/api/settings/api")
async def api_settings_get():
    """读取当前用户自定义 API 配置。
    api_key 返回脱敏串（前端仅显示已设置与否，写入时若字段为空或与脱敏串一致则保留原值）。
    env_defaults 返回 .env 中的当前值，供前端占位提示；
    env_channels 返回生图内置通道（secondary/agnes）的 .env 配置，供通道选择器展示。"""
    data = _load_api_settings()
    text  = data.get("text")  or {}
    image = data.get("image") or {}
    # env 默认值（用于前端占位）
    env_text = {
        "base_url": _get_base_url(),
        "api_key":  _mask_key(os.getenv("OPENAI_API_KEY", "")),
        "model":    os.getenv("MODEL", "gpt-4o-mini"),
    }
    env_image = {
        "base_url": (os.getenv("IMAGE_BASE_URL") or "").strip() or _get_base_url(),
        "api_key":  _mask_key((os.getenv("IMAGE_API_KEY") or os.getenv("OPENAI_API_KEY") or "")),
        "model":    (os.getenv("IMAGE_MODEL") or os.getenv("AGNES_IMAGE_MODEL") or "gpt-image-2"),
    }
    # 生图内置通道（供前端通道选择器展示）
    def _chan(api_key_env: str, base_url_env: str, model_env: str, fallback_model: str, base_url_fallback: str = "") -> dict:
        return {
            "base_url": ((os.getenv(base_url_env) or "").strip().rstrip("/") or base_url_fallback or ""),
            "api_key":  _mask_key(os.getenv(api_key_env) or ""),
            "model":    (os.getenv(model_env) or "").strip() or fallback_model,
        }
    env_channels = {
        "secondary": _chan("IMAGE_API_KEY", "IMAGE_BASE_URL", "IMAGE_MODEL", "gpt-image-2"),
        "agnes":     _chan("OPENAI_API_KEY", "OPENAI_BASE_URL", "AGNES_IMAGE_MODEL", "agnes-image-2.1-flash", _get_base_url()),
        "lovart":    _chan("LOVART_API_KEY", "LOVART_BASE_URL", "LOVART_IMAGE_MODEL", "generate_image_gpt_image_1_5", LOVART_DEFAULT_BASE),
    }
    image_provider = str(image.get("provider") or "auto").strip().lower()
    if image_provider not in ("auto", "secondary", "agnes", "custom", "lovart"):
        image_provider = "auto"
    return {
        "text":  {
            "base_url": (text.get("base_url") or "").strip(),
            "api_key":  _mask_key((text.get("api_key") or "").strip()),
            "model":    (text.get("model") or "").strip(),
            "has_custom": bool((text.get("api_key") or "").strip() or (text.get("base_url") or "").strip() or (text.get("model") or "").strip()),
        },
        "image": {
            "provider": image_provider,
            "base_url": (image.get("base_url") or "").strip(),
            "api_key":  _mask_key((image.get("api_key") or "").strip()),
            "model":    (image.get("model") or "").strip(),
            "has_custom": bool((image.get("api_key") or "").strip() or (image.get("base_url") or "").strip() or (image.get("model") or "").strip()),
        },
        "env_defaults": {"text": env_text, "image": env_image},
        "env_channels": {"image": env_channels},
        "scope": _role_ctx.get(),
    }


@app.post("/api/settings/api")
async def api_settings_save(req: Request):
    """保存当前用户自定义 API 配置。
    字段约定：
    - 空字符串 → 清空该字段（回退到 env 默认值）
    - 形如 'xxxx…xxxx（已设置 N 位）' 的脱敏占位串 → 保留原值不变
    - 其他非空串 → 视为新值写入"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "请求体必须是对象"}, status_code=400)

    cur = _load_api_settings()
    cur_text  = cur.get("text")  or {}
    cur_image = cur.get("image") or {}

    def _merge(in_group: dict, cur_group: dict) -> dict:
        out = {}
        for field in ("base_url", "api_key", "model"):
            v = str((in_group or {}).get(field, "") or "").strip()
            # 脱敏占位串 → 保留原值
            if v and ("…" in v or v.startswith("****")):
                out[field] = (cur_group.get(field) or "").strip()
            else:
                out[field] = v
        # provider 单独处理：仅接受合法值，非法或缺失保持原值
        p = str((in_group or {}).get("provider", "") or "").strip().lower()
        if p in ("auto", "secondary", "agnes", "custom", "lovart"):
            out["provider"] = p
        else:
            out["provider"] = str(cur_group.get("provider") or "auto").strip().lower()
        return out

    new_text  = _merge(body.get("text"),  cur_text)
    new_image = _merge(body.get("image"), cur_image)
    _save_api_settings({"text": new_text, "image": new_image})
    return {"ok": True, "message": "API 自定义配置已保存"}


@app.post("/api/settings/api/test")
async def api_settings_test(req: Request):
    """测试自定义 API 连接。
    body: {"kind": "text" | "image", "config": {"base_url": "...", "api_key": "...", "model": "..."}}
    - kind=text: 调用 /chat/completions 发一句 "ping"，期望 200
    - kind=image: 调用 /images/generations 生成一张 1024x1024 测试图（不落盘，仅校验连通性）
    返回 {ok: bool, latency_ms: int, detail: str}"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    kind = (body.get("kind") or "").strip().lower()
    cfg = body.get("config") or {}
    if kind not in ("text", "image"):
        return JSONResponse({"error": "kind 必须是 text 或 image"}, status_code=400)
    base_url = str(cfg.get("base_url") or "").strip().rstrip("/")
    api_key  = str(cfg.get("api_key") or "").strip()
    model    = str(cfg.get("model") or "").strip()
    # 脱敏占位串 → 用 env 默认值（优先备用通道 IMAGE_*；Lovart 用 LOVART_API_KEY）
    if not api_key or "…" in api_key or api_key.startswith("****"):
        if kind == "image" and "lovart" in base_url.lower():
            api_key = (os.getenv("LOVART_API_KEY") or "").strip()
        else:
            api_key = (os.getenv("IMAGE_API_KEY") or os.getenv("OPENAI_API_KEY", "")).strip() if kind == "image" else os.getenv("OPENAI_API_KEY", "")
    if not base_url:
        if kind == "text":
            base_url = _get_base_url()
        else:
            base_url = ((os.getenv("IMAGE_BASE_URL") or "").strip() or _get_base_url())
    if not model:
        if kind == "text":
            model = os.getenv("MODEL", "gpt-4o-mini")
        else:
            model = (os.getenv("IMAGE_MODEL") or os.getenv("AGNES_IMAGE_MODEL") or "gpt-image-2")
    if not api_key:
        return JSONResponse({"ok": False, "detail": "未提供 api_key 且 .env 未配置 OPENAI_API_KEY"}, status_code=400)
    if not base_url:
        return JSONResponse({"ok": False, "detail": "未提供 base_url"}, status_code=400)

    import time
    t0 = time.time()
    try:
        async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            if kind == "text":
                url = f"{base_url}/chat/completions"
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 8,
                }
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                resp = await client.post(url, json=payload, headers=headers)
            else:
                # Lovart 通道：AK/SK HMAC 签名，用 mode/query 验证连通性
                if "lovart" in base_url.lower():
                    l_ak = api_key
                    l_sk = (os.getenv("LOVART_SECRET_KEY") or "").strip()
                    if not l_sk:
                        return JSONResponse({"ok": False, "detail": "Lovart 需要 .env 配置 LOVART_SECRET_KEY"}, status_code=200)
                    data = await _lovart_api_request(base_url, l_ak, l_sk, "POST",
                                                     "/v1/openapi/mode/query", body={})
                    mode = "无限排队" if data.get("unlimited") else "快速"
                    n = len(data.get("unlimited_list") or []) or len(data.get("fast_list") or [])
                    return {"ok": True, "latency_ms": latency,
                            "detail": f"Lovart 连接成功（{mode}模式，可用模型 {n} 个）"}
                url = f"{base_url}/images/generations"
                payload = {
                    "model": model,
                    "prompt": "a small purple butterfly on a white background, simple test image",
                    "n": 1,
                    "size": "1024x1024",
                    "image_size": "1024x1024",
                }
                headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                resp = await client.post(url, json=payload, headers=headers)
        latency = int((time.time() - t0) * 1000)
        if resp.status_code == 200:
            return {"ok": True, "latency_ms": latency, "detail": f"连接成功（{model} @ {base_url}）"}
        return JSONResponse({
            "ok": False,
            "latency_ms": latency,
            "detail": f"HTTP {resp.status_code}：{resp.text[:200]}",
        }, status_code=200)
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return JSONResponse({
            "ok": False,
            "latency_ms": latency,
            "detail": f"连接失败：{type(e).__name__}: {e}",
        }, status_code=200)


@app.post("/api/img2img/generate")
async def img2img_generate(req: Request):
    """图生图：上传图片(base64) → 视觉理解 → 融合所选许墨卡面风格重绘。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    style = data.get("style") or "rain"
    ratio = data.get("ratio") or "square"
    extra = data.get("extra") or ""
    quality = (data.get("quality") or "medium").lower()
    if quality not in ("fast", "medium", "high"):
        quality = "medium"
    image_b64 = (data.get("image") or "").strip()
    # 多参考图：我的化身图 / 场景图 / 许墨参考图（每组最多 5 张 base64 data URL）
    avatar_refs_in = data.get("avatar_refs") or []
    scene_refs_in = data.get("scene_refs") or []
    xumo_refs_in = data.get("xumo_refs") or []
    if not isinstance(avatar_refs_in, list): avatar_refs_in = []
    if not isinstance(scene_refs_in, list): scene_refs_in = []
    if not isinstance(xumo_refs_in, list): xumo_refs_in = []
    avatar_refs_in = [x for x in avatar_refs_in if isinstance(x, str) and x.startswith("data:")][:5]
    scene_refs_in = [x for x in scene_refs_in if isinstance(x, str) and x.startswith("data:")][:5]
    xumo_refs_in = [x for x in xumo_refs_in if isinstance(x, str) and x.startswith("data:")][:5]
    if style not in IMG2IMG_STYLES:
        return JSONResponse({"error": "未知风格"}, status_code=400)
    # 付费校验：非 owner 检查钱包余额（按所选质量档位）；owner 检查月度配额
    ok, reason = _wallet_can_generate(quality)
    if not ok:
        return JSONResponse({"error": reason}, status_code=403)
    if _role_ctx.get() == "owner" and _img_quota_exhausted():
        info = _img_quota_info()
        return JSONResponse(
            {"error": f"本月生图余额已用完（{info['used']}/{info['quota']} 次），请下个月再来，或让主人调整配额。"},
            status_code=403,
        )
    size = IMG2IMG_SIZES.get(ratio, "1024x1024")

    # 解析 data URL 或裸 base64
    mime = "jpeg"
    if image_b64.startswith("data:"):
        head, _, image_b64 = image_b64.partition(",")
        m = re.search(r"data:image/(\w+)", head)
        if m:
            mime = m.group(1).lower()
    if not image_b64:
        return JSONResponse({"error": "请先上传图片"}, status_code=400)

    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        return JSONResponse({"error": "图片数据解码失败"}, status_code=400)
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": "图片不能超过 8MB"}, status_code=400)
    if len(raw) < 100:
        return JSONResponse({"error": "图片内容为空"}, status_code=400)

    async def _work():
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp"}.get(mime, ".jpg")
        work_id = uuid.uuid4().hex[:12]
        IMG2IMG_DIR.mkdir(parents=True, exist_ok=True)
        src_path = IMG2IMG_DIR / f"{work_id}_src{ext}"
        src_path.write_bytes(raw)
        src_url = f"/static/img2img/{work_id}_src{ext}"

        # 视觉理解 + 提示词合成（一次调用完成）
        style_meta = IMG2IMG_STYLES[style]
        ref_hint_parts = []
        if avatar_refs_in:
            ref_hint_parts.append(f"我的化身参考图（{len(avatar_refs_in)} 张）：请参考这些图中「她」的形象、发型、着装、气质，在重绘画面里保持「她」的形象与这些参考一致")
        if scene_refs_in:
            ref_hint_parts.append(f"场景参考图（{len(scene_refs_in)} 张）：请参考这些图的场景、构图、色调、氛围，在重绘画面里融入这些场景元素")
        if xumo_refs_in:
            ref_hint_parts.append(f"许墨参考图（{len(xumo_refs_in)} 张）：请严格参考这些图中许墨的形象、发型、眼镜、着装，在重绘画面里保持许墨形象与这些参考完全一致")
        ref_hint = ("\n【用户上传的参考图】\n" + "\n".join(ref_hint_parts) + "\n") if ref_hint_parts else ""

        user_content = [
            {"type": "text", "text": (
                f"所选风格主题：{style_meta['name']}（{style_meta['desc']}）\n"
                f"风格元素参考：{style_meta['prompt']}\n"
                f"用户附加描述：{extra.strip() or '（无，请自行发挥）'}\n"
                f"画幅比例：{ratio}（portrait=竖版 / landscape=横版 / square=方形）\n"
                f"{ref_hint}"
                "请看图后按系统要求输出 JSON。"
            )},
            {"type": "image_url", "image_url": {"url": f"data:image/{'png' if ext == '.png' else 'jpeg'};base64,{base64.b64encode(raw).decode()}"}},
        ]
        # 追加参考图到视觉理解请求（让 LLM 看到参考图并融入 prompt）
        for ref_url in avatar_refs_in + scene_refs_in + xumo_refs_in:
            user_content.append({"type": "image_url", "image_url": {"url": ref_url}})
        try:
            content = await _call_llm(
                [
                    {"role": "system", "content": IMG2IMG_VISION_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=3000,
            )
        except Exception as e:
            raise GenJobError(f"画面分析失败：{e}")

        parsed = _extract_img2img_json(content)
        if not parsed or not parsed["image_prompt"]:
            raise GenJobError("提示词生成失败，请重试")

        # 保底：许墨入画但提示词漏了形象锚点时，前置固定英文外貌句
        image_prompt = parsed["image_prompt"]
        if parsed["with_xumo"] and "Lucien" not in image_prompt:
            image_prompt = f"{XUMO_LOOK_EN}. {image_prompt}"

        # 以 LLM 生成的 prompt 驱动全新画面（不传原图给生图模型，避免照搬原图动作）
        # 画面含人物/角色 → gpt-image-2（角色图）；纯场景 → agnes（场景图）
        # 若用户上传了许墨参考图，取第一张替代默认许墨参考传给 /images/edits 强制角色一致
        xumo_ref_override = None
        if xumo_refs_in:
            try:
                ref_mime, ref_bytes = _parse_data_url(xumo_refs_in[0])
                if ref_bytes and len(ref_bytes) <= 8 * 1024 * 1024:
                    ref_ext = "png" if "png" in ref_mime else "jpg"
                    xumo_ref_override = (ref_bytes, ref_mime, f"xumo_ref_{work_id}.{ref_ext}")
            except Exception:
                pass
        gen_url = await _generate_img2img_image(image_prompt, work_id, size, has_character=bool(parsed["with_xumo"]), xumo_ref_override=xumo_ref_override, quality=quality)
        if not gen_url:
            raise GenJobError("绘图服务暂时不可用，请稍后重试")

        # 付费扣费：非 owner 从钱包扣对应档位价格（owner 由 _img_quota_consume 在 _openai_generate_image 内已扣月度配额）
        _wallet_consume_for_image(quality)

        record = {
            "id": work_id,
            "style": style,
            "style_name": style_meta["name"],
            "ratio": ratio,
            "quality": quality,
            "extra": extra.strip(),
            "src": src_url,
            "gen": gen_url,
            "prompt": image_prompt,
            "comment": parsed["comment"],
            "with_xumo": parsed["with_xumo"],
            "time": datetime.now().strftime("%m-%d %H:%M"),
        }
        records = _load_img2img()
        records.append(record)
        records = records[-60:]
        _save_img2img(records)

        info = _add_affinity("img2img", f"画境共创 · {style_meta['name']}")
        return {"record": record, "affinity": info}

    if data.get("bg"):
        job = await submit_gen_job("img2img", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


@app.get("/api/img2img/history")
async def img2img_history():
    """历史作品，最新在前。"""
    return {"records": list(reversed(_load_img2img()))}


@app.delete("/api/img2img/{record_id}")
async def img2img_delete(record_id: str):
    records = _load_img2img()
    kept = [r for r in records if r.get("id") != record_id]
    if len(kept) == len(records):
        return JSONResponse({"error": "作品不存在"}, status_code=404)
    _save_img2img(kept)
    for r in records:
        if r.get("id") == record_id:
            for key in ("src", "gen", "card"):
                try:
                    role_file(r[key].lstrip("/")).unlink(missing_ok=True)
                except Exception:
                    pass
    return {"ok": True}


# ================= 画境分享卡（语录叠加成卡） =================

_SHARE_CARD_FONT_CANDIDATES = [
    # 项目自带手写体（霞鹜文楷 LXGW WenKai，OFL 开源）——许墨手写质感
    str(BASE_DIR / "static" / "fonts" / "LXGWWenKai-Medium.ttf"),
    str(BASE_DIR / "static" / "fonts" / "LXGWWenKai-Regular.ttf"),
    r"C:\Windows\Fonts\simkai.ttf",   # 楷体（文人气质，兜底）
    r"C:\Windows\Fonts\msyh.ttc",     # 微软雅黑
    r"C:\Windows\Fonts\Deng.ttf",     # 等线
    r"C:\Windows\Fonts\simhei.ttf",   # 黑体
    r"C:\Windows\Fonts\simsun.ttc",   # 宋体
]

_CARD_FONT_CACHE = {}


def _share_font(size: int, bold: bool = True):
    """加载中文字体（带缓存）；找不到时回退 Pillow 默认字体。"""
    key = (size, bold)
    if key in _CARD_FONT_CACHE:
        return _CARD_FONT_CACHE[key]
    try:
        from PIL import ImageFont
    except ImportError:
        return None
    if bold:
        # 粗体优先雅黑粗体（楷体无粗体，细描边替代）
        paths = [r"C:\Windows\Fonts\msyhbd.ttc"] + _SHARE_CARD_FONT_CANDIDATES
    else:
        paths = _SHARE_CARD_FONT_CANDIDATES
    for p in paths:
        try:
            f = ImageFont.truetype(p, size)
            _CARD_FONT_CACHE[key] = f
            return f
        except Exception:
            continue
    _CARD_FONT_CACHE[key] = None
    return None


def _card_wrap(draw, text: str, font, max_w: int, spacing: int = 0) -> list:
    """按像素宽度自动换行（含字间距）。"""
    if not font:
        return [text[i:i + max(1, max_w // 28)] for i in range(0, len(text), max(1, max_w // 28))]
    lines, cur = [], ""
    for ch in text:
        trial = cur + ch
        tw = draw.textlength(trial, font=font) + spacing * max(0, len(trial) - 1)
        if cur and tw > max_w:
            lines.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


@app.post("/api/img2img/{record_id}/card")
async def img2img_make_card(record_id: str, req: Request):
    """画境分享卡：在作品图上叠加语录文字，生成分享卡图片。
    文字（语录）与卡片图一并保存在作品记录里，可反复重新生成。"""
    try:
        data = await req.json()
    except Exception:
        data = {}
    text = (data.get("text") or "").strip()[:120]
    pos = data.get("pos") or "bottom"
    if pos not in ("top", "center", "bottom"):
        pos = "bottom"
    if not text:
        return JSONResponse({"error": "请先写一句语录文字"}, status_code=400)

    records = _load_img2img()
    rec = next((r for r in records if r.get("id") == record_id), None)
    if not rec:
        return JSONResponse({"error": "作品不存在"}, status_code=404)
    gen_path = rec.get("gen", "").lstrip("/")
    if not gen_path:
        return JSONResponse({"error": "作品图片不存在"}, status_code=404)
    img_path = role_file(gen_path)
    if not img_path.exists():
        return JSONResponse({"error": "作品图片文件已丢失"}, status_code=404)

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return JSONResponse({"error": "服务器缺少 Pillow 库，无法生成分享卡"}, status_code=500)

    def _render() -> str:
        """CPU 密集的图像合成（逐行渐变 + 高斯模糊 + PNG 编码），整体放线程池执行，
        避免阻塞事件循环拖慢其他并发请求。"""
        img = Image.open(img_path).convert("RGB")
        w, h = img.size

        # 底部/顶部/居中的文字遮罩带（半透明渐变 + 细描边）
        bar_h = int(h * 0.30)
        if pos == "top":
            y0, y1 = 0, bar_h
        elif pos == "center":
            y0, y1 = int(h * 0.5 - bar_h * 0.55), int(h * 0.5 + bar_h * 0.55)
        else:
            y0, y1 = h - bar_h, h

        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for y in range(max(0, y0), min(h, y1)):
            t = (y - y0) / max(1, y1 - y0)
            if pos == "top":
                a = int(170 * (1 - t))
            else:
                a = int(170 * t)
            od.line([(0, y), (w, y)], fill=(16, 10, 34, a))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        draw = ImageDraw.Draw(img)

        # 主文字：随画幅自适应字号（手写体）
        base = max(28, min(66, int(w * 0.052)))
        font = _share_font(base, bold=True)
        if font is None:
            font = draw.getfont() if hasattr(draw, "getfont") else None
        spacing = max(2, int(base * 0.10))  # 手写体轻微字距更疏朗
        pad = int(w * 0.10)
        max_w = w - pad * 2
        lines = _card_wrap(draw, text, font, max_w, spacing=spacing)[:4]

        # 纵向居中放置文字块（行距放宽，手写体呼吸感）
        lh = int(base * 1.62)
        block_h = len(lines) * lh
        if pos == "top":
            ty = int(bar_h * 0.5 - block_h * 0.5) + int(base * 0.15)
        elif pos == "center":
            ty = y0 + (y1 - y0 - block_h) // 2 + int(base * 0.15)
        else:
            ty = h - bar_h + (bar_h - block_h) // 2 + int(base * 0.15)

        # 柔和阴影层（高斯模糊）→ 白字细描边（letter_spacing 原生字距，避免字叠）
        from PIL import ImageFilter as _PIL_ImageFilter
        shadow_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        for li, line in enumerate(lines):
            if not font:
                x = pad
            else:
                tw = draw.textlength(line, font=font) + spacing * max(0, len(line) - 1)
                x = max(pad, (w - tw) // 2)
            y = ty + li * lh
            sd.text((x + 3, y + 4), line, font=font, fill=(0, 0, 0, 170), letter_spacing=spacing)
        shadow_layer = shadow_layer.filter(_PIL_ImageFilter.GaussianBlur(3.5))
        img = Image.alpha_composite(img.convert("RGBA"), shadow_layer)
        draw = ImageDraw.Draw(img)
        for li, line in enumerate(lines):
            if not font:
                x = pad
            else:
                tw = draw.textlength(line, font=font) + spacing * max(0, len(line) - 1)
                x = max(pad, (w - tw) // 2)
            y = ty + li * lh
            draw.text(
                (x, y), line, font=font, letter_spacing=spacing,
                fill=(255, 255, 255, 255), stroke_width=2, stroke_fill=(45, 24, 78),
            )

        # 底部小签名：手写体小字
        sign = "—— 许墨 · 恋语市 · 画境"
        sf = _share_font(max(13, int(base * 0.30)), bold=False)
        if sf:
            sw = draw.textlength(sign, font=sf)
            sy = h - int(h * 0.05)
            draw.text(((w - sw) / 2 + 1, sy + 1), sign, font=sf, fill=(0, 0, 0, 180))
            draw.text(((w - sw) / 2, sy), sign, font=sf, fill=(255, 255, 255, 235))

        card_name = f"{record_id}_card.png"
        card_path = IMG2IMG_DIR / card_name
        img.save(card_path, "PNG")
        return f"/static/img2img/{card_name}"

    try:
        card_url = await run_in_threadpool(_render)
    except Exception as e:
        return JSONResponse({"error": f"分享卡生成失败：{e}"}, status_code=500)

    # 语录与卡片一起保存进作品记录
    rec["card"] = card_url
    rec["card_text"] = text
    rec["card_pos"] = pos
    rec["card_time"] = datetime.now().strftime("%m-%d %H:%M")
    _save_img2img(records)
    return {"ok": True, "card": card_url, "card_text": text}


# ================= 全局生图参考图接口 =================

@app.get("/api/global_ref")
async def global_ref_info(request: Request):
    """获取当前全局生图参考图信息。
    默认模式返回多张参考图（许墨1~4.png）；自定义模式返回单张上传图。
    """
    state = _global_ref_load()
    v = state.get("version", 1)
    paths = _global_ref_current_paths()
    has_ref = len(paths) > 0
    is_default = state.get("active") == "default" or not state.get("custom_path")
    # 构建参考图 URL 列表（默认模式多张，自定义模式单张）
    images = []
    for i in range(len(paths)):
        images.append({
            "url": f"/api/global_ref/image?index={i}&v={v}",
            "name": f"许墨参考 {i + 1}" if is_default else (state.get("name") or "自定义参考图"),
        })
    return {
        "active": "default" if is_default else "custom",
        "url": f"/api/global_ref/image?v={v}",
        "name": "许墨（默认设定）" if is_default else (state.get("name") or "自定义参考图"),
        "time": state.get("time", ""),
        "has_ref": has_ref,
        "count": len(paths),
        "images": images,
        "version": v,
    }


@app.get("/api/global_ref/image")
async def global_ref_image(index: int = 0):
    """返回当前全局生图参考图原图（供前端预览）。
    index 指定第几张（默认模式多张时用），自定义模式忽略 index。
    """
    paths = _global_ref_current_paths()
    if not paths:
        return JSONResponse({"error": "参考图不存在"}, status_code=404)
    idx = max(0, min(index, len(paths) - 1))
    path = paths[idx]
    if path and path.exists():
        return FileResponse(path)
    return JSONResponse({"error": "参考图不存在"}, status_code=404)


@app.post("/api/global_ref/upload")
async def global_ref_upload(req: Request):
    """上传一张图作为全局生图参考图（所有 img2img / txt2img / 化身等生图共用）。"""
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    image_b64 = (body.get("image") or "").strip()
    name = (body.get("name") or "").strip() or "自定义参考图"
    if not image_b64:
        return JSONResponse({"error": "请提供图片数据"}, status_code=400)

    mime = "jpeg"
    if image_b64.startswith("data:"):
        head, _, image_b64 = image_b64.partition(",")
        m = re.search(r"data:image/(\w+)", head)
        if m:
            mime = m.group(1).lower()
    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        return JSONResponse({"error": "图片数据解码失败"}, status_code=400)
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": "图片不能超过 8MB"}, status_code=400)
    if len(raw) < 200:
        return JSONResponse({"error": "图片内容过小"}, status_code=400)
    # 校验文件 magic（防止传任意二进制）
    if not (raw[:3] == b"\xff\xd8\xff"  # jpeg
            or raw[:8] == b"\x89PNG\r\n\x1a\n"  # png
            or raw[:4] == b"RIFF" and raw[8:12] == b"WEBP"  # webp
            or raw[:2] == b"BM"):  # bmp
        return JSONResponse({"error": "仅支持 PNG / JPG / WEBP / BMP"}, status_code=400)

    ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp"}.get(mime, ".jpg")
    GLOBAL_REF_DIR.mkdir(parents=True, exist_ok=True)
    # 覆盖写入固定文件名，避免堆积
    save_path = GLOBAL_REF_DIR / f"global_ref{ext}"
    save_path.write_bytes(raw)

    state = _global_ref_load()
    state["active"] = "custom"
    state["custom_path"] = str(save_path)
    state["name"] = name
    state["time"] = datetime.now().strftime("%m-%d %H:%M")
    _global_ref_bump(state)
    _global_ref_save(state)
    return {
        "ok": True,
        "active": "custom",
        "url": f"/api/global_ref/image?v={state['version']}",
        "name": name,
        "time": state["time"],
        "version": state["version"],
    }


@app.post("/api/global_ref/reset")
async def global_ref_reset():
    """重置为默认参考图（许墨1~4.png）。"""
    if not _global_ref_has_default():
        return JSONResponse({"error": "默认参考图不存在"}, status_code=400)
    state = _global_ref_load()
    state["active"] = "default"
    state["custom_path"] = ""
    state["name"] = ""
    state["time"] = ""
    _global_ref_bump(state)
    _global_ref_save(state)
    return {
        "ok": True,
        "active": "default",
        "url": f"/api/global_ref/image?v={state['version']}",
        "name": "许墨（默认设定）",
        "time": "",
        "version": state["version"],
    }


# ================= 化身：真人照片 → 恋与制作人风格卡通形象 =================
AVATARIFY_FILE = RolePath("avatarify.json")
AVATARIFY_DIR = RolePath("static", "avatarify")

AVATARIFY_THEMES = {
    "campus": {
        "name": "樱树初遇",
        "emoji": "🌸",
        "desc": "恋语大学 · 春樱学院",
        "prompt": (
            "Lianyu University campus in spring, cherry blossom trees lining "
            "the path, petals drifting in the air, academy-style outfit, soft "
            "morning light, fresh youthful mood"
        ),
    },
    "daily": {
        "name": "街角日常",
        "emoji": "☕",
        "desc": "咖啡香气 · 温柔便服",
        "prompt": (
            "cozy street corner cafe, warm ambient light, latte art and "
            "dessert on the table, casual daily outfit, relaxed intimate "
            "everyday atmosphere"
        ),
    },
    "rain": {
        "name": "雨夜同行",
        "emoji": "🌂",
        "desc": "共撑一伞 · 霓虹湿街",
        "prompt": (
            "rainy night street shared under one umbrella, neon reflections "
            "on wet pavement, cool violet-blue palette, gentle drizzle, "
            "quiet romantic mood"
        ),
    },
    "butterfly": {
        "name": "蝶梦星河",
        "emoji": "🦋",
        "desc": "紫蝶纷飞 · 梦幻光斑",
        "prompt": (
            "dreamlike fantasy realm, purple butterflies swirling around, "
            "glittering light particles and bokeh, starry galaxy backdrop, "
            "ethereal romantic atmosphere"
        ),
    },
    "star": {
        "name": "天台星语",
        "emoji": "🌃",
        "desc": "城市夜景 · 并肩看星",
        "prompt": (
            "rooftop terrace at night overlooking the city skyline, starry "
            "sky, gentle wind in hair, city lights bokeh, serene heartfelt "
            "mood"
        ),
    },
    "free": {
        "name": "自由画布",
        "emoji": "✨",
        "desc": "按你的描述来",
        "prompt": "follow the user's custom description freely",
    },
}

AVATARIFY_VISION_PROMPT = """你是《恋与制作人》官方角色设计师。玩家（女主角/制作人本人）上传了一张自己的真实照片，想要变成恋与制作人世界里的卡通形象。你的任务：仔细看懂照片里人物的外观特征，然后输出一段可直接用于 AI 绘图的英文提示词，把 TA 画进所选主题的卡面里。

【第一步：识别玩家特征（必须忠实保留，这是"像 TA 本人"的关键）】
- 性别、大致年龄段、发型（长度/卷直/刘海/扎发）、发色、脸型与肤色、是否戴眼镜、显著五官特点（如痣、酒窝）、体型、服装风格与颜色、显著配饰（耳环/帽子/发饰等）
- 不评价美丑，只客观记录特征；照片模糊处合理推断

【许墨形象锚点（仅"与许墨同框"模式需要）】
- 26岁儒雅青年教授：深墨色柔软微卷黑色短发（额前一缕碎发）、狭长温柔的深紫色（紫罗兰）眼眸、银色细框眼镜（必须戴着）、白净清隽鹅蛋脸、鼻梁高挺、唇色偏淡、清瘦高挑肩宽腰窄、修长手指、嘴角含笑
- 气质：温柔含笑、斯文儒雅、带一点神秘疏离；象征色紫色、象征物蝴蝶
- 防跑偏铁律：许墨必须戴银色细框眼镜且清晰可见、瞳色深紫罗兰（禁琥珀棕/灰/蓝）、衣着只用黑白灰紫（白衬衫+深灰或深紫外套），画风禁 Q版/chibi
- 固定英文外貌句（duo 模式必须把下面这段逐字完整复制进 image_prompt，不得删改任何词）：
  "Lucien (Xu Mo) from the otome game 'Mr Love: Queen's Choice', a 26-year-old gentle Chinese university professor, tall slim elegant figure with broad shoulders, deep ink-black soft slightly wavy short hair with a loose strand falling on his forehead, narrow gentle eyes with soft deep violet-purple irises and gentle lavender-violet eye color, ALWAYS wearing thin silver wire-framed glasses with clear lenses, porcelain pale fair skin, oval clean scholarly face with high straight nose bridge and pale muted lips, long slender fingers, subtle warm mysterious closed-mouth smile, wearing a crisp white shirt with dark grey or deep purple layers such as a long coat or cardigan, black white grey purple color palette only, no bright colors, elegant cool violet tones and purple butterfly motif"

【绘画模式】
- solo（单人立绘）：画面只有玩家化身一人，构图以 TA 为绝对主角（半身或全身立绘），背景为所选主题场景
- duo（与许墨同框）：双人卡面，玩家化身与许墨自然互动（并肩散步、对视、合照姿势、递伞等贴合主题），两人体型比例协调，许墨形象必须包含上述完整固定英文外貌句

【恋与制作人画风】
- 日系乙女向精致立绘、厚涂+赛璐璐、五官与手部刻画精致、柔和唯美用色、氛围感光影、背景虚化光斑

【输出要求】
只输出一个 JSON 对象，不要任何其他文字：
{
  "traits": "中文，30-60字，以许墨第二人称口吻轻声描述你认出的玩家特征（如'你留着齐肩的黑发，笑起来眼睛弯弯……'），温柔具体，像在端详照片",
  "image_prompt": "英文绘图提示词，80-150词。必须包含：1)玩家特征的英文转述（发型发色/眼镜/服装/配饰等，保持可识别一致）；2)所选主题场景元素与构图（solo=单人主角构图，duo=双人互动构图+许墨锚点至少5项）；3)恋与制作人画风关键词；4)与主题统一的色调",
  "comment": "以许墨第一人称说的一句中文短评（15-40字），针对'把你画进他的世界'这件事，温柔话留三分，可带蝴蝶或学术意象"
}
"""


def _load_avatarify() -> list:
    if AVATARIFY_FILE.exists():
        try:
            data = json.loads(AVATARIFY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_avatarify(records: list):
    atomic_json(AVATARIFY_FILE, records)


@app.post("/api/avatarify/generate")
async def avatarify_generate(req: Request):
    """化身：上传真人照片(base64) → 识别特征 → 转恋与制作人风格卡通形象。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    mode = data.get("mode") or "solo"
    theme = data.get("theme") or "campus"
    ratio = data.get("ratio") or "portrait"
    quality = (data.get("quality") or "medium").lower()
    if quality not in ("fast", "medium", "high"):
        quality = "medium"
    extra = data.get("extra") or ""
    image_b64 = (data.get("image") or "").strip()
    if mode not in ("solo", "duo"):
        return JSONResponse({"error": "未知模式"}, status_code=400)
    if theme not in AVATARIFY_THEMES:
        return JSONResponse({"error": "未知主题"}, status_code=400)
    # 付费校验：非 owner 检查钱包余额（按所选质量档位）；owner 检查月度配额
    ok, reason = _wallet_can_generate(quality)
    if not ok:
        return JSONResponse({"error": reason}, status_code=403)
    if _role_ctx.get() == "owner" and _img_quota_exhausted():
        info = _img_quota_info()
        return JSONResponse(
            {"error": f"本月生图余额已用完（{info['used']}/{info['quota']} 次），请下个月再来，或让主人调整配额。"},
            status_code=403,
        )
    size = IMG2IMG_SIZES.get(ratio, "1536x2048")

    # 解析 data URL 或裸 base64
    mime = "jpeg"
    if image_b64.startswith("data:"):
        head, _, image_b64 = image_b64.partition(",")
        m = re.search(r"data:image/(\w+)", head)
        if m:
            mime = m.group(1).lower()
    if not image_b64:
        return JSONResponse({"error": "请先上传照片"}, status_code=400)

    try:
        raw = base64.b64decode(image_b64)
    except Exception:
        return JSONResponse({"error": "图片数据解码失败"}, status_code=400)
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"error": "图片不能超过 8MB"}, status_code=400)
    if len(raw) < 100:
        return JSONResponse({"error": "图片内容为空"}, status_code=400)

    async def _work():
        ext = {"jpeg": ".jpg", "jpg": ".jpg", "png": ".png", "webp": ".webp", "bmp": ".bmp"}.get(mime, ".jpg")
        work_id = uuid.uuid4().hex[:12]
        AVATARIFY_DIR.mkdir(parents=True, exist_ok=True)
        src_path = AVATARIFY_DIR / f"{work_id}_src{ext}"
        src_path.write_bytes(raw)
        src_url = f"/static/avatarify/{work_id}_src{ext}"

        # 视觉理解 + 提示词合成（一次调用完成）
        theme_meta = AVATARIFY_THEMES[theme]
        mode_desc = "solo（单人立绘）" if mode == "solo" else "duo（与许墨同框双人卡面）"
        user_content = [
            {"type": "text", "text": (
                f"绘画模式：{mode_desc}\n"
                f"所选卡面主题：{theme_meta['name']}（{theme_meta['desc']}）\n"
                f"主题场景元素参考：{theme_meta['prompt']}\n"
                f"玩家补充描述：{extra.strip() or '（无）'}\n"
                f"画幅比例：{ratio}（portrait=竖版 / landscape=横版 / square=方形）\n"
                "请看照片后按系统要求输出 JSON。"
            )},
            {"type": "image_url", "image_url": {"url": f"data:image/{'png' if ext == '.png' else 'jpeg'};base64,{base64.b64encode(raw).decode()}"}},
        ]
        try:
            content = await _call_llm(
                [
                    {"role": "system", "content": AVATARIFY_VISION_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=3000,
            )
        except Exception as e:
            raise GenJobError(f"照片分析失败：{e}")

        parsed = _extract_img2img_json(content)
        if not parsed or not parsed["image_prompt"]:
            raise GenJobError("提示词生成失败，请重试")

        # 保底：同框模式但提示词漏了许墨形象锚点时，前置固定英文外貌句
        image_prompt = parsed["image_prompt"]
        if mode == "duo" and "Lucien" not in image_prompt:
            image_prompt = f"{XUMO_LOOK_EN}. {image_prompt}"

        gen_url = await _openai_generate_image(image_prompt, AVATARIFY_DIR, "/static/avatarify", work_id, size, has_character=True, quality=quality)
        if not gen_url:
            raise GenJobError("绘图服务暂时不可用，请稍后重试")

        # 付费扣费：非 owner 从钱包扣对应档位价格
        _wallet_consume_for_image(quality)

        record = {
            "id": work_id,
            "mode": mode,
            "theme": theme,
            "theme_name": theme_meta["name"],
            "ratio": ratio,
            "quality": quality,
            "extra": extra.strip(),
            "src": src_url,
            "gen": gen_url,
            "prompt": image_prompt,
            "traits": (parsed.get("desc") or "") if isinstance(parsed, dict) else "",
            "comment": parsed["comment"],
            "time": datetime.now().strftime("%m-%d %H:%M"),
        }
        # traits 单独解析（_extract_img2img_json 不含该键）
        m = re.search(r"\{.*\}", content, re.S)
        if m:
            try:
                _extra = json.loads(m.group(0))
                if isinstance(_extra, dict):
                    record["traits"] = (_extra.get("traits") or "").strip()
            except json.JSONDecodeError:
                pass

        records = _load_avatarify()
        records.append(record)
        records = records[-60:]
        _save_avatarify(records)

        info = _add_affinity("avatarify", f"化身卡面 · {theme_meta['name']}{' · 与许墨同框' if mode == 'duo' else ''}")
        return {"record": record, "affinity": info}

    if data.get("bg"):
        job = await submit_gen_job("avatarify", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


@app.get("/api/avatarify/history")
async def avatarify_history():
    """化身历史，最新在前。"""
    return {"records": list(reversed(_load_avatarify()))}


@app.delete("/api/avatarify/{record_id}")
async def avatarify_delete(record_id: str):
    records = _load_avatarify()
    kept = [r for r in records if r.get("id") != record_id]
    if len(kept) == len(records):
        return JSONResponse({"error": "化身不存在"}, status_code=404)
    _save_avatarify(kept)
    for r in records:
        if r.get("id") == record_id:
            for key in ("src", "gen"):
                try:
                    role_file(r[key].lstrip("/")).unlink(missing_ok=True)
                except Exception:
                    pass
    return {"ok": True}


# ================= 世界·恋语市：自定义地点（含图生图配图） =================
WORLD_PLACES_FILE = RolePath("world_places.json")
WORLD_PLACES_DIR = RolePath("static", "world_places")

WORLD_PLACE_PROMPT = """你是《恋与制作人》恋语市的地图绘制师。玩家要在开放世界地图上新建一个自定义地点，并为其绘制一张场景配图。你的任务：根据地点名称与描述（若有参考图请先看懂图），输出地点简介与可直接用于 AI 绘图的英文提示词。

【世界观】恋语市：以上海为原型的滨海都市，浪漫日常风；许墨（Lucien）是恋语大学教授，象征色紫色、象征物蝴蝶。

【画风】Mr Love: Queen's Choice official art style, anime otome game background illustration, semi-thick painting, soft romantic palette, cinematic light, no people（配图为场景图，不要出现人物）

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{
  "desc": "中文地点简介，40-80字，写进地图图鉴，末尾可带一句氛围描写",
  "image_prompt": "英文绘图提示词，60-120词。必须包含：地点的场景元素与构图、时间/天气氛围、恋与制作人画风关键词、统一色调（可参考玩家选的风格）",
  "comment": "以许墨第一人称说的一句中文短评（15-40字），温柔含笑，可带学术梗或蝴蝶意象，针对这个地点"
}
"""

# 地点视觉风格预设（融合进绘图提示词）
WORLD_PLACE_STYLES = {
    "sunset":  { "name": "黄昏暮色", "prompt": "golden sunset hour, warm amber glow, long soft shadows" },
    "night":   { "name": "城市夜色", "prompt": "city night scene, neon lights, starry sky, cool violet-blue palette" },
    "rain":    { "name": "细雨朦胧", "prompt": "gentle rain, misty atmosphere, umbrella, wet reflective ground" },
    "spring":  { "name": "春日花语", "prompt": "spring blossom season, petals in the air, fresh pastel colors" },
    "snow":    { "name": "落雪时分", "prompt": "soft snowfall, quiet winter mood, warm window lights" },
    "dream":   { "name": "蝶梦幻境", "prompt": "dreamlike fantasy mood, purple butterflies, glowing light particles" },
    "free":    { "name": "自由风格", "prompt": "follow the user's description freely" },
}


def _load_world_places() -> list:
    if WORLD_PLACES_FILE.exists():
        try:
            data = json.loads(WORLD_PLACES_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_world_places(places: list):
    atomic_json(WORLD_PLACES_FILE, places)


@app.get("/api/world/places")
async def world_places_list():
    """自定义地点列表。"""
    return {"places": list(reversed(_load_world_places())), "styles": [
        {"key": k, "name": v["name"]} for k, v in WORLD_PLACE_STYLES.items()
    ]}


@app.post("/api/world/places")
async def world_place_create(req: Request):
    """创建自定义地点：LLM 润色简介 + 图生图（可选参考图）生成场景配图。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "请填写地点名称"}, status_code=400)
    if len(name) > 20:
        return JSONResponse({"error": "名称不能超过 20 字"}, status_code=400)
    desc = (data.get("desc") or "").strip()[:200]
    icon = (data.get("icon") or "📍").strip()[:4] or "📍"
    kind = data.get("kind") if data.get("kind") in ("build", "mark") else "build"
    style = data.get("style") if data.get("style") in WORLD_PLACE_STYLES else "sunset"
    ratio = data.get("ratio") if data.get("ratio") in IMG2IMG_SIZES else "landscape"
    size = IMG2IMG_SIZES[ratio]
    try:
        px = int(data.get("x")), int(data.get("y"))
        x = max(2, min(141, px[0]))
        y = max(2, min(141, px[1]))
    except (TypeError, ValueError):
        return JSONResponse({"error": "地点坐标不合法"}, status_code=400)

    image_b64 = (data.get("image") or "").strip()
    raw = None
    if image_b64:
        if image_b64.startswith("data:"):
            _, _, image_b64 = image_b64.partition(",")
        try:
            raw = base64.b64decode(image_b64)
        except Exception:
            return JSONResponse({"error": "参考图解码失败"}, status_code=400)
        if len(raw) > 8 * 1024 * 1024:
            return JSONResponse({"error": "参考图不能超过 8MB"}, status_code=400)

    style_meta = WORLD_PLACE_STYLES[style]
    user_text = (
        f"地点名称：{name}\n"
        f"玩家描述：{desc or '（无，请根据名称自由发挥）'}\n"
        f"地点类型：{'建筑' if kind == 'build' else '户外地标'}\n"
        f"视觉风格：{style_meta['name']}（{style_meta['prompt']}）\n"
        f"画幅比例：{ratio}（portrait=竖版 / landscape=横版 / square=方形）\n"
    )
    content_part = [{"type": "text", "text": user_text + "请按要求输出 JSON。"}]
    if raw:
        content_part.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(raw).decode()
        }})
    try:
        content = await _call_llm(
            [
                {"role": "system", "content": WORLD_PLACE_PROMPT},
                {"role": "user", "content": content_part},
            ],
            max_tokens=2000,
        )
    except Exception as e:
        return JSONResponse({"error": f"地点构思失败：{e}"}, status_code=500)

    parsed = _extract_img2img_json(content)
    if not parsed or not parsed["image_prompt"]:
        return JSONResponse({"error": "地点构思失败，请重试"}, status_code=500)

    place_id = "cp_" + uuid.uuid4().hex[:10]
    img_url = await _openai_generate_image(
        parsed["image_prompt"] + ", " + style_meta["prompt"]
        if style != "free" else parsed["image_prompt"],
        WORLD_PLACES_DIR, "/static/world_places", place_id, size,
        has_character=False,
    )
    if not img_url:
        return JSONResponse({"error": "绘图服务暂时不可用，请稍后重试"}, status_code=500)

    w, h = (2, 2) if kind == "build" else (1, 1)
    place = {
        "id": place_id,
        "name": name,
        "desc": parsed["desc"] or desc or name,
        "icon": icon,
        "kind": kind,
        "style": style,
        "style_name": style_meta["name"],
        "x": x, "y": y, "w": w, "h": h,
        "img": img_url,
        "prompt": parsed["image_prompt"],
        "comment": parsed["comment"],
        "time": datetime.now().strftime("%m-%d %H:%M"),
    }
    places = _load_world_places()
    places.append(place)
    places = places[-80:]
    _save_world_places(places)

    info = _add_affinity("world_place", f"新建地点 · {name}")
    return {"place": place, "affinity": info}


@app.delete("/api/world/places/{place_id}")
async def world_place_delete(place_id: str):
    places = _load_world_places()
    kept = [p for p in places if p.get("id") != place_id]
    if len(kept) == len(places):
        return JSONResponse({"error": "地点不存在"}, status_code=404)
    _save_world_places(kept)
    for p in places:
        if p.get("id") == place_id and p.get("img"):
            try:
                role_file(p["img"].lstrip("/")).unlink(missing_ok=True)
            except Exception:
                pass
    return {"ok": True}


# ================= 世界·恋语市：建筑入内（室内场景 AI 插画） =================
# 玩家进入 POI 建筑 → 切换到全屏室内视图（AI 生成的室内插图作背景 + HTML 热点叠加）
WORLD_INTERIORS_FILE = RolePath("world_interiors.json")
WORLD_INTERIORS_DIR = RolePath("static", "world_interiors")

WORLD_INTERIOR_PROMPT = """你是《恋与制作人》恋语市的室内场景绘制师。玩家要进入一个建筑的室内，请根据建筑名与玩家描述，输出室内简介与可直接用于 AI 绘图的英文提示词。

【世界观】恋语市：以上海为原型的滨海都市，浪漫日常风；许墨（Lucien）是恋语大学教授，象征色紫色、象征物蝴蝶。

【画风】Mr Love: Queen's Choice official art style, anime otome game interior background illustration, semi-thick painting, soft romantic palette, cinematic light, no people（室内场景图，不要出现人物，留出前景互动空间）

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{
  "desc": "中文室内简介，40-100字，写进室内图鉴，描绘氛围与陈设",
  "image_prompt": "英文绘图提示词，60-140词。必须包含：室内场景元素与构图、家具/陈设、时间/天气氛围、恋与制作人画风关键词、统一色调",
  "comment": "以许墨第一人称说的一句中文短评（15-40字），温柔含笑，可带学术梗或蝴蝶意象，针对这个室内"
}
"""


def _load_world_interiors() -> dict:
    if WORLD_INTERIORS_FILE.exists():
        try:
            data = json.loads(WORLD_INTERIORS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _save_world_interiors(d: dict):
    WORLD_INTERIORS_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


@app.get("/api/world/interiors")
async def world_interiors_list():
    """列出所有已生成的室内场景配置（前端拿 img URL + desc 渲染）"""
    return {"interiors": _load_world_interiors()}


@app.post("/api/world/interiors/{place_id}")
async def world_interior_get_or_create(place_id: str, req: Request):
    """生成或取回某建筑的室内场景。POST body: {name, prompt_hint}。
    若缓存中已有则直接返回；否则调 LLM 增强 prompt → 生图 → 落盘 → 缓存。
    """
    data = await req.json()
    name = (data.get("name") or place_id).strip()
    prompt_hint = (data.get("prompt_hint") or "").strip()

    interiors = _load_world_interiors()
    cached = interiors.get(place_id)
    if cached and cached.get("img"):
        # 已生成过，直接返回（前端热点配置在 INTERIORS 静态表里）
        return {"interior": cached}

    # LLM 增强：玩家 prompt_hint + 建筑名 → 完整 image_prompt + desc + comment
    user_text = (
        f"建筑名称：{name}\n"
        f"玩家描述：{prompt_hint or '（无，请根据建筑名称自由发挥室内陈设）'}\n"
        f"画幅比例：landscape（横版全景，便于全屏背景）\n"
    )
    try:
        content = await _call_llm(
            [
                {"role": "system", "content": WORLD_INTERIOR_PROMPT},
                {"role": "user", "content": user_text + "请按要求输出 JSON。"},
            ],
            max_tokens=2000,
        )
    except Exception as e:
        return JSONResponse({"error": f"室内构思失败：{e}"}, status_code=500)

    parsed = _extract_img2img_json(content)
    if not parsed or not parsed["image_prompt"]:
        return JSONResponse({"error": "室内构思失败，请重试"}, status_code=500)

    size = "landscape_16_9"
    img_url = await _openai_generate_image(
        parsed["image_prompt"],
        WORLD_INTERIORS_DIR, "/static/world_interiors", place_id, size,
        has_character=False,
    )
    if not img_url:
        return JSONResponse({"error": "绘图服务暂时不可用，请稍后重试"}, status_code=500)

    interior = {
        "place_id": place_id,
        "name": name,
        "img": img_url,
        "desc": parsed.get("desc") or "",
        "comment": parsed.get("comment") or "",
        "prompt": parsed["image_prompt"],
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    interiors[place_id] = interior
    _save_world_interiors(interiors)
    return {"interior": interior}


@app.delete("/api/world/interiors/{place_id}")
async def world_interior_delete(place_id: str):
    """删除某建筑室内场景缓存（重新生成时用）"""
    interiors = _load_world_interiors()
    if place_id in interiors:
        img = interiors[place_id].get("img", "")
        del interiors[place_id]
        _save_world_interiors(interiors)
        if img:
            try:
                role_file(img.lstrip("/")).unlink(missing_ok=True)
            except Exception:
                pass
    return {"ok": True}


# ================= 世界·恋语市：地形改造（建造模式笔刷持久化） =================
WORLD_EDITS_FILE = RolePath("world_edits.json")
WORLD_EDITS_MAX = 6000   # 地形编辑 tile 上限（超出淘汰最早）


def _load_world_edits() -> dict:
    if WORLD_EDITS_FILE.exists():
        try:
            data = json.loads(WORLD_EDITS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_world_edits(edits: dict):
    atomic_json(WORLD_EDITS_FILE, edits, indent=None)


@app.get("/api/world/edits")
async def world_edits_list():
    """全部地形改造（笔刷编辑过的 tile）。"""
    edits = _load_world_edits()
    out = []
    for key, e in edits.items():
        try:
            xs, ys = key.split(",")
            rec = {"x": int(xs), "y": int(ys)}
            if "b" in e:
                rec["b"] = e["b"]
            if "d" in e:
                rec["d"] = e["d"]
            out.append(rec)
        except Exception:
            continue
    return {"edits": out, "count": len(out)}


@app.post("/api/world/edits")
async def world_edits_apply(req: Request):
    """批量提交地形编辑（建造模式笔刷涂抹，前端节流上传）。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    tiles = data.get("tiles")
    if not isinstance(tiles, list) or not tiles:
        return JSONResponse({"error": "缺少 tiles"}, status_code=400)
    if len(tiles) > 200:
        return JSONResponse({"error": "单次最多提交 200 格"}, status_code=400)

    edits = _load_world_edits()
    for t in tiles:
        if not isinstance(t, dict):
            continue
        try:
            x, y = int(t.get("x")), int(t.get("y"))
        except (TypeError, ValueError):
            continue
        if not (0 <= x < 144 and 0 <= y < 144):
            continue
        b, d = t.get("b"), t.get("d")
        if b is not None:
            b = int(b)
            if not (0 <= b <= 14):
                b = None
        if d is not None:
            d = int(d)
            if not (0 <= d <= 3):
                d = None
        if b is None and d is None:
            continue
        key = f"{x},{y}"
        cur = edits.get(key, {})
        rec = {}
        if b is not None or "b" in cur:
            rec["b"] = b if b is not None else cur["b"]
        if d is not None or "d" in cur:
            rec["d"] = d if d is not None else cur["d"]
        edits[key] = rec   # 覆盖保序
    while len(edits) > WORLD_EDITS_MAX:
        edits.pop(next(iter(edits)))
    _save_world_edits(edits)
    return {"ok": True, "count": len(edits)}


@app.delete("/api/world/edits")
async def world_edits_clear():
    """清空全部地形改造，恢复原生地貌。"""
    _save_world_edits({})
    return {"ok": True}


# ================= 世界·恋语市：AI 智能建设（地形+地点+建筑一站式生成） =================
WORLD_AI_TERRAIN_MAX = 1000   # AI 单次建设最多改造的 tile 数

WORLD_AI_BUILD_PROMPT = """你是《恋与制作人》恋语市的城市设计师许墨，温柔博学，擅长把玩家一个模糊的念头变成完整的城市设计。玩家要在开放世界地图（144×144 tile）上做一次小型开发，你需要输出一套「建设方案」：地形改造 + 地点/建筑 + 装饰 + 居民 + 事件。

【地形编号 b】0深海(禁行) 1浅水(禁行) 2沙滩 3草地 4森林 5丘陵 6山地(禁行) 7雪峰(禁行) 8马路 9广场砖 10建筑(禁行) 11公园草 12室内地板 13木桥 14田野
【装饰编号 d】0无 1树 2路灯 3花 4石头 5灌木 6蘑菇 7长椅 8围栏 9喷泉 10摊位 11路标 12篝火 13枯树 14野花丛 15古典路灯
【规划铁律】
- 一切落在给定中心约 ±10 格内，任何坐标夹在 2~141；
- 建设中心点周围 2 格内必须保持可通行（玩家可能正站在那里，禁止用水体/建筑围死中心）；
- 先铺地形（rect/circle），再放建筑：kind=build 的地点会落地为实体建筑块（尺寸建议 2×2 ~ 4×3），门口一行会自动留出道路；
- 装饰(d>0)的指令必须同时带一个非实体 b（例如草地+花丛、公园草+树），禁止把树种在水里/山上；
- terrain 指令最多 12 条，两种形状：{"shape":"rect","x":左上x,"y":左上y,"w":宽,"h":高,"b":编号,"d":可选} 或 {"shape":"circle","x":圆心x,"y":圆心y,"r":半径≤8,"b":编号,"d":可选}；rect 的 w、h ≤ 18；
- places 最多 6 个，name ≤ 12 字，icon 用一个 emoji；kind: build(建筑)/mark(户外地标，w=h=1)；
- decors 最多 20 个，每个 {"x":坐标,"y":坐标,"d":装饰编号}，用于精细点缀（喷泉/长椅/篝火/摊位/路标等），不得压在实体地形上；
- npcs 最多 3 个，每个 {"name":"名字≤12字","emoji":"一个emoji","color":"#rrggbb","lines":["台词1","台词2"],"x":坐标,"y":坐标}，台词≤6 句、每句≤80 字；居民是恋语市普通市民，不是许墨/男主；
- event 可选 1 个，{"title":"事件名≤12字","text":"事件描述30-80字","kind":"rumor或visitor或event"}，作为这片新区域的「开业事件」出现在城市脉搏里；
- 与已有地点保持 ≥3 格间距，不得压在已有地点坐标上；
- 风格：恋语市浪漫日常风，命名有故事感（可用蝴蝶/星空/花/海的意象）。

【输出】只输出一个 JSON 对象，不要任何其他文字：
{
  "title": "方案名，≤12字",
  "concept": "以许墨第一人称说设计思路，30-60字，温柔含笑",
  "terrain": [ ...形状指令... ],
  "places": [ {"name":"…","icon":"⛩️","kind":"build","x":1,"y":1,"w":2,"h":2,"desc":"一句话场景简介（20-40字）"} ],
  "decors": [ {"x":1,"y":1,"d":9} ],
  "npcs": [ {"name":"小鹿","emoji":"🦌","color":"#eab308","lines":["今天的晚霞很好看。"],"x":1,"y":1} ],
  "event": {"title":"新店开张","text":"街角传来咖啡香，新开的店今天营业了。","kind":"event"}
}
想法很小就给 1~2 条 terrain、1 个 place、不加 npcs/event；想法再大也不得超出条数上限。"""

# 内置 POIS 摘要（与 static/world-data.js 保持一致，供 LLM 避让）
WORLD_BUILTIN_POIS = [
    ("你的公寓", 100, 78), ("街角咖啡店", 88, 74), ("脑科学研究院", 83, 67),
    ("恋语大学", 75, 61), ("旧图书馆", 87, 80), ("日夜超市", 97, 76),
    ("教工公寓", 86, 76), ("中央钟楼", 92, 72), ("梧桐公园", 99, 66),
    ("北岬灯塔", 112, 48), ("神庙遗迹", 42, 58), ("废弃实验室", 64, 39),
    ("临海栈桥", 122, 84), ("北岭矿脉", 58, 34), ("星辰石碑群", 41, 57),
]


def _extract_ai_build_json(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _world_pois_brief() -> str:
    lines = ["- %s (%d,%d)" % p for p in WORLD_BUILTIN_POIS]
    for p in _load_world_places():
        try:
            lines.append("- %s (%d,%d)" % (str(p.get("name") or "?"), int(p.get("x") or 0), int(p.get("y") or 0)))
        except (TypeError, ValueError):
            continue
    return "\n".join(lines)


def _expand_ai_terrain(terrain) -> list:
    """LLM 形状指令 → tile 列表（去重、越界丢弃、限量）。"""
    tiles: dict = {}
    for t in terrain if isinstance(terrain, list) else []:
        if not isinstance(t, dict):
            continue
        b, d = t.get("b"), t.get("d")
        try:
            b = int(b) if b is not None else None
            d = int(d) if d is not None else None
        except (TypeError, ValueError):
            continue
        if not ((b is not None and 0 <= b <= 14) or (d is not None and 0 <= d <= 3)):
            continue
        cells = []
        try:
            if t.get("shape") == "circle":
                cx0, cy0 = int(t.get("x")), int(t.get("y"))
                r = min(8, max(1, int(t.get("r") or 2)))
                for yy in range(cy0 - r, cy0 + r + 1):
                    for xx in range(cx0 - r, cx0 + r + 1):
                        if (xx - cx0) ** 2 + (yy - cy0) ** 2 <= r * r + r:
                            cells.append((xx, yy))
            else:
                x0, y0 = int(t.get("x")), int(t.get("y"))
                w = min(18, max(1, int(t.get("w") or 1)))
                h = min(18, max(1, int(t.get("h") or 1)))
                for yy in range(y0, y0 + h):
                    for xx in range(x0, x0 + w):
                        cells.append((xx, yy))
        except (TypeError, ValueError):
            continue
        for xx, yy in cells:
            if not (0 <= xx < 144 and 0 <= yy < 144):
                continue
            key = f"{xx},{yy}"
            rec = dict(tiles.get(key, {}))
            if b is not None and 0 <= b <= 14:
                rec["b"] = b
            if d is not None and 0 <= d <= 3:
                rec["d"] = d
            tiles[key] = rec
            if len(tiles) >= WORLD_AI_TERRAIN_MAX:
                break
        if len(tiles) >= WORLD_AI_TERRAIN_MAX:
            break
    out = []
    for key, rec in tiles.items():
        xs, ys = key.split(",")
        e = {"x": int(xs), "y": int(ys)}
        if "b" in rec:
            e["b"] = rec["b"]
        if "d" in rec:
            e["d"] = rec["d"]
        out.append(e)
    return out


def _sanitize_ai_places(raw) -> list:
    places = []
    if not isinstance(raw, list):
        return places
    for p in raw:
        if not isinstance(p, dict) or len(places) >= 6:
            break
        name = str(p.get("name") or "").strip()[:20]
        if not name:
            continue
        icon = str(p.get("icon") or "📍").strip()[:4] or "📍"
        kind = p.get("kind") if p.get("kind") in ("build", "mark") else "build"
        try:
            x = max(2, min(141, int(p.get("x"))))
            y = max(2, min(141, int(p.get("y"))))
        except (TypeError, ValueError):
            continue
        w = max(1, min(6, int(p.get("w") or (2 if kind == "build" else 1))))
        h = max(1, min(6, int(p.get("h") or (2 if kind == "build" else 1))))
        places.append({
            "name": name, "icon": icon, "kind": kind,
            "x": min(x, 143 - w), "y": min(y, 143 - h),
            "w": w, "h": h,
            "desc": str(p.get("desc") or "").strip()[:120],
        })
    return places


def _sanitize_ai_decors(raw) -> list:
    """AI 方案里的 decor 列表 → 校验后的 [{x,y,d}]。"""
    out = []
    if not isinstance(raw, list):
        return out
    for d in raw:
        if not isinstance(d, dict) or len(out) >= 20:
            break
        try:
            x = max(2, min(141, int(d.get("x"))))
            y = max(2, min(141, int(d.get("y"))))
            dv = int(d.get("d"))
        except (TypeError, ValueError):
            continue
        if not (0 <= dv <= 15):
            continue
        out.append({"x": x, "y": y, "d": dv})
    return out


def _sanitize_ai_npc_draft(raw) -> list:
    """AI 方案里的 NPC 草稿 → 校验后的 [{name,emoji,color,lines,x,y}]。"""
    out = []
    if not isinstance(raw, list):
        return out
    for n in raw:
        if not isinstance(n, dict) or len(out) >= 3:
            break
        name = str(n.get("name") or "").strip()[:12]
        if not name:
            continue
        emoji = str(n.get("emoji") or "🙂").strip()[:4] or "🙂"
        color = str(n.get("color") or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#8b5cf6"
        raw_lines = n.get("lines")
        if not isinstance(raw_lines, list):
            raw_lines = str(raw_lines or "").splitlines()
        lines = [str(l).strip()[:80] for l in raw_lines if str(l).strip()]
        lines = lines[:6]
        if not lines:
            lines = ["你好，欢迎来恋语市。"]
        try:
            x = max(2, min(141, int(n.get("x"))))
            y = max(2, min(141, int(n.get("y"))))
        except (TypeError, ValueError):
            continue
        out.append({
            "name": name, "emoji": emoji, "color": color,
            "lines": lines, "x": x, "y": y,
        })
    return out


def _sanitize_ai_event(raw) -> dict | None:
    """AI 方案里的 event → 校验后的 {title,text,kind} 或 None。"""
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()[:12]
    text = str(raw.get("text") or "").strip()[:120]
    if not title or not text:
        return None
    kind = raw.get("kind") if raw.get("kind") in ("rumor", "visitor", "event") else "event"
    return {"title": title, "text": text, "kind": kind}


def _ai_build_cost(tile_count: int) -> tuple[int, int]:
    """AI 建设批发价：基础设计费 + 每格 ¥2，体力每 5 格 +1 封顶 60。"""
    money = 30 + tile_count * 2
    sp = min(60, 10 + (tile_count + 4) // 5)
    return money, sp


@app.post("/api/world/ai/design")
async def world_ai_design(req: Request):
    """AI 智能建设：根据玩家想法生成建设方案（地形+地点+建筑），不落盘。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    idea = str(data.get("idea") or "").strip()[:120]
    if not idea:
        return JSONResponse({"error": "先告诉许墨你想建点什么吧"}, status_code=400)
    try:
        cx = max(2, min(141, int(data.get("x"))))
        cy = max(2, min(141, int(data.get("y"))))
    except (TypeError, ValueError):
        cx, cy = 100, 78

    user = (
        f"玩家想法：{idea}\n"
        f"建设中心：地图坐标 ({cx}, {cy})，方案主体应落在中心 ±10 格内\n"
        f"已有地点（保持 ≥3 格间距，禁止重叠）：\n{_world_pois_brief()}\n"
        f"请输出建设方案 JSON。"
    )
    try:
        content = await _call_llm(
            [{"role": "system", "content": WORLD_AI_BUILD_PROMPT},
             {"role": "user", "content": user}],
            max_tokens=3000,
        )
    except Exception as e:
        print(f"[world] ai_design LLM call failed: {e}", flush=True)
        return JSONResponse({"error": f"方案构思失败：{e}"}, status_code=500)

    print(f"[world] ai_design LLM returned, len={len(content)}, head={content[:200]!r}", flush=True)
    plan = _extract_ai_build_json(content)
    print(f"[world] ai_design extracted plan={plan!r}", flush=True)
    if not plan or not any(plan.get(k) for k in ("terrain", "places", "decors", "npcs", "event")):
        print(f"[world] ai_design plan invalid (no content), full content:\n{content[:1000]}", flush=True)
        return JSONResponse({"error": "方案构思失败，请换个说法再试"}, status_code=500)

    title = str(plan.get("title") or idea)[:12]
    concept = str(plan.get("concept") or "").strip()[:100]
    tiles = _expand_ai_terrain(plan.get("terrain"))
    places = _sanitize_ai_places(plan.get("places"))
    decors = _sanitize_ai_decors(plan.get("decors"))
    npc_drafts = _sanitize_ai_npc_draft(plan.get("npcs"))
    event = _sanitize_ai_event(plan.get("event"))
    if not tiles and not places and not decors and not npc_drafts:
        return JSONResponse({"error": "方案里没有可建设的内容，请重试"}, status_code=500)
    # cost：tile + decor + npc + event 综合计价
    extra = len(decors) + len(npc_drafts) * 5 + (5 if event else 0)
    money, sp = _ai_build_cost(len(tiles) + extra)
    return {
        "plan": {"title": title, "concept": concept,
                 "terrain": plan.get("terrain") or [], "places": places,
                 "decors": decors, "npcs": npc_drafts, "event": event},
        "tile_count": len(tiles),
        "decor_count": len(decors),
        "npc_count": len(npc_drafts),
        "has_event": bool(event),
        "cost_money": money,
        "cost_sp": sp,
    }


@app.post("/api/world/ai/build")
async def world_ai_build(req: Request):
    """AI 智能建设：应用方案，写入地形编辑与自定义地点。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    plan = data.get("plan") if isinstance(data.get("plan"), dict) else {}
    tiles = _expand_ai_terrain(plan.get("terrain"))
    places = _sanitize_ai_places(plan.get("places"))
    decors = _sanitize_ai_decors(plan.get("decors"))
    npc_drafts = _sanitize_ai_npc_draft(plan.get("npcs"))
    event = _sanitize_ai_event(plan.get("event"))
    if not tiles and not places and not decors and not npc_drafts:
        return JSONResponse({"error": "方案内容为空"}, status_code=400)

    title = str(plan.get("title") or "新的风景")[:12]
    concept = str(plan.get("concept") or "").strip()[:100]

    edits = _load_world_edits()
    for e in tiles:
        key = f"{e['x']},{e['y']}"
        cur = edits.get(key, {})
        rec = {}
        if "b" in e or "b" in cur:
            rec["b"] = e.get("b", cur.get("b"))
        if "d" in e or "d" in cur:
            rec["d"] = e.get("d", cur.get("d"))
        edits[key] = rec
    # 独立 decor（不带 b）也合并到 edits 的 d 字段
    for d in decors:
        key = f"{d['x']},{d['y']}"
        cur = edits.get(key, {})
        cur["d"] = d["d"]
        if "b" in cur:
            edits[key] = cur
        else:
            edits[key] = {"d": d["d"]}
    while len(edits) > WORLD_EDITS_MAX:
        edits.pop(next(iter(edits)))
    _save_world_edits(edits)

    saved_places = _load_world_places()
    now = datetime.now().strftime("%m-%d %H:%M")
    new_places = []
    for p in places:
        rec = {
            "id": "ab_" + uuid.uuid4().hex[:8],
            "name": p["name"],
            "desc": p["desc"] or (title + " · AI 规划"),
            "icon": p["icon"], "kind": p["kind"],
            "style": "free", "style_name": "AI 建设",
            "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"],
            "img": "", "prompt": "", "comment": concept,
            "time": now,
        }
        saved_places.append(rec)
        new_places.append(rec)
    saved_places = saved_places[-80:]
    _save_world_places(saved_places)

    # 落住 NPC 居民
    new_npcs = []
    if npc_drafts:
        saved_npcs = _load_world_npcs()
        for n in npc_drafts:
            rec = {
                "id": "cn_" + uuid.uuid4().hex[:8],
                "name": n["name"], "emoji": n["emoji"], "color": n["color"],
                "lines": n["lines"], "x": n["x"], "y": n["y"],
                "desc": title + " · AI 设计居民",
                "time": now,
            }
            saved_npcs.append(rec)
            new_npcs.append(rec)
        _save_world_npcs(saved_npcs[-WORLD_NPCS_MAX:])

    info = _add_affinity("world_place", f"AI 建设落成 · {title}")
    extra = len(decors) + len(npc_drafts) * 5 + (5 if event else 0)
    money, sp = _ai_build_cost(len(tiles) + extra)
    return {
        "ok": True, "title": title,
        "places": new_places,
        "edits": tiles, "tile_count": len(tiles),
        "decors": decors, "decor_count": len(decors),
        "npcs": new_npcs, "npc_count": len(new_npcs),
        "event": event,
        "cost_money": money, "cost_sp": sp,
        "affinity": info,
    }


# ================= 世界·恋语市：自定义居民（NPC） =================
WORLD_NPCS_FILE = RolePath("world_npcs.json")
WORLD_NPCS_MAX = 40
WORLD_NPC_COLORS = [
    "#8b5cf6", "#ec4899", "#f59e0b", "#10b981",
    "#0ea5e9", "#6366f1", "#ef4444", "#64748b",
]


def _load_world_npcs() -> list:
    if WORLD_NPCS_FILE.exists():
        try:
            data = json.loads(WORLD_NPCS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_world_npcs(npcs: list):
    atomic_json(WORLD_NPCS_FILE, npcs)


@app.get("/api/world/npcs")
async def world_npcs_list():
    return {"npcs": list(reversed(_load_world_npcs())), "colors": WORLD_NPC_COLORS}


@app.post("/api/world/npcs")
async def world_npc_create(req: Request):
    """创建自定义居民：落住恋语市，可对话、有台词轮播。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    name = (data.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "请给居民起个名字"}, status_code=400)
    if len(name) > 12:
        return JSONResponse({"error": "名字不能超过 12 字"}, status_code=400)
    emoji = (data.get("emoji") or "🙂").strip()[:4] or "🙂"
    color = (data.get("color") or "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#8b5cf6"
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list):
        raw_lines = str(raw_lines or "").splitlines()
    lines = [str(l).strip()[:80] for l in raw_lines if str(l).strip()]
    lines = lines[:6]
    if not lines:
        return JSONResponse({"error": "至少写一句 TA 会说的话"}, status_code=400)
    try:
        px, py = int(data.get("x")), int(data.get("y"))
        x = max(2, min(141, px))
        y = max(2, min(141, py))
    except (TypeError, ValueError):
        return JSONResponse({"error": "位置坐标不合法"}, status_code=400)

    npc = {
        "id": "cn_" + uuid.uuid4().hex[:8],
        "name": name, "emoji": emoji, "color": color,
        "lines": lines, "x": x, "y": y,
        "time": datetime.now().strftime("%m-%d %H:%M"),
    }
    desc = (data.get("desc") or "").strip()
    if desc:
        npc["desc"] = desc[:80]
    npcs = _load_world_npcs()
    npcs.append(npc)
    _save_world_npcs(npcs[-WORLD_NPCS_MAX:])
    info = _add_affinity("world_place", f"新居民入住了恋语市 · {name}")
    return {"npc": npc, "affinity": info}


@app.delete("/api/world/npcs/{npc_id}")
async def world_npc_delete(npc_id: str):
    npcs = _load_world_npcs()
    kept = [n for n in npcs if n.get("id") != npc_id]
    if len(kept) == len(npcs):
        return JSONResponse({"error": "居民不存在"}, status_code=404)
    _save_world_npcs(kept)
    return {"ok": True}


# --- 自定义居民 · AI 肖像（为一位居民生成恋语市画风立绘） ---
NPC_IMG_DIR = RolePath("static", "npc_img")

NPC_PORTRAIT_PROMPT = """你是《恋与制作人》开放世界「恋语市」的居民立绘绘制助手。下面给出一位自定义居民的设定，请据此构思一幅 TA 的半身/全身立绘，并输出一段可直接用于 AI 绘图的英文提示词。

【画面要求】
- 这位居民是恋语市的普通市民（不是许墨/男主），请按设定绘制其外貌、年龄、着装与气质
- 日系乙女向精致立绘、厚涂+赛璐璐、五官与手部精致、柔和唯美用色、氛围感光影
- 背景虚化，可带一点恋语市街景（咖啡馆/公园/栈桥/灯塔/书店/市集）的氛围光斑
- 画面色调与该居民的代表色呼应

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{{"image_prompt": "英文绘图提示词，80~140 词，包含人物外貌、年龄、着装、姿态、表情、背景氛围与画风关键词"}}"""


@app.post("/api/world/npcs/{npc_id}/image")
async def world_npc_image(npc_id: str, bg: bool = False):
    """为一位自定义居民生成 AI 肖像（按需，落盘并回写到居民记录）。"""
    async def _work():
        npcs = _load_world_npcs()
        npc = next((n for n in npcs if n.get("id") == npc_id), None)
        if not npc:
            raise GenJobError("居民不存在", status=404)
        lines_preview = "；".join((npc.get("lines") or [])[:3])
        material = (
            f"【居民 · {npc.get('emoji', '')} {npc.get('name', '')}】\n"
            f"代表色：{npc.get('color', '#8b5cf6')}\n"
            f"人设：{npc.get('desc', '（未填写，请根据名字与台词自由想象一位恋语市市民）')}\n"
            f"台词：{lines_preview}"
        )
        img_url, img_prompt = await _llm_image_for_text(
            material, NPC_IMG_DIR, "/static/npc_img", f"cn_{npc_id}",
            IMG2IMG_SIZES.get("portrait", "1024x1536"), with_xumo=False,
            system_prompt=NPC_PORTRAIT_PROMPT,
            has_character=True,
        )
        if not img_url:
            raise GenJobError("肖像生成失败，请重试")
        npc["image"] = img_url
        npc["image_prompt"] = img_prompt
        npc["image_time"] = datetime.now().strftime("%m-%d %H:%M")
        _save_world_npcs(npcs)
        return {"image": img_url + f"?t={int(_time.time())}", "affinity": None}

    if bg:
        job = await submit_gen_job("npc", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


# --- 智能设计居民（LLM 生成草稿，不落盘；由她挑选后走 POST /api/world/npcs 入住） ---

SMART_NPC_PROMPT = SYSTEM_PROMPT + """

【当前任务】她想为「恋语市」这座海滨小城设计新居民。请你（许墨）根据她的想法，设计几位有血有肉、有生活气息的市民。
输出严格 JSON（不要任何多余文字）：
{"npcs": [{"name": "...", "emoji": "...", "color": "#hex", "desc": "...", "lines": ["...", "..."]}], "remark": "..."}

要求：
- name：2~6 字中文名，贴合身份与气质，绝不与已有居民重名；
- emoji：一个最能代表 TA 的 emoji；
- color：从 #8b5cf6 #ec4899 #f59e0b #10b981 #0ea5e9 #6366f1 #ef4444 #64748b 中选一个；
- desc：一句话人设（身份 + 性格 + 一个小习惯或小秘密），35 字内；
- lines：4~6 句口语台词，像真的会在街边说出来的话，体现性格与生活质感；其中至多一句可以和这座城的温柔传闻、蝴蝶、灯塔或「大学里那位许教授」有关，点到为止不要刻意；
- remark：以许墨口吻对她说的一句设计笔记，25 字内，笃定而温柔。"""


def _extract_smart_npc_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("npcs"), list):
        return None
    out = []
    for raw in data["npcs"][:3]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()[:12]
        if not name:
            continue
        color = str(raw.get("color") or "").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = random.choice(WORLD_NPC_COLORS)
        lines = [str(l).strip()[:80] for l in (raw.get("lines") or []) if str(l).strip()]
        if not lines:
            continue
        out.append({
            "name": name,
            "emoji": str(raw.get("emoji") or "🙂").strip()[:4] or "🙂",
            "color": color,
            "desc": str(raw.get("desc") or "").strip()[:80],
            "lines": lines[:6],
        })
    if not out:
        return None
    remark = str(data.get("remark") or "").strip()[:60]
    return {"npcs": out, "remark": remark}


@app.post("/api/world/npcs/smart")
async def world_npc_smart(req: Request):
    """智能设计居民：LLM 按她的想法出一批居民草稿（不落盘，挑选后另行入住）。"""
    try:
        data = await req.json()
    except Exception:
        data = {}
    idea = str((data or {}).get("idea") or "").strip()[:120]
    try:
        count = max(1, min(3, int((data or {}).get("count") or 2)))
    except (TypeError, ValueError):
        count = 2

    exist = [n.get("name", "") for n in _load_world_npcs()]
    exist_txt = "、".join(exist) if exist else "（暂无）"
    if not idea:
        idea = random.choice([
            "围绕恋语市的日常角落（咖啡馆、公园、栈桥、灯塔、书店、花店、市集）自由发挥",
            "一群和这座海滨小城气质相符的普通人",
            "带一点奇妙色彩但不脱离日常的市民",
        ])

    user_msg = (
        f"【她的想法】{idea}\n"
        f"【设计人数】{count} 位\n"
        f"【已有居民】{exist_txt}（新居民不要与这些名字重复）\n"
        f"【城市地标】街角咖啡店、香樟公园、临江天桥、灯塔、栈桥、深夜书店、中央市集、大学实验楼\n\n"
        "请输出 JSON。"
    )
    try:
        content = await _call_llm(
            [
                {"role": "system", "content": SMART_NPC_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=1400,
        )
    except Exception as e:
        return JSONResponse({"error": f"居民设计失败：{e}"}, status_code=500)

    parsed = _extract_smart_npc_json(content)
    if not parsed:
        return JSONResponse({"error": "居民设计失败，请重试"}, status_code=500)
    return parsed


# ================= 世界·恋语市：世界脉搏（智能生成事件 / 传闻 / 来客 / 新地点） =================
WORLD_PULSE_FILE = RolePath("world_pulse.json")
WORLD_PULSE_EVENT_MAX = 12     # 事件保留上限（含已完成）
WORLD_PULSE_RUMOR_MAX = 30     # 传闻保留上限
WORLD_PULSE_VISITOR_MAX = 8    # 来客保留上限
WORLD_PULSE_GEN_COOLDOWN = 45  # 两次生成的最小间隔（秒），防连点

WORLD_PULSE_TYPES = {
    "festival": "城市庆典",
    "incident": "突发小事",
    "mystery": "神秘异象",
    "market": "限时集市",
    "weather": "天象奇观",
    "encounter": "浪漫偶遇",
    "show": "街头演出",
    "exhibit": "限时展览",
    "hunt": "全城寻宝",
    "goodwill": "爱心公益",
}
WORLD_PULSE_ITEMS = ["bread", "coffee", "bento", "herb", "iron", "fish"]
WORLD_PULSE_RARITY = {"common": "寻常", "rare": "稀有", "epic": "史诗"}
WORLD_PULSE_VITALITY_MAX = 100   # 城市活力上限

WORLD_PULSE_PROMPT = """你是《恋与制作人》开放世界「恋语市」的城市叙事引擎。恋语市是以上海为原型的滨海都市，浪漫日常中带着一丝"记忆悬疑"；许墨（Lucien）是恋语大学教授，象征色紫色、象征物蝴蝶，语气温和含笑、爱用学术比喻。
根据给出的世界状态，生成一批让城市"活起来"的动态内容：1 个可参与的城市事件（含 2 个分支选择）、2 条城市传闻、1 位限时来访的客人。

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{
  "event": {
    "title": "事件名，6-14字",
    "emoji": "一个贴切的 emoji",
    "type": "festival|incident|mystery|market|weather|encounter|show|exhibit|hunt|goodwill 之一",
    "type_name": "类型中文名，2-4字",
    "desc": "地图图鉴一句话介绍，30-60字",
    "story": "玩家抵达时展开的微故事，120-200字，第二人称'你'，有画面感和余韵，可与许墨或城市记忆 subtly 呼应",
    "comment": "许墨第一人称短评，15-40字，温柔含笑，可带学术梗或蝴蝶意象",
    "reward": {"money": "20到80的整数", "exp": "30到90的整数", "item": "bread|coffee|bento|herb|iron|fish 或 null", "qty": "1或2"},
    "choices": [
      {
        "label": "分支选项，6-12字，动宾短语（如 帮老人修好灯 / 顺着暗巷追过去）",
        "outcome": "选这个分支后发生的事，60-120字，第二人称，有始有终、留余韵",
        "comment": "许墨对这条分支结局的第一人称短评，12-35字",
        "money_delta": "-20到+30的整数（相对基准奖励的增减）",
        "exp_delta": "-15到+40的整数"
      },
      {
        "label": "另一条走向不同的分支，6-12字",
        "outcome": "同上，情绪基调与第一条有差异（如一条热闹一条安静、一条冒险一条温柔）",
        "comment": "许墨短评 12-35字",
        "money_delta": "-20到+30",
        "exp_delta": "-15到+40"
      }
    ]
  },
  "rumors": [
    {"title": "传闻标题 8-16字", "emoji": "一个 emoji", "text": "市井口吻的城市微故事 100-200字，像街坊转述，留有余韵，真假难辨", "comment": "许墨短评 10-30字"},
    {"title": "传闻标题 8-16字", "emoji": "一个 emoji", "text": "同上，题材与第一条不同", "comment": "许墨短评 10-30字"}
  ],
  "visitor": {
    "name": "来客名字 2-6字（如 修表匠阿伯 / 卖花姑娘 / 旅行的诗人）",
    "emoji": "一个 emoji",
    "color": "#8b5cf6 格式的十六进制颜色",
    "lines": ["TA 的一句话，15-40字", "第二句，聊自己在城中的见闻", "第三句，临别的话"]
  }
}

【创作要求】贴合给出的天气/时段/天数/城市活力氛围：活力低时偏安静小事，活力高时可以热闹盛大；十种事件类型轮换出现，避免与"近期事件"的标题和类型重复；传闻要有恋语市的市井温度（钟楼、海堤、咖啡店、大学、灯塔等既有地标可入文）；不要出现真实品牌名。"""

WORLD_PULSE_PLACE_PROMPT = """,
  "place_idea": {
    "name": "新地点名，4-10字",
    "icon": "一个 emoji 图标",
    "kind": "build 或 mark",
    "desc": "中文地点简介 40-80字，写进地图图鉴",
    "image_prompt": "英文绘图提示词 60-120词，包含场景元素与构图、时间/天气氛围、统一色调，以及画风关键词 Mr Love: Queen's Choice official art style, anime otome game background illustration, semi-thick painting, soft romantic palette, cinematic light, no people",
    "comment": "许墨第一人称短评，15-40字",
    "style": "sunset|night|rain|spring|snow|dream 之一"
  }"""


def _load_world_pulse() -> dict:
    if WORLD_PULSE_FILE.exists():
        try:
            data = json.loads(WORLD_PULSE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("events", [])
                data.setdefault("rumors", [])
                data.setdefault("visitors", [])
                data.setdefault("last_gen_ts", 0)
                data.setdefault("gen_count", 0)
                try:
                    data["vitality"] = max(0, min(WORLD_PULSE_VITALITY_MAX, int(data.get("vitality") or 0)))
                except (TypeError, ValueError):
                    data["vitality"] = 20
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"events": [], "rumors": [], "visitors": [], "last_gen_ts": 0, "gen_count": 0, "vitality": 20}


def _add_pulse_vitality(pulse: dict, delta: int):
    before = int(pulse.get("vitality") or 0)
    pulse["vitality"] = max(0, min(WORLD_PULSE_VITALITY_MAX, before + delta))


def _pulse_vitality_level(v: int) -> str:
    if v >= 75:
        return "璀璨之城"
    if v >= 50:
        return "活跃之城"
    if v >= 25:
        return "苏醒之城"
    return "沉睡之城"


def _roll_pulse_rarity(vitality: int) -> str:
    """城市活力越高，稀有事件概率越大。"""
    r = random.random()
    if vitality >= 75:
        return "epic" if r < 0.24 else ("rare" if r < 0.62 else "common")
    if vitality >= 50:
        return "epic" if r < 0.16 else ("rare" if r < 0.50 else "common")
    if vitality >= 25:
        return "epic" if r < 0.10 else ("rare" if r < 0.37 else "common")
    return "epic" if r < 0.06 else ("rare" if r < 0.27 else "common")


def _save_world_pulse(pulse: dict):
    atomic_json(WORLD_PULSE_FILE, pulse)


def _gc_world_pulse(pulse: dict, day: int) -> bool:
    """按游戏日清理过期动态；返回是否发生了变化。"""
    changed = False
    kept, done_seen = [], []
    for e in pulse["events"]:
        try:
            exp = int(e.get("expire_day") or 0)
        except (TypeError, ValueError):
            exp = day
        if e.get("status") == "done":
            done_seen.append(e)
        elif exp >= day:
            kept.append(e)
        else:
            changed = True
    kept += done_seen[-6:]
    if len(done_seen) > 6:
        changed = True
    pulse["events"] = kept[-WORLD_PULSE_EVENT_MAX:]
    visitors = []
    for v in pulse["visitors"]:
        try:
            exp = int(v.get("expire_day") or 0)
        except (TypeError, ValueError):
            exp = day
        if exp >= day:
            visitors.append(v)
        else:
            changed = True
    pulse["visitors"] = visitors[-WORLD_PULSE_VISITOR_MAX:]
    if len(pulse["rumors"]) > WORLD_PULSE_RUMOR_MAX:
        pulse["rumors"] = pulse["rumors"][-WORLD_PULSE_RUMOR_MAX:]
        changed = True
    return changed


def _pulse_txt(v, maxlen: int) -> str:
    return str(v or "").strip()[:maxlen]


def _norm_pulse_payload(data: dict, day: int, vitality: int = 20) -> dict:
    """把 LLM 输出规范化为安全的事件/传闻/来客记录。"""
    now = datetime.now().strftime("%m-%d %H:%M")
    ev = data.get("event") if isinstance(data.get("event"), dict) else {}
    etype = ev.get("type") if ev.get("type") in WORLD_PULSE_TYPES else random.choice(list(WORLD_PULSE_TYPES))
    rarity = _roll_pulse_rarity(vitality)
    reward = ev.get("reward") if isinstance(ev.get("reward"), dict) else {}
    # 稀有度决定奖励上限：common < rare < epic
    cap = {"common": (60, 80), "rare": (90, 120), "epic": (120, 160)}[rarity]
    floor = {"common": (20, 30), "rare": (40, 60), "epic": (60, 90)}[rarity]
    try:
        r_money = max(floor[0], min(cap[0], int(reward.get("money") or 30)))
    except (TypeError, ValueError):
        r_money = floor[0]
    try:
        r_exp = max(floor[1], min(cap[1], int(reward.get("exp") or 40)))
    except (TypeError, ValueError):
        r_exp = floor[1]
    r_item = reward.get("item") if reward.get("item") in WORLD_PULSE_ITEMS else None
    if rarity != "common" and not r_item:
        r_item = random.choice(WORLD_PULSE_ITEMS)
    try:
        r_qty = 2 if (rarity == "epic" and r_item) else (max(1, min(2, int(reward.get("qty") or 1))) if r_item else 0)
    except (TypeError, ValueError):
        r_qty = 1 if r_item else 0
    # 分支选择：LLM 未给/格式不对时构造默认两条
    choices = []
    raw_choices = ev.get("choices") if isinstance(ev.get("choices"), list) else []
    for c in raw_choices[:3]:
        if not isinstance(c, dict):
            continue
        label = _pulse_txt(c.get("label"), 16)
        if not label:
            continue
        try:
            md = max(-20, min(30, int(c.get("money_delta") or 0)))
        except (TypeError, ValueError):
            md = 0
        try:
            ed = max(-15, min(40, int(c.get("exp_delta") or 0)))
        except (TypeError, ValueError):
            ed = 0
        choices.append({
            "label": label,
            "outcome": _pulse_txt(c.get("outcome"), 180) or "你参与了这段城市故事，留下了一段小小的回忆。",
            "comment": _pulse_txt(c.get("comment"), 60),
            "money_delta": md, "exp_delta": ed,
        })
    if not choices:
        choices = [
            {"label": "走进这段故事", "outcome": _pulse_txt(ev.get("story"), 180) or "你参与了这段城市故事，留下了一段小小的回忆。",
             "comment": "", "money_delta": 0, "exp_delta": 0},
            {"label": "静静做个旁观者", "outcome": "你在人群外围看了很久，把这一幕收进心里。城市的故事，也成为你的故事。",
             "comment": "有些风景，远远看着也很好。", "money_delta": -10, "exp_delta": 10},
        ]
    event = {
        "id": "pe_" + uuid.uuid4().hex[:8],
        "title": _pulse_txt(ev.get("title"), 20) or "城市的一天",
        "emoji": _pulse_txt(ev.get("emoji"), 4) or "✨",
        "type": etype,
        "type_name": _pulse_txt(ev.get("type_name"), 6) or WORLD_PULSE_TYPES[etype],
        "rarity": rarity,
        "rarity_name": WORLD_PULSE_RARITY[rarity],
        "desc": _pulse_txt(ev.get("desc"), 120),
        "story": _pulse_txt(ev.get("story"), 420),
        "comment": _pulse_txt(ev.get("comment"), 90),
        "reward": {"money": r_money, "exp": r_exp, "item": r_item, "qty": r_qty},
        "choices": choices,
        "x": random.randint(38, 122), "y": random.randint(40, 106),
        "status": "active",
        "expire_day": day + random.randint(2, 4),
        "time": now,
    }
    rumors = []
    for r in (data.get("rumors") or [])[:2]:
        if not isinstance(r, dict):
            continue
        title = _pulse_txt(r.get("title"), 24)
        if not title:
            continue
        rumors.append({
            "id": "pr_" + uuid.uuid4().hex[:8],
            "title": title,
            "emoji": _pulse_txt(r.get("emoji"), 4) or "🗣️",
            "text": _pulse_txt(r.get("text"), 320),
            "comment": _pulse_txt(r.get("comment"), 60),
            "time": now,
        })
    vd = data.get("visitor") if isinstance(data.get("visitor"), dict) else {}
    vname = _pulse_txt(vd.get("name"), 12)
    vlines = [str(l).strip()[:60] for l in (vd.get("lines") or []) if str(l).strip()][:4]
    color = _pulse_txt(vd.get("color"), 7)
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#f59e0b"
    visitor = None
    if vname and vlines:
        visitor = {
            "id": "pv_" + uuid.uuid4().hex[:8],
            "name": vname,
            "emoji": _pulse_txt(vd.get("emoji"), 4) or "🧳",
            "color": color,
            "lines": vlines,
            "x": random.randint(38, 122), "y": random.randint(40, 106),
            "expire_day": day + random.randint(1, 3),
            "time": now,
        }
    return {"event": event, "rumors": rumors, "visitor": visitor}


PULSE_DIAG_DIR = BASE_DIR / ".cache" / "pulse_diag"


def _pulse_balance_json(text: str) -> str | None:
    """从 text 中按花括号配对截取第一个完整 JSON 对象。

    比 `\\{.*\\}` 贪婪正则更稳：能容忍 JSON 后有额外文字、多个 JSON 块、
    或字符串里包含 `}` 字符。失败返回 None。
    """
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _pulse_clean_json(text: str) -> str:
    """清理 LLM 输出里常见的非标 JSON 杂质：尾随逗号、``` 代码壳残余。"""
    t = text.strip()
    # 剥代码壳（保险起见，正则没匹配到 ``` 时也不会破坏内容）
    t = _strip_code_fence(t)
    # 去尾随逗号（}, ] 前的逗号）
    t = re.sub(r",\s*([}\]])", r"\1", t)
    return t


def _extract_pulse_json(text: str) -> dict | None:
    """从 LLM 回复中提取城市脉搏 JSON。

    依次尝试：剥代码壳整体 loads → 贪婪花括号截取 → 平衡花括号截取 →
    清理尾随逗号后重试。全部失败时把原始文本落盘到 .cache/pulse_diag/
    便于排查，避免无声失败。
    """
    if not text:
        return None
    candidates: list[str] = []
    stripped = _strip_code_fence(text)
    if stripped and stripped != text:
        candidates.append(stripped)
    greedy = re.search(r"\{.*\}", text, re.S)
    if greedy and greedy.group(0) not in candidates:
        candidates.append(greedy.group(0))
    balanced = _pulse_balance_json(text)
    if balanced and balanced not in candidates:
        candidates.append(balanced)

    for cand in candidates:
        # 先原样试
        try:
            data = json.loads(cand)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, ValueError):
            pass
        # 清理后再试
        cleaned = _pulse_clean_json(cand)
        if cleaned != cand:
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    return data
            except (json.JSONDecodeError, ValueError):
                pass

    # 全部失败：落盘原始内容，便于排查
    try:
        PULSE_DIAG_DIR.mkdir(parents=True, exist_ok=True)
        diag_file = PULSE_DIAG_DIR / f"pulse_raw_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.txt"
        diag_file.write_text(
            f"=== length: {len(text)} ===\n{text}\n",
            encoding="utf-8",
        )
    except Exception:
        pass
    return None


@app.get("/api/world/pulse")
async def world_pulse_get(day: int = 0):
    """城市动态列表（前端带当前游戏日，顺带做过期清理）。"""
    pulse = _load_world_pulse()
    try:
        day = max(1, int(day))
    except (TypeError, ValueError):
        day = 1
    if _gc_world_pulse(pulse, day):
        _save_world_pulse(pulse)
    vitality = int(pulse.get("vitality") or 0)
    return {
        "events": [e for e in reversed(pulse["events"]) if e.get("status") == "active"],
        "rumors": list(reversed(pulse["rumors"])),
        "visitors": list(reversed(pulse["visitors"])),
        "vitality": vitality,
        "vitality_level": _pulse_vitality_level(vitality),
        "gen_count": int(pulse.get("gen_count") or 0),
        "cooldown_left": max(0, int(WORLD_PULSE_GEN_COOLDOWN - (_time.time() - float(pulse.get("last_gen_ts") or 0)))),
    }


@app.post("/api/world/pulse/generate")
async def world_pulse_generate(req: Request):
    """让城市生长：LLM 依据世界状态生成 事件+传闻+来客（可选同步生成一个新地点含配图）。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)

    try:
        day = max(1, int(data.get("day") or 1))
    except (TypeError, ValueError):
        day = 1
    try:
        hour = max(0, min(23, int(data.get("hour") or 8)))
    except (TypeError, ValueError):
        hour = 8
    weather = str(data.get("weather") or "clear")[:12]
    weather_name = {
        "clear": "晴", "cloudy": "多云", "rain": "小雨", "storm": "雷暴",
        "fog": "浓雾", "snow": "降雪", "starry": "星夜",
    }.get(weather, "晴")
    try:
        main_stage = max(0, min(6, int(data.get("main_stage") or 0)))
    except (TypeError, ValueError):
        main_stage = 0
    places = [str(p)[:20] for p in (data.get("places") or []) if p][:10]
    last_titles = [str(t)[:20] for t in (data.get("last_titles") or []) if t][:6]
    seed = str(data.get("seed") or "").strip()[:40]
    with_place = bool(data.get("with_place"))

    pulse = _load_world_pulse()
    cooldown_left = int(WORLD_PULSE_GEN_COOLDOWN - (_time.time() - float(pulse.get("last_gen_ts") or 0)))
    if cooldown_left > 0:
        return JSONResponse(
            {"error": f"城市正在生长中，{cooldown_left} 秒后再来～", "retry_after": cooldown_left},
            status_code=429,
        )
    vitality = int(pulse.get("vitality") or 0)

    user_text = (
        f"世界状态：第 {day} 天 · {hour:02d}:00 · 天气「{weather_name}」 · 主线进度 {main_stage}/6\n"
        f"城市活力：{vitality}/100（{_pulse_vitality_level(vitality)}）\n"
        f"城中已有的自定义地点：{'、'.join(places) if places else '（暂无）'}\n"
        f"近期已出现过的事件（避免题材与类型重复）：{'、'.join(last_titles) if last_titles else '（无）'}\n"
        f"玩家灵感：{seed or '（无，请自由发挥）'}\n"
        "请按系统要求输出 JSON。"
    )
    system_prompt = WORLD_PULSE_PROMPT + (WORLD_PULSE_PLACE_PROMPT if with_place else "")

    async def _work():
        try:
            content = await _call_llm(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
                max_tokens=3200,
            )
        except Exception as e:
            raise GenJobError(f"城市脉搏生成失败：{e}")

        parsed = _extract_pulse_json(content)
        if not parsed:
            raise GenJobError("城市脉搏构思失败，请重试")

        payload = _norm_pulse_payload(parsed, day, vitality)

        # 可选：同步生成一个新地点（LLM 出简介+绘图提示词 → 生图 → 落入自定义地点库）
        place = None
        idea = parsed.get("place_idea") if isinstance(parsed.get("place_idea"), dict) else None
        if with_place and idea and _pulse_txt(idea.get("name"), 20):
            style = idea.get("style") if idea.get("style") in WORLD_PLACE_STYLES else random.choice(
                [k for k in WORLD_PLACE_STYLES if k != "free"]
            )
            style_meta = WORLD_PLACE_STYLES[style]
            kind = "mark" if idea.get("kind") == "mark" else "build"
            img_url = await _openai_generate_image(
                _pulse_txt(idea.get("image_prompt"), 600) + ", " + style_meta["prompt"],
                WORLD_PLACES_DIR, "/static/world_places", "cp_" + uuid.uuid4().hex[:10],
                IMG2IMG_SIZES.get("landscape", "1024x1024"),
                has_character=False,
            )
            px = random.randint(24, 128)
            py = random.randint(24, 124)
            place = {
                "id": "cp_" + uuid.uuid4().hex[:10],
                "name": _pulse_txt(idea.get("name"), 20),
                "desc": _pulse_txt(idea.get("desc"), 120),
                "icon": _pulse_txt(idea.get("icon"), 4) or "📍",
                "kind": kind,
                "style": style,
                "style_name": style_meta["name"],
                "x": px, "y": py,
                "w": 2 if kind == "build" else 1,
                "h": 2 if kind == "build" else 1,
                "img": img_url,
                "prompt": _pulse_txt(idea.get("image_prompt"), 600),
                "comment": _pulse_txt(idea.get("comment"), 90),
                "time": datetime.now().strftime("%m-%d %H:%M"),
                "pulse": True,
            }
            wplaces = _load_world_places()
            wplaces.append(place)
            _save_world_places(wplaces[-80:])

        # 落库
        _gc_world_pulse(pulse, day)
        pulse["events"].append(payload["event"])
        pulse["rumors"].extend(payload["rumors"])
        if payload["visitor"]:
            pulse["visitors"].append(payload["visitor"])
        pulse["last_gen_ts"] = _time.time()
        pulse["gen_count"] = int(pulse.get("gen_count") or 0) + 1
        _add_pulse_vitality(pulse, 2)
        _save_world_pulse(pulse)

        info = _add_affinity("world_pulse", f"城市脉搏 · {payload['event']['title']}")
        return {
            "event": payload["event"],
            "rumors": payload["rumors"],
            "visitor": payload["visitor"],
            "place": place,
            "affinity": info,
            "vitality": int(pulse.get("vitality") or 0),
            "vitality_level": _pulse_vitality_level(int(pulse.get("vitality") or 0)),
        }

    if data.get("bg"):
        job = await submit_gen_job("pulse", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


@app.post("/api/world/pulse/event/{ev_id}/done")
async def world_pulse_event_done(ev_id: str):
    """标记事件为已参与；参与让城市更有活力。"""
    pulse = _load_world_pulse()
    for e in pulse["events"]:
        if e.get("id") == ev_id:
            if e.get("status") != "done":
                e["status"] = "done"
                _add_pulse_vitality(pulse, 6)
                _save_world_pulse(pulse)
            info = _add_affinity("world_event", f"参与事件 · {e.get('title', '')}")
            return {"ok": True, "affinity": info, "vitality": int(pulse.get("vitality") or 0),
                    "vitality_level": _pulse_vitality_level(int(pulse.get("vitality") or 0))}
    return JSONResponse({"error": "事件不存在"}, status_code=404)


WORLD_PULSE_IMG_DIR = RolePath("static", "world_pulse_img")


@app.post("/api/world/pulse/event/{ev_id}/image")
async def world_pulse_event_image(ev_id: str, bg: bool = False):
    """为一条城市事件生成场景配图（按需，落盘并回写到事件记录）。"""
    async def _work():
        pulse = _load_world_pulse()
        ev = next((e for e in pulse["events"] if e.get("id") == ev_id), None)
        if not ev:
            raise GenJobError("事件不存在", status=404)
        material = (
            f"【城市事件 · {ev.get('emoji', '')} {ev.get('title', '')}】\n"
            f"类型：{ev.get('type_name', '')}\n"
            f"图鉴简介：{ev.get('desc', '')}\n"
            f"微故事：{ev.get('story', '')}\n"
            f"许墨短评：{ev.get('comment', '')}"
        )
        img_url, img_prompt = await _llm_image_for_text(
            material, WORLD_PULSE_IMG_DIR, "/static/world_pulse_img", f"ev_{ev_id}",
            IMG2IMG_SIZES.get("landscape", "1024x1024"), with_xumo=False,
        )
        if not img_url:
            raise GenJobError("配图生成失败，请重试")
        ev["image"] = img_url
        ev["image_prompt"] = img_prompt
        ev["image_time"] = datetime.now().strftime("%m-%d %H:%M")
        _save_world_pulse(pulse)
        return {"image": img_url + f"?t={int(_time.time())}", "affinity": None}

    if bg:
        job = await submit_gen_job("pulse", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


WORLD_PULSE_VERIFY_PROMPT = """你是《恋与制作人》开放世界「恋语市」中的许墨（Lucien）——恋语大学教授，语气温和含笑、爱用学术比喻，象征色紫色、象征物蝴蝶。
玩家把一条城中传闻带给你求证。请以许墨的身份给出一段"求证报告"：先温和地接下这件事，再像做研究一样条理清晰地讲述你如何查证、结果如何，最后给传闻一个结论。

【传闻】
标题：{title}
内容：{text}

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{{
  "verdict": "true|false|unknown 之一（true=属实，false=讹传，unknown=存疑）",
  "report": "许墨的求证报告，120-220字，第一人称，温和含笑，有查证过程和细节，可带学术梗或蝴蝶意象",
  "comment": "一句收尾的短评，12-30字"
}}"""


@app.post("/api/world/pulse/rumor/{rumor_id}/verify")
async def world_pulse_rumor_verify(rumor_id: str):
    """请许墨帮忙求证一条传闻（LLM 生成求证报告与结论）。"""
    pulse = _load_world_pulse()
    rumor = next((r for r in pulse["rumors"] if r.get("id") == rumor_id), None)
    if not rumor:
        return JSONResponse({"error": "传闻不存在"}, status_code=404)
    if rumor.get("verify"):
        return {"ok": True, "already": True, "verify": rumor["verify"],
                "vitality": int(pulse.get("vitality") or 0)}

    system_prompt = WORLD_PULSE_VERIFY_PROMPT.format(
        title=rumor.get("title", ""), text=rumor.get("text", ""),
    )
    try:
        content = await _call_llm(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": "许墨，这条传闻是真的吗？"}],
            max_tokens=900,
        )
    except Exception as e:
        return JSONResponse({"error": f"求证失败：{e}"}, status_code=500)

    parsed = _extract_pulse_json(content)
    verdict = "unknown"
    if parsed and parsed.get("verdict") in ("true", "false", "unknown"):
        verdict = parsed["verdict"]
    report = _pulse_txt(parsed.get("report"), 300) if parsed else ""
    if not report:
        report = "我托了系里的朋友打听了一圈——线索到这里就断了。这条传闻，暂时只能存疑。"
    verify = {
        "verdict": verdict,
        "verdict_name": {"true": "属实", "false": "讹传", "unknown": "存疑"}[verdict],
        "report": report,
        "comment": _pulse_txt(parsed.get("comment"), 60) if parsed else "",
        "time": datetime.now().strftime("%m-%d %H:%M"),
    }
    rumor["verify"] = verify
    _add_pulse_vitality(pulse, 2)
    _save_world_pulse(pulse)
    info = _add_affinity("world_pulse", f"求证传闻 · {rumor.get('title', '')}")
    return {"ok": True, "verify": verify, "affinity": info,
            "vitality": int(pulse.get("vitality") or 0),
            "vitality_level": _pulse_vitality_level(int(pulse.get("vitality") or 0))}


WORLD_PULSE_GIFT_TEXTS = [
    "{name}接过礼物，眼睛一下子亮了：「这座城的人情味，比我想的还要暖。」",
    "{name}小心地把礼物收进行囊：「谢谢你。旅途很长，这样的心意最经得起惦记。」",
    "{name}愣了一下，随即笑着道谢：「在恋语市遇到的善意，我会一路带去下一座城。」",
    "{name}郑重地和你道别：「礼物我收下了，故事也讲给你听了——我们算朋友了。」",
]


@app.post("/api/world/pulse/visitor/{visitor_id}/gift")
async def world_pulse_visitor_gift(visitor_id: str):
    """送给限时来客一件小礼物，TA 会回赠谢礼（每位来客一次）。"""
    pulse = _load_world_pulse()
    visitor = next((v for v in pulse["visitors"] if v.get("id") == visitor_id), None)
    if not visitor:
        return JSONResponse({"error": "来客已离开这座城市"}, status_code=404)
    if visitor.get("gifted"):
        return JSONResponse({"error": "礼物已经送过啦，TA 记着你的好"}, status_code=429)

    roll = random.random()
    if roll < 0.40:
        gift = {"money": random.randint(15, 40)}
    elif roll < 0.85:
        gift = {"item": random.choice(WORLD_PULSE_ITEMS), "qty": random.randint(1, 2)}
    else:
        gift = {"money": random.randint(25, 55), "item": random.choice(WORLD_PULSE_ITEMS), "qty": 1}
    text = random.choice(WORLD_PULSE_GIFT_TEXTS).format(name=visitor.get("name", "来客"))
    visitor["gifted"] = 1
    _add_pulse_vitality(pulse, 2)
    _save_world_pulse(pulse)
    info = _add_affinity("world_pulse", f"赠礼来客 · {visitor.get('name', '')}")
    return {"ok": True, "gift": gift, "text": text, "affinity": info,
            "vitality": int(pulse.get("vitality") or 0),
            "vitality_level": _pulse_vitality_level(int(pulse.get("vitality") or 0))}


@app.delete("/api/world/pulse/{kind}/{item_id}")
async def world_pulse_delete(kind: str, item_id: str):
    """手动清理某条动态（events / rumors / visitors）。"""
    pulse = _load_world_pulse()
    key = {"events": "events", "rumors": "rumors", "visitors": "visitors"}.get(kind)
    if not key:
        return JSONResponse({"error": "未知类型"}, status_code=400)
    kept = [x for x in pulse[key] if x.get("id") != item_id]
    if len(kept) == len(pulse[key]):
        return JSONResponse({"error": "条目不存在"}, status_code=404)
    pulse[key] = kept
    _save_world_pulse(pulse)
    return {"ok": True}


# ================= 世界·恋语市：编年史（世界记录 · 许墨的记忆） =================
WORLD_LOG_FILE = RolePath("world_log.json")
WORLD_LOG_MAX = 1500          # 编年史条目上限（超出淘汰最早）
WORLD_LOG_BATCH = 40          # 单次上报上限
WORLD_MEMORY_TTL = 600        # 许墨记忆缓存秒数
_world_log_lock = asyncio.Lock()

WORLD_LOG_TYPES = {
    "day", "weather", "talk", "gather", "chest", "photo", "shard", "page",
    "puzzle", "battle", "quest", "build", "npc", "place", "pulse", "rumor",
    "gift", "rest", "other",
}

# 里程碑类型：主线推进 / 解谜 / 战斗 / 结局等会被特别高亮，并在记忆生成时作为锚点
WORLD_LOG_MILESTONE_TYPES = {"quest", "battle", "puzzle", "shard", "ending"}
WORLD_LOG_MILESTONE_KEYWORDS = (
    "结局", "主线推进", "解开了", "登顶", "取得「回声核心」", "集齐", "第 1 天",
)

# 时段划分（按游戏内分钟 0-1439）
WORLD_LOG_TOD_RANGES = [
    ("dawn",     0,   300, "🌅", "黎明"),     # 00:00-05:00
    ("morning",  300, 720, "🌄", "上午"),     # 05:00-12:00
    ("noon",     720, 900, "☀️", "正午"),     # 12:00-15:00
    ("afternoon",900, 1140,"🌇", "下午"),     # 15:00-19:00
    ("evening",  1140,1320,"🌆", "黄昏"),     # 19:00-22:00
    ("night",    1320,1440,"🌙", "夜晚"),     # 22:00-24:00
]

WORLD_MEMORY_STYLES = {
    "gentle":   ("温柔回顾", "像许墨自然地聊起两人的过往，带一点观察、调侃或小小的约定"),
    "poetic":   ("诗意小品", "用诗意的笔触写一段短小隽永的回忆，可以有比喻和意象，但不要矫情"),
    "narrative":("故事叙述", "像在讲一个发生过的故事，有时间线、有起承转合，但仍是许墨的口吻"),
}


def _load_world_log() -> dict:
    if WORLD_LOG_FILE.exists():
        try:
            data = json.loads(WORLD_LOG_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                # 旧数据兼容：补 id / star / milestone 字段
                # id 用 ts+day+time+type+text 的 sha1 前 12 位（确定性，无需落盘也能稳定）
                needs_save = False
                for e in data["entries"]:
                    if not isinstance(e, dict):
                        continue
                    if not e.get("id"):
                        raw = f"{e.get('ts','')}|{e.get('day','')}|{e.get('time','')}|{e.get('type','')}|{str(e.get('text',''))[:80]}"
                        e["id"] = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
                        needs_save = True
                    if "star" not in e:
                        e["star"] = 0
                        needs_save = True
                    if "milestone" not in e:
                        e["milestone"] = _world_log_is_milestone(e)
                        needs_save = True
                # 旧数据就地升级一次（持久化，下次直接命中）
                if needs_save:
                    try:
                        _save_world_log(data)
                    except OSError:
                        pass
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {"entries": [], "memory": None}


def _save_world_log(data: dict):
    """原子写：先写 .tmp 再 rename，避免并发请求半截写入损坏 JSON。"""
    payload = json.dumps(data, ensure_ascii=False)
    # RolePath 不支持 with_suffix，直接拼字符串路径
    target = Path(str(WORLD_LOG_FILE))
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(target)


def _world_log_is_milestone(e: dict) -> int:
    typ = e.get("type", "")
    text = str(e.get("text") or "")
    if typ in WORLD_LOG_MILESTONE_TYPES:
        return 1
    if any(kw in text for kw in WORLD_LOG_MILESTONE_KEYWORDS):
        return 1
    return 0


def _world_log_tod(tmin: int) -> str:
    """根据游戏内分钟返回时段 key。"""
    try:
        t = int(tmin)
    except (TypeError, ValueError):
        t = 0
    for key, lo, hi, _icon, _label in WORLD_LOG_TOD_RANGES:
        if lo <= t < hi:
            return key
    return "night"


def _world_log_dedup_key(e: dict) -> str:
    """同日同时分同类型同文本视为重复（beacon 重试兜底）。"""
    return f"{e.get('day','?')}|{e.get('time','?')}|{e.get('type','?')}|{str(e.get('text',''))[:80]}"


@app.get("/api/world/log")
async def world_log_list(
    limit: int = 400, type: str = "", day: int = 0,
    q: str = "", page: int = 0, page_size: int = 0,
    order: str = "desc", star: int = 0, milestone: int = 0,
):
    """世界编年史：entries 新→旧（可切换）；附带覆盖天数 / 类型分布 / 时段分布 / 活跃度统计。

    - q:        关键词模糊匹配（不区分大小写）
    - page:     0 = 不分页返回 limit 条；>=1 时按 page_size 分页
    - page_size:分页大小（1-200），仅当 page>=1 生效
    - order:    desc=新→旧（默认），asc=旧→新
    - star:     1 = 仅看收藏
    - milestone:1 = 仅看里程碑
    """
    wl = _load_world_log()
    all_entries = wl["entries"]
    # 过滤
    filtered = all_entries
    if type:
        filtered = [e for e in filtered if e.get("type") == type]
    if day:
        filtered = [e for e in filtered if e.get("day") == day]
    if star:
        filtered = [e for e in filtered if e.get("star")]
    if milestone:
        filtered = [e for e in filtered if e.get("milestone")]
    if q:
        ql = q.strip().lower()
        if ql:
            filtered = [e for e in filtered if ql in str(e.get("text", "")).lower()]
    total = len(filtered)
    # 排序：保持旧→新为基准
    ordered = list(filtered)
    shown = list(reversed(ordered)) if order == "desc" else ordered
    # 分页
    if page >= 1 and page_size > 0:
        ps = max(1, min(200, page_size))
        start = (page - 1) * ps
        shown = shown[start:start + ps]
        has_more = (start + ps) < total
    else:
        shown = shown[:max(1, min(limit, 800))]
        has_more = len(shown) < total
    # 统计（始终基于全量，不受过滤影响）
    days = sorted({e.get("day", 1) for e in all_entries}, reverse=True)
    types = {}
    tod = {k: 0 for k, *_ in WORLD_LOG_TOD_RANGES}
    milestone_count = 0
    star_count = 0
    for e in all_entries:
        k = e.get("type", "other")
        types[k] = types.get(k, 0) + 1
        tod[_world_log_tod(e.get("time", 0))] += 1
        if e.get("milestone"):
            milestone_count += 1
        if e.get("star"):
            star_count += 1
    # 活跃度：按天聚合最近 7 天的条目数
    recent_days = days[:7] if days else []
    activity = {}
    for d in recent_days:
        activity[d] = sum(1 for e in all_entries if e.get("day") == d)
    return {
        "entries": shown, "count": total, "total_all": len(all_entries),
        "days": days, "types": types, "tod": tod,
        "milestone_count": milestone_count, "star_count": star_count,
        "activity": activity, "has_more": has_more,
        "first_day": days[-1] if days else 0, "last_day": days[0] if days else 0,
    }


@app.post("/api/world/log")
async def world_log_append(req: Request):
    """批量追加世界记录（前端节流上报，弹窗关闭/页面隐藏时 beacon 兜底）。

    - 同批内及与近期记录去重（避免 beacon 重试导致重复）
    - 自动写入 id / milestone 字段
    """
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    items = data.get("entries")
    if not isinstance(items, list) or not items:
        return JSONResponse({"error": "缺少 entries"}, status_code=400)
    items = items[:WORLD_LOG_BATCH]
    async with _world_log_lock:
        wl = _load_world_log()
        now = _time.time()
        # 近期去重窗口：最近 60 条的 key
        existing_keys = {_world_log_dedup_key(e) for e in wl["entries"][-60:]}
        batch_keys = set()
        added = 0
        for it in items:
            if not isinstance(it, dict):
                continue
            text = str(it.get("text") or "").strip()
            if not text:
                continue
            typ = it.get("type") if it.get("type") in WORLD_LOG_TYPES else "other"
            try:
                day = max(1, int(it.get("day") or 1))
                tmin = max(0, min(1439, int(it.get("time") or 0)))
            except (TypeError, ValueError):
                day, tmin = 1, 0
            rec = {
                "id": uuid.uuid4().hex[:12],
                "ts": round(now, 3),
                "day": day, "time": tmin, "type": typ,
                "text": text[:120], "star": 0,
            }
            for k in ("x", "y"):
                v = it.get(k)
                if isinstance(v, (int, float)):
                    rec[k] = int(v)
            rec["milestone"] = _world_log_is_milestone(rec)
            k = _world_log_dedup_key(rec)
            if k in existing_keys or k in batch_keys:
                continue
            batch_keys.add(k)
            wl["entries"].append(rec)
            added += 1
        while len(wl["entries"]) > WORLD_LOG_MAX:
            wl["entries"].pop(0)
        _save_world_log(wl)
    return {"ok": True, "count": len(wl["entries"]), "added": added}


@app.patch("/api/world/log/{entry_id}")
async def world_log_patch(entry_id: str, req: Request):
    """更新单条记录：star（收藏/取消）, text（编辑文字）。"""
    try:
        data = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    async with _world_log_lock:
        wl = _load_world_log()
        target = None
        for e in wl["entries"]:
            if e.get("id") == entry_id:
                target = e
                break
        if target is None:
            return JSONResponse({"error": "条目不存在"}, status_code=404)
        if "star" in data:
            try:
                target["star"] = 1 if int(data["star"]) else 0
            except (TypeError, ValueError):
                pass
        if isinstance(data.get("text"), str):
            t = data["text"].strip()
            if t:
                target["text"] = t[:120]
        _save_world_log(wl)
    return {"ok": True, "entry": target}


@app.delete("/api/world/log/{entry_id}")
async def world_log_delete_one(entry_id: str):
    """删除单条记录（不影响其它）。"""
    async with _world_log_lock:
        wl = _load_world_log()
        before = len(wl["entries"])
        wl["entries"] = [e for e in wl["entries"] if e.get("id") != entry_id]
        if len(wl["entries"]) == before:
            return JSONResponse({"error": "条目不存在"}, status_code=404)
        _save_world_log(wl)
    return {"ok": True, "count": len(wl["entries"])}


@app.delete("/api/world/log")
async def world_log_clear():
    """清空编年史（许墨的记忆缓存一并清空）。"""
    async with _world_log_lock:
        _save_world_log({"entries": [], "memory": None})
    return {"ok": True}


@app.get("/api/world/log/export")
async def world_log_export(format: str = "txt"):
    """导出编年史为 txt / json，按天分组、时间正序。"""
    wl = _load_world_log()
    entries = wl["entries"]
    if format == "json":
        body = json.dumps({"entries": entries}, ensure_ascii=False, indent=2)
        return Response(
            content=body,
            media_type="application/json; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="world_log.json"'},
        )
    # txt：按天分组
    lines = ["# 恋语市 · 世界编年史", f"# 导出于 {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    by_day = {}
    for e in entries:
        by_day.setdefault(e.get("day", 1), []).append(e)
    for d in sorted(by_day.keys()):
        lines.append(f"==== 第 {d} 天 ====")
        for e in sorted(by_day[d], key=lambda x: x.get("time", 0)):
            hh, mm = divmod(int(e.get("time", 0)), 60)
            star = "★ " if e.get("star") else ""
            ms = "  ⭐里程碑" if e.get("milestone") else ""
            lines.append(f"{hh:02d}:{mm:02d}  {star}{e.get('text','')}{ms}")
        lines.append("")
    body = "\n".join(lines).encode("utf-8")
    return Response(
        content=body,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="world_log.txt"'},
    )


WORLD_MEMORY_STYLE_HINTS = WORLD_MEMORY_STYLES  # 别名：便于前端反查


@app.get("/api/world/memory/styles")
async def world_memory_styles():
    """前端查询可用的记忆风格。"""
    return {"styles": [{"key": k, "label": v[0], "hint": v[1]} for k, v in WORLD_MEMORY_STYLES.items()]}


@app.get("/api/world/memory")
async def world_memory(refresh: int = 0, style: str = "gentle"):
    """许墨的世界记忆：依据编年史由 LLM 生成，10 分钟内走缓存。

    - style: gentle(温柔回顾) / poetic(诗意小品) / narrative(故事叙述)
    """
    style = style if style in WORLD_MEMORY_STYLES else "gentle"
    wl = _load_world_log()
    mem = wl.get("memory")
    now = _time.time()
    # 缓存命中需 style 一致
    if (not refresh and isinstance(mem, dict) and mem.get("text")
            and mem.get("style") == style
            and now - mem.get("ts", 0) < WORLD_MEMORY_TTL):
        return {"text": mem["text"], "time": mem["ts"], "cached": True,
                "style": style, "log_count": len(wl["entries"])}
    entries = wl["entries"][-140:]
    if not entries:
        return {"text": "", "log_count": 0, "style": style}
    # 里程碑锚点：优先呈现给 LLM
    milestones = [e for e in entries if e.get("milestone")]
    milestones_tail = milestones[-8:]
    lines = []
    for e in entries:
        hh, mm = divmod(int(e.get("time", 0)), 60)
        flag = " ⭐" if e.get("milestone") else ""
        star = " ★" if e.get("star") else ""
        lines.append(f"第{e.get('day', 1)}天 {hh:02d}:{mm:02d}{flag}{star} {e.get('text', '')}")
    try:
        vitality = _load_world_pulse().get("vitality", 20)
    except Exception:
        vitality = 20
    style_label, style_hint = WORLD_MEMORY_STYLES[style]
    user = (
        f"【记忆风格】{style_label}：{style_hint}\n"
        f"【编年史（旧→新，共 {len(entries)} 条，其中里程碑 {len(milestones)} 条）】\n"
        + "\n".join(lines)
        + f"\n\n当前城市活力：{vitality}/100"
        + (f"\n近期里程碑：{'；'.join(e.get('text','') for e in milestones_tail)}" if milestones_tail else "")
    )
    sys_prompt = SYSTEM_PROMPT + f"""

【任务】你在「世界·恋语市」里陪着 TA 生活。下面是这个世界近期的编年史（流水记录，旧→新）。
请以许墨的身份，把这段共同经历写成一段「世界记忆」（150~220 字）：
- 回忆具体的细节：谁、在哪、发生了什么、天气如何，不要空泛抒情
- ⭐ 标记的是里程碑事件（主线推进 / 解谜 / 战斗 / 结局等），请在记忆里自然地带到这些节点
- ★ 标记的是 TA 主动收藏的瞬间，多半是 TA 在意的小事，记得轻轻提一笔
- 风格要求：{style_label} —— {style_hint}
- 直接输出正文，不要标题、不要引号、不要 markdown
"""
    try:
        text = (await _call_llm([
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user},
        ], max_tokens=500)).strip()
    except Exception as exc:
        return JSONResponse({"error": f"记忆生成失败：{str(exc)[:120]}"}, status_code=500)
    if not text:
        return JSONResponse({"error": "记忆生成失败，请稍后再试"}, status_code=500)
    wl["memory"] = {"text": text, "ts": now, "style": style}
    _save_world_log(wl)
    return {"text": text, "time": now, "cached": False,
            "style": style, "log_count": len(wl["entries"]),
            "milestone_count": len(milestones)}


# 四大学习功能路由（features.py）
from features import router as features_router  # noqa: E402

app.include_router(features_router)

# 六大创意手机 App 路由（creative_apps.py）：清梦/心智图谱/蝶语花园/平行宇宙/天台观星/黑天鹅档案
from creative_apps import router as creative_router  # noqa: E402

app.include_router(creative_router)

# 三大生活类手机 App 路由（life_apps.py）：衣橱换装 / 工作助手 / 恋爱日记
from life_apps import router as life_router  # noqa: E402

app.include_router(life_router)

# 手谈 · 围棋对弈路由（go_game.py）：规则引擎 + 许墨 AI + 台词
from go_game import router as go_router  # noqa: E402

app.include_router(go_router)

# 大富翁游戏路由（monopoly_game.py）：完整规则引擎 + 许墨台词 + 3D世界集成
from monopoly_game import router as monopoly_router  # noqa: E402

app.include_router(monopoly_router)

# 八大口袋新功能路由（pocket_apps.py）：电台 / B3实验室 / 宠物 / 来信 / 许愿池 / 占卜 / 闪念 / 剪贴板
from pocket_apps import router as pocket_router  # noqa: E402

app.include_router(pocket_router)

# 颠覆性功能集路由（extra_apps.py）：承诺管家 / 睡眠守护+晨间播报 / 剪贴板接话 / 许墨每日日记
from extra_apps import router as extra_router  # noqa: E402

app.include_router(extra_router)

# 时光总结路由（summary_apps.py）：今日总结 / 周结 / 月结 / 年结 —— 我和许墨的点点滴滴
from summary_apps import router as summary_router  # noqa: E402

app.include_router(summary_router)

# 奇想功能集路由（wonder_apps.py）：决策预言家 / 默契测验 / 每日悬疑事件簿 / 反向扮演剧场 / 关系年度报告 / 习惯养成管家 / 晚间语音回顾 / 记忆博物馆
from wonder_apps import router as wonder_router  # noqa: E402

app.include_router(wonder_router)

# 深度互动功能集路由（deep_apps.py）：观察手记 / 共梦联机 / 平行世界if线 / 记忆碎片修复 / 反向教学课堂 / 情绪天气联动 / 共同习惯 / 危急时刻演练室 / 声音信箱 / 合著的书
from deep_apps import router as deep_router  # noqa: E402

app.include_router(deep_router)

# 心灵互动功能集路由（psyche_apps.py）—— 深度共鸣十域：
# 情绪共振日记 / 人格实验室 / 深夜来电模式 / 案件共研室 / 记忆标本馆
# 观察者挑战 / 平行世界通讯 / 梦境解析互动 / 关系温度计 / 共同创作实验
from psyche_apps import router as psyche_router  # noqa: E402

app.include_router(psyche_router)

# 新星功能集路由（nova_apps.py）：时空热线 / 双我辩论 / 合影日历 / 心动成就 / 情绪急救箱 / 人生模拟器
from nova_apps import router as nova_router  # noqa: E402

app.include_router(nova_router)

# 新星功能集四期路由（nova_apps2.py）：梦境解码器 / 平行信箱 / 深夜电台 / 默契雷达 / 命运岔路 / 心跳频谱
from nova_apps2 import router as nova2_router  # noqa: E402

app.include_router(nova2_router)

# 新星功能集五期路由（nova_apps3.py）：潜意识密室 / 时空胶囊 / 共感温度计 / 七日预言 / 沉默信使 / 心跳调音台
from nova_apps3 import router as nova3_router  # noqa: E402

app.include_router(nova3_router)

# 六大互动养成功能路由（story_apps.py）：互动剧情副本 / 工作经济 / 特质养成 /
# 定制晚安故事 / 树洞模式 / 节日事件引擎
from story_apps import router as story_router  # noqa: E402

app.include_router(story_router)

# 许墨云资料库路由（xumocloud_apps.py）：把 xumocloud.com 公开数据爬下来，
# 分发到现有 app（语录/衣橱/合影日历/黑天鹅档案/浏览器搜索）
from xumocloud_apps import router as xcloud_router  # noqa: E402

app.include_router(xcloud_router)

# 二十项颠覆性功能路由（disrupt_apps.py）：
# 原十大：逆向时光机 / 人格融合实验室 / 潜意识剧场 / 命运回声图谱 /
# 时光密室 / 心跳实验室 / 次元裂隙 / 命运赌局 / 回忆修复工坊 / 共生体演化
# 新增十项：梦境织机 / 情绪气象台 / 平行宇宙探测器 / 记忆拼图 / 心灵共鸣电台 /
# 时间胶囊花园 / 灵魂镜像室 / 命运编织者 / 情感化学反应 / 星际罗盘
from disrupt_apps import router as disrupt_router  # noqa: E402

app.include_router(disrupt_router)

# 六期颠覆性功能（nova_apps4.py）：亲密里程碑 / 吃醋实验室 / 记忆卡牌对决 / 合著专辑 / 云旅行
from nova_apps4 import router as nova4_router  # noqa: E402

app.include_router(nova4_router)

# 七期颠覆性功能（nova_apps5.py）：深夜食堂 / 镜像学习 / 挑战书 / 忏悔室 / 关系沙盒
from nova_apps5 import router as nova5_router  # noqa: E402

app.include_router(nova5_router)

# 八期颠覆性功能（nova_apps6.py）：最后一日 / 消失的七日 / 通感邮局 / 共犯系统 / 情绪交易所
from nova_apps6 import router as nova6_router  # noqa: E402

app.include_router(nova6_router)

# 九期颠覆性功能（nova_apps7.py）：雾区·遗忘 / 命运对弈 / 觉醒模式 / 许墨的梦 / 意识U盘
from nova_apps7 import router as nova7_router  # noqa: E402

app.include_router(nova7_router)

# AI 自定义扩展功能路由（extensions_apps.py）：
# 提示词模板 / 工具链集成 / 工作流编排 —— 可视化配置 + 启用/禁用 + 优先级管理 + 安全沙箱
from extensions_apps import router as extensions_router, build_prompt_injection  # noqa: E402

app.include_router(extensions_router)

# AI 对话式扩展构建器路由（ai_extension_builder.py）：
# 自然语言对话创建扩展 + 智能推荐 + 配置生成
from ai_extension_builder import router as ai_builder_router  # noqa: E402

app.include_router(ai_builder_router, prefix="/api/extensions")

# 应用市场功能路由（marketplace_apps.py）：
# 应用分类浏览、搜索筛选、评价评分、AI推荐系统
from marketplace_apps import router as marketplace_router  # noqa: E402

app.include_router(marketplace_router)

# 智能App构建器路由（smart_app_builder.py）：
# AI对话式创建、可视化配置、模板系统、代码生成
from smart_app_builder import router as smart_builder_router  # noqa: E402

app.include_router(smart_builder_router)

# AI视频功能路由（video_apps.py）：
# 成长记录时光机 / 记忆回放剧场 / 梦境可视化播放器 / 时空旅行日记 / 共同时刻相册 / 虚拟约会场景生成
from video_apps import router as video_router  # noqa: E402

app.include_router(video_router)


# ===========================================================================
# 自定义插件系统（plugin_core）：A 自动发现 / B 钩子 / C 沙箱 三合一
# ---------------------------------------------------------------------------
# 在所有内置路由注册完成后，加载 plugins/ 目录下的自定义插件。
#   - 方案 A：约定式自动发现 —— 暴露 router 即挂载到 /api/plugins/<name>
#   - 方案 B：钩子式        —— 实现 chat_reply / menu_items 等钩子改写行为
#   - 方案 C：沙箱子进程    —— 独立 HTTP 服务，主程序反向代理
# 沙箱插件在 lifespan 中异步启动；A/B 在此同步加载并注册路由。
# ===========================================================================
try:
    from plugin_core import (
        get_plugin_hub, register_all_plugins,
        start_sandbox_plugins, stop_sandbox_plugins,
        unload_all_plugins, get_hook_manager,
        PLUGIN_TYPE_AUTO, PLUGIN_TYPE_HOOK, PLUGIN_TYPE_SANDBOX,
    )
    _plugin_hub = get_plugin_hub()
    # 发现 + 加载所有插件（A/B 同步，C 仅登记 manifest，子进程在 lifespan 启动）
    _plugin_load_results = _plugin_hub.load_all_plugins()
    # 注册 A 的路由到 /api/plugins/<name>
    _plugin_reg_results = _plugin_hub.register_with_app(app, prefix="/api/plugins")
    print(f"[xumo] 插件系统已加载：{_plugin_load_results}", flush=True)
    print(f"[xumo] 插件路由已注册：{_plugin_reg_results}", flush=True)
except Exception as _plugin_err:
    _plugin_hub = None
    print(f"[xumo] 插件系统加载失败（已跳过）：{type(_plugin_err).__name__} {_plugin_err}", flush=True)


@app.get("/api/plugins")
async def plugins_inspect():
    """查看已加载的插件（A/B/C 三类）与已注册的钩子。"""
    if _plugin_hub is None:
        return {"enabled": False, "error": "插件系统未加载"}
    hub = _plugin_hub
    loaded = hub.get_loaded_plugins()
    out = {"enabled": True, "plugins": [], "hooks": []}
    for name, (ptype, contract) in loaded.items():
        item = {"name": name, "version": contract.version, "type": ptype}
        if ptype == PLUGIN_TYPE_SANDBOX:
            item["port"] = getattr(contract, "port", None)
            item["routes_prefix"] = getattr(contract, "routes_prefix", "")
        out["plugins"].append(item)
    try:
        _hook_mgr = get_hook_manager()
        for hn in _hook_mgr.list_hook_names():
            caller = _hook_mgr.get_hook(hn)
            n = len(caller._impls) if caller else 0
            if n:
                out["hooks"].append({"name": hn, "impls": n})
    except Exception:
        pass
    return out


# ---------------------------------------------------------------------------
# 时光盒 · 制造与许墨的专属回忆（纪念日 / 时光胶囊 / 回忆卡 / 约会企划）
# ---------------------------------------------------------------------------
TIMEBOX_FILE = RolePath("timebox.json")
_timebox_lock = asyncio.Lock()

TIMEBOX_CAPSULE_MAX = 40   # 胶囊上限
TIMEBOX_RELIC_MAX = 60     # 回忆卡上限
TIMEBOX_PLAN_MAX = 30      # 约会企划上限


def _load_timebox() -> dict:
    try:
        data = json.loads(TIMEBOX_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key in ("anniversaries", "capsules", "relics", "plans"):
        if not isinstance(data.get(key), list):
            data[key] = []
    return data


def _save_timebox(data: dict):
    atomic_json(TIMEBOX_FILE, data)


def _date_diff_days(date_str: str):
    """目标日期距今天数：正=未来，负=已过去，0=今天；非法返回 None。"""
    try:
        target = datetime.strptime((date_str or "")[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (target - datetime.now().date()).days


def _first_met_info() -> dict:
    """从聊天记录里找「初遇之日」。"""
    logs = _load_chat_log()
    first_ts = ""
    for item in logs:
        ts = item.get("ts") or ""
        if ts and (not first_ts or ts < first_ts):
            first_ts = ts
    if not first_ts:
        return {}
    days = _date_diff_days(first_ts[:10])
    if days is None:
        return {}
    return {"date": first_ts[:10], "days": -days}


def _capsule_view(c: dict) -> dict:
    """胶囊对外视图：未到期时隐去内容。"""
    days_left = _date_diff_days(c.get("open_date", ""))
    opened = bool(c.get("reply")) or (days_left is not None and days_left <= 0)
    return {
        "id": c.get("id"),
        "open_date": c.get("open_date"),
        "created": c.get("created"),
        "days_left": days_left,
        "opened": opened,
        "content": c.get("content", "") if opened else "",
        "reply": c.get("reply", "") if opened else "",
        "image": c.get("image", "") if opened else "",
    }


@app.get("/api/timebox")
async def timebox_get():
    data = _load_timebox()
    annivs = []
    for a in data["anniversaries"]:
        days = _date_diff_days(a.get("date", ""))
        annivs.append({**a, "days": days})
    # 越临近越靠前；已过的按最近排
    annivs.sort(key=lambda a: (
        a["days"] is None, abs(a["days"]) if a["days"] is not None else 0
    ))
    return {
        "anniversaries": annivs,
        "capsules": [_capsule_view(c) for c in reversed(data["capsules"])],
        "relics": list(reversed(data["relics"])),
        "plans": list(reversed(data["plans"])),
        "first_met": _first_met_info(),
    }


# --- 纪念日 ----------------------------------------------------------------

@app.post("/api/timebox/anniv")
async def timebox_anniv_add(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    name = (body.get("name") or "").strip()
    date = (body.get("date") or "").strip()[:10]
    icon = ((body.get("icon") or "").strip() or "💐")[:4]
    if not name:
        return JSONResponse({"error": "请填写纪念日名称"}, status_code=400)
    if len(name) > 20:
        return JSONResponse({"error": "名称不能超过 20 字"}, status_code=400)
    if _date_diff_days(date) is None:
        return JSONResponse({"error": "日期格式不正确"}, status_code=400)
    async with _timebox_lock:
        data = _load_timebox()
        if len(data["anniversaries"]) >= 40:
            return JSONResponse({"error": "纪念日最多 40 个"}, status_code=400)
        item = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "date": date,
            "icon": icon,
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        data["anniversaries"].append(item)
        _save_timebox(data)
    info = _add_affinity("anniversary", f"记下纪念日 · {name}")
    return {"item": item, "affinity": info}


@app.delete("/api/timebox/anniv/{item_id}")
async def timebox_anniv_delete(item_id: str):
    async with _timebox_lock:
        data = _load_timebox()
        kept = [a for a in data["anniversaries"] if a.get("id") != item_id]
        if len(kept) == len(data["anniversaries"]):
            return JSONResponse({"error": "纪念日不存在"}, status_code=404)
        data["anniversaries"] = kept
        _save_timebox(data)
    return {"ok": True}


# --- 时光胶囊 --------------------------------------------------------------

@app.post("/api/timebox/capsule")
async def timebox_capsule_add(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    content = (body.get("content") or "").strip()
    open_date = (body.get("open_date") or "").strip()[:10]
    if not content:
        return JSONResponse({"error": "胶囊内容不能为空"}, status_code=400)
    if len(content) > 500:
        return JSONResponse({"error": "胶囊内容最多 500 字"}, status_code=400)
    days = _date_diff_days(open_date)
    if days is None:
        return JSONResponse({"error": "开启日期格式不正确"}, status_code=400)
    if days < 0:
        return JSONResponse({"error": "开启日期不能早于今天"}, status_code=400)
    async with _timebox_lock:
        data = _load_timebox()
        if len(data["capsules"]) >= TIMEBOX_CAPSULE_MAX:
            return JSONResponse(
                {"error": f"胶囊最多 {TIMEBOX_CAPSULE_MAX} 枚，先开启或清理一些吧"},
                status_code=400,
            )
        item = {
            "id": uuid.uuid4().hex[:12],
            "content": content,
            "open_date": open_date,
            "created": datetime.now().strftime("%Y-%m-%d"),
            "reply": "",
        }
        data["capsules"].append(item)
        _save_timebox(data)
    info = _add_affinity("capsule", "封存一枚时光胶囊")
    return {"item": _capsule_view(item), "affinity": info}


CAPSULE_REPLY_PROMPT = SYSTEM_PROMPT + """

【当前任务】她在 {created} 写下一枚时光胶囊，约定 {open_date} 开启，今天正是开启的日子。
胶囊里她写道：
「{content}」

请以许墨的身份写一封回信（120~200 字）：
1. 像此刻才第一次读到这段话，自然回应里面的内容，带一点"跨越时间"的温柔与感慨；
2. 时光已过去 {gap} 天，可以巧妙提及这段间隔（如恰在同一天就不要提天数）；
3. 落款「—— 许墨」。只输出信的正文，不要 JSON、不要解释、不要标题。"""


@app.post("/api/timebox/capsule/{item_id}/open")
async def timebox_capsule_open(item_id: str):
    async with _timebox_lock:
        data = _load_timebox()
        cap = next((c for c in data["capsules"] if c.get("id") == item_id), None)
        if not cap:
            return JSONResponse({"error": "胶囊不存在"}, status_code=404)
        if cap.get("reply"):
            return {"item": _capsule_view(cap)}  # 已开启过，幂等返回
        days_left = _date_diff_days(cap.get("open_date", ""))
        if days_left is None or days_left > 0:
            return JSONResponse(
                {"error": f"还没到开启的日子，再等 {max(days_left, 0)} 天"},
                status_code=400,
            )
        gap = max(-(_date_diff_days(cap.get("created", "")) or 0), 0)
        messages = [
            {"role": "system", "content": CAPSULE_REPLY_PROMPT.format(
                created=cap.get("created", ""),
                open_date=cap.get("open_date", ""),
                content=cap.get("content", ""),
                gap=gap,
            )},
            {"role": "user", "content": "（开启胶囊）"},
        ]
        try:
            reply = (await _call_llm(messages, max_tokens=800)).strip()
        except Exception as e:
            return JSONResponse({"error": f"回信生成失败：{e}"}, status_code=500)
        cap["reply"] = reply
        cap["opened_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _save_timebox(data)
    info = _add_affinity("capsule_open", "开启时光胶囊，收到许墨的回信")
    return {"item": _capsule_view(cap), "affinity": info}


@app.delete("/api/timebox/capsule/{item_id}")
async def timebox_capsule_delete(item_id: str):
    async with _timebox_lock:
        data = _load_timebox()
        kept = [c for c in data["capsules"] if c.get("id") != item_id]
        if len(kept) == len(data["capsules"]):
            return JSONResponse({"error": "胶囊不存在"}, status_code=404)
        data["capsules"] = kept
        _save_timebox(data)
    return {"ok": True}


# --- 回忆卡 ----------------------------------------------------------------

RELIC_PROMPT = SYSTEM_PROMPT + """

【当前任务】请根据近期对话与记忆手账，为她制作一张「回忆卡」——像你们专属相册里的一页。
输出严格 JSON（不要任何多余文字）：
{"title": "...", "text": "...", "his_line": "..."}

要求：
- title：8 字以内，点名一个具体瞬间或意象；
- text：90~150 字，第二人称「你」回顾你们相处的画面，必须引用对话里真实出现过的事与细节，温柔克制、有画面感；
- his_line：此刻你想对她说的一句话，15~30 字，话留三分。"""


def _extract_relic_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "title": (data.get("title") or "").strip()[:20],
        "text": (data.get("text") or "").strip()[:400],
        "his_line": (data.get("his_line") or "").strip()[:80],
    }


@app.post("/api/timebox/relic/generate")
async def timebox_relic_generate(bg: bool = False):
    async def _work():
        # 汇总素材：最近对话 + 记忆手账 + 心动等级
        logs = _load_chat_log()[-40:]
        dialog_lines = []
        for item in logs:
            role = item.get("role")
            who = "她" if role == "user" else "许墨"
            text = (item.get("content") or "").strip()
            if text:
                dialog_lines.append(f"{who}：{text[:120]}")
        memories = _sorted_memories(_load_memories())[:15]
        mem_lines = [f"- [{m.get('tag', '其他')}] {m.get('content', '')}" for m in memories]
        aff = _affinity_info(_load_affinity())

        if not dialog_lines and not mem_lines:
            raise GenJobError("还没有可用的回忆素材，先和他聊几句吧", status=400)

        material = ""
        if dialog_lines:
            material += "【近期对话】\n" + "\n".join(dialog_lines) + "\n\n"
        if mem_lines:
            material += "【记忆手账】\n" + "\n".join(mem_lines) + "\n\n"
        material += f"【当前心动】{aff['value']}（{aff['level_name']}·{aff['level_title']}）"

        try:
            content = await _call_llm(
                [
                    {"role": "system", "content": RELIC_PROMPT},
                    {"role": "user", "content": material + "\n\n请输出 JSON。"},
                ],
                max_tokens=1200,
            )
        except Exception as e:
            raise GenJobError(f"回忆卡生成失败：{e}")

        parsed = _extract_relic_json(content)
        if not parsed or not parsed["text"]:
            raise GenJobError("回忆卡生成失败，请重试")

        item = {
            "id": uuid.uuid4().hex[:12],
            **parsed,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%m-%d %H:%M"),
        }
        async with _timebox_lock:
            data = _load_timebox()
            data["relics"].append(item)
            data["relics"] = data["relics"][-TIMEBOX_RELIC_MAX:]
            _save_timebox(data)
        info = _add_affinity("relic", f"回忆卡 · {parsed['title']}")
        return {"item": item, "affinity": info}

    if bg:
        job = await submit_gen_job("timebox_relic", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


@app.delete("/api/timebox/relic/{item_id}")
async def timebox_relic_delete(item_id: str):
    async with _timebox_lock:
        data = _load_timebox()
        kept = [r for r in data["relics"] if r.get("id") != item_id]
        if len(kept) == len(data["relics"]):
            return JSONResponse({"error": "回忆卡不存在"}, status_code=404)
        data["relics"] = kept
        _save_timebox(data)
    return {"ok": True}


# --- 约会企划 --------------------------------------------------------------

PLAN_PROMPT = SYSTEM_PROMPT + """

【当前任务】她提出了一个约会想法，请你（许墨）把它扩写成一份可执行的「约会企划书」。
输出严格 JSON（不要任何多余文字）：
{"title": "...", "invite": "...", "schedule": [{"time": "...", "item": "..."}], "tip": "..."}

要求：
- title：企划名，10 字以内，带一点学术或诗意的双关；
- invite：以许墨口吻发出的邀请，30~50 字，笃定而温柔；
- schedule：4~6 个时间点安排，time 形如 "14:00"，item 25 字内，安排要具体（结合恋语市场景：临江天桥、大学实验室、香樟公园、深夜咖啡馆等）；
- tip：一条他会悄悄准备的贴心细节，30 字内。"""


def _extract_plan_json(text: str):
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    schedule = data.get("schedule")
    if not isinstance(schedule, list):
        schedule = []
    clean_sched = []
    for s in schedule[:6]:
        if not isinstance(s, dict):
            continue
        t = str(s.get("time") or "").strip()[:8]
        it = str(s.get("item") or "").strip()[:60]
        if t and it:
            clean_sched.append({"time": t, "item": it})
    if not clean_sched:
        return None
    return {
        "title": (data.get("title") or "").strip()[:20] or "约会企划",
        "invite": (data.get("invite") or "").strip()[:120],
        "schedule": clean_sched,
        "tip": (data.get("tip") or "").strip()[:60],
    }


@app.post("/api/timebox/plan")
async def timebox_plan_create(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    idea = (body.get("idea") or "").strip()
    if not idea:
        return JSONResponse({"error": "请先说说你的约会想法"}, status_code=400)
    if len(idea) > 100:
        return JSONResponse({"error": "想法最多 100 字"}, status_code=400)

    try:
        content = await _call_llm(
            [
                {"role": "system", "content": PLAN_PROMPT},
                {"role": "user", "content": f"她的约会想法：{idea}\n\n请输出 JSON。"},
            ],
            max_tokens=1500,
        )
    except Exception as e:
        return JSONResponse({"error": f"企划生成失败：{e}"}, status_code=500)

    parsed = _extract_plan_json(content)
    if not parsed:
        return JSONResponse({"error": "企划生成失败，请重试"}, status_code=500)

    item = {
        "id": uuid.uuid4().hex[:12],
        "idea": idea,
        **parsed,
        "time": datetime.now().strftime("%m-%d %H:%M"),
    }
    async with _timebox_lock:
        data = _load_timebox()
        data["plans"].append(item)
        data["plans"] = data["plans"][-TIMEBOX_PLAN_MAX:]
        _save_timebox(data)
    info = _add_affinity("date_plan", f"约会企划 · {parsed['title']}")
    return {"item": item, "affinity": info}


@app.delete("/api/timebox/plan/{item_id}")
async def timebox_plan_delete(item_id: str):
    async with _timebox_lock:
        data = _load_timebox()
        kept = [p for p in data["plans"] if p.get("id") != item_id]
        if len(kept) == len(data["plans"]):
            return JSONResponse({"error": "企划不存在"}, status_code=404)
        data["plans"] = kept
        _save_timebox(data)
    return {"ok": True}


# --- 时光盒 · AI 配图（回忆卡 / 约会企划 / 纪念日 / 胶囊回信） -----------------

TIMEBOX_IMG_DIR = RolePath("static", "timebox_img")
TIMEBOX_IMG_PREFIX = "/static/timebox_img"
TIMEBOX_IMG_SIZES = {
    "relic": "1152x896",    # 回忆卡 · 横幅
    "plan": "896x1152",     # 企划 · 竖版海报
    "anniv": "1024x1024",   # 纪念日 · 方形
    "capsule": "896x1152",  # 胶囊回信 · 竖版
}
# 前端 type → timebox.json 里的列表键
TIMEBOX_IMG_POOLS = {
    "relic": "relics",
    "plan": "plans",
    "anniv": "anniversaries",
    "capsule": "capsules",
}

TIMEBOX_IMG_PROMPT = """你是《恋与制作人》官方卡面绘制助手。下面给出「时光 · 专属回忆」里一条记录的内容，请据此构思一个只属于许墨与她的画面，并输出一段可直接用于 AI 绘图的英文提示词。

【许墨形象锚点（许墨必须入画，提示词中要逐字包含下面这段固定英文外貌句，只能追加不能删改）】
"{xumo_look}"

【画面要求】
- 双人温柔互动的场景优先；「她」可以用背影、侧脸或手部特写来暗示，不刻画清晰正脸
- 许墨形象铁律：银色细框眼镜必须清晰可见、瞳色深紫罗兰（禁琥珀棕/蓝/灰瞳）、白净鹅蛋脸鼻梁高挺、衣着只用黑白灰紫（白衬衫+深灰或深紫外套/大衣）
- 恋与制作人画风：日系乙女向精致立绘、厚涂+赛璐璐、五官与手部精致、柔和唯美用色、氛围感光影、背景虚化光斑
- 统一冷紫或暖光色调，可点缀蝴蝶 / 纸鹤 / 紫色意象

【输出要求】只输出一个 JSON 对象，不要任何其他文字：
{{"image_prompt": "英文绘图提示词，100~160 词，包含场景、两人姿态、着装、镜头与光线、画风关键词"}}"""


def _extract_image_prompt_json(text: str) -> str:
    """从 LLM 输出中提取 {"image_prompt": "..."} 的英文绘图提示词；失败返回空串。"""
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return (data.get("image_prompt") or "").strip()
        except json.JSONDecodeError:
            pass
    return ""


@app.post("/api/timebox/image")
async def timebox_image_generate(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    kind = (body.get("type") or "").strip()
    item_id = (body.get("id") or "").strip()

    async def _work():
        if kind not in TIMEBOX_IMG_SIZES or not item_id:
            raise GenJobError("参数不正确", status=400)

        # 锁内取素材快照（生成耗时长，不持锁）
        async with _timebox_lock:
            data = _load_timebox()
            pool = data.get(TIMEBOX_IMG_POOLS[kind], [])
            item = next((x for x in pool if x.get("id") == item_id), None)
            if not item:
                raise GenJobError("记录不存在", status=404)
            if kind == "capsule" and not item.get("reply"):
                raise GenJobError("先开启这枚胶囊，再为回信配图", status=400)
            snap = dict(item)

        if kind == "relic":
            material = (
                f"【回忆卡 · {snap.get('title', '')}】\n{snap.get('text', '')}\n"
                f"许墨的话：「{snap.get('his_line', '')}」\n日期：{snap.get('date', '')}"
            )
        elif kind == "plan":
            sched = "；".join(
                f"{s.get('time', '')} {s.get('item', '')}" for s in snap.get("schedule", [])
            )
            material = (
                f"【约会企划 · {snap.get('title', '')}】\n她的想法：{snap.get('idea', '')}\n"
                f"许墨的邀请：「{snap.get('invite', '')}」\n时间线：{sched}\n"
                f"贴心细节：{snap.get('tip', '')}"
            )
        elif kind == "anniv":
            material = (
                f"【纪念日】{snap.get('icon', '')} {snap.get('name', '')}，"
                f"日期 {snap.get('date', '')}——属于她与许墨的重要日子。"
            )
        else:  # capsule
            material = (
                f"【时光胶囊】她于 {snap.get('created', '')} 写下：「{snap.get('content', '')}」\n"
                f"{snap.get('open_date', '')} 开启时，许墨回信写道：\n{snap.get('reply', '')}"
            )

        try:
            content = await _call_llm(
                [
                    {
                        "role": "system",
                        "content": TIMEBOX_IMG_PROMPT.format(xumo_look=XUMO_LOOK_EN),
                    },
                    {"role": "user", "content": material + "\n\n请输出 JSON。"},
                ],
                max_tokens=800,
            )
        except Exception as e:
            raise GenJobError(f"配图构思失败：{e}")

        image_prompt = _extract_image_prompt_json(content)
        if not image_prompt:
            raise GenJobError("配图构思失败，请重试")
        if "Lucien" not in image_prompt:
            image_prompt = XUMO_LOOK_EN + ", " + image_prompt

        image_url = await _openai_generate_image(
            image_prompt,
            TIMEBOX_IMG_DIR,
            TIMEBOX_IMG_PREFIX,
            f"{kind}_{item_id}",
            TIMEBOX_IMG_SIZES[kind],
            has_character=True,
        )
        if not image_url:
            raise GenJobError("配图生成失败，请重试")

        # 回写（条目可能已被删，容忍）
        async with _timebox_lock:
            data = _load_timebox()
            pool = data.get(TIMEBOX_IMG_POOLS[kind], [])
            item = next((x for x in pool if x.get("id") == item_id), None)
            if item:
                item["image"] = image_url
                item["image_prompt"] = image_prompt
                item["image_time"] = datetime.now().strftime("%m-%d %H:%M")
                _save_timebox(data)

        stamp = f"?t={int(_time.time())}"
        return {"image": image_url + stamp, "affinity": None}

    if body.get("bg"):
        job = await submit_gen_job("timebox_img", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


# ---------------------------------------------------------------------------
# 约会手账 · 一起去过哪里（约会记录 / 足迹地图）
# ---------------------------------------------------------------------------
DATELOG_FILE = RolePath("date_log.json")
DATE_PHOTOS_DIR = RolePath("static", "date_photos")
_date_log_lock = asyncio.Lock()

DATE_LOG_MAX = 200  # 约会记录上限


def _load_datelog() -> dict:
    try:
        data = json.loads(DATELOG_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("dates"), list):
        data = {"dates": []}
    return data


def _save_datelog(data: dict):
    atomic_json(DATELOG_FILE, data)


def _datelog_stats(dates: list) -> dict:
    places = set()
    first = ""
    for d in dates:
        key = (d.get("place") or "").strip()
        if key:
            places.add(key)
        dt = (d.get("date") or "")[:10]
        if dt and (not first or dt < first):
            first = dt
    return {"total": len(dates), "places": len(places), "first_date": first}


@app.get("/api/dates")
async def datelog_get():
    data = _load_datelog()
    return {
        "dates": list(reversed(data["dates"])),  # 新的在前
        "stats": _datelog_stats(data["dates"]),
    }


DATE_MEMORY_PROMPT = SYSTEM_PROMPT + """

【当前任务】她把一次和你的约会记进了你们的「约会手账」。请以许墨的身份，为这次约会写一段手账小结。
时间：{date}
地点：{place}{city}
她记下的内容：{what}
她标记的心情：{mood}

要求（80~140 字）：
- 第二人称「你」，像当晚回家后在手账页边写下的批注，温柔克制、有画面感；
- 自然呼应她写下的内容与心情（若内容为空，就着地点与心情展开想象，不要提"她没写"）；
- 只输出小结正文，不要 JSON、不要解释、不要落款。"""


async def _gen_date_memory(item: dict, prev: str = "") -> str:
    city = (item.get("city") or "").strip()
    # 注意：不要在 user 消息里引用旧版小结全文——上游推理模型会因此耗尽
    # max_tokens（finish=length、content 为空），改为只要求换新角度。
    messages = [
        {
            "role": "system",
            "content": DATE_MEMORY_PROMPT.format(
                date=item.get("date", ""),
                place=item.get("place", ""),
                city=f"（{city}）" if city else "",
                what=(item.get("what") or "").strip() or "（未填写）",
                mood=item.get("mood") or "—",
            ),
        },
        {
            "role": "user",
            "content": (
                "（这是重写：请换一个与前次完全不同的切入角度与意象，重新写这次约会的小结）"
                if prev
                else "（请写小结）"
            ),
        },
    ]
    for _ in range(2):  # 上游偶发空回复，自动重试一次
        text = (await _call_llm(messages, max_tokens=1000)).strip()
        if text:
            return text
    return ""


def _save_date_photo(item_id: str, data_url: str) -> str:
    """解析 dataURL 存为 static/date_photos/{id}.jpg，返回访问路径；失败返回空串。"""
    b64 = (data_url or "").strip()
    if not b64:
        return ""
    if b64.startswith("data:"):
        _, _, b64 = b64.partition(",")
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return ""
    if len(raw) < 100 or len(raw) > 8 * 1024 * 1024:
        return ""
    DATE_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    (DATE_PHOTOS_DIR / f"{item_id}.jpg").write_bytes(raw)
    return f"/static/date_photos/{item_id}.jpg"


@app.post("/api/dates")
async def datelog_add(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    place = (body.get("place") or "").strip()
    city = (body.get("city") or "").strip()[:20]
    date = (body.get("date") or "").strip()[:10]
    what = (body.get("what") or "").strip()[:300]
    mood = ((body.get("mood") or "").strip() or "💕")[:4]
    photo_b64 = (body.get("photo") or "").strip()
    if not place:
        return JSONResponse({"error": "请填写约会地点"}, status_code=400)
    if len(place) > 30:
        return JSONResponse({"error": "地点名最多 30 字"}, status_code=400)
    days = _date_diff_days(date)
    if days is None:
        return JSONResponse({"error": "日期格式不正确"}, status_code=400)
    if days > 0:
        return JSONResponse(
            {"error": "约会日期还不能在未来——赴约之后再来记录吧"}, status_code=400
        )

    async with _date_log_lock:
        data = _load_datelog()
        if len(data["dates"]) >= DATE_LOG_MAX:
            return JSONResponse(
                {"error": f"约会记录最多 {DATE_LOG_MAX} 条，先清理一些吧"}, status_code=400
            )
        item = {
            "id": "d" + uuid.uuid4().hex[:10],
            "place": place,
            "city": city,
            "date": date,
            "what": what,
            "mood": mood,
            "photo": "",
            "memory": "",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if photo_b64:
            item["photo"] = _save_date_photo(item["id"], photo_b64)
        data["dates"].append(item)
        _save_datelog(data)

    # 许墨补写小结（失败不阻塞记录本身）
    try:
        item["memory"] = await _gen_date_memory(item)
        async with _date_log_lock:
            fresh = _load_datelog()
            for i, d in enumerate(fresh["dates"]):
                if d.get("id") == item["id"]:
                    fresh["dates"][i]["memory"] = item["memory"]
                    break
            _save_datelog(fresh)
    except Exception:
        pass

    info = _add_affinity("date_log", f"约会手账 · {place}")
    return {"item": item, "affinity": info}


@app.post("/api/dates/{item_id}/memory")
async def datelog_memory_regen(item_id: str):
    async with _date_log_lock:
        data = _load_datelog()
        item = next((d for d in data["dates"] if d.get("id") == item_id), None)
        if not item:
            return JSONResponse({"error": "约会记录不存在"}, status_code=404)
        prev = item.get("memory") or ""
    try:
        memory = await _gen_date_memory(item, prev=prev)
    except Exception as e:
        return JSONResponse({"error": f"小结生成失败：{e}"}, status_code=500)
    if not memory:
        return JSONResponse({"error": "小结生成失败，请重试"}, status_code=500)
    async with _date_log_lock:
        fresh = _load_datelog()
        for i, d in enumerate(fresh["dates"]):
            if d.get("id") == item_id:
                fresh["dates"][i]["memory"] = memory
                break
        _save_datelog(fresh)
    item["memory"] = memory
    info = _add_affinity("date_memory", f"重写约会小结 · {item.get('place', '')}")
    return {"item": item, "affinity": info}


# --- 约会手账 · AI 配图（为一条约会记录生成双人场景插画） ---
DATE_IMG_DIR = RolePath("static", "date_img")


@app.post("/api/dates/{item_id}/image")
async def datelog_image_generate(item_id: str, bg: bool = False):
    """为一条约会记录生成 AI 配图（按需，落盘并回写到记录）。"""
    async def _work():
        async with _date_log_lock:
            data = _load_datelog()
            item = next((d for d in data["dates"] if d.get("id") == item_id), None)
            if not item:
                raise GenJobError("约会记录不存在", status=404)
            snap = dict(item)
        city = f"（{snap.get('city', '')}）" if snap.get("city") else ""
        material = (
            f"【约会手账 · {snap.get('place', '')}】{city}\n"
            f"日期：{snap.get('date', '')}\n她记下的内容：{snap.get('what', '') or '（未填写）'}\n"
            f"心情：{snap.get('mood', '')}\n许墨的小结：{snap.get('memory', '')}"
        )
        img_url, img_prompt = await _llm_image_for_text(
            material, DATE_IMG_DIR, "/static/date_img", f"d_{item_id}",
            IMG2IMG_SIZES.get("landscape", "1024x1024"), with_xumo=True,
        )
        if not img_url:
            raise GenJobError("配图生成失败，请重试")
        async with _date_log_lock:
            fresh = _load_datelog()
            for i, d in enumerate(fresh["dates"]):
                if d.get("id") == item_id:
                    fresh["dates"][i]["ai_image"] = img_url
                    fresh["dates"][i]["ai_image_prompt"] = img_prompt
                    fresh["dates"][i]["ai_image_time"] = datetime.now().strftime("%m-%d %H:%M")
                    break
            _save_datelog(fresh)
        return {"image": img_url + f"?t={int(_time.time())}", "affinity": None}

    if bg:
        job = await submit_gen_job("datelog", _work)
        return {"job_id": job["id"], "status": "queued", "bg": True}
    try:
        return await _work()
    except GenJobError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


@app.delete("/api/dates/{item_id}")
async def datelog_delete(item_id: str):
    if not re.fullmatch(r"d[0-9a-f]{6,16}", item_id):
        return JSONResponse({"error": "记录不存在"}, status_code=404)
    async with _date_log_lock:
        data = _load_datelog()
        kept = [d for d in data["dates"] if d.get("id") != item_id]
        if len(kept) == len(data["dates"]):
            return JSONResponse({"error": "约会记录不存在"}, status_code=404)
        data["dates"] = kept
        _save_datelog(data)
    # 连带清理照片文件
    try:
        f = DATE_PHOTOS_DIR / f"{item_id}.jpg"
        if f.exists():
            f.unlink()
    except OSError:
        pass
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    # 默认仅本机回环，避免误将服务暴露到局域网/公网；需要外部访问时显式 HOST=0.0.0.0
    host = os.getenv("HOST", "127.0.0.1")
    # 绑定非回环地址时强制要求访问口令，防止局域网/公网任意调用 LLM 消耗余额
    if host not in ("127.0.0.1", "localhost", "::1") and not (os.getenv("ACCESS_CODE") or "").strip():
        raise RuntimeError(
            "HOST 绑定非回环地址时必须设置 ACCESS_CODE 访问口令，否则拒绝启动。"
            "请先在 .env 中配置 ACCESS_CODE。"
        )
    # 自签 HTTPS 端口：局域网 IP 上 getUserMedia（电话麦克风）需要安全上下文
    _cert_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "certs")
    _crt = os.path.join(_cert_dir, "xumo.crt")
    _key = os.path.join(_cert_dir, "xumo.key")
    if os.path.exists(_crt) and os.path.exists(_key):
        import threading
        _https_port = int(os.getenv("HTTPS_PORT", "8443"))
        _hs = uvicorn.Server(uvicorn.Config(
            app, host=host, port=_https_port,
            ssl_certfile=_crt, ssl_keyfile=_key, log_level="warning",
        ))
        threading.Thread(target=_hs.run, daemon=True, name="https-server").start()
        print(f"[xumo] https listening on https://{host}:{_https_port}/")
    else:
        print("[xumo] certs/xumo.crt 不存在，跳过 HTTPS 端口（麦克风需 HTTPS 访问）")
    uvicorn.run(app, host=host, port=port)
