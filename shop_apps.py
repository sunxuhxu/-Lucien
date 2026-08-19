"""和许墨一起开店：轻量双人经营玩法。

店铺状态按角色持久化，所有会改变余额/库存的操作都在同一文件锁内完成。
"""
import json
import random
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from role_data import RolePath
from store_common import atomic_json, file_lock

router = APIRouter()
SHOP_FILE = RolePath("together_shop.json")


SHOP_TYPES = {
    "cafe": {
        "name": "蝶屿咖啡馆", "tagline": "咖啡香、旧书页和一场不赶时间的相遇",
        "products": [
            {"id": "coffee", "name": "许墨手冲", "desc": "他负责控制水温，你负责挑一张唱片", "price": 32, "cost": 13},
            {"id": "cake", "name": "白巧莓果蛋糕", "desc": "酸甜刚好，适合分享", "price": 38, "cost": 17},
            {"id": "set", "name": "双人午后套餐", "desc": "两杯饮品和一份只留给熟客的甜点", "price": 68, "cost": 29},
        ],
    },
    "bookshop": {
        "name": "墨迹书店", "tagline": "卖书，也替每一段故事保留安静的位置",
        "products": [
            {"id": "essay", "name": "许墨选书", "desc": "每本都夹着他写的一句推荐语", "price": 46, "cost": 24},
            {"id": "notebook", "name": "蝶翼笔记本", "desc": "适合记下灵感与尚未说出口的话", "price": 28, "cost": 11},
            {"id": "gift", "name": "共读礼盒", "desc": "两本书、两枚书签和一次共读约定", "price": 88, "cost": 43},
        ],
    },
    "flower": {
        "name": "紫藤花房", "tagline": "把难以开口的心意，交给花替你说",
        "products": [
            {"id": "violet", "name": "紫罗兰小束", "desc": "克制、安静，却足够长久", "price": 42, "cost": 19},
            {"id": "butterfly", "name": "蝶语花盒", "desc": "一只纸蝶停在花瓣之间", "price": 66, "cost": 30},
            {"id": "custom", "name": "心意定制花礼", "desc": "许墨会根据故事替客人配花", "price": 108, "cost": 52},
        ],
    },
}

STRATEGIES = {
    "steady": {"name": "默契营业", "desc": "你招呼客人，他负责出品，稳定积累口碑", "demand": 1.0, "rep": 2},
    "story": {"name": "故事企划", "desc": "请每位客人留下一句话，许墨替今日写结语", "demand": 0.9, "rep": 4},
    "surprise": {"name": "限定惊喜", "desc": "推出只营业一天的隐藏款，客流更高也更忙", "demand": 1.35, "rep": 1},
}

EVENTS = [
    ("一位常客带朋友来，说这里像一处不会催人离开的岛。", 2),
    ("临近打烊忽然下雨，你们把门口的伞借给了最后一位客人。", 1),
    ("客人认出了许墨教授。他扶了扶眼镜，只说今天是你的合伙人。", 3),
    ("有个小朋友在留言簿上画了一只歪歪扭扭的蝴蝶。", 2),
    ("你们配合得太自然，熟客笑着问这家店是不是一封很长的情书。", 3),
]


