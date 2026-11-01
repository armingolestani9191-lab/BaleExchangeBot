# ==========================================
# MINI APP SERVER SETTINGS
# تنظیمات سرور مینی اپ
# ==========================================

import os

# آدرس اجرای سرور
HOST = "0.0.0.0"

# پورت؛ در Railway از متغیر محیطی PORT استفاده می‌شود
PORT = int(os.environ.get("PORT", 8080))

# حداکثر سفارش‌های قابل نمایش
MAX_ORDERS_PER_PAGE = 50

# تنظیمات CORS
CORS_ORIGINS = ["*"]

# نسخه API
API_VERSION = "1.1.0"