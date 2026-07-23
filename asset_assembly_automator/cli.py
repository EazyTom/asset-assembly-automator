from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from asset_assembly_automator import __version__
from asset_assembly_automator.core.config import get_settings
from asset_assembly_automator.core.db.models import Database
from asset_assembly_automator.core.logging import configure_logging
from asset_assembly_automator.core.state_machine import StageId
from asset_assembly_automator.orchestrator.runner import PipelineRunner
from asset_assembly_automator.orchestrator.watchers import ArtifactWatcher


def cmd_init(args: argparse.Namespace) -> int:
    settings = get_settings()
    settings.paths.app_data.mkdir(parents=True, exist_ok=True)
    Database()
    print(f"Initialized DB at {settings.paths.app_data / 'aaa.db'}")
    return 0


def cmd_create_project(args: argparse.Namespace) -> int:
    db = Database()
    pid = db.create_project(args.name, args.output_root, unity_project_path=args.unity)
    print(f"Created project {pid}: {args.name}")
    return 0


def cmd_create_pipeline(args: argparse.Namespace) -> int:
    db = Database()
    plid = db.create_pipeline(
        args.project_id,
        args.asset_name,
        poly_budget=args.poly_budget,
        multi_view=args.multi_view,
    )
    print(f"Created pipeline {plid}: {args.asset_name}")
    return 0


async def cmd_run(args: argparse.Namespace) -> int:
    configure_logging(verbose=args.verbose)
    runner = PipelineRunner(dry_run=args.dry_run, verbose=args.verbose)
    if args.stage:
        result = await runner.run_stage(args.pipeline_id, StageId(args.stage))
    else:
        result = await runner.run_pipeline(args.pipeline_id, auto=not args.manual)
    print(result)
    return 0 if result.success else 1


async def cmd_watch(args: argparse.Namespace) -> int:
    loop = asyncio.get_running_loop()
    db = Database()

    def on_event(kind: str, path: Path) -> None:
        print(f"[watch] {kind}: {path}")
        if kind == "mj_import" and args.pipeline_id:
            db.add_asset(
                args.pipeline_id,
                "concept",
                str(path),
                provider="midjourney",
                metadata={"imported_via": "watch_folder"},
            )

    settings = get_settings()
    watcher = ArtifactWatcher(loop, on_event)
    if settings.midjourney.watch_folder:
        watcher.watch_import_folder(settings.midjourney.watch_folder)
    if args.output_dir:
        watcher.watch_output_dir(args.output_dir)
    watcher.start()
    flush = asyncio.create_task(watcher.run_flush_loop())
    try:
        await asyncio.sleep(args.duration or 3600)
    finally:
        flush.cancel()
        watcher.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="aaa", description="Asset Assembly Automator CLI")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command")

    init_p = sub.add_parser("init", help="Initialize app data and database")
    init_p.set_defaults(func=cmd_init)

    proj_p = sub.add_parser("create-project", help="Create a project")
    proj_p.add_argument("name")
    proj_p.add_argument("output_root")
    proj_p.add_argument("--unity", default=None)
    proj_p.set_defaults(func=cmd_create_project)

    pipe_p = sub.add_parser("create-pipeline", help="Create a character pipeline")
    pipe_p.add_argument("project_id", type=int)
    pipe_p.add_argument("asset_name")
    pipe_p.add_argument("--poly-budget", default="hero", choices=["hero", "npc", "crowd"])
    pipe_p.add_argument("--multi-view", action="store_true")
    pipe_p.set_defaults(func=cmd_create_pipeline)

    run_p = sub.add_parser("run", help="Run pipeline or stage")
    run_p.add_argument("--pipeline-id", type=int, required=True)
    run_p.add_argument("--stage", default=None)
    run_p.add_argument("--dry-run", action="store_true")
    run_p.add_argument("--verbose", action="store_true")
    run_p.add_argument("--manual", action="store_true", help="Stop at manual gates")
    run_p.set_defaults(func=lambda a: asyncio.run(cmd_run(a)))

    watch_p = sub.add_parser("watch", help="Watch import/output folders")
    watch_p.add_argument("--pipeline-id", type=int)
    watch_p.add_argument("--output-dir")
    watch_p.add_argument("--duration", type=int, default=3600)
    watch_p.set_defaults(func=lambda a: asyncio.run(cmd_watch(a)))

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0
    fn = args.func
    if asyncio.iscoroutinefunction(fn):
        return asyncio.run(fn(args))
    return fn(args)


if __name__ == "__main__":
    sys.exit(main())
