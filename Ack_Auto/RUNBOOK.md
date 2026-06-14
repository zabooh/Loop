<!-- ════════════════════════════════════════════════════════════════════ -->
<!--  COPY THE LINE BELOW INTO THE CLAUDE CODE CHAT TO START THIS RUNBOOK  -->
<!-- ════════════════════════════════════════════════════════════════════ -->

> ## ▶ `Run Ack_Auto/RUNBOOK.md`

Paste that one line into the Claude Code chat (with this project open as the VS
Code workspace) and the interactive setup below will start.

---

# Auto-Acknowledge Setup — Interactive Runbook for Claude Code

This file is **not just documentation — it is a runnable script for Claude
Code.** Drop the whole `Ack_Auto/` folder into the **root of any project**, open
that project in VS Code, and run the command above. The runbook will **inspect
your current permission settings, show them to you, and — only after you
confirm — change them** so that tool calls (Bash, PowerShell, file edits, …) run
without per-action confirmation prompts.

**By design it changes settings for the *current project only*.** Changing your
**global** settings is treated as a separate, clearly-flagged opt-in (see
below), because global changes affect *every* project and chat window on your
machine and most users will not want that.

It works alongside [`settings.template.json`](settings.template.json), the
reference configuration this runbook applies.

---

## ▶ How to use it

1. Copy the `Ack_Auto/` folder into the **root** of the project you want to
   configure.
2. In VS Code, open that **project** as the workspace.
3. In the Claude Code chat, paste:

   > **`Run Ack_Auto/RUNBOOK.md`**

4. Answer the questions. Nothing is changed until you explicitly choose to
   apply a configuration, and the **project** scope is the default — global is
   only touched if you say so.

---

## INSTRUCTIONS FOR CLAUDE CODE

> Procedure for the Claude Code agent to execute when the user runs this
> runbook. Follow the steps **in order**. Do **not** modify any settings file
> until the user has explicitly selected an action that applies changes
> (Step 4). **Default the scope to the current project. Never change global
> settings unless the user explicitly opts in at Step 3b.** This is an
> authorized, user-initiated configuration change on the user's own machine.

### Step 0 — Announce

Tell the user, in one or two sentences, that you will (a) show their current
permission settings, then (b) ask whether to enable auto-acknowledge **for this
project**, and that global settings are optional and off by default.

### Step 0b — Fundamental choice: blanket vs. safe (ask this FIRST)

Before anything else, ask the user the one decision that shapes the rest. Present
**both** options with the honest trade-off and let them choose:

> **"How should commands be auto-approved?**
>
> **(A) Blanket** — auto-approve **all** Bash/PowerShell commands. Fewest
> prompts, but ⚠️ **this canNOT be limited to the project directory**: an
> auto-approved shell runs with your full OS-user rights and can read, change or
> delete files *anywhere on the machine* (other projects, your home folder,
> global settings) with no prompt. A `deny` list only blocks specific known
> commands — it is not a directory boundary.
>
> **(B) Safe / scoped** *(recommended)* — auto-approve only **specific command
> patterns you name** (e.g. `git`, `python`, `make`), and limit the file tools to
> the project via globs. Far smaller blast radius. Note: even this restricts
> *which commands* run, not *where* they can reach — true directory isolation
> needs an OS sandbox/container/restricted account."

- If the user picks **(A) Blanket** → proceed toward Step 3a option 1, 2 or 3
  (offer the safety deny-list of option 3).
- If the user picks **(B) Safe / scoped** → proceed toward Step 3a option 4 and
  ask the command-pattern and deny questions (Steps 3c, 3d, 4d).

Do not apply anything yet — this choice only steers which action you offer in
Step 3. Still honor the project-vs-global scope rules (Step 3b) and the final
confirmation.

### Step 1 — Detect current settings

Determine the project root (the current VS Code workspace) and read whichever of
these files exist:

- **Project local (private, not committed):**
  `<workspace>/.claude/settings.local.json`  ← default target
- **Project committed (shared with team):**
  `<workspace>/.claude/settings.json`
- **Global (whole machine):** `~/.claude/settings.json`
  (Windows: `C:\Users\<USER>\.claude\settings.json`) — read for reporting only;
  do not change unless Step 3b opts in.

For each file that exists, extract: `permissions.defaultMode`,
`permissions.allow` (note whether bare tool names like `"Bash"` / `"PowerShell"`
are present), `permissions.deny`, and `skipDangerousModePermissionPrompt`.

