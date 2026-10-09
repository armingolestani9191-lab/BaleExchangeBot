
import json
import re
import sqlite3
from datetime import datetime, timezone

from config import ORDER_CHANNEL
from database import get_connection


PRICE_PER_MEMBER = 10
FIRST_REWARD = 25
REWARD_PER_MEMBER = 3
LEAVE_PENALTY = 10
GUARANTEE_HOURS = 48
MAX_MEMBERS = 10000
REFUND_AFTER_LOSSES = 10

BOT_ID = None
BOT_USERNAME = None

COMPLETED_ORDER_MESSAGE = (
    "🎉 تبریک!\n\n"
    "سفارش ممبر تضمینی با موفقیت تکمیل شد!\n"
    "تمام اعضای درخواستی ثبت شدند."
)


def set_bot_info(bot_id, username):
    global BOT_ID, BOT_USERNAME
    BOT_ID = bot_id
    BOT_USERNAME = username


def init_guaranteed_db():
    """ساخت جدول‌های مستقل سفارش تضمینی و مهاجرت امن در صورت نیاز."""

    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS guaranteed_member_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS guaranteed_member_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                channel_username TEXT NOT NULL,
                target_count INTEGER NOT NULL,
                joined_count INTEGER NOT NULL DEFAULT 0,
                lost_count INTEGER NOT NULL DEFAULT 0,
                total_cost INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                refunded INTEGER NOT NULL DEFAULT 0,
                channel_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                refunded_at TEXT,
                FOREIGN KEY (owner_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS guaranteed_member_claims (
                order_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reward_amount INTEGER NOT NULL DEFAULT 3,
                membership_status TEXT NOT NULL DEFAULT 'active',
                penalty_applied INTEGER NOT NULL DEFAULT 0,
                left_at TEXT,
                PRIMARY KEY (order_id, user_id),
                FOREIGN KEY (order_id)
                    REFERENCES guaranteed_member_orders(id),
                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_guaranteed_orders_owner
            ON guaranteed_member_orders(owner_id);

            CREATE INDEX IF NOT EXISTS idx_guaranteed_orders_status
            ON guaranteed_member_orders(status);

            CREATE INDEX IF NOT EXISTS idx_guaranteed_claims_status
            ON guaranteed_member_claims(membership_status);
        """)


def _set_state(user_id, state, payload=None):
    payload = payload or {}

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO guaranteed_member_states (user_id, state, payload)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                state = excluded.state,
                payload = excluded.payload
            """,
            (user_id, state, json.dumps(payload))
        )


def _get_state(user_id):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT state, payload
            FROM guaranteed_member_states
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

    if not row:
        return None, {}

    try:
        payload = json.loads(row["payload"] or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}

    return row["state"], payload


def clear_state(user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM guaranteed_member_states WHERE user_id = ?",
            (user_id,)
        )


def _answer_callback(api, callback_id, text, show_alert=False):
    if not callback_id:
        return

    api("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text,
        "show_alert": show_alert
    })


def _error_description(result):
    if not isinstance(result, dict):
        return ""

    description = result.get("description", "")

    if isinstance(description, str):
        try:
            parsed = json.loads(description)
            if isinstance(parsed, dict):
                return str(parsed.get("description", description))
        except (json.JSONDecodeError, TypeError):
            pass

    return str(description)


def _check_bot_admin(api, channel_username):
    if not BOT_ID:
        return False

    result = api("getChatMember", {
        "chat_id": channel_username,
        "user_id": BOT_ID
    })

    if not result or not result.get("ok"):
        print("Guaranteed bot admin check failed:", result)
        return False

    status = result.get("result", {}).get("status", "")
    return status in ("administrator", "creator", "owner")


