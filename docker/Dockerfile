FROM python:3.12-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib \
    OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 GENERATOR_WORK_DIR=/work \
    NUMBA_CACHE_DIR=/work/cache/numba
RUN apt-get update && apt-get install -y --no-install-recommends libopenmpi3 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONPATH=/app
RUN pip install --no-cache-dir uv==0.8.22
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-cache --frozen --no-dev --no-install-project
COPY service ./service
COPY validation ./validation
COPY LICENSE ./LICENSE
RUN uv sync --no-cache --frozen --no-dev
RUN useradd --create-home --uid 10001 generator && mkdir /work && chown generator /work
ENV PATH=/app/.venv/bin:$PATH
EXPOSE 8090

FROM base AS test
RUN uv sync --no-cache --frozen
COPY tests ./tests
USER generator
CMD ["pytest", "-q", "-p", "no:cacheprovider"]

FROM base AS wheel-test
RUN uv build --wheel --out-dir /tmp/dist
RUN uv pip install --target /tmp/isolated --no-deps /tmp/dist/*.whl
COPY scripts/check_wheel.py /tmp/check_wheel.py
RUN cd /tmp && PYTHONPATH=/tmp/isolated python /tmp/check_wheel.py

FROM base AS runtime
USER generator
CMD ["uvicorn", "service.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090"]
