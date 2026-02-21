import os
import json
import time
import sqlite3
import urllib.request
import urllib.parse
from flask import Flask, request, jsonify, send_from_directory

# =========================
# Config (ENV)
# =========================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")  # e.g. https://your-app.up.railway.app/web/index.html
P2P_PLAYER_FEE_PCT = 3  # buyer fee %
DAILY_COINS = 200
VIP_REWARD_BONUS = 1.10  # +10% rewards

app = Flask(__name__, static_folder="web", static_url_path="/web")

# =========================
# Data load
# =========================
def load_json_file(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return fallback

PLAYERS = load_json_file("players.json", [])
CLUBS = load_json_file("clubs.json", [])

PLAYERS_BY_ID = {int(p["id"]): p for p in PLAYERS if "id" in p}
CLUBS_BY_ID = {int(c["id"]): c for c in CLUBS if "id" in c}

# =========================
# DB helpers
# =========================
DB_PATH = "game.db"

def db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        club_id INTEGER DEFAULT 0,
        club_name TEXT DEFAULT '',
        coins INTEGER NOT NULL DEFAULT 0,
        last_daily INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        user_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        qty INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (user_id, player_id)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS market_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        price INTEGER NOT NULL,
        status TEXT NOT NULL, -- active/sold/canceled
        created_at INTEGER DEFAULT (strftime('%s','now')),
        sold_at INTEGER
    )
    """)

    # P2P player trades (escrow)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS p2p_player_trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        seller_id INTEGER NOT NULL,
        buyer_id INTEGER NOT NULL,
        player_id INTEGER NOT NULL,
        price INTEGER NOT NULL,
        fee INTEGER NOT NULL,
        status TEXT NOT NULL, -- pending/accepted/canceled
        created_at INTEGER DEFAULT (strftime('%s','now')),
        accepted_at INTEGER
    )
    """)

    # Transactions log
    cur.execute("""
    CREATE TABLE IF NOT EXISTS tx_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        delta INTEGER NOT NULL,
        note TEXT,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )
    """)

    # Level/XP
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_level (
        user_id INTEGER PRIMARY KEY,
        xp INTEGER NOT NULL DEFAULT 0,
        level INTEGER NOT NULL DEFAULT 1
    )
    """)

    # VIP
    cur.execute("""
    CREATE TABLE IF NOT EXISTS vip (
        user_id INTEGER PRIMARY KEY,
        vip_until INTEGER NOT NULL DEFAULT 0
    )
    """)

    # Stars purchase dedupe (safe)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS purchases (
        tg_charge_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        payload TEXT,
        created_at INTEGER DEFAULT (strftime('%s','now'))
    )
    """)

    conn.commit()
    conn.close()

init_db()

# =========================
# Telegram helpers
# =========================
def tg(method: str, payload: dict):
    if not BOT_TOKEN:
        return {"ok": False, "description": "BOT_TOKEN missing"}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"ok": False, "description": str(e)}

def tg_send_message(chat_id: int, text: str, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return tg("sendMessage", payload)

# =========================
# Economy / Inventory
# =========================
def log_tx(user_id: int, kind: str, delta: int, note: str = ""):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT INTO tx_log(user_id, kind, delta, note) VALUES(?,?,?,?)",
                (user_id, kind, int(delta), note[:200]))
    conn.commit()
    conn.close()

def ensure_user(user_id: int, username: str = ""):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO users(user_id, username) VALUES(?,?)", (user_id, username))
    if username:
        cur.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None

def add_coins(user_id: int, amount: int, kind: str = "coins_add", note: str = ""):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (int(amount), user_id))
    conn.commit()
    cur.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
    coins = cur.fetchone()["coins"]
    conn.close()
    log_tx(user_id, kind, +int(amount), note)
    return coins

def take_coins(user_id: int, amount: int, kind: str = "coins_spend", note: str = "") -> bool:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT coins FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row or row["coins"] < int(amount):
        conn.close()
        return False
    cur.execute("UPDATE users SET coins = coins - ? WHERE user_id=?", (int(amount), user_id))
    conn.commit()
    conn.close()
    log_tx(user_id, kind, -int(amount), note)
    return True

