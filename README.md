# 🎌 AnimeStreamBot

Bot de Discord para seguir tus animes favoritos. Te notifica automáticamente cuando sale un nuevo episodio, muestra calendarios semanales, rankings y más, usando la API gratuita de AniList.

---

## ✨ Comandos

### 📡 Suscripciones
| Comando | Descripción |
|---|---|
| `!animeAdd <nombre>` | Suscribe el canal a notificaciones de nuevos episodios |
| `!animeList` | Muestra los animes suscritos en el canal actual |
| `!animeRemove <nombre>` | Cancela la suscripción a un anime |

### 🔍 Información
| Comando | Descripción |
|---|---|
| `!animeInfo <nombre>` | Ficha completa: sinopsis, estudio, puntuación, géneros y más |
| `!animeSearch <nombre>` | Busca un anime y muestra los 5 primeros resultados |

### 🏆 Rankings
| Comando | Descripción |
|---|---|
| `!animeTop` | TOP 5 animes mejor calificados de todos los tiempos |
| `!animeGenre <género>` | TOP 5 mejor calificados de un género específico |

### 📅 Calendario
| Comando | Descripción |
|---|---|
| `!animeSeason` | Animes más populares de la temporada actual |
| `!animeSchedule` | Calendario semanal con episodios por día |

### ❓ Ayuda
| Comando | Descripción |
|---|---|
| `!animeHelp` | Muestra todos los comandos disponibles |

---

## 🚀 Instalación

### Requisitos
- Python 3.8 o superior
- Una cuenta de [Discord Developer Portal](https://discord.com/developers/applications)

### Pasos

**1. Clona el repositorio**
```bash
git clone https://github.com/Javiercatalanv/AnimeStreamBot.git
cd AnimeStreamBot
```

**2. Instala las dependencias**
```bash
pip install -r requirements.txt
```

**3. Crea el archivo `.env`**
```
BOT_TOKEN=tu_token_de_discord_aquí
```

**4. Ejecuta el bot**
```bash
python anime_bot.py
```

## 📡 Fuente de datos

Toda la información proviene de **[AniList](https://anilist.co)** a través de su API pública GraphQL, 100% gratuita y sin necesidad de clave de API.

---
