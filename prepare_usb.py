#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Интерактивная подготовка флешки BOTYARA GAMES (Windows / Linux)."""

import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import launch

try:
    import curses
except ImportError:
    curses = None


def removable_drives():
    """Смонтированные съёмные носители; ручной путь остаётся запасным вариантом."""
    if os.name == "nt":
        drives = []
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        for n in range(26):
            root = chr(65 + n) + ':\\'
            if mask & (1 << n) and ctypes.windll.kernel32.GetDriveTypeW(root) == 2:
                drives.append(Path(root))
        return drives
    if sys.platform.startswith("linux"):
        try:
            result = subprocess.run(["lsblk", "-J", "-o", "NAME,RM,TRAN,MOUNTPOINTS"],
                                    capture_output=True, text=True, check=True, timeout=10)
            devices = json.loads(result.stdout).get("blockdevices", [])
            drives = []

            def visit(device, removable=False):
                removable = removable or str(device.get("rm", "0")).lower() in ("1", "true") or device.get("tran") == "usb"
                if removable:
                    for mount in device.get("mountpoints") or []:
                        if mount and Path(mount).is_dir():
                            drives.append(Path(mount))
                for child in device.get("children") or []:
                    visit(child, removable)
            for device in devices:
                visit(device)
            return sorted(set(drives))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return []


def text_prompt(step, question, details=()):
    print('\n' + launch.paint('  ' + step, 'yellow_b', 'bold'))
    for line in details:
        print(launch.paint('  ' + line, 'fg'))
    return input(launch.paint('  › ', 'aqua_b') + question + ': ')


class CursesPrompt:
    """Тот же мастер, но вопросы рисуются на отдельном экране терминала."""

    def __init__(self, screen):
        self.screen = screen
        self.styles = dict(title=curses.A_BOLD, detail=0, prompt=curses.A_BOLD, hint=0)
        if curses.has_colors():
            colors = {'title': ('yellow_b', curses.COLOR_YELLOW), 'detail': ('fg', curses.COLOR_WHITE),
                      'prompt': ('aqua_b', curses.COLOR_CYAN), 'hint': ('fg_dim', curses.COLOR_WHITE)}
            wide_colors = curses.COLORS >= 256
            background = 235 if wide_colors else curses.COLOR_BLACK
            for i, (role, (color, fallback)) in enumerate(colors.items(), 1):
                foreground = launch.PAL[color][1] if wide_colors else fallback
                curses.init_pair(i, foreground, background)
                self.styles[role] |= curses.color_pair(i)
            self.screen.bkgd(' ', self.styles['detail'])

    def __call__(self, step, question, details=()):
        value = ''
        while True:
            self.screen.erase()
            height, width = self.screen.getmaxyx()
            if height < 9 or width < 32:
                raise curses.error('terminal too small')

            def line(row, text, role):
                self.screen.addnstr(row, 2, text, width - 4, self.styles[role])

            line(1, 'BOTYARA GAMES / USB / v' + launch.__version__, 'title')
            line(2, '─' * (width - 4), 'hint')
            line(3, step, 'title')
            questions = (textwrap.wrap(question, width - 4) or [''])[-(height - 7):]
            question_row = height - 3 - len(questions)
            shown = [part for detail in details for part in textwrap.wrap(detail, width - 4)]
            for row, detail in enumerate(shown[:question_row - 4], 4):
                line(row, detail, 'detail')
            for row, part in enumerate(questions, question_row):
                line(row, part, 'prompt')
            visible = value[-(width - 8):]
            line(height - 3, '› ' + visible, 'detail')
            line(height - 2, 'Enter — подтвердить   Ctrl+C — отмена', 'hint')
            self.screen.move(height - 3, 4 + len(visible))
            self.screen.refresh()
            key = self.screen.get_wch()
            if key in ('\n', '\r', curses.KEY_ENTER):
                return value
            if key in ('\x08', '\x7f', curses.KEY_BACKSPACE):
                value = value[:-1]
            elif isinstance(key, str) and key.isprintable():
                value += key


