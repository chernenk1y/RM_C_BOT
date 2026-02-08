import sqlite3
from datetime import time, datetime, timedelta
import json
import uuid
import requests
import pandas as pd
import logging

db_logger = logging.getLogger('database')

# Добавь в начало database.py после импортов:

# === ЮКАССА КОНФИГ ===
YOOKASSA_SHOP_ID = "1237681"
YOOKASSA_SECRET_KEY = "live_-Qdq_6lyDp0c1ck5HkZ_xLw5ZFtO5s7oyJquVI7hweA"
YOOKASSA_RETURN_URL = "https://t.me/SVS_365_bot"
YOOKASSA_WEBHOOK_URL = "https://svs365bot.ru/webhook/yookassa"
YOOKASSA_API_URL = "https://api.yookassa.ru/v3/payments"

# Базовые заголовки для запросов
yookassa_headers = {
    "Content-Type": "application/json",
    "Idempotence-Key": "",
    "Authorization": ""
}

# Словарь городов и их таймзон (смещение от МСК)
CITY_TIMEZONES = {
    "Калининград (-1)": -1,      # МСК-1
    "Москва (+0)": 0,           # МСК+0
    "Самара (+1)": 1,           # МСК+1
    "Екатеринбург (+2)": 2,     # МСК+2
    "Омск (+3)": 3,             # МСК+3
    "Новосибирск (+4)": 4,      # МСК+4
    "Красноярск (+4)": 4,       # МСК+4
    "Иркутск (+5)": 5,          # МСК+5
    "Якутск (+6)": 6,           # МСК+6
    "Владивосток (+7)": 7,     # МСК+7
    "Магадан (+8)": 8,         # МСК+8
    "Камчатка (+9)": 9         # МСК+9
}

def get_available_cities():
    """Возвращает список доступных городов"""
    return list(CITY_TIMEZONES.keys())

def get_user_local_time(user_id):
    """Возвращает время пользователя с учетом его таймзоны (относительно МСК)"""
    from bot import get_moscow_time  # Импортируем из bot.py
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT timezone_offset FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result and result[0] is not None:
        timezone_offset = result[0]
        # Берем московское время как базовое
        moscow_time = get_moscow_time()
        return moscow_time + timedelta(hours=timezone_offset)
    else:
        return get_moscow_time()

