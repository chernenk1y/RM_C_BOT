import sqlite3
import sys

print("🔄 Обновляю структуру базы данных...")

conn = sqlite3.connect('mentor_bot.db')
cursor = conn.cursor()

try:
    # 1. Добавляем новые поля в user_progress_advanced
    new_columns = [
        ('has_additional_comment', 'BOOLEAN DEFAULT 0'),
        ('additional_comment', 'TEXT'),
        ('comment_viewed', 'BOOLEAN DEFAULT 0'),
        ('comment_added_at', 'TIMESTAMP')
    ]
    
    for column_name, column_type in new_columns:
        try:
            cursor.execute(f'ALTER TABLE user_progress_advanced ADD COLUMN {column_name} {column_type}')
            print(f"✅ Добавлено поле: {column_name}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" in str(e):
                print(f"⚠️ Поле {column_name} уже существует")
            else:
                print(f"⚠️ Ошибка добавления поля {column_name}: {e}")
    
    # 2. Обновляем существующие записи
    # Для заданий с teacher_comment и статусом approved устанавливаем has_additional_comment = 1
    cursor.execute('''
        UPDATE user_progress_advanced 
        SET has_additional_comment = 1 
        WHERE status = 'approved' 
          AND teacher_comment IS NOT NULL 
          AND teacher_comment != '✅ Задание принято автоматически.'
    ''')
    
    updated_count = cursor.rowcount
    print(f"✅ Обновлено записей с доп. комментариями: {updated_count}")
    
    conn.commit()
    print("\n🎉 Структура БД успешно обновлена!")
    
except Exception as e:
    print(f"🚨 Критическая ошибка: {e}")
    import traceback
    traceback.print_exc()
    conn.rollback()
finally:
    conn.close()

# Проверяем структуру
print("\n🔍 Проверка структуры таблицы user_progress_advanced:")
conn = sqlite3.connect('mentor_bot.db')
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(user_progress_advanced)")
columns = cursor.fetchall()

print("Структура таблицы:")
for col in columns:
    print(f"  {col[1]} ({col[2]})")

conn.close()

print("\n✅ Готово! Запустите бота и проверьте работу.")