def yes_no(prompt, question, step, details=(), default=True):
    while True:
        answer = prompt(step, '%s [%s]' % (question, 'Y/n' if default else 'y/N'), details).strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes', 'д', 'да'):
            return True
        if answer in ('n', 'no', 'н', 'нет'):
            return False
        if 'Ответьте да или нет.' not in details:
            details = ('Ответьте да или нет.', *details)


def choose_drive(prompt):
    drives = removable_drives()
    details = ['Найденные съёмные диски:']
    details.extend('  %d. %s' % (i, drive) for i, drive in enumerate(drives, 1))
    if not drives:
        details.append('Не обнаружены; можно указать путь вручную.')
    feedback = []
    while True:
        value = prompt('01 / НОСИТЕЛЬ', 'Номер диска или путь к смонтированной флешке (Q — выход)',
                       feedback + details).strip().strip('"')
        if value.lower() in ('q', 'quit'):
            return None
        if value.isdigit() and 1 <= int(value) <= len(drives):
            path = drives[int(value) - 1]
        else:
            path = Path(value).expanduser() if value else None
        if path and path.is_dir():
            return path.resolve()
        feedback = ['Папка не существует. Проверьте путь.']


# --python-version/--platform фильтруют колёса, но pip по умолчанию
# вычисляет PEP 508 markers по компьютеру, на котором запущен мастер.
_TARGET_PIP = """
import runpy
import sys
from pip._vendor.packaging import markers

version, arch = sys.argv[1:3]
del sys.argv[1:3]
host_environment = markers.default_environment

def target_environment():
    env = host_environment()
    env.update(python_version=version, python_full_version=version + '.0',
               implementation_name='cpython', implementation_version=version + '.0',
               platform_python_implementation='CPython', sys_platform='linux',
               os_name='posix', platform_system='Linux', platform_machine=arch,
               platform_release='', platform_version='')
    return env

markers.default_environment = target_environment
runpy.run_module('pip', run_name='__main__', alter_sys=True)
"""


def linux_wheel_command(project, dest, python_version, arch, baseline):
    """Все target-теги — Linux или универсальные, независимо от ОС подготовки."""
    version = python_version.replace('.', '')
    platform_tag = 'manylinux2014' if baseline == '2.17' else 'manylinux_2_28'
    platforms = [platform_tag + '_' + arch]
    if baseline == '2.28':
        platforms.append('manylinux2014_' + arch)
    platforms.append('manylinux_2_17_' + arch)
    platforms.append('linux_' + arch)
    cmd = [sys.executable, '-I', '-c', _TARGET_PIP, python_version, arch,
           'download', '--disable-pip-version-check',
           '--only-binary=:all:', '--dest', str(dest), '--implementation', 'cp',
           '--python-version', version, '--abi', 'cp' + version, '--abi', 'abi3', '--abi', 'none']
    for platform_tag in platforms:
        cmd += ['--platform', platform_tag]
    req = project / 'requirements.txt'
    return cmd + (['-r', str(req)] if req.is_file() else launch.detect_imports(project))


def linux_wheels_only(directory):
    """Защита от прямых ссылок на колёса других ОС в requirements."""
    for path in directory.iterdir():
        if not path.is_file() or not path.name.endswith('.whl'):
            return False
        parts = path.name[:-4].split('-')
        if len(parts) < 5 or any(tag != 'any' and not (tag.startswith('linux_') or tag.startswith('manylinux'))
                                 for tag in parts[-1].split('.')):
            return False
    return True


