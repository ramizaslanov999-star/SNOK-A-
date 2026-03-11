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
rep_cooldown = 3600  # 1 saat

# =========================
# VERİTABANI
# =========================
def veritabani_hazirla():
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()

    c.execute('''
        CREATE TABLE IF NOT EXISTS son_kisiler (
            veren_id TEXT PRIMARY KEY,
            hedef_id TEXT,
            zaman INTEGER,
            bildirim_gonderildi INTEGER DEFAULT 0
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS bildirim_ayar (
            kullanici_id TEXT PRIMARY KEY,
            durum INTEGER DEFAULT 1
        )
    ''')

    conn.commit()
    conn.close()
    print("✅ Veritabanı hazır!")

veritabani_hazirla()

def son_kisi_kaydet(veren_id, hedef_id, zaman):
    try:
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute(
            "REPLACE INTO son_kisiler (veren_id, hedef_id, zaman, bildirim_gonderildi) VALUES (?, ?, ?, 0)",
            (str(veren_id), str(hedef_id), int(zaman))
        )
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

def bildirim_durumu_getir(kullanici_id):
    try:
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute("SELECT durum FROM bildirim_ayar WHERE kullanici_id=?", (str(kullanici_id),))
        sonuc = c.fetchone()

        if sonuc is None:
            c.execute("INSERT INTO bildirim_ayar (kullanici_id, durum) VALUES (?, 1)", (str(kullanici_id),))
            conn.commit()
            conn.close()
            return True

        conn.close()
        return bool(sonuc[0])
    except Exception as e:
        print(f"❌ Bildirim durumu okuma hatası: {e}")
        return True

