#!/usr/bin/env python3
"""eBay Listing Advisor — analyzes your active listings and suggests improvements."""

import asyncio
import json
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import webbrowser
import tempfile
from datetime import datetime
from pathlib import Path

# ── API key management ──────────────────────────────────────────────────────

KEY_FILE = Path.home() / ".ebay_advisor_key"


def load_api_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    return None


def save_api_key(key: str):
    KEY_FILE.write_text(key.strip())
    KEY_FILE.chmod(0o600)


# ── eBay scraper ─────────────────────────────────────────────────────────────

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
CHROME_PROFILE = str(Path.home() / "Library/Application Support/Google/Chrome")


async def scrape_listings(status_cb) -> list[dict]:
    """Open Chrome with the user's profile (keeps eBay login), scrape all active listings."""
    from playwright.async_api import async_playwright

    listings = []

    async with async_playwright() as p:
        status_cb("Opening Chrome with your eBay session…")
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE,
            executable_path=CHROME,
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
            slow_mo=200,
        )

        page = await ctx.new_page()

        status_cb("Navigating to eBay Seller Hub…")
        await page.goto("https://www.ebay.com/sh/lst/active", wait_until="networkidle", timeout=30000)

        # Handle login redirect
        if "signin" in page.url or "login" in page.url:
            status_cb("⚠️  Please sign in to eBay in the Chrome window, then click Continue.")
            await page.wait_for_url("**/sh/lst/active", timeout=120000)

        # Collect listing rows — iterate through pagination
        page_num = 1
        while True:
            status_cb(f"Reading listings page {page_num}…")
            await page.wait_for_selector(".shui-dt-row, [data-test-id='listing-row']", timeout=15000)

            rows = await page.query_selector_all(".shui-dt-row, [data-test-id='listing-row']")
            if not rows:
                break

            for row in rows:
                try:
                    title_el = await row.query_selector(".SECONDARY_INFO a, [data-test-id='listing-title'] a, h3 a")
                    if not title_el:
                        continue
                    title = (await title_el.inner_text()).strip()
                    href = await title_el.get_attribute("href")
                    if href and not href.startswith("http"):
                        href = "https://www.ebay.com" + href

                    price_el = await row.query_selector("[data-test-id='price'] span, .PRICE")
                    price = (await price_el.inner_text()).strip() if price_el else "N/A"

                    watchers_el = await row.query_selector("[data-test-id='watchers'], .WATCHES")
                    watchers = (await watchers_el.inner_text()).strip() if watchers_el else "0"

                    qty_el = await row.query_selector("[data-test-id='quantity'], .QUANTITY")
                    qty = (await qty_el.inner_text()).strip() if qty_el else "1"

                    listings.append({"title": title, "url": href, "price": price, "watchers": watchers, "qty": qty})
                except Exception:
                    continue

            # Next page
            next_btn = await page.query_selector("button[aria-label='Next page']:not([disabled]), .pagination__next:not([disabled])")
            if next_btn:
                await next_btn.click()
                await page.wait_for_load_state("networkidle")
                page_num += 1
            else:
                break

        # For each listing, grab the full detail page
        detailed = []
        for i, listing in enumerate(listings):
            status_cb(f"Reading listing {i+1}/{len(listings)}: {listing['title'][:50]}…")
            if not listing.get("url"):
                detailed.append(listing)
                continue
            try:
                detail_page = await ctx.new_page()
                await detail_page.goto(listing["url"], wait_until="domcontentloaded", timeout=20000)

                desc_el = await detail_page.query_selector("#desc_div, #vi-desc-maincntr, .ux-layout-section--listings")
                description = (await desc_el.inner_text()).strip()[:2000] if desc_el else ""

                # Item specifics
                specifics_els = await detail_page.query_selector_all(".ux-labels-values__labels, .itemAttr")
                specifics = []
                for s in specifics_els[:20]:
                    text = (await s.inner_text()).strip()
                    if text:
                        specifics.append(text)

                # Photo count
                photos_els = await detail_page.query_selector_all(".ux-image-carousel-item img, .vi-image-gallery img")
                photo_count = len(photos_els)

                # Shipping
                ship_el = await detail_page.query_selector(".ux-labels-values--shipping .ux-textspans, #fshippingCost")
                shipping = (await ship_el.inner_text()).strip() if ship_el else "Not found"

                # Returns
                returns_el = await detail_page.query_selector(".ux-labels-values--returns .ux-textspans, #vi-ret-accrd-txt")
                returns = (await returns_el.inner_text()).strip() if returns_el else "No returns"

                # Category
                cat_el = await detail_page.query_selector_all(".seo-breadcrumb-text a")
                category = " > ".join([(await c.inner_text()).strip() for c in cat_el[-3:]]) if cat_el else ""

                await detail_page.close()

                detailed.append({
                    **listing,
                    "description": description,
                    "item_specifics": ", ".join(specifics),
                    "photo_count": photo_count,
                    "shipping": shipping,
                    "returns": returns,
                    "category": category,
                })
            except Exception as e:
                detailed.append({**listing, "error": str(e)})

        # Search sold comps for each listing
        for i, listing in enumerate(detailed):
            status_cb(f"Checking sold prices for: {listing['title'][:45]}…")
            try:
                keywords = "+".join(listing["title"].split()[:6])
                comp_page = await ctx.new_page()
                await comp_page.goto(
                    f"https://www.ebay.com/sch/i.html?_nkw={keywords}&LH_Sold=1&LH_Complete=1",
                    wait_until="domcontentloaded", timeout=15000
                )
                sold_els = await comp_page.query_selector_all(".s-item__price")
                sold_prices = []
                for el in sold_els[:10]:
                    text = (await el.inner_text()).strip()
                    sold_prices.append(text)
                listing["sold_comps"] = sold_prices
                await comp_page.close()
            except Exception:
                listing["sold_comps"] = []

        await ctx.close()
        return detailed


