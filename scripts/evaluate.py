import argparse
import json
from pathlib import Path

from src.config import load_config
from src.evaluation import SCENARIOS, evaluate_local, replay
from src.storage import Repository


def main():
    parser = argparse.ArgumentParser(description="Reproducible replay or recorded local-session evaluation")
    parser.add_argument("--scenario", choices=SCENARIOS, default="CPU spike")
    parser.add_argument("--session", help="Evaluate an existing local session instead of simulation")
    parser.add_argument("--config")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = load_config(args.config)
    result = evaluate_local(Repository(config.db_path), args.session) if args.session else replay(args.scenario, config)[1]
    content = json.dumps(result, indent=2, allow_nan=False)
    print(content)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
