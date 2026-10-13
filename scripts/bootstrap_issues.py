#!/usr/bin/env python3
"""Idempotent G0 issue bootstrap, dry-run by default.

The script never edits existing issues, pushes code, merges, or publishes.
It refuses to write if it cannot completely enumerate existing issues.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

SEED = Path(__file__).resolve().parents[1] / "docs" / "ISSUE_SEED.json"
DEFAULT_REPO = "Aspeternity/SeekPulse"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
TASK_PATTERN = re.compile(r"<!--\s*seekpulse-task:([A-Z][0-9]+-[0-9]+)\s*-->")


class BootstrapError(RuntimeError):
    pass


def load_seed(path: Path = SEED) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise BootstrapError("ISSUE_SEED.json must contain nonempty tasks list")
    keys = [task.get("key") for task in tasks]
    if any(not isinstance(key, str) or not re.fullmatch(r"[A-Z][0-9]+-[0-9]+", key) for key in keys):
        raise BootstrapError("Every task must have a stable key (e.g. G0-01)")
    if len(keys) != len(set(keys)):
        raise BootstrapError("Duplicate task keys in seed")
    for task in tasks:
        if not isinstance(task.get("title"), str) or not isinstance(task.get("body"), str):
            raise BootstrapError("Missing title/body in seed")
        if not isinstance(task.get("labels"), list):
            raise BootstrapError("Missing labels in seed")
    return tasks


def task_body(task: dict[str, Any]) -> str:
    return f"<!-- seekpulse-task:{task['key']} -->\n\n" + task["body"].rstrip() + "\n"


def recorded_keys(existing: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for row in existing:
        body = row.get("body") or ""
        for match in TASK_PATTERN.findall(body):
            keys.add(match)
    return keys


class GitHubWriteClient:
    def __init__(self, repo: str, token: str):
        self.repo = repo
        self.token = token

    def request(self, method: str, path: str, obj: dict[str, Any] | None = None, params=None):
        base = f"https://api.github.com/repos/{self.repo}{path}"
        if params:
            base += "?" + urlencode(params)
        body = None if obj is None else json.dumps(obj).encode("utf-8")
        req = Request(
            base,
            data=body,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "SeekPulse-IssueBootstrap/0.1",
                "Authorization": "Bearer " + self.token,
                **({"Content-Type": "application/json"} if body is not None else {}),
            },
            method=method,
        )
        try:
            with urlopen(req, timeout=20) as response:
                payload = json.load(response)
                links = response.headers.get("Link", "")
                return payload, links
        except HTTPError as exc:
            raise BootstrapError(f"GitHub HTTP {exc.code}, path={path}") from None
        except (URLError, OSError, ValueError, TimeoutError) as exc:
            raise BootstrapError(f"GitHub unavailable at {path}: {type(exc).__name__}") from None

    def get_all_issues(self) -> list[dict[str, Any]]:
        all_items = []
        page = 1
        while True:
            batch, links = self.request("GET", "/issues", params={"state": "all", "per_page": 100, "page": page})
            if not isinstance(batch, list):
                raise BootstrapError("Malformed GitHub issue list; refusing to write")
            all_items.extend(item for item in batch if "pull_request" not in item)
            if 'rel="next"' not in links:
                if len(batch) == 100 and not links:
                    raise BootstrapError("Cannot verify complete issue pagination; refusing to write")
                break
            page += 1
            if page > 100:
                raise BootstrapError("Too many issues; refusing to write")
        return all_items

    def label_exists(self, name: str) -> bool:
        # The write request only happens in an explicitly selected --apply run.
        try:
            self.request("GET", "/labels/" + quote(name, safe=""))
            return True
        except BootstrapError as error:
            if "HTTP 404" in str(error):
                return False
            raise


def bootstrap(client: GitHubWriteClient, tasks: list[dict[str, Any]]) -> list[str]:
    # All existing tasks are read first; errors abort before any mutation.
    existing = recorded_keys(client.get_all_issues())
    output = []
    pending = [task for task in tasks if task["key"] not in existing]
    labels = sorted({name for task in pending for name in task["labels"]})
    for label in labels:
        if not client.label_exists(label):
            client.request("POST", "/labels", {"name": label, "color": "596579", "description": "SeekPulse workflow label"})
    for task in pending:
        result, _ = client.request(
            "POST",
            "/issues",
            {"title": task["title"], "body": task_body(task), "labels": task["labels"]},
        )
        output.append(f"CREATED {task['key']} => {result.get('html_url', 'UNKNOWN_URL')}")
    for task in tasks:
        if task["key"] in existing:
            output.append(f"EXISTING {task['key']} (unchanged)")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--dry-run", action="store_true", help="Default: show task seed, no network writes")
    action.add_argument("--apply", action="store_true", help="Explicitly create missing GitHub issues")
    args = parser.parse_args(argv)
    if not REPO_PATTERN.fullmatch(args.repo):
        parser.error("--repo requires owner/name")
    tasks = load_seed()
    if not args.apply:
        print(f"DRY RUN: {len(tasks)} prepared issues for {args.repo}; no GitHub write performed")
        for task in tasks:
            print(f"  {task['key']}: {task['title']} [{', '.join(task['labels'])}]")
        return 0
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN or GH_TOKEN is required for --apply; no writes performed", file=sys.stderr)
        return 2
    print("GitHub write requested (--apply). Checking existing task identifiers first...")
    try:
        for line in bootstrap(GitHubWriteClient(args.repo, token), tasks):
            print(line)
    except BootstrapError as exc:
        print(f"ERROR: {exc}; do not infer which tasks were completed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