def replace_wheel_bundle(staging, target):
    """Копируем новый набор на флешку до замены; старый оставляем при ошибке."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix='.wheels-', dir=target.parent))
    new, old = temp / 'new', temp / 'old'
    try:
        shutil.copytree(staging, new)
        if target.exists():
            target.rename(old)
        try:
            new.rename(target)
        except OSError:
            if old.exists():
                old.rename(target)
            raise
        if old.exists():
            shutil.rmtree(old)
    finally:
        # Если даже откат не удался, резервная копия остаётся на флешке.
        if not old.exists():
            shutil.rmtree(temp)


def prepare(drive, save_repos, save_wheels, python_versions=(), arch=None, baseline=None, overwrite=False):
    """Сохраняет launcher и по выбору исходники/колёса; не затирает чужие каталоги."""
    root = drive / 'BOTYARA-GAMES'
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise OSError('Путь %s занят и не является обычной папкой.' % root)
    if save_wheels and not python_versions:
        raise ValueError('Не выбрана версия Python для wheel-файлов.')
    root.mkdir(parents=True, exist_ok=overwrite)
    files = [Path(launch.__file__)]
    updater = Path(__file__).with_name('update_repos_usb.sh')
    if updater.is_file():
        files.append(updater)
    for source in files:
        target = root / source.name
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise OSError('Путь %s занят — не перезаписываю.' % target)
    for source in files:
        shutil.copy2(source, root / source.name)
    failures = []
    if not (save_repos or save_wheels):
        return root, failures
    for folder, needed in (('repos', save_repos), ('wheels', save_wheels)):
        path = root / folder
        if needed:
            if path.is_symlink():
                raise OSError('Путь %s — символическая ссылка, не трогаю.' % path)
            path.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='botyara-usb-') as temp:
        for name in dict.fromkeys(launch.REPO_LIST):
            # Значения BOTYARA_REPOS не должны выходить за пределы флешки.
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
                launch.err('Недопустимое имя репозитория: ' + name)
                failures.append(name)
                continue
            print('\n' + launch.paint('  ▸ ' + name, 'aqua_b', 'bold'), flush=True)
            stored = root / 'repos' / name
            if save_repos and (stored.exists() or stored.is_symlink()):
                if stored.is_symlink() or not (stored / '.git').is_dir():
                    launch.warn('Папка уже существует и не является git-клоном — не трогаю.')
                    failures.append(name)
                    continue
                good, msg, _ = launch.git_pull(stored)
                if not good:
                    launch.err('Не удалось обновить: ' + msg)
                    failures.append(name)
                    continue
                project = stored
            else:
                project = Path(temp) / name
                good, msg = launch.git_clone('https://github.com/%s/%s.git' % (launch.GH_USER, name), project)
                if not good:
                    launch.err('Ошибка клонирования: ' + msg)
                    failures.append(name)
                    continue
                if save_repos:
                    shutil.copytree(project, stored)
                    project = stored
            if save_wheels:
                failures.extend(download_wheel_bundles(root, project, name, python_versions, arch, baseline))
    return root, failures



def download_wheel_bundles(root, project, name, versions, arch, baseline):
    req = project / 'requirements.txt'
    safe, reason = launch.offline_requirements_safe(req) if req.is_file() else (True, '')
    if not safe:
        launch.err('Нельзя подготовить wheel-файлы: ' + reason)
        return [name]
    game_dir = root / 'wheels' / name
    if game_dir.is_symlink() or (game_dir.exists() and not game_dir.is_dir()):
        launch.warn('Путь wheel-файлов занят — не трогаю.')
        return [name]
    needs_download = req.is_file() or bool(launch.detect_imports(project))
    failures = []
    for version in versions:
        target = game_dir / launch.wheel_bundle_tag(version)
        label = '%s (Python %s)' % (name, version)
        launch.info('Wheel-файлы для Python ' + version)
        try:
            if target.is_symlink() or (target.exists() and not target.is_dir()):
                raise OSError('путь набора занят')
            with tempfile.TemporaryDirectory(prefix='botyara-wheels-') as temp:
                staging = Path(temp)
                if needs_download:
                    cmd = linux_wheel_command(project, staging, version, arch, baseline)
                    subprocess.run(cmd, cwd=str(project), timeout=600, check=True)
                if not linux_wheels_only(staging):
                    raise ValueError('скачаны не Linux wheel-файлы')
                replace_wheel_bundle(staging, target)
                launch.ok('Python %s: wheel-файлов: %d' % (version, len(list(staging.iterdir()))))
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            launch.err('%s: не удалось обновить набор: %s' % (label, exc))
            failures.append(label)
    return failures


PYTHON_PRESETS = tuple('3.%d' % minor for minor in range(10, 15))


def choose_python_versions(prompt, step):
    local = '%d.%d' % sys.version_info[:2]
    presets = ', '.join(PYTHON_PRESETS)
    details = ('Поддерживаемые варианты: ' + presets,
               'Можно указать несколько через запятую или пробел. Не знаете версию? Введите «все».')
    while True:
        raw = prompt(step, 'Версии CPython [%s]' % local, details).strip().lower() or local
        if raw in ('все', 'всё', 'all', '*'):
            return PYTHON_PRESETS
        versions = tuple(dict.fromkeys(re.split(r'[,\s]+', raw)))
        if all(re.fullmatch(r'3\.(?:0|[1-9][0-9]?)', version) for version in versions):
            return versions
        details = ('Укажите версии как 3.11 или 3.10, 3.12.', *details[-2:])


def collect_options(prompt):
    drive = choose_drive(prompt)
    if drive is None:
        return None
    step = '02 / СОДЕРЖИМОЕ'
    details = ('Файлы будут записаны в: %s' % (drive / 'BOTYARA-GAMES'), 'Ничего не форматируется.')
    root = drive / 'BOTYARA-GAMES'
    overwrite = root.exists() or root.is_symlink()
    if overwrite:
        if not yes_no(prompt, 'BOTYARA-GAMES уже есть. Перезаписать выбранные файлы?', step,
                      (*details, 'Остальные файлы и наборы Python сохранятся.'), default=False):
            return None
    elif not yes_no(prompt, 'Продолжить?', step, details):
        return None
    repos = yes_no(prompt, 'Скачать репозитории для офлайн-установки?', step)
    wheels = yes_no(prompt, 'Скачать Linux wheel-файлы для офлайн-установки?', step)
    versions = ()
    arch = baseline = None
    if wheels:
        step = '03 / ЦЕЛЕВОЙ LINUX'
        versions = choose_python_versions(prompt, step)
        while True:
            arch = prompt(step, 'Архитектура Linux-ПК: x86_64 / aarch64 [x86_64]').strip() or 'x86_64'
            if arch in ('x86_64', 'aarch64'):
                break
        while True:
            baseline = prompt(step, 'Минимальная glibc Linux-ПК: 2.17 / 2.28 [2.17]').strip() or '2.17'
            if baseline in ('2.17', '2.28'):
                break
    return drive, repos, wheels, versions, arch, baseline, overwrite


def configure():
    if (curses is not None and not launch.NO_COLOR and sys.stdin.isatty()
            and os.environ.get('TERM') not in (None, '', 'dumb')):
        try:
            return curses.wrapper(lambda screen: collect_options(CursesPrompt(screen)))
        except curses.error:
            launch.warn('curses недоступен — использую текстовый режим')
    launch.show_banner()
    launch.info('ПОДГОТОВКА ФЛЕШКИ · потребуются интернет, git и pip')
    return collect_options(text_prompt)


def main():
    options = configure()
    if options is None:
        return 0
    if options[2]:
        launch.warn('Проверьте набор на целевом Linux: точная patch-версия Python и ядро неизвестны.')
    print('\n' + launch.paint('  ПОДГОТОВКА ФЛЕШКИ', 'yellow_b', 'bold'))
    try:
        root, failures = prepare(*options)
    except (OSError, ValueError) as exc:
        launch.err(str(exc))
        return 1
    launch.hr()
    if failures:
        launch.err('Не удалось подготовить: ' + ', '.join(failures))
        launch.dim('Проверьте ошибки выше и повторите подготовку. Папка: %s' % root)
        return 1
    launch.ok('Готово: %s' % root)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print('\nОтменено.')
        sys.exit(130)
