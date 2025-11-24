import requests
import json
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters

BOT_TOKEN = "8504549391:AAGc96vx_H6NPiCDBKEOkgpNPu930B7OviI"
OWM_API_KEY = "e4647864c6cf2bf55cab616b4e8a601a"
GEMINI_API_KEY = "AIzaSyBYSL28lgPgGHUwp-3I4Bcdz1SbDcuLVEQ"

POPULAR_CITIES = ["Astana", "Almaty", "Shymkent", "Aktau"]
active_chats = {}
timers = {}

def geocode_city(query: str):
    try:
        url = "http://api.openweathermap.org/geo/1.0/direct"
        params = {"q": query.strip(), "limit": 1, "appid": OWM_API_KEY}
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        if not data: return None
        item = data[0]
        return {"name": item.get("name"), "lat": item.get("lat"), "lon": item.get("lon"), "country": item.get("country")}
    except:
        return None

def weather_by_coords(lat: float, lon: float):
    try:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {"lat": lat, "lon": lon, "appid": OWM_API_KEY, "units": "metric", "lang": "ru"}
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        d = resp.json()
        if d.get("cod") != 200 and d.get("cod") != "200": return None
        name = d.get("name") or ""
        country = d.get("sys", {}).get("country", "")
        temp = d["main"]["temp"]
        desc = d["weather"][0]["description"]
        wind = d["wind"]["speed"]
        feels = d["main"].get("feels_like")
        res = f"Погода в {name}{(', ' + country) if country else ''}:\n🌡 Температура: {temp}°C"
        if feels is not None: res += f" (ощущается как {feels}°C)"
        res += f"\n🌥 {desc}\n💨 Ветер: {wind} м/с"
        return res
    except:
        return None

def ask_gemini(prompt: str) -> str:
    if not GEMINI_API_KEY or "YOUR" in GEMINI_API_KEY: return "Ошибка AI: нет ключа GEMINI_API_KEY."
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": GEMINI_API_KEY}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=8)
        r.raise_for_status()
        data = r.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as e:
        return f"Ошибка AI при запросе: {e}"

def clean_ai_response(raw: str) -> str:
    if not raw: return raw
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    s = re.sub(r"^`", "", s)
    s = re.sub(r"`$", "", s)
    s = s.strip()
    return s

def try_parse_json_from_text(text: str):
    t = clean_ai_response(text)
    try:
        return json.loads(t)
    except:
        first = t.find("{")
        last = t.rfind("}")
        if first != -1 and last != -1 and last > first:
            snippet = t[first:last+1]
            try:
                return json.loads(snippet)
            except:
                return None
        return None

def ai_assistant_decision(user_text: str):
    prompt = f"""
Ты ассистент Telegram-бота. У тебя есть инструмент get_weather(city).
Если пользователь хочет погоду — верни JSON: {{ "action": "weather", "city": "<город>" }}.
Иначе — верни JSON: {{ "action": "reply", "text": "<ответ>" }}.
Ответь ТОЛЬКО JSON (можно в одну строку). Текст пользователя: "{user_text}"
""".strip()
    raw = ask_gemini(prompt).strip()
    parsed = try_parse_json_from_text(raw)
    if isinstance(parsed, dict):
        return parsed
    return {"action": "reply", "text": raw}

def get_keyboard():
    keyboard = [[InlineKeyboardButton(city, callback_data=city)] for city in POPULAR_CITIES]
    return InlineKeyboardMarkup(keyboard)

async def start_goodbye_timer(update: Update, chat_id):
    if chat_id in timers:
        timers[chat_id].cancel()
    timers[chat_id] = asyncio.create_task(goodbye_task(update, chat_id))

async def goodbye_task(update: Update, chat_id):
    await asyncio.sleep(35)
    if active_chats.get(chat_id):
        await update.message.reply_text("👋 Хорошего дня! До свидания!")
        active_chats[chat_id] = False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    active_chats[chat_id] = True
    ai_intro = ask_gemini("Кратко представься как помощник: скажи, что можешь показать погоду и с тобой можно пообщаться.")
    await update.message.reply_text(f"{ai_intro}\nВыбери популярный город или напиши свой, я пойму о каком городе вы говорите:", reply_markup=get_keyboard())

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not active_chats.get(chat_id, False):
        await update.message.reply_text("Напишите /start, чтобы начать диалог со мной.")
        return
    user_text = update.message.text.strip()
    geo = geocode_city(user_text)
    if geo:
        weather = weather_by_coords(geo["lat"], geo["lon"])
        if weather:
            await update.message.reply_text(weather)
            await start_goodbye_timer(update, chat_id)
            return
    decision = ai_assistant_decision(user_text)
    action = (decision.get("action") or "").lower()
    if action == "weather":
        city = decision.get("city") or ""
        geo = geocode_city(city)
        if not geo:
            geo = geocode_city(user_text)
        if geo:
            weather = weather_by_coords(geo["lat"], geo["lon"])
            if weather:
                await update.message.reply_text(weather)
                await start_goodbye_timer(update, chat_id)
                return
            else:
                await update.message.reply_text(f"Не удалось получить погоду для «{city}».")
                await start_goodbye_timer(update, chat_id)
                return
        else:
            await update.message.reply_text(f"Не удалось найти город: «{city}». Попробуй написать по-другому.")
            await start_goodbye_timer(update, chat_id)
            return
    reply_text = decision.get("text") or "Извини, я не понял."
    await update.message.reply_text(reply_text)
    await start_goodbye_timer(update, chat_id)

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    city = query.data
    geo = geocode_city(city)
    if geo:
        weather = weather_by_coords(geo["lat"], geo["lon"])
        if weather:
            await query.edit_message_text(weather)
            chat_id = query.message.chat.id
            class DummyUpdate:
                effective_chat = query.message.chat
                message = query.message
            await start_goodbye_timer(DummyUpdate(), chat_id)
            return
    await query.edit_message_text(f"Не удалось получить погоду для {city}.")

app = ApplicationBuilder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
app.add_handler(CallbackQueryHandler(button))

print("Бот запущен…")
app.run_polling()
