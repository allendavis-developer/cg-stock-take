#!/usr/bin/env python3
import asyncio
import sys
import os
import re
import subprocess
from pathlib import Path

# Local installation paths
SCRIPT_DIR = Path(__file__).resolve().parent
LOCAL_PACKAGES_DIR = SCRIPT_DIR / "app" / "python"
LOCAL_BROWSERS_DIR = SCRIPT_DIR / "app" / "python" / "local-browsers"
INSTALL_MARKER = SCRIPT_DIR / ".dependencies_installed"
USER_DATA_DIR = SCRIPT_DIR / "playwright_user_data"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(LOCAL_BROWSERS_DIR)

# Add local packages to Python path
sys.path.insert(0, str(LOCAL_PACKAGES_DIR))

def bootstrap_pip():
    print("[INFO] Bootstrapping pip using get-pip.py...")

    get_pip_path = SCRIPT_DIR / "vendor" / "get-pip.py"
    if not get_pip_path.exists():
        print(f"[ERROR] get-pip.py not found at {get_pip_path}")
        sys.exit(1)

    try:
        subprocess.run(
            [sys.executable, str(get_pip_path), "--upgrade", "--user"],
            check=True
        )
        print("[INFO] pip bootstrapped successfully!")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to bootstrap pip: {e}")
        sys.exit(1)


def install_dependencies():
    """Install required packages locally on first run."""
    if INSTALL_MARKER.exists():
        return  # Already installed
    
    print("[INFO] First run detected. Installing dependencies locally...")
    
    # Create local packages directory
    LOCAL_PACKAGES_DIR.mkdir(parents=True, exist_ok=True)

    # Install playwright locally
    bootstrap_pip()
    print("[INFO] Installing playwright to local directory...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", 
             "--target", str(LOCAL_PACKAGES_DIR), 
             "playwright"],
            check=True
        )
        print("[INFO] playwright installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to install playwright: {e}")
        sys.exit(1)
    
    # Install Playwright browsers locally using the local package
    print("[INFO] Installing Chromium browser to local directory...")

    # Install Playwright browsers locally using the local package
    print("[INFO] Installing Chromium browser to local directory...")

    env = os.environ.copy()
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(LOCAL_BROWSERS_DIR)
    env["PYTHONPATH"] = str(LOCAL_PACKAGES_DIR)

    try:
        # Use 'python -m playwright install chromium' instead of importing __main__
        subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys; sys.path.insert(0, r'{LOCAL_PACKAGES_DIR}'); import playwright.__main__ as p; p.main()",
                "install",
                "chromium"
            ],
            check=True,
            env=env
        )
        print("[INFO] Chromium installed successfully!")
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to install Chromium: {e}")
        sys.exit(1)


    # Create marker file
    INSTALL_MARKER.touch()
    print("[INFO] All dependencies installed successfully!")
    print("[INFO] Setup complete!")
    print("[INFO] Please close this script and run it again to continue.")
    sys.exit(0)

# Install dependencies before importing playwright
install_dependencies()

# Set browser path for local installation
import os
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(LOCAL_BROWSERS_DIR)

from playwright.async_api import async_playwright


async def wait_for_login(page):
    print("[INFO] Navigating to NOSPOS...")
    await page.goto("https://nospos.com/stock/search")
    await page.wait_for_load_state("networkidle")

    # Detect login redirection
    if "login" in page.url:
        print("[INFO] Please complete login manually in the browser window.")
        try:
            await page.wait_for_url("**/nospos.com/**")
        except Exception as e:
            print(f"[ERROR] Page closed during login: {e}")
            sys.exit(1)

    print("[INFO] Waiting for NOSPOS to finish redirects...")

    max_checks = 60
    checks = 0

    while checks < max_checks:
        if page.is_closed():
            print("[ERROR] Page closed before login confirmation.")
            sys.exit(1)

        current_url = page.url.rstrip("/")
        logged_in = (
            current_url == "https://nospos.com"
            or "/stock/search" in current_url
        )

        if logged_in:
            print("[INFO] Login confirmed. You're inside NOSPOS.")
            return True

        await asyncio.sleep(1)
        checks += 1

    print("[ERROR] Timeout waiting for login to finish.")
    return False


