FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy FRONTEND_DIR=/srv/frontend
# ffmpeg: cuts audio clips for phrase cards and decodes audio for Whisper
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/backend

COPY backend/pyproject.toml backend/uv.lock ./
# Optional local transcription (adds a few hundred MB): docker compose build --build-arg WITH_WHISPER=1
ARG WITH_WHISPER=0
RUN if [ "$WITH_WHISPER" = "1" ]; then uv sync --frozen --no-dev --no-install-project --extra whisper; else uv sync --frozen --no-dev --no-install-project; fi

COPY backend/app ./app
COPY frontend /srv/frontend

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
