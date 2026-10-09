
import os

# ==============================
# تنظیمات ربات بله
# ==============================

# توکن ربات بله را داخل کوتیشن قرار بده
BOT_TOKEN = "848571933:f0aQ5uN_JgJgxH94pWvVS9ANgIiD8ramL_s"

# شناسه عددی ادمین
ADMIN_ID = 595450272

# کانال انتشار سفارش‌ها
ORDER_CHANNEL = "@djbdbdhddhdb"


# ==============================
# تنظیمات دیتابیس
# ==============================

# در Railway اطلاعات در Volume ذخیره می‌شوند
IS_RAILWAY = any(
    os.environ.get(name)
    for name in (
        "RAILWAY_ENVIRONMENT",
        "RAILWAY_PROJECT_ID",
        "RAILWAY_SERVICE_ID",
    )
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

if IS_RAILWAY:
    DB_PATH = "/data/bot.db"
else:
    DB_PATH = os.path.join(BASE_DIR, "bot.db")
