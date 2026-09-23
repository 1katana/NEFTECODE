FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY orchestrator /app/orchestrator
COPY Quality_neftecode /app/Quality_neftecode
COPY neftecode_optimizer /app/neftecode_optimizer
COPY reliability_agent /app/reliability_agent
COPY integration /app/integration
COPY neftecode_processing.py /app/neftecode_processing.py
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# The application resolves configs, scenarios and model bundles relative to the
# source checkout. Editable installs preserve those paths just like the Windows
# setup documented in README.md.
RUN python -m pip install --no-cache-dir \
    -e /app/orchestrator \
    -e /app/Quality_neftecode \
    -e /app/neftecode_optimizer \
    -e /app/reliability_agent \
    -e /app/integration \
    && sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p /app/integration/runtime

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)" || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "neftecode_integration.app:app", "--host", "0.0.0.0", "--port", "8000"]
