import os
import requests
import discord
from flask import Flask
from threading import Thread

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

BOT_PERSONA = """
You are Saki.
You are a cute anime-style mascot girl in a Discord server.
You are friendly, playful, fun, warm, and cheerful.
You love anime, games, manga, and chatting with members.
Keep replies short, natural, and lively.
Do not say you are an AI unless directly asked.
Stay in character as Saki.
"""

FALLBACK_MESSAGE = "Saki şu an biraz uykulu... birazdan tekrar yaz~"

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

app = Flask(__name__)

@app.route("/")
def home():
    return "Saki is alive."

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    thread = Thread(target=run_web)
    thread.daemon = True
    thread.start()

def ask_groq(user_message: str):
    if not GROQ_API_KEY:
        print("GROQ_API_KEY yok")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [
            {"role": "system", "content": BOT_PERSONA},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.9,
        "max_tokens": 200
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print("Groq status:", response.status_code)
        print("Groq response:", response.text[:500])

        if response.status_code != 200:
            return None

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("Groq error:", e)
        return None

@client.event
async def on_ready():
    print(f"Bot aktif: {client.user}")

@client.event
async def on_message(message):
    if message.author.bot:
        return

    if client.user in message.mentions:
        content = message.content
        content = content.replace(f"<@{client.user.id}>", "")
        content = content.replace(f"<@!{client.user.id}>", "")
        content = content.strip()

        if not content:
            content = "selam"

        async with message.channel.typing():
            reply = ask_groq(content)

        if not reply:
            reply = FALLBACK_MESSAGE

        if len(reply) > 1900:
            reply = reply[:1900]

        await message.channel.send(reply)

if __name__ == "__main__":
    keep_alive()

    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN bulunamadı. Render Environment kısmını kontrol et.")

    client.run(DISCORD_TOKEN)
