from conftest import cli


def test_print_agent_guide_renders_the_notebook_rules():
    r = cli("print-agent-guide")
    assert r.returncode == 0
    out = r.stdout
    assert out.startswith("## ")
    for tool in ("notebooks_list", "notebook_search"):
        assert tool in out
    assert "draft" in out
    assert "rationale" in out
    assert "tokens" in out.lower()
    assert "посмотри в блокноте" in out
