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


class BannerGlyphs(unittest.TestCase):
    """Баннер должен читаться как BOTYARA, а не DOTYARA."""

    def test_b_is_not_a_d(self):
        b = launch._BANNER_LETTERS["B"]
        d = launch._BANNER_LETTERS.get("D") or ["██████╗ ", "██╔══██╗", "██║  ██║",
                                                "██║  ██║", "██████╔╝", "╚═════╝ "]
        self.assertNotEqual(b, d)

    def test_b_has_two_bowls(self):
        """У настоящей B верхняя и нижняя «чаши» одинаковые, посередине перемычка."""
        rows = [r.strip() for r in launch._BANNER_LETTERS["B"]]
        self.assertEqual(rows[4], rows[2])        # низ чаши = верх чаши
        self.assertIn("██╔══██╗", rows[1])
        self.assertIn("██╔══██╗", rows[3])        # нижняя чаша открывается так же

    def test_banner_colors_are_gruvbox_only(self):
        """Никакой радуги: только цвета из палитры gruvbox."""
        for color in launch._BANNER_COLORS:
            self.assertIn(color, launch.PAL)

    def test_banner_colors_are_calm(self):
        """Баннер не должен переливаться 7 цветами."""
        self.assertLessEqual(len(set(launch._BANNER_COLORS)), 3)


class MenuAlignment(unittest.TestCase):
    def _menu_lines(self):
        old = launch.NO_COLOR
        launch.NO_COLOR = True
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                launch.draw_menu({})
            return [launch.ANSI_RE.sub("", l) for l in buf.getvalue().splitlines()]
        finally:
            launch.NO_COLOR = old

    def test_second_column_aligned(self):
        """[a] / [r] / [u] — строго в одной колонке."""
        cols = []
        for line in self._menu_lines():
            for key in ("[a]", "[r]", "[u]"):
                if key in line:
                    cols.append(line.index(key))
        self.assertEqual(len(cols), 3)
        self.assertEqual(len(set(cols)), 1, "второй столбец разъехался: %r" % cols)

    def test_hotkeys_present(self):
        text = "\n".join(self._menu_lines())
        for key in ("[i]", "[a]", "[d]", "[r]", "[s]", "[u]", "[q]"):
            self.assertIn(key, text)


class PanelStyle(unittest.TestCase):
    def _panel(self, **kwargs):
        old = launch.NO_COLOR
        launch.NO_COLOR = False
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                launch.panel(["x"], **kwargs)
            return buf.getvalue()
        finally:
            launch.NO_COLOR = old

    def test_border_is_dim_gray(self):
        """Рамка — fg_dim, а не цвет акцента."""
        out = self._panel(title="Т", accent="red")
        dim_code = launch._fg_code("fg_dim")
        self.assertIn(dim_code + "╭─", out)
        self.assertIn(dim_code + "╰", out)

    def test_title_keeps_accent(self):
        out = self._panel(title="Т", accent="red_b")
        # заголовок красится «цвет + bold», поэтому проверяем префикс кода
        self.assertIn(launch._fg_code("red_b")[:-1], out)

    def test_all_accents_are_palette_colors(self):
        for accent in ("yellow", "red_b", "green", "aqua", "purple", "blue"):
            self.assertIn(accent, launch.PAL)


