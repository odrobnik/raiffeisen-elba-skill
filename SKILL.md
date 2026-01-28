---
name: raiffeisen-elba
description: "Automate Raiffeisen ELBA online banking using Playwright: login/session (pushTAN 2FA approval), list accounts, download documents, and fetch transactions via API. Use when the user mentions ELBA, Raiffeisen, or Austrian Raiffeisen banking."
summary: "Raiffeisen ELBA banking automation: login, accounts, documents, and transactions."
version: 1.0.0
homepage: https://github.com/clawdbot-skills/raiffeisen-elba
metadata: {"clawdbot":{"emoji":"🏦","requires":{"bins":["python3","playwright"]}}}
---

# Raiffeisen ELBA Banking Automation

Automate **Raiffeisen ELBA** online banking.

**Entry point:** `{baseDir}/scripts/elba.py`

## Setup

### Quick setup (recommended)

```bash
python3 {baseDir}/scripts/elba.py setup
```

What `setup` does:
- Prompts for your **ELBA ID (Verfügernummer)** and **PIN**
- Writes `~/clawd/raiffeisen-elba/.env` with credentials
- Ensures Playwright is installed and installs Chromium

## Commands

### Session management

```bash
python3 {baseDir}/scripts/elba.py login             # Login and save session
python3 {baseDir}/scripts/elba.py logout            # Clear session
```

Session is persisted in `~/.moltbot/raiffeisen-elba/.pw-profile/`.

**Note:** Sessions and API tokens are cached in the Playwright profile and reused when possible.

### Accounts

```bash
python3 {baseDir}/scripts/elba.py accounts          # List all accounts (auto-login if needed)
python3 {baseDir}/scripts/elba.py accounts --visible # Show browser while fetching
python3 {baseDir}/scripts/elba.py accounts --json    # Output as JSON
python3 {baseDir}/scripts/elba.py --debug accounts  # Save bank-native payloads to debug/ (optional)
```

The `accounts` command will reuse a cached API token when available and only log in (pushTAN 2FA) if needed.

Shows:
- Account type (Giro, Depot, Kredit, etc.)
- Account name
- IBAN / Depot number
- Balance / Value
- Available amount / Performance (for Depot)

### Download Documents

```bash
python3 {baseDir}/scripts/elba.py download                    # Download all documents from mailbox
python3 {baseDir}/scripts/elba.py download --visible          # Show browser while downloading
python3 {baseDir}/scripts/elba.py download -o ~/docs          # Save to specific directory
python3 {baseDir}/scripts/elba.py download --json             # Output document list as JSON
python3 {baseDir}/scripts/elba.py download --from 01.01.2026  # Filter by start date
python3 {baseDir}/scripts/elba.py download --until 31.01.2026    # Filter by end date
python3 {baseDir}/scripts/elba.py download --from 01.01.2026 --until 31.01.2026  # Date range
```

Downloads documents (PDFs) from the ELBA mailbox/documents section. Each document includes:
- Document name
- Category (Anlegen, etc.)
- Account number
- File type and size

Date format: DD.MM.YYYY (e.g., 17.01.2026)

Default save location: `~/clawd/raiffeisen-elba/documents`

### Transactions

```bash
python3 {baseDir}/scripts/elba.py transactions --iban AT063293900008601411 --from 2025-01-01 --until 2025-12-31 --format json
python3 {baseDir}/scripts/elba.py transactions --iban AT063293900008601411 --from 2025-01-01 --until 2025-12-31 --format csv
python3 {baseDir}/scripts/elba.py transactions --iban AT063293900008601411 --from 2025-01-01 --until 2025-12-31 --format both
python3 {baseDir}/scripts/elba.py transactions --iban AT063293900008601411 --from 2025-01-01 --until 2025-12-31 --output /path/to/transactions_2025
```

The `transactions` command reuses cached API tokens and paginates until all results are retrieved.
Date format: YYYY-MM-DD.

## References

- `references/accounts.schema.json`
- `references/transactions.schema.json`

## Security notes

- Credentials (ELBA ID, PIN) are stored in `~/clawd/raiffeisen-elba/.env`.
- Login requires **pushTAN approval** in the Raiffeisen ELBA app.
