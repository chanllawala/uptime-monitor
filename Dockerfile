FROM python:3.12-slim

# Unbuffered so container logs stream in real time rather than sitting in a
# buffer, which matters for a long-running worker you watch via `docker logs`.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Dependencies are copied and installed before the source so that editing code
# does not invalidate the (slow) pip layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Run as a non-root user: a container that only makes outbound HTTP requests
# has no reason to hold root inside its namespace.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /srv
USER appuser

EXPOSE 8000

# Overridden by the worker service in docker-compose.
CMD ["uvicorn", "app.web:app", "--host", "0.0.0.0", "--port", "8000"]
