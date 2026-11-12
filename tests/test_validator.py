"""validation rules observed through Store and the validator API."""

import re
import subprocess

import pytest
import yaml

from okf_notebooks.store import Invalid, Store
from okf_notebooks.validator import validate_file

LONG = "A body that is comfortably longer than twenty characters.\n"


def put(
    store, title="Deploy", type="Playbook", fm=None, body=LONG, actor="claude-code"
):
    f = {"description": "How to deploy", **(fm or {})}
    return store.write_concept(
        "notes", type=type, title=title, frontmatter=f, body=body, actor=actor
    )


def rules(exc: pytest.ExceptionInfo, level="error"):
    return {v.rule for v in exc.value.violations if v.level == level}


def snapshot(root):
    return {
        p: p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".git" not in p.parts and ".tmp" not in p.parts
    }


@pytest.fixture
def store(root):
    return Store(root, git=False)


def rejected(store, root, **kw):
    before = snapshot(root)
    with pytest.raises(Invalid) as e:
        put(store, **kw)
    assert snapshot(root) == before
    return e


# -- error rules: negative + positive --------------------------------------
def test_valid_write_has_no_violations(store):
    assert put(store).warnings == []


def test_unknown_type_rejected(store, root):
    assert "type" in rules(rejected(store, root, type="Nonsense"))


def test_title_and_description_required(store, root):
    e = rejected(store, root, title="x", fm={"description": ""})
    assert "description" in rules(e)
    with pytest.raises(Invalid) as e2:
        store.write_concept(
            "notes", type="Term", title="x", frontmatter={}, body=LONG, actor="a"
        )
    assert "description" in rules(e2)
    p = validate_file(
        b"---\ntype: Term\ndescription: d\n---\n" + LONG.encode(), _ctx(store)
    )
    assert "title" in {v.rule for v in p}


def test_template_required_field(store, root):
    assert "required-field" in rules(rejected(store, root, type="Decision"))
    put(store, type="Decision", fm={"owner": "andrey"})  # filled -> ok


def test_link_must_exist_in_bundle(store, root):
    e = rejected(store, root, body=LONG + "see [x](/terms/missing.md)\n")
    assert "link" in rules(e)
    put(store, title="Term A", type="Term")
    put(store, body=LONG + "see [x](/terms/term-a.md)\n")


def test_link_in_frontmatter_field_checked(store, root):
    assert "link" in rules(rejected(store, root, fm={"see": "/terms/nope.md"}))


def test_link_outside_bundle_rejected(store, root):
    assert "link" in rules(
        rejected(store, root, body=LONG + "[x](/../../etc/passwd.md)\n")
    )


def test_size_limit(root):
    small = Store(root, git=False, max_concept_bytes=200)
    assert "size" in rules(rejected(small, root, body="x" * 300))
    put(small, body=LONG)


@pytest.mark.parametrize(
    "tags",
    [["Not A Slug"], ["a"] * 11, "plain", [1], ["ok", "под_чёрк"]],
)
def test_bad_tags_rejected(store, root, tags):
    assert "tags" in rules(rejected(store, root, fm={"tags": tags}))


def test_ten_slug_tags_accepted(store):
    put(store, fm={"tags": [f"t{i}" for i in range(10)]})
    put(store, title="Other", fm={"tags": ["cd", "k8s", "аргосd"]})


SECRETS = [
    "AKIAIOSFODNN7EXAMPLE",
    "-----BEGIN RSA PRIVATE KEY-----",
    "ghp_" + "a1B2c3D4e5" * 4,
    "xoxb-123456789012-abcdefghijkl",
    "sk-ant-api03-" + "Ab1_" * 8,
    "api_key = 'q8Zx2kLm9PqR4tVw7YzB'",
    "AIza" + "Sy" + "A" * 33,
]


@pytest.mark.parametrize("secret", SECRETS)
def test_secret_in_body_rejected_and_not_echoed(store, root, secret):
    e = rejected(store, root, body=LONG + f"config: {secret}\n")
    assert "secret" in rules(e)
    assert all(secret not in v.message for v in e.value.violations)


def test_ordinary_text_is_not_a_secret(store):
    put(
        store,
        body="The token is rotated weekly; password policy lives in Vault. sk-1\n",
    )


def test_all_errors_returned_as_list(store, root):
    e = rejected(
        store,
        root,
        type="Decision",
        fm={"tags": "bad"},
        body="short AKIAIOSFODNN7EXAMPLE [x](/terms/zz.md)",
    )
    assert {"required-field", "tags", "secret", "link"} <= rules(e)


