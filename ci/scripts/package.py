# -*- coding: utf-8 -*-
import argparse
import hashlib
import zipfile
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--checksum", required=True)
    args = parser.parse_args()

    lib = Path(args.library)
    arch = Path(args.archive)
    arch.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(arch, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(lib, arcname=lib.name)

    sha = hashlib.sha256(arch.read_bytes()).hexdigest()
    Path(args.checksum).write_text(f"{sha}  {arch.name}\n", encoding="utf-8")
    print(f"Packaged {arch.name} ({sha})")

if __name__ == "__main__":
    main()
