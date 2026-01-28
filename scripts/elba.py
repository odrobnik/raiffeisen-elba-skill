#!/usr/bin/env python3
"""
Raiffeisen ELBA Banking Automation

Automates login and basic data retrieval for Raiffeisen ELBA (Austria).
"""

import sys
import os
import time
import re
import argparse
import json
from pathlib import Path
import requests

# Try importing playwright
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
except ImportError:
    print("ERROR: playwright not installed. Run: pip3 install playwright && playwright install chromium")
    sys.exit(1)

# --- Configuration ---
BASE_DIR = Path(__file__).parent.parent
CREDENTIALS_DIR = Path.home() / "clawd" / "raiffeisen-elba"
CREDENTIALS_FILE = CREDENTIALS_DIR / ".env"
PROFILE_DIR = Path.home() / ".clawdbot" / "raiffeisen-elba" / ".pw-profile"
SESSION_URL_FILE = PROFILE_DIR / "last_url.txt"
TOKEN_CACHE_FILE = PROFILE_DIR / "token.json"
DEBUG_DIR = Path.home() / ".clawdbot" / "raiffeisen-elba" / "debug"

URL_LOGIN = "https://sso.raiffeisen.at/mein-login/identify"
URL_DASHBOARD = "https://mein.elba.raiffeisen.at/bankingws-widgetsystem/meine-produkte/dashboard"
URL_DOCUMENTS = "https://mein.elba.raiffeisen.at/bankingws-widgetsystem/mailbox/dokumente"

# Mapping from ID prefix to region name (for matching in dropdown)
REGION_MAPPING = {
    "ELVIE33V": "Burgenland",
    "ELOOE03V": "Carinthia",  # or "Kärnten"
    "ELVIE32V": "Lower Austria",  # "Lower Austria" or "Wien" 
    "ELOOE01V": "Upper Austria",  # could also be "Bank Direct" or "Privat Bank"
    "ELOOE05V": "Salzburg",
    "ELVIE38V": "Styria",  # or "Steiermark"
    "ELOOE11V": "Tyrol",   # could also be "Jungholz" or "Alpen Privatbank"
    "ELVIE37V": "Vorarlberg"
}

