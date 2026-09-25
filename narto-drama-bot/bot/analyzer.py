"""Find the dramatic moments of an episode without any AI model:

  * audio energy + sudden loudness jumps (slaps, screams, music stings)
  * scene-cut density (fast editing = tension)
  * a light bias toward later moments (short dramas escalate)

From those we build clip plans:
  teaser  = a 2s flash-forward of the strongest moment INSIDE the clip (shown first, with the hook text)
  body    = 25-55s that ENDS right as the next big moment starts  -> cliffhanger
"""
import json
import re
import subprocess

import numpy as np

WIN = 0.5  # seconds per analysis window


def probe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "format=duration:stream=codec_type,width,height", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), {})
    return {"duration": float(j["format"]["duration"]), "width": v.get("width"), "height": v.get("height"),
            "has_audio": any(s["codec_type"] == "audio" for s in j["streams"])}


def _audio_rms(path: str, dur: float) -> np.ndarray:
    sr = 8000
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True).stdout
    n = int(dur / WIN)
    if not raw:
        return np.zeros(n)
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    step = int(sr * WIN)
    frames = len(a) // step
    rms = np.sqrt(np.mean(a[: frames * step].reshape(frames, step) ** 2, axis=1) + 1e-9)
    db = 20 * np.log10(rms + 1e-6)
    out = np.full(n, db.min() if len(db) else -60.0)
    out[: min(n, len(db))] = db[:n]
    return out


def _scene_cuts(path: str, thr=0.32) -> list[float]:
    p = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-an", "-vf",
                        f"scale=192:-2,select='gt(scene,{thr})',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", p.stderr)]


def _z(x):
    s = x.std()
    return (x - x.mean()) / s if s > 1e-6 else x * 0


def analyze(path: str) -> dict:
    info = probe(path)
    dur = info["duration"]
    n = max(1, int(dur / WIN))
    rms = _audio_rms(path, dur) if info["has_audio"] else np.zeros(n)
    cuts = _scene_cuts(path)
    loud = _z(rms)
    # onset: how much louder than the previous 3 seconds
    prev = np.array([rms[max(0, i - 6):i].mean() if i else rms[0] for i in range(n)])
    onset = _z(np.clip(rms - prev, 0, None))
    density = np.zeros(n)
    for c in cuts:
        i = int(c / WIN)
        density[max(0, i - 2): i + 3] += 1
    density = _z(density)
    ramp = np.linspace(0, 0.35, n)  # escalation bias
    intensity = 0.45 * loud + 0.4 * onset + 0.3 * density + ramp
    # light smoothing
    intensity = np.convolve(intensity, np.ones(3) / 3, mode="same")
    return {**info, "win": WIN, "cuts": cuts, "intensity": [round(float(v), 3) for v in intensity]}


def _peaks(x: np.ndarray, min_gap: int) -> list[int]:
    order = np.argsort(-x)
    chosen = []
    for i in order:
        if all(abs(i - j) >= min_gap for j in chosen):
            chosen.append(int(i))
    return chosen


def _snap(t: float, cuts: list[float], lo: float, hi: float) -> float:
    """Move t to the nearest scene cut inside [lo,hi] so clips start on a clean shot."""
    cands = [c for c in cuts if lo <= c <= hi]
    return min(cands, key=lambda c: abs(c - t)) if cands else t


def plan_clips(a: dict, count=3, min_len=25.0, max_len=55.0, teaser_len=2.2, taken=None) -> list[dict]:
    """taken: list of (start,end) already used for this episode -> avoid overlap."""
    x = np.array(a["intensity"])
    dur, win, cuts = a["duration"], a["win"], a["cuts"]
    taken = list(taken or [])
    plans = []
    if dur <= min_len + 3:  # tiny episode: whole thing is the clip
        i = int(np.argmax(x))
        return [{"start": 0.0, "end": dur, "teaser_start": max(0, i * win - 1), "teaser_end": min(dur, i * win - 1 + teaser_len),
                 "score": float(x[i])}]
    for pi in _peaks(x, min_gap=int(8 / win)):
        cliff = pi * win
        end = cliff + 0.4  # stop right as the shock begins
        if end < min_len * 0.8 or end > dur - 0.5:
            continue
        # choose length: try to include a strong second moment for the teaser
        length = min(max_len, end)
        start = _snap(end - length, cuts, end - max_len, end - min_len)
        start = max(0.0, start)
        if end - start < min_len * 0.8:
            continue
        if any(not (end <= s or start >= e) for s, e in taken):
            continue
        # teaser: strongest point inside body, excluding the last 4s (don't spoil the cliffhanger)
        lo, hi = int(start / win) + 2, int((end - 4) / win)
        if hi <= lo:
            continue
        ti = lo + int(np.argmax(x[lo:hi]))
        t0 = max(start, ti * win - teaser_len * 0.45)
        plans.append({"start": round(start, 2), "end": round(end, 2),
                      "teaser_start": round(t0, 2), "teaser_end": round(t0 + teaser_len, 2),
                      "score": round(float(x[pi] + 0.5 * x[ti]), 3)})
        taken.append((start, end))
        if len(plans) >= count:
            break
    return plans