def set_user_timezone(user_id, city, timezone_offset):
    """Устанавливает город и таймзону пользователя"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE users SET city = ?, timezone_offset = ? 
        WHERE user_id = ?
    ''', (city, timezone_offset, user_id))
    
    conn.commit()
    conn.close()

def is_day_available(user_id, day_id):
    """Проверяет доступен ли день пользователю"""
    user_time = get_user_local_time(user_id)
    return user_time.hour >= 0  # Доступно с 00:00 местного времени

def is_assignment_available(user_id, assignment_id):
    """Проверяет доступно ли задание до 12:00 местного времени"""
    user_time = get_user_local_time(user_id)
    return user_time.hour < 23  # Доступно до 22:00

def get_user_current_day(user_id, arc_id):
    """Определяет текущий день дуги для пользователя"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Получаем дату начала доступа к дуге
    cursor.execute('''
        SELECT purchased_at FROM user_arc_access 
        WHERE user_id = ? AND arc_id = ?
    ''', (user_id, arc_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        start_date = datetime.fromisoformat(result[0])
        user_time = get_user_local_time(user_id)
        days_passed = (user_time.date() - start_date.date()).days
        return min(days_passed + 1, 40)  # Не больше 40 дней
    else:
        return 1  # Первый день по умолчанию

def save_assignment_answer(user_id, assignment_id, answer_text, answer_files):
    """Сохраняет ответ на задание (текст + файлы)"""

def get_user_assignments_for_day(user_id, day_id):
    """Получает все задания для дня пользователя"""

def update_daily_stats(user_id, arc_id, day_id, completed_count):
    """Обновляет статистику дня (пропуск/выполнение)"""

def get_day_assignments_count(day_id):
    """Возвращает количество заданий в дне"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM assignments WHERE day_id = ?', (day_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0

def init_db():
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    print("🚀 ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ С КОМПАНИЯМИ (НОВАЯ СТРУКТУРА)")
    print("=" * 50)

    # ★★★ КУРСЫ И АРКИ ★★★
    
    # Курсы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS courses (
            course_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT
        )
    ''')
    print("✅ Таблица courses создана/проверена")
    
    # Арки (стандартные шаблоны тренингов)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS arcs (
            arc_id INTEGER PRIMARY KEY,
            course_id INTEGER,
            title TEXT,
            order_num INTEGER,
            price INTEGER,
            дата_начала DATE,
            дата_окончания DATE,
            бесплатный_период INTEGER DEFAULT 7,
            status TEXT DEFAULT 'active',
            is_available BOOLEAN DEFAULT 1,
            FOREIGN KEY (course_id) REFERENCES courses(course_id)
        )
    ''')
    print("✅ Таблица arcs создана/проверена")
    
    # ★★★ КОМПАНИИ ★★★
    
    # Компании
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            join_key TEXT UNIQUE NOT NULL,
            start_date DATE NOT NULL,
            end_date DATE,
            tg_group_link TEXT,
            admin_email TEXT,
            price INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            FOREIGN KEY (created_by) REFERENCES users(user_id)
        )
    ''')
    print("✅ Таблица companies создана/проверена")
    
    # Арки компаний (связь компания + стандартный тренинг)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS company_arcs (
            company_arc_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            arc_id INTEGER NOT NULL,
            actual_start_date DATE NOT NULL,
            actual_end_date DATE,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id),
            FOREIGN KEY (arc_id) REFERENCES arcs(arc_id),
            UNIQUE(company_id, arc_id)
        )
    ''')
    print("✅ Таблица company_arcs создана/проверена")
    
    # ★★★ ПОЛЬЗОВАТЕЛИ ★★★
    
    # Пользователи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            fio TEXT,
            city TEXT,
            timezone_offset INTEGER DEFAULT 0,
            phone TEXT,
            accepted_offer BOOLEAN DEFAULT 0,
            accepted_offer_date TEXT,
            accepted_service_offer BOOLEAN DEFAULT 0,
            accepted_service_offer_date TEXT,
            is_admin BOOLEAN DEFAULT 0,
            is_blocked BOOLEAN DEFAULT 0,
            current_company_id INTEGER,  -- Текущая компания пользователя
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    print("✅ Таблица users создана/проверена")
    
    # Привязка пользователей к компаниям
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_companies (
            user_id INTEGER NOT NULL,
            company_id INTEGER NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active BOOLEAN DEFAULT 1,
            PRIMARY KEY (user_id, company_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (company_id) REFERENCES companies(company_id)
        )
    ''')
    print("✅ Таблица user_companies создана/проверена")
    
    # ★★★ ТАБЛИЦА ДОСТУПОВ - ВОЗВРАЩАЕМ СТАРОЕ НАЗВАНИЕ! ★★★
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_arc_access (
            access_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            arc_id INTEGER,  -- ★ СТАРАЯ КОЛОНКА для совместимости
            company_arc_id INTEGER, -- ★ НОВАЯ КОЛОНКА для компаний
            access_type TEXT DEFAULT 'paid',
            purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id),
            CHECK (arc_id IS NOT NULL OR company_arc_id IS NOT NULL), -- Хотя бы одна заполнена
            UNIQUE(user_id, arc_id, company_arc_id)
        )
    ''')
    print("✅ Таблица user_arc_access создана с поддержкой компаний")
    
    # ★★★ СТРУКТУРА ТРЕНИНГА ★★★
    
    # Дни тренинга (стандартные для arc_id=1)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS days (
            day_id INTEGER PRIMARY KEY AUTOINCREMENT,
            arc_id INTEGER,
            title TEXT NOT NULL,
            order_num INTEGER,
            FOREIGN KEY (arc_id) REFERENCES arcs (arc_id)
        )
    ''')
    print("✅ Таблица days создана/проверена")
    
    # Задания
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignments (
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
    print("✅ Таблица assignments создана/проверена")
    
    # ★★★ ПЛАТЕЖИ ★★★
    
    # Платежи
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_arc_id INTEGER NOT NULL,  -- ★ Связь с аркой компании
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            yookassa_payment_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            metadata TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id)
        )
    ''')
    print("✅ Таблица payments создана/проверена")
    
    # ★★★ ПРОГРЕСС И СТАТИСТИКА ★★★
    
    # Прогресс пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_progress_advanced (
            user_id INTEGER,
            assignment_id INTEGER,
            status TEXT DEFAULT 'submitted', -- 'submitted', 'approved', 'rejected'
            answer_text TEXT,
            answer_files TEXT, -- JSON с file_id
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
    print("✅ Таблица user_progress_advanced создана/проверена")
    
    # Статистика дней
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_daily_stats (
            user_id INTEGER,
            company_arc_id INTEGER,  -- ★ Связь с аркой компании
            day_id INTEGER,
            date DATE,
            assignments_completed INTEGER DEFAULT 0,
            is_skipped BOOLEAN DEFAULT FALSE,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (company_arc_id) REFERENCES company_arcs (company_arc_id),
            FOREIGN KEY (day_id) REFERENCES days (day_id),
            PRIMARY KEY (user_id, day_id)
        )
    ''')
    print("✅ Таблица user_daily_stats создана/проверена")
    
    # ★★★ ДОПОЛНИТЕЛЬНЫЕ ТАБЛИЦЫ ★★★
    
    # Бесплатные доступы
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS free_access_grants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            company_arc_id INTEGER,  -- ★ Связь с аркой компании
            granted_by INTEGER,
            granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (company_arc_id) REFERENCES company_arcs (company_arc_id)
        )
    ''')
    print("✅ Таблица free_access_grants создана/проверена")
    
    # Логи уведомлений
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            recipient_type TEXT,
            text TEXT,
            photo_id TEXT,
            success_count INTEGER,
            fail_count INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES users(user_id)
        )
    ''')
    print("✅ Таблица notification_logs создана/проверена")
    
    # Тесты
    cursor.execute('''
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
    ''')
    print("✅ Таблица tests создана/проверена")
    
    # Результаты тестов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_arc_id INTEGER NOT NULL,  -- ★ Связь с аркой компании
            week_num INTEGER NOT NULL,
            score INTEGER,
            answers_json TEXT NOT NULL,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id),
            UNIQUE(user_id, company_arc_id, week_num)
        )
    ''')
    print("✅ Таблица test_results создана/проверена")
    
    # Прогресс тестов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_progress (
            progress_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            company_arc_id INTEGER NOT NULL,  -- ★ Связь с аркой компании
            week_num INTEGER NOT NULL,
            current_question INTEGER DEFAULT 1,
            answers_json TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id),
            UNIQUE(user_id, company_arc_id, week_num)
        )
    ''')
    print("✅ Таблица test_progress создана/проверена")
    
    # ★★★ ОБЯЗАТЕЛЬНО: СОЗДАЕМ СТАНДАРТНЫЙ ТРЕНИНГ ★★★
    
    # Проверяем есть ли стандартный тренинг
    cursor.execute('SELECT 1 FROM arcs WHERE arc_id = 1')
    if not cursor.fetchone():
        print("📦 Создаю стандартный 8-недельный тренинг (arc_id=1)...")
        cursor.execute('''
            INSERT INTO arcs (arc_id, course_id, title, order_num, price, дата_начала, дата_окончания)
            VALUES (1, 1, 'Стандартный 8-недельный тренинг', 1, 0, '2026-01-01', '2026-12-31')
        ''')
        print("✅ Стандартный тренинг создан")
    
    conn.commit()
    conn.close()
    
    print("=" * 50)
    print("🎉 БАЗА ДАННЫХ ГОТОВА К РАБОТЕ С КОМПАНИЯМИ")
    print("=" * 50)
    
    # ★★★ ОБНОВЛЯЕМ ВАЖНЫЕ ФУНКЦИИ ★★★
    update_key_functions()

def update_key_functions():
    """Обновляет ключевые функции для работы с новой структурой"""
    
    print("\n🔄 ОБНОВЛЕНИЕ КЛЮЧЕВЫХ ФУНКЦИЙ")
    print("=" * 50)
    
    # Обновляем функцию check_user_arc_access чтобы она понимала новую структуру
    print("✅ Функции обновлены для работы с company_arc_id")
    print("   • check_user_arc_access теперь проверяет доступ к арке компании")
    print("   • grant_arc_access выдает доступ к арке компании")
    print("   • get_user_active_arcs работает с компаниями")
    print("=" * 50)

def create_company(name, join_key, start_date, end_date=None, tg_group_link=None, 
                   admin_email=None, price=0, created_by=None):
    """Создает новую компанию"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT INTO companies 
            (name, join_key, start_date, end_date, tg_group_link, admin_email, price, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (name, join_key, start_date, end_date, tg_group_link, admin_email, price, created_by))
        
        company_id = cursor.lastrowid
        
        # Проверяем есть ли стандартный тренинг (arc_id=1)
        cursor.execute('SELECT 1 FROM arcs WHERE arc_id = 1')
        if cursor.fetchone():
            # Автоматически создаем company_arc для стандартного тренинга
            cursor.execute('''
                INSERT INTO company_arcs (company_id, arc_id, actual_start_date, actual_end_date)
                VALUES (?, 1, ?, DATE(?, '+56 days'))
            ''', (company_id, start_date, start_date))
            
            company_arc_id = cursor.lastrowid
            print(f"✅ Создана компания: {name} (ID: {company_id}), арка: {company_arc_id}")
        else:
            print(f"⚠️ Компания создана, но нет стандартного тренинга! arc_id=1 не найден")
            company_arc_id = None
        
        conn.commit()
        return company_id, company_arc_id
        
    except sqlite3.IntegrityError:
        print(f"❌ Ключ '{join_key}' уже используется")
        return None, None
    except Exception as e:
        print(f"❌ Ошибка создания компании: {e}")
        return None, None
    finally:
        conn.close()

def get_company_by_key(join_key):
    """Получает компанию по ключу (регистронезависимо)"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT company_id, name, start_date, end_date, tg_group_link, 
               admin_email, price, is_active
        FROM companies 
        WHERE UPPER(join_key) = UPPER(?) AND is_active = 1
    ''', (join_key,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'company_id': result[0],
            'name': result[1],
            'start_date': result[2],
            'end_date': result[3],
            'tg_group_link': result[4],
            'admin_email': result[5],
            'price': result[6],
            'is_active': result[7]
        }
    return None

def get_user_company(user_id):
    """Получает компанию пользователя"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Сначала пробуем через user_companies
    cursor.execute('''
        SELECT c.company_id, c.name, c.join_key, c.start_date, c.tg_group_link,
               c.admin_email, c.price, uc.joined_at
        FROM user_companies uc
        JOIN companies c ON uc.company_id = c.company_id
        WHERE uc.user_id = ? AND uc.is_active = 1
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'company_id': result[0],
            'name': result[1],
            'join_key': result[2],
            'start_date': result[3],
            'tg_group_link': result[4],
            'admin_email': result[5],
            'price': result[6],
            'joined_at': result[7]
        }
    return None

def join_user_to_company(user_id, company_id):
    """Привязывает пользователя к компании"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Проверяем, не состоит ли уже в другой компании
        cursor.execute('SELECT company_id FROM user_companies WHERE user_id = ? AND is_active = 1', (user_id,))
        existing = cursor.fetchone()
        
        if existing:
            # Деактивируем старую привязку
            cursor.execute('UPDATE user_companies SET is_active = 0 WHERE user_id = ?', (user_id,))
        
        # Добавляем новую привязку
        cursor.execute('''
            INSERT OR REPLACE INTO user_companies (user_id, company_id, is_active)
            VALUES (?, ?, 1)
        ''', (user_id, company_id))
        
        # Обновляем current_company_id в users
        cursor.execute('UPDATE users SET current_company_id = ? WHERE user_id = ?', 
                      (company_id, user_id))
        
        conn.commit()
        print(f"✅ Пользователь {user_id} присоединился к компании {company_id}")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка привязки к компании: {e}")
        return False
    finally:
        conn.close()

def get_company_users(company_id):
    """Получает всех пользователей компании - ИСПРАВЛЕННАЯ"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            u.user_id, 
            u.username, 
            u.first_name, 
            u.fio, 
            uc.joined_at
        FROM user_companies uc
        JOIN users u ON uc.user_id = u.user_id
        WHERE uc.company_id = ? AND uc.is_active = 1
        ORDER BY uc.joined_at
    ''', (company_id,))
    
    users = cursor.fetchall()
    conn.close()
    
    return [{
        'user_id': row[0],
        'username': row[1],
        'first_name': row[2],
        'fio': row[3],
        'joined_at': row[4]
    } for row in users]

def get_all_companies():
    """Получает все компании (для админа) - ПОЛНОСТЬЮ ИСПРАВЛЕННАЯ"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # ★★★ ПОЛНЫЙ ЗАПРОС СО ВСЕМИ НУЖНЫМИ КОЛОНКАМИ ★★★
    cursor.execute('''
        SELECT 
            c.company_id, 
            c.name, 
            c.join_key, 
            c.start_date, 
            c.end_date,
            c.tg_group_link,
            c.admin_email,
            c.price,
            c.created_by,
            c.created_at,
            c.is_active,
            COUNT(DISTINCT uc.user_id) as user_count
        FROM companies c
        LEFT JOIN user_companies uc ON c.company_id = uc.company_id AND uc.is_active = 1
        WHERE c.is_active = 1
        GROUP BY c.company_id
        ORDER BY c.created_at DESC
    ''')
    
    companies = cursor.fetchall()
    conn.close()
    
    # Возвращаем только нужные для отображения поля
    return [{
        'company_id': row[0],
        'name': row[1],
        'join_key': row[2],
        'start_date': row[3],
        'end_date': row[4],
        'tg_group_link': row[5],
        'admin_email': row[6],
        'price': row[7],
        'created_by': row[8],
        'created_at': row[9],
        'is_active': row[10],
        'user_count': row[11]
    } for row in companies]

def get_company_arc(company_id):
    """Получает арку компании - ИСПРАВЛЕННАЯ"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            ca.company_arc_id, 
            ca.arc_id, 
            ca.actual_start_date, 
            ca.actual_end_date, 
            ca.status
        FROM company_arcs ca
        WHERE ca.company_id = ? AND ca.status = 'active'
        ORDER BY ca.company_arc_id DESC
        LIMIT 1
    ''', (company_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'company_arc_id': result[0],
            'arc_id': result[1],
            'actual_start_date': result[2],
            'actual_end_date': result[3],
            'status': result[4]
        }
    return None

# В функции add_user добавляем новое поле
def add_user(user_id, username, first_name):

def init_assignments():

def get_current_assignment(user_id):

def save_submission(user_id, assignment_id, file_id):

def get_submissions():

def update_submission(user_id, assignment_id, status):

def get_submission_file(user_id, assignment_id):

# Новая функция проверки оплаты
def check_payment(user_id, course_id=1):

# Функция имитации оплаты
def add_payment(user_id, course_id=1):

def get_students_with_submissions():

def upgrade_database():

def get_student_submissions(user_id):

def upgrade_database():

def create_test_submission():

def save_assignment_file(user_id, assignment_id, file_id):
    """Сохраняет файл в новую таблицу для нескольких файлов"""

def get_assignment_files(user_id, assignment_id):
    """Получает все файлы для конкретного задания пользователя"""

def get_assignment_file_count(user_id, assignment_id):
    """Получает количество файлов для задания"""

def get_course_status(user_id):
    """Получает статусы курсов для ученика"""

def get_assignment_status(user_id, course_title):
    """Получает статусы заданий в курсе"""

def check_user_arc_access(user_id, arc_id):
    """Проверяет доступ - работает и со старым arc_id и с новым company_arc_id"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        if arc_id < 1000:  # Старый arc_id
            cursor.execute('''
                SELECT 1 FROM user_arc_access 
                WHERE user_id = ? AND arc_id = ?
            ''', (user_id, arc_id))
        else:  # Новый company_arc_id
            cursor.execute('''
                SELECT 1 FROM user_arc_access 
                WHERE user_id = ? AND company_arc_id = ?
            ''', (user_id, arc_id))
        
        result = cursor.fetchone()
        return result is not None
        
    except Exception as e:
        print(f"🚨 Ошибка проверки доступа: {e}")
        return False
    finally:
        conn.close()

def get_user_skip_days(user_id, arc_id):
    """Возвращает количество пропущенных дней в дуге"""

def get_users_with_skipped_days():
    """Возвращает учеников с пропущенными днями"""

def block_user(user_id):
    """Блокирует пользователя"""

def unblock_user(user_id):
    """Разблокирует пользователя и сбрасывает пропуски"""

def test_new_structure():
    """Тестирует новую структуру БД"""

# ★★★ ВЫЗЫВАЕМ ПРИ ЗАПУСКЕ ★★★
if __name__ == "__main__":
    init_db()
    init_assignments()
    test_new_structure()

def add_test_access(user_id):
    """Добавляет тестовый доступ к первой дуге для тестирования"""

def load_courses_from_excel():
    """Загружает данные курсов из Excel файла - ПОЛНАЯ ВЕРСИЯ с поддержкой медиа"""
    
def reload_courses_data():
    """Перезагружает данные курсов из Excel - ОБНОВЛЕННАЯ ВЕРСИЯ"""

def check_database_structure():
    """Проверяет текущую структуру базы данных"""
    
def get_user_courses(user_id):
    """Получает курсы доступные пользователю"""
    
def get_course_arcs(course_title):
    """Получает дуги курса (заглушка)"""

def grant_arc_access(user_id, arc_id, access_type='paid'):
    """Выдает доступ - работает и со старым arc_id и с новым company_arc_id"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Определяем что это: arc_id или company_arc_id?
        # Если arc_id < 1000 - это старая система, иначе - company_arc_id
        if arc_id < 1000:  # Старый arc_id
            cursor.execute('''
                INSERT OR REPLACE INTO user_arc_access 
                (user_id, arc_id, company_arc_id, access_type)
                VALUES (?, ?, NULL, ?)
            ''', (user_id, arc_id, access_type))
        else:  # Новый company_arc_id
            cursor.execute('''
                INSERT OR REPLACE INTO user_arc_access 
                (user_id, arc_id, company_arc_id, access_type)
                VALUES (?, NULL, ?, ?)
            ''', (user_id, arc_id, access_type))
        
        conn.commit()
        print(f"✅ Доступ добавлен: user {user_id} -> ID {arc_id} (тип: {'arc' if arc_id < 1000 else 'company_arc'})")
        return True
    
    except Exception as e:
        print(f"🚨 Ошибка при добавлении доступа: {e}")
        return False
    finally:
        conn.close()

def check_user_company_access(user_id):
    """Проверяет доступ пользователя к любой компании - ИСПРАВЛЕННАЯ"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Проверяем наличие доступа к ЛЮБОЙ компании
        cursor.execute('''
            SELECT 1 FROM user_arc_access 
            WHERE user_id = ? AND company_arc_id IS NOT NULL
        ''', (user_id,))
        
        result = cursor.fetchone()
        
        if result:
            return True, "Есть доступ к компании"
        else:
            return False, "Нет доступа к компании"
        
    except Exception as e:
        print(f"🚨 Ошибка проверки доступа к компании: {e}")
        return False, f"Ошибка: {e}"
    finally:
        conn.close()

def is_day_available(user_id, arc_id, day_order):
    """Проверяет, доступен ли день для пользователя"""

def check_user_arc_access(user_id, arc_id):
    """Проверяет доступ пользователя к дуге"""

def check_assignments_structure():
    """Проверяет структуру заданий и их связь с днями"""

def get_day_id_by_title(day_title, arc_id):
    """Находит ID дня по его названию и ID дуги"""

def save_assignment_answer_with_day(user_id, assignment_id, day_id, answer_text, answer_files):
    """Сохраняет ответ с указанием дня"""

def get_day_id_by_title_and_arc(day_title, arc_id):
    """Находит ID дня по названию и ID дуги"""

def get_assignment_by_title_and_day(assignment_title, day_id):
    """Находит задание по названию и ID дня"""

def is_day_available_for_user(user_id, day_id):
    """Проверяет доступен ли день для выполнения заданий"""

def get_available_days_for_user(user_id, arc_id):
    """Возвращает доступные дни для пользователя в дуге"""

def mark_day_as_skipped(user_id, day_id):
    """Отмечает день как пропущенный"""

def check_and_open_missed_days(user_id):
    """Открывает текущий день если он еще не открыт"""

def get_current_arc_day(user_id, company_arc_id):
    """Возвращает текущий день арки компании для пользователя"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # 1. Получаем дату старта арки компании
    cursor.execute('SELECT actual_start_date FROM company_arcs WHERE company_arc_id = ?', (company_arc_id,))
    result = cursor.fetchone()
    
    if not result or not result[0]:
        conn.close()
        return {
            'day_id': None,
            'day_title': f"Ошибка: дата начала не указана",
            'day_number': 0,
            'total_days': 56,  # 8 недель
            'company_arc_id': company_arc_id,
            'actual_start_date': None
        }
    
    actual_start_date_str = result[0]
    
    # Преобразуем строку в дату
    try:
        if isinstance(actual_start_date_str, str):
            # Очищаем строку
            actual_start_date_str = actual_start_date_str.strip()
            if not actual_start_date_str:
                conn.close()
                return {
                    'day_id': None,
                    'day_title': f"Ошибка: пустая дата начала",
                    'day_number': 0,
                    'total_days': 56,
                    'company_arc_id': company_arc_id,
                    'actual_start_date': None
                }
            
            # Парсим дату
            if ' ' in actual_start_date_str:
                actual_start_date = datetime.strptime(actual_start_date_str, '%Y-%m-%d %H:%M:%S').date()
            else:
                actual_start_date = datetime.strptime(actual_start_date_str, '%Y-%m-%d').date()
        else:
            # Уже datetime/date объект
            actual_start_date = actual_start_date_str
            if hasattr(actual_start_date, 'date'):
                actual_start_date = actual_start_date.date()
    except Exception as e:
        print(f"🚨 Ошибка парсинга даты '{actual_start_date_str}': {e}")
        conn.close()
        return {
            'day_id': None,
            'day_title': f"Ошибка формата даты",
            'day_number': 0,
            'total_days': 56,
            'company_arc_id': company_arc_id,
            'actual_start_date': None
        }
    
    # 2. Получаем местное время пользователя
    user_time = get_user_local_time(user_id)
    user_date = user_time.date()
    
    # 3. Вычисляем текущий день арки компании
    if user_date < actual_start_date:
        current_day = 0  # Тренинг еще не начался
    else:
        current_day = (user_date - actual_start_date).days + 1
    
    # Ограничиваем максимальным количеством дней (56 дней = 8 недель)
    current_day = min(max(current_day, 0), 56)
    
    # 4. Находим соответствующий день в стандартном тренинге (arc_id = 1)
    # Предполагаем что стандартный тренинг в arcs имеет ID = 1
    cursor.execute('''
        SELECT day_id, title FROM days 
        WHERE arc_id = 1 AND order_num = ?
    ''', (current_day,))
    
    day_info = cursor.fetchone()
    conn.close()
    
    if day_info:
        day_id, day_title = day_info
        return {
            'day_id': day_id,
            'day_title': day_title,
            'day_number': current_day,
            'total_days': 56,
            'company_arc_id': company_arc_id,
            'actual_start_date': actual_start_date
        }
    
    # Если дня нет в базе
    return {
        'day_id': None,
        'day_title': f"День {current_day}",
        'day_number': current_day,
        'total_days': 56,
        'company_arc_id': company_arc_id,
        'actual_start_date': actual_start_date
    }

def get_current_arc():
    """Всегда возвращает дугу 1 для тестирования (до 10 января 2026)"""

def reload_full_from_excel():
    """ПОЛНАЯ перезагрузка всех данных из Excel (удаление старых + создание новых)"""

def get_user_skip_statistics(user_id, company_arc_id):
    """Статистика пользователя в компании"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # 1. Получаем дату старта арки компании
    cursor.execute('''
        SELECT ca.actual_start_date, ca.actual_end_date, c.name as company_name
        FROM company_arcs ca
        JOIN companies c ON ca.company_id = c.company_id
        WHERE ca.company_arc_id = ?
    ''', (company_arc_id,))
    
    arc_result = cursor.fetchone()
    
    if not arc_result or not arc_result[0]:
        conn.close()
        return {'error': 'Арка компании не найдена'}
    
    actual_start_date_str, actual_end_date, company_name = arc_result
    
    # Преобразуем дату старта
    try:
        if isinstance(actual_start_date_str, str):
            actual_start_date_str = actual_start_date_str.strip()
            if ' ' in actual_start_date_str:
                actual_start_date = datetime.strptime(actual_start_date_str, '%Y-%m-%d %H:%M:%S').date()
            else:
                actual_start_date = datetime.strptime(actual_start_date_str, '%Y-%m-%d').date()
        else:
            actual_start_date = actual_start_date_str
            if hasattr(actual_start_date, 'date'):
                actual_start_date = actual_start_date.date()
    except Exception as e:
        print(f"🚨 Ошибка парсинга даты в статистике: {e}")
        conn.close()
        return {'error': 'Ошибка формата даты'}
    
    # 2. Находим дату первого ответа в этой компании
    cursor.execute('''
        SELECT MIN(DATE(upa.submitted_at))
        FROM user_progress_advanced upa
        JOIN assignments a ON upa.assignment_id = a.assignment_id
        JOIN days d ON a.day_id = d.day_id
        WHERE upa.user_id = ? AND d.arc_id = 1  -- Стандартный тренинг
        AND upa.submitted_at IS NOT NULL
    ''', (user_id,))
    
    first_answer_result = cursor.fetchone()
    
    if not first_answer_result or not first_answer_result[0]:
        # Если нет ответов, берем дату получения доступа
        cursor.execute('''
            SELECT MIN(purchased_at) 
            FROM user_company_access 
            WHERE user_id = ? AND company_arc_id = ?
        ''', (user_id, company_arc_id))
        first_access_result = cursor.fetchone()
        
        if not first_access_result or not first_access_result[0]:
            user_start_date = actual_start_date
        else:
            user_start_date = datetime.fromisoformat(first_access_result[0]).date()
    else:
        user_start_date = first_answer_result[0]
        if isinstance(user_start_date, str):
            user_start_date = datetime.fromisoformat(user_start_date).date()
    
    # 3. Сколько ВСЕГО заданий в стандартном тренинге (56 дней)
    cursor.execute('SELECT COUNT(*) FROM assignments a JOIN days d ON a.day_id = d.day_id WHERE d.arc_id = 1')
    total_assignments = cursor.fetchone()[0]
    
    # 4. Выполненные задания (approved) в этой компании
    cursor.execute('''
        SELECT a.assignment_id, a.title, d.title as day_title, d.order_num
        FROM user_progress_advanced upa
        JOIN assignments a ON upa.assignment_id = a.assignment_id
        JOIN days d ON a.day_id = d.day_id
        WHERE upa.user_id = ? AND d.arc_id = 1 
        AND upa.status = 'approved'
    ''', (user_id,))
    
    completed_assignments_data = cursor.fetchall()
    completed_assignments = len(completed_assignments_data)
    completed_ids = {row[0] for row in completed_assignments_data}
    completed_days = {row[3] for row in completed_assignments_data}
    
    # 5. Задания на проверке (submitted)
    cursor.execute('''
        SELECT COUNT(*) 
        FROM user_progress_advanced upa
        JOIN assignments a ON upa.assignment_id = a.assignment_id
        JOIN days d ON a.day_id = d.day_id
        WHERE upa.user_id = ? AND d.arc_id = 1 
        AND upa.status = 'submitted'
    ''', (user_id,))
    
    submitted_assignments = cursor.fetchone()[0]
    
    # 6. ВСЕ задания стандартного тренинга
    cursor.execute('''
        SELECT a.assignment_id, a.title, d.title as day_title, d.order_num
        FROM assignments a
        JOIN days d ON a.day_id = d.day_id
        WHERE d.arc_id = 1
        ORDER BY d.order_num, a.assignment_id
    ''',)
    
    all_assignments = cursor.fetchall()
    
    # 7. Определяем пропущенные задания
    skipped_list = []
    today = datetime.now().date()
    
    for assignment_id, assignment_title, day_title, day_order in all_assignments:
        # Задание доступно с дня user_start_date + (day_order - 1)
        assignment_due_date = user_start_date + timedelta(days=(day_order - 1))
        
        # Пропущенным считаем если дедлайн прошел и задание не выполнено
        if today > assignment_due_date and assignment_id not in completed_ids:
            # Проверяем не на проверке ли
            cursor.execute('''
                SELECT 1 FROM user_progress_advanced 
                WHERE assignment_id = ? AND user_id = ? AND status = 'submitted'
            ''', (assignment_id, user_id))
            is_submitted = cursor.fetchone()
            
            if not is_submitted:
                skipped_list.append({
                    'day': day_title,
                    'assignment': assignment_title,
                    'day_number': day_order,
                    'due_date': assignment_due_date
                })
    
    skipped_assignments = len(skipped_list)
    
    # 8. Процент выполнения
    completion_rate = 0
    if total_assignments > 0:
        completion_rate = round((completed_assignments / total_assignments) * 100)
    
    # 9. СЕРИЯ БЕЗ ПРОПУСКОВ
    max_streak = 0
    current_streak = 0
    last_day = -1
    
    for day_order in sorted(completed_days):
        if day_order == last_day + 1:
            current_streak += 1
        else:
            current_streak = 1
        
        max_streak = max(max_streak, current_streak)
        last_day = day_order
    
    # 10. Текущий день арки компании
    current_day_info = get_current_arc_day(user_id, company_arc_id)
    current_day = current_day_info['day_number'] if current_day_info else 0
    
    conn.close()
    
    return {
        'company_name': company_name,
        'total_assignments': total_assignments,
        'completed_assignments': completed_assignments,
        'submitted_assignments': submitted_assignments,
        'skipped_assignments': skipped_assignments,
        'completion_rate': completion_rate,
        'remaining_assignments': total_assignments - completed_assignments - submitted_assignments - skipped_assignments,
        'skipped_list': skipped_list[:10],
        'start_date': user_start_date,
        'streak_days': max_streak,
        'current_day': current_day,
        'company_arc_id': company_arc_id,
        'actual_start_date': actual_start_date
    }

def check_and_notify_skipped_days(user_id, arc_id):
    """Проверяет пропуски и возвращает сообщение для пользователя"""

def get_user_offer_status(user_id):
    """Возвращает статус принятия оферты пользователем - ФИКС БАГА С 'None'"""

def accept_offer(user_id, phone=None, fio=None):
    """Сохраняет принятие оферты пользователем - ИСПРАВЛЕННАЯ (не перезаписывает)"""

def get_offer_text():
    """Читает текст оферты из файла"""

def get_service_offer_text():
    """Читает текст оферты на услуги из файла"""

def get_user_service_offer_status(user_id):
    """Возвращает статус принятия оферты на услуги"""

def accept_service_offer(user_id):
    """Сохраняет принятие оферты на услуги"""

def load_notifications_from_excel():
    """Загружает уведомления из Excel в БД"""

def get_notification(notification_type, day_num=None):
    
def get_mass_notification(notification_type, days_before=None):
    """Получает массовое уведомление"""

def check_notification_sent(user_id, notification_id, day_num=None):
    """Проверяет, отправлялось ли уже это уведомление пользователю"""

def mark_notification_sent(user_id, notification_id, day_num=None):
    """Отмечает уведомление как отправленное"""

def save_payment(user_id, company_arc_id, amount, yookassa_id, status='pending'):
    """Сохраняет платеж за доступ к тренингу компании"""
    import logging
    logger = logging.getLogger(__name__)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Проверяем существует ли таблица с правильной структурой
        cursor.execute("PRAGMA table_info(payments)")
        columns = cursor.fetchall()
        column_names = [col[1] for col in columns]
        
        # Если таблица имеет старую структуру - создаем новую
        if 'company_arc_id' not in column_names:
            logger.warning("Таблица payments имеет старую структуру, пересоздаем...")
            cursor.execute("DROP TABLE IF EXISTS payments")
            cursor.execute('''
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    company_arc_id INTEGER NOT NULL,  # ★ ИЗМЕНИЛИ: arc_id → company_arc_id ★
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    yookassa_payment_id TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    metadata TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(user_id),
                    FOREIGN KEY (company_arc_id) REFERENCES company_arcs(company_arc_id)
                )
            ''')
            conn.commit()
            logger.info("✅ Таблица payments пересоздана с поддержкой компаний")
        
        # Сохраняем платеж
        cursor.execute('''
            INSERT INTO payments (user_id, company_arc_id, amount, status, yookassa_payment_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, company_arc_id, amount, status, yookassa_id))
        
        conn.commit()
        payment_id = cursor.lastrowid
        
        logger.info(f"✅ Платеж сохранен: ID {payment_id}, user={user_id}, company_arc={company_arc_id}, amount={amount}₽, yookassa={yookassa_id}")
        return payment_id
        
    except Exception as e:
        logger.error(f"🚨 Ошибка сохранения платежа: {e}", exc_info=True)
        return None
    finally:
        conn.close()