class UpdateCheck(unittest.TestCase):
    """Самообновление не должно спрашивать, когда всё и так свежее."""

    def setUp(self):
        self._saved = dict(launch._REMOTE)
        launch._REMOTE.update(version=None, data=None, ts=0.0)
        self._net = unittest.mock.patch.object(launch, "internet_ok", return_value=True)
        self._net.start()

    def tearDown(self):
        self._net.stop()
        launch._REMOTE.update(self._saved)

    def _with_remote(self, version):
        return unittest.mock.patch.object(
            launch, "_fetch_remote", return_value=(version, 'launch.py __version__ = "%s"' % version))

    def _quiet(self, fn, *a, **kw):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = fn(*a, **kw)
        return result, buf.getvalue()

    def test_same_version_is_silent(self):
        with self._with_remote(launch.__version__):
            remote, out = self._quiet(launch.check_update, quiet=True)
        self.assertIsNone(remote)
        self.assertEqual(out.strip(), "", "при последней версии лаунчер должен молчать")

    def test_older_remote_is_silent(self):
        with self._with_remote("0.0.1"):
            remote, out = self._quiet(launch.check_update, quiet=True)
        self.assertIsNone(remote)
        self.assertEqual(out.strip(), "")

    def test_newer_remote_is_reported(self):
        with self._with_remote("99.0.0"):
            remote, out = self._quiet(launch.check_update, quiet=True)
        self.assertEqual(remote, "99.0.0")
        self.assertIn("ОБНОВЛЕНИЕ", out)

    def test_loud_mode_explains_when_up_to_date(self):
        with self._with_remote(launch.__version__):
            _, out = self._quiet(launch.check_update, quiet=False)
        self.assertIn("последняя версия", out)

    def test_offline_quiet_is_silent(self):
        with unittest.mock.patch.object(launch, "internet_ok", return_value=False):
            remote, out = self._quiet(launch.check_update, quiet=True)
        self.assertIsNone(remote)
        self.assertEqual(out.strip(), "")

    def test_offline_loud_explains(self):
        with unittest.mock.patch.object(launch, "internet_ok", return_value=False):
            _, out = self._quiet(launch.check_update, quiet=False)
        self.assertIn("нет интернета", out)

    def test_self_update_asks_nothing_when_current(self):
        with self._with_remote(launch.__version__), \
             unittest.mock.patch.object(launch, "confirm") as conf:
            _, out = self._quiet(launch.self_update, confirm_first=True)
        conf.assert_not_called()
        self.assertEqual(out.strip(), "")

    def test_self_update_skips_write_on_cancel(self):
        with self._with_remote("99.0.0"), \
             unittest.mock.patch.object(launch, "confirm", return_value=False), \
             unittest.mock.patch.object(launch, "INSTALLED_SCRIPT",
                                        Path(tempfile.mkdtemp()) / "launch.py"):
            changed, _ = self._quiet(launch.self_update, confirm_first=True)
        self.assertFalse(changed)

    def test_updated_file_stays_executable(self):
        """os.replace приносит права временного файла — +x теряться не должен."""
        import os
        d = Path(tempfile.mkdtemp())
        target = d / "launch.py"
        target.write_text('__version__ = "1.0.0"\n', encoding="utf-8")
        with unittest.mock.patch.object(launch, "INSTALLED_SCRIPT", target), \
             unittest.mock.patch.object(launch, "SCRIPT_DIR", d), \
             unittest.mock.patch.object(launch, "check_update", return_value="9.9.9"), \
             unittest.mock.patch.object(launch, "_fetch_remote",
                                        return_value=("9.9.9", '__version__ = "9.9.9"\n')):
            changed, _ = self._quiet(launch.self_update)
        self.assertTrue(changed)
        self.assertEqual(launch.read_version(target), "9.9.9")
        self.assertTrue(os.access(target, os.X_OK), "файл должен остаться исполняемым")

    def test_remote_fetch_is_cached(self):
        launch._REMOTE.update(version=None, data=None, ts=0.0)
        calls = []

        def fake_urlopen(*a, **kw):
            calls.append(1)
            import io as _io
            return unittest.mock.MagicMock(
                __enter__=lambda s: _io.BytesIO(b'__version__ = "9.9.9"\n'),
                __exit__=lambda *a: False)

        with unittest.mock.patch.object(launch.urllib.request, "urlopen", fake_urlopen):
            launch._fetch_remote()
            launch._fetch_remote()
        self.assertEqual(len(calls), 1, "файл с GitHub должен качаться один раз за запуск")


