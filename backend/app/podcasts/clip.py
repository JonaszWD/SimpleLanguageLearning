"""Cut a short audio clip for a phrase card, using ffmpeg (needed only for clips)."""

import hashlib
import shutil
import subprocess
from pathlib import Path

from . import config


def available() -> bool:
    return shutil.which("ffmpeg") is not None


def cut(audio: Path, start: float, end: float, pad: float = 0.25) -> Path:
    """Returns an mp3 of [start, end] (a little padding each side), cached on disk."""
    if not available():
        raise RuntimeError("ffmpeg is not installed")
    if not 0 <= start < end or end - start > 60:
        raise ValueError("clips must be between 0 and 60 seconds")
    config.ensure_dirs()
    key = hashlib.sha1(f"{audio.name}|{start:.2f}|{end:.2f}".encode()).hexdigest()[:16]
    out = config.CLIP_DIR / f"{key}.mp3"
    if not out.exists():
        s = max(0.0, start - pad)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{s:.2f}", "-to", f"{end + pad:.2f}", "-i", str(audio),
                        "-vn", "-ac", "1", "-ar", "24000", "-c:a", "libmp3lame", "-q:a", "6", str(out)], check=True, timeout=60)
    return out