def load_credentials():
    """Load credentials from the specified .env file."""
    if not CREDENTIALS_FILE.exists():
        return None, None
    
    # Load explicitly
    config = {}
    with open(CREDENTIALS_FILE, 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                config[key] = value.strip().strip("'").strip('"')
    
    return config.get('ELBA_ID'), config.get('ELBA_PIN')



def _now_iso_local() -> str:
    from datetime import datetime
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _write_debug_json(prefix: str, payload) -> Path:
    _ensure_dir(DEBUG_DIR)
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
    out = DEBUG_DIR / f"{ts}-{prefix}.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return out


def _eu_amount(amount: float | None) -> str:
    if amount is None:
        return "N/A"
    s = f"{amount:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def _canonical_account_type_elba(raw_type: str | None) -> str:
    t = (raw_type or "").lower()
    # ELBA 'type' here is UI label (e.g. Giro, Sparkonto, Kredit, Depot)
    if 'depot' in t:
        return 'depot'
    if 'giro' in t or 'konto' in t:
        return 'checking'
    if 'spar' in t:
        return 'savings'
    if 'kredit' in t or 'loan' in t:
        return 'loan'
    return 'other'


def canonicalize_accounts_elba(accounts: list[dict], raw_path: Path | None = None) -> dict:
    out_accounts = []
    for a in accounts or []:
        if not isinstance(a, dict):
            continue
        name = a.get('name') or 'N/A'
        iban = a.get('iban')
        typ = _canonical_account_type_elba(a.get('type'))

        currency = None
        # Determine currency from balance/value object
        for key in ('balance','available','value'):
            v = a.get(key)
            if isinstance(v, dict):
                currency = v.get('currencyCode') or v.get('currency')
                if currency:
                    break
        currency = (currency or 'EUR').strip()

        balances = None
        securities = None

        if a.get('type') == 'Depot' or typ == 'depot':
            v = a.get('value') if isinstance(a.get('value'), dict) else None
            pl = a.get('profit_loss') if isinstance(a.get('profit_loss'), dict) else None
            securities = {
                'value': {'amount': v.get('amount'), 'currency': currency} if v and v.get('amount') is not None else None,
                'profitLoss': {
                    'amount': pl.get('amount'),
                    'currency': (pl.get('currencyCode') or currency) if pl else currency,
                    'percent': pl.get('percent')
                } if pl else None
            }
        else:
            b = a.get('balance') if isinstance(a.get('balance'), dict) else None
            av = a.get('available') if isinstance(a.get('available'), dict) else None
            balances = {
                'booked': {'amount': b.get('amount'), 'currency': currency} if b and b.get('amount') is not None else None,
                'available': {'amount': av.get('amount'), 'currency': currency} if av and av.get('amount') is not None else None,
            }

        out_accounts.append({
            'id': iban or name,
            'type': typ,
            'name': name,
            'iban': iban,
            'currency': currency,
            'balances': balances,
            'securities': securities,
        })

    return {
        'institution': 'elba',
        'fetchedAt': _now_iso_local(),
        'rawPath': str(raw_path) if raw_path else None,
        'accounts': out_accounts,
    }


def get_region_name(elba_id):
    """Determine region name from ELBA_ID prefix."""
    if not elba_id:
        return None
    prefix = elba_id[:8].upper()
    
    # Check specific mapping
    if prefix in REGION_MAPPING:
        return REGION_MAPPING[prefix]
    
    return None

def login(page, elba_id, pin):
    """Perform the login flow."""
    print(f"[login] Navigating to {URL_LOGIN}...")
    page.goto(URL_LOGIN)
    
    # Check for service unavailable
    time.sleep(1)
    page_content = page.content()
    if "Service Unavailable" in page_content or "503" in page.title():
        print("[login] ERROR: Service Unavailable (503). ELBA may be temporarily down.")
        print("[login] Please try again later.")
        return False
    
    # Check for session expired page
    if page.locator('text="Session expired"').is_visible() or page.locator('text="Page Expired"').is_visible():
        print("[login] Session expired, restarting...")
        # Click Restart button if present
        if page.locator('button:has-text("Restart")').is_visible():
            page.locator('button:has-text("Restart")').click()
            time.sleep(2)
        # Don't return - continue with login flow
    else:
        # Check if we are already redirected to dashboard (session reuse)
        time.sleep(1)
        if "mein.elba.raiffeisen.at" in page.url:
            print("[login] Already logged in!")
            return True

    # 1. Select Region
    region_name = get_region_name(elba_id)
    if not region_name:
        print(f"[login] ERROR: Could not determine region for ID {elba_id}")
        return False
    
    print(f"[login] Selecting region for {elba_id[:8]} -> looking for '{region_name}'...")
    
    # Navigate dropdown option by option using arrow keys
    try:
        # Region dropdown: rds-select[formcontrolname="mandant"]
        dropdown = page.locator('rds-select[formcontrolname="mandant"]')
        dropdown.click()
        time.sleep(0.5)
        
        # Try to find the option by navigating with arrow keys
        # First, get the initial selected value
        max_attempts = 20  # Prevent infinite loop
        
        found = False
        for attempt in range(max_attempts):
            # Check the currently highlighted option
            try:
                # Get all options and find the active/highlighted one
                options = page.locator('rds-option')
                
                # Check each visible option for a match
                for i in range(options.count()):
                    option_text = options.nth(i).inner_text()
                    if region_name.lower() in option_text.lower():
                        print(f"[login] Found matching option: {option_text}")
                        options.nth(i).click()
                        time.sleep(0.5)
                        found = True
                        break
                        
            except Exception:
                pass
            
            if found:
                break
                
            # If not found yet, press down arrow to move to next option
            page.keyboard.press("ArrowDown")
            time.sleep(0.2)
        
        if not found:
            print(f"[login] ERROR: Could not find region '{region_name}' in dropdown")
            return False
        
    except Exception as e:
        print(f"[login] Error selecting region: {e}")
        return False

    # 2. Fill Form
    print("[login] Entering credentials...")
    try:
        # Signatory number: input[formcontrolname="verfuegerNr"]
        page.locator('input[formcontrolname="verfuegerNr"]').fill(elba_id)
        
        # PIN: input[formcontrolname="pin"]
        page.locator('input[formcontrolname="pin"]').fill(pin)
        
        # Wait for Continue button to become enabled
        print("[login] Waiting for Continue button to enable...")
        submit_button = page.locator('button[type="submit"]:not([disabled])')
        submit_button.wait_for(timeout=10000, state="visible")
        time.sleep(1)  # Extra safety delay for validation
        
        # Submit: button[type="submit"]
        submit_button.click()
    except Exception as e:
        print(f"[login] Error filling form: {e}")
        return False

    # 3. Handle 2FA (pushTAN)
    print("[login] Waiting for pushTAN screen...")
    
    try:
        # Wait for the code element: p.rds-display-1
        # Timeout 10s for the element to appear
        code_locator = page.locator('p.rds-display-1')
        code_locator.wait_for(timeout=10000)
        
        code = code_locator.inner_text().strip()
        print("\n" + "="*40)
        print(f"ELBA PUSHTAN CODE: {code}")
        print("="*40 + "\n")
        
        # Send to Telegram via stdout (Agent will see this)
        # Assuming the user is running this interactively or the agent is watching.
        
    except PlaywrightTimeout:
        # Maybe no 2FA needed or error?
        print("[login] Did not see pushTAN code. Checking for errors...")
    
    # 4. Wait for success or error
    print("[login] Waiting for navigation to dashboard...")
    start_time = time.time()
    while time.time() - start_time < 120: # 2 minute timeout for approval
        # Check for service unavailable (skip if page is still navigating)
        try:
            page_content = page.content()
            if "Service Unavailable" in page_content or "503" in page.title():
                print("[login] ERROR: Service Unavailable (503). ELBA may be temporarily down.")
                return False
        except Exception:
            # Page is still navigating, skip this check
            pass
        
        if "mein.elba.raiffeisen.at" in page.url:
            print("[login] Login successful!")
            
            # Navigate to the full dashboard to ensure all cookies are set
            print("[login] Loading products dashboard to establish session...")
            # networkidle is brittle for SPA apps; use domcontentloaded with a timeout.
            page.goto(URL_DASHBOARD, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            
            # Verify we didn't get redirected back to login
            if "sso.raiffeisen.at" in page.url or "mein-login" in page.url:
                print("[login] ERROR: Redirected back to login after initial success.")
                return False
            
            # Try to find at least one banking product card to confirm page loaded
            try:
                page.locator('banking-product-card').first.wait_for(timeout=5000, state="visible")
                print("[login] Dashboard loaded successfully!")
            except PlaywrightTimeout:
                print("[login] WARNING: Dashboard loaded but no product cards visible yet.")
            
            # Save the current URL for later use
            SESSION_URL_FILE.parent.mkdir(parents=True, exist_ok=True)
            SESSION_URL_FILE.write_text(page.url, encoding='utf-8')
            print(f"[login] Saved session URL: {page.url}")
            
            # Give browser extra time to persist everything
            time.sleep(2)
            
            return True
        
        # Check for session expired
        if page.locator('text="Session expired"').is_visible() or page.locator('text="Page Expired"').is_visible():
            print("[login] ERROR: Session expired during login.")
            return False
        
        # Check for invalid signature error
        if page.locator('text="Invalid signature data"').is_visible():
            print("[login] ERROR: Invalid signature data were entered. Please try again.")
            return False
        
        # Check errors
        if page.locator('div#error_message').is_visible():
            err = page.locator('div#error_message').inner_text()
            print(f"[login] ERROR: {err}")
            return False
            
        time.sleep(1)
        
    print("[login] Timeout waiting for approval.")
    return False


def fetch_accounts(page):
    """Fetch accounts from the dashboard carousel (assumes already on dashboard)."""
    # Ensure we're on the products dashboard
    if "meine-produkte/dashboard" not in page.url:
        print(f"[accounts] Navigating to products dashboard...")
        try:
            # networkidle is brittle for SPA apps; use domcontentloaded with a timeout.
            page.goto(URL_DASHBOARD, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
        except Exception as e:
            error_msg = str(e)
            if "ERR_CONNECTION_RESET" in error_msg or "connection was reset" in error_msg.lower():
                print("[accounts] ERROR: Connection reset. ELBA server connection failed.")
                print("[accounts] Please try again later.")
                return []
            else:
                print(f"[accounts] ERROR: Navigation failed: {e}")
                return []
    
    # Check for connection errors on the page
    page_content = page.content()
    if "ERR_CONNECTION_RESET" in page_content or "connection was reset" in page_content.lower():
        print("[accounts] ERROR: Connection reset. ELBA server connection failed.")
        print("[accounts] Please try again later.")
        return []
    
    # Check for session expired or login page
    if "sso.raiffeisen.at" in page.url or "mein-login" in page.url:
        print("[accounts] ERROR: Redirected to login page. Session expired.")
        return []
    
    print(f"[accounts] Current URL: {page.url}")
    
    # Wait for banking product cards to load
    try:
        print("[accounts] Waiting for banking-product-card elements...")
        page.locator('banking-product-card').first.wait_for(timeout=15000, state="visible")
        print("[accounts] Found banking product cards!")
    except PlaywrightTimeout:
        print(f"[accounts] ERROR: Could not find banking product cards after timeout.")
        print(f"[accounts] Page title: {page.title()}")
        # Try to find what IS on the page
        try:
            body_text = page.locator('body').inner_text()[:500]
            print(f"[accounts] Page content preview: {body_text}")
        except:
            pass
        return []
    
    accounts = []
    seen_ibans = set()  # Track IBANs to avoid duplicates
    
    # Carousel navigation: click right arrow until it disappears
    carousel_page = 1
    max_pages = 20  # Safety limit
    
    while carousel_page <= max_pages:
        print(f"[accounts] Processing carousel page {carousel_page}...")
        
        # Wait a moment for carousel to settle
        time.sleep(1)
        
        # Get ALL banking-product-card elements in the DOM
        all_cards = page.locator('banking-product-card').all()
        
        # Filter to only actually visible cards (in viewport)
        visible_cards = []
        for card in all_cards:
            try:
                # Check if card is visible AND in viewport
                if card.is_visible():
                    bbox = card.bounding_box()
                    if bbox and bbox['width'] > 0 and bbox['height'] > 0:
                        visible_cards.append(card)
            except:
                pass
        
        print(f"[accounts] Found {len(visible_cards)} visible card(s) (out of {len(all_cards)} total in DOM)")
        
        cards_processed_this_page = 0
        
        # Process all visible cards
        for i, card in enumerate(visible_cards):
            print(f"[accounts] Processing card {i}...")
            
            # Try quick IBAN extraction for duplicate check
            quick_iban = None
            try:
                footer = card.locator('rds-card-footer')
                # Get all text content
                footer_text = footer.text_content(timeout=2000)
                
                # Remove screen reader text and clean up
                footer_text = footer_text.replace("Produkt-Id:", "")
                footer_text = footer_text.replace("IBAN bzw. Produkt ID kopieren", "")
                
                # Clean and normalize - just take all remaining text
                quick_iban = ' '.join(footer_text.split()).strip()
                
                if not quick_iban:
                    print(f"[accounts] Card {i}: Empty IBAN after cleaning")
                else:
                    print(f"[accounts] Card {i}: Extracted IBAN: '{quick_iban}'")
                    
                    if quick_iban in seen_ibans:
                        print(f"[accounts] Card {i}: Already processed")
                        continue  # Skip - already processed
            except Exception as e:
                print(f"[accounts] Card {i}: Could not quick-extract IBAN: {e}")
                # Continue processing - we'll get IBAN in the full extraction below
            
            try:
                # Extract account type from rds-card-subtitle
                account_type = card.locator('rds-card-subtitle').inner_text(timeout=5000).strip()
            except Exception as e:
                print(f"[accounts] Card {i}: Could not extract type: {e}")
                account_type = "Unknown"
            
            try:
                # Extract account name from rds-card-title
                name = card.locator('rds-card-title').inner_text(timeout=5000).strip()
            except Exception as e:
                print(f"[accounts] Card {i}: Could not extract name: {e}")
                name = "Unknown"
            
            try:
                # Extract balance from strong (could be text-success, text-danger, or plain strong)
                # Try text-success first (positive balance)
                balance_elem = card.locator('strong.text-success').first
                if balance_elem.count() > 0:
                    balance_text = balance_elem.inner_text(timeout=2000).strip()
                else:
                    # Try text-danger (negative balance for loans/credits)
                    balance_elem = card.locator('strong.text-danger').first
                    if balance_elem.count() > 0:
                        balance_text = balance_elem.inner_text(timeout=2000).strip()
                    else:
                        # For depots with 0, try any strong tag (might be plain styling)
                        balance_elem = card.locator('rds-card-content strong').first
                        balance_text = balance_elem.inner_text(timeout=2000).strip()
            except Exception as e:
                print(f"[accounts] Card {i}: Could not extract balance: {e}")
                # For Depot with no balance, default to 0
                if account_type == "Depot":
                    balance_text = "0,00 EUR"
                else:
                    balance_text = ""
            
            available_text = ""
            entwicklung_text = ""
            try:
                # Try to extract available amount from "verfügbar" (bank accounts)
                available_elem = card.locator('small:has-text("verfügbar")')
                available_text = available_elem.inner_text(timeout=2000).strip()
                # Extract just the amount part after "verfügbar"
                if "verfügbar" in available_text:
                    available_text = available_text.split("verfügbar")[1].strip()
            except Exception:
                # For Depot accounts, try to extract "Entwicklung" (performance)
                try:
                    entwicklung_elem = card.locator('small:has-text("Entwicklung")')
                    entwicklung_text = entwicklung_elem.inner_text(timeout=2000).strip()
                except Exception:
                    available_text = ""
            
            # Extract IBAN if we didn't get it in the quick check
            if quick_iban:
                iban = quick_iban
            else:
                try:
                    footer = card.locator('rds-card-footer')
                    footer_text = footer.text_content(timeout=5000)
                    footer_text = footer_text.replace("Produkt-Id:", "").replace("IBAN bzw. Produkt ID kopieren", "")
                    iban = ' '.join(footer_text.split()).strip()
                    if not iban:
                        iban = "Unknown"
                except Exception as e:
                    print(f"[accounts] Card {i}: Could not extract IBAN: {e}")
                    iban = "Unknown"
            
            # Skip if we couldn't extract valid data
            if not iban or iban == "Unknown" or account_type == "Unknown":
                print(f"[accounts] Card {i}: Skipping - incomplete data (iban={iban}, type={account_type})")
                continue
            
            # Add to seen set and increment counter
            seen_ibans.add(iban)
            cards_processed_this_page += 1
            
            balance_primary, balance_eur = _parse_money_pair(balance_text)
            
            if account_type == "Depot":
                profit_loss_percent = _parse_percent_text(entwicklung_text)
                available_primary = None
                available_eur = None
                profit_loss = {
                    "amount": None,
                    "currencyCode": None,
                    "percent": profit_loss_percent
                }
            else:
                available_primary, available_eur = _parse_money_pair(available_text)
                if available_primary is None:
                    available_primary = balance_primary
                profit_loss = None
            
            if account_type == "Depot":
                accounts.append({
                    "type": account_type,
                    "name": name,
                    "iban": iban,
                    "value": balance_primary,
                    "value_eur": balance_eur,
                    "profit_loss": profit_loss
                })
            else:
                accounts.append({
                    "type": account_type,
                    "name": name,
                    "iban": iban,
                    "balance": balance_primary,
                    "balance_eur": balance_eur,
                    "available": available_primary,
                    "available_eur": available_eur,
                    "profit_loss": profit_loss
                })
            
            print(f"[accounts] Card {i}: {account_type} - {name}")
        
        print(f"[accounts] Processed {cards_processed_this_page} new account(s) on this page")
        
        # If we didn't process any new cards for 2 consecutive pages, we're done
        if cards_processed_this_page == 0 and carousel_page > 2:
            print("[accounts] No new accounts found, stopping.")
            break
        
        # Check for right arrow to navigate to next carousel page
        print("[accounts] Checking for right arrow...")
        try:
            right_arrow = page.locator('rds-directional-arrow button.right').first
            
            # Check if arrow exists and is visible
            if right_arrow.count() > 0:
                is_visible = right_arrow.is_visible()
                is_disabled = right_arrow.is_disabled()
                print(f"[accounts] Right arrow found: visible={is_visible}, disabled={is_disabled}")
                
                if is_visible and not is_disabled:
                    print("[accounts] Clicking right arrow to next page...")
                    right_arrow.click()
                    time.sleep(2)  # Wait for carousel animation
                    carousel_page += 1
                else:
                    print("[accounts] Right arrow disabled or not visible - reached end.")
                    break
            else:
                print("[accounts] No right arrow found - single page carousel.")
                break
        except Exception as e:
            print(f"[accounts] Error checking right arrow: {e}")
            break
    
    if carousel_page > max_pages:
        print(f"[accounts] WARNING: Reached max carousel pages ({max_pages}), stopping.")
    
    print(f"[accounts] Total unique accounts found: {len(accounts)}")
    return accounts

def _extract_bearer_token(page):
    """Try to extract bearer token from storage."""
    token = page.evaluate("""() => {
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            const value = localStorage.getItem(key);
            if (value && (value.includes('Bearer') || key.includes('token') || key.includes('auth'))) {
                try {
                    const parsed = JSON.parse(value);
                    if (parsed.access_token) return parsed.access_token;
                    if (parsed.token) return parsed.token;
                    if (typeof parsed === 'string' && parsed.startsWith('Bearer ')) {
                        return parsed.substring(7);
                    }
                } catch {
                    if (typeof value === 'string' && value.match(/^[A-Za-z0-9_-]{20,}$/)) {
                        return value;
                    }
                }
            }
        }
        
        for (let i = 0; i < sessionStorage.length; i++) {
            const key = sessionStorage.key(i);
            const value = sessionStorage.getItem(key);
            if (value && (value.includes('Bearer') || key.includes('token') || key.includes('auth'))) {
                try {
                    const parsed = JSON.parse(value);
                    if (parsed.access_token) return parsed.access_token;
                    if (parsed.token) return parsed.token;
                    if (typeof parsed === 'string' && parsed.startsWith('Bearer ')) {
                        return parsed.substring(7);
                    }
                } catch {
                    if (typeof value === 'string' && value.match(/^[A-Za-z0-9_-]{20,}$/)) {
                        return value;
                    }
                }
            }
        }
        return null;
    }""")
    
    if token:
        print(f"[token] Found token in storage: {token[:20]}...", flush=True)
    return token

def _load_cached_token():
    if not TOKEN_CACHE_FILE.exists():
        return None
    try:
        data = TOKEN_CACHE_FILE.read_text(encoding="utf-8").strip()
        if not data:
            return None
        payload = None
        try:
            payload = json.loads(data)
        except Exception:
            payload = None
        if isinstance(payload, dict):
            token = payload.get("token")
            if token:
                return token
        if isinstance(data, str) and data.startswith("{") is False:
            return data
    except Exception:
        return None
    return None

def _save_cached_token(token):
    if not token:
        return
    try:
        TOKEN_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE_FILE.write_text(json.dumps({"token": token}), encoding="utf-8")
    except Exception:
        pass

def _clear_cached_token():
    try:
        if TOKEN_CACHE_FILE.exists():
            TOKEN_CACHE_FILE.unlink()
    except Exception:
        pass

def _extract_bearer_token_from_storage_state(context):
    try:
        state = context.storage_state()
    except Exception:
        return None
    origins = state.get("origins", []) if isinstance(state, dict) else []
    for origin in origins:
        for item in origin.get("localStorage", []) + origin.get("sessionStorage", []):
            key = item.get("name", "")
            value = item.get("value", "")
            if value and (value.find("Bearer") >= 0 or "token" in key or "auth" in key):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, dict):
                        if parsed.get("access_token"):
                            return parsed.get("access_token")
                        if parsed.get("token"):
                            return parsed.get("token")
                    if isinstance(parsed, str) and parsed.startswith("Bearer "):
                        return parsed[7:]
                except Exception:
                    if isinstance(value, str) and re.match(r'^[A-Za-z0-9_-]{20,}$', value):
                        return value
    return None

def _get_bearer_token(context, page):
    """Extract bearer token from storage/cache or capture from API requests."""
    print("[token] Extracting bearer token...", flush=True)
    cached = _load_cached_token()
    if cached:
        print("[token] Using cached token...", flush=True)
        return cached
    
    token = _extract_bearer_token_from_storage_state(context)
    if token:
        print(f"[token] Found token in storage state: {token[:20]}...", flush=True)
        _save_cached_token(token)
        return token
    
    token = _extract_bearer_token(page)
    if token:
        _save_cached_token(token)
        return token
    
    print("[token] Token not found in storage, capturing from API requests...", flush=True)
    captured_token = {'value': None}
    
    def handle_request(route, request):
        auth_header = request.headers.get('authorization', '')
        if auth_header.startswith('Bearer '):
            captured_token['value'] = auth_header[7:]
            print(f"[token] Captured: {captured_token['value'][:20]}...", flush=True)
        route.continue_()
    
    page.route('**/api/**', handle_request)
    try:
        # networkidle is brittle for SPA apps; use domcontentloaded with a timeout.
        page.goto(URL_DASHBOARD, wait_until="domcontentloaded", timeout=15000)
    except Exception:
        # If navigation fails, try a reload to trigger requests
        try:
            page.reload(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            pass

    time.sleep(3)
    if not captured_token['value']:
        try:
            page.reload(wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)
        except Exception:
            pass
    page.unroute('**/api/**')
    token = captured_token['value']
    if token:
        _save_cached_token(token)
    return token

def _money_dict_from_api(amount_obj):
    if not amount_obj or not isinstance(amount_obj, dict):
        return None
    amount = amount_obj.get('amount')
    currency = amount_obj.get('currencyCode') or amount_obj.get('currency')
    return {"amount": amount, "currencyCode": currency}

def _parse_money_text(text):
    if not text:
        return None
    s = ' '.join(text.split()).strip()
    if not s:
        return None
    
    currency_match = re.search(r'([A-Z]{3})$', s)
    currency = currency_match.group(1) if currency_match else None
    
    number_match = re.search(r'-?[\d\.\s]+,\d+|-?[\d\.\s]+', s)
    if not number_match:
        return {"amount": None, "currencyCode": currency}
    
    num = number_match.group(0).replace(' ', '').replace('.', '').replace(',', '.')
    try:
        amount = float(num)
    except Exception:
        amount = None
    
    return {"amount": amount, "currencyCode": currency}

def _parse_money_pair(text):
    if not text:
        return (None, None)
    parts = [p.strip() for p in text.split(" / ")]
    primary = _parse_money_text(parts[0]) if len(parts) > 0 else None
    secondary = _parse_money_text(parts[1]) if len(parts) > 1 else None
    return (primary, secondary)

def _parse_percent_text(text):
    if not text:
        return None
    m = re.search(r'-?[\d\.\s]+,\d+|-?[\d\.\s]+', text)
    if not m:
        return None
    num = m.group(0).replace(' ', '').replace('.', '').replace(',', '.')
    try:
        return float(num) / 100.0
    except Exception:
        return None

def _format_money_for_print(money):
    if not money or not isinstance(money, dict):
        return "N/A"
    amount = money.get("amount")
    currency = money.get("currencyCode")
    if amount is None:
        return "N/A" if not currency else f"N/A {currency}"
    if currency:
        return f"{amount:,.2f} {currency}"
    return f"{amount:,.2f}"

def _format_money_pair_for_print(primary, secondary):
    primary_str = _format_money_for_print(primary)
    if secondary and isinstance(secondary, dict) and secondary.get("amount") is not None:
        secondary_str = _format_money_for_print(secondary)
        return f"{primary_str} / {secondary_str}"
    return primary_str

def _format_profit_loss_for_print(profit_loss):
    if not profit_loss or not isinstance(profit_loss, dict):
        return "N/A"
    percent = profit_loss.get("percent")
    if percent is None:
        return "N/A"
    return f"{percent * 100:.2f}%"

def _prune_none(value):
    if isinstance(value, dict):
        pruned = {}
        for k, v in value.items():
            pv = _prune_none(v)
            if pv is not None:
                pruned[k] = pv
        return pruned or None
    if isinstance(value, list):
        items = [v for v in (_prune_none(v) for v in value) if v is not None]
        return items or None
    return value

def _product_to_account(product):
    account_type = product.get('smallHeader') or product.get('type') or "Unknown"
    name = product.get('largeHeader') or "Unknown"
    product_type = product.get('type') or ""
    details = product.get('details') or {}
    
    if product_type == "DEPOT":
        iban = product.get('productId') or product.get('uniqueId') or "Unknown"
        value = _money_dict_from_api(details.get('betragKontoWaehrung'))
        value_eur = None
        profit_loss_eur = _money_dict_from_api(details.get('betragInEuro'))
        profit_loss_percent = details.get('entwicklungProzent')
        profit_loss = {
            "amount": profit_loss_eur.get("amount") if profit_loss_eur else None,
            "currencyCode": profit_loss_eur.get("currencyCode") if profit_loss_eur else None,
            "percent": (profit_loss_percent / 100.0) if profit_loss_percent is not None else None
        }
        available = None
        available_eur = None
    else:
        iban = product.get('uniqueId') or "Unknown"
        balance = _money_dict_from_api(details.get('betragKontoWaehrung'))
        balance_eur = _money_dict_from_api(details.get('betragInEuro'))
        available = _money_dict_from_api(details.get('verfuegbarKontoWaehrung'))
        available_eur = _money_dict_from_api(details.get('verfuegbarInEuro'))
        if available is None:
            available = balance
        profit_loss = None
    
    if product_type == "DEPOT":
        return {
            "type": account_type,
            "name": name,
            "iban": iban,
            "value": value,
            "value_eur": value_eur,
            "profit_loss": profit_loss
        }
    
    return {
        "type": account_type,
        "name": name,
        "iban": iban,
        "balance": balance,
        "balance_eur": balance_eur,
        "available": available,
        "available_eur": available_eur,
        "profit_loss": profit_loss
    }

def fetch_accounts_api(token, cookies):
    """Fetch accounts via products API.

    Returns: (accounts, raw_path) where raw_path points to the bank-native products JSON.
    """
    url = "https://mein.elba.raiffeisen.at/api/bankingws-widgetsystem/bankingws-ui/rest/produkte?skipImages=true"

    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Safari/605.1.15",
    }

    print("[api] Fetching products...", flush=True)

    try:
        response = requests.get(url, headers=headers, cookies=cookies)
        if response.status_code == 200:
            products = response.json()
            print(f"[api] Found {len(products)} products", flush=True)
            raw_path = _write_debug_json("products-raw", products)
            return ([_product_to_account(p) for p in products], raw_path)

        print(f"[api] Request failed with status {response.status_code}: {response.text}", flush=True)
        return (None, None)
    except Exception as e:
        print(f"[api] Error: {e}", flush=True)
        return (None, None)
    except Exception as e:
        print(f"[api] Error: {e}", flush=True)
        return None


def fetch_documents(page, output_dir=None, date_from=None, date_to=None):
    """Fetch and download documents from mailbox."""
    print("[documents] Navigating to documents page...")
    try:
        page.goto(URL_DOCUMENTS, wait_until="networkidle")
        time.sleep(3)
    except Exception as e:
        error_msg = str(e)
        if "ERR_CONNECTION_RESET" in error_msg or "connection was reset" in error_msg.lower():
            print("[documents] ERROR: Connection reset. ELBA server connection failed.")
            return []
        else:
            print(f"[documents] ERROR: Navigation failed: {e}")
            return []
    
    # Apply date filter if provided
    if date_from or date_to:
        print(f"[documents] Applying date filter: {date_from or 'any'} to {date_to or 'any'}", flush=True)
        try:
            if date_from:
                from_input = page.locator('input[formcontrolname="fromDate"]')
                from_input.fill(date_from)
                print(f"[documents] Filled 'from' date: {date_from}, pressing Tab...", flush=True)
                page.keyboard.press("Tab")
                print("[documents] Waiting for page to reload after 'from' date...", flush=True)
                time.sleep(3)
            
            if date_to:
                to_input = page.locator('input[formcontrolname="toDate"]')
                to_input.fill(date_to)
                print(f"[documents] Filled 'to' date: {date_to}, pressing Tab...", flush=True)
                page.keyboard.press("Tab")
                print("[documents] Waiting for page to reload after 'to' date...", flush=True)
                time.sleep(3)
            
            # Wait for results to fully load
            print("[documents] Waiting for filtered results to load...", flush=True)
            time.sleep(3)
        except Exception as e:
            print(f"[documents] Warning: Could not apply date filter: {e}", flush=True)
    
    # Set up download directory
    if not output_dir:
        output_dir = Path.home() / "clawd" / "raiffeisen-elba" / "documents"
    else:
        output_dir = Path(output_dir)
    
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[documents] Saving to: {output_dir}")
    
    # Configure browser downloads
    # Note: Playwright handles downloads via download events
    
    documents = []
    downloaded_files = set()  # Track downloaded files to avoid duplicates
    processed_docs = set()  # Track document names we've already processed
    
    # Download documents while scrolling (virtual scroller removes items from DOM as you scroll)
    print("[documents] Starting download with infinite scroll...")
    print("[documents] Downloading documents as they appear (virtual scroller)", flush=True)
    time.sleep(3)
    
    no_new_downloads_count = 0
    max_no_change_attempts = 50  # Increased to ensure we get all 189+ documents (need more scrolling)
    total_processed = 0
    successful_downloads = 0
    
    # Find the virtual scroller (the inner scroll container)
    scroller = page.locator('virtual-scroller.vertical.selfScroll')
    
    while no_new_downloads_count < max_no_change_attempts:
        # Get currently visible document rows
        doc_rows = page.locator('rds-list-item-row').all()
        
        downloads_this_batch = 0
        
        # Process each visible row
        for row in doc_rows:
            try:
                # Check if this row has a download button
                download_btn = row.locator('button[icon="download"]').first
                if download_btn.count() == 0:
                    continue  # Skip rows without download buttons
                
                # Extract document name for logging
                try:
                    name_elem = row.locator('p.rds-body-strong.dok-truncate-2-lines')
                    doc_name = name_elem.inner_text(timeout=1000).strip()
                except:
                    doc_name = f"document_{total_processed}"
                
                # Create a unique identifier for this row (button element ID or position)
                try:
                    button_aria = download_btn.get_attribute('aria-label', timeout=1000)
                    row_id = button_aria if button_aria else doc_name
                except:
                    row_id = doc_name
                
                # Skip if we've already processed this exact button
                if row_id in processed_docs:
                    continue
                
                processed_docs.add(row_id)
                total_processed += 1
                
                print(f"\n[documents] Processing {total_processed}: {doc_name}", flush=True)
                
                # Try to download
                try:
                    
                    print(f"[documents]   → Initiating download...", flush=True)
                    with page.expect_download(timeout=30000) as download_info:
                        download_btn.click()
                        time.sleep(0.5)
                    
                    download = download_info.value
                    filename = download.suggested_filename
                    
                    # Handle duplicate filenames by adding (2), (3), etc.
                    base_filepath = output_dir / filename
                    if base_filepath.exists() or filename in downloaded_files:
                        # Extract name and extension
                        name_parts = filename.rsplit('.', 1)
                        if len(name_parts) == 2:
                            base_name, ext = name_parts
                        else:
                            base_name, ext = filename, ''
                        
                        # Find next available number
                        counter = 2
                        while True:
                            new_filename = f"{base_name} ({counter}){('.' + ext) if ext else ''}"
                            new_filepath = output_dir / new_filename
                            if not new_filepath.exists() and new_filename not in downloaded_files:
                                filename = new_filename
                                filepath = new_filepath
                                break
                            counter += 1
                    else:
                        filepath = base_filepath
                    
                    download.save_as(filepath)
                    downloaded_files.add(filename)
                    successful_downloads += 1
                    downloads_this_batch += 1
                    
                    print(f"[documents]   ✓ Downloaded {successful_downloads}: {filename}", flush=True)
                    print(f"[documents]   ✓ Saved to: {filepath}", flush=True)
                    
                    time.sleep(1)  # Rate limit
                    
                except Exception as e:
                    print(f"[documents]   ✗ Error downloading: {e}", flush=True)
            except Exception as e:
                print(f"[documents] Error processing row: {e}", flush=True)
                continue
        
        # Scroll to load more
        if downloads_this_batch > 0:
            no_new_downloads_count = 0
            print(f"[documents] Downloaded {downloads_this_batch} new document(s) this batch, scrolling for more...", flush=True)
        else:
            no_new_downloads_count += 1
            print(f"[documents] No new documents this batch ({no_new_downloads_count}/{max_no_change_attempts}), scrolling...", flush=True)
        
        # Scroll more aggressively to trigger lazy loading
        scroller.evaluate("el => el.scrollBy(0, 2000)")
        time.sleep(5)  # Longer wait to ensure lazy load completes
    
    print(f"\n[documents] Downloaded {successful_downloads} document(s) to {output_dir}", flush=True)
    return documents


def cmd_setup():
    """Interactive setup wizard."""
    print("Raiffeisen ELBA Setup")
    print("---------------------")
    
    # Ensure directories
    if not CREDENTIALS_DIR.exists():
        CREDENTIALS_DIR.mkdir(parents=True)
        print(f"Created {CREDENTIALS_DIR}")
        
    elba_id = input("Enter ELBA-Verfügernummer (e.g., ELVIE32V...): ").strip()
    pin = input("Enter PIN (5 digits): ").strip()
    
    if not elba_id or not pin:
        print("Error: ID and PIN are required.")
        return
        
    # Write to .env
    with open(CREDENTIALS_FILE, 'w') as f:
        f.write(f"ELBA_ID={elba_id}\n")
        f.write(f"ELBA_PIN={pin}\n")
    
    print(f"Credentials saved to {CREDENTIALS_FILE}")
    
    # Verify Playwright
    print("Verifying Playwright installation...")
    try:
        import playwright
        os.system("playwright install chromium")
    except ImportError:
        print("Please install playwright: pip3 install playwright")

def cmd_login(headless=True):
    """Run the login flow."""
    elba_id, pin = load_credentials()
    if not elba_id or not pin:
        print("Credentials not found. Run 'setup' first.")
        sys.exit(1)
        
    with sync_playwright() as p:
        # Create persistent context
        if not PROFILE_DIR.exists():
            PROFILE_DIR.mkdir(parents=True)
            
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 800}
        )
        
        page = context.new_page()
        try:
            if login(page, elba_id, pin):
                print("Session saved.")
            else:
                sys.exit(1)
        finally:
            context.close()

