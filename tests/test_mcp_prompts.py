from rag import mcp_prompts


def test_prompt_texts_include_required_sequences():
    assert "get_context_pack" in mcp_prompts.change_plan_text("add booking", "web")
    assert "App scope: web" in mcp_prompts.change_plan_text("add booking", "web")
    assert "impact_of_change" in mcp_prompts.pr_review_text("diff summary")
    assert "trace_requirement" in mcp_prompts.requirement_coverage_text("REQ-1")
    assert "list_sources" in mcp_prompts.onboarding_slice_text("multi-tenancy")
    assert "find_gaps" in mcp_prompts.regression_check_text("BookingService", "web")
