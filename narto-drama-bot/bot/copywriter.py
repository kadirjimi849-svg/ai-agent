"""Hooks, captions, titles, hashtags.

Two modes:
  * built-in library (works offline, no cost) - hook "styles" are tracked so the bot learns which style wins
  * optional Claude API: writes fresh hooks per drama from its synopsis (set ANTHROPIC_API_KEY + copywriter.ai: true)
"""
import json
import os
import random
import re
from urllib.parse import urlencode

# style_id -> templates. {title} is replaced by the drama title.
# Library hooks are deliberately plot-agnostic (true for any drama of that niche).
# Plot-specific hooks come from catalog.yaml (hooks:) or from the AI reading the synopsis.
HOOKS_AR = {
    "shock": ["لن تصدق ما فعلته أمام الجميع!", "هذا المشهد صدم الجميع…", "لم يتوقع أحد هذه النهاية!",
              "انظر إلى وجهه عندما عرف الحقيقة"],
    "question": ["ماذا كنت ستفعل لو كنت مكانها؟", "هل تستحق هذا بعد كل ما فعلته؟",
                 "من برأيك على حق؟ اكتب في التعليقات", "هل سيسامحها بعد هذا؟"],
    "revenge": ["ظنّوا أنها ضعيفة… كانوا مخطئين", "لحظة الانتقام التي انتظرها الجميع",
                "أذلّوه أمام الجميع… والآن جاء دوره", "الانتقام يبدأ الآن…"],
    "ceo": ["المدير التنفيذي البارد لم يعد بارداً", "عندما يغار المدير…",
            "لم يعرف أنها ستغيّر حياته", "قلبه لا يتحرك إلا من أجلها"],
    "secret": ["لا أحد يعرف من هو حقاً…", "سخروا منه… قبل أن يعرفوا هويته", "سرّ سيغيّر كل شيء"],
    "rebirth": ["فرصة ثانية… وهذه المرة لن تخطئ", "هذه المرة لن تثق بأحد", "عادت لتغيّر مصيرها"],
    "werewolf": ["رفضها… ثم ندم", "القمر المكتمل يكشف كل شيء", "هي ليست كما يظنون"],
    "suspense": ["انتظر حتى النهاية…", "آخر 5 ثوانٍ غيّرت كل شيء", "لن تصدق ما سيحدث بعد ذلك"],
    "legend": ["سخروا منه… ولم يعرفوا أنه أسطورة", "الجميع استهانوا به… حتى هذه اللحظة",
               "القوة الحقيقية تظهر الآن…", "عاد… والجميع يرتجف", "ظنّوه ضعيفاً… خطأ لن ينسوه"],
}
HOOKS_EN = {
    "shock": ["You won't believe what she did in front of everyone", "Nobody saw this coming…"],
    "question": ["What would you do in her place?", "Who's right? Tell us in the comments"],
    "revenge": ["They thought she was weak… they were wrong", "The revenge everyone was waiting for"],
    "ceo": ["The cold CEO isn't so cold anymore", "He had no idea she'd change his life"],
    "secret": ["Nobody knows who he really is…", "They laughed… before they knew who he was"],
    "rebirth": ["A second chance… and this time she won't fail"],
    "werewolf": ["He rejected her… then regretted it"],
    "suspense": ["Wait for the end…", "The last 5 seconds changed everything"],
    "legend": ["They laughed at him… not knowing he was a legend", "His real power shows now…"],
}
NICHE_STYLES = {
    "revenge": ["revenge", "shock", "suspense", "question"],
    "ceo": ["ceo", "secret", "question", "suspense"],
    "romance": ["ceo", "question", "suspense", "shock"],
    "secret": ["secret", "shock", "suspense"],
    "rebirth": ["rebirth", "revenge", "suspense"],
    "werewolf": ["werewolf", "shock", "suspense"],
    "family": ["shock", "question", "suspense"],
    "legend": ["legend", "secret", "shock", "suspense"],
}
TAGS_AR = {
    "base": ["#دراما", "#مسلسلات_قصيرة", "#مسلسل_مدبلج", "#دراما_صينية"],
    "legend": ["#أسطورة", "#أكشن"],
    "revenge": ["#انتقام", "#دراما_انتقام"], "ceo": ["#المدير_التنفيذي", "#رومانسي"],
    "romance": ["#رومانسي", "#حب"], "secret": ["#هوية_سرية", "#ملياردير"],
    "rebirth": ["#العودة_بالزمن"], "werewolf": ["#مستذئب", "#ألفا"], "family": ["#عائلة"],
    "tiktok": ["#اكسبلور", "#fyp"], "instagram": ["#اكسبلور", "#reels"], "youtube": ["#shorts"], "facebook": ["#reels"],
}
TAGS_EN = {"base": ["#drama", "#shortdrama", "#minidrama", "#cdrama"], "legend": ["#action"], "revenge": ["#revenge"], "ceo": ["#ceo", "#romance"],
           "romance": ["#romance"], "secret": ["#billionaire"], "rebirth": ["#rebirth"], "werewolf": ["#werewolf", "#alpha"],
           "family": ["#family"], "tiktok": ["#fyp"], "instagram": ["#reels"], "youtube": ["#shorts"], "facebook": ["#reels"]}

END_LINES = {"ar": ("ماذا سيحدث بعد ذلك؟", "شاهد الحلقة كاملة مجاناً"),
             "en": ("What happens next?", "Watch the full episode free")}
END_LINES_NO_SITE = {"ar": ("ماذا سيحدث بعد ذلك؟", "تابعنا حتى لا يفوتك الجزء التالي"),
                     "en": ("What happens next?", "Follow so you don't miss the next part")}


