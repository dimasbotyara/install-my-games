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
from pathlib import Path

import launch


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


def yes_no(question, default=True):
    while True:
        answer = input('%s [%s]: ' % (question, 'Y/n' if default else 'y/N')).strip().lower()
        if not answer:
            return default
        if answer in ('y', 'yes', 'д', 'да'):
            return True
        if answer in ('n', 'no', 'н', 'нет'):
            return False
        print('Ответьте да или нет.')


def choose_drive():
    drives = removable_drives()
    print('\nНайденные съёмные диски:')
    for i, drive in enumerate(drives, 1):
        print('  %d. %s' % (i, drive))
    if not drives:
        print('  не обнаружены; можно указать путь вручную')
    while True:
        value = input('Номер диска или путь к смонтированной флешке (q — выход): ').strip().strip('"')
        if value.lower() in ('q', 'quit'):
            return None
        if value.isdigit() and 1 <= int(value) <= len(drives):
            path = drives[int(value) - 1]
        else:
            path = Path(value).expanduser() if value else None
        if path and path.is_dir():
            return path.resolve()
        print('Папка не существует. Проверьте путь.')


def linux_wheel_command(project, dest, python_version, arch, baseline):
    """Все target-теги — Linux или универсальные, независимо от ОС подготовки."""
    version = python_version.replace('.', '')
    platform_tag = 'manylinux2014' if baseline == '2.17' else 'manylinux_2_28'
    platforms = [platform_tag + '_' + arch]
    if baseline == '2.28':
        platforms.append('manylinux2014_' + arch)
    platforms.append('manylinux_2_17_' + arch)
    platforms.append('linux_' + arch)
    cmd = [sys.executable, '-m', 'pip', 'download', '--disable-pip-version-check',
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


def prepare(drive, save_repos, save_wheels, python_version=None, arch=None, baseline=None):
    """Сохраняет launcher и по выбору исходники/колёса; не затирает чужие каталоги."""
    root = drive / 'BOTYARA-GAMES'
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(launch.__file__), root / 'launch.py')
    failures = []
    if not (save_repos or save_wheels):
        return root, failures
    if save_repos:
        (root / 'repos').mkdir(exist_ok=True)
    if save_wheels:
        (root / 'wheels').mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory(prefix='botyara-usb-') as temp:
        for name in launch.REPO_LIST:
            # Значения BOTYARA_REPOS не должны выходить за пределы флешки.
            if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in ('.', '..'):
                print('Недопустимое имя репозитория:', name)
                failures.append(name)
                continue
            print('\n▸', name, flush=True)
            stored = root / 'repos' / name
            if save_repos and stored.exists():
                if not (stored / '.git').is_dir():
                    print('  Папка уже существует и не является git-клоном — не трогаю.')
                    failures.append(name)
                    continue
                good, msg, _ = launch.git_pull(stored)
                if not good:
                    print('  Не удалось обновить:', msg)
                    failures.append(name)
                    continue
                project = stored
            else:
                project = Path(temp) / name
                good, msg = launch.git_clone('https://github.com/%s/%s.git' % (launch.GH_USER, name), project)
                if not good:
                    print('  Ошибка клонирования:', msg)
                    failures.append(name)
                    continue
                if save_repos:
                    shutil.copytree(project, stored)
                    project = stored
            if save_wheels:
                staging = Path(temp) / (name + '-wheels')
                staging.mkdir()
                cmd = linux_wheel_command(project, staging, python_version, arch, baseline)
                req = project / 'requirements.txt'
                safe, reason = launch.offline_requirements_safe(req) if req.is_file() else (True, '')
                if not safe:
                    print('  Нельзя подготовить wheel-файлы:', reason)
                    failures.append(name)
                    continue
                # Нет requirements и импортов — pip download без аргументов не нужен.
                if not (project / 'requirements.txt').is_file() and not launch.detect_imports(project):
                    good = True
                else:
                    try:
                        result = subprocess.run(cmd, cwd=str(project), timeout=600)
                        good = result.returncode == 0
                    except (OSError, subprocess.SubprocessError) as exc:
                        print('  pip:', exc)
                        good = False
                if not good or not linux_wheels_only(staging):
                    print('  Ошибка загрузки Linux wheel-файлов; старый набор сохранён.')
                    failures.append(name)
                    continue
                target = root / 'wheels' / name
                if target.is_symlink() or (target.exists() and not target.is_dir()):
                    print('  Путь wheel-файлов занят — не трогаю.')
                    failures.append(name)
                    continue
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(staging, target)
                print('  wheel-файлов:', len(list(target.iterdir())))
    return root, failures


def main():
    print('BOTYARA GAMES v%s — подготовка флешки' % launch.__version__)
    print('Потребуются интернет, git и pip. Ничего не форматируется.')
    drive = choose_drive()
    if drive is None:
        return 0
    print('Файлы будут записаны в:', drive / 'BOTYARA-GAMES')
    if not yes_no('Продолжить?'):
        return 0
    repos = yes_no('Скачать репозитории для офлайн-установки?')
    wheels = yes_no('Скачать Linux wheel-файлы для офлайн-установки?')
    version = arch = baseline = None
    if wheels:
        default = '%d.%d' % sys.version_info[:2]
        while True:
            version = input('Версия CPython на Linux-ПК (например 3.11) [%s]: ' % default).strip() or default
            if re.fullmatch(r'3\.\d{1,2}', version):
                break
            print('Укажите версию в формате 3.11.')
        while True:
            arch = input('Архитектура Linux-ПК: x86_64 / aarch64 [x86_64]: ').strip() or 'x86_64'
            if arch in ('x86_64', 'aarch64'):
                break
        while True:
            baseline = input('Минимальная glibc Linux-ПК: 2.17 / 2.28 [2.17]: ').strip() or '2.17'
            if baseline in ('2.17', '2.28'):
                break
        print('Важно: pip вычисляет некоторые условные зависимости по ОС подготовки;')
        print('проверяйте готовый набор на целевом Linux, особенно при подготовке в Windows.')
    root, failures = prepare(drive, repos, wheels, version, arch, baseline)
    print('\nГотово:', root)
    if failures:
        print('Не удалось подготовить:', ', '.join(failures))
        print('Проверьте ошибки выше и повторите подготовку.')
        return 1
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nОтменено.')
        sys.exit(130)
