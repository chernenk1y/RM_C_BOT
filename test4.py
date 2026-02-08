import sqlite3

def check_database():
    print("🔍 Проверка структуры базы данных...")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # 1. Проверяем все таблицы
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()
    
    print("\n📊 Список таблиц в базе:")
    for table in tables:
        print(f"  - {table[0]}")
    
    # 2. Проверяем таблицу payments
    print("\n🔍 Проверка таблицы payments:")
    try:
        cursor.execute("PRAGMA table_info(payments)")
        columns = cursor.fetchall()
        if columns:
            print(f"  ✅ Таблица payments существует, колонок: {len(columns)}")
            print("  Структура колонок:")
            for col in columns:
                print(f"    - {col[1]} ({col[2]})")
        else:
            print("  ❌ Таблица payments пустая или не существует")
    except sqlite3.OperationalError:
        print("  ❌ Таблица payments не существует!")
    
    # 3. Проверяем таблицу companies
    print("\n🔍 Проверка таблицы companies:")
    try:
        cursor.execute("PRAGMA table_info(companies)")
        columns = cursor.fetchall()
        if columns:
            print(f"  ✅ Таблица companies существует, колонок: {len(columns)}")
    except sqlite3.OperationalError:
        print("  ❌ Таблица companies не существует!")
    
    # 4. Проверяем таблицу company_arcs
    print("\n🔍 Проверка таблицы company_arcs:")
    try:
        cursor.execute("PRAGMA table_info(company_arcs)")
        columns = cursor.fetchall()
        if columns:
            print(f"  ✅ Таблица company_arcs существует, колонок: {len(columns)}")
    except sqlite3.OperationalError:
        print("  ❌ Таблица company_arcs не существует!")
    
    # 5. Показываем пример данных
    print("\n📋 Пример данных из таблицы payments:")
    try:
        cursor.execute("SELECT COUNT(*) FROM payments")
        count = cursor.fetchone()[0]
        print(f"  Всего платежей: {count}")
        
        if count > 0:
            cursor.execute("SELECT * FROM payments ORDER BY created_at DESC LIMIT 5")
            payments = cursor.fetchall()
            for payment in payments:
                print(f"  - ID: {payment[0]}, User: {payment[1]}, Status: {payment[4]}, Yookassa: {payment[5]}")
    except sqlite3.OperationalError:
        print("  ❌ Не удалось получить данные из payments")
    
    conn.close()
    
    print("\n✅ Проверка завершена")

if __name__ == "__main__":
    check_database()