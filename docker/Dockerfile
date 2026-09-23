FROM node:20-alpine AS base

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm install

COPY . .
# CRLF->LF в shebang, иначе в контейнере: env: 'bash\r': No such file or directory.
RUN sed -i 's/\r$//' docker/docker-entrypoint.sh && chmod +x docker/docker-entrypoint.sh

FROM base AS dev

ENTRYPOINT ["/app/docker/docker-entrypoint.sh"]
CMD ["npm", "start"]

FROM base AS builder

# ⚠️ ЗДЕСЬ НАМЕРЕННО НЕТ REACT_APP_*_BASE_URL, И ДОБАВЛЯТЬ ИХ НЕЛЬЗЯ.
#
# Раньше стояло `ENV REACT_APP_API_BASE_URL=${SERVICE__REACT_APP_API_BASE_URL}`.
# Это не работало и не могло: в Dockerfile `${VAR}` разворачивается из ARG/ENV
# СБОРКИ, а такого ARG не объявлено — подставлялась пустая строка. Строки убраны
# как мёртвые.
#
# И это не тот случай, когда «надо просто пробросить через ARG». Прод-бандл обязан
# ходить на СВОЙ origin: он раздаётся nginx'ом, который сам проксирует /api и /ws.
# Клиент это умеет — при пустом значении httpClient берёт `/`, а WS собирает
# `ws(s)://window.location.host` (см. shared/api/httpClient.js и
# features/chat/model/useWebSocketChat.js). Именно поэтому прод и работает.
#
# А в `.env.example` эти ключи заданы как `http://localhost:8000` — они нужны DEV,
# где фронт живёт на 3000, бэкенд на 8000 и CRA читает их в рантайме `npm start`.
# Пробросить их сюда через ARG означало бы ЗАШИТЬ `localhost:8000` в прод-бандл:
# браузер пользователя пошёл бы на свой localhost, и прод бы лёг.
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
