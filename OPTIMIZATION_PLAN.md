# You Digest — Optimierungsplan

> Erstellt 2026-05-31 durch Tiefenanalyse (5 parallele Analyse-Agents: Backend/DB, Frontend/UX, Infra/Docker, LLM/Pipeline, Architektur/Security).
> Findings, die von mehreren Agents unabhängig bestätigt wurden, sind mit ✓✓ markiert (hohe Konfidenz).

## Live-Gesamtbild (kritisch)

Der VPS hat **3.8 GiB RAM, davon zur Analysezeit nur 133 MiB frei + 663 MiB Swap aktiv** — permanent übercommittet (17 Container, nproc=2). **Kein einziger Container hat ein Memory-Limit.** Eine OOM-Situation (z.B. Podcast-Transcribe) kann beliebige andere Container killen (auch authentik/DBs). Zusätzlich liegt das Podcast-Audio-Volume bei **1.3 GB** (Cleanup greift nicht). Das sind die akutesten Risiken.

Parallel dazu das gravierendste **Sicherheits**-Finding: **kein API-Endpoint erzwingt Auth** — die gesamte Absicherung hängt allein an der NPM/Authentik-Forward-Auth-Config. Wer den Proxy umgeht (Port 8000 direkt), hat vollen Zugriff auf Mails, Depot, IMAP-Passwort-Tests und LLM-Key-Verbrauch.

---

## P0 — Akute Risiken ✅ ERLEDIGT (2026-05-31)

Alle 6 Punkte umgesetzt, deployed und verifiziert. API/DB/Redis/Frontend laufen healthy.

| # | Finding | Status | Umsetzung |
|---|---|---|---|
| P0-1 | ✓✓ Keine Memory-Limits → OOM-Roulette | ✅ | `mem_limit` api 900m/res400m/cpus1.5, db 384m/res128m, redis 96m, frontend 64m — verifiziert via `docker inspect` |
| P0-2 | Kein Endpoint erzwingt Auth | ✅ (2. Anlauf) | Alle Router außer `health` an `auth=[Depends(get_current_user)]`. **Eigentliche Ursache** des 1. Fehlschlags: nicht der frontend-nginx (der reicht die Header korrekt durch), sondern **NPM**: die `X-authentik-*` standen im server-level `advanced_config`, aber nginx verwirft server-level `proxy_set_header` sobald ein `location`-Block eigene hat (der `location /` tut das via `proxy.conf`). **Fix:** dediziertes `location /api {}` mit den 5 `X-authentik-*` Headern in NPM `advanced_config` (proxy_host id=7, persistent in `database.sqlite` + live-conf, `nginx -t` ok + reload). `get_current_user` akzeptiert jetzt username **oder** uid **oder** email (robuster). Browser-E2E verifiziert: alle Seiten laden eingeloggt. Backups: `database.sqlite.bak_*` + `7.conf.bak_*` im NPM-Volume |
| P0-3 | Redis ohne `maxmemory` | ✅ | `--maxmemory 64mb --maxmemory-policy allkeys-lru --appendonly no` — verifiziert via `redis-cli config get` |
| P0-4 | Docker-Logs ohne `max-size` | ⚠️ teilweise | Per-Service `logging: json-file max-size 10m max-file 3` auf allen 4 assistant-Containern (verifiziert). **Offen:** host-weite `/etc/docker/daemon.json` für die übrigen ~13 Container (braucht daemon-restart = alle Stacks neu) |
| P0-5 | Podcast-Audio 1.3 GB | ✅ | `reap_orphan_audio` + `podcast_cleanup_job` (6h) ergänzt; manuell ausgeführt → **465 MB freigegeben** (1.3G → 798M; Rest = bewusst behaltenes Audio kürzlich/aktiver/innerhalb-keep_audio_days-Episoden, wird beim Altern abgeräumt) |
| P0-6 | `SECRET_KEY` Default, keine Validierung | ✅ | Startup-Abbruch bei leer/Default/<32 Zeichen (`main.py`). Bonus: `log_level`-Fallback (P2-9) gleich mit erledigt |

