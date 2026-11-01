
"""Admin statistics and management for partner channels."""

from database import get_connection
from features import admin_panel


BTN_CHANNEL_STATS = "📊 آمار و وضعیت کانال‌ها"

PAGE_SIZE = 15
_PREFIX = "acs:"

REQUIRED_PERMISSIONS = (
    "can_post_messages",
    "can_edit_messages",
    "can_delete_messages",
)


def _send(send_message, chat_id, text, keyboard=None):
    if keyboard:
        return send_message(chat_id, text, keyboard)
    return send_message(chat_id, text)


def _button(text, callback_data):
    return {
        "text": text,
        "callback_data": callback_data,
    }


def _inline_keyboard(rows):
    return {"inline_keyboard": rows}


def _get_channels():
    """Return registered partner channels without deleting any history."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                pc.id,
                pc.owner_id,
                pc.chat_id,
                pc.username,
                pc.title,
                pc.status,
                pc.created_at,
                u.username AS owner_username
            FROM partner_channels pc
            LEFT JOIN users u
                ON u.user_id = pc.owner_id
            WHERE pc.status != 'deleted'
            ORDER BY pc.id DESC
        """).fetchall()

    return [dict(row) for row in rows]


def _get_bot_id(api):
    try:
        result = api("getMe", {})
    except Exception:
        return None

    if not result or not result.get("ok"):
        return None

    return result.get("result", {}).get("id")


def _unknown_check(status):
    return {
        "checkable": False,
        "member": None,
        "is_admin": None,
        "permissions_ok": None,
        "active": None,
        "status": status,
    }


def _check_channel(api, channel, bot_id):
    """
    Check bot membership and permissions for one registered channel.

    Missing permission fields are treated as unknown, not as permission
    granted. Only verified permissions can make a channel active.
    """
    if not bot_id:
        return _unknown_check("اطلاعات ربات دریافت نشد")

    try:
        result = api("getChatMember", {
            "chat_id": channel["chat_id"],
            "user_id": bot_id,
        })
    except Exception:
        return _unknown_check("وضعیت قابل بررسی نیست")

    if not result or not result.get("ok"):
        return _unknown_check("وضعیت قابل بررسی نیست")

    member_info = result.get("result") or {}
    member_status = member_info.get("status")

    is_member = member_status in (
        "creator",
        "owner",
        "administrator",
        "member",
        "restricted",
    )

    is_admin = member_status in (
        "creator",
        "owner",
        "administrator",
    )

    if not is_member:
        return {
            "checkable": True,
            "member": False,
            "is_admin": False,
            "permissions_ok": False,
            "active": False,
            "status": "ربات عضو کانال نیست",
        }

    if not is_admin:
        return {
            "checkable": True,
            "member": True,
            "is_admin": False,
            "permissions_ok": False,
            "active": False,
            "status": "ربات ادمین نیست",
        }

    # سازندهٔ کانال دسترسی کامل دارد.
    if member_status in ("creator", "owner"):
        permissions_ok = True
    else:
        permission_values = [
            member_info.get(permission)
            for permission in REQUIRED_PERMISSIONS
        ]

        # وجود حتی یک مجوز صریحاً غیرفعال یعنی دسترسی‌ها کامل نیستند.
        if any(value is False for value in permission_values):
            permissions_ok = False

        # فقط وقتی تمام مجوزها صریحاً True باشند، دسترسی تأیید می‌شود.
        elif all(value is True for value in permission_values):
            permissions_ok = True

        # فیلد مفقود یا None به معنی مجوز داشتن نیست.
        else:
            permissions_ok = None

    if permissions_ok is True:
        active = True
        status_text = "فعال"
    elif permissions_ok is False:
        active = False
        status_text = "دسترسی‌های لازم کامل نیست"
    else:
        active = None
        status_text = "مجوزها از API قابل تأیید نیستند"

    return {
        "checkable": True,
        "member": True,
        "is_admin": True,
        "permissions_ok": permissions_ok,
        "active": active,
        "status": status_text,
    }


def _yes_no(value):
    if value is True:
        return "✅ بله"
    if value is False:
        return "❌ خیر"
    return "⚠️ قابل بررسی نیست"


