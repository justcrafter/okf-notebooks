"""FTS5 index, search and list through the public core API."""

import os
import shutil
import sqlite3
import time

import pytest
from registry_helpers import make_ws

from okf_notebooks.indexer import BadCursor, FTS5Unavailable, Index, check_fts5
from okf_notebooks.store import Store


def put(store, ws="notes", type_="Term", title="T", desc="d", body="x" * 25, **fm):
    return store.write_concept(
        ws,
        type=type_,
        title=title,
        frontmatter={"description": desc, **fm},
        body=body,
        actor="claude-code",
    ).concept.id


def ids(res):
    return [h.id for h in res.hits]


def hand_file(root, ws, rel, title, body, extra=""):
    p = root / "notebooks" / ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\ntype: Term\ntitle: {title}\ndescription: hand\n{extra}---\n{body}\n"
    )
    return p


def test_fts5_available():
    check_fts5()
    assert issubclass(FTS5Unavailable, RuntimeError)


def test_fts5_missing_gives_clear_error(monkeypatch):
    real = sqlite3.connect

    class Fake:
        def __init__(self):
            self.con = real(":memory:")

        def execute(self, sql, *a):
            if "fts5" in sql:
                raise sqlite3.OperationalError("no such module: fts5")
            return self.con.execute(sql, *a)

        def close(self):
            self.con.close()

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: Fake())
    with pytest.raises(FTS5Unavailable, match="FTS5"):
        check_fts5()


def test_ranking_title_over_tags_over_description_over_body(root):
    s = Store(root, git=False)
    put(s, title="Alpha body", desc="nothing", body="the word zebra appears here once")
    put(s, title="Beta desc", desc="zebra in description", body="y" * 30)
    put(s, title="Gamma tags", desc="nothing", body="z" * 30, tags=["zebra"])
    put(s, title="Zebra title", desc="nothing", body="w" * 30)
    res = s.index.search("zebra")
    assert [h.title for h in res.hits] == [
        "Zebra title",
        "Gamma tags",
        "Beta desc",
        "Alpha body",
    ]


def test_results_have_only_summary_fields_no_body(root):
    s = Store(root, git=False)
    put(s, title="Pods", desc="about pods", body="secret-body-token " * 5)
    (hit,) = s.index.search("secret").hits
    assert set(vars(hit)) == {
        "notebook", "id", "title", "type", "description",
        "snippet", "status", "stale",
    }  # fmt: skip
    assert "secret-body-token" in hit.snippet
    assert hit.status == "draft"
    assert hit.id == "/terms/pods"


def test_snippet_at_most_200_chars(root):
    s = Store(root, git=False)
    put(s, title="Long", body="needle " + "lorem ipsum dolor " * 200)
    (hit,) = s.index.search("needle").hits
    assert 0 < len(hit.snippet) <= 200


def test_filters_notebook_types_tags_status(root):
    make_ws(root, "other", "name: o\nstatus: active\ntypes: [Term, Decision]\n")
    s = Store(root, git=False)
    put(s, title="Kafka term", tags=["mq", "infra"], body="kafka broker topic")
    put(s, type_="Project", title="Kafka project", tags=["mq"], body="kafka cluster")
    put(s, "other", title="Kafka elsewhere", body="kafka other")
    s.update_concept(
        "notes",
        "/terms/kafka-term",
        base_etag=s.read_concept("notes", "/terms/kafka-term").etag,
        actor="claude-code",
    )

    assert {h.notebook for h in s.index.search("kafka").hits} == {"notes", "other"}
    assert ids(s.index.search("kafka", notebook="other")) == ["/terms/kafka-elsewhere"]
    assert ids(s.index.search("kafka", notebook="notes", types=["project"])) == [
        "/projects/kafka-project"
    ]
    assert ids(s.index.search("kafka", notebook="notes", tags=["infra"])) == [
        "/terms/kafka-term"
    ]
    assert len(s.index.search("kafka", notebook="notes", tags=["mq"]).hits) == 2
    assert s.index.search("kafka", notebook="notes", status=["stable"]).hits == []
    assert len(s.index.search("kafka", notebook="notes", status=["draft"]).hits) == 2


