# ==========================================
# MINI APP API
# ارتباط مینی اپ با ربات
# ==========================================

import os
import time
import requests

from urllib.parse import quote

from flask import (
    Flask,
    request,
    jsonify,
    make_response,
    send_from_directory,
    Response
)

from config import BOT_TOKEN
from database import get_connection
from miniapp.auth import validate_init_data
from miniapp import settings

from features import members, guaranteed_members


# ==========================================
# تنظیمات
# ==========================================

WEB_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "web"
)

API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}/"
FILE_URL = f"https://tapi.bale.ai/file/bot{BOT_TOKEN}/"

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False

# اطلاعات کانال‌ها برای جلوگیری از درخواست تکراری
CHANNEL_CACHE = {}

# فایل‌هایی که از getChat دریافت شده‌اند
AVATAR_FILE_IDS = set()

CHANNEL_CACHE_SECONDS = 300


# ==========================================
# ارتباط با API بله
# ==========================================

def bale_api(method, data=None):

    try:

        response = requests.post(
            API_URL + method,
            json=data or {},
            timeout=20
        )

        try:
            result = response.json()
        except ValueError:
            return {
                "ok": False,
                "description": "Invalid API response",
                "http_status": response.status_code
            }

        if not response.ok:
            result["http_status"] = response.status_code

        return result

    except requests.RequestException as error:

        print(
            "Mini App Bale API error:",
            method,
            repr(error)
        )

        return {
            "ok": False,
            "description": str(error)
        }


# ==========================================
# فایل‌های مینی اپ
# ==========================================

@app.route("/", methods=["GET"])
def index():

    return send_from_directory(
        WEB_DIR,
        "index.html"
    )


@app.route("/<path:filename>", methods=["GET"])
def web_files(filename):

    return send_from_directory(
        WEB_DIR,
        filename
    )


# ==========================================
# نمایش عکس پروفایل کانال
# ==========================================

@app.route("/api/channel-avatar", methods=["GET"])
def channel_avatar():

    file_id = request.args.get("file_id", "")

    if not file_id or file_id not in AVATAR_FILE_IDS:
        return "", 404

    try:

        file_result = bale_api(
            "getFile",
            {"file_id": file_id}
        )

        if not file_result or not file_result.get("ok"):
            return "", 404

        file_path = (
            file_result.get("result", {}).get("file_path")
        )

        if not file_path:
            return "", 404

        image_response = requests.get(
            FILE_URL + file_path,
            timeout=20
        )

        if not image_response.ok:
            return "", 404

        content_type = image_response.headers.get(
            "Content-Type",
            "image/jpeg"
        )

        response = Response(
            image_response.content,
            mimetype=content_type
        )

        response.headers["Cache-Control"] = (
            "public, max-age=3600"
        )

        return response

    except Exception as error:

        print(
            "Channel avatar error:",
            repr(error)
        )

        return "", 500


# ==========================================
# اطلاعات کانال
# ==========================================

def get_channel_info(channel_username):

    channel_username = str(
        channel_username or ""
    ).strip()

    if not channel_username:
        return {
            "title": "کانال",
            "username": "",
            "avatar_url": None,
            "channel_url": None
        }

    cache_key = channel_username.lower()
    now = time.time()

    cached = CHANNEL_CACHE.get(cache_key)

    if cached and now - cached["time"] < CHANNEL_CACHE_SECONDS:
        return cached["data"]

    chat_id = channel_username

    if not chat_id.startswith("@"):
        chat_id = "@" + chat_id

    result = bale_api(
        "getChat",
        {"chat_id": chat_id}
    )

    if not result or not result.get("ok"):

        fallback_username = channel_username.lstrip("@")

        return {
            "title": fallback_username,
            "username": fallback_username,
            "avatar_url": None,
            "channel_url": (
                f"https://ble.ir/{fallback_username}"
                if fallback_username else None
            )
        }

    chat = result.get("result", {})

    title = (
        chat.get("title")
        or chat.get("first_name")
        or channel_username.lstrip("@")
    )

    username = (
        chat.get("username")
        or channel_username.lstrip("@")
    )

    photo = chat.get("photo") or {}

    file_id = (
        photo.get("big_file_id")
        or photo.get("small_file_id")
    )

    avatar_url = None

    if file_id:

        AVATAR_FILE_IDS.add(file_id)

        avatar_url = (
            "/api/channel-avatar?file_id="
            + quote(file_id)
        )

    data = {
        "title": title,
        "username": username,
        "avatar_url": avatar_url,
        "channel_url": f"https://ble.ir/{username}"
    }

    CHANNEL_CACHE[cache_key] = {
        "time": now,
        "data": data
    }

    return data


