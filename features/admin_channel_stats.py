
"""Admin statistics and management for registered Bale channels."""

from database import get_connection
from features import admin_panel


BTN_CHANNEL_STATS = "📊 آمار و وضعیت کانال‌ها"

PAGE_SIZE = 8

MEMBER_STATUSES = {
    "creator",
    "administrator",
    "owner",
    "member",
}


def _inline_keyboard(rows):
    return {"inline_keyboard": rows}


def _is_member(member):
    status = (member or {}).get("status")

    if status in MEMBER_STATUSES:
        return True

    return (
        status == "restricted"
        and bool((member or {}).get("is_member"))
    )


def _is_admin(member):
    return (member or {}).get("status") in {
        "creator",
        "administrator",
        "owner",
    }


def _has_required_permissions(member):
    """Use the same permission requirements as partner channel registration."""
    if not _is_admin(member):
        return False

    # Creator has full channel control.
    if (member or {}).get("status") in {"creator", "owner"}:
        return True

    return all(
        member.get(permission) is not False
        for permission in (
            "can_post_messages",
            "can_edit_messages",
            "can_delete_messages",
        )
    )


def _get_bot_id(api):
    result = api("getMe", {})

    if not result or not result.get("ok"):
        return None

    return result.get("result", {}).get("id")


def _get_channel_status(api, channel_ref, bot_id):
    """
    Return real API status.
    Unknown API results are kept unknown instead of being called inactive.
    """
    if not bot_id:
        return {
            "checkable": False,
            "member": None,
            "admin": None,
            "active": None,
            "title": None,
            "chat_id": None,
            "username": None,
        }

    chat_result = api("getChat", {"chat_id": channel_ref})

    if not chat_result or not chat_result.get("ok"):
        return {
            "checkable": False,
            "member": None,
            "admin": None,
            "active": None,
            "title": None,
            "chat_id": None,
            "username": None,
        }

    chat = chat_result.get("result", {})

    member_result = api("getChatMember", {
        "chat_id": chat.get("id"),
        "user_id": bot_id,
    })

    if not member_result or not member_result.get("ok"):
        return {
            "checkable": False,
            "member": None,
            "admin": None,
            "active": None,
            "title": chat.get("title"),
            "chat_id": chat.get("id"),
            "username": chat.get("username"),
        }

    member = member_result.get("result", {})

    return {
        "checkable": True,
        "member": _is_member(member),
        "admin": _is_admin(member),
        "active": _has_required_permissions(member),
        "title": chat.get("title"),
        "chat_id": chat.get("id"),
        "username": chat.get("username"),
    }


def _load_partner_channels():
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
                COALESCE(u.username, '') AS owner_username
            FROM partner_channels pc
            LEFT JOIN users u ON u.user_id = pc.owner_id
            ORDER BY pc.id DESC
        """).fetchall()

    return [dict(row) for row in rows]


def _load_force_join_channels():
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT id, username, title
            FROM force_join_channels
            ORDER BY id
        """).fetchall()

    return [dict(row) for row in rows]


def _registered_channel_refs():
    """
    Check channels already stored by the bot.
    Bale's Bot API does not provide a complete list of every channel
    the bot belongs to.
    """
    refs = {}

    for channel in _load_partner_channels():
        key = f"partner:{channel['id']}"
        refs[key] = channel.get("chat_id")

    for channel in _load_force_join_channels():
        key = f"force_join:{channel['id']}"
        refs[key] = f"@{channel['username']}"

    return refs


def _collect_statistics(api):
    partners = _load_partner_channels()
    registered_refs = _registered_channel_refs()
    bot_id = _get_bot_id(api)

    member_count = 0
    admin_count = 0
    active_count = 0
    unknown_count = 0

    for channel_ref in registered_refs.values():
        status = _get_channel_status(api, channel_ref, bot_id)

        if not status["checkable"]:
            unknown_count += 1
            continue

        if status["member"]:
            member_count += 1

        if status["admin"]:
            admin_count += 1

        if status["active"]:
            active_count += 1

    active_partner_count = sum(
        1 for channel in partners
        if channel.get("status") == "active"
    )

    text = (
        "📊 آمار کانال‌های ثبت‌شده\n\n"
        f"🤝 کل کانال‌های همکار: {len(partners):,}\n"
        f"✅ همکارهای فعال در دیتابیس: {active_partner_count:,}\n"
        f"📋 کانال‌های جوین اجباری: "
        f"{len(_load_force_join_channels()):,}\n\n"
        "🔎 وضعیت واقعی ربات در کانال‌های ثبت‌شده:\n"
        f"👤 عضو: {member_count:,}\n"
        f"👮 ادمین: {admin_count:,}\n"
        f"🟢 دارای دسترسی‌های لازم: {active_count:,}\n"
        f"❔ قابل بررسی نبود: {unknown_count:,}\n\n"
        "نکته: این آمار مربوط به کانال‌های ثبت‌شده در دیتابیس است، "
        "نه تمام کانال‌هایی که ربات ممکن است در آن‌ها عضو باشد."
    )

    return text


