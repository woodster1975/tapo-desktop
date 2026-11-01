# Third-party components

- PySide6/Qt: LGPLv3/GPL/commercial options. This source app uses dynamically linked PySide6 wheels. Keep required notices, license texts and replacement/relinking rights when distributing a frozen bundle. See https://doc.qt.io/qtforpython-6/licenses.html.
- PyTapo: upstream LICENSE applies; see https://github.com/JurajNyiri/pytapo/blob/3.4.30/LICENSE.
- Lato Regular/Bold: SIL Open Font License 1.1. Bundled font copyright/license in assets/LATO-LICENSE.txt. Unmodified fonts; Lato is a reserved font name.
- keyring and its dependencies: consult installed package metadata/licenses.
- PyAV 19.0.2: BSD-3-Clause Python bindings. Its wheels bundle FFmpeg libraries with their own LGPL/GPL notices; retain the installed PyAV/FFmpeg license files when distributing a standalone app. Used for stream-copy live recording, with G.711 audio expanded to PCM when required by Matroska.
- FFmpeg: source setup uses external executables. The Windows installer bundles Gyan's GPLv3 essentials build 9.0.2, with its license, download checksum, configuration and source links in `licenses/FFmpeg`. Qt and PyAV wheels also contain their own FFmpeg libraries/notices. Fulfil corresponding-source obligations before redistributing binaries; source links alone are not an offer of source.
- PyInstaller: its bootloader has a redistribution exception; follow https://pyinstaller.org/en/stable/license.html.

Tapo Desk is an unofficial client, not affiliated with TP-Link. No private video, credentials or Tapo product branding assets are included in distributable archives.
