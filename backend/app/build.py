"""Describe the frontend build so the service worker updates itself.

The version is a hash of every served file, so editing any frontend file changes it:
phones then download the new files without the Docker image being rebuilt.
"""

import hashlib
import json
from pathlib import Path

_cache: dict = {"sig": None, "info": None}


def _files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*")
        if p.is_file() and p.name != "sw.js" and not any(part.startswith(".") for part in p.relative_to(root).parts)
    )


def build_info(root: Path) -> dict:
    files = _files(root)
    sig = tuple((str(p), p.stat().st_size, p.stat().st_mtime_ns) for p in files)
    if _cache["sig"] != sig:  # rehash only when something changed
        h = hashlib.sha1()
        shell = ["./"]
        for p in files:
            rel = p.relative_to(root).as_posix()
            h.update(rel.encode())
            h.update(p.read_bytes())
            shell.append(rel)
        _cache.update(sig=sig, info={"version": h.hexdigest()[:10], "shell": shell})
    return _cache["info"]


def service_worker_source(root: Path) -> str:
    return f"self.__BUILD__ = {json.dumps(build_info(root))};\n" + (root / "sw.js").read_text()


def write_site(frontend: Path, out: Path) -> None:
    """Static hosting: copy the app to `out` with a generated sw.js (no server involved)."""
    import shutil

    shutil.copytree(frontend, out, dirs_exist_ok=True)
    (out / "sw.js").write_text(service_worker_source(frontend))


if __name__ == "__main__":
    import sys

    write_site(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"wrote {sys.argv[2]} (version {build_info(Path(sys.argv[1]))['version']})")
