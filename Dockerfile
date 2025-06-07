FROM python:3.11-slim

# Install system dependencies and download tools
RUN apt-get update && \
    apt-get install -y curl pandoc xz-utils && \
    curl -L -o tectonic.tar.gz https://github.com/tectonic-typesetting/tectonic/releases/latest/download/tectonic-x86_64-unknown-linux-musl.tar.gz && \
    mkdir -p /opt/tectonic && \
    tar -xzf tectonic.tar.gz -C /opt/tectonic --strip-components=1 && \
    ln -s /opt/tectonic/tectonic /usr/local/bin/tectonic && \
    rm tectonic.tar.gz

# Set working directory
WORKDIR /app
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port and run app
ENV PORT=10000
CMD ["python", "app.py"]

