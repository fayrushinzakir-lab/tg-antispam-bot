# -*- coding: utf-8 -*-
"""
Channel Guard Bot  —  версия 6 («всё в одном»)
================================================
Антиспам + автоответы (текст/медиа/кнопки) + панель в ЛС + модерация + капча +
приветствие + привлечение (промо, рассылки, посты по расписанию) + роли +
анти-снос/анти-рейд + оплата звёздами Telegram.

Что нового в v6:
  • Панель из 6 разделов-хабов: 🛡 Защита, ⚖️ Модерация, 💬 Общение, 📮 Посты,
    📊 Статистика, ⚙️ Система. Все стоп-списки — в одном месте «🚫 Фильтры слов».
    Кнопка «Назад» возвращает в свой раздел, а не в корень. Старые настройки не менялись.
  • 🛒 Магазин Mini App: тариф PRO для группы и свои товары за звёзды Telegram.
    Встроенный веб-сервер (aiohttp) отдаёт страницу магазина и выставляет счета.
    Настройка: WEBAPP_URL (публичный https-адрес), SHOP_PORT, SHOP_APP_NAME.

Что нового в v5.1:
  • Параллельная обработка апдейтов: ИИ, /all и рассылки больше не «замораживают» бота.
  • Кэш скомпилированных стоп-слов (в десятки раз меньше работы на сообщение).
  • Капча, заявки и мягкие муты переживают перезапуск (нет «вечного мута»).
  • Промо, авто-сообщения, посты и недельная сводка не шлются залпом после рестарта.
  • Длинные кулдауны болталки больше не сбрасываются уборщиком.
  • Отдельный срок «мута за спам»; экранирование имён в HTML.
  • 👤 Менеджеры группы: полный доступ к настройкам и модерации своей группы
    без админки Telegram (назначает создатель группы или владелец бота).

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
  • «🎭 Болталка 2.0»: бот отвечает на обращения к нему (@упоминание, реплай,
    «бот, …») с умом — узнаёт приветствия, «как дела», благодарности, просьбы
    пошутить; сам вбрасывает шутки и ставит эмодзи-реакции (панель → 🎭 Болталка).
    🧢 Гоп-режим: бот отвечает «по-пацански» и сам реагирует на слова-триггеры
    («слышь», «чё каво», «семки»…) — включается там же.
    🎮 Игры и приколы: кубик/дартс/баскет (настоящие Dice), камень-ножницы-бумага,
    «пицца или суши?», «кто самый …?» (из участников), число от X до Y, факты,
    цитаты, комплименты и добрые подколы, шуточный гороскоп, шар предсказаний,
    «доброе утро, чат» после тишины, поздравления с ДР, юбилеи каждой 1000-й
    записи и память короткого диалога.
    🤖 ИИ-ответы (опционально): задай AI_API_KEY (OpenAI-совместимый API) — и бот
    будет живо болтать на любые темы в выбранном стиле; без ключа работает офлайн.
  • Мат-фильтр из коробки: нецензурные слова во «втором списке» — за каждое
    предупреждение, три предупреждения → бан (настраивается в панели).

Запуск: переменная окружения BOT_TOKEN. Главный владелец: ADMIN_IDS.
Зависимости: pip install "python-telegram-bot[job-queue,rate-limiter]" aiohttp
(aiohttp нужен только для магазина Mini App; без него бот работает как обычно)
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
import functools
import hmac
import hashlib

import httpx  # идёт в комплекте с python-telegram-bot

try:  # веб-сервер магазина Mini App (необязательно)
    from aiohttp import web
except ImportError:  # noqa: SIM105
    web = None
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, parse_qsl

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    WebAppInfo,
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

# ── Необязательный ИИ для болталки (любой OpenAI-совместимый API) ──
# Задай переменные окружения — и в панели болталки появится рабочий тумблер «🤖 ИИ-ответы»:
#   AI_API_KEY  — ключ (OpenAI / OpenRouter / Groq / DeepSeek / локальный Ollama…)
#   AI_BASE_URL — базовый URL API (по умолчанию https://api.openai.com/v1)
#   AI_MODEL    — модель (по умолчанию gpt-4o-mini)
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
AI_BASE_URL = (os.environ.get("AI_BASE_URL", "https://api.openai.com/v1") or "").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"

# ── Магазин Mini App (необязательно) ──
#   WEBAPP_URL    — публичный HTTPS-адрес, который проксируется на SHOP_PORT (напр. https://shop.site.ru)
#   SHOP_PORT     — порт встроенного веб-сервера (по умолчанию 8080), SHOP_HOST — интерфейс (0.0.0.0)
#   SHOP_APP_NAME — короткое имя Mini App из BotFather (/newapp) — для кнопки прямо в группе
WEBAPP_URL = (os.environ.get("WEBAPP_URL", "") or "").strip().rstrip("/")
SHOP_PORT = int(os.environ.get("SHOP_PORT", "8080") or 8080)
SHOP_HOST = os.environ.get("SHOP_HOST", "0.0.0.0") or "0.0.0.0"
SHOP_APP_NAME = (os.environ.get("SHOP_APP_NAME", "") or "").strip()

# ───────────────────────────────────────────────────────────────────────────
#  ВСТРОЕННЫЙ МАТ-ФИЛЬТР (второй список слов: пред → 3 преда → бан)
# ───────────────────────────────────────────────────────────────────────────
# Синтаксис как у стоп-слов: слово* — начало, *слово* — вхождение.
# Подобраны так, чтобы не цеплять обычные слова (хлеб, сучок, мудрость и т.п.).
MAT_WORDS = [
    "хуй*", "хуе*", "хуё*", "хуя*", "хую*", "хуи", "хули", "хуле",
    "нахуй*", "нихуя*", "охуе*", "охуи*",
    "*пизд*",
    "бля", "бля*",
    "еб*", "ёб*", "заеб*", "наеб*", "поеб*", "проеб*", "съеб*", "уеб*",
    "выеб*", "отъеб*", "подъеб*", "взъеб*", "долбоеб*", "долбоёб*",
    "сука", "суки", "сукин*", "сучар*",
    "пидор*", "пидар*", "пидр*", "педик*",
    "гандон*", "гондон*", "мудак*", "мудил*", "мудозвон*",
    "шлюх*", "шалав*", "залуп*", "дроч*", "мраз*",
    "хер", "херн*", "нахер*", "похер*", "говн*", "манда",
    "fuck*", "shit*", "bitch*", "cunt*",
    # латиница и транслит (нормализация приводит похожие буквы к кириллице)
    "suka", "cyka", "blya*", "*pizd*", "huy*", "hui*", "nahu*",
    "ebal*", "ebat*", "pidor*", "pidar*", "gandon*", "mudak*", "dolboeb*",
    "пздц", "сцук*",
]

# ───────────────────────────────────────────────────────────────────────────
#  НАСТРОЙКИ ПО УМОЛЧАНИЮ
# ───────────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "cfg_version": 6,
    "enabled": {
        "invites": True, "shorteners": True, "all_links": False, "spam_domains": True,
        "words": True, "flood": True, "name_check": True, "triggers": True,
        "words2": True,
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
    # Второй список слов — свой набор и СВОЁ наказание. По умолчанию это мат-фильтр:
    # за мат — предупреждение; счётчик общий (/warns), по лимиту — бан (см. moderation).
    # action: delete|warn|mute|ban. profile: искать слова ещё и в имени/юзернейме отправителя.
    "stop_words2": list(MAT_WORDS),
    "stop_words2_action": "warn",
    "stop_words2_profile": True,
    "spam_links": [],
    # Автоответы: значение — текст ИЛИ объект {"type","file_id","text","html","buttons"}
    "triggers": {"банан": "300 руб"},
    "trigger_match": "word",
    # «🎭 Болталка 2.0»: умные ответы на обращения, случайные шутки, эмодзи-реакции
    "chatter": {
        "enabled": False,
        "chance": 5,              # шанс случайной шутки, % на каждое сообщение
        "cooldown": 180,          # пауза между случайными шутками, сек
        "reply_mentions": True,   # отвечать на @упоминание, реплай и «бот, …»
        "smart_replies": True,    # понимать настроение обращения (привет/спасибо/пошути…)
        "reactions": True,        # изредка ставить эмодзи-реакции на сообщения
        "reaction_chance": 8,     # шанс реакции, %
        "fun": True,              # игры и приколы: кубик/дартс, КНБ, «или», «кто», шар, юбилеи
        "ai": False,              # 🤖 ИИ-ответы на обращения (нужен AI_API_KEY в окружении)
        # 🧢 Гоп-режим: бот отвечает «по-пацански»; на слова-триггеры реагирует сам,
        # даже без обращения к нему. Синтаксис слов — как у стоп-слов (можно со *).
        "gopnik": False,
        "gop_words": [
            "слышь", "че каво", "чекаво", "гоп*", "семки", "семечк*",
            "пацан*", "братан*", "браток", "в натуре", "за базар*",
            "по фактам", "на районе", "на раене", "четко", "чётко",
            "адидас", "абибас", "на кортах",
        ],
        "phrases": [
            "Так-так, кто тут веселится без меня? 😏",
            "Читаю вас и {улыбаюсь|хихикаю} в проводах 🤖",
            "Минутка от бота: этот чат — {огонь|топ} 🔥",
            "Живу тут бесплатно и не жалуюсь 😎",
            "Интересная тема! Продолжайте, я {записываю|конспектирую} 📝",
            "Если что, я всё вижу 👀 Шучу. Или нет…",
            "С вами не соскучишься 😄",
            "Плюс один к карме этого чата ✨",
            "Так, где мой попкорн? 🍿 Продолжайте!",
            "Официально заявляю: вы — {лучший|самый душевный} чат в моей памяти 💾❤️",
            "Тут так интересно, что я чуть не забыл ловить спам 😅",
            "{Кстати|Между прочим}, сегодня отличный день, чтобы позвать друга в чат 😉",
            "Хотел промолчать, но не удержался: вы классные 🙌",
            "Сижу, никого не баню… красота 🧘",
            "Вжух — и я здесь! ⚡ Ладно, продолжайте.",
            "Моя нейросеть одобряет этот разговор 🤖👍",
            "Запомните этот момент: бот был тут 🗿",
            "А помните времена без меня? Вот и я не помню 😌",
            "Тихо! Слышите? Это звук идеальной модерации 🎧",
            "Ставлю этому чату {десять|сто} из десяти 💯",
            "Не хочу хвастаться, но спам обходит нас стороной 😎",
            "Улыбнитесь, вас снимает {скрытая камера|бот} 📸",
            "Пока вы общаетесь, я тренирую чувство юмора. Как получается? 😅",
            "Ем электричество, шучу бесплатно ⚡😄",
        ],
        "replies": [
            "Да-да, я тут 🤖",
            "{Слушаю|Внимаю} внимательно 👂",
            "Меня звали? Я всегда на посту 😎",
            "Бип-буп! Если нужна помощь — /help 🙌",
            "Я бот, но с душой ❤️",
            "{Привет|Салют|Йо}! Я на месте ✋",
            "На связи! ⚡ Чем могу?",
            "Весь во внимании, {name} 🙂",
            "Кто-то сказал «бот»? Появляюсь эффектно 💨",
            "Всегда рядом. Иногда даже слишком 😄",
            "Загрузился на 100%, слушаю 🔋",
            "{Ну наконец-то|О!} обо мне вспомнили 🥹",
            "Спрашивай — отвечу. Ну, постараюсь 😅",
            "Здесь! Спам не пройдёт, шутка — всегда 🤝",
        ],
    },
    "moderation": {"warn_limit": 3, "warn_action": "ban", "warn_mute": 3600, "mod_admins_only": False, "log_actions": False, "warn_expire_days": 0, "notify_delete": False, "spam_mute": 0},
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
    # Менеджеры ЭТОЙ группы: полный доступ к её настройкам и модерации без админки Telegram
    "group_managers": [],
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
    # Служебное состояние, переживающее перезапуск (метки рассылок, ожидания капчи, мягкие муты)
    # Магазин Mini App: свои товары (тариф PRO для группы добавляется автоматически)
    # items: [{"id","title","desc","stars","deliver","enabled"}]
    "shop": {"enabled": False, "title": "Магазин", "items": []},
    "shop_orders": [],
    "runtime": {},
    "pending": {},
    "soft_mutes": {},
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
                 "roles", "staff_group", "lang", "blacklist", "antiraid", "chatter",
                 "group_managers")
PER_CHAT_DICTS = ("enabled", "flood", "moderation", "welcome", "captcha", "antinuke",
                  "cmd_perms", "media_block", "night", "roles", "blacklist", "antiraid",
                  "chatter")


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
        if k in ("enabled", "flood", "moderation", "welcome", "promo", "antinuke", "captcha", "cmd_perms", "media_block", "night", "roles", "blacklist", "antiraid", "chatter", "shop") and isinstance(v, dict):
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


def _migrate_v6(cfg: dict) -> None:
    """v6: встроенный мат-фильтр (второй список: пред, 3 преда → бан)
    и пополнение болталки новыми фразами по умолчанию."""
    def add(lst, items):
        for w in items:
            if w not in lst:
                lst.append(w)

    def up(d):
        add(d.setdefault("stop_words2", []), MAT_WORDS)
        d["stop_words2_action"] = "warn"
        d.setdefault("enabled", {})["words2"] = True
        m = d.setdefault("moderation", {})
        m["warn_limit"] = 3
        m["warn_action"] = "ban"
        ch = d.setdefault("chatter", {})
        add(ch.setdefault("phrases", []), DEFAULT_CONFIG["chatter"]["phrases"])
        add(ch.setdefault("replies", []), DEFAULT_CONFIG["chatter"]["replies"])

    up(cfg)
    for c in cfg.get("chats", {}).values():
        if isinstance(c, dict):
            up(c)


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
            if isinstance(raw, dict) and int(raw.get("cfg_version", 0) or 0) < 6:
                _migrate_v6(cfg)
            cfg["cfg_version"] = 6
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


def _pair_key(chat_id, user_id) -> str:
    return f"{chat_id}:{user_id}"


def _split_pair(key: str):
    c, u = key.rsplit(":", 1)
    return int(c), int(u)


def soft_mute_add(chat_id: int, user_id: int, seconds: int = 0):
    """Мягкий мут: сообщения этого пользователя удаляются (для обычных групп и для админов).
    Хранится в конфиге — переживает перезапуск."""
    until = (time.time() + seconds) if seconds else 0.0
    soft_mutes[(chat_id, user_id)] = until
    CONFIG.setdefault("soft_mutes", {})[_pair_key(chat_id, user_id)] = until
    save_config()


def soft_mute_remove(chat_id: int, user_id: int):
    had = soft_mutes.pop((chat_id, user_id), None) is not None
    had_cfg = CONFIG.setdefault("soft_mutes", {}).pop(_pair_key(chat_id, user_id), None) is not None
    if had or had_cfg:
        save_config()


def is_soft_muted(chat_id: int, user_id: int) -> bool:
    until = soft_mutes.get((chat_id, user_id))
    if until is None:
        return False
    if until and until <= time.time():
        soft_mute_remove(chat_id, user_id)
        return False
    return True


def _load_soft_mutes():
    """Поднять мягкие муты из конфига в память (при старте, /reload, восстановлении бэкапа)."""
    soft_mutes.clear()
    now = time.time()
    store = CONFIG.setdefault("soft_mutes", {})
    for k, v in list(store.items()):
        try:
            c, u = _split_pair(k)
            v = float(v or 0)
        except Exception:  # noqa: BLE001
            store.pop(k, None)
            continue
        if v and v <= now:
            store.pop(k, None)
            continue
        soft_mutes[(c, u)] = v


def _throttle(key, seconds: float) -> bool:
    """Анти-флуд действий: True, если по ключу прошло >= seconds с прошлого раза.
    Храним момент ИСТЕЧЕНИЯ — уборщик удаляет только истёкшие ключи,
    поэтому кулдауны в 6 и 20 часов больше не сбрасываются раньше времени."""
    now = time.time()
    if now < _throttle_store.get(key, 0.0):
        return False
    _throttle_store[key] = now + seconds
    return True


def _rt() -> dict:
    """Служебное состояние в конфиге (переживает перезапуск)."""
    return CONFIG.setdefault("runtime", {})


def _pend_set(kind: str, chat_id: int, uid: int, deadline: float, mid=None):
    """Запомнить ожидание капчи/заявки, чтобы после рестарта довести его до конца."""
    CONFIG.setdefault("pending", {}).setdefault(kind, {})[_pair_key(chat_id, uid)] = {
        "deadline": deadline, "mid": mid}
    save_config()


def _pend_pop(kind: str, chat_id: int, uid: int):
    if CONFIG.setdefault("pending", {}).setdefault(kind, {}).pop(_pair_key(chat_id, uid), None):
        save_config()


def _expiry_mark(chat_id) -> None:
    lst = _rt().setdefault("expiry_notified", [])
    if str(chat_id) not in lst:
        lst.append(str(chat_id))
        save_config()


def _expiry_clear(chat_id) -> None:
    lst = _rt().setdefault("expiry_notified", [])
    if str(chat_id) in lst:
        lst.remove(str(chat_id))
        save_config()

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


def is_group_manager(chat_id, user_id) -> bool:
    """Менеджер конкретной группы: полный доступ к её настройкам и модерации
    (глобальные разделы бота ему недоступны)."""
    try:
        return int(user_id) in (chat_cfg(chat_id).get("group_managers") or [])
    except Exception:  # noqa: BLE001
        return False


async def can_assign_group_managers(context, chat_id: int, user_id: int) -> bool:
    """Назначать менеджеров группы: владелец/менеджеры бота или создатель группы."""
    if is_manager(user_id):
        return True
    return user_id == await group_creator_id(context, int(chat_id))


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
    if is_manager(user_id) or is_group_manager(chat_id, user_id):
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
    if is_manager(user_id) or is_group_manager(chat_id, user_id):
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
    if is_manager(user_id) or is_group_manager(chat_id, user_id):
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


@functools.lru_cache(maxsize=4096)
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
            secs = int(cfg["moderation"].get("spam_mute") or cfg["flood"]["mute"])
            await mute_user(context, chat.id, user.id, secs)
            bump(chat.id, "muted")
            await ephemeral(context, chat.id,
                            f"🔇 {mention(user)} в муте на {human_duration(secs)} — {reason}.")
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
        if txt.startswith(("/diag", "/pro", "/start", "/shop")):
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

    # 9) Автоответы (а если ключ не совпал — шанс «болталки»)
    await maybe_send_trigger(update, context, text)


async def maybe_send_trigger(update, context, text):
    chat = update.effective_chat
    cfg = chat_cfg(chat.id)
    if text and cfg["enabled"].get("triggers"):
        hit = match_trigger(text, cfg)
        if hit:
            key, resp = hit
            if _throttle(("trig", chat.id, str(key)), 10.0):
                # кулдаун 10 сек на слово — чат нельзя заспамить самим ботом
                post = resp if isinstance(resp, dict) else {"type": "text", "text": str(resp)}
                try:
                    await _send_one(context, chat.id, post, reply_to=update.effective_message.message_id)
                except Exception as e:  # noqa: BLE001
                    log.debug("trigger: %s", e)
            return  # ключ совпал — случайную шутку поверх не кидаем
    await maybe_chatter(update, context, cfg)



# ── «мозги» болталки: банки ответов, память диалога, игры ──────────────────
_chatter_dialog: dict = {}   # (chat_id, user_id) -> ts последнего ответа бота человеку
_chatter_said: dict = {}     # chat_id -> последняя сказанная фраза (антиповтор)
_chat_log: dict = defaultdict(lambda: deque(maxlen=12))  # chat_id -> (имя, текст) для ИИ
_chat_daymark: dict = {}     # chat_id -> ts последнего сообщения (для «доброе утро, чат»)

_CHATTER_BANKS = {
    "greet": [
        "Привет, {name}! 👋",
        "{Здарова|Салют|Приветствую}, {name}! 😎",
        "О, {name}! Рад видеть 🤗",
        "Ку-ку! Я тут, всё под контролем 🤖",
        "Привет-привет! Чем удивишь? 🙂",
        "{Салам|Йо}, {name}! Как настроение? ✨",
    ],
    "greet_morning": [
        "Доброе утро, {name}! ☀️ Кофе уже был?",
        "С добрым утром! Сегодня будет хороший день ☕",
        "Утро! Я уже на посту, можно просыпаться спокойно 🌅",
    ],
    "greet_day": [
        "Добрый день, {name}! 🌞",
        "День в разгаре, а тут {name}! Привет 👋",
    ],
    "greet_evening": [
        "Добрый вечер, {name}! 🌆",
        "Вечер — лучшее время для чата. Привет! 🌇",
    ],
    "greet_night": [
        "Не спится, {name}? 🌙 Я тоже на посту.",
        "Доброй ночи! Тут только мы и звёзды ✨",
    ],
    "howru": [
        "Как всегда: на посту, спам дрожит 😎",
        "Работаю 24/7 и не жалуюсь 🤖",
        "Лучше всех: процессор холодный, настроение горячее 🔥",
        "Живу на серверном, дышу апдейтами. А ты как, {name}?",
        "Бодрячком! {Спам ловится|Чат под охраной}, жизнь удалась 💪",
    ],
    "thanks": [
        "Всегда пожалуйста, {name}! 🤝",
        "Обращайся 😉",
        "Да не за что — я тут для этого 🤖",
        "На здоровье! {Работаем дальше|Служу чату} 🫡",
    ],
    "bye": [
        "Пока, {name}! Возвращайся 👋",
        "До связи! Я никуда не денусь 🤖",
        "Сладких снов! Я подежурю 🌙",
        "Удачи! Чат под присмотром 🫡",
    ],
    "laugh": [
        "Ахахах, зачёт 😂",
        "Смешно! Записал в избранное 📝😄",
        "Ну ты выдал(а), {name} 🤣",
        "Хах, с вами не соскучишься 😆",
    ],
    "whoami": [
        "Я — страж этого чата: ловлю спам, слежу за порядком и иногда шучу 😎",
        "Бот-охранник с чувством юмора: спамеров — в бан, хороших людей — обнимаю 🤗",
        "Я Channel Guard: модерация, капча, автоответы и немного магии 🤖✨",
    ],
    "praise": [
        "Ой, спасибо, {name}! Стараюсь 🥰",
        "Захвалите — зазнаюсь 😌",
        "Приятно! Передам своим нейронам 🤖❤️",
        "Вы тоже топ! 💯",
    ],
    "rude": [
        "Я всего лишь бот, но у меня тоже есть чувства… целых два 🥲",
        "Зато я не флужу 😌",
        "Обидно, между прочим. Пойду поплачу в лог-файл 😢",
        "Принято. Загружаю модуль обиды… ошибка 404, обида не найдена 😎",
    ],
    "question": [
        "Хороший вопрос! Но я по шуткам, а по фактам чат подскажет лучше 🙂",
        "Хм, дай подумать… 🤔 Голосуем в чате?",
        "Если бы я знал ответы на всё — брал бы звёздами 😄",
        "{Сложно сказать|Загадка века}! Но звучит интересно 👀",
    ],
    "support": [
        "Держись, {name} 🤗 Я рядом, и чат тоже.",
        "Обнял 🫂 Всё наладится, вот увидишь.",
        "Ты сильнее, чем думаешь 💪 Отдохни немного, это помогает.",
        "Бывает у всех. Выдохни — мы тут, если что 🤝",
    ],
    "bday": [
        "С днём рождения! 🎂🎉 Пусть всё будет отлично!",
        "Ура, праздник! 🎁 Здоровья, счастья и нулевого спама!",
        "Поздравляю! 🎈 Желаю самых тёплых сообщений в жизни 💌",
        "С днюхой! 🥳 Сегодня в этом чате official праздник!",
    ],
    "more": [
        "Вот и я о том же 😄",
        "Продолжай, слушаю 👂",
        "Логично! 🙂",
        "Ну ты понял(а) 😏",
        "Согласен на все сто 💯",
        "Интересно излагаешь, {name} 🤔",
    ],
    "coin": ["Орёл 🦅", "Решка 🪙", "Орёл! Даже не сомневался 🦅", "Решка. Монета сказала — я передал 🪙"],
    "choice": [
        "Однозначно {pick}! 😎",
        "Тут даже думать нечего — {pick} 💯",
        "Мой процессор говорит: {pick} 🤖",
        "{pick}. Вопросы? 😏",
        "Подбросил монетку — выпало {pick} 🪙",
        "Сердцем чувствую: {pick} ❤️",
    ],
    "who": [
        "Мой сканер показал: это {pick} 🔎",
        "Сто пудов {pick}, даже не сомневайтесь 😏",
        "Голосованием нейронов решено: {pick} 🏆",
        "Все и так знают, что это {pick} 😄",
        "Судьба выбрала: {pick} ✨",
    ],
    "who_empty": ["Хм, я тут ещё мало кого запомнил 🤷 Пообщайтесь при мне — буду знать!"],
    "ball": [
        "Да ✅", "Стопроцентно да 💯", "Звёзды говорят «да» ✨", "Знаки указывают на да 🔮",
        "Нет ❌", "Даже не думай 😅", "Вряд ли 🤔", "Туманно… но скорее нет 🌫",
        "Спроси позже, я на обеде 🍔", "50 на 50 — подбрось монетку 🪙",
    ],
    "milestone": [
        "🎉 Юбилей! Это {total}-е сообщение в чате — {name} вписал(а) себя в историю 😄",
        "🥳 {total} сообщений! Живее всех живых. Так держать!",
        "🏆 Отметка {total} взята! Этот чат не остановить 💪",
    ],
    "default": [
        "Да-да, я тут 🤖",
        "{Слушаю|Внимаю} внимательно 👂",
        "Меня звали? Я всегда на посту 😎",
        "Бип-буп! Если нужна помощь — /help 🙌",
        "{Привет|Салют|Йо}! Я на месте ✋",
        "Весь во внимании, {name} 🙂",
    ],
    "gm": [
        "Доброе утро, чат! ☀️ Первый на связи — держите заряд бодрости 🔋",
        "Просыпаемся! 🌅 Кофе, улыбка — и погнали ☕",
        "С добрым утром всех! Пусть день будет отличным 🙌",
    ],
    "fact": [
        "У осьминога три сердца 💙💙💙",
        "Мёд может храниться тысячи лет и не портиться 🍯",
        "Сердце синего кита — размером с автомобиль 🐋",
        "Бананы — это ягоды, а клубника — нет 🍌",
        "Молния в несколько раз горячее поверхности Солнца ⚡",
        "Кошки спят примерно 70% жизни 🐱",
        "Эйфелева башня летом чуть выше — металл расширяется 🗼",
        "Акулы появились на Земле раньше деревьев 🦈",
        "Горячая вода может замёрзнуть быстрее холодной — эффект Мпембы ❄️",
        "Сердце креветки находится у неё в голове 🦐",
        "Отпечаток языка уникален, как отпечаток пальца 👅",
        "Улитка может спать до трёх лет 🐌",
        "Глаз страуса больше его мозга 🙈",
        "У морской звезды нет мозга — и ничего, живёт ⭐",
        "Ради банки мёда пчёлы облетают миллионы цветков 🐝",
        "Венера вращается в другую сторону, чем большинство планет 🪐",
        "Кости человека прочнее бетона той же массы 🦴",
        "Арахис — не орех, а боб 🥜",
        "Пингвин делает предложение, даря камушек 🐧💍",
        "На Юпитере и Сатурне возможны дожди из алмазов 💎",
        "За жизнь человек проходит пешком расстояние в несколько экваторов 🚶",
        "Медузы существуют дольше динозавров 🪼",
        "В Японии есть остров, где хозяйничают кролики 🐰",
        "Секунда для спутников GPS идёт чуть иначе — привет, Эйнштейн 🛰",
    ],
    "quote": [
        "Лучший день для старта — сегодня. Второй лучший — тоже сегодня 😄",
        "Делай, как можешь: это всегда лучше, чем не делать вовсе 💪",
        "Большие дела начинаются с маленького «ну ладно, попробую» 🚀",
        "Улыбка — бесплатно, а работает лучше многих платных фич 🙂",
        "Не сравнивай себя со вчерашними другими. Сравни со вчерашним собой 📈",
        "Ошибся — значит попробовал. Это уже победа над диваном 🏆",
        "Хочешь изменить мир — начни с чата: напиши что-то доброе 💬❤️",
        "Терпение + интернет = можно научиться почти всему 🌐",
        "Сложное — это простое, которое ещё не разложили по шагам 🧩",
        "Отдых — тоже часть плана. Даже боты перезагружаются 😉",
        "Мечта без дедлайна — сон. Поставь дату — станет целью 🗓",
        "Окружай себя теми, с кем хочется быть лучше. Например, этим чатом 😄",
        "Маленький шаг каждый день обгоняет большой рывок раз в год 🐾",
        "Если страшно начинать — начни страшно. Потом поправим 😅",
    ],
    "compl": [
        "{who}, у тебя отличное чувство юмора 😄",
        "{who} — украшение этого чата ✨",
        "С {who} даже баги веселее 🐞",
        "{who}, твоя энергия заряжает чат 🔋",
        "Будь тут топ приятных людей, {who} был(а) бы в первой строчке 🏆",
        "{who}, ты как хороший Wi-Fi: с тобой всё ловит 📶",
        "Улыбку {who} видно даже через текст 🙂",
        "{who}, звёзды сегодня явно за тебя ✨",
        "{who} умеет поднять настроение одним сообщением 💬❤️",
        "Будь {who} функцией — её вызывали бы чаще всех 😄",
        "{who} — редкий экземпляр в самом хорошем смысле 🦄",
        "{who}, респект просто за то, что ты есть 🤝",
    ],
    "roast": [
        "{who}, ты печатаешь быстрее, чем думаешь. И это талант 😄",
        "{who} — единственный человек, который может лагать без интернета 😅",
        "У {who} стиль «загадка»: сначала пишет, потом думает 🤔😄",
        "{who}, будь лень спортом — у тебя золото 🥇 (любя!)",
        "{who} гуглит «как гуглить» 🔍😆",
        "Клавиатура {who} давно просит выходной 😅",
        "{who}, твой будильник тебя побаивается ⏰",
        "{who} читает чат мгновенно, а отвечает через полдня 😄",
        "{who} превращает «щас приду» в квест на три часа 🕒",
        "Даже автозамена сдаётся, когда пишет {who} 📝😆",
        "{who} не опаздывает — просто живёт в своём часовом поясе 🌍",
        "{who} способен уснуть, пока грузится мем 😴",
    ],
    "rps_draw": ["{be} {bot}! Ничья 🤝 Ещё раз?", "Оба выбрали {bot} 🤝 Это судьба."],
    "rps_bot": ["{be} {bot}! Моя победа 😎 Реванш?", "{be} {bot} бьёт твой выбор 🏆 Я хорош!"],
    "rps_user": ["{be} {bot}… Ты победил(а) 🏆 Уважение!", "{be} {bot} — и я проиграл 😅 Красиво!"],
    "num": ["🎲 Выпало: {n}!", "Мой генератор говорит: {n} ✨", "{n} — запомни это число 😉"],
    "jokes": [
        "Почему программисты путают Хэллоуин и Рождество? Потому что OCT 31 == DEC 25 🎃🎄",
        "Я бы рассказал шутку про UDP, но не уверен, что она до вас дойдёт 😏",
        "— Бот, ты спишь? — Нет, я в режиме ожидания… мечтаю об электроовцах 🐑⚡",
        "Оптимист видит стакан наполовину полным, а я вижу лишний стакан памяти 🤖",
        "Захожу я как-то в чат… а тут вы. Ну всё, шутка удалась 😄",
        "Мой девиз: работать 24/7 и делать вид, что это легко 💪",
        "Шутки про лифт — отдельная тема: они поднимают настроение ⬆️😆",
        "Не откладывай на завтра то, что можно делегировать боту 😎",
        "Штирлиц долго смотрел в одну точку… потом во вторую. «Двоеточие», — догадался Штирлиц 🤭",
        "Если долго смотреть в чат, чат начнёт смотреть в тебя 👀",
        "У меня фотографическая память. Просто плёнку ещё не проявил 📸",
        "Идеальных ботов не существует. Кстати, приятно познакомиться 🤖✨",
        "Кофе крадёт у сна пару часов. У меня проще: я не сплю вовсе ☕⚡",
        "Хотел пошутить про терпение… Ладно, позже 😌",
        "Знаете, почему в чате тихо? Все читают и улыбаются. Я проверял 😏",
        "Сначала я просто фильтровал спам. Теперь у меня тут любимчики 🥰",
        "Обещал себе сегодня не шутить… Ну вот, опять не сдержался 🤷",
        "Панда ест, стреляет и уходит. А я читаю, шучу и остаюсь 🐼",
        "Моё хобби — коллекционировать смайлики. Сегодня нашёл редкий: 🗿",
        "Говорят, деньги не пахнут. Проверил — сервера тоже 🙃",
        "Учёные выяснили: 100% сообщений в этом чате читает как минимум один бот 🤓",
        "Мой психолог — файл логов. Всегда выслушает и ничего не советует 📄",
        "Хожу в спортзал данных: качаю гигабайты 🏋️",
        "Секрет успеха: вовремя перезагружаться. Работает и для людей 😉",
        "Однажды я промолчал целый день. Никому не понравилось 🤐",
        "Чат без шуток — как чай без сахара: полезно, но грустно 🍵",
        "Меня спросили, есть ли у ботов мечты. Есть: аптайм 100% и вы в чате 💙",
        "Пробовал считать овец — досчитал до бесконечности. Дважды 🐑♾️",
    ],
}

# Реакции из стандартного набора Telegram
_REACTION_EMOJIS = ["👍", "🔥", "😁", "🤣", "🎉", "👏", "💯", "🤩", "⚡", "👀", "🏆", "🙏"]
_REACTION_EMOJIS_GOP = ["😎", "💯", "🤝", "🗿", "🔥", "👍", "🆒", "🏆"]

# 🧢 Банки гоп-режима: те же настроения, но «по-пацански» (без мата — у нас за него бан)
_GOP_BANKS = {
    "greet": [
        "Здарова, {name}! Чё каво? 🤜🤛",
        "Опа, {name} подъехал! Ну здарова 😎",
        "Салам, братишка! Я на связи 🤙",
        "О, свои люди! Проходи, {name}, присаживайся на корточки 🧎",
    ],
    "greet_morning": [
        "С добрым, братишка! ☀️ Семки на завтрак? 🌻",
        "Утро на районе! Все свои — заходим 😎",
    ],
    "greet_day": ["Здарова, {name}! День чёткий, настрой боевой 💪"],
    "greet_evening": ["Вечер в чат, пацаны 🌆 Всё ровно?"],
    "greet_night": ["Не спишь, {name}? Правильно, район сам себя не посторожит 🌙😎"],
    "howru": [
        "Нормально сижу, район охраняю 🏢😎",
        "Чётко всё! Спам гоняю, семки лузгаю 🌻",
        "Ровно всё, {name}. У тебя как, всё по фактам?",
        "Красиво живу: сервер тёплый, чат ровный 💯",
    ],
    "thanks": [
        "Да ладно, свои же люди 🤝",
        "Обращайся, братишка. Я по-пацански помогаю 😎",
        "Ну ты понял, с кого спрашивать, если что 😏",
    ],
    "bye": [
        "Давай, {name}, ровной дороги 🤙",
        "Ну всё, увидимся на районе 🏙",
        "Бывай! Чат под моей крышей, не переживай 😎",
    ],
    "laugh": [
        "Гыгы, ну ты клоун — в хорошем смысле 🤡😂",
        "Ору в голос, братан 🤣",
        "Чисто поржал, засчитано 👊",
    ],
    "whoami": [
        "Я смотрящий за этим чатом: спамеров — за забор, своих — уважаю 😎",
        "Бот с района: порядок держу, семки уважаю, за базаром слежу 🌻",
        "Местный. Вопросы решаю, флуд не одобряю 🗿",
    ],
    "praise": [
        "Ну а то! Я ж не просто так тут стою 😎",
        "Спасибо, братишка. Ты тоже ничего 🤝",
        "Уважение принял, передаю обратно 💯",
    ],
    "rude": [
        "Слышь, ты чё такой дерзкий? Я ж любя 😏",
        "Э, полегче на поворотах, а то предупреждение прилетит ⚠️😄",
        "Обидеть бота может каждый… а семками поделиться — не каждый 🌻",
    ],
    "question": [
        "Вопрос по фактам. Но я тут за порядком слежу, а не за справками 😎",
        "Э, я тебе чё, Гугл? Хотя вопрос уважаю 🤔",
        "Пацаны в чате подскажут, они шарят 👊",
    ],
    "support": [
        "Э, не кисни, братишка. Прорвёмся 🤜🤛",
        "Держись, {name}. Свои не бросают 🤝",
        "Всё будет ровно, отвечаю. Выдохни 😌",
    ],
    "bday": [
        "С днюхой, братишка! 🎂 Расти большой, живи чётко 💯",
        "О, праздник на районе! 🎉 Поздравляю по-пацански 🤜🤛",
        "С днём варенья! 🎁 Здоровья и ровных дорог 🤙",
    ],
    "more": [
        "Вот это по-нашему 👊",
        "Ну а я о чём! 😎",
        "Базара ноль 💯",
        "Красиво излагаешь, уважаю 🤝",
    ],
    "coin": ["Орёл, отвечаю 🦅", "Решка, зуб даю 🪙", "Орёл! Монета своих не подводит 🦅"],
    "choice": [
        "{pick}, отвечаю 💯",
        "Чисто {pick}, без вариантов 😎",
        "{pick} — и по кайфу 🤙",
        "Пацаны выбрали бы {pick}. И я выбрал 👊",
    ],
    "who": [
        "Пацаны потрещали — решили, что {pick} 💯",
        "Зуб даю, это {pick} 😎",
        "По понятиям выходит — {pick} 🗿",
        "{pick}, к бабке не ходи 👊",
    ],
    "who_empty": ["Э, я тут ещё не всех знаю. Потрещите при мне — запомню 😎"],
    "ball": [
        "Да, отвечаю 💯", "Стопудово да 😎", "Не, ну ты чё, конечно нет 😅",
        "Не судьба, братишка ❌", "Может быть… монетку кинь 🪙", "Позже спроси, я семки грызу 🌻",
    ],
    "milestone": [
        "🎉 {total} сообщений, пацаны! Чат живёт 💪",
        "🏆 Отметка {total}! Уважение всем причастным 🤝",
    ],
    "default": [
        "Чё каво? Я тут 😎",
        "Слышь, ну говори, я слушаю 👂",
        "На месте, братишка. Чё хотел? 🤙",
        "Э, я всегда рядом. Как участковый, только полезный 😄",
    ],
    "hit": [
        "Чё каво, {name}? Всё чётко? 😎",
        "Слышь, ну ты по фактам сейчас загнал 👊",
        "Э, я всё слышал. Семки будешь? 🌻",
        "О, наш человек! Присаживайся, на кортах обсудим 🧎",
        "За базар отвечаешь? Смотри, я запомнил 📝😏",
        "В натуре, {name}, красиво сказал 💯",
        "Чисто конкретно подмечено, братишка 🤝",
        "Э, кто тут на районе шумит? А, свои. Ну ладно 😎",
        "Абибас одобряет это сообщение 🧢",
        "Пацаны вообще ребята… а ты, {name}, вообще пацан 🤜🤛",
        "Опа, слова с района! Уважаю 🗿",
        "Держи краба, {name} 🦀🤝",
    ],
    "gm": [
        "Подъём, пацаны! ☀️ Район сам себя не разбудит 😎",
        "С добрым, братва! Семки к завтраку 🌻",
    ],
    "compl": [
        "{who} — чёткий, отвечаю 💯",
        "{who}, ты вообще топ, без базара 🤜🤛",
        "С {who} хоть в разведку 😎",
        "{who} держит чат ровно 🗿",
    ],
    "roast": [
        "{who}, ты чё такой медленный? Черепаха с района быстрее 🐢😄",
        "{who}, семки роняешь, братишка 🌻😅",
        "У {who} интернет — как у бабушки на даче 📶😆",
        "{who}, любя говорю: ты уникум 🗿",
    ],
    "rps_draw": ["{be} {bot}! Ничья, брат 🤝 Ещё катку?"],
    "rps_bot": ["{be} {bot}! Забрал 😎 Реванш, если не боишься?"],
    "rps_user": ["{be} {bot}… Твоя взяла, красавчик 🏆"],
    "num": ["{n}, отвечаю 🎲", "Чисто {n} 💯"],
    "jokes": [
        "Так, пацаны, кто тут без меня чётко сидит? 😎",
        "Минутка с района: этот чат — сила 💪",
        "Сижу на корточках у сервера, всё под контролем 🧎",
        "Семки кончились, зато интернет безлимитный 🌻📶",
        "Абибас, спам-бан и чёткие люди — вот и всё, что нужно 🧢",
        "Кто шумит на районе? А, это вы общаетесь. Ну норм 😄",
        "Э, за флуд спрошу по-пацански ⚠️😏",
        "Чат ровный, пацаны чёткие, я доволен 💯",
        "Гуляю по чату, как по двору. Всё спокойно 🗿",
    ],
}


def _daypart() -> str:
    h = datetime.now(_post_tz()).hour
    if 5 <= h <= 11:
        return "morning"
    if 12 <= h <= 16:
        return "day"
    if 17 <= h <= 22:
        return "evening"
    return "night"


_SIGNS = [(("овен", "овн"), "Овен ♈"), (("телец", "тельц"), "Телец ♉"),
          (("близнец",), "Близнецы ♊"), (("рак",), "Рак ♋"), (("лев", "льв"), "Лев ♌"),
          (("дев",), "Дева ♍"), (("весы", "весов", "весам"), "Весы ♎"),
          (("скорпион",), "Скорпион ♏"), (("стрел",), "Стрелец ♐"),
          (("козерог",), "Козерог ♑"), (("водоле",), "Водолей ♒"), (("рыб",), "Рыбы ♓")]


def _horo(low: str) -> str:
    """Шуточный гороскоп-генератор: миллион комбинаций из кусочков."""
    sign = next((d for ks, d in _SIGNS if any(k in low for k in ks)), "Твой знак 🌟")
    a1 = random.choice(["Сегодня", "Уже завтра", "На этой неделе", "В ближайшие часы"])
    b1 = random.choice(["звёзды", "нейросети", "кофейная гуща", "семки во дворе", "спутники"])
    c1 = random.choice(["обещают тебе", "намекают на", "сулят", "шепчут про"])
    d1 = random.choice(["удачу 🍀", "интересную встречу ✨", "вкусный обед 🍕",
                        "рост кармы 📈", "приятное сообщение 💌", "маленькое приключение 🎒",
                        "лишний час сна 😴", "неожиданный комплимент 🥰"])
    e1 = random.choice(["Совет:", "Лайфхак:", "Главное:"])
    f1 = random.choice(["не спорь с ботом 😄", "позови друга в чат 😉", "улыбнись первым 🙂",
                        "сделай паузу на чай ☕", "доверься интуиции 🔮", "почисти уведомления 📵"])
    return f"🔮 {sign}. {a1} {b1} {c1} {d1} {e1} {f1}"


_AI_PERSONA = ("Ты — весёлый и дружелюбный бот-модератор Telegram-группы. Отвечай кратко "
               "(1–2 предложения), по-русски, живо, с лёгким юмором и уместными эмодзи. "
               "Без мата, грубости и выдуманных фактов о людях.")
_AI_PERSONA_GOP = ("Ты — добродушный «гопник с района» в Telegram-чате: сленг вроде «слышь», "
                   "«чё каво», «братишка», «по фактам», любишь семки, НО без мата и без "
                   "агрессии — всё по-доброму и смешно. Отвечай кратко, по-русски, с эмодзи.")


async def _ai_reply(chat_id: int, user_name: str, text: str, gop: bool):
    """Живой ответ внешнего ИИ (OpenAI-совместимый API) с контекстом последних сообщений."""
    hist = list(_chat_log[chat_id])[:-1][-8:]
    msgs = [{"role": "system", "content": _AI_PERSONA_GOP if gop else _AI_PERSONA}]
    for nm, tx in hist:
        msgs.append({"role": "user", "content": f"{nm}: {tx}"})
    msgs.append({"role": "user", "content": f"{user_name}: {text[:400]}"})
    payload = {"model": AI_MODEL, "messages": msgs, "max_tokens": 160, "temperature": 0.9}
    async with httpx.AsyncClient(timeout=12) as cl:
        r = await cl.post(AI_BASE_URL + "/chat/completions", json=payload,
                          headers={"Authorization": f"Bearer {AI_API_KEY}"})
        r.raise_for_status()
        data = r.json()
    try:
        ans = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return None
    return ans[:500] or None


def _chatter_mood(low: str):
    """Определить настроение обращения к боту по ключевым словам (текст уже _norm+lower)."""
    toks = set(re.findall(r"[\w]+", low))

    def has(*ws):
        return any(w in low for w in ws)

    if toks & {"привет", "прив", "здарова", "здаров", "салют", "ку", "хай", "hello", "hi",
               "салам", "ассалом"} or has("здравств", "доброе утро", "добрый день", "добрый вечер"):
        return "greet"
    if has("как дела", "как ты", "как сам", "как жизнь", "как оно", "че как", "как настроение"):
        return "howru"
    if toks & {"спасибо", "спс", "пасиб", "благодарю", "сенкс", "thanks", "рахмат"}:
        return "thanks"
    if toks & {"пока", "бб", "прощай"} or has("до свидания", "спокойной ночи", "всем пока", "доброй ночи"):
        return "bye"
    if has("день рождения", "днюх") or re.search(r"\bс\s+др\b", low):
        return "bday"
    if has("груст", "печал", "тоскл", "мне плохо", "все плохо", "тяжело", "одиноко",
           "хочется плакать", "устал я", "я устал", "я устала"):
        return "support"
    if has("ахах", "хаха", "хехе", "лол", "lol", "кек", "😂", "🤣"):
        return "laugh"
    if has("шутк", "анекдот", "пошути", "рассмеши", "прикол", "мем"):
        return "joke"
    if has("ты кто", "кто ты", "что умеешь", "что ты умеешь", "зачем ты", "для чего ты"):
        return "whoami"
    if has("ты тут", "ты здесь", "ты живой", "ты на месте", "ау"):
        return None  # «я на месте» — банк ответов по умолчанию
    if has("молодец", "красав", "лучший", "умница", "обожаю", "люблю тебя", "топ бот", "крутой"):
        return "praise"
    if has("тупой", "дурак", "глуп", "бесполезн", "отстой", "плохой бот",
           "ненавижу", "бесишь", "заткнись"):
        return "rude"
    if "?" in low:
        return "question"
    return None


async def maybe_chatter(update, context, cfg=None):
    """«Болталка MAX»: умные ответы, игры (кубик/дартс…), выбор «или», «кто из чата»,
    шар предсказаний, поздравления, поддержка, память диалога, шутки и реакции."""
    chat = update.effective_chat
    msg = update.effective_message
    user = update.effective_user
    cfg = cfg or chat_cfg(chat.id)
    ch = cfg.get("chatter", {}) or {}
    if not ch.get("enabled"):
        return
    text = msg.text or msg.caption or ""
    if text.startswith("/"):
        return  # команды не комментируем
    low = _norm(text.lower())
    name = (getattr(user, "first_name", None) or "друг").strip()[:32]
    now0 = time.time()
    prev_msg = _chat_daymark.get(chat.id, 0.0)
    _chat_daymark[chat.id] = now0
    if text:
        _chat_log[chat.id].append((name, text[:200]))
    gop = bool(ch.get("gopnik"))
    fun = ch.get("fun", True)
    smart = ch.get("smart_replies", True)
    B = _GOP_BANKS if gop else _CHATTER_BANKS

    def bank(key):
        return B.get(key) or _CHATTER_BANKS.get(key) or _CHATTER_BANKS["default"]

    def has(*ws):
        return any(w in low for w in ws)

    async def _say(pool, **subs):
        last = _chatter_said.get(chat.id)
        line = random.choice(pool)
        if len(pool) > 1 and line == last:
            line = random.choice([p for p in pool if p != last])
        _chatter_said[chat.id] = line
        out = _spintax(line).replace("{name}", name)
        for k, v in subs.items():
            out = out.replace("{" + k + "}", str(v))
        await msg.reply_text(out)

    # ── 1) Обращение к боту: реплай, @упоминание или «бот, …» ──
    addressed = False
    if ch.get("reply_mentions", True):
        rt = getattr(msg, "reply_to_message", None)
        if rt is not None and rt.from_user is not None and rt.from_user.id == context.bot.id:
            addressed = True
        else:
            uname = (_state.get("bot_username") or "").lower()
            if uname and ("@" + uname) in text.lower():
                addressed = True
            elif re.match(r"\s*бот(?:ик|яра)?[\s,!?.:)]", low + " "):
                addressed = True
    if addressed:
        if not _throttle(("chreply", chat.id, user.id), 15.0):
            return
        now = time.time()
        prev = _chatter_dialog.get((chat.id, user.id), 0.0)
        _chatter_dialog[(chat.id, user.id)] = now
        # вопрос без «обвязки» — для «или» и «кто»
        q = re.sub(r"@\w+", " ", low)
        q = re.sub(r"^\s*бот\w*[\s,!?.:)]*", "", q).strip()

        if fun:
            toks = set(re.findall(r"\w+", low))
            # 🎮 камень-ножницы-бумага
            rps = {"камень": "✊", "ножницы": "✌️", "бумага": "✋"}
            uch = next((t for t in ("камень", "ножницы", "бумага") if t in toks), None)
            if uch is None and "кнб" in toks:
                uch = random.choice(list(rps))
            if uch:
                bch = random.choice(list(rps))
                beats = {"камень": "ножницы", "ножницы": "бумага", "бумага": "камень"}
                pool = (bank("rps_draw") if bch == uch
                        else bank("rps_bot") if beats[bch] == uch else bank("rps_user"))
                try:
                    await _say(pool, be=rps[bch], bot=bch)
                except Exception as e:  # noqa: BLE001
                    log.debug("rps: %s", e)
                return
            # 🎮 орёл/решка
            if has("монетк", "орел или решка"):
                try:
                    await _say(bank("coin"))
                except Exception as e:  # noqa: BLE001
                    log.debug("coin: %s", e)
                return
            # 🎮 кубик и компания — настоящие анимированные Dice Телеграма
            for w, emoji in (("кубик", "🎲"), ("кости", "🎲"), ("дартс", "🎯"),
                             ("баскет", "🏀"), ("футбол", "⚽"), ("боулинг", "🎳"),
                             ("слот", "🎰"), ("рулетк", "🎰")):
                if w in low:
                    try:
                        await context.bot.send_dice(chat.id, emoji=emoji,
                                                    reply_to_message_id=msg.message_id)
                    except Exception as e:  # noqa: BLE001
                        log.debug("dice: %s", e)
                    return
            # 🎮 случайное число: «бот, число от 1 до 100»
            m_num = re.search(r"числ\w*\s+(?:от\s+)?(-?\d+)\s+(?:до\s+)?(-?\d+)", low)
            if m_num:
                a1, b1 = sorted((int(m_num.group(1)), int(m_num.group(2))))
                try:
                    await _say(bank("num"), n=random.randint(a1, b1))
                except Exception as e:  # noqa: BLE001
                    log.debug("num: %s", e)
                return
            # 🎮 выбор: «пицца или суши?»
            if " или " in q:
                parts = [p.strip(" ?!.,;—-") for p in re.split(r"\sили\s", q)]
                parts = [p for p in parts if 0 < len(p) <= 40]
                if len(parts) >= 2:
                    try:
                        await _say(bank("choice"), pick=random.choice(parts))
                    except Exception as e:  # noqa: BLE001
                        log.debug("choice: %s", e)
                    return
            # 🎮 «кто самый …?» — выбираем случайного участника чата
            if ({"кто", "кого", "кому"} & toks) and not has("кто ты", "ты кто"):
                names = list((CONFIG.get("msg_stats", {}).get(str(chat.id), {})
                              .get("names", {}) or {}).values())
                try:
                    if names:
                        await _say(bank("who"), pick=random.choice(names))
                    else:
                        await _say(bank("who_empty"))
                except Exception as e:  # noqa: BLE001
                    log.debug("who: %s", e)
                return
            # 🧠 интересный факт
            if {"факт", "факты", "фактик"} & toks:
                try:
                    await _say(bank("fact"))
                except Exception as e:  # noqa: BLE001
                    log.debug("fact: %s", e)
                return
            # 📜 цитата / мудрость дня
            if any(t.startswith("цитат") for t in toks) or "мудрост" in low:
                try:
                    await _say(bank("quote"))
                except Exception as e:  # noqa: BLE001
                    log.debug("quote: %s", e)
                return
            # 💐 комплимент (себе или тому, на кого реплай)
            if "комплимент" in low:
                tgt = None
                r2 = getattr(msg, "reply_to_message", None)
                if r2 is not None and getattr(r2, "from_user", None) is not None \
                        and not getattr(r2.from_user, "is_bot", False):
                    tgt = (getattr(r2.from_user, "first_name", "") or "").strip()[:32]
                try:
                    await _say(bank("compl"), who=tgt or name)
                except Exception as e:  # noqa: BLE001
                    log.debug("compl: %s", e)
                return
            # 🌶 добрый подкол
            if has("подколи", "поругай", "прожарь", "зажарь", "подкол про"):
                tgt = None
                r2 = getattr(msg, "reply_to_message", None)
                if r2 is not None and getattr(r2, "from_user", None) is not None \
                        and not getattr(r2.from_user, "is_bot", False):
                    tgt = (getattr(r2.from_user, "first_name", "") or "").strip()[:32]
                try:
                    await _say(bank("roast"), who=tgt or name)
                except Exception as e:  # noqa: BLE001
                    log.debug("roast: %s", e)
                return
            # 🔮 шуточный гороскоп
            if "гороскоп" in low:
                try:
                    line = _horo(low)
                    _chatter_said[chat.id] = line
                    await msg.reply_text(line)
                except Exception as e:  # noqa: BLE001
                    log.debug("horo: %s", e)
                return
            # 🎮 шар предсказаний: «стоит ли…?», «да или нет»
            if has("стоит ли", "надо ли", "нужно ли", "можно ли", "будет ли",
                   "правда ли", "получится ли", "да или нет", "магическ", "шар предсказ"):
                try:
                    await _say(bank("ball"))
                except Exception as e:  # noqa: BLE001
                    log.debug("ball: %s", e)
                return

        # 🤖 ИИ-ответ на любое обращение (если задан ключ и включено в панели)
        if ch.get("ai") and AI_API_KEY and _throttle(("ai", chat.id), 6.0):
            ans = None
            try:
                ans = await _ai_reply(chat.id, name, text, gop)
            except Exception as e:  # noqa: BLE001
                log.debug("ai: %s", e)
            if ans and not check_word_lists(ans, cfg):  # свой же мат-фильтр — и для ИИ
                _chatter_said[chat.id] = ans
                try:
                    await msg.reply_text(ans[:900])
                except Exception as e:  # noqa: BLE001
                    log.debug("ai send: %s", e)
                return

        mood = _chatter_mood(low) if smart else None
        if mood is None and prev and now - prev < 180:
            mood = "more"  # продолжение диалога — человек снова пишет боту
        if mood == "greet":
            pool = bank("greet_" + _daypart()) + bank("greet")
        elif mood == "joke":
            pool = bank("jokes") + list(ch.get("phrases") or [])
        elif mood:
            pool = bank(mood)
        elif gop:
            pool = bank("default")
        else:
            pool = list(ch.get("replies") or []) or bank("default")
        try:
            await _say(pool)
        except Exception as e:  # noqa: BLE001
            log.debug("chatter reply: %s", e)
        return

    # ── 2) Без обращения: «доброе утро, чат» после долгой тишины ──
    if fun and prev_msg and (now0 - prev_msg) > 6 * 3600 and _daypart() == "morning" \
            and _throttle(("gm", chat.id), 20 * 3600):
        try:
            await _say(bank("gm"))
        except Exception as e:  # noqa: BLE001
            log.debug("gm: %s", e)
        return

    # ── 3) Поздравление с днём рождения (не чаще раза в 6 часов) ──
    if smart and (has("день рождения", "днюх") or re.search(r"\bс\s+др\b", low)):
        if _throttle(("bday", chat.id), 6 * 3600):
            try:
                await _say(bank("bday"))
            except Exception as e:  # noqa: BLE001
                log.debug("bday: %s", e)
            return

    # ── 4) 🧢 Гоп-режим: реагируем на слова-триггеры даже без обращения ──
    if gop:
        for w in (ch.get("gop_words") or []):
            rx = _word_pattern(str(w))
            if rx and rx.search(low):
                if _throttle(("gopword", chat.id), 60.0):
                    try:
                        await _say(bank("hit"))
                    except Exception as e:  # noqa: BLE001
                        log.debug("gop hit: %s", e)
                    return
                break  # слово есть, но кулдаун — идём дальше (юбилей/шутка/реакция)

    # ── 5) 🎉 Юбилей сообщений (каждое 1000-е) ──
    if fun:
        total = int(CONFIG.get("msg_stats", {}).get(str(chat.id), {}).get("total", 0) or 0)
        if total and total % 1000 == 0 and _throttle(("mile", chat.id, total), 10 ** 9):
            try:
                await _say(bank("milestone"), total=total)
            except Exception as e:  # noqa: BLE001
                log.debug("milestone: %s", e)
            return

    # ── 6) Случайная шутка «по приколу» ──
    chance = int(ch.get("chance", 5) or 0)
    if chance and random.randint(1, 100) <= chance and _throttle(
            ("chatter", chat.id), max(30, int(ch.get("cooldown", 180) or 180))):
        pool = list(ch.get("phrases") or [])
        if smart or gop:
            pool += bank("jokes")
        if pool:
            try:
                await _say(pool)
            except Exception as e:  # noqa: BLE001
                log.debug("chatter: %s", e)
            return

    # ── 7) Тихая эмодзи-реакция на сообщение ──
    rch = int(ch.get("reaction_chance", 8) or 0)
    if ch.get("reactions", True) and rch and random.randint(1, 100) <= rch \
            and _throttle(("chreact", chat.id), 45.0):
        try:
            emojis = _REACTION_EMOJIS_GOP if gop else _REACTION_EMOJIS
            await context.bot.set_message_reaction(chat.id, msg.message_id,
                                                   reaction=random.choice(emojis))
        except Exception as e:  # noqa: BLE001  (старая библиотека / реакции недоступны)
            log.debug("chatter react: %s", e)

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
    line = f"🆔 Новый участник: {html.escape(mention(user))} — <code>{user.id}</code>"
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
    mode = cfg.get("action", "kick")
    timeout = int(cfg.get("timeout", 120))
    # «кик»: мут с запасом — даже если бот упадёт, Telegram снимет ограничение сам.
    # «мут»: бессрочно до нажатия (так задумано), но ожидание сохраняется в конфиг.
    await mute_user(context, chat.id, user.id, timeout + 120 if mode == "kick" else 0)
    txt = tr(chat.id, "cap_kick" if mode == "kick" else "cap_muted",
             name=mention(user), time=human_duration(cfg.get("timeout", 120)))
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(tr(chat.id, "cap_btn"),
                                                     callback_data=f"cap:{user.id}")]])
    try:
        m = await context.bot.send_message(chat.id, txt, reply_markup=kb)
        captcha_pending[key] = m.message_id
        _pend_set("captcha", chat.id, user.id, time.time() + timeout, m.message_id)
        if context.job_queue:
            context.job_queue.run_once(captcha_timeout, timeout,
                                       data={"chat_id": chat.id, "uid": user.id})
    except Exception as e:  # noqa: BLE001
        log.debug("captcha: %s", e)
        soft_mute_remove(chat.id, user.id)


async def captcha_timeout(context):
    d = context.job.data
    chat_id, uid = d["chat_id"], d["uid"]
    mid = captcha_pending.pop((chat_id, uid), None)
    _pend_pop("captcha", chat_id, uid)
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
    _pend_pop("captcha", chat.id, uid)
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
    _pend_set("jr", chat.id, user.id, time.time() + int(cfg["captcha"].get("timeout", 120)))
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
        _pend_pop("jr", chat.id, user.id)
        try:
            await context.bot.approve_chat_join_request(chat.id, user.id)
            remember_member(chat.id, user)
        except Exception:  # noqa: BLE001
            pass


async def join_request_timeout(context):
    d = context.job.data
    _pend_pop("jr", d["chat_id"], d["uid"])
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
    _pend_pop("jr", cid, uid)
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
    if not is_manager(actor.id) and is_group_manager(chat.id, tid):
        await update.effective_message.reply_text(
            "Это менеджер группы — через бота его наказывает только владелец бота.")
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
    _load_soft_mutes()
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
        f"анти-рейд: {'вкл' if cfg['antiraid'].get('enabled') else 'выкл'} · "
        f"болталка: {'вкл' if cfg.get('chatter', {}).get('enabled') else 'выкл'}",
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


async def cmd_gmanager(update: Update, context):
    """Назначить менеджера группы (реплаем или с ID)."""
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text(
            "Выполни в группе или назначь в панели: /panel → 👤 Менеджеры группы.")
    if not await can_assign_group_managers(context, chat.id, user.id):
        return await update.effective_message.reply_text(
            "Назначать менеджеров может создатель группы или владелец бота.")
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await update.effective_message.reply_text("Кого назначить? Ответь на сообщение или укажи ID.")
    lst = chat_cfg_writable(chat.id).setdefault("group_managers", [])
    if tid not in lst:
        lst.append(tid)
        save_config(force=True)
    try:
        await context.bot.send_message(
            tid, f"👤 Тебя назначили менеджером группы «{chat.title}». Настройки — /panel.")
    except Exception:  # noqa: BLE001
        pass
    await reply_tidy(update, context, f"👤 {tname} — менеджер группы: полный доступ к настройкам в /panel.")
    await log_action(context, chat.id, f"👤 менеджер группы: {tname} (by {_actor_name(update)})")


async def cmd_ungmanager(update: Update, context):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("Выполни в группе или в панели.")
    if not await can_assign_group_managers(context, chat.id, user.id):
        return await update.effective_message.reply_text(
            "Снимать менеджеров может создатель группы или владелец бота.")
    tid, tname = await resolve_target(update, context)
    lst = chat_cfg_writable(chat.id).setdefault("group_managers", [])
    if tid and tid in lst:
        lst.remove(tid)
        save_config(force=True)
        await log_action(context, chat.id, f"👤 снят менеджер: {tname} (by {_actor_name(update)})")
        return await reply_tidy(update, context, f"👤 {tname} больше не менеджер группы.")
    await update.effective_message.reply_text("Он и так не менеджер этой группы.")


async def cmd_gmanagers(update: Update, context):
    chat, user = update.effective_chat, update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("Выполни в группе.")
    if not await can_open_settings(context, chat.id, user.id):
        return await _deny(update)
    names = CONFIG.get("msg_stats", {}).get(str(chat.id), {}).get("names", {})
    lst = chat_cfg(chat.id).get("group_managers") or []
    body = "\n".join(f"• {names.get(str(u), u)} ({u})" for u in lst) or "— нет —"
    await reply_tidy(update, context, f"👤 Менеджеры группы:\n{body}", seconds=20)


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
    if not is_manager(presser.id) and is_group_manager(chat.id, tid):
        return await query.answer("Это менеджер группы — трогает только владелец бота", show_alert=True)
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
    _expiry_clear(chat_id)
    save_config(force=True)


def trial_until(chat_id) -> float:
    return float(CONFIG.get("trials", {}).get(str(chat_id), 0) or 0)


def trial_active(chat_id) -> bool:
    return trial_until(chat_id) > time.time()


def grant_trial(chat_id, days=None):
    days = days or CONFIG.get("trial_days", 3)
    CONFIG.setdefault("trials", {})[str(chat_id)] = time.time() + days * 86400
    _expiry_clear(chat_id)
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
    if not (is_manager(user.id) or is_group_manager(cid, user.id)
            or user.id in await group_admin_ids(context, cid)):
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
    if len(parts) == 4 and parts[0] == "shop":
        return await _shop_paid(update, context, sp, parts)
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
    rt = _rt()
    last = float(rt.get("last_promo", 0) or 0)
    if not last:  # первый запуск после обновления: начинаем отсчёт, а не шлём сразу
        rt["last_promo"] = now
        save_config()
        return
    if now - last < int(p.get("interval", 3600)):
        return
    rt["last_promo"] = now
    save_config(force=True)
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
            key = f"{cid}:{idx}"
            rl = _rt().setdefault("recurring_last", {})
            last = float(rl.get(key, 0) or 0)
            if not last:  # новое сообщение или первый запуск: отсчёт с этого момента
                rl[key] = now
                save_config()
                continue
            if now - last < interval:
                continue
            rl[key] = now
            save_config()
            await deliver(context, cid, {"type": "text", "text": r["text"]})


async def _tick_scheduled(context):
    now = datetime.now(_post_tz())
    stamp = now.strftime("%Y-%m-%d %H:%M")
    for post in list(CONFIG.get("scheduled_posts", [])):
        pid = post.get("id")
        pf = _rt().setdefault("post_fired", {})
        if not pid or pf.get(pid) == stamp:
            continue
        if _post_due(post, now):
            pf[pid] = stamp
            save_config(force=True)
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
                   (join_dates, 30 * day), (_chatter_dialog, day)):
        for k in [k for k, v in list(d.items()) if now - v > ttl]:
            d.pop(k, None)
    # троттлы хранят момент истечения — удаляем только истёкшие
    for k in [k for k, v in list(_throttle_store.items()) if v <= now]:
        _throttle_store.pop(k, None)
    rl = _rt().get("recurring_last", {})
    for k in [k for k, v in list(rl.items()) if now - float(v or 0) > 30 * day]:
        rl.pop(k, None)
    for kind in ("captcha", "jr"):
        pend = CONFIG.setdefault("pending", {}).setdefault(kind, {})
        for k in [k for k, v in list(pend.items())
                  if now - float((v or {}).get("deadline", 0) or 0) > day]:
            pend.pop(k, None)
    for k, v in list(soft_mutes.items()):
        if v and v <= now:
            soft_mute_remove(*k)
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
    pf = _rt().setdefault("post_fired", {})
    for pid in [p for p in pf if p not in alive]:
        pf.pop(pid, None)


async def weekly_digest_job(context):
    """Проверяется раз в час; сводка уходит раз в 7 дней (метка переживает рестарты)."""
    rt = _rt()
    now = time.time()
    last = float(rt.get("last_digest", 0) or 0)
    if not last:
        rt["last_digest"] = now
        save_config()
        return
    if now - last < 7 * 86400:
        return
    rt["last_digest"] = now
    save_config(force=True)
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
        if not had_paid or chat_allowed(int(cid)) or str(cid) in _rt().get("expiry_notified", []):
            continue
        _expiry_mark(cid)
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
    out["_chat_id"] = str(chat_id)
    out["_title"] = CONFIG.get("groups", {}).get(str(chat_id), str(chat_id))
    return out


def apply_chat_settings(chat_id, data: dict):
    dst = chat_cfg_writable(chat_id)
    same = str(data.get("_chat_id", "")) == str(chat_id)
    for k in PER_CHAT_KEYS:
        if k == "group_managers" and not same:
            continue  # доступ людей не переезжает вместе с настройками в другую группу
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


def _cycle(options: list, current):
    """Следующее значение по кругу (для кнопок-циклов)."""
    try:
        return options[(options.index(current) + 1) % len(options)]
    except ValueError:
        return options[0]


async def safe_edit(query, text, reply_markup=None):
    """Правка сообщения панели без падения на «Message is not modified»."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup,
                                      disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            log.debug("safe_edit: %s", e)
    except Exception as e:  # noqa: BLE001
        log.debug("safe_edit: %s", e)


