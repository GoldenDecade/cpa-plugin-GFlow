# -*- coding: utf-8 -*-
"""
GFlow Environment Bootstrapper:
Checks for required Python dependencies (curl_cffi, aiosqlite, pydantic, etc.)
If dependencies are missing, can automatically install them or clone/link a virtualenv.
"""

import os
import sys
import subprocess
import json
from pathlib import Path

REQUIRED_MODULES = [
    "curl_cffi",
    "aiosqlite",
    "pydantic",
    "fastapi",
    "uvicorn",
    "httpx",
    "tomli",
    "bcrypt",
]

def check_environment():
    missing = []
    for mod in REQUIRED_MODULES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    
    return {
        "ok": len(missing) == 0,
        "python": sys.executable,
        "version": sys.version.split()[0],
        "missing": missing,
    }

def install_dependencies(python_exe: str, req_file: Path):
    cmd = [python_exe, "-m", "pip", "install", "-r", str(req_file)]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {
        "returncode": res.returncode,
        "stdout": res.stdout,
        "stderr": res.stderr,
    }

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        print(json.dumps(check_environment(), ensure_ascii=False))
    else:
        status = check_environment()
        print(json.dumps(status, ensure_ascii=False, indent=2))
