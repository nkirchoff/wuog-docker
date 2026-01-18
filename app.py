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
            with open("headers_auth.json") as f:
                auth = json.load(f)
            
            # Helper: Try to init
            try:
                return YTMusic(auth)
            except TypeError as te:
                if "NoneType" in str(te) or "concatenate" in str(te):
                    logging.warning("YTMusic init failed (NoneType). Attempting force-fix with generic Visitor ID.")
                    # The library might be failing to parse the cookie.
                    # We ensure X-Goog-Visitor-Id is present.
                    if 'X-Goog-Visitor-Id' not in auth:
                        auth['X-Goog-Visitor-Id'] = 'CgthbHBoYS10ZXN0' # Generic valid-looking ID
                    
                    return YTMusic(auth)
                raise te
        except Exception as e:
            logging.error(f"Failed to load YTMusic: {e}")
    return None

@app.route('/api/status')
def status():
    return jsonify({
        "yt_configured": os.path.exists("headers_auth.json"),
        "tasks": TASKS
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
            return jsonify({"success": False, "error": "Invalid JSON format. Please paste the JSON object."})
            
        # Optional: Test initialization immediately to give feedback
        try:
            # We do a trial init to see if it crashes
            try:
                YTMusic(headers_json)
            except TypeError as te:
                 # Apply the same fix strategy as get_yt_client to save a "fixed" version
                 if "NoneType" in str(te) or "concatenate" in str(te):
                     if 'X-Goog-Visitor-Id' not in headers_json:
                         headers_json['X-Goog-Visitor-Id'] = 'CgthbHBoYS10ZXN0'
                     YTMusic(headers_json) # Retry
                 else:
                     raise te
        except Exception as e:
             return jsonify({"success": False, "error": f"Auth Verification Failed: {str(e)}"})

        with open("headers_auth.json", "w") as f:
            json.dump(headers_json, f)
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route('/sync/youtube/<filename>', methods=['POST'])
def sync_youtube(filename):
    if TASKS["sync"]["status"] == "running":
        return jsonify({"message": "A sync job is already running."}), 400

    yt = get_yt_client()
    if not yt:
        return jsonify({"message": "YouTube Music not configured! Configure it first."}), 400

    def run_sync():
        TASKS["sync"]["status"] = "running"
        TASKS["sync"]["progress"] = 0
        TASKS["sync"]["message"] = f"Starting sync for {filename}"
        
        filepath = os.path.join("data/automation", filename)
        playlist_name = filename.replace(".csv", "").replace("_", " ")
        
        logging.info(f"Starting YT Sync for {playlist_name}...")
        
        try:
            playlist_id = yt.create_playlist(title=f"WUOG: {playlist_name}", description="Synced from WUOG Scraper")
            logging.info(f"Created playlist {playlist_id}")
            TASKS["sync"]["message"] = "Reading songs..."
            
            songs_to_add = []
            with open(filepath, 'r') as f:
                rows = list(csv.DictReader(f))
                total_songs = len(rows)
                
                for i, row in enumerate(rows):
                    TASKS["sync"]["progress"] = int((i / total_songs) * 100)
                    TASKS["sync"]["message"] = f"Searching: {row['Song']}"
                    
                    query = f"{row['Artist']} {row['Song']}"
                    # Search
                    try:
                        search_results = yt.search(query, filter="songs")
                        if search_results:
                            video_id = search_results[0]['videoId']
                            songs_to_add.append(video_id)
                    except Exception as e:
                        logging.warning(f"Search failed for {query}: {e}")
            
            TASKS["sync"]["message"] = f"Adding {len(songs_to_add)} songs to playlist..."
            if songs_to_add:
                yt.add_playlist_items(playlist_id, songs_to_add)
            
            TASKS["sync"]["status"] = "complete"
            TASKS["sync"]["message"] = "Sync Complete!"
        except Exception as e:
            TASKS["sync"]["status"] = "error"
            TASKS["sync"]["message"] = f"Failed: {str(e)}"
            logging.error(f"Sync failed: {e}")
        
        time.sleep(10)
        TASKS["sync"]["status"] = "idle"

    threading.Thread(target=run_sync).start()
    return jsonify({"success": True, "message": f"Sync started for {filename}"})

if __name__ == '__main__':
    # Ensure data dirs exist
    os.makedirs("data/automation", exist_ok=True)
    app.run(host='0.0.0.0', port=1785)
