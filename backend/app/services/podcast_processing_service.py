"""
Podcast Processing Service — Download, Transkription, Summary.

Two processing paths:
  - Gemini API (if GEMINI_API_KEY set): Upload full audio → 1 transcribe call + 1 summary call
  - OpenRouter fallback: Chunk audio → N transcribe calls + 1 summary call

No more Map-Reduce — summary always runs on the full transcript in a single call.
"""
import asyncio
import base64
import hashlib
import logging
import os
import subprocess
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.ssrf import safe_stream

from app.models.podcast import (
    PodcastEpisode, PodcastEpisodeChunk, PodcastArtifact,
    PodcastProcessingRun, PodcastFeed, PodcastPrompt,
)
from app.llm.provider import get_llm_provider
from app.config import get_settings

logger = logging.getLogger(__name__)

# Audio storage directory inside the container
AUDIO_DIR = Path("/app/podcast_audio")
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# Chunking config (only used for OpenRouter fallback)
DEFAULT_CHUNK_DURATION = 600  # 10 minutes
DEFAULT_CHUNK_OVERLAP = 30   # 30 seconds overlap
CHUNK_STRATEGY_VERSION = 2

# Lock timeout — release stuck locks after this duration
LOCK_TIMEOUT = timedelta(minutes=30)

FALLBACK_SUMMARY_PROMPT = "Erstelle eine strukturierte Zusammenfassung des folgenden Podcast-Transkripts."


