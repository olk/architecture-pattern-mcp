"""Stage-0 pattern-selection benchmark harness for ArchitecturePipeline.

Adapted from design-pattern-mcp-local (commit 25cbfba); retargeted to B's
pipeline stages (build.embed / retrieval.dense / retrieval.bm25 / llm.weights
/ llm.generate / llm.evaluate / reasoning.* / e2e.total).
"""

HARNESS_PACKAGE = "tests.benchmark.harness"
