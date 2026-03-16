import os
import re
import json
import random
import sqlite3
import asyncio
from datetime import datetime, timezone, timedelta
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
WARN_LOG_CHANNEL_ID = int(os.getenv("WARN_LOG_CHANNEL_ID", "1471826660025176297"))
LEVEL_LOG_CHANNEL_ID = int(os.getenv("LEVEL_LOG_CHANNEL_ID", "1471137929886695547"))
OWNER_NAME = os.getenv("OWNER_NAME", "Sunucu Sahibi")
DB_PATH = os.getenv("DB_PATH", "saki_memory.db")

SYNC_GUILD_ID_INT = int(SYNC_GUILD_ID) if SYNC_GUILD_ID and SYNC_GUILD_ID.isdigit() else None

# =========================================================
# CONFIG
# =========================================================
DEFAULT_BAD_WORDS = [
    "amk", "aq", "amq", "orospu", "orosbu", "piç", "pic", "sik", "sikerim",
    "siktir", "yarrak", "yarraq", "göt", "got", "bok", "ibne", "puşt", "pust"
]

ANIME_LIST = [
    ("Berserk 1997", "Karanlık ve ağır hikâye seviyorsan çok iyi gider."),
    ("Claymore", "Berserk sevene yakın gelen sert bir hava verir."),
    ("Vinland Saga", "Ağır karakter gelişimi ve sert dünya arıyorsan sağlam."),
    ("Hellsing Ultimate", "Karizma ve karanlık aksiyon tarafı çok güçlü."),
    ("Dororo", "Karanlık ama duygulu bir yolculuk istiyorsan iyi seçim."),
    ("Attack on Titan", "Gerilim ve savaş tarafı güçlü bir seri."),
    ("86", "Savaş, dram ve atmosfer dengesi güzel."),
    ("Parasyte", "Rahatsız edici ama sürükleyici bir yapı seviyorsan iyi gider."),
    ("Devilman Crybaby", "Sert ve kaotik bir enerji veriyor."),
    ("Goblin Slayer", "Koyu fantezi ve acımasız dünya seviyorsan bakılır."),
]

WAIFU_ARCHETYPES = [
    "cool ve sessiz tip",
    "tatlı ama hafif yaramaz tip",
    "alaycı ama sevecen tip",
    "gamer girl tipi",
    "utangaç ama sadık tip",
    "zeki senpai tipi",
]

SHORT_QA = {
    "selam": "Selam~ Nasılsın?",
    "merhaba": "Merhaba~ Nasılsın?",
    "nasılsın": "İyiyim, sen nasılsın?",
    "nasilsin": "İyiyim, sen nasılsın?",
    "naber": "Takılıyorum işte, sende durumlar nasıl?",
    "iyi": "Güzelmiş, böyle devam~",
    "cok iyi": "Ohh, bunu duymak iyi geldi.",
    "çok iyi": "Ohh, bunu duymak iyi geldi.",
    "guzelmis": "Beğenmene sevindim~",
    "güzelmiş": "Beğenmene sevindim~",
}

# =========================================================
# HELPERS
# =========================================================
def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def sanitize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

def normalize_content(text: str) -> str:
    return sanitize_text(text.lower())

def contains_bad_word(text: str) -> bool:
    normalized = normalize_content(text)
    for bad in DEFAULT_BAD_WORDS:
        if bad in normalized:
            return True
    return False

def format_dt(dt: datetime) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")

def parse_duration(duration: str) -> Optional[timedelta]:
    """
    Örnek:
    30m
    2h
    7d
    1d12h
    2h30m
    """
    if not duration:
        return None

    matches = re.findall(r"(\d+)([mhd])", duration.lower())
    if not matches:
        return None

    total = timedelta()
    for value, unit in matches:
        value = int(value)
        if unit == "m":
            total += timedelta(minutes=value)
        elif unit == "h":
            total += timedelta(hours=value)
        elif unit == "d":
            total += timedelta(days=value)

    return total if total.total_seconds() > 0 else None

