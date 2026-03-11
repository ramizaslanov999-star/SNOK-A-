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
import aiohttp

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

# Veritabanını oluştur
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
    try:
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute("REPLACE INTO son_kisiler (veren_id, hedef_id, zaman, bildirim_gonderildi) VALUES (?, ?, ?, 0)",
                  (str(veren_id), str(hedef_id), int(zaman)))
        conn.commit()
        conn.close()
        print(f"✅ Kayıt: {veren_id} → {hedef_id} @ {zaman}")
        return True
    except Exception as e:
        print(f"❌ Veritabanı hatası: {e}")
        return False

def son_kisi_getir(veren_id):
    try:
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute("SELECT hedef_id, zaman FROM son_kisiler WHERE veren_id=?", (str(veren_id),))
        sonuc = c.fetchone()
        conn.close()
        return sonuc if sonuc else None
    except Exception as e:
        print(f"❌ Veritabanı okuma hatası: {e}")
        return None

def bildirim_durumu_guncelle(veren_id):
    try:
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute("UPDATE son_kisiler SET bildirim_gonderildi=1 WHERE veren_id=?", (str(veren_id),))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"❌ Bildirim güncelleme hatası: {e}")

def tum_bildirimler_getir():
    try:
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute("SELECT veren_id, zaman FROM son_kisiler WHERE bildirim_gonderildi=0")
        sonuclar = c.fetchall()
        conn.close()
        return sonuclar
    except Exception as e:
        print(f"❌ Bildirim listesi hatası: {e}")
        return []

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

async def webhook_komut_gonder(kanal, komut):
    """Webhook ile YAGPDB'ye komut gönder"""
    try:
        # Webhook oluştur
        webhook = await kanal.create_webhook(name="SNOK-İtibar")
        
        # Webhook ile mesaj gönder
        await webhook.send(
            komut,
            username="SNOK Sistemi"
        )
        
        # Webhook'u hemen sil
        await webhook.delete()
        
        print(f"✅ Webhook ile gönderildi: {komut}")
        return True
    except Exception as e:
        print(f"❌ Webhook hatası: {e}")
        return False

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
            title="⚔️ **KENDİNİ YÜCELTEMEZSİN** ⚔️",
            description="Kendi adını kendin yüceltemezsin. Bu yerde saygı, başkalarının gözünde kazanılır.",
            color=0xFFA500
        )
        await ctx.send(embed=embed)
        return
    
    simdi = int(time.time())
    veren_id = ctx.author.id
    
    # SON KİŞİ KONTROLÜ
    son_kisi = son_kisi_getir(veren_id)
    if son_kisi:
        son_hedef_id = int(son_kisi[0])
        son_zaman = son_kisi[1]
        
        # Aynı kişiye verme kontrolü
        if son_hedef_id == hedef.id:
            gecen = simdi - son_zaman
            if gecen < rep_cooldown:
                embed = discord.Embed(
                    title="⚔️ **SAYGI TEK YERDE TOPLANMAZ** ⚔️",
                    description="Aynı kişiye üst üste itibar verilmez. Saygı tek bir yerde toplanmaz.",
                    color=0xFFA500
                )
                await ctx.send(embed=embed)
                return
        
        # Cooldown kontrolü
        gecen = simdi - son_zaman
        if gecen < rep_cooldown:
            kalan = rep_cooldown - gecen
            dakika = kalan // 60
            saniye = kalan % 60
            embed = discord.Embed(
                title="⏳ **SABIR** ⏳",
                description=f"Yeni bir saygı bırakmak için **{dakika} dakika {saniye} saniye** zamanının dolmasını beklemelisin.",
                color=0xFFFF00
            )
            await ctx.send(embed=embed)
            return
    
    # YAGPDB'Yİ TETİKLE - WEBHOOK İLE
    try:
        log_kanal = bot.get_channel(LOG_KANAL_ID)
        if log_kanal:
            # WEBHOOK ile gönder
            yagpdb_komut = f"-snokrep {hedef.mention}"
            basarili = await webhook_komut_gonder(log_kanal, yagpdb_komut)
            
            if basarili:
                # 2 saniye bekle
                await asyncio.sleep(2)
                
                # Son kişiyi kaydet
                son_kisi_kaydet(veren_id, hedef.id, simdi)
                
                embed = discord.Embed(
                    title="🌟 **GÖLGELER ARASINDAN YÜKSELEN İSİM** 🌟",
                    description=f"**{ctx.author.display_name}**, **{hedef.display_name}**'nin adını saygı defterine yazdı. Bu sunucuda bir isim daha gölgeler arasından yükseliyor.",
                    color=0x00FF00
                )
                await ctx.send(embed=embed)
            else:
                await ctx.send("❌ YAGPDB'ye komut gönderilemedi!")
        else:
            await ctx.send("❌ Log kanalı bulunamadı!")
            
    except Exception as e:
        print(f"❌ HATA: {e}")
        embed = discord.Embed(
            title="❌ **HATA**",
            description="Puan verilemedi",
            color=0xFF0000
        )
        await ctx.send(embed=embed)

@bot.command(name='şaka', aliases=['saka'])
async def saka(ctx):
    await ctx.send(f"😂 {random.choice(saka_listesi)}")

@bot.command(name='fıkra', aliases=['fikra'])
async def fikra(ctx):
    await ctx.send(f"🎭 {random.choice(fıkra_listesi)}")

@bot.command(name='yardım', aliases=['yrd', 'help'])
async def yardim(ctx):
    is_abi = (ctx.author.id == ABI_ID)
    
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
        name="👑 **İtibar Sistemi**",
        value=(
            "`-r @kullanıcı` - İtibar puanı verir\n"
            "• 1 saat cooldown\n"
            "• Aynı kişiye üst üste verilmez\n"
            "• 1 saat sonra bildirim gelir"
        ),
        inline=False
    )
    
    if is_abi:
        embed.add_field(
            name="👑 **Abi Özel**",
            value="Hoş geldin abi! Sistem aktif.",
            inline=False
        )
    
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ SNOK v35.0 hazır!")
    print(f"🔹 -r komutu: 1 saat cooldown + son kişi kontrolü")
    print(f"🔹 Log kanalına WEBHOOK ile gönderiliyor")
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
                if simdi >= zaman + 3600:
                    if kanal:
                        embed = discord.Embed(
                            title="⚡ **SAYGI DEFTERİ YENİDEN AÇILDI** ⚡",
                            description=f"<@{veren_id}> Bekleme süresi sona erdi. Saygı defteri yeniden açık.",
                            color=0x00FF00
                        )
                        await kanal.send(embed=embed)
                        bildirim_durumu_guncelle(veren_id)
                        print(f"✅ Bildirim gönderildi: {veren_id}")
        except Exception as e:
            print(f"❌ Bildirim hatası: {e}")
        await asyncio.sleep(30)

if __name__ == "__main__":
    print("=" * 60)
    print("🚀 SNOK v35.0 BAŞLATILIYOR")
    print("=" * 60)
    print(f"🔹 Log kanalı: {LOG_KANAL_ID}")
    print(f"🔹 Bildirim kanalı: {BILDIRIM_KANAL_ID}")
    print("=" * 60)
    bot.run(DISCORD_TOKEN)
