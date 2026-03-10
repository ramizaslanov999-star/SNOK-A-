import discord
from discord.ext import commands
import os
import time
import random
import asyncio
import sqlite3
from flask import Flask
import threading
from dotenv import load_dotenv

app = Flask(__name__)

@app.route('/')
def home():
    return "SNOK çalışıyor! 🤖"

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

ABI_ID = 423889250052734986
LOG_KANAL_ID = 1475733574413062215
BILDIRIM_KANAL_ID = 1473947547365019812

DB_DOSYASI = "son_kisi.db"

conn = sqlite3.connect(DB_DOSYASI)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS son_kisiler
             (veren_id TEXT PRIMARY KEY, 
              hedef_id TEXT, 
              zaman INTEGER,
              bildirim_gonderildi INTEGER DEFAULT 0)''')
conn.commit()
conn.close()
print("✅ Son kişi veritabanı hazır!")

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

saka_listesi = [
    "Bir gün bilgisayar fareye sormuş: 'Benimle oynar mısın?' Fare: 'Tabii ama önce şu kablolarını topla!' 🖱️",
    "Botlar neden yalan söylemez? Çünkü onların RAM'i yalanı kaldırmaz! 🤖",
    "Seninle ben çok iyi anlaşıyoruz. Çünkü ikimiz de sürekli mesajlaşıyoruz! 💬",
    "Bir gün bir bot 'Çok yoruldum' demiş. O günden beri reboot bekliyor! 🔄"
]

fıkra_listesi = [
    "Temel arkadaşıyla vapura binmiş. Biletçi sormuş: 'Biletiniz?' Temel: 'Yok.' Biletçi: 'Nerede?' Temel: 'Karadeniz'de!' 🚢",
    "Temel'e sormuşlar: 'En çok neyi seversin?' Temel: 'Para!' 'Peki ondan sonra?' Temel: 'Para üstü!' 💰"
]

rep_cooldown = 3600  # 1 saat

@bot.command(name='r', aliases=['-r'])
async def rep_ver(ctx, hedef: discord.Member = None):
    if not hedef:
        embed = discord.Embed(
            title="⚔️ **HATA** ⚔️",
            description="Birini etiketlemelisin!\nKullanım: `-r @kullanıcı`",
            color=0xFF0000
        )
        await ctx.send(embed=embed)
        return
    
    if hedef.id == ctx.author.id:
        embed = discord.Embed(
            title="⚔️ **KENDİNİ ONURLANDIRAMAZSIN** ⚔️",
            description="İtibar kazanılır, yazılmaz. Kendine puan veremezsin.",
            color=0xFFA500
        )
        await ctx.send(embed=embed)
        return
    
    simdi = int(time.time())
    veren_id = ctx.author.id
    hedef_id = hedef.id
    
    son_kisi = son_kisi_getir(veren_id)
    
    # COOLDOWN KONTROLÜ - 1 saat içinde KİMSEYE veremezsin
    if son_kisi:
        gecen = simdi - son_kisi["zaman"]
        
        # 1 saat dolmamışsa
        if gecen < rep_cooldown:
            kalan = rep_cooldown - gecen
            dakika = kalan // 60
            saniye = kalan % 60
            embed = discord.Embed(
                title="⏳ **Sabır...**",
                description=f"Yeni bir saygı bırakmak için zamanın dolmasını beklemelisin.\n\n⏱️ **{dakika} dakika {saniye} saniye** kaldı.",
                color=0xFFFF00
            )
            await ctx.send(embed=embed)
            return
    
    # 1 saat geçmiş - YAGPDB'yi tetikle
    try:
        log_kanal = bot.get_channel(LOG_KANAL_ID)
        if log_kanal:
            await log_kanal.send(f"-snokrep {hedef.id}")
            print(f"✅ YAGPDB'ye iletildi: -snokrep {hedef.id}")
            
            son_kisi_kaydet(veren_id, hedef_id, simdi)
            
            embed = discord.Embed(
                title="🌟 **Onur Yükseldi** 🌟",
                description=f"Gölgeler arasından bir isim daha yükseldi…\n\n**{hedef.display_name}**, **{ctx.author.display_name}** tarafından onurlandırıldı.",
                color=0x00FF00
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Log kanalı bulunamadı!")
            
    except Exception as e:
        print(f"❌ HATA: {e}")
        embed = discord.Embed(title="❌ **HATA**", description=f"Puan verilemedi: {str(e)}", color=0xFF0000)
        await ctx.send(embed=embed)

@bot.command(name='şaka', aliases=['saka'])
async def saka(ctx):
    await ctx.send(f"😂 {random.choice(saka_listesi)}")

@bot.command(name='fıkra', aliases=['fikra'])
async def fikra(ctx):
    await ctx.send(f"🎭 {random.choice(fıkra_listesi)}")

@bot.command(name='yardım', aliases=['yrd', 'help'])
async def yardim(ctx):
    embed = discord.Embed(
        title="🌸 **SNOK - İtibar Asistanı** 🌸",
        description="Merhaba! Ben SNOK, itibar sistemini yöneten basit bir botum.",
        color=0x00FF00
    )
    embed.add_field(
        name="🎪 **Eğlence**",
        value="`!şaka` - Rastgele şaka\n`!fıkra` - Temel fıkrası",
        inline=False
    )
    embed.add_field(
        name="👑 **İtibar**",
        value="`-r @kullanıcı` - İtibar puanı verir\n• 1 saat cooldown (kimseye veremezsin)\n• 1 saat sonra bildirim gelir",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ SNOK hazır!")
    print(f"🔹 -r komutu: Genel cooldown (1 saat)")
    print(f"⏰ Bildirim kontrolü başlatılıyor...")
    bot.loop.create_task(bildirim_kontrol())

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # -r komutunu manuel yakala
    if message.content.startswith('-r ') or message.content.startswith('-r'):
        ctx = await bot.get_context(message)
        hedef = message.mentions[0] if message.mentions else None
        if hedef:
            await rep_ver(ctx, hedef)
        else:
            embed = discord.Embed(
                title="⚔️ **HATA** ⚔️",
                description="Birini etiketlemelisin!\nKullanım: `-r @kullanıcı`",
                color=0xFF0000
            )
            await message.channel.send(embed=embed)
        return
    
    # "Beni niye selamlamadın?" sorusu
    if "selamlamadın" in message.content.lower() and "niye" in message.content.lower():
        await message.reply("😅 Aa fark etmemişim, kusura bakma! Şimdi sana kocaman bir merhaba! 👋😊")
        return
    
    await bot.process_commands(message)

async def bildirim_kontrol():
    await bot.wait_until_ready()
    print(f"⏰ Bildirim kontrolü başladı")
    while not bot.is_closed():
        try:
            simdi = int(time.time())
            bildirimler = tum_bildirimler_getir()
            kanal = bot.get_channel(BILDIRIM_KANAL_ID)
            
            for veren_id, zaman in bildirimler:
                # SADECE 3600 saniye geçtiyse bildirim gönder
                if simdi >= zaman + 3600:
                    if kanal:
                        embed = discord.Embed(
                            title="⚡ **İtibar Defteri Açıldı** ⚡",
                            description=f"<@{veren_id}> Bekleme süresi sona erdi. İtibar defteri yeniden açık.",
                            color=0x00FF00
                        )
                        await kanal.send(embed=embed)
                        bildirim_durumu_guncelle(veren_id)
        except Exception as e:
            print(f"❌ Bildirim hatası: {e}")
        await asyncio.sleep(60)

if __name__ == "__main__":
    print("=" * 50)
    print("🚀 SNOK v26.0 - GENEL COOLDOWN")
    print("=" * 50)
    print("🔹 -r komutu: 1 saat cooldown (kimseye veremezsin)")
    print("🔹 YAGPDB ID hatası çözüldü")
    print("=" * 50)
    bot.run(DISCORD_TOKEN)
