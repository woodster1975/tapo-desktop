# Tapo Desk

A native Python/Qt app for viewing and recording Tapo cameras on Windows and Linux.

## Download for Windows

Download **TapoDesk-0.7.2-Setup-x64.exe** from the [latest release](https://github.com/woodster1975/tapo-desktop/releases/latest). The installer includes Python and the media tools, installs for your Windows account, and adds a Start menu entry and optional desktop shortcut.

Close Tapo Desk before upgrading. Your camera settings and saved credentials are retained. The current installer is unsigned; its SHA-256 checksum is published beside the download. Requires 64-bit Windows 10 version 1809 or later.

## Features

- Live camera view and a multi-camera wall, with full-quality focus.
- Record directly from live view into a local MKV file.
- Browse microSD recordings by camera and date, with an activity timeline and detection markers.
- Cached previews, progressive playback, pause, mute and MP4 export.
- Local-network discovery and manual camera profiles.
- Persistent passwords in Windows Credential Manager or the Linux desktop keyring.
- Console-free Windows startup and hidden background media processes.

Tapo Desk is an unofficial client, not affiliated with TP-Link. Camera and firmware support varies; bounded checks have been performed with C310 and C320WS cameras.

## First use

Connect the computer and cameras to the same local network. Use **Find cameras** or **Add camera** to configure your devices. Replace any example profiles with your own camera addresses.

Open **Credentials** to save the Tapo account password used for recordings. Live view also requires the separately configured Camera Account username and password from the Tapo app. A shared Camera Account can be used across cameras, with per-camera overrides available.

Select a camera and refresh recordings, or connect live view. Use **Record** during live view and **Stop recording** to finish the file. Video is copied without re-encoding where supported; audio is retained or converted when necessary.

## Privacy and storage

Settings and preview caches live outside the source folder. Windows uses `%LOCALAPPDATA%\TapoDesk` for settings and Windows Credential Manager for passwords. Linux uses the user configuration directory and desktop keyring. Plaintext credential fallback stores are rejected.

Passwords persist between sessions. Leaving a password field blank retains the saved password. Other software running as the same operating-system user may also access that user's credential store. Credentials do not transfer automatically between computers.

Recordings stay in your chosen destination. Windows uninstall retains settings, credentials and recordings. The repository excludes local credentials, footage, screenshots, test evidence and generated binaries.

## Run from source

Python 3.11 or newer is required; 64-bit Python 3.12 is recommended. FFmpeg and ffprobe must be available on PATH or in a local media-tool location supported by the launchers.

On Windows, install Python including its launcher, then run:

```powershell
.\setup.ps1
.\start.ps1
```

Setup puts the environment in local application storage, outside synchronized source folders. **Start Tapo Desk.cmd** also launches the configured app. The machine-specific `.windows-runtime` file is excluded from Git.

On Ubuntu, use a normal desktop session with an unlocked Secret Service keyring:

```bash
sudo apt update
sudo apt install python3-venv ffmpeg libsecret-tools libxcb-cursor0 libxkbcommon-x11-0 libegl1
bash setup.sh
./start.sh
```

Use `./start.sh --demo` for an illustrative interface without camera or credential access.

## Build the Windows installer

Install Inno Setup 6 or 7, complete source setup, then run:

```powershell
.\build-windows.ps1
```

The build downloads and verifies pinned FFmpeg tools and generates the installer in `dist`. See [Windows packaging](packaging/README.md) and [third-party components](THIRD_PARTY.md).

## Validation and limitations

Version 0.7.2 passed 114 offline tests. Packaged Windows checks covered GUI-to-worker communication, hidden console state, camera recording dates, a short live recording and video decoding. Isolated install/start/uninstall preserved camera settings and saved credentials. Historical Linux checks covered the camera wall and recording playback.

Run offline tests inside the configured environment:

```bash
python -m unittest discover
```

Initial connections and previews without stored camera JPEGs can take longer. Discovery depends on local network and firewall settings. Multi-hour recording, audible content and installation on a separate clean Windows computer remain unvalidated.

Dependency licenses and bundled notices apply to their respective components. See [THIRD_PARTY.md](THIRD_PARTY.md) before redistributing builds.
