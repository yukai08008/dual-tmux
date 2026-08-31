FROM python:3.12-slim

WORKDIR /opt/dual-tmux
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

ENV DUAL_TMUX_HOME=/data
EXPOSE 8790
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/health', timeout=3)"
ENTRYPOINT ["dt", "feishu", "bridge", "--host", "0.0.0.0", "--port", "8790"]
