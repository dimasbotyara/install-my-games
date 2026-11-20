# 🎮 BOTYARA GAMES — install-my-games

Games installer & launcher for **school Linux computer labs** (v2.3.4).
Runs from a **USB stick**: clones the games, builds venvs, installs dependencies,
auto-detects entry points, keeps a game registry, shows PC specs and can even
update itself from GitHub. Pure Python stdlib — **zero pip dependencies**.

![CI](https://github.com/dimasbotyara/install-my-games/actions/workflows/ci.yml/badge.svg)

---

## Documentation site

The Russian-language guide lives in [`docs/`](docs/) and covers installation,
USB preparation, offline use, safety and troubleshooting. Preview it locally:

```bash
python3 -m http.server 8000 --directory docs
```

GitHub Pages is deployed by `.github/workflows/pages.yml` when `docs/` changes
on `main`. In the repository settings, select **Pages → Build and deployment →
Source → GitHub Actions**. Once the workflow succeeds, the site is available at
<https://dimasbotyara.github.io/install-my-games/>. Pages must be enabled in the
repository settings; simply merging the workflow does not configure it.

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
3. **Adds an alias** to `~/.bashrc` and `~/.zshrc` (once, no duplicates):
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

The big ASCII banner is drawn in the menu only. The startup screen is a compact
two-line header, so the first thing you see doesn't scroll your terminal away.

## Password gate 🔒

Opening the launcher (and anything that does something: installing, launching,
self-update) asks for a password. Input is hidden (`getpass`), 3 attempts.

The password itself is **not stored anywhere**: only a salted SHA-256 hash lives
in `launch.py`, compared in constant time (`hmac.compare_digest`). This is only a basic gate: a short or weak password can still be guessed offline,
and anyone with access to the script can bypass the check.
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
the address it listens on. This includes `alchemy-matcher` and `botyaracloud` (Flask). The terminal
animation picker `cli-anims` also stays attached so its menu can read the
keyboard and draw in the terminal; press `Q` to exit the picker.

- the app exits (you closed it / it crashed) → the launcher closes too and the
  screen is left clean, no server log hanging around in your terminal;
- `Ctrl+C` → the server is stopped and the launcher closes too;

The detection looks at the game's imports and names in `requirements.txt` (also
local included requirements) and asks one question: *is there a window?* A game that imports `pygame`/`tkinter`/`customtkinter`/Qt is a normal windowed game and
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

Updating is **manual**: `[u]` in the menu, or `--update`. That's it.

Startup and exit never touch GitHub. It used to check for a new `launch.py` on
every start and before every exit — meaning a download from GitHub right when you
just want to open a game, which on a slow phone connection (Termux) could hang
for fifteen seconds. Now nothing is fetched until you ask for it, and exits are
instant.

`[u]` asks for confirmation only if an update actually exists; if you're on the
newest version it just says so and returns to the menu.

> Self-update works only after this repository is actually pushed to
> `dimasbotyara/install-my-games`. Bump `__version__` in `launch.py` for updates
> to be detected.

## Preparing a USB stick (Windows or Linux) 💾

On a computer with internet, Python 3 with pip and Git, clone or download this
repository and run from its directory:

```bash
python prepare_usb.py       # Windows: py prepare_usb.py
```

The wizard lists mounted removable drives (Linux uses `lsblk`; Windows uses drive
types), or accepts a directory manually. Check the path before confirming: no
disk is formatted. It creates `BOTYARA-GAMES/`, copies `launch.py`, then asks
whether to download game repositories and Linux wheels separately. Wheels alone
can be useful when games are already on the target PC; for a fresh offline PC,
select **both**. Existing Git clones are updated; unrelated existing directories
are not deleted. Failed downloads are reported and give a nonzero exit code.
`BOTYARA_REPOS` also applies to the wizard.

For wheels, specify the target **CPython version**, Linux CPU architecture
(`x86_64` or `aarch64`) and minimum glibc baseline (`2.17` or `2.28`). On the
target, check with `python3 --version`, `uname -m` and `ldd --version`. The
wizard requests only binary wheels for Linux or platform-independent `any`,
including dependencies, even when run on Windows. Packages without a compatible
wheel cannot be prepared this way. One target combination is stored per game;
preparing a different combination replaces that game's wheel set.

