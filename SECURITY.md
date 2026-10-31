# Security and privacy

provenum is built for unpublished manuscripts, so this page sets out what happens to the files
you give it, which protections the web app (`provenum serve`) has, and what is still missing.

## What happens to your files

| | Command-line tools | Web app (`provenum serve`) |
|---|---|---|
| Where files are processed | Your computer | The computer running `provenum serve` (yours, by default) |
| What is stored | Only the files you name as outputs | A session folder (in the system temp directory, or `--workdir`) holding the uploaded project, the tables, the spec and the output |
| How long | Until you delete them | Until you press *Delete my files now*, or the session has been idle for `--ttl` hours (default 6). Folders left by an earlier run are removed when the server starts. |
| What leaves the computer | Nothing, unless you run `provenum anchor` | Nothing, unless you choose a model |
| When a model is used | Each number's sentence and paragraph, the table catalogue and your notes go to the Ollama server you name (`--host`) | The same, to the server entered on the page. The page warns when that server is not on this computer. |

provenum has no telemetry and no accounts, and it makes no other network requests. It has no
runtime dependencies beyond the Python standard library.

## Web app protections

The app listens on `127.0.0.1` only, unless you pass `--host`. On every request it applies these
protections:

- **Requests from other websites are refused.**
  - The `Host` header must name this server, which defeats DNS rebinding.
  - A request that changes anything must come from the app's own origin.
  - Every request body must be JSON, zip or TOML. A web page can only send these types after a
    CORS preflight, and the server never answers one.
- **Sessions are addressed by 192-bit random tokens.** No route lists sessions.
- **Uploads are checked.**
  - A zip entry is refused if it has an absolute path, `..`, `:` or control characters, or if it
    would land outside the session folder.
  - A zip may hold at most 5000 files and unpack to at most 200 MB.
- **The spec can only read tables inside the tables folder.** An invalid spec never replaces the
  last valid one.
- **The model server must be an `http://` or `https://` address.** `file:` and other schemes are
  refused.
- **Every response carries security headers:** Content-Security-Policy (`default-src 'self'`, so
  no inline scripts run), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  cross-origin isolation headers and `Cache-Control: no-store`.
- **The page escapes all text from the manuscript, the tables and the model** before showing it,
  and so does the downloadable report.
- **The AI step cannot change the manuscript on its own.**
  - The model only chooses among cells whose value already matches the number.
  - A cell is applied only after you accept it, and only if its value reproduces exactly what was
    written.
  - Instructions hidden in a manuscript therefore cannot make provenum write anything else.

Each protection has a test in `tests/test_web.py` (pytest) or `tests/web/` (Vitest).

## Not yet suitable for

- **Hosting for other people.** There is no login.
  - With `--host 0.0.0.0` or behind a proxy (`--allow-host`), anyone who can reach the port can
    upload a project. The server prints a warning when started that way.
  - A shared deployment needs authentication, HTTPS, per-user isolation and upload limits.
- **Untrusted model servers.** Anything you send to a model server is visible to whoever runs it.
  Use your own Ollama, for example on a lab server reached through an SSH tunnel.

## Reviews

- **2026-10-31, branch `feat/webapp`:**
  - The first hardening pass fixed these issues:
    - a cross-site form could start a run that sent the manuscript to any host;
    - session ids were short;
    - spec paths could read CSV files anywhere on the machine;
    - sessions were never deleted;
    - zip entry names with `:` were accepted;
    - an invalid spec could replace the valid one on disk.
  - A separate code review of the hardened branch found no further vulnerabilities at high
    confidence. It looked at path traversal, script injection, cross-site requests, DNS rebinding,
    server-side requests to other hosts and session handling.

## Reporting a problem

Please report security issues privately via GitHub: on the repository page, open *Security* →
*Report a vulnerability*. Please do not open a public issue for them.
