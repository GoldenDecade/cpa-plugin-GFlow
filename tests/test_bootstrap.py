"""验证页面握手的权限边界，仅使用虚构密钥，不连接 Google。"""
import base64
import ctypes as c
import json
import io
from pathlib import Path
import unittest
import zipfile
import psutil

ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / "target" / "release" / "gflow.dll"
if not DLL.exists():
    DLL = Path("D:/LUO/proxyAPI/EasyCLIProxyAPI-v0.2.96-Windows-amd64/cpa-core/plugins/windows/amd64/gflow-v0.1.0.dll")


class Buffer(c.Structure):
    _fields_ = [("ptr", c.c_void_p), ("len", c.c_size_t)]


Call = c.CFUNCTYPE(c.c_int, c.c_char_p, c.c_void_p, c.c_size_t, c.POINTER(Buffer))
Free = c.CFUNCTYPE(None, c.c_void_p, c.c_size_t)
Shutdown = c.CFUNCTYPE(None)


class Plugin(c.Structure):
    _fields_ = [("abi_version", c.c_uint32), ("call", Call), ("free_buffer", Free), ("shutdown", Shutdown)]


class BootstrapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = c.CDLL(str(DLL))
        cls.api = Plugin()
        init = cls.library.cliproxy_plugin_init
        init.argtypes = [c.c_void_p, c.POINTER(Plugin)]
        init.restype = c.c_int
        if init(None, c.byref(cls.api)):
            raise RuntimeError("Plugin init failed")
        cls.rpc("plugin.register", {"config_yaml": base64.b64encode(("enabled: true" + chr(10) + "management_key: synthetic-management-key" + chr(10)).encode()).decode()})
        result = cls.rpc("management.register", {})["result"]
        cls.menu = next(r["Path"] for r in result["Resources"] if r.get("Menu") == "GFlow")
        cls.nonce = cls.menu.split("#gflow_session=", 1)[1]

    @classmethod
    def tearDownClass(cls):
        descendants = psutil.Process().children(recursive=True)
        cls.api.shutdown()
        _, alive = psutil.wait_procs(descendants, timeout=3)
        for process in alive:
            try:
                process.terminate()
            except psutil.NoSuchProcess:
                pass
        psutil.wait_procs(alive, timeout=3)

    @classmethod
    def rpc(cls, method, payload):
        raw = json.dumps(payload).encode()
        data = c.create_string_buffer(raw)
        output = Buffer()
        rc = cls.api.call(method.encode(), c.cast(data, c.c_void_p), len(raw), c.byref(output))
        try:
            result = json.loads(c.string_at(output.ptr, output.len))
        finally:
            cls.api.free_buffer(output.ptr, output.len)
        if rc:
            raise RuntimeError(result.get("error", {}).get("message", "plugin call failed"))
        return result

    def resource(self, path, headers=None):
        result = self.rpc("management.handle", {
            "Method": "GET", "Path": "/v0/resource/plugins/gflow/" + path,
            "Headers": {k: [v] for k, v in (headers or {}).items()}
        })["result"]
        result["decoded"] = base64.b64decode(result["Body"])
        return result

    def test_public_html_contains_no_credentials(self):
        result = self.resource("manage")
        self.assertEqual(result["StatusCode"], 200)
        self.assertNotIn(b"synthetic-management-key", result["decoded"])
        self.assertNotIn(self.nonce.encode(), result["decoded"])
        self.assertNotIn(b'id="mgmtKey"', result["decoded"])

    def test_menu_contains_ticket_not_management_key(self):
        self.assertGreaterEqual(len(self.nonce), 40)
        self.assertNotIn("synthetic-management-key", self.menu)

    def test_extension_download_contains_independent_gflow_manifest(self):
        result = self.resource("extension.zip")
        self.assertEqual(result["StatusCode"], 200)
        with zipfile.ZipFile(io.BytesIO(result["decoded"])) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(manifest["name"], "GFlow 登录助手")
            self.assertIn("background.js", archive.namelist())
            self.assertNotIn(b"synthetic-management-key", archive.read("popup.js"))

    def test_missing_and_invalid_ticket_are_rejected(self):
        for headers in [{}, {"X-GFlow-Session": "incorrect"}]:
            result = self.resource("bootstrap", headers)
            self.assertEqual(result["StatusCode"], 401)
            self.assertNotIn(b"synthetic-management-key", result["decoded"])

    def test_valid_ticket_returns_private_session(self):
        result = self.resource("bootstrap", {"X-GFlow-Session": self.nonce, "Sec-Fetch-Site": "same-origin"})
        self.assertEqual(result["StatusCode"], 200)
        self.assertEqual(json.loads(result["decoded"])["management_key"], "synthetic-management-key")
        self.assertIn("no-store", result["Headers"]["cache-control"][0])
        cookie = result["Headers"]["set-cookie"][0]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_cross_site_request_rejected_even_with_valid_ticket(self):
        result = self.resource("bootstrap", {"X-GFlow-Session": self.nonce, "Sec-Fetch-Site": "cross-site"})
        self.assertEqual(result["StatusCode"], 403)

    def test_cookie_refresh_and_missing_config(self):
        result = self.resource("bootstrap", {"Cookie": "gflow_ui_session=" + self.nonce})
        self.assertEqual(result["StatusCode"], 200)
        self.rpc("plugin.reconfigure", {"config_yaml": "enabled: true"})
        try:
            result = self.resource("bootstrap", {"X-GFlow-Session": self.nonce})
            self.assertEqual(result["StatusCode"], 503)
            self.assertIn("插件", json.loads(result["decoded"])["error"]["message"])
        finally:
            self.rpc("plugin.reconfigure", {"config_yaml": "management_key: synthetic-management-key"})


if __name__ == "__main__":
    unittest.main()
