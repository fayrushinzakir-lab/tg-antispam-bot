# -*- coding: utf-8 -*-
"""
Channel Guard Bot  —  версия 5
================================================
Антиспам + автоответы (текст/медиа/кнопки) + панель в ЛС + модерация + капча +
приветствие + привлечение (промо, рассылки, посты по расписанию) + роли +
анти-снос/анти-рейд + оплата звёздами Telegram.

Что нового в v5 (относительно v4):
  • Стоп-слова: точное совпадение по умолчанию; «слово*» — начало слова,
    «*слово» — конец, «*слово*» — любое вхождение. Нормализация обходов
    (невидимые символы, латинские двойники букв, ё=е).
  • Ключи автоответов и «⚪ Исключения» (белый список) не считаются нарушением.
  • Наказание за спам настраивается: удалить / предупреждение / мут / бан.
    Предупреждения идут в общий счётчик (/warns) с эскалацией по настройкам.
  • Автоответы: медиа (фото/видео/гиф/стикер/документ), HTML-форматирование,
    инлайн-кнопки-ссылки, рандомизация {а|б}, кулдаун от само-спама.
  • Владелец/менеджеры бота: команды работают даже в неодобренных чатах,
    можно модерировать админов групп (мут по админу — «мягкий», удалением).
  • Ловля скрытых ссылок (text_link) и точные границы доменов.
  • Один конвейер обработки сообщений, единый отправщик постов (deliver),
    единый минутный тик (промо/авто-сообщения/посты), уборщик памяти,
    отложенная запись конфига (без записи файла на каждое сообщение).
  • Статистика модерации и список участников для /all переживают перезапуск.

Запуск: переменная окружения BOT_TOKEN. Главный владелец: ADMIN_IDS.
Зависимости: pip install "python-telegram-bot[job-queue,rate-limiter]"
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
import random
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllPrivateChats,
)
from telegram.error import BadRequest, Forbidden, NetworkError, TimedOut, RetryAfter
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ChatJoinRequestHandler,
    PreCheckoutQueryHandler,
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
    "cfg_version": 5,
    "enabled": {
        "invites": True, "shorteners": True, "all_links": False, "spam_domains": True,
        "words": True, "flood": True, "name_check": True, "triggers": True,
        "words2": False,
        "clean_service": False,
        "clean_commands": False,
    },
    "flood": {"limit": 5, "period": 10, "mute": 300},
    # Синтаксис: слово — точное совпадение; слово* — начало; *слово — конец; *слово* — вхождение.
    "stop_words": [
        "казино*", "casino*", "крипт*", "ставк*", "букмекер*",
        "заработок", "заработай", "инвестиц*", "1xbet", "1win", "mostbet",
        "порно*", "porn*", "интим*",
    ],
    # Исключения: никогда не считаются нарушением (плюс ключи автоответов защищены сами).
    "white_words": [],
    # Реакция на спам-ссылки и стоп-слова (первый список): delete | warn | mute | ban
    "spam_action": "delete",
    # Второй список слов — свой набор и СВОЁ наказание (обычно строже первого).
    # action: delete|warn|mute|ban. profile: искать слова ещё и в имени/юзернейме отправителя.
    "stop_words2": [],
    "stop_words2_action": "ban",
    "stop_words2_profile": True,
    "spam_links": [],
    # Автоответы: значение — текст ИЛИ объект {"type","file_id","text","html","buttons"}
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
    # Наказание медиа-фильтра: delete|warn|mute|ban
    "media_action": "delete",
    # Ночной режим: в заданные часы сообщения обычных участников удаляются
    "night": {"enabled": False, "start": 23, "end": 7, "tz": 0},
    # Повторяющиеся авто-сообщения: [{"text": ..., "interval": минуты, "enabled": True}]
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
        "type": "text",
        "file_id": None,
        "buttons": [],
        "html": False,
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
    # Подписчики ЛС по группам (кто прошёл капчу-заявку): {chat_id: [user_ids]}
    "dm_subscribers": {},
    # Подписки на тариф «Профессиональный»: {chat_id: ts окончания}
    "subscriptions": {},
    # Пробный период: дней по умолчанию и выданные триалы {chat_id: ts окончания}
    "trial_days": 3,
    "trials": {},
    # Статистика: {chat_id: {users, names, days, total, mod}} — единое хранилище
    # (users/names — и роспись активности, и список участников для /all; mod — счётчики модерации)
    "msg_stats": {},
    # Запланированные посты: список объектов
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
    ("clean_commands", "Чистить команды в чате (/start, /ban…)"),
]

# Подписи действий-наказаний (единые по всем меню)
_ACT_RU = {"delete": "только удалить", "warn": "удалить + пред", "mute": "удалить + мут", "ban": "удалить + бан"}
_ACT_CYCLE = ["delete", "warn", "mute", "ban"]

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
PER_CHAT_KEYS = ("enabled", "flood", "stop_words", "white_words", "spam_action",
                 "stop_words2", "stop_words2_action",
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
    trg = d.get("triggers")
    if not isinstance(trg, dict):
        return
    if not any("," in k for k in trg):
        return
    new = {}
    for k, v in trg.items():
        if "," in k:
            for w in k.split(","):
                w = w.strip().lower()
                if w:
                    new[w] = copy.deepcopy(v)
        else:
            new[k] = v
    d["triggers"] = new


def _force_all_admins_only(cfg: dict) -> None:
    """Призыв /all нельзя открывать «всем» — переводим такой уровень в «админы»
    (на верхнем уровне и в каждом чате)."""
    def fix(d):
        cp = d.get("cmd_perms")
        if isinstance(cp, dict) and cp.get("all") == "all":
            cp["all"] = "admins"
    fix(cfg)
    for ch in cfg.get("chats", {}).values():
        if isinstance(ch, dict):
            fix(ch)


# Миграция v4 → v5: старые слова из дефолтного списка были «основами» и ловились
# по вхождению; теперь поиск точный, поэтому известным основам дописываем «*»,
# чтобы поведение не сломалось. Свои слова пользователя остаются точными.
_V5_STARS = {"казино", "casino", "крипт", "ставк", "букмекер", "инвестиц", "порно", "porn", "интим"}


def _star_words(lst):
    out = []
    for w in lst or []:
        wl = str(w)
        out.append(wl + "*" if wl.lower() in _V5_STARS and not wl.endswith("*") else wl)
    return out


def _migrate_v5(cfg: dict) -> None:
    cfg["stop_words"] = _star_words(cfg.get("stop_words"))
    cfg["stop_words2"] = _star_words(cfg.get("stop_words2"))
    cfg["global_stop_words"] = _star_words(cfg.get("global_stop_words"))
    for ch in cfg.get("chats", {}).values():
        if isinstance(ch, dict):
            ch["stop_words"] = _star_words(ch.get("stop_words"))
            ch["stop_words2"] = _star_words(ch.get("stop_words2"))


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw = json.load(f)
            cfg = _merge_defaults(raw)
            # Миграция при обновлении со старой версии: уже известные группы
            # автоматически считаем разрешёнными, чтобы бот в них не замолчал.
            if isinstance(raw, dict) and raw.get("groups") and not cfg.get("approved_chats"):
                cfg["approved_chats"] = [int(c) for c in raw["groups"].keys()]
            # Починка автоответов: старые «склеенные» ключи с запятой разбиваем на слова
            _split_comma_triggers(cfg)
            for ch in cfg.get("chats", {}).values():
                if isinstance(ch, dict):
                    _split_comma_triggers(ch)
            _force_all_admins_only(cfg)
            if isinstance(raw, dict) and int(raw.get("cfg_version", 0) or 0) < 5:
                _migrate_v5(cfg)
            cfg["cfg_version"] = 5
            return cfg
        except Exception as e:  # noqa: BLE001
            log.warning("Не прочитать %s: %s", CONFIG_PATH, e)
    return copy.deepcopy(DEFAULT_CONFIG)


# ── Отложенная запись конфига: save_config() лишь помечает «грязным»,
#    файл пишет _flush_config() (по таймеру, при выключении и при force=True). ──
_cfg_dirty = False


def save_config(force: bool = False) -> None:
    global _cfg_dirty
    _cfg_dirty = True
    if force:
        _flush_config()


def _flush_config() -> None:
    global _cfg_dirty
    if not _cfg_dirty:
        return
    _cfg_dirty = False
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
#  ПАМЯТЬ (оперативная; периодически чистится janitor_job)
# ───────────────────────────────────────────────────────────────────────────

flood_store: dict = defaultdict(deque)    # (chat_id, user_id) -> метки сообщений
nuke_store: dict = defaultdict(deque)     # (chat_id, actor_id) -> метки банов (анти-снос)
captcha_pending: dict = {}                # (chat_id, user_id) -> message_id капчи
_admin_cache: dict = {}
_creator_cache: dict = {}                 # chat_id -> id создателя группы (или None)
_recurring_last: dict = {}                # (chat_id, idx) -> метка последней отправки авто-сообщения
soft_mutes: dict = {}                     # (chat_id, user_id) -> до какого времени удалять (0 = до снятия)
join_dates: dict = {}                     # (chat_id, user_id) -> метка времени входа (для /info)
_throttle_store: dict = {}
_join_handled: dict = {}                  # (chat_id, user_id) -> ts обработки входа (антидубль)
join_requests: dict = {}                  # (chat_id, user_id) -> True, пока ждём капчу-заявку
_raid_joins: dict = {}                    # chat_id -> deque меток входов
_raid_until: dict = {}                    # chat_id -> ts, до которого активен строгий режим
_all_active: dict = {}                    # chat_id -> идёт ли сейчас призыв /all
_report_cd: dict = {}                     # (chat_id, user_id) -> ts последней жалобы
_appeal_cd: dict = {}                     # user_id -> ts последней апелляции
_expiry_notified = set()                  # chat_id (str), по которым уже сообщили об окончании доступа
_post_last_fired: dict = {}               # post_id -> "YYYY-MM-DD HH:MM" (защита от двойной публикации)
ADMIN_CACHE_TTL = 300
_state = {"last_promo": 0.0}


def soft_mute_add(chat_id: int, user_id: int, seconds: int = 0):
    """Мягкий мут: сообщения этого пользователя удаляются (для обычных групп и для админов)."""
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


def _throttle(key, seconds: float) -> bool:
    """Анти-флуд действий: True, если по ключу прошло >= seconds с прошлого раза."""
    now = time.time()
    if now - _throttle_store.get(key, 0.0) < seconds:
        return False
    _throttle_store[key] = now
    return True

# ───────────────────────────────────────────────────────────────────────────
#  СТАТИСТИКА (единая, персистентная): msg_stats[chat] = users/names/days/total/mod
# ───────────────────────────────────────────────────────────────────────────


def _stats_chat(chat_id) -> dict:
    ms = CONFIG.setdefault("msg_stats", {}).setdefault(
        str(chat_id), {"users": {}, "names": {}, "days": {}, "total": 0, "mod": {}})
    ms.setdefault("mod", {})
    ms.setdefault("users", {})
    ms.setdefault("names", {})
    ms.setdefault("days", {})
    return ms


def bump(chat_id: int, metric: str, n: int = 1) -> None:
    """Счётчики модерации (персистентные, для /stats и недельной сводки)."""
    mod = _stats_chat(chat_id)["mod"]
    mod[metric] = mod.get(metric, 0) + n
    save_config()


def _display_name(user) -> str:
    nm = (getattr(user, "full_name", None) or getattr(user, "first_name", None) or "—")
    if getattr(user, "username", None):
        nm = f"@{user.username}"
    return nm[:40]


def remember_member(chat_id: int, user) -> None:
    """Запомнить участника (для /all и топов) — даже если он ещё ничего не писал."""
    if user is None or getattr(user, "is_bot", False):
        return
    ms = _stats_chat(chat_id)
    uid = str(user.id)
    ms["users"].setdefault(uid, 0)
    nm = _display_name(user)
    if ms["names"].get(uid) != nm:
        ms["names"][uid] = nm
        save_config()


def track_message(chat_id: int, user) -> None:
    """Учёт сообщений: всего, по дням и по пользователям (пишется отложенно)."""
    ms = _stats_chat(chat_id)
    uid = str(user.id)
    ms["users"][uid] = ms["users"].get(uid, 0) + 1
    ms["names"][uid] = _display_name(user)
    today = datetime.now(_post_tz()).strftime("%Y-%m-%d")
    ms["days"][today] = ms["days"].get(today, 0) + 1
    ms["total"] = ms.get("total", 0) + 1
    if len(ms["days"]) > 40:  # храним ~месяц
        for d in sorted(ms["days"])[:-35]:
            ms["days"].pop(d, None)
    if len(ms["users"]) > 600:  # предохранитель памяти для очень больших групп
        keep = dict(sorted(ms["users"].items(), key=lambda kv: kv[1], reverse=True)[:500])
        ms["users"] = keep
        ms["names"] = {u: n for u, n in ms["names"].items() if u in keep}
    save_config()


def _msg_stats_summary(chat_id):
    """Возвращает (total, today, week, top[(name,count)…]) по сообщениям чата."""
    ms = CONFIG.get("msg_stats", {}).get(str(chat_id))
    if not ms:
        return 0, 0, 0, []
    tz = _post_tz()
    today = datetime.now(tz).strftime("%Y-%m-%d")
    days = ms.get("days", {})
    week_days = {(datetime.now(tz) - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)}
    week = sum(c for d, c in days.items() if d in week_days)
    names = ms.get("names", {})
    top = [kv for kv in sorted(ms.get("users", {}).items(), key=lambda kv: kv[1], reverse=True)
           if kv[1] > 0][:10]
    top_named = [(names.get(uid, uid), cnt) for uid, cnt in top]
    return ms.get("total", 0), days.get(today, 0), week, top_named


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
    ("all",  "📣 Призыв /all",               ["admins", "owner"], "admins"),
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


def is_anon_admin(update) -> bool:
    """True, если сообщение прислано анонимным администратором группы."""
    msg = getattr(update, "effective_message", None)
    chat = getattr(update, "effective_chat", None)
    if msg is not None and chat is not None:
        sc = getattr(msg, "sender_chat", None)
        if sc is not None and getattr(sc, "id", None) == chat.id:
            return True
    u = getattr(update, "effective_user", None)
    return bool(u is not None and getattr(u, "id", None) == 1087968824)  # GroupAnonymousBot


async def can_moderate(context, chat_id: int, user_id: int, key: str = "ban", update=None) -> bool:
    if is_manager(user_id):
        return True
    if chat_cfg(chat_id)["moderation"].get("mod_admins_only"):
        return False  # «Модерация только для владельца» — строгий режим (роли тоже не действуют)
    if role_grants(chat_id, user_id, key):
        return True  # кастомная роль выдала это право
    level = cmd_level(chat_id, key)
    if level == "all":
        return True
    if update is not None and is_anon_admin(update) and level == "admins":
        return True  # анонимный админ = администратор группы
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
    """Группы (cid_str, title), которыми человек вправе управлять через бота."""
    out = []
    for cid, title in CONFIG.get("groups", {}).items():
        try:
            if await can_open_settings(context, int(cid), user_id):
                out.append((cid, title))
        except Exception:  # noqa: BLE001
            continue
    return out


async def can_edit_target(context, user_id: int, target) -> bool:
    """Может ли человек править эту цель панели."""
    if is_manager(user_id):
        return True
    if not target or target == "defaults":
        return False
    try:
        return await can_open_settings(context, int(target), user_id)
    except Exception:  # noqa: BLE001
        return False


def chat_allowed(chat_id: int) -> bool:
    """True, если бот допущен работать в этом чате: одобрение (бесплатно),
    оплата звёздами или активный пробный период."""
    if not CONFIG.get("require_approval", True):
        return True
    if chat_id in CONFIG.get("approved_chats", []):
        return True
    return is_pro(chat_id) or trial_active(chat_id)


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


def _duration_and_reason(update: Update, context):
    """Разбор хвоста /ban и /mute: необязательная длительность (30m/2ч/1д) + причина."""
    args = list(context.args)
    if not update.effective_message.reply_to_message and args:
        args = args[1:]
    duration, rest = None, []
    for a in args:
        d = parse_duration(a)
        if d is not None and duration is None:
            duration = d
        else:
            rest.append(a)
    return duration, " ".join(rest).strip()


def _args_text(update: Update) -> str:
    text = update.effective_message.text or ""
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _csv(text: str):
    """«слово1, слово2» → список нормализованных слов."""
    return [w.strip().lower() for w in (text or "").split(",") if w.strip()]


def _add_unique(lst: list, words) -> list:
    """Добавить в список только новые элементы; вернуть добавленные."""
    added = [w for w in words if w not in lst]
    lst.extend(added)
    return added


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

# ───────────────────────────────────────────────────────────────────────────
#  ДВИЖОК СЛОВ И ДЕТЕКТОРЫ
# ───────────────────────────────────────────────────────────────────────────

_ZW_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
_L2C = str.maketrans("acekmopxyACEKMOPXY", "асекморхуАСЕКМОРХУ")


def _norm(s: str) -> str:
    """Против обходов: убираем невидимые символы, латинские двойники приводим
    к кириллице, ё → е. Применяется и к тексту, и к самим словам."""
    return _ZW_RE.sub("", s).translate(_L2C).replace("ё", "е").replace("Ё", "Е")


def _word_pattern(w: str):
    """Скомпилированный шаблон стоп-слова:
       слово   — только целое слово («бан» НЕ сработает на «банан»)
       слово*  — начало слова («ставк*» ловит «ставки», но не «выставка»)
       *слово  — конец слова
       *слово* — любое вхождение (старое поведение)"""
    w = _norm(w.lower().strip())
    pre, suf = w.startswith("*"), w.endswith("*")
    core = w.strip("*")
    if not core:
        return None
    esc = re.escape(core)
    if pre and suf:
        pat = esc
    elif suf:
        pat = r"(?<!\w)" + esc
    elif pre:
        pat = esc + r"(?!\w)"
    else:
        pat = r"(?<!\w)" + esc + r"(?!\w)"
    try:
        return re.compile(pat)
    except re.error:
        return re.compile(re.escape(core))


def _enclosing_word(t: str, start: int, end: int) -> str:
    """Целое слово, внутри которого нашлось совпадение (расширяем до границ слова)."""
    i, j = start, end
    while i > 0 and (t[i - 1].isalnum() or t[i - 1] == "_"):
        i -= 1
    while j < len(t) and (t[j].isalnum() or t[j] == "_"):
        j += 1
    return t[i:j]


def _protected_words(cfg) -> list:
    """Что нельзя считать нарушением: белый список + ключи автоответов (если включены)."""
    out = list(cfg.get("white_words", []) or [])
    if cfg["enabled"].get("triggers"):
        out += [str(k) for k in (cfg.get("triggers") or {}).keys()]
    return [_norm(x.lower().strip()) for x in out if x and str(x).strip("*").strip()]


def _is_protected(token: str, protected: list) -> bool:
    for p in protected:
        pre, suf = p.startswith("*"), p.endswith("*")
        core = p.strip("*")
        if not core:
            continue
        if pre and suf:
            if core in token:
                return True
        elif suf:
            if token.startswith(core):
                return True
        elif pre:
            if token.endswith(core):
                return True
        elif token == core:
            return True
    return False


def _find_word(t: str, words, protected):
    """Первое стоп-слово, у которого есть совпадение НЕ внутри защищённого слова."""
    if not t:
        return None
    for w in words or []:
        rx = w and _word_pattern(str(w))
        if not rx:
            continue
        for m in rx.finditer(t):
            if not _is_protected(_enclosing_word(t, m.start(), m.end()), protected):
                return w
    return None


def check_word_lists(text: str, cfg: dict, user=None):
    """Проверка по всем спискам. Возвращает (слово, действие) или None.
    Второй список приоритетнее (обычно строже); белый список и ключи
    автоответов защищают совпадения во всех списках, включая глобальный."""
    t = _norm((text or "").lower())
    protected = _protected_words(cfg)
    if cfg["enabled"].get("words2"):
        hit = _find_word(t, cfg.get("stop_words2"), protected)
        if not hit and user is not None and cfg.get("stop_words2_profile", True):
            prof = _norm(" ".join(filter(None, [getattr(user, "first_name", None),
                                                 getattr(user, "last_name", None),
                                                 getattr(user, "username", None)])).lower())
            hit = _find_word(prof, cfg.get("stop_words2"), protected)
        if hit:
            return hit, cfg.get("stop_words2_action", "ban")
    if cfg["enabled"].get("words"):
        hit = (_find_word(t, cfg.get("stop_words"), protected)
               or _find_word(t, CONFIG.get("global_stop_words"), protected))
        if hit:
            return hit, cfg.get("spam_action", "delete")
    return None


def _name_flagged(cfg, name: str) -> bool:
    """Спам в имени/юзернейме новичка: стоп-слова (без защиты исключений) или ссылки."""
    t = _norm((name or "").lower())
    return bool(_find_word(t, cfg.get("stop_words"), [])
                or _find_word(t, CONFIG.get("global_stop_words"), [])
                or find_link_violation(name or "", cfg))


def _domain_hit(d: str, t: str) -> bool:
    """Домен с границами: «t.cn» не сработает внутри «start.cnn.com»."""
    try:
        return re.search(r"(?<![\w.-])" + re.escape(d.lower()) + r"(?![\w-])", t) is not None
    except re.error:
        return d.lower() in t


def find_link_violation(text: str, cfg: dict):
    t = text.lower()
    en = cfg["enabled"]
    if en.get("invites") and any(
        p in t for p in ("t.me/+", "t.me/joinchat", "telegram.me/+",
                          "telegram.me/joinchat", "joinchat/", "tg://join")
    ):
        return "invite-ссылка"
    if en.get("shorteners") and any(_domain_hit(s, t) for s in SHORTENERS):
        return "сокращённая ссылка"
    if en.get("spam_domains"):
        for d in cfg.get("spam_links", []):
            if d and _domain_hit(d, t):
                return "спам-домен"
    if en.get("all_links") and URL_HINT_RE.search(t):
        return "ссылка"
    return None


def _entity_urls(msg) -> str:
    """Скрытые ссылки (text_link) из текста и подписи — спамеры прячут URL за словами."""
    urls = []
    for ents in (getattr(msg, "entities", None) or (), getattr(msg, "caption_entities", None) or ()):
        for e in ents:
            if getattr(e, "type", None) == "text_link" and getattr(e, "url", None):
                urls.append(e.url)
    return " ".join(urls)


def is_blacklisted(chat_id: int, user) -> bool:
    """Пользователь в чёрном списке — по ID или по подстроке имени/фамилии/юзернейма.
    Проверяется список группы И глобальный (подстрока здесь — осознанно)."""
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


def match_trigger(text: str, cfg: dict):
    """Ключ автоответа в тексте. Ключи со «*» матчатся как стоп-слова.
    Возвращает (ключ, ответ) — ответ может быть строкой или объектом контента."""
    triggers = cfg.get("triggers", {})
    if not triggers:
        return None
    mode = cfg.get("trigger_match", "word")
    low = _norm(text.lower())
    best = None
    best_len = -1
    for key, resp in triggers.items():
        kl = _norm(str(key).lower())
        if "*" in kl:
            rx = _word_pattern(kl)
            hit = bool(rx and rx.search(low))
        elif mode == "contains":
            hit = kl in low
        else:
            try:
                hit = re.search(r"(?<!\w)" + re.escape(kl) + r"(?!\w)", low) is not None
            except re.error:
                hit = kl in low
        if hit and len(kl.strip("*")) > best_len:
            best_len = len(kl.strip("*"))
            best = (key, resp)
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
    """Мут участника. В супергруппе — настоящий. Если Telegram не даёт (обычная
    группа или цель — админ) — «мягкий мут»: сообщения будут удаляться."""
    until = None if not seconds else datetime.now(timezone.utc) + timedelta(seconds=seconds)
    try:
        await context.bot.restrict_chat_member(chat_id, user_id, permissions=MUTE_PERMS, until_date=until)
        soft_mute_remove(chat_id, user_id)  # настоящий мут — мягкий не нужен
    except Exception as e:  # noqa: BLE001
        log.debug("mute %s: %s → мягкий мут", user_id, e)
        soft_mute_add(chat_id, user_id, int(seconds) if seconds else 0)


def _admin_api_hint(e) -> str:
    """Пояснение, когда Telegram отказал в действии над администратором."""
    if "administrator" in str(e).lower():
        return ("\nℹ️ Telegram не даёт ботам банить/ограничивать администраторов — даже с полными "
                "правами. Сними с него админку в настройках группы, и команда сработает. "
                "А /mute по админу уже работает как «мягкий»: я просто удаляю его сообщения.")
    return ""


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


# ── уведомления ─────────────────────────────────────────────────────────────


async def _delete_later(context):
    d = context.job.data
    try:
        await context.bot.delete_message(d["chat_id"], d["mid"])
    except Exception:  # noqa: BLE001
        pass


async def ephemeral(context, chat_id: int, text: str, seconds: int = 10, **kwargs):
    """Сообщение в чат, которое само исчезает — чтобы служебные уведомления
    (предупреждения, флуд-муты, «удалено, потому что…») не засоряли чат."""
    try:
        m = await context.bot.send_message(chat_id, text, **kwargs)
    except Exception as e:  # noqa: BLE001
        log.debug("ephemeral: %s", e)
        return None
    if seconds and context.job_queue:
        context.job_queue.run_once(_delete_later, seconds, data={"chat_id": chat_id, "mid": m.message_id})
    return m


async def reply_tidy(update, context, text, seconds: int = 12, **kwargs):
    """Ответ бота в группе, который сам исчезает через seconds, если включена
    «Чистить команды». В личке или при выключенной чистке — остаётся."""
    msg = await update.effective_message.reply_text(text, **kwargs)
    chat = update.effective_chat
    if (chat and chat.type in ("group", "supergroup")
            and chat_cfg(chat.id)["enabled"].get("clean_commands") and context.job_queue):
        context.job_queue.run_once(_delete_later, seconds, data={"chat_id": chat.id, "mid": msg.message_id})
    return msg


async def alert_owners(context, text, reply_markup=None):
    """Личное оповещение всем главным владельцам (ADMIN_IDS)."""
    for oid in ADMIN_IDS:
        try:
            await context.bot.send_message(oid, text, reply_markup=reply_markup)
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
    """Служебное уведомление по группе: в её Staff-группу, если задана, иначе владельцам."""
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
    await ephemeral(context, chat_id, f"🗑 Сообщение удалено: {reason}.", 5)


# ── единая реакция на нарушения ─────────────────────────────────────────────


async def _drop(msg, chat_id: int):
    """Тихо удалить сообщение и посчитать."""
    try:
        await msg.delete()
        bump(chat_id, "deleted")
    except Exception as e:  # noqa: BLE001
        log.debug("drop: %s", e)


async def _ban_quiet(context, chat_id: int, user_id: int):
    try:
        await context.bot.ban_chat_member(chat_id, user_id)
        bump(chat_id, "banned")
        log.info("Бан (чёрный список) %s в %s", user_id, chat_id)
    except Exception as e:  # noqa: BLE001
        log.debug("ban quiet %s: %s", user_id, e)


async def apply_warn(context, chat_id: int, uid: int, name: str, reason: str = "") -> str:
    """Единственная точка выдачи предупреждения с эскалацией по настройкам.
    Используется командой /warn, кнопкой в /info и авто-наказанием за спам.
    Возвращает текст для объявления."""
    n = inc_warn(chat_id, uid)
    bump(chat_id, "warns")
    m = chat_cfg(chat_id)["moderation"]
    limit = m["warn_limit"]
    tail = f" — {reason}" if reason else ""
    if n >= limit:
        reset_warns(chat_id, uid)
        try:
            if m["warn_action"] == "ban":
                await context.bot.ban_chat_member(chat_id, uid)
                bump(chat_id, "banned")
                return f"🚫 {name}: {n}/{limit} предупреждений{tail} — бан."
            await mute_user(context, chat_id, uid, m["warn_mute"])
            bump(chat_id, "muted")
            return f"🔇 {name}: {n}/{limit} предупреждений{tail} — мут на {human_duration(m['warn_mute'])}."
        except Exception as e:  # noqa: BLE001
            log.debug("apply_warn punish: %s", e)
            return f"⚠️ {name}: {n}/{limit}{tail} — лимит достигнут, но наказать не вышло."
    return f"⚠️ {name}: предупреждение {n}/{limit}{tail}."


async def punish_spam(update, context, reason: str, action=None):
    """Единая реакция на спам: удалить сообщение + наказание по настройке.
    action: delete | warn | mute | ban (по умолчанию — spam_action группы)."""
    msg, chat, user = update.effective_message, update.effective_chat, update.effective_user
    cfg = chat_cfg(chat.id)
    await _drop(msg, chat.id)
    act = action or cfg.get("spam_action", "delete")
    if act == "delete":
        await notify_deleted(context, chat.id, reason)
        return
    if act == "warn":
        note = await apply_warn(context, chat.id, user.id, mention(user), reason)
        if _throttle(("warnnote", chat.id, user.id), 3.0):  # не заваливаем чат уведомлениями
            await ephemeral(context, chat.id, note)
        await log_action(context, chat.id, f"авто: {note}")
        return
    try:
        if act == "ban":
            await context.bot.ban_chat_member(chat.id, user.id)
            bump(chat.id, "banned")
            await ephemeral(context, chat.id, f"🚫 {mention(user)} забанен — {reason}.")
        elif act == "mute":
            await mute_user(context, chat.id, user.id, cfg["flood"]["mute"])
            bump(chat.id, "muted")
            await ephemeral(context, chat.id, f"🔇 {mention(user)} в муте — {reason}.")
        await log_action(context, chat.id, f"авто-{act}: {mention(user)} — {reason}")
    except Exception as e:  # noqa: BLE001
        log.debug("punish_spam %s: %s", act, e)


def track_nuke(chat_id, actor_id):
    a = chat_cfg(chat_id)["antinuke"]
    now = time.time()
    dq = nuke_store[(chat_id, actor_id)]
    dq.append(now)
    while dq and now - dq[0] > a["window"]:
        dq.popleft()
    return len(dq)

# ───────────────────────────────────────────────────────────────────────────
#  ЗАМОК ДОПУСКА И МИГРАЦИЯ ГРУППЫ
# ───────────────────────────────────────────────────────────────────────────


async def _gate_unapproved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Регистрируется в group=-1: в группах без допуска глушит все остальные
    хендлеры. Пропускает владельца/менеджеров бота, /diag /pro /start,
    сообщения об оплате и миграции."""
    chat = update.effective_chat
    if chat is None or getattr(chat, "type", None) not in ("group", "supergroup"):
        return
    remember_group(chat)
    if chat_allowed(chat.id):
        return
    user = update.effective_user
    if user is not None and is_manager(user.id):
        return  # владелец/менеджеры пользуются ботом даже в неодобренном чате
    msg = update.effective_message
    if msg is not None:
        if getattr(msg, "successful_payment", None):
            return  # оплату нельзя терять — иначе звёзды спишутся впустую
        if msg.migrate_to_chat_id or msg.migrate_from_chat_id:
            return
        txt = msg.text or ""
        if txt.startswith(("/diag", "/pro", "/start")):
            return
    raise ApplicationHandlerStop


