import sqlite3
import json
from datetime import datetime

def check_test_structure():
    """Проверяет структуру таблиц тестирования"""
    print("🔍 ПРОВЕРКА СТРУКТУРЫ ТАБЛИЦ ТЕСТОВ")
    print("=" * 50)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # 1. Проверяем структуру test_results
    print("\n📋 ТАБЛИЦА test_results:")
    cursor.execute("PRAGMA table_info(test_results)")
    columns = cursor.fetchall()
    
    print("Колонки:")
    for col in columns:
        print(f"  {col[0]}. {col[1]} - {col[2]}")
    
    # 2. Проверяем структуру test_progress
    print("\n📋 ТАБЛИЦА test_progress:")
    cursor.execute("PRAGMA table_info(test_progress)")
    columns = cursor.fetchall()
    
    print("Колонки:")
    for col in columns:
        print(f"  {col[0]}. {col[1]} - {col[2]}")
    
    # 3. Проверяем есть ли arc_id в таблицах
    print("\n🔍 ПРОВЕРКА НАЛИЧИЯ arc_id:")
    
    cursor.execute("PRAGMA table_info(test_results)")
    test_results_cols = [col[1] for col in cursor.fetchall()]
    
    cursor.execute("PRAGMA table_info(test_progress)")
    test_progress_cols = [col[1] for col in cursor.fetchall()]
    
    print(f"test_results имеет arc_id: {'arc_id' in test_results_cols}")
    print(f"test_progress имеет arc_id: {'arc_id' in test_progress_cols}")
    
    # 4. Проверяем данные в test_results
    print("\n📊 ДАННЫЕ В test_results:")
    cursor.execute("SELECT * FROM test_results LIMIT 5")
    rows = cursor.fetchall()
    
    if rows:
        for row in rows:
            print(f"ID: {row[0]}, user_id: {row[1]}, company_arc_id: {row[2]}, week_num: {row[3]}, score: {row[4]}")
    else:
        print("Нет данных")
    
    # 5. Проверяем данные в test_progress
    print("\n📊 ДАННЫЕ В test_progress:")
    cursor.execute("SELECT * FROM test_progress LIMIT 5")
    rows = cursor.fetchall()
    
    if rows:
        for row in rows:
            print(f"ID: {row[0]}, user_id: {row[1]}, company_arc_id: {row[2]}, week_num: {row[3]}, current_question: {row[4]}")
    else:
        print("Нет данных")
    
    conn.close()

def check_functions():
    """Проверяет вызовы функций"""
    print("\n🔍 ПРОВЕРКА ВЫЗОВОВ ФУНКЦИЙ")
    print("=" * 50)
    
    # Импортируем функции из database
    import sys
    sys.path.append('.')
    
    try:
        from database import (
            get_test_progress, save_test_progress, 
            save_test_result, clear_test_progress,
            get_test_result, get_all_test_results
        )
        
        print("✅ Функции импортированы")
        
        # Проверяем сигнатуры функций
        import inspect
        
        print("\n📋 СИГНАТУРЫ ФУНКЦИЙ:")
        
        functions_to_check = [
            (get_test_progress, "get_test_progress"),
            (save_test_progress, "save_test_progress"),
            (save_test_result, "save_test_result"),
            (clear_test_progress, "clear_test_progress"),
            (get_test_result, "get_test_result"),
            (get_all_test_results, "get_all_test_results")
        ]
        
        for func, name in functions_to_check:
            try:
                sig = inspect.signature(func)
                print(f"{name}{sig}")
            except Exception as e:
                print(f"{name}: Ошибка {e}")
                
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")

