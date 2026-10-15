FROM python:3.12 AS builder
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=on
ENV PIP_DEFAULT_TIMEOUT=200

RUN python -m venv /opt/poetry
RUN /opt/poetry/bin/pip install --no-cache-dir poetry==1.8.3
RUN ln -svT /opt/poetry/bin/poetry /usr/local/bin/poetry
RUN poetry config virtualenvs.in-project true

WORKDIR /app
COPY pyproject.toml poetry.lock README.md ./
RUN poetry install --no-interaction --no-ansi --no-root --without=dev \
    && rm -rf ~/.cache/pypoetry/{cache,artifacts}

COPY ./src ./src
RUN poetry install --no-interaction --no-ansi --without=dev


FROM python:3.12-slim AS main
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq5 libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app /app
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH=/app/src
ENV DJANGO_SETTINGS_MODULE=millarym_core.settings
ENV MEDIA_ROOT=/app/media
RUN install -o appuser -g appuser -d $MEDIA_ROOT
USER appuser
EXPOSE 8000/tcp
CMD ["gunicorn", "--bind=0.0.0.0:8000", "--workers=3", "millarym_core.wsgi"]
