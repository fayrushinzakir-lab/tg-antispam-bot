# -*- coding: utf-8 -*-
"""
AntiSpam Moriarty Bot  —  версия 2
================================================
Что умеет:
  • Антиспам: invite-ссылки Telegram, сокращатели, спам-домены, фильтр стоп-слов,
    антифлуд (N сообщений за T секунд -> мут), проверка имён при входе.
  • Автоответы (ключевые слова): пишешь слово в чат -> бот отвечает заданным текстом.
    Пример: "банан" -> "300 руб". Слов и ответов можно завести сколько угодно.
  • Панель управления в ЛС с ботом (на кнопках) + текстовые команды.
    Управлять может ТОЛЬКО владелец (см. ADMIN_IDS). Все настройки правятся удалённо
    и сохраняются в config.json.

Запуск: переменная окружения BOT_TOKEN (токен от @BotFather).
ID владельца: переменная ADMIN_IDS (по умолчанию уже вписан твой ID).
"""

import os
import re
import sys
import json
import time
import copy
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ───────────────────────────────────────────────────────────────────────────
#  НАСТРОЙКИ ОКРУЖЕНИЯ
# ───────────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

# ID тех, кому разрешено управлять ботом (через запятую). По умолчанию — твой ID.
DEFAULT_ADMIN = "8387802287"
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", DEFAULT_ADMIN).replace(" ", "").split(",") if x
}

# Куда сохранять настройки. Если на Railway смонтирован Volume в /data — настройки
# переживут передеплой. Иначе пишем рядом (сбрасываются при пересборке контейнера).
DATA_DIR = os.environ.get("DATA_DIR") or ("/data" if os.path.isdir("/data") else ".")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

# ───────────────────────────────────────────────────────────────────────────
#  НАСТРОЙКИ ПО УМОЛЧАНИЮ  (правятся прямо из ЛС бота, файл менять не обязательно)
# ───────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    # Включение/выключение модулей
    "enabled": {
        "invites": True,        # блокировать invite-ссылки t.me/+, joinchat
        "shorteners": True,     # блокировать сокращатели (bit.ly и т.п.)
        "all_links": False,     # блокировать ВООБЩЕ любые ссылки от не-админов
        "spam_domains": True,   # блокировать домены из списка spam_links
        "words": True,          # фильтр стоп-слов
        "flood": True,          # антифлуд
        "name_check": True,     # бан при входе, если имя содержит спам
        "triggers": True,       # автоответы по ключевым словам
    },
    # Антифлуд
    "flood": {"limit": 5, "period": 10, "mute": 300},
    # Стоп-слова (если есть в сообщении — сообщение удаляется)
    "stop_words": [
        "казино", "casino", "крипт", "ставк", "букмекер",
        "заработок", "заработай", "инвестиц", "1xbet", "1win", "mostbet",
        "порно", "porn", "интим",
    ],
    # Дополнительные спам-домены (помимо встроенных сокращателей)
    "spam_links": [],
    # Ключевые слова -> ответ. Пример ниже можно удалить в панели.
    "triggers": {"банан": "300 руб"},
    # Режим срабатывания триггеров: "word" (целое слово) или "contains" (любое вхождение)
    "trigger_match": "word",
}

# Встроенный список сокращателей ссылок (для тумблера "Сокращатели")
SHORTENERS = {
    "bit.ly", "goo.gl", "tinyurl.com", "cutt.ly", "is.gd", "clck.ru",
    "vk.cc", "t.cn", "ow.ly", "rb.gy", "shorturl.at", "tiny.cc",
    "rebrand.ly", "surl.li", "qps.ru",
}

# Подписи модулей для меню тумблеров
FEATURES = [
    ("invites", "Invite-ссылки Telegram"),
    ("shorteners", "Сокращатели ссылок"),
    ("all_links", "Блокировать ВСЕ ссылки"),
    ("spam_domains", "Спам-домены из списка"),
    ("words", "Фильтр стоп-слов"),
    ("flood", "Антифлуд"),
    ("name_check", "Проверка имён при входе"),
    ("triggers", "Автоответы (ключевые слова)"),
]

# ───────────────────────────────────────────────────────────────────────────
#  ЛОГИ
# ───────────────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("antispam")

# ───────────────────────────────────────────────────────────────────────────
#  ХРАНЕНИЕ НАСТРОЕК
# ───────────────────────────────────────────────────────────────────────────


