# Windows packaging

Use 64-bit Python 3.12 and Inno Setup 6 or 7 on Windows. From the source folder,
run `build-windows.ps1`. It uses the existing `.windows-runtime` environment,
installs build-only dependencies, converts the icon, verifies the pinned FFmpeg
download, builds the application and compiles the installer.

The installer is `dist/installers/TapoDesk-<version>-Setup-x64.exe`; its SHA-256
file is beside it. The current portable folder is recorded in
`dist/windows/latest-build.json`. Each build uses a fresh versioned directory
to avoid changing files being synced or used by another build. The analysis
cache stays in local app storage for quicker subsequent builds.

The app uses a one-folder PyInstaller bundle inside a conventional Inno Setup
installer. Python, Qt, PyAV, FFmpeg and ffprobe are included. It does not unpack
a new Python runtime every time the app or a camera worker starts. The main
executable uses the native Windows GUI subsystem, preventing a console window
from being allocated at startup. A separate worker executable under `_internal`
shares the runtime and retains private input/output pipes. Workers and their
FFmpeg subprocesses are launched without console windows.
Only assets, application imports, the media tools and third-party notices are
included. Camera settings, stored passwords, caches and test footage are not.

Installation is per-user under Local AppData/Programs/Tapo Desk. Start menu
access is standard; a desktop shortcut is optional. A stable AppId supports
upgrades. The application mutex requires closing the app before install or
uninstall, allowing any live recording to finish first. Uninstall has no rules
to delete settings, Credential Manager entries or saved footage.

Icon master: `assets/tapo-desk.png`. Windows icon: `assets/tapo-desk.ico`, with
16, 20, 24, 32, 40, 48, 64, 128 and 256-pixel images. The same icon is applied to
the app, executable, installer and shortcuts. It is an original independent
camera mark, not TP-Link branding.

Local packaging validation uses a separate AppId and temporary installation,
never an existing normal installation. Machine-specific checks and reports are
excluded from Git. Offline regression tests are the root-level `test_*.py` files.

This personal build is unsigned. A trusted publisher release needs an
Authenticode certificate/signing service; a checksum is not a digital
signature. Included software retains its own licenses. Before redistribution,
fulfil the source/notices/replacement rights of the bundled GPL/LGPL components.
