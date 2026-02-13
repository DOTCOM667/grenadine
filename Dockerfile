# Utiliser une image Python officielle avec support Playwright
FROM mcr.microsoft.com/playwright/python:v1.41.2-jammy

# Définir le répertoire de travail
WORKDIR /app

# 1. Copier et installer les dépendances D'ABORD
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Copier le reste du code ENSUITE
COPY . .

# Exposer le port
EXPOSE 7860

# Lancer l'application
CMD ["python", "app.py"]
