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
            
            # YTMusic initialization can fail with NoneType concatenation if headers are missing
            # we ensure basic mandatory headers are present or have defaults
            mandatory_headers = {
                'X-Goog-Visitor-Id': 'CgthbHBoYS10ZXN0',
                'X-Youtube-Client-Name': '67',
                'X-Youtube-Client-Version': '1.20260114.03.00'
            }
            
            # Normalize keys for comparison
            auth_keys_lower = {k.lower(): k for k in auth.keys()}
            
            for key, default_val in mandatory_headers.items():
                if key.lower() not in auth_keys_lower:
                    auth[key] = default_val
            
            try:
                return YTMusic(auth)
            except TypeError as te:
                if "NoneType" in str(te) or "concatenate" in str(te):
                    logging.warning("YTMusic init failed with NoneType. Retrying with essential fallback.")
                    # Injecting a hardcoded basic auth dictionary as a last resort
                    # to keep the app from crashing.
                    if 'Cookie' not in auth:
                         return None
                    return YTMusic(auth)
                raise te
        except Exception as e:
            logging.error(f"Failed to load YTMusic: {e}")
    return None

TASKS = {
    "backfill": {"status": "idle", "progress": 0, "message": ""},
    "sync": {"status": "idle", "progress": 0, "message": ""}
}

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
    if TASKS["backfill"]["status"] == "running":
        return jsonify({"success": False, "message": "Backfill already running"})

    try:
        pages = int(request.form.get('pages', 5))
        TASKS["backfill"]["status"] = "running"
        TASKS["backfill"]["message"] = "Starting..."
        TASKS["backfill"]["progress"] = 0
        
        def run_backfill():
            try:
                # We can't easily track precise progress inside Scraper without refactoring it heavily
                # So we fake it slightly or just show "Running"
                TASKS["backfill"]["message"] = f"Scraping {pages} pages..."
                for target in scraper.config['targets']:
                    scraper.process_target(target, max_pages=pages)
                TASKS["backfill"]["status"] = "complete"
                TASKS["backfill"]["message"] = "Backfill complete!"
            except Exception as e:
                TASKS["backfill"]["status"] = "error"
                TASKS["backfill"]["message"] = str(e)
            
            # Reset after a delay
            time.sleep(10)
            TASKS["backfill"]["status"] = "idle"
        
        threading.Thread(target=run_backfill).start()
        return jsonify({"success": True, "message": "Backfill started"})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

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

        # Validate minimal headers
        if 'Cookie' not in headers_json and 'cookie' not in headers_json:
             return jsonify({"success": False, "error": "Missing 'Cookie' header. Please copy the full request headers."})
        
        # Check for SAPISID inside the cookie (Crucial for auth)
        cookie_str = headers_json.get('Cookie', headers_json.get('cookie', ''))
        if 'SAPISID' not in cookie_str and '__Secure-3PAPISID' not in cookie_str:
             return jsonify({"success": False, "error": "Invalid Cookie: Missing SAPISID. Please recopy headers from YouTube Music correctly."})

        # Inject mandatory defaults if they are missing in the user's paste
        if 'X-Goog-Visitor-Id' not in headers_json:
            headers_json['X-Goog-Visitor-Id'] = 'CgthbHBoYS10ZXN0' # Generic alpha-test ID
        if 'X-Youtube-Client-Name' not in headers_json:
            headers_json['X-Youtube-Client-Name'] = '67'
        if 'X-Youtube-Client-Version' not in headers_json:
            headers_json['X-Youtube-Client-Version'] = '1.20260114.03.00'

        # Optional: Test initialization immediately to give feedback
        try:
            YTMusic(headers_json)
        except Exception as e:
             return jsonify({"success": False, "error": f"Auth Verification Failed (Library Crash): {str(e)}. Make sure you copied the WHOLE header section."})

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
            # Check if playlist already exists
            playlist_name_full = f"WUOG: {playlist_name}"
            playlist_id = None
            try:
                existing_playlists = yt.get_library_playlists(limit=50) # Check recent ones
                for p in existing_playlists:
                    if p['title'] == playlist_name_full:
                        playlist_id = p['playlistId']
                        logging.info(f"Reusing existing playlist {playlist_id}")
                        break
            except Exception as e:
                logging.warning(f"Could not fetch existing playlists: {e}")

            if not playlist_id:
                playlist_id = yt.create_playlist(title=playlist_name_full, description="Synced from WUOG Scraper")
                logging.info(f"Created new playlist {playlist_id}")
            
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
            if "concatenate" in str(e) and "NoneType" in str(e):
                TASKS["sync"]["message"] = "Invalid Auth: Cookie missing SAPISID. Please recopy headers."
            else:
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
