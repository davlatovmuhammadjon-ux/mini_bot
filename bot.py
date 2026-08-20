import asyncio
import calendar as pycal
import logging
import os
import random
import re
from datetime import datetime, date
from io import BytesIO

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton, BufferedInputFile)

import database as db
from config import BOT_TOKEN, OWNER_ID
from keyboards import main_menu, teams_kb, back_main_kb, offer_scorers_kb
from cal_keyboard import build_calendar_kb, build_hour_kb, build_minute_kb
from export import build_standings_text, render_standings_image

logging.basicConfig(level=logging.INFO)

LOGOS_DIR = "logos"
os.makedirs(LOGOS_DIR, exist_ok=True)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())


# ================== СОСТОЯНИЯ ==================
class AddTeam(StatesGroup):
    name = State()

class AddPlayer(StatesGroup):
    name = State()

class AddMatch(StatesGroup):
    home = State()
    away = State()
    date = State()
    time = State()
    stadium = State()
    score = State()

class AddFixture(StatesGroup):
    home = State()
    away = State()
    date = State()
    time = State()
    stadium = State()

class EnterResult(StatesGroup):
    score = State()

class RecordGoals(StatesGroup):
    active = State()

class AddAdmin(StatesGroup):
    uid = State()

class SetLogo(StatesGroup):
    photo = State()

class CreateTournament(StatesGroup):
    type_ = State()
    subtype = State()
    name = State()
    teams = State()
class AddTeamsToTournament(StatesGroup):
    active = State()

class CupGroups(StatesGroup):
    num = State()


# ================== ПРАВА ==================
def is_owner(user_id):
    if OWNER_ID != 0 and user_id == OWNER_ID:
        return True
    return db.get_owner() == user_id


def is_admin(user_id):
    return is_owner(user_id) or db.is_admin(user_id)


async def deny_message(message, text="⛔ Это действие доступно только администраторам."):
    await message.answer(text)


async def deny_callback(callback, text="⛔ Недостаточно прав"):
    await callback.answer(text, show_alert=True)


# ================== УТИЛИТЫ ==================
def format_date(iso):
    try:
        return datetime.strptime(iso, "%Y-%m-%d %H:%M").strftime("%d.%m.%Y %H:%M")
    except Exception:
        return iso


def _clean_stadium(text):
    s = text.strip()
    return None if s.lower() in ("нет", "-", "no", "0", "без стадиона") else s


def get_current_menu(uid):
    t = db.get_active_tournament()
    t_type = t["type"] if t else "league"
    return main_menu(is_admin=is_admin(uid), tournament_type=t_type)


MAIN_MENU_BUTTONS = {
    "⚽ Результаты", "📅 Расписание", "🏆 Таблица", "🥇 Бомбардиры",
    "📋 Команды", "👥 Игроки", "📤 Экспорт", "ℹ️ Помощь", "🔐 Админы",
    "🏆 Турниры", "📊 Группы", "🎯 Плей-офф"
}

INPUT_STATES = [
    AddTeam.name, AddPlayer.name,
    AddMatch.stadium, AddMatch.score,
    AddFixture.stadium, EnterResult.score, AddAdmin.uid,
    CreateTournament.name
]


# ================== ТЕКСТОВЫЕ ХЕЛПЕРЫ ==================
def teams_list_text(tid):
    teams = db.get_tournament_teams(tid) if tid else []
    if not teams:
        return "Команд в турнире нет."
    return "<b>📋 Команды</b>\n\n" + "\n".join(
        f"• {t['name']}{' 🖼' if t['logo'] else ''}" for t in teams)


def teams_manage_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить команду в турнир", callback_data="tt_add")],
        [InlineKeyboardButton(text="➖ Убрать из турнира", callback_data="tt_del")],
        [InlineKeyboardButton(text="🖼 Установить логотип", callback_data="team_logo")],
        [InlineKeyboardButton(text="❌ Убрать логотип", callback_data="team_logo_del_menu")],
        [InlineKeyboardButton(text="🗑 Удалить команду (из БД)", callback_data="team_del")],
        [InlineKeyboardButton(text="🆕 Создать команду", callback_data="team_add")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])


def results_lines(limit=25):
    t = db.get_active_tournament()
    if not t:
        return []
    lines = []
    for m in db.get_played_matches(t["id"])[:limit]:
        stage_label = ""
        if m["stage"] not in ("regular",):
            stage_label = f" [{m['stage']}]"
        line = f"• {m['home_name']} {m['home_score']}:{m['away_score']} {m['away_name']}{stage_label}  ·  {format_date(m['date'])}"
        if m["stadium"]:
            line += f"\n     🏟️ {m['stadium']}"
        lines.append(line)
    return lines


def schedule_lines(limit=25):
    t = db.get_active_tournament()
    if not t:
        return []
    lines = []
    for m in db.get_upcoming_matches(t["id"])[:limit]:
        stage_label = ""
        if m["stage"] not in ("regular",):
            stage_label = f" [{m['stage']}]"
        line = f"• {format_date(m['date'])} — {m['home_name']} vs {m['away_name']}{stage_label}"
        if m["stadium"]:
            line += f"\n     🏟️ {m['stadium']}"
        lines.append(line)
    return lines


def results_text():
    t = db.get_active_tournament()
    lines = results_lines()
    header = f"<b>⚽ Результаты «{t['name']}»</b>\n\n" if t else "<b>⚽ Результаты</b>\n\n"
    return (header + "\n".join(lines)) if lines else header + "Сыгранных матчей пока нет."


def schedule_text():
    t = db.get_active_tournament()
    lines = schedule_lines()
    header = f"<b>📅 Расписание «{t['name']}»</b>\n\n" if t else "<b>📅 Расписание</b>\n\n"
    return (header + "\n".join(lines)) if lines else header + "Запланированных матчей нет."


def results_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить результат", callback_data="match_add")],
        [InlineKeyboardButton(text="🗑 Удалить матч", callback_data="match_del")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])


def schedule_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Запланировать матч", callback_data="fixture_add")],
        [InlineKeyboardButton(text="✏️ Ввести результат", callback_data="fixture_result_menu")],
        [InlineKeyboardButton(text="🗑 Удалить матч", callback_data="fixture_del_menu")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])


def format_standings():
    t = db.get_active_tournament()
    if not t:
        return "Нет активного турнира."
    standings = db.get_standings(t["id"])
    if not standings:
        return f"Таблица «{t['name']}» пуста."
    
    if t["type"] == "amateur":
        # Для любительского турнира показываем процент побед
        lines = [f"{'№':<3}{'Команда':<14}{'И':<3}{'В':<3}{'Н':<3}{'П':<3}{'%':<5}{'ГЗ':<4}{'ГП':<4}"]
        for i, s in enumerate(standings, 1):
            win_pct = f"{s['win_pct']:.0%}"
            lines.append(f"{i:<3}{s['name'][:13]:<14}{s['played']:<3}{s['wins']:<3}{s['draws']:<3}"
                         f"{s['losses']:<3}{win_pct:<5}{s['gf']:<4}{s['ga']:<4}")
        return f"<b>🎯 {t['name']}</b> (по % побед)\n<pre>" + "\n".join(lines) + "</pre>"
    else:
        # Обычная таблица с очками
        lines = [f"{'№':<3}{'Команда':<16}{'И':<3}{'В':<3}{'Н':<3}{'П':<3}{'ГЗ':<4}{'ГП':<4}{'О':<3}"]
        for i, s in enumerate(standings, 1):
            lines.append(f"{i:<3}{s['name'][:15]:<16}{s['played']:<3}{s['wins']:<3}{s['draws']:<3}"
                         f"{s['losses']:<3}{s['gf']:<4}{s['ga']:<4}{s['points']:<3}")
        return f"<b>🏆 {t['name']}</b>\n<pre>" + "\n".join(lines) + "</pre>"

