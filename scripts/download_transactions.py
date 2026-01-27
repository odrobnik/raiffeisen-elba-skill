#!/usr/bin/env python3
"""
Download bank transactions (Kontoumsätze) and export as CSV/JSON
"""
import sys
import time
import json
import csv
import requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from elba import load_credentials, login, URL_DOCUMENTS, PROFILE_DIR

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed")
    sys.exit(1)

def get_bearer_token_from_browser(page):
    """Extract bearer token from browser"""
    print("[token] Extracting bearer token...", flush=True)
    
    # Try localStorage/sessionStorage first
    token = page.evaluate("""() => {
        for (let i = 0; i < localStorage.length; i++) {
            const key = localStorage.key(i);
            const value = localStorage.getItem(key);
            if (value && (value.includes('Bearer') || key.includes('token') || key.includes('auth'))) {
                try {
                    const parsed = JSON.parse(value);
                    if (parsed.access_token) return parsed.access_token;
                    if (parsed.token) return parsed.token;
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
        print(f"[token] Found token: {token[:20]}...", flush=True)
        return token
    
    # Capture from network request
    print("[token] Capturing from API request...", flush=True)
    captured_token = {'value': None}
    
    def handle_request(route, request):
        auth_header = request.headers.get('authorization', '')
        if auth_header.startswith('Bearer '):
            captured_token['value'] = auth_header[7:]
            print(f"[token] Captured: {captured_token['value'][:20]}...", flush=True)
        route.continue_()
    
    page.route('**/api/**', handle_request)
    page.goto(URL_DOCUMENTS, wait_until="domcontentloaded")
    time.sleep(3)
    page.unroute('**/api/**')
    
    return captured_token['value']

def fetch_products(token, cookies):
    """Fetch all products (accounts, depots, credits)"""
    url = "https://mein.elba.raiffeisen.at/api/bankingws-widgetsystem/bankingws-ui/rest/produkte?skipImages=true"
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Safari/605.1.15"
    }
    
    print(f"[api] Fetching products...", flush=True)
    
    try:
        response = requests.get(url, headers=headers, cookies=cookies)
        
        if response.status_code == 200:
            products = response.json()
            print(f"[api] Found {len(products)} products", flush=True)
            return products
        else:
            print(f"[api] Request failed with status {response.status_code}: {response.text}", flush=True)
            return None
    except Exception as e:
        print(f"[api] Error: {e}", flush=True)
        return None

def fetch_transactions(token, cookies, iban, date_from, date_to, limit=3001):
    """Fetch transactions for a specific IBAN and date range"""
    url = "https://mein.elba.raiffeisen.at/api/bankingzv-umsatz/umsatz-ui/rest/kontoumsaetze"
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3 Safari/605.1.15"
    }
    
    body = {
        "predicate": {
            "buchungVon": f"{date_from}T00:00:00.000",
            "buchungBis": f"{date_to}T23:59:59.999",
            "neuanlageBis": None,
            "idBis": None,
            "betragVon": None,
            "betragBis": None,
            "betragsrichtung": "BEIDE",
            "kategorieCodes": None,
            "kategorieCodesNotIn": False,
            "hashtags": None,
            "ibans": [iban],
            "pending": True,
            "folgenummernKarteByIban": None
        },
        "limit": limit
    }
    
    print(f"[api] Fetching transactions for {iban} from {date_from} to {date_to}...", flush=True)
    
    try:
        response = requests.post(url, json=body, headers=headers, cookies=cookies)
        
        if response.status_code == 200:
            data = response.json()
            transactions = data.get('kontoumsaetze', [])
            print(f"[api] Received {len(transactions)} transactions", flush=True)
            return transactions
        else:
            print(f"[api] Request failed with status {response.status_code}: {response.text}", flush=True)
            return None
    except Exception as e:
        print(f"[api] Error: {e}", flush=True)
        return None

def export_to_csv(transactions, output_file):
    """Export transactions to CSV"""
    if not transactions:
        print(f"[csv] No transactions to export")
        return
    
    print(f"[csv] Writing {len(transactions)} transactions to {output_file}...", flush=True)
    
    # Define CSV columns based on actual API response
    fieldnames = [
        'id', 'buchungstag', 'valuta', 'betrag', 'waehrung',
        'transaktionsteilnehmer', 'verwendungszweck', 'zahlungsreferenz',
        'kategorieCode', 'iban', 'auftraggeberIban', 'auftraggeberBic',
        'bestandreferenz', 'ersterfasserreferenz'
    ]
    
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        
        for tx in transactions:
            # Extract amount
            betrag_obj = tx.get('betrag', {})
            betrag = betrag_obj.get('amount', '') if isinstance(betrag_obj, dict) else betrag_obj
            waehrung = betrag_obj.get('currency', '') if isinstance(betrag_obj, dict) else 'EUR'
            
            row = {
                'id': tx.get('id', ''),
                'buchungstag': tx.get('buchungstag', ''),
                'valuta': tx.get('valuta', ''),
                'betrag': betrag,
                'waehrung': waehrung,
                'transaktionsteilnehmer': tx.get('transaktionsteilnehmerZeile1', ''),
                'verwendungszweck': tx.get('verwendungszweckZeile1', ''),
                'zahlungsreferenz': tx.get('zahlungsreferenz', ''),
                'kategorieCode': tx.get('kategorieCode', ''),
                'iban': tx.get('iban', ''),
                'auftraggeberIban': tx.get('auftraggeberIban', ''),
                'auftraggeberBic': tx.get('auftraggeberBic', ''),
                'bestandreferenz': tx.get('bestandreferenz', ''),
                'ersterfasserreferenz': tx.get('ersterfasserreferenz', '')
            }
            writer.writerow(row)
    
    print(f"[csv] Export complete: {output_file}", flush=True)

def export_to_json(transactions, output_file):
    """Export transactions to JSON"""
    if not transactions:
        print(f"[json] No transactions to export")
        return
    
    print(f"[json] Writing {len(transactions)} transactions to {output_file}...", flush=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(transactions, f, indent=2, ensure_ascii=False)
    
    print(f"[json] Export complete: {output_file}", flush=True)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Download ELBA transactions as CSV/JSON')
    parser.add_argument('--list-accounts', action='store_true', help='List all accounts and exit')
    parser.add_argument('--iban', help='IBAN to fetch transactions for')
    parser.add_argument('--from', dest='date_from', help='Start date (YYYY-MM-DD)')
    parser.add_argument('--to', dest='date_to', help='End date (YYYY-MM-DD)')
    parser.add_argument('--format', choices=['csv', 'json', 'both'], default='both', help='Export format')
    parser.add_argument('--output', help='Output filename (without extension)')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.list_accounts:
        if not args.iban or not args.date_from or not args.date_to:
            parser.error('--iban, --from, and --to are required (unless --list-accounts is used)')
    
    # Continue with existing validation
    if args.date_from and args.date_to:
        # Validate dates
        try:
            datetime.strptime(args.date_from, '%Y-%m-%d')
            datetime.strptime(args.date_to, '%Y-%m-%d')
        except ValueError:
            print("ERROR: Dates must be in YYYY-MM-DD format")
            sys.exit(1)
    
    # Default output filename
    if not args.output:
        args.output = f"transactions_{args.iban.replace('AT', '')}_{args.date_from}_{args.date_to}"
    
    # Get credentials and login
    elba_id, pin = load_credentials()
    if not elba_id or not pin:
        print("ERROR: Credentials not found")
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
            print("[main] Logging in to get token...")
            page.goto(URL_DOCUMENTS, wait_until="networkidle")
            time.sleep(3)
            
            if "sso.raiffeisen.at" in page.url or "mein-login" in page.url:
                print("[main] Performing login...")
                if not login(page, elba_id, pin):
                    print("[main] Login failed")
                    sys.exit(1)
            
            # Get bearer token
            token = get_bearer_token_from_browser(page)
            if not token:
                print("[main] ERROR: Could not extract bearer token")
                sys.exit(1)
            
            # Get cookies
            cookies = {cookie['name']: cookie['value'] for cookie in context.cookies()}
            
            # Handle --list-accounts
            if args.list_accounts:
                products = fetch_products(token, cookies)
                if products is None:
                    print("[main] Failed to fetch products")
                    sys.exit(1)
                
                print(f"\n{'='*60}")
                print("Accounts:")
                print(f"{'='*60}\n")
                
                for product in products:
                    if product.get('type') == 'KONTO':
                        iban = product.get('uniqueId', '')
                        name = product.get('largeHeader', '')
                        details = product.get('details', {})
                        betrag = details.get('betragKontoWaehrung', {})
                        amount = betrag.get('amount', 0)
                        currency = betrag.get('currency', 'EUR')
                        
                        print(f"{iban}")
                        print(f"  Name: {name}")
                        print(f"  Balance: {amount:,.2f} {currency}")
                        print()
                
                sys.exit(0)
            
            # Fetch transactions
            transactions = fetch_transactions(token, cookies, args.iban, args.date_from, args.date_to)
            
            if transactions is None:
                print("[main] Failed to fetch transactions")
                sys.exit(1)
            
            if len(transactions) == 0:
                print("[main] No transactions found in date range")
                sys.exit(0)
            
            print(f"\n{'='*60}")
            print(f"Fetched {len(transactions)} transactions")
            print(f"{'='*60}\n")
            
            # Export
            if args.format in ['csv', 'both']:
                csv_file = Path(f"{args.output}.csv")
                export_to_csv(transactions, csv_file)
            
            if args.format in ['json', 'both']:
                json_file = Path(f"{args.output}.json")
                export_to_json(transactions, json_file)
            
            print(f"\n[main] Export complete!")
            
        finally:
            context.close()

if __name__ == "__main__":
    main()
