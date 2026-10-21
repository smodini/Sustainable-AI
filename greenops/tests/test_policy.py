from app.config import EscalationPolicy, IdlePolicy, load_policies


def test_article_defaults():
    p = IdlePolicy()
    assert p.observation_days == 14
    assert p.exemption_tags == (("hygiene-status", "exempt-from-hygiene"),)


def test_escalation_is_notice_warning_stop_snapshot_delete_over_14_days():
    e = EscalationPolicy()
    assert (e.notice_day, e.warning_day, e.stop_snapshot_day, e.delete_day) == (0, 3, 7, 14)
    assert e.snapshot_retention_days == 7


def test_env_override_of_exemption_tags():
    idle, _ = load_policies({"GREENOPS_EXEMPTION_TAGS": "keep-alive=true, team = protected"})
    assert idle.exemption_tags == (("keep-alive", "true"), ("team", "protected"))


def test_malformed_exemption_env_is_rejected():
    try:
        load_policies({"GREENOPS_EXEMPTION_TAGS": "keep-alive"})
    except ValueError:
        return
    raise AssertionError("expected ValueError")
