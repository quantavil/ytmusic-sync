import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import json

from utils import clean_string, clean_title, title_matches, artist_matches, retry_operation
from playlist_sync import (
    should_skip_sync,
    find_or_create_playlist,
    resolve_track_ids,
    sync_playlist
)
from scraper import parse_kworb_html

def make_mock_html(rows_html, headers=None, date="2026-07-01"):
    if headers is None:
        headers = ["Pos", "P+", "Artist and Title", "Wks", "Pk", "(x?)", "Streams", "Streams+", "Total"]
    headers_html = "".join(f"<th>{h}</th>" for h in headers)
    return f"""
    <html>
    <head><title>Spotify Weekly Chart {date}</title></head>
    <body>
    <span class="pagetitle">Spotify Weekly Chart - {date}</span>
    <table>
        <tr>{headers_html}</tr>
        {rows_html}
    </table>
    </body>
    </html>
    """

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
        # Unicode script preservation (e.g. Hindi/Devanagari)
        self.assertEqual(clean_string("सजनी"), "सजनी")
        self.assertEqual(clean_string("Dil Bechara (दिल बेचारा)"), "dil bechara दिल बेचारा")

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
        # Preserve legitimate "from" inside parentheses
        self.assertEqual(clean_title("Song (From Now On)"), "song from now on")
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
            
        with self.assertRaises(ValueError):
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
        rows = """
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
            <td>=</td>
            <td><a href="artist/2.html">Artist B</a> - <a href="track/spotifyid2.html">Title B</a></td>
            <td>5</td>
            <td>2</td>
            <td></td>
            <td>1,200,000</td>
            <td>50,000</td>
            <td>6,000,000</td>
        </tr>
        """
        mock_html = make_mock_html(rows)
        
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

        track2 = parsed["tracks"][1]
        self.assertEqual(track2["change"], "0")

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
        headers = ["Unrecognized1", "Unrecognized2", "Unrecognized3", "Unrecognized4", "Unrecognized5", "Unrecognized6", "Unrecognized7"]
        rows = """
        <tr>
            <td>10</td>
            <td>+5</td>
            <td><a href="artist/1.html">Artist A</a> - <a href="track/spotifyid1.html">Title A</a></td>
            <td>12</td>
            <td>3</td>
            <td>unused</td>
            <td>2,000,000</td>
        </tr>
        """
        mock_html = make_mock_html(rows, headers)
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
        headers = ["Pos", "P+", "Artist and Title", "Wks", "Pk", "(x?)", "Streams"]
        rows = """
        <tr>
            <td>1</td>
            <td>0</td>
            <td>Artist A - <a href="track/spotifyid1.html">Title A</a></td>
            <td>10</td>
            <td>1</td>
            <td>x</td>
            <td>1,500,000</td>
        </tr>
        """
        mock_html = make_mock_html(rows, headers)
        parsed = parse_kworb_html(mock_html, "global")
        self.assertEqual(len(parsed["tracks"]), 1)
        track = parsed["tracks"][0]
        self.assertEqual(track["artist"], "Artist A")
        self.assertEqual(track["title"], "Title A")
        self.assertEqual(track["spotifyId"], "spotifyid1")

    def test_parse_kworb_html_low_count(self):
        headers = ["Pos", "P+", "Artist and Title", "Wks", "Pk", "(x?)", "Streams"]
        rows = """
        <tr>
            <td>1</td><td>0</td><td><a href="artist/1.html">Artist A</a> - <a href="track/spotifyid1.html">Title A</a></td><td>10</td><td>1</td><td>x</td><td>1,500,000</td>
        </tr>
        """
        mock_html = make_mock_html(rows, headers)
        parsed = parse_kworb_html(mock_html, "global")
        self.assertEqual(len(parsed["tracks"]), 1)

    @patch("playlist_sync.call", side_effect=lambda func, *args, **kwargs: func())
    def test_find_or_create_playlist_existing(self, mock_call):
        youtube = MagicMock()
        
        list_playlists_mock = MagicMock()
        list_playlists_mock.execute.return_value = {
            "items": [
                {
                    "id": "pl_123",
                    "snippet": {"title": "Spotify Weekly Global Top 200", "description": "desc"}
                }
            ],
            "nextPageToken": None
        }
        youtube.playlists().list.return_value = list_playlists_mock
        
        list_items_mock = MagicMock()
        list_items_mock.execute.return_value = {
            "items": [
                {
                    "id": "svid1",
                    "snippet": {
                        "resourceId": {"videoId": "vid1"}
                    }
                }
            ],
            "nextPageToken": None
        }
        youtube.playlistItems().list.return_value = list_items_mock
        
        playlist_id, current_tracks, existing_title, existing_description = find_or_create_playlist(youtube, "Spotify Weekly Global Top 200", "desc")
        
        self.assertEqual(playlist_id, "pl_123")
        self.assertEqual(len(current_tracks), 1)
        self.assertEqual(current_tracks[0]["videoId"], "vid1")
        self.assertEqual(current_tracks[0]["setVideoId"], "svid1")
        self.assertEqual(existing_title, "Spotify Weekly Global Top 200")
        self.assertEqual(existing_description, "desc")
        youtube.playlists().list.assert_called_once_with(
            mine=True, part="snippet,id", maxResults=50, pageToken=None
        )
        youtube.playlistItems().list.assert_called_once_with(
            playlistId="pl_123", part="snippet,id", maxResults=50, pageToken=None
        )
        youtube.playlists().insert.assert_not_called()

    @patch("playlist_sync.call", side_effect=lambda func, *args, **kwargs: func())
    def test_find_or_create_playlist_new(self, mock_call):
        youtube = MagicMock()
        
        list_playlists_mock = MagicMock()
        list_playlists_mock.execute.return_value = {"items": [], "nextPageToken": None}
        youtube.playlists().list.return_value = list_playlists_mock
        
        insert_playlist_mock = MagicMock()
        insert_playlist_mock.execute.return_value = {"id": "new_pl_456"}
        youtube.playlists().insert.return_value = insert_playlist_mock
        
        playlist_id, current_tracks, existing_title, existing_description = find_or_create_playlist(youtube, "Spotify Weekly Global Top 200", "desc")
        
        self.assertEqual(playlist_id, "new_pl_456")
        self.assertEqual(current_tracks, [])
        self.assertEqual(existing_title, "Spotify Weekly Global Top 200")
        self.assertEqual(existing_description, "desc")
        youtube.playlists().list.assert_called_once()
        youtube.playlists().insert.assert_called_once_with(
            part="snippet,status",
            body={
                "snippet": {
                    "title": "Spotify Weekly Global Top 200",
                    "description": "desc"
                },
                "status": {
                    "privacyStatus": "public"
                }
            }
        )

    @patch("playlist_sync.call")
    def test_find_or_create_playlist_api_error(self, mock_call):
        youtube = MagicMock()
        mock_call.side_effect = RuntimeError("API error")
        
        with self.assertRaises(RuntimeError):
            find_or_create_playlist(youtube, "Spotify Weekly Global Top 200", "desc")

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
        
        resolved, resolved_count, cached_count, failed_count = resolve_track_ids(yt, tracks, cache_by_id, cache_by_name)
        
        self.assertEqual(resolved[0]["ytMusicId"], "yt_light")
        self.assertEqual(resolved[1]["ytMusicId"], "yt_levitate")
        self.assertEqual(resolved_count, 1)
        self.assertEqual(cached_count, 1)
        self.assertEqual(failed_count, 0)
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
        
        resolved, resolved_count, cached_count, failed_count = resolve_track_ids(yt, tracks, {}, {})
        
        self.assertEqual(resolved[0]["ytMusicId"], "yt_dance")
        self.assertEqual(resolved_count, 1)
        self.assertEqual(yt.search.call_count, 2)
        yt.search.assert_any_call("Drake One Dance", filter="songs")
        yt.search.assert_any_call("Drake One Dance", filter="videos")

    def test_resolve_track_ids_missing_video_id_falls_back(self):
        # Songs search matches title+artist but the result has no videoId
        # (edge case bug fix: must still fall back to videos, not give up).
        yt = MagicMock()
        def mock_search(query, filter=None):
            if filter == "songs":
                return [{"title": "One Dance", "artists": [{"name": "Drake"}], "videoId": None}]
            elif filter == "videos":
                return [{"title": "One Dance", "artists": [{"name": "Drake"}], "videoId": "yt_dance"}]
            return []
        yt.search.side_effect = mock_search

        tracks = [{"spotifyId": "sp1", "artist": "Drake", "title": "One Dance"}]
        resolved, resolved_count, cached_count, failed_count = resolve_track_ids(yt, tracks, {}, {})

        self.assertEqual(resolved[0]["ytMusicId"], "yt_dance")
        self.assertEqual(resolved_count, 1)
        self.assertEqual(yt.search.call_count, 2)

    @patch("utils.time.sleep", return_value=None)
    def test_resolve_track_ids_retries_transient_search_failure(self, mock_sleep):
        # First call raises, second call (retry) succeeds.
        yt = MagicMock()
        call_count = {"n": 0}
        def mock_search(query, filter=None):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("transient network blip")
            return [{"title": "Blinding Lights", "artists": [{"name": "The Weeknd"}], "videoId": "yt_light"}]
        yt.search.side_effect = mock_search

        tracks = [{"spotifyId": "sp1", "artist": "The Weeknd", "title": "Blinding Lights"}]
        resolved, resolved_count, cached_count, failed_count = resolve_track_ids(yt, tracks, {}, {})

        self.assertEqual(resolved[0]["ytMusicId"], "yt_light")
        self.assertEqual(resolved_count, 1)
        self.assertEqual(failed_count, 0)
        self.assertEqual(call_count["n"], 2)  # 1 failure + 1 successful retry

    @patch("utils.time.sleep", return_value=None)
    def test_resolve_track_ids_permanent_failure_counted(self, mock_sleep):
        # Both songs and videos search exhaust retries -> failed_count increments,
        # ytMusicId stays unset, no crash.
        yt = MagicMock()
        yt.search.side_effect = ConnectionError("down")

        tracks = [{"spotifyId": "sp1", "artist": "Nobody", "title": "Nothing"}]
        resolved, resolved_count, cached_count, failed_count = resolve_track_ids(yt, tracks, {}, {})

        self.assertNotIn("ytMusicId", resolved[0])
        self.assertEqual(resolved_count, 0)
        self.assertEqual(failed_count, 1)

    @patch("playlist_sync.call", side_effect=lambda func, *args, **kwargs: func())
    @patch("playlist_sync.time.sleep", return_value=None)
    def test_sync_playlist_delta_and_reorder(self, mock_sleep, mock_call):
        youtube = MagicMock()
        
        current_tracks = [
            {"videoId": "old2", "setVideoId": "svid2"},  # index 0
            {"videoId": "old3", "setVideoId": "svid3"},  # index 1
            {"videoId": "old1", "setVideoId": "svid1"}   # index 2
        ]
        
        target_tracks = ["new1", "old3", "new2", "new3", "new4", "new5", "new6", "old2"]
        
        insert_mocks = []
        for new_vid in ["new1", "new2", "new3", "new4", "new5", "new6"]:
            m = MagicMock()
            m.execute.return_value = {"id": f"svid_{new_vid}"}
            insert_mocks.append(m)
            
        youtube.playlistItems().insert.side_effect = lambda part, body: insert_mocks.pop(0)
        
        delete_mock = MagicMock()
        youtube.playlistItems().delete.return_value = delete_mock
        
        update_mock = MagicMock()
        youtube.playlistItems().update.return_value = update_mock
        youtube.playlists().update.return_value = update_mock
        
        sync_playlist(
            youtube,
            playlist_id="pl_123",
            current_tracks=current_tracks,
            new_video_ids=target_tracks,
            target_title="Spotify Weekly Global Top 200",
            target_description="desc",
            existing_title="Spotify Weekly Global Top 200"
        )
        
        youtube.playlistItems().delete.assert_called_once_with(id="svid1")
        self.assertEqual(youtube.playlistItems().insert.call_count, 6)
        
        youtube.playlistItems().update.assert_called_once_with(
            part="snippet",
            body={
                "id": "svid3",
                "snippet": {
                    "playlistId": "pl_123",
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": "old3"
                    },
                    "position": 0
                }
            }
        )
        
        youtube.playlists().update.assert_called_once_with(
            part="snippet",
            body={
                "id": "pl_123",
                "snippet": {
                    "title": "Spotify Weekly Global Top 200",
                    "description": "desc"
                }
            }
        )

    @patch("playlist_sync.call", side_effect=lambda func, *args, **kwargs: func())
    @patch("playlist_sync.time.sleep", return_value=None)
    def test_sync_playlist_pure_reshuffle(self, mock_sleep, mock_call):
        youtube = MagicMock()
        
        current_tracks = [
            {"videoId": "A", "setVideoId": "svidA"},
            {"videoId": "B", "setVideoId": "svidB"},
            {"videoId": "C", "setVideoId": "svidC"},
            {"videoId": "D", "setVideoId": "svidD"},
            {"videoId": "E", "setVideoId": "svidE"},
            {"videoId": "F", "setVideoId": "svidF"},
            {"videoId": "G", "setVideoId": "svidG"},
            {"videoId": "H", "setVideoId": "svidH"}
        ]
        
        # Swap A and H. Shift is 7, which is > 5 threshold.
        target_tracks = ["H", "B", "C", "D", "E", "F", "G", "A"]
        
        update_mock = MagicMock()
        youtube.playlistItems().update.return_value = update_mock
        youtube.playlists().update.return_value = update_mock
        
        sync_playlist(
            youtube,
            playlist_id="pl_123",
            current_tracks=current_tracks,
            new_video_ids=target_tracks,
            target_title="Spotify Weekly Global Top 200",
            target_description="desc",
            existing_title="Spotify Weekly Global Top 200"
        )
        
        # Expect exactly 2 updates (one for H and one for A).
        self.assertEqual(youtube.playlistItems().update.call_count, 2)

    def test_youtube_client_call_quota_error(self):
        from youtube_client import call as youtube_call, QuotaExceededError
        from googleapiclient.errors import HttpError
        import httplib2
        
        resp = httplib2.Response({"status": 403})
        content = b'{"error": {"errors": [{"reason": "quotaExceeded"}], "message": "Quota exceeded"}}'
        http_err = HttpError(resp, content)
        
        def failing_func():
            raise http_err
            
        with self.assertRaises(QuotaExceededError):
            youtube_call(failing_func, attempts=1)

    def test_parse_kworb_html_multiple_artists(self):
        headers = ["Pos", "P+", "Artist and Title", "Wks", "Pk", "(x?)", "Streams"]
        rows = """
        <tr>
            <td>1</td>
            <td>0</td>
            <td><a href="artist/a.html">Artist A</a> & <a href="artist/b.html">Artist B</a> - <a href="track/spotifyid1.html">Title A</a></td>
            <td>10</td><td>1</td><td>x</td><td>1,500,000</td>
        </tr>
        """
        mock_html = make_mock_html(rows, headers)
        parsed = parse_kworb_html(mock_html, "global")
        self.assertEqual(len(parsed["tracks"]), 1)
        track = parsed["tracks"][0]
        self.assertEqual(track["artist"], "Artist A & Artist B")
        self.assertEqual(track["title"], "Title A")
        self.assertEqual(track["spotifyId"], "spotifyid1")

    @patch("playlist_sync.call", side_effect=lambda func, *args, **kwargs: func())
    @patch("playlist_sync.time.sleep", return_value=None)
    def test_sync_playlist_description_no_update(self, mock_sleep, mock_call):
        youtube = MagicMock()
        
        current_tracks = []
        target_tracks = ["new1"]
        
        insert_mock = MagicMock()
        insert_mock.execute.return_value = {"id": "svid_new1"}
        youtube.playlistItems().insert.return_value = insert_mock
        
        sync_playlist(
            youtube,
            playlist_id="pl_123",
            current_tracks=current_tracks,
            new_video_ids=target_tracks,
            target_title="Spotify Weekly Global Top 200",
            target_description="desc",
            existing_title="Spotify Weekly Global Top 200",
            existing_description="desc"  # identical to target_description
        )
        
        # Verify description update is NOT called
        youtube.playlists().update.assert_not_called()

    def test_load_ytmusic_cache_multi_file(self):
        from playlist_sync import load_ytmusic_cache
        with tempfile.TemporaryDirectory() as tmpdir:
            cache1 = {
                "tracks": [
                    {"spotifyId": "sp1", "ytMusicId": "yt1", "artist": "Artist A", "title": "Title A"}
                ]
            }
            cache2 = {
                "tracks": [
                    {"spotifyId": "sp2", "ytMusicId": "yt2", "artist": "Artist B", "title": "Title B"}
                ]
            }
            with open(Path(tmpdir) / "global.json", "w", encoding="utf-8") as f:
                json.dump(cache1, f)
            with open(Path(tmpdir) / "in.json", "w", encoding="utf-8") as f:
                json.dump(cache2, f)
                
            cache_by_id, cache_by_name = load_ytmusic_cache(tmpdir)
            self.assertEqual(cache_by_id.get("sp1"), "yt1")
            self.assertEqual(cache_by_id.get("sp2"), "yt2")
            self.assertEqual(cache_by_name.get("artist a|||title a"), "yt1")
            self.assertEqual(cache_by_name.get("artist b|||title b"), "yt2")

    @patch("playlist_sync.call", side_effect=lambda func, *args, **kwargs: func())
    @patch("playlist_sync.time.sleep", return_value=None)
    def test_sync_playlist_deletes_orphaned(self, mock_sleep, mock_call):
        youtube = MagicMock()
        current_tracks = [
            {"videoId": "vid1", "setVideoId": "svid1"},
            {"videoId": None, "setVideoId": "svid2"}
        ]
        new_video_ids = ["vid1"]
        
        delete_mock = MagicMock()
        youtube.playlistItems().delete.return_value = delete_mock
        youtube.playlists().update.return_value = MagicMock()
        
        sync_playlist(
            youtube,
            playlist_id="pl_123",
            current_tracks=current_tracks,
            new_video_ids=new_video_ids,
            target_title="Spotify Weekly Global Top 200",
            target_description="desc",
            existing_title="Spotify Weekly Global Top 200",
            existing_description="desc"
        )
        
        youtube.playlistItems().delete.assert_called_once_with(id="svid2")

    @patch("sync.parse_args")
    @patch("sync.scrape_kworb")
    @patch("sync.should_skip_sync", return_value=False)
    @patch("sync.YTMusic")
    @patch("youtube_client.get_youtube_client")
    @patch("sync.load_ytmusic_cache", return_value=({}, {}))
    @patch("sync.resolve_track_ids")
    @patch("sync.find_or_create_playlist")
    @patch("sync.sync_playlist")
    @patch("builtins.open", new_callable=unittest.mock.mock_open)
    @patch("sync.Path")
    @patch("json.dump")
    def test_main_sync_skips_on_partial_failure(
        self, mock_json_dump, mock_path, mock_open, mock_sync_playlist, mock_find_create,
        mock_resolve, mock_load_cache, mock_yt_client, mock_ytmusic, mock_should_skip,
        mock_scrape, mock_parse_args
    ):
        from sync import main as sync_main
        
        args = MagicMock()
        args.country = "global"
        args.data_dir = "data"
        args.auth = None
        args.dry_run = False
        args.force = False
        args.min_resolve_ratio = 0.90
        mock_parse_args.return_value = args
        
        mock_scrape.return_value = {
            "country": "global",
            "countryName": "Global",
            "weekDate": "2026-07-01",
            "tracks": [{"spotifyId": f"sp{i}"} for i in range(10)]
        }
        
        mock_resolve.return_value = (
            [{"spotifyId": f"sp{i}", "ytMusicId": f"yt{i}"} for i in range(8)] + [{"spotifyId": "sp8"}, {"spotifyId": "sp9"}],
            5, 3, 2
        )
        
        sync_main()
        
        mock_find_create.assert_not_called()
        mock_sync_playlist.assert_not_called()
        
        called_data = mock_json_dump.call_args[0][0]
        self.assertEqual(called_data["weekDate"], "2026-07-01-partial")

if __name__ == "__main__":
    unittest.main()