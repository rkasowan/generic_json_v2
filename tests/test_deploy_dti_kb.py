#!/usr/bin/env python3
"""Offline KB publisher target guards: no credentials, network or live writes."""

import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SPEC = importlib.util.spec_from_file_location("dti_kb_publisher_under_test", SCRIPTS / "deploy_dti_kb.py")
publisher = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(SCRIPTS))
try:
    SPEC.loader.exec_module(publisher)
finally:
    sys.path.pop(0)

EXPECTED = "https://expected.service-now.com"
OTHER = "https://other.service-now.com"


class OriginTests(unittest.TestCase):
    def test_valid_origins_and_trailing_slash_normalization(self):
        for source, expected in (
            (EXPECTED, EXPECTED),
            (EXPECTED + "/", EXPECTED),
            ("https://EXPECTED.service-now.com/", EXPECTED),
            ("https://expected.service-now.com:8443/", EXPECTED + ":8443"),
            ("https://[::1]/", "https://[::1]"),
        ):
            with self.subTest(source=source):
                self.assertEqual(publisher.instance_origin(source), expected)

    def test_non_origins_are_rejected_without_echoing_the_input(self):
        invalid = (
            "", "expected.service-now.com", "http://expected.service-now.com", "https://",
            EXPECTED + "/kb_view.do", EXPECTED + "//", EXPECTED + "?q=x", EXPECTED + "?",
            EXPECTED + "#anchor", EXPECTED + "#", "https://user@expected.service-now.com",
            "https://user:password@expected.service-now.com", "https://@expected.service-now.com",
            " " + EXPECTED, EXPECTED + " ", "https://expected.\nservice-now.com",
            "https://expected.service-now.com\\path", "https://expected.service-now.com:wrong",
            "https://expected.service-now.com:99999", "https://expected.service-now.com:",
            "https://[::1", "https://[::1]suffix", EXPECTED + "\x7f",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError) as raised:
                    publisher.instance_origin(value)
                self.assertEqual(str(raised.exception),
                                 "expected an HTTPS instance origin without userinfo, path, query or fragment")


class TargetGuardTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(base=EXPECTED)
        self.admin = Mock(instance=EXPECTED)

    def assert_no_requests(self):
        self.client.query.assert_not_called()
        self.client.request.assert_not_called()
        self.admin.run_background_script.assert_not_called()

    def assert_blocked(self):
        with patch.object(publisher, "Client", return_value=self.client), \
                patch.object(publisher, "ServiceNow", return_value=self.admin):
            with self.assertRaises(RuntimeError):
                publisher.main(["--expected-instance", EXPECTED])
        self.assert_no_requests()

    def test_missing_expected_instance_fails_before_connection_construction(self):
        with patch.object(publisher, "Client") as client_constructor, \
                patch.object(publisher, "ServiceNow") as admin_constructor, \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                publisher.main([])
        self.assertEqual(raised.exception.code, 2)
        client_constructor.assert_not_called()
        admin_constructor.assert_not_called()

    def test_invalid_expected_instance_fails_before_connection_construction(self):
        with patch.object(publisher, "Client") as client_constructor, \
                patch.object(publisher, "ServiceNow") as admin_constructor, \
                redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                publisher.main(["--expected-instance", EXPECTED + "/kb_view.do"])
        self.assertEqual(raised.exception.code, 2)
        client_constructor.assert_not_called()
        admin_constructor.assert_not_called()

    def test_agreed_but_wrong_connections_are_blocked_before_first_query(self):
        self.client.base = OTHER
        self.admin.instance = OTHER
        self.assert_blocked()

    def test_wrong_background_target_is_blocked_before_first_query(self):
        self.admin.instance = OTHER
        self.assert_blocked()

    def test_wrong_table_target_is_blocked_before_first_query(self):
        self.client.base = OTHER
        self.assert_blocked()

    def test_invalid_table_target_is_blocked_before_first_query(self):
        self.client.base = EXPECTED + "/unexpected"
        self.assert_blocked()

    def test_invalid_background_target_is_blocked_before_first_query(self):
        self.admin.instance = "http://expected.service-now.com"
        self.assert_blocked()

    def test_matching_targets_publish_and_read_back_with_normalized_slashes(self):
        self.client.base = EXPECTED + "/"
        self.admin.instance = EXPECTED
        source = Mock()
        source.read_text.return_value = "# Focused target test"
        body = publisher.markdown_to_html(source.read_text.return_value)
        article = {"sys_id": "a" * 32, "number": "KBTEST0001", "short_description": publisher.TITLE,
                   "workflow_state": "published", "active": "true", "latest": "true",
                   "display_attachments": "true", "text": body}
        self.client.query.side_effect = [
            [{"sys_id": "b" * 32, "title": "IT"}], [{"sys_id": article["sys_id"]}], [article],
        ]
        output = io.StringIO()
        with patch.object(publisher, "Client", return_value=self.client), \
                patch.object(publisher, "ServiceNow", return_value=self.admin), \
                patch.object(publisher, "SOURCE", source), redirect_stdout(output):
            publisher.main(["--expected-instance", EXPECTED + "/"])
        self.assertEqual(self.client.query.call_count, 3)
        self.client.request.assert_not_called()
        self.admin.run_background_script.assert_called_once()
        script, scope = self.admin.run_background_script.call_args.args
        self.assertEqual(scope, "global")
        self.assertIn(article["sys_id"], script)
        self.assertIn("k.setValue('display_attachments','true')", script)
        self.assertIn("display_attachments", self.client.query.call_args.args[2].split(","))
        self.assertEqual(json.loads(output.getvalue())["number"], "KBTEST0001")
        self.assertNotIn("text", json.loads(output.getvalue()))

    def test_new_article_payload_makes_attachments_visible(self):
        source = Mock()
        source.read_text.return_value = "# New KB target test"
        article = {"sys_id": "a" * 32, "number": "KBTEST0002", "short_description": publisher.TITLE,
                   "workflow_state": "published", "active": True, "latest": True,
                   "display_attachments": True,
                   "text": publisher.markdown_to_html(source.read_text.return_value)}
        self.client.query.side_effect = [
            [{"sys_id": "b" * 32, "title": "IT"}], [], [], [article],
        ]
        self.client.request.return_value = {"sys_id": article["sys_id"]}
        with patch.object(publisher, "Client", return_value=self.client), \
                patch.object(publisher, "ServiceNow", return_value=self.admin), \
                patch.object(publisher, "SOURCE", source), redirect_stdout(io.StringIO()):
            publisher.main(["--expected-instance", EXPECTED])
        self.client.request.assert_called_once()
        method, path, payload = self.client.request.call_args.args
        self.assertEqual((method, path), ("POST", "/api/now/table/kb_knowledge"))
        self.assertIs(payload["display_attachments"], True)
        self.admin.run_background_script.assert_called_once()
        self.assertEqual(self.client.query.call_count, 4)

    def test_hidden_or_missing_attachment_visibility_fails_readback(self):
        for visibility in (False, "false", None):
            with self.subTest(visibility=visibility):
                client = Mock(base=EXPECTED)
                admin = Mock(instance=EXPECTED)
                source = Mock()
                source.read_text.return_value = "# Visibility test"
                article = {"sys_id": "a" * 32, "number": "KBTEST0003", "short_description": publisher.TITLE,
                           "workflow_state": "published", "active": "true", "latest": "true",
                           "text": publisher.markdown_to_html(source.read_text.return_value)}
                if visibility is not None:
                    article["display_attachments"] = visibility
                client.query.side_effect = [
                    [{"sys_id": "b" * 32, "title": "IT"}], [{"sys_id": article["sys_id"]}], [article],
                ]
                with patch.object(publisher, "Client", return_value=client), \
                        patch.object(publisher, "ServiceNow", return_value=admin), \
                        patch.object(publisher, "SOURCE", source):
                    with self.assertRaisesRegex(RuntimeError, "visible-attachments state"):
                        publisher.main(["--expected-instance", EXPECTED])
                client.request.assert_not_called()
                admin.run_background_script.assert_called_once()
                self.assertEqual(client.query.call_count, 3)


if __name__ == "__main__":
    unittest.main()
