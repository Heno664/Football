import os
import json
import time
import random
import sqlite3
from flask import Flask, request, send_from_directory
import requests

BOT_TOKEN = os.environ.get("8577376940:AAGT_NbFUdmIQtDy1jKoRQ_dnokAgZVkRPY", "8577376940:AAGT_NbFUdmIQtDy1jKoRQ_dnokAgZVkRPY")
WEBAPP_URL = "https://football-production-d728.up.railway.app/web/index.html"  # ссылка на твою игру

app = Flask(__name__, static_folder="web", static_url_path="/web")

@app.route("/", methods=["GET"])
def home():
    return "Server is running", 200

def tg_send_message(chat_id: int, text: str, reply_markup=None):
    url = f"https://api.telegram.org/bot{"8577376940:AAGT_NbFUdmIQtDy1jKoRQ_dnokAgZVkRPY"}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload, timeout=10)

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or {}
    text = message.get("text", "")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if not chat_id:
        return "ok", 200

    # /start
    if text.startswith("/start"):
        keyboard = {
            "inline_keyboard": [[
                {"text": "⚽ Играть", "web_app": {"url": WEBAPP_URL}}
            ]]
        }
        tg_send_message(chat_id, "Привет! Нажми «Играть» чтобы открыть игру 👇", keyboard)
        return "ok", 200

    # любые другие сообщения
    tg_send_message(chat_id, "Напиши /start чтобы открыть игру ⚽")
    return "ok", 200

# ---------- Database ----------
conn = sqlite3.connect("game.db", check_same_thread=False)
cur = conn.cursor()

# Users table
cur.execute("""CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY,
 coins INTEGER DEFAULT 1000,
 last_daily INTEGER DEFAULT 0,
 club_real TEXT,
 club_custom TEXT
)""")

# Players table
cur.execute("""CREATE TABLE IF NOT EXISTS players (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER,
 name TEXT,
 position TEXT,
 attack INTEGER,
 defense INTEGER,
 speed INTEGER,
 rarity TEXT,
 image TEXT
)""")

# Market table
cur.execute("""CREATE TABLE IF NOT EXISTS market (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 seller_id INTEGER,
 player_id INTEGER,
 price INTEGER
)""")
conn.commit()

# ---------- Load JSON ----------
with open("players.json", encoding="utf-8") as f:
    PLAYERS = json.load(f)

with open("clubs.json", encoding="utf-8") as f:
    CLUBS = json.load(f)

# ---------- Provider Token ----------
PROVIDER_TOKEN = "1877036958:TEST:086ec82e70265c9632a476edd85723f6ce0784f2"  # вставь сюда токен от BotFather

# ---------- Endpoints ----------

# Daily reward
@app.route("/daily", methods=["POST"])
def daily():
    user = request.json["user_id"]
    now = int(time.time())
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user,))
    cur.execute("SELECT last_daily FROM users WHERE id=?", (user,))
    last = cur.fetchone()[0]
    if now - last < 86400:
        return {"message":"Уже получал сегодня"}
    reward = random.randint(200,500)
    cur.execute("UPDATE users SET coins=coins+?, last_daily=? WHERE id=?", (reward, now, user))
    conn.commit()
    return {"message":f"+{reward} монет 💰"}

@app.route("/game")
def game():
    return send_from_directory("web", "index.html")

# Open pack
@app.route("/open_pack", methods=["POST"])
def open_pack():
    user = request.json["user_id"]
    cur.execute("SELECT coins FROM users WHERE id=?", (user,))
    if cur.fetchone()[0] < 300:
        return {"error":"Недостаточно монет"}
    cur.execute("UPDATE users SET coins=coins-300 WHERE id=?", (user,))
    p = random.choice(PLAYERS)
    cur.execute("""INSERT INTO players (user_id,name,position,attack,defense,speed,rarity,image)
                VALUES (?,?,?,?,?,?,?,?)""",
                (user,p["name"],p["position"],p["attack"],p["defense"],p["speed"],p["rarity"],p["image"]))
    conn.commit()
    return p

# PvP match
@app.route("/match", methods=["POST"])
def match():
    user = request.json["user_id"]
    cur.execute("SELECT attack,defense,speed FROM players WHERE user_id=?", (user,))
    team = cur.fetchall()
    if not team:
        return {"error":"Нет игроков"}
    power = sum([sum(p) for p in team])//len(team)
    enemy = random.randint(150,300)
    if power>enemy:
        reward=random.randint(200,400)
        cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (reward,user))
        conn.commit()
        return {"result":"win","reward":reward,"your":power,"enemy":enemy}
    return {"result":"lose","your":power,"enemy":enemy}

# Market
@app.route("/market")
def market():
    cur.execute("""SELECT market.id, players.name, players.position, players.attack,
                   players.defense, players.speed, players.rarity, players.image, market.price
                   FROM market JOIN players ON market.player_id = players.id""")
    return {"market":cur.fetchall()}

# Buy player from market
@app.route("/buy_player", methods=["POST"])
def buy():
    buyer=request.json["user_id"]
    market_id=request.json["market_id"]
    cur.execute("SELECT seller_id,player_id,price FROM market WHERE id=?", (market_id,))
    seller,player_id,price = cur.fetchone()
    cur.execute("UPDATE users SET coins=coins-? WHERE id=?", (price,buyer))
    cur.execute("UPDATE users SET coins=coins+? WHERE id=?", (price,seller))
    cur.execute("UPDATE players SET user_id=? WHERE id=?", (buyer,player_id))
    cur.execute("DELETE FROM market WHERE id=?", (market_id,))
    conn.commit()
    return {"message":"Игрок куплен"}

# Clubs
@app.route("/clubs")
def clubs(): return {"clubs":CLUBS}

# Buy coins (Telegram Payment)
@app.route("/buy_coins", methods=["POST"])
def buy_coins():
    user = request.json["user_id"]
    amount = request.json["amount"]
    price = amount * 0.1  # 10 монет = $1
    payload = {
        "chat_id": user,
        "provider_token": PROVIDER_TOKEN,
        "start_parameter": f"coins_{amount}",
        "title": f"Покупка {amount} монет",
        "description": f"Покупка {amount} монет для игры Football Stars",
        "currency": "USD",
        "prices": [{"label": f"{amount} монет", "amount": int(price*100)}]
    }
    return payload

# Add coins after payment
@app.route("/add_coins", methods=["POST"])
def add_coins():
    user = request.json["user_id"]
    amount = request.json["amount"]
    cur.execute("UPDATE users SET coins = coins + ? WHERE id=?", (amount,user))
    conn.commit()
    return {"message":f"+{amount} монет добавлено"}

# Run server
if __name__=="__main__":
    app.run(port=5000)








