import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

import launch
import prepare_usb


class USBTests(unittest.TestCase):
    def test_drive_detection_linux_usb_parent(self):
        data = {"blockdevices": [{"name": "sdb", "rm": False, "tran": "usb", "mountpoints": [None],
                                  "children": [{"mountpoints": ["/media/usb"]}]}]}
        with mock.patch.object(prepare_usb.sys, "platform", "linux"), \
             mock.patch.object(prepare_usb.os, "name", "posix"), \
             mock.patch.object(prepare_usb.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(data))), \
             mock.patch.object(Path, "is_dir", return_value=True):
            self.assertEqual(prepare_usb.removable_drives(), [Path('/media/usb')])

    def test_windows_host_command_targets_linux(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            (project / 'requirements.txt').write_text('pygame\n')
            cmd = prepare_usb.linux_wheel_command(project, project / 'dest', '3.11', 'x86_64', '2.28')
            platforms = [cmd[i + 1] for i, x in enumerate(cmd) if x == '--platform']
            self.assertTrue(all(p.startswith(('manylinux', 'linux_')) for p in platforms))
            self.assertIn('manylinux_2_17_x86_64', platforms)
            self.assertIn('--only-binary=:all:', cmd)
            self.assertIn('cp311', cmd)

    def test_reject_windows_wheel(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / 'package-1.0-py3-none-win_amd64.whl').touch()
            self.assertFalse(prepare_usb.linux_wheels_only(path))

    def test_flask_and_pygame_requirements_priority(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / 'run.py').write_text('print("ok")')
            (path / 'requirements.txt').write_text('-r extra.txt\nFlask>=2\n')
            (path / 'extra.txt').write_text('pygame-ce==2.5\n')
            self.assertIsNone(launch.detect_web(path))
            (path / 'extra.txt').write_text('# none\n')
            self.assertEqual(launch.detect_web(path), 'Flask')

    def test_web_exit_never_waits_for_input(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(launch.subprocess, 'Popen') as popen, \
             mock.patch.object(launch, 'pause', side_effect=AssertionError('must not pause')), \
             mock.patch.object(launch, 'clear_screen_for_exit'), redirect_stdout(io.StringIO()):
            popen.return_value.wait.return_value = 1
            self.assertTrue(launch._run_in_terminal('game', sys.executable, td, 'app.py', 'Flask'))

    def test_offline_pip_failure_not_reported_ready(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td) / 'game'
            project.mkdir()
            (project / 'run.py').write_text('import fakepackage\n')
            with mock.patch.object(launch, 'FLASH_WHEELS_DIR', Path(td) / 'wheels'), \
                 mock.patch.object(launch, 'ensure_venv', return_value=(Path('/python'), 'ok')), \
                 redirect_stdout(io.StringIO()):
                reg = {}
                self.assertFalse(launch.setup_project(project, reg, False))
                self.assertIn('game', reg)

    def test_reject_remote_nested_requirements(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / 'requirements.txt').write_text('-r nested.txt\n')
            (path / 'nested.txt').write_text('foo @ https://example.com/foo.whl\n')
            self.assertFalse(launch.offline_requirements_safe(path / 'requirements.txt')[0])

    def test_prepare_wheel_failure_preserves_old_bundle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            existing = root / 'BOTYARA-GAMES' / 'wheels' / 'game'
            existing.mkdir(parents=True)
            (existing / 'old.whl').write_text('old')

            def clone(url, dest):
                dest.mkdir()
                (dest / 'run.py').write_text('import flask\n')
                return True, ''

            with mock.patch.object(launch, 'REPO_LIST', ['game']), \
                 mock.patch.object(launch, 'git_clone', side_effect=clone), \
                 mock.patch.object(prepare_usb.subprocess, 'run', return_value=mock.Mock(returncode=1)), \
                 redirect_stdout(io.StringIO()):
                result, failures = prepare_usb.prepare(root, True, True, '3.11', 'x86_64', '2.17')
            self.assertEqual(failures, ['game'])
            self.assertTrue((result / 'repos' / 'game' / 'run.py').exists())
            self.assertEqual((existing / 'old.whl').read_text(), 'old')
            self.assertTrue((result / 'launch.py').is_file())
            self.assertTrue((result / 'update_repos_usb.sh').is_file())

    @unittest.skipUnless(shutil.which('bash') and shutil.which('git') and shutil.which('python3'),
                         'requires Bash, Git and python3')
    def test_usb_updater_syncs_only_listed_repos(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            upstream = root / 'upstream'
            upstream.mkdir()
            usb, failures = prepare_usb.prepare(root, False, False)
            self.assertFalse(failures)
            repos = usb / 'repos'
            repos.mkdir()
            github = 'https://github.com/%s/' % launch.GH_USER
            env = dict(os.environ, BOTYARA_REPOS='existing,missing', GIT_CONFIG_NOSYSTEM='1',
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_COUNT='1',
                       GIT_CONFIG_KEY_0='url.%s/.insteadOf' % upstream.as_uri(),
                       GIT_CONFIG_VALUE_0=github, GIT_ALLOW_PROTOCOL='file')

            def git(cwd, *args):
                return subprocess.run(['git', *args], cwd=cwd, env=env, check=True,
                                      capture_output=True, text=True, timeout=10)

            def commit(repo, text):
                (repo / 'data.txt').write_text(text)
                git(repo, 'add', 'data.txt')
                git(repo, '-c', 'user.name=Test', '-c', 'user.email=test@example.org',
                    '-c', 'commit.gpgsign=false', 'commit', '-qm', text)

            for name in ('existing', 'missing', 'unlisted'):
                remote = upstream / (name + '.git')
                git(upstream, 'init', '-q', '-b', 'main', str(remote))
                commit(remote, 'old')
                if name != 'missing':
                    git(repos, 'clone', '--depth', '1', github + name + '.git', name)
                commit(remote, 'new')

            def update(settings):
                return subprocess.run(['bash', str(usb / 'update_repos_usb.sh')], cwd=root,
                                      env=settings, capture_output=True, text=True, timeout=15)

            result = update(env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((repos / 'existing' / 'data.txt').read_text(), 'new')
            self.assertEqual((repos / 'missing' / 'data.txt').read_text(), 'new')
            self.assertEqual((repos / 'unlisted' / 'data.txt').read_text(), 'old')
            self.assertIn('добавлено: 1', result.stdout)
            self.assertIn('обновлено: 1', result.stdout)
            self.assertNotIn('\x1b[', result.stdout)

            (repos / 'occupied').mkdir()
            (repos / 'occupied' / 'keep.txt').touch()
            result = update(dict(env, BOTYARA_REPOS='occupied,../outside,existing'))
            self.assertEqual(result.returncode, 1)
            self.assertIn('ошибок: 2', result.stdout)
            self.assertIn('без изменений: 1', result.stdout)
            self.assertTrue((repos / 'occupied' / 'keep.txt').exists())

    def test_offline_repo_copy_and_failure_summary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / 'repos' / 'game'
            repo.mkdir(parents=True)
            (repo / 'run.py').write_text('import missing_pkg\n')
            projects = root / 'installed'
            with mock.patch.object(launch, 'PROJECTS_DIR', projects), \
                 mock.patch.object(launch, 'REGISTRY_FILE', projects / '.registry.json'), \
                 mock.patch.object(launch, 'FLASH_REPOS_DIR', root / 'repos'), \
                 mock.patch.object(launch, 'FLASH_WHEELS_DIR', root / 'wheels'), \
                 mock.patch.object(launch, 'REPO_LIST', ['game']), \
                 mock.patch.object(launch, 'ensure_venv', return_value=(Path('/python'), 'ok')), \
                 redirect_stdout(io.StringIO()):
                stats = launch.install_games(False, {}, interactive=False)
            self.assertTrue((projects / 'game' / 'run.py').exists())
            self.assertEqual(stats['failed'], ['game'])
            self.assertEqual(stats['ok'], [])

    def test_wheel_metadata_direct_link_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            whl = Path(td) / 'demo-1.0-py3-none-any.whl'
            with ZipFile(whl, 'w') as archive:
                archive.writestr('demo-1.0.dist-info/METADATA',
                                 'Metadata-Version: 2.1\nName: demo\nVersion: 1.0\n'
                                 'Requires-Dist: foo @ https://example.com/foo.whl\n')
            self.assertFalse(launch.offline_wheels_safe(td)[0])

    def test_offline_install_real_wheel(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            flash = root / 'stick'
            project = root / 'installed' / 'game'
            project.mkdir(parents=True)
            (project / 'run.py').write_text('import test_usb_pkg\n')
            (project / 'requirements.txt').write_text('test-usb-pkg==1.0\n')
            wheel_dir = flash / 'wheels' / 'game'
            wheel_dir.mkdir(parents=True)
            whl = wheel_dir / 'test_usb_pkg-1.0-py3-none-any.whl'
            with ZipFile(whl, 'w') as z:
                z.writestr('test_usb_pkg.py', 'answer = 42\n')
                z.writestr('test_usb_pkg-1.0.dist-info/METADATA', 'Metadata-Version: 2.1\nName: test-usb-pkg\nVersion: 1.0\n')
                z.writestr('test_usb_pkg-1.0.dist-info/WHEEL', 'Wheel-Version: 1.0\nGenerator: tests\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
                z.writestr('test_usb_pkg-1.0.dist-info/RECORD', '')
            with mock.patch.object(launch, 'FLASH_WHEELS_DIR', flash / 'wheels'), redirect_stdout(io.StringIO()):
                reg = {}
                self.assertTrue(launch.setup_project(project, reg, False))
            result = subprocess.run([reg['game']['python'], '-c', 'import test_usb_pkg; print(test_usb_pkg.answer)'],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), '42')


if __name__ == '__main__':
    unittest.main()
