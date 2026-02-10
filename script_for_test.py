# test_fixed_tests.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import sqlite3
from database import recreate_test_tables_fixed

def test_functions():
    """Тестируем исправленные функции"""
    print("🔍 Тестирование функций тестов...")
    
    # 1. Проверяем таблицы
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    print("\n📊 Проверка данных:")
    
    # Количество вопросов по неделям
    cursor.execute("SELECT week_num, COUNT(*) FROM tests GROUP BY week_num ORDER BY week_num")
    weeks = cursor.fetchall()
    print(f"Вопросов в тестах:")
    for week, count in weeks:
        print(f"  Неделя {week}: {count} вопросов")
    
    # Проверяем тестовые данные
    test_user_id = 918928334
    print(f"\n👤 Проверка для пользователя {test_user_id}:")
    
    # Доступные марафоны
    from database import get_user_active_arcs
    active_arcs = get_user_active_arcs(test_user_id)
    print(f"Активных марафонов: {len(active_arcs) if active_arcs else 0}")
    
    if active_arcs:
        for arc in active_arcs:
            arc_id, arc_title, start_date, end_date, access_type, arc_type = arc
            print(f"  - {arc_title} (ID: {arc_id}, тип: {arc_type}, доступ: {access_type})")
            
            # Проверяем доступные тесты
            from database import get_available_tests
            is_company = (arc_type == 'company')
            tests = get_available_tests(test_user_id, arc_id, is_company)
            print(f"    Доступно тестов: {len(tests)}")
            
            for test in tests:
                status = "✅ пройден" if test['completed'] else "📝 доступен"
                print(f"      Неделя {test['week_num']}: {status}")
    
    conn.close()

def quick_fix():
    """Быстрое исправление таблиц"""
    print("⚡ Быстрое исправление таблиц тестов...")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Просто добавляем недостающую колонку arc_id если ее нет
        cursor.execute("PRAGMA table_info(test_results)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'arc_id' not in columns:
            print("Добавляем колонку arc_id в test_results...")
            cursor.execute("ALTER TABLE test_results ADD COLUMN arc_id INTEGER")
        
        cursor.execute("PRAGMA table_info(test_progress)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if 'arc_id' not in columns:
            print("Добавляем колонку arc_id в test_progress...")
            cursor.execute("ALTER TABLE test_progress ADD COLUMN arc_id INTEGER")
        
        conn.commit()
        print("✅ Колонки добавлены")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        # Пробуем пересоздать таблицы
        recreate_test_tables_fixed()
    
    conn.close()

if __name__ == "__main__":
    print("=" * 50)
    print("ИСПРАВЛЕНИЕ СИСТЕМЫ ТЕСТОВ")
    print("=" * 50)
    
    print("\nВыберите действие:")
    print("1. Быстрое исправление (добавить недостающие колонки)")
    print("2. Полное пересоздание таблиц")
    print("3. Только тестирование функций")
    
    choice = input("Ваш выбор (1/2/3): ")
    
    if choice == "1":
        quick_fix()
    elif choice == "2":
        recreate_test_tables_fixed()
    elif choice == "3":
        test_functions()
    else:
        print("❌ Неверный выбор")
    
    print("\n✅ Готово!")