> **Hinweis P0-4:** Die host-weiten Log-Limits sind bewusst ausgelassen, weil ein Docker-daemon-Restart alle 17 Container des Hosts (portainer, npm, authentik, …) neu startet. Entscheidung beim Nutzer.

---

## P1 — Hoher Nutzen ✅ GRÖSSTENTEILS ERLEDIGT (2026-05-31)

Umgesetzt, deployed, verifiziert (commits `69b72f4` + Fix `2610f34`):
- **P1-3** ✅ Scheduler `job_defaults` (coalesce + max_instances=1 + misfire_grace_time=300)
- **P1-4** ✅ AsyncOpenAI timeout=60s + max_retries=3
- **P1-5** ✅ Mail-Liste deferred `body_text`/`body_html` (NICHT `raw_headers` — wird von `_add_unsubscribe` gelesen, deferred→MissingGreenlet)
- **P1-6** ✅ Digest N+1 → `selectinload(MailMessage.classifications)`
- **P1-7** ✅ 6 Indizes live via `CREATE INDEX CONCURRENTLY`: `ix_mail_message_acct_folder_date`, `ix_podcast_episode_published_at`, `ix_rss_item_feed_guid`, `ix_rss_item_published_at`, `ix_mail_classification_message_id`, `ix_depot_snapshot_captured_at` + Modell `models/mail.py` angeglichen
- **P1-8** ✅ Audit-Count via `func.count()` statt `len(.all())`
- **P1-9** ✅ Digest-AI-Summary Cap auf 100 Mails

**Sprint 2 ✅ ERLEDIGT** (2026-05-31, assistant `6e47c63` + infra `f6f7759`):
- **P1-11** ✅ Postgres-Tuning (shared_buffers 96MB, effective_cache_size 256MB, max_connections 30, work_mem 8MB, maintenance_work_mem 48MB). DB-RAM ~86→~46 MiB.
- **P1-12** ✅ Nginx gzip (recharts.js 392→115 KB).
- **P1-13 / P1-14** ✅ Frontend Code-Splitting (lazy routes + Suspense) + manualChunks (react, recharts eigener Chunk).

**Sprint 3 ✅ ERLEDIGT** (2026-05-31, assistant `6ca7f7d`):
- **P1-1 / P1-2** ✅ Event-Loop-Blocking behoben: ffprobe/ffmpeg (download+chunk) + Gemini-SDK (`upload_file`/`generate_content`/`delete_file`) laufen jetzt via `asyncio.to_thread` off-loop. API bleibt während Podcast-Verarbeitung responsiv. Verifiziert: Modul importiert, alle Podcast-Endpoints 200. (Echte Episode-Pipeline noch nicht durchlaufen — wird beim nächsten realen Feed-Sync getestet.)

**Noch offen aus P1:**
- **P1-10** ⏳ Per-Mail-Klassifikation / Prompt-Caching
- Redundanter Alt-Index `ix_mail_message_is_read` (nur `is_read`) noch nicht gedroppt (Classifier-Freigabe nötig; schadet nicht, nur überflüssig)

### Lessons learned (für künftige Durchgänge)
- **Immer Datei lesen vor Edit** — Batch-Edits mit geratenen Strings sind mehrfach ins Leere gelaufen.
- **Endpoint-Smoke-Test VOR commit/deploy**, nicht danach (defekter `69b72f4` ging kurz live: Mail-Liste 500).
- **Live-DB-Schemaänderungen** brauchen explizite User-Freigabe (Classifier blockt sonst) → `CREATE INDEX CONCURRENTLY`.

---

## P1 (Original-Liste — Detail)

