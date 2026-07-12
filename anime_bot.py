import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import json
import os
import random
from datetime import datetime, timezone
from dotenv import load_dotenv

# =============================================
# CONFIGURACIÓN
# =============================================
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHECK_INTERVAL_MINUTES = 30  # Cada cuántos minutos revisar nuevos episodios

if not BOT_TOKEN:
    raise ValueError(
        "⚠️ No se encontró BOT_TOKEN. Crea un archivo .env con la línea:\n"
        "BOT_TOKEN=tu_token_aquí"
    )

# =============================================
# Archivo para guardar suscripciones y estado
# =============================================
DATA_FILE = "anime_subscriptions.json"

# =============================================
# Carga y guarda datos de suscripciones
# =============================================
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# =============================================
# Consulta a la API de AniList (GraphQL)
# =============================================
ANILIST_URL = "https://graphql.anilist.co"

SEARCH_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME, status_in: [RELEASING, NOT_YET_RELEASED]) {
    id
    title {
      romaji
      english
      native
    }
    coverImage {
      large
    }
    siteUrl
    meanScore
    popularity
    nextAiringEpisode {
      airingAt
      episode
    }
    status
  }
}
"""

ID_QUERY = """
query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id
    title {
      romaji
      english
    }
    coverImage {
      large
    }
    siteUrl
    meanScore
    popularity
    episodes
    nextAiringEpisode {
      airingAt
      episode
    }
    status
  }
}
"""

TOP_QUERY = """
query ($page: Int, $perPage: Int) {
  Page(page: $page, perPage: $perPage) {
    media(type: ANIME, sort: SCORE_DESC, status: FINISHED, isAdult: false) {
      id
      title {
        romaji
        english
      }
      meanScore
      popularity
      episodes
      genres
      coverImage {
        large
      }
      siteUrl
      description(asHtml: false)
    }
  }
}
"""

async def get_top_anime(session, limit=5):
    """Obtiene los animes mejor calificados de todos los tiempos."""
    async with session.post(
        ANILIST_URL,
        json={
            "query": TOP_QUERY,
            "variables": {"page": 1, "perPage": limit}
        },
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("data", {}).get("Page", {}).get("media", [])

SCHEDULE_QUERY = """
query ($page: Int, $perPage: Int, $airingAt_greater: Int, $airingAt_lesser: Int) {
  Page(page: $page, perPage: $perPage) {
    airingSchedules(
      airingAt_greater: $airingAt_greater
      airingAt_lesser: $airingAt_lesser
      sort: TIME
    ) {
      airingAt
      episode
      media {
        title {
          romaji
          english
        }
        siteUrl
        popularity
      }
    }
  }
}
"""

async def get_weekly_schedule(session):
    """Obtiene todos los animes que emiten episodio esta semana."""
    from datetime import timedelta

    now = datetime.now(tz=timezone.utc)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_week = start_of_week + timedelta(days=7)

    start_ts = int(start_of_week.timestamp())
    end_ts = int(end_of_week.timestamp())

    all_schedules = []
    page = 1

    while True:
        async with session.post(
            ANILIST_URL,
            json={
                "query": SCHEDULE_QUERY,
                "variables": {
                    "page": page,
                    "perPage": 50,
                    "airingAt_greater": start_ts - 1,
                    "airingAt_lesser": end_ts
                }
            },
            headers={"Content-Type": "application/json"}
        ) as resp:
            if resp.status != 200:
                break
            data = await resp.json()
            items = data.get("data", {}).get("Page", {}).get("airingSchedules", [])
            if not items:
                break
            all_schedules.extend(items)
            if len(items) < 50:
                break
            page += 1

    return all_schedules


INFO_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    id
    title {
      romaji
      english
      native
    }
    description(asHtml: false)
    coverImage {
      large
    }
    bannerImage
    siteUrl
    meanScore
    popularity
    favourites
    episodes
    duration
    status
    season
    seasonYear
    genres
    studios(isMain: true) {
      nodes { name }
    }
    startDate { year month day }
    endDate { year month day }
    nextAiringEpisode {
      airingAt
      episode
    }
  }
}
"""

MULTI_SEARCH_QUERY = """
query ($search: String) {
  Page(page: 1, perPage: 5) {
    media(search: $search, type: ANIME) {
      id
      title {
        romaji
        english
      }
      meanScore
      popularity
      episodes
      status
      season
      seasonYear
      genres
      coverImage { large }
      siteUrl
      nextAiringEpisode {
        airingAt
        episode
      }
    }
  }
}
"""

QUIZ_QUERY = """
query ($page: Int) {
  Page(page: $page, perPage: 10) {
    media(type: ANIME, sort: POPULARITY_DESC, isAdult: false, status: FINISHED) {
      id
      title {
        romaji
        english
      }
      description(asHtml: false)
      coverImage { large }
      siteUrl
      meanScore
    }
  }
}
"""

