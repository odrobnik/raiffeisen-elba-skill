#!/usr/bin/env python3
"""
Test script to collect all document IDs without downloading
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from elba import load_credentials, login, URL_DOCUMENTS, PROFILE_DIR

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed")
    sys.exit(1)

def collect_all_ids(page):
    """Collect IDs while scrolling (virtual scroller removes old rows)"""
    print("[collect] Collecting IDs while scrolling...", flush=True)
    
    scroller = page.locator('virtual-scroller.vertical.selfScroll')
    scrollable_content = page.locator('virtual-scroller.vertical.selfScroll div.scrollable-content').first
    
    all_ids = {}  # Use dict to dedupe by aria-label
    prev_translateY = 0
    prev_count = 0
    no_new_items_count = 0
    max_no_new = 20  # Stop after 20 scrolls with no new items
    
    # Get row height for scrolling
    first_row = page.locator('rds-list-item-row').first
    first_row.wait_for(timeout=10000, state="visible")
    row_height = first_row.bounding_box()['height']
    scroll_amount = int(row_height * 1.5)
    
    print(f"[collect] Row height: {row_height}px, scrolling {scroll_amount}px per step", flush=True)
    
    while no_new_items_count < max_no_new:
        # Capture IDs from currently visible rows
        rows = page.locator('rds-list-item-row').all()
        new_this_scroll = 0
        
        for row in rows:
            try:
                btn = row.locator('button[icon="download"]').first
                if btn.count() == 0:
                    continue
                
                aria = btn.get_attribute('aria-label', timeout=500)
                if not aria or aria in all_ids:
                    continue
                
                try:
                    name = row.locator('p.rds-body-strong.dok-truncate-2-lines').inner_text(timeout=500).strip()
                except:
                    name = "Unknown"
                
                all_ids[aria] = name
                new_this_scroll += 1
            except:
                continue
        
        # Get current translateY position
        try:
            style = scrollable_content.get_attribute('style', timeout=1000)
            import re
            match = re.search(r'translateY\((\d+)px\)', style)
            current_translateY = int(match.group(1)) if match else 0
        except:
            current_translateY = prev_translateY
        
        translateY_delta = current_translateY - prev_translateY
        
        # Log progress
        print(f"[collect] Pos: {current_translateY}px (+{translateY_delta}), total: {len(all_ids)} (+{new_this_scroll} new)", flush=True)
        
        # Check if we should stop
        if new_this_scroll == 0:
            no_new_items_count += 1
            if no_new_items_count >= max_no_new:
                print(f"[collect] Stopping: no new items for {max_no_new} consecutive scrolls", flush=True)
                break
        else:
            no_new_items_count = 0
        
        prev_translateY = current_translateY
        prev_count = len(all_ids)
        
        # Scroll by one row
        scroller.evaluate(f"el => el.scrollBy(0, {scroll_amount})")
        time.sleep(1)
    
    print(f"\n[collect] Complete! Found {len(all_ids)} unique documents", flush=True)
    return [(aria, name) for aria, name in all_ids.items()]

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
            # Login first
            print("[test] Attempting to access documents page...")
            page.goto(URL_DOCUMENTS, wait_until="networkidle")
            time.sleep(3)
            
            # Check if we need to login
            if "sso.raiffeisen.at" in page.url or "mein-login" in page.url:
                print("[test] Not logged in, performing login...")
                if not login(page, elba_id, pin):
                    print("[test] Login failed")
                    sys.exit(1)
                # After login, navigate to documents
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
            
            # Collect IDs
            all_ids = collect_all_ids(page)
            
            print(f"\n{'='*60}")
            print(f"COLLECTION COMPLETE: {len(all_ids)} documents found")
            print(f"{'='*60}")
            
            # Show first 10
            print("\nFirst 10 documents:")
            for i, (aria, name) in enumerate(all_ids[:10], 1):
                print(f"  {i}. {name}")
            
        finally:
            context.close()

if __name__ == "__main__":
    main()
