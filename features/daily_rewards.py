
"""Daily wheel and daily gift rewards for BaleExchangeBot."""

import random
from datetime import datetime
from zoneinfo import ZoneInfo

from database import get_connection


IRAN_TZ = ZoneInfo("Asia/Tehran")

REWARDS = {
    "🎰 چرخونه روزانه": ("wheel", "چرخونه روزانه", 1, 50),
    "🎁 هدیه روزانه": ("gift", "هدیه روزانه", 10, 25),
}


def iran_today():
    """Return today's date according to Iran's timezone."""
    return datetime.now(IRAN_TZ).date().isoformat()


def init_daily_rewards_db():
    """Create the daily reward claims table."""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_reward_claims (
                user_id INTEGER NOT NULL,
                reward_type TEXT NOT NULL,
                claim_date TEXT NOT NULL,
                amount INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, reward_type, claim_date)
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_daily_reward_claims_date
            ON daily_reward_claims(claim_date)
        """)


def handle_message(text, user_id, chat_id, send_message):
    """Handle daily wheel and gift buttons."""

    reward = REWARDS.get(text)

    if reward is None:
        return False

    reward_type, title, minimum, maximum = reward
    reward_date = iran_today()

    with get_connection() as conn:
        # Lock the database for this transaction to prevent
        # multiple rewards from rapid repeated button presses.
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT amount
            FROM daily_reward_claims
            WHERE user_id = ?
              AND reward_type = ?
              AND claim_date = ?
            """,
            (user_id, reward_type, reward_date)
        ).fetchone()

        if existing:
            previous_amount = existing["amount"]
            conn.commit()

            send_message(
                chat_id,
                f"⏳ {title} رو امروز گرفتی!\n\n"
                f"🪙 جایزه امروزت: {previous_amount} سکه\n"
                "🔄 بعد از ساعت ۰۰:۰۰ به وقت ایران "
                "دوباره می‌تونی استفاده کنی."
            )
            return True

        amount = random.randint(minimum, maximum)

        # Add the reward directly to the existing wallet balance.
        conn.execute(
            "UPDATE users SET coins = coins + ? WHERE user_id = ?",
            (amount, user_id)
        )

        # Record the claim in the same transaction as the balance update.
        conn.execute(
            """
            INSERT INTO daily_reward_claims
                (user_id, reward_type, claim_date, amount)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, reward_type, reward_date, amount)
        )

        balance_row = conn.execute(
            "SELECT coins FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        balance = balance_row["coins"] if balance_row else 0
        conn.commit()

    send_message(
        chat_id,
        f"🎉 تبریک! {title} رو بردی!\n\n"
        f"🪙 جایزه: {amount} سکه\n"
        f"💰 موجودی جدید کیف پول: {balance} سکه\n\n"
        "⏰ هر روز ساعت ۰۰:۰۰ به وقت ایران "
        "دوباره فعال می‌شه."
    )

    return True
