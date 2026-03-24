# NetOps MCP Server — reproducible install via uv.lock; non-root runtime
# Policy: Python 3.12 only (Dependabot ignores 3.13+ for this image).
# Pinned index digest (docker buildx imagetools inspect python:3.12-slim)
FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4 AS builder

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

FROM python:3.12-slim@sha256:3d5ed973e45820f5ba5e46bd065bd88b3a504ff0724d85980dcd05eab361fcf4

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
