import sys
import time
import random
import json
from pathlib import Path

from utils import retry_operation, verify_match

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

def should_skip_sync(out_file, week_date, force, dry_run):
    if out_file.exists() and not force and not dry_run:
        try:
            with open(out_file, "r", encoding="utf-8") as f:
                cached_chart = json.load(f)
            cached_week_date = cached_chart.get("weekDate")
            print(f"Checking sync status: Cached Date = {cached_week_date}, Chart Date = {week_date}")
            if cached_week_date == week_date:
                return True
        except Exception as e:
            print(f"⚠️ Warning: Failed to read cached chart file to compare weekDate: {e}")
    return False

def find_or_create_playlist(yt, target_title, target_description):
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
        
        def create_pl():
            return yt.create_playlist(
                title=target_title,
                description=target_description,
                privacy_status="PUBLIC"
            )
            
        res = retry_operation(
            create_pl,
            attempts=3,
            delay=2,
            fatal=True,
            error_msg="Create playlist"
        )
        if isinstance(res, str) and res != "STATUS_FAILED":
            playlist_id = res
        elif isinstance(res, dict) and "playlistId" in res:
            playlist_id = res["playlistId"]
        else:
            print(f"❌ Error: Failed to create playlist. Response: {res}")
            sys.exit(1)
        print(f"Created playlist ID: {playlist_id}")
        is_new_playlist = True
        
    if is_new_playlist:
        current_tracks = []
    else:
        print("Fetching current playlist tracks...")
        playlist_details = yt.get_playlist(playlist_id, limit=None)
        current_tracks = playlist_details.get("tracks", [])
        print(f"Current playlist has {len(current_tracks)} tracks.")
        
    return playlist_id, is_new_playlist, current_tracks

def resolve_track_ids(yt, tracks, cache_by_id, cache_by_name):
    resolved_count = 0
    cached_count = 0
    
    print("Enriching track metadata with YouTube Music IDs...")
    # WARNING: This loop MUST execute sequentially. Each successful resolution updates
    # cache_by_name, which is referenced by subsequent items. Parallelizing or reordering
    # this loop will break duplicate-detection, resulting in duplicate search queries.
    for idx, t in enumerate(tracks):
        if (idx + 1) % 50 == 0 or idx == 0 or idx == len(tracks) - 1:
            print(f"  Progress: {idx + 1}/{len(tracks)} tracks processed...")
            
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
                        matched_result = None
                        # Check top 5 results for verification
                        for r_idx, res in enumerate(search_results[:5]):
                            if verify_match(artist, title, res):
                                matched_result = res
                                break
                        
                        if matched_result:
                            yt_id = matched_result.get("videoId")
                            if yt_id:
                                print(f"    🔍 [Search] Resolved '{query}' to YouTube ID: {yt_id} (matched on result {r_idx + 1})")
                                t["ytMusicId"] = yt_id
                                # Add to in-memory cache
                                if spotify_id:
                                    cache_by_id[spotify_id] = yt_id
                                key = f"{artist.lower().strip()}|||{title.lower().strip()}"
                                cache_by_name[key] = yt_id
                                
                                resolved_count += 1
                            else:
                                print(f"  ⚠ No videoId found in verified match for: {query}")
                        else:
                            print(f"  ⚠️ Warning: Verification failed for '{query}'. None of the top {len(search_results[:5])} results passed the similarity criteria.")
                    else:
                        print(f"  ⚠ No search results for: {query}")
                except Exception as e:
                    print(f"  ⚠ YTMusic search failed for '{query}': {e}")
                    
    print(f"YTMusic Enrichment: {resolved_count} resolved via search, {cached_count} resolved via cache.")
    return tracks

def sync_playlist(yt, playlist_id, current_tracks, new_video_ids, target_description):
    # A. Add new tracks first (appends to the end of the playlist)
    print(f"Adding {len(new_video_ids)} new tracks...")
    chunk_size = 50
    for i in range(0, len(new_video_ids), chunk_size):
        chunk = new_video_ids[i:i + chunk_size]
        print(f"Adding tracks {i+1} to {min(i + chunk_size, len(new_video_ids))}...")
        
        def upload_chunk():
            res = yt.add_playlist_items(playlist_id, chunk)
            status = res.get('status') if isinstance(res, dict) else res
            if status == 'STATUS_FAILED':
                raise RuntimeError(f"STATUS_FAILED: {res}")
            return res

        retry_operation(
            upload_chunk,
            attempts=3,
            delay=2,
            fatal=True,
            error_msg=f"Add chunk {i+1} to {min(i + chunk_size, len(new_video_ids))} to playlist"
        )
    print("New tracks added successfully.")

    # B. Remove old tracks (removes original track instances by original setVideoId)
    current_count = len(current_tracks)
    if current_count > 0:
        to_remove = []
        skipped_remove_count = 0
        for t in current_tracks:
            vid = t.get("videoId")
            svid = t.get("setVideoId")
            if vid and svid:
                to_remove.append({"videoId": vid, "setVideoId": svid})
            else:
                skipped_remove_count += 1
        
        if skipped_remove_count > 0:
            print(f"⚠️ Warning: {skipped_remove_count} tracks in original playlist could not be marked for removal because they lack videoId or setVideoId.")
            
        if to_remove:
            print(f"Removing {len(to_remove)} old tracks from YouTube Music playlist...")
            retry_operation(
                lambda: yt.remove_playlist_items(playlist_id, to_remove),
                attempts=3,
                delay=2,
                fatal=True,
                error_msg="Remove tracks from playlist"
            )
            print("Removal of old tracks complete.")
        else:
            print("No tracks with valid setVideoId and videoId found. Skipping removal.")

    # C. Update description to match the new Week Date
    print("Updating playlist description...")
    retry_operation(
        lambda: yt.edit_playlist(playlist_id, description=target_description),
        attempts=3,
        delay=2,
        fatal=False,
        error_msg="Update playlist description"
    )
    print("Description update completed (or skipped on failure).")
