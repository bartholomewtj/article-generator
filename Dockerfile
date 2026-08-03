# Backend image for the hosted deployment (Hugging Face Spaces).
#
# Serves the JSON API that index.html calls. It holds no API keys and writes
# nothing to disk: ARTICLEGEN_STATELESS makes every draft render-and-return, so
# a restart loses nothing and no visitor can read another visitor's article.

FROM python:3.12-slim

# Spaces serve on 7860.
ENV PORT=7860 \
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

# Spaces runs containers as a non-root user; match it so the image behaves the
# same locally as it does deployed.
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 7860

# Identifies us to OpenAlex's "polite pool", which gets better rate limits.
# Override at deploy time with a real address.
ENV OPENALEX_MAILTO=""

CMD ["sh", "-c", "python -m articlegen web --port ${PORT}"]
