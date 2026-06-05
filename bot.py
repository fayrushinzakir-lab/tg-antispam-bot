# -*- coding: utf-8 -*-
"""
AntiSpam Moriarty Bot  —  версия 4
================================================
Антиспам + автоответы + панель в ЛС + модерация (варн/мут/бан/кик) + приветствие
+ привлечение людей: ссылка-приглашение, рассылка по всем группам, авто-промо по
  таймеру, постинг в группу.
+ выдача прав управления другим людям (менеджеры).

Запуск: переменная окружения BOT_TOKEN. Главный владелец: ADMIN_IDS (уже вписан твой ID).
"""

import os
import re
import sys
import json
import time
import copy
import html
import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

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
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# ───────────────────────────────────────────────────────────────────────────
#  ОКРУЖЕНИЕ
# ───────────────────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()

DEFAULT_ADMIN = "8387802287"
ADMIN_IDS = {
    int(x) for x in os.environ.get("ADMIN_IDS", DEFAULT_ADMIN).replace(" ", "").split(",") if x
}

DATA_DIR = os.environ.get("DATA_DIR") or ("/data" if os.path.isdir("/data") else ".")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

# ───────────────────────────────────────────────────────────────────────────
#  НАСТРОЙКИ ПО УМОЛЧАНИЮ
# ───────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "enabled": {
        "invites": True, "shorteners": True, "all_links": False, "spam_domains": True,
        "words": True, "flood": True, "name_check": True, "triggers": True,
    },
    "flood": {"limit": 5, "period": 10, "mute": 300},
    "stop_words": [
        "казино", "casino", "крипт", "ставк", "букмекер",
        "заработок", "заработай", "инвестиц", "1xbet", "1win", "mostbet",
        "порно", "porn", "интим",
    ],
    "spam_links": [],
    "triggers": {"банан": "300 руб"},
    "trigger_match": "word",
    "moderation": {"warn_limit": 3, "warn_action": "mute", "warn_mute": 3600, "mod_admins_only": False},
    "welcome": {"enabled": False, "text": "Добро пожаловать, {name}! Рады видеть тебя в «{chat}»."},
    "warns": {},
    # Кому выдан доступ к управлению (помимо ADMIN_IDS)
    "managers": [],
    # Известные группы (для рассылки/промо): {chat_id: title}
    "groups": {},
    # Сохранённые ссылки-приглашения: {chat_id: url}
    "invite_links": {},
    # Авто-промо
    "promo": {
        "enabled": False,
        "interval": 3600,
        "text": "Заходи к нам почаще и зови друзей! 🙌",
    },
    # Текст «зазывалы» — сообщения с кнопкой «Пригласить друга»
    "invite_text": "Нравится у нас? Зови друзей 👇",
    # Кто отписался от призывов /all: {chat_id: [user_ids]}
    "all_optout": {},
    # Правила группы (общие для всех групп бота)
    "rules": "Правила группы:\n1) Без спама и рекламы.\n2) Уважайте участников.\n3) Общайтесь по теме.",
    # Защита от сноса (анти-нюк)
    "antinuke": {"enabled": True, "ban_threshold": 5, "window": 30, "action": "stop"},
}

SHORTENERS = {
    "bit.ly", "goo.gl", "tinyurl.com", "cutt.ly", "is.gd", "clck.ru",
    "vk.cc", "t.cn", "ow.ly", "rb.gy", "shorturl.at", "tiny.cc", "rebrand.ly", "surl.li", "qps.ru",
}

FEATURES = [
    ("invites", "Invite-ссылки Telegram"),
    ("shorteners", "Сокращатели ссылок"),
    ("all_links", "Блокировать ВСЕ ссылки"),
    ("spam_domains", "Спам-домены из списка"),
    ("words", "Фильтр стоп-слов (чёрный список)"),
    ("flood", "Антифлуд"),
    ("name_check", "Проверка имён при входе"),
    ("triggers", "Автоответы (ключевые слова)"),
]

# ───────────────────────────────────────────────────────────────────────────
#  ЛОГИ
# ───────────────────────────────────────────────────────────────────────────

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
log = logging.getLogger("antispam")

# ───────────────────────────────────────────────────────────────────────────
#  ХРАНЕНИЕ
# ───────────────────────────────────────────────────────────────────────────


def _merge_defaults(data: dict) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return cfg
    for k, v in data.items():
        if k in ("enabled", "flood", "moderation", "welcome", "promo") and isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    return cfg


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return _merge_defaults(json.load(f))
        except Exception as e:  # noqa: BLE001
            log.warning("Не прочитать %s: %s", CONFIG_PATH, e)
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(CONFIG, f, ensure_ascii=False, indent=2)
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:  # noqa: BLE001
        log.warning("Не сохранить настройки: %s", e)


CONFIG = load_config()

# ───────────────────────────────────────────────────────────────────────────
#  ПАМЯТЬ
# ───────────────────────────────────────────────────────────────────────────

flood_store: dict = defaultdict(deque)
members_store: dict = defaultdict(dict)   # chat_id -> {user_id: имя} (в памяти, для /all)
nuke_store: dict = defaultdict(deque)     # (chat_id, actor_id) -> метки банов (анти-снос)
_admin_cache: dict = {}
ADMIN_CACHE_TTL = 300
_state = {"last_promo": 0.0}

URL_HINT_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|tg://)", re.IGNORECASE)

FULL_PERMS = ChatPermissions(
    can_send_messages=True, can_send_audios=True, can_send_documents=True,
    can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
    can_add_web_page_previews=True,
)
MUTE_PERMS = ChatPermissions(can_send_messages=False)

# ───────────────────────────────────────────────────────────────────────────
#  ПРАВА
# ───────────────────────────────────────────────────────────────────────────


def is_owner(user_id: int) -> bool:
    """Главный владелец (из ADMIN_IDS). Может выдавать/забирать права."""
    return user_id in ADMIN_IDS


def is_manager(user_id: int) -> bool:
    """Кто может управлять ботом: владелец + выданные доступы."""
    return is_owner(user_id) or user_id in CONFIG.get("managers", [])


async def group_admin_ids(context, chat_id: int) -> set:
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


async def is_exempt(context, chat_id: int, user_id: int) -> bool:
    if is_manager(user_id):
        return True
    return user_id in await group_admin_ids(context, chat_id)


async def can_moderate(context, chat_id: int, user_id: int) -> bool:
    if is_manager(user_id):
        return True
    if CONFIG["moderation"].get("mod_admins_only"):
        return False
    return user_id in await group_admin_ids(context, chat_id)


# ───────────────────────────────────────────────────────────────────────────
#  ВСПОМОГАТЕЛЬНОЕ
# ───────────────────────────────────────────────────────────────────────────


def mention(user) -> str:
    if getattr(user, "username", None):
        return "@" + user.username
    return getattr(user, "first_name", None) or "пользователь"


def human_duration(sec) -> str:
    sec = int(sec)
    if sec >= 86400 and sec % 86400 == 0:
        return f"{sec // 86400} дн"
    if sec >= 3600 and sec % 3600 == 0:
        return f"{sec // 3600} ч"
    if sec >= 60:
        return f"{sec // 60} мин"
    return f"{sec} сек"


