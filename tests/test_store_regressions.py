"""Regressions in the core store: slugs, title limits, status reset."""

import threading

import pytest

from okf_notebooks.store import Invalid, Store

LONG = "A body that is comfortably longer than twenty characters.\n"


def put(store, title, actor="claude-code", **kw):
    return store.write_concept(
        "notes",
        type=kw.pop("type", "Playbook"),
        title=title,
        frontmatter={"description": "d"},
        body=LONG,
        actor=actor,
        **kw,
    )


@pytest.fixture
def store(root):
    return Store(root, git=False)


# -- F1 ---------------------------------------------------------------------
@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Откат релиза", "otkat-reliza"),
        ("Щётка, ёж и ЮЛА!", "schetka-ezh-i-yula"),
        ("  Deploy 🚀 now!!  ", "deploy-now"),
        ("Café Münch", "cafe-munch"),
    ],
)
def test_slug_is_ascii_transliterated(store, title, slug):
    c = put(store, title).concept
    assert c.id == f"/playbooks/{slug}"
    assert c.frontmatter["title"] == title.strip()


def test_title_without_letters_is_invalid_with_violation(store):
    with pytest.raises(Invalid) as e:
        put(store, "🚀🚀")
    assert [(v.rule, v.level) for v in e.value.violations] == [("title", "error")]


def test_same_title_gets_numeric_suffix_not_conflict(store):
    ids = [put(store, "Deploy").concept.id for _ in range(3)]
    assert ids == ["/playbooks/deploy", "/playbooks/deploy-2", "/playbooks/deploy-3"]


def test_duplicate_title_is_only_a_warning(store):
    put(store, "Deploy")
    res = put(store, "Deploy")
    assert any(w.startswith("duplicate-title") for w in res.warnings)


def test_same_slug_different_title_also_gets_suffix(store):
    put(store, "Deploy")
    assert put(store, "deploy!").concept.id == "/playbooks/deploy-2"


def test_concurrent_creates_of_one_title_get_distinct_ids(root):
    stores = [Store(root, git=False) for _ in range(6)]
    ids, errs = [], []

    def go(s):
        try:
            ids.append(put(s, "Race").concept.id)
        except Exception as e:  # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=go, args=(s,)) for s in stores]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errs == [] and len(set(ids)) == 6


# -- F2 ---------------------------------------------------------------------
@pytest.mark.parametrize("n", [201, 300, 5000])
def test_overlong_title_is_invalid_with_title_violation(store, root, n):
    with pytest.raises(Invalid) as e:
        put(store, "a" * n)
    assert "title" in {v.rule for v in e.value.violations}
    assert not list((root / "notebooks/notes/playbooks").glob("*.md"))


def test_long_valid_title_gets_capped_slug(store):
    c = put(store, "word " * 40).concept  # 200 chars
    assert len(c.id) < 120


def test_overlong_type_is_invalid_not_oserror(store):
    with pytest.raises(Invalid):
        put(store, "x", type="T" * 400)


@pytest.mark.parametrize("n", [20, 400])
def test_bad_type_error_truncates_the_echoed_type(store, n):
    with pytest.raises(Invalid) as e:
        put(store, "x", type="Q" * n)
    shown = [str(e.value), *(v.message for v in e.value.violations)]
    assert all("Q" * 65 not in m for m in shown)
    assert any("Q" * 64 + "…" in m for m in shown) == (n > 64)


# -- F3 ---------------------------------------------------------------------
def test_agent_edit_resets_stable_to_draft(store):
    c = put(store, "Doc", actor="human").concept
    h = store.update_concept(
        "notes", c.id, base_etag=c.etag, fields={"status": "stable"}, actor="human"
    ).concept
    assert h.frontmatter["status"] == "stable"
    res = store.append_concept("notes", c.id, text="more text here\n", actor="claude-code")
    assert res.concept.frontmatter["status"] == "draft"
    assert any(w.startswith("status-reset") for w in res.warnings)


def test_agent_edit_keeps_deprecated_hidden_from_default_search(store):
    c = put(store, "Doc", actor="human").concept
    store.update_concept(
        "notes", c.id, base_etag=c.etag, fields={"status": "deprecated"}, actor="human"
    )
    res = store.append_concept("notes", c.id, text="more text here\n", actor="claude-code")
    assert res.concept.frontmatter["status"] == "deprecated"
    assert not any(w.startswith("status-reset") for w in res.warnings)
    assert store.index.search("comfortably").hits == []
    assert [h.id for h in store.index.search("comfortably", status=["deprecated"]).hits] == [c.id]


def test_human_edit_keeps_stable(store):
    c = put(store, "Doc", actor="human").concept
    h = store.update_concept(
        "notes", c.id, base_etag=c.etag, fields={"status": "stable"}, actor="human"
    ).concept
    res = store.append_concept("notes", c.id, text="more text here\n", actor="human")
    assert res.concept.frontmatter["status"] == "stable" and res.warnings == []
    assert h.frontmatter["status"] == "stable"
