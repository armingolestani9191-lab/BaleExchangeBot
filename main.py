
import time
import requests

from config import BOT_TOKEN
from database import init_db, get_connection
from features import views, members, guaranteed_members


API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}/"
session = requests.Session()

GUARANTEED_CHECK_INTERVAL = 300  # هر ۵ دقیقه
last_guaranteed_check = 0


def api(method, data=None):
    """ارسال درخواست به API بله با گزارش خطاها."""
    url = API_URL + method

    try:
        response = session.post(
            url,
            json=data or {},
            timeout=35
        )

        if not response.ok:
            print(f"\nAPI HTTP Error ({method})")
            print("Status:", response.status_code)
            print("Response:", response.text)

            return {
                "ok": False,
                "http_status": response.status_code,
                "description": response.text
            }

        try:
            result = response.json()
        except ValueError:
            print(f"\nInvalid JSON response ({method})")
            print("Response:", response.text)

            return {
                "ok": False,
                "description": "Invalid JSON response"
            }

        if not result.get("ok", False):
            print(f"\nAPI Error ({method}):", result)

        return result

    except requests.RequestException as error:
        print(f"\nConnection Error ({method}):", error)

        return {
            "ok": False,
            "description": str(error)
        }


def send_message(chat_id, text, keyboard=None):
    """ارسال پیام."""
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        data["reply_markup"] = keyboard

    return api("sendMessage", data)


def main_menu():
    """منوی اصلی ربات."""
    return {
        "keyboard": [
            [
                {"text": "🛒 سفارش سین"},
                {"text": "💰 کیف پول"}
            ],
            [
                {"text": "👥 ممبر معمولی"},
                {"text": "🛡️ ممبر تضمینی"}
            ],
            [
                {"text": "📖 راهنما"}
            ]
        ],
        "resize_keyboard": True
    }


def register_user(user):
    """ثبت یا به‌روزرسانی اطلاعات کاربر."""
    user_id = user.get("id")

    if not user_id:
        return

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (
                user_id,
                user.get("username"),
                user.get("first_name")
            )
        )


def clear_all_states(user_id):
    """پاک کردن مراحل فعال هر دو نوع سفارش و سین."""
    views.clear_state(user_id)
    members.clear_state(user_id)
    guaranteed_members.clear_state(user_id)


def handle_message(message):
    """مدیریت پیام‌های کاربران."""
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return

    register_user(user)

    # شروع ربات
    if text in ("/start", "شروع"):
        clear_all_states(user_id)

        send_message(
            chat_id,
            "سلام فرمانده! 👋\n\n"
            "به ربات سفارش سین و ممبر خوش اومدی.\n"
            "از منوی زیر انتخاب کن:",
            main_menu()
        )
        return

    # لغو مراحل
    if text == "/cancel":
        clear_all_states(user_id)

        send_message(
            chat_id,
            "❌ مراحل فعلی لغو شد.\n\n"
            "از منوی زیر می‌تونی دوباره شروع کنی.",
            main_menu()
        )
        return

    # سفارش ممبر معمولی
    if text == "👥 ممبر معمولی":
        clear_all_states(user_id)

        members.start_order(
            user_id,
            chat_id,
            send_message
        )
        return

    # سفارش ممبر تضمینی
    if text == "🛡️ ممبر تضمینی":
        clear_all_states(user_id)

        guaranteed_members.start_order(
            user_id,
            chat_id,
            send_message
        )
        return

    # سفارش سین
    if text == "🛒 سفارش سین":
        clear_all_states(user_id)

        views.start_order(
            user_id,
            chat_id,
            send_message
        )
        return

    # ادامه مراحل سفارش سین
    if views.handle_message(message, api, send_message):
        return

    # ادامه مراحل ممبر معمولی
    if members.handle_message(message, api, send_message):
        return

    # ادامه مراحل ممبر تضمینی
    if guaranteed_members.handle_message(message, api, send_message):
        return

    # کیف پول
    if text == "💰 کیف پول":
        with get_connection() as conn:
            row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()

        coins = row["coins"] if row else 0

        send_message(
            chat_id,
            f"💰 موجودی کیف پولت: {coins} سکه"
        )
        return

    # راهنما
    if text == "📖 راهنما":
        send_message(
            chat_id,
            "📖 راهنمای ربات\n\n"
            "🛒 سفارش سین: ثبت سفارش سین\n"
            "👥 ممبر معمولی: هر ممبر ۵ سکه\n"
            "🛡️ ممبر تضمینی: هر ممبر ۱۰ سکه\n"
            "💰 کیف پول: مشاهده موجودی سکه‌ها\n\n"
            "🎁 پاداش ممبر معمولی: ۳ سکه\n"
            "🎁 اولین پاداش ممبر تضمینی: ۲۵ سکه\n"
            "🎁 پاداش ممبرهای بعدی تضمینی: ۳ سکه\n"
            "⏱️ مهلت تضمین: ۴۸ ساعت\n\n"
            "برای لغو مراحل فعلی بنویس:\n"
            "/cancel"
        )


