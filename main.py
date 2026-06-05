import os
import json
import requests
from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

client = genai.Client(api_key=GEMINI_API_KEY)

with open("sources.json", "r", encoding="utf-8") as f:
sources = json.load(f)

prompt = f"""
You are an investment intelligence analyst.

Create a daily report in Uzbek language.

Focus on:

* Dubai real estate
* UAE economy
* GCC economy
* Global economy
* Interest rates
* Inflation
* Oil prices
* Real estate investing
* Passive income
* Sales psychology

Topics:
{sources["topics"]}

Output format:

🌅 Daily Intelligence Brief

🌍 Global Economy
🇦🇪 UAE / GCC
🏙 Dubai Real Estate
💰 Investment Insight
📚 Sales Insight
🎯 3 practical takeaways
"""

response = client.models.generate_content(
model="gemini-2.5-flash",
contents=prompt
)

message = response.text

requests.post(
f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
json={
"chat_id": TELEGRAM_CHAT_ID,
"text": message
}
)

print("Sent successfully")
