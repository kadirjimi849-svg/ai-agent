"""Get a YouTube refresh token (run once per channel, from ANY computer).

1. console.cloud.google.com -> new project -> enable "YouTube Data API v3"
2. OAuth consent screen: External, add your Gmail as test user, then PUBLISH the app
   (apps in "testing" get refresh tokens that expire after 7 days)
3. Credentials -> OAuth client ID -> "Desktop app" -> put ID/secret in .env (YT_CLIENT_ID / YT_CLIENT_SECRET)
4. python tools/youtube_auth.py
   open the link, choose the channel, allow. The browser then goes to http://localhost/?code=...
   (the page won't load - that's normal). Copy the FULL address from the address bar and paste it here.
Note: until Google audits your API project, videos uploaded via API may be forced to private.
      Request the audit: https://support.google.com/youtube/contact/yt_api_form
"""
import os
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import load  # noqa: E402

load()
cid, sec = os.environ["YT_CLIENT_ID"], os.environ["YT_CLIENT_SECRET"]
redirect = "http://localhost"
url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
    "client_id": cid, "redirect_uri": redirect, "response_type": "code", "access_type": "offline", "prompt": "consent",
    "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"})
print("Open:\n", url)
back = input("\nPaste the full localhost URL: ").strip()
code = parse_qs(urlparse(back).query).get("code", [back])[0]
j = requests.post("https://oauth2.googleapis.com/token", data={
    "code": code, "client_id": cid, "client_secret": sec, "redirect_uri": redirect,
    "grant_type": "authorization_code"}).json()
print("\nYT_REFRESH_TOKEN=" + j.get("refresh_token", f"ERROR {j}"))
