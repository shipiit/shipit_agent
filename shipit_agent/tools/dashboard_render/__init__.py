"""Render rich HTML dashboards (cards, charts, timelines, verdicts).

Public surface::

    from shipit_agent.tools.dashboard_render import DashboardRenderTool, render_dashboard
"""

from .dashboard_render_tool import DashboardRenderTool
from .renderer import render_dashboard

__all__ = ["DashboardRenderTool", "render_dashboard"]