# ==========================================
# CORS
# ==========================================

@app.after_request
def add_cors_headers(response):

    response.headers["Access-Control-Allow-Origin"] = "*"

    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, X-Bale-Init-Data"
    )

    response.headers["Access-Control-Allow-Methods"] = (
        "GET, POST, OPTIONS"
    )

    return response


# ==========================================
# پاسخ خطا
# ==========================================

def error_response(message, status_code=400):

    return jsonify({
        "ok": False,
        "error": message
    }), status_code


# ==========================================
# احراز هویت
# ==========================================

def get_authenticated_user():

    init_data = request.headers.get(
        "X-Bale-Init-Data",
        ""
    )

    if not init_data:
        raise ValueError("اطلاعات ورود دریافت نشد.")

    auth = validate_init_data(init_data)

    user = auth.get("user")

    if not isinstance(user, dict) or not user.get("id"):
        raise ValueError("اطلاعات کاربر معتبر نیست.")

    return user


# ==========================================
# وضعیت سرور
# ==========================================

@app.route("/api/health", methods=["GET"])
def health():

    return jsonify({
        "ok": True,
        "message": "Mini App API is running",
        "version": settings.API_VERSION
    })


# ==========================================
# بررسی ورود
# ==========================================

@app.route("/api/auth/check", methods=["GET", "OPTIONS"])
def auth_check():

    if request.method == "OPTIONS":
        return make_response("", 204)

    try:

        user = get_authenticated_user()

        return jsonify({
            "ok": True,
            "user": {
                "id": user["id"],
                "first_name": user.get("first_name", ""),
                "username": user.get("username", "")
            }
        })

    except Exception as error:

        return error_response(
            str(error),
            401
        )


# ==========================================
# پروفایل کاربر
# ==========================================

@app.route("/api/user/profile", methods=["GET", "OPTIONS"])
def user_profile():

    if request.method == "OPTIONS":
        return make_response("", 204)

    try:

        user = get_authenticated_user()
        user_id = int(user["id"])

        with get_connection() as conn:

            row = conn.execute(
                """
                SELECT
                    user_id,
                    username,
                    first_name,
                    coins,
                    created_at
                FROM users
                WHERE user_id = ?
                LIMIT 1
                """,
                (user_id,)
            ).fetchone()

        if not row:

            return jsonify({
                "ok": True,
                "user": {
                    "id": user_id,
                    "first_name": user.get("first_name", ""),
                    "username": user.get("username", ""),
                    "coins": 0,
                    "created_at": None
                }
            })

        return jsonify({
            "ok": True,
            "user": {
                "id": row["user_id"],
                "first_name": row["first_name"] or "",
                "username": row["username"] or "",
                "coins": row["coins"] or 0,
                "created_at": row["created_at"]
            }
        })

    except Exception as error:

        print(
            "Mini App profile error:",
            repr(error)
        )

        return error_response(
            "دریافت اطلاعات حساب ناموفق بود.",
            500
        )


# ==========================================
# دریافت سفارش‌های فعال
# ==========================================

