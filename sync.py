#!/usr/bin/env python3
import json
import argparse
from pathlib import Path
from ytmusicapi import YTMusic

from utils import COUNTRIES, get_auth_file
from scraper import scrape_kworb
from playlist_sync import (
    load_ytmusic_cache,
    should_skip_sync,
    resolve_track_ids,
    find_or_create_playlist,
    sync_playlist
)

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
        help="Path to auth file (browser.json). Auto-detects if omitted."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without modifying YouTube Music playlists."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force sync even if the weekDate has not changed."
    )
    return parser.parse_args()

def main():
    args = parse_args()
    print(f"🚀 Starting YouTube Music sync for country: {args.country.upper()}")
    out_file = Path(args.data_dir) / f"{args.country}.json"
    
    # 1. Scrape chart data from Kworb
    chart = scrape_kworb(args.country)
    country_name = chart["countryName"]
    week_date = chart["weekDate"]
    tracks = chart["tracks"]
    
    print(f"Loaded {len(tracks)} tracks for {country_name} ({week_date}) from Kworb.")
    
    # Check if we already synchronized this week to save API quota
    if should_skip_sync(out_file, week_date, args.force, args.dry_run):
        print(f"ℹ️ Playlist for {country_name} is already up to date ({week_date}). Skipping sync.")
        return
            
    if args.force:
        print("Force flag active. Proceeding with sync regardless of cache date comparison.")
    
    # 2. Authenticate with YouTube Music
    auth_file = get_auth_file(args.auth)
    print(f"Authenticating using: {auth_file}")
    yt = YTMusic(auth_file)
        
    # 3. Load cache and enrich tracks with YouTube Music IDs
    cache_by_id, cache_by_name = load_ytmusic_cache(args.data_dir)
    print(f"Loaded cache from existing JSONs: {len(cache_by_id)} unique IDs, {len(cache_by_name)} name pairs.")
    
    tracks = resolve_track_ids(yt, tracks, cache_by_id, cache_by_name)
    
    # Deduplicate video IDs while preserving ranking order to prevent YTM API failure
    seen = set()
    new_video_ids = []
    for t in tracks:
        yt_id = t.get("ytMusicId")
        if yt_id and yt_id not in seen:
            seen.add(yt_id)
            new_video_ids.append(yt_id)
            
    print(f"Found {len(new_video_ids)} unique resolved YouTube Music track IDs out of {len(tracks)} tracks.")
    
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
        
    # 4. Find or Create Playlist
    target_title = f"Spotify Weekly {country_name} Top 200"
    target_description = f"Synced automatically from Spotify weekly streaming chart on {week_date} via Spotify sync bot."
    
    playlist_id, is_new_playlist, current_tracks = find_or_create_playlist(yt, target_title, target_description)
    
    # 5. Sync Playlist
    sync_playlist(yt, playlist_id, current_tracks, new_video_ids, target_description)
    
    # Save the updated chart data with resolved IDs to file (delayed to final step)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(chart, f, indent=2, ensure_ascii=False)
    print(f"Saved updated data to {out_file}")
    
    playlist_url = f"https://music.youtube.com/playlist?list={playlist_id}"
    print(f"\n🎉 Sync Complete! Playlist URL: {playlist_url}")

if __name__ == "__main__":
    main()
