import os
import logging
import random
from datetime import datetime, time, timedelta
from typing import Optional, Dict, Any
import json
from collections import defaultdict

import pytz
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes,
    CallbackQueryHandler, MessageHandler, filters
)

# Google Sheets импорты
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Загружаем переменные окружения
load_dotenv()

# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
CREDENTIALS_FILE = "credentials.json"

# Хранилище данных пользователей
user_chats: Dict[int, Dict[str, Any]] = {}
user_stats: Dict[int, Dict[str, Any]] = defaultdict(lambda: {
    "workouts_done": 0,
    "total_hold_time": 0,
    "max_hold_time": 0,
    "pullups_done": 0,
    "current_streak": 0,
    "last_workout": None,
    "achievements": []
})

# --- ПРИКОЛЮХИ ---

# Мотивационные фразы
MOTIVATION_PHRASES = [
    "💪 Твои предплечья скажут тебе спасибо!",
    "🔥 Еще немного - и ты будешь крушить арбузы голыми руками!",
    "⚡ Каждая секунда виса делает тебя сильнее!",
    "🎯 Дисциплина - это то, что отличает чемпионов!",
    "🌟 Помни: даже Попай ел шпинат ради предплечий!",
    "🤝 Твои руки заслуживают этой заботы!",
    "⏱️ Время виса = время роста силы!",
    "🎸 Представь, как круто ты будешь играть на гитаре с такими предплечьями!",
    "💥 Прогресс не остановить!",
    "🏆 Сегодня ты лучше, чем вчера!"
]

# Смешные комментарии после тренировки
WORKOUT_COMMENTS = [
    "Отлично! Теперь можно и арбуз голыми руками раздавить! 🍉",
    "Молодец! Твои предплечья становятся сильнее с каждой тренировкой! 💪",
    "Супер! После таких тренировок рукопожатие будет железным! 🤝",
    "Класс! Осталось всего 666 тренировок до полного превосходства над миром! 😈",
    "Отличная работа! Гора мышц растет! 🏔️",
    "Так держать! Скоро сможешь подтягиваться на мизинцах! 🖕",
    "Здорово! Ты сегодня победил свою лень! 🏆",
    "Круто! Твои предплечья теперь как канаты! ⛓️"
]

# Достижения
ACHIEVEMENTS = {
    "first_workout": {"name": "Первые шаги", "desc": "Выполнил первую тренировку", "emoji": "🌱"},
    "streak_3": {"name": "В ритме", "desc": "3 тренировки подряд", "emoji": "📅"},
    "streak_10": {"name": "Неостановимый", "desc": "10 тренировок подряд", "emoji": "🔥"},
    "hold_60": {"name": "Железный хват", "desc": "Провис 60 секунд", "emoji": "⚡"},
    "workouts_10": {"name": "Ветеран", "desc": "10 тренировок всего", "emoji": "🎖️"},
    "workouts_50": {"name": "Мастер предплечий", "desc": "50 тренировок", "emoji": "👑"},
    "pullup_king": {"name": "Король подтягиваний", "desc": "Сделал 100 подтягиваний", "emoji": "🤴"}
}

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# --- КЛАСС ДЛЯ РАБОТЫ С GOOGLE SHEETS ---
class GoogleSheetsLogger:
    def __init__(self, credentials_file: str, spreadsheet_id: str):
        self.spreadsheet_id = spreadsheet_id
        self.service = None
        self._initialize_service(credentials_file)

    def _initialize_service(self, credentials_file: str):
        """Инициализация сервиса Google Sheets"""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_file,
                scopes=["https://www.googleapis.com/auth/spreadsheets"]
            )
            self.service = build("sheets", "v4", credentials=credentials)
            logger.info("✅ Подключение к Google Sheets установлено")
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к Google Sheets: {e}")

    def log_event(self, event_type: str, chat_id: Optional[int] = None,
                  username: Optional[str] = None, message: str = "",
                  additional_data: str = ""):
        """Запись события в Google Sheets"""
        if not self.service:
            return

        try:
            tz = pytz.timezone(TIMEZONE)
            timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

            values = [[
                timestamp,
                event_type,
                str(chat_id) if chat_id else "",
                username or "",
                message,
                additional_data
            ]]

            body = {"values": values}

            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="Logs!A:F",  # Добавили колонку F для дополнительных данных
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()

        except Exception as e:
            logger.error(f"❌ Ошибка записи в Google Sheets: {e}")


