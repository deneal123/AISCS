FROM python:3.13-slim

ARG NEXUS_PYPI_INDEX_URL

ENV HOME="/dude"
ENV PYTHONPATH=$HOME

RUN groupadd -g 999 dudes && \
    useradd -u 999 -m -g dudes -s /bin/bash dude && \
    mkdir -p ${HOME} && chown dude:dudes $HOME

RUN mkdir -p /var/lib/app/storage && chown -R dude:dudes /var/lib/app

WORKDIR ${HOME}

RUN apt-get update && apt-get install -y curl build-essential netcat-openbsd \
    gcc \
    libpq-dev \
    postgresql-client \
    cargo \
    rustc \
    gosu \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install -i "${NEXUS_PYPI_INDEX_URL:-https://pypi.org/simple}" --disable-pip-version-check --no-cache-dir uv

COPY --chown=dude:dudes ./backend/pyproject.toml ./backend/uv.lock ${HOME}/

RUN uv sync --frozen

ENV PATH="${HOME}/.venv/bin:$PATH"

COPY --chown=dude:dudes ./backend/service ${HOME}/service
COPY --chown=dude:dudes ./backend/alembic ${HOME}/alembic
COPY --chown=dude:dudes ./backend/docker/entrypoints.sh ${HOME}
COPY --chown=dude:dudes ./backend/docker/docker-entrypoint.sh ${HOME}

# Нормализуем переводы строк (CRLF->LF) и делаем исполняемыми. CRLF в shebang
# ломает запуск в Linux: env: 'bash\r': No such file or directory.
RUN sed -i 's/\r$//' ${HOME}/entrypoints.sh ${HOME}/docker-entrypoint.sh \
    && chmod +x ${HOME}/entrypoints.sh ${HOME}/docker-entrypoint.sh

ENTRYPOINT ["/dude/docker-entrypoint.sh"]

CMD ["server"]
