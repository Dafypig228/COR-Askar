import requests
import json
import asyncio
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, CallbackQueryHandler, filters

BOT_TOKEN = "8589947061:AAErdg9WHXlaEMzAloh27BnNjzaByFUJwuw"
OWM_API_KEY = "e4647864c6cf2bf55cab616b4e8a601a"
GEMINI_API_KEY = "AIzaSyA1vbHSjJoeYMlQHeJ7Ilg5sBpnmr1ioTA"

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
    prompt = f"""Ты — умный ассистент Telegram-бота. Ответь ОДНОЙ СТРОКОЙ и НИЧЕГО БОЛЬШЕ: 
Либо начни строку с `WEATHER:` и после двоеточия укажи город/топоним (на любом языке или транслитерации), 
либо начни строку с `REPLY:` и после двоеточия дай развёрнутый информативный ответ (не повторяй вход).
Если явно про погоду (слова "погода", "сколько градусов", "хочу погоду", "дай погоду", просто название города) — используй WEATHER.
Если это вопрос, тема или название страны без запроса погоды — используй REPLY и дай полезную справку.
Примеры:
Астана -> WEATHER: Astana
хочу погоду в алматы -> WEATHER: Almaty
почему небо синее? -> REPLY: Небо кажется синим потому что...
Кыргызстан -> REPLY: Кыргызстан — страна в Центральной Азии...
Текст пользователя: "{user_text}"
""".strip()

    raw = ask_gemini(prompt).strip()
    cleaned = clean_ai_response(raw)
    if not cleaned:
        return {"action": "reply", "text": "Извини, не смог получить ответ от AI."}

    up = cleaned.strip()
    if up.upper().startswith("WEATHER:"):
        city = up[len("WEATHER:"):].strip()
        if not city:
            return {"action": "reply", "text": "ИИ сказал, что хочет показать погоду, но не указал город."}
        return {"action": "weather", "city": city}
    if up.upper().startswith("REPLY:"):
        text = up[len("REPLY:"):].strip()
        if not text:
            return {"action": "reply", "text": "Извини, ИИ вернул пустой ответ."}
        return {"action": "reply", "text": text}

    # fallback: если LLM случайно ответил без префикса, попытаемся догадаться
    lower = up.lower()
    if "погод" in lower or "градус" in lower or "сколько" in lower and "град" in lower:
        return {"action": "weather", "city": up}
    return {"action": "reply", "text": up}

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
    # Сначала просим LLM решить — WEATHER или REPLY
    decision = ai_assistant_decision(user_text)
    action = (decision.get("action") or "").lower()

    if action == "weather":
        city = decision.get("city") or user_text
        geo = geocode_city(city)
        if not geo:
            # попробуем геокодить исходный текст как fallback
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
            await update.message.reply_text(f"Не удалось найти город: «{city}». Попробуйте написать по-другому.")
            await start_goodbye_timer(update, chat_id)
            return

    # action == reply
    reply_text = decision.get("text") or ""
    # если ИИ вернул ровно вход — попросим ИИ дать развёрнутый ответ, но только один раз
    if reply_text.strip() and reply_text.strip().lower() == user_text.strip().lower():
        retry_prompt = f"Пользователь: \"{user_text}\". Не повторяй вход. Дай развёрнутый полезный ответ в одну-две короткие абзацы."
        raw2 = ask_gemini(retry_prompt).strip()
        cleaned2 = clean_ai_response(raw2)
        if cleaned2 and cleaned2.strip().lower() != user_text.strip().lower():
            reply_text = cleaned2

    if not reply_text:
        reply_text = "Извини, я не понял. Попробуй переформулировать."

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
