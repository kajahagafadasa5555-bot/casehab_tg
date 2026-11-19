import asyncio
import logging
import sys
import random
import string
import aiosqlite
import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "ВАШ_ТОКЕН_ЗДЕСЬ" # ЗАМЕНИТЕ НА ВАШ ТОКЕН!
ADMIN_ID = 8400799305
CHANNEL_ID = "@casehab"
CHANNEL_LINK = "https://t.me/casehab"
CONTACT_ADMIN = "@drag_monster_zl"

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# ================= БАЗА ДАННЫХ =================
DB_PATH = "bot.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT, balance INTEGER DEFAULT 0, coins INTEGER DEFAULT 0, referrer_id INTEGER, ref_count INTEGER DEFAULT 0, last_seen TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS coupons (code TEXT PRIMARY KEY, user_id INTEGER, item_name TEXT, status INTEGER DEFAULT 0, created_at TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, item_name TEXT, price INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        await db.execute("CREATE TABLE IF NOT EXISTS admins (user_id INTEGER PRIMARY KEY, rank INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, admin_id INTEGER, action TEXT, timestamp TIMESTAMP)")
        await db.execute("CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, reward_type TEXT, amount INTEGER, uses_left INTEGER)")
        await db.execute("CREATE TABLE IF NOT EXISTS banned (user_id INTEGER PRIMARY KEY)")
        
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance', 'False')")
        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('panic_mode', 'False')")
        await db.execute("INSERT OR IGNORE INTO admins (user_id, rank) VALUES (?, 3)", (ADMIN_ID,))
        await db.commit()

async def get_user(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (uid,)) as cur:
            return await cur.fetchone()

async def update_bal(uid, bal_add=0, coin_add=0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ?, coins = coins + ? WHERE user_id = ?", (bal_add, coin_add, uid))
        await db.commit()

async def is_banned(uid):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM banned WHERE user_id = ?", (uid,)) as cur:
            return bool(await cur.fetchone())

async def get_admin_rank(uid):
    if uid == ADMIN_ID: return 3
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT rank FROM admins WHERE user_id = ?", (uid,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

async def log_action(admin_id, action):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO logs (admin_id, action, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)", (admin_id, action))
        await db.commit()

# ================= ИГРОВЫЕ ДАННЫЕ =================
CASES = {
    "case_1": {
        "name": "📦 Бюджетный (10 монет / 1 коэн)",
        "price_bal": 10, "price_coin": 1,
        "items": [
            {"name": "5 монет", "price": 5, "weight": 60, "type": "bal"},
            {"name": "15 монет", "price": 15, "weight": 30, "type": "bal"},
            {"name": "🐻 Мишка (Подарок)", "price": 100, "weight": 9, "type": "item"},
            {"name": "⭐ 25 Звезд", "price": 100, "weight": 1, "type": "item"}
        ]
    },
    "nft_case": {
        "name": "💎 NFT-Кейс (700 Звезд)",
        "price_bal": 0, "price_coin": 0, "price_stars": 700,
        "items": [
            {"name": "⭐ 25 Звезд", "price": 25, "weight": 70, "type": "item"},
            {"name": "⭐ 50 Звезд", "price": 50, "weight": 20, "type": "item"},
            {"name": "🎁 Дорогой Подарок", "price": 500, "weight": 9, "type": "item"},
            {"name": "👑 NFT Подарок", "price": 5000, "weight": 1, "type": "item"} 
        ]
    }
}

# ================= КЛАВИАТУРЫ =================
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Кейсы", callback_data="cases_menu"), InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu")],
        [InlineKeyboardButton(text="🎒 Инвентарь", callback_data="inventory"), InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton(text="👥 Рефералы", callback_data="ref_menu"), InlineKeyboardButton(text="🎟 Промокод", callback_data="enter_promo")]
    ])

