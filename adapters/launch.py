"""Small shell-free adapter entry point; successful ensure writes no context."""
import argparse
import json
import subprocess
import sys

sys.dont_write_bytecode = True
from bridge import call_tool, invoke, read_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("action", choices=("ensure", "tool"))
    parser.add_argument("name", nargs="?")
    parser.add_argument("arguments", nargs="?", default="{}")
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        if args.action == "ensure":
            invoke(config, "ensure", timeout=5)
        else:
            result = call_tool(config, args.name, json.loads(args.arguments))
            print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Prospect adapter: {str(exc)[:1600]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