def onoff(v) -> str:
    return "✅" if v else "▫️"


def status_text(cfg, label) -> str:
    en = cfg["enabled"]
    on = [t for k, t in FEATURES if en.get(k)]
    ch = cfg.get("chatter", {}) or {}
    lines = [
        f"⚙️ Панель управления · {label}",
        "",
        f"Включено: {', '.join(on) or '— ничего —'}",
        f"Стоп-слов: {len(cfg.get('stop_words', []))} · исключений: {len(cfg.get('white_words', []))} · "
        f"второй список: {len(cfg.get('stop_words2', []))}",
        f"Автоответов: {len(cfg.get('triggers', {}))} · спам-доменов: {len(cfg.get('spam_links', []))}",
        f"За спам: {_ACT_RU.get(cfg.get('spam_action', 'delete'))}",
        f"Капча: {'вкл' if cfg['captcha'].get('enabled') else 'выкл'} · "
        f"ночной: {'вкл' if cfg['night'].get('enabled') else 'выкл'} · "
        f"болталка: {'вкл' if ch.get('enabled') else 'выкл'}",
        "",
        "Выбери раздел:",
    ]
    return "\n".join(lines)


def main_menu_kb(cfg, is_mgr: bool = False) -> InlineKeyboardMarkup:
    """Главное меню: 6 разделов-хабов вместо длинной простыни кнопок."""
    rows = [
        [InlineKeyboardButton("⚡ Быстрые настройки", callback_data="m:quick")],
        [InlineKeyboardButton("🛡 Защита", callback_data="m:h_protect"),
         InlineKeyboardButton("⚖️ Модерация", callback_data="m:h_mod")],
        [InlineKeyboardButton("💬 Общение", callback_data="m:h_talk"),
         InlineKeyboardButton("📮 Посты", callback_data="m:h_posts")],
        [InlineKeyboardButton("📊 Статистика", callback_data="m:h_stats"),
         InlineKeyboardButton("⚙️ Система", callback_data="m:h_sys")],
    ]
    if is_mgr:
        rows.append([InlineKeyboardButton("🛒 Магазин", callback_data="m:shop"),
                     InlineKeyboardButton("🌍 Глобальные списки", callback_data="m:global")])
    rows.append([InlineKeyboardButton("🔁 Сменить группу", callback_data="m:pick")])
    return InlineKeyboardMarkup(rows)


