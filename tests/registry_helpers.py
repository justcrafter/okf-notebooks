"""Shared builders for registry/index tests."""


def make_ws(root, slug, meta, concepts=(), where="notebooks"):
    ws = root / where / slug
    (ws / ".okf").mkdir(parents=True)
    (ws / ".okf" / "notebook.yaml").write_text(meta)
    (ws / "index.md").write_text(f"# {slug}\n")
    for rel, text in concepts:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    return ws


KUBE = """\
name: Платформа Kubernetes
description: Решения и плейбуки по кластерам
scope: "Что сюда писать: деплой"
preset: core
types: [Decision, Term]
status: active
"""