def parse_duration(tok: str):
    m = re.fullmatch(r"(\d+)([mhdмчд]?)", tok.lower())
    if not m:
        return None
    n = int(m.group(1))
    mult = {"": 60, "m": 60, "м": 60, "h": 3600, "ч": 3600, "d": 86400, "д": 86400}[m.group(2)]
    return n * mult


def _args_text(update: Update) -> str:
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def remember_group(chat):
    if getattr(chat, "type", None) not in ("group", "supergroup"):
        return
    key = str(chat.id)
    title = chat.title or key
    if CONFIG["groups"].get(key) != title:
        CONFIG["groups"][key] = title
        save_config()


def forget_group(chat_id):
    if CONFIG["groups"].pop(str(chat_id), None) is not None:
        CONFIG["invite_links"].pop(str(chat_id), None)
        save_config()


# ── детекторы ───────────────────────────────────────────────────────────────


def find_link_violation(text: str, cfg: dict):
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
    triggers = cfg.get("triggers", {})
    if not triggers:
        return None
    mode = cfg.get("trigger_match", "word")
    low = text.lower()
    best = None
    for key, resp in triggers.items():
        kl = key.lower()
        if mode == "contains":
            hit = kl in low
        else:
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


async def mute_user(context, chat_id: int, user_id: int, seconds):
    until = None if not seconds else datetime.now(timezone.utc) + timedelta(seconds=seconds)
    await context.bot.restrict_chat_member(chat_id, user_id, permissions=MUTE_PERMS, until_date=until)


# ── предупреждения ──────────────────────────────────────────────────────────


def _warns_chat(chat_id):
    return CONFIG["warns"].setdefault(str(chat_id), {})


def get_warn(chat_id, uid):
    return CONFIG["warns"].get(str(chat_id), {}).get(str(uid), 0)


def inc_warn(chat_id, uid):
    w = _warns_chat(chat_id)
    w[str(uid)] = w.get(str(uid), 0) + 1
    save_config()
    return w[str(uid)]


def dec_warn(chat_id, uid):
    w = _warns_chat(chat_id)
    n = max(0, w.get(str(uid), 0) - 1)
    if n == 0:
        w.pop(str(uid), None)
    else:
        w[str(uid)] = n
    save_config()
    return n


def reset_warns(chat_id, uid):
    _warns_chat(chat_id).pop(str(uid), None)
    save_config()


async def alert_owners(context, text):
    """Личное оповещение всем главным владельцам (ADMIN_IDS)."""
    for oid in ADMIN_IDS:
        try:
            await context.bot.send_message(oid, text)
        except Exception as e:  # noqa: BLE001
            log.debug("alert owner %s: %s", oid, e)


def track_nuke(chat_id, actor_id):
    a = CONFIG["antinuke"]
    now = time.time()
    dq = nuke_store[(chat_id, actor_id)]
    dq.append(now)
    while dq and now - dq[0] > a["window"]:
        dq.popleft()
    return len(dq)


# ───────────────────────────────────────────────────────────────────────────
#  СООБЩЕНИЯ В ГРУППАХ
# ───────────────────────────────────────────────────────────────────────────


async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    chat = update.effective_chat
    if not msg or not user or user.is_bot:
        return

    remember_group(chat)
    if user.id not in set(CONFIG["all_optout"].get(str(chat.id), [])):
        members_store[chat.id][user.id] = user.first_name or user.username or str(user.id)
    text = msg.text or msg.caption or ""

    if await is_exempt(context, chat.id, user.id):
        await maybe_send_trigger(update, context, text)
        return

    cfg = CONFIG

    reason = find_link_violation(text, cfg)
    if reason:
        try:
            await msg.delete()
            log.info("Удалено (%s) от %s", reason, user.id)
        except Exception as e:  # noqa: BLE001
            log.debug("delete link: %s", e)
        return

    if cfg["enabled"].get("words"):
        bad = find_word_violation(text, cfg)
        if bad:
            try:
                await msg.delete()
                log.info("Удалено (стоп-слово '%s') от %s", bad, user.id)
            except Exception as e:  # noqa: BLE001
                log.debug("delete word: %s", e)
            return

    if cfg["enabled"].get("flood") and check_flood(chat.id, user.id, cfg):
        try:
            await mute_user(context, chat.id, user.id, cfg["flood"]["mute"])
            await msg.reply_text(f"🔇 {mention(user)} замучен на {cfg['flood']['mute']} сек за флуд.")
        except Exception as e:  # noqa: BLE001
            log.debug("flood mute: %s", e)
        return

    await maybe_send_trigger(update, context, text)


async def maybe_send_trigger(update, context, text):
    if not CONFIG["enabled"].get("triggers"):
        return
    hit = match_trigger(text, CONFIG)
    if hit:
        try:
            await update.effective_message.reply_text(hit[1])
        except Exception as e:  # noqa: BLE001
            log.debug("trigger: %s", e)


async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return
    remember_group(chat)
    name_check = CONFIG["enabled"].get("name_check")
    welcome = CONFIG["welcome"]
    for u in msg.new_chat_members:
        if u.is_bot:
            continue
        if name_check:
            name = " ".join(filter(None, [u.first_name, u.last_name, u.username])).lower()
            if find_word_violation(name, CONFIG) or find_link_violation(name, CONFIG):
                try:
                    await context.bot.ban_chat_member(chat.id, u.id)
                    log.info("Бан при входе (спам в имени): %s", u.id)
                except Exception as e:  # noqa: BLE001
                    log.debug("ban new member: %s", e)
                continue
        if welcome.get("enabled") and welcome.get("text"):
            text = welcome["text"].replace("{name}", u.first_name or "друг").replace("{chat}", chat.title or "чат")
            try:
                await context.bot.send_message(chat.id, text)
            except Exception as e:  # noqa: BLE001
                log.debug("welcome: %s", e)


async def on_my_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бота добавили/удалили/сняли — обновляем список групп и оповещаем владельца."""
    cm = update.my_chat_member
    if not cm:
        return
    status = cm.new_chat_member.status
    old = cm.old_chat_member.status
    actor = cm.from_user
    if status in ("member", "administrator"):
        remember_group(cm.chat)
        log.info("Бот в группе %s, статус %s", cm.chat.id, status)
        if old == "administrator" and status == "member" and CONFIG["antinuke"].get("enabled"):
            await alert_owners(
                context,
                f"⚠️ В «{cm.chat.title}» меня сняли с админки (кто: {mention(actor)}). "
                f"Пока не вернёшь права — защита и антиспам не работают.")
    elif status in ("left", "kicked"):
        if CONFIG["antinuke"].get("enabled"):
            await alert_owners(context, f"⚠️ Меня удалили из группы «{cm.chat.title}» (кто: {mention(actor)}).")
        forget_group(cm.chat.id)
        log.info("Бот удалён из группы %s", cm.chat.id)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анти-снос: следим за массовыми банами и назначением новых админов."""
    cm = update.chat_member
    if not cm:
        return
    a = CONFIG.get("antinuke", {})
    if not a.get("enabled"):
        return
    chat = cm.chat
    actor = cm.from_user
    target = cm.new_chat_member.user
    new = cm.new_chat_member.status
    old = cm.old_chat_member.status
    if not actor or actor.id == context.bot.id:
        return

    # Новый админ — оповестить владельца
    if new == "administrator" and old not in ("administrator", "creator") and not is_manager(actor.id):
        await alert_owners(context, f"⚠️ В «{chat.title}» новый админ: {mention(target)} (назначил {mention(actor)}).")
        return

    # Массовый бан — возможный снос
    if new == "kicked" and actor.id != target.id and not is_manager(actor.id):
        cnt = track_nuke(chat.id, actor.id)
        if cnt >= a["ban_threshold"]:
            nuke_store[(chat.id, actor.id)].clear()
            await alert_owners(
                context,
                f"🚨 ВОЗМОЖНЫЙ СНОС в «{chat.title}»!\n"
                f"{mention(actor)} забанил {cnt}+ участников за {a['window']} сек.")
            if a["action"] == "stop":
                try:
                    await context.bot.ban_chat_member(chat.id, actor.id)
                    await alert_owners(context, f"✅ {mention(actor)} забанен — снос остановлен.")
                except Exception as e:  # noqa: BLE001
                    await alert_owners(
                        context,
                        f"⚠️ Не смог сам забанить {mention(actor)}: {e}\nЗайди в группу и останови вручную.")


