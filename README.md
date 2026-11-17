# eBay Listing Advisor

A Mac app that reads all your active eBay listings and uses Claude AI to suggest improvements to titles, pricing, descriptions, photos, shipping and more. Runs on demand — just click the icon.

## What it does

1. Opens Chrome with your existing eBay login (no need to sign in again)
2. Scrapes every active listing including photos, item specifics, shipping and returns
3. Checks recently sold comparable items to validate your pricing
4. Sends everything to Claude AI for expert analysis
5. Produces a formatted HTML report that opens automatically in your browser

## Requirements

- macOS 12 or later
- Python 3.10+
- Google Chrome (signed in to eBay)
- Anthropic API key (free tier available at [console.anthropic.com](https://console.anthropic.com))

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/ebay-advisor.git
cd ebay-advisor
bash install.sh
```

This installs dependencies, sets up Playwright, and adds **eBay Advisor.app** to `/Applications`.

## First run

1. Open **eBay Advisor** from Launchpad or `/Applications`
2. Click **Set / Change API Key** and paste your Anthropic key
3. Make sure Chrome is open and signed in to eBay
4. Click **Analyse My Listings**

Reports are saved to `~/Documents/eBay Advisor Reports/` and open automatically in your browser.

## Notes

- Chrome will open briefly during the scan — this is normal
- The scan takes roughly 1–2 minutes per listing
- Run it whenever you want a fresh review — there is no schedule or background process
