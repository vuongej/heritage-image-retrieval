# syntax=docker/dockerfile:1.7
# Web demo: build SPA (web/spa, Vite + React) rồi phục vụ bằng Caddy (~50 MB), kèm proxy /api.

FROM node:22-alpine AS build
WORKDIR /app
COPY web/spa/package.json web/spa/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/spa/ ./
RUN npm run build

FROM caddy:2-alpine
COPY deploy/web.Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s --retries=5 CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
