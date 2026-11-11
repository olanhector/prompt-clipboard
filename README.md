# Prompt Clipboard

A small phrase clipboard for macOS, aimed at the prompts you retype all day.
Click a phrase, it's on your clipboard.

Previously "Clipboard Widget 2". Your existing phrases are picked up
automatically — see [Your data](#your-data).

## Install

```bash
./build_app.sh                 # uses a Tk-capable python3 already on this Mac
./build_app.sh --embed-python  # ships its own Python; ~66 MB, runs anywhere
```

Then drag `PromptClipboard.app` to `/Applications`, or anywhere else — the
bundle only ever runs the copy of the script inside itself, so its location on
disk doesn't matter.

To run from source instead, double-click `prompt-clipboard.command`.

## Use

| Action | How |
|---|---|
| Copy a phrase | Click it, or `⌘1`–`⌘9` |
| Add | `＋` or `⌘N` |
| Edit / reorder / delete | Right-click a phrase |
| Search | Type in the box, or `⌘F`; `Esc` clears |
| Settings | `⌘,` |
| Quit | `⌘Q` |

### Settings

`⌘,` opens Settings, which also appears in the application menu and under File.

- **Keep window on top of other apps** — remembered between launches. The same
  toggle still lives in View → Always on Top; both drive one setting, so they
  can't disagree.
- **Your phrases** — shows the data folder, with a button to reveal it in
  Finder.

## Command line

Works without a GUI, so it's usable over SSH and from scripts. The built app
accepts the same flags, which is how you verify a bundle without a display:

```bash
python3 prompt_clipboard.py --list
python3 prompt_clipboard.py --copy "Meeting"
python3 prompt_clipboard.py --add "PR" "Taking a look now."
python3 prompt_clipboard.py --doctor     # environment diagnostics
python3 prompt_clipboard.py --selftest   # build the UI off-screen, check it

PromptClipboard.app/Contents/MacOS/launch --selftest
```

## Your data

```
~/Library/Application Support/PromptClipboard/
├── phrases.json    your phrases
└── state.json      window size, position, always-on-top
```

Plain JSON, outside the bundle, so rebuilding or replacing the app never
touches it. Writes are atomic, so a crash mid-save can't corrupt the file. Set
`PROMPT_CLIPBOARD_HOME` to use a different folder (handy for testing); the
older `CLIPBOARD_WIDGET_HOME` still works.

On first run, if that folder doesn't exist yet, the app **copies** phrases and
window state from an earlier install — `ClipboardWidget2`, then
`ClipboardWidget`, then the seed bundled in the .app. It only ever copies: the
old folder is left exactly as it was, so nothing is lost if you go back.

Logs from bundle launches go to `~/Library/Logs/PromptClipboard.log`.

## Requirements

With `--embed-python`, none — the bundle carries its own Python 3.13 and Tk 9.

Otherwise: a `python3` with **Tk 8.6 or newer**. Apple's `/usr/bin/python3`
ships Tk 8.5.9 (2010), which on current macOS draws native buttons and leaves
every custom-coloured frame, label, entry and text blank — an 8.5 interpreter
passes an `import tkinter` check and then renders an empty window, so the
launcher tests the Tk version rather than just the import, and shows a dialog
instead of a blank app.

## Shipping this to other people

Not ready yet. `--embed-python` solves the runtime half — a bundle built that
way runs on a Mac with no Python installed, and was verified running from a
path with no connection to the machine that built it. What's still missing:

- **Gatekeeper.** The bundle is ad-hoc signed. That's invisible locally because
  a locally built app never gets a quarantine flag, but a *downloaded* copy
  does, and an ad-hoc signature has no Developer ID and no notarisation, so
  macOS refuses to open it. Needs a real signing identity plus a notarisation
  step in `build_app.sh`.
- **A distribution channel**, and whatever review it carries.

The bundle identifier is `local.promptclipboard`. If this ever does go through
a Meta-managed channel, that is the thing to revisit first.

Why not py2app, the usual answer here: it expects a framework build whose
`zlib` is a shared module, and fails on python-build-standalone with
`module 'zlib' has no attribute '__file__'`. The Pythons available are Apple's
(Tk 8.5, too old) and fbpython (Meta infrastructure, not ours to redistribute),
so there is no framework build to point it at. python-build-standalone is
designed to be relocated, which makes copying it in both simpler and easier to
verify.

## What v1 got wrong

Each of these is now a design constraint rather than a bug:

| v1 | now |
|---|---|
| Absolute path to the build directory baked into the launcher — renaming the folder broke the app | Launcher resolves everything relative to the bundle |
| `LSUIElement=true`: no Dock icon, no `⌘`-Tab, no `⌘Q` — an invisible window meant an unkillable process | Normal app with a Dock icon and a menu bar |
| `overrideredirect(True)` borderless window that macOS often never composited | Ordinary window with a real title bar |
| Unsigned bundle showed a generic icon | Ad-hoc signed at build time |
| Failures were completely silent | Alert dialog on failure, plus a log file |
| Saved position could restore off-screen | Geometry clamped to the visible display |
| Phrases lived inside the bundle | Phrases in Application Support |
| No way to test without a screen | `--selftest` and `--doctor`, on the bundle too |
