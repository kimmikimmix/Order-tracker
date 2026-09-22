# Order Tracker

A local, Bloomberg-style terminal for a sales desk: every order from every
customer on one dense screen, colour-coded by stage, with every piece of
paperwork filed against the order it belongs to and searchable by its contents.

It runs entirely on your own machine. No server, no cloud account, no
subscription, and nothing leaves the computer.

![the blotter and an open order](docs/screenshot-blotter.png)

## What it does

**One order book.** Every order across every customer in a single sortable,
filterable blotter — order number, customer, their PO number, stage, promised
date, days until due, value, owner, document count.

**Tells you what needs chasing.** The dashboard raises flags without being
asked:

| Flag | Meaning |
| --- | --- |
| `OVERDUE` | past its promised date and not shipped |
| `DUE SOON` | promised within the next 7 days |
| `STALLED` | open, but nobody has touched it in 14 days |
| `NO PO` | confirmed or further along with no customer PO on file |
| `ON HOLD` | parked, so it stops counting as on-track |

**Keeps the paperwork with the order.** Drop in POs, invoices, packing lists,
signed contracts and saved emails. The text inside each file is read and
indexed, so searching `Meridian Freight` finds the packing list that mentions
the carrier, not just files named after it. A file that names an order number
is filed against that order automatically.

**Imports the exports you already have.** Point it at a `.csv` or `.xlsx` from
your ERP or order portal. Columns are matched up for you — `Sales Order #`,
`Customer PO`, `Requested Delivery` and friends are all recognised — and you
confirm the mapping before anything is written. Re-importing a fresh export
updates the orders already on file, matched on order number, which is how you
refresh statuses in bulk.

**Keyboard-first.** `/` to search, `1`–`5` for views, `j`/`k` to move down the
blotter, `enter` to open, `n` for a new order, `esc` to close.

## Setting it up

Run this once. It asks where to keep your data, offers to move anything
already stored, and puts a shortcut on the desktop:

```bash
python3 setup.py               # Windows: py setup.py
```

Pick any folder on any drive — an external or network drive is fine. The
choice is remembered outside the app folder, so updating or re-downloading
the app never moves your orders. Run `setup.py` again any time to change it.

## Running it

You need Python 3.10 or newer. Nothing else — no `pip install`, no Node, no
database to set up.

Double-click the desktop shortcut, or:

```bash
python3 run.py
```

Starting it a second time just reopens the browser rather than running two
copies.

### Stopping it

Click **QUIT** in the top-right of the app. That is the whole answer — there
is no console window to keep open.

The desktop shortcut starts the app windowless, so nothing appears in the
taskbar. It keeps running in the background after you close the browser tab,
which is what you want when you are flicking between it and your email.
Closing the tab does not stop it; QUIT does. If you started it from a command
prompt instead, `Ctrl+C` there also works.

Your data is written as you go, so stopping it never loses anything.

## Running it from a personal or USB drive

The whole thing is portable — it is plain Python files, a database and your
documents, with nothing installed into Windows. Copy the folder to your drive
and set it up as portable:

```
py setup.py --portable
```

That writes a `portable.txt` marker beside `run.py`. While that file is
there, orders and documents stay inside the app folder and any saved location
is ignored, so the folder works whatever drive letter it gets on whatever
machine. Move it, copy it, back it up — it is one folder.

Delete `portable.txt` to go back to a chosen data folder.

Two things to know:

- **Python must exist on whatever machine you plug into.** The app carries no
  interpreter. Any machine with Python 3.10+ runs it.
- **Re-run `py setup.py --shortcut` after moving**, so the desktop icon points
  at the new location.

It opens `http://127.0.0.1:8787/` in your browser. Press `Ctrl+C` to stop.

To look around before putting real data in, load the sample order book. It goes
into its own `demo-data/` folder and never touches your real one:

```bash
python3 run.py --demo
```

Other options:

```bash
python3 run.py --port 9000     # if 8787 is taken (it will find a free port anyway)
python3 run.py --no-browser    # don't open a browser
python3 run.py --reindex       # re-read the text of every stored document
python3 run.py --data FOLDER   # keep orders and documents somewhere else
python3 run.py --where         # print where the data is kept, then exit
```

### If the desktop shortcut is missing

Make just the shortcut, leaving everything else alone:

```
py setup.py --shortcut
```

On Windows the Desktop folder is found through the registry, so a desktop
that OneDrive has taken over is handled. If PowerShell is blocked by policy,
a `.bat` launcher is written instead — it starts the app the same way.

