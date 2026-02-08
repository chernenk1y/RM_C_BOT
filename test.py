# check_access.py
import sqlite3
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def check_user_access(user_id):
    """Проверяем доступы пользователя"""
    print(f"🔍 Проверка доступа пользователя {user_id}")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    print("\n1. Проверяем user_arc_access:")
    cursor.execute('''
        SELECT access_id, arc_id, company_arc_id, access_type, purchased_at 
        FROM user_arc_access 
        WHERE user_id = ?
    ''', (user_id,))
    
    accesses = cursor.fetchall()
    
    if accesses:
        print(f"✅ Найдено доступов: {len(accesses)}")
        for access in accesses:
            print(f"   - ID: {access[0]}, Arc: {access[1]}, Company Arc: {access[2]}, Type: {access[3]}, Date: {access[4]}")
    else:
        print("❌ Нет записей в user_arc_access")
    
    print("\n2. Проверяем компанию пользователя:")
    cursor.execute('''
        SELECT uc.company_id, c.name, c.start_date, c.price
        FROM user_companies uc
        JOIN companies c ON uc.company_id = c.company_id
        WHERE uc.user_id = ? AND uc.is_active = 1
    ''', (user_id,))
    
    company = cursor.fetchone()
    
    if company:
        company_id, company_name, start_date, price = company
        print(f"✅ Компания найдена:")
        print(f"   - ID: {company_id}")
        print(f"   - Название: {company_name}")
        print(f"   - Старт: {start_date}")
        print(f"   - Цена: {price}₽")
    else:
        print("❌ Пользователь не в компании")
    
    print("\n3. Проверяем арку компании:")
    if company:
        cursor.execute('''
            SELECT ca.company_arc_id, ca.arc_id, ca.actual_start_date, ca.actual_end_date
            FROM company_arcs ca
            WHERE ca.company_id = ? AND ca.status = 'active'
        ''', (company_id,))
        
        company_arc = cursor.fetchone()
        
        if company_arc:
            company_arc_id, arc_id, start_date, end_date = company_arc
            print(f"✅ Арка компании найдена:")
            print(f"   - ID: {company_arc_id}")
            print(f"   - Arc ID: {arc_id}")
            print(f"   - Старт: {start_date}")
            print(f"   - Окончание: {end_date}")
        else:
            print("❌ У компании нет активной арки")
    
    print("\n4. Проверяем платежи:")
    cursor.execute('''
        SELECT id, company_arc_id, amount, status, yookassa_payment_id
        FROM payments 
        WHERE user_id = ? 
        ORDER BY created_at DESC
    ''', (user_id,))
    
    payments = cursor.fetchall()
    
    if payments:
        print(f"✅ Найдено платежей: {len(payments)}")
        for p in payments:
            print(f"   - ID: {p[0]}, Company Arc: {p[1]}, Amount: {p[2]}₽, Status: {p[3]}, Yookassa: {p[4]}")
    else:
        print("❌ Нет платежей")
    
    conn.close()
    
    return bool(accesses)

def fix_access(user_id):
    """Исправляем доступ вручную"""
    print(f"\n🔧 Исправление доступа для пользователя {user_id}")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # 1. Находим компанию пользователя
    cursor.execute('''
        SELECT uc.company_id
        FROM user_companies uc
        WHERE uc.user_id = ? AND uc.is_active = 1
    ''', (user_id,))
    
    company = cursor.fetchone()
    
    if not company:
        print("❌ Пользователь не в компании")
        return False
    
    company_id = company[0]
    
    # 2. Находим арку компании
    cursor.execute('''
        SELECT ca.company_arc_id
        FROM company_arcs ca
        WHERE ca.company_id = ? AND ca.status = 'active'
    ''', (company_id,))
    
    company_arc = cursor.fetchone()
    
    if not company_arc:
        print("❌ У компании нет активной арки")
        return False
    
    company_arc_id = company_arc[0]
    
    # 3. Проверяем есть ли доступ
    cursor.execute('''
        SELECT 1 FROM user_arc_access 
        WHERE user_id = ? AND company_arc_id = ?
    ''', (user_id, company_arc_id))
    
    if cursor.fetchone():
        print("✅ Доступ уже есть")
        return True
    
    # 4. Создаем доступ
    cursor.execute('''
        INSERT INTO user_arc_access (user_id, company_arc_id, access_type)
        VALUES (?, ?, 'paid')
    ''', (user_id, company_arc_id))
    
    conn.commit()
    
    print(f"✅ Доступ создан: user={user_id}, company_arc={company_arc_id}")
    
    # 5. Проверяем
    cursor.execute('''
        SELECT access_id, purchased_at 
        FROM user_arc_access 
        WHERE user_id = ? AND company_arc_id = ?
    ''', (user_id, company_arc_id))
    
    access = cursor.fetchone()
    
    if access:
        print(f"✅ Подтверждение: доступ ID={access[0]}, дата={access[1]}")
    
    conn.close()
    return True

if __name__ == "__main__":
    user_id = 918928334  # Ваш ID
    
    print("=" * 50)
    print("ПРОВЕРКА ДОСТУПА ПОЛЬЗОВАТЕЛЯ")
    print("=" * 50)
    
    has_access = check_user_access(user_id)
    
    if not has_access:
        print(f"\n⚠️  У пользователя {user_id} нет доступа!")
        
        response = input("Исправить доступ? (y/n): ")
        if response.lower() == 'y':
            fix_access(user_id)
            
            print("\n📊 Проверка после исправления:")
            check_user_access(user_id)
    else:
        print(f"\n✅ У пользователя {user_id} есть доступ!")
