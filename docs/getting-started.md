# Getting started with Alba OS Prompt Intelligence

**Start here if you have never programmed.** This guide takes you from
nothing to a running Alba demo, one small step at a time. You do not need
to know Python, Docker, or databases. Every step has one command to copy,
and tells you what you should see after it.

If you already know your way around a terminal, the short version is in
the [README quickstart](../README.md#demo-in-5-minutes). This guide is
the long, careful version of the same steps.

> **Which version is this guide for?** Demo v0.1.0, on the
> `experimental/demo-close` branch. If you cloned the repository and this
> file is missing, run `git checkout experimental/demo-close` inside the
> project folder first. If you are reading this file, you are already on
> the right branch.

## What Alba does, in plain words

Alba helps you write a good instruction — called a *prompt* — for an
image or video generator.

Imagine you want an AI tool to draw the same virtual host again and
again: same face, same cobalt dress, same hairstyle. If your instruction
is vague, the face or the dress changes every time. Alba keeps a small
library of past examples: prompts that worked (approved) and prompts
that failed (rejected). When you write a short request, called a
*brief*, Alba looks up the most similar approved examples, warns you
about the failures to avoid, and writes one clear, structured
recommendation. Then a human — you — reads it and decides: **Approve**,
**Revise** once with a comment, or **Reject**.

Three things Alba does **not** do:

- It does **not** draw pictures or videos. It only writes the
  instruction for a tool that does.
- It does **not** work on its own. Nothing is used until a human
  approves it.
- It does **not** send your data to the internet. Everything runs on
  your own computer, on the address `http://127.0.0.1:8000/`. Only
  people on your computer can open it.

The demo tour uses three ready-made cases. You will try all three in
[Step 8](#step-8--try-the-three-demo-briefs):

| # | Case | What you do | What should happen |
| --- | --- | --- | --- |
| 1 | Approve — cobalt host | Start it, read the recommendation | Approved cobalt-host examples are found, and the recommendation is well supported. Approve it. |
| 2 | Revise — station frames | Start it, then choose **Revise** once | The recommendation reaches human review. Try feedback such as “Add more negative space without changing identity or movement.” |
| 3 | Reject — no evidence | Start it, read the result | The Cobalt Lounge project has no logo examples, so no approved evidence is found and confidence is low. This is a safe case to reject. |

## Before you start — what you need

You need four programs installed on your computer. None of them is
Alba itself. Alba is the code you will download in Step 3. Think of
these four as tools Alba needs to run:

| Program | What it is, in one sentence | Where to get it (official site) | Check it is installed |
| --- | --- | --- | --- |
| Git | A tool that downloads a copy of a code project. | <https://git-scm.com/downloads> | `git --version` |
| uv | A tool that installs Python and the Python libraries Alba needs. You do **not** need to install Python yourself. | <https://docs.astral.sh/uv/getting-started/installation/> | `uv --version` |
| Docker Desktop | A tool that runs a ready-made database (PostgreSQL) in a sealed box, called a *container*, on your computer. | <https://www.docker.com/products/docker-desktop/> | `docker --version` and `docker info` |
| Ollama | A tool that runs AI models on your own computer. **Only needed for real-model mode.** The default demo does not need it. | <https://ollama.com/download> | `ollama --version` |

You also need:

- A Windows, macOS, or Linux computer. This guide is written for
  **Windows with PowerShell** first. Linux and macOS steps are in
  [Running on Linux or macOS](#running-on-linux-or-macos).
- An internet connection the first time only. The first run downloads
  the database image and the Python libraries. After that, the demo
  itself runs offline (except real-model mode, which also needs the
  models downloaded once).
- Free space on your disk, and ports `5432` (database) and `8000`
  (web page) free. A *port* is like a numbered door on your computer
  that a program uses. If another program already uses one of those
  doors, see [Troubleshooting](#troubleshooting).

### Install the four programs

Do them one at a time. After each install, **close PowerShell
completely and open a new one** before you test it. New programs are
often only found by a fresh window.

**1. Git (Windows).** Open <https://git-scm.com/downloads>, download
the Windows installer, and run it. Accept the default options on every
screen — you do not need to change anything. Then open a new
PowerShell window and type:

```powershell
git --version
```

You should see a line with a version number, for example starting
with `git version`. If PowerShell says the command is not recognized,
Git did not finish installing, or you are in an old PowerShell window
that was open before the install. Close it and open a new one.

**2. uv (Windows).** In PowerShell, copy and paste this command
exactly. It comes from the official uv installation page:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Wait until it says the install is done. Then close PowerShell, open a
new one, and type:

```powershell
uv --version
```

You should see a line with a version number. `uv` also installs
Python 3.12 for you when Alba needs it. Do not install Python
separately.

**3. Docker Desktop (Windows).** Open
<https://www.docker.com/products/docker-desktop/>, download Docker
Desktop, and run the installer. Accept the defaults. If it asks you to
restart your computer, restart it. Then open Docker Desktop from the
Start menu and wait until it finishes starting. Then, in a new
PowerShell window, type:

```powershell
docker --version
docker info
```

`docker --version` should print a version number. `docker info`
should print information about Docker. If `docker info` shows an
error saying Docker is not running, Docker Desktop is still starting,
or it is not open. Wait a minute and try again.

**4. Ollama — only for real-model mode.** Skip this step for now if
you just want the default demo. You can come back to it later in
[Real-model mode](#real-model-mode-ollama). To install it, open
<https://ollama.com/download>, download the installer for your
system, run it, then check it in a new PowerShell window with:

```powershell
ollama --version
```

## Step 1 — Open PowerShell

On Windows, click the Start menu, type `PowerShell`, and open
**Windows PowerShell**. A dark window with a blinking cursor appears.
That window is called a *terminal*. You type commands there, and the
computer answers with text.

From now on, every grey box in this guide is one command to type in
that window. Type it exactly, then press Enter. Do not type the
`PS>` part — that is just the prompt the window shows you.

## Step 2 — Check the tools are there

In PowerShell, type these three commands, one at a time. Each one
should print a version number. If one says “not recognized”, go back
to the install step for that program.

```powershell
git --version
uv --version
docker --version
```

Then check Docker is actually running, not just installed:

```powershell
docker info
```

If `docker info` prints information, you are ready. If it prints an
error, open Docker Desktop and wait until it has finished starting,
then try again.

## Step 3 — Download Alba (clone the repository)

Type this command. It downloads a copy of the Alba project into a
new folder called `alba-os-prompt-intelligence` in your current
folder. `git clone` means “download a copy of this project”.

```powershell
git clone -b experimental/demo-close https://github.com/zeedher-aisuites/alba-os-prompt-intelligence.git
```

You should see lines about downloading. Wait until the prompt returns
(that is, until you can type again). If you see an error about the
network, check your internet connection and try again.

> The `-b experimental/demo-close` part matters: it tells Git to
> download the experimental demo branch. A plain `git clone` downloads
> the `main` branch, which does not have the demo-close work yet. If
> you already cloned without `-b`, run `cd
> alba-os-prompt-intelligence` and then `git checkout
> experimental/demo-close` before continuing.

## Step 4 — Go into the project folder

```powershell
cd alba-os-prompt-intelligence
```

`cd` means “change directory”, that is, go into that folder. From
now on, every command in this guide must be run from inside this
folder. If a command says a file is not found, the most common cause
is that you are in the wrong folder. Type `pwd` to see where you are:
it should end in `alba-os-prompt-intelligence`.

## Step 5 — Start the demo (one command)

Type:

```powershell
.\scripts\demo.ps1
```

That is the whole start command. It does, in order: create a settings
file called `.env` from `.env.example` if you do not have one, start
the database, install the Python libraries, apply the database
changes, set up the workflow checkpoints, load the demo data, build
the demo search index, and start the web page.

**The first run is the slowest.** It downloads the database image
and the Python libraries. Do not close the window while it works.
Leave it alone until you see the “Alba OS demo is ready” message
in Step 6.

### If Windows blocks the script (ExecutionPolicy)

If you see an error like this:

```text
.\scripts\demo.ps1 : File ... cannot be loaded because running scripts
is disabled on this system.
```

That is Windows protecting you from running script files by default.
It is not an Alba error, and Alba is not broken. Use this one-time
workaround instead. It runs the script once, without changing any
setting on your computer:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1
```

What that command means, word by word: start a new PowerShell,
ignore the “do not run scripts” rule just for this one run
(`-ExecutionPolicy Bypass`), and run this file (`-File`).

If you would rather allow scripts permanently for your own user
account, run this once instead, answer `Y` when it asks, and then run
`.\scripts\demo.ps1` normally from then on:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

That changes one setting for your user only: scripts you wrote
yourself, or scripts from your own computer, are allowed to run.
Scripts downloaded from the internet still need to be unblocked
first. If you are unsure, use the one-time workaround above — it is
the safer choice.

## Step 6 — Wait, and read the messages

While the demo script runs, it prints one line for each phase. You
should see these lines, in this order:

```text
Starting PostgreSQL (provider: fake)...
Installing Python dependencies...
Applying database migrations...
Setting up durable workflow checkpoints...
Seeding demo data (idempotent)...
Rebuilding embeddings with the deterministic fake provider (diagnostic only, not EmbeddingGemma evidence)...
Alba OS demo is ready (provider: fake).
  Web interface: http://127.0.0.1:8000/
  OpenAPI docs:  http://127.0.0.1:8000/docs
  Health:        http://127.0.0.1:8000/health
```

What each phase means:

- **Starting PostgreSQL** — Docker starts the database. The first
  time, it downloads the database image.
- **Installing Python dependencies** — `uv` installs the libraries
  Alba needs, at the exact versions in `uv.lock`.
- **Applying database migrations** — Alba creates its tables in the
  database. A *migration* is a small, numbered change to the database
  structure.
- **Setting up durable workflow checkpoints** — Alba prepares the
  place where a workflow can safely pause and wait for a human.
- **Seeding demo data** — Alba loads the ready-made demo projects
  and examples: `cobalt-lounge`, `alba-product-studio`, and
  `retrieval-evaluation-lab`. *Seeding* means loading starter data.
  Running it twice is safe; it skips data that is already there.
- **Rebuilding embeddings** — Alba builds the search index for the
  demo examples, using the fake provider in the default mode.

When you see `Alba OS demo is ready`, **do not close the PowerShell
window**. The web page only works while that window is open and the
script is running. Leave the window open in the background while you
use Alba in your browser.

If the script stops with an error instead, do not guess. Find the
error in [Troubleshooting](#troubleshooting).

## Step 7 — Open Alba in your browser

Open your web browser (Edge, Chrome, Firefox, or any other) and go
to exactly this address:

```text
http://127.0.0.1:8000/
```

You should see the Alba home page, titled “Alba OS Prompt
Intelligence”, with a **New workflow** button, a list of the available
projects, and a “Dependency readiness” section that says **Ready**.

`127.0.0.1` means “this computer”. Alba only listens on this
computer, so nobody else on your network can open it. That is on
purpose: this demo has no login, so it must never be shared on the
internet.

### How to know it works — the health pages

These two pages are a quick self-test. Open them in your browser:

1. <http://127.0.0.1:8000/health> — you should see a small text
   page saying the service is `ok`, with the service name
   “Alba OS Prompt Intelligence MVP” and the environment
   `development`.
2. <http://127.0.0.1:8000/health/database> — you should see a
   small text page saying the database is `ok` and `reachable`.
   This page checks that Alba can really talk to PostgreSQL.

If the first page works but the second one shows an error, the web
page is running but the database is not. See
[Troubleshooting](#troubleshooting).

## Step 8 — Try the three demo briefs

On the home page, click **New workflow**. You will see a form with
a project list, a query type, a brief box, and constraints, plus three
buttons at the top:

- **1 · Approve — cobalt host**
- **2 · Revise — station frames**
- **3 · Reject — no evidence**

Clicking one of these buttons fills the form for you. You do not
need to type anything. Then click **Start workflow** at the bottom
of the form.

### Case 1 — Approve

1. Click **1 · Approve — cobalt host**. The form fills in the
   `retrieval-evaluation-lab` project, the `ai_influencer` query
   type, the brief about a cobalt-dressed virtual host, and two
   constraints: “Preserve the same face” and “Keep the approved
   cobalt outfit”.
2. Click **Start workflow**. Wait a moment. The workflow runs, then
   pauses and waits for you.
3. Read the page. You should see a **Recommendation** (the proposed
   prompt), a **Rationale** (why it was written that way),
   **Approved evidence** (the past examples it used), and
   **Rejected evidence** with a warning (the failures it avoided).
   The recommendation should be well supported by the approved
   evidence.
4. At the bottom, click **Approve**. The workflow finishes. This is
   the happy path: good evidence, good recommendation, human says
   yes.

### Case 2 — Revise

1. Go back to **New workflow** and click
   **2 · Revise — station frames**. The form fills in the
   `retrieval-evaluation-lab` project, the `video_frame` query type,
   and a brief about two travelers crossing a station, keeping
   wardrobe and movement the same.
2. Click **Start workflow** and wait until it pauses for review.
3. This time, do not click Approve. Type feedback in the
   **Feedback** box, for example: “Add more negative space without
   changing identity or movement.” Feedback is required for a
   revise — the box is there for exactly this.
4. Click **Revise**. Alba runs once more, using your feedback, and
   then pauses again. You can only revise once per workflow. After
   that, you must approve or reject.

### Case 3 — Reject

1. Go back to **New workflow** and click
   **3 · Reject — no evidence**. The form fills in the
   `cobalt-lounge` project, the `logo` query type, and a brief about
   a geometric Alba monogram.
2. Click **Start workflow** and wait until it pauses for review.
3. Read the result. Cobalt Lounge has no logo examples, so no
   approved evidence is found and confidence is low. Alba does not
   invent evidence — it says so. Click **Reject**. This is the safe
   failure: when there is no good evidence, the honest answer is no.

After each case, you can go to **Workflows** (the history page) to
see the finished workflow, or start the next case.

## Real-model mode (Ollama)

The default demo uses *fake* providers. They are fixed, predictable
stand-ins: they prove the workflow, the search, and the human review
work end to end. Fake results are **diagnostic only**. They must
never be presented as real EmbeddingGemma or Qwen quality.

Real-model mode uses two small models that run on your computer
through Ollama:

- `embeddinggemma:300m` — turns text into numbers for search.
- `qwen2.5:3b` — writes the recommendation.

Do this only after the fake demo works. The models are large
downloads, so this step needs internet and time.

**Step 1 — Install Ollama.** Open <https://ollama.com/download>,
download the installer for your system, and run it. Then, in a new
PowerShell window, check it:

```powershell
ollama --version
```

**Step 2 — Download the two models.** Run these two commands, one
at a time, and wait for each to finish. They are large, so be
patient:

```powershell
ollama pull embeddinggemma:300m
ollama pull qwen2.5:3b
```

**Step 3 — Check both models are there:**

```powershell
ollama list
```

You should see both model names in the list. If one is missing,
repeat its `ollama pull` command.

**Step 4 — Start the demo in real-model mode.** Stop the fake demo
first (Ctrl+C in the PowerShell window, see
[Stop the demo](#stop-the-demo)), then run:

```powershell
.\scripts\demo.ps1 -Ollama
```

The script checks that both models are installed and stops with a
clear message if one is missing. It never downloads models by
itself. Then repeat the three demo briefs from Step 8. The pages
look the same; only the recommendation text and the speed change,
because a real model is now doing the work.

## Import your own corpus

A *corpus* is your own collection of past prompt examples, in a
spreadsheet file (CSV). The template is
`data/templates/prompt-corpus-v1.csv` in the project. The full rules
for every column are in
[docs/data/prompt-corpus-v1.md](data/prompt-corpus-v1.md) — read that
file before you prepare a real corpus.

The short version, step by step:

**Step 1 — Copy the template.** Make a copy of
`data/templates/prompt-corpus-v1.csv` and name it, for example,
`my-corpus.csv`. Keep your own file outside the project folder if
you do not want it in Git. Do not edit the original template file.

**Step 2 — Change the project on every row.** Every row has a
`project_slug` column. All rows in one file must use the same
project, and that project must already exist in Alba. Use one of
the seeded projects, for example `retrieval-evaluation-lab`.
(The example rows in the template use `example-project`, which does
not exist after seeding — change that value on every row to your
chosen project.)

**Step 3 — Fill in your examples.** One row is one past example.
Fill in `prompt`, `expected_result`, `status` (`approved`,
`in_review`, or `rejected`), `platform`, `generation_method`,
and `tags`. Tags are separated by the `|` character, for example
`identity|outfit|editorial`. Save the file as UTF-8 CSV. If you use
a spreadsheet program, choose “Save as CSV” and UTF-8 encoding if
it asks.

**Step 4 — Check the file without changing anything.** This command
only reads your file and reports problems. It does not touch the
database:

```powershell
uv run python -m scripts.validate_prompt_corpus my-corpus.csv --strict
```

Fix every error it reports, then run it again until it passes.

**Step 5 — Dry run the import.** This shows what would be imported,
without writing anything:

```powershell
uv run python -m scripts.import_prompt_corpus my-corpus.csv --project retrieval-evaluation-lab --dry-run
```

**Step 6 — Import for real:**

```powershell
uv run python -m scripts.import_prompt_corpus my-corpus.csv --project retrieval-evaluation-lab --strict
```

The import is idempotent: running it twice does not create
duplicates. Rows are skipped if the same project and prompt were
already imported, or if the `external-id:<id>` tag is already there.

**Step 7 — Build embeddings for the new examples.** Imported
examples have no search numbers until you build them. Run:

```powershell
uv run python -m scripts.rebuild_embeddings --project retrieval-evaluation-lab --provider fake
```

Use `--provider ollama` instead of `--provider fake` if you are in
real-model mode. After this step, your examples appear in the
library (`/library` in the web interface) and can be retrieved by
new workflows.

Two honest limits of the importer, so they do not surprise you:
`source_reference` and `created_at` have no place to be stored in
this version, and are reported as not stored. And the web library
is read-only: you can look at examples there, but you cannot add,
edit, or delete them from the web page. Use the importer above.

## Stop the demo

1. Go to the PowerShell window where the demo is running.
2. Press **Ctrl+C** (hold Ctrl, press C). The web page stops.
3. Close the browser tab if you like. The database keeps running
   in the background — that is normal.

To stop the database too, run this in the project folder, in a new
PowerShell window:

```powershell
docker compose stop
```

Your data is kept. Next time you run `.\scripts\demo.ps1`, your
data is still there.

## Reset the demo and uninstall cleanly

**Reset all demo data and start clean.** This deletes every project,
example, and workflow in the demo database. It cannot be undone.
Stop the demo first (Ctrl+C), then run:

```powershell
docker compose down --volumes
```

Then run `.\scripts\demo.ps1` again to start from an empty, freshly
seeded demo.

**Uninstall Alba completely.**

1. Stop the demo (Ctrl+C).
2. Run `docker compose down --volumes` to delete the demo data.
3. Optionally, remove the downloaded database image, so nothing of
   Alba is left in Docker:

   ```powershell
   docker image rm pgvector/pgvector:pg17
   ```

   Skip this step if you plan to use Alba again — the image will
   just be downloaded again next time.
4. Delete the project folder `alba-os-prompt-intelligence`. That
   removes the code, the settings file `.env`, and the Python
   environment (`.venv`).
5. If you also want to remove the tools themselves, uninstall Git,
   uv, Docker Desktop, and Ollama from Windows Settings, like any
   other program. Alba does not install anything outside its own
   folder except the Docker image and volume above.

## Troubleshooting

Find your error message below. Each row has the symptom (what you
see), the cause (in plain words), and the exact fix.

| Problem | Symptom | Cause | Fix |
| --- | --- | --- | --- |
| `uv` not found | PowerShell says `uv` is not recognized as a command, or the demo script says `Missing required command: uv`. | uv is not installed, or PowerShell was opened before uv was installed. | Install uv from <https://docs.astral.sh/uv/getting-started/installation/>. Then close PowerShell completely and open a new one. Run `uv --version` again. |
| `docker` not found | PowerShell says `docker` is not recognized, or the demo script says `Missing required command: docker`. | Docker Desktop is not installed, or PowerShell was opened before it was installed. | Install Docker Desktop from <https://www.docker.com/products/docker-desktop/>. Close PowerShell, open a new one, and run `docker --version` again. |
| Docker Desktop not running | `docker info` shows an error, or the demo script fails at “Starting PostgreSQL”. | Docker Desktop is installed but not started yet, or it is still starting. | Open Docker Desktop from the Start menu and wait until it finishes starting. Run `docker info` again — it should print information, not an error. Then run the demo script again. |
| Port 5432 or 8000 already in use | The demo fails while starting PostgreSQL, or the web page fails to start, with an error about the address already being in use. | Another program is already using port `5432` (database) or `8000` (web page). A port is like a numbered door; only one program can use each door. | Find the program using the port, for example `netstat -ano \| findstr :8000` in PowerShell (use `:5432` for the database port). The last number on the line is the process ID. Stop that program, or close it in Task Manager. Then run the demo script again. |
| Ollama model missing | The demo script says `Missing Ollama model: embeddinggemma:300m` or `Missing Ollama model: qwen2.5:3b`. | You started the demo with `-Ollama`, but that model was never downloaded. The script never downloads models by itself. | Run `ollama pull embeddinggemma:300m` and `ollama pull qwen2.5:3b`, then check with `ollama list`. Start the demo again with `.\scripts\demo.ps1 -Ollama`. Or run the default fake demo instead, with no `-Ollama`. |
| Script cannot be loaded (ExecutionPolicy) | PowerShell says the `.ps1` file “cannot be loaded because running scripts is disabled on this system”. | Windows blocks script files by default, for safety. | Use the one-time workaround: `powershell -ExecutionPolicy Bypass -File .\scripts\demo.ps1`. See [Step 5](#step-5--start-the-demo-one-command) for the permanent option. |
| Database connection refused / Postgres not healthy | `/health/database` shows an error, or a command says the database connection was refused. | The database container is not running, or it is still starting. | In the project folder, run `docker compose ps` to see if `postgres` is running and healthy. If not, run `docker compose up -d --wait postgres` and wait. If it keeps failing, run `docker compose logs postgres` and read the last lines for the real error. |
| Page does not open at `http://127.0.0.1:8000/` | The browser says the page cannot be reached, or it keeps loading forever. | The demo script is not running anymore (the PowerShell window was closed, or Ctrl+C stopped it), or you typed the address wrong. | Check the PowerShell window: it must still be open and show “Alba OS demo is ready”. If it was closed, run `.\scripts\demo.ps1` again. Type the address exactly: `http://127.0.0.1:8000/` — with `http://`, the numbers, the dots, and the final `/`. |
| Demo brief says the project is not seeded | The browser shows an alert like `Demo project "retrieval-evaluation-lab" is not seeded yet`. | The demo data was not loaded. Either the demo script did not finish, or the database was reset after the web page started. | Stop the demo (Ctrl+C), run `.\scripts\demo.ps1` again from the beginning, and wait for “Alba OS demo is ready” before opening the browser. |

If your error is not in this table, copy the full error message
from the PowerShell window. The last few lines usually say what
went wrong. Check first whether Docker Desktop is open and whether
you are inside the `alba-os-prompt-intelligence` folder (`pwd`
should end with that name).

## What this demo does not do

- No login, no password protection, no encryption (TLS), and no
  support for several users at once. Do not share it on the
  internet, and do not change the address from `127.0.0.1` to
  `0.0.0.0`. `0.0.0.0` would mean “everyone on the network can
  reach it”.
- No image or video generation or analysis, no ANN index, no
  chunking, reranking, or hybrid search, no multi-agent or
  autonomous behavior, no streaming, and no telemetry.
- No automatic import of a corpus beyond the CSV importer above.
  The web library is read-only.
- Old finished workflows stay saved until you delete them or
  reset the database. There is no automatic cleanup.
- The default password in `.env.example` (`alba_dev`) is a
  placeholder for local development only. Change
  `ALBA_POSTGRES_PASSWORD` in your own `.env` file before you
  share the computer with anyone. Your `.env` file is never
  uploaded to Git.

## Running on Linux or macOS

The steps are the same, with two differences:

1. Install Git, uv, and Docker from the same official pages above.
   On Linux and macOS, install uv with this command from the
   official uv page:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Start the demo with the shell script instead of the PowerShell
   script:

   ```bash
   bash scripts/demo.sh
   ```

   For real-model mode:

   ```bash
   bash scripts/demo.sh --ollama
   ```

Everything else — the web address, the three demo briefs, the
health pages, stopping, and resetting — is exactly the same.

## Glossary

One sentence for each word this guide uses.

- **Prompt** — the written instruction you give to an image or video
  generator.
- **Brief** — your short request to Alba, in your own words, saying
  what you want the prompt to do.
- **Embedding** — a list of numbers that represents what a piece of
  text means, so the computer can compare meanings, not just words.
- **Retrieval** — looking up the past examples whose meaning is
  closest to your brief.
- **Workflow** — the whole job from your brief to the human decision:
  search, write a recommendation, wait, and decide.
- **Checkpoint** — a saved stopping point of a workflow, so it can
  safely wait for a human and continue later, even after a restart.
- **Migration** — a small, numbered change to the database
  structure, applied in order.
- **Seed** — starter data loaded into an empty database so the demo
  has something to show.
- **Fake provider** — a fixed, predictable stand-in for a real AI
  model, used to test the plumbing without downloading a model.
- **Ollama** — a program that runs AI models on your own computer.
- **Docker** — a program that runs other programs in sealed boxes
  called containers, so they work the same on every computer.
- **uv** — a program that installs Python and Python libraries for a
  project, at exact versions.

## What was not tested here

This guide was written and checked on a Linux machine that has no
Docker, no PostgreSQL, no Ollama, and no Windows PowerShell. The
following steps were **not** run end to end on that machine, so
please treat them as documented from the code, not as tested:

- The full demo startup (`demo.ps1` / `demo.sh`) with Docker and
  PostgreSQL.
- The PowerShell ExecutionPolicy workaround on real Windows.
- The three demo briefs end to end in a browser.
- Real-model mode (`--ollama`) and the two `ollama pull` downloads.
- The CSV import and embedding rebuild against a live database.

What **was** checked here: every command and file named in this
guide was read in the repository (`scripts/demo.ps1`,
`scripts/demo.sh`, `scripts/run_web.py`, `docker-compose.yml`,
`.env.example`, `scripts/import_prompt_corpus.py`,
`scripts/validate_prompt_corpus.py`,
`scripts/rebuild_embeddings.py`, the workflow templates, and the
health routes). The four official download links above were
checked against the official sites. If a step fails on your
computer, start with [Troubleshooting](#troubleshooting) and
report the exact error message you see.
