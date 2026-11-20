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


def write_wheel(directory, name, metadata=''):
    wheel = directory / ('%s-1.0-py3-none-any.whl' % name)
    with ZipFile(wheel, 'w') as archive:
        archive.writestr(name + '.py', 'answer = 42\n')
        archive.writestr('%s-1.0.dist-info/METADATA' % name,
                         'Metadata-Version: 2.1\nName: %s\nVersion: 1.0\n%s' % (name, metadata))
        archive.writestr('%s-1.0.dist-info/WHEEL' % name,
                         'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n')
        archive.writestr('%s-1.0.dist-info/RECORD' % name, '')
    return wheel.name


class USBTests(unittest.TestCase):
    def test_drive_detection_linux_usb_parent(self):
        data = {"blockdevices": [{"name": "sdb", "rm": False, "tran": "usb", "mountpoints": [None],
                                  "children": [{"mountpoints": ["/media/usb"]}]}]}
        with mock.patch.object(prepare_usb.sys, "platform", "linux"), \
             mock.patch.object(prepare_usb.os, "name", "posix"), \
             mock.patch.object(prepare_usb.subprocess, "run", return_value=mock.Mock(stdout=json.dumps(data))), \
             mock.patch.object(Path, "is_dir", return_value=True):
            self.assertEqual(prepare_usb.removable_drives(), [Path('/media/usb')])

    def test_wizard_collects_options_in_shared_prompt_flow(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(prepare_usb, 'removable_drives', return_value=[]):
            prompt = mock.Mock(side_effect=[td, 'да', 'нет', '', 'invalid', '3.11', 'aarch64', '2.28'])
            options = prepare_usb.collect_options(prompt)
            self.assertEqual(options, (Path(td).resolve(), False, True, ('3.11',), 'aarch64', '2.28', False))
            self.assertIn('Укажите версии как 3.11', prompt.call_args_list[5].args[2][0])

    def test_wizard_can_select_all_or_multiple_python_versions(self):
        for raw, expected in [('все', prepare_usb.PYTHON_PRESETS), ('3.12, 3.10 3.12', ('3.12', '3.10'))]:
            with self.subTest(raw=raw):
                self.assertEqual(prepare_usb.choose_python_versions(mock.Mock(return_value=raw), 'Python'), expected)

    def test_wizard_declines_or_confirms_existing_bundle(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(prepare_usb, 'removable_drives', return_value=[]):
            drive = Path(td)
            root = drive / 'BOTYARA-GAMES'
            root.mkdir()
            launcher = root / 'launch.py'
            launcher.write_text('old')
            (root / 'keep.txt').touch()
            prompt = mock.Mock(side_effect=[td, ''])
            with mock.patch.object(prepare_usb, 'configure', side_effect=lambda: prepare_usb.collect_options(prompt)):
                self.assertEqual(prepare_usb.main(), 0)
            self.assertEqual(launcher.read_text(), 'old')
            self.assertIn('[y/N]', prompt.call_args.args[1])
            with self.assertRaises(FileExistsError):
                prepare_usb.prepare(drive, False, False)
            options = prepare_usb.collect_options(mock.Mock(side_effect=[td, 'да', 'нет', 'нет']))
            self.assertEqual(prepare_usb.prepare(*options), (root, []))
            self.assertTrue((root / 'keep.txt').is_file())
            self.assertEqual(launch.read_version(launcher), '2.3.6')

    def test_wizard_uses_text_without_curses(self):
        with mock.patch.object(prepare_usb, 'curses', None), \
             mock.patch.object(prepare_usb, 'removable_drives', return_value=[]), \
             mock.patch('builtins.input', return_value='q'), redirect_stdout(io.StringIO()) as out:
            self.assertIsNone(prepare_usb.configure())
        self.assertIn('01 / НОСИТЕЛЬ', out.getvalue())

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

    def test_pip_resolves_dependencies_using_target_python_markers(self):
        with tempfile.TemporaryDirectory() as td:
            project = Path(td)
            index = project / 'index'
            index.mkdir()
            old = write_wheel(index, 'old_dep')
            new = write_wheel(index, 'new_dep')
            app = write_wheel(index, 'demo_app',
                              'Requires-Dist: old-dep; python_version < "3.11"\n'
                              'Requires-Dist: new-dep; python_version >= "3.11"\n')
            (project / 'requirements.txt').write_text('demo-app; sys_platform == "linux"\n')
            for version, dependency in [('3.10', old), ('3.14', new)]:
                with self.subTest(version=version):
                    dest = project / version
                    command = prepare_usb.linux_wheel_command(project, dest, version, 'x86_64', '2.17')
                    result = subprocess.run(command + ['--no-index', '--find-links', str(index)],
                                            capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertEqual({wheel.name for wheel in dest.iterdir()}, {app, dependency})

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

    def test_prepare_multiple_versions_preserves_failed_and_unselected_bundles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            existing = root / 'BOTYARA-GAMES' / 'wheels' / 'game'
            for version in ('cp311', 'cp312', 'cp314'):
                (existing / version).mkdir(parents=True)
                (existing / version / 'old.whl').write_text('old')
            (existing / 'legacy.whl').touch()

            def clone(url, dest):
                dest.mkdir()
                (dest / 'run.py').write_text('import flask\n')
                return True, ''

            def download(cmd, **kwargs):
                version = cmd[cmd.index('--python-version') + 1]
                if version == '311':
                    raise subprocess.CalledProcessError(1, cmd)
                dest = Path(cmd[cmd.index('--dest') + 1])
                (dest / 'demo-1.0-py3-none-any.whl').touch()

            with mock.patch.object(launch, 'REPO_LIST', ['game']), \
                 mock.patch.object(launch, 'git_clone', side_effect=clone) as git_clone, \
                 mock.patch.object(prepare_usb.subprocess, 'run', side_effect=download) as pip, \
                 redirect_stdout(io.StringIO()):
                result, failures = prepare_usb.prepare(root, True, True, ('3.11', '3.12', '3.13'),
                                                        'x86_64', '2.17', overwrite=True)
            git_clone.assert_called_once()
            self.assertEqual(pip.call_count, 3)
            self.assertEqual(failures, ['game (Python 3.11)'])
            self.assertTrue((result / 'repos' / 'game' / 'run.py').exists())
            self.assertEqual((existing / 'cp311' / 'old.whl').read_text(), 'old')
            self.assertEqual((existing / 'cp314' / 'old.whl').read_text(), 'old')
            self.assertFalse((existing / 'cp312' / 'old.whl').exists())
            for version in ('cp312', 'cp313'):
                self.assertTrue((existing / version / 'demo-1.0-py3-none-any.whl').is_file())
            self.assertTrue((existing / 'legacy.whl').is_file())
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
            env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1',
                       GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_COUNT='1',
                       GIT_CONFIG_KEY_0='url.%s/.insteadOf' % upstream.as_uri(),
                       GIT_CONFIG_VALUE_0=github, GIT_ALLOW_PROTOCOL='file')
            env.pop('BOTYARA_REPOS', None)
            launcher = usb / 'launch.py'
            fixture = usb / 'remote_launch.py'
            source = launcher.read_text(encoding='utf-8') + """

if not os.environ.get('BOTYARA_REPOS'):
    REPO_LIST = REPOSITORIES

def _fetch_remote():
    data = (SCRIPT_DIR / 'remote_launch.py').read_text(encoding='utf-8')
    match = VERSION_RE.search(data)
    return (match.group(1), data) if match else (None, 'ошибка загрузки')
"""
            version = '__version__ = "%s"' % launch.__version__
            launcher.write_text(source.replace(version, '__version__ = "1.0.0"')
                                .replace('REPOSITORIES', "['unlisted']"), encoding='utf-8')
            new_source = source.replace('REPOSITORIES', "['existing', 'missing']")
            fixture.write_text(new_source, encoding='utf-8')

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
            self.assertEqual(launcher.read_text(encoding='utf-8'), new_source)
            self.assertIn('launch.py обновлён', result.stdout)
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

            fixture.write_text(new_source.replace(version, '__version__ = "1.0.0"'), encoding='utf-8')
            result = update(env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(launcher.read_text(encoding='utf-8'), new_source)

            for bad in ('offline', '__version__ = "99.0.0"\ndef broken('):
                with self.subTest(remote=bad):
                    fixture.write_text(bad, encoding='utf-8')
                    result = update(env)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('без изменений: 2', result.stdout)
                    self.assertEqual(launcher.read_text(encoding='utf-8'), new_source)
                    self.assertFalse(list(usb.glob('.launch-*.tmp')))

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

    def test_offline_bundle_missing_version_or_legacy_fallback(self):
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(launch, 'FLASH_WHEELS_DIR', Path(td)), \
             mock.patch.object(launch.subprocess, 'run', return_value=mock.Mock(stdout='3.13\n')) as run:
            root = Path(td) / 'game'
            (root / 'cp312').mkdir(parents=True)
            selected, error = launch.offline_wheel_bundle('game', 'venv-python')
            self.assertIsNone(selected)
            self.assertIn('Python 3.13', error)
            self.assertEqual(run.call_args.args[0][0], 'venv-python')
            (root / 'legacy.whl').touch()
            self.assertEqual(launch.offline_wheel_bundle('game', 'venv-python'), (root, ''))
            target = root / 'cp313'
            target.mkdir()
            self.assertEqual(launch.offline_wheel_bundle('game', 'venv-python'), (target, ''))

    def test_offline_install_real_wheel(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            flash = root / 'stick'
            project = root / 'installed' / 'game'
            project.mkdir(parents=True)
            (project / 'run.py').write_text('import test_usb_pkg\n')
            (project / 'requirements.txt').write_text('test-usb-pkg==1.0\n')
            root_wheels = flash / 'wheels' / 'game'
            wheel_dir = root_wheels / launch.wheel_bundle_tag('%d.%d' % sys.version_info[:2])
            wheel_dir.mkdir(parents=True)
            (root_wheels / 'bad-1.0-py3-none-any.whl').touch()  # старый набор не смешивается с выбранным
            write_wheel(wheel_dir, 'test_usb_pkg')
            with mock.patch.object(launch, 'FLASH_WHEELS_DIR', flash / 'wheels'), redirect_stdout(io.StringIO()):
                reg = {}
                self.assertTrue(launch.setup_project(project, reg, False))
            result = subprocess.run([reg['game']['python'], '-c', 'import test_usb_pkg; print(test_usb_pkg.answer)'],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.strip(), '42')


if __name__ == '__main__':
    unittest.main()
