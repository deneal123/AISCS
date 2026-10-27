from __future__ import annotations

import argparse
import json
from pathlib import Path

from service.contracts import SimulationConfig
from service.main import (
    build_catalog,
    build_connectome_evaluation,
    build_evaluation,
    build_generation,
)
from service.settings import connectome_model_path


def main():
    parser = argparse.ArgumentParser(description="Compartmental generator")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("catalog")
    verify = sub.add_parser("connectome-verify")
    verify.add_argument("--directory", type=Path)
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--stimulus", choices=["none", "weak", "strong"], default="weak")
    run.add_argument("--seed", type=int, default=1)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--output", type=Path, required=True)
    cns = sub.add_parser("evaluate-cns")
    cns.add_argument("--output", type=Path, required=True)
    cns.add_argument("--phase", choices=["development", "test"], required=True)
    cns.add_argument(
        "--protocol",
        type=Path,
        default=connectome_model_path().with_name("protocol.json"),
    )
    args = parser.parse_args()
    if args.command == "catalog":
        print(json.dumps(build_catalog(), ensure_ascii=False))
    elif args.command == "connectome-verify":
        from service.infrastructure.connectome.dataset import load_registered_graph
        from service.settings import connectome_directory

        graph = load_registered_graph(args.directory or connectome_directory())
        print(json.dumps(graph.provenance, ensure_ascii=False))
    elif args.command == "evaluate":
        print(json.dumps(build_evaluation(args.output), ensure_ascii=False))
    elif args.command == "evaluate-cns":
        print(
            json.dumps(
                build_connectome_evaluation(args.output, args.protocol, args.phase),
                ensure_ascii=False,
            )
        )
    else:
        config = (
            SimulationConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
            if args.config
            else SimulationConfig(stimulus=args.stimulus, seed=args.seed)
        )
        manifest = build_generation().execute(config, args.output)
        print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
