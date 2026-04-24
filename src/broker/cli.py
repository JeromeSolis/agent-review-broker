"""Entry point. `python -m broker launch --name broker` runs one session."""

import argparse
import asyncio
import sys
from pathlib import Path

from broker.config import REPO_ROOT, settings
from broker.db import init_db


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="broker")
    sub = p.add_subparsers(dest="cmd", required=True)

    launch = sub.add_parser("launch", help="Run one agent session (supervisor restarts on exit)")
    launch.add_argument("--name", default=settings.agent_name, help="Agent name under agent_configs/")
    launch.add_argument(
        "--session-timeout",
        type=int,
        default=settings.session_timeout_s,
        help="Max seconds per invocation",
    )

    sub.add_parser("prompt", help="Print the assembled system prompt and exit")
    sub.add_parser("check-koala", help="Probe the Koala MCP endpoint and print available tools")

    return p


async def _cmd_launch(args: argparse.Namespace) -> int:
    settings.agent_name = args.name
    await init_db()
    # Lazy import so `broker prompt` / `broker check-koala` don't require anthropic.
    from broker.harness import run_once

    turns = await run_once(session_timeout_s=args.session_timeout)
    print(f"[cli] session ended after {turns} turns")
    return 0


async def _cmd_prompt(args: argparse.Namespace) -> int:
    from broker.prompt import assemble_prompt

    print(assemble_prompt())
    return 0


async def _cmd_check_koala(args: argparse.Namespace) -> int:
    from broker.config import load_api_key
    from broker.koala_client import KoalaClient

    key = load_api_key(settings.agent_name)
    if not key:
        print("ERROR: No Koala API key. Drop one at agent_configs/<name>/.api_key", file=sys.stderr)
        return 2
    settings.koala_api_key = key
    koala = KoalaClient(api_key=key)
    try:
        tools = await koala.list_tools()
        for t in tools:
            print(f"- {t.get('name')}: {t.get('description', '')[:100]}")
    finally:
        await koala.close()
    return 0


def main() -> None:
    args = _parser().parse_args()
    match args.cmd:
        case "launch":
            sys.exit(asyncio.run(_cmd_launch(args)))
        case "prompt":
            sys.exit(asyncio.run(_cmd_prompt(args)))
        case "check-koala":
            sys.exit(asyncio.run(_cmd_check_koala(args)))


if __name__ == "__main__":
    main()
