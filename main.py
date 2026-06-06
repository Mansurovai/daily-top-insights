import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import requests
from google import genai
from google.genai import types


GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent")
SEND_HOUR = int(os.getenv("SEND_HOUR", "7"))
SEND_MINUTE = int(os.getenv("SEND_MINUTE", "0"))
POLL_INTERVAL_SECONDS = int(os.getenv("POLL_INTERVAL_SECONDS", "2"))
DATABASE_PATH = os.getenv("DATABASE_PATH", "bot.db")
SOURCES_FILE = os.getenv("SOURCES_FILE", "sources.json")
LEGACY_SUBSCRIBERS_FILE = os.getenv("LEGACY_SUBSCRIBERS_FILE", "subscribers.json")

TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

client = genai.Client(api_key=GEMINI_API_KEY)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


WELCOME_TEXT = """Assalomu alaykum!

Daily Top Insights botiga xush kelibsiz.

Har kuni ertalab 07:00 da sizga:
- Global economy
- UAE va GCC
- Dubai real estate
- Investment va passive income
- Sales insight
- Podcast va expert insight

bo'yicha qisqa, amaliy intelligence brief yuboriladi.

O'zingiz kuzatmoqchi bo'lgan mavzu, sayt yoki odam nomini shu yerga yozing. U faqat sizning profilingizga qo'shiladi."""


HELP_TEXT = """Buyruqlar:

/start - botga obuna bo'lish
/help - yordam
/my_sources - siz kiritgan mavzu, sayt va odamlar
/clear_sources - siz kiritgan shaxsiy manbalarni tozalash
/brief - hozir shaxsiy brief olish

Oddiy matn yuborsangiz, u faqat sizning shaxsiy manbalaringizga qo'shiladi. Boshqa userlarga yuborilmaydi."""


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with connect_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                chat_id TEXT PRIMARY KEY,
                first_name TEXT,
                username TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_daily_sent_date TEXT
            )
            """
        )
    migrate_legacy_subscribers()


def migrate_legacy_subscribers() -> None:
    if not os.path.exists(LEGACY_SUBSCRIBERS_FILE):
        return

    try:
        with open(LEGACY_SUBSCRIBERS_FILE, "r", encoding="utf-8") as file:
            subscribers = json.load(file)
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not read legacy subscribers file: %s", LEGACY_SUBSCRIBERS_FILE)
        return

    if not isinstance(subscribers, list):
        logger.warning("Legacy subscribers file must contain a JSON list.")
        return

    current_time = now_iso()
    migrated_count = 0
    with connect_db() as conn:
        for chat_id in subscribers:
            chat_id = str(chat_id).strip()
            if not chat_id:
                continue
            conn.execute(
                """
                INSERT INTO users (chat_id, first_name, username, is_active, created_at, updated_at)
                VALUES (?, '', '', 1, ?, ?)
                ON CONFLICT(chat_id) DO UPDATE SET
                    is_active = 1,
                    updated_at = excluded.updated_at
                """,
                (chat_id, current_time, current_time),
            )
            migrated_count += 1

    if migrated_count:
        logger.info("Migrated %s legacy subscribers into SQLite.", migrated_count)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                value TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (chat_id) REFERENCES users(chat_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )


def now_iso() -> str:
    return datetime.now(ZoneInfo(TIMEZONE)).isoformat(timespec="seconds")


def load_sources() -> dict[str, Any]:
    if not os.path.exists(SOURCES_FILE):
        return {
            "topics": [
                "global economy",
                "UAE economy",
                "GCC investments",
                "Dubai real estate",
                "US stock market",
                "investment psychology",
                "sales psychology",
            ],
            "sites": [],
            "people": [],
            "youtube_channels": [],
            "podcasts": [],
            "books": [],
        }

    with open(SOURCES_FILE, "r", encoding="utf-8") as file:
        return json.load(file)


def get_state(key: str, default: str = "") -> str:
    with connect_db() as conn:
        row = conn.execute("SELECT value FROM bot_state WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO bot_state (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def upsert_user(chat: dict[str, Any]) -> bool:
    chat_id = str(chat["id"])
    first_name = chat.get("first_name", "")
    username = chat.get("username", "")
    current_time = now_iso()

    with connect_db() as conn:
        existing = conn.execute(
            "SELECT chat_id FROM users WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO users (chat_id, first_name, username, is_active, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                first_name = excluded.first_name,
                username = excluded.username,
                is_active = 1,
                updated_at = excluded.updated_at
            """,
            (chat_id, first_name, username, current_time, current_time),
        )
        return existing is None


