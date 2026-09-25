"""Get NON-EXPIRING Page tokens (+ linked Instagram IDs) for all your Facebook pages.

1. developers.facebook.com -> create an app (type Business) -> add "Facebook Login for Business"
2. Graph API Explorer -> choose your app -> add permissions:
     pages_show_list, pages_read_engagement, pages_manage_posts, pages_read_user_content,
     read_insights, business_management, instagram_basic, instagram_content_publish, instagram_manage_insights
   -> Generate Access Token (short-lived user token)
3. python tools/meta_tokens.py <SHORT_USER_TOKEN>      (META_APP_ID / META_APP_SECRET in .env)
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot.config import load  # noqa: E402  (loads .env)

cfg = load()
V = cfg.get("graph_version", "v23.0")
short = sys.argv[1]
long_user = requests.get(f"https://graph.facebook.com/{V}/oauth/access_token", params={
    "grant_type": "fb_exchange_token", "client_id": os.environ["META_APP_ID"],
    "client_secret": os.environ["META_APP_SECRET"], "fb_exchange_token": short}).json()
if "access_token" not in long_user:
    sys.exit(long_user)
pages = requests.get(f"https://graph.facebook.com/{V}/me/accounts", params={
    "fields": "name,id,access_token,instagram_business_account{id,username}",
    "access_token": long_user["access_token"], "limit": 100}).json()
for p in pages.get("data", []):
    ig = p.get("instagram_business_account") or {}
    print(f"\n# {p['name']}\n  page_id: \"{p['id']}\"")
    if ig:
        print(f"  instagram: @{ig.get('username')}  ig_user_id: \"{ig['id']}\"")
    print(f"  token (put in .env): {p['access_token']}")