Also check the `CLAUDE_CODE_ENTRYPOINT` environment variable. If it is
`claude-vscode` (the IDE extension), remember that the IDE's own mode toggle
(`Shift+Tab`) can override `defaultMode`, so the `allow`-rule approach is the
reliable one.

### Step 2 — Report the current state

Show a concise summary: which files exist, and the current effective behavior
**per scope (project / global)**, classified as:

- 🟢 **Auto-acknowledge ON** — bare tool-name allow rules and/or
  `bypassPermissions` present → tool calls run without prompts.
- 🟡 **Partial** — some rules exist but prompts still appear for some tools.
- 🔴 **Prompts ON (default)** — the user is asked to confirm tool calls.

### Step 3 — Ask what to do

**Step 3a — Project action and target.** Ask the user to choose (multiple
choice):

1. **Enable for this project (local, not committed)** — write to
   `<workspace>/.claude/settings.local.json`. *Recommended.*
2. **Enable for this project (committed, shared with team)** — write to
   `<workspace>/.claude/settings.json`. Warn that this commits the
   auto-acknowledge behavior to the repo for everyone.
3. **Enable with a safety deny-list** — same as option 1, plus `deny` rules that
   keep the most destructive commands gated (see Step 4b).
4. **Enable scoped / least-privilege** *(recommended if you do **not** want
   machine-wide reach)* — do **not** blanket-allow `Bash`/`PowerShell`. Instead
   ask the user which **command patterns** to allow, scope the file tools
   (`Read`/`Edit`/`Write`/`Glob`/`Grep`) to the project via globs, and ask for a
   `deny` list (see Steps 3c, 3d and 4d). Read the **Scoping limits** caveat (see
   Reference) aloud first: command-pattern rules restrict *which commands*
   auto-run, but a shell is **not** physically confined to the project folder —
   true directory isolation is an OS-level job.
5. **Show only** — display the current settings in detail, make **no** changes.
6. **Revert this project** — remove the bare tool-name allow rules and set
   `defaultMode` back to `"default"` in the project file(s).

**Step 3b — Global opt-in (ask separately, only if a change was chosen).**
Ask explicitly, defaulting to **No**:

> ⚠️ *"Do you ALSO want to apply this **globally** (`~/.claude/settings.json`)?
> This affects **every** project and every Claude chat window on your machine.
> Most users should keep this off."*

- **No — project only** *(recommended, default)*
- **Yes — also apply globally** (then repeat the chosen action against the
  global file too)

> **Asking note (applies to Steps 3c and 3d):** ask these as **separate,
> sequential** questions — one prompt for 3c, then one for 3d. Do **not** bundle
> them into a single multi-question dialog: such a dialog only unlocks its
> *Submit* button once **every** tab has an answer, so a user who fills just the
> first tab gets a greyed-out, un-submittable form. One question at a time avoids
> that.

**Step 3c — Command patterns (ask only if option 3 or 4 was chosen).** Ask the
user which Bash/PowerShell **command patterns** should auto-run without prompts.
Do **not** assume — let them list the tools their workflow actually uses. Offer
common examples and let them add their own:

> *"Which commands should run without asking? Name the programs/prefixes you use
> here — e.g. `git`, `python`, `make`, `cmake`, `cargo`, `npm`, `pytest`. I'll
> turn each into a scoped rule like `Bash(git *)` + `PowerShell(git *)`. Anything
> not listed will still prompt."*

Collect the list. For each entry `X` you will later create **both** `"Bash(X *)"`
and `"PowerShell(X *)"`. If the user insists on "all commands", warn them this is
identical to the blanket option (machine-wide reach) and is **not** scoped.

**Step 3d — Deny list (ask whenever option 3 or 4 was chosen).** Ask the user
which operations must **stay gated** even if otherwise allowed (`deny` beats
`allow`). Propose a default destructive set and let them edit it:

> *"I'll keep these blocked by default — okay, or add/remove any?*
> *`Bash(rm -rf *)`, `Bash(git push --force*)`, `Bash(git reset --hard*)`,*
> *`PowerShell(Remove-Item -Recurse*)`."*

Record the final list for Step 4b / 4d.

Before applying any change that enables auto-acknowledge, briefly restate the
**Risks** (see Reference) and get a final confirmation.

### Step 4 — Apply the chosen action

