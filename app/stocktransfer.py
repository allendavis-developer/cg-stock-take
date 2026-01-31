#!/usr/bin/env python3
import asyncio
import sys
import os
import re
import subprocess
import math
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
HOME_URL = "https://nospos.com"
SALE_BUTTON_SELECTOR = 'a.btn.btn-massive.btn-massive-outline[href="/newsales/cart/create"]'


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
SESSION_FILE = SCRIPT_DIR / "auth_session.json"


async def wait_for_login(page):
    if SESSION_FILE.exists():
        print("[INFO] Loading saved session...")
        try:
            await page.context.storage_state(path=str(SESSION_FILE))
            await page.goto("https://nospos.com/stock/search")
            await page.wait_for_load_state("networkidle")
            
            if "login" not in page.url:
                print("[INFO] Session restored successfully!")
                return True
        except:
            print("[INFO] Session expired, need to login again")


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

    max_checks = 120
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
                
            # Save session after successful login
            await page.context.storage_state(path=str(SESSION_FILE))
            print("[INFO] Session saved for future use")
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

async def fetch_with_retry(page, url, max_retries=5, delay_on_rate_limit=30):
    """
    Navigate to a URL with rate-limit protection (HTTP 429).
    Returns the response object.
    """
    retries = 0
    while retries < max_retries:
        response = await page.goto(url)
        await page.wait_for_load_state("networkidle")
        
        if response.status != 429:
            return response

        print(f"[WARNING] Rate limited at {url}! Sleeping {delay_on_rate_limit}s...")
        await asyncio.sleep(delay_on_rate_limit)
        retries += 1

    print(f"[ERROR] Max retries reached for {url}.")
    return None


# --- CONFIG FLAG ---
TEST_FIRST_TOP_CATEGORY_ONLY = False  # Set False to explore all top-level categories

import csv
import re
import random

MAX_CATEGORY_DEPTH = 0  # will track maximum category depth dynamically

async def explore_category(page, url, path=None, is_top_level=False, top_category_name=None):
    global MAX_CATEGORY_DEPTH

    if path is None:
        path = []

    await asyncio.sleep(random.uniform(1.5, 3.0))  # random delay

    response = await fetch_with_retry(page, url)
    if response is None:
        print("[ERROR] Could not reach the page due to rate limiting.")
        return []

    if page.is_closed():
        print("[ERROR] Page was closed unexpectedly.")
        return []

    table_type = await page.evaluate("""
        () => {
            const th = document.querySelector('#stock-valuation-table > table > thead > tr > th');
            return th ? th.textContent.trim() : null;
        }
    """)

    rows_for_this_category = []

    if table_type is None:
        empty_table = await page.evaluate("""
            () => {
                const td = document.querySelector('#stock-valuation-table > table > tbody > tr > td');
                if (!td) return false;
                return /no/i.test(td.textContent.trim());
            }
        """)
        if empty_table:
            leaf_headers = ["Barserial", "Name", "Quantity", "Retail", "Cost", "VAT", "Net", "Total Margin", "Margin %"]
            rows_for_this_category.append((path.copy(), [""] * len(leaf_headers)))
        return rows_for_this_category

    if table_type.lower() == "barserial":
        # scrape leaf table
        await scrape_leaf_table(page, path, url)
        # scrape_leaf_table already appends to global all_rows; we'll collect local rows here too
        local_rows = []
        table_rows = await page.evaluate("""
            () => Array.from(document.querySelectorAll('#stock-valuation-table > table > tbody > tr')).map(tr => {
                return Array.from(tr.querySelectorAll('td')).map(td => td.textContent.trim());
            })
        """)
        for r in table_rows:
            local_rows.append((path.copy(), r))
        rows_for_this_category.extend(local_rows)
        return rows_for_this_category

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
        return rows_for_this_category

    for i, subcat in enumerate(subcategories):
        # Only restrict at top-level for testing
        if is_top_level and TEST_FIRST_TOP_CATEGORY_ONLY and i > 0:
            break
        # For top-level, remember the category name
        current_top = subcat["name"] if is_top_level else top_category_name
        sub_rows = await explore_category(page, subcat["url"], path + [subcat["name"]],
                                          is_top_level=False, top_category_name=current_top)
        rows_for_this_category.extend(sub_rows)

    return rows_for_this_category

