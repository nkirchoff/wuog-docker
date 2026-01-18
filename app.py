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
def run_weekly_sync():
    """Finds the current month's CSV and syncs it."""
    try:
        now = datetime.now()
        # Filename format: Automation_Month_Year.csv
        # We need to construct the current month's expected filename
        current_month_str = now.strftime("%B_%Y") # e.g. January_2026
        filename = f"Automation_{current_month_str}.csv"
        
        filepath = os.path.join("data/automation", filename)
        if os.path.exists(filepath):
            logging.info(f"Weekly Sync: Found {filename}. Starting sync.")
            # We run this in a thread so it doesn't block the scheduler loop, 
            # effectively behaving like the button press.
            threading.Thread(target=perform_sync, args=(filename,)).start()
        else:
            logging.info(f"Weekly Sync: {filename} not found yet. Skipping.")
    except Exception as e:
        logging.error(f"Weekly sync failed to trigger: {e}")

def run_schedule():
    interval = scraper.config.get('polling_interval_minutes', 60)
    schedule.every(interval).minutes.do(scraper.run_cycle)
    
    # Weekly Sync: Sunday at 3 AM
    schedule.every().sunday.at("03:00").do(run_weekly_sync)
    
    logging.info(f"Scheduler started. Polling every {interval} minutes. Weekly sync on Sundays at 03:00.")
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
            
            # Helper: Ensure defaults exist even in saved file
            defaults = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.5",
                "Content-Type": "application/json",
                "X-Goog-AuthUser": "0",
                "X-Goog-Visitor-Id": "CgthbHBoYS10ZXN0",
                "X-Youtube-Client-Name": "67",
                "X-Youtube-Client-Version": "1.20230705.01.00",
            }
            # Case-insensitive update
            lower_keys = {k.lower(): k for k in auth.keys()}
            for k, v in defaults.items():
                if k.lower() not in lower_keys:
                    auth[k] = v

            return YTMusic(auth)
        except Exception as e:
            logging.error(f"Failed to load YTMusic: {e}")
    return None

TASKS = {
    "backfill": {"status": "idle", "progress": 0, "message": ""},
    "sync": {"status": "idle", "progress": 0, "message": ""}
}

def perform_sync(filename):
    """Shared function to run the sync process."""
    if TASKS["sync"]["status"] == "running":
        logging.warning("Sync requested but already running. Skipping.")
        return

    yt = get_yt_client()
    if not yt:
        logging.error("Cannot sync: YouTube not configured.")
        return

    TASKS["sync"]["status"] = "running"
    TASKS["sync"]["progress"] = 0
    TASKS["sync"]["message"] = f"Starting sync for {filename}"
        
    try:
        filepath = os.path.join("data/automation", filename)
        
        # New Naming: WUOG Month Year
        # Filename: Automation_January_2026.csv
        # Remove extension
        clean_name = filename.replace(".csv", "")
        # Remove "Automation_" prefix if present
        if clean_name.startswith("Automation_"):
            clean_name = clean_name.replace("Automation_", "")
        
        # Replace remaining underscores with spaces: "January 2026"
        clean_name = clean_name.replace("_", " ")
        
        playlist_title = f"WUOG {clean_name}"
        
        logging.info(f"Starting YT Sync for {playlist_title}...")
        
        # Check if playlist already exists
        playlist_id = None
        try:
            existing_playlists = yt.get_library_playlists(limit=50) # Check recent ones
            for p in existing_playlists:
                if p['title'] == playlist_title:
                    playlist_id = p['playlistId']
                    logging.info(f"Reusing existing playlist {playlist_id}")
                    break
        except Exception as e:
            logging.warning(f"Could not fetch existing playlists: {e}")

        if not playlist_id:
            playlist_id = yt.create_playlist(title=playlist_title, description="Synced from WUOG Scraper")
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
        
        TASKS["sync"]["message"] = f"Adding {len(songs_to_add)} songs..."
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
        
        # 1. Parse JSON
        try:
            headers_json = json.loads(raw_headers)
        except json.JSONDecodeError:
            # Fallback: Maybe they pasted the raw HTTP header text? 
            # We can try to be smart, but for now just tell them to use JSON.
            return jsonify({"success": False, "error": "Invalid JSON format. Please paste the JSON object extracted from the network tab."})

        # 2. Case-Insensitive Normalization of keys
        # We prefer Title-Case for standard headers, but 'cookie' works too.
        # Let's rebuild a clean dictionary.
        normalized = {}
        for k, v in headers_json.items():
            normalized[k] = v
        
        # Check Cookie specifically (case-insensitive search)
        cookie_val = None
        for k, v in normalized.items():
            if k.lower() == 'cookie':
                cookie_val = v
                break
        
        if not cookie_val:
             return jsonify({"success": False, "error": "Missing 'Cookie' header. Please copy the full request headers."})
        
        if 'SAPISID' not in cookie_val and '__Secure-3PAPISID' not in cookie_val:
             return jsonify({"success": False, "error": "Invalid Cookie: Missing SAPISID. Please recopy headers from a request to music.youtube.com (e.g. 'browse')."})

        # 3. Inject Defaults if missing
        defaults = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.5",
            "Content-Type": "application/json",
            "X-Goog-AuthUser": "0",
            "X-Goog-Visitor-Id": "CgthbHBoYS10ZXN0",
            "X-Youtube-Client-Name": "67",
            "X-Youtube-Client-Version": "1.20230705.01.00",
        }
        
        lower_keys = {k.lower(): k for k in normalized.keys()}
        for k, v in defaults.items():
            if k.lower() not in lower_keys:
                normalized[k] = v

        # 4. Verify Initialization
        try:
            YTMusic(normalized)
        except Exception as e:
             return jsonify({"success": False, "error": f"Auth Verification Failed: {str(e)}. Tip: Try copying headers from the 'browse' or 'landing' request."})

        with open("headers_auth.json", "w") as f:
            json.dump(normalized, f)
            
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

    threading.Thread(target=perform_sync, args=(filename,)).start()
    return jsonify({"success": True, "message": f"Sync started for {filename}"})

if __name__ == '__main__':
    # Ensure data dirs exist
    os.makedirs("data/automation", exist_ok=True)
    app.run(host='0.0.0.0', port=1785)
