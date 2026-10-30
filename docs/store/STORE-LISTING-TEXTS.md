# Chrome Web Store — Copy-Paste Listing Texts (PrintHub Pro 1.5.0)

Every field below is ready to paste into the Developer Dashboard.
Character limits are verified. Do not add emoji to the store name.

---

## 1. Item name  (limit: 45 chars — this is 39)

```
PrintHub Pro — Print from Any Web Page
```

## 2. Short description  (limit: 132 chars — this is 131)

```
Print any page, PDF, selection or screenshot to your own printer via the
local PrintHub hub. Silent, no dialog, 100% local.
```
(one line, no line break when pasting)

## 3. Detailed description  (plain text, safe for the 16,000-char limit)

```
PrintHub Pro prints the web page you are viewing straight to YOUR printer — no print dialog, no extra clicks, no cloud service. The page goes from Chrome to a tiny hub program on your own computer, and from there to any printer installed in Windows, macOS or Linux.

FEATURES
• One-click silent printing of the current tab
• Save any page as a PDF file (no paper needed)
• Print a full-page screenshot of the current tab
• Right-click → "Print with PrintHub Pro" on pages, links and selections
• Keyboard hotkey Alt+P (rebindable) for instant printing
• Optional: intercept window.print() on websites and send it to your printer silently
• JavaScript API (window.printhub) so your own web app / POS / kiosk page can fire print jobs
• Default printer, paper size, copies and tray — set once in Options, every job just works
• Recent-jobs list with status (printed / printing / failed), pause and resume the queue
• Desktop notifications when a job succeeds or fails

HOW IT WORKS
1. Install the PrintHub Pro hub on your computer (free, ~10 MB, link below). It runs 100% locally and talks to your installed printers.
2. Install this extension. The popup turns green — "Hub connected".
3. Click "Print this page". Done. The job goes straight to your default printer.

WHERE TO GET THE HUB
https://github.com/bitdreamit/PrintHub-Pro/releases
(Windows: run PrintHub-Pro-Setup-1.5.0.exe — includes its own Python, nothing else to install. Linux: .deb package or install-unix.sh.)

PRIVACY — 100% LOCAL
• Pages and print jobs travel only inside your computer (browser → hub → printer). They never touch any server.
• No analytics, no tracking, no account, no data collection. Full privacy policy: https://bitdreamit.github.io/PrintHub-Pro/privacy-policy.html

WHO IS THIS FOR
• Offices and shops that print invoices, tickets, receipts or labels from a web system and hate the print dialog
• Kiosks and POS stations where the page must go straight to paper
• Anyone who wants Chrome's print dialog out of the way

The extension alone cannot print — the free local hub must be installed on the same computer. Get it from the link above; setup takes about two minutes and the popup walks you through it.

Support: https://github.com/bitdreamit/PrintHub-Pro/issues
```

## 4. Category / language / region

| Field | Value |
|---|---|
| Category | **Productivity** |
| Language | **English (United States)** |
| Regions | All (default) |
| Visibility | Public |

## 5. Single purpose (Privacy tab)

```
Print web pages — and PDF or screenshot versions of them — to a printer
connected to the user's own computer, via the user's own locally installed
PrintHub Pro hub service, without showing Chrome's print dialog.
```

## 6. Permission justifications (Privacy tab — paste one per permission)

**Host permissions — `<all_urls>`:**
```
A content script runs on every page for two printing features: (1) when the
user clicks "Print this page", uses the right-click menu or the hotkey, the
extension captures the page the user is viewing and converts it to a print
job; (2) websites that integrate the extension's window.printhub JavaScript
API (e.g. POS/kiosk systems) send print requests through the same relay.
The content script performs no data collection: it only forwards print
requests made by the user or by the page itself to the extension, and only
after the user has installed and enabled the feature in Options (it can be
turned off). Printing is impossible without an explicit user or page action;
the extension never reads or transmits page content on its own.
```

**Host permissions — `http://127.0.0.1/*` and `http://localhost/*`:**
```
The extension communicates only with the PrintHub Pro hub, a local program
the user installs on their own computer to reach their printers. All print
jobs are sent to this local address only. 127.0.0.1 traffic never leaves
the user's machine and cannot reach any web server.
```

**`tabs`:**
```
To read the title and URL of the tab the user chooses to print, so the print
job can be named after the page and shown in the local recent-jobs list.
```

**`activeTab` + `scripting`:**
```
To start page capture only when the user requests a print (popup button,
context menu, or keyboard command), converting the current page into the
print job. No script is injected until the user acts.
```

**`storage`:**
```
To save the user's settings (printer, paper size, copies, hub address) and
the local recent-jobs list in chrome.storage on their own machine.
```

**`notifications`:**
```
To notify the user when a print job succeeds or fails.
```

**`contextMenus`:**
```
To add the "Print with PrintHub Pro" entry to the browser's right-click menu.
```

## 7. Data usage disclosures (Privacy tab checkboxes)

Select: **"This item does not collect any user data"** — plus, if the form
asks about website content because of host permissions, declare:

| Data type | Collected? | Purpose | Sold? | Transferred? |
|---|---|---|---|---|
| Website content | Processed locally only | User-requested printing | No | No — stays on the user's machine |
| Personal communications | No | — | — | — |
| Personally identifiable information | No | — | — | — |
| Health, financial, authentication info | No | — | — | — |
| Location, web history, user activity | No | — | — | — |

Certifications: tick **all three** ("does not sell data", "does not use for
unrelated purposes", "does not use for determining creditworthiness").

## 8. Notes for reviewers (dashboard field)

```
PrintHub Pro is a printing tool with NO server and NO data collection.
All communication goes to 127.0.0.1 (the user's own machine).

TESTING WITHOUT THE HUB:
The extension is fully installable and openable without the companion hub.
The popup will show "Checking hub..." then "Hub not running" with an
Options link — this is the expected graceful state. All popup controls,
options page, context menu and hotkey remain functional and safe to test.
No page content is read or transmitted in this state.

TESTING WITH THE HUB (full flow):
1. Download the free hub from https://github.com/bitdreamit/PrintHub-Pro/releases
   (Windows Setup exe includes an embedded Python runtime; nothing else needed),
   run it, then reload the extension — the popup shows "Hub connected".
2. Click "Print this page" or press Alt+P — the page is sent to the local
   hub, which forwards it to the OS default printer. If no printer exists,
   the job fails gracefully with a notification.

The <all_urls> content script (content/relay.js) only relays window messages
for user-triggered print actions and the window.printhub JS API; it collects
no data. Source: https://github.com/bitdreamit/PrintHub-Pro
```

## 9. Screenshot files (Privacy → nothing; Store listing → Screenshots)

Upload from `screenshots/`, in this order:
1. `shot-1-popup.png` (1280×800) — main hero
2. `shot-2-how-it-works.png` (1280×800)
3. `shot-3-options.png` (1280×800)

Optional extra: `promo-tile-440x280.png` → "Promotional images → Small tile".
Store icon (128×128) is taken automatically from the zip — no upload needed.
