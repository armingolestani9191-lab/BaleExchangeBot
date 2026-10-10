
import json

from database import get_connection
from config import ORDER_CHANNEL, ADMIN_ID


MAX_ORDER_COUNT = 10000

BOT_ID = None
BOT_USERNAME = None


def set_bot_info(bot_id, username):
    global BOT_ID, BOT_USERNAME
    BOT_ID = bot_id
    BOT_USERNAME = (username or "").lstrip("@")


COMPLETED_ORDER_MESSAGE = """🎉 تبریک!

👁️ سفارش سینت با موفقیت تکمیل شد!
✅ تمام سین‌های درخواستی ثبت شدن.
📩 پست سفارش از کانال حذف شد.

💡 حالا می‌تونی:
• 🪙 دوباره سکه جمع کنی
• 👁️ سفارش سین جدید ثبت کنی
• 🚀 اگه سکه داری، همین الان سفارش بعدیت رو ثبت کن!

❤️ ممنون که از ربات ما استفاده می‌کنی."""


def init_views_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}'
            )
        """)


def set_state(user_id, state, payload=None):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_states (user_id, state, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state = excluded.state,
                payload = excluded.payload
            """,
            (
                user_id,
                state,
                json.dumps(payload or {}, ensure_ascii=False)
            )
        )


def get_state(user_id):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT state, payload
            FROM user_states
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

    if not row:
        return None, {}

    return row["state"], json.loads(row["payload"])


def clear_state(user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM user_states WHERE user_id = ?",
            (user_id,)
        )


def answer_callback(api, callback_id, text):
    api(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_id,
            "text": text
        }
    )


def order_keyboard(order_id):
    keyboard = [
        [
            {
                "text": "👁️ دیدم",
                "callback_data": f"seen:{order_id}"
            },
            {
                "text": "🚩 گزارش",
                "callback_data": f"report:{order_id}"
            }
        ]
    ]

    if BOT_USERNAME:
        keyboard.append([
            {
                "text": "🤖 رفتن به ربات",
                "url": f"https://ble.ir/{BOT_USERNAME}"
            }
        ])

    return {"inline_keyboard": keyboard}


def start_order(user_id, chat_id, send_message):
    set_state(user_id, "waiting_post")

    send_message(
        chat_id,
        "🛒 سفارش جدید سین\n\n"
        "پست موردنظرت رو از کانالت فوروارد کن.\n\n"
        "بعد از دریافت پست، تعداد سین موردنظرت رو وارد کن.\n\n"
        "💰 هزینه: هر کلیک یکتا = ۱ سکه\n\n"
        "برای لغو بنویس /cancel"
    )


