import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
import tempfile
import json
import sys

# Import functions from sync.py
from sync import (
    clean_string,
    verify_match,
    retry_operation,
    should_skip_sync,
    parse_kworb_html,
    parse_num
)

class TestSyncBot(unittest.TestCase):

    def test_clean_string(self):
        self.assertEqual(clean_string("Hello, World!"), "hello world")
        self.assertEqual(clean_string("  Artist - Title (Remix)  "), "artist title remix")
        self.assertEqual(clean_string(""), "")
        self.assertEqual(clean_string(None), "")

    def test_verify_match(self):
        # Case 1: Perfect match
        res_ok = {
            "title": "Blinding Lights",
            "artists": [{"name": "The Weeknd"}]
        }
        self.assertTrue(verify_match("The Weeknd", "Blinding Lights", res_ok))

        # Case 2: Substring matching in collaborations
        res_collab = {
            "title": "Peaches",
            "artists": [{"name": "Justin Bieber"}, {"name": "Daniel Caesar"}, {"name": "Giveon"}]
        }
        self.assertTrue(verify_match("Justin Bieber", "Peaches", res_collab))
        self.assertTrue(verify_match("Daniel Caesar", "peaches", res_collab))

        # Case 3: Minor typos / punctuation
        res_typo = {
            "title": "Rockstar",
            "artists": [{"name": "Post Malone feat. 21 Savage"}]
        }
        self.assertTrue(verify_match("Post Malone", "Rockstar!", res_typo))

        # Case 4: Mismatched title (ratio too low)
        res_different_title = {
            "title": "Starboy",
            "artists": [{"name": "The Weeknd"}]
        }
        self.assertFalse(verify_match("The Weeknd", "Blinding Lights", res_different_title))

        # Case 5: Mismatched artist
        res_wrong_artist = {
            "title": "Blinding Lights",
            "artists": [{"name": "Different Artist"}]
        }
        self.assertFalse(verify_match("The Weeknd", "Blinding Lights", res_wrong_artist))

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
        with self.assertRaises(SystemExit):
            parse_kworb_html(mock_html_empty, "global")

if __name__ == "__main__":
    unittest.main()
