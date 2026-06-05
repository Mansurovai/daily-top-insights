import os
import json
import requests
from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

client = genai.Client(api_key=GEMINI_API_KEY)

SUBSCRIBERS_FILE = "subscribers.json"


def load_json(filename, default):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default


def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def update_subscribers():
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    response = requests.get(url, timeout=30).json()

    subscribers = load_json(SUBSCRIBERS_FILE, [])

    for item in response.get("result", []):
        message = item.get("message", {})
        chat = message.get("chat", {})
        chat_id = chat.get("id")

        if chat_id and str(chat_id) not in subscribers:
            subscribers.append(str(chat_id))

    save_json(SUBSCRIBERS_FILE, subscribers)
    return subscribers


def create_brief():
    sources = load_json("sources.json", {})

    prompt = f"""
You are my daily intelligence agent.

Use Google Search to find fresh news from the last 24-72 hours.

Create a daily report in Uzbek language.

Focus on:
- global economy
- UAE and GCC economy
- Dubai real estate
- investment and passive income
- sales psychology

Topics:
{sources.get("topics", [])}

Format:

🌅 Daily Intelligence Brief

🌍 Global Economy
🇦🇪 UAE / GCC
🏙 Dubai Real Estate
💰 Investment Insight
📚 Sales Insight
🎯 Broker uchun bugungi 3 ta gap

Include source names or links where possible.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )

    return response.text


def send_message(chat_id, text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": text
        },
        timeout=30
    )


def main():
    subscribers = update_subscribers()
    brief = create_brief()

    for chat_id in subscribers:
        send_message(chat_id, brief)

    print(f"Sent to {len(subscribers)} subscribers")


if __name__ == "__main__":
    main()
