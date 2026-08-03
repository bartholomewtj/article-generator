# Backend image for the hosted deployment.
#
# Serves the JSON API that index.html calls. It holds no API keys and writes
# nothing to disk: ARTICLEGEN_STATELESS makes every draft render-and-return, so
# a restart loses nothing and no visitor can read another visitor's article.
#
# Host-neutral. Every host that matters injects PORT and expects the app to bind
# it, which the CMD below does. Currently deployed on Render (see render.yaml);
# it also runs unchanged on Fly, Cloud Run, or a plain `docker run`.

FROM python:3.12-slim

# A default for a bare `docker run`; the host overrides it in practice.
ENV PORT=8000 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ARTICLEGEN_STATELESS=1 \
    ARTICLEGEN_ALLOWED_ORIGINS=https://bartholomewtj.github.io \
    ARTICLEGEN_RATE_LIMIT=20

WORKDIR /app

# Dependencies first so a code change doesn't reinstall them.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml ./
COPY articlegen ./articlegen
RUN pip install --no-cache-dir --no-deps -e .

# Run unprivileged, as the hosts do, so local behaviour matches deployed.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Identifies us to OpenAlex's "polite pool", which gets better rate limits.
# Override at deploy time with a real address.
ENV OPENALEX_MAILTO=""

CMD ["sh", "-c", "python -m articlegen web --port ${PORT}"]
