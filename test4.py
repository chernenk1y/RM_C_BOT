# test_database_structure.py
import sqlite3
import sys

def check_database_structure():
    """Полная проверка структуры базы данных"""
    print("🔍 ПОЛНАЯ ПРОВЕРКА СТРУКТУРЫ БАЗЫ ДАННЫХ")
    print("=" * 70)
    
    try:
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        # 1. Получаем список всех таблиц
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        print(f"📊 ВСЕГО ТАБЛИЦ В БАЗЕ: {len(tables)}\n")
        
        # 2. Проверяем каждую таблицу
        for table_name, in tables:
            print(f"📋 ТАБЛИЦА: {table_name}")
            print("-" * 40)
            
            # Структура таблицы
            cursor.execute(f"PRAGMA table_info({table_name})")
            columns = cursor.fetchall()
            
            print(f"Колонок: {len(columns)}")
            for col in columns:
                col_id, name, type_, notnull, default, pk = col
                pk_mark = " 🔑" if pk else ""
                notnull_mark = " NOT NULL" if notnull else ""
                default_mark = f" DEFAULT {default}" if default else ""
                print(f"  {name:25} {type_:15}{notnull_mark}{default_mark}{pk_mark}")
            
            # Количество записей
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                print(f"Записей: {count}")
                
                # Для некоторых таблиц показываем примеры данных
                if count > 0 and count <= 10:
                    cursor.execute(f"SELECT * FROM {table_name} LIMIT 3")
                    sample = cursor.fetchall()
                    if sample and len(sample[0]) <= 5:  # Не показываем сложные структуры
                        print(f"Пример данных (первые 3 записи):")
                        for row in sample:
                            print(f"  {row}")
            except Exception as e:
                print(f"Ошибка подсчета записей: {e}")
            
            print()
        
        # 3. Специальная проверка структуры тестирования
        print("\n🎯 ПРОВЕРКА СИСТЕМЫ ТЕСТИРОВАНИЯ")
        print("=" * 70)
        
        # Проверяем таблицу tests
        print("\n📊 ТАБЛИЦА TESTS:")
        cursor.execute("SELECT week_num, COUNT(*) FROM tests GROUP BY week_num ORDER BY week_num")
        weeks = cursor.fetchall()
        
        if weeks:
            total_questions = 0
            print("Вопросы по неделям:")
            for week_num, count in weeks:
                print(f"  Неделя {week_num}: {count} вопросов")
                total_questions += count
            print(f"Всего вопросов: {total_questions}")
            
            # Пример вопроса
            cursor.execute("SELECT week_num, question_text, correct_option FROM tests LIMIT 1")
            sample = cursor.fetchone()
            if sample:
                week_num, question, correct = sample
                print(f"\nПример вопроса (неделя {week_num}):")
                print(f"  Вопрос: {question[:50]}...")
                print(f"  Правильный ответ: {correct}")
        else:
            print("❌ В таблице tests нет данных!")
        
        # Проверяем таблицу test_results
        print("\n📊 ТАБЛИЦА TEST_RESULTS:")
        cursor.execute("SELECT COUNT(*) FROM test_results")
        result_count = cursor.fetchone()[0]
        print(f"Всего пройденных тестов: {result_count}")
        
        if result_count > 0:
            # Статистика по пользователям и компаниям
            cursor.execute("""
                SELECT 
                    COUNT(DISTINCT user_id) as users,
                    COUNT(DISTINCT company_arc_id) as company_arcs,
                    COUNT(DISTINCT week_num) as weeks
                FROM test_results
            """)
            users, company_arcs, weeks = cursor.fetchone()
            print(f"Пользователей: {users}, Компаний: {company_arcs}, Недель: {weeks}")
            
            # Средний балл
            cursor.execute("SELECT AVG(score) FROM test_results")
            avg_score = cursor.fetchone()[0]
            if avg_score:
                print(f"Средний балл: {avg_score:.1f}/15")
        
        # Проверяем связи с компаниями
        print("\n🔗 СВЯЗИ ТЕСТОВ С КОМПАНИЯМИ:")
        
        # Проверяем company_arcs
        cursor.execute("SELECT COUNT(*) FROM company_arcs")
        company_arcs_count = cursor.fetchone()[0]
        print(f"Company arcs: {company_arcs_count}")
        
        if company_arcs_count > 0:
            cursor.execute("""
                SELECT ca.company_arc_id, c.name, ca.actual_start_date, ca.actual_end_date
                FROM company_arcs ca
                JOIN companies c ON ca.company_id = c.company_id
                LIMIT 5
            """)
            sample = cursor.fetchall()
            for company_arc_id, company_name, start_date, end_date in sample:
                print(f"  Company arc {company_arc_id}: {company_name}")
                print(f"    С {start_date} по {end_date}")
        
        # 4. Проверяем пользователей и их доступы
        print("\n👥 ПОЛЬЗОВАТЕЛИ И ДОСТУПЫ:")
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        print(f"Всего пользователей: {users_count}")
        
        # Пользователи с компаниями
        cursor.execute("""
            SELECT COUNT(DISTINCT uc.user_id) 
            FROM user_companies uc 
            WHERE uc.is_active = 1
        """)
        users_with_companies = cursor.fetchone()[0]
        print(f"Пользователей в компаниях: {users_with_companies}")
        
        # Доступы к тестированию
        cursor.execute("""
            SELECT COUNT(*) 
            FROM user_arc_access 
            WHERE company_arc_id IS NOT NULL
        """)
        company_accesses = cursor.fetchone()[0]
        print(f"Доступов к компаниям: {company_accesses}")
        
        # 5. Проверяем целостность данных
        print("\n✅ ПРОВЕРКА ЦЕЛОСТНОСТИ ДАННЫХ:")
        
        # Тесты без правильных ответов
        cursor.execute("SELECT COUNT(*) FROM tests WHERE correct_option IS NULL OR correct_option = ''")
        invalid_tests = cursor.fetchone()[0]
        if invalid_tests > 0:
            print(f"⚠️  Найдено тестов без правильного ответа: {invalid_tests}")
        else:
            print("✓ Все тесты имеют правильный ответ")
        
        # Результаты без company_arc_id
        cursor.execute("SELECT COUNT(*) FROM test_results WHERE company_arc_id IS NULL")
        invalid_results = cursor.fetchone()[0]
        if invalid_results > 0:
            print(f"⚠️  Найдено результатов тестов без company_arc_id: {invalid_results}")
        else:
            print("✓ Все результаты тестов имеют company_arc_id")
        
        # Проверяем foreign keys
        print("\n🔐 ПРОВЕРКА ВНЕШНИХ КЛЮЧЕЙ:")
        
        # test_results -> users
        cursor.execute("""
            SELECT COUNT(*) 
            FROM test_results tr
            LEFT JOIN users u ON tr.user_id = u.user_id
            WHERE u.user_id IS NULL
        """)
        orphaned_results = cursor.fetchone()[0]
        if orphaned_results > 0:
            print(f"⚠️  Найдено результатов тестов без пользователя: {orphaned_results}")
        else:
            print("✓ Все результаты привязаны к пользователям")
        
        # test_results -> company_arcs
        cursor.execute("""
            SELECT COUNT(*) 
            FROM test_results tr
            LEFT JOIN company_arcs ca ON tr.company_arc_id = ca.company_arc_id
            WHERE ca.company_arc_id IS NULL
        """)
        orphaned_company_results = cursor.fetchone()[0]
        if orphaned_company_results > 0:
            print(f"⚠️  Найдено результатов тестов без company_arc: {orphaned_company_results}")
        else:
            print("✓ Все результаты привязаны к компаниям")
        
        conn.close()
        
        print("\n" + "=" * 70)
        print("✅ ПРОВЕРКА ЗАВЕРШЕНА УСПЕШНО")
        return True
        
    except Exception as e:
        print(f"\n❌ ОШИБКА ПРОВЕРКИ: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_test_data_integrity():
    """Проверяет целостность данных для тестирования"""
    print("\n🎯 ПРОВЕРКА ЦЕЛОСТНОСТИ ДАННЫХ ТЕСТИРОВАНИЯ")
    print("=" * 70)
    
    try:
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        # 1. Проверяем структуру questions_json в test_results
        print("\n📝 ПРОВЕРКА ФОРМАТА ОТВЕТОВ В TEST_RESULTS:")
        
        cursor.execute("SELECT result_id, answers_json FROM test_results LIMIT 5")
        results = cursor.fetchall()
        
        if results:
            print("Примеры формата answers_json:")
            for result_id, answers_json in results:
                try:
                    import json
                    answers = json.loads(answers_json)
                    if isinstance(answers, list):
                        print(f"  Result {result_id}: {len(answers)} ответов")
                    else:
                        print(f"  Result {result_id}: неправильный формат ({type(answers)})")
                except json.JSONDecodeError:
                    print(f"  Result {result_id}: невалидный JSON")
        else:
            print("Нет данных в test_results")
        
        # 2. Проверяем количество вопросов на неделю
        print("\n📊 ПРОВЕРКА КОЛИЧЕСТВА ВОПРОСОВ:")
        
        cursor.execute("SELECT week_num, COUNT(*) as count FROM tests GROUP BY week_num")
        weeks_data = cursor.fetchall()
        
        if weeks_data:
            print("Вопросов по неделям:")
            for week_num, count in weeks_data:
                print(f"  Неделя {week_num}: {count} вопросов")
                
                # Проверяем что у всех вопросов есть варианты ответов
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM tests 
                    WHERE week_num = ? 
                    AND (option1 IS NULL OR option1 = '')
                """, (week_num,))
                empty_options = cursor.fetchone()[0]
                if empty_options > 0:
                    print(f"    ⚠️  Найдено вопросов без option1: {empty_options}")
        
        # 3. Проверяем корректность correct_option
        print("\n✅ ПРОВЕРКА ПРАВИЛЬНЫХ ОТВЕТОВ:")
        
        cursor.execute("""
            SELECT DISTINCT correct_option 
            FROM tests 
            WHERE correct_option IS NOT NULL
        """)
        correct_options = cursor.fetchall()
        
        if correct_options:
            print("Используемые значения correct_option:")
            for option, in correct_options:
                print(f"  '{option}'")
        
        # 4. Проверяем, что все test_results имеют score
        print("\n📈 ПРОВЕРКА БАЛЛОВ:")
        
        cursor.execute("SELECT COUNT(*) FROM test_results WHERE score IS NULL")
        null_scores = cursor.fetchone()[0]
        
        if null_scores > 0:
            print(f"⚠️  Найдено результатов без баллов: {null_scores}")
        else:
            cursor.execute("SELECT MIN(score), MAX(score), AVG(score) FROM test_results")
            min_score, max_score, avg_score = cursor.fetchone()
            print(f"Баллы: min={min_score}, max={max_score}, avg={avg_score:.1f}")
        
        # 5. Проверяем данные test_progress
        print("\n🔄 ПРОВЕРКА PROGRESS:")
        
        cursor.execute("SELECT COUNT(*) FROM test_progress")
        progress_count = cursor.fetchone()[0]
        print(f"Активных прогрессов тестов: {progress_count}")
        
        if progress_count > 0:
            cursor.execute("SELECT week_num, COUNT(*) FROM test_progress GROUP BY week_num")
            progress_by_week = cursor.fetchall()
            for week_num, count in progress_by_week:
                print(f"  Неделя {week_num}: {count} активных тестов")
        
        conn.close()
        
        print("\n" + "=" * 70)
        print("✅ ПРОВЕРКА ЦЕЛОСТНОСТИ ЗАВЕРШЕНА")
        return True
        
    except Exception as e:
        print(f"\n❌ ОШИБКА ПРОВЕРКИ ЦЕЛОСТНОСТИ: {e}")
        return False

def test_database_operations():
    """Тестирует основные операции с базой данных"""
    print("\n🧪 ТЕСТИРОВАНИЕ ОПЕРАЦИЙ С БАЗОЙ ДАННЫХ")
    print("=" * 70)
    
    try:
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        # 1. Тест: получение тестов для недели
        print("\n1. 📋 ТЕСТ: ПОЛУЧЕНИЕ ТЕСТОВ ДЛЯ НЕДЕЛИ")
        cursor.execute("SELECT week_num FROM tests LIMIT 1")
        sample_week = cursor.fetchone()
        
        if sample_week:
            week_num = sample_week[0]
            print(f"  Тестируем неделю: {week_num}")
            
            cursor.execute("""
                SELECT test_id, question_text, option1, option2, option3, option4, option5, correct_option
                FROM tests 
                WHERE week_num = ?
                ORDER BY test_id
                LIMIT 3
            """, (week_num,))
            
            tests = cursor.fetchall()
            print(f"  Найдено тестов: {len(tests)}")
            
            for i, test in enumerate(tests, 1):
                test_id, question, opt1, opt2, opt3, opt4, opt5, correct = test
                print(f"  Тест {i} (ID: {test_id}):")
                print(f"    Вопрос: {question[:40]}...")
                print(f"    Варианты: {opt1}, {opt2}, {opt3}, {opt4}, {opt5}")
                print(f"    Правильный: {correct}")
        
        # 2. Тест: создание тестового результата
        print("\n2. 📝 ТЕСТ: СОЗДАНИЕ РЕЗУЛЬТАТА ТЕСТА")
        
        # Находим существующего пользователя и компанию
        cursor.execute("SELECT user_id FROM users LIMIT 1")
        test_user = cursor.fetchone()
        
        cursor.execute("SELECT company_arc_id FROM company_arcs LIMIT 1")
        test_company_arc = cursor.fetchone()
        
        if test_user and test_company_arc:
            test_user_id = test_user[0]
            test_company_arc_id = test_company_arc[0]
            
            print(f"  Тестовый пользователь: {test_user_id}")
            print(f"  Тестовая компания: {test_company_arc_id}")
            
            # Проверяем, есть ли уже результат для этой недели
            cursor.execute("""
                SELECT result_id FROM test_results 
                WHERE user_id = ? AND company_arc_id = ? AND week_num = 1
            """, (test_user_id, test_company_arc_id))
            
            existing_result = cursor.fetchone()
            
            if not existing_result:
                print("  Создаем тестовый результат...")
                
                # Тестовые данные
                test_answers = '[{"question_id": 1, "answer": "option1", "correct": true}]'
                test_score = 1
                
                try:
                    cursor.execute("""
                        INSERT INTO test_results 
                        (user_id, company_arc_id, week_num, score, answers_json)
                        VALUES (?, ?, ?, ?, ?)
                    """, (test_user_id, test_company_arc_id, 1, test_score, test_answers))
                    
                    conn.commit()
                    print(f"  ✅ Тестовый результат создан (ID: {cursor.lastrowid})")
                except Exception as e:
                    print(f"  ❌ Ошибка создания: {e}")
            else:
                print(f"  ⚠️  Результат уже существует (ID: {existing_result[0]})")
        
        # 3. Тест: получение результатов пользователя
        print("\n3. 📊 ТЕСТ: ПОЛУЧЕНИЕ РЕЗУЛЬТАТОВ ПОЛЬЗОВАТЕЛЯ")
        
        if test_user:
            cursor.execute("""
                SELECT tr.week_num, tr.score, tr.completed_at, c.name as company_name
                FROM test_results tr
                JOIN company_arcs ca ON tr.company_arc_id = ca.company_arc_id
                JOIN companies c ON ca.company_id = c.company_id
                WHERE tr.user_id = ?
                ORDER BY tr.completed_at DESC
                LIMIT 3
            """, (test_user_id,))
            
            user_results = cursor.fetchall()
            
            if user_results:
                print(f"  Найдено результатов: {len(user_results)}")
                for week_num, score, completed_at, company_name in user_results:
                    print(f"  Неделя {week_num}: {score}/15 баллов, компания: {company_name}")
            else:
                print("  У пользователя нет результатов тестов")
        
        # 4. Тест: проверка доступных тестов
        print("\n4. 🔍 ТЕСТ: ПРОВЕРКА ДОСТУПНЫХ ТЕСТОВ")
        
        if test_user and test_company_arc:
            # Получаем все недели с тестами
            cursor.execute("SELECT DISTINCT week_num FROM tests ORDER BY week_num")
            all_weeks = [row[0] for row in cursor.fetchall()]
            
            # Получаем пройденные недели пользователем
            cursor.execute("""
                SELECT DISTINCT week_num 
                FROM test_results 
                WHERE user_id = ? AND company_arc_id = ?
            """, (test_user_id, test_company_arc_id))
            
            completed_weeks = [row[0] for row in cursor.fetchall()]
            
            print(f"  Всего недель с тестами: {len(all_weeks)}")
            print(f"  Пройденные недели: {completed_weeks}")
            print(f"  Доступные недели: {[w for w in all_weeks if w not in completed_weeks]}")
        
        conn.close()
        
        print("\n" + "=" * 70)
        print("✅ ТЕСТИРОВАНИЕ ОПЕРАЦИЙ ЗАВЕРШЕНО")
        return True
        
    except Exception as e:
        print(f"\n❌ ОШИБКА ТЕСТИРОВАНИЯ ОПЕРАЦИЙ: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Главная функция тестирования"""
    print("🔬 ТЕСТИРОВАНИЕ СТРУКТУРЫ БАЗЫ ДАННЫХ")
    print("=" * 70)
    
    # Проверяем существование файла базы данных
    import os
    if not os.path.exists('mentor_bot.db'):
        print("❌ Файл mentor_bot.db не найден!")
        print("Создайте базу данных запуском бота или командой /updatedb")
        return
    
    print(f"📁 Файл базы данных найден: {os.path.getsize('mentor_bot.db')} байт")
    
    # Выполняем проверки
    check1 = check_database_structure()
    check2 = check_test_data_integrity()
    check3 = test_database_operations()
    
    print("\n" + "=" * 70)
    print("📋 ИТОГИ ТЕСТИРОВАНИЯ:")
    print(f"  Структура базы: {'✅ ПРОЙДЕНА' if check1 else '❌ ПРОВАЛЕНА'}")
    print(f"  Целостность данных: {'✅ ПРОЙДЕНА' if check2 else '❌ ПРОВАЛЕНА'}")
    print(f"  Операции с БД: {'✅ ПРОЙДЕНА' if check3 else '❌ ПРОВАЛЕНА'}")
    
    if check1 and check2 and check3:
        print("\n🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ УСПЕШНО!")
        print("База данных готова к работе с тестированием.")
    else:
        print("\n⚠️  НЕКОТОРЫЕ ТЕСТЫ НЕ ПРОЙДЕНЫ!")
        print("Проверьте структуру базы данных и данные.")

if __name__ == "__main__":
    main()
