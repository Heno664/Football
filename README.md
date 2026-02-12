# Football Stars (Telegram Mini App)

Мини-игра про карточки футболистов: ежедневные награды, открытие паков, матчи и рынок.

## Запуск

```bash
pip install -r requirements.txt
python server.py
```

Приложение будет доступно на `http://localhost:5000/game` (и `http://localhost:5000/` автоматически откроет игру) и статика на `/web`.

## Переменные окружения

```bash
export BOT_TOKEN="<telegram bot token>"
export PROVIDER_TOKEN="<telegram payments provider token>"
export WEBAPP_URL="https://your-domain/web/index.html"
```

- `BOT_TOKEN` — нужен для webhook-ответов в Telegram.
- `PROVIDER_TOKEN` — нужен для Telegram Payments.
- `WEBAPP_URL` — ссылка, которую бот отправляет кнопкой «Играть».

## Что есть в приложении

- Профиль игрока (монеты + количество карт).
- Daily reward с ограничением 1 раз в сутки.
- Открытие паков за монеты.
- Матч с наградой за победу.
- Рынок (просмотр и покупка карт).
- Toast-уведомления и адаптивный интерфейс под Telegram Mini App.