# Создаем логгер
try:
    sheets_logger = GoogleSheetsLogger(CREDENTIALS_FILE, SPREADSHEET_ID)
except Exception as e:
    logger.error(f"Не удалось создать логгер Google Sheets: {e}")
    sheets_logger = None


# --- ФУНКЦИИ ДЛЯ РАБОТЫ С ДОСТИЖЕНИЯМИ ---

def check_achievements(chat_id: int, workout_data: dict):
    """Проверка и выдача достижений"""
    stats = user_stats[chat_id]
    new_achievements = []

    # Первая тренировка
    if stats["workouts_done"] == 1 and "first_workout" not in stats["achievements"]:
        stats["achievements"].append("first_workout")
        new_achievements.append(ACHIEVEMENTS["first_workout"])

    # Серии тренировок
    if stats["current_streak"] >= 3 and "streak_3" not in stats["achievements"]:
        stats["achievements"].append("streak_3")
        new_achievements.append(ACHIEVEMENTS["streak_3"])

    if stats["current_streak"] >= 10 and "streak_10" not in stats["achievements"]:
        stats["achievements"].append("streak_10")
        new_achievements.append(ACHIEVEMENTS["streak_10"])

    # Общее количество тренировок
    if stats["workouts_done"] >= 10 and "workouts_10" not in stats["achievements"]:
        stats["achievements"].append("workouts_10")
        new_achievements.append(ACHIEVEMENTS["workouts_10"])

    if stats["workouts_done"] >= 50 and "workouts_50" not in stats["achievements"]:
        stats["achievements"].append("workouts_50")
        new_achievements.append(ACHIEVEMENTS["workouts_50"])

    # Время виса
    if stats["max_hold_time"] >= 60 and "hold_60" not in stats["achievements"]:
        stats["achievements"].append("hold_60")
        new_achievements.append(ACHIEVEMENTS["hold_60"])

    # Подтягивания
    if stats["pullups_done"] >= 100 and "pullup_king" not in stats["achievements"]:
        stats["achievements"].append("pullup_king")
        new_achievements.append(ACHIEVEMENTS["pullup_king"])

    return new_achievements


