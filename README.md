# WUOG Semester Playlists (v3)

Collects everything WUOG 90.5FM logs to Spinitron and keeps one set of Apple Music
playlists per UGA semester. The playlists grow every day while the semester runs,
then freeze for good a few days after finals.

## What changed from v2

| v2 | v3 |
| --- | --- |
| Watched only the `Automation` DJ page. WUOG stopped logging automation there on Aug 18, 2026, so v2 has collected nothing since. | Reads Spinitron's calendar feed: every show, DJ, and **show category** (Rotation, Specialty Show, Talk, Sport, News, Live Music). |
| Light Side / Dark Side split by hour. Day and night automation drew from the same pool (95–100% overlap), so the two playlists were near-duplicates. | Playlists are cut by **programming type** (configurable "views"), which is where the actual differences are. |
| Spring = Jan–Jul, Fall = Aug–Dec | Real UGA registrar dates (classes begin → finals end), plus a freeze date |
| YouTube Music, re-searching every song every week | Apple Music, matching by **ISRC** first (Spinitron logs them for most DJ spins), then a scored search. Matches are cached. |
| 1 s between requests | 10 s, per Spinitron's robots.txt `Crawl-delay` |

## Semester lifecycle

1. **Open** (classes begin → finals end + `freeze_grace_days`): the collector runs hourly
   and the Apple Music sync runs daily at `sync_at`. New tracks are appended in the order they first aired.
2. **Frozen**: one last sync after the grace period, then the semester's playlists are marked
   frozen and never touched again. The next semester starts new playlists on its first day.

The Apple Music API can create playlists and add to them, but it can't rename them, reorder them,
or remove tracks. So the sync is append-only, and names and descriptions are fixed at creation.
Edit `views` in `config.yaml` *before* a semester's first sync.

## Apple Music auth

Two tokens are needed, both entered on the dashboard (stored in `data/applemusic.json`, mode 600):

* **Developer token.** Either paste a JWT, or upload a MusicKit key (`.p8`, plus Team ID and Key ID)
  and the app mints its own. MusicKit keys require a paid Apple Developer Program membership.
* **Music User Token.** Use *Sign in with Apple Music* on the dashboard. MusicKit JS needs a secure
  context, so open the dashboard at `http://localhost:1785` (e.g. `ssh -L 1785:localhost:1785 omv`).
  These tokens last about 6 months; the dashboard shows when the current one was saved.

## Deploy

```yaml
services:
  wuog-scraper:
    image: ghcr.io/nkirchoff/wuog-docker:latest
    container_name: wuog_scraper
    restart: unless-stopped
    ports: ["1785:1785"]
    volumes:
      - /path/to/data:/app/data
      # - /path/to/config.yaml:/app/config.yaml   # to customize semesters/views
    environment:
      - TZ=America/New_York
```

On first start the collector backfills the current semester (≈ 1 playlist page per 10 s,
so a full semester takes a few hours). The v2 database (`wuog_data.db`) is left untouched.

## Analysis

`analysis/` holds the scripts behind the programming-by-hour report (they run against `data/wuog.db`).
