# Postfix strict MX policy

[![Tests](https://github.com/TrapoSAMA/postfix-strict-mx-policy/actions/workflows/tests.yml/badge.svg)](https://github.com/TrapoSAMA/postfix-strict-mx-policy/actions/workflows/tests.yml)

`check_mx_policy.py` is an optional Postfix policy service that requires every
checked recipient domain to publish an explicit, non-Null MX record.

Its main purpose is to prevent messages with a mistyped recipient domain from
being accepted into an MTA queue and failing only hours or days later. This is
a common operational problem with Postfix and other MTAs: the sender may not
discover a simple domain-entry mistake until normal delivery retries are
exhausted.

For example, if a sender enters `user@gmial.com` instead of `user@gmail.com`
and the mistyped domain does not exist or has no explicit MX, the service
returns `550 5.1.2` during `RCPT TO`. Postfix does not accept or queue the
message, and the submitting client receives the error immediately.

This service is not a spelling checker and does not validate the local part or
mailbox. A mistyped, lookalike, or parked domain that publishes a valid MX
record passes the policy because DNS cannot reveal what the sender intended.

## Policy scope and standards trade-off

This is intentionally stricter than standard SMTP delivery. RFC 5321 defines
an implicit MX fallback when a domain has no MX record but has a usable address
record. Consequently, an A/AAAA-only mail destination can be standards
compliant even though this service rejects it.

Use this policy only when the installation deliberately requires explicit MX
records and accepts that compatibility trade-off. If the goal is general,
standards-compatible recipient-domain validation, use Postfix's built-in
[`reject_unknown_recipient_domain`](https://www.postfix.org/postconf.5.html#reject_unknown_recipient_domain)
instead.

The service distinguishes permanent DNS results from temporary lookup
failures:

| DNS or processing result | Policy response | Effect |
| --- | --- | --- |
| At least one explicit, non-Null MX | `DUNNO` | Postfix continues with the next restriction. |
| NXDOMAIN | `550 5.1.2` | The client receives an immediate permanent rejection. |
| No MX answer, including an A/AAAA-only domain | `550 5.1.2` | The local explicit-MX requirement is enforced. |
| Null MX or malformed domain | `550 5.1.2` | The recipient domain is rejected. |
| Timeout, SERVFAIL, unavailable nameserver, or other temporary DNS error | `DUNNO` | The service fails open and Postfix continues. |
| Missing dependency or internal error | `DUNNO` | The service fails open and Postfix continues. |

The permanent `550` response is intentional: it prevents local queuing and
immediately returns control to the submitting client. Temporary DNS failures
never produce that permanent rejection; they return `DUNNO`, allowing Postfix
and later restrictions to decide the outcome.

## Requirements

- Python 3.8 or newer
- `dnspython` (installed automatically by the packaged distribution)

## Installation

### Packaged release

Download the wheel for the selected release and install it with `pip`. For
version 1.0.1:

```bash
python3 -m pip install \
  https://github.com/TrapoSAMA/postfix-strict-mx-policy/releases/download/v1.0.1/postfix_strict_mx_policy-1.0.1-py3-none-any.whl
check-mx-policy --check
```

The package installs the `check-mx-policy` command and selects a compatible
`dnspython` release for the running Python version.

### Standalone script

When dependencies are managed by the operating system, the script can be
installed directly:

```bash
install -o root -g root -m 755 check_mx_policy.py /usr/local/bin/check_mx_policy.py
/usr/local/bin/check_mx_policy.py --check
```

The check reports the Python and dnspython versions and verifies that the
configured DNS resolver can answer a root NS query.

The examples below use the standalone path. A packaged installation may use
the absolute path reported by `command -v check-mx-policy` instead.

## Postfix configuration

Add the service to `/etc/postfix/master.cf`:

```text
mxpolicy  unix  -       n       n       -       10      spawn
        user=nobody argv=/usr/local/bin/check_mx_policy.py
```

English is the default rejection language. To use the Spanish response, add
the language option to the same service; no second script is required:

```text
mxpolicy  unix  -       n       n       -       10      spawn
        user=nobody argv=/usr/local/bin/check_mx_policy.py --language=es
```

The process limit is an administrator decision. Postfix documentation commonly
uses `0` for policy services so their capacity follows the SMTP service. A
fixed value such as `10` is appropriate only when intentionally sized for the
installation.

The production installation that motivated this service uses the following
restriction order (shown with normal spaces and underscores):

```text
smtpd_recipient_restrictions = permit_mynetworks,
        permit_sasl_authenticated,
        reject_unauth_destination,
        check_policy_service unix:private/mxpolicy,
        reject_non_fqdn_recipient,
        reject_unknown_recipient_domain,
        check_policy_service unix:/var/spool/postfix/private/dovecot-quota

submission_recipient_restrictions = check_policy_service unix:private/mxpolicy,
        permit_sasl_authenticated,
        reject
```

This order has two deliberate effects:

- Normal SMTP clients in `mynetworks` or authenticated through SASL are
  permitted before `mxpolicy`; other accepted relay destinations reach it
  only after `reject_unauth_destination`.
- Submission checks `mxpolicy` before permitting authenticated clients, so an
  authenticated sender cannot submit a recipient domain without explicit MX.

The example deliberately contains no `reject_unknown_domain`: that is not a
built-in Postfix restriction. The valid built-in name is
`reject_unknown_recipient_domain`.

`submission_recipient_restrictions` is commonly a local variable referenced by
a submission service override such as
`-o smtpd_recipient_restrictions=$submission_recipient_restrictions`; verify
that relationship in `master.cf`.

Merge these examples with the installation's existing restrictions; do not
replace them blindly. In particular, keep `reject_unauth_destination` before
the policy service on public SMTP paths so this addition cannot weaken relay
controls. Then validate and reload Postfix:

```bash
postfix check
postfix reload
```

## Comparison with native Postfix validation

Postfix's `reject_unknown_recipient_domain` rejects a non-local recipient
domain when it has neither an MX nor an A record, or when its MX is malformed.
It therefore permits RFC-compatible implicit-MX delivery to an address record.
Postfix also handles Null MX natively in current versions and applies its own
configured action for temporary lookup failures.

| Recipient-domain DNS result | `reject_unknown_recipient_domain` | This service |
| --- | --- | --- |
| Valid explicit MX | Continues | `DUNNO` |
| No MX, but an A/AAAA record exists | Continues using implicit MX | `550 5.1.2` |
| NXDOMAIN, with no MX or A/AAAA | Uses Postfix's configured unknown-address response (450 by default) | `550 5.1.2` |
| Temporary DNS failure | Uses Postfix's configured temporary-failure action | `DUNNO` |

Choose the built-in restriction for standards-compatible validation. Choose
this service when immediate feedback and an explicit-MX-only policy are more
important than accepting uncommon A/AAAA-only mail destinations. Both may be
used in the same restriction chain when their different behavior is intended.

## Additional behavior

- Temporary and unexpected DNS failures are logged without writing diagnostic
  text to the policy protocol on standard output.
- Internationalized domains are converted to their ASCII IDNA representation.
- A bounded resolver cache reduces repeated DNS queries within each process.
- The service evaluates the recipient domain only; final delivery and mailbox
  validation remain Postfix's responsibility.

## Tests

The tests use a fake resolver and do not depend on public DNS:

```bash
python3 -m unittest discover -s tests -v
```

## References

- [RFC 5321, section 5.1](https://www.rfc-editor.org/rfc/rfc5321#section-5.1)
  defines explicit MX lookup, implicit MX fallback, permanent nonexistent-domain
  errors, and retry behavior for temporary lookup failures.
- [Issue #1](https://github.com/TrapoSAMA/postfix-strict-mx-policy/issues/1)
  records the design discussion that clarified the standards trade-off and the
  operational purpose of the policy.

## License

Version 1.0.1 is distributed under the GNU General Public License version 2.0
only (`GPL-2.0-only`). Copying, modification, and redistribution are permitted
under those terms and come without warranty. See `LICENSE`, `NOTICE`, and
`THIRD_PARTY_NOTICES.md` for the complete licensing information.
