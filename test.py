"""
Миграция данных в новую структуру user_arc_access
"""
import sqlite3

def migrate_user_arc_access():
    """Мигрирует данные в новую структуру таблицы"""
    
    print("🔄 МИГРАЦИЯ user_arc_access")
    print("=" * 50)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # 1. Создаем временную таблицу с данными
        print("1. Создаю временную таблицу...")
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_arc_access_new (
                access_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                arc_id INTEGER,
                company_arc_id INTEGER,
                access_type TEXT DEFAULT 'paid',
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id),
                UNIQUE(user_id, arc_id, company_arc_id)
            )
        ''')
        
        # 2. Копируем существующие данные
        print("2. Копирую данные...")
        
        # Проверяем есть ли старая таблица
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='user_arc_access_old'")
        if cursor.fetchone():
            # Берем из старой таблицы
            cursor.execute('SELECT user_id, arc_id, access_type, purchased_at FROM user_arc_access_old')
        else:
            # Берем из текущей
            cursor.execute('SELECT user_id, arc_id, access_type, purchased_at FROM user_arc_access WHERE arc_id IS NOT NULL')
        
        old_records = cursor.fetchall()
        print(f"   Найдено старых записей: {len(old_records)}")
        
        for user_id, arc_id, access_type, purchased_at in old_records:
            cursor.execute('''
                INSERT INTO user_arc_access_new (user_id, arc_id, company_arc_id, access_type, purchased_at)
                VALUES (?, ?, NULL, ?, ?)
            ''', (user_id, arc_id, access_type, purchased_at))
        
        # 3. Копируем данные компаний (если есть)
        try:
            cursor.execute('SELECT user_id, company_arc_id, access_type, purchased_at FROM user_company_access')
            company_records = cursor.fetchall()
            print(f"   Найдено записей компаний: {len(company_records)}")
            
            for user_id, company_arc_id, access_type, purchased_at in company_records:
                cursor.execute('''
                    INSERT INTO user_arc_access_new (user_id, arc_id, company_arc_id, access_type, purchased_at)
                    VALUES (?, NULL, ?, ?, ?)
                ''', (user_id, company_arc_id, access_type, purchased_at))
        except:
            print("   Записей компаний нет")
        
        # 4. Переименовываем таблицы
        print("3. Переименовываю таблицы...")
        cursor.execute("ALTER TABLE user_arc_access RENAME TO user_arc_access_old_backup")
        cursor.execute("ALTER TABLE user_arc_access_new RENAME TO user_arc_access")
        
        conn.commit()
        print("✅ Миграция завершена успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка миграции: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_user_arc_access()