def goals_progress_text(match_id):
    m = db.get_match(match_id)
    home = db.get_team_by_id(m["home_team_id"])
    away = db.get_team_by_id(m["away_team_id"])
    hg = db.count_goals_for_match_team(match_id, m["home_team_id"])
    ag = db.count_goals_for_match_team(match_id, m["away_team_id"])
    return (f"⚽ <b>Запись голов</b>\n"
            f"<b>{home['name']}</b> {m['home_score']}:{m['away_score']} <b>{away['name']}</b>\n"
            f"🏠 Записано: {hg}/{m['home_score']}   ✈️ Записано: {ag}/{m['away_score']}\n\n"
            f"Нажимайте на игроков, которые забили:")


def goals_kb(match_id):
    m = db.get_match(match_id)
    home = db.get_team_by_id(m["home_team_id"])
    away = db.get_team_by_id(m["away_team_id"])
    buttons = [[InlineKeyboardButton(text=f"— {home['name']} —", callback_data="noop")]]
    for p in db.get_players(home["id"]):
        buttons.append([InlineKeyboardButton(text=f"⚽ {p['name']}",
                       callback_data=f"goal:{match_id}:{p['id']}:{home['id']}")])
    buttons.append([InlineKeyboardButton(text=f"— {away['name']} —", callback_data="noop")])
    for p in db.get_players(away["id"]):
        buttons.append([InlineKeyboardButton(text=f"⚽ {p['name']}",
                       callback_data=f"goal:{match_id}:{p['id']}:{away['id']}")])
    buttons.append([InlineKeyboardButton(text="✅ Завершить запись",
                   callback_data=f"goals_done:{match_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def format_match_scorers(match_id):
    goals = db.get_goals_for_match(match_id)
    return ("<b>Голы:</b>\n" + "\n".join(f"⚽ {g['player']} ({g['team']})" for g in goals)) \
        if goals else "Авторы голов не указаны."


# ================== СТАРТ / ПОМОЩЬ ==================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    uid = message.from_user.id
    if OWNER_ID == 0 and db.get_owner() is None:
        db.set_owner(uid)
        await message.answer(f"👑 Вы назначены владельцем бота.\nВаш ID: <code>{uid}</code>")
    await message.answer(
        "⚽ <b>Футбольный журнал</b>\n\n"
        "Всё для любительского чемпионата:\n"
        "🏆 Чемпионаты и кубки\n"
        "📋 Команды и 👥 составы\n"
        "📅 Календарь и ⚽ результаты\n"
        "🏆 Таблица и 🥇 бомбардиры\n\n"
        "Выберите раздел 👇",
        reply_markup=get_current_menu(uid))


@dp.message(Command("help"))
@dp.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Разделы</b>\n\n"
        "🏆 Турниры — создание чемпионатов/кубков\n"
        "⚽ Результаты — сыгранные матчи\n"
        "📅 Расписание — календарь будущих игр\n"
        "🏆 Таблица — автоподсчёт очков\n"
        "🥇 Бомбардиры — лучшие снайперы\n"
        "📊 Группы — для кубков\n"
        "🎯 Плей-офф — стадии кубков\n"
        "📋 Команды / 👥 Игроки — составы\n"
        "📤 Экспорт — таблица текстом/картинкой\n"
        "🔐 Админы — управление доступом\n\n"
        "Узнать свой ID: /id\nОтмена действия: /cancel")


@dp.message(Command("id"))
async def cmd_id(message: Message):
    await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")


@dp.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.", reply_markup=get_current_menu(message.from_user.id))


@dp.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()


@dp.message(StateFilter(*INPUT_STATES), F.text.in_(MAIN_MENU_BUTTONS))
async def menu_button_during_input(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✋ Ввод отменён. Вы вернулись в меню.",
                         reply_markup=get_current_menu(message.from_user.id))


# ================== КОМАНДЫ ==================
@dp.message(F.text == "📋 Команды")
async def teams_menu(message: Message):
    t = db.get_active_tournament()
    teams = db.get_tournament_teams(t["id"]) if t else []
    text = f"<b>📋 Команды турнира «{t['name']}»</b>\n\n" if t else "<b>📋 Команды</b>\n\n"
    text += (
        "\n".join(f"• {team['name']}{' 🖼' if team['logo'] else ''}" for team in teams)
        if teams else "Команд в этом турнире нет.")
    await message.answer(text, reply_markup=teams_manage_kb())


@dp.callback_query(F.data == "team_add")
async def team_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    await state.set_state(AddTeam.name)
    await callback.message.edit_text("Введите название команды:\n(или /cancel)")
    await callback.answer()


@dp.message(AddTeam.name)
async def team_add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if db.get_team(name):
        return await message.answer("Такая команда уже есть. Введите другое название:")
    db.add_team(name)
    await state.clear()
    await message.answer(f"✅ Команда <b>{name}</b> добавлена!",
                         reply_markup=get_current_menu(message.from_user.id))


@dp.callback_query(F.data == "tt_add")
async def tt_add(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    if not t:
        return await callback.answer("Сначала создайте турнир", show_alert=True)
    all_teams = db.get_teams()
    in_t = {r["id"] for r in db.get_tournament_teams(t["id"])}
    available = [team for team in all_teams if team["id"] not in in_t]
    if not available:
        return await callback.answer("Все команды уже в турнире", show_alert=True)
    await callback.message.edit_text("Выберите команду для добавления:",
                                     reply_markup=teams_kb(available, "ttadd"))
    await callback.answer()


@dp.callback_query(F.data.startswith("ttadd:"))
async def tt_add_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    team_id = int(callback.data.split(":")[1])
    db.add_team_to_tournament(t["id"], team_id)
    await callback.answer("Добавлено в турнир")
    teams = db.get_tournament_teams(t["id"])
    text = f"<b>📋 Команды турнира «{t['name']}»</b>\n\n" + "\n".join(
        f"• {tm['name']}{' 🖼' if tm['logo'] else ''}" for tm in teams)
    await callback.message.edit_text(text, reply_markup=teams_manage_kb())


@dp.callback_query(F.data == "tt_del")
async def tt_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    if not t: return await callback.answer("Нет турнира", show_alert=True)
    teams = db.get_tournament_teams(t["id"])
    if not teams:
        return await callback.answer("Команд нет", show_alert=True)
    await callback.message.edit_text("Кого убрать из турнира?",
                                     reply_markup=teams_kb(teams, "ttrm"))
    await callback.answer()


@dp.callback_query(F.data.startswith("ttrm:"))
async def tt_rm_done(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    team_id = int(callback.data.split(":")[1])
    db.remove_team_from_tournament(t["id"], team_id)
    await callback.answer("Убрано из турнира")
    teams = db.get_tournament_teams(t["id"])
    text = f"<b>📋 Команды турнира «{t['name']}»</b>\n\n" + (
        "\n".join(f"• {tm['name']}{' 🖼' if tm['logo'] else ''}" for tm in teams)
        if teams else "Команд в этом турнире нет.")
    await callback.message.edit_text(text, reply_markup=teams_manage_kb())


@dp.callback_query(F.data == "team_del")
async def team_del_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    teams = db.get_teams()
    if not teams: return await callback.answer("Команд нет", show_alert=True)
    await callback.message.edit_text("Какую команду удалить из БД?",
                                     reply_markup=teams_kb(teams, "teamdel"))  # ← было "tdel"
    await callback.answer()


@dp.callback_query(F.data.startswith("teamdel:"))  # ← было "tdel:"
async def team_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    team_id = int(callback.data.split(":")[1])
    team = db.get_team_by_id(team_id)
    if team and team["logo"] and os.path.exists(team["logo"]):
        os.remove(team["logo"])
    name = db.delete_team_by_id(team_id)
    await callback.answer(f"Команда '{name}' удалена")
    t = db.get_active_tournament()
    await callback.message.edit_text(teams_list_text(t["id"] if t else None),
                                     reply_markup=teams_manage_kb())

# ================== БЫСТРЫЕ КОМАНДЫ /nclub /nclubs ==================
@dp.message(Command("nclub"))
async def cmd_nclub(message: Message):
    if not is_admin(message.from_user.id):
        return await deny_message(message)
    args = message.text.split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        return await message.answer(
            "❌ Укажите название.\nПример: <code>/nclub ФК Хосилот</code>")
    name = args[1].strip()
    if db.get_team(name):
        return await message.answer(f"⚠️ Команда <b>{name}</b> уже существует.")
    db.add_team(name)  # автоматически попадёт в активный турнир
    t = db.get_active_tournament()
    tournament_info = f"\n🏆 Добавлена в: <b>{t['name']}</b>" if t else ""
    await message.answer(
        f"✅ Команда <b>{name}</b> создана!{tournament_info}\n\n"
        f"Добавить ещё? Просто отправьте:\n<code>/nclub Название</code>",
        reply_markup=get_current_menu(message.from_user.id))


@dp.message(Command("nclubs"))
async def cmd_nclubs(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await deny_message(message)
    args = message.text.split(maxsplit=1)
    # Если названия переданы сразу после команды — обработаем
    if len(args) > 1 and args[1].strip():
        return await _process_bulk_names(message, args[1])
    # Иначе — просим прислать списком
    await state.set_state(BulkAddTeams.names)
    await message.answer(
        "📋 <b>Массовое добавление команд</b>\n\n"
        "Отправьте список — каждое название с новой строки:\n\n"
        "<code>ФК Хосилот\nФК Рахш\nФК Дружба\nФК Звезда</code>\n\n"
        "Для отмены: /cancel")


class BulkAddTeams(StatesGroup):
    names = State()


@dp.message(BulkAddTeams.names)
async def bulk_add_process(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return await deny_message(message)
    result = await _process_bulk_names(message, message.text)
    await state.clear()
    return result


async def _process_bulk_names(message: Message, text: str):
    # Разбиваем по переносам строк, запятым, точкам с запятой
    raw = re.split(r"[\n,;]+", text)
    names = [n.strip() for n in raw if n.strip()]
    if not names:
        return await message.answer("❌ Список пуст.")
    created = []
    duplicates = []
    for name in names:
        if db.get_team(name):
            duplicates.append(name)
        else:
            db.add_team(name)
            created.append(name)
    t = db.get_active_tournament()
    tournament_info = f"\n🏆 Турнир: <b>{t['name']}</b>" if t else ""
    report = f"<b>📋 Результат</b>{tournament_info}\n\n"
    if created:
        report += f"✅ <b>Создано ({len(created)}):</b>\n" + "\n".join(f"• {n}" for n in created) + "\n\n"
    if duplicates:
        report += f"⚠️ <b>Уже существовали ({len(duplicates)}):</b>\n" + "\n".join(f"• {n}" for n in duplicates)
    report += "\n\n💡 Ещё можно: <code>/nclub Название</code>"
    await message.answer(report, reply_markup=get_current_menu(message.from_user.id))
# ================== ЛОГОТИПЫ ==================
@dp.callback_query(F.data == "team_logo")
async def team_logo_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    teams = db.get_teams()
    if not teams: return await callback.answer("Команд нет", show_alert=True)
    await callback.message.edit_text("Какой команде установить логотип?",
                                     reply_markup=teams_kb(teams, "logo"))
    await callback.answer()


@dp.callback_query(F.data.startswith("logo:"))
async def team_logo_choose(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    team_id = int(callback.data.split(":")[1])
    await state.set_state(SetLogo.photo)
    await state.update_data(team_id=team_id)
    team = db.get_team_by_id(team_id)
    await callback.message.edit_text(
        f"📷 Пришли картинку-логотип для <b>{team['name']}</b>\n(или /cancel)")
    await callback.answer()


@dp.message(SetLogo.photo, F.photo)
async def team_logo_save(message: Message, state: FSMContext):
    data = await state.get_data()
    team_id = data["team_id"]
    path = os.path.join(LOGOS_DIR, f"team_{team_id}.jpg")
    await bot.download(message.photo[-1], destination=path)
    db.set_team_logo(team_id, path)
    await state.clear()
    team = db.get_team_by_id(team_id)
    await message.answer_photo(BufferedInputFile.from_file(path),
                               caption=f"✅ Логотип <b>{team['name']}</b> установлен!",
                               reply_markup=get_current_menu(message.from_user.id))


@dp.message(SetLogo.photo)
async def team_logo_bad(message: Message):
    await message.answer("Нужно отправить именно картинку (фото). Попробуй ещё раз 📷")


@dp.callback_query(F.data == "team_logo_del_menu")
async def team_logo_del_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    teams = [t for t in db.get_teams() if t["logo"]]
    if not teams:
        return await callback.answer("Ни у одной команды нет логотипа", show_alert=True)
    await callback.message.edit_text("У какой команды убрать логотип?",
                                     reply_markup=teams_kb(teams, "logodel"))
    await callback.answer()


@dp.callback_query(F.data.startswith("logodel:"))
async def team_logo_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    team = db.get_team_by_id(int(callback.data.split(":")[1]))
    if team["logo"] and os.path.exists(team["logo"]):
        os.remove(team["logo"])
    db.clear_team_logo(team["id"])
    await callback.answer(f"Логотип '{team['name']}' удалён")
    t = db.get_active_tournament()
    await callback.message.edit_text(teams_list_text(t["id"] if t else None),
                                     reply_markup=teams_manage_kb())


@dp.callback_query(F.data.startswith("showlogo:"))
async def show_logo(callback: CallbackQuery):
    team = db.get_team_by_id(int(callback.data.split(":")[1]))
    if team["logo"] and os.path.exists(team["logo"]):
        await callback.message.answer_photo(BufferedInputFile.from_file(team["logo"]),
                                            caption=f"🖼 <b>{team['name']}</b>")
    await callback.answer()


# ================== ИГРОКИ ==================
@dp.message(F.text == "👥 Игроки")
async def players_menu(message: Message):
    teams = db.get_teams()
    if not teams:
        return await message.answer("Сначала добавьте команду.",
                                    reply_markup=get_current_menu(message.from_user.id))
    await message.answer("Выберите команду:", reply_markup=teams_kb(teams, "players_team"))


@dp.callback_query(F.data.startswith("players_team:"))
async def show_team_players(callback: CallbackQuery):
    team_id = int(callback.data.split(":")[1])
    team = db.get_team_by_id(team_id)
    players = db.get_players(team_id)
    text = f"👥 <b>{team['name']}</b>\n" + (
        "\n".join(f"• {p['name']}" for p in players) if players else "Игроков пока нет.")
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить игрока", callback_data=f"player_add:{team_id}")],
        [InlineKeyboardButton(text="🗑 Удалить игрока", callback_data=f"player_del:{team_id}")]]
    if team["logo"]:
        buttons.append([InlineKeyboardButton(text="🖼 Логотип", callback_data=f"showlogo:{team_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="players_back")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("player_add:"))
async def player_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    await state.set_state(AddPlayer.name)
    await state.update_data(team_id=int(callback.data.split(":")[1]))
    await callback.message.edit_text("Введите имя игрока:\n(или /cancel)")
    await callback.answer()


@dp.message(AddPlayer.name)
async def player_add_name(message: Message, state: FSMContext):
    data = await state.get_data()
    team_id = data["team_id"]
    name = message.text.strip()
    db.add_player(team_id, name)
    await state.clear()
    team = db.get_team_by_id(team_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить ещё", callback_data=f"player_add:{team_id}")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await message.answer(f"✅ Игрок <b>{name}</b> добавлен в <b>{team['name']}</b>", reply_markup=kb)


@dp.callback_query(F.data.startswith("player_del:"))
async def player_del_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    team_id = int(callback.data.split(":")[1])
    players = db.get_players(team_id)
    if not players: return await callback.answer("Игроков нет", show_alert=True)
    buttons = [[InlineKeyboardButton(text=p["name"], callback_data=f"pdel:{team_id}:{p['id']}")]
               for p in players]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data=f"players_team:{team_id}")])
    await callback.message.edit_text("Кого удалить?",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("pdel:"))
async def player_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    _, team_id, player_id = callback.data.split(":")
    team_id, player_id = int(team_id), int(player_id)
    name = db.delete_player_by_id(player_id)
    await callback.answer(f"Удалён: {name}")
    team = db.get_team_by_id(team_id)
    players = db.get_players(team_id)
    text = f"👥 <b>{team['name']}</b>\n" + (
        "\n".join(f"• {p['name']}" for p in players) if players else "Игроков пока нет.")
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить игрока", callback_data=f"player_add:{team_id}")],
        [InlineKeyboardButton(text="🗑 Удалить игрока", callback_data=f"player_del:{team_id}")]]
    if team["logo"]:
        buttons.append([InlineKeyboardButton(text="🖼 Логотип", callback_data=f"showlogo:{team_id}")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="players_back")])
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


# ================== РЕЗУЛЬТАТЫ ==================
@dp.message(F.text == "⚽ Результаты")
async def results_menu(message: Message):
    await message.answer(results_text(), reply_markup=results_menu_kb())


@dp.callback_query(F.data == "match_add")
async def match_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    if not t:
        return await callback.answer("Нет активного турнира", show_alert=True)
    teams = db.get_tournament_teams(t["id"])
    if len(teams) < 2:
        return await callback.answer("Нужно минимум 2 команды", show_alert=True)
    await state.set_state(AddMatch.home)
    await callback.message.edit_text("🏠 Выберите домашнюю команду:",
                                     reply_markup=teams_kb(teams, "home"))
    await callback.answer()


@dp.callback_query(StateFilter(AddMatch.home), F.data.startswith("home:"))
async def match_home(callback: CallbackQuery, state: FSMContext):
    home_id = int(callback.data.split(":")[1])
    await state.update_data(home_id=home_id)
    await state.set_state(AddMatch.away)
    t = db.get_active_tournament()
    teams = [tm for tm in db.get_tournament_teams(t["id"]) if tm["id"] != home_id]
    home = db.get_team_by_id(home_id)
    await callback.message.edit_text(f"🏠 Дом: <b>{home['name']}</b>\n✈️ Выберите гостевую команду:",
                                     reply_markup=teams_kb(teams, "away"))
    await callback.answer()


@dp.callback_query(StateFilter(AddMatch.away), F.data.startswith("away:"))
async def match_away(callback: CallbackQuery, state: FSMContext):
    away_id = int(callback.data.split(":")[1])
    await state.update_data(away_id=away_id)
    await state.set_state(AddMatch.date)
    now = datetime.now()
    await callback.message.edit_text("📅 Выберите дату матча:",
                                     reply_markup=build_calendar_kb(now.year, now.month))
    await callback.answer()


@dp.message(AddMatch.stadium)
async def match_stadium(message: Message, state: FSMContext):
    await state.update_data(stadium=_clean_stadium(message.text))
    await state.set_state(AddMatch.score)
    await message.answer("🔢 Введите счёт в формате <code>3:1</code>:")


@dp.message(AddMatch.score)
async def match_score(message: Message, state: FSMContext):
    m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)$", message.text.strip())
    if not m:
        return await message.answer("Неверный формат. Пример: <code>3:1</code>")
    hs, as_ = int(m.group(1)), int(m.group(2))
    data = await state.get_data()
    t = db.get_active_tournament()
    match_id = db.add_match(t["id"], data["home_id"], data["away_id"], hs, as_,
                            data["date"], data.get("stadium"))
    await state.clear()
    home = db.get_team_by_id(data["home_id"])
    away = db.get_team_by_id(data["away_id"])
    st = f"\n🏟️ {data['stadium']}" if data.get("stadium") else ""
    await message.answer(
        f"✅ <b>Матч записан</b>\n⚽ {home['name']} {hs}:{as_} {away['name']}\n🗓 {format_date(data['date'])}{st}",
        reply_markup=offer_scorers_kb(match_id))


@dp.callback_query(F.data == "match_del")
async def match_del_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    matches = db.get_played_matches(t["id"]) if t else []
    if not matches: return await callback.answer("Матчей нет", show_alert=True)
    buttons = [[InlineKeyboardButton(
        text=f"{m['home_name']} {m['home_score']}:{m['away_score']} {m['away_name']}",
        callback_data=f"mdel:{m['id']}")] for m in matches[:30]]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="matches_back")])
    await callback.message.edit_text("Какой матч удалить?",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("mdel:"))
async def match_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    db.delete_match(int(callback.data.split(":")[1]))
    await callback.answer("Матч удалён")
    await callback.message.edit_text(results_text(), reply_markup=results_menu_kb())


# ================== РАСПИСАНИЕ ==================
@dp.message(F.text == "📅 Расписание")
async def schedule_menu(message: Message):
    await message.answer(schedule_text(), reply_markup=schedule_menu_kb())


@dp.callback_query(F.data == "fixture_add")
async def fixture_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    if not t:
        return await callback.answer("Нет активного турнира", show_alert=True)
    teams = db.get_tournament_teams(t["id"])
    if len(teams) < 2: return await callback.answer("Нужно минимум 2 команды", show_alert=True)
    await state.set_state(AddFixture.home)
    await callback.message.edit_text("🏠 Выберите домашнюю команду:",
                                     reply_markup=teams_kb(teams, "fhome"))
    await callback.answer()


@dp.callback_query(StateFilter(AddFixture.home), F.data.startswith("fhome:"))
async def fixture_home(callback: CallbackQuery, state: FSMContext):
    home_id = int(callback.data.split(":")[1])
    await state.update_data(home_id=home_id)
    await state.set_state(AddFixture.away)
    t = db.get_active_tournament()
    teams = [tm for tm in db.get_tournament_teams(t["id"]) if tm["id"] != home_id]
    home = db.get_team_by_id(home_id)
    await callback.message.edit_text(f"🏠 Дом: <b>{home['name']}</b>\n✈️ Выберите гостевую команду:",
                                     reply_markup=teams_kb(teams, "faway"))
    await callback.answer()


@dp.callback_query(StateFilter(AddFixture.away), F.data.startswith("faway:"))
async def fixture_away(callback: CallbackQuery, state: FSMContext):
    away_id = int(callback.data.split(":")[1])
    await state.update_data(away_id=away_id)
    await state.set_state(AddFixture.date)
    now = datetime.now()
    await callback.message.edit_text("📅 Выберите дату матча:",
                                     reply_markup=build_calendar_kb(now.year, now.month))
    await callback.answer()


@dp.message(AddFixture.stadium)
async def fixture_stadium(message: Message, state: FSMContext):
    data = await state.get_data()
    stadium = _clean_stadium(message.text)
    t = db.get_active_tournament()
    match_id = db.add_fixture(t["id"], data["home_id"], data["away_id"], data["date"], stadium)
    await state.clear()
    home = db.get_team_by_id(data["home_id"])
    away = db.get_team_by_id(data["away_id"])
    st = f"\n🏟️ {stadium}" if stadium else ""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Ввести результат", callback_data=f"fres:{match_id}")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await message.answer(
        f"📅 <b>Матч запланирован</b>\n⚽ {home['name']} — {away['name']}\n"
        f"🗓 {format_date(data['date'])}{st}", reply_markup=kb)