def add_user_source(chat_id: str, value: str) -> None:
    clean_value = value.strip()
    if not clean_value:
        return

    with connect_db() as conn:
        conn.execute(
            """
            INSERT INTO user_sources (chat_id, value, created_at)
            VALUES (?, ?, ?)
            """,
            (chat_id, clean_value, now_iso()),
        )


def get_user_sources(chat_id: str) -> list[str]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT value FROM user_sources
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT 50
            """,
            (chat_id,),
        ).fetchall()
        return [row["value"] for row in rows]


def clear_user_sources(chat_id: str) -> None:
    with connect_db() as conn:
        conn.execute("DELETE FROM user_sources WHERE chat_id = ?", (chat_id,))


def get_active_users() -> list[str]:
    with connect_db() as conn:
        rows = conn.execute(
            "SELECT chat_id FROM users WHERE is_active = 1 ORDER BY created_at"
        ).fetchall()
        return [row["chat_id"] for row in rows]


def mark_daily_sent(chat_id: str, date_value: str) -> None:
    with connect_db() as conn:
        conn.execute(
            """
            UPDATE users
            SET last_daily_sent_date = ?, updated_at = ?
            WHERE chat_id = ?
            """,
            (date_value, now_iso(), chat_id),
        )


def was_daily_sent(chat_id: str, date_value: str) -> bool:
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT last_daily_sent_date FROM users
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
        return bool(row and row["last_daily_sent_date"] == date_value)


def telegram_request(method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.post(
        f"{TELEGRAM_API_URL}/{method}",
        json=payload or {},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data


def send_message(chat_id: str, text: str) -> None:
    max_length = 3900
    parts = [text[i : i + max_length] for i in range(0, len(text), max_length)]

    for part in parts:
        telegram_request(
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": part,
                "disable_web_page_preview": True,
            },
        )


def create_brief(user_sources: list[str] | None = None) -> str:
    sources = load_sources()
    user_sources = user_sources or []

    prompt = f"""
You are a daily intelligence agent for a Dubai real estate broker.

Use Google Search to find fresh, useful information from the last 24-72 hours.
Write in Uzbek language with clear, practical, business-focused wording.

Main focus:
- Dubai real estate market news, transactions, prices, supply, demand, launches, rents, regulations, and developer activity
- Dubai, UAE, and GCC government news that can affect investors, residency, business, tourism, capital flows, and real estate demand
- global macro changes that can affect Dubai property: interest rates, inflation, oil, currencies, geopolitics, migration, and investor sentiment
- US stock market and major company/economic news when it can affect global investor mood or liquidity
- investment, trading, sales, and negotiation insights from respected experts, podcasts, interviews, books, and research
- investment and passive income
- investor psychology
- sales psychology
- YouTube podcasts, interviews, and expert talks

Global topics:
{sources.get("topics", [])}

Preferred websites:
{sources.get("sites", [])}

People or experts to follow:
{sources.get("people", [])}

YouTube channels:
{sources.get("youtube_channels", [])}

Podcasts:
{sources.get("podcasts", [])}

Books and authors:
{sources.get("books", [])}

This user's personal interests, sites, people, or notes:
{user_sources}

Rules:
- Think like a Dubai real estate broker who wants to be among the first to know important market changes.
- Prioritize news that can help the broker advise investors before competitors do.
- Separate hard market news from opinion.
- Explain why each item matters for Dubai real estate or investor conversations.
- Prioritize practical insights useful for talking to investors.
- Do not summarize entertainment content.
- Include source names or links where possible.
- If information is uncertain, say it carefully.
- Keep it concise but valuable.

Format:

Daily Intelligence Brief

1. Bugungi 5 ta eng muhim yangilik
- Each item must include: what happened, why it matters for Dubai real estate, and the source.
- Prioritize Dubai real estate first, then UAE/GCC government or economy, then global macro or US stock market if relevant.

