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
import io
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
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
)
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChatJoinRequestHandler,
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
        "words2": False,
        "clean_service": False,
    },
    "flood": {"limit": 5, "period": 10, "mute": 300},
    "stop_words": [
        "казино", "casino", "крипт", "ставк", "букмекер",
        "заработок", "заработай", "инвестиц", "1xbet", "1win", "mostbet",
        "порно", "porn", "интим",
    ],
    # Второй список слов — свой набор и СВОЁ наказание (мягче/строже первого).
    # action: delete|mute|ban. profile: искать слова ещё и в имени/юзернейме участника.
    "stop_words2": [],
    "stop_words2_action": "ban",
    "stop_words2_profile": True,
    "spam_links": [],
    "triggers": {"банан": "300 руб"},
    "trigger_match": "word",
    "moderation": {"warn_limit": 3, "warn_action": "mute", "warn_mute": 3600, "mod_admins_only": False, "log_actions": False, "warn_expire_days": 0, "notify_delete": False},
    # Анти-рейд: при всплеске входов включается строгий режим на время
    "antiraid": {"enabled": False, "joins": 8, "window": 60, "lock_min": 10},
    # Кто может выполнять команды (по группам). Уровни: all|admins|owner (создатель). Владелец/менеджеры бота — всегда.
    "cmd_perms": {"ban": "admins", "mute": "admins", "warn": "admins", "all": "admins", "settings": "admins"},
    # Медиа-фильтр: какие типы сообщений удалять у обычных участников
    "media_block": {"photo": False, "video": False, "animation": False, "sticker": False,
                    "voice": False, "video_note": False, "audio": False, "document": False, "forward": False},
    # Наказание медиа-фильтра: delete|mute|ban (что делать с отправителем заблокированного медиа)
    "media_action": "delete",
    # Ночной режим: в заданные часы сообщения обычных участников удаляются
    "night": {"enabled": False, "start": 23, "end": 7, "tz": 0},
    # Повторяющиеся авто-сообщения: [{"text": ..., "interval": минуты}]
    "recurring": [],
    # Кастомные роли модераторов: {имя: {"perms": [ban|mute|warn|all], "members": [user_id]}}
    "roles": {},
    # Staff-группа (служебный чат для уведомлений по этой группе); 0 — не задана
    "staff_group": 0,
    # Чёрный список пользователей этой группы: по ID и по подстрокам имени/юзернейма
    "blacklist": {"ids": [], "names": []},
    "welcome": {"enabled": False, "text": "Добро пожаловать, {name}! Рады видеть тебя в «{chat}».", "buttons": [], "delete_after": 0},
    # Язык сообщений для новичков (капча и т.п.): ru | uz | en
    "lang": "ru",
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
        "pin": False,
    },
    # Текст «зазывалы» — сообщения с кнопкой «Пригласить друга»
    "invite_text": "Нравится у нас? Зови друзей 👇",
    # Кто отписался от призывов /all: {chat_id: [user_ids]}
    "all_optout": {},
    # Правила группы (по умолчанию; у каждой группы могут быть свои)
    "rules": "Правила группы:\n1) Без спама и рекламы.\n2) Уважайте участников.\n3) Общайтесь по теме.",
    # Защита от сноса (анти-нюк)
    "antinuke": {"enabled": True, "ban_threshold": 5, "window": 30, "action": "stop"},
    # Капча для новичков: проверка «я не бот» на входе
    "captcha": {"enabled": False, "timeout": 120, "action": "kick", "via_request": True},
    # Показывать ID новичка при входе: "off" | "all" | "admins"
    "show_join_id": "off",
    # Глобальный допуск: бот работает в группе только после одобрения владельцем
    "require_approval": True,
    "approved_chats": [],
    # Подписчики ЛС по группам (кто прошёл капчу-заявку или запускал бота): {chat_id: [user_ids]}
    "dm_subscribers": {},
    # Запланированные посты (ежедневно в заданное время): список объектов
    "scheduled_posts": [],
    # Часовой пояс для расписания постов (смещение от UTC в часах)
    "post_tz": 5,
    # Глобальные списки на ВСЕ группы владельца
    "global_blacklist": {"ids": [], "names": []},
    "global_stop_words": [],
    # Время последнего предупреждения (для авто-сгорания): {chat: {uid: ts}}
    "warns_ts": {},
    # Индивидуальные настройки по чатам: {chat_id: {...только per-chat ключи...}}
    # Если для чата записи нет — используются глобальные настройки выше (как шаблон).
    "chats": {},
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
    ("words2", "Второй список слов (своё наказание)"),
    ("flood", "Антифлуд"),
    ("name_check", "Проверка имён при входе"),
    ("triggers", "Автоответы (ключевые слова)"),
    ("clean_service", "Чистить сервис-сообщения (вход/выход)"),
]

# ── Языки сообщений для новичков (капча и т.п.) ──────────────────────────────
LANGS = {"ru": "Русский 🇷🇺", "uz": "Oʻzbekcha 🇺🇿", "en": "English 🇺🇸"}
TR = {
    "cap_btn": {
        "ru": "✅ Я не бот",
        "uz": "✅ Men bot emasman",
        "en": "✅ I'm not a bot",
    },
    "cap_muted": {
        "ru": "👋 {name}, чтобы писать в этом чате, нажми кнопку ниже за {time}.",
        "uz": "👋 {name}, ushbu chatda yozish uchun {time} ichida quyidagi tugmani bosing.",
        "en": "👋 {name}, to write in this chat, press the button below within {time}.",
    },
    "cap_kick": {
        "ru": "👋 {name}, нажми кнопку ниже за {time}. До этого твои сообщения будут удаляться, "
              "а если не нажмёшь — удалю из чата.",
        "uz": "👋 {name}, {time} ichida quyidagi tugmani bosing. Shu vaqtgacha xabarlaringiz "
              "oʻchiriladi, bosmasangiz — chatdan chiqarib yuboraman.",
        "en": "👋 {name}, press the button below within {time}. Until then your messages will be "
              "deleted, and if you don't press it I'll remove you from the chat.",
    },
    "cap_ok": {
        "ru": "✅ Спасибо! Теперь можешь писать.",
        "uz": "✅ Rahmat! Endi yozishingiz mumkin.",
        "en": "✅ Thanks! You can write now.",
    },
    "cap_dm": {
        "ru": "👋 Привет! Ты хочешь вступить в «{chat}».\nНажми кнопку ниже, чтобы подтвердить, "
              "что ты не бот — и я впущу тебя.",
        "uz": "👋 Salom! Siz «{chat}» guruhiga qoʻshilmoqchisiz.\nBot emasligingizni tasdiqlash uchun "
              "quyidagi tugmani bosing — va men sizni qabul qilaman.",
        "en": "👋 Hi! You're requesting to join «{chat}».\nPress the button below to confirm you're "
              "not a bot, and I'll let you in.",
    },
    "cap_ok_dm": {
        "ru": "✅ Готово! Я впустил тебя в «{chat}». Добро пожаловать!",
        "uz": "✅ Tayyor! Sizni «{chat}» guruhiga qabul qildim. Xush kelibsiz!",
        "en": "✅ Done! I've let you into «{chat}». Welcome!",
    },
}


def tr(chat_id: int, key: str, **kw) -> str:
    """Перевод сообщения для новичков по языку группы (по умолчанию ru)."""
    lang = chat_cfg(chat_id).get("lang", "ru")
    s = TR.get(key, {}).get(lang) or TR.get(key, {}).get("ru", key)
    try:
        return s.format(**kw) if kw else s
    except Exception:  # noqa: BLE001
        return s

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


# Настройки, которые могут быть индивидуальными для каждой группы.
# Всё остальное (managers, groups, promo, approved_chats, invite_text, …) — глобальное.
PER_CHAT_KEYS = ("enabled", "flood", "stop_words", "stop_words2", "stop_words2_action",
                 "stop_words2_profile", "spam_links", "triggers",
                 "trigger_match", "moderation", "welcome", "captcha", "show_join_id",
                 "rules", "antinuke", "cmd_perms", "media_block", "media_action", "night", "recurring",
                 "roles", "staff_group", "lang", "blacklist", "antiraid")
PER_CHAT_DICTS = ("enabled", "flood", "moderation", "welcome", "captcha", "antinuke",
                  "cmd_perms", "media_block", "night", "roles", "blacklist", "antiraid")


def _fill_chat(chat: dict, base: dict) -> dict:
    """Полный набор per-chat настроек: берём из chat, недостающее — из base (шаблон)."""
    out = {}
    chat = chat if isinstance(chat, dict) else {}
    for k in PER_CHAT_KEYS:
        if k in PER_CHAT_DICTS:
            merged = copy.deepcopy(base.get(k, {}))
            if isinstance(chat.get(k), dict):
                merged.update(chat[k])
            out[k] = merged
        else:
            out[k] = copy.deepcopy(chat[k]) if k in chat else copy.deepcopy(base.get(k))
    return out


def _merge_defaults(data: dict) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return cfg
    for k, v in data.items():
        if k in ("enabled", "flood", "moderation", "welcome", "promo", "antinuke", "captcha", "cmd_perms", "media_block", "night", "roles", "blacklist", "antiraid") and isinstance(v, dict):
            cfg[k].update(v)
        else:
            cfg[k] = v
    # Нормализуем индивидуальные настройки чатов: добираем недостающие ключи из шаблона
    if isinstance(cfg.get("chats"), dict):
        cfg["chats"] = {str(cid): _fill_chat(c, cfg) for cid, c in cfg["chats"].items()}
    else:
        cfg["chats"] = {}
    return cfg


def _split_comma_triggers(d: dict) -> None:
    """Разбить старые автоответы вида «слово1, слово2»: один ключ → отдельные слова."""
    tr = d.get("triggers")
    if not isinstance(tr, dict):
        return
    if not any("," in k for k in tr):
        return
    new = {}
    for k, v in tr.items():
        if "," in k:
            for w in k.split(","):
                w = w.strip().lower()
                if w:
                    new[w] = v
        else:
            new[k] = v
    d["triggers"] = new


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cfg = _merge_defaults(raw)
            # Миграция при обновлении со старой версии: уже известные группы
            # автоматически считаем разрешёнными, чтобы бот в них не замолчал.
            # Новые чаты по-прежнему требуют одобрения владельца.
            if isinstance(raw, dict) and raw.get("groups") and not cfg.get("approved_chats"):
                cfg["approved_chats"] = [int(c) for c in raw["groups"].keys()]
            # Починка автоответов: старые «склеенные» ключи с запятой разбиваем на слова
            _split_comma_triggers(cfg)
            for ch in cfg.get("chats", {}).values():
                if isinstance(ch, dict):
                    _split_comma_triggers(ch)
            return cfg
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
stats_store: dict = defaultdict(lambda: defaultdict(int))  # chat_id -> {метрика: счётчик}
captcha_pending: dict = {}                # (chat_id, user_id) -> message_id капчи
_admin_cache: dict = {}
_creator_cache: dict = {}                 # chat_id -> id создателя группы (или None)
_recurring_last: dict = {}               # (chat_id, idx) -> метка последней отправки авто-сообщения
soft_mutes: dict = {}                    # (chat_id, user_id) -> до какого времени удалять сообщения (0 = до снятия)
join_dates: dict = {}                    # (chat_id, user_id) -> метка времени входа (для /info)
ADMIN_CACHE_TTL = 300


def soft_mute_add(chat_id: int, user_id: int, seconds: int = 0):
    """Мягкий мут: помечаем, что сообщения этого пользователя надо удалять (для обычных групп)."""
    soft_mutes[(chat_id, user_id)] = (time.time() + seconds) if seconds else 0.0


def soft_mute_remove(chat_id: int, user_id: int):
    soft_mutes.pop((chat_id, user_id), None)


def is_soft_muted(chat_id: int, user_id: int) -> bool:
    until = soft_mutes.get((chat_id, user_id))
    if until is None:
        return False
    if until and until <= time.time():
        soft_mutes.pop((chat_id, user_id), None)
        return False
    return True
_state = {"last_promo": 0.0}


def bump(chat_id: int, metric: str, n: int = 1) -> None:
    """Счётчик статистики в памяти (для /stats). Сбрасывается при рестарте."""
    stats_store[chat_id][metric] += n

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
    creator = None
    try:
        for a in await context.bot.get_chat_administrators(chat_id):
            ids.add(a.user.id)
            if a.status == "creator":
                creator = a.user.id
    except Exception as e:  # noqa: BLE001
        log.debug("get_chat_administrators(%s): %s", chat_id, e)
    _admin_cache[chat_id] = (now, ids)
    _creator_cache[chat_id] = creator
    return ids


async def group_creator_id(context, chat_id: int):
    """ID создателя (владельца) группы. Использует тот же кэш, что и список админов."""
    await group_admin_ids(context, chat_id)  # заполнит _creator_cache
    return _creator_cache.get(chat_id)


async def is_exempt(context, chat_id: int, user_id: int) -> bool:
    if is_manager(user_id):
        return True
    if user_id in await group_admin_ids(context, chat_id):
        return True
    return bool(user_roles(chat_id, user_id))  # участники кастомных ролей тоже не фильтруются


# Права, которые может выдавать кастомная роль
ROLE_PERM_DEFS = [
    ("ban", "🔨 Банить / кикать"),
    ("mute", "🔇 Мутить"),
    ("warn", "⚠️ Предупреждать"),
    ("all", "📣 Призыв /all"),
]
ROLE_PERM_KEYS = [k for k, _ in ROLE_PERM_DEFS]


def chat_roles(chat_id) -> dict:
    return chat_cfg(chat_id).get("roles", {}) or {}


def user_roles(chat_id, user_id: int):
    """Список имён ролей, в которых состоит человек в этой группе."""
    return [name for name, r in chat_roles(chat_id).items()
            if user_id in (r or {}).get("members", [])]


def role_grants(chat_id, user_id: int, key: str) -> bool:
    """True, если хотя бы одна роль человека даёт право key."""
    for name in user_roles(chat_id, user_id):
        if key in (chat_roles(chat_id).get(name) or {}).get("perms", []):
            return True
    return False


# Команды с настраиваемым уровнем доступа. (key, подпись, доступные уровни, по умолчанию)
CMD_DEFS = [
    ("ban",  "🔨 Бан / кик / разбан",        ["admins", "owner"], "admins"),
    ("mute", "🔇 Мут / размут",              ["admins", "owner"], "admins"),
    ("warn", "⚠️ Предупреждения",            ["admins", "owner"], "admins"),
    ("all",  "📣 Призыв /all",               ["all", "admins", "owner"], "admins"),
    ("settings", "⚙️ Кто открывает настройки", ["admins", "owner"], "admins"),
]
CMD_DEFAULT = {k: d for k, _, _, d in CMD_DEFS}
CMD_LEVELS = {k: lv for k, _, lv, _ in CMD_DEFS}
LEVEL_SHORT = {"all": "👥 все", "admins": "🛡 админы чата", "owner": "👑 создатель группы"}

# Типы вложений для медиа-фильтра
MEDIA_TYPES = [
    ("photo", "🖼 Фото"), ("video", "🎬 Видео"), ("animation", "🎞 GIF"),
    ("sticker", "🩷 Стикеры"), ("voice", "🎤 Голосовые"), ("video_note", "⭕ Кружки"),
    ("audio", "🎵 Аудио"), ("document", "📎 Файлы"), ("forward", "↩️ Пересланные"),
]


def cmd_level(chat_id, key: str) -> str:
    return chat_cfg(chat_id).get("cmd_perms", {}).get(key, CMD_DEFAULT.get(key, "admins"))


async def can_moderate(context, chat_id: int, user_id: int, key: str = "ban") -> bool:
    if is_manager(user_id):
        return True
    if chat_cfg(chat_id)["moderation"].get("mod_admins_only"):
        return False  # «Модерация только для владельца» — строгий режим (роли тоже не действуют)
    if role_grants(chat_id, user_id, key):
        return True  # кастомная роль выдала это право
    level = cmd_level(chat_id, key)
    if level == "all":
        return True
    if level == "owner":
        return user_id == await group_creator_id(context, chat_id)
    return user_id in await group_admin_ids(context, chat_id)  # admins


async def can_open_settings(context, chat_id: int, user_id: int) -> bool:
    """Может ли человек открывать настройки этой группы (не зависит от mod_admins_only)."""
    if is_manager(user_id):
        return True
    level = cmd_level(chat_id, "settings")
    if level == "owner":
        return user_id == await group_creator_id(context, chat_id)
    return user_id in await group_admin_ids(context, chat_id)  # admins


async def user_admin_groups(context, user_id: int):
    """Группы (cid_str, title), которыми человек вправе управлять через бота
    (он админ Telegram И ему разрешено открывать настройки этой группы)."""
    out = []
    for cid, title in CONFIG.get("groups", {}).items():
        try:
            if await can_open_settings(context, int(cid), user_id):
                out.append((cid, title))
        except Exception:  # noqa: BLE001
            continue
    return out


async def can_edit_target(context, user_id: int, target) -> bool:
    """Может ли человек править эту цель панели.
    Менеджер — что угодно. Иначе — это его группа и ему разрешено открывать её настройки."""
    if is_manager(user_id):
        return True
    if not target or target == "defaults":
        return False
    try:
        return await can_open_settings(context, int(target), user_id)
    except Exception:  # noqa: BLE001
        return False


def chat_allowed(chat_id: int) -> bool:
    """True, если бот допущен работать в этом чате (или допуск выключен)."""
    if not CONFIG.get("require_approval", True):
        return True
    return chat_id in CONFIG.get("approved_chats", [])


def chat_cfg(chat_id) -> dict:
    """Активные настройки чата: индивидуальные, если заданы, иначе глобальный шаблон."""
    cid = str(chat_id)
    chats = CONFIG.get("chats", {})
    if cid in chats:
        return chats[cid]
    return CONFIG  # глобальные настройки верхнего уровня = шаблон по умолчанию


def chat_cfg_writable(chat_id) -> dict:
    """Редактируемые настройки чата: при первом изменении копируем из шаблона."""
    cid = str(chat_id)
    chats = CONFIG.setdefault("chats", {})
    if cid not in chats:
        chats[cid] = {k: copy.deepcopy(CONFIG.get(k)) for k in PER_CHAT_KEYS}
    return chats[cid]


def panel_cfg(context) -> dict:
    """Редактируемый конфиг выбранной группы."""
    tgt = context.user_data.get("cfg_target")
    if tgt and tgt != "defaults":
        return chat_cfg_writable(int(tgt))
    return CONFIG  # запасной вариант, если группа не выбрана (UI этого не допускает)


def panel_cfg_view(context) -> dict:
    """Конфиг выбранной группы ТОЛЬКО для показа — без создания персональной копии."""
    tgt = context.user_data.get("cfg_target")
    if tgt and tgt != "defaults":
        return chat_cfg(int(tgt))
    return CONFIG


def panel_target_label(context) -> str:
    tgt = context.user_data.get("cfg_target")
    if not tgt or tgt == "defaults":
        return "— группа не выбрана —"
    title = CONFIG.get("groups", {}).get(str(tgt), str(tgt))
    return f"📂 {title}"


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
    for w in CONFIG.get("global_stop_words", []):  # глобальные стоп-слова (на все группы)
        if w and w.lower() in t:
            return w
    return None


def is_blacklisted(chat_id: int, user) -> bool:
    """Пользователь в чёрном списке — по ID или по подстроке имени/фамилии/юзернейма.
    Проверяется список группы И глобальный список (на все группы владельца)."""
    if user is None:
        return False
    uid = getattr(user, "id", None)
    prof = " ".join(filter(None, [getattr(user, "first_name", None),
                                   getattr(user, "last_name", None),
                                   getattr(user, "username", None)])).lower()
    for bl in (chat_cfg(chat_id).get("blacklist", {}) or {}, CONFIG.get("global_blacklist", {}) or {}):
        if uid in bl.get("ids", []):
            return True
        for n in bl.get("names", []):
            if n and n.lower() in prof:
                return True
    return False


def find_word2_violation(text: str, cfg: dict, user=None):
    """Второй список: ищем слово в тексте, а при включённой проверке профиля —
    ещё и в имени/фамилии/юзернейме отправителя."""
    words = cfg.get("stop_words2", [])
    if not words:
        return None
    t = (text or "").lower()
    for w in words:
        if w and w.lower() in t:
            return w
    if user is not None and cfg.get("stop_words2_profile", True):
        prof = " ".join(filter(None, [getattr(user, "first_name", None),
                                       getattr(user, "last_name", None),
                                       getattr(user, "username", None)])).lower()
        for w in words:
            if w and w.lower() in prof:
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
    """Мут участника. В супергруппе — настоящий мут. В обычной группе мут одного нельзя,
    поэтому включаем «мягкий мут»: сообщения этого пользователя будут удаляться."""
    until = None if not seconds else datetime.now(timezone.utc) + timedelta(seconds=seconds)
    try:
        await context.bot.restrict_chat_member(chat_id, user_id, permissions=MUTE_PERMS, until_date=until)
        soft_mute_remove(chat_id, user_id)  # настоящий мут — мягкий не нужен
    except Exception as e:  # noqa: BLE001
        log.debug("mute %s: %s → мягкий мут (обычная группа)", user_id, e)
        soft_mute_add(chat_id, user_id, int(seconds) if seconds else 0)


# ── предупреждения ──────────────────────────────────────────────────────────


def _warns_chat(chat_id):
    return CONFIG["warns"].setdefault(str(chat_id), {})


def get_warn(chat_id, uid):
    n = CONFIG["warns"].get(str(chat_id), {}).get(str(uid), 0)
    if n:
        days = chat_cfg(chat_id).get("moderation", {}).get("warn_expire_days", 0)
        if days:
            ts = CONFIG.get("warns_ts", {}).get(str(chat_id), {}).get(str(uid), 0)
            if ts and (time.time() - ts) > days * 86400:
                reset_warns(chat_id, uid)
                return 0
    return n


def inc_warn(chat_id, uid):
    w = _warns_chat(chat_id)
    w[str(uid)] = w.get(str(uid), 0) + 1
    CONFIG.setdefault("warns_ts", {}).setdefault(str(chat_id), {})[str(uid)] = time.time()
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


async def alert_staff(context, text):
    """Личное оповещение владельцам + менеджерам (у кого открыт ЛС с ботом)."""
    seen = set()
    for uid in list(ADMIN_IDS) + list(CONFIG.get("managers", [])):
        if uid in seen:
            continue
        seen.add(uid)
        try:
            await context.bot.send_message(uid, text)
        except Exception as e:  # noqa: BLE001
            log.debug("alert staff %s: %s", uid, e)


async def notify_staff(context, chat_id: int, text: str):
    """Служебное уведомление по группе: в её Staff-группу, если задана, иначе — в ЛС владельцам."""
    sg = chat_cfg(chat_id).get("staff_group", 0)
    if sg:
        try:
            await context.bot.send_message(sg, text)
            return
        except Exception as e:  # noqa: BLE001
            log.debug("notify staff group %s: %s", sg, e)
    await alert_owners(context, text)


async def log_action(context, chat_id: int, text: str):
    """Журнал действий: если включён, пишем событие модерации в staff-группу/владельцам."""
    if not chat_cfg(chat_id).get("moderation", {}).get("log_actions"):
        return
    title = CONFIG.get("groups", {}).get(str(chat_id), str(chat_id))
    await notify_staff(context, chat_id, f"📋 [{title}] {text}")


def _actor_name(update) -> str:
    u = update.effective_user
    return mention(u) if u else "—"


async def notify_deleted(context, chat_id: int, reason: str):
    """Короткое авто-удаляемое уведомление в чат, почему сообщение удалено (если включено)."""
    if not chat_cfg(chat_id).get("moderation", {}).get("notify_delete"):
        return
    try:
        m = await context.bot.send_message(chat_id, f"🗑 Сообщение удалено: {reason}.")
        if context.job_queue:
            context.job_queue.run_once(_delete_later, 5, data={"chat_id": chat_id, "mid": m.message_id})
    except Exception as e:  # noqa: BLE001
        log.debug("notify_deleted: %s", e)


def track_nuke(chat_id, actor_id):
    a = chat_cfg(chat_id)["antinuke"]
    now = time.time()
    dq = nuke_store[(chat_id, actor_id)]
    dq.append(now)
    while dq and now - dq[0] > a["window"]:
        dq.popleft()
    return len(dq)


# ───────────────────────────────────────────────────────────────────────────
#  СООБЩЕНИЯ В ГРУППАХ
# ───────────────────────────────────────────────────────────────────────────


async def _gate_unapproved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Замок: в неодобренных группах бот молчит (блокируем все прочие хендлеры).

    Группу всё равно запоминаем, чтобы владелец мог одобрить её из панели.
    Пропускаем диагностику (/diag) и служебные сообщения о миграции группы.
    """
    chat = update.effective_chat
    if chat is not None and getattr(chat, "type", None) in ("group", "supergroup"):
        remember_group(chat)
        if not chat_allowed(chat.id):
            msg = update.effective_message
            txt = (msg.text or "") if msg else ""
            if txt.startswith("/diag"):
                return  # диагностику пропускаем даже без одобрения
            if msg and (msg.migrate_to_chat_id or msg.migrate_from_chat_id):
                return  # миграцию группы пропускаем
            raise ApplicationHandlerStop


def _migrate_chat(old_id: int, new_id: int):
    """Перенести одобрение и настройки при апгрейде группы в супергруппу (id меняется)."""
    if old_id == new_id:
        return
    appr = CONFIG.setdefault("approved_chats", [])
    if old_id in appr and new_id not in appr:
        appr.append(new_id)
    o, n = str(old_id), str(new_id)
    for store in ("groups", "chats", "invite_links", "all_optout", "warns"):
        d = CONFIG.get(store)
        if isinstance(d, dict) and o in d and n not in d:
            d[n] = d.pop(o)
    save_config()
    log.info("Группа мигрировала: %s → %s", old_id, new_id)


async def on_migrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Апгрейд группы → супергруппа: переносим одобрение/настройки на новый chat_id."""
    msg = update.effective_message
    if not msg:
        return
    if msg.migrate_to_chat_id:
        _migrate_chat(update.effective_chat.id, msg.migrate_to_chat_id)
    elif msg.migrate_from_chat_id:
        _migrate_chat(msg.migrate_from_chat_id, update.effective_chat.id)


