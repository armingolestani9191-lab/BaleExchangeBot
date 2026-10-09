
import os
import sqlite3

from config import DB_PATH


def get_connection():
    # مسیر کامل دیتابیس
    db_path = os.path.abspath(DB_PATH)
    db_dir = os.path.dirname(db_path)

    # ایجاد پوشه در صورت نبودن آن
    os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        timeout=30,
        isolation_level="DEFERRED"
    )

    conn.row_factory = sqlite3.Row

    # فعال‌سازی کلیدهای خارجی
    conn.execute("PRAGMA foreign_keys = ON")

    # انتظار برای آزاد شدن قفل دیتابیس
    conn.execute("PRAGMA busy_timeout = 30000")

    return conn


def init_db():
    with get_connection() as conn:
        # حالت مناسب برای دسترسی هم‌زمان به دیتابیس
        conn.execute("PRAGMA journal_mode = WAL")

        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                coins INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                order_type TEXT NOT NULL DEFAULT 'views',
                target_count INTEGER NOT NULL,
                counted_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                channel_message_id INTEGER,
                info_message_id INTEGER,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS order_clicks (
                order_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                clicked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                PRIMARY KEY (order_id, user_id),

                FOREIGN KEY (order_id)
                    REFERENCES orders(id),

                FOREIGN KEY (user_id)
                    REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                reporter_id INTEGER NOT NULL,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,

                FOREIGN KEY (order_id)
                    REFERENCES orders(id),

                FOREIGN KEY (reporter_id)
                    REFERENCES users(user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_orders_user
                ON orders(user_id);

            CREATE INDEX IF NOT EXISTS idx_orders_status
                ON orders(status);

            CREATE INDEX IF NOT EXISTS idx_reports_status
                ON reports(status);

            CREATE INDEX IF NOT EXISTS idx_order_clicks_user
                ON order_clicks(user_id);

            CREATE INDEX IF NOT EXISTS idx_reports_order
                ON reports(order_id);
        """)


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully!")
    print("Database path:", os.path.abspath(DB_PATH))
