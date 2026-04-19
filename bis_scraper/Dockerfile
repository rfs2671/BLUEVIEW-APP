# Playwright-official Python image: ships Chromium + all OS deps (libnss, etc.)
# preinstalled. If you roll your own base you'll fight chromium deps for hours.
FROM mcr.microsoft.com/playwright/python:v1.43.0-jammy

WORKDIR /app

# Install Python deps first so Docker layer cache survives source edits.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers are already installed in the base image, but `playwright install`
# is a no-op if they're present — safe to run.
RUN python -m playwright install --with-deps chromium

COPY bis_scraper.py .

# No HTTP port — this is a worker process.
ENV PYTHONUNBUFFERED=1

CMD ["python", "-u", "bis_scraper.py"]
