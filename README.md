# Raiffeisen ELBA Skill

Unified web automation for ELBA: login, logout, accounts, transactions.

## Usage
```bash
python3 scripts/elba.py login
python3 scripts/elba.py logout
python3 scripts/elba.py accounts
python3 scripts/elba.py transactions --account <iban> --from YYYY-MM-DD --until YYYY-MM-DD
```

## Notes
- Playwright is required; login requires pushTAN approval.
- Session state stored in `~/.moltbot/raiffeisen-elba/`.
- See `SKILL.md` for agent usage guidance.
