FROM python:3.11-slim

# Install OpenCV dependencies (includes libGL)
RUN apt-get update && apt-get install -y \
    libzbar0 \
    libgl1 \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
