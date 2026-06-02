from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .research_anomalies import POSITIVE, RISK
from .research_display import company_display_name, display_name_lookup, point_display_name, replace_identifier_with_name, resolve_display_name
from .research_models import EvidenceItem, FinancialChart, FinancialDataPoint, ResearchDraft, ResearchSignal
from .research_validation import validate_research_draft
from .utils import clean_filename


OUTPUT_DIR = Path("downloads") / "research_outputs"


def save_memo_html(draft: ResearchDraft, output_dir: str | Path = OUTPUT_DIR) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    suffix = "final" if draft.validation_report and draft.validation_report.status == "PASS_FINAL_DELIVERABLE" else "draft_not_final"
    filename = clean_filename(f"{draft.target.ticker or draft.target.name}_investment_memo_{suffix}_{draft.generated_at[:10]}", "investment_memo")
    path = output / f"{filename}.html"
    path.write_text(render_memo_html(draft), encoding="utf-8")
    _run_mobile_validation_if_needed(path, draft)
    return path


def save_dashboard_html(draft: ResearchDraft, output_dir: str | Path = OUTPUT_DIR) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    suffix = "final" if draft.validation_report and draft.validation_report.status == "PASS_FINAL_DELIVERABLE" else "draft_not_final"
    filename = clean_filename(f"{draft.target.ticker or draft.target.name}_research_dashboard_{suffix}_{draft.generated_at[:10]}", "research_dashboard")
    path = output / f"{filename}.html"
    path.write_text(render_dashboard_html(draft), encoding="utf-8")
    _run_mobile_validation_if_needed(path, draft)
    return path


def _run_mobile_validation_if_needed(path: Path, draft: ResearchDraft) -> None:
    if draft.run_metadata.get("_mobile_validation_running"):
        return
    try:
        from .research_mobile_validation import validate_mobile_html

        draft.run_metadata["_mobile_validation_running"] = True
        validate_mobile_html(path, draft)
        draft.validation_report = validate_research_draft(draft)
        path.write_text(render_memo_html(draft) if "investment_memo" in path.name else render_dashboard_html(draft), encoding="utf-8")
    except Exception as exc:
        draft.run_metadata.setdefault("mobile_validation", {"passed": False, "error": str(exc)})
    finally:
        draft.run_metadata.pop("_mobile_validation_running", None)


def render_memo_html(draft: ResearchDraft) -> str:
    content = f"""
    <main class="memo-shell">
      {_hero(draft, "投资备忘录草稿", "不限页数，结论先行；以完整呈现重要信号、图表和证据追溯为准。")}
      {_validation_section(draft)}
      {_model_runs_section(draft)}
      {_financial_charts_section(draft, compact=True)}
      {_objective_anomalies_section(draft, compact=True)}
      <section class="section">
        <div class="section-title">
          <p class="eyebrow">深度分析信号</p>
          <h2>基于已勾选异常生成的核心信号</h2>
        </div>
        <div class="signal-list">
          {''.join(_signal_card(signal, draft.evidence, compact=True, anomaly_lookup=_anomaly_title_lookup(draft)) for signal in draft.signals)}
        </div>
      </section>
      <section class="section two-col">
        <div>
          <p class="eyebrow">可比公司</p>
          <h2>精选可比与交叉验证组</h2>
          {_groups_html(draft)}
        </div>
        <div>
          <p class="eyebrow">证据审计</p>
          <h2>证据审计摘要</h2>
          {_audit_html(draft)}
        </div>
      </section>
      <section class="section">
        <p class="eyebrow">下一步验证</p>
        <h2>系统下一步自动验证计划</h2>
        <ol class="next-list">{''.join(f'<li>{_e(item)}</li>' for item in draft.next_fetch_plan)}</ol>
      </section>
      {_reference_appendix(draft)}
      {_evidence_drawer(draft)}
    </main>
    """
    return _document("AI 行业研究投资备忘录", content, draft)


def render_dashboard_html(draft: ResearchDraft) -> str:
    company_lookup = _draft_display_lookup(draft)
    content = f"""
    <main class="dashboard-shell">
      {_hero(draft, "交互式研究看板草稿", "信号卡片、证据矩阵、可比组与审计附录版本。点击信号或证据可打开右侧来源抽屉。")}
      {_validation_section(draft)}
      {_model_runs_section(draft)}
      <section class="grid-3">
        {_metric_tile("候选证据", str(len(draft.evidence)), "所有图表与文字结论必须绑定来源")}
        {_metric_tile("核心信号草稿", str(len(draft.signals)), "含亮点、风险和待验证假设")}
        {_metric_tile("真实财务图表", str(len(draft.financial_charts)), "基于 SEC XBRL / Wind 数据点")}
      </section>
      {_financial_charts_section(draft, compact=False)}
      {_objective_anomalies_section(draft, compact=False)}
      <section class="section">
        <div class="section-title">
          <p class="eyebrow">覆盖矩阵</p>
          <h2>产业链证据覆盖矩阵</h2>
          <p>矩阵用于先看“哪里证据够、哪里需要补抓”，不是最终投资结论。</p>
        </div>
        {_coverage_matrix(draft)}
      </section>
      <section class="section">
        <div class="section-title">
          <p class="eyebrow">深度分析信号</p>
          <h2>基于用户勾选异常的深度分析信号</h2>
        </div>
        <div class="signal-grid">
          {''.join(_signal_card(signal, draft.evidence, compact=False, anomaly_lookup=_anomaly_title_lookup(draft)) for signal in draft.signals)}
        </div>
      </section>
      <section class="section two-col">
        <div>
          <p class="eyebrow">可比公司</p>
          <h2>可比公司逻辑</h2>
          {_groups_html(draft)}
        </div>
        <div>
          <p class="eyebrow">审计附录</p>
          <h2>证据审计附录</h2>
          {_audit_html(draft)}
        </div>
      </section>
      <section class="section">
        <p class="eyebrow">候选证据</p>
        <h2>候选证据清单</h2>
        {_evidence_table(draft.evidence, company_lookup)}
      </section>
      {_reference_appendix(draft)}
      {_evidence_drawer(draft)}
    </main>
    """
    return _document("AI 行业研究交互看板", content, draft)