async def get_quiz_pool(session):
    """Obtiene un grupo de animes populares para el quiz."""
    page = random.randint(1, 15)
    async with session.post(
        ANILIST_URL,
        json={"query": QUIZ_QUERY, "variables": {"page": page}},
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("data", {}).get("Page", {}).get("media", [])

SEASON_QUERY = """
query ($season: MediaSeason, $year: Int, $page: Int) {
  Page(page: $page, perPage: 25) {
    media(season: $season, seasonYear: $year, type: ANIME, sort: POPULARITY_DESC, isAdult: false) {
      id
      title {
        romaji
        english
      }
      meanScore
      popularity
      episodes
      genres
      coverImage { large }
      siteUrl
      nextAiringEpisode {
        airingAt
        episode
      }
    }
  }
}
"""

GENRE_QUERY = """
query ($genre: String, $page: Int) {
  Page(page: $page, perPage: 5) {
    media(genre: $genre, type: ANIME, sort: SCORE_DESC, status: FINISHED, isAdult: false) {
      id
      title {
        romaji
        english
      }
      meanScore
      popularity
      episodes
      genres
      coverImage { large }
      siteUrl
      description(asHtml: false)
    }
  }
}
"""

async def get_anime_info(session, name: str):
    async with session.post(
        ANILIST_URL,
        json={"query": INFO_QUERY, "variables": {"search": name}},
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("data", {}).get("Media")

async def search_anime_multi(session, name: str):
    async with session.post(
        ANILIST_URL,
        json={"query": MULTI_SEARCH_QUERY, "variables": {"search": name}},
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("data", {}).get("Page", {}).get("media", [])

async def get_season_anime(session, season: str, year: int):
    async with session.post(
        ANILIST_URL,
        json={"query": SEASON_QUERY, "variables": {"season": season, "year": year, "page": 1}},
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("data", {}).get("Page", {}).get("media", [])

async def get_anime_by_genre(session, genre: str):
    async with session.post(
        ANILIST_URL,
        json={"query": GENRE_QUERY, "variables": {"genre": genre.title(), "page": 1}},
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return []
        data = await resp.json()
        return data.get("data", {}).get("Page", {}).get("media", [])

async def search_anime(session, name: str):
    """Busca un anime por nombre y devuelve sus datos."""
    async with session.post(
        ANILIST_URL,
        json={"query": SEARCH_QUERY, "variables": {"search": name}},
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("data", {}).get("Media")

async def get_anime_by_id(session, anime_id: int):
    """Obtiene datos actualizados de un anime por su ID."""
    async with session.post(
        ANILIST_URL,
        json={"query": ID_QUERY, "variables": {"id": anime_id}},
        headers={"Content-Type": "application/json"}
    ) as resp:
        if resp.status != 200:
            return None
        data = await resp.json()
        return data.get("data", {}).get("Media")

# =============================================
# Configuración del bot
# =============================================
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True, help_command=None)

# =============================================
# Comando: !animeAdd <nombre>
# =============================================
def subscribe_channel(guild_id: str, channel_id: str, anime: dict, subscribed_by: str):
    """
    Suscribe un canal a un anime. Reutilizable desde comandos y botones.
    Devuelve (embed, ok).
    """
    title = anime["title"]["english"] or anime["title"]["romaji"]
    anime_id = anime["id"]
    next_ep = anime.get("nextAiringEpisode")

    if anime.get("status") == "FINISHED":
        embed = discord.Embed(
            title=f"⚠️ {title} ya finalizó",
            description="Este anime no tiene próximos episodios, no tiene sentido suscribirse.",
            color=0xF39C12
        )
        return embed, False

    data = load_data()
    key = f"{guild_id}_{channel_id}_{anime_id}"

    if key in data:
        embed = discord.Embed(
            title=f"⚠️ Ya suscrito",
            description=f"Este canal ya está suscrito a **{title}**.",
            color=0xF39C12
        )
        return embed, False

    data[key] = {
        "guild_id": guild_id,
        "channel_id": channel_id,
        "anime_id": anime_id,
        "anime_name": title,
        "cover": anime["coverImage"]["large"],
        "url": anime["siteUrl"],
        "last_notified_episode": (next_ep["episode"] - 1) if next_ep else 0,
        "subscribed_by": subscribed_by
    }
    save_data(data)

    embed = discord.Embed(
        title=f"✅ Suscrito a {title}",
        description="Te avisaré en este canal cada vez que salga un nuevo episodio.",
        color=0x7289DA
    )
    score = anime.get("meanScore")
    popularity = anime.get("popularity", 0)
    if score:
        stars = "⭐" * round(score / 20)
        embed.add_field(
            name="⭐ Puntuación global",
            value=f"**{score/10:.1f}/10** {stars}\n👥 {popularity:,} usuarios en AniList",
            inline=False
        )

    embed.set_thumbnail(url=anime["coverImage"]["large"])

    if next_ep:
        embed.add_field(
            name="📅 Próximo episodio",
            value=f"Episodio **{next_ep['episode']}** — <t:{next_ep['airingAt']}:F> (<t:{next_ep['airingAt']}:R>)",
            inline=False
        )
    else:
        embed.add_field(name="📅 Próximo episodio", value="Sin fecha confirmada aún.", inline=False)

    embed.set_footer(text=f"Fuente: AniList | Suscrito por {subscribed_by}")
    return embed, True

# =============================================
# Views: botones interactivos
# =============================================
class SubscribeButton(discord.ui.Button):
    """Botón ➕ para suscribirse a un anime desde resultados de búsqueda."""
    def __init__(self, anime: dict, index: int):
        title = anime["title"]["english"] or anime["title"]["romaji"]
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=f"{index}. {title}"[:80],
            emoji="➕",
            row=(index - 1) % 5
        )
        self.anime = anime

    async def callback(self, interaction: discord.Interaction):
        embed, ok = subscribe_channel(
            guild_id=str(interaction.guild.id),
            channel_id=str(interaction.channel.id),
            anime=self.anime,
            subscribed_by=interaction.user.display_name
        )
        if ok:
            self.disabled = True
            self.style = discord.ButtonStyle.success
            self.emoji = "✅"
        await interaction.response.edit_message(view=self.view)
        await interaction.followup.send(embed=embed)

class SubscribeView(discord.ui.View):
    """View con un botón de suscripción por cada resultado de búsqueda."""
    def __init__(self, animes: list, timeout=180):
        super().__init__(timeout=timeout)
        for i, anime in enumerate(animes[:5], 1):
            self.add_item(SubscribeButton(anime, i))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class ConfirmRemoveView(discord.ui.View):
    """Confirmación ✅/❌ antes de eliminar suscripciones."""
    def __init__(self, author_id: int, keys_to_delete: list, anime_names: list, timeout=60):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.keys_to_delete = keys_to_delete
        self.anime_names = anime_names
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "⛔ Solo quien usó el comando puede confirmar.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger, emoji="✅")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = load_data()
        deleted = []
        for k in self.keys_to_delete:
            if k in data:
                deleted.append(data[k]["anime_name"])
                del data[k]
        save_data(data)
        self.resolved = True
        for item in self.children:
            item.disabled = True
        nombres = ", ".join(f"**{n}**" for n in deleted)
        await interaction.response.edit_message(
            content=f"🗑️ Suscripción a {nombres} eliminada correctamente.",
            embed=None, view=self
        )
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="❌")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.resolved = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="👍 Operación cancelada, no se eliminó nada.",
            embed=None, view=self
        )
        self.stop()

# =============================================
# Comando: !animeAdd <nombre>
# =============================================
@bot.command(name="animeAdd", aliases=["animejoin", "animesub"])
async def anime_news(ctx, *, anime_name: str):
    """
    Suscribe el canal actual a notificaciones de nuevos episodios.
    Uso: !animeAdd Nombre del Anime
    """
    await ctx.send(f"🔍 Buscando **{anime_name}**...")

    async with aiohttp.ClientSession() as session:
        anime = await search_anime(session, anime_name)

        if anime:
            embed, ok = subscribe_channel(
                guild_id=str(ctx.guild.id),
                channel_id=str(ctx.channel.id),
                anime=anime,
                subscribed_by=ctx.author.display_name
            )
            await ctx.send(embed=embed)
            return

        # Búsqueda difusa: no hubo match exacto en emisión,
        # buscamos parecidos y ofrecemos botones
        sugerencias = await search_anime_multi(session, anime_name)

    if not sugerencias:
        await ctx.send(
            f"❌ No encontré nada parecido a **{anime_name}**. "
            f"Revisa la ortografía o prueba con el nombre en inglés/romaji."
        )
        return

    embed = discord.Embed(
        title=f"🤔 No encontré \"{anime_name}\" en emisión",
        description="¿Quisiste decir alguno de estos? Toca el botón para suscribirte:",
        color=0xF39C12
    )
    status_map = {
        "FINISHED": "✅ Finalizado", "RELEASING": "📡 En emisión",
        "NOT_YET_RELEASED": "⏳ Próximamente", "CANCELLED": "❌ Cancelado", "HIATUS": "⏸️ En pausa"
    }
    for i, a in enumerate(sugerencias, 1):
        t = a["title"]["english"] or a["title"]["romaji"]
        st = status_map.get(a.get("status", ""), "")
        score = a.get("meanScore")
        score_str = f" • ⭐ {score/10:.1f}" if score else ""
        embed.add_field(name=f"{i}. {t}", value=f"{st}{score_str}", inline=False)

    await ctx.send(embed=embed, view=SubscribeView(sugerencias))

# =============================================
# Comando: !animeList — ver suscripciones activas
# =============================================
@bot.command(name="animeList", aliases=[])
async def anime_list(ctx):
    """Muestra todos los animes suscritos en este canal."""
    channel_id = str(ctx.channel.id)
    guild_id = str(ctx.guild.id)
    data = load_data()

    subs = [v for k, v in data.items() if v["guild_id"] == guild_id and v["channel_id"] == channel_id]

    if not subs:
        await ctx.send("📋 No hay animes suscritos en este canal. Usa `!animeAdd Nombre` para agregar uno.")
        return

    embed = discord.Embed(title="📋 Animes suscritos en este canal", color=0x7289DA)
    for sub in subs:
        embed.add_field(name=sub["anime_name"], value=f"[Ver en AniList]({sub['url']})", inline=True)
    await ctx.send(embed=embed)

# =============================================
# Comando: !animeRemove "Nombre del anime"
# =============================================
@bot.command(name="animeRemove", aliases=[])
async def anime_remove(ctx, *, anime_name: str):
    """Elimina una suscripción de este canal (con confirmación)."""
    channel_id = str(ctx.channel.id)
    guild_id = str(ctx.guild.id)
    data = load_data()

    to_delete = [
        k for k, v in data.items()
        if v["guild_id"] == guild_id
        and v["channel_id"] == channel_id
        and anime_name.lower() in v["anime_name"].lower()
    ]

    if not to_delete:
        await ctx.send(f"❌ No encontré una suscripción para **{anime_name}** en este canal.")
        return

    anime_names = [data[k]["anime_name"] for k in to_delete]

    if len(to_delete) == 1:
        desc = f"¿Seguro que quieres eliminar la suscripción a **{anime_names[0]}**?"
    else:
        lista = "\n".join(f"• **{n}**" for n in anime_names)
        desc = (
            f"Tu búsqueda coincide con **{len(to_delete)} suscripciones**:\n{lista}\n\n"
            f"¿Seguro que quieres eliminarlas TODAS?"
        )

    embed = discord.Embed(title="🗑️ Confirmar eliminación", description=desc, color=0xE74C3C)
    embed.set_footer(text="Tienes 60 segundos para confirmar")
    view = ConfirmRemoveView(ctx.author.id, to_delete, anime_names)
    await ctx.send(embed=embed, view=view)


# =============================================
# Comando: !animeSchedule — calendario semanal
# =============================================
@bot.command(name="animeSchedule", aliases=["schedule", "calendario"])
async def anime_schedule(ctx):
    """Muestra qué animes emiten episodio cada día de esta semana."""
    from datetime import timedelta

    await ctx.send("📅 Consultando el calendario semanal de anime, un momento...")

    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]

    async with aiohttp.ClientSession() as session:
        schedules = await get_weekly_schedule(session)

    if not schedules:
        await ctx.send("❌ No pude obtener el calendario en este momento. Intenta más tarde.")
        return

    # Agrupar por día de la semana (en UTC)
    por_dia = {i: [] for i in range(7)}

    for item in schedules:
        airing_dt = datetime.fromtimestamp(item["airingAt"], tz=timezone.utc)
        dia_semana = airing_dt.weekday()  # 0=lunes, 6=domingo
        title = item["media"]["title"]["english"] or item["media"]["title"]["romaji"]
        episode = item["episode"]
        airing_ts = item["airingAt"]
        por_dia[dia_semana].append((title, episode, airing_ts))

    # Enviar un embed por cada día que tenga animes
    now = datetime.now(tz=timezone.utc)
    start_of_week = now - timedelta(days=now.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)

    embeds_enviados = 0
    for dia_idx in range(7):
        animes_del_dia = por_dia[dia_idx]
        if not animes_del_dia:
            continue

        fecha_dia = start_of_week + timedelta(days=dia_idx)
        es_hoy = fecha_dia.date() == now.date()

        titulo_embed = f"{EMOJIS[dia_idx]} {DIAS[dia_idx]}"
        if es_hoy:
            titulo_embed += " — HOY"

        embed = discord.Embed(
            title=titulo_embed,
            color=0xFF6B35 if es_hoy else 0x7289DA
        )

        # Agrupar en bloques de 15 para no pasarse del límite de Discord
        lineas = []
        for title, episode, airing_ts in animes_del_dia:
            lineas.append(f"• **{title}** — Ep. {episode} <t:{airing_ts}:t>")

        # Discord limita los fields a 1024 chars, dividimos si hace falta
        chunk = ""
        for linea in lineas:
            if len(chunk) + len(linea) + 1 > 1020:
                embed.add_field(name="\u200b", value=chunk, inline=False)
                chunk = linea + "\n"
            else:
                chunk += linea + "\n"
        if chunk:
            embed.add_field(name=f"{len(animes_del_dia)} animes", value=chunk, inline=False)

        embed.set_footer(text="Horarios en tu zona horaria local • Fuente: AniList")
        await ctx.send(embed=embed)
        embeds_enviados += 1
        await asyncio.sleep(0.5)  # Evitar rate limit de Discord

    if embeds_enviados == 0:
        await ctx.send("📭 No hay animes programados para esta semana en AniList.")

# =============================================
# Comando: !animeTop — top 5 mejor calificados
# =============================================
@bot.command(name="animeTop", aliases=["top"])
async def anime_top(ctx):
    """Muestra el TOP 5 de animes mejor calificados de todos los tiempos."""
    await ctx.send("🏆 Consultando el TOP 5 de animes mejor calificados...")

    MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    async with aiohttp.ClientSession() as session:
        top_animes = await get_top_anime(session, limit=5)

    if not top_animes:
        await ctx.send("❌ No pude obtener el ranking en este momento. Intenta más tarde.")
        return

    embed = discord.Embed(
        title="🏆 TOP 5 Animes Mejor Calificados",
        description="Los animes mejor valorados de todos los tiempos según AniList",
        color=0xFFD700
    )

    for i, anime in enumerate(top_animes):
        title = anime["title"]["english"] or anime["title"]["romaji"]
        score = anime.get("meanScore", 0)
        popularity = anime.get("popularity", 0)
        episodes = anime.get("episodes") or "?"
        genres = ", ".join(anime.get("genres", [])[:3])

        # Descripción corta (primeras 120 chars sin HTML)
        raw_desc = anime.get("description") or ""
        short_desc = raw_desc.replace("<br>", " ").replace("<i>", "").replace("</i>", "")
        short_desc = short_desc[:120] + "..." if len(short_desc) > 120 else short_desc

        embed.add_field(
            name=f"{MEDALS[i]} {title}",
            value=(
                f"⭐ **{score/10:.1f}/10** • 👥 {popularity:,} usuarios\n"
                f"📺 {episodes} eps • 🎭 {genres}\n"
                f"_{short_desc}_\n"
                f"[Ver en AniList]({anime['siteUrl']})"
            ),
            inline=False
        )

    embed.set_thumbnail(url=top_animes[0]["coverImage"]["large"])
    embed.set_footer(text="Fuente: AniList • Ordenado por puntuación media")
    await ctx.send(embed=embed)

# =============================================
# Tarea en background: revisa nuevos episodios
# =============================================
async def get_notification_channel(sub):
    """Obtiene el canal de la suscripción, usando fetch si no está en caché."""
    channel = bot.get_channel(int(sub["channel_id"]))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(sub["channel_id"]))
        except (discord.NotFound, discord.Forbidden):
            return None
    return channel

