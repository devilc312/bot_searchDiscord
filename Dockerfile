FROM python:3.12-slim
WORKDIR /app
RUN useradd -m bot && mkdir /data && chown bot /data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV DATA_DIR=/data PYTHONUNBUFFERED=1
USER bot
CMD ["python", "-m", "app"]