def test_secret_in_append_rejected_keeps_file(store, root):
    c = put(store).concept
    before = snapshot(root)
    with pytest.raises(Invalid) as e:
        store.append_concept("notes", c.id, text="AKIAIOSFODNN7EXAMPLE\n", actor="a")
    assert "secret" in rules(e) and snapshot(root) == before


def test_update_validates_final_file(store, root):
    c = put(store).concept
    before = snapshot(root)
    with pytest.raises(Invalid) as e:
        store.update_concept(
            "notes", c.id, base_etag=c.etag, frontmatter={"title": "Deploy"}, actor="a"
        )
    assert "description" in rules(e) and snapshot(root) == before


def test_error_makes_no_git_commit(root):
    s = Store(root)
    put(s)
    n = lambda: subprocess.run(
        ["git", "-C", str(root), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    before = n()
    with pytest.raises(Invalid):
        put(s, title="Bad", body=LONG + "AKIAIOSFODNN7EXAMPLE")
    assert n() == before


# -- file level rules (UTF-8, YAML) ----------------------------------------
def _ctx(store):
    from okf_notebooks.validator import Context

    return Context(
        bundle=store.root / "notebooks/notes",
        cid="/terms/x",
        types=store.types.types(store.root / "notebooks/notes"),
        max_concept_bytes=65536,
    )


def test_invalid_utf8_is_error(store):
    v = validate_file(b"---\ntype: Term\n---\n\xff\xfe bad", _ctx(store))
    assert "utf8" in {x.rule for x in v}


def test_invalid_yaml_is_error(store):
    v = validate_file(b"---\ntype: [unclosed\n---\n" + LONG.encode(), _ctx(store))
    assert "yaml" in {x.rule for x in v}


def test_missing_frontmatter_is_error(store):
    v = validate_file(LONG.encode(), _ctx(store))
    assert "yaml" in {x.rule for x in v}


def test_valid_file_passes(store):
    data = b"---\ntype: Term\ntitle: T\ndescription: d\n---\n" + LONG.encode()
    assert [x for x in validate_file(data, _ctx(store)) if x.level == "error"] == []


def test_unencodable_text_rejected_at_write(store, root):
    assert "utf8" in rules(rejected(store, root, body="lone \ud800 surrogate " * 3))


# -- warnings -----------------------------------------------------------
def test_duplicate_title_warning(store, root):
    put(store, title="Same Title")
    # distinct file, identical title in frontmatter: write via human-owned manual file
    (root / "notebooks/notes/playbooks/other.md").write_text(
        "---\ntype: Playbook\ntitle: Brand New\ndescription: d\n---\n" + LONG
    )
    res = put(store, title="Brand New")
    # slug brand-new differs from other.md, same title -> warning
    assert any(w.startswith("duplicate-title") for w in res.warnings)
    assert (root / "notebooks/notes/playbooks/brand-new.md").is_file()


def test_unique_title_no_duplicate_warning(store):
    put(store, title="One")
    assert put(store, title="Two").warnings == []


@pytest.mark.parametrize("body", ["", "short\n"])
def test_short_body_warns_but_writes(store, body):
    res = put(store, body=body)
    assert any(w.startswith("short-body") for w in res.warnings)


def test_twenty_char_body_no_warning(store):
    assert put(store, body="x" * 20).warnings == []


# -- server-set fields ------------------------------------------------------
def fm_of(store, res):
    return store.read_concept("notes", res.concept.id).frontmatter


def test_server_sets_draft_generated_and_type_title(store):
    fm = fm_of(store, put(store, actor="opencode"))
    assert fm["status"] == "draft"
    assert fm["type"] == "Playbook" and fm["title"] == "Deploy"
    assert re.fullmatch(r"opencode/\S+", fm["generated"]["by"])
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", fm["generated"]["at"])


@pytest.mark.parametrize("val", ["180d", "26w", "6m", "2y", " 90d ", "9999y"])
def test_valid_stale_after_is_accepted(store, val):
    assert put(store, fm={"stale_after": val}).warnings == []


@pytest.mark.parametrize(
    "val", ["99999999999999d", "99999y", "soon", "180", "-5d", 180, ["1d"], "1.5y"]
)
def test_garbage_or_out_of_range_stale_after_is_rejected(store, root, val):
    e = rejected(store, root, fm={"stale_after": val})
    assert "stale-after" in rules(e)


def test_stale_after_from_type_template_unless_agent_passes(store):
    assert (
        fm_of(store, put(store, type="Decision", fm={"owner": "o"}))["stale_after"]
        == "180d"
    )
    r = put(store, title="D2", type="Decision", fm={"owner": "o", "stale_after": "30d"})
    assert fm_of(store, r)["stale_after"] == "30d"
    assert "stale_after" not in fm_of(store, put(store, title="P"))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "draft"),
        ("status", "stable"),
        ("verified", True),
        ("generated", {"by": "x", "at": "y"}),
        ("type", "Term"),
    ],
)
def test_agent_cannot_pass_server_fields_on_write(store, root, field, value):
    assert "forbidden-field" in rules(rejected(store, root, fm={field: value}))