def cmd_logout():
    """Clear the session."""
    if PROFILE_DIR.exists():
        import shutil
        shutil.rmtree(PROFILE_DIR)
        print("Session cleared.")
    else:
        print("No session found.")


def cmd_accounts(headless=True, json_output=False):
    """List all accounts (logs in automatically if needed)."""
    elba_id, pin = load_credentials()
    if not elba_id or not pin:
        print("Credentials not found. Run 'setup' first.")
        sys.exit(1)
    
    # Ensure profile dir exists
    if not PROFILE_DIR.exists():
        PROFILE_DIR.mkdir(parents=True)
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 800}
        )
        
        page = context.new_page()
        raw_path = None
        
        try:
            # Try to use existing session first (no forced login)
            print("[accounts] Attempting to access dashboard (reuse session)...")
            try:
                page.goto(URL_DASHBOARD, wait_until="domcontentloaded")
                time.sleep(2)
            except Exception as e:
                error_msg = str(e)
                if "ERR_CONNECTION_RESET" in error_msg or "connection was reset" in error_msg.lower():
                    print("[accounts] ERROR: Connection reset. ELBA server connection failed.")
                    print("[accounts] Please try again later.")
                    sys.exit(1)
                else:
                    raise
            
            # Check for connection errors on the page
            page_content = page.content()
            if "ERR_CONNECTION_RESET" in page_content or "connection was reset" in page_content.lower():
                print("[accounts] ERROR: Connection reset. ELBA server connection failed.")
                print("[accounts] Please try again later.")
                sys.exit(1)
            
            # Prefer API for accounts (reuse token from prior login)
            token = _get_bearer_token(context, page)
            accounts = None
            if token:
                cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                accounts, raw_path = fetch_accounts_api(token, cookies)

                # Common failure: cached token expired -> 401. Clear cache and retry once.
                if accounts is None:
                    _clear_cached_token()
                    token = _get_bearer_token(context, page)
                    if token:
                        cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                        accounts, raw_path = fetch_accounts_api(token, cookies)

            # If API failed, then login and retry once
            if accounts is None:
                print("[accounts] API request failed or no token; performing login...")
                if not login(page, elba_id, pin):
                    print("[accounts] Login failed.")
                    sys.exit(1)

                # After login, force token re-extraction (cached token might be stale).
                _clear_cached_token()
                token = _get_bearer_token(context, page)
                if token:
                    cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                    accounts, raw_path = fetch_accounts_api(token, cookies)

            if accounts is None:
                print("[accounts] WARNING: API unavailable, falling back to scraping.")
                accounts = fetch_accounts(page)

            wrapper = canonicalize_accounts_elba(accounts or [], raw_path=raw_path)

            if json_output:
                print(json.dumps(wrapper, ensure_ascii=False, indent=2))
            else:
                print(f"[accounts] {len(wrapper['accounts'])} account(s):")
                for acc in wrapper["accounts"]:
                    name = acc.get("name") or "N/A"
                    iban = acc.get("iban")
                    iban_clean = "".join(str(iban).split()) if iban is not None else ""
                    iban_short = f"{iban_clean[:4]}...{iban_clean[-4:]}" if len(iban_clean) > 8 else (iban_clean or "IBAN N/A")
                    typ = acc.get("type") or "other"
                    cur = acc.get("currency") or "EUR"

                    balances = acc.get("balances") if isinstance(acc.get("balances"), dict) else None
                    booked = balances.get("booked") if isinstance(balances, dict) else None
                    available = balances.get("available") if isinstance(balances, dict) else None

                    sec = acc.get("securities") if isinstance(acc.get("securities"), dict) else None
                    sec_value = sec.get("value") if isinstance(sec, dict) else None

                    if isinstance(sec_value, dict) and sec_value.get("amount") is not None:
                        v_s = f"{_eu_amount(float(sec_value['amount']))} {cur}"
                        pl = sec.get("profitLoss") if isinstance(sec, dict) else None
                        pl_s = ""
                        if isinstance(pl, dict) and pl.get("amount") is not None:
                            pl_s = f" (P/L {_eu_amount(float(pl['amount']))} {cur}" + (f" / {float(pl.get('percent'))*100:.1f}%" if pl.get("percent") is not None else "") + ")"
                        print(f"- {name} — {iban_short} — value {v_s}{pl_s} — {typ}")
                        continue

                    booked_s = "N/A"
                    avail_s = None
                    if isinstance(booked, dict) and booked.get("amount") is not None:
                        booked_s = f"{_eu_amount(float(booked['amount']))} {cur}"
                    if isinstance(available, dict) and available.get("amount") is not None:
                        avail_s = f"{_eu_amount(float(available['amount']))} {cur}"

                    if avail_s and avail_s != booked_s:
                        print(f"- {name} — {iban_short} — {booked_s} (avail {avail_s}) — {typ}")
                    else:
                        print(f"- {name} — {iban_short} — {booked_s} — {typ}")

                if wrapper.get("rawPath"):
                    print(f"[accounts] raw payload saved: {wrapper['rawPath']}")
            
        finally:
            context.close()


