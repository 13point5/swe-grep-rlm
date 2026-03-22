#!/usr/bin/env python3
"""Collect PR-level code retrieval examples from GitHub.

The collector favors merged PRs that touch multiple non-test files, and it
stores enough metadata to support downstream retrieval benchmarks or reward
construction.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Optional


DEFAULT_REPOS = [
    "django/django",
    "psf/requests",
    "pallets/flask",
    "pytest-dev/pytest",
    "scikit-learn/scikit-learn",
    "matplotlib/matplotlib",
    "pandas-dev/pandas",
    "sympy/sympy",
    "ansible/ansible",
    "huggingface/transformers",
    "pydata/xarray",
    "sphinx-doc/sphinx",
    "celery/celery",
    "fastapi/fastapi",
    "python/cpython",
]

TEST_DIR_NAMES = {
    "test",
    "tests",
    "__tests__",
    "spec",
    "specs",
    "testing",
}

TEST_FILE_PATTERNS = (
    re.compile(r"(^|[._-])(test|spec)([._-]|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)(test_[^/]+|[^/]+_test)\.[A-Za-z0-9]+$", re.IGNORECASE),
    re.compile(r"(?:^|/)([^/]+)\.spec\.[A-Za-z0-9]+$", re.IGNORECASE),
    re.compile(r"(?:^|/)([^/]+)\.test\.[A-Za-z0-9]+$", re.IGNORECASE),
)

LOCAL_ISSUE_REF_RE = re.compile(
    r"(?i)\b(?:fix(?:e[sd])?|close[sd]?|resolve[sd]?|refs?|references?|related to)\b[^\n\r]{0,120}?(?:issue\s+)?#(\d+)"
)
CROSS_REPO_ISSUE_REF_RE = re.compile(
    r"(?i)\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)\b"
)


@dataclass
class LinkedIssue:
    number: int
    title: str
    body: str
    url: str
    source: str


@dataclass
class PRExample:
    repo: str
    pr_number: int
    pr_url: str
    pr_title: str
    pr_body: str
    merged_at: str
    query_text: str
    query_source: str
    linked_issues: list[dict[str, Any]]
    file_count: int
    non_test_file_count: int
    test_file_count: int
    files: list[str]
    non_test_files: list[str]
    test_files: list[str]
    additions: int
    deletions: int
    source: str = "github_pr"


class GHClient:
    """GraphQL-backed GitHub client via gh CLI."""

    def __init__(self, tokenless_fallback: bool = True) -> None:
        self.gh = shutil.which("gh")
        self.tokenless_fallback = tokenless_fallback
        self.use_gh = bool(self.gh) and self._gh_authenticated()

    def _gh_authenticated(self) -> bool:
        if not self.gh:
            return False
        proc = subprocess.run(
            [self.gh, "auth", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode == 0

    def repo_pull_requests(
        self,
        repo: str,
        *,
        page_size: int,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        if self.use_gh:
            return self._repo_pull_requests_graphql(repo, page_size=page_size, cursor=cursor)
        if not self.tokenless_fallback:
            raise RuntimeError("gh CLI is unavailable or not authenticated")
        return self._repo_pull_requests_rest(repo, page_size=page_size, cursor=cursor)

    def pull_request_files(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        if self.use_gh:
            return self._pull_request_files_gh(repo, pr_number)
        if not self.tokenless_fallback:
            raise RuntimeError("gh CLI is unavailable or not authenticated")
        return self._pull_request_files_rest(repo, pr_number)

    def _repo_pull_requests_graphql(
        self,
        repo: str,
        *,
        page_size: int,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        owner, name = repo.split("/", 1)
        query = """
        query($owner:String!, $name:String!, $page_size:Int!, $cursor:String) {
          repository(owner:$owner, name:$name) {
            pullRequests(
              first:$page_size,
              after:$cursor,
              states:MERGED,
              orderBy:{field:UPDATED_AT, direction:DESC}
            ) {
              nodes {
                number
                title
                url
                mergedAt
                bodyText
                closingIssuesReferences(first:10) {
                  nodes {
                    number
                    title
                    bodyText
                    url
                  }
                }
                files(first:100) {
                  totalCount
                  nodes {
                    path
                    additions
                    deletions
                  }
                }
              }
              pageInfo {
                hasNextPage
                endCursor
              }
            }
          }
        }
        """
        payload = _gh_graphql(query, owner=owner, name=name, page_size=page_size, cursor=cursor)
        repo_data = payload.get("data", {}).get("repository")
        if not repo_data:
            raise RuntimeError(f"No repository data returned for {repo}")
        pulls = repo_data["pullRequests"]
        return {
            "nodes": pulls["nodes"],
            "page_info": pulls["pageInfo"],
        }

    def _repo_pull_requests_rest(
        self,
        repo: str,
        *,
        page_size: int,
        cursor: Optional[str] = None,
    ) -> dict[str, Any]:
        # Best-effort public fallback. This path is slower and does not expose
        # closingIssuesReferences, so PR body heuristics matter more.
        page = int(cursor or "1")
        url = f"https://api.github.com/repos/{repo}/pulls?state=closed&per_page={page_size}&page={page}"
        data = _http_json(url)
        nodes = []
        for item in data:
            if not item.get("merged_at"):
                continue
            files = _http_json(f"https://api.github.com/repos/{repo}/pulls/{item['number']}/files?per_page=100")
            nodes.append(
                {
                    "number": item["number"],
                    "title": item.get("title", ""),
                    "url": item.get("html_url", ""),
                    "mergedAt": item.get("merged_at", ""),
                    "bodyText": item.get("body", "") or "",
                    "closingIssuesReferences": {"nodes": []},
                    "files": {
                        "totalCount": len(files),
                        "nodes": [
                            {
                                "path": f.get("filename", ""),
                                "additions": int(f.get("additions", 0)),
                                "deletions": int(f.get("deletions", 0)),
                            }
                            for f in files
                        ],
                    },
                }
            )
        has_next_page = len(data) == page_size
        return {
            "nodes": nodes,
            "page_info": {
                "hasNextPage": has_next_page,
                "endCursor": str(page + 1) if has_next_page else None,
            },
        }

    def _pull_request_files_gh(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        gh = shutil.which("gh")
        if not gh:
            raise RuntimeError("gh CLI is not installed")

        proc = subprocess.run(
            [
                gh,
                "api",
                f"repos/{repo}/pulls/{pr_number}/files",
                "--paginate",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or f"gh pull files query failed for {repo}#{pr_number}")

        payload = proc.stdout.strip()
        if not payload:
            return []

        pages: list[Any] = []
        decoder = json.JSONDecoder()
        idx = 0
        while idx < len(payload):
            while idx < len(payload) and payload[idx].isspace():
                idx += 1
            if idx >= len(payload):
                break
            page, consumed = decoder.raw_decode(payload, idx)
            pages.append(page)
            idx = consumed

        files: list[dict[str, Any]] = []
        for page in pages:
            if not isinstance(page, list):
                continue
            for file_info in page:
                files.append(
                    {
                        "path": file_info.get("filename", ""),
                        "additions": int(file_info.get("additions", 0) or 0),
                        "deletions": int(file_info.get("deletions", 0) or 0),
                    }
                )
        return files

    def _pull_request_files_rest(self, repo: str, pr_number: int) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = _http_json(
                f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?per_page=100&page={page}"
            )
            if not batch:
                break
            for file_info in batch:
                files.append(
                    {
                        "path": file_info.get("filename", ""),
                        "additions": int(file_info.get("additions", 0) or 0),
                        "deletions": int(file_info.get("deletions", 0) or 0),
                    }
                )
            if len(batch) < 100:
                break
            page += 1
        return files


def _gh_graphql(query: str, **variables: Any) -> dict[str, Any]:
    gh = shutil.which("gh")
    if not gh:
        raise RuntimeError("gh CLI is not installed")

    args = [gh, "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if value is None:
            continue
        args.extend(["-F", f"{key}={value}"])

    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "gh graphql query failed")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse gh graphql JSON output") from exc


def _http_json(url: str) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "swe-grep-rlm-data-collection",
        },
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - trusted GitHub API URL
        return json.loads(resp.read().decode("utf-8"))


def load_repos(paths: list[str]) -> list[str]:
    repos: list[str] = []
    for item in paths:
        if not item:
            continue
        p = Path(item)
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                repos.append(stripped)
        else:
            repos.append(item.strip())
    seen = set()
    ordered = []
    for repo in repos:
        if repo in seen:
            continue
        seen.add(repo)
        ordered.append(repo)
    return ordered


def is_test_path(path: str) -> bool:
    norm = path.replace("\\", "/").strip("/")
    if not norm:
        return False
    parts = [part.lower() for part in norm.split("/")]
    if any(part in TEST_DIR_NAMES for part in parts):
        return True
    name = parts[-1]
    if any(pattern.search(norm) for pattern in TEST_FILE_PATTERNS):
        return True
    if name.startswith("test_") or name.endswith("_test.py") or name.endswith("_test.ts"):
        return True
    return False


def classify_files(files: list[dict[str, Any]]) -> tuple[list[str], list[str], int, int]:
    all_files: list[str] = []
    non_test_files: list[str] = []
    test_files: list[str] = []
    additions = 0
    deletions = 0

    for file_info in files:
        path = file_info.get("path", "")
        if not path:
            continue
        all_files.append(path)
        additions += int(file_info.get("additions", 0) or 0)
        deletions += int(file_info.get("deletions", 0) or 0)
        if is_test_path(path):
            test_files.append(path)
        else:
            non_test_files.append(path)

    return all_files, non_test_files, test_files, additions, deletions


def extract_linked_issues(
    repo: str,
    pr_body: str,
    closing_refs: list[dict[str, Any]],
) -> tuple[list[LinkedIssue], str, str]:
    linked_map: dict[tuple[int, str], LinkedIssue] = {}

    def upsert_issue(number: int, title: str, body: str, url: str, source: str) -> None:
        key = (number, url or f"https://github.com/{repo}/issues/{number}")
        existing = linked_map.get(key)
        if existing is None:
            linked_map[key] = LinkedIssue(
                number=number,
                title=title,
                body=body,
                url=key[1],
                source=source,
            )
            return

        if not existing.title and title:
            existing.title = title
        if not existing.body and body:
            existing.body = body
        sources = set(existing.source.split("+"))
        sources.add(source)
        existing.source = "+".join(sorted(sources))

    for issue in closing_refs:
        number = issue.get("number")
        if not number or int(number) <= 0:
            continue
        upsert_issue(
            int(number),
            issue.get("title", ""),
            issue.get("bodyText", "") or "",
            issue.get("url", ""),
            "closing_ref",
        )

    for match in CROSS_REPO_ISSUE_REF_RE.finditer(pr_body or ""):
        ref_repo = match.group(1)
        if ref_repo != repo:
            continue
        number = int(match.group(2))
        if number <= 0:
            continue
        upsert_issue(
            number,
            "",
            "",
            f"https://github.com/{repo}/issues/{number}",
            "body_ref",
        )

    for match in LOCAL_ISSUE_REF_RE.finditer(pr_body or ""):
        number = int(match.group(1))
        if number <= 0:
            continue
        upsert_issue(
            number,
            "",
            "",
            f"https://github.com/{repo}/issues/{number}",
            "body_keyword",
        )

    linked = sorted(linked_map.values(), key=lambda issue: issue.number)

    query_source = "closing_issue_titles"
    issue_texts = []
    for issue in linked:
        text = "\n\n".join(part for part in [issue.title.strip(), issue.body.strip()] if part)
        if text:
            issue_texts.append(text)
    if issue_texts:
        query_source = "closing_issue_text"
        query_text = "\n\n".join(dict.fromkeys(issue_texts))
    else:
        query_source = "pr_title_body"
        query_text = pr_body.strip()

    return linked, query_text, query_source


def build_example(
    client: GHClient,
    repo: str,
    pr_node: dict[str, Any],
    *,
    min_non_test_files: int,
) -> Optional[PRExample]:
    files_conn = pr_node.get("files") or {}
    files = files_conn.get("nodes") or []
    total_files = int(files_conn.get("totalCount", len(files)) or len(files))
    if total_files > len(files):
        files = client.pull_request_files(repo, int(pr_node["number"]))
    all_files, non_test_files, test_files, additions, deletions = classify_files(files)

    linked_issues, query_text, query_source = extract_linked_issues(
        repo, pr_node.get("bodyText", ""), (pr_node.get("closingIssuesReferences") or {}).get("nodes", [])
    )

    non_test_count = len(non_test_files)
    if non_test_count < min_non_test_files:
        return None

    if not query_text.strip():
        return None

    return PRExample(
        repo=repo,
        pr_number=int(pr_node["number"]),
        pr_url=pr_node.get("url", ""),
        pr_title=pr_node.get("title", ""),
        pr_body=pr_node.get("bodyText", "") or "",
        merged_at=pr_node.get("mergedAt", "") or "",
        query_text=query_text.strip(),
        query_source=query_source,
        linked_issues=[asdict(issue) for issue in linked_issues],
        file_count=len(all_files),
        non_test_file_count=non_test_count,
        test_file_count=len(test_files),
        files=all_files,
        non_test_files=non_test_files,
        test_files=test_files,
        additions=additions,
        deletions=deletions,
    )


def collect_repo(
    client: GHClient,
    repo: str,
    *,
    page_size: int,
    max_pages: int,
    min_non_test_files: int,
    max_non_test_files: int,
    max_records: Optional[int],
) -> list[PRExample]:
    cursor: Optional[str] = None
    page = 0
    collected: list[PRExample] = []

    while page < max_pages:
        page += 1
        payload = client.repo_pull_requests(repo, page_size=page_size, cursor=cursor)
        nodes = payload["nodes"]
        for pr_node in nodes:
            example = build_example(client, repo, pr_node, min_non_test_files=min_non_test_files)
            if not example:
                continue
            if not (min_non_test_files <= example.non_test_file_count <= max_non_test_files):
                continue
            if not example.linked_issues:
                continue
            collected.append(example)
            if max_records is not None and len(collected) >= max_records:
                return collected

        page_info = payload["page_info"]
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    return collected


def write_jsonl(path: str, rows: list[PRExample]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(asdict(row), ensure_ascii=True, sort_keys=True) + "\n")


def write_csv(path: str, rows: list[PRExample]) -> None:
    fieldnames = list(asdict(rows[0]).keys()) if rows else [
        "repo",
        "pr_number",
        "pr_url",
        "pr_title",
        "pr_body",
        "merged_at",
        "query_text",
        "query_source",
        "linked_issues",
        "file_count",
        "non_test_file_count",
        "test_file_count",
        "files",
        "non_test_files",
        "test_files",
        "additions",
        "deletions",
        "source",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            data = asdict(row)
            for key in ("linked_issues", "files", "non_test_files", "test_files"):
                data[key] = json.dumps(data[key], ensure_ascii=True)
            writer.writerow(data)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect multi-file PR examples from GitHub.")
    parser.add_argument("--repos-file", action="append", default=[], help="Path to a newline-delimited repo list.")
    parser.add_argument("--repo", action="append", default=[], help="Explicit repo slug, e.g. psf/requests.")
    parser.add_argument("--out-jsonl", required=True, help="Output JSONL path.")
    parser.add_argument("--out-csv", required=True, help="Output CSV path.")
    parser.add_argument("--min-non-test-files", type=int, default=4)
    parser.add_argument("--max-non-test-files", type=int, default=15)
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-records-per-repo", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0, help="Stop after this many rows total; 0 means no limit.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel repo workers.")
    parser.add_argument("--sleep", type=float, default=0.0, help="Optional sleep between repo requests.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repos = load_repos(args.repos_file + args.repo)
    if not repos:
        repos = list(DEFAULT_REPOS)

    client = GHClient(tokenless_fallback=True)
    if client.use_gh:
        print("Using authenticated gh GraphQL collection", file=sys.stderr)
    else:
        print("Using best-effort REST fallback; this will be slower and more rate-limited", file=sys.stderr)

    rows: list[PRExample] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(
                collect_repo,
                client,
                repo,
                page_size=args.page_size,
                max_pages=args.max_pages,
                min_non_test_files=args.min_non_test_files,
                max_non_test_files=args.max_non_test_files,
                max_records=args.max_records_per_repo if args.max_records_per_repo > 0 else None,
            ): repo
            for repo in repos
        }
        for future in as_completed(future_map):
            repo = future_map[future]
            try:
                repo_rows = future.result()
            except Exception as exc:
                print(f"[warn] {repo}: {exc}", file=sys.stderr)
                continue
            rows.extend(repo_rows)
            rows.sort(key=lambda r: (r.repo, r.non_test_file_count, r.pr_number))
            print(f"[ok] {repo}: +{len(repo_rows)} examples", file=sys.stderr)
            if args.sleep > 0:
                time.sleep(args.sleep)
            if args.limit and len(rows) >= args.limit:
                rows = rows[: args.limit]
                break

    rows.sort(key=lambda r: (r.repo, r.non_test_file_count, r.pr_number))
    out_jsonl = Path(args.out_jsonl)
    out_csv = Path(args.out_csv)
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(str(out_jsonl), rows)
    write_csv(str(out_csv), rows)

    print(f"Wrote {len(rows)} rows to {out_jsonl} and {out_csv}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
