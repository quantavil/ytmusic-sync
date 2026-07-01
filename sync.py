#!/usr/bin/env python3
import os
import json
import argparse
import sys
import re
import time
import random
from pathlib import Path
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup
from ytmusicapi import YTMusic

# Supported countries (Global and India only)
COUNTRIES = {
    "global": {"name": "Global", "slug": "global_weekly"},
    "in": {"name": "India", "slug": "in_weekly"}
}

BASE_URL = "https://kworb.net/spotify/country"

def parse_args():
    parser = argparse.ArgumentParser(description="Sync Spotify charts to YouTube Music playlists.")
    parser.add_argument(
        "--country",
        type=str,
        default="global",
        choices=list(COUNTRIES.keys()),
        help="Country chart to sync ('global' or 'in')."
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="data",
        help="Path to save/load scraped JSON data."
    )
    parser.add_argument(
        "--auth",
        type=str,
        default=None,
        help="Path to auth file (oauth.json or browser.json). Auto-detects if omitted."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without modifying YouTube Music playlists."
    )
    return parser.parse_args()

def extract_week_date(soup):
    sources = []
    pagetitle_span = soup.find("span", class_="pagetitle")
    if pagetitle_span:
        sources.append(pagetitle_span.get_text())
    if soup.title:
        sources.append(soup.title.get_text())
    for tag in ["h1", "h2", "h3"]:
        for el in soup.find_all(tag):
            sources.append(el.get_text())
            
    for s in sources:
        # Check for YYYY-MM-DD or YYYY/MM/DD
        m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        # Check for Month DD, YYYY
        m2 = re.search(r"(\w{3,9})\s+(\d{1,2}),?\s+(\d{4})", s)
        if m2:
            try:
                date_str = f"{m2.group(1)} {m2.group(2)} {m2.group(3)}".replace(",", "")
                for fmt in ("%B %d %Y", "%b %d %Y"):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        return dt.strftime("%Y-%m-%d")
                    except ValueError:
                        continue
            except Exception:
                pass
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def scrape_kworb(country_code):
    country_config = COUNTRIES[country_code]
    url = f"{BASE_URL}/{country_config['slug']}.html"
    print(f"⏳ Scraping Kworb Weekly Chart: {url} ...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MusicChartsDash/1.0)"}
    
    # Fetch HTML with simple retry mechanism
    for attempt in range(3):
        try:
            res = requests.get(url, headers=headers, timeout=15)
            res.raise_for_status()
            break
        except Exception as e:
            if attempt == 2:
                print(f"Error: Failed to fetch {url} after 3 attempts: {e}")
                sys.exit(1)
            time.sleep(2 * (attempt + 1))
            
    soup = BeautifulSoup(res.text, "html.parser")
    table = soup.find("table")
    if not table:
        print(f"Error: No table found in HTML from {url}")
        sys.exit(1)
        
    rows = table.find_all("tr")
    if not rows:
        print("Error: Table has no rows")
        sys.exit(1)
        
    header_row = rows[0]
    headers_list = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
    
    col_pos = -1
    col_change = -1
    col_track = -1
    col_days = -1
    col_peak = -1
    col_streams = -1
    
    for idx, h in enumerate(headers_list):
        h_lower = h.lower()
        if "pos" in h_lower or h_lower == "#":
            col_pos = idx
        elif "p+" in h_lower or "+/-" in h_lower or "change" in h_lower:
            col_change = idx
        elif "artist" in h_lower or "title" in h_lower or "track" in h_lower:
            col_track = idx
        elif "days" in h_lower or "wks" in h_lower or "weeks" in h_lower:
            col_days = idx
        elif "pk" in h_lower or "peak" in h_lower:
            col_peak = idx
        elif h_lower == "streams":
            col_streams = idx
            
    # Fallback to defaults if headers match fails
    if col_pos == -1: col_pos = 0
    if col_change == -1: col_change = 1
    if col_track == -1: col_track = 2
    if col_days == -1: col_days = 3
    if col_peak == -1: col_peak = 4
    if col_streams == -1: col_streams = 6
    
    week_date = extract_week_date(soup)
    tracks = []
    
    for r_idx in range(1, len(rows)):
        if len(tracks) >= 200:
            break
            
        cells = rows[r_idx].find_all("td")
        if len(cells) < 5:
            continue
            
        try:
            rank = int(cells[col_pos].get_text(strip=True))
        except ValueError:
            continue
            
        change = cells[col_change].get_text(strip=True)
        if not change or change in ("0", "--", "—"):
            change = "0"
            
        track_cell = cells[col_track]
        a_tags = track_cell.find_all("a")
        artist = ""
        title = ""
        spotify_id = ""
        
        if len(a_tags) >= 2:
            artist = a_tags[0].get_text(strip=True)
            title = a_tags[1].get_text(strip=True)
            href = a_tags[1].get("href", "")
            match = re.search(r"track/([a-zA-Z0-9]+)\.html", href)
            if match:
                spotify_id = match.group(1)
        elif len(a_tags) == 1:
            title = a_tags[0].get_text(strip=True)
            href = a_tags[0].get("href", "")
            match = re.search(r"track/([a-zA-Z0-9]+)\.html", href)
            if match:
                spotify_id = match.group(1)
        else:
            track_text = track_cell.get_text(strip=True)
            if " - " in track_text:
                artist, title = track_text.split(" - ", 1)
            else:
                title = track_text
                
        def parse_num(raw):
            raw_clean = re.sub(r"[^\d]", "", raw)
            return int(raw_clean) if raw_clean else 0
            
        streams = parse_num(cells[col_streams].get_text(strip=True))
        peak = parse_num(cells[col_peak].get_text(strip=True))
        weeks = parse_num(cells[col_days].get_text(strip=True))
        
        tracks.append({
            "rank": rank,
            "change": change,
            "title": title,
            "artist": artist,
            "spotifyId": spotify_id,
            "ytMusicId": "",
            "streams": streams,
            "peak": peak,
            "weeks": weeks
        })
        
    return {
        "country": country_code,
        "countryName": country_config["name"],
        "weekDate": week_date,
        "lastUpdated": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        "tracks": tracks
    }

