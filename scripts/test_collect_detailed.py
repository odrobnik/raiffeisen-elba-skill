#!/usr/bin/env python3
"""
Test script to collect all document IDs with detailed logging
"""
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from elba import load_credentials, login, URL_DOCUMENTS, PROFILE_DIR

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed")
    sys.exit(1)

def collect_all_ids(page):
    """Collect IDs while scrolling - capture ALL attributes for uniqueness"""
    print("[collect] Collecting IDs while scrolling...", flush=True)
    
    scroller = page.locator('virtual-scroller.vertical.selfScroll')
    scrollable_content = page.locator('virtual-scroller.vertical.selfScroll div.scrollable-content').first
    
    all_docs = []  # List to preserve all documents
    seen_keys = set()  # Track what we've seen
    prev_translateY = 0
    no_new_items_count = 0
    max_no_new = 20
    
    # Get row height for scrolling
    first_row = page.locator('rds-list-item-row').first
    first_row.wait_for(timeout=10000, state="visible")
    row_height = first_row.bounding_box()['height']
    scroll_amount = int(row_height * 1.5)
    
    print(f"[collect] Row height: {row_height}px, scrolling {scroll_amount}px per step", flush=True)
    
    while no_new_items_count < max_no_new:
        rows = page.locator('rds-list-item-row').all()
        new_this_scroll = 0
        
        for row in rows:
            try:
                btn = row.locator('button[icon="download"]').first
                if btn.count() == 0:
                    continue
                
                # Capture ALL available attributes
                doc_info = {}
                
                # Aria label
                doc_info['aria_label'] = btn.get_attribute('aria-label') or ""
                
                # Document name
                try:
                    doc_info['name'] = row.locator('p.rds-body-strong.dok-truncate-2-lines').inner_text().strip()
                except:
                    doc_info['name'] = ""
                
                # Date (if visible)
                try:
                    doc_info['date'] = row.locator('p.rds-body-normal').first.inner_text().strip()
                except:
                    doc_info['date'] = ""
                
                # Account info (second p.rds-body-normal)
                try:
                    account_parts = row.locator('p.rds-body-normal').all()
                    if len(account_parts) > 1:
                        doc_info['account'] = account_parts[1].inner_text().strip()
                    else:
                        doc_info['account'] = ""
                except:
                    doc_info['account'] = ""
                
                # Try to get any data attributes or IDs from the button
                try:
                    all_attrs = btn.evaluate("el => Array.from(el.attributes).map(a => [a.name, a.value])")
                    doc_info['button_attrs'] = dict(all_attrs)
                except:
                    doc_info['button_attrs'] = {}
                
                # Try to get the row's attributes
                try:
                    row_attrs = row.evaluate("el => Array.from(el.attributes).map(a => [a.name, a.value])")
                    doc_info['row_attrs'] = dict(row_attrs)
                except:
                    doc_info['row_attrs'] = {}
                
                # Create a composite unique key from multiple fields
                # Use account + date + name as the key since aria_label might not be unique
                unique_key = f"{doc_info['account']}|{doc_info['date']}|{doc_info['name']}|{doc_info['aria_label']}"
                
                if unique_key in seen_keys:
                    continue
                
                seen_keys.add(unique_key)
                doc_info['unique_key'] = unique_key
                all_docs.append(doc_info)
                new_this_scroll += 1
                
            except Exception as e:
                continue
        
        # Get current translateY position
        try:
            style = scrollable_content.get_attribute('style')
            import re
            match = re.search(r'translateY\((\d+)px\)', style)
            current_translateY = int(match.group(1)) if match else 0
        except:
            current_translateY = prev_translateY
        
        translateY_delta = current_translateY - prev_translateY
        print(f"[collect] Pos: {current_translateY}px (+{translateY_delta}), total: {len(all_docs)} (+{new_this_scroll} new)", flush=True)
        
        # Check if we should stop
        if new_this_scroll == 0:
            no_new_items_count += 1
            if no_new_items_count >= max_no_new:
                print(f"[collect] Stopping: no new items for {max_no_new} consecutive scrolls", flush=True)
                break
        else:
            no_new_items_count = 0
        
        prev_translateY = current_translateY
        
        # Scroll
        scroller.evaluate(f"el => el.scrollBy(0, {scroll_amount})")
        
        # Wait for placeholder to disappear (indicates new content loaded)
        time.sleep(0.5)
        try:
            # Wait for any loading placeholders to be gone
            page.wait_for_function(
                """() => {
                    const placeholders = document.querySelectorAll('.placeholder, [class*="placeholder"], [class*="loading"], [class*="skeleton"]');
                    return placeholders.length === 0 || Array.from(placeholders).every(el => el.offsetParent === null);
                }""",
                timeout=10000
            )
        except:
            # If no placeholder detected or timeout, just wait a bit
            time.sleep(1.5)
    
    print(f"\n[collect] Complete! Found {len(all_docs)} unique documents", flush=True)
    return all_docs

def main():
    elba_id, pin = load_credentials()
    if not elba_id or not pin:
        print("Credentials not found")
        sys.exit(1)
    
    if not PROFILE_DIR.exists():
        PROFILE_DIR.mkdir(parents=True)
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={"width": 1280, "height": 800}
        )
        
        page = context.new_page()
        
        try:
            # Login
            print("[test] Attempting to access documents page...")
            page.goto(URL_DOCUMENTS, wait_until="networkidle")
            time.sleep(3)
            
            if "sso.raiffeisen.at" in page.url or "mein-login" in page.url:
                print("[test] Not logged in, performing login...")
                if not login(page, elba_id, pin):
                    print("[test] Login failed")
                    sys.exit(1)
                print("[test] Login successful, navigating to documents...")
                page.goto(URL_DOCUMENTS, wait_until="networkidle")
                time.sleep(3)
            else:
                print("[test] Already logged in!")
            
            # Apply date filter
            print("[test] Waiting for date filter inputs...")
            from_input = page.locator('input[formcontrolname="fromDate"]')
            from_input.wait_for(timeout=15000, state="visible")
            
            print("[test] Filling 'from' date...")
            from_input.fill("01.01.2025")
            page.keyboard.press("Tab")
            print("[test] Waiting for page reload after 'from' date...")
            time.sleep(4)
            
            print("[test] Filling 'to' date...")
            to_input = page.locator('input[formcontrolname="toDate"]')
            to_input.fill("31.12.2025")
            page.keyboard.press("Tab")
            print("[test] Waiting for filtered results to load...")
            time.sleep(5)
            
            # Collect all documents
            all_docs = collect_all_ids(page)
            
            print(f"\n{'='*60}")
            print(f"COLLECTION COMPLETE: {len(all_docs)} documents found")
            print(f"{'='*60}")
            
            # Save detailed log
            output_file = Path("elba_documents_detailed.json")
            with open(output_file, 'w') as f:
                json.dump(all_docs, f, indent=2, ensure_ascii=False)
            print(f"\nDetailed log saved to: {output_file}")
            
            # Also save a simple text list
            text_file = Path("elba_documents_list.txt")
            with open(text_file, 'w') as f:
                for i, doc in enumerate(all_docs, 1):
                    f.write(f"{i}. {doc['date']} | {doc['name']} | {doc['account']}\n")
            print(f"Simple list saved to: {text_file}")
            
            # Show first 20
            print("\nFirst 20 documents:")
            for i, doc in enumerate(all_docs[:20], 1):
                print(f"  {i}. {doc['date']} | {doc['name']} | {doc['account']}")
            
        finally:
            context.close()

if __name__ == "__main__":
    main()
