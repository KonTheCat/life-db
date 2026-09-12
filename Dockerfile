FROM python:3.14-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY server/ server/
COPY dispatcher/ dispatcher/

ENV PATH="/app/.venv/bin:$PATH"

# mcp-server (Container App) uses this default CMD as-is;
# notification-dispatcher (Container Apps Job) overrides the command to
# `uv run python dispatcher/run.py` -- same image, different entrypoint,
# per plan §10.
CMD ["uv", "run", "python", "server/main.py"]
