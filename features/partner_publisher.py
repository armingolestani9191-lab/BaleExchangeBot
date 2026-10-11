
from concurrent.futures import ThreadPoolExecutor

from database import get_connection


# استخر مشترک برای ویرایش و حذف هم‌زمان پیام‌ها
_MESSAGE_POOL = ThreadPoolExecutor(max_workers=12)


# مبلغ پاداش صاحب کانال برای هر نوع سفارش
PARTNER_REWARDS = {
    "views": 5,
    "members": 7,
    "guaranteed_members": 10,
}

# مبلغ پیش‌فرض برای سازگاری با سفارش‌های ناشناخته
PARTNER_REWARD_PER_ORDER = 5

# عنوان فارسی هر نوع سفارش
ORDER_TYPE_LABELS = {
    "views": "تبلیغ سین",
    "members": "تبلیغ ممبر معمولی",
    "guaranteed_members": "تبلیغ ممبر تضمینی",
}


def get_partner_reward(order_type):
    """تعیین مبلغ پاداش براساس نوع سفارش."""
    return PARTNER_REWARDS.get(
        str(order_type or "").strip(),
        PARTNER_REWARD_PER_ORDER,
    )


def get_order_type_label(order_type):
    """گرفتن عنوان فارسی نوع سفارش."""
    return ORDER_TYPE_LABELS.get(
        str(order_type or "").strip(),
        "تبلیغ",
    )


def init_tables():
    """ساخت جدول‌های انتشار سفارش و پاداش کانال‌های همکار."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS order_channel_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                post_message_id INTEGER,
                info_message_id INTEGER,
                order_type TEXT NOT NULL DEFAULT 'views',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_id, channel_id),
                FOREIGN KEY (order_id)
                    REFERENCES orders(id)
                    ON DELETE CASCADE
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_order_channel_messages_order
            ON order_channel_messages(order_id)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS partner_order_rewards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                order_type TEXT NOT NULL,
                order_id INTEGER NOT NULL,
                amount INTEGER NOT NULL DEFAULT 5,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(channel_id, order_type, order_id),
                FOREIGN KEY (channel_id)
                    REFERENCES partner_channels(id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_partner_order_rewards_channel
            ON partner_order_rewards(channel_id)
        """)


def save_order_message(
    order_id,
    channel_id,
    post_message_id,
    info_message_id,
    order_type="views",
):
    """ذخیره شناسه هر دو پیام سفارش در یک کانال."""
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO order_channel_messages (
                order_id,
                channel_id,
                post_message_id,
                info_message_id,
                order_type
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(order_id, channel_id)
            DO UPDATE SET
                post_message_id = excluded.post_message_id,
                info_message_id = excluded.info_message_id,
                order_type = excluded.order_type
        """, (
            order_id,
            str(channel_id),
            post_message_id,
            info_message_id,
            order_type,
        ))


def get_order_messages(order_id):
    """گرفتن پیام‌های ثبت‌شده یک سفارش از تمام کانال‌ها."""
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT
                channel_id,
                post_message_id,
                info_message_id,
                order_type
            FROM order_channel_messages
            WHERE order_id = ?
            ORDER BY id
        """, (order_id,)).fetchall()

    return [dict(row) for row in rows]


def delete_order_messages(order_id):
    """حذف اطلاعات پیام‌های یک سفارش از جدول."""
    with get_connection() as conn:
        conn.execute("""
            DELETE FROM order_channel_messages
            WHERE order_id = ?
        """, (order_id,))


