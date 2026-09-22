FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY orchestrator /app/orchestrator
COPY Quality_neftecode /app/Quality_neftecode
COPY neftecode_optimizer /app/neftecode_optimizer
COPY reliability_agent /app/reliability_agent
COPY integration /app/integration
COPY neftecode_processing.py /app/neftecode_processing.py

RUN python -m pip install --no-cache-dir \
    /app/orchestrator \
    /app/Quality_neftecode \
    /app/neftecode_optimizer \
    /app/reliability_agent \
    /app/integration

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "neftecode_integration.app:app", "--host", "0.0.0.0", "--port", "8000"]