class InternetCheck(unittest.TestCase):
    def setUp(self):
        launch._NET_CACHE.update(ok=None, ts=0.0)

    def tearDown(self):
        launch._NET_CACHE.update(ok=None, ts=0.0)

    def test_result_is_cached(self):
        calls = []

        def fake_conn(addr, timeout=0):
            calls.append(addr)
            return unittest.mock.MagicMock()

        with unittest.mock.patch.object(launch.socket, "create_connection", fake_conn), \
             unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertTrue(launch.internet_ok())
            self.assertTrue(launch.internet_ok())
            self.assertTrue(launch.internet_ok())
        self.assertEqual(len(calls), 1, "повторные проверки должны браться из кэша")

    def test_offline_is_cached_too(self):
        calls = []

        def dead_conn(addr, timeout=0):
            calls.append(addr)
            raise OSError("сети нет")

        with unittest.mock.patch.object(launch.socket, "create_connection", dead_conn), \
             unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(launch.internet_ok())
            self.assertFalse(launch.internet_ok())
        self.assertEqual(len(calls), 3, "три хоста один раз, потом кэш")

    def test_force_bypasses_cache(self):
        calls = []

        def dead_conn(addr, timeout=0):
            calls.append(addr)
            raise OSError("сети нет")

        with unittest.mock.patch.object(launch.socket, "create_connection", dead_conn), \
             unittest.mock.patch.dict("os.environ", {}, clear=True):
            launch.internet_ok()
            launch.internet_ok(force=True)
        self.assertEqual(len(calls), 6)

    def test_proxy_env_is_used(self):
        """При школьном прокси прямой TCP ничего не доказывает — идём через него."""
        env = {"HTTPS_PROXY": "http://proxy.school:3128"}
        with unittest.mock.patch.dict("os.environ", env, clear=True), \
             unittest.mock.patch.object(launch, "_origin_reachable", return_value=True) as reach, \
             unittest.mock.patch.object(launch.socket, "create_connection") as direct:
            self.assertTrue(launch.internet_ok())
        reach.assert_called_once_with("http://proxy.school:3128")
        direct.assert_not_called()

    def test_proxy_without_scheme(self):
        with unittest.mock.patch.dict("os.environ", {"HTTPS_PROXY": "proxy.school:3128"}, clear=True):
            self.assertEqual(launch._proxy_url(), "http://proxy.school:3128")

    def test_no_proxy_env(self):
        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(launch._proxy_url(), "")


class ImportScanLimit(unittest.TestCase):
    def test_huge_venv_does_not_eat_the_budget(self):
        """1200 файлов в .venv не должны мешать найти pygame в run.py."""
        with tempfile.TemporaryDirectory() as td:
            g = Path(td) / "game"
            lib = g / ".venv" / "lib"
            lib.mkdir(parents=True)
            for i in range(1200):
                (lib / ("m%04d.py" % i)).write_text("import requests\n", encoding="utf-8")
            (g / "run.py").write_text("import pygame\n", encoding="utf-8")
            self.assertEqual(launch.detect_imports(g), ["pygame"])

    def test_git_dir_is_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            g = Path(td) / "game"
            (g / ".git" / "hooks").mkdir(parents=True)
            (g / ".git" / "hooks" / "x.py").write_text("import requests\n", encoding="utf-8")
            (g / "run.py").write_text("import pygame\n", encoding="utf-8")
            self.assertEqual(launch.detect_imports(g), ["pygame"])