def _home_keyboard():
    return _inline_keyboard([
        [{"text": "🤝 فهرست کانال‌های همکار",
          "callback_data": "acs:list:0"}],
        [{"text": "🔒 فهرست جوین اجباری",
          "callback_data": "acs:force:0"}],
        [{"text": "🔄 به‌روزرسانی آمار",
          "callback_data": "acs:home"}],
        [{"text": "🔙 بازگشت به پنل",
          "callback_data": "acs:panel"}],
    ])


def _list_keyboard(channels, page, category="partner"):
    start = page * PAGE_SIZE
    current = channels[start:start + PAGE_SIZE]
    rows = []

    for channel in current:
        if category == "partner":
            channel_id = channel["id"]
            title = (
                channel.get("title")
                or channel.get("username")
                or str(channel.get("chat_id"))
            )
            status = channel.get("status") or "نامشخص"
            label = f"📢 {title} | {status}"

            rows.append([{
                "text": label[:60],
                "callback_data": f"acs:detail:{channel_id}:{page}",
            }])
        else:
            username = channel.get("username") or "بدون یوزرنیم"
            title = channel.get("title") or username

            rows.append([{
                "text": f"🔒 {title} (@{username})"[:60],
                "callback_data": f"acs:force_detail:{channel['id']}:{page}",
            }])

    nav = []

    if page > 0:
        nav.append({
            "text": "⬅️ قبلی",
            "callback_data": f"acs:{'list' if category == 'partner' else 'force'}:{page - 1}",
        })

    if start + PAGE_SIZE < len(channels):
        nav.append({
            "text": "بعدی ➡️",
            "callback_data": f"acs:{'list' if category == 'partner' else 'force'}:{page + 1}",
        })

    if nav:
        rows.append(nav)

    rows.append([{
        "text": "🔙 آمار کانال‌ها",
        "callback_data": "acs:home",
    }])

    return _inline_keyboard(rows)


def _partner_detail(channel, api):
    bot_id = _get_bot_id(api)
    status = _get_channel_status(
        api,
        channel.get("chat_id"),
        bot_id,
    )

    owner_username = (channel.get("owner_username") or "").strip()

    if owner_username:
        owner_text = f"@{owner_username.lstrip('@')}"
    else:
        owner_text = str(channel.get("owner_id"))

    title = (
        channel.get("title")
        or channel.get("username")
        or str(channel.get("chat_id"))
    )

    if not status["checkable"]:
        member_text = "❔ قابل بررسی نیست"
        admin_text = "❔ قابل بررسی نیست"
        active_text = "❔ قابل بررسی نیست"
    else:
        member_text = "بله" if status["member"] else "خیر"
        admin_text = "بله" if status["admin"] else "خیر"
        active_text = "بله" if status["active"] else "خیر"

    database_status = channel.get("status") or "نامشخص"

    text = (
        f"📢 جزئیات کانال همکار\n\n"
        f"🏷 نام: {title}\n"
        f"🆔 آیدی کانال: {channel.get('chat_id')}\n"
        f"👤 مالک: {owner_text}\n"
        f"🆔 آیدی عددی مالک: {channel.get('owner_id')}\n"
        f"📌 وضعیت ثبت در ربات: {database_status}\n\n"
        "🔎 وضعیت واقعی ربات در کانال:\n"
        f"👥 عضو کانال است: {member_text}\n"
        f"👮 ادمین کانال است: {admin_text}\n"
        f"🟢 مجوز ارسال، ویرایش و حذف دارد: {active_text}\n\n"
        "وضعیت «فعال» در دیتابیس به‌تنهایی به معنی داشتن "
        "دسترسی‌های لازم در حال حاضر نیست."
    )

    keyboard = _inline_keyboard([
        [{
            "text": "🗑 حذف از فهرست همکار",
            "callback_data": f"acs:confirm_delete:{channel['id']}",
        }],
        [{
            "text": "🔙 فهرست کانال‌های همکار",
            "callback_data": "acs:list:0",
        }],
    ])

    return text, keyboard