def add_player(user_id: int, player_id: int, qty: int = 1):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO inventory(user_id, player_id, qty) VALUES(?,?,0)", (user_id, player_id))
    cur.execute("UPDATE inventory SET qty = qty + ? WHERE user_id=? AND player_id=?", (int(qty), user_id, player_id))
    conn.commit()
    conn.close()

def remove_player(user_id: int, player_id: int, qty: int = 1) -> bool:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT qty FROM inventory WHERE user_id=? AND player_id=?", (user_id, player_id))
    row = cur.fetchone()
    if not row or int(row["qty"]) < int(qty):
        conn.close()
        return False
    cur.execute("UPDATE inventory SET qty = qty - ? WHERE user_id=? AND player_id=?", (int(qty), user_id, player_id))
    conn.commit()
    conn.close()
    return True

def get_inventory(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT player_id, qty FROM inventory WHERE user_id=? AND qty>0", (user_id,))
    rows = cur.fetchall()
    conn.close()
    items = []
    for r in rows:
        pid = int(r["player_id"])
        p = PLAYERS_BY_ID.get(pid)
        if p:
            items.append({"player": p, "qty": int(r["qty"])})
    return items

def squad_rating(user_id: int) -> int:
    inv = get_inventory(user_id)
    ratings = []
    for it in inv:
        p = it["player"]
        qty = it["qty"]
        for _ in range(min(qty, 3)):
            ratings.append(int(p.get("rating", 50)))
    ratings.sort(reverse=True)
    top = ratings[:5] if ratings else [50]
    return int(sum(top) / len(top))

# =========================
# VIP + Level
# =========================
def is_vip(user_id: int) -> bool:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT vip_until FROM vip WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return False
    return int(row["vip_until"]) > int(time.time())

def ensure_level_row(user_id: int):
    conn = db()
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO user_level(user_id, xp, level) VALUES(?,?,?)", (user_id, 0, 1))
    conn.commit()
    conn.close()

def xp_needed(level: int) -> int:
    return 100 + (level - 1) * 60

def add_xp(user_id: int, amount: int, note: str = ""):
    ensure_level_row(user_id)
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE user_level SET xp = xp + ? WHERE user_id=?", (int(amount), user_id))
    conn.commit()

    cur.execute("SELECT xp, level FROM user_level WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    xp, lvl = int(row["xp"]), int(row["level"])

    leveled_up = False
    while xp >= xp_needed(lvl):
        xp -= xp_needed(lvl)
        lvl += 1
        leveled_up = True

    cur.execute("UPDATE user_level SET xp=?, level=? WHERE user_id=?", (xp, lvl, user_id))
    conn.commit()
    conn.close()

    if leveled_up:
        add_coins(user_id, 50, kind="level_up", note=f"Level {lvl}")

    if note:
        log_tx(user_id, "xp", 0, f"+{amount} XP: {note}")

    return {"xp": xp, "level": lvl, "leveled_up": leveled_up}

# =========================
# Catalog (Stars)
# =========================
CATALOG = {
    "pack_small": {"title": "Пак Small", "desc": "Открыть 1 пак (1 игрок)", "stars": 10, "grant": {"packs": 1}},
    "pack_big": {"title": "Пак Big", "desc": "Открыть 5 паков (5 игроков)", "stars": 45, "grant": {"packs": 5}},
    "coins_1k": {"title": "1000 монет", "desc": "Добавит 1000 монет", "stars": 15, "grant": {"coins": 1000}},
    "sub_vip": {"title": "VIP на 30 дней", "desc": "Бонус +10% наград", "stars": 50, "grant": {"vip_days": 30}},
}

# store packs in user coins? we'll use "packs balance" via log only -> simple: packs are opened instantly after purchase? we grant "open tokens" as coins? We'll store packs as coins-like in tx note? Better: store in users table? We'll use coins only and open packs anytime with coins cost? 
# For simplicity: purchases grant "pack_credits" stored in users table as coins? We'll add field pack_credits.
def ensure_pack_credits_col():
    conn = db()
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(users)")
    cols = [r["name"] for r in cur.fetchall()]
    if "pack_credits" not in cols:
        cur.execute("ALTER TABLE users ADD COLUMN pack_credits INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    conn.close()
ensure_pack_credits_col()

def add_packs(user_id: int, n: int, note=""):
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET pack_credits = pack_credits + ? WHERE user_id=?", (int(n), user_id))
    conn.commit()
    conn.close()
    log_tx(user_id, "packs_add", 0, f"+{n} packs {note}")

def take_pack(user_id: int) -> bool:
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT pack_credits FROM users WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    if not row or int(row["pack_credits"]) <= 0:
        conn.close()
        return False
    cur.execute("UPDATE users SET pack_credits = pack_credits - 1 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()
    log_tx(user_id, "pack_open", 0, "Opened pack")
    return True

# =========================
# Routes
# =========================
@app.get("/health")
def health():
    return jsonify({"ok": True})

@app.get("/")
def root():
    # helpful default
    return jsonify({"ok": True, "web": "/web/index.html", "webhook": "/webhook"})

@app.get("/web/index.html")
def web_index():
    return send_from_directory("web", "index.html")

@app.post("/webhook")
def webhook():
    upd = request.get_json(silent=True) or {}

    # 1) messages
    msg = upd.get("message") or upd.get("edited_message")
    if msg:
        chat_id = msg["chat"]["id"]
        from_user = msg.get("from", {})
        user_id = int(from_user.get("id", 0))
        username = from_user.get("username") or (from_user.get("first_name", "") + " " + from_user.get("last_name", "")).strip()

        if user_id:
            ensure_user(user_id, username)

        text = (msg.get("text") or "").strip().lower()
        if text == "/start":
            if not WEBAPP_URL:
                tg_send_message(chat_id, "⚠️ WEBAPP_URL не задан в Railway Variables.\nНужно: https://.../web/index.html")
            else:
                keyboard = {
                    "inline_keyboard": [[{
                        "text": "Играть ⚽",
                        "web_app": {"url": WEBAPP_URL}
                    }]]
                }
                tg_send_message(chat_id, "Привет! Нажми «Играть» чтобы открыть игру 👇", keyboard)

        return jsonify({"ok": True})

    # 2) successful payment (Stars)
    sp = upd.get("message", {}).get("successful_payment")
    if sp:
        from_user = upd["message"].get("from", {})
        user_id = int(from_user.get("id", 0))
        ensure_user(user_id, from_user.get("username") or "")

        tg_charge_id = sp.get("telegram_payment_charge_id", "")
        payload = sp.get("invoice_payload", "")

        # dedupe
        conn = db()
        cur = conn.cursor()
        cur.execute("SELECT tg_charge_id FROM purchases WHERE tg_charge_id=?", (tg_charge_id,))
        if cur.fetchone():
            conn.close()
            return jsonify({"ok": True})
        cur.execute("INSERT INTO purchases(tg_charge_id, user_id, payload) VALUES(?,?,?)", (tg_charge_id, user_id, payload))
        conn.commit()
        conn.close()

        # payload format: product:userId:timestamp
        product = payload.split(":")[0] if payload else ""
        item = CATALOG.get(product)
        lines = []
        if not item:
            lines.append("Оплата получена ✅ (товар не найден в каталоге)")
        else:
            grant = item["grant"]
            if "coins" in grant:
                add_coins(user_id, int(grant["coins"]), kind="stars_buy", note=product)
                lines.append(f"✅ Начислено монет: {grant['coins']}")
            if "packs" in grant:
                add_packs(user_id, int(grant["packs"]), note=product)
                lines.append(f"✅ Паков добавлено: {grant['packs']}")
            if "vip_days" in grant:
                days = int(grant["vip_days"])
                add_seconds = days * 86400
                now = int(time.time())
                conn2 = db()
                cur2 = conn2.cursor()
                cur2.execute("INSERT OR IGNORE INTO vip(user_id, vip_until) VALUES(?,0)", (user_id,))
                conn2.commit()
                cur2.execute("SELECT vip_until FROM vip WHERE user_id=?", (user_id,))
                cur_until = int(cur2.fetchone()["vip_until"])
                new_until = max(cur_until, now) + add_seconds
                cur2.execute("UPDATE vip SET vip_until=? WHERE user_id=?", (new_until, user_id))
                conn2.commit()
                conn2.close()
                lines.append(f"⭐ VIP активен до: {time.strftime('%Y-%m-%d', time.gmtime(new_until))}")
                log_tx(user_id, "vip", 0, f"VIP until {new_until}")

        tg_send_message(upd["message"]["chat"]["id"], "\n".join(lines) if lines else "Оплата получена ✅")
        return jsonify({"ok": True})

    return jsonify({"ok": True})

# =========================
# API: bootstrap / data
# =========================
@app.get("/api/bootstrap")
def api_bootstrap():
    user_id = request.args.get("user_id", type=int)
    username = request.args.get("username", default="", type=str)
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400

    ensure_user(user_id, username)
    ensure_level_row(user_id)

    u = get_user(user_id)
    inv = get_inventory(user_id)
    vip = is_vip(user_id)

    # level
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT xp, level FROM user_level WHERE user_id=?", (user_id,))
    lr = cur.fetchone()
    cur.execute("SELECT vip_until FROM vip WHERE user_id=?", (user_id,))
    vr = cur.fetchone()
    conn.close()

    return jsonify({
        "ok": True,
        "user": {
            "user_id": user_id,
            "username": u.get("username",""),
            "club_id": u.get("club_id", 0),
            "club_name": u.get("club_name",""),
            "coins": u.get("coins", 0),
            "pack_credits": u.get("pack_credits", 0),
            "last_daily": u.get("last_daily", 0),
            "vip": vip,
            "vip_until": int(vr["vip_until"]) if vr else 0,
            "level": int(lr["level"]) if lr else 1,
            "xp": int(lr["xp"]) if lr else 0,
            "need": xp_needed(int(lr["level"]) if lr else 1)
        },
        "inventory": inv,
        "clubs": CLUBS,
        "players_count": len(PLAYERS)
    })

@app.get("/api/players")
def api_players():
    return jsonify({"ok": True, "players": PLAYERS})

@app.get("/api/clubs")
def api_clubs():
    return jsonify({"ok": True, "clubs": CLUBS})

@app.post("/api/set_club")
def api_set_club():
    data = request.get_json(silent=True) or {}
    user_id = int(data.get("user_id", 0))
    club_id = int(data.get("club_id", 0))
    club_name = (data.get("club_name") or "").strip()[:20]

    if not user_id or club_id <= 0:
        return jsonify({"ok": False, "error": "bad_params"}), 400
    if club_id not in CLUBS_BY_ID:
        return jsonify({"ok": False, "error": "unknown_club"}), 400

    ensure_user(user_id)
    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET club_id=?, club_name=? WHERE user_id=?", (club_id, club_name, user_id))
    conn.commit()
    conn.close()
    add_xp(user_id, 5, "Set club")
    return jsonify({"ok": True})

# =========================
# Daily reward
# =========================
@app.post("/api/daily/claim")
def api_daily_claim():
    data = request.get_json(silent=True) or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400

    ensure_user(user_id)
    u = get_user(user_id)
    now = int(time.time())
    last = int(u.get("last_daily", 0))
    if now - last < 24 * 3600:
        left = 24 * 3600 - (now - last)
        return jsonify({"ok": False, "error": "cooldown", "left": left}), 400

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE users SET last_daily=? WHERE user_id=?", (now, user_id))
    conn.commit()
    conn.close()

    reward = DAILY_COINS
    if is_vip(user_id):
        reward = int(reward * VIP_REWARD_BONUS)
    coins = add_coins(user_id, reward, kind="daily", note="Daily reward")
    add_xp(user_id, 10, "Daily reward")
    return jsonify({"ok": True, "coins": coins, "reward": reward})

# =========================
# Packs
# =========================
import random

def random_player():
    if not PLAYERS:
        return None
    # weighted by rating: higher rating slightly rarer
    pool = []
    for p in PLAYERS:
        r = int(p.get("rating", 50))
        w = max(1, 100 - r)  # rating 90 -> 10 weight, rating 70 -> 30 weight
        pool.append((p, w))
    total = sum(w for _, w in pool)
    x = random.randint(1, total)
    acc = 0
    for p, w in pool:
        acc += w
        if x <= acc:
            return p
    return pool[-1][0]

@app.post("/api/open_pack")
def api_open_pack():
    data = request.get_json(silent=True) or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400
    ensure_user(user_id)

    if not take_pack(user_id):
        return jsonify({"ok": False, "error": "no_packs"}), 400

    p = random_player()
    if not p:
        return jsonify({"ok": False, "error": "no_players_data"}), 500

    pid = int(p["id"])
    add_player(user_id, pid, 1)
    add_xp(user_id, 15, "Opened pack")
    return jsonify({"ok": True, "player": p})

# =========================
# Market
# =========================
@app.get("/api/market/list")
def api_market_list():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, seller_id, player_id, price, status, created_at
        FROM market_listings
        WHERE status='active'
        ORDER BY id DESC
        LIMIT 50
    """)
    rows = cur.fetchall()
    conn.close()

    items = []
    for r in rows:
        p = PLAYERS_BY_ID.get(int(r["player_id"]))
        if p:
            items.append({**dict(r), "player": p})
    return jsonify({"ok": True, "items": items})

@app.post("/api/market/sell")
def api_market_sell():
    data = request.get_json(silent=True) or {}
    user_id = int(data.get("user_id", 0))
    player_id = int(data.get("player_id", 0))
    price = int(data.get("price", 0))

    if not user_id or player_id <= 0 or price <= 0:
        return jsonify({"ok": False, "error": "bad_params"}), 400
    if player_id not in PLAYERS_BY_ID:
        return jsonify({"ok": False, "error": "unknown_player"}), 400

    ensure_user(user_id)

    if not remove_player(user_id, player_id, 1):
        return jsonify({"ok": False, "error": "not_owned"}), 400

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO market_listings(seller_id, player_id, price, status)
        VALUES(?,?,?, 'active')
    """, (user_id, player_id, price))
    conn.commit()
    lid = cur.lastrowid
    conn.close()

    add_xp(user_id, 5, "Listed on market")
    return jsonify({"ok": True, "listing_id": lid})

@app.post("/api/market/buy")
def api_market_buy():
    data = request.get_json(silent=True) or {}
    buyer_id = int(data.get("user_id", 0))
    listing_id = int(data.get("listing_id", 0))
    if not buyer_id or not listing_id:
        return jsonify({"ok": False, "error": "bad_params"}), 400

    ensure_user(buyer_id)

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM market_listings WHERE id=?", (listing_id,))
    r = cur.fetchone()
    if not r:
        conn.close()
        return jsonify({"ok": False, "error": "not_found"}), 404
    if r["status"] != "active":
        conn.close()
        return jsonify({"ok": False, "error": "not_active"}), 400
    if int(r["seller_id"]) == buyer_id:
        conn.close()
        return jsonify({"ok": False, "error": "self_buy"}), 400

    price = int(r["price"])
    seller_id = int(r["seller_id"])
    player_id = int(r["player_id"])
    conn.close()

    if not take_coins(buyer_id, price, kind="market_buy", note=f"Listing {listing_id}"):
        return jsonify({"ok": False, "error": "not_enough_coins"}), 400

    add_coins(seller_id, price, kind="market_sell", note=f"Listing {listing_id}")
    add_player(buyer_id, player_id, 1)

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE market_listings SET status='sold', sold_at=strftime('%s','now') WHERE id=?", (listing_id,))
    conn.commit()
    conn.close()

    add_xp(buyer_id, 8, "Bought on market")
    return jsonify({"ok": True})

# =========================
# Match (simple)
# =========================
@app.post("/api/match/play")
def api_match_play():
    data = request.get_json(silent=True) or {}
    user_id = int(data.get("user_id", 0))
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400
    ensure_user(user_id)

    my = squad_rating(user_id)
    opp = random.randint(55, 90)
    chance = max(0.1, min(0.9, 0.5 + (my - opp) / 100.0))
    win = random.random() < chance

    reward = 120 if win else 60
    if is_vip(user_id):
        reward = int(reward * VIP_REWARD_BONUS)

    add_coins(user_id, reward, kind="match", note=f"{'WIN' if win else 'LOSE'} my{my} vs {opp}")
    add_xp(user_id, 10, "Played match")

    return jsonify({"ok": True, "win": win, "my": my, "opp": opp, "reward": reward})

# =========================
# Stars invoice
# =========================
@app.post("/api/create_invoice")
def api_create_invoice():
    data = request.get_json(silent=True) or {}
    user_id = int(data.get("user_id", 0))
    product = (data.get("product") or "").strip()
    if not user_id or not product:
        return jsonify({"ok": False, "error": "bad_params"}), 400
    item = CATALOG.get(product)
    if not item:
        return jsonify({"ok": False, "error": "unknown_product"}), 400

    payload = f"{product}:{user_id}:{int(time.time())}"

    invoice = {
        "title": item["title"],
        "description": item["desc"],
        "payload": payload,
        "currency": "XTR",
        "prices": [{"label": item["title"], "amount": item["stars"]}],
        "provider_token": ""
    }

    # subscription
    if product == "sub_vip":
        invoice["subscription_period"] = 2592000  # 30 days

    res = tg("createInvoiceLink", invoice)
    if not res.get("ok"):
        return jsonify({"ok": False, "error": "tg_error", "detail": res}), 400
    return jsonify({"ok": True, "url": res["result"]})

# =========================
# P2P: player <-> coins (escrow)
# =========================
@app.post("/api/p2p_player/create")
def api_p2p_player_create():
    data = request.get_json(silent=True) or {}
    seller_id = int(data.get("seller_id", 0))
    buyer_id = int(data.get("buyer_id", 0))
    player_id = int(data.get("player_id", 0))
    price = int(data.get("price", 0))

    if not seller_id or not buyer_id or seller_id == buyer_id:
        return jsonify({"ok": False, "error": "bad_users"}), 400
    if player_id <= 0 or price <= 0:
        return jsonify({"ok": False, "error": "bad_params"}), 400
    if player_id not in PLAYERS_BY_ID:
        return jsonify({"ok": False, "error": "unknown_player"}), 400

    ensure_user(seller_id)
    ensure_user(buyer_id)

    # lock 1 player from seller
    if not remove_player(seller_id, player_id, 1):
        return jsonify({"ok": False, "error": "seller_not_owned"}), 400

    fee = max(1, int(price * P2P_PLAYER_FEE_PCT / 100))

    conn = db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO p2p_player_trades(seller_id, buyer_id, player_id, price, fee, status)
        VALUES(?,?,?,?,?,'pending')
    """, (seller_id, buyer_id, player_id, price, fee))
    conn.commit()
    trade_id = cur.lastrowid
    conn.close()

    log_tx(seller_id, "p2p_player_lock", 0, f"Trade {trade_id}: locked player {player_id}")
    return jsonify({"ok": True, "trade_id": trade_id, "fee": fee})

@app.post("/api/p2p_player/accept")
def api_p2p_player_accept():
    data = request.get_json(silent=True) or {}
    trade_id = int(data.get("trade_id", 0))
    user_id = int(data.get("user_id", 0))  # buyer

    if not trade_id or not user_id:
        return jsonify({"ok": False, "error": "bad_params"}), 400

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM p2p_player_trades WHERE id=?", (trade_id,))
    t = cur.fetchone()
    conn.close()

    if not t:
        return jsonify({"ok": False, "error": "not_found"}), 404
    if t["status"] != "pending":
        return jsonify({"ok": False, "error": "not_pending"}), 400
    if int(t["buyer_id"]) != user_id:
        return jsonify({"ok": False, "error": "not_buyer"}), 403

    seller_id = int(t["seller_id"])
    buyer_id = int(t["buyer_id"])
    player_id = int(t["player_id"])
    price = int(t["price"])
    fee = int(t["fee"])
    total = price + fee

    if not take_coins(buyer_id, total, kind="p2p_player_pay", note=f"Trade {trade_id}: {price}+fee{fee}"):
        return jsonify({"ok": False, "error": "not_enough_coins", "need": total}), 400

    add_coins(seller_id, price, kind="p2p_player_receive_coins", note=f"Trade {trade_id}")
    add_player(buyer_id, player_id, 1)

    conn = db()
    cur = conn.cursor()
    cur.execute("UPDATE p2p_player_trades SET status='accepted', accepted_at=strftime('%s','now') WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()

    add_xp(buyer_id, 10, "P2P trade buy")
    add_xp(seller_id, 6, "P2P trade sell")
    return jsonify({"ok": True})

@app.post("/api/p2p_player/cancel")
def api_p2p_player_cancel():
    data = request.get_json(silent=True) or {}
    trade_id = int(data.get("trade_id", 0))
    user_id = int(data.get("user_id", 0))  # seller

    if not trade_id or not user_id:
        return jsonify({"ok": False, "error": "bad_params"}), 400

    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM p2p_player_trades WHERE id=?", (trade_id,))
    t = cur.fetchone()
    if not t:
        conn.close()
        return jsonify({"ok": False, "error": "not_found"}), 404
    if t["status"] != "pending":
        conn.close()
        return jsonify({"ok": False, "error": "not_pending"}), 400
    if int(t["seller_id"]) != user_id:
        conn.close()
        return jsonify({"ok": False, "error": "not_seller"}), 403

    seller_id = int(t["seller_id"])
    player_id = int(t["player_id"])

    add_player(seller_id, player_id, 1)
    cur.execute("UPDATE p2p_player_trades SET status='canceled' WHERE id=?", (trade_id,))
    conn.commit()
    conn.close()

    log_tx(seller_id, "p2p_player_refund", 0, f"Trade {trade_id}: refunded player {player_id}")
    return jsonify({"ok": True})

@app.get("/api/p2p_player/list")
def api_p2p_player_list():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400

    conn = db()
    cur = conn.cursor()
    cur.execute("""
      SELECT id, seller_id, buyer_id, player_id, price, fee, status, created_at, accepted_at
      FROM p2p_player_trades
      WHERE seller_id=? OR buyer_id=?
      ORDER BY id DESC
      LIMIT 50
    """, (user_id, user_id))
    rows = cur.fetchall()
    conn.close()

    items = []
    for r in rows:
        p = PLAYERS_BY_ID.get(int(r["player_id"]))
        items.append({**dict(r), "player": p})
    return jsonify({"ok": True, "items": items})

# =========================
# TX / Level / VIP endpoints
# =========================
@app.get("/api/tx")
def api_tx():
    user_id = request.args.get("user_id", type=int)
    limit = request.args.get("limit", default=50, type=int)
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400
    limit = max(10, min(limit, 200))
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT kind, delta, note, created_at FROM tx_log WHERE user_id=? ORDER BY id DESC LIMIT ?",
                (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return jsonify({"ok": True, "items": [dict(r) for r in rows]})

@app.get("/api/level")
def api_level():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400
    ensure_level_row(user_id)
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT xp, level FROM user_level WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    lvl = int(row["level"])
    return jsonify({"ok": True, "level": lvl, "xp": int(row["xp"]), "need": xp_needed(lvl)})

@app.get("/api/vip")
def api_vip():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"ok": False, "error": "user_id required"}), 400
    conn = db()
    cur = conn.cursor()
    cur.execute("SELECT vip_until FROM vip WHERE user_id=?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return jsonify({"ok": True, "vip": (int(row["vip_until"]) > int(time.time())) if row else False,
                    "vip_until": int(row["vip_until"]) if row else 0})

# Run locally:
# flask --app server run --debug
