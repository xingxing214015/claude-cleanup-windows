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
        idle_patch = patch.object(cleanup, 'ensure_idle', return_value=0)
        idle_patch.start()
        self.addCleanup(idle_patch.stop)
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

    def desktop_fixture(self):
        package = {'Name': 'Claude', 'PackageFullName': 'Claude_1.0.0.0_x64__fixture',
                   'PackageFamilyName': 'Claude_fixture'}
        package_root = self.home / 'AppData/Local/Packages/Claude_fixture'
        profile = package_root / 'LocalCache/Roaming/Claude'
        profile.mkdir(parents=True)
        (profile / 'claude_desktop_config.json').write_text('{"mcpServers":{}}')
        (profile / 'Cookies').write_bytes(b'fixture login')
        (profile / 'claude-code-sessions').mkdir()
        (profile / 'claude-code-sessions/history').write_text('desktop fixture session')
        state = package_root / 'LocalState'
        state.mkdir()
        (state / 'fixture').write_bytes(b'state')
        legacy = self.roaming / 'Claude'
        legacy.mkdir(parents=True)
        (legacy / 'config.json').write_text('{"fixture":true}')
        (package_root / 'other-package-data').write_bytes(b'additional backup')
        return package, package_root, profile, legacy

    def test_desktop_reset_backs_up_complete_profiles_and_keeps_cli_history(self):
        package, root, profile, legacy = self.desktop_fixture()
        with patch.object(cleanup, 'installed_packages', return_value=[package]):
            targets = cleanup.candidates(cleanup.roots(self.home, self.roaming), False, 'reset')
            self.assertNotIn(profile, targets)  # Parent LocalCache moves as one unit.
            batch = cleanup.execute(self.home, self.roaming, targets, None, desktop='reset')
        self.assertFalse(profile.exists())
        self.assertFalse(legacy.exists())
        self.assertFalse((root / 'LocalState').exists())
        self.assertEqual((self.cli / 'projects/history').read_text(), 'keep')
        self.assertEqual(cleanup.read_settings(self.cli / 'settings.json'), self.settings)
        record = json.loads((batch / 'plan.json').read_text())
        for item in record['moves']:
            self.assertTrue(Path(item['destination']).exists())
        self.assertTrue(any(p.read_bytes() == b'fixture login' for p in (batch / 'snapshot').rglob('Cookies')))
        self.assertTrue(any(p.read_text() == 'desktop fixture session' for p in (batch / 'snapshot/desktop').rglob('history')))

    def test_complete_profile_requires_explicit_reset(self):
        _, _, profile, legacy = self.desktop_fixture()
        with self.assertRaises(RuntimeError):
            cleanup.execute(self.home, self.roaming, [legacy], None)
        self.assertTrue(profile.exists())
        self.assertFalse((self.home / 'ClaudeCleanupBackups').exists())

    def test_uninstall_only_after_verified_complete_package_backup(self):
        package, root, _, _ = self.desktop_fixture()
        observed = []
        def uninstall(selected):
            batches = list((self.home / 'ClaudeCleanupBackups').iterdir())
            snapshot = batches[0] / 'snapshot/packages/Claude_fixture'
            self.assertEqual((snapshot / 'other-package-data').read_bytes(), b'additional backup')
            self.assertTrue((snapshot / 'LocalCache/Roaming/Claude/Cookies').exists())
            observed.append(selected)
        with patch.object(cleanup, 'installed_packages', return_value=[package]), \
                patch.object(cleanup, 'uninstall_package', side_effect=uninstall):
            targets = cleanup.candidates(cleanup.roots(self.home, self.roaming), False, 'uninstall')
            batch = cleanup.execute(self.home, self.roaming, targets, None, desktop='uninstall')
        self.assertEqual(observed, [package])
        self.assertEqual(json.loads((batch / 'plan.json').read_text())['status'], 'complete')

    def test_uninstall_backup_failure_never_calls_windows_uninstaller(self):
        package, _, profile, _ = self.desktop_fixture()
        with patch.object(cleanup, 'installed_packages', return_value=[package]), \
                patch.object(cleanup, 'uninstall_package') as uninstall, \
                patch.object(cleanup.shutil, 'copytree', side_effect=OSError('disk full')):
            targets = cleanup.candidates(cleanup.roots(self.home, self.roaming), False, 'uninstall')
            with self.assertRaises(OSError):
                cleanup.execute(self.home, self.roaming, targets, None, desktop='uninstall')
        uninstall.assert_not_called()
        self.assertTrue(profile.exists())

    def test_uninstall_failure_reports_partial_state_and_retains_recovery_data(self):
        package, _, _, _ = self.desktop_fixture()
        with patch.object(cleanup, 'installed_packages', return_value=[package]), \
                patch.object(cleanup, 'uninstall_package', side_effect=RuntimeError('fixture failure')):
            targets = cleanup.candidates(cleanup.roots(self.home, self.roaming), False, 'uninstall')
            with self.assertRaises(RuntimeError):
                cleanup.execute(self.home, self.roaming, targets, None, desktop='uninstall')
        batch = next((self.home / 'ClaudeCleanupBackups').iterdir())
        self.assertEqual(json.loads((batch / 'plan.json').read_text())['status'], 'backed-up')
        self.assertTrue((batch / 'snapshot/packages/Claude_fixture/LocalState/fixture').exists())
        self.assertTrue((batch / 'quarantine').exists())

    def test_unknown_installer_or_package_changes_stop_before_writes(self):
        with patch.object(cleanup, 'installed_packages', return_value=[]):
            with self.assertRaises(RuntimeError):
                cleanup.execute(self.home, self.roaming, [], None, desktop='uninstall')
        with patch.object(cleanup, 'installed_packages', return_value=[{'Name': 'new'}]):
            with self.assertRaises(RuntimeError):
                cleanup.execute(self.home, self.roaming, [], None, desktop='reset', expected_packages=[])
        self.assertFalse((self.home / 'ClaudeCleanupBackups').exists())

    def test_running_app_blocks_reset_before_backup(self):
        with patch.object(cleanup, 'installed_packages', return_value=[]), \
                patch.object(cleanup, 'ensure_idle', side_effect=RuntimeError('app running')):
            targets = cleanup.candidates(cleanup.roots(self.home, self.roaming), False, 'reset')
            with self.assertRaises(RuntimeError):
                cleanup.execute(self.home, self.roaming, targets, None, desktop='reset')
        self.assertFalse((self.home / 'ClaudeCleanupBackups').exists())


if __name__ == '__main__':
    unittest.main()
