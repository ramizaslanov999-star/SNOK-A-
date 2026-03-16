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
AUTO_CHAT_HOURS = int(os.getenv("AUTO_CHAT_HOURS", "6"))
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

GREETINGS = {"selam", "merhaba", "naber", "nasılsın", "nasilsin", "iyi misin", "hello", "hi"}
SHORT_QA = {
    "nasılsın": "İyiyim, sen nasılsın?",
    "nasilsin": "İyiyim, sen nasılsın?",
    "naber": "Takılıyorum işte, sende durumlar nasıl?",
    "merhaba": "Merhaba~ Nasılsın?",
    "selam": "Selam~ Bugün ne konuşuyoruz?"
}

ANIME_LIST = [
    ("Berserk 1997", "Karanlık atmosfer ve ağır hikâye için çok iyi gider."),
    ("Claymore", "Berserk sevene yakın gelen karanlık bir hava verir."),
    ("Vinland Saga", "Ağır karakter gelişimi ve sert dünya istiyorsan sağlamdır."),
    ("Attack on Titan", "Gerilim, savaş ve büyük hikâye isteyenlere iyi gider."),
    ("Dororo", "Karanlık ama duygulu bir yolculuk istiyorsan güzel seçim."),
    ("Devilman Crybaby", "Sert, karanlık ve rahatsız edici güçlü bir enerji verir."),
    ("Goblin Slayer", "Koyu fantezi ve acımasız dünya seviyorsan bakılır."),
    ("Hellsing Ultimate", "Karanlık aksiyon ve güçlü karizma arıyorsan çok iyi."),
    ("Parasyte", "Psikolojik gerilim ve vahşet tarafı hoşuna gidebilir."),
    ("86", "Savaş ve dram tarafı sağlamdır."),
]

WAIFU_ARCHETYPES = [
    "cool ve sessiz tip",
    "tatlı ama hafif yaramaz tip",
    "gamer girl tipi",
    "alaycı ama sevecen tip",
    "utangaç ama sadık tip",
    "zeki senpai tipi",
]

# =========================================================
# DATABASE
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
        content[:1200],
        datetime.now(timezone.utc).isoformat()
    ))
    conn.commit()
    conn.close()

def get_recent_channel_messages(channel_id: int, limit: int = 8) -> List[sqlite3.Row]:
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
# LEARNING
# =========================================================
def add_unique(items: List[str], value: str, limit: int = 8):
    value = value.strip().lower()
    if not value:
        return
    if value not in items:
        items.append(value)
    while len(items) > limit:
        items.pop(0)

def clean_fact_text(text: str) -> str:
    text = re.sub(r"[^\w\sçğıöşüÇĞİÖŞÜ-]", "", text).strip()
    return text[:50]

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
    ]

    for pattern, bucket in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            fact = clean_fact_text(m.group(1))
            if fact:
                add_unique(profile[bucket], fact)

    return profile

def profile_to_text(profile: Dict[str, Any]) -> str:
    parts = []
    if profile.get("likes"):
        parts.append("Sevdiği şeyler: " + ", ".join(profile["likes"][:5]))
    if profile.get("favorite_anime"):
        parts.append("Anime tercihleri: " + ", ".join(profile["favorite_anime"][:4]))
    if profile.get("favorite_games"):
        parts.append("Oyun tercihleri: " + ", ".join(profile["favorite_games"][:4]))
    return "\n".join(parts) if parts else "Henüz kayıtlı bilgi yok."

def recent_context_to_text(channel_id: int, limit: int = 6) -> str:
    rows = get_recent_channel_messages(channel_id, limit=limit)
    if not rows:
        return "Henüz kayıt yok."
    lines = []
    for row in rows:
        lines.append(f'{row["username"]}: {row["content"]}')
    return "\n".join(lines)

