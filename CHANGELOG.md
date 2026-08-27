# Changelog

All notable changes to this project are documented in this file.

## Unreleased

- Add concrete outcome examples comparing the service with Postfix's native
  `reject_unknown_recipient_domain` restriction.

## 1.0.0 - 2026-08-26

- Add the reusable Postfix policy protocol service.
- Require explicit recipient-domain MX records while failing open on temporary
  DNS and internal errors.
- Add Null MX, IDNA, resolver cache, English and Spanish message support.
- Add dependency and DNS diagnostics through `--check`.
- Add focused tests for Python 3.8 and 3.13.
- Add wheel and source distribution metadata.
- Document the intentional difference from Postfix's built-in
  `reject_unknown_recipient_domain` restriction.
- Clarify that rejection occurs immediately during `RCPT TO`, before the
  message is accepted or queued, and document the limits of typo detection.
