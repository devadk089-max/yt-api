FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8000
ENV COOKIES_FILE=/app/cookies.txt
ENV ACCOUNTS_FILE=/app/accounts.json
ENV CACHE_TTL=300
ENV MAX_DURATION=7200
ENV COOKIE_CHECK_INTERVAL=1800
ENV COOKIE_REFRESH_BEFORE=3600
ENV DAILY_REPORT_HOUR=9

EXPOSE 8000

CMD ["python", "main.py"]
