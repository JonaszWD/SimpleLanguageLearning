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

`frontend/js/plan.js`. Anki is 10 min every day including weekends.

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