def cmd_download(headless=True, output_dir=None, date_from=None, date_to=None, json_output=False):
    """Download documents from mailbox (logs in automatically if needed)."""
    print("[INIT] Starting ELBA document download...", flush=True)
    elba_id, pin = load_credentials()
    if not elba_id or not pin:
        print("Credentials not found. Run 'setup' first.", flush=True)
        sys.exit(1)
    print(f"[INIT] Loaded credentials for {elba_id[:8]}...", flush=True)
    
    # Ensure profile dir exists
    if not PROFILE_DIR.exists():
        PROFILE_DIR.mkdir(parents=True)
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 800},
            accept_downloads=True
        )
        
        page = context.new_page()
        raw_path = None
        
        try:
            # Try to navigate to documents first
            print("[download] Attempting to access documents page...")
            try:
                page.goto(URL_DOCUMENTS, wait_until="networkidle")
                time.sleep(2)
            except Exception as e:
                error_msg = str(e)
                if "ERR_CONNECTION_RESET" in error_msg or "connection was reset" in error_msg.lower():
                    print("[download] ERROR: Connection reset. ELBA server connection failed.")
                    print("[download] Please try again later.")
                    sys.exit(1)
                else:
                    raise
            
            # Check if we got redirected to login
            if "sso.raiffeisen.at" in page.url or "mein-login" in page.url:
                print("[download] Not logged in, performing login...")
                if not login(page, elba_id, pin):
                    print("[download] Login failed.")
                    sys.exit(1)
                # After successful login, navigate to documents
                print("[download] Login successful, navigating to documents...")
                page.goto(URL_DOCUMENTS, wait_until="networkidle")
                time.sleep(2)
            else:
                print("[download] Already logged in!")
            
            # Now fetch and download documents
            documents = fetch_documents(page, output_dir, date_from, date_to)
            
            if json_output:
                import json
                print(json.dumps(documents, ensure_ascii=False, indent=2))
            elif not documents:
                print("No documents downloaded.")
            
        finally:
            context.close()

