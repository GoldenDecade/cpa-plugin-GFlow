from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules


root = Path(SPECPATH).resolve().parents[1]
sys.path[:0] = [str(root / "python"), str(root / "python" / "flow2api")]
datas = [
    (str(root / "python/flow2api/config/setting_example.toml"), "config"),
    (str(root / "python/flow2api/LICENSE"), "licenses/flow2api"),
]
binaries = []
hiddenimports = [path.stem for path in (root / "python").glob("*.py") if path.name != "worker.py"]
hiddenimports += collect_submodules("src", filter=lambda name: name != "src.main")
for package in ("curl_cffi", "nodriver", "playwright", "aiosqlite", "bcrypt", "psutil"):
    package_data, package_binaries, package_imports = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_imports

analysis = Analysis(
    [str(root / "python/worker.py")],
    pathex=[str(root / "python"), str(root / "python/flow2api")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "pytest"],
    noarchive=False,
)
archive = PYZ(analysis.pure)
executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="gflow-worker",
    console=True,
    debug=False,
    strip=False,
    upx=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
