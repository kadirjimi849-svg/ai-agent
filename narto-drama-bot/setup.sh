#!/usr/bin/env bash
# Ubuntu VPS setup:  bash setup.sh
set -e
cd "$(dirname "$0")"
sudo apt-get update
sudo apt-get install -y ffmpeg python3-venv python3-pip fonts-noto-core libraqm0 libfribidi0 libharfbuzz0b sqlite3
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
[ -f config.yaml ] || cp config.example.yaml config.yaml
[ -f catalog.yaml ] || cp catalog.example.yaml catalog.yaml
[ -f .env ] || { cp .env.example .env; chmod 600 .env; }
ls /usr/share/fonts/truetype/noto/NotoKufiArabic-Bold.ttf >/dev/null && echo "font OK"
.venv/bin/python -c "from PIL import features; print('Arabic shaping (raqm):', features.check('raqm'))"
echo
echo "Done. Next: edit .env, config.yaml, catalog.yaml then:"
echo "  .venv/bin/python -m bot sync"
echo "  .venv/bin/python -m bot produce"
echo "  pm2 start '.venv/bin/python -m bot run' --name drama-bot"
