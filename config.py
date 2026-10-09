import os

# توکن ربات بله
BOT_TOKEN = "1200170625:YgLV45DlcFz7_S664RIp0jIoSe-sDCe-3kA"

# شناسه عددی ادمین
ADMIN_ID = 0

# تشخیص محیط اجرا
if (
    os.environ.get("RAILWAY_ENVIRONMENT")
    or os.environ.get("RAILWAY_PROJECT_ID")
):
    DB_PATH = "/data/bot.db"
else:
    BASE_DIR = os.path.dirname(
        os.path.abspath(__file__)
    )
    DB_PATH = os.path.join(BASE_DIR, "bot.db")
    
    # کانال انتشار سفارش‌ها
ORDER_CHANNEL = "@djbdbdhddhdb"