def message_media_type(msg) -> str:
    """Тип вложения сообщения для медиа-фильтра (или '' если это просто текст)."""
    if msg.photo:
        return "photo"
    if msg.video:
        return "video"
    if msg.animation:
        return "animation"
    if msg.sticker:
        return "sticker"
    if msg.voice:
        return "voice"
    if msg.video_note:
        return "video_note"
    if msg.audio:
        return "audio"
    if msg.document:
        return "document"
    return ""


def _is_forward(msg) -> bool:
    return bool(getattr(msg, "forward_origin", None) or getattr(msg, "forward_date", None))


def is_night_now(night: dict) -> bool:
    """Идут ли сейчас 'тихие часы' для группы (с учётом её часового пояса)."""
    if not night or not night.get("enabled"):
        return False
    start, end = night.get("start", 23), night.get("end", 7)
    if start == end:
        return False
    h = (datetime.now(timezone.utc) + timedelta(hours=night.get("tz", 0))).hour
    if start < end:
        return start <= h < end
    return h >= start or h < end  # окно через полночь


async def on_group_guard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ночной режим и медиа-фильтр. Удаляет сообщения обычных участников и
    останавливает дальнейшую обработку (чтобы не дублировать с антиспамом)."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or user.is_bot:
        return
    if not chat_allowed(chat.id):
        return
    if await is_exempt(context, chat.id, user.id):
        return
    # Чёрный список: баним и удаляем сообщение (по ID или имени)
    if is_blacklisted(chat.id, user):
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            bump(chat.id, "banned")
            log.info("Бан (чёрный список) от %s", user.id)
        except Exception as e:  # noqa: BLE001
            log.debug("blacklist ban msg: %s", e)
        raise ApplicationHandlerStop
    # Мягкий мут (обычная группа): удаляем сообщения замученного, пока мут не снят
    if is_soft_muted(chat.id, user.id):
        try:
            await msg.delete()
            bump(chat.id, "deleted")
        except Exception as e:  # noqa: BLE001
            log.debug("soft-mute delete: %s", e)
        raise ApplicationHandlerStop
    cfg = chat_cfg(chat.id)
    # Ночной режим
    if is_night_now(cfg.get("night", {})):
        try:
            await msg.delete()
            bump(chat.id, "deleted")
        except Exception as e:  # noqa: BLE001
            log.debug("night delete: %s", e)
        raise ApplicationHandlerStop
    # Медиа-фильтр
    mb = cfg.get("media_block", {})
    if mb:
        t = message_media_type(msg)
        blocked = (t and mb.get(t)) or (mb.get("forward") and _is_forward(msg))
        if blocked:
            try:
                await msg.delete()
                bump(chat.id, "deleted")
            except Exception as e:  # noqa: BLE001
                log.debug("media block: %s", e)
            action = cfg.get("media_action", "delete")
            if action in ("mute", "ban"):
                try:
                    if action == "ban":
                        await context.bot.ban_chat_member(chat.id, user.id)
                        bump(chat.id, "banned")
                    else:
                        await mute_user(context, chat.id, user.id, cfg["flood"]["mute"])
                        bump(chat.id, "muted")
                except Exception as e:  # noqa: BLE001
                    log.debug("media punish: %s", e)
            raise ApplicationHandlerStop


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

    cfg = chat_cfg(chat.id)

    reason = find_link_violation(text, cfg)
    if reason:
        try:
            await msg.delete()
            bump(chat.id, "deleted")
            log.info("Удалено (%s) от %s", reason, user.id)
        except Exception as e:  # noqa: BLE001
            log.debug("delete link: %s", e)
        await notify_deleted(context, chat.id, reason)
        return

    if cfg["enabled"].get("words2"):
        bad2 = find_word2_violation(text, cfg, user)
        if bad2:
            action = cfg.get("stop_words2_action", "ban")
            try:
                await msg.delete()
                bump(chat.id, "deleted")
            except Exception as e:  # noqa: BLE001
                log.debug("delete word2: %s", e)
            try:
                if action == "ban":
                    await context.bot.ban_chat_member(chat.id, user.id)
                    bump(chat.id, "banned")
                elif action == "mute":
                    await mute_user(context, chat.id, user.id, cfg["flood"]["mute"])
                    bump(chat.id, "muted")
            except Exception as e:  # noqa: BLE001
                log.debug("word2 punish: %s", e)
            log.info("Второй список ('%s', %s) от %s", bad2, action, user.id)
            return

    if cfg["enabled"].get("words"):
        bad = find_word_violation(text, cfg)
        if bad:
            try:
                await msg.delete()
                bump(chat.id, "deleted")
                log.info("Удалено (стоп-слово '%s') от %s", bad, user.id)
            except Exception as e:  # noqa: BLE001
                log.debug("delete word: %s", e)
            await notify_deleted(context, chat.id, "запрещённое слово")
            return

    if cfg["enabled"].get("flood") and check_flood(chat.id, user.id, cfg):
        try:
            await mute_user(context, chat.id, user.id, cfg["flood"]["mute"])
            bump(chat.id, "flood_muted")
            await msg.reply_text(f"🔇 {mention(user)} замучен на {cfg['flood']['mute']} сек за флуд.")
        except Exception as e:  # noqa: BLE001
            log.debug("flood mute: %s", e)
        return

    await maybe_send_trigger(update, context, text)


async def maybe_send_trigger(update, context, text):
    cfg = chat_cfg(update.effective_chat.id)
    if not cfg["enabled"].get("triggers"):
        return
    hit = match_trigger(text, cfg)
    if hit:
        try:
            await update.effective_message.reply_text(hit[1])
        except Exception as e:  # noqa: BLE001
            log.debug("trigger: %s", e)


async def send_welcome(context, chat, user):
    """Отправить приветствие новичку, если оно включено (с кнопками и авто-удалением)."""
    w = chat_cfg(chat.id)["welcome"]
    if not (w.get("enabled") and w.get("text")):
        return
    text = w["text"].replace("{name}", user.first_name or "друг").replace("{chat}", chat.title or "чат")
    markup = _post_buttons_markup(w.get("buttons"))
    try:
        m = await context.bot.send_message(chat.id, text, reply_markup=markup)
    except Exception as e:  # noqa: BLE001
        log.debug("welcome: %s", e)
        return
    secs = int(w.get("delete_after", 0) or 0)
    if secs and context.job_queue:
        context.job_queue.run_once(_delete_later, secs, data={"chat_id": chat.id, "mid": m.message_id})


async def announce_join_id(context, chat, user):
    """Показать Telegram ID новичка: всем в чате или только администрации (в ЛС)."""
    mode = chat_cfg(chat.id).get("show_join_id", "off")
    if mode not in ("all", "admins"):
        return
    uname = f"@{user.username}" if user.username else "—"
    full = " ".join(filter(None, [user.first_name, user.last_name])) or "пользователь"
    if mode == "all":
        try:
            await context.bot.send_message(
                chat.id,
                f"🆔 Новый участник: {html.escape(full)}\n"
                f"ID: <code>{user.id}</code> · юзернейм: {html.escape(uname)}\n"
                f"<i>ID не меняется — по нему всегда можно найти человека.</i>",
                parse_mode="HTML")
        except Exception as e:  # noqa: BLE001
            log.debug("join id (all): %s", e)
    else:  # admins
        await notify_staff(
            context, chat.id,
            f"🆔 В «{chat.title or chat.id}» зашёл: {full}\n"
            f"ID: {user.id} · юзернейм: {uname}")


async def start_captcha(context, chat, user) -> bool:
    """Просит новичка нажать «я не бот». В супергруппе — с мутом до нажатия,
    в обычной группе (где мут недоступен) — режим «кик, если не нажал». True — капча запущена."""
    c = chat_cfg(chat.id)["captcha"]
    muted = False
    try:
        await context.bot.restrict_chat_member(chat.id, user.id, permissions=MUTE_PERMS)
        muted = True
    except Exception as e:  # noqa: BLE001
        log.debug("captcha mute %s: %s (обычная группа — режим кика)", user.id, e)
    name = user.first_name or "друг"
    if muted:
        text = tr(chat.id, "cap_muted", name=html.escape(name), time=human_duration(c['timeout']))
    else:
        # обычная группа: мут одного нельзя — «мягкий мут» (удаляем сообщения) до нажатия/таймаута
        soft_mute_add(chat.id, user.id, c["timeout"] + 30)
        text = tr(chat.id, "cap_kick", name=html.escape(name), time=human_duration(c['timeout']))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(chat.id, "cap_btn"), callback_data=f"cap:{user.id}")]])
    try:
        sent = await context.bot.send_message(chat.id, text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        log.debug("captcha msg %s: %s", user.id, e)
        soft_mute_remove(chat.id, user.id)
        if muted:
            try:
                await context.bot.restrict_chat_member(chat.id, user.id, permissions=FULL_PERMS)
            except Exception:  # noqa: BLE001
                pass
        return False
    captcha_pending[(chat.id, user.id)] = sent.message_id
    if context.job_queue:
        context.job_queue.run_once(
            captcha_timeout, c["timeout"],
            data={"chat_id": chat.id, "user_id": user.id},
            name=f"cap:{chat.id}:{user.id}")
    return True


async def captcha_timeout(context: ContextTypes.DEFAULT_TYPE):
    """Время на капчу вышло — кик/бан новичка."""
    d = context.job.data
    chat_id, uid = d["chat_id"], d["user_id"]
    mid = captcha_pending.pop((chat_id, uid), None)
    if mid is None:
        return  # уже подтвердил
    soft_mute_remove(chat_id, uid)
    try:
        await context.bot.delete_message(chat_id, mid)
    except Exception:  # noqa: BLE001
        pass
    action = chat_cfg(chat_id)["captcha"].get("action", "kick")
    try:
        await context.bot.ban_chat_member(chat_id, uid)
        if action != "ban":
            await context.bot.unban_chat_member(chat_id, uid, only_if_banned=True)
        bump(chat_id, "captcha_fail")
        bump(chat_id, "banned" if action == "ban" else "kicked")
        log.info("Капча не пройдена (%s): %s", action, uid)
    except Exception as e:  # noqa: BLE001
        log.debug("captcha fail action %s: %s", uid, e)


def info_action_kb(tid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❗ Предупредить", callback_data=f"act:warn:{tid}"),
         InlineKeyboardButton("🔇 Мут 1ч", callback_data=f"act:mute:{tid}")],
        [InlineKeyboardButton("🔊 Размут", callback_data=f"act:unmute:{tid}"),
         InlineKeyboardButton("🚫 Бан", callback_data=f"act:ban:{tid}")],
        [InlineKeyboardButton("👥 Роли", callback_data=f"act:roles:{tid}")],
    ])


def info_roles_kb(chat_id: int, tid: int) -> InlineKeyboardMarkup:
    roles = chat_roles(chat_id)
    rows = []
    for i, name in enumerate(sorted(roles.keys())):
        inrole = tid in (roles[name] or {}).get("members", [])
        rows.append([InlineKeyboardButton(f"{'✅' if inrole else '➕'} {name}",
                                          callback_data=f"arole:{tid}:{i}")])
    if not rows:
        rows.append([InlineKeyboardButton("Ролей нет — создай в /panel → ▶️ Ещё → Роли", callback_data="noop")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"act:back:{tid}")])
    return InlineKeyboardMarkup(rows)


async def handle_action_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Кнопки действий под карточкой /info: предупредить / мут / размут / бан."""
    query = update.callback_query
    chat = update.effective_chat
    presser = update.effective_user
    data = query.data or ""

    # Роли с карточки: показать список, переключать членство (право — как на настройки)
    if data.startswith("arole:") or data.startswith("act:roles:") or data.startswith("act:back:"):
        try:
            tid = int(data.split(":")[-2]) if data.startswith("arole:") else int(data.split(":")[2])
        except Exception:  # noqa: BLE001
            return await query.answer()
        if not await can_open_settings(context, chat.id, presser.id):
            return await query.answer("Роли может назначать тот, кто настраивает группу", show_alert=True)
        if data.startswith("act:back:"):
            try:
                await query.edit_message_reply_markup(reply_markup=info_action_kb(tid))
            except Exception:  # noqa: BLE001
                pass
            return await query.answer()
        if data.startswith("arole:"):
            idx = int(data.split(":")[2])
            wcfg = chat_cfg_writable(chat.id)
            names = sorted((wcfg.get("roles", {}) or {}).keys())
            if idx < len(names):
                mem = wcfg["roles"][names[idx]].setdefault("members", [])
                if tid in mem:
                    mem.remove(tid)
                else:
                    if not is_manager(tid):
                        mem.append(tid)
                save_config()
        try:
            await query.edit_message_reply_markup(reply_markup=info_roles_kb(chat.id, tid))
        except Exception:  # noqa: BLE001
            pass
        return await query.answer()

    try:
        _, action, tid_s = data.split(":")
        tid = int(tid_s)
    except Exception:  # noqa: BLE001
        return await query.answer()
    key = {"warn": "warn", "mute": "mute", "unmute": "mute", "ban": "ban"}.get(action, "ban")
    if not await can_moderate(context, chat.id, presser.id, key):
        return await query.answer("Нет прав", show_alert=True)
    if action in ("ban", "mute") and (is_manager(tid) or tid in await group_admin_ids(context, chat.id)):
        return await query.answer("Это администратор/доверенный — не трогаю", show_alert=True)
    try:
        if action == "warn":
            n = inc_warn(chat.id, tid)
            bump(chat.id, "warns")
            m = chat_cfg(chat.id)["moderation"]
            if n >= m["warn_limit"]:
                reset_warns(chat.id, tid)
                if m["warn_action"] == "ban":
                    await context.bot.ban_chat_member(chat.id, tid)
                    bump(chat.id, "banned")
                    msg = f"{n}/{m['warn_limit']} — бан"
                else:
                    await mute_user(context, chat.id, tid, m["warn_mute"])
                    bump(chat.id, "muted")
                    msg = f"{n}/{m['warn_limit']} — мут"
            else:
                msg = f"предупреждение {n}/{m['warn_limit']}"
        elif action == "mute":
            await mute_user(context, chat.id, tid, 3600)
            bump(chat.id, "muted")
            msg = "мут на 1 час"
        elif action == "unmute":
            soft_mute_remove(chat.id, tid)
            try:
                await context.bot.restrict_chat_member(chat.id, tid, permissions=FULL_PERMS)
            except Exception:  # noqa: BLE001
                pass
            msg = "размучен"
        elif action == "ban":
            await context.bot.ban_chat_member(chat.id, tid)
            bump(chat.id, "banned")
            msg = "забанен"
        else:
            return await query.answer()
        await query.answer("✅ " + msg)
        try:
            base = query.message.text or "👤 Инфо"
            await query.edit_message_text(
                base + f"\n\n✅ {presser.first_name}: {msg}")
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        await query.answer(f"Не вышло: {e}", show_alert=True)


async def handle_setstaff_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажатие выбора главной группы при /setstaff (кнопка в staff-чате)."""
    query = update.callback_query
    user = update.effective_user
    try:
        _, main_s, staff_s = (query.data or "").split(":")
        main_id, staff_id = int(main_s), int(staff_s)
    except Exception:  # noqa: BLE001
        return await query.answer()
    if not await can_edit_target(context, user.id, str(main_id)):
        return await query.answer("Это не твоя группа", show_alert=True)
    chat_cfg_writable(main_id)["staff_group"] = staff_id
    save_config()
    await query.answer("Готово")
    title = CONFIG.get("groups", {}).get(str(main_id), str(main_id))
    try:
        await query.edit_message_text(
            f"✅ Этот чат теперь служебный для «{title}».\n"
            "Сюда будут приходить уведомления (новый админ, возможный снос, ID новичков и т.п.).")
    except Exception:  # noqa: BLE001
        pass


async def handle_captcha_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажатие кнопки «я не бот» новичком."""
    query = update.callback_query
    user = update.effective_user
    chat = update.effective_chat
    try:
        target = int((query.data or "").split(":")[1])
    except (IndexError, ValueError):
        return await query.answer()
    if user.id != target:
        return await query.answer("Это кнопка не для тебя 🙂", show_alert=True)
    mid = captcha_pending.pop((chat.id, user.id), None)
    if mid is None:
        return await query.answer("Уже подтверждено или время вышло.")
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(f"cap:{chat.id}:{user.id}"):
            job.schedule_removal()
    soft_mute_remove(chat.id, user.id)
    try:
        await context.bot.restrict_chat_member(chat.id, user.id, permissions=FULL_PERMS)
    except Exception as e:  # noqa: BLE001
        log.debug("captcha unmute %s: %s", user.id, e)
    try:
        await context.bot.delete_message(chat.id, mid)
    except Exception:  # noqa: BLE001
        pass
    bump(chat.id, "captcha_pass")
    await query.answer(tr(chat.id, "cap_ok"))
    await send_welcome(context, chat, user)


_join_handled: dict = {}  # (chat_id, user_id) -> ts последней обработки входа (антидубль)


def _join_seen(chat_id: int, user_id: int, window: int = 20) -> bool:
    """True, если этот вход уже обрабатывали недавно — чтобы капча не сработала дважды
    (и на сервис-сообщение «вошёл», и на событие chat_member)."""
    key = (chat_id, user_id)
    now = time.time()
    last = _join_handled.get(key)
    _join_handled[key] = now
    return last is not None and (now - last) < window


join_requests: dict = {}  # (chat_id, user_id) -> True, пока ждём прохождения капчи-заявки


def add_dm_subscriber(chat_id: int, user_id: int):
    """Запомнить, что у бота есть личка с этим человеком (для будущих рассылок от группы)."""
    subs = CONFIG.setdefault("dm_subscribers", {}).setdefault(str(chat_id), [])
    if user_id not in subs:
        subs.append(user_id)
        save_config()


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Заявка на вступление: пишем новичку капчу в ЛИЧКУ. Так капча работает в любой
    группе (мут не нужен), и человек оказывается в личке у бота."""
    jr = update.chat_join_request
    if not jr:
        return
    chat = jr.chat
    user = jr.from_user
    if not chat_allowed(chat.id):
        return
    cfg = chat_cfg(chat.id)
    cap = cfg["captcha"]
    if not (cap.get("enabled") and cap.get("via_request", True)):
        return  # капча-в-личке выключена — заявку обработает админ вручную
    if is_blacklisted(chat.id, user):
        try:
            await context.bot.decline_chat_join_request(chat.id, user.id)
            log.info("Заявка отклонена (чёрный список): %s", user.id)
        except Exception as e:  # noqa: BLE001
            log.debug("blacklist decline: %s", e)
        return
    if cfg["enabled"].get("name_check"):
        name = " ".join(filter(None, [user.first_name, user.last_name, user.username])).lower()
        if find_word_violation(name, cfg) or find_link_violation(name, cfg):
            try:
                await context.bot.decline_chat_join_request(chat.id, user.id)
            except Exception as e:  # noqa: BLE001
                log.debug("decline spam name: %s", e)
            return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(chat.id, "cap_btn"), callback_data=f"jrok:{chat.id}")]])
    try:
        await context.bot.send_message(jr.user_chat_id, tr(chat.id, "cap_dm", chat=chat.title or "группа"),
                                       reply_markup=kb)
    except Exception as e:  # noqa: BLE001
        log.debug("join-request dm %s: %s", user.id, e)
        return  # не смогли написать в личку — оставляем заявку админам
    join_requests[(chat.id, user.id)] = True
    if context.job_queue:
        context.job_queue.run_once(
            join_request_timeout, cap["timeout"],
            data={"chat_id": chat.id, "user_id": user.id}, name=f"jr:{chat.id}:{user.id}")


async def join_request_timeout(context: ContextTypes.DEFAULT_TYPE):
    d = context.job.data
    cid, uid = d["chat_id"], d["user_id"]
    if join_requests.pop((cid, uid), None) is None:
        return  # уже подтвердил
    try:
        await context.bot.decline_chat_join_request(cid, uid)
        log.info("Заявка отклонена (капча не пройдена): %s", uid)
    except Exception as e:  # noqa: BLE001
        log.debug("join-request timeout decline: %s", e)


async def handle_join_request_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Новичок нажал «я не бот» в личке — одобряем заявку и запоминаем его как подписчика."""
    query = update.callback_query
    user = update.effective_user
    try:
        cid = int((query.data or "").split(":")[1])
    except Exception:  # noqa: BLE001
        return await query.answer()
    try:
        await context.bot.approve_chat_join_request(cid, user.id)
    except Exception as e:  # noqa: BLE001
        log.debug("approve join-request %s: %s", user.id, e)
        return await query.answer("Не получилось, попробуй ещё раз позже", show_alert=True)
    join_requests.pop((cid, user.id), None)
    if context.job_queue:
        for job in context.job_queue.get_jobs_by_name(f"jr:{cid}:{user.id}"):
            job.schedule_removal()
    _join_seen(cid, user.id)            # чтобы в группе капча повторно не сработала
    add_dm_subscriber(cid, user.id)     # теперь ему можно слать рассылку от группы
    bump(cid, "captcha_pass")
    title = CONFIG.get("groups", {}).get(str(cid), "группу")
    await query.answer(tr(cid, "cap_ok"))
    try:
        await query.edit_message_text(tr(cid, "cap_ok_dm", chat=title))
    except Exception:  # noqa: BLE001
        pass
    try:
        class _C:
            id = cid
            title = CONFIG.get("groups", {}).get(str(cid), "")
        await send_welcome(context, _C(), user)
    except Exception as e:  # noqa: BLE001
        log.debug("welcome after approve: %s", e)


_raid_joins: dict = {}   # chat_id -> deque меток входов
_raid_until: dict = {}   # chat_id -> ts, до которого активен строгий режим


def _raid_tick(chat_id: int, ar: dict):
    """Регистрирует вход и говорит, активен ли рейд-режим. Возвращает (in_raid, just_started)."""
    now = time.time()
    window = int(ar.get("window", 60))
    dq = _raid_joins.setdefault(chat_id, deque())
    dq.append(now)
    while dq and now - dq[0] > window:
        dq.popleft()
    active = now < _raid_until.get(chat_id, 0)
    just = False
    if not active and len(dq) >= int(ar.get("joins", 8)):
        _raid_until[chat_id] = now + int(ar.get("lock_min", 10)) * 60
        active = True
        just = True
    return active, just


async def handle_join(context, chat, u):
    """Единая обработка входа новичка: проверка имени → капча или приветствие.
    Вызывается из сервис-сообщения (on_new_members) и из события chat_member
    (в супергруппе вход по ссылке приходит именно как chat_member, без сервис-сообщения)."""
    if u is None or getattr(u, "is_bot", False):
        return
    if _join_seen(chat.id, u.id):
        return
    if is_blacklisted(chat.id, u):
        try:
            await context.bot.ban_chat_member(chat.id, u.id)
            bump(chat.id, "name_bans")
            log.info("Бан при входе (чёрный список): %s", u.id)
        except Exception as e:  # noqa: BLE001
            log.debug("blacklist ban join: %s", e)
        return
    cfg = chat_cfg(chat.id)
    if cfg["enabled"].get("name_check"):
        name = " ".join(filter(None, [u.first_name, u.last_name, u.username])).lower()
        if find_word_violation(name, cfg) or find_link_violation(name, cfg):
            try:
                await context.bot.ban_chat_member(chat.id, u.id)
                bump(chat.id, "name_bans")
                log.info("Бан при входе (спам в имени): %s", u.id)
            except Exception as e:  # noqa: BLE001
                log.debug("ban new member: %s", e)
            return
    bump(chat.id, "joined")
    join_dates[(chat.id, u.id)] = time.time()
    # Анти-рейд: при всплеске входов включаем строгий режим — новичков мьютим
    ar = cfg.get("antiraid", {})
    if ar.get("enabled"):
        in_raid, just_started = _raid_tick(chat.id, ar)
        if just_started:
            await notify_staff(
                context, chat.id,
                f"🛡 Антирейд в «{chat.title or chat.id}»: всплеск входов "
                f"(≥{ar.get('joins', 8)} за {ar.get('window', 60)}с). Строгий режим на "
                f"{ar.get('lock_min', 10)} мин — новички мьютятся.")
        if in_raid:
            await mute_user(context, chat.id, u.id, int(ar.get("lock_min", 10)) * 60)
            await log_action(context, chat.id, f"🛡 антирейд: новичок {mention(u)} замьючен")
            return
    await announce_join_id(context, chat, u)
    if cfg["captcha"].get("enabled") and await start_captcha(context, chat, u):
        return  # приветствие — после прохождения капчи
    await send_welcome(context, chat, u)


async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return
    remember_group(chat)
    for u in msg.new_chat_members:
        await handle_join(context, chat, u)


async def on_service_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаляет сервис-сообщения (вошёл/вышел/закреп/смена фото и т.п.), если включено."""
    chat = update.effective_chat
    if not chat or not chat_cfg(chat.id)["enabled"].get("clean_service"):
        return
    msg = update.effective_message
    if not msg:
        return
    try:
        await msg.delete()
    except Exception as e:  # noqa: BLE001
        log.debug("clean service: %s", e)


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
        # Свежо добавили и чат ещё не одобрен — спрашиваем разрешение у владельца
        if old in ("left", "kicked") and CONFIG.get("require_approval", True) \
                and cm.chat.id not in CONFIG.get("approved_chats", []):
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Разрешить", callback_data=f"appr:ok:{cm.chat.id}"),
                InlineKeyboardButton("🚫 Не разрешать", callback_data=f"appr:no:{cm.chat.id}"),
            ]])
            for oid in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        oid,
                        f"🔔 Меня добавили в «{html.escape(cm.chat.title or str(cm.chat.id))}» "
                        f"(id <code>{cm.chat.id}</code>).\nКто добавил: {html.escape(mention(actor))}.\n\n"
                        f"Пока не разрешишь — я в этом чате ничего не делаю.",
                        reply_markup=kb, parse_mode="HTML")
                except Exception as e:  # noqa: BLE001
                    log.debug("approval ask %s: %s", oid, e)
        if old == "administrator" and status == "member" and chat_cfg(cm.chat.id)["antinuke"].get("enabled"):
            await alert_owners(
                context,
                f"⚠️ В «{cm.chat.title}» меня сняли с админки (кто: {mention(actor)}). "
                f"Пока не вернёшь права — защита и антиспам не работают.")
    elif status in ("left", "kicked"):
        if chat_cfg(cm.chat.id)["antinuke"].get("enabled"):
            await alert_owners(context, f"⚠️ Меня удалили из группы «{cm.chat.title}» (кто: {mention(actor)}).")
        forget_group(cm.chat.id)
        log.info("Бот удалён из группы %s", cm.chat.id)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анти-снос: следим за массовыми банами и назначением новых админов."""
    cm = update.chat_member
    if not cm:
        return
    chat = cm.chat
    # Кого-то повысили/сняли — сбросим кэш админов этой группы, чтобы права в панели
    # подхватились мгновенно (а не через ADMIN_CACHE_TTL).
    try:
        admin_roles = {"administrator", "creator"}
        was_admin = cm.old_chat_member.status in admin_roles
        is_admin = cm.new_chat_member.status in admin_roles
        if was_admin != is_admin:
            _admin_cache.pop(chat.id, None)
            _creator_cache.pop(chat.id, None)
    except Exception:  # noqa: BLE001
        pass
    if not chat_allowed(chat.id):
        return
    # Вход нового участника. В супергруппе вход по ссылке приходит сюда (chat_member),
    # а не сервис-сообщением — поэтому капчу/приветствие запускаем и отсюда.
    try:
        if (cm.new_chat_member.status == "member"
                and cm.old_chat_member.status in ("left", "kicked")):
            await handle_join(context, chat, cm.new_chat_member.user)
    except Exception as e:  # noqa: BLE001
        log.debug("chat_member join: %s", e)
    a = chat_cfg(chat.id)["antinuke"]
    if not a.get("enabled"):
        return
    actor = cm.from_user
    target = cm.new_chat_member.user
    new = cm.new_chat_member.status
    old = cm.old_chat_member.status
    if not actor or actor.id == context.bot.id:
        return

    # Новый админ — оповестить владельца
    if new == "administrator" and old not in ("administrator", "creator") and not is_manager(actor.id):
        await notify_staff(context, chat.id, f"⚠️ В «{chat.title}» новый админ: {mention(target)} (назначил {mention(actor)}).")
        return

    # Массовый бан — возможный снос
    if new == "kicked" and actor.id != target.id and not is_manager(actor.id):
        cnt = track_nuke(chat.id, actor.id)
        if cnt >= a["ban_threshold"]:
            nuke_store[(chat.id, actor.id)].clear()
            await notify_staff(
                context, chat.id,
                f"🚨 ВОЗМОЖНЫЙ СНОС в «{chat.title}»!\n"
                f"{mention(actor)} забанил {cnt}+ участников за {a['window']} сек.")
            if a["action"] == "stop":
                try:
                    await context.bot.ban_chat_member(chat.id, actor.id)
                    bump(chat.id, "banned")
                    await notify_staff(context, chat.id, f"✅ {mention(actor)} забанен — снос остановлен.")
                except Exception as e:  # noqa: BLE001
                    await notify_staff(
                        context, chat.id,
                        f"⚠️ Не смог сам забанить {mention(actor)}: {e}\nЗайди в группу и останови вручную.")


async def on_chat_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Оповещение при смене названия/фото группы."""
    chat = update.effective_chat
    if not chat or not chat_cfg(chat.id)["antinuke"].get("enabled"):
        return
    msg = update.effective_message
    if not msg:
        return
    who = mention(update.effective_user) if update.effective_user else "кто-то"
    if msg.new_chat_title:
        await notify_staff(context, chat.id, f"⚠️ В «{chat.title}» изменили название (кто: {who}).")
    elif msg.new_chat_photo:
        await notify_staff(context, chat.id, f"⚠️ В «{chat.title}» сменили фото группы (кто: {who}).")
    elif msg.delete_chat_photo:
        await notify_staff(context, chat.id, f"⚠️ В «{chat.title}» удалили фото группы (кто: {who}).")


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


