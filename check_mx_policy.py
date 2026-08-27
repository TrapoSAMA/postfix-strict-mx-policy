#!/usr/bin/env python3
# Copyright (C) 2026 Rodrigo Cortés Cano
# SPDX-License-Identifier: GPL-2.0-only

"""Postfix policy service that requires an explicit recipient-domain MX."""

import argparse
import re
import sys

try:
    import syslog
except ImportError:
    syslog = None

try:
    import dns
    import dns.exception
    import dns.resolver
except ImportError as import_error:
    dns = None
    DNS_IMPORT_ERROR = import_error
else:
    DNS_IMPORT_ERROR = None


VERSION = "1.0.0"
REJECT_TEMPLATES = {
    "es": (
        "action=550 5.1.2 El correo no se pudo entregar porque el dominio "
        "destinatario '{domain}' no tiene registros MX validos para recibir "
        "correo. Verifica la direccion del destinatario."
    ),
    "en": (
        "action=550 5.1.2 The message could not be delivered because the "
        "recipient domain '{domain}' has no valid MX records for receiving "
        "mail. Verify the recipient address."
    ),
}
DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class DomainNotFound(Exception):
    pass


class NoMxAnswer(Exception):
    pass


class TemporaryDnsError(Exception):
    pass


def log_error(message):
    safe_message = " ".join(str(message).splitlines())
    if syslog is not None:
        syslog.syslog(syslog.LOG_ERR, "check_mx_policy: " + safe_message)
    else:
        print("check_mx_policy: " + safe_message, file=sys.stderr, flush=True)


def reject_invalid(domain, language="en"):
    return REJECT_TEMPLATES[language].format(domain=domain)


def normalize_domain(domain):
    domain = domain.strip().rstrip(".")
    if not domain or domain.startswith("[") or len(domain) > 253:
        raise ValueError("invalid recipient domain")
    try:
        ascii_domain = domain.encode("idna").decode("ascii").lower()
    except UnicodeError as error:
        raise ValueError("invalid internationalized recipient domain") from error
    labels = ascii_domain.split(".")
    if len(labels) < 2 or any(not DOMAIN_LABEL.match(label) for label in labels):
        raise ValueError("invalid recipient domain")
    return ascii_domain


class DnsPythonMxLookup:
    def __init__(self):
        if DNS_IMPORT_ERROR is not None:
            raise RuntimeError("dnspython is not installed")
        self.resolver = dns.resolver.Resolver()
        self.resolver.timeout = 2.0
        self.resolver.lifetime = 4.0
        if hasattr(dns.resolver, "LRUCache"):
            self.resolver.cache = dns.resolver.LRUCache(max_size=1000)
        elif hasattr(dns.resolver, "Cache"):
            self.resolver.cache = dns.resolver.Cache()

    def _resolve(self, domain, record_type):
        resolve = getattr(self.resolver, "resolve", None)
        if resolve is None:
            resolve = self.resolver.query
        return resolve(domain, record_type)

    def mx_records(self, domain):
        try:
            answers = self._resolve(domain + ".", "MX")
            return [
                (int(answer.preference), str(answer.exchange).rstrip("."))
                for answer in answers
            ]
        except dns.resolver.NXDOMAIN as error:
            raise DomainNotFound() from error
        except dns.resolver.NoAnswer as error:
            raise NoMxAnswer() from error
        except (dns.resolver.NoNameservers, dns.exception.Timeout) as error:
            raise TemporaryDnsError(str(error)) from error
        except dns.exception.DNSException as error:
            raise TemporaryDnsError(str(error)) from error

    def check_resolver(self):
        try:
            return bool(self._resolve(".", "NS"))
        except dns.exception.DNSException as error:
            raise TemporaryDnsError(str(error)) from error


def check_mx(recipient, lookup, language="en"):
    if "@" not in recipient:
        return "action=DUNNO"
    raw_domain = recipient.rsplit("@", 1)[1]
    if not raw_domain.strip():
        return "action=DUNNO"
    try:
        domain = normalize_domain(raw_domain)
    except ValueError:
        return reject_invalid(raw_domain.strip().lower().rstrip("."), language)

    try:
        records = lookup.mx_records(domain)
        if not records or any(exchange == "" for _, exchange in records):
            return reject_invalid(domain, language)
        return "action=DUNNO"
    except (DomainNotFound, NoMxAnswer):
        return reject_invalid(domain, language)
    except TemporaryDnsError as error:
        log_error(f"temporary DNS failure for {domain}: {error}")
        return "action=DUNNO"
    except Exception as error:
        log_error(f"unexpected {type(error).__name__} for {domain}: {error}")
        return "action=DUNNO"


def process_request(attributes, lookup, language="en"):
    state = attributes.get("protocol_state", "")
    if state and state.upper() != "RCPT":
        return "action=DUNNO"
    recipient = attributes.get("recipient", "")
    if not recipient or lookup is None:
        return "action=DUNNO"
    return check_mx(recipient, lookup, language)


def policy_loop(input_stream, output_stream, lookup, language="en"):
    attributes = {}
    for raw_line in input_stream:
        line = raw_line.rstrip("\r\n")
        if line == "":
            if attributes:
                print(
                    process_request(attributes, lookup, language),
                    file=output_stream,
                )
                print(file=output_stream)
                output_stream.flush()
                attributes = {}
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            attributes[key] = value
    if attributes:
        print(process_request(attributes, lookup, language), file=output_stream)
        print(file=output_stream)
        output_stream.flush()


def run_check():
    print("Postfix strict MX policy - system check")
    print()
    version = sys.version_info
    print(f"Python: {version.major}.{version.minor}.{version.micro}")
    if DNS_IMPORT_ERROR is not None:
        print("dnspython: MISSING")
        print("DNS resolver: NOT TESTED")
        print()
        print("Result: FAILED - install the dnspython package")
        return 1
    print(f"dnspython: {getattr(dns, '__version__', 'installed')}")
    lookup = DnsPythonMxLookup()
    try:
        lookup.check_resolver()
    except TemporaryDnsError as error:
        print(f"DNS resolver: FAILED - {error}")
        print()
        print("Result: FAILED")
        return 1
    print("DNS resolver: OK")
    print()
    print("Result: OK")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Postfix policy service requiring an explicit recipient MX"
    )
    parser.add_argument(
        "--check", action="store_true", help="check dependencies and DNS"
    )
    parser.add_argument(
        "--language",
        choices=sorted(REJECT_TEMPLATES),
        default="en",
        help="language for permanent rejection messages (default: en)",
    )
    parser.add_argument("--version", action="store_true", help="print the version")
    arguments = parser.parse_args(argv)
    if arguments.version:
        print(VERSION)
        return 0
    if arguments.check:
        return run_check()

    lookup = None
    if DNS_IMPORT_ERROR is None:
        try:
            lookup = DnsPythonMxLookup()
        except Exception as error:
            log_error(f"could not initialize DNS resolver: {error}")
    else:
        log_error("dnspython is not installed; all requests will return DUNNO")
    policy_loop(sys.stdin, sys.stdout, lookup, arguments.language)
    return 0


if __name__ == "__main__":
    sys.exit(main())
