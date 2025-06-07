FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y curl pandoc xz-utils ca-certificates && \
    apt-get clean

# Download and install Tectonic manually
RUN curl -L -o tectonic.tar.gz https://github.com/tectonic-typesetting/tectonic/releases/latest/download/tectonic-x86_64-unknown-linux-musl.tar.gz && \
    mkdir -p /opt/tectonic && \
    tar -xzf tectonic.tar.gz -C /opt/tectonic && \
    ln -s /opt/tectonic/tectonic /usr/local/bin/tectonic && \
    rm tectonic.tar.gz

# Verify tectonic installed (prints version)
RUN tectonic --version || echo "Tectonic not found"

# Set working directory
WORKDIR /app
COPY . /app

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Expose port and run app
ENV PORT=10000
CMD ["python", "app.py"]
