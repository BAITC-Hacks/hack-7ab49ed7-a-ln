FROM ghcr.io/astral-sh/uv:0.9.15 AS uv

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY sample_data ./sample_data
RUN uv sync --frozen --no-dev --no-editable \
    && useradd --uid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin moneygraph \
    && mkdir -p /data \
    && chown moneygraph /data
USER moneygraph
ENV MG_DATA_DIR=/data \
    MG_DEMO_DATA_DIR=/app/sample_data
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/ready', timeout=3)"
# The API is only reachable through the frontend proxy on the compose network, so its forwarded
# client address is trusted (the login rate limiter keys on it).
CMD ["uvicorn", "mg_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-access-log"]
