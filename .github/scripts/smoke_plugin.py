import argparse
import base64
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib


class Buffer(ctypes.Structure):
    _fields_ = [("ptr", ctypes.c_void_p), ("len", ctypes.c_size_t)]


Call = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(Buffer))
Free = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_size_t)
Shutdown = ctypes.CFUNCTYPE(None)


class Plugin(ctypes.Structure):
    _fields_ = [("abi_version", ctypes.c_uint32), ("call", Call), ("free_buffer", Free), ("shutdown", Shutdown)]


def probe(library, expected_version):
    loaded = ctypes.CDLL(str(library))
    interface = Plugin()
    entry = loaded.cliproxy_plugin_init
    entry.argtypes = [ctypes.c_void_p, ctypes.POINTER(Plugin)]
    entry.restype = ctypes.c_int
    assert entry(None, ctypes.byref(interface)) == 0

    def rpc(method, payload):
        raw = json.dumps(payload).encode()
        request = ctypes.create_string_buffer(raw)
        response = Buffer()
        status = interface.call(method.encode(), request, len(raw), ctypes.byref(response))
        try:
            value = json.loads(ctypes.string_at(response.ptr, response.len))
        finally:
            interface.free_buffer(response.ptr, response.len)
        assert status == 0, value
        return value["result"]

    def request(path, method="GET", query=None):
        result = rpc("management.handle", {"Path": path, "Method": method, "Query": query or {}})
        return result["StatusCode"], base64.b64decode(result["Body"])

    try:
        registration = rpc("plugin.register", {})
        assert registration["metadata"]["Version"] == expected_version
        routes = rpc("management.register", {})
        assert {item["Path"] for item in routes["Resources"]} == {"/manage", "/extension.zip"}
        for path in ["bootstrap", "tmp", "api/status"]:
            status, _ = request("/v0/resource/plugins/gflow/" + path)
            assert status == 404
        status, html = request("/v0/resource/plugins/gflow/manage")
        assert status == 200 and b"cli-proxy-auth" in html
        status, response = request("/v0/management/plugins/gflow/api/status")
        assert status == 200, response.decode("utf-8", errors="replace")
        status_data = json.loads(response)
        assert status_data["initialized"] is True and status_data["total_tokens"] == 0
        data_directory = library.parent / "gflow-data"
        assert Path(status_data["database_path"]).resolve() == (data_directory / "flow.db").resolve()
        runtime = Path(status_data["python"]).resolve()
        assert data_directory.resolve() in runtime.parents and runtime.is_file()
        status, response = request("/v0/management/plugins/gflow/api/models")
        assert status == 200 and len(json.loads(response)["models"]) == 7
        status, response = request("/v0/management/plugins/gflow/api/media", query={"file": ["../flow.db"]})
        assert status == 404
        status, _ = request("/v0/management/plugins/gflow/api/status", method="POST")
        assert status == 405
        runtime_before = runtime.stat().st_mtime_ns
        interface.shutdown()
        status, _ = request("/v0/management/plugins/gflow/api/status")
        assert status == 200 and runtime.stat().st_mtime_ns == runtime_before
        print(json.dumps({"clean_install": "passed", "runtime": str(runtime), "models": 7}), flush=True)
    finally:
        interface.shutdown()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--expected-version")
    options = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    expected_version = options.expected_version or tomllib.loads((root / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]
    if options.probe:
        probe(options.library.resolve(), expected_version)
        return
    staging = root / ".build" / ("clean plugin install " + str(time.time_ns()))
    plugins = staging / "plugins" / "native"
    plugins.mkdir(parents=True)
    staged_library = plugins / options.library.name
    shutil.copy2(options.library, staged_library)
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "GFLOW_WORKER_BINARY", "GFLOW_DATA_DIR"):
        environment.pop(name, None)
    environment["PATH"] = str(staging / "no-system-python")
    subprocess.run(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--probe", "--library", str(staged_library), "--expected-version", expected_version],
        cwd=staging, env=environment, check=True, timeout=180,
    )


if __name__ == "__main__":
    main()
