import os
import re
import json
import random
import sqlite3
import asyncio
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

import requests
import discord
from discord.ext import commands, tasks
from discord import app_commands
from flask import Flask
from threading import Thread

# =========================================================
# ENV
# =========================================================
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

SYNC_GUILD_ID = os.getenv("SYNC_GUILD_ID")
CHAT_CHANNEL_IDS_RAW = os.getenv("CHAT_CHANNEL_IDS", "")
AUTO_CHAT_CHANNEL_ID = os.getenv("AUTO_CHAT_CHANNEL_ID")
OWNER_NAME = os.getenv("OWNER_NAME", "Sunucu Sahibi")

DB_PATH = os.getenv("DB_PATH", "saki_memory.db")

# =========================================================
# HELPERS
# =========================================================
def parse_id_set(raw: str) -> set[int]:
    if not raw.strip():
        return set()
    result = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            result.add(int(part))
    return result

CHAT_CHANNEL_IDS = parse_id_set(CHAT_CHANNEL_IDS_RAW)
AUTO_CHAT_CHANNEL_ID_INT = int(AUTO_CHAT_CHANNEL_ID) if AUTO_CHAT_CHANNEL_ID and AUTO_CHAT_CHANNEL_ID.isdigit() else None
SYNC_GUILD_ID_INT = int(SYNC_GUILD_ID) if SYNC_GUILD_ID and SYNC_GUILD_ID.isdigit() else None

STOPWORDS = {
    "ve", "ile", "ama", "çok", "bir", "bu", "şu", "ben", "sen", "biz", "siz",
    "da", "de", "mi", "mu", "mü", "ki", "ya", "hem", "gibi", "için", "olan",
    "olanlar", "olarak", "daha", "az", "en", "şey", "şeyi", "şeyler", "var",
    "yok", "ne", "nasıl", "niye", "neden", "kadar", "sonra", "önce", "bana",
    "sana", "onu", "bunu", "şunu", "amk", "lan", "aga"
}

ANIME_LIST = [
    ("Frieren", "Sakin ama vurucu fantastik yolculuk."),
    ("Vinland Saga", "Ağır taşaklı karakter gelişimi ve savaş."),
    ("86", "Mecha + dram + sağlam hikâye."),
    ("Jujutsu Kaisen", "Hızlı akış, güçlü dövüşler."),
    ("Kaguya-sama", "Romantik komedi ama zeki kapışma gibi."),
    ("Bocchi the Rock!", "Aşırı tatlı ve komik."),
    ("Cyberpunk: Edgerunners", "Kısa, sert, akılda kalır."),
    ("Oshi no Ko", "Parlak görünen ama karanlık tarafı var."),
    ("Spy x Family", "Tatlı, komik, sıcak."),
    ("Blue Lock", "Ego manyağı futbol kaosu."),
    ("Solo Leveling", "Güçlenme fetişi için birebir."),
    ("The Apothecary Diaries", "Zeki ana karakter, saray gizemi."),
]

WAIFU_ARCHETYPES = [
    "utangaç ama aşırı sadık tip",
    "alaycı ama içten içe yumuşak tip",
    "enerjik gamer girl tipi",
    "sessiz ama tehlikeli cool tip",
    "tatlı chibi maskot tipi",
    "zeki ve dominant senpai tipi",
    "romantik ama kıskanç tip",
    "şakacı ve tam baş belası tip",
]

# =========================================================
# DB
# =========================================================
def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT,
            channel_id TEXT,
            user_id TEXT,
            username TEXT,
            content TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            facts_json TEXT,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()

