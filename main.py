import telebot
from telebot import types
import sqlite3
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from telebot.types import BotCommand

# --- 1. Load Secrets ---
load_dotenv()
TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')

bot = telebot.TeleBot(TOKEN)

# --- 2. Car Configuration ---
CAR_LIMITS = {
    "VW Blue": 35,
    "VW GRAY": 35,
    "570": 35,
    "Adventures": 40
}

CAR_PARITY = {
    "VW Blue": "odd",
    "VW GRAY": "odd",
    "570": "even",
    "Adventures": "odd"
}

user_data = {}

# --- 3. Database Setup ---
conn = sqlite3.connect('fuel_tracker.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''CREATE TABLE IF NOT EXISTS records
                  (id INTEGER PRIMARY KEY AUTOINCREMENT,
                   car TEXT,
                   driver TEXT,
                   liters REAL,
                   fill_date TEXT)''')
conn.commit()

# --- 4. The Core Math (7-Day Cycle / Day 8 Reset) ---
def get_car_state(car):
    cursor.execute("SELECT liters, fill_date FROM records WHERE car=? ORDER BY fill_date ASC", (car,))
    all_fills = cursor.fetchall()
    
    # If no history, it's completely ready for a Day 1
    if not all_fills:
        return {"state": "READY", "fills": 0, "liters": 0.0, "reset_time": None, "last_reset": None}
    
    cycle_start = None
    cycle_fills = 0
    cycle_liters = 0.0
    
    for fill in all_fills:
        fill_liters = fill[0]
        fill_date = datetime.fromisoformat(fill[1])
        
        # Does this fill start a brand new cycle? (7 full days after the cycle_start)
        if cycle_start is None or fill_date >= (cycle_start + timedelta(days=7)):
            cycle_start = fill_date
            cycle_fills = 1
            cycle_liters = fill_liters
        else:
            # It happened during the active 7-day cycle
            cycle_fills += 1
            cycle_liters += fill_liters
            
    now = datetime.now()
    reset_time = cycle_start + timedelta(days=7) # The exact moment the 7-day window closes
    
    if now >= reset_time:
        return {"state": "READY", "fills": 0, "liters": 0.0, "reset_time": None, "last_reset": reset_time}
    else:
        return {"state": "ACTIVE", "fills": cycle_fills, "liters": cycle_liters, "reset_time": reset_time, "last_reset": None}

# --- 5. The Smart Dispatcher (APScheduler) ---
def weekly_backup():
    if not ADMIN_CHAT_ID:
        return
    try:
        with open('fuel_tracker.db', 'rb') as db_file:
            caption = f"🛡️ Weekly Database Backup: {datetime.now().strftime('%Y-%m-%d')}"
            bot.send_document(ADMIN_CHAT_ID, db_file, caption=caption)
    except Exception as e:
        bot.send_message(ADMIN_CHAT_ID, f"⚠️ Backup failed: {e}")

def daily_smart_check():
    if not GROUP_CHAT_ID:
        return
    
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    yesterday = now - timedelta(days=1)
    
    for car, max_liters in CAR_LIMITS.items():
        state = get_car_state(car)
        
        # 1. The 24-Hour Warning (Window is closing soon!)
        if state["state"] == "ACTIVE":
            if now < state["reset_time"] <= tomorrow:
                fills_left = 2 - state["fills"]
                liters_left = max_liters - state["liters"]
                if fills_left > 0 and liters_left > 0:
                    msg = f"⚠️ *Fuel Reminder:* {car}'s 7-Day Cycle resets tomorrow!\n\nYou still have {fills_left} fill(s) and {liters_left}L left to claim."
                    bot.send_message(GROUP_CHAT_ID, msg, parse_mode='Markdown')
        
        # 2. The Reset Announcement (It just cleared the cycle!)
        elif state["state"] == "READY" and state["last_reset"]:
            if yesterday < state["last_reset"] <= now:
                msg = f"🔔 *Quota Reset!* The 7-day cycle for *{car}* has officially ended. It is ready for a fresh Day 1 ({max_liters}L limit)."
                bot.send_message(GROUP_CHAT_ID, msg, parse_mode='Markdown')

# Start the background scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(daily_smart_check, 'cron', hour=8, minute=0) # Runs every morning at 8:00 AM
scheduler.add_job(weekly_backup, 'cron', day_of_week='sun', hour=23, minute=50) # Sunday nights
scheduler.start()


# --- 6. Bot Commands ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    help_text = (
        "🚗 *Family Fuel Tracker Bot*\n"
        "Tracking a 7-Day Limit Cycle.\n\n"
        "⛽ *Commands:*\n"
        "`/check` - 🚦 PRE-CHECK if a car can get petrol today.\n"
        "`/fill` - Log petrol (Interactive menu).\n"
        "`/status` - Check all cars' cycle status.\n"
        "`/history` - See recent logs for a car.\n"
        "`/undo` - Deletes your most recent entry.\n"
        "\n"
        "*Registered Cars:*\n"
        "- VW Blue (Odd): 35L\n"
        "- VW GRAY (Odd): 35L\n"
        "- 570 (Even): 35L\n"
        "- Adventures (Odd): 40L"
    )
    bot.reply_to(message, help_text, parse_mode='Markdown')

# --- CHECK COMMAND ---
@bot.message_handler(commands=['check'])
def check_start(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    markup.add(*CAR_LIMITS.keys())
    msg = bot.reply_to(message, "🚦 Which car do you want to pre-check?", reply_markup=markup)
    bot.register_next_step_handler(msg, process_check_step)

def process_check_step(message):
    car = message.text
    markup = types.ReplyKeyboardRemove()
    if car not in CAR_LIMITS:
        bot.reply_to(message, "❌ Unrecognized car.", reply_markup=markup)
        return

    # 1. Plate Rule
    today_day = datetime.now().day
    is_today_odd = (today_day % 2 != 0)
    car_parity = CAR_PARITY[car]
    
    can_fill_date = True
    if car_parity == "odd" and not is_today_odd:
        date_status = f"❌ *Failed:* {car} needs an ODD date, but today is {today_day} (Even)."
        can_fill_date = False
    elif car_parity == "even" and is_today_odd:
        date_status = f"❌ *Failed:* {car} needs an EVEN date, but today is {today_day} (Odd)."
        can_fill_date = False
    else:
        date_status = f"✅ *Passed:* Today is a valid {car_parity} date."

    # 2. Cycle Rule
    state = get_car_state(car)
    max_liters = CAR_LIMITS[car]
    can_fill_quota = False
    
    if state["state"] == "READY":
        quota_status = f"✅ *Passed:* Cycle is clean! Ready for a new Day 1."
        can_fill_quota = True
        liters_left = max_liters
    else: # ACTIVE
        fills_left = 2 - state["fills"]
        liters_left = max_liters - state["liters"]
        if fills_left > 0 and liters_left > 0:
            end_str = state["reset_time"].strftime('%b %d at %I:%M %p')
            quota_status = f"✅ *Passed:* In Active Cycle (resets {end_str}). You have {fills_left} fills and {liters_left}L left."
            can_fill_quota = True
        else:
            end_str = state["reset_time"].strftime('%b %d at %I:%M %p')
            quota_status = f"❌ *Failed:* You used your allowance for this cycle. Resets on {end_str}."

    # Final Verdict
    if can_fill_date and can_fill_quota:
        verdict = f"🟢 *YES, YOU ARE GOOD TO GO!* 🟢\nYou can pump up to *{liters_left}L* today."
    else:
        verdict = f"🔴 *DO NOT GO TO THE STATION!* 🔴\nYou cannot fill {car} today."

    response = f"🚘 *Pre-Check for {car}*\n\n*1. Plate Rule:*\n{date_status}\n\n*2. Cycle Rule:*\n{quota_status}\n\n➖➖➖➖➖➖➖➖\n{verdict}"
    bot.reply_to(message, response, parse_mode='Markdown', reply_markup=markup)

# --- FILL COMMAND ---
@bot.message_handler(commands=['fill'])
def fill_start(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    markup.add(*CAR_LIMITS.keys())
    msg = bot.reply_to(message, "🚗 Which car are you filling up?", reply_markup=markup)
    bot.register_next_step_handler(msg, process_car_step)

def process_car_step(message):
    car = message.text
    if car not in CAR_LIMITS:
        bot.reply_to(message, "❌ Unrecognized car.", reply_markup=types.ReplyKeyboardRemove())
        return

    # Plate Check
    today_day = datetime.now().day
    is_today_odd = (today_day % 2 != 0)
    if CAR_PARITY[car] == "odd" and not is_today_odd:
        bot.reply_to(message, f"🛑 *STOP!* {car} has an ODD plate, but today is the {today_day} (Even).", parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
        return
    if CAR_PARITY[car] == "even" and is_today_odd:
        bot.reply_to(message, f"🛑 *STOP!* {car} has an EVEN plate, but today is the {today_day} (Odd).", parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
        return

    # Cycle Check
    state = get_car_state(car)
    max_liters = CAR_LIMITS[car]
    
    if state["state"] == "ACTIVE" and (state["fills"] >= 2 or state["liters"] >= max_liters):
        bot.reply_to(message, f"🚨 *DENIED:* {car} has maxed out its allowance for this cycle. Resets on {state['reset_time'].strftime('%b %d')}.", parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
        return

    chat_id = message.chat.id
    user_data[chat_id] = {'car': car}
    
    # Calculate remaining liters to show the right buttons
    remaining_liters = max_liters if state["state"] == "READY" else max_liters - state["liters"]
    
    # Generate Smart Buttons
    markup = types.ReplyKeyboardMarkup(row_width=3, resize_keyboard=True, one_time_keyboard=True)
    buttons = []
    
    for amount in [5, 10, 15, 20, 25, 30, 35, 40]:
        if amount < remaining_liters:
            buttons.append(f"{amount}L")
            
    markup.add(*buttons)
    markup.add(f"Full Allowance ({remaining_liters}L)")
    markup.add("⌨️ Type Custom Amount") 

    msg = bot.reply_to(message, f"⛽ You selected *{car}*.\n\nYou have up to *{remaining_liters}L* available.\nChoose the amount you pumped:", parse_mode='Markdown', reply_markup=markup)
    bot.register_next_step_handler(msg, process_liters_step)

def process_liters_step(message):
    chat_id = message.chat.id
    if chat_id not in user_data: return
    car = user_data[chat_id]['car']
    
    text_input = message.text
    
    # Handle the "Type Custom Amount" fallback
    if text_input == "⌨️ Type Custom Amount":
        msg = bot.reply_to(message, "Please type the exact number of liters (e.g., `18.5`):", parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_liters_step)
        return

    # Extract the number from the button they clicked
    try:
        if "Full Allowance" in text_input:
            liters = float(text_input.split('(')[1].split('L')[0])
        elif "L" in text_input:
            liters = float(text_input.replace('L', ''))
        else:
            liters = float(text_input)
    except Exception:
        bot.reply_to(message, "⚠️ Not a valid selection. Start over with /fill.", reply_markup=types.ReplyKeyboardRemove())
        del user_data[chat_id]
        return

    state = get_car_state(car)
    max_liters = CAR_LIMITS[car]
    remaining_liters = max_liters if state["state"] == "READY" else max_liters - state["liters"]
    
    if state["state"] == "ACTIVE" and liters > remaining_liters:
        bot.reply_to(message, f"🚨 *DENIED:* Adding {liters}L exceeds the limit. You can only add *{remaining_liters}L*.", parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
        del user_data[chat_id]
        return

    user_data[chat_id]['liters'] = liters
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    markup.add('Yes ✅', 'No ❌')
    msg = bot.reply_to(message, f"Double checking:\nLogging *{liters}L* for *{car}*.\n\nCorrect?", parse_mode='Markdown', reply_markup=markup)
    bot.register_next_step_handler(msg, process_confirmation_step)

def process_confirmation_step(message):
    chat_id = message.chat.id
    if chat_id not in user_data: return
        
    if message.text == 'Yes ✅':
        car = user_data[chat_id]['car']
        liters = user_data[chat_id]['liters']
        driver = message.from_user.first_name.replace('*', '').replace('_', '').replace('`', '')
        now_str = datetime.now().isoformat()
        
        cursor.execute("INSERT INTO records (car, driver, liters, fill_date) VALUES (?, ?, ?, ?)", (car, driver, liters, now_str))
        conn.commit()
        
        state = get_car_state(car) # get updated state
        msg = f"Data added ✅ All good, {driver}!\n\n📊 *{car} Cycle Status:*\nState: {state['state']}\nFills: {state['fills']}/2\nLiters: {state['liters']}/{CAR_LIMITS[car]}L"
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=types.ReplyKeyboardRemove())
    else:
        bot.reply_to(message, "Canceled! 🛑", reply_markup=types.ReplyKeyboardRemove())
        
    del user_data[chat_id]

# --- STATUS COMMAND ---
@bot.message_handler(commands=['status'])
def check_status(message):
    status_text = "📊 *Current Fleet Status:*\n\n"
    for car, max_liters in CAR_LIMITS.items():
        state = get_car_state(car)
        max_liters = CAR_LIMITS[car]
        
        if state["state"] == "READY":
            status_text += f"🟢 *{car}*: READY (Day 1 Available)\n"
        else: # ACTIVE
            fills_left = 2 - state["fills"]
            liters_left = max_liters - state["liters"]
            indicator = "🔴" if (fills_left <= 0 or liters_left <= 0) else "🟢"
            status_text += f"{indicator} *{car}*: ACTIVE ({liters_left}L left, resets {state['reset_time'].strftime('%b %d')})\n"
    
    bot.reply_to(message, status_text, parse_mode='Markdown')

# --- HISTORY COMMAND ---
@bot.message_handler(commands=['history'])
def history_start(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True, one_time_keyboard=True)
    markup.add(*CAR_LIMITS.keys())
    msg = bot.reply_to(message, "🔍 Which car's history?", reply_markup=markup)
    bot.register_next_step_handler(msg, process_history_step)

def process_history_step(message):
    car = message.text
    markup = types.ReplyKeyboardRemove()
    if car not in CAR_LIMITS:
        bot.reply_to(message, "❌ Unrecognized car.", reply_markup=markup)
        return
        
    cursor.execute("SELECT driver, liters, fill_date FROM records WHERE car=? ORDER BY fill_date DESC LIMIT 5", (car,))
    records = cursor.fetchall()
    
    if not records:
        bot.reply_to(message, f"📝 No logs found for *{car}*.", parse_mode='Markdown', reply_markup=markup)
        return
        
    hist_text = f"📝 *Last 5 logs for {car}:*\n\n"
    for r in records:
        date_str = datetime.fromisoformat(r[2]).strftime('%b %d at %I:%M %p')
        safe_name = r[0].replace('*', '').replace('_', '')
        hist_text += f"⛽ {r[1]}L by {safe_name} on {date_str}\n"
        
    bot.reply_to(message, hist_text, parse_mode='Markdown', reply_markup=markup)

# --- UNDO COMMAND ---
@bot.message_handler(commands=['undo'])
def undo_last(message):
    driver = message.from_user.first_name.replace('*', '').replace('_', '').replace('`', '')
    cursor.execute("SELECT id, car, liters FROM records WHERE driver=? ORDER BY fill_date DESC LIMIT 1", (driver,))
    record = cursor.fetchone()
    
    if not record:
        bot.reply_to(message, "⚠️ Couldn't find recent logs from you.")
        return
        
    cursor.execute("DELETE FROM records WHERE id=?", (record[0],))
    conn.commit()
    bot.reply_to(message, f"⏪ *Undone!* Deleted your last entry: {record[2]}L for {record[1]}.", parse_mode='Markdown')

# --- RUN BOT ---
print("Fuel Tracker Bot v5 (7-Day Cycle) is running...")

bot.set_my_commands([
    BotCommand("check", "🚦 Pre-check if a car can get petrol"),
    BotCommand("fill", "⛽ Log a new petrol fill"),
    BotCommand("status", "📊 Check all cars' cycle status"),
    BotCommand("history", "📝 See recent logs for a car"),
    BotCommand("undo", "⏪ Delete your last entry"),
    BotCommand("help", "ℹ️ Show instructions")
])

bot.infinity_polling()