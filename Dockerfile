# Bookworm (Debian 12) is a platform Playwright installs Chromium's system libraries on.
FROM python:3.11-slim-bookworm

WORKDIR /app

COPY pyproject.toml ./
COPY pokegrab ./pokegrab
RUN pip install --no-cache-dir ".[playwright]" \
 && python -m playwright install --with-deps chromium

COPY config.example.yaml config.yaml* ./

CMD ["python", "-m", "pokegrab"]
