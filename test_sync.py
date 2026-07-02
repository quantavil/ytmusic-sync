import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import json
import sys

from utils import clean_string, clean_title, title_matches, artist_matches, retry_operation
from playlist_sync import (
    should_skip_sync,
    find_or_create_playlist,
    resolve_track_ids,
    sync_playlist
)
from scraper import parse_kworb_html

class TestSyncBot(unittest.TestCase):

    def test_clean_string(self):
        self.assertEqual(clean_string("Hello, World!"), "hello world")
        self.assertEqual(clean_string("  Artist - Title (Remix)  "), "artist title remix")
        self.assertEqual(clean_string(""), "")
        self.assertEqual(clean_string(None), "")
        # Unicode normalization
        self.assertEqual(clean_string("eńau"), "enau")
        self.assertEqual(clean_string("JAŸ-Z"), "jayz")
        self.assertEqual(clean_string("Titã Me Preguntó"), "tita me pregunto")

    def test_clean_title(self):
        # Strip feat in parentheses
        self.assertEqual(clean_title("Closer (feat. Halsey)"), "closer")
        self.assertEqual(clean_title("No Lie (feat. Dua Lipa)"), "no lie")
        # Strip remaster suffixes
        self.assertEqual(clean_title("Smooth Criminal - 2012 Remaster"), "smooth criminal")
        self.assertEqual(clean_title("Wonderwall - Remastered"), "wonderwall")
        # Strip explicit/clean version tags
        self.assertEqual(clean_title("NORMAL (Explicit Ver.)"), "normal")
        self.assertEqual(clean_title("Seven - Explicit Ver. (feat. Latto)"), "seven")
        self.assertEqual(clean_title("Confident - Single Version"), "confident")
        # Strip radio edit
        self.assertEqual(clean_title("On The Floor (Radio Edit)"), "on the floor")
        # Strip from movie
        self.assertEqual(clean_title('I Knew It, I Knew You (From "Toy Story 5")'), "i knew it i knew you")
        # Strip pipe '|' metadata
        self.assertEqual(clean_title("Labon Ko - (Lyrics) | Bhool Bhulaiyaa | Pritam | K.K."), "labon ko")
        # Preserve "with" as an ordinary word in titles
        self.assertEqual(clean_title("Stay With Me"), "stay with me")
        self.assertEqual(clean_title("With You"), "with you")
        # But still strip bracketed "with" features
        self.assertEqual(clean_title("Closer (with Halsey)"), "closer")
        # No-op for clean titles
        self.assertEqual(clean_title("Blinding Lights"), "blinding lights")
        self.assertEqual(clean_title(""), "")
        self.assertEqual(clean_title(None), "")

    def test_title_matches(self):
        # Exact match
        self.assertTrue(title_matches("Blinding Lights", {"title": "Blinding Lights"}))

        # Match after stripping feat suffix
        self.assertTrue(title_matches("Starboy", {"title": "Starboy (feat. Daft Punk)"}))

        # Match after stripping remaster suffix
        self.assertTrue(title_matches("Smooth Criminal - 2012 Remaster", {"title": "Smooth Criminal"}))

        # Match with movie suffix stripped from both
        self.assertTrue(title_matches('Sajni (From "Laapataa Ladies")', {"title": "Sajni"}))

        # Mismatched title (ratio too low) → reject
        self.assertFalse(title_matches("Blinding Lights", {"title": "Starboy"}))

        # Composer/singer crossover — title-only so this passes now
        self.assertTrue(title_matches("Aawaara Angaara", {"title": "Aawaara Angaara"}))

        # Video title with pipe stripped
        self.assertTrue(title_matches("Labon Ko", {"title": "Labon Ko - (Lyrics) | Bhool Bhulaiyaa | Pritam"}))

        # Version mismatches (Remix, Acoustic, Instrumental, Live, Cover, Tribute, Karaoke)
        self.assertFalse(title_matches("Espresso", {"title": "Espresso (Remix)"}))
        self.assertFalse(title_matches("Espresso", {"title": "Espresso (Acoustic Version)"}))
        self.assertFalse(title_matches("Espresso", {"title": "Espresso (Instrumental)"}))
        self.assertFalse(title_matches("Espresso", {"title": "Espresso (Live)"}))
        self.assertFalse(title_matches("Espresso", {"title": "Espresso (Cover)"}))
        self.assertFalse(title_matches("Espresso", {"title": "Espresso (Karaoke)"}))
        
        # Matching versions
        self.assertTrue(title_matches("Espresso (Remix)", {"title": "Espresso (Remix)"}))
        self.assertTrue(title_matches("Espresso - Remix", {"title": "Espresso (rmx)"}))
        self.assertTrue(title_matches("Tribute", {"title": "Tribute"}))

    def test_artist_matches(self):
        # Exact match
        self.assertTrue(artist_matches("The Weeknd", {"artists": [{"name": "The Weeknd"}]}))

        # Collab component match
        self.assertTrue(artist_matches("Justin Bieber & Daniel Caesar", {"artists": [{"name": "Daniel Caesar"}]}))
        self.assertTrue(artist_matches("Sachet-Parampara", {"artists": [{"name": "Parampara Tandon"}]}))

        # Substring match (valid containing tokens)
        self.assertTrue(artist_matches("Post Malone", {"artists": [{"name": "Post Malone feat. 21 Savage"}]}))

        # Mismatched artist
        self.assertFalse(artist_matches("The Weeknd", {"artists": [{"name": "Different Artist"}]}))
        self.assertFalse(artist_matches("The Weeknd", {"artists": [{"name": ""}]}))

        # Tightened token match (rejecting false-positives of substring containment)
        self.assertFalse(artist_matches("Ana", {"artists": [{"name": "Anastasia"}]}))
        self.assertFalse(artist_matches("War", {"artists": [{"name": "Warpaint"}]}))
        self.assertFalse(artist_matches("Ari", {"artists": [{"name": "Arijit Singh"}]}))

        # Rejecting tribute/cover/karaoke acts
        self.assertFalse(artist_matches("Taylor Swift", {"artists": [{"name": "Taylor Swift Tribute Band"}]}))
        self.assertFalse(artist_matches("Taylor Swift", {"artists": [{"name": "Taylor Swift Cover Band"}]}))
        self.assertFalse(artist_matches("Taylor Swift", {"artists": [{"name": "Karaoke Taylor Swift"}]}))
        self.assertTrue(artist_matches("The Cover Girls", {"artists": [{"name": "The Cover Girls"}]}))

    def test_retry_operation_success(self):
        call_count = 0
        def dummy_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        res = retry_operation(dummy_func, attempts=3, delay=0.01)
        self.assertEqual(res, "success")
        self.assertEqual(call_count, 1)

    def test_retry_operation_fail_then_succeed(self):
        call_count = 0
        def dummy_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("Transient error")
            return "success"
            
        res = retry_operation(dummy_func, attempts=3, delay=0.01)
        self.assertEqual(res, "success")
        self.assertEqual(call_count, 2)

    def test_retry_operation_fatal(self):
        def dummy_func():
            raise ValueError("Fatal error")
            
        with self.assertRaises(SystemExit):
            retry_operation(dummy_func, attempts=3, delay=0.01, fatal=True)

    def test_retry_operation_non_fatal(self):
        def dummy_func():
            raise ValueError("Soft error")
            
        res = retry_operation(dummy_func, attempts=2, delay=0.01, fatal=False)
        self.assertIsNone(res)

    def test_should_skip_sync(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_cache = Path(tmpdir) / "global.json"
            
            # Case 1: Cache file does not exist
            self.assertFalse(should_skip_sync(temp_cache, "2026-07-01", force=False, dry_run=False))
            
            # Write cache
            cache_data = {"weekDate": "2026-07-01"}
            with open(temp_cache, "w") as f:
                json.dump(cache_data, f)
                
            # Case 2: Matching date, default flags -> should skip
            self.assertTrue(should_skip_sync(temp_cache, "2026-07-01", force=False, dry_run=False))
            
            # Case 3: Matching date, force = True -> should not skip
            self.assertFalse(should_skip_sync(temp_cache, "2026-07-01", force=True, dry_run=False))
            
            # Case 4: Matching date, dry_run = True -> should not skip
            self.assertFalse(should_skip_sync(temp_cache, "2026-07-01", force=False, dry_run=True))
            
            # Case 5: Mismatched date -> should not skip
            self.assertFalse(should_skip_sync(temp_cache, "2026-07-08", force=False, dry_run=False))

    def test_parse_kworb_html_success(self):
        mock_html = """
        <html>
        <head><title>Spotify Weekly Chart 2026-07-01</title></head>
        <body>
        <span class="pagetitle">Spotify Weekly Chart - 2026-07-01</span>
        <table>
            <tr>
                <th>Pos</th>
                <th>P+</th>
                <th>Artist and Title</th>
                <th>Wks</th>
                <th>Pk</th>
                <th>(x?)</th>
                <th>Streams</th>
                <th>Streams+</th>
                <th>Total</th>
            </tr>
            <tr>
                <td>1</td>
                <td>0</td>
                <td><a href="artist/1.html">Artist A</a> - <a href="track/spotifyid1.html">Title A</a></td>
                <td>10</td>
                <td>1</td>
                <td>x</td>
                <td>1,500,000</td>
                <td>100,000</td>
                <td>15,000,000</td>
            </tr>
            <tr>
                <td>2</td>
                <td>+1</td>
                <td><a href="artist/2.html">Artist B</a> - <a href="track/spotifyid2.html">Title B</a></td>
                <td>5</td>
                <td>2</td>
                <td></td>
                <td>1,200,000</td>
                <td>50,000</td>
                <td>6,000,000</td>
            </tr>
        </table>
        </body>
        </html>
        """
        
        parsed = parse_kworb_html(mock_html, "global")
        self.assertEqual(parsed["weekDate"], "2026-07-01")
        self.assertEqual(len(parsed["tracks"]), 2)
        
        track1 = parsed["tracks"][0]
        self.assertEqual(track1["rank"], 1)
        self.assertEqual(track1["change"], "0")
        self.assertEqual(track1["artist"], "Artist A")
        self.assertEqual(track1["title"], "Title A")
        self.assertEqual(track1["spotifyId"], "spotifyid1")
        self.assertEqual(track1["streams"], 1500000)
        self.assertEqual(track1["peak"], 1)
        self.assertEqual(track1["weeks"], 10)

    def test_parse_kworb_html_zero_rows(self):
        mock_html_empty = "<html><body><table><tr><th>Pos</th></tr></table></body></html>"
        with self.assertRaises(ValueError):
            parse_kworb_html(mock_html_empty, "global")

    def test_parse_kworb_html_missing_date(self):
        mock_html_no_date = """
        <html>
        <head><title>Spotify Weekly Chart</title></head>
        <body>
        <table>
            <tr><th>Pos</th><th>P+</th><th>Artist and Title</th><th>Wks</th><th>Pk</th><th>(x?)</th><th>Streams</th></tr>
            <tr><td>1</td><td>0</td><td>Artist A - <a href="track/1.html">Title A</a></td><td>10</td><td>1</td><td>x</td><td>1,500,000</td></tr>
        </table>
        </body>
        </html>
        """
        with self.assertRaises(ValueError):
            parse_kworb_html(mock_html_no_date, "global")

    def test_parse_kworb_html_fallback(self):
        mock_html = """
        <html>
        <head><title>Spotify Weekly Chart 2026-07-01</title></head>
        <body>
        <span class="pagetitle">Spotify Weekly Chart - 2026-07-01</span>
        <table>
            <tr>
                <th>Unrecognized1</th>
                <th>Unrecognized2</th>
                <th>Unrecognized3</th>
                <th>Unrecognized4</th>
                <th>Unrecognized5</th>
                <th>Unrecognized6</th>
                <th>Unrecognized7</th>
            </tr>
            <tr>
                <td>10</td>
                <td>+5</td>
                <td><a href="artist/1.html">Artist A</a> - <a href="track/spotifyid1.html">Title A</a></td>
                <td>12</td>
                <td>3</td>
                <td>unused</td>
                <td>2,000,000</td>
            </tr>
        </table>
        </body>
        </html>
        """
        parsed = parse_kworb_html(mock_html, "global")
        self.assertEqual(parsed["weekDate"], "2026-07-01")
        self.assertEqual(len(parsed["tracks"]), 1)
        track = parsed["tracks"][0]
        self.assertEqual(track["rank"], 10)
        self.assertEqual(track["change"], "+5")
        self.assertEqual(track["artist"], "Artist A")
        self.assertEqual(track["title"], "Title A")
        self.assertEqual(track["weeks"], 12)
        self.assertEqual(track["peak"], 3)
        self.assertEqual(track["streams"], 2000000)

    def test_parse_kworb_html_single_anchor(self):
        mock_html = """
        <html>
        <head><title>Spotify Weekly Chart 2026-07-01</title></head>
        <body>
        <span class="pagetitle">Spotify Weekly Chart - 2026-07-01</span>
        <table>
            <tr>
                <th>Pos</th>
                <th>P+</th>
                <th>Artist and Title</th>
                <th>Wks</th>
                <th>Pk</th>
                <th>(x?)</th>
                <th>Streams</th>
            </tr>
            <tr>
                <td>1</td>
                <td>0</td>
                <td>Artist A - <a href="track/spotifyid1.html">Title A</a></td>
                <td>10</td>
                <td>1</td>
                <td>x</td>
                <td>1,500,000</td>
            </tr>
        </table>
        </body>
        </html>
        """
        parsed = parse_kworb_html(mock_html, "global")
        self.assertEqual(len(parsed["tracks"]), 1)
        track = parsed["tracks"][0]
        self.assertEqual(track["artist"], "Artist A")
        self.assertEqual(track["title"], "Title A")
        self.assertEqual(track["spotifyId"], "spotifyid1")

    def test_parse_kworb_html_low_count(self):
        mock_html = """
        <html>
        <head><title>Spotify Weekly Chart 2026-07-01</title></head>
        <body>
        <span class="pagetitle">Spotify Weekly Chart - 2026-07-01</span>
        <table>
            <tr>
                <th>Pos</th><th>P+</th><th>Artist and Title</th><th>Wks</th><th>Pk</th><th>(x?)</th><th>Streams</th>
            </tr>
            <tr>
                <td>1</td><td>0</td><td><a href="artist/1.html">Artist A</a> - <a href="track/spotifyid1.html">Title A</a></td><td>10</td><td>1</td><td>x</td><td>1,500,000</td>
            </tr>
        </table>
        </body>
        </html>
        """
        parsed = parse_kworb_html(mock_html, "global")
        self.assertEqual(len(parsed["tracks"]), 1)

    @patch("playlist_sync.retry_operation", side_effect=lambda func, *args, **kwargs: func())
    def test_find_or_create_playlist_existing(self, mock_retry):
        yt = MagicMock()
        yt.get_library_playlists.return_value = [
            {"title": "Spotify Weekly Global Top 200", "playlistId": "pl_123"}
        ]
        yt.get_playlist.return_value = {
            "tracks": [{"videoId": "vid1", "setVideoId": "svid1"}]
        }
        
        playlist_id, current_tracks = find_or_create_playlist(yt, "Spotify Weekly Global Top 200", "desc")
        
        self.assertEqual(playlist_id, "pl_123")
        self.assertEqual(len(current_tracks), 1)
        self.assertEqual(current_tracks[0]["videoId"], "vid1")
        yt.get_library_playlists.assert_called_once()
        yt.get_playlist.assert_called_once_with("pl_123", limit=None)
        yt.create_playlist.assert_not_called()

    @patch("playlist_sync.retry_operation", side_effect=lambda func, *args, **kwargs: func())
    def test_find_or_create_playlist_new(self, mock_retry):
        yt = MagicMock()
        yt.get_library_playlists.return_value = []
        yt.create_playlist.return_value = "new_pl_456"
        
        playlist_id, current_tracks = find_or_create_playlist(yt, "Spotify Weekly Global Top 200", "desc")
        
        self.assertEqual(playlist_id, "new_pl_456")
        self.assertEqual(current_tracks, [])
        yt.get_library_playlists.assert_called_once()
        yt.create_playlist.assert_called_once_with(
            title="Spotify Weekly Global Top 200",
            description="desc",
            privacy_status="PUBLIC"
        )
        yt.get_playlist.assert_not_called()

    def test_find_or_create_playlist_create_status_failed(self):
        yt = MagicMock()
        yt.get_library_playlists.return_value = []
        yt.create_playlist.return_value = "STATUS_FAILED"
        
        # Because create_pl raises RuntimeError when status is STATUS_FAILED, 
        # retry_operation will exhaust retries and call sys.exit(1) because fatal=True.
        with self.assertRaises(SystemExit):
            find_or_create_playlist(yt, "Spotify Weekly Global Top 200", "desc")

    def test_resolve_track_ids(self):
        yt = MagicMock()
        # Mock search results: first result matches artist and title
        yt.search.return_value = [
            {"title": "Blinding Lights", "artists": [{"name": "The Weeknd"}], "videoId": "yt_light"}
        ]
        
        tracks = [
            {"spotifyId": "sp1", "artist": "The Weeknd", "title": "Blinding Lights"},
            {"spotifyId": "sp2", "artist": "Dua Lipa", "title": "Levitating"}
        ]
        cache_by_id = {"sp2": "yt_levitate"}
        cache_by_name = {}
        
        resolved = resolve_track_ids(yt, tracks, cache_by_id, cache_by_name)
        
        self.assertEqual(resolved[0]["ytMusicId"], "yt_light")
        self.assertEqual(resolved[1]["ytMusicId"], "yt_levitate")
        # Songs search matched, so only songs filter was called
        yt.search.assert_called_once_with("The Weeknd Blinding Lights", filter="songs")

    def test_resolve_track_ids_video_fallback(self):
        yt = MagicMock()
        # Songs search returns no matching result, video search does
        def mock_search(query, filter=None):
            if filter == "songs":
                return [{"title": "Wrong Song", "artists": [{"name": "Wrong Artist"}], "videoId": "wrong"}]
            elif filter == "videos":
                return [{"title": "One Dance", "artists": [{"name": "Drake"}], "videoId": "yt_dance"}]
            return []
        yt.search.side_effect = mock_search
        
        tracks = [{"spotifyId": "sp1", "artist": "Drake", "title": "One Dance"}]
        
        resolved = resolve_track_ids(yt, tracks, {}, {})
        
        self.assertEqual(resolved[0]["ytMusicId"], "yt_dance")
        self.assertEqual(yt.search.call_count, 2)
        yt.search.assert_any_call("Drake One Dance", filter="songs")
        yt.search.assert_any_call("Drake One Dance", filter="videos")

    @patch("playlist_sync.retry_operation", side_effect=lambda func, *args, **kwargs: func())
    def test_sync_playlist_success(self, mock_retry):
        yt = MagicMock()
        yt.add_playlist_items.return_value = {"status": "STATUS_SUCCEEDED"}
        
        current_tracks = [
            {"videoId": "old1", "setVideoId": "svid1"},
            {"videoId": "old2", "setVideoId": "svid2"}
        ]
        new_tracks = [f"new_{i}" for i in range(55)]
        
        sync_playlist(yt, "pl_123", current_tracks, new_tracks, "new description")
        
        # Verify add_playlist_items is called twice (chunk size 50)
        self.assertEqual(yt.add_playlist_items.call_count, 2)
        yt.add_playlist_items.assert_any_call("pl_123", new_tracks[:50], duplicates=True)
        yt.add_playlist_items.assert_any_call("pl_123", new_tracks[50:], duplicates=True)
        
        # Verify remove_playlist_items is called with current tracks
        yt.remove_playlist_items.assert_called_once_with(
            "pl_123",
            [
                {"videoId": "old1", "setVideoId": "svid1"},
                {"videoId": "old2", "setVideoId": "svid2"}
            ]
        )
        
        # Verify edit_playlist is called
        yt.edit_playlist.assert_called_once_with("pl_123", description="new description")

    @patch("utils.time.sleep", return_value=None)
    def test_sync_playlist_add_failed(self, mock_sleep):
        yt = MagicMock()
        yt.add_playlist_items.return_value = {"status": "STATUS_FAILED"}
        
        with self.assertRaises(SystemExit):
            sync_playlist(yt, "pl_123", [], ["new_1"], "desc")
        self.assertEqual(yt.add_playlist_items.call_count, 3)
        yt.add_playlist_items.assert_any_call("pl_123", ["new_1"], duplicates=True)

if __name__ == "__main__":
    unittest.main()
