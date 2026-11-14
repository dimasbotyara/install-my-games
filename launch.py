#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BOTYARA GAMES — единственный скрипт: установщик + лаунчер игр для школьных
линукс-компов (ALT Linux Education). Живёт на флешке, ставит игры в
~/.config/systemd-backup, сам находит точки входа и зависимости, ведёт реестр,
показывает характеристики ПК и умеет обновлять сам себя с GitHub.

Домашним ПК не место. Школе — самое то.
"""

import getpass
import hashlib
import hmac
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "2.2.0"

# ============================== НАСТРОЙКИ ==============================

SCRIPT_REPO = "dimasbotyara/install-my-games"   # репозиторий самого скрипта
GH_USER = "dimasbotyara"

# Игры можно переопределить для теста: BOTYARA_REPOS="repo1,repo2"
REPO_LIST = [
    # топ-выбор
    "botyarapong",
    "botyarajump",
    "botyaraclick",
    "botyaraTD",
    "botyaraRTS",
    "pygame-arkanoid",
    "pygame-slide-survivors",
    # дополнительные
    "botyaracities-ru",
    "botyaracasino",
    "botyaraexchange",
    # новинки
    "gearworks-industrial-age",
    "botyaragames",
]
if os.environ.get("BOTYARA_REPOS"):
    REPO_LIST = [r.strip() for r in os.environ["BOTYARA_REPOS"].split(",") if r.strip()]

PROJECTS_DIR = Path.home() / ".config" / "systemd-backup"
REGISTRY_FILE = PROJECTS_DIR / ".registry.json"
INSTALLED_SCRIPT = PROJECTS_DIR / "launch.py"
SCRIPT_DIR = Path(__file__).resolve().parent
FLASH_REPOS_DIR = SCRIPT_DIR / "repos"      # оффлайн-копии игр на флешке

ALIAS_NAME = "dimasbotyara"
ALIAS_LINE = 'alias %s="python3 ~/.config/systemd-backup/launch.py"' % ALIAS_NAME
ALIAS_MARKER = "# BOTYARA GAMES launcher"

# --- пароль лаунчера: в коде только хэш с солью, сам пароль не хранится ---
AUTH_SALT = "botyara-games::hidden-launcher::v2"
AUTH_HASH = "674485607c066f34c1be917790bce9d4b120e87c0e2c5c9954c1da82982d4ab6"
AUTH_ATTEMPTS = 3

# иерархия точек входа: run.py > app.py > main.py
ENTRY_PRIORITY = ["run.py", "app.py", "main.py"]

# import name -> pip name (остальные ставятся как есть)
PIP_NAME_MAP = {
    "PIL": "pillow",
    "cv2": "opencv-python",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dotenv": "python-dotenv",
    "Crypto": "pycryptodome",
}

# запасной список stdlib для python < 3.10 (нет sys.stdlib_module_names)
FALLBACK_STDLIB = set("""
__future__ abc argparse array ast asyncio atexit base64 binascii bisect builtins
bz2 calendar cmath cmd code codecs collections colorsys compileall concurrent
configparser contextlib contextvars copy copyreg cProfile csv ctypes curses dataclasses
datetime dbm decimal difflib dis doctest email ensurepip enum errno faulthandler
fileinput fnmatch fractions ftplib functools gc getopt getpass gettext glob graphlib
gzip hashlib heapq hmac html http idlelib importlib inspect io ipaddress itertools json
keyword linecache locale logging lzma marshal math mimetypes mmap multiprocessing
netrc numbers operator os pathlib pickle pickletools pkgutil platform plistlib poplib
posixpath pprint profile pstats pty pwd py_compile pyclbr pydoc queue quopri random re
readline reprlib runpy sched secrets select selectors shelve shlex shutil signal site
smtpd smtplib sndhdr socket socketserver sqlite3 ssl stat statistics string stringprep
struct subprocess symtable sys sysconfig tarfile telnetlib tempfile termios textwrap
threading time timeit tkinter token tokenize tomllib trace tracemalloc tty turtle
turtledemo types typing unicodedata unittest urllib uuid venv warnings wave weakref
webbrowser wsgiref xml xmlrpc zipapp zipfile zipimport zlib zoneinfo
""".split())

IMPORT_RE = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_][A-Za-z0-9_]*)", re.M)
ANSI_RE = re.compile(r"\033\[[0-9;]*m")
VERSION_RE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.M)

# ============================== ГРУВБОК ==============================

IS_TTY = sys.stdout.isatty()
NO_COLOR = not IS_TTY or "NO_COLOR" in os.environ
TRUECOLOR = IS_TTY and os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")

# имя -> (gruvbox truecolor, ближайший 256-color)
PAL = {
    "fg":       ((235, 219, 178), 223),
    "fg_dim":   ((146, 131, 116), 245),
    "red":      ((204, 36, 29), 124),
    "red_b":    ((251, 73, 52), 203),
    "green":    ((152, 151, 26), 100),
    "green_b":  ((184, 187, 38), 142),
    "yellow":   ((215, 153, 33), 136),
    "yellow_b": ((250, 189, 35), 214),
    "blue":     ((69, 133, 136), 66),
    "blue_b":   ((131, 165, 152), 109),
    "purple":   ((177, 98, 134), 132),
    "purple_b": ((211, 134, 155), 175),
    "aqua":     ((104, 157, 106), 72),
    "aqua_b":   ((142, 192, 124), 108),
    "orange":   ((214, 93, 14), 166),
    "orange_b": ((254, 128, 25), 208),
}

def _fg_code(name):
    tc, c256 = PAL[name]
    if TRUECOLOR:
        return "\033[38;2;%d;%d;%dm" % tc
    return "\033[38;5;%dm" % c256

STYLE_CODES = {"bold": "1", "dim": "2", "italic": "3", "underline": "4", "reverse": "7"}

def paint(text, *styles):
    """Красит текст в gruvbox-цвета; без терминала возвращает как есть."""
    if NO_COLOR or not styles:
        return text
    codes = []
    for s in styles:
        if s in PAL:
            codes.append(_fg_code(s).replace("\033[", "").rstrip("m"))
        elif s in STYLE_CODES:
            codes.append(STYLE_CODES[s])
    if not codes:
        return text
    return "\033[%sm%s\033[0m" % (";".join(codes), text)

def width(s):
    """Видимая ширина строки (без ANSI-кодов)."""
    return len(ANSI_RE.sub("", s))

def term_w():
    return max(shutil.get_terminal_size().columns, 40)

def clear():
    if IS_TTY:
        print("\033[H\033[2J\033[3J", end="")
    else:
        print()

def hr(char="─", color="fg_dim"):
    print(paint(char * min(term_w(), 64), color))

# ANSI Shadow font
_BANNER_LETTERS = {
    "B": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "Y": ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚██╔╝  ", "   ██║   ", "   ╚═╝   "],
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "R": [" ██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
}
_SMALL_LETTERS = {
    "B": ["╔╗ ", "╠╩╗", "╚═╝"], "O": ["╔═╗", "║ ║", "╚═╝"], "T": ["╔═╗", " ║ ", " ╩ "],
    "Y": ["╦╔═", "╠╩╗", "╩ ╩"], "A": ["╔═╗", "╠═╣", "╩ ╩"], "R": ["╦═╗", "╠╦╝", "╩╚═"],
}
_BANNER_COLORS = ["red_b", "orange_b", "yellow_b", "green_b", "aqua_b", "blue_b", "purple_b"]

def banner_lines():
    """Большой баннер, если влезает, иначе маленький."""
    font = _BANNER_LETTERS if term_w() >= 62 else _SMALL_LETTERS
    rows_n = len(_BANNER_LETTERS["B"]) if font is _BANNER_LETTERS else len(_SMALL_LETTERS["B"])
    # каждая буква выровнена по своей максимальной ширине (у R нижние строки короче)
    padded = {ch: [r.ljust(max(len(r) for r in rows)) for r in rows] for ch, rows in font.items()}
    return [" ".join(padded[ch][i] for ch in "BOTYARA") for i in range(rows_n)]

def show_banner():
    for i, line in enumerate(banner_lines()):
        print(paint(line, _BANNER_COLORS[i % len(_BANNER_COLORS)], "bold"))
    print(paint("  games installer & launcher  ·  v%s  ·  ALT Linux edition" % __version__,
                "fg_dim", "italic"))
    hr()

def panel(lines, title=None, accent="blue"):
    """Рамочка вокруг контента. lines: список строк (могут быть крашеные)."""
    cw = max([width(l) for l in lines] + [20] + ([width(title) + 4] if title else []))
    inner = cw + 2
    b = paint
    if title and inner - width(title) - 3 >= 1:
        fill = inner - width(title) - 3
        print(b("╭─", accent) + b(" " + title + " ", accent, "bold")
              + b("─" * fill, accent) + b("╮", accent))
    else:
        print(b("╭", accent) + b("─" * inner, accent) + b("╮", accent))
    for l in lines:
        pad = cw - width(l)
        print(b("│", accent) + " " + l + " " * pad + " " + b("│", accent))
    print(b("╰", accent) + b("─" * inner, accent) + b("╯", accent))

def kv(label, value, w=15):
    return paint("  " + label.ljust(w), "fg_dim") + value

def bar(pct, w=20):
    pct = max(0.0, min(100.0, pct))
    filled = int(round(pct / 100 * w))
    col = "green_b" if pct < 60 else ("yellow_b" if pct < 85 else "red_b")
    return paint("█" * filled, col) + paint("░" * (w - filled), "fg_dim") + paint(" %4.0f%%" % pct, "bold")

# ============================== МЕЛКИЕ ХЕЛПЕРЫ ==============================

def ask(prompt, default=None):
    try:
        raw = input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    raw = raw.strip()
    if raw == "" and default is not None:
        return default
    return raw

def confirm(prompt, default=True):
    d = "Y/n" if default else "y/N"
    raw = ask(paint("  › ", "aqua_b") + prompt + paint(" [%s] " % d, "fg_dim"), default=None)
    if raw is None:
        return default
    if raw == "":
        return default
    return raw[:1].lower() in ("y", "д")

def pause(msg="Enter — вернуться в меню"):
    ask(paint("  · ", "fg_dim") + paint(msg, "fg_dim"))

def ok(msg):    print(paint("  ✔ ", "green_b", "bold") + msg)
def warn(msg): print(paint("  ⚠ ", "yellow_b", "bold") + msg)
def err(msg):  print(paint("  ✘ ", "red_b", "bold") + msg)
def info(msg): print(paint("  ▸ ", "blue_b") + msg)
def dim(msg):  print(paint("    " + msg, "fg_dim"))

def vtuple(v):
    try:
        return tuple(int(x) for x in re.findall(r"\d+", v)[:3]) or (0,)
    except Exception:
        return (0,)

def read_version(path):
    try:
        m = VERSION_RE.search(Path(path).read_text(encoding="utf-8", errors="ignore"))
        return m.group(1) if m else None
    except Exception:
        return None

# ============================== ПАРОЛЬ ==============================

def password_hash(pw):
    """Соль + SHA-256: готовый хэш не гуглится и в радужных таблицах не ищется."""
    return hashlib.sha256((AUTH_SALT + ":" + pw).encode("utf-8")).hexdigest()

def verify_password(pw):
    """Сравнение за постоянное время, чтобы не подсказывать угадавшим часть хэша."""
    return hmac.compare_digest(password_hash(pw), AUTH_HASH)

def require_password():
    """Вход по паролю. Ввод не отображается (getpass). Неверный — 3 попытки."""
    for attempt in range(1, AUTH_ATTEMPTS + 1):
        print(paint("  🔒 ", "yellow_b", "bold")
              + paint("скрытный лаунчер — введи пароль (попытка %d/%d)" % (attempt, AUTH_ATTEMPTS),
                      "fg_dim"))
        try:
            pw = getpass.getpass(paint("  › ", "aqua_b", "bold"))
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if pw and verify_password(pw):
            ok("доступ разрешён")
            return True
        warn("неа")
        time.sleep(0.8)
    err("доступ запрещён. до встречи 🕵️")
    return False

# ============================== СЕТЬ ==============================

def internet_ok(timeout=2.5):
    """Быстрая проверка: сначала IP-адреса (без DNS), потом github.com."""
    for host, port in (("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53), ("github.com", 443)):
        try:
            s = socket.create_connection((host, port), timeout=timeout)
            s.close()
            return True
        except OSError:
            continue
    return False

# ============================== РЕЕСТР ==============================

def load_registry():
    if not REGISTRY_FILE.exists():
        return {}
    try:
        data = json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_registry(reg):
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")

def detect_entry(project):
    """run.py > app.py > main.py; если нет — единственный .py в корне; иначе None."""
    for name in ENTRY_PRIORITY:
        if (project / name).is_file():
            return name
    pyfiles = sorted(p.name for p in project.glob("*.py") if p.is_file())
    if len(pyfiles) == 1:
        return pyfiles[0]
    return None

def choose_entry(project):
    """Интерактивный выбор точки входа (когда авто-детект не сработал)."""
    pyfiles = sorted(p.name for p in project.glob("*.py") if p.is_file())
    if not pyfiles:
        return None
    print(paint("  .py файлы в корне:", "fg_dim"))
    for i, name in enumerate(pyfiles, 1):
        print(paint("    [%d] " % i, "fg_dim") + name)
    raw = ask(paint("  › ", "aqua_b") + "Какой запускать? (номер/имя, Enter — отложить): ")
    if not raw:
        return None
    if raw.isdigit() and 1 <= int(raw) <= len(pyfiles):
        return pyfiles[int(raw) - 1]
    if raw in pyfiles:
        return raw
    return None

def detect_imports(project):
    """Сканирует .py на import-ы, выкидывает stdlib и локальные модули,
    маппит имена типа PIL -> pillow. Возвращает pip-имена."""
    stdlib = getattr(sys, "stdlib_module_names", None) or FALLBACK_STDLIB
    mods = set()
    count = 0
    for p in project.rglob("*.py"):
        count += 1
        if count > 400:
            break
        parts = set(p.parts)
        if ".venv" in parts or ".git" in parts:
            continue
        try:
            mods.update(IMPORT_RE.findall(p.read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            continue
    local = {q.stem for q in project.glob("*.py") if q.is_file()}
    try:
        for q in project.iterdir():
            if q.is_dir() and (q / "__init__.py").exists():
                local.add(q.name)
    except Exception:
        pass
    deps = set()
    for m in mods:
        if m in stdlib or m in local:
            continue
        deps.add(PIP_NAME_MAP.get(m, m))
    return sorted(deps)

def sync_registry(reg=None, quiet=False):
    """Автодополнение реестра: добавляет найденные игры, чистит удалённые,
    обновляет путь до venv-питона."""
    changed = False
    if reg is None:
        reg = load_registry()
    if PROJECTS_DIR.exists():
        for d in sorted(PROJECTS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if not any(d.glob("*.py")):
                continue
            if d.name not in reg:
                reg[d.name] = {
                    "path": str(d),
                    "entry": detect_entry(d),
                    "python": str(d / ".venv" / "bin" / "python"),
                }
                changed = True
                if not quiet:
                    ok("реестр: добавлена %s" % d.name)
    for name in list(reg.keys()):
        item = reg[name]
        p = Path(item.get("path", ""))
        if not p.exists() or not any(p.glob("*.py")):
            del reg[name]
            changed = True
            if not quiet:
                warn("реестр: %s исчезла — убираю" % name)
            continue
        venv_py = p / ".venv" / "bin" / "python"
        want_py = str(venv_py) if venv_py.exists() else sys.executable
        if item.get("python") != want_py:
            item["python"] = want_py
            changed = True
    if changed:
        save_registry(reg)
    return reg

def game_status(info):
    """(цвет точки, подпись) — готовность игры к запуску."""
    path = Path(info.get("path", ""))
    entry = info.get("entry")
    if not path.exists() or not any(path.glob("*.py")):
        return "red", "папка исчезла"
    if not entry:
        return "orange", "не настроено"
    if not (path / entry).is_file():
        return "red", "%s пропал" % entry
    if (path / ".venv" / "bin" / "python").exists():
        return "green", entry
    return "yellow", entry + " (без venv)"

def parse_selection(raw, count):
    """'1 2 3' / '1,2,3' / '1, 2, 3' / '4' / 'все' -> отсортированные номера.

    Возвращает None, если ввод кривой (буквы, выход за диапазон, пусто)."""
    low = raw.strip().lower()
    if low in ("все", "всё", "all", "*"):
        return list(range(1, count + 1))
    nums = []
    for part in re.split(r"[,\s]+", low):
        if not part:
            continue
        if not part.isdigit():
            return None
        n = int(part)
        if not (1 <= n <= count):
            return None
        if n not in nums:
            nums.append(n)
    return sorted(nums) if nums else None

# ============================== УСТАНОВКА ==============================

def ensure_venv(project):
    """Создаёт .venv. Возвращает (python-путь|None, сообщение)."""
    venv = project / ".venv"
    py = venv / "bin" / "python"
    if py.exists():
        return py, "уже есть"
    try:
        r = subprocess.run([sys.executable, "-m", "venv", str(venv)],
                           capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and py.exists():
            return py, "создан"
    except Exception:
        pass
    # фоллбэк: без pip (ensurepip может отсутствовать)
    try:
        r = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and py.exists():
            return py, "создан (без pip)"
    except Exception:
        pass
    return None, "не создался (см. apt-get install python3-module-pip python3-module-venv)"

def pip_install(py_bin, args):
    try:
        r = subprocess.run([str(py_bin), "-m", "pip", "install", "--disable-pip-version-check",
                            "-q", *args], capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            return True, ""
        tail = [l for l in r.stderr.strip().splitlines() if l.strip()][-2:]
        return False, " / ".join(tail)
    except Exception as e:
        return False, str(e)

def find_flash_repos():
    """Оффлайн-копии игр рядом со скриптом (папка repos/ на флешке)."""
    found = {}
    if FLASH_REPOS_DIR.is_dir():
        for d in FLASH_REPOS_DIR.iterdir():
            if d.is_dir() and any(d.glob("*.py")):
                found[d.name] = d
    return found

def git_clone(url, dest):
    try:
        r = subprocess.run(["git", "clone", "--depth", "1", "--quiet", url, str(dest)],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            return True, ""
        tail = [l for l in r.stderr.strip().splitlines() if l.strip()][-1:]
        return False, tail[0] if tail else "неизвестная ошибка"
    except Exception as e:
        return False, str(e)

def git_pull(dest):
    try:
        r = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only", "--depth", "1", "-q"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            return True, "обновлён"
        # неглубокая копия могла запутать git — пробуем без --depth
        r = subprocess.run(["git", "-C", str(dest), "pull", "--ff-only", "-q"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            return True, "обновлён"
        if "not possible" in (r.stderr or "") or "diverging" in (r.stderr or ""):
            return False, "ветка разошлась"
        return False, "нет сети или ошибка git"
    except Exception as e:
        return False, str(e)

def setup_project(project, reg, online, interactive=True):
    """venv + зависимости + точка входа для одной игры. Возвращает True если ок."""
    name = project.name
    print(paint("▸ " + name, "orange_b", "bold"))

    # --- точка входа ---
    entry = reg.get(name, {}).get("entry")
    src = "реестр"
    if not entry or not (project / entry).is_file():
        entry = detect_entry(project)
        src = "авто"
    if entry is None:
        pyfiles = sorted(p.name for p in project.glob("*.py") if p.is_file())
        if not pyfiles:
            dim("нет .py файлов — пропускаю")
            return False
        if interactive:
            print(kv("точка входа", paint("не найдена — нужен выбор", "yellow_b")))
            entry = choose_entry(project)
            src = "вручную"
            if entry is None:
                dim("отложено — настроишь в меню")
        else:
            dim("точка входа не ясна (%d файлов) — настроишь в меню" % len(pyfiles))
    else:
        print(kv("точка входа", paint(entry, "green_b") + paint(" (%s)" % src, "fg_dim")))

    # --- зависимости ---
    deps = []
    req = project / "requirements.txt"
    if req.exists():
        deps = ["-r", str(req)]
        print(kv("зависимости", paint("requirements.txt", "aqua_b")))
    else:
        deps = detect_imports(project)
        print(kv("зависимости", paint(", ".join(deps) if deps else "не нужны (чистый stdlib)", "aqua_b")
                + paint(" (авто)", "fg_dim")))

    # --- venv ---
    py_bin, note = ensure_venv(project)
    print(kv("venv", paint(note, "green_b" if py_bin else "red_b")))
    if py_bin is None:
        reg[name] = {"path": str(project), "entry": entry, "python": sys.executable}
        return entry is not None

    # --- установка зависимостей ---
    if deps:
        if not online:
            warn("нет сети — пакеты не ставились, запусти установку при интернете")
        else:
            pip_ok, pip_err = pip_install(py_bin, deps)
            if pip_ok:
                ok("pip: установлено/обновлено")
            else:
                err("pip: %s" % (pip_err or "ошибка"))

    reg[name] = {"path": str(project), "entry": entry, "python": str(py_bin)}
    ok("готово")
    return True

def install_games(online, reg, interactive=True):
    """Клонирует/обновляет все игры из REPO_LIST и настраивает их."""
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    flash = find_flash_repos()
    stats = {"new": [], "updated": [], "ok": [], "failed": []}

    if flash:
        info("на флешке найдены оффлайн-копии: %s" % ", ".join(sorted(flash)))

    for repo in REPO_LIST:
        dest = PROJECTS_DIR / repo
        print()
        if dest.is_dir() and (dest / ".git").is_dir():
            if online:
                good, msg = git_pull(dest)
                if good:
                    ok("%s: %s" % (repo, msg))
                    stats["updated"].append(repo)
                else:
                    err("%s: не обновился (%s)" % (repo, msg))
                    stats["failed"].append(repo)
            else:
                dim("%s: есть, но без сети не обновить" % repo)
        elif dest.is_dir():
            warn("%s: папка есть, но не git — не трогаю" % repo)
        elif online:
            info("клонирую github.com/%s/%s ..." % (GH_USER, repo))
            good, msg = git_clone("https://github.com/%s/%s.git" % (GH_USER, repo), dest)
            if good:
                ok("%s: склонирован" % repo)
                stats["new"].append(repo)
            elif repo in flash:
                warn("git не смог (%s) — копирую с флешки" % msg)
                if dest.exists():
                    shutil.rmtree(dest, ignore_errors=True)
                shutil.copytree(flash[repo], dest)
                ok("%s: скопирован с флешки" % repo)
                stats["new"].append(repo)
            else:
                err("%s: не скачался (%s)" % (repo, msg))
                stats["failed"].append(repo)
        elif repo in flash:
            info("%s: копирую с флешки (оффлайн)" % repo)
            shutil.copytree(flash[repo], dest)
            ok("скопирован")
            stats["new"].append(repo)
        else:
            err("%s: нет ни сети, ни оффлайн-копии на флешке" % repo)
            stats["failed"].append(repo)
            continue

        if dest.is_dir() and any(dest.glob("*.py")):
            if setup_project(dest, reg, online, interactive):
                stats["ok"].append(repo)
        else:
            reg.pop(repo, None)

    save_registry(reg)
    return stats

def install_summary(stats):
    print()
    lines = [
        kv("новые", paint(str(len(stats["new"])), "green_b")),
        kv("обновлённые", paint(str(len(stats["updated"])), "blue_b")),
        kv("настроены", paint(str(len(stats["ok"])), "green_b")),
        kv("ошибки", paint(str(len(stats["failed"])), "red_b" if stats["failed"] else "green_b")),
    ]
    if stats["failed"]:
        lines.append(paint("  " + ", ".join(stats["failed"]), "red"))
    panel(lines, title="ИТОГИ УСТАНОВКИ", accent="purple")

# ============================== ALIAS / САМОУСТАНОВКА ==============================

def install_alias():
    """Добавляет alias в ~/.bashrc (и ~/.zshrc, если есть). Возвращает список."""
    touched = []
    rcs = [Path.home() / ".bashrc"]
    zshrc = Path.home() / ".zshrc"
    if zshrc.exists():
        rcs.append(zshrc)
    for rc in rcs:
        try:
            text = rc.read_text(encoding="utf-8", errors="ignore") if rc.exists() else ""
        except Exception:
            continue
        if ("alias %s" % ALIAS_NAME) in text:
            touched.append((rc, "уже есть"))
            continue
        try:
            with rc.open("a", encoding="utf-8") as f:
                if text and not text.endswith("\n"):
                    f.write("\n")
                f.write("\n%s\n%s\n" % (ALIAS_MARKER, ALIAS_LINE))
            touched.append((rc, "добавлен"))
        except Exception as e:
            touched.append((rc, "не вышло: %s" % e))
    return touched

def uninstall_alias():
    """Вычищает alias-блок из rc-файлов. Возвращает [(rc, что сделали)]."""
    touched = []
    for rc in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        if not rc.exists():
            continue
        try:
            lines = rc.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception as e:
            touched.append((rc, "не прочитался: %s" % e))
            continue
        kept = [l for l in lines
                if l.strip() != ALIAS_MARKER
                and not l.strip().startswith("alias %s=" % ALIAS_NAME)]
        if len(kept) == len(lines):
            touched.append((rc, "alias не найден"))
            continue
        try:
            rc.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            touched.append((rc, "убран"))
        except Exception as e:
            touched.append((rc, "не записался: %s" % e))
    return touched

def self_install():
    """Копирует себя в ~/.config/systemd-backup/launch.py (без даунгрейда)."""
    me = Path(__file__).resolve()
    if me == INSTALLED_SCRIPT.resolve():
        return
    if INSTALLED_SCRIPT.exists():
        old = read_version(INSTALLED_SCRIPT)
        if old and vtuple(old) > vtuple(__version__):
            info("на компе уже новее (v%s с GitHub) — не перезаписываю" % old)
            return
    try:
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(me, INSTALLED_SCRIPT)
        os.chmod(INSTALLED_SCRIPT, 0o755)
        ok("скрипт установлен: %s" % INSTALLED_SCRIPT)
    except Exception as e:
        err("не смог скопировать себя: %s" % e)

# ============================== САМООБНОВЛЕНИЕ ==============================

def self_update():
    """Качает свежий launch.py с GitHub raw и подменяет установленную копию."""
    print()
    if not internet_ok():
        err("нет интернета — обновление недоступно")
        return
    url = "https://raw.githubusercontent.com/%s/main/launch.py" % SCRIPT_REPO
    info("проверяю %s ..." % SCRIPT_REPO)
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            err("файла нет: %s" % url)
            dim("запушь репозиторий %s (ветка main), тогда самообновление заработает" % SCRIPT_REPO)
        else:
            err("GitHub отвечает: HTTP %d" % e.code)
        return
    except Exception as e:
        err("не скачалось: %s" % e)
        return

    m = VERSION_RE.search(data)
    if not m:
        err("в скачанном файле нет версии — обновление отменено")
        return
    remote = m.group(1)
    if vtuple(remote) == vtuple(__version__):
        ok("у тебя последняя версия: v%s" % __version__)
        return
    if vtuple(remote) < vtuple(__version__):
        warn("локальная v%s новее, чем на GitHub (v%s) — запушь коммит" % (__version__, remote))
        return

    print()
    lines = [
        kv("установлена", paint("v" + __version__, "fg_dim")),
        kv("на GitHub", paint("v" + remote, "green_b", "bold")),
    ]
    panel(lines, title="ДОСТУПНО ОБНОВЛЕНИЕ", accent="green")

    if INSTALLED_SCRIPT.resolve() == Path(__file__).resolve():
        # обновляем сам файл, с которого запущены
        target = Path(__file__).resolve()
    else:
        target = INSTALLED_SCRIPT

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / (target.name + ".new")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, target)
        os.chmod(target, 0o755)
        ok("обновлено до v%s → %s" % (remote, target))
        dim("перезапусти лаунчер, чтобы продолжить на новой версии")
    except Exception as e:
        err("не получилось записать: %s" % e)

    # заодно обновляем копию на флешке, если она доступна на запись
    flash_copy = SCRIPT_DIR / "launch.py"
    if SCRIPT_DIR != PROJECTS_DIR and flash_copy.exists():
        try:
            old_flash = read_version(flash_copy)
            if old_flash and vtuple(old_flash) < vtuple(remote):
                flash_copy.write_text(data, encoding="utf-8")
                os.chmod(flash_copy, 0o755)
                ok("флешка тоже обновлена: %s" % flash_copy)
        except Exception:
            dim("флешка только для чтения — обновить копию на ней не вышло")

# ============================== ХАРАКТЕРИСТИКИ ПК ==============================

def _read(path, default=None):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return default

def _gb(kb):
    return "%.1f ГБ" % (kb / 1048576.0)

def _uptime(sec):
    d, rest = divmod(int(sec), 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    return ("%dд " % d if d else "") + ("%dч " % h if h or d else "") + "%dм" % m

def collect_specs():
    """Собирает инфу о компе. Всё в try — на кривой системе просто «—»."""
    s = {}

    def safe(key, fn):
        try:
            s[key] = fn()
        except Exception:
            s[key] = "—"

    def os_name():
        for line in (_read("/etc/os-release") or "").splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"')
        return "Linux"

    def cpu_model():
        for line in (_read("/proc/cpuinfo") or "").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
        return "—"

    def cpu_freq():
        for line in (_read("/proc/cpuinfo") or "").splitlines():
            if line.startswith("cpu MHz"):
                return "%.2f ГГц" % (float(line.split(":", 1)[1]) / 1000.0)
        return "—"

    def ram():
        mem = {}
        for line in (_read("/proc/meminfo") or "").splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                mem[parts[0].strip()] = float(re.findall(r"\d+", parts[1])[0])
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        used = max(total - avail, 0)
        pct = used / total * 100 if total else 0
        return "%s / %s  %s" % (_gb(used), _gb(total), bar(pct))

    def swap():
        mem = {}
        for line in (_read("/proc/meminfo") or "").splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                mem[parts[0].strip()] = float(re.findall(r"\d+", parts[1])[0])
        total = mem.get("SwapTotal", 0)
        free = mem.get("SwapFree", 0)
        if not total:
            return "нет"
        used = total - free
        pct = used / total * 100
        return "%s / %s  %s" % (_gb(used), _gb(total), bar(pct))

    def disk():
        u = shutil.disk_usage("/")
        pct = u.used / u.total * 100 if u.total else 0
        return "%.1f ГБ / %.1f ГБ  %s" % (u.used / 1073741824.0, u.total / 1073741824.0, bar(pct))

    def gpu():
        try:
            r = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10)
            cards = []
            for line in r.stdout.splitlines():
                if re.search(r"VGA compatible|3D controller|Display controller", line):
                    cards.append(line.split(": ", 1)[-1].strip())
            return "; ".join(cards) if cards else "—"
        except Exception:
            return "—"

    def resolution():
        try:
            r = subprocess.run(["xrandr", "--current"], capture_output=True, text=True, timeout=10)
            m = re.search(r"current\s+(\d+)\s*x\s+(\d+)", r.stdout)
            return "%s x %s" % (m.group(1), m.group(2)) if m else "—"
        except Exception:
            return "—"

    def ip():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(0)
            sock.connect(("10.255.255.255", 1))
            addr = sock.getsockname()[0]
            sock.close()
            return addr
        except Exception:
            return "—"

    def packages():
        try:
            r = subprocess.run(["rpm", "-qa"], capture_output=True, text=True, timeout=20)
            n = len([l for l in r.stdout.splitlines() if l.strip()])
            return str(n) if n else "—"
        except Exception:
            return "—"

    def battery():
        for bat in sorted(Path("/sys/class/power_supply").glob("BAT*")):
            cap = _read(bat / "capacity")
            if cap:
                status = _read(bat / "status", "")
                return "%s%% (%s)" % (cap, status.lower())
        return "нет"

    def cpu_temp():
        raw = _read("/sys/class/thermal/thermal_zone0/temp")
        if raw:
            try:
                return "%.0f°C" % (int(raw) / 1000.0)
            except Exception:
                pass
        return "—"

    def load():
        la = (_read("/proc/loadavg") or "").split()
        return " ".join(la[:3]) if len(la) >= 3 else "—"

    def desktop():
        de = os.environ.get("XDG_CURRENT_DESKTOP", "")
        sess = os.environ.get("XDG_SESSION_TYPE", "")
        return " + ".join(x for x in (de.split(":")[-1], sess) if x) or "—"

    uptime_raw = _read("/proc/uptime")
    safe("os", os_name)
    s["host"] = platform.node() or _read("/etc/hostname", "—")
    s["kernel"] = "%s %s" % (platform.system().lower(), platform.release())
    s["arch"] = platform.machine()
    s["cpu"] = cpu_model()
    s["cores"] = str(os.cpu_count() or "—")
    s["freq"] = cpu_freq()
    safe("ram", ram)
    safe("swap", swap)
    safe("disk", disk)
    s["gpu"] = gpu()
    s["res"] = resolution()
    safe("uptime", lambda: _uptime(float(uptime_raw.split()[0])) if uptime_raw else "—")
    s["load"] = load()
    s["temp"] = cpu_temp()
    s["desktop"] = desktop()
    s["shell"] = os.path.basename(os.environ.get("SHELL", "—"))
    s["term"] = os.environ.get("TERM", "—") + (" / " + os.environ["COLORTERM"] if os.environ.get("COLORTERM") else "")
    s["lang"] = os.environ.get("LANG", "—")
    s["battery"] = battery()
    s["ip"] = ip()
    s["packages"] = packages()
    s["python"] = "%s (%s)" % (platform.python_version(), sys.executable)
    return s

def show_specs():
    clear()
    show_banner()
    s = collect_specs()
    lines = [
        kv("ОС", paint(s["os"], "yellow_b")),
        kv("хост", s["host"]),
        kv("ядро", paint(s["kernel"], "aqua_b") + paint("  " + s["arch"], "fg_dim")),
        kv("uptime", s["uptime"]),
        kv("загрузка", s["load"]),
        "",
        kv("CPU", paint(s["cpu"], "green_b")),
        kv("ядра", s["cores"] + paint("  @ " + s["freq"], "fg_dim")),
        kv("темп.", s["temp"]),
        kv("RAM", s["ram"]),
        kv("swap", s["swap"]),
        kv("диск /", s["disk"]),
        "",
        kv("GPU", paint(s["gpu"], "purple_b")),
        kv("экран", s["res"]),
        kv("батарея", s["battery"]),
        "",
        kv("DE", s["desktop"]),
        kv("shell", s["shell"]),
        kv("терминал", s["term"]),
        kv("язык", s["lang"]),
        kv("IP", s["ip"]),
        kv("пакеты (rpm)", s["packages"]),
        kv("python", paint(s["python"], "orange_b")),
    ]
    print()
    panel(lines, title="ХАРАКТЕРИСТИКИ КОМПЬЮТЕРА", accent="aqua")
    print()
    pause("Enter — назад в меню")

# ============================== ЗАПУСК ИГР ==============================

def launch_detached(name, game, reg):
    """Запускает игру откреплённо (setsid), чистит терминал и закрывает лаунчер.

    Возвращает True, если лаунчер пора закрыть (игра ушла в свободный полёт),
    False — если остались в меню (например, игра сразу упала)."""
    path = Path(game.get("path", ""))
    entry = game.get("entry")

    if not path.exists() or not any(path.glob("*.py")):
        err("папка игры пропала: %s" % path)
        pause()
        return False

    if not entry or not (path / entry).is_file():
        info("точка входа не настроена — давай выберем")
        entry = choose_entry(path)
        if not entry:
            dim("без точки входа не запустить")
            pause()
            return False
        game["entry"] = entry
        save_registry(reg)

    py = game.get("python") or ""
    if not py or not Path(py).exists():
        py = sys.executable
        warn("venv нет — запускаю системным python")

    info("запускаю %s (%s) откреплённо..." % (name, entry))
    try:
        proc = subprocess.Popen([py, str(path / entry)], cwd=str(path),
                                start_new_session=True)
    except Exception as e:
        err("не запустилось: %s" % e)
        pause()
        return False

    time.sleep(1.0)
    if proc.poll() is not None:
        # упала мгновенно — терминал НЕ чистим, чтобы был виден её вывод
        err("%s вырубилась сразу (код %s) — вывод выше подскажет причину" %
            (name, proc.returncode))
        pause()
        return False

    clear()  # терминал пустой, игра живёт своей жизнью, лаунчер закрывается
    return True

def delete_game(reg):
    clear()
    show_banner()
    names = sorted(reg.keys())
    if not names:
        warn("реестр пуст — удалять нечего")
        pause()
        return
    print(paint("  какую игру удалить?", "bold"))
    for i, name in enumerate(names, 1):
        print(paint("  [%d] " % i, "fg_dim") + name)
    raw = ask(paint("  › ", "aqua_b") + "номер (Enter — отмена): ")
    if not raw or not raw.isdigit() or not (1 <= int(raw) <= len(names)):
        return
    name = names[int(raw) - 1]
    path = Path(reg[name].get("path", ""))

    print()
    info("что удаляем у %s?" % name)
    print(paint("    [1] ", "fg_dim") + "всё: папку " + paint(str(path), "fg_dim") + " и из реестра")
    print(paint("    [2] ", "fg_dim") + "только из реестра (папку оставить)")
    print(paint("    [0] ", "fg_dim") + "ничего, я передумал")
    what = ask(paint("  › ", "aqua_b") + "выбор: ", default="0")
    if what == "2":
        del reg[name]
        save_registry(reg)
        ok("%s удалена из реестра (папка на месте)" % name)
        pause()
        return
    if what != "1":
        dim("отмена")
        pause()
        return
    if path.exists() and path.is_dir():
        really = confirm("точно снести %s целиком? назад дороги нет" % path, default=False)
        if not really:
            dim("отмена")
            pause()
            return
        try:
            shutil.rmtree(path)
            del reg[name]
            save_registry(reg)
            ok("%s снесена полностью" % name)
        except Exception as e:
            err("не получилось: %s" % e)
    else:
        del reg[name]
        save_registry(reg)
        ok("%s удалена из реестра" % name)
    pause()

# ============================== ПОЧИНКА И СТИРКА ==============================

def repair_games(reg, names, online=None):
    """Сносит .venv выбранных игр и собирает заново: venv + зависимости + точка входа."""
    if online is None:
        online = internet_ok()
    fixed = 0
    for name in names:
        item = reg.get(name)
        if not item:
            warn("%s: нет в реестре — пропускаю" % name)
            continue
        project = Path(item.get("path", ""))
        print()
        if not project.exists() or not any(project.glob("*.py")):
            warn("%s: папка пропала — пропускаю" % name)
            continue
        print(paint("🔧 " + name, "orange_b", "bold"))
        venv = project / ".venv"
        if venv.exists():
            try:
                shutil.rmtree(venv)
                dim("старый .venv снесён")
            except Exception as e:
                err("не смог снести .venv: %s" % e)
                continue
        else:
            dim(".venv не было — соберу с нуля")
        if setup_project(project, reg, online):
            fixed += 1
    save_registry(reg)
    return fixed

def repair_menu(reg):
    """Меню починки: выбрать игры ('1 2 3' / '1,2,3' / '1, 2, 3' / '4' / 'все'),
    починить все, удалить все следы или выйти. True — закрыть лаунчер."""
    while True:
        clear()
        show_banner()
        names = sorted(reg.keys())
        if not names:
            warn("реестр пуст — чинить нечего")
            pause()
            return False
        rows = []
        for i, name in enumerate(names, 1):
            col, note = game_status(reg[name])
            rows.append(paint("  %2d. " % i, "fg_dim") + paint(name, "bold", "fg")
                        + "  " + paint(note, "fg_dim") + "  " + paint("●", col))
        panel(rows, title="ПОЧИНКА ИГР", accent="yellow")
        print()
        print(paint("  выбор: ", "fg_dim")
              + paint('"1 2 3"', "fg") + paint(" / ", "fg_dim")
              + paint('"1,2,3"', "fg") + paint(" / ", "fg_dim")
              + paint('"1, 2, 3"', "fg") + paint(" / ", "fg_dim")
              + paint('"4"', "fg") + paint(" или ", "fg_dim") + paint('"все"', "fg"))
        print(paint("  [все]", "green_b", "bold") + " починить все      "
              + paint("[w]", "red_b", "bold") + " удалить все следы      "
              + paint("[q]", "fg_dim", "bold") + " выход из этого меню")
        print()
        raw = ask(paint("  › ", "aqua_b", "bold"), default=None)
        if raw is None:
            return False
        low = raw.strip().lower()
        if low in ("", "q", "й", "выход", "quit", "exit"):
            return False
        if low in ("все", "всё", "all", "*", "a", "ф"):
            fixed = repair_games(reg, names)
            ok("починено игр: %d" % fixed)
            pause()
            continue
        if low in ("w", "ц", "wipe", "следы", "удалить все следы"):
            if wipe_all_traces(reg):
                return True
            continue
        nums = parse_selection(raw, len(names))
        if not nums:
            warn("не понял %r — номера через пробел/запятую, «все», w или q" % raw)
            pause()
            continue
        chosen = [names[n - 1] for n in nums]
        fixed = repair_games(reg, chosen)
        ok("починено: %d из %d (%s)" % (fixed, len(chosen), ", ".join(chosen)))
        pause()

def wipe_all_traces(reg):
    """«Удалить все следы»: сносит с ЭТОГО компа игры, реестр, установленную
    копию скрипта и alias. Флешку не трогает. True — закрыть лаунчер."""
    clear()
    show_banner()
    games_n = 0
    if PROJECTS_DIR.exists():
        games_n = len([d for d in PROJECTS_DIR.iterdir()
                       if d.is_dir() and not d.name.startswith(".")])
    lines = [
        kv("игры", paint("%d шт. — %s" % (games_n, PROJECTS_DIR), "red_b")),
        kv("реестр", paint(str(REGISTRY_FILE), "red_b")),
        kv("копия скрипта", paint(str(INSTALLED_SCRIPT), "red_b")),
        kv("alias", paint("dimasbotyara в .bashrc / .zshrc", "red_b")),
        "",
        paint("  флешку и скрипт на ней это НЕ трогает", "green_b"),
    ]
    panel(lines, title="УДАЛИТЬ ВСЕ СЛЕДЫ?", accent="red")
    print()
    if not confirm("точно стереть все следы на этом компе?", default=False):
        dim("отмена")
        pause()
        return False
    word = ask(paint("  › ", "aqua_b", "bold")
               + paint("набри УДАЛИТЬ большими буквами: ", "red_b", "bold"))
    if word.strip().upper() != "УДАЛИТЬ":
        dim("не то слово — отмена")
        pause()
        return False

    print()
    running_from_pc = Path(__file__).resolve() == INSTALLED_SCRIPT.resolve()
    if PROJECTS_DIR.exists():
        try:
            shutil.rmtree(PROJECTS_DIR)
            ok("снесено: %s (игры + реестр + копия скрипта)" % PROJECTS_DIR)
        except Exception as e:
            err("не всё получилось снести: %s" % e)
    reg.clear()
    for rc, note in uninstall_alias():
        if note == "убран":
            ok("%s: %s" % (rc.name, note))
        else:
            dim("%s: %s" % (rc.name, note))
    print()
    if running_from_pc:
        warn("лаунчер запущен с компа — его файл тоже снесён, после выхода он закроется")
    ok("следов не осталось. осталась только флешка 😌")
    pause()
    return True

# ============================== МЕНЮ ==============================

def draw_menu(reg):
    clear()
    show_banner()
    names = sorted(reg.keys())
    if names:
        rows = []
        for i, name in enumerate(names, 1):
            info = reg[name]
            col, note = game_status(info)
            dot = paint("●", col)
            entry_txt = paint(note, "fg_dim")
            rows.append(paint("  %2d. " % i, "fg_dim") + paint(name, "bold", "fg") + "  " + entry_txt + "  " + dot)
        panel(rows, title="ИГРЫ (%d)" % len(names), accent="purple")
    else:
        print(paint("  🤷 игр нет — нажми [i] и поставим!", "yellow_b"))

    print()
    print(paint("  [i]", "green_b", "bold") + " установить/обновить игры     " +
          paint("[a]", "blue_b", "bold") + " синхронизировать реестр")
    print(paint("  [d]", "red_b", "bold") + " удалить игру                  " +
          paint("[r]", "yellow_b", "bold") + " починить игры 🔧")
    print(paint("  [s]", "aqua_b", "bold") + " характеристики компьютера     " +
          paint("[u]", "orange_b", "bold") + " обновить сам скрипт")
    print(paint("  [q]", "fg_dim", "bold") + " выход")
    print()
    return names

def menu_loop(reg):
    while True:
        names = draw_menu(reg)
        choice = ask(paint("  › ", "aqua_b", "bold"), default=None)
        if choice is None:
            choice = "q"
        choice = choice.strip().lower()

        if choice in ("q", "quit", "exit", "выход", "й"):
            print()
            if internet_ok(1.5):
                if confirm("проверить обновления скрипта перед выходом?", default=True):
                    self_update()
            else:
                dim("без сети — проверку обновлений пропускаю")
            print(paint("  ✨ пока! и не забудь вынести мусор из класса", "purple_b", "italic"))
            return

        if choice in ("i", "ш"):
            online = internet_ok()
            reg = sync_registry(reg)
            stats = install_games(online, reg)
            install_summary(stats)
            pause()
            reg = sync_registry(reg)
            continue

        if choice in ("a", "ф"):
            reg = sync_registry(reg)
            ok("реестр синхронизирован: %d игр" % len(reg))
            pause()
            continue

        if choice in ("d", "в"):
            delete_game(reg)
            continue

        if choice in ("r", "к"):
            if repair_menu(reg):
                return
            reg = load_registry()
            continue

        if choice in ("s", "ы"):
            show_specs()
            continue

        if choice in ("u", "г"):
            self_update()
            pause()
            continue

        if choice.isdigit():
            idx = int(choice)
            if 1 <= idx <= len(names):
                if launch_detached(names[idx - 1], reg[names[idx - 1]], reg):
                    return
            else:
                warn("нет игры с таким номером")
                pause()
            continue

        if choice in reg:
            if launch_detached(choice, reg[choice], reg):
                return
            continue

        warn("не понял: %r — номер, i/a/d/r/s/u или q" % choice)
        pause()

# ============================== ЗАПУСК ==============================

def startup_flow():
    """Баннер, сеть, самоустановка, alias, вопрос про установку игр."""
    show_banner()

    online = internet_ok()
    if online:
        ok("интернет: " + paint("есть — GitHub доступен", "green_b", "bold"))
    else:
        warn("интернет: " + paint("НЕТ — режим флешки (обновление с GitHub недоступно)", "red_b", "bold"))
    print(kv("папка игр", paint(str(PROJECTS_DIR), "aqua_b")))
    print(kv("скрипт", paint(str(Path(__file__).resolve()), "fg_dim")))
    print()

    self_install()
    for rc, note in install_alias():
        msg = "%s: %s" % (rc.name, note)
        if note == "добавлен":
            ok(msg)
        elif "не вышло" in note:
            err(msg)
        else:
            dim(msg)
    print(paint("  (alias dimasbotyara появится после перезахода или: source ~/.bashrc)", "fg_dim"))
    print()
    return online

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--version" in argv:
        print("BOTYARA GAMES v%s" % __version__)
        return 0
    if "--help" in argv or "-h" in argv:
        print(__doc__.strip())
        print()
        print("использование: launch.py [имя_игры] [опции]")
        print("  (без опций)      меню лаунчера (вход по паролю)")
        print("  ИМЯ              запустить игру по имени сразу (лаунчер закроется)")
        print("  --install        скачать/обновить игры и настроить venv")
        print("  --sync           только синхронизировать реестр")
        print("  --specs          характеристики компьютера")
        print("  --update         проверить обновление скрипта")
        print("  --version        версия")
        return 0

    if "--specs" in argv:
        show_specs()
        return 0

    # всё остальное — за паролем
    if not require_password():
        return 1

    if "--update" in argv:
        self_update()
        return 0

    if "--install" in argv or "--sync" in argv:
        show_banner()
        online = internet_ok()
        if online:
            ok("интернет: есть")
        else:
            warn("интернет: нет — ставлю что могу с флешки")
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        reg = sync_registry()
        if "--sync" in argv:
            ok("реестр: %d игр" % len(reg))
            return 0
        stats = install_games(online, reg)
        install_summary(stats)
        return 0

    # ---- обычный режим / запуск игры по имени ----
    online = startup_flow()
    reg = sync_registry()

    target = next((a for a in argv if not a.startswith("-")), None)
    if target is None:
        # нужно ли что-то докачать/обновить?
        missing = [r for r in REPO_LIST if not (PROJECTS_DIR / r).is_dir()]
        if missing and online:
            print()
            info("не хватает %d игр: %s..." % (len(missing), ", ".join(missing[:4])))
            if confirm("скачать/обновить игры с GitHub сейчас?", default=True):
                stats = install_games(online, reg)
                install_summary(stats)
                reg = sync_registry(reg)
        elif missing:
            flash = find_flash_repos()
            copiable = [r for r in missing if r in flash]
            if copiable:
                info("без сети — скопирую с флешки: %s" % ", ".join(copiable))
                stats = install_games(online, reg)
                install_summary(stats)
                reg = sync_registry(reg)
        elif online:
            print()
            if confirm("обновить игры с GitHub сейчас?", default=True):
                stats = install_games(online, reg)
                install_summary(stats)
                reg = sync_registry(reg)

        menu_loop(reg)
        return 0

    if target in reg:
        launch_detached(target, reg[target], reg)
        return 0
    err("игра %r не найдена в реестре. доступно: %s" % (target, ", ".join(sorted(reg)) or "ничего"))
    return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        print(paint("  👋 прервано. пока!", "purple_b"))
        sys.exit(130)