def handle_message(message, api, send_message):
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return False

    state, payload = get_state(user_id)

    # لغو مرحلهٔ فعلی
    if text in ("/cancel", "لغو سفارش"):
        if state:
            clear_state(user_id)

            send_message(
                chat_id,
                "❌ مرحلهٔ فعلی لغو شد."
            )
            return True

        return False

    # دریافت پست فورواردشده
    if state == "waiting_post":
        if (
            not message.get("forward_origin")
            and not message.get("forward_from_chat")
        ):
            send_message(
                chat_id,
                "⚠️ لطفاً پست موردنظرت رو از کانالت فوروارد کن."
            )
            return True

        set_state(
            user_id,
            "waiting_count",
            {
                "source_chat_id": chat_id,
                "source_message_id": message.get("message_id")
            }
        )

        send_message(
            chat_id,
            "🔢 حالا تعداد سین موردنظرت رو وارد کن.\n\n"
            f"حداکثر تعداد: {MAX_ORDER_COUNT:,}\n"
            "💰 هزینهٔ هر کلیک یکتا: ۱ سکه"
        )

        return True

    # دریافت تعداد سین
    if state == "waiting_count":
        try:
            target_count = int(text)
        except (ValueError, TypeError):
            send_message(
                chat_id,
                "⚠️ لطفاً تعداد رو فقط به‌صورت عدد وارد کن."
            )
            return True

        if target_count < 1 or target_count > MAX_ORDER_COUNT:
            send_message(
                chat_id,
                f"⚠️ تعداد باید بین ۱ تا {MAX_ORDER_COUNT:,} باشه."
            )
            return True

        total_cost = target_count

        # بررسی موجودی و ثبت اولیه سفارش
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            user_row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()

            if not user_row or user_row["coins"] < total_cost:
                current_coins = (
                    user_row["coins"] if user_row else 0
                )

                conn.commit()

                send_message(
                    chat_id,
                    "❌ سکهٔ کافی نداری!\n\n"
                    f"💰 موجودی فعلی: {current_coins} سکه\n"
                    f"💸 هزینهٔ سفارش: {total_cost} سکه"
                )
                return True

            conn.execute(
                """
                UPDATE users
                SET coins = coins - ?
                WHERE user_id = ?
                """,
                (total_cost, user_id)
            )

            cursor = conn.execute(
                """
                INSERT INTO orders (
                    user_id,
                    order_type,
                    target_count,
                    counted_count,
                    status
                )
                VALUES (?, 'views', ?, 0, 'pending')
                """,
                (user_id, target_count)
            )

            order_id = cursor.lastrowid
            conn.commit()

        # فوروارد واقعی پیام اصلی کاربر به کانال سفارش‌ها
        forwarded = api(
            "forwardMessage",
            {
                "chat_id": ORDER_CHANNEL,
                "from_chat_id": payload["source_chat_id"],
                "message_id": payload["source_message_id"]
            }
        )

        # اگر فوروارد ناموفق بود، پول کاربر برگردد
        if not forwarded.get("ok"):
            with get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")

                conn.execute(
                    """
                    UPDATE users
                    SET coins = coins + ?
                    WHERE user_id = ?
                    """,
                    (total_cost, user_id)
                )

                conn.execute(
                    "DELETE FROM orders WHERE id = ?",
                    (order_id,)
                )

                conn.commit()

            clear_state(user_id)

            send_message(
                chat_id,
                "❌ فوروارد پست به کانال ناموفق بود.\n"
                "سکه‌های سفارش به حسابت برگردونده شدن."
            )
            return True

        channel_message_id = (
            forwarded.get("result", {}).get("message_id")
        )

        if not channel_message_id:
            with get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")

                conn.execute(
                    """
                    UPDATE users
                    SET coins = coins + ?
                    WHERE user_id = ?
                    """,
                    (total_cost, user_id)
                )

                conn.execute(
                    "DELETE FROM orders WHERE id = ?",
                    (order_id,)
                )

                conn.commit()

            clear_state(user_id)

            send_message(
                chat_id,
                "❌ شناسهٔ پیام فورواردشده دریافت نشد.\n"
                "سکه‌های سفارش به حسابت برگردونده شدن."
            )
            return True

        # پیام اطلاعات سفارش؛ جدا از پست فورواردشده
        info_text = (
            f"📋 **سفارش سین**\n\n"
            f"👤 سین درخواستی: {target_count}\n"
            f"👁️ سین خورده: 0\n"
            f"#{order_id}"
        )

        info_result = api(
            "sendMessage",
            {
                "chat_id": ORDER_CHANNEL,
                "text": info_text,
                "reply_to_message_id": channel_message_id,
                "reply_markup": order_keyboard(order_id)
            }
        )

        if not info_result.get("ok"):
            api(
                "deleteMessage",
                {
                    "chat_id": ORDER_CHANNEL,
                    "message_id": channel_message_id
                }
            )

            with get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")

                conn.execute(
                    """
                    UPDATE users
                    SET coins = coins + ?
                    WHERE user_id = ?
                    """,
                    (total_cost, user_id)
                )

                conn.execute(
                    "DELETE FROM orders WHERE id = ?",
                    (order_id,)
                )

                conn.commit()

            clear_state(user_id)

            send_message(
                chat_id,
                "❌ ارسال پیام دکمه‌های سفارش ناموفق بود.\n"
                "سکه‌های سفارش به حسابت برگردونده شدن."
            )
            return True

        info_message_id = (
            info_result.get("result", {}).get("message_id")
        )

        with get_connection() as conn:
            conn.execute(
                """
                UPDATE orders
                SET channel_message_id = ?,
                    info_message_id = ?
                WHERE id = ?
                """,
                (
                    channel_message_id,
                    info_message_id,
                    order_id
                )
            )

        clear_state(user_id)

        send_message(
            chat_id,
            "✅ سفارشت با موفقیت ثبت شد!\n\n"
            f"🆔 شماره سفارش: {order_id}\n"
            f"👁️ تعداد درخواستی: {target_count}\n"
            f"💰 هزینه: {total_cost} سکه"
        )

        return True

    return False


