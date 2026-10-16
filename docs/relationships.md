# Workspace relationships

Allowed types: `depends_on`, `references`, `implements`, `documents`, `tests`,
`shares_contract_with`.

## Rules

- Targets must exist in the workspace registry
- One-way edges only (no implicit reverse)
- Duplicates and self-targets are rejected
- Cycles are skipped during expansion

## Related scope

`scope=related` starts at the current workspace and includes authorized outbound
targets (default depth 1). Unauthorized targets are filtered by the caller's
`Principal` allowlist. There is no implicit global search; `scope=global`
remains disabled.
