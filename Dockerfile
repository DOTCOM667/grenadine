FROM python:3.11-slim

# Installer les dépendances système pour Playwright
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxcb1 \
    libxkbcommon0 \
    libx11-6 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Créer un utilisateur non-root
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

# Installer les dépendances Python
COPY --chown=user requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Installer Chromium pour Playwright
RUN playwright install chromium

# Copier le code
COPY --chown=user . .

# Créer le dossier de backups
RUN mkdir -p backups

# Port pour Gradio (App Runner l'utilisera pour le health check)
EXPOSE 7860
ENV GRADIO_SERVER_NAME="0.0.0.0"

CMD ["python3", "app.py"]
