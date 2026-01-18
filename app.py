from flask import Flask, render_template, send_from_directory, request, jsonify
import threading
import schedule
import time
import os
import csv
import json
import logging
from ytmusicapi import YTMusic

# Import our existing classes
from scraper import Scraper

app = Flask(__name__)
scraper = Scraper()

# Background Scheduler Thread
def run_schedule():
    interval = scraper.config.get('polling_interval_minutes', 60)
    schedule.every(interval).minutes.do(scraper.run_cycle)
    logging.info(f"Scheduler started. Polling every {interval} minutes.")
    while True:
        schedule.run_pending()
        time.sleep(1)

# Start scheduler on launch
threading.Thread(target=run_schedule, daemon=True).start()

def get_yt_client():
    if os.path.exists("headers_auth.json"):
        try:
            return YTMusic("headers_auth.json")
        except Exception as e:
            logging.error(f"Failed to load YTMusic: {e}")
    return None

@app.route('/')
def index():
    # List CSV files
    data_dir = "data/automation" # TODO: Make dynamic based on targets
    files = []
    if os.path.exists(data_dir):
        for f in os.listdir(data_dir):
            if f.endswith(".csv"):
                size = os.path.getsize(os.path.join(data_dir, f))
                # Convert size to readable format
                readable_size = f"{size / 1024:.1f} KB"
                files.append({"name": f, "size": readable_size})
    
    # Sort by name (descending roughly gives newest months first)
    files.sort(key=lambda x: x['name'], reverse=True)
    return render_template('index.html', files=files)

@app.route('/download/<filename>')
def download_file(filename):
    return send_from_directory('data/automation', filename, as_attachment=True)

@app.route('/backfill', methods=['POST'])
def backfill():
    try:
        pages = int(request.form.get('pages', 5))
        def run_backfill():
            for target in scraper.config['targets']:
                scraper.process_target(target, max_pages=pages)
        
        threading.Thread(target=run_backfill).start()
        return "Backfill started in background. Check logs or refresh page in a few minutes."
    except Exception as e:
        return f"Error: {e}"

@app.route('/api/status')
def status():
    return jsonify({
        "yt_configured": os.path.exists("headers_auth.json")
    })

@app.route('/config/youtube', methods=['POST'])
def config_youtube():
    try:
        data = request.json
        raw_headers = data.get('headers')
        # Try to parse as JSON first
        try:
            headers_json = json.loads(raw_headers)
        except json.JSONDecodeError:
            # Maybe it's raw HTTP headers? simplistic fallback or error
            return jsonify({"success": False, "error": "Invalid JSON format. Please paste the JSON object."})
            
        with open("headers_auth.json", "w") as f:
            json.dump(headers_json, f)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/sync/youtube/<filename>', methods=['POST'])
def sync_youtube(filename):
    yt = get_yt_client()
    if not yt:
        return jsonify({"message": "YouTube Music not configured! Configure it first."}), 400

    def run_sync():
        filepath = os.path.join("data/automation", filename)
        playlist_name = filename.replace(".csv", "").replace("_", " ")
        
        logging.info(f"Starting YT Sync for {playlist_name}...")
        
        # 1. Create or Find Playlist
        # Note: Searching for own playlists via API is tricky, simpler to just create new for now 
        # or list library. Let's create a new one to be safe.
        try:
            playlist_id = yt.create_playlist(title=f"WUOG: {playlist_name}", description="Synced from WUOG Scraper")
            logging.info(f"Created playlist {playlist_id}")
            
            songs_to_add = []
            with open(filepath, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    query = f"{row['Artist']} {row['Song']}"
                    
                    # Search
                    search_results = yt.search(query, filter="songs")
                    if search_results:
                        # Pick first result
                        video_id = search_results[0]['videoId']
                        songs_to_add.append(video_id)
                    else:
                        logging.warning(f"Could not find on YT Music: {query}")
                        
            # Add to playlist (batching?)
            # ytmusicapi handles batching generally well, but let's be safe
            if songs_to_add:
                yt.add_playlist_items(playlist_id, songs_to_add)
                logging.info(f"Added {len(songs_to_add)} songs to playlist.")
        except Exception as e:
            logging.error(f"Sync failed: {e}")

    threading.Thread(target=run_sync).start()
    return jsonify({"message": f"Sync started for {filename}. It may take a while."})

if __name__ == '__main__':
    # Ensure data dirs exist
    os.makedirs("data/automation", exist_ok=True)
    app.run(host='0.0.0.0', port=1785)
