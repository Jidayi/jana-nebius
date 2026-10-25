"""Proposal parser output is checked against real configuration declarations with synthetic milestone bindings."""

from jana_tools import proposals


def test_proposals_of_milestones_in_force_have_keys(monkeypatch):
    keys = proposals.declared_keys()
    assert "release_slsa_target_level" in keys["SEC-22"]
    monkeypatch.setattr(proposals, "proposal_counts", lambda: {"SEC-22": 1, "ZZZ-98": 2})
    monkeypatch.setattr(
        proposals,
        "primary_requirements",
        lambda milestone: [("synthetic", "SEC-22")] if milestone == "M0" else [("synthetic", "ZZZ-98")],
    )
    monkeypatch.setattr(proposals, "MILESTONES_IN_FORCE", ("M0",))
    assert proposals.proposal_errors() == []
    monkeypatch.setattr(proposals, "MILESTONES_IN_FORCE", ("M0", "M40"))
    assert proposals.proposal_errors() == ["ZZZ-98 (M40) has 2 proposal value(s) and no configuration key"]
