"""Credential-free TP-Link UDP discovery on attached IPv4 subnets."""
import asyncio
import ipaddress
import re
from .storage import UserError


def local_networks():
    """Qt enumerates adapter netmasks on Linux and Windows without shell commands."""
    from PySide6.QtNetwork import QNetworkInterface
    rows=[]
    for interface in QNetworkInterface.allInterfaces():
        flags=interface.flags()
        if not flags & QNetworkInterface.InterfaceFlag.IsUp or not flags & QNetworkInterface.InterfaceFlag.IsRunning or flags & QNetworkInterface.InterfaceFlag.IsLoopBack:
            continue
        for entry in interface.addressEntries():
            try:
                ip=ipaddress.IPv4Address(entry.ip().toString())
                prefix=entry.prefixLength()
                if not ip.is_private or ip.is_loopback or ip.is_link_local or not 1<=prefix<=30:
                    continue
                network=ipaddress.IPv4Network(f'{ip}/{prefix}',strict=False)
                rows.append({'network':str(network),'address':str(ip),
                             'adapter':interface.humanReadableName() or interface.name()})
            except ValueError:
                continue
    return sorted(rows,key=lambda row:(ipaddress.IPv4Address(row['address']),row['adapter']))


def clean_text(value,limit=80):
    return ''.join(c for c in str(value) if c.isprintable())[:limit].strip()


def device_from_response(raw,network):
    """Whitelist discovery fields, using datagram source rather than advertised IP."""
    try:
        host=ipaddress.IPv4Address(raw['meta']['ip'])
        if host not in network or host in (network.network_address,network.broadcast_address):return None
        response=raw['discovery_response']
        info=response.get('result') or response.get('system',{}).get('get_sysinfo',{})
        if not isinstance(info,dict):return None
        kind=clean_text(info.get('device_type',info.get('mic_type',info.get('type','')))).upper()
        model=clean_text(info.get('device_model',info.get('model',''))).split('(',1)[0].strip()
        if not model:return None
        # Kasa plugs and unrelated network services are not branded as Tapo.
        if 'TAPO' not in kind and kind!='SMART.IPCAMERA':
            return None
        camera='CAMERA' in kind
        category='Camera' if camera else ('Hub' if 'HUB' in kind else 'Other Tapo device')
        return {'host':str(host),'model':model,'kind':category,'is_camera':camera}
    except (KeyError,TypeError,ValueError,AttributeError):
        return None


def onvif_device(data, host, network):
    """Read only model/name scopes from an ONVIF ProbeMatch, never service URLs."""
    from urllib.parse import unquote
    from xml.etree import ElementTree as ET
    try:
        source=ipaddress.IPv4Address(host)
        if source not in network or source in (network.network_address,network.broadcast_address):return None
        if len(data)>65535 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():return None
        root=ET.fromstring(data)
        matches=[e for e in root.iter() if e.tag.rsplit('}',1)[-1]=='ProbeMatch']
        for match in matches:
            scopes=[]
            for e in match.iter():
                if e.tag.rsplit('}',1)[-1]=='Scopes':scopes.extend((e.text or '').split())
            hardware=[unquote(v.rsplit('/',1)[-1]) for v in scopes if '/hardware/' in v]
            names=[unquote(v.rsplit('/',1)[-1]) for v in scopes if '/name/' in v]
            model=clean_text(hardware[0] if hardware else '').split('(',1)[0].strip()
            brand=' '.join(names).upper()
            if not model or not (model.upper() in ('C310','C320WS') or 'TAPO' in brand):continue
            return {'host':str(source),'model':model,'kind':'Camera','is_camera':True}
    except (ValueError,TypeError,ET.ParseError):
        return None
    return None


async def onvif_scan(network,address,capture):
    """Multicast plus bounded direct probes avoid Wi-Fi multicast suppression."""
    import socket
    import uuid
    def probe():
        return (f'<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
          'xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
          'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
          'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
          f'<s:Header><a:MessageID>uuid:{uuid.uuid4()}</a:MessageID>'
          '<a:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</a:To>'
          '<a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</a:Action>'
          '</s:Header><s:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types>'
          '</d:Probe></s:Body></s:Envelope>').encode()
    class Receiver(asyncio.DatagramProtocol):
        def datagram_received(self,data,addr):
            row=onvif_device(data,addr[0],network)
            if row:capture(row)
    transport,_=await asyncio.get_running_loop().create_datagram_endpoint(
        Receiver,local_addr=(address,0),family=socket.AF_INET)
    try:
        sock=transport.get_extra_info('socket')
        sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_IF,socket.inet_aton(address))
        sock.setsockopt(socket.IPPROTO_IP,socket.IP_MULTICAST_TTL,1)
        transport.sendto(probe(),('239.255.255.250',3702))
        await asyncio.sleep(0.25)
        if network.num_addresses<=1024:
            message=probe()
            for host in network.hosts():
                if str(host)==address:continue
                transport.sendto(message,(str(host),3702))
                await asyncio.sleep(0.004)
        await asyncio.sleep(3)
    finally:
        transport.close()


async def scan(network_text, *, address=None, cancelled=None, on_progress=None, discover=None, networks=None, onvif_discover=None):
    """Local discovery only: no update(), authentication, keyring or HTTP login."""
    try:
        network=ipaddress.IPv4Network(network_text,strict=True)
    except (ValueError,TypeError):
        raise UserError('Choose a local network from the list, then scan again.') from None
    attached=local_networks() if networks is None else networks
    selected=next((row for row in attached if row['network']==str(network) and (address is None or row['address']==address)),None)
    if not selected:
        raise UserError('This network is no longer attached. Reopen Find cameras and select an active adapter.')
    if discover is None:
        from kasa import Discover
        discover=Discover.discover
    found={}
    def capture_row(row):
        if row:
            found[row['host']]=row
            if on_progress:on_progress(len(found))
    def capture(raw):capture_row(device_from_response(raw,network))
    async def tplink():
        devices={}
        try:
            devices=await discover(target=str(network.broadcast_address),discovery_timeout=5,
                                   discovery_packets=3,on_discovered_raw=capture)
        finally:
            await asyncio.gather(*(device.protocol.close() for device in devices.values()),return_exceptions=True)
    onvif_discover=onvif_discover or onvif_scan
    tasks=[asyncio.create_task(tplink()),asyncio.create_task(onvif_discover(network,selected['address'],capture_row))]
    watcher=None
    if cancelled is not None:
        async def watch():
            while not all(task.done() for task in tasks):
                if cancelled.is_set():
                    for task in tasks:task.cancel()
                    return
                await asyncio.sleep(0.1)
        watcher=asyncio.create_task(watch())
    try:
        outcomes=await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),timeout=15)
        if cancelled is not None and cancelled.is_set():raise asyncio.CancelledError()
        failures=sum(isinstance(item,BaseException) for item in outcomes)
        if failures==2:
            raise UserError('Discovery could not use this network. Check your firewall and adapter, then retry.')
        warnings=[]
        if failures:warnings.append('One discovery method was unavailable. Your firewall may be blocking it.')
        if network.num_addresses>1024:
            warnings.append('Direct camera probes are skipped on networks larger than 1,024 addresses; broadcast discovery is still used.')
        return {'network':str(network),'devices':sorted(found.values(),key=lambda row:ipaddress.IPv4Address(row['host'])), 'warnings':warnings}
    except TimeoutError:
        raise UserError('Discovery timed out. Check your network adapter and retry.') from None
    finally:
        if watcher:
            watcher.cancel();await asyncio.gather(watcher,return_exceptions=True)
        for task in tasks:
            if not task.done():task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
