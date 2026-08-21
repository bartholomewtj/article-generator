# SSSF starter recipes. Stamped by install.py, then yours to edit.
#
# Deliberately small. These are the handful you need on day one: run something,
# watch it, and open the trace. Add your own as your chains grow, and see the
# example branch for the fuller set (orchestrator agents, kill, rosters, ipi).

# `.env` reaches every ADW through this, so keys work without exporting them.
set dotenv-load
set positional-arguments

# Every recipe passes this through, so `SSSF_CONFIG=other.yaml just sdlc "..."`
# swaps the whole roster for one run.
config := env_var_or_default("SSSF_CONFIG", "adws/adw_sssf_config/sssf.config.yaml")
db     := "adws/adw_data/sssf.db"

# where the upstream sssf skill's visualizer app lives (see `just obs`)
viz    := env_var_or_default("SSSF_VIZ", "~/.claude/skills/sssf/apps/visualizer")
# cross-repo run board (see `just factory`)
live   := env_var_or_default("SSSF_LIVE", home_directory() / ".claude/skills/sssf-health/scripts/live.py")
# this factory's skill checkout — fleet/ lives here, not in stamped repos
skill  := env_var_or_default("CLAUDESSSF", "~/.claude/skills/claudesssf")

# list every recipe
default:
    @just --list

# ── first run ───────────────────────────────────────────────────────────────

# Proves the whole path works: config validated, session minted, agent ran,
# envelope parsed, gates checked, trace written. Costs a few cents and changes
# nothing in your repo, because both workflows are read-only.
#
# (`just --list` shows only the LAST comment line, so that one is the summary.)

# start here: two cheap read-only runs, end to end
demo:
    @echo "1/2  adw_prompt: one agent, one prompt"
    uv run adws/adw_prompt.py --config {{config}} --agent scout "reply with a one-line summary of this repo"
    @echo "\n2/2  adw_scout: read-only recon"
    uv run adws/adw_scout.py --config {{config}} "list the top-level directories in this repo and what each is for. change nothing."
    @echo "\nboth done. now run:  just sessions    (or: just obs)"

# ── run a workflow ──────────────────────────────────────────────────────────
# Args pass straight through: "<prompt or path/to/prompt.md>" [--adw-id X]

# one agent, one prompt: just prompt "summarize this repo"
prompt *ARGS:
    uv run adws/adw_prompt.py --config {{config}} "$@"

# read-only recon: just scout "where is auth handled"
scout *ARGS:
    uv run adws/adw_scout.py --config {{config}} "$@"

# plan only: just plan "add a /health endpoint"
plan *ARGS:
    uv run adws/adw_plan.py --config {{config}} "$@"

# planner, builder, commit: just plan-build "add a /health endpoint"
plan-build *ARGS:
    uv run adws/adw_plan_build.py --config {{config}} "$@"

# plan, build, test, commit: just sdlc "add a /health endpoint"
sdlc *ARGS:
    uv run adws/adw_plan_build_test.py --config {{config}} "$@"

# the full chain, plus review and docs: just simple-sdlc "add a /health endpoint"
simple-sdlc *ARGS:
    uv run adws/adw_simple_sdlc.py --config {{config}} "$@"

# ── watch it ────────────────────────────────────────────────────────────────
# Reads never block a running workflow, the db is WAL. Poll as hard as you like.

# the last 10 runs
sessions:
    @sqlite3 {{db}} "select adw_id, status, substr(request,1,50), total_tokens, round(total_cost,4) from sessions order by started_at desc limit 10;"

# phase status in sequence: just phases <adw_id>
phases ADW_ID:
    @sqlite3 {{db}} "select seq, name, kind, owner, status, attempt from phases where adw_id='{{ADW_ID}}' order by seq;"

# the live event tail: just tail <adw_id>
tail ADW_ID:
    @sqlite3 {{db}} "select rowid, type, name, started_at from events where adw_id='{{ADW_ID}}' order by rowid desc limit 25;"

# what a run has alive right now, with pids: just procs <adw_id>
procs ADW_ID:
    @sqlite3 {{db}} "select kind, name, pid, command, started_at from processes where adw_id='{{ADW_ID}}' and ended_at is null order by id;"

# ── sandbox (fleet stays in the skill) ──────────────────────────────────────
# just box-up [--roster balanced --budget 5]
box-up *FLAGS:
    PYTHONUTF8=1 uv run {{skill}}/fleet/sbx.py up --repo "{{justfile_directory()}}" {{FLAGS}}

# just box-run <run-id> "add a /health endpoint"
box-run RUN_ID *ARGS:
    PYTHONUTF8=1 uv run {{skill}}/fleet/sbx.py run "{{RUN_ID}}" {{ARGS}}

boxes:
    PYTHONUTF8=1 uv run {{skill}}/fleet/sbx.py status

# just box-msg <run-id> "how's it going?"
box-msg RUN_ID TEXT:
    PYTHONUTF8=1 uv run {{skill}}/fleet/sbx.py msg "{{RUN_ID}}" "{{TEXT}}"

# just box-down <run-id>
box-down RUN_ID *FLAGS:
    PYTHONUTF8=1 uv run {{skill}}/fleet/sbx.py down "{{RUN_ID}}" {{FLAGS}}

# ── observability UI ────────────────────────────────────────────────────────

# claudeSSSF does not bundle the visualizer. The db schema is unchanged, so the
# upstream SSSF app reads these traces as-is — point it at this repo's db.
# Needs bun, and the upstream sssf skill installed at USER scope
# (~/.claude/skills/sssf) — that is where a normal skill install lands; a
# repo-local .claude/skills/ copy is the exception, not the rule.
#
# One process, one port. The first run builds the UI into the app's own dist/
# (once per machine, ~2s), after which the api serves it directly — no vite, no
# second port, nothing stamped into this repo. Editing the UI itself is the only
# reason to want hot reload: `bun run dev` in that folder, on :4601.
#
# The --db path is single-quoted because a Windows path arrives with backslashes
# and sh eats them unquoted, which pointed the server at a nonexistent db.
#
# Two repos at once: PORT=4610 just obs

# boot the trace UI for this repo, http://localhost:4600
obs:
    @test -f {{db}} || { echo "no trace db at {{db}} yet — run 'just demo' first"; exit 1; }
    @test -d {{viz}}/dist || (echo "first run: building the visualizer ui" && cd {{viz}} && bun install && bun run build)
    bun run {{viz}}/server/index.ts --db '{{justfile_directory()}}/{{db}}'

# every stamped repo's runs, http://127.0.0.1:4620
factory:
    python "{{live}}"