async def _deny(update):
    """Ответить, что у пользователя недостаточно прав на команду (вместо молчания)."""
    try:
        await update.effective_message.reply_text("⛔ Недостаточно прав для этой команды.")
    except Exception:  # noqa: BLE001
        pass
    return None


async def _guard(update, context, key: str = "ban"):
    chat = update.effective_chat
    actor = update.effective_user
    if not await can_moderate(context, chat.id, actor.id, key):
        return await _deny(update)
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


async def cmd_reload(update, context):
    """Перечитать список админов/права этой группы прямо сейчас (ручная синхронизация)."""
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return
    # сбрасываем кэш ДО проверки прав, чтобы свеженазначенный админ тоже мог обновить
    _admin_cache.pop(chat.id, None)
    _creator_cache.pop(chat.id, None)
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return await _deny(update)
    await update.effective_message.reply_text("✅ Готово — список админов и права перечитаны.")


async def cmd_diag(update, context):
    """Диагностика в группе: почему бот не реагирует. Доступна админам/владельцу."""
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type == "private":
        if msg:
            await msg.reply_text("Команду /diag нужно вызвать в группе.")
        return
    user = update.effective_user
    if not (is_manager(user.id) or user.id in await group_admin_ids(context, chat.id)):
        return
    lines = [f"🔧 Диагностика · {chat.title}", f"chat_id: <code>{chat.id}</code> · тип: {chat.type}", ""]
    appr = chat_allowed(chat.id)
    lines.append(("✅" if appr else "🔴") +
                 (" Группа одобрена" if appr else " Группа НЕ одобрена → бот молчит. Реши в ЛС: /panel → 👥 Доступ → 🔐 Допуск чатов"))
    try:
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
        isadm = me.status in ("administrator", "creator")
        if isadm:
            lines.append("✅ Бот — администратор")
            cd = bool(getattr(me, "can_delete_messages", False))
            cr = bool(getattr(me, "can_restrict_members", False))
            lines.append(("✅" if cd else "🔴") + f" Право удалять сообщения: {'да' if cd else 'НЕТ'}")
            lines.append(("✅" if cr else "🔴") + f" Право банить/мутить: {'да' if cr else 'НЕТ'}")
        else:
            lines.append("🔴 Бот НЕ администратор → Telegram не отдаёт ему обычные сообщения "
                         "(privacy-mode), и он не может удалять/банить. Сделай бота админом с правами "
                         "удалять сообщения и банить.")
    except Exception as e:  # noqa: BLE001
        lines.append(f"⚠️ Не смог проверить статус бота: {e}")
    cfg = chat_cfg(chat.id)
    en = cfg["enabled"]
    lines += [
        "",
        f"Стоп-слова: {'вкл' if en.get('words') else 'выкл'} ({len(cfg['stop_words'])} шт)",
        f"Автоответы: {'вкл' if en.get('triggers') else 'выкл'} ({len(cfg['triggers'])} шт)",
        f"Антифлуд: {'вкл' if en.get('flood') else 'выкл'} · Капча: {'вкл' if cfg['captcha']['enabled'] else 'выкл'}",
        f"Настройки группы: {'свои' if str(chat.id) in CONFIG.get('chats', {}) else 'по умолчанию'}",
    ]
    if await is_exempt(context, chat.id, user.id):
        lines.append("\nℹ️ Ты админ/доверенный — на ТВОИ сообщения фильтры НЕ действуют. "
                     "Проверяй стоп-слова с обычного аккаунта (не админа).")
    if chat.type == "group":
        lines.append("\nℹ️ Это ОБЫЧНАЯ группа. Настоящий мут Telegram тут недоступен, поэтому мут работает "
                     "как «мягкий»: бот удаляет сообщения заглушённого (для /mute, мута за флуд/предупреждения и капчи). "
                     "Снаружи это как мут. Бан/кик/стоп-слова/автоответы работают как обычно. "
                     "Хочешь честный мут (человек вообще не сможет отправить сообщение) — сделай группу супергруппой "
                     "(можно приватной).")
    try:
        await msg.reply_text("\n".join(lines), parse_mode="HTML")
    except Exception:  # noqa: BLE001
        await msg.reply_text("\n".join(lines).replace("<code>", "").replace("</code>", ""))


async def cmd_ban(update, context):
    g = await _guard(update, context)
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    # необязательная длительность: /ban 1ч | 30м | 7д (иначе — навсегда)
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
    until = None if not duration else datetime.now(timezone.utc) + timedelta(seconds=duration)
    try:
        await context.bot.ban_chat_member(chat.id, tid, until_date=until)
        bump(chat.id, "banned")
        dur_txt = "навсегда" if not duration else f"на {human_duration(duration)}"
        await update.effective_message.reply_text(
            f"🚫 {tname} забанен {dur_txt}." + (f"\nПричина: {reason}" if reason else ""))
        await log_action(context, chat.id, f"🚫 бан {dur_txt}: {tname} (by {_actor_name(update)})"
                         + (f" — {reason}" if reason else ""))
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}\nПроверь, что я админ с правом банить.")


async def cmd_block(update, context):
    """В чёрный список по ID (ответом на сообщение или /block @user|id) + бан сразу."""
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban"):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text(
            "Кого в чёрный список? Ответь на его сообщение или /block @user (либо id). "
            "Имена добавляются в панели: ▶️ Ещё → 🚷 Чёрный список.")
        return
    if is_manager(tid) or tid in await group_admin_ids(context, chat.id):
        await update.effective_message.reply_text("Это администратор/доверенный — не добавляю.")
        return
    wcfg = chat_cfg_writable(chat.id)
    ids = wcfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("ids", [])
    if tid not in ids:
        ids.append(tid)
        save_config()
    try:
        await context.bot.ban_chat_member(chat.id, tid)
        bump(chat.id, "banned")
    except Exception as e:  # noqa: BLE001
        log.debug("block ban: %s", e)
    await update.effective_message.reply_text(
        f"🚷 {tname} в чёрном списке (ID {tid}). Если вернётся — забаню снова.")
    await log_action(context, chat.id, f"🚷 в чёрный список: {tname} (ID {tid}, by {_actor_name(update)})")


async def cmd_unblock(update, context):
    """Убрать из чёрного списка по ID (ответом или /unblock id) + разбан."""
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban"):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Кого убрать? Ответь на сообщение или /unblock id.")
        return
    wcfg = chat_cfg_writable(chat.id)
    ids = wcfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("ids", [])
    if tid in ids:
        ids.remove(tid)
        save_config()
    try:
        await context.bot.unban_chat_member(chat.id, tid, only_if_banned=True)
    except Exception as e:  # noqa: BLE001
        log.debug("unblock unban: %s", e)
    await update.effective_message.reply_text(f"✅ {tname} убран из чёрного списка.")
    await log_action(context, chat.id, f"✅ из чёрного списка: {tname} (by {_actor_name(update)})")


async def cmd_unban(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban"):
        return await _deny(update)
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
    g = await _guard(update, context, "ban")
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    try:
        await context.bot.ban_chat_member(chat.id, tid)
        await context.bot.unban_chat_member(chat.id, tid, only_if_banned=True)
        bump(chat.id, "kicked")
        await update.effective_message.reply_text(f"👢 {tname} удалён (сможет зайти заново).")
        await log_action(context, chat.id, f"👢 кик: {tname} (by {_actor_name(update)})")
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}")


async def cmd_mute(update, context):
    g = await _guard(update, context, "mute")
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
        bump(chat.id, "muted")
        dur_txt = "навсегда" if not duration else f"на {human_duration(duration)}"
        await update.effective_message.reply_text(
            f"🔇 {tname} в муте {dur_txt}." + (f"\nПричина: {reason}" if reason else ""))
        await log_action(context, chat.id, f"🔇 мут {dur_txt}: {tname} (by {_actor_name(update)})"
                         + (f" — {reason}" if reason else ""))
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}\nПроверь право ограничивать.")


async def cmd_unmute(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "mute"):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Кого размутить? Ответь на сообщение или /unmute @user")
        return
    soft_mute_remove(chat.id, tid)
    try:
        await context.bot.restrict_chat_member(chat.id, tid, permissions=FULL_PERMS)
    except Exception as e:  # noqa: BLE001
        log.debug("unmute restrict %s: %s", tid, e)  # обычная группа — хватило снятия мягкого мута
    await update.effective_message.reply_text(f"🔊 {tname} размучен.")
    await log_action(context, chat.id, f"🔊 размут: {tname} (by {_actor_name(update)})")


async def cmd_warn(update, context):
    g = await _guard(update, context, "warn")
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    reason = extract_reason(update, context)
    n = inc_warn(chat.id, tid)
    bump(chat.id, "warns")
    m = chat_cfg(chat.id)["moderation"]
    limit = m["warn_limit"]
    if n >= limit:
        reset_warns(chat.id, tid)
        try:
            if m["warn_action"] == "ban":
                await context.bot.ban_chat_member(chat.id, tid)
                bump(chat.id, "banned")
                await update.effective_message.reply_text(f"⚠️ {tname}: {n}/{limit} — бан.")
                await log_action(context, chat.id, f"⚠️→🚫 {n}/{limit} предупреждений → бан: {tname}")
            else:
                await mute_user(context, chat.id, tid, m["warn_mute"])
                bump(chat.id, "muted")
                await update.effective_message.reply_text(
                    f"⚠️ {tname}: {n}/{limit} — мут на {human_duration(m['warn_mute'])}.")
                await log_action(context, chat.id, f"⚠️→🔇 {n}/{limit} → мут: {tname}")
        except Exception as e:  # noqa: BLE001
            await update.effective_message.reply_text(f"Лимит достигнут, но наказать не вышло: {e}")
    else:
        await update.effective_message.reply_text(
            f"⚠️ {tname}: предупреждение {n}/{limit}." + (f"\nПричина: {reason}" if reason else ""))
        await log_action(context, chat.id, f"⚠️ пред {n}/{limit}: {tname} (by {_actor_name(update)})"
                         + (f" — {reason}" if reason else ""))


async def cmd_unwarn(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "warn"):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("С кого снять предупреждение? /unwarn @user")
        return
    n = dec_warn(chat.id, tid)
    await update.effective_message.reply_text(f"➖ {tname}: теперь {n} предупреждений.")


async def cmd_role(update, context):
    """Выдать человеку кастомную роль (ответом на его сообщение): /role Имя"""
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return
    user = update.effective_user
    if not await can_open_settings(context, chat.id, user.id):
        return await _deny(update)
    name = _args_text(update).strip()
    roles = chat_roles(chat.id)
    if not name:
        lst = ", ".join(roles.keys()) if roles else "ролей пока нет"
        await update.effective_message.reply_text(
            f"Ответь на сообщение человека и напиши: /role Имя\nРоли: {lst}\n"
            "Создать роль — в личке: /panel → ▶️ Ещё → Роли.")
        return
    key = next((k for k in roles if k.lower() == name.lower()), None)
    if not key:
        await update.effective_message.reply_text(f"Роли «{name}» нет. Создай её в панели (▶️ Ещё → Роли).")
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Ответь на сообщение человека, которому выдать роль.")
        return
    if is_manager(tid):
        await update.effective_message.reply_text("Это владелец/менеджер бота — роль не нужна.")
        return
    wcfg = chat_cfg_writable(chat.id)
    role = wcfg["roles"][key]
    members = role.setdefault("members", [])
    if tid in members:
        await update.effective_message.reply_text(f"{tname} уже в роли «{key}».")
        return
    members.append(tid)
    save_config()
    plabel = ", ".join(role.get("perms", [])) or "пока без прав (отметь их в панели)"
    await update.effective_message.reply_text(f"✅ {tname} теперь «{key}» (может: {plabel}).")


async def cmd_unrole(update, context):
    """Снять все кастомные роли с человека (ответом на сообщение): /unrole"""
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return
    user = update.effective_user
    if not await can_open_settings(context, chat.id, user.id):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Ответь на сообщение человека, с которого снять роль.")
        return
    wcfg = chat_cfg_writable(chat.id)
    removed = []
    for rname, r in wcfg.get("roles", {}).items():
        mem = r.get("members", [])
        if tid in mem:
            mem.remove(tid)
            removed.append(rname)
    if removed:
        save_config()
        await update.effective_message.reply_text(f"✅ С {tname} снято: {', '.join(removed)}.")
    else:
        await update.effective_message.reply_text(f"{tname} не состоит в кастомных ролях.")


async def cmd_setstaff(update, context):
    """Сделать ТЕКУЩИЙ чат служебным (staff) для одной из твоих групп: /setstaff"""
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return
    user = update.effective_user
    if not is_manager(user.id) and user.id not in await group_admin_ids(context, chat.id):
        return
    remember_group(chat)
    my = await user_admin_groups(context, user.id)
    targets = [(cid, t) for cid, t in my if int(cid) != chat.id]
    if not targets:
        await update.effective_message.reply_text(
            "Нет групп, которым этот чат можно назначить служебным. "
            "Сначала добавь бота в основную группу и стань там админом/владельцем.")
        return
    rows = [[InlineKeyboardButton(t if len(t) <= 30 else t[:29] + "…", callback_data=f"ss:{cid}:{chat.id}")]
            for cid, t in targets]
    await update.effective_message.reply_text(
        "Для какой группы сделать ЭТОТ чат служебным (сюда пойдут уведомления)?",
        reply_markup=InlineKeyboardMarkup(rows))


async def cmd_warns(update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "warn"):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Чьи предупреждения? /warns @user")
        return
    await update.effective_message.reply_text(
        f"{tname}: {get_warn(chat.id, tid)}/{chat_cfg(chat.id)['moderation']['warn_limit']} предупреждений.")


async def cmd_stats(update, context):
    """Статистика по текущей группе (с последнего перезапуска бота)."""
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id):
        return await _deny(update)
    s = stats_store.get(chat.id, {})
    active = len(members_store.get(chat.id, {}))
    warned_now = len(CONFIG["warns"].get(str(chat.id), {}))
    lines = [
        f"📊 Статистика «{chat.title or chat.id}»",
        "(с последнего перезапуска бота)",
        "",
        f"🗑 Удалено спама: {s.get('deleted', 0)}",
        f"🔇 Мутов за флуд: {s.get('flood_muted', 0)}",
        f"🚫 Банов: {s.get('banned', 0)} · 👢 киков: {s.get('kicked', 0)} · 🔇 мутов: {s.get('muted', 0)}",
        f"⚠️ Выдано предупреждений: {s.get('warns', 0)}",
        f"🪪 Бан по спам-имени: {s.get('name_bans', 0)}",
        f"🤖 Капча: прошли {s.get('captcha_pass', 0)} · не прошли {s.get('captcha_fail', 0)}",
        "",
        f"👥 Активных участников вижу: {active}",
        f"📌 Сейчас с предупреждениями: {warned_now}",
    ]
    await update.effective_message.reply_text("\n".join(lines))


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
        return await _deny(update)
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
        return await _deny(update)
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
    """Призыв: тихо тегнуть всех активных участников.

    Объявление остаётся в чате, а сами меншены идут «бегущей строкой» —
    каждая новая пачка удаляет предыдущую, чтобы не засорять чат. Уведомления
    при этом доходят: они срабатывают в момент отправки сообщения с упоминанием.
    """
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "all"):
        return await _deny(update)
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

    # убираем саму команду /all из чата
    try:
        await update.effective_message.delete()
    except Exception:  # noqa: BLE001
        pass

    # видимое объявление — остаётся в чате
    try:
        await context.bot.send_message(chat.id, f"📣 {html.escape(text)}", parse_mode="HTML")
    except Exception as e:  # noqa: BLE001
        log.debug("all announce: %s", e)

    # меншены «бегущей строкой»: каждая новая пачка удаляет предыдущую
    prev_id = None
    batch = []
    for i, (uid, name) in enumerate(targets, 1):
        batch.append(f'<a href="tg://user?id={uid}">{html.escape(name or "друг")}</a>')
        if len(batch) >= 5 or i == len(targets):
            try:
                sent = await context.bot.send_message(chat.id, " ".join(batch), parse_mode="HTML")
            except Exception as e:  # noqa: BLE001
                log.debug("all batch: %s", e)
                sent = None
            if prev_id is not None:
                try:
                    await context.bot.delete_message(chat.id, prev_id)
                except Exception:  # noqa: BLE001
                    pass
            prev_id = sent.message_id if sent else prev_id
            batch = []
            await asyncio.sleep(1)  # окно, чтобы успело прийти уведомление + анти-флуд

    # убираем последнюю пачку — в чате остаётся только объявление
    if prev_id is not None:
        await asyncio.sleep(1)
        try:
            await context.bot.delete_message(chat.id, prev_id)
        except Exception:  # noqa: BLE001
            pass


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
        return await _deny(update)
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
    chat = update.effective_chat
    await update.effective_message.reply_text(
        chat_cfg(chat.id).get("rules") or "Правила пока не заданы.")


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
    panel_cfg(context)["rules"] = text
    save_config()
    await update.effective_message.reply_text(
        f"✅ Правила сохранены ({panel_target_label(context)}).", reply_markup=rules_kb())


async def _post_to_chat(context, cid, text=None, photo_id=None, pin=False):
    """Опубликовать в группе текст или фото (с подписью), при желании — закрепить."""
    if photo_id:
        m = await context.bot.send_photo(int(cid), photo_id, caption=(text or None))
    else:
        m = await context.bot.send_message(int(cid), text)
    if pin:
        try:
            await context.bot.pin_chat_message(int(cid), m.message_id, disable_notification=True)
        except Exception as e:  # noqa: BLE001
            log.debug("pin %s: %s", cid, e)
    return m


async def _dm_broadcast(context, cid, text=None, photo_id=None):
    """Рассылка в ЛС подписчикам группы (кто прошёл капчу-заявку), от имени группы."""
    subs = list(CONFIG.get("dm_subscribers", {}).get(str(cid), []))
    title = CONFIG.get("groups", {}).get(str(cid), "группа")
    header = f"📢 От «{title}»:\n"
    body = header + (text or "")
    ok = fail = 0
    blocked = []
    for uid in subs:
        try:
            if photo_id:
                await context.bot.send_photo(uid, photo_id, caption=body)
            else:
                await context.bot.send_message(uid, body)
            ok += 1
        except Forbidden:
            fail += 1
            blocked.append(uid)  # человек заблокировал бота — уберём из подписчиков
        except Exception as e:  # noqa: BLE001
            fail += 1
            log.debug("dm-broadcast %s: %s", uid, e)
    if blocked:
        lst = CONFIG.setdefault("dm_subscribers", {}).get(str(cid), [])
        CONFIG["dm_subscribers"][str(cid)] = [u for u in lst if u not in blocked]
        save_config()
    return ok, fail


async def _broadcast(context, text=None, photo_id=None, pin=False):
    ok = fail = 0
    for cid in list(CONFIG["groups"].keys()):
        try:
            await _post_to_chat(context, cid, text, photo_id, pin)
            ok += 1
        except Forbidden:
            # Бота кикнули/заблокировали в этом чате — это навсегда, забываем группу
            fail += 1
            forget_group(int(cid))
            log.info("broadcast: забыта группа %s (Forbidden)", cid)
        except BadRequest as e:
            fail += 1
            if any(s in str(e).lower() for s in ("chat not found", "chat_id is empty", "group chat was upgraded")):
                forget_group(int(cid))
                log.info("broadcast: забыта группа %s (%s)", cid, e)
            else:
                log.debug("broadcast %s: %s", cid, e)
        except Exception as e:  # noqa: BLE001 — временные/сетевые ошибки: группу НЕ забываем
            fail += 1
            log.debug("broadcast %s (временная ошибка): %s", cid, e)
    return ok, fail


def _post_tz():
    return timezone(timedelta(hours=int(CONFIG.get("post_tz", 5))))


def _post_buttons_markup(buttons):
    """buttons: список [текст, url] → инлайн-клавиатура (по кнопке на строку)."""
    if not buttons:
        return None
    rows = []
    for b in buttons:
        try:
            txt, url = b[0], b[1]
            if txt and url:
                rows.append([InlineKeyboardButton(txt, url=url)])
        except Exception:  # noqa: BLE001
            continue
    return InlineKeyboardMarkup(rows) if rows else None


