# CPU-сайдкар. Runtime и GGUF закреплены отдельно, модель не включена в Git/образ.
FROM ubuntu:24.04
ARG JSONSCHEMA_DEB_VERSION=4.10.3-2ubuntu1
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl python3 "python3-jsonschema=${JSONSCHEMA_DEB_VERSION}" libgomp1 libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
ARG LLAMA_VERSION=b11846
ARG LLAMA_SHA256=eb26d338963f04eda3f70f23ef4a8575d44bc643f58d26c2f51925a58fbd43ff
RUN curl --fail --location --proto '=https' --tlsv1.2 \
      "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_VERSION}/llama-${LLAMA_VERSION}-bin-ubuntu-x64.tar.gz" \
      --output /tmp/llama.tar.gz \
    && printf '%s  /tmp/llama.tar.gz\n' "${LLAMA_SHA256}" | sha256sum --check --strict \
    && mkdir /opt/llama \
    && tar --extract --gzip --file /tmp/llama.tar.gz --directory /opt/llama --strip-components=1 \
    && rm /tmp/llama.tar.gz \
    && test -x /opt/llama/llama-server
RUN groupadd --gid 10001 local-llm && useradd --uid 10001 --gid 10001 --no-create-home local-llm \
    && mkdir /models && chown 10001:10001 /models
WORKDIR /opt/gpthub
COPY service ./local_llm/service/
COPY scripts/__init__.py scripts/provision_model.py ./local_llm/scripts/
RUN python3 -c "from local_llm.service.main import main; from local_llm.scripts.provision_model import main as provision; from local_llm.service.presentation.http import Gateway"
USER 10001:10001
ENV LOCAL_LLM_HOST=0.0.0.0
EXPOSE 8080
CMD ["python3", "-m", "local_llm.service"]
