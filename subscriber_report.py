"""
Monthstayz Thailand - Weekly Subscriber Report Bot
---------------------------------------------------
Pulls current subscriber/follower counts from each connected platform,
compares against last week's numbers (stored in state.json), and posts
a formatted report to a Telegram group.

Every platform function returns an int (current count) or None if that
platform isn't configured yet. Platforms with no credentials are simply
skipped in the report - so you can turn platforms on one at a time as
you get API access, without breaking anything.

Facebook and Instagram support two modes:
  1. Official Graph API (reliable, needs a one-time token setup) - used
     automatically if FACEBOOK_PAGE_ACCESS_TOKEN / INSTAGRAM_ACCESS_TOKEN
     are set.
  2. Public-page scraping fallback (zero setup, but fragile - see notes
     in scrape_public_page_metric() below) - used automatically if no
     token is set but a page URL/username is.

Run manually with:  python subscriber_report.py
Run weekly via the GitHub Actions workflow in .github/workflows/
"""

import json
import os
import re
import sys
from pathlib import Path

import requests

# Pretend to be a normal browser - reduces (but does not eliminate) the
# chance of being served a login wall instead of the public page.
SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

STATE_FILE = Path(__file__).parent / "state.json"

# Order matters here - this is the order platforms will appear in the report,
# matching your existing weekly report layout.
PLATFORM_ORDER = [
    "facebook",
    "instagram",
    "tiktok",
    "youtube",
    "telegram",
    "x",
    "kit",
    "whatchimp",
]

PLATFORM_LABELS = {
    "facebook": "Facebook",
    "instagram": "Instagram",
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "telegram": "Telegram",
    "x": "X",
    "kit": "Kit",
    "whatchimp": "Whatchimp",
}


# ---------------------------------------------------------------------------
# Platform fetchers
# Each one reads its own credentials from environment variables (which, in
# production, come from GitHub Actions Secrets - never hardcode keys here).
# ---------------------------------------------------------------------------

