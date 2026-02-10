def recreate_test_tables():
    """Пересоздает таблицы тестов с поддержкой обоих типов (arc_id и company_arc_id)"""
    import sqlite3
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    print("🔄 Пересоздание таблиц тестов...")
    
    # 1. Удаляем старые таблицы
    cursor.execute("DROP TABLE IF EXISTS test_results")
    cursor.execute("DROP TABLE IF EXISTS test_progress")
    
    # 2. Создаем новую таблицу test_results с поддержкой обоих типов
    cursor.execute('''
        CREATE TABLE test_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            arc_id INTEGER,              -- ★ Для обычных арк
            company_arc_id INTEGER,      -- ★ Для компаний
            week_num INTEGER NOT NULL,
            score INTEGER,
            answers_json TEXT NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            CHECK (arc_id IS NOT NULL OR company_arc_id IS NOT NULL), -- Хотя бы одно заполнено
            UNIQUE(user_id, COALESCE(arc_id, 0), COALESCE(company_arc_id, 0), week_num)
        )
    ''')
    
    print("✅ Таблица test_results создана с поддержкой обоих типов")
    
    # 3. Создаем новую таблицу test_progress с поддержкой обоих типов
    cursor.execute('''
        CREATE TABLE test_progress (
            progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            arc_id INTEGER,              -- ★ Для обычных арк
            company_arc_id INTEGER,      -- ★ Для компаний
            week_num INTEGER NOT NULL,
            current_question INTEGER DEFAULT 1,
            answers_json TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            CHECK (arc_id IS NOT NULL OR company_arc_id IS NOT NULL), -- Хотя бы одно заполнено
            UNIQUE(user_id, COALESCE(arc_id, 0), COALESCE(company_arc_id, 0), week_num)
        )
    ''')
    
    print("✅ Таблица test_progress создана с поддержкой обоих типов")
    
    # 4. Создаем индексы
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_test_results_user ON test_results(user_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_test_results_week ON test_results(week_num)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_test_progress_user ON test_progress(user_id)')
    
    conn.commit()
    conn.close()
    
    print("🎉 Таблицы тестов пересозданы с поддержкой компаний и обычных арк")
    
    # Проверяем
    check_test_tables_structure()

def check_test_tables_structure():
    """Проверяем новую структуру"""
    import sqlite3
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    print("\n📋 Проверка новой структуры:")
    
    tables = ['test_results', 'test_progress']
    
    for table in tables:
        print(f"\n{table}:")
        cursor.execute(f"PRAGMA table_info({table})")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
    
    conn.close()
