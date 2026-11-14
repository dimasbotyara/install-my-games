#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOTYARA GAMES — smoke tests.

Чистый stdlib (unittest), сеть не нужна, HOME не трогается —
все функции тестируются на временных папках.
"""

import io
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import launch  # noqa: E402


def make_game(parent, name="game", files=None):
    """Создаёт фейковую игру-проект. files: {имя: содержимое}."""
    d = parent / name
    d.mkdir(parents=True)
    for fname, content in (files or {"run.py": "print('hi')\n"}).items():
        (d / fname).write_text(content, encoding="utf-8")
    return d


class EntryPointDetection(unittest.TestCase):
    def test_run_beats_everything(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"app.py": "x", "main.py": "x", "run.py": "x"})
            self.assertEqual(launch.detect_entry(d), "run.py")

    def test_app_beats_main(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"app.py": "x", "main.py": "x"})
            self.assertEqual(launch.detect_entry(d), "app.py")

    def test_main_alone(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"main.py": "x"})
            self.assertEqual(launch.detect_entry(d), "main.py")

    def test_single_py_file(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"pong.py": "x"})
            self.assertEqual(launch.detect_entry(d), "pong.py")

    def test_ambiguous_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"a.py": "x", "b.py": "x"})
            self.assertIsNone(launch.detect_entry(d))

    def test_no_py_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"readme.md": "x"})
            self.assertIsNone(launch.detect_entry(d))


class DependencyDetection(unittest.TestCase):
    def test_stdlib_and_local_filtered(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={
                "main.py": "import os, sys\nimport pygame\nfrom PIL import Image\nimport helper\n",
                "helper.py": "MAGIC = 42\n",
            })
            self.assertEqual(launch.detect_imports(d), ["pillow", "pygame"])

    def test_no_deps(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"main.py": "import json, math\nfrom pathlib import Path\n"})
            self.assertEqual(launch.detect_imports(d), [])

    def test_venv_excluded_from_scan(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), files={"main.py": "import pygame\n"})
            planted = d / ".venv" / "lib"
            planted.mkdir(parents=True)
            (planted / "evil.py").write_text("import totally_unknown_thing\n", encoding="utf-8")
            self.assertEqual(launch.detect_imports(d), ["pygame"])


class Registry(unittest.TestCase):
    def setUp(self):
        self._old_dir, self._old_file = launch.PROJECTS_DIR, launch.REGISTRY_FILE
        self.tmp = tempfile.mkdtemp()
        launch.PROJECTS_DIR = Path(self.tmp)
        launch.REGISTRY_FILE = Path(self.tmp) / ".registry.json"

    def tearDown(self):
        launch.PROJECTS_DIR, launch.REGISTRY_FILE = self._old_dir, self._old_file
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_roundtrip(self):
        reg = {"pong": {"path": "/tmp/pong", "entry": "run.py", "python": "py"}}
        launch.save_registry(reg)
        self.assertEqual(launch.load_registry(), reg)

    def test_corrupt_json_gives_empty(self):
        launch.REGISTRY_FILE.write_text("{ это не json", encoding="utf-8")
        self.assertEqual(launch.load_registry(), {})

    def test_sync_autodetects_and_prunes(self):
        make_game(launch.PROJECTS_DIR, "pong", {"run.py": "x"})
        (launch.PROJECTS_DIR / ".hidden").mkdir()
        make_game(launch.PROJECTS_DIR, "not_a_game", {"readme.md": "x"})
        reg = launch.sync_registry()
        self.assertIn("pong", reg)
        self.assertNotIn("not_a_game", reg)
        self.assertEqual(reg["pong"]["entry"], "run.py")

    def test_sync_prunes_disappeared(self):
        launch.save_registry({"ghost": {"path": str(launch.PROJECTS_DIR / "ghost"),
                                        "entry": "main.py", "python": "py"}})
        reg = launch.sync_registry()
        self.assertNotIn("ghost", reg)

    def test_sync_picks_up_venv_python(self):
        g = make_game(launch.PROJECTS_DIR, "pong", {"run.py": "x"})
        venv_py = g / ".venv" / "bin" / "python"
        venv_py.parent.mkdir(parents=True)
        venv_py.write_text("#!/bin/sh\n", encoding="utf-8")
        reg = launch.sync_registry()
        self.assertEqual(reg["pong"]["python"], str(venv_py))


class GameStatus(unittest.TestCase):
    def test_missing_dir_is_red(self):
        col, _ = launch.game_status({"path": "/nonexistent/nope", "entry": "run.py"})
        self.assertEqual(col, "red")

    def test_no_entry_is_orange(self):
        with tempfile.TemporaryDirectory() as td:
            make_game(Path(td), "g")
            col, _ = launch.game_status({"path": str(Path(td) / "g"), "entry": None})
            self.assertEqual(col, "orange")

    def test_ready_is_green(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_game(Path(td), "g", {"run.py": "x"})
            (g / ".venv" / "bin").mkdir(parents=True)
            (g / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
            col, note = launch.game_status({"path": str(g), "entry": "run.py"})
            self.assertEqual(col, "green")

    def test_without_venv_is_yellow(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_game(Path(td), "g", {"run.py": "x"})
            col, _ = launch.game_status({"path": str(g), "entry": "run.py"})
            self.assertEqual(col, "yellow")


class UI(unittest.TestCase):
    def test_paint_disabled_returns_plain(self):
        old = launch.NO_COLOR
        launch.NO_COLOR = True
        try:
            self.assertEqual(launch.paint("hi", "red_b", "bold"), "hi")
        finally:
            launch.NO_COLOR = old

    def test_paint_enabled_adds_ansi(self):
        old = launch.NO_COLOR
        launch.NO_COLOR = False
        try:
            out = launch.paint("hi", "red_b", "bold")
            self.assertTrue(out.startswith("\033["))
            self.assertTrue(out.endswith("\033[0m"))
        finally:
            launch.NO_COLOR = old

    def test_width_ignores_ansi(self):
        painted = launch.paint("hello", "green_b", "bold")
        self.assertEqual(launch.width(painted), 5)

    def test_panel_box(self):
        old = launch.NO_COLOR
        launch.NO_COLOR = True
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                launch.panel(["строка один", "строка два"], title="ТЕСТ", accent="purple")
            out = buf.getvalue()
            for ch in ("╭", "╮", "│", "╰", "╯"):
                self.assertIn(ch, out)
            self.assertIn("ТЕСТ", out)
            self.assertIn("строка один", out)
        finally:
            launch.NO_COLOR = old

    def test_banner_lines_aligned(self):
        lines = launch.banner_lines()
        self.assertGreaterEqual(len(lines), 3)
        widths = [launch.width(l) for l in lines]
        self.assertEqual(len(set(widths)), 1)

    def test_bar_thresholds(self):
        old = launch.NO_COLOR
        launch.NO_COLOR = True
        try:
            self.assertIn("██", launch.bar(100))
            self.assertIn("░", launch.bar(0))
            self.assertIn("50%", launch.bar(50))
        finally:
            launch.NO_COLOR = old


class Versioning(unittest.TestCase):
    def test_vtuple(self):
        self.assertEqual(launch.vtuple("2.0.0"), (2, 0, 0))
        self.assertLess(launch.vtuple("2.0.0"), launch.vtuple("2.1.0"))
        self.assertLess(launch.vtuple("2.0.0"), launch.vtuple("10.0.0"))
        self.assertEqual(launch.vtuple("мусор"), (0,))

    def test_read_version(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "x.py"
            f.write_text('__version__ = "3.14.15"\n', encoding="utf-8")
            self.assertEqual(launch.read_version(f), "3.14.15")
            f.write_text("нет версии тут\n", encoding="utf-8")
            self.assertIsNone(launch.read_version(f))

    def test_repo_list_has_new_games(self):
        self.assertIn("gearworks-industrial-age", launch.REPO_LIST)
        self.assertIn("botyaragames", launch.REPO_LIST)

    def test_alias_line_matches_spec(self):
        self.assertEqual(
            launch.ALIAS_LINE,
            'alias dimasbotyara="python3 ~/.config/systemd-backup/launch.py"')


class SelfInstall(unittest.TestCase):
    def setUp(self):
        self._old_dir, self._old_script = launch.PROJECTS_DIR, launch.INSTALLED_SCRIPT
        self.tmp = tempfile.mkdtemp()
        launch.PROJECTS_DIR = Path(self.tmp)
        launch.INSTALLED_SCRIPT = Path(self.tmp) / "launch.py"

    def tearDown(self):
        launch.PROJECTS_DIR, launch.INSTALLED_SCRIPT = self._old_dir, self._old_script
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _read_installed(self):
        return launch.INSTALLED_SCRIPT.read_text(encoding="utf-8")

    def test_copies_self(self):
        launch.INSTALLED_SCRIPT.write_text("старая версия", encoding="utf-8")
        launch.self_install()
        self.assertIn("__version__ =", self._read_installed())

    def test_no_downgrade(self):
        """Если на компе уже новее (обновлено с GitHub) — не перезаписываем старым."""
        launch.INSTALLED_SCRIPT.write_text('__version__ = "99.0.0"\n', encoding="utf-8")
        launch.self_install()
        self.assertIn('99.0.0', self._read_installed())

    def test_upgrades_old(self):
        launch.INSTALLED_SCRIPT.write_text('__version__ = "0.0.1"\n', encoding="utf-8")
        launch.self_install()
        self.assertIn(launch.__version__, self._read_installed())


class AliasInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._patch = unittest.mock.patch.object(Path, "home", return_value=Path(self.tmp))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_alias_added_once(self):
        bashrc = Path(self.tmp) / ".bashrc"
        first = launch.install_alias()
        self.assertEqual(first[0][1], "добавлен")
        self.assertIn(launch.ALIAS_LINE, bashrc.read_text(encoding="utf-8"))
        second = launch.install_alias()
        self.assertEqual(second[0][1], "уже есть")
        # и не задублировался
        content = bashrc.read_text(encoding="utf-8")
        self.assertEqual(content.count("alias dimasbotyara"), 1)


class Auth(unittest.TestCase):
    def test_hash_is_64_hex(self):
        self.assertRegex(launch.AUTH_HASH, r"^[0-9a-f]{64}$")

    def test_auth_hash_pinned(self):
        """Хэш в коде зафиксирован — случайно не поменялся."""
        self.assertEqual(
            launch.AUTH_HASH,
            "674485607c066f34c1be917790bce9d4b120e87c0e2c5c9954c1da82982d4ab6")

    def test_hash_differs_per_password(self):
        self.assertNotEqual(launch.password_hash("a"), launch.password_hash("b"))
        self.assertNotEqual(launch.password_hash(""), launch.password_hash(" "))

    def test_salt_is_in_the_mix(self):
        """Хэш не должен быть голым sha256 от известного пароля — соль участвует."""
        import hashlib
        for guess in (b"qwerty", b"123456", b"password"):
            self.assertNotEqual(launch.AUTH_HASH, hashlib.sha256(guess).hexdigest())
        self.assertNotEqual(launch.AUTH_HASH,
                            hashlib.sha256(launch.AUTH_SALT.encode()).hexdigest())

    def test_verify_rejects_wrong_passwords(self):
        for wrong in ("", "wrong", "12345", "Qwerty", "qwerty ", "password"):
            self.assertFalse(launch.verify_password(wrong))

    def test_verify_mechanism(self):
        """Механика verify: True только на пароле, чей хэш в AUTH_HASH."""
        with unittest.mock.patch.object(launch, "AUTH_HASH",
                                        launch.password_hash("topsecret-test")):
            self.assertTrue(launch.verify_password("topsecret-test"))
            self.assertFalse(launch.verify_password("wrong"))


class SelectionParsing(unittest.TestCase):
    def test_space_separated(self):
        self.assertEqual(launch.parse_selection("1 2 3", 5), [1, 2, 3])

    def test_comma_no_spaces(self):
        self.assertEqual(launch.parse_selection("1,2,3", 5), [1, 2, 3])

    def test_comma_with_spaces(self):
        self.assertEqual(launch.parse_selection("1, 2, 3", 5), [1, 2, 3])

    def test_single_number(self):
        self.assertEqual(launch.parse_selection("4", 5), [4])

    def test_all_words(self):
        for word in ("все", "всё", "all", "*"):
            self.assertEqual(launch.parse_selection(word, 3), [1, 2, 3])

    def test_dedup_and_sort(self):
        self.assertEqual(launch.parse_selection("3 1 1 3", 5), [1, 3])

    def test_letters_rejected(self):
        self.assertIsNone(launch.parse_selection("1 x", 5))

    def test_out_of_range_rejected(self):
        self.assertIsNone(launch.parse_selection("6", 5))
        self.assertIsNone(launch.parse_selection("0", 5))

    def test_empty_rejected(self):
        self.assertIsNone(launch.parse_selection("", 5))
        self.assertIsNone(launch.parse_selection("   ", 5))


class AliasRemoval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._patch = unittest.mock.patch.object(Path, "home", return_value=Path(self.tmp))
        self._patch.start()

    def tearDown(self):
        self._patch.stop()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_remove_block_keeps_other_lines(self):
        bashrc = Path(self.tmp) / ".bashrc"
        bashrc.write_text("export EDITOR=vim\n\n%s\n%s\n\n# мой конфиг\n"
                          % (launch.ALIAS_MARKER, launch.ALIAS_LINE), encoding="utf-8")
        touched = launch.uninstall_alias()
        self.assertEqual(touched[0][1], "убран")
        content = bashrc.read_text(encoding="utf-8")
        self.assertNotIn("alias dimasbotyara", content)
        self.assertNotIn(launch.ALIAS_MARKER, content)
        self.assertIn("export EDITOR=vim", content)
        self.assertIn("# мой конфиг", content)

    def test_no_alias_reported(self):
        (Path(self.tmp) / ".bashrc").write_text("просто конфиг\n", encoding="utf-8")
        touched = launch.uninstall_alias()
        self.assertEqual(touched[0][1], "alias не найден")


class RepairGames(unittest.TestCase):
    def setUp(self):
        self._old_dir, self._old_file = launch.PROJECTS_DIR, launch.REGISTRY_FILE
        self.tmp = tempfile.mkdtemp()
        launch.PROJECTS_DIR = Path(self.tmp)
        launch.REGISTRY_FILE = Path(self.tmp) / ".registry.json"

    def tearDown(self):
        launch.PROJECTS_DIR, launch.REGISTRY_FILE = self._old_dir, self._old_file
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repair_rebuilds_venv(self):
        """Починка сносит .venv и собирает настоящий заново (без сети, без deps)."""
        g = make_game(launch.PROJECTS_DIR, "g", {"run.py": "print('hi')\n"})
        fake_py = g / ".venv" / "bin" / "python"
        fake_py.parent.mkdir(parents=True)
        fake_py.write_text("СЛОМАННЫЙ-СТАРЫЙ", encoding="utf-8")
        reg = {"g": {"path": str(g), "entry": "run.py", "python": str(fake_py)}}

        fixed = launch.repair_games(reg, ["g"], online=False)

        self.assertEqual(fixed, 1)
        self.assertTrue(fake_py.exists())
        self.assertNotEqual(fake_py.read_text(encoding="utf-8", errors="ignore"),
                            "СЛОМАННЫЙ-СТАРЫЙ")
        self.assertEqual(reg["g"]["python"], str(fake_py))

    def test_repair_skips_missing_folder(self):
        reg = {"ghost": {"path": str(launch.PROJECTS_DIR / "ghost"),
                         "entry": "run.py", "python": "py"}}
        self.assertEqual(launch.repair_games(reg, ["ghost"], online=False), 0)

    def test_repair_unknown_name(self):
        self.assertEqual(launch.repair_games({}, ["нет-такой"], online=False), 0)


class WipeTraces(unittest.TestCase):
    def setUp(self):
        self._old_dir, self._old_file, self._old_script = (
            launch.PROJECTS_DIR, launch.REGISTRY_FILE, launch.INSTALLED_SCRIPT)
        self.tmp = tempfile.mkdtemp()
        launch.PROJECTS_DIR = Path(self.tmp) / ".config" / "systemd-backup"
        launch.REGISTRY_FILE = launch.PROJECTS_DIR / ".registry.json"
        launch.INSTALLED_SCRIPT = launch.PROJECTS_DIR / "launch.py"
        self.home = tempfile.mkdtemp()
        self._home_patch = unittest.mock.patch.object(Path, "home", return_value=Path(self.home))
        self._home_patch.start()
        make_game(launch.PROJECTS_DIR, "g", {"run.py": "print('hi')\n"})
        launch.save_registry({"g": {"path": str(launch.PROJECTS_DIR / "g"),
                                    "entry": "run.py", "python": "py"}})
        launch.install_alias()

    def tearDown(self):
        self._home_patch.stop()
        launch.PROJECTS_DIR, launch.REGISTRY_FILE, launch.INSTALLED_SCRIPT = (
            self._old_dir, self._old_file, self._old_script)
        import shutil
        for d in (self.tmp, self.home):
            shutil.rmtree(d, ignore_errors=True)

    def test_cancelled_by_first_confirm(self):
        reg = launch.load_registry()
        with unittest.mock.patch.object(launch, "confirm", return_value=False):
            self.assertFalse(launch.wipe_all_traces(reg))
        self.assertTrue(launch.PROJECTS_DIR.exists())

    def test_cancelled_by_wrong_word(self):
        reg = launch.load_registry()
        with unittest.mock.patch.object(launch, "confirm", return_value=True), \
             unittest.mock.patch.object(launch, "ask", return_value="нет"):
            self.assertFalse(launch.wipe_all_traces(reg))
        self.assertTrue(launch.PROJECTS_DIR.exists())

    def test_wipe_removes_everything(self):
        reg = launch.load_registry()
        with unittest.mock.patch.object(launch, "confirm", return_value=True), \
             unittest.mock.patch.object(launch, "ask", return_value="УДАЛИТЬ"):
            self.assertTrue(launch.wipe_all_traces(reg))
        self.assertFalse(launch.PROJECTS_DIR.exists())
        self.assertFalse(reg)
        bashrc = Path(self.home) / ".bashrc"
        content = bashrc.read_text(encoding="utf-8")
        self.assertNotIn("alias dimasbotyara", content)
        self.assertNotIn(launch.ALIAS_MARKER, content)


class SmokeCLI(unittest.TestCase):
    """Самые настоящие смоки: реальный запуск CLI."""

    def _run(self, *args):
        return subprocess.run([sys.executable, "-I", str(REPO_ROOT / "launch.py"), *args],
                              capture_output=True, text=True, timeout=120,
                              env={"PATH": "/usr/bin:/bin", "HOME": tempfile.mkdtemp()})

    def test_version(self):
        r = self._run("--version")
        self.assertEqual(r.returncode, 0)
        self.assertIn(launch.__version__, r.stdout)

    def test_help(self):
        r = self._run("--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("--install", r.stdout)

    def test_specs(self):
        r = self._run("--specs")
        self.assertEqual(r.returncode, 0)
        self.assertIn("ХАРАКТЕРИСТИКИ", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
