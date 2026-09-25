"""CLI:  python -m bot <command>

  web [--port 8080]        dashboard + autopilot (connect accounts, library, settings, log)
  autopilot [--once]       autopilot without the dashboard (uses the settings saved from the dashboard)
  library [ROOT]           scan the series folder (default: library_root setting, e.g. D:\\narto-drama)
  sync                     read catalog.yaml, list episodes from MinIO/local
  scan BUCKET [PREFIX]     show folders in MinIO to help write catalog.yaml
  produce [--drama S] [--ep N] [--count N] [--lang ar]
  preview FILE [--hook "..."]   render test clips from any local video (no DB, no upload)
  publish ACCOUNT [--clip ID] [--live]
  check                    verify tokens of every account
  stats                    pull views/likes now
  report                   what works: dramas, hook styles, accounts
  clips                    list ready clips
  run                      daemon: produce + publish on schedule + learn
"""
import argparse
import json
from pathlib import Path

from .config import load


def main():
    import sys
    for stream in (sys.stdout, sys.stderr):  # Arabic output on Windows consoles
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="bot")
    ap.add_argument("--config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync"); s.add_argument("--catalog", default="catalog.yaml")
    s = sub.add_parser("scan"); s.add_argument("bucket"); s.add_argument("prefix", nargs="?", default="")
    s = sub.add_parser("produce"); s.add_argument("--drama"); s.add_argument("--ep", type=int)
    s.add_argument("--count", type=int); s.add_argument("--lang", action="append")
    s = sub.add_parser("preview"); s.add_argument("file"); s.add_argument("--hook", default="لن تصدق ما سيحدث بعد ذلك")
    s.add_argument("--title", default="مانودراما"); s.add_argument("--count", type=int, default=2)
    s = sub.add_parser("publish"); s.add_argument("account"); s.add_argument("--clip", type=int)
    s.add_argument("--live", action="store_true", help="really post even if dry_run: true")
    sub.add_parser("check"); sub.add_parser("stats"); sub.add_parser("report"); sub.add_parser("run")
    sub.add_parser("clips")
    s = sub.add_parser("web"); s.add_argument("--port", type=int, default=8080); s.add_argument("--no-browser", action="store_true")
    s = sub.add_parser("autopilot"); s.add_argument("--once", action="store_true"); s.add_argument("--no-publish", action="store_true")
    s = sub.add_parser("library"); s.add_argument("root", nargs="?")
    a = ap.parse_args()
    cfg = load(a.config)

    if a.cmd == "web":
        from .web import serve
        serve(cfg, a.port, open_browser=not a.no_browser)
        return

    if a.cmd == "preview":
        from . import analyzer, editor
        from .copywriter import Copywriter
        an = analyzer.analyze(a.file)
        plans = analyzer.plan_clips(an, count=a.count)
        print(json.dumps(plans, indent=1))
        vertical = bool(an.get("height") and an["height"] / an["width"] > 1.5)
        font = (cfg.get("render") or {}).get("font")
        for i, p in enumerate(plans):
            out = Path(cfg["paths"]["clips"]) / f"preview_{Path(a.file).stem}_{i}.mp4"
            editor.render(a.file, p, out, hook_text=a.hook, label=f"{a.title} • الحلقة 1",
                          domain=cfg.get("domain") or "",
                          end_lines=(*Copywriter.end_lines("ar", bool(cfg.get("domain"))), a.title), font_path=font,
                          has_audio=an["has_audio"], vertical=vertical)
            print("->", out)
        return

    from .runner import Bot
    bot = Bot(cfg)
    accounts = {x["name"]: x for x in cfg.get("accounts", [])}

    if a.cmd == "sync":
        bot.sync(a.catalog)
    elif a.cmd == "scan":
        for prefix, n in bot.storage.scan(a.bucket, a.prefix):
            print(f"{n:4d} episodes  s3://{a.bucket}/{prefix}")
    elif a.cmd == "produce":
        print(bot.produce(a.drama, a.ep, a.count, a.lang))
    elif a.cmd == "publish":
        print(bot.publish_next(accounts[a.account], a.clip, dry=False if a.live else None))
    elif a.cmd == "check":
        from .publishers import get_publisher
        for name, acc in accounts.items():
            try:
                print(f"✔ {name:<20} {get_publisher(acc['platform'], acc, bot.ctx).check()}")
            except Exception as e:
                print(f"✘ {name:<20} {e}")
    elif a.cmd == "stats":
        print(bot.brain.refresh_stats(), "posts updated")
    elif a.cmd == "report":
        print(bot.brain.report())
    elif a.cmd == "clips":
        for r in bot.db.q("""SELECT c.id,c.lang,c.hook_id,c.hook_text,e.drama_slug,e.ep_no,c.start,c.end,
                             (SELECT GROUP_CONCAT(account) FROM posts p WHERE p.clip_id=c.id) used
                             FROM clips c JOIN episodes e ON e.id=c.episode_id ORDER BY c.id DESC LIMIT 50"""):
            print(dict(r))
    elif a.cmd == "run":
        bot.run_forever()
    elif a.cmd in ("autopilot", "library"):
        import time
        from . import library, logs
        from .autopilot import Autopilot
        logs.set_file(Path(cfg["paths"]["data"]) / "bot.log")
        pilot = Autopilot(bot)
        if a.cmd == "library":
            print(library.scan(bot.db, a.root or pilot.s["library_root"]))
        elif a.once:
            print(pilot.cycle(publish=not a.no_publish))
        else:
            pilot.enable(True)
            pilot.start()
            while True:
                time.sleep(3600)


if __name__ == "__main__":
    main()
