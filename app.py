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
    if os.path.exists("data/auth.json"):
        try:
            with open("data/auth.json") as f:
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
# ... (rest of file)

@app.route('/api/status')
def status():
    return jsonify({
        "yt_configured": os.path.exists("data/auth.json"),
        "tasks": TASKS
    })

# ...

        # 4. Verify Initialization
        try:
            YTMusic(normalized)
        except Exception as e:
             return jsonify({"success": False, "error": f"Auth Verification Failed: {str(e)}. Tip: Try copying headers from the 'browse' or 'landing' request."})

        # Ensure directory exists
        os.makedirs("data", exist_ok=True)
        with open("data/auth.json", "w") as f:
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

@app.route('/sync/all', methods=['POST'])
def sync_all():
    if TASKS["sync"]["status"] == "running":
        return jsonify({"message": "A sync job is already running."}), 400
        
    yt = get_yt_client()
    if not yt:
        return jsonify({"message": "YouTube Music not configured!"}), 400
        
    threading.Thread(target=perform_sync_all).start()
    return jsonify({"success": True, "message": "Batch Sync Started"})

if __name__ == '__main__':
    # Ensure data dirs exist
    os.makedirs("data/automation", exist_ok=True)
    app.run(host='0.0.0.0', port=1785)
