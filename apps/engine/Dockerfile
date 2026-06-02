# Engine image. Built from Docker Hub's python base — NOT nixpacks' ghcr.io image — so a build never depends on
# ghcr.io being up (a ghcr.io 502 was failing deploys before they reached our code). Copying the full source
# BEFORE `pip install .` also ships a real wheel containing the cosmu package (nixpacks copied only
# pyproject.toml first, producing an empty package — the earlier runtime ModuleNotFoundError). Deps are pure
# manylinux wheels (psycopg2-binary, ccxt, cryptography, pydantic-core, aiohttp…), so the slim base needs no
# compiler. Railway injects $PORT and overrides CMD via railway.toml's startCommand; the CMD is a local fallback.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY . /app
RUN pip install .

EXPOSE 8000
# `python -m` (not the bare uvicorn console script) so /app is on sys.path even if the install layer regresses.
CMD ["sh", "-c", "python -m uvicorn cosmu.api.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