def _merge_defaults(data: dict) -> dict:
    """Добавляет недостающие ключи из DEFAULT_CONFIG в загруженный конфиг."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return cfg
    for k, v in data.items():
        if k == "enabled" and isinstance(v, dict):
            cfg["enabled"].update(v)
        elif k == "flood" and isinstance(v, dict):
            cfg["flood"].update(v)
        else:
            cfg[k] = v
    return cfg


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return _merge_defaults(json.load(f))
        except Exception as e:  # noqa: BLE001
            log.warning("Не удалось прочитать %s: %s — беру значения по умолчанию", CONFIG_PATH, e)
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось сохранить настройки: %s", e)


CONFIG = load_config()

# ───────────────────────────────────────────────────────────────────────────
#  СОСТОЯНИЕ В ПАМЯТИ
# ───────────────────────────────────────────────────────────────────────────

flood_store: dict = defaultdict(deque)        # (chat_id, user_id) -> очередь меток времени
_admin_cache: dict = {}                        # chat_id -> (ts, set(admin_ids))
ADMIN_CACHE_TTL = 300

URL_HINT_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|tg://)", re.IGNORECASE)

# ───────────────────────────────────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНОЕ
# ───────────────────────────────────────────────────────────────────────────


def is_owner(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def group_admin_ids(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> set:
    """ID администраторов чата (с кешем на 5 минут)."""
    now = time.time()
    cached = _admin_cache.get(chat_id)
    if cached and now - cached[0] < ADMIN_CACHE_TTL:
        return cached[1]
    ids: set = set()
    try:
        for a in await context.bot.get_chat_administrators(chat_id):
            ids.add(a.user.id)
    except Exception as e:  # noqa: BLE001
        log.debug("get_chat_administrators(%s): %s", chat_id, e)
    _admin_cache[chat_id] = (now, ids)
    return ids


async def is_exempt(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int) -> bool:
    """Владелец бота и админы чата не подпадают под антиспам."""
    if is_owner(user_id):
        return True
    return user_id in await group_admin_ids(context, chat_id)


def find_link_violation(text: str, cfg: dict):
    """Возвращает причину (строку), если в тексте запрещённая ссылка, иначе None."""
    t = text.lower()
    en = cfg["enabled"]

    if en.get("invites") and any(
        p in t for p in ("t.me/+", "t.me/joinchat", "telegram.me/+",
                          "telegram.me/joinchat", "joinchat/", "tg://join")
    ):
        return "invite-ссылка"

    if en.get("shorteners") and any(s in t for s in SHORTENERS):
        return "сокращённая ссылка"

    if en.get("spam_domains"):
        for d in cfg.get("spam_links", []):
            if d and d.lower() in t:
                return f"спам-домен ({d})"

    if en.get("all_links") and URL_HINT_RE.search(t):
        return "ссылка"

    return None


def find_word_violation(text: str, cfg: dict):
    t = text.lower()
    for w in cfg.get("stop_words", []):
        if w and w.lower() in t:
            return w
    return None


def match_trigger(text: str, cfg: dict):
    """Ищет подходящий ключ. Возвращает (ключ, ответ) или None.
    При нескольких совпадениях берём самый длинный ключ (более точный)."""
    triggers = cfg.get("triggers", {})
    if not triggers:
        return None
    mode = cfg.get("trigger_match", "word")
    low = text.lower()
    best = None
    for key, resp in triggers.items():
        kl = key.lower()
        hit = False
        if mode == "contains":
            hit = kl in low
        else:  # "word" — целое слово (работает и для кириллицы)
            try:
                hit = re.search(r"(?<!\w)" + re.escape(kl) + r"(?!\w)", low) is not None
            except re.error:
                hit = kl in low
        if hit and (best is None or len(kl) > len(best[0])):
            best = (kl, resp)
    return best


def check_flood(chat_id: int, user_id: int, cfg: dict) -> bool:
    f = cfg["flood"]
    now = time.time()
    dq = flood_store[(chat_id, user_id)]
    dq.append(now)
    while dq and now - dq[0] > f["period"]:
        dq.popleft()
    if len(dq) >= f["limit"]:
        dq.clear()
        return True
    return False


async def mute_user(context, chat_id: int, user_id: int, seconds: int):
    until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    await context.bot.restrict_chat_member(
        chat_id,
        user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=until,
    )


def mention(user) -> str:
    if user.username:
        return "@" + user.username
    return user.first_name or "пользователь"


# ───────────────────────────────────────────────────────────────────────────
#  ОБРАБОТКА СООБЩЕНИЙ В ГРУППАХ
# ───────────────────────────────────────────────────────────────────────────


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or user.is_bot:
        return

    text = msg.text or msg.caption or ""

    # Админы чата и владелец — без проверок, но автоответы для них работают
    if await is_exempt(context, chat.id, user.id):
        await maybe_send_trigger(update, context, text)
        return

    cfg = CONFIG

    # 1) Ссылки
    reason = find_link_violation(text, cfg)
    if reason:
        try:
            await msg.delete()
            log.info("Удалено (%s) от %s в чате %s", reason, user.id, chat.id)
        except Exception as e:  # noqa: BLE001
            log.debug("delete link msg: %s", e)
        return

    # 2) Стоп-слова
    if cfg["enabled"].get("words"):
        bad = find_word_violation(text, cfg)
        if bad:
            try:
                await msg.delete()
                log.info("Удалено (стоп-слово '%s') от %s", bad, user.id)
            except Exception as e:  # noqa: BLE001
                log.debug("delete word msg: %s", e)
            return

    # 3) Антифлуд
    if cfg["enabled"].get("flood") and check_flood(chat.id, user.id, cfg):
        try:
            await mute_user(context, chat.id, user.id, cfg["flood"]["mute"])
            await msg.reply_text(
                f"🔇 {mention(user)} замучен на {cfg['flood']['mute']} сек за флуд."
            )
            log.info("Мут за флуд: %s в чате %s", user.id, chat.id)
        except Exception as e:  # noqa: BLE001
            log.debug("mute flood: %s", e)
        return

    # 4) Автоответы (ключевые слова)
    await maybe_send_trigger(update, context, text)


async def maybe_send_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    if not CONFIG["enabled"].get("triggers"):
        return
    hit = match_trigger(text, CONFIG)
    if hit:
        try:
            await update.effective_message.reply_text(hit[1])
        except Exception as e:  # noqa: BLE001
            log.debug("send trigger: %s", e)


async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not CONFIG["enabled"].get("name_check"):
        return
    chat = update.effective_chat
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return
    for u in msg.new_chat_members:
        if u.is_bot:
            continue
        name = " ".join(filter(None, [u.first_name, u.last_name, u.username])).lower()
        if find_word_violation(name, CONFIG) or find_link_violation(name, CONFIG):
            try:
                await context.bot.ban_chat_member(chat.id, u.id)
                log.info("Бан при входе (спам в имени): %s", u.id)
            except Exception as e:  # noqa: BLE001
                log.debug("ban new member: %s", e)


# ───────────────────────────────────────────────────────────────────────────
#  ПАНЕЛЬ УПРАВЛЕНИЯ (КНОПКИ) — ТОЛЬКО ДЛЯ ВЛАДЕЛЬЦА
# ───────────────────────────────────────────────────────────────────────────


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data="m:status")],
        [InlineKeyboardButton("🔘 Функции", callback_data="m:toggles"),
         InlineKeyboardButton("⚙️ Антифлуд", callback_data="m:flood")],
        [InlineKeyboardButton("💬 Ключевые слова", callback_data="m:triggers")],
        [InlineKeyboardButton("🚫 Стоп-слова", callback_data="m:words"),
         InlineKeyboardButton("🔗 Спам-ссылки", callback_data="m:links")],
        [InlineKeyboardButton("ℹ️ Помощь", callback_data="m:help")],
    ])


def toggles_kb() -> InlineKeyboardMarkup:
    rows = []
    for key, label in FEATURES:
        on = CONFIG["enabled"].get(key, False)
        rows.append([InlineKeyboardButton(f"{'✅' if on else '❌'} {label}", callback_data=f"tg:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def triggers_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить ответ", callback_data="add:trigger")]]
    mode = CONFIG.get("trigger_match", "word")
    mode_label = "целое слово" if mode == "word" else "любое вхождение"
    rows.append([InlineKeyboardButton(f"🔁 Режим: {mode_label}", callback_data="mode:trig")])
    for i, k in enumerate(sorted(CONFIG["triggers"].keys())):
        v = CONFIG["triggers"][k]
        prev = (v[:18] + "…") if len(v) > 18 else v
        rows.append([InlineKeyboardButton(f"❌ {k} → {prev}", callback_data=f"dt:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить слово", callback_data="add:word")]]
    for i, w in enumerate(sorted(CONFIG["stop_words"])):
        rows.append([InlineKeyboardButton(f"❌ {w}", callback_data=f"dw:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def links_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить домен", callback_data="add:link")]]
    for i, d in enumerate(sorted(CONFIG["spam_links"])):
        rows.append([InlineKeyboardButton(f"❌ {d}", callback_data=f"dl:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def flood_kb() -> InlineKeyboardMarkup:
    f = CONFIG["flood"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Лимит сообщений: {f['limit']}", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:limit:-"),
         InlineKeyboardButton("➕", callback_data="fl:limit:+")],
        [InlineKeyboardButton(f"Период: {f['period']} сек", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:period:-"),
         InlineKeyboardButton("➕", callback_data="fl:period:+")],
        [InlineKeyboardButton(f"Длительность мута: {f['mute']} сек", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:mute:-"),
         InlineKeyboardButton("➕", callback_data="fl:mute:+")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def status_text() -> str:
    en = CONFIG["enabled"]
    f = CONFIG["flood"]
    lines = ["📊 Статус бота", ""]
    for key, label in FEATURES:
        lines.append(f"{'🟢' if en.get(key) else '🔴'} {label}")
    lines += [
        "",
        f"Антифлуд: {f['limit']} сообщ. / {f['period']} сек → мут {f['mute']} сек",
        f"Стоп-слов: {len(CONFIG['stop_words'])}",
        f"Спам-доменов: {len(CONFIG['spam_links'])}",
        f"Автоответов: {len(CONFIG['triggers'])}",
    ]
    return "\n".join(lines)


HELP_TEXT = (
    "ℹ️ Команды (работают только у тебя, в этом чате с ботом):\n\n"
    "/panel — открыть панель управления\n"
    "/status — текущие настройки\n\n"
    "Автоответы:\n"
    "/add слово = ответ — добавить (напр. /add банан = 300 руб)\n"
    "/del слово — удалить\n"
    "/list — список автоответов\n\n"
    "Стоп-слова:\n"
    "/addword слово · /delword слово · /words\n\n"
    "Спам-домены:\n"
    "/addlink домен · /dellink домен · /links\n\n"
    "Прочее:\n"
    "/id — узнать свой ID и ID чата\n\n"
    "В группе боту нужны права: удалять сообщения, "
    "блокировать и ограничивать участников."
)


async def safe_edit(query, text, kb):
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("safe_edit: %s", e)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not query:
        return
    if not is_owner(user.id):
        await query.answer("Недоступно", show_alert=True)
        return

    data = query.data or ""
    await query.answer()

    # Навигация по меню
    if data == "m:main":
        return await safe_edit(query, "🛠 Панель управления AntiSpam", main_menu_kb())
    if data == "m:status":
        return await safe_edit(query, status_text(), main_menu_kb())
    if data == "m:toggles":
        return await safe_edit(query, "🔘 Включение/выключение функций:", toggles_kb())
    if data == "m:triggers":
        return await safe_edit(query, "💬 Автоответы (слово → ответ):", triggers_kb())
    if data == "m:words":
        return await safe_edit(query, "🚫 Стоп-слова (сообщение с ними удаляется):", words_kb())
    if data == "m:links":
        return await safe_edit(query, "🔗 Спам-домены (помимо встроенных сокращателей):", links_kb())
    if data == "m:flood":
        return await safe_edit(query, "⚙️ Настройки антифлуда:", flood_kb())
    if data == "m:help":
        return await safe_edit(query, HELP_TEXT, main_menu_kb())

    if data == "noop":
        return

    # Тумблеры
    if data.startswith("tg:"):
        key = data[3:]
        CONFIG["enabled"][key] = not CONFIG["enabled"].get(key, False)
        save_config()
        return await safe_edit(query, "🔘 Включение/выключение функций:", toggles_kb())

    # Режим срабатывания триггеров
    if data == "mode:trig":
        CONFIG["trigger_match"] = "contains" if CONFIG.get("trigger_match") == "word" else "word"
        save_config()
        return await safe_edit(query, "💬 Автоответы (слово → ответ):", triggers_kb())

    # Антифлуд +/-
    if data.startswith("fl:"):
        _, field, sign = data.split(":")
        step = {"limit": 1, "period": 5, "mute": 60}[field]
        floor = {"limit": 2, "period": 5, "mute": 30}[field]
        delta = step if sign == "+" else -step
        CONFIG["flood"][field] = max(floor, CONFIG["flood"][field] + delta)
        save_config()
        return await safe_edit(query, "⚙️ Настройки антифлуда:", flood_kb())

    # Удаление элементов
    if data.startswith("dt:"):
        idx = int(data[3:])
        keys = sorted(CONFIG["triggers"].keys())
        if 0 <= idx < len(keys):
            CONFIG["triggers"].pop(keys[idx], None)
            save_config()
        return await safe_edit(query, "💬 Автоответы (слово → ответ):", triggers_kb())
    if data.startswith("dw:"):
        idx = int(data[3:])
        words = sorted(CONFIG["stop_words"])
        if 0 <= idx < len(words):
            CONFIG["stop_words"].remove(words[idx])
            save_config()
        return await safe_edit(query, "🚫 Стоп-слова:", words_kb())
    if data.startswith("dl:"):
        idx = int(data[3:])
        links = sorted(CONFIG["spam_links"])
        if 0 <= idx < len(links):
            CONFIG["spam_links"].remove(links[idx])
            save_config()
        return await safe_edit(query, "🔗 Спам-домены:", links_kb())

    # Запуск ввода нового значения
    if data == "add:trigger":
        context.user_data["await"] = "trigger"
        return await safe_edit(
            query,
            "Пришли строку в формате:\n\nслово = ответ\n\nНапример:\nбанан = 300 руб\n\n"
            "(или /cancel чтобы отменить)",
            None,
        )
    if data == "add:word":
        context.user_data["await"] = "word"
        return await safe_edit(query, "Пришли стоп-слово одним сообщением.\n(или /cancel)", None)
    if data == "add:link":
        context.user_data["await"] = "link"
        return await safe_edit(query, "Пришли домен, напр. example.com\n(или /cancel)", None)


# ───────────────────────────────────────────────────────────────────────────
#  КОМАНДЫ В ЛС
# ───────────────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_owner(user.id):
        await update.message.reply_text("🛠 Панель управления AntiSpam", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(
            "Это приватный антиспам-бот. Добавь меня в группу администратором, "
            "чтобы я следил за порядком."
        )


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text("🛠 Панель управления AntiSpam", reply_markup=main_menu_kb())


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text(status_text(), reply_markup=main_menu_kb())


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text(HELP_TEXT)


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.pop("await", None):
        await update.message.reply_text("Отменено.", reply_markup=main_menu_kb())


async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    c = update.effective_chat
    await update.message.reply_text(
        f"Твой ID: {u.id}\nID этого чата: {c.id}"
    )


def _args_text(update: Update) -> str:
    """Текст команды без самой команды."""
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    body = _args_text(update)
    if "=" not in body:
        await update.message.reply_text("Формат: /add слово = ответ")
        return
    key, resp = body.split("=", 1)
    key, resp = key.strip().lower(), resp.strip()
    if not key or not resp:
        await update.message.reply_text("Пусто. Формат: /add слово = ответ")
        return
    CONFIG["triggers"][key] = resp
    save_config()
    await update.message.reply_text(f"✅ Добавлено: «{key}» → «{resp}»", reply_markup=triggers_kb())


async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    key = _args_text(update).lower()
    if CONFIG["triggers"].pop(key, None) is not None:
        save_config()
        await update.message.reply_text(f"🗑 Удалено: «{key}»", reply_markup=triggers_kb())
    else:
        await update.message.reply_text("Такого ключа нет.")


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    if not CONFIG["triggers"]:
        await update.message.reply_text("Автоответов пока нет.", reply_markup=triggers_kb())
        return
    lines = [f"• {k} → {v}" for k, v in sorted(CONFIG["triggers"].items())]
    await update.message.reply_text("💬 Автоответы:\n" + "\n".join(lines), reply_markup=triggers_kb())


async def cmd_addword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    w = _args_text(update).lower()
    if not w:
        await update.message.reply_text("Формат: /addword слово")
        return
    if w not in CONFIG["stop_words"]:
        CONFIG["stop_words"].append(w)
        save_config()
    await update.message.reply_text(f"✅ Стоп-слово добавлено: {w}", reply_markup=words_kb())


async def cmd_delword(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    w = _args_text(update).lower()
    if w in CONFIG["stop_words"]:
        CONFIG["stop_words"].remove(w)
        save_config()
        await update.message.reply_text(f"🗑 Удалено: {w}", reply_markup=words_kb())
    else:
        await update.message.reply_text("Такого слова нет.")


async def cmd_words(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text(
        "🚫 Стоп-слова:\n" + (", ".join(sorted(CONFIG["stop_words"])) or "—"),
        reply_markup=words_kb(),
    )


async def cmd_addlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    d = _args_text(update).lower()
    if not d:
        await update.message.reply_text("Формат: /addlink домен")
        return
    if d not in CONFIG["spam_links"]:
        CONFIG["spam_links"].append(d)
        save_config()
    await update.message.reply_text(f"✅ Домен добавлен: {d}", reply_markup=links_kb())


async def cmd_dellink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    d = _args_text(update).lower()
    if d in CONFIG["spam_links"]:
        CONFIG["spam_links"].remove(d)
        save_config()
        await update.message.reply_text(f"🗑 Удалено: {d}", reply_markup=links_kb())
    else:
        await update.message.reply_text("Такого домена нет.")


async def cmd_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text(
        "🔗 Спам-домены:\n" + (", ".join(sorted(CONFIG["spam_links"])) or "—"),
        reply_markup=links_kb(),
    )


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Текст в ЛС — нужен для пошагового добавления через кнопки."""
    user = update.effective_user
    if not is_owner(user.id):
        return
    awaiting = context.user_data.get("await")
    if not awaiting:
        await update.message.reply_text("Открой панель: /panel")
        return
    text = (update.effective_message.text or "").strip()
    context.user_data.pop("await", None)

    if awaiting == "trigger":
        if "=" not in text:
            await update.message.reply_text("Нужен формат: слово = ответ. Попробуй снова через /panel.")
            return
        key, resp = text.split("=", 1)
        key, resp = key.strip().lower(), resp.strip()
        if key and resp:
            CONFIG["triggers"][key] = resp
            save_config()
            await update.message.reply_text(f"✅ Добавлено: «{key}» → «{resp}»", reply_markup=triggers_kb())
        else:
            await update.message.reply_text("Пусто. Попробуй снова через /panel.")
    elif awaiting == "word":
        w = text.lower()
        if w and w not in CONFIG["stop_words"]:
            CONFIG["stop_words"].append(w)
            save_config()
        await update.message.reply_text(f"✅ Стоп-слово: {w}", reply_markup=words_kb())
    elif awaiting == "link":
        d = text.lower()
        if d and d not in CONFIG["spam_links"]:
            CONFIG["spam_links"].append(d)
            save_config()
        await update.message.reply_text(f"✅ Домен: {d}", reply_markup=links_kb())


