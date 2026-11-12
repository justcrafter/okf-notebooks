"""Builders for lifecycle tests (seam 1: core API against a tmp root)."""

import yaml

from okf_notebooks.auth import Actor
from okf_notebooks.lifecycle import Lifecycle
from okf_notebooks.store import Store

DESC = "Decisions, playbooks and terms about the Kubernetes platform and deployment."
SCOPE = "Write: cluster decisions and runbooks. Do not write: personal notes."


def actor(name="claude-code", policy="proposal", perms=("read", "write", "notebook_creation")):
    return Actor(name, "laptop", "t-1", frozenset(perms), policy)


def make_lc(root, **kw):
    return Lifecycle(Store(root, git=False), **kw)


def args(slug="kube", **over):
    base = {
        "slug": slug,
        "name": "Kubernetes platform",
        "description": DESC,
        "scope": SCOPE,
        "preset": "core",
        "rationale": "No existing notebook covers the cluster platform.",
    }
    base.update(over)
    return base


def meta(root, where, slug):
    return yaml.safe_load((root / where / slug / ".okf" / "notebook.yaml").read_text("utf-8"))
