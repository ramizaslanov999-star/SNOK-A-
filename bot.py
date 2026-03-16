import os
import requests
import discord
from flask import Flask
from threading import Thread

# =========================
# ENV VARIABLES
# =========================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
HF_API_KEY = os.getenv("HF_API_KEY")

# =========================
# BOT SETTINGS
# =========================
BOT_PERSONA = """
You are Hikari.
You are a cute anime-style Discord mascot girl for a community server.
You are friendly, playful, cheerful, slightly mischievous, and lovable.
You speak in short, natural, fun messages.
You like anime, games, fun server chatter, and friendly banter.
Do not say you are an AI unless directly asked.
Do not make your answers too long.
Stay in character.
"""

FALLBACK_MESSAGE = "Hikari şu an biraz uykulu... sonra tekrar konuşalım!"

# =========================
# DISCORD CLIENT
# =========================
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# =========================
# KEEP ALIVE FOR RENDER
# =========================
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive."

def run_web():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    thread = Thread(target=run_web)
    thread.daemon = True
    thread.start()

# =========================
# AI PROVIDERS
# =========================
def ask_groq(user_message: str):
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY yok")
        return None

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": BOT_PERSONA},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.9,
        "max_tokens": 300
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"🟣 Groq status: {response.status_code}")
        print(f"🟣 Groq response: {response.text[:500]}")

        if response.status_code != 200:
            return None

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"❌ Groq error: {e}")
        return None


def ask_together(user_message: str):
    if not TOGETHER_API_KEY:
        print("❌ TOGETHER_API_KEY yok")
        return None

    url = "https://api.together.xyz/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {TOGETHER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/Llama-3-70b-chat-hf",
        "messages": [
            {"role": "system", "content": BOT_PERSONA},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.9,
        "max_tokens": 300
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"🟢 Together status: {response.status_code}")
        print(f"🟢 Together response: {response.text[:500]}")

        if response.status_code != 200:
            return None

        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"❌ Together error: {e}")
        return None


def ask_huggingface(user_message: str):
    if not HF_API_KEY:
        print("❌ HF_API_KEY yok")
        return None

    url = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-large"
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}"
    }
    payload = {
        "inputs": user_message
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        print(f"🟠 HuggingFace status: {response.status_code}")
        print(f"🟠 HuggingFace response: {response.text[:500]}")

        if response.status_code != 200:
            return None

        data = response.json()

        if isinstance(data, list) and len(data) > 0:
            if "generated_text" in data[0]:
                return data[0]["generated_text"].strip()

        return None
    except Exception as e:
        print(f"❌ HuggingFace error: {e}")
        return None


def ask_ai(user_message: str):
    user_message = user_message.strip()

    if not user_message:
        return "Bana bir şey yaz, boş boş etiket atma kerata."

    providers = [
        ("Groq", ask_groq),
        ("Together", ask_together),
        ("HuggingFace", ask_huggingface),
    ]

    for provider_name, provider_func in providers:
        print(f"➡️ Deneniyor: {provider_name}")
        reply = provider_func(user_message)

        if reply and reply.strip():
            print(f"✅ Başarılı provider: {provider_name}")
            return reply

    print("❌ Tüm provider'lar başarısız oldu.")
    return FALLBACK_MESSAGE

# =========================
# DISCORD EVENTS
# =========================
@client.event
async def on_ready():
    print(f"✅ Bot aktif: {client.user}")

    if not DISCORD_TOKEN:
        print("❌ DISCORD_TOKEN eksik")
    if not GROQ_API_KEY:
        print("⚠️ GROQ_API_KEY eksik")
    if not TOGETHER_API_KEY:
        print("⚠️ TOGETHER_API_KEY eksik")
    if not HF_API_KEY:
        print("⚠️ HF_API_KEY eksik")


@client.event
async def on_message(message):
    if message.author.bot:
        return

    if client.user in message.mentions:
        content = message.content

        mention_formats = [
            f"<@{client.user.id}>",
            f"<@!{client.user.id}>"
        ]

        for mention in mention_formats:
            content = content.replace(mention, "")

        content = content.strip()

        print(f"💬 Kullanıcı mesajı: {content}")

        async with message.channel.typing():
            reply = ask_ai(content)

        if len(reply) > 1900:
            reply = reply[:1900]

        await message.channel.send(reply)

# =========================
# MAIN
# =========================
if __name__ == "__main__":
    keep_alive()

    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN bulunamadı. Render environment variables kısmını kontrol et.")

    client.run(DISCORD_TOKEN)