def build_episode_embed(sub, anime, aired_episode, next_ep=None, is_final=False):
    """Construye el embed de notificación de nuevo episodio."""
    if is_final:
        title = "🏁 ¡Episodio FINAL disponible!"
        desc = f"**{sub['anime_name']}** — Episodio **{aired_episode}** (FINAL) ya está disponible en Crunchyroll."
    else:
        title = "🎬 ¡Nuevo episodio disponible!"
        desc = f"**{sub['anime_name']}** — Episodio **{aired_episode}** ya está disponible en Crunchyroll."

    embed = discord.Embed(title=title, description=desc, color=0xFF6B35, url=sub["url"])
    embed.set_thumbnail(url=sub["cover"])

    score = anime.get("meanScore")
    if score:
        embed.add_field(
            name="⭐ Puntuación global",
            value=f"**{score/10:.1f}/10** — {anime.get('popularity', 0):,} usuarios",
            inline=False
        )

    if next_ep:
        embed.add_field(
            name="📅 Próximo episodio",
            value=f"Ep. **{next_ep['episode']}** — <t:{next_ep['airingAt']}:F> (<t:{next_ep['airingAt']}:R>)",
            inline=False
        )
    elif is_final:
        embed.add_field(
            name="✅ Serie finalizada",
            value="Este era el último episodio. La suscripción se eliminará automáticamente.",
            inline=False
        )

    embed.set_footer(text="Fuente: AniList • El episodio suele llegar a Crunchyroll ~1h después de Japón")
    return embed