def _check_user_membership(api, channel_username, user_id):
    """
    True: عضویت تأیید شد.
    False: کاربر عضو نیست.
    None: بررسی به علت خطای نامشخص ممکن نشد.
    """

    chat_result = api("getChat", {
        "chat_id": channel_username
    })

    if not chat_result or not chat_result.get("ok"):
        print("Guaranteed channel check failed:", chat_result)
        return None

    result = api("getChatMember", {
        "chat_id": channel_username,
        "user_id": user_id
    })

    if not result or not result.get("ok"):
        description = _error_description(result).lower()
        http_status = result.get("http_status")

        if (
            http_status == 404
            and "no such group or user" in description
        ):
            return False

        print("Guaranteed membership check failed:", result)
        return None

    member = result.get("result", {})
    status = member.get("status", "")

    if status in ("creator", "administrator", "owner", "member"):
        return True

    if status == "restricted":
        return bool(member.get("is_member", False))

    if status in ("left", "kicked", "banned"):
        return False

    return False


def _order_keyboard(order):
    channel_name = order["channel_username"].lstrip("@")

    keyboard = [[
        {
            "text": "📢 عضویت در کانال",
            "url": f"https://ble.ir/{channel_name}"
        },
        {
            "text": "✅ عضو شدم",
            "callback_data": f"guaranteed_member_claim:{order['id']}"
        }
    ]]

    if BOT_USERNAME:
        keyboard.append([{
            "text": "🤖 رفتن به ربات",
            "url": f"https://ble.ir/{BOT_USERNAME}"
        }])

    return {"inline_keyboard": keyboard}


def _order_text(order):
    return (
        "🛡️ سفارش ممبر تضمینی\n\n"
        f"🔗 کانال: {order['channel_username']}\n"
        f"👥 تعداد درخواستی: {order['target_count']}\n"
        f"✅ عضویت‌های تأییدشده: {order['joined_count']}\n"
        f"📉 ریزش تأییدشده: {order['lost_count']}\n\n"
        f"🆔 سفارش: #{order['id']}\n"
        f"💰 قیمت هر ممبر: {PRICE_PER_MEMBER} سکه"
    )


def start_order(user_id, chat_id, send_message):
    _set_state(user_id, "waiting_channel")

    send_message(
        chat_id,
        "🛡️ ثبت سفارش ممبر تضمینی\n\n"
        "ابتدا ربات را در کانالی که می‌خواهی برایش ممبر بگیری "
        "ادمین کن.\n\n"
        "سپس آیدی کانال را بفرست:\n"
        "@channelusername\n\n"
        f"💰 قیمت هر ممبر: {PRICE_PER_MEMBER} سکه\n"
        f"🎁 پاداش اولین ممبر تأییدشده: {FIRST_REWARD} سکه\n"
        f"🎁 پاداش ممبرهای بعدی: {REWARD_PER_MEMBER} سکه\n"
        f"⏱️ مهلت بررسی تضمین: {GUARANTEE_HOURS} ساعت\n\n"
        "برای لغو مراحل بنویس /cancel"
    )


