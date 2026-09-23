# Order Tracker

A local, Bloomberg-style terminal for a PCB sales desk: every order from every
customer on one dense screen, colour-coded by stage, with the full build
specification and cost sheet behind each one, and every piece of paperwork
filed against the order it belongs to and searchable by its contents.

It runs entirely on your own machine. No server, no cloud account, no
subscription, and nothing leaves the computer.

![the blotter and an open order](docs/screenshot-blotter.png)

## What it does

**One order book.** Every order across every customer in a single sortable,
filterable blotter — order number, customer, their PO number, stage, promised
date, days until due, value, owner, document count.

**Shows you where your customers are, and what time it is there.** The
dashboard opens on a world map with every customer on it, sized by how much
work is open and turning red when something is flagged. The day/night line
sweeps across it in real time, with the sun and the moon at the point each is
overhead, and a row of clocks underneath tells you who is at their desk right
now and who is asleep.

**Holds the whole build specification.** Layers, material, panel, finish,
copper, drills, impedance, BVH — with the conversions done for you: ounces to
microns and millimetres, a thickness tolerance in percent to a range in
millimetres, and how many boards come off a working panel.

**Prices the job in won and quotes it in dollars.** Enter the PCB price, and
for a turnkey order the SMT, the stencils and the components. Inflation and
markup are applied on top, and the whole sheet totals as you type. One click
prints the specification and the costing on white paper.

**Opens on what you have to do today.** The first thing on the first page is
one list of everything waiting on you, gathered from the four places it
hides: email the matching was not sure about, follow-up actions logged in
folders and cases, folders whose come-back date has arrived, orders past
their promised date, disputes whose answer is due, and paperwork nobody
filed. Late things are red and first, every line says why it is there, and
clicking one opens the thing itself. When there is nothing, it says so.

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

**Reads your email without being connected to it.** Save a message out of
Outlook — drag it into a folder, or File → Save As — and drop it on the
INBOX page. The sender, the subject, the date and the body are read on this
machine; the mail is summarised in two or three sentences taken from what it
actually says; it is sorted into DEFECT, DELIVERY, PURCHASE ORDER, QUOTE,
PAYMENT or SPEC; and it is filed against the order whose PO or order number
it mentions, or against the customer it came from. Attachments are stored as
documents of their own, so the PO inside the mail ends up on the order too.
Anything it is not sure about waits in the tray with the reasons for its
guess written next to it. Nothing is sent anywhere, and `.msg` works without
Outlook installed.

**Gives every conversation a folder.** Not everything a customer sends is an
order, and most of it starts long before one exists: a price request, a
sample, a question about a stack-up, a chase about a delivery. Each gets a
folder with the topic on the front, the emails received and sent kept
together inside it, what they want, where it stands right now, a date to
come back to it, and the actions still outstanding. The customer list shows
how many each customer has running.

**Keeps the whole story of a dispute.** When a lot comes back faulty, open a
case against the order: what is wrong, how many pieces, how much is claimed,
who is handling it, and when an answer is due. Then log every call, mail,
meeting and decision as it happens, each with its date, and give the ones
that need chasing a follow-up date. The dashboard counts what is outstanding
and what is late, and one click prints the case — position and full log — on
white paper for the meeting.

**Imports the exports you already have.** Point it at a `.csv` or `.xlsx` from
your ERP or order portal. Columns are matched up for you — `Sales Order #`,
`Customer PO`, `Requested Delivery` and friends are all recognised — and you
confirm the mapping before anything is written. Re-importing a fresh export
updates the orders already on file, matched on order number, which is how you
refresh statuses in bulk.

**Knows the product, not just the order.** Every order carries a product
number and a product name — a part number, a model, or whichever of the two
you actually use. Both are searchable, both appear in the blotter and on the
printed sheet, both come across from a spreadsheet import, and the order form
offers everything you have made before so a repeat board is picked rather
than spelled differently the second time.

**Fills in what it already knows.** A new order is dated today and its
quotation section carries the customer's contact person across as soon as
you pick the customer — both editable, neither guessed twice. Every date box
has a TODAY button beside it, and the contact field offers everyone already
on a customer record, so the same person is spelled the same way each time.

