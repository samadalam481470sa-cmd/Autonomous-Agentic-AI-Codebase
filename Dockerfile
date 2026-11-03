FROM node:22-alpine AS dashboard
WORKDIR /ui
COPY apps/dashboard/package.json apps/dashboard/package-lock.json ./
RUN npm ci --no-audit --fund=false
COPY apps/dashboard/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY services ./services
COPY apps ./apps
COPY --from=dashboard /ui/dist ./apps/dashboard/dist
COPY packages ./packages
RUN pip install --no-cache-dir .
RUN useradd -m agent && mkdir -p /app/workspaces /app/database && chown -R agent:agent /app
USER agent
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)" || exit 1
CMD ["uvicorn","services.api.main:app","--host","0.0.0.0","--port","8000","--no-server-header"]