def _migrate_chat(old_id: int, new_id: int) -> None:
    """Группа стала супергруппой: переносим всё, что привязано к chat_id."""
    o, n = str(old_id), str(new_id)
    if o == n:
        return
    for key in ("groups", "invite_links", "chats", "subscriptions", "trials",
                "msg_stats", "warns", "warns_ts", "all_optout", "dm_subscribers"):
        d = CONFIG.get(key)
        if isinstance(d, dict) and o in d:
            d[n] = d.pop(o)
    if old_id in CONFIG.get("approved_chats", []):
        CONFIG["approved_chats"] = [new_id if c == old_id else c for c in CONFIG["approved_chats"]]
    save_config(force=True)
    log.info("Миграция чата %s → %s", old_id, new_id)


async def on_migrate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg:
        return
    if msg.migrate_to_chat_id:
        _migrate_chat(msg.chat.id, msg.migrate_to_chat_id)
    elif msg.migrate_from_chat_id:
        _migrate_chat(msg.migrate_from_chat_id, msg.chat.id)


# ───────────────────────────────────────────────────────────────────────────
#  ЕДИНЫЙ КОНВЕЙЕР ГРУППОВЫХ СООБЩЕНИЙ
# ───────────────────────────────────────────────────────────────────────────


def message_media_type(msg):
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
    return None


def _is_forward(msg) -> bool:
    return bool(getattr(msg, "forward_origin", None) or getattr(msg, "forward_date", None))


def is_night_now(night: dict) -> bool:
    if not night or not night.get("enabled"):
        return False
    tz = timezone(timedelta(hours=int(night.get("tz", 0))))
    h = datetime.now(tz).hour
    start, end = int(night.get("start", 23)), int(night.get("end", 7))
    if start == end:
        return False
    if start < end:
        return start <= h < end
    return h >= start or h < end  # через полночь


async def on_group_traffic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Весь порядок проверок группового сообщения — сверху вниз в одном месте."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user or user.is_bot:
        return
    remember_group(chat)
    track_message(chat.id, user)
    text = msg.text or msg.caption or ""

    # 1) Мягкий мут — раньше исключений: владелец бота может наложить его даже
    #    на админа группы (Telegram не даёт мутить админов, а удалять — даёт).
    #    Владельцев/менеджеров бота это не касается никогда.
    if not is_manager(user.id) and is_soft_muted(chat.id, user.id):
        return await _drop(msg, chat.id)

    # 2) Админы, менеджеры и участники ролей — фильтры не действуют, только автоответы
    if await is_exempt(context, chat.id, user.id):
        return await maybe_send_trigger(update, context, text)

    # 3) Чёрный список (этой группы + глобальный): удалить и забанить
    if is_blacklisted(chat.id, user):
        await _drop(msg, chat.id)
        return await _ban_quiet(context, chat.id, user.id)

    cfg = chat_cfg(chat.id)

    # 4) Ночной режим
    if is_night_now(cfg.get("night", {})):
        return await _drop(msg, chat.id)

    # 5) Медиа-фильтр
    mb = cfg.get("media_block", {}) or {}
    mt = message_media_type(msg)
    if (mt and mb.get(mt)) or (mb.get("forward") and _is_forward(msg)):
        return await punish_spam(update, context, "запрещённый тип вложения",
                                 action=cfg.get("media_action", "delete"))

    # 6) Ссылки: видимый текст + скрытые text_link
    scan = (text + " " + _entity_urls(msg)).strip()
    reason = find_link_violation(scan, cfg) if scan else None
    if reason:
        return await punish_spam(update, context, reason)

    # 7) Стоп-слова: второй список (своё наказание) → первый + глобальные
    hit = check_word_lists(scan, cfg, user)
    if hit:
        return await punish_spam(update, context, "запрещённое слово", action=hit[1])

    # 8) Антифлуд
    if cfg["enabled"].get("flood") and check_flood(chat.id, user.id, cfg):
        try:
            await mute_user(context, chat.id, user.id, cfg["flood"]["mute"])
            bump(chat.id, "flood_muted")
            await ephemeral(context, chat.id,
                            f"🔇 {mention(user)} замучен на {human_duration(cfg['flood']['mute'])} за флуд.", 15)
        except Exception as e:  # noqa: BLE001
            log.debug("flood mute: %s", e)
        return

    # 9) Автоответы
    await maybe_send_trigger(update, context, text)


async def maybe_send_trigger(update, context, text):
    chat = update.effective_chat
    cfg = chat_cfg(chat.id)
    if not text or not cfg["enabled"].get("triggers"):
        return
    hit = match_trigger(text, cfg)
    if not hit:
        return
    key, resp = hit
    if not _throttle(("trig", chat.id, str(key)), 10.0):
        return  # кулдаун 10 сек на слово — чат нельзя заспамить самим ботом
    post = resp if isinstance(resp, dict) else {"type": "text", "text": str(resp)}
    try:
        await _send_one(context, chat.id, post, reply_to=update.effective_message.message_id)
    except Exception as e:  # noqa: BLE001
        log.debug("trigger: %s", e)

# ───────────────────────────────────────────────────────────────────────────
#  ВХОД НОВИЧКОВ: приветствие, капча, анти-рейд
# ───────────────────────────────────────────────────────────────────────────


async def send_welcome(context, chat, user):
    w = chat_cfg(chat.id).get("welcome", {})
    if not w.get("enabled"):
        return
    text = (w.get("text") or "Добро пожаловать, {name}!")
    text = text.replace("{name}", user.first_name or "друг") \
               .replace("{mention}", mention(user)) \
               .replace("{chat}", chat.title or "чат")
    try:
        m = await context.bot.send_message(chat.id, text,
                                           reply_markup=_post_buttons_markup(w.get("buttons")))
        after = int(w.get("delete_after", 0) or 0)
        if after and context.job_queue:
            context.job_queue.run_once(_delete_later, after, data={"chat_id": chat.id, "mid": m.message_id})
    except Exception as e:  # noqa: BLE001
        log.debug("welcome: %s", e)


async def announce_join_id(context, chat, user):
    mode = chat_cfg(chat.id).get("show_join_id", "off")
    if mode == "off":
        return
    line = f"🆔 Новый участник: {mention(user)} — <code>{user.id}</code>"
    if mode == "all":
        await ephemeral(context, chat.id, line, 30, parse_mode="HTML")
    elif mode == "admins":
        title = CONFIG.get("groups", {}).get(str(chat.id), str(chat.id))
        await notify_staff(context, chat.id, f"🆔 [{title}] вход: {mention(user)} — {user.id}")


async def start_captcha(context, chat, user):
    """Капча в чате: новичок в муте (настоящем или мягком), пока не нажмёт кнопку."""
    cfg = chat_cfg(chat.id)["captcha"]
    key = (chat.id, user.id)
    if key in captcha_pending:
        return
    await mute_user(context, chat.id, user.id, 0)  # до нажатия
    mode = cfg.get("action", "kick")
    txt = tr(chat.id, "cap_kick" if mode == "kick" else "cap_muted",
             name=mention(user), time=human_duration(cfg.get("timeout", 120)))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(chat.id, "cap_btn"),
                                                     callback_data=f"cap:{user.id}")]])
    try:
        m = await context.bot.send_message(chat.id, txt, reply_markup=kb)
        captcha_pending[key] = m.message_id
        if context.job_queue:
            context.job_queue.run_once(captcha_timeout, cfg.get("timeout", 120),
                                       data={"chat_id": chat.id, "uid": user.id})
    except Exception as e:  # noqa: BLE001
        log.debug("captcha: %s", e)
        soft_mute_remove(chat.id, user.id)


async def captcha_timeout(context):
    d = context.job.data
    chat_id, uid = d["chat_id"], d["uid"]
    mid = captcha_pending.pop((chat_id, uid), None)
    if mid is None:
        return  # уже нажал
    try:
        await context.bot.delete_message(chat_id, mid)
    except Exception:  # noqa: BLE001
        pass
    if chat_cfg(chat_id)["captcha"].get("action", "kick") == "kick":
        try:
            await context.bot.ban_chat_member(chat_id, uid)
            await context.bot.unban_chat_member(chat_id, uid)  # кик, не бан
            bump(chat_id, "kicked")
        except Exception as e:  # noqa: BLE001
            log.debug("captcha kick: %s", e)
        soft_mute_remove(chat_id, uid)
    # режим «мут»: остаётся в муте, пока админ не размутит


async def handle_captcha_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    try:
        uid = int((query.data or "cap:0").split(":", 1)[1])
    except ValueError:
        return await query.answer()
    if update.effective_user.id != uid:
        return await query.answer("Эта кнопка не для тебя 🙂", show_alert=True)
    captcha_pending.pop((chat.id, uid), None)
    soft_mute_remove(chat.id, uid)
    try:
        await context.bot.restrict_chat_member(chat.id, uid, permissions=FULL_PERMS)
    except Exception as e:  # noqa: BLE001
        log.debug("captcha unmute: %s", e)
    try:
        await query.edit_message_text(tr(chat.id, "cap_ok"))
        if context.job_queue:
            context.job_queue.run_once(_delete_later, 8,
                                       data={"chat_id": chat.id, "mid": query.message.message_id})
    except Exception:  # noqa: BLE001
        pass
    await query.answer("✅")


def _join_seen(chat_id: int, uid: int) -> bool:
    """Вход приходит двумя путями (сервис-сообщение и chat_member) — дедупликация."""
    key = (chat_id, uid)
    now = time.time()
    if now - _join_handled.get(key, 0) < 120:
        return True
    _join_handled[key] = now
    return False


def add_dm_subscriber(chat_id: int, uid: int):
    lst = CONFIG.setdefault("dm_subscribers", {}).setdefault(str(chat_id), [])
    if uid not in lst:
        lst.append(uid)
        save_config()


async def _raid_tick(chat_id: int, cfg: dict, context) -> bool:
    """Учёт входа для анти-рейда. True — сейчас действует строгий режим."""
    a = cfg.get("antiraid", {}) or {}
    now = time.time()
    if a.get("enabled"):
        dq = _raid_joins.setdefault(chat_id, deque())
        dq.append(now)
        while dq and now - dq[0] > a.get("window", 60):
            dq.popleft()
        if len(dq) >= a.get("joins", 8) and now >= _raid_until.get(chat_id, 0):
            _raid_until[chat_id] = now + a.get("lock_min", 10) * 60
            title = CONFIG.get("groups", {}).get(str(chat_id), str(chat_id))
            await notify_staff(context, chat_id,
                               f"🚨 [{title}] Похоже на рейд: {len(dq)} входов за {a.get('window', 60)} сек. "
                               f"Новички будут отсеиваться {a.get('lock_min', 10)} мин.")
    return now < _raid_until.get(chat_id, 0)


async def handle_join(context, chat, user):
    """Единая обработка входа участника (из сервис-сообщения или chat_member)."""
    if user is None or getattr(user, "is_bot", False):
        return
    if not chat_allowed(chat.id):
        return
    remember_member(chat.id, user)
    if _join_seen(chat.id, user.id):
        return
    join_dates[(chat.id, user.id)] = time.time()
    cfg = chat_cfg(chat.id)

    if is_blacklisted(chat.id, user):
        return await _ban_quiet(context, chat.id, user.id)

    if cfg["enabled"].get("name_check") and _name_flagged(cfg, " ".join(filter(None, [
            getattr(user, "first_name", None), getattr(user, "last_name", None),
            getattr(user, "username", None)]))):
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            await context.bot.unban_chat_member(chat.id, user.id)  # кик за спам-имя
            bump(chat.id, "kicked")
            title = CONFIG.get("groups", {}).get(str(chat.id), str(chat.id))
            await notify_staff(context, chat.id, f"🥷 [{title}] кик при входе (спам-имя): {mention(user)} ({user.id})")
        except Exception as e:  # noqa: BLE001
            log.debug("name kick: %s", e)
        return

    if await _raid_tick(chat.id, cfg, context):
        try:
            await context.bot.ban_chat_member(chat.id, user.id)
            await context.bot.unban_chat_member(chat.id, user.id)
            bump(chat.id, "kicked")
        except Exception as e:  # noqa: BLE001
            log.debug("raid kick: %s", e)
        return

    if not await is_exempt(context, chat.id, user.id):
        if cfg["captcha"].get("enabled") and not cfg["captcha"].get("via_request", True):
            await start_captcha(context, chat, user)
    await send_welcome(context, chat, user)
    await announce_join_id(context, chat, user)


async def on_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    for u in msg.new_chat_members or []:
        if u.is_bot and context.bot and u.id == context.bot.id:
            continue  # свой вход обрабатывает on_my_member
        await handle_join(context, chat, u)


# ── заявки на вступление (капча в личке) ────────────────────────────────────


async def on_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    req = update.chat_join_request
    if not req:
        return
    chat, user = req.chat, req.from_user
    remember_group(chat)
    if not chat_allowed(chat.id):
        return
    cfg = chat_cfg(chat.id)
    name = " ".join(filter(None, [user.first_name, user.last_name, user.username]))
    if is_blacklisted(chat.id, user) or (cfg["enabled"].get("name_check") and _name_flagged(cfg, name)):
        try:
            await context.bot.decline_chat_join_request(chat.id, user.id)
        except Exception as e:  # noqa: BLE001
            log.debug("decline: %s", e)
        return
    if not (cfg["captcha"].get("enabled") and cfg["captcha"].get("via_request", True)):
        try:
            await context.bot.approve_chat_join_request(chat.id, user.id)
            remember_member(chat.id, user)
            add_dm_subscriber(chat.id, user.id)
        except Exception as e:  # noqa: BLE001
            log.debug("approve: %s", e)
        return
    join_requests[(chat.id, user.id)] = True
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(chat.id, "cap_btn"),
                                                     callback_data=f"jrok:{chat.id}:{user.id}")]])
    try:
        await context.bot.send_message(user.id, tr(chat.id, "cap_dm", chat=chat.title or "чат"),
                                       reply_markup=kb)
        if context.job_queue:
            context.job_queue.run_once(join_request_timeout, cfg["captcha"].get("timeout", 120),
                                       data={"chat_id": chat.id, "uid": user.id})
    except Exception as e:  # noqa: BLE001
        # ЛС закрыт — впускаем без капчи, иначе человек застрянет навсегда
        log.debug("join dm: %s", e)
        join_requests.pop((chat.id, user.id), None)
        try:
            await context.bot.approve_chat_join_request(chat.id, user.id)
            remember_member(chat.id, user)
        except Exception:  # noqa: BLE001
            pass


async def join_request_timeout(context):
    d = context.job.data
    if join_requests.pop((d["chat_id"], d["uid"]), None):
        try:
            await context.bot.decline_chat_join_request(d["chat_id"], d["uid"])
        except Exception as e:  # noqa: BLE001
            log.debug("jr timeout: %s", e)


async def handle_join_request_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        _, cid, uid = (query.data or "").split(":", 2)
        cid, uid = int(cid), int(uid)
    except ValueError:
        return await query.answer()
    if update.effective_user.id != uid:
        return await query.answer("Эта кнопка не для тебя 🙂", show_alert=True)
    join_requests.pop((cid, uid), None)
    title = CONFIG.get("groups", {}).get(str(cid), "чат")
    try:
        await context.bot.approve_chat_join_request(cid, uid)
        remember_member(cid, update.effective_user)
        add_dm_subscriber(cid, uid)
        await query.edit_message_text(tr(cid, "cap_ok_dm", chat=title))
    except Exception as e:  # noqa: BLE001
        await query.edit_message_text(f"Не вышло одобрить заявку: {e}")
    await query.answer("✅")


# ── сервисные события ───────────────────────────────────────────────────────


async def on_service_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not msg:
        return
    if chat_cfg(chat.id)["enabled"].get("clean_service"):
        try:
            await msg.delete()
        except Exception:  # noqa: BLE001
            pass


async def on_command_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or not msg:
        return
    if chat_cfg(chat.id)["enabled"].get("clean_commands") and context.job_queue:
        context.job_queue.run_once(_delete_later, 3, data={"chat_id": chat.id, "mid": msg.message_id})


async def on_my_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Бота добавили/удалили из группы."""
    cm = update.my_chat_member
    if not cm:
        return
    chat = cm.chat
    if chat.type not in ("group", "supergroup"):
        return
    new = cm.new_chat_member.status
    old = cm.old_chat_member.status
    if new in ("member", "administrator") and old in ("left", "kicked"):
        remember_group(chat)
        adder = cm.from_user
        who = mention(adder) if adder else "кто-то"
        if chat_allowed(chat.id):
            return
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Одобрить (бесплатно)", callback_data=f"appr:ok:{chat.id}"),
            InlineKeyboardButton("🚫 Нет", callback_data=f"appr:no:{chat.id}"),
        ]])
        await alert_owners(context,
                           f"➕ Бота добавили в «{chat.title}» (id {chat.id}), добавил: {who}.\n"
                           f"Группа пока без допуска — бот молчит. Одобрить или пусть оформляют тариф (/pro)?",
                           reply_markup=kb)
        try:
            await context.bot.send_message(
                chat.id,
                "👋 Привет! Я включусь в этой группе после одобрения владельцем бота "
                "или оформления тарифа — команда /pro. Выдайте мне права администратора "
                "(удаление сообщений, бан, приглашения).")
        except Exception:  # noqa: BLE001
            pass
    elif new in ("left", "kicked"):
        forget_group(chat.id)


async def on_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Изменения участников: входы (для капчи/приветствия) и анти-снос."""
    cm = update.chat_member
    if not cm:
        return
    chat = cm.chat
    if chat.type not in ("group", "supergroup"):
        return
    old, new = cm.old_chat_member, cm.new_chat_member
    # сброс кэша админов при изменении статусов админства
    if "administrator" in (old.status, new.status) or new.status == "creator":
        _admin_cache.pop(chat.id, None)
    if not chat_allowed(chat.id):
        return
    if new.status == "member" and old.status in ("left", "kicked"):
        await handle_join(context, chat, new.user)
        return
    # Анти-снос: массовые баны одним админом
    a = chat_cfg(chat.id).get("antinuke", {})
    if a.get("enabled") and new.status == "kicked" and cm.from_user \
            and cm.from_user.id != context.bot.id and not is_manager(cm.from_user.id):
        cnt = track_nuke(chat.id, cm.from_user.id)
        if cnt >= a.get("ban_threshold", 5):
            nuke_store.pop((chat.id, cm.from_user.id), None)
            title = CONFIG.get("groups", {}).get(str(chat.id), str(chat.id))
            actor = mention(cm.from_user)
            note = f"🚨 [{title}] АНТИ-СНОС: {actor} забанил {cnt}+ человек за {a.get('window', 30)} сек!"
            if a.get("action") == "ban":
                try:
                    await context.bot.ban_chat_member(chat.id, cm.from_user.id)
                    note += " Я забанил его."
                except Exception as e:  # noqa: BLE001
                    note += f" Забанить его не смог ({e}) — вмешайся вручную."
            else:  # stop: пробуем снять права
                try:
                    await context.bot.promote_chat_member(
                        chat.id, cm.from_user.id,
                        can_manage_chat=False, can_delete_messages=False, can_restrict_members=False,
                        can_promote_members=False, can_change_info=False, can_invite_users=False,
                        can_pin_messages=False, can_manage_video_chats=False)
                    note += " Я снял с него права (если мог)."
                except Exception as e:  # noqa: BLE001
                    note += f" Снять права не смог ({e}) — вмешайся вручную."
            await alert_staff(context, note)


