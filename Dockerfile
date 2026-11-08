# VOXORA in one container: the website is built, then served by the backend.
# Made for a free Hugging Face Space (Docker SDK, port 7860), and works on any
# Docker host (Render, Railway, Fly.io, a VPS).
#
# Secrets are set in the host's settings, never in this file:
#   DATABASE_URL       Supabase Postgres (session pooler URI, postgresql+psycopg://...)
#   SUPABASE_URL, SUPABASE_ANON_KEY, ADMIN_EMAILS
#   SECRET_KEY         any long random string (signs media links)
#   GEMINI_API_KEY     optional: Ask the Book, summaries

# ---------------------------------------------------------------- the website
FROM node:24-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- the backend
FROM python:3.13-slim

# OpenCV (used by OCR) needs these system libraries. Tesseract is the light OCR
# engine (its own process, no models held in memory), so scanned pages work on 512 MB.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-tel \
 && rm -rf /var/lib/apt/lists/*

# Hugging Face runs containers as user 1000.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=7860 \
    ENVIRONMENT=production \
    LOG_JSON=true \
    AUDIO_DELIVERY=device \
    TTS_PROVIDER=edge \
    TTS_ENABLED_PROVIDERS=edge,piper,openai,elevenlabs

WORKDIR /home/user/app
COPY --chown=user backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir --user -r backend/requirements.txt

COPY --chown=user backend/ backend/
COPY --chown=user --from=web /web/dist frontend/dist

EXPOSE 7860
CMD ["python", "backend/main.py"]
