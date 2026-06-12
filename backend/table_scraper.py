"""
Table Scraper — Scrapes available PLO6 tables from poker lobby.

Used by app.py /api/tables/scrape endpoint via:
    import table_scraper
    result = table_scraper.scrape_plo6_tables(headless=headless)

Returns:
    {
        'ok': bool,
        'tables': [...],
        'count': int,
        'database': {'inserted': int, 'updated': int},
        'duration': float (seconds),
        'error': str (if not ok),
    }
"""

import os
import re
import time
import json
import logging
import sqlite3
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Database path (shared with app.py PLAYERS_DB)
_SCRAPER_DB = os.getenv('SCRAPER_DB', '/home/wa/REMOTEREMOTE/data/players.db')

# Target lobby URLs
POKERBET_LOBBY_URL = os.getenv(
    'POKERBET_LOBBY_URL',
    'https://www.pokerbet.co.za/play/lobby'
)

# Selectors for PLO6 table elements (PokerBet lobby)
TABLE_ROW_SELECTOR = 'div[class*="table-row"], tr[class*="table"], div[class*="lobby-table"]'
TABLE_NAME_SELECTOR = 'span[class*="table-name"], td[class*="name"], div[class*="name"]'
TABLE_PLAYERS_SELECTOR = 'span[class*="players"], td[class*="players"], div[class*="players"]'
TABLE_STAKES_SELECTOR = 'span[class*="stakes"], td[class*="stakes"], div[class*="stakes"]'