def handle_callback_query(callback, api, send_message):
    callback_id = callback.get("id")
    user = callback.get("from", {})
    user_id = user.get("id")
    data = callback.get("data", "")
    callback_message = callback.get("message", {})

    if not callback_id or not user_id:
        return False

    # ثبت کلیک روی دکمهٔ دیدم
    if data.startswith("seen:"):
        try:
            order_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            answer_callback(api, callback_id, "❌ سفارش نامعتبره.")
            return True

        completed = False
        new_count = 0
        owner_id = None
        channel_message_id = None
        info_message_id = None
        target_count = 0

        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            order = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE id = ?
                """,
                (order_id,)
            ).fetchone()

            if not order or order["status"] != "pending":
                conn.commit()
                answer_callback(
                    api,
                    callback_id,
                    "⚠️ این سفارش دیگه فعال نیست."
                )
                return True

            if order["user_id"] == user_id:
                conn.commit()
                answer_callback(
                    api,
                    callback_id,
                    "🚫 نمی‌تونی روی سفارش خودت کلیک کنی!"
                )
                return True

            # مطمئن می‌شویم کاربر در دیتابیس وجود دارد
            conn.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name
                )
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

            inserted = conn.execute(
                """
                INSERT OR IGNORE INTO order_clicks (
                    order_id, user_id
                )
                VALUES (?, ?)
                """,
                (order_id, user_id)
            )

            if inserted.rowcount == 0:
                conn.commit()
                answer_callback(
                    api,
                    callback_id,
                    "⚠️ قبلاً پاداش این سفارش رو گرفتی!"
                )
                return True

            conn.execute(
                """
                UPDATE users
                SET coins = coins + 1
                WHERE user_id = ?
                """,
                (user_id,)
            )

            new_count = order["counted_count"] + 1
            target_count = order["target_count"]
            completed = new_count >= target_count

            new_status = "completed" if completed else "pending"

            conn.execute(
                """
                UPDATE orders
                SET counted_count = ?,
                    status = ?
                WHERE id = ?
                """,
                (new_count, new_status, order_id)
            )

            owner_id = order["user_id"]
            channel_message_id = order["channel_message_id"]
            info_message_id = order["info_message_id"]

            conn.commit()

        answer_callback(
            api,
            callback_id,
            "🎉 یک سکه به حسابت اضافه شد!"
        )

        # وقتی سفارش کامل شد، پیام‌های کانال حذف می‌شوند
        if completed:
            if channel_message_id:
                api(
                    "deleteMessage",
                    {
                        "chat_id": ORDER_CHANNEL,
                        "message_id": channel_message_id
                    }
                )

            if info_message_id:
                api(
                    "deleteMessage",
                    {
                        "chat_id": ORDER_CHANNEL,
                        "message_id": info_message_id
                    }
                )

            # پیام جدید برای صاحب سفارش
            send_message(
                owner_id,
                COMPLETED_ORDER_MESSAGE
            )

        else:
            # متن جدید پس از هر کلیک یکتا
            new_info_text = (
                f"📋 **سفارش سین**\n\n"
                f"👤 سین درخواستی: {target_count}\n"
                f"👁️ سین خورده: {new_count}\n"
                f"#{order_id}"
            )

            if info_message_id:
                api(
                    "editMessageText",
                    {
                        "chat_id": ORDER_CHANNEL,
                        "message_id": info_message_id,
                        "text": new_info_text,
                        "reply_markup": order_keyboard(order_id)
                    }
                )

        return True

    # ثبت گزارش سفارش
    if data.startswith("report:"):
        try:
            order_id = int(data.split(":", 1)[1])
        except (ValueError, IndexError):
            answer_callback(api, callback_id, "❌ سفارش نامعتبره.")
            return True

        with get_connection() as conn:
            order = conn.execute(
                """
                SELECT *
                FROM orders
                WHERE id = ?
                """,
                (order_id,)
            ).fetchone()

            if not order or order["status"] != "pending":
                answer_callback(
                    api,
                    callback_id,
                    "⚠️ این سفارش دیگه فعال نیست."
                )
                return True

            if order["user_id"] == user_id:
                answer_callback(
                    api,
                    callback_id,
                    "🚫 نمی‌تونی سفارش خودت رو گزارش کنی!"
                )
                return True

            # ثبت اطلاعات گزارش‌دهنده
            conn.execute(
                """
                INSERT INTO users (
                    user_id, username, first_name
                )
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

            # دریافت مشخصات خریدار برای پیام ادمین
            buyer = conn.execute(
                """
                SELECT username, first_name
                FROM users
                WHERE user_id = ?
                """,
                (order["user_id"],)
            ).fetchone()

            conn.execute(
                """
                INSERT INTO reports (
                    order_id, reporter_id, reason
                )
                VALUES (?, ?, ?)
                """,
                (order_id, user_id, "گزارش از کانال")
            )

        answer_callback(
            api,
            callback_id,
            "✅ گزارش برای ادمین ارسال شد."
        )

        if ADMIN_ID:
            # اول خود بنر سفارش را برای ادمین کپی می‌کنیم.
            # channel_message_id شناسهٔ بنر است، نه پیام سفارش سین.
            banner_message_id = order["channel_message_id"]

            if banner_message_id:
                banner_result = api(
                    "copyMessage",
                    {
                        "chat_id": ADMIN_ID,
                        "from_chat_id": ORDER_CHANNEL,
                        "message_id": banner_message_id
                    }
                )

                if not banner_result.get("ok"):
                    print(
                        "Could not copy reported order banner:",
                        banner_result
                    )

            buyer_id = order["user_id"]

            buyer_username = (
                f"@{buyer['username']}"
                if buyer and buyer["username"]
                else "ندارد"
            )

            buyer_name = (
                buyer["first_name"]
                if buyer and buyer["first_name"]
                else "ثبت نشده"
            )

            report_text = (
                "🚩 گزارش جدید سفارش سین\n\n"
                f"📋 شماره سفارش: {order_id}\n"
                f"👤 نام خریدار: {buyer_name}\n"
                f"🔗 یوزرنیم خریدار: {buyer_username}\n"
                f"🆔 آیدی عددی خریدار: {buyer_id}\n"
                f"🧾 آیدی گزارش‌دهنده: {user_id}"
            )

            report_keyboard = {
                "inline_keyboard": [[
                    {
                        "text": "🚫 بن کردن خریدار",
                        "callback_data": (
                            f"reportban:{buyer_id}:{order_id}"
                        )
                    },
                    {
                        "text": "✅ بررسی شد",
                        "callback_data": f"reportdone:{order_id}"
                    }
                ]]
            }

            send_message(
                ADMIN_ID,
                report_text,
                report_keyboard
            )

        return True

    return False
