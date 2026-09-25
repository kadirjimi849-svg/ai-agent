"""MinIO / S3 access: list episodes, download, upload rendered clips, presigned URLs."""
import re
import shutil
from pathlib import Path

from .config import secret

VIDEO_EXT = (".mp4", ".mkv", ".mov", ".m4v", ".webm", ".ts")


def ep_number(name: str) -> int | None:
    """'ep-012.mp4', 'E12', 'الحلقة 12', '12.mp4' -> 12"""
    stem = Path(name).stem
    m = re.search(r"(?:ep|e|episode|حلقة|الحلقة)[\s_\-\.]*(\d{1,4})", stem, re.I) or re.search(r"(\d{1,4})(?!.*\d)", stem)
    return int(m.group(1)) if m else None


class Storage:
    def __init__(self, cfg):
        self.cfg = cfg.get("minio") or {}
        self._s3 = None

    @property
    def s3(self):
        if self._s3 is None:
            import boto3
            from botocore.client import Config as BotoCfg
            self._s3 = boto3.client(
                "s3",
                endpoint_url=self.cfg["endpoint"],
                aws_access_key_id=secret(self.cfg.get("access_key_env", "MINIO_ACCESS_KEY")),
                aws_secret_access_key=secret(self.cfg.get("secret_key_env", "MINIO_SECRET_KEY")),
                region_name=self.cfg.get("region", "us-east-1"),
                config=BotoCfg(signature_version="s3v4", s3={"addressing_style": "path"}),
            )
        return self._s3

    # ---------- listing ----------
    def list_episodes(self, source: dict) -> list[tuple[int, str]]:
        """Returns sorted [(ep_no, src)] where src is 's3://bucket/key' or a local path."""
        out = []
        if source.get("type", "s3") == "local":
            for p in sorted(Path(source["dir"]).iterdir()):
                if p.suffix.lower() in VIDEO_EXT and (n := ep_number(p.name)) is not None:
                    out.append((n, str(p)))
        else:
            bucket, prefix = source["bucket"], source.get("prefix", "")
            for obj in self._iter(bucket, prefix):
                key = obj["Key"]
                if key.lower().endswith(VIDEO_EXT) and (n := ep_number(key)) is not None:
                    out.append((n, f"s3://{bucket}/{key}"))
        dedup = {}
        for n, s in out:
            dedup.setdefault(n, s)
        return sorted(dedup.items())

    def _iter(self, bucket, prefix, delimiter=None):
        kw = {"Bucket": bucket, "Prefix": prefix}
        if delimiter:
            kw["Delimiter"] = delimiter
        for page in self.s3.get_paginator("list_objects_v2").paginate(**kw):
            if delimiter:
                yield from page.get("CommonPrefixes", [])
            else:
                yield from page.get("Contents", [])

    def scan(self, bucket, prefix=""):
        """Top-level folders under prefix -> helps build catalog.yaml."""
        res = []
        for cp in self._iter(bucket, prefix, "/"):
            sub = cp["Prefix"]
            eps = self.list_episodes({"bucket": bucket, "prefix": sub})
            res.append((sub, len(eps)))
        return res

    # ---------- files ----------
    def fetch(self, src: str, cache_dir: str) -> str:
        if not src.startswith("s3://"):
            return src
        bucket, key = src[5:].split("/", 1)
        dst = Path(cache_dir) / "src" / bucket / key
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(dst.suffix + ".part")
            self.s3.download_file(bucket, key, str(tmp))
            shutil.move(tmp, dst)
        return str(dst)

    def upload(self, path: str, key: str, content_type="video/mp4") -> str | None:
        bucket = self.cfg.get("clips_bucket")
        if not bucket:
            return None
        self.s3.upload_file(path, bucket, key, ExtraArgs={"ContentType": content_type})
        return key

    def public_url(self, key: str, hours=6) -> str:
        bucket = self.cfg["clips_bucket"]
        if base := self.cfg.get("public_base_url"):
            return f"{base.rstrip('/')}/{bucket}/{key}"
        return self.s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key},
                                              ExpiresIn=hours * 3600)

    @staticmethod
    def prune_cache(cache_dir: str, max_gb: float):
        files = sorted((p for p in Path(cache_dir, "src").rglob("*") if p.is_file()), key=lambda p: p.stat().st_atime)
        total = sum(p.stat().st_size for p in files)
        while files and total > max_gb * 1024 ** 3:
            p = files.pop(0)
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
