PrintHub Pro 2.0.2 - Windows
===========================

NORMAL INSTALL (recommended):
  Double-click  PrintHub-Pro-Setup-2.0.2.exe
  - installs everything (Python included, no admin)
  - starts the hub + auto-runs at logon (Startup app, visible)
  - creates the Start Menu shortcuts:
      Start PrintHub Pro / PrintHub Tool / Uninstall
  - OPTIONAL Windows service: tick the box on the components
    page, or run PrintHub Tool > 5 later (services.msc)
  - silent install:  PrintHub-Pro-Setup-2.0.2.exe /S

AFTER INSTALL use 'PrintHub Tool' (Start Menu) - a numbered menu
for start / stop / status / service add+remove / auto-run /
update check / uninstall. Non-technical users need nothing else.

If Windows SmartScreen appears: More info > Run anyway.
If the file reports 'corrupted': re-download it and compare the
SHA-256 printed in SHA256SUMS-2.0.2.txt.