def handle_callback(callback):
    """مدیریت دکمه‌های شیشه‌ای."""
    data = callback.get("data", "")

    # ممبر تضمینی؛ پیشوند جداگانه دارد.
    if data.startswith("guaranteed_member_"):
        guaranteed_members.handle_callback_query(
            callback,
            api,
            send_message
        )
        return

    # ممبر معمولی
    if data.startswith("member_"):
        members.handle_callback_query(
            callback,
            api,
            send_message
        )
        return

    # سفارش سین
    views.handle_callback_query(
        callback,
        api,
        send_message
    )


def check_guaranteed_members_periodically():
    """بررسی خروج اعضای سفارش‌های تضمینی هر پنج دقیقه."""
    global last_guaranteed_check

    now = time.monotonic()

    if now - last_guaranteed_check < GUARANTEED_CHECK_INTERVAL:
        return

    # پیش از اجرا زمان را ثبت می‌کنیم تا در صورت خطا،
    # بررسی به شکل بی‌نهایت و پشت سر هم تکرار نشود.
    last_guaranteed_check = now

    try:
        guaranteed_members.check_guaranteed_memberships(
            api,
            send_message
        )
    except Exception as error:
        print("Guaranteed membership monitoring error:", repr(error))


def main():
    """راه‌اندازی ربات."""

    if not BOT_TOKEN or BOT_TOKEN == "توکن_واقعی_خودت":
        print("ERROR: توکن را در config.py تنظیم کن.")
        return

    # آماده‌سازی دیتابیس‌ها
    init_db()
    views.init_views_db()
    members.init_members_db()
    guaranteed_members.init_guaranteed_db()

    print("Database initialized.")

    # اتصال به API بله
    result = api("getMe")

    if not result.get("ok"):
        print("اتصال به API بله ناموفق بود.")
        print("پاسخ:", result)
        return

    bot = result.get("result", {})

    bot_id = bot.get("id")
    bot_username = bot.get("username")

    # تنظیم اطلاعات ربات در هر دو ماژول
    members.set_bot_info(
        bot_id,
        bot_username
    )

    guaranteed_members.set_bot_info(
        bot_id,
        bot_username
    )

    print("Bot connected:", bot_username or bot_id)

    offset = None

    print("Bot is running...")

    while True:
        try:
            params = {"timeout": 25}

            if offset is not None:
                params["offset"] = offset

            result = api("getUpdates", params)

            if not result.get("ok"):
                check_guaranteed_members_periodically()
                time.sleep(3)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message")
                callback = update.get("callback_query")

                try:
                    if message:
                        handle_message(message)

                    elif callback:
                        handle_callback(callback)

                except Exception as error:
                    print("Update processing error:", repr(error))

            # بررسی دوره‌ای حتی وقتی پیام جدیدی وجود ندارد
            check_guaranteed_members_periodically()

        except KeyboardInterrupt:
            print("Bot stopped.")
            break

        except Exception as error:
            print("Main loop error:", repr(error))
            time.sleep(2)


if __name__ == "__main__":
    main()
