# Web image (Option A): builds the SPA, serves it with nginx, and proxies
# API + WebSocket traffic to the `api` service — single origin for the browser.
FROM node:22-slim AS build

WORKDIR /app
COPY chat_frontend/package.json chat_frontend/package-lock.json ./
RUN npm ci
COPY chat_frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html