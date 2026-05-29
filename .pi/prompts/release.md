---
description: Commit, push, and build macOS .app release
argument-hint: "[version] [message]"
---
Release: commit all changes, push to origin, build macOS .app, install to /Applications.

Steps:
1. git add -A && git commit -m "release" (or use the message if provided)
2. git push origin main
3. If version provided: update pyproject.toml version, git tag v{version}, push tag
4. pkill vermilion-bird (if running), then clean dist/
5. python3 -m PyInstaller vermilion-bird.spec --noconfirm
6. cp -R dist/Vermilion Bird.app /Applications/
7. Report size and status

Argument usage:
- /release → default commit message "release"
- /release 0.3.0 → version + default message
- /release "feat: add marketplace" → custom message
- /release 0.3.0 "feat: add marketplace" → version + custom message
