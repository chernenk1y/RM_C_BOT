# test_notifications.py
import database

# Запусти сначала reload_full_from_excel чтобы загрузить уведомления
database.reload_full_from_excel()

# Или если уже загружены, проверь функции:
import sqlite3
conn = sqlite3.connect('mentor_bot.db')
cursor = conn.cursor()

print("📊 Проверка загрузки уведомлений:")
cursor.execute("SELECT COUNT(*) FROM notifications")
print(f"Уведомлений в БД: {cursor.fetchone()[0]}")

cursor.execute("SELECT type, day_num, text FROM notifications LIMIT 5")
for row in cursor.fetchall():
    print(f"Тип {row[0]}, день {row[1]}: {row[2][:50]}...")

conn.close()
