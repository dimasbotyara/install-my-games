#!/bin/bash

# Синхронизация офлайн-копий из списка соседнего launch.py.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
if [ ! -f launch.py ] || [ -L launch.py ]; then
    printf '%s\n' 'Ошибка: нужен обычный файл launch.py рядом с update_repos_usb.sh на флешке.' >&2
    exit 1
fi

exec python3 -IB - <<'PY'
import os
import re
import stat
import sys
import tempfile
from types import ModuleType
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import launch


def refresh_launcher(current, target):
    """Проверяем и подменяем только файл на флешке, не установленную копию."""
    temporary = None
    try:
        if target.is_symlink():
            raise OSError("launch.py — символическая ссылка")
        version, data = current._fetch_remote()
        if not version:
            raise ValueError(data)
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
            raise ValueError("неизвестный формат версии: %s" % version)
        if current.vtuple(version) <= current.vtuple(current.__version__):
            current.info("оставляю launch.py v%s (на GitHub v%s)" % (current.__version__, version))
            return current, True

        # Загружаем новый список в этом же запуске, не читая старый .pyc.
        fresh = ModuleType("launch")
        fresh.__file__ = str(target)
        exec(compile(data, str(target), "exec"), vars(fresh))
        helpers = ("main", "git_clone", "git_pull", "paint", "ok", "err", "hr")
        if (fresh.__version__ != version or not isinstance(fresh.REPO_LIST, list)
                or not all(callable(getattr(fresh, name, None)) for name in helpers)):
            raise ValueError("скачанный launch.py неполный или имеет неожиданную версию")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=".launch-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        temporary.chmod(stat.S_IMODE(target.stat().st_mode))
        os.replace(temporary, target)
    except Exception as exc:
        current.err("не удалось обновить launch.py: %s" % exc)
        current.warn("продолжаю со списком текущей версии")
        return current, False
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    current.ok("launch.py обновлён: v%s → v%s" % (current.__version__, version))
    return fresh, True


launch.show_banner()
print(launch.paint("  СИНХРОНИЗАЦИЯ ФЛЕШКИ", "yellow_b", "bold"))
launch, launcher_ok = refresh_launcher(launch, Path.cwd() / "launch.py")
repos = launch.FLASH_REPOS_DIR
try:
    if repos.is_symlink():
        raise OSError("repos/ — символическая ссылка")
    repos.mkdir(exist_ok=True)
except OSError as exc:
    launch.err("не удалось открыть папку репозиториев: %s" % exc)
    sys.exit(1)

counts = {"добавлено": 0, "обновлено": 0, "без изменений": 0, "ошибок": 0}
for name in dict.fromkeys(launch.REPO_LIST):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in (".", ".."):
        launch.err("недопустимое имя репозитория: %s" % name)
        counts["ошибок"] += 1
        continue

    dest = repos / name
    url = "https://github.com/%s/%s.git" % (launch.GH_USER, name)
    if dest.is_symlink() or (dest.exists() and not (dest / ".git").is_dir()):
        launch.err("%s: путь занят, оставляю без изменений" % name)
        counts["ошибок"] += 1
        continue

    if dest.exists():
        print(launch.paint("  ▸ Обновляю %s" % name, "aqua_b"), flush=True)
        good, msg, changed = launch.git_pull(dest)
        result = "обновлено" if changed else "без изменений"
    else:
        print(launch.paint("  ▸ Скачиваю %s" % name, "aqua_b"), flush=True)
        good, msg = launch.git_clone(url, dest)
        result = "добавлено"

    if good:
        counts[result] += 1
        launch.ok("%s: %s" % (name, result))
    else:
        counts["ошибок"] += 1
        launch.err("%s: %s" % (name, msg))

launch.hr()
for label, count in counts.items():
    color = "red_b" if label == "ошибок" and count else "fg"
    print(launch.paint("  %s: %d" % (label, count), color))
sys.exit(1 if counts["ошибок"] or not launcher_ok else 0)
PY
