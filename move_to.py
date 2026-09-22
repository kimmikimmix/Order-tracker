#!/usr/bin/env python3
"""Copy Order Tracker to another drive and run it from there from now on.

    py move_to.py "G:\\my folder\\Order Tracker"        copy it across
    py move_to.py "G:\\my folder" --check               test the folder only
    py move_to.py "G:\\my folder" --manual              print what to copy by hand
    py move_to.py --finish                             complete a hand-made copy

Copies the whole app plus whatever you have already stored, switches the
copy to portable mode so it keeps its data in its own folder, and repoints
the desktop shortcut at the new location.

Nothing is deleted. The original folder is left exactly as it is until you
have checked the copy works and remove it yourself.

There is a button for all of this on the SETUP page inside the app, which
saves getting a command prompt into the right folder.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ordertracker import config, relocate  # noqa: E402
from ordertracker.relocate import (  # noqa: E402,F401  (kept importable here)
    MoveError, SKIP, SKIP_JUNK_ONLY, SKIP_NO_GIT, copy_database,
    count_stored, describe_copy_failure, force_copy, is_inside, usable,
)


def print_manual_plan(destination) -> int:
    """Exactly what to copy where, for doing it in File Explorer.

    Nothing is written anywhere by this. It exists because a drive that
    Python cannot write to is often one File Explorer copies to quite
    happily, and because the data folder is easy to miss: it is frequently
    not inside the app folder at all.
    """
    report = relocate.plan(destination, probe=False)
    source = report["source"]
    target = Path(report["destination"])
    stored = report["stored"]

    print("  Copy it by hand — nothing below writes anything for you.\n")
    print("  1. Close Order Tracker. Click QUIT in the app, or close the")
    print("     black window if one is open. Copying a database while it is")
    print("     open is the one way to end up with a half-written copy.\n")

    print("  2. In File Explorer, open this folder:\n")
    print(f"         {source}\n")
    print("     Press Ctrl+A to select everything, then Ctrl+C.\n")

    print("  3. Open the folder you want it in:\n")
    print(f"         {target}\n")
    print("     Press Ctrl+V.\n")

    if report["data_inside_app"]:
        print("     Your orders live inside the folder you just copied, so")
        print(f"     they came with it ({stored or 'nothing stored yet'}).\n")
        step = "4"
    elif stored:
        print("  4. Your orders are NOT in that folder. They are here, and")
        print("     this is the step people miss:\n")
        print(f"         {report['data_source']}")
        print(f"         ({stored})\n")
        print("     Copy that whole folder, and paste it inside the new one")
        print("     so that you end up with:\n")
        print(f"         {report['data_destination']}\n")
        print("     Copy the folder itself, not just the files in it — the")
        print("     database keeps its most recent changes in companion")
        print("     files that sit beside it.\n")
        step = "5"
    else:
        print("  4. Nothing is stored yet, so there is no data to bring.\n")
        step = "5"

    print(f"  {step}. Open a Command Prompt IN THE NEW FOLDER — click the address")
    print("     bar in File Explorer, type  cmd  and press Enter, so the")
    print(f"     prompt reads {target}. Then run:\n")
    print("         py move_to.py --finish\n")
    print("     That marks the copy as portable so it keeps its data in its")
    print("     own folder, brings your welcome name across, repoints the")
    print("     desktop icon, and tells you what it found.\n")

    print("  Nothing has been copied or changed. Do the steps above, then")
    print("  run the --finish command inside the copy.\n")
    return 0


def report_steps(result: dict) -> None:
    for step in result["steps"]:
        print(f"  [ ok ] {step}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Copy Order Tracker to another drive and run it from there.")
    parser.add_argument("destination", nargs="?",
                        help=r'the new folder, e.g. "G:\Order Tracker"')
    parser.add_argument("--no-git", action="store_true",
                        help="skip the .git folder (you then cannot `git pull` there)")
    parser.add_argument("--no-shortcut", action="store_true")
    parser.add_argument("--check", action="store_true",
                        help="test the destination and report, without copying")
    parser.add_argument("--force", action="store_true",
                        help="copy even though Order Tracker is still running")
    parser.add_argument("--replace-data", action="store_true",
                        help="overwrite orders already in the destination")
    parser.add_argument("--manual", action="store_true",
                        help="print what to copy where, and copy nothing")
    parser.add_argument("--finish", action="store_true",
                        help="run inside a copy you made by hand, to complete it")
    args = parser.parse_args(argv)

    if args.finish:
        print("\nORDER TRACKER — finish a hand-made copy\n")
        print(f"  this folder   {config.BASE_DIR.resolve()}\n")
        try:
            result = relocate.finish_here(shortcut=not args.no_shortcut)
        except relocate.MoveError as exc:
            print(f"  {exc}\n")
            return 1
        report_steps(result)
        print("\n  Done. Start it with:\n")
        print("      py run.py\n")
        print("  Check it is reading from here:\n")
        print("      py run.py --where\n")
        print("  Nothing in the folder you copied from has been touched.\n")
        return 0

    if not args.destination:
        parser.error("give the folder to copy to, or use --finish inside a "
                     "copy you made by hand")

    report = relocate.plan(args.destination, probe=not args.manual)
    print("\nORDER TRACKER — move to another drive\n")
    print(f"  from  {report['source']}")
    print(f"  to    {report['destination']}\n")

    if args.manual:
        return print_manual_plan(args.destination)

    if report["problem"]:
        print(f"  {report['problem']}")
        print("  Nothing has been copied.\n")
        return 1

    if args.check:
        print(f"  [ ok ] {report['destination']} can be written to")
        print("  [ ok ] a database can be created there")
        print(f"  [ ok ] your orders would come from {report['data_source']}")
        print(f"         ({report['stored'] or 'nothing stored yet'})")
        if report["destination_stored"]:
            print(f"  [ !! ] that folder ALREADY holds "
                  f"{report['destination_stored']}")
            print("         copying would replace them — add --replace-data "
                  "if that is right")
        if report["warning"]:
            print()
            for text in report["warning"].splitlines():
                print(f"  ! {text}" if text else "  !")
        print("\n  Nothing was copied. Run the same command without --check "
              "to do it.\n")
        return 0

    live = relocate.running_copy()
    if live and not args.force:
        print("  Order Tracker is still running, and its orders are open.")
        print(f"  It is using {live}\n")
        print("  Close it first, or the copy can end up with a half-written")
        print("  database: click QUIT in the app, then run this again.\n")
        print("  (If you are sure it is safe, add --force.)\n")
        return 1

    if report["warning"]:
        for text in report["warning"].splitlines():
            print(f"  ! {text}" if text else "  !")
        print()

    if report["not_empty"]:
        print("  Note: that folder is not empty. Files with the same names will")
        print("  be overwritten; anything else there is left alone.\n")

    try:
        result = relocate.run(args.destination, keep_git=not args.no_git,
                              shortcut=not args.no_shortcut,
                              replace_data=args.replace_data)
    except relocate.MoveError as exc:
        print(f"  {exc}\n")
        print("  Nothing has been changed in the original folder.\n")
        if not args.no_git:
            print("  You can also leave out the git history, which is most of")
            print("  these files and none of the app:\n")
            print(f'      py move_to.py "{args.destination}" --no-git\n')
        return 1

    report_steps(result)
    print("\n  Done.\n")
    print(f"    the app now lives in   {result['destination']}")
    print(f"    its data is in         {result['data']}")
    if result["shortcut"]:
        print(f"    desktop shortcut       {Path(result['shortcut']).name}")
    print()
    print("  Check it works:\n")
    print(f'      cd /d "{result["destination"]}"')
    print("      py run.py\n")
    print(f"  Once you are happy, delete the old folder:\n      {result['source']}\n")
    print("  Nothing has been removed for you.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
