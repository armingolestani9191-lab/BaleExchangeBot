import re

from database import get_connection


BTN_PARTNER = "📢 کانال همکار"
BTN_ADD_CHANNEL = "➕ افزودن کانال"
BTN_REMOVE_CHANNEL = "➖ حذف کانال"
BTN_MY_CHANNELS = "📋 کانال‌های من"
BTN_PARTNER_BACK = "🔙 بازگشت"

# وضعیت موقت مراحل ثبت یا حذف کانال
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
            [{"text": BTN_REMOVE_CHANNEL}],
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


def _channel_success_text(title, chat_id):
    return (
        "✅ کانال با موفقیت ثبت و فعال شد!\n\n"
        f"📢 نام کانال: {title}\n"
        f"🆔 شناسه کانال: {chat_id}\n\n"
        "از این به بعد سفارش‌های جدید می‌تونن در کانال همکار منتشر بشن. "
        "برای هر سفارش که با موفقیت در کانالت منتشر بشه، ۵ سکه پاداش می‌گیری."
    )


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
            SELECT id, owner_id, status
            FROM partner_channels
            WHERE chat_id = ?
            LIMIT 1
        """, (chat_id,)).fetchone()

        if existing:
            if int(existing["owner_id"]) != int(user_id):
                return (
                    False,
                    "❌ این کانال قبلاً توسط حساب دیگری ثبت شده است."
                )

            if existing["status"] != "inactive":
                return False, "این کانال قبلاً ثبت شده است."

            # کانال قبلاً حذف شده بود؛ در صورت ثبت مجدد فعالش کن.
            conn.execute("""
                UPDATE partner_channels
                SET
                    username = ?,
                    title = ?,
                    status = 'active',
                    approved_at = CURRENT_TIMESTAMP
                WHERE id = ?
                  AND owner_id = ?
            """, (
                username,
                title,
                existing["id"],
                user_id,
            ))

            return True, _channel_success_text(title, chat_id)

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

    return True, _channel_success_text(title, chat_id)


def _my_channels(user_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                pc.id,
                pc.chat_id,
                pc.username,
                pc.title,
                pc.status,
                COALESCE(SUM(por.amount), 0) AS earnings,
                COUNT(por.id) AS valid_actions
            FROM partner_channels pc
            LEFT JOIN partner_order_rewards por
                ON por.channel_id = pc.id
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
            status_text = "غیرفعال / حذف‌شده"

        channel_name = (
            row["title"]
            or row["username"]
            or str(row["chat_id"])
        )

        lines.append(
            f"📢 {channel_name}\n"
            f"🔢 شناسه ثبت کانال: {row['id']}\n"
            f"وضعیت: {status_text}\n"
            f"💰 درآمد ثبت‌شده: {row['earnings']} سکه\n"
            f"✅ سفارش‌های پاداش‌گرفته: {row['valid_actions']}\n"
        )

    return "\n".join(lines)


def _channels_for_removal(user_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                id,
                chat_id,
                username,
                title
            FROM partner_channels
            WHERE owner_id = ?
              AND status = 'active'
            ORDER BY id DESC
        """, (user_id,)).fetchall()

    return rows


def _remove_channel(user_id, value):
    """
    فقط کانالی را غیرفعال می‌کند که متعلق به همین کاربر باشد.
    رکورد کانال حذف فیزیکی نمی‌شود تا سابقه پاداش و درآمد باقی بماند.
    """
    value = value.strip()

    if not value.isdigit():
        return (
            False,
            "❌ شناسه ثبت کانال باید عددی باشد.\n"
            "عدد کنار «شناسه ثبت کانال» را بفرست."
        )

    channel_id = int(value)

    with get_connection() as conn:
        row = conn.execute("""
            SELECT id, title, chat_id
            FROM partner_channels
            WHERE id = ?
              AND owner_id = ?
              AND status = 'active'
            LIMIT 1
        """, (channel_id, user_id)).fetchone()

        if not row:
            return (
                False,
                "❌ کانال فعالی با این شناسه در فهرست خودت پیدا نشد.\n"
                "شناسه را از فهرست کانال‌های خودت بررسی کن."
            )

        conn.execute("""
            UPDATE partner_channels
            SET status = 'inactive'
            WHERE id = ?
              AND owner_id = ?
              AND status = 'active'
        """, (
            channel_id,
            user_id,
        ))

    title = row["title"] or str(row["chat_id"])

    return True, (
        "✅ کانال از فهرست همکارهای فعال خارج شد.\n\n"
        f"📢 کانال: {title}\n\n"
        "از این به بعد سفارش جدیدی در این کانال منتشر نمی‌شود.\n"
        "💰 سابقه درآمد و پاداش‌های قبلی محفوظ است."
    )


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
            "از این بخش می‌تونی کانالت رو ثبت کنی، "
            "کانال‌های ثبت‌شده رو ببینی یا کانالی رو از همکاری خارج کنی.",
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
            "برای لغو، /cancel را بفرست.",
            _menu_keyboard()
        )
        return True

    if text == BTN_REMOVE_CHANNEL:
        rows = _channels_for_removal(user_id)

        if not rows:
            _states.pop(user_id, None)

            _send(
                send_message,
                chat_id,
                "فعلاً کانال همکار فعالی برای حذف نداری.",
                _menu_keyboard()
            )
            return True

        _states[user_id] = "waiting_delete_channel"

        lines = [
            "➖ حذف کانال همکار\n",
            "کانالی را که می‌خواهی حذف کنی از فهرست زیر پیدا کن.",
            "فقط عدد «شناسه ثبت کانال» را در پیام بعدی بفرست:\n"
        ]

        for row in rows:
            channel_name = (
                row["title"]
                or row["username"]
                or str(row["chat_id"])
            )

            lines.append(
                f"📢 {channel_name}\n"
                f"شناسه ثبت کانال: {row['id']}\n"
            )

        lines.append(
            "⚠️ کانال از همکاری فعال خارج می‌شود؛ "
            "سابقه درآمد و پاداش‌های قبلی باقی می‌ماند.\n"
            "برای لغو، /cancel را بفرست."
        )

        _send(
            send_message,
            chat_id,
            "\n".join(lines),
            _menu_keyboard()
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
                "ثبت کانال لغو شد.",
                _menu_keyboard()
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

    if _states.get(user_id) == "waiting_delete_channel":
        if text == "/cancel":
            _states.pop(user_id, None)

            _send(
                send_message,
                chat_id,
                "عملیات حذف کانال لغو شد.",
                _menu_keyboard()
            )
            return True

        success, result_text = _remove_channel(
            user_id,
            text
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
    # این بخش فعلاً دکمه درون‌پیامی ندارد.
    return False