def update_payment_status(yookassa_id, status):
    """Обновляет статус платежа для компании"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        conn = sqlite3.connect('mentor_bot.db', timeout=10)
        cursor = conn.cursor()
        
        completed_at = datetime.now().isoformat() if status == 'succeeded' else None
        
        cursor.execute('''
            UPDATE payments 
            SET status = ?, completed_at = ?
            WHERE yookassa_payment_id = ?
        ''', (status, completed_at, yookassa_id))
        
        conn.commit()
        logger.info(f"Статус платежа компании {yookassa_id} обновлен на '{status}'")
        
    except Exception as e:
        logger.error(f"Ошибка обновления статуса: {e}")
    finally:
        if conn:
            conn.close()


def check_if_can_buy_arc(user_id, arc_id):
    """Проверяет можно ли купить дугу (до 10 дня)"""

def grant_trial_access(user_id, company_arc_id):
    """Выдает БЕСПЛАТНЫЙ пробный доступ к тренингу компании (первые 3 дня)"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Проверяем существует ли такая арка компании
        cursor.execute('SELECT 1 FROM company_arcs WHERE company_arc_id = ?', (company_arc_id,))
        if not cursor.fetchone():
            print(f"🚨 Арка компании {company_arc_id} не существует!")
            return False
        
        # Проверяем состоит ли пользователь в этой компании
        cursor.execute('''
            SELECT 1 FROM user_companies uc
            JOIN company_arcs ca ON uc.company_id = ca.company_id
            WHERE uc.user_id = ? AND ca.company_arc_id = ? AND uc.is_active = 1
        ''', (user_id, company_arc_id))
        
        if not cursor.fetchone():
            print(f"🚨 Пользователь {user_id} не состоит в компании арки {company_arc_id}")
            return False
        
        # Выдаем пробный доступ
        cursor.execute('''
            INSERT OR REPLACE INTO user_arc_access (user_id, company_arc_id, access_type)
            VALUES (?, ?, 'trial')
        ''', (user_id, company_arc_id))
        
        conn.commit()
        print(f"✅ Пробный доступ к компании выдан: user {user_id} -> company_arc {company_arc_id}")
        return True
    
    except Exception as e:
        print(f"🚨 Ошибка при выдаче пробного доступа: {e}")
        return False
    
    finally:
        conn.close()
    
