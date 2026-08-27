#!/usr/bin/env python3
# Copyright (C) 2026 Rodrigo Cortés Cano
# SPDX-License-Identifier: GPL-2.0-only

import importlib.util
import io
import pathlib
import unittest
from unittest import mock

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "check_mx_policy.py"
SPEC = importlib.util.spec_from_file_location("check_mx_policy", str(SCRIPT))
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


class FakeLookup:
    def __init__(self, records=None, error=None):
        self.records = records if records is not None else [(10, "mx.example.org")]
        self.error = error
        self.domains = []

    def mx_records(self, domain):
        self.domains.append(domain)
        if self.error is not None:
            raise self.error
        return self.records


class MxPolicyTest(unittest.TestCase):
    def test_valid_mx_is_allowed(self):
        lookup = FakeLookup()
        self.assertEqual("action=DUNNO", POLICY.check_mx("user@example.org", lookup))
        self.assertEqual(["example.org"], lookup.domains)

    def test_missing_domain_is_ignored(self):
        self.assertEqual("action=DUNNO", POLICY.check_mx("invalid", FakeLookup()))
        self.assertEqual("action=DUNNO", POLICY.check_mx("user@", FakeLookup()))

    def test_missing_mx_is_rejected(self):
        for error in (POLICY.DomainNotFound(), POLICY.NoMxAnswer()):
            result = POLICY.check_mx("user@example.org", FakeLookup(error=error))
            self.assertTrue(result.startswith("action=550 5.1.2"))

    def test_null_mx_is_rejected(self):
        result = POLICY.check_mx("user@example.org", FakeLookup(records=[(0, "")]))
        self.assertTrue(result.startswith("action=550 5.1.2"))

    def test_english_rejection_message(self):
        result = POLICY.check_mx(
            "user@example.org", FakeLookup(error=POLICY.NoMxAnswer())
        )
        self.assertEqual(
            "action=550 5.1.2 The message could not be delivered because the "
            "recipient domain 'example.org' has no valid MX records for receiving "
            "mail. Verify the recipient address.",
            result,
        )

    def test_spanish_rejection_message(self):
        result = POLICY.check_mx(
            "user@example.org", FakeLookup(error=POLICY.NoMxAnswer()), "es"
        )
        self.assertIn("El correo no se pudo entregar", result)

    def test_temporary_and_unexpected_errors_fail_open(self):
        with mock.patch.object(POLICY, "log_error") as logger:
            temporary = POLICY.check_mx(
                "user@example.org",
                FakeLookup(error=POLICY.TemporaryDnsError("timeout")),
            )
            unexpected = POLICY.check_mx(
                "user@example.org", FakeLookup(error=RuntimeError("unexpected"))
            )
        self.assertEqual("action=DUNNO", temporary)
        self.assertEqual("action=DUNNO", unexpected)
        self.assertEqual(2, logger.call_count)

    def test_idna_and_invalid_domains(self):
        lookup = FakeLookup()
        self.assertEqual("action=DUNNO", POLICY.check_mx("user@münich.example", lookup))
        self.assertEqual(["xn--mnich-kva.example"], lookup.domains)
        result = POLICY.check_mx("user@invalid_domain.example", FakeLookup())
        self.assertTrue(result.startswith("action=550 5.1.2"))

    def test_non_rcpt_request_is_ignored(self):
        result = POLICY.process_request(
            {"protocol_state": "DATA", "recipient": "user@example.org"}, FakeLookup()
        )
        self.assertEqual("action=DUNNO", result)

    def test_policy_loop_handles_reuse_and_pending_eof_request(self):
        source = io.StringIO(
            "protocol_state=RCPT\nrecipient=user@example.org\n\n"
            "protocol_state=RCPT\nrecipient=other@example.org\n"
        )
        output = io.StringIO()
        lookup = FakeLookup()
        POLICY.policy_loop(source, output, lookup)
        self.assertEqual("action=DUNNO\n\naction=DUNNO\n\n", output.getvalue())
        self.assertEqual(["example.org", "example.org"], lookup.domains)

    def test_policy_loop_uses_selected_language(self):
        source = io.StringIO(
            "protocol_state=RCPT\nrecipient=user@example.org\n\n"
        )
        output = io.StringIO()
        POLICY.policy_loop(source, output, FakeLookup(error=POLICY.NoMxAnswer()))
        self.assertIn("The message could not be delivered", output.getvalue())

    def test_missing_dependency_fails_open_per_request(self):
        source = io.StringIO("protocol_state=RCPT\nrecipient=user@example.org\n\n")
        output = io.StringIO()
        POLICY.policy_loop(source, output, None)
        self.assertEqual("action=DUNNO\n\n", output.getvalue())

    @unittest.skipIf(POLICY.DNS_IMPORT_ERROR is not None, "dnspython is not installed")
    def test_dnspython_backend_has_bounded_runtime_and_cache(self):
        lookup = POLICY.DnsPythonMxLookup()
        self.assertEqual(2.0, lookup.resolver.timeout)
        self.assertEqual(4.0, lookup.resolver.lifetime)
        self.assertIsNotNone(lookup.resolver.cache)


if __name__ == "__main__":
    unittest.main()