async def on_chat_settings_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Смена названия группы — обновить справочник."""
    chat = update.effective_chat
    if chat:
        CONFIG["groups"][str(chat.id)] = chat.title or str(chat.id)
        save_config()

# ───────────────────────────────────────────────────────────────────────────
#  КОМАНДЫ МОДЕРАЦИИ
# ───────────────────────────────────────────────────────────────────────────


async def resolve_target(update: Update, context):
    """Цель команды: реплай, упоминание, @username (по памяти чата) или числовой ID."""
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, mention(u)
    for e in msg.entities or []:
        if e.type == "text_mention" and e.user:
            return e.user.id, mention(e.user)
    args = context.args or []
    if not args:
        return None, None
    tok = args[0]
    if re.fullmatch(r"-?\d{5,}", tok):
        uid = int(tok)
        names = CONFIG.get("msg_stats", {}).get(str(update.effective_chat.id), {}).get("names", {})
        return uid, names.get(str(uid), tok)
    if tok.startswith("@"):
        low = tok.lower()
        names = CONFIG.get("msg_stats", {}).get(str(update.effective_chat.id), {}).get("names", {})
        for uid, nm in names.items():
            if nm.lower() == low:
                return int(uid), nm
        await msg.reply_text(f"Не знаю {tok} — я запоминаю тех, кто писал в чате. "
                             "Ответь на его сообщение или укажи числовой ID.")
        return None, None
    return None, None


def extract_reason(update: Update, context) -> str:
    args = list(context.args or [])
    if not update.effective_message.reply_to_message and args:
        args = args[1:]
    return " ".join(args).strip()


async def _deny(update: Update):
    try:
        await update.effective_message.reply_text("Недостаточно прав для этой команды.")
    except Exception:  # noqa: BLE001
        pass
    return None


async def _guard(update: Update, context, key: str = "ban"):
    """Общая проверка команд наказания: права актора + защита цели.
    Владельца/менеджеров бота не трогает никто; админов группы — только владелец бота."""
    chat = update.effective_chat
    actor = update.effective_user
    if not await can_moderate(context, chat.id, actor.id, key, update=update):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        await update.effective_message.reply_text(
            "Укажи пользователя: ответь на его сообщение или добавь @user / числовой ID.")
        return None
    if is_manager(tid):
        await update.effective_message.reply_text("Это владелец/менеджер бота — действие не применяю.")
        return None
    if not is_manager(actor.id) and tid in await group_admin_ids(context, chat.id):
        await update.effective_message.reply_text(
            "Это администратор группы — через бота его наказывает только владелец бота.")
        return None
    return tid, tname


async def cmd_reload(update: Update, context):
    if not is_manager(update.effective_user.id):
        return await _deny(update)
    global CONFIG
    _flush_config()
    CONFIG = load_config()
    await update.effective_message.reply_text("♻️ Настройки перечитаны с диска.")


async def cmd_diag(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("Эта команда — для группы.")
    if not (is_manager(user.id) or await can_open_settings(context, chat.id, user.id)):
        return await _deny(update)
    cfg = chat_cfg(chat.id)
    rights = "?"
    try:
        me = await context.bot.get_chat_member(chat.id, context.bot.id)
        if me.status == "administrator":
            perms = []
            if getattr(me, "can_delete_messages", False):
                perms.append("удаление")
            if getattr(me, "can_restrict_members", False):
                perms.append("бан/мут")
            if getattr(me, "can_invite_users", False):
                perms.append("приглашения")
            if getattr(me, "can_pin_messages", False):
                perms.append("закреп")
            rights = "админ (" + (", ".join(perms) or "без ключевых прав!") + ")"
        else:
            rights = f"НЕ админ ({me.status}) — фильтры работать не будут!"
    except Exception as e:  # noqa: BLE001
        rights = f"не проверить: {e}"
    custom = "индивидуальные" if str(chat.id) in CONFIG.get("chats", {}) else "по шаблону"
    en = cfg["enabled"]
    on = [t for k, t in FEATURES if en.get(k)]
    lines = [
        f"🩺 Диагностика · {chat.title}",
        f"ID: {chat.id} · тип: {chat.type}",
        f"Доступ: {access_status(chat.id)}",
        f"Права бота: {rights}",
        f"Настройки: {custom}",
        f"Включено: {', '.join(on) or '— ничего —'}",
        f"Стоп-слов: {len(cfg.get('stop_words', []))} (+{len(CONFIG.get('global_stop_words', []))} глоб.) · "
        f"второй список: {len(cfg.get('stop_words2', []))} · исключений: {len(cfg.get('white_words', []))}",
        f"За спам: {_ACT_RU.get(cfg.get('spam_action', 'delete'))}",
        f"Автоответов: {len(cfg.get('triggers', {}))} · спам-доменов: {len(cfg.get('spam_links', []))}",
        f"Капча: {'вкл' if cfg['captcha'].get('enabled') else 'выкл'} · "
        f"ночной режим: {'вкл' if cfg['night'].get('enabled') else 'выкл'} · "
        f"анти-рейд: {'вкл' if cfg['antiraid'].get('enabled') else 'выкл'}",
    ]
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_ban(update: Update, context):
    g = await _guard(update, context, "ban")
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    duration, reason = _duration_and_reason(update, context)
    until = None if not duration else datetime.now(timezone.utc) + timedelta(seconds=duration)
    try:
        await context.bot.ban_chat_member(chat.id, tid, until_date=until)
        bump(chat.id, "banned")
        dur_txt = "навсегда" if not duration else f"на {human_duration(duration)}"
        await reply_tidy(update, context,
                         f"🚫 {tname} забанен {dur_txt}." + (f"\nПричина: {reason}" if reason else ""))
        await log_action(context, chat.id,
                         f"🚫 бан {dur_txt}: {tname} (by {_actor_name(update)})" + (f" — {reason}" if reason else ""))
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(
            f"Не вышло: {e}{_admin_api_hint(e)}\nПроверь, что я админ с правом банить.")


async def cmd_unban(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban", update=update):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Укажи ID или ответь на сообщение.")
    try:
        await context.bot.unban_chat_member(chat.id, tid, only_if_banned=True)
        await reply_tidy(update, context, f"✅ {tname} разбанен.")
        await log_action(context, chat.id, f"✅ разбан: {tname} (by {_actor_name(update)})")
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}")


async def cmd_kick(update: Update, context):
    g = await _guard(update, context, "ban")
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    try:
        await context.bot.ban_chat_member(chat.id, tid)
        await context.bot.unban_chat_member(chat.id, tid)
        bump(chat.id, "kicked")
        await reply_tidy(update, context, f"👢 {tname} исключён из чата.")
        await log_action(context, chat.id, f"👢 кик: {tname} (by {_actor_name(update)})")
    except Exception as e:  # noqa: BLE001
        await update.effective_message.reply_text(f"Не вышло: {e}{_admin_api_hint(e)}")


async def cmd_mute(update: Update, context):
    g = await _guard(update, context, "mute")
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    duration, reason = _duration_and_reason(update, context)
    duration = duration or 3600
    await mute_user(context, chat.id, tid, duration)
    bump(chat.id, "muted")
    soft = " (мягкий — просто удаляю его сообщения)" if is_soft_muted(chat.id, tid) else ""
    await reply_tidy(update, context,
                     f"🔇 {tname} в муте на {human_duration(duration)}{soft}." +
                     (f"\nПричина: {reason}" if reason else ""))
    await log_action(context, chat.id,
                     f"🔇 мут {human_duration(duration)}: {tname} (by {_actor_name(update)})" +
                     (f" — {reason}" if reason else ""))


async def cmd_unmute(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "mute", update=update):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Укажи ID или ответь на сообщение.")
    soft_mute_remove(chat.id, tid)
    try:
        await context.bot.restrict_chat_member(chat.id, tid, permissions=FULL_PERMS)
    except Exception as e:  # noqa: BLE001
        log.debug("unmute: %s", e)
    await reply_tidy(update, context, f"🔊 {tname} размучен.")
    await log_action(context, chat.id, f"🔊 размут: {tname} (by {_actor_name(update)})")


async def cmd_warn(update: Update, context):
    g = await _guard(update, context, "warn")
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    reason = extract_reason(update, context)
    note = await apply_warn(context, chat.id, tid, tname, reason)
    await reply_tidy(update, context, note)
    await log_action(context, chat.id, f"{note} (by {_actor_name(update)})")


async def cmd_unwarn(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "warn", update=update):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Укажи ID или ответь на сообщение.")
    n = dec_warn(chat.id, tid)
    await reply_tidy(update, context, f"➖ {tname}: снято одно предупреждение, осталось {n}.")


async def cmd_warns(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "warn", update=update):
        return await _deny(update)
    w = CONFIG["warns"].get(str(chat.id), {})
    if not w:
        return await reply_tidy(update, context, "Предупреждений нет — все молодцы. ✨")
    names = CONFIG.get("msg_stats", {}).get(str(chat.id), {}).get("names", {})
    limit = chat_cfg(chat.id)["moderation"]["warn_limit"]
    lines = [f"⚠️ Предупреждения (лимит {limit}):"]
    for uid, n in sorted(w.items(), key=lambda kv: kv[1], reverse=True)[:30]:
        lines.append(f"• {names.get(uid, uid)} — {n}/{limit}")
    await reply_tidy(update, context, "\n".join(lines), seconds=20)


# ── роли ────────────────────────────────────────────────────────────────────


async def cmd_role(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if not (is_manager(user.id) or await can_open_settings(context, chat.id, user.id)):
        return await _deny(update)
    roles = chat_roles(chat.id)
    if not context.args:
        return await update.effective_message.reply_text(
            "Роли этой группы: " + (", ".join(roles) or "— нет —") +
            "\nВыдать: /role <имя_роли> (ответом на сообщение или с ID). Создать роль — в панели.")
    rname = context.args[0]
    if rname not in roles:
        return await update.effective_message.reply_text(f"Роли «{rname}» нет. Создай её в панели → 🎖 Роли.")
    context.args = context.args[1:]
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Кому выдать? Ответь на сообщение или укажи ID.")
    cfg = chat_cfg_writable(chat.id)
    r = cfg.setdefault("roles", {}).setdefault(rname, {"perms": [], "members": []})
    if tid not in r["members"]:
        r["members"].append(tid)
        save_config()
    await reply_tidy(update, context, f"🎖 {tname} теперь в роли «{rname}».")


async def cmd_unrole(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if not (is_manager(user.id) or await can_open_settings(context, chat.id, user.id)):
        return await _deny(update)
    if not context.args:
        return await update.effective_message.reply_text("Формат: /unrole <имя_роли> (ответом или с ID).")
    rname = context.args[0]
    context.args = context.args[1:]
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("У кого забрать? Ответь на сообщение или укажи ID.")
    cfg = chat_cfg_writable(chat.id)
    r = cfg.setdefault("roles", {}).get(rname)
    if r and tid in r.get("members", []):
        r["members"].remove(tid)
        save_config()
        return await reply_tidy(update, context, f"🎖 {tname} убран из роли «{rname}».")
    await update.effective_message.reply_text("Он и так не в этой роли.")


async def cmd_setstaff(update: Update, context):
    """Выполняется В БУДУЩЕЙ staff-группе: привязывает её к одной из твоих групп."""
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("Выполни эту команду в группе, которая станет служебной.")
    groups = await user_admin_groups(context, user.id)
    groups = [(cid, t) for cid, t in groups if int(cid) != chat.id]
    if not groups:
        return await _deny(update)
    rows = [[InlineKeyboardButton(t[:40], callback_data=f"ss:{cid}")] for cid, t in groups[:25]]
    await update.effective_message.reply_text(
        "Для какой группы этот чат станет служебным (сюда пойдут уведомления и журнал)?",
        reply_markup=InlineKeyboardMarkup(rows))


async def handle_setstaff_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    user = update.effective_user
    try:
        cid = int((query.data or "ss:0").split(":", 1)[1])
    except ValueError:
        return await query.answer()
    if not await can_edit_target(context, user.id, cid):
        return await query.answer("Ты не управляешь той группой", show_alert=True)
    chat_cfg_writable(cid)["staff_group"] = chat.id
    save_config(force=True)
    title = CONFIG.get("groups", {}).get(str(cid), str(cid))
    await query.edit_message_text(f"✅ Этот чат теперь служебный для «{title}»: сюда пойдут уведомления и журнал.")
    await query.answer("Готово")


# ── /info и кнопки действий ─────────────────────────────────────────────────

STATUS_RU = {"creator": "создатель", "administrator": "админ", "member": "участник",
             "restricted": "ограничен", "left": "вышел", "kicked": "забанен"}


def info_action_kb(chat_id: int, uid: int) -> InlineKeyboardMarkup:
    rows = [[
        InlineKeyboardButton("⚠️ Пред", callback_data=f"act:warn:{uid}"),
        InlineKeyboardButton("🔇 Мут 1ч", callback_data=f"act:mute:{uid}"),
    ], [
        InlineKeyboardButton("🔊 Размут", callback_data=f"act:unmute:{uid}"),
        InlineKeyboardButton("🚫 Бан", callback_data=f"act:ban:{uid}"),
    ]]
    if chat_roles(chat_id):
        rows.append([InlineKeyboardButton("🎖 Роли", callback_data=f"arole:menu:{uid}")])
    return InlineKeyboardMarkup(rows)


def info_roles_kb(chat_id: int, uid: int) -> InlineKeyboardMarkup:
    rows = []
    for name in sorted(chat_roles(chat_id)):
        on = uid in (chat_roles(chat_id).get(name) or {}).get("members", [])
        rows.append([InlineKeyboardButton(f"{'✅' if on else '▫️'} {name}",
                                          callback_data=f"arole:t:{name}:{uid}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=f"arole:back:{uid}")])
    return InlineKeyboardMarkup(rows)


async def cmd_info(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("Эта команда — для группы.")
    if not await can_moderate(context, chat.id, user.id, "warn", update=update):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Ответь на сообщение или укажи @user / ID.")
    status = "?"
    try:
        m = await context.bot.get_chat_member(chat.id, tid)
        status = STATUS_RU.get(m.status, m.status)
        tname = mention(m.user)
    except Exception:  # noqa: BLE001
        pass
    limit = chat_cfg(chat.id)["moderation"]["warn_limit"]
    jd = join_dates.get((chat.id, tid))
    jd_txt = datetime.fromtimestamp(jd).strftime("%d.%m.%Y %H:%M") if jd else "— не видел —"
    rl = ", ".join(user_roles(chat.id, tid)) or "—"
    msgs = CONFIG.get("msg_stats", {}).get(str(chat.id), {}).get("users", {}).get(str(tid), 0)
    text = (f"👤 {tname}\n"
            f"ID: {tid}\n"
            f"Статус: {status}\n"
            f"Предупреждений: {get_warn(chat.id, tid)}/{limit}\n"
            f"Сообщений (учтено): {msgs}\n"
            f"Вход: {jd_txt}\n"
            f"Роли: {rl}")
    await update.effective_message.reply_text(text, reply_markup=info_action_kb(chat.id, tid))


async def handle_action_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    presser = update.effective_user
    data = query.data or ""
    parts = data.split(":")
    # ── переключение ролей из карточки ──
    if data.startswith("arole:"):
        if len(parts) < 3:
            return await query.answer()
        sub = parts[1]
        uid = int(parts[-1])
        if not (is_manager(presser.id) or await can_open_settings(context, chat.id, presser.id)):
            return await query.answer("Нет прав", show_alert=True)
        if sub == "menu":
            try:
                await query.edit_message_reply_markup(info_roles_kb(chat.id, uid))
            except Exception:  # noqa: BLE001
                pass
            return await query.answer()
        if sub == "back":
            try:
                await query.edit_message_reply_markup(info_action_kb(chat.id, uid))
            except Exception:  # noqa: BLE001
                pass
            return await query.answer()
        if sub == "t":
            rname = ":".join(parts[2:-1])
            cfg = chat_cfg_writable(chat.id)
            r = cfg.setdefault("roles", {}).setdefault(rname, {"perms": [], "members": []})
            if uid in r["members"]:
                r["members"].remove(uid)
            else:
                r["members"].append(uid)
            save_config()
            try:
                await query.edit_message_reply_markup(info_roles_kb(chat.id, uid))
            except Exception:  # noqa: BLE001
                pass
            return await query.answer("Сохранено")
        return await query.answer()
    # ── действия наказания ──
    if len(parts) < 3:
        return await query.answer()
    action, tid = parts[1], int(parts[2])
    key = {"warn": "warn", "mute": "mute", "unmute": "mute", "ban": "ban"}.get(action, "ban")
    if not await can_moderate(context, chat.id, presser.id, key):
        return await query.answer("Нет прав", show_alert=True)
    if is_manager(tid):
        return await query.answer("Это владелец/менеджер бота — не трогаю", show_alert=True)
    if action in ("ban", "mute") and not is_manager(presser.id) \
            and tid in await group_admin_ids(context, chat.id):
        return await query.answer("Админов через бота трогает только владелец бота", show_alert=True)
    try:
        if action == "warn":
            note = await apply_warn(context, chat.id, tid, "участник")
        elif action == "mute":
            await mute_user(context, chat.id, tid, 3600)
            bump(chat.id, "muted")
            note = "🔇 мут на 1 час"
        elif action == "unmute":
            soft_mute_remove(chat.id, tid)
            await context.bot.restrict_chat_member(chat.id, tid, permissions=FULL_PERMS)
            note = "🔊 размучен"
        elif action == "ban":
            await context.bot.ban_chat_member(chat.id, tid)
            bump(chat.id, "banned")
            note = "🚫 забанен"
        else:
            return await query.answer()
    except Exception as e:  # noqa: BLE001
        return await query.answer(f"Не вышло: {e}"[:190], show_alert=True)
    await log_action(context, chat.id, f"{note} (id {tid}, by {mention(presser)})")
    try:
        base = (query.message.text or "").split("\n➡️")[0]
        await query.edit_message_text(base + f"\n➡️ {note} (— {mention(presser)})",
                                      reply_markup=info_action_kb(chat.id, tid))
    except Exception:  # noqa: BLE001
        pass
    await query.answer(note[:190])

# ───────────────────────────────────────────────────────────────────────────
#  СТАТИСТИКА, ПРИВЛЕЧЕНИЕ, ПРОЧИЕ КОМАНДЫ ГРУППЫ
# ───────────────────────────────────────────────────────────────────────────


async def cmd_stats(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "warn", update=update):
        return await _deny(update)
    ms = _stats_chat(chat.id)
    s = ms.get("mod", {})
    active = sum(1 for c in ms.get("users", {}).values() if c > 0)
    total, today, week, _top = _msg_stats_summary(chat.id)
    warned_now = len(CONFIG["warns"].get(str(chat.id), {}))
    lines = [
        f"📊 Статистика · {chat.title}",
        f"Сообщений: всего {total} · сегодня {today} · за неделю {week}",
        f"Активных участников (писали): {active}",
        "",
        "🛡 Модерация (за всё время):",
        f"• удалено сообщений: {s.get('deleted', 0)}",
        f"• предупреждений: {s.get('warns', 0)} (сейчас с предами: {warned_now})",
        f"• мутов: {s.get('muted', 0)} · за флуд: {s.get('flood_muted', 0)}",
        f"• банов: {s.get('banned', 0)} · киков: {s.get('kicked', 0)}",
        "",
        "Подробный топ активности — /top",
    ]
    await reply_tidy(update, context, "\n".join(lines), seconds=25)


async def cmd_top(update: Update, context):
    chat = update.effective_chat
    total, today, week, top = _msg_stats_summary(chat.id)
    if not top:
        return await reply_tidy(update, context, "Пока нечего показать — я ещё не насчитал сообщений.")
    lines = [f"🏆 Топ активности · {chat.title} (всего {total}):"]
    medals = ["🥇", "🥈", "🥉"]
    for i, (name, cnt) in enumerate(top):
        lines.append(f"{medals[i] if i < 3 else f'{i + 1}.'} {name} — {cnt}")
    await reply_tidy(update, context, "\n".join(lines), seconds=30)


async def ensure_invite_link(context, chat_id: int):
    link = CONFIG.get("invite_links", {}).get(str(chat_id))
    if link:
        return link
    try:
        link = await context.bot.export_chat_invite_link(chat_id)
    except Exception:  # noqa: BLE001
        try:
            inv = await context.bot.create_chat_invite_link(chat_id)
            link = inv.invite_link
        except Exception as e:  # noqa: BLE001
            log.debug("invite link %s: %s", chat_id, e)
            return None
    CONFIG.setdefault("invite_links", {})[str(chat_id)] = link
    save_config()
    return link


async def cmd_invite(update: Update, context):
    chat = update.effective_chat
    link = await ensure_invite_link(context, chat.id)
    if not link:
        return await update.effective_message.reply_text(
            "Не смог получить ссылку — дай мне право «Приглашение по ссылке».")
    await reply_tidy(update, context, f"🔗 Ссылка-приглашение:\n{link}", seconds=60)


cmd_link = cmd_invite  # /link — то же самое


async def cmd_zazyvala(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "all", update=update):
        return await _deny(update)
    link = await ensure_invite_link(context, chat.id)
    if not link:
        return await update.effective_message.reply_text(
            "Сначала дай мне право «Приглашение по ссылке».")
    text = _args_text(update) or chat_cfg(chat.id).get("invite_text") or CONFIG.get("invite_text")
    share = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📨 Пригласить друга", url=share)]])
    try:
        await update.effective_message.delete()
    except Exception:  # noqa: BLE001
        pass
    await context.bot.send_message(chat.id, text, reply_markup=kb)


def _optout_list(chat_id) -> list:
    return CONFIG.setdefault("all_optout", {}).setdefault(str(chat_id), [])


async def cmd_all(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if not await can_moderate(context, chat.id, user.id, "all", update=update):
        return await _deny(update)
    if _all_active.get(chat.id):
        return await update.effective_message.reply_text("Призыв уже идёт — останови его кнопкой или /stopall.")
    text = _args_text(update) or "Все сюда! 👀"
    ms = CONFIG.get("msg_stats", {}).get(str(chat.id), {})
    users = ms.get("users", {})
    names = ms.get("names", {})
    optout = set(_optout_list(chat.id))
    targets = [(int(uid), names.get(uid) or "друг")
               for uid, _cnt in sorted(users.items(), key=lambda kv: kv[1], reverse=True)
               if uid.lstrip("-").isdigit() and int(uid) not in optout and int(uid) != user.id]
    if not targets:
        return await update.effective_message.reply_text(
            "Пока некого звать — я отмечаю тех, кто писал в чате или недавно вступил.")
    targets = targets[:100]
    try:
        await update.effective_message.delete()
    except Exception:  # noqa: BLE001
        pass
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏹ Стоп", callback_data="allstop")]])
    head = await context.bot.send_message(
        chat.id, f"📣 {text}\n\nЗову участников: 0/{len(targets)}…", reply_markup=kb)
    _all_active[chat.id] = True
    done = 0
    try:
        for i in range(0, len(targets), 5):
            if not _all_active.get(chat.id):
                break
            batch = targets[i:i + 5]
            links = ", ".join(f'<a href="tg://user?id={uid}">{html.escape(nm)}</a>' for uid, nm in batch)
            try:
                await context.bot.send_message(chat.id, f"👋 {links}", parse_mode="HTML",
                                               disable_notification=False)
                done += len(batch)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
            except Exception as e:  # noqa: BLE001
                log.debug("all batch: %s", e)
            try:
                await head.edit_text(f"📣 {text}\n\nЗову участников: {done}/{len(targets)}…", reply_markup=kb)
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(2)
    finally:
        _all_active[chat.id] = False
    try:
        await head.edit_text(f"📣 {text}\n\n✅ Позвал: {done} из {len(targets)}. "
                             "Отписаться от призывов — /anreg.")
    except Exception:  # noqa: BLE001
        pass


async def cmd_stopall(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "all", update=update):
        return await _deny(update)
    if _all_active.get(chat.id):
        _all_active[chat.id] = False
        return await reply_tidy(update, context, "⏹ Призыв остановлен.")
    await reply_tidy(update, context, "Призыв сейчас не идёт.")


async def cmd_anreg(update: Update, context):
    chat = update.effective_chat
    uid = update.effective_user.id
    lst = _optout_list(chat.id)
    if uid not in lst:
        lst.append(uid)
        save_config()
    await reply_tidy(update, context, "🔕 Больше не буду упоминать тебя в призывах /all. Вернуться — /reg.")


async def cmd_reg(update: Update, context):
    chat = update.effective_chat
    uid = update.effective_user.id
    lst = _optout_list(chat.id)
    if uid in lst:
        lst.remove(uid)
        save_config()
    remember_member(chat.id, update.effective_user)
    await reply_tidy(update, context, "🔔 Снова буду звать тебя в /all.")


async def cmd_say(update: Update, context):
    if not is_manager(update.effective_user.id):
        return await _deny(update)
    text = _args_text(update)
    if not text:
        return await update.effective_message.reply_text("Формат: /say текст объявления")
    try:
        await update.effective_message.delete()
    except Exception:  # noqa: BLE001
        pass
    await context.bot.send_message(update.effective_chat.id, _spintax(text))


async def cmd_rules(update: Update, context):
    rules = chat_cfg(update.effective_chat.id).get("rules") or "Правила не заданы."
    await reply_tidy(update, context, f"📜 {rules}", seconds=60)


async def cmd_setrules(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type in ("group", "supergroup"):
        if not (is_manager(user.id) or await can_open_settings(context, chat.id, user.id)):
            return await _deny(update)
        text = _args_text(update)
        if not text:
            return await update.effective_message.reply_text("Формат: /setrules текст правил")
        chat_cfg_writable(chat.id)["rules"] = text
        save_config()
        return await reply_tidy(update, context, "📜 Правила обновлены. Посмотреть — /rules.")
    await update.effective_message.reply_text("Выполни /setrules в самой группе (или задай правила в панели).")


async def cmd_purge(update: Update, context):
    chat = update.effective_chat
    msg = update.effective_message
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban", update=update):
        return await _deny(update)
    if not msg.reply_to_message:
        return await msg.reply_text("Ответь командой /purge на сообщение, С КОТОРОГО чистить.")
    start = msg.reply_to_message.message_id
    end = msg.message_id
    if end - start > 300:
        start = end - 300
    deleted = 0
    for mid in range(start, end + 1):
        try:
            await context.bot.delete_message(chat.id, mid)
            deleted += 1
        except Exception:  # noqa: BLE001
            pass
    bump(chat.id, "deleted", deleted)
    await ephemeral(context, chat.id, f"🧹 Удалено сообщений: {deleted}.", 6)
    await log_action(context, chat.id, f"🧹 purge {deleted} (by {_actor_name(update)})")


async def cmd_report(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    msg = update.effective_message
    if chat.type not in ("group", "supergroup"):
        return
    if not _throttle(("report", chat.id, user.id), 120):
        return await _drop(msg, chat.id)
    target = msg.reply_to_message
    link = ""
    if str(chat.id).startswith("-100") and target:
        link = f"\nСообщение: https://t.me/c/{str(chat.id)[4:]}/{target.message_id}"
    about = f" на {mention(target.from_user)}" if target and target.from_user else ""
    reason = _args_text(update)
    title = CONFIG.get("groups", {}).get(str(chat.id), str(chat.id))
    await notify_staff(context, chat.id,
                       f"🚨 [{title}] Жалоба от {mention(user)}{about}."
                       + (f"\nПричина: {reason}" if reason else "") + link)
    try:
        await msg.delete()
    except Exception:  # noqa: BLE001
        pass
    await ephemeral(context, chat.id, "🚨 Жалоба отправлена модераторам. Спасибо!", 6)


async def cmd_me(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        return
    limit = chat_cfg(chat.id)["moderation"]["warn_limit"]
    msgs = CONFIG.get("msg_stats", {}).get(str(chat.id), {}).get("users", {}).get(str(user.id), 0)
    rl = ", ".join(user_roles(chat.id, user.id)) or "—"
    silent = "🔕 отписан от /all" if user.id in _optout_list(chat.id) else "🔔 в списке /all"
    await reply_tidy(update, context,
                     f"👤 {mention(user)}\n"
                     f"Предупреждений: {get_warn(chat.id, user.id)}/{limit}\n"
                     f"Сообщений (учтено): {msgs}\nРоли: {rl}\n{silent}", seconds=20)


async def cmd_appeal(update: Update, context):
    user = update.effective_user
    text = _args_text(update)
    if not text:
        return await update.effective_message.reply_text(
            "Напиши так: /appeal твоё сообщение — я передам его владельцам бота.")
    now = time.time()
    if now - _appeal_cd.get(user.id, 0) < 3600:
        return await update.effective_message.reply_text("Апелляцию можно отправлять раз в час.")
    _appeal_cd[user.id] = now
    await alert_owners(context, f"📮 Апелляция от {mention(user)} (id {user.id}):\n{text}")
    await update.effective_message.reply_text("📮 Передал владельцам. Ответ придёт сюда, если решат ответить.")


async def cmd_gblock(update: Update, context):
    if not is_manager(update.effective_user.id):
        return await _deny(update)
    arg = _args_text(update)
    tid, tname = await resolve_target(update, context)
    gb = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
    if tid:
        if is_manager(tid):
            return await update.effective_message.reply_text("Это владелец/менеджер бота.")
        if tid not in gb["ids"]:
            gb["ids"].append(tid)
            save_config(force=True)
        return await update.effective_message.reply_text(
            f"🌐 {tname} в ГЛОБАЛЬНОМ чёрном списке — бан во всех группах при первом сообщении.")
    if arg:
        if arg.lower() not in gb["names"]:
            gb["names"].append(arg.lower())
            save_config(force=True)
        return await update.effective_message.reply_text(
            f"🌐 Подстрока имени «{arg}» в глобальном ЧС.")
    await update.effective_message.reply_text("Формат: /gblock (реплай | ID | подстрока имени)")


async def cmd_gunblock(update: Update, context):
    if not is_manager(update.effective_user.id):
        return await _deny(update)
    arg = _args_text(update)
    gb = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
    if re.fullmatch(r"-?\d{5,}", arg or ""):
        uid = int(arg)
        if uid in gb["ids"]:
            gb["ids"].remove(uid)
            save_config(force=True)
            return await update.effective_message.reply_text("Убрал из глобального ЧС.")
    if arg and arg.lower() in gb["names"]:
        gb["names"].remove(arg.lower())
        save_config(force=True)
        return await update.effective_message.reply_text("Убрал подстроку из глобального ЧС.")
    await update.effective_message.reply_text("Не нашёл такого в глобальном ЧС. Формат: /gunblock ID | подстрока")

# ───────────────────────────────────────────────────────────────────────────
#  ДОСТАВКА ПОСТОВ (единый отправщик)
# ───────────────────────────────────────────────────────────────────────────

_SPINTAX_RE = re.compile(r"\{([^{}|]*(?:\|[^{}|]*)+)\}")


def _spintax(text: str) -> str:
    """Рандомизация {вариант1|вариант2|вариант3} — в т.ч. вложенные проходы."""
    if not text:
        return text
    for _ in range(10):
        m = _SPINTAX_RE.search(text)
        if not m:
            break
        text = text[:m.start()] + random.choice(m.group(1).split("|")) + text[m.end():]
    return text


def _post_tz():
    try:
        return timezone(timedelta(hours=int(CONFIG.get("post_tz", 0))))
    except Exception:  # noqa: BLE001
        return timezone.utc


def _one_button(label: str, url: str):
    return {"text": (label or "Открыть")[:40], "url": url}


def _parse_button_rows(text: str):
    """«Текст - https://ссылка» по строке; несколько кнопок в ряд — через «;».
    Возвращает список рядов: [[{text,url},…],…]"""
    rows = []
    for line in (text or "").splitlines():
        row = []
        for item in line.split(";"):
            item = item.strip()
            if not item:
                continue
            for sep in (" — ", " - ", " -", "- ", "—", "-"):
                if sep in item:
                    label, url = item.split(sep, 1)
                    break
            else:
                label, url = "Открыть", item
            url = url.strip()
            if url.startswith("@"):
                url = "https://t.me/" + url[1:]
            if not re.match(r"^(https?://|t\.me/|tg://)", url):
                continue
            if url.startswith("t.me/"):
                url = "https://" + url
            row.append(_one_button(label.strip(), url))
        if row:
            rows.append(row)
    return rows


def _post_buttons_markup(buttons):
    """Понимает и новый формат (ряды), и старый плоский список кнопок."""
    if not buttons:
        return None
    rows = []
    for item in buttons:
        if isinstance(item, list):
            row = [InlineKeyboardButton(b.get("text", "Открыть"), url=b.get("url"))
                   for b in item if isinstance(b, dict) and b.get("url")]
            if row:
                rows.append(row)
        elif isinstance(item, dict) and item.get("url"):
            rows.append([InlineKeyboardButton(item.get("text", "Открыть"), url=item["url"])])
    return InlineKeyboardMarkup(rows) if rows else None


_NO_CAPTION_TYPES = {"sticker", "video_note"}
_POST_TYPE_RU = {"text": "текст", "photo": "фото", "video": "видео", "animation": "гиф",
                 "sticker": "стикер", "document": "файл", "audio": "аудио",
                 "voice": "войс", "video_note": "кружок"}
_TAG_RE = re.compile(r"<[^>]+>")


def _trig_preview(v, maxlen: int = 18) -> str:
    """Короткое превью автоответа: строка или объект контента."""
    if isinstance(v, dict):
        body = _TAG_RE.sub("", v.get("text") or "").strip()
        nb = len(v.get("buttons") or [])
        s = f"[{_POST_TYPE_RU.get(v.get('type'), 'медиа')}{' +🔘' if nb else ''}] {body}".strip()
    else:
        s = str(v)
    return (s[:maxlen] + "…") if len(s) > maxlen else s


def _capture_post_content(message):
    """Из сообщения в ЛС — объект контента поста/автоответа (с HTML-форматированием)."""
    if message.text:
        return {"type": "text", "text": message.text_html or message.text, "html": True}
    cap = message.caption_html if message.caption else None
    base = {"text": cap or "", "html": bool(cap)}
    if message.photo:
        return dict(base, type="photo", file_id=message.photo[-1].file_id)
    if message.video:
        return dict(base, type="video", file_id=message.video.file_id)
    if message.animation:
        return dict(base, type="animation", file_id=message.animation.file_id)
    if message.sticker:
        return {"type": "sticker", "file_id": message.sticker.file_id, "text": "", "html": False}
    if message.video_note:
        return {"type": "video_note", "file_id": message.video_note.file_id, "text": "", "html": False}
    if message.voice:
        return dict(base, type="voice", file_id=message.voice.file_id)
    if message.audio:
        return dict(base, type="audio", file_id=message.audio.file_id)
    if message.document:
        return dict(base, type="document", file_id=message.document.file_id)
    return None


async def _send_one(context, cid, post, reply_to=None):
    """Отправка одного «поста» (текст/медиа + кнопки + пин) в один чат."""
    t = post.get("type", "text")
    text = _spintax(post.get("text") or "")
    fid = post.get("file_id")
    markup = None if t in _NO_CAPTION_TYPES else _post_buttons_markup(post.get("buttons"))
    cap = None if t in _NO_CAPTION_TYPES else (text or None)
    pm = "HTML" if post.get("html") else None
    b = context.bot
    kw = {"disable_notification": bool(post.get("silent"))}
    if reply_to:
        kw.update(reply_to_message_id=reply_to, allow_sending_without_reply=True)
    if t == "text":
        m = await b.send_message(int(cid), text or "‎", reply_markup=markup, parse_mode=pm,
                                 disable_web_page_preview=bool(post.get("no_preview")), **kw)
    elif t == "photo":
        m = await b.send_photo(int(cid), fid, caption=cap, reply_markup=markup, parse_mode=pm, **kw)
    elif t == "video":
        m = await b.send_video(int(cid), fid, caption=cap, reply_markup=markup, parse_mode=pm, **kw)
    elif t == "animation":
        m = await b.send_animation(int(cid), fid, caption=cap, reply_markup=markup, parse_mode=pm, **kw)
    elif t == "document":
        m = await b.send_document(int(cid), fid, caption=cap, reply_markup=markup, parse_mode=pm, **kw)
    elif t == "audio":
        m = await b.send_audio(int(cid), fid, caption=cap, reply_markup=markup, parse_mode=pm, **kw)
    elif t == "voice":
        m = await b.send_voice(int(cid), fid, caption=cap, reply_markup=markup, parse_mode=pm, **kw)
    elif t == "sticker":
        m = await b.send_sticker(int(cid), fid, **kw)
    elif t == "video_note":
        m = await b.send_video_note(int(cid), fid, **kw)
    else:
        m = await b.send_message(int(cid), text or "‎", reply_markup=markup, parse_mode=pm, **kw)
    if post.get("pin"):
        try:
            await b.pin_chat_message(int(cid), m.message_id, disable_notification=True)
        except Exception as e:  # noqa: BLE001
            log.debug("pin: %s", e)
    return m


async def deliver(context, cid, post, reply_to=None) -> bool:
    """ЕДИНСТВЕННАЯ точка доставки в группу (промо, посты, рассылки, публикации).
    False — доступа нет; при «нас выгнали» группа забывается."""
    try:
        await _send_one(context, int(cid), post, reply_to=reply_to)
        return True
    except Forbidden:
        forget_group(int(cid))
    except BadRequest as e:
        low = str(e).lower()
        if any(s in low for s in ("chat not found", "chat_id is empty", "group chat was upgraded")):
            forget_group(int(cid))
        else:
            log.debug("deliver %s: %s", cid, e)
    except Exception as e:  # noqa: BLE001
        log.debug("deliver %s: %s", cid, e)
    return False


async def _broadcast(context, text=None, photo_id=None, pin=False):
    """Рассылка по всем известным группам."""
    ok = fail = 0
    post = {"type": "photo" if photo_id else "text", "text": text or "",
            "file_id": photo_id, "pin": pin}
    for cid in list(CONFIG["groups"].keys()):
        if await deliver(context, cid, post):
            ok += 1
        else:
            fail += 1
        await asyncio.sleep(0.1)
    return ok, fail


async def _dm_broadcast(context, chat_ids, post):
    """Рассылка в ЛС подписчикам выбранных групп (кто прошёл капчу-заявку)."""
    sent = fail = 0
    seen = set()
    subs = CONFIG.setdefault("dm_subscribers", {})
    for cid in chat_ids:
        for uid in list(subs.get(str(cid), [])):
            if uid in seen:
                continue
            seen.add(uid)
            try:
                await _send_one(context, uid, post)
                sent += 1
            except Forbidden:
                try:
                    subs[str(cid)].remove(uid)
                    save_config()
                except ValueError:
                    pass
                fail += 1
            except Exception as e:  # noqa: BLE001
                log.debug("dm %s: %s", uid, e)
                fail += 1
            await asyncio.sleep(0.08)
    return sent, fail

# ───────────────────────────────────────────────────────────────────────────
#  ПОСТЫ ПО РАСПИСАНИЮ
# ───────────────────────────────────────────────────────────────────────────

_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def _new_post_id() -> str:
    return f"p{int(time.time() * 1000) % 10_000_000}"


def _find_post(pid: str):
    for p in CONFIG.get("scheduled_posts", []):
        if p.get("id") == pid:
            return p
    return None


def _post_chat_ids(post) -> list:
    ch = post.get("chats", "all")
    if ch == "all":
        return list(CONFIG.get("groups", {}).keys())
    return [str(c) for c in ch]


def _post_groups_label(post) -> str:
    ch = post.get("chats", "all")
    if ch == "all":
        return "все группы"
    names = [CONFIG.get("groups", {}).get(str(c), str(c)) for c in ch]
    s = ", ".join(names[:3])
    return s + (f" +{len(names) - 3}" if len(names) > 3 else "")


def _post_due(post, now) -> bool:
    if not post.get("enabled", True):
        return False
    if post.get("time") != now.strftime("%H:%M"):
        return False
    days = post.get("days") or []
    return (not days) or (now.weekday() in days)


async def _send_scheduled_post(context, post):
    n = 0
    for cid in _post_chat_ids(post):
        if await deliver(context, cid, post):
            n += 1
        await asyncio.sleep(0.1)
    log.info("Пост %s отправлен в %s групп", post.get("id"), n)

# ───────────────────────────────────────────────────────────────────────────
#  ТАРИФ «ПРОФЕССИОНАЛЬНЫЙ» (оплата звёздами) И ПРОБНЫЙ ПЕРИОД
# ───────────────────────────────────────────────────────────────────────────

PRO_PLANS = {
    "1m": {"stars": 225, "days": 30, "title": "1 месяц"},
    "3m": {"stars": 651, "days": 90, "title": "3 месяца (-3%)"},
    "6m": {"stars": 1254, "days": 180, "title": "6 месяцев (-7%)"},
    "1y": {"stars": 2304, "days": 365, "title": "1 год (-15%)"},
}


def pro_until(chat_id) -> float:
    return float(CONFIG.get("subscriptions", {}).get(str(chat_id), 0) or 0)


def is_pro(chat_id) -> bool:
    return pro_until(chat_id) > time.time()


def extend_pro(chat_id, days: int):
    base = max(time.time(), pro_until(chat_id))
    CONFIG.setdefault("subscriptions", {})[str(chat_id)] = base + days * 86400
    _expiry_notified.discard(str(chat_id))
    save_config(force=True)


def trial_until(chat_id) -> float:
    return float(CONFIG.get("trials", {}).get(str(chat_id), 0) or 0)


def trial_active(chat_id) -> bool:
    return trial_until(chat_id) > time.time()


def grant_trial(chat_id, days=None):
    days = days or CONFIG.get("trial_days", 3)
    CONFIG.setdefault("trials", {})[str(chat_id)] = time.time() + days * 86400
    _expiry_notified.discard(str(chat_id))
    save_config(force=True)


def access_status(chat_id) -> str:
    if chat_id in CONFIG.get("approved_chats", []):
        return "✅ одобрено владельцем (бессрочно)"
    if is_pro(chat_id):
        return "⭐ тариф до " + datetime.fromtimestamp(pro_until(chat_id)).strftime("%d.%m.%Y")
    if trial_active(chat_id):
        return "🎁 пробный до " + datetime.fromtimestamp(trial_until(chat_id)).strftime("%d.%m.%Y %H:%M")
    if not CONFIG.get("require_approval", True):
        return "✅ допуск не требуется"
    return "⛔ нет допуска (нужно одобрение или тариф /pro)"


def tariff_text(chat_id) -> str:
    return (
        "⭐ Тариф «Профессиональный»\n\n"
        f"Статус этой группы: {access_status(chat_id)}\n\n"
        "Полный функционал бота: антиспам, капча, автоответы, посты, статистика.\n"
        "Оплата звёздами Telegram прямо здесь — выбери срок:"
    )


def tariff_kb(chat_id) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"⭐ {p['stars']} — {p['title']}",
                                  callback_data=f"buyg:{chat_id}:{key}")]
            for key, p in PRO_PLANS.items()]
    return InlineKeyboardMarkup(rows)


async def cmd_pro(update: Update, context):
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        remember_group(chat)
        return await update.effective_message.reply_text(
            tariff_text(chat.id), reply_markup=tariff_kb(chat.id))
    lines = ["⭐ Тариф «Профессиональный» — оплата в самой группе командой /pro.", ""]
    for key, p in PRO_PLANS.items():
        lines.append(f"• {p['title']} — {p['stars']} ⭐")
    lines.append("\nДобавь бота в группу, дай права админа и вызови там /pro.")
    await update.effective_message.reply_text("\n".join(lines))


async def handle_buy_group_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    try:
        _, cid, plan = (query.data or "").split(":", 2)
        cid = int(cid)
    except ValueError:
        return await query.answer()
    p = PRO_PLANS.get(plan)
    if not p:
        return await query.answer("Неизвестный тариф", show_alert=True)
    if not (is_manager(user.id) or user.id in await group_admin_ids(context, cid)):
        return await query.answer("Тариф оформляют администраторы группы", show_alert=True)
    title = CONFIG.get("groups", {}).get(str(cid), "группа")
    try:
        await context.bot.send_invoice(
            chat_id=cid,
            title=f"Тариф PRO · {p['title']}",
            description=f"Полный доступ бота в «{title}» на {p['days']} дней.",
            payload=f"pro:{cid}:{plan}",
            provider_token="",  # Telegram Stars
            currency="XTR",
            prices=[LabeledPrice(label=p["title"], amount=p["stars"])],
        )
        await query.answer("Счёт отправлен — оплати звёздами ⭐")
    except Exception as e:  # noqa: BLE001
        await query.answer(f"Оплата сейчас недоступна: {e}"[:190], show_alert=True)


async def on_pre_checkout(update: Update, context):
    q = update.pre_checkout_query
    try:
        await q.answer(ok=True)
    except Exception as e:  # noqa: BLE001
        log.debug("pre_checkout: %s", e)


async def on_successful_payment(update: Update, context):
    sp = update.effective_message.successful_payment
    payload = sp.invoice_payload or ""
    parts = payload.split(":")
    if len(parts) == 3 and parts[0] == "pro":
        cid, plan = int(parts[1]), parts[2]
        p = PRO_PLANS.get(plan, {"days": 30, "stars": sp.total_amount})
        extend_pro(cid, p["days"])
        until = datetime.fromtimestamp(pro_until(cid)).strftime("%d.%m.%Y")
        try:
            await context.bot.send_message(
                cid, f"⭐ Оплата получена! Тариф активен до {until}. Спасибо! Панель управления — в ЛС бота: /panel")
        except Exception:  # noqa: BLE001
            pass
        title = CONFIG.get("groups", {}).get(str(cid), str(cid))
        payer = mention(update.effective_user) if update.effective_user else "?"
        await alert_owners(context, f"💰 Оплата {sp.total_amount} ⭐ за «{title}» ({plan}) от {payer}. До {until}.")


async def cmd_grantpro(update: Update, context):
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    args = context.args or []
    chat = update.effective_chat
    cid = chat.id if chat.type in ("group", "supergroup") else None
    days = 30
    for a in args:
        if re.fullmatch(r"-?\d{6,}", a):
            cid = int(a)
        elif a.isdigit():
            days = int(a)
    if cid is None:
        return await update.effective_message.reply_text(
            "Формат: /grantpro <chat_id> <дней>  (в группе chat_id можно не указывать)")
    extend_pro(cid, days)
    until = datetime.fromtimestamp(pro_until(cid)).strftime("%d.%m.%Y")
    await update.effective_message.reply_text(
        f"⭐ Выдал PRO чату {CONFIG.get('groups', {}).get(str(cid), cid)} на {days} дн (до {until}).")

# ───────────────────────────────────────────────────────────────────────────
#  ФОНОВЫЕ ЗАДАЧИ: единый минутный тик + уборщик + сводки
# ───────────────────────────────────────────────────────────────────────────


async def _tick_promo(context, now: float):
    p = CONFIG["promo"]
    if not p.get("enabled") or not (p.get("text") or p.get("file_id")):
        return
    if now - _state["last_promo"] < int(p.get("interval", 3600)):
        return
    _state["last_promo"] = now
    post = {"type": p.get("type", "text"), "text": p.get("text", ""), "file_id": p.get("file_id"),
            "buttons": p.get("buttons", []), "pin": p.get("pin", False), "html": p.get("html", False)}
    ok = 0
    for cid in list(CONFIG["groups"].keys()):
        if await deliver(context, cid, post):
            ok += 1
        await asyncio.sleep(0.1)
    if ok:
        log.info("Авто-промо отправлено в %s групп", ok)


async def _tick_recurring(context, now: float):
    for cid in list(CONFIG.get("groups", {}).keys()):
        items = chat_cfg(int(cid)).get("recurring", []) or []
        for idx, r in enumerate(items):
            if not (isinstance(r, dict) and r.get("enabled") and r.get("text")):
                continue
            interval = max(5, int(r.get("interval", 60))) * 60
            key = (str(cid), idx)
            if now - _recurring_last.get(key, 0) < interval:
                continue
            _recurring_last[key] = now
            await deliver(context, cid, {"type": "text", "text": r["text"]})


async def _tick_scheduled(context):
    now = datetime.now(_post_tz())
    stamp = now.strftime("%Y-%m-%d %H:%M")
    for post in list(CONFIG.get("scheduled_posts", [])):
        pid = post.get("id")
        if not pid or _post_last_fired.get(pid) == stamp:
            continue
        if _post_due(post, now):
            _post_last_fired[pid] = stamp
            await _send_scheduled_post(context, post)


async def minute_tick(context):
    """Один минутный job вместо трёх: промо, повторяющиеся сообщения, посты."""
    now = time.time()
    for fn in (_tick_promo, _tick_recurring):
        try:
            await fn(context, now)
        except Exception as e:  # noqa: BLE001
            log.warning("tick %s: %s", fn.__name__, e)
    try:
        await _tick_scheduled(context)
    except Exception as e:  # noqa: BLE001
        log.warning("tick scheduled: %s", e)


async def janitor_job(context):
    """Раз в час выкидываем протухшие записи из оперативных словарей."""
    now = time.time()
    day = 86400
    for d, ttl in ((_join_handled, 600), (_report_cd, 2 * 3600), (_appeal_cd, 2 * 3600),
                   (join_dates, 30 * day), (_throttle_store, 3600), (_recurring_last, 7 * day)):
        for k in [k for k, v in list(d.items()) if now - v > ttl]:
            d.pop(k, None)
    for k, v in list(soft_mutes.items()):
        if v and v <= now:
            soft_mutes.pop(k, None)
    for store in (flood_store, nuke_store):
        for k, dq in list(store.items()):
            if not dq or now - dq[-1] > 3600:
                store.pop(k, None)
    for k, dq in list(_raid_joins.items()):
        if not dq or now - dq[-1] > 3600:
            _raid_joins.pop(k, None)
    for k, v in list(_raid_until.items()):
        if v <= now:
            _raid_until.pop(k, None)
    alive = {p.get("id") for p in CONFIG.get("scheduled_posts", [])}
    for pid in [p for p in _post_last_fired if p not in alive]:
        _post_last_fired.pop(pid, None)


async def weekly_digest_job(context):
    """Раз в неделю — сводка по каждой группе в её staff-чат (или владельцам)."""
    for cid in list(CONFIG.get("groups", {}).keys()):
        try:
            if not chat_allowed(int(cid)):
                continue
            total, today, week, top = _msg_stats_summary(cid)
            s = _stats_chat(cid).get("mod", {})
            title = CONFIG["groups"].get(cid, cid)
            top_line = ", ".join(f"{n} ({c})" for n, c in top[:3]) or "—"
            await notify_staff(context, int(cid),
                               f"🗞 Недельная сводка · {title}\n"
                               f"Сообщений за неделю: {week}\n"
                               f"Топ: {top_line}\n"
                               f"Модерация (всего): удалено {s.get('deleted', 0)}, "
                               f"предов {s.get('warns', 0)}, мутов {s.get('muted', 0) + s.get('flood_muted', 0)}, "
                               f"банов {s.get('banned', 0)}, киков {s.get('kicked', 0)}")
        except Exception as e:  # noqa: BLE001
            log.debug("digest %s: %s", cid, e)


async def maintenance_daily_job(context):
    """Раз в сутки: напоминание об окончании тарифа/триала."""
    for cid in list(CONFIG.get("groups", {}).keys()):
        had_paid = str(cid) in CONFIG.get("subscriptions", {}) or str(cid) in CONFIG.get("trials", {})
        if not had_paid or chat_allowed(int(cid)) or str(cid) in _expiry_notified:
            continue
        _expiry_notified.add(str(cid))
        title = CONFIG["groups"].get(str(cid), cid)
        try:
            await context.bot.send_message(int(cid),
                                           "⛔ Доступ бота в этой группе закончился. Продлить — /pro.")
        except Exception:  # noqa: BLE001
            pass
        await alert_owners(context, f"⌛ У «{title}» закончился доступ (тариф/триал).")


async def flush_config_job(context):
    _flush_config()

# ───────────────────────────────────────────────────────────────────────────
#  РАССЫЛКА И БЭКАПЫ
# ───────────────────────────────────────────────────────────────────────────


async def cmd_broadcast(update: Update, context):
    if not is_manager(update.effective_user.id):
        return await _deny(update)
    text = _args_text(update)
    if not text:
        return await update.effective_message.reply_text(
            "Формат: /broadcast текст — отправлю во все группы.\n"
            "Рассылка с фото/кнопками и в ЛС подписчикам — через панель (📣 Промо).")
    ok, fail = await _broadcast(context, text=text)
    await update.effective_message.reply_text(f"📤 Рассылка: отправлено {ok}, недоступно {fail}.")


def _slug(s: str) -> str:
    s = re.sub(r"[^\w\- ]+", "", s or "", flags=re.UNICODE).strip().replace(" ", "_")
    return s[:40] or "chat"


async def send_backup(context, to_id: int):
    _flush_config()
    data = json.dumps(CONFIG, ensure_ascii=False, indent=2).encode("utf-8")
    bio = io.BytesIO(data)
    bio.name = f"config_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    await context.bot.send_document(to_id, bio,
                                    caption="🗄 Полный бэкап настроек. Восстановить: пришли этот файл мне в ЛС.")


def extract_chat_settings(chat_id) -> dict:
    cfg = chat_cfg(chat_id)
    out = {k: copy.deepcopy(cfg.get(k)) for k in PER_CHAT_KEYS}
    out["_chat_backup"] = True
    out["_title"] = CONFIG.get("groups", {}).get(str(chat_id), str(chat_id))
    return out


def apply_chat_settings(chat_id, data: dict):
    dst = chat_cfg_writable(chat_id)
    for k in PER_CHAT_KEYS:
        if k in data:
            dst[k] = copy.deepcopy(data[k])
    save_config(force=True)


async def send_chat_backup(context, to_id: int, chat_id):
    data = json.dumps(extract_chat_settings(chat_id), ensure_ascii=False, indent=2).encode("utf-8")
    title = CONFIG.get("groups", {}).get(str(chat_id), str(chat_id))
    bio = io.BytesIO(data)
    bio.name = f"chat_{_slug(title)}.json"
    await context.bot.send_document(to_id, bio,
                                    caption=f"🗄 Настройки группы «{title}». Восстановить: пришли файл мне в ЛС "
                                            f"(применится к выбранной в панели группе).")

# ───────────────────────────────────────────────────────────────────────────
#  ПАНЕЛЬ УПРАВЛЕНИЯ: клавиатуры и тексты
# ───────────────────────────────────────────────────────────────────────────


def _cycle(lst, cur):
    try:
        return lst[(lst.index(cur) + 1) % len(lst)]
    except ValueError:
        return lst[0]


async def safe_edit(query, text, kb):
    """Правка сообщения панели без падений на 'message is not modified'."""
    try:
        await query.edit_message_text(text, reply_markup=kb, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("safe_edit: %s", e)
    except Exception as e:  # noqa: BLE001
        log.debug("safe_edit: %s", e)
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass


def onoff(v) -> str:
    return "🟢" if v else "🔴"


def status_text(context) -> str:
    cfg = panel_cfg_view(context)
    label = panel_target_label(context)
    tgt = context.user_data.get("cfg_target")
    en = cfg["enabled"]
    on = sum(1 for k, _ in FEATURES if en.get(k))
    access = access_status(int(tgt)) if tgt and tgt != "defaults" else "—"
    custom = "индивидуальные" if (tgt and str(tgt) in CONFIG.get("chats", {})) else "по общему шаблону"
    return (
        f"🛡 Панель управления\n"
        f"Группа: {label}\n"
        f"Доступ: {access}\n"
        f"Настройки: {custom} · включено фильтров: {on}/{len(FEATURES)}\n"
        f"За спам: {_ACT_RU.get(cfg.get('spam_action', 'delete'))} · "
        f"стоп-слов {len(cfg.get('stop_words', []))} · исключений {len(cfg.get('white_words', []))} · "
        f"автоответов {len(cfg.get('triggers', {}))}\n\n"
        f"Выбери раздел:"
    )


def main_menu_kb(context) -> InlineKeyboardMarkup:
    manager = is_manager((context.user_data or {}).get("_uid", 0))
    rows = [
        [InlineKeyboardButton("📂 Выбрать группу", callback_data="m:pick"),
         InlineKeyboardButton("⚡ Быстрые тумблеры", callback_data="m:quick")],
        [InlineKeyboardButton("🧩 Фильтры (вкл/выкл)", callback_data="m:toggles"),
         InlineKeyboardButton("🛡 Модерация", callback_data="m:mod")],
        [InlineKeyboardButton("🚫 Стоп-слова", callback_data="m:words"),
         InlineKeyboardButton("🧨 Второй список", callback_data="m:words2")],
        [InlineKeyboardButton("🔗 Спам-домены", callback_data="m:links"),
         InlineKeyboardButton("🌊 Антифлуд", callback_data="m:flood")],
        [InlineKeyboardButton("💬 Автоответы", callback_data="m:triggers"),
         InlineKeyboardButton("📎 Медиа-фильтр", callback_data="m:media")],
        [InlineKeyboardButton("👋 Приветствие", callback_data="m:welcome"),
         InlineKeyboardButton("🤖 Капча", callback_data="m:captcha")],
        [InlineKeyboardButton("🌙 Ночной режим", callback_data="m:night"),
         InlineKeyboardButton("🔁 Авто-сообщения", callback_data="m:recurring")],
        [InlineKeyboardButton("⛔ Чёрный список", callback_data="m:blacklist"),
         InlineKeyboardButton("🚨 Анти-рейд", callback_data="m:antiraid")],
        [InlineKeyboardButton("🧱 Анти-снос", callback_data="m:antinuke"),
         InlineKeyboardButton("🎖 Роли", callback_data="m:roles")],
        [InlineKeyboardButton("🔐 Права команд", callback_data="m:cmdperms"),
         InlineKeyboardButton("🗣 Язык новичков", callback_data="m:lang")],
        [InlineKeyboardButton("📜 Правила", callback_data="m:rules"),
         InlineKeyboardButton("🧷 Staff-чат", callback_data="m:staff")],
    ]
    if manager:
        rows += [
            [InlineKeyboardButton("📣 Промо и рассылки", callback_data="m:promo"),
             InlineKeyboardButton("🗓 Посты по расписанию", callback_data="m:sched")],
            [InlineKeyboardButton("🌐 Глобальные списки", callback_data="m:global"),
             InlineKeyboardButton("🔓 Допуск групп", callback_data="m:approve")],
            [InlineKeyboardButton("👥 Менеджеры бота", callback_data="m:access")],
        ]
    rows += [
        [InlineKeyboardButton("🗄 Бэкап", callback_data="m:backup"),
         InlineKeyboardButton("▶️ Ещё", callback_data="m:other")],
        [InlineKeyboardButton("➕ Как добавлять", callback_data="m:add"),
         InlineKeyboardButton("ℹ️ О боте", callback_data="m:about")],
    ]
    return InlineKeyboardMarkup(rows)


def pick_kb(groups, manager: bool) -> InlineKeyboardMarkup:
    rows = []
    for cid, title in groups[:50]:
        mark = "📂 " if str(cid) in CONFIG.get("chats", {}) else ""
        rows.append([InlineKeyboardButton(f"{mark}{title[:40]}", callback_data=f"pick:{cid}")])
    if manager:
        rows.append([InlineKeyboardButton("🧬 Общий шаблон (для новых групп)", callback_data="pick:defaults")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


QUICK_KEYS = ["words", "words2", "flood", "triggers", "invites", "all_links", "clean_service", "clean_commands"]


def quick_kb(cfg) -> InlineKeyboardMarkup:
    names = dict(FEATURES)
    rows = [[InlineKeyboardButton(f"{onoff(cfg['enabled'].get(k))} {names.get(k, k)}",
                                  callback_data=f"q:{k}")] for k in QUICK_KEYS]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def toggles_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{onoff(cfg['enabled'].get(k))} {title}", callback_data=f"t:{k}")]
            for k, title in FEATURES]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить слова", callback_data="add:word")]]
    for i, w in enumerate(sorted(cfg.get("stop_words", []))[:60]):
        rows.append([InlineKeyboardButton(f"❌ {w}", callback_data=f"dw:{i}")])
    rows.append([InlineKeyboardButton("⚪ Исключения (белый список)", callback_data="m:whitewords")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words_menu_text(cfg, label) -> str:
    return (f"🚫 Стоп-слова · {label}\n\n"
            f"Слов: {len(cfg.get('stop_words', []))} (+{len(CONFIG.get('global_stop_words', []))} глобальных). "
            f"Наказание — «За спам» в 🛡 Модерации: {_ACT_RU.get(cfg.get('spam_action', 'delete'))}.\n\n"
            "Синтаксис:\n"
            "• слово — только целое слово («бан» не тронет «банан»)\n"
            "• слово* — начало слова («ставк*» ловит «ставки»)\n"
            "• *слово — конец слова\n"
            "• *слово* — любое вхождение\n\n"
            "Ключи автоответов и ⚪ исключения нарушением не считаются. "
            "Обходы (невидимые символы, латинские двойники, ё/е) я выравниваю сам.")


def whitewords_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить исключение", callback_data="add:wword")]]
    for i, w in enumerate(sorted(cfg.get("white_words", []))[:60]):
        rows.append([InlineKeyboardButton(f"❌ {w}", callback_data=f"dww:{i}")])
    rows.append([InlineKeyboardButton("⬅️ К стоп-словам", callback_data="m:words")])
    return InlineKeyboardMarkup(rows)


def whitewords_menu_text(cfg, label) -> str:
    return (f"⚪ Исключения · {label}\n\n"
            f"Слов: {len(cfg.get('white_words', []))}\n\n"
            "Эти слова никогда не считаются нарушением, даже если их цепляет стоп-слово "
            "(обычное, из второго списка или глобальное). Ключи автоответов защищены сами.\n"
            "Синтаксис тот же: слово — точное, слово* — начало, *слово* — любое вхождение.")


def words2_kb(cfg) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{onoff(cfg['enabled'].get('words2'))} Второй список включён",
                              callback_data="t2:words2")],
        [InlineKeyboardButton(f"⚖️ Наказание: {_ACT_RU.get(cfg.get('stop_words2_action', 'ban'))}",
                              callback_data="w2act")],
        [InlineKeyboardButton(f"{onoff(cfg.get('stop_words2_profile', True))} Проверять имя/юзернейм автора",
                              callback_data="w2prof")],
        [InlineKeyboardButton("➕ Добавить слова", callback_data="add:word2")],
    ]
    for i, w in enumerate(sorted(cfg.get("stop_words2", []))[:60]):
        rows.append([InlineKeyboardButton(f"❌ {w}", callback_data=f"dw2:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words2_menu_text(cfg, label) -> str:
    return (f"🧨 Второй список слов · {label}\n\n"
            f"Слов: {len(cfg.get('stop_words2', []))}. Свой набор со СВОИМ наказанием — обычно "
            "строже первого (например, мгновенный бан за мат или наркотемы).\n"
            "Синтаксис слов тот же (звёздочки). Проверка имени ловит спамеров с "
            "«рекламой в нике» по первому же сообщению.")


def links_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить домены", callback_data="add:link")]]
    for i, d in enumerate(sorted(cfg.get("spam_links", []))[:60]):
        rows.append([InlineKeyboardButton(f"❌ {d}", callback_data=f"dl:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def links_menu_text(cfg, label) -> str:
    en = cfg["enabled"]
    return (f"🔗 Ссылки · {label}\n\n"
            f"Invite-ссылки: {onoff(en.get('invites'))} · сокращатели: {onoff(en.get('shorteners'))} · "
            f"ВСЕ ссылки: {onoff(en.get('all_links'))} (переключается в 🧩 Фильтрах)\n"
            f"Свои спам-домены: {len(cfg.get('spam_links', []))} — сообщения с ними удаляются.\n"
            "Домен указывай без http:// — например: example.com")


def flood_kb(cfg) -> InlineKeyboardMarkup:
    f = cfg["flood"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(cfg['enabled'].get('flood'))} Антифлуд включён", callback_data="t2:flood")],
        [InlineKeyboardButton(f"📨 Порог: {f['limit']} сообщ.", callback_data="fl:limit"),
         InlineKeyboardButton(f"⏱ Окно: {f['period']} сек", callback_data="fl:period")],
        [InlineKeyboardButton(f"🔇 Мут за флуд: {human_duration(f['mute'])}", callback_data="fl:mute")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def mod_kb(cfg) -> InlineKeyboardMarkup:
    m = cfg["moderation"]
    exp = m.get("warn_expire_days", 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚠️ Лимит предупреждений: {m['warn_limit']}", callback_data="md:limit")],
        [InlineKeyboardButton(f"⚖️ По лимиту: {'бан' if m['warn_action'] == 'ban' else 'мут'}",
                              callback_data="md:act"),
         InlineKeyboardButton(f"🔇 Мут: {human_duration(m['warn_mute'])}", callback_data="md:mute")],
        [InlineKeyboardButton(f"⌛ Преды сгорают: {('через ' + str(exp) + ' дн') if exp else 'никогда'}",
                              callback_data="md:expire")],
        [InlineKeyboardButton(f"🧨 За спам: {_ACT_RU.get(cfg.get('spam_action', 'delete'))}",
                              callback_data="md:spamact")],
        [InlineKeyboardButton(f"{onoff(m.get('notify_delete'))} Писать в чат, что удалил",
                              callback_data="md:notif")],
        [InlineKeyboardButton(f"{onoff(m.get('log_actions'))} Журнал действий (в staff-чат)",
                              callback_data="md:log")],
        [InlineKeyboardButton(f"{onoff(m.get('mod_admins_only'))} Модерация только для владельца бота",
                              callback_data="md:adm")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def mod_menu_text(cfg, label) -> str:
    return (f"🛡 Модерация · {label}\n\n"
            "«За спам» — что делать с автором спам-ссылки или стоп-слова из первого списка: "
            "только удалить, или ещё предупреждение / мут / бан.\n"
            "Предупреждения копятся (/warn и авто), по лимиту — мут или бан.")


def media_kb(cfg) -> InlineKeyboardMarkup:
    mb = cfg.get("media_block", {})
    rows, row = [], []
    for k, title in MEDIA_TYPES:
        row.append(InlineKeyboardButton(f"{'🔴' if mb.get(k) else '🟢'} {title}", callback_data=f"mb:{k}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(f"⚖️ Наказание: {_ACT_RU.get(cfg.get('media_action', 'delete'))}",
                                      callback_data="mact")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def media_menu_text(cfg, label) -> str:
    return (f"📎 Медиа-фильтр · {label}\n\n"
            "🔴 — этот тип вложений у обычных участников запрещён (админов не касается).\n"
            "«Пересланные» — любые форварды из других чатов/каналов.")


def night_kb(cfg) -> InlineKeyboardMarkup:
    n = cfg["night"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(n.get('enabled'))} Ночной режим включён", callback_data="nm:tgl")],
        [InlineKeyboardButton(f"🌆 С {n.get('start', 23)}:00", callback_data="nm:start"),
         InlineKeyboardButton(f"🌅 До {n.get('end', 7)}:00", callback_data="nm:end")],
        [InlineKeyboardButton(f"🕑 Пояс: UTC{'+' if int(n.get('tz', 0)) >= 0 else ''}{n.get('tz', 0)}",
                              callback_data="nm:tz")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def night_menu_text(cfg, label) -> str:
    n = cfg["night"]
    state = "сейчас АКТИВЕН — сообщения удаляются" if is_night_now(n) else "сейчас не активен"
    return (f"🌙 Ночной режим · {label}\n\n"
            f"{state}.\nВ заданные часы сообщения обычных участников тихо удаляются; "
            "админов и доверенных это не касается.")


def triggers_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Текст", callback_data="add:trigger"),
             InlineKeyboardButton("🖼 Медиа/кнопки", callback_data="add:trigmedia")],
            [InlineKeyboardButton(
                f"🎯 Совпадение: {'слово целиком' if cfg.get('trigger_match', 'word') == 'word' else 'вхождение'}",
                callback_data="mode:trig")]]
    trg = cfg.get("triggers", {})
    for i, k in enumerate(sorted(trg)[:60]):
        rows.append([InlineKeyboardButton(f"❌ {k} → {_trig_preview(trg[k])}", callback_data=f"dt:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def triggers_menu_text(cfg, label) -> str:
    return (f"💬 Автоответы · {label}\n\n"
            f"Всего: {len(cfg.get('triggers', {}))}. Бот отвечает реплаем на ключевое слово "
            "(не чаще раза в 10 сек на слово).\n"
            "Ответ — текст с форматированием и {вариантами|рандомизации}, либо медиа "
            "(фото/видео/гиф/стикер/файл) с подписью и кнопками-ссылками.\n"
            "Ключи можно со звёздочкой: «банан*» ответит и на «бананы». "
            "Ключи автоответов защищены от стоп-слов.\n"
            "Повторное добавление того же ключа перезаписывает ответ.")


def welcome_kb(cfg) -> InlineKeyboardMarkup:
    w = cfg["welcome"]
    da = int(w.get("delete_after", 0) or 0)
    ji = cfg.get("show_join_id", "off")
    ji_ru = {"off": "выкл", "all": "в чат", "admins": "в staff"}.get(ji, ji)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(w.get('enabled'))} Приветствие включено", callback_data="wl:tgl")],
        [InlineKeyboardButton("✏️ Текст", callback_data="wl:edit"),
         InlineKeyboardButton("🔘 Кнопки", callback_data="wl:btns")],
        [InlineKeyboardButton(f"🗑 Удалять через: {human_duration(da) if da else 'не удалять'}",
                              callback_data="wl:del")],
        [InlineKeyboardButton(f"🆔 Показывать ID новичка: {ji_ru}", callback_data="ji:cycle")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def welcome_menu_text(cfg, label) -> str:
    w = cfg["welcome"]
    return (f"👋 Приветствие · {label}\n\n"
            "Плейсхолдеры: {name} — имя, {mention} — @упоминание, {chat} — название группы.\n"
            f"Сейчас: «{(w.get('text') or '')[:200]}»\n"
            f"Кнопок-рядов: {len(w.get('buttons') or [])}")


def captcha_kb(cfg) -> InlineKeyboardMarkup:
    c = cfg["captcha"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(c.get('enabled'))} Капча включена", callback_data="cp:tgl")],
        [InlineKeyboardButton(f"⏱ Время: {human_duration(c.get('timeout', 120))}", callback_data="cp:timeout"),
         InlineKeyboardButton(f"⚖️ Не прошёл: {'кик' if c.get('action', 'kick') == 'kick' else 'мут'}",
                              callback_data="cp:action")],
        [InlineKeyboardButton(f"{onoff(c.get('via_request', True))} Через заявки (капча в ЛС)",
                              callback_data="cp:via")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def captcha_menu_text(cfg, label) -> str:
    return (f"🤖 Капча · {label}\n\n"
            "«Через заявки» — лучший режим: включи в группе вступление по заявкам, "
            "и бот будет присылать кнопку в ЛС; спамер не попадёт в чат вовсе.\n"
            "Иначе капча выдаётся прямо в чате: новичок в муте, пока не нажмёт кнопку "
            "(в обычной группе — «мягкий мут» удалением сообщений).\n"
            "Язык кнопки и текста — в 🗣 «Язык новичков».")


def rules_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить правила", callback_data="ru:edit")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def rules_menu_text(cfg, label) -> str:
    return f"📜 Правила · {label}\n\nПоказываются по /rules.\n\n{(cfg.get('rules') or '— не заданы —')[:800]}"


def blacklist_kb(cfg) -> InlineKeyboardMarkup:
    bl = cfg.get("blacklist", {"ids": [], "names": []})
    rows = [[InlineKeyboardButton("➕ По ID", callback_data="add:blid"),
             InlineKeyboardButton("➕ По имени", callback_data="add:blname")]]
    for i, v in enumerate(bl.get("ids", [])[:30]):
        rows.append([InlineKeyboardButton(f"❌ id {v}", callback_data=f"dblid:{i}")])
    for i, v in enumerate(bl.get("names", [])[:30]):
        rows.append([InlineKeyboardButton(f"❌ «{v}»", callback_data=f"dblname:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def blacklist_menu_text(cfg, label) -> str:
    bl = cfg.get("blacklist", {})
    return (f"⛔ Чёрный список · {label}\n\n"
            f"ID: {len(bl.get('ids', []))} · подстрок имени: {len(bl.get('names', []))}\n"
            "Такой человек банится при входе или при первом сообщении. "
            "«По имени» — подстрока в имени/фамилии/юзернейме.\n"
            "Быстро добавить из чата: /block (ответом на сообщение).")


def antiraid_kb(cfg) -> InlineKeyboardMarkup:
    a = cfg["antiraid"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(a.get('enabled'))} Анти-рейд включён", callback_data="ar:tgl")],
        [InlineKeyboardButton(f"👥 Порог: {a.get('joins', 8)} входов", callback_data="ar:joins"),
         InlineKeyboardButton(f"⏱ за {a.get('window', 60)} сек", callback_data="ar:window")],
        [InlineKeyboardButton(f"🔒 Строгий режим: {a.get('lock_min', 10)} мин", callback_data="ar:lock")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def antiraid_menu_text(cfg, label) -> str:
    return (f"🚨 Анти-рейд · {label}\n\n"
            "При всплеске входов (ботоводы заливают аккаунты) включается строгий режим: "
            "новые участники на время автоматически выкидываются, staff-чат получает сигнал.")


def antinuke_kb(cfg) -> InlineKeyboardMarkup:
    a = cfg["antinuke"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(a.get('enabled'))} Анти-снос включён", callback_data="an:tgl")],
        [InlineKeyboardButton(f"🔨 Порог: {a.get('ban_threshold', 5)} банов / {a.get('window', 30)} сек",
                              callback_data="an:thresh")],
        [InlineKeyboardButton(f"⚖️ Реакция: {'снять права' if a.get('action') != 'ban' else 'забанить'}",
                              callback_data="an:act")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def antinuke_menu_text(cfg, label) -> str:
    return (f"🧱 Анти-снос · {label}\n\n"
            "Если админ начинает массово банить участников (взлом/обида), бот бьёт тревогу "
            "и пытается остановить его. Чтобы «снять права» сработало, я должен стоять "
            "в списке админов ВЫШЕ него (назначен позже с правом назначать).")


def roles_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Создать роль", callback_data="add:role")]]
    for name in sorted(cfg.get("roles", {}))[:30]:
        r = cfg["roles"][name] or {}
        rows.append([InlineKeyboardButton(
            f"🎖 {name} · {len(r.get('members', []))} чел · {len(r.get('perms', []))} прав",
            callback_data=f"rl:{name}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def roles_menu_text(cfg, label) -> str:
    return (f"🎖 Роли · {label}\n\n"
            "Свои звания для доверенных участников: модератор, хелпер и т.п. Участник роли "
            "не попадает под фильтры и получает выбранные права команд.\n"
            "Выдать в чате: /role <имя_роли> ответом на сообщение.")


def role_detail_kb(cfg, name) -> InlineKeyboardMarkup:
    r = cfg.get("roles", {}).get(name, {"perms": [], "members": []})
    rows = [[InlineKeyboardButton(f"{'✅' if k in r.get('perms', []) else '▫️'} {title}",
                                  callback_data=f"rp:{name}:{k}")] for k, title in ROLE_PERM_DEFS]
    rows.append([InlineKeyboardButton("➕ Участник по ID", callback_data=f"rmadd:{name}")])
    names_map = {}
    for m in r.get("members", [])[:20]:
        rows.append([InlineKeyboardButton(f"❌ участник {names_map.get(str(m), m)}",
                                          callback_data=f"rmx:{name}:{m}")])
    rows.append([InlineKeyboardButton("🗑 Удалить роль", callback_data=f"rdel:{name}"),
                 InlineKeyboardButton("⬅️ Назад", callback_data="m:roles")])
    return InlineKeyboardMarkup(rows)


def staff_menu_text(cfg, label) -> str:
    sg = cfg.get("staff_group", 0)
    cur = CONFIG.get("groups", {}).get(str(sg), sg) if sg else "— не задан —"
    return (f"🧷 Staff-чат · {label}\n\n"
            f"Сейчас: {cur}\n\n"
            "Служебная группа для команды: туда идут жалобы (/report), журнал действий, "
            "тревоги анти-рейда/анти-сноса и недельные сводки.\n"
            "Привязать: создай отдельную группу, добавь туда бота и выполни там /setstaff.")


def staff_kb(cfg) -> InlineKeyboardMarkup:
    rows = []
    if cfg.get("staff_group", 0):
        rows.append([InlineKeyboardButton("🗑 Отвязать staff-чат", callback_data="st:clear")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def cmdperms_kb(cfg) -> InlineKeyboardMarkup:
    rows = []
    for k, title, _lv, _d in CMD_DEFS:
        rows.append([InlineKeyboardButton(f"{title}: {LEVEL_SHORT.get(cmd_level_from(cfg, k))}",
                                          callback_data=f"perm:{k}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def cmd_level_from(cfg, key) -> str:
    return cfg.get("cmd_perms", {}).get(key, CMD_DEFAULT.get(key, "admins"))


def cmdperms_menu_text(label) -> str:
    return (f"🔐 Права команд · {label}\n\n"
            "Кому доступны команды наказаний и настройки. Владелец и менеджеры бота — всегда. "
            "«Создатель группы» — только владелец самой группы.\n"
            "Точечные права отдельным людям — через 🎖 Роли.")


def lang_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(("✅ " if cfg.get("lang", "ru") == code else "") + name,
                                  callback_data=f"lang:{code}")] for code, name in LANGS.items()]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def recurring_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить авто-сообщение", callback_data="rec:add")]]
    for i, r in enumerate((cfg.get("recurring") or [])[:20]):
        mark = onoff(r.get("enabled"))
        rows.append([
            InlineKeyboardButton(f"{mark} кажд. {r.get('interval', 60)} мин · {str(r.get('text', ''))[:20]}",
                                 callback_data=f"rectgl:{i}"),
            InlineKeyboardButton("❌", callback_data=f"recdel:{i}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def recurring_menu_text(cfg, label) -> str:
    return (f"🔁 Авто-сообщения · {label}\n\n"
            "Периодические напоминания в чат (правила, ссылки, реклама своих услуг). "
            "Формат добавления: «минуты - текст», напр.: 120 - Не забывайте про /rules!\n"
            "Минимальный интервал — 5 минут. Работает {рандомизация|вариантов}.")


def other_kb(context) -> InlineKeyboardMarkup:
    rows = []
    tgt = context.user_data.get("cfg_target")
    if tgt and tgt != "defaults" and str(tgt) in CONFIG.get("chats", {}):
        rows.append([InlineKeyboardButton("↩️ Сбросить настройки к шаблону", callback_data="resetchat")])
    if is_manager(context.user_data.get("_uid", 0)):
        rows.append([InlineKeyboardButton(
            f"🕑 Часовой пояс расписаний: UTC{'+' if int(CONFIG.get('post_tz', 0)) >= 0 else ''}{CONFIG.get('post_tz', 0)}",
            callback_data="tz:cycle")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def other_menu_text(context) -> str:
    label = panel_target_label(context)
    return (f"▶️ Ещё · {label}\n\n"
            "«Сбросить к шаблону» — удалить индивидуальные настройки группы: она снова "
            "будет жить по общему шаблону (и меняться вместе с ним). Действие необратимо, "
            "при сомнениях сделай 🗄 бэкап.")


def global_kb() -> InlineKeyboardMarkup:
    g = CONFIG.get("global_blacklist", {"ids": [], "names": []})
    rows = [[InlineKeyboardButton("➕ Стоп-слово", callback_data="add:gword"),
             InlineKeyboardButton("➕ ЧС: ID", callback_data="add:gbid"),
             InlineKeyboardButton("➕ ЧС: имя", callback_data="add:gbname")]]
    for i, w in enumerate(sorted(CONFIG.get("global_stop_words", []))[:30]):
        rows.append([InlineKeyboardButton(f"❌ слово: {w}", callback_data=f"dgw:{i}")])
    for i, v in enumerate(g.get("ids", [])[:20]):
        rows.append([InlineKeyboardButton(f"❌ id {v}", callback_data=f"dgbid:{i}")])
    for i, v in enumerate(g.get("names", [])[:20]):
        rows.append([InlineKeyboardButton(f"❌ имя «{v}»", callback_data=f"dgbname:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def global_menu_text() -> str:
    return ("🌐 Глобальные списки (на ВСЕ группы)\n\n"
            f"Стоп-слов: {len(CONFIG.get('global_stop_words', []))} · "
            f"ЧС ID: {len(CONFIG.get('global_blacklist', {}).get('ids', []))} · "
            f"ЧС имён: {len(CONFIG.get('global_blacklist', {}).get('names', []))}\n"
            "Действуют поверх настроек каждой группы. Исключения группы могут "
            "локально «разрешить» глобальное слово.\nБыстро: /gblock и /gunblock.")


def access_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить менеджера (ID)", callback_data="dm:add")]]
    for uid in CONFIG.get("managers", [])[:20]:
        rows.append([InlineKeyboardButton(f"❌ {uid}", callback_data=f"dm:del:{uid}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def access_menu_text() -> str:
    owners = ", ".join(str(x) for x in sorted(ADMIN_IDS))
    return ("👥 Менеджеры бота\n\n"
            f"Главные владельцы (из окружения): {owners}\n"
            f"Менеджеры: {len(CONFIG.get('managers', []))}\n\n"
            "Менеджер управляет ботом как владелец (кроме выдачи прав). "
            "Быстро: /grant и /revoke (ответом или по ID).")


def approve_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"{onoff(CONFIG.get('require_approval', True))} Требовать допуск для новых групп",
        callback_data="apt:req")]]
    for cid, title in list(CONFIG.get("groups", {}).items())[:30]:
        ok = chat_allowed(int(cid))
        mark = "✅" if ok else "⛔"
        rows.append([InlineKeyboardButton(f"{mark} {title[:32]}",
                                          callback_data=f"appr:{'no' if int(cid) in CONFIG.get('approved_chats', []) else 'ok'}:{cid}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def approve_menu_text() -> str:
    return ("🔓 Допуск групп\n\n"
            "Нажми на группу: ⛔ → одобрить бесплатно; ✅ (если одобрена вручную) → отозвать.\n"
            "Группы с оплаченным тарифом/триалом работают сами по себе — их отзыв не отключит "
            "до конца оплаченного срока.\nВыдать тариф вручную: /grantpro <chat_id> <дней>. "
            "Выдать пробный: кнопкой в уведомлении о новой группе.")


def promo_kb() -> InlineKeyboardMarkup:
    p = CONFIG["promo"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(p.get('enabled'))} Авто-промо включено", callback_data="pr:tgl")],
        [InlineKeyboardButton(f"⏱ Интервал: {human_duration(p.get('interval', 3600))}", callback_data="pr:int"),
         InlineKeyboardButton(f"{onoff(p.get('pin'))} Закреплять", callback_data="pr:pin")],
        [InlineKeyboardButton("✏️ Контент промо", callback_data="pr:content"),
         InlineKeyboardButton("🔘 Кнопки", callback_data="pr:btns")],
        [InlineKeyboardButton("👀 Тест в ЛС", callback_data="pr:test")],
        [InlineKeyboardButton("📤 Разослать сейчас (все группы)", callback_data="pr:bcast")],
        [InlineKeyboardButton("📮 Пост в одну группу", callback_data="pr:post")],
        [InlineKeyboardButton("💌 Рассылка в ЛС подписчикам", callback_data="pr:dm")],
        [InlineKeyboardButton("✏️ Текст «зазывалы» (/zazyvala)", callback_data="pr:invitetext")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def promo_menu_text() -> str:
    p = CONFIG["promo"]
    return ("📣 Промо и рассылки (все группы)\n\n"
            f"Авто-промо: {'вкл' if p.get('enabled') else 'выкл'}, раз в {human_duration(p.get('interval', 3600))}, "
            f"тип: {_POST_TYPE_RU.get(p.get('type', 'text'))}\n"
            f"Текст: «{_TAG_RE.sub('', p.get('text') or '')[:120]}»\n\n"
            "Подписчики ЛС — те, кто вступал через заявки с капчей в личке.")


def post_groups_kb(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    if prefix == "dmto":
        rows.append([InlineKeyboardButton("💌 ВСЕМ подписчикам", callback_data="dmto:all")])
    for cid, title in list(CONFIG.get("groups", {}).items())[:40]:
        rows.append([InlineKeyboardButton(title[:40], callback_data=f"{prefix}:{cid}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:promo")])
    return InlineKeyboardMarkup(rows)


def sched_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Новый пост", callback_data="sp:new")]]
    for p in CONFIG.get("scheduled_posts", [])[:20]:
        pid = p.setdefault("id", _new_post_id())
        days = p.get("days") or []
        days_txt = "ежедн." if not days else ",".join(_WEEKDAYS_RU[d] for d in days)
        rows.append([
            InlineKeyboardButton(
                f"{onoff(p.get('enabled', True))} {p.get('time', '--:--')} {days_txt} · "
                f"{_trig_preview(p, 14)} · {_post_groups_label(p)}",
                callback_data=f"sptgl:{pid}"),
            InlineKeyboardButton("❌", callback_data=f"spdel:{pid}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def sched_menu_text() -> str:
    tz = CONFIG.get("post_tz", 0)
    return ("🗓 Посты по расписанию (во все или выбранные группы)\n\n"
            f"Часовой пояс расписания: UTC{'+' if int(tz) >= 0 else ''}{tz} (меняется в ▶️ Ещё).\n"
            "Нажми на пост — вкл/выкл, ❌ — удалить.")


def sched_groups_kb(pid: str) -> InlineKeyboardMarkup:
    post = _find_post(pid) or {}
    ch = post.get("chats", "all")
    rows = [[InlineKeyboardButton(("✅ " if ch == "all" else "") + "Все группы",
                                  callback_data=f"spg:{pid}:all")]]
    for cid, title in list(CONFIG.get("groups", {}).items())[:40]:
        mark = "✅ " if (isinstance(ch, list) and str(cid) in [str(c) for c in ch]) else ""
        rows.append([InlineKeyboardButton(f"{mark}{title[:38]}", callback_data=f"spg:{pid}:{cid}")])
    rows.append([InlineKeyboardButton("💾 Готово", callback_data="m:sched")])
    return InlineKeyboardMarkup(rows)


def backup_kb(context) -> InlineKeyboardMarkup:
    manager = is_manager(context.user_data.get("_uid", 0))
    rows = []
    if manager:
        rows.append([InlineKeyboardButton("📦 Скачать ПОЛНЫЙ бэкап", callback_data="bk:full")])
    rows.append([InlineKeyboardButton("📄 Скачать настройки этой группы", callback_data="bk:chat")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def backup_menu_text(context) -> str:
    return ("🗄 Бэкап · " + panel_target_label(context) + "\n\n"
            "Файл группы можно прислать мне в ЛС — настройки применятся к выбранной "
            "в панели группе (удобно клонировать конфиг между группами).\n"
            "Полный бэкап (только владелец) восстанавливает вообще всё — тоже просто "
            "пришли файл в ЛС.")


def add_help_text() -> str:
    return (
        "➕ Как добавлять (в ЛС, для выбранной группы):\n\n"
        "• Автоответ: /add банан - 300 руб  (несколько ключей: /add цена,прайс - смотри закреп)\n"
        "• С медиа и кнопками — кнопка «🖼 Медиа/кнопки» в 💬 Автоответах\n"
        "• Стоп-слова: /addword казино*, ставк*   (синтаксис звёздочек — в меню 🚫)\n"
        "• Спам-домены: /addlink scam.com, bit.ly\n"
        "• Удалить: /del банан · /delword казино* · /dellink scam.com\n"
        "• Списки: /list · /words · /links\n\n"
        "В группе: /ban /kick /mute 30m /warn /block /info — ответом на сообщение."
    )


def about_text() -> str:
    return (
        "🛡 Channel Guard · Версия 5\n\n"
        "Антиспам и модерация: стоп-слова с точным совпадением и масками (слово*), "
        "исключения, второй список со своим наказанием, скрытые ссылки, медиа-фильтр, "
        "антифлуд, капча (в чате и через заявки), анти-рейд, анти-снос, ночной режим, "
        "роли, предупреждения с эскалацией.\n"
        "Привлечение: приветствия с кнопками, автоответы с медиа, /all, зазывала, "
        "авто-промо, посты по расписанию, рассылки в группы и в ЛС подписчикам.\n"
        "Оплата тарифа — звёздами Telegram (/pro). Настройки — /panel в ЛС."
    )


HELP_TEXT = (
    "🛡 Помощь по боту\n\n"
    "В ЛИЧКЕ (управление):\n"
    "/panel — панель настроек (выбор группы, все разделы)\n"
    "/add ключ - ответ · /del · /list — автоответы (медиа — через панель)\n"
    "/addword слова · /delword · /words — стоп-слова (слово, слово*, *слово*)\n"
    "/addlink домены · /dellink · /links — спам-домены\n"
    "/broadcast текст — рассылка по группам (владелец)\n"
    "/status /about /pro /appeal /userid\n\n"
    "В ГРУППЕ (модерация — ответом на сообщение):\n"
    "/ban [30m|2ч|1д] [причина] · /unban · /kick\n"
    "/mute [30m] [причина] · /unmute · /warn [причина] · /unwarn · /warns\n"
    "/block · /unblock — чёрный список группы\n"
    "/info · /purge · /report · /me · /stats · /top\n"
    "/all [текст] · /stopall · /anreg · /reg — призыв\n"
    "/invite · /zazyvala · /rules · /setrules · /setwelcome · /role · /diag\n\n"
    "Наказание за спам (удалить/пред/мут/бан) — панель → 🛡 Модерация.\n"
    "Исключения из стоп-слов — панель → 🚫 Стоп-слова → ⚪ Исключения."
)

GROUPADMIN_HELP = (
    "🛡 Я слежу за порядком в этой группе.\n\n"
    "Быстрые команды (ответом на сообщение): /ban /kick /mute 30m /warn /block /info\n"
    "Также: /warns /purge /stats /top /all /rules /invite /diag\n"
    "Участникам: /report — пожаловаться, /me — мой статус, /anreg — не звать в /all\n\n"
    "Все настройки (фильтры, капча, приветствие, автоответы с медиа, наказание за спам, "
    "исключения из стоп-слов) — в ЛС бота: /panel"
)

# ───────────────────────────────────────────────────────────────────────────
#  ОБРАБОТКА КНОПОК ПАНЕЛИ
# ───────────────────────────────────────────────────────────────────────────


async def handle_allstop_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "all"):
        return await query.answer("Недостаточно прав", show_alert=True)
    if _all_active.get(chat.id):
        _all_active[chat.id] = False
        return await query.answer("⏹ Останавливаю призыв")
    return await query.answer("Призыв уже завершён")


_MANAGER_CB = ("m:global", "m:access", "m:approve", "m:promo", "m:sched",
               "pr:", "pto:", "dmto:", "sp:", "spg:", "sptgl:", "spdel:",
               "dm:", "apt:", "appr:", "add:gword", "add:gbid", "add:gbname",
               "dgw:", "dgbid:", "dgbname:", "bk:full", "tz:", "pick:defaults")


async def _render_menu(query, context, key: str):
    """Показ раздела панели по ключу m:*."""
    cfg = panel_cfg_view(context)
    label = panel_target_label(context)
    if key == "m:main":
        return await safe_edit(query, status_text(context), main_menu_kb(context))
    if key == "m:pick":
        user_id = context.user_data.get("_uid", 0)
        if is_manager(user_id):
            groups = list(CONFIG.get("groups", {}).items())
        else:
            groups = await user_admin_groups(context, user_id)
        return await safe_edit(query, "📂 Выбери группу для настройки:\n(📂 — у группы индивидуальные настройки)",
                               pick_kb(groups, is_manager(user_id)))
    views = {
        "m:quick": ("⚡ Быстрые тумблеры · " + label, quick_kb(cfg)),
        "m:toggles": ("🧩 Фильтры · " + label + "\n🟢 включено · 🔴 выключено", toggles_kb(cfg)),
        "m:words": (words_menu_text(cfg, label), words_kb(cfg)),
        "m:whitewords": (whitewords_menu_text(cfg, label), whitewords_kb(cfg)),
        "m:words2": (words2_menu_text(cfg, label), words2_kb(cfg)),
        "m:links": (links_menu_text(cfg, label), links_kb(cfg)),
        "m:flood": ("🌊 Антифлуд · " + label + "\nСлишком часто пишет → мут.", flood_kb(cfg)),
        "m:mod": (mod_menu_text(cfg, label), mod_kb(cfg)),
        "m:media": (media_menu_text(cfg, label), media_kb(cfg)),
        "m:night": (night_menu_text(cfg, label), night_kb(cfg)),
        "m:triggers": (triggers_menu_text(cfg, label), triggers_kb(cfg)),
        "m:welcome": (welcome_menu_text(cfg, label), welcome_kb(cfg)),
        "m:captcha": (captcha_menu_text(cfg, label), captcha_kb(cfg)),
        "m:rules": (rules_menu_text(cfg, label), rules_kb()),
        "m:blacklist": (blacklist_menu_text(cfg, label), blacklist_kb(cfg)),
        "m:antiraid": (antiraid_menu_text(cfg, label), antiraid_kb(cfg)),
        "m:antinuke": (antinuke_menu_text(cfg, label), antinuke_kb(cfg)),
        "m:roles": (roles_menu_text(cfg, label), roles_kb(cfg)),
        "m:staff": (staff_menu_text(cfg, label), staff_kb(cfg)),
        "m:cmdperms": (cmdperms_menu_text(label), cmdperms_kb(cfg)),
        "m:lang": ("🗣 Язык сообщений для новичков · " + label, lang_kb(cfg)),
        "m:recurring": (recurring_menu_text(cfg, label), recurring_kb(cfg)),
        "m:other": (other_menu_text(context), other_kb(context)),
        "m:backup": (backup_menu_text(context), backup_kb(context)),
        "m:global": (global_menu_text(), global_kb()),
        "m:access": (access_menu_text(), access_kb()),
        "m:approve": (approve_menu_text(), approve_kb()),
        "m:promo": (promo_menu_text(), promo_kb()),
        "m:sched": (sched_menu_text(), sched_kb()),
        "m:add": (add_help_text(), InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="m:main")]])),
        "m:about": (about_text(), InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data="m:main")]])),
    }
    if key in views:
        text, kb = views[key]
        return await safe_edit(query, text, kb)
    return await safe_edit(query, status_text(context), main_menu_kb(context))


def _ask(context, state: str):
    context.user_data["await"] = state


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    data = query.data or ""
    if data == "noop":
        return await query.answer()
    context.user_data["_uid"] = user.id
    manager = is_manager(user.id)

    if not manager and any(data.startswith(p) for p in _MANAGER_CB):
        return await query.answer("Это раздел владельца бота", show_alert=True)

    # ── допуск групп (кнопки приходят и из уведомлений в ЛС) ──
    if data.startswith("appr:"):
        try:
            _, verdict, cid = data.split(":", 2)
            cid = int(cid)
        except ValueError:
            return await query.answer()
        ap = CONFIG.setdefault("approved_chats", [])
        title = CONFIG.get("groups", {}).get(str(cid), str(cid))
        if verdict == "ok":
            if cid not in ap:
                ap.append(cid)
            save_config(force=True)
            try:
                await context.bot.send_message(cid, "✅ Группа одобрена — я включился. Настройки: /panel в ЛС.")
            except Exception:  # noqa: BLE001
                pass
            note = f"✅ «{title}» одобрена."
        else:
            if cid in ap:
                ap.remove(cid)
                save_config(force=True)
                note = f"⛔ Допуск «{title}» отозван."
            else:
                note = f"«{title}» остаётся без допуска."
        if (query.message and query.message.chat and query.message.chat.type == "private"
                and data and query.message.reply_markup
                and any(b.callback_data and b.callback_data.startswith("m:")
                        for row in query.message.reply_markup.inline_keyboard for b in row)):
            await query.answer(note)
            return await _render_menu(query, context, "m:approve")
        try:
            await query.edit_message_text((query.message.text or "") + f"\n\n➡️ {note}")
        except Exception:  # noqa: BLE001
            pass
        return await query.answer(note[:190])

    # ── доступ к панели ──
    if not manager:
        groups = await user_admin_groups(context, user.id)
        if not groups:
            return await query.answer("Ты не администратор ни одной моей группы", show_alert=True)
        allowed = {str(cid) for cid, _ in groups}
        tgt = context.user_data.get("cfg_target")
        if not tgt or tgt == "defaults" or str(tgt) not in allowed:
            context.user_data["cfg_target"] = groups[0][0]
    else:
        if not context.user_data.get("cfg_target"):
            gs = list(CONFIG.get("groups", {}).keys())
            context.user_data["cfg_target"] = gs[0] if gs else "defaults"

    label = panel_target_label(context)

    # ── выбор группы ──
    if data.startswith("pick:"):
        tgt = data[5:]
        if tgt != "defaults":
            if not manager and str(tgt) not in {str(c) for c, _ in await user_admin_groups(context, user.id)}:
                return await query.answer("Не твоя группа", show_alert=True)
        context.user_data["cfg_target"] = tgt
        await query.answer("Выбрано")
        return await _render_menu(query, context, "m:main")

    # ── навигация ──
    if data.startswith("m:"):
        return await _render_menu(query, context, data)

    # ── тумблеры ──
    if data.startswith(("q:", "t:", "t2:")):
        key = data.split(":", 1)[1]
        wcfg = panel_cfg(context)
        wcfg["enabled"][key] = not wcfg["enabled"].get(key)
        save_config()
        back = {"q": "m:quick", "t": "m:toggles",
                "t2": "m:words2" if key == "words2" else "m:flood"}[data.split(":", 1)[0]]
        return await _render_menu(query, context, back)

    # ── ожидание текстового ввода ──
    prompts = {
        "add:word": ("word", f"Пришли стоп-слова для «{label}» через запятую.\n"
                             "Синтаксис: слово (точно), слово*, *слово, *слово*.\n(или /cancel)"),
        "add:word2": ("word2", f"Пришли слова ВТОРОГО списка для «{label}» через запятую. (или /cancel)"),
        "add:wword": ("wword", f"Пришли слова-исключения для «{label}» через запятую. (или /cancel)"),
        "add:link": ("link", f"Пришли спам-домены для «{label}» через запятую, без http://. (или /cancel)"),
        "add:trigger": ("trigger", "Формат: ключ - ответ\nНесколько ключей: цена,прайс - смотри закреп\n"
                                   "Работает {рандомизация|вариантов}. (или /cancel)"),
        "add:blid": ("blid", "Пришли ID пользователей через запятую — они получат бан при входе/сообщении. (или /cancel)"),
        "add:blname": ("blname", "Пришли подстроки имени через запятую (ловится в имени/фамилии/юзернейме). (или /cancel)"),
        "add:gword": ("gword", "Пришли ГЛОБАЛЬНЫЕ стоп-слова через запятую (для всех групп). (или /cancel)"),
        "add:gbid": ("gbid", "Пришли ID для ГЛОБАЛЬНОГО чёрного списка через запятую. (или /cancel)"),
        "add:gbname": ("gbname", "Пришли подстроки имени для ГЛОБАЛЬНОГО ЧС через запятую. (или /cancel)"),
        "add:role": ("rolenew", "Название новой роли одним словом (например: Модератор). (или /cancel)"),
        "rec:add": ("recurring", "Формат: минуты - текст\nНапример: 120 - Не забывайте про /rules! (или /cancel)"),
        "ru:edit": ("rules", f"Пришли новый текст правил для «{label}». (или /cancel)"),
        "wl:edit": ("welcome", "Пришли текст приветствия. Плейсхолдеры: {name}, {mention}, {chat}. (или /cancel)"),
        "wl:btns": ("welcome_btns", "Кнопки: «Текст - https://ссылка» по одной на строку, ряд — через «;».\n"
                                    "Пришли «-» чтобы убрать кнопки. (или /cancel)"),
        "st:set": ("staff", "Пришли ID staff-группы (проще: выполни /setstaff в самой staff-группе). (или /cancel)"),
        "dm:add": ("mgr", "Пришли ID нового менеджера (узнать свой: /userid). (или /cancel)"),
        "pr:content": ("promo_content", "Пришли контент промо: текст ИЛИ фото/видео/гиф с подписью. "
                                        "Форматирование и {спинтакс|рандом} сохранятся. (или /cancel)"),
        "pr:btns": ("promo_btns", "Кнопки промо: «Текст - https://ссылка» по строке, ряд — через «;». "
                                  "«-» — убрать. (или /cancel)"),
        "pr:invitetext": ("invitetext", "Пришли текст «зазывалы» для /zazyvala. (или /cancel)"),
        "pr:bcast": ("bcast", "Пришли сообщение для рассылки во ВСЕ группы: текст или фото с подписью. (или /cancel)"),
        "sp:new": ("sp_time", "🗓 Новый пост · Шаг 1 из 3\nВремя и дни: «19:30 пн,чт» или «09:00» (ежедневно). (или /cancel)"),
    }
    if data in prompts:
        state, prompt = prompts[data]
        if data == "sp:new":
            context.user_data["sp_draft"] = {}
        _ask(context, state)
        return await safe_edit(query, prompt, None)

    if data == "add:trigmedia":
        context.user_data["trig_draft"] = {}
        _ask(context, "trig_keys")
        return await safe_edit(query, "🖼 Автоответ с медиа · Шаг 1 из 3\n\n"
                                      f"Пришли ключевые слова для «{label}» через запятую "
                                      "(можно со звёздочкой: банан*). (или /cancel)", None)

    # ── удаления по индексу ──
    wcfg = panel_cfg(context)
    del_map = {
        "dw:": ("stop_words", "m:words"), "dw2:": ("stop_words2", "m:words2"),
        "dww:": ("white_words", "m:whitewords"), "dl:": ("spam_links", "m:links"),
    }
    for pref, (lkey, back) in del_map.items():
        if data.startswith(pref):
            lst = sorted(wcfg.get(lkey, []))
            i = int(data[len(pref):])
            if 0 <= i < len(lst):
                try:
                    wcfg[lkey].remove(lst[i])
                    save_config()
                except ValueError:
                    pass
            return await _render_menu(query, context, back)
    if data.startswith("dt:"):
        keys = sorted(wcfg.get("triggers", {}))
        i = int(data[3:])
        if 0 <= i < len(keys):
            wcfg["triggers"].pop(keys[i], None)
            save_config()
        return await _render_menu(query, context, "m:triggers")
    if data.startswith("dblid:") or data.startswith("dblname:"):
        bl = wcfg.setdefault("blacklist", {"ids": [], "names": []})
        kind = "ids" if data.startswith("dblid:") else "names"
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(bl.get(kind, [])):
            bl[kind].pop(i)
            save_config()
        return await _render_menu(query, context, "m:blacklist")
    if data.startswith(("dgw:", "dgbid:", "dgbname:")):
        if data.startswith("dgw:"):
            lst = sorted(CONFIG.get("global_stop_words", []))
            i = int(data[4:])
            if 0 <= i < len(lst):
                CONFIG["global_stop_words"].remove(lst[i])
        else:
            gb = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
            kind = "ids" if data.startswith("dgbid:") else "names"
            i = int(data.split(":", 1)[1])
            if 0 <= i < len(gb.get(kind, [])):
                gb[kind].pop(i)
        save_config(force=True)
        return await _render_menu(query, context, "m:global")

    # ── циклы значений и переключатели ──
    if data == "mode:trig":
        wcfg["trigger_match"] = "contains" if wcfg.get("trigger_match", "word") == "word" else "word"
        save_config()
        return await _render_menu(query, context, "m:triggers")
    if data.startswith("fl:"):
        f = wcfg["flood"]
        k = data[3:]
        cyc = {"limit": [3, 5, 7, 10, 15], "period": [5, 10, 15, 30, 60],
               "mute": [60, 300, 900, 3600, 86400]}[k]
        f[k] = _cycle(cyc, f.get(k))
        save_config()
        return await _render_menu(query, context, "m:flood")
    if data.startswith("md:"):
        m = wcfg["moderation"]
        k = data[3:]
        if k == "limit":
            m["warn_limit"] = _cycle([2, 3, 4, 5], m.get("warn_limit"))
        elif k == "act":
            m["warn_action"] = "ban" if m.get("warn_action") != "ban" else "mute"
        elif k == "mute":
            m["warn_mute"] = _cycle([600, 1800, 3600, 10800, 86400], m.get("warn_mute"))
        elif k == "expire":
            m["warn_expire_days"] = _cycle([0, 3, 7, 14, 30], m.get("warn_expire_days", 0))
        elif k == "spamact":
            wcfg["spam_action"] = _cycle(_ACT_CYCLE, wcfg.get("spam_action", "delete"))
        elif k == "notif":
            m["notify_delete"] = not m.get("notify_delete")
        elif k == "log":
            m["log_actions"] = not m.get("log_actions")
        elif k == "adm":
            m["mod_admins_only"] = not m.get("mod_admins_only")
        save_config()
        return await _render_menu(query, context, "m:mod")
    if data == "w2act":
        wcfg["stop_words2_action"] = _cycle(_ACT_CYCLE, wcfg.get("stop_words2_action", "ban"))
        save_config()
        return await _render_menu(query, context, "m:words2")
    if data == "w2prof":
        wcfg["stop_words2_profile"] = not wcfg.get("stop_words2_profile", True)
        save_config()
        return await _render_menu(query, context, "m:words2")
    if data == "mact":
        wcfg["media_action"] = _cycle(_ACT_CYCLE, wcfg.get("media_action", "delete"))
        save_config()
        return await _render_menu(query, context, "m:media")
    if data.startswith("mb:"):
        k = data[3:]
        wcfg.setdefault("media_block", {})[k] = not wcfg["media_block"].get(k)
        save_config()
        return await _render_menu(query, context, "m:media")
    if data.startswith("nm:"):
        n = wcfg["night"]
        k = data[3:]
        if k == "tgl":
            n["enabled"] = not n.get("enabled")
        elif k in ("start", "end"):
            n[k] = (int(n.get(k, 0)) + 1) % 24
        elif k == "tz":
            n["tz"] = int(n.get("tz", 0)) + 1 if int(n.get("tz", 0)) < 12 else -11
        save_config()
        return await _render_menu(query, context, "m:night")
    if data.startswith("wl:"):
        w = wcfg["welcome"]
        k = data[3:]
        if k == "tgl":
            w["enabled"] = not w.get("enabled")
        elif k == "del":
            w["delete_after"] = _cycle([0, 30, 60, 120, 300], int(w.get("delete_after", 0) or 0))
        save_config()
        return await _render_menu(query, context, "m:welcome")
    if data == "ji:cycle":
        wcfg["show_join_id"] = _cycle(["off", "all", "admins"], wcfg.get("show_join_id", "off"))
        save_config()
        return await _render_menu(query, context, "m:welcome")
    if data.startswith("cp:"):
        c = wcfg["captcha"]
        k = data[3:]
        if k == "tgl":
            c["enabled"] = not c.get("enabled")
        elif k == "timeout":
            c["timeout"] = _cycle([60, 120, 180, 300], c.get("timeout", 120))
        elif k == "action":
            c["action"] = "mute" if c.get("action", "kick") == "kick" else "kick"
        elif k == "via":
            c["via_request"] = not c.get("via_request", True)
        save_config()
        return await _render_menu(query, context, "m:captcha")
    if data.startswith("ar:"):
        a = wcfg["antiraid"]
        k = data[3:]
        if k == "tgl":
            a["enabled"] = not a.get("enabled")
        elif k == "joins":
            a["joins"] = _cycle([5, 8, 12, 20], a.get("joins", 8))
        elif k == "window":
            a["window"] = _cycle([30, 60, 120], a.get("window", 60))
        elif k == "lock":
            a["lock_min"] = _cycle([5, 10, 30, 60], a.get("lock_min", 10))
        save_config()
        return await _render_menu(query, context, "m:antiraid")
    if data.startswith("an:"):
        a = wcfg["antinuke"]
        k = data[3:]
        if k == "tgl":
            a["enabled"] = not a.get("enabled")
        elif k == "thresh":
            a["ban_threshold"] = _cycle([3, 5, 8, 12], a.get("ban_threshold", 5))
        elif k == "act":
            a["action"] = "ban" if a.get("action") != "ban" else "stop"
        save_config()
        return await _render_menu(query, context, "m:antinuke")
    if data.startswith("perm:"):
        k = data[5:]
        levels = CMD_LEVELS.get(k, ["admins", "owner"])
        cp = wcfg.setdefault("cmd_perms", {})
        cp[k] = _cycle(levels, cp.get(k, CMD_DEFAULT.get(k, "admins")))
        save_config()
        return await _render_menu(query, context, "m:cmdperms")
    if data.startswith("lang:"):
        code = data[5:]
        if code in LANGS:
            wcfg["lang"] = code
            save_config()
        return await _render_menu(query, context, "m:lang")
    if data.startswith("rectgl:") or data.startswith("recdel:"):
        items = wcfg.setdefault("recurring", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(items):
            if data.startswith("rectgl:"):
                items[i]["enabled"] = not items[i].get("enabled")
            else:
                items.pop(i)
            save_config()
        return await _render_menu(query, context, "m:recurring")
    if data == "st:clear":
        wcfg["staff_group"] = 0
        save_config()
        return await _render_menu(query, context, "m:staff")

    # ── роли: карточка/права/участники ──
    if data.startswith("rl:"):
        name = data[3:]
        context.user_data["role_name"] = name
        return await safe_edit(query, f"🎖 Роль «{name}» · {label}\n\nОтметь права; участников "
                                      f"добавляй по ID или командой /role {name} в чате.",
                               role_detail_kb(panel_cfg_view(context), name))
    if data.startswith("rp:"):
        _, name, perm = data.split(":", 2)
        r = wcfg.setdefault("roles", {}).setdefault(name, {"perms": [], "members": []})
        if perm in r["perms"]:
            r["perms"].remove(perm)
        else:
            r["perms"].append(perm)
        save_config()
        return await safe_edit(query, f"🎖 Роль «{name}» · {label}", role_detail_kb(wcfg, name))
    if data.startswith("rmadd:"):
        context.user_data["role_name"] = data[6:]
        _ask(context, "rolemember")
        return await safe_edit(query, f"Пришли ID участника для роли «{data[6:]}». (или /cancel)", None)
    if data.startswith("rmx:"):
        _, name, uid = data.split(":", 2)
        r = wcfg.setdefault("roles", {}).get(name)
        if r and int(uid) in r.get("members", []):
            r["members"].remove(int(uid))
            save_config()
        return await safe_edit(query, f"🎖 Роль «{name}» · {label}", role_detail_kb(wcfg, name))
    if data.startswith("rdel:"):
        wcfg.get("roles", {}).pop(data[5:], None)
        save_config()
        return await _render_menu(query, context, "m:roles")

    # ── сброс к шаблону ──
    if data == "resetchat:yes":
        tgt = context.user_data.get("cfg_target")
        if tgt and tgt != "defaults":
            CONFIG.get("chats", {}).pop(str(tgt), None)
            save_config(force=True)
        await query.answer("Сброшено")
        return await _render_menu(query, context, "m:main")
    if data == "resetchat":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Да, сбросить", callback_data="resetchat:yes"),
                                    InlineKeyboardButton("⬅️ Отмена", callback_data="m:other")]])
        return await safe_edit(query, f"Сбросить ВСЕ настройки «{label}» к общему шаблону?\n"
                                      "Отменить будет нельзя (при сомнениях сначала сделай 🗄 бэкап).", kb)
    if data == "tz:cycle":
        CONFIG["post_tz"] = int(CONFIG.get("post_tz", 0)) + 1 if int(CONFIG.get("post_tz", 0)) < 12 else -11
        save_config()
        return await _render_menu(query, context, "m:other")

    # ── менеджеры ──
    if data.startswith("dm:del:"):
        uid = int(data[7:])
        if uid in CONFIG.get("managers", []):
            CONFIG["managers"].remove(uid)
            save_config(force=True)
        return await _render_menu(query, context, "m:access")
    if data == "apt:req":
        CONFIG["require_approval"] = not CONFIG.get("require_approval", True)
        save_config(force=True)
        return await _render_menu(query, context, "m:approve")

    # ── промо/посты/рассылки (владелец) ──
    if data == "pr:tgl":
        CONFIG["promo"]["enabled"] = not CONFIG["promo"].get("enabled")
        save_config()
        return await _render_menu(query, context, "m:promo")
    if data == "pr:int":
        CONFIG["promo"]["interval"] = _cycle([1800, 3600, 7200, 14400, 86400],
                                             int(CONFIG["promo"].get("interval", 3600)))
        save_config()
        return await _render_menu(query, context, "m:promo")
    if data == "pr:pin":
        CONFIG["promo"]["pin"] = not CONFIG["promo"].get("pin")
        save_config()
        return await _render_menu(query, context, "m:promo")
    if data == "pr:test":
        p = CONFIG["promo"]
        try:
            await _send_one(context, user.id, p)
            await query.answer("Отправил тест в ЛС")
        except Exception as e:  # noqa: BLE001
            await query.answer(f"Не вышло: {e}"[:190], show_alert=True)
        return
    if data == "pr:post":
        return await safe_edit(query, "📮 В какую группу опубликовать пост?", post_groups_kb("pto"))
    if data == "pr:dm":
        return await safe_edit(query, "💌 Кому в ЛС? Подписчики — прошедшие капчу-заявку.",
                               post_groups_kb("dmto"))
    if data.startswith("pto:"):
        context.user_data["post_chat"] = data[4:]
        _ask(context, "post")
        title = CONFIG.get("groups", {}).get(data[4:], data[4:])
        return await safe_edit(query, f"Пришли пост для «{title}»: текст ИЛИ медиа с подписью "
                                      "(форматирование сохранится). (или /cancel)", None)
    if data.startswith("dmto:"):
        context.user_data["dm_chat"] = data[5:]
        _ask(context, "dmcast")
        who = "всем подписчикам" if data[5:] == "all" else f"подписчикам «{CONFIG.get('groups', {}).get(data[5:], data[5:])}»"
        return await safe_edit(query, f"Пришли сообщение для рассылки {who}: текст или медиа. (или /cancel)", None)
    if data.startswith("sptgl:"):
        p = _find_post(data[6:])
        if p:
            p["enabled"] = not p.get("enabled", True)
            save_config()
        return await _render_menu(query, context, "m:sched")
    if data.startswith("spdel:"):
        CONFIG["scheduled_posts"] = [p for p in CONFIG.get("scheduled_posts", []) if p.get("id") != data[6:]]
        save_config(force=True)
        return await _render_menu(query, context, "m:sched")
    if data.startswith("spg:"):
        _, pid, val = data.split(":", 2)
        p = _find_post(pid)
        if p:
            if val == "all":
                p["chats"] = "all"
            else:
                ch = p.get("chats")
                ch = [] if ch == "all" else [str(c) for c in (ch or [])]
                if val in ch:
                    ch.remove(val)
                else:
                    ch.append(val)
                p["chats"] = ch or "all"
            save_config()
        return await safe_edit(query, "🗓 Куда публиковать этот пост?", sched_groups_kb(pid))

    # ── бэкапы ──
    if data == "bk:full":
        await send_backup(context, user.id)
        return await query.answer("Файл отправлен")
    if data == "bk:chat":
        tgt = context.user_data.get("cfg_target")
        if not tgt or tgt == "defaults":
            return await query.answer("Сначала выбери группу", show_alert=True)
        await send_chat_backup(context, user.id, tgt)
        return await query.answer("Файл отправлен")

    await query.answer()

# ───────────────────────────────────────────────────────────────────────────
#  ЧЁРНЫЙ СПИСОК ИЗ ЧАТА
# ───────────────────────────────────────────────────────────────────────────


async def cmd_block(update: Update, context):
    """Добавить в ЧС группы (по реплаю/ID) и сразу забанить."""
    g = await _guard(update, context, "ban")
    if not g:
        return
    tid, tname = g
    chat = update.effective_chat
    bl = chat_cfg_writable(chat.id).setdefault("blacklist", {"ids": [], "names": []})
    if tid not in bl["ids"]:
        bl["ids"].append(tid)
        save_config(force=True)
    try:
        await context.bot.ban_chat_member(chat.id, tid)
        bump(chat.id, "banned")
    except Exception as e:  # noqa: BLE001
        log.debug("block ban: %s", e)
    await reply_tidy(update, context, f"⛔ {tname} в чёрном списке группы: бан сейчас и при любой попытке вернуться.")
    await log_action(context, chat.id, f"⛔ ЧС: {tname} (by {_actor_name(update)})")


async def cmd_unblock(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban", update=update):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Укажи ID или ответь на сообщение.")
    bl = chat_cfg_writable(chat.id).setdefault("blacklist", {"ids": [], "names": []})
    if tid in bl["ids"]:
        bl["ids"].remove(tid)
        save_config(force=True)
    try:
        await context.bot.unban_chat_member(chat.id, tid, only_if_banned=True)
    except Exception:  # noqa: BLE001
        pass
    await reply_tidy(update, context, f"✅ {tname} убран из чёрного списка и разбанен.")

# ───────────────────────────────────────────────────────────────────────────
#  ЛИЧНЫЕ КОМАНДЫ
# ───────────────────────────────────────────────────────────────────────────


def add_group_button() -> InlineKeyboardButton:
    uname = _state.get("bot_username", "")
    return InlineKeyboardButton("➕ Добавить бота в группу",
                                url=f"https://t.me/{uname}?startgroup=true")


async def _ensure_panel_target(context, user_id: int) -> bool:
    """Выставить cfg_target по правам. False — пользователю нечем управлять."""
    tgt = context.user_data.get("cfg_target")
    if is_manager(user_id):
        if not tgt:
            gs = list(CONFIG.get("groups", {}).keys())
            context.user_data["cfg_target"] = gs[0] if gs else "defaults"
        return True
    groups = await user_admin_groups(context, user_id)
    if not groups:
        return False
    allowed = {str(c) for c, _ in groups}
    if not tgt or tgt == "defaults" or str(tgt) not in allowed:
        context.user_data["cfg_target"] = groups[0][0]
    return True


async def cmd_start(update: Update, context):
    user = update.effective_user
    context.user_data["_uid"] = user.id
    kb = InlineKeyboardMarkup([[add_group_button()],
                               [InlineKeyboardButton("⚙️ Панель управления", callback_data="m:main")]])
    await update.effective_message.reply_text(
        f"👋 Привет, {user.first_name or 'друг'}!\n\n"
        "Я — Channel Guard: антиспам, модерация, капча, приветствия, автоответы, "
        "промо и посты по расписанию для твоих групп.\n\n"
        "1️⃣ Добавь меня в группу и дай права администратора\n"
        "2️⃣ Открой /panel и настрой под себя\n\n"
        "Помощь — /help · тариф — /pro",
        reply_markup=kb)


async def cmd_panel(update: Update, context):
    user = update.effective_user
    context.user_data["_uid"] = user.id
    if not await _ensure_panel_target(context, user.id):
        return await update.effective_message.reply_text(
            "Панель доступна владельцу бота и администраторам групп, где я работаю.\n"
            "Добавь меня в свою группу с правами админа — и /panel откроется.",
            reply_markup=InlineKeyboardMarkup([[add_group_button()]]))
    await update.effective_message.reply_text(status_text(context), reply_markup=main_menu_kb(context))


async def cmd_status(update: Update, context):
    user = update.effective_user
    context.user_data["_uid"] = user.id
    if not await _ensure_panel_target(context, user.id):
        return await update.effective_message.reply_text("Ты пока не управляешь ни одной моей группой.")
    tgt = context.user_data.get("cfg_target")
    if not tgt or tgt == "defaults":
        return await update.effective_message.reply_text("Группа не выбрана — открой /panel → 📂.")
    total, today, week, _top = _msg_stats_summary(tgt)
    s = _stats_chat(tgt).get("mod", {})
    cfg = chat_cfg(int(tgt))
    on = sum(1 for k, _ in FEATURES if cfg["enabled"].get(k))
    await update.effective_message.reply_text(
        f"📊 {panel_target_label(context)}\n"
        f"Доступ: {access_status(int(tgt))}\n"
        f"Фильтров включено: {on}/{len(FEATURES)} · за спам: {_ACT_RU.get(cfg.get('spam_action', 'delete'))}\n"
        f"Сообщений: сегодня {today} · за неделю {week} · всего {total}\n"
        f"Модерация: удалено {s.get('deleted', 0)}, предов {s.get('warns', 0)}, "
        f"мутов {s.get('muted', 0) + s.get('flood_muted', 0)}, банов {s.get('banned', 0)}\n\n"
        f"Подробности и настройки — /panel")


async def cmd_help(update: Update, context):
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        return await reply_tidy(update, context, GROUPADMIN_HELP, seconds=30)
    await update.effective_message.reply_text(HELP_TEXT)


async def cmd_about(update: Update, context):
    await update.effective_message.reply_text(about_text())


async def cmd_cancel(update: Update, context):
    for k in ("await", "trig_draft", "sp_draft", "role_name", "post_chat", "dm_chat"):
        context.user_data.pop(k, None)
    await update.effective_message.reply_text("Отменено. Панель — /panel.")


def _finalize_sched_post(context, buttons=None):
    d = context.user_data.pop("sp_draft", {})
    context.user_data.pop("await", None)
    if not d.get("time") or not d.get("type"):
        return None
    post = {"id": _new_post_id(), "enabled": True, "chats": "all",
            "time": d["time"], "days": d.get("days", []),
            "type": d.get("type", "text"), "text": d.get("text", ""),
            "html": d.get("html", False), "file_id": d.get("file_id"),
            "buttons": buttons or []}
    CONFIG.setdefault("scheduled_posts", []).append(post)
    save_config(force=True)
    return post["id"]


def _save_trigger_draft(context):
    d = context.user_data.pop("trig_draft", {})
    context.user_data.pop("await", None)
    keys = d.pop("keys", [])
    cfg = panel_cfg(context)
    for k in keys:
        cfg.setdefault("triggers", {})[k] = copy.deepcopy(d)
    save_config()
    return keys, d, cfg


async def cmd_skip(update: Update, context):
    """Пропустить шаг кнопок в мастерах (то же, что прислать «-»)."""
    awaiting = context.user_data.get("await")
    if awaiting == "trig_btns":
        keys, val, cfg = _save_trigger_draft(context)
        if keys:
            return await update.effective_message.reply_text(
                f"✅ Автоответ сохранён для: {', '.join(keys)} ({panel_target_label(context)})",
                reply_markup=triggers_kb(cfg))
    elif awaiting == "sp_btns":
        pid = _finalize_sched_post(context)
        if pid:
            return await update.effective_message.reply_text(
                "✅ Пост создан. Куда публиковать?", reply_markup=sched_groups_kb(pid))
    elif awaiting == "promo_btns":
        context.user_data.pop("await", None)
        CONFIG["promo"]["buttons"] = []
        save_config()
        return await update.effective_message.reply_text("Кнопки промо убраны.", reply_markup=promo_kb())
    elif awaiting == "welcome_btns":
        context.user_data.pop("await", None)
        cfg = panel_cfg(context)
        cfg["welcome"]["buttons"] = []
        save_config()
        return await update.effective_message.reply_text("Кнопки приветствия убраны.",
                                                         reply_markup=welcome_kb(cfg))
    await update.effective_message.reply_text("Сейчас нечего пропускать. Панель — /panel.")


async def cmd_userid(update: Update, context):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return await reply_tidy(update, context, f"🆔 {mention(u)}: {u.id}", seconds=20)
    chat = update.effective_chat
    extra = f"\n🆔 Этой группы: {chat.id}" if chat.type in ("group", "supergroup") else ""
    await reply_tidy(update, context, f"🆔 Твой ID: {update.effective_user.id}{extra}", seconds=20)


async def cmd_setwelcome(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("Выполни в группе (или задай в /panel → 👋).")
    if not (is_manager(user.id) or await can_open_settings(context, chat.id, user.id)):
        return await _deny(update)
    text = _args_text(update)
    if not text:
        return await update.effective_message.reply_text(
            "Формат: /setwelcome текст ({name}, {mention}, {chat}). Кнопки — в панели.")
    w = chat_cfg_writable(chat.id)["welcome"]
    w["text"] = text
    w["enabled"] = True
    save_config()
    await reply_tidy(update, context, "👋 Приветствие сохранено и включено.")


async def cmd_grant(update: Update, context):
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Кому выдать доступ? Ответь на сообщение или укажи ID.")
    if tid not in CONFIG["managers"] and not is_owner(tid):
        CONFIG["managers"].append(tid)
        save_config(force=True)
    await update.effective_message.reply_text(f"🔑 {tname} теперь менеджер бота (управление всеми группами).")
    try:
        await context.bot.send_message(tid, "🔑 Тебе выдали доступ к управлению ботом. Панель — /panel.")
    except Exception:  # noqa: BLE001
        pass


async def cmd_revoke(update: Update, context):
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("У кого забрать доступ? Ответь или укажи ID.")
    if tid in CONFIG["managers"]:
        CONFIG["managers"].remove(tid)
        save_config(force=True)
        return await update.effective_message.reply_text(f"🔒 Доступ {tname} отозван.")
    await update.effective_message.reply_text("У него и не было доступа.")


async def cmd_managers(update: Update, context):
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    lines = ["👑 Владельцы: " + ", ".join(str(x) for x in sorted(ADMIN_IDS))]
    lines += [f"🔑 Менеджер: {m}" for m in CONFIG.get("managers", [])] or ["Менеджеров нет."]
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_settings_hint(update: Update, context):
    uname = _state.get("bot_username", "")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚙️ Открыть панель в ЛС",
                                                     url=f"https://t.me/{uname}?start=panel")]])
    await reply_tidy(update, context, "Все настройки — в личке бота: /panel", reply_markup=kb)

# ── контент-команды в ЛС (для выбранной в панели группы) ────────────────────


async def _content_cfg(update, context):
    """Право и конфиг для /add /addword /addlink и их списков."""
    user = update.effective_user
    context.user_data["_uid"] = user.id
    if not await _ensure_panel_target(context, user.id):
        await update.effective_message.reply_text("Сначала стань админом группы, где я работаю. /panel")
        return None
    tgt = context.user_data.get("cfg_target")
    if not await can_edit_target(context, user.id, tgt):
        await update.effective_message.reply_text("Нет доступа к выбранной группе — выбери свою в /panel → 📂.")
        return None
    return panel_cfg(context)


async def cmd_add(update: Update, context):
    cfg = await _content_cfg(update, context)
    if cfg is None:
        return
    raw = _args_text(update)
    if " - " not in raw:
        return await update.effective_message.reply_text(
            "Формат: /add ключ - ответ\nНесколько ключей: /add цена,прайс - смотри закреп\n"
            "Ответ с медиа/кнопками — /panel → 💬 Автоответы → 🖼.")
    keys_part, answer = raw.split(" - ", 1)
    keys = _csv(keys_part)
    answer = answer.strip()
    if not keys or not answer:
        return await update.effective_message.reply_text("Не понял. Формат: /add ключ - ответ")
    for k in keys:
        cfg.setdefault("triggers", {})[k] = answer
    save_config()
    await update.effective_message.reply_text(
        f"✅ Автоответ для: {', '.join(keys)} ({panel_target_label(context)})")


async def cmd_del(update: Update, context):
    cfg = await _content_cfg(update, context)
    if cfg is None:
        return
    key = _args_text(update).strip().lower()
    if not key:
        return await update.effective_message.reply_text("Формат: /del ключ")
    if cfg.get("triggers", {}).pop(key, None) is not None:
        save_config()
        return await update.effective_message.reply_text(f"🗑 Автоответ «{key}» удалён.")
    await update.effective_message.reply_text("Такого ключа нет. Список — /list")


async def cmd_list(update: Update, context):
    cfg = await _content_cfg(update, context)
    if cfg is None:
        return
    trg = cfg.get("triggers", {})
    if not trg:
        return await update.effective_message.reply_text("Автоответов пока нет. Добавить: /add ключ - ответ")
    lines = [f"💬 Автоответы ({panel_target_label(context)}):"]
    for k in sorted(trg)[:60]:
        lines.append(f"• {k} → {_trig_preview(trg[k], 60)}")
    await update.effective_message.reply_text("\n".join(lines))


def _make_list_cmds(list_key: str, title: str, back_hint: str):
    async def _add(update: Update, context):
        cfg = await _content_cfg(update, context)
        if cfg is None:
            return
        words = _csv(_args_text(update))
        if not words:
            return await update.effective_message.reply_text(f"Формат: /{back_hint} слово1, слово2")
        added = _add_unique(cfg.setdefault(list_key, []), words)
        if added:
            save_config()
        await update.effective_message.reply_text(
            (f"✅ Добавлено ({len(added)}): {', '.join(added)}" if added else "Всё это уже в списке.")
            + f" ({panel_target_label(context)})")

    async def _del(update: Update, context):
        cfg = await _content_cfg(update, context)
        if cfg is None:
            return
        removed = []
        for w in _csv(_args_text(update)):
            if w in cfg.get(list_key, []):
                cfg[list_key].remove(w)
                removed.append(w)
        if removed:
            save_config()
        await update.effective_message.reply_text(
            f"🗑 Убрано: {', '.join(removed)}" if removed else "Ничего из этого в списке не нашёл.")

    async def _show(update: Update, context):
        cfg = await _content_cfg(update, context)
        if cfg is None:
            return
        items = sorted(cfg.get(list_key, []))
        await update.effective_message.reply_text(
            f"{title} ({len(items)}): " + (", ".join(items[:150]) or "— пусто —"))

    return _add, _del, _show


cmd_addword, cmd_delword, cmd_words = _make_list_cmds("stop_words", "🚫 Стоп-слова", "addword")
cmd_addlink, cmd_dellink, cmd_links = _make_list_cmds("spam_links", "🔗 Спам-домены", "addlink")

# ───────────────────────────────────────────────────────────────────────────
#  ПРИЁМ ТЕКСТА/МЕДИА/ФАЙЛОВ В ЛИЧКЕ (состояния мастеров)
# ───────────────────────────────────────────────────────────────────────────

_TARGET_STATES = {"word", "word2", "wword", "link", "trigger", "blid", "blname",
                  "welcome", "welcome_btns", "rules", "recurring", "rolenew",
                  "rolemember", "staff", "trig_keys", "trig_content", "trig_btns"}
_MANAGER_STATES = {"gword", "gbid", "gbname", "mgr", "promo_content", "promo_btns",
                   "invitetext", "bcast", "dmcast", "post", "sp_time", "sp_content", "sp_btns"}


async def _state_allowed(update, context, awaiting) -> bool:
    user = update.effective_user
    if awaiting in _MANAGER_STATES:
        if not is_manager(user.id):
            context.user_data.pop("await", None)
            return False
        return True
    if awaiting in _TARGET_STATES:
        tgt = context.user_data.get("cfg_target")
        if not await can_edit_target(context, user.id, tgt):
            context.user_data.pop("await", None)
            await update.effective_message.reply_text("Нет доступа к выбранной группе — /panel.")
            return False
    return True


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    text = (msg.text or "").strip()
    awaiting = context.user_data.pop("await", None)
    if not awaiting:
        return await msg.reply_text("Я на месте 🙂 Панель — /panel, помощь — /help.")
    if not await _state_allowed(update, context, awaiting):
        return
    cfg = panel_cfg(context)
    label = panel_target_label(context)

    if awaiting in ("word", "word2", "wword", "link"):
        key = {"word": "stop_words", "word2": "stop_words2",
               "wword": "white_words", "link": "spam_links"}[awaiting]
        kbf = {"word": words_kb, "word2": words2_kb, "wword": whitewords_kb, "link": links_kb}[awaiting]
        added = _add_unique(cfg.setdefault(key, []), _csv(text))
        if added:
            save_config()
        return await msg.reply_text(
            (f"✅ Добавлено ({len(added)}): {', '.join(added)}" if added else "Всё это уже в списке.")
            + f" ({label})", reply_markup=kbf(cfg))

    if awaiting == "trigger":
        if " - " not in text:
            _ask(context, "trigger")
            return await msg.reply_text("Формат: ключ - ответ (или /cancel)")
        keys_part, answer = text.split(" - ", 1)
        keys = _csv(keys_part)
        for k in keys:
            cfg.setdefault("triggers", {})[k] = answer.strip()
        save_config()
        return await msg.reply_text(f"✅ Автоответ для: {', '.join(keys)} ({label})",
                                    reply_markup=triggers_kb(cfg))

    if awaiting == "trig_keys":
        words = _csv(text)
        if not words:
            _ask(context, "trig_keys")
            return await msg.reply_text("Пусто. Пришли слова через запятую, или /cancel.")
        context.user_data["trig_draft"] = {"keys": words}
        _ask(context, "trig_content")
        return await msg.reply_text(
            "Шаг 2 из 3 · Пришли сам ответ: текст ИЛИ фото/видео/гиф/стикер/документ с подписью.\n"
            "Форматирование сохранится, работает {рандомизация|вариантов}.")

    if awaiting == "trig_content":
        d = context.user_data.get("trig_draft", {})
        content = _capture_post_content(msg)
        if not d.get("keys") or not content:
            _ask(context, "trig_content")
            return await msg.reply_text("Не понял ответ. Пришли текст или медиа, или /cancel.")
        d.update(content)
        _ask(context, "trig_btns")
        return await msg.reply_text(
            "Шаг 3 из 3 · Кнопки-ссылки? По одной на строку «Текст - https://ссылка», "
            "несколько в один ряд — через «;». Пришли «-», если без кнопок.")

    if awaiting == "trig_btns":
        d = context.user_data.get("trig_draft", {})
        if not d.get("keys"):
            return await msg.reply_text("Черновик потерялся — начни заново через /panel.")
        if text not in ("-", "—", "нет"):
            d["buttons"] = _parse_button_rows(text)
        keys, val, wcfg = _save_trigger_draft(context)
        return await msg.reply_text(
            f"✅ Автоответ сохранён для: {', '.join(keys)} — {_trig_preview(val, 40)} ({label})",
            reply_markup=triggers_kb(wcfg))

    if awaiting == "blid":
        bl = cfg.setdefault("blacklist", {"ids": [], "names": []})
        added = _add_unique(bl["ids"], [int(x) for x in _csv(text) if x.lstrip("-").isdigit()])
        save_config()
        return await msg.reply_text(f"⛔ В ЧС добавлено ID: {len(added)} ({label})",
                                    reply_markup=blacklist_kb(cfg))
    if awaiting == "blname":
        bl = cfg.setdefault("blacklist", {"ids": [], "names": []})
        added = _add_unique(bl["names"], _csv(text))
        save_config()
        return await msg.reply_text(f"⛔ В ЧС добавлено подстрок: {len(added)} ({label})",
                                    reply_markup=blacklist_kb(cfg))

    if awaiting == "welcome":
        cfg["welcome"]["text"] = text
        cfg["welcome"]["enabled"] = True
        save_config()
        return await msg.reply_text("👋 Приветствие сохранено и включено.", reply_markup=welcome_kb(cfg))
    if awaiting == "welcome_btns":
        cfg["welcome"]["buttons"] = [] if text in ("-", "—", "нет") else _parse_button_rows(text)
        save_config()
        return await msg.reply_text("🔘 Кнопки приветствия сохранены.", reply_markup=welcome_kb(cfg))

    if awaiting == "rules":
        cfg["rules"] = text
        save_config()
        return await msg.reply_text("📜 Правила сохранены.", reply_markup=rules_kb())

    if awaiting == "recurring":
        m = re.match(r"(\d+)\s*[-—]\s*(.+)", text, re.S)
        if not m:
            _ask(context, "recurring")
            return await msg.reply_text("Формат: минуты - текст (напр.: 120 - Читайте /rules). /cancel")
        interval = max(5, int(m.group(1)))
        cfg.setdefault("recurring", []).append({"text": m.group(2).strip(),
                                                "interval": interval, "enabled": True})
        save_config()
        return await msg.reply_text(f"🔁 Добавлено: каждые {interval} мин.", reply_markup=recurring_kb(cfg))

    if awaiting == "rolenew":
        name = text.split()[0][:20]
        cfg.setdefault("roles", {}).setdefault(name, {"perms": [], "members": []})
        save_config()
        return await msg.reply_text(f"🎖 Роль «{name}» создана · {label}\nОтметь права:",
                                    reply_markup=role_detail_kb(cfg, name))
    if awaiting == "rolemember":
        name = context.user_data.get("role_name")
        if not (name and text.lstrip("-").isdigit()):
            return await msg.reply_text("Нужен числовой ID. Заново — /panel → 🎖 Роли.")
        r = cfg.setdefault("roles", {}).setdefault(name, {"perms": [], "members": []})
        uid = int(text)
        if uid not in r["members"]:
            r["members"].append(uid)
            save_config()
        return await msg.reply_text(f"🎖 Добавил {uid} в «{name}».", reply_markup=role_detail_kb(cfg, name))

    if awaiting == "staff":
        if not text.lstrip("-").isdigit():
            return await msg.reply_text("Нужен числовой ID группы (обычно -100…). Проще — /setstaff в самой группе.")
        cfg["staff_group"] = int(text)
        save_config()
        return await msg.reply_text("🧷 Staff-чат привязан.", reply_markup=staff_kb(cfg))

    if awaiting == "mgr":
        if not text.isdigit():
            return await msg.reply_text("Нужен числовой ID (узнать: пусть человек напишет мне /userid).")
        uid = int(text)
        if uid not in CONFIG["managers"] and not is_owner(uid):
            CONFIG["managers"].append(uid)
            save_config(force=True)
            try:
                await context.bot.send_message(uid, "🔑 Тебе выдали доступ к управлению ботом. /panel")
            except Exception:  # noqa: BLE001
                pass
        return await msg.reply_text(f"🔑 {uid} теперь менеджер.", reply_markup=access_kb())

    if awaiting in ("gword", "gbid", "gbname"):
        if awaiting == "gword":
            added = _add_unique(CONFIG.setdefault("global_stop_words", []), _csv(text))
        elif awaiting == "gbid":
            gb = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
            added = _add_unique(gb["ids"], [int(x) for x in _csv(text) if x.lstrip("-").isdigit()])
        else:
            gb = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
            added = _add_unique(gb["names"], _csv(text))
        save_config(force=True)
        return await msg.reply_text(f"🌐 Добавлено: {len(added)}.", reply_markup=global_kb())

    if awaiting == "invitetext":
        CONFIG["invite_text"] = text
        save_config()
        return await msg.reply_text("✏️ Текст зазывалы сохранён.", reply_markup=promo_kb())

    if awaiting == "promo_content":
        CONFIG["promo"].update({"type": "text", "text": msg.text_html or text,
                                "html": True, "file_id": None})
        save_config()
        return await msg.reply_text("✅ Контент промо: текст сохранён.", reply_markup=promo_kb())
    if awaiting == "promo_btns":
        CONFIG["promo"]["buttons"] = [] if text in ("-", "—", "нет") else _parse_button_rows(text)
        save_config()
        return await msg.reply_text("🔘 Кнопки промо сохранены.", reply_markup=promo_kb())

    if awaiting == "bcast":
        ok, fail = await _broadcast(context, text=text)
        return await msg.reply_text(f"📤 Рассылка: отправлено {ok}, недоступно {fail}.",
                                    reply_markup=promo_kb())

    if awaiting == "dmcast":
        target = context.user_data.pop("dm_chat", "all")
        chat_ids = list(CONFIG.get("dm_subscribers", {}).keys()) if target == "all" else [target]
        sent, fail = await _dm_broadcast(context, chat_ids,
                                         {"type": "text", "text": msg.text_html or text, "html": True})
        return await msg.reply_text(f"💌 В ЛС: доставлено {sent}, недоступно {fail}.",
                                    reply_markup=promo_kb())

    if awaiting == "post":
        cid = context.user_data.pop("post_chat", None)
        if not cid:
            return await msg.reply_text("Группа потерялась — заново: /panel → 📣 → Пост.")
        ok = await deliver(context, cid, {"type": "text", "text": msg.text_html or text,
                                         "html": True})
        return await msg.reply_text("✅ Опубликовано." if ok else "Не вышло (меня нет в группе?).",
                                    reply_markup=promo_kb())

    if awaiting == "sp_time":
        m = re.match(r"(\d{1,2}):(\d{2})\s*(.*)", text)
        if not m:
            _ask(context, "sp_time")
            return await msg.reply_text("Формат: 19:30 пн,чт или 09:00. /cancel")
        h, mnt = int(m.group(1)) % 24, int(m.group(2)) % 60
        daymap = {"пн": 0, "вт": 1, "ср": 2, "чт": 3, "пт": 4, "сб": 5, "вс": 6}
        days = sorted({daymap[t] for t in re.split(r"[,\s]+", m.group(3).lower()) if t in daymap})
        context.user_data.setdefault("sp_draft", {}).update(
            {"time": f"{h:02d}:{mnt:02d}", "days": days})
        _ask(context, "sp_content")
        return await msg.reply_text("Шаг 2 из 3 · Пришли контент поста: текст или медиа с подписью.")

    if awaiting == "sp_content":
        content = _capture_post_content(msg)
        if not content:
            _ask(context, "sp_content")
            return await msg.reply_text("Не понял. Пришли текст или медиа, или /cancel.")
        context.user_data.setdefault("sp_draft", {}).update(content)
        _ask(context, "sp_btns")
        return await msg.reply_text("Шаг 3 из 3 · Кнопки «Текст - ссылка» по строке (ряд — через «;») "
                                    "или «-» без кнопок.")

    if awaiting == "sp_btns":
        rows = None if text in ("-", "—", "нет") else _parse_button_rows(text)
        pid = _finalize_sched_post(context, rows)
        if not pid:
            return await msg.reply_text("Черновик потерялся — начни заново: /panel → 🗓.")
        return await msg.reply_text("✅ Пост создан. Куда публиковать?", reply_markup=sched_groups_kb(pid))

    await msg.reply_text("Не понял. Панель — /panel, отмена — /cancel.")


async def on_private_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    awaiting = context.user_data.get("await")
    if not awaiting:
        return
    if not await _state_allowed(update, context, awaiting):
        return

    if awaiting == "trig_content":
        d = context.user_data.get("trig_draft", {})
        content = _capture_post_content(msg)
        if not d.get("keys") or not content:
            return await msg.reply_text("Не понял медиа. Пришли ещё раз или /cancel.")
        d.update(content)
        if content["type"] in _NO_CAPTION_TYPES:  # стикер/кружок — без подписи и кнопок
            keys, val, cfg = _save_trigger_draft(context)
            return await msg.reply_text(
                f"✅ Автоответ ({_POST_TYPE_RU.get(val.get('type'), 'медиа')}) сохранён для: {', '.join(keys)}.",
                reply_markup=triggers_kb(cfg))
        _ask(context, "trig_btns")
        return await msg.reply_text("Шаг 3 из 3 · Кнопки «Текст - ссылка» по строке (ряд — через «;») "
                                    "или «-» без кнопок.")

    if awaiting == "sp_content":
        content = _capture_post_content(msg)
        if not content:
            return await msg.reply_text("Не понял медиа. Ещё раз или /cancel.")
        context.user_data.setdefault("sp_draft", {}).update(content)
        if content["type"] in _NO_CAPTION_TYPES:
            pid = _finalize_sched_post(context)
            if pid:
                return await msg.reply_text("✅ Пост создан. Куда публиковать?",
                                            reply_markup=sched_groups_kb(pid))
            return await msg.reply_text("Черновик потерялся — /panel → 🗓.")
        _ask(context, "sp_btns")
        return await msg.reply_text("Шаг 3 из 3 · Кнопки или «-».")

    if awaiting == "promo_content":
        content = _capture_post_content(msg)
        if not content:
            return await msg.reply_text("Не понял медиа.")
        context.user_data.pop("await", None)
        CONFIG["promo"].update({"type": content["type"], "file_id": content.get("file_id"),
                                "text": content.get("text", ""), "html": content.get("html", False)})
        save_config()
        return await msg.reply_text("✅ Контент промо сохранён.", reply_markup=promo_kb())

    if awaiting == "bcast":
        if not msg.photo:
            return await msg.reply_text("Для рассылки подойдёт текст или фото с подписью. Ещё раз или /cancel.")
        context.user_data.pop("await", None)
        ok, fail = await _broadcast(context, text=msg.caption or "", photo_id=msg.photo[-1].file_id)
        return await msg.reply_text(f"📤 Рассылка: отправлено {ok}, недоступно {fail}.",
                                    reply_markup=promo_kb())

    if awaiting == "dmcast":
        content = _capture_post_content(msg)
        if not content:
            return await msg.reply_text("Не понял медиа.")
        context.user_data.pop("await", None)
        target = context.user_data.pop("dm_chat", "all")
        chat_ids = list(CONFIG.get("dm_subscribers", {}).keys()) if target == "all" else [target]
        sent, fail = await _dm_broadcast(context, chat_ids, content)
        return await msg.reply_text(f"💌 В ЛС: доставлено {sent}, недоступно {fail}.",
                                    reply_markup=promo_kb())

    if awaiting == "post":
        content = _capture_post_content(msg)
        if not content:
            return await msg.reply_text("Не понял медиа.")
        context.user_data.pop("await", None)
        cid = context.user_data.pop("post_chat", None)
        if not cid:
            return await msg.reply_text("Группа потерялась — /panel → 📣.")
        ok = await deliver(context, cid, content)
        return await msg.reply_text("✅ Опубликовано." if ok else "Не вышло (меня нет в группе?).",
                                    reply_markup=promo_kb())


async def on_private_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    awaiting = context.user_data.get("await")

    if awaiting in ("trig_content", "sp_content", "promo_content", "dmcast", "post", "bcast"):
        return await on_private_media(update, context)

    doc = msg.document
    if not doc:
        return
    name = (doc.file_name or "").lower()
    if not (name.endswith(".json") or (doc.mime_type or "").endswith("json")):
        return await msg.reply_text("Если это бэкап — нужен .json файл. Иначе: панель — /panel.")
    try:
        f = await context.bot.get_file(doc.file_id)
        raw = bytes(await f.download_as_bytearray())
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return await msg.reply_text(f"Не смог прочитать файл: {e}")

    if isinstance(data, dict) and data.get("_chat_backup"):
        context.user_data["_uid"] = user.id
        if not await _ensure_panel_target(context, user.id):
            return await msg.reply_text("Сначала выбери группу в /panel.")
        tgt = context.user_data.get("cfg_target")
        if not await can_edit_target(context, user.id, tgt) or not tgt or tgt == "defaults":
            return await msg.reply_text("Нет доступа к выбранной группе — /panel → 📂.")
        apply_chat_settings(int(tgt), data)
        return await msg.reply_text(
            f"✅ Настройки из файла применены к {panel_target_label(context)} "
            f"(бэкап был от «{data.get('_title', '?')}»).")

    if isinstance(data, dict) and ("groups" in data or "enabled" in data):
        if not is_manager(user.id):
            return await msg.reply_text("Полный бэкап может восстановить только владелец бота.")
        global CONFIG
        CONFIG = _merge_defaults(data)
        _split_comma_triggers(CONFIG)
        for ch in CONFIG.get("chats", {}).values():
            if isinstance(ch, dict):
                _split_comma_triggers(ch)
        _force_all_admins_only(CONFIG)
        CONFIG["cfg_version"] = 5
        save_config(force=True)
        return await msg.reply_text("✅ Полный бэкап восстановлен. Проверь /panel.")

    await msg.reply_text("Не похоже ни на полный бэкап, ни на файл настроек группы.")

# ───────────────────────────────────────────────────────────────────────────
#  ОШИБКИ, СТАРТ, РЕГИСТРАЦИЯ
# ───────────────────────────────────────────────────────────────────────────


async def on_error(update, context):
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        log.debug("network: %s", err)
        return
    log.error("Ошибка обработчика: %s", err, exc_info=err)


async def _post_init(app):
    me = await app.bot.get_me()
    _state["bot_username"] = me.username
    private_cmds = [
        BotCommand("panel", "панель управления"), BotCommand("status", "статус группы"),
        BotCommand("add", "автоответ: ключ - ответ"), BotCommand("list", "список автоответов"),
        BotCommand("addword", "добавить стоп-слова"), BotCommand("words", "список стоп-слов"),
        BotCommand("addlink", "добавить спам-домены"), BotCommand("pro", "тариф"),
        BotCommand("help", "помощь"), BotCommand("cancel", "отменить ввод"),
        BotCommand("userid", "мой ID"),
    ]
    group_cmds = [
        BotCommand("report", "пожаловаться модераторам"), BotCommand("me", "мой статус"),
        BotCommand("rules", "правила группы"), BotCommand("invite", "ссылка-приглашение"),
        BotCommand("anreg", "не звать меня в /all"), BotCommand("reg", "снова звать в /all"),
        BotCommand("userid", "ID (свой/по реплаю)"), BotCommand("pro", "тариф для группы"),
    ]
    admin_cmds = group_cmds + [
        BotCommand("ban", "бан (реплаем)"), BotCommand("kick", "кик"),
        BotCommand("mute", "мут (напр. 30m)"), BotCommand("unmute", "размут"),
        BotCommand("warn", "предупреждение"), BotCommand("warns", "список предов"),
        BotCommand("block", "в чёрный список"), BotCommand("info", "карточка участника"),
        BotCommand("purge", "чистка (реплаем)"), BotCommand("stats", "статистика"),
        BotCommand("top", "топ активности"), BotCommand("all", "позвать всех"),
        BotCommand("say", "сказать от бота"), BotCommand("zazyvala", "кнопка «пригласить»"),
        BotCommand("setwelcome", "приветствие"), BotCommand("setrules", "правила"),
        BotCommand("diag", "диагностика"), BotCommand("help", "команды"),
    ]
    for scope, cmds in ((BotCommandScopeAllPrivateChats(), private_cmds),
                        (BotCommandScopeAllGroupChats(), group_cmds),
                        (BotCommandScopeAllChatAdministrators(), admin_cmds)):
        try:
            await app.bot.set_my_commands(cmds, scope=scope)
        except Exception as e:  # noqa: BLE001
            log.debug("set_my_commands: %s", e)
    log.info("Бот @%s запущен · групп в памяти: %s", me.username, len(CONFIG.get("groups", {})))


async def _post_shutdown(app):
    _flush_config()


def build_app() -> Application:
    app = (Application.builder().token(BOT_TOKEN)
           .post_init(_post_init).post_shutdown(_post_shutdown).build())
    private = filters.ChatType.PRIVATE
    groups = filters.ChatType.GROUPS

    # Замок допуска: глушит неодобренные группы (кроме владельца и исключений)
    app.add_handler(MessageHandler(groups, _gate_unapproved), group=-1)

    # ── личные команды ──
    app.add_handler(CommandHandler("start", cmd_start, filters=private))
    app.add_handler(CommandHandler(["panel", "menu"], cmd_panel, filters=private))
    app.add_handler(CommandHandler("settings", cmd_panel, filters=private))
    app.add_handler(CommandHandler("status", cmd_status, filters=private))
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
    app.add_handler(CommandHandler("appeal", cmd_appeal, filters=private))
    app.add_handler(CommandHandler("gblock", cmd_gblock))
    app.add_handler(CommandHandler("gunblock", cmd_gunblock))
    app.add_handler(CommandHandler("grant", cmd_grant))
    app.add_handler(CommandHandler("revoke", cmd_revoke))

    # ── общие ──
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("pro", cmd_pro))
    app.add_handler(CommandHandler("grantpro", cmd_grantpro))
    app.add_handler(CommandHandler("reload", cmd_reload))
    app.add_handler(CommandHandler(["userid", "uid", "id"], cmd_userid))
    app.add_handler(PreCheckoutQueryHandler(on_pre_checkout))

    # ── команды в группе ──
    for names, fn in (
        ("ban", cmd_ban), ("unban", cmd_unban), ("kick", cmd_kick),
        ("mute", cmd_mute), ("unmute", cmd_unmute),
        ("warn", cmd_warn), ("unwarn", cmd_unwarn), ("warns", cmd_warns),
        ("block", cmd_block), ("unblock", cmd_unblock),
        ("role", cmd_role), ("unrole", cmd_unrole), ("setstaff", cmd_setstaff),
        ("info", cmd_info), ("stats", cmd_stats), ("top", cmd_top),
        (["invite", "link"], cmd_invite), ("zazyvala", cmd_zazyvala),
        ("all", cmd_all), ("stopall", cmd_stopall),
        ("anreg", cmd_anreg), ("reg", cmd_reg), ("say", cmd_say),
        ("rules", cmd_rules), ("setrules", cmd_setrules), ("setwelcome", cmd_setwelcome),
        ("purge", cmd_purge), ("report", cmd_report), (["me"], cmd_me),
        ("diag", cmd_diag), (["config"], cmd_settings_hint),
    ):
        app.add_handler(CommandHandler(names, fn, filters=groups))
    app.add_handler(CommandHandler(["settings"], cmd_settings_hint, filters=groups))
    app.add_handler(CommandHandler(["status"], cmd_me, filters=groups))

    # ── кнопки: специализированные раньше общего роутера ──
    app.add_handler(CallbackQueryHandler(handle_captcha_press, pattern=r"^cap:"))
    app.add_handler(CallbackQueryHandler(handle_join_request_press, pattern=r"^jrok:"))
    app.add_handler(CallbackQueryHandler(handle_setstaff_press, pattern=r"^ss:"))
    app.add_handler(CallbackQueryHandler(handle_action_press, pattern=r"^(act:|arole:)"))
    app.add_handler(CallbackQueryHandler(handle_allstop_press, pattern=r"^allstop$"))
    app.add_handler(CallbackQueryHandler(handle_buy_group_press, pattern=r"^buyg:"))
    app.add_handler(CallbackQueryHandler(on_callback))

    # ── членство и входы ──
    app.add_handler(ChatMemberHandler(on_my_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(MessageHandler(groups & filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_members))
    app.add_handler(MessageHandler(
        groups & (filters.StatusUpdate.NEW_CHAT_TITLE | filters.StatusUpdate.NEW_CHAT_PHOTO),
        on_chat_settings_change))

    # ── group=1: оплата → миграция → единый конвейер → чистка сервис-сообщений ──
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment), group=1)
    app.add_handler(MessageHandler(groups & filters.StatusUpdate.MIGRATE, on_migrate), group=1)
    app.add_handler(MessageHandler(groups & ~filters.StatusUpdate.ALL, on_group_traffic), group=1)
    app.add_handler(MessageHandler(groups & filters.StatusUpdate.ALL, on_service_cleanup), group=1)
    # ── group=2: авто-чистка команд ──
    app.add_handler(MessageHandler(groups & filters.COMMAND, on_command_cleanup), group=2)

    # ── личка: мастера и бэкапы ──
    app.add_handler(MessageHandler(private & filters.TEXT & ~filters.COMMAND, on_private_text))
    app.add_handler(MessageHandler(
        private & (filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Sticker.ALL
                   | filters.VIDEO_NOTE | filters.AUDIO | filters.VOICE),
        on_private_media))
    app.add_handler(MessageHandler(private & filters.Document.ALL, on_private_document))

    app.add_error_handler(on_error)
    return app


def main():
    if not BOT_TOKEN:
        log.error("Не задан BOT_TOKEN (переменная окружения).")
        sys.exit(1)
    app = build_app()
    _state["last_promo"] = time.time()
    jq = app.job_queue
    jq.run_repeating(minute_tick, interval=60, first=20)
    jq.run_repeating(flush_config_job, interval=90, first=90)
    jq.run_repeating(janitor_job, interval=3600, first=600)
    jq.run_repeating(maintenance_daily_job, interval=86400, first=3600)
    jq.run_repeating(weekly_digest_job, interval=7 * 86400, first=7 * 86400)
    log.info("Запуск polling… (данные: %s)", CONFIG_PATH)
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