def handle_message(message, api, send_message):
    user = message.get("from", {})
    chat = message.get("chat", {})
    text = (message.get("text") or "").strip()

    user_id = user.get("id")
    chat_id = chat.get("id")

    if not user_id or not chat_id:
        return False

    state, payload = _get_state(user_id)

    if not state:
        return False

    if text == "/cancel":
        clear_state(user_id)
        send_message(chat_id, "❌ سفارش ممبر تضمینی لغو شد.")
        return True

    if state == "waiting_channel":
        if not re.fullmatch(r"@[A-Za-z0-9_]{5,32}", text):
            send_message(
                chat_id,
                "❌ آیدی کانال معتبر نیست.\n"
                "مثال: @channelusername"
            )
            return True

        if not _check_bot_admin(api, text):
            send_message(
                chat_id,
                "❌ ادمین بودن ربات در کانال تأیید نشد.\n"
                "آیدی کانال و دسترسی ربات را بررسی کن."
            )
            return True

        _set_state(
            user_id,
            "waiting_count",
            {"channel_username": text}
        )

        send_message(
            chat_id,
            "✅ دسترسی ربات تأیید شد.\n\n"
            f"🔗 کانال: {text}\n"
            f"💰 قیمت هر ممبر: {PRICE_PER_MEMBER} سکه\n\n"
            "چند ممبر می‌خواهی سفارش بدهی؟\n"
            f"حداکثر: {MAX_MEMBERS}"
        )
        return True

    if state == "waiting_count":
        try:
            count = int(text)
        except ValueError:
            send_message(chat_id, "❌ تعداد را با عدد وارد کن.")
            return True

        if not 1 <= count <= MAX_MEMBERS:
            send_message(
                chat_id,
                f"❌ تعداد باید بین ۱ تا {MAX_MEMBERS} باشد."
            )
            return True

        cost = count * PRICE_PER_MEMBER

        with get_connection() as conn:
            row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()

        coins = row["coins"] if row else 0

        if coins < cost:
            send_message(
                chat_id,
                "❌ موجودی سکه کافی نیست!\n\n"
                f"💰 هزینه سفارش: {cost} سکه\n"
                f"🪙 موجودی فعلی: {coins} سکه"
            )
            return True

        payload["target_count"] = count
        payload["total_cost"] = cost
        _set_state(user_id, "confirming", payload)

        keyboard = {
            "inline_keyboard": [[
                {
                    "text": "❌ لغو",
                    "callback_data": "guaranteed_member_cancel"
                },
                {
                    "text": "✅ تأیید سفارش",
                    "callback_data": "guaranteed_member_confirm"
                }
            ]]
        }

        send_message(
            chat_id,
            "🧾 تأیید سفارش ممبر تضمینی\n\n"
            f"🔗 کانال: {payload['channel_username']}\n"
            f"👥 تعداد: {count}\n"
            f"💰 هزینه کل: {cost} سکه\n\n"
            f"اگر بیش از {REFUND_AFTER_LOSSES} ممبر در مهلت تضمین "
            "از دست بروند، هزینه سفارش به‌طور کامل برمی‌گردد.\n\n"
            "سفارش را تأیید می‌کنی؟",
            keyboard
        )
        return True

    return True


