import sqlite3
import json

def check_database_functions():
    """Проверяем все функции работы с тестами в database.py"""
    print("🔍 ПРОВЕРКА ФУНКЦИЙ DATABASE.PY")
    print("=" * 60)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # 1. Проверяем конкретную запись в test_results
    print("\n📋 ПРОВЕРКА КОНКРЕТНОЙ ЗАПИСИ В test_results:")
    cursor.execute('''
        SELECT result_id, user_id, arc_id, company_arc_id, week_num, score, answers_json, completed_at
        FROM test_results 
        WHERE user_id = 918928334 AND week_num = 1
    ''')
    
    row = cursor.fetchone()
    if row:
        print(f"✅ Найдена запись:")
        print(f"   result_id: {row[0]}")
        print(f"   user_id: {row[1]}")
        print(f"   arc_id: {row[2]}")
        print(f"   company_arc_id: {row[3]}")
        print(f"   week_num: {row[4]}")
        print(f"   score: {row[5]}")
        
        # Проверяем JSON
        try:
            answers = json.loads(row[6]) if row[6] else {}
            print(f"   answers_json: OK ({len(answers)} ответов)")
        except:
            print(f"   answers_json: ERROR - невалидный JSON")
        
        print(f"   completed_at: {row[7]}")
    else:
        print("❌ Запись не найдена!")
    
    # 2. Проверяем функцию get_test_result
    print("\n📋 ТЕСТ ФУНКЦИИ get_test_result:")
    try:
        from database import get_test_result
        
        result = get_test_result(918928334, 1)
        if result:
            print(f"✅ Функция работает:")
            print(f"   result_id: {result.get('result_id')}")
            print(f"   score: {result.get('score')}")
            print(f"   answers: {len(result.get('answers', {}))} ответов")
            print(f"   completed_at: {result.get('completed_at')}")
        else:
            print("❌ Функция вернула None")
    except Exception as e:
        print(f"❌ Ошибка в get_test_result: {e}")
        import traceback
        traceback.print_exc()
    
    # 3. Проверяем функцию get_all_test_results
    print("\n📋 ТЕСТ ФУНКЦИИ get_all_test_results:")
    try:
        from database import get_all_test_results
        
        results = get_all_test_results(918928334)
        print(f"✅ Найдено результатов: {len(results)}")
        
        for i, (result_id, week_num, score, completed_at) in enumerate(results, 1):
            print(f"   {i}. Неделя {week_num}: {score}%, {completed_at}")
    except Exception as e:
        print(f"❌ Ошибка в get_all_test_results: {e}")
        import traceback
        traceback.print_exc()
    
    # 4. Проверяем SQL запросы функций
    print("\n📋 ПРОВЕРКА SQL ЗАПРОСОВ:")
    
    # Проверяем запрос из get_test_result
    print("\n🔍 SQL из get_test_result:")
    sql = '''
        SELECT result_id, score, answers_json, completed_at
        FROM test_results 
        WHERE user_id = ? AND arc_id = 1 AND week_num = ?
    '''
    print(f"   Запрос: {sql}")
    
    cursor.execute(sql, (918928334, 1))
    result = cursor.fetchone()
    print(f"   Результат: {result}")
    
    # 5. Проверяем есть ли дубликаты
    print("\n📋 ПРОВЕРКА НА ДУБЛИКАТЫ:")
    cursor.execute('''
        SELECT user_id, week_num, COUNT(*) as count
        FROM test_results 
        WHERE user_id = 918928334
        GROUP BY user_id, week_num
        HAVING COUNT(*) > 1
    ''')
    
    duplicates = cursor.fetchall()
    if duplicates:
        print("❌ Найдены дубликаты:")
        for user_id, week_num, count in duplicates:
            print(f"   Неделя {week_num}: {count} записей")
    else:
        print("✅ Дубликатов нет")
    
    # 6. Проверяем структуру записей
    print("\n📋 ПОЛНАЯ СТРУКТУРА ЗАПИСИ:")
    cursor.execute("SELECT * FROM test_results WHERE user_id = 918928334")
    row = cursor.fetchone()
    
    if row:
        print("Индексы и значения:")
        for i, value in enumerate(row):
            print(f"  [{i}] = {value}")
    
    conn.close()
    
    # 7. Проверяем импорты в bot.py
    print("\n📋 ПРОВЕРКА ИМПОРТОВ В BOT.PY:")
    try:
        with open('bot.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ищем импорты из database
        import re
        imports = re.findall(r'from database import (.*?)\n', content)
        
        if imports:
            print("✅ Найдены импорты из database:")
            for imp in imports:
                # Проверяем есть ли функции тестов
                functions = imp.split(',')
                test_funcs = [f for f in functions if 'test' in f.lower()]
                if test_funcs:
                    print(f"   📌 {imp}")
        else:
            print("❌ Не найдены импорты из database")
            
    except Exception as e:
        print(f"❌ Ошибка чтения bot.py: {e}")

def check_bot_error():
    """Ищем где возникает ошибка 'arc_id' в bot.py"""
    print("\n🔍 ПОИСК ОШИБКИ 'arc_id' В BOT.PY")
    print("=" * 60)
    
    try:
        with open('bot.py', 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Ищем строки с ошибкой arc_id
        error_lines = []
        for i, line in enumerate(lines, 1):
            if 'arc_id' in line.lower():
                error_lines.append((i, line.strip()))
        
        if error_lines:
            print(f"✅ Найдено {len(error_lines)} упоминаний 'arc_id':")
            for line_num, line_text in error_lines[:10]:  # Показываем первые 10
                print(f"   Строка {line_num}: {line_text}")
        else:
            print("❌ Не найдено упоминаний 'arc_id'")
        
        # Ищем конкретно ошибку с кавычками
        print("\n🔍 ПОИСК ОШИБКИ С 'arc_id':")
        for i, line in enumerate(lines, 1):
            if "'arc_id'" in line or '"arc_id"' in line:
                print(f"   Строка {i}: {line.strip()}")
                
        # Ищем вызовы show_test_result_details
        print("\n🔍 ВЫЗОВЫ show_test_result_details:")
        for i, line in enumerate(lines, 1):
            if 'show_test_result_details' in line:
                # Найти начало и конец вызова
                print(f"   Строка {i}: {line.strip()[:100]}...")
                
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def check_show_test_result_details():
    """Проверяем функцию show_test_result_details"""
    print("\n🔍 АНАЛИЗ ФУНКЦИИ show_test_result_details")
    print("=" * 60)
    
    try:
        with open('bot.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Ищем функцию show_test_result_details
        import re
        pattern = r'async def show_test_result_details\(.*?\):(.*?)(?=\nasync def |\n\n|$)'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            func_body = match.group(0)
            print("✅ Функция найдена")
            
            # Ищем использование arc_id в функции
            if 'arc_id' in func_body:
                print("❌ В функции используется arc_id!")
                
                # Показываем контекст
                lines = func_body.split('\n')
                for i, line in enumerate(lines):
                    if 'arc_id' in line:
                        print(f"   Строка в функции: {line.strip()}")
            else:
                print("✅ В функции НЕТ использования arc_id")
                
            # Проверяем параметры функции
            param_match = re.search(r'async def show_test_result_details\((.*?)\):', func_body)
            if param_match:
                params = param_match.group(1)
                print(f"📋 Параметры функции: {params}")
                
                # Проверяем есть ли arc_id в параметрах
                if 'arc_id' in params:
                    print("❌ arc_id есть в параметрах функции!")
                else:
                    print("✅ arc_id нет в параметрах")
        else:
            print("❌ Функция не найдена")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def main():
    print("🔬 ГЛУБОКАЯ ДИАГНОСТИКА ОШИБКИ 'arc_id'")
    print("=" * 60)
    
    check_database_functions()
    check_bot_error()
    check_show_test_result_details()
    
    print("\n🎯 ВЫВОДЫ И РЕКОМЕНДАЦИИ:")
    print("1. Проверьте строки с 'arc_id' в bot.py")
    print("2. Проверьте параметры функции show_test_result_details")
    print("3. Проверьте все вызовы этой функции")
    print("4. Убедитесь что arc_id не передается как строка с кавычками")

if __name__ == "__main__":
    main()
