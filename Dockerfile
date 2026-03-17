FROM python:3.12-slim
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libgobject-2.0-0 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libcairo2 \
    libharfbuzz0b \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Install Playwright system deps manually (Debian Trixie renames some Ubuntu font packages)
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-unifont \
    fonts-ubuntu \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*
# Now install just the Chromium browser binary (deps already satisfied above)
RUN playwright install chromium
COPY backend/ ./backend/
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8001"]