@tasks.loop(minutes=CHECK_INTERVAL_MINUTES)
async def check_new_episodes():
    data = load_data()
    if not data:
        return

    changed = False

    async with aiohttp.ClientSession() as session:
        for key, sub in list(data.items()):
            try:
                anime = await get_anime_by_id(session, sub["anime_id"])
                if not anime:
                    continue

                next_ep = anime.get("nextAiringEpisode")
                status = anime.get("status")
                total_episodes = anime.get("episodes")
                last_notified = sub.get("last_notified_episode", 0)

                if next_ep:
                    # Si AniList dice que el próximo es el N, el N-1 ya salió.
                    # No comparamos horas: el avance del campo ES la señal.
                    aired_episode = next_ep["episode"] - 1

                    if aired_episode > last_notified:
                        channel = await get_notification_channel(sub)
                        if channel:
                            # Si nos saltamos varios episodios (bot caído), avisar cada uno
                            for ep in range(last_notified + 1, aired_episode + 1):
                                is_last_of_batch = (ep == aired_episode)
                                embed = build_episode_embed(
                                    sub, anime, ep,
                                    next_ep=next_ep if is_last_of_batch else None
                                )
                                await channel.send(embed=embed)
                                await asyncio.sleep(1)

                        data[key]["last_notified_episode"] = aired_episode
                        changed = True

                elif status == "FINISHED" and total_episodes:
                    # El anime terminó: notificar el episodio final si falta
                    if total_episodes > last_notified:
                        channel = await get_notification_channel(sub)
                        if channel:
                            for ep in range(last_notified + 1, total_episodes + 1):
                                is_final = (ep == total_episodes)
                                embed = build_episode_embed(
                                    sub, anime, ep, next_ep=None, is_final=is_final
                                )
                                await channel.send(embed=embed)
                                await asyncio.sleep(1)

                    # Eliminar la suscripción, ya no hay más episodios
                    del data[key]
                    changed = True

                await asyncio.sleep(1)  # Pausa entre peticiones a AniList
            except Exception as e:
                print(f"[ERROR] Al revisar {sub.get('anime_name', key)}: {e}")

    if changed:
        save_data(data)