def reward_partner_channel(
    channel_chat_id,
    order_type,
    order_id,
    api=None,
):
    """
    افزودن پاداش مناسب به حساب صاحب کانال همکار.
    برای هر کانال و سفارش فقط یک‌بار پاداش ثبت می‌شود.
    """
    try:
        channel_chat_id = int(channel_chat_id)
    except (TypeError, ValueError):
        return False

    reward_amount = get_partner_reward(order_type)
    order_label = get_order_type_label(order_type)
    owner_id = None

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        channel = conn.execute("""
            SELECT id, owner_id
            FROM partner_channels
            WHERE chat_id = ?
              AND status = 'active'
            LIMIT 1
        """, (channel_chat_id,)).fetchone()

        if not channel:
            conn.commit()
            return False

        owner_id = channel["owner_id"]

        result = conn.execute("""
            INSERT OR IGNORE INTO partner_order_rewards (
                channel_id,
                order_type,
                order_id,
                amount
            )
            VALUES (?, ?, ?, ?)
        """, (
            channel["id"],
            order_type,
            order_id,
            reward_amount,
        ))

        # اگر پاداش قبلاً ثبت شده، دوباره سکه اضافه نمی‌کنیم.
        if result.rowcount != 1:
            conn.commit()
            return False

        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, coins)
            VALUES (?, 0)
        """, (owner_id,))

        conn.execute("""
            UPDATE users
            SET coins = coins + ?
            WHERE user_id = ?
        """, (
            reward_amount,
            owner_id,
        ))

        conn.commit()

    # اطلاع‌رسانی خصوصی فقط برای صاحب کانال
    if api and owner_id:
        text = (
            "🎉 تبریک! پاداش شما واریز شد.\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📢 نوع سفارش: {order_label}\n"
            f"🧾 شماره سفارش: #{order_id}\n\n"
            f"💰 مبلغ واریزی: {reward_amount} سکه\n"
            "✅ وضعیت: واریز موفق\n\n"
            "🎁 این پاداش بابت انتشار موفق سفارش "
            "در کانال همکار شما پرداخت شد.\n\n"
            "❤️ از همکاری و همراهی شما سپاسگزاریم."
        )

        try:
            response = api("sendMessage", {
                "chat_id": owner_id,
                "text": text,
            })

            if not response or not response.get("ok"):
                print(
                    "Partner publisher: owner reward notification failed:",
                    owner_id,
                    response,
                )

        except Exception as error:
            print(
                "Partner publisher: owner notification exception:",
                owner_id,
                repr(error),
            )

    return True


def publish_order(
    api,
    order_id,
    source_chat_id,
    source_message_id,
    info_text,
    reply_markup,
    main_channel_id,
    order_type="views",
):
    """
    انتشار سفارش سین در کانال اصلی و کانال‌های همکار.
    پست منبع با forwardMessage ارسال می‌شود.
    """

    main_post = api("forwardMessage", {
        "chat_id": main_channel_id,
        "from_chat_id": source_chat_id,
        "message_id": source_message_id,
    })

    if not main_post or not main_post.get("ok"):
        print("Partner publisher: main post failed:", main_post)
        return {"ok": False}

    main_post_id = main_post.get("result", {}).get("message_id")

    if not main_post_id:
        return {"ok": False}

    main_info = api("sendMessage", {
        "chat_id": main_channel_id,
        "text": info_text,
        "reply_to_message_id": main_post_id,
        "reply_markup": reply_markup,
    })

    main_info_id = (
        main_info.get("result", {}).get("message_id")
        if main_info and main_info.get("ok")
        else None
    )

    if not main_info_id:
        api("deleteMessage", {
            "chat_id": main_channel_id,
            "message_id": main_post_id,
        })
        print("Partner publisher: main info failed:", main_info)
        return {"ok": False}

    save_order_message(
        order_id,
        main_channel_id,
        main_post_id,
        main_info_id,
        order_type,
    )

    with get_connection() as conn:
        partners = conn.execute("""
            SELECT chat_id
            FROM partner_channels
            WHERE status = 'active'
        """).fetchall()

    for partner in partners:
        partner_chat_id = partner["chat_id"]

        try:
            if int(partner_chat_id) == int(main_channel_id):
                continue
        except (TypeError, ValueError):
            pass

        try:
            partner_post = api("forwardMessage", {
                "chat_id": partner_chat_id,
                "from_chat_id": source_chat_id,
                "message_id": source_message_id,
            })

            if not partner_post or not partner_post.get("ok"):
                print(
                    "Partner publisher: forward failed:",
                    partner_chat_id,
                    partner_post,
                )
                continue

            partner_post_id = (
                partner_post.get("result", {}).get("message_id")
            )

            if not partner_post_id:
                continue

            partner_info = api("sendMessage", {
                "chat_id": partner_chat_id,
                "text": info_text,
                "reply_to_message_id": partner_post_id,
                "reply_markup": reply_markup,
            })

            partner_info_id = (
                partner_info.get("result", {}).get("message_id")
                if partner_info and partner_info.get("ok")
                else None
            )

            if not partner_info_id:
                api("deleteMessage", {
                    "chat_id": partner_chat_id,
                    "message_id": partner_post_id,
                })

                print(
                    "Partner publisher: info failed:",
                    partner_chat_id,
                    partner_info,
                )
                continue

            save_order_message(
                order_id,
                partner_chat_id,
                partner_post_id,
                partner_info_id,
                order_type,
            )

            reward_partner_channel(
                partner_chat_id,
                order_type,
                order_id,
                api=api,
            )

        except Exception as error:
            print(
                "Partner publisher: channel error:",
                partner_chat_id,
                repr(error),
            )

    return {
        "ok": True,
        "channel_message_id": main_post_id,
        "info_message_id": main_info_id,
    }


# ==========================================
# انتشار سفارش‌های متنی ممبر
# ==========================================

def _init_text_order_table():
    """جدول مستقل برای سفارش‌های ممبر."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS text_order_channel_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_type TEXT NOT NULL,
                order_id INTEGER NOT NULL,
                channel_id TEXT NOT NULL,
                info_message_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(order_type, order_id, channel_id)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_text_order_channel_messages_order
            ON text_order_channel_messages(order_type, order_id)
        """)


def _save_text_order_message(
    order_type,
    order_id,
    channel_id,
    message_id,
):
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO text_order_channel_messages (
                order_type,
                order_id,
                channel_id,
                info_message_id
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(order_type, order_id, channel_id)
            DO UPDATE SET
                info_message_id = excluded.info_message_id
        """, (
            order_type,
            order_id,
            str(channel_id),
            message_id,
        ))


