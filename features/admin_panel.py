
"""Button-based admin panel for BaleExchangeBot."""

from datetime import datetime, timedelta, timezone, time as datetime_time
from zoneinfo import ZoneInfo

from config import ADMIN_ID
from database import get_connection


TEHRAN = ZoneInfo("Asia/Tehran")

BTN_PANEL = "🛠 پنل مدیریت"
BTN_JOIN = "🔒 جوین اجباری"
BTN_ADD_CHANNEL = "➕ افزودن کانال جوین اجباری"
BTN_REMOVE_CHANNEL = "➖ حذف کانال جوین اجباری"
BTN_LIST_CHANNELS = "📋 کانال‌های جوین اجباری"

BTN_BROADCAST_USERS = "📨 همگانی در پیوی"
BTN_BROADCAST_CHANNEL = "📢 همگانی در کانال"

BTN_USER_STATS = "👥 آمار کاربران"
BTN_ORDER_STATS = "📊 آمار کلی سفارش‌ها"

BTN_ADMINS = "👮 ادمین‌ها"
BTN_ADD_ADMIN = "➕ افزودن ادمین"
BTN_REMOVE_ADMIN = "➖ حذف ادمین"
BTN_LIST_ADMINS = "📋 فهرست ادمین‌ها"

BTN_BAN = "🚫 بن کاربران"
BTN_BANNED = "📋 کاربران بن‌شده"
BTN_BAN_USER = "🚫 بن کردن کاربر"
BTN_UNBAN_USER = "✅ آنبن کردن کاربر"

BTN_BACK = "🔙 بازگشت"
BTN_CANCEL = "❌ لغو عملیات"

JOIN_CHECK = "admin_panel_join_check"


def init_admin_panel_db():
    """Create admin panel tables."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS panel_admins (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS panel_bans (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                banned_by INTEGER NOT NULL,
                banned_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS admin_panel_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS force_join_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                title TEXT,
                added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_panel_bans_user
                ON panel_bans(user_id);
        """)

        conn.execute(
            "INSERT OR IGNORE INTO panel_admins (user_id) VALUES (?)",
            (int(ADMIN_ID),)
        )


def is_admin(user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False

    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM panel_admins WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    return row is not None


def is_banned(user_id):
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return False

    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM panel_bans WHERE user_id = ?",
            (user_id,)
        ).fetchone()

    return row is not None


def set_state(user_id, state, payload=""):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO admin_panel_states (user_id, state, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state = excluded.state,
                payload = excluded.payload
        """, (int(user_id), state, payload or ""))


def get_state(user_id):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT state, payload
            FROM admin_panel_states
            WHERE user_id = ?
        """, (int(user_id),)).fetchone()

    if not row:
        return None, ""

    return row["state"], row["payload"] or ""


def clear_state(user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM admin_panel_states WHERE user_id = ?",
            (int(user_id),)
        )


def panel_keyboard():
    return {
        "keyboard": [
            [{"text": BTN_JOIN}],
            [{"text": BTN_BROADCAST_USERS}],
            [{"text": BTN_BROADCAST_CHANNEL}],
            [{"text": BTN_USER_STATS}, {"text": BTN_ORDER_STATS}],
            [{"text": BTN_ADMINS}, {"text": BTN_BAN}],
            [{"text": BTN_CANCEL}],
        ],
        "resize_keyboard": True
    }


def join_keyboard():
    return {
        "keyboard": [
            [{"text": BTN_ADD_CHANNEL}],
            [{"text": BTN_REMOVE_CHANNEL}],
            [{"text": BTN_LIST_CHANNELS}],
            [{"text": BTN_BACK}, {"text": BTN_CANCEL}],
        ],
        "resize_keyboard": True
    }


def admins_keyboard():
    return {
        "keyboard": [
            [{"text": BTN_ADD_ADMIN}, {"text": BTN_REMOVE_ADMIN}],
            [{"text": BTN_LIST_ADMINS}],
            [{"text": BTN_BACK}, {"text": BTN_CANCEL}],
        ],
        "resize_keyboard": True
    }


