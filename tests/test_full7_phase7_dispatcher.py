import pytest

from research.run_full7_phase7_only import REQUIRED_FALSE_FLAGS, Phase7Error, _require_false_env
from research.run_full7_phase2_phase3 import _phase7_worker_authorized


def test_phase7_dispatcher_requires_every_research_and_collection_flag_false(monkeypatch):
    for name in REQUIRED_FALSE_FLAGS:
        monkeypatch.setenv(name, "false")
    receipt = _require_false_env()
    assert set(receipt) == set(REQUIRED_FALSE_FLAGS)
    assert set(receipt.values()) == {"false"}


def test_phase7_dispatcher_rejects_any_rebuild_authorization(monkeypatch):
    for name in REQUIRED_FALSE_FLAGS:
        monkeypatch.setenv(name, "false")
    monkeypatch.setenv("PHASE5_REBUILD_ALLOWED", "true")
    with pytest.raises(Phase7Error, match="phase7_guard_env_not_false:PHASE5_REBUILD_ALLOWED"):
        _require_false_env()


@pytest.mark.parametrize(
    "branch",
    ["audit/full7-cp2-20260922", "release/full7-final-rc-1.0.0"],
)
def test_phase7_dispatcher_is_reachable_on_audit_and_rc_branches(branch):
    assert _phase7_worker_authorized(
        service_id="srv-damiu0p42hec739a0rig", branch=branch, enabled="true"
    )


def test_phase7_dispatcher_rejects_production_or_main():
    assert not _phase7_worker_authorized(
        service_id="srv-da7l8ae7bikc73dp3m70", branch="main", enabled="true"
    )
