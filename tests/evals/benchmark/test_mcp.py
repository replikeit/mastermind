"""Request bounds through a real initialized stdio MCP connection."""

from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

from evals.benchmark.artifacts import BenchmarkError
from evals.benchmark.mcp import McpClient


SERVER = r'''
import json, sys
initialized = False
calls = 0
for line in sys.stdin:
    request = json.loads(line)
    if request['method'] == 'notifications/initialized':
        initialized = True
        continue
    if request['method'] == 'initialize':
        result = {'protocolVersion': '2025-11-25', 'capabilities': {'tools': {}},
                  'serverInfo': {'name': 'request-bound-fixture', 'version': '1'}}
    else:
        assert initialized and request['method'] == 'tools/call'
        calls += 1
        result = {'arguments': request['params']['arguments'], 'calls': calls}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], 'result': result}), flush=True)
'''


@unittest.skipUnless(os.name == "posix", "requires POSIX stdio selectors")
class McpClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        self.command = [sys.executable, "-I", "-S", "-B", "-c", SERVER]

    def client(self, **kwargs):
        return McpClient(self.command, cwd=self.cwd, env={}, **kwargs)

    def test_default_request_cap_rejects_large_payload_before_server_receives_it(self):
        with self.client() as client:
            with self.assertRaises(BenchmarkError) as caught:
                client.call("echo", {"text": "x" * (16 * 1024)})
            self.assertEqual(caught.exception.code, "mcp_request_limit")
            self.assertEqual(client.call("echo", {"text": "small"}),
                             {"arguments": {"text": "small"}, "calls": 1})

    def test_opt_in_roundtrips_large_utf8_payload_and_enforces_configured_byte_cap(self):
        arguments = {"text": "я" * (16 * 1024)}
        with self.client(request_limit=64 * 1024) as client:
            self.assertEqual(client.call("echo", arguments), {"arguments": arguments, "calls": 1})
            with self.assertRaises(BenchmarkError) as caught:
                client.call("echo", {"text": "я" * (32 * 1024)})
            self.assertEqual(caught.exception.code, "mcp_request_limit")
            self.assertEqual(client.call("echo", {}), {"arguments": {}, "calls": 2})

    def test_invalid_request_limits_do_not_start_a_child(self):
        for limit in (True, False, 0, -1, 4 * 1024 * 1024 + 1, 1.5, "65536", None):
            with self.subTest(limit=limit), patch("evals.benchmark.mcp.subprocess.Popen") as spawn:
                with self.assertRaises(BenchmarkError) as caught:
                    self.client(request_limit=limit)
                self.assertEqual(caught.exception.code, "invalid_limits")
                spawn.assert_not_called()

    def test_maximum_limit_accepts_initialization_and_reply_is_a_defensive_copy(self):
        with self.client(request_limit=4 * 1024 * 1024) as client:
            expected = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                        "serverInfo": {"name": "request-bound-fixture", "version": "1"}}
            self.assertEqual(client.initialize_result, expected)
            reply = client.initialize_result
            reply["serverInfo"]["name"] = "changed"
            self.assertEqual(client.initialize_result, expected)
            with self.assertRaises(AttributeError):
                client.initialize_result = {}
            self.assertEqual(client.call("echo", {}), {"arguments": {}, "calls": 1})


if __name__ == "__main__":
    unittest.main()
