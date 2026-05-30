"""
Seed default podcast prompts on startup.
"""
import logging
from sqlalchemy import select, delete
from app.database import async_session
from app.models.podcast import PodcastPrompt

logger = logging.getLogger(__name__)

DEFAULT_SUMMARY_PROMPT = """Du bist ein Podcast-Zusammenfasser. Dir wird das vollstaendige Transkript einer Podcast-Episode gegeben. Erstelle daraus eine strukturierte Zusammenfassung.

Regeln:
- Fasse die wichtigsten Erkenntnisse und Aussagen zusammen
- Strukturiere thematisch, nicht chronologisch
- Behalte wichtige Namen, Zahlen und Fakten bei
- Ignoriere Werbung, Sponsor-Hinweise und Eigenwerbung
- Schreibe auf Deutsch, es sei denn der Podcast ist auf Englisch
- Laenge: ausfuehrlich aber praegnant"""


async def seed_default_prompts():
    """Create/update default podcast summary prompt. Remove obsolete map_summary prompt."""
    try:
        async with async_session() as db:
            # Remove obsolete map_summary default prompt
            await db.execute(
                delete(PodcastPrompt).where(
                    PodcastPrompt.prompt_type == "map_summary",
                    PodcastPrompt.is_default == True,
                )
            )

            # Ensure reduce_summary default exists
            result = await db.execute(
                select(PodcastPrompt).where(
                    PodcastPrompt.prompt_type == "reduce_summary",
                    PodcastPrompt.is_default == True,
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                # Update name/description if still the old Map-Reduce wording
                if "Abschnitts-Summaries" in (existing.description or ""):
                    existing.description = "Standard-Prompt fuer Podcast-Zusammenfassungen"
                    existing.name = "Standard Summary"
            else:
                prompt = PodcastPrompt(
                    name="Standard Summary",
                    description="Standard-Prompt fuer Podcast-Zusammenfassungen",
                    system_prompt=DEFAULT_SUMMARY_PROMPT,
                    prompt_type="reduce_summary",
                    is_default=True,
                )
                db.add(prompt)
                logger.info("Seeded default podcast summary prompt")

            await db.commit()
    except Exception as e:
        logger.error(f"Failed to seed podcast prompts: {e}")
