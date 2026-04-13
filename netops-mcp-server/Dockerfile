# NetOps MCP Server — reproducible install via uv.lock; non-root runtime
# Policy: Python 3.12 only (Dependabot ignores 3.13+ for this image).
# Pinned index digest (docker buildx imagetools inspect python:3.12-slim)
FROM python:3.12-slim@sha256:804ddf3251a60bbf9c92e73b7566c40428d54d0e79d3428194edf40da6521286 AS builder

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim@sha256:804ddf3251a60bbf9c92e73b7566c40428d54d0e79d3428194edf40da6521286

WORKDIR /app
RUN adduser --disabled-password --gecos "" mcp

COPY --from=builder --chown=mcp:mcp /app/.venv /app/.venv
COPY --chown=mcp:mcp pyproject.toml README.md ./
COPY --chown=mcp:mcp src ./src

USER mcp
ENV PATH="/app/.venv/bin:${PATH}" \
    VIRTUAL_ENV="/app/.venv" \
    MCP_PORT=8010

EXPOSE 8010
CMD ["python", "-m", "netops_mcp_server.server"]