async def navigate_to_take(page, take_id):
    url = f"https://nospos.com/stock/take-legacy/view?id={take_id}"
    print(f"[INFO] Navigating to: {url}")
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    print("[INFO] Arrived at TAKE page.")

    # STEP 0: Press the "Investigate" button
    investigate_button = await page.query_selector("button.btn-investigate")
    if investigate_button:
        print("[INFO] Clicking 'Investigate' button...")
        await investigate_button.click()
        # Wait a bit for dynamic table to populate
        await asyncio.sleep(1)
    else:
        print("[WARNING] 'Investigate' button not found.")

    # STEP 1: Check if tbody exists
    exists = await page.evaluate("""() => !!document.querySelector("#tbody-investigate")""")
    print(f"[DEBUG] tbody-investigate exists? {exists}")

    # STEP 2: Log innerHTML preview
    html_preview = await page.evaluate("""
        () => {
            const el = document.querySelector("#tbody-investigate");
            return el ? el.innerHTML.slice(0, 500) : null;
        }
    """)
    print(f"[DEBUG] tbody HTML preview: {html_preview!r}")

    # STEP 3: Count rows
    row_count = await page.evaluate("""
        () => document.querySelectorAll("#tbody-investigate tr").length
    """)
    print(f"[DEBUG] Number of TR rows detected: {row_count}")

    # STEP 4: Retry if rows haven't loaded yet
    if row_count == 0:
        print("[DEBUG] No rows yet, waiting for dynamic load...")
        for i in range(10):
            await asyncio.sleep(1)
            row_count = await page.evaluate("""
                () => document.querySelectorAll("#tbody-investigate tr").length
            """)
            print(f"[DEBUG] Retry {i+1}/10 – rows: {row_count}")
            if row_count > 0:
                break

    # STEP 5: Extract data
    data = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll("#tbody-investigate tr");
            const items = [];
            rows.forEach(row => {
                const cells = row.querySelectorAll("td");
                if (cells.length === 0) return;
                const clean = (v) => v?.textContent?.trim() || "";
                items.push({
                    category:  clean(cells[0]),
                    serial:    clean(cells[1]),
                    name:      clean(cells[2]),
                    inStock:   Number(clean(cells[3])),
                    scanned:   Number(clean(cells[4]?.childNodes?.[0]?.textContent?.trim()) || 0),
                    location:  clean(cells[5]),
                    diffStock: Number(clean(cells[6])),
                    diffCost:  Number(clean(cells[7]))
                });
            });
            return items;
        }
    """)

    print("[INFO] Extracted items:")

    # STEP 6: Log branch name and H3 content
    branch_name, h3_content = await page.evaluate("""
    () => {
        const branchEl = document.querySelector('#navbar-mobile-collapse > ul.nav.navbar-nav.action-links > li:nth-child(1) > a span');
        const h3El = document.querySelector('body > div.min-vh-100.d-flex.flex-column > main > div.row > div > div > div:nth-child(1) > div > div:nth-child(1) > h3');
        return [
            branchEl ? branchEl.textContent.trim() : 'Unknown Branch',
            h3El ? h3El.textContent.trim() : 'No H3 Found'
        ];
    }
    """)

    print(f"[INFO] Page context: {branch_name} - {h3_content}")


    # STEP 7: Filter items with diffStock < 0
    missing_items = [item for item in data if item["diffStock"] < 0]
    # Log only the serials (barcodes)
    missing_serials = [item["serial"] for item in missing_items]
    print(f"[INFO] Missing item barserials ({len(missing_serials)} found):")
    for serial in missing_serials:
        print(f" - {serial}")

    # STEP 8: Save missing barserials to file
    # Make a safe filename from branch + H3
    safe_filename = re.sub(r'[^A-Za-z0-9_-]+', '_', f"{branch_name}-{h3_content}") + ".txt"

    # Extract barserials from missing items
    barserials = [item["serial"] for item in missing_items]

    # Write each barserial on a new line
    with open(safe_filename, "w", encoding="utf-8") as f:
        for serial in barserials:
            f.write(serial + "\n")

    print(f"[INFO] Saved {len(barserials)} missing barserials to {safe_filename}")

    return missing_items


async def main():
    # --- Prompt user first ---
    try:
        take_id = input("Enter TAKE ID: ").strip()
    except KeyboardInterrupt:
        print("\n[INFO] Aborted by user.")
        return

    async with async_playwright() as pw:
        print("[INFO] Launching browser...")
        browser = await pw.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=["--start-maximized"]
        )
        page = await browser.new_page()

        logged_in = await wait_for_login(page)
        if not logged_in:
            return

        await navigate_to_take(page, take_id)

        print("[INFO] Ready for further automation.")


if __name__ == "__main__":
    asyncio.run(main())