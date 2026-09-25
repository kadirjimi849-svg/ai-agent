"""Local series library, e.g.  D:\\narto-drama\\(مدبلج) أسطورة قرية السنام\\1.mp4

Every sub-folder of the root is one series. Its title is the folder name without "(مدبلج)".
Episodes are the video files inside (sub-folders included), numbered from the file name
("12.mp4", "الحلقة 12", "EP12") or, when names carry no usable number, by natural sort order.
"""
import hashlib
import json
import re
from pathlib import Path

from .logs import log
from .storage import VIDEO_EXT, ep_number

NICHE_WORDS = [  # first match wins; used to pick hook styles and hashtags
    ("revenge", ["انتقام", "انتقم", "ثأر", "الخائن", "خيانة"]),
    ("legend", ["أسطور", "اسطور", "إمبراطور", "امبراطور", "التنين", "سيف", "القتال", "الكركدن", "ملك", "الحارس",
                "قوة", "المحارب", "السيوف", "حكم العالم"]),
    ("ceo", ["ملياردير", "المدير", "الرئيس", "العملاق المالي", "الثري", "ثري", "الوريث"]),
    ("secret", ["سر", "السري", "الخفي", "المختوم", "متخفي", "المتخفي", "هوية", "الظل"]),
    ("rebirth", ["عودة", "العائد", "ولادة", "بعد أن", "المطرود", "المنتقل"]),
    ("werewolf", ["ذئب", "مستذئب", "الوحوش"]),
    ("family", ["التوأم", "الأب", "الأم", "زوجة الأب", "عائلة"]),
    ("romance", ["حب", "زواج", "زوج", "زوجة", "القلوب", "عشق", "الحسناء", "حرة"]),
]


def clean_title(folder: str) -> str:
    t = re.sub(r"[\(\[（]\s*مدبلج[ةه]?\s*[\)\]）]", "", folder)
    t = re.sub(r"\bمدبلج[ةه]?\b", "", t)
    return re.sub(r"\s+", " ", t).strip(" -_") or folder


def guess_niche(title: str) -> str:
    for niche, words in NICHE_WORDS:
        if any(w in title for w in words):
            return niche
    return "family"


def slug_for(folder: str) -> str:
    return "s-" + hashlib.md5(folder.encode("utf-8")).hexdigest()[:10]


def _natural(p: Path):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", str(p))]


def episodes_in(folder: Path) -> list[tuple[int, str]]:
    files = sorted((p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXT), key=_natural)
    nums = [ep_number(p.name) for p in files]
    if None in nums or len(set(nums)) != len(nums):
        nums = list(range(1, len(files) + 1))
    return sorted(zip(nums, (str(p) for p in files)))


def scan(db, root: str) -> dict:
    """Adds/updates every series folder under root. Keeps the active/priority choices made in the dashboard."""
    rootp = Path(root)
    if not rootp.is_dir():
        raise FileNotFoundError(f"المجلد غير موجود: {root}")
    found, eps_total = 0, 0
    for d in sorted((p for p in rootp.iterdir() if p.is_dir()), key=_natural):
        eps = episodes_in(d)
        if not eps:
            continue
        slug, title = slug_for(d.name), clean_title(d.name)
        row = db.one("SELECT extra FROM dramas WHERE slug=?", slug)
        extra = json.loads(row["extra"] or "{}") if row else {}
        extra.update({"folder": str(d), "source": {"type": "local", "dir": str(d)}})
        if row:
            db.x("UPDATE dramas SET title=?, extra=? WHERE slug=?", title, json.dumps(extra, ensure_ascii=False), slug)
        else:
            db.x("INSERT INTO dramas(slug,title,niche,url,priority,active,extra) VALUES(?,?,?,?,1.0,1,?)",
                 slug, title, guess_niche(title), "", json.dumps(extra, ensure_ascii=False))
        for n, src in eps:
            db.x("""INSERT INTO episodes(drama_slug,ep_no,src,src_type) VALUES(?,?,?,'local')
                    ON CONFLICT(drama_slug,ep_no) DO UPDATE SET src=excluded.src""", slug, n, src)
        # episodes whose file was removed from disk
        db.x(f"DELETE FROM episodes WHERE drama_slug=? AND ep_no NOT IN ({','.join('?' * len(eps))})"
             " AND id NOT IN (SELECT episode_id FROM clips)", slug, *[n for n, _ in eps])
        found += 1
        eps_total += len(eps)
    log(f"library: {found} series, {eps_total} episodes in {root}")
    return {"series": found, "episodes": eps_total}