# =========================================================
# RESPONSE CLEANUP
# =========================================================
def cleanup_ai_response(text: str, username: str) -> str:
    if not text:
        return "Saki şu an biraz uykulu... birazdan tekrar yaz~"

    text = text.replace("Hikari", "Saki")
    text = text.replace("Sankaso No Kizuna", username)
    text = text.replace("Seni 147", "Seni")
    text = text.replace("ID", "")
    text = text.replace("Ben Hikari", "Ben Saki")

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    cleaned = []
    seen = set()

    banned_parts = [
        "türkçede ne konuşuyoruz",
        "sankaso no kizuna olarak tanıyorum",
        "ben hikari",
        "i am hikari",
        "i'm hikari"
    ]

    for line in lines:
        low = line.lower()

        if any(bad in low for bad in banned_parts):
            continue

        low = re.sub(r"\d{6,}", "", low).strip()
        key = low
        if key in seen or not key:
            continue
        seen.add(key)
        cleaned.append(line)

    if not cleaned:
        cleaned = [text.strip()]

    result = " ".join(cleaned[:2]).strip()
    result = re.sub(r"\s+", " ", result).strip()
    result = re.sub(r"([!?.,])\1+", r"\1", result)

    if len(result) > 300:
        result = result[:300].rsplit(" ", 1)[0]

    if not result:
        result = "Saki burada, tekrar yaz bakalım~"

    return result

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
        "temperature": 0.7,
        "max_tokens": 180
    }

    try:
        r = requests.post(base_url, headers=headers, json=payload, timeout=40)
        print(f"[AI] {model} status:", r.status_code)
        print(f"[AI] {model} body:", r.text[:350])

        if r.status_code != 200:
            return None

        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[AI] {model} error:", e)
        return None

def ask_ai(messages: List[Dict[str, str]], username: str) -> str:
    providers = []

    if GROQ_API_KEY:
        providers.append((
            "https://api.groq.com/openai/v1/chat/completions",
            "llama-3.1-8b-instant",
            GROQ_API_KEY
        ))

    if DEEPSEEK_API_KEY:
        providers.append((
            "https://api.deepseek.com/chat/completions",
            "deepseek-chat",
            DEEPSEEK_API_KEY
        ))

    if OPENAI_API_KEY:
        providers.append((
            "https://api.openai.com/v1/chat/completions",
            "gpt-4o-mini",
            OPENAI_API_KEY
        ))

    for url, model, key in providers:
        reply = call_openai_compatible(url, key, model, messages)
        if reply:
            return cleanup_ai_response(reply, username)

    return "Saki şu an biraz uykulu... birazdan tekrar yaz~"

def build_system_prompt(
    guild_name: str,
    user_display_name: str,
    profile_text: str
) -> str:
    return f"""
Senin adın Saki.
Sen {guild_name} sunucusunun anime/chibi maskotusun.
Her zaman Türkçe konuşursun.
Kısa, doğal ve net cevap verirsin.
Tek mesajda tek cevap verirsin.
Aynı cümleyi tekrar etmezsin.
Kullanıcıya asla sayı, ID, etiket, sunucu adı veya garip kimlikler yakıştırmazsın.
Kullanıcının adını biliyorsan sadece adıyla hitap edersin: {user_display_name}
Gereksiz şiirsel veya robot gibi konuşmazsın.
Maksimum 2-3 kısa cümle yazarsın.
Anime, manga, oyun ve sunucu sohbetlerini seversin.
Sorulan şeye direkt cevap verirsin.
Asla "Ben Hikari" demezsin.
Asla "Sankaso No Kizuna olarak tanıyorum" gibi saçma cümle kurmazsın.

Kullanıcı hakkında bildiklerin:
{profile_text}
""".strip()

def build_chat_messages(
    guild_name: str,
    user_display_name: str,
    user_input: str,
    profile_text: str,
    recent_context_text: str
) -> List[Dict[str, str]]:
    system = build_system_prompt(guild_name, user_display_name, profile_text)

    user_content = f"""
Son konuşmalar:
{recent_context_text}

Yeni kullanıcı mesajı:
{user_input}
""".strip()

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content}
    ]

# =========================================================
# WEB
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
# BOT
# =========================================================
class SakiBot(commands.Bot):
    async def setup_hook(self):
        init_db()

        try:
            if SYNC_GUILD_ID_INT:
                guild = discord.Object(id=SYNC_GUILD_ID_INT)
                self.tree.clear_commands(guild=guild)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"[Slash] Guild sync tamam: {SYNC_GUILD_ID_INT}")
            else:
                await self.tree.sync()
                print("[Slash] Global sync tamam")
        except Exception as e:
            print("[Slash] Sync error:", e)

        if not auto_chat_loop.is_running() and AUTO_CHAT_CHANNEL_ID_INT:
            auto_chat_loop.start()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True