@check_new_episodes.before_loop
async def before_check():
    await bot.wait_until_ready()

# =============================================
# Comando: !animeInfo <nombre>
# =============================================
@bot.command(name="animeInfo", aliases=["info"])
async def anime_info(ctx, *, anime_name: str):
    """Muestra la ficha completa de un anime."""
    await ctx.send(f"🔍 Buscando información de **{anime_name}**...")

    async with aiohttp.ClientSession() as session:
        anime = await get_anime_info(session, anime_name)

    if not anime:
        await ctx.send(f"❌ No encontré información sobre **{anime_name}**.")
        return

    title = anime["title"]["english"] or anime["title"]["romaji"]
    native = anime["title"]["native"] or ""
    score = anime.get("meanScore")
    popularity = anime.get("popularity", 0)
    favourites = anime.get("favourites", 0)
    episodes = anime.get("episodes") or "?"
    duration = anime.get("duration") or "?"
    status_map = {
        "FINISHED": "✅ Finalizado",
        "RELEASING": "📡 En emisión",
        "NOT_YET_RELEASED": "⏳ Pendiente",
        "CANCELLED": "❌ Cancelado",
        "HIATUS": "⏸️ En pausa"
    }
    status = status_map.get(anime.get("status", ""), anime.get("status", "Desconocido"))
    season_map = {"WINTER": "Invierno", "SPRING": "Primavera", "SUMMER": "Verano", "FALL": "Otoño"}
    season = season_map.get(anime.get("season", ""), "")
    year = anime.get("seasonYear") or ""
    season_str = f"{season} {year}".strip() or "Desconocido"
    genres = ", ".join(anime.get("genres", [])[:5]) or "N/A"
    studios = ", ".join([s["name"] for s in anime.get("studios", {}).get("nodes", [])]) or "Desconocido"

    raw_desc = anime.get("description") or "Sin descripción disponible."
    desc = raw_desc.replace("<br>", " ").replace("<i>", "*").replace("</i>", "*").replace("<b>", "**").replace("</b>", "**")
    desc = desc[:350] + "..." if len(desc) > 350 else desc

    embed = discord.Embed(
        title=f"{title}",
        description=f"*{native}*\n\n{desc}",
        color=0x02A9FF,
        url=anime["siteUrl"]
    )
    embed.set_thumbnail(url=anime["coverImage"]["large"])

    if score:
        embed.add_field(name="⭐ Puntuación", value=f"**{score/10:.1f}/10**", inline=True)
    embed.add_field(name="👥 Popularidad", value=f"{popularity:,} usuarios", inline=True)
    embed.add_field(name="❤️ Favoritos", value=f"{favourites:,}", inline=True)
    embed.add_field(name="📺 Episodios", value=str(episodes), inline=True)
    embed.add_field(name="⏱️ Duración/ep", value=f"{duration} min", inline=True)
    embed.add_field(name="🏠 Estudio", value=studios, inline=True)
    embed.add_field(name="📅 Temporada", value=season_str, inline=True)
    embed.add_field(name="📊 Estado", value=status, inline=True)
    embed.add_field(name="🎭 Géneros", value=genres, inline=False)

    next_ep = anime.get("nextAiringEpisode")
    if next_ep:
        embed.add_field(
            name="📡 Próximo episodio",
            value=f"Ep. **{next_ep['episode']}** — <t:{next_ep['airingAt']}:R>",
            inline=False
        )

    embed.set_footer(text="Fuente: AniList")
    await ctx.send(embed=embed)

# =============================================
# Comando: !animeSearch <nombre>
# =============================================
@bot.command(name="animeSearch", aliases=["buscar"])
async def anime_search_cmd(ctx, *, anime_name: str):
    """Busca un anime y muestra los 5 primeros resultados."""
    await ctx.send(f"🔍 Buscando **{anime_name}**...")

    async with aiohttp.ClientSession() as session:
        results = await search_anime_multi(session, anime_name)

    if not results:
        await ctx.send(f"❌ No encontré resultados para **{anime_name}**.")
        return

    status_map = {
        "FINISHED": "✅ Finalizado",
        "RELEASING": "📡 En emisión",
        "NOT_YET_RELEASED": "⏳ Próximamente",
        "CANCELLED": "❌ Cancelado",
        "HIATUS": "⏸️ En pausa"
    }
    season_map = {"WINTER": "Invierno", "SPRING": "Primavera", "SUMMER": "Verano", "FALL": "Otoño"}

    embed = discord.Embed(
        title=f"\U0001F50E Resultados para \"{anime_name}\"",
        description=f"Se encontraron {len(results)} resultado(s):",
        color=0x02A9FF
    )

    for i, anime in enumerate(results, 1):
        title = anime["title"]["english"] or anime["title"]["romaji"]
        score = anime.get("meanScore")
        score_str = f"⭐ {score/10:.1f}/10" if score else "Sin puntuación"
        status = status_map.get(anime.get("status", ""), "Desconocido")
        season = season_map.get(anime.get("season", ""), "")
        year = anime.get("seasonYear") or ""
        season_str = f"{season} {year}".strip()
        episodes = anime.get("episodes") or "?"
        genres = ", ".join(anime.get("genres", [])[:3])

        embed.add_field(
            name=f"{i}. {title}",
            value=(
                f"{score_str} • {status}\n"
                f"📺 {episodes} eps • 📅 {season_str}\n"
                f"🎭 {genres}\n"
                f"[Ver en AniList]({anime['siteUrl']})"
            ),
            inline=False
        )

    embed.set_thumbnail(url=results[0]["coverImage"]["large"])
    embed.set_footer(text="Toca ➕ para suscribirte directamente • Fuente: AniList")
    await ctx.send(embed=embed, view=SubscribeView(results))

