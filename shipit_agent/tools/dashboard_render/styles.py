"""Inline stylesheet for the dashboard render tool.

Kept in its own module so the HTML renderer stays readable and the CSS
can be tweaked without scrolling past rendering logic. The palette is
deliberately muted (system cream background, soft pastel accents) so
numbers and headings stay the focus — the same aesthetic as the
Claude-Desktop-style life dashboards the tool is modelled on.
"""

from __future__ import annotations

BASE_CSS = """*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#f8f7f4;color:#1a1a18;padding:24px 16px;max-width:820px;margin:0 auto}
h1{font-size:24px;font-weight:500;margin-bottom:4px;line-height:1.3}
.sub{font-size:12px;color:#888;margin-bottom:28px}
.sec{margin-bottom:32px}
.sec-title{font-size:11px;font-weight:500;letter-spacing:.09em;color:#888;text-transform:uppercase;margin-bottom:14px;padding-bottom:7px;border-bottom:1px solid #e8e7e3}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.g4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
.metric{background:#f0efe9;border-radius:10px;padding:14px;text-align:center}
.metric-label{font-size:11px;color:#888;margin-bottom:5px}
.metric-value{font-size:22px;font-weight:500;word-break:break-word}
.metric-value.small{font-size:15px}
.metric-sub{font-size:11px;color:#666;margin-top:3px}
.card{background:#fff;border:1px solid #e8e7e3;border-radius:12px;padding:14px 16px;margin-bottom:10px}
.card-title{font-size:12px;font-weight:500;margin-bottom:10px}
.badge{display:inline-block;font-size:11px;font-weight:500;padding:3px 9px;border-radius:20px;margin-right:4px}
.b-blue{background:#e6f1fb;color:#0c447c}
.b-green{background:#eaf3de;color:#27500a}
.b-amber{background:#faeeda;color:#633806}
.b-purple{background:#eeedfe;color:#3c3489}
.b-gray{background:#ececea;color:#555}
.b-red{background:#fbe6e2;color:#8b2d19}
.bar-row{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.bar-lbl{font-size:12px;color:#555;min-width:160px}
.bar-bg{flex:1;height:7px;background:#e8e7e3;border-radius:4px;overflow:hidden}
.bar-fill{height:100%;border-radius:4px}
.bar-pct{font-size:12px;font-weight:500;min-width:36px;text-align:right}
.tl-wrap{position:relative;padding-left:24px}
.tl-row{margin-bottom:16px;position:relative}
.tl-dot{width:12px;height:12px;border-radius:50%;position:absolute;left:-24px;top:3px}
.tl-line{position:absolute;left:-19px;top:15px;width:1px;bottom:-16px;background:#ddd}
.tl-period{font-size:11px;font-weight:500;color:#888;margin-bottom:3px}
.tl-head{font-size:13px;font-weight:500;margin-bottom:3px}
.tl-desc{font-size:12px;color:#555;line-height:1.5}
.tl-tags{margin-top:5px}
.trait-row{display:flex;align-items:flex-start;gap:10px;padding:8px 0;border-bottom:1px solid #f0efe9}
.trait-row:last-child{border-bottom:none}
.trait-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;margin-top:4px}
.trait-text{font-size:12px;color:#555;line-height:1.5}
.trait-text strong{color:#1a1a18;font-weight:500}
.phase-card{border:1px solid #e8e7e3;border-radius:0 12px 12px 0;padding:14px 16px;margin-bottom:8px;border-left:3px solid #888}
.phase-year{font-size:13px;font-weight:500;margin-bottom:2px}
.phase-sub{font-size:11px;color:#888;margin-bottom:8px}
.phase-items{font-size:12px;color:#555;line-height:1.8}
.verdict-box{background:#eaf3de;border:1px solid #c0dd97;border-radius:12px;padding:16px 18px;margin-top:24px}
.verdict-title{font-size:14px;font-weight:500;color:#27500a;margin-bottom:6px}
.verdict-text{font-size:13px;color:#1a1a18;line-height:1.7}
.verdict-text strong{font-weight:600}
.lifestyle-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px}
.lifestyle-item{background:#f0efe9;border-radius:10px;padding:12px 14px}
.lifestyle-title{font-size:12px;font-weight:500;margin-bottom:3px}
.lifestyle-desc{font-size:11px;color:#666;line-height:1.4}
.chart-wrap{position:relative;width:100%;height:240px;margin-bottom:16px}
.callout{background:#fff;border:1px solid #e8e7e3;border-radius:12px;padding:14px 16px}
.callout-head{font-size:13px;font-weight:500;margin-bottom:6px}
.callout-body{font-size:12px;color:#555;line-height:1.6}
@media (max-width:540px){
  body{padding:16px 12px}
  .g3,.g4,.lifestyle-grid{grid-template-columns:1fr 1fr}
  .bar-lbl{min-width:110px}
}
"""
