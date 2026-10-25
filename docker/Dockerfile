FROM python:3.12-slim

WORKDIR /opt/research-sidecar
ARG UV_VERSION=0.11.15
RUN pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml uv.lock README.md ./
COPY service /opt/research-sidecar/service
RUN uv sync --frozen --no-dev --no-editable && uv cache clean
COPY docker/entrypoint.sh /opt/research-sidecar/entrypoint.sh
COPY data /data
COPY knowledge /opt/research-sidecar/knowledge
RUN chmod +x /opt/research-sidecar/entrypoint.sh \
    && chown -R 65532:65532 /opt/research-sidecar /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/research-sidecar/.venv/bin:$PATH \
    HOME=/tmp \
    PORT=8080 \
    RESEARCH_DATA_DIR=/data
EXPOSE 8080
USER 65532:65532
ENTRYPOINT ["/opt/research-sidecar/entrypoint.sh"]
