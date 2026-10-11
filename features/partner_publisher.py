```python
from database import get_connection


# پاداش صاحب کانال به ازای هر سفارش منتشرشده
PARTNER_REWARD_PER_ORDER = 5


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
    """ذخیرهٔ شناسهٔ هر دو پیام سفارش در یک کانال."""
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
    """گرفتن پیام‌های ثبت‌شدهٔ یک سفارش از تمام کانال‌ها."""
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


def reward_partner_channel(channel_chat_id, order_type, order_id):
    """
    دادن ۵ سکه به صاحب کانال فعال.
    برای هر سفارش و هر کانال فقط یک‌بار پاداش ثبت می‌شود.
    """
    try:
        channel_chat_id = int(channel_chat_id)
    except (TypeError, ValueError):
        return False

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

        # ابتدا رکورد پاداش ثبت می‌شود؛ محدودیت UNIQUE
        # جلوی پرداخت دوباره برای همین سفارش را می‌گیرد.
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
            PARTNER_REWARD_PER_ORDER,
        ))

        if result.rowcount != 1:
            conn.commit()
            return False

        # مطمئن شو صاحب کانال در جدول کاربران وجود دارد.
        conn.execute("""
            INSERT OR IGNORE INTO users (user_id, coins)
            VALUES (?, 0)
        """, (channel["owner_id"],))

        conn.execute("""
            UPDATE users
            SET coins = coins + ?
            WHERE user_id = ?
        """, (
            PARTNER_REWARD_PER_ORDER,
            channel["owner_id"],
        ))

        conn.commit()

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
    انتشار سفارش در کانال اصلی و کانال‌های همکار فعال.

    اگر انتشار در کانال اصلی ناموفق باشد، سفارش ناموفق اعلام می‌شود.
    خطای یک کانال همکار، انتشار در کانال‌های دیگر را متوقف نمی‌کند.
    """

    # ۱. انتشار پست اصلی در کانال سفارش‌ها
    main_post = api("forwardMessage", {
        "chat_id": main_channel_id,
        "from_chat_id": source_chat_id,
        "message_id": source_message_id,
    })

    if not main_post or not main_post.get("ok"):
        print("Partner publisher: main post failed:", main_post)
        return {"ok": False}

    main_post_id = (
        main_post.get("result", {}).get("message_id")
    )

    if not main_post_id:
        return {"ok": False}

    # ۲. انتشار پیام اطلاعات و دکمه‌های سفارش
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

    # ۳. ذخیرهٔ پیام‌های کانال اصلی
    save_order_message(
        order_id,
        main_channel_id,
        main_post_id,
        main_info_id,
        order_type,
    )

    # ۴. گرفتن کانال‌های همکار فعال
    with get_connection() as conn:
        partners = conn.execute("""
            SELECT chat_id
            FROM partner_channels
            WHERE status = 'active'
        """).fetchall()

    # ۵. انتشار در کانال‌های همکار
    for partner in partners:
        partner_chat_id = partner["chat_id"]

        # کانال اصلی نباید دوباره به عنوان همکار پردازش شود.
        if str(partner_chat_id) == str(main_channel_id):
            continue

        try:
            # کپی پست اصلی برای حفظ متن و رسانه
            copied_post = api("copyMessage", {
                "chat_id": partner_chat_id,
                "from_chat_id": main_channel_id,
                "message_id": main_post_id,
            })

            if not copied_post or not copied_post.get("ok"):
                print(
                    "Partner publisher: copy failed:",
                    partner_chat_id,
                    copied_post,
                )
                continue

            partner_post_id = (
                copied_post.get("result", {}).get("message_id")
            )

            if not partner_post_id:
                continue

            # پیام اطلاعات و همان دکمه‌های سفارش
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

            # پیام‌ها باید قبل از پاداش ذخیره شوند.
            save_order_message(
                order_id,
                partner_chat_id,
                partner_post_id,
                partner_info_id,
                order_type,
            )

            # پاداش فقط پس از انتشار موفق هر دو پیام داده می‌شود.
            reward_partner_channel(
                partner_chat_id,
                order_type,
                order_id,
            )

        except Exception as error:
            print(
                "Partner publisher: channel error:",
                partner_chat_id,
                error,
            )

    return {
        "ok": True,
        "channel_message_id": main_post_id,
        "info_message_id": main_info_id,
    }
```
