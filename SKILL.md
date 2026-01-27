---
name: raiffeisen-elba
description: "Automate Raiffeisen ELBA online banking using Playwright: login/session (pushTAN 2FA approval), list accounts + balances. Use when the user mentions ELBA, Raiffeisen, or Austrian Raiffeisen banking."
summary: "Raiffeisen ELBA banking automation: login, accounts, and balances."
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

Session is persisted in `~/.clawdbot/raiffeisen-elba/.pw-profile/`.

**Note:** ELBA sessions don't persist between browser sessions, so most commands will automatically log in if needed.

### Accounts

```bash
python3 {baseDir}/scripts/elba.py accounts          # List all accounts (auto-login if needed)
python3 {baseDir}/scripts/elba.py accounts --visible # Show browser while fetching
python3 {baseDir}/scripts/elba.py accounts --json    # Output as JSON
```

The `accounts` command will automatically perform login with pushTAN 2FA if not already authenticated.

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
python3 {baseDir}/scripts/elba.py download --to 31.01.2026    # Filter by end date
python3 {baseDir}/scripts/elba.py download --from 01.01.2026 --to 31.01.2026  # Date range
```

Downloads documents (PDFs) from the ELBA mailbox/documents section. Each document includes:
- Document name
- Category (Anlegen, etc.)
- Account number
- File type and size

Date format: DD.MM.YYYY (e.g., 17.01.2026)

Default save location: `~/clawd/raiffeisen-elba/documents`

## Security notes

- Credentials (ELBA ID, PIN) are stored in `~/clawd/raiffeisen-elba/.env`.
- Login requires **pushTAN approval** in the Raiffeisen ELBA app.
