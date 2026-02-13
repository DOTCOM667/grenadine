# Utiliser une image Python officielle avec support Playwright
# Cette image contient déjà les navigateurs (Chrome, Firefox, etc.) et toutes les dépendances système.
FROM mcr.microsoft.com/playwright/python:v1.41.2-jammy

# Définir le répertoire de travail à l'intérieur du conteneur
WORKDIR /app

# Copier le fichier des dépendances Python
COPY requirements.txt .

# Installer les dépendances listées dans requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copier tout le reste de votre code (app.py, etc.) dans le conteneur
COPY . .

# Exposer le port que votre application Gradio utilise pour être accessible
EXPOSE 7860

# La commande qui sera exécutée au démarrage du conteneur pour lancer votre application
CMD ["python", "app.py"]
