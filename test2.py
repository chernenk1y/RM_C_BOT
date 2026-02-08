"""
Поиск всех упоминаний user_company_access
"""
import re

def find_user_company_access_references():
    print("🔍 ПОИСК user_company_access В КОДЕ")
    print("=" * 60)
    
    files = ['bot.py', 'database.py']
    
    for file_name in files:
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Ищем все упоминания
            lines = content.split('\n')
            found = False
            
            for i, line in enumerate(lines, 1):
                if 'user_company_access' in line:
                    if not found:
                        print(f"\n📄 Файл: {file_name}")
                        found = True
                    
                    # Обрезаем длинные строки
                    line_display = line.strip()
                    if len(line_display) > 100:
                        line_display = line_display[:97] + "..."
                    
                    print(f"   Строка {i}: {line_display}")
                    
                    # Предлагаем замену
                    if 'FROM user_company_access' in line.upper():
                        new_line = line.replace('user_company_access', 'user_arc_access')
                        print(f"   💡 Заменить на: {new_line.strip()}")
                    elif 'JOIN user_company_access' in line.upper():
                        new_line = line.replace('user_company_access', 'user_arc_access')
                        print(f"   💡 Заменить на: {new_line.strip()}")
            
            if not found:
                print(f"\n📄 Файл: {file_name} - упоминаний не найдено")
                
        except Exception as e:
            print(f"\n❌ Ошибка чтения {file_name}: {e}")
    
    print("\n" + "=" * 60)
    print("🎯 РЕКОМЕНДАЦИИ:")
    print("1. Замени все 'user_company_access' на 'user_arc_access'")
    print("2. В запросах используй 'company_arc_id IS NOT NULL' вместо 'access_type'")
    print("=" * 60)

if __name__ == "__main__":
    find_user_company_access_references()
