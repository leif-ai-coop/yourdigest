"""
Podcast Processing Service — Download, Chunking, Transkription, Map-Reduce Summary.

Pipeline stages:
  1. download   — Audio-Datei herunterladen
  2. chunk      — Audio in Segmente zerlegen (pydub/ffmpeg)
  3. transcribe — Chunks transkribieren via OpenRouter (Gemini)
  4. map_summary — Pro Chunk Kernaussagen extrahieren
  5. reduce_summary — Gesamtsummary aus Chunk-Summaries + Volltranskript-Artifact
"""
import base64
import hashlib
import logging
import os
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from pydub import AudioSegment
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.podcast import (
    PodcastEpisode, PodcastEpisodeChunk, PodcastArtifact,
    PodcastProcessingRun, PodcastFeed, PodcastPrompt,
)
from app.llm.provider import get_llm_provider

logger = logging.getLogger(__name__)

# Audio storage directory inside the container
AUDIO_DIR = Path("/app/podcast_audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Chunking config
DEFAULT_CHUNK_DURATION = 600  # 10 minutes
DEFAULT_CHUNK_OVERLAP = 30   # 30 seconds overlap
CHUNK_STRATEGY_VERSION = 1

# Lock timeout — release stuck locks after this duration
LOCK_TIMEOUT = timedelta(minutes=30)

FALLBACK_MAP_PROMPT = "Fasse den folgenden Podcast-Abschnitt in klaren Bulletpoints zusammen."
FALLBACK_REDUCE_PROMPT = "Erstelle aus den folgenden Abschnitts-Zusammenfassungen eine kohaerente Gesamtzusammenfassung."


async def get_global_podcast_model(db: AsyncSession, model_type: str) -> str | None:
    """Get global podcast model setting from app_setting table.
    model_type: 'transcription' or 'summary'
    """
    from app.models.audit import AppSetting
    key = f"podcast_{model_type}_model"
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == key)
    )
    setting = result.scalars().first()
    return setting.value if setting and setting.value else None


async def _get_default_prompt(db: AsyncSession, prompt_type: str) -> PodcastPrompt | None:
    """Get the default prompt for a given type from DB."""
    from sqlalchemy import select as sa_select
    result = await db.execute(
        sa_select(PodcastPrompt).where(
            PodcastPrompt.prompt_type == prompt_type,
            PodcastPrompt.is_default == True,
        )
    )
    return result.scalars().first()


def _create_run(
    episode_id: uuid.UUID,
    stage: str,
    chunk_id: uuid.UUID | None = None,
    model: str | None = None,
    prompt_id: uuid.UUID | None = None,
    prompt_version: int | None = None,
) -> PodcastProcessingRun:
    return PodcastProcessingRun(
        episode_id=episode_id,
        chunk_id=chunk_id,
        stage=stage,
        status="running",
        model=model,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        started_at=datetime.now(timezone.utc),
    )


def _complete_run(run: PodcastProcessingRun, tokens: int | None = None, duration_ms: int | None = None):
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.tokens_used = tokens
    run.duration_ms = duration_ms


def _fail_run(run: PodcastProcessingRun, error_class: str, error_msg: str):
    run.status = "failed"
    run.completed_at = datetime.now(timezone.utc)
    run.error_class = error_class
    run.error_message = error_msg[:2000]


# ---------------------------------------------------------------------------
# Stage 1: Download
# ---------------------------------------------------------------------------