def _parse_buttons(text):
    """Каждая строка → кнопка-ссылка. Понимает «Текст - url», «Текст | url»,
    «Текст url», «Текст: url» и просто url. Ссылка делает кнопку кликабельной."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.search(r"(https?://\S+|tg://\S+|t\.me/\S+)", line)
        if not m:
            continue
        url = m.group(1)
        if url.startswith("t.me/"):
            url = "https://" + url
        txt = line[:m.start()].strip(" \t-|—–:•").strip()
        if not txt:
            txt = "Перейти"
        out.append([txt, url])
    return out


def _capture_post_content(message):
    """Извлечь из сообщения тип/файл/текст для будущей публикации."""
    cap = (message.caption or "").strip()
    if message.photo:
        return {"type": "photo", "file_id": message.photo[-1].file_id, "text": cap}
    if getattr(message, "video", None):
        return {"type": "video", "file_id": message.video.file_id, "text": cap}
    if getattr(message, "animation", None):
        return {"type": "animation", "file_id": message.animation.file_id, "text": cap}
    if getattr(message, "sticker", None):
        return {"type": "sticker", "file_id": message.sticker.file_id, "text": ""}
    if getattr(message, "document", None):
        return {"type": "document", "file_id": message.document.file_id, "text": cap}
    if getattr(message, "audio", None):
        return {"type": "audio", "file_id": message.audio.file_id, "text": cap}
    if getattr(message, "voice", None):
        return {"type": "voice", "file_id": message.voice.file_id, "text": cap}
    if getattr(message, "video_note", None):
        return {"type": "video_note", "file_id": message.video_note.file_id, "text": ""}
    if message.text:
        return {"type": "text", "file_id": None, "text": message.text}
    return None


# типы контента, которые НЕ поддерживают подпись/кнопки
_NO_CAPTION_TYPES = {"sticker", "video_note"}


def _post_chat_ids(post):
    """Список групп поста (поддержка и нового chat_ids, и старого chat_id)."""
    cids = post.get("chat_ids")
    if cids:
        return [int(c) for c in cids]
    if post.get("chat_id"):
        return [int(post["chat_id"])]
    return []


async def _send_one(context, cid, post):
    """Опубликовать пост в одну группу."""
    t = post.get("type", "text")
    text = post.get("text") or ""
    fid = post.get("file_id")
    markup = None if t in _NO_CAPTION_TYPES else _post_buttons_markup(post.get("buttons"))
    cap = None if t in _NO_CAPTION_TYPES else (text or None)
    b = context.bot
    if t == "text":
        m = await b.send_message(cid, text or "‎", reply_markup=markup)
    elif t == "photo":
        m = await b.send_photo(cid, fid, caption=cap, reply_markup=markup)
    elif t == "video":
        m = await b.send_video(cid, fid, caption=cap, reply_markup=markup)
    elif t == "animation":
        m = await b.send_animation(cid, fid, caption=cap, reply_markup=markup)
    elif t == "document":
        m = await b.send_document(cid, fid, caption=cap, reply_markup=markup)
    elif t == "audio":
        m = await b.send_audio(cid, fid, caption=cap, reply_markup=markup)
    elif t == "voice":
        m = await b.send_voice(cid, fid, caption=cap, reply_markup=markup)
    elif t == "video_note":
        m = await b.send_video_note(cid, fid)
    elif t == "sticker":
        m = await b.send_sticker(cid, fid)
    else:
        m = await b.send_message(cid, text or "‎")
    if post.get("pin"):
        try:
            await b.pin_chat_message(cid, m.message_id, disable_notification=True)
        except Exception as e:  # noqa: BLE001
            log.debug("sched pin %s: %s", cid, e)
    return m


async def _send_scheduled_post(context, post):
    """Опубликовать запланированный пост во все его группы."""
    last = None
    for cid in _post_chat_ids(post):
        try:
            last = await _send_one(context, cid, post)
        except Forbidden:
            log.info("Пост «%s»: нет доступа в %s", post.get("name"), cid)
        except Exception as e:  # noqa: BLE001
            log.warning("Пост «%s» в %s: %s", post.get("name"), cid, e)
    return last


async def _fire_scheduled_post(context):
    pid = context.job.data.get("id")
    post = _find_post(pid)
    if not post or not post.get("enabled", True):
        return
    try:
        await _send_scheduled_post(context, post)
        log.info("Запланированный пост «%s» опубликован", post.get("name"))
    except Forbidden:
        log.info("Пост «%s»: нет доступа в группу", post.get("name"))
    except Exception as e:  # noqa: BLE001
        log.warning("Пост «%s»: ошибка публикации: %s", post.get("name"), e)


def _find_post(pid):
    for p in CONFIG.get("scheduled_posts", []):
        if p.get("id") == pid:
            return p
    return None


def _new_post_id():
    n = 1
    existing = {p.get("id") for p in CONFIG.get("scheduled_posts", [])}
    while f"p{n}" in existing:
        n += 1
    return f"p{n}"


def _schedule_post(jq, post):
    if jq is None or not post.get("enabled", True):
        return
    try:
        h, m = map(int, str(post["time"]).split(":"))
    except Exception:  # noqa: BLE001
        return
    from datetime import time as _dtime
    jq.run_daily(_fire_scheduled_post, time=_dtime(h, m, tzinfo=_post_tz()),
                 data={"id": post["id"]}, name=f"sched:{post['id']}")


def _unschedule_post(jq, pid):
    if jq is None:
        return
    for job in jq.get_jobs_by_name(f"sched:{pid}"):
        job.schedule_removal()


def _reschedule_all_posts(jq):
    """Снять все задания постов и создать заново из конфига (после старта/смены пояса)."""
    if jq is None:
        return
    for job in list(jq.jobs()):
        if job.name and job.name.startswith("sched:"):
            job.schedule_removal()
    for p in CONFIG.get("scheduled_posts", []):
        _schedule_post(jq, p)


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


async def send_backup(context, chat_id: int):
    """Отправить config.json текущих настроек в чат (обычно ЛС владельца)."""
    try:
        raw = json.dumps(CONFIG, ensure_ascii=False, indent=2).encode("utf-8")
        bio = io.BytesIO(raw)
        bio.name = "config.json"
        await context.bot.send_document(
            chat_id, document=bio, filename="config.json", caption="💾 Полный бэкап настроек AntiSpam.")
    except Exception as e:  # noqa: BLE001
        log.debug("send backup: %s", e)
        try:
            await context.bot.send_message(chat_id, f"Не вышло отправить бэкап: {e}")
        except Exception:  # noqa: BLE001
            pass


def extract_chat_settings(cfg) -> dict:
    """Только per-chat ключи из конфига (для бэкапа одной группы/шаблона)."""
    return {k: copy.deepcopy(cfg[k]) for k in PER_CHAT_KEYS if k in cfg}


def apply_chat_settings(target, settings: dict):
    """Применить настройки к цели: 'defaults' (шаблон) или chat_id (конкретная группа)."""
    filled = _fill_chat(settings, CONFIG)  # недостающие ключи добираем из шаблона
    if target == "defaults":
        for k in PER_CHAT_KEYS:
            CONFIG[k] = filled[k]
    else:
        CONFIG.setdefault("chats", {})[str(target)] = filled
    save_config()


def _slug(label: str) -> str:
    s = "".join(c if c.isalnum() else "_" for c in label).strip("_")
    return (s[:40] or "group")


async def send_chat_backup(context, dm_chat_id: int, settings: dict, label: str):
    """Отправить файл с настройками одной группы/шаблона в ЛС."""
    payload = {"_type": "moriarty_chat_settings", "label": label, "settings": settings}
    fname = f"moriarty_{_slug(label)}.json"
    try:
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        bio = io.BytesIO(raw)
        bio.name = fname
        await context.bot.send_document(
            dm_chat_id, document=bio, filename=fname, caption=f"💾 Настройки: {label}")
    except Exception as e:  # noqa: BLE001
        log.debug("send chat backup: %s", e)
        try:
            await context.bot.send_message(dm_chat_id, f"Не вышло отправить бэкап: {e}")
        except Exception:  # noqa: BLE001
            pass


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


async def recurring_job(context: ContextTypes.DEFAULT_TYPE):
    """Повторяющиеся авто-сообщения по каждой группе (свои или из шаблона)."""
    now = time.time()
    for cid in list(CONFIG.get("groups", {}).keys()):
        chat_id = int(cid)
        if not chat_allowed(chat_id):
            continue
        items = chat_cfg(chat_id).get("recurring", []) or []
        for idx, it in enumerate(items):
            text = (it or {}).get("text")
            if not text:
                continue
            interval = max(60, int((it.get("interval") or 60)) * 60)
            key = (chat_id, idx)
            if key not in _recurring_last:
                _recurring_last[key] = now  # старт отсчёта, сразу не шлём
                continue
            if now - _recurring_last[key] >= interval:
                _recurring_last[key] = now
                try:
                    await context.bot.send_message(chat_id, text)
                except Exception as e:  # noqa: BLE001
                    log.debug("recurring send %s: %s", chat_id, e)


# ───────────────────────────────────────────────────────────────────────────
#  ПАНЕЛЬ (кнопки)
# ───────────────────────────────────────────────────────────────────────────


def main_menu_kb(target_label: str = "— группа —", full: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"⚙️ Настраиваю: {target_label}", callback_data="pick:list")],
        [InlineKeyboardButton("📊 Статус", callback_data="m:status"),
         InlineKeyboardButton("🔘 Функции", callback_data="m:toggles")],
        [InlineKeyboardButton("⚙️ Антифлуд", callback_data="m:flood"),
         InlineKeyboardButton("🛡 Модерация", callback_data="m:mod")],
        [InlineKeyboardButton("🛡 Анти-снос", callback_data="m:antinuke"),
         InlineKeyboardButton("👋 Приветствие", callback_data="m:welcome")],
        [InlineKeyboardButton("🤖 Капча", callback_data="m:captcha"),
         InlineKeyboardButton("💬 Автоответы", callback_data="m:triggers")],
        [InlineKeyboardButton("🚫 Стоп-слова", callback_data="m:words"),
         InlineKeyboardButton("🔗 Спам-ссылки", callback_data="m:links")],
        [InlineKeyboardButton("📜 Правила", callback_data="m:rules"),
         InlineKeyboardButton("▶️ Ещё", callback_data="m:other")],
    ]
    if full:  # глобальные разделы — только владельцу/менеджерам
        rows.append([InlineKeyboardButton("📣 Промо/Рассылка", callback_data="m:promo"),
                     InlineKeyboardButton("👥 Доступ", callback_data="m:access")])
    rows.append([InlineKeyboardButton("💾 Бэкап", callback_data="m:backup"),
                 InlineKeyboardButton("ℹ️ Помощь", callback_data="m:help")])
    return InlineKeyboardMarkup(rows)


def pick_kb(manager: bool = True, allowed=None) -> InlineKeyboardMarkup:
    """Выбор группы для настройки (📂 — уже настроена, ▫️ — по умолчанию)."""
    rows = []
    custom = set(CONFIG.get("chats", {}).keys())
    shown = 0
    for cid, title in sorted(CONFIG.get("groups", {}).items()):
        if allowed is not None and cid not in allowed:
            continue
        label = title if len(title) <= 26 else title[:25] + "…"
        mark = "📂" if cid in custom else "▫️"
        rows.append([InlineKeyboardButton(f"{mark} {label}", callback_data=f"pick:{cid}")])
        shown += 1
    if shown == 0:
        rows.append([InlineKeyboardButton("➕ Сначала добавь меня в группу", callback_data="noop")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def captcha_kb(cfg) -> InlineKeyboardMarkup:
    c = cfg["captcha"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Капча включена" if c["enabled"] else "🔴 Капча выключена", callback_data="cap_set:toggle")],
        [InlineKeyboardButton(f"Время на проверку: {human_duration(c['timeout'])}", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="cap_set:to:-"), InlineKeyboardButton("➕", callback_data="cap_set:to:+")],
        [InlineKeyboardButton(f"Если не прошёл: {'бан' if c['action'] == 'ban' else 'кик'}", callback_data="cap_set:action")],
        [InlineKeyboardButton(f"{'✅' if c.get('via_request', True) else '⬜'} Капча в личке (по заявке)",
                              callback_data="cap_set:viareq")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def backup_kb(owner: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("⬇️ Скачать настройки этой группы", callback_data="bk:gexport")],
        [InlineKeyboardButton("⬆️ Загрузить настройки в эту группу", callback_data="bk:gimport")],
    ]
    if owner:
        rows.append([InlineKeyboardButton("💾 Полный бэкап (весь бот)", callback_data="bk:export")])
        rows.append([InlineKeyboardButton("♻️ Восстановить всё из файла", callback_data="bk:import")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def antinuke_kb(cfg) -> InlineKeyboardMarkup:
    a = cfg["antinuke"]
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


def other_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Медиа-фильтр", callback_data="m:media"),
         InlineKeyboardButton("🌙 Ночной режим", callback_data="m:night")],
        [InlineKeyboardButton("🛑 Второй список слов", callback_data="m:words2"),
         InlineKeyboardButton("🚷 Чёрный список", callback_data="m:blacklist")],
        [InlineKeyboardButton("🔁 Авто-сообщения", callback_data="m:recurring"),
         InlineKeyboardButton("👥 Роли", callback_data="m:roles")],
        [InlineKeyboardButton("🛡 Staff-группа", callback_data="m:staff"),
         InlineKeyboardButton("🌐 Язык новичков", callback_data="m:lang")],
        [InlineKeyboardButton("🛡 Анти-рейд", callback_data="m:antiraid"),
         InlineKeyboardButton("🕹 Права на команды", callback_data="m:cmdperms")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def blacklist_kb(cfg) -> InlineKeyboardMarkup:
    bl = cfg.get("blacklist", {}) or {}
    rows = [
        [InlineKeyboardButton("➕ Добавить ID", callback_data="add:blid"),
         InlineKeyboardButton("➕ Добавить имя", callback_data="add:blname")],
    ]
    for i, uid in enumerate(bl.get("ids", [])):
        rows.append([InlineKeyboardButton(f"❌ ID {uid}", callback_data=f"dblid:{i}")])
    for i, nm in enumerate(bl.get("names", [])):
        rows.append([InlineKeyboardButton(f"❌ имя: {nm}", callback_data=f"dblname:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def blacklist_menu_text(cfg, target_label: str) -> str:
    bl = cfg.get("blacklist", {}) or {}
    return (
        f"🚷 Чёрный список · {target_label}\n\n"
        f"По ID: {len(bl.get('ids', []))} · по именам: {len(bl.get('names', []))}\n\n"
        "Кто попал в список — баню при входе (и при заявке отклоняю), а если он уже в группе и "
        "что-то пишет — баню и удаляю. «Имя» — это подстрока: ищется в имени, фамилии и юзернейме.\n\n"
        "Быстро добавить из чата: ответь на сообщение командой /block (по ID), /unblock — убрать."
    )


def antiraid_kb(cfg) -> InlineKeyboardMarkup:
    a = cfg.get("antiraid", {})
    on = a.get("enabled")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Анти-рейд включён" if on else "🔴 Анти-рейд выключен", callback_data="ar:toggle")],
        [InlineKeyboardButton(f"Порог входов: {a.get('joins', 8)}", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="ar:joins:-"), InlineKeyboardButton("➕", callback_data="ar:joins:+")],
        [InlineKeyboardButton(f"За период: {a.get('window', 60)} сек", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="ar:window:-"), InlineKeyboardButton("➕", callback_data="ar:window:+")],
        [InlineKeyboardButton(f"Строгий режим: {a.get('lock_min', 10)} мин", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="ar:lock:-"), InlineKeyboardButton("➕", callback_data="ar:lock:+")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:other")],
    ])


def antiraid_menu_text(cfg, target_label: str) -> str:
    a = cfg.get("antiraid", {})
    return (
        f"🛡 Анти-рейд · {target_label}\n\n"
        f"Статус: {'включён' if a.get('enabled') else 'выключен'}.\n"
        f"Срабатывает, если в группу за {a.get('window', 60)} сек заходит "
        f"≥ {a.get('joins', 8)} человек.\n"
        f"Тогда на {a.get('lock_min', 10)} мин включается строгий режим: новички "
        "автоматически мьютятся (их сообщения удаляются), а в staff приходит уведомление. "
        "Через это время режим выключается сам."
    )


def global_kb() -> InlineKeyboardMarkup:
    bl = CONFIG.get("global_blacklist", {}) or {}
    gw = CONFIG.get("global_stop_words", [])
    rows = [
        [InlineKeyboardButton("➕ ID в ЧС", callback_data="add:gbid"),
         InlineKeyboardButton("➕ имя в ЧС", callback_data="add:gbname")],
        [InlineKeyboardButton("➕ глоб. стоп-слово", callback_data="add:gword")],
    ]
    for i, uid in enumerate(bl.get("ids", [])):
        rows.append([InlineKeyboardButton(f"❌ ID {uid}", callback_data=f"dgbid:{i}")])
    for i, nm in enumerate(bl.get("names", [])):
        rows.append([InlineKeyboardButton(f"❌ имя: {nm}", callback_data=f"dgbname:{i}")])
    for i, w in enumerate(gw):
        rows.append([InlineKeyboardButton(f"❌ слово: {w}", callback_data=f"dgword:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:access")])
    return InlineKeyboardMarkup(rows)


def global_menu_text() -> str:
    bl = CONFIG.get("global_blacklist", {}) or {}
    gw = CONFIG.get("global_stop_words", [])
    return (
        "🌍 Глобальные списки (на ВСЕ твои группы)\n\n"
        f"Чёрный список: ID {len(bl.get('ids', []))}, имён {len(bl.get('names', []))}.\n"
        f"Стоп-слов: {len(gw)}.\n\n"
        "Кто/что здесь — действует сразу во всех группах бота: глобально забаненный "
        "отлетает при входе и при сообщении везде, а глобальные стоп-слова удаляются во "
        "всех чатах в дополнение к локальным. Удобно против спамеров, кочующих по группам.\n\n"
        "Быстро: ответь на сообщение командой /gblock — добавит в глобальный ЧС."
    )


def lang_kb(cfg) -> InlineKeyboardMarkup:
    cur = cfg.get("lang", "ru")
    rows = [[InlineKeyboardButton(("✅ " if code == cur else "") + name, callback_data=f"lang:{code}")]
            for code, name in LANGS.items()]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def lang_menu_text(cfg, target_label: str) -> str:
    cur = LANGS.get(cfg.get("lang", "ru"), "Русский")
    return (
        f"🌐 Язык для новичков · {target_label}\n\n"
        f"Сейчас: {cur}\n\n"
        "На этом языке бот пишет сообщения, которые видят новички (капча). "
        "Панель настроек остаётся на русском."
    )


def roles_kb(cfg) -> InlineKeyboardMarkup:
    roles = cfg.get("roles", {}) or {}
    rows = [[InlineKeyboardButton("➕ Создать роль", callback_data="add:role")]]
    for i, name in enumerate(sorted(roles.keys())):
        cnt = len((roles[name] or {}).get("members", []))
        rows.append([InlineKeyboardButton(f"✏️ {name} · {cnt} чел.", callback_data=f"rl:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def roles_menu_text(cfg, target_label: str) -> str:
    roles = cfg.get("roles", {}) or {}
    return (
        f"👥 Роли модераторов · {target_label}\n\n"
        f"Создано ролей: {len(roles)}\n\n"
        "Роль — это набор прав (банить/мутить/предупреждать), который выдаётся человеку "
        "БЕЗ назначения его админом Telegram. Создай роль, отметь права, потом в группе "
        "назначь людей командой /role Имя (ответом на сообщение). Снять — /unrole."
    )


def role_detail_kb(cfg, idx: int) -> InlineKeyboardMarkup:
    names = sorted((cfg.get("roles", {}) or {}).keys())
    if idx >= len(names):
        return roles_kb(cfg)
    r = cfg["roles"][names[idx]]
    perms = r.get("perms", [])
    rows = []
    for key, label in ROLE_PERM_DEFS:
        on = key in perms
        rows.append([InlineKeyboardButton(f"{'✅' if on else '❌'} {label}", callback_data=f"rp:{idx}:{key}")])
    for uid in (r.get("members", []) or [])[:15]:
        rows.append([InlineKeyboardButton(f"➖ убрать {uid}", callback_data=f"rm:{idx}:{uid}")])
    rows.append([InlineKeyboardButton("🗑 Удалить роль", callback_data=f"rdel:{idx}")])
    rows.append([InlineKeyboardButton("⬅️ К ролям", callback_data="m:roles")])
    return InlineKeyboardMarkup(rows)


def role_detail_text(cfg, idx: int, target_label: str) -> str:
    names = sorted((cfg.get("roles", {}) or {}).keys())
    if idx >= len(names):
        return "Роль не найдена."
    name = names[idx]
    r = cfg["roles"][name]
    perms = ", ".join(r.get("perms", [])) or "нет прав"
    return (
        f"✏️ Роль «{name}» · {target_label}\n\n"
        f"Права: {perms}\n"
        f"Людей в роли: {len(r.get('members', []))}\n\n"
        f"Отметь права галочками. Назначать людей — в группе командой /role {name} "
        "(ответом на сообщение)."
    )


def staff_kb(cfg) -> InlineKeyboardMarkup:
    rows = []
    if cfg.get("staff_group"):
        rows.append([InlineKeyboardButton("🔌 Отвязать staff-группу", callback_data="st:unset")])
    on = cfg.get("moderation", {}).get("log_actions")
    rows.append([InlineKeyboardButton(f"📋 Журнал действий: {'вкл' if on else 'выкл'}", callback_data="st:log")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def staff_menu_text(cfg, target_label: str) -> str:
    sg = cfg.get("staff_group", 0)
    cur = CONFIG.get("groups", {}).get(str(sg), str(sg)) if sg else "не задана"
    return (
        f"🛡 Staff-группа · {target_label}\n\n"
        f"Сейчас: {cur}\n\n"
        "Это отдельный чат для команды модераторов, куда бот шлёт служебные уведомления "
        "(новый админ, возможный снос, ID новичков и т.п.) вместо лички владельцу.\n\n"
        "Как привязать: создай отдельный чат, добавь туда бота, напиши там команду "
        "/setstaff и выбери эту группу."
    )


def media_kb(cfg) -> InlineKeyboardMarkup:
    mb = cfg.get("media_block", {})
    rows = []
    for key, label in MEDIA_TYPES:
        on = mb.get(key, False)
        rows.append([InlineKeyboardButton(f"{'🚫 удаляю' if on else '✅ можно'} · {label}", callback_data=f"mb:{key}")])
    act = cfg.get("media_action", "delete")
    act_ru = {"delete": "только удалить", "mute": "удалить + мут", "ban": "удалить + бан"}.get(act, act)
    rows.append([InlineKeyboardButton(f"⚙️ Наказание: {act_ru}", callback_data="mact")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def media_menu_text(cfg, target_label: str) -> str:
    act = cfg.get("media_action", "delete")
    act_ru = {"delete": "только удаляю сообщение", "mute": "удаляю и мучу отправителя",
              "ban": "удаляю и баню отправителя"}.get(act, act)
    return (
        f"🧹 Медиа-фильтр · {target_label}\n\n"
        "🚫 — этот тип удаляется у обычных участников, ✅ — разрешён. "
        "Админы и доверенные не затрагиваются.\n\n"
        f"⚙️ Наказание за заблокированное медиа: {act_ru}. Меняется кнопкой ниже.\n\n"
        "ℹ️ Это грубый фильтр по типу вложения. Распознавания «18+» по содержимому "
        "картинки здесь нет — для этого нужен внешний ИИ-классификатор."
    )


def night_kb(cfg) -> InlineKeyboardMarkup:
    n = cfg.get("night", {})
    tz = n.get("tz", 0)
    tzs = f"UTC{'+' if tz >= 0 else ''}{tz}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Включён" if n.get("enabled") else "🔴 Выключен", callback_data="nm:toggle")],
        [InlineKeyboardButton(f"С {n.get('start', 23):02d}:00", callback_data="noop"),
         InlineKeyboardButton("➖", callback_data="nm:start:-"),
         InlineKeyboardButton("➕", callback_data="nm:start:+")],
        [InlineKeyboardButton(f"До {n.get('end', 7):02d}:00", callback_data="noop"),
         InlineKeyboardButton("➖", callback_data="nm:end:-"),
         InlineKeyboardButton("➕", callback_data="nm:end:+")],
        [InlineKeyboardButton(f"Пояс: {tzs}", callback_data="noop"),
         InlineKeyboardButton("➖", callback_data="nm:tz:-"),
         InlineKeyboardButton("➕", callback_data="nm:tz:+")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:other")],
    ])


def night_menu_text(cfg, target_label: str) -> str:
    n = cfg.get("night", {})
    return (
        f"🌙 Ночной режим · {target_label}\n\n"
        f"Сейчас: {'включён' if n.get('enabled') else 'выключен'}\n"
        f"Тихие часы: с {n.get('start', 23):02d}:00 до {n.get('end', 7):02d}:00 "
        f"(пояс UTC{'+' if n.get('tz', 0) >= 0 else ''}{n.get('tz', 0)})\n\n"
        "В это время сообщения обычных участников удаляются (админы пишут свободно). "
        "Поставь часовой пояс под свой регион (например, Москва — UTC+3)."
    )


def recurring_kb(cfg) -> InlineKeyboardMarkup:
    items = cfg.get("recurring", []) or []
    rows = [[InlineKeyboardButton("➕ Добавить авто-сообщение", callback_data="add:recurring")]]
    for i, it in enumerate(items):
        txt = ((it or {}).get("text", "") or "")[:18]
        rows.append([InlineKeyboardButton(f"❌ {(it or {}).get('interval', '?')}м: {txt}", callback_data=f"rec:del:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def recurring_menu_text(cfg, target_label: str) -> str:
    items = cfg.get("recurring", []) or []
    return (
        f"🔁 Авто-сообщения · {target_label}\n\n"
        f"Сейчас настроено: {len(items)}\n\n"
        "Бот периодически сам публикует сообщение в группе. "
        "Добавляя, укажи интервал и текст в формате: минуты = текст\n"
        "Например: 120 = Не забывайте читать правила! /group"
    )


def cmdperms_kb(cfg) -> InlineKeyboardMarkup:
    perms = cfg.get("cmd_perms", {})
    rows = []
    for key, label, _levels, default in CMD_DEFS:
        cur = perms.get(key, default)
        rows.append([InlineKeyboardButton(f"{label}: {LEVEL_SHORT.get(cur, cur)}", callback_data=f"cp:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def cmdperms_menu_text(cfg, target_label: str) -> str:
    return (
        f"🕹 Права на команды · {target_label}\n\n"
        "Нажимай, чтобы переключить, кто может пользоваться:\n"
        "🛡 админы чата · 👑 только создатель группы · 👥 все участники.\n"
        "Владелец и менеджеры бота могут всё всегда.\n\n"
        "⚙️ «Кто открывает настройки» — кому доступна эта панель для группы.\n"
        "Это могут менять только создатель группы и владелец бота.\n\n"
        "ℹ️ Тумблер «Модерация только для владельца» (в разделе 🛡 Модерация) — "
        "строгий режим: тогда команды модерации доступны лишь владельцу/менеджерам бота."
    )


def toggles_kb(cfg) -> InlineKeyboardMarkup:
    rows = []
    for key, label in FEATURES:
        on = cfg["enabled"].get(key, False)
        rows.append([InlineKeyboardButton(f"{'✅' if on else '❌'} {label}", callback_data=f"tg:{key}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def triggers_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить ответ", callback_data="add:trigger")]]
    mode = cfg.get("trigger_match", "word")
    rows.append([InlineKeyboardButton(
        f"🔁 Режим: {'целое слово' if mode == 'word' else 'любое вхождение'}", callback_data="mode:trig")])
    for i, k in enumerate(sorted(cfg["triggers"].keys())):
        v = cfg["triggers"][k]
        prev = (v[:18] + "…") if len(v) > 18 else v
        rows.append([InlineKeyboardButton(f"❌ {k} → {prev}", callback_data=f"dt:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить слово", callback_data="add:word")]]
    for i, w in enumerate(sorted(cfg["stop_words"])):
        rows.append([InlineKeyboardButton(f"❌ {w}", callback_data=f"dw:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words2_kb(cfg) -> InlineKeyboardMarkup:
    act = cfg.get("stop_words2_action", "ban")
    act_ru = {"delete": "удалить", "mute": "мут", "ban": "бан"}.get(act, act)
    prof = cfg.get("stop_words2_profile", True)
    rows = [
        [InlineKeyboardButton("➕ Добавить слово", callback_data="add:word2")],
        [InlineKeyboardButton(f"⚙️ Наказание: {act_ru}", callback_data="w2act")],
        [InlineKeyboardButton(f"{'✅' if prof else '⬜'} Искать в профиле/имени: {'да' if prof else 'нет'}",
                              callback_data="w2prof")],
    ]
    for i, w in enumerate(sorted(cfg.get("stop_words2", []))):
        rows.append([InlineKeyboardButton(f"❌ {w}", callback_data=f"dw2:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:other")])
    return InlineKeyboardMarkup(rows)


def words2_menu_text(cfg, target_label: str) -> str:
    en = cfg["enabled"].get("words2")
    act = cfg.get("stop_words2_action", "ban")
    act_ru = {"delete": "удаляю сообщение", "mute": "удаляю и мучу", "ban": "удаляю и баню"}.get(act, act)
    prof = cfg.get("stop_words2_profile", True)
    return (
        f"🛑 Второй список слов · {target_label}\n\n"
        f"Статус: {'включён' if en else 'выключен'} (вкл/выкл — в разделе «Функции»).\n"
        f"Наказание: {act_ru}.\n"
        f"Поиск в профиле/имени: {'да' if prof else 'нет'}.\n\n"
        "Это отдельный список со своим, более строгим наказанием (в отличие от обычных "
        "стоп-слов, которые просто удаляются). Если включён поиск в профиле — слова "
        "ищутся ещё и в имени/юзернейме отправителя (ловит спам-профили)."
    )


def links_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить домен", callback_data="add:link")]]
    for i, d in enumerate(sorted(cfg["spam_links"])):
        rows.append([InlineKeyboardButton(f"❌ {d}", callback_data=f"dl:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def flood_kb(cfg) -> InlineKeyboardMarkup:
    f = cfg["flood"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"Лимит сообщений: {f['limit']}", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:limit:-"), InlineKeyboardButton("➕", callback_data="fl:limit:+")],
        [InlineKeyboardButton(f"Период: {f['period']} сек", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:period:-"), InlineKeyboardButton("➕", callback_data="fl:period:+")],
        [InlineKeyboardButton(f"Длительность мута: {f['mute']} сек", callback_data="noop")],
        [InlineKeyboardButton("➖", callback_data="fl:mute:-"), InlineKeyboardButton("➕", callback_data="fl:mute:+")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def mod_kb(cfg) -> InlineKeyboardMarkup:
    m = cfg["moderation"]
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
    exp = m.get("warn_expire_days", 0)
    rows.append([InlineKeyboardButton(
        f"⏳ Сгорание предов: {'выкл' if not exp else str(exp) + ' дн'}", callback_data="md:expire")])
    rows.append([InlineKeyboardButton(
        f"🗑 Сообщать о причине удаления: {'да' if m.get('notify_delete') else 'нет'}", callback_data="md:notify")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def welcome_kb(cfg) -> InlineKeyboardMarkup:
    w = cfg["welcome"]
    jid = cfg.get("show_join_id", "off")
    jid_label = {"off": "🆔 ID новичка: не показывать",
                 "all": "🆔 ID новичка: видно всем",
                 "admins": "🆔 ID новичка: только админам"}.get(jid, "🆔 ID новичка: не показывать")
    da = int(w.get("delete_after", 0) or 0)
    da_label = "выкл" if not da else human_duration(da)
    nb = len(w.get("buttons", []))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Включено" if w["enabled"] else "🔴 Выключено", callback_data="wl:toggle")],
        [InlineKeyboardButton("✏️ Изменить текст", callback_data="wl:edit")],
        [InlineKeyboardButton(f"🔘 Кнопки-ссылки: {nb}", callback_data="wl:btns")],
        [InlineKeyboardButton(f"⏱ Авто-удаление: {da_label}", callback_data="wl:del")],
        [InlineKeyboardButton(jid_label, callback_data="wl:joinid")],
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
        [InlineKeyboardButton(f"📌 Закреплять посты: {'да' if p.get('pin') else 'нет'}", callback_data="pr:pin")],
        [InlineKeyboardButton("💬 Рассылка подписчикам в ЛС", callback_data="dmcast:list")],
        [InlineKeyboardButton("🗓 Запланированные посты", callback_data="m:sched")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def post_groups_kb() -> InlineKeyboardMarkup:
    rows = []
    for i, (cid, title) in enumerate(sorted(CONFIG["groups"].items())):
        label = title if len(title) <= 30 else title[:29] + "…"
        rows.append([InlineKeyboardButton(f"📝 {label}", callback_data=f"pto:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:promo")])
    return InlineKeyboardMarkup(rows)


def dmcast_groups_kb() -> InlineKeyboardMarkup:
    rows = []
    for i, (cid, title) in enumerate(sorted(CONFIG["groups"].items())):
        n = len(CONFIG.get("dm_subscribers", {}).get(str(cid), []))
        label = title if len(title) <= 24 else title[:23] + "…"
        rows.append([InlineKeyboardButton(f"💬 {label} ({n} подп.)", callback_data=f"dmto:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:promo")])
    return InlineKeyboardMarkup(rows)


_POST_TYPE_RU = {"text": "текст", "photo": "фото", "video": "видео", "animation": "гиф",
                 "sticker": "стикер", "document": "документ", "audio": "аудио",
                 "voice": "голосовое", "video_note": "кружок"}


def _post_groups_label(post, maxlen=14):
    cids = _post_chat_ids(post)
    names = [CONFIG.get("groups", {}).get(str(c), str(c)) for c in cids]
    if not names:
        return "—"
    if len(names) == 1:
        t = names[0]
        return t if len(t) <= maxlen else t[:maxlen - 1] + "…"
    return f"{len(names)} групп"


def sched_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Новый пост", callback_data="sp:new")]]
    for p in CONFIG.get("scheduled_posts", []):
        flag = "🟢" if p.get("enabled", True) else "⚪"
        rows.append([InlineKeyboardButton(f"{flag} {p['name']} · {p['time']} → {_post_groups_label(p, 12)}",
                                          callback_data=f"spo:{p['id']}")])
    tz = CONFIG.get("post_tz", 5)
    rows.append([InlineKeyboardButton("🕐 −", callback_data="sptz:-"),
                 InlineKeyboardButton(f"пояс UTC+{tz}", callback_data="noop"),
                 InlineKeyboardButton("🕐 +", callback_data="sptz:+")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:promo")])
    return InlineKeyboardMarkup(rows)


def sched_menu_text() -> str:
    posts = CONFIG.get("scheduled_posts", [])
    tz = CONFIG.get("post_tz", 5)
    return (
        f"🗓 Запланированные посты · часовой пояс UTC+{tz}\n\n"
        f"Постов: {len(posts)}. Каждый выходит каждый день в своё время и в выбранные группы (можно несколько).\n\n"
        "Контент любой: текст, фото, видео, гиф, стикер, документ — плюс кнопки-ссылки и эмодзи. "
        "Нажми на пост, чтобы включить/выключить, закрепление или удалить.\n\n"
        "⚠️ Расписание переживает перезапуск только при подключённом Volume."
    )


def sched_post_kb(p) -> InlineKeyboardMarkup:
    pid = p["id"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Включён" if p.get("enabled", True) else "⚪ Выключен",
                              callback_data=f"spt:{pid}")],
        [InlineKeyboardButton(f"📌 Закреплять: {'да' if p.get('pin') else 'нет'}", callback_data=f"spp:{pid}")],
        [InlineKeyboardButton("🗑 Удалить пост", callback_data=f"spd:{pid}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:sched")],
    ])


def sched_post_text(p) -> str:
    cids = _post_chat_ids(p)
    names = [CONFIG.get("groups", {}).get(str(c), str(c)) for c in cids]
    groups = ", ".join(names) if names else "—"
    btns = p.get("buttons") or []
    preview = (p.get("text") or "").strip().replace("\n", " ")
    preview = preview[:60] + "…" if len(preview) > 60 else preview
    txt = (
        f"📨 Пост «{p['name']}»\n"
        f"Группы ({len(names)}): {groups}\n"
        f"Время: каждый день в {p['time']} (UTC+{CONFIG.get('post_tz', 5)})\n"
        f"Тип: {_POST_TYPE_RU.get(p.get('type'), 'пост')} · кнопок: {len(btns)}\n"
    )
    if preview:
        txt += f"Текст: {preview}\n"
    return txt


def sched_groups_kb(selected=None) -> InlineKeyboardMarkup:
    selected = set(int(c) for c in (selected or []))
    rows = []
    for i, (cid, title) in enumerate(sorted(CONFIG["groups"].items())):
        mark = "✅ " if int(cid) in selected else "☐ "
        label = title if len(title) <= 26 else title[:25] + "…"
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"spg:{i}")])
    if selected:
        rows.append([InlineKeyboardButton(f"Готово → выбрано: {len(selected)}", callback_data="spgo")])
    rows.append([InlineKeyboardButton("⬅️ Отмена", callback_data="m:sched")])
    return InlineKeyboardMarkup(rows)


def access_kb() -> InlineKeyboardMarkup:
    rows = []
    for i, uid in enumerate(CONFIG["managers"]):
        rows.append([InlineKeyboardButton(f"❌ убрать {uid}", callback_data=f"dm:{i}")])
    rows.append([InlineKeyboardButton("🔐 Допуск чатов", callback_data="m:approve")])
    rows.append([InlineKeyboardButton("🌍 Глобальные списки", callback_data="m:global")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def approve_kb() -> InlineKeyboardMarkup:
    req = CONFIG.get("require_approval", True)
    rows = [[InlineKeyboardButton(
        "🔒 Требовать одобрение: ВКЛ" if req else "🔓 Требовать одобрение: ВЫКЛ",
        callback_data="apt:toggle")]]
    appr = set(CONFIG.get("approved_chats", []))
    for cid, title in sorted(CONFIG["groups"].items()):
        cid_i = int(cid)
        label = title if len(title) <= 22 else title[:21] + "…"
        if cid_i in appr:
            rows.append([InlineKeyboardButton(f"✅ {label}", callback_data=f"appr:no:{cid_i}")])
        else:
            rows.append([InlineKeyboardButton(f"⛔ {label} — разрешить", callback_data=f"appr:ok:{cid_i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def approve_menu_text() -> str:
    req = CONFIG.get("require_approval", True)
    n = len(CONFIG.get("approved_chats", []))
    return (
        "🔐 Допуск чатов.\n\n"
        f"Требовать одобрение: {'включено' if req else 'выключено'}\n"
        f"Разрешённых чатов: {n}\n\n"
        "Когда включено, в новых группах бот молчит, пока ты не нажмёшь «разрешить». "
        "✅ — чат разрешён (нажми, чтобы отозвать). ⛔ — нажми, чтобы разрешить.\n\n"
        "Выключишь — бот будет работать во всех группах, куда его добавили."
    )


def status_text(cfg, target_label: str = "— группа —", show_global: bool = True) -> str:
    en = cfg["enabled"]
    f = cfg["flood"]
    m = cfg["moderation"]
    p = CONFIG["promo"]
    lines = [f"📊 Статус · {target_label}", ""]
    for key, label in FEATURES:
        lines.append(f"{'🟢' if en.get(key) else '🔴'} {label}")
    who = "только владелец" if m["mod_admins_only"] else "админы чата"
    pun = "бан" if m["warn_action"] == "ban" else f"мут {human_duration(m['warn_mute'])}"
    jid_label = {"off": "не показывать", "all": "видно всем", "admins": "только админам"}.get(
        cfg.get("show_join_id", "off"), "не показывать")
    appr_label = "требуется одобрение" if CONFIG.get("require_approval", True) else "свободный"
    lines += [
        "",
        f"Антифлуд: {f['limit']}/{f['period']}с → мут {f['mute']}с",
        f"Предупреждения: {m['warn_limit']} → {pun} · модерируют: {who}",
        f"Приветствие: {'вкл' if cfg['welcome']['enabled'] else 'выкл'}",
        f"Капча: {'вкл' if cfg['captcha']['enabled'] else 'выкл'} ({human_duration(cfg['captcha']['timeout'])}, {'бан' if cfg['captcha']['action'] == 'ban' else 'кик'})",
        f"ID новичка: {jid_label}",
        f"Стоп-слов: {len(cfg['stop_words'])} · доменов: {len(cfg['spam_links'])} · автоответов: {len(cfg['triggers'])}",
    ]
    if show_global:
        lines += [
            "",
            "— общее по боту —",
            f"Допуск чатов: {appr_label} (разрешено: {len(CONFIG.get('approved_chats', []))})",
            f"Авто-промо: {'вкл' if p['enabled'] else 'выкл'} (каждые {human_duration(p['interval'])})",
            f"Групп на учёте: {len(CONFIG['groups'])} · своя настройка у: {len(CONFIG.get('chats', {}))} · доступ выдан: {len(CONFIG['managers'])}",
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


def antinuke_menu_text(cfg) -> str:
    a = cfg["antinuke"]
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


def rules_menu_text(cfg) -> str:
    return (
        "📜 Правила группы.\n\n"
        "Участники смотрят их командой /group в чате.\n\n"
        "Сейчас:\n" + (cfg.get("rules") or "—")
    )


def captcha_menu_text(cfg) -> str:
    c = cfg["captcha"]
    act = "бан" if c["action"] == "ban" else "кик (сможет зайти заново)"
    return (
        "🤖 Капча для новичков.\n\n"
        f"Статус: {'включена' if c['enabled'] else 'выключена'}\n"
        f"Время на проверку: {human_duration(c['timeout'])}\n"
        f"Если не прошёл: {act}\n\n"
        "Новичок при входе не может писать, пока не нажмёт «Я не бот». "
        "Не успел за отведённое время — применяю действие выше.\n\n"
        "Боту нужно право «Ограничивать участников». Создателя группы Telegram "
        "ограничить нельзя, поэтому к нему капча не применяется.\n\n"
        "ℹ️ В супергруппе новичок реально не может писать до нажатия. В обычной группе настоящий "
        "мут недоступен, поэтому до нажатия его сообщения удаляются (мягкий мут), а если не нажал "
        "вовремя — удаляю из чата. Тип группы покажет /diag.\n\n"
        "🔗 «Капча в личке (по заявке)»: если в настройках группы включить ссылку «с заявкой на "
        "вступление» (Request Admin Approval), бот будет писать новичку капчу В ЛИЧКУ и впускать "
        "после нажатия. Работает в любой группе, и человек попадает в личку бота (можно потом "
        "слать рассылку от группы). Бот должен быть админом с правом добавлять/одобрять участников."
    )


def backup_menu_text(label: str = "— группа —", owner: bool = False) -> str:
    t = (
        f"💾 Бэкап настроек · сейчас: {label}\n\n"
        "«Скачать настройки этой группы» — пришлю файл с настройками выбранной цели "
        "(стоп-слова, автоответы, приветствие, капча, правила, лимиты, анти-снос…).\n\n"
        "«Загрузить» — пришли такой файл, и я применю его к выбранной цели "
        "(можно перенести настройки из одной группы в другую).\n\n"
        "Переключить, что настраиваешь, — кнопкой «Настраиваю: …» в главном меню.\n"
    )
    if owner:
        t += ("\n💾 Полный бэкап — весь бот сразу (все группы + менеджеры + допуски + промо). "
              "Удобно при переносе и если на хостинге слетают настройки при пересборке.")
    return t


HELP_TEXT = (
    "ℹ️ Управление (в ЛС): /panel /status /id\n\n"
    "⚙️ У каждой группы могут быть СВОИ настройки. В панели сверху кнопка "
    "«Настраиваю: …» — выбери конкретную группу, и дальше всё "
    "(стоп-слова, приветствие, капча, правила и т.д.) применяется именно к ней.\n\n"
    "Автоответы: /add слово = ответ · /del · /list\n"
    "Стоп-слова (чёрный список, удаляются): /addword · /delword · /words\n"
    "Спам-домены: /addlink · /dellink · /links\n"
    "Приветствие: /setwelcome текст ({name}, {chat})\n"
    "Правила: /setrules текст\n"
    "(команды выше меняют ту цель, что выбрана в панели сверху)\n\n"
    "🛡 Модерация (в группе, для админов чата):\n"
    "/ban /unban /kick · /mute [время] /unmute · /warn /unwarn /warns · /stats\n"
    "/userid — узнать ID (ответом на сообщение — ID автора)\n"
    "/info — карточка пользователя + кнопки (предупредить/мут/бан) (ответом)\n"
    "/reload — перечитать админов/права прямо сейчас (в группе)\n"
    "/diag — диагностика в группе: почему бот не реагирует (одобрена ли, админ ли бот, права)\n"
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
    "🛡 Защита от сноса — в панели «Анти-снос».\n"
    "🕹 Кто какие команды может (и кто открывает настройки) — панель → ▶️ Ещё → «Права на команды».\n"
    "🧹 Медиа-фильтр, 🌙 ночной режим (тихие часы) и 🔁 авто-сообщения — там же, в ▶️ Ещё.\n"
    "👥 Роли модераторов (выдать частичные права без админки Telegram) — ▶️ Ещё → Роли; "
    "назначать в группе: /role Имя (ответом), снять — /unrole.\n"
    "🛡 Staff-группа (служебный чат для уведомлений): в отдельном чате с ботом напиши /setstaff.\n"
    "🤖 Капча для новичков и 🆔 показ ID новичка — в панели.\n"
    "💾 Бэкап: «Скачать/Загрузить настройки этой группы» (по выбранной цели). "
    "Полный бэкап всего бота — у главного владельца.\n\n"
    "👥 Доступ (только главный владелец):\n"
    "/grant — выдать права · /revoke — забрать · /managers — список\n"
    "🔐 Допуск чатов (панель → Доступ): бот молчит в новых группах, "
    "пока ты их не разрешишь.\n\n"
    "Боту в группе нужны права: удалять сообщения, блокировать, "
    "ограничивать участников и приглашать пользователей (для ссылок)."
)


GROUPADMIN_HELP = (
    "ℹ️ Ты администратор группы — можешь настраивать СВОИ группы (где ты админ и где есть бот).\n\n"
    "Открой /panel. Сверху кнопка «Настраиваю: …» — выбери свою группу, "
    "дальше можно менять: функции, антифлуд, модерацию, анти-снос, приветствие, "
    "капчу, ключевые слова (автоответы), стоп-слова, спам-домены, правила.\n\n"
    "💾 Бэкап → «Скачать/Загрузить настройки этой группы» — сохранить или перенести настройки группы.\n\n"
    "В группе работают команды модерации: /ban /kick /mute /warn /warns /stats, "
    "а также /group (правила), /link (ссылка), /reload (перечитать права) и "
    "/diag (диагностика — почему бот молчит).\n\n"
    "🕹 Кто какие команды может — панель → ▶️ Ещё → «Права на команды» "
    "(а кто открывает настройки группы — меняет только создатель группы).\n"
    "🧹 Медиа-фильтр, 🌙 ночной режим и 🔁 авто-сообщения — тоже в ▶️ Ещё.\n"
    "👥 Роли — выдать помощнику частичные права без админки: ▶️ Ещё → Роли, "
    "назначать в группе /role Имя (ответом), снять /unrole.\n"
    "🛡 Staff-группа — отдельный чат для уведомлений: добавь туда бота и напиши /setstaff.\n\n"
    "Если тебя снимут с админов группы — она пропадёт из доступа.\n"
    "Шаблон, рассылка, допуск чатов и менеджеры — только у владельца бота."
)


async def safe_edit(query, text, kb):
    try:
        await query.edit_message_text(text, reply_markup=kb)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("safe_edit: %s", e)


def welcome_menu_text(cfg) -> str:
    jid = {"off": "не показывать", "all": "видно всем", "admins": "только администрации"}.get(
        cfg.get("show_join_id", "off"), "не показывать")
    return (
        "👋 Приветствие новых участников.\n\n"
        f"Сейчас: {'включено' if cfg['welcome']['enabled'] else 'выключено'}\n"
        f"ID новичка при входе: {jid}\n\n"
        "Текст:\n" + (cfg["welcome"]["text"] or "—") + "\n\n"
        "Можно использовать {name} (имя) и {chat} (название группы)."
    )


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not query:
        return

    data = query.data or ""

    # Капча — кнопку жмёт новичок (не менеджер), поэтому обрабатываем до проверки прав
    if data.startswith("cap:"):
        return await handle_captcha_press(update, context)

    # Капча по заявке на вступление — кнопку жмёт новичок в ЛИЧКЕ
    if data.startswith("jrok:"):
        return await handle_join_request_press(update, context)

    # Привязка staff-группы — кнопка в служебном чате
    if data.startswith("ss:"):
        return await handle_setstaff_press(update, context)

    # Кнопки действий под карточкой /info (модераторские) — проверка прав внутри
    if data.startswith("act:") or data.startswith("arole:"):
        return await handle_action_press(update, context)

    # Доступ к панели: владелец/менеджер — полный; админ группы — только свои группы
    manager = is_manager(user.id)
    if manager:
        allowed = set(CONFIG.get("groups", {}).keys())  # менеджер настраивает любую группу
    else:
        my = await user_admin_groups(context, user.id)
        if not my:
            await query.answer("Недоступно", show_alert=True)
            return
        allowed = {cid for cid, _ in my}
        # глобальные разделы — недоступны не-менеджерам
        if (data in ("m:promo", "m:access", "m:approve", "m:sched", "bk:export", "bk:import")
                or data.startswith(("pr:", "post:", "pto:", "dm:", "dmcast:", "dmto:", "sp:", "spo:", "spt:",
                                    "spp:", "spd:", "spg:", "spgo", "sptz:", "appr:", "apt:"))):
            await query.answer("Это только для владельца/менеджеров бота", show_alert=True)
            return
    # Цель панели — всегда реальная группа из доступных
    if allowed and context.user_data.get("cfg_target") not in allowed:
        context.user_data["cfg_target"] = sorted(allowed)[0]

    await query.answer()

    # Конфиг выбранной группы — для ПОКАЗА (read-only). Копия для правки берётся при изменении.
    cfg = panel_cfg_view(context)
    label = panel_target_label(context)

    # Выбор группы
    if data.startswith("pick:"):
        val = data[5:]
        if val == "list":
            return await safe_edit(
                query, "Выбери группу для настройки (📂 — уже настроена, ▫️ — по умолчанию):",
                pick_kb(manager, allowed))
        if val not in allowed:
            return await query.answer(
                "Группа недоступна" if manager else "Это не твоя группа", show_alert=True)
        context.user_data["cfg_target"] = val
        return await safe_edit(
            query, "🛠 Панель управления AntiSpam",
            main_menu_kb(panel_target_label(context), full=manager))

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

    # Глобальные списки — только владелец
    if data == "m:global" or data.startswith(("add:gbid", "add:gbname", "add:gword", "dgbid:", "dgbname:", "dgword:")):
        if not is_owner(user.id):
            return await query.answer("Только для главного владельца", show_alert=True)
        gbl = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
        gw = CONFIG.setdefault("global_stop_words", [])
        if data == "add:gbid":
            context.user_data["await"] = "gbid"
            return await safe_edit(query, "Пришли числовой ID для ГЛОБАЛЬНОГО чёрного списка.\n(или /cancel)", None)
        if data == "add:gbname":
            context.user_data["await"] = "gbname"
            return await safe_edit(query, "Пришли имя/@юзернейм для ГЛОБАЛЬНОГО чёрного списка.\n(или /cancel)", None)
        if data == "add:gword":
            context.user_data["await"] = "gword"
            return await safe_edit(query, "Пришли ГЛОБАЛЬНОЕ стоп-слово (удаляется во всех группах).\n(или /cancel)", None)
        if data.startswith("dgbid:"):
            i = int(data.split(":")[1])
            if 0 <= i < len(gbl["ids"]):
                gbl["ids"].pop(i); save_config()
        elif data.startswith("dgbname:"):
            i = int(data.split(":")[1])
            if 0 <= i < len(gbl["names"]):
                gbl["names"].pop(i); save_config()
        elif data.startswith("dgword:"):
            i = int(data.split(":")[1])
            if 0 <= i < len(gw):
                gw.pop(i); save_config()
        return await safe_edit(query, global_menu_text(), global_kb())

    # Анти-рейд
    if data.startswith("ar:"):
        cfg = panel_cfg(context)
        a = cfg.setdefault("antiraid", {"enabled": False, "joins": 8, "window": 60, "lock_min": 10})
        parts = data.split(":")
        if parts[1] == "toggle":
            a["enabled"] = not a.get("enabled")
        elif parts[1] == "joins":
            a["joins"] = max(3, min(50, a.get("joins", 8) + (1 if parts[2] == "+" else -1)))
        elif parts[1] == "window":
            a["window"] = max(10, min(600, a.get("window", 60) + (10 if parts[2] == "+" else -10)))
        elif parts[1] == "lock":
            a["lock_min"] = max(1, min(120, a.get("lock_min", 10) + (5 if parts[2] == "+" else -5)))
        save_config()
        return await safe_edit(query, antiraid_menu_text(cfg, label), antiraid_kb(cfg))

    # Раздел «Бэкап»
    if data == "m:backup" or data.startswith("bk:"):
        owner = is_owner(user.id)
        if data == "bk:gexport":
            await send_chat_backup(context, user.id, extract_chat_settings(cfg), label)
            return await safe_edit(
                query, backup_menu_text(label, owner) + "\n\n✅ Файл с настройками отправлен в этот чат.",
                backup_kb(owner))
        if data == "bk:gimport":
            context.user_data["await"] = "import_chat"
            context.user_data["import_target"] = context.user_data.get("cfg_target", "defaults")
            return await safe_edit(
                query, f"Пришли файл с настройками — применю их к «{label}».\n"
                       "Это перезапишет настройки выбранной цели.\n\n(или /cancel)", None)
        # Полный бэкап — только главный владелец
        if data in ("bk:export", "bk:import") and not owner:
            return await query.answer("Полный бэкап — только для главного владельца", show_alert=True)
        if data == "bk:export":
            await send_backup(context, user.id)
            return await safe_edit(
                query, backup_menu_text(label, owner) + "\n\n✅ Полный бэкап отправлен в этот чат.",
                backup_kb(owner))
        if data == "bk:import":
            context.user_data["await"] = "import_config"
            return await safe_edit(
                query, "Пришли мне файл полного бэкапа (config.json) — заменю ВСЕ настройки бота на него.\n(или /cancel)", None)
        return await safe_edit(query, backup_menu_text(label, owner), backup_kb(owner))

    # Раздел «Допуск чатов» — только для главного владельца
    if data == "m:approve" or data.startswith("appr:") or data.startswith("apt:"):
        if not is_owner(user.id):
            return await query.answer("Только для главного владельца", show_alert=True)
        if data == "apt:toggle":
            CONFIG["require_approval"] = not CONFIG.get("require_approval", True)
            save_config()
        elif data.startswith("appr:"):
            _, act, cid = data.split(":", 2)
            cid = int(cid)
            appr = CONFIG.setdefault("approved_chats", [])
            if act == "ok" and cid not in appr:
                appr.append(cid)
                save_config()
                try:
                    await context.bot.send_message(
                        cid, "✅ Бот активирован владельцем. Антиспам и модерация включены.")
                except Exception:  # noqa: BLE001
                    pass
            elif act == "no" and cid in appr:
                appr.remove(cid)
                save_config()
        return await safe_edit(query, approve_menu_text(), approve_kb())

    # Раздел «Права на команды» — менять может только создатель группы или владелец/менеджер бота
    if data == "m:other":
        return await safe_edit(query, f"▶️ Дополнительно · {label}", other_kb())
    if data == "m:cmdperms" or data.startswith("cp:"):
        tgt = context.user_data.get("cfg_target", "defaults")
        if not manager:
            is_creator = tgt not in (None, "defaults") and user.id == await group_creator_id(context, int(tgt))
            if not is_creator:
                return await query.answer(
                    "Права на команды меняет только создатель группы или владелец бота", show_alert=True)
        if data.startswith("cp:"):
            wcfg = panel_cfg(context)
            key = data[3:]
            levels = CMD_LEVELS.get(key)
            if levels:
                cur = wcfg.setdefault("cmd_perms", {}).get(key, CMD_DEFAULT.get(key, "admins"))
                nxt = levels[(levels.index(cur) + 1) % len(levels)] if cur in levels else levels[0]
                wcfg["cmd_perms"][key] = nxt
                save_config()
            cfg = wcfg
        return await safe_edit(query, cmdperms_menu_text(cfg, label), cmdperms_kb(cfg))

    nav = {
        "m:main": ("🛠 Панель управления AntiSpam", main_menu_kb(label, full=manager)),
        "m:status": (status_text(cfg, label, show_global=manager), main_menu_kb(label, full=manager)),
        "m:toggles": (f"🔘 Функции · {label}\nВключение/выключение:", toggles_kb(cfg)),
        "m:triggers": (f"💬 Автоответы (слово → ответ) · {label}:", triggers_kb(cfg)),
        "m:words": (f"🚫 Стоп-слова · {label}\nСообщения с этими словами удаляются:", words_kb(cfg)),
        "m:words2": (words2_menu_text(cfg, label), words2_kb(cfg)),
        "m:lang": (lang_menu_text(cfg, label), lang_kb(cfg)),
        "m:blacklist": (blacklist_menu_text(cfg, label), blacklist_kb(cfg)),
        "m:antiraid": (antiraid_menu_text(cfg, label), antiraid_kb(cfg)),
        "m:links": (f"🔗 Спам-домены · {label}:", links_kb(cfg)),
        "m:flood": (f"⚙️ Антифлуд · {label}:", flood_kb(cfg)),
        "m:mod": (f"🛡 Модерация · {label}\nКоманды — в группе (/ban, /mute…). Здесь — предупреждения:", mod_kb(cfg)),
        "m:welcome": (welcome_menu_text(cfg), welcome_kb(cfg)),
        "m:promo": (promo_menu_text(), promo_kb()),
        "m:antinuke": (antinuke_menu_text(cfg), antinuke_kb(cfg)),
        "m:captcha": (captcha_menu_text(cfg), captcha_kb(cfg)),
        "m:rules": (rules_menu_text(cfg), rules_kb()),
        "m:media": (media_menu_text(cfg, label), media_kb(cfg)),
        "m:night": (night_menu_text(cfg, label), night_kb(cfg)),
        "m:recurring": (recurring_menu_text(cfg, label), recurring_kb(cfg)),
        "m:roles": (roles_menu_text(cfg, label), roles_kb(cfg)),
        "m:staff": (staff_menu_text(cfg, label), staff_kb(cfg)),
        "m:help": (HELP_TEXT if manager else GROUPADMIN_HELP, main_menu_kb(label, full=manager)),
    }
    if data in nav:
        return await safe_edit(query, *nav[data])

    if data == "noop":
        return

    if data.startswith("tg:"):
        cfg = panel_cfg(context)
        key = data[3:]
        cfg["enabled"][key] = not cfg["enabled"].get(key, False)
        save_config()
        return await safe_edit(query, f"🔘 Функции · {label}\nВключение/выключение:", toggles_kb(cfg))

    if data == "mode:trig":
        cfg = panel_cfg(context)
        cfg["trigger_match"] = "contains" if cfg.get("trigger_match") == "word" else "word"
        save_config()
        return await safe_edit(query, f"💬 Автоответы (слово → ответ) · {label}:", triggers_kb(cfg))

    if data.startswith("fl:"):
        cfg = panel_cfg(context)
        _, field, sign = data.split(":")
        step = {"limit": 1, "period": 5, "mute": 60}[field]
        floor = {"limit": 2, "period": 5, "mute": 30}[field]
        cfg["flood"][field] = max(floor, cfg["flood"][field] + (step if sign == "+" else -step))
        save_config()
        return await safe_edit(query, f"⚙️ Антифлуд · {label}:", flood_kb(cfg))

    if data.startswith("an:"):
        cfg = panel_cfg(context)
        what = data.split(":")[1]
        a = cfg["antinuke"]
        if what == "toggle":
            a["enabled"] = not a["enabled"]
        elif what == "action":
            a["action"] = "alert" if a["action"] == "stop" else "stop"
        elif what == "thr":
            a["ban_threshold"] = max(2, a["ban_threshold"] + (1 if data.split(":")[2] == "+" else -1))
        elif what == "win":
            a["window"] = max(10, a["window"] + (10 if data.split(":")[2] == "+" else -10))
        save_config()
        return await safe_edit(query, antinuke_menu_text(cfg), antinuke_kb(cfg))

    if data.startswith("cap_set:"):
        cfg = panel_cfg(context)
        parts = data.split(":")
        c = cfg["captcha"]
        if parts[1] == "toggle":
            c["enabled"] = not c["enabled"]
        elif parts[1] == "action":
            c["action"] = "ban" if c["action"] == "kick" else "kick"
        elif parts[1] == "to":
            c["timeout"] = max(30, min(600, c["timeout"] + (30 if parts[2] == "+" else -30)))
        elif parts[1] == "viareq":
            c["via_request"] = not c.get("via_request", True)
        save_config()
        return await safe_edit(query, captcha_menu_text(cfg), captcha_kb(cfg))

    if data == "ru:edit":
        context.user_data["await"] = "rules"
        return await safe_edit(query, f"Пришли новый текст правил для «{label}» одним сообщением.\n(или /cancel)", None)

    if data.startswith("md:"):
        cfg = panel_cfg(context)
        parts = data.split(":")
        m = cfg["moderation"]
        if parts[1] == "action":
            m["warn_action"] = "ban" if m["warn_action"] == "mute" else "mute"
        elif parts[1] == "owneronly":
            m["mod_admins_only"] = not m["mod_admins_only"]
        elif parts[1] == "limit":
            m["warn_limit"] = max(1, m["warn_limit"] + (1 if parts[2] == "+" else -1))
        elif parts[1] == "mute":
            m["warn_mute"] = max(300, m["warn_mute"] + (1800 if parts[2] == "+" else -1800))
        elif parts[1] == "expire":
            order = [0, 1, 3, 7, 14, 30]
            cur = m.get("warn_expire_days", 0)
            m["warn_expire_days"] = order[(order.index(cur) + 1) % len(order)] if cur in order else 0
        elif parts[1] == "notify":
            m["notify_delete"] = not m.get("notify_delete")
        save_config()
        return await safe_edit(query, f"🛡 Модерация · {label}\nНастройки предупреждений:", mod_kb(cfg))

    if data == "wl:toggle":
        cfg = panel_cfg(context)
        cfg["welcome"]["enabled"] = not cfg["welcome"]["enabled"]
        save_config()
        return await safe_edit(query, welcome_menu_text(cfg), welcome_kb(cfg))
    if data == "wl:edit":
        context.user_data["await"] = "welcome"
        return await safe_edit(query, f"Пришли новый текст приветствия для «{label}» одним сообщением.\n"
                                       "Можно вставить {name} и {chat}.\n\n(или /cancel)", None)
    if data == "wl:btns":
        context.user_data["await"] = "welcome_btns"
        return await safe_edit(
            query,
            "Пришли кнопки-ссылки для приветствия: по одной на строку «Текст - https://ссылка».\n"
            "Пришли «-», чтобы убрать кнопки.\n\n(или /cancel)", None)
    if data == "wl:del":
        cfg = panel_cfg(context)
        order = [0, 30, 60, 120, 300]
        cur = int(cfg["welcome"].get("delete_after", 0) or 0)
        cfg["welcome"]["delete_after"] = order[(order.index(cur) + 1) % len(order)] if cur in order else 0
        save_config()
        return await safe_edit(query, welcome_menu_text(cfg), welcome_kb(cfg))
    if data == "wl:joinid":
        cfg = panel_cfg(context)
        order = ["off", "all", "admins"]
        cur = cfg.get("show_join_id", "off")
        cfg["show_join_id"] = order[(order.index(cur) + 1) % len(order)] if cur in order else "all"
        save_config()
        return await safe_edit(query, welcome_menu_text(cfg), welcome_kb(cfg))

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
            return await safe_edit(query, "Пришли сообщение (текст или фото с подписью) — разошлю во все группы бота.\n(или /cancel)", None)
        if what == "pin":
            CONFIG["promo"]["pin"] = not CONFIG["promo"].get("pin", False)
            save_config()
            return await safe_edit(query, promo_menu_text(), promo_kb())

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
            return await safe_edit(query, f"Пришли текст или фото с подписью — опубликую в «{title}».\n(или /cancel)", None)
        return await safe_edit(query, "Группа не найдена.", post_groups_kb())

    if data == "dmcast:list":
        if not CONFIG["groups"]:
            return await safe_edit(query, "Пока нет известных групп.", promo_kb())
        return await safe_edit(
            query,
            "Кому рассылать в личку: выбери группу. Подписчики — те, кто прошёл капчу-заявку "
            "(вступал через ссылку с одобрением). Сообщение придёт им в ЛС с шапкой от имени группы.",
            dmcast_groups_kb())
    if data.startswith("dmto:"):
        items = sorted(CONFIG["groups"].items())
        i = int(data[5:])
        if 0 <= i < len(items):
            cid, title = items[i]
            n = len(CONFIG.get("dm_subscribers", {}).get(str(cid), []))
            if n == 0:
                return await safe_edit(
                    query,
                    f"У «{title}» пока нет подписчиков в ЛС. Они появляются, когда люди вступают "
                    "через ссылку-заявку и проходят капчу в личке (включи это в разделе Капча).",
                    dmcast_groups_kb())
            context.user_data["await"] = "dmcast"
            context.user_data["dmcast_chat"] = int(cid)
            return await safe_edit(
                query, f"Пришли текст или фото с подписью — разошлю {n} подписчикам «{title}» в ЛС.\n(или /cancel)", None)
        return await safe_edit(query, "Группа не найдена.", dmcast_groups_kb())

    if data == "m:sched":
        if not CONFIG["groups"]:
            return await safe_edit(query, "Пока нет известных групп для постинга.", promo_kb())
        return await safe_edit(query, sched_menu_text(), sched_kb())
    if data == "sp:new":
        if not CONFIG["groups"]:
            return await safe_edit(query, "Пока нет групп для постинга.", sched_kb())
        context.user_data["sp_draft"] = {"chat_ids": []}
        context.user_data["await"] = "sp_name"
        return await safe_edit(query, "Название поста? (например: Утренний анонс)\n(или /cancel)", None)
    if data.startswith("spg:"):
        items = sorted(CONFIG["groups"].items())
        i = int(data[4:])
        d = context.user_data.setdefault("sp_draft", {})
        sel = d.setdefault("chat_ids", [])
        if 0 <= i < len(items):
            cid = int(items[i][0])
            if cid in sel:
                sel.remove(cid)
            else:
                sel.append(cid)
        return await safe_edit(query, "Выбери группы для поста (можно несколько), затем «Готово»:",
                               sched_groups_kb(sel))
    if data == "spgo":
        d = context.user_data.setdefault("sp_draft", {})
        if not d.get("chat_ids"):
            return await safe_edit(query, "Отметь хотя бы одну группу:", sched_groups_kb(d.get("chat_ids")))
        context.user_data["await"] = "sp_content"
        return await safe_edit(
            query,
            "Теперь пришли САМ ПОСТ: текст, фото / видео / гиф / стикер / документ (с подписью) — "
            "что отправишь, то и будет публиковаться. Эмодзи и форматирование сохранятся.\n(или /cancel)", None)
    if data.startswith("spo:"):
        p = _find_post(data[4:])
        if not p:
            return await safe_edit(query, sched_menu_text(), sched_kb())
        return await safe_edit(query, sched_post_text(p), sched_post_kb(p))
    if data.startswith("spt:"):
        p = _find_post(data[4:])
        if p:
            p["enabled"] = not p.get("enabled", True)
            save_config()
            if p["enabled"]:
                _schedule_post(context.job_queue, p)
            else:
                _unschedule_post(context.job_queue, p["id"])
            return await safe_edit(query, sched_post_text(p), sched_post_kb(p))
        return await safe_edit(query, sched_menu_text(), sched_kb())
    if data.startswith("spp:"):
        p = _find_post(data[4:])
        if p:
            p["pin"] = not p.get("pin", False)
            save_config()
            return await safe_edit(query, sched_post_text(p), sched_post_kb(p))
        return await safe_edit(query, sched_menu_text(), sched_kb())
    if data.startswith("spd:"):
        pid = data[4:]
        if _find_post(pid):
            CONFIG["scheduled_posts"] = [x for x in CONFIG["scheduled_posts"] if x.get("id") != pid]
            _unschedule_post(context.job_queue, pid)
            save_config()
        return await safe_edit(query, sched_menu_text(), sched_kb())
    if data.startswith("sptz:"):
        sign = data.split(":")[1]
        tz = int(CONFIG.get("post_tz", 5)) + (1 if sign == "+" else -1)
        CONFIG["post_tz"] = max(-12, min(14, tz))
        save_config()
        _reschedule_all_posts(context.job_queue)
        return await safe_edit(query, sched_menu_text(), sched_kb())

    if data.startswith("dt:"):
        cfg = panel_cfg(context)
        keys = sorted(cfg["triggers"].keys())
        i = int(data[3:])
        if 0 <= i < len(keys):
            cfg["triggers"].pop(keys[i], None)
            save_config()
        return await safe_edit(query, f"💬 Автоответы (слово → ответ) · {label}:", triggers_kb(cfg))
    if data.startswith("dw:"):
        cfg = panel_cfg(context)
        words = sorted(cfg["stop_words"])
        i = int(data[3:])
        if 0 <= i < len(words):
            cfg["stop_words"].remove(words[i])
            save_config()
        return await safe_edit(query, f"🚫 Стоп-слова · {label}:", words_kb(cfg))
    if data.startswith("dl:"):
        cfg = panel_cfg(context)
        links = sorted(cfg["spam_links"])
        i = int(data[3:])
        if 0 <= i < len(links):
            cfg["spam_links"].remove(links[i])
            save_config()
        return await safe_edit(query, f"🔗 Спам-домены · {label}:", links_kb(cfg))

    if data.startswith("mb:"):
        wcfg = panel_cfg(context)
        key = data[3:]
        mbd = wcfg.setdefault("media_block", {})
        mbd[key] = not mbd.get(key, False)
        save_config()
        return await safe_edit(query, media_menu_text(wcfg, label), media_kb(wcfg))

    if data == "mact":
        wcfg = panel_cfg(context)
        cyc = ["delete", "mute", "ban"]
        cur = wcfg.get("media_action", "delete")
        wcfg["media_action"] = cyc[(cyc.index(cur) + 1) % len(cyc)] if cur in cyc else "delete"
        save_config()
        return await safe_edit(query, media_menu_text(wcfg, label), media_kb(wcfg))

    if data.startswith("dw2:"):
        wcfg = panel_cfg(context)
        words = sorted(wcfg.get("stop_words2", []))
        i = int(data[4:])
        if 0 <= i < len(words):
            wcfg["stop_words2"].remove(words[i])
            save_config()
        return await safe_edit(query, words2_menu_text(wcfg, label), words2_kb(wcfg))
    if data == "w2act":
        wcfg = panel_cfg(context)
        cyc = ["delete", "mute", "ban"]
        cur = wcfg.get("stop_words2_action", "ban")
        wcfg["stop_words2_action"] = cyc[(cyc.index(cur) + 1) % len(cyc)] if cur in cyc else "ban"
        save_config()
        return await safe_edit(query, words2_menu_text(wcfg, label), words2_kb(wcfg))
    if data == "w2prof":
        wcfg = panel_cfg(context)
        wcfg["stop_words2_profile"] = not wcfg.get("stop_words2_profile", True)
        save_config()
        return await safe_edit(query, words2_menu_text(wcfg, label), words2_kb(wcfg))
    if data.startswith("dblid:"):
        wcfg = panel_cfg(context)
        ids = wcfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("ids", [])
        i = int(data.split(":")[1])
        if 0 <= i < len(ids):
            ids.pop(i)
            save_config()
        return await safe_edit(query, blacklist_menu_text(wcfg, label), blacklist_kb(wcfg))
    if data.startswith("dblname:"):
        wcfg = panel_cfg(context)
        names = wcfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("names", [])
        i = int(data.split(":")[1])
        if 0 <= i < len(names):
            names.pop(i)
            save_config()
        return await safe_edit(query, blacklist_menu_text(wcfg, label), blacklist_kb(wcfg))
    if data.startswith("lang:"):
        wcfg = panel_cfg(context)
        code = data.split(":")[1]
        if code in LANGS:
            wcfg["lang"] = code
            save_config()
        return await safe_edit(query, lang_menu_text(wcfg, label), lang_kb(wcfg))

    if data.startswith("nm:"):
        wcfg = panel_cfg(context)
        n = wcfg.setdefault("night", {})
        parts = data.split(":")
        if parts[1] == "toggle":
            n["enabled"] = not n.get("enabled", False)
        elif parts[1] == "start":
            n["start"] = (n.get("start", 23) + (1 if parts[2] == "+" else -1)) % 24
        elif parts[1] == "end":
            n["end"] = (n.get("end", 7) + (1 if parts[2] == "+" else -1)) % 24
        elif parts[1] == "tz":
            n["tz"] = max(-12, min(14, n.get("tz", 0) + (1 if parts[2] == "+" else -1)))
        save_config()
        return await safe_edit(query, night_menu_text(wcfg, label), night_kb(wcfg))

    if data.startswith("rec:del:"):
        wcfg = panel_cfg(context)
        i = int(data.split(":")[2])
        items = wcfg.setdefault("recurring", [])
        if 0 <= i < len(items):
            items.pop(i)
            save_config()
        return await safe_edit(query, recurring_menu_text(wcfg, label), recurring_kb(wcfg))

    if data == "add:recurring":
        context.user_data["await"] = "recurring"
        return await safe_edit(
            query,
            f"Пришли авто-сообщение для «{label}» в формате: минуты = текст\n"
            "Например: 120 = Не забывайте про правила!\n\n(или /cancel)", None)

    # Роли
    if data == "add:role":
        context.user_data["await"] = "role_new"
        return await safe_edit(
            query, f"Пришли название новой роли для «{label}» (например: Чистильщик).\n(или /cancel)", None)
    if data.startswith("rl:"):
        idx = int(data[3:])
        return await safe_edit(query, role_detail_text(cfg, idx, label), role_detail_kb(cfg, idx))
    if data.startswith("rp:"):
        wcfg = panel_cfg(context)
        _, idx_s, key = data.split(":")
        idx = int(idx_s)
        names = sorted((wcfg.get("roles", {}) or {}).keys())
        if idx < len(names) and key in ROLE_PERM_KEYS:
            perms = wcfg["roles"][names[idx]].setdefault("perms", [])
            if key in perms:
                perms.remove(key)
            else:
                perms.append(key)
            save_config()
        return await safe_edit(query, role_detail_text(wcfg, idx, label), role_detail_kb(wcfg, idx))
    if data.startswith("rm:"):
        wcfg = panel_cfg(context)
        _, idx_s, uid_s = data.split(":")
        idx = int(idx_s)
        names = sorted((wcfg.get("roles", {}) or {}).keys())
        if idx < len(names):
            mem = wcfg["roles"][names[idx]].get("members", [])
            try:
                mem.remove(int(uid_s))
                save_config()
            except ValueError:
                pass
        return await safe_edit(query, role_detail_text(wcfg, idx, label), role_detail_kb(wcfg, idx))
    if data.startswith("rdel:"):
        wcfg = panel_cfg(context)
        idx = int(data.split(":")[1])
        names = sorted((wcfg.get("roles", {}) or {}).keys())
        if idx < len(names):
            wcfg.get("roles", {}).pop(names[idx], None)
            save_config()
        return await safe_edit(query, roles_menu_text(wcfg, label), roles_kb(wcfg))

    # Staff-группа
    if data == "st:unset":
        wcfg = panel_cfg(context)
        wcfg["staff_group"] = 0
        save_config()
        return await safe_edit(query, staff_menu_text(wcfg, label), staff_kb(wcfg))
    if data == "st:log":
        wcfg = panel_cfg(context)
        wcfg.setdefault("moderation", {})["log_actions"] = not wcfg.get("moderation", {}).get("log_actions")
        save_config()
        return await safe_edit(query, staff_menu_text(wcfg, label), staff_kb(wcfg))

    if data == "add:trigger":
        context.user_data["await"] = "trigger"
        return await safe_edit(query, f"Пришли строку: слово = ответ (для «{label}»).\nМожно несколько слов через запятую на один ответ, например: банан, яблоко, груша = это фрукт\n\n(или /cancel)", None)
    if data == "add:word":
        context.user_data["await"] = "word"
        return await safe_edit(query, f"Пришли стоп-слово для «{label}» одним сообщением.\n(или /cancel)", None)
    if data == "add:word2":
        context.user_data["await"] = "word2"
        return await safe_edit(query, f"Пришли слово для ВТОРОГО списка «{label}» одним сообщением.\n(или /cancel)", None)
    if data == "add:blid":
        context.user_data["await"] = "blid"
        return await safe_edit(query, f"Пришли числовой ID пользователя для чёрного списка «{label}».\n(или /cancel)", None)
    if data == "add:blname":
        context.user_data["await"] = "blname"
        return await safe_edit(query, f"Пришли имя/часть имени или @юзернейм для чёрного списка «{label}».\n(или /cancel)", None)
    if data == "add:link":
        context.user_data["await"] = "link"
        return await safe_edit(query, f"Пришли домен для «{label}», напр. example.com\n(или /cancel)", None)


# ───────────────────────────────────────────────────────────────────────────
#  КОМАНДЫ В ЛС / ОБЩИЕ
# ───────────────────────────────────────────────────────────────────────────


async def add_group_button(context):
    """Кнопка «Добавить меня в группу» — открывает в Telegram выбор группы.
    admin=… просит сразу выдать боту нужные права админа."""
    uname = context.bot.username or (await context.bot.get_me()).username
    rights = "delete_messages+restrict_members+invite_users+pin_messages"
    return InlineKeyboardButton(
        "➕ Добавить меня в группу",
        url=f"https://t.me/{uname}?startgroup=true&admin={rights}")


async def _ensure_panel_target(update, context):
    """Готовит цель панели (всегда реальная группа). Возвращает (level, label, full).
    level: manager | groupadmin | nogroups | none."""
    uid = update.effective_user.id
    manager = is_manager(uid)
    if manager:
        allowed = list(CONFIG.get("groups", {}).keys())
        if not allowed:
            return "nogroups", "", True
    else:
        allowed = [cid for cid, _ in await user_admin_groups(context, uid)]
        if not allowed:
            return "none", "", False
    if context.user_data.get("cfg_target") not in allowed:
        context.user_data["cfg_target"] = sorted(allowed)[0]
    return ("manager" if manager else "groupadmin"), panel_target_label(context), manager


async def cmd_start(update, context):
    add_btn = await add_group_button(context)
    level, label, full = await _ensure_panel_target(update, context)
    if level == "manager":
        kb = InlineKeyboardMarkup([
            [add_btn],
            [InlineKeyboardButton("🛠 Открыть панель", callback_data="m:main")],
            [InlineKeyboardButton("ℹ️ Помощь по настройкам", callback_data="m:help")],
        ])
        await update.message.reply_text(
            "👋 Привет! Я AntiSpam Moriarty.\n\n"
            "Добавь меня в группу администратором — буду чистить спам, защищать от сноса "
            "и помогать с модерацией. У каждой группы могут быть свои настройки.\n\n"
            "🛠 «Открыть панель» — настройки   ·   /help — помощь",
            reply_markup=kb)
    elif level == "groupadmin":
        kb = InlineKeyboardMarkup([
            [add_btn],
            [InlineKeyboardButton("🛠 Настроить мои группы", callback_data="m:main")],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data="m:help")],
        ])
        await update.message.reply_text(
            "👋 Привет! Ты администратор группы с этим ботом.\n\n"
            "Можешь настроить свои группы (где ты админ): антиспам, приветствие, "
            "капчу, правила и т.д. Нажми «Настроить мои группы».",
            reply_markup=kb)
    elif level == "nogroups":
        await update.message.reply_text(
            "👋 Привет! Я AntiSpam Moriarty.\n\n"
            "Я ещё не добавлен ни в одну группу. Нажми кнопку ниже, добавь меня "
            "администратором — и тогда в /panel появятся настройки этой группы.",
            reply_markup=InlineKeyboardMarkup([[add_btn]]))
    else:
        await update.message.reply_text(
            "👋 Я антиспам-бот. Добавь меня в группу администратором — и я буду следить за порядком.\n\n"
            "Настройками управляет владелец бота и админы своих групп. Что я умею — /help.",
            reply_markup=InlineKeyboardMarkup([[add_btn]]))


async def cmd_panel(update, context):
    level, label, full = await _ensure_panel_target(update, context)
    if level == "none":
        return
    if level == "nogroups":
        add_btn = await add_group_button(context)
        await update.message.reply_text(
            "Я пока не добавлен ни в одну группу. Добавь меня — и появятся настройки.",
            reply_markup=InlineKeyboardMarkup([[add_btn]]))
        return
    await update.message.reply_text(
        "🛠 Панель управления AntiSpam", reply_markup=main_menu_kb(label, full=full))


async def cmd_status(update, context):
    level, label, full = await _ensure_panel_target(update, context)
    if level in ("none", "nogroups"):
        return
    await update.message.reply_text(
        status_text(panel_cfg_view(context), label, show_global=(level == "manager")),
        reply_markup=main_menu_kb(label, full=full))


async def cmd_help(update, context):
    add_btn = await add_group_button(context)
    uid = update.effective_user.id
    if is_manager(uid):
        await update.message.reply_text(HELP_TEXT, reply_markup=InlineKeyboardMarkup([[add_btn]]))
        return
    if await user_admin_groups(context, uid):
        await update.message.reply_text(GROUPADMIN_HELP, reply_markup=InlineKeyboardMarkup([[add_btn]]))
        return
    await update.message.reply_text(
        "Я антиспам-бот. Добавь меня в группу администратором — буду чистить спам, "
        "защищать от сноса и помогать с модерацией. Настройками управляет владелец бота "
        "и админы своих групп.",
        reply_markup=InlineKeyboardMarkup([[add_btn]]))


async def cmd_purge(update, context):
    """Удалить сообщения от отвеченного до текущего (чистка спама). Только модераторы."""
    chat = update.effective_chat
    msg = update.effective_message
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban"):
        return await _deny(update)
    if not msg.reply_to_message:
        await msg.reply_text("Ответь командой /purge на сообщение, начиная с которого удалить.")
        return
    start = msg.reply_to_message.message_id
    end = msg.message_id
    ids = list(range(start, end + 1))
    if len(ids) > 200:
        await msg.reply_text("Слишком большой диапазон (>200). Ответь ближе к началу спама.")
        return
    deleted = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        try:
            await context.bot.delete_messages(chat.id, chunk)
            deleted += len(chunk)
        except Exception:  # noqa: BLE001
            for mid in chunk:  # по одному, если пачкой не вышло
                try:
                    await context.bot.delete_message(chat.id, mid)
                    deleted += 1
                except Exception:  # noqa: BLE001
                    pass
    bump(chat.id, "deleted")
    await log_action(context, chat.id, f"🧹 очистка: удалено ~{deleted} сообщений (by {_actor_name(update)})")
    try:
        note = await context.bot.send_message(chat.id, f"🧹 Удалено ~{deleted} сообщений.")
        if context.job_queue:
            context.job_queue.run_once(_delete_later, 5, data={"chat_id": chat.id, "mid": note.message_id})
    except Exception:  # noqa: BLE001
        pass


async def _delete_later(context):
    d = context.job.data
    try:
        await context.bot.delete_message(d["chat_id"], d["mid"])
    except Exception:  # noqa: BLE001
        pass


_report_cd: dict = {}  # (chat_id, user_id) -> ts последней жалобы (антиспам жалоб)


async def cmd_report(update, context):
    """Жалоба от пользователя: ответом на плохое сообщение /report (или @admin). Уходит в staff/владельцам."""
    chat = update.effective_chat
    msg = update.effective_message
    reporter = update.effective_user
    if not msg.reply_to_message:
        await msg.reply_text("Чтобы пожаловаться, ответь этой командой на нужное сообщение.")
        return
    key = (chat.id, reporter.id)
    now = time.time()
    if now - _report_cd.get(key, 0) < 30:
        return  # не чаще раза в 30 сек
    _report_cd[key] = now
    target = msg.reply_to_message.from_user
    title = CONFIG.get("groups", {}).get(str(chat.id), str(chat.id))
    head = (f"🚨 Жалоба в «{title}»\n"
            f"От: {mention(reporter)}\n"
            f"На: {mention(target) if target else '—'}")
    sent_to_staff = False
    sg = chat_cfg(chat.id).get("staff_group", 0)
    if sg:
        try:
            await context.bot.send_message(sg, head)
            await context.bot.forward_message(sg, chat.id, msg.reply_to_message.message_id)
            sent_to_staff = True
        except Exception as e:  # noqa: BLE001
            log.debug("report→staff: %s", e)
    if not sent_to_staff:
        await alert_staff(context, head + "\n(переслать сообщение не вышло — посмотри в чате)")
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass
    try:
        ack = await context.bot.send_message(chat.id, "✅ Жалоба отправлена администрации.")
        if context.job_queue:
            context.job_queue.run_once(_delete_later, 5, data={"chat_id": chat.id, "mid": ack.message_id})
    except Exception:  # noqa: BLE001
        pass


async def cmd_me(update, context):
    """Пользователь смотрит свой статус: предупреждения и т.п. Доступно всем."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or chat.type == "private":
        await update.effective_message.reply_text("Эта команда работает в группе.")
        return
    n = get_warn(chat.id, user.id)
    limit = chat_cfg(chat.id)["moderation"]["warn_limit"]
    muted = "да" if is_soft_muted(chat.id, user.id) else "нет"
    lines = [
        f"👤 {mention(user)}",
        f"ID: <code>{user.id}</code>",
        f"Предупреждения: {n}/{limit}",
        f"В муте: {muted}",
    ]
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


