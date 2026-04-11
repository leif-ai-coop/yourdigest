"""
Seed default podcast prompts on startup.
"""
import logging
from sqlalchemy import select
from app.database import async_session
from app.models.podcast import PodcastPrompt

logger = logging.getLogger(__name__)

DEFAULT_MAP_PROMPT = """Du bist ein Podcast-Zusammenfasser. Erstelle eine strukturierte Zusammenfassung des folgenden Podcast-Abschnitts.

Regeln:
- Fasse die Kernaussagen in klaren Bulletpoints zusammen
- Behalte wichtige Namen, Zahlen und Fakten bei
- Ignoriere Werbung, Sponsor-Hinweise und Eigenwerbung
- Schreibe auf Deutsch, es sei denn der Podcast ist auf Englisch
- Sei praegnant aber vollstaendig"""

DEFAULT_REDUCE_PROMPT = """Du bist ein Podcast-Zusammenfasser. Dir werden Zusammenfassungen einzelner Abschnitte eines Podcasts gegeben. Erstelle daraus eine kohaerente Gesamtzusammenfassung.

Regeln:
- Fasse die wichtigsten Erkenntnisse und Aussagen zusammen
- Strukturiere thematisch, nicht chronologisch
- Entferne Redundanzen zwischen den Abschnitten
- Behalte wichtige Details, Zitate und Fakten bei
- Schreibe auf Deutsch, es sei denn der Podcast ist auf Englisch
- Laenge: ausfuehrlich aber praegnant"""

DEFAULTS = [
    {
        "name": "Standard Chunk-Summary",
        "description": "Zusammenfassung einzelner Podcast-Abschnitte (Map-Phase)",
        "system_prompt": DEFAULT_MAP_PROMPT,
        "prompt_type": "map_summary",
        "is_default": True,
    },
    {
        "name": "Standard Gesamt-Summary",
        "description": "Gesamtzusammenfassung aus Abschnitts-Summaries (Reduce-Phase)",
        "system_prompt": DEFAULT_REDUCE_PROMPT,
        "prompt_type": "reduce_summary",
        "is_default": True,
    },
]


async def seed_default_prompts():
    """Create default podcast prompts if they don't exist yet."""
    try:
        async with async_session() as db:
            for default in DEFAULTS:
                result = await db.execute(
                    select(PodcastPrompt).where(
                        PodcastPrompt.prompt_type == default["prompt_type"],
                        PodcastPrompt.is_default == True,
                    )
                )
                if result.scalar_one_or_none():
                    continue

                prompt = PodcastPrompt(**default)
                db.add(prompt)
                logger.info(f"Seeded default podcast prompt: {default['name']}")

            await db.commit()
    except Exception as e:
        logger.error(f"Failed to seed podcast prompts: {e}")