def _use_gemini_direct() -> bool:
    """Check if Gemini API key is configured for direct access."""
    return bool(get_settings().gemini_api_key)


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
    result = await db.execute(
        select(PodcastPrompt).where(
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

        ep_dir = AUDIO_DIR / str(episode.id)
        ep_dir.mkdir(parents=True, exist_ok=True)

        audio_path = ep_dir / "original"
        async with httpx.AsyncClient(timeout=httpx.Timeout(300, connect=30)) as client:
            async with safe_stream(client, "GET", episode.audio_url,
                                   headers={"User-Agent": "YouDigest/1.0 (Podcast RSS Reader)"}) as resp:
                resp.raise_for_status()

                ct = resp.headers.get("content-type", "")
                if ct:
                    episode.mime_type = ct.split(";")[0].strip()[:100]

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

        if not episode.duration_seconds:
            try:
                probe = await asyncio.to_thread(
                    subprocess.run,
                    ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                     "-of", "csv=p=0", str(audio_path)],
                    capture_output=True, text=True, timeout=30,
                )
                episode.duration_seconds = int(float(probe.stdout.strip()))
            except Exception:
                pass

        logger.info(f"Downloaded audio for '{episode.title}' ({total_bytes} bytes)")
        return True

    except Exception as e:
        episode.processing_status = "error"
        episode.error_class = "download"
        episode.error_message = str(e)[:2000]
        episode.is_retryable = True
        episode.locked_at = None
        _fail_run(run, "download", str(e))
        logger.error(f"Audio download failed for episode {episode.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 2: Chunk (OpenRouter fallback only)
# ---------------------------------------------------------------------------

async def chunk_episode_audio(db: AsyncSession, episode: PodcastEpisode) -> bool:
    """Split episode audio into chunks using ffmpeg subprocess (no RAM loading).
    Only needed for OpenRouter path.

    ffprobe/ffmpeg run via asyncio.to_thread so a long-running chunking job does
    not block the event loop (which also serves the API in this single process).
    """
    run = _create_run(episode.id, "chunk")
    db.add(run)

    episode.processing_status = "chunking"
    episode.locked_at = datetime.now(timezone.utc)
    await db.flush()

    start = time.time()
    try:
        if not episode.audio_path or not os.path.exists(episode.audio_path):
            raise FileNotFoundError(f"Audio file not found: {episode.audio_path}")

        # Get duration via ffprobe (no RAM usage; off-loop so the API stays responsive)
        probe = await asyncio.to_thread(
            subprocess.run,
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", episode.audio_path],
            capture_output=True, text=True, timeout=30,
        )
        total_seconds = float(probe.stdout.strip())

        if not episode.duration_seconds:
            episode.duration_seconds = int(total_seconds)

        ep_dir = AUDIO_DIR / str(episode.id)
        chunks = []
        chunk_index = 0
        pos_seconds = 0.0

        while pos_seconds < total_seconds:
            chunk_start = max(0, pos_seconds - (DEFAULT_CHUNK_OVERLAP if chunk_index > 0 else 0))
            chunk_end = min(total_seconds, pos_seconds + DEFAULT_CHUNK_DURATION)
            duration = chunk_end - chunk_start

            chunk_path = ep_dir / f"chunk_{chunk_index:04d}.mp3"

            # ffmpeg chunk extraction — streams directly, no full file in RAM.
            # Off-loop (to_thread) so this CPU-bound call doesn't freeze the API.
            proc = await asyncio.to_thread(
                subprocess.run,
                ["ffmpeg", "-y", "-ss", str(chunk_start), "-t", str(duration),
                 "-i", episode.audio_path, "-ab", "64k", "-ac", "1",
                 "-ar", "22050", str(chunk_path)],
                capture_output=True, timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg chunk {chunk_index} failed: {proc.stderr[-500:]}")

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
            pos_seconds += DEFAULT_CHUNK_DURATION

        episode.chunk_count = len(chunks)
        episode.chunk_duration_seconds = DEFAULT_CHUNK_DURATION
        episode.chunk_overlap_seconds = DEFAULT_CHUNK_OVERLAP
        episode.chunk_strategy_version = CHUNK_STRATEGY_VERSION
        episode.locked_at = None

        _complete_run(run, duration_ms=int((time.time() - start) * 1000))
        logger.info(f"Chunked '{episode.title}' into {len(chunks)} chunks (ffmpeg, no RAM)")
        return True

    except Exception as e:
        episode.processing_status = "error"
        episode.error_class = "chunk"
        episode.error_message = str(e)[:2000]
        episode.is_retryable = True
        episode.locked_at = None
        _fail_run(run, "chunk", str(e))
        logger.error(f"Audio chunking failed for episode {episode.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 3a: Transcribe via Gemini API (full audio, single call)
# ---------------------------------------------------------------------------

async def transcribe_episode_gemini(db: AsyncSession, episode: PodcastEpisode, model: str | None = None) -> bool:
    """Transcribe full audio via Google Gemini API. Single call, no chunking needed."""
    import google.generativeai as genai

    settings = get_settings()
    genai.configure(api_key=settings.gemini_api_key)

    used_model = model or "gemini-2.5-flash"
    run = _create_run(episode.id, "transcribe", model=used_model)
    db.add(run)

    episode.processing_status = "transcribing"
    episode.locked_at = datetime.now(timezone.utc)
    episode.processing_attempts += 1
    await db.flush()

    start = time.time()
    try:
        if not episode.audio_path or not os.path.exists(episode.audio_path):
            raise FileNotFoundError(f"Audio not found: {episode.audio_path}")

        # Upload file to Gemini. The google-generativeai SDK is synchronous and
        # generate_content can run for minutes — run both off the event loop via
        # asyncio.to_thread so the single-process API stays responsive.
        audio_file = await asyncio.to_thread(genai.upload_file, episode.audio_path)
        logger.info(f"Uploaded audio to Gemini: {audio_file.name}")

        # Transcribe
        gm = genai.GenerativeModel(used_model)
        response = await asyncio.to_thread(
            gm.generate_content,
            [
                audio_file,
                "Transkribiere dieses Audio wortgetreu. Gib nur das Transkript aus, ohne Kommentare oder Formatierung. Behalte die Originalsprache bei."
            ],
            generation_config=genai.GenerationConfig(temperature=0.1, max_output_tokens=65536),
        )

        transcript = response.text
        duration_ms = int((time.time() - start) * 1000)

        # Create single chunk record for consistency
        chunk = PodcastEpisodeChunk(
            episode_id=episode.id,
            chunk_index=0,
            start_seconds=0,
            end_seconds=episode.duration_seconds or 0,
            transcript_text=transcript,
            transcript_model=used_model,
            status="done",
            completed_at=datetime.now(timezone.utc),
        )
        db.add(chunk)
        episode.chunk_count = 1
        episode.chunk_strategy_version = CHUNK_STRATEGY_VERSION
        episode.locked_at = None

        tokens = None
        if hasattr(response, 'usage_metadata'):
            tokens = getattr(response.usage_metadata, 'total_token_count', None)
        _complete_run(run, tokens=tokens, duration_ms=duration_ms)

        # Cleanup uploaded file (off-loop; network I/O, best-effort)
        try:
            await asyncio.to_thread(genai.delete_file, audio_file.name)
        except Exception:
            pass

        logger.info(f"Gemini transcribed '{episode.title}' ({len(transcript)} chars)")
        return True

    except Exception as e:
        episode.processing_status = "error"
        episode.error_class = "transcription"
        episode.error_message = str(e)[:2000]
        episode.is_retryable = True
        episode.locked_at = None
        _fail_run(run, "transcription", str(e))
        logger.error(f"Gemini transcription failed for episode {episode.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 3b: Transcribe chunk via OpenRouter (fallback)
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

        with open(chunk.audio_path, "rb") as f:
            audio_bytes = f.read()
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        ext = os.path.splitext(chunk.audio_path)[1].lower()
        mime_map = {".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".m4a": "audio/mp4", ".wav": "audio/wav"}

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
                    {"type": "text", "text": "Transkribiere diesen Audio-Clip wortgetreu."}
                ]
            }
        ]

        result = await llm.chat(messages=messages, model=model, temperature=0.1, max_tokens=16000)

        chunk.transcript_text = result["content"]
        chunk.transcript_model = model
        chunk.status = "done"
        chunk.locked_at = None
        chunk.locked_by = None
        chunk.completed_at = datetime.now(timezone.utc)

        _complete_run(run, tokens=result.get("total_tokens"), duration_ms=int((time.time() - start) * 1000))
        logger.info(f"Transcribed chunk {chunk.chunk_index} of episode {chunk.episode_id}")
        return True

    except Exception as e:
        chunk.status = "error"
        chunk.error_class = "transcription"
        chunk.error_message = str(e)[:2000]
        chunk.is_retryable = True
        chunk.locked_at = None
        chunk.locked_by = None
        chunk.last_error_at = datetime.now(timezone.utc)
        _fail_run(run, "transcription", str(e))
        logger.error(f"Transcription failed for chunk {chunk.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Stage 4: Summarize full transcript (single call, no Map-Reduce)
# ---------------------------------------------------------------------------

async def summarize_episode(
    db: AsyncSession,
    episode: PodcastEpisode,
    prompt: PodcastPrompt | None = None,
    model: str | None = None,
) -> bool:
    """Generate summary from the full transcript in a single LLM call. Creates artifacts."""
    if not model:
        model = await get_global_podcast_model(db, "summary")

    # Load all chunks to build full transcript
    result = await db.execute(
        select(PodcastEpisodeChunk)
        .where(PodcastEpisodeChunk.episode_id == episode.id)
        .order_by(PodcastEpisodeChunk.chunk_index)
    )
    chunks = result.scalars().all()

    if not chunks:
        logger.error(f"No chunks found for episode {episode.id}")
        return False

    # Check all chunks have transcripts
    missing = [c for c in chunks if not c.transcript_text]
    if missing:
        logger.warning(f"Episode {episode.id} has {len(missing)} chunks without transcript")
        return False

    if not prompt:
        prompt = await _get_default_prompt(db, "reduce_summary")
    system_prompt = prompt.system_prompt if prompt else FALLBACK_SUMMARY_PROMPT
    prompt_id = prompt.id if prompt else None
    prompt_version = prompt.version if prompt else None
    llm = get_llm_provider()
    used_model = model or llm.default_model

    episode.processing_status = "summarizing"
    episode.locked_at = datetime.now(timezone.utc)
    await db.flush()

    # --- Create transcript artifact ---
    full_transcript = "\n\n".join(
        f"[{int(c.start_seconds / 60)}-{int(c.end_seconds / 60)} min]\n{c.transcript_text}"
        for c in chunks if c.transcript_text
    )
    transcript_hash = hashlib.sha256(full_transcript.encode()).hexdigest()

    await db.execute(
        update(PodcastArtifact)
        .where(PodcastArtifact.episode_id == episode.id, PodcastArtifact.artifact_type == "transcript", PodcastArtifact.is_active == True)
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

    # --- Summary (single call on full transcript) ---
    run = _create_run(episode.id, "summary", model=used_model, prompt_id=prompt_id, prompt_version=prompt_version)
    db.add(run)
    await db.flush()

    start = time.time()
    try:
        episode_context = f"Podcast: {episode.title or 'Unbekannt'}"
        if episode.description:
            import re
            desc_text = re.sub(r'<[^>]+>', ' ', episode.description)[:500]
            episode_context += f"\nBeschreibung: {desc_text}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{episode_context}\n\n---\n\nVollstaendiges Transkript:\n\n{full_transcript}"},
        ]

        llm_result = await llm.chat(messages=messages, model=used_model, temperature=0.3, max_tokens=8000)
        summary_content = llm_result["content"]

        input_hash = hashlib.sha256(
            f"{transcript_artifact.id}|{prompt_id}|{prompt_version}|{used_model}".encode()
        ).hexdigest()

        await db.execute(
            update(PodcastArtifact)
            .where(PodcastArtifact.episode_id == episode.id, PodcastArtifact.artifact_type == "summary", PodcastArtifact.is_active == True)
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

        _complete_run(run, tokens=llm_result.get("total_tokens"), duration_ms=int((time.time() - start) * 1000))
        logger.info(f"Summarized episode '{episode.title}' ({summary_artifact.word_count} words)")
        return True

    except Exception as e:
        episode.processing_status = "error"
        episode.error_class = "summarization"
        episode.error_message = str(e)[:2000]
        episode.is_retryable = True
        episode.locked_at = None
        _fail_run(run, "summarization", str(e))
        logger.error(f"Summary failed for episode {episode.id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Audio cleanup
# ---------------------------------------------------------------------------

async def cleanup_episode_audio(db: AsyncSession, episode: PodcastEpisode):
    """Remove audio files for an episode after successful processing."""
    feed = await db.get(PodcastFeed, episode.feed_id)
    keep_days = feed.keep_audio_days if feed else None

    if keep_days is not None:
        if episode.audio_downloaded_at:
            cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
            if episode.audio_downloaded_at > cutoff:
                return

    ep_dir = AUDIO_DIR / str(episode.id)
    if ep_dir.exists():
        import shutil
        shutil.rmtree(ep_dir)
        logger.info(f"Cleaned up audio for episode {episode.id}")

    episode.audio_path = None

    result = await db.execute(
        select(PodcastEpisodeChunk).where(PodcastEpisodeChunk.episode_id == episode.id)
    )
    for chunk in result.scalars().all():
        chunk.audio_path = None


# ---------------------------------------------------------------------------
# Orphan / stale audio reaper (safety net beyond the success-path cleanup)
# ---------------------------------------------------------------------------

async def reap_orphan_audio(db: AsyncSession) -> dict:
    """Periodic safety-net cleanup of the audio volume.

    ``cleanup_episode_audio`` only runs after a *successful* summary, so audio of
    failed/aborted episodes accumulates forever. This reaper removes directories
    that are safe to delete:
      - no matching episode row (true orphans)
      - episode status done/skipped (respecting feed.keep_audio_days)
      - episode status error and older than 7 days (retries had their chance)
    It never touches episodes that are actively processing or currently locked.
    """
    import shutil

    if not AUDIO_DIR.exists():
        return {"deleted": 0, "freed_mb": 0}

    result = await db.execute(
        select(
            PodcastEpisode.id,
            PodcastEpisode.processing_status,
            PodcastEpisode.locked_at,
            PodcastEpisode.audio_downloaded_at,
            PodcastFeed.keep_audio_days,
        ).join(PodcastFeed, PodcastFeed.id == PodcastEpisode.feed_id, isouter=True)
    )
    episodes = {str(row[0]): row for row in result.all()}

    now = datetime.now(timezone.utc)
    active = {"pending", "downloading", "transcribing", "summarizing"}
    deleted = 0
    freed = 0

    for ep_dir in AUDIO_DIR.iterdir():
        if not ep_dir.is_dir():
            continue
        row = episodes.get(ep_dir.name)
        should_delete = False

        if row is None:
            should_delete = True  # orphan: no DB row
        else:
            _id, status, locked_at, downloaded_at, keep_days = row
            if status in active or locked_at is not None:
                should_delete = False
            elif status in ("done", "skipped"):
                if keep_days is not None and downloaded_at is not None \
                        and downloaded_at > now - timedelta(days=keep_days):
                    should_delete = False
                else:
                    should_delete = True
            elif status == "error":
                should_delete = downloaded_at is None or downloaded_at < now - timedelta(days=7)

        if not should_delete:
            continue

        try:
            size = sum(f.stat().st_size for f in ep_dir.rglob("*") if f.is_file())
            shutil.rmtree(ep_dir)
            deleted += 1
            freed += size
            if row is not None:
                ep = await db.get(PodcastEpisode, uuid.UUID(ep_dir.name))
                if ep:
                    ep.audio_path = None
        except Exception as e:
            logger.error(f"reap_orphan_audio: failed to delete {ep_dir}: {e}")

    if deleted:
        await db.commit()
        logger.info(f"reap_orphan_audio: removed {deleted} dir(s), freed {freed // (1024 * 1024)} MB")

    return {"deleted": deleted, "freed_mb": freed // (1024 * 1024)}


# ---------------------------------------------------------------------------
# Release stale locks
# ---------------------------------------------------------------------------

async def release_stale_locks(db: AsyncSession):
    """Release locks on episodes/chunks that have been locked too long."""
    cutoff = datetime.now(timezone.utc) - LOCK_TIMEOUT

    await db.execute(
        update(PodcastEpisode)
        .where(PodcastEpisode.locked_at.isnot(None), PodcastEpisode.locked_at < cutoff)
        .values(locked_at=None)
    )

    await db.execute(
        update(PodcastEpisodeChunk)
        .where(PodcastEpisodeChunk.locked_at.isnot(None), PodcastEpisodeChunk.locked_at < cutoff)
        .values(locked_at=None, locked_by=None)
    )
