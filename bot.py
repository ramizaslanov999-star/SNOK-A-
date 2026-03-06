import discord
from discord.ext import commands
import os
import httpx
import time
import random
import re
import asyncio
import sqlite3
from datetime import datetime, timedelta
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
    c.execute("REPLACE INTO son_kisiler (veren_id, hedef_id, zaman) VALUES (?, ?, ?)",
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

def bildirim_durumu_kontrol(veren_id):
    conn = sqlite3.connect(DB_DOSYASI)
    c = conn.cursor()
    c.execute("SELECT bildirim_gonderildi FROM son_kisiler WHERE veren_id=?", (str(veren_id),))
    sonuc = c.fetchone()
    conn.close()
    return sonuc[0] if sonuc else 0

system_prompt = """
Sen SNOK'sun. Bir Discord sohbet botusun.
- Adın SNOK. Rkiaoni tarafından yapıldın.
- 17 yaşında, genç, enerjik, tatlı bir botsun.
- Konuşurken bol bol emoji kullanırsın: 😊 🥰 🤗 😂 ✨
- Şakacı, samimi ve arkadaş canlısısın.
- Kısa ve doğal cevaplar ver.
"""

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
        return random.choice(["😅 Çok yoğunum, birazdan dener misin?", "⚡ Enerjim düştü, hemen geliyorum!", "🤗 Bir saniye, düşünüyorum..."])

ai_yoneticisi = AIYoneticisi(AI_SERVICES)

kufur_listesi = ['amk', 'aq', 'sik', 'pic', 'orospu', 'ibne', 'göt', 'yarrak', 'pust', 'anani', 'babani', 'sikeyim', 'sikik', 'amcik', 'amq', 'piç', 'orospu çocuğu', 'amına koyayım']

hafiza = defaultdict(lambda: {
    "ilk_gorusme": time.time(),
    "son_gorusme": time.time(),
    "konusma_sayisi": 0,
    "bilgiler": {},
    "konusma_tarzi": "normal"
})

son_mesaj_zamani = defaultdict(float)
mesaj_sayaci = defaultdict(list)

async def spam_kufur_kontrolu(message):
    user_id = message.author.id
    simdi = time.time()
    icerik = message.content.lower()
    if simdi - son_mesaj_zamani[user_id] < 1.5:
        mesaj_sayaci[user_id].append(simdi)
        if len(mesaj_sayaci[user_id]) > 3 and simdi - mesaj_sayaci[user_id][0] < 5:
            await message.reply("🍬 **Hey!** Çok hızlı mesaj atıyorsun, yavaş ol! 🍭")
            return True
    son_mesaj_zamani[user_id] = simdi
    if len(mesaj_sayaci[user_id]) > 10:
        mesaj_sayaci[user_id] = mesaj_sayaci[user_id][-5:]
    for kufur in kufur_listesi:
        if kufur in icerik:
            await message.reply("😳 **Ayıp!** Böyle kelimeler duymak istemiyorum! 🥺")
            return True
    return False

yeni_katilanlar = {}

async def yeni_katilana_selam_ver(message):
    user_id = message.author.id
    simdi = time.time()
    if user_id not in yeni_katilanlar or simdi - yeni_katilanlar[user_id] > 3600:
        yeni_katilanlar[user_id] = simdi
        if random.random() < 0.3:
            selamlar = [
                f"👋 Merhaba {message.author.display_name}! Hoş geldin sohbete!",
                f"😊 Selam {message.author.display_name}! Nasılsın?",
                f"🤗 Ooo {message.author.display_name}, geldin mi? Bekliyordum!"
            ]
            await message.reply(random.choice(selamlar))
            return True
    return False

r_tesekkurleri = [
    "🤗 Ayy çok tatlısın! Teşekkürler {isim}!",
    "🥰 Bana değer verdiğin için sağ ol {isim}!",
    "😊 İyilik yap iyilik bul {isim}!",
    "💖 Sen gerçekten çok iyi birisin {isim}!",
    "✨ Bana itibar verdiğin için teşekkürler {isim}!"
]

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

rep_cooldown = 3600
rep_bildirim_kanal_id = 1473947547365019812

# ========== -R KOMUTU - YAGPDB ENTEGRASYONLU ==========
@bot.command(name='rep', aliases=['r', '-r'])
async def rep_ver(ctx, hedef: discord.Member = None):
    """İtibar puanı verir - YAGPDB ile entegre"""
    
    if not hedef:
        embed = discord.Embed(title="⚔️ **HATA** ⚔️", description="Birini etiketlemelisin!\nKullanım: `-r @kullanıcı`", color=0xFF0000)
        await ctx.send(embed=embed)
        return
    
    if hedef.id == ctx.author.id:
        embed = discord.Embed(title="⚔️ **KENDİNİ ONURLANDIRAMAZSIN** ⚔️", description="Gerçek bir savaşçı kendi kılıcını sırtlamaz.", color=0xFFA500)
        await ctx.send(embed=embed)
        return
    
    simdi = int(time.time())
    veren_id = ctx.author.id
    hedef_id = hedef.id
    
    # VERİTABANINDAN SON KİŞİYİ GETİR
    son_kisi = son_kisi_getir(veren_id)
    
    # AYNI KİŞİ KONTROLÜ
    if son_kisi:
        if son_kisi["hedef_id"] == hedef_id:
            gecen = simdi - son_kisi["zaman"]
            
            if gecen < rep_cooldown:
                # Cooldown içinde aynı kişi
                kalan = rep_cooldown - gecen
                dakika = int(kalan // 60)
                saniye = int(kalan % 60)
                embed = discord.Embed(
                    title="⚔️ **ONUR SIRADA BEKLİYOR** ⚔️",
                    description=f"**Aynı savaşçıya iki kez onur verilmez!**\n\n{hedef.mention} için bekleme süren bitmemiş.\n⏳ **{dakika} dakika {saniye} saniye** sonra başkasına verebilirsin.",
                    color=0xFF0000
                )
                await ctx.send(embed=embed)
                return
            else:
                # Cooldown geçmiş ama son kişi aynı - yine engelle!
                embed = discord.Embed(
                    title="⚔️ **ONUR SIRADA BEKLİYOR** ⚔️",
                    description=f"**Aynı savaşçıya tekrar onur veremezsin!**\n\nÖnce **başka birini** onurlandır, sonra {hedef.mention}'e dönebilirsin.",
                    color=0xFF0000
                )
                await ctx.send(embed=embed)
                return
    
    # ========== YAGPDB KOMUTUNU ÇALIŞTIR ==========
    # YAGPDB'nin +giverep komutunu çağır
    try:
        # YAGPDB'nin kanalına mesaj gönder (admin komutu)
        yagpdb_kanal = bot.get_channel(1475733574413062215)  # Log kanalı
        if yagpdb_kanal:
            await yagpdb_kanal.send(f"+giverep {hedef.mention}")
        
        # Başarılı olduysa KAYDET
        son_kisi_kaydet(veren_id, hedef_id, simdi)
        
        # Bildirim zamanlayıcısı başlat
        asyncio.create_task(bildirim_gonder(ctx.author, simdi + rep_cooldown))
        
        # Başarılı mesajı
        tesekkur = random.choice(r_tesekkurleri).format(isim=hedef.display_name)
        embed = discord.Embed(
            title="🏆 **ONUR BAĞIŞLANDI!** 🏆",
            description=f"{ctx.author.mention} → {hedef.mention}\n\n{tesekkur}",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        
    except Exception as e:
        embed = discord.Embed(title="❌ **HATA**", description=f"Puan verilemedi: {str(e)}", color=0xFF0000)
        await ctx.send(embed=embed)

async def bildirim_gonder(kullanici, bitis_zamani):
    simdi = time.time()
    bekle = bitis_zamani - simdi
    if bekle > 0:
        await asyncio.sleep(bekle)
        veren_id = kullanici.id
        durum = bildirim_durumu_kontrol(veren_id)
        if durum == 0:
            kanal = bot.get_channel(rep_bildirim_kanal_id)
            if kanal:
                embed = discord.Embed(
                    title="⚡ **GÜCÜN GERİ DÖNDÜ!** ⚡",
                    description=f"{kullanici.mention} 1 saatlik bekleme süren doldu! Artık yeni bir savaşçıya onur verebilirsin.\n\n_Unutma, aynı savaşçıya tekrar onur vermek için önce başkasına vermelisin._",
                    color=0x00FF00
                )
                await kanal.send(embed=embed)
                bildirim_durumu_guncelle(veren_id, 1)

@bot.command(name='şaka', aliases=['saka'])
async def saka(ctx):
    await ctx.send(f"😂 {random.choice(saka_listesi)}")

@bot.command(name='fıkra', aliases=['fikra'])
async def fikra(ctx):
    await ctx.send(f"🎭 {random.choice(fıkra_listesi)}")

@bot.command(name='yazitura', aliases=['yt', 'yazi', 'tura'])
async def yazi_tura(ctx):
    sonuc = random.choice(['Yazı! 🪙', 'Tura! 🦅', 'Para dik durdu! 🤹'])
    await ctx.send(f"🪙 **{ctx.author.display_name}** için: {sonuc}")

@bot.command(name='zar', aliases=['dice'])
async def zar_at(ctx, adet: int = 1):
    if adet > 5:
        adet = 5
        await ctx.send("En fazla 5 zar atabilirim! 🎲")
    zarlar = [random.choice(['⚀', '⚁', '⚂', '⚃', '⚄', '⚅']) for _ in range(adet)]
    await ctx.send(f"🎲 **{ctx.author.display_name}** için {adet} zar: {' '.join(zarlar)}")

@bot.command(name='bilgi', aliases=['info'])
async def bilgi_ver(ctx):
    bilgiler = [
        "Python yılan değil, bir programlama dilidir! 🐍",
        "Discord'da ilk bot 2015'te yapıldı! 📅",
        "Ben Rkiaoni tarafından yapıldım! 👑",
        "Her gün yeni bir şey öğreniyorum! 📚"
    ]
    await ctx.send(f"ℹ️ {random.choice(bilgiler)}")

@bot.command(name='sarıl', aliases=['saril', 'hug'])
async def saril(ctx, member: discord.Member = None):
    if member is None or member.id == ctx.author.id:
        await ctx.send(f"🤗 {ctx.author.display_name} kendine mi sarılacaksın? Bari ben sarılayım!")
    else:
        await ctx.send(f"🤗 {ctx.author.display_name}, {member.mention}'a sarıldı! 💕")

def konusma_tarzi_analiz(mesaj):
    mesaj_lower = mesaj.lower()
    alayli_kelimeler = ['alay', 'dalga', 'salak', 'aptal', 'mal']
    if any(k in mesaj_lower for k in alayli_kelimeler):
        return "alayli"
    tatli_kelimeler = ['❤️', '💕', '😘', '😍', 'tatlı', 'canım']
    if any(k in mesaj_lower for k in tatli_kelimeler):
        return "tatli"
    ciddi_kelimeler = ['sorun', 'problem', 'yardım', 'lütfen', 'önemli']
    if any(k in mesaj_lower for k in ciddi_kelimeler):
        return "ciddi"
    return "normal"

@bot.command(name='yardım', aliases=['yrd', 'kömək'])
async def yardim(ctx):
    embed = discord.Embed(
        title="🌸 **SNOK - Yapay Zekalı Arkadaşın** 🌸",
        description="Merhaba! Ben **SNOK**, Rkiaoni tarafından yaratılmış yapay zeka destekli bir botum.",
        color=discord.Color.pink()
    )
    embed.add_field(
        name="🎪 **Eğlence Komutları**",
        value="`!fıkra` - Temel'den fıkralar 🎭\n`!şaka` - Komik şakalar 😂\n`!yazitura` - Yazı tura 🪙\n`!zar` - Zar atar 🎲\n`!bilgi` - İlginç bilgiler ℹ️\n`!sarıl` - Birine sarılır 🤗",
        inline=False
    )
    embed.add_field(
        name="👑 **İtibar Sistemi**",
        value="`-r @kullanıcı` - İtibar puanı verir\n• Aynı kişiye 1 saatte bir verilebilir\n• Cooldown bitince bildirim gelir",
        inline=False
    )
    embed.add_field(
        name="💬 **Sohbet**",
        value="Bana @SNOK yazarak veya 'snok' diyerek ulaşabilirsin",
        inline=False
    )
    embed.set_footer(text="SNOK v16.0 - YAGPDB Entegre | Rkiaoni tarafından yaratıldı")
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ SNOK hazır!")
    print(f"👑 Yaratıcı: Rkiaoni")
    print(f"🔹 -r komutu: YAGPDB entegre + aynı kişi kontrolü")
    print(f"🧠 Yapay zeka: Gemini + Groq")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    user_id = message.author.id
    simdi = time.time()
    is_abi = (user_id == ABI_ID)
    hafiza[user_id]["son_gorusme"] = simdi
    hafiza[user_id]["konusma_sayisi"] += 1
    hafiza[user_id]["konusma_tarzi"] = konusma_tarzi_analiz(message.content)
    if "selamlamadın" in message.content.lower() and "niye" in message.content.lower():
        await message.reply("😅 Aa fark etmemişim, kusura bakma! Şimdi sana kocaman bir merhaba! 👋😊")
        return
    if not (bot.user.mentioned_in(message) or 'snok' in message.content.lower()):
        if not is_abi:
            await yeni_katilana_selam_ver(message)
        return
    if await spam_kufur_kontrolu(message):
        return
    if message.content.startswith('!'):
        await bot.process_commands(message)
        return
    async with message.channel.typing():
        messages = [{"role": "user", "content": message.content}]
        tarz = hafiza[user_id]["konusma_tarzi"]
        tarz_ek = ""
        if tarz == "alayli":
            tarz_ek = "\nKarşındaki alaylı konuşuyor. Biraz sinirlenebilirsin."
        elif tarz == "tatli":
            tarz_ek = "\nKarşındaki tatlı konuşuyor. Sen de tatlı cevap ver."
        elif tarz == "ciddi":
            tarz_ek = "\nKarşındaki ciddi konuşuyor. Ciddi cevap ver."
        if is_abi:
            abi_prompt = system_prompt + "\n\n=== ÖZEL ===\nŞu an seni yaratan abinle konuşuyorsun! Ona 'abi' diye hitap et ve çok samimi ol."
        else:
            abi_prompt = system_prompt + tarz_ek
        cevap = await ai_yoneticisi.cevap_al(messages, abi_prompt)
        try:
            await message.reply(cevap)
        except discord.errors.HTTPException:
            await message.channel.send(cevap)

if __name__ == "__main__":
    if not DISCORD_TOKEN:
        print("❌ Discord token eksik!")
    else:
        print("=" * 50)
        print("🚀 SNOK v16.0 - YAGPDB ENTEGRE")
        print("=" * 50)
        print(f"👑 Yaratıcı: Rkiaoni")
        print(f"🔹 -r komutu: YAGPDB entegre + aynı kişi kontrolü")
        print("=" * 50)
        bot.run(DISCORD_TOKEN)