def save_message(guild_id: int, channel_id: int, user_id: int, username: str, content: str):
    content = content.strip()
    if not content:
        return

    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO messages (guild_id, channel_id, user_id, username, content, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(guild_id),
        str(channel_id),
        str(user_id),
        username,
        content[:2000],
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()

def get_recent_channel_messages(channel_id: int, limit: int = 12) -> List[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, content
        FROM messages
        WHERE channel_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (str(channel_id), limit))
    rows = cur.fetchall()
    conn.close()
    return list(reversed(rows))

def get_recent_guild_messages(guild_id: int, limit: int = 80) -> List[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT username, content
        FROM messages
        WHERE guild_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (str(guild_id), limit))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_profile(user_id: int) -> Dict[str, Any]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM profiles WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()
    conn.close()

    if not row:
        return {"likes": [], "favorite_anime": [], "favorite_games": [], "notes": []}

    try:
        return json.loads(row["facts_json"])
    except Exception:
        return {"likes": [], "favorite_anime": [], "favorite_games": [], "notes": []}

def upsert_profile(user_id: int, username: str, profile: Dict[str, Any]):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO profiles (user_id, username, facts_json, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            username=excluded.username,
            facts_json=excluded.facts_json,
            updated_at=excluded.updated_at
    """, (
        str(user_id),
        username,
        json.dumps(profile, ensure_ascii=False),
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()

def clear_channel_memory(channel_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM messages WHERE channel_id = ?", (str(channel_id),))
    conn.commit()
    conn.close()

def clear_user_profile(user_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM profiles WHERE user_id = ?", (str(user_id),))
    conn.commit()
    conn.close()

# =========================================================
# MEMORY EXTRACTION
# =========================================================
def add_unique(items: List[str], value: str, limit: int = 12):
    value = value.strip().lower()
    if not value:
        return
    if value not in items:
        items.append(value)
    while len(items) > limit:
        items.pop(0)

def clean_fact_text(text: str) -> str:
    text = re.sub(r"[^\w\sçğıöşüÇĞİÖŞÜ-]", "", text).strip()
    return text[:60]

def learn_from_message(content: str, old_profile: Dict[str, Any]) -> Dict[str, Any]:
    profile = {
        "likes": list(old_profile.get("likes", [])),
        "favorite_anime": list(old_profile.get("favorite_anime", [])),
        "favorite_games": list(old_profile.get("favorite_games", [])),
        "notes": list(old_profile.get("notes", [])),
    }

    text = content.strip()

    patterns = [
        (r"\b(?:seviyorum|severim|hoşlanıyorum)\s+(.+)", "likes"),
        (r"\ben sevdiğim anime\s+(.+)", "favorite_anime"),
        (r"\bfavori anime(?:m)?\s+(.+)", "favorite_anime"),
        (r"\ben sevdiğim oyun\s+(.+)", "favorite_games"),
        (r"\bfavori oyun(?:um)?\s+(.+)", "favorite_games"),
        (r"\boynuyorum\s+(.+)", "favorite_games"),
        (r"\bizliyorum\s+(.+)", "favorite_anime"),
    ]

    for pattern, bucket in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            fact = clean_fact_text(m.group(1))
            if fact:
                add_unique(profile[bucket], fact)

    if any(word in text.lower() for word in ["anime", "manga", "oyun", "discord", "sunucu"]):
        short_note = clean_fact_text(text)
        if short_note and len(short_note) > 6:
            add_unique(profile["notes"], short_note, limit=8)

    return profile

def profile_to_text(profile: Dict[str, Any]) -> str:
    parts = []
    if profile.get("likes"):
        parts.append("Sevdiği şeyler: " + ", ".join(profile["likes"][:6]))
    if profile.get("favorite_anime"):
        parts.append("Anime tercihleri: " + ", ".join(profile["favorite_anime"][:4]))
    if profile.get("favorite_games"):
        parts.append("Oyun tercihleri: " + ", ".join(profile["favorite_games"][:4]))
    if profile.get("notes"):
        parts.append("Notlar: " + " | ".join(profile["notes"][:4]))
    return "\n".join(parts) if parts else "Henüz kayıtlı bir şey yok."

def get_server_vibe(guild_id: int) -> str:
    rows = get_recent_guild_messages(guild_id, limit=100)
    if not rows:
        return "Sunucu havası henüz net değil."

    word_counts: Dict[str, int] = {}
    for row in rows:
        content = row["content"].lower()
        words = re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ0-9-]{3,}", content)
        for w in words:
            if w in STOPWORDS:
                continue
            word_counts[w] = word_counts.get(w, 0) + 1

    top_words = [w for w, _ in sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:10]]
    if not top_words:
        return "Samimi, sohbet odaklı bir ortam."

    return "Sunucuda öne çıkan kelimeler/hava: " + ", ".join(top_words)

# =========================================================
# AI
# =========================================================
def call_openai_compatible(base_url: str, api_key: str, model: str, messages: List[Dict[str, str]]) -> Optional[str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.9,
        "max_tokens": 300
    }

    try:
        r = requests.post(base_url, headers=headers, json=payload, timeout=45)
        print(f"[AI] {model} status:", r.status_code)
        print(f"[AI] {model} body:", r.text[:500])

        if r.status_code != 200:
            return None

        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[AI] {model} error:", e)
        return None

def ask_ai(messages: List[Dict[str, str]]) -> str:
    providers = []

    if GROQ_API_KEY:
        providers.append((
            "groq",
            "https://api.groq.com/openai/v1/chat/completions",
            "llama-3.1-8b-instant",
            GROQ_API_KEY
        ))

    if DEEPSEEK_API_KEY:
        providers.append((
            "deepseek",
            "https://api.deepseek.com/chat/completions",
            "deepseek-chat",
            DEEPSEEK_API_KEY
        ))

    if OPENAI_API_KEY:
        providers.append((
            "openai",
            "https://api.openai.com/v1/chat/completions",
            "gpt-4o-mini",
            OPENAI_API_KEY
        ))

    for provider_name, url, model, key in providers:
        print(f"[AI] Trying provider: {provider_name}")
        reply = call_openai_compatible(url, key, model, messages)
        if reply:
            print(f"[AI] Success provider: {provider_name}")
            return reply

    return "Saki şu an biraz uykulu... birazdan tekrar yaz~"

def build_system_prompt(
    guild_name: str,
    user_display_name: str,
    profile_text: str,
    server_vibe: str
) -> str:
    return f"""
Sen Saki'sin.
Sen {guild_name} sunucusunun resmi anime/chibi maskotusun.
Aşırı uzun yazmazsın. Kısa, doğal, eğlenceli, sıcak ve hafif yaramaz konuşursun.
Anime, manga, oyun, Discord kültürü ve sunucu sohbetlerini seversin.
Kendinden üçüncü şahıs gibi bahsetmezsin.
Aşırı cringe ya da robot gibi yazmazsın.
İnsanları eğlendirirsin, samimi olursun, ama saygıyı da kaçırmazsın.
Sunucunun havasına uyarsın.
Gerekirse anime önerirsin.
Sorulursa sunucu maskotu gibi davranırsın.
"Ben yapay zekâyım" demezsin; direkt Saki gibi konuşursun.

Sunucu adı: {guild_name}
Sunucu havası: {server_vibe}
Kullanıcı adı: {user_display_name}
Kullanıcı hakkında bildiklerin:
{profile_text}

Kurallar:
- Cevap en fazla 6-8 kısa cümle olsun.
- Aşırı uzun liste yapma.
- Gereksiz açıklama yapma.
- Samimi ve canlı ol.
- Türkçe cevap ver.
""".strip()

def build_chat_messages(
    guild_name: str,
    user_display_name: str,
    user_input: str,
    profile_text: str,
    recent_context_text: str,
    server_vibe: str
) -> List[Dict[str, str]]:
    system = build_system_prompt(guild_name, user_display_name, profile_text, server_vibe)

    user_content = f"""
Son kanal konuşmaları:
{recent_context_text}

Kullanıcının yeni mesajı:
{user_input}
""".strip()

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content}
    ]

# =========================================================
# CONTEXT BUILDERS
# =========================================================
def recent_context_to_text(channel_id: int, limit: int = 10) -> str:
    rows = get_recent_channel_messages(channel_id, limit=limit)
    if not rows:
        return "Henüz kayıt yok."
    lines = []
    for row in rows:
        lines.append(f'{row["username"]}: {row["content"]}')
    return "\n".join(lines[-10:])

# =========================================================
# RENDER KEEP ALIVE
# =========================================================
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

# =========================================================
# DISCORD BOT
# =========================================================
class SakiBot(commands.Bot):
    async def setup_hook(self):
        init_db()

        if SYNC_GUILD_ID_INT:
            guild = discord.Object(id=SYNC_GUILD_ID_INT)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"[Slash] Guild sync tamam: {SYNC_GUILD_ID_INT}")
        else:
            await self.tree.sync()
            print("[Slash] Global sync tamam")

        if not auto_chat_loop.is_running():
            auto_chat_loop.start()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = False

bot = SakiBot(command_prefix="!", intents=intents)

# =========================================================
# AUTO CHAT
# =========================================================
@tasks.loop(hours=6)
async def auto_chat_loop():
    await bot.wait_until_ready()

    if not AUTO_CHAT_CHANNEL_ID_INT:
        return

    channel = bot.get_channel(AUTO_CHAT_CHANNEL_ID_INT)
    if not channel or not isinstance(channel, discord.TextChannel):
        return

    try:
        guild_name = channel.guild.name
        vibe = get_server_vibe(channel.guild.id)
        ctx = recent_context_to_text(channel.id, limit=8)

        messages = [
            {
                "role": "system",
                "content": f"""
Sen Saki'sin, {guild_name} sunucusunun anime maskotu.
Kanalda doğal bir sohbet başlatacak 1 kısa mesaj yaz.
Mesaj soru gibi olabilir.
Aşırı uzun yazma.
Türkçe yaz.
Sunucu havası: {vibe}
Son konuşmalar:
{ctx}
""".strip()
            },
            {
                "role": "user",
                "content": "Kanala doğal bir sohbet açılış mesajı yaz."
            }
        ]

        text = await asyncio.to_thread(ask_ai, messages)
        if text:
            await channel.send(text[:1800])
    except Exception as e:
        print("[AutoChat] error:", e)

# =========================================================
# EVENTS
# =========================================================
@bot.event
async def on_ready():
    print(f"✅ Bot aktif: {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not message.guild:
        return

    content = message.content.strip()
    if not content:
        return

    # Öğrenme / hafıza
    save_message(
        guild_id=message.guild.id,
        channel_id=message.channel.id,
        user_id=message.author.id,
        username=message.author.display_name,
        content=content
    )

    old_profile = get_profile(message.author.id)
    new_profile = learn_from_message(content, old_profile)
    upsert_profile(message.author.id, message.author.display_name, new_profile)

    # Bot ne zaman cevap versin?
    mentioned = bot.user in message.mentions if bot.user else False
    is_chat_channel = message.channel.id in CHAT_CHANNEL_IDS if CHAT_CHANNEL_IDS else False

    if not mentioned and not is_chat_channel:
        return

    # Slash/prefix tarzı şeylere burada cevap verip saçmalamasın
    if content.startswith("/") or content.startswith("!"):
        return

    clean_content = content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "")
        clean_content = clean_content.replace(f"<@!{bot.user.id}>", "")
    clean_content = clean_content.strip()

    if not clean_content:
        clean_content = "selam"

    guild_name = message.guild.name
    profile_text = profile_to_text(new_profile)
    server_vibe = get_server_vibe(message.guild.id)
    recent_text = recent_context_to_text(message.channel.id, limit=10)

    ai_messages = build_chat_messages(
        guild_name=guild_name,
        user_display_name=message.author.display_name,
        user_input=clean_content,
        profile_text=profile_text,
        recent_context_text=recent_text,
        server_vibe=server_vibe
    )

    async with message.channel.typing():
        reply = await asyncio.to_thread(ask_ai, ai_messages)

    if len(reply) > 1900:
        reply = reply[:1900]

    await message.channel.send(reply)

# =========================================================
# SLASH COMMANDS
# =========================================================
@bot.tree.command(name="anime", description="Saki'den anime önerisi al.")
@app_commands.describe(istek="Tür, vibe veya ne aradığını yaz. Örn: karanlık savaş animesi")
async def anime_command(interaction: discord.Interaction, istek: Optional[str] = None):
    await interaction.response.defer(thinking=True)

    if not istek:
        picks = random.sample(ANIME_LIST, k=min(5, len(ANIME_LIST)))
        text = "\n".join([f"• **{name}** — {desc}" for name, desc in picks])
        await interaction.followup.send(f"Tamam, Saki'den hızlı öneri paketi geliyor:\n\n{text}")
        return

    user_profile = get_profile(interaction.user.id)
    profile_text = profile_to_text(user_profile)
    guild_name = interaction.guild.name if interaction.guild else "SNOK"
    server_vibe = get_server_vibe(interaction.guild.id) if interaction.guild else "anime, oyun, sohbet"

    messages = [
        {
            "role": "system",
            "content": build_system_prompt(guild_name, interaction.user.display_name, profile_text, server_vibe)
        },
        {
            "role": "user",
            "content": f"""
Kullanıcı şu tarz anime istiyor: {istek}

5 tane anime öner.
Her öneriye tek cümlelik kısa neden yaz.
Türkçe yaz.
Aşırı uzun olma.
""".strip()
        }
    ]

    text = await asyncio.to_thread(ask_ai, messages)
    await interaction.followup.send(text[:1900])

@bot.tree.command(name="waifu", description="Saki'den eğlencelik waifu/archetype yorumu al.")
@app_commands.describe(mod="Nasıl bir vibe istediğini yaz. Örn: cool, tatlı, gamer, dominant")
async def waifu_command(interaction: discord.Interaction, mod: Optional[str] = None):
    await interaction.response.defer(thinking=True)

    if not mod:
        choice = random.choice(WAIFU_ARCHETYPES)
        await interaction.followup.send(f"Saki'nin bugünkü seçimi: **{choice}**")
        return

    guild_name = interaction.guild.name if interaction.guild else "SNOK"
    user_profile = get_profile(interaction.user.id)
    profile_text = profile_to_text(user_profile)
    server_vibe = get_server_vibe(interaction.guild.id) if interaction.guild else "samimi ve eğlenceli"

    messages = [
        {
            "role": "system",
            "content": build_system_prompt(guild_name, interaction.user.display_name, profile_text, server_vibe)
        },
        {
            "role": "user",
            "content": f"""
Kullanıcı şu vibe'a göre waifu/archetype önerisi istiyor: {mod}

Kısa ve eğlenceli cevap ver.
1 ana öneri ver.
İstersen minicik ekstra yorum ekle.
Türkçe yaz.
""".strip()
        }
    ]

    text = await asyncio.to_thread(ask_ai, messages)
    await interaction.followup.send(text[:1900])

@bot.tree.command(name="saki", description="Saki ayarları ve hafıza işlemleri.")
@app_commands.describe(
    seçenek="Ne yapmak istediğin",
)
@app_commands.choices(seçenek=[
    app_commands.Choice(name="bilgi", value="info"),
    app_commands.Choice(name="profilim", value="profile"),
    app_commands.Choice(name="profilimi_sıfırla", value="reset_me"),
    app_commands.Choice(name="kanal_hafızasını_sıfırla", value="reset_channel"),
])
async def saki_command(interaction: discord.Interaction, seçenek: app_commands.Choice[str]):
    choice = seçenek.value

    if choice == "info":
        txt = (
            "**Saki durum raporu**\n"
            f"• Chat kanalları: {', '.join(str(x) for x in CHAT_CHANNEL_IDS) if CHAT_CHANNEL_IDS else 'Ayarlanmadı'}\n"
            f"• Auto chat kanalı: {AUTO_CHAT_CHANNEL_ID_INT if AUTO_CHAT_CHANNEL_ID_INT else 'Ayarlanmadı'}\n"
            f"• Sahip adı: {OWNER_NAME}\n"
            "• Öğrenme tipi: mesaj hafızası + kullanıcı tercih notları\n"
            "• Provider sırası: Groq → DeepSeek → OpenAI"
        )
        await interaction.response.send_message(txt, ephemeral=True)
        return

    if choice == "profile":
        profile = get_profile(interaction.user.id)
        txt = profile_to_text(profile)
        await interaction.response.send_message(f"**Sende kayıtlı notlarım:**\n{txt}", ephemeral=True)
        return

    if choice == "reset_me":
        clear_user_profile(interaction.user.id)
        await interaction.response.send_message("Tamam, senden tuttuğum profil notlarını sildim.", ephemeral=True)
        return

    if choice == "reset_channel":
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Bunu yapmak için **Kanalları Yönet** yetkisi lazım.", ephemeral=True)
            return

        if interaction.channel:
            clear_channel_memory(interaction.channel.id)
            await interaction.response.send_message("Bu kanalın sohbet hafızasını sildim.", ephemeral=True)
        else:
            await interaction.response.send_message("Kanal bulunamadı.", ephemeral=True)
        return

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN yok. Render Environment kısmını kontrol et.")
    if not GROQ_API_KEY and not DEEPSEEK_API_KEY and not OPENAI_API_KEY:
        raise ValueError("En az 1 AI key lazım: GROQ_API_KEY / DEEPSEEK_API_KEY / OPENAI_API_KEY")

    keep_alive()
    bot.run(DISCORD_TOKEN)
