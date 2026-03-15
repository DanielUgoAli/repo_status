#!/usr/bin/env python3
"""
Recursively scan a directory for Git repositories and print a formatted status report.

Usage:
  python repo_status_recursive.py
  python repo_status_recursive.py C:/path/to/root
  python repo_status_recursive.py . --show-files --max-files 8
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


BRANCH_RE = re.compile(
    r"^##\s+(?P<branch>[^.\s]+)(?:\.\.\.(?P<upstream>[^\s]+))?(?:\s+\[(?P<tracking>[^\]]+)\])?"
)


@dataclass
class RepoStatus:
    path: Path
    branch: str
    upstream: str | None
    ahead: int
    behind: int
    staged: int
    modified: int
    deleted: int
    untracked: int
    renamed: int
    conflicted: int
    clean: bool
    changed_files: list[str]


def run_git(repo_path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def find_git_repos(root: Path) -> list[Path]:
    repos: list[Path] = []
    visited: set[Path] = set()

    for current_dir, dirnames, filenames in os.walk(root):
        current = Path(current_dir)

        if ".git" in dirnames or ".git" in filenames:
            resolved = current.resolve()
            if resolved not in visited:
                repos.append(current)
                visited.add(resolved)

        if ".git" in dirnames:
            dirnames.remove(".git")

    repos.sort(key=lambda p: str(p).lower())
    return repos


def parse_tracking(tracking: str | None) -> tuple[int, int]:
    if not tracking:
        return 0, 0

    ahead = 0
    behind = 0
    for chunk in tracking.split(","):
        item = chunk.strip()
        if item.startswith("ahead "):
            ahead = int(item.split(" ", 1)[1])
        elif item.startswith("behind "):
            behind = int(item.split(" ", 1)[1])
    return ahead, behind


def parse_repo_status(repo_path: Path) -> RepoStatus:
    result = run_git(repo_path, ["status", "--porcelain=v1", "--branch"])
    if result.returncode != 0:
        return RepoStatus(
            path=repo_path,
            branch="(error)",
            upstream=None,
            ahead=0,
            behind=0,
            staged=0,
            modified=0,
            deleted=0,
            untracked=0,
            renamed=0,
            conflicted=0,
            clean=False,
            changed_files=[f"git status failed: {result.stderr.strip() or 'unknown error'}"],
        )

    lines = result.stdout.splitlines()

    branch = "(detached)"
    upstream: str | None = None
    ahead = 0
    behind = 0

    staged = 0
    modified = 0
    deleted = 0
    untracked = 0
    renamed = 0
    conflicted = 0
    changed_files: list[str] = []

    for idx, line in enumerate(lines):
        if idx == 0 and line.startswith("## "):
            match = BRANCH_RE.match(line)
            if match:
                branch = match.group("branch") or branch
                upstream = match.group("upstream")
                ahead, behind = parse_tracking(match.group("tracking"))
            continue

        if not line:
            continue

        if line.startswith("?? "):
            untracked += 1
            changed_files.append(line[3:])
            continue

        status = line[:2]
        path = line[3:]
        changed_files.append(path)

        x, y = status[0], status[1]

        if "U" in status or status in {"AA", "DD"}:
            conflicted += 1

        if x not in {" ", "?"}:
            staged += 1

        if y not in {" ", "?"}:
            modified += 1

        if "D" in status:
            deleted += 1

        if "R" in status:
            renamed += 1

    clean = (staged + modified + deleted + untracked + renamed + conflicted) == 0

    return RepoStatus(
        path=repo_path,
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        staged=staged,
        modified=modified,
        deleted=deleted,
        untracked=untracked,
        renamed=renamed,
        conflicted=conflicted,
        clean=clean,
        changed_files=changed_files,
    )


def rel_path(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def print_report(statuses: list[RepoStatus], root: Path, show_files: bool, max_files: int) -> None:
    width = 90
    line = "=" * width
    print(line)
    print(f"GIT STATUS REPORT (recursive)\nRoot: {root.resolve()}")
    print(line)

    clean_count = sum(1 for s in statuses if s.clean)
    dirty_count = len(statuses) - clean_count

    print(
        f"Repositories found: {len(statuses)} | Clean: {clean_count} | "
        f"Dirty/Error: {dirty_count}"
    )
    print("-" * width)

    for i, status in enumerate(statuses, start=1):
        short_path = rel_path(status.path, root)
        state = "CLEAN" if status.clean else "DIRTY"
        print(f"[{i:02}] {short_path}")
        print(f"     Branch : {status.branch}")
        if status.upstream:
            print(
                f"     Upstream: {status.upstream} "
                f"(ahead {status.ahead}, behind {status.behind})"
            )
        else:
            print("     Upstream: (none)")

        print(
            "     Changes : "
            f"staged={status.staged}, modified={status.modified}, deleted={status.deleted}, "
            f"renamed={status.renamed}, untracked={status.untracked}, conflicted={status.conflicted}"
        )
        print(f"     State   : {state}")

        if show_files and status.changed_files:
            print("     Files   :")
            for file_path in status.changed_files[:max_files]:
                print(f"       - {file_path}")
            extra = len(status.changed_files) - max_files
            if extra > 0:
                print(f"       ... and {extra} more")

        print("-" * width)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Recursively discover Git repos and print a pretty status report."
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Root directory to scan recursively (default: current directory).",
    )
    parser.add_argument(
        "--show-files",
        action="store_true",
        help="Show changed file paths for each repository.",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=10,
        help="Maximum number of changed files to display per repository when --show-files is used.",
    )

    args = parser.parse_args()
    root = Path(args.root).expanduser()

    if not root.exists() or not root.is_dir():
        print(f"Error: '{root}' is not a valid directory.")
        return 1

    repos = find_git_repos(root)
    if not repos:
        print(f"No Git repositories found under: {root.resolve()}")
        return 0

    statuses = [parse_repo_status(repo) for repo in repos]
    print_report(statuses, root=root, show_files=args.show_files, max_files=max(1, args.max_files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
