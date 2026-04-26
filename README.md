# ⛽ Family Fuel Tracker Bot (FuelLogic)

A smart, zero-typing Telegram bot designed to manage strict government fuel rationing quotas for a multi-car family fleet. Built with Python, this bot acts as an automated dispatcher to prevent wasted trips to the petrol station by tracking complex active windows, blackout periods, and license plate date rules.

## ✨ Features

* **100% Zero-Typing Interface:** Users interact entirely via dynamic inline buttons. The bot calculates the exact remaining allowance and generates custom buttons for liters (e.g., `5L`, `10L`, `Full Allowance (15.0L)`).
* **Smart Pre-Check (`/check`):** Instantly calculates date parity and rolling quota status to give a green/red light before the driver leaves the house.
* **Proactive "Smart Dispatcher":** Runs a background scheduler to send automated alerts to the family group chat when a car's active window is closing or when a blackout period ends.
* **Automated Weekly Backups:** Automatically extracts the SQLite database and privately messages it to the admin every Sunday night to prevent data loss.

---

## 🧠 The Rationing Logic

This bot is hardcoded to manage a specific **Triggered Cycle** rationing system. 



1. **The Active Window (Days 1-7):** The moment a car gets fuel, a 7-day clock starts. During this window, the car has a maximum of 2 fills and a hard limit of liters (35L or 40L depending on the car).
2. **The Blackout Period (Days 8-9):** The car is strictly locked out of the system. No fuel can be purchased, even if there is unused allowance from the Active Window.
3. **The Reset (Day 10):** The slate is wiped clean. The car is ready to trigger a new Day 1 cycle at any time.
4. **Odd/Even Date Rule:** Cars with Odd license plates can only get fuel on Odd dates (1st, 3rd, 15th), and Even plates on Even dates. 

---

## 🛠️ Setup & Installation

### Prerequisites
* Python 3.8+
* A Telegram Bot Token (from [@BotFather](https://t.me/botfather))
* Your Personal Telegram ID (from [@userinfobot](https://t.me/userinfobot))
* Your Family Group Chat ID (from [@RawDataBot](https://t.me/RawDataBot))

### 1. Clone the Repository
```bash
git clone [https://github.com/Fxdictator/FuelLogic_bot.git](https://github.com/Fxdictator/FuelLogic_bot.git)
cd FuelLogic_bot