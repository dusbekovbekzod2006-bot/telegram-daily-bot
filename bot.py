import logging
import json
import os
from datetime import datetime, timedelta
import pytz
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

TOKEN = os.environ.get("TOKEN", "")
TIMEZONE = "Asia/Tashkent"
WAITING_TASK = 1

GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def get_sheets_client():
    if not GOOGLE_CREDENTIALS_JSON:
        logger.warning("GOOGLE_CREDENTIALS not set")
        return None
    try:
        creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        return client
    except Exception as e:
        logger.error(f"Sheets client error: {e}")
        return None


def get_sheet():
    client = get_sheets_client()
    if not client or not SPREADSHEET_ID:
        return None
    try:
        return client.open_by_key(SPREADSHEET_ID).sheet1
    except Exception as e:
        logger.error(f"Get sheet error: {e}")
        return None


def sheet_add_task(user_id, username, task_text):
    try:
        sheet = get_sheet()
        if sheet is None:
            return False
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        sheet.append_row([str(user_id), username or "", task_text, now, "active", ""])
        return True
    except Exception as e:
        logger.error(f"sheet_add_task error: {e}")
        return False


def sheet_get_tasks(user_id):
    try:
        sheet = get_sheet()
        if sheet is None:
            return {}
        all_rows = sheet.get_all_records()
        tasks = {}
        for i, row in enumerate(all_rows):
            if str(row.get("User ID", "")) == str(user_id) and row.get("Status", "") == "active":
                task_key = str(i)
                tasks[task_key] = {
                    "task": row.get("Task", ""),
                    "date": row.get("Date Added", ""),
                    "row_index": i + 2
                }
        return tasks
    except Exception as e:
        logger.error(f"sheet_get_tasks error: {e}")
        return {}


def sheet_complete_task(user_id, row_index):
    try:
        sheet = get_sheet()
        if sheet is None:
            return False
        tz = pytz.timezone(TIMEZONE)
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        sheet.update_cell(row_index, 5, "done")
        sheet.update_cell(row_index, 6, now)
        return True
    except Exception as e:
        logger.error(f"sheet_complete_task error: {e}")
        return False


def sheet_delete_task(user_id, row_index):
    try:
        sheet = get_sheet()
        if sheet is None:
            return False
        sheet.delete_rows(row_index)
        return True
    except Exception as e:
        logger.error(f"sheet_delete_task error: {e}")
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Vazifalar ro'yxati", callback_data="list_tasks")],
        [InlineKeyboardButton("Yangi vazifa qo'shish", callback_data="add_task")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Salom! Men vazifalar botiman.\n\nNima qilishni xohlaysiz?",
        reply_markup=reply_markup
    )


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    tasks = sheet_get_tasks(user_id)
    if not tasks:
        keyboard = [[InlineKeyboardButton("Ortga", callback_data="back_main")]]
        await query.edit_message_text(
            "Hozircha vazifalar yo'q.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
    keyboard = []
    for key, task_info in tasks.items():
        task_text = task_info["task"]
        row_index = task_info["row_index"]
        short = task_text[:30] + "..." if len(task_text) > 30 else task_text
        keyboard.append([
            InlineKeyboardButton(f"✅ {short}", callback_data=f"done_{row_index}"),
            InlineKeyboardButton("🗑", callback_data=f"del_{row_index}")
        ])
    keyboard.append([InlineKeyboardButton("Ortga", callback_data="back_main")])
    msg = "Sizning vazifalaringiz:\n"
    for key, task_info in tasks.items():
        msg += f"- {task_info['task']} ({task_info['date']})\n"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))


async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Yangi vazifani yozing:")
    return WAITING_TASK


async def add_task_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_text = update.message.text.strip()
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name or ""
    success = sheet_add_task(user_id, username, task_text)
    if success:
        await update.message.reply_text(f"Vazifa qo'shildi: {task_text}")
    else:
        await update.message.reply_text("Xatolik yuz berdi. Iltimos qaytadan urinib ko'ring.")
    keyboard = [
        [InlineKeyboardButton("Vazifalar ro'yxati", callback_data="list_tasks")],
        [InlineKeyboardButton("Yangi vazifa qo'shish", callback_data="add_task")],
    ]
    await update.message.reply_text("Boshqa nima qilishni xohlaysiz?", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END


async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    row_index = int(query.data.split("_")[1])
    user_id = query.from_user.id
    success = sheet_complete_task(user_id, row_index)
    if success:
        await query.answer("Vazifa bajarildi!", show_alert=True)
    else:
        await query.answer("Xatolik!", show_alert=True)
    await list_tasks(update, context)


async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    row_index = int(query.data.split("_")[1])
    user_id = query.from_user.id
    success = sheet_delete_task(user_id, row_index)
    if success:
        await query.answer("Vazifa o'chirildi!", show_alert=True)
    else:
        await query.answer("Xatolik!", show_alert=True)
    await list_tasks(update, context)


async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    keyboard = [
        [InlineKeyboardButton("Vazifalar ro'yxati", callback_data="list_tasks")],
        [InlineKeyboardButton("Yangi vazifa qo'shish", callback_data="add_task")],
    ]
    await query.edit_message_text("Nima qilishni xohlaysiz?", reply_markup=InlineKeyboardMarkup(keyboard))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bekor qilindi.")
    return ConversationHandler.END


def main():
    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(add_task_start, pattern="^add_task$")],
        states={
            WAITING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_receive)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(list_tasks, pattern="^list_tasks$"))
    application.add_handler(CallbackQueryHandler(complete_task, pattern="^done_"))
    application.add_handler(CallbackQueryHandler(delete_task, pattern="^del_"))
    application.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))

    logger.info("Bot ishga tushdi...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
