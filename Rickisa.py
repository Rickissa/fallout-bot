# fallout_bot_complete.py
import os
import json
import time
import uuid
import logging
import datetime
import re
import random
from typing import Dict, Any, List, Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, JobQueue
)
from datetime import time as dt_time

# ---------------- CONFIG ----------------
BOT_TOKEN = "7976287620:AAHnHM40DfWGte6nFvzg5ZhD9NKVkMVO9Co"
DATA_FILE = "data.json"
VENUS_NAME = "Венера"
LOG_PAGE_SIZE = 6
SHOP_PAGE_SIZE = 5

# Параметры производства
PRODUCTION_TYPES = {
    "легкий": {"people": 15, "yield_min": 15, "yield_max": 25},
    "средний": {"people": 20, "yield_min": 25, "yield_max": 30},
    "тяжелый": {"people": 35, "yield_min": 30, "yield_max": 40},
    "усиленный": {"people": 50, "yield_min": 50, "yield_max": 75}
}

# Параметры форм правления (по умолчанию)
DEFAULT_GOVERNMENT_CONFIG = {
    "рабский_труд": {"people_cost": -10, "caps_gain": 35},
    "людские_отношения": {"people_gain": 2, "caps_cost": 25},
    "трудовые_отношения": {"goods_bonus": 10, "caps_cost": 10}
}

# Настройки дипломатии (длительность в днях)
DEFAULT_DIPLOMACY_DURATION = {
    "pact": 3,
    "war": 2,
    "military": 3,
    "trade": 3
}

# Цена за единицу товара (глобальная)
DEFAULT_GOODS_PRICE = 10

# Время выполнения ежедневных заданий (по умолчанию 18:00)
DEFAULT_PRODUCTION_TIME = dt_time(18, 0)
DEFAULT_GOVERNMENT_TIME = dt_time(18, 0)

# ----------------------------------------

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
# ---------------- Persistence ----------------
def load_data() -> Dict[str, Any]:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            # ensure keys
            d.setdefault("players", {})
            d.setdefault("shop_items", [])
            d.setdefault("logs", [])
            d.setdefault("ADMIN_PASSWORD", "fallout_admin_123")
            d.setdefault("ADMIN_ID", None)
            d.setdefault("group_chat_id", None)
            d.setdefault("market_items", [])
            d.setdefault("active_deals", {})
            d.setdefault("pending_diplomacy", {})
            d.setdefault("active_treaties", {})
            d.setdefault("diplomacy_config", DEFAULT_DIPLOMACY_DURATION.copy())
            d.setdefault("government_config", DEFAULT_GOVERNMENT_CONFIG.copy())
            d.setdefault("goods_price", DEFAULT_GOODS_PRICE)
            d.setdefault("production_time", "18:00")
            d.setdefault("government_time", "18:00")
            d.setdefault("scheduled_payments", {})
            d.setdefault("scheduled_goods", {})

            # Проверка целостности government_config
            gov_config = d.setdefault("government_config", {})
            for gtype, default_params in DEFAULT_GOVERNMENT_CONFIG.items():
                if gtype not in gov_config:
                    gov_config[gtype] = default_params.copy()
                else:
                    for key, value in default_params.items():
                        if key not in gov_config[gtype]:
                            gov_config[gtype][key] = value
            
            # Инициализируем поселения для существующих игроков
            for pid, player in d.get("players", {}).items():
                if "settlements" not in player:
                    player["settlements"] = []
            
            return d
        except Exception as e:
            logger.exception("Failed to load data.json: %s", e)
    
    # defaults
    return {
        "players": {},
        "shop_items": [],
        "logs": [],
        "ADMIN_PASSWORD": "fallout_admin_123",
        "ADMIN_ID": None,
        "group_chat_id": None,
        "market_items": [],
        "active_deals": {},
        "pending_diplomacy": {},
        "active_treaties": {},
        "diplomacy_config": DEFAULT_DIPLOMACY_DURATION.copy(),
        "government_config": DEFAULT_GOVERNMENT_CONFIG.copy(),
        "goods_price": DEFAULT_GOODS_PRICE,
        "production_time": "18:00",
        "government_time": "18:00",
        "scheduled_payments": {},
        "scheduled_goods": {}
    }


def save_data(app_context: ContextTypes.DEFAULT_TYPE) -> None:
    d = app_context.application.bot_data
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "players": d.get("players", {}),
                "shop_items": d.get("shop_items", []),
                "logs": d.get("logs", []),
                "ADMIN_PASSWORD": d.get("ADMIN_PASSWORD", "fallout_admin_123"),
                "ADMIN_ID": d.get("ADMIN_ID"),
                "group_chat_id": d.get("group_chat_id"),
                "market_items": d.get("market_items", []),
                "active_deals": d.get("active_deals", {}),
                "pending_diplomacy": d.get("pending_diplomacy", {}),
                "active_treaties": d.get("active_treaties", {}),
                "diplomacy_config": d.get("diplomacy_config", DEFAULT_DIPLOMACY_DURATION.copy()),
                "government_config": d.get("government_config", DEFAULT_GOVERNMENT_CONFIG.copy()),
                "goods_price": d.get("goods_price", DEFAULT_GOODS_PRICE),
                "production_time": d.get("production_time", "18:00"),
                "government_time": d.get("government_time", "18:00"),
                "scheduled_payments": d.get("scheduled_payments", {}),
                "scheduled_goods": d.get("scheduled_goods", {})
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.exception("Failed to save data.json: %s", e)


def add_log(ctx: ContextTypes.DEFAULT_TYPE, text: str) -> None:
    bot_data = ctx.application.bot_data
    logs = bot_data.setdefault("logs", [])
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    logs.append(f"[{ts}] {text}")
    if len(logs) > 5000:
        del logs[: len(logs) - 5000]
    save_data(ctx)

# ---------------- Helpers ----------------
def strid(uid: int) -> str:
    return str(uid)


def get_faction_name(players: Dict, pid: str) -> str:
    p = players.get(pid, {})
    return p.get("faction") or p.get("first_name") or f"ID {pid}"


def shop_message_text(items: List[dict], page: int = 0) -> str:
    if not items:
        return "🛒 Лавка пуста."
    start_idx = page * SHOP_PAGE_SIZE
    end_idx = start_idx + SHOP_PAGE_SIZE
    page_items = items[start_idx:end_idx]
    lines = []
    for i, it in enumerate(page_items, start_idx + 1):
        owner = it.get("owner_name") or str(it.get("owner_id"))
        lines.append(f"{i}. {it['title']} — {it['price']} крышек (от {owner})")
    total_pages = (len(items) + SHOP_PAGE_SIZE - 1) // SHOP_PAGE_SIZE
    header = f"🛒 Лавка (стр. {page + 1}/{total_pages}):\n"
    return header + "\n".join(lines)


def make_shop_keyboard(items: List[dict], page: int = 0) -> InlineKeyboardMarkup:
    start_idx = page * SHOP_PAGE_SIZE
    end_idx = start_idx + SHOP_PAGE_SIZE
    page_items = items[start_idx:end_idx]
    kb = []
    for i, it in enumerate(page_items, start_idx):
        kb.append([InlineKeyboardButton(f"Купить #{i + 1} — {it['price']}💠", callback_data=f"buy_{i}")])
    if not kb:
        kb = [[InlineKeyboardButton("Лавка пуста", callback_data="noop")]]
    else:
        nav_buttons = []
        total_pages = (len(items) + SHOP_PAGE_SIZE - 1) // SHOP_PAGE_SIZE
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("◀️ Назад", callback_data=f"shop_page_{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ▶️", callback_data=f"shop_page_{page + 1}"))
        if nav_buttons:
            kb.append(nav_buttons)
    return InlineKeyboardMarkup(kb)


def market_message_text(items: List[dict]) -> str:
    if not items:
        return "🏪 Магазин пуст."
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"{i}. {it}")
    return "🏪 Магазин:\n" + "\n".join(lines)


def format_troops(troops: List[dict]) -> str:
    if not troops:
        return "Войск нет"
    lines = []
    for i, t in enumerate(troops, 1):
        lines.append(f"\n  {i}. {t['name']}")
        lines.append(f"     Количество: {t['qty']}")
    return "\n".join(lines)


def format_storage(items: List[str]) -> str:
    if not items:
        return "Склад пуст"
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"\n  {i}. {item}")
        lines.append("     " + "-" * 40)
    return "\n".join(lines)


def format_base(items: List[str]) -> str:
    if not items:
        return "База пуста"
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"\n  {i}. {item}")
        lines.append("     " + "-" * 40)
    return "\n".join(lines)


def format_focus(items: List[str]) -> str:
    if not items:
        return "Фокус пуст"
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"\n  {i}. {item}")
        lines.append("     " + "-" * 40)
    return "\n".join(lines)


def format_actions(items: List[str]) -> str:
    if not items:
        return "Записи о ходе действий пусты"
    lines = []
    for i, item in enumerate(items, 1):
        lines.append(f"\n  {i}. {item}")
        lines.append("     " + "-" * 40)
    return "\n".join(lines)


def player_main_kb(is_admin: bool) -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🛒 Лавка", callback_data="player_shop")],
        [InlineKeyboardButton("➕ Добавить товар", callback_data="player_add_item")],
        [InlineKeyboardButton("⚔️ Войска", callback_data="player_troops")],
        [InlineKeyboardButton("📦 Склад", callback_data="player_storage")],
        [InlineKeyboardButton("🏰 База", callback_data="player_base")],
        [InlineKeyboardButton("🎯 Фокус", callback_data="player_focus")],
        [InlineKeyboardButton("🚶 Ход", callback_data="player_actions")],
        [InlineKeyboardButton("🏪 Магазин", callback_data="player_market")],
        [InlineKeyboardButton("💰 Торговая точка", callback_data="player_trade")],
        [InlineKeyboardButton("💸 Передать крышки", callback_data="player_transfer")],
        [InlineKeyboardButton("🤝 Дипломатия", callback_data="player_diplomacy")],
        [InlineKeyboardButton("🏛 Форма правления", callback_data="player_government")],
        [InlineKeyboardButton("🏭 Производство", callback_data="player_production")],
        [InlineKeyboardButton("🏘 Мои поселения", callback_data="player_settlement")],
        [InlineKeyboardButton("👤 Профиль", callback_data="player_profile")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton("⚙️ Админ-панель", callback_data="admin_open")])
    return InlineKeyboardMarkup(kb)


def admin_main_kb() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("👥 Игроки", callback_data="adm_players")],
        [InlineKeyboardButton("🛒 Управление лавкой", callback_data="adm_shop")],
        [InlineKeyboardButton("📜 Логи", callback_data="adm_logs_0")],
        [InlineKeyboardButton("✉️ Отправить ход игроку", callback_data="adm_send_turn")],
        [InlineKeyboardButton("⚔️ Войска всех фракций", callback_data="adm_all_troops")],
        [InlineKeyboardButton("📦 Товары всех фракций", callback_data="adm_all_goods")],
        [InlineKeyboardButton("🏛 Все формы правления", callback_data="adm_all_governments")],
        [InlineKeyboardButton("🤝 Все дипломатии", callback_data="adm_all_treaties")],
        [InlineKeyboardButton("🏭 Производство всех фракций", callback_data="adm_all_productions")],
        [InlineKeyboardButton("🎁 Управление магазином", callback_data="adm_market")],
        [InlineKeyboardButton("💰 Установить цену товара", callback_data="adm_set_goods_price")],
        [InlineKeyboardButton("⏰ Установить время производства", callback_data="adm_set_production_time")],
        [InlineKeyboardButton("⏰ Установить время формы правления", callback_data="adm_set_government_time")],
        [InlineKeyboardButton("🤝 Управление дипломатией", callback_data="adm_diplomacy")],
        [InlineKeyboardButton("🏛 Управление формами правления", callback_data="adm_government")],
        [InlineKeyboardButton("🏘 Управление поселениями", callback_data="adm_settlements")],
        [InlineKeyboardButton("💵 Плановые выплаты", callback_data="adm_scheduled_payments")],
        [InlineKeyboardButton("🔙 Выйти из админки", callback_data="adm_logout")]
    ]
    return InlineKeyboardMarkup(kb)
    # ===== PRODUCTION JOBS =====
