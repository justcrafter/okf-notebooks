"""Story 15, seam 2: the MCP tools over HTTP for a proposed Notebook."""

import json

import pytest
import test_mcp_tools as base
from test_mcp_tools import WS, assert_error, assert_resource_error, data, write

from okf_notebooks.lifecycle import Lifecycle
from okf_notebooks.store import Store

# fixtures of the shared MCP helpers, re-exported for pytest
anyio_backend = base.anyio_backend
mem = base.mem


def lifecycle(m):
    return Lifecycle(Store(m.cfg.root, git=False))


async def propose(c):
    assert not (await c.call_tool("notebook_create", WS)).is_error


@pytest.mark.anyio
async def test_author_works_in_their_proposed_notebook(mem):
    m = mem()
    async with m.connect("claude-code") as c:
        await propose(c)
        w = data(await write(c, notebook="obs", type="Project", title="Grafana"))
        assert w["id"] == "/projects/grafana" and w["status"] == "draft"
        assert w["generated"]["by"].startswith("claude-code/")
        r = data(await c.call_tool("notebook_read", {"notebook": "obs", "id": w["id"]}))
        assert r["etag"] == w["etag"] and "data from a notebook" in r["body"]
        up = data(await c.call_tool("notebook_update", {
            "notebook": "obs", "id": w["id"], "base_etag": w["etag"],
            "body": "A brand new body that is long enough.\n"}))
        stale = await c.call_tool("notebook_update", {
            "notebook": "obs", "id": w["id"], "base_etag": w["etag"],
            "body": "Another body that is long enough too.\n"})
        assert assert_error(stale, "conflict")["current"]["etag"] == up["etag"]
        ap = data(await c.call_tool("notebook_update", {
            "notebook": "obs", "id": w["id"], "append": "- appended\n"}))
        assert ap["etag"] != up["etag"]
        lst = data(await c.call_tool("notebook_list", {"notebook": "obs"}))
        assert [i["id"] for i in lst["items"]] == [w["id"]]
        s = data(await c.call_tool("notebook_search", {"query": "brand", "notebook": "obs"}))
        assert s["count"] == 1
        bad = await write(c, notebook="obs", type="Nope", title="X")
        assert_error(bad, "invalid")
        assert (await c.call_tool("notebook_validate", {"notebook": "obs"})).structured_content["ok"]
        res = json.loads((await c.read_resource("okf://obs/projects/grafana")).contents[0].text)
        assert res["id"] == w["id"]
        assert "Grafana" in (await c.read_resource("okf://obs/index")).contents[0].text
        # default (cross-notebook) search never includes proposed notes, even for the author
        assert data(await c.call_tool("notebook_search", {"query": "brand"}))["count"] == 0


@pytest.mark.anyio
async def test_other_actor_sees_nothing_of_a_proposed_notebook(mem):
    m = mem()
    async with m.connect("claude-code") as c:
        await propose(c)
        w = data(await write(c, notebook="obs", type="Project", title="Grafana"))
    async with m.connect("opencode") as o:
        for tool, a in (
            ("notebook_describe", {"notebook": "obs"}),
            ("notebook_read", {"notebook": "obs", "id": w["id"]}),
            ("notebook_update", {"notebook": "obs", "id": w["id"], "append": "x\n"}),
            ("notebook_search", {"query": "x", "notebook": "obs"}),
            ("notebook_list", {"notebook": "obs"}),
            ("notebook_validate", {"notebook": "obs", "id": w["id"]}),
        ):
            assert_error(await o.call_tool(tool, a), "not_found")
        assert_error(await write(o, notebook="obs", type="Project", title="Mine"), "not_found")
        for uri in ("okf://obs/index", f"okf://obs/{w['id'].lstrip('/')}"):
            await assert_resource_error(o, uri, "not_found")
        assert data(await o.call_tool("notebook_search", {"query": "Grafana"}))["count"] == 0
        assert data(await o.call_tool("notebook_list", {}))["count"] == 0


@pytest.mark.anyio
async def test_approve_publishes_notes_and_reject_stops_writes(mem):
    m = mem()
    async with m.connect("claude-code") as c:
        await propose(c)
        w = data(await write(c, notebook="obs", type="Project", title="Grafana",
                             body="Grafana dashboards for latency.\n"))
        lifecycle(m).approve("obs")
    async with m.connect("opencode") as o:
        r = data(await o.call_tool("notebook_read", {"notebook": "obs", "id": w["id"]}))
        assert r["etag"] == w["etag"]
        s = data(await o.call_tool("notebook_search", {"query": "dashboards"}))
        assert [h["id"] for g in s["groups"] for h in g["results"]] == [w["id"]]
        assert not (await write(o, notebook="obs", type="Project", title="Loki")).is_error
    async with m.connect("claude-code") as c:
        await c.call_tool("notebook_create", {
            **WS, "slug": "obs2", "name": "Metrics pipeline",
            "description": "Prometheus remote-write pipelines, retention and cardinality budgets.",
            "scope": "Write: pipeline configs. Do not write: dashboards.",
            "rationale": "Pipelines differ from dashboards.", "confirm_distinct": True})
        lifecycle(m).reject("obs2", "not needed")
        assert_error(await write(c, notebook="obs2", type="Project", title="X"), "not_found")
