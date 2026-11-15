# 🎮 BOTYARA GAMES — install-my-games

One-file games installer & launcher for **school Linux computer labs**.
Runs from a **USB stick**: clones the games, builds venvs, installs dependencies,
auto-detects entry points, keeps a game registry, shows PC specs and can even
update itself from GitHub. Pure Python stdlib — **zero pip dependencies**.

![CI](https://github.com/dimasbotyara/install-my-games/actions/workflows/ci.yml/badge.svg)

---

## ⚠️ NOT FOR YOUR HOME PC

> **This tool was built for school computer labs running [ALT Linux Education][alt].**
> It clones repositories, writes shell config files (`~/.bashrc`), creates folders in
> `~/.config`, and runs whatever code is inside those repositories — by design.
>
> If that sentence makes you uncomfortable, do not run this on your personal machine.
> And honestly — review `launch.py` before running it anywhere. It's one file on purpose,
> so you *can* read it.

[alt]: https://www.altlinux.org/ALT_Education

---

## What it does (one command, everything)

```
python3 /run/media/you/FLASH/launch.py
```

1. **Checks the internet** — status is shown immediately; without it the script
   switches to "USB stick mode" and errors clearly instead of hanging.
2. **Installs itself** to `~/.config/systemd-backup/launch.py` (never downgrades a
   newer GitHub-updated copy).
3. **Adds an alias** to `~/.bashrc` (once, no duplicates):
   ```bash
   alias dimasbotyara="python3 ~/.config/systemd-backup/launch.py"
   ```
4. **Downloads / updates the games** from GitHub (`git clone --depth 1`, then
   `git pull` — and if a shallow clone can't fast-forward, it un-shallows first).
   If GitHub is unreachable, falls back to offline copies in `repos/` on the stick.
5. **Configures every game**: venv + dependencies (auto-detected) + entry point.
6. **Launches games** from a gruvbox-dark menu (gruvbox palette only — yellow
   accents, dim panel borders, no rainbow).

No internet? Games already on the PC still launch — offline never blocks playing.

## Password gate 🔒

Opening the launcher (and anything that does something: installing, launching,
self-update) asks for a password. Input is hidden (`getpass`), 3 attempts.

The password itself is **not stored anywhere**: only a salted SHA-256 hash lives
in `launch.py`, compared in constant time (`hmac.compare_digest`). No rainbow
table is going to reverse it, and reading the source won't reveal the secret.
To change the password, replace `AUTH_HASH` with
`sha256(AUTH_SALT + ":" + new_password)`.

Read-only helpers (`--help`, `--version`, `--specs`) stay password-free.

## Fire-and-forget launching

Choosing a game **detaches** it from the launcher: the game gets its own session
(`setsid`), the launcher wipes the terminal and exits, and the game keeps running
on its own — no forgotten launcher windows hanging around afterwards. If a game
dies within the first second, the terminal is *not* cleared so its error output
stays visible.

## Web apps stay in the terminal 🌐

A **web app** (Flask, Django, FastAPI, Bottle, Tornado, Sanic, Quart) is handled
the other way round: it runs **in the launcher's terminal**, you see its log and
the address it listens on, and `Ctrl+C` stops the server and returns you to the
menu — no password prompt again, the session is already unlocked.

The detection looks at the game's imports and asks one question: *is there a
window?* A game that imports `pygame`/`tkinter`/Qt is a normal windowed game and
gets detached even if it also talks to a web server in the background
(`botyarapong`: pygame window + `werkzeug` multiplayer server — that one is
detached). `werkzeug`/`aiohttp` alone are not treated as a web app either — they
are often just a network engine inside a game.

Stopping is stubborn-proof: `SIGTERM` first, `SIGKILL` five seconds later if the
server ignores it.

## Entry point detection

Scans each game in this priority order:

```
run.py  →  app.py  →  main.py  →  (single .py in root)  →  ask you
```

If nothing matches, the launcher asks — and remembers your choice in the registry.

## Dependencies without requirements.txt

If a game has no `requirements.txt`, the script scans its `.py` files for
`import`/`from` statements, drops stdlib and local modules, maps names
(`PIL → pillow`, `cv2 → opencv-python`, …) and pip-installs the rest.
You are never asked to type dependency names by hand.

## Game registry (auto-completion & deletion)

`.registry.json` auto-syncs on every start:

- new game folders in the target directory are **added** automatically;
- deleted folders are **pruned**;
- venv paths are **refreshed**;
- menu item `[d]` deletes a game (folder + registry entry, with confirmation).

## PC specs (mini-fastfetch)

Menu item `[s]` — OS, kernel, uptime, load average, CPU model/frequency/temperature,
RAM/swap/disk usage bars, GPU, screen resolution, battery, DE/shell/terminal,
locale, local IP, rpm package count and Python version. No logo, no external tools
required (optional extras degrade to `—` gracefully).

## Self-update

The launcher quietly checks `raw.githubusercontent.com/dimasbotyara/install-my-games/main`
on start and before exiting (or on demand via `[u]` / `--update`).

It **only asks a question when an update actually exists** — if your version is
already the newest, nothing happens and you're never nagged. When there is one,
it updates the installed copy and, if writable, the copy on the stick. Offline
it stays silent, so it never gets in the way. The downloaded file is fetched
once per run and cached.

> Self-update works only after this repository is actually pushed to
> `dimasbotyara/install-my-games`. Bump `__version__` in `launch.py` for updates
> to be detected.

## Offline mode (the USB stick part)

Put pre-cloned game repos next to the script:

```
FLASH/
├── launch.py
└── repos/
    ├── botyarapong/      # plain git clones
    ├── botyaraTD/
    └── ...
```

Without internet the installer copies games from `repos/` (keeping `.git`, so a
later online `git pull` still works). Online always prefers GitHub — the stick
copy is the fallback, not the source of truth.

## Repair & wipe 🔧

`[r]` opens the repair menu with every game listed:

- pick what to fix: one number (`4`), several (`1 2 3`, `1,2,3`, `1, 2, 3` — any
  separators work), or `все`;
- **починить все** — repair everything in one go;
- **удалить все следы** — the "nuke" button (see below);
- **выход** — back to the main menu.

Repairing a game deletes its `.venv`, re-detects the entry point and rebuilds
venv + dependencies from scratch — the cure for a pip run that died halfway.

**Удалить все следы** erases every trace the launcher left *on that PC*: all
games, the registry, the installed script copy and the `.bashrc`/`.zshrc` alias.
Double-protected: a confirmation plus typing `УДАЛИТЬ` by hand. The USB stick
(and the script on it) is never touched — that's your installer, not a trace.

## Menu keys

| Key | Action |
|-----|--------|
| `1..N` or game name | launch (windowed games detach; web apps run in the terminal) |
| `i` | install / update all games |
| `a` | re-sync the registry |
| `d` | delete a game |
| `r` | repair menu (rebuild venv, wipe all traces) |
| `s` | PC specs |
| `u` | update the script itself |
| `q` | exit (offers a final update check when online) |

CLI: `--install`, `--sync`, `--specs`, `--update`, `--version`, `--help`, or
`launch.py <game-name>` to launch straight from the shell.

## The game list

Defaults live in `REPO_LIST` in `launch.py` — currently 12 repos from
[github.com/dimasbotyara](https://github.com/dimasbotyara), including
`gearworks-industrial-age` and `botyaragames`. For a test run you can override it
without editing the file:

```bash
BOTYARA_REPOS="botyarapong,botyaragames" python3 launch.py
```

## Requirements

- ALT Linux Education (or any Linux, really) with `python3` and `git`
- internet *for installing/updating* (playing works offline)
- if `python3 -m venv` fails: `sudo apt-get install python3-module-pip python3-module-venv`

## Development

```bash
python -m py_compile launch.py
python -I -m unittest discover -s tests -v
```

100+ stdlib-only smoke tests (entry detection, dependency scanning, registry,
versions, UI rendering, banner glyphs, menu alignment, update checks, web-app
detection, terminal launching, password session, selection parsing, repair, alias
removal, wipe guard, self-install downgrade guard, real CLI runs) run in CI on
Python 3.10–3.14.
Tests never touch the network or your real `HOME`.

## Disclaimer

School computers are shared and boring on purpose. Test this on one machine,
read the script, and deploy to the rest only after you know what it does.
You break it — you explain it to the IT teacher. 🔧
