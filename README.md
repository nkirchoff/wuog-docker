# WUOG Scraper & Playlist Manager V2

A comprehensive tool that scrapes WUOG playlists from Spinitron and syncs them to YouTube Music. Now featuring a web dashboard for easy management.

## Features

### Core Scraping
*   **Continuous Monitoring**: Runs 24/7 to scrape new plays.
*   **Deduplication**: Smartly tracks Date/Time/Artist/Song to ensure your CSVs don't have duplicate entries for the same play.
*   **Historical Backfill**: Scrape past months of data through the web UI.

### YouTube Music Integration
*   **One-Click Sync**: Push a CSV playlist to YouTube Music instantly.
*   **Sync All**: Sequentially sync all monthly playlists with one button.
*   **Weekly Auto-Sync**: Every **Sunday at 3:00 AM**, the system checks the current month's playlist and syncs new songs automatically.
*   **Safe Re-syncing**: The system checks if songs are already in the playlist before adding them, so you don't get duplicates on YouTube.

### Web Dashboard (Port 1785)
*   Manage API Authentication.
*   View status of background jobs (Sync, Backfill).
*   Download CSV files directly.

## Deployment (Docker)

This project is built automatically to the GitHub Container Registry. You do not need to build it manually.

### docker-compose.yml
Use this configuration on your server (OMV, Portainer, etc):

```yaml
services:
  wuog-scraper:
    image: ghcr.io/nkirchoff/wuog-docker:latest
    container_name: wuog_scraper
    restart: unless-stopped
    ports:
      - "1785:1785"
    volumes:
      - /path/to/data:/app/data
      - /path/to/headers_auth.json:/app/headers_auth.json # Stores YT Cookies
    environment:
      - TZ=America/New_York
```

### Setup Instructions
1.  **Deploy** the stack.
2.  **Open Dashboard**: Go to `http://<server-ip>:1785`.
3.  **Configure YouTube**:
    *   Click **Configure Auth**.
    *   Paste your request JSON (containing `Cookie: ... SAPISID=...`) from `music.youtube.com`.
    *   *Tip: Use Firefox Developer Tools -> Network Tab -> Filter "browse" -> Copy headers.*

## Configuration (config.yaml)
The system uses a default config, but you can override it by mounting `config.yaml`:

```yaml
polling_interval_minutes: 60
targets:
  - name: "Automation"
    url: "https://spinitron.com/WUOG/dj/132321/Automation"
    export_folder: "data/automation"
    consolidation: "monthly"
```

## Security Note for Contributors
*   No API keys are hardcoded.
*   `headers_auth.json` is `.gitignore`d and persisted via volume.
