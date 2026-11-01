
import re

from database import get_connection
from features import admin_panel


BTN_PARTNER = "📢 افزودن کانال"
BTN_ADD_CHANNEL = "➕ افزودن کانال"
BTN_REMOVE_CHANNEL = "➖ حذف کانال"
BTN_MY_CHANNELS = "📋 کانال‌های من"
BTN_PARTNER_BACK = "🏠 بازگشت به منوی اصلی"

_states = {}


def _send(send_message, chat_id, text, keyboard=None):
    if keyboard:
        return send_message(chat_id, text, keyboard)
    return send_message(chat_id, text)


def _main_menu_keyboard(user_id):
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
            {"text": BTN_PARTNER}
        ],
        [
            {"text": "📖 راهنما"}
        ]
    ]

    if admin_panel.is_admin(user_id):
        keyboard.append([{"text": admin_panel.BTN_PANEL}])

    return {
        "keyboard": keyboard,
        "resize_keyboard": True
    }


def _partner_menu_keyboard():
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

    for prefix in (
        "https://t.me/",
        "http://t.me/",
        "https://bale.ai/",
        "http://bale.ai/",
    ):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break

    value = value.strip().strip("/")

    if value.startswith("@"):
        username = value[1:]
        if re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            return "@" + username
        return None

    if re.fullmatch(r"-100\d+", value):
        return value

    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", value):
        return "@" + value

    return None


def _check_bot_admin(api, channel_ref):
    me = api("getMe", {})

    if not me or not me.get("ok"):
        return False, None, "دریافت اطلاعات ربات ناموفق بود."

    bot_id = me.get("result", {}).get("id")
    if not bot_id:
        return False, None, "شناسه ربات دریافت نشد."

    result = api("getChat", {"chat_id": channel_ref})

    if not result or not result.get("ok"):
        return False, None, (
            "کانال پیدا نشد یا ربات به آن دسترسی ندارد. "
            "یوزرنیم یا آیدی کانال را بررسی کن."
        )

    chat = result.get("result", {})

    if chat.get("type") != "channel":
        return False, None, "این شناسه مربوط به کانال نیست."

    member_result = api("getChatMember", {
        "chat_id": chat.get("id"),
        "user_id": bot_id
    })

    if not member_result or not member_result.get("ok"):
        return False, None, (
            "وضعیت ادمین ربات بررسی نشد. "
            "ربات را به کانال اضافه کن و دوباره تلاش کن."
        )

    member = member_result.get("result", {})
    status = member.get("status")

    if status not in ("administrator", "creator", "owner"):
        return False, None, "ربات هنوز ادمین کانال نیست."

    if status != "creator":
        if member.get("can_post_messages") is False:
            return False, None, "دسترسی ارسال پیام ربات فعال نیست."

        if member.get("can_edit_messages") is False:
            return False, None, "دسترسی ویرایش پیام ربات فعال نیست."

        if member.get("can_delete_messages") is False:
            return False, None, "دسترسی حذف پیام ربات فعال نیست."

    return True, chat, None


def _add_channel(user_id, value, api):
    channel_ref = _normalise_channel(value)

    if not channel_ref:
        return False, (
            "❌ آیدی یا یوزرنیم معتبر نیست.\n"
            "مثال: @my_channel"
        )

    ok, chat, error = _check_bot_admin(api, channel_ref)

    if not ok:
        return False, "❌ " + error

    chat_id = chat.get("id")
    title = chat.get("title") or "بدون عنوان"
    username = chat.get("username")

    if chat_id is None:
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
                return False, (
                    "❌ این کانال قبلاً توسط حساب دیگری ثبت شده است."
                )

            if existing["status"] == "active":
                return False, "این کانال هم‌اکنون فعال است."

            conn.execute("""
                UPDATE partner_channels
                SET username = ?,
                    title = ?,
                    status = 'active',
                    approved_at = CURRENT_TIMESTAMP
                WHERE id = ? AND owner_id = ?
            """, (
                username,
                title,
                existing["id"],
                user_id
            ))
        else:
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
        "✅ کانال با موفقیت ثبت و فعال شد!\n\n"
        f"📢 نام کانال: {title}\n"
        f"🆔 شناسه کانال: {chat_id}\n\n"
        "سفارش‌های جدید در این کانال منتشر می‌شوند و "
        "برای هر سفارش با انتشار موفق، ۵ سکه پاداش می‌گیری."
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
                COALESCE(SUM(por.amount), 0) AS earnings,
                COUNT(por.id) AS rewarded_orders
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
            status_text = "حذف‌شده"

        name = row["title"] or row["username"] or str(row["chat_id"])

        lines.append(
            f"📢 {name}\n"
            f"🆔 آیدی کانال: {row['chat_id']}\n"
            f"وضعیت: {status_text}\n"
            f"💰 درآمد ثبت‌شده: {row['earnings']} سکه\n"
            f"✅ سفارش‌های پاداش‌گرفته: {row['rewarded_orders']}\n"
        )

    return "\n".join(lines)