# =============================================
# Comando: !animeSeason — animes de la temporada
# =============================================
@bot.command(name="animeSeason", aliases=["season", "temporada"])
async def anime_season(ctx):
    """Muestra los animes más populares de la temporada actual."""
    from datetime import timedelta

    now = datetime.now(tz=timezone.utc)
    month = now.month
    year = now.year

    if month in [1, 2, 3]:
        season, season_name = "WINTER", "Invierno"
    elif month in [4, 5, 6]:
        season, season_name = "SPRING", "Primavera"
    elif month in [7, 8, 9]:
        season, season_name = "SUMMER", "Verano"
    else:
        season, season_name = "FALL", "Otoño"

    await ctx.send(f"📅 Cargando animes de **{season_name} {year}**...")

    async with aiohttp.ClientSession() as session:
        animes = await get_season_anime(session, season, year)

    if not animes:
        await ctx.send("❌ No pude obtener la temporada actual. Intenta más tarde.")
        return

    embed = discord.Embed(
        title=f"🌸 Temporada {season_name} {year}",
        description=f"Los {len(animes)} animes más populares de esta temporada:",
        color=0xFF6B9D
    )

    for anime in animes[:15]:
        title = anime["title"]["english"] or anime["title"]["romaji"]
        score = anime.get("meanScore")
        score_str = f"⭐ {score/10:.1f}" if score else "—"
        popularity = anime.get("popularity", 0)
        genres = ", ".join(anime.get("genres", [])[:2])
        next_ep = anime.get("nextAiringEpisode")
        next_str = f" • Ep. {next_ep['episode']} <t:{next_ep['airingAt']}:R>" if next_ep else ""

        embed.add_field(
            name=title,
            value=f"{score_str} \u2022 \U0001F465 {popularity:,}\n\U0001F3AD {genres}{next_str}\n[AniList]({anime['siteUrl']})",
            inline=True
        )

    embed.set_footer(text=f"Temporada {season_name} {year} • Fuente: AniList")
    await ctx.send(embed=embed)

# =============================================
# Comando: !animeGenre <género>
# =============================================
VALID_GENRES = [
    "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy",
    "Horror", "Mahou Shoujo", "Mecha", "Music", "Mystery", "Psychological",
    "Romance", "Sci-Fi", "Slice of Life", "Sports", "Supernatural", "Thriller"
]

@bot.command(name="animeGenre", aliases=["genero", "género"])
async def anime_genre(ctx, *, genre: str):
    """Muestra el top 5 de animes mejor calificados de un género."""
    # Buscar el género más cercano (case-insensitive)
    genre_match = next(
        (g for g in VALID_GENRES if g.lower() == genre.lower()),
        None
    )

    if not genre_match:
        genres_list = " • ".join(VALID_GENRES)
        await ctx.send(
            f"❌ Género **{genre}** no encontrado.\n"
            f"**Géneros disponibles:**\n{genres_list}"
        )
        return

    await ctx.send(f"🎭 Buscando top 5 de **{genre_match}**...")

    async with aiohttp.ClientSession() as session:
        animes = await get_anime_by_genre(session, genre_match)

    if not animes:
        await ctx.send(f"❌ No encontré animes del género **{genre_match}**.")
        return

    MEDALS = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]

    embed = discord.Embed(
        title=f"🎭 Top 5 — {genre_match}",
        description=f"Los mejor calificados del género **{genre_match}**",
        color=0x9B59B6
    )

    for i, anime in enumerate(animes[:5]):
        title = anime["title"]["english"] or anime["title"]["romaji"]
        score = anime.get("meanScore", 0)
        popularity = anime.get("popularity", 0)
        episodes = anime.get("episodes") or "?"
        genres = ", ".join(anime.get("genres", [])[:3])
        raw_desc = anime.get("description") or ""
        desc = raw_desc.replace("<br>", " ").replace("<i>", "").replace("</i>", "")
        desc = desc[:100] + "..." if len(desc) > 100 else desc

        embed.add_field(
            name=f"{MEDALS[i]} {title}",
            value=(
                f"⭐ **{score/10:.1f}/10** • 👥 {popularity:,}\n"
                f"📺 {episodes} eps • 🎭 {genres}\n"
                f"_{desc}_\n"
                f"[Ver en AniList]({anime['siteUrl']})"
            ),
            inline=False
        )

    embed.set_thumbnail(url=animes[0]["coverImage"]["large"])
    embed.set_footer(text="Fuente: AniList • Solo animes finalizados")
    await ctx.send(embed=embed)

