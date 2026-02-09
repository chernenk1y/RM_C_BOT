# create_compatibility_tables.py
import sqlite3

def create_user_company_access_table():
    """Создает таблицу user_company_access для совместимости со старым кодом"""
    print("🔧 Создание таблицы user_company_access для совместимости...")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # 1. Проверяем существует ли таблица
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_company_access'")
    if cursor.fetchone():
        print("✅ Таблица user_company_access уже существует")
        conn.close()
        return
    
    # 2. Создаем таблицу
    cursor.execute('''
        CREATE TABLE user_company_access (
            access_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_arc_id INTEGER NOT NULL,
            purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id)
        )
    ''')
    
    # 3. Копируем данные из user_arc_access
    cursor.execute('''
        INSERT INTO user_company_access (user_id, company_arc_id, purchased_at)
        SELECT user_id, company_arc_id, purchased_at
        FROM user_arc_access
        WHERE company_arc_id IS NOT NULL
    ''')
    
    conn.commit()
    
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