**Repeats an order without retyping it.** A repeat customer usually wants the
same board again. Pick the earlier order and the whole specification and cost
sheet come across; you give it a new number and change what has moved.

**Backs itself up somewhere else.** Point it at a second folder — another
drive, a network share — and it copies the order book there every time it
starts, keeping the last several copies. The status bar always shows when your
work was last saved and last backed up.

**Keyboard-first.** `/` to search, `1`–`9` for views, `j`/`k` to move down the
blotter, `enter` to open, `n` for a new order, `esc` to close.

## The build specification and cost sheet

Open any order and there are five tabs: **ORDER**, **SPEC**, **COST**,
**DOCS** and **HISTORY**.

**SPEC** holds what is being made:

| | |
| --- | --- |
| Quotation | quote date, quote reference, contact person |
| What it is | product type (rigid, flex, flex-rigid), class, CCL material |
| Size and panel | board size, array size, ups per array, working panel |
| Stack-up | layers, thickness and tolerance, copper inner and outer, surface finish and its thickness, impedance |
| Drilling | minimum drill size and how many, total drills, BVH and which layers |
| Order | options, quantity per lot, number of lots |

Underneath, the things that follow from it are worked out as you type: copper
weight in ounces, microns and millimetres; the thickness tolerance as a
millimetre range; how many arrays fit a working panel and how many boards that
is; how many panels the order needs and how much of each is used.

**COST** is entered in won and shown in both currencies:

- **PCB** — the total, or the price per piece. Fill in either and the other
  follows from the quantity.
- **Turnkey** — tick it and SMT, stencils and components appear. Two stencils
  are needed when both sides are populated; the price per stencil starts from
  the figure on the SETUP page.
- **Inflation** (× 1.25 by default) and **markup** (20–30%) can be applied to
  every total, and the exchange rate converts the result to dollars.

An order keeps the rates it was quoted at. Changing the exchange rate or the
markup on the SETUP page sets the starting point for new orders and never
reprices an old quote behind your back.

**PRINT SHEET** opens a clean page on white paper — the specification, the
costing and the documents on file — ready for `Ctrl+P` or saving as a PDF.

## The inbox: filing email without a mail server

This machine cannot reach your mailbox, and the app never tries. You bring
the mail to it:

1. In Outlook, drag the message into a folder on your drive, or File → Save
   As → Outlook Message Format. Several at once is fine.
2. Drop them on the INBOX page, or on the MAIL tab of an order to file them
   there directly.

`.eml` and `.msg` are both read, and `.msg` needs nothing installed — the
reader for Outlook's compound-file format is part of the app.

For each mail it works out three things, in this order:

**Who sent it.** From the internet headers where they are kept, otherwise
from Outlook's own properties, preferring the real SMTP address over the
internal directory name.

**What it says.** The reply history and the signature are cut away first —
summarising a reply otherwise gives you last week's news. What is left is
scored sentence by sentence: words that repeat are taken to be the subject
matter, sentences carrying most of them win, and a sentence with a quantity,
a date or a question in it counts for more. Two or three sentences come back,
in the order they were written. **Every word of the summary is a word from
the mail** — it is an extract, not a rewrite, so it cannot invent a promise
nobody made. It runs in a blink and works in English and Korean.

**Where it belongs.** In order of how much they are worth trusting:

| Signal | How sure |
| --- | --- |
| a PO, order or quote number you hold, in the subject line | 0.95 |
| the same, in the body | 0.85 |
| a sender you have filed to this customer before | 0.90 |
| the contact address on the customer record | 0.90 |
| the mail domain, when only one customer uses it | 0.75 |
| the customer's name written in the mail | 0.70 |
| the customer's only open order — offered, never assumed | 0.60 |

At 0.8 and above it files itself; below that it waits in the tray. Naming two
orders at once always waits, however well the sender is known. Every reason
is kept and shown next to the mail, and correcting one teaches the next: file
a stranger's mail against a customer once and the next mail from that address
goes there by itself.

