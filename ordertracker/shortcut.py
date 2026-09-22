"""Put an Order Tracker icon on the desktop.

Windows gets a real .lnk shortcut, built through PowerShell — always present,
so no third-party package is needed. If PowerShell is locked down by policy,
a .bat launcher is written instead, which always works.

macOS gets a double-clickable .command file and Linux a .desktop launcher.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config

SHORTCUT_NAME = "Order Tracker"


class ShortcutError(Exception):
    """The shortcut could not be created; the message says why."""


def python_for_launching() -> Path:
    """The interpreter to run the app with."""
    return Path(sys.executable) if sys.executable else Path("python3")


# --- Windows ---------------------------------------------------------------

# Values are passed in as parameters rather than pasted into the script, so a
# path containing quotes or braces cannot break — or rewrite — the script.
_PS_SCRIPT = r'''
param(
  [Parameter(Mandatory=$true)][string]$LinkPath,
  [Parameter(Mandatory=$true)][string]$Target,
  [string]$Arguments = "",
  [string]$WorkDir = "",
  [string]$IconPath = "",
  [string]$Description = ""
)
$ErrorActionPreference = "Stop"
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($LinkPath)
$link.TargetPath = $Target
if ($Arguments)   { $link.Arguments = $Arguments }
if ($WorkDir)     { $link.WorkingDirectory = $WorkDir }
if ($IconPath)    { $link.IconLocation = $IconPath }
if ($Description) { $link.Description = $Description }
$link.Save()
Write-Output $LinkPath
'''


def windows_desktop() -> Path:
    """The real Desktop folder, following any OneDrive redirection.

    The registry is the authority here: on a machine where OneDrive has taken
    over the desktop, %USERPROFILE%\\Desktop still exists but is not the one
    the user actually sees.
    """
    try:
        import winreg

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, "Desktop")
        candidate = Path(os.path.expandvars(value))
        if candidate.is_dir():
            return candidate
    except Exception:
        pass  # fall through to the ordinary guesses

    profile = Path(os.environ.get("USERPROFILE") or Path.home())
    for candidate in (profile / "OneDrive" / "Desktop", profile / "Desktop"):
        if candidate.is_dir():
            return candidate
    return profile / "Desktop"


def _launcher_command() -> tuple[Path, str]:
    """(interpreter, arguments) used to start the app."""
    exe = python_for_launching()
    # pythonw.exe runs without leaving a console window behind.
    windowed = exe.with_name("pythonw.exe")
    target = windowed if windowed.exists() else exe
    return target, f'"{config.BASE_DIR / "run.py"}"'


def _windows_bat(desktop: Path) -> Path:
    """A plain batch launcher — the fallback when PowerShell is unavailable."""
    exe = python_for_launching()
    link = desktop / f"{SHORTCUT_NAME}.bat"
    link.write_text(
        "@echo off\r\n"
        f"title {SHORTCUT_NAME}\r\n"
        f'cd /d "{config.BASE_DIR}"\r\n'
        f'"{exe}" run.py\r\n',
        encoding="utf-8",
    )
    return link


def _windows_shortcut(icon: Path | None) -> Path:
    desktop = windows_desktop()
    try:
        desktop.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ShortcutError(f"The desktop folder {desktop} is not reachable: {exc}") from exc

    link = desktop / f"{SHORTCUT_NAME}.lnk"
    target, arguments = _launcher_command()

    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(_PS_SCRIPT)
        script_path = Path(handle.name)

    command = [
        "powershell", "-NoProfile", "-NonInteractive",
        "-ExecutionPolicy", "Bypass", "-File", str(script_path),
        "-LinkPath", str(link),
        "-Target", str(target),
        "-Arguments", arguments,
        "-WorkDir", str(config.BASE_DIR),
        "-Description", "Open the Order Tracker terminal",
    ]
    if icon and icon.exists():
        command += ["-IconPath", str(icon)]

    problem = ""
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=90)
        if result.returncode == 0 and link.exists():
            return link
        problem = (result.stderr or result.stdout or "PowerShell reported an error").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        problem = f"PowerShell could not be run ({exc})"
    finally:
        script_path.unlink(missing_ok=True)

    # PowerShell is blocked or unhappy — a .bat on the desktop still works.
    try:
        return _windows_bat(desktop)
    except OSError as exc:
        raise ShortcutError(
            f"Neither a shortcut nor a launcher could be written to {desktop}.\n"
            f"PowerShell said: {problem}\n"
            f"Writing the file failed with: {exc}"
        ) from exc


# --- macOS -----------------------------------------------------------------

def _macos_shortcut() -> Path:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    link = desktop / f"{SHORTCUT_NAME}.command"
    link.write_text(
        "#!/bin/bash\n"
        f'cd "{config.BASE_DIR}"\n'
        f'exec "{python_for_launching()}" run.py\n',
        encoding="utf-8",
    )
    link.chmod(0o755)
    return link


# --- Linux -----------------------------------------------------------------

def _linux_shortcut(icon: Path | None) -> Path:
    desktop = Path(os.environ.get("XDG_DESKTOP_DIR") or (Path.home() / "Desktop"))
    desktop.mkdir(parents=True, exist_ok=True)
    link = desktop / f"{SHORTCUT_NAME}.desktop"
    lines = [
        "[Desktop Entry]",
        "Type=Application",
        f"Name={SHORTCUT_NAME}",
        "Comment=Open the Order Tracker terminal",
        f'Exec="{python_for_launching()}" "{config.BASE_DIR / "run.py"}"',
        f"Path={config.BASE_DIR}",
        "Terminal=false",
        "Categories=Office;",
    ]
    if icon and icon.exists():
        lines.append(f"Icon={icon}")
    link.write_text("\n".join(lines) + "\n", encoding="utf-8")
    link.chmod(0o755)
    return link


# --- entry point -----------------------------------------------------------

def default_icon() -> Path | None:
    candidate = config.ASSETS_DIR / "ordertracker.ico"
    return candidate if candidate.exists() else None


def create(icon: Path | None = None) -> Path:
    """Create the desktop shortcut and return where it was put."""
    if icon is None:
        icon = default_icon()

    if sys.platform == "win32":
        return _windows_shortcut(icon)
    if sys.platform == "darwin":
        return _macos_shortcut()
    return _linux_shortcut(icon)
