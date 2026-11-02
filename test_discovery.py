import asyncio
from dataclasses import asdict
import ipaddress
import os
import tempfile
import threading
import unittest
from unittest.mock import patch
from tapo_desktop import discovery as d, worker
from tapo_desktop.storage import Camera

NET=ipaddress.IPv4Network('192.168.0.0/24')
ATTACHED=[{'network':str(NET),'address':'192.168.0.123','adapter':'Wi-Fi'}]

def packet(host='192.168.0.20',model='C310(EU)',kind='SMART.IPCAMERA'):
    return {'meta':{'ip':host},'discovery_response':{'result':{
        'ip':'10.0.0.99','device_model':model,'device_type':kind,'owner':'private-owner','device_id':'private-id'}}}


def onvif(model='C310',name='Tapo C310'):
    return f'<Envelope><ProbeMatches><ProbeMatch><Scopes>onvif://www.onvif.org/name/{name.replace(" ","%20")} onvif://www.onvif.org/hardware/{model}</Scopes></ProbeMatch></ProbeMatches></Envelope>'.encode()


async def no_onvif(*args):pass


class DiscoveryTests(unittest.TestCase):
    def test_whitelist_and_source_address(self):
        row=d.device_from_response(packet(),NET)
        self.assertEqual(row['host'],'192.168.0.20')
        self.assertEqual(row['model'],'C310')
        self.assertNotIn('private',str(row))
        self.assertIsNone(d.device_from_response(packet('10.0.0.1'),NET))
        self.assertIsNone(d.device_from_response(packet(model='HS110',kind='IOT.SMARTPLUG'),NET))
        self.assertFalse(d.device_from_response(packet(model='P110',kind='SMART.TAPOPLUG'),NET)['is_camera'])

    def test_onvif_camera_identity_and_malformed_packets(self):
        self.assertEqual(d.onvif_device(onvif(), '192.168.0.162',NET)['model'],'C310')
        self.assertEqual(d.onvif_device(onvif('C320WS','C320WS'),'192.168.0.21',NET)['model'],'C320WS')
        self.assertIsNone(d.onvif_device(onvif('Other','Other camera'),'192.168.0.165',NET))
        self.assertIsNone(d.onvif_device(b'<!DOCTYPE x><x/>','192.168.0.20',NET))
        self.assertIsNone(d.onvif_device(b'not xml','192.168.0.20',NET))
        self.assertIsNone(d.onvif_device(onvif(),'10.0.0.1',NET))

    def test_scan_deduplicates_and_never_updates_devices(self):
        class Protocol:
            closed=False
            async def close(self):self.closed=True
        class Device:
            protocol=Protocol()
            async def update(self):raise AssertionError('Discovery must never authenticate or update')
        device=Device()
        async def fake_discover(**kwargs):
            self.assertEqual(kwargs['target'],'192.168.0.255')
            self.assertNotIn('credentials',kwargs)
            kwargs['on_discovered_raw'](packet())
            return {'192.168.0.20':device}
        async def fake_onvif(network,address,capture):
            self.assertEqual(address,'192.168.0.123')
            capture(d.onvif_device(onvif(),'192.168.0.20',network))
            capture(d.onvif_device(onvif('C320WS','C320WS'),'192.168.0.21',network))
        result=asyncio.run(d.scan(str(NET),discover=fake_discover,onvif_discover=fake_onvif,networks=ATTACHED))
        self.assertEqual(len(result['devices']),2)
        self.assertTrue(device.protocol.closed)

    def test_rejects_nonattached_network_and_adapter(self):
        for network,address in [('10.0.0.0/24',None),(str(NET),'192.168.0.99')]:
            with self.assertRaises(d.UserError):asyncio.run(d.scan(network,address=address,networks=ATTACHED))

    def test_cancellation(self):
        event=threading.Event();event.set()
        async def slow(**kwargs):await asyncio.sleep(30)
        async def other(*args):await asyncio.sleep(30)
        with self.assertRaises(asyncio.CancelledError):
            asyncio.run(d.scan(str(NET),cancelled=event,networks=ATTACHED,discover=slow,onvif_discover=other))

    def test_discovery_worker_needs_no_camera_or_credentials(self):
        async def fake_scan(*args,**kwargs):return {'devices':[]}
        with patch.object(d,'scan',side_effect=fake_scan),patch.object(worker,'get_secret') as secret,patch.object(worker,'emit'):
            self.assertEqual(worker.result_for({'op':'discover','network':str(NET)}),{'devices':[]})
            secret.assert_not_called()


class DiscoveryUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(lambda *_:None)
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'XDG_CONFIG_HOME':self.tmp.name,'LOCALAPPDATA':self.tmp.name});self.env.start()
        from tapo_desktop.app import MainWindow,DiscoveryDialog
        from tapo_desktop.storage import save_cameras,Camera
        save_cameras([Camera('first','First','192.168.0.20'),Camera('second','Second','192.168.0.21')])
        self.window=MainWindow(demo=True)
        self.dialog=DiscoveryDialog(self.window.cameras,self.window,networks=ATTACHED)
    def tearDown(self):
        self.dialog.running=False;self.dialog.close();self.window.close();self.env.stop();self.tmp.cleanup()
    def test_known_devices_disabled_and_new_camera_addable(self):
        rows=[d.onvif_device(onvif(),'192.168.0.162',NET),d.onvif_device(onvif(),'192.168.0.20',NET),
              d.device_from_response(packet('192.168.0.170','P110','SMART.TAPOPLUG'),NET)]
        self.dialog.got_results({'network':str(NET),'devices':rows})
        self.assertEqual(self.dialog.table.item(1,3).text(),'Already added')
        self.assertEqual(self.dialog.table.item(2,3).text(),'Not a camera')
        self.dialog.table.selectRow(0)
        self.assertTrue(self.dialog.add_btn.isEnabled())
        self.assertEqual(self.dialog.selected_devices()[0]['host'],'192.168.0.162')
        self.window.add_discovered(self.dialog.selected_devices())
        self.assertEqual(len(self.window.cameras),3)
        self.window.add_discovered(rows)
        self.assertEqual(len(self.window.cameras),3)
    def test_no_adapter_empty_and_error_recovery(self):
        self.dialog.got_results({'network':str(NET),'devices':[]})
        self.assertFalse(self.dialog.add_btn.isEnabled())
        self.dialog.running=True;self.dialog.failed('Firewall blocked discovery')
        self.assertFalse(self.dialog.running)
        self.assertTrue(self.dialog.scan_btn.isEnabled())
    def test_close_during_scan_requests_cancellation(self):
        requested=[];self.dialog.cancel_requested.connect(lambda:requested.append(True))
        self.dialog.running=True;self.dialog.reject()
        self.assertTrue(requested);self.assertTrue(self.dialog.close_pending)
        self.dialog.cancelled();self.assertFalse(self.dialog.running)


if __name__=='__main__':unittest.main()
