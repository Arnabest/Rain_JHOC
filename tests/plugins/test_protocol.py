import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from jhoc.contracts import PluginManifest  # noqa: E402
from jhoc.plugins import HealthStatus, PluginHost, PluginLifecycle  # noqa: E402
from jhoc.plugins.protocol import PluginProtocolError  # noqa: E402


class FakePlugin:
    def __init__(self, *, fail_invoke: bool = False):
        self.fail_invoke = fail_invoke
        self.cancelled = []
        self.drained = False
        self.closed = False

    def describe(self):
        return {"plugin_id": "test.echo", "protocol_version": "1.0", "capabilities": ["echo"]}

    def health(self):
        return {"status": HealthStatus.READY.value}

    def initialize(self, config):
        self.config = dict(config)

    def validate(self, request):
        if "value" not in request:
            raise ValueError("value is required")

    def invoke(self, request):
        if self.fail_invoke:
            raise RuntimeError("injected invoke failure")
        return {"echo": request["value"]}

    def stream(self, request):
        yield {"echo": request["value"]}
        yield {"done": True}

    def cancel(self, work_id):
        self.cancelled.append(work_id)

    def checkpoint(self):
        return {"checkpoint": 1}

    def drain(self):
        self.drained = True

    def shutdown(self):
        self.closed = True


def make_host(plugin=None):
    manifest = PluginManifest(
        "test.echo", "Test Echo", "1.0.0", "1.0", "capability", verification_status="VERIFIED"
    )
    return PluginHost(manifest, plugin or FakePlugin())


class PluginProtocolTests(unittest.TestCase):
    def test_full_lifecycle_and_stream(self):
        host = make_host()
        host.verify()
        host.install()
        host.load()
        description = host.handshake()
        self.assertEqual(description.lifecycle, PluginLifecycle.NEGOTIATED)
        host.initialize({"mode": "test"})
        self.assertEqual(host.invoke({"value": 3}), {"echo": 3})
        self.assertEqual(list(host.stream({"value": 4})), [{"echo": 4}, {"done": True}])
        host.drain()
        host.shutdown()
        self.assertEqual(host.state, PluginLifecycle.STOPPED)

    def test_invalid_lifecycle_operation_is_rejected(self):
        host = make_host()
        with self.assertRaises(PluginProtocolError):
            host.invoke({"value": 1})

    def test_protocol_mismatch_is_fail_closed(self):
        host = make_host()
        host.protocol_version = "2.0"
        with self.assertRaises(PluginProtocolError):
            host.verify()
        self.assertEqual(host.state, PluginLifecycle.FAILED)

    def test_injected_invoke_failure_enters_failed(self):
        host = make_host(FakePlugin(fail_invoke=True))
        host.verify()
        host.install()
        host.load()
        host.handshake()
        host.initialize()
        with self.assertRaises(RuntimeError):
            host.invoke({"value": 1})
        self.assertEqual(host.state, PluginLifecycle.FAILED)
        self.assertIn("injected invoke failure", host.last_error)

    def test_health_before_start_is_unavailable(self):
        host = make_host()
        self.assertEqual(host.health()["status"], HealthStatus.UNAVAILABLE.value)

    def test_abandoned_stream_returns_host_to_ready(self):
        host = make_host()
        host.verify()
        host.install()
        host.load()
        host.handshake()
        host.initialize()
        stream = host.stream({"value": 5})
        self.assertEqual(next(iter(stream)), {"echo": 5})
        stream.close()
        self.assertEqual(host.state, PluginLifecycle.READY)

    def test_repeated_load_invoke_drain_shutdown_cycles_release_plugins(self):
        plugins = []
        for index in range(250):
            plugin = FakePlugin(fail_invoke=index % 10 == 0)
            plugins.append(plugin)
            host = make_host(plugin)
            host.verify()
            host.install()
            host.load()
            host.handshake()
            host.initialize()
            if plugin.fail_invoke:
                with self.assertRaises(RuntimeError):
                    host.invoke({"value": index})
            else:
                self.assertEqual(host.invoke({"value": index}), {"echo": index})
                host.drain()
            host.shutdown()
            self.assertEqual(host.state, PluginLifecycle.STOPPED)
        self.assertTrue(all(plugin.closed for plugin in plugins))


if __name__ == "__main__":
    unittest.main()
