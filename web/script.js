let user_id = 1;
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    user_id = tg.initDataUnsafe?.user?.id || 1;
}

const els = {
    coins: document.getElementById("coins"),
    cardsCount: document.getElementById("cards-count"),
    teamPower: document.getElementById("team-power"),
    rating: document.getElementById("rating"),
    cardArea: document.getElementById("card-area"),
    marketArea: document.getElementById("market-area"),
    leaderboard: document.getElementById("leaderboard"),
    toast: document.getElementById("toast"),
    dailyTimer: document.getElementById("daily-timer"),
    searchMy: document.getElementById("search-my"),
};

let lastDaily = 0;

function showToast(text) {
    els.toast.textContent = text;
    els.toast.classList.add("show");
    setTimeout(() => els.toast.classList.remove("show"), 2200);
}

const FALLBACK_PLAYER_IMAGE = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 96 96'%3E%3Crect width='96' height='96' rx='16' fill='%231e293b'/%3E%3Ctext x='50%25' y='56%25' dominant-baseline='middle' text-anchor='middle' font-size='36'%3E%E2%9A%BD%3C/text%3E%3C/svg%3E";

function fmtTime(seconds) {
    const h = Math.floor(seconds / 3600).toString().padStart(2, "0");
    const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, "0");
    const s = (seconds % 60).toString().padStart(2, "0");
    return `${h}:${m}:${s}`;
}

function renderCard(p, mode = "my") {
    const total = p.attack + p.defense + p.speed;
    const controls = mode === "market"
        ? `<p>💰 ${p.price}</p><button class="small primary" onclick="buy(${p.id})">Купить</button>`
        : `<button class="small" onclick="sellPrompt(${p.id})">Продать</button>`;

    return `<div class="player-card ${p.rarity || "common"}">
        <h3>${p.name}</h3>
        <img src="/web/images/players/${p.image}" class="player-image" alt="${p.name}" onerror="this.onerror=null;this.src='${FALLBACK_PLAYER_IMAGE}';">
        <p class="meta">${p.position}</p>
        <p>ATT:${p.attack} DEF:${p.defense} SPD:${p.speed}</p>
        <p class="meta">Сила: ${total}</p>
        ${controls}
    </div>`;
}

async function loadProfile() {
    const r = await fetch(`/profile?user_id=${user_id}`);
    const d = await r.json();
    if (!d.ok) return;
    els.coins.textContent = d.profile.coins;
    els.cardsCount.textContent = d.profile.cards_count;
    els.teamPower.textContent = d.profile.team_power;
    els.rating.textContent = d.profile.rating;
    lastDaily = d.profile.last_daily;
    renderDailyTimer();
}

function renderDailyTimer() {
    const diff = Math.floor(Date.now() / 1000) - lastDaily;
    const rem = 86400 - diff;
    els.dailyTimer.textContent = rem > 0 ? `Daily через: ${fmtTime(rem)}` : "Daily: готов";
}

async function loadMyPlayers() {
    const r = await fetch(`/my_players?user_id=${user_id}`);
    const d = await r.json();
    if (!d.ok) return;

    let players = d.players;
    const q = els.searchMy.value.trim().toLowerCase();
    if (q) {
        players = players.filter((p) => p.name.toLowerCase().includes(q) || p.position.toLowerCase().includes(q));
    }

    if (!players.length) {
        els.cardArea.innerHTML = '<div class="empty">Пока нет игроков. Открой пак 🎴</div>';
        return;
    }

    els.cardArea.innerHTML = players.map((p) => renderCard(p, "my")).join("");
}

async function loadMarket() {
    const r = await fetch("/market");
    const d = await r.json();
    if (!d.ok) return;

    if (!d.market.length) {
        els.marketArea.innerHTML = '<div class="empty">Рынок пуст</div>';
        return;
    }
    els.marketArea.innerHTML = d.market.map((item) => renderCard(item, "market")).join("");
}

async function loadLeaderboard() {
    const r = await fetch("/leaderboard");
    const d = await r.json();
    if (!d.ok) return;

    if (!d.leaders.length) {
        els.leaderboard.innerHTML = '<div class="empty">Лидерборд пока пуст</div>';
        return;
    }

    els.leaderboard.innerHTML = d.leaders
        .map((u, i) => `<div class="leader-row ${u.user_id === user_id ? "me" : ""}">
            <span>#${i + 1}</span>
            <span>ID ${u.user_id}</span>
            <span>🏆 ${u.rating}</span>
            <span>W/L ${u.wins}/${u.losses}</span>
            <span>💰 ${u.coins}</span>
        </div>`)
        .join("");
}

async function daily() {
    const r = await fetch("/daily", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id }),
    });
    const d = await r.json();
    showToast(d.message || d.error);
    await loadProfile();
}

async function openPack() {
    const r = await fetch("/open_pack", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id }),
    });
    const d = await r.json();
    if (!d.ok) {
        showToast(d.error);
        return;
    }
    showToast(`Получен игрок: ${d.player.name} (${d.player.rarity})`);
    await Promise.all([loadProfile(), loadMyPlayers()]);
}

async function playMatch() {
    const r = await fetch("/match", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id }),
    });
    const d = await r.json();
    if (!d.ok) {
        showToast(d.error);
        return;
    }
    if (d.result === "win") {
        showToast(`🏆 Победа! +${d.reward} монет (${d.your} vs ${d.enemy})`);
    } else {
        showToast(`😢 Поражение (${d.your} vs ${d.enemy})`);
    }
    await Promise.all([loadProfile(), loadLeaderboard()]);
}

async function sellPrompt(playerId) {
    const value = prompt("Введите цену продажи (минимум 100):", "300");
    if (!value) return;

    const price = Number(value);
    if (!Number.isFinite(price) || price < 100) {
        showToast("Введите корректную цену");
        return;
    }

    const r = await fetch("/sell_player", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id, player_id: playerId, price }),
    });
    const d = await r.json();
    showToast(d.message || d.error);
    if (d.ok) {
        await Promise.all([loadMarket(), loadMyPlayers()]);
    }
}

async function buy(id) {
    const r = await fetch("/buy_player", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id, market_id: id }),
    });
    const d = await r.json();
    showToast(d.message || d.error);
    if (d.ok) {
        await Promise.all([loadProfile(), loadMyPlayers(), loadMarket()]);
    }
}

async function buyCoins(amount) {
    if (!tg || !tg.PaymentRequest) {
        showToast("Покупка монет доступна только в Telegram");
        return;
    }

    const r = await fetch("/buy_coins", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id, amount }),
    });
    const d = await r.json();
    if (!d.ok) {
        showToast(d.error);
        return;
    }

    tg.PaymentRequest.showInvoice(d.invoice).then(async (result) => {
        if (result && result.status === "paid") {
            await fetch("/add_coins", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_id, amount }),
            });
            showToast(`Оплата успешна! +${amount} монет`);
            await loadProfile();
        }
    });
}

setInterval(renderDailyTimer, 1000);
loadProfile();
loadMyPlayers();
loadMarket();
loadLeaderboard();
