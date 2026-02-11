import asyncio
from playwright.async_api import async_playwright
from datetime import datetime
import mysql.connector
from mysql.connector import errorcode
import os
from huggingface_hub import HfApi
import json
import hashlib
from pathlib import Path
import aiofiles
from collections import deque
import gradio as gr

# --- CONFIGURATION ---
BACKUP_DIR = "backups"
EXTERNAL_LOG_FILE = "messages_realtime.jsonl"

# Configuration MySQL via variables d'environnement
DB_CONFIG = {
    'host': os.environ.get('MYSQL_HOST'),
    'user': os.environ.get('MYSQL_USER'),
    'password': os.environ.get('MYSQL_PWD'),
    'database': os.environ.get('MYSQL_DB'),
    'raise_on_warnings': True
}

# File d'attente pour traitement asynchrone
message_queue = deque()

# Créer le dossier de backup
Path(BACKUP_DIR).mkdir(exist_ok=True)

def get_db_connection():
    """Crée une connexion à la base de données MySQL"""
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except mysql.connector.Error as err:
        print(f"Erreur de connexion MySQL: {err}")
        return None

def init_db():
    """Initialise la base de données MySQL"""
    conn = get_db_connection()
    if not conn:
        return
    try:
        c = conn.cursor()
        c.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['database']}")
        conn.database = DB_CONFIG['database']
        c.execute('''CREATE TABLE IF NOT EXISTS messages
                     (id INT AUTO_INCREMENT PRIMARY KEY, 
                      timestamp DATETIME, 
                      author VARCHAR(255), 
                      content TEXT,
                      hash VARCHAR(32) UNIQUE)''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_hash ON messages(hash)')
        conn.commit()
    except mysql.connector.Error as err:
        print(f"Erreur initialisation DB: {err}")
    finally:
        conn.close()

def message_hash(author: str, content: str) -> str:
    """Génère un hash unique pour déduplication"""
    return hashlib.md5(f"{author}:{content}".encode()).hexdigest()

async def save_message_external(msg_data: dict):
    """Sauvegarde immédiate dans un fichier local JSONL"""
    try:
        async with aiofiles.open(EXTERNAL_LOG_FILE, mode='a', encoding='utf-8') as f:
            await f.write(json.dumps(msg_data, ensure_ascii=False) + '\n')
            await f.flush()
    except Exception as e:
        print(f"Erreur sauvegarde externe: {e}")

async def process_message_queue():
    """Traite la file d'attente des messages en arrière-plan"""
    while True:
        if message_queue:
            msg_data = message_queue.popleft()
            conn = get_db_connection()
            if conn:
                try:
                    c = conn.cursor()
                    msg_hash = message_hash(msg_data['author'], msg_data['content'])
                    
                    c.execute("SELECT id FROM messages WHERE hash=%s", (msg_hash,))
                    if not c.fetchone():
                        # Conversion du timestamp ISO en format MySQL DATETIME
                        dt_obj = datetime.fromisoformat(msg_data['timestamp'].replace('Z', '+00:00'))
                        mysql_ts = dt_obj.strftime('%Y-%m-%d %H:%M:%S')
                        
                        c.execute("INSERT INTO messages (timestamp, author, content, hash) VALUES (%s, %s, %s, %s)",
                                  (mysql_ts, msg_data['author'], msg_data['content'], msg_hash))
                        conn.commit()
                        
                        await save_message_external(msg_data)
                        print(f"✅ ARCHIVÉ: {msg_data['author']}: {msg_data['content'][:50]}")
                except mysql.connector.Error as err:
                    print(f"Erreur traitement message: {err}")
                finally:
                    conn.close()
        await asyncio.sleep(0.1)

def get_history(limit=500):
    """Récupère l'historique des messages"""
    conn = get_db_connection()
    if not conn:
        return "Erreur de connexion à la base de données."
    try:
        c = conn.cursor()
        c.execute("SELECT timestamp, author, content FROM messages ORDER BY id DESC LIMIT %s", (limit,))
        rows = c.fetchall()
        if not rows:
            return "Aucun message dans l'historique."
        return "\n\n".join([f"[{r[0]}] **{r[1]}**: {r[2]}" for r in rows])
    except mysql.connector.Error as err: 
        return f"Erreur lors du chargement de l'historique: {err}"
    finally:
        conn.close()

def export_to_file():
    """Export complet de l'historique"""
    conn = get_db_connection()
    if not conn:
        return None
    try:
        c = conn.cursor()
        c.execute("SELECT timestamp, author, content FROM messages ORDER BY id ASC")
        rows = c.fetchall()
        
        file_path = f"{BACKUP_DIR}/full_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(f"[{r[0]}] {r[1]}: {r[2]}\n")
        return file_path
    except Exception as e:
        print(f"Erreur export: {e}")
        return None
    finally:
        conn.close()

async def monitor():
    """Surveillance ultra-rapide avec MutationObserver"""
    init_db()
    asyncio.create_task(process_message_queue())
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent="Mozilla/5.0")
        page = await context.new_page()
        
        print("🚀 Ouverture de tlk.io/grenadine...")
        await page.goto("https://tlk.io/grenadine", wait_until="networkidle")
        
        await page.evaluate("""
            () => {
                window.newMessages = [];
                const observer = new MutationObserver((mutations) => {
                    mutations.forEach((mutation) => {
                        mutation.addedNodes.forEach((node) => {
                            if (node.nodeName === 'DL' && node.classList.contains('post')) {
                                const author = node.querySelector('dt')?.innerText?.trim() || 'Unknown';
                                const contentNodes = node.querySelectorAll('dd');
                                const content = Array.from(contentNodes).map(dd => dd.innerText.trim()).join(' | ');
                                if (author && content) {
                                    window.newMessages.push({
                                        author: author,
                                        content: content,
                                        timestamp: new Date().toISOString()
                                    });
                                }
                            }
                        });
                    });
                });
                const liveSection = document.querySelector('#live');
                if (liveSection) {
                    observer.observe(liveSection, { childList: true, subtree: true });
                }
            }
        """)
        
        while True:
            try:
                new_messages = await page.evaluate("window.newMessages.splice(0)")
                if new_messages:
                    for msg in new_messages:
                        message_queue.append(msg)
                
                history = get_history()
                yield f"🚀 **Surveillance Active (MySQL Hostinger)**\n\n{history}"
            except Exception as e:
                print(f"Erreur cycle: {e}")
                await asyncio.sleep(5)
            await asyncio.sleep(0.5)

with gr.Blocks(title="Grenadine - MySQL") as demo:
    gr.Markdown("# 🚀 Grenadine - Archivage MySQL")
    with gr.Row():
        with gr.Column(scale=4):
            output = gr.Markdown(value="🔄 Initialisation...")
        with gr.Column(scale=1):
            btn_export = gr.Button("📥 Export .txt")
            file_download = gr.File(label="Download")
            btn_export.click(fn=export_to_file, outputs=file_download)

    demo.load(monitor, outputs=output)

if __name__ == "__main__":
    demo.queue().launch(server_name="0.0.0.0", server_port=7860)
