import re
from datetime import datetime, timezone
import requests
from bs4 import BeautifulSoup

from utils import COUNTRIES, BASE_URL, retry_operation, parse_num

def extract_week_date(soup):
    sources = []
    pagetitle_span = soup.find("span", class_="pagetitle")
    if pagetitle_span:
        sources.append(pagetitle_span.get_text())
    if soup.title:
        sources.append(soup.title.get_text())
    
    for s in sources:
        m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", s)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        m2 = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", s)
        if m2:
            try:
                date_str = f"{m2.group(1)} {m2.group(2)} {m2.group(3)}".replace(",", "")
                for fmt in ("%B %d %Y", "%b %d %Y"):
                    try:
                        return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
            except Exception:
                pass
    raise ValueError("Failed to parse week date from Kworb page structure. Page layout might have changed.")

def fetch_kworb_html(country_code):
    country_config = COUNTRIES[country_code]
    url = f"{BASE_URL}/{country_config['slug']}.html"
    print(f"⏳ Scraping Kworb Weekly Chart: {url} ...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; MusicChartsDash/1.0)"}
    
    def fetch_url():
        res = requests.get(url, headers=headers, timeout=15)
        res.raise_for_status()
        res.encoding = "utf-8"
        return res.text

    html_content = retry_operation(
        fetch_url,
        attempts=3,
        delay=2,
        linear_backoff=True,
        fatal=True,
        error_msg=f"Failed to fetch {url}"
    )
    return html_content

def parse_kworb_html(html_content, country_code):
    country_config = COUNTRIES[country_code]
    soup = BeautifulSoup(html_content, "html.parser")
    table = soup.find("table")
    if not table:
        raise ValueError(f"No table found in HTML for {country_code}")
        
    rows = table.find_all("tr")
    if not rows:
        raise ValueError("Table has no rows")
        
    header_row = rows[0]
    headers_list = [th.get_text(strip=True) for th in header_row.find_all(["th", "td"])]
    
    col_pos = -1
    col_change = -1
    col_track = -1
    col_weeks = -1
    col_peak = -1
    col_streams = -1
    
    for idx, h in enumerate(headers_list):
        h_lower = h.lower()
        if ("pos" in h_lower or h_lower == "#") and col_pos == -1:
            col_pos = idx
        elif ("p+" in h_lower or "+/-" in h_lower or "change" in h_lower) and col_change == -1:
            col_change = idx
        elif ("artist" in h_lower or "title" in h_lower or "track" in h_lower) and col_track == -1:
            col_track = idx
        elif ("days" in h_lower or "wks" in h_lower or "weeks" in h_lower) and col_weeks == -1:
            col_weeks = idx
        elif ("pk" in h_lower or "peak" in h_lower) and col_peak == -1:
            col_peak = idx
        elif h_lower == "streams" and col_streams == -1:
            col_streams = idx
            
    # Fallback to defaults if headers match fails
    fallbacks_used = []
    if col_pos == -1:
        col_pos = 0
        fallbacks_used.append("Pos (0)")
    if col_change == -1:
        col_change = 1
        fallbacks_used.append("Change (1)")
    if col_track == -1:
        col_track = 2
        fallbacks_used.append("Track (2)")
    if col_weeks == -1:
        col_weeks = 3
        fallbacks_used.append("Weeks (3)")
    if col_peak == -1:
        col_peak = 4
        fallbacks_used.append("Peak (4)")
    if col_streams == -1:
        col_streams = 6
        fallbacks_used.append("Streams (6)")
        
    if fallbacks_used:
        print(f"⚠️ Warning: Header detection failed for columns: {', '.join(fallbacks_used)}. Using fallback indices.")
    
    week_date = extract_week_date(soup)
    tracks = []
    
    required_cols = max(col_pos, col_change, col_track, col_weeks, col_peak, col_streams) + 1
    for r_idx in range(1, len(rows)):
        if len(tracks) >= 200:
            break
            
        cells = rows[r_idx].find_all("td")
        if len(cells) < required_cols:
            print(f"⚠️ Warning: Skipping row {r_idx} because it has only {len(cells)} columns (expected {required_cols})")
            continue
            
        try:
            rank = int(cells[col_pos].get_text(strip=True))
        except ValueError:
            print(f"⚠️ Warning: Skipping row {r_idx} due to invalid rank format: '{cells[col_pos].get_text(strip=True)}'")
            continue
            
        change = cells[col_change].get_text(strip=True)
        if not change or change in ("0", "--", "—", "="):
            change = "0"
            
        track_cell = cells[col_track]
        a_tags = track_cell.find_all("a")
        artist = ""
        title = ""
        spotify_id = ""
        
        # Note: Featured/collaborator artists (e.g. "(w/ Ejae...)") are intentionally omitted
        # from the scraped artist field as YTM search handles primary artist + title best.
        track_text = track_cell.get_text(" ", strip=True)
        if " - " in track_text:
            artist, title = track_text.split(" - ", 1)
            artist = artist.strip()
            title = title.strip()
        else:
            artist = ""
            title = track_text.strip()

        # Find the Spotify track link specifically by scanning href for "track/"
        href = ""
        for a in a_tags:
            a_href = a.get("href", "")
            if "track/" in a_href:
                href = a_href
                title = a.get_text(strip=True)
                break

        if href:
            match = re.search(r"track/([a-zA-Z0-9]+)\.html", href)
            if match:
                spotify_id = match.group(1)
                
        streams = parse_num(cells[col_streams].get_text(strip=True))
        peak = parse_num(cells[col_peak].get_text(strip=True))
        weeks = parse_num(cells[col_weeks].get_text(strip=True))
        
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
        
    if len(tracks) == 0:
        raise ValueError("Scraped 0 tracks from Kworb page. This indicates a parser structure or column layout change.")
    elif len(tracks) < 100:
        print(f"⚠️ Warning: Scraped only {len(tracks)} tracks (expected ~200). Some rows might have failed to parse.")
        
    return {
        "country": country_code,
        "countryName": country_config["name"],
        "weekDate": week_date,
        "lastUpdated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tracks": tracks
    }

def scrape_kworb(country_code):
    html_content = fetch_kworb_html(country_code)
    return parse_kworb_html(html_content, country_code)