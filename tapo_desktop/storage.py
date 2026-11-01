"""Non-secret preferences and OS-only credential storage."""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile


class UserError(Exception):
    pass


@dataclass
class Camera:
    id: str
    name: str
    host: str
    model: str = 'Tapo'
    username: str = ''  # Camera account username, not the Tapo account email.
    stream: str = 'stream1'
    use_shared_credentials: bool = True

    @classmethod
    def from_dict(cls, data):
        import ipaddress
        obj = cls(**{k: data[k] for k in cls.__dataclass_fields__ if k in data})
        addr = ipaddress.ip_address(obj.host)
        if addr.version != 4 or not addr.is_private or addr.is_loopback or addr.is_link_local:
            raise UserError('Use a private LAN IPv4 address for the camera.')
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', obj.id):
            raise UserError('Invalid camera identifier.')
        if not isinstance(obj.use_shared_credentials, bool):
            raise UserError('Invalid credential selection.')
        if not obj.name.strip() or obj.stream not in ('stream1', 'stream2'):
            raise UserError('Enter a name and choose a valid video quality.')
        return obj


def root_dir():
    if platform.system() == 'Windows':
        base = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))
    else:
        base = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))
    root = base/'TapoDesk'
    try:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        raise UserError('Application settings folder is not writable. Check your user profile permissions.') from None
    return root


def cache_dir():
    path = root_dir()/'playback-cache'
    path.mkdir(exist_ok=True, mode=0o700)
    return path


def thumbnail_path(camera,date,start,end):
    return cache_dir()/(camera.id+'-'+camera.host.replace('.','_'))/'thumbnails'/f'{date}_{int(start)}-{int(end)}.jpg'


def load_cameras():
    path = root_dir()/'cameras.json'
    if not path.exists():
        return [Camera('c310', 'C310', '192.168.0.163', 'C310'),
                Camera('c320ws', 'C320WS', '192.168.0.164', 'C320WS')]
    try:
        return [Camera.from_dict(c) for c in json.loads(path.read_text())]
    except Exception:
        raise UserError('Camera settings could not be read. Restore cameras.json or rename it to start again.') from None


def save_cameras(cameras):
    payload = [asdict(Camera.from_dict(asdict(c))) for c in cameras]
    fd, tmp = tempfile.mkstemp(prefix='.cameras-', dir=root_dir())
    try:
        with os.fdopen(fd, 'w') as file:
            json.dump(payload, file, indent=2)
        os.replace(tmp, root_dir()/'cameras.json')
    finally:
        Path(tmp).unlink(missing_ok=True)


def credential_key(kind, camera_id=None):
    if kind == 'shared_camera':
        return 'tapo-desk-camera', 'shared'
    if kind == 'cloud':
        return 'tapo-poc', 'owner'  # Reuse the verified CLI's desktop entry.
    return 'tapo-desk-camera', camera_id


def _native_keyring():
    import keyring
    backend = keyring.get_keyring()
    module = type(backend).__module__
    allowed = ('keyring.backends.Windows', 'keyring.backends.SecretService', 'keyring.backends.macOS')
    if not any(module == name or module.startswith(name+'.') for name in allowed):
        raise UserError('No supported secure credential store. Unlock your desktop keyring and install libsecret-tools on Linux.')
    if platform.system() == 'Windows':
        if module != 'keyring.backends.Windows':
            raise UserError('Windows Credential Manager is required to save passwords securely.')
        # Persist for this Windows user across logons on this laptop, without
        # requesting enterprise credential roaming or a session-only entry.
        backend.persist = 'local machine'
    return keyring