Attachments worth keeping are stored as documents against the same order —
the PO inside the mail, not just the mail. Signature logos and certificates
are left out. The mail itself is stored too, so it stays searchable and can
be opened again exactly as it arrived.

Set your own addresses under SETUP → EMAIL INTAKE and mail you sent is marked
as going out rather than coming in. That is only a guess — it cannot know
about a message a colleague forwarded on, or one saved out of somebody
else's Sent folder — so every email carries a **RECEIVED / SENT** switch you
can set by hand, and the tray can be narrowed to one direction. Relabelling
one corrects the folders and cases it has been logged in, so a log never
says "received" about something you sent, and it never disturbs where the
email is filed. The confidence needed to file without
asking is set there too.

## Folders: everything that is not an order yet

The order book answers *what have we sold*. Folders answer the other half:
*what is anybody waiting on me for*.

Open one from **FOLDERS → + NEW FOLDER**, or straight from an email in the
tray — **START A FOLDER FROM THIS EMAIL** carries the subject and the summary
across. Each folder holds:

| | |
| --- | --- |
| **Topic** | the headline: what this conversation is about |
| **What they want** | the request in your own words |
| **Where it stands** | what is happening right now, and who has the ball |
| **Come back by** | the date it next needs attention |
| **Kind and status** | enquiry, quote request, sample, spec question, delivery, complaint — waiting on us, waiting on them, quoted, won, lost |
| **Worth** | what it is worth if it becomes an order |

Inside are two things. The **emails**, received and sent, filed together —
open an email in the inbox and choose the folder, and it is logged as having
arrived or gone. It works the other way round too: inside a folder, pick any
email that is not in one yet and add it.

**No order reference is needed, and no recognised sender either.** Plenty of
work arrives halfway through — a colleague forwards a thread, or the customer
writes from an address nobody has seen. Put that mail in a folder and it
takes the folder's customer as its own, and is done with: the email is filed,
the reason is recorded ("filed into F-2026-001 by hand"), and it leaves the
tray. A mail that already has a customer keeps it; the folder is a second
home for that one, not a reassignment. An email can also simply be given a
customer with no order at all, on the same screen. And the **log**: every call, meeting, note, decision and
action, each with its date, never overwritten. Any entry can carry a
follow-up date, and those appear on the FOLDERS page and the dashboard,
turning red when they pass.

Folders are shown as cards rather than rows, because a topic is a headline,
not a cell. The ones due soonest come first; the ones with no date wait at
the bottom rather than jumping the queue. `PRINT` puts the whole folder —
topic, position, log and the list of emails — on one sheet of white paper,
which is what you want in front of you before a call.

A folder can be pointed at an order once one exists, and settling it (won,
lost, closed) takes it out of what is outstanding without deleting anything.
Deleting a folder leaves its emails on file; only the folder goes.

## Disputes, defects and what you did about them

A dispute is won on the record, not on the argument. Open a case against the
order (CASES → OPEN A CASE, or the CASES tab on any order) and it holds two
things:

**The position.** What is wrong, the kind (defect, shortage, delay, wrong
spec, damage, price), severity, how many pieces are affected, the lot, the
value claimed in won, who is handling it, when an answer is due, and — as
they become known — the root cause and the resolution.

**The log.** Every call, mail, meeting, visit, note, action and decision, each
with its own date and the person on the other end. Entries are added, never
overwritten. Anything that needs chasing gets a follow-up date, and those
appear on the CASES page and on the dashboard, with the late ones in red,
until they are ticked off.

An email in the tray can be logged straight into a case, or can open a new
one with its subject and summary already filled in.

`PRINT REPORT` puts the whole thing — position, what is wrong, root cause,
resolution and the full log with every detail — on white paper. That is the
document you take into the meeting or attach to the credit note.

Case references count up within the year: `C-2026-001`. Closing an order
takes its cases with it; a closed case stops appearing in what is
outstanding, while a resolved one keeps its actions until they are done.

## Putting customers on the map

