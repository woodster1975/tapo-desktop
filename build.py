"""Build on the target OS. No cross compilation or credential/data bundling."""
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parent
if sys.platform=='win32':
    import runpy
    runpy.run_path(str(root/'packaging/build_windows.py'),run_name='__main__')
    raise SystemExit(0)
# Console bootloader preserves JSON pipes for the camera worker on Windows.
# The GUI detaches its console; the worker retains its inherited pipes.
scratch=tempfile.TemporaryDirectory(prefix='tapo-desk-build-')
args=[sys.executable,'-m','PyInstaller','--noconfirm','--onedir',
      '--workpath',str(Path(scratch.name)/'work'),'--specpath',scratch.name,
      '--name','TapoDesk','--add-data',str(root/'assets')+':assets',
      '--collect-submodules','keyring.backends','--collect-submodules','pytapo','--collect-submodules','av',
      '--copy-metadata','keyring','--copy-metadata','pytapo',
      '--exclude-module','PySide6.QtWebEngineCore','--exclude-module','PySide6.QtWebEngineWidgets',
      '--exclude-module','PySide6.Qt3DCore',str(root/'run.py')]
subprocess.run(args,cwd=root,check=True)
scratch.cleanup()
print('Built '+str(root/'dist/TapoDesk'))
