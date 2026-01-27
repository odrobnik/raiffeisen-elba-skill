#!/usr/bin/env python3
"""
Simplified collection script - focus on capturing everything
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
    """Collect IDs while scrolling - simple approach"""
    print("[collect] Starting collection...", flush=True)
    
    scroller = page.locator('virtual-scroller.vertical.selfScroll')
    scrollable_content = page.locator('virtual-scroller.vertical.selfScroll div.scrollable-content').first
    
    all_docs = []
    seen_count = 0
    no_new_count = 0
    max_no_new = 30  # Increased from 20
    scroll_count = 0
    
    # Get row height
    first_row = page.locator('rds-list-item-row').first
    first_row.wait_for(timeout=10000, state="visible")
    row_height = first_row.bounding_box()['height']
    scroll_amount = int(row_height * 1.5)
    
    print(f"[collect] Row height: {row_height}px, scrolling {scroll_amount}px per step", flush=True)
    print(f"[collect] Will stop after {max_no_new} scrolls with no new documents", flush=True)
    
    while no_new_count < max_no_new:
        scroll_count += 1
        rows = page.locator('rds-list-item-row').all()
        new_this_scroll = 0
        
        for idx, row in enumerate(rows):
            try:
                btn = row.locator('button[icon="download"]').first
                if btn.count() == 0:
                    continue
                
                # Get all possible identifiers
                doc = {
                    'index': len(all_docs),
                    'aria_label': '',
                    'name': '',
                    'date': '',
                    'account': '',
                    'row_index': idx
                }
                
                try:
                    doc['aria_label'] = btn.get_attribute('aria-label') or ''
                except:
                    pass
                
                try:
                    doc['name'] = row.locator('p.rds-body-strong').inner_text().strip()
                except:
                    pass
                
                try:
                    body_texts = row.locator('p.rds-body-normal').all()
                    if len(body_texts) > 0:
                        doc['date'] = body_texts[0].inner_text().strip()
                    if len(body_texts) > 1:
                        doc['account'] = body_texts[1].inner_text().strip()
                except:
                    pass
                
                # Create a unique signature - use multiple fields
                # Include index in current scroll to handle true duplicates
                signature = f"{doc['date']}|{doc['name']}|{doc['account']}|{doc['aria_label']}"
                
                # Check if we've seen this exact document before
                is_duplicate = False
                for existing in all_docs:
                    existing_sig = f"{existing['date']}|{existing['name']}|{existing['account']}|{existing['aria_label']}"
                    if signature == existing_sig:
                        is_duplicate = True
                        break
                
                if not is_duplicate:
                    all_docs.append(doc)
                    new_this_scroll += 1
                    
            except Exception as e:
                continue
        
        # Get scroll position
        try:
            style = scrollable_content.get_attribute('style')
            import re
            match = re.search(r'translateY\((\d+)px\)', style)
            current_pos = int(match.group(1)) if match else 0
        except:
            current_pos = 0
        
        # Log progress
        delta = len(all_docs) - seen_count
        print(f"[collect] Scroll #{scroll_count}, pos: {current_pos}px, total: {len(all_docs)} (+{new_this_scroll} new)", flush=True)
        
        # Check stopping condition
        if new_this_scroll == 0:
            no_new_count += 1
            if no_new_count >= max_no_new:
                print(f"[collect] Stopping: no new documents for {max_no_new} consecutive scrolls", flush=True)
                break
        else:
            no_new_count = 0
        
        seen_count = len(all_docs)
        
        # Scroll and wait
        scroller.evaluate(f"el => el.scrollBy(0, {scroll_amount})")
        time.sleep(2)  # Simple fixed wait
    
    print(f"\n[collect] Collection complete! Found {len(all_docs)} documents after {scroll_count} scrolls", flush=True)
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
            print("[test] Applying date filters...")
            from_input = page.locator('input[formcontrolname="fromDate"]')
            from_input.wait_for(timeout=15000, state="visible")
            
            from_input.fill("01.01.2025")
            page.keyboard.press("Tab")
            time.sleep(4)
            
            to_input = page.locator('input[formcontrolname="toDate"]')
            to_input.fill("31.12.2025")
            page.keyboard.press("Tab")
            time.sleep(5)
            
            # Collect documents
            all_docs = collect_all_ids(page)
            
            print(f"\n{'='*60}")
            print(f"COLLECTION COMPLETE: {len(all_docs)} documents found")
            print(f"{'='*60}")
            
            # Save detailed JSON
            output_file = Path("elba_documents_detailed.json")
            with open(output_file, 'w') as f:
                json.dump(all_docs, f, indent=2, ensure_ascii=False)
            print(f"\nDetailed log saved to: {output_file}")
            
            # Save simple text list
            text_file = Path("elba_documents_list.txt")
            with open(text_file, 'w') as f:
                for i, doc in enumerate(all_docs, 1):
                    f.write(f"{i}. {doc['date']} | {doc['name']} | {doc['account']}\n")
            print(f"Simple list saved to: {text_file}")
            
            # Show first 30
            print("\nFirst 30 documents:")
            for i, doc in enumerate(all_docs[:30], 1):
                print(f"  {i}. {doc['date']} | {doc['name']}")
            
            if len(all_docs) >= 30:
                print(f"\n  ... and {len(all_docs) - 30} more")
            
        finally:
            context.close()

if __name__ == "__main__":
    main()
