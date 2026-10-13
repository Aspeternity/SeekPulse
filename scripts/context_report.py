#!/usr/bin/env python3
"""Read-only, evidence-oriented SeekPulse project handoff report.

Remote status always comes from live GitHub responses or is UNKNOWN; never
assume that a stale document, old workflow run, or missing API response means
successful CI/approval. No write API operations are performed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = "Aspeternity/SeekPulse"
REPO_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def extract_repo_from_remote(url: str | None) -> str | None:
    """Accept standard SSH or HTTPS GitHub Git remotes, not arbitrary URLs."""
    if not url:
        return None
    value = url.strip()
    ssh = re.fullmatch(r"git@github\.com:([^\s]+?)(?:\.git)?", value)
    if ssh:
        slug = ssh.group(1)
    else:
        parsed = urlsplit(value)
        if parsed.hostname != "github.com" or parsed.scheme not in {"http", "https", "ssh"}:
            return None
        slug = parsed.path.lstrip("/")
        if slug.endswith(".git"):
            slug = slug[:-4]
    return slug if REPO_PATTERN.fullmatch(slug) else None


def git_command(*args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=7,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def local_snapshot() -> dict[str, Any]:
    head = git_command("rev-parse", "HEAD")
    branch = git_command("branch", "--show-current")
    origin = git_command("remote", "get-url", "origin")
    status = git_command("status", "--porcelain=v1", "--untracked-files=normal")
    return {
        "verified": head is not None and status is not None,
        "head_sha": head or "UNKNOWN",
        "branch": branch or "UNKNOWN",
        "origin_repo": extract_repo_from_remote(origin) or "UNKNOWN",
        "working_tree": (
            "UNKNOWN" if status is None else "CLEAN" if not status else "DIRTY"
        ),
        "modified_paths_sample": status.splitlines()[:20] if status else [],
        "note": "Local working tree only; not proof of remote push or CI.",
    }


class GitHubReadError(RuntimeError):
    pass


class GitHubReader:
    def __init__(self, token: str | None = None) -> None:
        self.token = token

    def get(self, path: str, params: dict[str, str | int] | None = None) -> Any:
        uri = "https://api.github.com" + path
        if params:
            uri += "?" + urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SeekPulse-ContextReport/0.1",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        req = Request(uri, headers=headers, method="GET")
        try:
            with urlopen(req, timeout=12) as response:
                return json.load(response)
        except HTTPError as error:
            raise GitHubReadError(f"GitHub HTTP {error.code} ({path})") from None
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise GitHubReadError(
                f"GitHub request unavailable ({path}): {type(error).__name__}"
            ) from None


def classify_checks(check_data: Any, status_data: Any) -> dict[str, Any]:
    """Never call absent, partial, or still-running checks green."""
    if not isinstance(check_data, dict) or not isinstance(status_data, dict):
        return {"state": "UNKNOWN", "reason": "One or more check APIs unavailable"}
    checks = check_data.get("check_runs")
    if not isinstance(checks, list) or not isinstance(status_data.get("statuses"), list):
        return {"state": "UNKNOWN", "reason": "Malformed check response"}
    if int(check_data.get("total_count", 0)) > len(checks):
        return {"state": "UNKNOWN", "reason": "Check results are paginated/incomplete"}
    detail = [
        {"name": row.get("name"), "status": row.get("status"), "conclusion": row.get("conclusion")}
        for row in checks
    ]
    contexts = status_data.get("statuses", [])
    failed = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
    if any(r.get("conclusion") in failed for r in checks) or any(
        r.get("state") in {"failure", "error"} for r in contexts
    ):
        state = "FAILED"
    elif not checks and not contexts:
        state = "UNKNOWN"
    elif any(r.get("status") != "completed" for r in checks) or any(
        r.get("state") == "pending" for r in contexts
    ):
        state = "PENDING"
    elif any(r.get("conclusion") not in {"success", "skipped", "neutral"} for r in checks):
        state = "UNKNOWN"
    elif any(r.get("state") != "success" for r in contexts):
        state = "UNKNOWN"
    else:
        state = "OBSERVED_CHECKS_PASSING"
    return {
        "state": state,
        "sha_specific": True,
        "check_count": len(checks),
        "status_context_count": len(contexts),
        "checks": detail[:30],
        "note": "Observed checks only; required-branch-rule coverage and real-device acceptance are separate.",
    }


def commit_checks(reader: GitHubReader, repo: str, sha: str) -> dict[str, Any]:
    base = f"/repos/{repo}/commits/{sha}"
    try:
        check_data = reader.get(base + "/check-runs", {"per_page": 100})
        statuses = reader.get(base + "/status")
        return classify_checks(check_data, statuses)
    except GitHubReadError as error:
        return {"state": "UNKNOWN", "reason": str(error)}


def live_snapshot(
    reader: GitHubReader, repo: str, issue_number: int | None, limit: int
) -> dict[str, Any]:
    prefix = f"/repos/{repo}"
    meta = reader.get(prefix)
    branch = meta.get("default_branch", "main")
    branch_info = reader.get(prefix + "/branches/" + quote(branch, safe=""))
    sha = branch_info.get("commit", {}).get("sha")
    if not sha:
        raise GitHubReadError("Default branch SHA missing from GitHub response")
    issues = reader.get(prefix + "/issues", {"state": "open", "per_page": 100})
    pulls = reader.get(prefix + "/pulls", {"state": "open", "per_page": 100})
    if not isinstance(issues, list) or not isinstance(pulls, list):
        raise GitHubReadError("GitHub issue/PR listing format invalid")
    true_issues = [i for i in issues if "pull_request" not in i]
    issues_partial = len(issues) >= 100
    pulls_partial = len(pulls) >= 100
    current_issue: dict[str, Any] | None = None
    if issue_number is not None:
        row = reader.get(prefix + f"/issues/{issue_number}")
        current_issue = {
            "number": row.get("number"),
            "title": row.get("title"),
            "state": row.get("state"),
            "url": row.get("html_url"),
            "assignees": [u.get("login") for u in row.get("assignees", [])],
            "labels": [x.get("name") for x in row.get("labels", [])],
            "body_excerpt": (row.get("body") or "")[:2500],
        }
    selected_pulls = [
        {
            "number": p.get("number"),
            "title": p.get("title"),
            "head_sha": (p.get("head") or {}).get("sha"),
            "head_ref": (p.get("head") or {}).get("ref"),
            "base_ref": (p.get("base") or {}).get("ref"),
            "draft": p.get("draft"),
            "url": p.get("html_url"),
            "author": (p.get("user") or {}).get("login"),
        }
        for p in pulls[:limit]
    ]
    for p in selected_pulls:
        p["ci"] = (
            commit_checks(reader, repo, p["head_sha"])
            if p["head_sha"]
            else {"state": "UNKNOWN", "reason": "PR head SHA missing"}
        )
    return {
        "verification": "LIVE_GITHUB_READ",
        "repo": meta.get("full_name", repo),
        "repo_url": meta.get("html_url"),
        "default_branch": branch,
        "default_branch_sha": sha,
        "default_branch_checks": commit_checks(reader, repo, sha),
        "open_issues_sample": [
            {"number": i.get("number"), "title": i.get("title"), "url": i.get("html_url")}
            for i in true_issues[:limit]
        ],
        "issues_listing_may_be_partial": issues_partial,
        "open_prs_sample": selected_pulls,
        "prs_listing_may_be_partial": pulls_partial,
        "specific_issue": current_issue,
    }


def recorded_authorization() -> dict[str, str]:
    """Read the latest *recorded* approval, never guess newer approval from chat."""
    path = ROOT / "docs" / "APPROVALS.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        events = payload.get("events", [])
        if not isinstance(events, list) or not events:
            raise ValueError("No approval records")
        latest = events[-1]
        stage = latest["authorized_stage"]
        plan = latest["approved_plan"]
        date = latest["date"]
        restricted = ", ".join(latest.get("not_authorized", []))
        return {
            "state": "RECORDED_ONLY",
            "summary": f"{plan}, stage {stage}, recorded {date}; NOT authorized: {restricted}",
            "event_id": latest.get("event_id", "UNKNOWN"),
            "source": str(path.relative_to(ROOT)),
            "caution": "The latest user instruction may supersede this recorded snapshot.",
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {
            "state": "UNKNOWN",
            "summary": "UNKNOWN (no parseable local approval record)",
            "caution": "Never infer authorization when approval record is unavailable.",
        }


def collect_report(
    repo: str = DEFAULT_REPO,
    issue_number: int | None = None,
    offline: bool = False,
    limit: int = 10,
    reader: GitHubReader | None = None,
) -> dict[str, Any]:
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError("Repository must have owner/name format")
    approval = recorded_authorization()
    result: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "requested_repo": repo,
        "recorded_approval": approval,
        "local": local_snapshot(),
        "github": {"verification": "UNKNOWN", "reason": "No live request performed"},
        "cautions": [
            "GitHub SHA/PR/CI must be checked live before modifying code.",
            "A green CI check never means real-device acceptance, merge approval, or release approval.",
            "Issue ownership and actual user authorization require independent verification.",
        ],
    }
    if offline:
        result["github"] = {
            "verification": "UNKNOWN",
            "reason": "--offline: no real-time GitHub verification performed",
        }
    else:
        try:
            result["github"] = live_snapshot(
                reader or GitHubReader(os.environ.get("GITHUB_TOKEN")),
                repo,
                issue_number,
                max(1, min(limit, 30)),
            )
        except GitHubReadError as error:
            result["github"] = {"verification": "UNKNOWN", "reason": str(error)}
    return result


def render_markdown(report: dict[str, Any]) -> str:
    local = report["local"]
    remote = report["github"]
    lines = [
        "# SeekPulse 开发交接报告（只读快照）",
        "",
        f"- 生成时间 UTC：{report['generated_at_utc']}",
        f"- 目标仓库：`{report['requested_repo']}`",
        f"- 最近记录的授权：{report['recorded_approval'].get('summary', 'UNKNOWN')}",
        "- 授权来源：`docs/APPROVALS.json` / `docs/APPROVALS.md`；仍需核对最新用户指令",
        f"- 本地分支 / SHA：`{local['branch']}` / `{local['head_sha']}`",
        f"- 本地工作区：**{local['working_tree']}**",
        f"- 远端核验状态：**{remote.get('verification', 'UNKNOWN')}**",
    ]
    if remote.get("verification") == "LIVE_GITHUB_READ":
        lines.extend([
            f"- 远端默认分支：`{remote['default_branch']}`",
            f"- 远端默认分支 SHA：`{remote['default_branch_sha']}`",
            "- 该 SHA 的检查观察："
            f"**{remote['default_branch_checks']['state']}**（不是实机验收）",
            "",
            "## 开放 PR（带 PR HEAD SHA 的检查观察）",
        ])
        for p in remote["open_prs_sample"]:
            lines.append(
                f"- #{p['number']} [{p['title']}]({p['url']}) — "
                f"`{p['head_ref']}` / `{p['head_sha']}` / "
                f"{p['ci']['state']} / draft={p['draft']}"
            )
        lines.append("")
        lines.append("## 开放 Issue（样本）")
        for i in remote["open_issues_sample"]:
            lines.append(f"- #{i['number']} [{i['title']}]({i['url']})")
        if remote.get("issues_listing_may_be_partial") or remote.get("prs_listing_may_be_partial"):
            lines.append("- **警告：Issue/PR 列表可能分页不完整，不可宣称这是全部任务。**")
        if remote.get("specific_issue"):
            i = remote["specific_issue"]
            lines.append(f"\n## 当前 Issue #{i['number']}：{i['title']}")
            lines.append(f"- 状态：{i['state']}；指定负责人：{i['assignees']}")
            lines.append(f"- 链接：{i['url']}")
    else:
        lines.append(f"- 未核实原因：{remote.get('reason', 'UNKNOWN')}")
    lines.extend([
        "",
        "## 进入下一步前的阻断检查",
        "",
        "- 重新核实 `docs/APPROVALS.md`、任务唯一负责人、当前 HEAD 对应完整 CI、实机验收和用户授权。",
        "- 未核实的数据一律当作 UNKNOWN，不得自动开发下一阶段或合并/发布。",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub owner/repository")
    parser.add_argument("--issue", type=int, help="Issue number to inspect")
    parser.add_argument("--offline", action="store_true", help="Skip live GitHub calls")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--limit", type=int, default=10, help="Maximum listed issues and PRs")
    parser.add_argument("--output", help="Optional output file; default prints to stdout")
    args = parser.parse_args(argv)
    if args.issue is not None and args.issue < 1:
        parser.error("--issue must be positive")
    try:
        report = collect_report(args.repo, args.issue, args.offline, args.limit)
    except ValueError as error:
        parser.error(str(error))
    data = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.format == "json"
        else render_markdown(report)
    )
    if args.output:
        Path(args.output).write_text(data, encoding="utf-8")
    else:
        sys.stdout.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
