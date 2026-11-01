
"""Multi-channel mandatory membership for BaleExchangeBot."""

from database import get_connection


CHECK_CALLBACK = "force_join_check"


def init_force_join_db():
    """Create the persistent channel configuration table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS force_join_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                title TEXT,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


def normalize_username(value):
    """Normalize a public channel username."""
    value = (value or "").strip()

    if value.startswith("https://ble.ir/"):
        value = value.rsplit("/", 1)[-1]

    if value.startswith("@"):
        value = value[1:]

    return value.strip()


def get_channels():
    """Return configured channels."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, username, title
            FROM force_join_channels
            ORDER BY id
        """).fetchall()

    return [dict(row) for row in rows]


def add_channel(username, title=None):
    """Add or update a channel."""
    username = normalize_username(username)

    if not username:
        return False

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO force_join_channels (username, title)
            VALUES (?, ?)
            ON CONFLICT(username) DO UPDATE SET
                title = COALESCE(excluded.title, force_join_channels.title)
        """, (username, title))

    return True


def remove_channel(username):
    """Remove a configured channel."""
    username = normalize_username(username)

    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM force_join_channels WHERE LOWER(username) = LOWER(?)",
            (username,)
        )

    return result.rowcount > 0


def channel_list_text():
    """Format the configured channel list."""
    channels = get_channels()

    if not channels:
        return "📭 هنوز هیچ کانالی برای جوین اجباری ثبت نشده."

    lines = ["📋 کانال‌های جوین اجباری:\n"]

    for index, channel in enumerate(channels, start=1):
        username = channel["username"]
        title = channel.get("title") or username
        lines.append(f"{index}. {title} — @{username}")

    return "\n".join(lines)


def is_member(api, channel_username, user_id):
    """Check whether a user is a member of a channel."""
    result = api("getChatMember", {
        "chat_id": f"@{channel_username}",
        "user_id": user_id
    })

    if not result or not result.get("ok"):
        # Do not allow access when membership cannot be verified.
        print(
            "Force join membership check failed:",
            channel_username,
            result
        )
        return False

    member = result.get("result", {})
    status = member.get("status")

    if status in ("creator", "administrator", "member"):
        return True

    if status == "restricted" and member.get("is_member"):
        return True

    return False


def missing_channels(api, user_id):
    """Return channels the user has not joined."""
    missing = []

    for channel in get_channels():
        if not is_member(api, channel["username"], user_id):
            missing.append(channel)

    return missing


def build_join_keyboard(channels):
    """Build inline join buttons and the membership check button."""
    rows = []

    for channel in channels:
        username = channel["username"]
        title = channel.get("title") or f"عضویت در @{username}"

        rows.append([
            {
                "text": f"📢 عضویت در {title}",
                "url": f"https://ble.ir/{username}"
            }
        ])

    rows.append([
        {
            "text": "✅ بررسی عضویت",
            "callback_data": CHECK_CALLBACK
        }
    ])

    return {"inline_keyboard": rows}


def send_join_prompt(chat_id, send_message, channels=None):
    """Ask the user to join all required channels."""
    channels = channels if channels is not None else get_channels()

    if not channels:
        return

    send_message(
        chat_id,
        "🔒 برای استفاده از ربات، اول باید عضو کانال‌های زیر بشی.\n\n"
        "بعد از عضویت در همه کانال‌ها، روی «بررسی عضویت» بزن. 👇",
        build_join_keyboard(channels)
    )