def admin_menu(rank):
    if rank == 3:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Выдать валюту", callback_data="admin_give"), InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_promo")],
            [InlineKeyboardButton(text="🔍 Проверить купон", callback_data="admin_check")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"), InlineKeyboardButton(text="🛠 Тех. работы", callback_data="admin_maint")],
            [InlineKeyboardButton(text="👥 Персонал", callback_data="admin_staff"), InlineKeyboardButton(text="🚨 Паника", callback_data="admin_panic")],
            [InlineKeyboardButton(text="⚙️ Конструктор", callback_data="admin_constructor")]
        ])
    elif rank == 2:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Запросить выдачу", callback_data="admin_req_give"), InlineKeyboardButton(text="🎟 Запросить промо", callback_data="admin_req_promo")],
            [InlineKeyboardButton(text="🔍 Проверить купон", callback_data="admin_check")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"), InlineKeyboardButton(text="📜 Мои права", callback_data="admin_rights")]
        ])
    elif rank == 1:
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💰 Запросить выдачу", callback_data="admin_req_give")],
            [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"), InlineKeyboardButton(text="📜 Мои права", callback_data="admin_rights")]
        ])

def back_btn(cb="back_main"):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ Назад", callback_data=cb)]])

# ================= FSM =================
class AdminStates(StatesGroup):
    give_id = State(); give_amount = State(); give_type = State()
    check_coupon = State()
    promo_name = State(); promo_amount = State(); promo_uses = State(); promo_type = State()
    staff_id = State(); staff_rank = State(); staff_action = State()

class UserStates(StatesGroup):
    promo_input = State()
    bet_amount = State()

# ================= ПОЛЬЗОВАТЕЛЬСКИЕ ХЕНДЛЕРЫ =================

@dp.message(CommandStart())
async def cmd_start(message: Message):
    uid = message.from_user.id
    if await is_banned(uid): return await message.answer("⛔ Вы забанены.")
    
    # Проверка тех. работ
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'maintenance'") as cur:
            maint = (await cur.fetchone())[0]
    if maint == "True" and await get_admin_rank(uid) < 3:
        return await message.answer("🛠 <b>На боте проводятся технические работы. Зайдите позже.</b>")

    args = message.text.split()
    ref_id = int(args[1]) if len(args) > 1 and args[1].isdigit() else None
    if ref_id == uid: ref_id = None

    user = await get_user(uid)
    if not user:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO users (user_id, username, referrer_id) VALUES (?, ?, ?)", (uid, message.from_user.username, ref_id))
            await db.commit()
        if ref_id:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("UPDATE users SET ref_count = ref_count + 1 WHERE user_id = ?", (ref_id,))
                await db.commit()
            try: await bot.send_message(ref_id, "🎉 По вашей ссылке зашел новый пользователь!")
            except: pass

    await message.answer(f"👋 Привет, <b>{message.from_user.full_name}</b>!\nДобро пожаловать в CaseHab.", reply_markup=main_menu())

@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    rank = await get_admin_rank(message.from_user.id)
    if rank == 0: return await message.answer("⛔ У вас нет доступа.")
    await message.answer(f"👑 <b>Админ-панель (Ранг: {rank})</b>", reply_markup=admin_menu(rank))

@dp.callback_query(F.data == "back_main")
async def back_main_cb(call: CallbackQuery):
    await call.message.edit_text("Главное меню:", reply_markup=main_menu())