# =============================================
# Comando: !animeNext — próximos episodios de tus suscripciones
# =============================================
@bot.command(name="animeNext", aliases=["next", "proximos", "próximos"])
async def anime_next(ctx):
    """Muestra las suscripciones del canal ordenadas por cuál episodio sale antes."""
    channel_id = str(ctx.channel.id)
    guild_id = str(ctx.guild.id)
    data = load_data()

    subs = [v for v in data.values() if v["guild_id"] == guild_id and v["channel_id"] == channel_id]

    if not subs:
        await ctx.send("📋 No hay animes suscritos en este canal. Usa `!animeAdd Nombre` para agregar uno.")
        return

    await ctx.send("⏳ Consultando próximos episodios...")

    resultados = []
    async with aiohttp.ClientSession() as session:
        for sub in subs:
            try:
                anime = await get_anime_by_id(session, sub["anime_id"])
                if anime:
                    next_ep = anime.get("nextAiringEpisode")
                    resultados.append((sub, next_ep))
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f"[ERROR] animeNext {sub['anime_name']}: {e}")

    # Ordenar: primero los que tienen fecha (por cercanía), luego los sin fecha
    con_fecha = sorted(
        [r for r in resultados if r[1]],
        key=lambda r: r[1]["airingAt"]
    )
    sin_fecha = [r for r in resultados if not r[1]]

    embed = discord.Embed(
        title="⏭️ Próximos episodios",
        description="Tus suscripciones ordenadas por cuál sale antes:",
        color=0x1ABC9C
    )

    MEDALS = ["🔜", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, (sub, next_ep) in enumerate(con_fecha):
        emoji = MEDALS[i] if i < len(MEDALS) else "▫️"
        embed.add_field(
            name=f"{emoji} {sub['anime_name']}",
            value=f"Ep. **{next_ep['episode']}** — <t:{next_ep['airingAt']}:F> (<t:{next_ep['airingAt']}:R>)",
            inline=False
        )

    for sub, _ in sin_fecha:
        embed.add_field(
            name=f"❔ {sub['anime_name']}",
            value="Sin fecha confirmada para el próximo episodio.",
            inline=False
        )

    if con_fecha:
        embed.set_thumbnail(url=con_fecha[0][0]["cover"])
    embed.set_footer(text="Fuente: AniList • Horarios en tu zona horaria local")
    await ctx.send(embed=embed)

# =============================================
# Comando: !animeQuiz — adivina el anime por la sinopsis
# =============================================
import re as _re

def _clean_quiz_description(desc: str, titles: list) -> str:
    """Limpia HTML y censura los títulos dentro de la sinopsis."""
    desc = desc.replace("<br>", " ").replace("<i>", "").replace("</i>", "")
    desc = desc.replace("<b>", "").replace("</b>", "")
    desc = _re.sub(r"\(Source:.*?\)", "", desc, flags=_re.IGNORECASE)
    for t in titles:
        if t:
            desc = _re.sub(_re.escape(t), "▓▓▓▓▓", desc, flags=_re.IGNORECASE)
            # También censurar palabras individuales largas del título
            for palabra in t.split():
                if len(palabra) > 3:
                    desc = _re.sub(_re.escape(palabra), "▓▓▓", desc, flags=_re.IGNORECASE)
    return desc.strip()[:600]

class QuizView(discord.ui.View):
    """4 botones de opciones para el quiz."""
    def __init__(self, opciones: list, correcta: dict, timeout=45):
        super().__init__(timeout=timeout)
        self.correcta = correcta
        self.respondido = False
        random.shuffle(opciones)
        for anime in opciones:
            self.add_item(QuizButton(anime, es_correcta=(anime is correcta)))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class QuizButton(discord.ui.Button):
    def __init__(self, anime: dict, es_correcta: bool):
        title = anime["title"]["english"] or anime["title"]["romaji"]
        super().__init__(style=discord.ButtonStyle.primary, label=title[:80])
        self.es_correcta = es_correcta
        self.anime = anime

    async def callback(self, interaction: discord.Interaction):
        view: QuizView = self.view
        if view.respondido:
            await interaction.response.defer()
            return
        view.respondido = True

        correcta_title = view.correcta["title"]["english"] or view.correcta["title"]["romaji"]

        for item in view.children:
            item.disabled = True
            if isinstance(item, QuizButton):
                if item.es_correcta:
                    item.style = discord.ButtonStyle.success
                elif item is self:
                    item.style = discord.ButtonStyle.danger

        if self.es_correcta:
            resultado = discord.Embed(
                title=f"🎉 ¡Correcto, {interaction.user.display_name}!",
                description=f"Era **{correcta_title}**.",
                color=0x2ECC71,
                url=view.correcta["siteUrl"]
            )
        else:
            resultado = discord.Embed(
                title=f"❌ Incorrecto, {interaction.user.display_name}",
                description=f"La respuesta era **{correcta_title}**.",
                color=0xE74C3C,
                url=view.correcta["siteUrl"]
            )
        resultado.set_thumbnail(url=view.correcta["coverImage"]["large"])
        score = view.correcta.get("meanScore")
        if score:
            resultado.set_footer(text=f"⭐ {score/10:.1f}/10 en AniList")

        await interaction.response.edit_message(view=view)
        await interaction.followup.send(embed=resultado)
        view.stop()

@bot.command(name="animeQuiz", aliases=["quiz"])
async def anime_quiz(ctx):
    """Adivina el anime a partir de su sinopsis. 4 opciones, 45 segundos."""
    await ctx.send("🎲 Preparando el quiz...")

    async with aiohttp.ClientSession() as session:
        pool = await get_quiz_pool(session)

    # Necesitamos al menos 4 animes con descripción decente
    candidatos = [a for a in pool if a.get("description") and len(a["description"]) > 150]
    if len(candidatos) < 4:
        await ctx.send("❌ No pude preparar el quiz en este momento. Inténtalo de nuevo.")
        return

    opciones = random.sample(candidatos, 4)
    correcta = random.choice(opciones)

    titles_a_censurar = [
        correcta["title"].get("english"),
        correcta["title"].get("romaji")
    ]
    sinopsis = _clean_quiz_description(correcta["description"], titles_a_censurar)

    embed = discord.Embed(
        title="🧩 ¿Qué anime es este?",
        description=f"*{sinopsis}*",
        color=0x9B59B6
    )
    embed.set_footer(text="⏱️ Tienes 45 segundos • El primero en responder gana")

    await ctx.send(embed=embed, view=QuizView(opciones, correcta))

# =============================================
# Comando: !animeHelp — muestra todos los comandos
# =============================================
@bot.command(name="animeHelp", aliases=["help", "ayuda", "comandos"])
async def anime_help(ctx):
    """Muestra todos los comandos disponibles del bot."""
    embed = discord.Embed(
        title="🤖 Comandos del Bot de Anime",
        description="Aquí tienes todo lo que puedo hacer:",
        color=0x7289DA
    )

    # ── Suscripciones ──
    embed.add_field(name="\u200b", value="**📡 Suscripciones**", inline=False)
    embed.add_field(
        name="➕ `!animeAdd <nombre>`",
        value=(
            "Suscribe **este canal** a notificaciones automáticas cuando salga un episodio nuevo.\n"
            "**Ejemplo:** `!animeAdd One Piece`"
        ),
        inline=False
    )
    embed.add_field(
        name="📋 `!animeList`",
        value="Muestra todos los animes suscritos en este canal.\n**Ejemplo:** `!animeList`",
        inline=False
    )
    embed.add_field(
        name="🗑️ `!animeRemove <nombre>`",
        value="Cancela la suscripción a un anime en este canal (con confirmación).\n**Ejemplo:** `!animeRemove One Piece`",
        inline=False
    )
    embed.add_field(
        name="⏭️ `!animeNext`",
        value="Muestra tus suscripciones ordenadas por cuál episodio sale antes.\n**Ejemplo:** `!animeNext`",
        inline=False
    )

    # ── Información ──
    embed.add_field(name="\u200b", value="**🔍 Información**", inline=False)
    embed.add_field(
        name="ℹ️ `!animeInfo <nombre>`",
        value=(
            "Ficha completa de un anime: sinopsis, géneros, estudio, puntuación, episodios, estado y más.\n"
            "**Ejemplo:** `!animeInfo Fullmetal Alchemist`"
        ),
        inline=False
    )
    embed.add_field(
        name="🔎 `!animeSearch <nombre>`",
        value=(
            "Busca un anime y muestra los 5 primeros resultados. Útil cuando no sabes el nombre exacto.\n"
            "**Ejemplo:** `!animeSearch ataque`"
        ),
        inline=False
    )

    # ── Rankings y recomendaciones ──
    embed.add_field(name="\u200b", value="**🏆 Rankings y recomendaciones**", inline=False)
    embed.add_field(
        name="🏆 `!animeTop`",
        value="TOP 5 animes mejor calificados de todos los tiempos.\n**Ejemplo:** `!animeTop`",
        inline=False
    )
    embed.add_field(
        name="🎭 `!animeGenre <género>`",
        value=(
            "TOP 5 mejor calificados de un género específico.\n"
            "**Géneros:** Action, Romance, Horror, Comedy, Drama, Fantasy, Thriller...\n"
            "**Ejemplo:** `!animeGenre Romance`"
        ),
        inline=False
    )

    # ── Calendario ──
    embed.add_field(name="\u200b", value="**📅 Calendario**", inline=False)
    embed.add_field(
        name="🗓️ `!animeSeason`",
        value="Muestra los animes más populares de la temporada actual.\n**Ejemplo:** `!animeSeason`",
        inline=False
    )
    embed.add_field(
        name="📅 `!animeSchedule`",
        value="Calendario semanal completo con qué animes emiten episodio cada día.\n**Ejemplo:** `!animeSchedule`",
        inline=False
    )

    # ── Juegos ──
    embed.add_field(name="\u200b", value="**🎮 Juegos**", inline=False)
    embed.add_field(
        name="🧩 `!animeQuiz`",
        value="Adivina el anime a partir de su sinopsis. 4 opciones, 45 segundos, gana el primero en responder.\n**Ejemplo:** `!animeQuiz`",
        inline=False
    )

    embed.add_field(
        name="❓ `!animeHelp`",
        value="Muestra este mensaje de ayuda.",
        inline=False
    )

    embed.add_field(
        name="ℹ️ ¿Cómo funciona?",
        value=(
            f"El bot revisa cada **{CHECK_INTERVAL_MINUTES} minutos** si hay nuevos episodios usando la API de AniList. "
            "Cuando un episodio nuevo sale al aire, envía una notificación en el canal suscrito. "
            "Crunchyroll suele tenerlo disponible **~1 hora después**."
        ),
        inline=False
    )

    embed.set_footer(text="Fuente de datos: AniList • Bot hecho con discord.py")
    await ctx.send(embed=embed)

# =============================================
# Eventos del bot
# =============================================
@bot.event
async def on_ready():
    print(f"✅ Bot conectado como {bot.user} (ID: {bot.user.id})")
    print(f"📡 Revisando episodios cada {CHECK_INTERVAL_MINUTES} minutos")
    check_new_episodes.start()

@bot.event
async def on_command_error(ctx, error):
    prefix = ctx.prefix

    if isinstance(error, commands.MissingRequiredArgument):
        mensajes = {
            "animeadd":   f"⚠️ Debes indicar el nombre del anime.\n**Uso:** `{prefix}animeAdd <nombre>`\n**Ejemplo:** `{prefix}animeAdd One Piece`",
            "animeremove":f"⚠️ Debes indicar el nombre del anime a eliminar.\n**Uso:** `{prefix}animeRemove <nombre>`\n**Ejemplo:** `{prefix}animeRemove One Piece`",
            "animeinfo":  f"⚠️ Debes indicar el nombre del anime.\n**Uso:** `{prefix}animeInfo <nombre>`\n**Ejemplo:** `{prefix}animeInfo Fullmetal Alchemist`",
            "animesearch":f"⚠️ Debes indicar qué quieres buscar.\n**Uso:** `{prefix}animeSearch <nombre>`\n**Ejemplo:** `{prefix}animeSearch ataque`",
            "animegenre": f"⚠️ Debes indicar un género.\n**Uso:** `{prefix}animeGenre <género>`\n**Ejemplo:** `{prefix}animeGenre Romance`\nGéneros disponibles: Action, Adventure, Comedy, Drama, Fantasy, Horror, Mystery, Romance, Sci-Fi, Thriller...",
        }
        cmd = ctx.invoked_with.lower()
        msg = mensajes.get(cmd, f"⚠️ Faltan argumentos. Usa `{prefix}animeHelp` para ver todos los comandos.")
        await ctx.send(msg)

    elif isinstance(error, commands.CommandNotFound):
        await ctx.send(f"❓ Comando no encontrado. Usa `{prefix}animeHelp` para ver todos los comandos disponibles.")

    else:
        print(f"[ERROR] {error}")

# =============================================
# Iniciar el bot
# =============================================
if __name__ == "__main__":
    bot.run(BOT_TOKEN)