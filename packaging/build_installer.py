"""Compile the installer for the latest completed Windows bundle."""
import hashlib,json,runpy,shutil,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
tools=runpy.run_path(str(root/'packaging/build_windows.py'))
latest=json.loads((root/'dist/windows/latest-build.json').read_text())
bundle=(root/latest['bundle']).resolve()
if not bundle.is_relative_to((root/'dist/windows').resolve()):raise SystemExit('Invalid bundle path.')
tools['collect_notices'](bundle,tools['find_ffmpeg']())
shutil.copyfile(root/'packaging/INSTALL-NOTES.txt',bundle/'READ-ME.txt')
version=latest['version']
subprocess.run([tools['find_compiler'](),'/DAppVersion='+version,'/DBundleDir='+str(bundle),
    '/DOutputPath='+str(root/'dist/installers'),str(root/'packaging/TapoDesk.iss')],cwd=root,check=True)
installer=root/'dist/installers'/('TapoDesk-'+version+'-Setup-x64.exe')
with installer.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
installer.with_suffix('.exe.sha256').write_text(digest+'  '+installer.name+'\n')
receipt={'version':version,'installer':installer.name,'installer_bytes':installer.stat().st_size,
    'sha256':digest,'bundle':latest['bundle'],'bundle_bytes':sum(p.stat().st_size for p in bundle.rglob('*') if p.is_file())}
for name in ('windows-package-check','windows-installer-check'):
    path=root/'checks'/(name+'.json')
    if path.exists():receipt[name]=json.loads(path.read_text())
(installer.parent/'release.json').write_text(json.dumps(receipt,indent=2))
print('Installer ready: '+str(installer),flush=True)