def _channel_name(channel):
    return (
        channel.get("title")
        or channel.get("username")
        or str(channel.get("chat_id"))
    )


def _owner_name(channel):
    username = channel.get("owner_username")

    if username:
        username = str(username).strip().lstrip("@")
        if username:
            return "@" + username

    return str(channel.get("owner_id", "نامشخص"))


def _make_summary(api, channels):
    bot_id = _get_bot_id(api)

    total = len(channels)
    registered_members = 0
    admin_channels = 0
    active_channels = 0
    unchecked_channels = 0

    statuses = {}

    for channel in channels:
        check = _check_channel(api, channel, bot_id)
        statuses[channel["id"]] = check

        # اگر وضعیت نهایی یا بررسی API نامشخص باشد، آن را
        # بررسی‌نشده حساب می‌کنیم؛ ولی اطلاعات معلوم را نگه می‌داریم.
        if not check["checkable"] or check["active"] is None:
            unchecked_channels += 1

        if check["member"] is True:
            registered_members += 1

        if check["is_admin"] is True:
            admin_channels += 1

        if check["active"] is True:
            active_channels += 1

    return {
        "total": total,
        "members": registered_members,
        "admins": admin_channels,
        "active": active_channels,
        "unchecked": unchecked_channels,
        "statuses": statuses,
    }


def _stats_text(summary):
    return (
        "📊 آمار کانال‌های همکار\n\n"
        f"📢 کل کانال‌های ثبت‌شده: {summary['total']}\n"
        f"👤 ربات عضو کانال‌ها: {summary['members']}\n"
        f"🛡️ ربات ادمین کانال‌ها: {summary['admins']}\n"
        f"✅ کانال‌های فعال: {summary['active']}\n"
        f"⚠️ کانال‌های بررسی‌نشده: {summary['unchecked']}\n\n"
        "کانال فعال یعنی ربات ادمین باشد و دسترسی‌های لازم "
        "برای ارسال، ویرایش و حذف پیام تأیید شده باشند.\n"
        "وضعیت نامشخص به معنی غیرفعال بودن قطعی نیست.\n"
        "برای دیدن جزئیات، یکی از کانال‌ها را انتخاب کن."
    )


def _list_keyboard(channels, page, statuses):
    rows = []

    start = page * PAGE_SIZE
    end = start + PAGE_SIZE
    page_channels = channels[start:end]

    for channel in page_channels:
        check = statuses.get(channel["id"], {})
        active = check.get("active")

        if active is True:
            icon = "✅"
        elif active is False:
            icon = "❌"
        else:
            icon = "⚠️"

        title = _channel_name(channel)
        button_text = f"{icon} {title}"[:60]

        rows.append([
            _button(
                button_text,
                f"{_PREFIX}detail:{channel['id']}:{page}",
            )
        ])

    navigation = []

    if page > 0:
        navigation.append(
            _button("⬅️ صفحه قبل", f"{_PREFIX}list:{page - 1}")
        )

    if end < len(channels):
        navigation.append(
            _button("صفحه بعد ➡️", f"{_PREFIX}list:{page + 1}")
        )

    if navigation:
        rows.append(navigation)

    rows.append([
        _button("🔄 به‌روزرسانی آمار", f"{_PREFIX}list:{page}")
    ])

    return _inline_keyboard(rows)


