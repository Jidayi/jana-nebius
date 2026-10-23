"""Proposal values become configuration keys (plan rule 7): the register check for milestones in force."""

from jana_tools import proposals


def test_proposals_of_milestones_in_force_have_keys(monkeypatch):
    assert proposals.proposal_errors() == []
    assert proposals.proposal_counts()["SEC-22"] >= 1
    assert "release_slsa_target_level" in proposals.declared_keys()["SEC-22"]

    # A milestone whose requirements carry undeclared proposals fails the check.
    counts, keys = proposals.proposal_counts(), proposals.declared_keys()
    later = next(
        m for m in (f"M{n}" for n in range(2, 42))
        if any(r in counts and r not in keys for _, r in proposals.primary_requirements(m))
    )  # fmt: skip
    monkeypatch.setattr(proposals, "MILESTONES_IN_FORCE", ("M0", "M1", later))
    assert any(f"({later}) has" in e for e in proposals.proposal_errors())
