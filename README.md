# Language App

Offline-first iPhone web app (PWA) for a daily Spanish routine. JS frontend (no build step), FastAPI backend, uv + Docker.

```
frontend/   ES modules, service worker, IndexedDB (all user data lives on the phone)
backend/    FastAPI: serves the frontend, parses Anki .apkg files (/api/anki/import)
DESIGN.md   Source of truth for every visual decision
```

## Run

```sh
cd backend && uv sync && uv run uvicorn app.main:app --reload   # http://localhost:8000
docker compose up --build                                        # same, containerised
cd backend && uv run pytest
```

Service workers need HTTPS except on localhost. To install on an iPhone, serve over HTTPS (reverse proxy / tunnel), open in Safari, Share → Add to Home Screen.

## Offline and live updates

`./frontend` is bind-mounted into the container, so editing a frontend file needs no Docker rebuild. The server generates `/sw.js` with a hash of all frontend files and the precache list (`backend/app/build.py`). Open apps check for a new version on launch, on return to the app and every 15 min, then reload on the next screen change. Settings shows the running version and has a manual check. Rebuild the image only when backend code or dependencies change (`docker compose up --build -d`).

The service worker precaches the shell. Cards, progress and settings are in IndexedDB. Only Anki import needs the server. Settings → Export keeps a backup.

## Weekly plan

`frontend/js/plan.js`. Anki is 10 min every day including weekends. Saturday adds a 15 min talking unit.

## Practice material

None yet. Listening, shadowing and reading read from the IndexedDB `library` store (schema in `frontend/js/views/practice.js`).

## Content packs (Anki deck + audio + shadowing clips)

```sh
cd backend && uv run python -m app.packs build ../deck.apkg --id spanish-9000 --title "Spanish 9000 sentences (B1+)" --min-difficulty 2500
```
Packs live in `content/packs/` (committed; mounted into Docker; `index.json` lists them). On the phone: More → Import Anki deck → Download for offline.

## Reading (El Mundo / El País) with tap-to-translate

- Server fetches El Mundo articles (allowlist in `app/articles.py`, extend with `ARTICLE_HOSTS`). El País blocks automated fetches, so paste its text instead.
- Every import looks each word up in an offline dictionary and stores the glossary with the article, so reading works offline.
- Build the dictionary once (about 1.1 GB download, 180 MB result):

```sh
cd backend/data/dict && curl -LO https://kaikki.org/dictionary/Spanish/kaikki.org-dictionary-Spanish.jsonl
cd ../.. && uv run python -m app.dictionary build data/dict/kaikki-spanish.jsonl
```
Dictionary data: Wiktionary via kaikki.org, CC BY-SA 4.0.

## Hosting on GitHub Pages (free, public repo)

The whole app is static, so GitHub Pages can host it: `.github/workflows/pages.yml` assembles `frontend/` + `content/packs/` into one site (and generates `sw.js` with `backend/app/build.py`).

1. Settings → Pages → Source: **GitHub Actions**.
2. Push to `main`. Live at `https://<user>.github.io/<repo>/`. Open it in Safari, Share → Add to Home Screen.
3. Later pushes redeploy, and installed phones update themselves.

All URLs are relative (`frontend/js/config.js`), so the same files run at `/` (Docker) and `/<repo>/` (Pages). Static hosting has no backend, so article import and the daily article sync need the Docker server (or a scheduled job that publishes articles as static files). Limits: 1 GB site, soft 100 GB/month bandwidth.

## Grammar (B1 → B2 syllabus)

- `content/grammar/syllabus.json`: 32 weekly topics as data (ES + EN explanation, key rules, common mistakes for English speakers, tags, and a `verify` list where the content must be checked against the Instituto Cervantes Plan curricular). Add a track (e.g. `b2-c1`) to extend it.
- `content/grammar/exercises/<topic>.json`: generated exercises (cloze, conjugation, multiple choice, transformation, error correction). `review.json` lists items a human should look at; `apkg/` has one Anki deck per topic.
- The app syncs all of it into IndexedDB (works offline). Week 1 starts on the date set in Settings (default: the Monday you first open it). About 15% of new cards are grammar/mistake cards; the Monday/Thursday Grammar task runs explanation → exercises → write 5 sentences. Wrong answers are logged, become cloze mistake cards (capped per day), and feed Stats. A topic under 70% after two weeks gets extra practice. "Add a mistake" is in the More sheet.