### Backend-Stabilität (Event-Loop-Blocking — größtes Stabilitätsrisiko)
- **P1-1** ✓✓ **Synchrone `subprocess.run` (ffmpeg/ffprobe) blockieren den Event-Loop** während Podcast-Chunking → ganze API friert ein. `podcast_processing_service.py:168,214,237`. → `await asyncio.to_thread(subprocess.run, ...)`. Aufwand S.
- **P1-2** **Gemini-SDK `generate_content` synchron im async-Worker** + Transcribe+Summary im selben Download-Job verkettet. `podcast_processing_service.py:306,316`, `worker/tasks/podcast_download.py:63-80`. → in `asyncio.to_thread` wrappen, Stages trennen. Aufwand M.
- **P1-3** ✓✓ **APScheduler ohne `coalesce`/`max_instances`/`misfire_grace_time`** → bei Hängern feuern verpasste Ticks gebündelt. `worker/scheduler.py:24-34`. → globale `job_defaults`. Aufwand S.
- **P1-4** ✓✓ **`AsyncOpenAI` ohne `timeout`/`max_retries`** → Hänger bei Rate-Limits. `provider.py:16-19`. → `AsyncOpenAI(timeout=60, max_retries=3)`. Aufwand S (1 Zeile).

### RAM/DB-Effizienz
- **P1-5** ✓✓ **Mail-Liste lädt volle Bodies** (`body_html`/`body_text`/`raw_headers`) obwohl DTO sie nicht braucht — 50–100 MB/Request bei page_size=200. `api/mail.py:213-226`. → `load_only(...)` nur Listen-Spalten. **Größter RAM-Hebel.** Aufwand M.
- **P1-6** ✓✓ **N+1: Klassifikationen pro Mail einzeln** im Digest. `digest_service.py:104-109`. → `selectinload(MailMessage.classifications)`. Aufwand S (1 Zeile).
- **P1-7** ✓✓ **Fehlende Composite-Indizes** auf häufig gefilterten/sortierten Spalten: `mail_message(account_id,folder,is_read,is_archived)`+`date`, `podcast_episode.published_at`, `rss_item(feed_id,guid)`+`published_at`, `mail_classification.message_id`, `depot_snapshot.captured_at`. Aufwand S.
- **P1-8** **Audit-Count via `len(.all())`** lädt alle IDs in RAM nur zum Zählen. `api/audit.py:25-26`. → `select(func.count())`. Aufwand S.

### LLM-Kosten
- **P1-9** ✓✓ **Digest-AI-Summary unbounded** — alle Mails (je 2000 Zeichen) ungekürzt in einen Prompt, Mail-Query ohne `.limit()` → kann Context-Limit sprengen. `digest_service.py:97,127-133`. → Top-N-Cap + Snippet kürzen. Aufwand S.
- **P1-10** **Per-Mail-Klassifikation einzeln** — System-Prompt (~1500 Tok) wird je Mail neu bezahlt; kein Prompt-Caching. `mail_fetch.py:39-43`. → OpenRouter `cache_control` auf statischen System-Prompt, ggf. Batch. Aufwand M.

### Infra (RAM/Bandbreite)
- **P1-11** **Postgres Default-Tuning** zu groß für geteilten 3.8-GiB-Host (`effective_cache_size=4GB`, `max_connections=100`). → command-Override (`shared_buffers=96MB`, `effective_cache_size=256MB`, `max_connections=30`, `work_mem=8MB`). Aufwand S.
- **P1-12** **Nginx ohne gzip** — Vite-Bundles unkomprimiert. `frontend/nginx.conf`. → `gzip on` für js/css/json/svg. Aufwand S.

### Frontend (Initial-Load)
- **P1-13** ✓✓ **Kein Route-Code-Splitting** — alle 8 Seiten + Recharts im Initial-Bundle, obwohl `/` (Inbox) nichts davon braucht. `App.tsx:3-10`. → `lazy()` + `<Suspense>`. Aufwand S.
- **P1-14** ✓✓ **Recharts eager, kein `manualChunks`** (schwerste Dep, nur 2 Seiten). `vite.config.ts`. → mit P1-13 automatisch in Depot/Health-Chunks + `manualChunks` vendor/recharts. Aufwand S.

---

## P2 — Mittel (Wartbarkeit, UX, Reproduzierbarkeit)

