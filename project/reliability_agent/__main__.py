import argparse
import json
from pathlib import Path

from .agent import ReliabilityAgent
from .config import DEFAULT_ARTIFACT


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
    p = argparse.ArgumentParser(description='Standalone reliability regime agent')
    sub = p.add_subparsers(dest='command', required=True)
    t = sub.add_parser('train')
    t.add_argument('--data-dir', type=Path)
    t.add_argument('--output', type=Path, default=DEFAULT_ARTIFACT)
    for command in ['snapshot', 'assess', 'compare']:
        q = sub.add_parser(command)
        q.add_argument('--at')
        q.add_argument('--state', type=Path)
        q.add_argument('--data-dir', type=Path)
        q.add_argument('--output', type=Path)
        if command != 'snapshot':
            q.add_argument('--artifact', type=Path, default=DEFAULT_ARTIFACT)
            q.add_argument('--policy', type=Path)
            q.add_argument('--candidate', type=Path, required=command == 'compare')
    s = sub.add_parser('serve')
    s.add_argument('--artifact', type=Path, default=DEFAULT_ARTIFACT)
    s.add_argument('--policy', type=Path)
    s.add_argument('--host', default='127.0.0.1')
    s.add_argument('--port', type=int, default=8765)
    args = p.parse_args()
    if args.command == 'train':
        from .train import train
        result = train(args.data_dir, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return
    if args.command == 'serve':
        from .server import serve
        serve(ReliabilityAgent(args.artifact, args.policy), args.host, args.port)
        return
    if args.state:
        if args.at:
            p.error('Use either --state or --at, not both')
        state = read_json(args.state)
    else:
        from .data import read_telemetry, snapshot
        state = snapshot(*read_telemetry(args.data_dir), at=args.at)
    if args.command == 'snapshot':
        result = state
    else:
        agent = ReliabilityAgent(args.artifact, args.policy)
        candidate = read_json(args.candidate) if args.candidate else None
        result = agent.compare(state, candidate) if args.command == 'compare' else agent.assess(state, candidate)
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized+'\n', encoding='utf-8')
        print(str(args.output.resolve()))
    else:
        print(serialized)


if __name__ == '__main__':
    main()
