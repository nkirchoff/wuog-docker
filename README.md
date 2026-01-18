# WUOG Docker Scraper

A Dockerized Python application to scrape WUOG playlists from Spinitron, specifically targeting "Automation" (After Hours) or specific DJs. It consolidates songs into CSV files and runs 24/7.

## Features
- **Continuous Monitoring**: Runs on a schedule (default: every 60 minutes).
- **Automation/After Hours Support**: Automatically scrapes the "Automation" DJ page.
- **Data Consolidation**: Exports songs to CSV files (e.g., `data/automation/Automation_January_2026.csv`).
- **Duplicate Prevention**: Uses a local SQLite database (`data/wuog_data.db`) to track scraped playlists and songs to avoid duplicates.
- **Dockerized**: Easy to deploy and restart.

## Prerequisites
- Docker and Docker Compose

## Quick Start
1. **Configure** (Optional):
   Edit `config.yaml` to change targets or polling interval.
   ```yaml
   polling_interval_minutes: 60
   targets:
     - name: "Automation"
       url: "https://spinitron.com/WUOG/dj/132321/Automation"
       export_folder: "data/automation"
   ```

2. **Run**:
   ```bash
   docker-compose up -d --build
   ```

3. **Check Data**:
   ```

## Deploying to OpenMediaVault (OMV) or Remote Server
Yes, this project is fully portable. Since this setup builds a custom Docker image, you need to copy the **entire project folder** (not just the YAML files) to your server.

1. **Copy Files**: Transfer the whole `Wuog Docker` folder to your server (e.g., using SCP, FTP, or SMB).
   - Essential files: `scraper.py`, `requirements.txt`, `Dockerfile`, `config.yaml`, `docker-compose.yml`.
2. **Run via Terminal (SSH)**:
   Navigate to the folder on your server and run:
   ```bash
   docker-compose up -d --build
   ```
3. **Alternative (Portainer)**:
   If you use Portainer on OMV, you still need the files on the disk to build the image.
   - Using 'Stacks': You can paste the `docker-compose.yml` content into a Stack, **BUT** you must ensure the `build: .` context is correct (pointing to where you uploaded the files). Use the full path in `build` or just run via SSH for simplicity.

## Monitoring a Specific DJ
To monitor a specific DJ, add them to `config.yaml`:
```yaml
  - name: "DJ Name"
    url: "https://spinitron.com/WUOG/dj/12345/DJ-Name"
    export_folder: "data/djs/dj_name"
    consolidation: "none" # or "monthly"
```

## Apple Music Integration
Automating playlist creation requires an active Apple Developer Program membership ($99/year). If you have one, you can extend the `scraper.py` with the necessary API calls using the `developer_token` and `music_user_token`.
For now, the system creates standard CSVs that can be imported into Apple Music using third-party tools (like Soundiiz) or manual matching.

## Development / Manual Run
To run locally without Docker:
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Run once:
   ```bash
   python scraper.py --once
   ```