@dp.callback_query(F.data == "profile")
async def profile_cb(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    await call.message.edit_text(
        f"👤 <b>Профиль</b>\n\n🆔 ID: <code>{call.from_user.id}</code>\n"
        f"💰 Монеты: {user[2]}\n💎 Коэны: {user[3]}\n👥 Рефералов: {user[5]}/3",
        reply_markup=back_btn()
    )

@dp.callback_query(F.data == "inventory")
async def inv_cb(call: CallbackQuery):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT item_name, price FROM inventory WHERE user_id = ?", (call.from_user.id,)) as cur:
            items = await cur.fetchall()
    text = "🎒 <b>Инвентарь пуст.</b>" if not items else "🎒 <b>Ваши предметы:</b>\n\n" + "\n".join([f"▪️ {i[0]} ({i[1]})" for i in items])
    await call.message.edit_text(text, reply_markup=back_btn())

@dp.callback_query(F.data == "ref_menu")
async def ref_cb(call: CallbackQuery):
    bot_info = await bot.get_me()
    link = f"https://t.me/{bot_info.username}?start={call.from_user.id}"
    await call.message.edit_text(f"👥 <b>Рефералы</b>\n\nПригласите 3 друзей для вывода:\n<code>{link}</code>", reply_markup=back_btn())

# --- КЕЙСЫ ---
@dp.callback_query(F.data == "cases_menu")
async def cases_cb(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Бюджетный", callback_data="open_case_1")],
        [InlineKeyboardButton(text="💎 NFT-Кейс (Stars)", callback_data="open_nft_case")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("🎁 <b>Выберите кейс:</b>", reply_markup=kb)

@dp.callback_query(F.data.startswith("open_case_"))
async def open_case(call: CallbackQuery):
    case_id = call.data.replace("open_", "")
    case = CASES.get(case_id)
    if not case: return
    
    # Логика оплаты
    user = await get_user(call.from_user.id)
    if "price_stars" in case:
        await call.answer("Для оплаты Stars используется отдельная кнопка (в разработке)", show_alert=True)
        return
    if user[2] < case["price_bal"]:
        return await call.answer("❌ Недостаточно монет!", show_alert=True)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (case["price_bal"], call.from_user.id))
        await db.commit()

    await call.message.edit_text("🎰 Крутим рулетку...")
    await asyncio.sleep(1)
    
    # Проверка кнопки паники
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'panic_mode'") as cur:
            panic = (await cur.fetchone())[0]
            
    items = case["items"]
    if panic == "True":
        items = [i for i in items if i["price"] <= 50] # Только дешевые

    total_w = sum(i["weight"] for i in items)
    r = random.uniform(0, total_w)
    curr = 0
    win = items[0]
    for i in items:
        curr += i["weight"]
        if r <= curr:
            win = i; break
            
    await call.message.edit_text(f"🎉 <b>Вы выиграли:</b>\n\n{win['name']}\n💰 Ценность: {win['price']}", reply_markup=back_btn("cases_menu"))

# --- ИГРЫ ---
@dp.callback_query(F.data == "games_menu")
async def games_cb(call: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎮 Апгрейд (x2)", callback_data="game_upgrade")],
        [InlineKeyboardButton(text="🪙 Монетка (50/50)", callback_data="game_coin")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="back_main")]
    ])
    await call.message.edit_text("🎮 <b>Игры</b>\nВыберите игру:", reply_markup=kb)

