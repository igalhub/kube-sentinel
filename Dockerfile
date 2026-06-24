# --- build stage: install dependencies into an isolated venv ---
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /venv && /venv/bin/pip install --no-cache-dir -r requirements.txt

# --- runtime stage ---
FROM python:3.12-slim
COPY --from=builder /venv /venv
WORKDIR /app
COPY exporter/ ./exporter/

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

EXPOSE 8080
ENTRYPOINT ["/venv/bin/python", "-m", "exporter.main"]
