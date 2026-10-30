# Privacy Policy — PrintHub Pro

Applies to the PrintHub Pro browser extension and its companion local hub application.
Last updated: October 14, 2026

> **Short version:** PrintHub Pro works 100% on your own computer. Your pages and print jobs never reach us — there is no server to reach. We do not collect, store, sell, or share any personal data.

## 1. Who we are
PrintHub Pro is developed and maintained by **Bitdream IT** ("we", "us"). This policy covers the PrintHub Pro Chrome extension and the optional local hub application that installs on your computer to talk to your printer.

## 2. What the extension does
The extension lets you print the web page you are viewing — or save it as a PDF, or print a screenshot of it — on a printer connected to your own computer, without showing Chrome's print dialog. To do this it prepares a print job in your browser and hands it to the **PrintHub Pro hub**, a small program that runs on *your* machine and sends the job to *your* printer.

## 3. What data is processed, and where

| Data | Where it goes | Why |
|---|---|---|
| The content of the page you choose to print (rendered as PDF or image) | Only from your browser to the hub on the same computer (`127.0.0.1`) | Creating the print job you asked for |
| Page title and address of the tab you print | Stored locally in your browser (chrome.storage), shown as the job name | Naming and listing your recent jobs in the popup |
| Your settings (printer, paper size, copies, hub address) | Stored locally in your browser only | Remembering your preferences |
| Print job history (names, status, timestamp) | Stored locally in your browser only | Showing "Recent jobs" in the popup |

Nothing in this list is transmitted over the Internet by the extension. There is no analytics, no telemetry, no crash reporting, no advertising, and no account system. If you uninstall the extension and the hub, all of the above data is removed from your computer with them.

## 4. Permissions the extension requests, and why
- **Read and change all your data on all websites** (`<all_urls>`): a tiny helper script runs on pages so that (a) the "print this page" feature can capture the page you are viewing, and (b) websites that integrate our `window.printhub` JavaScript API can offer direct printing. The script reads nothing and sends nothing unless *you* trigger a print action. It can be turned off in Options.
- **tabs / activeTab**: to know the title and address of the tab you are printing, so the job gets a readable name.
- **scripting**: to start the page capture only when you click Print, right-click → Print, or use the hotkey.
- **storage**: to save your settings and recent-job list locally in your browser.
- **notifications**: to tell you whether a print job succeeded or failed.
- **contextMenus**: to add "Print with PrintHub Pro" to the right-click menu.
- **Access to `127.0.0.1` / `localhost`**: to talk to the hub program on your own computer. This address can never reach the Internet.

## 5. What we never do
- We never upload, collect, or view your pages, files, print jobs, or browsing history.
- We never sell or share data with third parties — there is no data to share.
- We never use your data for advertising, profiling, credit scoring, or any unrelated purpose.
- We never transfer data to other countries, because no data ever leaves your computer.

## 6. The local hub application
The hub is optional for browsing but required for printing. It listens only on your own machine (by default `127.0.0.1:9235`, or your LAN if you explicitly enable it with a security token) and forwards jobs to the printers installed in your operating system. The hub does not connect to any Bitdream IT server. Its source code is public in our GitHub repository for anyone to inspect.

## 7. Children's privacy
The extension is a general-purpose printing tool. Because no personal data is collected from any user of any age, no data concerning children is collected either.

## 8. Changes to this policy
If this policy changes, the new version will be posted at this same address with a new "last updated" date. If a change ever materially affects how data is handled, the extension will also show a notice in its store listing description.

## 9. Contact
Questions, requests, or complaints? Open an issue at [github.com/bitdreamit/PrintHub-Pro/issues](https://github.com/bitdreamit/PrintHub-Pro/issues) or email **support@bitdreamit.com**.