def cmd_transactions(headless=True, iban=None, date_from=None, date_to=None, output=None, fmt="json"):
    """Download transactions for a single IBAN (logs in automatically if needed)."""
    if not iban or not date_from or not date_to:
        print("Missing required arguments: --iban, --from, --until")
        sys.exit(1)
    
    elba_id, pin = load_credentials()
    if not elba_id or not pin:
        print("Credentials not found. Run 'setup' first.")
        sys.exit(1)
    
    if not PROFILE_DIR.exists():
        PROFILE_DIR.mkdir(parents=True)
    
    from download_transactions import fetch_transactions_all, export_to_csv, export_to_json
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 800}
        )
        
        page = context.new_page()
        try:
            print("[transactions] Attempting to access documents (reuse session)...")
            page.goto(URL_DOCUMENTS, wait_until="domcontentloaded")
            time.sleep(2)
            
            token = _get_bearer_token(context, page)
            if not token:
                print("[transactions] Token not found, performing login...")
                if not login(page, elba_id, pin):
                    print("[transactions] Login failed.")
                    sys.exit(1)
                token = _get_bearer_token(context, page)
            
            if not token:
                print("[transactions] ERROR: Could not extract bearer token")
                sys.exit(1)
            
            cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
            transactions, status_code = fetch_transactions_all(token, cookies, iban, date_from, date_to)
            
            if transactions is None and status_code == 401:
                print("[transactions] Token rejected (401). Clearing cache and re-authenticating...", flush=True)
                _clear_cached_token()
                if not login(page, elba_id, pin):
                    print("[transactions] Login failed.")
                    sys.exit(1)
                token = _get_bearer_token(context, page)
                if not token:
                    print("[transactions] ERROR: Could not extract bearer token")
                    sys.exit(1)
                cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                transactions, status_code = fetch_transactions_all(token, cookies, iban, date_from, date_to)
            
            if transactions is None:
                print("[transactions] Failed to fetch transactions")
                sys.exit(1)
            
            if len(transactions) == 0:
                print("[transactions] No transactions found in date range")
                sys.exit(0)
            
            if not output:
                output = f"transactions_{iban.replace('AT', '')}_{date_from}_{date_to}"
            
            if fmt in ["csv", "both"]:
                export_to_csv(transactions, Path(f"{output}.csv"))
            if fmt in ["json", "both"]:
                pruned = [_prune_none(tx) for tx in transactions]
                pruned = [tx for tx in pruned if tx is not None]
                export_to_json(pruned, Path(f"{output}.json"))
            
            print("[transactions] Export complete")
        finally:
            context.close()

