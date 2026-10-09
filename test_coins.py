from database import get_connection

print("=== کاربران ثبت‌شده ===")

with get_connection() as conn:
    users = conn.execute(
        """
        SELECT user_id, first_name, username, coins
        FROM users
        ORDER BY created_at DESC
        """
    ).fetchall()

    for user in users:
        print(
            f"ID: {user['user_id']} | "
            f"Name: {user['first_name']} | "
            f"Username: {user['username']} | "
            f"Coins: {user['coins']}"
        )

    if not users:
        print("هنوز هیچ کاربری ثبت نشده است.")
        raise SystemExit

    user_id = int(input("\nآیدی عددی حساب خودت را وارد کن: "))
    amount = int(input("چند سکه اضافه کنم؟ "))

    if amount <= 0:
        print("تعداد سکه باید بیشتر از صفر باشد.")
        raise SystemExit

    result = conn.execute(
        """
        UPDATE users
        SET coins = coins + ?
        WHERE user_id = ?
        """,
        (amount, user_id)
    )

    if result.rowcount == 0:
        print("این کاربر پیدا نشد.")
    else:
        print(f"✅ {amount} سکه به حساب اضافه شد.")

        balance = conn.execute(
            "SELECT coins FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()

        print("موجودی جدید:", balance["coins"])