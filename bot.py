import discord
from discord.ext import commands
import os
import time
import asyncio
import sqlite3
from datetime import datetime
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

if not DISCORD_TOKEN:
    print("❌ HATA: Discord token bulunamadı!")
    exit(1)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

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

def bildirim_durumu_guncelle(veren_id):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("UPDATE son_kisiler SET bildirim_gonderildi=1 WHERE veren_id=?", (str(veren_id),))
    conn.commit()
    conn.close()

def tum_bildirimler_getir():
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("SELECT veren_id, zaman FROM son_kisiler WHERE bildirim_gonderildi=0")
    sonuclar = c.fetchall()
    conn.close()
    return sonuclar

rep_cooldown = 3600

# ========== -R KOMUTU ==========
@bot.command(name='r', aliases=['-r'])
async def rep_ver(ctx, hedef: discord.Member = None):
    print(f"🔥🔥🔥 -r KOMUTU ÇALIŞTI! 🔥🔥🔥")
    print(f"📝 Yazan: {ctx.author}")
    print(f"🎯 Hedef: {hedef}")
    
    if not hedef:
        await ctx.send("❌ Birini etiketle: `-r @kullanıcı`")
        return
    
    if hedef.id == ctx.author.id:
        await ctx.send("⚔️ Kendine puan veremezsin!")
        return
    
    simdi = int(time.time())
    veren_id = ctx.author.id
    hedef_id = hedef.id
    
    son_kisi = son_kisi_getir(veren_id)
    
    if son_kisi and son_kisi["hedef_id"] == hedef_id:
        gecen = simdi - son_kisi["zaman"]
        
        if gecen < rep_cooldown:
            kalan = rep_cooldown - gecen
            dakika = kalan // 60
            saniye = kalan % 60
            await ctx.send(f"⏳ Bekleme süresi: {dakika} dakika {saniye} saniye")
            return
        else:
            await ctx.send("⚔️ Aynı kişiye tekrar veremezsin! Önce başkasına ver.")
            return
    
    try:
        log_kanal = bot.get_channel(LOG_KANAL_ID)
        if log_kanal:
            await log_kanal.send(f"-snokrep {hedef.id}")
            print(f"✅ Log kanalına gönderildi: -snokrep {hedef.id}")
            
            son_kisi_kaydet(veren_id, hedef_id, simdi)
            
            await ctx.send(f"✅ {ctx.author.mention} → {hedef.mention} (+1 puan)")
        else:
            await ctx.send("❌ Log kanalı bulunamadı!")
            
    except Exception as e:
        print(f"❌ HATA: {e}")
        await ctx.send(f"❌ Hata oluştu: {e}")

# ========== YARDIM KOMUTU ==========
@bot.command(name='yardım', aliases=['yrd', 'help'])
async def yardim(ctx):
    embed = discord.Embed(
        title="🌸 **SNOK Bot** 🌸",
        description="Merhaba! Ben SNOK, Rkiaoni tarafından yapıldım.",
        color=0x00FF00
    )
    embed.add_field(name="📝 Komutlar", value="`-r @kullanıcı` - İtibar puanı verir\n`!yardım` - Bu menüyü gösterir", inline=False)
    await ctx.send(embed=embed)

# ========== OLAY DİNLEYİCİLER ==========
@bot.event
async def on_ready():
    print(f"✅ SNOK hazır: {bot.user}")
    print(f"📋 Log Kanalı: {LOG_KANAL_ID}")
    print(f"🔔 Bildirim Kanalı: {BILDIRIM_KANAL_ID}")
    bot.loop.create_task(bildirim_kontrol())

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # -r komutunu manuel yakala
    if message.content.startswith('-r '):
        print(f"📥 Manuel -r yakalandı: {message.content}")
        ctx = await bot.get_context(message)
        hedef = message.mentions[0] if message.mentions else None
        if hedef:
            await rep_ver(ctx, hedef)
        else:
            await message.channel.send("❌ Birini etiketle: `-r @kullanıcı`")
        return
    
    await bot.process_commands(message)

# ========== BİLDİRİM KONTROLÜ ==========
async def bildirim_kontrol():
    await bot.wait_until_ready()
    print(f"⏰ Bildirim kontrolü başladı (1 dakikada bir kontrol)")
    while not bot.is_closed():
        try:
            simdi = int(time.time())
            bildirimler = tum_bildirimler_getir()
            kanal = bot.get_channel(BILDIRIM_KANAL_ID)
            
            for veren_id, zaman in bildirimler:
                if simdi >= zaman:
                    if kanal:
                        await kanal.send(f"<@{veren_id}> 1 saat doldu! Artık itibar verebilirsin.")
                        bildirim_durumu_guncelle(veren_id)
                        print(f"✅ Bildirim gönderildi: {veren_id}")
        except Exception as e:
            print(f"❌ Bildirim hatası: {e}")
        await asyncio.sleep(60)

# ========== BOTU BAŞLAT ==========
if __name__ == "__main__":
    print("=" * 50)
    print("🚀 SNOK v19.0 BAŞLATILIYOR")
    print("=" * 50)
    print(f"📋 Log Kanalı: {LOG_KANAL_ID}")
    print(f"🔔 Bildirim Kanalı: {BILDIRIM_KANAL_ID}")
    print("=" * 50)
    bot.run(DISCORD_TOKEN)