def _load() -> dict:
    if SHOP_FILE.exists():
        try:
            data = json.loads(SHOP_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return {"opened": False}


def _save(data: dict) -> None:
    atomic_json(SHOP_FILE, data)


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _stamp() -> str:
    return datetime.now().strftime("%m-%d %H:%M")


def _public(data: dict) -> dict:
    payload = {"shop": data, "types": SHOP_TYPES, "strategies": STRATEGIES}
    if data.get("opened"):
        kind = SHOP_TYPES.get(data.get("type"), SHOP_TYPES["cafe"])
        payload["products"] = kind["products"]
        payload["can_open_today"] = data.get("last_open_date") != _today()
        payload["next_level_xp"] = data.get("level", 1) * 100
    return payload


@router.get("/api/together-shop")
async def together_shop_get():
    return _public(_load())


@router.post("/api/together-shop/setup")
async def together_shop_setup(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    shop_type = str(body.get("type") or "").strip()
    name = str(body.get("name") or "").strip()
    if shop_type not in SHOP_TYPES:
        return JSONResponse({"error": "请选择一种店铺"}, status_code=400)
    if not name or len(name) > 18:
        return JSONResponse({"error": "店名需要是 1—18 个字"}, status_code=400)
    with file_lock(SHOP_FILE):
        old = _load()
        if old.get("opened"):
            return JSONResponse({"error": "你们已经有一家店了"}, status_code=409)
        products = SHOP_TYPES[shop_type]["products"]
        data = {
            "opened": True, "id": uuid.uuid4().hex[:10], "type": shop_type, "name": name,
            "tagline": SHOP_TYPES[shop_type]["tagline"], "created_at": _stamp(),
            "level": 1, "xp": 0, "reputation": 10, "balance": 520,
            "inventory": {p["id"]: 6 for p in products}, "last_open_date": "",
            "stats": {"days": 0, "customers": 0, "revenue": 0, "profit": 0},
            "logs": [{"ts": _stamp(), "title": "我们开店了", "text": f"许墨把写着“{name}”的木牌挂到门口。", "line": "从今天起，这里是我们的共同课题。"}],
        }
        _save(data)
    return _public(data)


@router.post("/api/together-shop/restock")
async def together_shop_restock(req: Request):
    try:
        body = await req.json()
        product_id = str(body.get("product_id") or "").strip()
        qty = int(body.get("qty", 5))
    except (TypeError, ValueError, Exception):
        return JSONResponse({"error": "补货参数不正确"}, status_code=400)
    if qty < 1 or qty > 20:
        return JSONResponse({"error": "每次可补 1—20 份"}, status_code=400)
    with file_lock(SHOP_FILE):
        data = _load()
        if not data.get("opened"):
            return JSONResponse({"error": "请先和许墨开一家店"}, status_code=400)
        products = SHOP_TYPES.get(data.get("type"), {}).get("products", [])
        product = next((p for p in products if p["id"] == product_id), None)
        if not product:
            return JSONResponse({"error": "没有找到这件商品"}, status_code=404)
        total = product["cost"] * qty
        if data.get("balance", 0) < total:
            return JSONResponse({"error": f"店铺余额不足，还差 ¥{total - data.get('balance', 0)}"}, status_code=400)
        data["balance"] -= total
        data.setdefault("inventory", {})[product_id] = data.get("inventory", {}).get(product_id, 0) + qty
        data.setdefault("logs", []).append({"ts": _stamp(), "title": "一起补货", "text": f"补入 {product['name']} × {qty}", "line": "清单给我吧。重的那一箱，我来。"})
        data["logs"] = data["logs"][-30:]
        _save(data)
    return _public(data)


@router.post("/api/together-shop/open")
async def together_shop_open(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"error": "请求体格式错误"}, status_code=400)
    strategy_id = str(body.get("strategy") or "steady").strip()
    if strategy_id not in STRATEGIES:
        return JSONResponse({"error": "请选择今日营业方式"}, status_code=400)
    with file_lock(SHOP_FILE):
        data = _load()
        if not data.get("opened"):
            return JSONResponse({"error": "请先和许墨开一家店"}, status_code=400)
        if data.get("last_open_date") == _today():
            return JSONResponse({"error": "今天已经营业过了，明天再一起开门吧"}, status_code=409)
        products = SHOP_TYPES[data["type"]]["products"]
        inventory = data.setdefault("inventory", {})
        if sum(max(0, inventory.get(p["id"], 0)) for p in products) <= 0:
            return JSONResponse({"error": "货架空了，先一起补货吧"}, status_code=400)

        strategy = STRATEGIES[strategy_id]
        level = max(1, int(data.get("level", 1)))
        wanted = max(3, int(random.randint(5, 9) * strategy["demand"] + level))
        sold = []
        revenue = cost = units = 0
        available = [p for p in products if inventory.get(p["id"], 0) > 0]
        while units < wanted and available:
            product = random.choice(available)
            inventory[product["id"]] -= 1
            revenue += product["price"]
            cost += product["cost"]
            units += 1
            rec = next((x for x in sold if x["id"] == product["id"]), None)
            if rec:
                rec["qty"] += 1
            else:
                sold.append({"id": product["id"], "name": product["name"], "qty": 1})
            available = [p for p in products if inventory.get(p["id"], 0) > 0]

        customers = max(1, units - random.randint(0, min(2, units - 1)))
        event_text, event_rep = random.choice(EVENTS)
        profit = revenue - cost
        xp_gain = customers * 8 + strategy["rep"] * 3
        old_level = level
        data["xp"] = int(data.get("xp", 0)) + xp_gain
        while data["xp"] >= data["level"] * 100:
            data["xp"] -= data["level"] * 100
            data["level"] += 1
        data["balance"] = int(data.get("balance", 0)) + revenue
        data["reputation"] = min(100, int(data.get("reputation", 0)) + strategy["rep"] + event_rep)
        data["last_open_date"] = _today()
        stats = data.setdefault("stats", {})
        stats["days"] = stats.get("days", 0) + 1
        stats["customers"] = stats.get("customers", 0) + customers
        stats["revenue"] = stats.get("revenue", 0) + revenue
        stats["profit"] = stats.get("profit", 0) + profit
        line = random.choice([
            "辛苦了，合伙人。今天的配合，我给满分。",
            "账目我核过了。至于打烊后的时间……要不要也一起安排？",
            "比营业额更值得记录的，是你今天笑了很多次。",
        ])
        log = {"ts": _stamp(), "title": f"第 {stats['days']} 次营业 · {strategy['name']}", "text": event_text, "line": line, "revenue": revenue, "profit": profit, "customers": customers, "sold": sold}
        data.setdefault("logs", []).append(log)
        data["logs"] = data["logs"][-30:]
        _save(data)
    result = _public(data)
    result["result"] = log
    result["level_up"] = data["level"] > old_level
    return result