def get_secret(kind, camera_id=None):
    service, account = credential_key(kind, camera_id)
    if platform.system() == 'Linux' and shutil.which('secret-tool'):
        try:
            r = subprocess.run(['secret-tool','lookup','service',service,'account',account],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30)
            value = r.stdout.decode('utf8') if r.returncode == 0 else None
        except Exception:
            raise UserError('Cannot access your desktop keyring. Unlock it and retry.') from None
    else:
        try:
            value = _native_keyring().get_password(service, account)
        except UserError:
            raise
        except Exception:
            raise UserError('Cannot access your operating system credential store.') from None
    if not value:
        what = 'Tapo account password' if kind == 'cloud' else 'Camera Account password for live view'
        raise UserError(f'Add the {what} in Credentials.')
    return value


def put_secret(kind, value, camera_id=None):
    if not value:
        raise UserError('Enter a password before saving.')
    service, account = credential_key(kind, camera_id)
    if platform.system() == 'Linux' and shutil.which('secret-tool'):
        try:
            r = subprocess.run(['secret-tool','store','--label=Tapo Desk', 'service',service,'account',account],
                               input=value.encode(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            if r.returncode:
                raise UserError('Unlock your desktop keyring and retry saving.')
        except (OSError, subprocess.TimeoutExpired):
            raise UserError('Keyring unavailable. Unlock your desktop keyring and retry.') from None
    else:
        try:
            _native_keyring().set_password(service, account, value)
        except UserError:
            raise
        except Exception:
            raise UserError('Unable to save in the operating system credential store.') from None


def load_shared_live_settings():
    path=root_dir()/'live-account.json'
    if path.exists():
        try:
            data=json.loads(path.read_text())
            if not isinstance(data.get('username'),str):raise ValueError()
            return {'username':data['username']}
        except (ValueError,TypeError,OSError):
            raise UserError('Shared live-view settings could not be read. Check live-account.json.') from None
    # Preserve legacy credentials: one configured account can seed the shared default.
    legacy=[camera for camera in load_cameras() if camera.username]
    if len(legacy)==1:
        return {'username':legacy[0].username,'legacy_camera_id':legacy[0].id}
    return {'username':''}


def save_shared_live_settings(username):
    fd,tmp=tempfile.mkstemp(prefix='.live-account-',dir=root_dir())
    try:
        with os.fdopen(fd,'w') as file:json.dump({'username':username},file)
        os.replace(tmp,root_dir()/'live-account.json')
    finally:Path(tmp).unlink(missing_ok=True)


def migrate_shared_live_account():
    settings=load_shared_live_settings()
    source=settings.get('legacy_camera_id')
    if source:
        password=get_secret('camera',source)
        put_secret('shared_camera',password)
        save_shared_live_settings(settings['username'])
    return {'username':settings['username']}


def shared_live_credentials():
    settings=migrate_shared_live_account()
    if not settings['username']:
        raise UserError('Set the shared Camera Account username and password in Credentials. It will be used for all cameras by default.')
    return settings['username'],get_secret('shared_camera')


def store_shared_live_account(username,password=''):
    if not isinstance(username,str) or not username.strip():
        raise UserError('Enter the shared Camera Account username.')
    if password:put_secret('shared_camera',password)
    else:
        migrate_shared_live_account()
        get_secret('shared_camera')  # Blank means keep an existing stored password.
    save_shared_live_settings(username.strip())


def export_clip(source, destination):
    """Publish a complete copy without replacing an existing file."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.tapo-export-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as output, source.open('rb') as input_file:
            shutil.copyfileobj(input_file, output)
        # Hard links are atomic and fail if the destination exists; same volume staging.
        try:
            os.link(tmp, destination)
        except FileExistsError:
            raise UserError('A file already exists with that name. Choose a different name.') from None
        except OSError:
            # Filesystems without hard links: exclusive creation still prevents overwrite.
            try:
                with destination.open('xb') as output, open(tmp,'rb') as input_file:
                    try:
                        shutil.copyfileobj(input_file, output)
                    except BaseException:
                        destination.unlink(missing_ok=True)
                        raise
            except FileExistsError:
                raise UserError('A file already exists with that name. Choose a different name.') from None
    finally:
        Path(tmp).unlink(missing_ok=True)