def test_no_notebook_search_grouped_and_active_only(root):
    make_ws(root, "second", "name: s\nstatus: active\ntypes: [Term]\n")
    make_ws(
        root, "pending", "name: p\nstatus: proposed\ntypes: [Term]\n", where="_proposed"
    )
    make_ws(root, "old", "name: a\nstatus: archived\ntypes: [Term]\n", where="_archive")
    s = Store(root, git=False)
    put(s, title="One", body="grapes in notes")
    put(s, "second", title="Two", body="grapes in second")
    put(s, "second", title="Three", body="grapes grapes grapes")
    hand_file(root, "pending", "terms/p.md", "P", "grapes proposed")
    shutil.copytree(root / "_proposed" / "pending", root / "notebooks" / "pend2")
    (root / "notebooks/pend2/.okf/notebook.yaml").write_text("status: proposed\n")
    hand_file(root, "pend2", "terms/q.md", "Q", "grapes hidden")

    res = s.index.search("grapes")
    assert sorted(g.notebook for g in res.groups) == ["notes", "second"]
    for g in res.groups:
        assert all(h.notebook == g.notebook for h in g.results)
    assert len(res.hits) == 3
    assert s.index.search("grapes", notebook="pending").hits == []


def test_deprecated_only_on_explicit_filter(root):
    s = Store(root, git=False)
    put(s, title="Live", body="mango fresh")
    hand_file(
        root, "notes", "terms/old.md", "Old", "mango ancient", "status: deprecated\n"
    )
    assert ids(s.index.search("mango")) == ["/terms/live"]
    assert ids(s.index.search("mango", status=["deprecated"])) == ["/terms/old"]
    assert [i.id for i in s.index.list().items] == ["/terms/live"]
    assert [i.id for i in s.index.list(status=["deprecated"]).items] == ["/terms/old"]


def test_stale_after_marks_stale(root):
    s = Store(root, git=False)
    old = "generated: {by: x, at: '2020-01-01T00:00:00Z'}\nstale_after: 180d\n"
    hand_file(root, "notes", "decisions/old.md", "Old", "papaya", old)
    put(s, type_="Decision", title="Fresh", body="papaya fresh", owner="a")
    by_id = {h.id: h for h in s.index.search("papaya").hits}
    assert by_id["/decisions/old"].stale is True
    assert by_id["/decisions/fresh"].stale is False
    listed = {i.id: i.stale for i in s.index.list().items}
    assert listed["/decisions/old"] is True


def test_naive_or_unparsable_generated_at_does_not_break_search_or_list(root):
    s = Store(root, git=False)
    naive = "generated: {by: x, at: '2020-01-01T00:00:00'}\nstale_after: 180d\n"
    junk = "generated: {by: x, at: 'last tuesday'}\nstale_after: 180d\n"
    hand_file(root, "notes", "decisions/naive.md", "Naive", "guava", naive)
    hand_file(root, "notes", "decisions/junk.md", "Junk", "guava", junk)
    by_id = {h.id: h for h in s.index.search("guava").hits}
    assert by_id["/decisions/naive"].stale is True  # naive is read as UTC
    assert by_id["/decisions/junk"].stale is False
    listed = {i.id: i.stale for i in s.index.list().items}
    assert listed == {"/decisions/naive": True, "/decisions/junk": False}


@pytest.mark.parametrize("huge", ["99999999999999d", "99999999999999999999y", "9" * 400 + "w"])
def test_overflowing_stale_after_is_not_stale_and_does_not_break_search_or_list(root, huge):
    s = Store(root, git=False)
    extra = f"generated: {{by: x, at: '2020-01-01T00:00:00Z'}}\nstale_after: {huge}\n"
    hand_file(root, "notes", "decisions/huge.md", "Huge", "kiwi", extra)
    hand_file(root, "notes", "decisions/ok.md", "Ok", "kiwi",
              "generated: {by: x, at: '2020-01-01T00:00:00Z'}\nstale_after: 180d\n")
    by_id = {h.id: h for h in s.index.search("kiwi").hits}
    assert by_id["/decisions/huge"].stale is False
    assert by_id["/decisions/ok"].stale is True
    assert {i.id: i.stale for i in s.index.list().items} == {
        "/decisions/huge": False,
        "/decisions/ok": True,
    }


def test_stale_horizon_boundary_is_four_digits(root):
    s = Store(root, git=False)
    old = "generated: {{by: x, at: '1990-01-01T00:00:00Z'}}\nstale_after: {}\n"
    for name, horizon in [("five", "10000d"), ("huge", "99999y"), ("four", "9999d")]:
        hand_file(root, "notes", f"decisions/{name}.md", name, "durian", old.format(horizon))
    stale = {h.id: h.stale for h in s.index.search("durian").hits}
    assert stale == {"/decisions/five": False, "/decisions/huge": False, "/decisions/four": True}
    assert {i.id: i.stale for i in s.index.list().items} == stale


def test_cyrillic_english_diacritics_prefix_no_stemming(root):
    s = Store(root, git=False)
    put(s, title="Деплой кластера", body="Развёртывание через ArgoCD, café menu")
    assert ids(s.index.search("деплой")) == ["/terms/deploy-klastera"]
    assert ids(s.index.search("ДЕПЛ")) == ["/terms/deploy-klastera"]  # prefix, case
    assert ids(s.index.search("cafe")) == ["/terms/deploy-klastera"]  # diacritics
    assert ids(s.index.search("argocd")) != []
    assert s.index.search("деплоить").hits == []  # no stemming
    assert s.index.search("clusters").hits == []


