import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parent / 'claude-cleanup-windows/scripts/claude_cleanup.py'
spec = importlib.util.spec_from_file_location('cleanup', SCRIPT)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.roaming = self.home / 'AppData/Roaming'
        local_patch = patch.dict(cleanup.os.environ, {'LOCALAPPDATA': str(self.home / 'AppData/Local')})
        local_patch.start()
        self.addCleanup(local_patch.stop)
        self.cli = self.home / '.claude'
        self.cli.mkdir()
        (self.cli / 'cache').mkdir()
        (self.cli / 'cache/data').write_bytes(b'cache data')
        (self.cli / 'projects').mkdir()
        (self.cli / 'projects/history').write_text('keep')
        self.settings = {'env': {'DISABLE_TELEMETRY': '1', 'SECRET': 'fixture'}, 'hooks': {}}
        (self.cli / 'settings.json').write_text(json.dumps(self.settings))

    def test_backup_move_and_settings_preservation(self):
        paths = cleanup.candidates(cleanup.roots(self.home, self.roaming), False)
        with patch.object(cleanup, 'ensure_idle', return_value=0):
            batch = cleanup.execute(self.home, self.roaming, paths, 'on')
        self.assertFalse((self.cli / 'cache').exists())
        self.assertEqual((batch / 'snapshot/cli/cache/data').read_bytes(), b'cache data')
        self.assertEqual((batch / 'quarantine/00-cache/data').read_bytes(), b'cache data')
        self.assertEqual((self.cli / 'projects/history').read_text(), 'keep')
        expected = dict(self.settings, env=dict(self.settings['env'], CLAUDE_CODE_SIMPLE='1'))
        self.assertEqual(cleanup.read_settings(self.cli / 'settings.json'), expected)
        self.assertEqual(json.loads((batch / 'plan.json').read_text())['status'], 'complete')

    def test_arbitrary_target_refused_before_write(self):
        with self.assertRaises(RuntimeError):
            cleanup.execute(self.home, self.roaming, [self.cli / 'projects'], None)
        self.assertFalse((self.home / 'ClaudeCleanupBackups').exists())

    def test_credential_only_when_explicitly_selected(self):
        credential = self.cli / '.credentials.json'
        credential.write_text('{"token":"fixture"}')
        locations = cleanup.roots(self.home, self.roaming)
        self.assertNotIn(credential, cleanup.candidates(locations, False))
        self.assertIn(credential, cleanup.candidates(locations, True))
        with self.assertRaises(RuntimeError):
            cleanup.execute(self.home, self.roaming, [credential], None)

    def test_backup_failure_leaves_sources_untouched(self):
        targets = cleanup.candidates(cleanup.roots(self.home, self.roaming), False)
        with patch.object(cleanup.shutil, 'copytree', side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):
                cleanup.execute(self.home, self.roaming, targets, None)
        self.assertEqual((self.cli / 'cache/data').read_bytes(), b'cache data')

    def test_junction_refused(self):
        import subprocess
        target = self.home / 'outside'
        target.mkdir()
        link = self.cli / 'cache/junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)], capture_output=True)
        if result.returncode:
            self.skipTest('Junction creation unavailable')
        try:
            with self.assertRaises(RuntimeError):
                cleanup.candidates(cleanup.roots(self.home, self.roaming), False)
        finally:
            link.rmdir()

    def test_claude_process_detection(self):
        self.assertTrue(cleanup.is_claude({'Name': 'Claude.exe'}))
        self.assertTrue(cleanup.is_claude({'Name': 'node.exe', 'CommandLine': r'node C:\npm\@anthropic-ai\claude-code\cli.js'}))
        self.assertFalse(cleanup.is_claude({'Name': 'node.exe', 'CommandLine': r'node C:\app\index.js'}))

    def test_msix_caches_and_unrelated_package_preserved(self):
        local = self.home / 'AppData/Local/Packages'
        root = local / 'Claude_pzs8sxrjxfjjc/LocalCache/Roaming/Claude'
        cache = root / 'Cache'
        cache.mkdir(parents=True)
        (cache / 'data').write_bytes(b'msix cache')
        history = root / 'claude-code-sessions'
        history.mkdir()
        (history / 'session').write_text('keep')
        other = local / 'Other_123/LocalCache/Roaming/Claude/Cache'
        other.mkdir(parents=True)
        targets = cleanup.candidates(cleanup.roots(self.home, self.roaming), False)
        self.assertIn(cache, targets)
        self.assertNotIn(other, targets)
        with patch.object(cleanup, 'ensure_idle', return_value=0):
            batch = cleanup.execute(self.home, self.roaming, targets, None)
        self.assertFalse(cache.exists())
        self.assertTrue(history.exists())
        self.assertTrue(other.exists())
        self.assertTrue(any(p.read_bytes() == b'msix cache' for p in (batch / 'snapshot/desktop').rglob('data')))

    def test_local_id_rotation_preserves_unrelated_config(self):
        identity = self.home / '.claude.json'
        before = {'userID': 'old', 'machineID': 'old', 'oauthAccount': {},
                  'mcpServers': {'example': {}}, 'projects': {'keep': True}}
        identity.write_text(json.dumps(before))
        backups = self.cli / 'backups'
        backups.mkdir()
        old = backups / '.claude.json.backup.123'
        old.write_text(json.dumps(before))
        with patch.object(cleanup, 'ensure_idle', return_value=0):
            batch = cleanup.execute(self.home, self.roaming, [], None, rotate_ids=True)
        after = json.loads(identity.read_text())
        self.assertNotEqual(after['userID'], 'old')
        self.assertEqual(after, json.loads(old.read_text()))
        self.assertEqual(after['mcpServers'], before['mcpServers'])
        self.assertEqual(after['projects'], before['projects'])
        self.assertNotIn('oauthAccount', after)
        self.assertEqual(json.loads((batch / 'snapshot/identity.json').read_text()), before)


if __name__ == '__main__':
    unittest.main()
