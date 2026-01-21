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

import csv
import random
import asyncio

CSV_FILE = "stock_data.csv"
MAX_CATEGORY_DEPTH = 0  # will track maximum category depth dynamically

# Store rows temporarily so we can compute max depth before writing
all_rows = []

async def scrape_leaf_table(page, path, url):
    global MAX_CATEGORY_DEPTH, all_rows

    MAX_CATEGORY_DEPTH = max(MAX_CATEGORY_DEPTH, len(path))

    print(f"[LEAF] Scraping leaf table at path: {' > '.join(path)}")
    await page.goto(url)
    await page.wait_for_load_state("networkidle")
    await asyncio.sleep(random.uniform(1, 2))  # polite delay

    # Detect headers
    headers = await page.evaluate("""
        () => {
            const ths = document.querySelectorAll('#stock-valuation-table > table > thead > tr > th');
            return Array.from(ths).map(th => th.textContent.trim());
        }
    """)

    if not headers or headers[0].lower() != "barserial":
        print(f"[WARNING] Expected Barserial table, got different headers at {url}")
        return

    # Extract rows
    rows = await page.evaluate("""
        () => {
            const trs = document.querySelectorAll('#stock-valuation-table > table > tbody > tr');
            return Array.from(trs).map(tr => {
                return Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim());
            });
        }
    """)

    if not rows:
        print(f"[WARNING] No rows found in leaf table at {url}")
        return

    # Store rows temporarily with category path
    for row in rows:
        all_rows.append((path.copy(), row))


# --- CONFIG FLAG ---
TEST_FIRST_TOP_CATEGORY_ONLY = False  # Set False to explore all top-level categories

