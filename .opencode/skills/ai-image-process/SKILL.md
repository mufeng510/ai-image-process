---
name: AI Image Process
description: Batch-process photos with the AI Image Process CLI (AI-Image-Process-CLI, or `python -m app cli` from source) — plan with --dry-run, run jobs, read the JSON summary, and generate Apple Live Photos. Use when the user asks to batch process, convert, clean metadata, or generate Live Photos from a folder of images.
---

# AI Image Process

Batch photo processing with a CLI whose contract is: exit code in, JSON out.

## Pick the right entry point first

| Situation | Command |
| --- | --- |
| Unzipped portable build | `AI-Image-Process-CLI` |
| Source checkout | `.venv/bin/python -m app cli` |

Passing CLI flags to the GUI binary (`AI-Image-Process`) **silently opens a window
and exits 0** — no error, no output. If a run "succeeds" instantly and printed
nothing, this is why.

## Workflow

1. **Plan first.** `--dry-run` runs preflight only: it writes nothing, does not
   even create the output directory, and reports how many files it would process.
   `--dry-run --json-summary` gives you `planned_input_count` and
   `planned_output_dir`.
2. **Then run**, with `--json-summary`.
3. **Read the answer from JSON**, not by scanning the output directory:

```bash
AI-Image-Process-CLI ./photos -o ./out --json-summary | jq -r '.outputs[].output'
```

With `--json-summary`, stdout carries the JSON document alone and all progress
goes to stderr. Without it, stdout is human-readable text — do not try to parse it.

## Exit codes

- `0` — all succeeded
- `1` — **partially** failed; read `failures[]`. Never treat this as success.
- `2` — preflight refused; **nothing was written**. The reason and how to fix it
  are in `preflight_error`.

`0` does not mean "every flag you wanted took effect" — it means files were
produced and none failed.

## Things that fail silently

These are the ones that produce a successful run with the wrong result:

- **Directories are not scanned recursively** (`input.recurse_folders=false`).
  Images in subfolders are skipped without any warning. If the file count looks
  low, this is almost always why.
- **Exact duplicates are dropped** (`steps.deduplicate` is on by default).
- **Output goes into a timestamped subfolder** (`output.subfolder_per_run=true`),
  not directly into the directory you passed to `-o`.
- **`--seed` does not make runs byte-identical.** Pixels are reproducible; EXIF
  timestamps record when the run happened. Do not verify idempotency with
  checksums.
- **Unknown keys in `--config` are dropped silently.** A typo in a config key
  looks exactly like a setting that did nothing.

## Configuration

Anything outside the CLI flags — recursion, concurrency (`runtime.worker_count`,
default 1), accepted extensions, naming, conflict policy, the AI video Provider —
is only reachable through a JSON file passed to `--config`. The file is a
**partial override**: keys you omit keep their defaults.

## Full reference

Read `docs/agent-cli.md` in the project for the complete parameter list, every
config key with defaults, copy-paste recipes, the summary JSON shape, and a
troubleshooting table. Run `--help` for the authoritative flag list.

For runtime errors (ExifTool / FFmpeg missing), the preflight message says which
one is missing and how to install it — read `preflight_error` in full rather than
paraphrasing it.