@dp.callback_query(F.data == "fixture_result_menu")
async def fixture_result_menu(callback: CallbackQuery):
    t = db.get_active_tournament()
    upcoming = db.get_upcoming_matches(t["id"]) if t else []
    if not upcoming: return await callback.answer("Нет запланированных матчей", show_alert=True)
    buttons = [[InlineKeyboardButton(
        text=f"{m['home_name']} vs {m['away_name']} ({format_date(m['date'])})",
        callback_data=f"fres:{m['id']}")] for m in upcoming[:30]]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="schedule_back")])
    await callback.message.edit_text("Выберите матч:",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("fres:"))
async def fixture_enter_result(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    match_id = int(callback.data.split(":")[1])
    m = db.get_match(match_id)
    if not m or m["home_score"] is not None:
        return await callback.answer("Матч уже сыгран или не найден", show_alert=True)
    await state.set_state(EnterResult.score)
    await state.update_data(match_id=match_id)
    home = db.get_team_by_id(m["home_team_id"])
    away = db.get_team_by_id(m["away_team_id"])
    st = f"\n🏟️ {m['stadium']}" if m["stadium"] else ""
    await callback.message.edit_text(
        f"⚽ <b>{home['name']}</b> — <b>{away['name']}</b>\n"
        f"🗓 {format_date(m['date'])}{st}\n\n"
        f"🔢 Введите счёт в формате <code>3:1</code>:")
    await callback.answer()


@dp.message(EnterResult.score)
async def enter_result(message: Message, state: FSMContext):
    m = re.match(r"^(\d+)\s*[:\-]\s*(\d+)$", message.text.strip())
    if not m:
        return await message.answer("Неверный формат. Пример: <code>3:1</code>")
    hs, as_ = int(m.group(1)), int(m.group(2))
    data = await state.get_data()
    db.set_match_score(data["match_id"], hs, as_)
    await state.clear()
    match = db.get_match(data["match_id"])
    home = db.get_team_by_id(match["home_team_id"])
    away = db.get_team_by_id(match["away_team_id"])
    await message.answer(
        f"✅ Результат записан: <b>{home['name']}</b> {hs}:{as_} <b>{away['name']}</b>",
        reply_markup=offer_scorers_kb(data["match_id"]))


@dp.callback_query(F.data == "fixture_del_menu")
async def fixture_del_menu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    matches = db.get_upcoming_matches(t["id"]) if t else []
    if not matches: return await callback.answer("Нет запланированных матчей", show_alert=True)
    buttons = [[InlineKeyboardButton(
        text=f"{m['home_name']} vs {m['away_name']} ({format_date(m['date'])})",
        callback_data=f"fdel:{m['id']}")] for m in matches[:30]]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="schedule_back")])
    await callback.message.edit_text("Какой матч удалить?",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("fdel:"))
