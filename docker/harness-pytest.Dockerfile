# Изолированный образ приёмки установленного pytest, не production-рантайм.
# Сеть нужна только сборщику. Политика пользовательского процесса не меняется:
# непривилегированный пользователь, read-only корень и network=none.
FROM gpthub-workspace-runtime:harness-dev
COPY docker/acceptance/pytest-requirements.txt /opt/gpthub-acceptance/pytest-requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: --require-hashes \
    -r /opt/gpthub-acceptance/pytest-requirements.txt \
    && chmod -R a-w /opt/gpthub-acceptance
