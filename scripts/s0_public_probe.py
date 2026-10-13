#!/usr/bin/env python3
"""Read-only S0 snapshot of public NodeSeek RSS and Telegram HTML.

This is NOT an authenticated Telethon/MTProto listener, and one snapshot
cannot measure new-post delivery delay. No user token/session is used.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

RSS_URL = "https://rss.nodeseek.com/"
TG_URL = "https://t.me/s/nodeseekc"
MAX_BYTES = 2_000_000
POST_PATH = re.compile(r"^/post-(\d+)(?:-\d+)?/?$")


def post_id_from_url(value: str) -> str | None:
    """Accept only canonical NodeSeek post links, never lookalike domains."""
    if not isinstance(value, str):
        return None
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("https", "http"):
        return None
    if (parts.hostname or "").lower() not in ("nodeseek.com", "www.nodeseek.com"):
        return None
    if port not in (None, 80, 443):
        return None
    match = POST_PATH.fullmatch(parts.path)
    return match.group(1) if match else None


class NodeSeekLinks(HTMLParser):
    """Parse public Telegram preview HTML without extracting message content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links_seen = 0
        self.post_ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if not href:
            return
        post_id = post_id_from_url(href)
        if post_id:
            self.links_seen += 1
            self.post_ids.add(post_id)


def telegram_ids(html: str) -> dict[str, object]:
    parser = NodeSeekLinks()
    parser.feed(html)
    parser.close()
    return {"linked_post_count": parser.links_seen, "unique_post_ids": sorted(parser.post_ids)}


def rss_ids(xml: bytes) -> dict[str, object]:
    """Extract RSS 2.0 and Atom post links with the standard XML parser."""
    root = ElementTree.fromstring(xml)
    root_type = root.tag.rsplit("}", 1)[-1].lower()
    ids: set[str] = set()
    entry_count = 0
    if root_type == "rss":
        items = root.findall("./channel/item")
        for item in items:
            entry_count += 1
            values = [item.findtext("link"), item.findtext("guid")]
            ids.update(pid for value in values if value and (pid := post_id_from_url(value)))
    elif root_type == "feed":
        ns = "{http://www.w3.org/2005/Atom}"
        for entry in root.findall(f"{ns}entry"):
            entry_count += 1
            values = [entry.findtext(f"{ns}id")]
            values.extend(link.get("href") for link in entry.findall(f"{ns}link"))
            ids.update(pid for value in values if value and (pid := post_id_from_url(value)))
    else:
        raise ValueError("unsupported rss/atom root")
    return {"feed_type": root_type, "entry_count": entry_count, "unique_post_ids": sorted(ids)}


def sample_source(name: str, url: str, timeout_seconds: float) -> dict[str, object]:
    observed_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    began = time.monotonic()
    result: dict[str, object] = {
        "source": name,
        "sample_started_utc": observed_at,
        "status": "unknown",
        "unique_post_ids": [],
    }
    req = Request(url, headers={"User-Agent": "SeekPulse-S0-FeasibilityProbe/0.1 (read-only)"})
    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            raw = response.read(MAX_BYTES + 1)
            content_type = response.headers.get("Content-Type", "")
            result["http_status"] = response.status
            result["content_type"] = content_type.split(";", 1)[0]
        if len(raw) > MAX_BYTES:
            raise ValueError("response too large")
        if name == "telegram_public_html":
            parsed = telegram_ids(raw.decode("utf-8", errors="replace"))
        else:
            parsed = rss_ids(raw)
        result.update(parsed)
        result["status"] = "ok" if parsed["unique_post_ids"] else "no_recognized_posts"
    except (HTTPError, URLError, OSError, TimeoutError, ValueError, ElementTree.ParseError) as exc:
        result["status"] = "error"
        # Never emit raw request URLs, response bodies, or exception details.
        result["error_type"] = type(exc).__name__
        if isinstance(exc, HTTPError):
            result["http_status"] = exc.code
    finally:
        result["elapsed_ms"] = round((time.monotonic() - began) * 1000)
    return result


def snapshot(timeout_seconds: float = 12.0) -> dict[str, object]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        tg = pool.submit(sample_source, "telegram_public_html", TG_URL, timeout_seconds)
        rss = pool.submit(sample_source, "rss", RSS_URL, timeout_seconds)
        sources = [tg.result(), rss.result()]
    tg_ids = set(sources[0]["unique_post_ids"])
    rss_ids_set = set(sources[1]["unique_post_ids"])
    return {
        "schema_version": 1,
        "probe": "PUBLIC_HTML_RSS_ONE_SHOT_NOT_MTPROTO_LATENCY",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sources,
        "common_post_ids": sorted(tg_ids & rss_ids_set),
        "latency_comparison": "UNMEASURED",
        "coverage_comparison": "UNMEASURED",
        "notes": [
            "Single snapshots and HTTP request timings do not measure actual post publication latency.",
            "Telegram public HTML is NOT the MTProto event stream; coverage and speed must be tested separately.",
            "Errors may reflect network restrictions, not missing NodeSeek posts.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write redacted JSON to a file; stdout if omitted")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()
    if not 2 <= args.timeout <= 30:
        parser.error("--timeout must be between 2 and 30 seconds")
    result = snapshot(args.timeout)
    data = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(data, encoding="utf-8")
        print(f"S0 snapshot: {args.output}; statuses: " + ", ".join(
            f"{x['source']}={x['status']}" for x in result["sources"]
        ))
    else:
        print(data, end="")
    return 0 if all(x["status"] == "ok" for x in result["sources"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