Open **CUSTOMERS**, edit one, and pick a country. That is enough: the position
and the time zone follow from it, and a city is used instead when it is one
the app knows (Shenzhen, San Jose, Stuttgart, Ansan and others). Type a
latitude and longitude yourself if you want it exact.

The clocks are shown in each customer's own zone and track daylight saving,
because they are worked out from the zone name rather than a fixed offset.

## Backups, and when it last saved

The status bar at the bottom always shows when your order book last changed
and when it was last copied somewhere else.

On the **SETUP** page, give it a backup folder — another drive, a USB stick, a
network share. From then on it takes a copy every time it starts, keeps the
last ten, and mirrors your documents alongside. **BACK UP NOW** does it on
demand.

The copy is taken through SQLite's own backup, not by copying the file, so it
always holds the changes you made seconds earlier. A backup is a complete,
working order book: point the app at that folder and it opens.

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

## A word about network drives

A mapped drive that points at a file server — `G:` that is really
`\\SomeServer\your-folder` — is not a disk with a different letter, and
Order Tracker should not run from one.

- SQLite, the database underneath it, says its file locking cannot be relied
  on over a network filesystem, and the write-ahead log this app uses does
  not work over one **at all**, because it needs shared memory a share
  cannot provide.
- Git cannot do the atomic renames a clone needs on many shares. It fails
  partway with `Rename from '.git/config.lock' to '.git/config' failed`.

The app spots one and says so — on the SETUP page, in `setup.py`, and in
`doctor.py`, which reports whether the app folder and the data folder are on
a network location.

**A network drive is the right home for your backups, not your live data.**
Keep the app and its data on the machine, then set the backup folder on the
SETUP page to the share. You get a complete, working order book copied there
every time the app starts — which is what most people wanted from "keep it on
the shared drive" in the first place.

### If you run it from a share anyway

It is your data, so nothing refuses. The app does what it can to make it
survivable:

- **The journal mode changes.** Write-ahead logging cannot work on a share,
  so a database going there is converted to the older rollback journal at
  the moment it is copied — while the file is new and nothing has it open,
  which is the one time the change is certain to take. Every write also
  waits for the disk rather than the cache.
- **Only one machine at a time.** The running copy leaves a note in the data
  folder and refreshes it. Another machine finding a fresh note stops and
  says whose it is. A session that dies clears itself after five minutes,
  and `--force` overrides it. Two machines writing to one database on a share
  is the way to corrupt it, and this catches the honest version of that.
- **Git stays behind.** It cannot do the renames a clone needs on a share, so
  the move leaves the history out by default when the destination is one.
  Update by pulling into a copy on the machine and copying across again.
- **Set a backup folder on a local disk.** The advice inverts: with the live
  book on the share, the safe copy belongs on the machine. The app says so at
  startup if no backup folder is set.

A USB stick or an external disk is a different matter: those are local
filesystems and portable mode works on them properly.

## Running it from a personal or USB drive

The whole thing is portable — plain Python files, a database and your
documents, with nothing installed into Windows.

**The easiest way is from inside the app.** Open **SETUP** (`6`), find *Move
it to another drive*, type the folder and press **CHECK THE FOLDER**. It
reports what would be copied and where, without writing anything. Then press
**COPY EVERYTHING THERE**.

When it finishes, click **QUIT** and open Order Tracker from your desktop
icon — it points at the new folder now. No command prompt, and nothing to get
into the right directory.

If a folder will not work, the reason appears on the page rather than as an
error in a black window, which is usually enough to tell a drive permission
apart from anything else.

The same thing from the command line, for anyone who prefers it:

```
py move_to.py "G:\my folder\Order Tracker"
```

That copies the app and everything you have stored to the new folder,
switches the copy to portable mode, and repoints the desktop shortcut at it.
Nothing is deleted — the old folder stays until you check the copy works and
remove it yourself.

**Everything comes with it.** Your orders and documents, the settings from the
SETUP page (they live in the database), your name on the welcome screen, and
the git history, so `git pull` still updates the app from its new home.

