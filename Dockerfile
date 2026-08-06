# Python 3.11 slim base per plan.md Technical Context.
FROM python:3.11-slim

# Keep Python from writing .pyc files and buffering stdout/stderr, useful for
# container logs (Constitution V — structured, immediately-visible logs).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Non-root user — no secrets are baked into any layer above; all
# configuration is supplied at runtime via environment variables /
# Secret Manager (Constitution III, IV).
RUN useradd --create-home --shell /usr/sbin/nologin appuser
USER appuser

# Cloud Run supplies PORT; API_PORT/API_HOST default to 8080/0.0.0.0 in
# app/config.py. Bind explicitly here for local `docker run` parity.
ENV API_HOST=0.0.0.0 \
    API_PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host ${API_HOST} --port ${API_PORT}"]
