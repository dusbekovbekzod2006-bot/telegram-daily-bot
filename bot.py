import logging
import json
import os
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

TOKEN = os.environ.get("TOKEN", "")
DATA_FILE = "tasks.json"
TIMEZONE = "Asia/Tashkent"
WAITING_TASK = 1

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


def load_tasks():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_tasks(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_tasks(user_id):
    return load_tasks().get(str(user_id), [])


def save_user_tasks(user_id, tasks):
    data = load_tasks()
    data[str(user_id)] = tasks
    save_tasks(data)


def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ish qoshish", callback_data="add_task")],
        [InlineKeyboardButton("Ishlarim royxati", callback_data="list_tasks")],
        [InlineKeyboardButton("Bajarilganlar", callback_data="done_tasks")],
        [InlineKeyboardButton("Hammasini ochirish", callback_data="clear_tasks")],
        [InlineKeyboardButton("Yordam", callback_data="help")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Salom, {update.effective_user.first_name}!\nMen kundalik ishlar botingizman!\nMenyudan foydalaning:",
        reply_markup=main_menu_keyboard()
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Asosiy menyu:", reply_markup=main_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Buyruqlar:\n/start\n/menu\n/add - Ish qoshish\n/list - Royxat\n\nFormat: HH:MM Ish nomi\nMasalan: 09:00 Email"
    target = update.message or update.callback_query.message
    await target.reply_text(text)


async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "Yangi ish:\nHH:MM Ish nomi\nMasalan: 09:00 Email\n\n/cancel - bekor"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg)
    else:
        await update.message.reply_text(msg)
    return WAITING_TASK


async def receive_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"):
        await update.message.reply_text("Bekor qilindi. /menu")
        return ConversationHandler.END
    parts = text.split(" ", 1)
    if len(parts) < 2:
        await update.message.reply_text("Format: HH:MM Ish nomi")
        return WAITING_TASK
    time_str, task_name = parts
    try:
        hour, minute = map(int, time_str.split(":"))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except Exception:
        await update.message.reply_text("Vaqt notogri! Masalan: 09:00")
        return WAITING_TASK
    user_id = str(update.effective_user.id)
    tasks = get_user_tasks(user_id)
    task = {"id": len(tasks) + 1, "name": task_name, "time": f"{hour:02d}:{minute:02d}", "done": False}
    tasks.append(task)
    save_user_tasks(user_id, tasks)
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    remind_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if remind_time <= now:
        remind_time += timedelta(days=1)
    context.job_queue.run_daily(
        send_reminder,
        time=remind_time.timetz(),
        days=tuple(range(7)),
        chat_id=update.effective_chat.id,
        name=f"task_{user_id}_{task['id']}",
        data={"task_name": task_name, "task_id": task["id"], "user_id": user_id}
    )
    await update.message.reply_text(f"Qoshildi! {task_name} - {hour:02d}:{minute:02d}\n\n/menu")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bekor qilindi. /menu")
    return ConversationHandler.END


async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    data = job.data
    keyboard = [[
        InlineKeyboardButton("Bajardim", callback_data=f"mark_done_{data['task_id']}"),
        InlineKeyboardButton("30 daqiqadan keyin", callback_data=f"snooze_{data['task_id']}")
    ]]
    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"ESLATMA!\n\n{data['task_name']}\n\nVaqti keldi!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = str(update.effective_user.id)
    if query:
        await query.answer()
    tasks = get_user_tasks(user_id)
    if not tasks:
        text = "Ishlar yoq. /add"
    else:
        active = [t for t in tasks if not t.get("done")]
        done_list = [t for t in tasks if t.get("done")]
        text = "Ishlaringiz:\n"
        if active:
            text += "\nBajarilmagan:\n" + "".join(f"  {t['time']} - {t['name']}\n" for t in active)
        if done_list:
            text += "\nBajarilgan:\n" + "".join(f"  {t['time']} - {t['name']} v\n" for t in done_list)
        text += f"\nJami: {len(tasks)}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Ish qoshish", callback_data="add_task"),
        InlineKeyboardButton("Menyu", callback_data="back_main")
    ]])
    target = query.message if query else update.message
    await target.reply_text(text, reply_markup=kb)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = str(update.effective_user.id)
    if data == "add_task":
        await add_task_start(update, context)
    elif data == "list_tasks":
        await list_tasks(update, context)
    elif data == "done_tasks":
        tasks = get_user_tasks(user_id)
        done = [t for t in tasks if t.get("done")]
        text = "Bajarilgan:\n" + "".join(f"  {t['time']} - {t['name']}\n" for t in done) if done else "Hali yoq."
        await query.message.reply_text(text)
    elif data == "clear_tasks":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Ha, ochir", callback_data="confirm_clear"),
            InlineKeyboardButton("Yoq", callback_data="back_main")
        ]])
        await query.message.reply_text("Hammasini ochirsinmi?", reply_markup=kb)
    elif data == "confirm_clear":
        save_user_tasks(user_id, [])
        await query.message.reply_text("Ochirildi!", reply_markup=main_menu_keyboard())
    elif data == "help":
        await help_command(update, context)
    elif data == "back_main":
        await query.message.reply_text("Asosiy menyu:", reply_markup=main_menu_keyboard())
    elif data.startswith("mark_done_"):
        task_id = int(data.split("_")[-1])
        tasks = get_user_tasks(user_id)
        for t in tasks:
            if t["id"] == task_id:
                t["done"] = True
        save_user_tasks(user_id, tasks)
        await query.edit_message_text("Bajarildi!")
    elif data.startswith("snooze_"):
        task_id = int(data.split("_")[-1])
        tasks = get_user_tasks(user_id)
        task_name = next((t["name"] for t in tasks if t["id"] == task_id), "")
        context.job_queue.run_once(
            send_reminder, when=1800, chat_id=query.message.chat_id,
            data={"task_name": task_name, "task_id": task_id, "user_id": user_id}
        )
        await query.edit_message_text(f"30 daqiqadan keyin! {task_name}")


def main():
    if not TOKEN:
        logger.error("TOKEN topilmadi!")
        return
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("add", add_task_start),
            CallbackQueryHandler(add_task_start, pattern="^add_task$")
        ],
        states={WAITING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task)]},
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True,
        per_user=True,
        per_message=False
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
