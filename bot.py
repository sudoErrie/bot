import os
import logging
from datetime import datetime, time
from typing import Optional, Dict, Any

import pytz
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

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

# Хранилище chat_id
user_chats: Dict[int, Dict[str, Any]] = {}

# Сообщение для напоминания
REMINDER_MESSAGE = """
⏰ Напоминание: время укрепить предплечья!

1. Вис на перекладине
   3 подхода по 20-30 секунд
   Используйте обычный хват (ладони от себя)
   Постепенно увеличивайте время виса на 5 секунд каждую неделю

2. Подтягивания с паузой
   3 подхода по 5-8 повторений
   В верхней точке задержитесь на 2 секунды
   Опускайтесь плавно, контролируя движение
"""

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
                  username: Optional[str] = None, message: str = ""):
        """Запись события в Google Sheets"""
        if not self.service:
            logger.warning("Сервис Google Sheets не инициализирован")
            return

        try:
            # Текущее время
            tz = pytz.timezone(TIMEZONE)
            timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

            # Данные для записи
            values = [[
                timestamp,
                event_type,
                str(chat_id) if chat_id else "",
                username or "",
                message
            ]]

            body = {"values": values}

            # Добавляем запись
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range="Logs!A:E",
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()

            logger.info(f"✅ Событие записано в Google Sheets: {event_type}")

        except HttpError as e:
            logger.error(f"❌ Ошибка записи в Google Sheets: {e}")
        except Exception as e:
            logger.error(f"❌ Неизвестная ошибка: {e}")


# Создаем логгер
try:
    sheets_logger = GoogleSheetsLogger(CREDENTIALS_FILE, SPREADSHEET_ID)
except Exception as e:
    logger.error(f"Не удалось создать логгер Google Sheets: {e}")
    sheets_logger = None


# --- ОБРАБОТЧИКИ КОМАНД ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or "NoUsername"
    first_name = update.effective_user.first_name

    # Сохраняем пользователя
    user_chats[chat_id] = {
        "username": username,
        "first_name": first_name,
        "registered_at": datetime.now(pytz.timezone(TIMEZONE)).isoformat()
    }

    # Логируем
    if sheets_logger:
        sheets_logger.log_event(
            event_type="START",
            chat_id=chat_id,
            username=username,
            message=f"Пользователь {first_name} запустил бота"
        )

    # Отвечаем
    await update.message.reply_text(
        f"Привет, {first_name}! 👋\n\n"
        "Я буду напоминать тебе про упражнения для предплечий.\n"
        "📅 Расписание: ПН, СР, ПТ в 17:00\n"
        "✅ Ты успешно зарегистрирован!\n\n"
        "Команды:\n"
        "/start - показать это сообщение\n"
        "/status - проверить статус\n"
        "/test - получить тестовое напоминание"
    )

    # Запускаем расписание
    await schedule_reminders_for_user(context.application, chat_id)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка статуса"""
    chat_id = update.effective_chat.id

    if sheets_logger:
        sheets_logger.log_event(
            event_type="STATUS_CHECK",
            chat_id=chat_id,
            username=update.effective_user.username
        )

    if chat_id in user_chats:
        await update.message.reply_text(
            "✅ Ты в списке! Напоминания придут:\n"
            "📅 Понедельник, Среда, Пятница в 17:00"
        )
    else:
        await update.message.reply_text(
            "❌ Ты не зарегистрирован. Напиши /start"
        )


async def test_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая отправка"""
    chat_id = update.effective_chat.id

    if sheets_logger:
        sheets_logger.log_event(
            event_type="TEST_REMINDER",
            chat_id=chat_id,
            username=update.effective_user.username
        )

    await update.message.reply_text(REMINDER_MESSAGE)


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    """Отправка напоминания"""
    job = context.job
    chat_id = job.chat_id

    if chat_id not in user_chats:
        job.schedule_removal()
        return

    if sheets_logger:
        sheets_logger.log_event(
            event_type="REMINDER_SENT",
            chat_id=chat_id,
            username=user_chats[chat_id].get("username")
        )

    try:
        await context.bot.send_message(chat_id=chat_id, text=REMINDER_MESSAGE)
        logger.info(f"✅ Напоминание отправлено в чат {chat_id}")
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        if sheets_logger:
            sheets_logger.log_event(
                event_type="ERROR",
                chat_id=chat_id,
                message=f"Ошибка отправки: {str(e)}"
            )


async def schedule_reminders_for_user(application: Application, chat_id: int):
    """Настройка расписания"""
    # Удаляем старые задачи
    if application.job_queue:
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

    if sheets_logger:
        sheets_logger.log_event(
            event_type="SCHEDULE_SET",
            chat_id=chat_id,
            username=user_chats.get(chat_id, {}).get("username")
        )


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")

    if sheets_logger and update and update.effective_chat:
        sheets_logger.log_event(
            event_type="ERROR",
            chat_id=update.effective_chat.id,
            message=f"Ошибка: {str(context.error)}"
        )


# --- ОСНОВНАЯ ФУНКЦИЯ ---

def main():
    """Запуск бота"""
    if not BOT_TOKEN:
        logger.error("❌ Не указан BOT_TOKEN в .env файле")
        return

    if not SPREADSHEET_ID:
        logger.error("❌ Не указан SPREADSHEET_ID в .env файле")
        return

    # Создаем приложение
    application = Application.builder().token(BOT_TOKEN).build()

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("test", test_reminder))
    application.add_error_handler(error_handler)

    # Логируем запуск
    if sheets_logger:
        sheets_logger.log_event(
            event_type="BOT_START",
            message=f"Бот запущен"
        )

    logger.info("🚀 Бот запущен и готов к работе!")

    # Запускаем
    application.run_polling()


if __name__ == "__main__":
    main()