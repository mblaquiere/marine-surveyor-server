FROM python:3.11-slim

# Install system dependencies, including LibreOffice
RUN apt-get update && \
    apt-get install -y libreoffice curl xz-utils ca-certificates && \
    apt-get clean

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=10000
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:10000", "--workers", "1", "--threads", "4", "--timeout", "180"]

