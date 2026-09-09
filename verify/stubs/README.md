# Library stubs for the Nagini verification set (nagini plan §3.5)

Annotated `.pyi` stubs declare unproven oracle assumptions about third-party
libraries; Nagini verifies programs *assuming* these stubs are correct. Every
stub is reviewed like source and — where feasible — spot-checked by an
executable test under `tests/verification/` (stub-conformance spot-checks).