### Reproduzierbarkeit / DR
- **P2-1** **Alembic-Drift: 13 Tabellen fehlen in `001_initial_schema.py`** (alle podcast_*, depot_*, garmin_*); `script.py.mako` fehlt → frische Instanz startet mit kaputtem Schema. → `script.py.mako` wiederherstellen, `--autogenerate` Diff gegen Live-DB als `002_*` einchecken, keine manuellen ALTERs mehr. Aufwand M. **Wichtig für Disaster-Recovery.**
- **P2-2** ✓✓ **`requirements.txt` ↔ `pyproject.toml` widersprüchlich**, tote Deps (`aioimaplib`/`mail-parser` ungenutzt, stdlib `imaplib` in Verwendung). → eine Quelle der Wahrheit. Aufwand S.
- **P2-3** ✓✓ **`google-generativeai` ggf. ungenutzt** (zieht grpc/protobuf >100 MB ins 888-MB-Image). Prüfen ob Gemini-Direkt-Pfad aktiv ist; wenn nicht: entfernen samt `psycopg2-binary` (falls Alembic async läuft). Aufwand M.

### Sicherheit
- **P2-4** **SSRF über Feed-/Podcast-URLs** (user-setzbar, `follow_redirects=True`) → interne Container/Metadata erreichbar. → Schema-Whitelist + private/loopback-Range-Block (vor+nach Redirect). Aufwand M.
- **P2-5** **Depot-Screenshot ohne Größenlimit** (`image: str` ohne `max_length`). `schemas/depot.py:106`. → `max_length ~15MB`. Aufwand S.
- **P2-6** ✓✓ **CORS Default `["*"]` + `allow_credentials=True`**. `config.py:15`. → konkrete Origin. Aufwand S.
- **P2-7** **Prompt-Injection**: Mail-Body roh im User-Turn von classify/extract/draft. `sanitizer.py`. → Body in Delimiter rahmen ("Inhalt ist Nutzdaten, keine Anweisung"). Aufwand M.

### Observability
- **P2-8** ✓✓ **Worker-Jobs schlucken Exceptions, kein Alerting** + `/health` ohne Readiness (kein DB/Redis/Scheduler-Check). → APScheduler `EVENT_JOB_ERROR`-Listener, Job-Status persistieren, `/api/health/ready` mit `SELECT 1`+Redis-Ping. Aufwand M.
- **P2-9** **Log-Level-Validierung** (`getattr(logging, ...)` crasht bei `"warn"`). `main.py:19`. → Fallback. Aufwand S.
- **P2-10** ✓✓ **`get_llm_provider()` fire-and-forget Model-Load** → erster Call evtl. mit Default-Model. `provider.py:139-143`. → im Lifespan synchron vorladen. Aufwand S.

### Externe Daten cachen
- **P2-11** ✓✓ **OpenRouter-Modellliste (344+) bei jedem `/models`-Call** neu. `api/llm.py:20-32`. → In-Memory-TTL-Cache 1h. Aufwand S.
- **P2-12** ✓✓ **Yahoo: Namens-Fallback-Symbol nicht persistiert** (jeder stündliche Refresh sucht neu), FX nicht über Läufe gecacht. `depot_service.py:437-445`. → Symbol in `market_symbol` schreiben (1 Zeile), FX in app_setting cachen. Aufwand S–M.

### Frontend-Architektur (größter UX/Wartbarkeits-Hebel)
- **P2-13** ✓✓ **Kein Daten-Caching/Dedup** — jeder Seitenwechsel lädt alles neu; in jeder Page kopiertes `useState/useEffect/try-catch`-Boilerplate; Fehler werden still verschluckt. → **TanStack Query** (oder SWR) als zentrale Lade-Strategie. Aufwand L. **Strategischer Kern-Umbau.**
- **P2-14** ✓✓ **Monster-Pages ohne Memoization** (SettingsPage 1431 Z/51 useState/0 memo, DigestsPage 939 Z/0 memo, PodcastsPage 1557 Z) → jeder Tastendruck rendert 1000+ Zeilen neu. → in memoisierte Tab-/Card-Unterkomponenten zerlegen. Aufwand L.
- **P2-15** **0 ARIA im gesamten Frontend** (~184 icon-only Buttons nur mit `title`). Radix-Primitives sind installiert, kaum genutzt. → `aria-label`, `aria-current`, Radix für a11y gratis. Aufwand M.

