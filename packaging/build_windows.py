"""Build a self-contained Windows app and optional Inno Setup installer."""
import argparse,contextlib,hashlib,json,os,re,shutil,subprocess,sys,tempfile,uuid
from importlib import metadata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tapo_desktop import __version__


def find_ffmpeg():
    candidates=[ROOT/'tools/ffmpeg-installer',Path(sys.executable).resolve().parent.parent/'tools/ffmpeg',ROOT/'tools/ffmpeg']
    for folder in candidates:
        if all((folder/name).is_file() for name in ('ffmpeg.exe','ffprobe.exe')):return folder
    raise SystemExit('Run packaging/fetch_ffmpeg.py first.')


def find_compiler(explicit=None):
    candidates=[explicit,shutil.which('ISCC.exe')]
    for base in ('ProgramFiles(x86)','ProgramFiles','LOCALAPPDATA'):
        value=os.environ.get(base)
        if value:candidates.extend(str(Path(value)/name/'ISCC.exe') for name in
            ('Inno Setup 7','Inno Setup 6','Programs/Inno Setup 7','Programs/Inno Setup 6'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():return str(candidate)
    raise SystemExit('Install Inno Setup from https://jrsoftware.org/isdl.php or pass --iscc PATH.')


def collect_notices(bundle,ffmpeg):
    folder=bundle/'licenses';folder.mkdir(exist_ok=True)
    shutil.copyfile(ROOT/'THIRD_PARTY.md',folder/'THIRD_PARTY.md')
    shutil.copyfile(ROOT/'assets/LATO-LICENSE.txt',folder/'LATO-LICENSE.txt')
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file():shutil.copyfile(python_license,folder/'Python-LICENSE.txt')
    for distribution in metadata.distributions():
        name=re.sub(r'[^a-zA-Z0-9_.-]','_',distribution.metadata['Name'])
        for relative in distribution.files or []:
            leaf=relative.name.lower()
            if not (leaf.startswith(('license','copying','notice','copyright')) or 'licenses' in relative.parts):continue
            source=Path(distribution.locate_file(relative))
            if not source.is_file() or source.suffix.lower() in ('.py','.pyc','.pyd','.dll') or source.stat().st_size>2_000_000:continue
            target=folder/name;target.mkdir(exist_ok=True)
            destination=target/relative.name
            if destination.exists() and destination.read_bytes()!=source.read_bytes():
                destination=target/(hashlib.sha256(str(relative).encode()).hexdigest()[:8]+'-'+relative.name)
            shutil.copyfile(source,destination)
    target=folder/'FFmpeg';target.mkdir(exist_ok=True)
    for name in ('LICENSE.txt','README.txt','DOWNLOAD.json'):
        if (ffmpeg/name).is_file():shutil.copyfile(ffmpeg/name,target/name)
    configuration=subprocess.run([str(ffmpeg/'ffmpeg.exe'),'-buildconf'],capture_output=True,text=True,check=True)
    (target/'BUILD-CONFIGURATION.txt').write_text(configuration.stdout+configuration.stderr,encoding='utf8')
    (target/'SOURCE.txt').write_text('Windows build: https://www.gyan.dev/ffmpeg/builds/\n'
        'Pinned 9.0.2 source revision: https://github.com/FFmpeg/FFmpeg/tree/946fcce07b\n'
        'Official source releases: https://ffmpeg.org/releases/\n'
        'Retain GPLv3 notices and supply corresponding source when redistributing these binaries.\n',encoding='utf8')


def version_resource(path):
    version=tuple(int(part) for part in __version__.split('.'))+(0,)
    path.write_text("VSVersionInfo(ffi=FixedFileInfo(filevers="+repr(version)+",prodvers="+repr(version)+
        ",mask=0x3f,flags=0,OS=0x40004,fileType=0x1,subtype=0,date=(0,0)),kids=["+
        "StringFileInfo([StringTable('040904B0',[StringStruct('CompanyName','Tapo Desk'),"+
        "StringStruct('FileDescription','Tapo Desk camera viewer'),StringStruct('FileVersion','"+__version__+"'),"+
        "StringStruct('ProductName','Tapo Desk'),StringStruct('ProductVersion','"+__version__+"'),"+
        "StringStruct('OriginalFilename','TapoDesk.exe')])]),VarFileInfo([VarStruct('Translation',[1033,1200])])])",encoding='utf8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installer',action='store_true')
    parser.add_argument('--iscc',help='Path to the Inno Setup compiler')
    options=parser.parse_args()
    if sys.platform!='win32':raise SystemExit('Build the Windows package on Windows.')
    compiler=find_compiler(options.iscc) if options.installer else None
    ffmpeg=find_ffmpeg()
    output=(ROOT/'dist/windows'/__version__).resolve()
    if output.exists():output=output.with_name(__version__+'-'+uuid.uuid4().hex[:8])
    if not output.is_relative_to((ROOT/'dist').resolve()):raise SystemExit('Build output must stay under dist.')
    work_parent=Path(os.environ.get('LOCALAPPDATA',tempfile.gettempdir()))/'TapoDesk/build-temp'
    work_parent.mkdir(parents=True,exist_ok=True)
    scratch=work_parent/('windows-'+__version__)
    scratch.mkdir(parents=True,exist_ok=True)
    # Persistent analysis cache makes subsequent packaging changes much faster.
    # A fresh output directory avoids cloud-sync locks on earlier build files.
    with contextlib.nullcontext(scratch):
        icon=ROOT/'assets/tapo-desk.ico'
        if not icon.is_file():raise SystemExit('Run packaging/make_icon.py first.')
        resource=scratch/'version.txt';version_resource(resource)
        environment=os.environ.copy()
        environment.update(TAPO_BUILD_ROOT=str(ROOT),TAPO_BUILD_SCRATCH=str(scratch),TAPO_BUILD_FFMPEG=str(ffmpeg))
        args=[sys.executable,'-m','PyInstaller','--noconfirm','--workpath',str(scratch/'work'),
            '--distpath',str(output),str(ROOT/'packaging/windows.spec')]
        subprocess.run(args,cwd=ROOT,env=environment,check=True)
    bundle=output/'TapoDesk'
    # Qt on supported Windows versions uses the OS ICU API (unversioned
    # exports). A different ICU from a build-tool search path can shadow it.
    # These are generated files only; never redistribute/override Windows ICU.
    internal=(bundle/'_internal').resolve()
    if not internal.is_relative_to(output):raise SystemExit('Unsafe bundle layout.')
    # The worker uses contents_directory='.' and shares the GUI runtime here.
    shutil.move(str(bundle/'TapoDeskWorker.exe'),str(internal/'TapoDeskWorker.exe'))
    for candidate in [internal/'icuuc.dll',*internal.glob('icudt*.dll')]:
        candidate.unlink(missing_ok=True)
    collect_notices(bundle,ffmpeg)
    shutil.copy2(ROOT/'packaging/INSTALL-NOTES.txt',bundle/'READ-ME.txt')
    receipt={'version':__version__,'platform':sys.platform,'python':sys.version.split()[0],
             'files':sum(1 for p in bundle.rglob('*') if p.is_file()),
             'bytes':sum(p.stat().st_size for p in bundle.rglob('*') if p.is_file())}
    (output/'build-receipt.json').write_text(json.dumps(receipt,indent=2))
    (ROOT/'dist/windows/latest-build.json').write_text(json.dumps({'bundle':str(bundle.relative_to(ROOT)),**receipt},indent=2))
    print('Built '+str(bundle),flush=True)
    if options.installer:
        subprocess.run([compiler,'/DAppVersion='+__version__,'/DBundleDir='+str(bundle),
            '/DOutputPath='+str(ROOT/'dist/installers'),str(ROOT/'packaging/TapoDesk.iss')],check=True,cwd=ROOT)
        installer=ROOT/'dist/installers'/('TapoDesk-'+__version__+'-Setup-x64.exe')
        with installer.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
        installer.with_suffix('.exe.sha256').write_text(digest+'  '+installer.name+'\n')
        print('Installer: '+str(installer),flush=True)


if __name__=='__main__':main()