def compute_text_level(text_xp: int) -> int:
    return max(1, text_xp // 25 + 1)

def compute_voice_level(voice_minutes: int) -> int:
    return max(1, voice_minutes // 60 + 1)

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
            text_xp INTEGER DEFAULT 0,
            text_level INTEGER DEFAULT 1,
            voice_minutes INTEGER DEFAULT 0,
            voice_level INTEGER DEFAULT 1,
            penalty_points INTEGER DEFAULT 0,
            updated_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT,
            user_id TEXT,
            moderator TEXT,
            reason TEXT,
            created_at TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS timed_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT,
            user_id TEXT,
            role_id TEXT,
            expires_at TEXT,
            reason TEXT,
            created_at TEXT
        )
    """)

    conn.commit()
    conn.close()

def ensure_profile(user_id: int, username: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM profiles WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()

    if not row:
        cur.execute("""
            INSERT INTO profiles (
                user_id, username, facts_json, text_xp, text_level,
                voice_minutes, voice_level, penalty_points, updated_at
            )
            VALUES (?, ?, ?, 0, 1, 0, 1, 0, ?)
        """, (
            str(user_id),
            username,
            json.dumps({"likes": [], "favorite_anime": [], "favorite_games": [], "notes": []}, ensure_ascii=False),
            now_utc().isoformat()
        ))
    else:
        cur.execute("""
            UPDATE profiles
            SET username = ?, updated_at = ?
            WHERE user_id = ?
        """, (username, now_utc().isoformat(), str(user_id)))

    conn.commit()
    conn.close()

def get_profile(user_id: int) -> Dict[str, Any]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM profiles WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()
    conn.close()

    if not row:
        return {
            "likes": [], "favorite_anime": [], "favorite_games": [], "notes": [],
            "text_xp": 0, "text_level": 1, "voice_minutes": 0, "voice_level": 1,
            "penalty_points": 0
        }

    try:
        facts = json.loads(row["facts_json"]) if row["facts_json"] else {}
    except Exception:
        facts = {}

    return {
        "likes": facts.get("likes", []),
        "favorite_anime": facts.get("favorite_anime", []),
        "favorite_games": facts.get("favorite_games", []),
        "notes": facts.get("notes", []),
        "text_xp": row["text_xp"] or 0,
        "text_level": row["text_level"] or 1,
        "voice_minutes": row["voice_minutes"] or 0,
        "voice_level": row["voice_level"] or 1,
        "penalty_points": row["penalty_points"] or 0
    }

def upsert_facts(user_id: int, username: str, facts: Dict[str, Any]):
    ensure_profile(user_id, username)
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        UPDATE profiles
        SET facts_json = ?, username = ?, updated_at = ?
        WHERE user_id = ?
    """, (
        json.dumps(facts, ensure_ascii=False),
        username,
        now_utc().isoformat(),
        str(user_id)
    ))
    conn.commit()
    conn.close()

def add_text_xp(user_id: int, username: str, amount: int = 1):
    ensure_profile(user_id, username)
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT text_xp FROM profiles WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()
    current_xp = row["text_xp"] if row else 0
    new_xp = current_xp + amount
    new_level = compute_text_level(new_xp)

    cur.execute("""
        UPDATE profiles
        SET text_xp = ?, text_level = ?, username = ?, updated_at = ?
        WHERE user_id = ?
    """, (new_xp, new_level, username, now_utc().isoformat(), str(user_id)))

    conn.commit()
    conn.close()

def add_voice_minutes(user_id: int, username: str, minutes: int):
    if minutes <= 0:
        return

    ensure_profile(user_id, username)
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT voice_minutes FROM profiles WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()
    current = row["voice_minutes"] if row else 0
    new_total = current + minutes
    new_level = compute_voice_level(new_total)

    cur.execute("""
        UPDATE profiles
        SET voice_minutes = ?, voice_level = ?, username = ?, updated_at = ?
        WHERE user_id = ?
    """, (new_total, new_level, username, now_utc().isoformat(), str(user_id)))

    conn.commit()
    conn.close()

