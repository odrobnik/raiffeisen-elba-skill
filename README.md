# Raiffeisen ELBA Skill

Unified web automation for ELBA: login, logout, accounts, transactions.

## Install

```bash
clawhub install raiffeisen-elba --registry "https://auth.clawdhub.com"
```

## Usage

```bash
python3 scripts/elba.py login
python3 scripts/elba.py logout
python3 scripts/elba.py accounts
python3 scripts/elba.py transactions --account <iban> --from YYYY-MM-DD --until YYYY-MM-DD
```

## Configuration

Set environment variables:
```bash
export RAIFFEISEN_ELBA_ID="ELVIE33V..."
export RAIFFEISEN_ELBA_PIN="12345"
```

Or create `workspace/raiffeisen-elba/config.json`:
```json
{
  "elba_id": "ELVIE33V...",
  "pin": "12345"
}
```

## Notes
- Playwright is required; login requires pushTAN approval.
- Session state stored in `~/.openclaw/raiffeisen-elba/` with restrictive permissions.
- Output paths (`--out`) are restricted to the workspace or `/tmp`.
- See `SKILL.md` for agent usage guidance.

## Documentation

- [SKILL.md](SKILL.md) — agent-facing reference (commands, behavior, limitations)
- [SETUP.md](SETUP.md) — prerequisites, configuration, and setup instructions
- [ClawHub](https://www.clawhub.com/skills/raiffeisen-elba) — install via ClawHub registry
