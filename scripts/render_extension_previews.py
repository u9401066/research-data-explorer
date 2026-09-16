"""Render native SVGs as Marketplace-compatible README previews.

Optional maintainer command: uv run --with playwright python scripts/render_extension_previews.py
Install Chromium with Playwright first, or pass --browser-executable.
The SVGs remain the canonical editable sources and are also shipped in the VSIX.
"""

import argparse
from pathlib import Path


def main() -> None:
    from playwright.sync_api import sync_playwright

    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    assets = Path(__file__).resolve().parents[1] / "docs/assets"
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, executable_path=args.browser_executable)
        for name, width, height in [("evidence-chain", 1200, 300), ("autoresearch", 720, 380)]:
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=2
            )
            page.goto((assets / f"{name}.svg").as_uri(), wait_until="load")
            page.screenshot(path=str(assets / f"{name}.png"), omit_background=True)
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