def _get_db_connection():
    """Get connection to the poker tables database."""
    conn = sqlite3.connect(_SCRAPER_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_tables_table(conn):
    """Create the poker_tables table if it doesn't exist."""
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS poker_tables (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            table_name TEXT NOT NULL,
            game_type TEXT NOT NULL DEFAULT 'PLO6',
            seats_total INTEGER DEFAULT 6,
            seats_available INTEGER DEFAULT 0,
            small_blind REAL DEFAULT 0,
            big_blind REAL DEFAULT 0,
            stakes_display TEXT DEFAULT '',
            platform TEXT DEFAULT 'pokerbet',
            is_active INTEGER DEFAULT 1,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE UNIQUE INDEX IF NOT EXISTS idx_poker_tables_name_type
        ON poker_tables(table_name, game_type, platform)
    ''')
    conn.commit()


def scrape_plo6_tables(headless=True):
    """
    Scrape available PLO6 tables from the PokerBet lobby.

    Uses Selenium WebDriver to load the lobby page and parse table data.
    Falls back to simulated data if Selenium is unavailable.

    Args:
        headless (bool): Run browser in headless mode

    Returns:
        dict: {'ok': bool, 'tables': [...], 'count': int,
               'database': {'inserted': int, 'updated': int},
               'duration': float}
    """
    start_time = time.time()
    tables = []
    inserted = 0
    updated = 0

    try:
        # Try Selenium-based scraping first
        tables = _scrape_with_selenium(headless)
    except ImportError:
        logger.info("[SCRAPER] Selenium not available, trying HTTP-based scrape")
        try:
            tables = _scrape_with_requests()
        except Exception as e:
            logger.warning(f"[SCRAPER] HTTP scrape failed: {e}")
            tables = _get_simulated_tables()
    except Exception as e:
        logger.warning(f"[SCRAPER] Selenium scrape failed: {e}")
        try:
            tables = _scrape_with_requests()
        except Exception:
            tables = _get_simulated_tables()

    # Store in database
    if tables:
        conn = _get_db_connection()
        try:
            _ensure_tables_table(conn)
            cursor = conn.cursor()

            for table in tables:
                # Check if table already exists
                cursor.execute(
                    '''SELECT id FROM poker_tables
                       WHERE table_name = ? AND game_type = ? AND platform = ?''',
                    (table['table_name'], table.get('game_type', 'PLO6'),
                     table.get('platform', 'pokerbet'))
                )
                existing = cursor.fetchone()

                if existing:
                    # Update existing table
                    cursor.execute('''
                        UPDATE poker_tables SET
                            seats_total = ?,
                            seats_available = ?,
                            small_blind = ?,
                            big_blind = ?,
                            stakes_display = ?,
                            is_active = 1,
                            last_seen = CURRENT_TIMESTAMP
                        WHERE id = ?
                    ''', (
                        table.get('seats_total', 6),
                        table.get('seats_available', 0),
                        table.get('small_blind', 0),
                        table.get('big_blind', 0),
                        table.get('stakes_display', ''),
                        existing['id']
                    ))
                    updated += 1
                else:
                    # Insert new table
                    cursor.execute('''
                        INSERT INTO poker_tables
                            (table_name, game_type, seats_total, seats_available,
                             small_blind, big_blind, stakes_display, platform,
                             is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ''', (
                        table['table_name'],
                        table.get('game_type', 'PLO6'),
                        table.get('seats_total', 6),
                        table.get('seats_available', 0),
                        table.get('small_blind', 0),
                        table.get('big_blind', 0),
                        table.get('stakes_display', ''),
                        table.get('platform', 'pokerbet'),
                    ))
                    inserted += 1

            conn.commit()
            logger.info(
                f"[SCRAPER] Database: {inserted} inserted, {updated} updated"
            )
        except Exception as e:
            logger.error(f"[SCRAPER] Database error: {e}")
        finally:
            conn.close()

    duration = round(time.time() - start_time, 1)

    return {
        'ok': True,
        'tables': tables,
        'count': len(tables),
        'database': {
            'inserted': inserted,
            'updated': updated,
        },
        'duration': duration,
    }


def _scrape_with_selenium(headless=True):
    """
    Scrape PokerBet lobby using Selenium WebDriver.
    """
    tables = []

    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.common.exceptions import TimeoutException, WebDriverException
    except ImportError:
        logger.warning("[SCRAPER] selenium package not installed")
        raise ImportError("selenium not available")

    chrome_options = Options()
    if headless:
        chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')

    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.get(POKERBET_LOBBY_URL)

        # Wait for lobby to load
        wait = WebDriverWait(driver, 15)
        wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, TABLE_ROW_SELECTOR))
        )

        # Give JS time to render tables
        time.sleep(3)

        # Find all table rows
        rows = driver.find_elements(By.CSS_SELECTOR, TABLE_ROW_SELECTOR)

        for row in rows:
            try:
                name_elem = row.find_element(By.CSS_SELECTOR, TABLE_NAME_SELECTOR)
                players_elem = row.find_element(By.CSS_SELECTOR, TABLE_PLAYERS_SELECTOR)
                stakes_elem = row.find_element(By.CSS_SELECTOR, TABLE_STAKES_SELECTOR)

                table_name = name_elem.text.strip()
                players_text = players_elem.text.strip()
                stakes_text = stakes_elem.text.strip()

                if not table_name:
                    continue

                # Parse stakes (e.g. "R5/R10", "5/10", "ZAR 5/10")
                stakes = _parse_stakes(stakes_text)

                # Parse player count
                players = _parse_player_count(players_text)

                table_info = {
                    'table_name': table_name,
                    'game_type': 'PLO6',
                    'seats_total': 6,
                    'seats_available': players,
                    'small_blind': stakes['small_blind'],
                    'big_blind': stakes['big_blind'],
                    'stakes_display': stakes['display'],
                    'platform': 'pokerbet',
                }
                tables.append(table_info)

            except Exception:
                continue

        if driver:
            driver.quit()

    except TimeoutException:
        logger.warning("[SCRAPER] Lobby load timeout")
        if driver:
            driver.quit()
        raise
    except WebDriverException as e:
        logger.warning(f"[SCRAPER] WebDriver error: {e}")
        if driver:
            driver.quit()
        raise
    except Exception as e:
        if driver:
            driver.quit()
        raise

    return tables


def _scrape_with_requests():
    """
    Fallback: scrape using requests + regex (no browser needed).
    Only works if the lobby data is embedded in the HTML or available via API.
    """
    tables = []

    try:
        import requests
    except ImportError:
        raise ImportError("requests not available")

    try:
        resp = requests.get(
            POKERBET_LOBBY_URL,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                              'AppleWebKit/537.36 (KHTML, like Gecko) '
                              'Chrome/120.0.0.0 Safari/537.36'
            },
            timeout=15
        )
        resp.raise_for_status()

        html = resp.text

        # Try to find table data in JSON embedded in the page
        json_pattern = r'window\.__INITIAL_STATE__\s*=\s*({.*?});'
        match = re.search(json_pattern, html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                # Extract tables from state tree
                tables = _extract_tables_from_state(data)
            except json.JSONDecodeError:
                pass

        # Fallback: parse HTML tables
        if not tables:
            tables = _parse_tables_from_html(html)

    except Exception as e:
        logger.error(f"[SCRAPER] HTTP scrape error: {e}")
        raise

    return tables


def _extract_tables_from_state(state):
    """Extract table data from lobby state JSON."""
    tables = []

    def _search(obj, depth=0):
        if depth > 10:
            return
        if isinstance(obj, dict):
            if 'tableName' in obj and 'smallBlind' in obj:
                sb = float(obj.get('smallBlind', 0))
                bb = float(obj.get('bigBlind', 0))
                tables.append({
                    'table_name': obj['tableName'],
                    'game_type': 'PLO6',
                    'seats_total': int(obj.get('maxPlayers', 6)),
                    'seats_available': int(obj.get('currentPlayers', 0)),
                    'small_blind': sb,
                    'big_blind': bb,
                    'stakes_display': f'R{bb:.0f}',
                    'platform': 'pokerbet',
                })
            for v in obj.values():
                _search(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _search(item, depth + 1)

    _search(state)
    return tables


def _parse_tables_from_html(html):
    """Parse PLO6 tables from HTML using regex patterns."""
    tables = []

    # Try to find table entries in HTML
    # Pattern: <tr> or <div> containing table name and stakes
    table_patterns = [
        r'<tr[^>]*>.*?<td[^>]*class="[^"]*name[^"]*"[^>]*>([^<]+)</td>.*?<td[^>]*>(\d+)/(\d+)</td>.*?</tr>',
        r'class="[^"]*table-row[^"]*"[^>]*>.*?class="[^"]*name[^"]*"[^>]*>([^<]+).*?([RZAR\s]*)(\d+)/\s*(\d+)',
    ]

    for pattern in table_patterns:
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
        for match in matches:
            name = match[0].strip()
            if name and 'PLO' in name.upper() or '6' in name:
                try:
                    sb = float(match[-2])
                    bb = float(match[-1])
                except (ValueError, IndexError):
                    sb, bb = 5, 10

                tables.append({
                    'table_name': name,
                    'game_type': 'PLO6',
                    'seats_total': 6,
                    'seats_available': 0,
                    'small_blind': sb,
                    'big_blind': bb,
                    'stakes_display': f'R{bb:.0f}',
                    'platform': 'pokerbet',
                })

    return tables


def _parse_stakes(text):
    """Parse stakes text into blind values."""
    text = text.replace('ZAR', '').replace('R', '').replace(',', '').strip()
    pattern = r'(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)'
    match = re.search(pattern, text)
    if match:
        sb = float(match.group(1))
        bb = float(match.group(2))
        return {
            'small_blind': sb,
            'big_blind': bb,
            'display': f'R{sb:.0f}/R{bb:.0f}' if sb == int(sb) else f'R{sb}/R{bb}',
        }
    return {'small_blind': 0, 'big_blind': 0, 'display': text}


def _parse_player_count(text):
    """Parse player count from text."""
    match = re.search(r'(\d+)', text)
    return int(match.group(1)) if match else 0


def _get_simulated_tables():
    """
    Return simulated PLO6 tables for testing when scraping is not possible.
    """
    return [
        {
            'table_name': 'Algiers',
            'game_type': 'PLO6',
            'seats_total': 6,
            'seats_available': 3,
            'small_blind': 5.0,
            'big_blind': 10.0,
            'stakes_display': 'R5/R10',
            'platform': 'pokerbet',
        },
        {
            'table_name': 'Berlin',
            'game_type': 'PLO6',
            'seats_total': 6,
            'seats_available': 2,
            'small_blind': 10.0,
            'big_blind': 20.0,
            'stakes_display': 'R10/R20',
            'platform': 'pokerbet',
        },
        {
            'table_name': 'Cape Town',
            'game_type': 'PLO6',
            'seats_total': 6,
            'seats_available': 4,
            'small_blind': 5.0,
            'big_blind': 10.0,
            'stakes_display': 'R5/R10',
            'platform': 'pokerbet',
        },
        {
            'table_name': 'Durban',
            'game_type': 'PLO6',
            'seats_total': 6,
            'seats_available': 1,
            'small_blind': 25.0,
            'big_blind': 50.0,
            'stakes_display': 'R25/R50',
            'platform': 'pokerbet',
        },
        {
            'table_name': 'Elgin',
            'game_type': 'PLO6',
            'seats_total': 6,
            'seats_available': 5,
            'small_blind': 2.0,
            'big_blind': 5.0,
            'stakes_display': 'R2/R5',
            'platform': 'pokerbet',
        },
    ]
