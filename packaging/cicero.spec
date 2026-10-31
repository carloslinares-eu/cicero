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
    excludes=[
        "pytest",
        # PyMuPDF 2 imports its optional layout analyzer (pymupdf.layout, ~49 MB of ONNX models) whenever it
        # is installed. Cicero never uses it, and bundled without its data it makes `import pymupdf` fail with
        # FileNotFoundError. Left out, the import fails cleanly and PyMuPDF works as before.
        "pymupdf.layout",
        "onnxruntime",
    ],
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
