import sqlite3
import json

def fix_test_tables():
    """Исправляет таблицы тестов - добавляет arc_id и заполняет его"""
    print("🔧 ИСПРАВЛЕНИЕ ТАБЛИЦ ТЕСТОВ")
    print("=" * 50)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # 1. Проверяем test_progress - добавляем arc_id если нет
        cursor.execute("PRAGMA table_info(test_progress)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'arc_id' not in columns:
            print("➕ Добавляем arc_id в test_progress...")
            
            # Создаем новую таблицу
            cursor.execute('''
                CREATE TABLE test_progress_new (
                    progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    arc_id INTEGER DEFAULT 1,
                    company_arc_id INTEGER,
                    week_num INTEGER NOT NULL,
                    current_question INTEGER DEFAULT 1,
                    answers_json TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id)
                )
            ''')
            
            # Копируем данные, устанавливая arc_id = 1
            cursor.execute('''
                INSERT INTO test_progress_new 
                (progress_id, user_id, arc_id, company_arc_id, week_num, current_question, answers_json, started_at)
                SELECT 
                    progress_id, 
                    user_id, 
                    1 as arc_id,  -- ★ ВАЖНО: устанавливаем arc_id = 1
                    company_arc_id, 
                    week_num, 
                    current_question, 
                    answers_json, 
                    started_at
                FROM test_progress
            ''')
            
            cursor.execute("DROP TABLE test_progress")
            cursor.execute("ALTER TABLE test_progress_new RENAME TO test_progress")
            
            print("✅ test_progress обновлена (добавлен arc_id = 1)")
        else:
            print("✅ arc_id уже есть в test_progress")
            
            # Проверяем и обновляем существующие записи
            cursor.execute("UPDATE test_progress SET arc_id = 1 WHERE arc_id IS NULL OR arc_id = 0")
            updated = cursor.rowcount
            if updated > 0:
                print(f"✅ Обновлено {updated} записей в test_progress (arc_id = 1)")
        
        # 2. Обновляем test_results - устанавливаем arc_id = 1 для всех записей
        print("\n➕ Обновляем arc_id в test_results...")
        
        cursor.execute("PRAGMA table_info(test_results)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'arc_id' not in columns:
            print("❌ ОШИБКА: В test_results нет arc_id, но в диагностике сказано что есть!")
            # Создаем заново если что-то пошло не так
            cursor.execute('''
                CREATE TABLE test_results_new (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    arc_id INTEGER DEFAULT 1,
                    company_arc_id INTEGER,
                    week_num INTEGER NOT NULL,
                    score INTEGER,
                    answers_json TEXT NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id)
                )
            ''')
            
            cursor.execute('''
                INSERT INTO test_results_new 
                (result_id, user_id, arc_id, company_arc_id, week_num, score, answers_json, completed_at)
                SELECT 
                    result_id, 
                    user_id, 
                    1 as arc_id,
                    company_arc_id, 
                    week_num, 
                    score, 
                    answers_json, 
                    completed_at
                FROM test_results
            ''')
            
            cursor.execute("DROP TABLE test_results")
            cursor.execute("ALTER TABLE test_results_new RENAME TO test_results")
            print("✅ test_results пересоздана")
        else:
            # Обновляем существующие записи
            cursor.execute("UPDATE test_results SET arc_id = 1 WHERE arc_id IS NULL OR arc_id = 0")
            updated = cursor.rowcount
            
            if updated > 0:
                print(f"✅ Обновлено {updated} записей в test_results (arc_id = 1)")
            else:
                print("✅ Все записи в test_results уже имеют arc_id = 1")
        
        # 3. Проверяем результат
        print("\n🔍 ПРОВЕРКА РЕЗУЛЬТАТА:")
        
        cursor.execute('SELECT arc_id, COUNT(*) FROM test_progress GROUP BY arc_id')
        print("📊 test_progress - распределение по arc_id:")
        for arc_id, count in cursor.fetchall():
            print(f"  arc_id {arc_id}: {count} записей")
        
        cursor.execute('SELECT arc_id, COUNT(*) FROM test_results GROUP BY arc_id')
        print("📊 test_results - распределение по arc_id:")
        for arc_id, count in cursor.fetchall():
            print(f"  arc_id {arc_id}: {count} записей")
        
        conn.commit()
        print("\n🎯 ИСПРАВЛЕНИЕ ЗАВЕРШЕНО")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()

def check_after_fix():
    """Проверка после исправления"""
    print("\n🔍 ПРОВЕРКА ПОСЛЕ ИСПРАВЛЕНИЯ")
    print("=" * 50)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Проверяем данные
    cursor.execute('SELECT * FROM test_results LIMIT 3')
    rows = cursor.fetchall()
    
    print("📋 ПЕРВЫЕ 3 ЗАПИСИ test_results:")
    for row in rows:
        print(f"  ID: {row[0]}, user: {row[1]}, arc_id: {row[2]}, company_arc_id: {row[3]}, week: {row[4]}, score: {row[5]}")
    
    # Проверяем структуру
    cursor.execute("PRAGMA table_info(test_progress)")
    test_progress_cols = [col[1] for col in cursor.fetchall()]
    
    cursor.execute("PRAGMA table_info(test_results)")
    test_results_cols = [col[1] for col in cursor.fetchall()]
    
    print(f"\n📋 test_progress имеет arc_id: {'arc_id' in test_progress_cols}")
    print(f"📋 test_results имеет arc_id: {'arc_id' in test_results_cols}")
    
    conn.close()

if __name__ == "__main__":
    fix_test_tables()
    check_after_fix()
