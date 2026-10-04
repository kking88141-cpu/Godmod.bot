#!/usr/bin/env python3
import os, sys, time, subprocess, sqlite3, threading
from concurrent.futures import ThreadPoolExecutor

def inject_libraries():
    try:
        import requests
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "--quiet"])

inject_libraries()
import requests

TELEGRAM_BOT_TOKEN = "8897482341:AAFrc96EoM2G8OGX7vqe1Pfeg7WEy9xWUgQ"
DB_NAME = "godmood_fast_realtime.db"

CACHED_WEIGHTS = None
BET_LEVELS = [10, 22, 52]
TARGET_BALANCE = 500

executor = ThreadPoolExecutor(max_workers=30)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA synchronous=OFF;")
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS predictions (
            period TEXT PRIMARY KEY,
            prediction TEXT,
            result TEXT,
            status TEXT,
            bet_amount INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS weights (
            model_id INTEGER PRIMARY KEY,
            weight REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS state (
            key TEXT PRIMARY KEY,
            value REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_ids (
            chat_id INTEGER PRIMARY KEY
        )
    ''')
    
    cursor.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('current_level', 1)")
    cursor.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('balance', 100)")
    cursor.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('total_bets', 0)")
    cursor.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('total_wins', 0)")
    cursor.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('total_losses', 0)")
    cursor.execute("INSERT OR IGNORE INTO state (key, value) VALUES ('engine_active', 1)")
    
    cursor.execute("SELECT COUNT(*) FROM weights")
    if cursor.fetchone()[0] == 0:
        for i in range(10):
            cursor.execute("INSERT INTO weights (model_id, weight) VALUES (?, ?)", (i, 1.0))
    conn.commit()
    conn.close()

init_db()

def get_state(key, default=0):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=0.01)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM state WHERE key=?", (key,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default
    except:
        return default

def update_state(key, value):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=0.01)
        cursor = conn.cursor()
        cursor.execute("UPDATE state SET value = ? WHERE key=?", (value, key))
        conn.commit()
        conn.close()
    except:
        pass

def get_stats():
    return {
        "balance": float(get_state('balance', 100.0)),
        "level": int(get_state('current_level', 1)),
        "bets": int(get_state('total_bets', 0)),
        "wins": int(get_state('total_wins', 0)),
        "losses": int(get_state('total_losses', 0)),
        "active": int(get_state('engine_active', 1))
    }

def update_game_state(status, bet_amount):
    current_level = int(get_state('current_level', 1))
    current_balance = float(get_state('balance', 100.0))
    
    total_bets = int(get_state('total_bets', 0)) + 1
    total_wins = int(get_state('total_wins', 0))
    total_losses = int(get_state('total_losses', 0))
    
    if status == "🟢 WIN":
        current_balance += bet_amount
        current_level = 1
        total_wins += 1
    else:
        current_balance -= bet_amount
        current_level += 1
        if current_level > 3:
            current_level = 3
        total_losses += 1
            
    update_state('current_level', current_level)
    update_state('balance', current_balance)
    update_state('total_bets', total_bets)
    update_state('total_wins', total_wins)
    update_state('total_losses', total_losses)
    
    return current_balance, current_level, {"bets": total_bets, "wins": total_wins, "losses": total_losses}

def reset_session_for_restart():
    update_state('balance', 100)
    update_state('current_level', 1)
    update_state('total_bets', 0)
    update_state('total_wins', 0)
    update_state('total_losses', 0)

def add_chat_id(chat_id):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=0.01)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO chat_ids (chat_id) VALUES (?)", (chat_id,))
        conn.commit()
        conn.close()
    except:
        pass

def get_all_chat_ids():
    try:
        conn = sqlite3.connect(DB_NAME, timeout=0.01)
        cursor = conn.cursor()
        cursor.execute("SELECT chat_id FROM chat_ids")
        rows = cursor.fetchall()
        conn.close()
        return [r[0] for r in rows]
    except:
        return []

def send_message_to_chat(chat_id, message):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=0.3)
    except:
        pass

def broadcast_message(message):
    chat_ids = get_all_chat_ids()
    if not chat_ids:
        return
    for cid in chat_ids:
        executor.submit(send_message_to_chat, cid, message)

def background_command_listener():
    offset = 0
    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=1"
            res = requests.get(url, timeout=1).json()
            if res.get("ok") and res.get("result"):
                for item in res["result"]:
                    offset = item["update_id"] + 1
                    if "message" in item and "chat" in item["message"]:
                        chat_id = item["message"]["chat"]["id"]
                        text = item["message"].get("text", "").strip().lower()
                        
                        add_chat_id(chat_id)
                        
                        if text == "/start":
                            update_state('engine_active', 1)
                            stats = get_stats()
                            msg = (
                                f"🚀 *Godmood Realtime Engine Started!*\n\n"
                                f"✅ बॉट सुपर-फास्ट मोड में एक्टिव है।\n"
                                f"💰 Balance: `₹{stats['balance']:.1f}` | Level: `{stats['level']}`"
                            )
                            executor.submit(send_message_to_chat, chat_id, msg)
                            
                        elif text == "/stop":
                            update_state('engine_active', 0)
                            msg = "🛑 *Godmood Engine Stopped!*\nबॉट को रोक दिया गया है। चालू करने के लिए `/start` भेजें।"
                            executor.submit(send_message_to_chat, chat_id, msg)
                            
                        elif text == "/status":
                            stats = get_stats()
                            status_msg = (
                                f"📊 *Live Engine Status*\n"
                                f"• Status: `{'🟢 RUNNING' if stats['active'] == 1 else '🔴 STOPPED'}`\n"
                                f"• Balance: `₹{stats['balance']:.1f}` (Target: `₹{TARGET_BALANCE}`)\n"
                                f"• Level: `{stats['level']}`\n"
                                f"• Total Bets: `{stats['bets']}`\n"
                                f"• Wins: `{stats['wins']}` | Losses: `{stats['losses']}`"
                            )
                            executor.submit(send_message_to_chat, chat_id, status_msg)
        except:
            pass
        time.sleep(0.05)

def load_weights_from_db():
    global CACHED_WEIGHTS
    if CACHED_WEIGHTS is not None:
        return CACHED_WEIGHTS
    try:
        conn = sqlite3.connect(DB_NAME, timeout=0.01)
        cursor = conn.cursor()
        cursor.execute("SELECT weight FROM weights ORDER BY model_id ASC")
        weights = [row[0] for row in cursor.fetchall()]
        conn.close()
        CACHED_WEIGHTS = weights if len(weights) == 10 else [1.0] * 10
    except:
        CACHED_WEIGHTS = [1.0] * 10
    return CACHED_WEIGHTS

def save_weights_to_db(weights):
    global CACHED_WEIGHTS
    CACHED_WEIGHTS = weights
    def _save():
        try:
            conn = sqlite3.connect(DB_NAME, timeout=0.01)
            cursor = conn.cursor()
            for i, w in enumerate(weights):
                cursor.execute("UPDATE weights SET weight = ? WHERE model_id = ?", (w, i))
            conn.commit()
            conn.close()
        except:
            pass
    executor.submit(_save)

def save_prediction_to_db(period, prediction, bet_amount, result=None, status=None):
    def _save():
        try:
            conn = sqlite3.connect(DB_NAME, timeout=0.01)
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO predictions (period, prediction, bet_amount, result, status)
                VALUES (?, ?, ?, ?, ?)
            ''', (period, prediction, bet_amount, result, status))
            conn.commit()
            conn.close()
        except:
            pass
    executor.submit(_save)

def get_recent_logs_from_db(limit=1):
    try:
        conn = sqlite3.connect(DB_NAME, timeout=0.01)
        cursor = conn.cursor()
        cursor.execute("SELECT period, prediction, result, status FROM predictions WHERE status IS NOT NULL ORDER BY period DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [{"period": r[0], "pred": r[1], "res": r[2], "status": r[3]} for r in rows[::-1]]
    except:
        return []

API_URL = "https://draw.ar-lottery01.com/WinGo/WinGo_30S/GetHistoryIssuePage.json?ts={}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro)",
    "Accept": "application/json",
    "Connection": "keep-alive"
}

def get_type(num):
    return "BIG" if int(num) >= 5 else "SMALL"

def god_ai_brain(next_period, data_list):
    god_weights = load_weights_from_db()
    if not data_list or len(data_list) < 10:
        import random
        return random.choice(["BIG", "SMALL"]), [], 85.0

    raw_nums = [int(item.get('number')) for item in data_list[:30] if item.get('number') is not None]
    trends = [get_type(n) for n in raw_nums]
    p_suffix = int(next_period[-4:]) if next_period.isdigit() else 777

    big_ratio = trends.count("BIG") / len(trends) if trends else 0.5
    chaos_shift = "SMALL" if big_ratio > 0.6 else "BIG"
    fib_sum = sum(raw_nums[i] for i in [0, 1, 2, 4, 7] if i < len(raw_nums))
    fib_pred = "BIG" if (fib_sum % 2 == 0) else "SMALL"
    mirror_pred = trends[0] if len(trends) > 1 and trends[0] != trends[1] else ("SMALL" if trends and trends[0] == "BIG" else "BIG")

    candidates = [
        chaos_shift, fib_pred, mirror_pred,
        "BIG" if raw_nums and ((raw_nums[0] * 7 + p_suffix) % 10) >= 5 else "SMALL",
        "SMALL" if trends and trends[:3].count("BIG") >= 2 else "BIG",
        trends[0] if trends else "BIG",
        "BIG" if raw_nums and (sum(raw_nums[:5]) / 5) >= 4.5 else "SMALL",
        "SMALL" if len(trends) > 1 and trends[0] == "BIG" and trends[1] == "BIG" else "BIG",
        "BIG" if p_suffix % 2 == 0 else "SMALL",
        trends[2] if len(trends) > 2 else "BIG"
    ]

    big_score = sum(god_weights[i] for i, choice in enumerate(candidates) if choice == "BIG")
    small_score = sum(god_weights[i] for i, choice in enumerate(candidates) if choice == "SMALL")
    
    total_w = big_score + small_score
    confidence = (max(big_score, small_score) / total_w) * 100 if total_w > 0 else 88.5

    decision = "BIG" if big_score >= small_score else "SMALL"
    return decision, candidates, confidence

def update_god_weights(actual_trend, last_votes):
    def _update():
        god_weights = load_weights_from_db()
        if not last_votes or len(last_votes) < len(god_weights):
            return
        for i, vote in enumerate(last_votes):
            if vote == actual_trend:
                god_weights[i] = min(god_weights[i] + 0.30, 5.0)
            else:
                god_weights[i] = max(god_weights[i] - 0.35, 0.01)
        save_weights_to_db(god_weights)
    executor.submit(_update)

def run_engine():
    threading.Thread(target=background_command_listener, daemon=True).start()
    print("[*] Ultra-Fast Realtime Engine Started...")
    time.sleep(0.2)
    
    broadcast_message(f"🚀 *Godmood Realtime Engine Activated*\n💰 Starting Balance: `₹{get_state('balance', 100)}`\n🎯 Target Limit: `₹{TARGET_BALANCE}`")
    
    last_processed_period = None
    active_pred = None
    session = requests.Session()
    
    while True:
        try:
            if int(get_state('engine_active', 1)) == 0:
                time.sleep(0.5)
                continue

            ts = int(time.time() * 1000)
            response = session.get(API_URL.format(ts), headers=HEADERS, timeout=0.4)
            if response.status_code != 200:
                time.sleep(0.1)
                continue
                
            json_data = response.json()
            data = json_data.get("data", {}).get("list", [])
            if not data:
                time.sleep(0.1)
                continue
                
            latest = data[0]
            current_period = latest.get("issueNumber")
            result_num = latest.get("number")
            
            # जब भी नया पीरियड वेबसाइट पर अपडेट हो जाए
            if current_period and current_period != last_processed_period:
                last_processed_period = current_period
                
                # 1. अगर पिछला कोई प्रेडिक्शन चल रहा था, तो उसका रिजल्ट तुरंत वैलिडेट करें
                if active_pred and active_pred["period"] == current_period:
                    actual_trend = get_type(result_num)
                    status = "🟢 WIN" if active_pred["prediction"] == actual_trend else "🔴 LOSS"
                    
                    new_balance, new_level, stats = update_game_state(status, active_pred["bet_amount"])
                    save_prediction_to_db(current_period, active_pred["prediction"], active_pred["bet_amount"], f"{result_num} ({actual_trend})", status)
                    update_god_weights(actual_trend, active_pred["votes"])
                    
                    msg = (
                        f"📊 *Result Update*\n"
                        f"🔹 Period: `{current_period}`\n"
                        f"🎯 Prediction: *{active_pred['prediction']}*\n"
                        f"🎲 Actual: *{result_num} ({actual_trend})*\n"
                        f"📌 Status: *{status}*\n"
                        f"💰 Current Balance: `₹{new_balance:.1f}`\n\n"
                        f"📈 *Session Stats:*\n"
                        f"• Total Bets: `{stats['bets']}`\n"
                        f"• Wins: `{stats['wins']}` | Losses: `{stats['losses']}`"
                    )
                    broadcast_message(msg)
                    
                    if new_balance >= TARGET_BALANCE:
                        target_msg = (
                            f"🎉 *TARGET REACHED! (₹{TARGET_BALANCE}+)* 🚀\n\n"
                            f"बधाई हो! टारगेट पूरा हो गया है।\n"
                            f"💰 Final Balance: `₹{new_balance:.1f}`\n\n"
                            f"🔄 *बॉट ऑटोमैटिक रीसेट होकर ₹100 से दोबारा शुरू हो रहा है...*"
                        )
                        broadcast_message(target_msg)
                        reset_session_for_restart()
                        time.sleep(0.1)
                        broadcast_message(f"🔥 *New Session Started!* \n💰 Balance: `₹100`")
                        
                    active_pred = None
                
                # 2. तुरंत अगले आने वाले पीरियड का प्रेडिक्शन जेनरेट करके भेजें
                next_period = str(int(current_period) + 1) if current_period.isdigit() else "Error"
                
                lvl = int(get_state('current_level', 1))
                bet_amount = BET_LEVELS[lvl - 1] if lvl <= len(BET_LEVELS) else BET_LEVELS[-1]
                current_bal = float(get_state('balance', 100.0))
                stats = get_stats()
                
                final_decision, votes, confidence = god_ai_brain(next_period, data)
                active_pred = {
                    "period": next_period, 
                    "prediction": final_decision, 
                    "votes": votes,
                    "bet_amount": bet_amount
                }
                
                save_prediction_to_db(next_period, final_decision, bet_amount)
                
                msg = (
                    f"🔥 *New Godmood Prediction*\n"
                    f"⏱ Target Period: `{next_period}`\n"
                    f"🔮 Prediction: *{final_decision}*\n"
                    f"💰 Investment: *₹{bet_amount}* (Level {lvl})\n"
                    f"💼 Wallet Balance: `₹{current_bal:.1f}`\n"
                    f"📈 Confidence: `{confidence:.1f}%`\n\n"
                    f"📊 *Stats:* (Bets: `{stats['bets']}` | Wins: `{stats['wins']}` | Losses: `{stats['losses']}`)"
                )
                broadcast_message(msg)
            
        except Exception:
            pass
            
        # बिना किसी डिले के सुपर-फास्ट लूप रन करने के लिए
        time.sleep(0.1)

if __name__ == "__main__":
    while True:
        try:
            run_engine()
        except Exception:
            time.sleep(1)