**Cross-platform limitation:** pip may evaluate dependency environment markers
using the *preparation* machine, not the target Linux machine. Windows-only or
Linux-only conditional dependencies can therefore be missed or cause a failure.
For best results prepare on a matching Linux system, and always test on the
actual offline PC. Requirements with direct URLs or alternate package sources
are rejected for offline preparation; this feature is for index packages with
available wheels, not arbitrary source builds. Native system libraries, a
working Python/venv/pip and any non-Python assets must already be installed on
the target; a wheel is not a substitute for OS packages.

## Offline installation from USB

The prepared layout looks like this (or create it manually):

```
FLASH/BOTYARA-GAMES/
├── launch.py
├── repos/
│   ├── botyarapong/      # git clones
│   └── botyaraTD/
└── wheels/
    ├── botyarapong/      # wheels for this game's requirements
    └── botyaraTD/
```

Without internet the installer copies games from `repos/` (keeping `.git`, so a
later online `git pull` still works). Online always prefers GitHub — the stick
copy is the fallback, not the source of truth. Run the **USB copy** of
`launch.py` on the Linux PC (or `python3 /path/to/BOTYARA-GAMES/launch.py
--install`), so it can find the adjacent folders. When offline, pip installs
from `wheels/<game>/` with `--no-index --only-binary=:all:`; it reports missing
or incompatible wheels as installation failures instead of saying the game is
ready. Direct links in requirements and wheel metadata are rejected offline.
The installed launcher copy in `~/.config/systemd-backup/` does not automatically
find a subsequently inserted stick; run the USB copy for installation or repair.
An environment created without pip cannot install wheels until pip/venv is fixed.

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

## Keeping the shell history clean

Launching the launcher shouldn't show up in your command history. Along with the
alias, the installer writes this into `~/.bashrc`:

```bash
HISTIGNORE="*launch.py*:*systemd-backup*:*botyara*:*dimasbotyara*:*BOTYARA*"
HISTCONTROL="ignoreboth"
```

`HISTIGNORE` makes bash skip those commands entirely, `ignoreboth` drops
duplicates and lines starting with a space. `zsh` uses different variable names
for the same idea, so `.zshrc` gets the alias only — no dead bash variables in
there.

Both lines are removed again by **удалить все следы**. If you already had the
alias from an older version, the installer just adds the missing history lines,
without duplicating the alias.

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
| `q` | exit (no update check) |

CLI: `--install`, `--sync`, `--specs`, `--update`, `--version`, `--help`, or
`launch.py <game-name>` to launch straight from the shell.

## The game list

Defaults live in `REPO_LIST` in `launch.py` — currently 16 repos from
[github.com/dimasbotyara](https://github.com/dimasbotyara), including
`gearworks-industrial-age`, `botyaragames`, `cli-anims`, `alchemy-matcher`,
`nnn-countdown` (CustomTkinter), and `botyaracloud` (Flask).
For a test run you can override it without editing the file:

```bash
BOTYARA_REPOS="botyarapong,botyaragames" python3 launch.py
```

## Requirements

- ALT Linux Education (or any Linux, really) with `python3` and `git`
- internet for updating, or a prepared USB stick with repositories and compatible wheels for offline installation
- if `python3 -m venv` fails: `sudo apt-get install python3-module-pip python3-module-venv`

## Development

```bash
python -m py_compile launch.py prepare_usb.py
python -I -m unittest discover -s tests -v
```

Stdlib-only smoke tests (entry detection, dependency scanning, registry,
versions, UI rendering, banner glyphs, menu alignment, update checks, web-app
detection, terminal launching, password session, quiet startup, shell history,
selection parsing, repair, alias removal, wipe guard, self-install downgrade
guard, real CLI runs) run in CI on Python 3.10–3.14.
Tests never touch the network or your real `HOME`.

## Disclaimer

School computers are shared and boring on purpose. Test this on one machine,
read the script, and deploy to the rest only after you know what it does.
You break it — you explain it to the IT teacher. 🔧
