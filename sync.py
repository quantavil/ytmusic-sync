#!/usr/bin/env python3
import json
import argparse
from pathlib import Path
from ytmusicapi import YTMusic

from utils import COUNTRIES
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
        help="Path to Google OAuth token file (token.json). Auto-detects if omitted."
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
    parser.add_argument(
        "--min-resolve-ratio",
        type=float,
        default=0.90,
        help="Minimum fraction of tracks that must resolve to a YouTube Music ID "
             "for this week to be marked as fully synced (default: 0.90). Below this, "
             "the sync still runs with whatever resolved, but the cache file is NOT "
             "written, so the next run retries the missing tracks instead of silently "
             "treating the week as done."
    )
    return parser.parse_args()

def main():
    args = parse_args()
    print(f"🚀 Starting YouTube Music sync for country: {args.country.upper()}")
    out_file = Path(args.data_dir) / f"{args.country}.json"
    
    from youtube_client import AuthError, QuotaExceededError
    try:
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
        
        # 2. Authenticate: unauthenticated YTMusic for search, official OAuth for writes
        print("Initializing unauthenticated YouTube Music client for searches...")
        yt_search = YTMusic()
        
        print("Loading official YouTube Data API client...")
        from youtube_client import get_youtube_client
        youtube = get_youtube_client(token_path=args.auth)
            
        # 3. Load cache and enrich tracks with YouTube Music IDs
        cache_by_id, cache_by_name = load_ytmusic_cache(args.data_dir)
        print(f"Loaded cache from existing JSONs: {len(cache_by_id)} unique IDs, {len(cache_by_name)} name pairs.")
        
        tracks, resolved_count, cached_count, failed_count = resolve_track_ids(yt_search, tracks, cache_by_id, cache_by_name)
        
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

        # Partial-failure guard: if too many tracks failed to resolve (transient
        # search errors, etc.), still sync what we have, but do NOT write the
        # cache file with the clean weekDate — otherwise should_skip_sync() would
        # treat this week as fully done and never retry the missing tracks until
        # next week.
        resolve_ratio = (resolved_count + cached_count) / len(tracks) if tracks else 1.0
        partial_failure = resolve_ratio < args.min_resolve_ratio
        if partial_failure:
            print(f"⚠️ Warning: Only {resolve_ratio:.1%} of tracks resolved (< {args.min_resolve_ratio:.0%} threshold, "
                  f"{failed_count} failed). Will sync with what resolved, but will NOT mark {week_date} as "
                  f"fully synced — next run will retry the missing tracks.")

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
        
        playlist_id, current_tracks, existing_description = find_or_create_playlist(youtube, target_title, target_description)
        
        # 5. Sync Playlist
        sync_playlist(youtube, playlist_id, current_tracks, new_video_ids, target_title, target_description, existing_description, data_dir=args.data_dir)
        
        # Save the updated chart data with resolved IDs to file (delayed to final step).
        # Write cache even on partial resolution failure to preserve resolved IDs,
        # but suffix the weekDate to ensure it retries on the next execution.
        out_file.parent.mkdir(parents=True, exist_ok=True)
        if partial_failure:
            print(f"ℹ️ Saving partial data to {out_file} to preserve resolved IDs, but marking as incomplete.")
            chart_copy = dict(chart)
            chart_copy["weekDate"] = f"{week_date}-partial"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(chart_copy, f, indent=2, ensure_ascii=False)
        else:
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(chart, f, indent=2, ensure_ascii=False)
            print(f"Saved updated data to {out_file}")
        
        playlist_url = f"https://music.youtube.com/playlist?list={playlist_id}"
        print(f"\n🎉 Sync Complete! Playlist URL: {playlist_url}")
        
    except AuthError as e:
        print(f"\n❌ Authentication Failure: {e}")
        print("Please run auth_google.py to set up your authorization credentials.")
        import sys
        sys.exit(1)
    except QuotaExceededError as e:
        print(f"\n❌ Quota Exceeded: {e}")
        print("The synchronization aborted because the Google YouTube Data API quota was exhausted.")
        import sys
        sys.exit(1)

if __name__ == "__main__":
    main()