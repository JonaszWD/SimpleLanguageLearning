# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
One learner (the owner): an English speaker studying Spanish at B1→B2, using an iPhone as the main device, following a daily routine. No other audiences confirmed.

## Product Purpose
Offline-first PWA that runs a fixed daily Spanish routine: Anki-style spaced-repetition cards (10 min every day, weekends included), a 32-week B1→B2 grammar syllabus with exercises, reading of real news articles with tap-to-translate, podcasts, and listening/shadowing practice. Success: the learner finishes the day's plan without friction and keeps the streak.

## Positioning
A single fixed daily routine, with all user data on the phone, working offline and with no account. Wrong answers feed back into mistake cards and extra grammar practice.

## Operating Context
Used on iPhone, installed from Safari via Add to Home Screen. Hosted statically on GitHub Pages or via the Docker FastAPI server. Content comes from Anki .apkg packs, El Mundo articles, Tatoeba sentences, and Wiktionary data (kaikki.org).

## Capabilities and Constraints
- Offline-first; data lives in IndexedDB; service worker precaches the shell.
- Frontend is plain ES modules with no build step; backend is FastAPI managed with uv.
- One-handed iPhone use: controls must be thumb-reachable.
- Static hosting has no backend, so article import and Anki import need the Docker server.
- Grammar content items marked `verify` still need checking against the Instituto Cervantes Plan curricular.

## Brand Commitments
None confirmed. DESIGN.md is the visual source of truth (see Open Decisions).

## Evidence on Hand
Real content under `content/` (packs, articles, grammar, podcasts). No testimonials, users, or metrics exist; do not invent any.

## Product Principles
1. The daily plan comes first: the next task is always obvious.
2. Everything works offline; the network is an optional upgrade.
3. Mistakes are material: errors turn into practice, not just a score.
4. Real Spanish over synthetic exercises where possible.
5. One thumb is enough.

## Open Decisions
- DESIGN.md is titled "ElevenLabs-design-analysis" and describes a marketing site, not this app. Confirm whether it is the intended visual authority or should be replaced by `/impeccable document` of the current UI.
- Accessibility standard (dark mode, text scaling) not established.
