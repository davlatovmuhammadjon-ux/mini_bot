from aiogram.types import (ReplyKeyboardMarkup, KeyboardButton,
                           InlineKeyboardMarkup, InlineKeyboardButton)


def main_menu(is_admin=False, tournament_type="league"):
    rows = [
        [KeyboardButton(text="🏆 Турниры")],
        [KeyboardButton(text="⚽ Результаты"), KeyboardButton(text="📅 Расписание")],
        [KeyboardButton(text="🏆 Таблица"), KeyboardButton(text="🥇 Бомбардиры")],
    ]
    if tournament_type == "cup":
        rows.append([KeyboardButton(text="📊 Группы"), KeyboardButton(text="🎯 Плей-офф")])
    rows.extend([
        [KeyboardButton(text="📋 Команды"), KeyboardButton(text="👥 Игроки")],
        [KeyboardButton(text="📤 Экспорт"), KeyboardButton(text="ℹ️ Помощь")],
    ])
    if is_admin:
        rows.append([KeyboardButton(text="🔐 Админы")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def teams_kb(teams, action):
    buttons = [[InlineKeyboardButton(text=t["name"], callback_data=f"{action}:{t['id']}")]
               for t in teams]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_main_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])


def offer_scorers_kb(match_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚽ Записать голы", callback_data=f"scorers_yes:{match_id}")],
        [InlineKeyboardButton(text="✅ Пропустить", callback_data=f"scorers_no:{match_id}")]])