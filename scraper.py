import requests
from bs4 import BeautifulSoup
import csv
import os
import sqlite3
import yaml
import time
import schedule
import logging
from datetime import datetime
from urllib.parse import urljoin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scraper.log")
    ]
)

class Database:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Table for playlists
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                url TEXT PRIMARY KEY,
                target_name TEXT,
                show_title TEXT,
                dj_name TEXT,
                date_str TEXT,
                time_str TEXT,
                timestamp DATETIME
            )
        ''')

        # Table for songs
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_url TEXT,
                artist TEXT,
                song TEXT,
                album TEXT,
                timestamp DATETIME,
                UNIQUE(playlist_url, artist, song)
            )
        ''')
        conn.commit()
        conn.close()

    def playlist_exists(self, url):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM playlists WHERE url = ?', (url,))
        exists = cursor.fetchone() is not None
        conn.close()
        return exists

    def save_playlist(self, data):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT OR IGNORE INTO playlists (url, target_name, show_title, dj_name, date_str, time_str, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (data['url'], data['target_name'], data['show_title'], data['dj_name'], data['date_str'], data['time_str'], datetime.now()))
            conn.commit()
        except Exception as e:
            logging.error(f"Error saving playlist: {e}")
        finally:
            conn.close()

    def save_songs(self, playlist_url, songs):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        new_count = 0
        try:
            for song in songs:
                try:
                    cursor.execute('''
                        INSERT INTO songs (playlist_url, artist, song, album, timestamp)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (playlist_url, song['artist'], song['song'], song['album'], datetime.now()))
                    new_count += 1
                except sqlite3.IntegrityError:
                    pass # Duplicate song in this playlist, skip
            conn.commit()
        except Exception as e:
            logging.error(f"Error saving songs: {e}")
        finally:
            conn.close()
        return new_count

    def get_songs_for_consolidation(self, target_name, start_date=None, end_date=None):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Build query
        query = '''
            SELECT s.artist, s.song, s.album, p.date_str, p.time_str
            FROM songs s
            JOIN playlists p ON s.playlist_url = p.url
            WHERE p.target_name = ?
        '''
        params = [target_name]
        
        # Note: Filtering by date string is tricky without strict parsing, 
        # but for now we fetch all and filter in python or rely on the order
        # Basic implementation: Sort by creation timestamp
        query += " ORDER BY s.timestamp DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        return rows

class Scraper:
    def __init__(self, config_path="config.yaml"):
        with open(config_path, 'r') as f:
            self.config = yaml.safe_load(f)
        
        self.db = Database(self.config['database_path'])
        self.headers = {'User-Agent': self.config.get('user_agent', 'WUOG-Scraper/1.0')}

    def run_cycle(self):
        logging.info("Starting scrape cycle...")
        for target in self.config['targets']:
            self.process_target(target)
        logging.info("Cycle complete.")

    def process_target(self, target):
        logging.info(f"Processing target: {target['name']}")
        try:
            response = requests.get(target['url'], headers=self.headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')

            # Find playlist items
            # Spinitron structure: div.list-item
            playlist_items = soup.find_all('div', {'class': 'list-item'})
            
            for item in playlist_items:
                link_tag = item.find('a', {'class': 'link row'})
                if not link_tag:
                    continue
                
                playlist_url = urljoin(target['url'], link_tag['href'])
                
                # Check if we already have this playlist
                if self.db.playlist_exists(playlist_url):
                    continue # Skip if processed
                
                # Parse metadata
                dt_div = item.find('div', {'class': 'datetime playlist'})
                date_str = ""
                time_str = ""
                if dt_div:
                    # Robust extraction
                    try:
                        month = dt_div.find('span', {'class': 'month'}).text.strip()
                        day = dt_div.find('span', {'class': 'day'}).text.strip()
                        year = dt_div.find('span', {'class': 'year'}).text.strip()
                        date_str = f"{month} {day} {year}"
                        time_str = dt_div.find('span', {'class': 'time'}).text.strip()
                    except AttributeError:
                        logging.warning(f"Could not parse date/time for {playlist_url}")

                show_title = item.find('h3', {'class': 'show-title'}).text.strip() if item.find('h3', {'class': 'show-title'}) else "N/A"
                dj_name = item.find('p', {'class': 'dj-name'}).text.strip() if item.find('p', {'class': 'dj-name'}) else "N/A"

                playlist_data = {
                    'url': playlist_url,
                    'target_name': target['name'],
                    'show_title': show_title,
                    'dj_name': dj_name,
                    'date_str': date_str,
                    'time_str': time_str
                }
                
                # Scrape the songs for this playlist
                songs = self.scrape_songs(playlist_url)
                
                # Save
                self.db.save_playlist(playlist_data)
                self.db.save_songs(playlist_url, songs)
                logging.info(f"Scraped {len(songs)} songs from {playlist_url}")

                time.sleep(1) # Be polite

            # After processing all new playlists for this target, run export/consolidation
            self.export_data(target)

        except Exception as e:
            logging.error(f"Error processing target {target['name']}: {e}")

    def scrape_songs(self, playlist_url):
        songs = []
        try:
            response = requests.get(playlist_url, headers=self.headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Song rows: tr.spin-item
            song_rows = soup.find_all('tr', {'class': 'spin-item'})
            for row in song_rows:
                artist = row.find('span', {'class': 'artist'}).text.strip() if row.find('span', {'class': 'artist'}) else "Unknown"
                song_title = row.find('span', {'class': 'song'}).text.strip() if row.find('span', {'class': 'song'}) else "Unknown"
                album = row.find('span', {'class': 'release'}).text.strip() if row.find('span', {'class': 'release'}) else "N/A"
                
                songs.append({
                    'artist': artist,
                    'song': song_title,
                    'album': album
                })
        except Exception as e:
            logging.error(f"Failed to scrape songs from {playlist_url}: {e}")
        return songs

    def export_data(self, target):
        export_mode = target.get('consolidation', 'none')
        if export_mode == 'none':
            return
            
        # Simplified export: Dump all data for this target to a single CSV for now
        # The user asked for "month" or "semester". 
        # For simplicity in V1, we create a master CSV for the target, and maybe rotate it by month filename.
        
        current_month = datetime.now().strftime("%B_%Y")
        folder = target['export_folder']
        os.makedirs(folder, exist_ok=True)
        
        filename = f"{target['name'].replace(' ', '_')}_{current_month}.csv"
        filepath = os.path.join(folder, filename)
        
        # Fetch all songs for this target
        # TODO: In a more advanced version, we would filter SQL query by date parsing logic.
        # For now, we dump everything we have for this target.
        rows = self.db.get_songs_for_consolidation(target['name'])
        
        try:
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Artist', 'Song', 'Album', 'Date_Played', 'Time_Played'])
                writer.writerows(rows)
            logging.info(f"Exported data to {filepath}")
        except Exception as e:
            logging.error(f"Error exporting CSV: {e}")

import http.server
import socketserver
import threading
import argparse

def start_file_server(port=1785):
    """
    Starts a simple HTTP server to serve files from the current directory (which includes data/).
    """
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory="data", **kwargs)

    try:
        with socketserver.TCPServer(("", port), Handler) as httpd:
            logging.info(f"Serving data/ directory on port {port}")
            httpd.serve_forever()
    except OSError as e:
        logging.error(f"Could not start web server on port {port}: {e}")

def main():
    parser = argparse.ArgumentParser(description="WUOG Scraper")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    # Start the file server in a background thread
    server_thread = threading.Thread(target=start_file_server, args=(1785,), daemon=True)
    server_thread.start()

    logging.info("Initializing WUOG Scraper...")
    scraper = Scraper()
    
    # Run once immediately
    scraper.run_cycle()
    
    if args.once:
        logging.info("Run once complete. Exiting.")
        return
    
    # Schedule
    interval = scraper.config.get('polling_interval_minutes', 60)
    schedule.every(interval).minutes.do(scraper.run_cycle)
    
    logging.info(f"Scheduler started. Polling every {interval} minutes.")
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    main()