**Close Order Tracker before using the command-line version.** It refuses to
run while the app is open, because copying a database that is being written to
is the one way this can leave you worse off than you started. The button
inside the app has no such problem: the app reading its own database through
SQLite's backup call is safe, and it is only writing to the new folder.

To test a destination before committing to it — useful if a copy has already
gone wrong once:

```
py move_to.py "G:\my folder\Order Tracker" --check
```

That reports whether the folder can be written to and what would be copied,
and copies nothing. If the copy itself fails, it names the files it could not
write rather than printing a wall of Python. `--no-git` leaves out the git
history, which is most of the files and none of the app.

### Doing it by hand

If the drive refuses Python altogether but File Explorer copies to it happily
— which happens on some company and network drives — ask for the plan
instead:

```
py move_to.py "G:\my folder\Order Tracker" --manual
```

That writes nothing. It prints exactly which folders to copy and where, with
the number of orders and documents in each so you can check the copy
afterwards. It names your data folder specifically, because it is usually
**not** inside the app folder and is the step people miss.

Once you have copied everything across, open a Command Prompt in the new
folder — click the address bar in File Explorer, type `cmd`, press Enter —
and run:

```
py move_to.py --finish
```

That marks the copy portable, carries your welcome name over, repoints the
desktop icon, and tells you how many orders it found. It never touches the
folder you copied from, so if anything is wrong the original is still there.

`py setup.py --portable` does the portable part on its own, if that is all
you need.

That writes a `portable.txt` marker beside `run.py`. While that file is
there, orders and documents stay inside the app folder, any saved location is
ignored, and the settings file moves into the folder too — so the folder works
whatever drive letter it gets on whatever machine, and your welcome name comes
with it. Move it, copy it, back it up — it is one folder.

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
python3 run.py --where         # print where the data is kept and what is in it
python3 run.py --here          # keep everything in this folder from now on
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

It reports whether Windows' ransomware protection is switched on, tries
several other folders and tells you which of them will hold your orders,
and hands you the command to switch to one.

The usual culprit on Windows is something guarding the folder rather than
anything in the app. Controlled folder access blocks **per application**,
which is why `git` can fill a folder that `python.exe` is then refused a
single file in. Either allow it — Windows Security → Virus & threat
protection → Ransomware protection → Allow an app through Controlled folder
access → add your `python.exe` — or keep the data somewhere it does not
watch, which takes one command and is remembered:

```
py setup.py --folder "%LOCALAPPDATA%\OrderTracker"
```

A folder left behind by an earlier attempt can also carry permissions that
deny writes; the check says whether the folder was already there, and
deleting it is then the whole fix.

### If your work computer only lets approved programs write files

Some managed machines allow `git` to fill a folder and then refuse
`python.exe` a single file in the same folder. The check above names it when
it can. There is nothing to fix in the app: put the whole thing on a drive
you own — a personal network drive is fine for this — and run it from there.

**Copy it in File Explorer**, not with a command. The same machine that
refuses Python a file will copy one quite happily through Explorer:

1. Open `C:\Users\<you>\Order-tracker`, press Ctrl+A then Ctrl+C.
2. Open `G:\your folder\Order Tracker` and press Ctrl+V.

Then, inside the copy, one command tells it to keep everything there:

```
cd /d "G:\your folder\Order Tracker"
py run.py --here
```

`--here` marks the copy portable, brings your welcome name across and
starts it. From then on the database, the documents, the settings file and
the scratch folder for temporary work all live in that one folder, and
nothing is written to the system disk at all. Afterwards just `py run.py`.

**To update it later**, double-click **`update.bat`**. It is in both folders,
so run it from whichever one you are in:

1. it fetches the newest version into the downloaded folder (the one with
   the download history in it), and
2. copies the program across to the copy you run from.

The first time it asks where the other folder is; paste the path and it
remembers. Everything after that is one double-click.

It replaces the program only. `data`, `demo-data`, `settings.json` and
`portable.txt` are excluded on both sides, and nothing is ever deleted —
files are only added or replaced, so an update cannot cost you your order
book. It refuses to write into a folder that is not an Order Tracker folder,
and it copies with Windows' own `robocopy` rather than through Python, so a
machine that only allows approved programs still lets it through.

