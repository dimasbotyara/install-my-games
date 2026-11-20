#!/bin/bash

# Синхронизация офлайн-копий из списка соседнего launch.py.
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
if [ ! -f launch.py ]; then
    printf '%s\n' 'Ошибка: положи update_repos_usb.sh рядом с launch.py на флешке.' >&2
    exit 1
fi

exec python3 -IB - <<'PY'
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import launch

repos = launch.FLASH_REPOS_DIR
try:
    if repos.is_symlink():
        raise OSError("repos/ — символическая ссылка")
    repos.mkdir(exist_ok=True)
except OSError as exc:
    launch.err("не удалось открыть папку репозиториев: %s" % exc)
    sys.exit(1)

launch.show_banner()
print(launch.paint("  СИНХРОНИЗАЦИЯ РЕПОЗИТОРИЕВ НА ФЛЕШКЕ", "yellow_b", "bold"))

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
sys.exit(1 if counts["ошибок"] else 0)
PY
