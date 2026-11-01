
# ==========================================
# MINI APP API SERVER
# سرور ارتباط مینی اپ با ربات
# ==========================================

import os

from flask import (
    Flask,
    request,
    jsonify,
    make_response,
    send_from_directory
)

from miniapp.auth import validate_init_data
from miniapp import settings
from database import get_connection


# ==========================================
# مسیر فایل‌های فرانت‌اند
# ==========================================

WEB_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "web"
)


# ==========================================
# ساخت برنامه
# ==========================================

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False


# ==========================================
# نمایش صفحه اصلی مینی اپ
# ==========================================

@app.route("/", methods=["GET"])
def index():

    return send_from_directory(
        WEB_DIR,
        "index.html"
    )


# ==========================================
# دریافت فایل‌های CSS و JS
# ==========================================

@app.route("/<path:filename>", methods=["GET"])
def web_files(filename):

    return send_from_directory(
        WEB_DIR,
        filename
    )


# ==========================================
# تنظیمات CORS
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
# احراز هویت کاربر
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
# پاسخ آزمایشی سرور
# ==========================================

@app.route("/api/health", methods=["GET"])
def health():

    return jsonify({
        "ok": True,
        "message": "Mini App API is running",
        "version": settings.API_VERSION
    })


# ==========================================
# بررسی ورود کاربر
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

    except ValueError as error:

        return error_response(str(error), 401)


# ==========================================
# دریافت پروفایل کاربر
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

    except ValueError as error:

        return error_response(str(error), 401)

    except Exception as error:

        print("Mini App profile error:", repr(error))

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

    if order_type not in ("all", "member", "guaranteed"):

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

    # احراز هویت

    try:

        get_authenticated_user()

    except ValueError as error:

        return error_response(str(error), 401)

    # دریافت سفارش‌ها

    try:

        with get_connection() as conn:

            if order_type == "member":

                query = """
                    SELECT
                        id,
                        channel_username,
                        target_count,
                        joined_count,
                        0 AS lost_count,
                        created_at,
                        'member' AS order_type
                    FROM member_orders
                    WHERE status = 'pending'
                    ORDER BY created_at DESC, id DESC
                    LIMIT ? OFFSET ?
                """

            elif order_type == "guaranteed":

                query = """
                    SELECT
                        id,
                        channel_username,
                        target_count,
                        joined_count,
                        lost_count,
                        created_at,
                        'guaranteed' AS order_type
                    FROM guaranteed_member_orders
                    WHERE status = 'pending'
                    ORDER BY created_at DESC, id DESC
                    LIMIT ? OFFSET ?
                """

            else:

                query = """
                    SELECT * FROM (

                        SELECT
                            id,
                            channel_username,
                            target_count,
                            joined_count,
                            0 AS lost_count,
                            created_at,
                            'member' AS order_type
                        FROM member_orders
                        WHERE status = 'pending'

                        UNION ALL

                        SELECT
                            id,
                            channel_username,
                            target_count,
                            joined_count,
                            lost_count,
                            created_at,
                            'guaranteed' AS order_type
                        FROM guaranteed_member_orders
                        WHERE status = 'pending'

                    )
                    ORDER BY created_at DESC, id DESC
                    LIMIT ? OFFSET ?
                """

            rows = conn.execute(
                query,
                (limit + 1, offset)
            ).fetchall()

        # آماده‌سازی خروجی

        has_more = len(rows) > limit
        rows = rows[:limit]

        orders = []

        for row in rows:

            target_count = row["target_count"] or 0
            joined_count = row["joined_count"] or 0

            orders.append({
                "id": row["id"],
                "type": row["order_type"],
                "channel_username": row["channel_username"],
                "target_count": target_count,
                "joined_count": joined_count,
                "remaining_count": max(
                    0,
                    target_count - joined_count
                ),
                "lost_count": row["lost_count"] or 0,
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

        print("Mini App orders error:", repr(error))

        return error_response(
            "دریافت سفارش‌ها ناموفق بود.",
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
