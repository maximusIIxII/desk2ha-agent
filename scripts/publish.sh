#!/usr/bin/env bash
# Publish desk2ha-agent: bump version, commit, tag, push.
#
# Usage:
#   ./scripts/publish.sh [patch|minor|major|x.y.z] [--dry-run]
#
# Assumes predeploy.sh has passed. Assumes staging deploy + verify also passed.
# DOES NOT run lint/tests/security — those are predeploy's job.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

REPO_NAME="desk2ha-agent"
REPO_URL="https://github.com/maximusIIxII/desk2ha-agent"
VERSION_FILE="pyproject.toml"

DRY_RUN=0
ARG="${1:-}"
if [[ "${2:-}" == "--dry-run" || "$ARG" == "--dry-run" ]]; then
    DRY_RUN=1
    if [[ "$ARG" == "--dry-run" ]]; then ARG="${2:-}"; fi
fi

get_current_version() {
    python3 -c "
import re
text = open('$VERSION_FILE').read()
print(re.search(r'^version\s*=\s*\"(.+?)\"', text, re.MULTILINE).group(1))
"
}

set_version() {
    python3 -c "
import re
text = open('$VERSION_FILE').read()
text = re.sub(r'^(version\s*=\s*\")(.+?)(\")', r'\g<1>$1\3', text, count=1, flags=re.MULTILINE)
with open('$VERSION_FILE', 'w') as f:
    f.write(text)
"
}

bump_version() {
    local current="$1" type="$2"
    IFS='.' read -r major minor patch <<< "$current"
    case "$type" in
        major) echo "$((major + 1)).0.0" ;;
        minor) echo "${major}.$((minor + 1)).0" ;;
        patch) echo "${major}.${minor}.$((patch + 1))" ;;
    esac
}

# Must be on main
BRANCH=$(git branch --show-current)
if [[ "$BRANCH" != "main" && "$BRANCH" != "master" ]]; then
    echo "[FAIL] publish must run on main/master (currently on $BRANCH)"
    exit 1
fi

git pull --ff-only origin "$BRANCH" || {
    echo "[FAIL] git pull --ff-only failed"
    exit 1
}

UNRELEASED=$(awk '/^## \[Unreleased\]/{f=1; next} /^## \[/{exit} f{print}' CHANGELOG.md)

# Detect bump type
HAS_BREAKING=$(echo "$UNRELEASED" | grep -c '^### Breaking' || true)
HAS_ADDED=$(echo "$UNRELEASED" | grep -cE '^### (Added|✨)' || true)

if [[ -z "$ARG" || "$ARG" == "--dry-run" ]]; then
    if [[ "$HAS_BREAKING" -gt 0 ]]; then BUMP_TYPE="major"
    elif [[ "$HAS_ADDED" -gt 0 ]]; then BUMP_TYPE="minor"
    else BUMP_TYPE="patch"; fi
    CURRENT=$(get_current_version)
    VERSION=$(bump_version "$CURRENT" "$BUMP_TYPE")
elif [[ "$ARG" == "major" || "$ARG" == "minor" || "$ARG" == "patch" ]]; then
    BUMP_TYPE="$ARG"
    CURRENT=$(get_current_version)
    VERSION=$(bump_version "$CURRENT" "$BUMP_TYPE")
elif [[ "$ARG" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    VERSION="$ARG"
    CURRENT=$(get_current_version)
    IFS='.' read -r cmaj cmin _ <<< "$CURRENT"
    IFS='.' read -r nmaj nmin _ <<< "$VERSION"
    if   [[ "$nmaj" -gt "$cmaj" ]]; then BUMP_TYPE="major"
    elif [[ "$nmin" -gt "$cmin" ]]; then BUMP_TYPE="minor"
    else BUMP_TYPE="patch"; fi
else
    echo "Usage: $0 [patch|minor|major|x.y.z] [--dry-run]"
    exit 1
fi

if git rev-parse "v$VERSION" >/dev/null 2>&1; then
    echo "[FAIL] tag v$VERSION already exists"
    exit 1
fi

echo "[i] Publishing $REPO_NAME v$VERSION ($BUMP_TYPE)  dry_run=$DRY_RUN"

# Bump version file
set_version "$VERSION"
echo "[OK] $VERSION_FILE -> $VERSION"

# Update CHANGELOG
DATE=$(date +%Y-%m-%d)
sed -i "s/^## \[Unreleased\]/## [Unreleased]\n\n## [$VERSION] - $DATE/" CHANGELOG.md

PREV_VERSION=$(grep -oP '^\## \[\K[\d.]+' CHANGELOG.md | head -2 | tail -1)
if [[ -n "$PREV_VERSION" ]] && grep -q "^\[${PREV_VERSION}\]:" CHANGELOG.md; then
    sed -i "/^\[${PREV_VERSION}\]:/i [$VERSION]: $REPO_URL/compare/v${PREV_VERSION}...v$VERSION" CHANGELOG.md
fi
echo "[OK] CHANGELOG.md updated"

git add "$VERSION_FILE" CHANGELOG.md
git commit -m "release: v$VERSION"
git tag "v$VERSION"
echo "[OK] Committed and tagged v$VERSION"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "[DRY-RUN] skipping push. To publish:"
    echo "  git push origin $BRANCH --tags"
    exit 0
fi

git push origin "$BRANCH" --tags
echo "[OK] Pushed to origin. PyPI workflow will auto-publish via release.yml"