If the desktop refuses the shortcut — it will, on a machine like this — a
launcher called `Order Tracker.bat` is written into the app folder instead.
Double-click it to start, or drag it to the taskbar.

`py move_to.py "G:\your folder\Order Tracker" --no-git` does the copying
for you and is worth trying first — but on a machine locked down this hard,
Windows may refuse to start that script at all, which looks like a bare
"access denied" with nothing else printed. That is the security software
stopping it before any of the code runs, and Explorer plus `--here` is the
way round it. `py doctor.py` says which of the tools this machine will run.

If the usual settings folder is closed to Python, `settings.json` is written
beside `run.py` instead and read back from there — you lose nothing. If the
system temporary folder is closed too, the scratch work that reading a PDF
out of an email needs happens in `data/.scratch` next to your orders.
`py doctor.py` lists every place the app writes and says which of them this
machine allows.

Two things to know when the drive is a network share: keep one machine in it
at a time (the app leaves a note in the folder and says so if another machine
has it open), and set a backup folder under SETUP so there is a second copy
somewhere. `git clone` and `git pull` cannot be relied on over a share, which
is why the copy above leaves the git history behind; to update later, pull on
the machine's own disk and run `move_to.py` again.

**On Windows** use `py run.py`. If Python isn't installed, get it from
python.org and tick "Add Python to PATH" during setup.

**On macOS** Python 3 is already there. Open Terminal, `cd` to this folder and
run the command above.

## Where your data lives

Wherever you pointed `setup.py`, in one folder:

```
<your folder>/
  data/
    orders.db        all orders, customers, email, cases and extracted text
    documents/       the original files, exactly as you dropped them in
    .scratch/        temporary working files, cleared as it goes
  demo-data/         the sample order book, kept well away from the real one
```

If you never ran `setup.py`, it sits beside the app instead. `python3 run.py
--where` always tells you.

Back it up by copying that folder. Move it to another machine by copying it
there.

Everything you change on the SETUP page is kept in `orders.db`, so it travels
with your data. The only thing kept elsewhere is a small settings file
recording your chosen folder and welcome name:

| | |
| --- | --- |
| Windows | `%LOCALAPPDATA%\OrderTracker\settings.json` |
| macOS | `~/Library/Application Support/OrderTracker/settings.json` |
| Linux | `~/.config/order-tracker/settings.json` |
| **Portable** | `settings.json` beside `run.py`, so nothing is left behind |

If the machine refuses Python that folder, the file is written beside
`run.py` instead and read back from there.

Data folders are excluded from git, so customer information is never
committed.

## Starting over

To remove it from a machine:

```bash
python3 uninstall.py           # Windows: py uninstall.py
```

On its own it deletes nothing — it lists every piece it can find, with what
each one holds, including the data folder (which is usually **not** inside the
app folder) and the settings file (which is outside it by design). To go
ahead:

```
py uninstall.py --delete
```

It asks you to type `DELETE` before anything goes. Your orders are the only
thing here that cannot be downloaded again, so save a copy first if there is
any doubt:

```
py uninstall.py --delete --save-to "D:\Order Tracker copy"
```

That writes a complete, working order book — `orders.db` plus every document
— to the folder you name, before anything is removed. Drop it in as `data/`
in a fresh install and you are back where you were.

A backup folder is never touched: it is somewhere else on purpose. The app
folder itself is left for you to delete in File Explorer, because the script
is running from inside it.

## The welcome screen

`setup.py` asks for a name to greet you with at startup. To change it later,
run `setup.py` again, or edit `welcome_name` in the settings file above.
Setting `show_welcome` to `false` there turns the splash off entirely.

## Making it yours

Most of it is on the **SETUP** page (`6`), no code involved:

- **Money** — exchange rate, the inflation multiplier, the default markup, the
  stencil price and its expected range.
- **Alerts** — how many days ahead counts as due soon, how long untouched
  counts as stalled, the unusable margin around a working panel.