async def explore_category(page, url, path=None, is_top_level=False):
    if path is None:
        path = []

    await asyncio.sleep(random.uniform(1.5, 3.0))  # random delay

    response = await page.goto(url)
    await page.wait_for_load_state("networkidle")

    if response.status == 429:
        print("[WARNING] Rate limited! Sleeping 30 seconds...")
        await asyncio.sleep(30)
        return await explore_category(page, url, path, is_top_level)

    if page.is_closed():
        print("[ERROR] Page was closed unexpectedly.")
        return

    table_type = await page.evaluate("""
        () => {
            const th = document.querySelector('#stock-valuation-table > table > thead > tr > th');
            return th ? th.textContent.trim() : null;
        }
    """)

    if table_type is None:
        # Check if table exists but contains only "No results"
        empty_table = await page.evaluate("""
            () => {
                const td = document.querySelector('#stock-valuation-table > table > tbody > tr > td');
                if (!td) return false;
                return /no/i.test(td.textContent.trim());
            }
        """)

        if empty_table:
            print(f"[INFO] Empty table detected at {url}, adding category path only.")
            # Add a row with empty leaf columns
            leaf_headers = ["Barserial", "Name", "Quantity", "Retail", "Cost", "VAT", "Net", "Total Margin", "Margin %"]
            all_rows.append((path.copy(), [""] * len(leaf_headers)))
        else:
            print(f"[WARNING] No table found at {url}")
        return


    if table_type.lower() == "barserial":
        await scrape_leaf_table(page, path, url)
        return

    # Category table: extract subcategories
    subcategories = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll('#stock-valuation-table > table > tbody > tr');
            return Array.from(rows).map(row => {
                const link = row.querySelector('td:first-child a');
                if (!link) return null;
                return {
                    name: link.textContent.trim(),
                    url: link.href
                };
            }).filter(Boolean);
        }
    """)

    if not subcategories:
        print(f"[WARNING] No subcategories found at {url}")
        return

    for i, subcat in enumerate(subcategories):
        # Only restrict at the top-level
        if is_top_level and TEST_FIRST_TOP_CATEGORY_ONLY and i > 0:
            print("[INFO] TEST MODE: only exploring first top-level category, skipping the rest.")
            break

        # Recurse; all lower levels explored fully
        await explore_category(page, subcat["url"], path + [subcat["name"]], is_top_level=False)



async def stock_process(page):
    top_url = "https://nospos.com/reports/stock/category-valuation"
    global MAX_CATEGORY_DEPTH, all_rows

    # Recursively traverse and scrape
    await explore_category(page, top_url, is_top_level=True)

    # Prepare CSV headers
    category_headers = [f"Category Level {i+1}" for i in range(MAX_CATEGORY_DEPTH)]
    leaf_headers = ["Barserial", "Name", "Quantity", "Retail", "Cost", "VAT", "Net", "Total Margin", "Margin %"]
    headers = category_headers + leaf_headers

    # Write to CSV
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for path, row in all_rows:
            padded_path = path + [""] * (MAX_CATEGORY_DEPTH - len(path))
            writer.writerow(padded_path + row)

    print(f"[INFO] Scraping complete. CSV saved as {CSV_FILE}")


async def save_receipt_pdf_in_context(context, receipt_url, pdf_path="receipt.pdf"):
    # Use existing context
    page = await context.new_page()
    print(f"[INFO] Navigating to {receipt_url}")
    await page.goto(receipt_url)
    await page.wait_for_load_state("networkidle")
    print(f"[INFO] Saving PDF to {pdf_path}")
    await page.pdf(
        path=pdf_path,
        format="A4",
        print_background=True,
        margin={"top": "10mm", "bottom": "10mm"}
    )
    await page.close()
    print("[INFO] PDF saved successfully.")


async def stock_process_sales(page, csv_file):
    """Read CSV, print Barserials, then navigate to a NOSPOS page and save receipt PDF."""
    print(f"[INFO] Reading sales CSV: {csv_file}")
    try:
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if "Barserial" not in reader.fieldnames:
                print("[WARNING] CSV does not contain a 'Barserial' column.")
                return

            barserials = []
            for i, row in enumerate(reader, start=1):
                barserial = row.get("Barserial", "")
                print(f"Row {i}: Barserial = {barserial}")
                if barserial:
                    barserials.append(barserial)

    except FileNotFoundError:
        print(f"[ERROR] CSV file not found: {csv_file}")
        return
    except Exception as e:
        print(f"[ERROR] Failed to read CSV: {e}")
        return

    # --- Navigate to the NOSPOS page ---
    target_url = "https://nospos.com/newsales/cart/46064/view"

    # print(f"[INFO] Navigating to {target_url} ...")
    # await page.goto(target_url)
    # await page.wait_for_load_state("networkidle")
    # print(f"[INFO] Arrived at {target_url}.")
    
    await save_receipt_pdf_in_context(page.context, "https://nospos.com/print/sale-receipt?id=46064")



async def main():
    if len(sys.argv) < 2:
        print("[ERROR] Missing mode.")
        print("Usage:")
        print("  python script.py take <TAKE_ID>")
        print("  python script.py stock_process")
        print("  python script.py stock_process_sales <CSV_FILE>")
        return

    mode = sys.argv[1].lower()

    take_id = None
    csv_file = None
    if mode == "take":
        if len(sys.argv) < 3:
            print("[ERROR] TAKE mode requires a TAKE ID.")
            return
        take_id = sys.argv[2]
    elif mode == "stock_process":
        pass
    elif mode == "stock_process_sales":
        if len(sys.argv) < 3:
            print("[ERROR] stock_process_sales mode requires a CSV file path.")
            return
        csv_file = sys.argv[2]
    else:
        print(f"[ERROR] Unknown mode: {mode}")
        return

    async with async_playwright() as pw:
        print("[INFO] Launching browser...")
        browser = await pw.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=["--start-maximized"]
        )
        page = await browser.new_page()

        # Wait for login first
        logged_in = await wait_for_login(page)
        if not logged_in:
            return

        # After login
        if csv_file:
            await stock_process_sales(page, csv_file)
        if mode == "take":
            await navigate_to_take(page, take_id)
        elif mode == "stock_process":
            await stock_process(page)

        print("[INFO] Done.")



if __name__ == "__main__":
    asyncio.run(main())