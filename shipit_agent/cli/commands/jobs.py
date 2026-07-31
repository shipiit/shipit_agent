"""`shipit jobs` — durable scheduled agent jobs from the CLI.

    shipit jobs add "Summarize new error logs" --every 3600
    shipit jobs add "Draft the daily post" --at 09:00 --name daily-post
    shipit jobs add "Weekly brief" --cron "0 8 * * 1"
    shipit jobs list
    shipit jobs remove daily-post
    shipit jobs start --provider bedrock          # blocks, firing when due

Jobs persist in SQLite (`.shipit_workspace/schedule.db` by default) — due
times and run counts survive restarts, so `start` resumes every job's slot
instead of resetting it.
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from shipit_agent.cli import ui


def _store(args: argparse.Namespace):
    from shipit_agent import SQLiteJobStore

    return SQLiteJobStore(args.db)


def cmd_add(args: argparse.Namespace) -> int:
    from shipit_agent.schedule import ScheduledJob

    if not (args.every or args.at or args.cron):
        ui.out(ui.style("Pick a schedule: --every SECONDS, --at HH:MM, "
                        "or --cron EXPR", "err"))
        return 1
    store = _store(args)
    try:
        name = args.name or f"job-{int(time.time())}"
        job = ScheduledJob(
            name=name, prompt=args.prompt, interval_seconds=args.every,
            at=args.at, cron=args.cron,
        )
        job.next_run = job.compute_next(time.time())
        store.save(job)
        due_in = max(0, int(job.next_run - time.time()))
        ui.out(f"{ui.style('✓', 'ok')} scheduled {ui.style(name, 'bold')} "
               f"— first run in ~{due_in}s")
        return 0
    finally:
        store.close()


def cmd_list(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        jobs = store.load_all()
        if not jobs:
            ui.out(ui.style("no jobs scheduled — add one with "
                            "`shipit jobs add`", "dim"))
            return 0
        now = time.time()
        for job in jobs:
            when = (job.cron or (f"daily {job.at}" if job.at
                    else f"every {int(job.interval_seconds or 0)}s"))
            due = max(0, int(job.next_run - now))
            ui.out(f"{ui.style(job.name, 'bold'):<32} {when:<16} "
                   f"runs={job.runs}  next in ~{due}s")
            ui.out(ui.style(f"    {job.prompt[:70]}", "dim"))
        return 0
    finally:
        store.close()


def cmd_remove(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        if store.load(args.name) is None:
            ui.out(ui.style(f"no job named '{args.name}'", "err"))
            return 1
        store.delete(args.name)
        ui.out(f"{ui.style('✓', 'ok')} removed {args.name}")
        return 0
    finally:
        store.close()


def cmd_start(args: argparse.Namespace) -> int:
    from shipit_agent import AgentScheduler, SQLiteJobStore
    from shipit_agent.cli.llm import build_agent

    store = SQLiteJobStore(args.db)
    jobs = store.load_all()
    if not jobs:
        ui.out(ui.style("nothing to run — add jobs first", "err"))
        store.close()
        return 1
    agent = build_agent(args)
    sched = AgentScheduler(agent, store=store)
    for job in jobs:  # re-register; persisted slots are resumed, not reset
        sched.add(job.prompt, every=job.interval_seconds, at=job.at,
                  cron=job.cron, name=job.name)
    ui.banner("shipit jobs — scheduler running",
              [("Jobs", str(len(jobs))), ("Store", args.db),
               ("Stop", "Ctrl+C")], emoji="⏰")
    try:
        sched.run_forever()
    except KeyboardInterrupt:
        ui.out(ui.style("\nscheduler stopped", "dim"))
    finally:
        store.close()
    return 0


def register(sub: Any) -> None:
    jobs = sub.add_parser("jobs", help="Durable scheduled agent jobs (cron)")
    jsub = jobs.add_subparsers(dest="jobs_command")

    def _db(p: argparse.ArgumentParser) -> None:
        p.add_argument("--db", default=".shipit_workspace/schedule.db")

    add_p = jsub.add_parser("add", help="Schedule a prompt")
    add_p.add_argument("prompt")
    add_p.add_argument("--every", type=float, default=None,
                       help="run every N seconds")
    add_p.add_argument("--at", default=None, help="daily at HH:MM")
    add_p.add_argument("--cron", default=None,
                       help="cron expression (pip install croniter)")
    add_p.add_argument("--name", default=None)
    _db(add_p)
    add_p.set_defaults(fn=cmd_add)

    list_p = jsub.add_parser("list", help="List scheduled jobs")
    _db(list_p)
    list_p.set_defaults(fn=cmd_list)

    rm_p = jsub.add_parser("remove", help="Remove a job by name")
    rm_p.add_argument("name")
    _db(rm_p)
    rm_p.set_defaults(fn=cmd_remove)

    start_p = jsub.add_parser("start", help="Run the scheduler (blocks)")
    _db(start_p)
    for flag in ("--provider", "--model", "--role", "--project-root", "--mcp"):
        start_p.add_argument(flag, default=None)
    start_p.add_argument("--guardrails", choices=["standard", "strict"],
                         default=None)
    start_p.set_defaults(fn=cmd_start)
    jobs.set_defaults(fn=cmd_list, db=".shipit_workspace/schedule.db")
