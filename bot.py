import os
import json
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
import openpyxl
from openpyxl.styles import Font, Alignment

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

# ========== Загрузка конфигурации ==========
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]
NOTIFICATION_CHAT_ID = os.getenv("NOTIFICATION_CHAT_ID")
if NOTIFICATION_CHAT_ID:
    NOTIFICATION_CHAT_ID = int(NOTIFICATION_CHAT_ID)
USERS_FILE = os.getenv("USERS_FILE", "users.json")
TEXTS_FILE = os.getenv("TEXTS_FILE", "texts.json")
PROXY_URL = os.getenv("PROXY_URL")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== Загрузка текстов ==========
with open(TEXTS_FILE, "r", encoding="utf-8") as f:
    texts = json.load(f)

# ========== Работа с пользователями ==========
def load_users():
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

users = load_users()

# ========== Состояния ==========
ASK_NAME, ASK_CONFIRMATION = range(2)

# ========== Клавиатуры ==========
def get_main_menu_keyboard():
    return ReplyKeyboardMarkup([
        [texts["menu_location"]],
        [texts["menu_program"]],
        [texts["menu_dresscode"]],
    ], resize_keyboard=True)

def get_confirmation_keyboard():
    return ReplyKeyboardMarkup([
        [texts["confirm_yes"]],
        [texts["confirm_no"]],
    ], resize_keyboard=True)