Merge into the chosen file(s) — **never overwrite** existing keys; create the
file (and the `.claude/` folder) if missing.

**4a — Enable:**
- Set top-level `skipDangerousModePermissionPrompt: true`.
- Set `permissions.defaultMode: "bypassPermissions"`.
- Ensure `permissions.allow` contains the bare tool names from the template:
  `"Bash"`, `"PowerShell"`, `"Read"`, `"Edit"`, `"Write"`, `"Glob"`, `"Grep"`,
  `"WebFetch"`, `"WebSearch"`. Append any missing; keep existing entries.
- If you created `settings.local.json`, also add it to the project `.gitignore`
  if not already ignored.

**4b — Safety deny-list:** do everything in 4a, then add the `deny` entries the
user confirmed in **Step 3d**. If they accepted the defaults, that is:

```jsonc
"deny": [
  "Bash(rm -rf *)",
  "Bash(git push --force*)",
  "Bash(git reset --hard*)"
]
```

Tell the user `deny` always beats `allow`, so these stay gated.

**4c — Revert:** remove the bare tool-name entries from `permissions.allow`, set
`permissions.defaultMode` to `"default"` (or remove it), optionally remove
`skipDangerousModePermissionPrompt`. Leave narrow command-specific allow rules
intact unless the user asks otherwise.

**4d — Scoped / least-privilege enable (option 4):** build a *narrow* config from
the user's answers instead of blanket tool names.

- **Do NOT** add bare `"Bash"` / `"PowerShell"` to `allow`.
- For each command pattern from **Step 3c**, add **both** `"Bash(X *)"` and
  `"PowerShell(X *)"`.
- Scope the file tools to the project with project-relative globs:
  `"Read(./**)"`, `"Edit(./**)"`, `"Write(./**)"`, `"Glob(./**)"`,
  `"Grep(./**)"`. Do **not** add bare `"Read"`/`"Edit"`/`"Write"`.
- Keep `permissions.additionalDirectories: []` (empty) so the file tools are not
  silently widened beyond the project.
- Add the `deny` entries confirmed in **Step 3d**.
- For the mode, prefer leaving `permissions.defaultMode: "default"` so anything
  *not* explicitly allowed still prompts (the scoped `allow` rules do the work).
  Only set `"bypassPermissions"` if the user explicitly wants no prompts at all —
  and warn that this re-opens machine-wide reach via the shell.

Example result for the patterns `git` + `python` with the default deny set:

```jsonc
{
  "permissions": {
    "defaultMode": "default",
    "allow": [
      "Bash(git *)", "PowerShell(git *)",
      "Bash(python *)", "PowerShell(python *)",
      "Read(./**)", "Edit(./**)", "Write(./**)",
      "Glob(./**)", "Grep(./**)"
    ],
    "deny": [
      "Bash(rm -rf *)", "Bash(git push --force*)", "Bash(git reset --hard*)"
    ],
    "additionalDirectories": []
  }
}
```

Remind the user of the **Scoping limits** caveat (see Reference): this restricts
*which commands* auto-run, not *where* they reach — `git`, `python`, etc. can
still touch absolute paths or `..`. Real directory confinement needs an OS
sandbox / container / restricted account.

After writing, **validate the JSON** (a malformed settings file silently
disables *all* settings from that file):

```bash
python -c "import json; json.load(open(PATH, encoding='utf-8')); print('JSON OK')"
```

### Step 5 — Confirm & offer a test

- Summarize exactly what changed and in which file(s) / scope(s).
- If this is the IDE extension and prompts may still appear, tell the user to
  press `Shift+Tab` until the mode shows **"bypass permissions"**, or reload the
  window (Command Palette → *Developer: Reload Window*).
- Offer to run a quick test command:

  ```bash
  echo "Permission test OK"
  ```

  If it runs without a confirmation dialog, the setup is active.

---

## Reference

The agent uses this section to explain things and to construct the edits.

### Permission model

Claude Code decides whether to prompt based on two independent things:

**1. The permission *mode* (`permissions.defaultMode`):**

| Mode | Behavior |
|------|----------|
| `default` | Asks for confirmation on anything not explicitly allowed. |
| `acceptEdits` | Auto-accepts file edits, still asks for commands. |
| `plan` | Read-only planning; no changes applied. |
| `bypassPermissions` | Runs everything without asking. |