def create_yookassa_payment(user_id, company_arc_id, amount, trial=False, description=""):
    """Создает платеж в Юкассе для доступа к тренингу компании - С ВСЕМИ МЕТОДАМИ ОПЛАТЫ"""
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"Создание платежа для компании: user={user_id}, company_arc={company_arc_id}, amount={amount}")
    
    import requests
    import base64
    import uuid
    
    auth_string = f'{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}'
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    idempotence_key = str(uuid.uuid4())
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json",
        "Idempotence-Key": idempotence_key
    }
    
    # Получаем данные компании
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Получаем название компании и стандартного тренинга
    cursor.execute('''
        SELECT c.name as company_name, a.title as arc_title
        FROM company_arcs ca
        JOIN companies c ON ca.company_id = c.company_id
        JOIN arcs a ON ca.arc_id = a.arc_id
        WHERE ca.company_arc_id = ?
    ''', (company_arc_id,))
    
    result = cursor.fetchone()
    if result:
        company_name, arc_title = result
    else:
        company_name = f"Компания {company_arc_id}"
        arc_title = "Стандартный тренинг"
    
    # Данные пользователя для чека
    cursor.execute('SELECT phone, fio FROM users WHERE user_id = ?', (user_id,))
    user_data = cursor.fetchone()
    user_phone = user_data[0] if user_data and user_data[0] else None
    user_fio = user_data[1] if user_data and user_data[1] else f"Пользователь {user_id}"
    
    conn.close()
    
    if not description:
        if trial:
            description = f"Пробный доступ к тренингу компании '{company_name}' (3 дня)"
        else:
            description = f"Полный доступ к тренингу компании '{company_name}'"
    
    # ✅ ВСЕ МЕТОДЫ ОПЛАТЫ (сохраняем вашу логику)
    payment_data = {
        "amount": {
            "value": f"{amount:.2f}",
            "currency": "RUB"
        },
        "payment_method_data": {
            "type": "bank_card"  # Базовый метод
        },
        "confirmation": {
            "type": "redirect",
            "return_url": YOOKASSA_RETURN_URL
        },
        "description": description,
        "capture": True,
        "metadata": {
            "user_id": user_id,
            "company_arc_id": company_arc_id,  # Изменили arc_id → company_arc_id
            "trial": trial,
            "company_name": company_name,
            "arc_title": arc_title
        },
        "receipt": {
            "customer": {
                "full_name": user_fio[:256]
            },
            "items": [
                {
                    "description": f"Доступ к тренингу компании: {company_name}"[:128],
                    "quantity": "1.00",
                    "amount": {
                        "value": f"{amount:.2f}",
                        "currency": "RUB"
                    },
                    "vat_code": "1",
                    "payment_mode": "full_payment",
                    "payment_subject": "service",
                    "country_of_origin_code": "643"
                }
            ]
        }
    }
    
    # Добавляем телефон если есть
    if user_phone:
        payment_data["receipt"]["customer"]["phone"] = user_phone
    
    # ✅ Убираем payment_method_data чтобы Юкасса показывала ВСЕ методы
    payment_data.pop("payment_method_data", None)
    
    logger.info(f"Создание платежа для компании '{company_name}'")
    
    try:
        response = requests.post(
            YOOKASSA_API_URL, 
            json=payment_data, 
            headers=headers, 
            timeout=30
        )
        
        if response.status_code == 200:
            payment_info = response.json()
            payment_id = payment_info["id"]
            confirmation_url = payment_info["confirmation"]["confirmation_url"]
            
            logger.info(f"✅ Платеж для компании создан: {payment_id}")
            
            # Сохраняем в БД (используем обновленную save_payment)
            save_payment(user_id, company_arc_id, amount, payment_id, 'pending')
            
            return confirmation_url, payment_id
        else:
            error_msg = f"Ошибка {response.status_code}: {response.text}"
            logger.error(error_msg)
            return None, error_msg
            
    except Exception as e:
        error_msg = f"Исключение: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return None, error_msg

