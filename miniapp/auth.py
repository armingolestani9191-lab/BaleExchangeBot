
# ==========================================
# MINI APP AUTHENTICATION
# احراز هویت کاربران مینی اپ بله
# ==========================================

import hashlib
import hmac
import json
import time

from urllib.parse import parse_qsl

import config


# حداکثر اعتبار اطلاعات ورود: یک ساعت
MAX_INIT_DATA_AGE = 3600

# اختلاف مجاز ساعت دستگاه و سرور
MAX_FUTURE_SKEW = 60


def validate_init_data(init_data):
    """
    بررسی اعتبار اطلاعات ارسالی از Mini App بله.

    خروجی:
        اطلاعات کاربر تأییدشده

    در صورت نامعتبر بودن:
        ValueError
    """

    if not isinstance(init_data, str) or not init_data:
        raise ValueError("اطلاعات ورود ارسال نشده است.")

    bot_token = getattr(config, "BOT_TOKEN", None)

    if not bot_token:
        raise ValueError("توکن ربات در config.py تنظیم نشده است.")

    # ==========================================
    # تجزیه اطلاعات
    # ==========================================

    try:
        pairs = parse_qsl(
            init_data,
            keep_blank_values=True,
            strict_parsing=True
        )

        data = {}

        for key, value in pairs:
            if key in data:
                raise ValueError("پارامتر تکراری در اطلاعات ورود.")

            data[key] = value

    except ValueError:
        raise

    except Exception:
        raise ValueError("ساختار اطلاعات ورود نامعتبر است.")

    received_hash = data.pop("hash", None)

    if not received_hash:
        raise ValueError("امضای اطلاعات ورود وجود ندارد.")

    # ==========================================
    # ساخت رشته بررسی
    # ==========================================

    data_check_string = "\n".join(
        f"{key}={value}"
        for key, value in sorted(data.items())
    )

    # ==========================================
    # محاسبه امضای معتبر
    # ==========================================

    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256
    ).digest()

    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(
        calculated_hash,
        received_hash
    ):
        raise ValueError("اطلاعات ورود معتبر نیست.")

    # ==========================================
    # بررسی زمان اعتبار
    # ==========================================

    try:
        auth_date = int(data.get("auth_date", "0"))
    except (ValueError, TypeError):
        raise ValueError("تاریخ ورود نامعتبر است.")

    current_time = int(time.time())

    if auth_date <= 0:
        raise ValueError("تاریخ ورود وجود ندارد.")

    if auth_date > current_time + MAX_FUTURE_SKEW:
        raise ValueError("تاریخ ورود نامعتبر است.")

    if current_time - auth_date > MAX_INIT_DATA_AGE:
        raise ValueError("اطلاعات ورود منقضی شده است.")

    # ==========================================
    # دریافت اطلاعات کاربر
    # ==========================================

    try:
        user = json.loads(data.get("user", "{}"))
    except (ValueError, TypeError):
        raise ValueError("اطلاعات کاربر نامعتبر است.")

    if not isinstance(user, dict):
        raise ValueError("ساختار اطلاعات کاربر نامعتبر است.")

    try:
        user_id = int(user.get("id", 0))
    except (ValueError, TypeError):
        raise ValueError("شناسه کاربر نامعتبر است.")

    if user_id <= 0:
        raise ValueError("شناسه کاربر وجود ندارد.")

    user["id"] = user_id

    return {
        "user": user,
        "auth_date": auth_date
    }