```sh
cd backend
uv run python -m app.grammar.build                                  # rebuild exercises (deterministic: Tatoeba + Wiktionary conjugations)
uv run python -m app.grammar.build --topic por-para --count 30
uv run python -m app.grammar.build --llm --dry-run                  # preview Claude prompts, no calls, no writes
ANTHROPIC_API_KEY=... uv run python -m app.grammar.build --llm --topic estilo-indirecto-pasado   # results cached in data/grammar/llm-cache
uv run python -m app.grammar.export_apkg                            # Anki decks with stable ids (re-import updates, no duplicates)
```
Needs `backend/data/grammar/conj.sqlite` (built from the Kaikki dump: `uv run python -m app.grammar.conjugation build data/dict/kaikki-spanish.jsonl`). Tests: `uv run pytest` and `node frontend/tests/grammar.test.mjs`.
Sources: sentences Tatoeba (CC BY 2.0 FR); conjugations Wiktionary via kaikki.org (CC BY-SA). LLM items are tagged `source: "llm"`.

## Podcasts (needs your own server)

Podcast audio can't be fetched by a browser (no CORS) and Whisper can't run on GitHub Pages, so this part needs the Docker server running somewhere your phone can reach over HTTPS (e.g. Tailscale or a reverse proxy; an `https://` page can't call plain `http://`). If the app is served from Pages, set `API_BASE` in `frontend/js/config.js` to the server URL and `CORS_ORIGINS` in `docker-compose.yml` to the Pages origin. Audio is stored only for personal use, on the server's disk and your phone. It is never re-hosted.

```sh
cd backend
uv run python -m app.podcasts feeds add hoy-hablamos --title "Hoy Hablamos" --level A2 --accent Spain --transcript
uv run python -m app.podcasts feeds resolve "Hoy Hablamos"   # lists candidates; saves only after you pick one and confirm
uv run python -m app.podcasts feeds validate                  # dead feeds, latest episode dates
uv run python -m app.podcasts plan --date 2026-11-03          # what would be picked, and why
uv run python -m app.podcasts prepare                         # download + transcribe tomorrow's episodes
```
- `content/podcasts/feeds.yaml` is the registry (id, title, feed_url, level A2–C1, accent, mode, has_official_transcript, episode_length_min, active, notes). URLs are never guessed. `PODCASTINDEX_API_KEY` / `_SECRET` add Podcast Index to the iTunes search.
- Transcripts: the publisher's (`<podcast:transcript>`: SRT, VTT, JSON), else Whisper locally (`uv sync --extra whisper`, `WHISPER_MODEL=tiny|base|small…`; Docker: `WITH_WHISPER=1 docker compose build`), else none. Whisper output is marked and can contain errors. ffmpeg is required for Whisper and for audio clips (included in the Docker image).
- Comprehension questions use the Claude API (`ANTHROPIC_API_KEY`), are cached, and are marked `llm`.
- Each evening the server prepares tomorrow's episodes; the app downloads them when opened on a network that can reach the server (iOS can't run background downloads). Tomorrow's readiness shows on Today.
- Caps and timing: `PODCAST_CACHE_MB`, `PODCAST_KEEP_DAYS`, `PODCAST_POLL_MINUTES`, `PODCAST_EVENING_HOUR`. Weekday mapping (default Mon/Wed/Fri extensive, Tue/Thu intensive) is in Settings.

### Transcripts with ElevenLabs

Put `ELEVENLABS_API_KEY=...` in `.env` (git- and docker-ignored). With a key, episodes without a usable publisher
transcript are transcribed by ElevenLabs Scribe: word timestamps, speaker labels, cut into sentences at punctuation,
pauses and speaker changes. The audio file is uploaded to ElevenLabs for this. If the call fails, local Whisper is the
fallback (when installed). Order: publisher transcript, ElevenLabs, Whisper, none.

## Talking unit (Saturday)

Free spoken conversation with an AI partner on ElevenLabs Agents (`backend/app/talk.py`, `frontend/js/talk.js`, route `#/talk`). B1→B2 Spanish, short turns, gentle in-line corrections, uses the week's grammar topic.

- Needs `ELEVENLABS_API_KEY` in `.env` with **Agents (convai) read + write** enabled (elevenlabs.io → API Keys). The key stays on the server; the phone gets a short-lived signed WebSocket URL from `POST /api/talk/session`.
- The agent is created on first use; its id is cached in `backend/data/talk/agent.json` and updated when the prompt in `talk.py` changes. Set `TALK_AGENT_ID` to use an agent you made in the ElevenLabs dashboard (give it `{{topic}}` and `{{focus}}` variables).
- Optional env: `TALK_VOICE_ID`, `TALK_TTS_MODEL` (default `eleven_flash_v2_5`), `TALK_LLM`.
- Online only, and needs the Docker server (no static Pages). iPhone asks for microphone permission on first use.