async def fixture_del(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    db.delete_match(int(callback.data.split(":")[1]))
    await callback.answer("Матч удалён")
    await callback.message.edit_text(schedule_text(), reply_markup=schedule_menu_kb())


# ================== КАЛЕНДАРЬ / ВРЕМЯ ==================
@dp.callback_query(F.data == "cal:noop")
async def cal_noop(cb: CallbackQuery):
    await cb.answer()


@dp.callback_query(F.data.startswith("cal:nav:"))
async def cal_nav(cb: CallbackQuery, state: FSMContext):
    _, _, y, m, d = cb.data.split(":")
    y, m, d = int(y), int(m), int(d)
    m += d
    if m < 1:
        m, y = 12, y - 1
    elif m > 12:
        m, y = 1, y + 1
    await cb.message.edit_reply_markup(reply_markup=build_calendar_kb(y, m))
    await cb.answer()


async def _start_time(state, cb):
    cur = await state.get_state()
    if cur == AddMatch.date.state:
        await state.set_state(AddMatch.time)
    elif cur == AddFixture.date.state:
        await state.set_state(AddFixture.time)
    await cb.message.edit_text("⏰ Выберите час начала матча:", reply_markup=build_hour_kb())


@dp.callback_query(F.data == "cal:today")
async def cal_today(cb: CallbackQuery, state: FSMContext):
    t = date.today()
    await state.update_data(year=t.year, month=t.month, day=t.day)
    await _start_time(state, cb)
    await cb.answer()


@dp.callback_query(F.data.startswith("cal:day:"))
async def cal_day(cb: CallbackQuery, state: FSMContext):
    _, _, y, m, d = cb.data.split(":")
    await state.update_data(year=int(y), month=int(m), day=int(d))
    await _start_time(state, cb)
    await cb.answer()


@dp.callback_query(F.data == "cal:cancel")
async def cal_cancel(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("Отменено.", reply_markup=back_main_kb())
    await cb.answer()


@dp.callback_query(F.data.startswith("timeh:"))
async def timeh(cb: CallbackQuery, state: FSMContext):
    hour = int(cb.data.split(":")[1])
    await state.update_data(hour=hour)
    await cb.message.edit_text(f"⏰ Час: <b>{hour:02d}:00</b>\nВыберите минуты:",
                               reply_markup=build_minute_kb(hour))
    await cb.answer()


@dp.callback_query(F.data == "time:backh")
async def time_backh(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text("⏰ Выберите час начала матча:", reply_markup=build_hour_kb())
    await cb.answer()


@dp.callback_query(F.data.startswith("timem:"))
async def timem(cb: CallbackQuery, state: FSMContext):
    _, hour, minute = cb.data.split(":")
    hour, minute = int(hour), int(minute)
    data = await state.get_data()
    dt = datetime(data["year"], data["month"], data["day"], hour, minute)
    date_iso = dt.strftime("%Y-%m-%d %H:%M")
    await state.update_data(date=date_iso)
    home = db.get_team_by_id(data["home_id"])
    away = db.get_team_by_id(data["away_id"])
    cur = await state.get_state()
    if cur == AddMatch.time.state:
        await state.set_state(AddMatch.stadium)
    elif cur == AddFixture.time.state:
        await state.set_state(AddFixture.stadium)
    await cb.message.edit_text(
        f"⚽ <b>{home['name']}</b> — <b>{away['name']}</b>\n🗓 {format_date(date_iso)}\n\n"
        f"🏟️ Укажите стадион (или отправьте «нет»):")
    await cb.answer()


# ================== БОМБАРДИРЫ ==================
@dp.callback_query(F.data.startswith("scorers_yes:"))
async def scorers_yes(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    match_id = int(callback.data.split(":")[1])
    await state.set_state(RecordGoals.active)
    await state.update_data(match_id=match_id)
    await callback.message.edit_text(goals_progress_text(match_id),
                                     reply_markup=goals_kb(match_id))
    await callback.answer()


@dp.callback_query(F.data.startswith("scorers_no:"))
async def scorers_no(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Готово!", reply_markup=back_main_kb())
    await callback.answer()


@dp.callback_query(F.data.startswith("goal:"))
async def add_goal(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    _, match_id, player_id, team_id = callback.data.split(":")
    match_id, player_id, team_id = int(match_id), int(player_id), int(team_id)
    m = db.get_match(match_id)
    max_goals = m["home_score"] if team_id == m["home_team_id"] else m["away_score"]
    if db.count_goals_for_match_team(match_id, team_id) >= max_goals:
        return await callback.answer("У этой команды больше нет голов в матче", show_alert=True)
    db.add_goal(match_id, player_id, team_id)
    await callback.answer("Гол записан!")
    await callback.message.edit_text(goals_progress_text(match_id), reply_markup=goals_kb(match_id))


@dp.callback_query(F.data.startswith("goals_done:"))
async def goals_done(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    match_id = int(callback.data.split(":")[1])
    await callback.message.edit_text("✅ Запись голов завершена.\n" + format_match_scorers(match_id),
                                     reply_markup=back_main_kb())
    await callback.answer()


@dp.message(F.text == "🥇 Бомбардиры")
async def top_scorers(message: Message):
    t = db.get_active_tournament()
    scorers = db.get_top_scorers(t["id"], 15) if t else []
    if not scorers:
        return await message.answer("Голы пока не записаны.")
    medals = ["🥇", "🥈", "🥉"]
    lines = []
    for i, s in enumerate(scorers):
        prefix = medals[i] if i < 3 else f"{i + 1}."
        lines.append(f"{prefix} {s['player']} ({s['team']}) — {s['goals']}")
    type_label = {"league": "⚽", "cup": "🏆", "amateur": "🎯"}.get(t["type"], "⚽")
    title = f"{type_label} Бомбардиры «{t['name']}»" if t else "🥇 Бомбардиры"
    await message.answer(f"<b>{title}</b>\n" + "\n".join(lines))


# ================== ТУРНИРЫ ==================
@dp.message(F.text == "🏆 Турниры")
async def tournaments_menu(message: Message):
    ts = db.get_tournaments()
    active = db.get_active_tournament()
    lines = []
    for t in ts:
        mark = "✅ " if active and t["id"] == active["id"] else "   "
        type_icons = {"league": "⚽", "cup": "🏆", "amateur": "🎯"}
        type_icon = type_icons.get(t["type"], "⚽")
        status_icon = "🟢" if t["status"] == "active" else "⏸"
        subtype = f" ({t['subtype']})" if t["subtype"] else ""
        lines.append(f"{mark}{type_icon} {t['name']}{subtype} {status_icon}")
    text = "<b>🏆 Все турниры</b>\n\n" + ("\n".join(lines) if lines else "Нет турниров.")
    text += "\n\n✅ — активный турнир"
    text += "\n⚽ — чемпионат/лига"
    text += "\n🏆 — кубок"
    text += "\n🎯 — любительский (по % побед)"
    text += "\n🟢 — активен, ⏸ — завершён"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новый турнир", callback_data="t_create")],
        [InlineKeyboardButton(text="🔄 Переключить активный", callback_data="t_switch")],
        [InlineKeyboardButton(text="🗑 Удалить турнир", callback_data="t_delete")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await message.answer(text, reply_markup=kb)


@dp.callback_query(F.data == "t_create")
async def t_create(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    await state.set_state(CreateTournament.type_)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚽ Чемпионат / Лига", callback_data="t_type:league")],
        [InlineKeyboardButton(text="🏆 Кубок (группы + плей-офф)", callback_data="t_type:cup")],
        [InlineKeyboardButton(text="🎯 Любительский (по % побед)", callback_data="t_type:amateur")]])
    await callback.message.edit_text("<b>Шаг 1/4</b>\n\nВыберите тип турнира:", reply_markup=kb)
    await callback.answer()


@dp.callback_query(CreateTournament.type_, F.data.startswith("t_type:"))
async def t_create_type(callback: CallbackQuery, state: FSMContext):
    type_ = callback.data.split(":")[1]
    await state.update_data(type_=type_)
    
    if type_ == "league":
        await state.set_state(CreateTournament.subtype)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🇪🇸 Ла Лига (Испания)", callback_data="t_sub:laliga")],
            [InlineKeyboardButton(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 Премьер-лига (Англия)", callback_data="t_sub:premier")],
            [InlineKeyboardButton(text="🇩🇪 Бундеслига (Германия)", callback_data="t_sub:bundesliga")],
            [InlineKeyboardButton(text="🇮🇹 Серия А (Италия)", callback_data="t_sub:seriea")],
            [InlineKeyboardButton(text="🇫🇷 Лига 1 (Франция)", callback_data="t_sub:ligue1")],
            [InlineKeyboardButton(text="📝 Другое", callback_data="t_sub:custom")]])
        await callback.message.edit_text("<b>Шаг 2/4</b>\n\nВыберите формат лиги:", reply_markup=kb)
    else:
        # Для cup и amateur пропускаем subtype
        await state.update_data(subtype=None)
        await state.set_state(CreateTournament.name)
        await callback.message.edit_text("<b>Шаг 2/4</b>\n\nВведите название турнира:", reply_markup=InlineKeyboardMarkup())
    await callback.answer()


@dp.callback_query(CreateTournament.subtype, F.data.startswith("t_sub:"))
async def t_create_subtype(callback: CallbackQuery, state: FSMContext):
    subtype_code = callback.data.split(":")[1]
    subtype_names = {
        "laliga": "Ла Лига",
        "premier": "Премьер-лига",
        "bundesliga": "Бундеслига",
        "seriea": "Серия А",
        "ligue1": "Лига 1",
        "custom": None
    }
    
    if subtype_code == "custom":
        await state.update_data(subtype=None, ask_name=True)
        await callback.message.edit_text("<b>Шаг 3/4</b>\n\nВведите название лиги:", 
                                         reply_markup=InlineKeyboardMarkup())
        await state.set_state(CreateTournament.name)
    else:
        await state.update_data(subtype=subtype_names[subtype_code])
        await state.set_state(CreateTournament.name)
        await callback.message.edit_text("<b>Шаг 3/4</b>\n\nВведите название турнира:", 
                                         reply_markup=InlineKeyboardMarkup())
    await callback.answer()


@dp.message(CreateTournament.name)
async def t_create_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(CreateTournament.teams)
    
    # Показываем все доступные команды для добавления
    all_teams = db.get_teams()
    if not all_teams:
        await message.answer(
            "⚠️ Нет доступных команд.\nСначала создайте команды через «📋 Команды».",
            reply_markup=back_main_kb())
        await state.clear()
        return
    
    kb_rows = [[InlineKeyboardButton(text=t["name"], callback_data=f"tadd_new:{t['id']}")]
               for t in all_teams][:30]
    kb_rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="t_add_done_new")])
    
    await message.answer(
        f"<b>Шаг 4/4</b>\n\nДобавьте команды в турнир.\nНажимайте на команды, затем «✅ Готово»:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))


@dp.callback_query(CreateTournament.teams, F.data.startswith("tadd_new:"))
async def t_add_team_new(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    team_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    if "selected_teams" not in data:
        data["selected_teams"] = []
    if team_id not in data["selected_teams"]:
        data["selected_teams"].append(team_id)
    await state.update_data(selected_teams=data["selected_teams"])
    
    # Обновляем клавиатуру
    all_teams = db.get_teams()
    selected = data["selected_teams"]
    available = [t for t in all_teams if t["id"] not in selected]
    
    kb_rows = [[InlineKeyboardButton(text=f"✓ {t['name']}" if t["id"] in selected else t["name"], 
                                     callback_data=f"tadd_new:{t['id']}")]
               for t in all_teams][:30]
    kb_rows.append([InlineKeyboardButton(text=f"✅ Готово ({len(selected)} выбрано)", 
                                         callback_data="t_add_done_new")])
    
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer(f"Добавлено! Выбрано: {len(selected)}")


@dp.callback_query(CreateTournament.teams, F.data == "t_add_done_new")
async def t_add_done_new(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    data = await state.get_data()
    selected = data.get("selected_teams", [])
    
    if len(selected) < 2:
        await callback.answer("Нужно минимум 2 команды", show_alert=True)
        return
    
    # Создаём турнир
    tid = db.create_tournament(data["name"], data["type_"], data.get("subtype"))
    
    # Добавляем команды
    for team_id in selected:
        db.add_team_to_tournament(tid, team_id)
    
    await state.clear()
    
    # Показываем следующие шаги
    t = db.get_tournament(tid)
    type_labels = {"league": "Чемпионат", "cup": "Кубок", "amateur": "Любительский"}
    
    kb_rows = []
    if t["type"] == "league" or t["type"] == "amateur":
        kb_rows.append([InlineKeyboardButton(text="🎯 Сгенерировать расписание",
                                             callback_data=f"t_gen_schedule:{tid}")])
    elif t["type"] == "cup":
        kb_rows.append([InlineKeyboardButton(text="🎲 Создать группы",
                                             callback_data=f"t_cup_groups:{tid}")])
    
    kb_rows.append([InlineKeyboardButton(text="🔄 Сделать активным",
                                         callback_data=f"t_activate:{tid}")])
    kb_rows.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    
    subtype_info = f"\nФормат: {t['subtype']}" if t["subtype"] else ""
    await callback.message.edit_text(
        f"✅ {type_labels[t['type']]} «{data['name']}» создан!\n"
        f"Команд: {len(selected)}{subtype_info}\n\nЧто дальше?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    await callback.answer()


@dp.callback_query(F.data == "t_switch")
async def t_switch(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    ts = db.get_tournaments()
    if not ts: return await callback.answer("Нет турниров", show_alert=True)
    buttons = [[InlineKeyboardButton(text=t["name"], callback_data=f"tsw:{t['id']}")]
               for t in ts]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tournaments_back")])
    await callback.message.edit_text("Какой турнир сделать активным?",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("tsw:"))
async def t_switch_do(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    tid = int(callback.data.split(":")[1])
    # деактивируем все, потом активируем выбранный
    for t in db.get_tournaments():
        db.set_tournament_status(t["id"], "paused")
    db.set_tournament_status(tid, "active")
    await callback.answer("Переключено!")
    t = db.get_tournament(tid)
    await callback.message.edit_text(
        f"✅ Активный турнир: <b>{t['name']}</b>",
        reply_markup=back_main_kb())


@dp.callback_query(F.data == "t_delete")
async def t_delete(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    ts = db.get_tournaments()
    if not ts: return await callback.answer("Нет турниров", show_alert=True)
    buttons = [[InlineKeyboardButton(text=t["name"], callback_data=f"tdel:{t['id']}")]
               for t in ts]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="tournaments_back")])
    await callback.message.edit_text("Какой турнир удалить?",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("tdel:"))
async def t_delete_do(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    tid = int(callback.data.split(":")[1])
    t = db.get_tournament(tid)
    db.delete_tournament(tid)
    await callback.answer(f"Турнир «{t['name']}» удалён")
    # если был активным, активируем первый оставшийся
    ts = db.get_tournaments()
    if ts and not db.get_active_tournament():
        db.set_tournament_status(ts[0]["id"], "active")
    await tournaments_menu_refresh(callback)


async def tournaments_menu_refresh(callback: CallbackQuery):
    ts = db.get_tournaments()
    active = db.get_active_tournament()
    lines = []
    for t in ts:
        mark = "✅ " if active and t["id"] == active["id"] else "   "
        type_icon = "⚽" if t["type"] == "league" else "🏆"
        status_icon = "🟢" if t["status"] == "active" else "⏸"
        lines.append(f"{mark}{type_icon} {t['name']} {status_icon}")
    text = "<b>🏆 Все турниры</b>\n\n" + ("\n".join(lines) if lines else "Нет турниров.")
    text += "\n\n✅ — активный турнир\n⚽ — чемпионат, 🏆 — кубок\n🟢 — активен, ⏸ — завершён"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Новый турнир", callback_data="t_create")],
        [InlineKeyboardButton(text="🔄 Переключить активный", callback_data="t_switch")],
        [InlineKeyboardButton(text="🗑 Удалить турнир", callback_data="t_delete")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await callback.message.edit_text(text, reply_markup=kb)


@dp.callback_query(F.data.startswith("t_activate:"))
async def t_activate(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    tid = int(callback.data.split(":")[1])
    for t in db.get_tournaments():
        db.set_tournament_status(t["id"], "paused")
    db.set_tournament_status(tid, "active")
    await callback.answer("Турнир активен!")
    await callback.message.edit_text("✅ Готово!", reply_markup=back_main_kb())


@dp.callback_query(F.data.startswith("t_gen_schedule:"))
async def t_gen_schedule(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    tid = int(callback.data.split(":")[1])
    teams = db.get_tournament_teams(tid)
    if len(teams) < 2:
        return await callback.answer("Нужно минимум 2 команды", show_alert=True)
    ids = [t["id"] for t in teams]
    base = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
    ids_matches = db.generate_round_robin_fixtures(tid, ids, base.strftime("%Y-%m-%d %H:%M"))
    db.set_tournament_status(tid, "active")
    await callback.answer(f"Создано {len(ids_matches)} матчей!")
    await callback.message.edit_text(
        f"✅ Сгенерировано {len(ids_matches)} матчей.\nТурнир активен!",
        reply_markup=back_main_kb())


@dp.callback_query(F.data.startswith("t_cup_groups:"))
async def t_cup_groups_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    tid = int(callback.data.split(":")[1])
    await state.set_state(CupGroups.num)
    await state.update_data(tid=tid)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=str(n), callback_data=f"grp_n:{n}") for n in range(2, 9)]])
    await callback.message.edit_text(
        "Сколько групп создать?\n(обычно 4 или 8, как на ЧМ)",
        reply_markup=kb)
    await callback.answer()


@dp.callback_query(CupGroups.num, F.data.startswith("grp_n:"))
async def t_cup_groups_make(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    n = int(callback.data.split(":")[1])
    data = await state.get_data()
    tid = data["tid"]
    teams = db.get_tournament_teams(tid)
    if len(teams) < n:
        await state.clear()
        return await callback.message.edit_text(
            f"Недостаточно команд. Нужно хотя бы {n}, у вас {len(teams)}.",
            reply_markup=back_main_kb())
    group_ids = db.auto_distribute_groups(tid, n)
    base = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0)
    total_fixtures = 0
    for gid in group_ids:
        g_teams = db.get_group_teams(gid)
        ids = [t["id"] for t in g_teams]
        if len(ids) >= 2:
            fx = db.generate_round_robin_fixtures(tid, ids, base.strftime("%Y-%m-%d %H:%M"), group_id=gid)
            total_fixtures += len(fx)
    await state.clear()
    db.set_tournament_status(tid, "active")
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Посмотреть группы", callback_data="cup_groups_view")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await callback.message.edit_text(
        f"✅ Создано {len(group_ids)} групп\n🎯 Матчей группового этапа: {total_fixtures}\n"
        f"Турнир активен!", reply_markup=kb)
    await callback.answer()


# ================== ГРУППЫ КУБКА ==================
@dp.message(F.text == "📊 Группы")
async def cup_groups_view(message: Message):
    t = db.get_active_tournament()
    if not t or t["type"] != "cup":
        return await message.answer("Активный турнир — не кубок.")
    groups = db.get_groups(t["id"])
    if not groups:
        return await message.answer("Группы ещё не созданы.")
    lines = [f"<b>📊 Группы «{t['name']}»</b>\n"]
    for g in groups:
        teams = db.get_group_teams(g["id"])
        standings = db.get_standings(t["id"], group_id=g["id"])
        lines.append(f"\n<b>🏟 Группа {g['name']}</b>")
        if standings:
            lines.append(f"{'№':<3}{'Команда':<15}{'И':>3}{'В':>3}{'Н':>3}{'П':>3}{'О':>3}")
            for i, s in enumerate(standings, 1):
                lines.append(f"{i:<3}{s['name'][:14]:<15}{s['played']:>3}{s['wins']:>3}"
                             f"{s['draws']:>3}{s['losses']:>3}{s['points']:>3}")
        else:
            lines.append("Матчей ещё не было.")
        lines.append("Состав: " + (", ".join(tm["name"] for tm in teams) if teams else "пусто"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Перейти в плей-офф", callback_data="cup_playoff_start")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await message.answer("\n".join(lines), reply_markup=kb)


@dp.callback_query(F.data == "cup_groups_view")
async def cup_groups_view_cb(callback: CallbackQuery):
    t = db.get_active_tournament()
    if not t or t["type"] != "cup":
        return await callback.answer("Не кубок", show_alert=True)
    groups = db.get_groups(t["id"])
    lines = [f"<b>📊 Группы «{t['name']}»</b>\n"]
    for g in groups:
        teams = db.get_group_teams(g["id"])
        standings = db.get_standings(t["id"], group_id=g["id"])
        lines.append(f"\n<b>🏟 Группа {g['name']}</b>")
        if standings:
            lines.append(f"{'№':<3}{'Команда':<15}{'И':>3}{'В':>3}{'Н':>3}{'П':>3}{'О':>3}")
            for i, s in enumerate(standings, 1):
                lines.append(f"{i:<3}{s['name'][:14]:<15}{s['played']:>3}{s['wins']:>3}"
                             f"{s['draws']:>3}{s['losses']:>3}{s['points']:>3}")
        lines.append("Состав: " + (", ".join(tm["name"] for tm in teams) if teams else "пусто"))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎯 Перейти в плей-офф", callback_data="cup_playoff_start")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb)
    await callback.answer()


# ================== ПЛЕЙ-ОФФ ==================
@dp.message(F.text == "🎯 Плей-офф")
async def cup_playoff_msg(message: Message):
    await message.answer(
        "Нажмите кнопку ниже, чтобы начать плей-офф:\n"
        "(бот возьмёт по 2 лучшие команды из каждой группы и создаст пары)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Сгенерировать плей-офф",
                                  callback_data="cup_playoff_start")],
            [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]]))


@dp.callback_query(F.data == "cup_playoff_start")
async def cup_playoff_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id): return await deny_callback(callback)
    t = db.get_active_tournament()
    if not t or t["type"] != "cup":
        return await callback.answer("Активный турнир — не кубок", show_alert=True)
    groups = db.get_groups(t["id"])
    if not groups:
        return await callback.answer("Сначала создайте группы", show_alert=True)
    qualified = []
    for g in groups:
        standings = db.get_standings(t["id"], group_id=g["id"])
        qualified.extend(standings[:2])
    if len(qualified) < 2:
        return await callback.answer("Недостаточно команд для плей-оффа", show_alert=True)
    random.shuffle(qualified)
    base = datetime.now().replace(hour=20, minute=0, second=0, microsecond=0)
    n = len(qualified) // 2
    stage_name = f"1/{n} финала" if n > 1 else "Финал"
    created = 0
    for i in range(n):
        h = db.get_team(qualified[2 * i]["name"])
        a = db.get_team(qualified[2 * i + 1]["name"])
        if h and a:
            db.add_fixture(t["id"], h["id"], a["id"],
                           base.strftime("%Y-%m-%d %H:%M"), stage=stage_name)
            created += 1
    await callback.answer(f"Создано матчей {stage_name}: {created}")
    await callback.message.edit_text(
        f"🎯 <b>Плей-офф «{t['name']}»</b>\n\n"
        f"Стадия: {stage_name}\nМатчей: {created}\n\n"
        f"Команды распределены случайно.\nИграйте и вводите результаты в разделе «⚽ Результаты»!",
        reply_markup=back_main_kb())


# ================== ТАБЛИЦА / ЭКСПОРТ ==================
@dp.message(F.text == "🏆 Таблица")
async def standings(message: Message):
    await message.answer(format_standings())


@dp.message(F.text == "📤 Экспорт")
async def export_menu(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 Таблица текстом (.txt)", callback_data="export_text")],
        [InlineKeyboardButton(text="🖼 Таблица картинкой (.png)", callback_data="export_image")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])
    await message.answer("Выберите формат экспорта:", reply_markup=kb)


@dp.callback_query(F.data == "export_text")
async def export_text(callback: CallbackQuery):
    t = db.get_active_tournament()
    text = build_standings_text(db.get_standings(t["id"]) if t else [])
    await callback.answer("Готово")
    await callback.message.answer_document(
        BufferedInputFile(text.encode("utf-8"), filename="tournament_table.txt"),
        caption="🏆 Турнирная таблица")


@dp.callback_query(F.data == "export_image")
async def export_image(callback: CallbackQuery):
    t = db.get_active_tournament()
    standings_data = db.get_standings(t["id"]) if t else []
    if not standings_data: return await callback.answer("Нет данных", show_alert=True)
    await callback.answer("Готовлю картинку...")
    title = f"Турнирная таблица — {t['name']}" if t else "Турнирная таблица"
    img = render_standings_image(standings_data, title=title)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    await callback.message.answer_photo(BufferedInputFile(buf.read(), filename="table.png"),
                                        caption="🏆 Турнирная таблица")


# ================== АДМИНЫ ==================
def _admins_text():
    admins = db.get_admins()
    owner = OWNER_ID if OWNER_ID != 0 else db.get_owner()
    text = f"<b>🔐 Администраторы</b>\n👑 Владелец: <code>{owner}</code>\n"
    text += ("\n".join(f"• <code>{a['user_id']}</code>" for a in admins)
             if admins else "\nДополнительных админов нет.")
    return text


def _admins_owner_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить админа", callback_data="admin_add")],
        [InlineKeyboardButton(text="🗑 Удалить админа", callback_data="admin_del_menu")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]])


@dp.message(F.text == "🔐 Админы")
async def admins_menu(message: Message):
    uid = message.from_user.id
    if not is_admin(uid): return await deny_message(message)
    await message.answer(_admins_text(),
                         reply_markup=_admins_owner_kb() if is_owner(uid) else back_main_kb())


@dp.callback_query(F.data == "admin_add")
async def admin_add(callback: CallbackQuery, state: FSMContext):
    if not is_owner(callback.from_user.id): return await deny_callback(callback)
    await state.set_state(AddAdmin.uid)
    await callback.message.edit_text(
        "Отправьте Telegram ID нового админа (число).\nУзнать: команда /id")
    await callback.answer()


@dp.message(AddAdmin.uid)
async def admin_add_uid(message: Message, state: FSMContext):
    if not is_owner(message.from_user.id): return await deny_message(message)
    if not message.text.strip().isdigit():
        return await message.answer("Нужно число (Telegram ID).")
    uid = int(message.text.strip())
    if uid == OWNER_ID or db.is_admin(uid) or db.get_owner() == uid:
        await state.clear()
        return await message.answer("Он уже админ.")
    db.add_admin(uid)
    await state.clear()
    await message.answer(f"✅ Пользователь <code>{uid}</code> теперь админ.",
                         reply_markup=get_current_menu(message.from_user.id))


@dp.callback_query(F.data == "admin_del_menu")
async def admin_del_menu(callback: CallbackQuery):
    if not is_owner(callback.from_user.id): return await deny_callback(callback)
    admins = db.get_admins()
    if not admins: return await callback.answer("Админов нет", show_alert=True)
    buttons = [[InlineKeyboardButton(text=str(a["user_id"]), callback_data=f"adel:{a['user_id']}")]
               for a in admins]
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admins_back")])
    await callback.message.edit_text("Кого удалить?",
                                     reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@dp.callback_query(F.data.startswith("adel:"))
async def admin_del(callback: CallbackQuery):
    if not is_owner(callback.from_user.id): return await deny_callback(callback)
    db.remove_admin(int(callback.data.split(":")[1]))
    await callback.answer("Админ удалён")
    await callback.message.edit_text(_admins_text(), reply_markup=_admins_owner_kb())


# ================== НАВИГАЦИЯ ==================
@dp.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.answer("🏠 Главное меню:",
                                  reply_markup=get_current_menu(callback.from_user.id))
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@dp.callback_query(F.data.in_({"players_back", "matches_back", "schedule_back",
                                "admins_back", "tournaments_back"}))
async def cb_back(callback: CallbackQuery):
    if callback.data == "players_back":
        await callback.message.edit_text("Выберите команду:",
                                         reply_markup=teams_kb(db.get_teams(), "players_team"))
    elif callback.data == "matches_back":
        await callback.message.edit_text(results_text(), reply_markup=results_menu_kb())
    elif callback.data == "schedule_back":
        await callback.message.edit_text(schedule_text(), reply_markup=schedule_menu_kb())
    elif callback.data == "admins_back":
        await callback.message.edit_text(_admins_text(), reply_markup=_admins_owner_kb())
    elif callback.data == "tournaments_back":
        await tournaments_menu_refresh(callback)
        return
    await callback.answer()


# ================== FALLBACK ==================
@dp.message()
async def fallback(message: Message):
    await message.answer("Не понимаю 🤔 Воспользуйтесь меню или /help.",
                         reply_markup=get_current_menu(message.from_user.id))


# ================== ЗАПУСК ==================
async def main():
    db.init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())