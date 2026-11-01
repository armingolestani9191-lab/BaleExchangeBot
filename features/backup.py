
import os
import sqlite3
import tempfile
import requests

from config import BOT_TOKEN, ADMIN_ID, DB_PATH


API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}/"


def handle_message(message, send_message):
    text = (message.get("text") or "").strip()

    if text != "/بکاپ":
        return False

    user = message.get("from", {})
    chat = message.get("chat", {})

    user_id = user.get("id")
    chat_id = chat.get("id")

    # فقط ادمین اصلی اجازه دارد
    if not user_id or int(user_id) != int(ADMIN_ID):
        return True

    # دستور فقط در پیوی ربات اجرا شود
    if chat.get("type") != "private" or chat_id != user_id:
        return True

    if not os.path.isfile(DB_PATH):
        send_message(
            chat_id,
            "❌ فایل دیتابیس پیدا نشد.\n"
            "مسیر دیتابیس را در تنظیمات بررسی کن."
        )
        return True

    temp_path = None

    try:
        # ساخت فایل موقت برای بکاپ سالم دیتابیس
        fd, temp_path = tempfile.mkstemp(
            prefix="bot_backup_",
            suffix=".db"
        )
        os.close(fd)

        # تهیه بکاپ با روش رسمی SQLite
        with sqlite3.connect(DB_PATH, timeout=30) as source:
            with sqlite3.connect(temp_path, timeout=30) as target:
                source.backup(target)

        # بررسی سلامت فایل بکاپ
        with sqlite3.connect(temp_path) as check_db:
            result = check_db.execute(
                "PRAGMA integrity_check"
            ).fetchone()

            if not result or result[0] != "ok":
                raise RuntimeError("Database backup integrity check failed")

        # ارسال فایل به پیوی ادمین
        with open(temp_path, "rb") as backup_file:
            response = requests.post(
                API_URL + "sendDocument",
                data={
                    "chat_id": str(chat_id),
                    "caption": "✅ آخرین بکاپ دیتابیس ربات"
                },
                files={
                    "document": (
                        "bot.db",
                        backup_file,
                        "application/octet-stream"
                    )
                },
                timeout=90
            )

        try:
            result = response.json()
        except ValueError:
            result = {}

        if response.ok and result.get("ok"):
            print("Database backup sent successfully.")
        else:
            print("Backup upload failed:", result)

            send_message(
                chat_id,
                "❌ فایل بکاپ ساخته شد، اما ارسال آن ناموفق بود.\n"
                "لاگ Railway را بررسی کن."
            )

    except Exception as error:
        print("Backup error:", repr(error))

        send_message(
            chat_id,
            "❌ هنگام تهیه یا ارسال بکاپ خطایی رخ داد.\n"
            "لاگ Railway را بررسی کن."
        )

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError as error:
                print("Temporary backup cleanup error:", repr(error))

    return True
