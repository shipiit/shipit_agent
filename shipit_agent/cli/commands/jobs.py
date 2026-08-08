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
    from shipit_agent.schedule import ScheduledAgentConfig, ScheduledJob

    if not (args.every or args.at or args.cron):
        ui.out(
            ui.style(
                "Pick a schedule: --every SECONDS, --at HH:MM, or --cron EXPR", "err"
            )
        )
        return 1
    store = _store(args)
    try:
        name = args.name or f"job-{int(time.time())}"
        config = ScheduledAgentConfig(
            provider=args.provider,
            model=args.model,
            role=args.role,
            project_root=args.project_root,
            runtime=args.runtime,
            optimized=args.optimized,
            permission_mode=args.permission_mode,
            guardrails=None if args.guardrails == "off" else args.guardrails,
            mcps=_csv(args.mcp),
            connections=_csv(args.connection),
            skills=_csv(args.skill),
            auto_use_skills=args.auto_skills,
            max_iterations=args.max_iterations,
            stream_events=args.stream_events,
        )
        try:
            config.validate()
        except ValueError as exc:
            ui.out(ui.style(str(exc), "err"))
            return 1
        job = ScheduledJob(
            name=name,
            prompt=args.prompt,
            interval_seconds=args.every,
            at=args.at,
            cron=args.cron,
            session_id=args.session_id,
            max_runs=args.max_runs,
            agent_config=config,
        )
        job.next_run = job.compute_next(time.time())
        store.save(job)
        due_in = max(0, int(job.next_run - time.time()))
        ui.out(
            f"{ui.style('✓', 'ok')} scheduled {ui.style(name, 'bold')} "
            f"— first run in ~{due_in}s"
        )
        return 0
    finally:
        store.close()


