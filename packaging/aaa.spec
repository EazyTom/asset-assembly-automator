# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ["asset_assembly_automator/gui/main.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("config/default.yaml", "config"),
        ("config/prompt_templates", "config/prompt_templates"),
        ("asset_assembly_automator/core/db/schema.sql", "asset_assembly_automator/core/db"),
        ("asset_assembly_automator/gui/theme/dark.qss", "asset_assembly_automator/gui/theme"),
        ("asset_assembly_automator/gui/resources", "asset_assembly_automator/gui/resources"),
    ],
    hiddenimports=[
        "asset_assembly_automator.stages.s01_prompt_build",
        "asset_assembly_automator.stages.s02_concept_generate",
        "asset_assembly_automator.stages.s03_concept_review",
        "asset_assembly_automator.stages.s04_image_prep",
        "asset_assembly_automator.stages.s04b_turnaround",
        "asset_assembly_automator.stages.s05_meshy_image_to_3d",
        "asset_assembly_automator.stages.s06_meshy_remesh",
        "asset_assembly_automator.stages.s07_meshy_rig",
        "asset_assembly_automator.stages.s08_meshy_animate",
        "asset_assembly_automator.stages.s09_meshy_download",
        "asset_assembly_automator.stages.s09b_qc_validate",
        "asset_assembly_automator.stages.s10_package_export",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AssetAssemblyAutomator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="AssetAssemblyAutomator",
)
