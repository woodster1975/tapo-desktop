"""Fetch a pinned, checksum-verified essentials build for Windows packaging."""
import hashlib,json,shutil,urllib.request,zipfile
from pathlib import Path

root=Path(__file__).resolve().parents[1]
url='https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-9.0.2-essentials_build.zip'
expected='60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba'
archive=root/'.setup-temp/ffmpeg-9.0.2-essentials.zip'
destination=root/'tools/ffmpeg-installer'
archive.parent.mkdir(parents=True,exist_ok=True)
if not archive.exists():
    with urllib.request.urlopen(url,timeout=60) as response,archive.open('wb') as output:shutil.copyfileobj(response,output)
with archive.open('rb') as source:actual=hashlib.file_digest(source,'sha256').hexdigest()
if actual!=expected:raise SystemExit('FFmpeg checksum mismatch. Do not use this download.')
destination.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(archive) as files:
    for name in files.namelist():
        basename=Path(name).name
        if basename.lower() not in ('ffmpeg.exe','ffprobe.exe','license','license.txt','readme.txt'):continue
        target=destination/('LICENSE.txt' if basename.lower()=='license' else basename)
        with files.open(name) as source,target.open('wb') as output:shutil.copyfileobj(source,output)
(destination/'DOWNLOAD.json').write_text(json.dumps({'version':'9.0.2','url':url,'sha256':actual},indent=2))
print('Verified FFmpeg 9.0.2 essentials for the installer.')
