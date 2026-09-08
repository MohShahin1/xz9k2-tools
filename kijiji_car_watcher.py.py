"""
Kijiji Car Listing Watcher
---------------------------
Checks a Kijiji search-results page (with YOUR filters already applied in the URL)
for new car listings and sends a Telegram message for each new one found.

SETUP
=====
1. Install dependencies:
       pip install requests beautifulsoup4

2. Get your filtered search URL:
   - Go to kijiji.ca, search for cars, set your make/model/price/location/etc filters
     in the normal Kijiji UI, and copy the resulting URL from your browser's
     address bar. Paste it into SEARCH_URL below.

3. Create a Telegram bot:
   - Message @BotFather on Telegram, send /newbot, follow the prompts.
   - It will give you a bot token like: 123456789:AAExampleTokenHere
   - Paste it into TELEGRAM_BOT_TOKEN below.

4. Get your chat ID:
   - Message your new bot anything (e.g. "hi") so it has a conversation with you.
   - Then visit this URL in your browser (replace <TOKEN>):
       https://api.telegram.org/bot<TOKEN>/getUpdates
   - Look for "chat":{"id": 123456789 ...} in the response. That number is your
     TELEGRAM_CHAT_ID below.

5. Fill in the CONFIG section below and run:
       python kijiji_car_watcher.py

   The first run just records all current listings as "already seen" (no spam).
   Every run after that will notify you only about NEW listings.

6. Schedule it to run automatically (see scheduling notes at the bottom of this file).
"""

import json
import os
import sys
import time
import random
from datetime import datetime

import requests
from bs4 import BeautifulSoup

# ============================== CONFIG ==================================

# These read from environment variables first (used when running on GitHub
# Actions, where you'll set them as encrypted Secrets), and fall back to the
# placeholder strings below (used only if you're running this locally on
# your own PC — in that case just paste your real values in place of the
# PASTE_YOUR_... placeholders).

SEARCH_URL = os.environ.get("KIJIJI_SEARCH_URL") or "https://www.kijiji.ca/b-cars-trucks/canada/PASTE-YOUR-FILTERED-SEARCH-URL-HERE"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or "PASTE_YOUR_BOT_TOKEN_HERE"
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID") or "PASTE_YOUR_CHAT_ID_HERE"

# Where "already seen" listing IDs are stored between runs, so you don't get
# repeat notifications. Keep this next to the script.
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "kijiji_seen.json")

# A realistic User-Agent reduces the chance of being blocked. Update
# periodically if needed.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}

# ==========================================================================


def load_seen_ids():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_ids(seen_ids):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen_ids), f, indent=2)


def fetch_listings():
    """
    Scrapes the search results page and returns a list of dicts:
    {id, title, price, url, location}

    NOTE: Kijiji's HTML structure changes over time. If this stops finding
    listings, open the search page in a browser, use "Inspect Element" on a
    listing card, and update the selectors below to match the current markup.
    """
    resp = requests.get(SEARCH_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    listings = []

    # Kijiji listing cards are typically <a> or <div> elements whose href
    # contains "/v-" (Kijiji's ad URL pattern). This is a fairly durable
    # pattern even when class names change.
    seen_hrefs = set()
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if "/v-" not in href:
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)

        full_url = href if href.startswith("http") else f"https://www.kijiji.ca{href}"

        # Try to pull a listing ID out of the URL (Kijiji URLs end in /NNNNNNN)
        listing_id = full_url.rstrip("/").split("/")[-1]
        if not listing_id.isdigit():
            continue

        title = a_tag.get_text(strip=True)
        if not title or len(title) < 3:
            # Some matched <a> tags are just images/icons with no useful text;
            # try to find a nearby heading instead.
            parent = a_tag.find_parent()
            heading = parent.find(["h2", "h3"]) if parent else None
            title = heading.get_text(strip=True) if heading else None
        if not title:
            continue

        listings.append({
            "id": listing_id,
            "title": title,
            "url": full_url,
        })

    return listings


def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": False,
    }, timeout=20)
    if not resp.ok:
        print(f"[!] Telegram send failed: {resp.status_code} {resp.text}")


def main():
    print(f"[{datetime.now().isoformat()}] Checking Kijiji for new listings...")

    if "PASTE-YOUR" in SEARCH_URL or "PASTE_YOUR" in TELEGRAM_BOT_TOKEN or "PASTE_YOUR" in TELEGRAM_CHAT_ID:
        print("[!] Please fill in SEARCH_URL, TELEGRAM_BOT_TOKEN, and TELEGRAM_CHAT_ID at the top of this file.")
        sys.exit(1)

    try:
        listings = fetch_listings()
    except requests.RequestException as e:
        print(f"[!] Failed to fetch Kijiji page: {e}")
        sys.exit(1)

    if not listings:
        print("[!] No listings found. Kijiji's page structure may have changed, "
              "or the search URL may be wrong. See the note in fetch_listings().")
        return

    seen_ids = load_seen_ids()
    is_first_run = len(seen_ids) == 0

    new_listings = [l for l in listings if l["id"] not in seen_ids]

    if is_first_run:
        print(f"[i] First run: recording {len(listings)} existing listings, no notifications sent.")
    else:
        print(f"[i] Found {len(new_listings)} new listing(s) out of {len(listings)} total.")
        for listing in new_listings:
            message = f"🚗 New Kijiji listing!\n\n{listing['title']}\n{listing['url']}"
            send_telegram_message(message)
            time.sleep(1)  # be gentle with Telegram's API

    seen_ids.update(l["id"] for l in listings)
    save_seen_ids(seen_ids)
    print(f"[{datetime.now().isoformat()}] Done.")


if __name__ == "__main__":
    main()

# ==========================================================================
# SCHEDULING NOTES
# ==========================================================================
#
# WINDOWS (Task Scheduler):
#   1. Open Task Scheduler -> Create Basic Task.
#   2. Trigger: e.g. "Daily", then set repeat every 15-30 minutes for the
#      whole day (advanced trigger settings).
#   3. Action: "Start a program"
#        Program: C:\path\to\python.exe
#        Arguments: C:\path\to\kijiji_car_watcher.py
#
# MAC / LINUX (cron):
#   Run `crontab -e` and add a line to check every 15 minutes:
#       */15 * * * * /usr/bin/python3 /path/to/kijiji_car_watcher.py >> /path/to/kijiji_log.txt 2>&1
#
# TIP: Don't check more often than every 10-15 minutes. Checking too
# frequently increases the chance Kijiji temporarily blocks your IP.
