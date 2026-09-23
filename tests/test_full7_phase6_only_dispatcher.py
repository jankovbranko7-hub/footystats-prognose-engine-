from pathlib import Path

def test_phase6_dispatcher_precedes_cp3_paths():
    source = Path("research/run_full7_phase2_phase3.py").read_text(encoding="utf-8")
    dispatcher = source.index("phase6_worker = (")
    cp3 = source.index("# Post-CP3 rule:")
    assert dispatcher < cp3
    block = source[dispatcher:cp3]
    assert "run_phase6_only" in block
    assert "return" in block

def test_phase6_only_hard_guards_present():
    source = Path("research/run_full7_phase6_only.py").read_text(encoding="utf-8")
    for key in (
        "COLLECTION_ALLOWED",
        "API_COLLECTION_ALLOWED",
        "CP1_ALLOWED",
        "CP2_ALLOWED",
        "CP3_ALLOWED",
        "PHASE4_REBUILD_ALLOWED",
        "PHASE5_REBUILD_ALLOWED",
        "O25_PHASE6_ALLOWED",
    ):
        assert key in source
    assert "PHASE5_PREOOS_1X2.npz" in source
    assert "PHASE5_PREOOS_BTTS.npz" in source
    assert "with block_network()" in source

def test_phase6_has_lock_before_oos_call():
    source = Path("research/full7_phase6_decision_research.py").read_text(encoding="utf-8")
    fn = source[source.index("def run_phase6("):]
    assert fn.index("_build_phase6_lock") < fn.index("_evaluate_oos_once")
    assert "O25_HOLD = True" in source
    research = source[source.index("def _research_rules"):source.index("def _compact_selected")]
    assert '"O25"' not in research

def test_phase6_dispatcher_is_bound_to_exact_audit_worker_and_branch():
    source = Path("research/run_full7_phase2_phase3.py").read_text(encoding="utf-8")
    assert 'RENDER_SERVICE_ID") == "srv-damiu0p42hec739a0rig"' in source
    assert 'RENDER_GIT_BRANCH") == "audit/full7-cp2-20260922"' in source

def test_phase6_guards_default_forbidden_flags_to_false_and_reject_true():
    source = Path("research/run_full7_phase6_only.py").read_text(encoding="utf-8")
    assert 'os.environ.get(key, "false").strip().lower()' in source
    assert 'if value != "false"' in source
