# 🎵 Spotify to YouTube Music Playlist Sync Bot

A lightweight, standalone Python utility that scrapes **Spotify Weekly Charts** directly from Kworb, resolves the track IDs to YouTube Music video IDs (with local metadata caching), and automatically synchronizes them into public YouTube Music playlists.

---

## 📋 Playlists Created on YouTube Music

The bot will search for or create the following playlists in your YouTube Music library:

| Chart | YouTube Music Playlist Name | Description |
| :--- | :--- | :--- |
| **Global** | `Spotify Weekly Global Top 200` | Synced from Spotify Weekly Global Chart. |
| **India** | `Spotify Weekly India Top 200` | Synced from Spotify Weekly India Chart. |

> [!NOTE]
> If a playlist with the exact target title already exists in your library, the bot will reuse it. Otherwise, it will create a new public playlist.
>
> During sync, the bot uses an **add-then-remove** flow to update the playlist to match the latest chart sequence, avoiding empty-playlist states while ensuring correct ordering.

---

## 🛠️ Setup & Installation

This directory is managed using `uv` (a fast Python package installer and resolver).

### 1. Initialize Virtual Environment & Install Dependencies
From the root of this directory (`ytmusic-sync`), run:
```bash
# Verify venv is created and packages are installed
uv pip install -r requirements.txt --python .venv
```

### 2. Configure Authentication
To write and update playlists in your YouTube Music library, you must authenticate. Run the setup script:
```bash
.venv/bin/python auth.py
```

* **Option 1: Browser Cookie Headers (Highly Recommended)**
  Follow the on-screen instructions to copy your request headers from `music.youtube.com` via Developer Tools and paste them. This generates `browser.json`.
  
* **Option 2: OAuth 2.0 (Unstable/Broken)**
  *Please note:* Due to Google API changes, using OAuth is currently prone to `400 Bad Request` ("invalid argument") errors on authenticated endpoints (such as playlist management). Use Option 1 instead.

---

## 🚀 Running the Sync

Once authentication is configured (having `browser.json` in this directory), run the sync script:

### Sync Spotify Global Chart
```bash
.venv/bin/python sync.py --country global
```

### Sync Spotify India Chart
```bash
.venv/bin/python sync.py --country in
```

### Dry Run (Test without mutating playlists)
```bash
.venv/bin/python sync.py --country global --dry-run
```

### ⚡ One-Click Local Sync (Linux)
You can synchronize both Global and India charts sequentially in a single step using the provided helper shell script:
```bash
./sync.sh
```
Alternatively, double-click `sync.sh` in your graphical file manager and select **"Run in Terminal"**.

---

## ⚙️ Command-Line Options

| Argument | Description | Default |
| :--- | :--- | :--- |
| `--country` | Country code of the chart to sync (`global` or `in`). | `global` |
| `--data-dir` | Path to save/load scraped JSON cache metadata. | `data` |
| `--auth` | Specific path to the auth file. | *Auto-detects `browser.json`* |
| `--dry-run` | Run the sync logic and output actions without writing to YouTube Music. | *Disabled* |
| `--force` | Force sync even if the weekDate has not changed. | *Disabled* |

---

## 🤖 GitHub Actions Automation

The repository includes a GitHub Actions workflow `.github/workflows/sync.yml` to automatically run the sync daily at **`03:50 UTC`**.

### Configuration Steps:
1. Copy the contents of your locally generated `browser.json`.
2. Go to your GitHub repository -> **Settings** -> **Secrets and variables** -> **Actions** -> **New repository secret**.
3. Create a secret named **`YT_MUSIC_BROWSER_JSON`** and paste the JSON contents.
4. Push the code to your GitHub repository:
   ```bash
   git init
   git add .
   git commit -m "feat: initial commit standalone scraper and sync bot"
   git branch -M main
   git remote add origin https://github.com/quantavil/ytmusic-sync.git
   git push -u origin main
   ```
