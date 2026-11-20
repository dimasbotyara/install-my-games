import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import launch


class GearworksTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.project = Path(temp.name) / launch.GEARWORKS
        self.project.mkdir()
        (self.project / 'main.py').touch()
        self.req = self.project / 'requirements.txt'
        self.req.write_text('noise\n', encoding='utf-8')

    def test_runs_last_even_with_override(self):
        with patch.object(launch, 'REPO_LIST', [launch.GEARWORKS, 'b', 'a']):
            self.assertEqual(launch.ordered_repos(), ['b', 'a', launch.GEARWORKS])

    def test_failed_dependencies_do_not_fail_setup(self):
        reg = {}
        with patch.object(launch, 'ensure_venv', return_value=('venv-python', 'ok')), \
             patch.object(launch, 'install_dependencies', return_value=(False, 'no wheel for noise')):
            self.assertTrue(launch.setup_project(self.project, reg, False, interactive=False))
        self.assertEqual(reg[launch.GEARWORKS]['entry'], 'main.py')

    def test_ready_does_not_check_internet(self):
        with patch.object(launch, 'pip_install', return_value=(True, '')) as pip, \
             patch.object(launch, 'internet_ok') as internet:
            self.assertTrue(launch.gearworks_ready(self.project, 'venv-python'))
        pip.assert_called_once_with('venv-python', ['--dry-run', '--no-index', '-r', str(self.req)])
        internet.assert_not_called()

    def test_missing_dependencies_block_launch_offline(self):
        with patch.object(launch, 'pip_install', return_value=(False, 'missing noise')), \
             patch.object(launch, 'install_dependencies', return_value=(False, 'no wheel')), \
             patch.object(launch, 'internet_ok', return_value=False) as internet, \
             patch.object(launch, 'ensure_venv', return_value=('venv-python', 'ok')), \
             patch.object(launch, 'pause'), patch.object(launch.subprocess, 'Popen') as popen:
            game = {'path': str(self.project), 'entry': 'main.py'}
            self.assertFalse(launch.launch_detached(launch.GEARWORKS, game, {}))
        internet.assert_called_once_with(force=True)
        popen.assert_not_called()

    def test_online_fallback_allows_source_build(self):
        wheels = self.project / 'wheels'
        wheels.mkdir()
        with patch.object(launch, 'offline_wheel_bundle', return_value=(wheels, '')), \
             patch.object(launch, 'pip_install', side_effect=[(False, 'no wheel'), (True, '')]) as pip:
            self.assertEqual(launch.install_dependencies(self.project, 'venv-python', ['noise'], True),
                             (True, ''))
        self.assertIn('--only-binary=:all:', pip.call_args_list[0].args[1])
        pip.assert_called_with('venv-python', ['--prefer-binary', 'noise'])
