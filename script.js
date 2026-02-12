let user_id = 1;
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    user_id = tg.initDataUnsafe?.user?.id || 1;
}

const els = {
    coins: document.getElementById("coins"),
    cardsCount: document.getElementById("cards-count"),
    cardArea: document.getElementById("card-area"),
    marketArea: document.getElementById("market-area"),
    toast: document.getElementById("toast"),
};

function showToast(text) {
    els.toast.textContent = text;
    els.toast.classList.add("show");
    setTimeout(() => els.toast.classList.remove("show"), 2200);
}

const FALLBACK_PLAYER_IMAGE = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='96' height='96' viewBox='0 0 96 96'%3E%3Crect width='96' height='96' rx='16' fill='%231e293b'/%3E%3Ctext x='50%25' y='56%25' dominant-baseline='middle' text-anchor='middle' font-size='36'%3E%E2%9A%BD%3C/text%3E%3C/svg%3E";

function renderCard(p, withBuy = false) {
    return `<div class="player-card ${p.rarity}">
        <h3>${p.name}</h3>
        <img src="/web/images/players/${p.image}" class="player-image" alt="${p.name}" onerror="this.onerror=null;this.src=FALLBACK_PLAYER_IMAGE;">
        <p class="meta">${p.position}</p>
        <p>ATT:${p.attack} DEF:${p.defense} SPD:${p.speed}</p>
        ${withBuy ? `<p>💰 ${p.price}</p><button class="small primary" onclick="buy(${p.id})">Купить</button>` : ""}
    </div>`;
}

async function loadProfile() {
    const r = await fetch(`/profile?user_id=${user_id}`);
    const d = await r.json();
    if (!d.ok) return;
    els.coins.textContent = d.profile.coins;
    els.cardsCount.textContent = d.profile.cards_count;
}

async function loadMyPlayers() {
    const r = await fetch(`/my_players?user_id=${user_id}`);
    const d = await r.json();
    if (!d.ok) return;

    if (!d.players.length) {
        els.cardArea.innerHTML = '<div class="empty">Пока нет игроков. Открой пак 🎴</div>';
        return;
    }

    els.cardArea.innerHTML = d.players.map((p) => renderCard(p)).join("");
}

async function loadMarket() {
    const r = await fetch("/market");
    const d = await r.json();
    if (!d.ok) return;

    if (!d.market.length) {
        els.marketArea.innerHTML = '<div class="empty">Рынок пуст</div>';
        return;
    }
    els.marketArea.innerHTML = d.market.map((item) => renderCard(item, true)).join("");
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
    showToast(`Получен игрок: ${d.player.name}`);
    await loadProfile();
    await loadMyPlayers();
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
        showToast(`🏆 Победа! +${d.reward} монет`);
    } else {
        showToast(`😢 Поражение (${d.your} vs ${d.enemy})`);
    }
    await loadProfile();
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
    if (!tg) {
        showToast("Открывай в Telegram");
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

loadProfile();
loadMyPlayers();
loadMarket();
