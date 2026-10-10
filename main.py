
import time
import threading
import requests

from config import BOT_TOKEN, ADMIN_ID
from database import init_db, get_connection
from features import (
    views,
    members,
    guaranteed_members,
    daily_rewards,
    force_join,
    admin_panel,
    backup,
)


API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}/"
_thread_local = threading.local()
GUARANTEED_CHECK_INTERVAL = 20


def api(method, data=None):
    """ارسال درخواست به API بله."""
    try:
        session = getattr(_thread_local, "session", None)

        if session is None:
            session = requests.Session()
            _thread_local.session = session

        response = session.post(
            API_URL + method,
            json=data or {},
            timeout=35
        )

        if not response.ok:
            print(
                f"API HTTP Error ({method}):",
                response.status_code,
                response.text
            )
            return {
                "ok": False,
                "http_status": response.status_code,
                "description": response.text
            }

        try:
            result = response.json()
        except ValueError:
            return {
                "ok": False,
                "description": "Invalid JSON response"
            }

        if not result.get("ok", False):
            print(f"API Error ({method}):", result)

        return result

    except requests.RequestException as error:
        print(f"Connection Error ({method}):", error)
        return {"ok": False, "description": str(error)}


def send_message(chat_id, text, keyboard=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        data["reply_markup"] = keyboard

    return api("sendMessage", data)


def copy_message(to_chat_id, from_chat_id, message_id):
    """کپی پیام با حفظ متن و رسانه."""
    return api("copyMessage", {
        "chat_id": to_chat_id,
        "from_chat_id": from_chat_id,
        "message_id": message_id
    })


def answer_callback(callback_id, text=None, show_alert=False):
    data = {"callback_query_id": callback_id}

    if text:
        data["text"] = text

    if show_alert:
        data["show_alert"] = True

    return api("answerCallbackQuery", data)


def main_menu(user_id=None):
    keyboard = [
        [
            {"text": "🛒 سفارش سین"},
            {"text": "💰 کیف پول"}
        ],
        [
            {"text": "🎰 چرخونه روزانه"},
            {"text": "🎁 هدیه روزانه"}
        ],
        [
            {"text": "👥 ممبر معمولی"},
            {"text": "🛡️ ممبر تضمینی"}
        ],
        [
            {"text": "📖 راهنما"}
        ]
    ]

    if user_id and admin_panel.is_admin(user_id):
        keyboard.append([{"text": admin_panel.BTN_PANEL}])

    return {
        "keyboard": keyboard,
        "resize_keyboard": True
    }


def register_user(user):
    user_id = user.get("id")

    if not user_id:
        return

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
        """, (
            user_id,
            user.get("username"),
            user.get("first_name")
        ))


def admin_give_coins(text, admin_id, chat_id, send_message_func):
    try:
        if int(admin_id) != int(ADMIN_ID):
            return False
    except (TypeError, ValueError):
        return False

    import re

    match = re.fullmatch(
        r"(\d+)\s+(@?[A-Za-z0-9_]{1,64}|\d+)",
        text.strip()
    )

    if not match:
        return False

    amount = int(match.group(1))
    target = match.group(2)

    if amount <= 0 or amount > 1_000_000_000:
        send_message_func(
            chat_id,
            "❌ تعداد سکه باید بین ۱ تا یک میلیارد باشد."
        )
        return True

    with get_connection() as conn:
        if target.isdigit():
            target_id = int(target)

            if target_id <= 0:
                send_message_func(chat_id, "❌ آیدی عددی نامعتبر است.")
                return True

            conn.execute("""
                INSERT INTO users (user_id, coins)
                VALUES (?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    coins = users.coins + excluded.coins
            """, (target_id, amount))

        else:
            username = target.lstrip("@")

            row = conn.execute("""
                SELECT user_id
                FROM users
                WHERE LOWER(REPLACE(username, '@', '')) = LOWER(?)
                LIMIT 1
            """, (username,)).fetchone()

            if not row:
                send_message_func(
                    chat_id,
                    "❌ این یوزرنیم در دیتابیس پیدا نشد؛ "
                    "از آیدی عددی استفاده کن."
                )
                return True

            target_id = row["user_id"]

            conn.execute(
                "UPDATE users SET coins = coins + ? WHERE user_id = ?",
                (amount, target_id)
            )

        balance = conn.execute(
            "SELECT coins FROM users WHERE user_id = ?",
            (target_id,)
        ).fetchone()["coins"]

    send_message_func(
        chat_id,
        "✅ سکه‌ها اضافه شدند.\n\n"
        f"👤 آیدی کاربر: {target_id}\n"
        f"🪙 سکه اضافه‌شده: {amount}\n"
        f"💰 موجودی جدید: {balance}"
    )

    return True


def clear_all_states(user_id):
    views.clear_state(user_id)
    members.clear_state(user_id)
    guaranteed_members.clear_state(user_id)


def handle_message(message):
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return

    # بکاپ دیتابیس؛ فقط ادمین و فقط در گفت‌وگوی خصوصی.
    if backup.handle_message(message, send_message):
        return

    register_user(user)

    # پنل ادمین باید پیش از پردازش قابلیت‌های عادی اجرا شود.
    if admin_panel.handle_message(
        message,
        api,
        send_message,
        copy_message
    ):
        return

    # کاربر بن‌شده به هیچ قابلیت ربات دسترسی ندارد.
    if admin_panel.is_banned(user_id):
        send_message(
            chat_id,
            "🚫 شما از استفاده از ربات بن شده‌اید.\n"
            "در صورت اشتباه بودن این تصمیم، با پشتیبانی تماس بگیرید."
        )
        return

    # مدیریت قدیمی جوین اجباری حفظ می‌شود.
    if force_join.handle_admin_command(
        text,
        user_id,
        chat_id,
        ADMIN_ID,
        api,
        send_message
    ):
        return

    if admin_give_coins(text, user_id, chat_id, send_message):
        return

    # ادمین‌های پنل می‌توانند مدیریت کنند؛ کاربران عادی باید عضو باشند.
    if not admin_panel.is_admin(user_id):
        if not force_join.check_access(
            user_id,
            chat_id,
            api,
            send_message
        ):
            return

    if daily_rewards.handle_message(
        text,
        user_id,
        chat_id,
        send_message
    ):
        return

        if text in ("/start", "شروع"):
        clear_all_states(user_id)

        send_message(
            chat_id,
            "به دنیای تبلیغات خوش اومدی! 👋\n"
            "اینجا می‌تونی رایگان شروع کنی، خدمات رو ببینی و سفارش تبلیغاتت رو ثبت کنی.\n"
            "📖 برای آشنایی با امکانات ربات، راهنما رو بخون.\n"
            "برای شروع، یکی از گزینه‌های منوی پایین رو انتخاب کن.",
            main_menu(user_id)
        )
        return

    if text == "/cancel":
        clear_all_states(user_id)

        send_message(
            chat_id,
            "❌ مراحل فعلی لغو شد.\n\n"
            "از منوی زیر می‌تونی دوباره شروع کنی.",
            main_menu(user_id)
        )
        return

    if text == "👥 ممبر معمولی":
        clear_all_states(user_id)
        members.start_order(user_id, chat_id, send_message)
        return

    if text == "🛡️ ممبر تضمینی":
        clear_all_states(user_id)
        guaranteed_members.start_order(user_id, chat_id, send_message)
        return

    if text == "🛒 سفارش سین":
        clear_all_states(user_id)
        views.start_order(user_id, chat_id, send_message)
        return

    if views.handle_message(message, api, send_message):
        return

    if members.handle_message(message, api, send_message):
        return

    if guaranteed_members.handle_message(message, api, send_message):
        return

    if text == "💰 کیف پول":
        with get_connection() as conn:
            row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()

        coins = row["coins"] if row else 0
        send_message(chat_id, f"💰 موجودی کیف پولت: {coins} سکه")
        return

    if text == "📖 راهنما":
        send_message(
            chat_id,
            "📖 راهنمای ربات\n\n"
            "🛒 سفارش سین: ثبت سفارش سین\n"
            "👥 ممبر معمولی: هر ممبر ۵ سکه\n"
            "🛡️ ممبر تضمینی: هر ممبر ۱۰ سکه\n"
            "💰 کیف پول: مشاهده موجودی سکه‌ها\n"
            "🎰 چرخونه روزانه: جایزه تصادفی ۱ تا ۵۰ سکه، روزی یک‌بار\n"
            "🎁 هدیه روزانه: جایزه تصادفی ۱۰ تا ۲۵ سکه، روزی یک‌بار\n\n"
            "🎁 پاداش ممبر معمولی: ۳ سکه\n"
            "🎁 اولین پاداش ممبر تضمینی: ۲۵ سکه\n"
            "🎁 پاداش ممبرهای بعدی تضمینی: ۳ سکه\n"
            "⏱️ مهلت تضمین: ۴۸ ساعت\n\n"
            "برای لغو مراحل فعلی بنویس:\n/cancel"
        )


def handle_callback(callback):
    data = callback.get("data", "")
    callback_id = callback.get("id")
    user_id = callback.get("from", {}).get("id")

    # اصلاح گزارش: قبل از جوین اجباری پردازش شود.
    # در غیر این صورت، به‌جای گزارش، پیام عضویت نمایش داده می‌شد.
    if data.startswith("report:"):
        views.handle_callback_query(
            callback,
            api,
            send_message
        )
        return

    # دکمه‌های گزارش مدیریتی فقط برای ادمین‌ها هستند.
    if data.startswith("reportban:"):
        if not user_id or not admin_panel.is_admin(user_id):
            if callback_id:
                answer_callback(
                    callback_id,
                    "⛔ این دکمه فقط برای ادمین است.",
                    show_alert=True
                )
            return

        try:
            _, target_id, order_id = data.split(":", 2)
            target_id = int(target_id)
            int(order_id)
        except (ValueError, TypeError):
            if callback_id:
                answer_callback(
                    callback_id,
                    "❌ اطلاعات دکمه نامعتبر است.",
                    show_alert=True
                )
            return

        ok, message_text = admin_panel.ban_user(
            target_id,
            user_id
        )

        if callback_id:
            answer_callback(
                callback_id,
                ("✅ " if ok else "⚠️ ") + message_text,
                show_alert=True
            )
        return

    if data.startswith("reportdone:"):
        if not user_id or not admin_panel.is_admin(user_id):
            if callback_id:
                answer_callback(
                    callback_id,
                    "⛔ این دکمه فقط برای ادمین است.",
                    show_alert=True
                )
            return

        if callback_id:
            answer_callback(
                callback_id,
                "✅ گزارش بررسی شد."
            )
        return

    # مدیریت دکمه‌های پنل حفظ می‌شود.
    if admin_panel.handle_callback(
        callback,
        api,
        send_message,
        answer_callback
    ):
        return

    if force_join.handle_callback(
        callback,
        api,
        send_message,
        answer_callback
    ):
        return

    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not user_id or not chat_id:
        return

    if admin_panel.is_banned(user_id):
        if callback_id:
            answer_callback(
                callback_id,
                "🚫 شما بن شده‌اید.",
                show_alert=True
            )
        return

    if not admin_panel.is_admin(user_id):
        if not force_join.check_access(
            user_id,
            chat_id,
            api,
            send_message
        ):
            if callback_id:
                answer_callback(
                    callback_id,
                    "ابتدا عضو کانال‌های اجباری شو.",
                    show_alert=True
                )
            return

    if data.startswith("guaranteed_member_"):
        guaranteed_members.handle_callback_query(
            callback,
            api,
            send_message
        )
        return

    if data.startswith("member_"):
        members.handle_callback_query(
            callback,
            api,
            send_message
        )
        return

    views.handle_callback_query(
        callback,
        api,
        send_message
    )


def guaranteed_membership_monitor():
    print(
        "Guaranteed membership monitor started. "
        f"Interval: {GUARANTEED_CHECK_INTERVAL}s"
    )

    while True:
        started_at = time.monotonic()

        try:
            guaranteed_members.check_guaranteed_memberships(
                api,
                send_message
            )
        except Exception as error:
            print(
                "Guaranteed membership monitoring error:",
                repr(error)
            )

        elapsed = time.monotonic() - started_at
        time.sleep(max(1, GUARANTEED_CHECK_INTERVAL - elapsed))


def start_guaranteed_membership_monitor():
    worker = threading.Thread(
        target=guaranteed_membership_monitor,
        name="guaranteed-membership-monitor",
        daemon=True
    )
    worker.start()


def main():
    if not BOT_TOKEN:
        print("ERROR: توکن ربات در config.py تنظیم نشده.")
        return

    init_db()
    views.init_views_db()
    members.init_members_db()
    guaranteed_members.init_guaranteed_db()
    daily_rewards.init_daily_rewards_db()
    force_join.init_force_join_db()
    admin_panel.init_admin_panel_db()

    print("Database initialized.")

    result = api("getMe")

    if not result or not result.get("ok"):
        print("اتصال به API بله ناموفق بود.")
        print("پاسخ:", result)
        return

    bot = result.get("result", {})
    bot_id = bot.get("id")
    bot_username = bot.get("username")

    views.set_bot_info(bot_id, bot_username)
    members.set_bot_info(bot_id, bot_username)
    guaranteed_members.set_bot_info(bot_id, bot_username)

    print("Bot connected:", bot_username or bot_id)

    start_guaranteed_membership_monitor()

    offset = None
    print("Bot is running...")

    while True:
        try:
            params = {"timeout": 25}

            if offset is not None:
                params["offset"] = offset

            result = api("getUpdates", params)

            if not result or not result.get("ok"):
                time.sleep(3)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1

                try:
                    if update.get("message"):
                        handle_message(update["message"])
                    elif update.get("callback_query"):
                        handle_callback(update["callback_query"])
                except Exception as error:
                    print("Update processing error:", repr(error))

        except KeyboardInterrupt:
            print("Bot stopped.")
            break

        except Exception as error:
            print("Main loop error:", repr(error))
            time.sleep(2)


if __name__ == "__main__":
    main()