# ── AI analysis ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert eBay seller and marketplace consultant with 15+ years of experience.
Analyze the provided eBay listing data and give specific, actionable advice to improve each listing's
visibility, conversion rate, and pricing. Be direct and specific — name exact changes to make.
When sold comps are available, cite the actual prices you see."""

def analyze_with_claude(listings: list[dict], api_key: str, status_cb) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    listing_data = json.dumps(listings, indent=2)

    status_cb("Sending listings to Claude AI for analysis…")

    prompt = f"""Here are my active eBay listings with full details and recently sold comparable items:

{listing_data}

Please analyze each listing and provide:

1. **Price Assessment** — Is my price too high, too low, or about right? Reference the actual sold comp prices.
2. **Title Improvement** — eBay allows ~80 characters. Is the title optimised with key search terms (brand, model, condition, size, colour)? Provide an improved title if needed.
3. **Description Quality** — Is it complete, accurate, mentions condition, contents, any flaws?
4. **Item Specifics** — Are key specifics filled in? Missing specifics reduce search visibility.
5. **Photos** — eBay allows 24 free photos. Are there enough? Is the main image likely clear?
6. **Shipping** — Free shipping boosts search rank. Is the shipping strategy competitive?
7. **Returns Policy** — Listings with returns rank higher. Do I have one?
8. **Overall Rating** — 🟢 Good / 🟡 Needs Work / 🔴 Needs Significant Improvement
9. **Top 3 Priority Actions** — The highest-impact changes, in priority order.

After all individual listings, provide:
- A summary table with listing name, current price, recommended price, and rating
- An overall priority action list (the 5 most impactful things to do across all listings)

Be specific. If a listing is good, say so. Don't invent problems."""

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=8192,
        messages=[{"role": "user", "content": prompt}],
        system=SYSTEM_PROMPT,
    )

    return message.content[0].text


# ── HTML report ──────────────────────────────────────────────────────────────