def _show_list(chat_id, page, api, send_message):
    channels = _get_channels()

    if not channels:
        _send(
            send_message,
            chat_id,
            "📊 هنوز کانال همکاری ثبت نشده است.",
            _inline_keyboard([
                [_button("🔄 به‌روزرسانی", f"{_PREFIX}list:0")]
            ]),
        )
        return

    max_page = max(0, (len(channels) - 1) // PAGE_SIZE)
    page = max(0, min(page, max_page))

    summary = _make_summary(api, channels)

    text = _stats_text(summary)
    text += f"\n\nصفحه {page + 1} از {max_page + 1}"

    _send(
        send_message,
        chat_id,
        text,
        _list_keyboard(channels, page, summary["statuses"]),
    )


def _show_detail(chat_id, channel_id, page, api, send_message):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT
                pc.id,
                pc.owner_id,
                pc.chat_id,
                pc.username,
                pc.title,
                pc.status,
                pc.created_at,
                u.username AS owner_username
            FROM partner_channels pc
            LEFT JOIN users u
                ON u.user_id = pc.owner_id
            WHERE pc.id = ?
              AND pc.status != 'deleted'
            LIMIT 1
        """, (channel_id,)).fetchone()

    if not row:
        _send(
            send_message,
            chat_id,
            "❌ این کانال دیگر در فهرست کانال‌های همکار نیست.",
            _inline_keyboard([
                [_button("🔙 بازگشت به فهرست", f"{_PREFIX}list:{page}")]
            ]),
        )
        return

    channel = dict(row)
    bot_id = _get_bot_id(api)
    check = _check_channel(api, channel, bot_id)

    saved_status = channel.get("status") or "نامشخص"
    saved_status_text = (
        "ثبت‌شده"
        if saved_status == "active"
        else saved_status
    )

    channel_username = channel.get("username")
    if channel_username:
        channel_username = "@" + str(channel_username).lstrip("@")
    else:
        channel_username = "ندارد"

    active_value = check.get("active")

    if active_value is True:
        active_text = "✅ فعال"
    elif active_value is False:
        active_text = "❌ غیرفعال"
    else:
        active_text = "⚠️ وضعیت قابل بررسی نیست"

    text = (
        "📋 جزئیات کانال همکار\n\n"
        f"📢 نام کانال: {_channel_name(channel)}\n"
        f"🔗 یوزرنیم کانال: {channel_username}\n"
        f"🆔 شناسه کانال: {channel['chat_id']}\n"
        f"👤 صاحب کانال: {_owner_name(channel)}\n"
        f"🆔 آیدی عددی صاحب کانال: {channel['owner_id']}\n\n"
        f"📌 وضعیت ذخیره‌شده: {saved_status_text}\n"
        f"👥 ربات عضو کانال است: {_yes_no(check.get('member'))}\n"
        f"🛡️ ربات ادمین است: {_yes_no(check.get('is_admin'))}\n"
        "🔑 دسترسی‌های لازم: "
        f"{_yes_no(check.get('permissions_ok'))}\n"
        f"📊 وضعیت نهایی: {active_text}\n"
        f"ℹ️ توضیح وضعیت: {check.get('status', 'نامشخص')}\n"
        f"🕒 تاریخ ثبت: {channel.get('created_at') or 'نامشخص'}\n"
    )

    rows = [
        [
            _button(
                "🗑 حذف از فهرست همکاران",
                f"{_PREFIX}confirm_delete:{channel_id}:{page}",
            )
        ],
        [
            _button(
                "🔄 بررسی دوباره",
                f"{_PREFIX}detail:{channel_id}:{page}",
            )
        ],
        [
            _button("🔙 بازگشت به فهرست", f"{_PREFIX}list:{page}")
        ],
    ]

    _send(send_message, chat_id, text, _inline_keyboard(rows))


def _confirm_delete(chat_id, channel_id, page, send_message):
    with get_connection() as conn:
        channel = conn.execute("""
            SELECT id, title, username, chat_id, owner_id
            FROM partner_channels
            WHERE id = ?
              AND status != 'deleted'
            LIMIT 1
        """, (channel_id,)).fetchone()

    if not channel:
        _send(
            send_message,
            chat_id,
            "❌ کانال پیدا نشد یا قبلاً از فهرست حذف شده است.",
            _inline_keyboard([
                [_button("🔙 بازگشت", f"{_PREFIX}list:{page}")]
            ]),
        )
        return

    channel = dict(channel)
    name = _channel_name(channel)

    text = (
        "⚠️ تأیید حذف کانال\n\n"
        f"📢 کانال: {name}\n"
        f"🆔 شناسه: {channel['chat_id']}\n\n"
        "کانال از فهرست انتشار سفارش‌های همکار حذف می‌شود.\n"
        "سوابق پاداش پاک نمی‌شوند. صاحب کانال می‌تواند بعداً "
        "از مسیر عادی دوباره آن را ثبت کند.\n\n"
        "حذف انجام شود؟"
    )

    _send(
        send_message,
        chat_id,
        text,
        _inline_keyboard([
            [
                _button(
                    "✅ بله، حذف شود",
                    f"{_PREFIX}delete:{channel_id}:{page}",
                ),
                _button(
                    "❌ انصراف",
                    f"{_PREFIX}detail:{channel_id}:{page}",
                ),
            ]
        ]),
    )


def _delete_channel(chat_id, channel_id, page, send_message):
    with get_connection() as conn:
        row = conn.execute("""
            SELECT id, title, username, chat_id
            FROM partner_channels
            WHERE id = ?
              AND status != 'deleted'
            LIMIT 1
        """, (channel_id,)).fetchone()

        if not row:
            _send(
                send_message,
                chat_id,
                "❌ این کانال قبلاً حذف شده یا پیدا نشد.",
                _inline_keyboard([
                    [_button("🔙 بازگشت", f"{_PREFIX}list:{page}")]
                ]),
            )
            return

        channel = dict(row)

        # حذف نرم: سوابق درآمد و پاداش‌ها حفظ می‌شوند.
        # انتشار سفارش‌ها فقط برای کانال‌های active انجام می‌شود.
        conn.execute("""
            UPDATE partner_channels
            SET status = 'deleted'
            WHERE id = ?
        """, (channel_id,))

    _send(
        send_message,
        chat_id,
        "✅ کانال از فهرست همکاران حذف شد.\n\n"
        f"📢 کانال: {_channel_name(channel)}\n"
        "سوابق پاداش حفظ شدند و صاحب کانال می‌تواند دوباره ثبتش کند.",
        _inline_keyboard([
            [_button("📋 بازگشت به فهرست", f"{_PREFIX}list:{page}")]
        ]),
    )


def handle_message(message, api, send_message):
    """Handle the admin's channel statistics menu button."""
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return False

    if chat.get("type") != "private":
        return False

    if text != BTN_CHANNEL_STATS:
        return False

    if not admin_panel.is_admin(user_id):
        _send(send_message, chat_id, "⛔ این بخش فقط برای ادمین است.")
        return True

    _show_list(chat_id, 0, api, send_message)
    return True


def handle_callback(callback, api, send_message, answer_callback):
    """Handle inline buttons for channel statistics and management."""
    data = callback.get("data") or ""

    if not data.startswith(_PREFIX):
        return False

    user = callback.get("from", {})
    user_id = user.get("id")
    callback_id = callback.get("id")

    message = callback.get("message", {})
    chat = message.get("chat", {})
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        if callback_id:
            answer_callback(
                callback_id,
                "❌ اطلاعات دکمه ناقص است.",
                show_alert=True,
            )
        return True

    if chat.get("type") != "private" or not admin_panel.is_admin(user_id):
        if callback_id:
            answer_callback(
                callback_id,
                "⛔ این دکمه فقط برای ادمین است.",
                show_alert=True,
            )
        return True

    if callback_id:
        answer_callback(callback_id)

    parts = data.split(":")

    try:
        action = parts[1]

        if action == "list" and len(parts) == 3:
            page = int(parts[2])
            _show_list(chat_id, page, api, send_message)
            return True

        if action == "detail" and len(parts) == 4:
            channel_id = int(parts[2])
            page = int(parts[3])
            _show_detail(
                chat_id,
                channel_id,
                page,
                api,
                send_message,
            )
            return True

        if action == "confirm_delete" and len(parts) == 4:
            channel_id = int(parts[2])
            page = int(parts[3])
            _confirm_delete(
                chat_id,
                channel_id,
                page,
                send_message,
            )
            return True

        if action == "delete" and len(parts) == 4:
            channel_id = int(parts[2])
            page = int(parts[3])
            _delete_channel(
                chat_id,
                channel_id,
                page,
                send_message,
            )
            return True

    except (TypeError, ValueError, IndexError):
        if callback_id:
            answer_callback(
                callback_id,
                "❌ اطلاعات دکمه نامعتبر است.",
                show_alert=True,
            )
        return True

    return True
