import logging, json, os
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

TOKEN = os.environ.get("TOKEN", "8950501361:AAHmhXzxBoWQ1Mpo9184btwPYQRi2sAQeK0")
DATA_FILE = "tasks.json"
TIMEZONE = "Asia/Tashkent"
WAITING_TASK = 1
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)


def load_tasks():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_tasks(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_tasks(uid):
    return load_tasks().get(uid, [])


def save_user_tasks(uid, tasks):
    d = load_tasks()
    d[uid] = tasks
    save_tasks(d)


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Ish qoshish", callback_data="add")],
        [InlineKeyboardButton("Ishlarim royxati", callback_data="list")],
        [InlineKeyboardButton("Bajarilganlar", callback_data="done")],
        [InlineKeyboardButton("Hammasini ochirish", callback_data="clear")],
        [InlineKeyboardButton("Yordam", callback_data="help")],
    ])


async def start(update, context):
    await update.message.reply_text(
        f"Salom, {update.effective_user.first_name}!\nMen kundalik ishlar botingizman!\nMenyudan foydalaning:",
        reply_markup=main_menu()
    )


async def menu(update, context):
    await update.message.reply_text("Asosiy menyu:", reply_markup=main_menu())


async def help_cmd(update, context):
    text = "Buyruqlar:\n/start\n/menu\n/add - Ish qoshish\n/list - Royxat\n\nFormat: HH:MM Ish nomi\nMasalan: 09:00 Email tekshirish"
    t = update.message or update.callback_query.message
    await t.reply_text(text)


async def add_start(update, context):
    msg = "Yangi ish qoshish\n\nFormatda yozing: HH:MM Ish nomi\nMasalan: 09:00 Email tekshirish\n\nBekor qilish: /cancel"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(msg)
    else:
        await update.message.reply_text(msg)
    return WAITING_TASK


async def receive_task(update, context):
    text = update.message.text.strip()
    if text.startswith("/"):
        await update.message.reply_text("Bekor qilindi.")
        return ConversationHandler.END
    parts = text.split(" ", 1)
    if len(parts) < 2:
        await update.message.reply_text("Format notogri! HH:MM Ish nomi formatida yozing.")
        return WAITING_TASK
    time_str, task_name = parts
    try:
        hour, minute = map(int, time_str.split(":"))
        assert 0 <= hour <= 23 and 0 <= minute <= 59
    except Exception:
        await update.message.reply_text("Vaqt notogri! Masalan: 09:00")
        return WAITING_TASK
    uid = str(update.effective_user.id)
    tasks = get_user_tasks(uid)
    task = {"id": len(tasks) + 1, "name": task_name, "time": f"{hour:02d}:{minute:02d}", "done": False}
    tasks.append(task)
    save_user_tasks(uid, tasks)
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    rt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if rt <= now:
        rt += timedelta(days=1)
    context.job_queue.run_daily(
        remind,
        time=rt.timetz(),
        days=tuple(range(7)),
        chat_id=update.effective_chat.id,
        name=f"t_{uid}_{task['id']}",
        data={"name": task_name, "id": task["id"], "uid": uid}
    )
    await update.message.reply_text(
        f"Ish qoshildi!\nIsh: {task_name}\nVaqt: {hour:02d}:{minute:02d} (har kuni)\n\n/menu"
    )
    return ConversationHandler.END


async def cancel(update, context):
    await update.message.reply_text("Bekor qilindi. /menu")
    return ConversationHandler.END


async def remind(context):
    job = context.job
    d = job.data
    kb = [[
        InlineKeyboardButton("Bajardim", callback_data=f"mark_{d['id']}"),
        InlineKeyboardButton("30 daqiqa keyin", callback_data=f"snooze_{d['id']}")
    ]]
    await context.bot.send_message(
        chat_id=job.chat_id,
        text=f"ESLATMA!\n\n{d['name']}\n\nBajarish vaqti keldi!",
        reply_markup=InlineKeyboardMarkup(kb)
    )


async def list_tasks(update, context):
    q = update.callback_query
    uid = str(update.effective_user.id)
    if q:
        await q.answer()
    tasks = get_user_tasks(uid)
    if not tasks:
        text = "Ishlar yoq.\n\n/add - ish qoshish"
    else:
        active = [t for t in tasks if not t.get("done")]
        done = [t for t in tasks if t.get("done")]
        text = "Ishlaringiz:\n\n"
        if active:
            text += "Bajarilmagan:\n" + "".join(f"  {t['time']} - {t['name']}\n" for t in active)
        if done:
            text += "\nBarajarilgan:\n" + "".join(f"  {t['time']} - {t['name']} v\n" for t in done)
        text += f"\nJami: {len(tasks)} | Bajarilmagan: {len(active)}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Ish qoshish", callback_data="add"),
        InlineKeyboardButton("Menyu", callback_data="back")
    ]])
    t = q.message if q else update.message
    await t.reply_text(text, reply_markup=kb)


async def btn(update, context):
    q = update.callback_query
    await q.answer()
    d = q.data
    uid = str(update.effective_user.id)
    if d == "add":
        await q.message.reply_text(
            "Formatda yozing: HH:MM Ish nomi\nMasalan: 09:00 Email tekshirish\n\nBekor qilish: /cancel"
        )
        context.user_data["awaiting"] = True
    elif d == "list":
        await list_tasks(update, context)
    elif d == "done":
        tasks = get_user_tasks(uid)
        dl = [t for t in tasks if t.get("done")]
        text = "Bajarilgan:\n" + "".join(f"- {t['time']} {t['name']}\n" for t in dl) if dl else "Hali bajarilgan ishlar yoq."
        await q.message.reply_text(text)
    elif d == "clear":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Ha, ochir", callback_data="confirm_clear"),
            InlineKeyboardButton("Yoq", callback_data="back")
        ]])
        await q.message.reply_text("Barcha ishlarni ochirasizmi?", reply_markup=kb)
    elif d == "confirm_clear":
        save_user_tasks(uid, [])
        await q.message.reply_text("Barcha ishlar ochirildi!")
    elif d == "help":
        await help_cmd(update, context)
    elif d == "back":
        await q.message.reply_text("Asosiy menyu:", reply_markup=main_menu())
    elif d.startswith("mark_"):
        tid = int(d.split("_")[1])
        tasks = get_user_tasks(uid)
        for t in tasks:
            if t["id"] == tid:
                t["done"] = True
        save_user_tasks(uid, tasks)
        await q.edit_message_text("Bajarildi!")
    elif d.startswith("snooze_"):
        tid = int(d.split("_")[1])
        tasks = get_user_tasks(uid)
        name = next((t["name"] for t in tasks if t["id"] == tid), "")
        context.job_queue.run_once(
            remind, when=1800, chat_id=q.message.chat_id,
            data={"name": name, "id": tid, "uid": uid}
        )
        await q.edit_message_text(f"30 daqiqadan keyin eslataman!\n\n{name}")


async def msg_handler(update, context):
    if context.user_data.get("awaiting"):
        context.user_data["awaiting"] = False
        await receive_task(update, context)
    else:
        await update.message.reply_text("Tushunmadim. /menu")


def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={WAITING_TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_task)]},
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("list", list_tasks))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(btn))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    print("Bot ishga tushdi!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
