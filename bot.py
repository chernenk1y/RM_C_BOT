import sqlite3
import json
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, JobQueue, CallbackQueryHandler
from telegram.helpers import escape_markdown
from datetime import datetime, timezone, timedelta, time
from database import (
    create_yookassa_payment,
    save_payment,  
    update_payment_status,
    check_if_can_buy_arc,
    grant_trial_access,
    init_db, add_user, init_assignments, get_submissions, 
    update_submission, get_submission_file, check_payment, 
    add_payment, upgrade_database, get_students_with_submissions, 
    get_student_submissions, create_test_submission, save_submission,
    save_assignment_file, get_assignment_files, get_assignment_file_count, 
    get_course_status, get_assignment_status, get_available_cities, 
    CITY_TIMEZONES, set_user_timezone,
    save_assignment_answer,
    check_user_arc_access,
    get_user_courses,
    grant_arc_access,
    is_day_available_for_user,
    get_available_days_for_user,
    mark_day_as_skipped,
    check_and_open_missed_days,
    get_day_id_by_title_and_arc,
    get_assignment_by_title_and_day,
    get_notification,
    get_mass_notification,
    get_user_local_time,
    get_user_access_type,
    set_user_as_admin
)
import uuid
import requests
import base64
import sys
import asyncio
from aiohttp import web
import logging
from urllib.parse import quote

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot_payments.log', encoding='utf-8'),
    ]
)

# Отключаем шумные библиотеки
for lib in ['httpx', 'httpcore', 'apscheduler', 'telegram']:
    logging.getLogger(lib).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.info("=== Бот запущен с логированием платежей ===")

from config import ADMIN_ID, ADMIN_IDS

def split_message(text, max_length=4096):
    """Разбивает длинное сообщение на части по max_length символов с учетом ссылок и Markdown"""
    if len(text) <= max_length:
        return [text]
    
    parts = []
    
    # Находим все ссылки в тексте и их позиции
    import re
    url_pattern = re.compile(r'https?://\S+')
    urls = list(url_pattern.finditer(text))
    
    # Находим все Telegram-ссылки отдельно (t.me, telegram.me)
    tg_pattern = re.compile(r'(?:t\.me|telegram\.me)/\S+')
    tg_urls = list(tg_pattern.finditer(text))
    
    # Объединяем все найденные ссылки
    all_links = urls + tg_urls
    
    current_pos = 0
    
    while current_pos < len(text):
        # Определяем, где можно безопасно разбить текст
        split_pos = min(current_pos + max_length, len(text))
        
        # Проверяем, не разрезаем ли мы ссылку
        for link in all_links:
            link_start, link_end = link.span()
            
            # Если ссылка пересекает границу разреза
            if link_start < split_pos < link_end:
                # Переносим разрез на конец ссылки
                split_pos = link_end
                break
        
        # Проверяем, не разрезаем ли мы посреди слова/предложения
        if split_pos < len(text):
            # Ищем хорошее место для разрыва
            for delimiter in ['\n\n', '\n', '. ', '! ', '? ', ' ', ', ']:
                # Ищем последнее вхождение разделителя ДО split_pos
                pos = text.rfind(delimiter, current_pos, split_pos - 100)
                if pos > current_pos:
                    split_pos = pos + len(delimiter)
                    break
        
        part = text[current_pos:split_pos].strip()
        if part:
            parts.append(part)
        
        current_pos = split_pos
    
    # Проверяем, не слишком ли длинные части
    final_parts = []
    for part in parts:
        if len(part) <= max_length:
            final_parts.append(part)
        else:
            # Если часть все еще слишком длинная, разбиваем жестко
            final_parts.extend([part[i:i+max_length] for i in range(0, len(part), max_length)])
    
    return final_parts

def is_admin(user_id):
    """Проверяет является ли пользователь админом"""
    return user_id == ADMIN_ID or user_id in ADMIN_IDS

TOKEN = "8524842145:AAEU6gk92Z1CZjySZ4ZkoPQNphByfjyaGwk"
init_db()

def get_moscow_time():
    """Фиксированное московское время (UTC+3) без таймзоны"""
    utc_now = datetime.now(timezone.utc)
    moscow_time = utc_now + timedelta(hours=3)
    return moscow_time.replace(tzinfo=None)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.message.from_user
    add_user(user.id, user.username, user.first_name)
    
    from database import get_user_company
    
    user_company = get_user_company(user.id)
    
    keyboard = [
        ["📚 Мои задания", "🎯 Купить тренинг"],
        ["👤 Профиль", "🛠 Тех.поддержка"]
    ]
    
    # Если есть компания, добавляем кнопку перехода в группу
    if user_company and user_company.get('tg_group_link'):
        keyboard.append(["👥 Группа компании"])
    
    if has_any_access(user.id) or user.id == ADMIN_ID:
        keyboard.append(["👥 Сообщество психолога"])
    
    if is_admin(user.id):
        keyboard.append(["👨‍🏫 Проверка заданий"])
        keyboard.append(["⚙️ Инструменты администратора"])
        keyboard.append(["🏢 Управление компаниями"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_message = f"Приветствую вас, {user.first_name}!"
    
    if user_company:
        welcome_message += f"\n\n🏢 **Ваша компания:** {user_company['name']}"
        welcome_message += f"\n📅 **Тренинг стартует:** {user_company['start_date']}"
    
    welcome_message += "\n\nВыберите действие:"
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup
    )

async def admin_tools_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню инструментов администратора"""
    context.user_data['current_section'] = 'admin_tools'
    
    keyboard = [
        ["🔧 Изменение доступа"],
        ["🔔 Отправить уведомление"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "⚙️ **Инструменты администратора**\n\n"
        "Выберите инструмент:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    print(f"🔍 Кнопка нажата: '{text}'")

    # ★★★ НОВЫЕ КНОПКИ ДЛЯ КОМПАНИЙ ★★★
    if text == "🔑 Ввести ключ компании":
        await enter_company_key(update, context)
        return
    
    if text == "🏢 Моя компания":
        await show_my_company(update, context)
        return
    
    # ★★★ ПРОВЕРКА ДОСТУПА БЕЗ КОМПАНИИ ★★★
    from database import get_user_company
    
    # Проверяем доступ к заданиям и покупкам
    blocked_without_company = ["📚 Мои задания", "🎯 Купить тренинг"]
    
    if text in blocked_without_company:
        user_company = get_user_company(user_id)
        
        if not user_company:
            keyboard = [["🔑 Ввести ключ компании"], ["🔙 В главное меню"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "⚠️ **Доступ заблокирован!**\n\n"
                "Для доступа к этому разделу необходимо присоединиться к компании.\n\n"
                "1. Получите ключ компании у администратора\n"
                "2. Перейдите в 👤 Профиль → 🔑 Ввести ключ компании\n"
                "3. Введите полученный ключ\n\n"
                "После этого вы получите доступ ко всем функциям.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
    
    # ДОБАВЬТЕ ЭТО ДЛЯ ОТЛАДКИ:
    if text.startswith(("🔄 ", "⏳ ", "✅ ")):
        print(f"🔍 Обрабатываем кнопку марафона: '{text}'")
        print(f"🔍 context.user_data: {context.user_data.get('available_arcs', {})}")
        
    current_section = context.user_data.get('current_section')
    if current_section == 'feedback' and context.user_data.get('in_feedback_detail'):
        pass

    if text.startswith("👤 ") and " - " in text and current_section == 'admin':
        print(f"🚨 Кнопка участника в админке: {text}")
        
        # Определяем по view_mode или тексту кнопки
        view_mode = context.user_data.get('view_mode', 'new')
        
        if view_mode == 'approved' or "принятых" in text:
            # ★★ ИСПРАВЛЕНИЕ: Извлекаем данные из mapping
            if 'student_mapping_approved' in context.user_data:
                mapping = context.user_data['student_mapping_approved']
                if text in mapping:
                    data = mapping[text]
                    # Сохраняем в контекст
                    context.user_data['current_student_id'] = data['user_id']
                    context.user_data['current_arc_id'] = data['arc_id']
                    print(f"✅ Извлечены данные: user_id={data['user_id']}, arc_id={data['arc_id']}")
                    await show_student_part_approved(update, context)
                else:
                    print(f"❌ Кнопка '{text}' не найдена в mapping_approved")
                    print(f"   Доступные ключи: {list(mapping.keys())}")
                    await update.message.reply_text("❌ Ошибка: данные участника не найдены")
            else:
                print(f"❌ Нет student_mapping_approved в контексте")
                await update.message.reply_text("❌ Ошибка: данные не загружены")
        else:
            # ★★ ИСПРАВЛЕНИЕ: Для новых заданий тоже извлекаем данные
            if 'student_mapping' in context.user_data:
                mapping = context.user_data['student_mapping']
                if text in mapping:
                    data = mapping[text]
                    context.user_data['current_student_id'] = data['user_id']
                    context.user_data['current_arc_id'] = data['arc_id']
                    print(f"✅ Извлечены данные: user_id={data['user_id']}, arc_id={data['arc_id']}")
                    await show_student_part_assignments(update, context)
                else:
                    print(f"❌ Кнопка '{text}' не найдена в mapping")
                    await update.message.reply_text("❌ Ошибка: данные участника не найдены")
            else:
                print(f"❌ Нет student_mapping в контексте")
                await update.message.reply_text("❌ Ошибка: данные не загружены")
        return

    current_section = context.user_data.get('current_section')

    if text.startswith("📝 ") and current_section == 'admin':
        print(f"🚨 Кнопка 📝 в админке: {text}")
        await show_assignment_for_admin(update, context)
        return

    if 'arc_selection_map' in context.user_data and update.message.text in context.user_data['arc_selection_map']:
        await show_tests_for_arc(update, context)
        return

    if 'test_mapping' in context.user_data and update.message.text in context.user_data['test_mapping']:
        await start_test(update, context)
        return

    # 1. Сначала проверяем статистику
    if text == "📊 Мой прогресс":
        await show_statistics(update, context)
        return
    
    # 2. Если находимся в меню статистики И текст содержит эмодзи части
    if current_section == 'statistics_menu' and text.startswith(("🔄", "⏳", "✅")):
        await show_arc_statistics(update, context)
        return
    
    # 3. Если нажали "Выбрать другую часть" в статистике
    if text == "📊 К выбору части":
        await show_statistics(update, context)
        return
    
    # 5. Обработка кнопок покупки (используем существующие функции)
    if text == "🎁 Пробный доступ(3 дня)":
        # Для пробного доступа к компании
        user_id = update.message.from_user.id
        from database import get_user_company, get_company_arc
        
        # Проверяем компанию пользователя
        user_company = get_user_company(user_id)
        if not user_company:
            await update.message.reply_text(
                "❌ **Вы не состоите в компании!**\n\n"
                "Для покупки доступа сначала присоединитесь к компании через профиль.",
                parse_mode='Markdown'
            )
            return
        
        # Получаем арку компании
        company_arc = get_company_arc(user_company['company_id'])
        if not company_arc:
            await update.message.reply_text("❌ У компании нет активного тренинга")
            return
        
        # Сохраняем данные о покупке
        context.user_data['current_company_arc_id'] = company_arc['company_arc_id']
        context.user_data['current_company_name'] = user_company['name']
        
        # Вызываем функцию покупки с trial=True
        await buy_arc_with_yookassa(update, context, trial=True)
        return

    if text == "💰 Купить полный доступ" or text == "💰 Купить доступ заранее":
        # Для полного доступа к компании
        user_id = update.message.from_user.id
        from database import get_user_company, get_company_arc
        
        # Проверяем компанию пользователя
        user_company = get_user_company(user_id)
        if not user_company:
            await update.message.reply_text(
                "❌ **Вы не состоите в компании!**\n\n"
                "Для покупки доступа сначала присоединитесь к компании через профиль.",
                parse_mode='Markdown'
            )
            return
        
        # Получаем арку компании
        company_arc = get_company_arc(user_company['company_id'])
        if not company_arc:
            await update.message.reply_text("❌ У компании нет активного тренинга")
            return
        
        # Сохраняем данные о покупке
        context.user_data['current_company_arc_id'] = company_arc['company_arc_id']
        context.user_data['current_company_name'] = user_company['name']
        
        # Вызываем функцию покупки с trial=False
        await buy_arc_with_yookassa(update, context, trial=False)
        return

    # 0. Определяем обработчики для каждого раздела
    if text.startswith("🔙"):
        current_section = context.user_data.get('current_section')
        
        back_handlers = {
            'admin': {
                # Все "назад" ведут или к новым или к принятым заданиям
                "🔙 Назад к списку": lambda u, c: (
                    show_approved_assignments(u, c) 
                    if c.user_data.get('view_mode') == 'approved' 
                    else show_new_assignments(u, c)
                ),
                "🔙 Назад к новым заданиям": show_new_assignments,
                "🔙 Назад к принятым заданиям": show_approved_assignments,
                "🔙 Назад к списку участников": lambda u, c: (
                    show_approved_assignments(u, c) 
                    if c.user_data.get('view_mode') == 'approved' 
                    else show_new_assignments(u, c)
                ),
                "🔙 Назад к проверке": admin_panel,
                "🔙 Вернуться в меню проверки": admin_panel,
            },
        }
        
        if current_section in back_handlers and text in back_handlers[current_section]:
            await back_handlers[current_section][text](update, context)
            return

    # Обработка статистики админа
    if text == "📊 Прогресс участников":
        await show_users_stats(update, context)
        return
    
    # Если находимся в меню статистики админа
    if context.user_data.get('current_section') == 'admin_stats':
        # Выбор участника по цветным кнопкам
        if text.startswith(("🟢", "🟡", "🟠", "🔴")):
            await show_admin_user_statistics(update, context)
            return
        
        # Выбор части участника
        if text.startswith(("🔄", "⏳", "✅")):
            await show_admin_arc_statistics(update, context)
            return
        
        # Навигация
        if text == "👤 Выбрать другого участника":
            await show_users_stats(update, context)
            return
        
        if text == "📊 Посмотреть другой марафон этого участника":
            user_info = context.user_data.get('admin_current_user')
            if user_info:
                await show_admin_user_statistics(update, context)
            else:
                await show_users_stats(update, context)
            return

    # ★★★ ТЕПЕРЬ ОБЩИЙ ОБРАБОТЧИК ДЛЯ ДУГ - ТОЛЬКО ЕСЛИ НЕ В admin_stats ★★★
    if text.startswith("🔄 ") or text.startswith("⏳ "):
        #Проверяем не находимся ли мы в админ-разделе
        current_section = context.user_data.get('current_section')
        
        # ★★★ ДОБАВЛЯЕМ ПРОВЕРКУ ДЛЯ admin_stats ★★★
        if current_section == 'admin_stats':
            # Это часть в статистике админа, уже обработали выше
            return
        
        if current_section == 'admin':
            # Это задание в админ-панели, обрабатываем отдельно
            await show_assignment_for_admin(update, context)
        else:
            # Это действительно дуга в каталоге
            await buy_arc_from_catalog(update, context)
        return

    elif text == "🎯 Купить тренинг":
        user_id = update.message.from_user.id
        
        # ★★★ ПРОВЕРКА КОМПАНИИ ★★★
        from database import get_user_company
        
        user_company = get_user_company(user_id)
        if not user_company:
            keyboard = [["🔑 Ввести ключ компании"], ["🔙 В главное меню"]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "⚠️ **Доступ заблокирован!**\n\n"
                "Для доступа к тренингу необходимо присоединиться к компании.\n\n"
                "1. Получите ключ компании у администратора\n"
                "2. Перейдите в 👤 Профиль → 🔑 Ввести ключ компании\n"
                "3. Введите полученный ключ\n\n"
                "После этого вы получите доступ ко всем функциям.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        
        # Если компания есть, показываем каталог
        await show_training_catalog(update, context)
        return

    # 1. Сначала ВСЕ уникальные кнопки которые точно определены
    unique_buttons = {
        "✅ Отправить задание": submit_assignment,
        "📝 Доступные задания": show_available_assignments,
        "👨‍🏫 Проверка заданий": admin_panel,
        "📚 Мои задания": my_assignments_menu,
        "🎯 Купить тренинг": lambda u, c: show_training_catalog_with_company_check(u, c),
        "👤 Профиль": profile_menu,
        "🛠 Тех.поддержка": tech_support_menu,
        "🔙 В главное меню": start,
        "⏰ Часовой пояс": select_timezone,
        "👤 Изменить ФИО": start_fio_change,
        "🔙 Назад в кабинет": profile_menu,
        "🆕 Новые задания": show_new_assignments,
        "✅ Принятые задания": show_approved_assignments,
        "📁 Завершенные": lambda u, c: u.message.reply_text("📝 В разработке"),
        "⚠️ Пропущенные": lambda u, c: u.message.reply_text("📝 В разработке"),
        "🔙 Назад к проверке": admin_panel,
        "📎 Добавить файл": lambda u, c: (c.user_data.update({'waiting_for_file': True}), u.message.reply_text("📎 **Отправьте фото или файл:**\n\nФайл будет добавлен к вашему ответу.", parse_mode='Markdown')),
        "💬 Задать вопрос": ask_question_handler,
        "✅ Принять задание": finish_approval,
        "🔙 Вернуться в меню проверки": admin_panel,
        "💬 Личная консультация": request_personal_consultation,
        "💰 Купить доступ": show_course_main,
        "Перейти в каталог тренинга": show_course_main,
        "🔧 Изменение доступа": manage_access,
        "👥 Сообщество психолога": go_to_community,
        "📊 Прогресс участников": show_users_stats,
        "🔙 Назад к тренингу": back_to_course_menu,
        "🔙 Выбор марафона": show_course_main,
        "📚 В меню заданий": my_assignments_menu,
        "📋 Принятые оферты": show_accepted_offers,
        "🔙 Назад в каталог": show_course_main,
        "📖 Инструкция": show_quick_guide,
        "💬 Задать вопрос о тренинге": contact_psychologist,
        "📷 Только фото": start_photo_only_answer,
        "📝 Только текст": start_text_only_answer, 
        "📷+📝 Фото и текст": start_photo_text_answer,
        "🔙 Назад к частям тренинга": show_events,
        "💰 Купить полный доступ": lambda u, c: buy_arc_with_yookassa(u, c, trial=False),
        "🎁 Пробный доступ(3 дня)": lambda u, c: buy_arc_with_yookassa(u, c, trial=True),
        "💰 Купить доступ заранее": lambda u, c: buy_arc_with_yookassa(u, c, trial=False),
        "🔙 Назад в меню заданий": show_available_assignments,
        "📚 В раздел Мои задания": my_assignments_menu,
        "💰 Купить заранее": lambda u, c: buy_arc_with_yookassa(u, c, trial=False),
        "📖 Всё о тренинге": show_about_course,
        "⚙️ Инструменты администратора": admin_tools_menu,
        "🔔 Отправить уведомление": start_notification,
        "🔙 Назад к инструментам": admin_tools_menu,
        "🔙 Назад": show_training_catalog,
        "📈 Тестирование": testing_menu,
        "📈 Пройти тест": show_available_tests,
        "📊 Мои результаты": lambda u, c: show_test_results(u, c),
        "📋 Показать все ответы": show_all_test_answers,
        "🔙 Назад к тестированию": testing_menu,
        "🔙 Выбрать другой марафон": lambda u, c: show_test_results(u, c),
        "🔙 Назад к результатам": lambda u, c: show_test_results(u, c),
        "📈 Пройти другой тест": show_available_tests,
        "🔙 Назад к тестам марафона": back_to_arc_tests,
        "🔙 Назад к результату": back_to_test_result,
        "💬 Комментарии к заданиям": admin_auto_approved_menu,
        "🔙 Отмена комментария": lambda u, c: admin_auto_approved_menu(u, c),
        "💬 Добавить комментарий": add_comment_to_approved_assignment,
        "💬 Комментарий добавлен ✅": lambda u, c: u.message.reply_text("✅ Комментарий уже добавлен и просмотрен участником"),
        "💬 Комментарий добавлен 🟡": lambda u, c: u.message.reply_text("🟡 Комментарий добавлен, ждет просмотра участником"),
        "📂 Архив заданий": show_feedback_parts,
        "📂 Архив заданий 🟡": show_feedback_parts,
        "🔙 К списку заданий": lambda u, c: show_student_part_approved(u, c),
    }

    if text == "🏢 Управление компаниями":
        await admin_companies_menu(update, context)
        return
    
    if text == "🏢 Создать компанию":
        await create_company_start(update, context)
        return
    
    if text == "📋 Список компаний":
        await show_companies_list(update, context)
        return
    
    if text == "🔙 Назад к управлению" or text == "🔙 К списку компаний":
        await admin_companies_menu(update, context)
        return
    
    # Обработка выбора конкретной компании из списка
    if text.startswith("🏢 ") and context.user_data.get('current_section') == 'admin_companies':
        await show_company_details(update, context)
        return

    if text in unique_buttons:
        await unique_buttons[text](update, context)
        return

    if text == "💬 Написать в поддержку":
        await write_to_support(update, context)
        return
    
    if text == "📖 Инструкции":
        await show_instructions(update, context)
        return
    
    if text == "👤 Авторы марафона":
        await show_author_info(update, context)
        return

    if text == "💰 Купить заранее":
        await buy_arc_with_yookassa(update, context, trial=False)
        return

    if text in ["📢 Всем в бот", "✅ Только полный доступ", "🎁 Только пробный доступ"]:
        await handle_notification_creation(update, context)
        return

    if text in ["📤 Отправить", "✏️ Изменить", "❌ Отменить"]:
        await handle_notification_creation(update, context)
        return

    # В handle_buttons добавляем более надежную очистку:
    if text == "🔙 Отменить":
        # Очищаем ВСЕ данные уведомления
        keys_to_remove = []
        for key in context.user_data.keys():
            if key.startswith('notification_'):
                keys_to_remove.append(key)
    
        for key in keys_to_remove:
            context.user_data.pop(key, None)
    
        print(f"🔙 Отмена уведомления. Удалено ключей: {len(keys_to_remove)}")
        await admin_tools_menu(update, context)
        return

    if text.startswith("📚") or text.startswith("🏆"):  # Добавляем 🏆
        print(f"✅ Выбор части в feedback: {text}")
        await show_feedback_type(update, context)
        return

    # Обработка кнопок заданий в админке (принятые задания)
    if (text.startswith("✅ ") or text.startswith("💬✅ ")) and context.user_data.get('current_section') == 'admin':
        print(f"🔍 Кнопка задания в админке: '{text}'")
        
        if 'assignment_mapping' in context.user_data and text in context.user_data['assignment_mapping']:
            data = context.user_data['assignment_mapping'][text]
            context.user_data['current_assignment_id'] = data['assignment_id']
            context.user_data['current_assignment_title'] = data['assignment_title']
            context.user_data['current_day_title'] = data['day_title']
            
            print(f"✅ Данные задания: assignment_id={data['assignment_id']}")
            await show_approved_assignment_simple(update, context)
        else:
            await show_approved_assignment_simple(update, context)
        return

    if (text.startswith("📝 ") or text.startswith("💬 ")) and context.user_data.get('current_section') in ['feedback', 'feedback_type']:
        print(f"🔍 Кнопка задания в feedback разделе: '{text}'")
        
        if 'feedback_assignments_map' in context.user_data and text in context.user_data['feedback_assignments_map']:
            await show_feedback_assignment_detail(update, context)
        else:
            await update.message.reply_text("❌ Задание не найдено")
        return

    # Обработка админки (оставляем 🔄)
    if context.user_data.get('current_section') == 'admin' and "🔄" in text:
        # Это админка - задания на проверке
        await show_assignment_for_admin(update, context)
        return

    if text.startswith("🟡 Новые ответы") or text.startswith("✅ Завершенные задания"):
        print(f"🔍 Кнопка типа ответов в feedback: '{text}'")
        
        # Проверяем что мы в разделе feedback
        if context.user_data.get('current_section') in ['feedback', 'feedback_type']:
            arc_id = context.user_data.get('current_feedback_arc')
            
            if not arc_id:
                await update.message.reply_text("❌ Сначала выберите часть.")
                await show_feedback_parts(update, context)
                return
            
            # Просто вызываем show_feedback_list
            await show_feedback_list(update, context)
            return

    # Если нажали на задание в разделе "Доступные задания"
    if context.user_data.get('current_section') == 'available_assignments':
        # Проверяем, нажали ли на задание (начинается с 📝)
        if text.startswith("📝"):
            await show_assignment_from_list(update, context)
            return
        
        if text == "🟡 Задания на проверке":
            await show_in_progress_assignments(update, context)
            return

    if text == "📂 Тестирование":
        await update.message.reply_text(
            "Разде 'Тестирование' скоро появится!\n"
            "Здесь будут доступны еженедельные тесты для проверки вашего прогресса.\n",
            parse_mode='Markdown'
        )
        return

    elif text.startswith("🎯 Марафон"):
        await show_seminar_details(update, context)
        return

    # Кнопка "Назад к частям"  
    if text == "🔙 Назад к частям":
        await show_feedback_parts(update, context)
        return

    # 2. Обработка оферт
    if text == "✅ Принять оферту":
        await accept_offer_handler(update, context)
        return

    if text == "❌ Отказаться":
        await decline_offer_handler(update, context)
        return

    if text == "❌ Отказаться от оферты" and context.user_data.get('showing_service_offer'):
        await decline_service_offer_handler(update, context)
        return

    if text == "✅ Принять оферту услуг":
        await accept_service_offer_handler(update, context)
        return

    # 3. Обработка разделов каталога
    if text == "📅 Расписание тренингов":
        await show_events(update, context)
        return

    if text == "🗓 Расписание семинаров":
        await show_schedule(update, context)
        return

    if text == "🔙 Назад к описанию тренинга":
        await show_about_course(update, context)
        return

    if text.startswith("📝"):
        # Проверяем из какого раздела пришли
        if 'feedback_assignments_map' in context.user_data and text in context.user_data['feedback_assignments_map']:
            await show_feedback_assignment_detail(update, context)
        
    # 5. Обработка по разделам с current_section
    current_section = context.user_data.get('current_section')
    view_mode = context.user_data.get('view_mode')

    # 5.5 Обработка раздела admin_access (управление доступом)
    if current_section == 'admin_access' and text.startswith("👤"):
        # Только кнопки вида "👤 Имя (1)" для управления доступом
        if "(" in text and ")" in text:
            await show_user_arcs_access(update, context)
            return

    # 5.6 Обработка раздела admin_stats (прогресс)
    if current_section == 'admin_stats':
        if text.startswith(("🟢", "🟡", "🟠", "🔴")):
            await show_user_statistics_admin(update, context)
            return

    # 6. Обработка кнопок Назад (упрощенная)
    if text.startswith("🔙"):
        # Уже обработано в начале, если не сработало - игнорируем
        pass

    # 8. Выбор часового пояса (вместо города)
    from database import get_available_cities
    if text in get_available_cities():
        from database import set_user_timezone, CITY_TIMEZONES
        timezone_offset = CITY_TIMEZONES[text]
        set_user_timezone(user_id, text, timezone_offset)
    
        # Форматируем сообщение
        if timezone_offset > 0:
            offset_display = f"+{timezone_offset}"
        elif timezone_offset < 0:
            offset_display = f"{timezone_offset}"
        else:
            offset_display = "0"
    
        await update.message.reply_text(
            f"✅ **Часовой пояс установлен!**\n\n"
            f"Разница с Москвой: {offset_display} часа\n"
            f"Задание дня будет открываться в 6:00 по вашему местному времени."
            f"В случае если вы не успеете его сделать до 0:00, оно засчитается как пропущенное."
            f"Если пропустить задание, то доступ к нему останется, но прервется серия выполнения заданий подряд." ,
            parse_mode='Markdown'
        )
        await profile_menu(update, context)
        return

    # 9. Если ничего не сработало
    await handle_text(update, context)

async def back_to_arcs_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат к списку разделов для покупки"""
    await show_buy_access(update, context)

async def back_to_course_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возврат в меню тренинга"""
    course_title = context.user_data.get('current_course', 'СЕБЯ ВЕРНИ СЕБЕ')
    
    keyboard = [
        ["📖 Всё о тренинге"],
        ["💰 Купить доступ"],
        ["🔙 В главное меню"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"📚 **{course_title}**\n\nВыберите часть:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_assignment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Универсальный обработчик для просмотра заданий"""
    view_mode = context.user_data.get('view_mode')
    if view_mode == 'approved':
        await show_assignment_approved(update, context)
    else:
        await show_assignment_for_admin(update, context)

async def view_submission_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    student_data = context.user_data.get('current_student')
    
    if not student_data:
        await update.message.reply_text("❌ Сначала выбери участника")
        return
    
    if " - файл " in text:
        parts = text.split(" - файл ")
        assignment_title = parts[0][2:].strip()
        file_number = int(parts[1])
        print(f"🚨 DEBUG: assignment_title = '{assignment_title}', file_number = {file_number}")
    else:
        # Старый формат для обратной совместимости
        assignment_title = text[2:].strip()
        file_number = 1
    
    # Находим конкретный файл по номеру
    submissions = get_student_submissions(student_data['user_id'])
    target_file = None
    current_file_num = 0
    
    for submission in submissions:
        file_db_id, assignment_id, title, status, telegram_file_id, created_at = submission
        if title == assignment_title:
            current_file_num += 1
            if current_file_num == file_number:
                target_file = submission
                break
    
    if not target_file:
        await update.message.reply_text("❌ Файл не найден")
        return
    
    file_db_id, assignment_id, title, status, telegram_file_id, created_at = target_file
    
    # Отправляем файл психолога
    status_icon = "🆕" if status == 'submitted' else "✅"
    await context.bot.send_document(
        chat_id=update.message.chat_id,
        document=telegram_file_id,
        caption=f"📎 Файл от @{student_data['username']}\n"
                f"📝 Задание: {title}\n"
                f"📁 Файл: {file_number}\n"
                f"📊 Статус: {status} {status_icon}\n"
                f"📅 Дата: {created_at}"
    )
    
    # Кнопки для проверки (только для новых файлов)
    if status == 'submitted':
        keyboard = [
            ["✅ Принять этот файл", "❌ Вернуть этот файл"],
            ["🔙 Назад к файлам", "🔙 Назад к работам участника"]
        ]
    else:
        keyboard = [
            ["🔙 Назад к файлам", "🔙 Назад к работам участника"]
        ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"Выбери действие для файла {file_number}:",
        reply_markup=reply_markup
    )
    
    # Сохраняем данные для обработки решения
    context.user_data['current_review'] = {
        'file_db_id': file_db_id,
        'user_id': student_data['user_id'],
        'assignment_id': assignment_id,
        'username': student_data['username'],
        'assignment_title': title,
        'file_number': file_number
    }


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_section'] = 'admin'
    """Обновленная админ-панель"""
    keyboard = [
        ["✅ Принятые задания"],
        ["📊 Прогресс участников"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👨‍🏫 **Проверка заданий**\n\n"
        "Выберите часть:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
 
    if context.user_data.get('notification_stage') == 'waiting_content':
        await process_notification_content(update, context)
        return
    
    if context.user_data.get('answering'):
        answer_type = context.user_data.get('answer_type', 'Фото_и_текст')
        
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            
            if 'answer_files' not in context.user_data:
                context.user_data['answer_files'] = []
            
            context.user_data['answer_files'].append(file_id)
            
            # Для "только фото" сразу показываем кнопку отправки
            if answer_type == 'Только_фото':
                await show_submit_button(update, context)
            # Для "фото+текст" показываем финальные кнопки
            elif answer_type == 'Фото_и_текст':
                await show_final_buttons(update, context)
            return


async def view_assignment_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    student_data = context.user_data.get('current_student')
    
    if not student_data:
        await update.message.reply_text("❌ Сначала выбери участника")
        return
    
    if text == "🔙 Назад к файлам":
        assignment_title = context.user_data.get('current_assignment_title')
    else:
        # Обычный вызов - извлекаем из текста кнопки
        assignment_title = text[2:].split(" (")[0].strip()
        context.user_data['current_assignment_title'] = assignment_title
    
    # Находим файлы для этого задания
    submissions = get_student_submissions(student_data['user_id'])
    
    keyboard = []
    file_counter = {}
    
    for file_db_id, assignment_id, title, status, telegram_file_id, created_at in submissions:
        
        if title == assignment_title:
            if title not in file_counter:
                file_counter[title] = 1
            else:
                file_counter[title] += 1
                
            file_number = file_counter[title]
            
            if status == 'submitted':
                status_icon = "🆕"
            elif status == 'approved':
                status_icon = "✅"
            elif status == 'rejected':
                status_icon = "❌"
            else:
                status_icon = "⏳"
            
            btn_text = f"{status_icon} {title} - файл {file_number}"
            keyboard.append([btn_text])
    
    if not keyboard:
        await update.message.reply_text("❌ В этом задании нет файлов")
        return
    
    keyboard.append(["🔙 Назад к заданиям"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"📋 Файлы задания '{assignment_title}':\nВыбери файл:",
        reply_markup=reply_markup
    )


# ★★★ НОВЫЕ ФУНКЦИИ ДЛЯ КОМПАНИЙ ★★★

async def profile_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Личный кабинет пользователя - ОБНОВЛЕННЫЙ С КОМПАНИЯМИ"""
    user_id = update.message.from_user.id
    
    from database import get_user_offer_status, get_user_company
    offer_status = get_user_offer_status(user_id)
    
    print(f"🔍 profile_menu: accepted={offer_status['accepted_offer']}, "
          f"has_phone={offer_status['has_phone']}, has_fio={offer_status['has_fio']}")
    
    # Если нет оферты - показываем оферту
    if not offer_status['accepted_offer']:
        await show_offer_agreement(update, context)
        return
    
    # Если оферта есть, но нет телефона - просим телефон
    if offer_status['accepted_offer'] and not offer_status['has_phone']:
        await request_phone_number(update, context)
        return
    
    # Если есть телефон, но нет ФИО - просим ФИО
    if offer_status['accepted_offer'] and offer_status['has_phone'] and not offer_status['has_fio']:
        await request_fio_number(update, context)
        return
    
    # Проверяем привязана ли компания
    user_company = get_user_company(user_id)
    
    keyboard = []
    
    if user_company:
        # Если компания есть
        keyboard.append(["🏢 Моя компания"])
        keyboard.append(["👤 Изменить ФИО"])
        keyboard.append(["⏰ Часовой пояс"])
        keyboard.append(["📋 Принятые оферты"])
        keyboard.append(["🔙 В главное меню"])
    else:
        # Если компании нет
        keyboard.append(["🔑 Ввести ключ компании"])
        keyboard.append(["👤 Изменить ФИО"])
        keyboard.append(["⏰ Часовой пояс"])
        keyboard.append(["📋 Принятые оферты"])
        keyboard.append(["🔙 В главное меню"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT fio, city, timezone_offset, phone FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    fio = result[0] if result and result[0] else "Не указано"
    city = result[1] if result and result[1] else "Не выбран"
    timezone_offset = result[2] if result and result[2] is not None else 0
    phone = result[3] if result and result[3] else "Не указан"
    
    if timezone_offset > 0:
        timezone_display = f"+{timezone_offset} часа от МСК"
    elif timezone_offset < 0:
        timezone_display = f"{timezone_offset} часа от МСК"
    else:
        timezone_display = "МСК (0)"
    
    message = f"👤 **Личный кабинет**\n\n"
    message += f"**ФИО:** {fio}\n"
    message += f"**Часовой пояс:** {timezone_display}\n"
    message += f"**Телефон:** {phone}\n\n"
    
    if user_company:
        message += f"🏢 **Компания:** {user_company['name']}\n"
        message += f"📅 **Старт тренинга:** {user_company['start_date']}\n\n"
    else:
        message += "⚠️ **Вы не состоите в компании!**\n\n"
        message += "Чтобы получить доступ к заданиям, необходимо ввести ключ компании.\n"
        message += "Ключ вам должен предоставить администратор вашей компании.\n\n"
    
    message += "Выберите действие:"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def enter_company_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос ключа компании"""
    context.user_data['waiting_for_company_key'] = True
    
    keyboard = [["🔙 Назад в кабинет"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🔑 **Ввод ключа компании**\n\n"
        "Введите ключ, который вам предоставил администратор компании:\n\n"
        "Ключ обычно состоит из букв и цифр, например: 'ABC123' или 'COMPANY2026'\n\n"
        "Если у вас нет ключа, обратитесь к администратору вашей компании.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_company_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного ключа компании"""
    user_id = update.message.from_user.id
    key = update.message.text.strip().upper()  # Приводим к верхнему регистру
    
    if key == "🔙 НАЗАД В КАБИНЕТ":
        context.user_data.pop('waiting_for_company_key', None)
        await profile_menu(update, context)
        return
    
    from database import get_company_by_key, join_user_to_company, get_user_company
    
    # Проверяем ключ
    company = get_company_by_key(key)
    
    if not company:
        await update.message.reply_text(
            "❌ **Ключ не найден!**\n\n"
            "Проверьте правильность введенного ключа или обратитесь к администратору компании.\n\n"
            "Попробуйте ввести ключ еще раз:",
            parse_mode='Markdown'
        )
        return
    
    # Проверяем, не состоит ли уже в этой компании
    current_company = get_user_company(user_id)
    if current_company and current_company['company_id'] == company['company_id']:
        await update.message.reply_text(
            f"ℹ️ **Вы уже состоите в компании '{company['name']}'**\n\n"
            f"Дата присоединения: {current_company['joined_at']}",
            parse_mode='Markdown'
        )
        context.user_data.pop('waiting_for_company_key', None)
        await profile_menu(update, context)
        return
    
    # Привязываем пользователя к компании
    success = join_user_to_company(user_id, company['company_id'])
    
    if success:
        context.user_data.pop('waiting_for_company_key', None)
        
        await update.message.reply_text(
            f"🎉 **Вы успешно присоединились к компании!**\n\n"
            f"🏢 **Название:** {company['name']}\n"
            f"📅 **Старт тренинга:** {company['start_date']}\n"
            f"💼 **Цена доступа:** {company['price']}₽\n\n"
            f"Теперь вы можете:\n"
            f"1. Перейти в раздел 'Мои задания'\n"
            f"2. Купить доступ к тренингу компании\n"
            f"3. Присоединиться к группе компании: {company['tg_group_link'] if company['tg_group_link'] else 'ссылка не указана'}\n\n"
            f"Для продолжения нажмите 'В главное меню'.",
            parse_mode='Markdown'
        )
        
        # Показываем главное меню
        keyboard = [["🔙 В главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        await update.message.reply_text(
            "Выберите действие:",
            reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            "❌ **Ошибка присоединения к компании!**\n\n"
            "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
            parse_mode='Markdown'
        )

async def show_my_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о компании пользователя"""
    user_id = update.message.from_user.id
    
    from database import get_user_company, get_company_users, get_company_arc
    
    user_company = get_user_company(user_id)
    
    if not user_company:
        await update.message.reply_text(
            "❌ **У вас нет привязанной компании!**\n\n"
            "Чтобы присоединиться к компании, перейдите в профиль и введите ключ компании.",
            parse_mode='Markdown'
        )
        return
    
    # Получаем участников компании
    company_users = get_company_users(user_company['company_id'])
    
    # Получаем арку компании
    company_arc = get_company_arc(user_company['company_id'])
    
    message = f"🏢 **Информация о компании**\n\n"
    message += f"**Название:** {user_company['name']}\n"
    message += f"**Ключ:** `{user_company['join_key']}`\n"
    message += f"**Старт тренинга:** {user_company['start_date']}\n"
    
    if company_arc and company_arc['actual_end_date']:
        message += f"**Окончание тренинга:** {company_arc['actual_end_date']}\n"
    
    message += f"**Цена доступа:** {user_company['price']}₽\n"
    
    if user_company['tg_group_link']:
        message += f"**Группа в Telegram:** {user_company['tg_group_link']}\n"
    
    message += f"\n**👥 Участники компании:** {len(company_users)}\n\n"
    
    # Показываем несколько участников
    if company_users:
        for i, user in enumerate(company_users[:5], 1):
            display_name = user['fio'] or user['first_name'] or user['username'] or f"Участник {user['user_id']}"
            message += f"{i}. {display_name}\n"
        
        if len(company_users) > 5:
            message += f"... и еще {len(company_users) - 5} участников\n"
    
    keyboard = [
        ["🔙 Назад в кабинет"],
        ["📊 Статистика компании"]  # TODO: реализовать позже
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

# ★★★ АДМИН-ИНТЕРФЕЙС ДЛЯ КОМПАНИЙ ★★★

async def admin_companies_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления компаниями для администратора"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    context.user_data['current_section'] = 'admin_companies'
    
    keyboard = [
        ["🏢 Создать компанию"],
        ["📋 Список компаний"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🏢 **Управление компаниями**\n\n"
        "Выберите действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def create_company_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало создания компании"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    context.user_data['company_creation_stage'] = 'name'
    context.user_data['new_company'] = {}
    
    keyboard = [["❌ Отменить создание"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🏢 **Создание новой компании**\n\n"
        "Шаг 1 из 6\n\n"
        "Введите название компании:\n\n"
        "Пример: 'ООО Рога и Копыта'\n"
        "Пример: 'Академия Продаж 2026'",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def create_company_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка создания компании по шагам"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    user_id = update.message.from_user.id
    text = update.message.text
    
    if text == "❌ Отменить создание":
        context.user_data.pop('company_creation_stage', None)
        context.user_data.pop('new_company', None)
        await admin_companies_menu(update, context)
        return
    
    stage = context.user_data.get('company_creation_stage')
    company_data = context.user_data.get('new_company', {})
    
    # Шаг 1: Название компании
    if stage == 'name':
        if len(text) < 3:
            await update.message.reply_text("❌ Название должно быть минимум 3 символа. Введите еще раз:")
            return
        
        company_data['name'] = text
        context.user_data['company_creation_stage'] = 'key'
        
        await update.message.reply_text(
            "🏢 **Создание новой компании**\n\n"
            "Шаг 2 из 6\n\n"
            "Введите ключ для вступления в компанию:\n\n"
            "**Требования:**\n"
            "• Минимум 4 символа\n"
            "• Только латинские буквы и цифры\n"
            "• Уникальный для всех компаний\n\n"
            "Пример: 'SALES2026', 'TEAM4321', 'COMPANYABC'",
            parse_mode='Markdown'
        )
    
    # Шаг 2: Ключ компании
    elif stage == 'key':
        # Проверяем формат ключа
        import re
        if not re.match(r'^[A-Za-z0-9]{4,}$', text):
            await update.message.reply_text(
                "❌ Неверный формат ключа!\n\n"
                "Ключ должен содержать:\n"
                "• Минимум 4 символа\n"
                "• Только латинские буквы и цифры\n"
                "• Без пробелов и спецсимволов\n\n"
                "Введите ключ еще раз:",
                parse_mode='Markdown'
            )
            return
        
        # Проверяем уникальность ключа
        from database import get_company_by_key
        if get_company_by_key(text):
            await update.message.reply_text(
                f"❌ Ключ '{text}' уже используется!\n\n"
                "Придумайте другой уникальный ключ:",
                parse_mode='Markdown'
            )
            return
        
        company_data['join_key'] = text.upper()  # Сохраняем в верхнем регистре
        context.user_data['company_creation_stage'] = 'start_date'
        
        await update.message.reply_text(
            "🏢 **Создание новой компании**\n\n"
            "Шаг 3 из 6\n\n"
            "Введите дату старта тренинга:\n\n"
            "**Формат:** ГГГГ-ММ-ДД\n"
            "**Примеры:**\n"
            "• 2026-03-01 (1 марта 2026)\n"
            "• 2026-06-15 (15 июня 2026)\n\n"
            "Тренинг будет длиться 8 недель (56 дней).",
            parse_mode='Markdown'
        )
    
    # Шаг 3: Дата старта
    elif stage == 'start_date':
        # Проверяем формат даты
        try:
            from datetime import datetime
            start_date = datetime.strptime(text, '%Y-%m-%d').date()
            today = datetime.now().date()
            
            if start_date < today:
                await update.message.reply_text(
                    "❌ Дата старта не может быть в прошлом!\n\n"
                    "Введите будущую дату:",
                    parse_mode='Markdown'
                )
                return
            
            company_data['start_date'] = text
            context.user_data['company_creation_stage'] = 'price'
            
            await update.message.reply_text(
                "🏢 **Создание новой компании**\n\n"
                "Шаг 4 из 6\n\n"
                "Введите стоимость доступа к тренингу (в рублях):\n\n"
                "**Примеры:**\n"
                "• 5000\n"
                "• 10000\n"
                "• 15000\n\n"
                "Если хотите сделать бесплатно, введите 0",
                parse_mode='Markdown'
            )
        
        except ValueError:
            await update.message.reply_text(
                "❌ Неверный формат даты!\n\n"
                "Используйте формат: ГГГГ-ММ-ДД\n"
                "Пример: 2026-03-01\n\n"
                "Введите дату еще раз:",
                parse_mode='Markdown'
            )
            return
    
    # Шаг 4: Цена
    elif stage == 'price':
        try:
            price = int(text)
            if price < 0:
                await update.message.reply_text("❌ Цена не может быть отрицательной. Введите еще раз:")
                return
            
            company_data['price'] = price
            context.user_data['company_creation_stage'] = 'tg_link'
            
            await update.message.reply_text(
                "🏢 **Создание новой компании**\n\n"
                "Шаг 5 из 6\n\n"
                "Введите ссылку на Telegram-группу компании:\n\n"
                "**Формат:** https://t.me/+xxxxxxx\n"
                "**Пример:** https://t.me/+ABC123DEF456\n\n"
                "Если группы нет, введите 'нет'",
                parse_mode='Markdown'
            )
        
        except ValueError:
            await update.message.reply_text("❌ Введите число! Пример: 5000, 10000")
            return
    
    # Шаг 5: TG ссылка
    elif stage == 'tg_link':
        if text.lower() == 'нет':
            company_data['tg_group_link'] = None
        elif not text.startswith('https://t.me/'):
            await update.message.reply_text(
                "❌ Неверный формат ссылки!\n\n"
                "Ссылка должна начинаться с https://t.me/\n"
                "Пример: https://t.me/+ABC123DEF456\n\n"
                "Введите ссылку еще раз или 'нет' если группы нет:",
                parse_mode='Markdown'
            )
            return
        else:
            company_data['tg_group_link'] = text
        
        context.user_data['company_creation_stage'] = 'email'
        
        await update.message.reply_text(
            "🏢 **Создание новой компании**\n\n"
            "Шаг 6 из 6\n\n"
            "Введите email для отправки статистики:\n\n"
            "**Примеры:**\n"
            "• hr@company.ru\n"
            "• manager@mail.com\n\n"
            "Если не нужно отправлять статистику, введите 'нет'",
            parse_mode='Markdown'
        )
    
    # Шаг 6: Email
    elif stage == 'email':
        if text.lower() == 'нет':
            company_data['admin_email'] = None
        else:
            import re
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', text):
                await update.message.reply_text(
                    "❌ Неверный формат email!\n\n"
                    "Примеры правильных email:\n"
                    "• hr@company.ru\n"
                    "• manager@mail.com\n"
                    "• admin@gmail.com\n\n"
                    "Введите email еще раз или 'нет':",
                    parse_mode='Markdown'
                )
                return
            company_data['admin_email'] = text
        
        # ★★★ СОЗДАЕМ КОМПАНИЮ ★★★
        from database import create_company
        company_id, company_arc_id = create_company(
            name=company_data['name'],
            join_key=company_data['join_key'],
            start_date=company_data['start_date'],
            tg_group_link=company_data.get('tg_group_link'),
            admin_email=company_data.get('admin_email'),
            price=company_data['price'],
            created_by=user_id
        )
        
        if company_id:
            # Очищаем данные
            context.user_data.pop('company_creation_stage', None)
            context.user_data.pop('new_company', None)
            
            await update.message.reply_text(
                f"🎉 **Компания успешно создана!**\n\n"
                f"🏢 **Название:** {company_data['name']}\n"
                f"🔑 **Ключ:** `{company_data['join_key']}`\n"
                f"📅 **Старт тренинга:** {company_data['start_date']}\n"
                f"💰 **Цена доступа:** {company_data['price']}₽\n"
                f"👥 **Telegram группа:** {company_data.get('tg_group_link', 'не указана')}\n"
                f"📧 **Email для статистики:** {company_data.get('admin_email', 'не указан')}\n\n"
                f"**Тренинг будет доступен с {company_data['start_date']} по "
                f"{company_data['start_date']} + 56 дней.\n\n"
                f"Сообщите участникам ключ для вступления: `{company_data['join_key']}`",
                parse_mode='Markdown'
            )
            
            await admin_companies_menu(update, context)
        else:
            await update.message.reply_text(
                "❌ **Ошибка создания компании!**\n\n"
                "Возможно ключ уже используется. Попробуйте создать компанию заново.",
                parse_mode='Markdown'
            )
            await admin_companies_menu(update, context)
    
    # Сохраняем данные
    context.user_data['new_company'] = company_data

async def show_companies_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех компаний - ИСПРАВЛЕННАЯ"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    from database import get_all_companies
    
    companies = get_all_companies()
    
    if not companies:
        keyboard = [["🏢 Создать компанию"], ["🔙 Назад к управлению"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "📭 **Нет созданных компаний**\n\n"
            "Создайте первую компанию:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    message = "🏢 **Список компаний**\n\n"
    
    for i, company in enumerate(companies, 1):
        message += f"{i}. **{company['name']}**\n"
        message += f"   🔑 Ключ: `{company['join_key']}`\n"
        message += f"   📅 Старт: {company['start_date']}\n"
        message += f"   👥 Участников: {company['user_count']}\n"
        message += f"   💰 Цена: {company['price']}₽\n"
        
        # Показываем только дату без времени
        created_date = company['created_at'].split()[0] if company['created_at'] else "неизвестно"
        message += f"   🕐 Создана: {created_date}\n\n"
    
    keyboard = []
    for company in companies[:10]:  # Ограничиваем 10 компаниями
        # Обрезаем длинные названия
        display_name = company['name']
        if len(display_name) > 20:
            display_name = display_name[:17] + "..."
        keyboard.append([f"🏢 {display_name}"])
    
    keyboard.append(["🏢 Создать компанию"])
    keyboard.append(["🔙 Назад к управлению"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_company_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали выбранной компании"""
    if not is_admin(update.message.from_user.id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    company_name = update.message.text.replace("🏢 ", "")
    
    from database import get_all_companies, get_company_users, get_company_arc
    
    companies = get_all_companies()
    target_company = None
    
    for company in companies:
        if company['name'] == company_name:
            target_company = company
            break
    
    if not target_company:
        await update.message.reply_text(f"❌ Компания '{company_name}' не найдена")
        return
    
    # Получаем участников компании
    users = get_company_users(target_company['company_id'])
    
    # Получаем арку компании
    company_arc = get_company_arc(target_company['company_id'])
    
    message = f"🏢 **Детали компании**\n\n"
    message += f"**Название:** {target_company['name']}\n"
    message += f"**Ключ:** `{target_company['join_key']}`\n"
    message += f"**Дата старта:** {target_company['start_date']}\n"
    message += f"**Цена доступа:** {target_company['price']}₽\n"
    message += f"**Участников:** {len(users)}\n"
    message += f"**Создана:** {target_company['created_at']}\n\n"
    
    if company_arc:
        message += f"**📊 Тренинг компании:**\n"
        message += f"• ID арки: {company_arc['company_arc_id']}\n"
        message += f"• Старт: {company_arc['actual_start_date']}\n"
        message += f"• Окончание: {company_arc['actual_end_date']}\n"
        message += f"• Длительность: 56 дней (8 недель)\n\n"
    
    message += f"**👥 Участники ({len(users)}):**\n"
    
    if users:
        for i, user in enumerate(users[:10], 1):  # Показываем первых 10
            display_name = user['fio'] or user['first_name'] or user['username'] or f"ID: {user['user_id']}"
            message += f"{i}. {display_name} (присоединился: {user['joined_at']})\n"
        
        if len(users) > 10:
            message += f"... и еще {len(users) - 10} участников\n"
    else:
        message += "Нет участников\n"
    
    keyboard = [
        ["📊 Статистика компании"],  # TODO: реализовать позже
        ["📧 Отправить уведомление"],  # TODO: реализовать позже
        ["✏️ Редактировать компанию"],  # TODO: реализовать позже
        ["🔙 К списку компаний"]
    ]
    
    # Сохраняем ID компании в контексте
    context.user_data['selected_company_id'] = target_company['company_id']
    context.user_data['selected_company_name'] = target_company['name']
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def request_fio_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просит ввести ФИО если его нет"""
    await update.message.reply_text(
        "📝 **Для завершения регистрации введите ваше ФИО:**\n\n"
        "Обязательно имя и фамилия (минимум 2 слова).\n"
        "**Примеры:**\n"
        "• Иванов Иван\n"
        "• Анна Петрова\n"
        "• Мария Сергеевна",
        parse_mode='Markdown'
    )
    
    context.user_data['waiting_for_fio'] = True
    
async def select_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор часового пояса"""
    from database import get_available_cities
    
    cities = get_available_cities()
    keyboard = []
    
    for i in range(0, len(cities), 2):
        row = cities[i:i+2]
        keyboard.append(row)
    
    keyboard.append(["🔙 Назад в кабинет"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "⏰ **Выберите ваш часовой пояс:**\n\n"
        "Цифра в скобках показывает разницу с Москвой:\n"
        "• Москва (+0) - ваш часовой пояс как в Москве\n"  
        "• Екатеринбург (+2) - на 2 часа ahead Москвы\n\n"
        "Это нужно для правильного отсчета времени выполнения заданий и отправки личных уведомлений.\n",
        reply_markup=reply_markup
    )

async def my_assignments_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню раздела 'Мои задания' - ВОССТАНАВЛИВАЕМ СТАРУЮ ЛОГИКУ"""
    context.user_data['current_student_id'] = None
    
    user_id = update.message.from_user.id
    
    # ★★★ УПРОЩЕННАЯ ПРОВЕРКА: только компания ★★★
    from database import get_user_company, get_company_arc
    
    user_company = get_user_company(user_id)
    
    if not user_company:
        keyboard = [["🔑 Ввести ключ компании"], ["🔙 В главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ **Вы не состоите в компании!**\n\n"
            "Для доступа к заданиям необходимо присоединиться к компании.\n\n"
            "1. Получите ключ компании у администратора\n"
            "2. Перейдите в 👤 Профиль → 🔑 Ввести ключ компании\n"
            "3. Введите полученный ключ",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    company_arc = get_company_arc(user_company['company_id'])
    
    if not company_arc:
        await update.message.reply_text(
            "❌ **У вашей компании нет активного тренинга!**\n\n"
            "Обратитесь к администратору компании.",
            parse_mode='Markdown'
        )
        return
    
    # ★★★ НЕ ПРОВЕРЯЕМ ДОСТУП ЗДЕСЬ! ★★★
    # Просто показываем меню, а проверку доступа делаем в show_available_assignments
    
    # ★★★ СОЗДАЕМ МЕНЮ ★★★
    keyboard = [
        ["📝 Доступные задания", "📊 Мой прогресс"],
        ["📂 Архив заданий", "📈 Тестирование"],
        ["🔙 В главное меню", "📖 Инструкция"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Формируем сообщение
    message = f"📚 **Мои задания**\n\n"
    message += f"🏢 **Компания:** {user_company['name']}\n"
    message += f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n\n"
    
    # Быстрая проверка есть ли доступ
    import sqlite3
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 1 FROM user_arc_access 
        WHERE user_id = ? AND (company_arc_id = ? OR arc_id = 1)
    ''', (user_id, company_arc['company_arc_id']))
    
    has_access = cursor.fetchone() is not None
    
    if has_access:
        # Получаем тип доступа
        cursor.execute('''
            SELECT access_type FROM user_arc_access 
            WHERE user_id = ? AND (company_arc_id = ? OR arc_id = 1)
            LIMIT 1
        ''', (user_id, company_arc['company_arc_id']))
        
        access_type = cursor.fetchone()
        if access_type:
            if access_type[0] == 'trial':
                message += f"🎁 **Тип доступа:** Пробный (3 дня)\n"
            else:
                message += f"💰 **Тип доступа:** Полный (56 дней)\n"
    else:
        message += f"⚠️ **Статус доступа:** Нет доступа\n"
        message += f"   Для получения доступа нажмите '🎯 Купить тренинг'\n"
    
    conn.close()
    
    message += "\n**Выберите раздел:**"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_available_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📝 Показывает задания из ВСЕХ активных частей - ПОЛНАЯ ВЕРСИЯ С ПРОБНЫМ ДОСТУПОМ"""
    context.user_data['current_section'] = 'available_assignments'
    user_id = update.message.from_user.id

    print(f"🔍 DEBUG show_available_assignments: user_id={user_id}")
    
    # ★★★ ПРОВЕРКА КОМПАНИИ И ДОСТУПА ★★★
    from database import get_user_company, get_company_arc
    
    user_company = get_user_company(user_id)
    if not user_company:
        keyboard = [["🔑 Ввести ключ компании"], ["🔙 В главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ **Вы не состоите в компании!**\n\n"
            "Для доступа к заданиям необходимо присоединиться к компании.\n\n"
            "1. Получите ключ компании у администратора\n"
            "2. Перейдите в 👤 Профиль → 🔑 Ввести ключ компании\n"
            "3. Введите полученный ключ",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    company_arc = get_company_arc(user_company['company_id'])
    if not company_arc:
        await update.message.reply_text(
            "❌ **У вашей компании нет активного тренинга!**\n\n"
            "Обратитесь к администратору компании.",
            parse_mode='Markdown'
        )
        return
    
    company_arc_id = company_arc['company_arc_id']
    company_name = user_company['name']
    
    # ★★★ ПРОВЕРЯЕМ ДОСТУП ★★★
    import sqlite3
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Проверяем доступ к этой арке компании или к arc_id=1
    cursor.execute('''
        SELECT access_type FROM user_arc_access 
        WHERE user_id = ? AND (company_arc_id = ? OR arc_id = 1)
        LIMIT 1
    ''', (user_id, company_arc_id))
    
    access_result = cursor.fetchone()
    
    if not access_result:
        # НЕТ ДОСТУПА - предлагаем перейти в каталог
        keyboard = [
            ["🎯 Купить тренинг"],  # В каталог, а не прямую покупку
            ["🔙 В главное меню"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"⚠️ **Нет доступа к тренингу компании!**\n\n"
            f"🏢 **Компания:** {company_name}\n"
            f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n\n"
            f"Для получения доступа нажмите '🎯 Купить тренинг' и выберите тип доступа в каталоге.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        conn.close()
        return
    
    access_type = access_result[0]
    conn.close()
    
    # ★★★ ЕСТЬ ДОСТУП - получаем текущий день ★★★
    from database import get_current_arc_day
    
    current_day_info = get_current_arc_day(user_id, company_arc_id)
    
    if not current_day_info or current_day_info['day_number'] == 0:
        # Тренинг еще не начался
        days_left = 0
        if current_day_info and current_day_info['actual_start_date']:
            from datetime import datetime
            start_date = current_day_info['actual_start_date']
            if isinstance(start_date, str):
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
            today = datetime.now().date()
            days_left = (start_date - today).days
        
        message = f"📅 **Тренинг вашей компании еще не начался**\n\n"
        message += f"🏢 **Компания:** {company_name}\n"
        message += f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n"
        
        if days_left > 0:
            message += f"⏳ **До начала:** {days_left} дней\n\n"
            message += f"Задания станут доступны в день старта тренинга."
        else:
            message += f"🔄 **Тренинг начнется в ближайшее время.**"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    current_day_num = current_day_info['day_number']
    
    # ★★★ ОГРАНИЧЕНИЕ ДЛЯ ПРОБНОГО ДОСТУПА ★★★
    if access_type == 'trial':
        # Пробный доступ - максимум 3 дня
        max_allowed_day = 3
        
        if current_day_num > max_allowed_day:
            day_to_show = max_allowed_day
            
            # Получаем дату окончания пробного доступа
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT purchased_at FROM user_arc_access 
                WHERE user_id = ? AND (company_arc_id = ? OR arc_id = 1) AND access_type = 'trial'
                LIMIT 1
            ''', (user_id, company_arc_id))
            
            trial_start_result = cursor.fetchone()
            trial_end_str = ""
            
            if trial_start_result and trial_start_result[0]:
                from datetime import datetime, timedelta
                try:
                    trial_start = datetime.fromisoformat(trial_start_result[0])
                    trial_end = trial_start + timedelta(days=3)
                    trial_end_str = trial_end.strftime('%d.%m.%Y')
                except:
                    pass
            
            conn.close()
            
            message = f"🎁 **Пробный доступ завершен**\n\n"
            message += f"🏢 **Компания:** {company_name}\n"
            message += f"📅 **Текущий день тренинга:** {current_day_num}\n"
            message += f"🎯 **Доступные дни пробного доступа:** 1-3 из 56\n"
            
            if trial_end_str:
                message += f"⏰ **Пробный доступ до:** {trial_end_str}\n\n"
            else:
                message += f"\n"
                
            message += "💡 **Для продолжения обучения:**\n"
            message += "• Купите полный доступ для доступа ко всем 56 дням\n"
            message += "• Ваш прогресс сохранится\n"
            message += "• Нажмите '💰 Купить полный доступ' для перехода\n\n"
            
            keyboard = [
                ["💰 Купить полный доступ"],
                ["📚 В раздел Мои задания"],
                ["🔙 В главное меню"]
            ]
            
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                message,
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
            return
        else:
            day_to_show = current_day_num
            
            # Формируем сообщение для пробного доступа
            message = f"🎁 **ДОСТУПНЫЕ ЗАДАНИЯ (Пробный доступ)**\n\n"
            message += f"🏢 **Компания:** {company_name}\n"
            message += f"📅 **Текущий день тренинга:** {current_day_num}\n"
            message += f"🎯 **Доступные дни:** 1-3 (пробный период)\n"
            message += f"⏳ **Осталось дней пробного доступа:** {max_allowed_day - current_day_num + 1}\n\n"
            
            # Получаем дату окончания пробного доступа
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            cursor.execute('''
                SELECT purchased_at FROM user_arc_access 
                WHERE user_id = ? AND (company_arc_id = ? OR arc_id = 1) AND access_type = 'trial'
                LIMIT 1
            ''', (user_id, company_arc_id))
            
            trial_start_result = cursor.fetchone()
            
            if trial_start_result and trial_start_result[0]:
                from datetime import datetime, timedelta
                try:
                    trial_start = datetime.fromisoformat(trial_start_result[0])
                    trial_end = trial_start + timedelta(days=3)
                    now = datetime.now()
                    
                    if now < trial_end:
                        days_left = (trial_end - now).days
                        hours_left = (trial_end - now).seconds // 3600
                        message += f"⏰ **Осталось времени:** {days_left} дней {hours_left} часов\n\n"
                except:
                    pass
            
            conn.close()
    else:
        # Полный доступ
        day_to_show = current_day_num
        
        message = f"📝 **ДОСТУПНЫЕ ЗАДАНИЯ**\n\n"
        message += f"🏢 **Компания:** {company_name}\n"
        message += f"📅 **Текущий день тренинга:** {current_day_num}\n\n"
    
    # ★★★ ПОЛУЧАЕМ ЗАДАНИЯ ДЛЯ ТЕКУЩЕГО ДНЯ ★★★
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Получаем задания для текущего дня (из стандартного тренинга arc_id = 1)
    cursor.execute('''
        SELECT a.assignment_id, a.title, a.content_text, d.order_num as day_number
        FROM assignments a
        JOIN days d ON a.day_id = d.day_id
        WHERE d.arc_id = 1 AND d.order_num = ?
        ORDER BY a.assignment_id
    ''', (day_to_show,))
    
    day_assignments = cursor.fetchall()
    
    all_assignments_info = []
    total_available = 0
    total_in_progress = 0
    total_completed = 0
    
    for assignment_id, assignment_title, content_text, day_number in day_assignments:
        cursor.execute('''
            SELECT status FROM user_progress_advanced 
            WHERE user_id = ? AND assignment_id = ?
        ''', (user_id, assignment_id))
        
        status_result = cursor.fetchone()
        status = status_result[0] if status_result else 'new'
        
        # Сохраняем информацию
        assignment_info = {
            'company_arc_id': company_arc_id,
            'company_name': company_name,
            'assignment_id': assignment_id,
            'title': assignment_title,
            'status': status,
            'day_num': day_number,
            'day_to_show': day_to_show,
            'current_day_num': current_day_num
        }
        
        # Считаем статистику
        if status == 'new':
            all_assignments_info.append(assignment_info)
            total_available += 1
        elif status == 'submitted':
            total_in_progress += 1
        elif status == 'approved':
            total_completed += 1
    
    conn.close()
    
    # ★★★ ФОРМИРУЕМ ОСНОВНОЕ СООБЩЕНИЕ ★★★
    if not all_assignments_info:
        message += f"✅ **Все задания дня {current_day_num} выполнены!**\n\n"
        
        if access_type == 'trial' and current_day_num >= 3:
            message += f"🎁 **Вы завершили пробный период!**\n\n"
            message += "💡 **Для продолжения обучения:**\n"
            message += "• Купите полный доступ для доступа ко всем 56 дням\n"
            message += "• Ваш прогресс сохранится\n\n"
            
            keyboard = [
                ["💰 Купить полный доступ"],
                ["📚 В раздел Мои задания"],
                ["🔙 В главное меню"]
            ]
        else:
            message += f"🔄 **Новые задания откроются завтра**\n\n"
            
            if current_day_num >= 56:
                message += f"🎉 **Поздравляем! Вы завершили 8-недельный тренинг!**"
            
            keyboard = [
                ["📚 В раздел Мои задания"],
                ["🔙 В главное меню"]
            ]
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    # Добавляем инструкцию к сообщению
    message += f"Доступно заданий: {total_available}\n"
    message += f"На проверке: {total_in_progress}\n"
    message += f"Выполнено: {total_completed}\n\n"
    
    message += "💡 **Как выполнять задания:**\n\n"
    message += "1. Нажмите на задание из списка ниже\n\n"
    message += "2. Выберите подходящий способ ответа\n\n"
    message += "3. Выполните задание и отправьте на проверку\n\n"
    message += "4. Задания открываются последовательно\n\n"
    message += "5. Выполненное задание будет в 'Архив заданий'\n\n"
    
    if access_type == 'trial':
        message += "🎁 **Пробный доступ:** только первые 3 дня\n\n"
    
    message += "Выберите задание:"
    
    # ★★★ СОЗДАЕМ КЛАВИАТУРУ ★★★
    keyboard = []
    assignments_mapping = []
    
    # Группируем задания по 2 в ряд
    row = []
    for i, assignment in enumerate(all_assignments_info[:24]):  # Ограничиваем 24 заданиями
        btn_text = f"📝 {assignment['title']}"
        row.append(btn_text)
        
        assignments_mapping.append({
            'btn_text': btn_text,
            'company_arc_id': assignment['company_arc_id'],
            'assignment_id': assignment['assignment_id'],
            'title': assignment['title'],
            'company_name': assignment['company_name']
        })
        
        if len(row) == 2 or i == len(all_assignments_info[:24]) - 1:
            keyboard.append(row)
            row = []
    
    if total_in_progress > 0:
        keyboard.append(["🟡 Задания на проверке"])
    
    # Добавляем кнопки в зависимости от типа доступа
    if access_type == 'trial':
        keyboard.append(["💰 Купить полный доступ"])  # Кнопка апгрейда
        keyboard.append(["📚 В раздел Мои задания"])
    else:
        keyboard.append(["📚 В раздел Мои задания"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Сохраняем данные для обработки нажатий
    context.user_data['assignments_mapping'] = assignments_mapping
    context.user_data['current_company_arc_id'] = company_arc_id
    context.user_data['current_company_name'] = company_name
    context.user_data['current_access_type'] = access_type  # Сохраняем тип доступа
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )



async def show_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали задания и ВЫБОР ТИПА ОТВЕТА"""
    user_id = update.message.from_user.id
    
    # 1. Получаем assignment_id из контекста (новый путь) или из текста (старый путь)
    assignment_id = context.user_data.get('current_assignment_id')
    
    if not assignment_id:
        # Старый путь: через текст кнопки
        assignment_title = update.message.text[2:].strip()
        
        day_title = context.user_data.get('current_day')
        arc_id = context.user_data.get('current_arc_id')
        
        if not day_title or not arc_id:
            await update.message.reply_text("❌ Ошибка: день не определен")
            return
        
        from database import get_day_id_by_title_and_arc, get_assignment_by_title_and_day
        
        day_id = get_day_id_by_title_and_arc(day_title, arc_id)
        if not day_id:
            await update.message.reply_text("❌ Ошибка: день не найден")
            return

        if " (до" in assignment_title:
            clean_title = assignment_title.split(" (до")[0].strip()
        else:
            clean_title = assignment_title

        assignment_id = get_assignment_by_title_and_day(clean_title, day_id)
        context.user_data['current_day_id'] = day_id
    
    if not assignment_id:
        await update.message.reply_text("❌ Задание не найдено")
        return
    
    # 2. Получаем данные задания
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT a.content_text, a.доступно_до, a.title, d.title as day_title, d.arc_id
        FROM assignments a
        JOIN days d ON a.day_id = d.day_id
        WHERE a.assignment_id = ?
    ''', (assignment_id,))

    result = cursor.fetchone()
    
    if not result:
        await update.message.reply_text("❌ Задание не найдено")
        conn.close()
        return

    content_text, available_until, assignment_title, day_title, arc_id = result
    
    # 3. Проверяем доступ (пробный 3 дня)
    from database import can_access_assignment
    can_access, access_message = can_access_assignment(user_id, assignment_id, arc_id)
    
    if not can_access:
        await update.message.reply_text(f"❌ {access_message}")
        conn.close()
        return
    
    # 4. Проверяем статус задания
    cursor.execute('''
        SELECT status FROM user_progress_advanced 
        WHERE user_id = ? AND assignment_id = ?
    ''', (user_id, assignment_id))
    
    progress = cursor.fetchone()
    
    if progress and progress[0] == 'submitted':
        await update.message.reply_text(
            "⏳ **Ваше задание уже на проверке!**\n\n"
            "Дождитесь обратной связи в разделе 'Ответ психолога'.",
            parse_mode='Markdown'
        )
        conn.close()
        return
    
    conn.close()
    
    # 5. Отправляем заголовок
    header = f"**📝 {assignment_title}**\n\n"
    
    if available_until and available_until != '22:00':
        header += f"⏰ **Сделать до:** {available_until} по вашему времени\n\n"
    
    await update.message.reply_text(header, parse_mode='Markdown')
    
    # 6. Отправляем текст задания через send_long_message
    if content_text:
        await send_long_message(update, content_text, "**Задание:**")
    
    # 7. Отправляем выбор типа ответа
    message = "**📤 Выберите вариант ответа:**"
    
    keyboard = [
        ["📷 Только фото"],
        ["📝 Только текст"],
        ["📷+📝 Фото и текст"],
        ["🔙 Назад в меню заданий"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    context.user_data['current_assignment'] = assignment_title
    context.user_data['current_assignment_id'] = assignment_id
    context.user_data['current_arc_id'] = arc_id
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_assignment_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, answer_type=None):
    """Начинает процесс ответа в зависимости от выбранного типа"""
    if not answer_type:
        answer_type = update.message.text
    
    context.user_data['answer_type'] = answer_type
    
    if answer_type == "📷 Только фото":
        await update.message.reply_text(
            "📷 **Отправьте фото для задания:**\n\n"
            "Прикрепите одно или несколько фото.",
            parse_mode='Markdown'
        )
        context.user_data['waiting_for_photo'] = True
        
    elif answer_type == "📝 Только текст":
        await update.message.reply_text(
            "📝 **Напишите текстовый ответ:**\n\n"
            "Опишите свои мысли, чувства или выполнение упражнения.",
            parse_mode='Markdown'
        )
        context.user_data['waiting_for_text'] = True
        
    elif answer_type == "📷+📝 Фото и текст":
        await update.message.reply_text(
            "📝 **Сначала напишите текстовый ответ:**\n\n"
            "Опишите свои мысли, чувства или выполнение упражнения.\n"
            "После текста нужно будет прикрепить фото.",
            parse_mode='Markdown'
        )
        context.user_data['waiting_for_text'] = True
        context.user_data['need_photo_after_text'] = True

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    
    # ★★★ ОБРАБОТКА СОЗДАНИЯ КОМПАНИИ ★★★
    if context.user_data.get('company_creation_stage'):
        await create_company_process(update, context)
        return
    
    # ★★★ ОБРАБОТКА КЛЮЧА КОМПАНИИ ★★★
    if context.user_data.get('waiting_for_company_key'):
        await process_company_key(update, context)
        return

    # ★ НОВОЕ: Обработка отмены получения file_id
    if context.user_data.get('waiting_for_file_id'):
        if text in ['отмена', 'отменить', 'cancel', 'стоп', 'stop']:
            context.user_data.pop('waiting_for_file_id', None)
            await update.message.reply_text(
                "❌ **Режим получения File ID отменен.**",
                parse_mode='Markdown'
            )
            return

    # Обработка текста для уведомлений
    if context.user_data.get('notification_stage') == 'waiting_content':
        # Проверяем не нажата ли кнопка "Отменить"
        if text == "🔙 Отменить":
            # Очищаем данные
            for key in ['notification_stage', 'notification_recipients']:
                context.user_data.pop(key, None)
            await admin_tools_menu(update, context)
            return
        
        # Обрабатываем текст уведомления
        await process_notification_content(update, context)
        return
    
    # Обработка кнопок в предпросмотре уведомления
    if context.user_data.get('notification_stage') == 'preview':
        if text == "📤 Отправить":
            await send_notification_final(update, context)
            return
        elif text == "✏️ Изменить":
            context.user_data['notification_stage'] = 'waiting_content'
            # Очищаем старый контент
            for key in ['notification_text', 'notification_photo', 'notification_document']:
                context.user_data.pop(key, None)
            
            await update.message.reply_text(
                "✏️ Отправьте новое сообщение с уведомлением:\n"
                "(можно прикрепить фото или файл)",
                reply_markup=ReplyKeyboardMarkup([["🔙 Отменить"]], resize_keyboard=True),
                parse_mode='Markdown'
            )
            return
        elif text == "❌ Отменить":
            # Очищаем все данные уведомления
            for key in ['notification_stage', 'notification_recipients', 'notification_text',
                       'notification_photo', 'notification_document', 'notification_users']:
                context.user_data.pop(key, None)
            await admin_tools_menu(update, context)
            return

    # === 1. ОБРАБОТКА ОТКАЗА ОТ ОФЕРТЫ ===
    if text == "❌ Отказаться":
        await update.message.reply_text(
            "❌ **Вы отказались от оферты.**\n\n"
            "Для использования бота необходимо принять оферту.\n"
            "Вы можете вернуться к этому позже в разделе 'Профиль'.",
            reply_markup=ReplyKeyboardMarkup([["🔙 В главное меню"]], resize_keyboard=True)
        )
        return

    # === 3. ОБРАБОТКА ВВОДА ТЕЛЕФОНА ===
    if context.user_data.get('waiting_for_phone'):
        phone = update.message.text.strip()
        
        import re
        phone_clean = re.sub(r'[^\d+]', '', phone)
        
        if phone_clean.startswith('+'):
            phone_clean = phone_clean[1:]
        
        if len(phone_clean) == 11 and phone_clean.startswith(('7', '8')):
            formatted_phone = f"+7{phone_clean[1:]}"
            
            print(f"🔍 Введен телефон: {formatted_phone}")
            
            # Сохраняем телефон в БД
            from database import accept_offer
            accept_offer(user_id, phone=formatted_phone, fio=None)
            
            context.user_data['waiting_for_phone'] = False
            
            await update.message.reply_text(
                f"✅ **Телефон принят и сохранен!**\n\n"
                f"📝 **Теперь введите ваше ФИО:**\n"
                f"(Обязательно имя и фамилия, минимум 2 слова)\n\n"
                f"**Пример:** Иванов Иван\n"
                f"**Пример:** Анна Петрова",
                parse_mode='Markdown'
            )
            
            context.user_data['waiting_for_fio'] = True
            return
        
        elif len(phone_clean) == 10 and phone_clean.startswith('9'):
            formatted_phone = f"+7{phone_clean}"
            
            print(f"🔍 Введен телефон: {formatted_phone}")
            
            # Сохраняем телефон в БД
            from database import accept_offer
            accept_offer(user_id, phone=formatted_phone, fio=None)
            
            context.user_data['waiting_for_phone'] = False
            
            await update.message.reply_text(
                f"✅ **Телефон принят и сохранен!**\n\n"
                f"📝 **Теперь введите ваше ФИО:**\n"
                f"(Обязательно имя и фамилия, минимум 2 слова)\n\n"
                f"**Пример:** Иванов Иван\n"
                f"**Пример:** Анна Петрова",
                parse_mode='Markdown'
            )
            return
            
            context.user_data['waiting_for_fio'] = True
        
        else:
            await update.message.reply_text(
                "❌ **Некорректный номер телефона.**\n\n"
                "Номер должен содержать 11 цифр.\n"
                "**Примеры правильных форматов:**\n"
                "• +79001234567\n"
                "• 89001234567\n"
                "• 79001234567\n\n"
                "Пожалуйста, введите номер еще раз:",
                parse_mode='Markdown'
            )
            return
        return

    # === 4. ОБРАБОТКА ВВОДА ФИО ===
    if context.user_data.get('waiting_for_fio'):
        fio = update.message.text.strip()
        user_id = update.message.from_user.id
    
        print(f"🔍 Введено ФИО: '{fio}'")
    
        # Проверяем что минимум 2 слова
        words = fio.split()
        if len(words) < 2:
            await update.message.reply_text(
                "❌ **ФИО должно содержать имя и фамилию.**\n\n"
                "Пожалуйста, введите минимум 2 слова (имя и фамилию).\n"
                "**Примеры:**\n"
                "• Иванов Иван\n"
                "• Анна Петрова\n"
                "• Мария Сергеевна",
                parse_mode='Markdown'
            )
            return
    
        # Проверяем что каждое слово минимум 2 символа
        short_words = []
        for word in words:
            if len(word.strip()) < 2:
                short_words.append(word)
    
        if short_words:
            await update.message.reply_text(
                f"❌ **Слишком короткие слова:** {', '.join(short_words)}\n\n"
                "Каждое слово должно быть минимум 2 символа.",
                parse_mode='Markdown'
            )
            return
    
        # Проверяем общую длину
        if len(fio) < 5:
            await update.message.reply_text(
                "❌ **ФИО слишком короткое.**\n\n"
                "Общая длина должна быть минимум 5 символов.",
                parse_mode='Markdown'
            )
            return
    
        # Сохраняем ФИО в БД
        from database import accept_offer
        success = accept_offer(user_id, phone=None, fio=fio)
    
        if success:
            # Очищаем все флаги регистрации
            for key in ['waiting_for_fio', 'waiting_for_phone', 'showing_offer']:
                if key in context.user_data:
                    del context.user_data[key]
        
            await update.message.reply_text(
                f"🎉 **Регистрация завершена! Остался последний шаг - выбрать часовой пояс. Это необходимо, чтобы бот открывал задания и отправлял уведомления согласно вашему времени.**\n\n"
                f"✅ ФИО: {fio}\n\n"
                "Теперь вы можете пользоваться всеми функциями бота.",
                reply_markup=ReplyKeyboardMarkup([["⏰ Часовой пояс"]], resize_keyboard=True),
                parse_mode='Markdown'
            )
        
            # НЕ переходим в профиль - пусть нажмет кнопку
        else:
            await update.message.reply_text(
                "❌ **Ошибка сохранения ФИО.**\n\n"
                "Пожалуйста, попробуйте еще раз или обратитесь в поддержку.",
                parse_mode='Markdown'
            )
        return

    # === 5. ОБРАБОТКА ВОПРОСОВ К ЗАДАНИЯМ ===
    if context.user_data.get('waiting_for_question'):
        question = text
        
        if 'questions' not in context.user_data:
            context.user_data['questions'] = []
        
        context.user_data['questions'].append(question)
        context.user_data['waiting_for_question'] = False
        
        answer_type = context.user_data.get('answer_type', 'Фото_и_текст')
        if answer_type in ['Только_фото', 'Только_текст']:
            await show_submit_button(update, context)
        else:
            await show_final_buttons(update, context)
        
        await update.message.reply_text(
            f"✅ **Вопрос добавлен!**\n\n"
            f"*{question[:100]}...*",
            parse_mode='Markdown'
        )
        return

    # === 6. ОБРАБОТКА ОТВЕТОВ НА ЗАДАНИЯ ===
    if context.user_data.get('answering'):
        answer_type = context.user_data.get('answer_type', 'Фото_и_текст')
        
        if answer_type == 'Только_текст':
            context.user_data['answer_text'] = text
            await show_submit_button(update, context)
            return
        
        elif answer_type == 'Фото_и_текст':
            if not context.user_data.get('answer_text'):
                context.user_data['answer_text'] = text
                await update.message.reply_text(
                    "✅ **Текст сохранен!**\n\n"
                    "📎 **Теперь прикрепите фото к ответу:**",
                    parse_mode='Markdown'
                )
                return
            
            elif context.user_data.get('answer_files'):
                context.user_data['questions'].append(text)
                await show_final_buttons(update, context)
                return
        
        elif answer_type == 'Только_фото':
            await update.message.reply_text(
                "📷 **Вы выбрали вариант 'Только фото'.**\n\n"
                "Пожалуйста, отправьте фото для задания.",
                parse_mode='Markdown'
            )
            return

    # === 7. ОБРАБОТКА КОММЕНТАРИЕВ АДМИНА ===
    if context.user_data.get('waiting_for_comment') and is_admin(user_id):
        comment = update.message.text
        context.user_data['current_comment'] = comment
        context.user_data['waiting_for_comment'] = False
    
        keyboard = [
            ["✅ Принять задание"],
            ["🔙 Вернуться в меню проверки"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
        await update.message.reply_text(
            f"💬 **Комментарий сохранен!**\n\n*{comment}*\n\n**Нажмите кнопку чтобы принять задание:**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
 
    elif is_admin(user_id) and context.user_data.get('current_comment'):
        additional_text = update.message.text
        current_comment = context.user_data['current_comment']
        context.user_data['current_comment'] = current_comment + "\n\n" + additional_text
    
        keyboard = [
            ["✅ Принять задание"],
            ["🔙 Вернуться в меню проверки"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
        await update.message.reply_text(
            f"💬 **Дополнение добавлено к комментарию!**\n\n*{additional_text}*\n\n**Нажмите кнопку чтобы принять задание:**",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return

    # === ОБРАБОТКА КОММЕНТАРИЯ АДМИНА К АВТОМАТИЧЕСКИ ПРИНЯТОМУ ЗАДАНИЮ ===
    if context.user_data.get('waiting_for_admin_comment'):
        if text == "🔙 Отмена комментария":
            context.user_data.pop('waiting_for_admin_comment', None)
            context.user_data.pop('current_auto_approved_assignment', None)
            await admin_auto_approved_menu(update, context)
            return
        
        # Сохраняем комментарий
        assignment_info = context.user_data.get('current_auto_approved_assignment')
        if assignment_info:
            from database import add_admin_comment_to_assignment
            add_admin_comment_to_assignment(
                assignment_info['assignment_id'],
                assignment_info['user_id'],
                text
            )
            
            # Очищаем данные
            context.user_data.pop('waiting_for_admin_comment', None)
            context.user_data.pop('current_auto_approved_assignment', None)
            
            await update.message.reply_text(
                f"✅ **Комментарий добавлен к заданию!**\n\n"
                f"Участник: {assignment_info['display_name']}\n"
                f"Задание: {assignment_info['assignment_title']}",
                parse_mode='Markdown'
            )
            
            # Возвращаем в меню
            await admin_auto_approved_menu(update, context)
        return

    # === 8. ОБРАБОТКА ДОПОЛНИТЕЛЬНЫХ КОММЕНТАРИЕВ АДМИНА ===
    if context.user_data.get('waiting_for_additional_comment'):
        comment_text = update.message.text
        
        if comment_text == "🔙 Отменить":
            # Очищаем флаги
            context.user_data.pop('waiting_for_additional_comment', None)
            context.user_data.pop('comment_for_student_id', None)
            context.user_data.pop('comment_for_assignment_id', None)
            
            await update.message.reply_text(
                "❌ **Добавление комментария отменено.**",
                parse_mode='Markdown'
            )
            
            # Возвращаемся к просмотру задания
            if context.user_data.get('current_student_id') and context.user_data.get('current_assignment_id'):
                # Вызываем функцию просмотра задания снова
                await show_approved_assignment_simple(update, context)
            return
        
        student_id = context.user_data.get('comment_for_student_id')
        assignment_id = context.user_data.get('comment_for_assignment_id')
        
        if not student_id or not assignment_id:
            await update.message.reply_text("❌ Ошибка: данные не найдены")
            return
        
        # Сохраняем комментарий
        from database import add_additional_comment_to_assignment
        success = add_additional_comment_to_assignment(student_id, assignment_id, comment_text)
        
        if success:
            # Очищаем флаги
            context.user_data.pop('waiting_for_additional_comment', None)
            context.user_data.pop('comment_for_student_id', None)
            context.user_data.pop('comment_for_assignment_id', None)
            
            # Получаем данные участника для уведомления
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            cursor.execute('SELECT fio FROM users WHERE user_id = ?', (student_id,))
            result = cursor.fetchone()
            student_name = result[0] if result and result[0] else f"Участник {student_id}"
            conn.close()
            
            await update.message.reply_text(
                f"✅ **Комментарий успешно добавлен!**\n\n"
                f"**Участник:** {student_name}\n"
                f"**Комментарий:**\n{comment_text[:100]}...\n\n"
                f"🟡 Теперь задание появится у участника в разделе '🟡 Новые ответы'",
                parse_mode='Markdown'
            )
            
            # Возвращаемся к просмотру задания
            if context.user_data.get('current_student_id') and context.user_data.get('current_assignment_id'):
                await show_approved_assignment_simple(update, context)
        else:
            await update.message.reply_text(
                "❌ **Ошибка при сохранении комментария.**\n"
                "Попробуйте еще раз или обратитесь к разработчику.",
                parse_mode='Markdown'
            )
        return

    if context.user_data.get('waiting_for_additional_comment'):
        await handle_additional_comment(update, context)
        return

    # === ОБРАБОТКА ВЫБОРА МАРАФОНА ===
    if 'arc_selection_map' in context.user_data and update.message.text in context.user_data['arc_selection_map']:
        await show_tests_for_arc(update, context)
        return

    # === ОБРАБОТКА ОТВЕТОВ ТЕСТА ===
    if context.user_data.get('current_section') == 'testing' and update.message.text in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "⏹️ Прервать тест"]:
        await process_test_answer(update, context)
        return
    
    # === ОБРАБОТКА ВЫБОРА ТЕСТА ===
    if 'test_mapping' in context.user_data and update.message.text in context.user_data['test_mapping']:
        await start_test(update, context)
        return
    
    # === ОБРАБОТКА ВЫБОРА МАРАФОНА ДЛЯ РЕЗУЛЬТАТОВ ===
    if 'arc_results_mapping' in context.user_data and update.message.text in context.user_data['arc_results_mapping']:
        await show_tests_for_arc_results(update, context)
        return
    
    # === ОБРАБОТКА ВЫБОРА ТЕСТА ДЛЯ РЕЗУЛЬТАТОВ ===
    if 'test_results_mapping' in context.user_data and update.message.text in context.user_data['test_results_mapping']:
        test_info = context.user_data['test_results_mapping'][update.message.text]
        await show_test_results(update, context, 
                              update.message.from_user.id,
                              test_info['arc_id'],
                              test_info['week_num'])
        return

    # === ОБРАБОТКА ОТВЕТОВ ТЕСТА ===
    # Теперь проверяем не цифры, а наличие активного теста
    if context.user_data.get('current_test') and not context.user_data.get('waiting_for_question'):
        # ★★ ИСПРАВЛЕНИЕ: Проверяем не кнопки 1️⃣-5️⃣, а любой текст при активном тесте
        # (кроме специальных команд)
        if text != "⏹️ Прервать тест":
            await process_test_answer(update, context)
            return
    
async def show_final_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает финальные кнопки после ответа (фото+текст)"""
    keyboard = [
        ["💬 Задать вопрос"],
        ["✅ Отправить задание"],
        ["🔙 Назад в меню заданий"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    files_count = len(context.user_data.get('answer_files', []))
    questions_count = len(context.user_data.get('questions', []))
    
    await update.message.reply_text(
        f"📊 **Готово!**\n\n"
        f"✅ Текст ответа: сохранен\n"
        f"📎 Фото: {files_count} шт.\n"
        f"💬 Вопросы: {questions_count} шт.\n\n"
        f"**Вы можете:**\n"
        f"• Добавить еще файлы\n"
        f"• Задать вопросы\n"
        f"• **Отправить задание на проверку**\n\n"
        f"После отправки изменить ответ будет нельзя!",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    
async def finish_assignment_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает отправку ответа и сохраняет в БД - ОБНОВЛЕННАЯ ДЛЯ КОМПАНИЙ"""
    user_id = update.message.from_user.id
    
    # Получаем данные из контекста
    assignment_id = context.user_data.get('current_assignment_id')
    day_id = context.user_data.get('current_day_id')
    answer_text = context.user_data.get('answer_text')
    answer_files = context.user_data.get('answer_files', [])
    questions = context.user_data.get('questions', [])
    arc_id = context.user_data.get('current_arc_id', 1)
    company_arc_id = context.user_data.get('current_company_arc_id')
    
    if not assignment_id:
        await update.message.reply_text("❌ Ошибка: не найдено задание")
        return
    
    # Формируем полный ответ с вопросами
    full_answer = answer_text if answer_text else ""
    
    if questions:
        if full_answer:
            full_answer += "\n\n"
        full_answer += "📋 **Вопросы к психологу:**\n"
        for i, question in enumerate(questions, 1):
            full_answer += f"{i}. {question}\n"
    
    print(f"🔍 DEBUG: Сохранение ответа: user={user_id}, assignment={assignment_id}, day={day_id}")
    
    # ★★★ СОХРАНЯЕМ ОТВЕТ В БАЗУ ★★★
    from database import save_assignment_answer_with_day_auto_approve
    
    # Сохраняем ответ с автоматическим принятием
    save_assignment_answer_with_day_auto_approve(
        user_id=user_id,
        assignment_id=assignment_id,
        day_id=day_id,
        answer_text=full_answer,
        answer_files=answer_files
    )
    
    # Очищаем контекст
    for key in ['answering', 'answer_text', 'answer_files', 'questions', 
                'current_assignment', 'current_assignment_id', 'current_day_id']:
        if key in context.user_data:
            del context.user_data[key]
    
    # ★★★ ПОКАЗЫВАЕМ ПОДТВЕРЖДЕНИЕ ★★★
    keyboard = [
        ["📝 Доступные задания"],
        ["📚 В раздел Мои задания"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "✅ Задание принято автоматически.\n\n"
        "У психолога есть возможность просмотреть все ваши задания и прикрепить к ним комментарии.\n\n"
        "Выполненные задания будут храниться в архиве заданий.\n\n"
        "Выберите следующее действие:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_assignment_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает вопрос к заданию"""
    question = update.message.text
    user_id = update.message.from_user.id
    
    if 'assignment_questions' not in context.user_data:
        context.user_data['assignment_questions'] = []
    
    context.user_data['assignment_questions'].append(question)
    context.user_data['waiting_for_question'] = False
    
    keyboard = [["✅ Завершить", "💬 Добавить еще вопрос"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"✅ **Вопрос добавлен!**\n\n"
        f"*{question}*\n\n"
        f"Хотите добавить еще вопрос или завершить отправку?",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def finish_assignment_with_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает отправку задания с вопросами"""
    user_id = update.message.from_user.id
    assignment_id = context.user_data.get('current_assignment_id')
    answer_text = context.user_data.get('current_answer_text')
    answer_files = context.user_data.get('current_answer_files', [])
    questions = context.user_data.get('assignment_questions', [])
    
    full_answer = answer_text
    if questions:
        full_answer += "\n\nВопросы:\n" + "\n".join(f"- " + q for q in questions)
    
    from database import save_assignment_answer
    save_assignment_answer(user_id, assignment_id, full_answer, answer_files)
    
    context.user_data['asking_questions'] = False
    context.user_data['waiting_for_question'] = False
    context.user_data['assignment_questions'] = []
    context.user_data['current_answer_text'] = None
    context.user_data['current_answer_files'] = []
    
    await update.message.reply_text(
        "🎉 **Ваш ответ отправлен психологу!**\n\n"
        "Он проверит вашу работу и оставит обратную связь.\n"
        "Статус можно отслеживать в 'Отправленные задания'.",
        parse_mode='Markdown'
    )
    
    await start(update, context)

async def show_new_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['view_mode'] = 'new'
    context.user_data['current_section'] = 'admin'
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Прямо получаем участников с новыми заданиями и их частями
    cursor.execute('''
        SELECT DISTINCT 
            u.user_id, 
            COALESCE(u.fio, u.username, 'ID:' || u.user_id) as display_name,
            ar.title as part_title,
            ar.arc_id,
            COUNT(upa.assignment_id) as new_count
        FROM users u
        JOIN user_progress_advanced upa ON u.user_id = upa.user_id
        JOIN assignments a ON upa.assignment_id = a.assignment_id
        JOIN days d ON a.day_id = d.day_id
        JOIN arcs ar ON d.arc_id = ar.arc_id
        WHERE upa.status = 'submitted'
        GROUP BY u.user_id, ar.arc_id
        ORDER BY new_count DESC
    ''')
    
    students_data = cursor.fetchall()
    conn.close()
    
    if not students_data:
        await update.message.reply_text("✅ Нет новых заданий для проверки")
        return
    
    keyboard = []
    student_mapping = {}
    
    for user_id, display_name, part_title, arc_id, new_count in students_data:
        # Обрезаем длинные имена
        if len(display_name) > 20:
            display_name = display_name[:17] + "..."
        
        # Формат: 👤 Имя - Часть X (N новых)
        btn_text = f"👤 {display_name} - {part_title} ({new_count} новых)"
        keyboard.append([btn_text])
        
        # Сохраняем mapping: кнопка → (user_id, arc_id)
        student_mapping[btn_text] = {'user_id': user_id, 'arc_id': arc_id}
    
    context.user_data['student_mapping'] = student_mapping
    
    keyboard.append(["🔙 Назад к проверке"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🆕 **Новые задания для проверки:**\n\n"
        "Выберите участника и марафон:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
async def show_student_part_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ВСЕ новые задания участника в выбранной части"""
    context.user_data['view_mode'] = 'new'
    print(f"🚨 Установлен view_mode='new' в show_student_part_assignments")
    text = update.message.text
    
    # Извлекаем данные из mapping
    student_mapping = context.user_data.get('student_mapping', {})
    mapping_data = student_mapping.get(text)
    
    if not mapping_data:
        await update.message.reply_text("❌ Ошибка: не удалось определить участника")
        return
    
    user_id = mapping_data['user_id']
    arc_id = mapping_data['arc_id']
    
    # Сохраняем в контексте
    context.user_data['current_student_id'] = user_id
    context.user_data['current_arc_id'] = arc_id
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Получаем имя участника и название части
    cursor.execute('SELECT fio, username FROM users WHERE user_id = ?', (user_id,))
    user_info = cursor.fetchone()
    display_name = user_info[0] if user_info[0] else (user_info[1] if user_info[1] else f"ID: {user_id}")
    
    cursor.execute('SELECT title FROM arcs WHERE arc_id = ?', (arc_id,))
    part_title = cursor.fetchone()[0]
    
    # Получаем ВСЕ новые задания участника в этой части
    cursor.execute('''
        SELECT a.assignment_id, a.title, d.title as day_title,
               a.content_text, upa.answer_text
        FROM assignments a
        JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
        JOIN days d ON a.day_id = d.day_id
        WHERE upa.user_id = ? AND upa.status = 'submitted' AND d.arc_id = ?
        ORDER BY d.order_num, a.assignment_id
    ''', (user_id, arc_id))
    
    assignments = cursor.fetchall()
    conn.close()
    
    if not assignments:
        await update.message.reply_text("❌ В этой части нет новых заданий")
        return
    
    keyboard = []
    
    for assignment_id, assignment_title, day_title, content_text, answer_text in assignments:
        # Обрезаем длинные названия
        short_content = (content_text[:30] + "...") if content_text else "без описания"
        btn_text = f"📝 {assignment_title} ({day_title})"
        keyboard.append([btn_text])
    
    keyboard.append(["🔙 Назад к списку участников"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"📋 **Новые задания участника:**\n\n"
        f"👤 **Участник:** {display_name}\n"
        f"🔄 {part_title}\n"
        f"📊 **Всего заданий:** {len(assignments)}\n\n"
        f"Выберите задание для проверки:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_student_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает тренинги выбранного участника"""
    text = update.message.text
    
    student_mapping = context.user_data.get('student_mapping', {})
    student_id = student_mapping.get(text)
    
    if not student_id:
        await update.message.reply_text("❌ Ошибка: не удалось определить участника")
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT c.course_id, c.title
        FROM courses c
        JOIN arcs a ON c.course_id = a.course_id
        JOIN days d ON a.arc_id = d.arc_id
        JOIN assignments ass ON d.day_id = ass.day_id
        JOIN user_progress_advanced upa ON ass.assignment_id = upa.assignment_id
        WHERE upa.user_id = ? AND upa.status = 'submitted'
    ''', (student_id,))
    
    courses = cursor.fetchall()
    conn.close()
    
    if not courses:
        await update.message.reply_text("❌ У участника нет тренингов с новыми заданиями")
        return
    
    keyboard = []
    for course_id, course_title in courses:
        keyboard.append([f"📖 {course_title}"])
    
    keyboard.append(["🔙 Назад к новым заданиям"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    context.user_data['current_student_id'] = student_id
    
    await update.message.reply_text(
        "📚 **Тренинги участника:**\n\n"
        "Выберите тренинг:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_assignment_for_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_section'] = 'admin'
    text = update.message.text
    
    print(f"🚨 [1] show_assignment_for_admin: text='{text}'")
    
    # Определяем префикс (📝 или ✅)
    if text.startswith("📝 "):
        assignment_title = text[2:].strip()
    elif text.startswith("✅ "):
        assignment_title = text[2:].strip()
    else:
        assignment_title = text.strip()
    
    print(f"🚨 [2] assignment_title='{assignment_title}'")
    
    # Парсинг дня из скобок (одинаково для 📝 и ✅)
    day_title = None
    if "(" in assignment_title and ")" in assignment_title:
        import re
        match = re.search(r'\((.*?)\)', assignment_title)
        if match:
            day_title = match.group(1).strip()
            assignment_title = assignment_title.split("(")[0].strip()
    
    print(f"🚨 [3] clean assignment_title='{assignment_title}'")
    print(f"🚨 [4] extracted day_title='{day_title}'")
    
    # Если извлекли день из кнопки - используем его
    if day_title:
        context.user_data['current_day'] = day_title
        print(f"🚨 [5] Сохранили в контекст: current_day='{day_title}'")
    
    student_id = context.user_data.get('current_student_id')
    print(f"🚨 [6] student_id={student_id}")
 
    if not student_id:
        await update.message.reply_text("❌ Ошибка: участник не выбран")
        return
    
    day_id = context.user_data.get('current_day_id')
    
    if not day_id:
        day_title = context.user_data.get('current_day')
        arc_id = context.user_data.get('current_arc_id')
        
        if day_title and arc_id:
            from database import get_day_id_by_title_and_arc
            day_id = get_day_id_by_title_and_arc(day_title, arc_id)
    
    if not day_id:
        await update.message.reply_text("❌ Ошибка: день не определен")
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT day_id, title FROM days WHERE day_id = ?', (day_id,))
    day_info = cursor.fetchone()
    
    cursor.execute('''
        SELECT assignment_id, title 
        FROM assignments 
        WHERE title = ? AND day_id = ?
    ''', (assignment_title, day_id))
    assignment_info = cursor.fetchone()
    
    cursor.execute('''
        SELECT COUNT(*) 
        FROM user_progress_advanced 
        WHERE assignment_id = ? AND user_id = ?
    ''', (assignment_info[0] if assignment_info else 0, student_id))
    answer_count = cursor.fetchone()[0]
    
    conn.close()
    
    if not assignment_info:
        import re
        clean_title = re.sub(r'^[^a-zA-Zа-яА-Я0-9]+', '', assignment_title)
        
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT assignment_id, title 
            FROM assignments 
            WHERE title = ? AND day_id = ?
        ''', (clean_title, day_id))
        assignment_info = cursor.fetchone()
        conn.close()
    
    if not assignment_info:
        await update.message.reply_text(f"❌ Задание '{assignment_title}' не найдено в дне {day_id}")
        return

    assignment_id, found_title = assignment_info
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''  
        SELECT a.assignment_id, a.content_text, 
               upa.answer_text, upa.answer_files, upa.status,
               u.fio, u.username, upa.teacher_comment
        FROM assignments a
        JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
        JOIN users u ON upa.user_id = u.user_id
        WHERE a.title = ? AND upa.user_id = ? AND a.day_id = ?
    ''', (found_title, student_id, day_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text("❌ Задание не найдено")
        return
    
    
    assignment_id, content_text, answer_text, answer_files, status, fio, username, teacher_comment = result
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.title, ar.title 
        FROM days d
        JOIN arcs ar ON d.arc_id = ar.arc_id
        WHERE d.day_id = ?
    ''', (day_id,))
    day_info = cursor.fetchone()
    conn.close()
    
    day_title = day_info[0] if day_info else "Неизвестно"
    arc_title = day_info[1] if day_info else "Неизвестно"
    
    display_name = fio if fio else username
    message = f"**📝 Задание: {assignment_title}**\n\n"
    message += f"**Участник:** {display_name}\n"
    message += f"{arc_title}\n"
    message += f"**День:** {day_title}\n\n"

    await update.message.reply_text(message, parse_mode='Markdown')

    # ★ ИСПРАВЛЕНО: Получаем медиа-контент задания
    from database import get_assignment_media
    media_data = None

    try:
        media_data = get_assignment_media(assignment_id)
        print(f"🔍 Получены медиа для задания {assignment_id} в админке: {media_data}")
    except Exception as e:
        print(f"⚠️ Ошибка получения медиа в админке: {e}")
        media_data = {'photos': [], 'audios': [], 'video_url': None}

    if content_text:
        await send_long_message(update, content_text, "**Задание:**")

    # ★ ИСПРАВЛЕНО: Показываем медиа задания в админке
    # 1. Фото задания (если есть и не пустой список)
    if media_data and media_data.get('photos'):
        photos = media_data['photos']
        if isinstance(photos, list) and photos:
            for i, photo_id in enumerate(photos[:3], 1):
                try:
                    await update.message.reply_photo(
                        photo=photo_id,
                        caption=f"🖼️ Фото {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки фото {i} в админке: {e}")

    # 2. Аудио задания (если есть и не пустой список)
    if media_data and media_data.get('audios'):
        audios = media_data['audios']
        if isinstance(audios, list) and audios:
            for i, audio_id in enumerate(audios[:2], 1):
                try:
                    await update.message.reply_audio(
                        audio=audio_id,
                        caption=f"🎵 Аудио {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки аудио {i} в админке: {e}")

    # 3. Видео задания (если есть и не пустая ссылка)
    if media_data and media_data.get('video_url'):
        video_url = media_data['video_url']
        if video_url and video_url.strip():
            video_msg = "🎬 **Видео к заданию:**\n"
            video_msg += f"{video_url}"
            await update.message.reply_text(video_msg, parse_mode='Markdown')

    if answer_text:
        await send_long_message(update, answer_text, "**Ответ участника:**")
    
    if answer_files:
        try:
            files_list = json.loads(answer_files)
            for i, file_id in enumerate(files_list, 1):
                try:
                    await update.message.reply_photo(
                        photo=file_id,
                        caption=f"📎 Фото {i} от участника"
                    )
                except Exception as photo_error:
                    try:
                        await update.message.reply_document(
                            document=file_id,
                            caption=f"📎 Фото {i} от участника"
                        )
                    except Exception as doc_error:
                        print(f"🚨 Ошибка отправки файла: {doc_error}")
                        
        except Exception as e:
            print(f"🚨 Ошибка загрузки фото: {e}")

    if teacher_comment and teacher_comment.strip():
        message += f"💬 Комментарий психолога: {teacher_comment}\n\n"
    else:
        message += "💬 Комментарий психолога: не оставлен\n\n"
    
    keyboard = [
        ["🔙 Назад к заданиям"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    context.user_data['current_assignment_id'] = assignment_id

    view_mode = context.user_data.get('view_mode', 'new')
    print(f"🚨 [DEBUG] view_mode={view_mode}, status={status}")
    
    if view_mode == 'approved' or status == 'approved':
        # Для принятых заданий - не запрашиваем комментарий
        keyboard = [["🔙 Назад к заданиям"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "✅ **Задание уже принято.**\n\n"
            "Комментарий психолога был оставлен ранее.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return

    keyboard = [["🔙 Вернуться в меню проверки"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        "💬 **Оставьте обязательный комментарий к выполненному заданию:**",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    context.user_data['waiting_for_comment'] = True


async def finish_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает принятие задания с комментарием"""
    assignment_id = context.user_data.get('current_assignment_id')
    student_id = context.user_data.get('current_student_id')
    comment = context.user_data.get('current_comment', '')
    
    if not assignment_id or not student_id:
        await update.message.reply_text("❌ Ошибка: данные задания не найдены")
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE user_progress_advanced 
        SET status = 'approved', teacher_comment = ?
        WHERE assignment_id = ? AND user_id = ?
    ''', (comment, assignment_id, student_id))

    cursor.execute('''
        UPDATE user_progress_advanced 
        SET viewed_by_student = 0
        WHERE assignment_id = ? AND user_id = ?
    ''', (assignment_id, student_id))
    
    conn.commit()
    conn.close()
    
    context.user_data['waiting_for_comment'] = False
    context.user_data['current_comment'] = None
    context.user_data['current_assignment_id'] = None
    context.user_data['current_student_id'] = None
    
    await update.message.reply_text(
        "🎉 **Задание принято!**\n\n"
        f"💬 **Ваш комментарий:** {comment}\n\n"
        "Участник увидит ваш комментарий в разделе 'Ответ психолога'",
        parse_mode='Markdown'
    )
    
    await admin_panel(update, context)

async def submit_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    # Проверка доступности дня (оставляем как есть)
    day_id = context.user_data.get('current_day_id')
    if day_id:
        from database import is_day_available_for_user
        if not is_day_available_for_user(user_id, day_id):
            await update.message.reply_text(
                f"⏰ **Время выполнения истекло!**\n\n"
                "Этот день уже закрыт для выполнения заданий.\n"
                "Задания должны быть выполнены до установленного времени.\n\n"
                "Этот день будет отмечен как пропущенный.",
                parse_mode='Markdown'
            )
            from database import mark_day_as_skipped
            mark_day_as_skipped(user_id, day_id)
            return
    
    assignment_id = context.user_data.get('current_assignment_id')
    
    if not assignment_id:
        await update.message.reply_text("❌ Ошибка: задание не выбрано")
        return

    answer_type = context.user_data.get('answer_type', 'Фото_и_текст')
    answer_text = context.user_data.get('answer_text')
    answer_files = context.user_data.get('answer_files', [])
    questions = context.user_data.get('questions', [])
    
    # Проверки на наличие ответа (оставляем как есть)
    if answer_type == 'Только_фото':
        if not answer_files:
            await update.message.reply_text(
                "❌ **Нельзя отправить задание!**\n\n"
                "Вы выбрали вариант 'Только фото'.\n"
                "Пожалуйста, отправьте хотя бы одно фото.",
                parse_mode='Markdown'
            )
            return
    
    elif answer_type == 'Только_текст':
        if not answer_text:
            await update.message.reply_text(
                "❌ **Нельзя отправить задание!**\n\n"
                "Вы выбрали вариант 'Только текст'.\n"
                "Пожалуйста, напишите текстовый ответ.",
                parse_mode='Markdown'
            )
            return
    
    elif answer_type == 'Фото_и_текст':
        if not answer_text or not answer_files:
            await update.message.reply_text(
                "❌ **Нельзя отправить задание!**\n\n"
                "Для варианта 'Фото и текст' нужны:\n"
                "• Текстовый ответ\n"  
                "• Хотя бы одно фото\n\n"
                "Дополните ответ и попробуйте снова.",
                parse_mode='Markdown'
            )
            return
    
    # Формируем полный ответ с вопросами
    full_answer = answer_text or "Ответ не содержит текста."
    if questions:
        full_answer += "\n\nВопросы:\n" + "\n".join(f"- " + q for q in questions)
    
    # ⭐ ИЗМЕНЕНИЕ: сразу ставим статус 'approved' вместо 'submitted'
    from database import save_assignment_answer_with_day_auto_approve
    save_assignment_answer_with_day_auto_approve(
        user_id=user_id,
        assignment_id=assignment_id,
        day_id=day_id,
        answer_text=full_answer,
        answer_files=answer_files
    )
    
    # Очищаем данные
    context.user_data['answering'] = False
    context.user_data['answer_type'] = None
    context.user_data['answer_text'] = None
    context.user_data['answer_files'] = []
    context.user_data['questions'] = []
    
    # ⭐ ИЗМЕНЕНИЕ: сообщение об автоматическом принятии
    await update.message.reply_text(
        "🎉 **Задание принято автоматически!**\n\n"
        f"**Тип ответа:** {answer_type.replace('_', ' ').title()}\n"
        "✅ Ваш ответ сохранен и принят. У психолога есть возможность просмотреть все ваши ответы на задания.\n\n"
        "**📋 Задание завершено!**\n"
        "После завершения задания в него нельзя внести изменения.\n\n"
        "**💬 Если есть вопросы:**\n"
        "Вы можете проконсультироваться с психологом в разделе 'Личная консультация'.\n\n"
        "**📚 Чтобы посмотреть ваши ответы:**\n"
        "Перейдите в раздел 'Архив заданий' → 'Завершенные задания'",
        parse_mode='Markdown'
    )
    
    await my_assignments_menu(update, context)

async def show_approved_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['view_mode'] = 'approved'
    context.user_data['current_section'] = 'admin'
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Получаем участников с принятыми заданиями по частям
    cursor.execute('''
        SELECT DISTINCT 
            u.user_id, 
            COALESCE(u.fio, u.username, 'ID:' || u.user_id) as display_name,
            ar.title as part_title,
            ar.arc_id,
            COUNT(upa.assignment_id) as approved_count
        FROM users u
        JOIN user_progress_advanced upa ON u.user_id = upa.user_id
        JOIN assignments a ON upa.assignment_id = a.assignment_id
        JOIN days d ON a.day_id = d.day_id
        JOIN arcs ar ON d.arc_id = ar.arc_id
        WHERE upa.status = 'approved'
        GROUP BY u.user_id, ar.arc_id
        ORDER BY approved_count DESC
    ''')
    
    students_data = cursor.fetchall()
    conn.close()
    
    if not students_data:
        await update.message.reply_text("✅ Нет принятых заданий")
        return
    
    keyboard = []
    student_mapping_approved = {}  # Отдельный mapping для принятых
    
    for user_id, display_name, part_title, arc_id, approved_count in students_data:
        # Обрезаем длинные имена
        if len(display_name) > 20:
            display_name = display_name[:17] + "..."
        
        # Формат: 👤 Имя - Часть X (N принятых)
        btn_text = f"👤 {display_name} - {part_title} ({approved_count} принятых)"
        keyboard.append([btn_text])
        
        # Сохраняем mapping: кнопка → (user_id, arc_id)
        student_mapping_approved[btn_text] = {'user_id': user_id, 'arc_id': arc_id}
    
    # ★★ ВАЖНО: Сохраняем mapping в контекст
    context.user_data['student_mapping_approved'] = student_mapping_approved
    
    keyboard.append(["🔙 Назад к проверке"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "✅ **Принятые задания:**\n\n"
        "Выберите участника и марафон:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_student_part_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ВСЕ принятые задания участника в выбранной части"""
    
    print(f"🔍 [DEBUG] show_student_part_approved вызван")
    print(f"🔍 [DEBUG] context.user_data keys: {list(context.user_data.keys())}")
    print(f"🔍 [DEBUG] current_student_id: {context.user_data.get('current_student_id')}")
    print(f"🔍 [DEBUG] current_arc_id: {context.user_data.get('current_arc_id')}")
    
    student_id = context.user_data.get('current_student_id')
    arc_id = context.user_data.get('current_arc_id')
    
    if not student_id or not arc_id:
        print(f"❌ [DEBUG] Ошибка: нет student_id или arc_id в контексте")
        await update.message.reply_text("❌ Ошибка: участник или часть не выбраны")
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Получаем информацию о части
    cursor.execute('SELECT title FROM arcs WHERE arc_id = ?', (arc_id,))
    arc_result = cursor.fetchone()
    arc_title = arc_result[0] if arc_result else f"Часть {arc_id}"
    
    # Получаем информацию об участнике
    cursor.execute('SELECT fio, username FROM users WHERE user_id = ?', (student_id,))
    user_result = cursor.fetchone()
    display_name = user_result[0] if user_result and user_result[0] else user_result[1] if user_result else f"Участник {student_id}"
    
    # Получаем задания
    cursor.execute('''
        SELECT a.assignment_id, a.title, d.title as day_title,
               upa.submitted_at, upa.has_additional_comment, upa.additional_comment_viewed
        FROM assignments a
        JOIN days d ON a.day_id = d.day_id
        JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
        WHERE upa.user_id = ? AND d.arc_id = ? AND upa.status = 'approved'
        ORDER BY d.order_num, a.assignment_id
    ''', (student_id, arc_id))
    
    assignments = cursor.fetchall()
    conn.close()
    
    if not assignments:
        await update.message.reply_text(f"✅ У участника {display_name} нет принятых заданий в части '{arc_title}'")
        return
    
    # Формируем сообщение
    message = f"✅ **Принятые задания**\n\n"
    message += f"**👤 Участник:** {display_name}\n"
    message += f"**🏆 Часть:** {arc_title}\n"
    message += f"**📊 Найдено:** {len(assignments)} заданий\n\n"
    
    # Создаем клавиатуру
    keyboard = []
    context.user_data['assignment_mapping'] = {}
    
    for assignment_id, assignment_title, day_title, submitted_at, has_comment, comment_viewed in assignments[:15]:
        # ★★ ИСПРАВЛЕНИЕ: Формируем текст кнопки с полным названием
        if has_comment:
            status_icon = "💬✅" if comment_viewed == 0 else "💬✅"
        else:
            status_icon = "✅"
        
        # ★★ ВАЖНО: Используем полное название для кнопки
        # Формат: "✅ Полное название (День X)"
        btn_text = f"{status_icon} {assignment_title} ({day_title})"
        keyboard.append([btn_text])
        
        # Сохраняем mapping с полным названием
        context.user_data['assignment_mapping'][btn_text] = {
            'assignment_id': assignment_id,
            'assignment_title': assignment_title,  # ← Полное название
            'day_title': day_title,
            'student_id': student_id,
            'arc_id': arc_id
        }
    
    keyboard.append(["🔙 Назад к списку участников"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_assignment_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает принятое задание с комментарием психолога"""
    if context.user_data.get('view_mode') != 'approved':
        context.user_data['view_mode'] = 'approved'
        print(f"🚨 Исправлен view_mode на 'approved'")
    text = update.message.text
    assignment_title = text[2:].strip()
    
    student_id = context.user_data.get('current_student_id')
    day_title = context.user_data.get('current_day')
    
    if not day_title:
        await update.message.reply_text("❌ Ошибка: день не определен")
        return
    
    from database import get_day_id_by_title_and_arc
    arc_id = context.user_data.get('current_arc_id')
    day_id = get_day_id_by_title_and_arc(day_title, arc_id)
    
    if not day_id:
        await update.message.reply_text("❌ Ошибка: день не найден")
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''  
        SELECT a.assignment_id, a.content_text, 
               upa.answer_text, upa.answer_files, upa.teacher_comment,
               u.fio, u.username
        FROM assignments a
        JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
        JOIN users u ON upa.user_id = u.user_id
        WHERE a.title = ? AND upa.user_id = ? AND a.day_id = ? AND upa.status = 'approved'
    ''', (assignment_title, student_id, day_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text("❌ Задание не найдено")
        return
    
    assignment_id, content_text, answer_text, answer_files, teacher_comment, fio, username = result
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT d.title, ar.title 
        FROM days d
        JOIN arcs ar ON d.arc_id = ar.arc_id
        WHERE d.day_id = ?
    ''', (day_id,))
    day_info = cursor.fetchone()
    conn.close()
    
    day_title_display = day_info[0] if day_info else day_title
    arc_title = day_info[1] if day_info else "Неизвестно"
    
    display_name = fio if fio else username

    header = f"**✅ Принятое задание: {assignment_title}**\n\n"
    header += f"**Участник:** {display_name}\n"
    header += f" {arc_title}\n"
    header += f"**День:** {day_title_display}\n\n"
    await update.message.reply_text(header, parse_mode='Markdown')

    if content_text:
        await send_long_message(update, content_text, "**Задание:**")

    if answer_text:
        await send_long_message(update, answer_text, "**Ответ участника:**")

    if answer_files:
        try:
            files_list = json.loads(answer_files)
            for i, file_id in enumerate(files_list, 1):
                try:
                    await update.message.reply_photo(
                        photo=file_id,
                        caption=f"📎 Фото {i} от участника"
                    )
                except Exception as photo_error:
                    try:
                        await update.message.reply_document(
                            document=file_id,
                            caption=f"📎 Фото {i} от участника"
                        )
                    except Exception as doc_error:
                        print(f"🚨 Ошибка отправки файла: {doc_error}")
        except Exception as e:
            print(f"🚨 Ошибка загрузки фото: {e}")

    if teacher_comment:
        await send_long_message(update, teacher_comment, "💬 Комментарий психолога:")

    final = "✅ **Задание принято!**\n\n"

    keyboard = [
        ["🔙 Назад к заданиям"],
        ["🔙 В главное меню"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(final, reply_markup=reply_markup, parse_mode='Markdown')

async def show_approved_assignment_simple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает принятое задание (упрощенная версия для новой структуры)"""
    text = update.message.text
    
    print(f"🚨 [1] show_approved_assignment_simple: text='{text}'")
    
    # ★★ ИСПРАВЛЕНИЕ: Пробуем получить данные из контекста сначала
    assignment_id = context.user_data.get('current_assignment_id')
    assignment_title = context.user_data.get('current_assignment_title')
    day_title = context.user_data.get('current_day_title')
    
    if assignment_id and assignment_title and day_title:
        # Используем данные из контекста
        print(f"✅ Используем данные из контекста: id={assignment_id}, title='{assignment_title}', day='{day_title}'")
    else:
        # Старый способ: парсим из текста кнопки
        print(f"⚠️ Данных нет в контексте, парсим из текста: '{text}'")
        
        # Парсим кнопку "✅ Задание X (День Y)" или "💬✅ Задание X (День Y)"
        if text.startswith("✅ "):
            clean_text = text[2:].strip()  # Убираем "✅ "
        elif text.startswith("💬✅ "):
            clean_text = text[4:].strip()  # Убираем "💬✅ "
        else:
            clean_text = text.strip()
        
        # Извлекаем день из скобок
        day_title = None
        if "(" in clean_text and ")" in clean_text:
            import re
            match = re.search(r'\((.*?)\)', clean_text)
            if match:
                day_title = match.group(1).strip()
                assignment_title = clean_text.split("(")[0].strip()
        
        print(f"🚨 [2] assignment_title='{assignment_title}', day_title='{day_title}'")
    
    student_id = context.user_data.get('current_student_id')
    arc_id = context.user_data.get('current_arc_id')
    
    if not student_id or not arc_id:
        await update.message.reply_text("❌ Ошибка: данные не найдены")
        return
    
    # Если day_title есть, но не день - исправляем
    if day_title and not day_title.startswith("День"):
        # Пробуем найти день в названии задания
        if assignment_title and " - " in assignment_title:
            parts = assignment_title.split(" - ")
            if parts[0].startswith("День"):
                day_title = parts[0]
    
    # Получаем day_id
    from database import get_day_id_by_title_and_arc
    day_id = get_day_id_by_title_and_arc(day_title, arc_id)
    
    if not day_id:
        await update.message.reply_text(f"❌ День '{day_title}' не найден в части {arc_id}")
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Ищем задание
    cursor.execute('''  
        SELECT a.assignment_id, a.content_text, 
               upa.answer_text, upa.answer_files, upa.teacher_comment,
               u.fio, u.username
        FROM assignments a
        JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
        JOIN users u ON upa.user_id = u.user_id
        WHERE a.title = ? AND upa.user_id = ? AND a.day_id = ? AND upa.status = 'approved'
    ''', (assignment_title, student_id, day_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text("❌ Задание не найдено")
        return
    
    assignment_id, content_text, answer_text, answer_files, teacher_comment, fio, username = result

    # ★★ ВАЖНО: Сохраняем ID задания и студента в контекст
    context.user_data['current_assignment_id'] = assignment_id
    context.user_data['current_student_id'] = student_id
    context.user_data['current_assignment_title'] = assignment_title

    print(f"🔍 Сохранены в контекст: student_id={student_id}, assignment_id={assignment_id}, title={assignment_title}")
    
    # Формируем заголовок
    display_name = fio if fio else username
    header = f"**✅ Принятое задание: {assignment_title}**\n\n"
    header += f"**👤 Участник:** {display_name}\n"
    header += f"**📅 День:** {day_title}\n\n"
    
    # Отправляем заголовок
    await update.message.reply_text(header, parse_mode='Markdown')
    
    # 1. Отправляем текст задания (если есть)
    if content_text:
        await send_long_message(
            update, 
            content_text, 
            prefix="**📝 Задание:**",
            parse_mode='Markdown'
        )

    # ★★ ДОБАВИТЬ ЗДЕСЬ - показ медиа задания
    # Получаем медиа-контент задания
    from database import get_assignment_media
    media_data = get_assignment_media(assignment_id)

    # 1. Фото задания
    if media_data and media_data.get('photos'):
        photos = media_data['photos']
        if isinstance(photos, list) and photos:
            for i, photo_id in enumerate(photos[:5], 1):
                try:
                    await update.message.reply_photo(
                        photo=photo_id,
                        caption=f"🖼️ Фото {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки фото {i}: {e}")

    # 2. Аудио задания
    if media_data and media_data.get('audios'):
        audios = media_data['audios']
        if isinstance(audios, list) and audios:
            for i, audio_id in enumerate(audios[:3], 1):
                try:
                    await update.message.reply_audio(
                        audio=audio_id,
                        caption=f"🎵 Аудио {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки аудио {i}: {e}")

    # 3. Видео задания
    if media_data and media_data.get('video_url'):
        video_url = media_data['video_url']
        if video_url and video_url.strip():
            if 'youtube.com' in video_url or 'youtu.be' in video_url:
                await update.message.reply_text(f"🎬 Видео к заданию:\n{video_url}")
            elif video_url.startswith(('BAACAgI', 'CgACAgI', 'BAACAgQ', 'AgACAgI')):
                try:
                    await update.message.reply_video(
                        video=video_url,
                        caption="🎬 Видео к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки видео: {e}")
                    await update.message.reply_text("🎬 Видео к заданию")
            else:
                await update.message.reply_text(f"🎬 Видео к заданию:\n{video_url}")
    
    # 2. Отправляем ответ участника (если есть)
    if answer_text:
        await send_long_message(
            update,
            answer_text,
            prefix="**📋 Ответ участника:**",
            parse_mode='Markdown'
        )
    
    # 3. Отправляем комментарий психолога (если есть)
    if teacher_comment and teacher_comment.strip():
        await send_long_message(
            update,
            teacher_comment,
            prefix="💬 Системный комментарий:",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "**💬 Комментарий психолога:** не оставлен\n",
            parse_mode='Markdown'
        )
    
    # 4. Отправляем фото если есть
    if answer_files:
        try:
            files_list = json.loads(answer_files)
            for i, file_id in enumerate(files_list, 1):
                try:
                    await update.message.reply_photo(
                        photo=file_id,
                        caption=f"📎 Фото {i} от участника"
                    )
                except Exception as photo_error:
                    try:
                        await update.message.reply_document(
                            document=file_id,
                            caption=f"📎 Файл {i} от участника"
                        )
                    except Exception as doc_error:
                        print(f"🚨 Ошибка отправки файла {i}: {doc_error}")
        except Exception as e:
            print(f"🚨 Ошибка загрузки файлов: {e}")

    
    
    # ★★ ИЗМЕНЕНИЕ: Добавляем кнопку для комментария
    # Создаем клавиатуру
    keyboard = []

    # Проверяем, есть ли уже дополнительный комментарий
    from database import get_additional_comment_status
    comment_status = get_additional_comment_status(student_id, assignment_id)

    print(f"🔍 Статус комментария: has={comment_status['has_additional_comment']}, viewed={comment_status['is_viewed']}")

    # Всегда добавляем кнопку "🔙 Назад к списку участников" первой
    keyboard.append(["🔙 Назад к списку участников"])

    # Затем добавляем кнопку для комментария, если нужно
    if not comment_status['has_additional_comment']:
        # Если нет доп. комментария - показываем кнопку для добавления
        keyboard.append(["💬 Добавить комментарий"])
    else:
        # Если уже есть комментарий - показываем информацию
        if comment_status['is_viewed']:
            keyboard.append(["💬 Комментарий добавлен ✅"])
        else:
            keyboard.append(["💬 Комментарий добавлен 🟡"])

    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    # Формируем сообщение
    message = "✅ **Задание принято**"
    if comment_status['has_additional_comment']:
        if comment_status['is_viewed']:
            message += "\n\n💬 **Дополнительный комментарий уже добавлен и просмотрен участником**"
        else:
            message += "\n\n🟡 **Дополнительный комментарий добавлен (ждет просмотра участником)**"

    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_additional_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текст дополнительного комментария"""
    comment_text = update.message.text
    
    print(f"🔍 [HANDLE_COMMENT] Получен текст комментария: '{comment_text[:50]}...'")
    
    if comment_text == "🔙 Отменить":
        print("🔍 [HANDLE_COMMENT] Пользователь отменил добавление комментария")
        
        # Очищаем флаги
        context.user_data.pop('waiting_for_additional_comment', None)
        context.user_data.pop('comment_for_student_id', None)
        context.user_data.pop('comment_for_assignment_id', None)
        context.user_data.pop('comment_assignment_title', None)
        context.user_data.pop('comment_student_name', None)
        
        await update.message.reply_text(
            "❌ **Добавление комментария отменено.**\n\n"
            "Возвращаюсь к просмотру задания...",
            parse_mode='Markdown'
        )
        
        # Возвращаемся к просмотру задания
        if context.user_data.get('current_student_id') and context.user_data.get('current_assignment_id'):
            await show_approved_assignment_simple(update, context)
        return
    
    student_id = context.user_data.get('comment_for_student_id')
    assignment_id = context.user_data.get('comment_for_assignment_id')
    assignment_title = context.user_data.get('comment_assignment_title', 'Неизвестное задание')
    student_name = context.user_data.get('comment_student_name', f'Участник {student_id}')
    
    if not student_id or not assignment_id:
        print(f"❌ [HANDLE_COMMENT] Ошибка: нет student_id или assignment_id")
        await update.message.reply_text("❌ Ошибка: данные не найдены. Начните заново.")
        return
    
    # Проверяем минимальную длину комментария
    if len(comment_text.strip()) < 10:
        await update.message.reply_text(
            "❌ **Комментарий слишком короткий.**\n\n"
            "Пожалуйста, напишите комментарий минимум из 10 символов.\n"
            "Участнику важно получить содержательную обратную связь.",
            parse_mode='Markdown'
        )
        return
    
    # Проверяем максимальную длину
    if len(comment_text) > 4000:
        await update.message.reply_text(
            "❌ **Комментарий слишком длинный.**\n\n"
            "Пожалуйста, сократите комментарий до 4000 символов.\n"
            "Слишком длинные комментарии сложно воспринимать.",
            parse_mode='Markdown'
        )
        return
    
    print(f"✅ [HANDLE_COMMENT] Сохраняю комментарий для задания {assignment_id}")
    
    # Сохраняем комментарий
    from database import add_additional_comment_to_assignment
    success = add_additional_comment_to_assignment(student_id, assignment_id, comment_text)
    
    if success:
        print(f"✅ [HANDLE_COMMENT] Комментарий успешно сохранен")
        
        # Очищаем флаги
        context.user_data.pop('waiting_for_additional_comment', None)
        context.user_data.pop('comment_for_student_id', None)
        context.user_data.pop('comment_for_assignment_id', None)
        context.user_data.pop('comment_assignment_title', None)
        context.user_data.pop('comment_student_name', None)
        
        # Получаем информацию о части для уведомления
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('''
            SELECT ar.title 
            FROM assignments a
            JOIN days d ON a.day_id = d.day_id
            JOIN arcs ar ON d.arc_id = ar.arc_id
            WHERE a.assignment_id = ?
        ''', (assignment_id,))
        
        result = cursor.fetchone()
        arc_title = result[0] if result else "Неизвестная часть"
        conn.close()
        
        # Формируем сообщение об успехе
        success_message = (
            f"✅ **Комментарий успешно добавлен!**\n\n"
            f"**👤 Участник:** {student_name}\n"
            f"**🏆 Часть:** {arc_title}\n"
            f"**📝 Задание:** {assignment_title}\n\n"
            f"**💬 Ваш комментарий:**\n"
            f"{comment_text[:300]}{'...' if len(comment_text) > 300 else ''}\n\n"
            f"🟡 **Теперь задание появится у участника в разделе '🟡 Новые ответы'.**\n\n"
            f"📊 *Статистика комментария:*\n"
            f"• Сохранено: {datetime.now().strftime('%H:%M:%S')}"
        )
        
        keyboard = [["🔙 К списку заданий"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            success_message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # ★★ ВАЖНО: НЕ вызываем show_approved_assignment_simple снова
        # Пользователь сам вернется к заданию когда захочет
        
    else:
        print(f"❌ [HANDLE_COMMENT] Ошибка при сохранении комментария")
        await update.message.reply_text(
            "❌ **Ошибка при сохранении комментария.**\n\n"
            "Пожалуйста, попробуйте еще раз или обратитесь к разработчику.\n"
            f"Код ошибки: задание {assignment_id}, участник {student_id}",
            parse_mode='Markdown'
        )

async def add_comment_to_approved_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает добавление комментария к принятому заданию - УЛУЧШЕННАЯ ВЕРСИЯ"""
    user_id = update.message.from_user.id
    
    # Проверяем что это админ
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только администратор может добавлять комментарии")
        return
    
    print(f"🔍 [ADD_COMMENT] Кнопка нажата админом: {update.message.from_user.id}")
    print(f"🔍 [ADD_COMMENT] Текущий контекст: {context.user_data}")
    
    # Получаем данные из контекста
    student_id = context.user_data.get('current_student_id')
    assignment_id = context.user_data.get('current_assignment_id')
    
    if not student_id or not assignment_id:
        print(f"❌ [ADD_COMMENT] Ошибка: нет student_id или assignment_id в контексте")
        await update.message.reply_text("❌ Ошибка: задание не выбрано. Вернитесь к списку заданий и выберите задание снова.")
        return
    
    # Проверяем, есть ли уже комментарий
    from database import get_additional_comment_status
    comment_status = get_additional_comment_status(student_id, assignment_id)
    
    if comment_status['has_additional_comment']:
        print(f"⚠️ [ADD_COMMENT] К заданию {assignment_id} уже есть комментарий")
        await update.message.reply_text(
            "⚠️ **К этому заданию уже добавлен дополнительный комментарий.**\n\n"
            f"**Статус:** {'🟡 Ждет просмотра' if not comment_status['is_viewed'] else '✅ Просмотрено'}\n\n"
            f"**Комментарий:**\n{comment_status['comment_text'][:200]}...",
            parse_mode='Markdown'
        )
        
        # Возвращаем к просмотру задания
        await show_approved_assignment_simple(update, context)
        return
    
    # Получаем данные о задании для информации
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.title, u.fio, d.title as day_title, ar.title as arc_title
        FROM assignments a
        JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
        JOIN users u ON upa.user_id = u.user_id
        JOIN days d ON a.day_id = d.day_id
        JOIN arcs ar ON d.arc_id = ar.arc_id
        WHERE upa.user_id = ? AND upa.assignment_id = ?
    ''', (student_id, assignment_id))
    
    result = cursor.fetchone()
    conn.close()
    
    assignment_title = result[0] if result else "Неизвестное задание"
    student_name = result[1] if result and result[1] else f"Участник {student_id}"
    day_title = result[2] if result else "Неизвестный день"
    arc_title = result[3] if result else "Неизвестная часть"
    
    print(f"✅ [ADD_COMMENT] Данные задания: title='{assignment_title}', student='{student_name}', day='{day_title}'")
    
    # Устанавливаем флаг ожидания комментария
    context.user_data['waiting_for_additional_comment'] = True
    context.user_data['comment_for_student_id'] = student_id
    context.user_data['comment_for_assignment_id'] = assignment_id
    context.user_data['comment_assignment_title'] = assignment_title
    context.user_data['comment_student_name'] = student_name
    
    keyboard = [["🔙 Отменить"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"💬 **Добавление комментария к заданию**\n\n"
        f"**Участник:** {student_name}\n"
        f"**Задание:** {assignment_title}\n\n"
        f"✍️ **Напишите комментарий для участника:**\n"
        f"(Комментарий будет добавлен к автоматическому комментарию)",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_feedback_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_section'] = 'feedback'
    context.user_data['in_feedback_mode'] = True
    """Показывает задания с обратной связью, сгруппированные по разделам"""
    user_id = update.message.from_user.id
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT ar.arc_id, ar.title,
               COUNT(CASE WHEN upa.viewed_by_student = 0 THEN 1 END) as new_count,
               COUNT(*) as total_count
        FROM arcs ar
        JOIN days d ON ar.arc_id = d.arc_id
        JOIN assignments a ON d.day_id = a.day_id
        JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
        WHERE upa.user_id = ? AND upa.status = 'approved' AND upa.teacher_comment IS NOT NULL
        GROUP BY ar.arc_id
        ORDER BY ar.order_num
    ''', (user_id,))
    
    arcs = cursor.fetchall()
    conn.close()
    
    if not arcs:
        await update.message.reply_text("📝 Пока нет обратной связи по заданиям.")
        return
    
    keyboard = []
    total_new = 0
    
    for arc_id, arc_title, new_count, total_count in arcs:
        status_icon = "🟡" if new_count > 0 else "🔄"
        if new_count > 0:
            total_new += new_count
            
        btn_text = f"{status_icon} {arc_title} ({new_count}/{total_count})"
        keyboard.append([btn_text])
    
    keyboard.append(["🔙 Назад к заданиям"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    message = f"💬 **Обратная связь по заданиям**"
    if total_new > 0:
        message += f"\n\n🟡 **У вас {total_new} новых комментариев!**"
    
    message += "\n\nВыберите раздел:"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def request_personal_consultation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос личной консультации - обновленная"""
    # Получаем данные текущего задания
    feedback_data = context.user_data.get('current_feedback_data')
    
    if not feedback_data:
        # Попробуем получить из другого места
        assignment_title = context.user_data.get('current_feedback_assignment')
        if assignment_title:
            feedback_data = {
                'title': assignment_title,
                'day': context.user_data.get('current_feedback_day', 'Не указано')
            }
    
    keyboard = [
        [InlineKeyboardButton("💬 Написать психологу", url="https://t.me/Artem_Kasimov_psy")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = "👤 **Связь с психологом**\n\n"
    message += "Нажмите кнопку ниже чтобы написать Артему напрямую.\n\n"
    
    if feedback_data:
        message += f"📝 **Задание:** {feedback_data.get('title', 'Не указано')}\n"
        message += f"📅 **День:** {feedback_data.get('day', 'Не указано')}\n\n"
    
    message += "В сообщении укажите:\n"
    message += "1. Ваш вопрос по заданию\n"
    message += "2. Что именно непонятно\n"
    message += "3. Какую помощь требуется\n\n"
    message += "Психолог ответит в личных сообщениях."
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_fio_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['waiting_for_fio'] = True
    await update.message.reply_text("📝 Введите ваше ФИО:")

async def show_course_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детали тренинга и список частей"""
    course_title = update.message.text[2:].strip()
    context.user_data['current_course'] = course_title
    
    from database import get_course_arcs
    arcs = get_course_arcs(course_title)
    
    keyboard = []
    keyboard.append(["📖 О тренинге"])
    
    for arc_id, arc_title, is_available in arcs:
        status = "🔓" if is_available else "🔒"
        keyboard.append([f"{status} {arc_title}"])
    
    keyboard.append(["🔙 Назад в каталог"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"📚 **{course_title}**\n\n"
        "Выберите раздел для просмотра:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

def get_course_arcs(course_title):
    """Получает часть тренинга с проверкой доступности по датам - ИСПРАВЛЕННАЯ"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT arc_id, title, order_num, price, 
               дата_начала, дата_окончания, бесплатный_период, 
               status, is_available
        FROM arcs 
        WHERE course_id = (SELECT course_id FROM courses WHERE title = ?) 
        AND status = 'active'
        AND дата_начала IS NOT NULL 
        AND дата_окончания IS NOT NULL
        ORDER BY order_num
    ''', (course_title,))
    
    arcs = cursor.fetchall()
    conn.close()
    
    today = datetime.now().date()
    result = []
    
    for arc in arcs:
        arc_id, title, order_num, price, start_date_str, end_date_str, free_period, status, is_available = arc
        
        # Пропускаем если нет дат (уже отфильтровано, но на всякий случай)
        if not start_date_str or not end_date_str:
            print(f"⚠️ Пропущена часть '{title}' - отсутствуют даты")
            continue
            
        try:
            # Преобразуем строку в дату
            if isinstance(start_date_str, str):
                if ' ' in start_date_str:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d %H:%M:%S').date()
                else:
                    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            else:
                start_date = start_date_str
            
            if isinstance(end_date_str, str):
                if ' ' in end_date_str:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S').date()
                else:
                    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            else:
                end_date = end_date_str
            
            # Определяем статус
            if today < start_date:
                arc_status = 'future'
            elif start_date <= today <= end_date:
                arc_status = 'active'
            else:
                arc_status = 'past'
            
            result.append({
                'arc_id': arc_id,
                'title': title,
                'order_num': order_num,
                'price': price,
                'start_date': start_date_str,
                'end_date': end_date_str,
                'status': arc_status,
                'free_period': free_period,
                'is_available': is_available
            })
            
        except Exception as e:
            print(f"🚨 Ошибка обработки части '{title}': {e}")
            continue
    
    return result

async def show_about_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Страница 'Всё о тренинге' с подразделами и ссылкой на Телеграф"""
    
    message_text = """
Тренинг СЕБЯ ВЕРНИ СЕБЕ.

Тренинг имеет практическую направленность и предназначен для психологов,  для всех мастеров помогающих практик, для всех, кто связан в своей профессиональной деятельности с управлением человеческими ресурсами и для тех, кому интересна  осознанная глубокая трансформация личности. 

@SVS_365_bot

Основная идея тренинга:

Вернуть себя в сою жизнь, в полном объёме. Чувствовать, принимать, быть. Тренинг не про эффективность, и не про достижение высоких результатов, а про замедление, внимание, наслаждение своей истиной природой.  Тренинг знакомит и развивает навык владения таким инструментом как самонаблюдение, это базовый навык для всех трансформаций, развития качеств, и переработки опыта жизни. Как следствие, в результате развитого самонаблюдения возникают предпосылки практическому развитию личности.

Что такое практическое развитие личности, и для чего? 

Развить или вырастить личность значит возвыситься над персональной, трансгенеративной травмой, трансформировать, принять и переплавить свой опыт, не отторгая его.

Свойства развитой личности, рождённой как бы второй раз  через принятие и осознание себя, объективны, измеримы, наблюдаемы:

Позитивно-созидательное творчество, как способ мышления и действия, с развитой социальной адаптированностью. Проявление себя в своём творчестве для мира  легко и свободно.

Выход за пределы собственного прошлого опыта и социокультурных привычек. Развитая личность трансцендентна, деятельность направляется в непознанное, за пределы существующего опыта

Множественность без распада. Личность осознаёт свои различные качества и роли, сохраняя при этом целостность и неделимость, способна применять творчески все свои качества.

Ключевая механика тренинга в том, чтобы, с одной стороны, последовательно создавать новые поведенческие привычки, с другой стороны,  отслеживать и перерабатывать у себя негативные поведенческие программы. Основное действующее вещество тренинга, это твоё внимание. Твоё внимание, которое ты направляешь внутрь себя, изучая себя и знакомясь с собой, наблюдаешь за своим поведением, за своими реакциями, учишься узнавать свои чувства, свои эмоции. Каждый день понемногу знакомишься с собой и узнаёшь себя все больше и больше.

Суть тренинга очень проста: понимание себя и понимание того, что происходит в твоей жизни, это некая конструкция, которая сложилась в тебе в большей степени без твоего участия. Твоя задача, исследовать это и творчески переработать. Задумайся над вопросом: а можно ли не обижаться? а можно ли не испытывать разрушительный гнев? а можно ли перестать тревожится и  бояться? И ответ очень простой: конечно можно. 

Идея тренинга в том чтобы в безопасном и спокойном режиме переработать: негативные эмоции, негативные убеждения о себе и о мире, саморазрушительные поведенческие программы, через контакт с истинной природой себя. Условие при котором возможен контакт с своими частями: полное принятие своих результатов какими бы они не были, в поле любви и доверия внутри себя. 

Тренинг дистанционный, годовой, его веду я, Артём Касимов, практикующий психолог, действительный член ОППЛ. Эмоционально-образный терапевт. Организационный психолог, предприниматель. Мне помогает моя команда психологов, со-тренеров, сапортов, и техническая команда. Вы находитесь в постоянном контакте с вашим психологом  тренинга, который помогает вам усвоить материал, и готов дать необходимую профессиональную поддержку, при возникновении выраженных эмоциональных реакций, или сопротивления 

Каждая из восьми частей тренинга посвящена развитию одного навыка, который всесторонне интегрируется в повседневную жизнь, как привычка. Каждая часть связывается с последующей, составляя одну объёмную интегративную систему.

Каждая часть тренинга открывается семинаром,  по теме и материалам тренинга. Семинар можно посетить лично, приняв участие в оной из встреч которые организуются согласно расписанию, или присутствовать в формате видео связи (ссылки будут в группе тренинга СВС), или ознакомится с материалами семинаров самостоятельно, в группе тренинга:
"""

    inline_keyboard = [[
        InlineKeyboardButton("📄 Подробное описание тренинга", 
                           url="https://telegra.ph/Sebya-verni-sebe-12-17")
    ]]
    inline_markup = InlineKeyboardMarkup(inline_keyboard)

    keyboard = [
        ["📅 Расписание тренингов"],
        ["🗓 Расписание семинаров"],
        ["💬 Задать вопрос о тренинге"],
        ["🔙 Назад","🔙 В главное меню"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        message_text,
        reply_markup=inline_markup,
        parse_mode='Markdown'
    )
    
    await update.message.reply_text(
        "Выберите часть:",
        reply_markup=reply_markup
    )

async def show_course_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Страница 'Купить доступ' - показывает тренинг компании пользователя"""
    user_id = update.message.from_user.id
    
    # ★★★ ПРОВЕРЯЕМ КОМПАНИЮ ★★★
    from database import get_user_company, get_company_arc, check_user_arc_access
    
    user_company = get_user_company(user_id)
    
    if not user_company:
        keyboard = [["🔑 Ввести ключ компании"], ["🔙 В главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ **Вы не состоите в компании!**\n\n"
            "Для покупки доступа необходимо присоединиться к компании.\n\n"
            "1. Получите ключ компании у администратора\n"
            "2. Перейдите в 👤 Профиль → 🔑 Ввести ключ компании\n"
            "3. Введите полученный ключ",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # Получаем арку компании
    company_arc = get_company_arc(user_company['company_id'])
    
    if not company_arc:
        await update.message.reply_text(
            "❌ **У вашей компании нет активного тренинга!**\n\n"
            "Обратитесь к администратору компании.",
            parse_mode='Markdown'
        )
        return
    
    company_arc_id = company_arc['company_arc_id']
    
    # Проверяем есть ли уже доступ
    has_access = check_user_arc_access(user_id, company_arc_id)
    
    message = f"🏢 **Тренинг вашей компании**\n\n"
    message += f"**Название компании:** {user_company['name']}\n"
    message += f"**Старт тренинга:** {company_arc['actual_start_date']}\n"
    message += f"**Окончание:** {company_arc['actual_end_date']}\n"
    message += f"**Длительность:** 8 недель (56 дней)\n"
    message += f"**Цена доступа:** {user_company['price']}₽\n\n"
    
    keyboard = []
    
    if has_access:
        message += "✅ **У вас уже есть полный доступ к этому тренингу!**\n\n"
        message += "Перейдите в раздел '📚 Мои задания' чтобы начать обучение."
        
        keyboard.append(["📚 Мои задания"])
        keyboard.append(["📖 Всё о тренинге"])
        keyboard.append(["🔙 В главное меню"])
    else:
        # ★★★ РАСЧЕТ ДОСТУПНЫХ ВАРИАНТОВ ★★★
        from datetime import datetime
        
        today = datetime.now().date()
        start_date = datetime.strptime(company_arc['actual_start_date'], '%Y-%m-%d').date()
        days_since_start = (today - start_date).days
        
        message += "**Доступные варианты:**\n\n"
        
        # Пробный доступ доступен только в первые 10 дней
        if days_since_start <= 10 and days_since_start >= 0:
            message += "🎁 **Пробный доступ (3 дня)**\n"
            message += "• Доступ к первым 3 дням тренинга\n"
            message += "• Сопровождение психолога\n"
            message += "• Цена: 100₽\n\n"
            
            keyboard.append(["🎁 Пробный доступ(3 дня)"])
        
        message += "💰 **Полный доступ (56 дней)**\n"
        message += "• Полный доступ ко всему тренингу\n"
        message += "• Поддержка на протяжении 8 недель\n"
        message += f"• Цена: {user_company['price']}₽\n\n"
        
        keyboard.append(["💰 Купить полный доступ"])
        
        if days_since_start > 10:
            message += "⚠️ *Пробный доступ доступен только в первые 10 дней тренинга.*\n\n"
        
        message += "Выберите тип доступа:"
    
    keyboard.append(["🔙 Назад к тренингу"])
    
    # Сохраняем company_arc_id для функции покупки
    context.user_data['current_company_arc_id'] = company_arc_id
    context.user_data['current_company'] = user_company['name']
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def contact_psychologist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к психологу с inline-кнопкой"""
    keyboard = [
        [InlineKeyboardButton("💬 Написать психологу", url="https://t.me/Artem_Kasimov_psy")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👤 **Связь с психологом**\n\n"
        "Нажмите кнопку ниже чтобы написать Артему:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


def get_current_arc():
    """ОРИГИНАЛЬНАЯ версия с исправлением проблемы раздела 0"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        from datetime import datetime
        today = datetime.now().date().isoformat()
        print(f"🔍 Поиск текущей части на дату: {today}")
        
        # Ищем часть с датами, включающими сегодня
        cursor.execute('''
            SELECT arc_id, title 
            FROM arcs 
            WHERE arc_id > 0
            AND дата_начала IS NOT NULL 
            AND дата_начала != ''
            AND дата_окончания IS NOT NULL 
            AND дата_окончания != ''
            AND DATE(дата_начала) <= DATE(?)
            AND DATE(дата_окончания) >= DATE(?)
            ORDER BY arc_id
            LIMIT 1
        ''', (today, today))
        
        current = cursor.fetchone()
        
        if current:
            print(f"✅ Найдена текущая часть: {current[1]} (ID: {current[0]})")
        else:
            print(f"⚠️ Текущая часть не найдена для даты {today}")
            # Покажем какие части есть
            cursor.execute('''
                SELECT arc_id, title, дата_начала, дата_окончания 
                FROM arcs 
                WHERE arc_id > 0 
                AND дата_начала IS NOT NULL
                ORDER BY дата_начала
            ''')
            all_arcs = cursor.fetchall()
            
            print(f"📋 Все части в БД:")
            for arc in all_arcs:
                print(f"  • {arc[1]} (ID:{arc[0]}) - {arc[2]} / {arc[3]}")
        
        return current
    
    except Exception as e:
        print(f"🚨 Ошибка в get_current_arc: {e}")
        cursor.execute('SELECT arc_id, title FROM arcs WHERE arc_id = 1')
        return cursor.fetchone()
    finally:
        conn.close()

async def check_daily_openings(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет и открывает новые дни в 06:00 местного времени"""
    print("=" * 50)
    print("🕛 [JOB] Проверка открытия новых дней...")
    
    current_moscow = get_moscow_time()
    print(f"🕐 Текущее время МСК: {current_moscow}")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, username, timezone_offset, city 
        FROM users 
        WHERE timezone_offset IS NOT NULL
    ''')
    
    users = cursor.fetchall()
    print(f"👥 Найдено пользователей: {len(users)}")
    
    opened_days_count = 0
    
    for user_id, username, timezone_offset, city in users:
        try:
            user_local_time = get_moscow_time() + timedelta(hours=timezone_offset)
            user_hour = user_local_time.hour
            user_minute = user_local_time.minute
            
            if user_hour == 6 and user_minute <= 5:
                print(f"👤 {username or user_id}: Время для открытия нового дня!")
                
                cursor.execute('''
                    SELECT uaa.arc_id, a.title
                    FROM user_arc_access uaa
                    JOIN arcs a ON uaa.arc_id = a.arc_id
                    WHERE uaa.user_id = ? AND a.status = 'active'
                ''', (user_id,))
                
                user_arcs = cursor.fetchall()
                
                for arc_id, arc_title in user_arcs:
                    cursor.execute('''
                        SELECT purchased_at FROM user_arc_access 
                        WHERE user_id = ? AND arc_id = ?
                    ''', (user_id, arc_id))
                    
                    purchase_result = cursor.fetchone()
                    if not purchase_result:
                        continue
                    
                    purchase_date = datetime.fromisoformat(purchase_result[0]).date()
                    days_since_start = (user_local_time.date() - purchase_date).days + 1
                    
                    cursor.execute('''
                        SELECT day_id, title 
                        FROM days 
                        WHERE arc_id = ? AND order_num = ?
                    ''', (arc_id, days_since_start))
                    
                    day_to_open = cursor.fetchone()
                    
            
            else:
                if user_hour == 6:
                    print(f"   ⏳ {username}: уже после 06:{user_minute:02d}")
                else:
                    print(f"   ⏳ {username}: сейчас {user_hour}:{user_minute:02d}")
                
        except Exception as e:
            print(f"❌ Ошибка пользователя {user_id}: {e}")
    
    conn.close()
    
    print(f"📊 Итог: отправлено уведомлений - {opened_days_count}")
    print("=" * 50)

async def reload_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полная перезагрузка данных из Excel"""
    if update.message.from_user.id == ADMIN_ID:
        await update.message.reply_text("🔄 Начинаю ПОЛНУЮ перезагрузку из Excel...")
        
        from database import reload_full_from_excel
        success = reload_full_from_excel()
        
        if success:
            await update.message.reply_text(
                "✅ **ПОЛНАЯ ПЕРЕЗАГРУЗКА ЗАВЕРШЕНА!**\n\n"
                "Все данные тренингов обновлены из Excel файла.\n"
                "Пользователи и их прогресс сохранены.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Ошибка при перезагрузке")
    else:
        await update.message.reply_text("❌ Нет доступа")

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список частей для выбора статистики"""
    context.user_data['current_section'] = 'statistics_menu'
    user_id = update.message.from_user.id
    
    from database import get_user_active_arcs, get_current_arc_day
    
    # Получаем ВСЕ части пользователя (и активные, и завершенные)
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT DISTINCT a.arc_id, a.title, a.дата_начала, a.дата_окончания,
               CASE 
                   WHEN DATE('now') < a.дата_начала THEN 'future'
                   WHEN DATE('now') > a.дата_окончания THEN 'past' 
                   ELSE 'active'
               END as status
        FROM user_arc_access uaa
        JOIN arcs a ON uaa.arc_id = a.arc_id
        WHERE uaa.user_id = ?
        ORDER BY a.дата_начала DESC
    ''', (user_id,))
    
    user_arcs = cursor.fetchall()
    conn.close()
    
    if not user_arcs:
        await update.message.reply_text(
            "📊 **У вас пока нет доступа к частям тренинга.**\n\n"
            "Приобретите доступ в разделе 'Купить тренинг'.",
            parse_mode='Markdown'
        )
        return
    
    # Формируем клавиатуру
    keyboard = []
    
    for arc_id, arc_title, arc_start, arc_end, status in user_arcs:
        # Определяем эмодзи и текст для кнопки
        if status == 'active':
            emoji = "🔄"
            status_text = "идёт сейчас"
        elif status == 'future':
            emoji = "⏳"
            status_text = "начнётся"
        else:
            emoji = "✅"
            status_text = "завершена"
        
        # Форматируем дату начала
        if isinstance(arc_start, str):
            start_date = arc_start.split()[0] if ' ' in arc_start else arc_start
        else:
            start_date = str(arc_start)
        
        # Создаем текст кнопки
        btn_text = f"{emoji} {arc_title}"
        keyboard.append([btn_text])
        
        # Сохраняем mapping для обработки
        if 'statistics_arc_map' not in context.user_data:
            context.user_data['statistics_arc_map'] = {}
        
        context.user_data['statistics_arc_map'][btn_text] = {
            'arc_id': arc_id,
            'arc_title': arc_title,
            'status': status,
            'start_date': start_date
        }
    
    keyboard.append(["📚 Мои задания"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Формируем сообщение
    message = "📊 **МОЙ ПРОГРЕСС**\n\n"
    message += "Выберите марафон(дату) для просмотра статистики:\n\n"
    
    # Добавляем пояснение по статусам
    message += "**Обозначения:**\n"
    message += "• 🔄 - Часть идёт сейчас\n"
    message += "• ✅ - Часть завершена\n\n"
    
    # Краткая сводка по всем частям
    active_count = sum(1 for _, _, _, _, status in user_arcs if status == 'active')
    future_count = sum(1 for _, _, _, _, status in user_arcs if status == 'future')
    past_count = sum(1 for _, _, _, _, status in user_arcs if status == 'past')
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_arc_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику по выбранной части - ОБНОВЛЕННАЯ С ФИО И ТЕГОМ"""
    user_id = update.message.from_user.id
    text = update.message.text
    
    # Получаем ФИО и тег пользователя
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT fio, username 
        FROM users 
        WHERE user_id = ?
    ''', (user_id,))
    
    user_info = cursor.fetchone()
    conn.close()
    
    user_fio = user_info[0] if user_info and user_info[0] else "Не указано"
    user_username = f"@{user_info[1]}" if user_info and user_info[1] else "Нет тега"
    
    # Получаем данные о выбранной части
    arc_map = context.user_data.get('statistics_arc_map', {})
    arc_info = arc_map.get(text)
    
    if not arc_info:
        await update.message.reply_text("❌ Часть не найдена")
        return
    
    arc_id = arc_info['arc_id']
    arc_title = arc_info['arc_title']
    status = arc_info['status']
    start_date = arc_info['start_date']
    
    # ★★★ ДОБАВЛЯЕМ ФИО И ТЕГ В НАЧАЛО ★★★
    message = f"👤 **{user_fio}** {user_username}\n\n"
    message += f"📊 **Статистика по тренингу: {arc_title}**\n\n"
    
    # Определяем статус
    from datetime import datetime
    
    try:
        if isinstance(start_date, str):
            if ' ' in start_date:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S').date()
            else:
                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
        else:
            start_date_obj = start_date
        
        today = datetime.now().date()
        
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT дата_окончания FROM arcs WHERE arc_id = ?', (arc_id,))
        end_date_result = cursor.fetchone()
        conn.close()
        
        end_date_str = end_date_result[0] if end_date_result else None
        
        if end_date_str:
            if isinstance(end_date_str, str):
                if ' ' in end_date_str:
                    end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d %H:%M:%S').date()
                else:
                    end_date_obj = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            else:
                end_date_obj = end_date_str
            
            if today < start_date_obj:
                status = 'future'
            elif start_date_obj <= today <= end_date_obj:
                status = 'active'
            else:
                status = 'past'
        else:
            status = 'future'
            
    except Exception as e:
        print(f"🚨 Ошибка определения статуса части: {e}")
        status = arc_info.get('status', 'unknown')
    
    # Информация о статусе части
    if status == 'active':
        message += f"🔄 **Статус:** Часть идёт сейчас\n"
    
    stats = None
    try:
        from database import get_user_skip_statistics
        stats = get_user_skip_statistics(user_id, arc_id)
    except Exception as e:
        print(f"⚠️ Ошибка получения статистики: {e}")
        stats = {
            'total_days': 0,
            'completed_days': 0,
            'skipped_days': 0,
            'streak_days': 0,
            'completion_rate': 0,
            'completed_assignments': 0,
            'skipped_assignments': 0,
            'skipped_list': [],
            'skipped_days_list': []
        }
    
    # Получаем текущий день для активной части
    current_day_info = None
    if status == 'active':
        try:
            from database import get_current_arc_day
            current_day_info = get_current_arc_day(user_id, arc_id)
        except Exception as e:
            print(f"⚠️ Ошибка получения текущего дня: {e}")
            current_day_info = None
    
    # Информация о статусе части
    if status == 'active':
        if current_day_info and 'day_number' in current_day_info:
            message += f"**Текущий день:** {current_day_info['day_number']} из 56\n"
    elif status == 'future':
        message += f"**Статус:** Начнётся {start_date}\n"
    else:
        message += f"**Статус:** тренинг завершен\n"
    
    message += f"**Дата начала:** {start_date}\n\n"
    
    # Статистика выполнения
    if status in ['active', 'past'] and stats:
        completed_assignments = stats.get('completed_assignments', 0)
        skipped_assignments = stats.get('skipped_assignments', 0)
        skipped_list = stats.get('skipped_list', [])
        streak_days = stats.get('streak_days', 0)
        completion_rate = stats.get('completion_rate', 0)

        message += "**Статистика заданий:**\n"
        message += f"• **Всего:** 56 дней(3 задания в день) \n"
        message += f"• **Выполнено заданий:** {completed_assignments}\n"
        message += f"• Процент выполнения: {completion_rate}%\n"

        # Пропущенные задания
        if skipped_assignments > 0 and skipped_list:
            message += f"📋 **Пропущенные задания:**\n"
            for i, skipped in enumerate(skipped_list[:10], 1):
                assignment_name = skipped.get('assignment', f'Задание {i}')
                message += f"{assignment_name}\n"
            
            if skipped_assignments > 10:
                message += f"... и еще {skipped_assignments - 10} заданий\n"
        else:
            message += "**• Пропущенных заданий нет!**\n"
        
        if streak_days > 0:
            message += f"• Лучшая серия выполнения: {streak_days} дней подряд без пропусков\n"
        
        message += "\n"
        
        # Пропущенные дни
        skipped_days_list = stats.get('skipped_days_list', [])
        if skipped_days_list:
            message += "📋 **Пропущенные дни:**\n"
            for day_title in skipped_days_list[:5]:
                message += f"• {day_title}\n"
            if len(skipped_days_list) > 5:
                message += f"• ... и ещё {len(skipped_days_list) - 5} дней\n"
            message += "\n"
    
    # Дополнительная статистика
    if status in ['active', 'past']:
        conn = None
        try:
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    COUNT(DISTINCT a.assignment_id) as total_assignments,
                    SUM(CASE WHEN upa.status IN ('submitted', 'approved') THEN 1 ELSE 0 END) as completed_assignments,
                    SUM(CASE WHEN upa.status = 'submitted' THEN 1 ELSE 0 END) as in_progress_assignments,
                    SUM(CASE WHEN upa.status = 'approved' THEN 1 ELSE 0 END) as approved_assignments
                FROM assignments a
                JOIN days d ON a.day_id = d.day_id
                LEFT JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id AND upa.user_id = ?
                WHERE d.arc_id = ?
            ''', (user_id, arc_id))
            
            result = cursor.fetchone()
            
            if result:
                total_assignments, completed, in_progress, approved = result
                if total_assignments and total_assignments > 0:
                    message += "**Дополнительная статистика:**\n"
                    message += f"• Проверено: {approved or 0}\n\n"
                    
        except Exception as e:
            print(f"⚠️ Ошибка SQL запроса в статистике: {e}")
        finally:
            if conn:
                conn.close()

    
    # Клавиатура
    keyboard = [
        ["📊 К выбору части"],
        ["📚 Мои задания"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    try:
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    except Exception as e:
        print(f"🚨 Ошибка отправки сообщения со статистикой: {e}")
        safe_message = message.replace('*', '').replace('_', '')
        await update.message.reply_text(
            safe_message[:4000],
            reply_markup=reply_markup
        )

async def manage_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление доступом - список пользователей"""
    context.user_data['current_section'] = 'admin_access'
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT u.user_id, 
               COALESCE(u.fio, u.username, 'ID:' || u.user_id) as display_name,
               COUNT(uaa.arc_id) as arc_count
        FROM users u
        LEFT JOIN user_arc_access uaa ON u.user_id = uaa.user_id
        GROUP BY u.user_id
        ORDER BY 
            CASE WHEN u.fio IS NOT NULL THEN 1 ELSE 2 END,
            u.user_id
        LIMIT 50
    ''')
    
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("❌ Нет пользователей в системе")
        return
    
    keyboard = []
    for user_id, display_name, arc_count in users:
        if len(display_name) > 25:
            display_name = display_name[:22] + "..."
        
        btn_text = f"👤 {display_name} ({arc_count})"
        keyboard.append([btn_text])
        
        if 'access_user_map' not in context.user_data:
            context.user_data['access_user_map'] = {}
        context.user_data['access_user_map'][btn_text] = user_id
    
    keyboard.append(["🔙 В главное меню"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🔧 **Управление доступом**\n\n"
        "Выберите пользователя (число в скобках - кол-во доступов):",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_user_arcs_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает доступы пользователя с inline-кнопками И список пользователей"""
    user_text = update.message.text
    user_map = context.user_data.get('access_user_map', {})
    user_id = user_map.get(user_text)
    
    if not user_id:
        await update.message.reply_text("❌ Пользователь не найден")
        return
    
    context.user_data['current_access_user'] = user_id
    context.user_data['current_access_user_text'] = user_text
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT fio, username FROM users WHERE user_id = ?', (user_id,))
    user_info = cursor.fetchone()
    fio, username = user_info if user_info else (None, None)
    display_name = fio if fio else (username if username else f"ID: {user_id}")
    
    cursor.execute('''
        SELECT a.arc_id, a.title, 
               CASE WHEN uaa.user_id IS NOT NULL THEN 1 ELSE 0 END as has_access
        FROM arcs a
        LEFT JOIN user_arc_access uaa ON a.arc_id = uaa.arc_id AND uaa.user_id = ?
        WHERE a.arc_id > 0
        ORDER BY a.arc_id
    ''', (user_id,))
    
    arcs = cursor.fetchall()
    
    cursor.execute('''
        SELECT u.user_id, 
               COALESCE(u.fio, u.username, 'ID:' || u.user_id) as display_name,
               COUNT(uaa.arc_id) as arc_count
        FROM users u
        LEFT JOIN user_arc_access uaa ON u.user_id = uaa.user_id
        GROUP BY u.user_id
        ORDER BY 
            CASE WHEN u.fio IS NOT NULL THEN 1 ELSE 2 END,
            u.user_id
        LIMIT 20
    ''')
    
    users = cursor.fetchall()
    conn.close()
    
    inline_keyboard = []
    row = []
    
    for i, (arc_id, arc_title, has_access) in enumerate(arcs):
        emoji = "✅" if has_access else "❌"
        short_title = f"Часть {arc_id}"
        button_text = f"{emoji} {short_title}"
        callback_data = f"access_toggle_{user_id}_{arc_id}_{1 if has_access else 0}"
        
        row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        if len(row) == 4 or i == len(arcs) - 1:
            inline_keyboard.append(row)
            row = []
    
    inline_keyboard.append([
        InlineKeyboardButton("✅ Дать все доступы", callback_data=f"access_all_{user_id}_1"),
        InlineKeyboardButton("❌ Забрать все", callback_data=f"access_all_{user_id}_0")
    ])
    
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    reply_keyboard = []
    for u_id, u_name, u_arc_count in users:
        if len(u_name) > 25:
            u_name = u_name[:22] + "..."
        
        prefix = "👉 " if u_id == user_id else "👤 "
        btn_text = f"{prefix}{u_name} ({u_arc_count})"
        reply_keyboard.append([btn_text])
        
        if 'access_user_map' not in context.user_data:
            context.user_data['access_user_map'] = {}
        context.user_data['access_user_map'][btn_text] = u_id
    
    reply_keyboard.append(["🔙 В главное меню"])
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    total_arcs = len(arcs)
    accessed_arcs = sum(1 for _, _, has_access in arcs if has_access)
    
    message = f"🔧 **Управление доступом**\n\n"
    message += f"👉 **Текущий пользователь:** {escape_markdown(display_name, version=2)}\n"
    message += f"📊 Доступов: {accessed_arcs}/{total_arcs}\n\n"
    message += "**Быстрое управление разделами:**\n"
    message += "• Нажмите на кнопку части тренинга чтобы переключить доступ ✅/❌\n"
    message += "• '✅ Дать все' - доступ ко всем частям тренинга\n"
    message += "• '❌ Забрать все' - удалить все доступы\n\n"
    message += "**Выберите другого пользователя из списка ниже:**"
    
    await update.message.reply_text(
        message,
        reply_markup=inline_markup,
        parse_mode='Markdown'
    )
    
    await update.message.reply_text(
        "👥 **Список пользователей:**\n"
        "(👉 - текущий выбранный)",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def handle_access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия inline-кнопок управления доступом"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("access_toggle_"):
        parts = data.split("_")
        user_id = int(parts[2])
        arc_id = int(parts[3])
        current_status = int(parts[4])
        
        from database import grant_arc_access
        
        if current_status == 1:
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM user_arc_access WHERE user_id = ? AND arc_id = ?', 
                          (user_id, arc_id))
            conn.commit()
            conn.close()
            new_status = 0
            action = "удален"
        else:
            grant_arc_access(user_id, arc_id, 'manual')
            new_status = 1
            action = "добавлен"
        
        await show_user_arcs_access_callback(query, context, user_id)
        await query.message.reply_text(f"✅ Доступ к части тренинга {arc_id} {action}!")
        return
    
    if data.startswith("access_all_"):
        parts = data.split("_")
        user_id = int(parts[2])
        action = int(parts[3])
        
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        if action == 1:
            cursor.execute('SELECT arc_id FROM arcs WHERE arc_id > 0')
            arcs = cursor.fetchall()
            
            for (arc_id,) in arcs:
                cursor.execute('''
                    INSERT OR IGNORE INTO user_arc_access (user_id, arc_id, access_type)
                    VALUES (?, ?, 'manual')
                ''', (user_id, arc_id))
            
            conn.commit()
            await query.message.reply_text("✅ Выдан доступ ко всем частям тренинга!")
        else:
            cursor.execute('DELETE FROM user_arc_access WHERE user_id = ?', (user_id,))
            conn.commit()
            await query.message.reply_text("❌ Все доступы удалены!")
        
        conn.close()
        
        await show_user_arcs_access_callback(query, context, user_id)
        return

async def show_user_arcs_access_callback(query, context, user_id):
    """Обновляет сообщение с inline-клавиатурой"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT fio, username FROM users WHERE user_id = ?', (user_id,))
    user_info = cursor.fetchone()
    fio, username = user_info if user_info else (None, None)
    display_name = fio if fio else (username if username else f"ID: {user_id}")
    
    cursor.execute('''
        SELECT a.arc_id, a.title, 
               CASE WHEN uaa.user_id IS NOT NULL THEN 1 ELSE 0 END as has_access
        FROM arcs a
        LEFT JOIN user_arc_access uaa ON a.arc_id = uaa.arc_id AND uaa.user_id = ?
        WHERE a.arc_id > 0
        ORDER BY a.arc_id
    ''', (user_id,))
    
    arcs = cursor.fetchall()
    conn.close()
    
    keyboard = []
    row = []
    
    for i, (arc_id, arc_title, has_access) in enumerate(arcs):
        emoji = "✅" if has_access else "❌"
        short_title = f"Д{arc_id}"
        button_text = f"{emoji} {short_title}"
        callback_data = f"access_toggle_{user_id}_{arc_id}_{1 if has_access else 0}"
        
        row.append(InlineKeyboardButton(button_text, callback_data=callback_data))
        
        if len(row) == 4 or i == len(arcs) - 1:
            keyboard.append(row)
            row = []
    
    keyboard.append([
        InlineKeyboardButton("✅ Дать все доступы", callback_data=f"access_all_{user_id}_1"),
        InlineKeyboardButton("❌ Забрать все", callback_data=f"access_all_{user_id}_0")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    total_arcs = len(arcs)
    accessed_arcs = sum(1 for _, _, has_access in arcs if has_access)
    
    message = f"🔧 **Управление доступом**\n\n"
    message += f"👤 **Пользователь:** {display_name}\n"
    message += f"📊 Доступов: {accessed_arcs}/{total_arcs}\n\n"
    message += "**Быстрое управление:**\n"
    message += "• Нажмите на кнопку раздела чтобы переключить доступ ✅/❌\n"
    message += "• '✅ Дать все' - доступ ко всем разделам\n"
    message += "• '❌ Забрать все' - удалить все доступы\n\n"
    message += f"✅ - доступ есть\n❌ - доступа нет"
    
    await query.edit_message_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_users_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список участников для просмотра статистики (админ) - ИСПРАВЛЕННАЯ"""
    context.user_data['current_section'] = 'admin_stats'
    
    # ★★★ ОЧИЩАЕМ СТАРЫЕ ДАННЫЕ ★★★
    for key in ['admin_current_user', 'admin_user_arcs_map', 'admin_current_arc_stats']:
        if key in context.user_data:
            del context.user_data[key]
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Получаем всех пользователей с ФИО или username
    cursor.execute('''
        SELECT u.user_id, 
               COALESCE(u.fio, u.first_name, u.username, 'ID:' || u.user_id) as display_name,
               COUNT(DISTINCT uaa.arc_id) + COUNT(DISTINCT uaa.company_arc_id) as arc_count
        FROM users u
        LEFT JOIN user_arc_access uaa ON u.user_id = uaa.user_id
        GROUP BY u.user_id
        ORDER BY 
            CASE WHEN u.fio IS NOT NULL THEN 1 
                 WHEN u.first_name IS NOT NULL THEN 2
                 ELSE 3 END,
            display_name
        LIMIT 50
    ''')
    
    users = cursor.fetchall()
    conn.close()
    
    if not users:
        await update.message.reply_text("❌ Нет пользователей в системе")
        return
    
    keyboard = []
    user_mapping = {}
    
    for user_id, display_name, arc_count in users:
        # Обрезаем длинные имена
        if len(display_name) > 25:
            display_name = display_name[:22] + "..."
        
        # Определяем цвет по активности
        conn2 = sqlite3.connect('mentor_bot.db')
        cursor2 = conn2.cursor()
        cursor2.execute('''
            SELECT COUNT(*) FROM user_progress_advanced 
            WHERE user_id = ? AND status IN ('submitted', 'approved')
        ''', (user_id,))
        
        activity_count = cursor2.fetchone()[0]
        conn2.close()
        
        # Цвета по активности
        if activity_count == 0:
            emoji = "🔴"  # Нет активности
        elif activity_count < 5:
            emoji = "🟠"  # Мало активности
        elif activity_count < 20:
            emoji = "🟡"  # Средняя активность
        else:
            emoji = "🟢"  # Высокая активность
        
        btn_text = f"{emoji} {display_name} ({arc_count})"
        keyboard.append([btn_text])
        
        user_mapping[btn_text] = {
            'user_id': user_id,
            'display_name': display_name,
            'arc_count': arc_count,
            'activity_count': activity_count
        }
    
    keyboard.append(["🔙 Назад к проверке"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Сохраняем mapping под правильным ключом
    context.user_data['admin_stats_users'] = user_mapping
    
    # Пояснение по цветам
    message = "📊 **Статистика участников (админ)**\n\n"
    message += "**Цвета по активности:**\n"
    message += "• 🟢 Высокая активность (20+ заданий)\n"
    message += "• 🟡 Средняя активность (5-19 заданий)\n"
    message += "• 🟠 Низкая активность (1-4 заданий)\n"
    message += "• 🔴 Нет активности\n\n"
    message += "**Число в скобках** - количество частей/компаний\n"
    message += "**Пример:** (2) = доступ к 2 частям или компаниям\n\n"
    message += "**Выберите участника:**"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_admin_arc_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную статистику пользователя по выбранной части (админ) - ИСПРАВЛЕННАЯ"""
    user_id = update.message.from_user.id
    text = update.message.text
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    print(f"🔍 DEBUG show_admin_arc_statistics: text='{text}'")
    
    # Получаем mapping
    user_arcs_map = context.user_data.get('admin_user_arcs_map', {})
    
    if text not in user_arcs_map:
        # Ищем частичное совпадение
        found = False
        for key, value in user_arcs_map.items():
            if text.strip() == key.strip():
                user_arcs_map[text] = value  # Обновляем ключ
                found = True
                break
        
        if not found:
            await update.message.reply_text("❌ Часть не найдена")
            return
    
    arc_info = user_arcs_map[text]
    target_user_id = arc_info['target_user_id']
    arc_id = arc_info['arc_id']
    arc_title = arc_info['arc_title']
    arc_type = arc_info['arc_type']
    access_type = arc_info['access_type']
    
    print(f"🔍 DEBUG: Статистика для user={target_user_id}, arc={arc_id}, type={arc_type}, access={access_type}")
    
    # ★★★ ВСЕГДА ИСПОЛЬЗУЕМ СТАНДАРТНОЕ НАЗВАНИЕ ТРЕНИНГА ★★★
    display_title = "Регулярный менеджмент(8 недель)"
    
    # Получаем информацию о пользователе
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT fio FROM users WHERE user_id = ?', (target_user_id,))
    user_data = cursor.fetchone()
    user_fio = user_data[0] if user_data and user_data[0] else f"Участник {target_user_id}"
    
    # Получаем компанию пользователя (для отображения в деталях)
    cursor.execute('''
        SELECT c.name, c.start_date 
        FROM user_companies uc
        JOIN companies c ON uc.company_id = c.company_id
        WHERE uc.user_id = ? AND uc.is_active = 1
    ''', (target_user_id,))
    
    company_data = cursor.fetchone()
    company_name = company_data[0] if company_data else "Неизвестно"
    company_start_date = company_data[1] if company_data else None
    
    conn.close()
    
    # ★★★ ПОЛУЧАЕМ СТАТИСТИКУ В ЗАВИСИМОСТИ ОТ ТИПА ДОСТУПА ★★★
    from database import get_user_skip_statistics
    
    if arc_type == 'company':
        # Для компании используем company_arc_id
        stats = get_user_skip_statistics(target_user_id, arc_id)
    else:
        # Для обычной дуги используем arc_id
        # Конвертируем в company_arc_id если нужно
        # Ищем company_arc_id для этой дуги
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT ca.company_arc_id 
            FROM company_arcs ca
            JOIN user_companies uc ON ca.company_id = uc.company_id
            WHERE uc.user_id = ? AND uc.is_active = 1 AND ca.arc_id = ?
        ''', (target_user_id, arc_id))
        
        company_arc = cursor.fetchone()
        conn.close()
        
        if company_arc:
            company_arc_id = company_arc[0]
            stats = get_user_skip_statistics(target_user_id, company_arc_id)
        else:
            # Используем общую статистику
            stats = {'error': 'Не найдена арка компании'}
    
    # Формируем сообщение
    message = f"👤 **{user_fio}**\n\n"
    
    if 'error' in stats:
        message += f"📚 **{display_title}**\n\n"
        message += f"🏢 **Компания:** {company_name}\n"
        if company_start_date:
            message += f"📅 **Дата начала:** {company_start_date}\n"
        message += f"\n⚠️ **Ошибка получения статистики:** {stats['error']}"
    else:
        message += f"📚 **{display_title}**\n\n"
        
        if company_name and company_name != "Неизвестно":
            message += f"🏢 **Компания:** {company_name}\n"
        
        if stats.get('actual_start_date'):
            message += f"📅 **Дата начала:** {stats['actual_start_date']}\n"
        elif stats.get('start_date'):
            message += f"📅 **Дата начала:** {stats['start_date']}\n"
        
        # Рассчитываем количество дней участия
        if stats.get('start_date') and stats.get('current_day'):
            message += f"📆 **Участвовал в тренинге:** {min(stats['current_day'], 56)} дней\n\n"
        else:
            message += f"📆 **Участвовал в тренинге:** {stats.get('current_day', 1)} дней\n\n"
        
        message += f"📊 **Выполнено заданий:** {stats.get('completed_assignments', 0)} из {stats.get('total_assignments', 168)}\n"
        
        # Рассчитываем корректный процент
        if stats.get('total_assignments', 0) > 0:
            completion_rate = round((stats.get('completed_assignments', 0) / stats.get('total_assignments')) * 100)
        else:
            completion_rate = 0
        
        message += f"📈 **Прогресс:** {completion_rate}%\n"
        
        if stats.get('submitted_assignments', 0) > 0:
            message += f"🟡 **На проверке:** {stats.get('submitted_assignments', 0)}\n"
        
        message += f"❌ **Пропущено:** {stats.get('skipped_assignments', 0)}\n"
        message += f"🔥 **Серия без пропусков:** {stats.get('streak_days', 0)} дней\n"
        
        if stats.get('current_day'):
            message += f"📅 **Текущий день тренинга:** {stats.get('current_day')} из 56\n"
        
        # Показываем тип доступа
        if access_type == 'trial':
            message += f"🎁 **Тип доступа:** Пробный (3 дня)\n"
        else:
            message += f"💰 **Тип доступа:** Полный (56 дней)\n"
        
        # Показываем последние пропущенные задания
        if stats.get('skipped_list') and len(stats['skipped_list']) > 0:
            message += f"\n📋 **Последние пропущенные задания:**\n"
            for i, skipped in enumerate(stats['skipped_list'][:5], 1):
                day_display = skipped.get('day', f"День {skipped.get('day_number', '?')}")
                assignment = skipped.get('assignment', 'Неизвестно')
                message += f"{i}. {day_display}: {assignment}\n"
    
    # Создаем клавиатуру
    keyboard = [
        ["📊 Посмотреть другой марафон этого участника"],
        ["👤 Выбрать другого участника"],
        ["👨‍🏫 Проверка заданий"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_admin_user_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора части для просмотра статистики пользователя (админ) - БЕЗ ДУБЛИКАТОВ"""
    user_id = update.message.from_user.id
    text = update.message.text
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Доступ запрещен")
        return
    
    print(f"🔍 DEBUG show_admin_user_statistics: text='{text}'")
    
    # Получаем пользователя из mapping
    users_map = context.user_data.get('admin_stats_users', {})
    user_info = users_map.get(text)
    
    if not user_info:
        # Ищем частичное совпадение
        for key, value in users_map.items():
            if text.strip() == key.strip():
                user_info = value
                break
        
        if not user_info:
            await update.message.reply_text("❌ Пользователь не найден")
            return
    
    target_user_id = user_info.get('user_id')
    display_name = user_info.get('display_name', f"Участник {target_user_id}")
    
    print(f"🔍 DEBUG: Найден пользователь: ID={target_user_id}, Name={display_name}")
    
    # Сохраняем данные пользователя
    context.user_data['admin_current_user'] = {
        'user_id': target_user_id,
        'display_name': display_name
    }
    
    # Получаем список частей пользователя (используем исправленную функцию)
    from database import get_user_active_arcs
    
    try:
        user_arcs = get_user_active_arcs(target_user_id)
        print(f"🔍 DEBUG: Получено уникальных частей для пользователя {target_user_id}: {len(user_arcs)}")
        
        if not user_arcs:
            await update.message.reply_text(
                f"👤 **{display_name}**\n\n"
                "❌ У участника нет активных частей тренинга.",
                parse_mode='Markdown'
            )
            await show_users_stats(update, context)
            return
        
        # ★★★ ДОПОЛНИТЕЛЬНАЯ ФИЛЬТРАЦИЯ НА УРОВНЕ ИНТЕРФЕЙСА ★★★
        unique_arcs_map = {}  # Для фильтрации дубликатов
        filtered_arcs = []
        
        for arc in user_arcs:
            arc_id, arc_title, start_date, end_date, access_type, arc_type = arc
            
            # Создаем уникальный ключ для фильтрации
            if arc_type == 'company':
                # Для компаний фильтруем по названию
                key = f"company_{arc_title}"
            else:
                # Для обычных частей по ID
                key = f"arc_{arc_id}"
            
            if key not in unique_arcs_map:
                unique_arcs_map[key] = True
                filtered_arcs.append(arc)
            else:
                print(f"⚠️  Пропущен интерфейсный дубликат: {arc_title}")
        
        user_arcs = filtered_arcs
        print(f"🔍 DEBUG: После интерфейсной фильтрации: {len(user_arcs)} частей")
        
        # Создаем mapping для частей
        admin_user_arcs_map = {}
        keyboard = []
        
        for arc in user_arcs:
            arc_id, arc_title, start_date, end_date, access_type, arc_type = arc
            
            # Определяем статус
            status = 'unknown'
            try:
                from datetime import datetime
                
                if start_date:
                    if isinstance(start_date, str):
                        try:
                            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d %H:%M:%S').date()
                        except ValueError:
                            try:
                                start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
                            except ValueError:
                                start_date_obj = datetime.now().date()
                    else:
                        start_date_obj = start_date
                        if hasattr(start_date_obj, 'date'):
                            start_date_obj = start_date_obj.date()
                    
                    today = datetime.now().date()
                    
                    if today < start_date_obj:
                        status = 'future'
                    elif arc_type == 'company' and end_date:
                        if isinstance(end_date, str):
                            try:
                                end_date_obj = datetime.strptime(end_date, '%Y-%m-%d %H:%M:%S').date()
                            except ValueError:
                                try:
                                    end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
                                except ValueError:
                                    end_date_obj = today + timedelta(days=56)
                        else:
                            end_date_obj = end_date
                            if hasattr(end_date_obj, 'date'):
                                end_date_obj = end_date_obj.date()
                        
                        if start_date_obj <= today <= end_date_obj:
                            status = 'active'
                        elif today > end_date_obj:
                            status = 'past'
                        else:
                            status = 'active'
                    else:
                        status = 'active'
            except Exception as e:
                print(f"⚠️ Ошибка определения статуса: {e}")
                status = 'active'
            
            # Создаем текст кнопки
            status_emoji = {
                'active': '🔄',
                'future': '⏳',
                'past': '✅',
                'unknown': '❓'
            }.get(status, '❓')
            
            # ★★★ УЛУЧШЕННОЕ ФОРМАТИРОВАНИЕ НАЗВАНИЯ ★★★
            if arc_type == 'company':
                # Для компаний добавляем тип доступа
                if access_type == 'trial':
                    access_emoji = '🎁'
                else:
                    access_emoji = '💰'
                
                btn_text = f"{status_emoji}{access_emoji} {arc_title}"
            else:
                # Для стандартных частей
                btn_text = f"{status_emoji} {arc_title}"
            
            # Обрезаем длинные названия
            if len(btn_text) > 40:
                btn_text = btn_text[:37] + "..."
            
            keyboard.append([btn_text])
            
            # Сохраняем информацию
            admin_user_arcs_map[btn_text] = {
                'arc_id': arc_id,
                'arc_title': arc_title,
                'status': status,
                'start_date': start_date,
                'end_date': end_date,
                'access_type': access_type,
                'arc_type': arc_type,
                'target_user_id': target_user_id
            }
        
        # Сохраняем mapping
        context.user_data['admin_user_arcs_map'] = admin_user_arcs_map
        
        keyboard.append(["👤 Выбрать другого участника"])
        keyboard.append(["👨‍🏫 Проверка заданий"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        # Получаем информацию о пользователе
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT fio, username, phone, city, created_at 
            FROM users 
            WHERE user_id = ?
        ''', (target_user_id,))
        
        user_data = cursor.fetchone()
        conn.close()
        
        user_fio = user_data[0] if user_data and user_data[0] else "Не указано"
        user_username = f"@{user_data[1]}" if user_data and user_data[1] else "Нет тега"
        user_phone = user_data[2] if user_data and user_data[2] else "Не указан"
        user_city = user_data[3] if user_data and user_data[3] else "Не выбран"
        user_created = user_data[4] if user_data and user_data[4] else "Неизвестно"
        
        # Получаем компанию пользователя
        from database import get_user_company
        user_company = get_user_company(target_user_id)
        
        message = f"👤 **Информация об участнике**\n\n"
        message += f"**ФИО:** {user_fio}\n"
        message += f"**Телеграм:** {user_username}\n"
        message += f"**Телефон:** {user_phone}\n"
        message += f"**Город:** {user_city}\n"
        message += f"**Зарегистрирован:** {user_created}\n"
        message += f"**Активных частей:** {len(user_arcs)}\n\n"
        
        if user_company:
            message += f"🏢 **Компания:** {user_company['name']}\n"
            message += f"📅 **Старт тренинга:** {user_company['start_date']}\n"
            message += f"💰 **Цена доступа:** {user_company['price']}₽\n\n"
        
        message += f"📊 **Выберите часть для просмотра статистики:**\n\n"
        message += f"🔄 - активная часть\n"
        message += f"⏳ - будущая часть\n"
        message += f"✅ - завершенная часть\n"
        
        if any(arc[4] == 'trial' for arc in user_arcs):
            message += f"🎁 - пробный доступ\n"
        if any(arc[4] == 'paid' for arc in user_arcs):
            message += f"💰 - полный доступ"
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode=None
        )
        
    except Exception as e:
        print(f"🚨 Ошибка в show_admin_user_statistics: {e}")
        import traceback
        traceback.print_exc()
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")




# В функции has_any_access:
def has_any_access(user_id):
    """Проверяет есть ли у пользователя доступ к любому тренингу компании"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # ★★ ИСПОЛЬЗУЕМ user_arc_access (не user_company_access!) ★★
        cursor.execute('SELECT 1 FROM user_arc_access WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result is not None
    except:
        return False
    finally:
        conn.close()

async def go_to_community(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет inline-кнопку для перехода в сообщество"""
    GROUP_LINK = "https://t.me/+khUT5h-XYMFkMDJi"
    
    keyboard = [[InlineKeyboardButton("👥 Перейти в закрытое сообщество", url=GROUP_LINK)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Нажмите кнопку ниже чтобы перейти в закрытое сообщество:",
        reply_markup=reply_markup
    )

async def show_offer_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает оферту регистрации с inline-кнопкой"""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    message_text = """📋 **СОГЛАШЕНИЕ С ОФЕРТОЙ (РЕГИСТРАЦИЯ)**

Политика в отношении обработки персональных данных

(политика конфиденциальности)

1. Общие положения

1.1. Настоящая политика обработки персональных данных составлена в соответствии с требованиями Федерального закона от 27.07.2006. №152-ФЗ «О персональных данных» и определяет порядок обработки персональных данных и меры по обеспечению безопасности персональных данных ИП Касимовым Артемом Равкатовичем (ИНН 661213624458, далее – Оператор).

*Полный текст оферты доступен по ссылке ниже.*"""
    
    inline_keyboard = [[
        InlineKeyboardButton("📄 Читать полную оферту",
                           url="https://telegra.ph/Politika-konfidencialnosti-12-15-55")
    ]]
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    reply_keyboard = [
        ["✅ Принять оферту"],
        ["❌ Отказаться"]
    ]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message_text,
        reply_markup=inline_markup,
        parse_mode='Markdown'
    )
    
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=reply_markup
    )
    
    context.user_data['showing_offer'] = True

async def accept_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает принятие оферты - с ReplyKeyboardRemove"""
    user_id = update.message.from_user.id
    
    from database import get_user_offer_status, accept_offer
    offer_status = get_user_offer_status(user_id)
    
    if offer_status['accepted_offer']:
        await update.message.reply_text(
            "✅ Вы уже приняли оферту ранее.",
            reply_markup=ReplyKeyboardRemove(),  # ← Удаляет клавиатуру
            parse_mode='Markdown'
        )
        return
    
    # Сохраняем
    #accept_offer(user_id, phone=None, fio=None)
    
    # УБИРАЕМ клавиатуру и просим телефон
    await update.message.reply_text(
        "✅ **Оферта принята!**\n\n"
        "📱 **Введите номер телефона:** в формате +7 или 8",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode='Markdown'
    )
    
    context.user_data['waiting_for_phone'] = True
    context.user_data['showing_offer'] = False

async def decline_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отказ от оферты - с переходом в главное меню"""
    user_id = update.message.from_user.id
    
    from database import decline_offer
    decline_offer(user_id)
    
    # Очищаем user_data
    context.user_data.clear()
    
    # Показываем сообщение и сразу переходим в главное меню
    keyboard = [["📚 Мои задания", "🎯 Купить тренинг"],
                ["👤 Профиль", "🛠 Тех.поддержка"]]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "❌ **Вы отказались от оферты.**\n\n"
        "Для регистрации и последующего использования бота необходимо принять пользовательское соглашение.\n",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Очищаем флаг показа оферты
    if 'showing_offer' in context.user_data:
        del context.user_data['showing_offer']

async def decline_service_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отказ от оферты - с переходом в главное меню"""
    user_id = update.message.from_user.id
    
    from database import decline_offer
    decline_offer(user_id)
    
    # Очищаем user_data
    context.user_data.clear()
    
    # Показываем сообщение и сразу переходим в главное меню
    keyboard = [["📚 Мои задания", "🎯 Купить тренинг"],
                ["👤 Профиль", "🛠 Тех.поддержка"]]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "❌ **Вы отказались от оферты.**\n\n"
        "Для доступа к разделу покупки части тренинга необходимо принять оферту. Вы можете ознакомиться с полным текстом на этапе принятия оферты, либо позже в профиле в соответствующем разделе.\n",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Очищаем флаг показа оферты
    if 'showing_offer' in context.user_data:
        del context.user_data['showing_offer']

async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список мероприятий тренинга"""

    schedule_text = """

**📅 Расписание тренингов**

Расписание

Этап 1 Планирование

Часть первая: Самонаблюдение и Намеренье.
20 декабря - 1 февраля 2026 года
Часть вторая: Инвентаризация ресурсов
2 февраля - 20 марта 2026 года

Этап 2. Действие

Часть третья: Самонаблюдение в действиях
21 марта - 1 мая 2026 года
Часть четвёртая: Действие в группе
2 мая - 21 июня 2026 года


этап 3 Принятие результата

Часть пятая: Лидерство и власть
22 июня - 1 августа 2026 года
Часть шестая: Принятие результата
22 июня - 1 августа 2026 года

Этап четвёртый: корректировка, закрепление

Часть седьмая: Осознание опыта
2 августа - 22 сентября 2026 года
Часть восьмая: Интеграция частей
2 ноября - 20 декабря 2026 года

    """
    
    keyboard = [
        ["🔙 Назад к описанию тренинга"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        schedule_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расписание всех марафона"""

    schedule_text = """

**📅 Расписание вебинаров**

Раздел на доработке, информация скоро появится!

    """
    
    keyboard = [
        ["🔙 Назад к описанию тренинга"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        schedule_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_service_offer_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает оферту на услуги с inline-кнопкой"""
    user_id = update.message.from_user.id
    arc_text = context.user_data.get('pending_purchase_arc', '')
    
    print(f"🔍 show_service_offer_agreement: сохраняем arc '{arc_text}' для user {user_id}")
    
    # Сохраняем ВСЕ данные из контекста
    purchase_context = {
        'pending_purchase_arc': arc_text,
        'current_section': context.user_data.get('current_section'),
        'current_arc_catalog': context.user_data.get('current_arc_catalog'),
        'part_status': context.user_data.get('part_status'),
        'buy_arc_id': context.user_data.get('buy_arc_id'),
        'buy_arc_price': context.user_data.get('buy_arc_price'),
        'original_message_text': update.message.text if hasattr(update, 'message') else ''
    }
    
    # Сохраняем в user_data
    context.user_data['saved_purchase_context'] = purchase_context
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    message_text = """📋 **ОФЕРТА НА ОКАЗАНИЕ УСЛУГ**

1. ОБЩИЕ ПОЛОЖЕНИЯ 

Настоящая публичная оферта является официальным публичным предложением Индивидуального предпринимателя Касимова Артема Равкатовича, действующего на основании свидетельства о государственной регистрации физического лица в качестве индивидуального предпринимателя ОГРНИП: 322665800202689: от 1 ноября 2022 г., и действующего на основании Диплома о профессиональной переподготовке № 0005 от 12.07.2023г., именуемого в дальнейшем «Исполнитель», заключить публичный договор (далее – «Договор» или «Оферта») об оказании психологических консультационных услуг юридическим и дееспособным физическим лицам на перечисленных ниже условиях.

*Полный текст оферты доступен по ссылке ниже.*"""

    inline_keyboard = [[
        InlineKeyboardButton("📄 Читать полную оферту", 
                           url="https://telegra.ph/Oferta-okazaniya-uslug-12-16")
    ]]
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    reply_keyboard = [
        ["✅ Принять оферту услуг"],
        ["❌ Отказаться от оферты"]
    ]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message_text,
        reply_markup=inline_markup,
        parse_mode='Markdown'
    )
    
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=reply_markup
    )
    
    context.user_data['showing_service_offer'] = True

async def accept_service_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Упрощенная версия - показывает кнопку для перехода"""
    user_id = update.message.from_user.id
    
    # 1. Принимаем оферту
    from database import accept_service_offer
    accept_service_offer(user_id)
    
    # 2. Получаем сохраненную часть
    pending_arc = context.user_data.get('pending_purchase_arc')
    
    if pending_arc:
        # 3. Показываем сообщение с кнопкой
        keyboard = [[pending_arc]]
        keyboard.append(["🔙 Выбор марафона"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "✅ **Оферта услуг принята!**\n\n"
            f"Теперь вы можете приобрести доступ к **{pending_arc}**.\n\n"
            "Нажмите на кнопку ниже чтобы продолжить покупку:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        
        # Очищаем сохраненную часть
        context.user_data.pop('pending_purchase_arc', None)
    else:
        # Если нет сохраненной части
        await update.message.reply_text(
            "✅ **Оферта услуг принята!**\n\n"
            "Теперь вы можете приобрести доступ к части тренинга.",
            parse_mode='Markdown'
        )
        await show_course_main(update, context)

async def show_accepted_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список принятых оферт с ссылками"""
    user_id = update.message.from_user.id
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT accepted_offer, accepted_offer_date, 
               accepted_service_offer, accepted_service_offer_date
        FROM users WHERE user_id = ?
    ''', (user_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text("❌ Данные не найдены")
        return
    
    accepted_offer, offer_date, accepted_service, service_date = result
    
    def format_moscow_date(date_str):
        if not date_str:
            return "дата не указана"
        try:
            from datetime import datetime, timedelta
            utc_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            msk_date = utc_date + timedelta(hours=3)
            return msk_date.strftime("%d.%m.%Y %H:%M (МСК)")
        except:
            return date_str
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    keyboard = []
    message = "📋 **Ваши принятые оферты**\n\n"
    
    if accepted_offer:
        formatted_date = format_moscow_date(offer_date)
        message += f"✅ **Политика конфиденциальности**\n"
        message += f"📅 Принята: {formatted_date}\n\n"
        
        keyboard.append([
            InlineKeyboardButton("📄 Политика конфиденциальности", 
                               url="https://telegra.ph/Politika-konfidencialnosti-12-15-55")
        ])
    
    if accepted_service:
        formatted_date = format_moscow_date(service_date)
        message += f"✅ **Оферта оказания услуг**\n"
        message += f"📅 Принята: {formatted_date}\n\n"
        
        keyboard.append([
            InlineKeyboardButton("📄 Оферта оказания услуг)", 
                               url="https://telegra.ph/Oferta-okazaniya-uslug-12-16")
        ])
    
    if not keyboard:
        message += "❌ У вас нет принятых оферт.\n\n"
        message += "Примите оферты в соответствующих разделах."
    
    inline_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    
    reply_keyboard = [["🔙 Назад в кабинет"]]
    reply_markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    if inline_markup:
        await update.message.reply_text(
            message,
            reply_markup=inline_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message,
            parse_mode='Markdown'
        )
    
    await update.message.reply_text(
        "Нажмите кнопку чтобы вернуться:",
        reply_markup=reply_markup
    )

async def show_today_assignments_info(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    """Показывает информацию о заданиях на текущий день для ВСЕХ активных частей"""
    if not user_id:
        user_id = update.message.from_user.id
    
    from database import get_user_active_arcs, get_current_arc_day, get_user_local_time
    
    active_arcs = get_user_active_arcs(user_id)
    
    if not active_arcs:
        return "Сейчас нет активных потоков."
    
    messages = []
    
    for arc_id, arc_title, arc_start, arc_end, access_type in active_arcs:
        day_info = get_current_arc_day(user_id, arc_id)
        
        if not day_info or day_info['day_number'] == 0:
            continue
        
        day_id = day_info['day_id']
        day_title = day_info['day_title']
        day_number = day_info['day_number']
        
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT a.title, a.доступно_до, 
                   upa.status as user_status
            FROM assignments a
            LEFT JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id 
                AND upa.user_id = ?
            WHERE a.day_id = ? 
            ORDER BY a.assignment_id
        ''', (user_id, day_id))

        assignments = cursor.fetchall()
        
        deadline_hour, deadline_minute = 12, 0
        if assignments and assignments[0][1]:
            try:
                time_str = str(assignments[0][1])
                if ':' in time_str:
                    deadline_hour, deadline_minute = map(int, time_str.split(':'))
            except:
                pass
        
        conn.close()
        
        user_time = get_user_local_time(user_id)
        current_hour = user_time.hour
        current_minute = user_time.minute
        
        is_day_available = (current_hour < deadline_hour or 
                           (current_hour == deadline_hour and current_minute < deadline_minute))

        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT order_num FROM arcs WHERE arc_id = ?', (arc_id,))
        arc_result = cursor.fetchone()
        arc_number = arc_result[0] if arc_result else '?'
        conn.close()
        
        all_submitted_or_approved = True
        if assignments:
            for title, available_until, user_status in assignments:
                if user_status not in ['submitted', 'approved']:
                    all_submitted_or_approved = False
                    break

        message = f"📅 **{day_title}** (Поток: {arc_title})\n\n"

        if all_submitted_or_approved and assignments:
            message += "🎉 **Вы выполнили все задания на сегодня!**\n"
            message += "Новые задания откроются завтра в 06:00\n\n"
        
        elif is_day_available and assignments:
            message += "✅ **Задания на текущий день доступны!**\n"
            message += f"Дедлайн: до {deadline_hour:02d}:{deadline_minute:02d}\n\n"
        
        elif not is_day_available and assignments:
            message += f"⏰ **Время выполнения заданий на сегодня истекло!**\n"
            message += f"Задания текущего дня уже закрыты (дедлайн был до {deadline_hour:02d}:{deadline_minute:02d}).\n"
            message += "Новые задания откроются завтра в 06:00\n\n"

        if assignments and not all_submitted_or_approved:
            for i, (title, available_until, user_status) in enumerate(assignments, 1):
                status_icon = "✅" if user_status in ['submitted', 'approved'] else "📝"
                time_text = f" - доступно до {available_until or '12:00'}"
                message += f"{i}. {status_icon} **{title}**{time_text}\n"
        
            message += "\n"
        
        message += "💡 **Важно:**\n"
        message += "• Задания должны быть выполнены до указанного времени\n"
        message += "• Если задание не выполнено вовремя, оно засчитывается как пропущенное\n"
        message += "• Пропуски отображаются в разделе 'Мой прогресс'\n"
        message += "• Задания, завершившиеся до получения доступа, не считаются пропусками\n\n"
        
        messages.append(message)
    
    if not messages:
        return "На сегодня нет активных заданий в ваших потоках."
    
    return "\n" + "="*40 + "\n".join(messages)

async def show_quick_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает краткое руководство по работе с заданиями"""
    
    guide_text = """📖 **КРАТКОЕ РУКОВОДСТВО ПО РАБОТЕ С ЗАДАНИЯМИ**

🎯 **КАК РАБОТАТЬ С ЗАДАНИЯМИ:**
1. **Ежедневно** в 06:00 открывается новый день и задания для него в разделе 'Доступные задания'
2. **Выберите задание** → выберите способ отправки ответа (только текст, только фото или текст+фото)
   • В зависимости от выбранного способа отправки ответа на задание зависит что будет прикреплено к заданию при отправке на проверку.
   • К ответу, при необходимости, можете **добавить комментарий** нажав на соответствующую кнопку.
   • Можете отправить несколько фотографий и несколько комментариев при необходимости, количество того, что прикрепит к итоговому ответу будет отображена.
3. **Отправляете ответ** → он сохранится и учтется в 'Мой прогресс'
4. Выполненные задания можно просмотреть в любой момент, но изменить уже нельзя.
5. Если вы пропустите день, то он останется доступен для выполнения, но вы потеряете 'серию без пропусков' в разделе 'Мой прогресс'

❓ **ЕСТЬ ВОПРОСЫ по заданиям?**
• В разделе 'Архив заданий' в каждом задании есть возможность связаться с психологом, нажав на 👤 Личная консультация
• В каждом задании при выполнении так же есть возможность связаться с психологом
"""

    # Создаем клавиатуру для возврата
    keyboard = [["📚 Мои задания"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Отправляем руководство
    await update.message.reply_text(
        guide_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_photo_only_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает ответ ТОЛЬКО ФОТО"""
    context.user_data['answering'] = True
    context.user_data['answer_type'] = 'Только_фото'
    context.user_data['answer_text'] = None
    context.user_data['answer_files'] = []
    
    keyboard = [["🔙 Назад в меню заданий"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📷 **Отправьте фото для задания:**\n\n"
        "После отправки всех фото нажмите кнопку '✅ Отправить задание'.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_text_only_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает ответ ТОЛЬКО ТЕКСТ"""
    context.user_data['answering'] = True
    context.user_data['answer_type'] = 'Только_текст'
    context.user_data['answer_text'] = None
    context.user_data['answer_files'] = []
    
    keyboard = [["🔙 Назад в меню заданий"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📝 **Напишите текстовый ответ на задание:**\n\n"
        "После написания текста нажмите кнопку '✅ Отправить задание'.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_photo_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает ответ ФОТО + ТЕКСТ (старый вариант)"""
    context.user_data['answering'] = True
    context.user_data['answer_type'] = 'Фото_и_текст'
    context.user_data['answer_text'] = None
    context.user_data['answer_files'] = []
    context.user_data['questions'] = []
    
    keyboard = [["🔙 Назад в меню заданий"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📝 **Напишите текстовый ответ на задание:**\n\n"
        "После текста нужно будет прикрепить фото и затем нажмите кнопку '✅ Отправить задание' .",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_submit_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает кнопки отправки с возможностью задать вопрос"""
    answer_type = context.user_data.get('answer_type', 'Фото_и_текст')
    
    files_count = len(context.user_data.get('answer_files', []))
    questions_count = len(context.user_data.get('questions', []))
    
    message = f"📊 **Готово!**\n\n"
    
    if answer_type == 'Только_фото':
        message += f"📎 Фото: {files_count} шт.\n"
    elif answer_type == 'Только_текст':
        text_preview = context.user_data.get('answer_text', '')[:100]
        message += f"✅ Текст ответа: сохранен\n"
        message += f"📄 Предпросмотр: {text_preview}...\n"
    
    message += f"💬 Вопросы: {questions_count} шт.\n\n"
    message += f"**Вы можете:**\n"
    message += f"• Задать вопрос по заданию\n"
    message += f"• **Отправить задание на проверку**\n\n"
    message += f"После отправки изменить ответ будет нельзя!"
    
    keyboard = [
        ["💬 Задать вопрос"],
        ["✅ Отправить задание"],
        ["🔙 Назад в меню заданий"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def ask_question_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает добавление вопроса к заданию"""
    answer_type = context.user_data.get('answer_type', 'Фото_и_текст')
    
    if answer_type == 'Только_фото' and not context.user_data.get('answer_files'):
        await update.message.reply_text(
            "📷 **Сначала отправьте фото для задания!**\n\n"
            "Вы выбрали вариант 'Только фото'.\n"
            "Пожалуйста, сначала отправьте фото, затем можете задать вопросы.",
            parse_mode='Markdown'
        )
        return
    
    if answer_type == 'Только_текст' and not context.user_data.get('answer_text'):
        await update.message.reply_text(
            "📝 **Сначала напишите текстовый ответ!**\n\n"
            "Вы выбрали вариант 'Только текст'.\n"
            "Пожалуйста, сначала напишите ответ, затем можете задать вопросы.",
            parse_mode='Markdown'
        )
        return
    
    if answer_type == 'Только_фото':
        files_count = len(context.user_data.get('answer_files', []))
        status = f"📎 Фото: {files_count} шт."
    elif answer_type == 'Только_текст':
        status = "✅ Текст ответа: сохранен"
    else:
        files_count = len(context.user_data.get('answer_files', []))
        status = f"✅ Текст + 📎 {files_count} фото"
    
    await update.message.reply_text(
        f"💬 **Задать вопрос по заданию**\n\n"
        f"Текущий статус: {status}\n\n"
        f"**Напишите ваш вопрос:**\n"
        f"(вопрос будет прикреплен к ответу на задание)",
        parse_mode='Markdown'
    )
    
    context.user_data['waiting_for_question'] = True

async def show_training_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о тренинге или фестивале"""
    training_text = update.message.text
    training_name = training_text[2:].strip()
    
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    
    if training_name == "Часть первая: Самонаблюдение и намеренье":
        message = """**Часть первая: Самонаблюдение и намеренье**
20 декабря - 1 февраля 2026 года
интенсивное погружение 19-21 декабря. Три дня живого контакта с собой и группой. Работа, фестиваль, шеринг. Мы создаем среду, где рушатся внутренние барьеры.
Полное погружение.Формат:
Пятница, 19.12 вечер, 19.00 заезд.
Размещение, подготовка к тренингу.
Суббота, 20.12, с 10.00 до 19.00 Основная часть тренинга
Фестиваль 20.00 до 24.00
Воскресенье, 21.12 10.00 до 17.00 Шеринг. Завершение

**Места сознательно ограничены до 12 участников. Это гарантия глубины работы для каждого участника.**

**более подробно прочитайте в статье нажав на кнопку ниже**"""
        
        inline_keyboard = [[
            InlineKeyboardButton("📄 Подробнее в статье", 
                               url="https://telegra.ph/Trening-pervyj-12-17")
        ]]
        inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    else:
        message = f"🎯 **{training_name}**\n\n"
        message += "**Ожидайте новостей!**\n\n"
        
        if training_name == "Фестиваль":
            message += "ожидайте новостей\n"
        else:
            message += "Тренинг будет запланирован незадолго до старта.\n"
        
        message += "Дата и время будут объявлены за 7 дней."
        inline_markup = None
    
    keyboard = [["🔙 Назад к мероприятиям"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    if inline_markup:
        await update.message.reply_text(
            message,
            reply_markup=inline_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            message,
            parse_mode='Markdown'
        )
    
    await update.message.reply_text(
        "Нажмите кнопку чтобы вернуться:",
        reply_markup=reply_markup
    )

async def send_scheduled_notifications(context: ContextTypes.DEFAULT_TYPE):
    """Отправка запланированных уведомлений"""
    print("="*50)
    print("🔔 [JOB] Проверка уведомлений...")
    
    from datetime import datetime, time
    from database import (
        get_user_local_time, get_current_arc, get_user_offer_status,
        get_notification, check_notification_sent, mark_notification_sent,
        get_mass_notification, get_user_skip_statistics
    )
    
    current_moscow = get_moscow_time()
    print(f"🕐 Текущее время МСК: {current_moscow}")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT user_id, username, timezone_offset, city, phone
        FROM users 
        WHERE timezone_offset IS NOT NULL 
        AND accepted_offer = 1 
        AND phone IS NOT NULL
    ''')
    
    users = cursor.fetchall()
    print(f"👥 Найдено пользователей: {len(users)}")
    
    total_sent = 0
    
    for user_id, username, timezone_offset, city, phone in users:
        try:
            user_time = get_user_local_time(user_id)
            user_hour = user_time.hour
            user_minute = user_time.minute
            
            print(f"👤 Пользователь: @{username or user_id} ({city})")
            print(f"   Местное время: {user_time.strftime('%H:%M')}")
            
            cursor.execute('''
                SELECT uaa.arc_id, a.title, a.дата_начала
                FROM user_arc_access uaa
                JOIN arcs a ON uaa.arc_id = a.arc_id
                WHERE uaa.user_id = ?
            ''', (user_id,))
            
            user_arcs = cursor.fetchall()
            
            if not user_arcs:
                continue
            
            for arc_id, arc_title, arc_start in user_arcs:

                # ПРОВЕРКА: arc_start может быть None!
                if not arc_start:
                    print(f"   ⚠️ У части {arc_title} нет даты начала, пропускаем")
                    continue
                
                # ПРЕОБРАЗОВАНИЕ ДАТЫ С ПРОВЕРКОЙ
                try:
                    if isinstance(arc_start, str):
                        arc_start_date = datetime.fromisoformat(arc_start).date()
                    else:
                        arc_start_date = arc_start
                    
                    # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА
                    if arc_start_date is None:
                        print(f"   ⚠️ Не удалось получить дату начала для {arc_title}")
                        continue
                        
                except Exception as e:
                    print(f"   ⚠️ Ошибка преобразования даты {arc_start}: {e}")
                    continue
                
                # ТЕПЕРЬ МОЖНО БЕЗОПАСНО СРАВНИВАТЬ
                if user_time.date() < arc_start_date:
                    continue
                
                if isinstance(arc_start, str):
                    arc_start_date = datetime.fromisoformat(arc_start).date()
                else:
                    arc_start_date = arc_start
                
                if user_time.date() < arc_start_date:
                    continue
                
                current_day = (user_time.date() - arc_start_date).days + 1
                current_day = min(max(current_day, 1), 40)
                
                print(f"   🔄 Часть тренинга: {arc_title}, день: {current_day}")
                
                if user_hour == 6 and user_minute == 0:
                    notification = get_notification(1, current_day)
                    if notification:
                        if not check_notification_sent(user_id, notification['id'], current_day):
                            message = notification['text']
                            
                            cursor.execute('''
                                SELECT COUNT(*) 
                                FROM assignments a
                                JOIN days d ON a.day_id = d.day_id
                                WHERE d.arc_id = ? AND d.order_num = ?
                            ''', (arc_id, current_day))
                            
                            assignment_count = cursor.fetchone()[0]

                            message += f"\n\n**Все шаги живут в разделе 'Мои задания'**\n"
                            
                            try:
                                if notification.get('image_url'):
                                    await context.bot.send_photo(
                                        chat_id=user_id,
                                        photo=notification['image_url'],
                                        caption=message,
                                        parse_mode='Markdown'
                                    )
                                else:
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=message,
                                        parse_mode='Markdown'
                                    )
                                
                                mark_notification_sent(user_id, notification['id'], current_day)
                                total_sent += 1
                                print(f"   ✅ Отправлено утреннее уведомление")
                            except Exception as e:
                                print(f"   ❌ Ошибка отправки: {e}")

                # ========== ВЕЧЕРНИЕ УВЕДОМЛЕНИЯ 19:00 (тип 7) ==========
                if user_hour == 19 and user_minute == 0:
                    notification = get_notification(7, current_day)
                    if notification and notification.get('text'):
                        if not check_notification_sent(user_id, notification['id'], current_day):
                            # Берем только текст из таблицы, добавляем заголовок
                            message_text = notification['text']
                            
                            # Формируем финальное сообщение с заголовком
                            message = "СЕБЯ ВЕРНИ СЕБЕ\n\n" + message_text
                            
                            try:
                                if notification.get('image_url'):
                                    await context.bot.send_photo(
                                        chat_id=user_id,
                                        photo=notification['image_url'],
                                        caption=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                else:
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                
                                mark_notification_sent(user_id, notification['id'], current_day)
                                total_sent += 1
                                print(f"   ✅ Отправлено вечернее уведомление (19:00)")
                            except Exception as e:
                                print(f"   ❌ Ошибка отправки: {e}")

                # ========== ВЕЧЕРНИЕ УВЕДОМЛЕНИЯ 21:00 (тип 8) ==========
                if user_hour == 21 and user_minute == 0:
                    notification = get_notification(8, current_day)
                    if notification and notification.get('text'):
                        if not check_notification_sent(user_id, notification['id'], current_day):
                            # Берем только текст из таблицы, добавляем заголовок
                            message_text = notification['text']
                            
                            # Формируем финальное сообщение с заголовком
                            message = "СЕБЯ ВЕРНИ СЕБЕ\n\n" + message_text
                            
                            try:
                                if notification.get('image_url'):
                                    await context.bot.send_photo(
                                        chat_id=user_id,
                                        photo=notification['image_url'],
                                        caption=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                else:
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                
                                mark_notification_sent(user_id, notification['id'], current_day)
                                total_sent += 1
                                print(f"   ✅ Отправлено вечернее уведомление (21:00)")
                            except Exception as e:
                                print(f"   ❌ Ошибка отправки: {e}")

                # ========== ВЕЧЕРНИЕ УВЕДОМЛЕНИЯ 10:00 (тип 9) ==========
                if user_hour == 10 and user_minute == 0:
                    notification = get_notification(9, current_day)
                    if notification and notification.get('text'):
                        if not check_notification_sent(user_id, notification['id'], current_day):
                            # Берем только текст из таблицы, добавляем заголовок
                            message_text = notification['text']
                            
                            # Формируем финальное сообщение с заголовком
                            message = "СЕБЯ ВЕРНИ СЕБЕ\n\n" + message_text
                            
                            try:
                                if notification.get('image_url'):
                                    await context.bot.send_photo(
                                        chat_id=user_id,
                                        photo=notification['image_url'],
                                        caption=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                else:
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                
                                mark_notification_sent(user_id, notification['id'], current_day)
                                total_sent += 1
                                print(f"   ✅ Отправлено вечернее уведомление (21:00)")
                            except Exception as e:
                                print(f"   ❌ Ошибка отправки: {e}")

                    # ========== ВЕЧЕРНИЕ УВЕДОМЛЕНИЯ 10:00 (тип 9) ==========
                if user_hour == 8 and user_minute == 45:
                    notification = get_notification(10, current_day)
                    if notification and notification.get('text'):
                        if not check_notification_sent(user_id, notification['id'], current_day):
                            # Берем только текст из таблицы, добавляем заголовок
                            message_text = notification['text']
                            
                            # Формируем финальное сообщение с заголовком
                            message = "СЕБЯ ВЕРНИ СЕБЕ\n\n" + message_text
                            
                            try:
                                if notification.get('image_url'):
                                    await context.bot.send_photo(
                                        chat_id=user_id,
                                        photo=notification['image_url'],
                                        caption=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                else:
                                    await context.bot.send_message(
                                        chat_id=user_id,
                                        text=message,
                                        parse_mode=None  # Без форматирования
                                    )
                                
                                mark_notification_sent(user_id, notification['id'], current_day)
                                total_sent += 1
                                print(f"   ✅ Отправлено вечернее уведомление (21:00)")
                            except Exception as e:
                                print(f"   ❌ Ошибка отправки: {e}")
               
                
                if user_hour == 9 and user_minute == 0:
                
                    cursor.execute('''
                        SELECT дата_начала 
                        FROM arcs 
                        WHERE arc_id = ?
                    ''', (arc_id,))
                    
                    arc_start_date_result = cursor.fetchone()
                    if arc_start_date_result:
                        arc_start_date = arc_start_date_result[0]
                        if isinstance(arc_start_date, str):
                            arc_start_date = datetime.fromisoformat(arc_start_date).date()
                        
                        days_before_start = (arc_start_date - user_time.date()).days
                        
                        if days_before_start == 2:
                            mass_notif = get_mass_notification(6, 2)
                            if mass_notif:
                                message = mass_notif['text']
                                message = message.replace('[номер_части]', arc_title)
                                message = message.replace('[дата_начала]', arc_start_date.strftime('%d.%m.%Y'))
                                
                                cursor.execute('''
                                    SELECT DISTINCT u.user_id 
                                    FROM users u
                                    WHERE u.accepted_offer = 1 
                                    AND u.phone IS NOT NULL
                                    AND u.user_id NOT IN (
                                        SELECT user_id FROM user_arc_access WHERE arc_id = ?
                                    )
                                ''', (arc_id,))
                                
                                all_users = cursor.fetchall()
                                
                                for (uid,) in all_users:
                                    try:
                                        if not check_notification_sent(uid, mass_notif['id']):
                                            await context.bot.send_message(
                                                chat_id=uid,
                                                text=message,
                                                parse_mode='Markdown'
                                            )
                                            mark_notification_sent(uid, mass_notif['id'])
                                            print(f"   📢 Отправлено уведомление о старте части тренинга пользователю {uid}")
                                    except Exception as e:
                                        print(f"   ❌ Ошибка отправки: {e}")
            
        except Exception as e:
            print(f"❌ Ошибка обработки пользователя {user_id}: {e}")
    
    conn.close()
    
    print(f"📊 Итог: отправлено уведомлений - {total_sent}")
    print("="*50)

async def buy_company_access(update: Update, context: ContextTypes.DEFAULT_TYPE, company_arc_id, trial=False):
    """Покупка доступа к тренингу компании"""
    user_id = update.message.from_user.id
    
    from database import get_user_company, get_company_arc
    
    user_company = get_user_company(user_id)
    if not user_company:
        await update.message.reply_text("❌ Вы не состоите в компании!")
        return
    
    company_arc = get_company_arc(user_company['company_id'])
    if not company_arc:
        await update.message.reply_text("❌ У компании нет активного тренинга")
        return
    
    # Проверяем не куплен ли уже доступ
    from database import check_user_arc_access
    if check_user_arc_access(user_id, company_arc_id):
        await update.message.reply_text("✅ У вас уже есть доступ к тренингу компании!")
        return
    
    # Определяем цену
    if trial:
        amount = 100  # Символическая сумма для пробного
        description = f"Пробный доступ к тренингу компании '{user_company['name']}'"
    else:
        amount = user_company['price']
        description = f"Полный доступ к тренингу компании '{user_company['name']}'"
    
    # Создаем платеж через Юкассу
    from database import create_yookassa_payment
    payment_url, payment_id = create_yookassa_payment(
        user_id, company_arc_id, amount, trial, description
    )
    
    if not payment_url:
        await update.message.reply_text(f"❌ Ошибка создания платежа")
        return
    
    # Сохраняем информацию о платеже
    context.user_data[f'payment_{user_id}'] = {
        'payment_id': payment_id,
        'company_arc_id': company_arc_id,
        'company_name': user_company['name'],
        'amount': amount,
        'trial': trial,
        'timestamp': datetime.now().isoformat()
    }
    
    # Создаем кнопки оплаты
    keyboard = [
        [InlineKeyboardButton("💳 Перейти к оплате", url=payment_url)],
        [InlineKeyboardButton("✅ Я оплатил", callback_data=f"check_payment_{payment_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = f"💳 **Оплата доступа к тренингу компании**\n\n"
    message_text += f"🏢 **Компания:** {user_company['name']}\n"
    message_text += f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n"
    message_text += f"💰 **Сумма:** {amount}₽\n"
    
    if trial:
        message_text += f"📝 **Тип:** Пробный доступ (3 дня)\n\n"
    else:
        message_text += f"📝 **Тип:** Полный доступ (56 дней)\n\n"
        
    message_text += "**Инструкция:**\n"
    message_text += "1. Нажмите '💳 Перейти к оплате'\n"
    message_text += "2. Оплатите в открывшемся окне\n"
    message_text += "3. Вернитесь в бот и нажмите '✅ Я оплатил'\n\n"
    message_text += f"📝 ID платежа: `{payment_id}`"
    
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def buy_arc_with_yookassa(update: Update, context: ContextTypes.DEFAULT_TYPE, trial=False):
    """Покупка доступа через Юкассу - АДАПТИРОВАННАЯ ДЛЯ КОМПАНИЙ"""
    user_id = update.message.from_user.id
    logger.info(f"Начало покупки: user={user_id}, trial={trial}")
    
    print(f"🔍 DEBUG buy_arc_with_yookassa: user_id={user_id}, trial={trial}")
    
    # ★★★ ДЛЯ ТРИАЛЬНОГО ДОСТУПА (БЕСПЛАТНО) ★★★
    if trial:
        # БЕСПЛАТНЫЙ пробный доступ - сразу выдаем
        return await grant_free_trial_access(update, context)
    
    # ★★★ ПРОВЕРЯЕМ КОМПАНИЮ ПОЛЬЗОВАТЕЛЯ ★★★
    from database import get_user_company, get_company_arc
    
    user_company = get_user_company(user_id)
    if not user_company:
        await update.message.reply_text(
            "❌ **Вы не состоите в компании!**\n\n"
            "Сначала присоединитесь к компании через профиль.",
            parse_mode='Markdown'
        )
        return
    
    # Получаем арку компании
    company_arc = get_company_arc(user_company['company_id'])
    if not company_arc:
        await update.message.reply_text("❌ У компании нет активного тренинга")
        return
    
    company_arc_id = company_arc['company_arc_id']
    company_name = user_company['name']
    price = user_company['price']
    
    # Проверяем не куплен ли уже доступ
    from database import check_user_arc_access
    has_access = check_user_arc_access(user_id, company_arc_id)
    
    if has_access:
        await update.message.reply_text(
            "✅ **У вас уже есть доступ к тренингу компании!**\n\n"
            "Проверьте раздел 'Мои задания'.",
            parse_mode='Markdown'
        )
        return
    
    # ★★★ СОЗДАЕМ ПЛАТЕЖ ЧЕРЕЗ ЮКАССУ ★★★
    description = f"Полный доступ к тренингу компании '{company_name}'"
    
    print(f"🔍 DEBUG: Создаем платеж для компании: {company_name}, цена: {price}")
    
    from database import create_yookassa_payment_with_receipt
    payment_url, payment_id = create_yookassa_payment_with_receipt(
        user_id, company_arc_id, price, False, description
    )
    
    print(f"🔍 DEBUG: Результат create_yookassa_payment: url={payment_url}, payment_id={payment_id}")
    
    if not payment_url:
        # Если упрощенная версия не сработала, пробуем обычную
        from database import create_yookassa_payment
        payment_url, payment_id = create_yookassa_payment(
            user_id, company_arc_id, price, False, description
        )
    
    if not payment_url:
        await update.message.reply_text(f"❌ Ошибка создания платежа: {payment_id}")
        return
    
    # Сохраняем информацию о платеже
    context.user_data[f'payment_{user_id}'] = {
        'payment_id': payment_id,
        'company_arc_id': company_arc_id,
        'company_name': company_name,
        'amount': price,
        'trial': False,
        'timestamp': datetime.now().isoformat()
    }
    
    # ★★★ СОЗДАЕМ КНОПКИ ОПЛАТЫ ★★★
    keyboard = [
        [InlineKeyboardButton("💳 Перейти к оплате", url=payment_url)],
        [InlineKeyboardButton("✅ Я оплатил", callback_data=f"check_payment_{payment_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message_text = f"💳 **Оплата доступа к тренингу компании**\n\n"
    message_text += f"🏢 **Компания:** {company_name}\n"
    message_text += f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n"
    message_text += f"💰 **Сумма:** {price}₽\n"
    message_text += f"📝 **Тип:** Полный доступ (56 дней)\n\n"
    message_text += "**Инструкция:**\n"
    message_text += "1. Нажмите '💳 Перейти к оплате'\n"
    message_text += "2. Оплатите в открывшемся окне\n"
    message_text += "3. Вернитесь в бот и нажмите '✅ Я оплатил'\n\n"
    message_text += f"📝 ID платежа: `{payment_id}`\n\n"
    message_text += "💡 **После оплаты доступ к заданиям откроется автоматически.**"
    
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    logger.info(f"Создан платеж: user={user_id}, company_arc={company_arc_id}, amount={price}")        

async def check_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет статус платежа - ОБНОВЛЕННАЯ С ОТЛАДКОЙ"""
    query = update.callback_query
    
    print(f"🔍 DEBUG: check_payment_callback ВЫЗВАН!")
    print(f"  Data: {query.data}")
    print(f"  User ID: {query.from_user.id}")
    
    # ★★★ ВАЖНО: Сначала отвечаем на callback ★★★
    await query.answer()
    print(f"  Callback answered")
    
    if query.data.startswith('check_payment_'):
        payment_id = query.data.replace('check_payment_', '')
        user_id = query.from_user.id
        
        print(f"🔍 DEBUG: Проверка платежа {payment_id} для пользователя {user_id}")
        
        try:
            # 1. Проверяем статус через API Юкассы
            import base64
            import requests
            from database import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_API_URL
            
            print(f"🔍 DEBUG: Проверяем платеж через API Юкассы: {payment_id}")
            
            auth_string = f'{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}'
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }
            
            print(f"🔍 DEBUG: Отправляем запрос к {YOOKASSA_API_URL}/{payment_id}")
            
            response = requests.get(f"{YOOKASSA_API_URL}/{payment_id}", headers=headers, timeout=10)
            
            print(f"🔍 DEBUG: Ответ от Юкассы: статус {response.status_code}")
            
            if response.status_code == 200:
                payment_info = response.json()
                status = payment_info.get("status")
                
                print(f"🔍 DEBUG: Статус платежа в Юкассе: {status}")
                
                # 2. Обновляем статус в нашей БД
                from database import update_payment_status
                update_payment_status(payment_id, status)
                
                if status == 'succeeded':
                    # 3. Получаем информацию о платеже компании
                    conn = sqlite3.connect('mentor_bot.db')
                    cursor = conn.cursor()
                    
                    cursor.execute('''
                        SELECT p.user_id, p.company_arc_id, p.amount, 
                               c.name as company_name, a.title as arc_title
                        FROM payments p
                        JOIN company_arcs ca ON p.company_arc_id = ca.company_arc_id
                        JOIN companies c ON ca.company_id = c.company_id
                        JOIN arcs a ON ca.arc_id = a.arc_id
                        WHERE p.yookassa_payment_id = ?
                    ''', (payment_id,))
                    
                    payment_data = cursor.fetchone()
                    
                    if payment_data:
                        user_id, company_arc_id, amount, company_name, arc_title = payment_data
                        
                        # ЗАКРЫВАЕМ соединение перед выдачей доступа
                        conn.close()
                        
                        # 4. ВЫДАЕМ ДОСТУП К КОМПАНИИ
                        from database import grant_arc_access
                        
                        access_type = 'paid'
                        access_text = f"полный ({amount}₽)"
                        
                        print(f"🔍 DEBUG: Выдаем доступ user={user_id}, company_arc={company_arc_id}")
                        
                        # Выдаем доступ к компании
                        access_granted = grant_arc_access(user_id, company_arc_id, access_type)
                        
                        if access_granted:
                            print(f"✅ DEBUG: Доступ выдан успешно")
                            
                            message = (
                                f"✅ **Оплата подтверждена!**\n\n"
                                f"🏢 **Компания:** {company_name}\n"
                                f"💰 **Сумма:** {amount}₽\n"
                                f"🎯 **Доступ:** {access_text}\n\n"
                                f"Теперь вы можете начать обучение в разделе '📚 Мои задания'."
                            )
                            
                            await query.edit_message_text(
                                message,
                                parse_mode='Markdown'
                            )
                            
                            print(f"✅ Сообщение обновлено")
                        else:
                            error_msg = "❌ Ошибка выдачи доступа"
                            print(f"❌ DEBUG: {error_msg}")
                            await query.edit_message_text(
                                f"✅ **Оплата подтверждена, но возникла проблема с доступом.**\n\n"
                                f"🏢 Компания: {company_name}\n"
                                f"💰 Сумма: {amount}₽\n\n"
                                f"Пожалуйста, нажмите /fixaccess чтобы получить доступ вручную.",
                                parse_mode='Markdown'
                            )
                    else:
                        error_msg = "Платеж найден в Юкассе, но не в нашей базе"
                        print(f"❌ DEBUG: {error_msg}")
                        await query.edit_message_text(
                            "❌ **Платеж найден в Юкассе, но не в нашей базе.**\n\n"
                            "Пожалуйста, обратитесь в поддержку.",
                            parse_mode='Markdown'
                        )
                
                elif status == 'pending':
                    print(f"⚠️ DEBUG: Платеж еще в обработке")
                    await query.answer(
                        "⏳ Платеж еще не подтвержден банком.\n"
                        "Обычно это занимает 1-2 минуты. Попробуйте через минуту.",
                        show_alert=True
                    )
                
                elif status == 'canceled':
                    print(f"❌ DEBUG: Платеж отменен")
                    await query.edit_message_text(
                        "❌ **Платеж отменен.**\n\n"
                        "Попробуйте оплатить снова или обратитесь в поддержку.",
                        parse_mode='Markdown'
                    )
                
                else:
                    print(f"⚠️ DEBUG: Неизвестный статус: {status}")
                    await query.answer(f"Статус платежа: {status}", show_alert=True)
            
            elif response.status_code == 404:
                print(f"❌ DEBUG: Платеж не найден в системе Юкассы")
                await query.answer("Платеж не найден в системе Юкассы", show_alert=True)
            
            else:
                error_msg = f"Ошибка API Юкассы: {response.status_code}"
                print(f"❌ DEBUG: {error_msg}")
                await query.answer(error_msg, show_alert=True)
        
        except Exception as e:
            error_msg = f"Ошибка проверки платежа: {str(e)}"
            print(f"❌ DEBUG: {error_msg}")
            import traceback
            traceback.print_exc()
            await query.answer(error_msg, show_alert=True)

async def send_long_message(update, text, prefix="", parse_mode='Markdown'):
    """Отправляет длинное сообщение частями"""
    max_length = 4096
    
    # Если текст короткий - отправляем как есть
    if len(text) <= max_length:
        if prefix:
            message = f"{prefix}\n\n{text}"
        else:
            message = text
        
        if update.message:
            await update.message.reply_text(message, parse_mode=parse_mode)
        else:
            await update.reply_text(message, parse_mode=parse_mode)
        return
    
    # Разбиваем длинный текст на части
    parts = []
    current_part = ""
    
    # Разбиваем по предложениям/абзацам
    paragraphs = text.split('\n\n')
    
    for paragraph in paragraphs:
        if len(current_part) + len(paragraph) + 2 <= max_length:
            if current_part:
                current_part += "\n\n"
            current_part += paragraph
        else:
            if current_part:
                parts.append(current_part)
            current_part = paragraph
    
    if current_part:
        parts.append(current_part)
    
    # Отправляем части
    for i, part in enumerate(parts, 1):
        if i == 1 and prefix:
            message = f"{prefix}\n\n{part}"
        else:
            message = part
        
        if update.message:
            await update.message.reply_text(message, parse_mode=parse_mode)
        else:
            await update.reply_text(message, parse_mode=parse_mode)

def clean_markdown_text(text):
    """Очищает текст от проблемных Markdown символов, но сохраняет корректное форматирование"""
    if not text:
        return text
    
    import re
    
    # 1. Заменяем множественные подчеркивания (3+) на дефисы
    # Это САМАЯ ВАЖНАЯ ЧАСТЬ - исправляет ошибку "Can't parse entities"
    text = re.sub(r'_{3,}', '---', text)
    
    # 2. НЕ экранируем корректные пары символов!
    # Вместо этого убираем сломанные форматирование
    
    # Считаем количество открывающих и закрывающих символов
    open_stars = text.count('**')
    close_stars = text.count('**')
    open_underscores = text.count('__')
    close_underscores = text.count('__')
    
    # Если форматирование сломано (нечетное количество) - убираем ВСЕ такие символы
    if (open_stars + close_stars) % 2 != 0:
        text = text.replace('**', '')
    if (open_underscores + close_underscores) % 2 != 0:
        text = text.replace('__', '')
    
    # 3. Проверяем и исправляем одиночные звездочки и подчеркивания
    # Считаем количество * и _
    single_stars = len(re.findall(r'(?<!\*)\*(?!\*)', text))
    single_underscores = len(re.findall(r'(?<!_)_(?!_)', text))
    
    # Если нечетное количество - убираем все одиночные
    if single_stars % 2 != 0:
        text = re.sub(r'(?<!\*)\*(?!\*)', '', text)
    if single_underscores % 2 != 0:
        text = re.sub(r'(?<!_)_(?!_)', '', text)
    
    # 4. Убираем обратные кавычки если они не парные
    backticks = text.count('`')
    if backticks % 2 != 0:
        text = text.replace('`', '')
    
    # 5. Проверяем квадратные скобки для ссылок
    # Если есть [ но нет ] - убираем
    if '[' in text and ']' not in text:
        text = text.replace('[', '')
    if ']' in text and '[' not in text:
        text = text.replace(']', '')
    
    return text

async def show_seminar_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали выбранного семинара"""
    seminar_name = update.message.text
    
    seminars = {
        "🎯 Часть первая: Самонаблюдение и намеренье": {
            "dates": "📅 22.12.2025 -30.01.2025",
            "time": "⏰ задания доступны с 6:00-12:00 по вашему времени установленному в профиле",
            "description": """
Часть первая: Самонаблюдение и намеренье(добавить описание)
Эта часть включат в себя выполнение 1 заадния которое открывается в 6:00. Вы должны успеть его выполнить за установленное время.
Отвечать на задание можно в трех вариациях: текстом, фотографией или тект+фото. Ваше выполненное задание отправится на проверу.
Как только психолог проверит его, вы получете обратную связь по нему и сможете изучить ее в соответвующем разделе.
""",
        }}
    if seminar_name not in seminars:
        await update.message.reply_text("❌ Информация о части не найден - на доработке")
        return
    
    info = seminars[seminar_name]
    
    message = f"**{seminar_name}**\n\n"
    message += f"{info['dates']}\n"
    message += f"{info['time']}\n\n"
    message += f"{info['description']}\n\n"
    
    keyboard = [
        ["🔙 Назад к частям тренинга"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_assignment_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text
    
    print(f"🔍 DEBUG show_assignment_from_list: text='{text}'")
    
    # Ищем задание в mapping
    mapping = context.user_data.get('assignments_mapping', [])
    assignment_info = None
    
    for info in mapping:
        if info['btn_text'] == text:
            assignment_info = info
            break
    
    if not assignment_info:
        print(f"❌ DEBUG: Задание '{text}' не найдено в mapping")
        print(f"  Доступные кнопки: {[m['btn_text'] for m in mapping]}")
        await update.message.reply_text("❌ Задание не найдено")
        return
    
    assignment_id = assignment_info['assignment_id']
    arc_id = assignment_info.get('arc_id', 1)  # ★★★ ИСПРАВЛЕНИЕ: используем arc_id из mapping или 1 по умолчанию ★★★
    
    print(f"🔍 DEBUG: Найдено задание ID={assignment_id}, arc_id={arc_id}")
    
    # Проверяем статус задания
    from database import check_assignment_status
    status = check_assignment_status(user_id, assignment_id)
    
    if status == 'submitted':
        await update.message.reply_text(
            "🟡 **Это задание уже на проверке!**\n\n"
            "Ждите ответа психолога в разделе 'Ответ психолога'.",
            parse_mode='Markdown'
        )
        return
    
    if status == 'approved':
        await update.message.reply_text(
            "✅ **Это задание уже проверено!**\n\n"
            "Ответ психолога доступен в разделе 'Ответ психолога'.",
            parse_mode='Markdown'
        )
        return
    
    # Сохраняем данные
    context.user_data['current_assignment'] = assignment_info['title']
    context.user_data['current_assignment_id'] = assignment_id
    context.user_data['current_arc_id'] = arc_id
    context.user_data['current_company_arc_id'] = assignment_info.get('company_arc_id')
    
    # Получаем day_id из базы данных
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT day_id, content_text, доступно_до, title 
        FROM assignments 
        WHERE assignment_id = ?
    ''', (assignment_id,))
    
    result = cursor.fetchone()
    
    if not result:
        conn.close()
        await update.message.reply_text("❌ Ошибка: задание не найдено в базе")
        return
    
    day_id, content_text, available_until, assignment_title = result
    
    # Получаем номер дня
    cursor.execute('''
        SELECT d.order_num, d.title as day_title
        FROM days d
        WHERE d.day_id = ?
    ''', (day_id,))
    
    day_info = cursor.fetchone()
    day_number = day_info[0] if day_info else 0
    day_title = day_info[1] if day_info else f"День {day_number}"
    
    conn.close()
    
    # Сохраняем day_id и day_number
    context.user_data['current_day_id'] = day_id
    context.user_data['current_day_number'] = day_number
    context.user_data['current_day_title'] = day_title

    from database import get_assignment_media
    media_data = None

    try:
        media_data = get_assignment_media(assignment_id)
        print(f"🔍 Получены медиа для задания {assignment_id}: {media_data}")
    except Exception as e:
        print(f"⚠️ Ошибка получения медиа: {e}")
        media_data = {'photos': [], 'audios': [], 'video_url': None}

    # ★★★ ПОКАЗЫВАЕМ ЗАДАНИЕ С ИНФОРМАЦИЕЙ О ДНЕ ★★★
    header = f"**📝 {assignment_title}**\n\n"
    header += f"📅 **{day_title}**\n\n"
    
    if available_until and available_until != '22:00':
        header += f"**Важно: задание будет сохранено только после выбора способа ответа(кнопки снизу)**\n\n"

    await update.message.reply_text(header, parse_mode='Markdown')

    # 1. Текст задания
    if content_text:
        await send_long_message(
            update, 
            content_text, 
            prefix="📋 **Задание:**",
            parse_mode='Markdown'
        )

    # 2. Фото (если есть и не пустой список)
    if media_data and media_data.get('photos'):
        photos = media_data['photos']
        if isinstance(photos, list) and photos:
            for i, photo_id in enumerate(photos[:5], 1):
                try:
                    await update.message.reply_photo(
                        photo=photo_id,
                        caption=f"🖼️ Фото {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки фото {i}: {e}")

    # 3. Аудио (если есть и не пустой список)
    if media_data and media_data.get('audios'):
        audios = media_data['audios']
        if isinstance(audios, list) and audios:
            for i, audio_id in enumerate(audios[:3], 1):
                try:
                    await update.message.reply_audio(
                        audio=audio_id,
                        caption=f"🎵 Аудио {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки аудио {i}: {e}")

    # 4. Видео (ссылка, если есть и не пустая)
    if media_data and media_data.get('video_url'):
        video_url = media_data['video_url']
        if video_url and video_url.strip():
            if 'youtube.com' in video_url or 'youtu.be' in video_url:
                await update.message.reply_text(f"🎬 Видео к заданию:\n{video_url}")
            elif video_url.startswith(('BAACAgI', 'CgACAgI', 'BAACAgQ', 'AgACAgI')):
                try:
                    await update.message.reply_video(
                        video=video_url,
                        caption="🎬 Видео к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки видео: {e}")
                    await update.message.reply_text("🎬 Видео к заданию")
            else:
                await update.message.reply_text(f"🎬 Видео к заданию:\n{video_url}")

    # ★★★ Показываем варианты ответа ★★★
    choice_message = "**📤 Выберите вариант ответа:**"

    keyboard = [
        ["📷 Только фото"],
        ["📝 Только текст"], 
        ["📷+📝 Фото и текст"],
        ["🔙 Назад в меню заданий"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    await update.message.reply_text(
        choice_message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Устанавливаем флаг что пользователь отвечает
    context.user_data['answering'] = True
    context.user_data['answer_text'] = None
    context.user_data['answer_files'] = []
    context.user_data['questions'] = []

async def show_in_progress_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает задания на проверке"""
    user_id = update.message.from_user.id
    
    in_progress = context.user_data.get('available_assignments', {}).get('in_progress', [])
    
    if not in_progress:
        await update.message.reply_text(
            "🟡 **Нет заданий на проверке.**\n\n"
            "Все отправленные задания уже проверены.",
            parse_mode='Markdown'
        )
        return
    
    message = "🟡 **ЗАДАНИЯ НА ПРОВЕРКЕ**\n\n"
    message += "Эти задания ждут ответа психолога:\n\n"
    
    for assignment in in_progress[:10]:
        message += f"• {assignment['title']} (день {assignment['day_num']})\n"
    
    message += "\n💬 Ответы появятся в разделе 'Ответ психолога'"
    
    keyboard = [["🔙 Назад в меню заданий"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_feedback_parts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает части с ответами психолога"""
    context.user_data['current_section'] = 'feedback'
    
    user_id = update.message.from_user.id
    
    from database import get_arcs_with_feedback
    arcs = get_arcs_with_feedback(user_id)
    
    if not arcs:
        await update.message.reply_text(
            "📝 **Пока нет ответов психолога.**\n\n"
            "Как только психолог проверит ваши работы, они появятся здесь.",
            parse_mode='Markdown'
        )
        return
    
    # ИНИЦИАЛИЗИРУЕМ mapping
    if 'feedback_arc_map' not in context.user_data:
        context.user_data['feedback_arc_map'] = {}
    
    keyboard = []
    for arc_id, arc_title, new_count, total_count in arcs:
        if new_count > 0:
            btn_text = f"🏆 {arc_title} 🟡({new_count})"
        else:
            btn_text = f"🏆 {arc_title} ({total_count})"
        keyboard.append([btn_text])
        
        # Сохраняем mapping
        context.user_data['feedback_arc_map'][btn_text] = arc_id
        # ★ ВАЖНО: Сохраняем также название арки
        context.user_data[f"arc_title_{arc_id}"] = arc_title
    
    keyboard.append(["📚 В раздел Мои задания"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "Архив заданий**\n\n"
        "Выберите часть:\n",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def show_feedback_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор типа ответов - ОБНОВЛЕННАЯ"""
    context.user_data['current_section'] = 'feedback_type'
    user_id = update.message.from_user.id
    
    # ★★ ВАЖНО: Получаем текст кнопки из update
    arc_text = update.message.text
    print(f"🔍 show_feedback_type: текст кнопки='{arc_text}'")
    
    # ★★ ВАЖНО: Проверяем что это не кнопка типа ответов
    if arc_text.startswith("🟡 Новые ответы") or arc_text.startswith("✅ Завершенные задания"):
        print(f"⚠️ Это кнопка типа ответов, пропускаем парсинг")
        # Это кнопка типа ответов - обрабатываем в show_feedback_list
        arc_id = context.user_data.get('current_feedback_arc')
        if arc_id:
            await show_feedback_list(update, context)
        else:
            await update.message.reply_text("❌ Ошибка: часть не выбрана")
        return
    
    # Очищаем текст от эмодзи и счетчиков
    import re
    
    # Убираем эмодзи 🏆 или 📚
    clean_title = arc_text.replace("🏆 ", "").replace("📚 ", "")
    
    # Убираем 🟡(X) или (X)
    clean_title = re.sub(r'\s*🟡\(\d+\)', '', clean_title)
    clean_title = re.sub(r'\s*\(\d+\)', '', clean_title)
    
    clean_title = clean_title.strip()
    
    print(f"🔍 Очищенное название: '{clean_title}'")
    
    # Ищем часть в БД
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT arc_id, title FROM arcs WHERE title = ?', (clean_title,))
    result = cursor.fetchone()
    
    if not result and "Часть" in clean_title:
        match = re.search(r'Часть\s*(\d+)', clean_title)
        if match:
            part_num = match.group(1)
            cursor.execute('SELECT arc_id, title FROM arcs WHERE title LIKE ?', (f'%{part_num}%',))
            result = cursor.fetchone()
    
    if not result:
        conn.close()
        
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT arc_id, title FROM arcs WHERE arc_id > 0')
        all_arcs = cursor.fetchall()
        conn.close()
        
        debug_msg = f"❌ Часть '{clean_title}' не найдена.\n\n**Доступные части:**\n"
        for arc_id, title in all_arcs:
            debug_msg += f"• {title}\n"
        
        await update.message.reply_text(debug_msg, parse_mode='Markdown')
        return
    
    arc_id, arc_title = result
    conn.close()
    
    print(f"✅ Найдена часть: ID={arc_id}, название='{arc_title}'")
    
    # Сохраняем в контекст
    context.user_data['current_feedback_arc'] = arc_id
    context.user_data['current_feedback_arc_title'] = arc_title
    
    # Получаем статистику
    from database import get_feedback_counts
    new_count, completed_count = get_feedback_counts(user_id, arc_id)
    
    print(f"📊 Статистика для части {arc_id}: новых={new_count}, завершенных={completed_count}")
    
    # Формируем сообщение
    message = f"💬 **Ответ психолога**\n\n"
    message += f"**Часть:** {arc_title}\n\n"
    
    if new_count == 0 and completed_count == 0:
        message += "📭 **В этой части пока нет проверенных заданий.**\n\n"
    else:
        message += f"📊 **Статистика ответов:**\n"
        if new_count > 0:
            message += f"• 🟡 Новые ответы: {new_count} (задания с комментариями психолога)\n"
        message += f"• ✅ Завершенные задания: {completed_count} (все проверенные задания)\n\n"

    message += "**В случае дополнительных комментариев от психолога в этом разделе появятся 'Новые ответы'**\n\n"
    message += "**Выберите раздел:**"
    
    # Создаем клавиатуру
    keyboard = []
    
    # Показываем "Новые ответы" только если они есть
    if new_count > 0:
        keyboard.append([f"🟡 Новые ответы ({new_count})"])
    
    # Всегда показываем "Завершенные задания"
    keyboard.append([f"✅ Завершенные задания ({completed_count})"])
    
    keyboard.append(["🔙 Назад к частям"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_feedback_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список заданий с ответами - УПРОЩЕННАЯ ВЕРСИЯ"""
    user_id = update.message.from_user.id
    text = update.message.text if update else ""
    
    arc_id = context.user_data.get('current_feedback_arc')
    arc_title = context.user_data.get('current_feedback_arc_title', f"Часть {arc_id}")
    
    if not arc_id:
        await update.message.reply_text("❌ Ошибка: часть не выбрана")
        return
    
    # Определяем тип просмотра
    view_type = 'new' if '🟡 Новые ответы' in text else 'completed'
    context.user_data['current_feedback_view_type'] = view_type
    
    print(f"🔍 Показываем список: тип={view_type}, арка={arc_id}")
    
    # Получаем задания в зависимости от типа
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    if view_type == 'new':
        # Задания с дополнительными комментариями, которые не просмотрены
        cursor.execute('''
            SELECT a.title, d.title as day_title, d.order_num,
                   upa.teacher_comment, upa.answer_text,
                   a.assignment_id, upa.has_additional_comment
            FROM assignments a
            JOIN days d ON a.day_id = d.day_id
            JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
            WHERE upa.user_id = ? 
              AND upa.status = 'approved'
              AND upa.has_additional_comment = 1
              AND upa.additional_comment_viewed = 0
              AND d.arc_id = ?
            ORDER BY d.order_num, a.assignment_id
        ''', (user_id, arc_id))
    else:
        # Все завершенные задания
        cursor.execute('''
            SELECT a.title, d.title as day_title, d.order_num,
                   upa.teacher_comment, upa.answer_text,
                   a.assignment_id, upa.has_additional_comment
            FROM assignments a
            JOIN days d ON a.day_id = d.day_id
            JOIN user_progress_advanced upa ON a.assignment_id = upa.assignment_id
            WHERE upa.user_id = ? 
              AND upa.status = 'approved'
              AND d.arc_id = ?
            ORDER BY d.order_num, a.assignment_id
        ''', (user_id, arc_id))
    
    assignments = cursor.fetchall()
    conn.close()
    
    print(f"🔍 Найдено заданий: {len(assignments)}")
    
    # Если нет заданий
    if not assignments:
        type_name = "новых ответов" if view_type == 'new' else "завершенных заданий"
        
        # ★★ ИСПРАВЛЕНИЕ: Создаем клавиатуру с актуальными данными
        from database import get_feedback_counts
        new_count, completed_count = get_feedback_counts(user_id, arc_id)
        
        message = f"📭 **Нет {type_name} в части '{arc_title}'.**\n\n"
        message += f"📊 **Актуальная статистика:**\n"
        if new_count > 0:
            message += f"• 🟡 Новые ответы: {new_count}\n"
        message += f"• ✅ Завершенные задания: {completed_count}\n\n"
        message += "👇 **Выберите другой раздел:**"
        
        keyboard = []
        
        if new_count > 0:
            keyboard.append([f"🟡 Новые ответы ({new_count})"])
        
        keyboard.append([f"✅ Завершенные задания ({completed_count})"])
        keyboard.append(["🔙 Назад к частям"])
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # Формируем сообщение
    type_name = "🟡 НОВЫЕ ОТВЕТЫ" if view_type == 'new' else "✅ ЗАВЕРШЕННЫЕ ЗАДАНИЯ"
    message = f"**{type_name}**\n\n"
    message += f"**Часть:** {arc_title}\n"
    message += f"**Найдено:** {len(assignments)} заданий\n\n"
    
    # Создаем клавиатуру
    keyboard = []
    
    for i, (assignment_title, day_title, day_num, comment, answer, assignment_id, has_additional_comment) in enumerate(assignments[:15]):
        clean_title = assignment_title

        # ★★ ИЗМЕНЕНИЕ: Оставляем полное название, только сокращаем если слишком длинное
        if assignment_title:
            # Если название слишком длинное, показываем в формате "День X: краткое описание"
            if len(clean_title) > 50:
                # Пробуем извлечь день из названия для более информативного отображения
                if " - " in clean_title:
                    parts = clean_title.split(" - ")
                    if len(parts) == 2:
                        # Формат: "День X: краткое..."
                        day_part = parts[0]
                        task_part = parts[1]
                        if len(task_part) > 30:
                            task_part = task_part[:27] + "..."
                        clean_title = f"{day_part}: {task_part}"
                    else:
                        # Просто обрезаем
                        clean_title = clean_title[:47] + "..."
                else:
                    # Просто обрезаем
                    clean_title = clean_title[:47] + "..."
        
        # Добавляем маркер для заданий с доп. комментариями
        if has_additional_comment:
            btn_text = f"💬 {clean_title}"
        else:
            btn_text = f"📝 {clean_title}"
            
        keyboard.append([btn_text])
        
        if 'feedback_assignments_map' not in context.user_data:
            context.user_data['feedback_assignments_map'] = {}
        
        context.user_data['feedback_assignments_map'][btn_text] = {
            'assignment_id': assignment_id,
            'assignment_title': assignment_title,
            'day_title': day_title,
            'day_num': day_num,
            'view_type': view_type,
            'has_additional_comment': bool(has_additional_comment)
        }
    
    keyboard.append(["🔙 Назад к частям"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_feedback_assignment_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали ответа психолога на задание - ИСПРАВЛЕННАЯ"""
    user_id = update.message.from_user.id
    text = update.message.text
    
    print(f"🔍 Обработка кнопки задания: '{text}'")
    print(f"🔍 feedback_assignments_map: {list(context.user_data.get('feedback_assignments_map', {}).keys())}")
    
    assignment_data = context.user_data.get('feedback_assignments_map', {}).get(text)
    
    if not assignment_data:
        await update.message.reply_text("❌ Задание не найдено в списке")
        return
    
    assignment_id = assignment_data['assignment_id']
    assignment_title = assignment_data['assignment_title']
    day_title = assignment_data['day_title']
    day_num = assignment_data['day_num']
    view_type = assignment_data.get('view_type', 'completed')
    has_additional_comment = assignment_data.get('has_additional_comment', False)
    
    print(f"🔍 Данные задания: id={assignment_id}, title={assignment_title}, view_type={view_type}")
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT upa.answer_text, upa.answer_files, upa.teacher_comment,
               a.content_text, upa.submitted_at, upa.additional_comment_viewed
        FROM user_progress_advanced upa
        JOIN assignments a ON upa.assignment_id = a.assignment_id
        WHERE upa.user_id = ? AND upa.assignment_id = ?
    ''', (user_id, assignment_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text("❌ Данные ответа не найдены")
        return
    
    answer_text, answer_files, teacher_comment, content_text, submitted_at, additional_comment_viewed = result
    
    # ★★ ИСПРАВЛЕНИЕ: Если это новый комментарий и он еще не просмотрен - отмечаем как просмотренный
    if has_additional_comment and additional_comment_viewed == 0:
        from database import mark_additional_comment_as_viewed
        mark_additional_comment_as_viewed(user_id, assignment_id)
        print(f"✅ Комментарий отмечен как просмотренный для задания {assignment_id}")
    
    # Форматируем сообщение
    full_message = f"📝 {assignment_title}\n\n"
    
    if content_text:
        full_message += f"Задание:\n{content_text}\n\n"
    
    if answer_text:
        full_message += f"Ваш ответ:\n{answer_text}\n\n"
    
    if teacher_comment:
        # Разделяем автоматический и дополнительный комментарии если есть
        if "💬 Комментарий психолога:" in teacher_comment:
            parts = teacher_comment.split("💬 Комментарий психолога:")
            auto_comment = parts[0].strip()
            admin_comment = parts[1].strip() if len(parts) > 1 else ""
            
            full_message += f"Системный комментарий:\n{auto_comment}\n\n"
            if admin_comment:
                full_message += f"Комментарий психолога:\n{admin_comment}\n\n"
                # ★★ ИСПРАВЛЕНИЕ: Добавляем отметку о новом комментарии
                if has_additional_comment and additional_comment_viewed == 0:
                    full_message += f"🆕 Новый комментарий психолога!\n\n"
        else:
            full_message += f"💬 Комментарий психолога:\n{teacher_comment}\n\n"
    
    full_message += f"📅 Отправлено: {submitted_at[:10] if submitted_at else 'Не указано'}"
    
    # Показываем медиа задания если есть
    from database import get_assignment_media
    media_data = get_assignment_media(assignment_id)

    # Фото задания
    if media_data and media_data.get('photos'):
        photos = media_data['photos']
        if isinstance(photos, list) and photos:
            for i, photo_id in enumerate(photos[:5], 1):
                try:
                    await update.message.reply_photo(
                        photo=photo_id,
                        caption=f"🖼️ Фото {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки фото {i}: {e}")

    # Аудио задания
    if media_data and media_data.get('audios'):
        audios = media_data['audios']
        if isinstance(audios, list) and audios:
            for i, audio_id in enumerate(audios[:3], 1):
                try:
                    await update.message.reply_audio(
                        audio=audio_id,
                        caption=f"🎵 Аудио {i} к заданию"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки аудио {i}: {e}")

    # Видео задания
    if media_data and media_data.get('video_url'):
        video_url = media_data['video_url']
        if video_url and video_url.strip():
            await update.message.reply_text(f"🎬 **Видео к заданию:**\n{video_url}")
    
    # Сохраняем данные для консультации
    context.user_data['current_feedback_data'] = {
        'title': assignment_title,
        'day': day_title,
        'day_num': day_num,
        'arc_title': context.user_data.get('current_feedback_arc_title', '')
    }
    
    # СОЗДАЕМ КЛАВИАТУРУ - ИСПРАВЛЕННАЯ
    keyboard = []
    
    # ★★ ИСПРАВЛЕНИЕ: Используем view_type вместо viewed
    if view_type == 'new':
        keyboard.append(["🟡 Новые ответы"])
    else:
        keyboard.append(["✅ Завершенные задания"])
    
    keyboard.append(["💬 Личная консультация"])
    keyboard.append(["🔙 Назад к частям"])
    keyboard.append(["🔙 В главное меню"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Отправляем фото ответа если есть
    if answer_files:
        try:
            files_list = json.loads(answer_files)
            for i, file_id in enumerate(files_list[:3], 1):
                try:
                    await update.message.reply_photo(
                        photo=file_id,
                        caption=f"📎 Ваше фото {i}"
                    )
                except:
                    try:
                        await update.message.reply_document(
                            document=file_id,
                            caption=f"📎 Файл {i} от вас"
                        )
                    except:
                        await update.message.reply_text(f"📎 Фото {i} (не удалось загрузить)")
        except Exception as e:
            print(f"🚨 Ошибка загрузки файлов ответа: {e}")
    
    # Отправляем основное сообщение
    if len(full_message) > 4000:
        parts = split_message(full_message)
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                clean_part = clean_markdown_text(part)
                await update.message.reply_text(clean_part, reply_markup=reply_markup, parse_mode=None)
            else:
                clean_part = clean_markdown_text(part)
                await update.message.reply_text(clean_part, parse_mode=None)
    else:
        clean_message = clean_markdown_text(full_message)
        await update.message.reply_text(clean_message, reply_markup=reply_markup, parse_mode=None)

async def show_training_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Каталог тренинга - скрывает пробный доступ если он уже был использован"""
    context.user_data['current_section'] = 'training_catalog'
    
    user_id = update.message.from_user.id
    from database import get_user_company, get_company_arc, get_user_access_type, is_trial_access_active
    
    # Проверяем компанию пользователя
    user_company = get_user_company(user_id)
    
    if user_company:
        company_arc = get_company_arc(user_company['company_id'])
        
        if company_arc:
            company_arc_id = company_arc['company_arc_id']
            
            message = f"🎯 **Каталог тренинга компании '{user_company['name']}'**\n\n"
            message += f"🏢 **Компания:** {user_company['name']}\n"
            message += f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n"
            message += f"💰 **Цена доступа:** {user_company['price']}₽\n\n"
            
            access_type = get_user_access_type(user_id, company_arc_id)
            
            if access_type == 'trial':
                # Проверяем активность пробного доступа
                trial_active, days_left = is_trial_access_active(user_id, company_arc_id)
                
                if trial_active:
                    message += f"🎁 **У вас активен пробный доступ!**\n\n"
                    message += f"⏳ **Осталось дней:** {days_left}\n\n"
                    message += "Вы можете продолжить обучение в разделе '📚 Мои задания'.\n"
                    message += "Для доступа ко всем 56 дням приобретите полный доступ."
                    
                    keyboard = [
                        ["📚 Мои задания"],
                        ["💰 Купить полный доступ"],  # Только полный доступ
                        ["📖 Всё о тренинге"],
                        ["🔙 В главное меню"]
                    ]
                else:
                    message += "🎁 **Ваш пробный доступ завершен**\n\n"
                    message += "Для продолжения обучения приобретите полный доступ.\n"
                    message += "Ваш прогресс сохранится после покупки."
                    
                    keyboard = [
                        ["💰 Купить полный доступ"],  # Только полный доступ
                        ["📖 Всё о тренинге"],
                        ["🔙 В главное меню"]
                    ]
            
            elif access_type == 'paid':
                message += "✅ **У вас уже есть полный доступ к тренингу!**\n\n"
                message += "Перейдите в раздел '📚 Мои задания' для продолжения обучения."
                keyboard = [
                    ["📚 Мои задания"],
                    ["📖 Всё о тренинге"],
                    ["🔙 В главное меню"]
                ]
            
            else:
                # Нет доступа - показываем обе кнопки
                message += "❌ **У вас нет доступа к тренингу компании**\n\n"
                message += "Выберите тип доступа:"
                keyboard = [
                    ["🎁 Пробный доступ(3 дня)"],
                    ["💰 Купить полный доступ"],
                    ["📖 Всё о тренинге"],
                    ["🔙 В главное меню"]
                ]
        
        else:
            message = f"⚠️ **У компании '{user_company['name']}' нет активного тренинга!**\n\n"
            message += "Обратитесь к администратору компании для настройки тренинга."
            keyboard = [["🔙 В главное меню"]]
    
    else:
        message = "🎯 **Каталог тренинга 'Себя верни себе'**\n\n"
        message += "⚠️ **Вы не состоите в компании!**\n\n"
        message += "Для покупки доступа сначала присоединитесь к компании через профиль."
        keyboard = [["🔙 В главное меню"]]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

def get_current_and_future_arcs():
    """Получает текущую и будущие дуги для покупки"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Получаем ВСЕ дуги, кроме "О курсе" (arc_id = 0)
        cursor.execute('''
            SELECT arc_id, title, дата_начала, дата_окончания, price
            FROM arcs 
            WHERE arc_id > 0
            ORDER BY arc_id
        ''')
        
        arcs = cursor.fetchall()
        
        # Определяем текущую дугу (по датам)
        current_arc = None
        future_arcs = []
        past_arcs = []
        
        today = datetime.now().date()
        
        for arc in arcs:
            arc_id, title, start_date, end_date, price = arc
            
            # Конвертируем даты если нужно
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date).date()
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date).date()
            
            if start_date <= today <= end_date:
                current_arc = (arc_id, title, price, "ТЕКУЩАЯ")
            elif today < start_date:
                future_arcs.append((arc_id, title, price, "БУДУЩАЯ"))
            else:
                past_arcs.append((arc_id, title, price, "ПРОШЕДШАЯ"))
        
        return {
            'current': current_arc,
            'future': future_arcs,
            'past': past_arcs,
            'all': arcs
        }
        
    except Exception as e:
        print(f"🚨 Ошибка получения дуг: {e}")
        return None
    finally:
        conn.close()

async def buy_arc_from_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о части и предлагает купить"""
    text = update.message.text
    print(f"🔍 buy_arc_from_catalog вызван с текстом: '{text}'")
    
    # Получаем данные из mapping
    if 'available_arcs' in context.user_data and text in context.user_data['available_arcs']:
        arc_info = context.user_data['available_arcs'][text]
        
        # ★★★ ВАЖНО: Сохраняем arc_id для покупки ★★★
        context.user_data['current_arc_catalog'] = arc_info['arc_id']
        
        arc_title = arc_info['title']
        arc_price = arc_info['price']
        arc_start = arc_info['дата_начала']
        arc_status = arc_info['status']
        
        # Формируем сообщение
        message = f"🔄 **{arc_title}**\n\n"
        
        if arc_status == 'активный':
            message += f"📅 **Старт:** {arc_start}\n"
            message += f"💰 **Цена:** {arc_price}₽\n\n"
            message += "✅ **Доступен пробный период 3 дня**\n\n"
            message += "**Варианты доступа:**\n"
            message += "1. 🎁 **Пробный доступ** - первые 3 дня бесплатно\n"
            message += "2. 💰 **Полный доступ** - весь тренинг\n\n"
            message += "Выберите вариант:"
            
            keyboard = [
                ["🎁 Пробный доступ(3 дня)"],
                ["💰 Купить полный доступ"],
                ["🔙 Назад в каталог"]
            ]
            
        elif arc_status == 'будущий':
            message += f"📅 **Старт:** {arc_start}\n"
            message += f"💰 **Цена:** {arc_price}₽\n\n"
            message += "⏳ **Тренинг еще не начался**\n\n"
            message += "**Вы можете купить доступ заранее:**\n"
            message += "• Полный доступ ко всему тренингу\n"
            message += "• Задания откроются в день старта\n\n"
            message += "Выберите вариант:"
            
            keyboard = [
                ["💰 Купить доступ заранее"],
                ["🔙 Назад в каталог"]
            ]
        
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Ошибка: часть не найдена")
    
# Webhook обработчик для Юкассы
async def yookassa_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик webhook от Юкассы"""
    try:
        data = json.loads(update.message.text)
        logger.info(f"Получен webhook от Юкассы: {data}")
        
        from database import handle_yookassa_webhook
        success, message = handle_yookassa_webhook(data)
        
        if success:
            logger.info(f"Webhook обработан успешно: {message}")
            return {'status': 'ok', 'message': message}
        else:
            logger.error(f"Ошибка обработки webhook: {message}")
            return {'status': 'error', 'message': message}
            
    except Exception as e:
        logger.error(f"Ошибка в webhook обработчике: {e}")
        return {'status': 'error', 'message': str(e)}

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки статуса платежей - ИСПРАВЛЕННАЯ"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Эта команда только для администраторов")
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Сначала проверим какие колонки есть в таблице
        cursor.execute("PRAGMA table_info(payments)")
        columns = [col[1] for col in cursor.fetchall()]
        logger.info(f"Колонки в payments: {columns}")
        
        # Если есть колонка 'id' вместо 'payment_id'
        if 'id' in columns and 'payment_id' not in columns:
            # Используем 'id' как идентификатор
            cursor.execute('''
                SELECT id, user_id, arc_id, amount, status, yookassa_payment_id, created_at
                FROM payments 
                ORDER BY created_at DESC 
                LIMIT 10
            ''')
        elif 'payment_id' in columns:
            # Используем 'payment_id'
            cursor.execute('''
                SELECT payment_id, user_id, arc_id, amount, status, yookassa_payment_id, created_at
                FROM payments 
                ORDER BY created_at DESC 
                LIMIT 10
            ''')
        else:
            # Таблица может быть пустой или не создана
            await update.message.reply_text("📭 Таблица платежей не создана или пустая")
            conn.close()
            return
        
        payments = cursor.fetchall()
        
        if not payments:
            await update.message.reply_text("📭 Нет платежей в истории")
            conn.close()
            return
        
        message = "📋 **Последние платежи:**\n\n"
        
        for payment in payments:
            # Определяем структуру платежа
            if len(payment) >= 7:
                # Если первая колонка - id
                if isinstance(payment[0], int):
                    payment_id, user_id, arc_id, amount, status, yookassa_id, created_at = payment
                else:
                    # Пропускаем некорректные записи
                    continue
            else:
                continue
            
            # Получаем информацию о дуге
            cursor.execute('SELECT title FROM arcs WHERE arc_id = ?', (arc_id,))
            arc_result = cursor.fetchone()
            arc_title = arc_result[0] if arc_result else f"Часть {arc_id}"
            
            status_icon = {
                'pending': '⏳',
                'succeeded': '✅',
                'canceled': '❌'
            }.get(status, '❓')
            
            message += f"{status_icon} **ID:** {payment_id}\n"
            message += f"👤 **User:** {user_id}\n"
            message += f"💰 **Сумма:** {amount}₽\n"
            message += f"🔄 **Часть:** {arc_title}\n"
            message += f"📊 **Статус:** {status}\n"
            message += f"📅 **Создан:** {created_at[:19] if created_at else 'N/A'}\n"
            if yookassa_id:
                message += f"🔗 **Юкасса:** `{yookassa_id[:15]}...`\n"
            message += "━━━━━━━━━━━━━━━━\n\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в check_payment_status: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()

async def test_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для проверки платежей"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Создаем тестовый платеж
    test_arc_id = 1
    test_amount = 100  # Пробный доступ
    
    from database import create_yookassa_payment
    payment_url, payment_id = create_yookassa_payment(
        user_id, test_arc_id, test_amount, True, "Тестовый платеж"
    )
    
    if payment_url:
        await update.message.reply_text(
            f"✅ Тестовый платеж создан\n"
            f"💰 Сумма: {test_amount}₽\n"
            f"🔗 URL: {payment_url}\n"
            f"📝 ID: {payment_id}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ Ошибка: {payment_id}")

async def test_payment_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тест платежа - создает платеж 100₽ для тестирования"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Используем Часть 1 для теста
    test_arc_id = 1
    test_amount = 100  # Пробный доступ
    
    from database import create_yookassa_payment
    payment_url, payment_id = create_yookassa_payment(
        user_id, test_arc_id, test_amount, True, "ТЕСТОВЫЙ ПЛАТЕЖ"
    )
    
    if payment_url:
        keyboard = [
            [InlineKeyboardButton("💳 Тестовая оплата", url=payment_url)],
            [InlineKeyboardButton("✅ Я оплатил (тест)", callback_data=f"check_payment_{payment_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"🧪 **ТЕСТОВЫЙ ПЛАТЕЖ**\n\n"
            f"💰 Сумма: {test_amount}₽ (пробный доступ)\n"
            f"🔗 Юкасса: {payment_url[:50]}...\n"
            f"📝 ID: `{payment_id}`\n\n"
            f"**Тестовая карта Юкассы:**\n"
            f"• Номер: `5555 5555 5555 4444`\n"
            f"• Срок: 12/34\n"
            f"• CVC: 123\n"
            f"• Имя: TEST TEST\n\n"
            f"После оплаты нажми '✅ Я оплатил (тест)'",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ Ошибка: {payment_id}")

async def check_db_structure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает структуру таблицы payments (упрощенная)"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Показываем только таблицу payments
        message = "📊 **Таблица payments:**\n\n"
        
        cursor.execute("PRAGMA table_info(payments)")
        columns = cursor.fetchall()
        
        if not columns:
            message += "❌ Таблица не существует\n"
        else:
            for col in columns:
                col_id, col_name, col_type, notnull, default_val, pk = col
                pk_mark = " 🔑" if pk else ""
                message += f"• `{col_name}` ({col_type}){pk_mark}\n"
        
        # Проверяем есть ли данные
        cursor.execute("SELECT COUNT(*) FROM payments")
        count = cursor.fetchone()[0]
        message += f"\n📊 Записей в таблице: {count}"
        
        if count > 0:
            cursor.execute("SELECT status, COUNT(*) FROM payments GROUP BY status")
            statuses = cursor.fetchall()
            message += "\n📈 По статусам:\n"
            for status, cnt in statuses:
                message += f"  • {status}: {cnt}\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в check_db_structure: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()

async def create_payments_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает таблицу payments если её нет"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            arc_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            yookassa_payment_id TEXT UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            metadata TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (arc_id) REFERENCES arcs(arc_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ Таблица payments создана/проверена")

async def show_tables(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех таблиц в БД"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        message = "🗂️ **Таблицы в базе данных:**\n\n"
        
        for table in tables:
            table_name = table[0]
            
            # Получаем количество записей
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                message += f"• `{table_name}` - {count} записей\n"
            except:
                message += f"• `{table_name}` - ошибка подсчета\n"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Ошибка в show_tables: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()

async def test_payment_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный тест платежной системы"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    message = "🧪 **ТЕСТ ПЛАТЕЖНОЙ СИСТЕМЫ**\n\n"
    
    # 1. Проверяем таблицу payments
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Проверяем существует ли таблица
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payments'")
    payments_exists = cursor.fetchone()
    
    if not payments_exists:
        message += "❌ Таблица `payments` не существует\n"
        # Создаем таблицу
        try:
            cursor.execute('''
                CREATE TABLE payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    arc_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT DEFAULT 'pending',
                    yookassa_payment_id TEXT UNIQUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
            ''')
            conn.commit()
            message += "✅ Таблица `payments` создана\n"
        except Exception as e:
            message += f"❌ Ошибка создания таблицы: {str(e)}\n"
    else:
        message += "✅ Таблица `payments` существует\n"
    
    # 2. Проверяем структуру
    cursor.execute("PRAGMA table_info(payments)")
    columns = cursor.fetchall()
    column_names = [col[1] for col in columns]
    
    message += f"📊 Колонки: {', '.join(column_names)}\n"
    
    # 3. Проверяем тестовые ключи Юкассы
    from config import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY
    
    if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
        if "test_" in YOOKASSA_SECRET_KEY:
            message += "✅ Тестовые ключи Юкассы настроены\n"
        else:
            message += "⚠️ Ключи Юкассы могут быть рабочими (не тестовые)\n"
    else:
        message += "❌ Ключи Юкассы не настроены в config.py\n"
    
    # 4. Проверяем есть ли тестовые платежи
    cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'succeeded'")
    succeeded_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
    pending_count = cursor.fetchone()[0]
    
    message += f"\n📈 **Статистика платежей:**\n"
    message += f"• Успешных: {succeeded_count}\n"
    message += f"• Ожидающих: {pending_count}\n"
    message += f"• Всего: {succeeded_count + pending_count}\n"
    
    conn.close()
    
    # 5. Инструкция для теста
    message += "\n🎯 **Инструкция для теста:**\n"
    message += "1. Нажми `Пробный доступ (100₽)` в разделе покупки\n"
    message += "2. Оплати тестовой картой: `5555 5555 5555 4444`\n"
    message += "3. Нажми `✅ Я оплатил` в боте\n"
    message += "4. Проверь доступ командой `/myaccess`\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def recreate_payments_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пересоздает таблицу payments с правильной структурой"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # 1. Удаляем старую таблицу если существует
        cursor.execute("DROP TABLE IF EXISTS payments")
        
        # 2. Создаем новую таблицу с правильной структурой
        cursor.execute('''
            CREATE TABLE payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                arc_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                yookassa_payment_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (arc_id) REFERENCES arcs(arc_id)
            )
        ''')
        
        conn.commit()
        
        # 3. Создаем индекс для быстрого поиска
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_yookassa_id ON payments(yookassa_payment_id)')
        
        conn.commit()
        
        await update.message.reply_text(
            "✅ **Таблица payments пересоздана с правильной структурой!**\n\n"
            "Новые колонки:\n"
            "• `id` - идентификатор платежа\n"
            "• `user_id` - ID пользователя\n"  
            "• `arc_id` - ID части тренинга\n"
            "• `amount` - сумма платежа\n"
            "• `status` - статус (pending/succeeded/canceled)\n"
            "• `yookassa_payment_id` - ID платежа в Юкассе\n"
            "• `created_at` - дата создания\n"
            "• `completed_at` - дата завершения\n"
            "• `metadata` - дополнительные данные\n\n"
            "Теперь можно тестировать платежи!",
            parse_mode='Markdown'
        )
        
        logger.info("Таблица payments пересоздана с новой структурой")
        
    except Exception as e:
        logger.error(f"Ошибка пересоздания таблицы payments: {e}")
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")
    finally:
        conn.close()

async def test_yookassa_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует подключение к Юкассе - ИСПРАВЛЕННАЯ"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    from database import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_API_URL
    import requests
    import base64
    
    message = "🔑 Тест ключей Юкассы:\n\n"
    message += f"Shop ID: {YOOKASSA_SHOP_ID}\n"
    message += f"Secret Key: {YOOKASSA_SECRET_KEY[:15]}...\n"
    message += f"API URL: {YOOKASSA_API_URL}\n\n"
    
    try:
        # Теперь тестируем создание МАЛЕНЬКОГО тестового платежа (1 рубль)
        auth_string = f'{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}'
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json",
            "Idempotence-Key": str(uuid.uuid4())
        }
        
        # Тестовые данные платежа (1 рубль)
        payment_data = {
            "amount": {
                "value": "1.00",
                "currency": "RUB"
            },
            "payment_method_data": {
                "type": "bank_card"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/PersonalityGrowth_bot"
            },
            "description": "Тестовый платеж для проверки подключения",
            "capture": True
        }
        
        response = requests.post(YOOKASSA_API_URL, json=payment_data, headers=headers, timeout=10)
        
        if response.status_code == 200:
            payment_info = response.json()
            payment_id = payment_info.get("id", "N/A")
            confirmation_url = payment_info.get("confirmation", {}).get("confirmation_url", "N/A")
            
            message += "✅ **Ключи рабочие! Платеж создан!**\n"
            message += f"ID платежа: {payment_id}\n"
            message += f"URL для оплаты: {confirmation_url[:50]}...\n\n"
            message += "⚠️ **ЭТО ТЕСТОВЫЙ ПЛАТЕЖ на 1 рубль!**\n"
            message += "Не оплачивай его, просто проверь что ссылка открывается.\n"
            
            # Сразу отменяем тестовый платеж
            try:
                cancel_headers = headers.copy()
                cancel_headers["Idempotence-Key"] = str(uuid.uuid4())
                cancel_response = requests.post(
                    f"{YOOKASSA_API_URL}/{payment_id}/cancel",
                    headers=cancel_headers,
                    timeout=5
                )
                if cancel_response.status_code == 200:
                    message += "✅ Тестовый платеж отменен\n"
            except:
                message += "⚠️ Не удалось отменить тестовый платеж (не страшно)\n"
                
        elif response.status_code == 401:
            message += "❌ **Ошибка авторизации (401)**\n"
            message += "Проверь Shop ID и Secret Key\n"
        else:
            message += f"❌ Ошибка: код {response.status_code}\n"
            
            # Показываем ошибку
            try:
                error_data = response.json()
                message += f"Описание: {error_data.get('description', 'N/A')}\n"
                message += f"Код: {error_data.get('code', 'N/A')}\n"
            except:
                message += f"Ответ: {response.text[:200]}\n"
            
    except requests.exceptions.Timeout:
        message += "❌ Таймаут подключения к Юкассе\n"
    except requests.exceptions.ConnectionError:
        message += "❌ Ошибка подключения к Юкассе\n"
    except Exception as e:
        message += f"❌ Ошибка: {str(e)[:100]}\n"
    
    # Отправляем частями если длинное
    if len(message) > 4000:
        parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(message)

async def check_my_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет доступы пользователя"""
    user_id = update.message.from_user.id
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT a.arc_id, a.title, uaa.access_type
        FROM user_arc_access uaa
        JOIN arcs a ON uaa.arc_id = a.arc_id
        WHERE uaa.user_id = ?
        ORDER BY a.arc_id
    ''', (user_id,))
    
    accesses = cursor.fetchall()
    conn.close()
    
    if not accesses:
        await update.message.reply_text("📭 У вас нет доступов к частям тренинга")
        return
    
    message = "✅ **Ваши доступы:**\n\n"
    for arc_id, title, access_type in accesses:
        type_text = "пробный (3 задания)" if access_type == 'trial' else "полный"
        message += f"• {title} - {type_text}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def debug_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последний платеж пользователя"""
    user_id = update.message.from_user.id
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, arc_id, amount, status, yookassa_payment_id, created_at
        FROM payments 
        WHERE user_id = ?
        ORDER BY created_at DESC 
        LIMIT 1
    ''', (user_id,))
    
    payment = cursor.fetchone()
    conn.close()
    
    if payment:
        pid, arc_id, amount, status, yookassa_id, created_at = payment
        message = f"📋 **Последний платеж:**\n\n"
        message += f"💰 Сумма: {amount}₽\n"
        message += f"📊 Статус: {status}\n"
        message += f"📅 Дата: {created_at}\n"
        message += f"🔗 Юкасса ID: `{yookassa_id}`\n\n"
        
        # Проверяем доступ
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM user_arc_access WHERE user_id = ? AND arc_id = ?', (user_id, arc_id))
        has_access = cursor.fetchone()
        conn.close()
        
        if has_access:
            message += "✅ Доступ ВЫДАН в БД"
        else:
            message += "❌ Доступа НЕТ в БД"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text("📭 У вас нет платежей")

async def debug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все активные колбэки"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Последние 5 платежей пользователя
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('''
        SELECT yookassa_payment_id, status, created_at 
        FROM payments 
        WHERE user_id = ?
        ORDER BY created_at DESC 
        LIMIT 5
    ''', (user_id,))
    
    payments = cursor.fetchall()
    conn.close()
    
    message = "🔍 **Активные платежи для колбэков:**\n\n"
    
    for yookassa_id, status, created_at in payments:
        callback_data = f"check_payment_{yookassa_id}"
        message += f"• `{callback_data}`\n"
        message += f"  Статус: {status}, Дата: {created_at}\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def simple_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простой тест колбэка"""
    keyboard = [[
        InlineKeyboardButton("✅ Тест оплаты", callback_data="check_payment_TEST123")
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "Нажмите кнопку чтобы проверить работу колбэка:",
        reply_markup=reply_markup
    )

async def fix_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Исправляет доступ для пользователя - ОБНОВЛЕННАЯ ДЛЯ КОМПАНИЙ"""
    user_id = update.message.from_user.id
    from database import get_user_company, get_company_arc, grant_arc_access, check_user_arc_access
    
    # Проверяем компанию пользователя
    user_company = get_user_company(user_id)
    if not user_company:
        await update.message.reply_text(
            "❌ **Вы не состоите в компании!**\n\n"
            "Сначала присоединитесь к компании через профиль.",
            parse_mode='Markdown'
        )
        return
    
    # Получаем арку компании
    company_arc = get_company_arc(user_company['company_id'])
    if not company_arc:
        await update.message.reply_text("❌ У компании нет активного тренинга")
        return
    
    company_arc_id = company_arc['company_arc_id']
    
    # Проверяем статус платежа
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT status, amount FROM payments 
        WHERE user_id = ? AND company_arc_id = ? 
        ORDER BY created_at DESC LIMIT 1
    ''', (user_id, company_arc_id))
    
    payment = cursor.fetchone()
    
    if payment:
        status, amount = payment
        
        if status == 'succeeded':
            # Платеж успешный - выдаем доступ
            success = grant_arc_access(user_id, company_arc_id, 'paid')
            
            if success:
                await update.message.reply_text(
                    f"✅ **Доступ к компании '{user_company['name']}' восстановлен!**\n\n"
                    f"💰 Оплачено: {amount}₽\n"
                    f"📅 Старт: {company_arc['actual_start_date']}\n\n"
                    f"Теперь вы можете использовать раздел '📚 Мои задания'.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ **Ошибка восстановления доступа.**\n\n"
                    "Пожалуйста, обратитесь в поддержку.",
                    parse_mode='Markdown'
                )
        else:
            await update.message.reply_text(
                f"❌ **Платеж не подтвержден.**\n\n"
                f"Статус: {status}\n\n"
                f"Если вы оплатили, подождите несколько минут и нажмите '✅ Я оплатил' в чате с платежом.",
                parse_mode='Markdown'
            )
    else:
        await update.message.reply_text(
            "❌ **Не найден платеж за эту компанию.**\n\n"
            "Пожалуйста, сначала оплатите доступ через каталог тренинга.",
            parse_mode='Markdown'
        )
    
    conn.close()

async def check_tables(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет и создает таблицы если нужно"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Проверяем user_arc_access
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_arc_access (
            user_id INTEGER,
            arc_id INTEGER,
            access_type TEXT,
            PRIMARY KEY (user_id, arc_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (arc_id) REFERENCES arcs(arc_id)
        )
    ''')
    
    # Проверяем trial_assignments_access
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trial_assignments_access (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            arc_id INTEGER,
            max_assignment_order INTEGER DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(user_id),
            FOREIGN KEY (arc_id) REFERENCES arcs(arc_id),
            UNIQUE(user_id, arc_id)
        )
    ''')
    
    conn.commit()
    conn.close()
    
    await update.message.reply_text("✅ Таблицы доступа проверены/созданы")

async def debug_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус регистрации"""
    user_id = update.message.from_user.id
    
    from database import get_user_offer_status
    status = get_user_offer_status(user_id)
    
    message = f"🔍 **Статус регистрации user_id={user_id}:**\n\n"
    message += f"✅ Оферта: {'принята' if status['accepted_offer'] else 'не принята'}\n"
    message += f"📱 Телефон: {status['phone'] or 'нет'}\n"
    message += f"📝 ФИО: {'есть' if status['has_fio'] else 'нет'}\n"
    
    # Покажем что в БД
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT accepted_offer, phone, fio FROM users WHERE user_id = ?', (user_id,))
    db_data = cursor.fetchone()
    conn.close()
    
    if db_data:
        message += f"\n📊 **Данные в БД:**\n"
        message += f"accepted_offer: {db_data[0]}\n"
        message += f"phone: {db_data[1]}\n"
        message += f"fio: {db_data[2]}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def reset_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает регистрацию для тестирования"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Сбрасываем данные регистрации
    cursor.execute('''
        UPDATE users 
        SET accepted_offer = 0,
            phone = NULL,
            fio = NULL
        WHERE user_id = ?
    ''', (user_id,))
    
    conn.commit()
    conn.close()
    
    # Очищаем user_data
    context.user_data.clear()
    
    await update.message.reply_text("✅ Регистрация сброшена. Начните заново.")

async def debug_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий статус регистрации и user_data"""
    user_id = update.message.from_user.id
    
    from database import get_user_offer_status
    status = get_user_offer_status(user_id)
    
    message = f"🧭 **Текущий поток регистрации:**\n\n"
    message += f"user_id: {user_id}\n"
    message += f"✅ Оферта: {'ДА' if status['accepted_offer'] else 'НЕТ'}\n"
    message += f"📱 Телефон: {'ДА' if status['has_phone'] else 'НЕТ'} ({status['phone']})\n"
    message += f"📝 ФИО: {'ДА' if status['has_fio'] else 'НЕТ'}\n\n"
    
    message += f"📋 **user_data:**\n"
    for key, value in context.user_data.items():
        message += f"  {key}: {value}\n"
    
    await update.message.reply_text(message)

async def start_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс создания уведомления"""
    context.user_data['notification_stage'] = 'select_recipients'
    
    keyboard = [
        ["📢 Всем в бот"],
        ["✅ Только полный доступ"],
        ["🎁 Только пробный доступ"],
        ["🔙 Назад к инструментам"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🔔 **Отправка уведомления**\n\n"
        "Выберите получателей:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )


async def handle_notification_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает создание уведомления"""
    text = update.message.text
    
    # 1. Выбор получателей
    if context.user_data.get('notification_stage') == 'select_recipients':
        recipient_types = {
            "📢 Всем в бот": "all",
            "✅ Только полный доступ": "full",
            "🎁 Только пробный доступ": "trial"
        }
        
        if text in recipient_types:
            context.user_data['notification_recipients'] = recipient_types[text]
            context.user_data['notification_stage'] = 'waiting_content'
            
            await update.message.reply_text(
                "✏️ **Напишите уведомление одним сообщением.**\n\n"
                "Можно прикрепить:\n"
                "• Текст\n"
                "• Текст + фото\n"
                "• Текст + файл\n\n"
                "Отправьте сообщение как обычно в Telegram.",
                reply_markup=ReplyKeyboardMarkup([["🔙 Отменить"]], resize_keyboard=True),
                parse_mode='Markdown'
            )
            return
    
    # 2. Обработка отправленного контента
    elif context.user_data.get('notification_stage') == 'waiting_content':
        # Здесь будем обрабатывать текст/фото в отдельной функции
        await process_notification_content(update, context)
        return
    
    # 3. Подтверждение отправки
    elif context.user_data.get('notification_stage') == 'preview':
        if text == "📤 Отправить":
            await send_notification_final(update, context)
        elif text == "✏️ Изменить":
            context.user_data['notification_stage'] = 'waiting_content'
            await update.message.reply_text(
                "✏️ Отправьте новое сообщение с уведомлением:",
                reply_markup=ReplyKeyboardMarkup([["🔙 Отменить"]], resize_keyboard=True)
            )
        elif text == "❌ Отменить":
            await admin_tools_menu(update, context)

async def process_notification_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает контент уведомления (текст + медиа)"""

    # Если нажата кнопка "Отменить" - обрабатываем отдельно
    if update.message.text == "🔙 Отменить":
        # Очищаем все данные
        keys_to_remove = []
        for key in context.user_data.keys():
            if key.startswith('notification_'):
                keys_to_remove.append(key)
        
        for key in keys_to_remove:
            context.user_data.pop(key, None)
        
        await admin_tools_menu(update, context)
        return
    
    # ВАЖНО: Проверяем caption (текст прикрепленный к фото/документу)
    if update.message.caption:
        context.user_data['notification_text'] = update.message.caption
    
    # Проверяем обычный текст (если отправлен без медиа)
    elif update.message.text and update.message.text != "🔙 Отменить":
        context.user_data['notification_text'] = update.message.text
    
    # Сохраняем фото если есть
    if update.message.photo:
        context.user_data['notification_photo'] = update.message.photo[-1].file_id
    
    # Сохраняем документ если есть  
    if update.message.document:
        context.user_data['notification_document'] = update.message.document.file_id
    
    # Проверяем, есть ли какой-то контент
    has_content = ('notification_text' in context.user_data or 
                   'notification_photo' in context.user_data or 
                   'notification_document' in context.user_data)
    
    if not has_content:
        await update.message.reply_text(
            "❌ Вы не отправили контент для уведомления. Попробуйте снова.",
            reply_markup=ReplyKeyboardMarkup([["🔙 Отменить"]], resize_keyboard=True)
        )
        return
    
    # Получаем количество получателей
    from database import get_users_for_notification
    recipient_type = context.user_data.get('notification_recipients', 'all')
    users = get_users_for_notification(recipient_type)
    
    # Показываем предпросмотр
    context.user_data['notification_stage'] = 'preview'
    context.user_data['notification_users'] = users
    
    keyboard = [
        ["📤 Отправить"],
        ["✏️ Изменить"],
        ["❌ Отменить"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Формируем сообщение о предпросмотре
    message_text = f"✅ **Уведомление зафиксировано!**\n\n"
    message_text += f"**Получателей:** {len(users)} человек\n"
    
    recipient_names = {
        'all': 'Все участники',
        'full': 'Только полный доступ',
        'trial': 'Только пробный доступ'
    }
    message_text += f"**Фильтр:** {recipient_names.get(recipient_type, 'Все участники')}\n"
    
    # Добавляем информацию о типе контента
    content_type = []
    if 'notification_text' in context.user_data:
        content_type.append("текст")
    if 'notification_photo' in context.user_data:
        content_type.append("фото")
    if 'notification_document' in context.user_data:
        content_type.append("файл")
    
    if content_type:
        message_text += f"**Контент:** {', '.join(content_type)}\n"
    
    message_text += "\n**Предпросмотр вашего уведомления:**"
    
    await update.message.reply_text(
        message_text,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Показываем как выглядит уведомление
    try:
        if 'notification_photo' in context.user_data:
            caption = context.user_data.get('notification_text', '')
            await update.message.reply_photo(
                photo=context.user_data['notification_photo'],
                caption=caption if caption else None,
                parse_mode='Markdown' if caption else None
            )
        elif 'notification_document' in context.user_data:
            caption = context.user_data.get('notification_text', '')
            await update.message.reply_document(
                document=context.user_data['notification_document'],
                caption=caption if caption else None,
                parse_mode='Markdown' if caption else None
            )
        elif 'notification_text' in context.user_data:
            text = context.user_data['notification_text']
            # Разбиваем длинные тексты
            if len(text) > 4000:
                parts = split_message(text)
                for part in parts:
                    await update.message.reply_text(part, parse_mode='Markdown')
            else:
                await update.message.reply_text(text, parse_mode='Markdown')
    except Exception as e:
        print(f"🚨 Ошибка при показе предпросмотра: {e}")
        await update.message.reply_text(
            "⚠️ Не удалось показать предпросмотр, но уведомление сохранено.",
            reply_markup=reply_markup
        )

async def send_notification_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет уведомление всем получателям"""
    users = context.user_data.get('notification_users', [])
    text = context.user_data.get('notification_text', '')
    photo = context.user_data.get('notification_photo')
    document = context.user_data.get('notification_document')
    
    if not users:
        await update.message.reply_text("❌ Нет получателей для отправки")
        return
    
    success = 0
    failed = 0
    failed_users = []  # Для логирования
    
    await update.message.reply_text(f"📤 Отправляю уведомление {len(users)} пользователям...")
    
    for user_id, fio, username in users:
        try:
            if photo:
                # Отправляем фото с текстом (caption)
                await context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption=text or None,  # caption может быть пустым
                    parse_mode='Markdown' if text else None
                )
            elif document:
                # Отправляем документ с текстом (caption)
                await context.bot.send_document(
                    chat_id=user_id,
                    document=document,
                    caption=text or None,
                    parse_mode='Markdown' if text else None
                )
            elif text:
                # Отправляем только текст
                if len(text) > 4000:
                    # Разбиваем длинные тексты
                    parts = split_message(text)
                    for i, part in enumerate(parts):
                        if i == 0:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=part,
                                parse_mode='Markdown'
                            )
                        else:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"📋 (продолжение)\n\n{part}",
                                parse_mode='Markdown'
                            )
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=text,
                        parse_mode='Markdown'
                    )
            success += 1
            
            # Делаем небольшую задержку чтобы не превысить лимиты Telegram
            if success % 20 == 0:
                import asyncio
                await asyncio.sleep(1)
                
        except Exception as e:
            print(f"🚨 Ошибка отправки {user_id}: {e}")
            failed += 1
            failed_users.append(str(user_id))
    
    # Сохраняем лог
    from database import save_notification_log
    admin_id = update.message.from_user.id
    recipient_type = context.user_data.get('notification_recipients', 'all')
    
    save_notification_log(
        admin_id=admin_id,
        recipient_type=recipient_type,
        text=text,
        photo_id=photo,
        success_count=success,
        fail_count=failed
    )
    
    # Очищаем данные
    for key in ['notification_stage', 'notification_recipients', 'notification_text',
                'notification_photo', 'notification_document', 'notification_users']:
        context.user_data.pop(key, None)
    
    # Показываем результат
    result_text = f"✅ **Рассылка завершена!**\n\n"
    result_text += f"📊 **Результат:**\n"
    result_text += f"• ✅ Успешно: {success}\n"
    result_text += f"• ❌ Не доставлено: {failed}\n"
    result_text += f"• 👥 Всего: {len(users)}\n"
    
    if failed > 0 and len(failed_users) > 0:
        result_text += f"\n⚠️ **Не доставлено пользователям:**\n"
        result_text += f"{', '.join(failed_users[:10])}"  # Показываем только первые 10
        if len(failed_users) > 10:
            result_text += f" и еще {len(failed_users) - 10}"
    
    await update.message.reply_text(
        result_text,
        parse_mode='Markdown'
    )
    
    await admin_tools_menu(update, context)


async def update_database_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ПОЛНОЕ обновление БД: создает все таблицы, добавляет колонки, сохраняет данные"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администраторов")
        return
    
    import os
    import time
    
    # Создаем backup перед изменениями
    backup_name = f"mentor_bot.db.backup_{int(time.time())}"
    
    try:
        import shutil
        shutil.copy2('mentor_bot.db', backup_name)
        logger.info(f"✅ Создан backup: {backup_name}")
    except Exception as e:
        logger.error(f"❌ Не удалось создать backup: {e}")
    
    conn = None
    try:
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        
        steps = []
        step_number = 1
        
        # === 1. ОСНОВНЫЕ ТАБЛИЦЫ ПОЛЬЗОВАТЕЛЕЙ И СТРУКТУРЫ ===
        
        # 1.1 Таблица users (добавляем недостающие колонки)
        cursor.execute("PRAGMA table_info(users)")
        user_columns = [col[1] for col in cursor.fetchall()]
        
        required_user_columns = [
            ('accepted_offer', 'BOOLEAN DEFAULT 0'),
            ('phone', 'TEXT'),
            ('accepted_service_offer', 'BOOLEAN DEFAULT 0'),
            ('accepted_offer_date', 'TIMESTAMP'),
            ('accepted_service_offer_date', 'TIMESTAMP'),
            ('is_blocked', 'BOOLEAN DEFAULT 0')
        ]
        
        for col_name, col_type in required_user_columns:
            if col_name not in user_columns:
                try:
                    cursor.execute(f'ALTER TABLE users ADD COLUMN {col_name} {col_type}')
                    steps.append(f"{step_number}. ✅ Добавлена колонка `{col_name}` в users")
                    step_number += 1
                except Exception as e:
                    steps.append(f"{step_number}. ⚠️ Не удалось добавить `{col_name}`: {str(e)[:50]}")
                    step_number += 1
        
        # === 2. ТАБЛИЦЫ ДОСТУПА И ПЛАТЕЖЕЙ ===
        
        # 2.1 Таблица user_arc_access
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_arc_access (
                user_id INTEGER,
                arc_id INTEGER,
                access_type TEXT,
                purchased_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP,
                PRIMARY KEY (user_id, arc_id),
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (arc_id) REFERENCES arcs(arc_id)
            )
        ''')
        steps.append(f"{step_number}. ✅ Таблица `user_arc_access` создана/проверена")
        step_number += 1
        
        # 2.2 Таблица trial_assignments_access
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS trial_assignments_access (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                arc_id INTEGER,
                max_assignment_order INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (arc_id) REFERENCES arcs(arc_id),
                UNIQUE(user_id, arc_id)
            )
        ''')
        steps.append(f"{step_number}. ✅ Таблица `trial_assignments_access` создана/проверена")
        step_number += 1
        
        # 2.3 Таблица payments (аккуратная миграция)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payments'")
        payments_exists = cursor.fetchone()
        
        if payments_exists:
            # Проверяем структуру существующей таблицы
            cursor.execute("PRAGMA table_info(payments)")
            payments_columns = [col[1] for col in cursor.fetchall()]
            
            required_payments_columns = ['arc_id', 'amount', 'status', 'yookassa_payment_id']
            
            if not all(col in payments_columns for col in required_payments_columns):
                # Сохраняем старые данные если есть
                cursor.execute("SELECT COUNT(*) FROM payments")
                old_count = cursor.fetchone()[0]
                
                if old_count > 0:
                    # Создаем временную таблицу для сохранения данных
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS payments_backup (
                            user_id INTEGER,
                            course_id INTEGER,
                            paid_at TIMESTAMP
                        )
                    ''')
                    
                    # Копируем данные
                    cursor.execute('INSERT INTO payments_backup SELECT * FROM payments')
                    steps.append(f"{step_number}. ⚠️ Сохранено {old_count} старых платежей в backup")
                    step_number += 1
                
                # Удаляем старую таблицу
                cursor.execute('DROP TABLE payments')
                steps.append(f"{step_number}. 🔄 Удалена старая таблица payments")
                step_number += 1
        
        # Создаем новую таблицу payments
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                arc_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                yookassa_payment_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                metadata TEXT,
                trial BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (arc_id) REFERENCES arcs(arc_id)
            )
        ''')
        steps.append(f"{step_number}. ✅ Таблица `payments` создана с новой структурой")
        step_number += 1
        
        # 2.4 Таблица free_access_grants
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS free_access_grants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                arc_id INTEGER,
                granted_by TEXT,
                granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (arc_id) REFERENCES arcs(arc_id)
            )
        ''')
        steps.append(f"{step_number}. ✅ Таблица `free_access_grants` создана/проверена")
        step_number += 1
        
        # === 3. ТАБЛИЦЫ ДЛЯ УВЕДОМЛЕНИЙ ===
        
        # 3.1 Таблица notifications
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                day_num INTEGER,
                text TEXT,
                image_url TEXT,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        steps.append(f"{step_number}. ✅ Таблица `notifications` создана/проверена")
        step_number += 1
        
        # 3.2 Таблица mass_notifications
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mass_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT,
                title TEXT,
                text TEXT,
                days_before INTEGER,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        steps.append(f"{step_number}. ✅ Таблица `mass_notifications` создана/проверена")
        step_number += 1
        
        # 3.3 Таблица sent_notifications
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS sent_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                notification_id INTEGER,
                day_num INTEGER,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        steps.append(f"{step_number}. ✅ Таблица `sent_notifications` создана/проверена")
        step_number += 1
        
        # === 4. ИНДЕКСЫ ДЛЯ ПРОИЗВОДИТЕЛЬНОСТИ ===
        
        indexes = [
            ('idx_user_arc_access_user', 'user_arc_access', 'user_id'),
            ('idx_user_arc_access_arc', 'user_arc_access', 'arc_id'),
            ('idx_payments_user', 'payments', 'user_id'),
            ('idx_payments_status', 'payments', 'status'),
            ('idx_payments_yookassa', 'payments', 'yookassa_payment_id'),
            ('idx_user_progress_user', 'user_progress_advanced', 'user_id'),
            ('idx_user_progress_assignment', 'user_progress_advanced', 'assignment_id'),
            ('idx_notifications_type', 'notifications', 'type, day_num'),
        ]
        
        for idx_name, table_name, column in indexes:
            try:
                cursor.execute(f'CREATE INDEX IF NOT EXISTS {idx_name} ON {table_name}({column})')
                steps.append(f"{step_number}. 📈 Создан индекс `{idx_name}`")
                step_number += 1
            except:
                steps.append(f"{step_number}. ⚠️ Не удалось создать индекс `{idx_name}`")
                step_number += 1
        
        # === 5. ВКЛЮЧАЕМ WAL ДЛЯ ПАРАЛЛЕЛЬНОГО ДОСТУПА ===
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        steps.append(f"{step_number}. ⚡ Включен WAL режим для параллельного доступа")
        step_number += 1
        
        conn.commit()
        
        # === 6. ФИНАЛЬНАЯ ПРОВЕРКА ===
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = cursor.fetchall()
        
        # Считаем записи в ключевых таблицах
        stats = []
        key_tables = ['users', 'user_progress_advanced', 'user_arc_access', 'payments']
        
        for table in key_tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            stats.append(f"• {table}: {count} зап.")
        
        # Формируем итоговое сообщение
        message = "🔄 **ПОЛНОЕ ОБНОВЛЕНИЕ БАЗЫ ДАННЫХ ЗАВЕРШЕНО**\n\n"
        message += "📋 **Выполненные шаги:**\n"
        message += "\n".join(steps)
        
        message += f"\n\n📊 **ИТОГОВАЯ СТРУКТУРА:**\n"
        message += f"• Таблиц: {len(tables)}\n"
        message += "\n".join(stats)
        
        message += f"\n\n💾 **Backup создан:** `{backup_name}`"
        message += "\n\n✅ **Готово к работе!**"
        
        # Отправляем частями если длинное
        if len(message) > 4000:
            parts = [message[i:i+4000] for i in range(0, len(message), 4000)]
            for part in parts:
                await update.message.reply_text(part, parse_mode='Markdown')
        else:
            await update.message.reply_text(message, parse_mode='Markdown')
        
        logger.info("✅ Полное обновление БД завершено успешно")
        
    except Exception as e:
        error_msg = f"❌ КРИТИЧЕСКАЯ ОШИБКА при обновлении БД: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        if conn:
            conn.rollback()
        
        await update.message.reply_text(
            f"{error_msg}\n\n"
            f"⚠️ **Восстановите backup командой:**\n"
            f"`cp {backup_name} mentor_bot.db`",
            parse_mode='Markdown'
        )
        
    finally:
        if conn:
            conn.close()

async def check_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет готовность к миграции"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    message = "🔍 **ПРОВЕРКА ГОТОВНОСТИ К МИГРАЦИИ**\n\n"
    
    # 1. Проверяем ключевые таблицы
    required_tables = [
        'users', 'arcs', 'days', 'assignments', 
        'user_progress_advanced', 'user_arc_access', 'payments'
    ]
    
    missing_tables = []
    for table in required_tables:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
        if not cursor.fetchone():
            missing_tables.append(table)
    
    if missing_tables:
        message += "❌ **Отсутствуют таблицы:**\n"
        for table in missing_tables:
            message += f"• `{table}`\n"
    else:
        message += "✅ **Все ключевые таблицы присутствуют**\n"
    
    # 2. Проверяем данные
    cursor.execute("SELECT COUNT(*) FROM users")
    user_count = cursor.fetchone()[0]
    message += f"\n👤 **Пользователей:** {user_count}\n"
    
    cursor.execute("SELECT COUNT(*) FROM user_progress_advanced")
    progress_count = cursor.fetchone()[0]
    message += f"📝 **Записей прогресса:** {progress_count}\n"
    
    # 3. Проверяем платежную систему
    from database import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY
    if YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY:
        message += f"💰 **Ключи Юкассы:** настроены\n"
    else:
        message += f"💰 **Ключи Юкассы:** ❌ НЕ настроены!\n"
    
    conn.close()
    
    message += "\n🎯 **Рекомендации:**\n"
    if not missing_tables:
        message += "1. Создайте backup БД\n"
        message += "2. Выполните `/updatedb`\n"
        message += "3. Протестируйте платежи\n"
    else:
        message += "1. Выполните `/updatedb` для создания таблиц\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')


async def verify_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет сохранность критичных данных"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    message = "🔍 **Проверка данных после обновления:**\n\n"
    
    # 1. Пользователи
    cursor.execute("SELECT COUNT(*), COUNT(fio), COUNT(city) FROM users")
    users_count, users_fio, users_city = cursor.fetchone()
    message += f"👤 **Пользователи:** {users_count} чел.\n"
    message += f"• С ФИО: {users_fio}\n"
    message += f"• С городом: {users_city}\n"
    
    # 2. Прогресс заданий
    cursor.execute("SELECT COUNT(*), COUNT(DISTINCT user_id) FROM user_progress_advanced")
    progress_count, unique_users = cursor.fetchone()
    message += f"\n📝 **Прогресс заданий:** {progress_count} записей\n"
    message += f"• Уникальных пользователей: {unique_users}\n"
    
    # 3. Проверяем статусы прогресса
    cursor.execute("SELECT status, COUNT(*) FROM user_progress_advanced GROUP BY status")
    statuses = cursor.fetchall()
    message += f"• По статусам:\n"
    for status, count in statuses:
        message += f"  - {status}: {count}\n"
    
    # 4. Доступы (должны быть старые если есть)
    cursor.execute("SELECT COUNT(*) FROM user_arc_access")
    access_count = cursor.fetchone()[0]
    message += f"\n🔑 **Доступы к частям:** {access_count} записей\n"
    
    # 5. Платежи (должны быть 0 или старые)
    cursor.execute("SELECT COUNT(*) FROM payments")
    payments_count = cursor.fetchone()[0]
    message += f"💰 **Платежи:** {payments_count} записей\n"
    
    conn.close()
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def check_yookassa_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет авторизацию в Юкассе"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    from database import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_API_URL
    import requests
    import base64
    import json
    
    message = f"🔑 **Проверка ключей Юкассы**\n\n"
    message += f"Shop ID: `{YOOKASSA_SHOP_ID}`\n"
    message += f"Secret Key: `{YOOKASSA_SECRET_KEY[:20]}...`\n\n"
    
    # Проверяем формат ключа
    if YOOKASSA_SECRET_KEY.startswith('test_'):
        message += "🟡 **ТЕСТОВЫЙ ключ** (начинается с test_)\n"
    elif YOOKASSA_SECRET_KEY.startswith('live_'):
        message += "💰 **РАБОЧИЙ ключ** (начинается с live_)\n"
    else:
        message += "❌ **Неправильный формат ключа!**\n"
        message += "Должен начинаться с `test_` или `live_`\n"
    
    try:
        # Формируем авторизацию
        auth_string = f'{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}'
        encoded_auth = base64.b64encode(auth_string.encode()).decode()
        
        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/json",
            "Idempotence-Key": "test-auth-check"
        }
        
        # Пробуем создать тестовый платеж на 1 рубль
        test_data = {
            "amount": {
                "value": "1.00",
                "currency": "RUB"
            },
            "payment_method_data": {
                "type": "bank_card"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://svs365bot.ru"
            },
            "description": "Тест авторизации",
            "capture": True
        }
        
        response = requests.post(YOOKASSA_API_URL, 
                               json=test_data, 
                               headers=headers, 
                               timeout=10)
        
        if response.status_code == 200:
            payment_info = response.json()
            payment_id = payment_info.get('id', 'N/A')
            message += f"✅ **Авторизация успешна!**\n"
            message += f"Создан тестовый платеж: `{payment_id}`\n"
            
            # Пробуем сразу отменить тестовый платеж
            try:
                cancel_headers = headers.copy()
                cancel_headers["Idempotence-Key"] = "cancel-test-payment"
                cancel_response = requests.post(
                    f"{YOOKASSA_API_URL}/{payment_id}/cancel",
                    headers=cancel_headers,
                    timeout=5
                )
                if cancel_response.status_code == 200:
                    message += "✅ Тестовый платеж отменен\n"
            except:
                message += "⚠️ Не удалось отменить тест платеж\n"
                
        elif response.status_code == 401:
            message += f"❌ **ОШИБКА 401: Неверные ключи!**\n"
            try:
                error_data = response.json()
                message += f"Код: {error_data.get('code', 'N/A')}\n"
                message += f"Описание: {error_data.get('description', 'N/A')}\n"
            except:
                message += f"Ответ: {response.text[:200]}\n"
            
            message += "\n**Проверь:**\n"
            message += "1. Shop ID в кабинете Юкассы\n"
            message += "2. Что ключ начинается с `live_`\n"
            message += "3. Что ключ скопирован полностью\n"
            
        else:
            message += f"⚠️ **Ошибка {response.status_code}**\n"
            message += f"Ответ: {response.text[:200]}\n"
            
    except requests.exceptions.Timeout:
        message += "❌ Таймаут подключения к Юкассе\n"
    except requests.exceptions.ConnectionError:
        message += "❌ Ошибка подключения к Юкассе\n"
    except Exception as e:
        message += f"❌ Ошибка: {str(e)[:100]}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def debug_last_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последний платеж"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, user_id, arc_id, amount, status, yookassa_payment_id, created_at
        FROM payments 
        ORDER BY created_at DESC 
        LIMIT 1
    ''')
    
    payment = cursor.fetchone()
    
    if payment:
        pay_id, user_id_db, arc_id, amount, status, yookassa_id, created_at = payment
        
        cursor.execute('SELECT title FROM arcs WHERE arc_id = ?', (arc_id,))
        arc_title = cursor.fetchone()
        arc_title = arc_title[0] if arc_title else f"Часть {arc_id}"
        
        message = f"**Последний платеж:**\n\n"
        message += f"ID: {pay_id}\n"
        message += f"User: {user_id_db}\n"
        message += f"{arc_title}\n"
        message += f"Сумма: {amount}₽\n"
        message += f"Статус: {status}\n"
        message += f"Юкасса ID: `{yookassa_id}`\n"
        message += f"Дата: {created_at}\n"
        
        # Проверяем есть ли доступ
        cursor.execute('SELECT 1 FROM user_arc_access WHERE user_id = ? AND arc_id = ?', (user_id_db, arc_id))
        has_access = cursor.fetchone()
        
        if has_access:
            message += f"\n✅ **Доступ выдан:** да"
        else:
            message += f"\n❌ **Доступ выдан:** нет"
    else:
        message = "📭 Нет платежей в базе"
    
    conn.close()
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def webhook_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус webhook"""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        return
    
    import requests
    
    try:
        resp = requests.get(f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo", timeout=10)
        info = resp.json()
        
        msg = f"🌐 **Webhook Status**\n\n"
        msg += f"• URL: `{info.get('result', {}).get('url', 'None')}`\n"
        msg += f"• Ошибок: {info.get('result', {}).get('pending_update_count', 0)}\n"
        msg += f"• Последняя ошибка: {info.get('result', {}).get('last_error_message', 'None')[:50]}\n"
        
        await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

def send_payment_notification(user_id, arc_title, amount, payment_id):
    """Отправляет уведомление пользователю об успешной оплате"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        from telegram import Bot
        from config import TOKEN
        
        bot = Bot(token=TOKEN)
        
        # Определяем тип доступа
        if float(amount) == 100:
            access_type = "пробный (3 задания)"
        else:
            access_type = "полный"
        
        message = (
            f"✅ **Оплата подтверждена!**\n\n"
            f"Сумма: {amount}₽\n"
            f"{arc_title}\n"
            f"Доступ: {access_type}\n"
            f"ID платежа: `{payment_id}`\n\n"
            f"Задания доступны в разделе **'Мои задания'**!"
        )
        
        # Отправляем сообщение
        bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode='Markdown'
        )
        
        logger.info(f"Уведомление отправлено пользователю {user_id}")
        
    except Exception as e:
        logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")

async def manage_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление webhook (только для админа)"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администраторов")
        return
    
    import requests
    
    command = context.args[0] if context.args else "status"
    
    try:
        if command == "status":
            # Проверка статуса webhook
            resp = requests.get(
                f"https://api.telegram.org/bot{TOKEN}/getWebhookInfo",
                timeout=10
            )
            info = resp.json().get('result', {})
            
            msg = (
                f"🌐 **Webhook Status**\n\n"
                f"• URL: `{info.get('url', 'Not set')}`\n"
                f"• Has custom cert: {info.get('has_custom_certificate', False)}\n"
                f"• Pending updates: {info.get('pending_update_count', 0)}\n"
                f"• Last error: {info.get('last_error_message', 'None')[:100]}\n"
                f"• Last sync: {info.get('last_synchronization_error_date', 'Never')}\n"
            )
            
        elif command == "set":
            # Установка webhook
            WEBHOOK_URL = f"https://svs365bot.ru/bot/{TOKEN}"
            
            resp = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/setWebhook",
                json={"url": WEBHOOK_URL},
                timeout=10
            )
            
            if resp.json().get('ok'):
                msg = f"✅ Webhook установлен: `{WEBHOOK_URL}`"
            else:
                msg = f"❌ Ошибка: {resp.json().get('description', 'Unknown')}"
                
        elif command == "delete":
            # Удаление webhook
            resp = requests.post(
                f"https://api.telegram.org/bot{TOKEN}/deleteWebhook",
                timeout=10
            )
            
            if resp.json().get('ok'):
                msg = "✅ Webhook удален"
            else:
                msg = f"❌ Ошибка: {resp.json().get('description', 'Unknown')}"
                
        elif command == "test":
            # Тестовый запрос
            WEBHOOK_URL = f"https://svs365bot.ru/bot/{TOKEN}"
            resp = requests.get(WEBHOOK_URL, timeout=10)
            msg = f"Test response: {resp.status_code}"
            
        else:
            msg = (
                "📋 **Доступные команды:**\n"
                "• `/webhook status` - статус\n"
                "• `/webhook set` - установить\n"
                "• `/webhook delete` - удалить\n"
                "• `/webhook test` - тест\n"
            )
            
    except Exception as e:
        msg = f"❌ Ошибка: {str(e)}"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

def start_yookassa_webhook_server():
    """Запускает сервер для вебхуков ЮKассы"""
    app = web.Application()
    app.router.add_post('/yookassa-webhook/', yookassa_webhook)
    
    # Запускаем в отдельном потоке
    runner = web.AppRunner(app)
    return runner

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Логирует ошибки и отправляет уведомление администратору"""
    logger = logging.getLogger(__name__)
    
    # Логируем ошибку
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    
    # НЕ используем 'application' - её нет в scope!
    # Вместо этого используем context.bot напрямую
    
    try:
        if ADMIN_ID and context.bot:
            error_text = f"❌ Ошибка в боте:\n{context.error}"
            # Урезаем текст если слишком длинный
            if len(error_text) > 4000:
                error_text = error_text[:4000] + "..."
            await context.bot.send_message(chat_id=ADMIN_ID, text=error_text)
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление об ошибке: {e}")

async def tech_support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню технической поддержки"""
    context.user_data['current_section'] = 'tech_support'
    
    keyboard = [
        ["💬 Написать в поддержку"],
        ["📖 Инструкции"],  
        ["👤 Авторы марафона"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "🛠️ **Техническая поддержка**\n\n"
        "Выберите раздел:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает инструкции (пока в разработке)"""
    
    keyboard = [
        ["💬 Написать в поддержку"],
        ["👤 Авторы марафона"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📖 **Инструкции**\n\n"
        "⚠️ *Раздел в разработке*\n\n"
        "Скоро здесь появятся подробные инструкции "
        "по работе с ботом и выполнению заданий.\n\n"
        "Если у вас есть вопросы, напишите в поддержку:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_author_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию об авторе тренинга (пока в разработке)"""
    
    keyboard = [
        ["💬 Написать в поддержку"],
        ["📖 Инструкции"],
        ["🔙 В главное меню"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "👤 **Авторы марафона**\n\n"
        "⚠️ *Раздел в разработке*\n\n"
        "Скоро здесь появится информация об авторах"
        "и создателе тренинга «Себя верни себе».\n\n"
        "Для связи используйте кнопку ниже:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def write_to_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход в бот поддержки"""
    support_link = "https://t.me/SVS_helaper_bot"  # Просто ссылка без параметров
    
    keyboard = [[InlineKeyboardButton("💬 Перейти в поддержку", url=support_link)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🛠️ *Техническая поддержка*\n\n"
        "Нажмите кнопку ниже для перехода в чат поддержки.\n\n"
        "В боте поддержки вы сможете:\n"
        "• Создать обращение\n"
        "• Выбрать бот, в котором проблема\n"
        "• Отслеживать историю обращений",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def load_media_from_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загружает медиа-контент из Excel"""
    if not is_admin(update.message.from_user.id):
        return
    
    await update.message.reply_text("🔄 Загружаю медиа-контент из Excel...")
    
    from database import update_assignment_with_media_from_excel
    count = update_assignment_with_media_from_excel()
    
    await update.message.reply_text(
        f"✅ Загружено медиа для {count} заданий\n\n"
        f"Теперь задания могут содержать:\n"
        f"• 🖼️ Фото\n"
        f"• 🎵 Аудио\n"
        f"• 🎬 Видео-ссылки",
        parse_mode='Markdown'
    )

async def load_media_simple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простая загрузка медиа из Excel"""
    if not is_admin(update.message.from_user.id):
        return
    
    await update.message.reply_text("🔄 Загружаю медиа из Excel (простой формат)...")
    
    from database import update_assignment_with_media_simple
    count = update_assignment_with_media_simple()
    
    if count > 0:
        # ПРОСТОЙ ТЕКСТ БЕЗ MARKDOWN
        message = (
            f"✅ Загружено фото для {count} заданий!\n\n"
            f"Теперь медиа будут отображаться в заданиях.\n"
            f"Проверьте: откройте любое задание с фото."
        )
        await update.message.reply_text(message)
    else:
        # ПРОСТОЙ ТЕКСТ БЕЗ MARKDOWN
        message = (
            "❌ Не удалось загрузить медиа.\n\n"
            "Проверьте:\n"
            "1. Файл courses_data.xlsx в папке с ботом\n"
            "2. Колонка 'фото' в листе 'Задания'\n"
            "3. File ID в ячейках (просто текст, без скобок)"
        )
        await update.message.reply_text(message)

async def debug_current_arc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущую активную часть"""
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        return
    
    from database import get_current_arc
    current = get_current_arc()
    
    if current:
        arc_id, arc_title = current
        message = f"🔍 **Текущая активный марафон:**\n"
        message += f"• ID: {arc_id}\n"
        message += f"• Название: {arc_title}\n"
        
        # Проверяем доступ
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT access_type FROM user_arc_access WHERE user_id = ? AND arc_id = ?', 
                      (user_id, arc_id))
        access = cursor.fetchone()
        conn.close()
        
        message += f"• Ваш доступ: {'ЕСТЬ' if access else 'НЕТ'}\n"
    else:
        message = "❌ **Нет активных марафонов*\n\n"
        
        # Покажем все части
        conn = sqlite3.connect('mentor_bot.db')
        cursor = conn.cursor()
        cursor.execute('SELECT arc_id, title, дата_начала, дата_окончания FROM arcs WHERE arc_id > 0')
        all_arcs = cursor.fetchall()
        conn.close()
        
        if all_arcs:
            message += "📋 **Все части в БД:**\n"
            for arc_id, title, start_date, end_date in all_arcs:
                message += f"• {title} (ID:{arc_id}) - {start_date} / {end_date}\n"
        else:
            message += "В БД нет частей!"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def grant_free_trial_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдает бесплатный пробный доступ на 3 дня - ДЛЯ КОМПАНИЙ"""
    user_id = update.message.from_user.id
    
    # Проверяем компанию пользователя
    from database import get_user_company, get_company_arc, grant_trial_access
    
    user_company = get_user_company(user_id)
    if not user_company:
        await update.message.reply_text(
            "❌ **Вы не состоите в компании!**\n\n"
            "Для пробного доступа сначала присоединитесь к компании.",
            parse_mode='Markdown'
        )
        return
    
    # Получаем арку компании
    company_arc = get_company_arc(user_company['company_id'])
    if not company_arc:
        await update.message.reply_text("❌ У компании нет активного тренинга")
        return
    
    company_arc_id = company_arc['company_arc_id']
    
    # Проверяем не куплен ли уже доступ
    from database import check_user_arc_access
    has_access = check_user_arc_access(user_id, company_arc_id)
    
    if has_access:
        await update.message.reply_text(
            "✅ **У вас уже есть доступ к тренингу компании!**\n\n"
            "Проверьте раздел 'Мои задания'.",
            parse_mode='Markdown'
        )
        return
    
    # Выдаем пробный доступ
    success = grant_trial_access(user_id, company_arc_id)
    
    if success:
        await update.message.reply_text(
            f"🎉 **Пробный доступ на 3 дня активирован!**\n\n"
            f"🏢 **Компания:** {user_company['name']}\n"
            f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n"
            f"⏱️ **Доступ до:** {datetime.now() + timedelta(days=3)}\n\n"
            f"Теперь вы можете начать обучение в разделе '📚 Мои задания'.\n\n"
            f"💡 **После окончания пробного периода:**\n"
            f"• Доступ к заданиям закроется\n"
            f"• Для продолжения нужно купить полный доступ\n"
            f"• Прогресс сохранится после покупки",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "❌ **Ошибка активации пробного доступа!**\n\n"
            "Пожалуйста, попробуйте позже или обратитесь в поддержку.",
            parse_mode='Markdown'
        )

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простая команда - показывает инструкцию"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Сохраняем ID сообщения с инструкцией
    message = await update.message.reply_text(
        "📎 **ОТПРАВЬТЕ МНЕ ФОТО/АУДИО КАК ОТВЕТ НА ЭТО СООБЩЕНИЕ**\n\n"
        "1. Нажмите и удерживайте это сообщение\n"
        "2. Выберите 'Ответить' (Reply)\n"
        "3. Отправьте фото или аудио файл\n"
        "4. Я верну File ID\n\n"
        "⚠️ Важно: отправляйте файл именно как ОТВЕТ на это сообщение!"
    )
    
    # Сохраняем ID сообщения в context
    context.user_data['getfileid_message_id'] = message.message_id


async def cancel_file_id_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выйти из режима получения file_id"""
    if 'waiting_for_file_id' in context.user_data:
        context.user_data.pop('waiting_for_file_id', None)
        await update.message.reply_text("✅ Режим получения File ID отменен.")
    else:
        await update.message.reply_text("⚠️ Режим получения File ID не активен.")


async def get_file_id_easy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Самый простой работающий вариант"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return
    
    # Отправляем инструкцию с кнопкой "Просто отправьте файл"
    await update.message.reply_text(
        "📎 **Просто отправьте мне фото или аудио файл!**\n\n"
        "Не нужно писать /getfileid в подписи.\n"
        "Просто отправьте файл - я сам определю, что вы хотите получить File ID."
    )

async def handle_admin_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все файлы от админов"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        return  # Не админ - пропускаем
    
    # Обрабатываем только если нет других активных режимов
    if (not context.user_data.get('answering') and 
        not context.user_data.get('notification_stage')):
        
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            await update.message.reply_text(
                f"🖼 File ID фото:\n`{file_id}`\n\n"
                f'📋 Для Excel (колонка "фото"):\n`{file_id}`',
            )
            return
        
        if update.message.audio:
            file_id = update.message.audio.file_id
            await update.message.reply_text(
                f"🎵 File ID аудио:\n`{file_id}`\n\n"
                f'📋 Для Excel (колонка "аудио"):\n`{file_id}`',
            )
            return
        
        if update.message.video:
            file_id = update.message.video.file_id
            duration = update.message.video.duration
            file_size_mb = update.message.video.file_size / (1024*1024) if update.message.video.file_size else 0
            
            # ПРОСТОЙ ТЕКСТ БЕЗ MARKDOWN
            message = (
                f"🎬 File ID видео получен!\n\n"
                f"🆔 Код: {file_id}\n"
                f"⏱ Длительность: {duration} секунд\n"
                f"📏 Размер: {file_size_mb:.1f} MB\n\n"
                f"📋 Для Excel (колонка 'видео_ссылка'):\n{file_id}\n\n"
                f"✅ Видео будет показываться прямо в Telegram!"
            )
            
            await update.message.reply_text(message)  # БЕЗ parse_mode='Markdown'
            return
                
        if update.message.document:
            file_id = update.message.document.file_id
            file_name = update.message.document.file_name or "Документ"
            
            await update.message.reply_text(
                f"📄 File ID документа:\n`{file_id}`\n\n"
                f"📝 Название: {file_name}\n\n"
                f'📋 Для Excel:\n`{file_id}`',
            )
            return

async def check_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить медиа в базе данных"""
    if not is_admin(update.message.from_user.id):
        return
    
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # Проверяем первое задание
    cursor.execute('''
        SELECT assignment_id, title, content_photos, content_audios, video_url
        FROM assignments 
        WHERE assignment_id = 1
    ''')
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        assignment_id, title, photos_json, audios_json, video_url = result
        
        message = f"🔍 **Задание {assignment_id}: {title}**\n\n"
        
        if photos_json:
            try:
                photos = json.loads(photos_json)
                message += f"🖼️ **Фото:** {len(photos)} шт.\n"
                for i, photo_id in enumerate(photos[:3], 1):
                    message += f"  {i}. `{photo_id[:30]}...`\n"
            except:
                message += f"🖼️ **Фото (RAW):** `{photos_json[:50]}...`\n"
        else:
            message += "🖼️ **Фото:** нет\n"
        
        message += f"\n📏 Длина данных фото: {len(photos_json) if photos_json else 0} символов"
        
        await update.message.reply_text(message, parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Задание не найдено")

async def add_photo_to_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить фото к заданию напрямую"""
    if not is_admin(update.message.from_user.id):
        return
    
    # Формат: /addphoto 1 file_id_here
    if context.args and len(context.args) >= 2:
        try:
            assignment_id = int(context.args[0])
            file_id = context.args[1]
            
            # Формируем JSON
            photos_json = json.dumps([file_id])
            
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            
            # Проверяем существует ли задание
            cursor.execute('SELECT title FROM assignments WHERE assignment_id = ?', (assignment_id,))
            if cursor.fetchone():
                # Обновляем
                cursor.execute('''
                    UPDATE assignments 
                    SET content_photos = ?
                    WHERE assignment_id = ?
                ''', (photos_json, assignment_id))
                
                conn.commit()
                
                await update.message.reply_text(
                    f"✅ **Фото добавлено к заданию {assignment_id}!**\n\n"
                    f"📸 File ID: `{file_id}`\n"
                    f"📋 JSON: {photos_json}\n\n"
                    f"Теперь откройте задание как пользователь для проверки.",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(f"❌ Задание {assignment_id} не найдено")
            
            conn.close()
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    elif update.message.photo and len(context.args) == 1:
        # Если отправлено фото + ID задания
        try:
            assignment_id = int(context.args[0])
            file_id = update.message.photo[-1].file_id
            photos_json = json.dumps([file_id])
            
            conn = sqlite3.connect('mentor_bot.db')
            cursor = conn.cursor()
            
            cursor.execute('UPDATE assignments SET content_photos = ? WHERE assignment_id = ?', 
                          (photos_json, assignment_id))
            
            conn.commit()
            conn.close()
            
            await update.message.reply_text(
                f"✅ **Фото добавлено!**\n\n"
                f"📝 Задание: {assignment_id}\n"
                f"🖼️ File ID: `{file_id}`\n\n"
                f"Теперь проверьте: откройте задание {assignment_id} как пользователь.",
                parse_mode='Markdown'
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")
    
    else:
        await update.message.reply_text(
            "📝 **Использование:**\n\n"
            "**Способ 1:**\n"
            "`/addphoto <ID_задания> <file_id>`\n\n"
            "**Способ 2:**\n"
            "1. Напишите `/addphoto <ID_задания>`\n"
            "2. Отправьте фото как ответ на это сообщение\n\n"
            "**Пример:** `/addphoto 1 AgACAgIAAxkBAAIJuml7o8cOswb-rXwZCAuL8P2vQEZcAAIJE2sbbOrZS8KL5JWUSu69AQADAgADeQADOAQ`"
        )

async def load_all_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загрузить ВСЕ медиа из Excel (фото, аудио, видео)"""
    if not is_admin(update.message.from_user.id):
        return
    
    await update.message.reply_text("🔄 Загружаю ВСЕ медиа из Excel...")
    
    from database import load_all_media_from_excel
    result = load_all_media_from_excel()
    
    if result['status'] == 'success':
        stats = result['stats']
        
        # ПРОСТОЙ ТЕКСТ БЕЗ MARKDOWN
        message = (
            f"✅ ВСЕ МЕДИА ЗАГРУЖЕНЫ УСПЕШНО!\n\n"
            f"📊 Статистика:\n"
            f"• 📝 Обработано строк: {stats['total_rows']}\n"
            f"• ✅ Обновлено заданий: {stats['updated_assignments']}\n"
            f"• 🖼️ Загружено фото: {stats['photos_loaded']}\n"
            f"• 🎵 Загружено аудио: {stats['audios_loaded']}\n"
            f"• 🎬 Загружено видео: {stats['videos_loaded']}\n"
            f"• ❌ Ошибок: {stats['errors']}\n\n"
            f"Теперь в заданиях будут отображаться:\n"
            f"• Фото\n• Аудио\n• Видео-ссылки"
        )
        
        await update.message.reply_text(message)  # Без parse_mode
    
    else:
        message = (
            f"❌ Ошибка загрузки медиа!\n\n"
            f"Проблема: {result['message']}\n\n"
            f"Проверьте:\n"
            f"1. Файл courses_data.xlsx в папке с ботом\n"
            f"2. Лист 'Задания' в файле\n"
            f"3. Колонки: 'фото', 'аудио', 'видео_ссылка'\n"
            f"4. Формат данных: просто file_id или URL"
        )
        
        await update.message.reply_text(message)

async def load_tests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для загрузки тестов из Excel (только админ)"""
    if not is_admin(update.message.from_user.id):
        return
    
    await update.message.reply_text("🔄 Загружаю тесты из Excel...")
    
    from database import load_tests_from_excel
    count = load_tests_from_excel()
    
    await update.message.reply_text(
        f"✅ Загружено {count} вопросов для тестов\n\n"
        f"Теперь доступны:\n"
        f"• 📈 Тестирование по неделям\n"
        f"• 📊 Сохранение результатов\n"
        f"• 🔄 Прогресс прохождения",
        parse_mode='Markdown'
    )


# ==================== ТЕСТИРОВАНИЕ ====================

async def testing_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню тестирования - С ПРОВЕРКОЙ КОМПАНИИ"""
    context.user_data['current_section'] = 'testing'
    user_id = update.message.from_user.id
    
    # ★★★ ПРОВЕРКА КОМПАНИИ ★★★
    from database import check_user_company_access, get_user_company
    
    has_company_access, message = check_user_company_access(user_id)
    user_company = get_user_company(user_id)
    
    if not has_company_access:
        # Показываем сообщение в зависимости от статуса
        if user_company:
            # Есть компания, но нет доступа
            keyboard = [
                ["💰 Купить доступ к тренингу"],
                ["🔙 В главное меню"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                f"📈 **Тестирование**\n\n"
                f"🏢 **Компания:** {user_company['name']}\n"
                f"❌ **Нет доступа к тренингу!**\n\n"
                f"Для доступа к тестам необходимо купить доступ к тренингу компании.",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            # Нет компании
            keyboard = [
                ["🔑 Ввести ключ компании"],
                ["🔙 В главное меню"]
            ]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            
            await update.message.reply_text(
                "📈 **Тестирование**\n\n"
                "❌ **Вы не состоите в компании!**\n\n"
                "Тесты доступны только участникам компаний.\n\n"
                "1. Получите ключ компании у администратора\n"
                "2. Перейдите в 👤 Профиль → 🔑 Ввести ключ компании\n"
                "3. Введите полученный ключ\n\n"
                "После этого тесты станут доступны.",
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        return
    
    # ★★★ ЕСТЬ ДОСТУП К КОМПАНИИ - ПОКАЗЫВАЕМ ТЕСТЫ ★★★
    keyboard = [
        ["📈 Пройти тест"],
        ["📊 Мои результаты"],
        ["📚 В раздел Мои задания"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        "📈 **ТЕСТИРОВАНИЕ**\n\n"
        "Еженедельные тесты для закрепления материала:\n\n"
        "• **Неделя 1** - дни 1-7\n"
        "• **Неделя 2** - дни 8-14\n"
        "• **Неделя 3** - дни 15-21\n"
        "• **Неделя 4** - дни 22-28\n"
        "• **Неделя 5** - дни 29-35\n"
        "• **Неделя 6** - дни 36-42\n"
        "• **Неделя 7** - дни 43-49\n"
        "• **Неделя 8** - дни 50-56\n\n"
        "Каждый тест: 15 вопросов, 5 вариантов ответа.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_available_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор марафона для тестирования - УПРОЩЕННАЯ ДЛЯ КОМПАНИЙ"""
    user_id = update.message.from_user.id
    
    # ★★★ ПРОВЕРКА КОМПАНИИ ★★★
    from database import check_user_company_access
    has_company_access, _ = check_user_company_access(user_id)
    
    if not has_company_access:
        await update.message.reply_text(
            "📭 **Нет доступа к тестам.**\n\n"
            "Для доступа к тестам необходим доступ к тренингу компании.",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([["🔙 Назад к тестированию"]], resize_keyboard=True)
        )
        return
    
    # ★★★ ВСЕГДА ИСПОЛЬЗУЕМ СТАНДАРТНЫЙ ТРЕНИНГ (arc_id=1) ★★★
    # Получаем информацию о стандартном тренинге
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    cursor.execute('SELECT title FROM arcs WHERE arc_id = 1')
    arc_title_result = cursor.fetchone()
    arc_title = arc_title_result[0] if arc_title_result else "8-недельный тренинг"
    conn.close()
    
    # Сохраняем в контекст
    context.user_data['current_arc_id'] = 1
    context.user_data['current_arc_title'] = arc_title
    context.user_data['current_arc_type'] = 'arc'  # Всегда обычный тренинг
    
    # Получаем доступные тесты
    from database import get_available_tests
    available_tests = get_available_tests(user_id)
    
    if not available_tests:
        await update.message.reply_text(
            f"📭 **Нет доступных тестов для '{arc_title}'.**\n\n"
            f"Тесты станут доступны после выполнения заданий первых дней.",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([["🔙 Назад к тестированию"]], resize_keyboard=True)
        )
        return
    
    # Создаем клавиатуру
    keyboard = []
    test_mapping = {}
    
    for test_info in available_tests:
        week_num = test_info['week_num']
        status = test_info['status']
        completed = test_info['completed']
        
        if completed:
            btn_text = f"✅ Неделя {week_num} (пройден)"
        elif status == "доступен":
            btn_text = f"📝 Неделя {week_num} (доступен)"
        else:
            btn_text = f"⏳ Неделя {week_num} (скоро)"
        
        keyboard.append([btn_text])
        test_mapping[btn_text] = {
            'week_num': week_num,
            'status': status,
            'completed': completed
        }
    
    keyboard.append(["🔙 Назад к тестированию"])
    
    # Сохраняем маппинг
    context.user_data['test_mapping'] = test_mapping
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    message = f"📝 **ТЕСТЫ ДЛЯ МАРАФОНА**\n\n"
    message += f"🏁 **Название:** {arc_title}\n\n"
    message += "**Доступные тесты:**\n"
    
    for test_info in available_tests:
        week_num = test_info['week_num']
        status = test_info['status']
        
        if status == "пройден":
            message += f"✅ Неделя {week_num} - пройден\n"
        elif status == "доступен":
            message += f"📝 Неделя {week_num} - доступен\n"
        else:
            message += f"⏳ Неделя {week_num} - скоро\n"
    
    message += "\nВыберите тест для прохождения:"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_tests_for_arc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает доступные тесты для выбранного марафона - ОБНОВЛЕННАЯ"""
    user_id = update.message.from_user.id
    text = update.message.text
    
    print(f"🔍 show_tests_for_arc: text='{text}'")
    
    if 'arc_selection_map' not in context.user_data or text not in context.user_data['arc_selection_map']:
        await update.message.reply_text("❌ Ошибка: данные марафона не найдены")
        await show_available_tests(update, context)
        return
    
    arc_info = context.user_data['arc_selection_map'][text]
    arc_id = arc_info['arc_id']
    arc_title = arc_info['arc_title']
    arc_type = arc_info.get('arc_type', 'arc')  # 'arc' или 'company'
    
    print(f"🔍 Выбран марафон: ID={arc_id}, тип={arc_type}, название='{arc_title}'")
    
    # Сохраняем в контекст
    context.user_data['current_arc_id'] = arc_id
    context.user_data['current_arc_title'] = arc_title
    context.user_data['current_arc_type'] = arc_type
    
    # Получаем доступные тесты
    from database import get_available_tests
    
    is_company = (arc_type == 'company')
    available_tests = get_available_tests(user_id, arc_id, is_company)
    
    if not available_tests:
        await update.message.reply_text(
            f"📭 **Нет доступных тестов для '{arc_title}'.**\n\n"
            f"Тесты станут доступны во время прохождения марафона.",
            parse_mode='Markdown',
            reply_markup=ReplyKeyboardMarkup([["🔙 Назад к тестированию"]], resize_keyboard=True)
        )
        return
    
    # Создаем клавиатуру
    keyboard = []
    test_mapping = {}
    
    for test_info in available_tests:
        week_num = test_info['week_num']
        status = test_info['status']
        completed = test_info['completed']
        
        if completed:
            btn_text = f"✅ Неделя {week_num} (пройден)"
        elif status == "доступен":
            btn_text = f"📝 Неделя {week_num} (доступен)"
        else:
            btn_text = f"⏳ Неделя {week_num} (скоро)"
        
        keyboard.append([btn_text])
        test_mapping[btn_text] = {
            'week_num': week_num,
            'status': status,
            'completed': completed
        }
    
    keyboard.append(["🔙 Выбрать другой марафон"])
    
    # Сохраняем маппинг
    context.user_data['test_mapping'] = test_mapping
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    message = f"📝 **ТЕСТЫ ДЛЯ МАРАФОНА**\n\n"
    message += f"🏁 **Название:** {arc_title}\n\n"
    message += "**Доступные тесты:**\n"
    
    for test_info in available_tests:
        week_num = test_info['week_num']
        status = test_info['status']
        
        if status == "пройден":
            message += f"✅ Неделя {week_num} - пройден\n"
        elif status == "доступен":
            message += f"📝 Неделя {week_num} - доступен\n"
        else:
            message += f"⏳ Неделя {week_num} - скоро\n"
    
    message += "\nВыберите тест для прохождения:"
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает тест - УПРОЩЕННАЯ ДЛЯ КОМПАНИЙ"""
    user_id = update.message.from_user.id
    text = update.message.text
    
    print(f"🔍 start_test: text='{text}'")
    
    if 'test_mapping' not in context.user_data or text not in context.user_data['test_mapping']:
        await update.message.reply_text("❌ Ошибка: данные теста не найдены")
        await show_available_tests(update, context)
        return
    
    test_info = context.user_data['test_mapping'][text]
    week_num = test_info['week_num']
    
    if test_info.get('completed', False):
        await update.message.reply_text(
            f"✅ **Тест для недели {week_num} уже пройден!**\n\n"
            f"Вы можете посмотреть результаты в разделе '📊 Мои результаты'.",
            parse_mode='Markdown'
        )
        return
    
    arc_title = context.user_data.get('current_arc_title', '8-недельный тренинг')
    
    print(f"🔍 Запуск теста: week={week_num}")
    
    # Проверяем есть ли незаконченный тест
    from database import get_test_progress, get_tests_for_week
    
    # Получаем вопросы теста
    tests = get_tests_for_week(week_num)
    
    if not tests:
        await update.message.reply_text(
            f"❌ **Тест для недели {week_num} не найден!**\n\n"
            f"Обратитесь к администратору.",
            parse_mode='Markdown'
        )
        return
    
    # ★★★ ИСПРАВЛЕНИЕ: получаем прогресс
    progress = get_test_progress(user_id, week_num)
    
    if progress:
        # Продолжаем прерванный тест
        current_question = progress['current_question']
        answers = progress['answers']
        message = f"🔄 **Продолжение теста недели {week_num}**\n\n"
        message += f"Вы прервали тест на вопросе {current_question} из {len(tests)}.\n"
        message += "Продолжим?"
    else:
        # Начинаем новый тест
        current_question = 1
        answers = {}
        message = f"📝 **НАЧАЛО ТЕСТА НЕДЕЛИ {week_num}**\n\n"
        message += f"Марафон: {arc_title}\n"
        message += f"Количество вопросов: {len(tests)}\n"
        message += "Теперь приступим к первому вопросу!"
    
    # ★★★ ИСПРАВЛЕНИЕ: Сохраняем данные теста
    context.user_data['current_test'] = {
        'arc_title': arc_title,
        'week_num': week_num,
        'total_questions': len(tests),
        'questions': tests,
        'current_question': current_question,  # ★ ВАЖНО: добавляем здесь
        'answers': answers                     # ★ ВАЖНО: сохраняем ответы
    }
    
    # ★★★ УДАЛЯЕМ старые ключи
    context.user_data.pop('test_answers', None)
    context.user_data.pop('test_question_num', None)
    
    print(f"🔍 test_data создан: current_question={current_question}, answers={len(answers)}")
    
    keyboard = [
        ["⏹️ Прервать тест"]  # Будет заменено в show_question
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    
    # Показываем первый/текущий вопрос
    await show_question(update, context)

async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_num=None):
    """Показывает вопрос теста - ФИНАЛЬНАЯ ВЕРСИЯ"""
    test_data = context.user_data.get('current_test')
    if not test_data:
        await update.message.reply_text("❌ Нет активного теста")
        return
    
    # ★★★ ИСПРАВЛЕНИЕ: Получаем question_num из test_data если не передан
    if question_num is None:
        question_num = test_data.get('current_question', 1)  # Используем get с default
    
    questions = test_data['questions']
    
    if question_num > len(questions):
        # Тест завершен
        await finish_test(update, context)
        return
    
    # Получаем вопрос
    question = questions[question_num - 1]
    test_id, question_text, option1, option2, option3, option4, option5, correct_option, explanation = question
    
    # Формируем сообщение БЕЗ вариантов ответа в тексте
    message = f"📈 **ТЕСТ: Неделя {test_data['week_num']}**\n\n"
    message += f"📝 **Вопрос {question_num} из 15**\n\n"
    message += f"{question_text}\n"
    
    # ★★ ИСПРАВЛЕНИЕ: Создаем клавиатуру с текстом вариантов ответа
    keyboard = []
    option_mapping = {}  # Для сопоставления текста кнопки с optionX
    
    # Собираем непустые варианты
    options = []
    if option1 and str(option1).strip():
        options.append((option1, 'option1'))
    if option2 and str(option2).strip():
        options.append((option2, 'option2'))
    if option3 and str(option3).strip():
        options.append((option3, 'option3'))
    if option4 and str(option4).strip():
        options.append((option4, 'option4'))
    if option5 and str(option5).strip():
        options.append((option5, 'option5'))
    
    # Располагаем по 1 кнопке в ряд (варианты ответа)
    for option_text, option_key in options:
        # Обрезаем текст для кнопки если слишком длинный
        display_text = option_text
        if len(display_text) > 40:
            display_text = display_text[:37] + "..."
        
        keyboard.append([display_text])
        option_mapping[display_text] = option_key
    
    # Кнопка прерывания отдельной строкой
    keyboard.append(["⏹️ Прервать тест"])
    
    # ★★ ВАЖНО: Сохраняем маппинг для обработки ответа
    context.user_data['current_question_options'] = option_mapping
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # ★★★ ИСПРАВЛЕНИЕ: Сохраняем текущий вопрос в test_data
    test_data['current_question'] = question_num
    context.user_data['current_test'] = test_data
    
    # ★★★ ДОБАВИТЬ ОТЛАДОЧНУЮ ИНФОРМАЦИЮ
    print(f"🔍 show_question: question_num={question_num}")
    print(f"🔍 options count: {len(options)}")
    print(f"🔍 option_mapping: {option_mapping}")
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def process_test_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ на вопрос теста - РАБОТАЕТ С ТЕКСТОВЫМИ КНОПКАМИ"""
    user_id = update.message.from_user.id
    text = update.message.text
    
    # ★★★ ДОБАВИТЬ ОТЛАДКУ
    print(f"🔍 process_test_answer вызван с text='{text}'")
    
    # Проверяем активный тест
    test_data = context.user_data.get('current_test')
    if not test_data:
        # Может это выбор теста?
        if text in ["📈 Пройти тест", "📊 Мои результаты"]:
            await handle_buttons(update, context)
            return
        
        await update.message.reply_text("❌ Нет активного теста")
        return
    
    # Обработка прерывания теста
    if text == "⏹️ Прервать тест":
        # Сохраняем прогресс
        from database import save_test_progress
        save_test_progress(
            user_id=user_id,
            week_num=test_data['week_num'],
            current_question=test_data['current_question'],
            answers=test_data.get('answers', {})
        )
        
        context.user_data.pop('current_test', None)
        context.user_data.pop('current_question_options', None)
        
        await update.message.reply_text(
            "⏸️ **Тест прерван.**\n\n"
            "Ваш прогресс сохранен.\n"
            "Можете продолжить позже.",
            reply_markup=ReplyKeyboardMarkup([["📈 Пройти тест"], ["📊 Мои результаты"]], resize_keyboard=True),
            parse_mode='Markdown'
        )
        return
    
    # ★★★ ИСПРАВЛЕНИЕ: Получаем выбранный вариант из маппинга
    option_mapping = context.user_data.get('current_question_options', {})
    
    # Пробуем найти точное совпадение по тексту кнопки
    selected_option_key = None
    selected_text = text
    
    for option_text, option_value in option_mapping.items():
        # ★★ Сравниваем текст кнопки (с учетом возможного обрезания)
        if text == option_text or option_text.startswith(text[:40]):
            selected_option_key = option_value
            selected_text = option_text  # Сохраняем оригинальный текст
            break
    
    print(f"🔍 selected_option_key: {selected_option_key}")
    print(f"🔍 option_mapping: {option_mapping}")
    
    if not selected_option_key:
        await update.message.reply_text("❌ Выберите вариант ответа из предложенных")
        return
    
    # Получаем текущий вопрос
    question_num = test_data['current_question']
    questions = test_data['questions']
    
    if question_num > len(questions):
        await finish_test(update, context)
        return
    
    question = questions[question_num - 1]
    test_id, question_text, option1, option2, option3, option4, option5, correct_option, explanation = question
    
    # Проверяем правильность
    is_correct = (selected_option_key == correct_option)
    
    # Сохраняем ответ в test_data
    if 'answers' not in test_data:
        test_data['answers'] = {}
    
    test_data['answers'][str(test_id)] = {
        'selected': selected_option_key,
        'selected_text': selected_text,  # Сохраняем текст, который выбрал пользователь
        'correct': is_correct,
        'question_text': question_text
    }
    
    # ★★★ ИСПРАВЛЕНИЕ: Сохраняем обновленный test_data
    context.user_data['current_test'] = test_data
    
    # Переходим к следующему вопросу
    test_data['current_question'] += 1
    
    # Очищаем маппинг текущего вопроса
    context.user_data.pop('current_question_options', None)
    
    # Сохраняем промежуточный прогресс
    from database import save_test_progress
    save_test_progress(
        user_id=user_id,
        week_num=test_data['week_num'],
        current_question=test_data['current_question'],
        answers=test_data['answers']
    )
    
    # Показываем следующий вопрос или завершаем
    if test_data['current_question'] <= len(questions):
        await show_question(update, context)
    else:
        await finish_test(update, context)

def save_test_progress(user_id, week_num, current_question, answers):
    """Сохраняет прогресс теста - УПРОЩЕННАЯ (всегда arc_id=1)"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    answers_json = json.dumps(answers) if answers else '{}'
    
    # ★★★ ВСЕГДА ИСПОЛЬЗУЕМ arc_id = 1
    cursor.execute('''
        INSERT OR REPLACE INTO test_progress 
        (user_id, arc_id, week_num, current_question, answers_json)
        VALUES (?, 1, ?, ?, ?)
    ''', (user_id, week_num, current_question, answers_json))
    
    conn.commit()
    conn.close()

def save_test_result(user_id, week_num, answers, score):
    """Сохраняет результат теста - УПРОЩЕННАЯ (всегда arc_id=1)"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    answers_json = json.dumps(answers) if answers else '{}'
    
    # ★★★ ВСЕГДА ИСПОЛЬЗУЕМ arc_id = 1, company_arc_id = NULL
    cursor.execute('''
        INSERT OR REPLACE INTO test_results 
        (user_id, arc_id, company_arc_id, week_num, score, answers_json)
        VALUES (?, 1, NULL, ?, ?, ?)
    ''', (user_id, week_num, score, answers_json))
    
    conn.commit()
    conn.close()

def clear_test_progress(user_id, week_num):
    """Очищает прогресс теста - УПРОЩЕННАЯ (всегда arc_id=1)"""
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    # ★★★ ВСЕГДА ИСПОЛЬЗУЕМ arc_id = 1
    cursor.execute('''
        DELETE FROM test_progress 
        WHERE user_id = ? AND arc_id = 1 AND week_num = ?
    ''', (user_id, week_num))
    
    conn.commit()
    conn.close()

async def finish_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает тест и показывает результаты - УПРОЩЕННАЯ ДЛЯ КОМПАНИЙ"""
    test_data = context.user_data.get('current_test')
    if not test_data:
        await update.message.reply_text("❌ Нет активного теста")
        return
    
    user_id = update.message.from_user.id
    week_num = test_data['week_num']
    answers = test_data.get('answers', {})
    
    # Подсчет результатов
    total_questions = len(test_data['questions'])
    correct_answers = sum(1 for answer in answers.values() if answer.get('correct', False))
    score = int((correct_answers / total_questions) * 100) if total_questions > 0 else 0
    
    print(f"🔍 finish_test: week={week_num}, answers={len(answers)}, correct={correct_answers}, score={score}")
    
    # Сохраняем результат
    from database import save_test_result
    result_id = save_test_result(
        user_id=user_id,
        week_num=week_num,
        answers=answers,
        score=score
    )
    
    # Очищаем данные теста
    context.user_data.pop('current_test', None)
    context.user_data.pop('current_question_options', None)
    
    # Показываем результаты
    await show_test_results(update, context, user_id, week_num)

async def show_test_results(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None, week_num=None):
    """Показывает результаты теста - УПРОЩЕННАЯ ДЛЯ КОМПАНИЙ"""
    if user_id is None:
        user_id = update.message.from_user.id
    
    # ★★★ УПРОЩАЕМ: Если передан week_num, показываем конкретный тест
    if week_num:
        from database import get_test_result, get_tests_for_week
        result_data = get_test_result(user_id, week_num)
        
        if not result_data:
            await update.message.reply_text("❌ Результаты теста не найдены")
            return
        
        # ★★★ ВСЕГДА arc_id = 1 (но теперь не передаем его)
        arc_title = "8-недельный тренинг"  # Константа
        
        score = result_data['score']
        answers = result_data['answers']
        
        # Получаем вопросы теста для деталей
        questions = get_tests_for_week(week_num)
        question_map = {str(q[0]): q for q in questions}  # test_id -> question data
        
        # ★★★ ИСПРАВЛЕНИЕ: передаем без arc_id
        await show_test_result_details(update, context, arc_title, week_num, score, answers, question_map)
        return
    
    # ★★★ УПРОЩАЕМ: Показываем все результаты пользователя
    from database import get_all_test_results
    results = get_all_test_results(user_id)
    
    if not results:
        await update.message.reply_text(
            "📭 **Результаты тестов отсутствуют**\n\n"
            "Вы еще не проходили тесты.",
            parse_mode='Markdown'
        )
        return
    
    # ★★★ УПРОЩАЕМ: Только один марафон - 8-недельный тренинг
    # Показываем сразу все результаты
    arc_title = "8-недельный тренинг"
    keyboard = []
    
    for result_id, res_week_num, score, completed_at in results:
        date_str = completed_at[:10] if completed_at else "??"
        btn_text = f"📊 Неделя {res_week_num} ({score}%) - {date_str}"
        keyboard.append([btn_text])
        
        # Сохраняем маппинг
        if 'test_results_mapping' not in context.user_data:
            context.user_data['test_results_mapping'] = {}
        context.user_data['test_results_mapping'][btn_text] = {
            'week_num': res_week_num
        }
    
    keyboard.append(["🔙 Назад к тестированию"])
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"📊 **ВАШИ РЕЗУЛЬТАТЫ ТЕСТОВ**\n\n"
        f"🏁 **Тренинг:** {arc_title}\n"
        f"📈 **Всего пройдено тестов:** {len(results)}\n\n"
        f"Выберите тест для просмотра деталей:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_tests_for_arc_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает тесты выбранного марафона для просмотра результатов - УПРОЩЕННАЯ"""
    # ★★★ УПРОЩАЕМ: эта функция почти не нужна, но оставляем для обработки кнопок
    
    user_id = update.message.from_user.id
    
    # Если нажали на результат из mapping
    text = update.message.text
    if 'test_results_mapping' in context.user_data and text in context.user_data['test_results_mapping']:
        test_info = context.user_data['test_results_mapping'][text]
        week_num = test_info['week_num']
        
        # Показываем результат теста
        await show_test_results(update, context, user_id, week_num)
        return
    
    # Иначе показываем все результаты
    await show_test_results(update, context, user_id)

async def show_test_result_details(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                   arc_title, week_num, score, answers, question_map):
    """Показывает детали результатов теста - УПРОЩЕННАЯ ДЛЯ КОМПАНИЙ"""
    total_questions = len(question_map)
    correct_answers = sum(1 for answer in answers.values() if answer.get('correct', False))
    
    # Формируем сообщение с результатами
    message = f"📈 **РЕЗУЛЬТАТ ТЕСТА: {arc_title} - Неделя {week_num}**\n\n"
    message += f"📊 **Результат: {score}% ({correct_answers} из {total_questions})**\n\n"
    
    # Находим ошибочные ответы
    wrong_answers = []
    for test_id_str, answer_data in answers.items():
        if not answer_data.get('correct', False):
            wrong_answers.append({
                'test_id': test_id_str,
                'selected': answer_data.get('selected'),
                'question_text': answer_data.get('question_text', '')
            })
    
    if wrong_answers:
        message += "❌ **Ошибки в вопросах:**\n\n"
        
        for i, wrong in enumerate(wrong_answers, 1):
            test_id = wrong['test_id']
            question_data = question_map.get(test_id)
            
            if question_data:
                test_id_full, question_text, option1, option2, option3, option4, option5, correct_option, explanation = question_data
                
                # Находим текст выбранного варианта
                selected_option = wrong['selected']
                option_texts = {
                    'option1': option1,
                    'option2': option2,
                    'option3': option3,
                    'option4': option4,
                    'option5': option5
                }
                
                # Получаем selected_text из сохраненных ответов
                answer_data = answers.get(test_id_str, {})
                selected_text = answer_data.get('selected_text', 'не указан')
                correct_text = option_texts.get(correct_option, 'не указан')
                
                message += f"{i}. **Вопрос:** {test_id}\n"
                message += f"   **Текст:** {question_text[:100]}...\n"
                message += f"   **Ваш ответ:** {selected_text}\n"
                message += f"   **💡 Верный ответ:** {correct_text}\n"
                
                if explanation:
                    message += f"   **Объяснение:** {explanation[:150]}...\n"
                
                message += "\n"
    
    else:
        message += "🎉 **Отличный результат! Все ответы верные!**\n\n"
    
    # Кнопки
    keyboard = [
        ["📋 Показать все ответы"],
        ["🔙 Назад к результатам"],
        ["📈 Пройти другой тест"]
    ]
    
    # ★★★ ИСПРАВЛЕНИЕ: сохраняем только week_num и arc_title (arc_id не нужен)
    context.user_data['current_test_details'] = {
        'arc_title': arc_title,
        'week_num': week_num,
        'score': score,
        'answers': answers,
        'question_map': question_map
    }
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Отправляем сообщение частями если слишком длинное
    if len(message) > 4000:
        parts = split_message(message)
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                await update.message.reply_text(part, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.message.reply_text(part, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_all_test_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все ответы теста (15 вопросов) - УПРОЩЕННАЯ ДЛЯ КОМПАНИЙ"""
    test_details = context.user_data.get('current_test_details')
    if not test_details:
        await update.message.reply_text("❌ Нет данных для отображения")
        return
    
    arc_title = test_details['arc_title']
    week_num = test_details['week_num']
    score = test_details['score']
    answers = test_details['answers']
    question_map = test_details['question_map']
    
    total_questions = len(question_map)
    correct_answers = sum(1 for answer in answers.values() if answer.get('correct', False))
    
    # Заголовок
    message = f"📋 **ВСЕ ОТВЕТЫ ТЕСТА: {arc_title} - Неделя {week_num}**\n\n"
    message += f"📊 Результат: {score}% ({correct_answers} из {total_questions})\n\n"
    
    # Сортируем вопросы по test_id
    sorted_test_ids = sorted(question_map.keys(), key=lambda x: int(x))
    
    question_count = 0
    
    for test_id_str in sorted_test_ids:
        question_count += 1
        question_data = question_map.get(test_id_str)
        if not question_data:
            continue
        
        test_id_full, question_text, option1, option2, option3, option4, option5, correct_option, explanation = question_data
        
        # Находим ответ пользователя
        user_answer = answers.get(test_id_str, {})
        selected_option = user_answer.get('selected')
        selected_text = user_answer.get('selected_text', 'нет ответа')
        is_correct = user_answer.get('correct', False)
        
        # Тексты всех вариантов
        option_texts = {
            'option1': option1,
            'option2': option2,
            'option3': option3,
            'option4': option4,
            'option5': option5
        }
        
        correct_text = option_texts.get(correct_option, 'не указан')
        
        message += f"**{question_count}. {question_text}**\n\n"
        message += f"**Ваш ответ:** {selected_text} "
        
        if is_correct:
            message += "✅\n"
        else:
            message += f"❌\n"
            message += f"**💡 Верный ответ:** {correct_text}\n"
            
            # Пояснение если есть и ответ неверный
            if explanation and str(explanation).strip():
                message += f"   **📝 Пояснение:** {explanation[:150]}...\n"
        
        message += "\n" + "─" * 30 + "\n\n"
    
    keyboard = [
        ["🔙 Назад к результату"],
        ["📈 Пройти другой тест"]
    ]
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Отправляем частями (сообщение будет очень длинное)
    if len(message) > 4000:
        parts = split_message(message)
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                await update.message.reply_text(part, reply_markup=reply_markup, parse_mode='Markdown')
            else:
                await update.message.reply_text(part, parse_mode='Markdown')
    else:
        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def back_to_test_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к результату теста из просмотра всех ответов - УПРОЩЕННАЯ"""
    if 'current_test_details' not in context.user_data:
        await update.message.reply_text("❌ Нет данных о тесте")
        return
    
    test_details = context.user_data['current_test_details']
    user_id = update.message.from_user.id
    
    # Получаем результат теста по week_num
    from database import get_test_result, get_tests_for_week
    result_data = get_test_result(user_id, test_details['week_num'])
    
    if not result_data:
        await update.message.reply_text("❌ Результаты теста не найдены")
        return
    
    score = result_data['score']
    answers = result_data['answers']
    
    # Получаем вопросы теста
    questions = get_tests_for_week(test_details['week_num'])
    question_map = {str(q[0]): q for q in questions}
    
    # Показываем результат
    await show_test_result_details(
        update, context,
        test_details['arc_title'],
        test_details['week_num'],
        score,
        answers,
        question_map
    )

async def back_to_arc_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к тестам марафона из просмотра результата - УПРОЩАЕМ"""
    # ★★★ УПРОЩАЕМ: просто возвращаем к результатам тестов
    await show_test_results(update, context)

async def admin_auto_approved_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню для комментариев к автоматически принятым заданиям"""
    if not is_admin(update.message.from_user.id):
        return
    
    from database import get_auto_approved_assignments
    
    assignments = get_auto_approved_assignments()
    
    if not assignments:
        await update.message.reply_text(
            "✅ **Все автоматически принятые задания уже прокомментированы.**",
            parse_mode='Markdown'
        )
        return
    
    keyboard = []
    assignment_mapping = {}
    
    for assignment in assignments[:20]:  # Ограничиваем 20 заданиями
        assignment_id, user_id, answer_text, answer_files, assignment_title, day_title, arc_title, fio, username = assignment
        
        display_name = fio if fio else username
        # Обрезаем длинные имена
        if len(display_name) > 15:
            display_name = display_name[:12] + "..."
        
        btn_text = f"📝 {assignment_title[:20]}... ({display_name})"
        keyboard.append([btn_text])
        
        assignment_mapping[btn_text] = {
            'assignment_id': assignment_id,
            'user_id': user_id,
            'assignment_title': assignment_title,
            'day_title': day_title,
            'arc_title': arc_title,
            'display_name': display_name
        }
    
    context.user_data['auto_approved_mapping'] = assignment_mapping
    context.user_data['current_section'] = 'admin_auto_approved'
    
    keyboard.append(["🔙 В инструменты администратора"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"🤖 **Автоматически принятые задания ({len(assignments)})**\n\n"
        "Выберите задание для добавления комментария:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_auto_approved_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает автоматически принятое задание для комментария"""
    if not is_admin(update.message.from_user.id):
        return
    
    text = update.message.text
    assignment_mapping = context.user_data.get('auto_approved_mapping', {})
    assignment_info = assignment_mapping.get(text)
    
    if not assignment_info:
        await update.message.reply_text("❌ Задание не найдено")
        return
    
    assignment_id = assignment_info['assignment_id']
    user_id = assignment_info['user_id']
    
    # Получаем полные данные задания
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT upa.answer_text, upa.answer_files, upa.teacher_comment,
               a.content_text, a.title, d.title, ar.title,
               u.fio, u.username
        FROM user_progress_advanced upa
        JOIN assignments a ON upa.assignment_id = a.assignment_id
        JOIN days d ON a.day_id = d.day_id
        JOIN arcs ar ON d.arc_id = ar.arc_id
        JOIN users u ON upa.user_id = u.user_id
        WHERE upa.assignment_id = ? AND upa.user_id = ?
    ''', (assignment_id, user_id))
    
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        await update.message.reply_text("❌ Данные задания не найдены")
        return
    
    answer_text, answer_files, teacher_comment, content_text, assignment_title, day_title, arc_title, fio, username = result
    
    display_name = fio if fio else username
    
    # Показываем информацию
    message = f"АВТОМАТИЧЕСКИ ПРИНЯТОЕ ЗАДАНИЕ\n\n"
    message += f"Участник: {display_name}\n"
    message += f"Марафон: {arc_title}\n"
    message += f"День: {day_title}\n"
    message += f"Задание: {assignment_title}\n\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')
    
    # Текст задания
    if content_text:
        await send_long_message(update, content_text, "📝 Задание:")
    
    # Ответ участника
    if answer_text:
        await send_long_message(update, answer_text, "📋 Ответ участника:")
    
    # Фото если есть
    if answer_files:
        try:
            files_list = json.loads(answer_files)
            for i, file_id in enumerate(files_list[:3], 1):
                try:
                    await update.message.reply_photo(
                        photo=file_id,
                        caption=f"📎 Фото {i} от участника"
                    )
                except Exception as e:
                    print(f"🚨 Ошибка отправки фото: {e}")
        except Exception as e:
            print(f"🚨 Ошибка загрузки файлов: {e}")
    
    # Текущий комментарий
    message = f"**💬 Текущий комментарий:**\n{teacher_comment}\n\n"
    message += "**✏️ Введите ваш комментарий к заданию:**"
    
    # Сохраняем данные для добавления комментария
    context.user_data['waiting_for_admin_comment'] = True
    context.user_data['current_auto_approved_assignment'] = {
        'assignment_id': assignment_id,
        'user_id': user_id,
        'display_name': display_name,
        'assignment_title': assignment_title
    }
    
    keyboard = [["🔙 Отмена комментария"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode='Markdown')

async def show_training_catalog_with_company_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет компанию перед показом каталога"""
    user_id = update.message.from_user.id
    
    from database import get_user_company
    user_company = get_user_company(user_id)
    
    if not user_company:
        keyboard = [["🔑 Ввести ключ компании"], ["🔙 В главное меню"]]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            "⚠️ **Доступ заблокирован!**\n\n"
            "Для доступа к тренингу необходимо присоединиться к компании.\n\n"
            "1. Получите ключ компании у администратора\n"
            "2. Перейдите в 👤 Профиль → 🔑 Ввести ключ компании\n"
            "3. Введите полученный ключ\n\n"
            "После этого вы получите доступ ко всем функциям.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    await show_training_catalog(update, context)

    
async def debug_company(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для отладки компании пользователя"""
    user_id = update.message.from_user.id
    from database import get_user_company, get_company_arc, check_user_arc_access
    
    user_company = get_user_company(user_id)
    
    if not user_company:
        await update.message.reply_text("❌ **Нет компании**")
        return
    
    company_arc = get_company_arc(user_company['company_id'])
    
    message = f"🏢 **Информация о компании пользователя**\n\n"
    message += f"**Название:** {user_company['name']}\n"
    message += f"**ID компании:** {user_company['company_id']}\n"
    message += f"**Ключ:** `{user_company['join_key']}`\n"
    message += f"**Цена:** {user_company['price']}₽\n"
    message += f"**Дата старта:** {user_company['start_date']}\n"
    
    if company_arc:
        message += f"\n**Информация о тренинге компании:**\n"
        message += f"**ID арки компании:** {company_arc['company_arc_id']}\n"
        message += f"**Старт тренинга:** {company_arc['actual_start_date']}\n"
        message += f"**Окончание тренинга:** {company_arc['actual_end_date']}\n"
        
        # Проверяем доступ
        has_access = check_user_arc_access(user_id, company_arc['company_arc_id'])
        message += f"**Доступ пользователя:** {'✅ Есть' if has_access else '❌ Нет'}"
    else:
        message += f"\n**❌ У компании нет тренинга!**"
    
    await update.message.reply_text(message, parse_mode='Markdown')

async def test_real_payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для создания тестового платежа 1₽"""
    user_id = update.message.from_user.id
    
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только для администратора")
        return
    
    from database import create_yookassa_payment_with_receipt, get_user_company, get_company_arc
    
    # Получаем компанию пользователя
    user_company = get_user_company(user_id)
    if not user_company:
        await update.message.reply_text("❌ У вас нет компании")
        return
    
    company_arc = get_company_arc(user_company['company_id'])
    if not company_arc:
        await update.message.reply_text("❌ У компании нет тренинга")
        return
    
    # Создаем тестовый платеж на 1 рубль
    test_amount = 1.00
    
    await update.message.reply_text("🔄 Создаю тестовый платеж 1₽...")
    
    payment_url, payment_id = create_yookassa_payment_with_receipt(
        user_id, company_arc['company_arc_id'], test_amount, False, "Тестовый платеж 1₽"
    )
    
    if payment_url:
        keyboard = [
            [InlineKeyboardButton("💳 Оплатить 1₽ (тест)", url=payment_url)],
            [InlineKeyboardButton("✅ Я оплатил", callback_data=f"check_payment_{payment_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"💳 **Тестовый платеж 1₽ создан!**\n\n"
            f"ID платежа: `{payment_id}`\n\n"
            f"**Инструкция:**\n"
            f"1. Нажмите '💳 Оплатить 1₽ (тест)'\n"
            f"2. Оплатите 1 рубль в открывшемся окне\n"
            f"3. Вернитесь в бот и нажмите '✅ Я оплатил'\n\n"
            f"После этого система должна выдать вам доступ.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(f"❌ Ошибка создания платежа: {payment_id}")

async def check_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет статус платежа - С АВТОМАТИЧЕСКИМ ВОССТАНОВЛЕНИЕМ"""
    query = update.callback_query
    
    print(f"🔍 DEBUG: check_payment_callback ВЫЗВАН!")
    print(f"  Data: {query.data}")
    print(f"  User ID: {query.from_user.id}")
    
    await query.answer()
    
    if query.data.startswith('check_payment_'):
        payment_id = query.data.replace('check_payment_', '')
        user_id = query.from_user.id
        
        print(f"🔍 DEBUG: Проверка платежа {payment_id} для пользователя {user_id}")
        
        try:
            # 1. Проверяем статус через API Юкассы
            import base64
            import requests
            from database import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_API_URL
            
            auth_string = f'{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}'
            encoded_auth = base64.b64encode(auth_string.encode()).decode()
            
            headers = {
                "Authorization": f"Basic {encoded_auth}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(f"{YOOKASSA_API_URL}/{payment_id}", headers=headers, timeout=10)
            
            if response.status_code == 200:
                payment_info = response.json()
                status = payment_info.get("status")
                amount_info = payment_info.get("amount", {})
                amount = float(amount_info.get("value", 0))
                
                print(f"🔍 DEBUG: Статус платежа в Юкассе: {status}, Сумма: {amount}")
                
                # 2. Проверяем есть ли платеж в нашей БД
                conn = sqlite3.connect('mentor_bot.db')
                cursor = conn.cursor()
                
                cursor.execute("SELECT id, company_arc_id FROM payments WHERE yookassa_payment_id = ?", (payment_id,))
                payment_db = cursor.fetchone()
                
                if not payment_db:
                    print(f"⚠️  DEBUG: Платеж не найден в БД, пытаемся восстановить...")
                    
                    # Получаем company_arc_id из metadata или используем 1
                    metadata = payment_info.get("metadata", {})
                    company_arc_id = metadata.get("company_arc_id", 1)
                    
                    # Восстанавливаем платеж
                    from database import save_payment
                    db_id = save_payment(user_id, company_arc_id, amount, payment_id, status)
                    
                    if db_id:
                        print(f"✅ DEBUG: Платеж восстановлен в БД с ID: {db_id}")
                        payment_db = (db_id, company_arc_id)
                    else:
                        print(f"❌ DEBUG: Не удалось восстановить платеж в БД")
                        await query.answer("Ошибка: платеж не найден в базе данных", show_alert=True)
                        return
                
                db_id, company_arc_id = payment_db
                
                # 3. Обновляем статус в нашей БД
                from database import update_payment_status
                update_payment_status(payment_id, status)
                
                if status == 'succeeded':
                    # 4. Выдаем доступ
                    from database import grant_arc_access
                    
                    access_granted = grant_arc_access(user_id, company_arc_id, 'paid')
                    
                    if access_granted:
                        # Получаем название компании для сообщения
                        cursor.execute('''
                            SELECT c.name as company_name
                            FROM company_arcs ca
                            JOIN companies c ON ca.company_id = c.company_id
                            WHERE ca.company_arc_id = ?
                        ''', (company_arc_id,))
                        
                        company_result = cursor.fetchone()
                        company_name = company_result[0] if company_result else "вашей компании"
                        
                        conn.close()
                        
                        await query.edit_message_text(
                            f"✅ **Оплата подтверждена!**\n\n"
                            f"🏢 **Компания:** {company_name}\n"
                            f"💰 **Сумма:** {amount}₽\n\n"
                            f"Теперь вы можете начать обучение в разделе '📚 Мои задания'.",
                            parse_mode='Markdown'
                        )
                    else:
                        await query.edit_message_text(
                            f"✅ **Оплата подтверждена, но возникла проблема с доступом.**\n\n"
                            f"Пожалуйста, нажмите /fixaccess чтобы получить доступ вручную.",
                            parse_mode='Markdown'
                        )
                
                elif status == 'pending':
                    await query.answer(
                        "⏳ Платеж еще не подтвержден банком.\n"
                        "Обычно это занимает 1-2 минуты. Попробуйте через минуту.",
                        show_alert=True
                    )
                
                elif status == 'canceled':
                    await query.edit_message_text(
                        "❌ **Платеж отменен.**\n\n"
                        "Попробуйте оплатить снова или обратитесь в поддержку.",
                        parse_mode='Markdown'
                    )
                
                else:
                    await query.answer(f"Статус платежа: {status}", show_alert=True)
            
            elif response.status_code == 404:
                await query.answer("Платеж не найден в системе Юкассы", show_alert=True)
            
            else:
                error_msg = f"Ошибка API Юкассы: {response.status_code}"
                await query.answer(error_msg, show_alert=True)
        
        except Exception as e:
            error_msg = f"Ошибка проверки платежа: {str(e)}"
            print(f"❌ DEBUG: {error_msg}")
            import traceback
            traceback.print_exc()
            await query.answer(error_msg, show_alert=True)

async def debug_test_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отладка данных теста"""
    test_data = context.user_data.get('current_test', {})
    
    message = "🔍 **ДАННЫЕ ТЕСТА:**\n\n"
    message += f"Ключи в test_data: {list(test_data.keys())}\n"
    
    if test_data:
        message += f"week_num: {test_data.get('week_num')}\n"
        message += f"current_question: {test_data.get('current_question')}\n"
        message += f"total_questions: {test_data.get('total_questions')}\n"
        message += f"questions count: {len(test_data.get('questions', []))}\n"
        message += f"answers count: {len(test_data.get('answers', {}))}\n"
        
        # Показываем текущие варианты ответов
        option_mapping = context.user_data.get('current_question_options', {})
        message += f"\n📋 **Варианты ответов:**\n"
        for text, option in option_mapping.items():
            message += f"  '{text}' → {option}\n"
    
    await update.message.reply_text(message, parse_mode='Markdown')


def main():
    application = Application.builder().token(TOKEN).build()

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            send_scheduled_notifications,
            interval=60,
            first=10
        )

    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(
            check_daily_openings,
            interval=3600,
            first=10
        )

    init_db()
    print("✅ База данных инициализирована")
    # ГАРАНТИРОВАННО создаем правильную таблицу payments
    conn = sqlite3.connect('mentor_bot.db')
    cursor = conn.cursor()
    
    try:
        # Удаляем старую таблицу если у нее неправильная структура
        cursor.execute("PRAGMA table_info(payments)")
        columns = cursor.fetchall()
        
        if columns:
            column_names = [col[1] for col in columns]
            # Проверяем наличие ключевых колонок
            required_columns = ['arc_id', 'amount', 'status', 'yookassa_payment_id']
            
            if not all(col in column_names for col in required_columns):
                print("⚠️ Обнаружена таблица payments со старой структурой, пересоздаем...")
                cursor.execute("DROP TABLE IF EXISTS payments")
        
        # Создаем/пересоздаем таблицу
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                arc_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                yookassa_payment_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                metadata TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (arc_id) REFERENCES arcs(arc_id)
            )
        ''')
        
        # Индексы для производительности
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_payments_yookassa_id ON payments(yookassa_payment_id)')
        
        conn.commit()
        print("✅ Таблица payments гарантированно создана с правильной структурой")
        
    except Exception as e:
        print(f"⚠️ Ошибка создания таблицы payments: {e}")
    finally:
        conn.close()
        
    upgrade_database()
    from database import test_new_structure
    test_new_structure()

    application.add_handler(MessageHandler(
        filters.PHOTO | filters.AUDIO | filters.VIDEO | filters.Document.ALL,
        handle_admin_files
    ))
    
    application.add_handler(CommandHandler("start", start))
    application.add_error_handler(error_handler)
    application.add_handler(CallbackQueryHandler(check_payment_callback, pattern='^check_payment_'))
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, handle_document))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))
    application.add_handler(CommandHandler("reloadfull", reload_full))
    application.add_handler(CallbackQueryHandler(handle_access_callback))
    application.add_handler(CommandHandler("payments", check_payment_status))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^{.*}$'), yookassa_webhook))
    application.add_handler(CommandHandler("testpay", test_payment_flow))
    application.add_handler(CommandHandler("paystruct", check_db_structure))
    application.add_handler(CommandHandler("createpaytable", create_payments_table))
    application.add_handler(CommandHandler("tables", show_tables))
    application.add_handler(CommandHandler("fixpayments", recreate_payments_table))
    application.add_handler(CommandHandler("testpayment", test_payment_system))
    application.add_handler(CommandHandler("testkeys", test_yookassa_keys))
    application.add_handler(CommandHandler("myaccess", check_my_access))
    application.add_handler(CommandHandler("debugpay", debug_payment))
    application.add_handler(CommandHandler("debugcb", debug_callback))
    application.add_handler(CommandHandler("simpletest", simple_test))
    application.add_handler(CommandHandler("fixaccess", fix_access))
    application.add_handler(CommandHandler("checktables", check_tables))
    application.add_handler(CommandHandler("debugreg", debug_registration))
    application.add_handler(CommandHandler("resetreg", reset_registration))
    application.add_handler(CommandHandler("debugflow", debug_flow))
    application.add_handler(CommandHandler("updatedb", update_database_full))
    application.add_handler(CommandHandler("checkmigrate", check_migration))
    application.add_handler(CommandHandler("verify", verify_data))
    application.add_handler(CommandHandler("checkauth", check_yookassa_auth))
    application.add_handler(CommandHandler("lastpay", debug_last_payment))
    application.add_handler(CommandHandler("whstatus", webhook_status))
    application.add_handler(CommandHandler("webhook", manage_webhook))
    application.add_handler(CommandHandler("loadmedia", load_media_from_excel))
    application.add_handler(CommandHandler("debugarc", debug_current_arc))
    application.add_handler(CommandHandler("getfileid", get_file_id))
    application.add_handler(CommandHandler("cancelfileid", cancel_file_id_mode))
    application.add_handler(CommandHandler("checkmedia", check_media))
    application.add_handler(CommandHandler("addphoto", add_photo_to_assignment))
    application.add_handler(CommandHandler("loadmediasimple", load_media_simple))
    application.add_handler(CommandHandler("loadallmedia", load_all_media))
    application.add_handler(CommandHandler("loadtests", load_tests_command))
    application.add_handler(CommandHandler("debugcompany", debug_company))
    application.add_handler(CommandHandler("test1rub", test_real_payment_command))
    application.add_handler(CommandHandler("debugtestdata", debug_test_data))
    
    
    print("Бот запущен...")
    
    
    webhook_mode = any(arg in sys.argv for arg in ['--webhook', 'webhook', '--wh'])
    
    if webhook_mode:
        print("🚀 Запуск в режиме WEBHOOK")
        WEBHOOK_HOST = "svs365bot.ru"
        TOKEN_PATH = f"bot/{TOKEN}"
        WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{TOKEN_PATH}"
        LISTEN_IP = "127.0.0.1"
        PORT = 8083
    
        try:
            # Просто запускаем webhook
            application.run_webhook(
                listen=LISTEN_IP,
                port=PORT,
                webhook_url=WEBHOOK_URL,
                drop_pending_updates=True,
            )
        except Exception as e:
            print(f"❌ Ошибка webhook: {e}")
            print("🔄 Переключаюсь на polling как fallback...")
            # Нужно создать новый event loop для polling
            import asyncio
            asyncio.set_event_loop(asyncio.new_event_loop())
            application.run_polling(allowed_updates=Update.ALL_TYPES)

    print("🚀 Запуск в режиме POLLING (локальный)")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
