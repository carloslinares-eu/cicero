# PyInstaller recipe for a single-file, windowed Cicero executable.
#
#   pip install -r requirements-dev.txt
#   pyinstaller packaging/cicero.spec
#
# The result is dist/Cicero.exe on Windows (dist/Cicero elsewhere).

from pathlib import Path

ROOT = Path(SPECPATH).parent
ASSETS = ROOT / "cicero" / "assets"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    datas=[(str(ASSETS), "cicero/assets")],
    hookspath=[str(Path(SPECPATH) / "hooks")],
    excludes=["pytest"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Cicero",
    icon=str(ASSETS / "cicero.ico"),
    console=False,
    upx=False,
)
