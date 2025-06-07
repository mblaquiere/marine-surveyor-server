FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y curl pandoc xz-utils ca-certificates && \
    apt-get clean

# Install Tectonic v0.13.0 (pinned, stable)
RUN curl -L -o tectonic.tar.gz https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%400.13.0/tectonic-0.13.0-x86_64-unknown-linux-musl.tar.gz && \
    mkdir -p /opt/tectonic && \
    tar -xzf tectonic.tar.gz -C /opt/tectonic && \
    ln -s /opt/tectonic/tectonic /usr/local/bin/tectonic && \
    rm tectonic.tar.gz

# Confirm it installed (optional)
RUN tectonic --version || echo "Tectonic install failed"

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

ENV PORT=10000
CMD ["python", "app.py"]