_appeal_cd: dict = {}


async def cmd_appeal(update, context):
    """Апелляция: пользователь пишет боту в ЛС /appeal текст — уходит владельцам."""
    user = update.effective_user
    text = _args_text(update)
    if not text:
        await update.message.reply_text(
            "Чтобы подать апелляцию, напиши: /appeal и текст обращения (например, почему тебя стоит разбанить).")
        return
    now = time.time()
    if now - _appeal_cd.get(user.id, 0) < 120:
        await update.message.reply_text("Апелляцию можно отправлять раз в пару минут. Попробуй позже.")
        return
    _appeal_cd[user.id] = now
    head = (f"📨 Апелляция от {mention(user)} (ID <code>{user.id}</code>"
            + (f", @{user.username}" if user.username else "") + f"):\n{text}")
    await alert_owners(context, head)
    await update.message.reply_text("✅ Обращение отправлено администрации. Жди ответа.")


async def cmd_gblock(update, context):
    """Глобальный бан: ответом на сообщение /gblock — в глобальный ЧС (все группы). Только владелец."""
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    chat = update.effective_chat
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Кого в глобальный ЧС? Ответь на сообщение или /gblock id.")
        return
    ids = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []}).setdefault("ids", [])
    if tid not in ids:
        ids.append(tid)
        save_config()
    try:
        await context.bot.ban_chat_member(chat.id, tid)
        bump(chat.id, "banned")
    except Exception as e:  # noqa: BLE001
        log.debug("gblock ban: %s", e)
    await update.effective_message.reply_text(f"🌍🚷 {tname} в глобальном чёрном списке (ID {tid}) — банится во всех группах.")