def create_yookassa_payment_simple(user_id, arc_id, amount, trial=False, description=""):
    """Резервная функция БЕЗ чека (для тестов или если основная не работает)"""

def handle_yookassa_webhook(data):
    """Обрабатывает webhook от Юкассы и отправляет уведомления"""

def check_assignment_status(user_id, assignment_id):
    """Проверяет статус задания для пользователя"""

def can_access_assignment(user_id, assignment_id, arc_id=None):
    """Проверяет может ли пользователь получить доступ к заданию"""
    
def has_new_feedback(user_id):
    """Проверяет есть ли новые непросмотренные ответы"""
    
def get_arcs_with_feedback(user_id):
    """Возвращает части с ответами и кол-вом новых (по новой логике)"""

def get_feedback_counts(user_id, arc_id):
    """Возвращает количество новых и завершенных ответов по новой логике"""

def decline_offer(user_id):
    """Упрощенная версия - без declined_offer_date"""

def get_users_for_notification(recipient_type='all'):
    """Упрощенный вариант - для 'full' берем всех кто есть в user_arc_access"""

def save_notification_log(admin_id, recipient_type, text, photo_id=None, success_count=0, fail_count=0):
    """Сохраняет лог отправки уведомлений"""

def is_admin(user_id):
    """Проверяет является ли пользователь админом"""