async def stock_process(page):
    top_url = "https://nospos.com/reports/stock/category-valuation"

    # Load root page
    await fetch_with_retry(page, top_url)
    
    # Extract shop name
    shop_name = await page.evaluate("""
        () => {
            const el = document.querySelector('a[href="#select-branch-modal"] span');
            return el ? el.textContent.trim() : "UnknownShop";
        }
    """)
    # Sanitize folder name
    shop_folder = re.sub(r'[^A-Za-z0-9_-]+', '_', shop_name)
    os.makedirs(shop_folder, exist_ok=True)
    print(f"[INFO] Saving CSVs under folder: {shop_folder}")


    # Extract top-level categories
    top_categories = await page.evaluate("""
        () => {
            const rows = document.querySelectorAll(
                '#stock-valuation-table > table > tbody > tr'
            );
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

    print(f"[INFO] Found {len(top_categories)} top-level categories")

    for i, cat in enumerate(top_categories):
        if TEST_FIRST_TOP_CATEGORY_ONLY and i > 0:
            print("[INFO] TEST MODE: only processing first top-level category")
            break

        print(f"[TOP] Processing category: {cat['name']}")

        rows = await explore_category(
            page,
            cat["url"],
            path=[cat["name"]],
            is_top_level=False
        )

        if not rows:
            print(f"[WARNING] No data for category {cat['name']}")
            continue

        # Compute max depth for this category
        max_depth = max(len(path) for path, _ in rows)

        category_headers = [f"Category Level {i+1}" for i in range(max_depth)]
        leaf_headers = [
            "Barserial", "Name", "Quantity", "Retail",
            "Cost", "VAT", "Net", "Total Margin", "Margin %"
        ]

        # Create CSV file path under shop folder
        filename = os.path.join(
            shop_folder,
            re.sub(r'[^A-Za-z0-9_-]+', '_', cat["name"]) + ".csv"
        )

        tmp_filename = filename + ".tmp"

        with open(tmp_filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(category_headers + leaf_headers)

            for path, row in rows:
                padded_path = path + [""] * (max_depth - len(path))
                writer.writerow(padded_path + row)

        # Atomic replace — Excel-safe
        os.replace(tmp_filename, filename)

        print(f"[INFO] Saved CSV: {filename}")

    print("[INFO] All top-level categories processed.")



async def save_receipt_pdf_in_context(context, receipt_id, branch_name):
    receipt_url = f"https://nospos.com/print/sale-receipt?id={receipt_id}"

    safe_branch = re.sub(r'[^A-Za-z0-9_-]+', '_', branch_name)
    os.makedirs(safe_branch, exist_ok=True)

    pdf_path = os.path.join(safe_branch, f"{receipt_id}.pdf")

    page = await context.new_page()
    response = await fetch_with_retry(page, receipt_url)
    if response is None:
        print(f"[ERROR] Could not navigate to {receipt_url}")
        await page.close()
        return

    print(f"[INFO] Saving receipt PDF to {pdf_path}")

    await page.pdf(
        path=pdf_path,
        format="A4",
        print_background=True,
        margin={"top": "10mm", "bottom": "10mm"}
    )

    await page.close()
    print("[INFO] PDF saved successfully.")



    
PAYMENT_METHOD = "Bank Transfer"
# examples:
# "Cash"
# "Card"
# "Store Credit"
# "Paypal"
# "Amazon"
# "Website"
# "Ebay Direct"

async def open_cart_items_per_unit(page, units, batch_size=20, finish_transaction=False):
    import re
    from collections import defaultdict

    i = 0
    while i < len(units):
        batch_end = min(i + batch_size, len(units))
        batch = units[i:batch_end]
        batch_num = (i // batch_size) + 1

        print(f"\n[INFO] Processing batch {batch_num}: items {i+1} to {batch_end} of {len(units)}")

        # ---- GO TO HOMEPAGE ----
        await fetch_with_retry(page, HOME_URL)
        await page.wait_for_load_state("networkidle")

        # ---- CLICK SALE ----
        sale_button = page.locator(SALE_BUTTON_SELECTOR)
        await sale_button.wait_for(state="visible", timeout=5000)

        async with page.expect_navigation(wait_until="networkidle"):
            await sale_button.click()

        print("[INFO] Entered Sales cart via Sale button.")

        # ---- EXTRACT CART ID (PER BATCH) ----
        current_url = page.url
        match = re.search(r"/cart/(\d+)/items", current_url)

        if not match:
            print(f"[ERROR] Could not extract cart ID from URL: {current_url}")
            i = batch_end
            continue

        cart_id = int(match.group(1))
        print(f"[INFO] Batch {batch_num} using cart ID: {cart_id}")

        base_url = f"https://nospos.com/newsales/cart/{cart_id}/items"
        update_url = f"https://nospos.com/newsales/cart/{cart_id}/items/update"

        # ---- CLEAR CART ----
        clear_button = page.locator(
            f'a[href="/newsales/cart/{cart_id}/items/delete"]:has-text("Clear")'
        )

        if await clear_button.count() > 0 and await clear_button.first.is_visible():
            await clear_button.click()
            await page.wait_for_selector("button.swal2-confirm", timeout=5000)
            await page.click("button.swal2-confirm")
            await page.wait_for_load_state("networkidle")
            print("[INFO] Cart cleared.")

        # ---- GROUP ITEMS ----
        grouped_items = defaultdict(list)
        for barserial, cost_per_unit in batch:
            grouped_items[barserial].append(cost_per_unit)

        print(f"[INFO] Batch has {len(grouped_items)} unique barcodes")

        # ---- ADD ITEMS ----
        barcode_input = page.locator("#stocksearch-search_barserial")

        for barserial in grouped_items:
            await barcode_input.fill(barserial)
            await barcode_input.press("Enter")
            await page.wait_for_load_state("networkidle")


        # ---- GO TO UPDATE/DISCOUNT PAGE ----
        await page.goto(update_url)
        await page.wait_for_load_state("networkidle")
        print(f"[INFO] On update page for batch.")

        # ---- ENTER PRICE, QUANTITY, AND DISCOUNT REASON FOR EACH UNIQUE BARCODE ----
        for idx, barserial in enumerate(grouped_items.keys()):
            costs = grouped_items[barserial]
            quantity = len(costs)
            # All units of the same barcode should have the same cost_per_unit
            cost_per_unit = costs[0]
            
            print(f"[INFO] Item {idx}: {barserial} - Qty: {quantity}, Cost/Unit: {cost_per_unit:.2f}")
            
            # Update quantity for this cart item
            quantity_input = page.locator(f"#cartitems-{idx}-quantity")
            await quantity_input.wait_for(state="visible", timeout=5000)
            await quantity_input.fill(str(quantity))
            
            # Update price (cost per unit - website will calculate total automatically)
            price_input = page.locator(f"#cartitems-{idx}-price")
            await price_input.wait_for(state="visible", timeout=5000)
            await price_input.fill(f"{cost_per_unit:.2f}")
            
            # Update discount reason
            discount_input = page.locator(f"#cartitems-{idx}-discount_reason")
            await discount_input.wait_for(state="visible", timeout=5000)
            await discount_input.fill(".")
            
            print(f"[INFO] Set item {idx}: Qty={quantity}, Price/Unit={cost_per_unit:.2f}")

        # ---- CLICK SAVE ----
        save_button = page.locator("button.btn.btn-blue", has_text="Save")
        await save_button.wait_for(state="visible", timeout=5000)
        print(f"[INFO] Clicking Save button...")
        
        # Wait for navigation after click
        async with page.expect_navigation(wait_until="domcontentloaded"):
            await save_button.click()

        print(f"[INFO] Navigated back to cart page. Waiting 1 seconds...")
        await page.wait_for_timeout(4000)  # Wait 4 seconds
        
        # ---- SELECT STANDARD PAYMENT METHOD ----
        print(f"[INFO] Selecting Standard payment method...")
        standard_select_button = page.locator('a.btn.btn-blue[href*="/method/update?method=Standard"]')
        await standard_select_button.wait_for(state="visible", timeout=5000)
        await standard_select_button.click()
        await page.wait_for_load_state("networkidle")
        print(f"[INFO] Standard payment method selected.")
                # ---- CALCULATE TOTAL FOR THIS BATCH (FROM DATA, NOT PAGE) ----
        batch_total = 0.0
        for barserial, costs in grouped_items.items():
            quantity = len(costs)
            cost_per_unit = costs[0]  # same assumption you already make
            batch_total += quantity * cost_per_unit

        print(f"[INFO] Batch {batch_num} total to be paid: £{batch_total:.2f}")

        # ---- FILL PAYMENT METHOD AMOUNT ----
        amount_str = f"{batch_total:.2f}"

        print(f"[INFO] Paying £{amount_str} via {PAYMENT_METHOD}")

        payment_input = page.locator(
            f'div.form-group:has(label:has-text("{PAYMENT_METHOD}")) input'
        )

        await payment_input.wait_for(state="visible", timeout=5000)
        await payment_input.fill(amount_str)


        # ---- PRESS FINISH BUTTON (IF ENABLED) ----
        if finish_transaction:
            print(f"[INFO] Clicking Finish button...")
            finish_button = page.locator('button.btn.btn-blue:has-text("Finish")')
            await finish_button.wait_for(state="visible", timeout=5000)
            await finish_button.click()
            await page.wait_for_load_state("networkidle")
            print(f"[INFO] Finish button clicked, transaction complete.")
        else:
            print(f"[INFO] Skipping Finish button (finish_transaction=False)")
        # ---------------------
        branch_name = await page.evaluate("""
                () => {
                    const el = document.querySelector(
                        '#navbar-mobile-collapse > ul.nav.navbar-nav.action-links > li:nth-child(1) > a span'
                    );
                    return el ? el.textContent.trim() : 'Unknown Branch';
                }
            """)
            
        # ---- SAVE RECEIPT PDF ----
        context = page.context
        await save_receipt_pdf_in_context(context, cart_id, branch_name)
        
        print(f"[INFO] Batch complete!\n")

        # ---- WAIT 5 SECONDS BEFORE NEXT BATCH ----
        print("[INFO] Waiting 5 seconds before next batch...")
        await page.wait_for_timeout(4000)  # 5000 ms = 5 seconds

        
        # Move to next batch
        i = batch_end


MAX_CART_ITEM_OPENS = None  # set to None to open ALL units

from collections import Counter, defaultdict

async def stock_process_sales(page, csv_file, finish_transaction=False):
    """Read CSV, log barcodes grouped, and process units individually with cost per unit."""
    
    print(f"[INFO] Reading sales CSV: {csv_file}")
    try:
        with open(csv_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            required_columns = ["Barserial", "Quantity", "Cost"]
            for col in required_columns:
                if col not in reader.fieldnames:
                    print(f"[WARNING] CSV does not contain a '{col}' column.")
                    return

            units = []  # list of tuples (barcode, cost_per_unit)
            unique_barcodes_processed = set()

            # Helper to parse numbers as floats
            def parse_number(s, row_num):
                s_clean = s.replace("£", "").replace(",", "").strip()
                try:
                    return float(s_clean)
                except ValueError:
                    print(f"[WARNING] Invalid number '{s}' at row {row_num}, defaulting to 0.")
                    return 0.0

            # Process CSV and build units
            for i, row in enumerate(reader, start=1):
                barserial = row.get("Barserial", "").strip()
                if not barserial:
                    continue

                # Check if we've hit the barcode limit
                if MAX_CART_ITEM_OPENS is not None and barserial not in unique_barcodes_processed:
                    if len(unique_barcodes_processed) >= MAX_CART_ITEM_OPENS:
                        break  # stop processing new barcodes

                quantity = parse_number(row.get("Quantity", "0"), i)
                cost = parse_number(row.get("Cost", "0"), i)

                if quantity <= 0:
                    continue

                cost_per_unit = cost / quantity if quantity else 0.0

                # Add this barcode to our set
                unique_barcodes_processed.add(barserial)

                # Subdivide quantity into 1-unit barcodes (all units of this barcode)
                for _ in range(int(quantity)):
                    units.append((barserial, cost_per_unit))

            # Summarize for logging
            barcode_counts = Counter([b for b, _ in units])
            barcode_totals = defaultdict(float)
            for b, c in units:
                barcode_totals[b] += c

            print(f"{'Barcode':<15} | {'Qty':>5} | {'Total Cost':>10} | {'Cost/Unit':>10}")
            print("-"*60)
            for barserial in barcode_counts:
                qty = barcode_counts[barserial]
                total_cost = barcode_totals[barserial]
                cost_per_unit = total_cost / qty if qty else 0.0
                print(f"{barserial:<15} | {qty:5} | {total_cost:10.2f} | {cost_per_unit:10.2f}")

    except FileNotFoundError:
        print(f"[ERROR] CSV file not found: {csv_file}")
        return
    except Exception as e:
        print(f"[ERROR] Failed to read CSV: {e}")
        return

    # Process units in batches of 20, passing the finish_transaction flag
    await open_cart_items_per_unit(page, units, batch_size=20, finish_transaction=finish_transaction)


async def process_refunds(page, receipt_ids):
    """Process refunds for a list of receipt IDs.
    For each receipt, navigates to the refund page and fills out refund forms for all items.
    """
    for receipt_id in receipt_ids:
        url = f"https://nospos.com/newsales/cart/{receipt_id}/add-refund"
        print(f"\n[INFO] Processing refunds for receipt ID: {receipt_id}")
        print(f"[INFO] Navigating to: {url}")
        
        try:
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(1)  # Brief pause for page to fully render
            
            # Find all refund cards on the page - only within the form
            cards = await page.query_selector_all('form#w3 .card')
            print(f"[INFO] Found {len(cards)} card(s) on the page")
            
            bank_transfer_unavailable = False
            
            for card_index, card in enumerate(cards, start=1):
                print(f"\n[INFO] Processing card {card_index}/{len(cards)}")
                
                try:
                    # Extract and set refund amount
                    refund_amount_input = await card.query_selector('input[name*="refund_amount"]')
                    if refund_amount_input:
                        # Get the hint text to extract the total refundable amount
                        hint = await card.query_selector('.help-block-hint')
                        if hint:
                            hint_text = await hint.inner_text()
                            # Parse "£0 / £17.50 Refunded" to get 17.50
                            import re
                            match = re.search(r'£[\d,]+\.?\d*\s*/\s*£([\d,]+\.?\d*)', hint_text)
                            if match:
                                refund_amount = match.group(1).replace(',', '')
                                await refund_amount_input.fill(refund_amount)
                                print(f"  [✓] Set refund amount to: £{refund_amount}")
                    
                    # Set refund method to "Bank Transfer"
                    refund_method_select = await card.query_selector('select[name*="refund_method"]')
                    if refund_method_select:
                        # Try to select "Bank Transfer"
                        try:
                            await refund_method_select.select_option(value="bank-transfer")
                            print(f"  [✓] Set refund method to: Bank Transfer")
                        except Exception as e:
                            print(f"  [WARNING] Could not select 'Bank Transfer': {e}")
                            print(f"  [INFO] Skipping receipt {receipt_id} - Bank Transfer not available")
                            bank_transfer_unavailable = True
                            break  # Exit the card loop
                    
                    # Set return to free quantity
                    freestock_input = await card.query_selector('input[name*="freestock_quantity"]')
                    if freestock_input:
                        # Get the hint text to extract the returnable quantity
                        freestock_hint = await card.query_selector('label[for*="freestock_quantity"] ~ .help-block-hint')
                        if not freestock_hint:
                            freestock_hint = await freestock_input.evaluate('el => el.parentElement.querySelector(".help-block-hint")')
                        
                        if freestock_hint:
                            hint_text = await freestock_hint.inner_text() if hasattr(freestock_hint, 'inner_text') else await page.evaluate('el => el.textContent', freestock_hint)
                            # Parse "0 / 1 Returned" to get 1
                            match = re.search(r'(\d+)\s*/\s*(\d+)\s*Returned', hint_text)
                            if match:
                                return_qty = match.group(2)
                                await freestock_input.fill(return_qty)
                                print(f"  [✓] Set return to free qty to: {return_qty}")
                    
                    # Set return to faulty quantity to 0
                    faulty_input = await card.query_selector('input[name*="faulty_quantity"]')
                    if faulty_input:
                        await faulty_input.fill('0')
                        print(f"  [✓] Set return to faulty qty to: 0")
                    
                    # Set reason to "."
                    reason_input = await card.query_selector('input[name*="reason"]')
                    if reason_input:
                        await reason_input.fill('...')
                        print(f"  [✓] Set reason to: .")
                    
                    print(f"[INFO] Successfully processed card {card_index}")
                    
                except Exception as card_error:
                    print(f"  [ERROR] Failed to process card {card_index}: {card_error}")
                    continue
            
            # If bank transfer was unavailable, skip to next receipt
            if bank_transfer_unavailable:
                print(f"[INFO] Skipping to next receipt due to Bank Transfer unavailability")
                continue
            
            print(f"\n[INFO] Completed processing all cards for receipt ID: {receipt_id}")
            
            # Wait 4 seconds then click the Process button
            await asyncio.sleep(4)
            print(f"\n[INFO] Clicking Process button...")
            try:
                # Find button that contains "Process" text
                process_button = await page.query_selector('button.btn.btn-blue:has-text("Process")')
                if process_button:
                    await process_button.click()
                    print(f"  [✓] Process button clicked")
                    await asyncio.sleep(2)  # Wait for submission to complete
                else:
                    print(f"  [WARNING] Process button not found")
            except Exception as button_error:
                print(f"  [ERROR] Failed to click Process button: {button_error}")
            
        except Exception as e:
            print(f"[ERROR] Failed to process receipt ID {receipt_id}: {e}")
            continue
    
    print(f"\n[INFO] Finished processing all {len(receipt_ids)} receipt(s)")


async def process_refunds_from_file(page, file_path):
    """Read receipt IDs from a file and process refunds for each.
    
    Args:
        page: Playwright page object
        file_path: Path to text file containing receipt IDs (one per line)
    """
    
    print(f"[INFO] Reading receipt IDs from: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # Parse receipt IDs from file
        receipt_ids = []
        for line_num, line in enumerate(lines, start=1):
            line = line.strip()
            
            # Skip empty lines
            if not line:
                continue
            
            # Try to parse as integer
            try:
                receipt_id = int(line)
                receipt_ids.append(receipt_id)
            except ValueError:
                print(f"[WARNING] Line {line_num}: '{line}' is not a valid number, skipping")
                continue
        
        print(f"[INFO] Found {len(receipt_ids)} valid receipt ID(s)")
        
        if not receipt_ids:
            print("[ERROR] No valid receipt IDs found in file")
            return
        
        # Display the receipt IDs that will be processed
        print(f"[INFO] Receipt IDs to process: {receipt_ids}")
        
        # Process refunds for all receipt IDs
        await process_refunds(page, receipt_ids)
        
        # Wait at the end so user can verify
        print("\n" + "="*60)
        print("[INFO] Refund processing complete!")
        print("[INFO] Please review the page to verify everything is correct.")
        print("[INFO] Press Enter to continue...")
        print("="*60)
        input()
        
    except FileNotFoundError:
        print(f"[ERROR] File not found: {file_path}")
        return
    except Exception as e:
        print(f"[ERROR] Failed to read file: {e}")
        return
    

async def main():
    if len(sys.argv) < 2:
        print("[ERROR] Missing mode.")
        print("Usage:")
        print("  run.bat take <TAKE_ID>")
        print("  run.bat stock_process")
        print("  run.bat stock_process_sales <CSV_FILE> --save to save transactions.")
        print("  run.bat stock_process_sales <CSV_FILE> to put it through without saving. This will still print a receipt so you can view if the transaction was set up right.")
        print("  run.bat process_refunds <RECEIPT_IDS_FILE>")
        return

    mode = sys.argv[1].lower()

    take_id = None
    csv_file = None
    refunds_file = None
    finish_transaction = False  # Default to False
    
    # Check for --save flag
    if "--save" in sys.argv:
        finish_transaction = True
        print("[INFO] --save flag detected: transactions will be finished and saved.")
    
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
    elif mode == "process_refunds":
        if len(sys.argv) < 3:
            print("[ERROR] process_refunds mode requires a receipt IDs file path.")
            return
        refunds_file = sys.argv[2]
    else:
        print(f"[ERROR] Unknown mode: {mode}")
        return

    async with async_playwright() as pw:
        print("[INFO] Launching browser...")
        browser = await pw.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        
        # Create context with saved state if it exists
        if SESSION_FILE.exists():
            context = await browser.new_context(storage_state=str(SESSION_FILE))
        else:
            context = await browser.new_context()
        
        page = await context.new_page()

        # Wait for login first
        logged_in = await wait_for_login(page)
        if not logged_in:
            return

        # After login
        if csv_file:
            await stock_process_sales(page, csv_file, finish_transaction)
        elif refunds_file:
            await process_refunds_from_file(page, refunds_file)
        elif mode == "take":
            await navigate_to_take(page, take_id)
        elif mode == "stock_process":
            await stock_process(page)

        print("[INFO] Done.")


if __name__ == "__main__":
    asyncio.run(main())