async def cmd_gunblock(update, context):
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text("Кого убрать из глобального ЧС? Ответь или /gunblock id.")
        return
    ids = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []}).setdefault("ids", [])
    if tid in ids:
        ids.remove(tid)
        save_config()
    await update.effective_message.reply_text(f"✅ {tname} убран из глобального чёрного списка.")


async def weekly_digest_job(context):
    """Раз в неделю шлём в staff-группы краткую сводку по группе."""
    for cid in list(CONFIG.get("groups", {}).keys()):
        try:
            cfg = chat_cfg(int(cid))
            if not cfg.get("staff_group"):
                continue
            st = stats_store.get(int(cid), {})
            title = CONFIG["groups"].get(cid, cid)
            text = (f"📊 Недельная сводка «{title}»\n"
                    f"Входов: {st.get('joined', 0)} · банов: {st.get('banned', 0)} · "
                    f"мутов: {st.get('muted', 0)} · удалено: {st.get('deleted', 0)} · "
                    f"предупреждений: {st.get('warns', 0)} · капча пройдена: {st.get('captcha_pass', 0)}")
            await context.bot.send_message(cfg["staff_group"], text)
        except Exception as e:  # noqa: BLE001
            log.debug("digest %s: %s", cid, e)


async def cmd_cancel(update, context):
    context.user_data.pop("sp_draft", None)
    if context.user_data.pop("await", None):
        full = is_manager(update.effective_user.id)
        await update.message.reply_text(
            "Отменено.", reply_markup=main_menu_kb(panel_target_label(context), full=full))


