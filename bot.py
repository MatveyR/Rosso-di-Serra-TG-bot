import os
import json
import logging
from dotenv import load_dotenv
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
PROXY_URL = os.getenv("PROXY_URL")  # например, http://proxy.example.com:8080 или socks5://...

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

# ========== Состояния для ConversationHandler ==========
(
    ASK_NAME,
    ASK_CONFIRMATION,
) = range(2)


# ========== Клавиатуры ==========
def get_main_menu_keyboard():
    keyboard = [
        [texts["menu_location"]],
        [texts["menu_program"]],
        [texts["menu_dresscode"]],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_confirmation_keyboard():
    keyboard = [
        [texts["confirm_yes"]],
        [texts["confirm_no"]],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


# ========== Обработчики регистрации ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = str(update.effective_user.id)
    if user_id in users and users[user_id].get("registered"):
        await update.message.reply_text(
            texts["main_menu_title"],
            reply_markup=get_main_menu_keyboard()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            texts["welcome"],
            reply_markup=ReplyKeyboardRemove(),
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
            reply_markup=ReplyKeyboardRemove()
        )
        await update.message.reply_text(
            texts["main_menu_title"],
            reply_markup=get_main_menu_keyboard()
        )
        await send_notification(
            context.application,
            f"✅ Новый участник подтвердил участие!\n"
            f"ID: {user_id}\n"
            f"Имя: {full_name}"
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
            f"❌ Участник отказался от участия.\n"
            f"ID: {user_id}\n"
            f"Имя: {full_name}"
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
        await update.message.reply_text("Сначала зарегистрируйтесь через /start")
        return

    if text == texts["menu_location"]:
        location_text = texts["location_text"]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                texts["location_button"],
                url=texts["location_map_url"]
            )]
        ])
        await update.message.reply_text(
            location_text,
            reply_markup=keyboard,
            disable_web_page_preview=True
        )

    elif text == texts["menu_program"]:
        await update.message.reply_text(texts["program_text"])

    elif text == texts["menu_dresscode"]:
        await update.message.reply_text(texts["dresscode_text"])

    else:
        await update.message.reply_text("Используйте кнопки меню.")


# ========== Уведомления ==========
async def send_notification(application: Application, text: str):
    if NOTIFICATION_CHAT_ID:
        try:
            await application.bot.send_message(chat_id=NOTIFICATION_CHAT_ID, text=text)
            logger.info(f"Уведомление отправлено в чат {NOTIFICATION_CHAT_ID}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления в чат {NOTIFICATION_CHAT_ID}: {e}")


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
        ws.append([
            uid,
            user.get("full_name", ""),
            "Подтвердил" if user.get("registered") else "Отказался"
        ])

    for col in ws.columns:
        max_length = 0
        col_letter = col[0].column_letter
        for cell in col:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 40)
        ws.column_dimensions[col_letter].width = adjusted_width

    tmp_file = "export_users.xlsx"
    wb.save(tmp_file)

    with open(tmp_file, "rb") as f:
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=f,
            filename="участники.xlsx"
        )
    os.remove(tmp_file)


async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return
    users_data = load_users()
    registered = {k: v for k, v in users_data.items() if v.get("registered")}
    if not registered:
        await update.message.reply_text("Нет зарегистрированных пользователей.")
        return
    text = "📋 Список участников:\n\n"
    for uid, data in registered.items():
        name = data.get("full_name", "Без имени")
        text += f"ID: `{uid}` – {name}\n"
    await update.message.reply_text(text, parse_mode="Markdown")


async def edit_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("Недостаточно прав.")
        return
    args = context.args
    if len(args) < 3:
        await update.message.reply_text(
            "Использование: /edit_user <user_id> <field> <new_value>\n"
            "Поля: name, status (confirmed/declined)\n"
            "Пример: /edit_user 123456789 name Иван Петров"
        )
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
        await update.message.reply_text(f"Имя пользователя {user_id} обновлено.")
    elif field == "status":
        if new_value not in ["confirmed", "declined"]:
            await update.message.reply_text("Статус должен быть 'confirmed' или 'declined'.")
            return
        users_data[user_id]["registered"] = (new_value == "confirmed")
        save_users(users_data)
        await update.message.reply_text(f"Статус пользователя {user_id} обновлён.")
    else:
        await update.message.reply_text("Недопустимое поле. Допустимые: name, status")

    global users
    users = load_users()


# ========== Основная функция ==========
def main():
    builder = Application.builder().token(BOT_TOKEN)

    # Настройка прокси, если задан
    if PROXY_URL:
        logger.info(f"Используется прокси: {PROXY_URL}")
        builder = builder.proxy(PROXY_URL)
    else:
        logger.info("Прокси не задан, работаем напрямую.")

    application = builder.build()

    # Регистрационный диалог
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
            ASK_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_confirmation)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    # Обработчики главного меню (кнопки)
    application.add_handler(MessageHandler(
        filters.Regex(f"^({texts['menu_location']}|{texts['menu_program']}|{texts['menu_dresscode']})$"),
        handle_main_menu
    ))

    # Админские команды
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("export", export_users))
    application.add_handler(CommandHandler("list_users", list_users))
    application.add_handler(CommandHandler("edit_user", edit_user))

    # Запуск
    application.run_polling()


if __name__ == "__main__":
    main()