"""Put an Order Tracker icon on the desktop.

Windows gets a real .lnk shortcut (built through PowerShell, which is always
present, rather than a third-party package), macOS gets a double-clickable
.command file, and Linux gets a .desktop launcher.
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


def python_for_launching() -> str:
    """The interpreter to run the app with."""
    return sys.executable or "python3"


# --- Windows ---------------------------------------------------------------

_PS_TEMPLATE = r'''
$ErrorActionPreference = "Stop"
$desktop = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path $desktop)) { throw "Desktop folder not found at $desktop" }
$link = Join-Path $desktop "{name}.lnk"
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($link)
$s.TargetPath = "{target}"
$s.Arguments = "{arguments}"
$s.WorkingDirectory = "{workdir}"
$s.Description = "Open the Order Tracker terminal"
{icon}
$s.Save()
Write-Output $link
'''


def _windows_shortcut(icon: Path | None) -> Path:
    # Prefer the windowed interpreter so no console box is left behind; fall
    # back to python.exe when pythonw.exe is missing from the install.
    exe = Path(python_for_launching())
    windowed = exe.with_name("pythonw.exe")
    target = windowed if windowed.exists() else exe

    icon_line = ""
    if icon and icon.exists():
        icon_line = f'$s.IconLocation = "{icon}"'

    script = _PS_TEMPLATE.format(
        name=SHORTCUT_NAME,
        target=str(target),
        arguments=f'"{config.BASE_DIR / "run.py"}"',
        workdir=str(config.BASE_DIR),
        icon=icon_line,
    )

    with tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False,
                                     encoding="utf-8") as handle:
        handle.write(script)
        script_path = Path(handle.name)

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShortcutError(f"PowerShell could not be run: {exc}") from exc
    finally:
        script_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise ShortcutError(
            (result.stderr or result.stdout or "PowerShell reported an error").strip())

    created = (result.stdout or "").strip().splitlines()
    if not created:
        raise ShortcutError("PowerShell did not report where the shortcut went.")
    return Path(created[-1])


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

def create(icon: Path | None = None) -> Path:
    """Create the desktop shortcut and return where it was put."""
    if icon is None:
        candidate = config.ASSETS_DIR / "ordertracker.ico"
        icon = candidate if candidate.exists() else None

    if sys.platform == "win32":
        return _windows_shortcut(icon)
    if sys.platform == "darwin":
        return _macos_shortcut()
    return _linux_shortcut(icon)
