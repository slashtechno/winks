a = Analysis(
    ["entry.py"],
    pathex=["src"],
    datas=[("assets/icon.png", "assets")],
    hiddenimports=[],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="winks",
    console=True,
    icon="assets/icon.png",
)
