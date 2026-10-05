"""MCP prompt templates for change, review, coverage, onboarding, regression."""

from __future__ import annotations


def _app_line(app: str) -> str:
    text = (app or "").strip()
    return f"App scope: {text}" if text else ""


def change_plan_text(task: str, app: str = "") -> str:
    app_line = _app_line(app)
    app_arg = f', app="{app.strip()}"' if (app or "").strip() else ""
    return f"""You are planning a code change in this workspace. Task:
{task}
{app_line}

Required tool sequence:
1) index_status
2) list_sources (if app scope unclear)
3) get_context_pack(task{app_arg})
4) impact_of_change(task{app_arg})
5) trace_requirement for any requirement IDs found in the docs hits

Deliverable (markdown):
- Goal and out-of-scope
- Requirements/docs that apply (paths + IDs)
- Code entry points and files to edit
- Tests to add/update
- Risks / regressions
- Open questions if evidence is weak

Do not write implementation code yet. Cite tool evidence only.
""".strip()


def pr_review_text(change_summary: str, app: str = "") -> str:
    app_line = _app_line(app)
    return f"""You are reviewing a change against workspace requirements and documentation.

Change summary / diff description:
{change_summary}
{app_line}

Required tool sequence:
1) index_status (warn if stale)
2) impact_of_change(change_summary)
3) trace_requirement for each requirement ID mentioned in the summary or docs hits
4) find_gaps on the affected area
5) search_code / search_knowledge for any unchecked claims

Deliverable (markdown checklist):
- [ ] Requirements covered (ID → code path)
- [ ] Docs still accurate / need updates
- [ ] Tests cover the behavioral change
- [ ] Security/ops constraints from docs respected
- [ ] Unresolved gaps (explicit)

Be skeptical. If the index lacks evidence, request human confirmation rather than approving.
""".strip()


def requirement_coverage_text(requirement: str, app: str = "") -> str:
    app_line = _app_line(app)
    return f"""Assess coverage for this requirement in the indexed workspace:

{requirement}
{app_line}

Required tool sequence:
1) trace_requirement(requirement)
2) search_code with the requirement text/ID
3) find_gaps(area=requirement)

Deliverable:
- Requirement interpretation (from docs hits only)
- Implementing code/tests (paths)
- Missing implementation or missing tests
- Missing or outdated documentation
- Confidence: high|medium|low based on scores and ID matches
""".strip()


def onboarding_slice_text(topic: str, app: str = "") -> str:
    app_line = _app_line(app)
    return f"""Build a reading guide for a developer/agent new to this topic:

{topic}
{app_line}

Required tool sequence:
1) list_sources
2) get_context_pack(topic)
3) search_knowledge for architecture/ADR context
4) search_code for entry points and tests

Deliverable (ordered reading list, max ~12 items):
1. Docs (why/constraints)
2. Entrypoints / modules
3. Key tests
4. Pitfalls from docs

Keep it short. Cite paths. No implementation.
""".strip()


def regression_check_text(changed_area: str, app: str = "") -> str:
    app_line = _app_line(app)
    return f"""Identify likely regressions for this changed area:

{changed_area}
{app_line}

Required tool sequence:
1) impact_of_change(changed_area)
2) trace_requirement for related requirement IDs
3) search_code for tests near the affected files (app filter if provided)
4) find_gaps(area=changed_area)

Deliverable:
- Behaviors/requirements that may regress
- Existing tests that should be run or extended
- Docs that imply constraints (auth, audit, performance, etc.)
- Suggested verification steps

If evidence is thin, say so.
""".strip()
