"""Carbon-aware placement (orchestration layer).

    grid intensity data (WattTime) -> scikit-learn forecast -> window/region planner
        -> closed-loop controller (re-plan, measure, feed forecast error back)

The threshold recommender in ``app.services.carbon_orchestrator`` (notify / scale down /
migrate / stop for wasteful *existing* resources) is separate and unchanged.
"""
