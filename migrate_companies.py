"""
Миграция для тестирования системы компаний
"""
import sqlite3
import sys
sys.path.append('.')  # Добавляем текущую директорию

from database import init_db, create_company

def setup_test_company():
    """Создает тестовую компанию для разработки"""
    
    # Инициализируем БД
    init_db()
    
    # Создаем тестовую компанию
    company_id, company_arc_id = create_company(
        name="Тестовая Компания",
        join_key="TEST2025",
        start_date="2026-02-08",  # Дата старта через неделю
        tg_group_link="https://t.me/+test_group",
        admin_email="admin@example.com",
        price=5000,
        created_by=1  # ID админа
    )
    
    if company_id:
        print(f"✅ Тестовая компания создана!")
        print(f"   ID компании: {company_id}")
        print(f"   ID арки компании: {company_arc_id}")
        print(f"   Ключ для входа: TEST2026")
        print(f"   Дата старта: 2026-02-08")
        print(f"   Цена: 5000 руб.")
    else:
        print("❌ Ошибка создания компании")

if __name__ == "__main__":
    setup_test_company()