def check_bot_calls():
    """Проверяет вызовы функций в bot.py"""
    print("\n🔍 ПРОВЕРКА ВЫЗОВОВ В bot.py")
    print("=" * 50)
    
    try:
        with open('bot.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ищем вызовы проблемных функций
        import re
        
        patterns = [
            (r'get_test_progress\([^)]+\)', 'get_test_progress'),
            (r'save_test_progress\([^)]+\)', 'save_test_progress'),
            (r'save_test_result\([^)]+\)', 'save_test_result'),
            (r'clear_test_progress\([^)]+\)', 'clear_test_progress'),
            (r'get_test_result\([^)]+\)', 'get_test_result'),
            (r'get_all_test_results\([^)]+\)', 'get_all_test_results'),
            (r'show_test_result_details\([^)]+\)', 'show_test_result_details'),
            (r'show_test_results\([^)]+\)', 'show_test_results')
        ]
        
        for pattern, func_name in patterns:
            matches = re.findall(pattern, content)
            if matches:
                print(f"\n📋 Вызовы {func_name}:")
                for match in matches[:3]:  # Показываем первые 3
                    print(f"  {match}")
    
    except FileNotFoundError:
        print("❌ Файл bot.py не найден")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def fix_table_structure():
    """Добавляет arc_id в таблицы если его нет"""
    print("\n🔧 ИСПРАВЛЕНИЕ СТРУКТУРЫ ТАБЛИЦ")
    print("=" * 50)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # 1. Проверяем test_progress
        cursor.execute("PRAGMA table_info(test_progress)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'arc_id' not in columns:
            print("➕ Добавляем arc_id в test_progress...")
            
            # Создаем временную таблицу
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_progress_new (
                    progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    arc_id INTEGER DEFAULT 1,
                    company_arc_id INTEGER,
                    week_num INTEGER NOT NULL,
                    current_question INTEGER DEFAULT 1,
                    answers_json TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Копируем данные
            cursor.execute('''
                INSERT INTO test_progress_new 
                (progress_id, user_id, company_arc_id, week_num, current_question, answers_json, started_at)
                SELECT progress_id, user_id, company_arc_id, week_num, current_question, answers_json, started_at
                FROM test_progress
            ''')
            
            # Заменяем таблицу
            cursor.execute("DROP TABLE test_progress")
            cursor.execute("ALTER TABLE test_progress_new RENAME TO test_progress")
            
            print("✅ test_progress обновлена")
        else:
            print("✅ arc_id уже есть в test_progress")
        
        # 2. Проверяем test_results
        cursor.execute("PRAGMA table_info(test_results)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'arc_id' not in columns:
            print("➕ Добавляем arc_id в test_results...")
            
            # Создаем временную таблицу
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_results_new (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    arc_id INTEGER DEFAULT 1,
                    company_arc_id INTEGER,
                    week_num INTEGER NOT NULL,
                    score INTEGER,
                    answers_json TEXT NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Копируем данные
            cursor.execute('''
                INSERT INTO test_results_new 
                (result_id, user_id, company_arc_id, week_num, score, answers_json, completed_at)
                SELECT result_id, user_id, company_arc_id, week_num, score, answers_json, completed_at
                FROM test_results
            ''')
            
            # Заменяем таблицу
            cursor.execute("DROP TABLE test_results")
            cursor.execute("ALTER TABLE test_results_new RENAME TO test_results")
            
            print("✅ test_results обновлена")
        else:
            print("✅ arc_id уже есть в test_results")
        
        conn.commit()
        print("\n🎯 СТРУКТУРА ИСПРАВЛЕНА")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        conn.rollback()
    finally:
        conn.close()

def main():
    """Основная функция"""
    print("🔬 ДИАГНОСТИКА СИСТЕМЫ ТЕСТИРОВАНИЯ")
    print("=" * 50)
    
    # 1. Проверяем структуру
    check_test_structure()
    
    # 2. Проверяем функции
    check_functions()
    
    # 3. Проверяем вызовы
    check_bot_calls()
    
    # 4. Предлагаем исправление
    print("\n🎯 ЧТО ДЕЛАТЬ:")
    print("1. Проверьте вывод выше")
    print("2. Если нет arc_id в таблицах - запустите исправление")
    print("3. Если arc_id есть - проверьте вызовы функций в bot.py")
    
    answer = input("\n🔧 Запустить исправление структуры? (y/n): ")
    if answer.lower() == 'y':
        fix_table_structure()

if __name__ == "__main__":
    main()