def test_human_may_set_status_and_verified(store):
    r = put(store, actor="human", fm={"status": "stable", "verified": "2026-01-01"})
    fm = fm_of(store, r)
    assert fm["status"] == "stable" and fm["verified"] == "2026-01-01"


def test_human_edit_keeps_verified(store):
    c = put(
        store, actor="human", fm={"verified": "2026-01-01", "status": "stable"}
    ).concept
    store.append_concept("notes", c.id, text="more more more\n", actor="human")
    fm = store.read_concept("notes", c.id).frontmatter
    assert fm["verified"] == "2026-01-01" and fm["status"] == "stable"


def test_generated_rewritten_on_update(store):
    c = put(store, actor="opencode").concept
    res = store.update_concept(
        "notes", c.id, base_etag=c.etag, body=LONG * 2, actor="claude-code"
    )
    assert fm_of(store, res)["generated"]["by"].startswith("claude-code/")


def verified_concept(store, root):
    c = put(
        store, actor="human", fm={"verified": "2026-01-01", "status": "stable"}
    ).concept
    return c


def test_agent_append_resets_verified_with_warning(store, root):
    c = verified_concept(store, root)
    res = store.append_concept(
        "notes", c.id, text="agent edit text\n", actor="claude-code"
    )
    fm = fm_of(store, res)
    assert fm["status"] == "draft" and "verified" not in fm
    assert any(w.startswith("verified-reset") for w in res.warnings)


def test_agent_update_resets_verified_with_warning(store, root):
    c = verified_concept(store, root)
    res = store.update_concept(
        "notes", c.id, base_etag=c.etag, body=LONG * 2, actor="claude-code"
    )
    fm = fm_of(store, res)
    assert fm["status"] == "draft" and "verified" not in fm
    assert any(w.startswith("verified-reset") for w in res.warnings)


def test_verified_reset_message_names_the_remaining_status(store, root):
    c = verified_concept(store, root)
    res = store.append_concept("notes", c.id, text="agent edit text\n", actor="claude-code")
    (msg,) = [w for w in res.warnings if w.startswith("verified-reset")]
    assert "reset it to draft" in msg and "cleared `verified`" in msg


def test_verified_reset_message_on_deprecated_does_not_claim_draft(store, root):
    c = put(
        store, actor="human", fm={"verified": "2026-01-01", "status": "deprecated"}
    ).concept
    res = store.append_concept("notes", c.id, text="agent edit text\n", actor="claude-code")
    assert fm_of(store, res)["status"] == "deprecated"
    (msg,) = [w for w in res.warnings if w.startswith("verified-reset")]
    assert "draft" not in msg
    assert "cleared `verified`" in msg and "deprecated" in msg


def test_unverified_agent_update_has_no_reset_warning(store):
    c = put(store).concept
    res = store.update_concept(
        "notes", c.id, base_etag=c.etag, body=LONG * 2, actor="a"
    )
    assert res.warnings == []


def test_agent_cannot_promote_or_alter_server_fields_on_update(store, root):
    c = put(store).concept
    cur = store.read_concept("notes", c.id).frontmatter
    for field, value in [
        ("status", "stable"),
        ("status", "deprecated"),
        ("generated", {"by": "x", "at": "y"}),
        ("type", "Term"),
        ("verified", "2026-01-01"),
    ]:
        before = snapshot(root)
        with pytest.raises(Invalid) as e:
            store.update_concept(
                "notes",
                c.id,
                base_etag=c.etag,
                frontmatter={**cur, field: value},
                actor="a",
            )
        assert "forbidden-field" in rules(e) and snapshot(root) == before


def test_agent_roundtrip_of_read_frontmatter_is_allowed(store):
    c = put(store).concept
    cur = store.read_concept("notes", c.id)
    res = store.update_concept(
        "notes",
        c.id,
        base_etag=cur.etag,
        frontmatter={**cur.frontmatter, "tags": ["x"]},
        actor="a",
    )
    assert fm_of(store, res)["tags"] == ["x"]


def test_yaml_dump_is_valid_frontmatter(store, root):
    put(store)
    text = (root / "notebooks/notes/playbooks/deploy.md").read_text()
    assert yaml.safe_load(text.split("---\n")[1])["title"] == "Deploy"
