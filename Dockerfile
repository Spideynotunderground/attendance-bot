FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Tashkent \
    DATA_DIR=/data

# fonts-dejavu-core: Cyrillic-capable font for the report image.
# tzdata: so ZoneInfo("Asia/Tashkent") resolves inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py report.py storage.py config.json ./
COPY fonts/ ./fonts/

# Mount a persistent volume here, or verified users and attendance history
# are lost on every restart.
RUN mkdir -p /data
VOLUME ["/data"]

CMD ["python", "bot.py"]
