FROM python:3.12-slim

LABEL org.opencontainers.image.source=https://github.com/Elena-sky/event-platform-retry-orchestrator-service

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["sh", "-c", "exec python -m app.main"]
