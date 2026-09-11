# Copyright (c) 2026 Oliver Kowalke
# SPDX-License-Identifier: MIT

"""FizzBee state-graph conformance-corpus extractor (L4, testing-strategies §3.5).

Runs one .fizz spec through the FizzBee model checker (hermetically, mirroring
scripts/fizz-check.sh), decodes the exhaustive state graph, and emits an
edge-covering set of ROOTED action traces as a JSON corpus. The corpus is the
source of truth for tests/verification/test_fizz_conformance.py, which replays
every trace against the real implementation (the Python-native stand-in for
FizzBee MBT adapters, which upstream ships only for Go/Java/Rust/TypeScript).

Graph artifacts: fizz always writes nodes_*.pb / adjacency_lists_*.pb on a
PASSED exhaustive run; graph.dot is skipped above 250 visited nodes (upstream
writeDotFileIfNeeded), so the extractor parses the protobuf files. Formats per
upstream proto/graph.proto:

    Nodes  { repeated string json = 1; }                  # one JSON per state
    Links  { int64 total_nodes = 1; repeated Link links = 2; }
    Link   { int64 src = 1; int64 dest = 2; string name = 3;
             repeated string labels = 4; double weight = 5; string type = 9; }

proto3 omits zero-valued scalars: an absent src/dest means node 0. Link
weights (perf annotations) are not reproducible run-to-run and are ignored;
everything else is byte-deterministic for a given spec + options.

Usage:
    uv run python scripts/fizz_traces.py verify/fizz/jobs_protocol.fizz \
        --out tests/verification/fizz_corpus/jobs_protocol.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_SCHEMA_VERSION = 1
DEFAULT_MAX_TRACES = 400
DEFAULT_MAX_TRACE_LEN = 64


def _read_varint(data: bytes, i: int) -> tuple[int, int]:
    shift = 0
    val = 0
    while True:
        b = data[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7


def _walk_fields(data: bytes) -> list[tuple[int, int, Any]]:
    fields: list[tuple[int, int, Any]] = []
    i = 0
    while i < len(data):
        tag, i = _read_varint(data, i)
        num, wt = tag >> 3, tag & 7
        if wt == 0:
            val, i = _read_varint(data, i)
            fields.append((num, wt, val))
        elif wt == 1:
            fields.append((num, wt, data[i : i + 8]))
            i += 8
        elif wt == 2:
            ln, i = _read_varint(data, i)
            fields.append((num, wt, data[i : i + ln]))
            i += ln
        elif wt == 5:
            fields.append((num, wt, data[i : i + 4]))
            i += 4
        else:
            raise ValueError(f"unsupported protobuf wire type {wt}")
    return fields


def parse_nodes_pb(path: Path) -> list[dict[str, Any]]:
    """Decode a nodes_*.pb chunk into the JSON state dict per node, in file order."""
    nodes: list[dict[str, Any]] = []
    for num, wt, val in _walk_fields(path.read_bytes()):
        if num == 1 and wt == 2:
            nodes.append(json.loads(val))
    return nodes


def parse_links_pb(path: Path) -> list[dict[str, Any]]:
    """Decode an adjacency_lists_*.pb chunk into normalized link dicts.

    Absent src/dest fields are node 0 (proto3 zero-default). Weights are
    dropped: they are perf-annotation doubles that vary between runs.
    """
    links: list[dict[str, Any]] = []
    for num, wt, val in _walk_fields(path.read_bytes()):
        if num != 2 or wt != 2:
            continue
        link: dict[str, Any] = {"src": 0, "dest": 0, "name": "", "labels": [], "type": ""}
        for f2, w2, v2 in _walk_fields(val):
            if f2 == 1 and w2 == 0:
                link["src"] = v2
            elif f2 == 2 and w2 == 0:
                link["dest"] = v2
            elif f2 == 3 and w2 == 2:
                link["name"] = v2.decode()
            elif f2 == 4 and w2 == 2:
                link["labels"].append(v2.decode())
            elif f2 == 9 and w2 == 2:
                link["type"] = v2.decode()
        links.append(link)
    return links


@dataclass(frozen=True)
class Edge:
    name: str
    dest: int


@dataclass
class Graph:
    nodes: list[dict[str, Any]]
    adj: dict[int, list[Edge]] = field(default_factory=dict)

    def edges(self) -> list[tuple[int, Edge]]:
        return [(src, e) for src in sorted(self.adj) for e in self.adj[src]]


def build_graph(nodes: list[dict[str, Any]], links: list[dict[str, Any]]) -> Graph:
    adj: dict[int, list[Edge]] = {i: [] for i in range(len(nodes))}
    seen: set[tuple[int, str, int]] = set()
    for link in links:
        if link["type"] != "action":
            continue
        key = (link["src"], link["name"], link["dest"])
        if key in seen:
            continue
        seen.add(key)
        adj[link["src"]].append(Edge(name=link["name"], dest=link["dest"]))
    for src, edges in adj.items():
        edges.sort(key=lambda e: (e.name, e.dest))
    graph = Graph(nodes=nodes, adj=adj)
    _canonicalize(graph)
    return graph


def _canonicalize(graph: Graph) -> None:
    """BFS from the root over sorted edges; reorder nodes/adjacency to BFS order.

    Node numbering in the .pb files is already BFS-deterministic for a given
    spec + options, but re-deriving the order here makes the corpus stable
    against upstream numbering changes.
    """
    order: list[int] = []
    index_of: dict[int, int] = {}
    queue = [0]
    while queue:
        src = queue.pop(0)
        if src in index_of:
            continue
        index_of[src] = len(order)
        order.append(src)
        for edge in graph.adj.get(src, []):
            if edge.dest not in index_of:
                queue.append(edge.dest)
    unreachable = set(graph.adj) - index_of.keys()
    if unreachable:
        raise ValueError(f"state graph has unreachable nodes: {sorted(unreachable)[:5]}")
    graph.nodes = [graph.nodes[i] for i in order]
    graph.adj = {
        index_of[src]: [Edge(name=e.name, dest=index_of[e.dest]) for e in graph.adj[src]]
        for src in order
    }


def compact_state(node: dict[str, Any]) -> dict[str, Any]:
    """Reduce a node JSON dump to what conformance adapters need: role fields."""
    return {
        role["ref_string"]: role["fields"]
        for role in node.get("roles", [])
    }


def cover_edges(
    graph: Graph, max_traces: int, max_trace_len: int
) -> tuple[list[list[tuple[int, str, int]]], set[tuple[int, str, int]]]:
    """Greedy edge-covering set of rooted walks (each trace starts at node 0).

    Self-loops are stutter transitions (Idle relief valves) with no real-code
    effect and are excluded from coverage. When the walk stalls on covered
    edges only, it path-finds through the covered subgraph to the nearest
    node that still has an uncovered out-edge.
    """
    uncovered: set[tuple[int, str, int]] = {
        (src, e.name, e.dest) for src, e in graph.edges() if e.dest != src
    }
    traces: list[list[tuple[int, str, int]]] = []
    while uncovered:
        if len(traces) >= max_traces:
            break
        trace: list[tuple[int, str, int]] = []
        cur = 0
        while len(trace) < max_trace_len:
            step = _next_uncovered_step(graph, cur, uncovered)
            if step is None:
                hop = _hop_toward_uncovered(graph, cur, uncovered)
                if hop is None:
                    break
                step = hop
            trace.append(step)
            uncovered.discard(step)
            cur = step[2]
        if not trace:
            break
        traces.append(trace)
    return traces, uncovered


def _next_uncovered_step(
    graph: Graph, cur: int, uncovered: set[tuple[int, str, int]]
) -> tuple[int, str, int] | None:
    for edge in graph.adj.get(cur, []):
        candidate = (cur, edge.name, edge.dest)
        if candidate in uncovered:
            return candidate
    return None


def _hop_toward_uncovered(
    graph: Graph, cur: int, uncovered: set[tuple[int, str, int]]
) -> tuple[int, str, int] | None:
    targets = {src for src, _, _ in uncovered}
    if cur in targets:
        return _next_uncovered_step(graph, cur, uncovered)
    parents: dict[int, tuple[int, str, int]] = {}
    queue = [cur]
    visited = {cur}
    while queue:
        node = queue.pop(0)
        for edge in graph.adj.get(node, []):
            nxt = edge.dest
            step = (node, edge.name, nxt)
            if nxt in visited:
                continue
            parents[nxt] = step
            if nxt in targets:
                path: list[tuple[int, str, int]] = [step]
                while path[0][0] != cur:
                    path.insert(0, parents[path[0][0]])
                return path[0]
            visited.add(nxt)
            queue.append(nxt)
    return None


def load_graph(spec: Path, fizz_bin: str) -> Graph:
    """Run fizz exhaustively on an isolated spec copy and decode the state graph.

    Mirrors scripts/fizz-check.sh: the spec (plus fizz.yaml) is copied to a
    private temp dir so compiled ASTs and graph artifacts never touch the repo.
    """
    with tempfile.TemporaryDirectory(prefix="fizz-traces-") as tmp:
        tmp_path = Path(tmp)
        shutil.copy(spec, tmp_path / spec.name)
        suite_defaults = spec.parent / "fizz.yaml"
        if suite_defaults.exists():
            shutil.copy(suite_defaults, tmp_path / suite_defaults.name)
        out_dir = tmp_path / "out"
        cmd = [
            fizz_bin,
            "--no-symmetry-reduction",
            "--output-dir",
            str(out_dir),
            str(tmp_path / spec.name),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, cwd=tmp_path)
        output = proc.stdout + proc.stderr
        if proc.returncode != 0 or "PASSED: Model checker completed successfully" not in output:
            raise RuntimeError(
                f"fizz run failed for {spec} (exit {proc.returncode}):\n{output[-2000:]}"
            )
        pb_nodes = sorted(out_dir.glob("nodes_*.pb"))
        pb_adj = sorted(out_dir.glob("adjacency_lists_*.pb"))
        if not pb_nodes or not pb_adj:
            raise RuntimeError(f"fizz produced no graph artifacts for {spec}:\n{output[-2000:]}")
        nodes: list[dict[str, Any]] = []
        links: list[dict[str, Any]] = []
        for chunk in pb_nodes:
            nodes.extend(parse_nodes_pb(chunk))
        for chunk in pb_adj:
            links.extend(parse_links_pb(chunk))
        return build_graph(nodes, links)


def build_corpus(spec: Path, fizz_bin: str, max_traces: int, max_trace_len: int) -> dict[str, Any]:
    """Export the canonical state graph + coverage stats as the corpus JSON.

    The corpus stores the GRAPH (deterministic across runs, verified), not a
    flat trace list: the jobs-protocol graph is tree-ish (582 edges / 487
    nodes), so rooted trace sets duplicate prefixes ~10x. The conformance test
    module re-derives rooted edge-covering walks from the graph at run time
    via cover_edges and dedups them into real-code execution signatures.
    """
    graph = load_graph(spec, fizz_bin)
    traces, uncovered = cover_edges(graph, max_traces, max_trace_len)
    coverable = sum(1 for src, e in graph.edges() if e.dest != src)
    corpus: dict[str, Any] = {
        "schema": CORPUS_SCHEMA_VERSION,
        "spec": spec.stem,
        "fizz_flags": ["--no-symmetry-reduction"],
        "stats": {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges()),
            "coverable_edges": coverable,
        },
        "nodes": [compact_state(node) for node in graph.nodes],
        "edges": [
            {"from": src, "action": e.name, "to": e.dest}
            for src, e in graph.edges()
        ],
    }
    if uncovered:
        corpus["stats"]["uncovered_at_generation"] = len(uncovered)
        corpus["stats"]["generation_traces"] = len(traces)
    return corpus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="path to the .fizz spec")
    parser.add_argument("--out", type=Path, required=True, help="corpus JSON output path")
    parser.add_argument("--fizz-bin", default="fizz", help="fizz binary (default: fizz)")
    parser.add_argument("--max-traces", type=int, default=DEFAULT_MAX_TRACES)
    parser.add_argument("--max-trace-len", type=int, default=DEFAULT_MAX_TRACE_LEN)
    args = parser.parse_args(argv)

    spec = args.spec if args.spec.is_absolute() else (Path.cwd() / args.spec)
    corpus = build_corpus(spec, args.fizz_bin, args.max_traces, args.max_trace_len)
    stats = corpus["stats"]
    if stats.get("uncovered_at_generation"):
        print(
            f"WARNING: generation budget left {stats['uncovered_at_generation']} edges "
            f"uncovered ({stats['coverable_edges']} coverable); raise --max-traces",
            file=sys.stderr,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(corpus, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"{corpus['spec']}: {stats['nodes']} nodes, {stats['edges']} edges "
        f"({stats['coverable_edges']} coverable) -> {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
