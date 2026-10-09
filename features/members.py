
import json
import re
import sqlite3

from config import ORDER_CHANNEL
from database import get_connection


PRICE_PER_MEMBER = 5
REWARD_PER_MEMBER = 3
MAX_MEMBERS = 10000

BOT_ID = None
BOT_USERNAME = None

COMPLETED_ORDER_MESSAGE = (
    "🎉 تبریک!\n\n"
    "سفارش ممبرت با موفقیت تکمیل شد!\n"
    "تمام اعضای درخواستی ثبت شدن.\n"
    "پیام سفارش از کانال حذف شد.\n\n"
    "💡 حالا می‌تونی:\n"
    "• 🪙 دوباره سکه جمع کنی\n"
    "• 👥 سفارش ممبر جدید ثبت کنی\n"
    "• 🚀 اگه سکه داری، همین الان سفارش بعدیت رو ثبت کن!\n\n"
    "❤️ ممنون که از ربات ما استفاده می‌کنی."
)


def set_bot_info(bot_id, username):
    global BOT_ID, BOT_USERNAME
    BOT_ID = bot_id
    BOT_USERNAME = username


def init_members_db():
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS member_states (
                user_id INTEGER PRIMARY KEY,
                state TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS member_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                channel_username TEXT NOT NULL,
                target_count INTEGER NOT NULL,
                joined_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                channel_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                FOREIGN KEY (owner_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS member_order_claims (
                order_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                claimed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (order_id, user_id),
                FOREIGN KEY (order_id) REFERENCES member_orders(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_member_orders_owner
            ON member_orders(owner_id);

            CREATE INDEX IF NOT EXISTS idx_member_orders_status
            ON member_orders(status);
        """)


def _set_state(user_id, state, payload=None):
    payload = payload or {}

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO member_states (user_id, state, payload)
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
            FROM member_states
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
            "DELETE FROM member_states WHERE user_id = ?",
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


def _check_bot_admin(api, channel_username):
    """بررسی ادمین بودن ربات؛ خطای API به معنی تأیید نیست."""
    if not BOT_ID:
        return False

    result = api("getChatMember", {
        "chat_id": channel_username,
        "user_id": BOT_ID
    })

    if not result or not result.get("ok"):
        print("Bot admin check failed:", result)
        return False

    status = result.get("result", {}).get("status", "")
    return status in ("administrator", "creator", "owner")


def _get_api_error_description(result):
    """استخراج توضیح خطا از پاسخ API؛ حتی وقتی بدنه JSON به‌شکل متن باشد."""
    if not isinstance(result, dict):
        return ""

    description = result.get("description", "")

    if isinstance(description, dict):
        return str(description.get("description", ""))

    if isinstance(description, str):
        try:
            parsed = json.loads(description)
            if isinstance(parsed, dict):
                return str(parsed.get("description", description))
        except (json.JSONDecodeError, TypeError):
            pass

        return description

    return str(description)


def _check_user_membership(api, channel_username, user_id):
    """
    True: عضویت تأیید شده
    False: کاربر عضو نیست یا API این وضعیت را با اطمینان گزارش کرده
    None: بررسی به علت خطای نامشخص ممکن نیست
    """

    # ابتدا مطمئن شو خود کانال از طریق API قابل دسترسی است.
    chat_result = api("getChat", {
        "chat_id": channel_username
    })

    if not chat_result or not chat_result.get("ok"):
        print(
            "Channel verification failed:",
            {
                "channel": channel_username,
                "response": chat_result
            }
        )
        return None

    # حالا عضویت کاربر را بررسی کن.
    result = api("getChatMember", {
        "chat_id": channel_username,
        "user_id": user_id
    })

    if not result or not result.get("ok"):
        description = _get_api_error_description(result)
        http_status = result.get("http_status") if isinstance(result, dict) else None

        # بعضی پاسخ‌های بله برای کاربری که عضو نیست،
        # به‌جای وضعیت left خطای 404 برمی‌گردانند.
        # این تفسیر فقط پس از تأیید دسترسی به خود کانال انجام می‌شود.
        if (
            http_status == 404
            and "no such group or user" in description.lower()
        ):
            print(
                "Membership lookup returned 404 for user:",
                {
                    "channel": channel_username,
                    "user_id": user_id
                }
            )
            return False

        print(
            "Membership check failed:",
            {
                "channel": channel_username,
                "user_id": user_id,
                "response": result
            }
        )
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
            "text": "📢 عضویت",
            "url": f"https://ble.ir/{channel_name}"
        },
        {
            "text": "✅ عضو شدم",
            "callback_data": f"member_claim:{order['id']}"
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
        "📋 سفارش عضو - تضمینی\n\n"
        f"🔗 {order['channel_username']}\n"
        f"👥 درخواستی: {order['target_count']}\n"
        f"✅ عضو شده: {order['joined_count']}\n\n"
        f"#{order['id']}"
    )


def start_order(user_id, chat_id, send_message):
    _set_state(user_id, "waiting_channel")

    send_message(
        chat_id,
        "👥 ثبت سفارش ممبر تضمینی\n\n"
        "⚠️ ابتدا ربات رو در کانالی که می‌خوای براش ممبر بگیری "
        "ادمین کن.\n\n"
        "سپس آیدی کانال رو به این شکل بفرست:\n"
        "@channelusername\n\n"
        f"💰 قیمت هر ممبر: {PRICE_PER_MEMBER} سکه\n\n"
        "برای لغو مراحل، /cancel رو بفرست."
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

    if text == "👥 سفارش ممبر تضمینی":
        start_order(user_id, chat_id, send_message)
        return True

    if not state:
        return False

    if text == "/cancel":
        clear_state(user_id)
        send_message(chat_id, "❌ مراحل سفارش ممبر لغو شد.")
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
                "❌ نتونستم ادمین بودن ربات رو تأیید کنم.\n\n"
                "آیدی کانال و دسترسی ربات رو بررسی کن و دوباره تلاش کن."
            )
            return True

        _set_state(
            user_id,
            "waiting_count",
            {"channel_username": text}
        )

        send_message(
            chat_id,
            "✅ ادمین بودن ربات تأیید شد.\n\n"
            f"🔗 کانال: {text}\n"
            f"💰 قیمت هر ممبر: {PRICE_PER_MEMBER} سکه\n\n"
            "چند ممبر می‌خوای؟\n"
            f"حداکثر تعداد: {MAX_MEMBERS}"
        )
        return True

    if state == "waiting_count":
        try:
            count = int(text)
        except ValueError:
            send_message(chat_id, "❌ تعداد رو با عدد وارد کن.")
            return True

        if not 1 <= count <= MAX_MEMBERS:
            send_message(
                chat_id,
                f"❌ تعداد باید بین ۱ تا {MAX_MEMBERS} باشه."
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
                "❌ سکه‌هات کافی نیست!\n\n"
                f"💰 هزینه: {cost} سکه\n"
                f"🪙 موجودی: {coins} سکه"
            )
            return True

        payload["target_count"] = count
        payload["total_cost"] = cost
        _set_state(user_id, "confirming", payload)

        keyboard = {
            "inline_keyboard": [[
                {"text": "❌ لغو", "callback_data": "member_cancel"},
                {"text": "✅ تأیید سفارش", "callback_data": "member_confirm"}
            ]]
        }

        send_message(
            chat_id,
            "🧾 تأیید سفارش ممبر\n\n"
            f"🔗 کانال: {payload['channel_username']}\n"
            f"👥 تعداد: {count}\n"
            f"💰 هزینه کل: {cost} سکه\n\n"
            "آیا سفارش رو تأیید می‌کنی؟",
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
        _answer_callback(api, callback_id, "اطلاعات سفارش نامعتبره.", True)
        return

    if not _check_bot_admin(api, channel):
        _answer_callback(api, callback_id, "ادمین بودن ربات تأیید نشد.", True)
        return

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            "SELECT state FROM member_states WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        if not row or row["state"] != "confirming":
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
            "UPDATE member_states SET state = 'processing' WHERE user_id = ?",
            (user_id,)
        )
        conn.execute(
            "UPDATE users SET coins = coins - ? WHERE user_id = ?",
            (cost, user_id)
        )
        cursor = conn.execute(
            """
            INSERT INTO member_orders
            (owner_id, channel_username, target_count, status)
            VALUES (?, ?, ?, 'pending')
            """,
            (user_id, channel, count)
        )
        order_id = cursor.lastrowid

    order = {
        "id": order_id,
        "channel_username": channel,
        "target_count": count,
        "joined_count": 0
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
                "UPDATE member_orders SET status = 'failed' WHERE id = ?",
                (order_id,)
            )

        clear_state(user_id)
        _answer_callback(api, callback_id, "انتشار سفارش ناموفق بود؛ سکه برگشت.", True)

        if chat_id:
            send_message(chat_id, "❌ سفارش منتشر نشد؛ سکه‌ها برگشت داده شدن.")
        return

    message_id = result.get("result", {}).get("message_id")

    with get_connection() as conn:
        conn.execute(
            "UPDATE member_orders SET channel_message_id = ? WHERE id = ?",
            (message_id, order_id)
        )

    clear_state(user_id)
    _answer_callback(api, callback_id, "سفارش با موفقیت ثبت شد.")

    if chat_id:
        send_message(
            chat_id,
            "✅ سفارش ممبر ثبت شد!\n\n"
            f"🔢 شماره سفارش: #{order_id}\n"
            f"👥 تعداد: {count}\n"
            f"💰 هزینه: {cost} سکه"
        )


def _cancel_order(user_id, callback, api, send_message):
    callback_id = callback.get("id")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")

    state, _ = _get_state(user_id)

    if state != "confirming":
        _answer_callback(api, callback_id, "این مرحله قبلاً تمام شده.", True)
        return

    clear_state(user_id)
    _answer_callback(api, callback_id, "سفارش لغو شد.")

    if chat_id:
        send_message(chat_id, "❌ ثبت سفارش ممبر لغو شد.")


def _claim_member(user_id, callback, api, send_message):
    callback_id = callback.get("id")
    data = callback.get("data", "")

    try:
        order_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        _answer_callback(api, callback_id, "شماره سفارش نامعتبره.", True)
        return

    with get_connection() as conn:
        order = conn.execute(
            "SELECT * FROM member_orders WHERE id = ?",
            (order_id,)
        ).fetchone()

    if not order:
        _answer_callback(api, callback_id, "سفارش پیدا نشد.", True)
        return

    if order["owner_id"] == user_id:
        _answer_callback(api, callback_id, "نمی‌تونی برای سفارش خودت پاداش بگیری.", True)
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
            api,
            callback_id,
            "بررسی عضویت ناموفق بود؛ کمی بعد دوباره تلاش کن.",
            True
        )
        return

    if membership is False:
        _answer_callback(
            api,
            callback_id,
            "هنوز عضو کانال نشدی! عضو شو و دوباره بزن.",
            True
        )
        return

    duplicate = False
    completed = False
    new_count = 0
    new_balance = 0

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        current = conn.execute(
            "SELECT * FROM member_orders WHERE id = ?",
            (order_id,)
        ).fetchone()

        if (
            not current
            or current["status"] != "pending"
            or current["joined_count"] >= current["target_count"]
        ):
            _answer_callback(api, callback_id, "این سفارش دیگه فعال نیست.", True)
            return

        user_info = callback.get("from", {})

        conn.execute(
            """
            INSERT INTO users (user_id, username, first_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (user_id, user_info.get("username"), user_info.get("first_name"))
        )

        try:
            conn.execute(
                """
                INSERT INTO member_order_claims (order_id, user_id)
                VALUES (?, ?)
                """,
                (order_id, user_id)
            )
        except sqlite3.IntegrityError:
            duplicate = True

        if not duplicate:
            conn.execute(
                "UPDATE users SET coins = coins + ? WHERE user_id = ?",
                (REWARD_PER_MEMBER, user_id)
            )

            conn.execute(
                "UPDATE member_orders SET joined_count = joined_count + 1 WHERE id = ?",
                (order_id,)
            )

            updated = conn.execute(
                "SELECT joined_count, target_count FROM member_orders WHERE id = ?",
                (order_id,)
            ).fetchone()

            new_count = updated["joined_count"]
            completed = new_count >= updated["target_count"]

            if completed:
                conn.execute(
                    """
                    UPDATE member_orders
                    SET status = 'completed', completed_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (order_id,)
                )

            balance_row = conn.execute(
                "SELECT coins FROM users WHERE user_id = ?",
                (user_id,)
            ).fetchone()
            new_balance = balance_row["coins"]

    if duplicate:
        _answer_callback(api, callback_id, "قبلاً برای این سفارش سکه گرفتی.", True)
        return

    _answer_callback(
        api,
        callback_id,
        f"{REWARD_PER_MEMBER}+ سکه اضافه شد؛ موجودی: {new_balance}"
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
            "joined_count": new_count
        }

        api("editMessageText", {
            "chat_id": ORDER_CHANNEL,
            "message_id": order["channel_message_id"],
            "text": _order_text(updated_order),
            "reply_markup": _order_keyboard(updated_order)
        })


def handle_callback_query(callback, api, send_message):
    data = callback.get("data", "")
    user_id = callback.get("from", {}).get("id")

    if not user_id or not data.startswith("member_"):
        return False

    if data == "member_confirm":
        _confirm_order(user_id, callback, api, send_message)
    elif data == "member_cancel":
        _cancel_order(user_id, callback, api, send_message)
    elif data.startswith("member_claim:"):
        _claim_member(user_id, callback, api, send_message)
    else:
        _answer_callback(
            api,
            callback.get("id"),
            "این دکمه شناخته نشد.",
            True
        )

    return True