def handle_admin_command(text, user_id, chat_id, admin_id, api, send_message):
    """Handle /addchannel, /removechannel and /channels for the main admin."""
    if text not in ("/channels",) and not (
        text.startswith("/addchannel")
        or text.startswith("/removechannel")
    ):
        return False

    try:
        if int(user_id) != int(admin_id):
            send_message(chat_id, "⛔ این دستور فقط برای ادمین رباته.")
            return True
    except (TypeError, ValueError):
        send_message(chat_id, "⛔ شناسه ادمین تنظیم نشده.")
        return True

    parts = text.split(maxsplit=1)
    command = parts[0].split("@", 1)[0].lower()

    if command == "/channels":
        send_message(chat_id, channel_list_text())
        return True

    if len(parts) != 2:
        if command == "/addchannel":
            send_message(
                chat_id,
                "روش استفاده:\n"
                "/addchannel @ChannelUsername\n\n"
                "ربات باید در کانال دسترسی لازم برای بررسی عضویت را داشته باشد."
            )
        else:
            send_message(
                chat_id,
                "روش استفاده:\n/removechannel @ChannelUsername"
            )
        return True

    username = normalize_username(parts[1])

    if not username or any(char.isspace() for char in username):
        send_message(chat_id, "❌ نام کانال معتبر نیست.")
        return True

    if command == "/addchannel":
        # Verify that the bot can access the channel before saving it.
        result = api("getChat", {"chat_id": f"@{username}"})

        if not result or not result.get("ok"):
            send_message(
                chat_id,
                "❌ کانال پیدا نشد یا ربات به آن دسترسی ندارد.\n"
                "نام کانال را بررسی کن و ربات را به کانال اضافه کن."
            )
            return True

        channel = result.get("result", {})
        actual_username = normalize_username(
            channel.get("username") or username
        )

        if not actual_username:
            send_message(
                chat_id,
                "❌ برای این روش باید کانال عمومی با آیدی مشخص داشته باشی."
            )
            return True

        # Check the bot's own membership/permissions.
        bot_info = api("getMe")
        bot_id = (bot_info or {}).get("result", {}).get("id")

        if not bot_id:
            send_message(chat_id, "❌ اطلاعات ربات از بله دریافت نشد.")
            return True

        bot_member = api("getChatMember", {
            "chat_id": f"@{actual_username}",
            "user_id": bot_id
        })

        if not bot_member or not bot_member.get("ok"):
            send_message(
                chat_id,
                "❌ ربات نمی‌تونه عضویت کانال رو بررسی کنه.\n"
                "ربات رو ادمین کانال کن و دوباره امتحان کن."
            )
            return True

        add_channel(actual_username, channel.get("title"))

        send_message(
            chat_id,
            f"✅ کانال @{actual_username} به جوین اجباری اضافه شد.\n\n"
            "از /channels برای دیدن فهرست کانال‌ها استفاده کن."
        )
        return True

    if command == "/removechannel":
        if remove_channel(username):
            send_message(
                chat_id,
                f"✅ کانال @{username} از جوین اجباری حذف شد."
            )
        else:
            send_message(
                chat_id,
                f"❌ کانال @{username} در فهرست جوین اجباری نبود."
            )

        return True

    return False


def check_access(user_id, chat_id, api, send_message):
    """Return True when access is allowed; otherwise show join prompt."""
    channels = get_channels()

    if not channels:
        return True

    missing = missing_channels(api, user_id)

    if missing:
        send_join_prompt(chat_id, send_message, missing)
        return False

    return True


def handle_callback(callback, api, send_message, answer_callback):
    """Handle the inline membership verification button."""
    data = callback.get("data", "")

    if data != CHECK_CALLBACK:
        return False

    callback_id = callback.get("id")
    user = callback.get("from", {})
    user_id = user.get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")

    if not user_id or not chat_id:
        if callback_id:
            answer_callback(callback_id, "اطلاعات کاربر دریافت نشد.")
        return True

    channels = get_channels()

    if not channels:
        if callback_id:
            answer_callback(callback_id, "فعلاً کانال اجباری ثبت نشده.")
        send_message(chat_id, "✅ جوین اجباری فعال نیست.")
        return True

    missing = missing_channels(api, user_id)

    if missing:
        if callback_id:
            answer_callback(
                callback_id,
                "هنوز عضو همه کانال‌ها نشدی.",
                show_alert=True
            )

        send_join_prompt(chat_id, send_message, missing)
        return True

    if callback_id:
        answer_callback(
            callback_id,
            "عضویتت تأیید شد! حالا می‌تونی از ربات استفاده کنی."
        )

    send_message(
        chat_id,
        "✅ عضویتت تأیید شد!\n"
        "حالا می‌تونی از منوی ربات استفاده کنی."
    )

    return True
