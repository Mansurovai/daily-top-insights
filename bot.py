import os
import json
from datetime import time
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from google import genai
from google.genai import types


GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

SUBSCRIBERS_FILE = "subscribers.json"

client = genai.Client(api_key=GEMINI_API_KEY)


WELCOME_TEXT = """👋 Assalomu alaykum!

Daily Top Insights ga xush kelibsiz.

Har kuni sizga quyidagi yo'nalishlar bo'yicha eng muhim va foydali ma'lumotlar yuboriladi:

🌍 Global Economy
🇦🇪 UAE & GCC
🏙 Dubai Real Estate
💰 Investment & Passive Income
📚 Sales Insights
🎙 Podcast & Expert Insights

Maqsad: iqtisodiyot, investitsiya va ko'chmas mulk bo'yicha muhim o'zgarishlarni tez, qisqa va amaliy ko'rinishda yetkazish.

📩 Birinchi Daily Brief hozir yuboriladi."""