def _confirm_order(user_id, callback, api, send_message):
    callback_id = callback.get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")

    state, payload = _get_state(user_id)

    if state != "confirming":
        _answer_callback(api, callback_id, "این مرحله منقضی شده.", True)
        return

    channel = payload.get("channel_username")
    count = payload.get("target_count")
    cost = payload.get("total_cost")

    if not channel or not count or not cost:
        clear_state(user_id)
        _answer_callback(api, callback_id, "اطلاعات سفارش نامعتبر است.", True)
        return

    if not _check_bot_admin(api, channel):
        _answer_callback(api, callback_id, "ادمین بودن ربات تأیید نشد.", True)
        return

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        state_row = conn.execute(
            """
            SELECT state
            FROM guaranteed_member_states
            WHERE user_id = ?
            """,
            (user_id,)
        ).fetchone()

        if not state_row or state_row["state"] != "confirming":
            _answer_callback(api, callback_id, "این سفارش قبلاً پردازش شده.", True)
            return

        balance_row = conn.execute(
            "SELECT coins FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        balance = balance_row["coins"] if balance_row else 0

        if balance < cost:
            _answer_callback(api, callback_id, "سکه کافی نیست.", True)
            return

        conn.execute(
            """
            UPDATE guaranteed_member_states
            SET state = 'processing'
            WHERE user_id = ?
            """,
            (user_id,)
        )

        conn.execute(
            "UPDATE users SET coins = coins - ? WHERE user_id = ?",
            (cost, user_id)
        )

        cursor = conn.execute(
            """
            INSERT INTO guaranteed_member_orders
            (owner_id, channel_username, target_count, total_cost, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (user_id, channel, count, cost)
        )

        order_id = cursor.lastrowid

    order = {
        "id": order_id,
        "channel_username": channel,
        "target_count": count,
        "joined_count": 0,
        "lost_count": 0
    }

    result = send_message(
        ORDER_CHANNEL,
        _order_text(order),
        _order_keyboard(order)
    )

    if not result or not result.get("ok"):
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            conn.execute(
                "UPDATE users SET coins = coins + ? WHERE user_id = ?",
                (cost, user_id)
            )

            conn.execute(
                """
                UPDATE guaranteed_member_orders
                SET status = 'failed', refunded = 1,
                    refunded_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (order_id,)
            )

        clear_state(user_id)
        _answer_callback(
            api, callback_id,
            "انتشار سفارش ناموفق بود؛ سکه‌ها برگشت داده شدند.",
            True
        )

        if chat_id:
            send_message(
                chat_id,
                "❌ سفارش منتشر نشد؛ سکه‌ها به کیف پولت برگشتند."
            )
        return

    message_id = result.get("result", {}).get("message_id")

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE guaranteed_member_orders
            SET channel_message_id = ?
            WHERE id = ?
            """,
            (message_id, order_id)
        )

    clear_state(user_id)
    _answer_callback(api, callback_id, "سفارش تضمینی ثبت شد.")

    if chat_id:
        send_message(
            chat_id,
            "✅ سفارش ممبر تضمینی ثبت شد!\n\n"
            f"🆔 شماره سفارش: #{order_id}\n"
            f"👥 تعداد: {count}\n"
            f"💰 هزینه: {cost} سکه"
        )


def _cancel_order(user_id, callback, api, send_message):
    callback_id = callback.get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")

    state, _ = _get_state(user_id)

    if state not in ("confirming", "waiting_channel", "waiting_count"):
        _answer_callback(api, callback_id, "این مرحله قبلاً تمام شده.", True)
        return

    clear_state(user_id)
    _answer_callback(api, callback_id, "سفارش لغو شد.")

    if chat_id:
        send_message(chat_id, "❌ سفارش ممبر تضمینی لغو شد.")


def _claim_member(user_id, callback, api, send_message):
    callback_id = callback.get("id")
    data = callback.get("data", "")

    try:
        order_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        _answer_callback(api, callback_id, "شماره سفارش نامعتبر است.", True)
        return

    with get_connection() as conn:
        order = conn.execute(
            """
            SELECT *
            FROM guaranteed_member_orders
            WHERE id = ?
            """,
            (order_id,)
        ).fetchone()

    if not order:
        _answer_callback(api, callback_id, "سفارش پیدا نشد.", True)
        return

    if order["owner_id"] == user_id:
        _answer_callback(api, callback_id, "نمی‌توانی از سفارش خودت پاداش بگیری.", True)
        return

    if order["status"] != "pending":
        _answer_callback(api, callback_id, "این سفارش فعال نیست.", True)
        return

    if order["joined_count"] >= order["target_count"]:
        _answer_callback(api, callback_id, "این سفارش تکمیل شده.", True)
        return

    membership = _check_user_membership(
        api,
        order["channel_username"],
        user_id
    )

    if membership is None:
        _answer_callback(
            api, callback_id,
            "بررسی عضویت ناموفق بود؛ کمی بعد دوباره تلاش کن.",
            True
        )
        return

    if membership is False:
        _answer_callback(
            api, callback_id,
            "هنوز عضو کانال نشدی! عضو شو و دوباره بزن.",
            True
        )
        return

    duplicate = False
    completed = False
    new_count = 0
    new_balance = 0
    reward = REWARD_PER_MEMBER

    user_info = callback.get("from", {})

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        current = conn.execute(
            """
            SELECT *
            FROM guaranteed_member_orders
            WHERE id = ?
            """,
            (order_id,)
        ).fetchone()

        if (
            not current
            or current["status"] != "pending"
            or current["joined_count"] >= current["target_count"]
        ):
            _answer_callback(api, callback_id, "این سفارش دیگر فعال نیست.", True)
            return

        conn.execute(
            """
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (
                user_id,
                user_info.get("username"),
                user_info.get("first_name")
            )
        )

        previous_claims = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM guaranteed_member_claims
            WHERE order_id = ?
            """,
            (order_id,)
        ).fetchone()["total"]

        reward = FIRST_REWARD if previous_claims == 0 else REWARD_PER_MEMBER

        try:
            conn.execute(
                """
                INSERT INTO guaranteed_member_claims
                    (order_id, user_id, reward_amount)
                VALUES (?, ?, ?)
                """,
                (order_id, user_id, reward)
            )
        except sqlite3.IntegrityError:
            duplicate = True

        if not duplicate:
            conn.execute(
                "UPDATE users SET coins = coins + ? WHERE user_id = ?",
                (reward, user_id)
            )

            conn.execute(
                """
                UPDATE guaranteed_member_orders
                SET joined_count = joined_count + 1
                WHERE id = ?
                """,
                (order_id,)
            )

            updated = conn.execute(
                """
                SELECT joined_count, target_count
                FROM guaranteed_member_orders
                WHERE id = ?
                """,
                (order_id,)
            ).fetchone()

            new_count = updated["joined_count"]
            completed = new_count >= updated["target_count"]

            if completed:
                conn.execute(
                    """
                    UPDATE guaranteed_member_orders
                    SET status = 'completed',
                        completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (order_id,)
                )

            new_balance = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()["coins"]

    if duplicate:
        _answer_callback(api, callback_id, "قبلاً برای این سفارش پاداش گرفتی.", True)
        return

    _answer_callback(
        api,
        callback_id,
        f"{reward} سکه پاداش گرفتی؛ موجودی: {new_balance}"
    )

    if completed:
        if order["channel_message_id"]:
            api("deleteMessage", {
                "chat_id": ORDER_CHANNEL,
                "message_id": order["channel_message_id"]
            })

        send_message(order["owner_id"], COMPLETED_ORDER_MESSAGE)

    elif order["channel_message_id"]:
        updated_order = {
            "id": order_id,
            "channel_username": order["channel_username"],
            "target_count": order["target_count"],
            "joined_count": new_count,
            "lost_count": order["lost_count"]
        }

        api("editMessageText", {
            "chat_id": ORDER_CHANNEL,
            "message_id": order["channel_message_id"],
            "text": _order_text(updated_order),
            "reply_markup": _order_keyboard(updated_order)
        })


