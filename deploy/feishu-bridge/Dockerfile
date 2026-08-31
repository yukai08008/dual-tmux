FROM python:3.12-slim

WORKDIR /opt/dual-tmux
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

ENV DUAL_TMUX_HOME=/data
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD dt daemon --status >/dev/null || exit 1
ENTRYPOINT ["dt", "daemon"]
