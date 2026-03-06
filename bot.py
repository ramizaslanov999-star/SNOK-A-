import discord
from discord.ext import commands
import os
import httpx
import time
import random
import re
import asyncio
import sqlite3
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "SNOK AI çalışıyor! 🤖"

def run_web():
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_web, daemon=True).start()

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print(f"🔑 DISCORD_TOKEN: {'VAR' if DISCORD_TOKEN else 'YOK'}")
print(f"🔑 GEMINI_API_KEY: {'VAR' if GEMINI_API_KEY else 'YOK'}")
print(f"🔑 GROQ_API_KEY: {'VAR' if GROQ_API_KEY else 'YOK'}")

if not DISCORD_TOKEN:
    print("❌ HATA: Discord token bulunamadı!")
    exit(1)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

ABI_ID = 423889250052734986
LOG_KANAL_ID = 1475733574413062215
BILDIRIM_KANAL_ID = 1473947547365019812

DB_DOSYASI = "reputation.db"

conn = sqlite3.connect(DB_DOSYASI)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS son_kisiler
             (veren_id TEXT PRIMARY KEY, 
              hedef_id TEXT, 
              zaman INTEGER,
              bildirim_gonderildi INTEGER DEFAULT 0)''')
conn.commit()
conn.close()
print("✅ Veritabanı hazır!")

def son_kisi_kaydet(veren_id, hedef_id, zaman):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("REPLACE INTO son_kisiler (veren_id, hedef_id, zaman, bildirim_gonderildi) VALUES (?, ?, ?, 0)",
              (str(veren_id), str(hedef_id), int(zaman)))
    conn.commit()
    conn.close()

def son_kisi_getir(veren_id):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("SELECT hedef_id, zaman FROM son_kisiler WHERE veren_id=?", (str(veren_id),))
    sonuc = c.fetchone()
    conn.close()
    if sonuc:
        return {"hedef_id": int(sonuc[0]), "zaman": sonuc[1]}
    return None

def bildirim_durumu_guncelle(veren_id, durum=1):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("UPDATE son_kisiler SET bildirim_gonderildi=? WHERE veren_id=?", (durum, str(veren_id)))
    conn.commit()
    conn.close()

def tum_bildirimler_getir():
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("SELECT veren_id, zaman FROM son_kisiler WHERE bildirim_gonderildi=0")
    sonuclar = c.fetchall()
    conn.close()
    return [{"veren_id": r[0], "zaman": r[1]} for r in sonuclar]

system_prompt = "Sen SNOK'sun, tatlı bir Discord botusun."

AI_SERVICES = [
    {
        "name": "Gemini",
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        "api_key": GEMINI_API_KEY,
        "priority": 1,
        "format_func": lambda messages, system: {
            "contents": [{
                "parts": [
                    {"text": f"{system}\n\nKullanıcı: {messages[-1]['content']}\nSNOK:"}
                ]
            }]
        },
        "headers": lambda key: {
            "Content-Type": "application/json",
            "x-goog-api-key": key
        },
        "url_with_key": lambda url, key: f"{url}?key={key}",
        "parse_func": lambda data: data["candidates"][0]["content"]["parts"][0]["text"]
    },
    {
        "name": "Groq",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "api_key": GROQ_API_KEY,
        "priority": 2,
        "format_func": lambda messages, system: {
            "model": "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": messages[-1]['content']}
            ],
            "max_tokens": 200,
            "temperature": 0.8
        },
        "headers": lambda key: {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        },
        "url_with_key": lambda url, key: url,
        "parse_func": lambda data: data["choices"][0]["message"]["content"]
    }
]

class AIYoneticisi:
    def __init__(self, services):
        self.services = services
        self.son_hata = {s["name"]: 0 for s in services}
        self.toplam_kullanim = 0
        self.basarisiz_servisler = set()
        print(f"🤖 AI Yöneticisi: {len(services)} AI servisi hazır")
    
    async def cevap_al(self, messages, system_prompt, max_retries=3):
        for deneme in range(max_retries):
            for service in sorted(self.services, key=lambda x: x["priority"]):
                if service["name"] in self.basarisiz_servisler:
                    continue
                if time.time() - self.son_hata[service["name"]] < 60:
                    continue
                try:
                    payload = service["format_func"](messages, system_prompt)
                    headers = service["headers"](service["api_key"])
                    url = service["url_with_key"](service["url"], service["api_key"])
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        response = await client.post(url, headers=headers, json=payload)
                        if response.status_code == 200:
                            self.toplam_kullanim += 1
                            self.son_hata[service["name"]] = 0
                            if service["name"] in self.basarisiz_servisler:
                                self.basarisiz_servisler.remove(service["name"])
                            data = response.json()
                            return service["parse_func"](data)
                        elif response.status_code == 429:
                            self.son_hata[service["name"]] = time.time()
                            continue
                        else:
                            self.son_hata[service["name"]] = time.time()
                            if response.status_code in [400, 401, 403]:
                                self.basarisiz_servisler.add(service["name"])
                            continue
                except Exception:
                    self.son_hata[service["name"]] = time.time()
                    continue
            await asyncio.sleep(10)
        return random.choice(["😅 Çok yoğunum, birazdan dener misin?", "⚡ Enerjim düştü, hemen geliyorum!"])

ai_yoneticisi = AIYoneticisi(AI_SERVICES)

rep_cooldown = 3600

@bot.command(name='r', aliases=['-r'])
async def rep_ver(ctx, hedef: discord.Member = None):
    print(f"📝 -r komutu çalıştı! Yazan: {ctx.author}, Hedef: {hedef}")
    
    if not hedef:
        embed = discord.Embed(title="⚔️ **HATA**", description="Birini etiketle! `-r @kullanıcı`", color=0xFF0000)
        await ctx.send(embed=embed)
        return
    
    if hedef.id == ctx.author.id:
        embed = discord.Embed(title="⚔️ **KENDİNİ ONURLANDIRAMAZSIN**", description="Kendine puan veremezsin.", color=0xFFA500)
        await ctx.send(embed=embed)
        return
    
    simdi = int(time.time())
    veren_id = ctx.author.id
    hedef_id = hedef.id
    
    son_kisi = son_kisi_getir(veren_id)
    
    if son_kisi and son_kisi["hedef_id"] == hedef_id:
        gecen = simdi - son_kisi["zaman"]
        
        if gecen < rep_cooldown:
            kalan = rep_cooldown - gecen
            dakika = int(kalan // 60)
            saniye = int(kalan % 60)
            embed = discord.Embed(
                title="⏳ **Sabır...**",
                description=f"Bekleme süresi: **{dakika} dakika {saniye} saniye**",
                color=0xFFFF00
            )
            await ctx.send(embed=embed)
            return
        else:
            embed = discord.Embed(
                title="⚔️ **Aynı Kişi**",
                description="Aynı kişiye tekrar veremezsin. Önce başkasına ver.",
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            return
    
    try:
        log_kanal = bot.get_channel(LOG_KANAL_ID)
        if log_kanal:
            await log_kanal.send(f"-snokrep {hedef.id}")
            print(f"✅ Log kanalına gönderildi: -snokrep {hedef.id}")
            
            son_kisi_kaydet(veren_id, hedef_id, simdi)
            
            embed = discord.Embed(
                title="✅ **Onur Verildi**",
                description=f"{ctx.author.mention} → {hedef.mention}",
                color=0x00FF00
            )
            await ctx.send(embed=embed)
        else:
            print(f"❌ Log kanalı bulunamadı! ID: {LOG_KANAL_ID}")
            await ctx.send("❌ Log kanalı bulunamadı!")
            
    except Exception as e:
        print(f"❌ HATA: {e}")
        await ctx.send(f"❌ Hata: {e}")

@bot.command(name='yardım', aliases=['yrd'])
async def yardim(ctx):
    embed = discord.Embed(title="🌸 SNOK", description="Merhaba! Ben SNOK.", color=0x00FF00)
    embed.add_field(name="-r @kişi", value="İtibar puanı verir", inline=False)
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ SNOK hazır: {bot.user}")
    print(f"📋 Log Kanalı ID: {LOG_KANAL_ID}")
    print(f"🔔 Bildirim Kanalı ID: {BILDIRIM_KANAL_ID}")
    bot.loop.create_task(bildirim_kontrol())

async def bildirim_kontrol():
    await bot.wait_until_ready()
    print(f"⏰ Bildirim kontrolü başladı")
    while not bot.is_closed():
        try:
            simdi = int(time.time())
            bildirimler = tum_bildirimler_getir()
            kanal = bot.get_channel(BILDIRIM_KANAL_ID)
            for b in bildirimler:
                if simdi >= b["zaman"]:
                    if kanal:
                        await kanal.send(f"<@{b['veren_id']}> 1 saat doldu!")
                        bildirim_durumu_guncelle(b["veren_id"], 1)
        except Exception as e:
            print(f"❌ Bildirim hatası: {e}")
        await asyncio.sleep(300)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.content.startswith('-r'):
        await bot.process_commands(message)
        return
    if bot.user.mentioned_in(message) or 'snok' in message.content.lower():
        async with message.channel.typing():
            await message.reply("Merhaba! Ben SNOK.")
    await bot.process_commands(message)

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 SNOK BAŞLATILIYOR")
    print("=" * 50)
    print(f"📋 Log Kanalı: {LOG_KANAL_ID}")
    print(f"🔔 Bildirim Kanalı: {BILDIRIM_KANAL_ID}")
    print("=" * 50)
    bot.run(DISCORD_TOKEN)
