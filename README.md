# Clothesline for Windows

**Screenshots, hung out to dry.** A glass bar slides down from the top of your screen and
holds your recent screenshots on a clothesline. Click one to copy it, drag it into any app,
keep it, or send it to the Recycle Bin.

> Independent Windows app **inspired by [Tendedero](https://tendedero.app) for macOS** by
> Alejandro Buján. It shares no code with Tendedero and is not affiliated with or endorsed by it.
> If you use a Mac, go and get the original.

## Features
- Bar glides down when the pointer rests at the top edge of the screen, and tucks away when you leave
- Global hotkeys: **Ctrl+Alt+T** or **Win+Shift+Y**
- Picks up new screenshots from `Pictures\Screenshots` and images copied to the clipboard
- Drag screenshots straight into Slack, Discord, browsers or File Explorer (always a copy, never a move)
- Glass look, clothes pegs, pendulum swing and spring animations
- Remembers your line between runs

## Gestures
| | |
|:--|:--|
| Click | Copy the image (ripple + "Copied!") |
| Double-click | Open in your default photo viewer |
| Drag out | Drop a copy into another app or folder |
| Hover, then **Keep** | Take it off the line. The file stays in Screenshots |
| Hover, then **Delete** (or the X) | Move the file to the Recycle Bin (restorable). Optional confirmation in the tray menu |
| Do nothing | After a while (5 min by default, adjustable in the tray menu) it leaves the line. The file is never touched |
| Right-click | Copy / Open / Show in folder / Move to Recycle Bin / Keep file, remove from line |

## Install
Requires **Windows 10 or 11** and **Python 3.10+** (tick "Add python.exe to PATH" in the installer).

1. Download this repository (**Code → Download ZIP**) and unzip it.
2. Double-click **`run.bat`**. The first run sets up a Python environment in
   `%LOCALAPPDATA%\Clothesline` (about a minute); after that it starts instantly.
3. Look for the tray icon near the clock.

Windows may warn that `run.bat` is from an unknown publisher: it is plain text, open it in Notepad to check.

To start with Windows, press **Win+R**, type `shell:startup`, and put a shortcut to `run.bat` there.

### Standalone .exe (optional)
Double-click `build_exe.bat`. The result is saved in `%LOCALAPPDATA%\Clothesline\dist`.

### Run from a terminal
```powershell
pip install -r requirements.txt
python clothesline.py
```

## Privacy
No account, no network access, no analytics. Everything stays on your PC.

## Status
Early version. Built with Python and PySide6 (Qt). Bug reports are welcome as issues.

## License
Code: MIT, see [LICENSE](LICENSE).
The name "Tendedero" and its icon belong to its author and are not used here.
