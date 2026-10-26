# How to publish v1.7.2 on GitHub Releases (5 minutes)

Goal: after this, **PrintHub Tool → 8 / extension "Check for update" /
`printhub.py update-check`** will find and open your release automatically
(they query `https://api.github.com/repos/bitdreamit/PrintHub-Pro/releases/latest`).

## Option A — Web UI (no tools needed)

1. Open https://github.com/bitdreamit/PrintHub-Pro/releases/new
2. **Choose a tag:** type `v1.7.2` → **Create new tag on publish** (target: main).
3. **Release title:** `v1.7.2 — Simple Install & Control`
4. **Describe:** paste the contents of `RELEASE-NOTES-v1.7.2.md` (this folder).
5. **Attach binaries** — drag & drop these files from `download/`:

   - PrintHub-Pro-Setup-1.7.2.exe
   - PrintHub-Pro-1.7.2.zip
   - PrintHub-Pro-v1.7.2-FULL.zip
   - PrintHub-Pro-Extension-v1.7.2.zip
   - printhub-pro_1.7.2_all.deb
   - SHA256SUMS-1.7.2.txt

6. Tick **Set as the latest release** → **Publish release**.
7. Verify: open https://github.com/bitdreamit/PrintHub-Pro/releases/latest —
   it must show v1.7.2. Then run `PrintHub Tool → 8` on the Windows PC:
   it should say "You are up to date (latest release: v1.7.2)".

## Option B — gh CLI (if you have `gh` installed and logged in)

```bash
cd download           # the folder that holds the six files
gh release create v1.7.2 \
  --repo bitdreamit/PrintHub-Pro \
  --title "v1.7.2 — Simple Install & Control" \
  --notes-file GitHub-Release-Kit/RELEASE-NOTES-v1.7.2.md \
  --latest \
  PrintHub-Pro-Setup-1.7.2.exe \
  PrintHub-Pro-1.7.2.zip \
  PrintHub-Pro-v1.7.2-FULL.zip \
  PrintHub-Pro-Extension-v1.7.2.zip \
  printhub-pro_1.7.2_all.deb \
  SHA256SUMS-1.7.2.txt
```

## Also push the source (repo is one commit behind)

```bash
cd <your local PrintHub-Pro clone>
# copy the updated tree (extension/, hub/, install/, installer/, docs/, README.md)
git add -A && git commit -m "v1.7.2 — PrintHub Tool, Windows service, silent install,
extension master switch, queue mode ON/OFF, tabbed options, GitHub update check" 
git push origin main
```

Or commit straight from the downloaded zips — `PrintHub-Pro-1.7.2.zip` already
has the repo-style layout inside (`extension/`, `doc/`, `tool/unix/hub/`).

## After publishing

- Every installed PrintHub (Tool → 8, About tab, CLI) reports v1.7.2 as up to date.
- Future releases: bump `VERSION` anchors, build, attach — the checkers pick
  the newest `releases/latest` automatically.