def cmd_list(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        jobs = store.load_all()
        if not jobs:
            ui.out(
                ui.style("no jobs scheduled — add one with `shipit jobs add`", "dim")
            )
            return 0
        now = time.time()
        for job in jobs:
            when = job.cron or (
                f"daily {job.at}"
                if job.at
                else f"every {int(job.interval_seconds or 0)}s"
            )
            due = max(0, int(job.next_run - now))
            ui.out(
                f"{ui.style(job.name, 'bold'):<32} {when:<16} "
                f"runs={job.runs}  next in ~{due}s  "
                f"{'active' if job.enabled else 'paused'}"
            )
            ui.out(ui.style(f"    {job.prompt[:70]}", "dim"))
            config = job.agent_config
            selected = (
                "/".join(part for part in (config.provider, config.model) if part)
                or "start defaults"
            )
            extras = [config.runtime, selected]
            if config.role:
                extras.append(f"role={config.role}")
            if config.project_root:
                extras.append(f"project={config.project_root}")
            if config.mcps:
                extras.append(f"mcp={','.join(config.mcps)}")
            if config.connections:
                extras.append(f"connections={','.join(config.connections)}")
            if config.skills:
                extras.append(f"skills={','.join(config.skills)}")
            if job.last_error:
                extras.append(f"error={job.last_error[:80]}")
            ui.out(ui.style(f"    {' | '.join(extras)}", "dim"))
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


def cmd_toggle(args: argparse.Namespace) -> int:
    store = _store(args)
    try:
        job = store.load(args.name)
        if job is None:
            ui.out(ui.style(f"no job named '{args.name}'", "err"))
            return 1
        job.enabled = bool(args.enabled)
        store.save(job)
        verb = "resumed" if job.enabled else "paused"
        ui.out(f"{ui.style('✓', 'ok')} {verb} {args.name}")
        return 0
    finally:
        store.close()


def _csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def build_scheduled_agent(config, defaults: argparse.Namespace):
    """Resolve one job's persisted runtime without sharing another job's agent."""
    from shipit_agent import ScheduledAgentFactory
    from shipit_agent.cli.llm import build_llm

    return ScheduledAgentFactory(
        llm_factory=build_llm,
        default_provider=getattr(defaults, "provider", None),
        default_model=getattr(defaults, "model", None),
        default_project_root=getattr(defaults, "project_root", None),
        default_mcps=_csv(getattr(defaults, "mcp", None)),
    )(config)


def cmd_start(args: argparse.Namespace) -> int:
    from shipit_agent import AgentScheduler, SQLiteJobStore

    store = SQLiteJobStore(args.db)
    jobs = store.load_all()
    if not jobs:
        ui.out(ui.style("nothing to run — add jobs first", "err"))
        store.close()
        return 1
    sched = AgentScheduler(
        agent_resolver=lambda config: build_scheduled_agent(config, args),
        store=store,
    )
    for job in jobs:  # re-register; persisted slots are resumed, not reset
        sched.add(
            job.prompt,
            every=job.interval_seconds,
            at=job.at,
            cron=job.cron,
            name=job.name,
            session_id=job.session_id,
            max_runs=job.max_runs,
            agent_config=job.agent_config,
        )
    ui.banner(
        "shipit jobs — scheduler running",
        [("Jobs", str(len(jobs))), ("Store", args.db), ("Stop", "Ctrl+C")],
        emoji="⏰",
    )
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
    add_p.add_argument("--every", type=float, default=None, help="run every N seconds")
    add_p.add_argument("--at", default=None, help="daily at HH:MM")
    add_p.add_argument(
        "--cron", default=None, help="cron expression (pip install croniter)"
    )
    add_p.add_argument("--name", default=None)
    add_p.add_argument("--provider", default=None)
    add_p.add_argument("--model", default=None)
    add_p.add_argument("--role", default=None)
    add_p.add_argument("--project-root", default=None)
    add_p.add_argument(
        "--runtime", choices=["project", "builtins", "role"], default="project"
    )
    add_p.add_argument(
        "--permission-mode",
        choices=["default", "acceptEdits", "plan", "bypass"],
        default="default",
    )
    add_p.add_argument(
        "--guardrails", choices=["standard", "strict", "off"], default="standard"
    )
    add_p.add_argument("--mcp", default=None, help="comma-separated MCP servers")
    add_p.add_argument(
        "--connection", default=None, help="comma-separated required connection IDs"
    )
    add_p.add_argument(
        "--skill", default=None, help="comma-separated packaged or project skill IDs"
    )
    add_p.add_argument(
        "--auto-skills", action=argparse.BooleanOptionalAction, default=True
    )
    add_p.add_argument("--session-id", default=None)
    add_p.add_argument("--max-iterations", type=int, default=None)
    add_p.add_argument("--max-runs", type=int, default=None)
    add_p.add_argument("--stream-events", action="store_true")
    add_p.add_argument(
        "--optimized", action=argparse.BooleanOptionalAction, default=True
    )
    _db(add_p)
    add_p.set_defaults(fn=cmd_add)

    list_p = jsub.add_parser("list", help="List scheduled jobs")
    _db(list_p)
    list_p.set_defaults(fn=cmd_list)

    rm_p = jsub.add_parser("remove", help="Remove a job by name")
    rm_p.add_argument("name")
    _db(rm_p)
    rm_p.set_defaults(fn=cmd_remove)

    for command, enabled in (("pause", False), ("resume", True)):
        toggle_p = jsub.add_parser(command, help=f"{command.title()} a job")
        toggle_p.add_argument("name")
        _db(toggle_p)
        toggle_p.set_defaults(fn=cmd_toggle, enabled=enabled)

    start_p = jsub.add_parser("start", help="Run the scheduler (blocks)")
    _db(start_p)
    for flag in ("--provider", "--model", "--role", "--project-root", "--mcp"):
        start_p.add_argument(flag, default=None)
    start_p.add_argument("--guardrails", choices=["standard", "strict"], default=None)
    start_p.set_defaults(fn=cmd_start)
    jobs.set_defaults(fn=cmd_list, db=".shipit_workspace/schedule.db")
