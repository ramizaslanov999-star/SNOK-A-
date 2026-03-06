import discord
from discord.ext import commands
import os
import time
import asyncio
import sqlite3
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

if not DISCORD_TOKEN:
    print("❌ Discord token bulunamadı!")
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

def tum_bildirimler_getir():
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("SELECT veren_id, zaman FROM son_kisiler WHERE bildirim_gonderildi=0")
    sonuclar = c.fetchall()
    conn.close()
    return sonuclar

rep_cooldown = 3600

@bot.command(name='r', aliases=['-r'])
async def rep_ver(ctx, hedef: discord.Member = None):
    print(f"📝 -r komutu çalıştı!")
    
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
            await ctx.send(f"⏳ Bekle: {dakika} dakika {saniye} saniye")
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

@bot.event
async def on_ready():
    print(f"✅ SNOK hazır: {bot.user}")
    print(f"📋 Log Kanalı: {LOG_KANAL_ID}")
    bot.loop.create_task(bildirim_kontrol())

async def bildirim_kontrol():
    await bot.wait_until_ready()
    print(f"⏰ Bildirim kontrolü başladı")
    while not bot.is_closed():
        try:
            simdi = int(time.time())
            bildirimler = tum_bildirimler_getir()
            kanal = bot.get_channel(BILDIRIM_KANAL_ID)
            for veren_id, zaman in bildirimler:
                if simdi >= zaman:
                    if kanal:
                        await kanal.send(f"<@{veren_id}> 1 saat doldu! Artık puan verebilirsin.")
                        conn = sqlite3.connect(DB_DOSYASI)
                        c = conn.cursor()
                        c.execute("UPDATE son_kisiler SET bildirim_gonderildi=1 WHERE veren_id=?", (veren_id,))
                        conn.commit()
                        conn.close()
        except Exception as e:
            print(f"❌ Bildirim hatası: {e}")
        await asyncio.sleep(60)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.content.startswith('-r'):
        await bot.process_commands(message)
        return
    if bot.user.mentioned_in(message) or 'snok' in message.content.lower():
        await message.reply("Merhaba! Ben SNOK. Sorun yaşıyorsan Rkiaoni'ye ulaş.")
    await bot.process_commands(message)

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 SNOK BAŞLATILIYOR")
    print("=" * 50)
    bot.run(DISCORD_TOKEN)