class Copywriter:
    def __init__(self, cfg, db, brain=None):
        self.cfg = cfg.get("copywriter") or {}
        self.site = cfg  # domain / drama_url
        self.db = db
        self.brain = brain

    # ---------- hooks ----------
    def hooks(self, drama, lang: str, n: int) -> list[tuple[str, str]]:
        """Returns n (style_id, text) pairs, favouring styles that performed best."""
        ai = self._ai_hooks(drama, lang) if self.cfg.get("ai") else []
        lib = HOOKS_AR if lang == "ar" else HOOKS_EN
        custom = (json.loads(drama["extra"] or "{}").get("hooks") or {}).get(lang, [])
        styles = NICHE_STYLES.get(drama["niche"], ["shock", "question", "suspense"])
        if self.brain:
            styles = self.brain.rank_styles(styles)
        pool = [("custom", h) for h in custom] + [("ai", h) for h in ai]
        for st in styles:
            pool += [(st, h) for h in random.sample(lib.get(st, []), len(lib.get(st, [])))]
        # first pick = best style, then diversify styles
        out, seen = [], set()
        for st, h in pool:
            if st not in seen or len(seen) >= n:
                out.append((st, h))
                seen.add(st)
            if len(out) >= n:
                break
        return out

    def _ai_hooks(self, drama, lang):
        key = os.environ.get("ANTHROPIC_API_KEY")
        cache_key = f"aihooks:{drama['slug']}:{lang}"
        if not key or (cached := self.db.get(cache_key)):
            return (cached or [])[:6]
        extra = json.loads(drama["extra"] or "{}")
        prompt = (f"You write viral on-screen hooks for short-drama clips on TikTok/Reels/Shorts.\n"
                  f"Series title: {drama['title']} (genre: {drama['niche']}). "
                  f"Synopsis: {extra.get('synopsis') or 'not available - work from the title only'}\n"
                  f"Write 8 hooks in {'Modern Standard Arabic understood across the Arab world' if lang == 'ar' else 'English'}"
                  f", max 45 characters each, curiosity-driven, no emojis, no hashtags, no spoilers of the ending, "
                  f"and never claim a specific plot event you cannot infer from the title or synopsis. "
                  f"Return ONLY a JSON array of strings.")
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            r = client.beta.messages.create(
                model=self.cfg.get("model") or "claude-opus-5", max_tokens=16000,
                output_config={"effort": "low"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                messages=[{"role": "user", "content": prompt}])
            if r.stop_reason == "refusal":
                raise RuntimeError("request declined")
            txt = "".join(b.text for b in r.content if b.type == "text")
            hooks = json.loads(txt[txt.index("["): txt.rindex("]") + 1])
            hooks = [h.strip() for h in hooks if isinstance(h, str) and 5 < len(h.strip()) <= 60]
            self.db.set(cache_key, hooks)
            return hooks[:6]
        except Exception as e:  # never block production on the AI
            print(f"[copywriter] AI hooks skipped: {e}")
            return []

    def best_hook(self, drama, lang, recent=()) -> tuple[str, str]:
        """The strongest hook not used recently (style ranking learns from the stats)."""
        cands = self.hooks(drama, lang, 12)
        for st, h in cands:
            if h not in recent:
                return st, h
        return cands[0]

    # ---------- captions ----------
    def link(self, drama, ep_no, platform, account, clip_id):
        base = drama["url"] or ""
        if not base and (tpl := self.site.get("drama_url")):
            base = tpl.format(slug=drama["slug"])
        if not base:
            return None
        sep = "&" if "?" in base else "?"
        q = {"ep": ep_no, "utm_source": platform, "utm_medium": "short", "utm_campaign": drama["slug"],
             "utm_content": f"{account}-c{clip_id}"}
        return base + sep + urlencode(q)

    def caption(self, *, drama, ep_no, hook, lang, platform, account, clip_id, domain):
        tags_src = TAGS_AR if lang == "ar" else TAGS_EN
        tags = tags_src["base"] + tags_src.get(drama["niche"], []) + tags_src.get(platform, [])
        tags.append("#" + re.sub(r"\W+", "_", drama["title"]).strip("_")[:40])
        title = drama["title"] if lang == "ar" else (drama["title_en"] or drama["title"])
        link = self.link(drama, ep_no, platform, account, clip_id)
        clickable = platform in ("facebook", "youtube")
        ar = lang == "ar"
        if link and clickable:
            where = f"▶️ {'شاهد المسلسل كاملاً مجاناً' if ar else 'Watch the full series free'}: {link}"
        elif domain:
            where = f"🔗 {'الحلقات كاملة على' if ar else 'Full episodes on'} {domain} ({'الرابط في البايو' if ar else 'link in bio'})"
        else:
            where = "🔔 تابعنا ليصلك الجزء التالي" if ar else "🔔 Follow for the next part"
        if ar:
            body = f"{hook}\n\n🎬 {title} – الحلقة {ep_no}\n{where}\n\n💬 اكتب رأيك في التعليقات"
        else:
            body = f"{hook}\n\n🎬 {title} – Episode {ep_no}\n{where}\n\n💬 Tell us what you think"
        body += "\n\n" + " ".join(dict.fromkeys(tags))
        yt_title = f"{hook} | {title} #shorts"[:100]
        return {"caption": body[:2200], "title": yt_title, "link": link}

    @staticmethod
    def end_lines(lang, has_site=True):
        src = END_LINES if has_site else END_LINES_NO_SITE
        return src.get(lang, src["ar"])
