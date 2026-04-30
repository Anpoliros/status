FROM node:22-bookworm-slim AS frontend
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY index.html vite.config.js ./
COPY frontend ./frontend
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    STATUS_DATABASE=/data/status.db \
    STATUS_JSON=/app/dist/status.json
COPY backend ./backend
COPY config.example.json ./config.json
COPY --from=frontend /app/dist ./dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
