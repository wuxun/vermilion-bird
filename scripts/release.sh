#!/bin/bash
# Release: commit all changes, push, build macOS .app, install to /Applications
# Usage: ./scripts/release.sh [version] ["commit message"]
#   version: auto-detect if omitted (reads pyproject.toml)

set -e

VERSION="${1:-}"
COMMIT_MSG="${2:-release}"

# ── 1. Stage & commit ──
echo "=== 1/4: Commit ==="
git add -A
git commit -m "$COMMIT_MSG" || echo "(no changes to commit)"

# ── 2. Push ──
echo "=== 2/4: Push ==="
git push origin main

# ── 3. Tag & push tag ──
if [ -n "$VERSION" ]; then
    echo "=== Tag: v$VERSION ==="
    git tag -a "v$VERSION" -m "v$VERSION: $COMMIT_MSG" 2>/dev/null || echo "(tag exists)"
    git push origin "v$VERSION" 2>/dev/null || echo "(tag already pushed)"
fi

# ── 4. Build macOS app ──
echo "=== 3/4: Build macOS .app ==="
# Kill any running instances
pkill -f "vermilion-bird" 2>/dev/null || true
sleep 1

# Clean & rebuild
rm -rf build/ dist/vermilion-bird "dist/Vermilion Bird.app"
python3 -m PyInstaller vermilion-bird.spec --noconfirm

# Copy to /Applications
echo "=== 4/4: Install to /Applications ==="
rm -rf "/Applications/Vermilion Bird.app"
cp -R "dist/Vermilion Bird.app" "/Applications/"

echo ""
echo "✅ Release complete!"
du -sh "dist/Vermilion Bird.app"
echo "/Applications/Vermilion Bird.app"