async def cmd_skip(update, context):
    """Пропустить шаг кнопок в мастере поста."""
    if context.user_data.get("await") == "sp_buttons":
        context.user_data["await"] = "sp_time"
        await update.message.reply_text(
            "Ок, без кнопок. Во сколько публиковать каждый день? Формат ЧЧ:ММ, "
            "например 13:00 (час дня) или 02:00 (два ночи).\n(или /cancel)")


async def cmd_id(update, context):
    u = update.effective_user
    c = update.effective_chat
    await update.message.reply_text(f"Твой ID: {u.id}\nID этого чата: {c.id}")


STATUS_RU = {"creator": "Владелец", "administrator": "Администратор", "member": "Участник",
             "restricted": "Ограничен", "left": "Не в группе", "kicked": "Забанен"}


async def cmd_info(update, context):
    """Карточка пользователя + кнопки модерации (как у GroupHelp). Для админов/модераторов."""
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type == "private":
        return
    actor = update.effective_user
    if not await can_moderate(context, chat.id, actor.id, "warn"):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        tid, tname = actor.id, (actor.first_name or str(actor.id))
    fname, uname, status = tname, "—", "—"
    try:
        cm = await context.bot.get_chat_member(chat.id, tid)
        status = STATUS_RU.get(cm.status, cm.status)
        u = cm.user
        fname = " ".join(filter(None, [u.first_name, u.last_name])) or fname
        uname = f"@{u.username}" if u.username else "—"
    except Exception as e:  # noqa: BLE001
        log.debug("info getmember %s: %s", tid, e)
    warns = get_warn(chat.id, tid)
    limit = chat_cfg(chat.id)["moderation"]["warn_limit"]
    roles = user_roles(chat.id, tid)
    src = msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else actor
    lang = getattr(src, "language_code", None) if src and src.id == tid else None
    lines = [
        "👤 Инфо",
        f"🆔 ID: <code>{tid}</code>",
        f"Имя: {html.escape(fname)}",
        f"Юзернейм: {html.escape(uname)}",
        f"Состояние: {status}",
        f"Предупреждения: {warns}/{limit}",
    ]
    jt = join_dates.get((chat.id, tid))
    if jt:
        lines.append("Вступил(а): " + datetime.fromtimestamp(jt).strftime("%d.%m.%y в %H:%M"))
    if lang:
        lines.append(f"Язык: {html.escape(lang)}")
    if roles:
        lines.append("Роли: " + html.escape(", ".join(roles)))
    if is_soft_muted(chat.id, tid):
        lines.append("🔇 Сейчас в муте")
    await msg.reply_text("\n".join(lines), reply_markup=info_action_kb(tid), parse_mode="HTML")


async def cmd_userid(update, context):
    """Узнать Telegram ID. Ответом на сообщение — ID его автора (для админов)."""
    msg = update.effective_message
    chat = update.effective_chat
    # Ответ на сообщение — показываем автора (для админов/менеджеров)
    if msg.reply_to_message and msg.reply_to_message.from_user:
        if not await can_moderate(context, chat.id, update.effective_user.id):
            return await msg.reply_text(
                "Это для администрации: ответь на сообщение пользователя командой /userid.")
        u = msg.reply_to_message.from_user
        uname = f"@{u.username}" if u.username else "—"
        full = " ".join(filter(None, [u.first_name, u.last_name])) or "пользователь"
        return await msg.reply_text(
            f"👤 {html.escape(full)}\n"
            f"ID: <code>{u.id}</code>\n"
            f"Юзернейм: {html.escape(uname)}\n\n"
            f"<i>Юзернейм можно сменить, а ID — нет.</i>",
            parse_mode="HTML")
    # Аргумент @user или id (для админов)
    if context.args:
        if not await can_moderate(context, chat.id, update.effective_user.id):
            return await msg.reply_text("Это для администрации.")
        tid, tname = await resolve_target(update, context)
        if not tid:
            return await msg.reply_text("Не нашёл такого пользователя. Лучше ответь на его сообщение.")
        return await msg.reply_text(
            f"👤 {html.escape(str(tname))}\nID: <code>{tid}</code>", parse_mode="HTML")
    # Без цели — собственный ID (доступно всем)
    u = update.effective_user
    await msg.reply_text(
        f"Твой ID: <code>{u.id}</code>\nID этого чата: <code>{chat.id}</code>", parse_mode="HTML")


async def cmd_setwelcome(update, context):
    if not is_manager(update.effective_user.id):
        return
    text = _args_text(update)
    if not text:
        await update.message.reply_text("Формат: /setwelcome текст (можно {name} и {chat})")
        return
    cfg = panel_cfg(context)
    cfg["welcome"]["text"] = text
    cfg["welcome"]["enabled"] = True
    save_config()
    await update.message.reply_text(
        f"✅ Приветствие сохранено и включено ({panel_target_label(context)}).", reply_markup=welcome_kb(cfg))


# ── доступ (только главный владелец) ────────────────────────────────────────


async def cmd_grant(update, context):
    if not is_owner(update.effective_user.id):
        return
    tid, tname = await resolve_target(update, context)
    if not tid:
        passed = context.args[0] if context.args else None
        if passed and passed.startswith("@"):
            await update.effective_message.reply_text(
                f"❗ Не смог определить ID для {passed}.\n"
                "Telegram не даёт ботам узнавать ID по @имени, если человек ещё ни разу не писал боту.\n\n"
                "Сделай любым способом:\n"
                f"1) Пусть человек напишет мне /start в личке — потом снова /grant {passed}\n"
                "2) Или выдай по числовому ID: /grant 123456789\n"
                "   (узнать ID: ответь на его сообщение в группе командой /userid, "
                "или пусть откроет @userinfobot)\n"
                "3) Или просто ответь на его сообщение командой /grant")
        else:
            await update.effective_message.reply_text(
                "Кому выдать права? Способы:\n"
                "• ответь на сообщение человека командой /grant\n"
                "• /grant <числовой_id>  (узнать ID: /userid ответом на его сообщение)\n"
                "• /grant @username — сработает, только если человек уже писал боту")
        return
    if tid not in CONFIG["managers"]:
        CONFIG["managers"].append(tid)
        save_config()
        await update.effective_message.reply_text(
            f"✅ {tname} теперь может управлять ботом (панель + модерация во всех группах).\nID: {tid}")
    else:
        await update.effective_message.reply_text(f"{tname} уже в списке управляющих (ID {tid}).")


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


async def cmd_settings_hint(update, context):
    """/config (или /settings) в группе — кнопка, открывающая настройки в личке."""
    chat = update.effective_chat
    if not chat or chat.type == "private":
        return
    user = update.effective_user
    if not await can_open_settings(context, chat.id, user.id):
        return await _deny(update)
    try:
        uname = context.bot.username or (await context.bot.get_me()).username
    except Exception:  # noqa: BLE001
        uname = None
    if uname:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(
            "⚙️ Открыть настройки", url=f"https://t.me/{uname}?start=panel")]])
        await update.effective_message.reply_text(
            "Настройки группы открываются в личке со мной 👇", reply_markup=kb)
    else:
        await update.effective_message.reply_text("Открой меня в личке и напиши /panel.")


# ── контент-команды ─────────────────────────────────────────────────────────


async def cmd_add(update, context):
    if not is_manager(update.effective_user.id):
        return
    body = _args_text(update)
    if "=" not in body:
        await update.message.reply_text("Формат: /add слово = ответ (можно несколько слов через запятую)")
        return
    keys_part, resp = body.split("=", 1)
    resp = resp.strip()
    words = [w.strip().lower() for w in keys_part.split(",") if w.strip()]
    if not words or not resp:
        await update.message.reply_text("Пусто. Формат: /add слово1, слово2 = ответ")
        return
    cfg = panel_cfg(context)
    for w in words:
        cfg["triggers"][w] = resp
    save_config()
    if len(words) == 1:
        msg = f"✅ Добавлено: «{words[0]}» → «{resp}» ({panel_target_label(context)})"
    else:
        msg = (f"✅ Добавлено {len(words)} слов → один ответ «{resp}» ({panel_target_label(context)}):\n"
               + ", ".join(words))
    await update.message.reply_text(msg, reply_markup=triggers_kb(cfg))


async def cmd_del(update, context):
    if not is_manager(update.effective_user.id):
        return
    key = _args_text(update).lower()
    cfg = panel_cfg(context)
    if cfg["triggers"].pop(key, None) is not None:
        save_config()
        await update.message.reply_text(f"🗑 Удалено: «{key}»", reply_markup=triggers_kb(cfg))
    else:
        await update.message.reply_text("Такого ключа нет.")


async def cmd_list(update, context):
    if not is_manager(update.effective_user.id):
        return
    cfg = panel_cfg(context)
    if not cfg["triggers"]:
        await update.message.reply_text("Автоответов пока нет.", reply_markup=triggers_kb(cfg))
        return
    lines = [f"• {k} → {v}" for k, v in sorted(cfg["triggers"].items())]
    await update.message.reply_text(
        f"💬 Автоответы ({panel_target_label(context)}):\n" + "\n".join(lines), reply_markup=triggers_kb(cfg))


async def cmd_addword(update, context):
    if not is_manager(update.effective_user.id):
        return
    w = _args_text(update).lower()
    if not w:
        await update.message.reply_text("Формат: /addword слово")
        return
    cfg = panel_cfg(context)
    if w not in cfg["stop_words"]:
        cfg["stop_words"].append(w)
        save_config()
    await update.message.reply_text(
        f"✅ Стоп-слово: {w} ({panel_target_label(context)})", reply_markup=words_kb(cfg))


async def cmd_delword(update, context):
    if not is_manager(update.effective_user.id):
        return
    w = _args_text(update).lower()
    cfg = panel_cfg(context)
    if w in cfg["stop_words"]:
        cfg["stop_words"].remove(w)
        save_config()
        await update.message.reply_text(f"🗑 Удалено: {w}", reply_markup=words_kb(cfg))
    else:
        await update.message.reply_text("Такого слова нет.")


async def cmd_words(update, context):
    if not is_manager(update.effective_user.id):
        return
    cfg = panel_cfg(context)
    await update.message.reply_text(
        f"🚫 Стоп-слова ({panel_target_label(context)}):\n" + (", ".join(sorted(cfg["stop_words"])) or "—"),
        reply_markup=words_kb(cfg))


async def cmd_addlink(update, context):
    if not is_manager(update.effective_user.id):
        return
    d = _args_text(update).lower()
    if not d:
        await update.message.reply_text("Формат: /addlink домен")
        return
    cfg = panel_cfg(context)
    if d not in cfg["spam_links"]:
        cfg["spam_links"].append(d)
        save_config()
    await update.message.reply_text(
        f"✅ Домен: {d} ({panel_target_label(context)})", reply_markup=links_kb(cfg))


async def cmd_dellink(update, context):
    if not is_manager(update.effective_user.id):
        return
    d = _args_text(update).lower()
    cfg = panel_cfg(context)
    if d in cfg["spam_links"]:
        cfg["spam_links"].remove(d)
        save_config()
        await update.message.reply_text(f"🗑 Удалено: {d}", reply_markup=links_kb(cfg))
    else:
        await update.message.reply_text("Такого домена нет.")


async def cmd_links(update, context):
    if not is_manager(update.effective_user.id):
        return
    cfg = panel_cfg(context)
    await update.message.reply_text(
        f"🔗 Спам-домены ({panel_target_label(context)}):\n" + (", ".join(sorted(cfg["spam_links"])) or "—"),
        reply_markup=links_kb(cfg))