def _get_text_order_messages(order_type, order_id):
    with get_connection() as conn:
        rows = conn.execute("""
            SELECT channel_id, info_message_id
            FROM text_order_channel_messages
            WHERE order_type = ?
              AND order_id = ?
            ORDER BY id
        """, (order_type, order_id)).fetchall()

    return [dict(row) for row in rows]


def _same_channel(first, second):
    first_text = str(first or "").strip().lower()
    second_text = str(second or "").strip().lower()

    if first_text.lstrip("@") == second_text.lstrip("@"):
        return True

    try:
        return int(first_text) == int(second_text)
    except (TypeError, ValueError):
        return False


def publish_text_order(
    api,
    order_id,
    info_text,
    reply_markup,
    main_channel_id,
    order_type,
):
    """انتشار سفارش متنی در کانال اصلی و کانال‌های همکار."""
    _init_text_order_table()

    main_result = api("sendMessage", {
        "chat_id": main_channel_id,
        "text": info_text,
        "reply_markup": reply_markup,
    })

    if not main_result or not main_result.get("ok"):
        print(
            "Partner publisher: main text order failed:",
            main_result,
        )
        return {"ok": False}

    main_message_id = main_result.get("result", {}).get("message_id")

    if not main_message_id:
        return {"ok": False}

    _save_text_order_message(
        order_type,
        order_id,
        main_channel_id,
        main_message_id,
    )

    with get_connection() as conn:
        partners = conn.execute("""
            SELECT chat_id
            FROM partner_channels
            WHERE status = 'active'
        """).fetchall()

    for partner in partners:
        partner_chat_id = partner["chat_id"]

        if _same_channel(partner_chat_id, main_channel_id):
            continue

        try:
            result = api("sendMessage", {
                "chat_id": partner_chat_id,
                "text": info_text,
                "reply_markup": reply_markup,
            })

            if not result or not result.get("ok"):
                print(
                    "Partner publisher: text order send failed:",
                    partner_chat_id,
                    result,
                )
                continue

            partner_message_id = (
                result.get("result", {}).get("message_id")
            )

            if not partner_message_id:
                continue

            _save_text_order_message(
                order_type,
                order_id,
                partner_chat_id,
                partner_message_id,
            )

            reward_partner_channel(
                partner_chat_id,
                order_type,
                order_id,
                api=api,
            )

        except Exception as error:
            print(
                "Partner publisher: text order channel error:",
                partner_chat_id,
                repr(error),
            )

    return {
        "ok": True,
        "result": {"message_id": main_message_id},
        "channel_message_id": main_message_id,
        "info_message_id": main_message_id,
    }


def edit_text_order_messages(
    api,
    order_id,
    order_type,
    text,
    reply_markup,
):
    """ویرایش پیام سفارش در تمام کانال‌های منتشرشده."""
    messages = _get_text_order_messages(order_type, order_id)

    if not messages:
        return 0

    def edit_one(item):
        return api("editMessageText", {
            "chat_id": item["channel_id"],
            "message_id": item["info_message_id"],
            "text": text,
            "reply_markup": reply_markup,
        })

    futures = [
        _MESSAGE_POOL.submit(edit_one, item)
        for item in messages
    ]

    results = []
    for future in futures:
        try:
            results.append(future.result())
        except Exception as error:
            results.append(None)
            print(
                "Partner publisher: text order edit exception:",
                repr(error),
            )

    for item, result in zip(messages, results):
        if not result or not result.get("ok"):
            print(
                "Partner publisher: text order edit failed:",
                item["channel_id"],
                result,
            )

    return len(messages)


def delete_text_order_messages(api, order_id, order_type):
    """حذف پیام سفارش از کانال‌ها و پاک‌کردن رکوردهای مربوطه."""
    messages = _get_text_order_messages(order_type, order_id)

    if not messages:
        return 0

    def delete_one(item):
        return api("deleteMessage", {
            "chat_id": item["channel_id"],
            "message_id": item["info_message_id"],
        })

    futures = [
        _MESSAGE_POOL.submit(delete_one, item)
        for item in messages
    ]

    results = []
    for future in futures:
        try:
            results.append(future.result())
        except Exception as error:
            results.append(None)
            print(
                "Partner publisher: text order delete exception:",
                repr(error),
            )

    for item, result in zip(messages, results):
        if not result or not result.get("ok"):
            print(
                "Partner publisher: text order delete failed:",
                item["channel_id"],
                result,
            )

    with get_connection() as conn:
        conn.execute("""
            DELETE FROM text_order_channel_messages
            WHERE order_type = ?
              AND order_id = ?
        """, (order_type, order_id))

    return len(messages)