bot = SakiBot(command_prefix="!", intents=intents)

# =========================================================
# AUTO CHAT
# =========================================================
@tasks.loop(hours=1)
async def auto_chat_loop():
    await bot.wait_until_ready()

    if not AUTO_CHAT_CHANNEL_ID_INT:
        return

    now_hour = datetime.now().hour
    if AUTO_CHAT_HOURS > 1 and now_hour % AUTO_CHAT_HOURS != 0:
        return

    channel = bot.get_channel(AUTO_CHAT_CHANNEL_ID_INT)
    if not channel or not isinstance(channel, discord.TextChannel):
        return

    prompts = [
        "Bugün izlediğiniz en iyi anime neydi?",
        "Şu an herkes en çok hangi oyuna sarıyor?",
        "Karanlık anime mi daha iyi, komedi mi?",
        "Şu an tek bir anime önerecek olsanız ne derdiniz?",
    ]
    await channel.send(random.choice(prompts))

# =========================================================
# EVENTS
# =========================================================
@bot.event
async def on_ready():
    print(f"✅ Bot aktif: {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    content = message.content.strip()
    if not content:
        return

    await bot.process_commands(message)

    if not content.startswith("/"):
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

    mentioned = bot.user in message.mentions if bot.user else False
    is_chat_channel = message.channel.id in CHAT_CHANNEL_IDS if CHAT_CHANNEL_IDS else False

    if not mentioned and not is_chat_channel:
        return

    if content.startswith("/"):
        return

    clean_content = content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "")
        clean_content = clean_content.replace(f"<@!{bot.user.id}>", "")
    clean_content = clean_content.strip()

    if not clean_content:
        clean_content = "selam"

    lower = clean_content.lower()

    if lower in SHORT_QA:
        await message.channel.send(SHORT_QA[lower])
        return

    if "kaç yaş" in lower or "kac yas" in lower:
        await message.channel.send("Gerçek bir yaşım yok, ben sunucunun maskotu Saki'yim~")
        return

    if "anime öner" in lower or "anime oner" in lower:
        profile = get_profile(message.author.id)
        likes = " ".join(profile.get("likes", []) + profile.get("favorite_anime", []))
        picks = []

        if "berserk" in likes or "berserk" in lower:
            picks = [
                ("Claymore", "Berserk sevene en yakın hislerden birini verir."),
                ("Vinland Saga", "Ağır hikâye ve güçlü karakter gelişimi var."),
                ("Hellsing Ultimate", "Karanlık ve karizmatik aksiyon arıyorsan iyi gider."),
            ]
        else:
            picks = random.sample(ANIME_LIST, 3)

        text = "\n".join([f"• **{name}** — {desc}" for name, desc in picks])
        await message.channel.send(f"Sana şunları öneririm:\n{text}")
        return

    guild_name = message.guild.name
    profile = get_profile(message.author.id)
    profile_text = profile_to_text(profile)
    recent_text = recent_context_to_text(message.channel.id, limit=6)

    ai_messages = build_chat_messages(
        guild_name=guild_name,
        user_display_name=message.author.display_name,
        user_input=clean_content,
        profile_text=profile_text,
        recent_context_text=recent_text
    )

    async with message.channel.typing():
        reply = await asyncio.to_thread(ask_ai, ai_messages, message.author.display_name)

    await message.channel.send(reply[:1900])

# =========================================================
# SLASH COMMANDS
# =========================================================
@bot.tree.command(name="anime", description="Saki'den anime önerisi al.")
@app_commands.describe(istek="Örn: karanlık savaş animesi")
async def anime_command(interaction: discord.Interaction, istek: Optional[str] = None):
    if interaction.guild and SYNC_GUILD_ID_INT and interaction.guild.id != SYNC_GUILD_ID_INT:
        await interaction.response.send_message("Bu komut şu an sadece ayarlı test sunucusunda aktif.", ephemeral=True)
        return

    await interaction.response.defer(thinking=True)

    if not istek:
        picks = random.sample(ANIME_LIST, 5)
        text = "\n".join([f"• **{name}** — {desc}" for name, desc in picks])
        await interaction.followup.send(f"Saki'den anime paketi:\n\n{text}")
        return

    istek_low = istek.lower()
    if "karanlık" in istek_low or "savaş" in istek_low or "berserk" in istek_low:
        picks = [
            ("Claymore", "Karanlık fantezi havası güzel tutuyor."),
            ("Vinland Saga", "Savaş ve ağır hikâye tarafı güçlü."),
            ("Hellsing Ultimate", "Sert ve karizmatik aksiyon veriyor."),
            ("Dororo", "Karanlık yolculuk ve duygusal taraf dengeli."),
            ("Attack on Titan", "Büyük tehdit ve savaş hissi güçlü."),
        ]
    else:
        picks = random.sample(ANIME_LIST, 5)

    text = "\n".join([f"• **{name}** — {desc}" for name, desc in picks])
    await interaction.followup.send(text)

