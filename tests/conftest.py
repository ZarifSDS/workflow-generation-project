"""Shared test setup."""

from dataclasses import replace

import pytest

from apps.studio import pipeline


@pytest.fixture(autouse=True)
def _search_step_off_by_default(request, monkeypatch):
    """Most tests predate the Search results step and start runs at Research; tests marked
    `search_step` keep it on, as it is in the app."""
    if request.node.get_closest_marker("search_step"):
        return
    step = pipeline.STEPS["search_results"]
    monkeypatch.setitem(pipeline.STEPS, "search_results", replace(step, default_on=False))
