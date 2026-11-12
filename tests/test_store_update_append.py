import pytest

from okf_notebooks.store import Conflict, NotFound, Store


@pytest.fixture
def store(root):
    return Store(root, git=False)


@pytest.fixture
def concept(store):
    return store.write_concept(
        "notes",
        type="Playbook",
        title="Deploy",
        frontmatter={"description": "d"},
        body="step 1 of the deploy runbook\n",
        actor="human",
    ).concept


def test_update_with_matching_etag_writes(store, concept):
    res = store.update_concept(
        "notes",
        concept.id,
        base_etag=concept.etag,
        body="step 1 of the deploy runbook\nstep 2\n",
        actor="claude-code",
    )
    assert res.concept.etag != concept.etag
    got = store.read_concept("notes", concept.id)
    assert got.body == "step 1 of the deploy runbook\nstep 2\n"
    assert got.frontmatter["description"] == "d"  # kept when not passed
    assert got.etag == res.concept.etag


def test_update_can_replace_frontmatter(store, concept):
    store.update_concept(
        "notes",
        concept.id,
        base_etag=concept.etag,
        frontmatter={"title": "Deploy", "description": "new"},
        actor="a",
    )
    got = store.read_concept("notes", concept.id)
    assert got.frontmatter["description"] == "new"
    assert got.body == "step 1 of the deploy runbook\n"


def test_update_with_stale_etag_is_conflict_with_current_content(store, concept):
    store.update_concept(
        "notes", concept.id, base_etag=concept.etag, body="mine\n", actor="a"
    )
    with pytest.raises(Conflict) as e:
        store.update_concept(
            "notes", concept.id, base_etag=concept.etag, body="theirs\n", actor="b"
        )
    assert e.value.code == "conflict"
    assert e.value.current.body == "mine\n"
    assert store.read_concept("notes", concept.id).body == "mine\n"


def test_update_missing_concept_is_not_found(store):
    with pytest.raises(NotFound):
        store.update_concept(
            "notes", "/terms/x", base_etag="0" * 64, body="x", actor="a"
        )


def test_append_adds_to_end_of_body_without_etag(store, concept):
    res = store.append_concept(
        "notes", concept.id, text="step 2\n", actor="claude-code"
    )
    got = store.read_concept("notes", concept.id)
    assert got.body == "step 1 of the deploy runbook\nstep 2\n"
    assert got.frontmatter["description"] == "d"
    assert res.concept.etag == got.etag


def test_append_inserts_newline_when_body_has_no_trailing_one(store):
    c = store.write_concept(
        "notes",
        type="Term",
        title="T",
        frontmatter={"description": "d"},
        body="a" * 20,
        actor="a",
    ).concept
    store.append_concept("notes", c.id, text="b", actor="a")
    assert store.read_concept("notes", c.id).body == "a" * 20 + "\nb"


def test_append_missing_concept_is_not_found(store):
    with pytest.raises(NotFound):
        store.append_concept("notes", "/terms/x", text="x", actor="a")