def bildirim_durumu_ayarla(kullanici_id, durum):
    try:
        conn = sqlite3.connect(DB_DOSYASI)
        c = conn.cursor()
        c.execute(
            "REPLACE INTO bildirim_ayar (kullanici_id, durum) VALUES (?, ?)",
            (str(kullanici_id), 1 if durum else 0)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Bildirim ayarlama hatası: {e}")
        return False

# =========================
# EĞLENCE
# =========================
saka_listesi = [
    "Bir gün bilgisayar fareye sormuş: 'Benimle oynar mısın?' Fare: 'Tabii ama önce şu kablolarını topla!' 🖱️",
    "Botlar neden yalan söylemez? Çünkü onların RAM'i yalanı kaldırmaz! 🤖",
    "Seninle ben çok iyi anlaşıyoruz. Çünkü ikimiz de sürekli mesajlaşıyoruz! 💬",
    "Bir gün bir bot 'Çok yoruldum' demiş. O günden beri reboot bekliyor! 🔄"
]

fikra_listesi = [
    "Temel arkadaşıyla vapura binmiş. Biletçi sormuş: 'Biletiniz?' Temel: 'Yok.' Biletçi: 'Nerede?' Temel: 'Karadeniz'de!' 🚢",
    "Temel'e sormuşlar: 'En çok neyi seversin?' Temel: 'Para!' 'Peki ondan sonra?' Temel: 'Para üstü!' 💰"
]

# =========================
# BUTON
# =========================
class BildirimKapatView(discord.ui.View):
    def __init__(self, hedef_kullanici_id):
        super().__init__(timeout=None)
        self.hedef_kullanici_id = str(hedef_kullanici_id)

    @discord.ui.button(label="Hatırlatıcıyı Kapat", style=discord.ButtonStyle.danger, emoji="🔕", custom_id="rep_bildirim_kapat")
    async def kapat_buton(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.hedef_kullanici_id:
            await interaction.response.send_message("❌ Bu buton sana ait değil.", ephemeral=True)
            return

        bildirim_durumu_ayarla(interaction.user.id, False)

        embed = discord.Embed(
            title="🔕 Bildirimler Kapatıldı",
            description="Saygınlık bildirimlerin kapatıldı. Tekrar açmak için `!repbildirimac` yazabilirsin.",
            color=0xFF0000
        )
        await interaction.response.edit_message(embed=embed, view=None)

# =========================
# REP KOMUTU
# =========================
@bot.command(name='r')
async def rep_ver(ctx, hedef: discord.Member = None):
    if not hedef:
        embed = discord.Embed(
            title="⚔️ HATA ⚔️",
            description="Birini etiketlemelisin.\nKullanım: `-r @kullanıcı`",
            color=0xFF0000
        )
        await ctx.send(embed=embed)
        return

    if hedef.id == ctx.author.id:
        embed = discord.Embed(
            title="⚔️ KENDİNE VEREMEZSİN ⚔️",
            description="Kendi kendine saygınlık veremezsin.",
            color=0xFFA500
        )
        await ctx.send(embed=embed)
        return

    if hedef.bot:
        embed = discord.Embed(
            title="⚔️ GEÇERSİZ HEDEF ⚔️",
            description="Botlara saygınlık veremezsin.",
            color=0xFFA500
        )
        await ctx.send(embed=embed)
        return

    simdi = int(time.time())
    veren_id = ctx.author.id

    son_kisi = son_kisi_getir(veren_id)
    if son_kisi:
        son_hedef_id = int(son_kisi[0])
        son_zaman = int(son_kisi[1])
        gecen = simdi - son_zaman

        if gecen < rep_cooldown:
            if son_hedef_id == hedef.id:
                embed = discord.Embed(
                    title="⚔️ SAYGI TEK YERDE TOPLANMAZ ⚔️",
                    description="Aynı kişiye cooldown bitmeden tekrar saygınlık veremezsin.",
                    color=0xFFA500
                )
                await ctx.send(embed=embed)
                return

            kalan = rep_cooldown - gecen
            dakika = kalan // 60
            saniye = kalan % 60
            embed = discord.Embed(
                title="⏳ SABIR ⏳",
                description=f"Yeni bir saygı bırakmak için **{dakika} dakika {saniye} saniye** beklemelisin.",
                color=0xFFFF00
            )
            await ctx.send(embed=embed)
            return

    try:
        log_kanal = bot.get_channel(LOG_KANAL_ID)
        if not log_kanal:
            await ctx.send("❌ Log kanalı bulunamadı.")
            return

        # EN KRİTİK KISIM BURASI
        yagpdb_komut = f"-snokrep <@{hedef.id}>"
        await log_kanal.send(yagpdb_komut)

        son_kisi_kaydet(veren_id, hedef.id, simdi)

        embed = discord.Embed(
            title="🌟 GÖLGELER ARASINDAN YÜKSELEN İSİM 🌟",
            description=f"**{ctx.author.display_name}**, **{hedef.display_name}** için saygınlık bıraktı.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)

        print(f"✅ YAGPDB komutu gönderildi: {yagpdb_komut}")

    except Exception as e:
        print(f"❌ HATA: {e}")
        embed = discord.Embed(
            title="❌ HATA",
            description="Puan verilemedi.",
            color=0xFF0000
        )
        await ctx.send(embed=embed)

# =========================
# BİLDİRİM KOMUTLARI
# =========================
@bot.command(name='repbildirimac')
async def repbildirimac(ctx):
    bildirim_durumu_ayarla(ctx.author.id, True)
    await ctx.send("🔔 Saygınlık bildirimlerin açıldı.")

@bot.command(name='repbildirimkapat')
async def repbildirimkapat(ctx):
    bildirim_durumu_ayarla(ctx.author.id, False)
    await ctx.send("🔕 Saygınlık bildirimlerin kapatıldı.")

@bot.command(name='şaka', aliases=['saka'])
async def saka(ctx):
    await ctx.send(f"😂 {random.choice(saka_listesi)}")

@bot.command(name='fıkra', aliases=['fikra'])
async def fikra(ctx):
    await ctx.send(f"🎭 {random.choice(fikra_listesi)}")

@bot.command(name='yardım', aliases=['yrd', 'help'])
async def yardim(ctx):
    is_abi = (ctx.author.id == ABI_ID)

    embed = discord.Embed(
        title="🌸 SNOK - İtibar Asistanı 🌸",
        description="Ben SNOK, itibar sistemini yöneten botum.",
        color=0x00FF00
    )
    embed.add_field(
        name="🎪 Eğlence",
        value="`!şaka` - Rastgele şaka\n`!fıkra` - Fıkra",
        inline=False
    )
    embed.add_field(
        name="👑 İtibar Sistemi",
        value=(
            "`-r @kullanıcı` - İtibar puanı verir\n"
            "`!repbildirimac` - Bildirim açar\n"
            "`!repbildirimkapat` - Bildirim kapatır\n"
            "• 1 saat cooldown\n"
            "• Aynı kişiye cooldown bitmeden tekrar verilmez\n"
            "• Süre dolunca bildirim gelir"
        ),
        inline=False
    )

    if is_abi:
        embed.add_field(
            name="👑 Abi Özel",
            value="Hoş geldin abi, sistem aktif.",
            inline=False
        )

    await ctx.send(embed=embed)

# =========================
# OLAYLAR
# =========================
@bot.event
async def on_ready():
    print("✅ SNOK hazır!")
    print("🔹 -r komutu aktif")
    print("🔹 Log kanalına normal bot mesajı gönderiliyor")
    print("🔹 Bildirim sistemi aktif")
    bot.loop.create_task(bildirim_kontrol())

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.startswith('-r'):
        ctx = await bot.get_context(message)
        hedef = message.mentions[0] if message.mentions else None

        if hedef:
            await rep_ver(ctx, hedef)
        else:
            embed = discord.Embed(
                title="⚔️ HATA ⚔️",
                description="Birini etiketlemelisin.\nKullanım: `-r @kullanıcı`",
                color=0xFF0000
            )
            await message.channel.send(embed=embed)
        return

    await bot.process_commands(message)

# =========================
# BİLDİRİM KONTROL
# =========================
async def bildirim_kontrol():
    await bot.wait_until_ready()
    print("⏰ Bildirim kontrolü başladı")

    while not bot.is_closed():
        try:
            simdi = int(time.time())
            bildirimler = tum_bildirimler_getir()
            kanal = bot.get_channel(BILDIRIM_KANAL_ID)

            for veren_id, zaman in bildirimler:
                if simdi >= int(zaman) + rep_cooldown:
                    if not bildirim_durumu_getir(veren_id):
                        bildirim_durumu_guncelle(veren_id)
                        continue

                    if kanal:
                        embed = discord.Embed(
                            title="🔔 Saygınlık vakti geldi!",
                            description=f"<@{veren_id}> Şu an bir üyeye saygınlık verebilirsin.",
                            color=0x00FF00
                        )

                        view = BildirimKapatView(veren_id)
                        await kanal.send(content=f"<@{veren_id}>", embed=embed, view=view)
                        print(f"✅ Bildirim gönderildi: {veren_id}")

                    bildirim_durumu_guncelle(veren_id)

        except Exception as e:
            print(f"❌ Bildirim hatası: {e}")

        await asyncio.sleep(30)

# =========================
# BAŞLAT
# =========================
if __name__ == "__main__":
    print("=" * 60)
    print("🚀 SNOK BAŞLATILIYOR")
    print("=" * 60)
    print(f"🔹 Log kanalı: {LOG_KANAL_ID}")
    print(f"🔹 Bildirim kanalı: {BILDIRIM_KANAL_ID}")
    print("=" * 60)
    bot.run(DISCORD_TOKEN)