def _force_join_detail(channel, api):
    bot_id = _get_bot_id(api)
    status = _get_channel_status(
        api,
        f"@{channel['username']}",
        bot_id,
    )

    if not status["checkable"]:
        member_text = "❔ قابل بررسی نیست"
        admin_text = "❔ قابل بررسی نیست"
        active_text = "❔ قابل بررسی نیست"
    else:
        member_text = "بله" if status["member"] else "خیر"
        admin_text = "بله" if status["admin"] else "خیر"
        active_text = "بله" if status["active"] else "خیر"

    title = channel.get("title") or channel["username"]

    text = (
        "🔒 جزئیات کانال جوین اجباری\n\n"
        f"🏷 نام: {title}\n"
        f"🔗 یوزرنیم: @{channel['username']}\n\n"
        "🔎 وضعیت ربات:\n"
        f"👥 عضو کانال است: {member_text}\n"
        f"👮 ادمین کانال است: {admin_text}\n"
        f"🟢 مجوزهای لازم را دارد: {active_text}"
    )

    keyboard = _inline_keyboard([
        [{
            "text": "🔙 فهرست جوین اجباری",
            "callback_data": "acs:force:0",
        }],
    ])

    return text, keyboard


def _edit_or_send(api, send_message, chat_id, message_id, text, keyboard):
    if message_id is not None:
        result = api("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": keyboard,
        })

        if result and result.get("ok"):
            return result

    return send_message(chat_id, text, keyboard)


def handle_message(message, api, send_message):
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return False

    if not admin_panel.is_admin(user_id):
        return False

    if chat.get("type") != "private":
        return False

    if text != BTN_CHANNEL_STATS:
        return False

    stats_text = _collect_statistics(api)
    send_message(chat_id, stats_text, _home_keyboard())
    return True


def _delete_partner_channel(channel_id):
    """
    Mirror the existing user-side channel removal behavior.
    Reward/earning rows are removed before the partner channel row
    to respect the database foreign keys.
    """
    with get_connection() as conn:
        channel = conn.execute("""
            SELECT id, owner_id, chat_id, title, username
            FROM partner_channels
            WHERE id = ?
            LIMIT 1
        """, (int(channel_id),)).fetchone()

        if not channel:
            return False, None

        conn.execute("""
            DELETE FROM partner_order_rewards
            WHERE channel_id = ?
        """, (channel_id,))

        conn.execute("""
            DELETE FROM partner_earnings
            WHERE channel_id = ?
        """, (channel_id,))

        conn.execute("""
            DELETE FROM partner_channels
            WHERE id = ?
        """, (channel_id,))

    return True, dict(channel)


