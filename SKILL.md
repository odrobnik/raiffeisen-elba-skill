---
name: raiffeisen-elba
description: "Automate Raiffeisen ELBA online banking: login/logout, list accounts, and fetch transactions via Playwright."
summary: "Raiffeisen ELBA banking automation: login, accounts, transactions."
version: 1.1.0
homepage: https://github.com/clawdbot-skills/raiffeisen-elba
metadata: {"moltbot": {"emoji": "🏦", "requires": {"bins": ["python3", "playwright"]}}}
---

# Raiffeisen ELBA Banking Automation

Unified UX for ELBA: **login**, **logout**, **accounts**, **transactions**.

**Entry point:** `{baseDir}/scripts/elba.py`

## Commands

```bash
python3 {baseDir}/scripts/elba.py login
python3 {baseDir}/scripts/elba.py logout
python3 {baseDir}/scripts/elba.py accounts
python3 {baseDir}/scripts/elba.py transactions --account <iban> --from YYYY-MM-DD --until YYYY-MM-DD
```

## Notes
- Uses Playwright (pushTAN approval during login).
- Session state stored in `~/.moltbot/raiffeisen-elba/`.