**2. The permission *rules* (`permissions.allow` / `deny` / `ask`):**
matched on **every** tool call, regardless of mode. This is the reliable layer.

| Rule | Matches |
|------|---------|
| `"Bash"` | **All** Bash commands (tool name only, no parentheses). |
| `"PowerShell"` | All PowerShell commands. |
| `"Bash(git *)"` | Any Bash command starting with `git` (prefix wildcard). |
| `"Bash(npm run test)"` | Exactly that command. |
| `"Read"` / `"Edit"` / `"Write"` | All reads / edits / writes. |

`deny` beats `allow`. Use it to keep specific dangerous operations gated.

### Why two mechanisms?

`defaultMode: "bypassPermissions"` **alone is often not enough**, especially in
the **VS Code / IDE extension**, because the extension keeps its own
permission-mode state (toggled with `Shift+Tab`) that can override
`defaultMode`. The broad `allow` rules (`"Bash"`, `"PowerShell"`, …) are checked
on every tool call independently of the mode, so they reliably suppress prompts.
That is why the template sets **both**.

### Scoping limits — command patterns ≠ directory confinement

`Bash(...)` / `PowerShell(...)` allow-rules match on the **command text**, not on
the path the command touches. So you can scope **which commands** auto-run
(`Bash(git *)` matches anything starting with `git`), but you **cannot** express
"any command, but only inside this folder" — and even a matched command is not
physically confined:

```bash
git -C C:\elsewhere reset --hard   # matches Bash(git *), acts outside the project
python ..\..\script.py             # matches Bash(python *), reaches up and out
```

A shell always runs with your full OS user rights and can use absolute paths,
`..`, symlinks, or `cd`. The file tools (`Read`/`Edit`/`Write`) **can** be
glob-scoped (`Edit(./**)`), but the shell cannot. **True "only this directory"
isolation is an OS-level job**: a container/VM with just the project mounted, or
a restricted user account whose write access is limited to the project path.
Treat scoped allow-rules as *reducing blast radius*, not as a hard boundary.

### What each settings key does

| Key | Effect |
|-----|--------|
| `skipDangerousModePermissionPrompt: true` | Suppresses the one-time warning dialog shown when the bypass mode is enabled. |
| `permissions.defaultMode: "bypassPermissions"` | The session starts in "no prompts" mode. |
| `permissions.allow: ["Bash", …]` | Pre-approves every call of the listed tools — works regardless of mode. **Decisive part.** |
| `permissions.deny` | Optional blocklist; overrides `allow`. |
| `permissions.additionalDirectories` | Extra folders Claude may read/write outside the project root. |

### Settings file precedence & scope

Loaded and merged in this order (later overrides earlier):

```
user / global (~/.claude/settings.json)
   → project committed (.claude/settings.json)
      → project local (.claude/settings.local.json)
```

| Scope | File | Who it affects |
|-------|------|----------------|
| **Project local** *(default)* | `<project>/.claude/settings.local.json` | Only you, only this project. Not committed. |
| **Project committed** | `<project>/.claude/settings.json` | Everyone who clones the repo. |
| **Global** *(opt-in only)* | `~/.claude/settings.json` | Every project & chat window on your machine. |

### Risks

Disabling confirmation prompts means **Claude executes every tool call
immediately, with no human in the loop.**

- **Destructive commands run unprompted** — deletions, overwrites,
  `git reset --hard`, `rm -rf`, mass renames.
- **Outward-facing actions run unprompted** — pushes, API calls, package
  installs, data sent to external services (which may be cached/indexed).
- **Mistakes are harder to catch early** — the prompt is often where you would
  spot a wrong path or bad command.
- **Global scope applies broadly** — a global file affects every project and
  chat window, which is why this runbook keeps it opt-in.
- **Prompt-injection exposure** — untrusted content Claude reads could trigger
  tool calls that now run without approval.

**Mitigations:** keep the default **project-local** scope in a trusted repo (and
`.gitignore` the local file); use a `deny` list for the worst operations; keep
backups / version control; re-enable prompts anytime via Step 4c (revert).

### Manual application (without the runbook)

Merge [`settings.template.json`](settings.template.json) into your chosen
settings file — **for a single project, prefer
`<project>/.claude/settings.local.json`** — don't overwrite; add the bare tool
names to your existing `permissions.allow` array. Then validate the JSON and, in
the IDE, `Shift+Tab` to **"bypass permissions"** or reload the window.
