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
# Install Playwright Chromium + all system deps it needs
RUN playwright install --with-deps chromium
COPY backend/ ./backend/
CMD ["uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8001"]
```

Then add `playwright` to your `requirements.txt` if it's not already there:
```
playwright==1.49.0
