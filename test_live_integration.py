#!/usr/bin/env python3
"""
Live Integration Test for ytmusic-sync.

This script executes real API calls using the credentials in token.json.
It will:
1. Create a temporary playlist "Spotify Sync Bot - Temp Hindi Test".
2. Populate it with an initial set of 6 Hindi tracks.
3. Run the sync_playlist logic to execute a HARD rearrangement:
   - Delete 2 tracks (Bairan, Gehra Hua).
   - Insert 2 new tracks (Finding Her, Sahiba) in the middle.
   - Reshuffle the remaining tracks from [Arz Kiya Hai, Khat, Tum Ho Toh, Sheesha]
     into the relative order [Sheesha, Khat, Tum Ho Toh, Arz Kiya Hai].
4. Fetch the final playlist items from YouTube to verify the correct sequence.
5. Robustly delete the temporary playlist with retries to clean up.
"""
import sys
import time
from youtube_client import get_youtube_client
from playlist_sync import find_or_create_playlist, sync_playlist

# Real, active YouTube Music / Video IDs from India chart:
# - Track A (Bairan): kyqJ_FId-_w      (deleted)
# - Track B (Arz Kiya Hai): -BJt4fCAtZE  (moved to pos 5)
# - Track C (Khat): KrJ5c-Egz-U         (moved to pos 1)
# - Track D (Gehra Hua): i1o1p_DD6TU     (deleted)
# - Track E (Tum Ho Toh): N7jDUBRVQVA    (moved to pos 3)
# - Track F (Sheesha): JPfoLgd3uKg       (moved to pos 0)
# - Track X (Finding Her): PZtSnQBsBW0   (inserted at pos 2)
# - Track Y (Sahiba): tNc2coVC2aw        (inserted at pos 4)

TEMP_TITLE = "Spotify Sync Bot - Temp Hindi Test"
TEMP_DESC = "Temporary playlist for testing Spotify to YTM synchronization. Will be deleted."

def main():
    print("🔑 Authenticating with YouTube Data API...")
    try:
        youtube = get_youtube_client()
    except Exception as e:
        print(f"❌ Authentication failed: {e}")
        print("Please make sure you have generated token.json by running auth_google.py.")
        sys.exit(1)

    playlist_id = None
    try:
        # Step 1: Create the temporary playlist
        print(f"➕ Creating temporary playlist: '{TEMP_TITLE}'...")
        res = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": TEMP_TITLE,
                    "description": TEMP_DESC
                },
                "status": {
                    "privacyStatus": "private"  # keep it private during test
                }
            }
        ).execute()
        playlist_id = res["id"]
        print(f"🎉 Created playlist with ID: {playlist_id}")

        # Step 2: Populate initial tracks
        # Order: Bairan, Arz Kiya Hai, Khat, Gehra Hua, Tum Ho Toh, Sheesha
        initial_vids = ["kyqJ_FId-_w", "-BJt4fCAtZE", "KrJ5c-Egz-U", "i1o1p_DD6TU", "N7jDUBRVQVA", "JPfoLgd3uKg"]
        print(f"🚀 Populating initial playlist with {len(initial_vids)} tracks...")
        for vid in initial_vids:
            for attempt in range(3):
                try:
                    youtube.playlistItems().insert(
                        part="snippet",
                        body={
                            "snippet": {
                                "playlistId": playlist_id,
                                "resourceId": {
                                    "kind": "youtube#video",
                                    "videoId": vid
                                }
                            }
                        }
                    ).execute()
                    break
                except Exception as e:
                    if attempt < 2:
                        print(f"  ⚠️ Warning: Populating track {vid} failed: {e}. Retrying in 2 seconds...")
                        time.sleep(2.0)
                    else:
                        raise e
            time.sleep(1.0)
        print("Initial population complete.")

        # Step 3: Fetch current tracks from YouTube to simulate existing state
        print("🔍 Fetching current state from YouTube...")
        _, current_tracks, existing_title, existing_description = find_or_create_playlist(youtube, TEMP_TITLE, TEMP_DESC)

        # Step 4: Define target state
        # Order: Sheesha, Khat, Finding Her (NEW), Tum Ho Toh, Sahiba (NEW), Arz Kiya Hai
        # Video IDs: ["JPfoLgd3uKg", "KrJ5c-Egz-U", "PZtSnQBsBW0", "N7jDUBRVQVA", "tNc2coVC2aw", "-BJt4fCAtZE"]
        target_video_ids = ["JPfoLgd3uKg", "KrJ5c-Egz-U", "PZtSnQBsBW0", "N7jDUBRVQVA", "tNc2coVC2aw", "-BJt4fCAtZE"]
        print(f"🔄 Syncing playlist to target order: {target_video_ids}...")

        # Execute sync_playlist
        sync_playlist(
            youtube=youtube,
            playlist_id=playlist_id,
            current_tracks=current_tracks,
            new_video_ids=target_video_ids,
            target_title=TEMP_TITLE,
            target_description=TEMP_DESC,
            existing_title=existing_title,
            existing_description=existing_description
        )

        # Step 5: Verify final state on YouTube
        print("🧪 Verifying mutations on YouTube...")
        res_items = youtube.playlistItems().list(
            playlistId=playlist_id,
            part="snippet",
            maxResults=10
        ).execute()

        items = res_items.get("items", [])
        final_video_ids = [item["snippet"]["resourceId"]["videoId"] for item in items]
        print(f"Final video IDs on YouTube: {final_video_ids}")

        assert len(final_video_ids) == 6, f"Expected 6 tracks, found {len(final_video_ids)}"
        assert final_video_ids[0] == "JPfoLgd3uKg", f"Expected Sheesha at index 0, found {final_video_ids[0]}"
        assert final_video_ids[1] == "KrJ5c-Egz-U", f"Expected Khat at index 1, found {final_video_ids[1]}"
        assert final_video_ids[2] == "PZtSnQBsBW0", f"Expected Finding Her at index 2, found {final_video_ids[2]}"
        assert final_video_ids[3] == "N7jDUBRVQVA", f"Expected Tum Ho Toh at index 3, found {final_video_ids[3]}"
        assert final_video_ids[4] == "tNc2coVC2aw", f"Expected Sahiba at index 4, found {final_video_ids[4]}"
        assert final_video_ids[5] == "-BJt4fCAtZE", f"Expected Arz Kiya Hai at index 5, found {final_video_ids[5]}"

        print("✅ SUCCESS: Complex Add, Delete, and Reorder (LIS) operations verified successfully on YouTube!")

    except AssertionError as e:
        print(f"❌ Assertion Failure during verification: {e}")
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
    finally:
        # Step 6: Cleanup - delete the temporary playlist with robust retries
        if playlist_id:
            print("⏳ Waiting 3 seconds for YouTube API cache synchronization before deleting...")
            time.sleep(3.0)
            
            attempts = 3
            for attempt in range(attempts):
                print(f"🧹 Cleaning up: Deleting temporary playlist '{TEMP_TITLE}' (ID: {playlist_id}) [Attempt {attempt+1}/{attempts}]...")
                try:
                    youtube.playlists().delete(id=playlist_id).execute()
                    print("🗑️ Playlist deleted successfully.")
                    break
                except Exception as e:
                    print(f"⚠️ Warning: Failed to delete playlist: {e}")
                    if attempt < attempts - 1:
                        print("⏳ Retrying deletion in 3 seconds...")
                        time.sleep(3.0)
                    else:
                        print("❌ Could not delete temporary playlist after max attempts. Please delete manually.")

if __name__ == "__main__":
    main()