- **Lists on the order form** — working panels (`CODE | width | height`),
  surface finishes, CCL materials, product types and classes. One per line;
  add your own and they appear in the drop-downs straight away.
- **Welcome screen** — the name you are greeted with, and whether it shows.
- **Backups** — the folder, how many copies to keep.

These are stored with your data, so they travel with it to another drive.

For the rest, open `ordertracker/config.py`. It is meant to be edited:

- **`PIPELINE`** — the stages an order moves through. Rename them to whatever
  your business says. The blotter, the board and the stage buttons all follow.
- **`DATE_INPUT_ORDER`** — `"MDY"` reads `03/12/2026` as 3 March;
  `"DMY"` reads it as 12 March. Unambiguous dates (`2026-12-03`, `3-Dec-2026`)
  always work either way.
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
- **The map is a backdrop, not an atlas.** The coastlines are drawn by hand and
  deliberately rough. Customer pins are plotted from real coordinates, so they
  land in the right place regardless.
- **It doesn't talk to your ERP, or to your mailbox.** Data arrives by import,
  by drag-and-drop, or by typing. Email is read from messages you save out and
  drop in; there is no connection to a mail server, by design — on a locked
  machine there could not be one, and nothing here leaves the computer.
- **The mail summary is an extract, not a rewrite.** It picks the sentences
  that carry the most of what the mail keeps saying. On a mail with no prose
  in it — a bare "see attached" — there is nothing to pick, and it says so.
  It cannot read a scanned letter, for the same reason as above.
- **Matching an email to an order is a guess, and says so.** It files what it
  is sure of and shows its reasons; the rest waits for you. It has no idea
  what your customers call things until you tell it once.
- **Legacy `.doc` and `.xls`** (the old binary formats) can't be read for text.
  Save as `.docx` / `.xlsx` if you need their contents searchable.

## Developing

```bash
python3 -m unittest discover tests     # 295 tests, no dependencies
```

The pieces:

```
run.py                      entry point
setup.py                    first-run wizard: storage folder, shortcut, name
move_to.py                  copy the app and its data to another drive
update.bat                  Windows: fetch the newest version and copy it
                            over the copy you run from
uninstall.py                find every piece of it and remove them
doctor.py                   startup check when something will not run
ordertracker/
  config.py                 pipeline, thresholds, paths — edit this first
  mail.py                   read a saved email, summarise it, file it
  outlook.py                Outlook .msg reader, written from the format up
  cases.py                  disputes and defects, and the log of each one
  threads.py                a folder per running conversation with a customer
  chase.py                  the dated log both of those keep
  briefing.py               what needs doing today, from everywhere at once
  settings.py               remembered storage folder and welcome name
  shortcut.py               desktop shortcut for Windows, macOS and Linux
  prefs.py                  the settings page's values, stored with the data
  db.py                     SQLite schema and full-text indexes
  orders.py                 order logic, alerts, search, dashboard
  pcb.py                    build specification, conversions and costing
  printsheet.py             the printable specification and cost sheet
  geo.py                    countries, positions and time zones
  drives.py                 telling a local disk from a network share
  inuse.py                  one machine at a time on a shared folder
  backup.py                 the second copy, and when things last saved
  relocate.py               copying the app and its data to another drive
  documents.py              file storage, classification, auto-filing
  importer.py               CSV / Excel import and column matching
  xlsx.py                   a small read-only .xlsx reader
  multipart.py              file-upload parsing
  server.py                 HTTP server and JSON API
  sampledata.py             the --demo order book
  extract/                  text out of PDFs, emails, Office files, HTML
web/                        the single-page front end (no build step)
  world.js                  hand-drawn coastlines, so no map data is fetched
  map.js                    the map, the day/night line, sun and moon
  spec.js                   the specification form and the cost sheet
  setup.js                  the settings page
  inbox.js                  the email tray
  cases.js                  disputes and their logs
  folders.js                the enquiry folders and what is in them
assets/                     app icon (regenerate with tools/make_icon.py)
tests/                      the test suite
```

Everything uses the Python standard library only. That is deliberate: it means
this still runs in five years on a machine with nothing installed on it.