def test_list_by_type_tag_and_cursor_pagination(root):
    s = Store(root, git=False)
    for n in "abcde":
        put(s, title=f"Item {n}", tags=["t1"] if n in "abc" else ["t2"])
    put(s, type_="Project", title="Proj", tags=["t1"])
    page1 = s.index.list(types=["Term"], limit=2)
    assert [i.id for i in page1.items] == ["/terms/item-a", "/terms/item-b"]
    page2 = s.index.list(types=["Term"], limit=2, cursor=page1.next_cursor)
    assert [i.id for i in page2.items] == ["/terms/item-c", "/terms/item-d"]
    page3 = s.index.list(types=["Term"], limit=2, cursor=page2.next_cursor)
    assert [i.id for i in page3.items] == ["/terms/item-e"]
    assert page3.next_cursor is None
    assert [i.id for i in s.index.list(tags=["t1"]).items] == [
        "/projects/proj", "/terms/item-a", "/terms/item-b", "/terms/item-c",
    ]  # fmt: skip
    with pytest.raises(BadCursor):
        s.index.list(cursor="%%%")


def test_startup_sync_picks_up_hand_files_and_removals(root):
    hand_file(root, "notes", "terms/hand.md", "Hand", "lychee text")
    hand_file(root, "notes", "terms/gone.md", "Gone", "lychee gone")
    first = Index(root)
    assert sorted(ids(first.search("lychee"))) == ["/terms/gone", "/terms/hand"]
    (root / "notebooks/notes/terms/gone.md").unlink()
    second = Index(root)  # new process: startup sync
    second.sync()
    assert ids(second.search("lychee")) == ["/terms/hand"]


def test_write_updates_index_point_wise(root):
    s = Store(root, git=False)
    cid = put(s, title="Pt", body="firstword here")
    assert ids(s.index.search("firstword")) == [cid]
    etag = s.read_concept("notes", cid).etag
    s.update_concept(
        "notes", cid, base_etag=etag, body="secondword here now\n", actor="a"
    )
    assert s.index.search("firstword").hits == []
    assert ids(s.index.search("secondword")) == [cid]
    s.append_concept("notes", cid, text="thirdword", actor="a")
    assert ids(s.index.search("thirdword")) == [cid]


def test_quick_check_sees_hand_edit_new_and_deleted_before_search(root):
    s = Store(root, git=False)
    cid = put(s, title="Edited", body="before text")
    assert ids(s.index.search("before")) == [cid]
    path = root / "notebooks/notes" / (cid[1:] + ".md")
    path.write_text(path.read_text().replace("before text", "afterwards text"))
    os.utime(path, ns=(time.time_ns() + 5_000_000_000,) * 2)
    hand_file(root, "notes", "terms/brandnew.md", "Brand", "newcomer here")
    assert s.index.search("before").hits == []
    assert ids(s.index.search("afterwards")) == [cid]
    assert ids(s.index.search("newcomer")) == ["/terms/brandnew"]
    path.unlink()
    assert s.index.search("afterwards").hits == []


def test_other_process_write_visible(root):
    a, b = Store(root, git=False), Store(root, git=False)
    assert a.index.search("kiwi").hits == []
    cid = put(b, title="Fruit", body="kiwi from b")
    assert ids(a.index.search("kiwi")) == [cid]


def test_rebuild_after_deleting_index_dir(root):
    s = Store(root, git=False)
    cid = put(s, title="Keep", body="durian body")
    shutil.rmtree(root / ".index")
    assert ids(s.index.search("durian")) == [cid]
    assert (root / ".index" / "fts.sqlite").is_file()
    shutil.rmtree(root / ".index")
    assert ids(Index(root).search("durian")) == [cid]  # fresh process too


def test_rebuild_on_schema_change_and_corruption(root):
    s = Store(root, git=False)
    cid = put(s, title="Keep", body="durian body")
    db = root / ".index" / "fts.sqlite"
    con = sqlite3.connect(db)
    con.execute("UPDATE meta SET value = '0' WHERE key = 'schema_version'")
    con.commit()
    con.close()
    assert ids(Index(root).search("durian")) == [cid]
    ver = sqlite3.connect(db).execute("SELECT value FROM meta").fetchone()[0]
    assert ver != "0"
    db.write_bytes(b"this is not a sqlite database" * 50)
    for sfx in ("-wal", "-shm"):
        (root / ".index" / f"fts.sqlite{sfx}").unlink(missing_ok=True)
    assert ids(Index(root).search("durian")) == [cid]
