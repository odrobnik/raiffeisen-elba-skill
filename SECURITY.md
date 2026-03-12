# Security Policy

## Core Architecture Risks and Mitigations

The **raiffeisen-elba** skill is designed to automate banking operations for Raiffeisen ELBA (Austria). By its very nature, it handles highly sensitive data, including authentication credentials, session tokens, and financial records.

### 1. Browser Automation (Playwright) & Token Extraction
The skill heavily relies on Playwright to emulate a real user logging into the Single Page Application (SPA). Additionally, it uses JavaScript evaluation (`page.evaluate`) to extract Bearer tokens directly from the browser's `localStorage` and `sessionStorage`, and intercepts network requests to capture authentication headers.

**Why is this necessary?**
Raiffeisen ELBA does not offer a public, consumer-facing OAuth/API for automated personal finance. The only way to retrieve structured data automatically is to piggyback on the internal APIs used by the ELBA web dashboard. To do this, the skill must acquire the short-lived Bearer token generated during a valid browser login session (which requires interactive pushTAN 2FA approval).

**Mitigations in Place:**
- **Strict File Permissions:** The Playwright profile directory (`.pw-profile`) and the token cache (`token.json`) are locked down to `0700` and `0600` permissions respectively. Only the executing user can read them.
- **Strict umask:** A default umask of `0077` is applied at runtime to ensure all newly created files in the state directory are completely private from the moment they are written.
- **Ephemeral State (Recommended Flow):** Users are strongly encouraged to always run `elba.py logout` at the end of their automation sequence. The `logout` command securely deletes the entire `.pw-profile` directory and any cached tokens, ensuring no valid session state remains on disk while the script is not running.
- **No Workspace Credential Files:** The skill explicitly refuses to load credentials from legacy workspace `.env` files to prevent accidental commits or exposure. Credentials must be provided via environment variables (`RAIFFEISEN_ELBA_ID`, `RAIFFEISEN_ELBA_PIN`) or a dedicated `config.json` with strict `0600` permissions.

### 2. Output Path Sanitization
The skill uses robust path sanitization (`_safe_output_path`) to prevent path traversal attacks. Exported data can only be written to the designated workspace directory (`~/clawd/`) or a temporary directory (`/tmp/`).

### Vulnerability Reporting
If you discover a security issue that goes beyond these known and accepted architectural limitations, please open an issue in the skill's repository.
