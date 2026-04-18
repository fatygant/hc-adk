#!/usr/bin/env python3
"""Render docs/pitch/pitch.html to pitch.pdf via headless Chromium (Playwright)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright


async def main() -> None:
    root = Path(__file__).resolve().parent
    html = root / "pitch.html"
    pdf = root / "pitch.pdf"
    uri = html.as_uri()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(uri, wait_until="networkidle")
        await page.evaluate("document.fonts.ready")
        await page.emulate_media(media="print")
        await page.pdf(
            path=str(pdf),
            print_background=True,
            prefer_css_page_size=True,
            margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
        )
        await browser.close()

    print(f"Wrote {pdf}")


if __name__ == "__main__":
    asyncio.run(main())
