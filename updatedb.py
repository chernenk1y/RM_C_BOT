#!/usr/bin/env python3
"""
Скрипт миграции базы данных mentor_bot.db
Обновляет структуру без удаления данных
"""

import sqlite3
import json
import sys
import os
from datetime import datetime

def print_step(step, description):
    """Выводит информацию о шаге миграции"""
    print(f"\n{'='*60}")
    print(f"ШАГ {step}: {description}")
    print(f"{'='*60}")

def backup_database(db_path='mentor_bot.db'):
    """Создает бэкап базы данных"""
    if os.path.exists(db_path):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{db_path}.backup_{timestamp}"
        
        import shutil
        shutil.copy2(db_path, backup_path)
        print(f"✅ Создан бэкап: {backup_path}")
        return backup_path
    else:
        print(f"⚠️ Файл {db_path} не существует, создаем новую БД")
        return None

def check_table_exists(cursor, table_name):
    """Проверяет существование таблицы"""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
    return cursor.fetchone() is not None

def check_column_exists(cursor, table_name, column_name):
    """Проверяет существование колонки в таблице"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = [col[1] for col in cursor.fetchall()]
    return column_name in columns

def migrate_database():
    """Основная функция миграции"""
    db_path = 'mentor_bot.db'
    
    print("🚀 НАЧАЛО МИГРАЦИИ БАЗЫ ДАННЫХ")
    print(f"База данных: {db_path}")
    
    # Создаем бэкап
    backup_path = backup_database(db_path)
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Шаг 1: Добавляем новые колонки в assignments
        print_step(1, "Обновление таблицы assignments")
        
        # Проверяем существование таблицы assignments
        if check_table_exists(cursor, 'assignments'):
            print("✅ Таблица assignments существует")
            
            # Добавляем колонки для медиа-контента
            new_columns = [
                ('content_photos', 'TEXT'),
                ('content_audios', 'TEXT'),
                ('video_url', 'TEXT')
            ]
            
            for column_name, column_type in new_columns:
                if not check_column_exists(cursor, 'assignments', column_name):
                    try:
                        cursor.execute(f'ALTER TABLE assignments ADD COLUMN {column_name} {column_type}')
                        print(f"✅ Добавлена колонка {column_name}")
                    except sqlite3.OperationalError as e:
                        print(f"⚠️ Не удалось добавить колонку {column_name}: {e}")
                else:
                    print(f"✅ Колонка {column_name} уже существует")
        else:
            print("❌ Таблица assignments не существует, создаем...")
            cursor.execute('''
                CREATE TABLE assignments (
                    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    order_num INTEGER UNIQUE,
                    course_id INTEGER DEFAULT 1,
                    day_id INTEGER,
                    content_text TEXT,
                    content_files TEXT,
                    content_photos TEXT,
                    content_audios TEXT,
                    video_url TEXT,
                    FOREIGN KEY (course_id) REFERENCES courses (course_id),
                    FOREIGN KEY (day_id) REFERENCES days (day_id)
                )
            ''')
            print("✅ Таблица assignments создана")
        
        # Шаг 2: Обновление таблицы user_progress_advanced
        print_step(2, "Обновление таблицы user_progress_advanced")
        
        if check_table_exists(cursor, 'user_progress_advanced'):
            print("✅ Таблица user_progress_advanced существует")
            
            # Добавляем колонки для дополнительных комментариев
            new_columns_progress = [
                ('has_additional_comment', 'BOOLEAN DEFAULT 0'),
                ('additional_comment', 'TEXT'),
                ('additional_comment_viewed', 'BOOLEAN DEFAULT 0')
            ]
            
            for column_name, column_type in new_columns_progress:
                if not check_column_exists(cursor, 'user_progress_advanced', column_name):
                    try:
                        cursor.execute(f'ALTER TABLE user_progress_advanced ADD COLUMN {column_name} {column_type}')
                        print(f"✅ Добавлена колонка {column_name}")
                    except sqlite3.OperationalError as e:
                        print(f"⚠️ Не удалось добавить колонку {column_name}: {e}")
                else:
                    print(f"✅ Колонка {column_name} уже существует")
        else:
            print("❌ Таблица user_progress_advanced не существует, создаем...")
            cursor.execute('''
                CREATE TABLE user_progress_advanced (
                    user_id INTEGER,
                    assignment_id INTEGER,
                    status TEXT DEFAULT 'submitted',
                    answer_text TEXT,
                    answer_files TEXT,
                    submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    teacher_comment TEXT,
                    viewed_by_student BOOLEAN DEFAULT 0,
                    has_additional_comment BOOLEAN DEFAULT 0,
                    additional_comment TEXT,
                    additional_comment_viewed BOOLEAN DEFAULT 0,
                    FOREIGN KEY (user_id) REFERENCES users (user_id),
                    FOREIGN KEY (assignment_id) REFERENCES assignments (assignment_id),
                    PRIMARY KEY (user_id, assignment_id)
                )
            ''')
            print("✅ Таблица user_progress_advanced создана")
        
        # Шаг 3: Создание таблиц для тестов (если нужно)
        print_step(3, "Создание таблиц для тестов (опционально)")
        
        test_tables = [
            ('tests', '''
                CREATE TABLE IF NOT EXISTS tests (
                    test_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    week_num INTEGER NOT NULL,
                    question_text TEXT NOT NULL,
                    option1 TEXT,
                    option2 TEXT,
                    option3 TEXT,
                    option4 TEXT,
                    option5 TEXT,
                    correct_option TEXT NOT NULL,
                    explanation TEXT,
                    UNIQUE(week_num, question_text)
                )
            '''),
            ('test_results', '''
                CREATE TABLE IF NOT EXISTS test_results (
                    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    arc_id INTEGER NOT NULL,
                    week_num INTEGER NOT NULL,
                    score INTEGER,
                    answers_json TEXT NOT NULL,
                    completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (arc_id) REFERENCES arcs(arc_id),
                    UNIQUE(user_id, arc_id, week_num)
                )
            '''),
            ('test_progress', '''
                CREATE TABLE IF NOT EXISTS test_progress (
                    progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    arc_id INTEGER NOT NULL,
                    week_num INTEGER NOT NULL,
                    current_question INTEGER DEFAULT 1,
                    answers_json TEXT,
                    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (arc_id) REFERENCES arcs(arc_id),
                    UNIQUE(user_id, arc_id, week_num)
                )
            ''')
        ]
        
        for table_name, create_sql in test_tables:
            if not check_table_exists(cursor, table_name):
                try:
                    cursor.execute(create_sql)
                    print(f"✅ Таблица {table_name} создана")
                except sqlite3.Error as e:
                    print(f"⚠️ Не удалось создать таблицу {table_name}: {e}")
            else:
                print(f"✅ Таблица {table_name} уже существует")
        
        # Шаг 4: Проверка и обновление других таблиц
        print_step(4, "Проверка других таблиц")
        
        # Проверяем таблицу users
        if check_table_exists(cursor, 'users'):
            print("✅ Таблица users существует")
            
            # Проверяем наличие колонки is_admin
            if not check_column_exists(cursor, 'users', 'is_admin'):
                try:
                    cursor.execute('ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0')
                    print("✅ Добавлена колонка is_admin в users")
                except sqlite3.OperationalError as e:
                    print(f"⚠️ Не удалось добавить колонку is_admin: {e}")
            else:
                print("✅ Колонка is_admin уже существует")
        else:
            print("❌ Таблица users не существует!")
        
        # Шаг 5: Создание индексов для производительности
        print_step(5, "Создание индексов")
        
        indexes = [
            ('idx_user_progress_user', 'user_progress_advanced (user_id)'),
            ('idx_user_progress_assignment', 'user_progress_advanced (assignment_id)'),
            ('idx_user_progress_status', 'user_progress_advanced (status)'),
            ('idx_user_arc_access', 'user_arc_access (user_id, arc_id)'),
            ('idx_assignments_day', 'assignments (day_id)'),
            ('idx_days_arc', 'days (arc_id)')
        ]
        
        for index_name, index_sql in indexes:
            try:
                cursor.execute(f'CREATE INDEX IF NOT EXISTS {index_name} ON {index_sql}')
                print(f"✅ Индекс {index_name} создан/проверен")
            except sqlite3.Error as e:
                print(f"⚠️ Не удалось создать индекс {index_name}: {e}")
        
        # Шаг 6: Проверка целостности данных
        print_step(6, "Проверка целостности данных")
        
        try:
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()
            if result and result[0] == 'ok':
                print("✅ Целостность базы данных: OK")
            else:
                print(f"⚠️ Проблемы с целостностью: {result}")
        except sqlite3.Error as e:
            print(f"⚠️ Не удалось проверить целостность: {e}")
        
        # Сохраняем изменения
        conn.commit()
        
        print("\n" + "="*60)
        print("✅ МИГРАЦИЯ УСПЕШНО ЗАВЕРШЕНА!")
        print("="*60)
        
        # Выводим статистику
        print("\n📊 СТАТИСТИКА БАЗЫ ДАННЫХ:")
        
        tables_to_check = ['users', 'arcs', 'days', 'assignments', 'user_progress_advanced', 'user_arc_access']
        for table in tables_to_check:
            if check_table_exists(cursor, table):
                cursor.execute(f'SELECT COUNT(*) FROM {table}')
                count = cursor.fetchone()[0]
                print(f"  • {table}: {count} записей")
        
        if backup_path:
            print(f"\n💾 Бэкап сохранен: {backup_path}")
        print(f"📁 Основная база: {db_path}")
        
    except Exception as e:
        print(f"\n❌ ОШИБКА МИГРАЦИИ: {e}")
        print("Откатываем изменения...")
        conn.rollback()
        
        # Восстанавливаем из бэкапа если была ошибка
        if backup_path and os.path.exists(backup_path):
            try:
                import shutil
                shutil.copy2(backup_path, db_path)
                print(f"✅ Восстановлен из бэкапа: {backup_path}")
            except Exception as restore_error:
                print(f"❌ Не удалось восстановить из бэкапа: {restore_error}")
        
        sys.exit(1)
        
    finally:
        if 'conn' in locals():
            conn.close()

def verify_migration():
    """Проверяет успешность миграции"""
    print("\n" + "="*60)
    print("🔍 ПРОВЕРКА МИГРАЦИИ")
    print("="*60)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Проверяем новые колонки
    columns_to_check = [
        ('assignments', 'content_photos'),
        ('assignments', 'content_audios'),
        ('assignments', 'video_url'),
        ('user_progress_advanced', 'has_additional_comment'),
        ('user_progress_advanced', 'additional_comment'),
        ('user_progress_advanced', 'additional_comment_viewed'),
        ('users', 'is_admin')
    ]
    
    all_ok = True
    for table, column in columns_to_check:
        if check_column_exists(cursor, table, column):
            print(f"✅ {table}.{column}: OK")
        else:
            print(f"❌ {table}.{column}: НЕ НАЙДЕНА")
            all_ok = False
    
    # Проверяем таблицы тестов
    test_tables = ['tests', 'test_results', 'test_progress']
    for table in test_tables:
        if check_table_exists(cursor, table):
            print(f"✅ Таблица {table}: OK")
        else:
            print(f"⚠️ Таблица {table}: не создана (но это нормально для текущей версии)")
    
    conn.close()
    
    if all_ok:
        print("\n🎉 ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ УСПЕШНО!")
    else:
        print("\n⚠️ ЕСТЬ ПРОБЛЕМЫ! Некоторые колонки не добавлены.")
    
    return all_ok

if __name__ == "__main__":
    # Запускаем миграцию
    migrate_database()
    
    # Проверяем результат
    verify_migration()
    
    print("\n📋 ИНСТРУКЦИЯ ПО ЗАПУСКУ БОТА:")
    print("1. Остановите бота если он запущен")
    print("2. Загрузите обновленные файлы bot.py и database.py")
    print("3. Запустите бота командой: python bot.py")
    print("\n⚠️ ВНИМАНИЕ: Не удаляйте файл mentor_bot.db после миграции!")