async def on_chat_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оповещение при смене названия/фото группы."""
    if not CONFIG["antinuke"].get("enabled"):
        return
    msg = update.effective_message
    chat = update.effective_chat
    if not msg:
        return
    who = mention(update.effective_user) if update.effective_user else "кто-то"
    if msg.new_chat_title:
        await alert_owners(context, f"⚠️ В «{chat.title}» изменили название (кто: {who}).")
    elif msg.new_chat_photo:
        await alert_owners(context, f"⚠️ В «{chat.title}» сменили фото группы (кто: {who}).")
    elif msg.delete_chat_photo:
        await alert_owners(context, f"⚠️ В «{chat.title}» удалили фото группы (кто: {who}).")


# ───────────────────────────────────────────────────────────────────────────
#  МОДЕРАЦИЯ
# ───────────────────────────────────────────────────────────────────────────


async def resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, mention(u)
    if context.args:
        a = context.args[0]
        if a.startswith("@"):
            try:
                ch = await context.bot.get_chat(a)
                return ch.id, ("@" + ch.username if ch.username else (ch.first_name or a))
            except Exception:  # noqa: BLE001
                return None, None
        if a.lstrip("-").isdigit():
            return int(a), a
    return None, None


def extract_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    args = list(context.args)
    if not update.effective_message.reply_to_message and args:
        args = args[1:]
    return " ".join(args).strip()


async def _guard(update, context):
    chat = update.effective_chat
    actor = update.effective_user
    if not await can_moderate(context, chat.id, actor.id):
        return None
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text(
            "Укажи пользователя: ответь на его сообщение или добавь @user (либо id)."
        )
        return None
    if is_manager(tid) or tid in await group_admin_ids(context, chat.id):
        await update.effective_message.reply_text("Это администратор/доверенный — действие не применяю.")
        return None
    return tid, tname


async def cmd_ban(update, context):
    g = await _guard(update, context)
    if not g:
        return
    tid, tname = g
    reason = extract_reason(update, context)
    try:
        await context.bot.ban_chat_member(update.effective_chat.id, tid)
        await update.effective_message.reply_text(f"🚫 {tname} забанен." + (f"\nПричина: {reason}" if reason else ""))
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}\nПроверь, что я админ с правом банить.")


async def cmd_unban(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Кого разбанить? /unban @user или id")
        return
    try:
        await context.bot.unban_chat_member(chat.id, tid, only_if_banned=True)
        await update.effective_message.reply_text(f"✅ {tname} разбанен.")
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}")


async def cmd_kick(update, context):
    g = await _guard(update, context)
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    try:
        await context.bot.ban_chat_member(chat.id, tid)
        await context.bot.unban_chat_member(chat.id, tid, only_if_banned=True)
        await update.effective_message.reply_text(f"👢 {tname} удалён (сможет зайти заново).")
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}")


async def cmd_mute(update, context):
    g = await _guard(update, context)
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    args = list(context.args)
    if not update.effective_message.reply_to_message and args:
        args = args[1:]
    duration = None
    rest = []
    for a in args:
        d = parse_duration(a)
        if d is not None and duration is None:
            duration = d
        else:
            rest.append(a)
    reason = " ".join(rest).strip()
    try:
        await mute_user(context, chat.id, tid, duration)
        dur_txt = "навсегда" if not duration else f"на {human_duration(duration)}"
        await update.effective_message.reply_text(
            f"🔇 {tname} в муте {dur_txt}." + (f"\nПричина: {reason}" if reason else ""))
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}\nПроверь право ограничивать.")


async def cmd_unmute(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Кого размутить? Ответь на сообщение или /unmute @user")
        return
    try:
        await context.bot.restrict_chat_member(chat.id, tid, permissions=FULL_PERMS)
        await update.effective_message.reply_text(f"🔊 {tname} размучен.")
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}")


async def cmd_warn(update, context):
    g = await _guard(update, context)
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    reason = extract_reason(update, context)
    n = inc_warn(chat.id, tid)
    m = CONFIG["moderation"]
    limit = m["warn_limit"]
    if n >= limit:
        reset_warns(chat.id, tid)
        try:
            if m["warn_action"] == "ban":
                await context.bot.ban_chat_member(chat.id, tid)
                await update.effective_message.reply_text(f"⚠️ {tname}: {n}/{limit} — бан.")
            else:
                await mute_user(context, chat.id, tid, m["warn_mute"])
                await update.effective_message.reply_text(
                    f"⚠️ {tname}: {n}/{limit} — мут на {human_duration(m['warn_mute'])}.")
        except Exception as e:  # noqa: BLE001
            await update.effective_message.reply_text(f"Лимит достигнут, но наказать не вышло: {e}")
    else:
        await update.effective_message.reply_text(
            f"⚠️ {tname}: предупреждение {n}/{limit}." + (f"\nПричина: {reason}" if reason else ""))


async def cmd_unwarn(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("С кого снять предупреждение? /unwarn @user")
        return
    n = dec_warn(chat.id, tid)
    await update.effective_message.reply_text(f"➖ {tname}: теперь {n} предупреждений.")


async def cmd_warns(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Чьи предупреждения? /warns @user")
        return
    await update.effective_message.reply_text(
        f"{tname}: {get_warn(chat.id, tid)}/{CONFIG['moderation']['warn_limit']} предупреждений.")


# ───────────────────────────────────────────────────────────────────────────
#  ПРИВЛЕЧЕНИЕ / ПОСТИНГ
# ───────────────────────────────────────────────────────────────────────────


async def ensure_invite_link(context, chat_id, force=False):
    """Возвращает (создаёт при необходимости) ссылку-приглашение для чата."""
    key = str(chat_id)
    link = CONFIG["invite_links"].get(key)
    if link and not force:
        return link
    try:
        res = await context.bot.create_chat_invite_link(chat_id)
        CONFIG["invite_links"][key] = res.invite_link
        save_config()
        return res.invite_link
    except Exception as e:  # noqa: BLE001
        log.debug("create invite link: %s", e)
        return None


async def cmd_invite(update, context):
    """Выдать ссылку-приглашение в текущую группу (для админов)."""
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return
    want_new = bool(context.args) and context.args[0].lower() in ("new", "новая")
    link = await ensure_invite_link(context, chat.id, force=want_new)
    if not link:
        await update.effective_message.reply_text(
            "Не вышло создать ссылку. Дай боту право «Приглашать пользователей».")
        return
    await update.effective_message.reply_text(f"🔗 Ссылка-приглашение:\n{link}\n\nДелись ей, чтобы звать народ.")


async def cmd_zazyvala(update, context):
    """Опубликовать в группе сообщение с кнопкой «Пригласить друга»."""
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return
    link = await ensure_invite_link(context, chat.id)
    if not link:
        await update.effective_message.reply_text(
            "Не вышло создать ссылку. Дай боту право «Приглашать пользователей».")
        return
    text = CONFIG.get("invite_text") or "Зови друзей 👇"
    share = "https://t.me/share/url?url=" + quote(link, safe="") + "&text=" + quote(text, safe="")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("👥 Пригласить друга", url=share)]])
    try:
        sent = await context.bot.send_message(chat.id, text, reply_markup=kb)
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло опубликовать: {e}")
        return
    try:
        await context.bot.pin_chat_message(chat.id, sent.message_id, disable_notification=True)
    except Exception:  # noqa: BLE001
        pass
    try:
        await update.effective_message.delete()
    except Exception:  # noqa: BLE001
        pass


def _optout_list(chat_id):
    return CONFIG["all_optout"].setdefault(str(chat_id), [])


async def cmd_all(update, context):
    """Призыв: отметить (тегнуть) всех активных участников группы."""
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return
    text = _args_text(update) or "Все сюда! 👀"
    optout = set(_optout_list(chat.id))
    members = members_store.get(chat.id, {})
    targets = [(uid, name) for uid, name in members.items() if uid not in optout]
    if not targets:
        await update.effective_message.reply_text(
            "Пока некого звать — я отмечаю только тех, кто писал в чате после моего запуска. "
            "Подожди, пока люди начнут писать, и зови снова.")
        return
    targets = targets[:100]  # предохранитель от мегафлуда
    batch, first = [], True
    for i, (uid, name) in enumerate(targets, 1):
        batch.append(f'<a href="tg://user?id={uid}">{html.escape(name or "друг")}</a>')
        if len(batch) >= 5 or i == len(targets):
            body = (f"📣 {html.escape(text)}\n" if first else "") + " ".join(batch)
            try:
                await context.bot.send_message(chat.id, body, parse_mode="HTML")
            except Exception as e:  # noqa: BLE001
                log.debug("all batch: %s", e)
            batch, first = [], False
            await asyncio.sleep(1)  # пауза между пачками, чтобы не словить лимиты


async def cmd_anreg(update, context):
    """Пользователь выходит из призывов /all."""
    chat = update.effective_chat
    uid = update.effective_user.id
    lst = _optout_list(chat.id)
    if uid not in lst:
        lst.append(uid)
        save_config()
    members_store.get(chat.id, {}).pop(uid, None)
    await update.effective_message.reply_text("✅ Ты больше не будешь получать призывы (/all). Вернуться: /reg")


async def cmd_reg(update, context):
    """Пользователь возвращается в призывы /all."""
    chat = update.effective_chat
    uid = update.effective_user.id
    lst = _optout_list(chat.id)
    if uid in lst:
        lst.remove(uid)
        save_config()
    members_store[chat.id][uid] = update.effective_user.first_name or str(uid)
    await update.effective_message.reply_text("✅ Снова участвуешь в призывах (/all).")


async def cmd_say(update, context):
    """Бот публикует объявление в текущей группе."""
    if not is_manager(update.effective_user.id):
        return
    text = _args_text(update)
    if not text:
        await update.effective_message.reply_text("Что написать? /say текст объявления")
        return
    chat = update.effective_chat
    try:
        await update.effective_message.delete()
    except Exception:  # noqa: BLE001
        pass
    await context.bot.send_message(chat.id, text)


async def cmd_rules(update, context):
    """Показать правила группы (для всех участников)."""
    await update.effective_message.reply_text(CONFIG.get("rules") or "Правила пока не заданы.")


async def cmd_link(update, context):
    """Ссылка на группу (для всех участников)."""
    chat = update.effective_chat
    link = await ensure_invite_link(context, chat.id)
    if not link:
        await update.effective_message.reply_text(
            "Ссылка пока недоступна — обратись к админу (боту нужно право «Приглашать пользователей»).")
        return
    await update.effective_message.reply_text(f"🔗 Ссылка на группу:\n{link}")


async def cmd_setrules(update, context):
    if not is_manager(update.effective_user.id):
        return
    text = _args_text(update)
    if not text:
        await update.effective_message.reply_text("Формат: /setrules текст правил")
        return
    CONFIG["rules"] = text
    save_config()
    await update.effective_message.reply_text("✅ Правила сохранены.", reply_markup=rules_kb())


async def _broadcast(context, text: str):
    ok = fail = 0
    for cid in list(CONFIG["groups"].keys()):
        try:
            await context.bot.send_message(int(cid), text)
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
            forget_group(int(cid))
    return ok, fail


async def cmd_broadcast(update, context):
    """Разослать сообщение во все группы бота (в ЛС)."""
    if not is_manager(update.effective_user.id):
        return
    text = _args_text(update)
    if not text:
        await update.message.reply_text("Что разослать? /broadcast текст сообщения")
        return
    if not CONFIG["groups"]:
        await update.message.reply_text("Пока нет известных групп. Добавь бота в группу и напиши там что-нибудь.")
        return
    ok, fail = await _broadcast(context, text)
    await update.message.reply_text(f"📣 Разослано в {ok} групп(ы), не доставлено: {fail}.")


async def promo_job(context: ContextTypes.DEFAULT_TYPE):
    p = CONFIG["promo"]
    if not p.get("enabled") or not p.get("text"):
        return
    now = time.time()
    if now - _state["last_promo"] < p.get("interval", 3600):
        return
    _state["last_promo"] = now
    ok, _fail = await _broadcast(context, p["text"])
    log.info("Авто-промо отправлено в %s групп", ok)


# ───────────────────────────────────────────────────────────────────────────
#  ПАНЕЛЬ (кнопки)
# ───────────────────────────────────────────────────────────────────────────


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Статус", callback_data="m:status")],
        [InlineKeyboardButton("🔘 Функции", callback_data="m:toggles"),
         InlineKeyboardButton("⚙️ Антифлуд", callback_data="m:flood")],
        [InlineKeyboardButton("🛡 Модерация", callback_data="m:mod"),
         InlineKeyboardButton("🛡 Анти-снос", callback_data="m:antinuke")],
        [InlineKeyboardButton("👋 Приветствие", callback_data="m:welcome"),
         InlineKeyboardButton("📣 Промо/Рассылка", callback_data="m:promo")],
        [InlineKeyboardButton("💬 Ключевые слова", callback_data="m:triggers"),
         InlineKeyboardButton("👥 Доступ", callback_data="m:access")],
        [InlineKeyboardButton("🚫 Стоп-слова", callback_data="m:words"),
         InlineKeyboardButton("🔗 Спам-ссылки", callback_data="m:links")],
        [InlineKeyboardButton("📜 Правила", callback_data="m:rules"),
         InlineKeyboardButton("ℹ️ Помощь", callback_data="m:help")],
    ])


def antinuke_kb() -> InlineKeyboardMarkup:
    a = CONFIG["antinuke"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Защита включена" if a["enabled"] else "🔴 Защита выключена", callback_data="an:toggle")],
        [InlineKeyboardButton(f"Порог: {a['ban_threshold']} банов за {a['window']} сек", callback_data="noop")],
        [InlineKeyboardButton("➖ порог", callback_data="an:thr:-"), InlineKeyboardButton("➕ порог", callback_data="an:thr:+")],
        [InlineKeyboardButton("➖ окно", callback_data="an:win:-"), InlineKeyboardButton("➕ окно", callback_data="an:win:+")],
        [InlineKeyboardButton(
            f"Действие: {'банить нарушителя' if a['action'] == 'stop' else 'только оповещать'}", callback_data="an:action")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def rules_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить правила", callback_data="ru:edit")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
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
    rows.append([InlineKeyboardButton(
        f"🔁 Режим: {'целое слово' if mode == 'word' else 'любое вхождение'}", callback_data="mode:trig")])
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
        [InlineKeyboardButton("➖", callback_data="fl:limit:-"), InlineKeyboardButton("➕", callback_data="fl:limit:+")],
        [InlineKeyboardButton(f"Период: {f['period']} сек", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:period:-"), InlineKeyboardButton("➕", callback_data="fl:period:+")],
        [InlineKeyboardButton(f"Длительность мута: {f['mute']} сек", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:mute:-"), InlineKeyboardButton("➕", callback_data="fl:mute:+")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def mod_kb() -> InlineKeyboardMarkup:
    m = CONFIG["moderation"]
    rows = [
        [InlineKeyboardButton(f"Лимит предупреждений: {m['warn_limit']}", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="md:limit:-"), InlineKeyboardButton("➕", callback_data="md:limit:+")],
        [InlineKeyboardButton(f"При лимите: {'бан' if m['warn_action'] == 'ban' else 'мут'}", callback_data="md:action")],
    ]
    if m["warn_action"] == "mute":
        rows += [
            [InlineKeyboardButton(f"Мут при лимите: {human_duration(m['warn_mute'])}", callback_data="noop")],
            [InlineKeyboardButton("➖", callback_data="md:mute:-"), InlineKeyboardButton("➕", callback_data="md:mute:+")],
        ]
    rows.append([InlineKeyboardButton(
        f"{'✅' if m['mod_admins_only'] else '❌'} Модерация только для владельца", callback_data="md:owneronly")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def welcome_kb() -> InlineKeyboardMarkup:
    w = CONFIG["welcome"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Включено" if w["enabled"] else "🔴 Выключено", callback_data="wl:toggle")],
        [InlineKeyboardButton("✏️ Изменить текст", callback_data="wl:edit")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def promo_kb() -> InlineKeyboardMarkup:
    p = CONFIG["promo"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Авто-промо включено" if p["enabled"] else "🔴 Авто-промо выключено",
                              callback_data="pr:toggle")],
        [InlineKeyboardButton(f"Интервал: {human_duration(p['interval'])}", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="pr:int:-"), InlineKeyboardButton("➕", callback_data="pr:int:+")],
        [InlineKeyboardButton("✏️ Изменить текст промо", callback_data="pr:edit")],
        [InlineKeyboardButton("✏️ Текст кнопки-зазывалы", callback_data="pr:invtext")],
        [InlineKeyboardButton("📨 Разослать сообщение сейчас", callback_data="pr:cast")],
        [InlineKeyboardButton("📝 Запостить в группу", callback_data="post:list")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def post_groups_kb() -> InlineKeyboardMarkup:
    rows = []
    for i, (cid, title) in enumerate(sorted(CONFIG["groups"].items())):
        label = title if len(title) <= 30 else title[:29] + "…"
        rows.append([InlineKeyboardButton(f"📝 {label}", callback_data=f"pto:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:promo")])
    return InlineKeyboardMarkup(rows)


def access_kb() -> InlineKeyboardMarkup:
    rows = []
    for i, uid in enumerate(CONFIG["managers"]):
        rows.append([InlineKeyboardButton(f"❌ убрать {uid}", callback_data=f"dm:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def status_text() -> str:
    en = CONFIG["enabled"]
    f = CONFIG["flood"]
    m = CONFIG["moderation"]
    p = CONFIG["promo"]
    lines = ["📊 Статус бота", ""]
    for key, label in FEATURES:
        lines.append(f"{'🟢' if en.get(key) else '🔴'} {label}")
    who = "только владелец" if m["mod_admins_only"] else "админы чата"
    pun = "бан" if m["warn_action"] == "ban" else f"мут {human_duration(m['warn_mute'])}"
    lines += [
        "",
        f"Антифлуд: {f['limit']}/{f['period']}с → мут {f['mute']}с",
        f"Предупреждения: {m['warn_limit']} → {pun} · модерируют: {who}",
        f"Приветствие: {'вкл' if CONFIG['welcome']['enabled'] else 'выкл'}",
        f"Авто-промо: {'вкл' if p['enabled'] else 'выкл'} (каждые {human_duration(p['interval'])})",
        f"Групп на учёте: {len(CONFIG['groups'])} · доступ выдан: {len(CONFIG['managers'])}",
        f"Стоп-слов: {len(CONFIG['stop_words'])} · доменов: {len(CONFIG['spam_links'])} · автоответов: {len(CONFIG['triggers'])}",
    ]
    return "\n".join(lines)


def promo_menu_text() -> str:
    p = CONFIG["promo"]
    return (
        "📣 Промо и рассылка.\n\n"
        f"Авто-промо: {'включено' if p['enabled'] else 'выключено'}, каждые {human_duration(p['interval'])}\n"
        f"Групп на учёте: {len(CONFIG['groups'])}\n\n"
        "Текст промо:\n" + (p["text"] or "—") + "\n\n"
        "«Разослать сейчас» — отправит одно сообщение во все группы.\n"
        "Кнопка-зазывала «Пригласить друга»: команда /zazyvala в группе.\n"
        "Текст зазывалы: " + (CONFIG.get("invite_text") or "—") + "\n"
        "В группе доступна команда /invite — ссылка-приглашение."
    )


def access_menu_text() -> str:
    mans = CONFIG["managers"]
    body = "\n".join(str(x) for x in mans) if mans else "пока никому (кроме тебя)"
    return (
        "👥 Доступ к управлению ботом.\n\n"
        "Сейчас управляют (помимо тебя):\n" + body + "\n\n"
        "Выдать права: команда /grant — ответом на сообщение человека в группе, "
        "либо /grant @username (или id).\n"
        "Забрать: /revoke @username (или кнопкой ниже)."
    )


def antinuke_menu_text() -> str:
    a = CONFIG["antinuke"]
    act = "забанить нарушителя и оповестить тебя" if a["action"] == "stop" else "только оповестить тебя"
    return (
        "🛡 Защита от сноса (анти-снос).\n\n"
        f"Статус: {'включена' if a['enabled'] else 'выключена'}\n"
        f"Триггер: {a['ban_threshold']}+ банов за {a['window']} сек от одного человека\n"
        f"Действие: {act}\n\n"
        "Что делает: ловит массовые баны, пишет тебе в ЛС и (если включено) банит нарушителя. "
        "Также сразу сообщает, если меня сняли с админки/удалили, назначили нового админа "
        "или сменили название/фото группы.\n\n"
        "⚠️ Создателя группы Telegram не даёт тронуть никому, даже боту — поэтому полностью "
        "запретить снос со стороны владельца нельзя, но ты узнаешь моментально."
    )


def rules_menu_text() -> str:
    return (
        "📜 Правила группы (одни для всех твоих групп).\n\n"
        "Участники смотрят их командой /group в чате.\n\n"
        "Сейчас:\n" + (CONFIG.get("rules") or "—")
    )


HELP_TEXT = (
    "ℹ️ Управление (в ЛС): /panel /status /id\n\n"
    "Автоответы: /add слово = ответ · /del · /list\n"
    "Стоп-слова (чёрный список, удаляются): /addword · /delword · /words\n"
    "Спам-домены: /addlink · /dellink · /links\n"
    "Приветствие: /setwelcome текст ({name}, {chat})\n"
    "Правила: /setrules текст\n\n"
    "🛡 Модерация (в группе, для админов чата):\n"
    "/ban /unban /kick · /mute [время] /unmute · /warn /unwarn /warns\n"
    "Цель: ответом на сообщение, либо @user или id. Время: 30m, 2h, 1d.\n\n"
    "📣 Привлечение, призыв, постинг:\n"
    "/invite — ссылка-приглашение (в группе)\n"
    "/zazyvala — кнопка «Пригласить друга» (в группе)\n"
    "/all [текст] — призыв: отметить всех активных (в группе)\n"
    "/anreg — выйти из призывов · /reg — вернуться\n"
    "/say текст — опубликовать в группе\n"
    "/broadcast текст — разослать во все группы (в ЛС)\n"
    "Постинг в выбранную группу и авто-промо — в панели «Промо/Рассылка».\n\n"
    "📜 Для участников (в группе): /group — правила · /link — ссылка на группу\n"
    "🛡 Защита от сноса — в панели «Анти-снос».\n\n"
    "👥 Доступ (только главный владелец):\n"
    "/grant — выдать права · /revoke — забрать · /managers — список\n\n"
    "Боту в группе нужны права: удалять сообщения, блокировать, "
    "ограничивать участников и приглашать пользователей (для ссылок)."
)


async def safe_edit(query, text, kb):
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("safe_edit: %s", e)


def welcome_menu_text() -> str:
    return (
        "👋 Приветствие новых участников.\n\n"
        f"Сейчас: {'включено' if CONFIG['welcome']['enabled'] else 'выключено'}\n\n"
        "Текст:\n" + (CONFIG["welcome"]["text"] or "—") + "\n\n"
        "Можно использовать {name} (имя) и {chat} (название группы)."
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not query:
        return
    if not is_manager(user.id):
        await query.answer("Недоступно", show_alert=True)
        return

    data = query.data or ""
    await query.answer()

    # Раздел «Доступ» — только для главного владельца
    if data == "m:access" or data.startswith("dm:"):
        if not is_owner(user.id):
            return await query.answer("Только для главного владельца", show_alert=True)
        if data.startswith("dm:"):
            i = int(data[3:])
            if 0 <= i < len(CONFIG["managers"]):
                CONFIG["managers"].pop(i)
                save_config()
        return await safe_edit(query, access_menu_text(), access_kb())

    nav = {
        "m:main": ("🛠 Панель управления AntiSpam", main_menu_kb()),
        "m:status": (status_text(), main_menu_kb()),
        "m:toggles": ("🔘 Включение/выключение функций:", toggles_kb()),
        "m:triggers": ("💬 Автоответы (слово → ответ):", triggers_kb()),
        "m:words": ("🚫 Стоп-слова — чёрный список. Сообщения с этими словами удаляются:", words_kb()),
        "m:links": ("🔗 Спам-домены (помимо встроенных сокращателей):", links_kb()),
        "m:flood": ("⚙️ Настройки антифлуда:", flood_kb()),
        "m:mod": ("🛡 Модерация. Команды — в группе (/ban, /mute, /warn...).\nЗдесь — настройки предупреждений:", mod_kb()),
        "m:welcome": (welcome_menu_text(), welcome_kb()),
        "m:promo": (promo_menu_text(), promo_kb()),
        "m:antinuke": (antinuke_menu_text(), antinuke_kb()),
        "m:rules": (rules_menu_text(), rules_kb()),
        "m:help": (HELP_TEXT, main_menu_kb()),
    }
    if data in nav:
        return await safe_edit(query, *nav[data])

    if data == "noop":
        return

    if data.startswith("tg:"):
        key = data[3:]
        CONFIG["enabled"][key] = not CONFIG["enabled"].get(key, False)
        save_config()
        return await safe_edit(query, "🔘 Включение/выключение функций:", toggles_kb())

    if data == "mode:trig":
        CONFIG["trigger_match"] = "contains" if CONFIG.get("trigger_match") == "word" else "word"
        save_config()
        return await safe_edit(query, "💬 Автоответы (слово → ответ):", triggers_kb())

    if data.startswith("fl:"):
        _, field, sign = data.split(":")
        step = {"limit": 1, "period": 5, "mute": 60}[field]
        floor = {"limit": 2, "period": 5, "mute": 30}[field]
        CONFIG["flood"][field] = max(floor, CONFIG["flood"][field] + (step if sign == "+" else -step))
        save_config()
        return await safe_edit(query, "⚙️ Настройки антифлуда:", flood_kb())

    if data.startswith("an:"):
        what = data.split(":")[1]
        a = CONFIG["antinuke"]
        if what == "toggle":
            a["enabled"] = not a["enabled"]
        elif what == "action":
            a["action"] = "alert" if a["action"] == "stop" else "stop"
        elif what == "thr":
            a["ban_threshold"] = max(2, a["ban_threshold"] + (1 if data.split(":")[2] == "+" else -1))
        elif what == "win":
            a["window"] = max(10, a["window"] + (10 if data.split(":")[2] == "+" else -10))
        save_config()
        return await safe_edit(query, antinuke_menu_text(), antinuke_kb())

    if data == "ru:edit":
        context.user_data["await"] = "rules"
        return await safe_edit(query, "Пришли новый текст правил одним сообщением.\n(или /cancel)", None)

    if data.startswith("md:"):
        parts = data.split(":")
        if parts[1] == "action":
            CONFIG["moderation"]["warn_action"] = "ban" if CONFIG["moderation"]["warn_action"] == "mute" else "mute"
        elif parts[1] == "owneronly":
            CONFIG["moderation"]["mod_admins_only"] = not CONFIG["moderation"]["mod_admins_only"]
        elif parts[1] == "limit":
            CONFIG["moderation"]["warn_limit"] = max(1, CONFIG["moderation"]["warn_limit"] + (1 if parts[2] == "+" else -1))
        elif parts[1] == "mute":
            CONFIG["moderation"]["warn_mute"] = max(300, CONFIG["moderation"]["warn_mute"] + (1800 if parts[2] == "+" else -1800))
        save_config()
        return await safe_edit(query, "🛡 Модерация. Настройки предупреждений:", mod_kb())

    if data == "wl:toggle":
        CONFIG["welcome"]["enabled"] = not CONFIG["welcome"]["enabled"]
        save_config()
        return await safe_edit(query, welcome_menu_text(), welcome_kb())
    if data == "wl:edit":
        context.user_data["await"] = "welcome"
        return await safe_edit(query, "Пришли новый текст приветствия одним сообщением.\n"
                                       "Можно вставить {name} и {chat}.\n\n(или /cancel)", None)

    if data.startswith("pr:"):
        what = data.split(":")[1]
        if what == "toggle":
            CONFIG["promo"]["enabled"] = not CONFIG["promo"]["enabled"]
            save_config()
            return await safe_edit(query, promo_menu_text(), promo_kb())
        if what == "int":
            sign = data.split(":")[2]
            CONFIG["promo"]["interval"] = max(600, CONFIG["promo"]["interval"] + (600 if sign == "+" else -600))
            save_config()
            return await safe_edit(query, promo_menu_text(), promo_kb())
        if what == "edit":
            context.user_data["await"] = "promo"
            return await safe_edit(query, "Пришли текст авто-промо одним сообщением.\n(или /cancel)", None)
        if what == "invtext":
            context.user_data["await"] = "invite_text"
            return await safe_edit(
                query, "Пришли текст для кнопки-зазывалы (его увидят участники и друзья при приглашении).\n(или /cancel)", None)
        if what == "cast":
            context.user_data["await"] = "broadcast"
            return await safe_edit(query, "Пришли сообщение — разошлю его во все группы бота.\n(или /cancel)", None)

    if data == "post:list":
        if not CONFIG["groups"]:
            return await safe_edit(query, "Пока нет известных групп. Добавь бота в группу и напиши там что-нибудь.", promo_kb())
        return await safe_edit(query, "Выбери группу, куда опубликовать:", post_groups_kb())
    if data.startswith("pto:"):
        items = sorted(CONFIG["groups"].items())
        i = int(data[4:])
        if 0 <= i < len(items):
            cid, title = items[i]
            context.user_data["await"] = "post"
            context.user_data["post_chat"] = int(cid)
            return await safe_edit(query, f"Пришли текст — опубликую его в «{title}».\n(или /cancel)", None)
        return await safe_edit(query, "Группа не найдена.", post_groups_kb())

    if data.startswith("dt:"):
        keys = sorted(CONFIG["triggers"].keys())
        i = int(data[3:])
        if 0 <= i < len(keys):
            CONFIG["triggers"].pop(keys[i], None)
            save_config()
        return await safe_edit(query, "💬 Автоответы (слово → ответ):", triggers_kb())
    if data.startswith("dw:"):
        words = sorted(CONFIG["stop_words"])
        i = int(data[3:])
        if 0 <= i < len(words):
            CONFIG["stop_words"].remove(words[i])
            save_config()
        return await safe_edit(query, "🚫 Стоп-слова:", words_kb())
    if data.startswith("dl:"):
        links = sorted(CONFIG["spam_links"])
        i = int(data[3:])
        if 0 <= i < len(links):
            CONFIG["spam_links"].remove(links[i])
            save_config()
        return await safe_edit(query, "🔗 Спам-домены:", links_kb())

    if data == "add:trigger":
        context.user_data["await"] = "trigger"
        return await safe_edit(query, "Пришли строку: слово = ответ\nНапример: банан = 300 руб\n\n(или /cancel)", None)
    if data == "add:word":
        context.user_data["await"] = "word"
        return await safe_edit(query, "Пришли стоп-слово одним сообщением.\n(или /cancel)", None)
    if data == "add:link":
        context.user_data["await"] = "link"
        return await safe_edit(query, "Пришли домен, напр. example.com\n(или /cancel)", None)


# ───────────────────────────────────────────────────────────────────────────
#  КОМАНДЫ В ЛС / ОБЩИЕ
# ───────────────────────────────────────────────────────────────────────────


async def cmd_start(update, context):
    if is_manager(update.effective_user.id):
        await update.message.reply_text("🛠 Панель управления AntiSpam", reply_markup=main_menu_kb())
    else:
        await update.message.reply_text(
            "Это приватный антиспам-бот. Добавь меня в группу администратором — буду следить за порядком.")


async def cmd_panel(update, context):
    if not is_manager(update.effective_user.id):
        return
    await update.message.reply_text("🛠 Панель управления AntiSpam", reply_markup=main_menu_kb())


async def cmd_status(update, context):
    if not is_manager(update.effective_user.id):
        return
    await update.message.reply_text(status_text(), reply_markup=main_menu_kb())


async def cmd_help(update, context):
    if not is_manager(update.effective_user.id):
        return
    await update.message.reply_text(HELP_TEXT)


async def cmd_cancel(update, context):
    if context.user_data.pop("await", None):
        await update.message.reply_text("Отменено.", reply_markup=main_menu_kb())


async def cmd_id(update, context):
    u = update.effective_user
    c = update.effective_chat
    await update.message.reply_text(f"Твой ID: {u.id}\nID этого чата: {c.id}")


async def cmd_setwelcome(update, context):
    if not is_manager(update.effective_user.id):
        return
    text = _args_text(update)
    if not text:
        await update.message.reply_text("Формат: /setwelcome текст (можно {name} и {chat})")
        return
    CONFIG["welcome"]["text"] = text
    CONFIG["welcome"]["enabled"] = True
    save_config()
    await update.message.reply_text("✅ Приветствие сохранено и включено.", reply_markup=welcome_kb())


# ── доступ (только главный владелец) ────────────────────────────────────────


async def cmd_grant(update, context):
    if not is_owner(update.effective_user.id):
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Кому выдать права? Ответь на сообщение человека или /grant @user (id).")
        return
    if tid not in CONFIG["managers"]:
        CONFIG["managers"].append(tid)
        save_config()
    await update.effective_message.reply_text(f"✅ {tname} теперь может управлять ботом (панель + модерация).")


async def cmd_revoke(update, context):
    if not is_owner(update.effective_user.id):
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("У кого забрать права? /revoke @user (id).")
        return
    if tid in CONFIG["managers"]:
        CONFIG["managers"].remove(tid)
        save_config()
    await update.effective_message.reply_text(f"🚫 У {tname} забраны права управления.")


async def cmd_managers(update, context):
    if not is_owner(update.effective_user.id):
        return
    await update.message.reply_text(access_menu_text(), reply_markup=access_kb())


# ── контент-команды ─────────────────────────────────────────────────────────


async def cmd_add(update, context):
    if not is_manager(update.effective_user.id):
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


async def cmd_del(update, context):
    if not is_manager(update.effective_user.id):
        return
    key = _args_text(update).lower()
    if CONFIG["triggers"].pop(key, None) is not None:
        save_config()
        await update.message.reply_text(f"🗑 Удалено: «{key}»", reply_markup=triggers_kb())
    else:
        await update.message.reply_text("Такого ключа нет.")


async def cmd_list(update, context):
    if not is_manager(update.effective_user.id):
        return
    if not CONFIG["triggers"]:
        await update.message.reply_text("Автоответов пока нет.", reply_markup=triggers_kb())
        return
    lines = [f"• {k} → {v}" for k, v in sorted(CONFIG["triggers"].items())]
    await update.message.reply_text("💬 Автоответы:\n" + "\n".join(lines), reply_markup=triggers_kb())


async def cmd_addword(update, context):
    if not is_manager(update.effective_user.id):
        return
    w = _args_text(update).lower()
    if not w:
        await update.message.reply_text("Формат: /addword слово")
        return
    if w not in CONFIG["stop_words"]:
        CONFIG["stop_words"].append(w)
        save_config()
    await update.message.reply_text(f"✅ Стоп-слово: {w}", reply_markup=words_kb())


async def cmd_delword(update, context):
    if not is_manager(update.effective_user.id):
        return
    w = _args_text(update).lower()
    if w in CONFIG["stop_words"]:
        CONFIG["stop_words"].remove(w)
        save_config()
        await update.message.reply_text(f"🗑 Удалено: {w}", reply_markup=words_kb())
    else:
        await update.message.reply_text("Такого слова нет.")


async def cmd_words(update, context):
    if not is_manager(update.effective_user.id):
        return
    await update.message.reply_text(
        "🚫 Стоп-слова:\n" + (", ".join(sorted(CONFIG["stop_words"])) or "—"), reply_markup=words_kb())


async def cmd_addlink(update, context):
    if not is_manager(update.effective_user.id):
        return
    d = _args_text(update).lower()
    if not d:
        await update.message.reply_text("Формат: /addlink домен")
        return
    if d not in CONFIG["spam_links"]:
        CONFIG["spam_links"].append(d)
        save_config()
    await update.message.reply_text(f"✅ Домен: {d}", reply_markup=links_kb())


async def cmd_dellink(update, context):
    if not is_manager(update.effective_user.id):
        return
    d = _args_text(update).lower()
    if d in CONFIG["spam_links"]:
        CONFIG["spam_links"].remove(d)
        save_config()
        await update.message.reply_text(f"🗑 Удалено: {d}", reply_markup=links_kb())
    else:
        await update.message.reply_text("Такого домена нет.")


async def cmd_links(update, context):
    if not is_manager(update.effective_user.id):
        return
    await update.message.reply_text(
        "🔗 Спам-домены:\n" + (", ".join(sorted(CONFIG["spam_links"])) or "—"), reply_markup=links_kb())


async def on_private_text(update, context):
    user = update.effective_user
    if not is_manager(user.id):
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
    elif awaiting == "welcome":
        if text:
            CONFIG["welcome"]["text"] = text
            CONFIG["welcome"]["enabled"] = True
            save_config()
            await update.message.reply_text("✅ Приветствие сохранено и включено.", reply_markup=welcome_kb())
        else:
            await update.message.reply_text("Пусто. Попробуй снова через /panel.")
    elif awaiting == "promo":
        if text:
            CONFIG["promo"]["text"] = text
            save_config()
            await update.message.reply_text("✅ Текст промо сохранён.", reply_markup=promo_kb())
        else:
            await update.message.reply_text("Пусто. Попробуй снова через /panel.")
    elif awaiting == "invite_text":
        if text:
            CONFIG["invite_text"] = text
            save_config()
            await update.message.reply_text(
                "✅ Текст зазывалы сохранён. Опубликуй кнопку командой /zazyvala в группе.",
                reply_markup=promo_kb())
        else:
            await update.message.reply_text("Пусто. Попробуй снова через /panel.")
    elif awaiting == "rules":
        if text:
            CONFIG["rules"] = text
            save_config()
            await update.message.reply_text("✅ Правила сохранены.", reply_markup=rules_kb())
        else:
            await update.message.reply_text("Пусто. Попробуй снова через /panel.")
    elif awaiting == "broadcast":
        if not text:
            await update.message.reply_text("Пусто, ничего не разослал.")
            return
        if not CONFIG["groups"]:
            await update.message.reply_text("Пока нет известных групп. Добавь бота в группу и напиши там что-нибудь.")
            return
        ok, fail = await _broadcast(context, text)
        await update.message.reply_text(f"📣 Разослано в {ok} групп(ы), не доставлено: {fail}.", reply_markup=promo_kb())
    elif awaiting == "post":
        cid = context.user_data.pop("post_chat", None)
        if not text or not cid:
            await update.message.reply_text("Пусто или группа не выбрана. Попробуй снова через /panel.")
            return
        try:
            await context.bot.send_message(cid, text)
            await update.message.reply_text("✅ Опубликовано.", reply_markup=promo_kb())
        except Exception as e:  # noqa: BLE001
            await update.message.reply_text(f"Не вышло опубликовать: {e}", reply_markup=promo_kb())


# ───────────────────────────────────────────────────────────────────────────
#  ОШИБКИ И ЗАПУСК
# ───────────────────────────────────────────────────────────────────────────


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Ошибка при обработке апдейта: %s", context.error)


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    private = filters.ChatType.PRIVATE
    groups = filters.ChatType.GROUPS

    # ЛС (управление)
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
    app.add_handler(CommandHandler("broadcast", cmd_broadcast, filters=private))
    app.add_handler(CommandHandler("managers", cmd_managers, filters=private))

    # Где угодно (внутренняя проверка)
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CommandHandler("setwelcome", cmd_setwelcome))
    app.add_handler(CommandHandler("setrules", cmd_setrules))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))

    # Модерация / привлечение (в группах)
    app.add_handler(CommandHandler("ban", cmd_ban, filters=groups))
    app.add_handler(CommandHandler("unban", cmd_unban, filters=groups))
    app.add_handler(CommandHandler("kick", cmd_kick, filters=groups))
    app.add_handler(CommandHandler("mute", cmd_mute, filters=groups))
    app.add_handler(CommandHandler("unmute", cmd_unmute, filters=groups))
    app.add_handler(CommandHandler("warn", cmd_warn, filters=groups))
    app.add_handler(CommandHandler("unwarn", cmd_unwarn, filters=groups))
    app.add_handler(CommandHandler(["warns", "warnings"], cmd_warns, filters=groups))
    app.add_handler(CommandHandler("say", cmd_say, filters=groups))
    app.add_handler(CommandHandler("invite", cmd_invite, filters=groups))
    app.add_handler(CommandHandler("link", cmd_link, filters=groups))
    app.add_handler(CommandHandler(["group", "rules"], cmd_rules, filters=groups))
    app.add_handler(CommandHandler(["zazyvala", "invitebtn"], cmd_zazyvala, filters=groups))
    app.add_handler(CommandHandler("all", cmd_all, filters=groups))
    app.add_handler(CommandHandler("anreg", cmd_anreg, filters=groups))
    app.add_handler(CommandHandler("reg", cmd_reg, filters=groups))

    # Кнопки
    app.add_handler(CallbackQueryHandler(on_callback))

    # Членство бота в группах
    app.add_handler(ChatMemberHandler(on_my_member, ChatMemberHandler.MY_CHAT_MEMBER))
    # Изменения участников (анти-снос)
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))

    # Новые участники
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))

    # Смена названия/фото группы (анти-снос)
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_TITLE | filters.StatusUpdate.NEW_CHAT_PHOTO | filters.StatusUpdate.DELETE_CHAT_PHOTO,
        on_chat_settings_change))

    # Сообщения в группах
    app.add_handler(MessageHandler(
        groups & (filters.TEXT | filters.CAPTION) & ~filters.StatusUpdate.ALL, on_group_message))

    # Текст в ЛС
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_private_text))

    app.add_error_handler(on_error)
    return app


def main():
    if not BOT_TOKEN:
        print("❌ Не задан BOT_TOKEN. На Railway добавь переменную BOT_TOKEN.")
        sys.exit(1)
    log.info("Запуск. Владельцы: %s. Конфиг: %s", ADMIN_IDS, CONFIG_PATH)
    app = build_app()
    if app.job_queue:
        app.job_queue.run_repeating(promo_job, interval=60, first=30)
    else:
        log.warning("JobQueue недоступен — авто-промо по таймеру работать не будет.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