2. Investorlar uchun 3 ta insight
- Use investment experts, podcasts, books, and market data.
- Make each insight useful for a broker conversation.

3. Bugun content uchun 3 ta g'oya
- Short ideas for Instagram, Telegram, LinkedIn, or YouTube Shorts.
- Make them practical for a Dubai real estate broker.

4. Bugun mijozga aytishga arziydigan 1 ta fakt
- One specific, memorable, source-backed fact.

Sources
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        ),
    )

    return response.text or "Bugungi brief yaratilmadi. Keyinroq qayta urinib ko'ring."


def handle_command(chat_id: str, text: str) -> None:
    if text.startswith("/start"):
        send_message(chat_id, WELCOME_TEXT)
        return

    if text.startswith("/help"):
        send_message(chat_id, HELP_TEXT)
        return

    if text.startswith("/my_sources"):
        values = get_user_sources(chat_id)
        if not values:
            send_message(chat_id, "Siz hali shaxsiy mavzu, sayt yoki odam kiritmagansiz.")
            return
        send_message(chat_id, "Sizning shaxsiy manbalaringiz:\n\n" + "\n".join(f"- {item}" for item in values))
        return

    if text.startswith("/clear_sources"):
        clear_user_sources(chat_id)
        send_message(chat_id, "Shaxsiy manbalaringiz tozalandi.")
        return

    if text.startswith("/brief"):
        send_message(chat_id, "Brief tayyorlanyapti. Bu 20-60 soniya vaqt olishi mumkin.")
        brief = create_brief(get_user_sources(chat_id))
        send_message(chat_id, brief)
        return

    send_message(chat_id, HELP_TEXT)


def handle_text(chat_id: str, text: str) -> None:
    add_user_source(chat_id, text)
    send_message(
        chat_id,
        "Qabul qilindi. Bu matn faqat sizning shaxsiy manbalaringizga qo'shildi va boshqa userlarga yuborilmaydi.",
    )


def handle_update(update: dict[str, Any]) -> None:
    message = update.get("message") or update.get("edited_message")
    if not message:
        return

    chat = message.get("chat")
    text = (message.get("text") or "").strip()
    if not chat or not text:
        return

    chat_id = str(chat["id"])
    is_new_user = upsert_user(chat)

    if is_new_user and not text.startswith("/start"):
        send_message(chat_id, WELCOME_TEXT)

    if text.startswith("/"):
        handle_command(chat_id, text)
    else:
        handle_text(chat_id, text)


def poll_updates_once() -> None:
    offset = int(get_state("telegram_update_offset", "0") or "0")
    data = telegram_request(
        "getUpdates",
        {
            "offset": offset,
            "timeout": 25,
            "allowed_updates": ["message", "edited_message"],
        },
    )

    for update in data.get("result", []):
        update_id = update["update_id"]
        try:
            handle_update(update)
        except Exception:
            logger.exception("Failed to handle update %s", update_id)
        finally:
            offset = max(offset, update_id + 1)
            set_state("telegram_update_offset", str(offset))


def should_send_daily_now() -> bool:
    current_time = datetime.now(ZoneInfo(TIMEZONE))
    send_time = current_time.replace(hour=SEND_HOUR, minute=SEND_MINUTE, second=0, microsecond=0)
    return send_time <= current_time < send_time + timedelta(minutes=5)


def send_daily_briefs() -> None:
    today = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    users = get_active_users()

    for chat_id in users:
        if was_daily_sent(chat_id, today):
            continue

        try:
            brief = create_brief(get_user_sources(chat_id))
            send_message(chat_id, brief)
            mark_daily_sent(chat_id, today)
            logger.info("Daily brief sent to %s", chat_id)
            time.sleep(1)
        except Exception:
            logger.exception("Failed to send daily brief to %s", chat_id)


def run_bot() -> None:
    init_db()
    logger.info("Bot started. Daily send time: %02d:%02d %s", SEND_HOUR, SEND_MINUTE, TIMEZONE)

    while True:
        try:
            poll_updates_once()
            if should_send_daily_now():
                send_daily_briefs()
        except Exception:
            logger.exception("Bot loop failed")

        time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_bot()