async def download_episode_audio(db: AsyncSession, episode: PodcastEpisode) -> bool:
    """Download audio file for an episode. Returns True on success."""
    run = _create_run(episode.id, "download")
    db.add(run)

    episode.processing_status = "downloading"
    episode.locked_at = datetime.now(timezone.utc)
    episode.processing_attempts += 1
    await db.flush()

    start = time.time()
    try:
        if not episode.audio_url:
            raise ValueError("No audio URL")

        # Create episode directory
        ep_dir = AUDIO_DIR / str(episode.id)
        ep_dir.mkdir(parents=True, exist_ok=True)

        # Download with streaming
        audio_path = ep_dir / "original"
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
            async with client.stream("GET", episode.audio_url, follow_redirects=True) as resp:
                resp.raise_for_status()

                # Get content type
                ct = resp.headers.get("content-type", "")
                if ct:
                    episode.mime_type = ct.split(";")[0].strip()[:100]

                # Determine extension
                ext = ".mp3"
                if "ogg" in ct:
                    ext = ".ogg"
                elif "mp4" in ct or "m4a" in ct:
                    ext = ".m4a"
                elif "wav" in ct:
                    ext = ".wav"

                audio_path = ep_dir / f"original{ext}"
                total_bytes = 0
                with open(audio_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        f.write(chunk)
                        total_bytes += len(chunk)

        episode.audio_path = str(audio_path)
        episode.audio_size_bytes = total_bytes
        episode.audio_downloaded_at = datetime.now(timezone.utc)
        episode.locked_at = None

        duration_ms = int((time.time() - start) * 1000)
        _complete_run(run, duration_ms=duration_ms)

        # Try to get duration from file if not known
        if not episode.duration_seconds:
            try:
                audio = AudioSegment.from_file(str(audio_path))
                episode.duration_seconds = int(len(audio) / 1000)
            except Exception:
                pass

        logger.info(f"Downloaded audio for '{episode.title}' ({total_bytes} bytes)")
        return True

    except Exception as e:
        error_class = "download"
        episode.processing_status = "error"
        episode.error_class = error_class
        episode.error_message = str(e)[:2000]
        episode.is_retryable = True
        episode.locked_at = None
        _fail_run(run, error_class, str(e))
        logger.error(f"Audio download failed for episode {episode.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 2: Chunk
# ---------------------------------------------------------------------------

async def chunk_episode_audio(db: AsyncSession, episode: PodcastEpisode) -> bool:
    """Split episode audio into chunks. Returns True on success."""
    run = _create_run(episode.id, "chunk")
    db.add(run)

    episode.processing_status = "chunking"
    episode.locked_at = datetime.now(timezone.utc)
    await db.flush()

    start = time.time()
    try:
        if not episode.audio_path or not os.path.exists(episode.audio_path):
            raise FileNotFoundError(f"Audio file not found: {episode.audio_path}")

        audio = AudioSegment.from_file(episode.audio_path)
        total_ms = len(audio)
        total_seconds = total_ms / 1000

        # Update duration if not set
        if not episode.duration_seconds:
            episode.duration_seconds = int(total_seconds)

        chunk_duration = DEFAULT_CHUNK_DURATION
        overlap = DEFAULT_CHUNK_OVERLAP

        # Calculate chunks
        ep_dir = AUDIO_DIR / str(episode.id)
        chunks = []
        chunk_index = 0
        pos_seconds = 0.0

        while pos_seconds < total_seconds:
            chunk_start = max(0, pos_seconds - (overlap if chunk_index > 0 else 0))
            chunk_end = min(total_seconds, pos_seconds + chunk_duration)

            start_ms = int(chunk_start * 1000)
            end_ms = int(chunk_end * 1000)
            chunk_audio = audio[start_ms:end_ms]

            # Export chunk
            chunk_path = ep_dir / f"chunk_{chunk_index:04d}.mp3"
            chunk_audio.export(str(chunk_path), format="mp3", bitrate="64k")

            chunk = PodcastEpisodeChunk(
                episode_id=episode.id,
                chunk_index=chunk_index,
                start_seconds=chunk_start,
                end_seconds=chunk_end,
                audio_path=str(chunk_path),
                status="pending",
            )
            db.add(chunk)
            chunks.append(chunk)

            chunk_index += 1
            pos_seconds += chunk_duration

        episode.chunk_count = len(chunks)
        episode.chunk_duration_seconds = chunk_duration
        episode.chunk_overlap_seconds = overlap
        episode.chunk_strategy_version = CHUNK_STRATEGY_VERSION
        episode.locked_at = None

        duration_ms = int((time.time() - start) * 1000)
        _complete_run(run, duration_ms=duration_ms)

        logger.info(f"Chunked '{episode.title}' into {len(chunks)} chunks")
        return True

    except Exception as e:
        error_class = "chunk"
        episode.processing_status = "error"
        episode.error_class = error_class
        episode.error_message = str(e)[:2000]
        episode.is_retryable = True
        episode.locked_at = None
        _fail_run(run, error_class, str(e))
        logger.error(f"Audio chunking failed for episode {episode.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 3: Transcribe (per chunk)
# ---------------------------------------------------------------------------

async def transcribe_chunk(db: AsyncSession, chunk: PodcastEpisodeChunk, model: str | None = None) -> bool:
    """Transcribe a single audio chunk via OpenRouter. Returns True on success."""
    if not model:
        model = await get_global_podcast_model(db, "transcription")
    run = _create_run(chunk.episode_id, "transcribe", chunk_id=chunk.id, model=model)
    db.add(run)

    chunk.status = "transcribing"
    chunk.locked_at = datetime.now(timezone.utc)
    chunk.locked_by = "transcribe_worker"
    chunk.processing_attempts += 1
    await db.flush()

    start = time.time()
    try:
        if not chunk.audio_path or not os.path.exists(chunk.audio_path):
            raise FileNotFoundError(f"Chunk audio not found: {chunk.audio_path}")

        # Read audio and encode as base64
        with open(chunk.audio_path, "rb") as f:
            audio_bytes = f.read()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        # Determine MIME type
        ext = os.path.splitext(chunk.audio_path)[1].lower()
        mime_map = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".wav": "audio/wav"}
        mime_type = mime_map.get(ext, "audio/mpeg")

        # Send to OpenRouter with audio
        llm = get_llm_provider()
        messages = [
            {
                "role": "system",
                "content": "Du bist ein Transkriptionsassistent. Transkribiere den folgenden Audio-Clip wortgetreu. Gib nur das Transkript aus, ohne Kommentare oder Formatierung. Behalte die Originalsprache bei."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": audio_b64,
                            "format": ext.lstrip(".") if ext in (".mp3", ".wav") else "mp3",
                        }
                    },
                    {
                        "type": "text",
                        "text": "Transkribiere diesen Audio-Clip wortgetreu."
                    }
                ]
            }
        ]

        result = await llm.chat(
            messages=messages,
            model=model,
            temperature=0.1,
            max_tokens=16000,
        )

        chunk.transcript_text = result["content"]
        chunk.transcript_model = model
        chunk.status = "done" if chunk.map_summary_text else "pending"  # pending for map_summary
        chunk.locked_at = None
        chunk.locked_by = None
        chunk.completed_at = datetime.now(timezone.utc) if chunk.map_summary_text else None

        duration_ms = int((time.time() - start) * 1000)
        _complete_run(run, tokens=result.get("total_tokens"), duration_ms=duration_ms)

        # After transcription, chunk needs map_summary next — set status to pending
        chunk.status = "pending"

        logger.info(f"Transcribed chunk {chunk.chunk_index} of episode {chunk.episode_id}")
        return True

    except Exception as e:
        error_class = "transcription"
        chunk.status = "error"
        chunk.error_class = error_class
        chunk.error_message = str(e)[:2000]
        chunk.is_retryable = True
        chunk.locked_at = None
        chunk.locked_by = None
        chunk.last_error_at = datetime.now(timezone.utc)
        _fail_run(run, error_class, str(e))
        logger.error(f"Transcription failed for chunk {chunk.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 4: Map-Summary (per chunk)
# ---------------------------------------------------------------------------

async def map_summarize_chunk(
    db: AsyncSession,
    chunk: PodcastEpisodeChunk,
    prompt: PodcastPrompt | None = None,
    model: str | None = None,
) -> bool:
    """Generate map-phase summary for a single chunk. Returns True on success."""
    if not model:
        model = await get_global_podcast_model(db, "summary")
    if not chunk.transcript_text:
        logger.warning(f"Chunk {chunk.id} has no transcript, skipping map_summary")
        return False

    if not prompt:
        prompt = await _get_default_prompt(db, "map_summary")
    system_prompt = prompt.system_prompt if prompt else FALLBACK_MAP_PROMPT
    prompt_id = prompt.id if prompt else None
    prompt_version = prompt.version if prompt else None

    run = _create_run(
        chunk.episode_id, "map_summary",
        chunk_id=chunk.id, model=model, prompt_id=prompt_id, prompt_version=prompt_version,
    )
    db.add(run)

    chunk.status = "summarizing"
    chunk.locked_at = datetime.now(timezone.utc)
    chunk.locked_by = "summarize_worker"
    await db.flush()

    start = time.time()
    try:
        llm = get_llm_provider()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Podcast-Abschnitt (Minute {int(chunk.start_seconds/60)}-{int(chunk.end_seconds/60)}):\n\n{chunk.transcript_text}"},
        ]

        result = await llm.chat(
            messages=messages,
            model=model,
            temperature=0.3,
            max_tokens=4000,
        )

        chunk.map_summary_text = result["content"]
        chunk.map_summary_model = model or llm.default_model
        chunk.status = "done"
        chunk.locked_at = None
        chunk.locked_by = None
        chunk.completed_at = datetime.now(timezone.utc)

        duration_ms = int((time.time() - start) * 1000)
        _complete_run(run, tokens=result.get("total_tokens"), duration_ms=duration_ms)

        logger.info(f"Map-summarized chunk {chunk.chunk_index} of episode {chunk.episode_id}")
        return True

    except Exception as e:
        error_class = "summarization"
        chunk.status = "error"
        chunk.error_class = error_class
        chunk.error_message = str(e)[:2000]
        chunk.is_retryable = True
        chunk.locked_at = None
        chunk.locked_by = None
        chunk.last_error_at = datetime.now(timezone.utc)
        _fail_run(run, error_class, str(e))
        logger.error(f"Map-summary failed for chunk {chunk.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 5: Reduce-Summary + Artifact creation
# ---------------------------------------------------------------------------

async def reduce_summarize_episode(
    db: AsyncSession,
    episode: PodcastEpisode,
    prompt: PodcastPrompt | None = None,
    model: str | None = None,
) -> bool:
    """Generate final summary from chunk summaries + create artifacts. Returns True on success."""
    if not model:
        model = await get_global_podcast_model(db, "summary")
    # Load all chunks ordered by index
    result = await db.execute(
        select(PodcastEpisodeChunk)
        .where(PodcastEpisodeChunk.episode_id == episode.id)
        .order_by(PodcastEpisodeChunk.chunk_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        logger.error(f"No chunks found for episode {episode.id}")
        return False

    # Check all chunks are done
    not_done = [c for c in chunks if c.status != "done"]
    if not_done:
        logger.warning(f"Episode {episode.id} has {len(not_done)} unfinished chunks, skipping reduce")
        return False

    if not prompt:
        prompt = await _get_default_prompt(db, "reduce_summary")
    system_prompt = prompt.system_prompt if prompt else FALLBACK_REDUCE_PROMPT
    prompt_id = prompt.id if prompt else None
    prompt_version = prompt.version if prompt else None
    llm = get_llm_provider()
    used_model = model or llm.default_model

    episode.processing_status = "reducing"
    episode.locked_at = datetime.now(timezone.utc)
    await db.flush()

    # --- Create transcript artifact ---
    full_transcript = "\n\n".join(
        f"[{int(c.start_seconds/60)}-{int(c.end_seconds/60)} min]\n{c.transcript_text}"
        for c in chunks if c.transcript_text
    )
    transcript_hash = hashlib.sha256(full_transcript.encode()).hexdigest()

    # Deactivate old transcript artifacts
    await db.execute(
        update(PodcastArtifact)
        .where(
            PodcastArtifact.episode_id == episode.id,
            PodcastArtifact.artifact_type == "transcript",
            PodcastArtifact.is_active == True,
        )
        .values(is_active=False)
    )

    transcript_artifact = PodcastArtifact(
        episode_id=episode.id,
        artifact_type="transcript",
        content=full_transcript,
        model=chunks[0].transcript_model if chunks else None,
        input_hash=transcript_hash,
        word_count=len(full_transcript.split()),
        is_active=True,
    )
    db.add(transcript_artifact)
    await db.flush()

    # --- Reduce summary ---
    run = _create_run(
        episode.id, "reduce_summary",
        model=used_model, prompt_id=prompt_id, prompt_version=prompt_version,
    )
    db.add(run)
    await db.flush()

    start = time.time()
    try:
        # Build map summaries input
        chunk_summaries = "\n\n".join(
            f"### Abschnitt {c.chunk_index + 1} (Minute {int(c.start_seconds/60)}-{int(c.end_seconds/60)})\n{c.map_summary_text}"
            for c in chunks if c.map_summary_text
        )

        episode_context = f"Podcast: {episode.title or 'Unbekannt'}"
        if episode.description:
            episode_context += f"\nBeschreibung: {episode.description[:500]}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{episode_context}\n\n---\n\n{chunk_summaries}"},
        ]

        llm_result = await llm.chat(
            messages=messages,
            model=used_model,
            temperature=0.3,
            max_tokens=8000,
        )

        summary_content = llm_result["content"]

        # Compute input hash for idempotency
        input_hash = hashlib.sha256(
            f"{transcript_artifact.id}|{prompt_id}|{prompt_version}|{used_model}|{CHUNK_STRATEGY_VERSION}".encode()
        ).hexdigest()

        # Deactivate old summary artifacts
        await db.execute(
            update(PodcastArtifact)
            .where(
                PodcastArtifact.episode_id == episode.id,
                PodcastArtifact.artifact_type == "summary",
                PodcastArtifact.is_active == True,
            )
            .values(is_active=False)
        )

        summary_artifact = PodcastArtifact(
            episode_id=episode.id,
            artifact_type="summary",
            content=summary_content,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            model=used_model,
            input_hash=input_hash,
            word_count=len(summary_content.split()),
            is_active=True,
        )
        db.add(summary_artifact)

        episode.processing_status = "done"
        episode.last_processed_at = datetime.now(timezone.utc)
        episode.locked_at = None
        episode.error_class = None
        episode.error_message = None

        duration_ms = int((time.time() - start) * 1000)
        _complete_run(run, tokens=llm_result.get("total_tokens"), duration_ms=duration_ms)

        logger.info(f"Reduce-summarized episode '{episode.title}' ({summary_artifact.word_count} words)")
        return True

    except Exception as e:
        error_class = "summarization"
        episode.processing_status = "error"
        episode.error_class = error_class
        episode.error_message = str(e)[:2000]
        episode.is_retryable = True
        episode.locked_at = None
        _fail_run(run, error_class, str(e))
        logger.error(f"Reduce-summary failed for episode {episode.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Audio cleanup
# ---------------------------------------------------------------------------

async def cleanup_episode_audio(db: AsyncSession, episode: PodcastEpisode):
    """Remove audio files for an episode after successful processing."""
    feed = await db.get(PodcastFeed, episode.feed_id)
    keep_days = feed.keep_audio_days if feed else None

    # If keep_audio_days is None, delete immediately after processing
    if keep_days is not None:
        if episode.audio_downloaded_at:
            cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
            if episode.audio_downloaded_at > cutoff:
                return  # Not old enough to delete yet

    ep_dir = AUDIO_DIR / str(episode.id)
    if ep_dir.exists():
        import shutil
        shutil.rmtree(ep_dir)
        logger.info(f"Cleaned up audio for episode {episode.id}")

    episode.audio_path = None

    # Clear chunk audio paths
    result = await db.execute(
        select(PodcastEpisodeChunk).where(PodcastEpisodeChunk.episode_id == episode.id)
    )
    for chunk in result.scalars().all():
        chunk.audio_path = None


# ---------------------------------------------------------------------------
# Release stale locks
# ---------------------------------------------------------------------------

async def release_stale_locks(db: AsyncSession):
    """Release locks on episodes/chunks that have been locked too long."""
    cutoff = datetime.now(timezone.utc) - LOCK_TIMEOUT

    # Episodes
    await db.execute(
        update(PodcastEpisode)
        .where(
            PodcastEpisode.locked_at.isnot(None),
            PodcastEpisode.locked_at < cutoff,
        )
        .values(locked_at=None)
    )

    # Chunks
    await db.execute(
        update(PodcastEpisodeChunk)
        .where(
            PodcastEpisodeChunk.locked_at.isnot(None),
            PodcastEpisodeChunk.locked_at < cutoff,
        )
        .values(locked_at=None, locked_by=None)
    )
