"""Browser sign-in for the 4 platforms (official OAuth). The dashboard runs on http://localhost:<port>,
so each developer app must allow these redirect URLs:

  YouTube   http://localhost:<port>/oauth/youtube      (Google "Desktop app" clients accept any localhost port)
  Facebook  http://localhost:<port>/oauth/facebook     (Facebook Login -> Valid OAuth Redirect URIs)
  TikTok    http://localhost:<port>/oauth/tiktok       (or any https URL of yours: then paste the address back)
Instagram is connected through Facebook (the IG professional account linked to a Facebook Page).
"""
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

import requests

GRAPH = "v23.0"
FB_SCOPES = ("pages_show_list,pages_read_engagement,pages_manage_posts,pages_read_user_content,read_insights,"
             "business_management,instagram_basic,instagram_content_publish,instagram_manage_insights")
YT_SCOPES = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"
TT_SCOPES = "user.info.basic,video.publish,video.list"


class OAuthError(Exception):
    pass


def _need(*names):
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise OAuthError("أدخل أولاً في الإعدادات: " + ", ".join(missing))
    return [os.environ[n] for n in names]


def _new_state(db, platform, **extra):
    st = secrets.token_urlsafe(16)
    db.set(f"oauth:{st}", {"platform": platform, "t": time.time(), **extra})
    return st


def pop_state(db, state, platform):
    data = db.get(f"oauth:{state}") if state else None
    db.x("DELETE FROM kv WHERE key=?", f"oauth:{state}")
    if not data or data["platform"] != platform or time.time() - data["t"] > 1800:
        raise OAuthError("انتهت صلاحية طلب الربط، أعد المحاولة")
    return data


def tiktok_redirect(base):
    return os.environ.get("TIKTOK_REDIRECT") or f"{base}/oauth/tiktok"


# ---------------------------------------------------------------- YouTube
def youtube_url(db, base):
    cid, _ = _need("YT_CLIENT_ID", "YT_CLIENT_SECRET")
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
        "client_id": cid, "redirect_uri": f"{base}/oauth/youtube", "response_type": "code",
        "access_type": "offline", "prompt": "consent select_account", "scope": YT_SCOPES,
        "state": _new_state(db, "youtube")})


def youtube_finish(code, base):
    cid, sec = _need("YT_CLIENT_ID", "YT_CLIENT_SECRET")
    j = requests.post("https://oauth2.googleapis.com/token", timeout=60, data={
        "code": code, "client_id": cid, "client_secret": sec, "redirect_uri": f"{base}/oauth/youtube",
        "grant_type": "authorization_code"}).json()
    if "refresh_token" not in j:
        raise OAuthError(f"Google: {j.get('error_description') or j}")
    ch = requests.get("https://www.googleapis.com/youtube/v3/channels", timeout=60,
                      params={"part": "snippet", "mine": "true"},
                      headers={"Authorization": f"Bearer {j['access_token']}"}).json()
    items = ch.get("items") or []
    if not items:
        raise OAuthError("هذا الحساب ليس لديه قناة يوتيوب")
    it = items[0]
    return {"channel_id": it["id"], "title": it["snippet"]["title"], "refresh_token": j["refresh_token"]}


# ---------------------------------------------------------------- Facebook + Instagram
def facebook_url(db, base):
    app_id, _ = _need("META_APP_ID", "META_APP_SECRET")
    return f"https://www.facebook.com/{GRAPH}/dialog/oauth?" + urlencode({
        "client_id": app_id, "redirect_uri": f"{base}/oauth/facebook", "scope": FB_SCOPES,
        "response_type": "code", "state": _new_state(db, "facebook")})


def facebook_pages(user_token):
    """Page tokens obtained from a long-lived user token do not expire."""
    app_id, sec = _need("META_APP_ID", "META_APP_SECRET")
    long_user = requests.get(f"https://graph.facebook.com/{GRAPH}/oauth/access_token", timeout=60, params={
        "grant_type": "fb_exchange_token", "client_id": app_id, "client_secret": sec,
        "fb_exchange_token": user_token}).json()
    if "access_token" not in long_user:
        raise OAuthError(f"Facebook: {long_user.get('error', long_user)}")
    j = requests.get(f"https://graph.facebook.com/{GRAPH}/me/accounts", timeout=60, params={
        "fields": "name,id,access_token,picture{url},instagram_business_account{id,username,profile_picture_url}",
        "access_token": long_user["access_token"], "limit": 100}).json()
    if "data" not in j:
        raise OAuthError(f"Facebook: {j.get('error', j)}")
    pages = []
    for p in j["data"]:
        ig = p.get("instagram_business_account") or {}
        pages.append({"id": p["id"], "name": p["name"], "token": p["access_token"],
                      "picture": ((p.get("picture") or {}).get("data") or {}).get("url"),
                      "ig_id": ig.get("id"), "ig_username": ig.get("username")})
    return pages


def facebook_finish(code, base):
    app_id, sec = _need("META_APP_ID", "META_APP_SECRET")
    j = requests.get(f"https://graph.facebook.com/{GRAPH}/oauth/access_token", timeout=60, params={
        "client_id": app_id, "client_secret": sec, "redirect_uri": f"{base}/oauth/facebook", "code": code}).json()
    if "access_token" not in j:
        raise OAuthError(f"Facebook: {j.get('error', j)}")
    return facebook_pages(j["access_token"])


# ---------------------------------------------------------------- TikTok
def _is_local(url):
    return url.startswith(("http://localhost", "http://127.0.0.1"))


def tiktok_url(db, base):
    key, _ = _need("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
    redirect = tiktok_redirect(base)
    params = {"client_key": key, "response_type": "code", "scope": TT_SCOPES, "redirect_uri": redirect}
    extra = {}
    if _is_local(redirect):  # TikTok "Desktop" apps use PKCE (hex-encoded SHA256 challenge)
        verifier = secrets.token_urlsafe(48)
        params.update(code_challenge=hashlib.sha256(verifier.encode()).hexdigest(), code_challenge_method="S256")
        extra["verifier"] = verifier
    params["state"] = _new_state(db, "tiktok", **extra)
    return "https://www.tiktok.com/v2/auth/authorize/?" + urlencode(params)


def tiktok_finish(code, base, verifier=None):
    key, sec = _need("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET")
    data = {"client_key": key, "client_secret": sec, "code": code, "grant_type": "authorization_code",
            "redirect_uri": tiktok_redirect(base)}
    if verifier:
        data["code_verifier"] = verifier
    j = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=60, data=data,
                      headers={"Content-Type": "application/x-www-form-urlencoded"}).json()
    if "refresh_token" not in j:
        raise OAuthError(f"TikTok: {j.get('error_description') or j}")
    u = requests.get("https://open.tiktokapis.com/v2/user/info/", timeout=60,
                     params={"fields": "open_id,display_name,avatar_url"},
                     headers={"Authorization": f"Bearer {j['access_token']}"}).json()
    user = (u.get("data") or {}).get("user") or {}
    return {"open_id": j.get("open_id") or user.get("open_id"), "display_name": user.get("display_name") or "TikTok",
            "refresh_token": j["refresh_token"], "access_token": j["access_token"],
            "exp": time.time() + int(j.get("expires_in", 86400))}