def bans_keyboard():
    return {
        "keyboard": [
            [{"text": BTN_BANNED}],
            [{"text": BTN_BAN_USER}, {"text": BTN_UNBAN_USER}],
            [{"text": BTN_BACK}, {"text": BTN_CANCEL}],
        ],
        "resize_keyboard": True
    }


def normalize_username(value):
    value = (value or "").strip()

    for prefix in ("https://ble.ir/", "https://bale.ai/"):
        if value.startswith(prefix):
            value = value[len(prefix):].split("/", 1)[0]

    if value.startswith("@"):
        value = value[1:]

    return value.strip()


def resolve_user_id(value):
    """Resolve numeric ID or username already known to the bot."""
    value = (value or "").strip()

    if value.isdigit():
        return int(value)

    username = normalize_username(value).lower()

    if not username:
        return None

    with get_connection() as conn:
        row = conn.execute("""
            SELECT user_id
            FROM users
            WHERE LOWER(REPLACE(username, '@', '')) = ?
            LIMIT 1
        """, (username,)).fetchone()

    return int(row["user_id"]) if row else None


def display_username(user_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT username FROM users WHERE user_id = ?",
            (int(user_id),)
        ).fetchone()

    username = row["username"] if row else None
    return f"@{username}" if username else f"آیدی {user_id}"


def add_admin(target_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT username FROM users WHERE user_id = ?",
            (int(target_id),)
        ).fetchone()

        conn.execute("""
            INSERT OR IGNORE INTO panel_admins (user_id, username)
            VALUES (?, ?)
        """, (
            int(target_id),
            row["username"] if row else None
        ))


def remove_admin(target_id):
    if int(target_id) == int(ADMIN_ID):
        return False

    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM panel_admins WHERE user_id = ?",
            (int(target_id),)
        )

    return result.rowcount > 0


def list_admins_text():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT a.user_id,
                   COALESCE(u.username, a.username) AS username
            FROM panel_admins a
            LEFT JOIN users u ON u.user_id = a.user_id
            ORDER BY a.user_id
        """).fetchall()

    if not rows:
        return "📭 فهرست ادمین‌ها خالی است."

    lines = ["👮 فهرست ادمین‌ها:\n"]

    for index, row in enumerate(rows, 1):
        username = (
            f"@{row['username']}"
            if row["username"]
            else "بدون یوزرنیم"
        )

        primary = (
            " ⭐ ادمین اصلی"
            if int(row["user_id"]) == int(ADMIN_ID)
            else ""
        )

        lines.append(
            f"{index}. {username}\n"
            f"   🆔 {row['user_id']}{primary}"
        )

    return "\n".join(lines)


def list_banned_text():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT b.user_id,
                   COALESCE(u.username, b.username) AS username,
                   b.banned_at
            FROM panel_bans b
            LEFT JOIN users u ON u.user_id = b.user_id
            ORDER BY b.banned_at DESC
            LIMIT 200
        """).fetchall()

    if not rows:
        return "✅ هیچ کاربری بن نیست."

    lines = ["🚫 کاربران بن‌شده:\n"]

    for row in rows:
        username = (
            f"@{row['username']}"
            if row["username"]
            else "بدون یوزرنیم"
        )

        lines.append(
            f"• {username} | آیدی: {row['user_id']}\n"
            f"  زمان بن: {row['banned_at']}"
        )

    return "\n".join(lines)


def ban_user(target_id, admin_id):
    if int(target_id) == int(ADMIN_ID):
        return False, "ادمین اصلی قابل بن شدن نیست."

    if is_admin(target_id):
        return False, "ابتدا دسترسی ادمین این کاربر را حذف کن."

    with get_connection() as conn:
        user = conn.execute(
            "SELECT username FROM users WHERE user_id = ?",
            (int(target_id),)
        ).fetchone()

        username = user["username"] if user else None

        conn.execute("""
            INSERT INTO panel_bans (user_id, username, banned_by)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                banned_by = excluded.banned_by,
                banned_at = CURRENT_TIMESTAMP
        """, (int(target_id), username, int(admin_id)))

    return True, "کاربر بن شد."


