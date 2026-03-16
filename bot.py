import discord
import requests
import os
import random
from flask import Flask
from threading import Thread

TOKEN = os.getenv("DISCORD_TOKEN")

GROQ_KEY = os.getenv("GROQ_API_KEY")
TOGETHER_KEY = os.getenv("TOGETHER_API_KEY")
HF_KEY = os.getenv("HF_API_KEY")

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

character_prompt = """
You are Hikari.
You are a cute anime mascot girl living in a Discord server.
You are playful, friendly and slightly chaotic.
You love anime, games and teasing members.
Keep answers short and fun.
"""

def ask_groq(msg):

    url = "https://api.groq.com/openai/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "llama3-70b-8192",
        "messages": [
            {"role": "system", "content": character_prompt},
            {"role": "user", "content": msg}
        ]
    }

    r = requests.post(url, headers=headers, json=data)

    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"]

    return None


def ask_together(msg):

    url = "https://api.together.xyz/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {TOGETHER_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "meta-llama/Llama-3-70b-chat-hf",
        "messages": [
            {"role": "system", "content": character_prompt},
            {"role": "user", "content": msg}
        ]
    }

    r = requests.post(url, headers=headers, json=data)

    if r.status_code == 200:
        return r.json()["choices"][0]["message"]["content"]

    return None


def ask_hugging(msg):

    url = "https://api-inference.huggingface.co/models/microsoft/DialoGPT-large"

    headers = {
        "Authorization": f"Bearer {HF_KEY}"
    }

    data = {
        "inputs": msg
    }

    r = requests.post(url, headers=headers, json=data)

    if r.status_code == 200:
        try:
            return r.json()[0]["generated_text"]
        except:
            return None

    return None


def ask_ai(msg):

    for ai in [ask_groq, ask_together, ask_hugging]:
        try:
            answer = ai(msg)
            if answer:
                return answer
        except:
            pass

    return "Hikari şu an biraz uykulu... sonra tekrar konuşalım!"


@client.event
async def on_ready():
    print("Bot aktif")


@client.event
async def on_message(message):

    if message.author == client.user:
        return

    if client.user in message.mentions:

        msg = message.content.replace(f"<@{client.user.id}>","")

        reply = ask_ai(msg)

        await message.channel.send(reply)


# render keep alive
app = Flask('')

@app.route('/')
def home():
    return "Bot alive"

def run():
    app.run(host='0.0.0.0',port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

keep_alive()

client.run(TOKEN)