def set_levels(user_id: int, username: str, text_level: Optional[int] = None, voice_level: Optional[int] = None):
    ensure_profile(user_id, username)
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT text_level, voice_level, text_xp, voice_minutes
        FROM profiles
        WHERE user_id = ?
    """, (str(user_id),))
    row = cur.fetchone()

    current_text_level = row["text_level"] if row else 1
    current_voice_level = row["voice_level"] if row else 1

    new_text_level = max(1, text_level if text_level is not None else current_text_level)
    new_voice_level = max(1, voice_level if voice_level is not None else current_voice_level)

    text_xp = max(0, (new_text_level - 1) * 25)
    voice_minutes = max(0, (new_voice_level - 1) * 60)

    cur.execute("""
        UPDATE profiles
        SET text_xp = ?, text_level = ?, voice_minutes = ?, voice_level = ?, username = ?, updated_at = ?
        WHERE user_id = ?
    """, (
        text_xp, new_text_level, voice_minutes, new_voice_level,
        username, now_utc().isoformat(), str(user_id)
    ))
    conn.commit()
    conn.close()

def add_penalty_points(user_id: int, username: str, amount: int):
    ensure_profile(user_id, username)
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("SELECT penalty_points FROM profiles WHERE user_id = ?", (str(user_id),))
    row = cur.fetchone()
    current = row["penalty_points"] if row else 0
    new_total = max(0, current + amount)

    cur.execute("""
        UPDATE profiles
        SET penalty_points = ?, username = ?, updated_at = ?
        WHERE user_id = ?
    """, (new_total, username, now_utc().isoformat(), str(user_id)))

    conn.commit()
    conn.close()

def save_warning(guild_id: int, user_id: int, moderator: str, reason: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO warnings (guild_id, user_id, moderator, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (
        str(guild_id),
        str(user_id),
        moderator,
        reason,
        now_utc().isoformat()
    ))
    conn.commit()
    conn.close()

def get_warnings(user_id: int, limit: int = 10) -> List[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT reason, moderator, created_at
        FROM warnings
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (str(user_id), limit))
    rows = cur.fetchall()
    conn.close()
    return rows

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
        now_utc().isoformat()
    ))
    conn.commit()
    conn.close()

def get_recent_channel_messages(channel_id: int, limit: int = 6) -> List[sqlite3.Row]:
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

def add_timed_role(guild_id: int, user_id: int, role_id: int, expires_at: datetime, reason: str):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO timed_roles (guild_id, user_id, role_id, expires_at, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(guild_id),
        str(user_id),
        str(role_id),
        expires_at.isoformat(),
        reason,
        now_utc().isoformat()
    ))
    conn.commit()
    conn.close()

def remove_timed_role_entry(user_id: int, role_id: int):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        DELETE FROM timed_roles
        WHERE user_id = ? AND role_id = ?
    """, (str(user_id), str(role_id)))
    conn.commit()
    conn.close()

def get_all_timed_roles() -> List[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, guild_id, user_id, role_id, expires_at, reason
        FROM timed_roles
        ORDER BY id ASC
    """)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_member_timed_roles(user_id: int) -> List[sqlite3.Row]:
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT role_id, expires_at, reason
        FROM timed_roles
        WHERE user_id = ?
        ORDER BY id DESC
    """, (str(user_id),))
    rows = cur.fetchall()
    conn.close()
    return rows

# =========================================================
# MEMORY / LEARNING
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
    return text[:60]