def _remove_channel(user_id, value):
    channel_ref = _normalise_channel(value)

    if not channel_ref:
        return False, (
            "❌ آیدی یا یوزرنیم کانال معتبر نیست.\n"
            "مثال: @my_channel یا شناسه عددی کانال"
        )

    # برای یوزرنیم، ابتدا کانال را از API پیدا می‌کنیم.
    # اگر کانال قابل دسترسی نباشد، حذف انجام نمی‌شود.
    with get_connection() as conn:
        if channel_ref.startswith("@"):
            result = None
            # برای حذف، خود کاربر لازم نیست ادمین ربات باشد؛
            # ولی ربات باید بتواند کانال را از API شناسایی کند.
            # تابع getChat در ادامه با شناسه ارسالی فراخوانی می‌شود.
        else:
            result = None

    # در بله باید شناسه عددی کانال از getChat به دست بیاید.
    # چون این تابع API نمی‌گیرد، جست‌وجو با اطلاعات ذخیره‌شده
    # انجام می‌شود؛ برای یوزرنیم و آیدی عددی هر دو.
    with get_connection() as conn:
        if channel_ref.startswith("@"):
            key = channel_ref[1:].lower()
            row = conn.execute("""
                SELECT id, chat_id, title, username
                FROM partner_channels
                WHERE owner_id = ?
                  AND status = 'active'
                  AND LOWER(username) = ?
                LIMIT 1
            """, (user_id, key)).fetchone()
        elif channel_ref.startswith("-100"):
            row = conn.execute("""
                SELECT id, chat_id, title, username
                FROM partner_channels
                WHERE owner_id = ?
                  AND status = 'active'
                  AND chat_id = ?
                LIMIT 1
            """, (user_id, int(channel_ref))).fetchone()
        else:
            key = channel_ref.lower()
            row = conn.execute("""
                SELECT id, chat_id, title, username
                FROM partner_channels
                WHERE owner_id = ?
                  AND status = 'active'
                  AND LOWER(username) = ?
                LIMIT 1
            """, (user_id, key)).fetchone()

        if not row:
            return False, (
                "❌ کانال فعالی با این آیدی یا یوزرنیم در فهرست خودت نیست.\n"
                "آیدی یا یوزرنیم را دقیق بررسی کن."
            )

        channel_id = row["id"]

        # حذف سوابق وابسته تا محدودیت کلید خارجی مانع حذف نشود.
        # سابقه پاداش کانال حذف‌شده نیز با حذف کامل رکورد پاک می‌شود.
        conn.execute("""
            DELETE FROM partner_order_rewards
            WHERE channel_id = ?
        """, (channel_id,))

        conn.execute("""
            DELETE FROM partner_earnings
            WHERE channel_id = ?
        """, (channel_id,))

        # حذف کامل کانال از فهرست کانال‌های همکار
        conn.execute("""
            DELETE FROM partner_channels
            WHERE id = ? AND owner_id = ?
        """, (channel_id, user_id))

    name = row["title"] or row["username"] or str(row["chat_id"])

    return True, (
        "✅ کانال با موفقیت از فهرست کانال‌های همکار حذف شد.\n\n"
        f"📢 کانال: {name}\n"
        "از این به بعد سفارش جدیدی برای این کانال منتشر نمی‌شود."
    )


def handle_message(message, api, send_message):
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return False

    if chat.get("type") != "private":
        return False

    if text == BTN_PARTNER_BACK:
        _states.pop(user_id, None)
        _send(
            send_message,
            chat_id,
            "🏠 به منوی اصلی برگشتی.",
            _main_menu_keyboard(user_id)
        )
        return True

    if text == BTN_PARTNER:
        _states.pop(user_id, None)
        _send(
            send_message,
            chat_id,
            "📢 بخش کانال‌های همکار\n\n"
            "از این بخش می‌تونی کانال اضافه کنی، حذف کنی "
            "یا درآمد و وضعیت کانال‌هات رو ببینی.",
            _partner_menu_keyboard()
        )
        return True

    if text == BTN_ADD_CHANNEL:
        _states[user_id] = "waiting_channel"
        _send(
            send_message,
            chat_id,
            "➕ افزودن کانال\n\n"
            "۱. ربات را به کانالت اضافه کن.\n"
            "۲. دسترسی ادمین ارسال، ویرایش و حذف پیام‌ها بده.\n"
            "۳. آیدی یا یوزرنیم کانال را بفرست.\n\n"
            "مثال: @my_channel\n"
            "برای لغو، /cancel را بفرست.",
            _partner_menu_keyboard()
        )
        return True

    if text == BTN_REMOVE_CHANNEL:
        _states[user_id] = "waiting_delete_channel"
        _send(
            send_message,
            chat_id,
            "➖ حذف کانال همکار\n\n"
            "آیدی یا یوزرنیم کانالی را که می‌خواهی حذف کنی بفرست.\n\n"
            "مثال: @my_channel\n"
            "برای لغو، /cancel را بفرست.",
            _partner_menu_keyboard()
        )
        return True

    if text == BTN_MY_CHANNELS:
        _states.pop(user_id, None)
        _send(
            send_message,
            chat_id,
            _my_channels(user_id),
            _partner_menu_keyboard()
        )
        return True

    state = _states.get(user_id)

    if state in ("waiting_channel", "waiting_delete_channel"):
        if text == "/cancel":
            _states.pop(user_id, None)
            _send(
                send_message,
                chat_id,
                "عملیات لغو شد.",
                _partner_menu_keyboard()
            )
            return True

        if state == "waiting_channel":
            success, result_text = _add_channel(user_id, text, api)
        else:
            success, result_text = _remove_channel(user_id, text)

        if success:
            _states.pop(user_id, None)

        _send(
            send_message,
            chat_id,
            result_text,
            _partner_menu_keyboard()
        )
        return True

    return False


def handle_callback(callback, api, send_message):
    return False
