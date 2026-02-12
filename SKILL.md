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

Unified UX for ELBA: **login**, **logout**, **accounts**, **transactions**.

**Entry point:** `{baseDir}/scripts/elba.py`

## Credentials

Set environment variables **or** create `workspace/raiffeisen-elba/config.json`:

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
- Uses Playwright (pushTAN approval during login).
- Session state stored in `~/.openclaw/raiffeisen-elba/` with restrictive permissions (dirs 700, files 600).
- Output paths (`--out`) are restricted to the workspace or `/tmp`.
