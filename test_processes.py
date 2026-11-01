import subprocess,sys,unittest
from pathlib import Path
from unittest.mock import patch
from tapo_desktop.processes import worker_command,prepare_worker_process


class ProcessLaunchTests(unittest.TestCase):
    def test_frozen_windows_uses_separate_internal_worker(self):
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'_MEIPASS','C:/app/_internal',create=True),patch.object(sys,'platform','win32'):
            executable,args=worker_command()
        self.assertEqual(Path(executable),Path('C:/app/_internal/TapoDeskWorker.exe'))
        self.assertEqual(args,['--worker'])

    def test_source_windows_uses_python_with_pipes(self):
        with patch.object(sys,'frozen',False,create=True),patch.object(sys,'executable','C:/Python312/pythonw.exe'),patch.object(sys,'platform','win32'):
            executable,args=worker_command()
        self.assertEqual(Path(executable),Path('C:/Python312/python.exe'));self.assertEqual(args[-1],'--worker')

    def test_frozen_linux_keeps_existing_worker_entry(self):
        with patch.object(sys,'frozen',True,create=True),patch.object(sys,'platform','linux'):
            self.assertEqual(worker_command(),(sys.executable,['--worker']))

    @unittest.skipUnless(sys.platform=='win32','Windows process flags')
    def test_worker_children_do_not_allocate_console_and_flags_are_preserved(self):
        calls=[]
        class FakePopen:
            def __init__(self,*args,**kwargs):calls.append(kwargs)
        with patch.object(subprocess,'Popen',FakePopen):
            prepare_worker_process();policy=subprocess.Popen;prepare_worker_process()
            self.assertIs(subprocess.Popen,policy)
            subprocess.Popen(['ffmpeg'],creationflags=subprocess.CREATE_NEW_CONSOLE|subprocess.CREATE_NEW_PROCESS_GROUP)
        flags=calls[0]['creationflags']
        self.assertTrue(flags&subprocess.CREATE_NO_WINDOW);self.assertTrue(flags&subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertFalse(flags&subprocess.CREATE_NEW_CONSOLE)
