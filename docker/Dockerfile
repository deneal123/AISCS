FROM python:3.12-slim

ARG FASTAPI_VERSION=0.116.2
ARG UVICORN_VERSION=0.35.0
RUN pip install --no-cache-dir \
        "fastapi==${FASTAPI_VERSION}" \
        "uvicorn==${UVICORN_VERSION}"

WORKDIR /opt/research-sidecar
COPY service /opt/research-sidecar/service
COPY docker/entrypoint.sh /opt/research-sidecar/entrypoint.sh
COPY data /data
RUN chmod +x /opt/research-sidecar/entrypoint.sh \
    && chown -R 65532:65532 /opt/research-sidecar /data

ENV PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    PORT=8080 \
    RESEARCH_DATA_DIR=/data
EXPOSE 8080
USER 65532:65532
ENTRYPOINT ["/opt/research-sidecar/entrypoint.sh"]