# --- ОБРАБОТЧИКИ КОМАНД ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start с красивым меню"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or "NoUsername"
    first_name = update.effective_user.first_name

    # Сохраняем пользователя
    user_chats[chat_id] = {
        "username": username,
        "first_name": first_name,
        "registered_at": datetime.now(pytz.timezone(TIMEZONE)).isoformat()
    }

    # Создаем красивое меню с кнопками
    keyboard = [
        [
            InlineKeyboardButton("📋 Сегодняшняя тренировка", callback_data="workout_today"),
            InlineKeyboardButton("📊 Моя статистика", callback_data="stats")
        ],
        [
            InlineKeyboardButton("🏆 Достижения", callback_data="achievements"),
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        ],
        [
            InlineKeyboardButton("🎲 Случайный факт", callback_data="random_fact"),
            InlineKeyboardButton("📝 Отметить тренировку", callback_data="log_workout")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Приветственное сообщение
    welcome_text = (
        f"🌟 Привет, {first_name}! 🌟\n\n"
        "Я твой персональный тренер по предплечьям! 🤵\n"
        "Буду напоминать о тренировках и следить за прогрессом.\n\n"
        "📅 Расписание: ПН, СР, ПТ в 17:00\n\n"
        "👇 Выбери, что хочешь сделать:"
    )

    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

    if sheets_logger:
        sheets_logger.log_event(
            event_type="START",
            chat_id=chat_id,
            username=username,
            message=f"Пользователь {first_name} запустил бота"
        )

    # Запускаем расписание
    await schedule_reminders_for_user(context.application, chat_id)


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на кнопки"""
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    callback_data = query.data

    if callback_data == "workout_today":
        await show_todays_workout(query, chat_id)
    elif callback_data == "stats":
        await show_stats(query, chat_id)
    elif callback_data == "achievements":
        await show_achievements(query, chat_id)
    elif callback_data == "help":
        await show_help(query)
    elif callback_data == "random_fact":
        await send_random_fact(query)
    elif callback_data == "log_workout":
        await ask_workout_details(query, context, chat_id)
    elif callback_data.startswith("log_"):
        await process_workout_log(query, context, chat_id, callback_data)


async def show_todays_workout(query, chat_id):
    """Показать тренировку на сегодня"""
    # Случайная мотивация
    motivation = random.choice(MOTIVATION_PHRASES)

    workout_text = (
        f"{motivation}\n\n"
        "📋 **Сегодняшняя программа:**\n\n"
        "1️⃣ **Вис на перекладине**\n"
        "   3 подхода по 20-30 секунд\n"
        "   Хват: ладони от себя\n\n"
        "2️⃣ **Подтягивания с паузой**\n"
        "   3 подхода по 5-8 повторений\n"
        "   Пауза в верхней точке 2 секунды\n\n"
        "💡 **Совет дня:** Дыши ровно и концентрируйся на мышцах!"
    )

    # Кнопка "Я сделал это!"
    keyboard = [[InlineKeyboardButton("✅ Я выполнил тренировку!", callback_data="log_workout")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        workout_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_stats(query, chat_id):
    """Показать статистику пользователя"""
    stats = user_stats[chat_id]

    # Прогресс-бар (просто для красоты)
    progress = min(stats["workouts_done"] / 10, 1.0)
    progress_bar = "█" * int(progress * 10) + "░" * (10 - int(progress * 10))

    stats_text = (
        "📊 **Твоя статистика**\n\n"
        f"🏋️ Всего тренировок: **{stats['workouts_done']}**\n"
        f"📈 Прогресс: [{progress_bar}] {int(progress * 100)}%\n"
        f"⏱️ Общее время виса: **{stats['total_hold_time']}** сек\n"
        f"🎯 Рекорд виса: **{stats['max_hold_time']}** сек\n"
        f"🤸 Подтягиваний всего: **{stats['pullups_done']}**\n"
        f"🔥 Текущая серия: **{stats['current_streak']}** тренировок\n"
        f"🏆 Достижений: **{len(stats['achievements'])}**\n"
    )

    if stats["last_workout"]:
        last = datetime.fromisoformat(stats["last_workout"])
        now = datetime.now(pytz.timezone(TIMEZONE))
        days_ago = (now - last).days
        stats_text += f"📅 Последняя тренировка: **{days_ago}** дн. назад"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        stats_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_achievements(query, chat_id):
    """Показать достижения"""
    stats = user_stats[chat_id]
    achievements = stats["achievements"]

    text = "🏆 **Твои достижения**\n\n"

    if not achievements:
        text += "Пока нет достижений. Выполни первую тренировку! 🌱"
    else:
        for ach in achievements:
            if ach in ACHIEVEMENTS:
                a = ACHIEVEMENTS[ach]
                text += f"{a['emoji']} **{a['name']}** - {a['desc']}\n"

        # Показать недостигнутые (серым)
        text += "\n🔒 **Еще можно получить:**\n"
        for ach_id, ach in ACHIEVEMENTS.items():
            if ach_id not in achievements:
                text += f"⚪ {ach['name']} - {ach['desc']}\n"

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')


async def show_help(query):
    """Показать помощь"""
    help_text = (
        "❓ **Как пользоваться ботом**\n\n"
        "🤖 **Команды:**\n"
        "/start - Главное меню\n"
        "/workout - Тренировка на сегодня\n"
        "/stats - Моя статистика\n"
        "/achievements - Достижения\n"
        "/fact - Случайный факт\n"
        "/log - Отметить тренировку\n\n"
        "📅 Напоминания приходят в ПН, СР, ПТ в 17:00\n\n"
        "💪 **Совет:** После тренировки отмечай её в боте,\n"
        "чтобы копились достижения и статистика!"
    )

    keyboard = [[InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(help_text, reply_markup=reply_markup, parse_mode='Markdown')


async def send_random_fact(query):
    """Отправить случайный факт о предплечьях"""
    facts = [
        "Знаешь ли ты, что сила хвата напрямую связана с долголетием? 🧬",
        "Предплечья состоят из 20 мышц! Это целая мышцефабрика! 🏭",
        "Рекорд виса на перекладине - 1 час 5 минут! 😱",
        "Сильные предплечья помогают играть на музыкальных инструментах 🎸",
        "У альпинистов самые сильные предплечья в мире 🧗",
        "Каждый день наши руки совершают тысячи хватательных движений ✋",
        "Мышцы предплечий восстанавливаются быстрее, чем бицепс или трицепс ⚡",
        "Сильный хват привлекает противоположный пол (научно доказано!) 💘"
    ]

    fact = random.choice(facts)

    keyboard = [
        [
            InlineKeyboardButton("🎲 Еще факт", callback_data="random_fact"),
            InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(f"🧠 **Факт дня:**\n\n{fact}",
                                  reply_markup=reply_markup,
                                  parse_mode='Markdown')


async def ask_workout_details(query, context, chat_id):
    """Спросить детали тренировки"""
    keyboard = [
        [
            InlineKeyboardButton("20-30 сек", callback_data="log_hold_25"),
            InlineKeyboardButton("30-40 сек", callback_data="log_hold_35"),
            InlineKeyboardButton("40+ сек", callback_data="log_hold_45")
        ],
        [
            InlineKeyboardButton("5-6 подтягиваний", callback_data="log_pull_5"),
            InlineKeyboardButton("7-8 подтягиваний", callback_data="log_pull_7"),
            InlineKeyboardButton("9+ подтягиваний", callback_data="log_pull_9")
        ],
        [
            InlineKeyboardButton("✅ Отметить без деталей", callback_data="log_simple"),
            InlineKeyboardButton("🔙 Отмена", callback_data="back_to_menu")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📝 **Отметить тренировку**\n\n"
        "Выбери свои результаты сегодня:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def process_workout_log(query, context, chat_id, callback_data):
    """Обработка отметки о тренировке"""
    stats = user_stats[chat_id]

    # Парсим данные
    hold_time = 25  # среднее по умолчанию
    pullups = 6  # среднее по умолчанию

    if callback_data == "log_hold_25":
        hold_time = 25
    elif callback_data == "log_hold_35":
        hold_time = 35
    elif callback_data == "log_hold_45":
        hold_time = 45
    elif callback_data == "log_pull_5":
        pullups = 5
    elif callback_data == "log_pull_7":
        pullups = 7
    elif callback_data == "log_pull_9":
        pullups = 9
    elif callback_data == "log_simple":
        hold_time = 25
        pullups = 6

    # Обновляем статистику
    stats["workouts_done"] += 1
    stats["total_hold_time"] += hold_time * 3  # 3 подхода
    stats["max_hold_time"] = max(stats["max_hold_time"], hold_time)
    stats["pullups_done"] += pullups * 3  # 3 подхода
    stats["last_workout"] = datetime.now(pytz.timezone(TIMEZONE)).isoformat()

    # Обновляем серию
    if stats["last_workout"]:
        last = datetime.fromisoformat(stats["last_workout"])
        now = datetime.now(pytz.timezone(TIMEZONE))
        if (now - last).days <= 2:  # Если прошло не больше 2 дней
            stats["current_streak"] += 1
        else:
            stats["current_streak"] = 1
    else:
        stats["current_streak"] = 1

    # Проверяем достижения
    new_achievements = check_achievements(chat_id, {"hold": hold_time, "pullups": pullups})

    # Формируем ответ
    comment = random.choice(WORKOUT_COMMENTS)
    response = f"✅ Тренировка отмечена!\n\n{comment}\n\n"

    if new_achievements:
        response += "🎉 **Новые достижения:**\n"
        for ach in new_achievements:
            response += f"{ach['emoji']} {ach['name']}: {ach['desc']}\n"

    # Показываем обновленную статистику
    response += f"\n📊 **Текущая статистика:**\n"
    response += f"Всего тренировок: {stats['workouts_done']}\n"
    response += f"Серия: {stats['current_streak']} 🔥"

    keyboard = [[InlineKeyboardButton("🔙 В меню", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        response,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

    # Логируем
    if sheets_logger:
        sheets_logger.log_event(
            event_type="WORKOUT_COMPLETED",
            chat_id=chat_id,
            username=user_chats.get(chat_id, {}).get("username"),
            message=f"Тренировка #{stats['workouts_done']}",
            additional_data=f"hold:{hold_time},pullups:{pullups}"
        )


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вернуться в главное меню"""
    query = update.callback_query
    await query.answer()

    chat_id = update.effective_chat.id
    first_name = user_chats.get(chat_id, {}).get("first_name", "друг")

    keyboard = [
        [
            InlineKeyboardButton("📋 Сегодняшняя тренировка", callback_data="workout_today"),
            InlineKeyboardButton("📊 Моя статистика", callback_data="stats")
        ],
        [
            InlineKeyboardButton("🏆 Достижения", callback_data="achievements"),
            InlineKeyboardButton("❓ Помощь", callback_data="help")
        ],
        [
            InlineKeyboardButton("🎲 Случайный факт", callback_data="random_fact"),
            InlineKeyboardButton("📝 Отметить тренировку", callback_data="log_workout")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"🌟 Главное меню, {first_name}! 🌟\n\nЧто хочешь сделать?",
        reply_markup=reply_markup
    )


async def workout_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /workout"""
    motivation = random.choice(MOTIVATION_PHRASES)

    workout_text = (
        f"{motivation}\n\n"
        "📋 **Сегодняшняя программа:**\n\n"
        "1️⃣ **Вис на перекладине**\n"
        "   3 подхода по 20-30 секунд\n\n"
        "2️⃣ **Подтягивания с паузой**\n"
        "   3 подхода по 5-8 повторений\n\n"
        "💪 У тебя получится!"
    )

    await update.message.reply_text(workout_text, parse_mode='Markdown')


async def fact_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /fact"""
    facts = [
        "Знаешь ли ты, что сила хвата напрямую связана с долголетием? 🧬",
        "Предплечья состоят из 20 мышц! Это целая мышцефабрика! 🏭",
        "Рекорд виса на перекладине - 1 час 5 минут! 😱",
        "Сильные предплечья помогают играть на музыкальных инструментах 🎸"
    ]

    await update.message.reply_text(f"🧠 {random.choice(facts)}")


# --- ОСТАЛЬНЫЕ ФУНКЦИИ (send_reminder, schedule_reminders_for_user, error_handler, main) ---
# ... (оставляем как в предыдущей версии)

async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Отправка напоминания с кнопками"""
    job = context.job
    chat_id = job.chat_id

    if chat_id not in user_chats:
        job.schedule_removal()
        return

    motivation = random.choice(MOTIVATION_PHRASES)

    keyboard = [
        [InlineKeyboardButton("✅ Отметить тренировку", callback_data="log_workout")],
        [InlineKeyboardButton("📋 Показать тренировку", callback_data="workout_today")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    reminder_text = (
        f"⏰ **Время тренировки!**\n\n"
        f"{motivation}\n\n"
        f"Не забывай про предплечья! 💪"
    )

    try:
        await context.bot.send_message(
            chat_id=chat_id,
            text=reminder_text,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        logger.info(f"✅ Напоминание отправлено в чат {chat_id}")

        if sheets_logger:
            sheets_logger.log_event(
                event_type="REMINDER_SENT",
                chat_id=chat_id,
                username=user_chats[chat_id].get("username")
            )
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")


async def schedule_reminders_for_user(application: Application, chat_id: int):
    """Настройка расписания"""
    if not application.job_queue:
        logger.error(f"❌ job_queue не инициализирован для чата {chat_id}")
        return

    # Удаляем старые задачи
    current_jobs = application.job_queue.jobs()
    for job in current_jobs:
        if job.chat_id == chat_id and job.name == "forearm_reminder":
            job.schedule_removal()

    # Дни недели: ПН=0, СР=2, ПТ=4
    target_days = [0, 2, 4]
    reminder_time = time(hour=17, minute=0, tzinfo=pytz.timezone(TIMEZONE))

    for day in target_days:
        application.job_queue.run_daily(
            send_reminder,
            time=reminder_time,
            days=(day,),
            chat_id=chat_id,
            name="forearm_reminder"
        )

    logger.info(f"✅ Запланированы напоминания для чата {chat_id}")


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")

    if sheets_logger and update and update.effective_chat:
        sheets_logger.log_event(
            event_type="ERROR",
            chat_id=update.effective_chat.id,
            message=f"Ошибка: {str(context.error)}"
        )


def main():
    """Запуск бота"""
    if not BOT_TOKEN:
        logger.error("❌ Не указан BOT_TOKEN в .env файле")
        return

    # Создаем приложение
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .job_queue()
        .build()
    )

    # Добавляем обработчики команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("workout", workout_command))
    application.add_handler(CommandHandler("fact", fact_command))

    # Добавляем обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_callback))

    # Добавляем обработчик ошибок
    application.add_error_handler(error_handler)

    # Логируем запуск
    if sheets_logger:
        sheets_logger.log_event(
            event_type="BOT_START",
            message=f"Бот запущен"
        )

    logger.info("🚀 Бот с приколюхами запущен и готов к работе!")

    # Запускаем
    application.run_polling()


if __name__ == "__main__":
    main()