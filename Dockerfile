# Imagem da API CostPilot. Verificada com docker compose em 2026-11-27.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
COPY backend ./backend
COPY config ./config

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 costpilot \
    && mkdir -p /app/data && chown costpilot /app/data

USER costpilot
EXPOSE 8000

# Os segredos (COSTPILOT_ADMIN_TOKEN, chaves de providers) vêm do ambiente, nunca da imagem.
CMD ["uvicorn", "app.main:create_app", "--factory", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
