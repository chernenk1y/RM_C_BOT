import sqlite3
conn = sqlite3.connect('mentor_bot.db')
cursor = conn.cursor()

# Проверь структуру таблицы
cursor.execute("PRAGMA table_info(user_arc_access)")
print("Структура user_arc_access:")
for col in cursor.fetchall():
    print(f"  {col[1]} ({col[2]})")

# Проверь данные
cursor.execute("SELECT * FROM user_arc_access")
print("\nДанные в user_arc_access:")
for row in cursor.fetchall():
    print(f"  {row}")

conn.close()
