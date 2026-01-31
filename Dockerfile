FROM python:3.11-slim

# Install FFmpeg and comprehensive font support
RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    fontconfig \
    fonts-dejavu-core \
    fonts-liberation \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the actual app file
COPY app-3.py app.py

# Set UTF-8 locale
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
