"""Render a vertical 1080x1920 short:

 [teaser 2s, zoom-punch + white flash]  ->  [body ending on the cliffhanger]  ->  [end card CTA]
 + hook text (first seconds) + drama/episode label + domain pill + red progress bar + loudness -14 LUFS
"""
import subprocess
from pathlib import Path

from . import overlays

FPS = 30
END_CARD = 2.8


def _fmt(label_in, label_out, zoom=False, vertical=False):
    """Fit any aspect into 1080x1920. Wide sources get a cheap blurred background
    (blur done at 1/4 resolution -> ~10x faster than full-res gblur)."""
    z = ",scale=trunc(iw*1.12/2)*2:-2,crop=trunc(iw/1.12/2)*2:trunc(ih/1.12/2)*2" if zoom else ""
    if vertical:
        zv = ",scale=1210:-2,crop=1080:1920" if zoom else ""
        return (f"[{label_in}]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920{zv},"
                f"setsar=1,fps={FPS},format=yuv420p[{label_out}]")
    return (f"[{label_in}]split=2[{label_out}a][{label_out}b];"
            f"[{label_out}a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
            f"boxblur=12:2,eq=brightness=-0.12,scale=1080:1920[{label_out}bg];"
            f"[{label_out}b]scale=1080:1920:force_original_aspect_ratio=decrease{z}[{label_out}fg];"
            f"[{label_out}bg][{label_out}fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS},format=yuv420p[{label_out}]")


AF = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"


def grab_frame(src, t, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0, t):.2f}", "-i", src, "-frames:v", "1", out], check=True)
    return out


def render(src, plan, out, *, hook_text, label, domain, end_lines, font_path, has_audio=True, vertical=False,
           accent=(229, 9, 20), crf=21, preset="veryfast"):
    out = Path(out)
    work = out.with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    hook_png = overlays.hook_overlay(hook_text, font_path, str(work / "hook.png"), accent)
    brand_png = overlays.brand_overlay(domain, label, font_path, str(work / "brand.png"), accent)
    frame = grab_frame(src, plan["end"] - 0.25, str(work / "cliff.jpg"))
    end_png = overlays.end_card(frame, end_lines, domain, font_path, str(work / "end.jpg"), accent)

    tl = plan["teaser_end"] - plan["teaser_start"]
    bl = plan["end"] - plan["start"]
    main_end = tl + bl
    total = main_end + END_CARD
    hook_until = tl + 2.3  # hook text stays a bit into the body

    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", f"{plan['teaser_start']:.2f}", "-t", f"{tl:.2f}", "-i", src,          # 0 teaser
           "-ss", f"{plan['start']:.2f}", "-t", f"{bl:.2f}", "-i", src,                  # 1 body
           "-loop", "1", "-framerate", str(FPS), "-t", f"{END_CARD}", "-i", end_png,     # 2 end card
           "-f", "lavfi", "-t", f"{END_CARD}", "-i", "anullsrc=r=44100:cl=stereo",       # 3 silence
           "-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", hook_png,   # 4
           "-loop", "1", "-framerate", str(FPS), "-t", f"{total:.2f}", "-i", brand_png,  # 5
           ]
    if not has_audio:
        cmd += ["-f", "lavfi", "-t", f"{main_end:.2f}", "-i", "anullsrc=r=44100:cl=stereo"]  # 6
    fc = [
        _fmt("0:v", "t0", zoom=True, vertical=vertical),
        f"[t0]fade=t=out:st={max(0, tl - 0.12):.2f}:d=0.12:color=white[v0]",
        _fmt("1:v", "b0", vertical=vertical),
        f"[b0]fade=t=in:st=0:d=0.15:color=white[v1]",
        f"[2:v]scale=1080:1920,setsar=1,fps={FPS},format=yuv420p,fade=t=in:st=0:d=0.25[v2]",
    ]
    if has_audio:
        fc += [f"[0:a]{AF},afade=t=out:st={max(0, tl - 0.15):.2f}:d=0.15[a0]", f"[1:a]{AF}[a1]"]
    else:
        fc += [f"[6:a]{AF},asplit=2[s0][s1]",
               f"[s0]atrim=0:{tl:.2f}[a0]",
               f"[s1]atrim=0:{bl:.2f},asetpts=PTS-STARTPTS[a1]"]
    fc += [
        f"[3:a]{AF}[a2]",
        "[v0][a0][v1][a1][v2][a2]concat=n=3:v=1:a=1[vc][ac]",
        f"[vc][4:v]overlay=0:0:enable='lt(t,{hook_until:.2f})'[vh]",
        f"[vh][5:v]overlay=0:0:enable='lt(t,{main_end:.2f})'[vb]",
        f"color=c=0x{accent[0]:02x}{accent[1]:02x}{accent[2]:02x}:s=1080x12:r={FPS}:d={total:.2f}[bar]",
        f"[vb][bar]overlay=x='-w+w*t/{main_end:.2f}':y=H-h:enable='lt(t,{main_end:.2f})'[vout]",
        "[ac]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[aout]",
    ]
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
            "-t", f"{total:.2f}", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {p.stderr[-2000:]}")
    cover = grab_frame(str(out), min(1.0, tl * 0.6), str(out.with_suffix(".jpg")))
    for f in work.iterdir():
        f.unlink()
    work.rmdir()
    return str(out), cover, total