@app.route("/api/orders", methods=["GET", "OPTIONS"])
def get_orders():

    if request.method == "OPTIONS":
        return make_response("", 204)

    order_type = request.args.get(
        "type",
        "all"
    ).lower()

    if order_type not in (
        "all",
        "member",
        "guaranteed"
    ):
        return error_response(
            "نوع سفارش نامعتبر است.",
            400
        )

    try:

        page = int(request.args.get("page", 1))

        limit = int(
            request.args.get(
                "limit",
                settings.MAX_ORDERS_PER_PAGE
            )
        )

        if page < 1 or limit < 1:
            raise ValueError

    except ValueError:

        return error_response(
            "شماره صفحه یا تعداد سفارش نامعتبر است.",
            400
        )

    limit = min(
        limit,
        settings.MAX_ORDERS_PER_PAGE
    )

    offset = (page - 1) * limit

    try:

        user = get_authenticated_user()
        user_id = int(user["id"])

    except Exception as error:

        return error_response(
            str(error),
            401
        )

    try:

        member_query = """
            SELECT
                o.id,
                o.owner_id,
                o.channel_username,
                o.target_count,
                o.joined_count,
                0 AS lost_count,
                o.created_at,
                NULL AS total_cost,
                (
                    SELECT COUNT(*)
                    FROM member_order_claims c
                    WHERE c.order_id = o.id
                ) AS claim_count,
                'member' AS order_type

            FROM member_orders o

            WHERE o.status = 'pending'
              AND o.owner_id != ?

              AND NOT EXISTS (
                  SELECT 1
                  FROM member_order_claims c
                  WHERE c.order_id = o.id
                    AND c.user_id = ?
              )
        """

        guaranteed_query = """
            SELECT
                o.id,
                o.owner_id,
                o.channel_username,
                o.target_count,
                o.joined_count,
                o.lost_count,
                o.created_at,
                o.total_cost,
                (
                    SELECT COUNT(*)
                    FROM guaranteed_member_claims c
                    WHERE c.order_id = o.id
                ) AS claim_count,
                'guaranteed' AS order_type

            FROM guaranteed_member_orders o

            WHERE o.status = 'pending'
              AND o.owner_id != ?

              AND NOT EXISTS (
                  SELECT 1
                  FROM guaranteed_member_claims c
                  WHERE c.order_id = o.id
                    AND c.user_id = ?
              )
        """

        if order_type == "member":

            query = member_query + """
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
            """

            params = (
                user_id,
                user_id,
                limit + 1,
                offset
            )

        elif order_type == "guaranteed":

            query = guaranteed_query + """
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
            """

            params = (
                user_id,
                user_id,
                limit + 1,
                offset
            )

        else:

            query = """
                SELECT *
                FROM (
                    """ + member_query + """
                    UNION ALL
                    """ + guaranteed_query + """
                )
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
            """

            params = (
                user_id,
                user_id,
                user_id,
                user_id,
                limit + 1,
                offset
            )

        with get_connection() as conn:

            rows = conn.execute(
                query,
                params
            ).fetchall()

        has_more = len(rows) > limit
        rows = rows[:limit]

        orders = []

        for row in rows:

            target_count = int(row["target_count"] or 0)
            joined_count = int(row["joined_count"] or 0)
            claim_count = int(row["claim_count"] or 0)

            if row["order_type"] == "member":

                price = members.PRICE_PER_MEMBER
                reward = members.REWARD_PER_MEMBER

                guarantee_hours = None
                leave_penalty = None
                first_reward_available = False

                total_cost = (
                    target_count * price
                )

            else:

                price = guaranteed_members.PRICE_PER_MEMBER

                first_reward_available = (
                    claim_count == 0
                )

                reward = (
                    guaranteed_members.FIRST_REWARD
                    if first_reward_available
                    else guaranteed_members.REWARD_PER_MEMBER
                )

                guarantee_hours = (
                    guaranteed_members.GUARANTEE_HOURS
                )

                leave_penalty = (
                    guaranteed_members.LEAVE_PENALTY
                )

                total_cost = int(
                    row["total_cost"] or
                    target_count * price
                )

            channel = get_channel_info(
                row["channel_username"]
            )

            orders.append({

                "id": row["id"],

                "type": row["order_type"],

                "channel_username": row["channel_username"],

                "channel_title": channel["title"],

                "channel_public_username": channel["username"],

                "avatar_url": channel["avatar_url"],

                "channel_url": channel["channel_url"],

                "target_count": target_count,

                "joined_count": joined_count,

                "remaining_count": max(
                    0,
                    target_count - joined_count
                ),

                "lost_count": int(
                    row["lost_count"] or 0
                ),

                "price_per_member": price,

                "total_cost": total_cost,

                "reward": reward,

                "first_reward_available": first_reward_available,

                "guarantee_hours": guarantee_hours,

                "leave_penalty": leave_penalty,

                "created_at": row["created_at"]

            })

        return jsonify({

            "ok": True,

            "orders": orders,

            "pagination": {
                "page": page,
                "limit": limit,
                "has_more": has_more
            }

        })

    except Exception as error:

        print(
            "Mini App orders error:",
            repr(error)
        )

        return error_response(
            "دریافت سفارش‌ها ناموفق بود.",
            500
        )


# ==========================================
# بررسی عضویت و دریافت پاداش
# استفاده از منطق اصلی ربات
# ==========================================

