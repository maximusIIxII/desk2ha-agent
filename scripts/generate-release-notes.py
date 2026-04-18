#!/usr/bin/env python3
"""Generate structured GitHub Release notes from CHANGELOG.md.

Usage: python3 scripts/generate-release-notes.py <version> [prev_tag] [--validate] [--learn]

Flags:
  --validate   Cross-validate CHANGELOG against git log since last tag.
  --learn      Enable self-learning: persist results to .release-notes-history.json.

Output format matches the standard HA integration release style:
  ## Breaking changes / New features / Bug fixes / Improvements / Other changes
  with "- None" for empty sections and a Full Changelog link at the bottom.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# Map CHANGELOG headers (emoji or text) to release note sections.
# Order matters -- first match wins.
_HEADER_MAP: list[tuple[str, list[str]]] = [
    ("breaking", [r"Breaking", r"BREAKING"]),
    ("features", [r"New features", r"Added", r"\u2728"]),
    ("fixes", [r"Bug fixes", r"Fixed", r"\U0001f41b"]),
    ("improvements", [r"Improvements", r"Changed", r"\U0001f527"]),
]

# Anything not matched above goes into "other".
_OTHER_HEADERS = [
    r"Security",
    r"Removed",
    r"Documentation",
    r"\U0001f512",
    r"\U0001f4d6",
]

_SECTION_TITLES = {
    "breaking": "\U0001f4a5 Breaking changes",
    "features": "\u2728 New features",
    "fixes": "\U0001f41b Bug fixes",
    "improvements": "\U0001f527 Improvements",
    "other": "\U0001f4e6 Other changes",
}

# Commit prefixes that never need CHANGELOG entries (default set).
_DEFAULT_SKIP_PREFIXES: list[str] = [
    "chore:",
    "ci:",
    "docs:",
    "style:",
    "build:",
    "test:",
    "tests:",
    "merge",
    "Merge",
]

# Files whose diffs are scanned for breaking changes.
_BREAKING_CHANGE_FILES: list[str] = [
    "desk2ha_agent/transport/http.py",
    "desk2ha_agent/transport/mqtt.py",
    "desk2ha_agent/plugin_registry.py",
    "desk2ha_agent/config.py",
    "custom_components/desk2ha/manifest.json",
    "manifest.json",
    "config.toml",
]

_HISTORY_PATH = Path(__file__).resolve().parent / ".release-notes-history.json"


# ---------------------------------------------------------------------------
# Original CHANGELOG parsing (unchanged)
# ---------------------------------------------------------------------------


def _extract_version_section(changelog: str, version: str) -> str:
    """Extract the content between ## [version] and the next ## [."""
    pattern = rf"^## \[{re.escape(version)}\].*?\n(.*?)(?=^## \[|\Z)"
    m = re.search(pattern, changelog, re.MULTILINE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _classify_items(section_text: str) -> dict[str, list[str]]:
    """Parse CHANGELOG section into classified buckets."""
    buckets: dict[str, list[str]] = {
        "breaking": [],
        "features": [],
        "fixes": [],
        "improvements": [],
        "other": [],
    }

    current_bucket: str | None = None

    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        # Check if this is a ### header line
        if stripped.startswith("### "):
            header_text = stripped[4:]
            current_bucket = None

            # Try main sections
            for bucket_key, patterns in _HEADER_MAP:
                for pat in patterns:
                    if re.search(pat, header_text, re.IGNORECASE):
                        current_bucket = bucket_key
                        break
                if current_bucket:
                    break

            # Try "other" sections
            if current_bucket is None:
                for pat in _OTHER_HEADERS:
                    if re.search(pat, header_text, re.IGNORECASE):
                        current_bucket = "other"
                        break

            # Fallback: unknown headers go to "other"
            if current_bucket is None:
                current_bucket = "other"
            continue

        # Collect list items (- or *) under current header
        if current_bucket and re.match(r"^[-*] ", stripped):
            buckets[current_bucket].append(stripped)

    return buckets


def _format_body(
    buckets: dict[str, list[str]],
    version: str,
    prev_tag: str,
    repo_url: str,
) -> str:
    """Format the release body in the standard style."""
    lines: list[str] = []

    for key in ("breaking", "features", "fixes", "improvements", "other"):
        title = _SECTION_TITLES[key]
        items = buckets.get(key, [])
        lines.append(f"## {title}")
        if items:
            lines.extend(items)
        else:
            lines.append("- None")
        lines.append("")

    # Full Changelog link
    if prev_tag:
        lines.append(f"Full Changelog: [CHANGELOG]({repo_url}/compare/{prev_tag}...v{version})")
    else:
        lines.append(f"Full Changelog: [CHANGELOG]({repo_url}/blob/main/CHANGELOG.md)")

    return "\n".join(lines)


def _detect_repo_url() -> str:
    """Detect repo URL from git remote origin."""
    try:
        remote = subprocess.check_output(["git", "remote", "get-url", "origin"], text=True).strip()
        # Convert SSH to HTTPS format
        m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", remote)
        if m:
            return f"https://github.com/{m.group(1)}"
        # Already HTTPS
        return remote.removesuffix(".git")
    except Exception:
        pass
    # Fallback: parse from CHANGELOG compare links
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"(https://github\.com/[^/]+/[^/\s\])]+)", changelog)
    if m:
        return m.group(1).rstrip("/")
    return "https://github.com/maximusIIxII/unknown"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_last_tag() -> str:
    """Return the most recent tag, or empty string."""
    try:
        return subprocess.check_output(
            ["git", "describe", "--tags", "--abbrev=0"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return ""


def _git_commits_since(tag: str) -> list[str]:
    """Return list of one-line commit messages since *tag* (or all if empty)."""
    cmd = ["git", "log", "--oneline"]
    if tag:
        cmd.append(f"{tag}..HEAD")
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def _git_diff_files_since(tag: str) -> str:
    """Return the unified diff of tracked files since *tag*."""
    cmd = ["git", "diff", tag, "HEAD"] if tag else ["git", "diff", "HEAD"]
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return ""


def _git_diff_names_since(tag: str) -> list[str]:
    """Return list of changed file paths since *tag*."""
    cmd = ["git", "diff", "--name-only"]
    if tag:
        cmd.extend([tag, "HEAD"])
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# 1. Git-log cross-validation
# ---------------------------------------------------------------------------


def _extract_keywords(message: str) -> list[str]:
    """Extract meaningful keywords from a commit message (lowercase)."""
    # Strip the short-hash prefix (e.g. "abc1234 ")
    parts = message.split(None, 1)
    text = parts[1] if len(parts) > 1 else parts[0]
    # Remove conventional-commit prefix
    text = re.sub(r"^[a-z]+(\(.+?\))?[!:]?\s*", "", text, flags=re.IGNORECASE)
    words = re.findall(r"[a-z]{3,}", text.lower())
    # Filter out very common filler words
    stopwords = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "are",
        "was",
        "were",
        "has",
        "have",
        "not",
        "all",
        "also",
        "when",
        "now",
        "via",
    }
    return [w for w in words if w not in stopwords]


def _fuzzy_match(commit_msg: str, changelog_text: str) -> bool:
    """Return True if enough keywords from the commit appear in the CHANGELOG."""
    keywords = _extract_keywords(commit_msg)
    if not keywords:
        return True  # trivial commit, nothing to match
    cl_lower = changelog_text.lower()
    matched = sum(1 for kw in keywords if kw in cl_lower)
    # Require at least 40% of keywords to match
    return matched >= max(1, len(keywords) * 0.4)


def _has_skip_prefix(commit_msg: str, extra_prefixes: list[str] | None = None) -> bool:
    """Return True if the commit message starts with a known skip prefix."""
    prefixes = list(_DEFAULT_SKIP_PREFIXES)
    if extra_prefixes:
        prefixes.extend(extra_prefixes)
    # Strip hash prefix
    parts = commit_msg.split(None, 1)
    text = parts[1] if len(parts) > 1 else parts[0]
    text_lower = text.lower()
    return any(text_lower.startswith(pfx.lower()) for pfx in prefixes)


def validate_commits(
    commits: list[str],
    changelog_text: str,
    learned_prefixes: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Cross-validate commits against CHANGELOG text.

    Returns (missing, skipped) lists of commit messages.
    """
    missing: list[str] = []
    skipped: list[str] = []
    for c in commits:
        if _has_skip_prefix(c, learned_prefixes):
            skipped.append(c)
            continue
        if not _fuzzy_match(c, changelog_text):
            missing.append(c)
    return missing, skipped


# ---------------------------------------------------------------------------
# 2. Breaking change detection
# ---------------------------------------------------------------------------

# Patterns that hint at breaking changes per file category.
_BREAKING_PATTERNS: list[tuple[str, list[re.Pattern[str]]]] = [
    (
        "http.py",
        [
            re.compile(r"^-\s*@?(app|router)\.(get|post|put|delete|patch)\(", re.M),
            re.compile(r"^-\s*async def (handle_|route_)", re.M),
        ],
    ),
    (
        "mqtt.py",
        [
            re.compile(r'^-\s*"[^"]+"\s*:', re.M),  # removed command mapping
            re.compile(r"^-\s*(COMMAND_|CMD_)", re.M),
        ],
    ),
    (
        "plugin_registry.py",
        [
            re.compile(r"^-\s+.*Collector", re.M),
            re.compile(r'^-\s+"[^"]+"', re.M),
        ],
    ),
    (
        "config.py",
        [
            re.compile(r'^-\s+["\']?\w+["\']?\s*[:=]', re.M),
        ],
    ),
    (
        "config.toml",
        [
            re.compile(r"^-\s*\[", re.M),
            re.compile(r"^-\s*\w+\s*=", re.M),
        ],
    ),
    (
        "manifest.json",
        [
            re.compile(r'^-\s*"schema_version"', re.M),
        ],
    ),
]


def _file_diff_section(full_diff: str, filename: str) -> str:
    """Extract the diff hunk for a specific file from a unified diff."""
    pattern = rf"^diff --git a/.*?{re.escape(filename)}.*?\n(.*?)(?=^diff --git|\Z)"
    m = re.search(pattern, full_diff, re.MULTILINE | re.DOTALL)
    return m.group(0) if m else ""


def detect_breaking_changes(tag: str) -> list[str]:
    """Scan git diff since *tag* for patterns indicating breaking changes.

    Returns a list of human-readable warning strings.
    """
    changed_files = _git_diff_names_since(tag)
    if not changed_files:
        return []

    full_diff = _git_diff_files_since(tag)
    if not full_diff:
        return []

    warnings: list[str] = []
    for file_suffix, patterns in _BREAKING_PATTERNS:
        # Find changed files matching this suffix
        matching = [f for f in changed_files if f.endswith(file_suffix)]
        for fpath in matching:
            section = _file_diff_section(full_diff, fpath)
            if not section:
                continue
            for pat in patterns:
                hits = pat.findall(section)
                if hits:
                    warnings.append(
                        f"  {fpath}: {len(hits)} removed/changed line(s) "
                        f"matching pattern {pat.pattern!r}"
                    )
    return warnings


# ---------------------------------------------------------------------------
# 3. Self-learning history
# ---------------------------------------------------------------------------


def _load_history() -> dict:
    """Load or initialise the history file."""
    if _HISTORY_PATH.exists():
        try:
            return json.loads(_HISTORY_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "learned_prefixes": list(_DEFAULT_SKIP_PREFIXES),
        "false_positives": [],
        "releases": {},
    }


def _save_history(data: dict) -> None:
    _HISTORY_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _learn_from_missing(history: dict, version: str, missing: list[str]) -> list[str]:
    """Analyse missing commits and learn new skip prefixes.

    Returns the updated list of missing commits (after filtering out
    newly-learned false positives).
    """
    prefix_counts: dict[str, int] = {}
    still_missing: list[str] = []

    for msg in missing:
        parts = msg.split(None, 1)
        text = parts[1] if len(parts) > 1 else parts[0]
        m = re.match(r"^([a-z]+)[:(!\s]", text, re.IGNORECASE)
        if m:
            pfx = m.group(1).lower() + ":"
            prefix_counts[pfx] = prefix_counts.get(pfx, 0) + 1

    # If a prefix appears in >=2 false-positive commits, learn it
    new_prefixes: list[str] = []
    learned = set(p.lower() for p in history.get("learned_prefixes", []))
    for pfx, count in prefix_counts.items():
        if count >= 2 and pfx not in learned:
            new_prefixes.append(pfx)
            learned.add(pfx)

    if new_prefixes:
        history.setdefault("learned_prefixes", []).extend(new_prefixes)

    # Re-filter missing using updated prefixes
    for msg in missing:
        if _has_skip_prefix(msg, list(learned)):
            history.setdefault("false_positives", []).append({"version": version, "commit": msg})
        else:
            still_missing.append(msg)

    return still_missing


# ---------------------------------------------------------------------------
# 4. Completeness scoring
# ---------------------------------------------------------------------------


def compute_score(
    total_commits: int,
    skipped: int,
    missing: int,
    breaking_warnings: int,
    has_breaking_section: bool,
) -> int:
    """Compute a completeness score 0-100."""
    if total_commits == 0:
        return 100

    non_trivial = total_commits - skipped
    if non_trivial <= 0:
        return 100

    documented = non_trivial - missing
    doc_ratio = documented / non_trivial  # 0..1

    score = int(doc_ratio * 90)  # max 90 from documentation coverage

    # +10 for breaking-change correctness
    if breaking_warnings > 0 and not has_breaking_section:
        score += 0  # penalty: missing breaking section
    else:
        score += 10

    return max(0, min(100, score))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a.lstrip("-") for a in sys.argv[1:] if a.startswith("--")}

    do_validate = "validate" in flags
    do_learn = "learn" in flags

    if not args:
        print(
            f"Usage: {sys.argv[0]} <version> [prev_tag] [--validate] [--learn]",
            file=sys.stderr,
        )
        sys.exit(1)

    version = args[0]
    prev_tag = args[1] if len(args) > 1 else ""

    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    section = _extract_version_section(changelog, version)

    if not section:
        # Fallback: try [Unreleased] (for dry-run / preview)
        section = _extract_version_section(changelog, "Unreleased")

    buckets = _classify_items(section)
    repo_url = _detect_repo_url()
    body = _format_body(buckets, version, prev_tag, repo_url)
    sys.stdout.buffer.write(body.encode("utf-8"))
    sys.stdout.buffer.write(b"\n")

    # ------------------------------------------------------------------
    # Validation & learning (printed to stderr so release body is clean)
    # ------------------------------------------------------------------
    if not do_validate:
        return

    tag = prev_tag or _git_last_tag()
    commits = _git_commits_since(tag)

    if not commits:
        print("\n[validate] No commits found since last tag.", file=sys.stderr)
        return

    # Load history for learned prefixes
    history = _load_history() if do_learn else {"learned_prefixes": [], "releases": {}}
    learned_prefixes = history.get("learned_prefixes", [])

    # --- Cross-validation ---
    changelog_flat = section  # use the version-specific section text
    missing, skipped = validate_commits(commits, changelog_flat, learned_prefixes)

    # --- Breaking change detection ---
    breaking_warnings = detect_breaking_changes(tag)
    has_breaking_section = bool(buckets.get("breaking"))

    # --- Learning ---
    if do_learn and missing:
        missing = _learn_from_missing(history, version, missing)

    # --- Scoring ---
    score = compute_score(
        total_commits=len(commits),
        skipped=len(skipped),
        missing=len(missing),
        breaking_warnings=len(breaking_warnings),
        has_breaking_section=has_breaking_section,
    )

    # --- Report ---
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"  Release notes validation for v{version}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"  Commits since {tag or '(initial)'}: {len(commits)}", file=sys.stderr)
    print(f"  Skipped (infra/trivial):          {len(skipped)}", file=sys.stderr)
    print(f"  Missing from CHANGELOG:           {len(missing)}", file=sys.stderr)
    print(f"  Completeness score:               {score}%", file=sys.stderr)

    if missing:
        print("\n  Commits NOT mentioned in CHANGELOG:", file=sys.stderr)
        for m in missing:
            print(f"    - {m}", file=sys.stderr)

    if breaking_warnings:
        print("\n  Potential BREAKING CHANGES detected in diff:", file=sys.stderr)
        for w in breaking_warnings:
            print(w, file=sys.stderr)
        if not has_breaking_section:
            print(
                "\n  *** WARNING: No ### Breaking section in CHANGELOG "
                "but breaking changes were detected! ***",
                file=sys.stderr,
            )

    # --- Persist history ---
    if do_learn:
        release_entry = {
            "total_commits": len(commits),
            "skipped": len(skipped),
            "missing": len(missing),
            "score": score,
            "breaking_warnings": len(breaking_warnings),
        }
        history.setdefault("releases", {})[version] = release_entry
        _save_history(history)
        print(f"\n  History saved to {_HISTORY_PATH}", file=sys.stderr)

        # Show score trend if we have prior releases
        releases = history.get("releases", {})
        if len(releases) > 1:
            print("\n  Score trend:", file=sys.stderr)
            for v, r in releases.items():
                print(f"    v{v}: {r['score']}%", file=sys.stderr)

    print("=" * 60, file=sys.stderr)


if __name__ == "__main__":
    main()
