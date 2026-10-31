# How to publish v1.7.2 on GitHub Releases (5 minutes)

Goal: after this, **AdvPrint Tool → 8 / extension "Check for update" /
`advprint.py update-check`** will find and open your release automatically
(they query `https://api.github.com/repos/bitdreamit/AdvPrint-Pro/releases/latest`).

## Option A — Web UI (no tools needed)

1. Open https://github.com/bitdreamit/AdvPrint-Pro/releases/new
2. **Choose a tag:** type `v1.7.2` → **Create new tag on publish** (target: main).
3. **Release title:** `v1.7.2 — Simple Install & Control`
4. **Describe:** paste the contents of `RELEASE-NOTES-v1.7.2.md` (this folder).
5. **Attach binaries** — drag & drop these files from `download/`:

   - AdvPrint-Pro-Setup-1.7.2.exe
   - AdvPrint-Pro-1.7.2.zip
   - AdvPrint-Pro-v1.7.2-FULL.zip
   - AdvPrint-Pro-Extension-v1.7.2.zip
   - advprint-pro_1.7.2_all.deb
   - SHA256SUMS-1.7.2.txt

6. Tick **Set as the latest release** → **Publish release**.
7. Verify: open https://github.com/bitdreamit/AdvPrint-Pro/releases/latest —
   it must show v1.7.2. Then run `AdvPrint Tool → 8` on the Windows PC:
   it should say "You are up to date (latest release: v1.7.2)".

## Option B — gh CLI (if you have `gh` installed and logged in)

```bash
cd download           # the folder that holds the six files
gh release create v1.7.2 \
  --repo bitdreamit/AdvPrint-Pro \
  --title "v1.7.2 — Simple Install & Control" \
  --notes-file GitHub-Release-Kit/RELEASE-NOTES-v1.7.2.md \
  --latest \
  AdvPrint-Pro-Setup-1.7.2.exe \
  AdvPrint-Pro-1.7.2.zip \
  AdvPrint-Pro-v1.7.2-FULL.zip \
  AdvPrint-Pro-Extension-v1.7.2.zip \
  advprint-pro_1.7.2_all.deb \
  SHA256SUMS-1.7.2.txt
```

## Also push the source (repo is one commit behind)

```bash
cd <your local AdvPrint-Pro clone>
# copy the updated tree (extension/, hub/, install/, installer/, docs/, README.md)
git add -A && git commit -m "v1.7.2 — AdvPrint Tool, Windows service, silent install,
extension master switch, queue mode ON/OFF, tabbed options, GitHub update check" 
git push origin main
```

Or commit straight from the downloaded zips — `AdvPrint-Pro-1.7.2.zip` already
has the repo-style layout inside (`extension/`, `doc/`, `tool/unix/hub/`).

## After publishing

- Every installed AdvPrint (Tool → 8, About tab, CLI) reports v1.7.2 as up to date.
- Future releases: bump `VERSION` anchors, build, attach — the checkers pick
  the newest `releases/latest` automatically.