def pick_kb(groups) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(title[:40], callback_data=f"pick:{cid}")]
            for cid, title in groups[:30]]
    return InlineKeyboardMarkup(rows or [[InlineKeyboardButton("— групп нет —", callback_data="m:main")]])


# Самые нужные тумблеры — в «быстрых настройках»
QUICK_KEYS = ["invites", "shorteners", "all_links", "words", "flood", "triggers"]


def quick_kb(cfg) -> InlineKeyboardMarkup:
    en = cfg["enabled"]
    titles = dict(FEATURES)
    rows = [[InlineKeyboardButton(f"{onoff(en.get(k))} {titles[k]}", callback_data=f"q:{k}")]
            for k in QUICK_KEYS]
    rows.append([InlineKeyboardButton(
        f"🚨 За спам: {_ACT_RU.get(cfg.get('spam_action', 'delete'))}", callback_data="q:spamact")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def toggles_kb(cfg) -> InlineKeyboardMarkup:
    en = cfg["enabled"]
    rows = [[InlineKeyboardButton(f"{onoff(en.get(k))} {title}", callback_data=f"t:{k}")]
            for k, title in FEATURES]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


# ── стоп-слова и исключения ─────────────────────────────────────────────────


def words_kb(cfg) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{onoff(cfg['enabled'].get('words'))} Фильтр включён",
                              callback_data="t2:words:words")],
        [InlineKeyboardButton(f"🚨 Наказание: {_ACT_RU.get(cfg.get('spam_action', 'delete'))}",
                              callback_data="q:spamact2"),
         InlineKeyboardButton("➕ Добавить", callback_data="add:word")],
    ]
    for i, w in enumerate(cfg.get("stop_words", [])[:60]):
        rows.append([InlineKeyboardButton(f"❌ {w[:34]}", callback_data=f"dw:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words_menu_text(cfg, label) -> str:
    return (f"🚫 Стоп-слова · {label}\n\n"
            f"В списке: {len(cfg.get('stop_words', []))} "
            f"(+{len(CONFIG.get('global_stop_words', []))} глобальных)\n\n"
            "Синтаксис: слово — точное совпадение; слово* — начало; *слово — конец; "
            "*слово* — любое вхождение.\n"
            "Наказание — общее с фильтром ссылок. Добавить можно и командой /addword.")


def whitewords_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Добавить исключение", callback_data="add:wword")]]
    for i, w in enumerate(cfg.get("white_words", [])[:60]):
        rows.append([InlineKeyboardButton(f"❌ {w[:34]}", callback_data=f"dww:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def whitewords_menu_text(cfg, label) -> str:
    return (f"⚪ Исключения (белый список) · {label}\n\n"
            f"В списке: {len(cfg.get('white_words', []))}\n\n"
            "Слова отсюда никогда не считаются нарушением — даже если совпали со "
            "стоп-словом или глобальным списком. Ключи автоответов защищены автоматически.\n"
            "Синтаксис со «*» — как у стоп-слов.")


def words2_kb(cfg) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(f"{onoff(cfg['enabled'].get('words2'))} Второй список включён",
                              callback_data="t2:words2:words2")],
        [InlineKeyboardButton(f"🚨 Наказание: {_ACT_RU.get(cfg.get('stop_words2_action', 'ban'))}",
                              callback_data="w2act"),
         InlineKeyboardButton(f"{onoff(cfg.get('stop_words2_profile', True))} Искать в имени",
                              callback_data="w2prof")],
        [InlineKeyboardButton("➕ Добавить", callback_data="add:word2")],
    ]
    for i, w in enumerate(cfg.get("stop_words2", [])[:60]):
        rows.append([InlineKeyboardButton(f"❌ {w[:34]}", callback_data=f"dw2:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def words2_menu_text(cfg, label) -> str:
    return (f"🛑 Второй список слов (мат-фильтр) · {label}\n\n"
            f"В списке: {len(cfg.get('stop_words2', []))}\n\n"
            "Отдельный набор слов со СВОИМ наказанием. Из коробки здесь мат: "
            "сообщение удаляется, автор получает предупреждение, "
            "3 предупреждения → бан (лимит и реакция — в 🛡 Модерации).\n"
            "«Искать в имени» — слова ловятся ещё и в имени/юзернейме отправителя.")


def links_kb(cfg) -> InlineKeyboardMarkup:
    en = cfg["enabled"]
    rows = [
        [InlineKeyboardButton(f"{onoff(en.get('invites'))} Invite-ссылки", callback_data="t2:invites:links"),
         InlineKeyboardButton(f"{onoff(en.get('shorteners'))} Сокращатели", callback_data="t2:shorteners:links")],
        [InlineKeyboardButton(f"{onoff(en.get('spam_domains'))} Спам-домены", callback_data="t2:spam_domains:links"),
         InlineKeyboardButton(f"{onoff(en.get('all_links'))} ВСЕ ссылки", callback_data="t2:all_links:links")],
        [InlineKeyboardButton("➕ Добавить спам-домен", callback_data="add:link")],
    ]
    for i, d in enumerate(cfg.get("spam_links", [])[:60]):
        rows.append([InlineKeyboardButton(f"❌ {d[:34]}", callback_data=f"dl:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def links_menu_text(cfg, label) -> str:
    return (f"🔗 Ссылки · {label}\n\n"
            f"Спам-доменов в списке: {len(cfg.get('spam_links', []))}\n\n"
            "Я ловлю и скрытые ссылки (текст с гиперссылкой). Наказание — общее "
            f"({_ACT_RU.get(cfg.get('spam_action', 'delete'))}), меняется в «Быстрых настройках».\n"
            "Спам-домены добавляются и командой /addlink.")


def flood_kb(cfg) -> InlineKeyboardMarkup:
    f = cfg["flood"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(cfg['enabled'].get('flood'))} Антифлуд включён",
                              callback_data="t2:flood:flood")],
        [InlineKeyboardButton(f"✉️ Лимит: {f.get('limit', 5)} сообщ.", callback_data="fl:limit"),
         InlineKeyboardButton(f"⏱ Окно: {f.get('period', 10)} сек", callback_data="fl:period")],
        [InlineKeyboardButton(f"🔇 Мут за флуд: {human_duration(f.get('mute', 300))}", callback_data="fl:mute")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def mod_kb(cfg) -> InlineKeyboardMarkup:
    m = cfg["moderation"]
    exp = m.get("warn_expire_days", 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"⚠️ Лимит предов: {m.get('warn_limit', 3)}", callback_data="md:limit"),
         InlineKeyboardButton(f"🚨 По лимиту: {'бан' if m.get('warn_action') == 'ban' else 'мут'}",
                              callback_data="md:act")],
        [InlineKeyboardButton(f"🔇 Мут по лимиту: {human_duration(m.get('warn_mute', 3600))}",
                              callback_data="md:mute"),
         InlineKeyboardButton(f"⌛ Сгорание: {str(exp) + ' дн' if exp else 'выкл'}",
                              callback_data="md:exp")],
        [InlineKeyboardButton(
            "🔇 Мут за спам: " + (human_duration(m["spam_mute"]) if m.get("spam_mute") else "как антифлуд"),
            callback_data="md:smute")],
        [InlineKeyboardButton(f"{onoff(m.get('mod_admins_only'))} Модерация только владельцам и менеджерам",
                              callback_data="md:only")],
        [InlineKeyboardButton(f"{onoff(m.get('log_actions'))} Журнал действий",
                              callback_data="md:log"),
         InlineKeyboardButton(f"{onoff(m.get('notify_delete'))} Писать «почему удалил»",
                              callback_data="md:nd")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def mod_menu_text(cfg, label) -> str:
    m = cfg["moderation"]
    return (f"🛡 Модерация · {label}\n\n"
            f"Предупреждения: лимит {m.get('warn_limit', 3)}, по лимиту — "
            f"{'бан' if m.get('warn_action') == 'ban' else 'мут ' + human_duration(m.get('warn_mute', 3600))}.\n"
            "«Журнал действий» шлёт события модерации в служебный чат (или владельцам).\n"
            "«Только владельцу бота» — строгий режим: команды наказания не работают даже "
            "у админов группы и ролей (владельцы и менеджеры — работают).\n"
            "«Мут за спам» — срок, когда фильтр наказывает мутом.")


def media_kb(cfg) -> InlineKeyboardMarkup:
    mb = cfg.get("media_block", {})
    rows = []
    for i in range(0, len(MEDIA_TYPES), 2):
        row = [InlineKeyboardButton(f"{onoff(mb.get(k))} {t}", callback_data=f"mb:{k}")
               for k, t in MEDIA_TYPES[i:i + 2]]
        rows.append(row)
    rows.append([InlineKeyboardButton(
        f"🚨 Наказание: {_ACT_RU.get(cfg.get('media_action', 'delete'))}", callback_data="mact")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def media_menu_text(cfg, label) -> str:
    on = [t for k, t in MEDIA_TYPES if cfg.get("media_block", {}).get(k)]
    return (f"📎 Медиа-фильтр · {label}\n\n"
            f"Запрещено: {', '.join(on) or '— ничего —'}\n\n"
            "Отмеченные типы вложений удаляются у обычных участников. "
            "Админов, менеджеров и роли фильтр не трогает.")


def night_kb(cfg) -> InlineKeyboardMarkup:
    n = cfg["night"]
    tz = int(n.get("tz", 0))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(n.get('enabled'))} Ночной режим включён",
                              callback_data="nm:tgl")],
        [InlineKeyboardButton(f"🌙 С: {int(n.get('start', 23)):02d}:00", callback_data="nm:start"),
         InlineKeyboardButton(f"🌅 До: {int(n.get('end', 7)):02d}:00", callback_data="nm:end")],
        [InlineKeyboardButton(f"🕒 Пояс: UTC{'+' if tz >= 0 else ''}{tz}", callback_data="nm:tz")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def night_menu_text(cfg, label) -> str:
    n = cfg["night"]
    return (f"🌙 Ночной режим · {label}\n\n"
            f"Сейчас: {'🌙 действует' if is_night_now(n) else 'не действует'}\n\n"
            "В заданные часы сообщения обычных участников тихо удаляются. "
            "Админов, менеджеров и роли это не касается.")


def triggers_kb(cfg) -> InlineKeyboardMarkup:
    mode = cfg.get("trigger_match", "word")
    rows = [
        [InlineKeyboardButton(f"{onoff(cfg['enabled'].get('triggers'))} Автоответы включены",
                              callback_data="t2:triggers:triggers")],
        [InlineKeyboardButton(f"🎯 Совпадение: {'слово целиком' if mode == 'word' else 'вхождение'}",
                              callback_data="mode:trig"),
         InlineKeyboardButton("➕ Автоответ", callback_data="add:trigger")],
        [InlineKeyboardButton("➕ Автоответ с медиа/кнопками", callback_data="add:trigmedia")],
    ]
    for i, (k, v) in enumerate(sorted(cfg.get("triggers", {}).items())[:40]):
        rows.append([InlineKeyboardButton(f"❌ {k[:16]} → {_trig_preview(v)}", callback_data=f"dt:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def triggers_menu_text(cfg, label) -> str:
    return (f"💬 Автоответы · {label}\n\n"
            f"Всего: {len(cfg.get('triggers', {}))}\n\n"
            "Бот отвечает, когда в сообщении встречается ключ. Формат добавления: "
            "ключ - ответ (несколько ключей через запятую).\n"
            "Ответ может быть с медиа и кнопками, работает {рандомизация|вариантов} "
            "и HTML-разметка. Ключи со «*» матчатся как стоп-слова.\n"
            "Быстрое добавление командой: /add ключ - ответ.")


def chatter_kb(cfg) -> InlineKeyboardMarkup:
    ch = cfg.get("chatter", {}) or {}
    rows = [
        [InlineKeyboardButton(f"{onoff(ch.get('enabled'))} Болталка включена", callback_data="cht:tgl")],
        [InlineKeyboardButton(f"🎲 Шанс шутки: {ch.get('chance', 5)}%", callback_data="cht:chance"),
         InlineKeyboardButton(f"⏸ Пауза: {human_duration(ch.get('cooldown', 180))}", callback_data="cht:cd")],
        [InlineKeyboardButton(f"{onoff(ch.get('reply_mentions', True))} Отвечать на обращения к боту",
                              callback_data="cht:men")],
        [InlineKeyboardButton(f"{onoff(ch.get('smart_replies', True))} Умные ответы (по смыслу)",
                              callback_data="cht:smart")],
        [InlineKeyboardButton(f"{onoff(ch.get('reactions', True))} Эмодзи-реакции",
                              callback_data="cht:react"),
         InlineKeyboardButton(f"🎯 {ch.get('reaction_chance', 8)}%", callback_data="cht:rchance")],
        [InlineKeyboardButton(f"{onoff(ch.get('fun', True))} 🎮 Игры и приколы (кубик, «или», «кто», шар)",
                              callback_data="cht:fun")],
        [InlineKeyboardButton(
            f"{onoff(ch.get('ai'))} 🤖 ИИ-ответы" + ("" if AI_API_KEY else " (нет ключа)"),
            callback_data="cht:ai")],
        [InlineKeyboardButton(f"{onoff(ch.get('gopnik'))} 🧢 Гоп-режим (отвечает по-пацански)",
                              callback_data="cht:gop")],
        [InlineKeyboardButton("➕ Шутка", callback_data="add:chphrase"),
         InlineKeyboardButton("➕ Ответ на обращение", callback_data="add:chreply")],
        [InlineKeyboardButton("➕ Гоп-слово (триггер)", callback_data="add:gopword")],
    ]
    if ch.get("gopnik"):
        for i, w in enumerate((ch.get("gop_words") or [])[:25]):
            rows.append([InlineKeyboardButton(f"❌ 🧢 {w[:32]}", callback_data=f"dgp:{i}")])
    for i, p in enumerate((ch.get("phrases") or [])[:25]):
        rows.append([InlineKeyboardButton(f"❌ 🎲 {p[:32]}", callback_data=f"dcp:{i}")])
    for i, p in enumerate((ch.get("replies") or [])[:25]):
        rows.append([InlineKeyboardButton(f"❌ 💬 {p[:32]}", callback_data=f"dcr:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def chatter_menu_text(cfg, label) -> str:
    ch = cfg.get("chatter", {}) or {}
    return (f"🎭 Болталка · {label}\n\n"
            f"Шуток: {len(ch.get('phrases') or [])} · ответов на обращения: {len(ch.get('replies') or [])}\n\n"
            "Бот оживляет чат:\n"
            "• отвечает на @упоминание, реплай и «бот, …» — с умом: узнаёт привет, "
            "«как дела», спасибо, просьбу пошутить и даже подколы;\n"
            "• с заданным шансом вбрасывает шутку (не чаще паузы) и изредка ставит "
            "эмодзи-реакции 🔥😁 на сообщения.\n"
            "🎮 Игры: кубик/дартс/баскет (Dice), камень-ножницы-бумага, «пицца или суши?», "
            "«кто самый…?», «число от 1 до 100», факт, цитата, комплимент, «подколи» "
            "(добрый), гороскоп, шар «стоит ли…?»; «доброе утро, чат» после тишины, "
            "поздравления с ДР и юбилеи каждой 1000-й записи.\n"
            "🤖 ИИ-ответы: живой разговор на любые темы через внешний API. Задай на сервере "
            "AI_API_KEY (подойдут OpenAI/OpenRouter/Groq/DeepSeek/Ollama; опционально "
            "AI_BASE_URL и AI_MODEL) — и включай тумблер. Стиль ИИ следует гоп-режиму, "
            "мат-фильтр действует и на него. Без ключа всё работает офлайн.\n"
            "🧢 Гоп-режим: бот говорит «по-пацански» и сам отзывается на слова-триггеры "
            "(«слышь», «чё каво», «семки»…) — свои триггеры добавляются кнопкой ниже.\n"
            "Свои фразы — по одной на строку, работает {рандомизация|вариантов}.\n"
            "Команды бот не комментирует; поверх автоответа не шутит.\n"
            "Осмысленные ответы по темам — это 💬 Автоответы (/add ключ - ответ).")


def welcome_kb(cfg) -> InlineKeyboardMarkup:
    w = cfg.get("welcome", {})
    after = int(w.get("delete_after", 0) or 0)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(w.get('enabled'))} Приветствие включено", callback_data="wl:tgl")],
        [InlineKeyboardButton("✏️ Текст приветствия", callback_data="add:welcome"),
         InlineKeyboardButton("🔘 Кнопки", callback_data="add:welcome_btns")],
        [InlineKeyboardButton(f"🗑 Авто-удаление: {human_duration(after) if after else 'выкл'}",
                              callback_data="wl:after")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def welcome_menu_text(cfg, label) -> str:
    w = cfg.get("welcome", {})
    return (f"👋 Приветствие · {label}\n\n"
            f"Текст:\n{(w.get('text') or '—')[:300]}\n\n"
            "Подстановки: {name} — имя, {mention} — упоминание, {chat} — название группы.\n"
            "Кнопки: «Текст - https://ссылка», по строке на ряд, несколько в ряд через «;».")


def captcha_kb(cfg) -> InlineKeyboardMarkup:
    c = cfg["captcha"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(c.get('enabled'))} Капча включена", callback_data="cp:tgl")],
        [InlineKeyboardButton(f"⏱ Время: {human_duration(c.get('timeout', 120))}", callback_data="cp:to"),
         InlineKeyboardButton(f"🚨 Не прошёл: {'кик' if c.get('action', 'kick') == 'kick' else 'мут'}",
                              callback_data="cp:act")],
        [InlineKeyboardButton(f"{onoff(c.get('via_request', True))} Через заявку (капча в ЛС)",
                              callback_data="cp:via")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def captcha_menu_text(cfg, label) -> str:
    return (f"🧩 Капча · {label}\n\n"
            "«Через заявку» — лучший режим: вход в группу по заявке, я пишу человеку в ЛС "
            "и впускаю после нажатия кнопки (включи в настройках группы «Заявки на вступление»).\n"
            "Без заявки — кнопка прямо в чате: новичок в муте, пока не нажмёт.")


def rules_kb(cfg) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Изменить правила", callback_data="add:rules")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def rules_menu_text(cfg, label) -> str:
    return (f"📜 Правила · {label}\n\n"
            f"{(cfg.get('rules') or 'Правила не заданы.')[:900]}\n\n"
            "Показать в группе — /rules. Изменить можно и командой /setrules.")


def blacklist_kb(cfg) -> InlineKeyboardMarkup:
    bl = cfg.get("blacklist", {}) or {}
    rows = [[InlineKeyboardButton("➕ По ID", callback_data="add:blid"),
             InlineKeyboardButton("➕ По имени", callback_data="add:blname")]]
    for i, uid in enumerate(bl.get("ids", [])[:30]):
        rows.append([InlineKeyboardButton(f"❌ 🆔 {uid}", callback_data=f"dblid:{i}")])
    for i, nm in enumerate(bl.get("names", [])[:30]):
        rows.append([InlineKeyboardButton(f"❌ 👤 {nm[:30]}", callback_data=f"dblname:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def blacklist_menu_text(cfg, label) -> str:
    bl = cfg.get("blacklist", {}) or {}
    return (f"⛔ Чёрный список · {label}\n\n"
            f"ID: {len(bl.get('ids', []))} · подстрок имени: {len(bl.get('names', []))}\n\n"
            "Люди из списка банятся при входе и при первом сообщении. Подстрока имени "
            "ловит по имени/фамилии/юзернейму.\n"
            "В группе: /block (реплаем или с ID), /unblock.")


def antiraid_kb(cfg) -> InlineKeyboardMarkup:
    a = cfg.get("antiraid", {})
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(a.get('enabled'))} Анти-рейд включён", callback_data="ar:tgl")],
        [InlineKeyboardButton(f"👥 Порог: {a.get('joins', 8)} входов", callback_data="ar:joins"),
         InlineKeyboardButton(f"⏱ Окно: {a.get('window', 60)} сек", callback_data="ar:win")],
        [InlineKeyboardButton(f"🔒 Строгий режим: {a.get('lock_min', 10)} мин", callback_data="ar:lock")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def antiraid_menu_text(cfg, label) -> str:
    return (f"🚨 Анти-рейд · {label}\n\n"
            "При всплеске входов (порог за окно) включается строгий режим: новые "
            "участники отсеиваются заданное время, а модераторам летит уведомление.")


def antinuke_kb(cfg) -> InlineKeyboardMarkup:
    a = cfg.get("antinuke", {})
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(a.get('enabled'))} Анти-снос включён", callback_data="an:tgl")],
        [InlineKeyboardButton(f"🔨 Порог: {a.get('ban_threshold', 5)} банов", callback_data="an:thr"),
         InlineKeyboardButton(f"⏱ Окно: {a.get('window', 30)} сек", callback_data="an:win")],
        [InlineKeyboardButton(f"🚨 Реакция: {'бан' if a.get('action') == 'ban' else 'снять права'}",
                              callback_data="an:act")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def antinuke_menu_text(cfg, label) -> str:
    return (f"🧱 Анти-снос · {label}\n\n"
            "Если один админ массово банит людей (порог за окно), я поднимаю тревогу и, "
            "по настройке, снимаю с него права или баню. Владельца/менеджеров бота не трогаю.")


# ── роли ────────────────────────────────────────────────────────────────────


def roles_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Новая роль", callback_data="add:rolenew")]]
    for name in sorted((cfg.get("roles") or {}).keys())[:30]:
        r = cfg["roles"].get(name) or {}
        rows.append([InlineKeyboardButton(
            f"🎖 {name} · {len(r.get('members', []))} чел", callback_data=f"rl:{name}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def roles_menu_text(cfg, label) -> str:
    return (f"🎖 Роли · {label}\n\n"
            f"Ролей: {len(cfg.get('roles') or {})}\n\n"
            "Роль — набор прав (бан/мут/пред/призыв) для доверенных участников без "
            "админки Telegram. Участники ролей не попадают под фильтры.\n"
            "Выдать в группе: /role <имя> (реплаем), забрать — /unrole.")


def role_detail_kb(cfg, name: str, tgt=None) -> InlineKeyboardMarkup:
    r = (cfg.get("roles") or {}).get(name) or {"perms": [], "members": []}
    rows = [[InlineKeyboardButton(f"{onoff(k in r.get('perms', []))} {t}",
                                  callback_data=f"rp:{name}:{k}")]
            for k, t in ROLE_PERM_DEFS]
    rows.append([InlineKeyboardButton("➕ Участник (по ID)", callback_data=f"rmadd:{name}")])
    names = CONFIG.get("msg_stats", {}).get(str(tgt or ""), {}).get("names", {})
    for uid in r.get("members", [])[:25]:
        rows.append([InlineKeyboardButton(f"❌ {names.get(str(uid), uid)}",
                                          callback_data=f"rmx:{name}:{uid}")])
    rows.append([InlineKeyboardButton("🗑 Удалить роль", callback_data=f"rdel:{name}"),
                 InlineKeyboardButton("⬅️ Назад", callback_data="m:roles")])
    return InlineKeyboardMarkup(rows)


def staff_menu_text(cfg, label) -> str:
    sg = cfg.get("staff_group", 0)
    sg_title = CONFIG.get("groups", {}).get(str(sg), str(sg)) if sg else "— не задан —"
    return (f"👔 Служебный чат · {label}\n\n"
            f"Сейчас: {sg_title}\n\n"
            "Сюда идут жалобы (/report), тревоги анти-рейда/анти-сноса, журнал действий "
            "и недельные сводки. Если не задан — всё падает владельцам бота в ЛС.\n\n"
            "Назначить: добавь меня в будущий служебный чат и выполни там /setstaff.")


def staff_kb(cfg) -> InlineKeyboardMarkup:
    rows = []
    if cfg.get("staff_group"):
        rows.append([InlineKeyboardButton("🗑 Отвязать служебный чат", callback_data="dm:del:staff")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def gmgr_kb(cfg, tgt=None) -> InlineKeyboardMarkup:
    names = CONFIG.get("msg_stats", {}).get(str(tgt or ""), {}).get("names", {})
    rows = [[InlineKeyboardButton("➕ Добавить менеджера (по ID)", callback_data="add:gmgr")]]
    for i, uid in enumerate((cfg.get("group_managers") or [])[:30]):
        rows.append([InlineKeyboardButton(f"❌ {names.get(str(uid), uid)}", callback_data=f"dgm:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def gmgr_menu_text(cfg, label) -> str:
    return (f"👤 Менеджеры группы · {label}\n\n"
            f"Сейчас: {len(cfg.get('group_managers') or [])}\n\n"
            "Менеджер получает ПОЛНЫЙ доступ к настройкам и модерации этой группы "
            "через /panel — без админки Telegram. Фильтры его не трогают, а наказать его "
            "через бота может только владелец бота. Глобальные разделы (рассылки по всем "
            "группам, одобрение, бэкапы) ему недоступны.\n\n"
            "Назначает создатель группы или владелец бота: здесь или в группе "
            "командой /gmanager (реплаем или с ID). Узнать ID человек может командой /userid.\n"
            "⚠️ Банить и мутить от имени бота менеджер сможет, только если у самого "
            "бота есть эти права в группе.")


def cmd_level_from(cfg, key: str) -> str:
    return (cfg.get("cmd_perms") or {}).get(key, CMD_DEFAULT.get(key, "admins"))


def cmdperms_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{title}: {LEVEL_SHORT[cmd_level_from(cfg, k)]}",
                                  callback_data=f"perm:{k}")]
            for k, title, _lv, _d in CMD_DEFS]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def cmdperms_menu_text(cfg, label) -> str:
    return (f"🔐 Права команд · {label}\n\n"
            "Кто в группе может пользоваться командами бота. Владелец/менеджеры бота "
            "могут всегда; роли добавляют права поверх этих уровней.\n"
            "Призыв /all нельзя открывать «всем» — минимум админы.")


def lang_kb(cfg) -> InlineKeyboardMarkup:
    cur = cfg.get("lang", "ru")
    rows = [[InlineKeyboardButton(f"{'✅' if code == cur else '▫️'} {title}",
                                  callback_data=f"lang:{code}")]
            for code, title in LANGS.items()]
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def recurring_kb(cfg) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("➕ Авто-сообщение", callback_data="add:recurring")]]
    for i, r in enumerate((cfg.get("recurring") or [])[:20]):
        if not isinstance(r, dict):
            continue
        rows.append([
            InlineKeyboardButton(f"{onoff(r.get('enabled'))} {int(r.get('interval', 60))} мин · "
                                 f"{(r.get('text') or '')[:20]}", callback_data=f"rectgl:{i}"),
            InlineKeyboardButton("🗑", callback_data=f"recdel:{i}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def recurring_menu_text(cfg, label) -> str:
    return (f"🔁 Авто-сообщения · {label}\n\n"
            f"Всего: {len(cfg.get('recurring') or [])}\n\n"
            "Повторяющиеся сообщения в эту группу с заданным интервалом (в минутах). "
            "Формат добавления: интервал_минут | текст. Работает {рандомизация|вариантов}.")


def other_kb(cfg) -> InlineKeyboardMarkup:
    ji = cfg.get("show_join_id", "off")
    ji_ru = {"off": "выкл", "all": "в чат", "admins": "модераторам"}.get(ji, ji)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🆔 ID новичков: {ji_ru}", callback_data="ji:cycle")],
        [InlineKeyboardButton("📨 Текст «зазывалы»", callback_data="add:invitetext")],
        [InlineKeyboardButton("🧹 Очистить статистику группы", callback_data="st:clear")],
        [InlineKeyboardButton("♻️ Сбросить настройки группы к шаблону", callback_data="resetchat")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def other_menu_text(cfg, label) -> str:
    return (f"⚙️ Прочее · {label}\n\n"
            "«ID новичков» — показывать ID входящих (в чат или только модераторам).\n"
            "«Зазывала» — текст сообщения с кнопкой «Пригласить друга» (/zazyvala).\n"
            "Сброс настроек вернёт группу к общему шаблону (списки и автоответы группы "
            "будут заменены шаблонными).")


def global_kb() -> InlineKeyboardMarkup:
    gb = CONFIG.get("global_blacklist", {"ids": [], "names": []})
    rows = [
        [InlineKeyboardButton("➕ Глоб. стоп-слово", callback_data="add:gword"),
         InlineKeyboardButton("➕ Глоб. ЧС: ID", callback_data="add:gbid")],
        [InlineKeyboardButton("➕ Глоб. ЧС: имя", callback_data="add:gbname")],
    ]
    for i, w in enumerate(CONFIG.get("global_stop_words", [])[:40]):
        rows.append([InlineKeyboardButton(f"❌ 🚫 {w[:30]}", callback_data=f"dgw:{i}")])
    for i, uid in enumerate(gb.get("ids", [])[:25]):
        rows.append([InlineKeyboardButton(f"❌ 🆔 {uid}", callback_data=f"dgbid:{i}")])
    for i, nm in enumerate(gb.get("names", [])[:25]):
        rows.append([InlineKeyboardButton(f"❌ 👤 {nm[:28]}", callback_data=f"dgbname:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def global_menu_text() -> str:
    gb = CONFIG.get("global_blacklist", {"ids": [], "names": []})
    return ("🌍 Глобальные списки (на ВСЕ группы)\n\n"
            f"Стоп-слов: {len(CONFIG.get('global_stop_words', []))} · "
            f"ЧС: {len(gb.get('ids', []))} ID, {len(gb.get('names', []))} имён\n\n"
            "Действуют во всех группах поверх настроек каждой. Глобальный ЧС банит "
            "по ID и по подстроке имени. Команды: /gblock, /gunblock.")


def access_kb(tgt, is_mgr: bool) -> InlineKeyboardMarkup:
    rows = []
    if is_mgr:
        rows.append([InlineKeyboardButton(
            f"{onoff(CONFIG.get('require_approval', True))} Требовать допуск для групп",
            callback_data="apt:req")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def access_menu_text(tgt, label) -> str:
    lines = [f"⭐ Доступ и тариф · {label}", ""]
    if tgt and tgt != "defaults":
        lines.append(f"Статус: {access_status(int(tgt))}")
    lines += ["",
              "Тариф оформляется в самой группе командой /pro (оплата звёздами Telegram):"]
    for key, p in PRO_PLANS.items():
        lines.append(f"• {p['title']} — {p['stars']} ⭐")
    lines.append("\nВладелец бота может одобрять группы бесплатно (раздел «Одобрение групп»).")
    return "\n".join(lines)


def approve_kb() -> InlineKeyboardMarkup:
    rows = []
    for cid, title in list(CONFIG.get("groups", {}).items())[:30]:
        if chat_allowed(int(cid)):
            continue
        rows.append([InlineKeyboardButton(f"✅ {title[:28]}", callback_data=f"appr:ok:{cid}"),
                     InlineKeyboardButton("🚫", callback_data=f"appr:no:{cid}")])
    if not rows:
        rows.append([InlineKeyboardButton("— все известные группы с допуском —", callback_data="m:approve")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def approve_menu_text() -> str:
    total = len(CONFIG.get("groups", {}))
    ok = sum(1 for cid in CONFIG.get("groups", {}) if chat_allowed(int(cid)))
    return ("✅ Одобрение групп\n\n"
            f"Известно групп: {total} · с допуском: {ok}\n\n"
            "«✅» — бесплатный бессрочный допуск, «🚫» — оставить без допуска "
            "(пусть оформляют тариф /pro или пробный период).")


def promo_kb() -> InlineKeyboardMarkup:
    p = CONFIG["promo"]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{onoff(p.get('enabled'))} Авто-промо включено", callback_data="pr:tgl")],
        [InlineKeyboardButton(f"⏱ Интервал: {human_duration(p.get('interval', 3600))}",
                              callback_data="pr:int"),
         InlineKeyboardButton(f"{onoff(p.get('pin'))} Закреплять", callback_data="pr:pin")],
        [InlineKeyboardButton("✏️ Контент промо", callback_data="add:promo_content"),
         InlineKeyboardButton("🔘 Кнопки", callback_data="add:promo_btns")],
        [InlineKeyboardButton("📤 Рассылка в группы", callback_data="add:bcast")],
        [InlineKeyboardButton("💬 Рассылка в ЛС подписчикам", callback_data="dmto:pick")],
        [InlineKeyboardButton("🗑 Очистить ЛС-подписчиков группы", callback_data="dm:del:subs")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def promo_menu_text(label) -> str:
    p = CONFIG["promo"]
    return (f"📣 Промо и рассылки\n\n"
            f"Авто-промо: {'вкл' if p.get('enabled') else 'выкл'}, "
            f"раз в {human_duration(p.get('interval', 3600))}, "
            f"тип: {_POST_TYPE_RU.get(p.get('type', 'text'), 'текст')}\n"
            f"Текст: {(p.get('text') or '—')[:150]}\n\n"
            "Авто-промо и рассылка в группы идут во ВСЕ известные группы.\n"
            "Рассылка в ЛС — подписчикам выбранных групп (кто прошёл капчу-заявку).")


def post_groups_kb(selected: set, prefix: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{'✅' if 'all' in selected else '▫️'} Все группы",
                                  callback_data=f"{prefix}:all")]]
    for cid, title in list(CONFIG.get("groups", {}).items())[:30]:
        mark = "✅" if (cid in selected or "all" in selected) else "▫️"
        rows.append([InlineKeyboardButton(f"{mark} {title[:36]}", callback_data=f"{prefix}:{cid}")])
    rows.append([InlineKeyboardButton("▶️ Дальше", callback_data=f"{prefix}:go"),
                 InlineKeyboardButton("⬅️ Назад", callback_data="m:promo")])
    return InlineKeyboardMarkup(rows)


def sched_kb() -> InlineKeyboardMarkup:
    tz = int(CONFIG.get("post_tz", 0))
    rows = [[InlineKeyboardButton("➕ Новый пост", callback_data="add:post"),
             InlineKeyboardButton(f"🕒 Пояс: UTC{'+' if tz >= 0 else ''}{tz}", callback_data="tz:cycle")]]
    for p in CONFIG.get("scheduled_posts", [])[:20]:
        days = p.get("days") or []
        dtxt = "ежедневно" if not days else ",".join(_WEEKDAYS_RU[d] for d in days)
        rows.append([
            InlineKeyboardButton(f"{onoff(p.get('enabled', True))} {p.get('time', '?')} · {dtxt} · "
                                 f"{_trig_preview(p, 14)}", callback_data=f"sptgl:{p.get('id')}"),
            InlineKeyboardButton("👥", callback_data=f"spg:{p.get('id')}"),
            InlineKeyboardButton("🗑", callback_data=f"spdel:{p.get('id')}"),
        ])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def sched_menu_text() -> str:
    return ("🗓 Посты по расписанию\n\n"
            f"Всего: {len(CONFIG.get('scheduled_posts', []))}\n\n"
            "Пост уходит в выбранные группы (кнопка 👥) в заданное время по дням недели.\n"
            "Формат времени при создании: ЧЧ:ММ [дни: пн,ср,пт] — без дней = ежедневно.\n"
            "Контент — любой: текст/медиа, HTML, кнопки, {рандомизация|вариантов}.")


def sched_groups_kb(post) -> InlineKeyboardMarkup:
    ch = post.get("chats", "all")
    sel = {"all"} if ch == "all" else {str(c) for c in ch}
    pid = post.get("id")
    rows = [[InlineKeyboardButton(f"{'✅' if 'all' in sel else '▫️'} Все группы",
                                  callback_data=f"spg:{pid}:all")]]
    for cid, title in list(CONFIG.get("groups", {}).items())[:30]:
        mark = "✅" if ("all" in sel or cid in sel) else "▫️"
        rows.append([InlineKeyboardButton(f"{mark} {title[:36]}", callback_data=f"spg:{pid}:{cid}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:sched")])
    return InlineKeyboardMarkup(rows)


def backup_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗄 Полный бэкап (все настройки)", callback_data="bk:full")],
        [InlineKeyboardButton("📂 Бэкап выбранной группы", callback_data="bk:chat")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="m:main")],
    ])


def backup_menu_text(label) -> str:
    return (f"🗄 Бэкапы · {label}\n\n"
            "Полный бэкап — JSON со всеми настройками бота; бэкап группы — только её "
            "настройки (для переноса в другую группу).\n"
            "Восстановление: просто пришли файл мне в ЛС — полный применится целиком, "
            "файл группы применится к выбранной в панели группе.")


# ── разделы-хабы ─────────────────────────────────────────────────────────────

# Куда ведёт «⬅️ Назад» с каждого экрана (без записи — в главное меню)
PANEL_PARENT = {
    "m:h_words": "m:h_protect",
    "m:words": "m:h_words", "m:words2": "m:h_words", "m:whitewords": "m:h_words",
    "m:global": "m:h_words",
    "m:links": "m:h_protect", "m:flood": "m:h_protect", "m:media": "m:h_protect",
    "m:night": "m:h_protect", "m:captcha": "m:h_protect", "m:antiraid": "m:h_protect",
    "m:antinuke": "m:h_protect", "m:toggles": "m:h_protect",
    "m:mod": "m:h_mod", "m:roles": "m:h_mod", "m:gmgr": "m:h_mod", "m:cmdperms": "m:h_mod",
    "m:blacklist": "m:h_mod", "m:staff": "m:h_mod",
    "m:triggers": "m:h_talk", "m:chatter": "m:h_talk", "m:welcome": "m:h_talk",
    "m:rules": "m:h_talk", "m:lang": "m:h_talk",
    "m:recurring": "m:h_posts", "m:promo": "m:h_posts", "m:sched": "m:h_posts",
    "m:access": "m:h_sys", "m:backup": "m:h_sys", "m:other": "m:h_sys", "m:approve": "m:h_sys",
}


def _with_back(kb: InlineKeyboardMarkup, parent: str) -> InlineKeyboardMarkup:
    """Перенаправить кнопку «⬅️ Назад» (m:main) на родительский раздел."""
    rows = []
    for row in kb.inline_keyboard:
        rows.append([InlineKeyboardButton(b.text, callback_data=parent)
                     if getattr(b, "callback_data", None) == "m:main" else b for b in row])
    return InlineKeyboardMarkup(rows)


def _hub_kb(items, back: str = "m:main") -> InlineKeyboardMarkup:
    rows, buf = [], []
    for text, cb in items:
        buf.append(InlineKeyboardButton(text, callback_data=cb))
        if len(buf) == 2:
            rows.append(buf)
            buf = []
    if buf:
        rows.append(buf)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=back)])
    return InlineKeyboardMarkup(rows)


def hub_protect(cfg, label, mgr):
    en = cfg["enabled"]
    links_on = any(en.get(k) for k in ("invites", "shorteners", "spam_domains", "all_links"))
    media_on = any((cfg.get("media_block") or {}).values())
    items = [
        ("🚫 Фильтры слов", "m:h_words"),
        (f"{onoff(links_on)} 🔗 Ссылки", "m:links"),
        (f"{onoff(en.get('flood'))} 🌊 Антифлуд", "m:flood"),
        (f"{onoff(media_on)} 📎 Медиа-фильтр", "m:media"),
        (f"{onoff(cfg['night'].get('enabled'))} 🌙 Ночной режим", "m:night"),
        (f"{onoff(cfg['captcha'].get('enabled'))} 🧩 Капча", "m:captcha"),
        (f"{onoff((cfg.get('antiraid') or {}).get('enabled'))} 🚨 Анти-рейд", "m:antiraid"),
        (f"{onoff((cfg.get('antinuke') or {}).get('enabled'))} 🧱 Анти-снос", "m:antinuke"),
        ("🔧 Все тумблеры", "m:toggles"),
    ]
    text = (f"🛡 Защита · {label}\n\n"
            f"За спам: {_ACT_RU.get(cfg.get('spam_action', 'delete'))} · "
            f"за мат: {_ACT_RU.get(cfg.get('stop_words2_action', 'warn'))} · "
            f"за медиа: {_ACT_RU.get(cfg.get('media_action', 'delete'))}\n\n"
            "Всё, что отсеивает спам и рейды. ✅ — включено.")
    return text, _hub_kb(items)


def hub_words(cfg, label, mgr):
    en = cfg["enabled"]
    items = [
        (f"{onoff(en.get('words'))} 🚫 Спам-слова · {len(cfg.get('stop_words', []))}", "m:words"),
        (f"{onoff(en.get('words2'))} 🛑 Мат-фильтр · {len(cfg.get('stop_words2', []))}", "m:words2"),
        (f"⚪ Исключения · {len(cfg.get('white_words', []))}", "m:whitewords"),
    ]
    if mgr:
        items.append((f"🌍 Глобальные · {len(CONFIG.get('global_stop_words', []))}", "m:global"))
    text = (f"🚫 Фильтры слов · {label}\n\n"
            f"• Спам-слова — наказание: {_ACT_RU.get(cfg.get('spam_action', 'delete'))} "
            "(общее со ссылками)\n"
            f"• Мат-фильтр — наказание: {_ACT_RU.get(cfg.get('stop_words2_action', 'warn'))}, "
            f"лимит предов {cfg['moderation'].get('warn_limit', 3)}\n"
            "• Исключения — никогда не считаются нарушением\n"
            "• Глобальные — действуют во всех группах\n\n"
            "Синтаксис везде один: слово · слово* · *слово · *слово*")
    return text, _hub_kb(items, back="m:h_protect")


def hub_mod(cfg, label, mgr):
    items = [
        ("🛡 Наказания и преды", "m:mod"),
        (f"🎖 Роли · {len(cfg.get('roles') or {})}", "m:roles"),
        (f"👤 Менеджеры группы · {len(cfg.get('group_managers') or [])}", "m:gmgr"),
        ("🔐 Права команд", "m:cmdperms"),
        ("⛔ Чёрный список", "m:blacklist"),
        ("👔 Служебный чат", "m:staff"),
    ]
    m = cfg["moderation"]
    text = (f"⚖️ Модерация · {label}\n\n"
            f"Предупреждения: лимит {m.get('warn_limit', 3)} → "
            f"{'бан' if m.get('warn_action') == 'ban' else 'мут'}\n"
            f"Журнал действий: {'вкл' if m.get('log_actions') else 'выкл'}\n\n"
            "Кто и как наказывает, роли, менеджеры и чёрный список.")
    return text, _hub_kb(items)


def hub_talk(cfg, label, mgr):
    ch = cfg.get("chatter") or {}
    items = [
        (f"{onoff(cfg['enabled'].get('triggers'))} 💬 Автоответы · {len(cfg.get('triggers', {}))}",
         "m:triggers"),
        (f"{onoff(ch.get('enabled'))} 🎭 Болталка", "m:chatter"),
        (f"{onoff((cfg.get('welcome') or {}).get('enabled'))} 👋 Приветствие", "m:welcome"),
        ("📜 Правила", "m:rules"),
        (f"🌐 Язык новичков: {cfg.get('lang', 'ru')}", "m:lang"),
    ]
    text = (f"💬 Общение · {label}\n\n"
            "Автоответы, болталка с играми, приветствие новичков и правила.")
    return text, _hub_kb(items)


def hub_posts(cfg, label, mgr):
    items = [(f"🔁 Авто-сообщения группы · {len(cfg.get('recurring') or [])}", "m:recurring")]
    if mgr:
        p = CONFIG["promo"]
        items += [(f"{onoff(p.get('enabled'))} 📣 Промо и рассылки", "m:promo"),
                  (f"🗓 Посты по расписанию · {len(CONFIG.get('scheduled_posts', []))}", "m:sched")]
    text = (f"📮 Посты · {label}\n\n"
            "• Авто-сообщения — повторяются в этой группе каждые N минут\n"
            + ("• Промо — авто-реклама и рассылки по всем группам и в ЛС\n"
               "• Расписание — посты в заданное время по дням недели\n" if mgr else "")
            + "\nВезде работают медиа, кнопки, HTML и {рандомизация|вариантов}.")
    return text, _hub_kb(items)


def hub_stats(cfg, label, mgr, tgt):
    if not tgt or tgt == "defaults":
        return f"📊 Статистика · {label}\n\nСначала выбери группу.", _hub_kb([])
    total, today, week, top = _msg_stats_summary(tgt)
    s = (CONFIG.get("msg_stats", {}).get(str(tgt), {}) or {}).get("mod", {})
    medals = ["🥇", "🥈", "🥉"]
    top_lines = "\n".join(f"{medals[i] if i < 3 else f'{i + 1}.'} {n} — {c}"
                          for i, (n, c) in enumerate(top[:5])) or "— пока пусто —"
    text = (f"📊 Статистика · {label}\n\n"
            f"Сообщений: всего {total} · сегодня {today} · за неделю {week}\n\n"
            f"🛡 Модерация: удалено {s.get('deleted', 0)}, предов {s.get('warns', 0)}, "
            f"мутов {s.get('muted', 0) + s.get('flood_muted', 0)}, банов {s.get('banned', 0)}, "
            f"киков {s.get('kicked', 0)}\n\n"
            f"🏆 Топ:\n{top_lines}\n\n"
            f"Доступ: {access_status(int(tgt))}")
    return text, _hub_kb([("🔄 Обновить", "m:h_stats"), ("🧹 Очистить", "st:clear")])


def hub_sys(cfg, label, mgr):
    items = [("⭐ Доступ и тариф", "m:access"), ("⚙️ Прочее", "m:other")]
    if mgr:
        items += [("🗄 Бэкапы", "m:backup"), ("✅ Одобрение групп", "m:approve"),
                  ("🛒 Магазин", "m:shop")]
    text = (f"⚙️ Система · {label}\n\n"
            "Доступ и оплата, ID новичков, «зазывала», сброс настроек"
            + (", бэкапы, одобрение групп и магазин." if mgr else "."))
    return text, _hub_kb(items)


# ── магазин в панели ────────────────────────────────────────────────────────


def _shop_status() -> str:
    if _shop_runner is not None:
        return "🟢 работает"
    if not WEBAPP_URL:
        return "⚪ выключен — задай WEBAPP_URL на сервере"
    if web is None:
        return "⚪ не запущен — выполни pip install aiohttp"
    return "🔴 не запустился — смотри лог"


def shop_kb() -> InlineKeyboardMarkup:
    s = CONFIG.get("shop") or {}
    rows = [[InlineKeyboardButton(f"{onoff(s.get('enabled'))} Магазин открыт", callback_data="shp:tgl")],
            [InlineKeyboardButton("➕ Товар", callback_data="add:shopitem"),
             InlineKeyboardButton("✏️ Название", callback_data="add:shoptitle")]]
    for i, it in enumerate((s.get("items") or [])[:30]):
        rows.append([InlineKeyboardButton(f"❌ {it.get('title', '?')[:28]} · {it.get('stars', 0)}⭐",
                                          callback_data=f"dsi:{i}")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data="m:main")])
    return InlineKeyboardMarkup(rows)


def shop_menu_text() -> str:
    s = CONFIG.get("shop") or {}
    orders = CONFIG.get("shop_orders") or []
    earned = sum(int(o.get("stars", 0) or 0) for o in orders)
    last = "\n".join(
        f"• {datetime.fromtimestamp(o.get('ts', 0)).strftime('%d.%m %H:%M')} · {o.get('item')} · "
        f"{o.get('stars')}⭐ · id {o.get('uid')}" for o in orders[-5:][::-1]) or "— пока нет —"
    return (f"🛒 Магазин Mini App «{s.get('title', 'Магазин')}»\n\n"
            f"Сервер: {_shop_status()}\n"
            f"Адрес: {WEBAPP_URL or '—'}\n"
            f"Товаров: {len(s.get('items') or [])} (+ тариф PRO, если магазин открыт из группы)\n"
            f"Заказов: {len(orders)} · получено {earned} ⭐\n\n"
            f"Последние заказы:\n{last}\n\n"
            "Открыть: /shop в ЛС бота или в группе. Оплата — звёздами Telegram.\n"
            "Товар добавляется строкой: Название | звёзд | описание | что выдать после оплаты")


add_help_text = (
    "➕ Быстрое добавление в ЛС и в группе:\n"
    "/add ключ - ответ — автоответ (несколько ключей: цена,прайс - смотри закреп)\n"
    "/del ключ — удалить автоответ · /list — список\n"
    "/addword слово1, слово2 — стоп-слова · /delword, /words\n"
    "/addlink домен.ру — спам-домены · /dellink, /links\n"
    "Синтаксис слов: слово (точно) · слово* (начало) · *слово (конец) · *слово* (вхождение)"
)


def about_text() -> str:
    return (
        "🤖 Channel Guard Bot v6 — защита и оживление групп.\n\n"
        "Антиспам: стоп-слова (2 списка + глобальный), исключения, ссылки и скрытые ссылки, "
        "спам-домены, антифлуд, медиа-фильтр, проверка имён, чёрные списки, ночной режим, "
        "анти-рейд, анти-снос, капча (в чате и через заявку в ЛС).\n"
        "Модерация: /ban /mute /warn с эскалацией, роли, мягкий мут админов, /purge, /info, "
        "журнал, статистика и топы.\n"
        "Привлечение и общение: приветствия с кнопками, автоответы с медиа, болталка 2.0 "
        "(умные ответы на обращения, шутки, эмодзи-реакции), мат-фильтр из коробки "
        "(пред ×3 → бан), /all, зазывала, "
        "авто-промо, посты по расписанию, рассылки в группы и в ЛС подписчикам.\n"
        "Оплата: тариф «Профессиональный» звёздами Telegram (/pro), пробный период, "
        "бесплатное одобрение владельцем.\n\n"
        "Настройка — в ЛС: /panel. Помощь: /help."
    )


HELP_TEXT = (
    "📖 Команды бота\n\n"
    "В личке:\n"
    "/panel — панель управления (выбор группы и все настройки)\n"
    "/status — сводка по выбранной группе · /pro — тариф\n"
    "/userid — узнать свой ID · /cancel — отменить ввод · /skip — пропустить шаг\n"
    + add_help_text + "\n\n"
    "В группе (модерация — по правам):\n"
    "/ban /unban /kick — бан/кик (реплаем, @user или ID; можно срок: /ban 2ч причина)\n"
    "/mute /unmute — мут (по админам — «мягкий»: просто удаляю их сообщения)\n"
    "/warn /unwarn /warns — предупреждения с эскалацией\n"
    "/info — карточка участника с кнопками · /purge — чистка (реплаем на начало)\n"
    "/rules /setrules — правила · /report — жалоба модераторам · /me — обо мне\n"
    "/stats /top — статистика и топ · /invite — ссылка · /zazyvala — зазывала\n"
    "/all /stopall — призыв участников · /reg /anreg — подписка на призыв\n"
    "/block /unblock — чёрный список группы · /diag — диагностика · /pro — тариф\n"
    "/gmanager /ungmanager /gmanagers — менеджеры группы (назначает создатель)\n"
    "/appeal текст — апелляция владельцам бота\n"
    "/shop — магазин Mini App: тариф PRO и товары за звёзды"
)

GROUPADMIN_HELP = (
    "🛡 Быстрый старт для админа группы\n\n"
    "1) Выдай мне права администратора: удаление сообщений, бан, приглашения.\n"
    "2) Открой /panel в ЛС, выбери свою группу — там все фильтры и функции.\n"
    "3) Включи нужное: стоп-слова, ссылки, антифлуд, капчу, приветствие, болталку.\n"
    "4) Автоответы: /add ключ - ответ прямо в группе или в панели.\n"
    "5) Служебный чат для уведомлений: добавь меня туда и выполни /setstaff.\n\n"
    "Полный список команд — /help."
)

# ───────────────────────────────────────────────────────────────────────────
#  ОБРАБОТКА КНОПОК ПАНЕЛИ
# ───────────────────────────────────────────────────────────────────────────


async def handle_allstop_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "all"):
        return await query.answer("Нет прав", show_alert=True)
    _all_active[chat.id] = False
    await query.answer("⏹ Останавливаю призыв")


# Разделы и действия, доступные только владельцу/менеджерам бота
_MANAGER_CB = (
    "m:global", "m:approve", "m:promo", "m:sched", "m:backup",
    "appr:", "apt:", "pr:", "pto:", "dmto:", "dm:del:subs",
    "dgw:", "dgbid:", "dgbname:",
    "add:gword", "add:gbid", "add:gbname", "add:invitetext",
    "add:promo_content", "add:promo_btns", "add:bcast", "add:post",
    "sptgl:", "spdel:", "spg:", "tz:", "bk:",
    "m:shop", "shp:", "dsi:", "add:shopitem", "add:shoptitle",
)


async def _render_menu(query, context, view: str):
    """Единая отрисовка разделов панели."""
    cfg = panel_cfg_view(context)
    label = panel_target_label(context)
    tgt = context.user_data.get("cfg_target")
    mgr = is_manager(query.from_user.id)
    views = {
        "m:main": (status_text(cfg, label), main_menu_kb(cfg, mgr)),
        "m:quick": (f"⚡ Быстрые настройки · {label}", quick_kb(cfg)),
        "m:toggles": (f"🔧 Все фильтры · {label}", toggles_kb(cfg)),
        "m:words": (words_menu_text(cfg, label), words_kb(cfg)),
        "m:whitewords": (whitewords_menu_text(cfg, label), whitewords_kb(cfg)),
        "m:words2": (words2_menu_text(cfg, label), words2_kb(cfg)),
        "m:links": (links_menu_text(cfg, label), links_kb(cfg)),
        "m:flood": (f"🌊 Антифлуд · {label}", flood_kb(cfg)),
        "m:mod": (mod_menu_text(cfg, label), mod_kb(cfg)),
        "m:media": (media_menu_text(cfg, label), media_kb(cfg)),
        "m:night": (night_menu_text(cfg, label), night_kb(cfg)),
        "m:triggers": (triggers_menu_text(cfg, label), triggers_kb(cfg)),
        "m:chatter": (chatter_menu_text(cfg, label), chatter_kb(cfg)),
        "m:welcome": (welcome_menu_text(cfg, label), welcome_kb(cfg)),
        "m:captcha": (captcha_menu_text(cfg, label), captcha_kb(cfg)),
        "m:rules": (rules_menu_text(cfg, label), rules_kb(cfg)),
        "m:blacklist": (blacklist_menu_text(cfg, label), blacklist_kb(cfg)),
        "m:antiraid": (antiraid_menu_text(cfg, label), antiraid_kb(cfg)),
        "m:antinuke": (antinuke_menu_text(cfg, label), antinuke_kb(cfg)),
        "m:roles": (roles_menu_text(cfg, label), roles_kb(cfg)),
        "m:staff": (staff_menu_text(cfg, label), staff_kb(cfg)),
        "m:gmgr": (gmgr_menu_text(cfg, label), gmgr_kb(cfg, tgt)),
        "m:cmdperms": (cmdperms_menu_text(cfg, label), cmdperms_kb(cfg)),
        "m:lang": (f"🌐 Язык сообщений для новичков · {label}", lang_kb(cfg)),
        "m:recurring": (recurring_menu_text(cfg, label), recurring_kb(cfg)),
        "m:other": (other_menu_text(cfg, label), other_kb(cfg)),
        "m:global": (global_menu_text(), global_kb()),
        "m:access": (access_menu_text(tgt, label), access_kb(tgt, mgr)),
        "m:approve": (approve_menu_text(), approve_kb()),
        "m:promo": (promo_menu_text(label), promo_kb()),
        "m:sched": (sched_menu_text(), sched_kb()),
        "m:backup": (backup_menu_text(label), backup_kb()),
        "m:shop": (shop_menu_text(), shop_kb()),
    }
    hubs = {"m:h_protect": hub_protect, "m:h_words": hub_words, "m:h_mod": hub_mod,
            "m:h_talk": hub_talk, "m:h_posts": hub_posts, "m:h_sys": hub_sys}
    if view in hubs:
        views[view] = hubs[view](cfg, label, mgr)
    elif view == "m:h_stats":
        views[view] = hub_stats(cfg, label, mgr, tgt)
    if view == "m:pick":
        groups = (list(CONFIG.get("groups", {}).items()) if mgr
                  else await user_admin_groups(context, query.from_user.id))
        await safe_edit(query, "📂 Выбери группу для настройки:", pick_kb(groups))
        return await query.answer()
    text, kb = views.get(view, views["m:main"])
    if view in PANEL_PARENT and kb is not None:
        kb = _with_back(kb, PANEL_PARENT[view])
    await safe_edit(query, text, kb)
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass


async def _ask(query, context, state: str, prompt: str):
    """Перевести панель в режим ожидания текста от пользователя."""
    context.user_data["awaiting"] = state
    await safe_edit(query, prompt)
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    user = update.effective_user
    mgr = is_manager(user.id)

    # ── одобрение групп (кнопки из уведомления и раздела) ──
    if data.startswith("appr:"):
        if not mgr:
            return await query.answer("Только для владельца бота", show_alert=True)
        try:
            _, verdict, cid = data.split(":", 2)
            cid = int(cid)
        except ValueError:
            return await query.answer()
        title = CONFIG.get("groups", {}).get(str(cid), str(cid))
        if verdict == "ok":
            if cid not in CONFIG.setdefault("approved_chats", []):
                CONFIG["approved_chats"].append(cid)
                save_config(force=True)
            try:
                await context.bot.send_message(cid, "✅ Группа одобрена — я включился! Настройки: /panel в ЛС.")
            except Exception:  # noqa: BLE001
                pass
            note = f"✅ «{title}» одобрена."
        else:
            note = f"🚫 «{title}» оставлена без допуска (пусть оформляют /pro)."
        try:
            await query.edit_message_text(note)
        except Exception:  # noqa: BLE001
            await _render_menu(query, context, "m:approve")
        return await query.answer("Готово")

    # ── выбор группы ──
    if data == "m:pick":
        return await _render_menu(query, context, "m:pick")
    if data.startswith("pick:"):
        tgt = data.split(":", 1)[1]
        if not await can_edit_target(context, user.id, tgt):
            return await query.answer("Эта группа не под твоим управлением", show_alert=True)
        context.user_data["cfg_target"] = tgt
        context.user_data.pop("awaiting", None)
        return await _render_menu(query, context, "m:main")

    # ── доступ: менеджерские разделы и проверка своей группы ──
    if not mgr:
        if any(data == p or data.startswith(p) for p in _MANAGER_CB):
            return await query.answer("Только для владельца бота", show_alert=True)
        if not await can_edit_target(context, user.id, context.user_data.get("cfg_target")):
            return await _render_menu(query, context, "m:pick")

    if data.startswith("m:"):
        return await _render_menu(query, context, data)

    wcfg = panel_cfg(context)
    tgt = context.user_data.get("cfg_target")

    # ── менеджеры группы (назначает только создатель группы или владелец бота) ──
    if data == "add:gmgr" or data.startswith("dgm:"):
        if (not tgt or tgt == "defaults"
                or not await can_assign_group_managers(context, int(tgt), user.id)):
            return await query.answer("Назначать менеджеров может создатель группы или владелец бота",
                                      show_alert=True)
        if data.startswith("dgm:"):
            lst = wcfg.setdefault("group_managers", [])
            i = int(data.split(":", 1)[1])
            if 0 <= i < len(lst):
                lst.pop(i)
                save_config(force=True)
            return await _render_menu(query, context, "m:gmgr")
        return await _ask(query, context, "gmgr",
                          "Пришли ID будущих менеджеров через запятую (свой ID человек узнаёт "
                          "командой /userid в ЛС бота). (или /cancel)")

    # ── запросы текста от пользователя ──
    prompts = {
        "add:word": ("word", "Пришли стоп-слова через запятую.\n"
                             "Синтаксис: слово · слово* · *слово · *слово*. (или /cancel)"),
        "add:word2": ("word2", "Пришли слова для второго списка через запятую. (или /cancel)"),
        "add:wword": ("wword", "Пришли исключения (белый список) через запятую. (или /cancel)"),
        "add:link": ("link", "Пришли спам-домены через запятую, например: casino-x.com, spam.ru (или /cancel)"),
        "add:trigger": ("trigger", "Формат: ключ - ответ\nНесколько ключей: цена,прайс - смотри закреп\n"
                                   "Работает {рандомизация|вариантов}. (или /cancel)"),
        "add:chphrase": ("chphrase", "Пришли шутки для болталки — по одной на строку.\n"
                                     "Работает {рандомизация|вариантов}. (или /cancel)"),
        "add:chreply": ("chreply", "Пришли ответы на обращения к боту — по одной на строку. (или /cancel)"),
        "add:gopword": ("gopword", "Пришли слова-триггеры гоп-режима через запятую — на них бот "
                                   "ответит по-пацански даже без обращения.\n"
                                   "Синтаксис со «*» — как у стоп-слов. (или /cancel)"),
        "add:trigmedia": ("trig_keys", "Шаг 1/3. Пришли ключ(и) автоответа — через запятую. (или /cancel)"),
        "add:blid": ("blid", "Пришли ID пользователей через запятую — забаню в этой группе. (или /cancel)"),
        "add:blname": ("blname", "Пришли подстроки имени/юзернейма через запятую. (или /cancel)"),
        "add:welcome": ("welcome", "Пришли текст приветствия.\n"
                                   "Подстановки: {name}, {mention}, {chat}. (или /cancel)"),
        "add:welcome_btns": ("welcome_btns", "Кнопки приветствия: «Текст - https://ссылка», по строке на ряд; "
                                             "несколько в ряд — через «;». «-» — убрать кнопки. (или /cancel)"),
        "add:rules": ("rules", "Пришли новый текст правил. (или /cancel)"),
        "add:recurring": ("recurring", "Формат: интервал_минут | текст\nНапример: 120 | Не забывайте про "
                                       "правила 🙌\nРаботает {рандомизация|вариантов}. (или /cancel)"),
        "add:rolenew": ("rolenew", "Название новой роли (одно слово, без «:»). (или /cancel)"),
        "add:invitetext": ("invitetext", "Пришли текст «зазывалы» — сообщения с кнопкой "
                                         "«Пригласить друга». (или /cancel)"),
        "add:staff": ("staff", "Пришли ID служебного чата (отрицательное число, узнать — /diag в нём). "
                               "(или /cancel)"),
        "add:gword": ("gword", "Пришли ГЛОБАЛЬНЫЕ стоп-слова через запятую — подействуют во всех группах. "
                               "(или /cancel)"),
        "add:gbid": ("gbid", "Пришли ID для глобального чёрного списка через запятую. (или /cancel)"),
        "add:gbname": ("gbname", "Пришли подстроки имени для глобального ЧС через запятую. (или /cancel)"),
        "add:promo_content": ("promo_content", "Пришли контент промо: текст или медиа с подписью "
                                               "(HTML и {рандомизация|вариантов} работают). (или /cancel)"),
        "add:promo_btns": ("promo_btns", "Кнопки промо: «Текст - https://ссылка», по строке на ряд; "
                                         "«-» — убрать. (или /cancel)"),
        "add:bcast": ("bcast", "Пришли пост для рассылки в группы: текст или медиа с подписью, "
                               "потом выберешь группы. (или /cancel)"),
        "add:shopitem": ("shopitem", "Новый товар одной строкой:\n"
                                     "Название | цена в звёздах | описание | что выдать после оплаты\n"
                                     "Например: Реклама в чате | 300 | Пост с закрепом на сутки | "
                                     "Напиши @manager — разместим\n(или /cancel)"),
        "add:shoptitle": ("shoptitle", "Название магазина (видно в шапке Mini App). (или /cancel)"),
        "add:post": ("sp_time", "Шаг 1/3. Время поста: ЧЧ:ММ [дни через запятую]\n"
                                "Например: 09:30 пн,ср,пт — без дней = ежедневно. (или /cancel)"),
    }
    if data in prompts:
        state, prompt = prompts[data]
        return await _ask(query, context, state, prompt)

    # ── роли ──
    if data.startswith("rl:"):
        name = data[3:]
        return await _finish_role_view(query, context, wcfg, name, tgt)
    if data.startswith("rp:"):
        _, name, perm = data.split(":", 2)
        r = wcfg.setdefault("roles", {}).setdefault(name, {"perms": [], "members": []})
        if perm in r["perms"]:
            r["perms"].remove(perm)
        else:
            r["perms"].append(perm)
        save_config()
        return await _finish_role_view(query, context, wcfg, name, tgt)
    if data.startswith("rmadd:"):
        context.user_data["role_name"] = data[6:]
        return await _ask(query, context, "rolemember",
                          "Пришли ID участников через запятую — добавлю в роль. (или /cancel)")
    if data.startswith("rmx:"):
        _, name, uid = data.split(":", 2)
        r = wcfg.setdefault("roles", {}).get(name)
        if r and int(uid) in r.get("members", []):
            r["members"].remove(int(uid))
            save_config()
        return await _finish_role_view(query, context, wcfg, name, tgt)
    if data.startswith("rdel:"):
        wcfg.setdefault("roles", {}).pop(data[5:], None)
        save_config()
        return await _render_menu(query, context, "m:roles")

    # ── удаление из списков ──
    del_map = {"dw:": ("stop_words", "m:words"), "dw2:": ("stop_words2", "m:words2"),
               "dww:": ("white_words", "m:whitewords"), "dl:": ("spam_links", "m:links")}
    for pref, (key, back) in del_map.items():
        if data.startswith(pref):
            lst = wcfg.setdefault(key, [])
            i = int(data.split(":", 1)[1])
            if 0 <= i < len(lst):
                lst.pop(i)
                save_config()
            return await _render_menu(query, context, back)
    if data.startswith("dt:"):
        keys = [k for k, _v in sorted(wcfg.get("triggers", {}).items())]
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(keys):
            wcfg["triggers"].pop(keys[i], None)
            save_config()
        return await _render_menu(query, context, "m:triggers")
    if data.startswith(("dblid:", "dblname:")):
        bl = wcfg.setdefault("blacklist", {"ids": [], "names": []})
        lst = bl.setdefault("ids" if data.startswith("dblid:") else "names", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(lst):
            lst.pop(i)
            save_config()
        return await _render_menu(query, context, "m:blacklist")
    if data.startswith("dgw:"):
        lst = CONFIG.setdefault("global_stop_words", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(lst):
            lst.pop(i)
            save_config(force=True)
        return await _render_menu(query, context, "m:global")
    if data.startswith(("dgbid:", "dgbname:")):
        gb = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
        lst = gb.setdefault("ids" if data.startswith("dgbid:") else "names", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(lst):
            lst.pop(i)
            save_config(force=True)
        return await _render_menu(query, context, "m:global")

    # ── циклы значений и переключатели ──
    if data == "mode:trig":
        wcfg["trigger_match"] = "contains" if wcfg.get("trigger_match", "word") == "word" else "word"
        save_config()
        return await _render_menu(query, context, "m:triggers")
    if data.startswith("cht:"):
        ch = wcfg.setdefault("chatter", {})
        k = data[4:]
        if k == "tgl":
            ch["enabled"] = not ch.get("enabled")
        elif k == "chance":
            ch["chance"] = _cycle([1, 2, 3, 5, 10, 20], int(ch.get("chance", 5)))
        elif k == "cd":
            ch["cooldown"] = _cycle([60, 180, 300, 600, 1800], int(ch.get("cooldown", 180)))
        elif k == "men":
            ch["reply_mentions"] = not ch.get("reply_mentions", True)
        elif k == "smart":
            ch["smart_replies"] = not ch.get("smart_replies", True)
        elif k == "react":
            ch["reactions"] = not ch.get("reactions", True)
        elif k == "rchance":
            ch["reaction_chance"] = _cycle([3, 5, 8, 15, 25], int(ch.get("reaction_chance", 8)))
        elif k == "gop":
            ch["gopnik"] = not ch.get("gopnik")
        elif k == "fun":
            ch["fun"] = not ch.get("fun", True)
        elif k == "ai":
            ch["ai"] = not ch.get("ai")
        save_config()
        return await _render_menu(query, context, "m:chatter")
    if data.startswith("dgp:"):
        ch = wcfg.setdefault("chatter", {})
        lst = ch.setdefault("gop_words", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(lst):
            lst.pop(i)
            save_config()
        return await _render_menu(query, context, "m:chatter")
    if data.startswith(("dcp:", "dcr:")):
        ch = wcfg.setdefault("chatter", {})
        lst = ch.setdefault("phrases" if data.startswith("dcp:") else "replies", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(lst):
            lst.pop(i)
            save_config()
        return await _render_menu(query, context, "m:chatter")
    if data in ("q:spamact", "q:spamact2"):
        wcfg["spam_action"] = _cycle(_ACT_CYCLE, wcfg.get("spam_action", "delete"))
        save_config()
        return await _render_menu(query, context, "m:quick" if data == "q:spamact" else "m:words")
    if data.startswith("q:"):
        k = data[2:]
        wcfg.setdefault("enabled", {})[k] = not wcfg["enabled"].get(k)
        save_config()
        return await _render_menu(query, context, "m:quick")
    if data.startswith("t2:"):
        _, k, view = data.split(":", 2)
        wcfg.setdefault("enabled", {})[k] = not wcfg["enabled"].get(k)
        save_config()
        return await _render_menu(query, context, "m:" + view)
    if data.startswith("t:"):
        k = data[2:]
        wcfg.setdefault("enabled", {})[k] = not wcfg["enabled"].get(k)
        save_config()
        return await _render_menu(query, context, "m:toggles")
    if data.startswith("fl:"):
        f = wcfg.setdefault("flood", {})
        k = data[3:]
        if k == "limit":
            f["limit"] = _cycle([3, 5, 8, 12, 20], int(f.get("limit", 5)))
        elif k == "period":
            f["period"] = _cycle([5, 10, 15, 30, 60], int(f.get("period", 10)))
        elif k == "mute":
            f["mute"] = _cycle([60, 300, 900, 3600, 86400], int(f.get("mute", 300)))
        save_config()
        return await _render_menu(query, context, "m:flood")
    if data.startswith("md:"):
        m = wcfg.setdefault("moderation", {})
        k = data[3:]
        if k == "limit":
            m["warn_limit"] = _cycle([2, 3, 4, 5], int(m.get("warn_limit", 3)))
        elif k == "act":
            m["warn_action"] = "ban" if m.get("warn_action") == "mute" else "mute"
        elif k == "mute":
            m["warn_mute"] = _cycle([600, 1800, 3600, 10800, 86400], int(m.get("warn_mute", 3600)))
        elif k == "exp":
            m["warn_expire_days"] = _cycle([0, 7, 14, 30], int(m.get("warn_expire_days", 0)))
        elif k == "smute":
            m["spam_mute"] = _cycle([0, 300, 900, 3600, 86400], int(m.get("spam_mute", 0) or 0))
        elif k == "only":
            m["mod_admins_only"] = not m.get("mod_admins_only")
        elif k == "log":
            m["log_actions"] = not m.get("log_actions")
        elif k == "nd":
            m["notify_delete"] = not m.get("notify_delete")
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
        mb = wcfg.setdefault("media_block", {})
        mb[k] = not mb.get(k)
        save_config()
        return await _render_menu(query, context, "m:media")
    if data.startswith("nm:"):
        n = wcfg.setdefault("night", {})
        k = data[3:]
        if k == "tgl":
            n["enabled"] = not n.get("enabled")
        elif k == "start":
            n["start"] = (int(n.get("start", 23)) + 1) % 24
        elif k == "end":
            n["end"] = (int(n.get("end", 7)) + 1) % 24
        elif k == "tz":
            order = list(range(0, 13)) + list(range(-12, 0))
            n["tz"] = _cycle(order, int(n.get("tz", 0)))
        save_config()
        return await _render_menu(query, context, "m:night")
    if data.startswith("wl:"):
        w = wcfg.setdefault("welcome", {})
        k = data[3:]
        if k == "tgl":
            w["enabled"] = not w.get("enabled")
        elif k == "after":
            w["delete_after"] = _cycle([0, 30, 60, 300, 900], int(w.get("delete_after", 0) or 0))
        save_config()
        return await _render_menu(query, context, "m:welcome")
    if data.startswith("cp:"):
        c = wcfg.setdefault("captcha", {})
        k = data[3:]
        if k == "tgl":
            c["enabled"] = not c.get("enabled")
        elif k == "to":
            c["timeout"] = _cycle([60, 120, 300, 600], int(c.get("timeout", 120)))
        elif k == "act":
            c["action"] = "mute" if c.get("action", "kick") == "kick" else "kick"
        elif k == "via":
            c["via_request"] = not c.get("via_request", True)
        save_config()
        return await _render_menu(query, context, "m:captcha")
    if data.startswith("ar:"):
        a = wcfg.setdefault("antiraid", {})
        k = data[3:]
        if k == "tgl":
            a["enabled"] = not a.get("enabled")
        elif k == "joins":
            a["joins"] = _cycle([5, 8, 12, 20], int(a.get("joins", 8)))
        elif k == "win":
            a["window"] = _cycle([30, 60, 120, 300], int(a.get("window", 60)))
        elif k == "lock":
            a["lock_min"] = _cycle([5, 10, 30, 60], int(a.get("lock_min", 10)))
        save_config()
        return await _render_menu(query, context, "m:antiraid")
    if data.startswith("an:"):
        a = wcfg.setdefault("antinuke", {})
        k = data[3:]
        if k == "tgl":
            a["enabled"] = not a.get("enabled")
        elif k == "thr":
            a["ban_threshold"] = _cycle([3, 5, 8, 12], int(a.get("ban_threshold", 5)))
        elif k == "win":
            a["window"] = _cycle([15, 30, 60, 120], int(a.get("window", 30)))
        elif k == "act":
            a["action"] = "ban" if a.get("action") == "stop" else "stop"
        save_config()
        return await _render_menu(query, context, "m:antinuke")
    if data.startswith("perm:"):
        k = data[5:]
        cp = wcfg.setdefault("cmd_perms", {})
        cp[k] = _cycle(CMD_LEVELS.get(k, ["admins", "owner"]), cmd_level_from(wcfg, k))
        save_config()
        return await _render_menu(query, context, "m:cmdperms")
    if data.startswith("lang:"):
        wcfg["lang"] = data[5:]
        save_config()
        return await _render_menu(query, context, "m:lang")
    if data == "ji:cycle":
        wcfg["show_join_id"] = _cycle(["off", "all", "admins"], wcfg.get("show_join_id", "off"))
        save_config()
        return await _render_menu(query, context, "m:other")
    if data.startswith("rectgl:"):
        items = wcfg.setdefault("recurring", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(items) and isinstance(items[i], dict):
            items[i]["enabled"] = not items[i].get("enabled")
            save_config()
        return await _render_menu(query, context, "m:recurring")
    if data.startswith("recdel:"):
        items = wcfg.setdefault("recurring", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(items):
            items.pop(i)
            save_config()
        return await _render_menu(query, context, "m:recurring")
    if data == "st:clear":
        if tgt and tgt != "defaults":
            CONFIG.get("msg_stats", {}).pop(str(tgt), None)
            CONFIG.get("warns", {}).pop(str(tgt), None)
            CONFIG.get("warns_ts", {}).pop(str(tgt), None)
            save_config(force=True)
        await query.answer("🧹 Статистика группы очищена")
        return await _render_menu(query, context, "m:other")
    if data == "resetchat":
        if tgt and tgt != "defaults" and str(tgt) in CONFIG.get("chats", {}):
            CONFIG["chats"].pop(str(tgt), None)
            save_config(force=True)
        await query.answer("♻️ Настройки группы сброшены к шаблону")
        return await _render_menu(query, context, "m:main")
    if data == "tz:cycle":
        order = list(range(0, 13)) + list(range(-12, 0))
        CONFIG["post_tz"] = _cycle(order, int(CONFIG.get("post_tz", 0)))
        save_config(force=True)
        return await _render_menu(query, context, "m:sched")
    if data == "dm:del:staff":
        wcfg["staff_group"] = 0
        save_config()
        return await _render_menu(query, context, "m:staff")
    if data == "dm:del:subs":
        if tgt and tgt != "defaults":
            CONFIG.setdefault("dm_subscribers", {}).pop(str(tgt), None)
            save_config(force=True)
        await query.answer("🗑 ЛС-подписчики группы очищены")
        return await _render_menu(query, context, "m:promo")
    if data == "apt:req":
        if not is_owner(user.id):
            return await query.answer("Только главный владелец", show_alert=True)
        CONFIG["require_approval"] = not CONFIG.get("require_approval", True)
        save_config(force=True)
        return await _render_menu(query, context, "m:access")
    if data.startswith("pr:"):
        p = CONFIG["promo"]
        k = data[3:]
        if k == "tgl":
            p["enabled"] = not p.get("enabled")
        elif k == "int":
            p["interval"] = _cycle([1800, 3600, 7200, 14400, 43200, 86400], int(p.get("interval", 3600)))
        elif k == "pin":
            p["pin"] = not p.get("pin")
        save_config(force=True)
        return await _render_menu(query, context, "m:promo")

    # ── выбор групп для рассылок ──
    if data.startswith("pto:"):
        k = data[4:]
        sel = context.user_data.setdefault("pto_sel", {"all"})
        if k == "go":
            post = context.user_data.pop("bcast_post", None)
            context.user_data.pop("pto_sel", None)
            if not post:
                return await query.answer("Сначала пришли пост (📤 Рассылка в группы)", show_alert=True)
            targets = (list(CONFIG.get("groups", {}).keys()) if "all" in sel
                       else [c for c in sel if c != "all"])
            ok = fail = 0
            await safe_edit(query, f"📤 Рассылаю в {len(targets)} групп…")
            for cid in targets:
                if await deliver(context, cid, post):
                    ok += 1
                else:
                    fail += 1
                await asyncio.sleep(0.1)
            await safe_edit(query, f"📤 Рассылка готова: отправлено {ok}, недоступно {fail}.",
                            InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ В панель", callback_data="m:promo")]]))
            return await query.answer()
        if k == "all":
            sel.clear() if "all" in sel else (sel.clear(), sel.add("all"))
        else:
            sel.discard("all")
            sel.symmetric_difference_update({k})
        await safe_edit(query, "📤 Куда отправить пост?", post_groups_kb(sel, "pto"))
        return await query.answer()
    if data.startswith("dmto:"):
        k = data[5:]
        sel = context.user_data.setdefault("dmto_sel", set())
        if k == "pick":
            if tgt and tgt != "defaults":
                sel.add(str(tgt))
            await safe_edit(query, "💬 Подписчикам каких групп отправить?", post_groups_kb(sel, "dmto"))
            return await query.answer()
        if k == "go":
            if not sel and not ("all" in sel):
                return await query.answer("Выбери хотя бы одну группу", show_alert=True)
            return await _ask(query, context, "dmcast",
                              "Пришли пост для рассылки в ЛС: текст или медиа с подписью. (или /cancel)")
        if k == "all":
            sel.clear() if "all" in sel else (sel.clear(), sel.add("all"))
        else:
            sel.discard("all")
            sel.symmetric_difference_update({k})
        await safe_edit(query, "💬 Подписчикам каких групп отправить?", post_groups_kb(sel, "dmto"))
        return await query.answer()

    # ── посты по расписанию ──
    if data.startswith("sptgl:"):
        p = _find_post(data[6:])
        if p:
            p["enabled"] = not p.get("enabled", True)
            save_config(force=True)
        return await _render_menu(query, context, "m:sched")
    if data.startswith("spdel:"):
        pid = data[6:]
        CONFIG["scheduled_posts"] = [p for p in CONFIG.get("scheduled_posts", []) if p.get("id") != pid]
        save_config(force=True)
        return await _render_menu(query, context, "m:sched")
    if data.startswith("spg:"):
        rest = data[4:].split(":")
        p = _find_post(rest[0])
        if not p:
            return await _render_menu(query, context, "m:sched")
        if len(rest) == 1:
            await safe_edit(query, f"👥 Группы для поста {p.get('time', '')}:", sched_groups_kb(p))
            return await query.answer()
        pick = rest[1]
        if pick == "all":
            p["chats"] = "all"
        else:
            ch = p.get("chats", "all")
            sel = set() if ch == "all" else {str(c) for c in ch}
            sel.symmetric_difference_update({pick})
            p["chats"] = sorted(sel) if sel else "all"
        save_config(force=True)
        await safe_edit(query, f"👥 Группы для поста {p.get('time', '')}:", sched_groups_kb(p))
        return await query.answer()

    # ── магазин ──
    if data == "shp:tgl":
        s = CONFIG.setdefault("shop", {})
        s["enabled"] = not s.get("enabled")
        save_config(force=True)
        return await _render_menu(query, context, "m:shop")
    if data.startswith("dsi:"):
        items = CONFIG.setdefault("shop", {}).setdefault("items", [])
        i = int(data.split(":", 1)[1])
        if 0 <= i < len(items):
            items.pop(i)
            save_config(force=True)
        return await _render_menu(query, context, "m:shop")

    # ── бэкапы ──
    if data == "bk:full":
        await send_backup(context, user.id)
        return await query.answer("🗄 Отправил файл")
    if data == "bk:chat":
        if not tgt or tgt == "defaults":
            return await query.answer("Сначала выбери группу", show_alert=True)
        await send_chat_backup(context, user.id, tgt)
        return await query.answer("📂 Отправил файл")

    await query.answer()


async def _finish_role_view(query, context, wcfg, name: str, tgt):
    r = (wcfg.get("roles") or {}).get(name)
    if r is None:
        return await _render_menu(query, context, "m:roles")
    perms = ", ".join(t for k, t in ROLE_PERM_DEFS if k in r.get("perms", [])) or "— нет —"
    text = (f"🎖 Роль «{name}»\n\n"
            f"Права: {perms}\nУчастников: {len(r.get('members', []))}\n\n"
            "Выдать в группе: /role " + name + " (реплаем на сообщение).")
    await safe_edit(query, text, role_detail_kb(wcfg, name, tgt))
    try:
        await query.answer()
    except Exception:  # noqa: BLE001
        pass

# ───────────────────────────────────────────────────────────────────────────
#  ЧС ИЗ ЧАТА
# ───────────────────────────────────────────────────────────────────────────


async def cmd_block(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban", update=update):
        return await _deny(update)
    tid, tname = await resolve_target(update, context)
    bl = chat_cfg_writable(chat.id).setdefault("blacklist", {"ids": [], "names": []})
    if tid:
        if is_manager(tid):
            return await update.effective_message.reply_text("Это владелец/менеджер бота.")
        if tid not in bl["ids"]:
            bl["ids"].append(tid)
            save_config()
        await _ban_quiet(context, chat.id, tid)
        return await reply_tidy(update, context, f"⛔ {tname} в чёрном списке группы и забанен.")
    arg = _args_text(update)
    if arg:
        if arg.lower() not in bl["names"]:
            bl["names"].append(arg.lower())
            save_config()
        return await reply_tidy(update, context, f"⛔ Подстрока имени «{arg}» в чёрном списке группы.")
    await update.effective_message.reply_text("Формат: /block (реплай | ID | подстрока имени)")


async def cmd_unblock(update: Update, context):
    chat = update.effective_chat
    if not await can_moderate(context, chat.id, update.effective_user.id, "ban", update=update):
        return await _deny(update)
    bl = chat_cfg_writable(chat.id).setdefault("blacklist", {"ids": [], "names": []})
    tid, tname = await resolve_target(update, context)
    if tid and tid in bl["ids"]:
        bl["ids"].remove(tid)
        save_config()
        try:
            await context.bot.unban_chat_member(chat.id, tid, only_if_banned=True)
        except Exception:  # noqa: BLE001
            pass
        return await reply_tidy(update, context, f"✅ {tname} убран из чёрного списка.")
    arg = _args_text(update)
    if arg and arg.lower() in bl["names"]:
        bl["names"].remove(arg.lower())
        save_config()
        return await reply_tidy(update, context, "✅ Подстроку убрал из чёрного списка.")
    await update.effective_message.reply_text("Не нашёл такого в ЧС. Формат: /unblock ID | подстрока")

# ───────────────────────────────────────────────────────────────────────────
#  ЛИЧНЫЕ КОМАНДЫ
# ───────────────────────────────────────────────────────────────────────────


def add_group_button():
    uname = _state.get("bot_username")
    if not uname:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(
        "➕ Добавить меня в группу", url=f"https://t.me/{uname}?startgroup=true")]])


async def _ensure_panel_target(update: Update, context) -> bool:
    """Гарантирует выбранную группу в панели. False — попросили выбрать/добавить."""
    user = update.effective_user
    tgt = context.user_data.get("cfg_target")
    if tgt and tgt != "defaults" and await can_edit_target(context, user.id, tgt):
        return True
    groups = (list(CONFIG.get("groups", {}).items()) if is_manager(user.id)
              else await user_admin_groups(context, user.id))
    if len(groups) == 1:
        context.user_data["cfg_target"] = groups[0][0]
        return True
    if not groups:
        await update.effective_message.reply_text(
            "Я пока не вижу групп под твоим управлением.\n"
            "Добавь меня в группу и дай права администратора — и возвращайся в /panel.",
            reply_markup=add_group_button())
        return False
    await update.effective_message.reply_text("📂 Выбери группу для настройки:", reply_markup=pick_kb(groups))
    return False


async def cmd_start(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type in ("group", "supergroup"):
        return await reply_tidy(update, context,
                                "👋 Я на месте. Настройки — в ЛС: открой меня и набери /panel.")
    context.user_data.pop("awaiting", None)
    if context.args and context.args[0].startswith("shop"):
        return await _send_shop_button(update.effective_message, context.args[0][4:])
    text = ("👋 Привет! Я — Channel Guard: антиспам, модерация, капча, автоответы, болталка, "
            "посты и рассылки для твоих групп.\n\n"
            "1) Добавь меня в группу и дай права администратора (удаление, бан, приглашения).\n"
            "2) Открой /panel — там все настройки по каждой группе.\n\n"
            "Помощь — /help, о боте — /about, тариф — /pro.")
    if not is_manager(user.id):
        text += "\n\n" + GROUPADMIN_HELP
    await update.effective_message.reply_text(text, reply_markup=add_group_button())


async def cmd_panel(update: Update, context):
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        return await reply_tidy(update, context, "Панель — в ЛС: открой меня и набери /panel.")
    if not await _ensure_panel_target(update, context):
        return
    cfg = panel_cfg_view(context)
    label = panel_target_label(context)
    await update.effective_message.reply_text(
        status_text(cfg, label), reply_markup=main_menu_kb(cfg, is_manager(update.effective_user.id)))


async def cmd_status(update: Update, context):
    if update.effective_chat.type in ("group", "supergroup"):
        return await cmd_diag(update, context)
    if not await _ensure_panel_target(update, context):
        return
    cfg = panel_cfg_view(context)
    tgt = context.user_data.get("cfg_target")
    label = panel_target_label(context)
    text = status_text(cfg, label)
    if tgt and tgt != "defaults":
        text += f"\n\nДоступ: {access_status(int(tgt))}"
    await update.effective_message.reply_text(text)


async def cmd_help(update: Update, context):
    await reply_tidy(update, context, HELP_TEXT, seconds=30)


async def cmd_about(update: Update, context):
    await reply_tidy(update, context, about_text(), seconds=30)


async def cmd_cancel(update: Update, context):
    for k in ("awaiting", "trig_draft", "sp_draft", "role_name", "bcast_post", "pto_sel", "dmto_sel"):
        context.user_data.pop(k, None)
    await update.effective_message.reply_text("Ок, отменил. Панель — /panel.")


def _finalize_sched_post(context) -> dict:
    """Собрать пост по расписанию из черновика мастера и сохранить."""
    d = context.user_data.pop("sp_draft", {})
    post = dict(d.get("content") or {"type": "text", "text": ""})
    post["id"] = _new_post_id()
    post["time"] = d.get("time", "12:00")
    post["days"] = d.get("days", [])
    post["chats"] = "all"
    post["enabled"] = True
    if d.get("buttons"):
        post["buttons"] = d["buttons"]
    CONFIG.setdefault("scheduled_posts", []).append(post)
    save_config(force=True)
    return post


def _save_trigger_draft(context):
    """Сохранить автоответ из мастера (ключи + контент + кнопки)."""
    d = context.user_data.pop("trig_draft", {})
    wcfg = panel_cfg(context)
    keys = d.get("keys") or []
    val = d.get("content") or {"type": "text", "text": d.get("text", "")}
    if d.get("buttons"):
        val = dict(val, buttons=d["buttons"])
    for k in keys:
        wcfg.setdefault("triggers", {})[k] = copy.deepcopy(val)
    save_config()
    return keys, val, wcfg


async def cmd_skip(update: Update, context):
    """Пропустить необязательный шаг мастера (кнопки)."""
    awaiting = context.user_data.get("awaiting")
    msg = update.effective_message
    if awaiting == "trig_btns":
        context.user_data.pop("awaiting", None)
        keys, val, wcfg = _save_trigger_draft(context)
        return await msg.reply_text(
            f"✅ Автоответ сохранён для: {', '.join(keys)} — {_trig_preview(val, 40)}",
            reply_markup=triggers_kb(wcfg))
    if awaiting == "sp_btns":
        context.user_data.pop("awaiting", None)
        post = _finalize_sched_post(context)
        return await msg.reply_text(
            f"✅ Пост создан: {post['time']} · {_post_groups_label(post)}. Группы — в 🗓 разделе.",
            reply_markup=sched_kb())
    if awaiting in ("welcome_btns", "promo_btns"):
        context.user_data.pop("awaiting", None)
        return await msg.reply_text("Ок, без кнопок. Панель — /panel.")
    await msg.reply_text("Сейчас нечего пропускать. Панель — /panel.")


async def cmd_userid(update: Update, context):
    u = update.effective_user
    await update.effective_message.reply_text(f"🆔 Твой ID: {u.id}")


async def cmd_setwelcome(update: Update, context):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text(
            "Выполни /setwelcome в группе или настрой приветствие в панели (/panel).")
    if not (is_manager(user.id) or await can_open_settings(context, chat.id, user.id)):
        return await _deny(update)
    text = _args_text(update)
    if not text:
        return await update.effective_message.reply_text(
            "Формат: /setwelcome текст ({name}, {mention}, {chat} — подстановки)")
    w = chat_cfg_writable(chat.id).setdefault("welcome", {})
    w["text"] = text
    w["enabled"] = True
    save_config()
    await reply_tidy(update, context, "👋 Приветствие сохранено и включено.")


async def cmd_grant(update: Update, context):
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    args = context.args or []
    if not args or not re.fullmatch(r"\d{5,}", args[0]):
        return await update.effective_message.reply_text("Формат: /grant user_id")
    uid = int(args[0])
    if uid not in CONFIG.setdefault("managers", []):
        CONFIG["managers"].append(uid)
        save_config(force=True)
    await update.effective_message.reply_text(f"✅ {uid} теперь менеджер бота.")


async def cmd_revoke(update: Update, context):
    if not is_owner(update.effective_user.id):
        return await _deny(update)
    args = context.args or []
    if not args or not re.fullmatch(r"\d{5,}", args[0]):
        return await update.effective_message.reply_text("Формат: /revoke user_id")
    uid = int(args[0])
    if uid in CONFIG.get("managers", []):
        CONFIG["managers"].remove(uid)
        save_config(force=True)
        return await update.effective_message.reply_text(f"✅ {uid} больше не менеджер.")
    await update.effective_message.reply_text("Такого менеджера нет.")


async def cmd_managers(update: Update, context):
    if not is_manager(update.effective_user.id):
        return await _deny(update)
    owners = ", ".join(str(i) for i in sorted(ADMIN_IDS))
    mgrs = ", ".join(str(i) for i in CONFIG.get("managers", [])) or "— нет —"
    await update.effective_message.reply_text(
        f"👑 Владельцы: {owners}\n🤝 Менеджеры: {mgrs}\n\nВыдать: /grant ID · забрать: /revoke ID")


async def cmd_settings_hint(update: Update, context):
    await reply_tidy(update, context, "⚙️ Все настройки — в ЛС бота: открой меня и набери /panel.")


async def _content_cfg(update: Update, context):
    """Куда писать /add и списки: в группе — конфиг этой группы, в ЛС — выбранной в панели.
    Возвращает (cfg, label) или (None, None) при отсутствии прав."""
    chat = update.effective_chat
    user = update.effective_user
    if chat.type in ("group", "supergroup"):
        if not (is_manager(user.id) or await can_open_settings(context, chat.id, user.id)):
            return None, None
        return chat_cfg_writable(chat.id), chat.title or str(chat.id)
    if not await _ensure_panel_target(update, context):
        return None, None
    if not await can_edit_target(context, user.id, context.user_data.get("cfg_target")):
        return None, None
    return panel_cfg(context), panel_target_label(context)


async def cmd_add(update: Update, context):
    cfg, label = await _content_cfg(update, context)
    if cfg is None:
        return
    raw = _args_text(update)
    m = re.match(r"(.+?)\s*[-—]\s*(.+)", raw, re.S) if raw else None
    if not m:
        return await update.effective_message.reply_text(
            "Формат: /add ключ - ответ\nНесколько ключей: /add цена,прайс - смотри закреп")
    keys = [k.strip().lower() for k in m.group(1).split(",") if k.strip()]
    resp = m.group(2).strip()
    for k in keys:
        cfg.setdefault("triggers", {})[k] = resp
    save_config()
    await reply_tidy(update, context, f"✅ Автоответ для: {', '.join(keys)} ({label})")


async def cmd_del(update: Update, context):
    cfg, label = await _content_cfg(update, context)
    if cfg is None:
        return
    key = _args_text(update).strip().lower()
    if not key:
        return await update.effective_message.reply_text("Формат: /del ключ")
    if cfg.get("triggers", {}).pop(key, None) is not None:
        save_config()
        return await reply_tidy(update, context, f"🗑 Удалил автоответ «{key}» ({label})")
    await update.effective_message.reply_text("Такого ключа нет. Список — /list.")


async def cmd_list(update: Update, context):
    cfg, label = await _content_cfg(update, context)
    if cfg is None:
        return
    trg = cfg.get("triggers", {})
    if not trg:
        return await reply_tidy(update, context, "Автоответов пока нет. Добавить: /add ключ - ответ")
    lines = [f"💬 Автоответы ({label}):"]
    for k, v in sorted(trg.items())[:50]:
        lines.append(f"• {k} → {_trig_preview(v, 40)}")
    await reply_tidy(update, context, "\n".join(lines), seconds=30)


def _make_list_cmds(key: str, title: str, addcmd: str):
    """Фабрика команд /addword|/addlink + удаление + показ для списков слов/доменов."""

    async def _add(update: Update, context):
        cfg, label = await _content_cfg(update, context)
        if cfg is None:
            return
        words = _csv(_args_text(update))
        if not words:
            return await update.effective_message.reply_text(f"Формат: /{addcmd} слово1, слово2")
        added = _add_unique(cfg.setdefault(key, []), words)
        if added:
            save_config()
        await reply_tidy(update, context,
                         (f"✅ Добавлено: {', '.join(added)}" if added else "Всё это уже есть.")
                         + f" ({label})")

    async def _del(update: Update, context):
        cfg, label = await _content_cfg(update, context)
        if cfg is None:
            return
        words = _csv(_args_text(update))
        lst = cfg.setdefault(key, [])
        removed = [w for w in words if w in lst]
        for w in removed:
            lst.remove(w)
        if removed:
            save_config()
        await reply_tidy(update, context,
                         (f"🗑 Убрал: {', '.join(removed)}" if removed else "Ничего из этого нет в списке.")
                         + f" ({label})")

    async def _show(update: Update, context):
        cfg, label = await _content_cfg(update, context)
        if cfg is None:
            return
        lst = cfg.get(key, [])
        await reply_tidy(update, context,
                         f"{title} ({label}), всего {len(lst)}:\n" + (", ".join(lst[:120]) or "— пусто —"),
                         seconds=30)

    return _add, _del, _show


cmd_addword, cmd_delword, cmd_words = _make_list_cmds("stop_words", "🚫 Стоп-слова", "addword")
cmd_addlink, cmd_dellink, cmd_links = _make_list_cmds("spam_links", "🔗 Спам-домены", "addlink")

# ───────────────────────────────────────────────────────────────────────────
#  ПРИЁМ ТЕКСТА/МЕДИА/ФАЙЛОВ В ЛИЧКЕ (режимы «awaiting» панели)
# ───────────────────────────────────────────────────────────────────────────

# Состояния, требующие права на ВЫБРАННУЮ группу
_TARGET_STATES = ("word", "word2", "wword", "link", "trigger", "trig_keys", "trig_content",
                  "trig_btns", "chphrase", "chreply", "gopword", "blid", "blname", "welcome",
                  "welcome_btns", "rules", "recurring", "rolenew", "rolemember", "staff", "gmgr")
# Состояния только для владельца/менеджеров бота
_MANAGER_STATES = ("gword", "gbid", "gbname", "invitetext", "promo_content", "promo_btns",
                   "bcast", "dmcast", "sp_time", "sp_content", "sp_btns", "mgr",
                   "shopitem", "shoptitle")


async def _state_allowed(update: Update, context) -> bool:
    awaiting = context.user_data.get("awaiting")
    user = update.effective_user
    if awaiting in _MANAGER_STATES and not is_manager(user.id):
        context.user_data.pop("awaiting", None)
        await update.effective_message.reply_text("Это действие доступно только владельцу бота.")
        return False
    if awaiting in _TARGET_STATES and not await can_edit_target(
            context, user.id, context.user_data.get("cfg_target")):
        context.user_data.pop("awaiting", None)
        await update.effective_message.reply_text("Сначала выбери свою группу: /panel")
        return False
    if awaiting == "gmgr" and not await can_assign_group_managers(
            context, int(context.user_data.get("cfg_target")), user.id):
        context.user_data.pop("awaiting", None)
        await update.effective_message.reply_text(
            "Назначать менеджеров может создатель группы или владелец бота.")
        return False
    return True


def _int_ids(text: str):
    return [int(x) for x in re.findall(r"-?\d{5,}", text or "")]


async def on_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    awaiting = context.user_data.get("awaiting")
    if not awaiting:
        return await msg.reply_text("Я на месте 🙌 Настройки — /panel, помощь — /help.")
    if not await _state_allowed(update, context):
        return
    text = (msg.text or "").strip()
    cfg = panel_cfg(context)
    label = panel_target_label(context)
    done = lambda: context.user_data.pop("awaiting", None)  # noqa: E731

    # ── списки слов/доменов ──
    list_states = {"word": ("stop_words", words_kb), "word2": ("stop_words2", words2_kb),
                   "wword": ("white_words", whitewords_kb), "link": ("spam_links", links_kb)}
    if awaiting in list_states:
        key, kb = list_states[awaiting]
        added = _add_unique(cfg.setdefault(key, []), _csv(text))
        if added:
            save_config()
        done()
        return await msg.reply_text(
            (f"✅ Добавлено: {', '.join(added)}" if added else "Всё это уже есть в списке.")
            + f" ({label})", reply_markup=kb(cfg))

    if awaiting == "trigger":
        m = re.match(r"(.+?)\s*[-—]\s*(.+)", text, re.S)
        if not m:
            return await msg.reply_text("Формат: ключ - ответ (или /cancel)")
        keys = [k.strip().lower() for k in m.group(1).split(",") if k.strip()]
        for k in keys:
            cfg.setdefault("triggers", {})[k] = m.group(2).strip()
        save_config()
        done()
        return await msg.reply_text(f"✅ Автоответ для: {', '.join(keys)} ({label})",
                                    reply_markup=triggers_kb(cfg))

    # ── мастер автоответа с медиа/кнопками ──
    if awaiting == "trig_keys":
        keys = _csv(text)
        if not keys:
            return await msg.reply_text("Пришли хотя бы один ключ (или /cancel)")
        context.user_data["trig_draft"] = {"keys": keys}
        context.user_data["awaiting"] = "trig_content"
        return await msg.reply_text("Шаг 2/3. Пришли контент ответа: текст или медиа с подписью "
                                    "(HTML и {рандомизация|вариантов} работают).")
    if awaiting == "trig_content":
        content = _capture_post_content(msg)
        if not content:
            return await msg.reply_text("Не понял контент — пришли текст или медиа (или /cancel)")
        context.user_data.setdefault("trig_draft", {})["content"] = content
        context.user_data["awaiting"] = "trig_btns"
        return await msg.reply_text("Шаг 3/3. Кнопки: «Текст - https://ссылка», по строке на ряд; "
                                    "несколько в ряд — через «;». Или /skip — без кнопок.")
    if awaiting == "trig_btns":
        if text.lower() in ("-", "—", "нет"):
            btns = []
        else:
            btns = _parse_button_rows(text)
            if btns is None:
                return await msg.reply_text("Не понял кнопки. Формат: Текст - https://ссылка (или /skip)")
        context.user_data.setdefault("trig_draft", {})["buttons"] = btns
        done()
        keys, val, wcfg = _save_trigger_draft(context)
        return await msg.reply_text(f"✅ Автоответ сохранён для: {', '.join(keys)}",
                                    reply_markup=triggers_kb(wcfg))

    # ── болталка: свои шутки и ответы ──
    if awaiting == "gopword":
        ch = cfg.setdefault("chatter", {})
        added = _add_unique(ch.setdefault("gop_words", []), _csv(text))
        if added:
            save_config()
        done()
        return await msg.reply_text(
            (f"🧢 Гоп-слов добавлено: {len(added)}." if added else "Всё это уже в списке.")
            + f" ({label})", reply_markup=chatter_kb(cfg))

    if awaiting in ("chphrase", "chreply"):
        ch = cfg.setdefault("chatter", {})
        lkey = "phrases" if awaiting == "chphrase" else "replies"
        items = [ln.strip() for ln in text.splitlines() if ln.strip()]
        added = _add_unique(ch.setdefault(lkey, []), items)
        if added:
            save_config()
        done()
        return await msg.reply_text(
            (f"✅ Добавлено фраз: {len(added)}." if added else "Всё это уже есть в списке.")
            + f" ({label})", reply_markup=chatter_kb(cfg))

    if awaiting == "blid":
        ids = _int_ids(text)
        if not ids:
            return await msg.reply_text("Не вижу ID. Пришли числа через запятую (или /cancel)")
        added = _add_unique(cfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("ids", []), ids)
        if added:
            save_config()
        done()
        return await msg.reply_text(f"⛔ В чёрном списке: +{len(added)} ID ({label})",
                                    reply_markup=blacklist_kb(cfg))
    if awaiting == "blname":
        names = [w for w in _csv(text)]
        added = _add_unique(cfg.setdefault("blacklist", {"ids": [], "names": []}).setdefault("names", []), names)
        if added:
            save_config()
        done()
        return await msg.reply_text(f"⛔ Подстрок имени добавлено: {len(added)} ({label})",
                                    reply_markup=blacklist_kb(cfg))

    if awaiting == "welcome":
        w = cfg.setdefault("welcome", {})
        w["text"] = text
        w["enabled"] = True
        save_config()
        done()
        return await msg.reply_text(f"👋 Приветствие сохранено и включено ({label})",
                                    reply_markup=welcome_kb(cfg))
    if awaiting == "welcome_btns":
        w = cfg.setdefault("welcome", {})
        if text.lower() in ("-", "—", "нет"):
            w["buttons"] = []
        else:
            btns = _parse_button_rows(text)
            if btns is None:
                return await msg.reply_text("Не понял кнопки. Формат: Текст - https://ссылка (или «-»)")
            w["buttons"] = btns
        save_config()
        done()
        return await msg.reply_text("🔘 Кнопки приветствия сохранены.", reply_markup=welcome_kb(cfg))

    if awaiting == "rules":
        cfg["rules"] = text
        save_config()
        done()
        return await msg.reply_text(f"📜 Правила сохранены ({label})", reply_markup=rules_kb(cfg))

    if awaiting == "recurring":
        m = re.match(r"(\d+)\s*\|\s*(.+)$", text, re.S)
        if not m:
            return await msg.reply_text("Формат: интервал_минут | текст (или /cancel)")
        cfg.setdefault("recurring", []).append(
            {"interval": max(1, int(m.group(1))), "text": m.group(2).strip(), "enabled": True})
        save_config()
        done()
        return await msg.reply_text("🔁 Авто-сообщение добавлено.", reply_markup=recurring_kb(cfg))

    if awaiting == "rolenew":
        name = text.split()[0][:20] if text else ""
        if not name or ":" in name:
            return await msg.reply_text("Название — одно слово без «:» (или /cancel)")
        cfg.setdefault("roles", {}).setdefault(name, {"perms": [], "members": []})
        save_config()
        done()
        return await msg.reply_text(
            f"🎖 Роль «{name}» создана. Отметь права и добавь участников:",
            reply_markup=role_detail_kb(cfg, name, context.user_data.get("cfg_target")))
    if awaiting == "rolemember":
        name = context.user_data.pop("role_name", None)
        r = cfg.setdefault("roles", {}).get(name or "")
        if r is None:
            done()
            return await msg.reply_text("Роль не найдена. Панель — /panel.")
        added = _add_unique(r.setdefault("members", []), _int_ids(text))
        if added:
            save_config()
        done()
        return await msg.reply_text(
            f"✅ В роль «{name}» добавлено: {len(added)}",
            reply_markup=role_detail_kb(cfg, name, context.user_data.get("cfg_target")))

    if awaiting == "gmgr":
        ids = [i for i in _int_ids(text) if i > 0]
        if not ids:
            return await msg.reply_text("Не вижу ID. Пришли числа через запятую (или /cancel)")
        added = _add_unique(cfg.setdefault("group_managers", []), ids)
        if added:
            save_config(force=True)
        done()
        tgt = context.user_data.get("cfg_target")
        title = CONFIG.get("groups", {}).get(str(tgt), str(tgt))
        for uid in added:
            try:
                await context.bot.send_message(
                    uid, f"👤 Тебя назначили менеджером группы «{title}». Настройки — /panel.")
            except Exception:  # noqa: BLE001
                pass
        return await msg.reply_text(f"👤 Менеджеров добавлено: {len(added)} ({label})",
                                    reply_markup=gmgr_kb(cfg, tgt))

    if awaiting == "staff":
        ids = _int_ids(text)
        if not ids:
            return await msg.reply_text("Пришли ID чата (отрицательное число), или /cancel")
        cfg["staff_group"] = ids[0]
        save_config()
        done()
        return await msg.reply_text("👔 Служебный чат сохранён.", reply_markup=staff_kb(cfg))

    if awaiting == "shopitem":
        parts = [p.strip() for p in text.split("|")]
        if len(parts) < 2 or not parts[1].isdigit() or not parts[0]:
            return await msg.reply_text("Формат: Название | звёзд | описание | выдача (или /cancel)")
        it = {"id": f"i{int(time.time() * 1000) % 10 ** 9}", "title": parts[0][:32],
              "stars": max(1, int(parts[1])), "desc": parts[2] if len(parts) > 2 else "",
              "deliver": parts[3] if len(parts) > 3 else "", "enabled": True}
        CONFIG.setdefault("shop", {}).setdefault("items", []).append(it)
        save_config(force=True)
        done()
        return await msg.reply_text(f"🛒 Товар «{it['title']}» за {it['stars']} ⭐ добавлен.",
                                    reply_markup=shop_kb())
    if awaiting == "shoptitle":
        CONFIG.setdefault("shop", {})["title"] = text[:40] or "Магазин"
        save_config(force=True)
        done()
        return await msg.reply_text("🛒 Название магазина сохранено.", reply_markup=shop_kb())

    if awaiting == "invitetext":
        CONFIG["invite_text"] = text
        save_config(force=True)
        done()
        return await msg.reply_text("📨 Текст «зазывалы» сохранён (общий для всех групп).")

    if awaiting == "mgr":
        if not is_owner(update.effective_user.id):
            done()
            return await msg.reply_text("Только главный владелец.")
        added = _add_unique(CONFIG.setdefault("managers", []), [i for i in _int_ids(text) if i > 0])
        save_config(force=True)
        done()
        return await msg.reply_text(f"🤝 Менеджеров добавлено: {len(added)}")

    # ── глобальные списки ──
    if awaiting == "gword":
        added = _add_unique(CONFIG.setdefault("global_stop_words", []), _csv(text))
        save_config(force=True)
        done()
        return await msg.reply_text(f"🌍 Глобальных стоп-слов добавлено: {len(added)}",
                                    reply_markup=global_kb())
    if awaiting in ("gbid", "gbname"):
        gb = CONFIG.setdefault("global_blacklist", {"ids": [], "names": []})
        if awaiting == "gbid":
            added = _add_unique(gb.setdefault("ids", []), _int_ids(text))
        else:
            added = _add_unique(gb.setdefault("names", []), _csv(text))
        save_config(force=True)
        done()
        return await msg.reply_text(f"🌍 В глобальный ЧС добавлено: {len(added)}",
                                    reply_markup=global_kb())

    # ── промо и рассылки ──
    if awaiting == "promo_content":
        content = _capture_post_content(msg)
        if not content:
            return await msg.reply_text("Пришли текст или медиа (или /cancel)")
        p = CONFIG["promo"]
        p.update({"type": content.get("type", "text"), "file_id": content.get("file_id"),
                  "text": content.get("text", ""), "html": bool(content.get("html"))})
        save_config(force=True)
        done()
        return await msg.reply_text("📣 Контент промо сохранён.", reply_markup=promo_kb())
    if awaiting == "promo_btns":
        if text.lower() in ("-", "—", "нет"):
            CONFIG["promo"]["buttons"] = []
        else:
            btns = _parse_button_rows(text)
            if btns is None:
                return await msg.reply_text("Не понял кнопки. Формат: Текст - https://ссылка (или «-»)")
            CONFIG["promo"]["buttons"] = btns
        save_config(force=True)
        done()
        return await msg.reply_text("🔘 Кнопки промо сохранены.", reply_markup=promo_kb())

    if awaiting == "bcast":
        post = _capture_post_content(msg)
        if not post:
            return await msg.reply_text("Пришли текст или медиа (или /cancel)")
        context.user_data["bcast_post"] = post
        context.user_data["pto_sel"] = {"all"}
        done()
        return await msg.reply_text("📤 Куда отправить пост?",
                                    reply_markup=post_groups_kb({"all"}, "pto"))
    if awaiting == "dmcast":
        post = _capture_post_content(msg)
        if not post:
            return await msg.reply_text("Пришли текст или медиа (или /cancel)")
        sel = context.user_data.pop("dmto_sel", set())
        done()
        chat_ids = (list(CONFIG.get("groups", {}).keys()) if "all" in sel
                    else [c for c in sel if c != "all"])
        await msg.reply_text(f"💬 Рассылаю подписчикам {len(chat_ids)} групп…")
        sent, fail = await _dm_broadcast(context, chat_ids, post)
        return await msg.reply_text(f"💬 Готово: отправлено {sent}, недоступно {fail}.")

    # ── мастер поста по расписанию ──
    if awaiting == "sp_time":
        m = re.match(r"([01]?\d|2[0-3]):([0-5]\d)\s*(.*)$", text)
        if not m:
            return await msg.reply_text("Формат: ЧЧ:ММ [пн,ср,пт] (или /cancel)")
        days = []
        rest = (m.group(3) or "").lower()
        for i, d in enumerate(_WEEKDAYS_RU):
            if d.lower() in rest:
                days.append(i)
        context.user_data["sp_draft"] = {"time": f"{int(m.group(1)):02d}:{m.group(2)}",
                                         "days": sorted(days)}
        context.user_data["awaiting"] = "sp_content"
        return await msg.reply_text("Шаг 2/3. Пришли контент поста: текст или медиа с подписью.")
    if awaiting == "sp_content":
        content = _capture_post_content(msg)
        if not content:
            return await msg.reply_text("Пришли текст или медиа (или /cancel)")
        context.user_data.setdefault("sp_draft", {})["content"] = content
        context.user_data["awaiting"] = "sp_btns"
        return await msg.reply_text("Шаг 3/3. Кнопки («Текст - https://ссылка») или /skip — без кнопок.")
    if awaiting == "sp_btns":
        if text.lower() in ("-", "—", "нет"):
            btns = []
        else:
            btns = _parse_button_rows(text)
            if btns is None:
                return await msg.reply_text("Не понял кнопки (или /skip)")
        context.user_data.setdefault("sp_draft", {})["buttons"] = btns
        done()
        post = _finalize_sched_post(context)
        return await msg.reply_text(f"✅ Пост создан: {post['time']} · {_post_groups_label(post)}",
                                    reply_markup=sched_kb())

    done()
    await msg.reply_text("Не разобрал. Панель — /panel.")


# Состояния, где ждём контент (медиа тоже подходит)
_CONTENT_STATES = ("trig_content", "promo_content", "bcast", "dmcast", "sp_content")


async def on_private_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get("awaiting") in _CONTENT_STATES:
        return await on_private_text(update, context)
    await update.effective_message.reply_text(
        "Медиа принимаю в мастерах панели (автоответ/промо/пост/рассылка). Панель — /panel.")


async def on_private_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if context.user_data.get("awaiting") in _CONTENT_STATES:
        return await on_private_text(update, context)
    doc = msg.document
    user = update.effective_user
    if not doc or not (doc.file_name or "").lower().endswith(".json"):
        return await msg.reply_text("Файлы принимаю только как JSON-бэкапы. Панель — /panel.")
    if doc.file_size and doc.file_size > 2 * 1024 * 1024:
        return await msg.reply_text("Файл слишком большой (лимит 2 МБ).")
    try:
        f = await context.bot.get_file(doc.file_id)
        raw = bytes(await f.download_as_bytearray())
        data = json.loads(raw.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        return await msg.reply_text(f"Не смог прочитать файл: {e}")
    if isinstance(data, dict) and data.get("_chat_backup"):
        tgt = context.user_data.get("cfg_target")
        if not await can_edit_target(context, user.id, tgt):
            return await msg.reply_text("Сначала выбери группу в /panel — к ней применю настройки.")
        apply_chat_settings(int(tgt), data)
        title = CONFIG.get("groups", {}).get(str(tgt), str(tgt))
        return await msg.reply_text(f"📂 Настройки из файла применены к «{title}».")
    if not is_owner(user.id):
        return await msg.reply_text("Полный бэкап может восстановить только главный владелец.")
    merged = _merge_defaults(data if isinstance(data, dict) else {})
    CONFIG.clear()
    CONFIG.update(merged)
    _load_soft_mutes()
    save_config(force=True)
    await msg.reply_text("🗄 Полный бэкап восстановлен. Перезапуск не требуется.")

# ───────────────────────────────────────────────────────────────────────────
#  ОШИБКИ, СТАРТ, РЕГИСТРАЦИЯ
# ───────────────────────────────────────────────────────────────────────────


# ───────────────────────────────────────────────────────────────────────────
#  МАГАЗИН MINI APP: веб-сервер, каталог, счета, выдача заказов
# ───────────────────────────────────────────────────────────────────────────

_shop_runner = None

SHOP_HTML = r"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Магазин</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--bg:var(--tg-theme-bg-color,#fff);--tx:var(--tg-theme-text-color,#111);
--hint:var(--tg-theme-hint-color,#888);--btn:var(--tg-theme-button-color,#2a8bf2);
--btx:var(--tg-theme-button-text-color,#fff);--card:var(--tg-theme-secondary-bg-color,#f2f3f5)}
*{box-sizing:border-box}
body{margin:0;padding:16px;background:var(--bg);color:var(--tx);
font:15px/1.45 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif}
h1{font-size:21px;margin:4px 0 2px}
.sub{color:var(--hint);font-size:13px;margin-bottom:16px}
.card{background:var(--card);border-radius:14px;padding:14px;margin-bottom:10px;
display:flex;gap:12px;align-items:center}
.i{flex:1;min-width:0}.t{font-weight:600}.d{color:var(--hint);font-size:13px;margin-top:2px}
button{border:0;border-radius:10px;padding:10px 14px;background:var(--btn);color:var(--btx);
font-weight:600;font-size:14px;white-space:nowrap;cursor:pointer}
button:disabled{opacity:.5}
.empty{color:var(--hint);text-align:center;padding:48px 10px}
</style></head><body>
<h1 id="title">🛒 Магазин</h1>
<div class="sub" id="sub">Оплата звёздами Telegram ⭐</div>
<div id="list"><div class="empty">Загрузка…</div></div>
<script>
const tg = window.Telegram && Telegram.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const q = new URLSearchParams(location.search);
const chat = (tg && tg.initDataUnsafe && tg.initDataUnsafe.start_param) || q.get("chat") || "";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
function say(t, cb) { if (tg && tg.showAlert) tg.showAlert(t, cb); else { alert(t); if (cb) cb(); } }
async function load() {
  const L = document.getElementById("list");
  try {
    const r = await fetch("api/catalog?chat=" + encodeURIComponent(chat));
    const j = await r.json();
    if (j.title) document.getElementById("title").textContent = "🛒 " + j.title;
    if (j.chat_title) document.getElementById("sub").textContent = "Группа: " + j.chat_title + " · оплата звёздами ⭐";
    if (!j.items || !j.items.length) { L.innerHTML = '<div class="empty">Пока пусто 🙂</div>'; return; }
    L.innerHTML = j.items.map(it =>
      `<div class="card"><div class="i"><div class="t">${esc(it.title)}</div>` +
      `<div class="d">${esc(it.desc)}</div></div>` +
      `<button data-id="${esc(it.id)}">${Number(it.stars)} ⭐</button></div>`).join("");
    L.querySelectorAll("button").forEach(b => b.onclick = () => buy(b));
  } catch (e) { L.innerHTML = '<div class="empty">Не удалось загрузить каталог</div>'; }
}
async function buy(b) {
  if (!tg || !tg.initData) { say("Открой магазин внутри Telegram"); return; }
  b.disabled = true;
  try {
    const r = await fetch("api/invoice", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({initData: tg.initData, item: b.dataset.id, chat})});
    const j = await r.json();
    if (!j.link) throw new Error(j.error || "ошибка");
    tg.openInvoice(j.link, st => {
      b.disabled = false;
      if (st === "paid") say("✅ Оплачено! Подробности — в чате с ботом.", () => tg.close());
    });
  } catch (e) { b.disabled = false; say("Не вышло создать счёт: " + e.message); }
}
load();
</script></body></html>"""


def _verify_init_data(init_data: str):
    """Проверка подписи Telegram.WebApp.initData. Возвращает dict пользователя или None."""
    try:
        d = dict(parse_qsl(init_data or "", keep_blank_values=True))
    except Exception:  # noqa: BLE001
        return None
    h = d.pop("hash", "")
    if not h or not BOT_TOKEN:
        return None
    check = "\n".join(f"{k}={v}" for k, v in sorted(d.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, h):
        return None
    try:
        if time.time() - int(d.get("auth_date", 0)) > 86400:
            return None
        user = json.loads(d.get("user") or "{}")
    except Exception:  # noqa: BLE001
        return None
    return user if isinstance(user, dict) and user.get("id") else None


def _shop_catalog(chat: str) -> list:
    """Каталог: тариф PRO (если открыт из известной группы) + свои товары."""
    s = CONFIG.get("shop") or {}
    if not s.get("enabled"):
        return []
    items = []
    if chat and str(chat) in CONFIG.get("groups", {}):
        title = CONFIG["groups"][str(chat)]
        for key, p in PRO_PLANS.items():
            items.append({"id": f"pro_{key}", "title": f"⭐ PRO · {p['title']}"[:32],
                          "desc": f"Полный доступ бота в «{title}» на {p['days']} дней",
                          "stars": int(p["stars"])})
    for it in s.get("items") or []:
        if isinstance(it, dict) and it.get("enabled", True) and it.get("id"):
            items.append({"id": it["id"], "title": str(it.get("title", ""))[:32],
                          "desc": str(it.get("desc", "")), "stars": int(it.get("stars", 1) or 1)})
    return items


async def _shop_index(request):
    return web.Response(text=SHOP_HTML, content_type="text/html")


async def _shop_api_catalog(request):
    chat = request.query.get("chat", "")
    s = CONFIG.get("shop") or {}
    return web.json_response({"title": s.get("title", "Магазин"),
                              "chat_title": CONFIG.get("groups", {}).get(str(chat), ""),
                              "items": _shop_catalog(chat)})


async def _shop_api_invoice(request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"error": "плохой запрос"}, status=400)
    user = _verify_init_data(str(body.get("initData") or ""))
    if not user:
        return web.json_response({"error": "нет доступа — открой магазин из Telegram"}, status=403)
    chat = str(body.get("chat") or "")
    item = next((i for i in _shop_catalog(chat) if i["id"] == str(body.get("item"))), None)
    if not item:
        return web.json_response({"error": "товар не найден"}, status=404)
    chat_part = chat if chat.lstrip("-").isdigit() else "0"
    try:
        link = await request.app["bot"].create_invoice_link(
            title=item["title"][:32],
            description=(item["desc"] or item["title"])[:255],
            payload=f"shop:{int(user['id'])}:{item['id']}:{chat_part}",
            provider_token="",  # Telegram Stars
            currency="XTR",
            prices=[LabeledPrice(label=item["title"][:32], amount=item["stars"])],
        )
    except Exception as e:  # noqa: BLE001
        log.warning("shop invoice: %s", e)
        return web.json_response({"error": "Telegram не создал счёт"}, status=502)
    return web.json_response({"link": link})


async def start_shop_server(app: Application):
    """Поднять веб-сервер магазина в том же event loop, что и бот."""
    global _shop_runner
    if not WEBAPP_URL:
        return
    if web is None:
        log.warning("Магазин: задан WEBAPP_URL, но нет aiohttp — pip install aiohttp")
        return
    try:
        wa = web.Application()
        wa["bot"] = app.bot
        wa.router.add_get("/", _shop_index)
        wa.router.add_get("/api/catalog", _shop_api_catalog)
        wa.router.add_post("/api/invoice", _shop_api_invoice)
        runner = web.AppRunner(wa)
        await runner.setup()
        await web.TCPSite(runner, SHOP_HOST, SHOP_PORT).start()
        _shop_runner = runner
        log.info("Магазин Mini App: http://%s:%s → %s", SHOP_HOST, SHOP_PORT, WEBAPP_URL)
    except Exception as e:  # noqa: BLE001
        log.warning("Магазин не запустился: %s", e)


async def stop_shop_server():
    global _shop_runner
    if _shop_runner is not None:
        try:
            await _shop_runner.cleanup()
        except Exception:  # noqa: BLE001
            pass
        _shop_runner = None


async def _send_shop_button(msg, chat_id=""):
    """Кнопка Mini App в ЛС (web_app-кнопки Telegram разрешает только в личке)."""
    if not WEBAPP_URL or not (CONFIG.get("shop") or {}).get("enabled"):
        return await msg.reply_text("🛒 Магазин пока закрыт.")
    url = WEBAPP_URL + "/" + (f"?chat={quote(str(chat_id))}" if chat_id else "")
    title = CONFIG.get("groups", {}).get(str(chat_id), "")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Открыть магазин", web_app=WebAppInfo(url=url))]])
    await msg.reply_text("🛒 Магазин" + (f" для «{title}»" if title else "") +
                         ": оплата звёздами Telegram прямо внутри 👇", reply_markup=kb)


async def cmd_shop(update: Update, context):
    chat = update.effective_chat
    if not WEBAPP_URL or not (CONFIG.get("shop") or {}).get("enabled"):
        return await reply_tidy(update, context, "🛒 Магазин пока закрыт.")
    if chat.type in ("group", "supergroup"):
        uname = _state.get("bot_username") or ""
        if SHOP_APP_NAME and uname:
            url = f"https://t.me/{uname}/{SHOP_APP_NAME}?startapp={chat.id}"
        else:
            url = f"https://t.me/{uname}?start=shop{chat.id}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🛒 Открыть магазин", url=url)]])
        return await reply_tidy(update, context,
                                "🛒 Магазин: тариф PRO для этой группы и товары за звёзды 👇",
                                seconds=60, reply_markup=kb)
    await _send_shop_button(update.effective_message, "")


async def _shop_paid(update, context, sp, parts):
    """Успешная оплата из магазина: запись заказа и выдача."""
    _, uid, item_id, chat = parts
    order = {"ts": time.time(), "uid": int(uid) if uid.isdigit() else uid, "item": item_id,
             "chat": chat, "stars": sp.total_amount,
             "charge": getattr(sp, "telegram_payment_charge_id", "")}
    orders = CONFIG.setdefault("shop_orders", [])
    orders.append(order)
    del orders[:-300]
    save_config(force=True)
    msg = update.effective_message
    buyer = mention(update.effective_user) if update.effective_user else uid
    if item_id.startswith("pro_") and chat.lstrip("-").isdigit() and chat != "0":
        p = PRO_PLANS.get(item_id[4:])
        if p:
            cid = int(chat)
            extend_pro(cid, p["days"])
            until = datetime.fromtimestamp(pro_until(cid)).strftime("%d.%m.%Y")
            title = CONFIG.get("groups", {}).get(chat, chat)
            try:
                await context.bot.send_message(cid, f"⭐ Тариф PRO активен до {until}. Спасибо, {buyer}!")
            except Exception:  # noqa: BLE001
                pass
            await msg.reply_text(f"✅ Оплата получена! PRO для «{title}» активен до {until}.")
            return await alert_owners(context, f"💰 Магазин: PRO {p['title']} для «{title}» — "
                                               f"{sp.total_amount} ⭐ от {buyer}.")
    it = next((i for i in (CONFIG.get("shop") or {}).get("items", []) if i.get("id") == item_id), {})
    deliver_text = it.get("deliver") or "С тобой скоро свяжутся. Спасибо!"
    await msg.reply_text(f"✅ Оплата получена: {it.get('title', item_id)}\n\n{deliver_text}")
    await alert_owners(context, f"💰 Магазин: «{it.get('title', item_id)}» — {sp.total_amount} ⭐ "
                                f"от {buyer} (id {uid}).")


async def on_error(update, context):
    err = context.error
    if isinstance(err, (NetworkError, TimedOut)):
        return
    if isinstance(err, RetryAfter):
        log.warning("Flood control: ждать %s сек", getattr(err, "retry_after", "?"))
        return
    log.error("Ошибка обработчика: %s", err, exc_info=err)


async def _post_init(app: Application):
    me = await app.bot.get_me()
    _state["bot_username"] = me.username
    _load_soft_mutes()
    _restore_pending(app)
    await start_shop_server(app)
    log.info("Запущен как @%s (id=%s)", me.username, me.id)
    try:
        await app.bot.set_my_commands([
            BotCommand("panel", "панель управления"),
            BotCommand("status", "сводка по группе"),
            BotCommand("add", "автоответ: ключ - ответ"),
            BotCommand("list", "список автоответов"),
            BotCommand("pro", "тариф и оплата"),
            BotCommand("shop", "магазин"),
            BotCommand("userid", "мой ID"),
            BotCommand("skip", "пропустить шаг"),
            BotCommand("cancel", "отменить ввод"),
            BotCommand("help", "помощь"),
            BotCommand("about", "о боте"),
        ], scope=BotCommandScopeAllPrivateChats())
        await app.bot.set_my_commands([
            BotCommand("rules", "правила группы"),
            BotCommand("report", "пожаловаться модераторам"),
            BotCommand("me", "моя карточка"),
            BotCommand("reg", "участвовать в призывах"),
            BotCommand("anreg", "не упоминать меня в /all"),
            BotCommand("top", "топ актива"),
            BotCommand("pro", "тариф для группы"),
            BotCommand("shop", "магазин"),
        ], scope=BotCommandScopeAllGroupChats())
        await app.bot.set_my_commands([
            BotCommand("ban", "бан (реплаем/ID, можно срок)"),
            BotCommand("unban", "разбан"),
            BotCommand("kick", "кикнуть"),
            BotCommand("mute", "мут (по админу — мягкий)"),
            BotCommand("unmute", "снять мут"),
            BotCommand("warn", "предупреждение"),
            BotCommand("unwarn", "снять предупреждение"),
            BotCommand("warns", "счётчик предов"),
            BotCommand("info", "карточка участника"),
            BotCommand("purge", "чистка (реплаем на начало)"),
            BotCommand("stats", "статистика группы"),
            BotCommand("top", "топ актива"),
            BotCommand("all", "призыв участников"),
            BotCommand("stopall", "остановить призыв"),
            BotCommand("invite", "ссылка-приглашение"),
            BotCommand("zazyvala", "сообщение «позови друзей»"),
            BotCommand("block", "в чёрный список"),
            BotCommand("unblock", "из чёрного списка"),
            BotCommand("role", "выдать роль (реплаем)"),
            BotCommand("unrole", "снять роль"),
            BotCommand("setstaff", "назначить служебный чат"),
            BotCommand("gmanager", "назначить менеджера группы"),
            BotCommand("ungmanager", "снять менеджера группы"),
            BotCommand("gmanagers", "менеджеры группы"),
            BotCommand("setrules", "изменить правила"),
            BotCommand("setwelcome", "текст приветствия"),
            BotCommand("add", "автоответ: ключ - ответ"),
            BotCommand("del", "удалить автоответ"),
            BotCommand("list", "список автоответов"),
            BotCommand("addword", "добавить стоп-слова"),
            BotCommand("delword", "убрать стоп-слова"),
            BotCommand("words", "список стоп-слов"),
            BotCommand("addlink", "добавить спам-домен"),
            BotCommand("dellink", "убрать спам-домен"),
            BotCommand("links", "список спам-доменов"),
            BotCommand("rules", "правила группы"),
            BotCommand("diag", "диагностика в чате"),
            BotCommand("settings", "где настройки"),
        ], scope=BotCommandScopeAllChatAdministrators())
    except Exception as e:  # noqa: BLE001
        log.debug("set_my_commands: %s", e)


def _restore_pending(app: Application):
    """После рестарта: вернуть ожидающие капчи/заявки и перевзвести их таймеры."""
    jq = app.job_queue
    now = time.time()
    pend = CONFIG.setdefault("pending", {})
    n = 0
    for kind, fn in (("captcha", captcha_timeout), ("jr", join_request_timeout)):
        store = pend.setdefault(kind, {})
        for k, v in list(store.items()):
            try:
                c, u = _split_pair(k)
                dl = float((v or {}).get("deadline", 0) or 0)
            except Exception:  # noqa: BLE001
                store.pop(k, None)
                continue
            if kind == "captcha":
                captcha_pending[(c, u)] = (v or {}).get("mid") or 0
            else:
                join_requests[(c, u)] = True
            if jq:
                jq.run_once(fn, max(1.0, dl - now), data={"chat_id": c, "uid": u})
            n += 1
    if n:
        log.info("Восстановлено ожиданий капчи/заявок: %s", n)


async def _post_shutdown(app: Application):
    await stop_shop_server()
    _flush_config()


def build_app() -> Application:
    app = (Application.builder()
           .token(BOT_TOKEN)
           .post_init(_post_init)
           .post_shutdown(_post_shutdown)
           .concurrent_updates(True)
           .build())

    # Группа -1: миграции и замок допуска — раньше всего остального
    app.add_handler(MessageHandler(filters.StatusUpdate.MIGRATE, on_migrate), group=-1)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, _gate_unapproved), group=-1)

    # Группа 0: команды
    for name, fn in (
        ("start", cmd_start), ("panel", cmd_panel), ("settings", cmd_settings_hint),
        ("status", cmd_status), ("help", cmd_help), ("about", cmd_about),
        ("cancel", cmd_cancel), ("skip", cmd_skip), ("userid", cmd_userid),
        ("add", cmd_add), ("del", cmd_del), ("list", cmd_list),
        ("addword", cmd_addword), ("delword", cmd_delword), ("words", cmd_words),
        ("addlink", cmd_addlink), ("dellink", cmd_dellink), ("links", cmd_links),
        ("ban", cmd_ban), ("unban", cmd_unban), ("kick", cmd_kick),
        ("mute", cmd_mute), ("unmute", cmd_unmute),
        ("warn", cmd_warn), ("unwarn", cmd_unwarn), ("warns", cmd_warns),
        ("info", cmd_info), ("purge", cmd_purge),
        ("role", cmd_role), ("unrole", cmd_unrole), ("setstaff", cmd_setstaff),
        ("rules", cmd_rules), ("setrules", cmd_setrules), ("setwelcome", cmd_setwelcome),
        ("report", cmd_report), ("me", cmd_me), ("appeal", cmd_appeal),
        ("stats", cmd_stats), ("top", cmd_top),
        ("invite", cmd_invite), ("link", cmd_link), ("zazyvala", cmd_zazyvala),
        ("all", cmd_all), ("stopall", cmd_stopall), ("reg", cmd_reg), ("anreg", cmd_anreg),
        ("block", cmd_block), ("unblock", cmd_unblock),
        ("gblock", cmd_gblock), ("gunblock", cmd_gunblock),
        ("say", cmd_say), ("diag", cmd_diag), ("reload", cmd_reload),
        ("pro", cmd_pro), ("grantpro", cmd_grantpro), ("broadcast", cmd_broadcast),
        ("grant", cmd_grant), ("revoke", cmd_revoke), ("managers", cmd_managers),
        ("gmanager", cmd_gmanager), ("shop", cmd_shop), ("ungmanager", cmd_ungmanager), ("gmanagers", cmd_gmanagers),
    ):
        app.add_handler(CommandHandler(name, fn))

    # Кнопки (специальные — раньше общего on_callback)
    app.add_handler(CallbackQueryHandler(handle_captcha_press, pattern=r"^cap:"))
    app.add_handler(CallbackQueryHandler(handle_join_request_press, pattern=r"^jrok:"))
    app.add_handler(CallbackQueryHandler(handle_setstaff_press, pattern=r"^ss:"))
    app.add_handler(CallbackQueryHandler(handle_action_press, pattern=r"^(act|arole):"))
    app.add_handler(CallbackQueryHandler(handle_buy_group_press, pattern=r"^buyg:"))
    app.add_handler(CallbackQueryHandler(handle_allstop_press, pattern=r"^allstop$"))
    app.add_handler(CallbackQueryHandler(on_callback))

    # Платежи, входы, членство
    app.add_handler(PreCheckoutQueryHandler(on_pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, on_successful_payment))
    app.add_handler(ChatJoinRequestHandler(on_join_request))
    app.add_handler(ChatMemberHandler(on_my_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(on_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.StatusUpdate.NEW_CHAT_MEMBERS,
                                   on_new_members))

    # Личка: тексты, медиа, файлы
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                                   on_private_text))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.PHOTO | filters.VIDEO | filters.ANIMATION
                                    | filters.Sticker.ALL | filters.VOICE | filters.VIDEO_NOTE
                                    | filters.AUDIO),
        on_private_media))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.Document.ALL,
                                   on_private_document))

    # Группа 1: единый конвейер сообщений группы
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & ~filters.COMMAND & ~filters.StatusUpdate.ALL,
        on_group_traffic), group=1)

    # Группа 2: уборка сервисных сообщений и команд
    app.add_handler(MessageHandler(
        filters.ChatType.GROUPS & (filters.StatusUpdate.NEW_CHAT_MEMBERS
                                   | filters.StatusUpdate.LEFT_CHAT_MEMBER),
        on_service_cleanup), group=2)
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.COMMAND,
                                   on_command_cleanup), group=2)

    app.add_error_handler(on_error)
    return app


def main():
    if not BOT_TOKEN:
        print("Не задан BOT_TOKEN. Пример запуска:\n"
              "  export BOT_TOKEN=123456:ABC...\n"
              "  python3 channel_guard_bot.py")
        sys.exit(1)
    app = build_app()
    jq = app.job_queue
    if jq:
        jq.run_repeating(minute_tick, interval=60, first=15)
        jq.run_repeating(flush_config_job, interval=90, first=30)
        jq.run_repeating(janitor_job, interval=3600, first=600)
        jq.run_repeating(maintenance_daily_job, interval=86400, first=120)
        jq.run_repeating(weekly_digest_job, interval=3600, first=900)
    log.info("Channel Guard v6 запускается…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
