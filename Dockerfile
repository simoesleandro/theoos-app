FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    THEOOS_SERVICE=1

WORKDIR /app

# Dependências de sistema (Pillow + HEIC + build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libjpeg-dev \
        zlib1g-dev \
        libheif-dev \
    && rm -rf /var/lib/apt/lists/*

# Dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Código
COPY . .

# Cria diretórios para dados persistentes
RUN mkdir -p /app/instance /app/static/uploads/boletos /app/logs

# Volume para dados persistentes (DB + uploads + logs)
VOLUME ["/app/instance", "/app/static/uploads/boletos", "/app/logs"]

# Usuário não-root para segurança
RUN useradd -m -u 1000 theoos && chown -R theoos:theoos /app
USER theoos

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health').read()" \
    || exit 1

CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--threads=4", "wsgi:application"]