def _parse_sqlite_datetime(value):
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.astimezone(timezone.utc)

    except (ValueError, TypeError):
        return None


def check_guaranteed_memberships(api, send_message):
    """
    باید از حلقه اصلی ربات به‌صورت دوره‌ای اجرا شود.

    اگر خروج قبل از ۴۸ ساعت تشخیص داده شود:
    - ۱۰ سکه از کاربر کم می‌شود.
    - ریزش سفارش یک واحد افزایش می‌یابد.
    - بعد از بیش از ۱۰ ریزش، هزینه کل سفارش یک بار برمی‌گردد.

    اگر عضویت بعد از ۴۸ ساعت هنوز برقرار باشد، بررسی آن claim
    خاتمه پیدا می‌کند.
    """

    now = datetime.now(timezone.utc)

    with get_connection() as conn:
        claims = conn.execute(
            """
            SELECT
                c.order_id,
                c.user_id,
                c.claimed_at,
                c.membership_status,
                c.penalty_applied,
                o.channel_username,
                o.owner_id,
                o.total_cost,
                o.refunded,
                o.channel_message_id,
                o.target_count,
                o.joined_count,
                o.lost_count
            FROM guaranteed_member_claims c
            JOIN guaranteed_member_orders o ON o.id = c.order_id
            WHERE c.membership_status = 'active'
            """
        ).fetchall()

    # تأیید دسترسی به هر کانال فقط یک بار در هر دور بررسی
    channel_cache = {}

    for claim in claims:
        claimed_at = _parse_sqlite_datetime(claim["claimed_at"])

        if not claimed_at:
            continue

        age_seconds = (now - claimed_at).total_seconds()
        within_guarantee = age_seconds < GUARANTEE_HOURS * 3600
        channel = claim["channel_username"]

        if channel not in channel_cache:
            chat_result = api("getChat", {"chat_id": channel})
            channel_cache[channel] = bool(
                chat_result and chat_result.get("ok")
            )

        if not channel_cache[channel]:
            # اگر خود کانال قابل بررسی نیست، کاربر را جریمه نکن.
            continue

        result = api("getChatMember", {
            "chat_id": channel,
            "user_id": claim["user_id"]
        })

        is_member = None

        if result and result.get("ok"):
            member = result.get("result", {})
            status = member.get("status", "")

            if status in ("creator", "administrator", "owner", "member"):
                is_member = True
            elif status == "restricted":
                is_member = bool(member.get("is_member", False))
            elif status in ("left", "kicked", "banned"):
                is_member = False

        else:
            description = _error_description(result).lower()
            http_status = result.get("http_status") if isinstance(result, dict) else None

            if (
                http_status == 404
                and "no such group or user" in description
            ):
                is_member = False
            else:
                # خطای نامشخص API نباید باعث جریمه شود.
                print(
                    "Guaranteed monitoring skipped:",
                    {
                        "order_id": claim["order_id"],
                        "user_id": claim["user_id"],
                        "response": result
                    }
                )
                continue

        # اگر هنوز عضو است و ۴۸ ساعت گذشته، دیگر نیازی به بررسی نیست.
        if is_member is True:
            if not within_guarantee:
                with get_connection() as conn:
                    conn.execute(
                        """
                        UPDATE guaranteed_member_claims
                        SET membership_status = 'expired'
                        WHERE order_id = ? AND user_id = ?
                          AND membership_status = 'active'
                        """,
                        (claim["order_id"], claim["user_id"])
                    )
            continue

        # خروج بعد از پایان مهلت، جریمه و بازپرداخت ایجاد نمی‌کند.
        # اگر اولین بار بعد از ۴۸ ساعت متوجه خروج شویم، زمان دقیق خروج
        # قابل اثبات نیست؛ پس جریمه اعمال نمی‌شود.
        if not within_guarantee:
            with get_connection() as conn:
                conn.execute(
                    """
                    UPDATE guaranteed_member_claims
                    SET membership_status = 'expired'
                    WHERE order_id = ? AND user_id = ?
                      AND membership_status = 'active'
                    """,
                    (claim["order_id"], claim["user_id"])
                )
            continue

        order_id = claim["order_id"]
        member_id = claim["user_id"]
        channel_name = claim["channel_username"]

        deducted = False
        refunded_now = False
        actual_balance = None
        new_lost_count = None
        refund_amount = claim["total_cost"]
        owner_id = claim["owner_id"]
        owner_chat = None

        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")

            current_claim = conn.execute(
                """
                SELECT membership_status, penalty_applied
                FROM guaranteed_member_claims
                WHERE order_id = ? AND user_id = ?
                """,
                (order_id, member_id)
            ).fetchone()

            if (
                not current_claim
                or current_claim["membership_status"] != "active"
                or current_claim["penalty_applied"]
            ):
                continue

            # ثبت خروج و جلوگیری از اعمال جریمه تکراری
            conn.execute(
                """
                UPDATE guaranteed_member_claims
                SET membership_status = 'left',
                    penalty_applied = 1,
                    left_at = CURRENT_TIMESTAMP
                WHERE order_id = ? AND user_id = ?
                """,
                (order_id, member_id)
            )

            conn.execute(
                "UPDATE users SET coins = coins - ? WHERE user_id = ?",
                (LEAVE_PENALTY, member_id)
            )

            balance_row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?",
                (member_id,)
            ).fetchone()

            actual_balance = balance_row["coins"] if balance_row else 0
            deducted = True

            conn.execute(
                """
                UPDATE guaranteed_member_orders
                SET lost_count = lost_count + 1
                WHERE id = ?
                """,
                (order_id,)
            )

            order_row = conn.execute(
                """
                SELECT lost_count, refunded, total_cost, owner_id,
                       channel_username, channel_message_id,
                       target_count, joined_count
                FROM guaranteed_member_orders
                WHERE id = ?
                """,
                (order_id,)
            ).fetchone()

            new_lost_count = order_row["lost_count"]
            owner_id = order_row["owner_id"]
            refund_amount = order_row["total_cost"]

            if (
                new_lost_count > REFUND_AFTER_LOSSES
                and not order_row["refunded"]
            ):
                conn.execute(
                    """
                    UPDATE users
                    SET coins = coins + ?
                    WHERE user_id = ?
                    """,
                    (refund_amount, owner_id)
                )

                conn.execute(
                    """
                    UPDATE guaranteed_member_orders
                    SET refunded = 1,
                        refunded_at = CURRENT_TIMESTAMP,
                        status = 'refunded'
                    WHERE id = ? AND refunded = 0
                    """,
                    (order_id,)
                )

                refunded_now = True

        if deducted:
            send_message(
                member_id,
                "⚠️ جریمه خروج از کانال\n\n"
                f"شما پیش از پایان مهلت {GUARANTEE_HOURS} ساعته "
                f"از کانال {channel_name} خارج شدی.\n"
                f"🪙 {LEAVE_PENALTY} سکه از موجودی‌ات کم شد.\n"
                f"💰 موجودی فعلی: {actual_balance} سکه"
            )

        if refunded_now:
            send_message(
                owner_id,
                "💰 بازپرداخت سفارش تضمینی\n\n"
                f"در سفارش #{order_id}، تعداد ممبرهای ازدست‌رفته "
                f"به {new_lost_count} نفر رسید.\n\n"
                f"کل هزینه سفارش، یعنی {refund_amount} سکه، "
                "به کیف پولت برگشت داده شد.\n"
                "این بازپرداخت فقط یک بار انجام می‌شود."
            )

        # اگر پیام سفارش هنوز در کانال وجود دارد، تعداد ریزش را به‌روز کن.
        if claim["channel_message_id"]:
            with get_connection() as conn:
                latest = conn.execute(
                    """
                    SELECT id, channel_username, target_count,
                           joined_count, lost_count, channel_message_id
                    FROM guaranteed_member_orders
                    WHERE id = ?
                    """,
                    (order_id,)
                ).fetchone()

            if latest and latest["channel_message_id"]:
                updated_order = {
                    "id": latest["id"],
                    "channel_username": latest["channel_username"],
                    "target_count": latest["target_count"],
                    "joined_count": latest["joined_count"],
                    "lost_count": latest["lost_count"]
                }

                api("editMessageText", {
                    "chat_id": ORDER_CHANNEL,
                    "message_id": latest["channel_message_id"],
                    "text": _order_text(updated_order),
                    "reply_markup": _order_keyboard(updated_order)
                })


def handle_callback_query(callback, api, send_message):
    data = callback.get("data", "")
    user_id = callback.get("from", {}).get("id")

    if not user_id or not data.startswith("guaranteed_member_"):
        return False

    if data == "guaranteed_member_confirm":
        _confirm_order(user_id, callback, api, send_message)

    elif data == "guaranteed_member_cancel":
        _cancel_order(user_id, callback, api, send_message)

    elif data.startswith("guaranteed_member_claim:"):
        _claim_member(user_id, callback, api, send_message)

    else:
        _answer_callback(
            api,
            callback.get("id"),
            "این دکمه شناخته نشد.",
            True
        )

    return True
