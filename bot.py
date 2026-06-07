import logging
import json
import os
from datetime import datetime
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

_sheet_obj = None

def get_sheet():
    global _sheet_obj
    try:
        if not GOOGLE_CREDENTIALS_JSON or not SPREADSHEET_ID:
            logger.warning("GOOGLE_CREDENTIALS or SPREADSHEET_ID not set")
            return None
        if _sheet_obj is None:
            creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
            client = gspread.authorize(creds)
            _sheet_obj = client.open_by_key(SPREADSHEET_ID).sheet1
        return _sheet_obj
    except Exception as e:
        logger.error(f"get_sheet error: {e}")
        _sheet_obj = None
        return None

def sheet_add_task(user_id, username, task_text):
    global _sheet_obj
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
        _sheet_obj = None
        return False

def sheet_get_tasks(user_id):
    global _sheet_obj
    try:
        sheet = get_sheet()
        if sheet is None:
            return {}
        all_rows = sheet.get_all_records()
        tasks = {}
        for i, row in enumerate(all_rows):
            if str(row.get("User ID", "")) == str(user_id) and row.get("Status", "") == "active":
                tasks[str(i)] = {
                    "task": row.get("Task", ""),
                    "date": row.get("Date Added", ""),
                    "row_index": i + 2
                }
        return tasks
    except Exception as e:
        logger.error(f"sheet_get_tasks error: {e}")
        _sheet_obj = None
        return {}

def sheet_complete_task(user_id, row_index):
    global _sheet_obj
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
        _sheet_obj = None
        return False

def sheet_delete_task(user_id, row_index):
    global _sheet_obj
    try:
        sheet = get_sheet()
        if sheet is None:
            return False
        sheet.delete_rows(row_index)
        return True
    except Exception as e:
        logger.error(f"sheet_delete_task error: {e}")
        _sheet_obj = None
        return False

async def show_menu_msg(message):
    keyboard = [
        [InlineKeyboardButton("Vazifalar ro'yxati", callback_data='list_tasks')],
        [InlineKeyboardButton("Yangi vazifa qo'shish", callback_data='add_task')],
    ]
    await message.reply_text("Nima qilishni xohlaysiz?", reply_markup=InlineKeyboardMarkup(keyboard))

async def show_menu_query(query):
    keyboard = [
        [InlineKeyboardButton("Vazifalar ro'yxati", callback_data='list_tasks')],
        [InlineKeyboardButton("Yangi vazifa qo'shish", callback_data='add_task')],
    ]
    await query.edit_message_text("Nima qilishni xohlaysiz?", reply_markup=InlineKeyboardMarkup(keyboard))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_menu_msg(update.message)

async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    tasks = sheet_get_tasks(user_id)
    if not tasks:
        keyboard = [[InlineKeyboardButton("Ortga", callback_data="back_main")]]
        await query.edit_message_text("Hozircha vazifalar yo'q.", reply_markup=InlineKeyboardMarkup(keyboard))
        return
    keyboard = []
    for key, task_info in tasks.items():
        task_text = task_info["task"]
        row_index = task_info["row_index"]
        short = task_text[:25] + "..." if len(task_text) > 25 else task_text
        keyboard.append([
            InlineKeyboardButton(f"Bajarildi: {short}", callback_data=f"done_{row_index}"),
            InlineKeyboardButton("O'chir", callback_data=f"del_{row_index}")
        ])
    keyboard.append([InlineKeyboardButton("Ortga", callback_data="back_main")])
    msg = "Sizning vazifalaringiz:\n"
    for key, task_info in tasks.items():
        msg += f"- {task_info['task']} ({task_info['date']})\n"
    await query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Yangi vazifani yozing (bekor qilish: /cancel):")
    return WAITING_TASK

async def add_task_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task_text = update.message.text.strip()
    user_id = update.message.from_user.id
    username = update.message.from_user.username or update.message.from_user.first_name or ""
    success = sheet_add_task(user_id, username, task_text)
    if success:
        await update.message.reply_text(f"Vazifa qo'shildi: {task_text}")
    else:
        await update.message.reply_text("Xatolik yuz berdi. Qaytadan urinib ko'ring.")
    await show_menu_msg(update.message)
    return ConversationHandler.END

async def complete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    row_index = int(query.data.split("_")[1])
    user_id = query.from_user.id
    success = sheet_complete_task(user_id, row_index)
    if success:
        await query.answer("Vazifa bajarildi!", show_alert=True)
    else:
        await query.answer("Xatolik!", show_alert=True)
    await show_menu_query(query)

async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    row_index = int(query.data.split("_")[1])
    user_id = query.from_user.id
    success = sheet_delete_task(user_id, row_index)
    if success:
        await query.answer("Vazifa o'chirildi!", show_alert=True)
    else:
        await query.answer("Xatolik!", show_alert=True)
    await show_menu_query(query)

async def back_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await show_menu_query(query)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bekor qilindi.")
    await show_menu_msg(update.message)
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

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(list_tasks, pattern="^list_tasks$"))
    application.add_handler(CallbackQueryHandler(complete_task, pattern="^done_"))
    application.add_handler(CallbackQueryHandler(delete_task, pattern="^del_"))
    application.add_handler(CallbackQueryHandler(back_main, pattern="^back_main$"))

    logger.info("Bot ishga tushdi...")
    application.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
