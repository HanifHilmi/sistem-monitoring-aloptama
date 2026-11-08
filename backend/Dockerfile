# SIMOLA backend image: API, worker and CLI share this image (PRD DOC-01/03).
FROM python:3.13.13-slim-bookworm AS build
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
RUN pip install --no-cache-dir uv==0.12.2
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY simola ./simola
RUN uv sync --frozen --no-dev

FROM python:3.13.13-slim-bookworm AS runtime
# Pango and HarfBuzz for WeasyPrint, which draws the monthly PDF report (R3.5); its fonts ship with the code.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin simola
WORKDIR /app
COPY --from=build --chown=simola:simola /app /app
ENV PATH="/app/.venv/bin:${PATH}" \
    XDG_CACHE_HOME=/tmp/.cache \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER simola
EXPOSE 8000
CMD ["uvicorn", "--factory", "simola.api.app:create_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
