"""`stele install` — render skill/hook/section content for one or more platforms."""

from __future__ import annotations

import argparse

from stele.packaging.install import install_for
from stele.packaging.platforms import PLATFORM_CONFIG


def run(args: argparse.Namespace) -> int:
    if args.all:
        targets = list(PLATFORM_CONFIG.keys())
    else:
        if not args.platform:
            print("stele: --platform NAME or --all required")
            return 2
        if args.platform not in PLATFORM_CONFIG:
            print(f"stele: unknown platform {args.platform!r}")
            return 2
        targets = [args.platform]

    for name in targets:
        install_for(name, dry_run=args.dry_run)
        print(f"stele: installed {name}")
        if name == "claude-code" and not args.dry_run:
            _print_claude_code_hook_notice()
    return 0


def _print_claude_code_hook_notice() -> None:
    """Claude Code does not auto-discover dropped hook scripts; it runs only the
    hooks registered in settings.json. Print the snippet the user must add so the
    SessionEnd ingest hook actually fires (the script alone does nothing).
    """
    print(
        "stele: hooks dropped at ~/.claude/hooks/. Claude Code only runs hooks\n"
        "       registered in ~/.claude/settings.json. Add the SessionEnd entry\n"
        "       below to enable the session-ingest hook (the large-output hook is\n"
        "       optional; wire it under PostToolUse if you want the reminder):\n"
        "\n"
        '  "hooks": {\n'
        '    "SessionEnd": [\n'
        '      { "hooks": [{ "type": "command",\n'
        '                    "command": "~/.claude/hooks/stele-session-ingest.sh" }] }\n'
        "    ]\n"
        "  }\n"
    )
