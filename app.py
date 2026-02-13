import asyncio
import os
import threading
import logging
import sys

import mysql.connector
from mysql.connector import pooling, Error
import gradio as gr
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# Configuration de la base de données (lues depuis les variables d'environnement)
DB_HOST = os.environ.get('MYSQL_HOST', 'grenadine.czowocaekxjw.us-east-2.rds.amazonaws.com')
DB_USER = os.environ.get('MYSQL_USER', 'Grenadine')
DB_PASSWORD = os.environ.get('MYSQL_PASSWORD', '5JFz4vQq52')
DB_NAME = os.environ.get('MYSQL_DATABASE', 'u122147766_Grenadine')
DB_PORT = int(os.environ.get('MYSQL_PORT', '3306'))

# URL de connexion Bright Data (à remplacer si elle change)
BRIGHT_DATA_WSS_URL = "wss://brd-customer-hl_e179173a-zone-grenadine:gbwyvr478eg1@brd.superproxy.io:9222"

# --- Variables Globales ---
db_connection_pool = None
seen_message_ids = set()
seen_message_lock = asyncio.Lock()

# --- Fonctions de Base de Données (inchangées mais améliorées) ---

def create_db_pool():
    """Crée le pool de connexions à la base de données."""
    global db_connection_pool
    try:
        db_connection_pool = pooling.MySQLConnectionPool(
            pool_name="db_pool",
            pool_size=5,
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            port=DB_PORT,
            connect_timeout=10
        )
        logging.info("✅ Pool de connexions DB créé avec succès.")
    except Error as e:
        logging.critical(f"❌ Échec de la création du pool de connexions DB: {e}")
        db_connection_pool = None

def get_db_connection():
    """Obtient une connexion depuis le pool."""
    if db_connection_pool is None:
        logging.error("Le pool de connexions n'est pas initialisé.")
        return None
    try:
        return db_connection_pool.get_connection()
    except Error as e:
        logging.error(f"Impossible d'obtenir une connexion DB: {e}")
        return None

# --- NOUVELLE FONCTION DE SCRAPING AVEC PLAYWRIGHT ---

async def fetch_html_with_playwright():
    """
    Se connecte au navigateur distant de Bright Data via Playwright,
    navigue vers tlk.io et retourne le HTML de la page.
    """
    async with async_playwright() as p:
        logging.info("Connexion au navigateur distant de Bright Data...")
        try:
            browser = await p.chromium.connect_over_cdp(BRIGHT_DATA_WSS_URL)
            page = await browser.new_page()
            logging.info(f"Navigation vers https://tlk.io/grenadine..." )
            await page.goto('https://tlk.io/grenadine', timeout=60000 ) # Timeout de 60s

            # Attendre que les messages soient chargés. On cible un sélecteur CSS qui contient les messages.
            await page.wait_for_selector('.message', timeout=30000)
            logging.info("✅ Page et messages chargés.")

            html_content = await page.content()
            await browser.close()
            return html_content
        except Exception as e:
            logging.error(f"❌ Erreur Playwright: {e}")
            if 'browser' in locals() and browser.is_connected():
                await browser.close()
            return None

# --- Fonctions de Traitement et Sauvegarde (adaptées) ---

def parse_and_save_messages(html_content):
    """Parse le HTML, extrait les messages et les sauvegarde en base de données."""
    if not html_content:
        return

    soup = BeautifulSoup(html_content, 'html.parser')
    messages_found = soup.select('.message') # Utilise le sélecteur CSS pour trouver les messages
    logging.info(f"Trouvé {len(messages_found)} éléments de message dans le HTML.")

    conn = get_db_connection()
    if not conn:
        return
    cursor = conn.cursor()

    new_messages_count = 0
    for msg_element in messages_found:
        try:
            # Extrait les données depuis les balises HTML
            message_id = msg_element.get('data-id')
            sender = msg_element.select_one('.user-name').get_text(strip=True)
            content = msg_element.select_one('.body').get_text(strip=True)
            # Le timestamp n'est pas facilement accessible, on utilise l'heure actuelle
            # ou on pourrait essayer de le parser si disponible.
            timestamp = msg_element.select_one('.timestamp a').get_text(strip=True)

            if message_id and message_id not in seen_message_ids:
                # Vérifier si le message existe déjà en DB
                cursor.execute("SELECT id FROM messages WHERE message_id = %s", (message_id,))
                if cursor.fetchone():
                    seen_message_ids.add(message_id) # Marquer comme vu même s'il est déjà en DB
                    continue

                # Insérer le nouveau message
                insert_query = "INSERT INTO messages (message_id, sender, content, timestamp) VALUES (%s, %s, %s, %s)"
                cursor.execute(insert_query, (message_id, sender, content, timestamp))
                seen_message_ids.add(message_id)
                new_messages_count += 1

        except Exception as e:
            # logging.warning(f"Impossible de parser un élément de message: {e}")
            continue

    if new_messages_count > 0:
        conn.commit()
        logging.info(f"✅ Sauvegardé {new_messages_count} nouveaux messages.")

    cursor.close()
    conn.close()


async def scraper_loop():
    """Boucle principale du scraper."""
    logging.info("🚀 Démarrage de la boucle de scraping...")
    while True:
        html = await fetch_html_with_playwright()
        if html:
            parse_and_save_messages(html)
        else:
            logging.warning("Aucun contenu HTML reçu, nouvelle tentative dans 15s.")
        
        await asyncio.sleep(15) # Scrape toutes les 15 secondes pour ne pas abuser

# --- Fonctions pour Gradio (inchangées) ---

def get_message_history():
    conn = get_db_connection()
    if not conn:
        return "<p>Erreur de connexion à la base de données.</p>"
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT sender, content, timestamp FROM messages ORDER BY timestamp DESC LIMIT 100")
        messages = cursor.fetchall()
        
        history_html = ""
        for sender, content, timestamp in reversed(messages):
            history_html += f"<p><strong>{sender}</strong> ({timestamp}): {content}</p>"
        return history_html if history_html else "<p>Aucun message trouvé.</p>"
    except Error as err:
        logging.error(f"Erreur DB dans get_message_history: {err}")
        return "<p>Erreur lors de la récupération de l'historique.</p>"
    finally:
        if conn and conn.is_connected():
            conn.close()

# --- Démarrage de l'application ---

def run_background_scraper():
    """Fonction cible pour le thread qui exécute la boucle asyncio."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(scraper_loop())

# Interface Gradio
with gr.Blocks() as demo:
    gr.Markdown("# Historique des messages tlk.io/grenadine")
    history_display = gr.HTML()
    demo.load(get_message_history, None, history_display)
    timer = gr.Timer(5) # Rafraîchit l'affichage toutes les 5 secondes
    timer.tick(get_message_history, None, history_display)

if __name__ == "__main__":
    # Initialiser le pool de connexions DB
    create_db_pool()

    # Installer les navigateurs pour Playwright (nécessaire dans le Dockerfile)
    # Note: cette commande doit être exécutée dans le shell du Dockerfile, pas ici.
    # os.system("playwright install")

    # Démarrer le scraper dans un thread séparé
    scraper_thread = threading.Thread(target=run_background_scraper, daemon=True)
    scraper_thread.start()
    logging.info("✅ Scraper démarré en arrière-plan.")

    # Lancer Gradio
    demo.launch(server_name="0.0.0.0", server_port=7860)