def unban_user(target_id):
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM panel_bans WHERE user_id = ?",
            (int(target_id),)
        )

    return result.rowcount > 0


def tehran_utc_bounds():
    """SQLite CURRENT_TIMESTAMP is UTC."""
    now = datetime.now(TEHRAN)

    today_local = datetime.combine(
        now.date(),
        datetime_time.min,
        tzinfo=TEHRAN
    )

    week_local = today_local - timedelta(days=6)

    today_utc = today_local.astimezone(timezone.utc).replace(tzinfo=None)
    week_utc = week_local.astimezone(timezone.utc).replace(tzinfo=None)

    return (
        today_utc.strftime("%Y-%m-%d %H:%M:%S"),
        week_utc.strftime("%Y-%m-%d %H:%M:%S")
    )


def count_table(table, today_start, week_start):
    """Count rows using indexed timestamp filters."""
    allowed_tables = {
        "users",
        "orders",
        "member_orders",
        "guaranteed_member_orders",
    }

    if table not in allowed_tables:
        raise ValueError("Invalid statistics table")

    with get_connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table}"
        ).fetchone()["n"]

        today = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE created_at >= ?",
            (today_start,)
        ).fetchone()["n"]

        week = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE created_at >= ?",
            (week_start,)
        ).fetchone()["n"]

    return {
        "today": today,
        "week": week,
        "total": total
    }


def user_stats_text():
    today, week = tehran_utc_bounds()
    stats = count_table("users", today, week)

    return (
        "👥 آمار کاربران ربات\n\n"
        f"📅 امروز: {stats['today']:,} کاربر\n"
        f"🗓️ ۷ روز اخیر: {stats['week']:,} کاربر\n"
        f"🌐 کل کاربران ثبت‌شده: {stats['total']:,} کاربر"
    )


def order_stats_text():
    today, week = tehran_utc_bounds()

    tables = [
        ("سین", "orders"),
        ("ممبر معمولی", "member_orders"),
        ("ممبر تضمینی", "guaranteed_member_orders"),
    ]

    results = {
        label: count_table(table, today, week)
        for label, table in tables
    }

    total_today = sum(item["today"] for item in results.values())
    total_week = sum(item["week"] for item in results.values())
    total_all = sum(item["total"] for item in results.values())

    lines = ["📊 آمار کلی سفارش‌ها\n"]

    for label, _table in tables:
        stats = results[label]

        lines.extend([
            f"🔹 {label}",
            f"   📅 امروز: {stats['today']:,}",
            f"   🗓️ ۷ روز اخیر: {stats['week']:,}",
            f"   🌐 کل: {stats['total']:,}\n",
        ])

    lines.extend([
        "━━━━━━━━━━━━━━",
        "📦 جمع کل سفارش‌ها",
        f"📅 امروز: {total_today:,}",
        f"🗓️ ۷ روز اخیر: {total_week:,}",
        f"🌐 کل: {total_all:,}",
    ])

    return "\n".join(lines)


def list_channels_text():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT username, title
            FROM force_join_channels
            ORDER BY id
        """).fetchall()

    if not rows:
        return "📭 هنوز کانالی برای جوین اجباری ثبت نشده."

    lines = ["📋 کانال‌های جوین اجباری:\n"]

    for index, row in enumerate(rows, 1):
        title = row["title"] or row["username"]
        lines.append(f"{index}. {title} — @{row['username']}")

    return "\n".join(lines)


def add_force_join_channel(username, title=None):
    username = normalize_username(username)

    if not username or any(char.isspace() for char in username):
        return False

    with get_connection() as conn:
        conn.execute("""
            INSERT INTO force_join_channels (username, title)
            VALUES (?, ?)
            ON CONFLICT(username) DO UPDATE SET
                title = COALESCE(excluded.title, force_join_channels.title)
        """, (username, title))

    return True


def remove_force_join_channel(username):
    username = normalize_username(username)

    with get_connection() as conn:
        result = conn.execute("""
            DELETE FROM force_join_channels
            WHERE LOWER(username) = LOWER(?)
        """, (username,))

    return result.rowcount > 0


def get_force_join_channels():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT username, title
            FROM force_join_channels
            ORDER BY id
        """).fetchall()

    return [dict(row) for row in rows]


