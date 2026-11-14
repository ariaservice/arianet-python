# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub: **Security tab → "Report a
vulnerability"** on https://github.com/ariaservice/arianet-python, rather than opening a public issue.
Include the SDK version and steps to reproduce.

Problems with the API service itself (not this client) can be reported the same way or through
https://ariaservice.net.

## Supported versions

Only the latest release receives fixes.

## What the client does to protect your token

- It sends the token only as an `Authorization: Bearer` header, only to the configured base URL,
  which must use `https` (plain `http` is accepted for `localhost` only).
- It never follows redirects, so the token cannot be forwarded to another host.
- Third-party GitHub Actions in this repository are pinned to commit SHAs.