def load_ytmusic_cache(data_dir):
    cache_by_id = {}
    cache_by_name = {}
    
    data_path = Path(data_dir)
    if not data_path.exists():
        return cache_by_id, cache_by_name
        
    for p in data_path.glob("*.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
                for t in data.get("tracks", []):
                    spotify_id = t.get("spotifyId")
                    yt_id = t.get("ytMusicId")
                    artist = t.get("artist")
                    title = t.get("title")
                    
                    if yt_id:
                        if spotify_id:
                            cache_by_id[spotify_id] = yt_id
                        if artist and title:
                            key = f"{artist.lower().strip()}|||{title.lower().strip()}"
                            cache_by_name[key] = yt_id
        except Exception as e:
            print(f"Warning: Failed to parse cache from {p}: {e}")
            
    return cache_by_id, cache_by_name

def get_auth_file(auth_path):
    if auth_path:
        if not Path(auth_path).exists():
            print(f"Error: Specified auth file not found: {auth_path}")
            sys.exit(1)
        return auth_path
        
    # Auto-detect browser.json first (recommended/working), then oauth.json (known issues)
    for path in ["browser.json", "oauth.json"]:
        p = Path(path)
        if p.exists():
            return str(p)
            
    print("Error: No authentication file found (oauth.json or browser.json).")
    print("Please run the authentication setup first.")
    sys.exit(1)

def main():
    args = parse_args()
    
    # 1. Scrape chart data from Kworb
    chart = scrape_kworb(args.country)
    country_name = chart["countryName"]
    week_date = chart["weekDate"]
    tracks = chart["tracks"]
    
    print(f"Loaded {len(tracks)} tracks for {country_name} ({week_date}) from Kworb.")
    
    # 2. Authenticate with YouTube Music
    auth_file = get_auth_file(args.auth)
    print(f"Authenticating using: {auth_file}")
    
    try:
        with open(auth_file, "r") as f:
            auth_data = json.load(f)
    except Exception:
        auth_data = {}

    if isinstance(auth_data, dict) and "client_id" in auth_data and "client_secret" in auth_data:
        from ytmusicapi.auth.oauth.credentials import OAuthCredentials
        print("Detected OAuth credentials. Initializing with oauth_credentials.")
        yt = YTMusic(
            auth_file,
            oauth_credentials=OAuthCredentials(
                client_id=auth_data["client_id"],
                client_secret=auth_data["client_secret"]
            )
        )
    else:
        yt = YTMusic(auth_file)
        
    # 3. Load cache and enrich tracks with YouTube Music IDs
    cache_by_id, cache_by_name = load_ytmusic_cache(args.data_dir)
    print(f"Loaded cache from existing JSONs: {len(cache_by_id)} unique IDs, {len(cache_by_name)} name pairs.")
    
    resolved_count = 0
    cached_count = 0
    
    for t in tracks:
        spotify_id = t.get("spotifyId")
        artist = t.get("artist")
        title = t.get("title")
        
        # Check Spotify ID cache
        yt_id = cache_by_id.get(spotify_id) if spotify_id else None
        
        # Check Name cache
        if not yt_id and artist and title:
            key = f"{artist.lower().strip()}|||{title.lower().strip()}"
            yt_id = cache_by_name.get(key)
            
        if yt_id:
            t["ytMusicId"] = yt_id
            cached_count += 1
        else:
            if artist and title:
                query = f"{artist} {title}"
                try:
                    # Delay to prevent rate limiting
                    time.sleep(random.uniform(0.3, 0.8))
                    
                    search_results = yt.search(query, filter="songs")
                    if search_results:
                        yt_id = search_results[0].get("videoId")
                        if yt_id:
                            t["ytMusicId"] = yt_id
                            # Add to in-memory cache
                            if spotify_id:
                                cache_by_id[spotify_id] = yt_id
                            key = f"{artist.lower().strip()}|||{title.lower().strip()}"
                            cache_by_name[key] = yt_id
                            
                            resolved_count += 1
                        else:
                            print(f"  ⚠ No videoId found for: {query}")
                    else:
                        print(f"  ⚠ No search results for: {query}")
                except Exception as e:
                    print(f"  ⚠ YTMusic search failed for '{query}': {e}")
                    
    print(f"YTMusic Enrichment: {resolved_count} resolved via search, {cached_count} resolved via cache.")
    
    new_video_ids = [t["ytMusicId"] for t in tracks if t.get("ytMusicId")]
    print(f"Found {len(new_video_ids)} resolved YouTube Music track IDs out of {len(tracks)} tracks.")
    
    if not new_video_ids:
        print("No YouTube Music IDs found. Nothing to sync.")
        return

    if args.dry_run:
        print("\n--- DRY RUN ACTIVE ---")
        print(f"Would save updated data cache to {args.data_dir}/{args.country}.json")
        print(f"Would sync to playlist: Spotify Weekly {country_name} Top 200")
        print(f"Tracks to add (first 5): {new_video_ids[:5]}")
        print("Dry run complete. No mutations performed.")
        return

    # Save the updated chart data with resolved IDs to file
    data_path = Path(args.data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    out_file = data_path / f"{args.country}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(chart, f, indent=2, ensure_ascii=False)
    print(f"Saved updated data to {out_file}")

    # 4. Find or Create Playlist
    target_title = f"Spotify Weekly {country_name} Top 200"
    target_description = f"Synced automatically from Spotify weekly streaming chart on {week_date} via Spotifx bot."
    
    print(f"Searching for existing playlist: '{target_title}'...")
    playlists = yt.get_library_playlists(limit=None)
    playlist_id = None
    for pl in playlists:
        if pl["title"] == target_title:
            playlist_id = pl["playlistId"]
            print(f"Found existing playlist: {target_title} (ID: {playlist_id})")
            break
            
    is_new_playlist = False
    if not playlist_id:
        print(f"Playlist not found. Creating new public playlist: '{target_title}'...")
        playlist_id = yt.create_playlist(
            title=target_title,
            description=target_description,
            privacy_status="PUBLIC"
        )
        print(f"Created playlist ID: {playlist_id}")
        is_new_playlist = True

    # 5. Nuke and Rebuild
    if is_new_playlist:
        current_tracks = []
        current_count = 0
        print("Playlist is newly created and empty. Skipping track retrieval.")
    else:
        print("Fetching current playlist tracks...")
        playlist_details = yt.get_playlist(playlist_id, limit=None)
        current_tracks = playlist_details.get("tracks", [])
        current_count = len(current_tracks)
        print(f"Current playlist has {current_count} tracks.")
    
    # Remove all current tracks if any exist
    if current_count > 0:
        print(f"Removing {current_count} tracks...")
        to_remove = [{"videoId": t["videoId"], "setVideoId": t["setVideoId"]} for t in current_tracks if t.get("setVideoId") and t.get("videoId")]
        if to_remove:
            yt.remove_playlist_items(playlist_id, to_remove)
            print("Removal complete.")
        else:
            print("No tracks found with setVideoId. Skipping removal.")
        
    # Add new tracks in chunks of 50 to prevent timeouts/API limits
    print(f"Adding {len(new_video_ids)} tracks...")
    chunk_size = 50
    for i in range(0, len(new_video_ids), chunk_size):
        chunk = new_video_ids[i:i + chunk_size]
        print(f"Adding tracks {i+1} to {min(i + chunk_size, len(new_video_ids))}...")
        yt.add_playlist_items(playlist_id, chunk)
    print("Tracks added successfully.")
    
    # Update description to match the new Week Date
    print("Updating playlist description...")
    yt.edit_playlist(playlist_id, description=target_description)
    print("Description updated.")
    
    playlist_url = f"https://music.youtube.com/playlist?list={playlist_id}"
    print(f"\n🎉 Sync Complete! Playlist URL: {playlist_url}")

if __name__ == "__main__":
    main()