@app.route(
    "/api/orders/<order_type>/<int:order_id>/claim",
    methods=["POST", "OPTIONS"]
)
def claim_order(order_type, order_id):

    if request.method == "OPTIONS":
        return make_response("", 204)

    if order_type not in ("member", "guaranteed"):
        return error_response(
            "نوع سفارش نامعتبر است.",
            400
        )

    try:

        user = get_authenticated_user()

        user_id = int(user["id"])

    except Exception as error:

        return error_response(
            str(error),
            401
        )

    module = (
        members
        if order_type == "member"
        else guaranteed_members
    )

    claims_table = (
        "member_order_claims"
        if order_type == "member"
        else "guaranteed_member_claims"
    )

    try:

        with get_connection() as conn:

            previous = conn.execute(
                f"""
                SELECT 1
                FROM {claims_table}
                WHERE order_id = ?
                  AND user_id = ?
                LIMIT 1
                """,
                (order_id, user_id)
            ).fetchone()

        if previous:

            return error_response(
                "قبلاً پاداش این سفارش را دریافت کرده‌ای.",
                409
            )

        callback_result = {}

        # این تابع، پاسخ callback را فقط ذخیره می‌کند.
        # بقیه درخواست‌ها مستقیماً به API بله می‌روند.
        def callback_api(method, data=None):

            if method == "answerCallbackQuery":

                callback_result["answer"] = data or {}

                return {"ok": True}

            return bale_api(
                method,
                data
            )

        def callback_send_message(chat_id, text, keyboard=None):

            data = {
                "chat_id": chat_id,
                "text": text
            }

            if keyboard:
                data["reply_markup"] = keyboard

            return bale_api(
                "sendMessage",
                data
            )

        callback_data = (
            f"member_claim:{order_id}"
            if order_type == "member"
            else f"guaranteed_member_claim:{order_id}"
        )

        callback = {

            "id": "miniapp_claim",

            "data": callback_data,

            "from": {
                "id": user_id,
                "username": user.get("username"),
                "first_name": user.get("first_name")
            }

        }

        # اجرای تابع واقعی ربات
        module._claim_member(
            user_id,
            callback,
            callback_api,
            callback_send_message
        )

        answer = callback_result.get(
            "answer",
            {}
        )

        answer_text = answer.get(
            "text",
            ""
        )

        # بررسی اینکه واقعاً claim ثبت شده باشد
        with get_connection() as conn:

            if order_type == "member":

                claim = conn.execute(
                    """
                    SELECT claimed_at
                    FROM member_order_claims
                    WHERE order_id = ?
                      AND user_id = ?
                    """,
                    (order_id, user_id)
                ).fetchone()

                reward = members.REWARD_PER_MEMBER

                order = conn.execute(
                    """
                    SELECT joined_count, target_count
                    FROM member_orders
                    WHERE id = ?
                    """,
                    (order_id,)
                ).fetchone()

            else:

                claim = conn.execute(
                    """
                    SELECT claimed_at, reward_amount
                    FROM guaranteed_member_claims
                    WHERE order_id = ?
                      AND user_id = ?
                    """,
                    (order_id, user_id)
                ).fetchone()

                reward = (
                    claim["reward_amount"]
                    if claim else 0
                )

                order = conn.execute(
                    """
                    SELECT joined_count, target_count
                    FROM guaranteed_member_orders
                    WHERE id = ?
                    """,
                    (order_id,)
                ).fetchone()

            balance_row = conn.execute(
                """
                SELECT coins
                FROM users
                WHERE user_id = ?
                """,
                (user_id,)
            ).fetchone()

        if not claim:

            return error_response(
                answer_text or
                "عضویت تأیید نشد. ابتدا عضو کانال شو و دوباره تلاش کن.",
                409
            )

        if "قبلاً" in answer_text:

            return error_response(
                answer_text,
                409
            )

        if not answer_text or "سکه" not in answer_text:

            return error_response(
                answer_text or "دریافت پاداش انجام نشد.",
                409
            )

        return jsonify({

            "ok": True,

            "message": "عضویت تأیید شد و پاداش به کیف پول اضافه شد.",

            "reward": reward,

            "balance": (
                balance_row["coins"]
                if balance_row else 0
            ),

            "joined_count": (
                order["joined_count"]
                if order else 0
            ),

            "target_count": (
                order["target_count"]
                if order else 0
            )

        })

    except Exception as error:

        print(
            "Mini App claim error:",
            repr(error)
        )

        return error_response(
            "بررسی عضویت یا ثبت پاداش ناموفق بود.",
            500
        )


# ==========================================
# اجرای سرور
# ==========================================

def run_server():

    print("Mini App API is starting...")

    app.run(
        host=settings.HOST,
        port=settings.PORT,
        debug=False,
        threaded=True,
        use_reloader=False
    )


if __name__ == "__main__":

    run_server()