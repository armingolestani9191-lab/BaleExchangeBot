import re

from database import get_connection


BTN_PARTNER = "📢 کانال همکار"
BTN_ADD_CHANNEL = "➕ افزودن کانال"
BTN_MY_CHANNELS = "📋 کانال‌های من"
BTN_PARTNER_BACK = "🔙 بازگشت"

# وضعیت موقت مراحل ثبت کانال
_states = {}


def _answer(api, callback_id, text, alert=False):
    if not callback_id:
        return

    data = {
        "callback_query_id": callback_id,
        "text": text
    }

    if alert:
        data["show_alert"] = True

    api("answerCallbackQuery", data)


def _send(send_message, chat_id, text, keyboard=None):
    if keyboard:
        return send_message(chat_id, text, keyboard)

    return send_message(chat_id, text)


def _menu_keyboard():
    return {
        "keyboard": [
            [{"text": BTN_ADD_CHANNEL}],
            [{"text": BTN_MY_CHANNELS}],
            [{"text": BTN_PARTNER_BACK}]
        ],
        "resize_keyboard": True
    }


def init_tables():
    """
    برای سازگاری با راه‌اندازی فعلی ربات نگه داشته شده.
    جدول‌ها در init_db داخل database.py ساخته می‌شوند.
    """
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS partner_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL UNIQUE,
                username TEXT,
                title TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                approved_at TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS partner_earnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                order_type TEXT NOT NULL,
                order_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                UNIQUE(
                    channel_id,
                    order_type,
                    order_id,
                    user_id
                ),

                FOREIGN KEY (channel_id)
                    REFERENCES partner_channels(id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_partner_channels_owner
            ON partner_channels(owner_id)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_partner_channels_status
            ON partner_channels(status)
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_partner_earnings_channel
            ON partner_earnings(channel_id)
        """)


def _normalise_channel(value):
    value = value.strip()

    if value.startswith("https://t.me/"):
        value = value[len("https://t.me/"):]

    elif value.startswith("http://t.me/"):
        value = value[len("http://t.me/"):]

    value = value.strip("/")

    if value.startswith("@"):
        username = value[1:]

        if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            return None

        return "@" + username

    # پشتیبانی از شناسه عددی کانال
    if re.fullmatch(r"-100\d+", value):
        return value

    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
        return "@" + value

    return None


def _check_bot_admin(api, chat_id):
    me = api("getMe", {})

    if not me or not me.get("ok"):
        return False, None, "دریافت اطلاعات ربات ناموفق بود."

    bot_id = me.get("result", {}).get("id")

    if not bot_id:
        return False, None, "شناسه ربات دریافت نشد."

    chat_result = api("getChat", {
        "chat_id": chat_id
    })

    if not chat_result or not chat_result.get("ok"):
        return (
            False,
            None,
            "کانال پیدا نشد یا ربات به آن دسترسی ندارد."
        )

    chat = chat_result.get("result", {})

    if chat.get("type") != "channel":
        return False, None, "این شناسه مربوط به کانال نیست."

    member_result = api("getChatMember", {
        "chat_id": chat_id,
        "user_id": bot_id
    })

    if not member_result or not member_result.get("ok"):
        return (
            False,
            None,
            "وضعیت ادمین ربات بررسی نشد. "
            "ربات را به کانال اضافه کن و دوباره تلاش کن."
        )

    member = member_result.get("result", {})
    status = member.get("status")

    if status not in ("administrator", "creator", "owner"):
        return False, None, "ربات هنوز ادمین کانال نیست."

    # اگر API این دسترسی‌ها را گزارش کند، نبودن هر کدام
    # مانع ثبت کانال می‌شود.
    if status != "creator":
        if member.get("can_post_messages") is False:
            return (
                False,
                None,
                "دسترسی ارسال پیام برای ربات فعال نیست."
            )

        if member.get("can_edit_messages") is False:
            return (
                False,
                None,
                "دسترسی ویرایش پیام‌ها برای ربات فعال نیست."
            )

        if member.get("can_delete_messages") is False:
            return (
                False,
                None,
                "دسترسی حذف پیام‌ها برای ربات فعال نیست."
            )

    return True, chat, None


def _add_channel(user_id, value, api):
    channel_ref = _normalise_channel(value)

    if not channel_ref:
        return (
            False,
            "❌ لینک یا آیدی کانال معتبر نیست.\n"
            "مثال: @my_channel"
        )

    ok, chat, error = _check_bot_admin(api, channel_ref)

    if not ok:
        return False, "❌ " + error

    chat_id = chat.get("id")
    title = chat.get("title") or "بدون عنوان"
    username = chat.get("username")

    if not chat_id:
        return False, "شناسه کانال از بله دریافت نشد."

    with get_connection() as conn:
        existing = conn.execute("""
            SELECT owner_id, status
            FROM partner_channels
            WHERE chat_id = ?
        """, (chat_id,)).fetchone()

        if existing:
            if existing["owner_id"] == user_id:
                return False, "این کانال قبلاً ثبت شده است."

            return (
                False,
                "این کانال قبلاً توسط حساب دیگری ثبت شده است."
            )

        conn.execute("""
            INSERT INTO partner_channels (
                owner_id,
                chat_id,
                username,
                title,
                status,
                approved_at
            )
            VALUES (?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
        """, (
            user_id,
            chat_id,
            username,
            title
        ))

    return True, (
        "✅ کانال با موفقیت ثبت و تأیید شد!\n\n"
        f"📢 نام کانال: {title}\n"
        f"🆔 شناسه کانال: {chat_id}\n\n"
        "ثبت کانال انجام شد. انتشار سفارش‌ها در کانال‌های همکار "
        "نیازمند اتصال بخش انتشار سفارش‌هاست."
    )


def _my_channels(user_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                pc.id,
                pc.chat_id,
                pc.username,
                pc.title,
                pc.status,
                COALESCE(SUM(pe.amount), 0) AS earnings,
                COUNT(pe.id) AS valid_actions
            FROM partner_channels pc
            LEFT JOIN partner_earnings pe
                ON pe.channel_id = pc.id
            WHERE pc.owner_id = ?
            GROUP BY pc.id
            ORDER BY pc.id DESC
        """, (user_id,)).fetchall()

    if not rows:
        return "هنوز کانالی ثبت نکردی."

    lines = ["📋 کانال‌های همکار تو\n"]

    for row in rows:
        if row["status"] == "active":
            status_text = "فعال"
        elif row["status"] == "pending":
            status_text = "در انتظار تأیید"
        else:
            status_text = "غیرفعال"

        channel_name = (
            row["title"]
            or row["username"]
            or str(row["chat_id"])
        )

        lines.append(
            f"📢 {channel_name}\n"
            f"وضعیت: {status_text}\n"
            f"💰 درآمد ثبت‌شده: {row['earnings']} سکه\n"
            f"✅ اقدامات معتبر: {row['valid_actions']}\n"
        )

    return "\n".join(lines)


def handle_message(message, api, send_message):
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return False

    # این بخش فقط در گفت‌وگوی خصوصی کار می‌کند.
    if chat.get("type") != "private":
        return False

    if text == BTN_PARTNER_BACK:
        _states.pop(user_id, None)

        _send(
            send_message,
            chat_id,
            "به منوی اصلی برگشتی.",
        )
        return True

    if text == BTN_PARTNER:
        _states.pop(user_id, None)

        _send(
            send_message,
            chat_id,
            "📢 بخش کانال‌های همکار\n\n"
            "از این بخش می‌تونی کانالت رو ثبت کنی و "
            "وضعیت و آمار اولیه‌اش رو ببینی.",
            _menu_keyboard()
        )
        return True

    if text == BTN_ADD_CHANNEL:
        _states[user_id] = "waiting_channel"

        _send(
            send_message,
            chat_id,
            "➕ افزودن کانال\n\n"
            "۱. ربات را به کانالت اضافه کن.\n"
            "۲. دسترسی ادمین برای ارسال، ویرایش و حذف پیام‌ها بده.\n"
            "۳. لینک عمومی یا آیدی کانال را همین‌جا بفرست.\n\n"
            "مثال: @my_channel\n\n"
            "برای لغو، /cancel را بفرست."
        )
        return True

    if text == BTN_MY_CHANNELS:
        _states.pop(user_id, None)

        _send(
            send_message,
            chat_id,
            _my_channels(user_id),
            _menu_keyboard()
        )
        return True

    if _states.get(user_id) == "waiting_channel":
        if text == "/cancel":
            _states.pop(user_id, None)

            _send(
                send_message,
                chat_id,
                "ثبت کانال لغو شد."
            )
            return True

        success, result_text = _add_channel(
            user_id,
            text,
            api
        )

        if success:
            _states.pop(user_id, None)

        _send(
            send_message,
            chat_id,
            result_text,
            _menu_keyboard()
        )
        return True

    return False


def handle_callback(callback, api, send_message):
    # در این مرحله دکمهٔ درون‌پیامی مخصوص این فایل نداریم.
    return False
