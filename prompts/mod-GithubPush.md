# MOD-H — Safe GitHub push setup + one-line push helper

> Independent of the other mods — run whenever. Sets up SAFE, on-demand pushing to your
> existing public GitHub repo.
> In Claude Code:  `Read prompts/mod-h.md and execute it. Stop and report back when done.`

```text
Read CLAUDE.md and .gitignore. My code is in a PUBLIC GitHub repo. I want to push my local
commits to GitHub on demand (not on a schedule). Set this up SAFELY and give me a one-line
way to do it. Work step by step and PAUSE for my confirmation at the checkpoints below.

=========================================================
PART 1 — SECRET SAFETY AUDIT (do this FIRST, before any push)
=========================================================
Because the repo is PUBLIC, leaking a secret = giving it to the world. Do all of this:

1. List everything git is currently TRACKING that could be sensitive:
   run `git ls-files` and check for: .env, any *.env, files with "secret"/"key"/"token"/
   "credential" in the name, API key files, *.pem, service-account JSON, SQLite DBs or
   data caches that might contain anything private.
2. Confirm .gitignore excludes at least: .env (and *.env), data/, .venv/, node_modules/,
   *.parquet, any local DB files, and any secrets files. If missing, add them.
3. CRITICAL — check git HISTORY, not just the working tree. A file gitignored TODAY may
   already be committed in a PAST commit and still be public. Run:
     `git log --all --full-history -- .env "*.env"`
   and similarly for any secret-looking files found in step 1.
   - If history is CLEAN (no secrets ever committed): say so and continue.
   - If a secret WAS committed at any point: STOP. Do NOT just delete the file. Tell me
     plainly: which file, which commits, and that (a) I should treat that key as
     COMPROMISED and rotate/regenerate it at the provider (e.g. generate a new Finnhub
     key and revoke the old one), and (b) cleaning git history is a destructive operation
     (git filter-repo / BFG) that we should do carefully together in a separate session.
     Wait for my instruction before doing anything destructive.
4. Verify my Finnhub key specifically is NOT tracked and NOT in history. Report the result
   explicitly.

>>> CHECKPOINT 1: Report the audit result and wait for me to say "continue" before pushing.

=========================================================
PART 2 — VERIFY REMOTE + AUTH
=========================================================
1. Show the current remote: `git remote -v`. Confirm it points to my GitHub repo. If there
   is no remote, ASK me for the repo URL and add it as `origin`.
2. Confirm which branch I'm on (`git branch --show-current`) and whether it tracks a remote
   branch.
3. Test that authentication works WITHOUT pushing real content yet:
   - Prefer the GitHub CLI if installed (`gh auth status`); otherwise check the git
     credential helper / SSH.
   - If auth is NOT set up, give me clear beginner steps to fix it. Recommend the simplest
     reliable option and tell me exactly what to click/type:
       * Option A (easiest): install GitHub CLI `gh` and run `gh auth login` (HTTPS, login
         via browser). 
       * Option B: SSH key setup.
     Do NOT ask me to paste a password or token into the chat or into any file. I will
     authenticate myself in my terminal/browser when you tell me to.

>>> CHECKPOINT 2: Confirm remote is correct and auth works. Wait for my "continue".

=========================================================
PART 3 — ONE-LINE PUSH HELPER (the recurring tool)
=========================================================
Create two scripts so I can push myself, in one line, WITHOUT needing a Claude session:

- scripts/push.sh   (macOS/Linux)
- scripts/push.ps1  (Windows PowerShell)

Behaviour of each:
1. Run the same secret tripwire EVERY push: refuse to push if `git ls-files` shows .env or
   any file matching the secret patterns above; print a clear error and exit non-zero.
2. `git add -A`
3. Commit with my message if I pass one, else a timestamped default
   (e.g. "checkpoint 2026-05-25 14:30"). If there's nothing to commit, say so and still
   attempt to push any unpushed commits.
4. `git push` to the current branch's upstream (set upstream automatically on first push).
5. Print a short success summary: branch, commit short-hash, and the remote URL.

Make both scripts executable / runnable and document them in README.md with copy-paste
usage for both OSes, e.g.:
   macOS:    ./scripts/push.sh "describe what changed"
   Windows:  ./scripts/push.ps1 "describe what changed"

=========================================================
PART 4 — DON'T break the live docs rule
=========================================================
If mod-g has been run, the CLAUDE.md "keep ABOUT.md updated" rule still applies to real
feature changes — but a plain push of existing work does NOT require doc changes. The push
script must not block on that.

ACCEPTANCE
- Audit confirms no secrets are tracked or in history (or clearly escalates if they are).
- `git remote -v` points to my repo and auth is verified.
- I can run one line in my terminal to commit + push, and the script refuses to push if a
  secret ever sneaks into the tracked set.

MANUAL STEPS FOR JAMES
Give me the exact one-line command for my OS to push from now on, and the exact steps (if
any) I need to do once to finish authentication in my own terminal/browser.

REPORT BACK
Show the audit result, the verified remote, and the push command I'll use going forward.
Then make an initial real push of my current work (after CHECKPOINT 2) and confirm it
landed on GitHub.
```
```text
RECURRING USE (no file needed): after this is set up, whenever you want to back up to GitHub,
just open Terminal in the project folder and run:
   macOS:    ./scripts/push.sh "what I changed"
   Windows:  ./scripts/push.ps1 "what I changed"
Or, if you happen to be in a Claude Code session already, you can just say:
   "Commit and push my changes to GitHub with a sensible message."
```