def _document(title: str, content: str, draft: ResearchDraft) -> str:
    company_lookup = _draft_display_lookup(draft)
    evidence_json = json.dumps([_evidence_payload(item, company_lookup) for item in draft.evidence], ensure_ascii=False)
    financial_json = json.dumps([_chart_payload(chart) for chart in draft.financial_charts], ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(title)} · {_e(draft.target.name)}</title>
  <style>{_style()}</style>
</head>
<body>
  {content}
  <script>
    const evidence = {evidence_json};
    const financialCharts = {financial_json};
    function showEvidence(ids) {{
      const drawer = document.getElementById('evidenceDrawer');
      const body = document.getElementById('drawerBody');
      const list = (ids || []).map(id => evidence[id]).filter(Boolean);
      body.innerHTML = list.length ? list.map((item, offset) => `
        <article class="drawer-card">
          <div class="drawer-meta">${{item.display_company || item.company || item.ticker || ''}} · ${{item.evidence_type || ''}} · ${{item.confidence_tier || ''}}</div>
          <h3>${{escapeHtml(item.display_title || item.title || item.url || 'Untitled')}}</h3>
          <p>${{escapeHtml(item.confidence_reason || '')}}</p>
          ${{item.quote ? `<blockquote>${{escapeHtml(item.quote)}}</blockquote>` : ''}}
          ${{item.page ? `<p>页码：${{escapeHtml(item.page)}}</p>` : ''}}
          ${{item.cell_reference ? `<p>表格单元格：${{escapeHtml(item.cell_reference)}}</p>` : ''}}
          ${{item.screenshot_uri ? `<figure class="source-shot"><img src="${{item.screenshot_uri}}" alt="source screenshot"><figcaption>原始截图：${{escapeHtml(item.screenshot_path || '')}}</figcaption></figure>` : '<p class="muted">截图将在证据下载与审计步骤生成后显示。</p>'}}
          <a href="${{item.url}}" target="_blank" rel="noreferrer">打开原始链接 ↗</a>
        </article>
      `).join('') : '<p class="muted">这个信号暂未绑定证据，不能升级为正式结论。</p>';
      drawer.classList.add('open');
      drawer.dataset.openedAt = String(Date.now());
    }}
    function showFinancialPoint(chartIndex, pointIndex) {{
      const drawer = document.getElementById('evidenceDrawer');
      const body = document.getElementById('drawerBody');
      const chart = financialCharts[chartIndex];
      const point = chart && chart.points ? chart.points[pointIndex] : null;
      if (!point) {{
        body.innerHTML = '<p class="muted">未找到这个数据点的来源。</p>';
        drawer.classList.add('open');
        drawer.dataset.openedAt = String(Date.now());
        return;
      }}
      const sources = point.sources || [];
      body.innerHTML = `
        <article class="drawer-card">
          <div class="drawer-meta">${{escapeHtml(point.display_company || point.company || point.ticker)}} · ${{escapeHtml(point.metric_label)}} · ${{escapeHtml(point.period)}}</div>
          <h3>${{escapeHtml(point.display_value)}}</h3>
          <p>指标：${{escapeHtml(point.metric_label)}}；期间：${{escapeHtml(point.period)}}；截至日：${{escapeHtml(point.end_date)}}。</p>
          <p class="muted">${{escapeHtml(chart.source_note || '数据来自 SEC XBRL / Wind fundamentals。当前已能追溯到 filing accession 或 Wind 字段；下一阶段会继续定位到具体表格、页码和截图。')}}</p>
          <p class="muted">财务数据截图：Wind/SEC 数据库来源通常不生成网页截图；正式版会补充 filing 页面截图或 Wind 字段审计截图。</p>
          ${{sources.map(source => `
            <div class="source-row">
              <strong>${{escapeHtml(source.title || source.form || 'financial source')}}</strong>
              <p>${{escapeHtml(source.concept || '')}} · ${{escapeHtml(source.accession || '')}}</p>
              ${{source.url ? `<a href="${{source.url}}" target="_blank" rel="noreferrer">打开原始来源 ↗</a>` : ''}}
            </div>
          `).join('')}}
        </article>
      `;
      drawer.classList.add('open');
      drawer.dataset.openedAt = String(Date.now());
    }}
    function closeEvidence() {{
      document.getElementById('evidenceDrawer').classList.remove('open');
    }}
    document.addEventListener('click', event => {{
      const drawer = document.getElementById('evidenceDrawer');
      if (!drawer || !drawer.classList.contains('open')) return;
      if (drawer.contains(event.target)) return;
      const openedAt = Number(drawer.dataset.openedAt || 0);
      if (Date.now() - openedAt < 80) return;
      closeEvidence();
    }});
    function escapeHtml(value) {{
      return String(value || '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[char]));
    }}
  </script>
</body>
</html>"""


def _draft_display_lookup(draft: ResearchDraft) -> dict[str, str]:
    return display_name_lookup([draft.target, *[company for group in draft.comparable_groups for company in group.companies]])


def _chart_payload(chart: FinancialChart) -> dict[str, Any]:
    data = chart.to_dict()
    for point in data.get("points", []):
        point["display_company"] = point.get("company") or point.get("ticker") or ""
    return data


def _evidence_payload(item: EvidenceItem, company_lookup: dict[str, str] | None = None) -> dict[str, Any]:
    data = item.to_dict()
    data["screenshot_uri"] = _local_path_to_uri(item.screenshot_path)
    display_company = item.company or resolve_display_name(item.ticker, company_lookup)
    data["display_company"] = display_company
    data["display_title"] = replace_identifier_with_name(item.title, item.ticker, display_company)
    data["title"] = data["display_title"]
    return data


def _local_path_to_uri(value: str) -> str:
    if not value:
        return ""
    try:
        return Path(value).resolve().as_uri()
    except Exception:
        return value


def _hero(draft: ResearchDraft, label: str, subtitle: str) -> str:
    return f"""
    <section class="hero">
      <div>
        <p class="eyebrow">{_e(label)}</p>
        <h1>{_e(company_display_name(draft.target))} · AI 产业链研究草稿</h1>
        <p class="hero-subtitle">{_e(subtitle)}</p>
      </div>
      <div class="hero-card">
        <span>目标公司</span><strong>{_e(company_display_name(draft.target))}</strong>
        <span>观察窗口</span><strong>最近 {draft.quarter_count} 个季度</strong>
        <span>生成时间</span><strong>{_e(draft.generated_at)}</strong>
        <span>报告状态</span><strong>{_e(draft.report_label)}</strong>
      </div>
    </section>
    <section class="notice">
      AI-assisted research; not investment advice. 本文件是证据审计与信号草稿，不构成投资建议；强结论必须由至少三个独立可信来源或高权威来源链条支持。
    </section>
    """


def _validation_section(draft: ResearchDraft) -> str:
    report = draft.validation_report
    if not report:
        return """
        <section class="section">
          <div class="validation-box fail">
            <p class="eyebrow">Validation</p>
            <h2>未生成自动验收报告</h2>
            <p>这份文件不能视作最终交付物。</p>
          </div>
        </section>
        """
    rows = []
    for check in report.checks:
        icon = "✅" if check.status == "pass" else "⚠️" if check.status == "warn" else "❌"
        rows.append(
            f"""
            <details class="check-row {check.status}" {'open' if check.status == 'fail' else ''}>
              <summary>{icon} {_e(check.category)} / {_e(check.check_id)}：{_e(check.requirement)}</summary>
              <p><strong>当前：</strong>{_e(check.observed)}</p>
              <p><strong>要求：</strong>{_e(check.required)}</p>
              <p><strong>修复：</strong>{_e(check.remediation or '已满足')}</p>
            </details>
            """
        )
    return f"""
    <section class="section">
      <div class="validation-box {'pass' if report.status == 'PASS_FINAL_DELIVERABLE' else 'fail'}">
        <p class="eyebrow">Automatic Acceptance Checklist</p>
        <h2>{'达到最终交付标准' if report.status == 'PASS_FINAL_DELIVERABLE' else '未达到最终交付标准'}</h2>
        <p>{_e(draft.report_label)}</p>
        <div class="validation-metrics">
          <span>通过 {report.passed}</span>
          <span>失败 {report.failed}</span>
          <span>警告 {report.warning}</span>
        </div>
        <div class="check-list">{''.join(rows)}</div>
      </div>
    </section>
    """


def _model_runs_section(draft: ResearchDraft) -> str:
    if not draft.model_runs:
        rows = "<tr><td colspan='7'>没有模型调用记录；本报告不能证明调用过大模型。</td></tr>"
    else:
        rows = "".join(
            f"""
            <tr>
              <td>{_e(run.provider)}</td>
              <td>{_e(run.model)}</td>
              <td>{_e(run.status)}</td>
              <td>{run.duration_seconds:.1f}s</td>
              <td>{_e(run.purpose)}</td>
              <td>{_e(run.output_summary)}</td>
              <td>{_e(run.error)}</td>
            </tr>
            """
            for run in draft.model_runs
        )
    return f"""
    <section class="section">
      <div class="table-wrap">
        <table class="model-table">
          <thead><tr><th>Provider</th><th>Model</th><th>Status</th><th>Duration</th><th>Purpose</th><th>Output</th><th>Error</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    </section>
    """


def _metric_tile(value: str, number: str, note: str) -> str:
    return f"""
    <div class="metric">
      <span>{_e(value)}</span>
      <strong>{_e(number)}</strong>
      <p>{_e(note)}</p>
    </div>
    """


def _financial_charts_section(draft: ResearchDraft, compact: bool) -> str:
    if not draft.financial_charts:
        return """
        <section class="section">
          <div class="empty-state">
            <p class="eyebrow">财务图表</p>
            <h2>暂未生成真实财务图表</h2>
            <p>当前公司或可比组缺少可直接抓取的 SEC XBRL / Wind fundamentals 数据。下一阶段会继续补公司 IR 表格、港股/A股公告和非上市公司外部数据。</p>
          </div>
        </section>
        """
    chart_items = list(enumerate(draft.financial_charts))
    charts = chart_items[:3] if compact else chart_items
    return f"""
    <section class="section">
      <div class="section-title">
        <div>
          <p class="eyebrow">财务图表</p>
          <h2>真实财务数据图表</h2>
          <p>这些图表不是占位符：数据来自 SEC XBRL companyfacts 或万得 Wind fundamentals，并保留原始 filing accession / Wind 字段来源。</p>
        </div>
      </div>
      <div class="chart-grid {'compact' if compact else ''}">
        {''.join(_chart_card(chart, index) for index, chart in charts)}
      </div>
    </section>
    """


def _objective_anomalies_section(draft: ResearchDraft, compact: bool) -> str:
    anomalies = draft.objective_anomalies[:8] if compact else draft.objective_anomalies
    if not anomalies:
        return """
        <section class="section">
          <div class="empty-state">
            <p class="eyebrow">客观异常扫描</p>
            <h2>暂未形成客观异常清单</h2>
            <p>第一阶段需要先完成资料/数据收集、横纵向对比和异常扫描。</p>
          </div>
        </section>
        """
    positive = [item for item in anomalies if item.polarity == POSITIVE]
    risk = [item for item in anomalies if item.polarity == RISK]
    return f"""
    <section class="section">
      <div class="section-title">
        <div>
          <p class="eyebrow">客观异常扫描</p>
          <h2>第一阶段客观异常清单</h2>
          <p>这些条目只来自真实财务数据、已读取正文主题命中、横向/纵向对比；资料缺口只放在审计附录，不进入积极/风险信号。</p>
        </div>
      </div>
      <div class="anomaly-columns">
        <div>
          <h3>积极信号</h3>
          {''.join(_anomaly_card(item) for item in positive) or '<p class="muted">暂无积极异常。</p>'}
        </div>
        <div>
          <h3>风险信号</h3>
          {''.join(_anomaly_card(item) for item in risk) or '<p class="muted">暂无风险异常。</p>'}
        </div>
      </div>
    </section>
    """


def _anomaly_card(anomaly: Any) -> str:
    selected = "已勾选深挖" if anomaly.selected_for_deep_dive else "未勾选"
    return f"""
    <article class="anomaly-card {'selected' if anomaly.selected_for_deep_dive else ''}">
      <span>{_e(anomaly.category)} · {_e(selected)}</span>
      <h4>{_e(anomaly.title)}</h4>
      <p>{_e(anomaly.observation)}</p>
      <p class="muted">对比依据：{_e(anomaly.comparison_basis)}</p>
      {f'<strong>{_e(anomaly.magnitude)}</strong>' if anomaly.magnitude else ''}
    </article>
    """


def _chart_card(chart: FinancialChart, chart_index: int) -> str:
    chart_html = _line_chart(chart, chart_index) if chart.chart_type == "line" else _bar_chart(chart, chart_index)
    return f"""
    <article class="chart-card">
      <div class="chart-head">
        <div>
          <h3>{_e(chart.title)}</h3>
          <p>{_e(chart.subtitle)}</p>
        </div>
        <span>{_e(chart.y_axis)}</span>
      </div>
      {chart_html}
      <p class="chart-insight">{_e(chart.insight)}</p>
      <p class="source-note">{_e(chart.source_note)}</p>
    </article>
    """


def _bar_chart(chart: FinancialChart, chart_index: int) -> str:
    points = chart.points
    if not points:
        return "<div class='empty-chart'>No data</div>"
    values = [max(0.0, point.value) for point in points]
    max_value = max(values) or 1
    bars = []
    for point_index, point in enumerate(points):
        height = max(6, min(100, abs(point.value) / max_value * 100))
        bars.append(
            f"""
            <button class="bar-item" type="button" onclick="showFinancialPoint({chart_index},{point_index})">
              <span class="bar-value">{_e(point.display_value)}</span>
              <i style="height:{height}%"></i>
              <em>{_e(_short_period(point))}</em>
              <small>{_e(point_display_name(point))}</small>
            </button>
            """
        )
    return f"<div class='bar-chart'>{''.join(bars)}</div>"


def _line_chart(chart: FinancialChart, chart_index: int) -> str:
    points = chart.points
    if not points:
        return "<div class='empty-chart'>No data</div>"
    values = [point.value for point in points]
    min_value, max_value = min(values), max(values)
    span = max(max_value - min_value, 1)
    width, height = 720, 260
    left, right, top, bottom = 48, 24, 24, 48
    plot_width = width - left - right
    plot_height = height - top - bottom
    coords = []
    for index, point in enumerate(points):
        x = left + (plot_width * index / max(1, len(points) - 1))
        y = top + plot_height - ((point.value - min_value) / span * plot_height)
        coords.append((x, y, point))
    polyline = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in coords)
    dots = []
    labels = []
    for point_index, (x, y, point) in enumerate(coords):
        dots.append(
            f"""
            <button class="line-dot" style="left:{x / width * 100:.2f}%;top:{y / height * 100:.2f}%" onclick="showFinancialPoint({chart_index},{point_index})">
              <span>{_e(point.display_value)}</span>
            </button>
            """
        )
        labels.append(f"<span style='left:{x / width * 100:.2f}%'>{_e(_short_period(point))}</span>")
    return f"""
    <div class="line-chart">
      <svg viewBox="0 0 {width} {height}" role="img" aria-label="{_e(chart.title)}">
        <line x1="{left}" y1="{height-bottom}" x2="{width-right}" y2="{height-bottom}" class="axis"></line>
        <line x1="{left}" y1="{top}" x2="{left}" y2="{height-bottom}" class="axis"></line>
        <polyline points="{polyline}" class="trend"></polyline>
      </svg>
      {''.join(dots)}
      <div class="x-labels">{''.join(labels)}</div>
    </div>
    """


def _signal_card(signal: ResearchSignal, evidence: list[EvidenceItem], compact: bool, anomaly_lookup: dict[str, str] | None = None) -> str:
    evidence_ids = [idx for idx in signal.evidence_ids if 0 <= idx < len(evidence)]
    button = f"onclick='showEvidence({json.dumps(evidence_ids)})'"
    status_label = {
        "evidence_backed": "证据较强",
        "needs_validation": "待验证",
        "data_gap": "数据缺口",
    }.get(signal.status, signal.status)
    score_items = signal.score.to_dict()
    bars = "".join(
        f"<div class='score-row'><span>{_e(_score_label(key))}</span><b style='width:{min(100, value * 20)}%'></b><em>{value}</em></div>"
        for key, value in score_items.items()
        if key != "total"
    )
    reasoning = "" if compact else f"""
      <details>
        <summary>展开 AI 推理链草稿</summary>
        <ol>{''.join(f'<li>{_e(step)}</li>' for step in signal.reasoning_chain)}</ol>
      </details>
    """
    actions = "" if compact else f"<ul class='mini-list'>{''.join(f'<li>{_e(action)}</li>' for action in signal.next_validation_actions)}</ul>"
    return f"""
    <article class="signal-card {signal.status}" {button}>
      <div class="signal-top">
        <span class="badge">{_e(signal.signal_type)}</span>
        <span class="status">{_e(status_label)}</span>
      </div>
      <h3>{_e(signal.title)}</h3>
      {_signal_anomaly_refs(signal, anomaly_lookup)}
      <p>{_e(signal.conclusion)}</p>
      <div class="chart-hint">
        <strong>{_e(signal.chart_hint)}</strong>
        <span>{_e(signal.chart_reason)}</span>
      </div>
      <div class="scores">{bars}</div>
      <p class="reasoning">{_e(signal.reasoning_summary)}</p>
      {reasoning}
      {actions}
      <button type="button">查看绑定证据（{len(evidence_ids)}）</button>
    </article>
    """


def _anomaly_title_lookup(draft: ResearchDraft) -> dict[str, str]:
    return {anomaly.anomaly_id: anomaly.title for anomaly in draft.objective_anomalies}


def _signal_anomaly_refs(signal: ResearchSignal, anomaly_lookup: dict[str, str] | None = None) -> str:
    if not signal.anomaly_ids:
        return ""
    labels = "".join(f"<span>{_e((anomaly_lookup or {}).get(item, item))}</span>" for item in signal.anomaly_ids[:4])
    return f"<div class='pill-row anomaly-ref'><strong>对应异常：</strong>{labels}</div>"


def _groups_html(draft: ResearchDraft) -> str:
    cards = []
    for group in draft.comparable_groups:
        companies = "、".join(company_display_name(company) for company in group.companies)
        cards.append(
            f"""
            <article class="group-card">
              <h3>{_e(group.title)}</h3>
              <p>{_e(group.purpose)}</p>
              <small>{_e(group.selection_logic)}</small>
              <div class="pill-row">{''.join(f'<span>{_e(company_display_name(company))}</span>' for company in group.companies)}</div>
              <p class="muted">{_e(companies)}</p>
            </article>
            """
        )
    return f"<div class='group-list'>{''.join(cards)}</div>"


def _audit_html(draft: ResearchDraft) -> str:
    return "<div class='audit-list'>" + "".join(
        f"""
        <article class="audit {finding.status}">
          <strong>{_e(finding.topic)}</strong>
          <span>{_e(finding.status)}</span>
          <p>{_e(finding.finding)}</p>
          <button type="button" onclick='showEvidence({json.dumps(finding.related_evidence_ids)})'>相关证据</button>
        </article>
        """
        for finding in draft.audit_findings
    ) + "</div>"


def _coverage_matrix(draft: ResearchDraft) -> str:
    types = ["annual", "quarterly", "transcript", "expert_memo", "presentation", "external_signal", "web"]
    rows = []
    company_names = [draft.target, *[company for group in draft.comparable_groups for company in group.companies]]
    seen: set[str] = set()
    for company in company_names:
        key = company.ticker.upper()
        if key in seen:
            continue
        seen.add(key)
        cells = []
        for evidence_type in types:
            ids = [idx for idx, item in enumerate(draft.evidence) if item.ticker.upper() == key and item.evidence_type == evidence_type]
            intensity = min(4, len(ids))
            cells.append(f"<td><button class='heat h{intensity}' onclick='showEvidence({json.dumps(ids[:12])})'>{len(ids)}</button></td>")
        rows.append(f"<tr><th>{_e(company_display_name(company))}</th>{''.join(cells)}</tr>")
    header = "".join(f"<th>{_e(_type_label(item))}</th>" for item in types)
    return f"<div class='table-wrap'><table class='matrix'><thead><tr><th>公司</th>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _evidence_table(evidence: list[EvidenceItem], company_lookup: dict[str, str] | None = None) -> str:
    rows = []
    for idx, item in enumerate(evidence[:80]):
        rows.append(
            f"""
            <tr onclick='showEvidence([{idx}])'>
              <td>{idx + 1}</td>
              <td>{_e(item.company or resolve_display_name(item.ticker, company_lookup))}</td>
              <td>{_e(_type_label(item.evidence_type))}</td>
              <td>{_e(item.confidence_tier)}</td>
              <td>{_e(item.source)}</td>
              <td>{_e(replace_identifier_with_name(item.title, item.ticker, item.company or resolve_display_name(item.ticker, company_lookup)))}</td>
            </tr>
            """
        )
    return f"<div class='table-wrap'><table class='evidence-table'><thead><tr><th>#</th><th>公司</th><th>类型</th><th>置信层</th><th>来源</th><th>标题</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _reference_appendix(draft: ResearchDraft) -> str:
    rows = []
    for index, item in enumerate(_deduped_reference_items(draft), start=1):
        link_html = f'<a href="{_e(item["link"])}" target="_blank" rel="noreferrer">一键打开 ↗</a>' if item["link"] else '<span class="muted">暂无可打开链接</span>'
        rows.append(
            f"""
            <tr>
              <td>{index}</td>
              <td>{_e(item["company"])}</td>
              <td>{_e(_type_label(item["type"]))}</td>
              <td>{_e(item["file_name"])}</td>
              <td>{_e(item["source"])}</td>
              <td>{link_html}</td>
            </tr>
            """
        )
    if not rows:
        body = "<p class='muted'>本次研究尚未记录可打开的参考资料。</p>"
    else:
        body = f"""
        <div class="table-wrap reference-wrap">
          <table class="reference-table">
            <thead><tr><th>#</th><th>公司</th><th>类型</th><th>文件名 / 资料名</th><th>来源</th><th>链接</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        """
    return f"""
    <section class="section reference-appendix">
      <div class="section-title">
        <div>
          <p class="eyebrow">References</p>
          <h2>本次研究参考资料附录</h2>
          <p>这里汇总本次研究查找、阅读或纳入证据审计的标的公司与可比公司资料；点击链接可一键打开原始网页、PDF 或本地截图/文件。</p>
        </div>
      </div>
      {body}
    </section>
    """


def _deduped_reference_items(draft_or_evidence: ResearchDraft | list[EvidenceItem]) -> list[dict[str, str]]:
    if isinstance(draft_or_evidence, ResearchDraft):
        return _deduped_reference_records(draft_or_evidence)
    return _deduped_evidence_reference_records(draft_or_evidence, {})


def _deduped_reference_records(draft: ResearchDraft) -> list[dict[str, str]]:
    company_lookup = _draft_display_lookup(draft)
    records = _deduped_evidence_reference_records(draft.evidence, company_lookup)
    records.extend(_financial_reference_records(draft.financial_charts, company_lookup))
    return _dedupe_reference_records(records)


def _deduped_evidence_reference_records(evidence: list[EvidenceItem], company_lookup: dict[str, str]) -> list[dict[str, str]]:
    seen: set[str] = set()
    records: list[dict[str, str]] = []
    for item in evidence:
        key = (item.url or item.screenshot_path or f"{item.ticker}:{item.title}:{item.evidence_type}").strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        display_company = item.company or resolve_display_name(item.ticker, company_lookup)
        display_title = replace_identifier_with_name(item.title or item.url, item.ticker, display_company)
        records.append(
            {
                "company": display_company,
                "type": item.evidence_type,
                "file_name": _reference_file_name(item, display_title),
                "source": item.source,
                "link": _reference_link(item),
                "period": item.period,
                "title": display_title,
            }
        )
    return sorted(records, key=_reference_sort_key)


def _financial_reference_records(charts: list[FinancialChart], company_lookup: dict[str, str]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for chart in charts:
        for point in chart.points:
            display_company = point.company or resolve_display_name(point.ticker, company_lookup)
            for source in point.sources:
                title = source.title or source.form or chart.title or point.metric_label
                concept = f" · {source.concept}" if source.concept else ""
                period = point.period or source.filed
                file_name = f"{display_company} {point.metric_label} {period}{concept}".strip()
                records.append(
                    {
                        "company": display_company,
                        "type": "financial_datapoint",
                        "file_name": file_name or title,
                        "source": title,
                        "link": source.url,
                        "period": period,
                        "title": chart.title,
                    }
                )
    return records


def _dedupe_reference_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in records:
        key = (item.get("link") or f'{item.get("company")}:{item.get("type")}:{item.get("file_name")}').strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return sorted(deduped, key=_reference_sort_key)


def _reference_sort_key(item: dict[str, str]) -> tuple[str, str, str, str]:
    return (item.get("company") or "", item.get("type") or "", item.get("period") or "", item.get("file_name") or item.get("title") or "")


def _reference_file_name(item: EvidenceItem, display_title: str) -> str:
    if item.screenshot_path:
        return Path(item.screenshot_path).name
    if item.url:
        path_name = Path(item.url.split("?", 1)[0].rstrip("/")).name
        if path_name and "." in path_name:
            return path_name
    return display_title or item.title or item.url or "未命名资料"


def _reference_link(item: EvidenceItem) -> str:
    if item.url:
        return item.url
    if item.screenshot_path:
        return _local_path_to_uri(item.screenshot_path)
    return ""


def _evidence_drawer(draft: ResearchDraft) -> str:
    return """
    <aside id="evidenceDrawer" class="drawer">
      <div class="drawer-head">
        <div>
          <p class="eyebrow">Traceability</p>
          <h2>原始出处</h2>
        </div>
        <button type="button" onclick="closeEvidence()">关闭</button>
      </div>
      <div id="drawerBody" class="drawer-body"></div>
    </aside>
    """


def _score_label(key: str) -> str:
    return {
        "importance": "重要性",
        "evidence_strength": "证据强度",
        "novelty": "新颖性",
        "investment_relevance": "投资相关性",
        "time_sensitivity": "时间敏感性",
        "actionability": "可行动性",
    }.get(key, key)


def _type_label(value: str) -> str:
    return {
        "annual": "年报",
        "quarterly": "季报",
        "transcript": "业绩会纪要",
        "expert_memo": "专家/渠道纪要",
        "presentation": "演示材料",
        "external_signal": "外部信号",
        "official_ir": "官方 IR",
        "official_filings": "官方公告",
        "financial_datapoint": "财务数据点",
        "private_company": "私有公司线索",
        "web": "网页",
    }.get(value, value or "未知")


def _short_period(point: FinancialDataPoint) -> str:
    period = point.period or point.end_date
    return period.replace("FY", "").replace(" ", "\n")


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _style() -> str:
    return """
    :root{--bg:#f6f8fb;--card:#fff;--ink:#102033;--muted:#65748b;--line:#dfe7f2;--blue:#275efe;--cyan:#0e9fbc;--green:#11845b;--orange:#b45309;--red:#b42318;--shadow:0 18px 45px rgba(16,32,51,.08)}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;line-height:1.55}
    .memo-shell,.dashboard-shell{max-width:1180px;margin:0 auto;padding:28px 18px 64px}.hero{display:grid;grid-template-columns:1fr 280px;gap:24px;align-items:stretch;margin-top:10px}
    .hero h1{font-size:clamp(30px,5vw,56px);line-height:1.05;margin:8px 0 14px;letter-spacing:-.04em}.hero-subtitle{font-size:18px;color:var(--muted);max-width:760px}
    .eyebrow{margin:0;color:var(--blue);font-size:12px;text-transform:uppercase;letter-spacing:.16em;font-weight:800}.hero-card,.metric,.signal-card,.group-card,.audit,.notice,.chart-card,.empty-state,.validation-box{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:24px;box-shadow:var(--shadow)}
    .hero-card{padding:22px;display:grid;gap:5px}.hero-card span{font-size:12px;color:var(--muted)}.hero-card strong{font-size:18px;margin-bottom:10px}.notice{margin:24px 0;padding:14px 18px;color:#42526b}
    .section{margin-top:30px}.section-title{display:flex;justify-content:space-between;align-items:end;gap:20px}.section h2,.section-title h2{font-size:26px;margin:4px 0 14px}.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:24px 0}
    .metric{padding:20px}.metric span{color:var(--muted)}.metric strong{display:block;font-size:42px;line-height:1;margin:10px 0}.metric p{margin:0;color:var(--muted)}
    .validation-box{padding:20px;border-left:8px solid var(--red)}.validation-box.pass{border-left-color:var(--green)}.validation-box h2{margin:6px 0}.validation-metrics{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}.validation-metrics span{background:#f2f6fb;border-radius:999px;padding:7px 11px;font-weight:800}.check-list{display:grid;gap:8px}.check-row{background:#f8fafc;border-radius:14px;padding:10px 12px;border:1px solid var(--line)}.check-row.fail{border-color:#fecaca;background:#fff7f7}.check-row.pass{border-color:#bbf7d0;background:#f4fff8}.check-row p{margin:6px 0;color:#42526b}
    .signal-list{display:grid;gap:16px}.signal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.signal-card{padding:20px;cursor:pointer;transition:.18s transform,.18s box-shadow}.signal-card:hover{transform:translateY(-2px);box-shadow:0 22px 55px rgba(16,32,51,.13)}
    .signal-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.badge,.status,.pill-row span{display:inline-flex;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:700;background:#edf3ff;color:#2442a8}.status{background:#eefaf5;color:var(--green)}.needs_validation .status{background:#fff7ed;color:var(--orange)}.data_gap .status{background:#fff1f0;color:var(--red)}
    .signal-card h3{font-size:20px;margin:14px 0 8px}.signal-card p{color:#42526b}.chart-hint{border-left:4px solid var(--cyan);padding:10px 12px;background:#f0fbff;border-radius:12px;margin:14px 0}.chart-hint strong{display:block}.chart-hint span{color:var(--muted);font-size:13px}
    .anomaly-ref{align-items:center;margin:8px 0}.anomaly-ref strong{font-size:12px;color:var(--muted)}.anomaly-ref span{max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    .chart-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.chart-grid.compact{grid-template-columns:1fr}.chart-card{padding:18px;overflow:hidden}.chart-head{display:flex;justify-content:space-between;gap:16px;align-items:start}.chart-head h3{margin:0 0 6px;font-size:20px}.chart-head p,.source-note{color:var(--muted);font-size:13px;margin:0}.chart-head span{white-space:nowrap;background:#eef6ff;color:#2442a8;border-radius:999px;padding:6px 10px;font-size:12px;font-weight:800}.chart-insight{font-weight:800;color:#203047}.empty-state{padding:22px}.empty-chart{height:220px;display:grid;place-items:center;color:var(--muted)}
    .anomaly-columns{display:grid;grid-template-columns:1fr 1fr;gap:18px}.anomaly-card{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0}.anomaly-card.selected{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.10)}.anomaly-card span{font-size:12px;color:var(--muted);font-weight:800}.anomaly-card h4{margin:8px 0}.anomaly-card p{margin:8px 0}.anomaly-card strong{display:inline-block;background:#eef2ff;color:#1d4ed8;border-radius:999px;padding:5px 9px}
    .bar-chart{height:285px;display:flex;gap:10px;align-items:end;padding:20px 4px 8px;border-bottom:1px solid var(--line);overflow-x:auto}.bar-item{position:relative;min-width:72px;flex:1;height:230px;border:0;background:transparent;display:flex;flex-direction:column;align-items:center;justify-content:end;gap:6px;cursor:pointer;color:var(--ink)}.bar-item i{width:70%;border-radius:12px 12px 4px 4px;background:linear-gradient(180deg,var(--blue),var(--cyan));display:block;box-shadow:0 10px 22px rgba(39,94,254,.2);transition:.18s transform}.bar-item:hover i{transform:translateY(-4px)}.bar-value{font-size:12px;font-weight:800;color:#203047}.bar-item em{font-style:normal;font-size:11px;color:var(--muted);white-space:pre-line}.bar-item small{font-size:11px;color:var(--blue);font-weight:800}
    .line-chart{height:310px;position:relative;margin-top:8px}.line-chart svg{width:100%;height:260px;display:block}.axis{stroke:#d7e1ee;stroke-width:1}.trend{fill:none;stroke:var(--blue);stroke-width:4;stroke-linecap:round;stroke-linejoin:round}.line-dot{position:absolute;transform:translate(-50%,-50%);width:18px;height:18px;border-radius:999px;border:3px solid #fff;background:var(--blue);box-shadow:0 4px 12px rgba(39,94,254,.35);cursor:pointer}.line-dot span{position:absolute;left:50%;bottom:18px;transform:translateX(-50%);white-space:nowrap;background:#102033;color:#fff;border-radius:9px;padding:4px 7px;font-size:11px;opacity:0;pointer-events:none}.line-dot:hover span{opacity:1}.x-labels{position:absolute;left:0;right:0;bottom:8px;height:36px}.x-labels span{position:absolute;transform:translateX(-50%);font-size:11px;color:var(--muted);white-space:pre-line;text-align:center}
    .scores{display:grid;gap:8px;margin:14px 0}.score-row{display:grid;grid-template-columns:86px 1fr 24px;gap:8px;align-items:center;font-size:12px;color:var(--muted)}.score-row b{height:8px;border-radius:999px;background:linear-gradient(90deg,var(--blue),var(--cyan));display:block}.score-row em{font-style:normal;text-align:right;color:var(--ink)}
    .signal-card button,.audit button,.drawer-head button{border:0;background:var(--ink);color:#fff;border-radius:12px;padding:9px 12px;font-weight:700;cursor:pointer}.mini-list,.next-list{color:#42526b}.two-col{display:grid;grid-template-columns:1.1fr .9fr;gap:22px}
    .group-list,.audit-list{display:grid;gap:12px}.group-card,.audit{padding:16px}.group-card h3,.audit strong{margin:0 0 8px;display:block}.group-card p,.group-card small,.audit p{color:var(--muted)}.pill-row{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}
    .audit{position:relative}.audit span{position:absolute;right:16px;top:16px;font-size:12px;color:var(--muted)}.table-wrap{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow)}table{border-collapse:collapse;width:100%;min-width:760px}th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}th{background:#f2f6fb;color:#42526b}tr{transition:.15s background}tbody tr:hover{background:#f8fbff}
    .reference-appendix .section-title p:not(.eyebrow){color:var(--muted);margin-top:0}.reference-table td:nth-child(4){font-weight:700;color:#203047}.reference-table a{color:var(--blue);font-weight:800;text-decoration:none;white-space:nowrap}.reference-wrap{margin-top:14px}
    .heat{min-width:42px;border:0;border-radius:10px;padding:8px 10px;cursor:pointer;background:#f1f5f9;color:#334155}.h1{background:#e0f2fe}.h2{background:#bae6fd}.h3{background:#7dd3fc}.h4{background:#38bdf8;color:#072638}
    .drawer{position:fixed;right:0;top:0;width:min(520px,94vw);height:100vh;background:#fff;box-shadow:-20px 0 60px rgba(16,32,51,.18);transform:translateX(105%);transition:.22s transform;z-index:10;padding:20px;overflow:auto}.drawer.open{transform:translateX(0)}.drawer-head{display:flex;justify-content:space-between;gap:14px;align-items:center;border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:14px}.drawer-head h2{margin:0}.drawer-card{border:1px solid var(--line);border-radius:18px;padding:14px;margin-bottom:12px;background:#fbfdff}.drawer-card h3{font-size:17px;margin:6px 0}.drawer-meta,.muted{color:var(--muted);font-size:13px}.drawer-card a{color:var(--blue);font-weight:800;text-decoration:none}.source-row{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.source-row p{margin:4px 0;color:var(--muted);font-size:13px}.source-shot{margin:12px 0;border:1px solid var(--line);border-radius:14px;overflow:hidden;background:#f8fafc}.source-shot img{display:block;width:100%;height:auto}.source-shot figcaption{padding:8px 10px;color:var(--muted);font-size:12px}blockquote{margin:10px 0;padding:10px 12px;background:#f6f8fb;border-left:4px solid var(--blue);border-radius:10px}
    details{background:#f8fafc;border-radius:14px;padding:10px 12px;margin:12px 0}summary{cursor:pointer;font-weight:800}@media(max-width:820px){.hero,.two-col,.grid-3,.signal-grid,.chart-grid,.anomaly-columns{grid-template-columns:1fr}.section-title{display:block}.memo-shell,.dashboard-shell{padding:18px 12px 50px}.hero h1{font-size:34px}.drawer{width:100vw}.bar-item{min-width:64px}}
    """
