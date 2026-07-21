# Сайдкар парсинга документов: opendataloader-pdf (Hancom, Apache-2.0) → markdown.
#
# Ядро opendataloader — Java, а python-пакет лишь запускает `java -jar`. Поэтому
# сервис живёт отдельным контейнером: иначе JRE (~190 МБ) уехала бы в образ backend
# и во все три celery-воркера (у них общий Dockerfile), а JVM стартовала бы прямо
# в процессе, обслуживающем API.
#
# Колесо с PyPI УЖЕ содержит собранный shaded-JAR — Maven тут не нужен.
FROM eclipse-temurin:21-jre-jammy

# LibreOffice headless доводит office-форматы до PDF (сам opendataloader парсит только
# PDF). Шрифты обязательны: без них кириллица в конвертированном PDF теряет глифы и
# извлечённый текст превращается в мусор.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip curl ca-certificates \
        libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress \
        fonts-dejavu-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# openpyxl — для xlsx/xls/ods: электронные таблицы читаем по ячейкам, а не через
# PDF-рендер (LibreOffice не печатает сетку в PDF → opendataloader не видит таблицу).
ARG OPENDATALOADER_VERSION=2.4.7
ARG OPENPYXL_VERSION=3.1.5
# ⚠️ tomli — БЭКПОРТ tomllib, и он здесь не «на всякий случай». База этого сайдкара
# `eclipse-temurin:21-jre-jammy`, её `python3` — 3.10, а tomllib вошёл в stdlib
# только в 3.11. У остальных сайдкаров образы на 3.12, там пакет не нужен.
# Поймано СБОРКОЙ: без него контейнер падал на импорте settings.py — то есть
# предположение «tomllib есть везде» было неверным ровно для одного из четырёх.
# Транспорт сайдкара. Версии совпадают с dev-зависимостями pyproject.toml: тесты
# должны проверять то, что реально исполняется в образе.
ARG FASTAPI_VERSION=0.115.6
ARG UVICORN_VERSION=0.34.0
RUN pip3 install --no-cache-dir \
        "tomli==2.0.1" \
        "opendataloader-pdf==${OPENDATALOADER_VERSION}" \
        "openpyxl==${OPENPYXL_VERSION}" \
        "fastapi==${FASTAPI_VERSION}" \
        "uvicorn==${UVICORN_VERSION}"

# ⚠️ core.py ОБЯЗАТЕЛЕН: логика вынесена туда из app.py, и без него контейнер
# падает на импорте. Проверяется тем, что образ действительно собирается и
# отвечает на /health — иначе такой промах виден только в проде.
# Код — каталогом `service/`, как у backend.
COPY service /opt/odl-sidecar/service
COPY docker/entrypoint.sh /opt/odl-sidecar/entrypoint.sh
RUN chmod +x /opt/odl-sidecar/entrypoint.sh

# HOME нужен LibreOffice: без записываемой домашней директории soffice падает.
#
# ⚠️ ТАЙМАУТЫ ЗДЕСЬ ПЕРЕКРЫВАЮТ ДЕФОЛТЫ `contracts.py`, поэтому правятся ВМЕСТЕ с ними
# (и с обоими compose-файлами — там свои `:-` дефолты). Было 120+300=420 при клиентском
# таймауте 180: сервер продолжал работу после ухода клиента. Сумма обязана быть < 180.
ENV HOME=/tmp \
    PYTHONUNBUFFERED=1 \
    JAVA_TOOL_OPTIONS="-Djava.awt.headless=true" \
    ODL_MAX_BYTES=20971520 \
    ODL_LO_TIMEOUT_SEC=70 \
    ODL_PARSE_TIMEOUT_SEC=95 \
    PORT=8080
EXPOSE 8080
ENTRYPOINT ["/opt/odl-sidecar/entrypoint.sh"]
