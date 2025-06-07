# Use lightweight Python base
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y curl pandoc && \
    curl --proto '=https' --tlsv1.2 -sSf https://tectonic.new/install.sh | sh

# Create app directory
WORKDIR /app
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port and run app
ENV PORT=10000
CMD ["python", "app.py"]