def get_youtube_subscribers():
    api_key = os.environ.get("YOUTUBE_API_KEY")
    channel_id = os.environ.get("YOUTUBE_CHANNEL_ID")
    if not api_key or not channel_id:
        return None
    resp = requests.get(
        "https://www.googleapis.com/youtube/v3/channels",
        params={"part": "statistics", "id": channel_id, "key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    return int(items[0]["statistics"]["subscriberCount"])


def get_kit_subscribers():
    api_key = os.environ.get("KIT_API_KEY")
    if not api_key:
        return None
    resp = requests.get(
        "https://api.kit.com/v4/subscribers",
        headers={"X-Kit-Api-Key": api_key},
        params={"status": "active", "include_total_count": "true", "per_page": 1},
        timeout=15,
    )
    resp.raise_for_status()
    return int(resp.json()["pagination"]["total_count"])


def get_telegram_member_count():
    """Member count of the group the bot itself is a member of (not the group
    it posts the report to, unless they're the same chat)."""
    bot_token = os.environ.get("TELEGRAM_SOURCE_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_SOURCE_CHAT_ID")
    if not bot_token or not chat_id:
        return None
    resp = requests.get(
        f"https://api.telegram.org/bot{bot_token}/getChatMemberCount",
        params={"chat_id": chat_id},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        return None
    return int(data["result"])


def get_facebook_page_followers():
    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
    if page_id and token:
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{page_id}",
            params={"fields": "followers_count", "access_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        return int(resp.json()["followers_count"])

    # Fallback: scrape the public page. No token needed, but see the
    # reliability notes on scrape_public_page_metric().
    page_url = os.environ.get("FACEBOOK_PAGE_URL")
    if page_url:
        return scrape_public_page_metric(page_url, ["followers", "people follow this", "likes"])

    return None


def get_instagram_followers():
    ig_user_id = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID")
    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN") or os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
    if ig_user_id and token:
        resp = requests.get(
            f"https://graph.facebook.com/v19.0/{ig_user_id}",
            params={"fields": "followers_count", "access_token": token},
            timeout=15,
        )
        resp.raise_for_status()
        return int(resp.json()["followers_count"])

    # Fallback: scrape the public profile. No token needed, but see the
    # reliability notes on scrape_public_page_metric().
    username = os.environ.get("INSTAGRAM_USERNAME")
    if username:
        return scrape_public_page_metric(f"https://www.instagram.com/{username}/", ["followers"])

    return None


def _parse_count_with_suffix(number_str):
    """Turns '1.2K' / '3,400' / '331' into an int."""
    number_str = number_str.strip().upper().replace(",", "")
    multiplier = 1
    if number_str.endswith("K"):
        multiplier, number_str = 1_000, number_str[:-1]
    elif number_str.endswith("M"):
        multiplier, number_str = 1_000_000, number_str[:-1]
    elif number_str.endswith("B"):
        multiplier, number_str = 1_000_000_000, number_str[:-1]
    return int(float(number_str) * multiplier)


def scrape_public_page_metric(url, keywords):
    """
    Best-effort scraper for a public Facebook/Instagram page's follower
    (or like) count, with NO login and NO official API.

    How it works: Meta still renders an og:description meta tag in the raw
    HTML of most public pages/profiles (this is what search engines use to
    show snippets like "331 Followers, 333 Following, 116 Posts"), and this
    function regex-matches a number next to one of the given keywords in it.

    IMPORTANT LIMITATIONS - read before relying on this:
    - Facebook/Instagram's Terms of Service prohibit automated scraping,
      even of public data. This is a deliberate trade-off you've chosen to
      accept in exchange for skipping the official API setup.
    - Meta can serve a login wall instead of the real page to automated
      requests at any time, with no warning - if that happens, this
      function returns None (gracefully skipped in the report) rather
      than crashing, but you also won't get a number that day.
    - Page HTML structure can change without notice, silently breaking
      the regex below. If Facebook/Instagram rows start showing
      "-- not configured --" for weeks in a row, this is the first place
      to check - the pattern below may need updating.
    - The IP addresses GitHub Actions runners use are shared with many
      other projects and are more likely to get rate-limited/blocked than
      a residential IP would be.
    """
    try:
        resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=15)
        resp.raise_for_status()
        html = resp.text

        og_match = re.search(r'<meta property="og:description" content="([^"]+)"', html)
        search_space = og_match.group(1) if og_match else html

        keyword_pattern = "|".join(keywords)
        match = re.search(
            r"([\d][\d,\.]*\s?[KMB]?)\s*(?:" + keyword_pattern + ")",
            search_space,
            re.IGNORECASE,
        )
        if not match:
            print(f"Scrape of {url}: couldn't find a follower count in the page (login wall or layout change?)", file=sys.stderr)
            return None
        return _parse_count_with_suffix(match.group(1))
    except Exception as e:
        print(f"Scrape of {url} failed: {e}", file=sys.stderr)
        return None


def get_x_followers():
    """Uses X API v2 'owned reads' (your own authenticated account), which is
    billed at the cheapest tier ($0.001/read as of mid-2026 pricing)."""
    bearer_token = os.environ.get("X_BEARER_TOKEN")
    user_id = os.environ.get("X_USER_ID")
    if not bearer_token or not user_id:
        return None
    resp = requests.get(
        f"https://api.twitter.com/2/users/{user_id}",
        headers={"Authorization": f"Bearer {bearer_token}"},
        params={"user.fields": "public_metrics"},
        timeout=15,
    )
    resp.raise_for_status()
    return int(resp.json()["data"]["public_metrics"]["followers_count"])


def get_tiktok_followers():
    """NOT AVAILABLE via TikTok's public Display API - follower_count is not
    a field it exposes for standard apps (only via TikTok Business API with
    a business partnership, or the Research API for approved academic/
    nonprofit use). Leaving this as a manual entry point: set TIKTOK_MANUAL_COUNT
    as an env var/secret and update it by hand until you have Business API access."""
    manual = os.environ.get("TIKTOK_MANUAL_COUNT")
    return int(manual) if manual else None


def get_whatchimp_contacts():
    """STUB - fill in once you confirm the right endpoint with Whatchimp's
    API docs (https://whatchimp.com/api-integration/) or their support team.
    They do have a REST API/webhooks; the exact field name for total
    contacts/subscribers wasn't published in their public docs, so this is
    written generically - update the URL and the JSON key below."""
    api_key = os.environ.get("WHATCHIMP_API_KEY")
    base_url = os.environ.get("WHATCHIMP_API_BASE_URL")  # e.g. https://api.whatchimp.com
    if not api_key or not base_url:
        return None
    try:
        resp = requests.get(
            f"{base_url}/contacts/count",  # <-- confirm/replace this path
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return int(data.get("total") or data.get("count"))  # <-- confirm/replace this key
    except Exception as e:
        print(f"Whatchimp fetch failed (endpoint likely needs confirming): {e}", file=sys.stderr)
        return None


FETCHERS = {
    "facebook": get_facebook_page_followers,
    "instagram": get_instagram_followers,
    "tiktok": get_tiktok_followers,
    "youtube": get_youtube_subscribers,
    "telegram": get_telegram_member_count,
    "x": get_x_followers,
    "kit": get_kit_subscribers,
    "whatchimp": get_whatchimp_contacts,
}


# ---------------------------------------------------------------------------
# State (yesterday's counts) so we can compute "New Subscribers"
# ---------------------------------------------------------------------------

def load_previous_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}


def save_state(current_counts):
    STATE_FILE.write_text(json.dumps(current_counts, indent=2))


# ---------------------------------------------------------------------------
# Report building + sending
# ---------------------------------------------------------------------------

def build_report_text(current, previous):
    lines = ["*Monthstayz Thailand - Weekly Subscriber Report*", ""]
    lines.append("Platform | Previous | New | Total")
    lines.append("-" * 34)

    grand_total = 0
    any_data = False

    for key in PLATFORM_ORDER:
        label = PLATFORM_LABELS[key]
        current_count = current.get(key)
        if current_count is None:
            lines.append(f"{label} | -- not configured --")
            continue

        any_data = True
        prev_count = previous.get(key)
        new_count = (current_count - prev_count) if prev_count is not None else 0
        sign = "+" if new_count > 0 else ""
        grand_total += current_count

        lines.append(f"{label} | {prev_count if prev_count is not None else '-'} | {sign}{new_count} | {current_count}")

    lines.append("-" * 34)
    lines.append(f"*Grand Total: {grand_total}*")

    if not any_data:
        lines.append("")
        lines.append("No platforms are configured yet - add API credentials as GitHub secrets to start populating this report.")

    return "\n".join(lines)


def send_telegram_message(text):
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_REPORT_CHAT_ID")
    if not bot_token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_REPORT_CHAT_ID must be set to send the report.")

    resp = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram send failed: {result}")


def main():
    previous = load_previous_state()

    current = {}
    for key in PLATFORM_ORDER:
        try:
            current[key] = FETCHERS[key]()
        except Exception as e:
            print(f"[{key}] fetch failed: {e}", file=sys.stderr)
            current[key] = None

    report_text = build_report_text(current, previous)
    print(report_text)  # always print to logs, useful for debugging in Actions

    send_telegram_message(report_text)

    # Only persist counts we actually got, so a temporary API outage on one
    # platform doesn't wipe out its last-known value for tomorrow's delta.
    merged_state = {**previous, **{k: v for k, v in current.items() if v is not None}}
    save_state(merged_state)


if __name__ == "__main__":
    main()