### If it won't start

Run the check. It walks the same steps the app does and names whatever
fails:

```bash
python3 doctor.py              # Windows: py doctor.py
```

The usual culprit on Windows is something guarding the folder rather than
anything in the app — ransomware protection (Windows Security → Virus &
threat protection → Controlled folder access), OneDrive keeping the folder
online-only, or antivirus blocking new database files. Keeping the data
outside the protected area gets past all three:

```
py run.py --demo --data "%LOCALAPPDATA%\OrderTracker"
```

**On Windows** use `py run.py`. If Python isn't installed, get it from
python.org and tick "Add Python to PATH" during setup.

**On macOS** Python 3 is already there. Open Terminal, `cd` to this folder and
run the command above.

## Where your data lives

Wherever you pointed `setup.py`, in one folder:

```
<your folder>/
  data/
    orders.db        all orders, customers, history and extracted text
    documents/       the original files, exactly as you dropped them in
  demo-data/         the sample order book, kept well away from the real one
```

If you never ran `setup.py`, it sits beside the app instead. `python3 run.py
--where` always tells you.

Back it up by copying that folder. Move it to another machine by copying it
there. There is no other state — the only thing kept elsewhere is a small
settings file recording your chosen folder and welcome name:

| | |
| --- | --- |
| Windows | `%LOCALAPPDATA%\OrderTracker\settings.json` |
| macOS | `~/Library/Application Support/OrderTracker/settings.json` |
| Linux | `~/.config/order-tracker/settings.json` |

Data folders are excluded from git, so customer information is never
committed.

## The welcome screen

`setup.py` asks for a name to greet you with at startup. To change it later,
run `setup.py` again, or edit `welcome_name` in the settings file above.
Setting `show_welcome` to `false` there turns the splash off entirely.

## Making it yours

Open `ordertracker/config.py`. It is meant to be edited:

- **`PIPELINE`** — the stages an order moves through. Rename them to whatever
  your business says. The blotter, the board and the stage buttons all follow.
- **`DATE_INPUT_ORDER`** — `"MDY"` reads `03/12/2026` as 3 March;
  `"DMY"` reads it as 12 March. Unambiguous dates (`2026-12-03`, `3-Dec-2026`)
  always work either way.
- **`DUE_SOON_DAYS`**, **`STALLED_DAYS`** — when the flags fire.
- **`PO_REQUIRED_FROM`** — the stage at which a missing customer PO becomes a
  problem.
- **`DOC_KINDS`** — the keywords that classify a dropped file.

## What it does not do

Worth knowing before you rely on it:

- **Scanned paper isn't searchable inside.** A PDF that is a photograph of a
  document has no text to read. It is still stored and still findable by
  filename, customer and order — but finding words inside it would need OCR,
  which is not included. PDFs generated by software (which is nearly all
  purchase orders and invoices) read perfectly.
- **It is single-user and has no password.** It listens on `127.0.0.1`, so only
  your machine can reach it; requests arriving under another hostname are
  refused, and writes triggered from another website are rejected. Sharing it
  across a team means adding accounts and access control, which this does not
  have. Don't expose the port to a network.
- **It doesn't talk to your ERP.** Data arrives by import, by drag-and-drop, or
  by typing. A live connection would be the next thing to build.
- **Legacy `.doc` and `.xls`** (the old binary formats) can't be read for text.
  Save as `.docx` / `.xlsx` if you need their contents searchable.

## Developing

```bash
python3 -m unittest discover tests     # 73 tests, no dependencies
```

The pieces:

```
run.py                      entry point
setup.py                    first-run wizard: storage folder, shortcut, name
doctor.py                   startup check when something will not run
ordertracker/
  config.py                 pipeline, thresholds, paths — edit this first
  settings.py               remembered storage folder and welcome name
  shortcut.py               desktop shortcut for Windows, macOS and Linux
  db.py                     SQLite schema and full-text indexes
  orders.py                 order logic, alerts, search, dashboard
  documents.py              file storage, classification, auto-filing
  importer.py               CSV / Excel import and column matching
  xlsx.py                   a small read-only .xlsx reader
  multipart.py              file-upload parsing
  server.py                 HTTP server and JSON API
  sampledata.py             the --demo order book
  extract/                  text out of PDFs, emails, Office files, HTML
web/                        the single-page front end (no build step)
assets/                     app icon (regenerate with tools/make_icon.py)
tests/                      the test suite
```

Everything uses the Python standard library only. That is deliberate: it means
this still runs in five years on a machine with nothing installed on it.
