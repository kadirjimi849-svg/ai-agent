"""Get a TikTok refresh token (once per TikTok account).

1. developers.tiktok.com -> create app -> add products "Login Kit" + "Content Posting API" (enable Direct Post)
   scopes: user.info.basic, video.publish, video.list
   Redirect URI: https://manodrama.com/tiktok-callback   (any https page on your domain; it doesn't need to exist)
2. Put TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in .env
3. python tools/tiktok_auth.py   -> log in with the TikTok account you want to post to -> paste the redirected URL
Note: until TikTok audits your app, direct posts are forced to "private (SELF_ONLY)". Submit the app for review
      in the developer portal (show a screen recording of the bot's flow) to unlock public posting.
"""
import os
import secrets
import sys
from urllib.parse import parse_qs, unquote, urlencode, urlparse

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import load  # noqa: E402

load()
key, sec = os.environ["TIKTOK_CLIENT_KEY"], os.environ["TIKTOK_CLIENT_SECRET"]
redirect = os.environ.get("TIKTOK_REDIRECT", "https://manodrama.com/tiktok-callback")
url = "https://www.tiktok.com/v2/auth/authorize/?" + urlencode({
    "client_key": key, "response_type": "code", "scope": "user.info.basic,video.publish,video.list",
    "redirect_uri": redirect, "state": secrets.token_hex(8)})
print("Open:\n", url)
back = input("\nPaste the full redirected URL: ").strip()
code = unquote(parse_qs(urlparse(back).query).get("code", [back])[0])
j = requests.post("https://open.tiktokapis.com/v2/oauth/token/", headers={"Content-Type": "application/x-www-form-urlencoded"},
                  data={"client_key": key, "client_secret": sec, "code": code, "grant_type": "authorization_code",
                        "redirect_uri": redirect}).json()
print("\nrefresh token (put in .env):", j.get("refresh_token", f"ERROR {j}"))
