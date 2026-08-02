# Monthstayz Thailand - Weekly Subscriber Report Bot: Setup Guide

This bot pulls subscriber/follower counts from your platforms and posts a
weekly report to your Telegram group, automatically, via GitHub Actions
(runs every Monday by default).

You don't need to set every platform up on day one - the script skips any
platform whose credentials aren't present, so you can turn them on one at a time.

## 0. Put this in a GitHub repo

1. Create a new **private** GitHub repository (e.g. `monthstayz-subscriber-report`).
2. Upload these three files, keeping the folder structure:
   - `subscriber_report.py`
   - `.github/workflows/weekly-subscriber-report.yml`
   - `SETUP.md` (this file - optional, just for reference)
3. Go to the repo's **Settings > Secrets and variables > Actions** - this is
   where all API keys/tokens go. Never put credentials directly in the code
   or commit them to the repo.

## 1. Telegram (do this first - takes 5 minutes)

You need a bot to **send** the report, and the numeric chat ID of your group
to send it **to**.

1. In Telegram, message **@BotFather** → `/newbot` → follow the prompts →
   copy the token it gives you. This is `TELEGRAM_BOT_TOKEN`.
2. Add that bot to your Telegram group as a member (no admin needed just to post).
3. Send any message in the group, then visit this URL in a browser
   (with your token filled in):
   `https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/getUpdates`
4. Find `"chat":{"id":-100xxxxxxxxxx, ...}` in the response - that negative
   number is `TELEGRAM_REPORT_CHAT_ID`.
5. Add both as repo secrets: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_REPORT_CHAT_ID`.

If you also want the bot to report your **Telegram group's own member count**
as one of the rows (matching row 5 in your screenshot), the bot needs to be a
member of that group too, and you'd set `TELEGRAM_SOURCE_CHAT_ID` (can be the
same group ID as above, or a different one) plus `TELEGRAM_SOURCE_BOT_TOKEN`
(can reuse the same bot token).

Test it works with a manual run before moving on (see step 6).

## 2. YouTube (easy, free)

1. Go to [Google Cloud Console](https://console.cloud.google.com/) → create a
   project (or reuse one) → **APIs & Services > Library** → enable
   **YouTube Data API v3**.
2. **APIs & Services > Credentials > Create Credentials > API key**.
3. Your channel ID: go to your channel → Settings, or use
   [this lookup tool](https://commentpicker.com/youtube-channel-id.php).
4. Add secrets: `YOUTUBE_API_KEY`, `YOUTUBE_CHANNEL_ID`.

## 3. Kit (easy)

1. In Kit, go to **Settings > Advanced > Developer** and generate a V4 API Key.
2. Add secret: `KIT_API_KEY`.

## 4. Facebook Page + Instagram - scraping fallback (zero setup, less reliable)

Since both profiles are public, the script can read follower counts straight
off the public page/profile HTML - no developer app, no token, no login.

1. Add secrets:
   - `FACEBOOK_PAGE_URL` → e.g. `https://www.facebook.com/monthstayz.thailand/`
   - `INSTAGRAM_USERNAME` → e.g. `monthstayzthailand` (just the username, no @ or URL)
2. That's it - no other steps.

**Please read this before relying on it:**
- Scraping public pages without an API key is against Facebook/Instagram's
  Terms of Service, even though the data itself is public. This is a
  trade-off you're choosing in exchange for skipping the official setup.
- Meta can serve a login wall instead of the real page to automated
  requests at any time, without warning. When that happens, the script
  just skips that row for the week rather than crashing - but you also
  won't get a number that week.
- The page's HTML can change format without notice, which can silently
  break the pattern the script looks for. If Facebook or Instagram start
  showing "-- not configured --" for several weeks running even though
  the secrets are set, that's the likely cause - the regex in
  `scrape_public_page_metric()` in the script would need a small update.
- This tends to be the single least reliable part of the whole report.

**If you ever want the sturdier option later:** the script still supports
the official Graph API path (`FACEBOOK_PAGE_ID` + `FACEBOOK_PAGE_ACCESS_TOKEN`,
`INSTAGRAM_BUSINESS_ACCOUNT_ID` + `INSTAGRAM_ACCESS_TOKEN`) - if those
secrets are present, the script uses them automatically instead of scraping,
with no code changes needed. Setup for that route: create an app at
[developers.facebook.com](https://developers.facebook.com/), use
**Tools > Graph API Explorer** with your own Page selected to generate a
long-lived Page token (permissions: `pages_read_engagement`, `pages_show_list`,
`instagram_basic`), then find your Page ID (Page's **About** tab) and
Instagram Business Account ID (`GET /{page-id}?fields=instagram_business_account`).

## 5. X / Twitter (has a real cost, but tiny for this use case)

X ended its free tier in Feb 2026. However, reading your *own* account's
follower count counts as an "owned read," billed at roughly $0.001/call -
running this weekly costs a fraction of a cent a month.

1. Sign up at [developer.x.com](https://developer.x.com/) - you'll need to
   add a payment method for pay-per-use billing.
2. Create a Project + App, generate a Bearer Token.
3. Find your numeric X user ID (e.g. via `https://api.twitter.com/2/users/by/username/MonthStayz`
   using your bearer token once you have it, or a free "tweet ID lookup" tool).
4. Add secrets: `X_BEARER_TOKEN`, `X_USER_ID`.

## 6. TikTok - not automatable right now

TikTok's public Display API does **not** expose follower counts to standard
apps - only via their Business API (needs a business partnership approval)
or Research API (academic/nonprofit only). There's no realistic from-scratch
path here.

For now, the script supports a manual override: set the secret
`TIKTOK_MANUAL_COUNT` to whatever the current count is, and update it by hand
each time you check TikTok directly. If you later get TikTok Business API
access, let me know and I'll wire up the real endpoint.

## 7. Whatchimp - needs one more piece of info

Whatchimp does have an API (see whatchimp.com/api-integration/), but their
public docs don't specify the exact endpoint/field for total contact count.
Two options:
- Ask their support team "what's the API endpoint to get my total contact/
  subscriber count?" and send me the answer - I'll wire it in precisely.
- Or check your Whatchimp dashboard's API/Developer section yourself for a
  documented endpoint.

Once you have it, set `WHATCHIMP_API_KEY` and `WHATCHIMP_API_BASE_URL`, and
update the URL path + JSON field name in `get_whatchimp_contacts()` in the
script (marked clearly with comments).

## 8. Test it

In your GitHub repo, go to **Actions > Weekly Subscriber Report > Run workflow**
to trigger it manually and confirm the message lands in your Telegram group.
Check any platforms showing "-- not configured --" against the secrets above.

Once it's running clean, it will fire automatically every Monday at the time
set in the workflow file (default: 9am Bangkok time - edit the `cron` line to change it).
