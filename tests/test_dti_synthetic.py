import importlib.util
from pathlib import Path
import unittest
from unittest import mock


PATH = Path(__file__).parents[1] / "synthetic" / "generic_json_v2_dti_synthetic.py"
SPEC = importlib.util.spec_from_file_location("dti_synthetic", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class ResponseParsingTests(unittest.TestCase):
    def test_base64_environment_decoding(self):
        with mock.patch.dict("os.environ", {"TEST_USER_B64": "c3ludGhldGljLnVzZXI="}, clear=False):
            self.assertEqual(MODULE.decoded_env("TEST_USER_B64", "TEST_USER"), "synthetic.user")

    def test_top_level_result(self):
        self.assertEqual(MODULE.first_result({"result": {"event_sys_id": "a"}})["event_sys_id"], "a")

    def test_results_array(self):
        body = {"result": {"results": [{"incident_sys_id": "b"}]}}
        self.assertEqual(MODULE.first_result(body)["incident_sys_id"], "b")

    def test_empty_results_array(self):
        self.assertEqual(MODULE.first_result({"result": {"results": []}}), {})

    def test_named_connector_string_result(self):
        body = {"result": {"USBEM genericJsonV2": '{"results":[{"event_sys_id":"c"}]}'}}
        self.assertEqual(MODULE.first_result(body)["event_sys_id"], "c")


if __name__ == "__main__":
    unittest.main()
