import json
import os
import random
import sqlite3
import time

import requests
from flask import Flask, jsonify, redirect, request, send_from_directory

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PROVIDER_TOKEN = os.environ.get("PROVIDER_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://football-production-d728.up.railway.app/web/index.html")

app = Flask(__name__, static_folder="web", static_url_path="/web")
conn = sqlite3.connect("game.db", check_same_thread=False)

conn.execute(
    """CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY,
 coins INTEGER DEFAULT 1000,
 last_daily INTEGER DEFAULT 0,
 club_real TEXT,
 club_custom TEXT
)"""
)
conn.execute(
    """CREATE TABLE IF NOT EXISTS players (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id INTEGER,
 name TEXT,
 position TEXT,
 attack INTEGER,
 defense INTEGER,
 speed INTEGER,
 rarity TEXT,
 image TEXT
)"""
)
conn.execute(
    """CREATE TABLE IF NOT EXISTS market (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 seller_id INTEGER,
 player_id INTEGER,
 price INTEGER
)"""
)
conn.commit()

with open("players.json", encoding="utf-8") as f:
    PLAYERS = json.load(f)
with open("clubs.json", encoding="utf-8") as f:
    CLUBS = json.load(f)


def db_fetchone(query, params=()):
    return conn.execute(query, params).fetchone()


def db_fetchall(query, params=()):
    return conn.execute(query, params).fetchall()


def ensure_user(user_id: int):
    conn.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (user_id,))
    conn.commit()


def json_error(message: str, code: int = 400):
    return jsonify({"ok": False, "error": message}), code


def tg_send_message(chat_id: int, text: str, reply_markup=None):
    if not BOT_TOKEN:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(url, json=payload, timeout=10)


@app.route("/", methods=["GET"])
def home():
    return redirect("/game")


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    message = data.get("message") or {}
    text = message.get("text", "")
    chat_id = (message.get("chat") or {}).get("id")

    if not chat_id:
        return "ok", 200

    if text.startswith("/start"):
        keyboard = {"inline_keyboard": [[{"text": "⚽ Играть", "web_app": {"url": WEBAPP_URL}}]]}
        tg_send_message(chat_id, "Привет! Нажми «Играть» чтобы открыть игру 👇", keyboard)
    else:
        tg_send_message(chat_id, "Напиши /start чтобы открыть игру ⚽")
    return "ok", 200


@app.route("/game")
def game():
    return send_from_directory("web", "index.html")


@app.route("/profile")
def profile():
    user = request.args.get("user_id", type=int)
    if not user:
        return json_error("Не указан user_id")
    ensure_user(user)

    row = db_fetchone("SELECT coins, last_daily FROM users WHERE id=?", (user,))
    cards_count = db_fetchone("SELECT COUNT(*) FROM players WHERE user_id=?", (user,))[0]
    return {"ok": True, "profile": {"coins": row[0], "last_daily": row[1], "cards_count": cards_count}}


@app.route("/my_players")
def my_players():
    user = request.args.get("user_id", type=int)
    if not user:
        return json_error("Не указан user_id")
    ensure_user(user)

    rows = db_fetchall(
        "SELECT id, name, position, attack, defense, speed, rarity, image FROM players WHERE user_id=? ORDER BY id DESC",
        (user,),
    )
    players = [
        {
            "id": row[0],
            "name": row[1],
            "position": row[2],
            "attack": row[3],
            "defense": row[4],
            "speed": row[5],
            "rarity": row[6],
            "image": row[7],
        }
        for row in rows
    ]
    return {"ok": True, "players": players}


@app.route("/daily", methods=["POST"])
def daily():
    user = (request.json or {}).get("user_id")
    if not user:
        return json_error("Не указан user_id")
    ensure_user(user)

    now = int(time.time())
    last = db_fetchone("SELECT last_daily FROM users WHERE id=?", (user,))[0]
    if now - last < 86400:
        return {"ok": False, "message": "Уже получал сегодня"}

    reward = random.randint(200, 500)
    conn.execute("UPDATE users SET coins=coins+?, last_daily=? WHERE id=?", (reward, now, user))
    conn.commit()
    return {"ok": True, "message": f"+{reward} монет 💰", "reward": reward}