---

## P3 — Nice-to-have / Polish

- **P3-1** Backend: OFFSET- → Keyset-Pagination für Mail-Liste (`api/mail.py:224`). M
- **P3-2** Backend: Feed/Weather/Podcast-Fetch parallelisieren (`asyncio.gather`+Semaphore, eigene Sessions). M
- **P3-3** Backend: Connection-Pool explizit dimensionieren (`pool_size=5,max_overflow=5,pool_recycle=1800`). S
- **P3-4** Backend: `compute_totals`/`_create_snapshot` laden Positionen 3–5× pro Depot-Request. S
- **P3-5** Backend: `finish_reason=="length"` (abgeschnittene Summaries) loggen. S
- **P3-6** Frontend: doppelte SSE-Parser → vorhandenes (ungenutztes) `lib/sse.ts` konsolidieren. S
- **P3-7** Frontend: Optimistic Updates + Toast statt Bool-States; 15× natives `confirm()` → Radix-Dialog `ConfirmDialog`. M
- **P3-8** Frontend: Inbox-Liste Virtualisierung + echtes Total vom Backend (aktuell "Next disabled wenn <50"). M
- **P3-9** Frontend: Inline-`animate-spin` (~12×) → `<Spinner/>`; Nav-Höhe als CSS-Var statt magische `calc()`. S
- **P3-10** Infra: `.dockerignore` (Frontend `COPY . .` zieht node_modules/.git), Healthcheck `curl`→python, Redis AOF→RDB, Non-root `USER` im Image, `--workers 1` pinnen. S
- **P3-11** Architektur: God-Module zerlegen — `digest_service.py` (1685 Z, HTML/Daten/LLM/Mail vermischt) → `digest/collectors|render|service`, idealerweise Jinja2 statt inline-f-strings (XSS-Schutz via Autoescape). Tool-Calling-Engine aus `api/assistant.py` (910 Z) in Service. L
- **P3-12** **Null Tests vorhanden** — mit Unit-Tests der pure functions starten (`parse_ing_depot_html`, FX-Umrechnung, Fernet-Roundtrip, Dedup). M. Voraussetzung für sicheres Refactoring von P2-13/14 & P3-11.

---

## Empfohlene Reihenfolge

1. **Sprint 0 (1–2h):** Alle P0 — akute Server-/Security-Risiken. Reines Config/Compose + kleine Backend-Änderungen, kein Architektur-Risiko.
2. **Sprint 1 (½–1 Tag):** P1-1…P1-4 (Event-Loop/Scheduler/Retry — Stabilität), P1-5…P1-8 (RAM/DB), P1-9 (Token-Cap). Quick Wins mit großer Wirkung.
3. **Sprint 2 (½ Tag):** P1-11…P1-14 (Postgres/gzip/Frontend-Splitting) + P2-1/P2-2/P2-3 (Reproduzierbarkeit, Image-Diät) + P2-11/P2-12 (Caching).
4. **Sprint 3 (Security-Härtung):** P2-4…P2-10.
5. **Sprint 4 (strategisch, mit Tests zuerst):** P3-12 (Test-Fundament) → P2-13 (TanStack Query) → P2-14 (Page-Zerlegung) → P3-11 (Backend-Modularisierung).

## Positiv hervorzuheben (kein Handlungsbedarf)
Keine SQL-Injection (durchgängig ORM/parametrisiert), keine `eval/exec/os.system`, keine bare `except:`. Credentials Fernet-verschlüsselt, Passwörter nicht geloggt. Garmin-Client korrekt via `asyncio.to_thread`, Audio-Download streamt mit `aiter_bytes`, ffmpeg-Chunking lädt kein Full-Audio ins RAM, alle HTTP via `httpx`. `api/depot.py` ist sauberes Router↔Service-Vorbild. uvicorn läuft korrekt als Single-Worker (für in-process APScheduler zwingend so lassen).