# ───────────────────────────────────────────────────────────────────────────
#  ОБРАБОТКА ОШИБОК
# ───────────────────────────────────────────────────────────────────────────


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Ошибка при обработке апдейта: %s", context.error)


# ───────────────────────────────────────────────────────────────────────────
#  СБОРКА И ЗАПУСК
# ───────────────────────────────────────────────────────────────────────────


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    private = filters.ChatType.PRIVATE

    # Команды (только в ЛС)
    app.add_handler(CommandHandler("start", cmd_start, filters=private))
    app.add_handler(CommandHandler(["panel", "settings", "menu"], cmd_panel, filters=private))
    app.add_handler(CommandHandler("status", cmd_status, filters=private))
    app.add_handler(CommandHandler("help", cmd_help, filters=private))
    app.add_handler(CommandHandler("cancel", cmd_cancel, filters=private))
    app.add_handler(CommandHandler("add", cmd_add, filters=private))
    app.add_handler(CommandHandler("del", cmd_del, filters=private))
    app.add_handler(CommandHandler("list", cmd_list, filters=private))
    app.add_handler(CommandHandler("addword", cmd_addword, filters=private))
    app.add_handler(CommandHandler("delword", cmd_delword, filters=private))
    app.add_handler(CommandHandler("words", cmd_words, filters=private))
    app.add_handler(CommandHandler("addlink", cmd_addlink, filters=private))
    app.add_handler(CommandHandler("dellink", cmd_dellink, filters=private))
    app.add_handler(CommandHandler("links", cmd_links, filters=private))
    app.add_handler(CommandHandler("id", cmd_id))  # работает где угодно

    # Кнопки панели
    app.add_handler(CallbackQueryHandler(on_callback))

    # Новые участники (проверка имени)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))

    # Сообщения в группах (антиспам + автоответы)
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & (filters.TEXT | filters.CAPTION) & ~filters.StatusUpdate.ALL,
        on_group_message,
    ))

    # Текст в ЛС (для пошагового добавления)
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_private_text))

    app.add_error_handler(on_error)
    return app


def main():
    if not BOT_TOKEN:
        print("❌ Не задан BOT_TOKEN. На Railway добавь переменную BOT_TOKEN с токеном от @BotFather.")
        sys.exit(1)
    log.info("Запуск бота. Владельцы: %s. Конфиг: %s", ADMIN_IDS, CONFIG_PATH)
    app = build_app()
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