def handle_callback(callback, api, send_message, answer_callback):
    data = callback.get("data", "")
    callback_id = callback.get("id")
    user_id = callback.get("from", {}).get("id")
    message = callback.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    message_id = message.get("message_id")

    if not data.startswith("acs:"):
        return False

    if not user_id or not admin_panel.is_admin(user_id):
        if callback_id:
            answer_callback(
                callback_id,
                "⛔ این دکمه فقط برای ادمین است.",
                show_alert=True,
            )
        return True

    if not chat_id:
        if callback_id:
            answer_callback(callback_id, "اطلاعات پیام دریافت نشد.")
        return True

    if callback_id:
        answer_callback(callback_id)

    if data == "acs:home":
        _edit_or_send(
            api,
            send_message,
            chat_id,
            message_id,
            _collect_statistics(api),
            _home_keyboard(),
        )
        return True

    if data == "acs:panel":
        keyboard = admin_panel.panel_keyboard()
        keyboard["keyboard"].append([{"text": BTN_CHANNEL_STATS}])
        send_message(chat_id, "🛠 پنل مدیریت ربات", keyboard)
        return True

    if data.startswith("acs:list:"):
        try:
            page = max(0, int(data.split(":")[2]))
        except (IndexError, ValueError):
            page = 0

        channels = _load_partner_channels()
        text = (
            f"🤝 فهرست کانال‌های همکار\n"
            f"تعداد ثبت‌شده: {len(channels):,}\n\n"
            "برای مشاهده جزئیات، یک کانال را انتخاب کن."
        )

        _edit_or_send(
            api,
            send_message,
            chat_id,
            message_id,
            text,
            _list_keyboard(channels, page, "partner"),
        )
        return True

    if data.startswith("acs:force:"):
        try:
            page = max(0, int(data.split(":")[2]))
        except (IndexError, ValueError):
            page = 0

        channels = _load_force_join_channels()
        text = (
            f"🔒 فهرست کانال‌های جوین اجباری\n"
            f"تعداد ثبت‌شده: {len(channels):,}\n\n"
            "برای مشاهده جزئیات، یک کانال را انتخاب کن."
        )

        _edit_or_send(
            api,
            send_message,
            chat_id,
            message_id,
            text,
            _list_keyboard(channels, page, "force"),
        )
        return True

    if data.startswith("acs:detail:"):
        try:
            _, _, _, channel_id, page = data.split(":")
            channel_id = int(channel_id)
            page = max(0, int(page))
        except (ValueError, TypeError):
            if callback_id:
                answer_callback(
                    callback_id,
                    "اطلاعات کانال نامعتبر است.",
                    show_alert=True,
                )
            return True

        channels = _load_partner_channels()
        channel = next(
            (item for item in channels if item["id"] == channel_id),
            None,
        )

        if not channel:
            _edit_or_send(
                api,
                send_message,
                chat_id,
                message_id,
                "❌ این کانال دیگر در فهرست وجود ندارد.",
                _list_keyboard(channels, page, "partner"),
            )
            return True

        detail_text, keyboard = _partner_detail(channel, api)
        _edit_or_send(
            api,
            send_message,
            chat_id,
            message_id,
            detail_text,
            keyboard,
        )
        return True

    if data.startswith("acs:force_detail:"):
        try:
            _, _, _, channel_id, page = data.split(":")
            channel_id = int(channel_id)
            page = max(0, int(page))
        except (ValueError, TypeError):
            return True

        channels = _load_force_join_channels()
        channel = next(
            (item for item in channels if item["id"] == channel_id),
            None,
        )

        if not channel:
            _edit_or_send(
                api,
                send_message,
                chat_id,
                message_id,
                "❌ این کانال دیگر در فهرست نیست.",
                _list_keyboard(channels, page, "force"),
            )
            return True

        detail_text, keyboard = _force_join_detail(channel, api)
        _edit_or_send(
            api,
            send_message,
            chat_id,
            message_id,
            detail_text,
            keyboard,
        )
        return True

    if data.startswith("acs:confirm_delete:"):
        try:
            channel_id = int(data.split(":")[2])
        except (IndexError, ValueError):
            return True

        channels = _load_partner_channels()
        channel = next(
            (item for item in channels if item["id"] == channel_id),
            None,
        )

        if not channel:
            _edit_or_send(
                api,
                send_message,
                chat_id,
                message_id,
                "❌ این کانال قبلاً حذف شده است.",
                _list_keyboard(channels, 0, "partner"),
            )
            return True

        title = (
            channel.get("title")
            or channel.get("username")
            or str(channel.get("chat_id"))
        )

        keyboard = _inline_keyboard([
            [{
                "text": "✅ بله، حذف شود",
                "callback_data": f"acs:delete:{channel_id}",
            }],
            [{
                "text": "❌ انصراف",
                "callback_data": "acs:list:0",
            }],
        ])

        _edit_or_send(
            api,
            send_message,
            chat_id,
            message_id,
            f"⚠️ حذف کانال از فهرست همکار؟\n\n"
            f"📢 {title}\n\n"
            "با حذف، این کانال دیگر سفارش جدید دریافت نمی‌کند. "
            "سوابق درآمد و پاداش ذخیره‌شده در جداول مربوط به کانال "
            "نیز مانند حذف از منوی کاربر پاک می‌شود.",
            keyboard,
        )
        return True

    if data.startswith("acs:delete:"):
        try:
            channel_id = int(data.split(":")[2])
        except (IndexError, ValueError):
            return True

        deleted, channel = _delete_partner_channel(channel_id)
        channels = _load_partner_channels()

        if deleted:
            text = (
                "✅ کانال از فهرست همکار حذف شد.\n\n"
                "مالک می‌تواند دوباره از بخش «📢 کانال همکار» "
                "آن را ثبت کند."
            )
        else:
            text = "❌ کانال پیدا نشد یا قبلاً حذف شده است."

        _edit_or_send(
            api,
            send_message,
            chat_id,
            message_id,
            text,
            _list_keyboard(channels, 0, "partner"),
        )
        return True

    return True
