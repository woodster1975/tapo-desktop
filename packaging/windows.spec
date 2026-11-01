# Shared runtime and analysis; separate native GUI and piped worker bootloaders.
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

root=Path(os.environ['TAPO_BUILD_ROOT'])
scratch=Path(os.environ['TAPO_BUILD_SCRATCH'])
ffmpeg=Path(os.environ['TAPO_BUILD_FFMPEG'])
datas=[(str(root/'assets'),'assets')]
datas += [(str(ffmpeg/name),'tools/ffmpeg') for name in ('ffmpeg.exe','ffprobe.exe')]
for package in ('keyring','pytapo','av'):datas += copy_metadata(package)
a=Analysis([str(root/'run.py')],pathex=[str(root)],binaries=[],datas=datas,
    hiddenimports=collect_submodules('keyring.backends')+collect_submodules('pytapo'),
    hookspath=[],hooksconfig={},runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore','PySide6.QtWebEngineWidgets','PySide6.Qt3DCore','PIL'],
    noarchive=False,optimize=0)
pyz=PYZ(a.pure)
gui=EXE(pyz,a.scripts,[],exclude_binaries=True,name='TapoDesk',
    debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=False,
    icon=str(root/'assets/tapo-desk.ico'),version=str(scratch/'version.txt'),contents_directory='_internal')
worker=EXE(pyz,a.scripts,[],exclude_binaries=True,name='TapoDeskWorker',
    debug=False,bootloader_ignore_signals=False,strip=False,upx=False,console=True,
    hide_console='hide-early',icon=str(root/'assets/tapo-desk.ico'),
    version=str(scratch/'version.txt'),contents_directory='.')
coll=COLLECT(gui,worker,a.binaries,a.datas,strip=False,upx=False,name='TapoDesk')
