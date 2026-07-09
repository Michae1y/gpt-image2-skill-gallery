FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY gallery_control /app/gallery_control
COPY prompts /app/prompts
COPY web /app/web

EXPOSE 8787
CMD ["uvicorn", "gallery_control.app:app", "--host", "0.0.0.0", "--port", "8787", "--proxy-headers"]
