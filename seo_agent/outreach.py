from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .config import FOLLOW_UP_DAYS
from .models import BacklinkOpportunity, OutreachEmail, TargetWebsite


@dataclass
class OutreachContext:
    """Everything needed to personalize one pitch. All fields are required — no generic emails."""

    host: BacklinkOpportunity
    contact_name: str
    sender_name: str
    sender_role: str
    referenced_article_title: str
    referenced_article_url: str
    content_idea: str
    value_proposition: str


class MissingPersonalization(ValueError):
    pass


def _require(ctx: OutreachContext) -> None:
    missing = [name for name in ("contact_name", "sender_name", "referenced_article_title",
                                 "content_idea", "value_proposition")
               if not getattr(ctx, name).strip()]
    if not ctx.host.contact_email:
        missing.append("host.contact_email")
    if missing:
        raise MissingPersonalization("Cannot send a generic email; missing: " + ", ".join(missing))


_TEMPLATES = {
    "en": {
        "subject": "Content idea for {site}: {idea}",
        "body": (
            "Hi {contact},\n\n"
            "I'm {sender}, {role} at {brand}. I recently read \"{ref_title}\" on {site} "
            "({ref_url}) and appreciated how practical it was for your readers.\n\n"
            "I'd like to contribute an original piece that builds on it: {idea}.\n\n"
            "Why it could be useful for {site}: {value}\n\n"
            "It would be written exclusively for {site}, follow your editorial guidelines, and "
            "I'm happy to adjust the angle to fit your content calendar.\n\n"
            "Would that be of interest?\n\n"
            "Best regards,\n{sender}\n{role}, {brand}"
        ),
        "followups": [
            ("Re: Content idea for {site}",
             "Hi {contact},\n\nJust bringing this back to the top of your inbox — I'd still love to "
             "write \"{idea}\" for {site}. Happy to share an outline first if that helps.\n\nBest,\n{sender}"),
            ("Re: Content idea for {site}",
             "Hi {contact},\n\nI know editors get a lot of pitches. If this topic isn't the right fit, "
             "I'd be glad to suggest a different angle related to \"{ref_title}\".\n\nThanks,\n{sender}"),
            ("Closing the loop — {site}",
             "Hi {contact},\n\nI'll close the loop here so I don't clutter your inbox. If you'd like "
             "the piece in the future, just reply and I'll pick it up.\n\nAll the best,\n{sender}"),
        ],
    },
    "ar": {
        "subject": "فكرة مقال لموقع {site}: {idea}",
        "body": (
            "مرحباً {contact}،\n\n"
            "أنا {sender}، {role} في {brand}. قرأت مؤخراً مقال \"{ref_title}\" على موقع {site} "
            "({ref_url}) وأعجبني ما قدّمه من فائدة عملية لقرّائكم.\n\n"
            "أودّ المساهمة بمقال أصلي يكمل هذا الموضوع: {idea}.\n\n"
            "لماذا قد يفيد قرّاء {site}: {value}\n\n"
            "سيُكتب المقال حصرياً لموقعكم وفق إرشاداتكم التحريرية، ويسعدني تعديل الزاوية بما "
            "يناسب خطتكم.\n\n"
            "هل تهمّكم الفكرة؟\n\n"
            "مع خالص التحية،\n{sender}\n{role}، {brand}"
        ),
        "followups": [
            ("رد: فكرة مقال لموقع {site}",
             "مرحباً {contact}،\n\nأردت فقط التذكير برسالتي السابقة، فما زلت متحمساً لكتابة "
             "\"{idea}\" لموقع {site}. يمكنني إرسال مخطط مبدئي أولاً إن رغبتم.\n\nمع التحية،\n{sender}"),
            ("رد: فكرة مقال لموقع {site}",
             "مرحباً {contact}،\n\nإن لم يكن هذا الموضوع مناسباً، يسعدني اقتراح زاوية أخرى مرتبطة "
             "بمقال \"{ref_title}\".\n\nشكراً لكم،\n{sender}"),
            ("رسالة أخيرة — {site}",
             "مرحباً {contact}،\n\nلن أثقل عليكم برسائل إضافية. إن رغبتم في المقال مستقبلاً، "
             "يكفي الرد على هذه الرسالة.\n\nأطيب التمنيات،\n{sender}"),
        ],
    },
}


def build_sequence(ctx: OutreachContext, client: TargetWebsite, start: date | None = None) -> list[OutreachEmail]:
    """Initial pitch plus Day 3 / 7 / 14 follow-ups, in the host site's language."""
    _require(ctx)
    start = start or date.today()
    lang = ctx.host.language if ctx.host.language in _TEMPLATES else "en"
    t = _TEMPLATES[lang]
    fields = dict(
        site=ctx.host.website, contact=ctx.contact_name, sender=ctx.sender_name,
        role=ctx.sender_role, brand=client.brand_name or client.domain,
        ref_title=ctx.referenced_article_title, ref_url=ctx.referenced_article_url,
        idea=ctx.content_idea, value=ctx.value_proposition,
    )
    emails = [OutreachEmail(ctx.host.contact_email, t["subject"].format(**fields),
                            t["body"].format(**fields), lang, start, 0)]
    for step, (day, (subj, body)) in enumerate(zip(FOLLOW_UP_DAYS, t["followups"]), 1):
        emails.append(OutreachEmail(ctx.host.contact_email, subj.format(**fields), body.format(**fields),
                                    lang, start + timedelta(days=day), step))
    return emails


def due_emails(sequence: list[OutreachEmail], today: date, replied: bool) -> list[OutreachEmail]:
    """Follow-ups stop as soon as the contact replies."""
    if replied:
        return []
    return [e for e in sequence if e.send_on == today]
