# Vulture whitelist: symbol references invisible to static analysis.
# https://github.com/jendrikseipp/vulture#whitelists
#
# Used by `make deadcode` / CI:
#   vulture src examples whitelist.py --min-confidence 80 \
#       --ignore-decorators "@step,@field_validator,@model_validator,@*.resource,@*.prompt"
#
# Add an entry here ONLY for a symbol that is provably live but has no static
# reference, and document the dispatch mechanism next to it. Prune entries when
# the symbol dies.

# MCP tools are dispatched dynamically via MCPArchitectServer._TOOL_METHOD_MAP
# (src/server.py): getattr(tool_instance, method_name) -> server.add_tool().
tool.list_architecture_patterns
tool.get_architecture_pattern
tool.submit_job
tool.get_status
tool.cancel
tool.design
tool.analyze
tool.generate
tool.evaluate

# CLI entry point declared in pyproject.toml [project.scripts].
cli

# MCP prompts registered by src/mcp_prompts/__init__.py::register_prompts
# via @server.prompt decorators (covered by --ignore-decorators, kept here
# for lower-confidence manual audits).
design_architecture_workflow
explore_pattern_catalog
evaluate_my_architecture
compare_architecture_styles