@dp.callback_query(F.data == "game_upgrade")
async def game_upgrade(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("🎮 <b>Апгрейд</b>\n\nВведите сумму ставки (Монеты):", reply_markup=back_btn("games_menu"))
    await state.set_state(UserStates.bet_amount)
    await state.update_data(game="upgrade")

@dp.message(UserStates.bet_amount)
async def process_bet(message: Message, state: FSMContext):
    if not message.text.isdigit(): return await message.answer("Введите число!")
    bet = int(message.text)
    user = await get_user(message.from_user.id)
    if user[2] < bet: return await message.answer("❌ Недостаточно монет!")
    
    data = await state.get_data()
    if data.get("game") == "upgrade":
        if random.random() < 0.5: # 50% шанс
            await update_bal(message.from_user.id, bal_add=bet)
            await message.answer(f"🎉 <b>Победа!</b> Вы выиграли {bet} монет.", reply_markup=main_menu())
        else:
            await update_bal(message.from_user.id, bal_add=-bet)
            await message.answer(f"😢 <b>Проигрыш.</b> Вы потеряли {bet} монет.", reply_markup=main_menu())
    await state.clear()

# --- ПРОМОКОДЫ ---
@dp.callback_query(F.data == "enter_promo")
async def enter_promo(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("🎟 Введите промокод:", reply_markup=back_btn())
    await state.set_state(UserStates.promo_input)

@dp.message(UserStates.promo_input)
async def check_promo(message: Message, state: FSMContext):
    code = message.text.strip()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM promos WHERE code = ? AND uses_left > 0", (code,)) as cur:
            promo = await cur.fetchone()
            
    if promo:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE promos SET uses_left = uses_left - 1 WHERE code = ?", (code,))
            await db.commit()
        await message.answer(f"✅ Промокод активирован! Вы получили: {promo[2]} {promo[1]}")
    else:
        await message.answer("❌ Неверный или использованный промокод.")
    await state.clear()

# ================= АДМИН ХЕНДЛЕРЫ =================

@dp.callback_query(F.data == "admin_stats")
async def a_stats(call: CallbackQuery):
    if await get_admin_rank(call.from_user.id) == 0: return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as c: total = (await c.fetchone())[0]
        time_th = (datetime.datetime.now() - datetime.timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S')
        async with db.execute("SELECT COUNT(*) FROM users WHERE last_seen >= ?", (time_th,)) as c: online = (await c.fetchone())[0]
    await call.message.answer(f"📊 Всего: {total}\n🟢 Онлайн: {online}", reply_markup=admin_menu(await get_admin_rank(call.from_user.id)))

@dp.callback_query(F.data == "admin_maint")
async def a_maint(call: CallbackQuery):
    if await get_admin_rank(call.from_user.id) != 3: return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'maintenance'") as c: val = (await c.fetchone())[0]
        new = "False" if val == "True" else "True"
        await db.execute("UPDATE settings SET value = ? WHERE key = 'maintenance'", (new,))
        await db.commit()
    await call.answer(f"Тех.работы: {'ВКЛ' if new=='True' else 'ВЫКЛ'}", show_alert=True)

@dp.callback_query(F.data == "admin_panic")
async def a_panic(call: CallbackQuery):
    if await get_admin_rank(call.from_user.id) != 3: return
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key = 'panic_mode'") as c: val = (await c.fetchone())[0]
        new = "False" if val == "True" else "True"
        await db.execute("UPDATE settings SET value = ? WHERE key = 'panic_mode'", (new,))
        await db.commit()
    await call.answer(f"🚨 Паника: {'ВКЛ' if new=='True' else 'ВЫКЛ'}", show_alert=True)

@dp.callback_query(F.data == "admin_give")
async def a_give(call: CallbackQuery, state: FSMContext):
    if await get_admin_rank(call.from_user.id) != 3: return
    await call.message.answer("Введите ID игрока:")
    await state.set_state(AdminStates.give_id)

@dp.message(AdminStates.give_id)
async def a_give_id(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    await state.update_data(tid=int(message.text))
    await message.answer("Введите сумму Монет:")
    await state.set_state(AdminStates.give_amount)

@dp.message(AdminStates.give_amount)
async def a_give_amt(message: Message, state: FSMContext):
    if not message.text.isdigit(): return
    data = await state.get_data()
    await update_bal(data['tid'], bal_add=int(message.text))
    await message.answer(f"✅ Выдано {message.text} монет пользователю {data['tid']}.", reply_markup=admin_menu(3))
    await state.clear()

@dp.callback_query(F.data == "admin_rights")
async def a_rights(call: CallbackQuery):
    r = await get_admin_rank(call.from_user.id)
    txt = "📜 <b>Ваши права:</b>\n\nВы Заместитель. Можете запрашивать выдачу и проверять купоны." if r == 2 else "📜 <b>Ваши права:</b>\n\nВы Мл. Админ. Можете запрашивать выдачу и смотреть статистику."
    await call.message.answer(txt, reply_markup=back_btn("back_main"))
# ================= ЗАПУСК =================
async def main():
    await init_db()
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Бот остановлен")