def _fetch_portfolio(token, cookies, depot_id, as_of_date=None):
    base_url = "https://mein.elba.raiffeisen.at/api/bankingwp-depotzentrale/depotzentrale-ui/rest/positionsuebersicht"
    if as_of_date:
        url = f"{base_url}/{depot_id}/{as_of_date}"
    else:
        url = f"{base_url}/{depot_id}"
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Safari/605.1.15"
    }
    
    try:
        response = requests.get(url, headers=headers, cookies=cookies)
        if response.status_code == 200:
            return response.json(), response.status_code
        return {"error": response.text}, response.status_code
    except Exception as e:
        return {"error": str(e)}, None

def cmd_portfolio(headless=True, depot_id=None, as_of_date=None, json_output=False):
    """Fetch depot portfolio positions."""
    if not depot_id:
        print("Missing required argument: --depot-id")
        sys.exit(1)
    
    elba_id, pin = load_credentials()
    if not elba_id or not pin:
        print("Credentials not found. Run 'setup' first.")
        sys.exit(1)
    
    if not PROFILE_DIR.exists():
        PROFILE_DIR.mkdir(parents=True)
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1280, "height": 800}
        )
        
        page = context.new_page()
        try:
            print("[portfolio] Attempting to access documents (reuse session)...")
            page.goto(URL_DOCUMENTS, wait_until="domcontentloaded")
            time.sleep(2)
            
            token = _get_bearer_token(context, page)
            if not token:
                print("[portfolio] Token not found, performing login...")
                if not login(page, elba_id, pin):
                    print("[portfolio] Login failed.")
                    sys.exit(1)
                token = _get_bearer_token(context, page)
            
            if not token:
                print("[portfolio] ERROR: Could not extract bearer token")
                sys.exit(1)
            
            cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
            data, status_code = _fetch_portfolio(token, cookies, depot_id, as_of_date)
            
            if status_code == 401:
                print("[portfolio] Token rejected (401). Clearing cache and re-authenticating...", flush=True)
                _clear_cached_token()
                if not login(page, elba_id, pin):
                    print("[portfolio] Login failed.")
                    sys.exit(1)
                token = _get_bearer_token(context, page)
                if not token:
                    print("[portfolio] ERROR: Could not extract bearer token")
                    sys.exit(1)
                cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
                data, status_code = _fetch_portfolio(token, cookies, depot_id, as_of_date)
            
            if status_code != 200:
                print("[portfolio] Failed to fetch portfolio")
                print(json.dumps(data, ensure_ascii=False, indent=2))
                sys.exit(1)
            
            pruned = _prune_none(data)
            if json_output:
                print(json.dumps(pruned, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(pruned, ensure_ascii=False, indent=2))
        finally:
            context.close()
def main():
    parser = argparse.ArgumentParser(description="Raiffeisen ELBA Automation")
    subparsers = parser.add_subparsers(dest="command")
    
    subparsers.add_parser("setup", help="Configure credentials")
    
    login_parser = subparsers.add_parser("login", help="Login and save session")
    login_parser.add_argument("--visible", action="store_true", help="Show browser")
    
    subparsers.add_parser("logout", help="Clear session")
    
    accounts_parser = subparsers.add_parser("accounts", help="List accounts")
    accounts_parser.add_argument("--visible", action="store_true", help="Show browser")
    accounts_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    download_parser = subparsers.add_parser("download", help="Download documents from mailbox")
    download_parser.add_argument("--visible", action="store_true", help="Show browser")
    download_parser.add_argument("--json", action="store_true", help="Output as JSON")
    download_parser.add_argument("-o", "--output", help="Output directory for documents")
    download_parser.add_argument("--from", dest="date_from", help="Start date (DD.MM.YYYY)")
    download_parser.add_argument("--until", dest="date_to", help="End date (DD.MM.YYYY)")
    
    transactions_parser = subparsers.add_parser("transactions", help="Download transactions for an IBAN")
    transactions_parser.add_argument("--visible", action="store_true", help="Show browser")
    transactions_parser.add_argument("--iban", required=True, help="IBAN to fetch transactions for")
    transactions_parser.add_argument("--from", dest="date_from", required=True, help="Start date (YYYY-MM-DD)")
    transactions_parser.add_argument("--until", dest="date_to", required=True, help="End date (YYYY-MM-DD)")
    transactions_parser.add_argument("--format", dest="fmt", choices=["csv", "json", "both"], default="json", help="Output format")
    transactions_parser.add_argument("--output", help="Output file base name (without extension)")
    
    portfolio_parser = subparsers.add_parser("portfolio", help="Fetch depot portfolio positions")
    portfolio_parser.add_argument("--visible", action="store_true", help="Show browser")
    portfolio_parser.add_argument("--depot-id", dest="depot_id", required=True, help="Depot ID (e.g., 3293966252586)")
    portfolio_parser.add_argument("--date", dest="as_of_date", help="As-of date (YYYY-MM-DD)")
    portfolio_parser.add_argument("--json", action="store_true", help="Output as JSON")
    
    subparsers.add_parser("balances", help="List balances")
    
    args = parser.parse_args()
    
    if args.command == "setup":
        cmd_setup()
    elif args.command == "login":
        cmd_login(headless=not args.visible)
    elif args.command == "logout":
        cmd_logout()
    elif args.command == "accounts":
        cmd_accounts(headless=not getattr(args, 'visible', False), json_output=getattr(args, 'json', False))
    elif args.command == "download":
        cmd_download(
            headless=not getattr(args, 'visible', False),
            output_dir=getattr(args, 'output', None),
            date_from=getattr(args, 'date_from', None),
            date_to=getattr(args, 'date_to', None),
            json_output=getattr(args, 'json', False)
        )
    elif args.command == "transactions":
        cmd_transactions(
            headless=not getattr(args, 'visible', False),
            iban=getattr(args, 'iban', None),
            date_from=getattr(args, 'date_from', None),
            date_to=getattr(args, 'date_to', None),
            output=getattr(args, 'output', None),
            fmt=getattr(args, 'fmt', "json")
        )
    elif args.command == "portfolio":
        cmd_portfolio(
            headless=not getattr(args, 'visible', False),
            depot_id=getattr(args, 'depot_id', None),
            as_of_date=getattr(args, 'as_of_date', None),
            json_output=getattr(args, 'json', False)
        )
    elif args.command == "balances":
        print("Not implemented yet. Please run 'login' first to ensure access.")
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