async def on_private_document(update, context):
    """Импорт настроек: файл после нажатия «Загрузить» в разделе Бэкап."""
    user = update.effective_user
    awaiting = context.user_data.get("await")
    if awaiting == "sp_content":
        if not is_manager(user.id):
            context.user_data.pop("await", None)
            return
        d = context.user_data.get("sp_draft", {})
        if not d.get("chat_ids"):
            await update.message.reply_text("Сначала выбери группы через /panel.")
            return
        content = _capture_post_content(update.message)
        if content:
            d.update(content)
            context.user_data["await"] = "sp_buttons"
            await update.message.reply_text(
                "Кнопки-ссылки под постом? Пришли по одной на строку: «Текст - https://ссылка» "
                "(по нажатию откроется ссылка). Или /skip (либо пришли «-»), если без кнопок.")
        return
    if awaiting not in ("import_config", "import_chat"):
        if is_manager(user.id) or await user_admin_groups(context, user.id):
            await update.message.reply_text(
                "Чтобы загрузить настройки, открой /panel → 💾 Бэкап → «Загрузить», затем пришли файл.")
        return
    owner = is_owner(user.id)
    if awaiting == "import_config" and not owner:
        context.user_data.pop("await", None)
        await update.message.reply_text("Полный бэкап может восстанавливать только главный владелец.")
        return
    target = context.user_data.get("import_target", context.user_data.get("cfg_target", "defaults"))
    if awaiting == "import_chat" and not await can_edit_target(context, user.id, target):
        context.user_data.pop("await", None)
        context.user_data.pop("import_target", None)
        await update.message.reply_text("Эта цель тебе недоступна.")
        return
    context.user_data.pop("await", None)
    doc = update.effective_message.document
    if not doc:
        return
    if doc.file_size and doc.file_size > 1_000_000:
        await update.message.reply_text(
            "Файл слишком большой — вряд ли это настройки.", reply_markup=backup_kb(owner))
        return
    try:
        tg_file = await doc.get_file()
        raw = await tg_file.download_as_bytearray()
        parsed = json.loads(bytes(raw).decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        await update.message.reply_text(
            f"Не смог прочитать файл как JSON: {e}", reply_markup=backup_kb(owner))
        return
    if not isinstance(parsed, dict):
        await update.message.reply_text(
            "Это не похоже на настройки (ожидался JSON-объект).", reply_markup=backup_kb(owner))
        return

    if awaiting == "import_config":
        new = _merge_defaults(parsed)
        CONFIG.clear()
        CONFIG.update(new)
        save_config()
        await update.message.reply_text(
            "✅ Полный бэкап восстановлен — применены все настройки бота.",
            reply_markup=main_menu_kb(panel_target_label(context), full=True))
        return

    # awaiting == "import_chat": настройки одной группы/шаблона
    if isinstance(parsed.get("settings"), dict):
        settings = parsed["settings"]
    elif any(k in parsed for k in PER_CHAT_KEYS) and not any(
            k in parsed for k in ("managers", "chats", "approved_chats", "groups")):
        settings = parsed  # «голый» объект настроек тоже принимаем
    else:
        await update.message.reply_text(
            "Это не похоже на настройки группы. Нужен файл, полученный кнопкой "
            "«Скачать настройки этой группы».", reply_markup=backup_kb(owner))
        return
    context.user_data.pop("import_target", None)
    apply_chat_settings(target, settings)
    await update.message.reply_text(
        f"✅ Настройки применены к «{panel_target_label(context)}».",
        reply_markup=backup_kb(owner))


async def on_private_media(update, context):
    """Медиа в личке: содержимое запланированного поста (любой тип) или фото для рассылки/поста."""
    user = update.effective_user
    awaiting = context.user_data.get("await")
    msg = update.message
    # Мастер планировщика — принимаем любой контент
    if awaiting == "sp_content":
        if not is_manager(user.id):
            context.user_data.pop("await", None)
            return
        d = context.user_data.get("sp_draft", {})
        if not d.get("chat_ids"):
            await msg.reply_text("Сначала выбери группы через /panel.")
            return
        content = _capture_post_content(msg)
        if not content:
            await msg.reply_text("Не понял контент. Пришли ещё раз или /cancel.")
            return
        d.update(content)
        if d["type"] in _NO_CAPTION_TYPES:
            context.user_data["await"] = "sp_time"
            await msg.reply_text(
                "Во сколько публиковать каждый день? Формат ЧЧ:ММ, например 13:00 (час дня) "
                "или 02:00 (два ночи).\n(или /cancel)")
        else:
            context.user_data["await"] = "sp_buttons"
            await msg.reply_text(
                "Кнопки-ссылки под постом? Пришли по одной на строку: «Текст - https://ссылка» "
                "(по нажатию откроется ссылка). Или /skip (либо пришли «-»), если без кнопок.")
        return
    # Рассылка/пост одним фото (как было)
    if awaiting not in ("broadcast", "post", "dmcast"):
        return
    if not is_manager(user.id):
        context.user_data.pop("await", None)
        return
    if not msg.photo:
        await msg.reply_text("Для этого шага пришли фото или текст (видео/стикеры — только в планировщике постов).")
        return
    photo_id = msg.photo[-1].file_id
    caption = (msg.caption or "").strip()
    context.user_data.pop("await", None)
    pin = CONFIG["promo"].get("pin", False)
    if awaiting == "broadcast":
        if not CONFIG["groups"]:
            await msg.reply_text("Пока нет известных групп.")
            return
        ok, fail = await _broadcast(context, caption, photo_id, pin)
        await msg.reply_text(f"📣 Разослано в {ok} групп(ы), не доставлено: {fail}.", reply_markup=promo_kb())
    elif awaiting == "post":
        cid = context.user_data.pop("post_chat", None)
        if not cid:
            await msg.reply_text("Группа не выбрана. Попробуй снова через /panel.")
            return
        try:
            await _post_to_chat(context, cid, caption, photo_id, pin)
            await msg.reply_text("✅ Опубликовано (фото).", reply_markup=promo_kb())
        except Exception as e:  # noqa: BLE001
            await msg.reply_text(f"Не вышло опубликовать: {e}", reply_markup=promo_kb())
    elif awaiting == "dmcast":
        cid = context.user_data.pop("dmcast_chat", None)
        if not cid:
            await msg.reply_text("Группа не выбрана. Попробуй снова через /panel.")
            return
        ok, fail = await _dm_broadcast(context, cid, caption, photo_id)
        await msg.reply_text(
            f"📨 Отправлено {ok} подписчикам, не доставлено: {fail}.", reply_markup=promo_kb())


async def on_private_text(update, context):
    user = update.effective_user
    manager = is_manager(user.id)
    if not manager and not await user_admin_groups(context, user.id):
        return
    awaiting = context.user_data.get("await")
    if not awaiting:
        await update.message.reply_text("Открой панель: /panel")
        return
    # Глобальные действия — только менеджерам
    if awaiting in ("promo", "invite_text", "broadcast", "post", "dmcast",
                    "sp_name", "sp_content", "sp_buttons", "sp_time",
                    "gbid", "gbname", "gword") and not manager:
        context.user_data.pop("await", None)
        await update.message.reply_text("Это только для владельца/менеджеров бота.")
        return
    # Настройки конкретной цели — проверяем право на неё
    if awaiting in ("trigger", "word", "word2", "blid", "blname", "link", "welcome", "welcome_btns", "rules", "recurring", "role_new"):
        tgt = context.user_data.get("cfg_target", "defaults")
        if not await can_edit_target(context, user.id, tgt):
            context.user_data.pop("await", None)
            await update.message.reply_text("Эта цель тебе недоступна.")
            return
    text = (update.effective_message.text or "").strip()
    context.user_data.pop("await", None)

    if awaiting == "trigger":
        if "=" not in text:
            context.user_data["await"] = "trigger"
            await update.message.reply_text(
                "Нужен формат: слово = ответ (можно несколько слов через запятую). Попробуй снова или /cancel.")
            return
        keys_part, resp = text.split("=", 1)
        resp = resp.strip()
        words = [w.strip().lower() for w in keys_part.split(",") if w.strip()]
        if words and resp:
            cfg = panel_cfg(context)
            for w in words:
                cfg["triggers"][w] = resp
            save_config()
            if len(words) == 1:
                msg = f"✅ Добавлено: «{words[0]}» → «{resp}» ({panel_target_label(context)})"
            else:
                msg = (f"✅ Добавлено {len(words)} слов → один ответ «{resp}» ({panel_target_label(context)}):\n"
                       + ", ".join(words))
            await update.message.reply_text(msg, reply_markup=triggers_kb(cfg))
        else:
            context.user_data["await"] = "trigger"
            await update.message.reply_text("Пусто. Формат: слово1, слово2 = ответ. Попробуй снова или /cancel.")
    elif awaiting == "word":
        w = text.lower()
        cfg = panel_cfg(context)
        if w and w not in cfg["stop_words"]:
            cfg["stop_words"].append(w)
            save_config()
        await update.message.reply_text(
            f"✅ Стоп-слово: {w} ({panel_target_label(context)})", reply_markup=words_kb(cfg))
    elif awaiting == "word2":
        w = text.lower()
        cfg = panel_cfg(context)
        lst = cfg.setdefault("stop_words2", [])
        if w and w not in lst:
            lst.append(w)
            save_config()
        await update.message.reply_text(
            f"✅ Во второй список добавлено: {w} ({panel_target_label(context)})", reply_markup=words2_kb(cfg))
    elif awaiting == "blid":
        cfg = panel_cfg(context)
        digits = "".join(ch for ch in text if ch.isdigit() or ch == "-")
        if not digits.lstrip("-").isdigit():
            await update.message.reply_text("Это не похоже на числовой ID. Попробуй снова через /panel.")
            return
        uid = int(digits)
        ids = cfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("ids", [])
        if uid not in ids:
            ids.append(uid)
            save_config()
        await update.message.reply_text(
            f"🚷 ID {uid} в чёрном списке ({panel_target_label(context)}).", reply_markup=blacklist_kb(cfg))
    elif awaiting == "blname":
        cfg = panel_cfg(context)
        nm = text.lstrip("@").lower().strip()
        names = cfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("names", [])
        if nm and nm not in names:
            names.append(nm)
            save_config()
        await update.message.reply_text(
            f"🚷 Имя «{nm}» в чёрном списке ({panel_target_label(context)}).", reply_markup=blacklist_kb(cfg))
    elif awaiting == "link":
        d = text.lower()
        cfg = panel_cfg(context)
        if d and d not in cfg["spam_links"]:
            cfg["spam_links"].append(d)
            save_config()
        await update.message.reply_text(
            f"✅ Домен: {d} ({panel_target_label(context)})", reply_markup=links_kb(cfg))
    elif awaiting == "gbid":
        digits = "".join(ch for ch in text if ch.isdigit() or ch == "-")
        if not digits.lstrip("-").isdigit():
            await update.message.reply_text("Это не похоже на ID. Попробуй снова через /panel.")
            return
        uid = int(digits)
        ids = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []}).setdefault("ids", [])
        if uid not in ids:
            ids.append(uid); save_config()
        await update.message.reply_text(f"🌍🚷 ID {uid} в глобальном чёрном списке.", reply_markup=global_kb())
    elif awaiting == "gbname":
        nm = text.lstrip("@").lower().strip()
        names = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []}).setdefault("names", [])
        if nm and nm not in names:
            names.append(nm); save_config()
        await update.message.reply_text(f"🌍🚷 Имя «{nm}» в глобальном чёрном списке.", reply_markup=global_kb())
    elif awaiting == "gword":
        w = text.lower().strip()
        gw = CONFIG.setdefault("global_stop_words", [])
        if w and w not in gw:
            gw.append(w); save_config()
        await update.message.reply_text(f"🌍 Глобальное стоп-слово: {w}.", reply_markup=global_kb())
    elif awaiting == "welcome_btns":
        cfg = panel_cfg(context)
        if text.strip() in ("-", "—", "нет"):
            cfg["welcome"]["buttons"] = []
            save_config()
            await update.message.reply_text("Кнопки приветствия убраны.", reply_markup=welcome_kb(cfg))
        else:
            btns = _parse_buttons(text)
            cfg["welcome"]["buttons"] = btns
            save_config()
            await update.message.reply_text(
                f"✅ Кнопок приветствия: {len(btns)} ({panel_target_label(context)}).", reply_markup=welcome_kb(cfg))
    elif awaiting == "welcome":
        if text:
            cfg = panel_cfg(context)
            cfg["welcome"]["text"] = text
            cfg["welcome"]["enabled"] = True
            save_config()
            await update.message.reply_text(
                f"✅ Приветствие сохранено и включено ({panel_target_label(context)}).", reply_markup=welcome_kb(cfg))
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
            cfg = panel_cfg(context)
            cfg["rules"] = text
            save_config()
            await update.message.reply_text(
                f"✅ Правила сохранены ({panel_target_label(context)}).", reply_markup=rules_kb())
        else:
            await update.message.reply_text("Пусто. Попробуй снова через /panel.")
    elif awaiting == "recurring":
        if "=" not in text:
            await update.message.reply_text("Нужен формат: минуты = текст. Попробуй снова через /panel.")
            return
        mins_s, body = text.split("=", 1)
        body = body.strip()
        try:
            mins = max(1, int(mins_s.strip()))
        except ValueError:
            await update.message.reply_text("Минуты должны быть числом. Пример: 120 = текст")
            return
        if not body:
            await update.message.reply_text("Пустой текст. Попробуй снова через /panel.")
            return
        cfg = panel_cfg(context)
        cfg.setdefault("recurring", []).append({"text": body, "interval": mins})
        save_config()
        await update.message.reply_text(
            f"✅ Авто-сообщение добавлено: каждые {mins} мин ({panel_target_label(context)}).",
            reply_markup=recurring_kb(cfg))
    elif awaiting == "role_new":
        nm = text.strip()[:32]
        if not nm:
            await update.message.reply_text("Пустое имя. Попробуй снова через /panel.")
            return
        cfg = panel_cfg(context)
        roles = cfg.setdefault("roles", {})
        if any(k.lower() == nm.lower() for k in roles):
            await update.message.reply_text("Такая роль уже есть.")
            return
        roles[nm] = {"perms": [], "members": []}
        save_config()
        await update.message.reply_text(
            f"✅ Роль «{nm}» создана ({panel_target_label(context)}). Теперь отметь ей права.",
            reply_markup=roles_kb(cfg))
    elif awaiting == "broadcast":
        if not text:
            await update.message.reply_text("Пусто, ничего не разослал.")
            return
        if not CONFIG["groups"]:
            await update.message.reply_text("Пока нет известных групп. Добавь бота в группу и напиши там что-нибудь.")
            return
        ok, fail = await _broadcast(context, text, pin=CONFIG["promo"].get("pin", False))
        await update.message.reply_text(f"📣 Разослано в {ok} групп(ы), не доставлено: {fail}.", reply_markup=promo_kb())
    elif awaiting == "post":
        cid = context.user_data.pop("post_chat", None)
        if not text or not cid:
            await update.message.reply_text("Пусто или группа не выбрана. Попробуй снова через /panel.")
            return
        try:
            await _post_to_chat(context, cid, text, pin=CONFIG["promo"].get("pin", False))
            await update.message.reply_text("✅ Опубликовано.", reply_markup=promo_kb())
        except Exception as e:  # noqa: BLE001
            await update.message.reply_text(f"Не вышло опубликовать: {e}", reply_markup=promo_kb())
    elif awaiting == "dmcast":
        cid = context.user_data.pop("dmcast_chat", None)
        if not text or not cid:
            await update.message.reply_text("Пусто или группа не выбрана. Попробуй снова через /panel.")
            return
        ok, fail = await _dm_broadcast(context, cid, text)
        await update.message.reply_text(
            f"📨 Отправлено {ok} подписчикам, не доставлено: {fail}.", reply_markup=promo_kb())
    elif awaiting == "sp_name":
        name = text[:40].strip()
        if not name:
            context.user_data["await"] = "sp_name"
            await update.message.reply_text("Пусто. Назови пост и пришли снова, или /cancel.")
            return
        d = context.user_data.setdefault("sp_draft", {})
        d["name"] = name
        if not CONFIG["groups"]:
            await update.message.reply_text("Нет групп для постинга.")
            return
        await update.message.reply_text(
            f"Пост «{name}». Выбери группы (можно несколько), затем «Готово»:",
            reply_markup=sched_groups_kb(d.get("chat_ids")))
    elif awaiting == "sp_content":
        d = context.user_data.get("sp_draft", {})
        if not d.get("chat_ids"):
            await update.message.reply_text("Сначала выбери группы через /panel.")
            return
        content = _capture_post_content(update.effective_message)
        if not content:
            context.user_data["await"] = "sp_content"
            await update.message.reply_text("Не понял контент. Пришли текст или медиа, или /cancel.")
            return
        d.update(content)
        if d["type"] in _NO_CAPTION_TYPES:
            context.user_data["await"] = "sp_time"
            await update.message.reply_text(
                "Во сколько публиковать каждый день? Формат ЧЧ:ММ, например 13:00 (час дня) "
                "или 02:00 (два ночи).\n(или /cancel)")
        else:
            context.user_data["await"] = "sp_buttons"
            await update.message.reply_text(
                "Кнопки-ссылки под постом? Пришли по одной на строку: «Текст - https://ссылка» "
                "(по нажатию откроется ссылка). Или /skip (либо пришли «-»), если без кнопок.")
    elif awaiting == "sp_buttons":
        d = context.user_data.get("sp_draft", {})
        if text.strip() not in ("-", "—", "нет", "skip"):
            d["buttons"] = _parse_buttons(text)
        context.user_data["await"] = "sp_time"
        await update.message.reply_text(
            "Во сколько публиковать каждый день? Формат ЧЧ:ММ, например 13:00 (час дня) "
            "или 02:00 (два ночи).\n(или /cancel)")
    elif awaiting == "sp_time":
        mt = re.match(r"^(\d{1,2})[:.\s](\d{2})$", text.strip())
        if not mt:
            context.user_data["await"] = "sp_time"
            await update.message.reply_text("Формат времени ЧЧ:ММ, например 13:00. Пришли снова или /cancel.")
            return
        h, m = int(mt.group(1)), int(mt.group(2))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            context.user_data["await"] = "sp_time"
            await update.message.reply_text("Часы 0–23, минуты 0–59. Пришли снова.")
            return
        d = context.user_data.pop("sp_draft", {})
        cids = d.get("chat_ids") or ([d["chat_id"]] if d.get("chat_id") else [])
        if not cids:
            await update.message.reply_text("Группы потерялись. Начни заново через /panel.")
            return
        post = {
            "id": _new_post_id(), "name": d.get("name", "пост"), "chat_ids": [int(c) for c in cids],
            "time": f"{h:02d}:{m:02d}", "type": d.get("type", "text"), "text": d.get("text", ""),
            "file_id": d.get("file_id"), "buttons": d.get("buttons", []), "pin": False, "enabled": True,
        }
        CONFIG.setdefault("scheduled_posts", []).append(post)
        save_config()
        _schedule_post(context.job_queue, post)
        names = [CONFIG.get("groups", {}).get(str(c), str(c)) for c in post["chat_ids"]]
        await update.message.reply_text(
            f"✅ Пост «{post['name']}» будет выходить каждый день в {post['time']} "
            f"(UTC+{CONFIG.get('post_tz', 5)}) в: {', '.join(names)}.", reply_markup=sched_kb())
    elif awaiting == "import_config":
        await update.message.reply_text(
            "Жду файл config.json (документом), а не текст. /panel → 💾 Бэкап → «Загрузить».")


# ───────────────────────────────────────────────────────────────────────────
#  ОШИБКИ И ЗАПУСК
# ───────────────────────────────────────────────────────────────────────────


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Ошибка при обработке апдейта: %s", context.error)


async def _post_init(app: Application):
    """Меню команд (список при вводе «/») — отдельно для групп и для лички."""
    try:
        group_cmds = [
            BotCommand("info", "👤 Инфо о пользователе + кнопки"),
            BotCommand("warn", "⚠️ Предупредить (ответом)"),
            BotCommand("unwarn", "Снять предупреждение (ответом)"),
            BotCommand("warns", "Сколько предупреждений (ответом)"),
            BotCommand("mute", "🔇 Заглушить (ответом)"),
            BotCommand("unmute", "🔊 Снять заглушение (ответом)"),
            BotCommand("ban", "🚫 Забанить (ответом)"),
            BotCommand("kick", "👢 Выгнать (ответом)"),
            BotCommand("unban", "Разбанить (ответом или @user)"),
            BotCommand("block", "🚷 В чёрный список + бан (ответом)"),
            BotCommand("unblock", "Убрать из чёрного списка (ответом)"),
            BotCommand("purge", "🧹 Удалить сообщения (ответом на начало)"),
            BotCommand("report", "🚨 Пожаловаться (ответом) — для всех"),
            BotCommand("me", "👤 Мои предупреждения/статус"),
            BotCommand("role", "👥 Выдать роль (ответом): /role Имя"),
            BotCommand("unrole", "Снять роли (ответом)"),
            BotCommand("all", "📣 Позвать всех"),
            BotCommand("say", "🗣 Сказать от имени бота"),
            BotCommand("group", "📜 Показать правила"),
            BotCommand("link", "🔗 Ссылка-приглашение"),
            BotCommand("stats", "📊 Статистика чата"),
            BotCommand("config", "⚙️ Настройки (откроются в личке)"),
            BotCommand("reload", "🔄 Обновить список админов/права"),
            BotCommand("diag", "🔧 Диагностика: почему бот молчит"),
            BotCommand("setstaff", "🛡 Сделать этот чат служебным"),
        ]
        # Команды модерации показываем ТОЛЬКО админам группы (обычные участники их не видят)
        await app.bot.set_my_commands(group_cmds, scope=BotCommandScopeAllChatAdministrators())
        # Обычным участникам в группах — только то, что для них (жалоба и свой статус)
        member_cmds = [
            BotCommand("report", "🚨 Пожаловаться (ответом на сообщение)"),
            BotCommand("me", "👤 Мои предупреждения/статус"),
        ]
        try:
            await app.bot.set_my_commands(member_cmds, scope=BotCommandScopeAllGroupChats())
        except Exception:  # noqa: BLE001
            pass
        priv_cmds = [
            BotCommand("panel", "⚙️ Панель настроек"),
            BotCommand("status", "📊 Статус и настройки"),
            BotCommand("start", "Старт"),
            BotCommand("help", "Что я умею"),
        ]
        await app.bot.set_my_commands(priv_cmds, scope=BotCommandScopeAllPrivateChats())
    except Exception as e:  # noqa: BLE001
        log.debug("set_my_commands: %s", e)


def build_app() -> Application:
    app = Application.builder().token(BOT_TOKEN).post_init(_post_init).build()

    private = filters.ChatType.PRIVATE
    groups = filters.ChatType.GROUPS

    # Замок допуска: в неодобренных группах глушим все остальные хендлеры (group=-1 → раньше всех)
    app.add_handler(MessageHandler(groups, _gate_unapproved), group=-1)

    # ЛС (управление)
    app.add_handler(CommandHandler("start", cmd_start, filters=private))
    app.add_handler(CommandHandler(["panel", "settings", "menu"], cmd_panel, filters=private))
    app.add_handler(CommandHandler(["config", "settings"], cmd_settings_hint, filters=groups))
    app.add_handler(CommandHandler("status", cmd_status, filters=private))
    app.add_handler(CommandHandler("help", cmd_help, filters=private))
    app.add_handler(CommandHandler("cancel", cmd_cancel, filters=private))
    app.add_handler(CommandHandler("skip", cmd_skip, filters=private))
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
    app.add_handler(CommandHandler(["userid", "uid"], cmd_userid))
    app.add_handler(CommandHandler("setwelcome", cmd_setwelcome))
    app.add_handler(CommandHandler("setrules", cmd_setrules))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))

    # Модерация / привлечение (в группах)
    app.add_handler(CommandHandler("reload", cmd_reload, filters=groups))
    app.add_handler(CommandHandler("diag", cmd_diag, filters=groups))
    app.add_handler(CommandHandler("info", cmd_info, filters=groups))
    app.add_handler(CommandHandler(["role", "setrole"], cmd_role, filters=groups))
    app.add_handler(CommandHandler("unrole", cmd_unrole, filters=groups))
    app.add_handler(CommandHandler("setstaff", cmd_setstaff, filters=groups))
    app.add_handler(CommandHandler("ban", cmd_ban, filters=groups))
    app.add_handler(CommandHandler("unban", cmd_unban, filters=groups))
    app.add_handler(CommandHandler("block", cmd_block, filters=groups))
    app.add_handler(CommandHandler("unblock", cmd_unblock, filters=groups))
    app.add_handler(CommandHandler("purge", cmd_purge, filters=groups))
    app.add_handler(CommandHandler("report", cmd_report, filters=groups))
    app.add_handler(CommandHandler(["me", "status"], cmd_me, filters=groups))
    app.add_handler(CommandHandler("appeal", cmd_appeal, filters=private))
    app.add_handler(CommandHandler("gblock", cmd_gblock, filters=groups))
    app.add_handler(CommandHandler("gunblock", cmd_gunblock, filters=groups))
    app.add_handler(CommandHandler("kick", cmd_kick, filters=groups))
    app.add_handler(CommandHandler("mute", cmd_mute, filters=groups))
    app.add_handler(CommandHandler("unmute", cmd_unmute, filters=groups))
    app.add_handler(CommandHandler("warn", cmd_warn, filters=groups))
    app.add_handler(CommandHandler("unwarn", cmd_unwarn, filters=groups))
    app.add_handler(CommandHandler(["warns", "warnings"], cmd_warns, filters=groups))
    app.add_handler(CommandHandler("stats", cmd_stats, filters=groups))
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
    app.add_handler(ChatJoinRequestHandler(on_join_request))

    # Новые участники
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))

    # Смена названия/фото группы (анти-снос)
    app.add_handler(MessageHandler(
        filters.StatusUpdate.NEW_CHAT_TITLE | filters.StatusUpdate.NEW_CHAT_PHOTO | filters.StatusUpdate.DELETE_CHAT_PHOTO,
        on_chat_settings_change))

    # Ночной режим и медиа-фильтр — отдельная группа 0 (может удалить и остановить обработку)
    app.add_handler(MessageHandler(
        groups & ~filters.StatusUpdate.ALL & ~filters.COMMAND, on_group_guard), group=0)

    # Антиспам / стоп-слова / автоответы / антифлуд — ГРУППА 1 (своя, иначе сторож выше
    # перехватил бы апдейт первым и этот хендлер не запустился бы)
    app.add_handler(MessageHandler(
        groups & (filters.TEXT | filters.CAPTION) & ~filters.StatusUpdate.ALL, on_group_message), group=1)

    # Текст в ЛС
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_private_text))
    # Файл в ЛС (импорт настроек)
    app.add_handler(MessageHandler(
        private & (filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Sticker.ALL
                   | filters.VIDEO_NOTE | filters.AUDIO | filters.VOICE),
        on_private_media))
    app.add_handler(MessageHandler(private & filters.Document.ALL, on_private_document))

    # Апгрейд группы в супергруппу — перенести одобрение/настройки на новый chat_id
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, on_migrate), group=1)

    # Чистка сервис-сообщений (вход/выход/закреп/смена фото) — отдельная группа,
    # чтобы работать вместе с приветствием/капчей/анти-сносом, а не вместо них
    app.add_handler(MessageHandler(groups & filters.StatusUpdate.ALL, on_service_cleanup), group=1)

    app.add_error_handler(on_error)
    return app


def main():
    if not BOT_TOKEN:
        print("❌ Не задан BOT_TOKEN. На Railway добавь переменную BOT_TOKEN.")
        sys.exit(1)
    log.info("Запуск. Владельцы: %s. Конфиг: %s", ADMIN_IDS, CONFIG_PATH)
    app = build_app()
    if app.job_queue:
        # чтобы авто-промо не выстрелило сразу после запуска — отсчёт интервала с этого момента
        _state["last_promo"] = time.time()
        app.job_queue.run_repeating(promo_job, interval=60, first=30)
        app.job_queue.run_repeating(recurring_job, interval=60, first=20)
        app.job_queue.run_repeating(weekly_digest_job, interval=7 * 86400, first=7 * 86400)
        _reschedule_all_posts(app.job_queue)  # восстановить расписание постов из конфига
    else:
        log.warning("JobQueue недоступен — авто-промо и запланированные посты работать не будут.")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
