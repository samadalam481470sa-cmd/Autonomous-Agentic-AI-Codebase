FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY services ./services
COPY apps ./apps
RUN pip install --no-cache-dir .
RUN useradd -m agent && mkdir -p /app/workspaces /app/database && chown -R agent:agent /app
USER agent
EXPOSE 8000
CMD ["uvicorn","services.api.main:app","--host","0.0.0.0","--port","8000"]
