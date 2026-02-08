# check_payment_status.py
import requests
import base64
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_API_URL

def check_payment_status(payment_id):
    """Проверяет статус платежа напрямую через API"""
    print(f"🔍 Проверка статуса платежа: {payment_id}")
    
    auth_string = f'{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}'
    encoded_auth = base64.b64encode(auth_string.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_auth}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.get(f"{YOOKASSA_API_URL}/{payment_id}", headers=headers, timeout=10)
        
        print(f"Статус ответа: {response.status_code}")
        
        if response.status_code == 200:
            payment_info = response.json()
            print(f"✅ Платеж найден:")
            print(f"  ID: {payment_info.get('id')}")
            print(f"  Статус: {payment_info.get('status')}")
            print(f"  Сумма: {payment_info.get('amount', {}).get('value')} {payment_info.get('amount', {}).get('currency')}")
            print(f"  Описание: {payment_info.get('description')}")
            print(f"  Создан: {payment_info.get('created_at')}")
            
            # Проверяем в нашей базе
            import sqlite3
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM payments WHERE yookassa_payment_id = ?", (payment_id,))
            payment_db = cursor.fetchone()
            
            if payment_db:
                print(f"\n✅ Платеж в нашей БД:")
                print(f"  ID: {payment_db[0]}")
                print(f"  User ID: {payment_db[1]}")
                print(f"  Company Arc ID: {payment_db[2]}")
                print(f"  Amount: {payment_db[3]}")
                print(f"  Status: {payment_db[4]}")
            else:
                print(f"\n❌ Платеж не найден в нашей БД!")
            
            conn.close()
        else:
            print(f"❌ Ошибка: {response.status_code}")
            print(f"Ответ: {response.text}")
            
    except Exception as e:
        print(f"❌ Исключение: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        payment_id = sys.argv[1]
    else:
        # Используем последний платеж из консоли
        payment_id = "311ae380-000f-5000-b000-1223c4f0a52d"
    
    check_payment_status(payment_id)