# ========== Обработчики регистрации ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    user_data = users.get(user_id)

    # Если уже подтвердил – в меню
    if user_data and user_data.get("registered") is True:
        await update.message.reply_text(
            texts["main_menu_title"],
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END

    # В остальных случаях – регистрация
    await update.message.reply_text(
        texts["welcome"],
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
        disable_web_page_preview=True
    )
    await update.message.reply_text(texts["ask_name"])
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    full_name = update.message.text.strip()
    if not full_name:
        await update.message.reply_text("Пожалуйста, введите имя и фамилию.")
        return ASK_NAME
    context.user_data["full_name"] = full_name
    await update.message.reply_text(
        texts["confirm_prompt"],
        reply_markup=get_confirmation_keyboard()
    )
    return ASK_CONFIRMATION

async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    text = update.message.text
    full_name = context.user_data.get("full_name", "")

    if text == texts["confirm_yes"]:
        users[user_id] = {
            "full_name": full_name,
            "registered": True,
        }
        save_users(users)
        await update.message.reply_text(
            texts["confirm_thanks"],
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        await update.message.reply_text(
            texts["main_menu_title"],
            reply_markup=get_main_menu_keyboard()
        )
        await send_notification(
            context.application,
            f"✅ Участник подтвердил участие (или повторно)!\nID: {user_id}\nИмя: {full_name}"
        )
        return ConversationHandler.END

    elif text == texts["confirm_no"]:
        users[user_id] = {
            "full_name": full_name,
            "registered": False,
        }
        save_users(users)
        await update.message.reply_text(
            texts["confirm_declined"],
            reply_markup=ReplyKeyboardRemove()
        )
        await send_notification(
            context.application,
            f"❌ Участник отказался (или повторно).\nID: {user_id}\nИмя: {full_name}"
        )
        return ConversationHandler.END

    else:
        await update.message.reply_text("Пожалуйста, выберите одну из кнопок.")
        return ASK_CONFIRMATION

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    context.user_data.clear()
    return ConversationHandler.END

# ========== Главное меню ==========
async def handle_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = str(update.effective_user.id)
    user_data = users.get(user_id, {})

    if not user_data.get("registered"):
        await update.message.reply_text("Вы не зарегистрированы или отказались от участия.")
        return

    if text == texts["menu_location"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(texts["location_button"], url=texts["location_map_url"])]
        ])
        await update.message.reply_text(
            texts["location_text"],
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
    elif text == texts["menu_program"]:
        await update.message.reply_text(
            texts["program_text"],
            parse_mode="HTML"
        )
    elif text == texts["menu_dresscode"]:
        await update.message.reply_text(
            texts["dresscode_text"],
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("Используйте кнопки меню.")

# ========== Уведомления ==========
async def send_notification(application: Application, text: str):
    if NOTIFICATION_CHAT_ID:
        try:
            await application.bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=text)
        except Exception as e:
            logger.error(f"Ошибка уведомления: {e}")

# ========== Планировщик ==========
async def send_scheduled_message(application: Application, text_key: str, only_confirmed=True):
    users_data = load_users()
    for uid, data in users_data.items():
        if only_confirmed and not data.get("registered"):
            continue
        try:
            msg = texts[text_key]
            await application.bot.send_message(
                chat_id=int(uid),
                text=msg,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
        except Exception as e:
            logger.error(f"Ошибка отправки {uid}: {e}")

def schedule_jobs(application: Application):
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

    # 27 июля 18:30 – тест
    reminder_time = datetime(2026, 7, 30, 18, 30, tzinfo=timezone(timedelta(hours=3)))
    scheduler.add_job(
        send_scheduled_message,
        DateTrigger(run_date=reminder_time),
        args=[application, "reminder_text", True]
    )

    # 30 июля 11:00 – напоминалка (только confirmed)
    reminder_time = datetime(2026, 7, 30, 11, 0, tzinfo=timezone(timedelta(hours=3)))
    scheduler.add_job(
        send_scheduled_message,
        DateTrigger(run_date=reminder_time),
        args=[application, "reminder_text", True]
    )

    # 31 июля 10:00 – благодарность с фото (только confirmed)
    # thanks_time = datetime(2026, 7, 31, 10, 0, tzinfo=timezone(timedelta(hours=3)))
    # scheduler.add_job(
    #     send_scheduled_message,
    #     DateTrigger(run_date=thanks_time),
    #     args=[application, "final_thanks_text", True]
    # )

    return scheduler

async def post_init(application: Application):
    scheduler = schedule_jobs(application)
    application.bot_data["scheduler"] = scheduler
    scheduler.start()
    logger.info("Планировщик запущен.")

# ========== Админ-команды ==========
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return
    msg = " ".join(context.args)
    if not msg:
        await update.message.reply_text("Укажите текст рассылки после команды.")
        return
    users_data = load_users()
    count = 0
    for uid, data in users_data.items():
        if data.get("registered"):
            try:
                await context.bot.send_message(chat_id=int(uid), text=msg)
                count += 1
            except Exception as e:
                logger.error(f"Ошибка рассылки {uid}: {e}")
    await update.message.reply_text(f"Рассылка выполнена. Отправлено {count} пользователям.")

async def export_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return
    data = load_users()
    registered = {k: v for k, v in data.items() if v.get("registered")}
    if not registered:
        await update.message.reply_text("Нет зарегистрированных пользователей.")
        return

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Участники"
    headers = ["ID пользователя", "Имя", "Статус"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center")

    for uid, user in registered.items():
        ws.append([uid, user.get("full_name", ""), "Подтвердил"])
    for col in ws.columns:
        max_len = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_len:
                    max_len = len(str(cell.value))
            except:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 2, 40)

    tmp_file = "export_users.xlsx"
    wb.save(tmp_file)
    with open(tmp_file, "rb") as f:
        await context.bot.send_document(chat_id=update.effective_user.id, document=f, filename="участники.xlsx")
    os.remove(tmp_file)

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return
    users_data = load_users()
    confirmed = {k: v for k, v in users_data.items() if v.get("registered")}
    if not confirmed:
        await update.message.reply_text("Нет подтвердивших участников.")
        return
    text = "📋 Список участников:\n\n"
    for uid, data in confirmed.items():
        text += f"ID: `{uid}` – {data.get('full_name', 'Без имени')}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Использование: /edit_user <user_id> <field> <new_value>\nПоля: name, status (confirmed/declined)")
        return
    user_id = args[0]
    field = args[1].lower()
    new_value = " ".join(args[2:])

    users_data = load_users()
    if user_id not in users_data:
        await update.message.reply_text(f"Пользователь с ID {user_id} не найден.")
        return

    if field == "name":
        users_data[user_id]["full_name"] = new_value
        save_users(users_data)
        await update.message.reply_text(f"Имя обновлено.")
    elif field == "status":
        if new_value not in ["confirmed", "declined"]:
            await update.message.reply_text("Статус должен быть 'confirmed' или 'declined'.")
            return
        users_data[user_id]["registered"] = (new_value == "confirmed")
        save_users(users_data)
        await update.message.reply_text(f"Статус обновлён.")
    else:
        await update.message.reply_text("Недопустимое поле. Допустимые: name, status")
    global users
    users = load_users()

# ========== Основная функция ==========
def main():
    builder = Application.builder().token(BOT_TOKEN)
    if PROXY_URL:
        logger.info(f"Используется прокси: {PROXY_URL}")
        builder = builder.proxy(PROXY_URL)
    else:
        logger.info("Прокси не задан.")

    application = builder.post_init(post_init).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirmation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    application.add_handler(MessageHandler(
        filters.Regex(f"^({texts['menu_location']}|{texts['menu_program']}|{texts['menu_dresscode']})$"),
        handle_main_menu
    ))

    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("export", export_users))
    application.add_handler(CommandHandler("list_users", list_users))
    application.add_handler(CommandHandler("edit_user", edit_user))

    application.run_polling()

if __name__ == "__main__":
    main()