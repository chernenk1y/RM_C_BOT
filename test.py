# test_structure.py
import sqlite3

def check_test_tables():
    """Проверяем структуру таблиц тестов"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    print("🔍 Проверка структуры таблиц тестов:")
    
    # 1. Таблица tests
    print("\n1. Таблица tests:")
    cursor.execute("PRAGMA table_info(tests)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"   - {col[1]} ({col[2]})")
    
    # 2. Таблица test_results
    print("\n2. Таблица test_results:")
    cursor.execute("PRAGMA table_info(test_results)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"   - {col[1]} ({col[2]})")
    
    # 3. Таблица test_progress
    print("\n3. Таблица test_progress:")
    cursor.execute("PRAGMA table_info(test_progress)")
    columns = cursor.fetchall()
    for col in columns:
        print(f"   - {col[1]} ({col[2]})")
    
    # 4. Пример данных
    print("\n4. Пример данных в tests:")
    cursor.execute("SELECT week_num, COUNT(*) FROM tests GROUP BY week_num ORDER BY week_num")
    weeks = cursor.fetchall()
    for week, count in weeks:
        print(f"   - Неделя {week}: {count} вопросов")
    
    conn.close()

if __name__ == "__main__":
    check_test_tables()
    cursor.execute("SELECT COUNT(*) FROM user_company_access")
    count = cursor.fetchone()[0]
    
    print(f"✅ Таблица user_company_access создана, записей: {count}")
    
    conn.close()

def update_existing_functions():
    """Обновляем функции, которые используют старую таблицу"""
    print("\n📝 Обновление функций для работы с новой структурой...")
    
    # Пока просто сообщаем какие функции нужно обновить
    print("""
    Функции для проверки:
    1. get_user_skip_statistics - УЖЕ ИСПРАВЛЕНА
    2. check_user_company_access - должна использовать user_arc_access
    3. Любые другие функции, которые используют user_company_access
    """)

if __name__ == "__main__":
    print("=" * 50)
    print("СОЗДАНИЕ СОВМЕСТИМЫХ ТАБЛИЦ")
    print("=" * 50)
    
    create_user_company_access_table()
    update_existing_functions()
    
    print("\n🎉 Готово! Старые функции теперь будут работать.")