class GitPull(unittest.TestCase):
    """Обновление игр на реальных локальных репозиториях (без сети)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.root = Path(self.tmp)
        self.origin = self.root / "origin.git"
        self._git(self.root, "init", "-q", "--bare", str(self.origin))
        seed = self.root / "seed"
        self._git(self.root, "clone", "-q", str(self.origin), str(seed))
        self._git(seed, "config", "user.email", "t@t")
        self._git(seed, "config", "user.name", "t")
        (seed / "f").write_text("a", encoding="utf-8")
        self._git(seed, "add", "f")
        self._git(seed, "commit", "-qm", "c1")
        self._git(seed, "push", "-q", "origin", "HEAD:master")
        self.seed = seed

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)

    def _new_commit(self, marker):
        (self.seed / "f").write_text((self.seed / "f").read_text() + marker, encoding="utf-8")
        self._git(self.seed, "commit", "-qam", marker)
        self._git(self.seed, "push", "-q", "origin", "HEAD:master")

    def _clone(self, name, *extra):
        dest = self.root / name
        self._git(self.root, "clone", "-q", *extra, "file://" + str(self.origin), str(dest))
        return dest

    def test_shallow_clone_gets_new_commits(self):
        """Главный баг: клон --depth 1 не мог обновиться на новый коммит."""
        game = self._clone("game", "--depth", "1")
        self.assertTrue(launch._is_shallow(game))
        self._new_commit("c2")
        good, msg, changed = launch.git_pull(game)
        self.assertTrue(good, msg)
        self.assertTrue(changed)
        self.assertEqual(launch._head_sha(game),
                         self._git(self.origin, "rev-parse", "master").stdout.strip())

    def test_up_to_date_reports_no_changes(self):
        game = self._clone("game", "--depth", "1")
        good, msg, changed = launch.git_pull(game)
        self.assertTrue(good, msg)
        self.assertFalse(changed, "нечего обновлять — значит и врать «обновлён» нельзя")
        self.assertEqual(msg, "уже новейшая")

    def test_full_clone_still_works(self):
        game = self._clone("game_full")
        self._new_commit("c3")
        good, _, changed = launch.git_pull(game)
        self.assertTrue(good)
        self.assertTrue(changed)

    def test_not_a_repository(self):
        good, msg, changed = launch.git_pull(self.root)
        self.assertFalse(good)
        self.assertFalse(changed)


class InstallSummary(unittest.TestCase):
    def _summary(self, stats):
        old = launch.NO_COLOR
        launch.NO_COLOR = True
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                launch.install_summary(stats)
            return buf.getvalue()
        finally:
            launch.NO_COLOR = old

    def test_counts_fresh_games(self):
        out = self._summary({"new": [], "updated": [], "fresh": ["a", "b"],
                             "ok": [], "failed": []})
        self.assertIn("уже новейшие", out)
        self.assertIn("2", out)

    def test_all_fresh_message(self):
        out = self._summary({"new": [], "updated": [], "fresh": ["a"], "ok": [], "failed": []})
        self.assertIn("обновлять нечего", out)

    def test_nothing_fresh_no_silly_message(self):
        out = self._summary({"new": ["x"], "updated": [], "fresh": [], "ok": [], "failed": []})
        self.assertNotIn("обновлять нечего", out)

    def test_stats_without_fresh_key_still_work(self):
        """Совместимость: старый формат stats без ключа fresh."""
        out = self._summary({"new": [], "updated": [], "ok": [], "failed": []})
        self.assertIn("ИТОГИ УСТАНОВКИ", out)


class WebDetection(unittest.TestCase):
    """Веб-приложения запускаются в терминале, обычные игры — открепляются."""

    def test_flask_app_is_web(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "casino",
                          {"app.py": "from flask import Flask\napp = Flask(__name__)\n"})
            self.assertEqual(launch.detect_web(d), "Flask")

    def test_django_app_is_web(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "site", {"manage.py": "import django\n"})
            self.assertEqual(launch.detect_web(d), "Django")

    def test_pygame_game_is_not_web(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "pong", {"run.py": "import pygame\n"})
            self.assertIsNone(launch.detect_web(d))

    def test_pygame_with_background_server_is_not_web(self):
        """botyarapong: pygame рисует окно, werkzeug крутит мультиплеер в фоне.

        Это обычная игра с окном — её открепляем, а не держим в терминале.
        """
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "pong", {
                "run.py": "import pygame\n",
                "network.py": "from werkzeug.serving import make_server\n",
            })
            self.assertIsNone(launch.detect_web(d))

    def test_werkzeug_alone_is_not_a_web_app(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "tool", {"run.py": "import werkzeug\n"})
            self.assertIsNone(launch.detect_web(d))

    def test_venv_is_ignored(self):
        """Flask в .venv чужой игры не делает игру веб-приложением."""
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "game", {"run.py": "import pygame\n"})
            planted = d / ".venv" / "lib"
            planted.mkdir(parents=True)
            (planted / "x.py").write_text("from flask import Flask\n", encoding="utf-8")
            self.assertIsNone(launch.detect_web(d))

    def test_missing_folder(self):
        self.assertIsNone(launch.detect_web("/nonexistent/nope"))


class TerminalLaunch(unittest.TestCase):
    """Веб-приложение: лаунчер ждёт и НЕ открепляет процесс."""

    def _patches(self, fake_wait):
        return [
            unittest.mock.patch.object(launch, "Popen", create=True),
            unittest.mock.patch.object(launch.subprocess, "Popen"),
        ]

    def test_web_game_runs_in_terminal(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "casino", {"app.py": "from flask import Flask\n"})
            proc = unittest.mock.MagicMock()
            proc.wait.return_value = 0
            with unittest.mock.patch.object(launch.subprocess, "Popen", return_value=proc) as popen, \
                 unittest.mock.patch.object(launch, "pause"), \
                 unittest.mock.patch.object(launch, "clear"), \
                 redirect_stdout(io.StringIO()) as buf:
                result = launch._run_in_terminal("casino", "py", d, "app.py", "Flask")
            self.assertFalse(result, "после веб-игры лаунчер должен остаться живым")
            kwargs = popen.call_args.kwargs
            self.assertNotIn("start_new_session", kwargs,
                             "веб-приложение нельзя откреплять от терминала")
            self.assertIn("Flask", buf.getvalue())

    def test_ctrl_c_stops_server_and_keeps_launcher(self):
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "casino", {"app.py": "from flask import Flask\n"})
            proc = unittest.mock.MagicMock()
            # первый wait — Ctrl+C; после terminate сервер выходит штатно
            proc.wait.side_effect = [KeyboardInterrupt, 0]
            with unittest.mock.patch.object(launch.subprocess, "Popen", return_value=proc), \
                 unittest.mock.patch.object(launch, "clear"), \
                 redirect_stdout(io.StringIO()):
                result = launch._run_in_terminal("casino", "py", d, "app.py", "Flask")
            self.assertFalse(result, "после Ctrl+C лаунчер должен остаться живым")
            proc.terminate.assert_called_once()
            self.assertGreaterEqual(proc.wait.call_count, 2)   # дождались завершения

    def test_stubborn_server_gets_killed(self):
        """Сервер не реагирует на terminate — его добивают, лаунчер жив."""
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "casino", {"app.py": "from flask import Flask\n"})
            proc = unittest.mock.MagicMock()
            proc.wait.side_effect = [KeyboardInterrupt, subprocess.TimeoutExpired("x", 5), 0]
            with unittest.mock.patch.object(launch.subprocess, "Popen", return_value=proc), \
                 unittest.mock.patch.object(launch, "clear"), \
                 redirect_stdout(io.StringIO()):
                result = launch._run_in_terminal("casino", "py", d, "app.py", "Flask")
            self.assertFalse(result)
            proc.kill.assert_called_once()

    def test_game_launch_detaches_pygame(self):
        """Обычная игра по-прежнему уходит в свою сессию."""
        with tempfile.TemporaryDirectory() as td:
            d = make_game(Path(td), "pong", {"run.py": "import pygame\n"})
            proc = unittest.mock.MagicMock()
            proc.poll.return_value = None
            with unittest.mock.patch.object(launch.subprocess, "Popen", return_value=proc) as popen, \
                 unittest.mock.patch.object(launch, "clear"), \
                 unittest.mock.patch.object(launch.time, "sleep"), \
                 redirect_stdout(io.StringIO()):
                result = launch.launch_detached(
                    "pong", {"path": str(d), "entry": "run.py", "python": "py"}, {})
            self.assertTrue(result, "pygame-игра должна открепляться и закрывать лаунчер")
            self.assertTrue(popen.call_args.kwargs.get("start_new_session"))


class SessionAndFarewell(unittest.TestCase):
    def test_password_asked_once_per_run(self):
        """Вернулись из веб-игры в меню — пароль заново не спрашиваем."""
        old = dict(launch._AUTH_STATE)
        launch._AUTH_STATE["ok"] = False
        try:
            with unittest.mock.patch.object(launch, "password_hash", return_value="x"), \
                 unittest.mock.patch.object(launch, "AUTH_HASH", "x"), \
                 unittest.mock.patch.object(launch, "getpass") as gp, \
                 redirect_stdout(io.StringIO()):
                gp.getpass.return_value = "topsecret"
                self.assertTrue(launch.require_password())
                self.assertTrue(launch.require_password())
                self.assertTrue(launch.require_password())
            self.assertEqual(gp.getpass.call_count, 1,
                             "пароль должен спрашиваться один раз за запуск")
        finally:
            launch._AUTH_STATE.update(old)

    def test_failed_password_is_not_remembered(self):
        old = dict(launch._AUTH_STATE)
        launch._AUTH_STATE["ok"] = False
        try:
            with unittest.mock.patch.object(launch, "verify_password", return_value=False), \
                 unittest.mock.patch.object(launch, "getpass") as gp, \
                 unittest.mock.patch.object(launch.time, "sleep"), \
                 redirect_stdout(io.StringIO()):
                gp.getpass.return_value = "wrong"
                self.assertFalse(launch.require_password())
            self.assertFalse(launch._AUTH_STATE["ok"])
            self.assertGreater(gp.getpass.call_count, 1)
        finally:
            launch._AUTH_STATE.update(old)


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