def learn_from_message(content: str, old_profile: Dict[str, Any]) -> Dict[str, Any]:
    new_profile = {
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
                add_unique(new_profile[bucket], fact)

    return new_profile

def profile_to_text(member: discord.Member, profile: Dict[str, Any]) -> str:
    lines = [
        f"**Üye:** {member.mention}",
        f"**Text Level:** {profile['text_level']} ({profile['text_xp']} xp)",
        f"**Voice Level:** {profile['voice_level']} ({profile['voice_minutes']} dk)",
        f"**Ceza Puanı:** {profile['penalty_points']}",
    ]

    if profile.get("likes"):
        lines.append("**Sevdiği şeyler:** " + ", ".join(profile["likes"][:5]))
    if profile.get("favorite_anime"):
        lines.append("**Anime tercihleri:** " + ", ".join(profile["favorite_anime"][:4]))
    if profile.get("favorite_games"):
        lines.append("**Oyun tercihleri:** " + ", ".join(profile["favorite_games"][:4]))

    return "\n".join(lines)

def recent_context_to_text(channel_id: int) -> str:
    rows = get_recent_channel_messages(channel_id, 5)
    if not rows:
        return "Henüz kayıt yok."
    return "\n".join([f"{r['username']}: {r['content']}" for r in rows])

# =========================================================
# LEVEL LOG PARSER
# =========================================================
def extract_text_from_message_and_embeds(message: discord.Message) -> str:
    parts = []
    if message.content:
        parts.append(message.content)

    for embed in message.embeds:
        if embed.title:
            parts.append(embed.title)
        if embed.description:
            parts.append(embed.description)
        for field in embed.fields:
            parts.append(field.name or "")
            parts.append(field.value or "")

    return "\n".join(parts)

def parse_level_update(message: discord.Message) -> Optional[dict]:
    """
    Level bot mesajlarından şunları çekmeye çalışır:
    - kullanıcı id
    - text level
    - voice level

    Desteklenen kaba örnekler:
    @uye text level 5 oldu
    @uye sohbet seviyesi 7
    @uye voice level 3
    @uye sesli seviyesi 4
    """
    raw = extract_text_from_message_and_embeds(message)
    if not raw.strip():
        return None

    user_id = None
    if message.mentions:
        user_id = message.mentions[0].id
    else:
        m_user = re.search(r"<@!?(\d+)>", raw)
        if m_user:
            user_id = int(m_user.group(1))

    if not user_id:
        return None

    text_level = None
    voice_level = None

    raw_low = raw.lower()

    text_patterns = [
        r"(?:text|mesaj|yazı|yazi|sohbet|chat)\s*(?:seviyesi|seviye|level|lvl)?\s*(\d+)",
        r"(\d+)\s*(?:text|mesaj|yazı|yazi|sohbet|chat)\s*(?:seviyesi|seviye|level|lvl)",
    ]
    voice_patterns = [
        r"(?:voice|sesli|səsli)\s*(?:seviyesi|seviye|level|lvl)?\s*(\d+)",
        r"(\d+)\s*(?:voice|sesli|səsli)\s*(?:seviyesi|seviye|level|lvl)",
    ]

    for pat in text_patterns:
        m = re.search(pat, raw_low)
        if m:
            text_level = int(m.group(1))
            break

    for pat in voice_patterns:
        m = re.search(pat, raw_low)
        if m:
            voice_level = int(m.group(1))
            break

    # Eğer hiç ayrım bulamadıysa ama seviye/level geçtiyse tek sayıyı text say
    if text_level is None and voice_level is None:
        if any(k in raw_low for k in ["seviye", "seviyesi", "level", "lvl"]):
            m_num = re.search(r"\b(\d{1,3})\b", raw_low)
            if m_num:
                text_level = int(m_num.group(1))

    if text_level is None and voice_level is None:
        return None

    return {
        "user_id": user_id,
        "text_level": text_level,
        "voice_level": voice_level
    }

# =========================================================
# AI
# =========================================================
def cleanup_ai_response(text: str, username: str) -> str:
    if not text:
        return "Şu an biraz yoğunlaştım, tekrar yaz bakalım~"

    text = text.replace("Hikari", "Saki")
    text = text.replace("Ben Hikari", "Ben Saki")
    text = text.replace("Sankaso No Kizuna", username)
    text = re.sub(r"\b\d{6,}\b", "", text)

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    unique_lines = []
    seen = set()

    banned_snippets = [
        "ben hikari",
        "türkçede ne konuşuyoruz",
        "sankaso no kizuna olarak tanıyorum",
        "kimlik",
        "id"
    ]

    for line in lines:
        lowered = line.lower()
        if any(b in lowered for b in banned_snippets):
            continue
        key = re.sub(r"\s+", " ", lowered).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_lines.append(line)

    if not unique_lines:
        result = sanitize_text(text)
    else:
        result = " ".join(unique_lines[:2])

    result = sanitize_text(result)

    if len(result) > 220:
        result = result[:220].rsplit(" ", 1)[0]

    for bad in DEFAULT_BAD_WORDS:
        result = re.sub(re.escape(bad), "***", result, flags=re.IGNORECASE)

    if not result:
        result = "Tam anlayamadım, bir daha kısa şekilde yazsana~"

    return result

def build_system_prompt(guild_name: str, username: str, profile: Dict[str, Any]) -> str:
    likes = ", ".join(profile.get("likes", [])[:4]) or "bilinmiyor"
    fav_anime = ", ".join(profile.get("favorite_anime", [])[:4]) or "bilinmiyor"
    fav_games = ", ".join(profile.get("favorite_games", [])[:4]) or "bilinmiyor"

    return f"""
Senin adın Saki.
Sen {guild_name} sunucusunun tatlı ama zeki maskotusun.
Her zaman Türkçe konuşursun.
Kısa, doğal, samimi ve temiz konuşursun.
Asla küfür etmezsin.
Asla aynı cümleyi tekrar etmezsin.
Asla kullanıcıya sayı, ID, garip hitap veya saçma isim takmazsın.
Kullanıcının adı: {username}
Bu kullanıcı hakkında bildiklerin:
- Sevdiği şeyler: {likes}
- Favori anime: {fav_anime}
- Favori oyun: {fav_games}

Kurallar:
- En fazla 2 kısa cümle yaz.
- Doğrudan soruya cevap ver.
- Gereksiz selamlama tekrarları yapma.
- Aşırı resmî olma.
- Tatlı ama abartısız ol.
- Kendi karakter adın sadece Saki.
""".strip()

def call_openai_compatible(base_url: str, api_key: str, model: str, messages: List[Dict[str, str]]) -> Optional[str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.6,
        "max_tokens": 160
    }

    try:
        r = requests.post(base_url, headers=headers, json=payload, timeout=40)
        print(f"[AI] {model} status: {r.status_code}")
        print(f"[AI] {model} body: {r.text[:300]}")
        if r.status_code != 200:
            return None
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[AI] {model} error: {e}")
        return None

def ask_ai(guild_name: str, username: str, user_input: str, profile: Dict[str, Any], recent_text: str) -> str:
    messages = [
        {"role": "system", "content": build_system_prompt(guild_name, username, profile)},
        {"role": "user", "content": f"Son konuşmalar:\n{recent_text}\n\nKullanıcı mesajı:\n{user_input}"}
    ]

    providers = []
    if GROQ_API_KEY:
        providers.append(("https://api.groq.com/openai/v1/chat/completions", "llama-3.1-8b-instant", GROQ_API_KEY))
    if DEEPSEEK_API_KEY:
        providers.append(("https://api.deepseek.com/chat/completions", "deepseek-chat", DEEPSEEK_API_KEY))
    if OPENAI_API_KEY:
        providers.append(("https://api.openai.com/v1/chat/completions", "gpt-4o-mini", OPENAI_API_KEY))

    for url, model, key in providers:
        reply = call_openai_compatible(url, key, model, messages)
        if reply:
            return cleanup_ai_response(reply, username)

    return "Şu an biraz yoğunlaştım, birazdan tekrar yaz olur mu~"

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
voice_sessions: Dict[int, datetime] = {}

class SakiBot(commands.Bot):
    async def setup_hook(self):
        init_db()
        try:
            if SYNC_GUILD_ID_INT:
                guild = discord.Object(id=SYNC_GUILD_ID_INT)
                await self.tree.sync(guild=guild)
                print(f"[Slash] Guild sync tamam: {SYNC_GUILD_ID_INT}")
            else:
                await self.tree.sync()
                print("[Slash] Global sync tamam")
        except Exception as e:
            print("[Slash] Sync error:", e)

        if not timed_role_loop.is_running():
            timed_role_loop.start()

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.voice_states = True

bot = SakiBot(command_prefix="!", intents=intents)

# =========================================================
# MODERATION
# =========================================================
async def send_warn_log(guild: discord.Guild, member: discord.Member, reason: str):
    channel = guild.get_channel(WARN_LOG_CHANNEL_ID)
    if channel:
        try:
            await channel.send(f"-warn {member.mention} {reason}")
        except Exception as e:
            print("Warn log error:", e)

async def moderate_message(message: discord.Message) -> bool:
    if contains_bad_word(message.content):
        try:
            await message.delete()
        except Exception as e:
            print("Delete message error:", e)

        add_penalty_points(message.author.id, message.author.display_name, 1)
        save_warning(message.guild.id, message.author.id, "Saki", "Küfür ettiği için")
        await send_warn_log(message.guild, message.author, "Küfür ettiği için")

        try:
            warn_msg = await message.channel.send(
                f"{message.author.mention} küfürlü mesajlar yasak. Mesajın silindi ve uyarı işlendi."
            )
            await asyncio.sleep(6)
            await warn_msg.delete()
        except Exception:
            pass

        return True

    return False

# =========================================================
# TIMED ROLE CHECKER
# =========================================================
@tasks.loop(minutes=1)
async def timed_role_loop():
    await bot.wait_until_ready()
    entries = get_all_timed_roles()
    now = now_utc()

    for entry in entries:
        try:
            expires_at = datetime.fromisoformat(entry["expires_at"])
        except Exception:
            continue

        if expires_at > now:
            continue

        guild = bot.get_guild(int(entry["guild_id"]))
        if not guild:
            remove_timed_role_entry(int(entry["user_id"]), int(entry["role_id"]))
            continue

        member = guild.get_member(int(entry["user_id"]))
        role = guild.get_role(int(entry["role_id"]))

        if member and role:
            try:
                await member.remove_roles(role, reason="Timed role süresi doldu")
            except Exception as e:
                print("Timed role remove error:", e)

        remove_timed_role_entry(int(entry["user_id"]), int(entry["role_id"]))

# =========================================================
# EVENTS
# =========================================================
@bot.event
async def on_ready():
    print(f"✅ Bot aktif: {bot.user}")

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    if member.bot:
        return

    now = now_utc()

    if before.channel is None and after.channel is not None:
        voice_sessions[member.id] = now
        return

    if before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
        start = voice_sessions.get(member.id)
        if start:
            minutes = int((now - start).total_seconds() // 60)
            add_voice_minutes(member.id, member.display_name, minutes)
        voice_sessions[member.id] = now
        return

    if before.channel is not None and after.channel is None:
        start = voice_sessions.pop(member.id, None)
        if start:
            minutes = int((now - start).total_seconds() // 60)
            add_voice_minutes(member.id, member.display_name, minutes)

@bot.event
async def on_message(message: discord.Message):
    if not message.guild:
        return

    # Level bot loglarını oku
    if message.author.bot and message.channel.id == LEVEL_LOG_CHANNEL_ID:
        parsed = parse_level_update(message)
        if parsed:
            member = message.guild.get_member(parsed["user_id"])
            if member:
                ensure_profile(member.id, member.display_name)
                set_levels(
                    member.id,
                    member.display_name,
                    text_level=parsed["text_level"],
                    voice_level=parsed["voice_level"]
                )
                print(
                    f"[LEVEL LOG] {member.display_name} | "
                    f"text={parsed['text_level']} voice={parsed['voice_level']}"
                )
        return

    if message.author.bot:
        return

    content = message.content.strip()
    if not content:
        return

    ensure_profile(message.author.id, message.author.display_name)

    moderated = await moderate_message(message)
    if moderated:
        return

    await bot.process_commands(message)

    if not content.startswith("/"):
        save_message(message.guild.id, message.channel.id, message.author.id, message.author.display_name, content)
        add_text_xp(message.author.id, message.author.display_name, 1)

        old_profile = get_profile(message.author.id)
        facts = {
            "likes": old_profile.get("likes", []),
            "favorite_anime": old_profile.get("favorite_anime", []),
            "favorite_games": old_profile.get("favorite_games", []),
            "notes": old_profile.get("notes", []),
        }
        new_facts = learn_from_message(content, facts)
        upsert_facts(message.author.id, message.author.display_name, new_facts)

    # Sadece mention veya reply
    mentioned = bot.user in message.mentions if bot.user else False
    replied_to_bot = False

    if message.reference and message.reference.message_id:
        try:
            ref = message.reference.resolved
            if ref is None:
                ref = await message.channel.fetch_message(message.reference.message_id)
            if ref and ref.author.id == bot.user.id:
                replied_to_bot = True
        except Exception:
            replied_to_bot = False

    if not mentioned and not replied_to_bot:
        return

    if content.startswith("/"):
        return

    clean_content = content
    if bot.user:
        clean_content = clean_content.replace(f"<@{bot.user.id}>", "")
        clean_content = clean_content.replace(f"<@!{bot.user.id}>", "")
    clean_content = sanitize_text(clean_content)

    if not clean_content:
        clean_content = "selam"

    lowered = clean_content.lower()

    if lowered in SHORT_QA:
        await message.channel.send(SHORT_QA[lowered])
        return

    if "kaç yaş" in lowered or "kac yas" in lowered:
        await message.channel.send("Gerçek bir yaşım yok, ben sunucunun maskotu Saki'yim~")
        return

    if "anime öner" in lowered or "anime oner" in lowered:
        profile = get_profile(message.author.id)
        likes_blob = " ".join(profile.get("likes", []) + profile.get("favorite_anime", []))
        if "berserk" in likes_blob.lower() or "berserk" in lowered:
            picks = [
                ("Claymore", "Berserk sevene yakın bir karanlık his veriyor."),
                ("Vinland Saga", "Ağır hikâye ve güçlü karakter gelişimi var."),
                ("Hellsing Ultimate", "Karanlık ve karizmatik aksiyon arıyorsan iyi gider."),
            ]
        else:
            picks = random.sample(ANIME_LIST, 3)

        text = "\n".join([f"• **{name}** — {desc}" for name, desc in picks])
        await message.channel.send(f"Sana şunları öneririm:\n{text}")
        return

    profile = get_profile(message.author.id)
    recent_text = recent_context_to_text(message.channel.id)

    async with message.channel.typing():
        reply = await asyncio.to_thread(
            ask_ai,
            message.guild.name,
            message.author.display_name,
            clean_content,
            profile,
            recent_text
        )

    await message.channel.send(reply[:1900])

# =========================================================
# SLASH COMMANDS
# =========================================================
@bot.tree.command(name="saki", description="Saki kendini tanıtır.")
async def saki_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "Merhaba~ Ben **Saki**. Bu sunucunun tatlı ama işini bilen maskotuyum.\n"
        "Sohbet ederim, anime öneririm, seviyeleri takip ederim ve gerektiğinde uyarı da yazarım.",
        ephemeral=True
    )

@bot.tree.command(name="anime", description="Saki'den anime önerisi al.")
@app_commands.describe(istek="Örn: karanlık savaş animesi")
async def anime_command(interaction: discord.Interaction, istek: Optional[str] = None):
    await interaction.response.defer(thinking=True)

    if not istek:
        picks = random.sample(ANIME_LIST, 5)
    else:
        low = istek.lower()
        if "karanlık" in low or "savaş" in low or "berserk" in low:
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

@bot.tree.command(name="waifu", description="Eğlencelik waifu yorumu al.")
@app_commands.describe(mod="Örn: cool, tatlı, gamer")
async def waifu_command(interaction: discord.Interaction, mod: Optional[str] = None):
    if not mod:
        await interaction.response.send_message(f"Bugünkü seçim: **{random.choice(WAIFU_ARCHETYPES)}**")
        return

    low = mod.lower()
    if "cool" in low:
        result = "Bence sana **cool ve sessiz tip** gider."
    elif "tatlı" in low:
        result = "Sana **tatlı ama hafif yaramaz tip** daha çok uyar."
    elif "gamer" in low:
        result = "Net şekilde **gamer girl tipi** derim."
    else:
        result = f"Bence sana **{random.choice(WAIFU_ARCHETYPES)}** gider."

    await interaction.response.send_message(result)

@bot.tree.command(name="profile", description="Bir üyenin kayıtlı profilini gösterir.")
@app_commands.describe(member="Profili gösterilecek üye")
async def profile_command(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    ensure_profile(target.id, target.display_name)
    profile = get_profile(target.id)
    await interaction.response.send_message(profile_to_text(target, profile), ephemeral=True)

@bot.tree.command(name="warnings", description="Bir üyenin son uyarılarını gösterir.")
@app_commands.describe(member="Uyarıları gösterilecek üye")
@app_commands.default_permissions(manage_messages=True)
async def warnings_command(interaction: discord.Interaction, member: discord.Member):
    rows = get_warnings(member.id, 10)
    if not rows:
        await interaction.response.send_message("Bu üyede kayıtlı uyarı yok.", ephemeral=True)
        return

    lines = [f"**{member.display_name}** için son uyarılar:"]
    for row in rows:
        try:
            ts = datetime.fromisoformat(row["created_at"]).strftime("%Y-%m-%d %H:%M")
        except Exception:
            ts = row["created_at"]
        lines.append(f"• `{ts}` — {row['reason']} ({row['moderator']})")

    await interaction.response.send_message("\n".join(lines[:11]), ephemeral=True)

@bot.tree.command(name="setlevels", description="Bir üyenin text ve voice levelini ayarlar.")
@app_commands.describe(member="Üye", text_level="Text seviyesi", voice_level="Voice seviyesi")
@app_commands.default_permissions(manage_guild=True)
async def setlevels_command(interaction: discord.Interaction, member: discord.Member, text_level: int, voice_level: int):
    text_level = max(1, text_level)
    voice_level = max(1, voice_level)
    set_levels(member.id, member.display_name, text_level, voice_level)
    await interaction.response.send_message(
        f"{member.mention} için text level **{text_level}**, voice level **{voice_level}** olarak ayarlandı.",
        ephemeral=True
    )

@bot.tree.command(name="penalty_add", description="Ceza puanı ekler.")
@app_commands.describe(member="Üye", amount="Eklenecek puan", reason="Sebep")
@app_commands.default_permissions(manage_messages=True)
async def penalty_add_command(interaction: discord.Interaction, member: discord.Member, amount: int, reason: str):
    amount = max(1, amount)
    add_penalty_points(member.id, member.display_name, amount)
    save_warning(interaction.guild.id, member.id, interaction.user.display_name, reason)
    await send_warn_log(interaction.guild, member, reason)
    await interaction.response.send_message(
        f"{member.mention} için **{amount}** ceza puanı eklendi. Sebep: {reason}",
        ephemeral=True
    )

@bot.tree.command(name="penalty_remove", description="Ceza puanı düşer.")
@app_commands.describe(member="Üye", amount="Düşülecek puan")
@app_commands.default_permissions(manage_messages=True)
async def penalty_remove_command(interaction: discord.Interaction, member: discord.Member, amount: int):
    amount = max(1, amount)
    add_penalty_points(member.id, member.display_name, -amount)
    await interaction.response.send_message(
        f"{member.mention} için **{amount}** ceza puanı düşüldü.",
        ephemeral=True
    )

@bot.tree.command(name="timerole_add", description="Belirli süreli rol verir.")
@app_commands.describe(member="Üye", role="Rol", duration="Örn: 30m / 2h / 7d / 1d12h", reason="Sebep")
@app_commands.default_permissions(manage_roles=True)
async def timerole_add_command(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role,
    duration: str,
    reason: Optional[str] = "Süreli rol"
):
    delta = parse_duration(duration)
    if not delta:
        await interaction.response.send_message(
            "Süre formatı geçersiz. Örnek: `30m`, `2h`, `7d`, `1d12h`",
            ephemeral=True
        )
        return

    me = interaction.guild.me
    if me is None:
        await interaction.response.send_message("Bot sunucu bilgisini okuyamadı.", ephemeral=True)
        return

    if not interaction.guild.me.guild_permissions.manage_roles:
        await interaction.response.send_message("Bende **Rolleri Yönet** yetkisi yok.", ephemeral=True)
        return

    if role >= me.top_role:
        await interaction.response.send_message(
            "Bu rolü veremem. Benim rolüm, vermeye çalıştığın rolün üstünde olmalı.",
            ephemeral=True
        )
        return

    if interaction.user != interaction.guild.owner and role >= interaction.user.top_role:
        await interaction.response.send_message(
            "Kendi rolünün üstündeki ya da eşit roldeki bir rolü veremezsin.",
            ephemeral=True
        )
        return

    if member == interaction.guild.owner and interaction.user != interaction.guild.owner:
        await interaction.response.send_message("Sunucu sahibine süreli rol veremezsin.", ephemeral=True)
        return

    expires_at = now_utc() + delta

    try:
        await member.add_roles(role, reason=f"Timed role: {reason}")
        add_timed_role(interaction.guild.id, member.id, role.id, expires_at, reason or "Süreli rol")
        await interaction.response.send_message(
            f"{member.mention} kullanıcısına {role.mention} rolü verildi.\n"
            f"Bitiş: **{format_dt(expires_at)}**",
            ephemeral=True
        )
    except discord.Forbidden:
        await interaction.response.send_message(
            "Rol veremedim. Rol sıralamasını ve yetkilerimi kontrol et.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(
            f"Rol verilirken hata oldu: {e}",
            ephemeral=True
        )

@bot.tree.command(name="timerole_remove", description="Süreli rol kaydını ve rolü kaldırır.")
@app_commands.describe(member="Üye", role="Rol")
@app_commands.default_permissions(manage_roles=True)
async def timerole_remove_command(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    try:
        await member.remove_roles(role, reason="Timed role manuel kaldırıldı")
    except Exception:
        pass

    remove_timed_role_entry(member.id, role.id)
    await interaction.response.send_message(
        f"{member.mention} üzerinden {role.mention} süreli rol kaydı kaldırıldı.",
        ephemeral=True
    )

@bot.tree.command(name="timeroles", description="Bir üyenin süreli rollerini listeler.")
@app_commands.describe(member="Üye")
@app_commands.default_permissions(manage_roles=True)
async def timeroles_command(interaction: discord.Interaction, member: discord.Member):
    rows = get_member_timed_roles(member.id)
    if not rows:
        await interaction.response.send_message("Bu üyede aktif süreli rol kaydı yok.", ephemeral=True)
        return

    lines = [f"**{member.display_name}** için aktif süreli roller:"]
    for row in rows[:10]:
        role = interaction.guild.get_role(int(row["role_id"]))
        role_name = role.mention if role else f"Rol ID: {row['role_id']}"
        try:
            expires = datetime.fromisoformat(row["expires_at"])
            expires_txt = format_dt(expires)
        except Exception:
            expires_txt = row["expires_at"]
        lines.append(f"• {role_name} — bitiş: `{expires_txt}` — sebep: {row['reason']}")

    await interaction.response.send_message("\n".join(lines), ephemeral=True)

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