def set_user_as_admin(user_id):
    """Устанавливает пользователя как администратора"""

def get_user_active_arcs(user_id):
    """Получает активные части/компании пользователя"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Для админов
    cursor.execute('SELECT is_admin FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    is_admin = user and user[0] == 1
    
    if is_admin:
        # Для админа - все доступы
        cursor.execute('''
            SELECT 
                COALESCE(uaa.arc_id, uaa.company_arc_id) as id,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN a.title
                    ELSE c.name
                END as title,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN a.дата_начала
                    ELSE ca.actual_start_date
                END as start_date,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN a.дата_окончания
                    ELSE ca.actual_end_date
                END as end_date,
                uaa.access_type,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN 'arc'
                    ELSE 'company'
                END as type
            FROM user_arc_access uaa
            LEFT JOIN arcs a ON uaa.arc_id = a.arc_id
            LEFT JOIN company_arcs ca ON uaa.company_arc_id = ca.company_arc_id
            LEFT JOIN companies c ON ca.company_id = c.company_id
            WHERE uaa.user_id = ?
            ORDER BY start_date
        ''', (user_id,))
    else:
        # Для обычных пользователей
        cursor.execute('''
            SELECT 
                COALESCE(uaa.arc_id, uaa.company_arc_id) as id,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN a.title
                    ELSE c.name
                END as title,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN a.дата_начала
                    ELSE ca.actual_start_date
                END as start_date,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN a.дата_окончания
                    ELSE ca.actual_end_date
                END as end_date,
                uaa.access_type,
                CASE 
                    WHEN uaa.arc_id IS NOT NULL THEN 'arc'
                    ELSE 'company'
                END as type
            FROM user_arc_access uaa
            LEFT JOIN arcs a ON uaa.arc_id = a.arc_id
            LEFT JOIN company_arcs ca ON uaa.company_arc_id = ca.company_arc_id
            LEFT JOIN companies c ON ca.company_id = c.company_id
            WHERE uaa.user_id = ?
            AND (
                (uaa.arc_id IS NOT NULL AND a.дата_начала IS NOT NULL AND a.дата_начала != '')
                OR
                (uaa.company_arc_id IS NOT NULL AND ca.actual_start_date IS NOT NULL)
            )
            ORDER BY start_date
        ''', (user_id,))
    
    arcs = cursor.fetchall()
    conn.close()
    
    return arcs

def save_assignment_answer_with_day_auto_approve(user_id, assignment_id, day_id, answer_text, answer_files):
    """Сохраняет ответ на задание с автоматическим принятием"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Сохраняем файлы как JSON
    files_json = json.dumps(answer_files) if answer_files else None
    
    # Автоматический комментарий психолога
    auto_comment = "✅ Задание принято автоматически."
    
    # ★★ ИЗМЕНЕНИЕ: Сохраняем с флагами для автоматического комментария
    cursor.execute('''
        INSERT OR REPLACE INTO user_progress_advanced 
        (user_id, assignment_id, answer_text, answer_files, status, teacher_comment, 
         viewed_by_student, has_additional_comment, additional_comment_viewed)
        VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0)
    ''', (user_id, assignment_id, answer_text, files_json, 'approved', auto_comment))
    
    # Обновляем статистику дня если есть day_id
    if day_id:
        try:
            cursor.execute('''
                INSERT OR REPLACE INTO user_daily_stats 
                (user_id, arc_id, day_id, date, assignments_completed, is_skipped)
                VALUES (?, 
                       (SELECT d.arc_id FROM days d JOIN assignments a ON d.day_id = a.day_id WHERE a.assignment_id = ?),
                       ?, DATE('now'), 1, 0)
            ''', (user_id, assignment_id, day_id))
        except Exception as e:
            print(f"⚠️ Ошибка обновления статистики дня: {e}")
    
    conn.commit()
    conn.close()
    print(f"✅ Задание {assignment_id} автоматически принято для пользователя {user_id}")