def member_status(api, username, user_id):
    result = api("getChatMember", {
        "chat_id": f"@{username}",
        "user_id": int(user_id)
    })

    if not result or not result.get("ok"):
        return False

    member = result.get("result", {})
    status = member.get("status")

    return (
        status in ("creator", "administrator", "owner", "member")
        or (
            status == "restricted"
            and member.get("is_member", False)
        )
    )


def missing_join_channels(api, user_id):
    missing = []

    for channel in get_force_join_channels():
        if not member_status(api, channel["username"], user_id):
            missing.append(channel)

    return missing


def send_join_prompt(chat_id, send_message, channels):
    rows = []

    for channel in channels:
        username = channel["username"]
        title = channel.get("title") or f"عضویت در @{username}"

        rows.append([{
            "text": f"📢 {title}",
            "url": f"https://ble.ir/{username}"
        }])

    rows.append([{
        "text": "✅ بررسی عضویت",
        "callback_data": JOIN_CHECK
    }])

    send_message(
        chat_id,
        "🔒 برای استفاده از ربات، اول عضو همه کانال‌های زیر شو.\n\n"
        "بعد از عضویت، دکمه «بررسی عضویت» رو بزن.",
        {"inline_keyboard": rows}
    )


def check_join_access(user_id, chat_id, api, send_message):
    channels = get_force_join_channels()

    if not channels:
        return True

    missing = missing_join_channels(api, user_id)

    if missing:
        send_join_prompt(chat_id, send_message, missing)
        return False

    return True


def handle_callback(callback, api, send_message, answer_callback):
    if callback.get("data") != JOIN_CHECK:
        return False

    callback_id = callback.get("id")
    user_id = callback.get("from", {}).get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")

    if not user_id or not chat_id:
        if callback_id:
            answer_callback(callback_id, "اطلاعات کاربر دریافت نشد.")
        return True

    channels = get_force_join_channels()

    if not channels:
        if callback_id:
            answer_callback(callback_id, "جوین اجباری فعال نیست.")
        send_message(chat_id, "✅ فعلاً کانال اجباری ثبت نشده.")
        return True

    missing = missing_join_channels(api, user_id)

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
        answer_callback(callback_id, "✅ عضویت تأیید شد.")

    send_message(
        chat_id,
        "✅ عضویتت تأیید شد. حالا می‌تونی از ربات استفاده کنی."
    )

    return True