@app.route("/open_pack", methods=["POST"])
def open_pack():
    user = (request.json or {}).get("user_id")
    if not user:
        return json_error("Не указан user_id")
    ensure_user(user)

    coins = db_fetchone("SELECT coins FROM users WHERE id=?", (user,))[0]
    if coins < 300:
        return json_error("Недостаточно монет")

    p = random.choice(PLAYERS)
    conn.execute("UPDATE users SET coins=coins-300 WHERE id=?", (user,))
    conn.execute(
        "INSERT INTO players (user_id,name,position,attack,defense,speed,rarity,image) VALUES (?,?,?,?,?,?,?,?)",
        (user, p["name"], p["position"], p["attack"], p["defense"], p["speed"], p["rarity"], p["image"]),
    )
    conn.commit()
    return {"ok": True, "player": p}


@app.route("/match", methods=["POST"])
def match():
    user = (request.json or {}).get("user_id")
    if not user:
        return json_error("Не указан user_id")
    ensure_user(user)

    team = db_fetchall("SELECT attack,defense,speed FROM players WHERE user_id=?", (user,))
    if not team:
        return json_error("Нет игроков")

    power = sum(sum(p) for p in team) // len(team)
    enemy = random.randint(150, 300)
    if power > enemy:
        reward = random.randint(200, 400)
        conn.execute("UPDATE users SET coins=coins+? WHERE id=?", (reward, user))
        conn.commit()
        return {"ok": True, "result": "win", "reward": reward, "your": power, "enemy": enemy}
    return {"ok": True, "result": "lose", "your": power, "enemy": enemy}


@app.route("/market")
def market():
    rows = db_fetchall(
        """SELECT market.id, players.name, players.position, players.attack,
                  players.defense, players.speed, players.rarity, players.image, market.price
           FROM market JOIN players ON market.player_id = players.id"""
    )
    return {
        "ok": True,
        "market": [
            {
                "id": row[0],
                "name": row[1],
                "position": row[2],
                "attack": row[3],
                "defense": row[4],
                "speed": row[5],
                "rarity": row[6],
                "image": row[7],
                "price": row[8],
            }
            for row in rows
        ],
    }


@app.route("/buy_player", methods=["POST"])
def buy_player():
    data = request.json or {}
    buyer = data.get("user_id")
    market_id = data.get("market_id")
    if not buyer or not market_id:
        return json_error("Некорректные параметры")

    ensure_user(buyer)
    row = db_fetchone("SELECT seller_id,player_id,price FROM market WHERE id=?", (market_id,))
    if not row:
        return json_error("Лот не найден", 404)

    seller, player_id, price = row
    if seller == buyer:
        return json_error("Нельзя купить своего игрока")

    ensure_user(seller)
    buyer_coins = db_fetchone("SELECT coins FROM users WHERE id=?", (buyer,))[0]
    if buyer_coins < price:
        return json_error("Недостаточно монет")

    try:
        conn.execute("BEGIN")
        conn.execute("UPDATE users SET coins=coins-? WHERE id=?", (price, buyer))
        conn.execute("UPDATE users SET coins=coins+? WHERE id=?", (price, seller))
        conn.execute("UPDATE players SET user_id=? WHERE id=?", (buyer, player_id))
        conn.execute("DELETE FROM market WHERE id=?", (market_id,))
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        return json_error("Не удалось выполнить покупку", 500)

    return {"ok": True, "message": "Игрок куплен"}


@app.route("/clubs")
def clubs():
    return {"ok": True, "clubs": CLUBS}


@app.route("/buy_coins", methods=["POST"])
def buy_coins():
    user = (request.json or {}).get("user_id")
    amount = (request.json or {}).get("amount")
    if not user or not amount:
        return json_error("Некорректные параметры")
    if not PROVIDER_TOKEN:
        return json_error("Платежи не настроены", 503)

    price = amount * 0.1
    return {
        "ok": True,
        "invoice": {
            "chat_id": user,
            "provider_token": PROVIDER_TOKEN,
            "start_parameter": f"coins_{amount}",
            "title": f"Покупка {amount} монет",
            "description": f"Покупка {amount} монет для игры Football Stars",
            "currency": "USD",
            "prices": [{"label": f"{amount} монет", "amount": int(price * 100)}],
        },
    }


@app.route("/add_coins", methods=["POST"])
def add_coins():
    user = (request.json or {}).get("user_id")
    amount = (request.json or {}).get("amount")
    if not user or not amount:
        return json_error("Некорректные параметры")

    ensure_user(user)
    conn.execute("UPDATE users SET coins = coins + ? WHERE id=?", (amount, user))
    conn.commit()
    return {"ok": True, "message": f"+{amount} монет добавлено"}


if __name__ == "__main__":
    app.run(port=5000)
