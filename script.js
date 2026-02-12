let user_id = 1;
if (window.Telegram.WebApp){
    Telegram.WebApp.expand();
    user_id = Telegram.WebApp.initDataUnsafe.user.id;
}

// -------------------- Daily --------------------
function daily(){
    fetch("/daily",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({user_id})
    }).then(r=>r.json()).then(d=>alert(d.message));
}

// -------------------- Open Pack --------------------
function openPack(){
    fetch("/open_pack",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({user_id})
    })
    .then(r=>r.json())
    .then(p=>{
        if(p.error){ alert(p.error); return; }
        document.getElementById("card-area").innerHTML = renderCard(p);
    });
}

// -------------------- Render Card --------------------
function renderCard(p){
    return `<div class="player-card ${p.rarity}">
        <h3>${p.name}</h3>
        <img src="/web/images/players/${p.image}" class="player-image">
        <p>${p.position}</p>
        <p>ATT:${p.attack} DEF:${p.defense} SPD:${p.speed}</p>
    </div>`;
}

// -------------------- PvP Match --------------------
function playMatch(){
    fetch("/match",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({user_id})
    }).then(r=>r.json())
    .then(d=>{
        if(d.error){ alert(d.error); return; }
        if(d.result==="win"){
            alert(`🏆 Победа!\nТвоя сила: ${d.your}\nСоперник: ${d.enemy}\nНаграда: ${d.reward} монет`);
        } else {
            alert(`😢 Поражение\nТвоя сила: ${d.your}\nСоперник: ${d.enemy}`);
        }
    });
}

// -------------------- Market --------------------
function loadMarket(){
    fetch("/market")
    .then(r=>r.json())
    .then(d=>{
        let html = "";
        d.market.forEach(item=>{
            html += `<div class="player-card ${item[6]}">
                <h3>${item[1]}</h3>
                <img src="/web/images/players/${item[7]}" class="player-image">
                <p>${item[2]}</p>
                <p>ATT:${item[3]} DEF:${item[4]} SPD:${item[5]}</p>
                <p>💰 ${item[8]}</p>
                <button onclick="buy(${item[0]})">Купить</button>
            </div>`;
        });
        document.getElementById("market-area").innerHTML = html;
    });
}

function buy(id){
    fetch("/buy_player",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({user_id, market_id:id})
    }).then(r=>r.json())
    .then(d=>alert(d.message || d.error));
}

// -------------------- Buy Coins (Telegram Payment) --------------------
function buyCoins(amount){
    if(!window.Telegram.WebApp) { alert("Открывай в Telegram"); return; }

    fetch("/buy_coins",{
        method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({user_id, amount})
    })
    .then(r=>r.json())
    .then(data=>{
        Telegram.WebApp.PaymentRequest.showInvoice(data)
        .then(result=>{
            if(result && result.status=="paid"){
                alert(`Оплата успешна! +${amount} монет`);
                fetch("/add_coins",{
                    method:"POST",
                    headers:{"Content-Type":"application/json"},
                    body:JSON.stringify({user_id, amount})
                });
            }
        });
    });
}
