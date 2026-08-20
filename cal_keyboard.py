import calendar as pycal
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
             "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
DAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def build_calendar_kb(year, month):
    buttons = [
        [InlineKeyboardButton(text="◀️", callback_data=f"cal:nav:{year}:{month}:-1"),
         InlineKeyboardButton(text=f"{MONTHS_RU[month-1]} {year}", callback_data="cal:noop"),
         InlineKeyboardButton(text="▶️", callback_data=f"cal:nav:{year}:{month}:1")],
        [InlineKeyboardButton(text=d, callback_data="cal:noop") for d in DAYS_RU],
    ]
    for week in pycal.monthcalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text="·", callback_data="cal:noop"))
            else:
                row.append(InlineKeyboardButton(text=str(day), callback_data=f"cal:day:{year}:{month}:{day}"))
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton(text="📌 Сегодня", callback_data="cal:today"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cal:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_hour_kb():
    buttons = []
    for i in range(0, 24, 6):
        buttons.append([InlineKeyboardButton(text=f"{h:02d}", callback_data=f"timeh:{h}")
                        for h in range(i, i + 6)])
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cal:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_minute_kb(hour):
    minutes = list(range(0, 60, 5))
    buttons = []
    for i in range(0, len(minutes), 4):
        buttons.append([InlineKeyboardButton(text=f"{m:02d}", callback_data=f"timem:{hour}:{m}")
                        for m in minutes[i:i + 4]])
    buttons.append([
        InlineKeyboardButton(text="◀️ Часы", callback_data="time:backh"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cal:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)