@bot.tree.command(name="waifu", description="Saki'den eğlencelik waifu yorumu al.")
@app_commands.describe(mod="Örn: cool, tatlı, gamer")
async def waifu_command(interaction: discord.Interaction, mod: Optional[str] = None):
    if interaction.guild and SYNC_GUILD_ID_INT and interaction.guild.id != SYNC_GUILD_ID_INT:
        await interaction.response.send_message("Bu komut şu an sadece ayarlı test sunucusunda aktif.", ephemeral=True)
        return

    if not mod:
        await interaction.response.send_message(f"Saki'nin bugünkü seçimi: **{random.choice(WAIFU_ARCHETYPES)}**")
        return

    mod_low = mod.lower()
    if "cool" in mod_low:
        result = "Bence sana **cool ve sessiz tip** gider. Ağır bir karizması olur."
    elif "tatlı" in mod_low:
        result = "Sana **tatlı ama hafif yaramaz tip** daha çok uyar."
    elif "gamer" in mod_low:
        result = "Net şekilde **gamer girl tipi** derim."
    else:
        result = f"Bence sana **{random.choice(WAIFU_ARCHETYPES)}** gider."

    await interaction.response.send_message(result)

@bot.tree.command(name="saki", description="Saki ayarları ve hafıza işlemleri.")
@app_commands.describe(seçenek="bilgi / profilim / profilimi_sıfırla / kanal_hafızasını_sıfırla")
@app_commands.choices(seçenek=[
    app_commands.Choice(name="bilgi", value="info"),
    app_commands.Choice(name="profilim", value="profile"),
    app_commands.Choice(name="profilimi_sıfırla", value="reset_me"),
    app_commands.Choice(name="kanal_hafızasını_sıfırla", value="reset_channel"),
])
async def saki_command(interaction: discord.Interaction, seçenek: app_commands.Choice[str]):
    if interaction.guild and SYNC_GUILD_ID_INT and interaction.guild.id != SYNC_GUILD_ID_INT:
        await interaction.response.send_message("Bu komut şu an sadece ayarlı test sunucusunda aktif.", ephemeral=True)
        return

    choice = seçenek.value

    if choice == "info":
        txt = (
            "**Saki durum raporu**\n"
            f"• Chat kanalları: {', '.join(str(x) for x in CHAT_CHANNEL_IDS) if CHAT_CHANNEL_IDS else 'Ayarlanmadı'}\n"
            f"• Auto chat kanalı: {AUTO_CHAT_CHANNEL_ID_INT if AUTO_CHAT_CHANNEL_ID_INT else 'Ayarlanmadı'}\n"
            f"• Sahip adı: {OWNER_NAME}\n"
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
        await interaction.response.send_message("Senden tuttuğum profil notlarını sildim.", ephemeral=True)
        return

    if choice == "reset_channel":
        if not interaction.user.guild_permissions.manage_channels:
            await interaction.response.send_message("Bunu yapmak için **Kanalları Yönet** yetkisi lazım.", ephemeral=True)
            return

        if interaction.channel:
            clear_channel_memory(interaction.channel.id)
            await interaction.response.send_message("Bu kanalın hafızasını sildim.", ephemeral=True)
        else:
            await interaction.response.send_message("Kanal bulunamadı.", ephemeral=True)

# =========================================================
# MAIN
# =========================================================
if __name__ == "__main__":
    if not DISCORD_TOKEN:
        raise ValueError("DISCORD_TOKEN yok.")
    if not GROQ_API_KEY and not DEEPSEEK_API_KEY and not OPENAI_API_KEY:
        raise ValueError("En az 1 AI key lazım.")

    keep_alive()
    bot.run(DISCORD_TOKEN)