async def production_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    player_id = job.data["player_id"]
    prod_type = job.data["prod_type"]
    bot_data = context.application.bot_data
    players = bot_data.get("players", {})
    player = players.get(str(player_id))
    if not player:
        return
    prod_info = PRODUCTION_TYPES[prod_type]
    units = random.randint(prod_info["yield_min"], prod_info["yield_max"])
    player["goods"] = player.get("goods", 0) + units
    try:
        await context.bot.send_message(
            chat_id=int(player_id),
            text=f"🏭 Производство завершено! Вы получили {units} единиц товара ({prod_type} труд). Они добавлены на склад."
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить игрока {player_id} о производстве: {e}")
    add_log(context, f"Игрок {player_id} получил {units} единиц товара от производства ({prod_type})")


def schedule_production_job(job_queue: JobQueue, player_id: str, prod_type: str, schedule_time: dt_time) -> None:
    if job_queue is None:
        logger.error("JobQueue не доступен. Невозможно запланировать производство для игрока %s", player_id)
        return
    cancel_production_job(job_queue, player_id)
    job_queue.run_daily(
        production_job_callback,
        time=schedule_time,
        days=tuple(range(7)),
        data={"player_id": player_id, "prod_type": prod_type},
        name=f"prod_{player_id}"
    )


def cancel_production_job(job_queue: JobQueue, player_id: str) -> None:
    if job_queue is None:
        return
    current_jobs = job_queue.get_jobs_by_name(f"prod_{player_id}")
    for job in current_jobs:
        job.schedule_removal()


async def remove_production(player: dict, player_id: str, ctx: ContextTypes.DEFAULT_TYPE):
    prod = player.get("production")
    if not prod:
        return
    troops = player.get("troops", [])
    people_troop = None
    for t in troops:
        if t["name"].lower() == "люди":
            people_troop = t
            break
    if people_troop:
        people_troop["qty"] += prod["people_used"]
    else:
        troops.append({"name": "Люди", "qty": prod["people_used"]})
    player["production"] = None
    cancel_production_job(ctx.application.job_queue, player_id)
    save_data(ctx)


# ===== GOVERNMENT JOBS =====
async def government_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    player_id = job.data["player_id"]
    gov_type = job.data["gov_type"]
    bot_data = context.application.bot_data
    players = bot_data.get("players", {})
    player = players.get(str(player_id))
    if not player:
        logger.warning(f"government_job_callback: игрок {player_id} не найден")
        return
    gov_config = bot_data.get("government_config", DEFAULT_GOVERNMENT_CONFIG)
    params = gov_config.get(gov_type)
    if not params:
        logger.error(f"government_job_callback: неизвестный тип правления {gov_type} для игрока {player_id}")
        return

    if gov_type == "рабский_труд":
        caps = params.get("caps_gain", 35)
        player["caps"] = player.get("caps", 0) + caps
        effect_text = f"Вы получили {caps} крышек от рабского труда."
    elif gov_type == "людские_отношения":
        people = params.get("people_gain", 2)
        troops = player.get("troops", [])
        people_troop = None
        for t in troops:
            if t["name"].lower() == "люди":
                people_troop = t
                break
        if people_troop:
            people_troop["qty"] += people
        else:
            troops.append({"name": "Люди", "qty": people})
        effect_text = f"Вы получили +{people} людей (людские отношения)."
    elif gov_type == "трудовые_отношения":
        goods = params.get("goods_bonus", 10)
        player["goods"] = player.get("goods", 0) + goods
        effect_text = f"Вы получили +{goods} товара (трудовые отношения)."
    else:
        return

    try:
        await context.bot.send_message(
            chat_id=int(player_id),
            text=f"🏛 Ежедневный эффект формы правления:\n{effect_text}"
        )
    except Exception as e:
        logger.error(f"Не удалось уведомить игрока {player_id} о форме правления: {e}")

    add_log(context, f"Игрок {player_id} получил ежедневный эффект от {gov_type}")


def schedule_government_job(job_queue: JobQueue, player_id: str, gov_type: str, schedule_time: dt_time) -> None:
    if job_queue is None:
        logger.error("JobQueue не доступен. Невозможно запланировать форму правления для игрока %s", player_id)
        return
    cancel_government_job(job_queue, player_id)
    job_queue.run_daily(
        government_job_callback,
        time=schedule_time,
        days=tuple(range(7)),
        data={"player_id": player_id, "gov_type": gov_type},
        name=f"gov_{player_id}"
    )


def cancel_government_job(job_queue: JobQueue, player_id: str) -> None:
    if job_queue is None:
        return
    current_jobs = job_queue.get_jobs_by_name(f"gov_{player_id}")
    for job in current_jobs:
        job.schedule_removal()


# ===== SETTLEMENT INCOME JOBS =====
async def settlement_income_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    job_data = job.data
    player_id = job_data["player_id"]
    set_idx = job_data["set_idx"]
    bot_data = context.application.bot_data
    players = bot_data.get("players", {})
    player = players.get(str(player_id))
    if not player:
        return
    
    settlements = player.get("settlements", [])
    if set_idx < 0 or set_idx >= len(settlements):
        return
    
    settlement = settlements[set_idx]
    daily_income = settlement.get("daily_income", 0)
    settlement["balance"] = settlement.get("balance", 0) + daily_income
    
    try:
        if daily_income > 0:
            await context.bot.send_message(
                chat_id=int(player_id),
                text=f"🏘 Поселение '{settlement['name']}' принесло доход:\n+{daily_income} крышек\nБаланс: {settlement['balance']}"
            )
        elif daily_income < 0:
            await context.bot.send_message(
                chat_id=int(player_id),
                text=f"🏘 Поселение '{settlement['name']}' требует налога:\n{daily_income} крышек\nБаланс: {settlement['balance']}"
            )
    except Exception as e:
        logger.error(f"Не удалось уведомить игрока {player_id} о доходе поселения: {e}")
    add_log(context, f"Доход поселения {player_id} '{settlement['name']}': {daily_income} крышек")


def schedule_settlement_income(job_queue: JobQueue, player_id: str, set_idx: int, schedule_time: dt_time) -> None:
    if job_queue is None:
        return
    cancel_settlement_income(job_queue, player_id, set_idx)
    job_queue.run_daily(
        settlement_income_callback,
        time=schedule_time,
        days=tuple(range(7)),
        data={"player_id": player_id, "set_idx": set_idx},
        name=f"settlement_{player_id}_{set_idx}"
    )


def cancel_settlement_income(job_queue: JobQueue, player_id: str, set_idx: int = None) -> None:
    if job_queue is None:
        return
    if set_idx is not None:
        current_jobs = job_queue.get_jobs_by_name(f"settlement_{player_id}_{set_idx}")
    else:
        current_jobs = job_queue.get_jobs_by_name(f"settlement_{player_id}")
    for job in current_jobs:
        job.schedule_removal()


# ===== SCHEDULED PAYMENTS JOBS =====
async def scheduled_payment_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    player_id = job.data["player_id"]
    amount = job.data["amount"]
    bot_data = context.application.bot_data
    players = bot_data.get("players", {})
    player = players.get(str(player_id))
    if not player:
        return
    
    player["caps"] = player.get("caps", 0) + amount
    try:
        if amount > 0:
            await context.bot.send_message(
                chat_id=int(player_id),
                text=f"💰 Вы получили {amount} крышек от администратора!"
            )
        else:
            await context.bot.send_message(
                chat_id=int(player_id),
                text=f"💸 У вас списано {abs(amount)} крышек администратором!"
            )
    except Exception as e:
        logger.error(f"Не удалось уведомить игрока {player_id} о выплате: {e}")
    add_log(context, f"Плановая выплата {amount} крышек игроку {player_id}")


def schedule_payment_job(job_queue: JobQueue, player_id: str, amount: int, schedule_time: dt_time) -> None:
    if job_queue is None:
        logger.error("JobQueue не доступен. Невозможно запланировать выплату для игрока %s", player_id)
        return
    cancel_payment_job(job_queue, player_id)
    job_queue.run_daily(
        scheduled_payment_callback,
        time=schedule_time,
        days=tuple(range(7)),
        data={"player_id": player_id, "amount": amount},
        name=f"payment_{player_id}"
    )


def cancel_payment_job(job_queue: JobQueue, player_id: str) -> None:
    if job_queue is None:
        return
    current_jobs = job_queue.get_jobs_by_name(f"payment_{player_id}")
    for job in current_jobs:
        job.schedule_removal()


# ===== SCHEDULED GOODS JOBS =====
async def scheduled_goods_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    player_id = job.data["player_id"]
    quantity = job.data["quantity"]
    bot_data = context.application.bot_data
    players = bot_data.get("players", {})
    player = players.get(str(player_id))
    if not player:
        return
    
    player["goods"] = player.get("goods", 0) + quantity
    try:
        if quantity > 0:
            await context.bot.send_message(
                chat_id=int(player_id),
                text=f"📦 Вы получили {quantity} единиц товара от администратора!"
            )
        else:
            await context.bot.send_message(
                chat_id=int(player_id),
                text=f"📦 У вас списано {abs(quantity)} единиц товара администратором!"
            )
    except Exception as e:
        logger.error(f"Не удалось уведомить игрока {player_id} о выплате товара: {e}")
    add_log(context, f"Плановая выплата {quantity} товара игроку {player_id}")


def schedule_goods_job(job_queue: JobQueue, player_id: str, quantity: int, schedule_time: dt_time) -> None:
    if job_queue is None:
        logger.error("JobQueue не доступен. Невозможно запланировать выплату товара для игрока %s", player_id)
        return
    cancel_goods_job(job_queue, player_id)
    job_queue.run_daily(
        scheduled_goods_callback,
        time=schedule_time,
        days=tuple(range(7)),
        data={"player_id": player_id, "quantity": quantity},
        name=f"goods_{player_id}"
    )


def cancel_goods_job(job_queue: JobQueue, player_id: str) -> None:
    if job_queue is None:
        return
    current_jobs = job_queue.get_jobs_by_name(f"goods_{player_id}")
    for job in current_jobs:
        job.schedule_removal()


# ===== WAR START JOB =====
async def war_start_job_callback(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    treaty_id = job.data["treaty_id"]
    bot_data = context.application.bot_data
    treaty = bot_data["active_treaties"].get(treaty_id)
    if not treaty or treaty.get("type") != "war" or not treaty.get("pending", True):
        return
    treaty["pending"] = False
    treaty["start"] = time.time()
    save_data(context)
    f1, f2 = treaty.get("factions", ["?", "?"])
    for pid in treaty.get("participants", []):
        try:
            await context.bot.send_message(
                chat_id=int(pid),
                text=f"⚔️ Война между {f1} и {f2} началась!"
            )
        except Exception as e:
            logger.error(f"Не удалось уведомить игрока {pid} о начале войны: {e}")
    add_log(context, f"Война между {f1} и {f2} началась.")


def schedule_war_start(job_queue: JobQueue, treaty_id: str, delay_days: float) -> None:
    if job_queue is None:
        logger.error("JobQueue не доступен. Невозможно запланировать начало войны.")
        return
    job_queue.run_once(
        war_start_job_callback,
        delay_days * 24 * 3600,
        data={"treaty_id": treaty_id},
        name=f"war_start_{treaty_id}"
    )
    # ===== COMMANDS =====
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = strid(user.id)
    bot_data = ctx.application.bot_data
    players = bot_data.setdefault("players", {})

    if uid not in players:
        players[uid] = {
            "username": user.username or "",
            "first_name": user.first_name or "",
            "faction": None,
            "caps": 0,
            "goods": 0,
            "troops": [],
            "storage": [],
            "base": [],
            "focus": [],
            "actions": [],
            "production": None,
            "government": None,
            "settlements": []
        }
        ctx.user_data["awaiting_faction"] = True
        await ctx.bot.send_message(chat_id=user.id,
                                   text=f"Привет, {user.first_name}! Я {VENUS_NAME}. Введи название своей фракции:")
        add_log(ctx, f"Новый игрок {user.first_name} (@{user.username}) начал регистрацию.")
        save_data(ctx)
        return

    is_admin = (bot_data.get("ADMIN_ID") == user.id)
    await ctx.bot.send_message(chat_id=user.id, text=f"С возвращением, {user.first_name}!",
                               reply_markup=player_main_kb(is_admin))


async def cmd_setgroup(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_text("Эту команду нужно выполнить в группе, где бот должен публиковать лавку.")
        return
    bot_data = ctx.application.bot_data
    bot_data["group_chat_id"] = update.effective_chat.id
    await update.message.reply_text("Группа зарегистрирована для публикации лавки.")
    add_log(ctx, f"Группа {update.effective_chat.id} зарегистрирована.")
    save_data(ctx)


async def cmd_admin(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bot_data = ctx.application.bot_data
    if bot_data.get("ADMIN_ID") == uid:
        await ctx.bot.send_message(chat_id=uid, text="Админ-панель:", reply_markup=admin_main_kb())
        return
    ctx.user_data["awaiting_admin_password"] = True
    await ctx.bot.send_message(chat_id=uid, text="Введи пароль админа (текстом):")
    # ===== CALLBACK HANDLER =====
async def callback_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user = query.from_user
    uid = strid(user.id)
    bot_data = ctx.application.bot_data
    players = bot_data.setdefault("players", {})
    shop = bot_data.setdefault("shop_items", [])
    admin_id = bot_data.get("ADMIN_ID")

    # ===== PLAYER SHOP =====
    if data == "player_shop":
        ctx.user_data["shop_page"] = 0
        text = shop_message_text(shop, 0)
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=make_shop_keyboard(shop, 0))
        add_log(ctx, f"Игрок {user.first_name} посмотрел лавку.")
        return

    if data.startswith("shop_page_"):
        page = int(data.split("_")[2])
        text = shop_message_text(shop, page)
        await query.edit_message_text(text=text, reply_markup=make_shop_keyboard(shop, page))
        return

    if data == "player_add_item":
        ctx.user_data["adding_item"] = True
        await ctx.bot.send_message(chat_id=int(uid),
                                   text="Введи товар в формате: Название Цена (например: Броня 150)\n\n💡 Можно писать любой текст, главное чтобы в конце было число - это будет цена.")
        return

    # ===== ТОРГОВАЯ ТОЧКА =====
    if data == "player_trade":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        price = bot_data.get("goods_price", DEFAULT_GOODS_PRICE)
        goods = player.get("goods", 0)
        total = goods * price
        text = f"💰 Торговая точка\n\n"
        text += f"Текущая цена за единицу товара: {price} крышек.\n"
        text += f"У вас на складе: {goods} единиц товара.\n"
        text += f"Общая стоимость вашего товара: {total} крышек.\n\n"
        text += "Вы можете продать товар игроку другой фракции."
        kb = [
            [InlineKeyboardButton("📤 Продать товар", callback_data="trade_sell")],
            [InlineKeyboardButton("Назад", callback_data="player_profile")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "trade_sell":
        my_faction = players.get(uid, {}).get("faction")
        factions = set()
        for p in players.values():
            if p.get("faction") and p.get("faction") != my_faction:
                factions.add(p["faction"])
        if not factions:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет других фракций для продажи.")
            return
        kb = []
        faction_list = sorted(factions)
        ctx.user_data["trade_factions"] = faction_list
        for i, f in enumerate(faction_list):
            kb.append([InlineKeyboardButton(f, callback_data=f"trade_faction_{i}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_trade")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выберите фракцию покупателя:",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("trade_faction_"):
        try:
            index = int(data.split("_", 2)[2])
        except:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка выбора фракции.")
            return
        faction_list = ctx.user_data.get("trade_factions", [])
        if index < 0 or index >= len(faction_list):
            await ctx.bot.send_message(chat_id=int(uid), text="Фракция не найдена.")
            return
        faction = faction_list[index]
        candidates = []
        for pid, p in players.items():
            if p.get("faction") == faction and pid != uid:
                candidates.append((pid, p.get("first_name", "Неизвестный")))
        if not candidates:
            await ctx.bot.send_message(chat_id=int(uid), text="В этой фракции нет других игроков.")
            return
        kb = []
        for pid, name in candidates:
            kb.append([InlineKeyboardButton(name, callback_data=f"trade_buyer_{pid}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="trade_sell")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выберите покупателя:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("trade_buyer_"):
        buyer_id = data.split("_", 2)[2]
        ctx.user_data["trade_buyer"] = buyer_id
        await ctx.bot.send_message(chat_id=int(uid), text="Введите количество товара для продажи (целое число):")
        ctx.user_data["awaiting_trade_qty"] = True
        return

    # ===== DEAL ACCEPT/REJECT =====
    if data.startswith("deal_accept_"):
        deal_id = data.split("_", 2)[2]
        deal = bot_data["active_deals"].get(deal_id)
        if not deal or deal["buyer_id"] != uid:
            await query.answer("Сделка не найдена или недействительна.")
            return
        if deal["status"] != "pending_buyer":
            await query.answer("Эта сделка уже обработана.")
            return
        ctx.user_data["deal_id"] = deal_id
        await ctx.bot.send_message(chat_id=int(uid),
                                   text="Введите процент налога (от 0 до 100), который вы хотите взять за сделку:")
        ctx.user_data["awaiting_tax"] = True
        return

    if data.startswith("deal_reject_"):
        deal_id = data.split("_", 2)[2]
        deal = bot_data["active_deals"].get(deal_id)
        if not deal:
            await query.answer("Сделка уже неактуальна.")
            return
        if deal["status"] != "pending_buyer":
            await query.answer("Эта сделка уже обработана.")
            return
        seller_id = deal["seller_id"]
        try:
            await ctx.bot.send_message(chat_id=int(seller_id), text="❌ Покупатель отклонил ваше предложение.")
        except:
            pass
        del bot_data["active_deals"][deal_id]
        save_data(ctx)
        await ctx.bot.send_message(chat_id=int(uid), text="Вы отклонили сделку.")
        return

    if data.startswith("deal_confirm_"):
        deal_id = data.split("_", 2)[2]
        deal = bot_data["active_deals"].get(deal_id)
        if not deal or deal["seller_id"] != str(uid):
            await query.answer("Сделка не найдена.")
            return
        if deal["status"] != "pending_seller":
            await query.answer("Эта сделка уже обработана.")
            return

        seller = players.get(deal["seller_id"])
        buyer = players.get(deal["buyer_id"])
        if not seller or not buyer:
            await ctx.bot.send_message(chat_id=int(uid), text="Один из участников не найден.")
            del bot_data["active_deals"][deal_id]
            save_data(ctx)
            return

        qty = deal["qty"]
        price = deal["price"]
        tax = deal["tax"]

        if seller.get("goods", 0) < qty:
            await ctx.bot.send_message(chat_id=int(uid),
                                       text="У вас недостаточно товара для продажи.")
            del bot_data["active_deals"][deal_id]
            save_data(ctx)
            return

        seller["goods"] -= qty
        seller_gets = int(price * (100 - tax) / 100)
        buyer_gets = price - seller_gets

        seller["caps"] = seller.get("caps", 0) + seller_gets
        buyer["caps"] = buyer.get("caps", 0) + buyer_gets

        add_log(ctx,
                f"Сделка {deal_id}: продавец {get_faction_name(players, deal['seller_id'])} ({deal['seller_id']}) продал {qty} товара за {price} крышек, налог {tax}%. Продавец получил {seller_gets}, покупатель получил комиссию {buyer_gets}.")

        if admin_id:
            try:
                seller_name = get_faction_name(players, deal['seller_id'])
                buyer_name = get_faction_name(players, deal['buyer_id'])
                price_per_unit = price // qty
                await ctx.bot.send_message(
                    chat_id=int(admin_id),
                    text=f"💰 Сделка {deal_id} завершена:\n"
                         f"Продавец: {seller_name} ({deal['seller_id']})\n"
                         f"Покупатель: {buyer_name} ({deal['buyer_id']})\n"
                         f"Количество: {qty}, цена за ед.: {price_per_unit}, общая сумма: {price}, налог {tax}%\n"
                         f"Продавец получил {seller_gets}, покупатель получил комиссию {buyer_gets}."
                )
            except Exception as e:
                logger.error(f"Не удалось уведомить админа: {e}")

        await ctx.bot.send_message(chat_id=int(deal["seller_id"]),
                                   text=f"✅ Сделка завершена! Вы продали {qty} товара за {price} крышек (налог {tax}%). Получено: {seller_gets} крышек.")
        await ctx.bot.send_message(chat_id=int(deal["buyer_id"]),
                                   text=f"✅ Сделка завершена! Вы выступили посредником в продаже {qty} товара за {price} крышек. Ваша комиссия: {buyer_gets} крышек.")

        del bot_data["active_deals"][deal_id]
        save_data(ctx)
        return
            # ===== ПРОИЗВОДСТВО =====
    if data == "player_production":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        prod = player.get("production")
        text = "🏭 Производство\n\n"
        if prod:
            prod_type = prod["type"]
            text += f"Текущий труд: {prod_type.capitalize()}\nЗанято людей: {prod['people_used']}\n\n"
            kb = [
                [InlineKeyboardButton("🔄 Сменить труд", callback_data="prod_change")],
                [InlineKeyboardButton("❌ Снять труд", callback_data="prod_remove")],
                [InlineKeyboardButton("Назад", callback_data="player_profile")]
            ]
        else:
            text += "Выберите тип труда:"
            kb = []
            for ptype, params in PRODUCTION_TYPES.items():
                kb.append([InlineKeyboardButton(
                    f"{ptype.capitalize()} – {params['people']} чел, {params['yield_min']}-{params['yield_max']} ед",
                    callback_data=f"prod_select_{ptype}"
                )])
            kb.append([InlineKeyboardButton("Назад", callback_data="player_profile")])
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("prod_select_"):
        prod_type = data.split("_", 2)[2]
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка.")
            return
        troops = player.get("troops", [])
        people_troop = None
        for t in troops:
            if t["name"].lower() == "люди":
                people_troop = t
                break
        if not people_troop:
            await ctx.bot.send_message(chat_id=int(uid), text="У вас нет войск 'Люди'.")
            return
        params = PRODUCTION_TYPES[prod_type]
        if people_troop["qty"] < params["people"]:
            await ctx.bot.send_message(chat_id=int(uid),
                                       text=f"Недостаточно людей. Нужно {params['people']}, у вас {people_troop['qty']}.")
            return
        if player.get("production"):
            await remove_production(player, uid, ctx)
        people_troop["qty"] -= params["people"]
        if people_troop["qty"] <= 0:
            troops.remove(people_troop)
        player["production"] = {"type": prod_type, "people_used": params["people"]}
        save_data(ctx)

        job_queue = ctx.application.job_queue
        if job_queue:
            try:
                prod_time_str = bot_data.get("production_time", "18:00")
                hour, minute = map(int, prod_time_str.split(':'))
                schedule_production_job(job_queue, uid, prod_type, dt_time(hour, minute))
                await ctx.bot.send_message(chat_id=int(uid),
                                           text=f"🏭 Вы начали {prod_type} труд. Ежедневно в {hour:02d}:{minute:02d} вы будете получать продукцию.")
            except Exception as e:
                logger.error(f"Ошибка планирования производства для {uid}: {e}")
                await ctx.bot.send_message(chat_id=int(uid),
                                           text="⚠️ Производство запущено, но автоматическое получение продукции невозможно из-за ошибки. Обратитесь к администратору.")
        else:
            await ctx.bot.send_message(chat_id=int(uid),
                                       text="⚠️ Производство запущено, но автоматическое получение продукции невозможно из-за отсутствия планировщика. Обратитесь к администратору.")
            logger.error("JobQueue отсутствует, производство для игрока {} не будет работать по расписанию.".format(uid))

        add_log(ctx, f"Игрок {user.first_name} начал производство: {prod_type}")
        return

    if data == "prod_remove":
        player = players.get(uid)
        if not player or not player.get("production"):
            await ctx.bot.send_message(chat_id=int(uid), text="У вас нет активного производства.")
            return
        await remove_production(player, uid, ctx)
        await ctx.bot.send_message(chat_id=int(uid), text="Производство остановлено, люди возвращены.")
        return

    if data == "prod_change":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка.")
            return
        text = "Выберите новый тип труда:"
        kb = []
        for ptype, params in PRODUCTION_TYPES.items():
            kb.append([InlineKeyboardButton(
                f"{ptype.capitalize()} – {params['people']} чел, {params['yield_min']}-{params['yield_max']} ед",
                callback_data=f"prod_select_{ptype}"
            )])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_production")])
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    # ===== МАГАЗИН =====
    if data == "player_market":
        market_items = bot_data.get("market_items", [])
        if not market_items:
            await ctx.bot.send_message(chat_id=int(uid), text="🏪 Магазин пуст.")
            return
        text = market_message_text(market_items)
        await ctx.bot.send_message(chat_id=int(uid), text=text)
        return

    # ===== ВОЙСКА =====
    if data == "player_troops":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        troops = p.get("troops", [])
        txt = f"⚔️ ВОЙСКА\n\n{format_troops(troops)}"
        kb = [
            [InlineKeyboardButton("Добавить войско", callback_data="troop_add")],
            [InlineKeyboardButton("Управлять войсками", callback_data="troop_manage")],
            [InlineKeyboardButton("Назад", callback_data="player_profile")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "troop_add":
        ctx.user_data["adding_troop"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введи войско в формате: Название Кол-во (например: ГУЛЬ 50)")
        return

    if data == "troop_manage":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        troops = p.get("troops", [])
        if not troops:
            await ctx.bot.send_message(chat_id=int(uid), text="Войск нет.")
            return
        kb = []
        for i, t in enumerate(troops, 1):
            kb.append([InlineKeyboardButton(f"{i}. {t['name']} ({t['qty']})", callback_data=f"troop_item_{i - 1}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_troops")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери войско:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("troop_item_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        troops = p.get("troops", [])
        if idx < 0 or idx >= len(troops):
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
            return
        t = troops[idx]
        kb = [
            [InlineKeyboardButton("Редактировать", callback_data=f"troop_edit_{idx}")],
            [InlineKeyboardButton("Удалить", callback_data=f"troop_del_{idx}")],
            [InlineKeyboardButton("Назад", callback_data="troop_manage")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=f"Войско #{idx + 1}: {t['name']} — {t['qty']}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("troop_edit_"):
        idx = int(data.split("_", 2)[2])
        ctx.user_data["editing_troop"] = idx
        await ctx.bot.send_message(chat_id=int(uid), text="Введи новое значение: Название Кол-во (пример: ГУЛЬ 100)")
        return

    if data.startswith("troop_del_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        troops = p.get("troops", [])
        if 0 <= idx < len(troops):
            removed = troops.pop(idx)
            add_log(ctx, f"Игрок {user.first_name} удалил свое войско: {removed}")
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text=f"Войско '{removed['name']}' удалено.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет такого войска.")
        return

    # ===== ХРАНИЛИЩЕ =====
    if data == "player_storage":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("storage", [])
        goods = p.get("goods", 0)
        txt = f"📦 СКЛАД\n\nПроизведённый товар: {goods} ед.\n{format_storage(items)}"
        kb = [
            [InlineKeyboardButton("Добавить запись", callback_data="storage_add")],
            [InlineKeyboardButton("Изменить/Удалить", callback_data="storage_manage")],
            [InlineKeyboardButton("Назад", callback_data="player_profile")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "storage_add":
        ctx.user_data["adding_storage"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введи текст для склада:")
        return

    if data == "storage_manage":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("storage", [])
        if not items:
            await ctx.bot.send_message(chat_id=int(uid), text="Склад пуст (нет записей).")
            return
        kb = []
        for i, item in enumerate(items, 1):
            kb.append([InlineKeyboardButton(f"{i}. {item[:30]}{'...' if len(item) > 30 else ''}",
                                            callback_data=f"storage_item_{i - 1}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_storage")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери запись склада:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("storage_item_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("storage", [])
        if not (0 <= idx < len(items)):
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
            return
        item = items[idx]
        kb = [
            [InlineKeyboardButton("Редактировать", callback_data=f"storage_edit_{idx}")],
            [InlineKeyboardButton("Удалить", callback_data=f"storage_del_{idx}")],
            [InlineKeyboardButton("Назад", callback_data="storage_manage")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=f"{item}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("storage_edit_"):
        idx = int(data.split("_", 2)[2])
        ctx.user_data["editing_storage"] = idx
        await ctx.bot.send_message(chat_id=int(uid), text="Введи новый текст:")
        return

    if data.startswith("storage_del_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("storage", [])
        if 0 <= idx < len(items):
            removed = items.pop(idx)
            add_log(ctx, f"Игрок {user.first_name} удалил запись склада: {removed}")
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text="Запись удалена.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
        return

    # ===== БАЗА =====
    if data == "player_base":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("base", [])
        txt = f"🏰 БАЗА\n\n{format_base(items)}"
        kb = [
            [InlineKeyboardButton("Добавить в базу", callback_data="base_add")],
            [InlineKeyboardButton("Изменить/Удалить", callback_data="base_manage")],
            [InlineKeyboardButton("Назад", callback_data="player_profile")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "base_add":
        ctx.user_data["adding_base"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введи текст для базы:")
        return

    if data == "base_manage":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("base", [])
        if not items:
            await ctx.bot.send_message(chat_id=int(uid), text="База пуста.")
            return
        kb = []
        for i, item in enumerate(items, 1):
            kb.append([InlineKeyboardButton(f"{i}. {item[:30]}{'...' if len(item) > 30 else ''}",
                                            callback_data=f"base_item_{i - 1}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_base")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери запись базы:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("base_item_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("base", [])
        if not (0 <= idx < len(items)):
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
            return
        item = items[idx]
        kb = [
            [InlineKeyboardButton("Редактировать", callback_data=f"base_edit_{idx}")],
            [InlineKeyboardButton("Удалить", callback_data=f"base_del_{idx}")],
            [InlineKeyboardButton("Назад", callback_data="base_manage")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=f"{item}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("base_edit_"):
        idx = int(data.split("_", 2)[2])
        ctx.user_data["editing_base"] = idx
        await ctx.bot.send_message(chat_id=int(uid), text="Введи новый текст:")
        return

    if data.startswith("base_del_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("base", [])
        if 0 <= idx < len(items):
            removed = items.pop(idx)
            add_log(ctx, f"Игрок {user.first_name} удалил из базы: {removed}")
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text="Запись удалена.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
        return

    # ===== ФОКУС =====
    if data == "player_focus":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("focus", [])
        txt = f"🎯 ФОКУС\n\n{format_focus(items)}"
        kb = [
            [InlineKeyboardButton("Добавить в фокус", callback_data="focus_add")],
            [InlineKeyboardButton("Изменить/Удалить", callback_data="focus_manage")],
            [InlineKeyboardButton("Назад", callback_data="player_profile")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "focus_add":
        ctx.user_data["adding_focus"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введи текст для фокуса:")
        return

    if data == "focus_manage":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("focus", [])
        if not items:
            await ctx.bot.send_message(chat_id=int(uid), text="Фокус пуст.")
            return
        kb = []
        for i, item in enumerate(items, 1):
            kb.append([InlineKeyboardButton(f"{i}. {item[:30]}{'...' if len(item) > 30 else ''}",
                                            callback_data=f"focus_item_{i - 1}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_focus")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери запись фокуса:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("focus_item_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("focus", [])
        if not (0 <= idx < len(items)):
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
            return
        item = items[idx]
        kb = [
            [InlineKeyboardButton("Редактировать", callback_data=f"focus_edit_{idx}")],
            [InlineKeyboardButton("Удалить", callback_data=f"focus_del_{idx}")],
            [InlineKeyboardButton("Назад", callback_data="focus_manage")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=f"{item}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("focus_edit_"):
        idx = int(data.split("_", 2)[2])
        ctx.user_data["editing_focus"] = idx
        await ctx.bot.send_message(chat_id=int(uid), text="Введи новый текст:")
        return

    if data.startswith("focus_del_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("focus", [])
        if 0 <= idx < len(items):
            removed = items.pop(idx)
            add_log(ctx, f"Игрок {user.first_name} удалил фокус: {removed}")
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text="Запись удалена.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
        return

    # ===== ХОД ДЕЙСТВИЙ =====
    if data == "player_actions":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("actions", [])
        txt = f"🚶 ХОД ДЕЙСТВИЙ\n\n{format_actions(items)}"
        kb = [
            [InlineKeyboardButton("Добавить запись", callback_data="actions_add")],
            [InlineKeyboardButton("Изменить/Удалить", callback_data="actions_manage")],
            [InlineKeyboardButton("Назад", callback_data="player_profile")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "actions_add":
        ctx.user_data["adding_actions"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введи запись о ходе действий:")
        return

    if data == "actions_manage":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("actions", [])
        if not items:
            await ctx.bot.send_message(chat_id=int(uid), text="Записи о ходе действий пусты.")
            return
        kb = []
        for i, item in enumerate(items, 1):
            kb.append([InlineKeyboardButton(f"{i}. {item[:30]}{'...' if len(item) > 30 else ''}",
                                            callback_data=f"actions_item_{i - 1}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_actions")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери запись:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("actions_item_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("actions", [])
        if not (0 <= idx < len(items)):
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
            return
        item = items[idx]
        kb = [
            [InlineKeyboardButton("Редактировать", callback_data=f"actions_edit_{idx}")],
            [InlineKeyboardButton("Удалить", callback_data=f"actions_del_{idx}")],
            [InlineKeyboardButton("Назад", callback_data="actions_manage")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=f"{item}", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("actions_edit_"):
        idx = int(data.split("_", 2)[2])
        ctx.user_data["editing_actions"] = idx
        await ctx.bot.send_message(chat_id=int(uid), text="Введи новый текст:")
        return

    if data.startswith("actions_del_"):
        idx = int(data.split("_", 2)[2])
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        items = p.get("actions", [])
        if 0 <= idx < len(items):
            removed = items.pop(idx)
            add_log(ctx, f"Игрок {user.first_name} удалил запись о ходе действий: {removed}")
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text="Запись удалена.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Неверный индекс.")
        return
            # ===== ПОСЕЛЕНИЯ (ИГРОК) =====
    if data == "player_settlement":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        
        settlements = player.get("settlements", [])
        if not settlements:
            await ctx.bot.send_message(
                chat_id=int(uid), 
                text="🏘 У вас нет поселений. Обратитесь к админу для создания.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Назад", callback_data="player_profile")]])
            )
            return
        
        kb = []
        for i, settlement in enumerate(settlements):
            name = settlement.get('name', f'Поселение {i+1}')
            kb.append([InlineKeyboardButton(f"🏘 {name}", callback_data=f"player_set_view_{i}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_profile")])
        
        await ctx.bot.send_message(
            chat_id=int(uid),
            text="🏘 Выберите поселение для управления:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if data.startswith("player_set_view_"):
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        
        try:
            idx = int(data.split("_", 3)[3])
        except:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка индекса.")
            return
        
        settlements = player.get("settlements", [])
        if idx < 0 or idx >= len(settlements):
            await ctx.bot.send_message(chat_id=int(uid), text="Поселение не найдено.")
            return
        
        settlement = settlements[idx]
        name = settlement.get("name", "Поселение")
        population = settlement.get("population", 0)
        daily_income = settlement.get("daily_income", 0)
        balance = settlement.get("balance", 0)
        
        txt = f"🏘 ПОСЕЛЕНИЕ: {name}\n\n"
        txt += f"Население: {population}\n"
        txt += f"Ежедневный доход/налог: {daily_income} крышек\n"
        txt += f"Баланс поселения: {balance} крышек\n"
        
        ctx.user_data["current_settlement_idx"] = idx
        
        kb = [
            [InlineKeyboardButton("💰 Снять крышки", callback_data="settlement_withdraw")],
            [InlineKeyboardButton("📥 Добавить крышки", callback_data="settlement_deposit")],
            [InlineKeyboardButton("Назад", callback_data="player_settlement")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "settlement_withdraw":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        settlements = player.get("settlements", [])
        idx = ctx.user_data.get("current_settlement_idx", 0)
        if idx < 0 or idx >= len(settlements):
            await ctx.bot.send_message(chat_id=int(uid), text="Поселение не найдено.")
            return
        
        settlement = settlements[idx]
        balance = settlement.get("balance", 0)
        if balance <= 0:
            await ctx.bot.send_message(chat_id=int(uid), text=f"На поселении нет крышек для снятия. Баланс: {balance}")
            return
        ctx.user_data["settlement_withdraw_amount"] = True
        await ctx.bot.send_message(chat_id=int(uid), 
                                   text=f"На поселении {balance} крышек.\nВведите сумму для снятия (целое число):")
        return

    if data == "settlement_deposit":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        caps = player.get("caps", 0)
        if caps <= 0:
            await ctx.bot.send_message(chat_id=int(uid), text=f"У вас нет крышек. Баланс: {caps}")
            return
        ctx.user_data["settlement_deposit_amount"] = True
        await ctx.bot.send_message(chat_id=int(uid),
                                   text=f"У вас {caps} крышек.\nВведите сумму для добавления на поселение (целое число):")
        return

    # ===== ПРОФИЛЬ =====
    if data == "player_profile":
        p = players.get(uid)
        if not p:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        settlements = p.get("settlements", [])
        settlement_info = ""
        if settlements:
            settlement_info = f"Поселения: {len(settlements)} шт."
        else:
            settlement_info = "Поселения: 0 шт."
        
        txt = f"👤 ПРОФИЛЬ\n\n"
        txt += f"Игрок: {p.get('first_name')} @{p.get('username')}\n"
        txt += f"Фракция: {p.get('faction')}\n"
        txt += f"Крышек: {p.get('caps')}\n"
        txt += f"Товар: {p.get('goods', 0)}\n"
        txt += f"Войск: {len(p.get('troops', []))}\n"
        txt += f"Склад (записи): {len(p.get('storage', []))}\n"
        txt += f"База: {len(p.get('base', []))}\n"
        txt += f"Фокус: {len(p.get('focus', []))}\n"
        txt += f"Ход действий: {len(p.get('actions', []))}\n"
        txt += f"Производство: {'да' if p.get('production') else 'нет'}\n"
        txt += f"Форма правления: {p.get('government', {}).get('type', 'нет')}\n"
        txt += settlement_info
        
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=player_main_kb(bot_data.get("ADMIN_ID") == user.id))
        return

    # ===== ПОКУПКА ТОВАРА =====
    if data and data.startswith("buy_"):
        try:
            idx = int(data.split("_", 1)[1])
        except:
            await query.answer("Ошибка.")
            return
        if idx < 0 or idx >= len(shop):
            await query.answer("Товар не найден или уже продан.")
            return
        item = shop[idx]
        buyer = players.get(uid)
        if not buyer:
            await query.answer("Сначала /start")
            return
        price = item["price"]
        current_caps = buyer.get("caps", 0)
        if current_caps < price:
            await query.answer(f"Недостаточно крышек. Нужно: {price}, у вас: {current_caps}")
            return
        seller_id = str(item["owner_id"])
        seller = players.get(seller_id)
        if seller_id == uid:
            await query.answer("Нельзя купить свой же товар!")
            return
        buyer["caps"] = current_caps - price
        if seller:
            seller["caps"] = seller.get("caps", 0) + price
        buyer.setdefault("storage", []).append(f"Куплено: {item['title']}")
        sold = shop.pop(idx)
        await query.answer("Куплено!")
        await ctx.bot.send_message(chat_id=int(uid),
                                   text=f"Ты купил '{sold['title']}' за {price} крышек. Баланс: {buyer['caps']}. Товар добавлен в склад.")
        if seller:
            try:
                await ctx.bot.send_message(chat_id=int(seller_id),
                                           text=f"Твой товар '{sold['title']}' продан за {price} крышек. Баланс: {seller['caps']}.")
            except:
                pass
        add_log(ctx, f"Игрок {user.first_name} купил '{sold['title']}' у {seller_id} за {price}")
        save_data(ctx)
        group_id = bot_data.get("group_chat_id")
        if group_id:
            try:
                await ctx.bot.send_message(chat_id=group_id, text=shop_message_text(shop),
                                           reply_markup=make_shop_keyboard(shop))
            except:
                pass
        return

    # ===== ПЕРЕВОД КРЫШЕК =====
    if data == "player_transfer":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        factions = set()
        for p in players.values():
            if p.get("faction") and p.get("faction") != player.get("faction"):
                factions.add(p["faction"])
        if not factions:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет других фракций для перевода.")
            return
        kb = []
        faction_list = sorted(factions)
        ctx.user_data["transfer_factions"] = faction_list
        for i, f in enumerate(faction_list):
            kb.append([InlineKeyboardButton(f, callback_data=f"transfer_faction_{i}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_profile")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выберите фракцию получателя:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("transfer_faction_"):
        try:
            index = int(data.split("_", 2)[2])
        except:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка выбора фракции.")
            return
        faction_list = ctx.user_data.get("transfer_factions", [])
        if index < 0 or index >= len(faction_list):
            await ctx.bot.send_message(chat_id=int(uid), text="Фракция не найдена.")
            return
        target_faction = faction_list[index]
        candidates = []
        for pid, p in players.items():
            if p.get("faction") == target_faction and pid != uid:
                candidates.append((pid, p.get("first_name", "Неизвестный")))
        if not candidates:
            await ctx.bot.send_message(chat_id=int(uid), text="В этой фракции нет игроков.")
            return
        kb = []
        for pid, name in candidates:
            kb.append([InlineKeyboardButton(name, callback_data=f"transfer_recipient_{pid}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_transfer")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выберите получателя:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("transfer_recipient_"):
        recipient_id = data.split("_", 2)[2]
        ctx.user_data["transfer_recipient"] = recipient_id
        await ctx.bot.send_message(chat_id=int(uid), text="Введите сумму для перевода (целое число):")
        ctx.user_data["awaiting_transfer_amount"] = True
        return

    # ===== ДИПЛОМАТИЯ =====
    if data == "player_diplomacy":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        kb = [
            [InlineKeyboardButton("📜 Информация о договорах", callback_data="diplo_info")],
            [InlineKeyboardButton("🤝 Новое предложение", callback_data="diplo_new")],
            [InlineKeyboardButton("Назад", callback_data="player_profile")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text="Дипломатия:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "diplo_info":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        my_faction = player.get("faction")
        if not my_faction:
            await ctx.bot.send_message(chat_id=int(uid), text="У вас нет фракции.")
            return
        treaties = bot_data.get("active_treaties", {})
        my_treaties = []
        for tid, t in treaties.items():
            if my_faction in t.get("factions", []):
                my_treaties.append((tid, t))
        if not my_treaties:
            await ctx.bot.send_message(chat_id=int(uid), text="У вашей фракции нет активных договоров.")
            return
        text = "📜 Активные договоры вашей фракции:\n\n"
        kb = []
        for tid, t in my_treaties:
            other_faction = [f for f in t["factions"] if f != my_faction][0]
            type_name = {
                "pact": "Пакт о ненападении",
                "war": "Война" + (" (ожидание)" if t.get("pending") else ""),
                "military": "Военный союз",
                "trade": "Торговый союз"
            }.get(t["type"], t["type"])
            if t.get("pending"):
                start_after = t.get("start_after", 0)
                start_str = time.ctime(start_after) if start_after else "скоро"
                text += f"• {type_name} с {other_faction}\n  начнётся {start_str}\n\n"
            else:
                end_str = time.ctime(t["end"]) if t.get("end") else "бессрочно"
                text += f"• {type_name} с {other_faction}\n  до {end_str}\n\n"
            kb.append([InlineKeyboardButton(f"Расторгнуть {type_name} с {other_faction}", callback_data=f"diplo_cancel_{tid}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_diplomacy")])
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "diplo_new":
        factions = set()
        for pid, p in players.items():
            if pid != uid and p.get("faction"):
                factions.add(p["faction"])
        if not factions:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет других фракций для взаимодействия.")
            return
        kb = []
        faction_list = sorted(factions)
        ctx.user_data["diplo_factions"] = faction_list
        for i, f in enumerate(faction_list):
            kb.append([InlineKeyboardButton(f, callback_data=f"diplo_faction_{i}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_diplomacy")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выберите фракцию для предложения:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("diplo_faction_"):
        try:
            index = int(data.split("_", 2)[2])
        except:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка выбора.")
            return
        faction_list = ctx.user_data.get("diplo_factions", [])
        if index < 0 or index >= len(faction_list):
            await ctx.bot.send_message(chat_id=int(uid), text="Фракция не найдена.")
            return
        target_faction = faction_list[index]
        ctx.user_data["diplo_target_faction"] = target_faction
        kb = [
            [InlineKeyboardButton("🕊 Пакт о ненападении", callback_data="diplo_pact")],
            [InlineKeyboardButton("⚔️ Объявить войну", callback_data="diplo_war")],
            [InlineKeyboardButton("🤝 Военный союз", callback_data="diplo_military")],
            [InlineKeyboardButton("💰 Торговый союз", callback_data="diplo_trade")],
            [InlineKeyboardButton("Назад", callback_data="diplo_new")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=f"Выберите тип договора с фракцией {target_faction}:",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return

    if data in ("diplo_pact", "diplo_war", "diplo_military", "diplo_trade"):
        treaty_type = data.split("_")[1]
        target_faction = ctx.user_data.get("diplo_target_faction")
        if not target_faction:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка: выберите фракцию заново.")
            return
        targets = []
        for pid, p in players.items():
            if pid != uid and p.get("faction") == target_faction:
                targets.append(pid)
        if not targets:
            await ctx.bot.send_message(chat_id=int(uid), text="В этой фракции нет игроков.")
            return

        if treaty_type == "war":
            treaty_id = uuid.uuid4().hex[:16]
            duration = bot_data["diplomacy_config"].get("war", 2)
            start_after = time.time() + duration * 24 * 3600
            bot_data["active_treaties"][treaty_id] = {
                "type": "war",
                "factions": [players[uid].get("faction"), target_faction],
                "start": None,
                "start_after": start_after,
                "end": None,
                "pending": True,
                "participants": [uid] + targets
            }
            save_data(ctx)
            from_name = players[uid].get("faction") or players[uid].get("first_name")
            for pid in [uid] + targets:
                try:
                    if pid == uid:
                        msg = f"⚔️ Вы объявили войну фракции {target_faction}. Военные действия начнутся через {duration} дня(ей)."
                    else:
                        msg = f"⚔️ Фракция {from_name} объявила вам войну. Военные действия начнутся через {duration} дня(ей)."
                    await ctx.bot.send_message(chat_id=int(pid), text=msg)
                except Exception as e:
                    logger.error(f"Не удалось уведомить игрока {pid} о войне: {e}")
            if ctx.application.job_queue:
                schedule_war_start(ctx.application.job_queue, treaty_id, duration)
            else:
                logger.error("JobQueue отсутствует, война не начнётся автоматически.")
            add_log(ctx, f"Игрок {from_name} ({uid}) объявил войну фракции {target_faction} (начнётся через {duration} дн.)")
            if admin_id:
                try:
                    await ctx.bot.send_message(
                        chat_id=int(admin_id),
                        text=f"⚔️ Фракция {from_name} объявила войну фракции {target_faction}. Военные действия начнутся через {duration} дня(ей)."
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа о войне: {e}")
        else:
            proposal_id = uuid.uuid4().hex[:16]
            bot_data["pending_diplomacy"][proposal_id] = {
                "from_id": uid,
                "from_faction": players[uid].get("faction"),
                "to_faction": target_faction,
                "to_ids": targets,
                "type": treaty_type,
                "timestamp": time.time()
            }
            save_data(ctx)

            for pid in targets:
                try:
                    from_name = players[uid].get("faction") or players[uid].get("first_name")
                    type_name = {
                        "pact": "Пакт о ненападении",
                        "military": "Военный союз",
                        "trade": "Торговый союз"
                    }.get(treaty_type, treaty_type)
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Принять", callback_data=f"diplo_accept_{proposal_id}")],
                        [InlineKeyboardButton("❌ Отклонить", callback_data=f"diplo_reject_{proposal_id}")]
                    ])
                    await ctx.bot.send_message(
                        chat_id=int(pid),
                        text=f"📩 Фракция {from_name} предлагает вам:\n\n{type_name}\n\nЕсли вы примете, договор вступит в силу.",
                        reply_markup=kb
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить предложение игроку {pid}: {e}")

            await ctx.bot.send_message(chat_id=int(uid), text="✅ Предложение отправлено. Ожидайте ответа.")
            add_log(ctx, f"Игрок {players[uid].get('faction')} ({uid}) предложил {treaty_type} фракции {target_faction}")
        return

    if data.startswith("diplo_accept_"):
        proposal_id = data.split("_", 2)[2]
        proposal = bot_data["pending_diplomacy"].get(proposal_id)
        if not proposal:
            await query.answer("Предложение устарело или уже обработано.")
            return
        if uid not in proposal["to_ids"]:
            await query.answer("Это предложение не для вас.")
            return

        from_player = players.get(proposal["from_id"])
        if not from_player:
            await ctx.bot.send_message(chat_id=int(uid), text="Отправитель больше не в игре.")
            del bot_data["pending_diplomacy"][proposal_id]
            save_data(ctx)
            return

        treaty_id = uuid.uuid4().hex[:16]
        duration = bot_data["diplomacy_config"].get(proposal["type"], 3)
        end_time = time.time() + duration * 24 * 3600
        bot_data["active_treaties"][treaty_id] = {
            "type": proposal["type"],
            "factions": [proposal["from_faction"], proposal["to_faction"]],
            "start": time.time(),
            "end": end_time,
            "pending": False,
            "participants": [proposal["from_id"]] + proposal["to_ids"]
        }
        del bot_data["pending_diplomacy"][proposal_id]
        save_data(ctx)

        type_name = {
            "pact": "Пакт о ненападении",
            "military": "Военный союз",
            "trade": "Торговый союз"
        }.get(proposal["type"], proposal["type"])
        msg = f"🤝 Договор '{type_name}' между фракциями {proposal['from_faction']} и {proposal['to_faction']} вступил в силу до {time.ctime(end_time)}."
        for pid in [proposal["from_id"]] + proposal["to_ids"]:
            try:
                await ctx.bot.send_message(chat_id=int(pid), text=msg)
            except:
                pass

        if admin_id:
            await ctx.bot.send_message(chat_id=int(admin_id), text=f"📜 Заключён договор: {type_name}\n"
                                                                    f"Фракции: {proposal['from_faction']} и {proposal['to_faction']}\n"
                                                                    f"Действует до {time.ctime(end_time)}")
        return

    if data.startswith("diplo_reject_"):
        proposal_id = data.split("_", 2)[2]
        proposal = bot_data["pending_diplomacy"].get(proposal_id)
        if not proposal:
            await query.answer("Предложение уже обработано.")
            return
        if uid not in proposal["to_ids"]:
            await query.answer("Это предложение не для вас.")
            return

        del bot_data["pending_diplomacy"][proposal_id]
        save_data(ctx)

        try:
            await ctx.bot.send_message(chat_id=int(proposal["from_id"]),
                                       text=f"❌ Ваше предложение к фракции {proposal['to_faction']} было отклонено.")
        except:
            pass

        await ctx.bot.send_message(chat_id=int(uid), text="Вы отклонили предложение.")
        return

    if data.startswith("diplo_cancel_"):
        treaty_id = data.split("_", 2)[2]
        treaty = bot_data["active_treaties"].get(treaty_id)
        if not treaty:
            await query.answer("Договор не найден или уже расторгнут.")
            return
        player = players.get(uid)
        my_faction = player.get("faction")
        if my_faction not in treaty.get("factions", []):
            await query.answer("Этот договор не относится к вашей фракции.")
            return
        del bot_data["active_treaties"][treaty_id]
        save_data(ctx)
        other_faction = [f for f in treaty["factions"] if f != my_faction][0]
        type_name = {
            "pact": "Пакт о ненападении",
            "war": "Война",
            "military": "Военный союз",
            "trade": "Торговый союз"
        }.get(treaty["type"], treaty["type"])
        msg = f"⚠️ Фракция {my_faction} расторгла договор '{type_name}' с вашей фракцией."
        for pid in treaty.get("participants", []):
            if pid != uid:
                try:
                    await ctx.bot.send_message(chat_id=int(pid), text=msg)
                except:
                    pass
        if admin_id:
            await ctx.bot.send_message(
                chat_id=int(admin_id),
                text=f"📜 Фракция {my_faction} расторгла договор {type_name} с {other_faction}."
            )
        await query.answer("Договор расторгнут.")
        await ctx.bot.send_message(chat_id=int(uid), text="Договор расторгнут.")
        return
            # ===== ФОРМА ПРАВЛЕНИЯ =====
    if data == "player_government":
        player = players.get(uid)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Сначала /start")
            return
        gov = player.get("government")
        text = "🏛 Форма правления\n\n"
        if gov:
            last_change = gov.get("last_change", 0)
            time_passed = time.time() - last_change
            days_left = 2 - time_passed / (24*3600)
            text += f"Текущая форма: {gov['type']}\n"
            if days_left > 0:
                text += f"Сменить можно через {max(0, days_left):.1f} дней.\n\n"
            else:
                text += "Вы можете сменить форму.\n\n"
        else:
            text += "Выберите форму правления (смена возможна раз в 2 дня):\n\n"

        gov_config = bot_data.get("government_config", DEFAULT_GOVERNMENT_CONFIG)
        kb = []
        for gtype, params in gov_config.items():
            default_params = DEFAULT_GOVERNMENT_CONFIG.get(gtype, {})
            if gtype == "рабский_труд":
                caps_gain = params.get("caps_gain", default_params.get("caps_gain", 35))
                desc = f"Рабский труд: -10 людей, +{caps_gain} крышек/день"
            elif gtype == "людские_отношения":
                people_gain = params.get("people_gain", default_params.get("people_gain", 2))
                caps_cost = params.get("caps_cost", default_params.get("caps_cost", 25))
                desc = f"Людские отношения: +{people_gain} людей/день, -{caps_cost} крышек"
            elif gtype == "трудовые_отношения":
                goods_bonus = params.get("goods_bonus", default_params.get("goods_bonus", 10))
                caps_cost = params.get("caps_cost", default_params.get("caps_cost", 10))
                desc = f"Трудовые отношения: +{goods_bonus} товара/день, -{caps_cost} крышек"
            else:
                desc = gtype
            kb.append([InlineKeyboardButton(desc, callback_data=f"gov_select_{gtype}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="player_profile")])
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("gov_select_"):
        try:
            gov_type = data.split("_", 2)[2]
            player = players.get(uid)
            if not player:
                await ctx.bot.send_message(chat_id=int(uid), text="Ошибка.")
                return

            current_gov = player.get("government")
            if current_gov:
                last_change = current_gov.get("last_change", 0)
                if time.time() - last_change < 2 * 24 * 3600:
                    await ctx.bot.send_message(chat_id=int(uid), text="Вы можете менять форму правления не чаще раза в 2 дня.")
                    return

            gov_config = bot_data.get("government_config", DEFAULT_GOVERNMENT_CONFIG)
            params = gov_config.get(gov_type)
            if not params:
                await ctx.bot.send_message(chat_id=int(uid), text="Неизвестная форма.")
                return

            if gov_type == "рабский_труд":
                troops = player.get("troops", [])
                people_troop = None
                for t in troops:
                    if t["name"].lower() == "люди":
                        people_troop = t
                        break
                if not people_troop or people_troop["qty"] < 10:
                    await ctx.bot.send_message(chat_id=int(uid), text="Недостаточно людей для рабского труда (нужно минимум 10).")
                    return
                people_troop["qty"] -= 10
                if people_troop["qty"] <= 0:
                    troops.remove(people_troop)
            elif gov_type == "людские_отношения":
                cost = params.get("caps_cost", 25)
                if player.get("caps", 0) < cost:
                    await ctx.bot.send_message(chat_id=int(uid), text=f"Недостаточно крышек (нужно {cost}).")
                    return
                player["caps"] -= cost
            elif gov_type == "трудовые_отношения":
                cost = params.get("caps_cost", 10)
                if player.get("caps", 0) < cost:
                    await ctx.bot.send_message(chat_id=int(uid), text=f"Недостаточно крышек (нужно {cost}).")
                    return
                player["caps"] -= cost

            if current_gov:
                cancel_government_job(ctx.application.job_queue, uid)

            player["government"] = {"type": gov_type, "last_change": time.time()}
            save_data(ctx)

            job_queue = ctx.application.job_queue
            if job_queue:
                try:
                    gov_time_str = bot_data.get("government_time", "18:00")
                    hour, minute = map(int, gov_time_str.split(':'))
                    schedule_government_job(job_queue, uid, gov_type, dt_time(hour, minute))
                    await ctx.bot.send_message(chat_id=int(uid),
                                               text=f"✅ Вы выбрали форму правления: {gov_type}. Ежедневно в {hour:02d}:{minute:02d} вы будете получать её эффект.")
                except Exception as e:
                    logger.error(f"Ошибка планирования формы правления для {uid}: {e}")
                    await ctx.bot.send_message(chat_id=int(uid),
                                               text="⚠️ Форма правления установлена, но ежедневные эффекты не будут работать из-за ошибки. Обратитесь к администратору.")
            else:
                await ctx.bot.send_message(chat_id=int(uid),
                                           text="⚠️ Форма правления установлена, но ежедневные эффекты не будут работать из-за отсутствия планировщика.")

            add_log(ctx, f"Игрок {player.get('faction')} ({uid}) установил форму правления {gov_type}")

            if admin_id:
                try:
                    faction_name = player.get('faction') or 'Без фракции'
                    await ctx.bot.send_message(
                        chat_id=int(admin_id),
                        text=f"🏛 Игрок {faction_name} ({uid}) выбрал форму правления: {gov_type}."
                    )
                except Exception as e:
                    logger.error(f"Не удалось уведомить админа о выборе формы правления: {e}")

        except Exception as e:
            logger.exception(f"Ошибка при выборе формы правления игроком {uid}: {e}")
            await ctx.bot.send_message(chat_id=int(uid), text="Произошла ошибка. Попробуйте позже.")
        return

    if data == "noop":
        await query.answer()
        return

    # ===== ADMIN FLOW =====
    if data == "admin_open":
        if admin_id is None:
            ctx.user_data["awaiting_admin_password"] = True
            await ctx.bot.send_message(chat_id=int(uid), text="Введи пароль админа (текстом):")
            return
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="У тебя нет прав админа.")
            return
        await ctx.bot.send_message(chat_id=int(uid), text="Админ-панель:", reply_markup=admin_main_kb())
        return
            if data == "adm_players":
        if admin_id != user.id:
            ctx.user_data["awaiting_admin_password"] = True
            await ctx.bot.send_message(chat_id=int(uid), text="Введи пароль админа (текстом):")
            return
        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Игроков пока нет.")
            return
        kb = []
        for pid_str, info in players_map.items():
            faction = info.get('faction', 'не указана')
            caps = info.get('caps', 0)
            label = f"{info.get('first_name') or '-'} @{info.get('username') or '-'} ({faction}) - {caps}💠"
            kb.append([InlineKeyboardButton(label[:60], callback_data=f"adm_player_{pid_str}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="admin_open")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери игрока:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_player_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_", 2)[2]
        player = bot_data.get("players", {}).get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return

        faction = player.get('faction', 'не указана')
        caps = player.get('caps', 0)
        goods = player.get('goods', 0)
        troops = player.get('troops', [])
        storage = player.get('storage', [])
        base = player.get('base', [])
        focus = player.get('focus', [])
        actions = player.get('actions', [])
        production = player.get('production')
        gov = player.get('government')
        settlements = player.get('settlements', [])

        player_info = f"👤 Игрок: {player.get('first_name')} @{player.get('username')} (ID: {pid_str})\n"
        player_info += f"🏴 Фракция: {faction}\n"
        player_info += f"💠 Крышек: {caps}\n"
        player_info += f"📦 Товар: {goods}\n"
        player_info += f"🏘 Поселений: {len(settlements)}\n\n"

        player_info += f"⚔️ Войска ({len(troops)}):\n"
        if troops:
            for i, troop in enumerate(troops, 1):
                player_info += f"  {i}. {troop['name']} — {troop['qty']}\n"
        else:
            player_info += "  Нет войск\n"

        player_info += f"\n🏭 Производство: "
        if production:
            player_info += f"{production['type']}, занято людей: {production['people_used']}\n"
        else:
            player_info += "не активно\n"

        player_info += f"\n🏛 Форма правления: "
        if gov:
            player_info += f"{gov['type']}\n"
        else:
            player_info += "не выбрана\n"

        player_info += f"\n📦 Склад (записи): {len(storage)}"
        if storage:
            player_info += " (первые 3):\n"
            for i, item in enumerate(storage[:3], 1):
                player_info += f"  {i}. {item}\n"
            if len(storage) > 3:
                player_info += f"  ... и ещё {len(storage) - 3} записей\n"
        else:
            player_info += "\n  Склад пуст\n"

        kb = [
            [InlineKeyboardButton("Удалить игрока", callback_data=f"adm_delete_player_{pid_str}")],
            [InlineKeyboardButton("Выдать крышек", callback_data=f"adm_give_player_{pid_str}")],
            [InlineKeyboardButton("Отнять крышек", callback_data=f"adm_take_player_{pid_str}")],
            [InlineKeyboardButton("Выдать товар", callback_data=f"adm_give_goods_{pid_str}")],
            [InlineKeyboardButton("Забрать товар", callback_data=f"adm_take_goods_{pid_str}")],
            [InlineKeyboardButton("Выдать войска", callback_data=f"adm_give_troops_{pid_str}")],
            [InlineKeyboardButton("Забрать войска", callback_data=f"adm_take_troops_{pid_str}")],
            [InlineKeyboardButton("Управлять войсками", callback_data=f"adm_troops_{pid_str}")],
            [InlineKeyboardButton("Управлять производством", callback_data=f"adm_production_{pid_str}")],
            [InlineKeyboardButton("Управлять формой правления", callback_data=f"adm_government_{pid_str}")],
            [InlineKeyboardButton("Управлять поселениями", callback_data=f"adm_settlements_{pid_str}")],
            [InlineKeyboardButton("Назад", callback_data="adm_players")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=player_info, reply_markup=InlineKeyboardMarkup(kb))
        return

    # ===== ADMIN ТОВАР =====
    if data.startswith("adm_give_goods_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["awaiting_admin_give_goods"] = {"target": pid_str}
        await ctx.bot.send_message(chat_id=int(uid), text=f"Введите количество товара для выдачи игроку {pid_str}:")
        return

    if data.startswith("adm_take_goods_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["awaiting_admin_take_goods"] = {"target": pid_str}
        await ctx.bot.send_message(chat_id=int(uid), text=f"Введите количество товара для изъятия у игрока {pid_str}:")
        return

    # ===== ADMIN ПРОИЗВОДСТВО =====
    if data.startswith("adm_production_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        player = players.get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        prod = player.get("production")
        if prod:
            text = f"🏭 Производство игрока {pid_str}\nТип: {prod['type']}\nЗанято людей: {prod['people_used']}\n\nЧто хотите сделать?"
            kb = [
                [InlineKeyboardButton("Изменить параметры", callback_data=f"adm_prod_edit_{pid_str}")],
                [InlineKeyboardButton("Снять производство", callback_data=f"adm_prod_remove_{pid_str}")],
                [InlineKeyboardButton("Назад", callback_data=f"adm_player_{pid_str}")]
            ]
        else:
            text = f"🏭 У игрока {pid_str} нет активного производства."
            kb = [[InlineKeyboardButton("Назад", callback_data=f"adm_player_{pid_str}")]]
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_prod_remove_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        player = players.get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        await remove_production(player, pid_str, ctx)
        await ctx.bot.send_message(chat_id=int(uid), text="Производство снято, люди возвращены.")
        try:
            await ctx.bot.send_message(chat_id=int(pid_str), text="Админ снял ваше производство. Люди возвращены.")
        except:
            pass
        return

    if data.startswith("adm_prod_edit_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["adm_edit_prod"] = pid_str
        await ctx.bot.send_message(chat_id=int(uid),
                                   text="Введите новые параметры в формате: тип_труда количество_людей (например: легкий 10). Доступные типы: легкий, средний, тяжелый, усиленный.")
        return

    # ===== ADMIN ПОСЕЛЕНИЯ (исправленные) =====
    if data == "adm_settlements":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет игроков.")
            return
        
        kb = []
        for pid_str, player in players_map.items():
            faction = player.get('faction', 'не указана')
            label = f"{faction} ({pid_str})"
            kb.append([InlineKeyboardButton(label[:60], callback_data=f"adm_set_player_{pid_str}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="admin_open")])
        
        await ctx.bot.send_message(chat_id=int(uid), text="🏘 Выберите игрока для управления поселениями:",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_set_player_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        player = players.get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        
        settlements = player.get("settlements", [])
        
        txt = f"🏘 ПОСЕЛЕНИЯ ИГРОКА {player.get('first_name')}\n\n"
        txt += f"Всего поселений: {len(settlements)}\n\n"
        
        if settlements:
            for i, s in enumerate(settlements, 1):
                txt += f"{i}. {s.get('name', 'Без названия')} | Люди: {s.get('population', 0)} | Доход: {s.get('daily_income', 0)} крышек\n"
        
        kb = []
        for i, settlement in enumerate(settlements):
            name = settlement.get('name', f'Поселение {i+1}')
            kb.append([InlineKeyboardButton(f"🏘 {name}", callback_data=f"adm_set_manage_{pid_str}_{i}")])
        
        kb.append([InlineKeyboardButton("➕ Создать поселение", callback_data=f"adm_set_create_{pid_str}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="adm_settlements")])
        
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_set_manage_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        parts = data.split("_")
        if len(parts) < 5:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка формата кнопки.")
            return
        pid_str = parts[3]
        set_idx = int(parts[4])
        player = players.get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        settlements = player.get("settlements", [])
        if set_idx < 0 or set_idx >= len(settlements):
            await ctx.bot.send_message(chat_id=int(uid), text="Поселение не найдено.")
            return
        settlement = settlements[set_idx]
        name = settlement.get('name', 'Поселение')
        pop = settlement.get('population', 0)
        income = settlement.get('daily_income', 0)
        balance = settlement.get('balance', 0)
        
        txt = f"🏘 ПОСЕЛЕНИЕ: {name}\n\n"
        txt += f"Население: {pop}\n"
        txt += f"Ежедневный доход/налог: {income} крышек\n"
        txt += f"Баланс поселения: {balance} крышек\n"
        
        ctx.user_data["adm_set_current"] = (pid_str, set_idx)
        
        kb = [
            [InlineKeyboardButton("✏️ Изменить название", callback_data=f"adm_set_edit_name_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("👥 Добавить население", callback_data=f"adm_set_add_pop_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("👥 Забрать население", callback_data=f"adm_set_remove_pop_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("💰 Установить доход", callback_data=f"adm_set_set_income_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("➕ Добавить крышки", callback_data=f"adm_set_add_balance_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("➖ Забрать крышки", callback_data=f"adm_set_remove_balance_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("⏰ Установить время дохода", callback_data=f"adm_set_set_time_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("❌ Удалить поселение", callback_data=f"adm_set_delete_{pid_str}_{set_idx}")],
            [InlineKeyboardButton("Назад", callback_data=f"adm_set_player_{pid_str}")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_set_create_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["adm_set_create"] = pid_str
        await ctx.bot.send_message(chat_id=int(uid), text="Введите название для нового поселения:")
        return

    if data.startswith("adm_set_delete_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка формата кнопки.")
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        player = players.get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        settlements = player.get("settlements", [])
        if set_idx < 0 or set_idx >= len(settlements):
            await ctx.bot.send_message(chat_id=int(uid), text="Поселение не найдено.")
            return
        settlement = settlements[set_idx]
        cancel_settlement_income(ctx.application.job_queue, pid_str, set_idx)
        removed = settlements.pop(set_idx)
        save_data(ctx)
        await ctx.bot.send_message(chat_id=int(uid), text=f"❌ Поселение '{removed.get('name')}' удалено.")
        try:
            await ctx.bot.send_message(chat_id=int(pid_str), text=f"❌ Админ удалил ваше поселение '{removed.get('name')}'.")
        except:
            pass
        add_log(ctx, f"Админ {user.first_name} удалил поселение '{removed.get('name')}' у игрока {pid_str}")
        return

    if data.startswith("adm_set_edit_name_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        ctx.user_data["adm_set_edit_name"] = (pid_str, set_idx)
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новое название поселения:")
        return

    if data.startswith("adm_set_add_pop_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        ctx.user_data["adm_set_add_pop"] = (pid_str, set_idx)
        await ctx.bot.send_message(chat_id=int(uid), text="Введите количество людей для добавления:")
        return

    if data.startswith("adm_set_remove_pop_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        ctx.user_data["adm_set_remove_pop"] = (pid_str, set_idx)
        await ctx.bot.send_message(chat_id=int(uid), text="Введите количество людей для удаления:")
        return

    if data.startswith("adm_set_set_income_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        ctx.user_data["adm_set_set_income"] = (pid_str, set_idx)
        await ctx.bot.send_message(chat_id=int(uid), text="Введите ежедневный доход/налог (может быть отрицательным, например: -50):")
        return

    if data.startswith("adm_set_add_balance_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        ctx.user_data["adm_set_add_balance"] = (pid_str, set_idx)
        await ctx.bot.send_message(chat_id=int(uid), text="Введите количество крышек для добавления на баланс поселения:")
        return

    if data.startswith("adm_set_remove_balance_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        ctx.user_data["adm_set_remove_balance"] = (pid_str, set_idx)
        await ctx.bot.send_message(chat_id=int(uid), text="Введите количество крышек для вычитания из баланса поселения:")
        return

    if data.startswith("adm_set_set_time_"):
        if admin_id != user.id:
            return
        parts = data.split("_")
        if len(parts) < 6:
            return
        pid_str = parts[4]
        set_idx = int(parts[5])
        ctx.user_data["adm_set_set_time"] = (pid_str, set_idx)
        await ctx.bot.send_message(chat_id=int(uid), text="Введите время для ежедневного дохода в формате ЧЧ:ММ (например: 09:00):")
        return
            # ===== ADMIN ФОРМА ПРАВЛЕНИЯ =====
    if data.startswith("adm_government_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        player = players.get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        gov = player.get("government")
        if gov:
            await ctx.bot.send_message(chat_id=int(uid), text=f"У игрока уже есть форма правления: {gov['type']}. Чтобы изменить, используйте сброс через редактирование игрока.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="У игрока нет формы правления. Вы можете назначить её через редактирование.")
        return

    # ===== ADMIN ВОЙСКА =====
    if data.startswith("adm_give_troops_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["awaiting_admin_give_troops"] = {"target": pid_str}
        await ctx.bot.send_message(chat_id=int(uid),
                                   text=f"Введи количество войск для выдачи игроку {pid_str} (целое число):")
        return

    if data.startswith("adm_take_troops_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["awaiting_admin_take_troops"] = {"target": pid_str}
        await ctx.bot.send_message(chat_id=int(uid),
                                   text=f"Введи количество войск для изъятия у игрока {pid_str} (целое число):")
        return

    # ===== ADMIN МАГАЗИН =====
    if data == "adm_market":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return

        market_items = bot_data.get("market_items", [])
        if not market_items:
            await ctx.bot.send_message(
                chat_id=int(uid),
                text="Магазин пуст.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Добавить в магазин", callback_data="adm_market_add")],
                    [InlineKeyboardButton("Назад", callback_data="admin_open")]
                ])
            )
            return

        text = market_message_text(market_items)
        kb = []
        for i, item in enumerate(market_items, 1):
            kb.append([InlineKeyboardButton(f"Удалить #{i}", callback_data=f"adm_market_del_{i - 1}")])
        kb.append([InlineKeyboardButton("Добавить в магазин", callback_data="adm_market_add")])
        kb.append([InlineKeyboardButton("Назад", callback_data="admin_open")])

        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "adm_market_add":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        ctx.user_data["awaiting_market_item"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введи текст для добавления в магазин:")
        return

    if data.startswith("adm_market_del_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        idx = int(data.split("_")[-1])
        market_items = bot_data.get("market_items", [])
        if 0 <= idx < len(market_items):
            removed = market_items.pop(idx)
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text=f"Элемент '{removed}' удален из магазина.")
            add_log(ctx, f"Админ {user.first_name} удалил из магазина: {removed}")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет такого элемента.")
        return

    # ===== ADMIN ОТПРАВКА ХОДА =====
    if data == "adm_send_turn":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return

        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Игроков пока нет.")
            return

        kb = []
        for pid_str, info in players_map.items():
            faction = info.get('faction', 'не указана')
            label = f"{info.get('first_name') or '-'} ({faction})"
            kb.append([InlineKeyboardButton(label[:60], callback_data=f"adm_send_turn_to_{pid_str}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="admin_open")])

        await ctx.bot.send_message(chat_id=int(uid), text="Выбери игрока для отправки хода:",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_send_turn_to_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        player = bot_data.get("players", {}).get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return

        faction = player.get('faction', 'не указана')
        player_name = player.get('first_name', 'Игрок')

        kb = [
            [InlineKeyboardButton("Отправить сразу", callback_data=f"adm_send_immediately_{pid_str}")],
            [InlineKeyboardButton("Назад", callback_data="adm_send_turn")]
        ]

        await ctx.bot.send_message(
            chat_id=int(uid),
            text=f"Выбран игрок: {player_name} (Фракция: {faction})\nВыбери тип отправки:",
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return

    if data.startswith("adm_send_immediately_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["awaiting_turn_message"] = {"player_id": pid_str}
        await ctx.bot.send_message(chat_id=int(uid), text="Введи сообщение для отправки:")
        return

    # ===== ADMIN ИНФОРМАЦИЯ =====
    if data == "adm_all_troops":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return

        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Игроков пока нет.")
            return

        troops_info = "⚔️ Войска всех фракций:\n\n"

        for pid_str, player in players_map.items():
            faction = player.get('faction', 'не указана')
            player_name = player.get('first_name', 'Неизвестный')
            troops = player.get('troops', [])

            troops_info += f"🏴 {player_name} ({faction}):\n"
            if troops:
                total_troops = sum(troop.get('qty', 0) for troop in troops)
                troops_info += f"  Всего войск: {total_troops}\n"
                for troop in troops:
                    troops_info += f"  • {troop['name']}: {troop['qty']}\n"
            else:
                troops_info += "  Нет войск\n"
            troops_info += "\n"

        if len(troops_info) > 4000:
            parts = [troops_info[i:i + 4000] for i in range(0, len(troops_info), 4000)]
            for part in parts:
                await ctx.bot.send_message(chat_id=int(uid), text=part)
        else:
            await ctx.bot.send_message(chat_id=int(uid), text=troops_info)

        kb = [[InlineKeyboardButton("Назад", callback_data="admin_open")]]
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери действие:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "adm_all_goods":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет игроков.")
            return
        lines = ["📦 Товары всех фракций:\n"]
        for pid, p in players_map.items():
            faction = p.get('faction') or 'не указана'
            goods = p.get('goods', 0)
            lines.append(f"• {faction} ({pid}): {goods} ед.")
        text = "\n".join(lines)
        await ctx.bot.send_message(chat_id=int(uid), text=text)
        return

    if data == "adm_all_governments":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет игроков.")
            return
        lines = ["🏛 Формы правления всех фракций:\n"]
        for pid, p in players_map.items():
            faction = p.get('faction') or 'не указана'
            gov = p.get('government')
            if gov:
                gov_type = gov.get('type', 'неизвестно')
                lines.append(f"• {faction} ({pid}): {gov_type}")
            else:
                lines.append(f"• {faction} ({pid}): нет")
        text = "\n".join(lines)
        await ctx.bot.send_message(chat_id=int(uid), text=text)
        return

    if data == "adm_all_treaties":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        treaties = bot_data.get("active_treaties", {})
        if not treaties:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет активных договоров.")
            return
        lines = ["🤝 Все активные дипломатические договоры:\n"]
        for tid, t in treaties.items():
            f1, f2 = t.get("factions", ["?", "?"])
            type_name = {
                "pact": "Пакт о ненападении",
                "war": "Война" + (" (ожидание)" if t.get("pending") else ""),
                "military": "Военный союз",
                "trade": "Торговый союз"
            }.get(t.get("type"), t.get("type"))
            if t.get("pending"):
                start_after = t.get("start_after", 0)
                start_str = time.ctime(start_after) if start_after else "скоро"
                lines.append(f"• {type_name}: {f1} <-> {f2} (начнётся {start_str})")
            else:
                end_str = time.ctime(t.get("end", 0)) if t.get("end") else "бессрочно"
                lines.append(f"• {type_name}: {f1} <-> {f2} до {end_str}")
        text = "\n".join(lines)
        await ctx.bot.send_message(chat_id=int(uid), text=text)
        return

    if data == "adm_all_productions":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет игроков.")
            return
        lines = ["🏭 Производство всех фракций:\n"]
        for pid, p in players_map.items():
            faction = p.get('faction') or 'не указана'
            prod = p.get('production')
            if prod:
                prod_type = prod.get('type', 'неизвестно')
                lines.append(f"• {faction} ({pid}): {prod_type}")
            else:
                lines.append(f"• {faction} ({pid}): нет")
        text = "\n".join(lines)
        await ctx.bot.send_message(chat_id=int(uid), text=text)
        return

    # ===== ADMIN НАСТРОЙКИ =====
    if data == "adm_set_goods_price":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        ctx.user_data["awaiting_goods_price"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новую цену за единицу товара (целое число):")
        return

    if data == "adm_set_production_time":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        ctx.user_data["awaiting_production_time"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новое время для производства в формате ЧЧ:ММ (например, 18:00):")
        return

    if data == "adm_set_government_time":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        ctx.user_data["awaiting_government_time"] = True
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новое время для формы правления в формате ЧЧ:ММ (например, 18:00):")
        return

    if data == "adm_diplomacy":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        config = bot_data.get("diplomacy_config", DEFAULT_DIPLOMACY_DURATION)
        text = "⚙️ Настройки дипломатии (длительность в днях):\n\n"
        text += f"🕊 Пакт о ненападении: {config.get('pact', 3)} дней\n"
        text += f"⚔️ Война (до начала): {config.get('war', 2)} дней\n"
        text += f"🤝 Военный союз: {config.get('military', 3)} дней\n"
        text += f"💰 Торговый союз: {config.get('trade', 3)} дней\n\n"
        kb = [
            [InlineKeyboardButton("Изменить пакт", callback_data="adm_diplo_set_pact")],
            [InlineKeyboardButton("Изменить войну", callback_data="adm_diplo_set_war")],
            [InlineKeyboardButton("Изменить военный союз", callback_data="adm_diplo_set_military")],
            [InlineKeyboardButton("Изменить торговый союз", callback_data="adm_diplo_set_trade")],
            [InlineKeyboardButton("Назад", callback_data="admin_open")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data == "adm_diplo_set_pact":
        if admin_id != user.id:
            return
        ctx.user_data["adm_diplo_setting"] = "pact"
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новую длительность пакта о ненападении (в днях):")
        return

    if data == "adm_diplo_set_war":
        if admin_id != user.id:
            return
        ctx.user_data["adm_diplo_setting"] = "war"
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новую длительность до начала войны (в днях):")
        return

    if data == "adm_diplo_set_military":
        if admin_id != user.id:
            return
        ctx.user_data["adm_diplo_setting"] = "military"
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новую длительность военного союза (в днях):")
        return

    if data == "adm_diplo_set_trade":
        if admin_id != user.id:
            return
        ctx.user_data["adm_diplo_setting"] = "trade"
        await ctx.bot.send_message(chat_id=int(uid), text="Введите новую длительность торгового союза (в днях):")
        return

    if data == "adm_government":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        config = bot_data.get("government_config", DEFAULT_GOVERNMENT_CONFIG)
        text = "⚙️ Текущие параметры форм правления:\n\n"
        for gtype, params in config.items():
            if gtype == "рабский_труд":
                text += f"Рабский труд: людей -10, крышек +{params.get('caps_gain', 35)} в день\n"
            elif gtype == "людские_отношения":
                text += f"Людские отношения: людей +{params.get('people_gain', 2)} в день, крышек -{params.get('caps_cost', 25)}\n"
            elif gtype == "трудовые_отношения":
                text += f"Трудовые отношения: товара +{params.get('goods_bonus', 10)} в день, крышек -{params.get('caps_cost', 10)}\n"
        kb = [
            [InlineKeyboardButton("Изменить рабский труд", callback_data="adm_gov_edit_рабский_труд")],
            [InlineKeyboardButton("Изменить людские отношения", callback_data="adm_gov_edit_людские_отношения")],
            [InlineKeyboardButton("Изменить трудовые отношения", callback_data="adm_gov_edit_трудовые_отношения")],
            [InlineKeyboardButton("Назад", callback_data="admin_open")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=text, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_gov_edit_"):
        if admin_id != user.id:
            return
        gov_type = data.split("_", 3)[3]
        ctx.user_data["adm_gov_editing"] = gov_type
        if gov_type == "рабский_труд":
            await ctx.bot.send_message(chat_id=int(uid), text="Введите новые параметры для рабского труда в формате: крышек_в_день (например: 40)")
        elif gov_type == "людские_отношения":
            await ctx.bot.send_message(chat_id=int(uid), text="Введите новые параметры для людских отношений в формате: людей_в_день стоимость_крышек (например: 3 30)")
        elif gov_type == "трудовые_отношения":
            await ctx.bot.send_message(chat_id=int(uid), text="Введите новые параметры для трудовых отношений в формате: товара_в_день стоимость_крышек (например: 15 15)")
        return

    # ===== ADMIN ВОЙСКА (управление) =====
    if data.startswith("adm_troops_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        player = bot_data.get("players", {}).get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        troops = player.get("troops", [])
        txt = f"⚔️ ВОЙСКА\n\n{format_troops(troops)}"
        kb = []
        for i, t in enumerate(troops, 1):
            kb.append([InlineKeyboardButton(f"{i}. {t['name']} ({t['qty']})",
                                            callback_data=f"adm_troop_item_{pid_str}_{i - 1}")])
        kb.append([InlineKeyboardButton("Добавить войско", callback_data=f"adm_troop_add_{pid_str}")])
        kb.append([InlineKeyboardButton("Назад", callback_data=f"adm_player_{pid_str}")])
        await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_troop_add_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["awaiting_admin_add_troop"] = {"target": pid_str}
        await ctx.bot.send_message(chat_id=int(uid),
                                   text=f"Введи новое войско для игрока {pid_str} в формате: Название Кол-во")
        return

    if data.startswith("adm_troop_item_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        parts = data.split("_")
        if len(parts) < 5:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка в формате команды.")
            return
        pid_str = parts[3]
        idx = int(parts[4])
        player = bot_data.get("players", {}).get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        troops = player.get("troops", [])
        if idx < 0 or idx >= len(troops):
            await ctx.bot.send_message(chat_id=int(uid), text="Войско не найдено.")
            return
        t = troops[idx]
        kb = [
            [InlineKeyboardButton("Изменить", callback_data=f"adm_troop_edit_{pid_str}_{idx}")],
            [InlineKeyboardButton("Удалить", callback_data=f"adm_troop_del_{pid_str}_{idx}")],
            [InlineKeyboardButton("Назад", callback_data=f"adm_troops_{pid_str}")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text=f"Войско #{idx + 1}: {t['name']} — {t['qty']}",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_troop_edit_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        parts = data.split("_")
        if len(parts) < 5:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка в формате команды.")
            return
        pid_str = parts[3]
        idx = int(parts[4])
        ctx.user_data["awaiting_admin_edit_troop"] = {"target": pid_str, "index": idx}
        await ctx.bot.send_message(chat_id=int(uid), text="Введи новое значение: Название Кол-во")
        return

    if data.startswith("adm_troop_del_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        parts = data.split("_")
        if len(parts) < 5:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка в формате команды.")
            return
        pid_str = parts[3]
        idx = int(parts[4])
        player = bot_data.get("players", {}).get(pid_str)
        if not player:
            await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
            return
        troops = player.get("troops", [])
        if 0 <= idx < len(troops):
            removed = troops.pop(idx)
            add_log(ctx, f"Админ {user.first_name} удалил войско игрока {pid_str}: {removed}")
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text="Войско удалено.")
            try:
                await ctx.bot.send_message(chat_id=int(pid_str), text=f"Админ удалил твоё войско: {removed['name']}")
            except:
                pass
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет такого войска.")
        return

    # ===== ADMIN ХРАНИЛИЩА, БАЗЫ, ФОКУСА, ХОДА (обобщённые) =====
    if data.startswith("adm_storage_") or data.startswith("adm_base_") or data.startswith("adm_focus_") or data.startswith("adm_actions_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        parts = data.split("_")
        if len(parts) < 3:
            await ctx.bot.send_message(chat_id=int(uid), text="Ошибка в формате команды.")
            return
        typ = parts[1]
        if parts[2].startswith("item_") or parts[2].startswith("add_") or parts[2].startswith("edit_") or parts[2].startswith("del_"):
            # Обработка подменю
            if parts[2] == "add_":
                pid_str = parts[-1] if len(parts) == 4 else None
                if not pid_str:
                    await ctx.bot.send_message(chat_id=int(uid), text="Ошибка: не указан игрок.")
                    return
                ctx.user_data["awaiting_admin_add_item"] = {"target": pid_str, "type": typ}
                await ctx.bot.send_message(chat_id=int(uid), text=f"Введи текст для {typ}:")
                return
            elif parts[2].startswith("item_"):
                # формат: adm_{typ}_item_{pid}_{idx}
                if len(parts) < 5:
                    await ctx.bot.send_message(chat_id=int(uid), text="Ошибка формата.")
                    return
                pid_str = parts[3]
                idx = int(parts[4])
                player = bot_data.get("players", {}).get(pid_str)
                if not player:
                    await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
                    return
                coll = player.get(typ, [])
                if not (0 <= idx < len(coll)):
                    await ctx.bot.send_message(chat_id=int(uid), text="Нет такого элемента.")
                    return
                item = coll[idx]
                kb = [
                    [InlineKeyboardButton("Изменить", callback_data=f"adm_{typ}_edit_{pid_str}_{idx}")],
                    [InlineKeyboardButton("Удалить", callback_data=f"adm_{typ}_del_{pid_str}_{idx}")],
                    [InlineKeyboardButton("Назад", callback_data=f"adm_{typ}_{pid_str}")]
                ]
                await ctx.bot.send_message(chat_id=int(uid), text=f"{item}", reply_markup=InlineKeyboardMarkup(kb))
                return
            elif parts[2].startswith("edit_"):
                # adm_{typ}_edit_{pid}_{idx}
                if len(parts) < 5:
                    await ctx.bot.send_message(chat_id=int(uid), text="Ошибка формата.")
                    return
                pid_str = parts[3]
                idx = int(parts[4])
                ctx.user_data["awaiting_admin_edit_item"] = {"target": pid_str, "type": typ, "index": idx}
                await ctx.bot.send_message(chat_id=int(uid), text="Введи новый текст:")
                return
            elif parts[2].startswith("del_"):
                if len(parts) < 5:
                    await ctx.bot.send_message(chat_id=int(uid), text="Ошибка формата.")
                    return
                pid_str = parts[3]
                idx = int(parts[4])
                player = bot_data.get("players", {}).get(pid_str)
                if not player:
                    await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
                    return
                coll = player.get(typ, [])
                if 0 <= idx < len(coll):
                    removed = coll.pop(idx)
                    add_log(ctx, f"Админ {user.first_name} удалил в {typ} игрока {pid_str}: {removed}")
                    save_data(ctx)
                    await ctx.bot.send_message(chat_id=int(uid), text="Элемент удалён.")
                else:
                    await ctx.bot.send_message(chat_id=int(uid), text="Нет такого элемента.")
                return
        else:
            # adm_{typ}_{pid} - показываем список
            pid_str = parts[2]
            player = bot_data.get("players", {}).get(pid_str)
            if not player:
                await ctx.bot.send_message(chat_id=int(uid), text="Игрок не найден.")
                return
            coll = player.setdefault(typ, [])
            txt = f"{typ.upper()}\n\n"
            if typ == "storage":
                txt += format_storage(coll)
            elif typ == "base":
                txt += format_base(coll)
            elif typ == "focus":
                txt += format_focus(coll)
            elif typ == "actions":
                txt += format_actions(coll)
            
            kb = []
            for i, item in enumerate(coll, 1):
                kb.append([InlineKeyboardButton(f"{i}. {item[:30]}{'...' if len(item) > 30 else ''}",
                                                callback_data=f"adm_{typ}_item_{pid_str}_{i - 1}")])
            kb.append([InlineKeyboardButton(f"Добавить в {typ}", callback_data=f"adm_{typ}_add_{pid_str}")])
            kb.append([InlineKeyboardButton("Назад", callback_data=f"adm_player_{pid_str}")])
            await ctx.bot.send_message(chat_id=int(uid), text=txt, reply_markup=InlineKeyboardMarkup(kb))
            return

    # ===== ADMIN ЛАВКА =====
    if data == "adm_shop":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        if not shop:
            await ctx.bot.send_message(chat_id=int(uid), text="Лавка пуста.")
            return
        kb = []
        for i, it in enumerate(shop, 1):
            kb.append(
                [InlineKeyboardButton(f"{i}. {it['title']} ({it['price']})", callback_data=f"adm_shop_item_{i - 1}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="admin_open")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выбери товар:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_shop_item_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        idx = int(data.split("_")[-1])
        if 0 <= idx < len(shop):
            it = shop[idx]
            kb = [
                [InlineKeyboardButton("Изменить (Название Цена)", callback_data=f"adm_shop_edit_{idx}")],
                [InlineKeyboardButton("Удалить", callback_data=f"adm_shop_del_{idx}")],
                [InlineKeyboardButton("Назад", callback_data="adm_shop")]
            ]
            await ctx.bot.send_message(chat_id=int(uid),
                                       text=f"#{idx + 1}: {it['title']} — {it['price']} (от {it.get('owner_name')})",
                                       reply_markup=InlineKeyboardMarkup(kb))
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет такого товара.")
        return

    if data.startswith("adm_shop_del_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        idx = int(data.split("_")[-1])
        if 0 <= idx < len(shop):
            removed = shop.pop(idx)
            add_log(ctx, f"Админ {user.first_name} удалил товар: {removed}")
            save_data(ctx)
            group_id = bot_data.get("group_chat_id")
            if group_id:
                try:
                    await ctx.bot.send_message(chat_id=group_id, text=shop_message_text(shop),
                                               reply_markup=make_shop_keyboard(shop))
                except:
                    pass
            await ctx.bot.send_message(chat_id=int(uid), text="Товар удалён.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет такого товара.")
        return

    if data.startswith("adm_shop_edit_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        idx = int(data.split("_")[-1])
        ctx.user_data["awaiting_admin_edit_shop"] = idx
        await ctx.bot.send_message(chat_id=int(uid), text="Введи новое значение: Название Цена")
        return

    # ===== ADMIN ЛОГИ =====
    if data and data.startswith("adm_logs_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        page = int(data.split("_")[2])
        logs = bot_data.get("logs", [])
        total_pages = max(1, (len(logs) + LOG_PAGE_SIZE - 1) // LOG_PAGE_SIZE)
        page = max(0, min(page, total_pages - 1))
        start = page * LOG_PAGE_SIZE
        block = logs[start:start + LOG_PAGE_SIZE]
        text_block = "\n".join(block) if block else "Логи пусты."

        keyboard = []
        start_page = max(0, page - 3)
        end_page = min(total_pages, start_page + 8)

        row = []
        for p in range(start_page, end_page):
            if p == page:
                row.append(InlineKeyboardButton(f"•{p + 1}•", callback_data=f"adm_logs_{p}"))
            else:
                row.append(InlineKeyboardButton(str(p + 1), callback_data=f"adm_logs_{p}"))
            if len(row) == 4:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"adm_logs_{page - 1}"))
        nav_buttons.append(InlineKeyboardButton(f"Стр {page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton("Вперёд ➡️", callback_data=f"adm_logs_{page + 1}"))
        keyboard.append(nav_buttons)

        keyboard.append([InlineKeyboardButton("🧹 Очистить логи", callback_data="adm_clear_logs")])
        keyboard.append([InlineKeyboardButton("Назад", callback_data="admin_open")])

        await ctx.bot.send_message(chat_id=int(uid), text=text_block, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data == "adm_clear_logs":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        bot_data["logs"] = []
        save_data(ctx)
        await ctx.bot.send_message(chat_id=int(uid), text="Логи очищены.")
        add_log(ctx, f"Админ {user.first_name} очистил логи")
        return

    if data == "adm_logout":
        if bot_data.get("ADMIN_ID") == user.id:
            bot_data["ADMIN_ID"] = None
            save_data(ctx)
            await ctx.bot.send_message(chat_id=int(uid), text="Вы вышли из админки.")
        else:
            await ctx.bot.send_message(chat_id=int(uid), text="Ты не админ.")
        return

    if data == "adm_scheduled_payments":
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        players_map = bot_data.get("players", {})
        if not players_map:
            await ctx.bot.send_message(chat_id=int(uid), text="Нет игроков.")
            return
        kb = []
        for pid_str, info in players_map.items():
            faction = info.get('faction', 'не указана')
            label = f"{info.get('first_name') or '-'} ({faction})"
            kb.append([InlineKeyboardButton(label[:60], callback_data=f"adm_sched_pay_player_{pid_str}")])
        kb.append([InlineKeyboardButton("Назад", callback_data="admin_open")])
        await ctx.bot.send_message(chat_id=int(uid), text="Выберите игрока для настройки плановых выплат:",
                                   reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_sched_pay_player_"):
        if admin_id != user.id:
            await ctx.bot.send_message(chat_id=int(uid), text="Только админ.")
            return
        pid_str = data.split("_")[-1]
        kb = [
            [InlineKeyboardButton("💰 Плановая выплата крышек", callback_data=f"adm_sched_pay_caps_{pid_str}")],
            [InlineKeyboardButton("📦 Плановая выплата товара", callback_data=f"adm_sched_pay_goods_{pid_str}")],
            [InlineKeyboardButton("Отменить выплату крышек", callback_data=f"adm_sched_cancel_caps_{pid_str}")],
            [InlineKeyboardButton("Отменить выплату товара", callback_data=f"adm_sched_cancel_goods_{pid_str}")],
            [InlineKeyboardButton("Назад", callback_data="adm_scheduled_payments")]
        ]
        await ctx.bot.send_message(chat_id=int(uid), text="Выберите тип выплаты:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("adm_sched_pay_caps_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["adm_sched_pay_caps"] = pid_str
        await ctx.bot.send_message(chat_id=int(uid),
                                   text=f"Введите количество крышек для ежедневной выплаты игроку {pid_str} (может быть отрицательным):")
        return

    if data.startswith("adm_sched_pay_goods_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        ctx.user_data["adm_sched_pay_goods"] = pid_str
        await ctx.bot.send_message(chat_id=int(uid),
                                   text=f"Введите количество товара для ежедневной выплаты игроку {pid_str} (может быть отрицательным):")
        return

    if data.startswith("adm_sched_cancel_caps_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        cancel_payment_job(ctx.application.job_queue, pid_str)
        await ctx.bot.send_message(chat_id=int(uid), text=f"Плановая выплата крышек для игрока {pid_str} отменена.")
        try:
            await ctx.bot.send_message(chat_id=int(pid_str), text="Ваша плановая выплата крышек отменена администратором.")
        except:
            pass
        return

    if data.startswith("adm_sched_cancel_goods_"):
        if admin_id != user.id:
            return
        pid_str = data.split("_")[-1]
        cancel_goods_job(ctx.application.job_queue, pid_str)
        await ctx.bot.send_message(chat_id=int(uid), text=f"Плановая выплата товара для игрока {pid_str} отменена.")
        try:
            await ctx.bot.send_message(chat_id=int(pid_str), text="Ваша плановая выплата товара отменена администратором.")
        except:
            pass
        return

    if data == "noop":
        await query.answer()
        return

    await ctx.bot.send_message(chat_id=int(uid), text="Неизвестная кнопка или функция в разработке.")
    # ===== ERROR HANDLER =====
async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception while handling an update:", exc_info=ctx.error)
    try:
        if update.effective_user:
            await ctx.bot.send_message(chat_id=update.effective_user.id, text="Произошла ошибка. Попробуй позже.")
    except:
        pass

# ===== MAIN =====
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.bot_data.update(load_data())

    # Восстанавливаем задания производства, формы правления и войны
    if app.job_queue is not None:
        players = app.bot_data.get("players", {})
        prod_time_str = app.bot_data.get("production_time", "18:00")
        gov_time_str = app.bot_data.get("government_time", "18:00")
        prod_hour, prod_minute = map(int, prod_time_str.split(':'))
        gov_hour, gov_minute = map(int, gov_time_str.split(':'))

        for pid, player in players.items():
            # Восстанавливаем производство
            prod = player.get("production")
            if prod:
                schedule_production_job(app.job_queue, pid, prod["type"], dt_time(prod_hour, prod_minute))
            
            # Восстанавливаем форму правления
            gov = player.get("government")
            if gov:
                schedule_government_job(app.job_queue, pid, gov["type"], dt_time(gov_hour, gov_minute))
            
            # Восстанавливаем поселения с доходом
            settlements = player.get("settlements", [])
            for set_idx, settlement in enumerate(settlements):
                if settlement.get("daily_income"):
                    schedule_settlement_income(app.job_queue, pid, set_idx, dt_time(18, 0))
        
        # Восстанавливаем задания начала войн
        treaties = app.bot_data.get("active_treaties", {})
        for tid, treaty in treaties.items():
            if treaty.get("type") == "war" and treaty.get("pending") and treaty.get("start_after"):
                delay = (treaty["start_after"] - time.time()) / (24*3600)
                if delay > 0:
                    schedule_war_start(app.job_queue, tid, delay)
        
        # Восстанавливаем плановые выплаты
        scheduled_payments = app.bot_data.get("scheduled_payments", {})
        for pid_str, info in scheduled_payments.items():
            if info.get("amount"):
                schedule_payment_job(app.job_queue, pid_str, info["amount"], dt_time(18, 0))
        
        scheduled_goods = app.bot_data.get("scheduled_goods", {})
        for pid_str, info in scheduled_goods.items():
            if info.get("quantity"):
                schedule_goods_job(app.job_queue, pid_str, info["quantity"], dt_time(18, 0))
    else:
        logger.warning("JobQueue не настроен. Производство, форма правления и войны по расписанию работать не будут.")

    # Handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setgroup", cmd_setgroup))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