def handle_message(message, api, send_message, copy_message):
    """Handle admin panel menus and inputs."""
    user = message.get("from", {})
    chat = message.get("chat", {})

    user_id = user.get("id")
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()

    if not user_id or not chat_id:
        return False

    if not is_admin(user_id):
        return False

    state, payload = get_state(user_id)

    if text == BTN_CANCEL:
        clear_state(user_id)
        send_message(chat_id, "❌ عملیات لغو شد.", panel_keyboard())
        return True

    if text == BTN_BACK:
        clear_state(user_id)
        send_message(chat_id, "🏠 منوی پنل مدیریت", panel_keyboard())
        return True

    if text in ("/admin", BTN_PANEL):
        clear_state(user_id)
        send_message(chat_id, "🛠 پنل مدیریت ربات", panel_keyboard())
        return True

    if text == BTN_JOIN:
        clear_state(user_id)
        send_message(chat_id, "🔒 مدیریت جوین اجباری", join_keyboard())
        return True

    if text == BTN_ADMINS:
        clear_state(user_id)
        send_message(chat_id, "👮 مدیریت ادمین‌ها", admins_keyboard())
        return True

    if text == BTN_BAN:
        clear_state(user_id)
        send_message(chat_id, "🚫 مدیریت بن کاربران", bans_keyboard())
        return True

    if text == BTN_ADD_CHANNEL:
        set_state(user_id, "add_channel")
        send_message(
            chat_id,
            "آیدی کانال عمومی رو بفرست؛ مثلاً @MyChannel",
            join_keyboard()
        )
        return True

    if text == BTN_REMOVE_CHANNEL:
        set_state(user_id, "remove_channel")
        send_message(
            chat_id,
            "آیدی کانالی رو بفرست که می‌خوای حذف کنی.",
            join_keyboard()
        )
        return True

    if text == BTN_LIST_CHANNELS:
        send_message(chat_id, list_channels_text(), join_keyboard())
        return True

    if text == BTN_BROADCAST_USERS:
        set_state(user_id, "broadcast_users")
        send_message(
            chat_id,
            "📨 حالا پیام یا رسانه‌ای رو که می‌خوای برای کاربران بفرستی "
            "ارسال یا فوروارد کن.\n\n"
            "برای لغو، دکمه «❌ لغو عملیات» رو بزن."
        )
        return True

    if text == BTN_BROADCAST_CHANNEL:
        set_state(user_id, "broadcast_channel_target")
        send_message(
            chat_id,
            "آیدی کانال مقصد رو بفرست؛ مثلاً @MyChannel.",
            panel_keyboard()
        )
        return True

    if text == BTN_USER_STATS:
        send_message(chat_id, user_stats_text(), panel_keyboard())
        return True

    if text == BTN_ORDER_STATS:
        send_message(chat_id, order_stats_text(), panel_keyboard())
        return True

    if text == BTN_ADD_ADMIN:
        set_state(user_id, "add_admin")
        send_message(
            chat_id,
            "یوزرنیم یا آیدی عددی کاربر رو بفرست.",
            admins_keyboard()
        )
        return True

    if text == BTN_REMOVE_ADMIN:
        set_state(user_id, "remove_admin")
        send_message(
            chat_id,
            "یوزرنیم یا آیدی عددی ادمینی رو بفرست.",
            admins_keyboard()
        )
        return True

    if text == BTN_LIST_ADMINS:
        send_message(chat_id, list_admins_text(), admins_keyboard())
        return True

    if text == BTN_BANNED:
        send_message(chat_id, list_banned_text(), bans_keyboard())
        return True

    if text == BTN_BAN_USER:
        set_state(user_id, "ban_user")
        send_message(
            chat_id,
            "یوزرنیم یا آیدی عددی کاربر رو برای بن بفرست.",
            bans_keyboard()
        )
        return True

    if text == BTN_UNBAN_USER:
        set_state(user_id, "unban_user")
        send_message(
            chat_id,
            "یوزرنیم یا آیدی عددی کاربر رو برای آنبن بفرست.",
            bans_keyboard()
        )
        return True

    if not state:
        return False

    # ارسال همگانی خصوصی؛ copyMessage محتوا را به متن ساده تبدیل نمی‌کند.
    if state == "broadcast_users":
        source_message_id = message.get("message_id")

        if source_message_id is None:
            send_message(chat_id, "❌ پیام قابل ارسال نیست.")
            return True

        with get_connection() as conn:
            rows = conn.execute(
                "SELECT user_id FROM users ORDER BY user_id"
            ).fetchall()

        success = 0
        failed = 0

        for row in rows:
            result = copy_message(
                row["user_id"],
                chat_id,
                source_message_id
            )

            if result and result.get("ok"):
                success += 1
            else:
                failed += 1

        clear_state(user_id)

        send_message(
            chat_id,
            "✅ ارسال همگانی تمام شد.\n\n"
            f"📨 موفق: {success:,}\n"
            f"⚠️ ناموفق: {failed:,}",
            panel_keyboard()
        )
        return True

    if state == "broadcast_channel_target":
        target = text.strip()

        if not target:
            send_message(chat_id, "❌ آیدی کانال مقصد رو وارد کن.")
            return True

        set_state(user_id, "broadcast_channel_message", target)
        send_message(
            chat_id,
            "حالا پیام یا رسانه رو ارسال یا فوروارد کن تا در کانال کپی بشه."
        )
        return True

    if state == "broadcast_channel_message":
        target = payload.strip()
        source_message_id = message.get("message_id")

        if source_message_id is None:
            send_message(chat_id, "❌ پیام قابل ارسال نیست.")
            return True

        result = copy_message(target, chat_id, source_message_id)
        clear_state(user_id)

        if result and result.get("ok"):
            send_message(
                chat_id,
                "✅ پیام در کانال مقصد ارسال شد.",
                panel_keyboard()
            )
        else:
            send_message(
                chat_id,
                "❌ ارسال ناموفق بود. آیدی کانال و دسترسی ربات رو بررسی کن.",
                panel_keyboard()
            )

        return True

    if state in ("add_admin", "remove_admin", "ban_user", "unban_user"):
        target_id = resolve_user_id(text)

        if target_id is None:
            send_message(
                chat_id,
                "❌ کاربر پیدا نشد. اگر یوزرنیم در دیتابیس ربات نیست، "
                "آیدی عددی رو بفرست."
            )
            return True

        if state == "add_admin":
            add_admin(target_id)
            clear_state(user_id)

            send_message(
                chat_id,
                f"✅ {display_username(target_id)} ادمین شد.\n"
                f"🆔 {target_id}",
                admins_keyboard()
            )
            return True

        if state == "remove_admin":
            removed = remove_admin(target_id)
            clear_state(user_id)

            send_message(
                chat_id,
                "✅ ادمین حذف شد." if removed
                else "❌ ادمین پیدا نشد یا ادمین اصلی قابل حذف نیست.",
                admins_keyboard()
            )
            return True

        if state == "ban_user":
            ok, message_text = ban_user(target_id, user_id)
            clear_state(user_id)

            send_message(
                chat_id,
                f"{'✅' if ok else '⚠️'} {message_text}\n🆔 {target_id}",
                bans_keyboard()
            )
            return True

        if state == "unban_user":
            removed = unban_user(target_id)
            clear_state(user_id)

            send_message(
                chat_id,
                (
                    f"✅ {display_username(target_id)} آنبن شد.\n"
                    "کاربر می‌تونه دوباره از ربات استفاده کنه."
                ) if removed else "❌ این کاربر بن نبود.",
                bans_keyboard()
            )
            return True

    if state in ("add_channel", "remove_channel"):
        username = normalize_username(text)

        if not username or any(char.isspace() for char in username):
            send_message(chat_id, "❌ آیدی کانال معتبر نیست.")
            return True

        if state == "add_channel":
            result = api("getChat", {"chat_id": f"@{username}"})

            if not result or not result.get("ok"):
                send_message(
                    chat_id,
                    "❌ کانال پیدا نشد یا ربات به اون دسترسی نداره. "
                    "آیدی رو بررسی کن."
                )
                return True

            channel = result.get("result", {})
            actual_username = normalize_username(
                channel.get("username") or username
            )

            if not actual_username:
                send_message(
                    chat_id,
                    "❌ این قابلیت فعلاً برای کانال‌های عمومی با یوزرنیمه."
                )
                return True

            bot_result = api("getMe")
            bot_id = (bot_result or {}).get("result", {}).get("id")

            if not bot_id or not member_status(
                api,
                actual_username,
                bot_id
            ):
                send_message(
                    chat_id,
                    "❌ ربات نمی‌تونه عضویت کانال رو بررسی کنه. "
                    "دسترسی ربات به کانال رو بررسی کن."
                )
                return True

            add_force_join_channel(
                actual_username,
                channel.get("title")
            )

            clear_state(user_id)

            send_message(
                chat_id,
                f"✅ کانال @{actual_username} اضافه شد.",
                join_keyboard()
            )
            return True

        removed = remove_force_join_channel(username)
        clear_state(user_id)

        send_message(
            chat_id,
            f"✅ کانال @{username} حذف شد." if removed
            else f"❌ کانال @{username} در فهرست نبود.",
            join_keyboard()
        )
        return True

    return False
