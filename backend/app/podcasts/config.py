"""Paths and settings for the podcast service. Everything is overridable by environment variable."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=value). Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip("\"'"))


_load_dotenv(Path(os.environ.get("ENV_FILE", ROOT / ".env")))
FEEDS_FILE = Path(os.environ.get("PODCAST_FEEDS", ROOT / "content" / "podcasts" / "feeds.yaml"))
DATA_DIR = Path(os.environ.get("PODCASTS_DATA", ROOT / "backend" / "data" / "podcasts"))
DB_PATH = DATA_DIR / "podcasts.sqlite"
AUDIO_DIR = DATA_DIR / "audio"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
CLIP_DIR = DATA_DIR / "clips"

USER_AGENT = "LanguageApp/1.0 (personal podcast client; +https://github.com/JonaszWD/SimpleLanguageLearning)"

POLL_MINUTES = int(os.environ.get("PODCAST_POLL_MINUTES", "180"))     # never refetch a feed sooner than this
CACHE_MB = int(os.environ.get("PODCAST_CACHE_MB", "2000"))            # audio cache cap
KEEP_DAYS = int(os.environ.get("PODCAST_KEEP_DAYS", "14"))            # delete listened episodes after N days
MAX_AUDIO_MB = int(os.environ.get("PODCAST_MAX_AUDIO_MB", "400"))     # refuse bigger files

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "small")              # tiny | base | small | medium | large-v3
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "auto")             # auto | cpu | cuda
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")           # int8 is fine on CPU
WHISPER_ENABLED = os.environ.get("WHISPER_ENABLED", "1") != "0"

# ElevenLabs Scribe (speech-to-text) is preferred over local Whisper when a key is set. Key comes from env/.env only.
ELEVENLABS_MODEL = os.environ.get("ELEVENLABS_STT_MODEL", "scribe_v1")
ELEVENLABS_ENABLED = os.environ.get("ELEVENLABS_ENABLED", "1") != "0"


def elevenlabs_key() -> str | None:
    return os.environ.get("ELEVENLABS_API_KEY") or None


EVENING_HOUR = int(os.environ.get("PODCAST_EVENING_HOUR", "19"))      # when tomorrow's audio is prepared
AUTOMATION = os.environ.get("PODCAST_AUTOMATION", "1") != "0"


def ensure_dirs() -> None:
    for d in (DATA_DIR, AUDIO_DIR, TRANSCRIPT_DIR, CLIP_DIR):
        d.mkdir(parents=True, exist_ok=True)