def build_html_report(analysis: str, listings: list[dict]) -> str:
    now = datetime.now().strftime("%d %B %Y, %H:%M")
    count = len(listings)

    # Convert markdown-ish analysis to HTML (basic)
    html_analysis = analysis \
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
        .replace("🟢", '<span class="good">🟢</span>') \
        .replace("🟡", '<span class="warn">🟡</span>') \
        .replace("🔴", '<span class="bad">🔴</span>')

    # Bold **text**
    import re
    html_analysis = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_analysis)
    # Headers
    html_analysis = re.sub(r"^#{1,3}\s+(.+)$", r"<h3>\1</h3>", html_analysis, flags=re.MULTILINE)
    # Newlines
    html_analysis = html_analysis.replace("\n\n", "</p><p>").replace("\n", "<br>")
    html_analysis = "<p>" + html_analysis + "</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>eBay Listing Advisor Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 900px; margin: 40px auto; padding: 0 20px; color: #1a1a1a; background: #f5f5f7; }}
  h1 {{ color: #e43137; border-bottom: 3px solid #e43137; padding-bottom: 10px; }}
  h2 {{ color: #333; margin-top: 2em; }}
  h3 {{ color: #444; margin-top: 1.5em; }}
  .meta {{ color: #666; margin-bottom: 2em; }}
  .card {{ background: white; border-radius: 12px; padding: 24px; margin: 20px 0;
           box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
  .good {{ color: #2e7d32; font-weight: bold; }}
  .warn {{ color: #e65100; font-weight: bold; }}
  .bad  {{ color: #c62828; font-weight: bold; }}
  strong {{ color: #222; }}
  p {{ line-height: 1.7; margin: 0.5em 0; }}
  .footer {{ text-align: center; color: #999; font-size: 0.85em; margin-top: 3em; padding: 20px; }}
</style>
</head>
<body>
<h1>eBay Listing Advisor Report</h1>
<p class="meta">Generated {now} &nbsp;·&nbsp; {count} active listing{"s" if count != 1 else ""} analysed</p>
<div class="card">
{html_analysis}
</div>
<div class="footer">Generated by eBay Advisor · Powered by Claude AI</div>
</body>
</html>"""


# ── GUI ───────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("eBay Listing Advisor")
        self.geometry("560x420")
        self.resizable(False, False)
        self.configure(bg="#f5f5f7")
        self._build_ui()
        self._report_path = None

    def _build_ui(self):
        pad = {"padx": 24, "pady": 10}

        # Header
        tk.Label(self, text="eBay Listing Advisor", font=("SF Pro Display", 22, "bold"),
                 bg="#f5f5f7", fg="#e43137").pack(pady=(28, 2))
        tk.Label(self, text="Analyses your active listings and suggests improvements",
                 font=("SF Pro Text", 12), bg="#f5f5f7", fg="#666").pack()

        # Key status
        self._key_var = tk.StringVar()
        self._update_key_label()
        self._key_lbl = tk.Label(self, textvariable=self._key_var,
                                  font=("SF Pro Text", 11), bg="#f5f5f7", fg="#888")
        self._key_lbl.pack(pady=(12, 0))

        tk.Button(self, text="Set / Change API Key", command=self._set_key,
                  font=("SF Pro Text", 11), bg="#f5f5f7", fg="#0071e3",
                  bd=0, cursor="hand2").pack()

        # Divider
        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=24, pady=16)

        # Status
        self._status_var = tk.StringVar(value="Ready — click Analyse to start.")
        tk.Label(self, textvariable=self._status_var, wraplength=500,
                 font=("SF Pro Text", 11), bg="#f5f5f7", fg="#444",
                 justify="center").pack(**pad)

        # Progress bar
        self._progress = ttk.Progressbar(self, mode="indeterminate", length=400)
        self._progress.pack(pady=4)

        # Buttons
        btn_frame = tk.Frame(self, bg="#f5f5f7")
        btn_frame.pack(pady=20)

        self._analyse_btn = tk.Button(
            btn_frame, text="  Analyse My Listings  ",
            font=("SF Pro Text", 14, "bold"),
            bg="#e43137", fg="white", activebackground="#c0282d",
            bd=0, padx=16, pady=10, cursor="hand2",
            command=self._start_analysis,
        )
        self._analyse_btn.pack(side="left", padx=8)

        self._report_btn = tk.Button(
            btn_frame, text="  Open Last Report  ",
            font=("SF Pro Text", 14),
            bg="#555", fg="white", activebackground="#333",
            bd=0, padx=16, pady=10, cursor="hand2",
            state="disabled",
            command=self._open_report,
        )
        self._report_btn.pack(side="left", padx=8)

        # Footer
        tk.Label(self, text="eBay must be signed in on Chrome before you click Analyse.",
                 font=("SF Pro Text", 10), bg="#f5f5f7", fg="#aaa").pack(side="bottom", pady=10)

    def _update_key_label(self):
        key = load_api_key()
        if key:
            self._key_var.set(f"API key: ····{key[-6:]}")
        else:
            self._key_var.set("⚠️  No API key set")

    def _set_key(self):
        key = simpledialog.askstring(
            "Anthropic API Key",
            "Enter your Anthropic API key\n(from console.anthropic.com):",
            show="*", parent=self
        )
        if key and key.strip().startswith("sk-"):
            save_api_key(key.strip())
            self._update_key_label()
        elif key:
            messagebox.showerror("Invalid Key", "API keys start with 'sk-'. Please check and try again.")

    def _set_status(self, msg: str):
        self._status_var.set(msg)
        self.update_idletasks()

    def _start_analysis(self):
        api_key = load_api_key()
        if not api_key:
            messagebox.showerror("No API Key", "Please set your Anthropic API key first.")
            return

        self._analyse_btn.config(state="disabled")
        self._progress.start(12)
        self._set_status("Starting…")

        def run():
            try:
                listings = asyncio.run(scrape_listings(self._set_status))
                if not listings:
                    self._set_status("No active listings found on eBay.")
                    return

                self._set_status(f"Found {len(listings)} listing(s). Analysing with Claude AI…")
                analysis = analyze_with_claude(listings, api_key, self._set_status)

                self._set_status("Building report…")
                html = build_html_report(analysis, listings)

                report_dir = Path.home() / "Documents" / "eBay Advisor Reports"
                report_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                self._report_path = report_dir / f"ebay_report_{stamp}.html"
                self._report_path.write_text(html)

                self._set_status(f"✅  Done! Report saved to {self._report_path.name}")
                self._report_btn.config(state="normal")
                webbrowser.open(self._report_path.as_uri())

            except Exception as e:
                self._set_status(f"Error: {e}")
                messagebox.showerror("Error", str(e))
            finally:
                self._progress.stop()
                self._analyse_btn.config(state="normal")

        threading.Thread(target=run, daemon=True).start()

    def _open_report(self):
        if self._report_path and self._report_path.exists():
            webbrowser.open(self._report_path.as_uri())


if __name__ == "__main__":
    app = App()
    app.mainloop()
