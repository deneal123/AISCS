FROM node:22-bookworm-slim
LABEL aspa.simulation.owner="simctl"
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1
