"""Native IPC regression fixture, never imports the real service."""
import json
import sys
print(json.dumps({"ready": True}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("cmd") == "shutdown":
        break
    if request["params"].get("stream"):
        if request["params"].get("force_eof"):
            break
        print(json.dumps({"id": request["id"], "done": True, "error": {
            "message": "synthetic upstream rejection", "status_code": 503}}), flush=True)
    else:
        # A transport loss must not cause native code to submit generation twice.
        break
