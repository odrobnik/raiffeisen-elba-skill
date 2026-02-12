---
name: raiffeisen-elba
description: "Automate Raiffeisen ELBA online banking: login/logout, list accounts, and fetch transactions via Playwright."
summary: "Raiffeisen ELBA banking automation: login, accounts, transactions."
version: 1.2.2
homepage: https://github.com/odrobnik/raiffeisen-elba-skill
metadata:
  openclaw:
    emoji: "🏦"
    requires:
      bins: ["python3"]
      python: ["requests", "playwright"]
      env: ["RAIFFEISEN_ELBA_ID", "RAIFFEISEN_ELBA_PIN"]
---

# Raiffeisen ELBA Banking Automation

Fetch current account balances, securities depot positions, and transactions for all account types in JSON format for automatic processing. Uses Playwright to automate Raiffeisen ELBA online banking.

**Entry point:** `{baseDir}/scripts/elba.py`

## Authentication

Requires **2FA via the Raiffeisen pushTAN app** on your iPhone. When the script initiates login, a confirmation code is displayed. Open the Raiffeisen app and approve the pushTAN request if the code matches.

## Credentials

Set environment variables **or** create `{workspace}/raiffeisen-elba/config.json`:

```json
{
  "elba_id": "YOUR_ELBA_ID",
  "pin": "YOUR_PIN"
}
```

Environment variables (`RAIFFEISEN_ELBA_ID`, `RAIFFEISEN_ELBA_PIN`) take precedence over config.json.

## Commands

```bash
python3 {baseDir}/scripts/elba.py login
python3 {baseDir}/scripts/elba.py logout
python3 {baseDir}/scripts/elba.py accounts
python3 {baseDir}/scripts/elba.py transactions --account <iban> --from YYYY-MM-DD --until YYYY-MM-DD
```

## Notes
- Session state stored in `~/.openclaw/raiffeisen-elba/` with restrictive permissions (dirs 700, files 600).
- Output paths (`--out`) are restricted to the workspace or `/tmp`.