def save_assignment_media(assignment_id, photos=None, audios=None, video_url=None):
    """Сохраняет медиа-контент для задания"""

def get_assignment_media(assignment_id):
    """Получает медиа-контент задания"""

def update_assignment_with_media_simple(file_path='courses_data.xlsx'):
    """Простая загрузка медиа с отладкой"""

def get_arcs_with_dates():
    """Возвращает дуги у которых указаны даты начала и окончания"""

def get_current_and_future_arcs():
    """Получает текущие и будущие дуги"""

def load_all_media_from_excel(file_path='courses_data.xlsx'):
    """Загружает ВСЕ типы медиа из Excel: фото, аудио, видео ссылки"""
    
def load_tests_from_excel(file_path='courses_data.xlsx'):  # ← исправлено название
    """Загружает тесты из Excel файла"""

def get_tests_for_week(week_num):
    """Получает все вопросы для теста конкретной недели"""

def get_available_tests(user_id, arc_id):
    """Возвращает доступные тесты для пользователя - НОВАЯ ЛОГИКА"""

def get_test_progress(user_id, arc_id, week_num):
    """Получает прогресс теста (если прервали)"""

def save_test_progress(user_id, arc_id, week_num, current_question, answers):
    """Сохраняет прогресс теста"""

def clear_test_progress(user_id, arc_id, week_num):
    """Очищает прогресс теста (после завершения)"""

def save_test_result(user_id, arc_id, week_num, answers, score):
    """Сохраняет результат теста"""

def get_test_result(user_id, arc_id, week_num):
    """Получает результат теста"""

def get_all_test_results(user_id, arc_id=None):
    """Получает все результаты тестов пользователя"""

def add_additional_comment_to_assignment(user_id, assignment_id, comment):
    """Добавляет дополнительный комментарий психолога к заданию"""

def get_additional_comment_status(user_id, assignment_id):
    """Проверяет статус дополнительного комментария"""
    

def mark_additional_comment_as_viewed(user_id, assignment_id):
    """Отмечает дополнительный комментарий как просмотренный"""
