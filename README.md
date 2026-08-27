# Postfix strict MX policy

[![Tests](https://github.com/TrapoSAMA/postfix-strict-mx-policy/actions/workflows/tests.yml/badge.svg)](https://github.com/TrapoSAMA/postfix-strict-mx-policy/actions/workflows/tests.yml)

`check_mx_policy.py` is an optional Postfix policy service. It rejects a remote
recipient domain when the domain does not publish an explicit MX record.

This is intentionally stricter than standard SMTP delivery. SMTP normally
allows a domain with an A or AAAA record and no MX to receive mail through an
implicit MX. This policy rejects that case by design.

## Requirements

- Python 3.8 or newer
- `dnspython` (installed automatically by the packaged distribution)

## Installation

### Packaged release

Download the wheel for the selected release and install it with `pip`. For
version 1.0.0:

```bash
python3 -m pip install \
  https://github.com/TrapoSAMA/postfix-strict-mx-policy/releases/download/v1.0.0/postfix_strict_mx_policy-1.0.0-py3-none-any.whl
check-mx-policy --check
```

The package installs the `check-mx-policy` command and selects a compatible
`dnspython` release for the running Python version.

### Standalone script

When dependencies are managed by the operating system, the original script
can still be installed directly:

```bash
install -o root -g root -m 755 check_mx_policy.py /usr/local/bin/check_mx_policy.py
/usr/local/bin/check_mx_policy.py --check
```

The check reports the Python and dnspython versions and verifies that the
configured DNS resolver can answer a root NS query.

The examples below use the standalone path. A packaged installation may use
the absolute path reported by `command -v check-mx-policy` instead.

## Postfix example

`/etc/postfix/master.cf`:

```text
mxpolicy  unix  -       n       n       -       10      spawn
        user=nobody argv=/usr/local/bin/check_mx_policy.py
```

English is the default rejection language, so the service definition above
needs no language option. To use the Spanish message, add the option to the
same service; no second script is required:

```text
mxpolicy  unix  -       n       n       -       10      spawn
        user=nobody argv=/usr/local/bin/check_mx_policy.py --language=es
```

The English permanent rejection is:

```text
550 5.1.2 The message could not be delivered because the recipient domain
'example.org' has no valid MX records for receiving mail. Verify the recipient
address.
```

The process limit is an administrator decision. Postfix documentation commonly
uses `0` for policy services so their capacity follows the SMTP service. A
fixed value such as `10` is appropriate only when it is intentionally sized for
the installation.

The production installation that motivated this service uses the following
restriction order (shown here with normal spaces and underscores):

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

The order has two deliberate effects:

- Normal SMTP clients in `mynetworks` or authenticated through SASL are
  permitted before `mxpolicy`; other accepted relay destinations reach it
  after `reject_unauth_destination`.
- Submission checks `mxpolicy` before permitting authenticated clients, so an
  authenticated sender cannot submit a recipient domain without explicit MX.

The original local value also contained `reject_unknown_domain`. It is neither
a built-in Postfix restriction nor a local restriction class in this
installation, so the corrected example removes it. The valid built-in name is
`reject_unknown_recipient_domain`, which remains later in the list.

`submission_recipient_restrictions` is commonly a local variable referenced by
a submission service override such as
`-o smtpd_recipient_restrictions=$submission_recipient_restrictions`; verify
that relationship in `master.cf`.

Merge these examples with the installation's existing restrictions; do not
replace them blindly. Then validate and reload Postfix:

```bash
postfix check
postfix reload
```

## Decisions

- Valid explicit MX: `DUNNO` so Postfix continues with the next restriction.
- NXDOMAIN, no MX answer, malformed domain, or Null MX: `550 5.1.2`.
- DNS timeout, unavailable nameserver, SERVFAIL, missing dependency, or an
  internal error: `DUNNO` to avoid blocking legitimate mail.
- Temporary and unexpected DNS failures are logged without writing diagnostic
  text to the policy protocol on standard output.
- Internationalized domains are converted to their ASCII IDNA representation.
- A bounded resolver cache reduces repeated DNS queries within each process.

## Difference from `reject_unknown_recipient_domain`

Postfix already provides
[`reject_unknown_recipient_domain`](https://www.postfix.org/postconf.5.html#reject_unknown_recipient_domain).
That restriction rejects a non-local recipient domain when it has neither an
MX record nor an A record, or when its MX is malformed.
It therefore permits standard SMTP implicit-MX delivery to an address record.
Postfix also handles Null MX natively in current versions and applies its own
temporary-failure behavior without an external policy service.

This project is deliberately stricter: it requires at least one explicit,
non-Null MX record and rejects a domain that has only A or AAAA records. It
also returns `DUNNO` for temporary DNS or internal failures so Postfix can
continue evaluating later restrictions.

Use the built-in restriction when the goal is simply to reject unknown
recipient domains. Use this service only when the installation intentionally
requires every checked recipient domain to publish an explicit MX record.

## Tests

The tests use a fake resolver and do not depend on public DNS:

```bash
python3 -m unittest discover -s tests -v
```

## License

Version 1.0.0 is distributed under the GNU General Public License version 2.0
only (`GPL-2.0-only`). Copying, modification, and redistribution are permitted
under those terms and come without warranty. See `LICENSE`, `NOTICE`, and
`THIRD_PARTY_NOTICES.md` for the complete licensing information.
