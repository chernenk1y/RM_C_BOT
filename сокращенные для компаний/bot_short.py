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
    
    keyboard = [
        ["📚 Мои задания", "🎯 Купить тренинг"],
        ["👤 Профиль", "🛠 Тех.поддержка"]
    ]

    if has_any_access(user.id) or user.id == ADMIN_ID:
        keyboard.append(["👥 Перейти в сообщество"])
    
    if is_admin(user.id):
        keyboard.append(["👨‍🏫 Проверка заданий"])
        keyboard.append(["⚙️ Инструменты администратора"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        f"Приветствую вас, {user.first_name}! Выбери действие:",
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
    
    if text.startswith("🔄 ") or text.startswith("⏳ "):
        #Проверяем не находимся ли мы в админ-разделе
        current_section = context.user_data.get('current_section')
        if current_section == 'admin':
            # Это задание в админ-панели, обрабатываем отдельно
            await show_assignment_for_admin(update, context)
        else:
            # Это действительно дуга в каталоге
            await buy_arc_from_catalog(update, context)
        return
    
    # 5. Обработка кнопок покупки (используем существующие функции)
    if text == "🎁 Пробный доступ(3 дня)":
        # Проверяем выбрана ли часть
        if 'current_arc_catalog' not in context.user_data:
            await update.message.reply_text("❌ Сначала выберите часть")
            return
        
        # Проверяем что это ТЕКУЩАЯ часть (активная)
        part_status = context.user_data.get('part_status', '')
        if part_status != 'активный':
            await update.message.reply_text(
                "❌ **Пробный доступ доступен только для активных марафонов!**\n\n"
                "Для будущих марафонов доступен только полный доступ.",
                parse_mode='Markdown'
            )
            return
        
        await grant_free_trial_access(update, context)
        return
    
    if text == "💰 Купить полный доступ":
        # Проверяем выбрана ли часть
        if 'current_arc_catalog' not in context.user_data:
            await update.message.reply_text("❌ Сначала выберите часть")
            return
        
        # Вызываем функцию покупки через Юкассу
        await buy_arc_with_yookassa(update, context, trial=False)
        return
    
    if text == "💰 Купить доступ заранее":
        # Проверяем выбрана ли часть
        if 'current_arc_catalog' not in context.user_data:
            await update.message.reply_text("❌ Сначала выберите часть")
            return
        
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

    # 1. Сначала ВСЕ уникальные кнопки которые точно определены
    unique_buttons = {
        "✅ Отправить задание": submit_assignment,
        "📝 Доступные задания": show_available_assignments,
        "👨‍🏫 Проверка заданий": admin_panel,
        "📚 Мои задания": my_assignments_menu,
        "🎯 Купить тренинг": show_training_catalog,
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
        "👥 Перейти в сообщество": go_to_community,
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
        "📈 Пройти тест": show_available_tests,  # Теперь это выбор марафона
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

async def view_submission_file(update: Update, context: ContextTypes.DEFAULT_TYPE)

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

async def enter_company_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос ключа компании"""

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

async def request_fio_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Просит ввести ФИО если его нет"""
    
async def select_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор часового пояса"""

async def my_assignments_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['current_student_id'] = None
    """Главное меню раздела 'Мои задания'"""

async def show_available_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📝 Показывает задания из ВСЕХ активных частей - ОБНОВЛЕННАЯ: последовательное открытие"""
    context.user_data['current_section'] = 'available_assignments'
    user_id = update.message.from_user.id

    print(f"🔍 DEBUG show_available_assignments вызвана для user_id={update.message.from_user.id}")
    
    # Добавь в самое начало:
    import traceback
    print("📋 Вызов функции show_available_assignments:")
    traceback.print_stack(limit=5)
    
    # ★★★ ПРОВЕРЯЕМ КОМПАНИЮ ★★★
    from database import get_user_company, get_company_arc, check_user_company_access
    
    # 1. Получаем компанию пользователя
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
    
    # 2. Получаем арку компании
    company_arc = get_company_arc(user_company['company_id'])
    if not company_arc:
        await update.message.reply_text(
            "❌ **У вашей компании нет активного тренинга!**\n\n"
            "Обратитесь к администратору компании.",
            parse_mode='Markdown'
        )
        return
    
    company_arc_id = company_arc['company_arc_id']
    
    # 3. Проверяем доступ пользователя к тренингу компании
    has_access, message = check_user_company_access(user_id)
    if not has_access:
        # Показываем кнопку покупки доступа
        keyboard = [
            ["💰 Купить доступ к тренингу"],
            ["🔙 В главное меню"]
        ]
        reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
        
        await update.message.reply_text(
            f"⚠️ **Нет доступа к тренингу компании!**\n\n"
            f"Компания: {user_company['name']}\n"
            f"Старт тренинга: {company_arc['actual_start_date']}\n"
            f"Цена доступа: {user_company['price']}₽\n\n"
            f"{message}\n\n"
            f"Чтобы получить доступ, нажмите '💰 Купить доступ к тренингу'",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return
    
    # ★★★ ПОЛУЧАЕМ ТЕКУЩИЙ ДЕНЬ АРКИ КОМПАНИИ ★★★
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
        message += f"🏢 **Компания:** {user_company['name']}\n"
        message += f"📅 **Старт тренинга:** {company_arc['actual_start_date']}\n"
        
        if days_left > 0:
            message += f"⏳ **До начала:** {days_left} дней\n\n"
            message += f"Задания станут доступны в день старта тренинга."
        else:
            message += f"🔄 **Тренинг начнется в ближайшее время.**"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    current_day_num = current_day_info['day_number']
    day_to_show = current_day_info['day_number']
    
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
            'company_name': user_company['name'],
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
    
    # ★★★ ФОРМИРУЕМ СООБЩЕНИЕ ★★★
    if not all_assignments_info:
        message = f"✅ **Все задания дня {current_day_num} выполнены!**\n\n"
        message += f"🏢 **Компания:** {user_company['name']}\n"
        message += f"📅 **Текущий день тренинга:** {current_day_num}\n"
        message += f"🔄 **Новые задания откроются завтра**\n\n"
        
        if current_day_num >= 56:
            message += f"🎉 **Поздравляем! Вы завершили 8-недельный тренинг!**"
        
        await update.message.reply_text(message, parse_mode='Markdown')
        return
    
    message = f"📝 **ДОСТУПНЫЕ ЗАДАНИЯ**\n\n"
    message += f"🏢 **Компания:** {user_company['name']}\n"
    message += f"📅 **Текущий день тренинга:** {current_day_num}\n\n"
    
    message += f"Доступно: все заданиядо до текущего дня тренинга. Для выполнения заданий последовательно, задания в меню отображаются по дням. Как только вы выполните все задания дня, откроются задания следующего дня, если этот день уже наступил.\n\n"
    
    message += "💡 **Как выполнять задания:**\n\n"
    message += "1. Нажмите на задание из списка ниже\n\n"
    message += "2. Выберите подходящий способ ответа\n\n"
    message += "3. Выполните задание и отправьте на проверку\n\n"
    message += "4. Задания открываются последовательно: когда выполните задания одного дня, тогда откроются следующие\n\n"
    message += "5. Выполненное задание будет храниться в разделе 'Архив заданий'\n\n"
    message += "6. Психолог имеет возможность просмотреть и ответить на все ваши задания\n\n"
    message += "7. Ответы к заданиям появятся в разделе 'Архив заданий' -> 'Новые ответы'\n\n"
    message += "8. Новые задания открываются в 06:00 по вашему времени\n\n"
    
    message += "Выберите задание:"
    
    # ★★★ СОЗДАЕМ КЛАВИАТУРУ ★★★
    keyboard = []
    assignments_mapping = []
    
    # Группируем задания по 2 в ряд
    row = []
    for i, assignment in enumerate(all_assignments_info[:24]):
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
    
    keyboard.append(["📚 В раздел Мои задания"])
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Сохраняем данные для обработки нажатий
    context.user_data['assignments_mapping'] = assignments_mapping
    context.user_data['current_company_arc_id'] = company_arc_id
    context.user_data['current_company_name'] = user_company['name']
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def show_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали задания и ВЫБОР ТИПА ОТВЕТА"""

async def start_assignment_answer(update: Update, context: ContextTypes.DEFAULT_TYPE, answer_type=None):
    """Начинает процесс ответа в зависимости от выбранного типа"""

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
       
async def finish_assignment_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает отправку ответа и сохраняет в БД"""

async def process_assignment_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает вопрос к заданию"""

async def finish_assignment_with_questions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает отправку задания с вопросами"""

async def show_new_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
async def show_student_part_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ВСЕ новые задания участника в выбранной части"""
    
async def show_student_courses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает тренинги выбранного участника"""
    
async def show_assignment_for_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
async def finish_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает принятие задания с комментарием"""

async def submit_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):

async def show_approved_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):

async def show_student_part_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает ВСЕ принятые задания участника в выбранной части"""

async def show_assignment_approved(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает принятое задание с комментарием психолога"""

async def show_approved_assignment_simple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает принятое задание (упрощенная версия для новой структуры)"""

async def handle_additional_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает текст дополнительного комментария"""

async def add_comment_to_approved_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает добавление комментария к принятому заданию - УЛУЧШЕННАЯ ВЕРСИЯ"""

async def show_feedback_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):

async def request_personal_consultation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос личной консультации - обновленная"""

async def start_fio_change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['waiting_for_fio'] = True
    await update.message.reply_text("📝 Введите ваше ФИО:")

async def show_course_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Детали тренинга и список частей"""

def get_course_arcs(course_title):
    """Получает часть тренинга с проверкой доступности по датам - ИСПРАВЛЕННАЯ"""

async def show_about_course(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Страница 'Всё о тренинге' с подразделами и ссылкой на Телеграф"""

async def show_course_main(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Страница 'Купить доступ' - показывает все части с датами ТОЛЬКО с указанными датами"""

async def contact_psychologist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход к психологу с inline-кнопкой"""

def get_current_arc():
    """ОРИГИНАЛЬНАЯ версия с исправлением проблемы раздела 0"""

async def check_daily_openings(context: ContextTypes.DEFAULT_TYPE):
    """Проверяет и открывает новые дни в 06:00 местного времени"""

async def reload_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полная перезагрузка данных из Excel"""

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список частей для выбора статистики"""

async def show_arc_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статистику по выбранной части - ИСПРАВЛЕННАЯ ВЕРСИЯ"""

async def manage_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление доступом - список пользователей"""

async def show_user_arcs_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает доступы пользователя с inline-кнопками И список пользователей"""

async def handle_access_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает нажатия inline-кнопок управления доступом"""

async def show_user_arcs_access_callback(query, context, user_id):
    """Обновляет сообщение с inline-клавиатурой"""

async def show_users_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список участников для просмотра статистики (админ)"""
    
async def show_admin_arc_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную статистику пользователя по выбранной части (админ)"""

async def show_admin_user_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает меню выбора части для просмотра статистики пользователя (админ)"""
    
async def show_admin_arc_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детальную статистику пользователя по выбранной части (админ)"""
    
def has_any_access(user_id):
    """Проверяет есть ли у пользователя доступ к любому разделу"""

async def go_to_community(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет inline-кнопку для перехода в сообщество"""

async def show_offer_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает оферту регистрации с inline-кнопкой"""

async def decline_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отказ от оферты - с переходом в главное меню"""

async def decline_service_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает отказ от оферты - с переходом в главное меню"""

async def show_events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Список мероприятий тренинга"""

async def show_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Расписание всех марафона"""

async def show_service_offer_agreement(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает оферту на услуги с inline-кнопкой"""

async def accept_service_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Упрощенная версия - показывает кнопку для перехода"""

async def show_accepted_offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список принятых оферт с ссылками"""

async def show_today_assignments_info(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    """Показывает информацию о заданиях на текущий день для ВСЕХ активных частей"""

async def show_quick_guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает краткое руководство по работе с заданиями"""
    
async def start_photo_only_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает ответ ТОЛЬКО ФОТО"""

async def start_text_only_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает ответ ТОЛЬКО ТЕКСТ"""

async def start_photo_text_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает ответ ФОТО + ТЕКСТ (старый вариант)"""

async def show_submit_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает кнопки отправки с возможностью задать вопрос"""

async def ask_question_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает добавление вопроса к заданию"""

async def show_training_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о тренинге или фестивале"""

async def send_scheduled_notifications(context: ContextTypes.DEFAULT_TYPE):
    """Отправка запланированных уведомлений"""

async def buy_arc_with_yookassa(update: Update, context: ContextTypes.DEFAULT_TYPE, trial=False):
    """Покупка доступа через Юкассу - АДАПТИРОВАННАЯ ДЛЯ КОМПАНИЙ"""
    user_id = update.message.from_user.id
    logger.info(f"Начало покупки: user={user_id}, trial={trial}")
    
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
    """Проверяет статус платежа - ОБНОВЛЕННАЯ"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith('check_payment_'):
        payment_id = query.data.replace('check_payment_', '')
        user_id = query.from_user.id
        
        logger.info(f"Проверка платежа компании: {payment_id} пользователем {user_id}")
        
        try:
            # 1. Проверяем статус через API Юкассы
            import base64
            from database import YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_API_URL
            
            headers = {
                "Authorization": f"Basic {base64.b64encode(f'{YOOKASSA_SHOP_ID}:{YOOKASSA_SECRET_KEY}'.encode()).decode()}",
                "Content-Type": "application/json"
            }
            
            response = requests.get(f"{YOOKASSA_API_URL}/{payment_id}", headers=headers)
            
            if response.status_code == 200:
                payment_info = response.json()
                status = payment_info.get("status")
                
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
                        
                        if amount == 100:  # Пробный доступ
                            access_type = 'trial'
                            access_text = "пробный (3 дня)"
                        else:  # Полный доступ
                            access_type = 'paid'
                            access_text = "полный (56 дней)"
                        
                        # Выдаем доступ к компании
                        access_granted = grant_arc_access(user_id, company_arc_id, access_type)
                        
                        if access_granted:
                            await query.edit_message_text(
                                f"✅ **Оплата подтверждена!**\n\n"
                                f"🏢 **Компания:** {company_name}\n"
                                f"💰 **Сумма:** {amount}₽\n"
                                f"🎯 **Доступ:** {access_text}\n\n"
                                f"Теперь вы можете начать обучение в разделе '📚 Мои задания'.",
                                parse_mode='Markdown'
                            )
                            logger.info(f"✅ Доступ к компании '{company_name}' выдан пользователю {user_id}")
                        else:
                            await query.edit_message_text(
                                f"✅ **Оплата подтверждена, но возникла проблема с доступом.**\n\n"
                                f"🏢 Компания: {company_name}\n"
                                f"💰 Сумма: {amount}₽\n\n"
                                f"Пожалуйста, нажмите /fixaccess чтобы получить доступ вручную.",
                                parse_mode='Markdown'
                            )
                    else:
                        await query.edit_message_text(
                            "❌ **Платеж найден в Юкассе, но не в нашей базе.**\n\n"
                            "Пожалуйста, обратитесь в поддержку.",
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
                logger.error(error_msg)
                await query.answer(error_msg, show_alert=True)
        
        except Exception as e:
            error_msg = f"Ошибка проверки платежа: {str(e)}"
            logger.error(error_msg)
            await query.answer(error_msg, show_alert=True)

async def send_long_message(update, text, prefix="", parse_mode='Markdown'):
    """Отправляет длинное сообщение частями"""

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

async def show_company_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали выбранной компании"""

def clean_markdown_text(text):
    """Очищает текст от проблемных Markdown символов, но сохраняет корректное форматирование"""

async def show_seminar_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали выбранного семинара"""

async def show_assignment_from_list(update: Update, context: ContextTypes.DEFAULT_TYPE):

async def show_in_progress_assignments(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает задания на проверке"""

async def show_feedback_parts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает части с ответами психолога"""

async def show_feedback_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор типа ответов - ОБНОВЛЕННАЯ"""

async def show_feedback_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список заданий с ответами - УПРОЩЕННАЯ ВЕРСИЯ"""

async def show_feedback_assignment_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает детали ответа психолога на задание - ИСПРАВЛЕННАЯ"""

async def show_training_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Каталог тренинга - сразу выбор: Всё о курсе / Купить доступ"""
    context.user_data['current_section'] = 'training_catalog'
    
    # ★★★ ПРОВЕРЯЕМ КОМПАНИЮ ПОЛЬЗОВАТЕЛЯ ★★★
    from database import get_user_company
    
    user_company = get_user_company(update.message.from_user.id)
    
    keyboard = [
        ["📖 Всё о тренинге"],
        ["💰 Купить доступ"],
        ["🔙 В главное меню"]
    ]
    
    # Если пользователь состоит в компании, добавляем информацию
    message = "🎯 **Каталог тренинга 'Себя верни себе'**\n\n"
    
    if user_company:
        message += f"🏢 **Ваша компания:** {user_company['name']}\n"
        message += f"📅 **Старт тренинга:** {user_company['start_date']}\n\n"
        message += "Выберите раздел:"
    else:
        message += "⚠️ **Вы не состоите в компании!**\n\n"
        message += "Для покупки доступа сначала присоединитесь к компании через профиль.\n\n"
        message += "Выберите раздел:"
    
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

def get_current_and_future_arcs():
    """Получает текущую и будущие дуги для покупки"""

async def buy_arc_from_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию о части и предлагает купить (обновленная логика)"""
    
async def yookassa_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик webhook от Юкассы"""

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для проверки статуса платежей - ИСПРАВЛЕННАЯ"""

async def test_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестовая команда для проверки платежей"""

async def test_payment_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тест платежа - создает платеж 100₽ для тестирования"""

async def check_db_structure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает структуру таблицы payments (упрощенная)"""

async def create_payments_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Создает таблицу payments если её нет"""

async def show_tables(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает список всех таблиц в БД"""

async def test_payment_system(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Полный тест платежной системы"""

async def recreate_payments_table(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пересоздает таблицу payments с правильной структурой"""

async def test_yookassa_keys(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Тестирует подключение к Юкассе - ИСПРАВЛЕННАЯ"""

async def check_my_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет доступы пользователя"""

async def debug_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последний платеж пользователя"""

async def debug_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все активные колбэки"""

async def simple_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простой тест колбэка"""

async def fix_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Исправляет доступ для пользователя"""

async def check_tables(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет и создает таблицы если нужно"""

async def debug_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус регистрации"""

async def reset_registration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сбрасывает регистрацию для тестирования"""

async def debug_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущий статус регистрации и user_data"""

async def start_notification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает процесс создания уведомления"""

async def handle_notification_creation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает создание уведомления"""

async def process_notification_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает контент уведомления (текст + медиа)"""

async def send_notification_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправляет уведомление всем получателям"""

async def update_database_full(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ПОЛНОЕ обновление БД: создает все таблицы, добавляет колонки, сохраняет данные"""

async def check_migration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет готовность к миграции"""

async def verify_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет сохранность критичных данных"""

async def check_yookassa_auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверяет авторизацию в Юкассе"""

async def debug_last_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает последний платеж"""

async def webhook_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает статус webhook"""

def send_payment_notification(user_id, arc_title, amount, payment_id):
    """Отправляет уведомление пользователю об успешной оплате"""

async def manage_webhook(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Управление webhook (только для админа)"""

def start_yookassa_webhook_server():
    """Запускает сервер для вебхуков ЮKассы"""

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Логирует ошибки и отправляет уведомление администратору"""

async def tech_support_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню технической поддержки"""

async def show_instructions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает инструкции (пока в разработке)"""

async def show_author_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает информацию об авторе тренинга (пока в разработке)"""

async def write_to_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Переход в бот поддержки"""

async def load_media_from_excel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загружает медиа-контент из Excel"""

async def load_media_simple(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простая загрузка медиа из Excel"""

async def debug_current_arc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает текущую активную часть"""

async def grant_free_trial_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выдает бесплатный пробный доступ на 3 дня"""

async def get_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простая команда - показывает инструкцию"""

async def cancel_file_id_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выйти из режима получения file_id"""
    
async def get_file_id_easy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Самый простой работающий вариант"""
    
async def handle_admin_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает все файлы от админов"""
    
async def check_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить медиа в базе данных"""
    
async def add_photo_to_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить фото к заданию напрямую"""

async def load_all_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загрузить ВСЕ медиа из Excel (фото, аудио, видео)"""

async def load_tests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда для загрузки тестов из Excel (только админ)"""

async def testing_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню тестирования"""

async def show_available_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает выбор марафона для тестирования"""

async def show_tests_for_arc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает доступные тесты для выбранного марафона"""

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начинает тест - ИСПРАВЛЕННАЯ ЛОГИКА ДОСТУПНОСТИ"""

async def show_question(update: Update, context: ContextTypes.DEFAULT_TYPE, question_num=None):
    """Показывает вопрос теста - ФИНАЛЬНАЯ ВЕРСИЯ"""

async def process_test_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обрабатывает ответ на вопрос теста - ИСПРАВЛЕННАЯ ВЕРСИЯ"""

async def finish_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершает тест и показывает результаты"""

async def show_test_results(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None, arc_id=None, week_num=None):
    """Показывает результаты теста - НОВАЯ ВЕРСИЯ: сначала выбор марафона"""

async def show_tests_for_arc_results(update: Update, context: ContextTypes.DEFAULT_TYPE, arc_id=None, arc_title=None):
    """Показывает тесты выбранного марафона для просмотра результатов"""

async def show_test_result_details(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                   arc_id, arc_title, week_num, score, answers, question_map):
    """Показывает детали результатов теста - ПОЛНАЯ ИСПРАВЛЕННАЯ ВЕРСИЯ"""

async def show_all_test_answers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает все ответы теста (15 вопросов) - ПОЛНАЯ ВЕРСИЯ"""

async def back_to_test_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к результату теста из просмотра всех ответов"""
    
async def back_to_arc_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Возвращает к тестам марафона из просмотра результата"""

async def admin_auto_approved_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню для комментариев к автоматически принятым заданиям"""

async def show_auto_approved_assignment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает автоматически принятое задание для комментария"""

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
