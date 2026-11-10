"""Stage 1 - download the raw inputs and record where they came from."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import config

_TAG_RE = re.compile(r"/releases/download/([^/]+)/")
_HEADERS = {"User-Agent": "rescinded-daylight-saving-time (https://github.com/aaronperry-dev)"}


def resolve_release_tag(session: requests.Session, latest_url: str = config.TZ_LATEST_URL) -> str:
    """Follow only the first redirect of the 'latest' URL to learn the release tag."""
    r = session.get(latest_url, allow_redirects=False, timeout=30)
    loc = r.headers.get("Location", "")
    m = _TAG_RE.search(loc)
    if r.status_code not in (301, 302, 303, 307, 308) or not m:
        raise RuntimeError(f"Could not resolve latest timezone-boundary-builder release from {latest_url} (HTTP {r.status_code})")
    return m.group(1)


def _download(session: requests.Session, url: str, dest: Path, retries: int = 3) -> dict:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            sha = hashlib.sha256()
            size = 0
            with session.get(url, stream=True, timeout=(15, 120)) as r:
                r.raise_for_status()
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_content(1 << 20):
                        fh.write(chunk)
                        sha.update(chunk)
                        size += len(chunk)
            tmp.replace(dest)
            return {"url": url, "file": dest.name, "bytes": size, "sha256": sha.hexdigest()}
        except requests.RequestException as err:  # network hiccup: retry
            last_err = err
            print(f"  attempt {attempt}/{retries} failed for {url}: {err}")
    raise RuntimeError(f"Download failed: {url}") from last_err


def fetch_all(raw_dir: Path, tz_release: str | None = None, force: bool = False) -> dict:
    """Download the boundary zip + Natural Earth states into raw_dir (cached)."""
    raw_dir = Path(raw_dir)
    manifest_path = raw_dir / "manifest.json"
    tz_zip = raw_dir / config.TZ_ZIP_NAME
    ne_file = raw_dir / config.NE_STATES_NAME

    if not force and manifest_path.exists() and tz_zip.exists() and ne_file.exists():
        manifest = json.loads(manifest_path.read_text())
        if tz_release is None or manifest.get("tz_release") == tz_release:
            print(f"fetch: using cached inputs (tz release {manifest.get('tz_release')}); pass --force to refresh")
            return manifest

    session = requests.Session()
    session.headers.update(_HEADERS)
    tag = tz_release or resolve_release_tag(session)
    print(f"fetch: timezone-boundary-builder release {tag}")
    tz_info = _download(session, config.TZ_TAG_URL.format(tag=tag), tz_zip)
    print(f"fetch: Natural Earth admin-1 states")
    ne_info = _download(session, config.NE_STATES_URL, ne_file)

    manifest = {
        "retrieved_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tz_release": tag,
        "files": {"timezones": tz_info, "states": ne_info},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest
