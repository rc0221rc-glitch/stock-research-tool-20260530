from __future__ import annotations

import html
import json
from pathlib import Path

from .research_models import EvidenceItem, ResearchDraft, ResearchSignal
from .utils import clean_filename


OUTPUT_DIR = Path("downloads") / "research_outputs"


def save_memo_html(draft: ResearchDraft, output_dir: str | Path = OUTPUT_DIR) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    filename = clean_filename(f"{draft.target.ticker or draft.target.name}_investment_memo_{draft.generated_at[:10]}", "investment_memo")
    path = output / f"{filename}.html"
    path.write_text(render_memo_html(draft), encoding="utf-8")
    return path


def save_dashboard_html(draft: ResearchDraft, output_dir: str | Path = OUTPUT_DIR) -> Path:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    filename = clean_filename(f"{draft.target.ticker or draft.target.name}_research_dashboard_{draft.generated_at[:10]}", "research_dashboard")
    path = output / f"{filename}.html"
    path.write_text(render_dashboard_html(draft), encoding="utf-8")
    return path


def render_memo_html(draft: ResearchDraft) -> str:
    content = f"""
    <main class="memo-shell">
      {_hero(draft, "投资备忘录草稿", "3–5 屏结论先行版本，正式发布前需要完成 AI 深度分析与人工证据确认。")}
      <section class="section">
        <div class="section-title">
          <p class="eyebrow">Alpha Signals</p>
          <h2>系统优先建议深挖的核心信号</h2>
        </div>
        <div class="signal-list">
          {''.join(_signal_card(signal, draft.evidence, compact=True) for signal in draft.signals)}
        </div>
      </section>
      <section class="section two-col">
        <div>
          <p class="eyebrow">Comparable Groups</p>
          <h2>精选可比与交叉验证组</h2>
          {_groups_html(draft)}
        </div>
        <div>
          <p class="eyebrow">Evidence Audit</p>
          <h2>证据审计摘要</h2>
          {_audit_html(draft)}
        </div>
      </section>
      <section class="section">
        <p class="eyebrow">Next Fetch Plan</p>
        <h2>系统下一步自动验证计划</h2>
        <ol class="next-list">{''.join(f'<li>{_e(item)}</li>' for item in draft.next_fetch_plan)}</ol>
      </section>
      {_evidence_drawer(draft)}
    </main>
    """
    return _document("AI 行业研究投资备忘录", content, draft)


def render_dashboard_html(draft: ResearchDraft) -> str:
    content = f"""
    <main class="dashboard-shell">
      {_hero(draft, "交互式研究看板草稿", "信号卡片、证据矩阵、可比组与审计附录版本。点击信号或证据可打开右侧来源抽屉。")}
      <section class="grid-3">
        {_metric_tile("候选证据", str(len(draft.evidence)), "所有图表与文字结论必须绑定来源")}
        {_metric_tile("核心信号草稿", str(len(draft.signals)), "含亮点、风险和待验证假设")}
        {_metric_tile("可比组", str(len(draft.comparable_groups)), "核心业务 + 上下游 + 替代路线")}
      </section>
      <section class="section">
        <div class="section-title">
          <p class="eyebrow">Coverage Matrix</p>
          <h2>产业链证据覆盖矩阵</h2>
          <p>矩阵用于先看“哪里证据够、哪里需要补抓”，不是最终投资结论。</p>
        </div>
        {_coverage_matrix(draft)}
      </section>
      <section class="section">
        <div class="section-title">
          <p class="eyebrow">Signal Cards</p>
          <h2>Alpha 信号与评分</h2>
        </div>
        <div class="signal-grid">
          {''.join(_signal_card(signal, draft.evidence, compact=False) for signal in draft.signals)}
        </div>
      </section>
      <section class="section two-col">
        <div>
          <p class="eyebrow">Comparable Groups</p>
          <h2>可比公司逻辑</h2>
          {_groups_html(draft)}
        </div>
        <div>
          <p class="eyebrow">Audit Appendix</p>
          <h2>证据审计附录</h2>
          {_audit_html(draft)}
        </div>
      </section>
      <section class="section">
        <p class="eyebrow">Evidence Table</p>
        <h2>候选证据清单</h2>
        {_evidence_table(draft.evidence)}
      </section>
      {_evidence_drawer(draft)}
    </main>
    """
    return _document("AI 行业研究交互看板", content, draft)


def _document(title: str, content: str, draft: ResearchDraft) -> str:
    evidence_json = json.dumps([item.to_dict() for item in draft.evidence], ensure_ascii=False)
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
    function showEvidence(ids) {{
      const drawer = document.getElementById('evidenceDrawer');
      const body = document.getElementById('drawerBody');
      const list = (ids || []).map(id => evidence[id]).filter(Boolean);
      body.innerHTML = list.length ? list.map((item, offset) => `
        <article class="drawer-card">
          <div class="drawer-meta">${{item.ticker || ''}} · ${{item.evidence_type || ''}} · ${{item.confidence_tier || ''}}</div>
          <h3>${{escapeHtml(item.title || item.url || 'Untitled')}}</h3>
          <p>${{escapeHtml(item.confidence_reason || '')}}</p>
          ${{item.quote ? `<blockquote>${{escapeHtml(item.quote)}}</blockquote>` : ''}}
          ${{item.page ? `<p>页码：${{escapeHtml(item.page)}}</p>` : ''}}
          ${{item.cell_reference ? `<p>表格单元格：${{escapeHtml(item.cell_reference)}}</p>` : ''}}
          ${{item.screenshot_path ? `<p>截图：${{escapeHtml(item.screenshot_path)}}</p>` : '<p class="muted">截图将在证据下载与审计步骤生成后显示。</p>'}}
          <a href="${{item.url}}" target="_blank" rel="noreferrer">打开原始链接 ↗</a>
        </article>
      `).join('') : '<p class="muted">这个信号暂未绑定证据，不能升级为正式结论。</p>';
      drawer.classList.add('open');
    }}
    function closeEvidence() {{
      document.getElementById('evidenceDrawer').classList.remove('open');
    }}
    function escapeHtml(value) {{
      return String(value || '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[char]));
    }}
  </script>
</body>
</html>"""


def _hero(draft: ResearchDraft, label: str, subtitle: str) -> str:
    return f"""
    <section class="hero">
      <div>
        <p class="eyebrow">{_e(label)}</p>
        <h1>{_e(draft.target.name)} · AI 产业链研究草稿</h1>
        <p class="hero-subtitle">{_e(subtitle)}</p>
      </div>
      <div class="hero-card">
        <span>目标公司</span><strong>{_e(draft.target.ticker or draft.target.name)}</strong>
        <span>观察窗口</span><strong>最近 {draft.quarter_count} 个季度</strong>
        <span>生成时间</span><strong>{_e(draft.generated_at)}</strong>
      </div>
    </section>
    <section class="notice">
      AI-assisted research; not investment advice. 本文件是证据审计与信号草稿，不构成投资建议；强结论必须由至少三个独立可信来源或高权威来源链条支持。
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


def _signal_card(signal: ResearchSignal, evidence: list[EvidenceItem], compact: bool) -> str:
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


def _groups_html(draft: ResearchDraft) -> str:
    cards = []
    for group in draft.comparable_groups:
        companies = "、".join(company.ticker for company in group.companies)
        cards.append(
            f"""
            <article class="group-card">
              <h3>{_e(group.title)}</h3>
              <p>{_e(group.purpose)}</p>
              <small>{_e(group.selection_logic)}</small>
              <div class="pill-row">{''.join(f'<span>{_e(company.ticker)}</span>' for company in group.companies)}</div>
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
    types = ["annual", "quarterly", "transcript", "presentation", "external_signal", "web"]
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
        rows.append(f"<tr><th>{_e(company.ticker)}</th>{''.join(cells)}</tr>")
    header = "".join(f"<th>{_e(_type_label(item))}</th>" for item in types)
    return f"<div class='table-wrap'><table class='matrix'><thead><tr><th>公司</th>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


def _evidence_table(evidence: list[EvidenceItem]) -> str:
    rows = []
    for idx, item in enumerate(evidence[:80]):
        rows.append(
            f"""
            <tr onclick='showEvidence([{idx}])'>
              <td>{idx + 1}</td>
              <td>{_e(item.ticker)}</td>
              <td>{_e(_type_label(item.evidence_type))}</td>
              <td>{_e(item.confidence_tier)}</td>
              <td>{_e(item.source)}</td>
              <td>{_e(item.title)}</td>
            </tr>
            """
        )
    return f"<div class='table-wrap'><table class='evidence-table'><thead><tr><th>#</th><th>公司</th><th>类型</th><th>置信层</th><th>来源</th><th>标题</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"


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
        "presentation": "演示材料",
        "external_signal": "外部信号",
        "web": "网页",
    }.get(value, value or "未知")


def _e(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def _style() -> str:
    return """
    :root{--bg:#f6f8fb;--card:#fff;--ink:#102033;--muted:#65748b;--line:#dfe7f2;--blue:#275efe;--cyan:#0e9fbc;--green:#11845b;--orange:#b45309;--red:#b42318;--shadow:0 18px 45px rgba(16,32,51,.08)}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;line-height:1.55}
    .memo-shell,.dashboard-shell{max-width:1180px;margin:0 auto;padding:28px 18px 64px}.hero{display:grid;grid-template-columns:1fr 280px;gap:24px;align-items:stretch;margin-top:10px}
    .hero h1{font-size:clamp(30px,5vw,56px);line-height:1.05;margin:8px 0 14px;letter-spacing:-.04em}.hero-subtitle{font-size:18px;color:var(--muted);max-width:760px}
    .eyebrow{margin:0;color:var(--blue);font-size:12px;text-transform:uppercase;letter-spacing:.16em;font-weight:800}.hero-card,.metric,.signal-card,.group-card,.audit,.notice{background:rgba(255,255,255,.88);border:1px solid var(--line);border-radius:24px;box-shadow:var(--shadow)}
    .hero-card{padding:22px;display:grid;gap:5px}.hero-card span{font-size:12px;color:var(--muted)}.hero-card strong{font-size:18px;margin-bottom:10px}.notice{margin:24px 0;padding:14px 18px;color:#42526b}
    .section{margin-top:30px}.section-title{display:flex;justify-content:space-between;align-items:end;gap:20px}.section h2,.section-title h2{font-size:26px;margin:4px 0 14px}.grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;margin:24px 0}
    .metric{padding:20px}.metric span{color:var(--muted)}.metric strong{display:block;font-size:42px;line-height:1;margin:10px 0}.metric p{margin:0;color:var(--muted)}
    .signal-list{display:grid;gap:16px}.signal-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}.signal-card{padding:20px;cursor:pointer;transition:.18s transform,.18s box-shadow}.signal-card:hover{transform:translateY(-2px);box-shadow:0 22px 55px rgba(16,32,51,.13)}
    .signal-top{display:flex;justify-content:space-between;gap:12px;align-items:center}.badge,.status,.pill-row span{display:inline-flex;border-radius:999px;padding:5px 10px;font-size:12px;font-weight:700;background:#edf3ff;color:#2442a8}.status{background:#eefaf5;color:var(--green)}.needs_validation .status{background:#fff7ed;color:var(--orange)}.data_gap .status{background:#fff1f0;color:var(--red)}
    .signal-card h3{font-size:20px;margin:14px 0 8px}.signal-card p{color:#42526b}.chart-hint{border-left:4px solid var(--cyan);padding:10px 12px;background:#f0fbff;border-radius:12px;margin:14px 0}.chart-hint strong{display:block}.chart-hint span{color:var(--muted);font-size:13px}
    .scores{display:grid;gap:8px;margin:14px 0}.score-row{display:grid;grid-template-columns:86px 1fr 24px;gap:8px;align-items:center;font-size:12px;color:var(--muted)}.score-row b{height:8px;border-radius:999px;background:linear-gradient(90deg,var(--blue),var(--cyan));display:block}.score-row em{font-style:normal;text-align:right;color:var(--ink)}
    .signal-card button,.audit button,.drawer-head button{border:0;background:var(--ink);color:#fff;border-radius:12px;padding:9px 12px;font-weight:700;cursor:pointer}.mini-list,.next-list{color:#42526b}.two-col{display:grid;grid-template-columns:1.1fr .9fr;gap:22px}
    .group-list,.audit-list{display:grid;gap:12px}.group-card,.audit{padding:16px}.group-card h3,.audit strong{margin:0 0 8px;display:block}.group-card p,.group-card small,.audit p{color:var(--muted)}.pill-row{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}
    .audit{position:relative}.audit span{position:absolute;right:16px;top:16px;font-size:12px;color:var(--muted)}.table-wrap{overflow:auto;background:#fff;border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow)}table{border-collapse:collapse;width:100%;min-width:760px}th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}th{background:#f2f6fb;color:#42526b}tr{transition:.15s background}tbody tr:hover{background:#f8fbff}
    .heat{min-width:42px;border:0;border-radius:10px;padding:8px 10px;cursor:pointer;background:#f1f5f9;color:#334155}.h1{background:#e0f2fe}.h2{background:#bae6fd}.h3{background:#7dd3fc}.h4{background:#38bdf8;color:#072638}
    .drawer{position:fixed;right:0;top:0;width:min(520px,94vw);height:100vh;background:#fff;box-shadow:-20px 0 60px rgba(16,32,51,.18);transform:translateX(105%);transition:.22s transform;z-index:10;padding:20px;overflow:auto}.drawer.open{transform:translateX(0)}.drawer-head{display:flex;justify-content:space-between;gap:14px;align-items:center;border-bottom:1px solid var(--line);padding-bottom:14px;margin-bottom:14px}.drawer-head h2{margin:0}.drawer-card{border:1px solid var(--line);border-radius:18px;padding:14px;margin-bottom:12px;background:#fbfdff}.drawer-card h3{font-size:17px;margin:6px 0}.drawer-meta,.muted{color:var(--muted);font-size:13px}.drawer-card a{color:var(--blue);font-weight:800;text-decoration:none}blockquote{margin:10px 0;padding:10px 12px;background:#f6f8fb;border-left:4px solid var(--blue);border-radius:10px}
    details{background:#f8fafc;border-radius:14px;padding:10px 12px;margin:12px 0}summary{cursor:pointer;font-weight:800}@media(max-width:820px){.hero,.two-col,.grid-3,.signal-grid{grid-template-columns:1fr}.section-title{display:block}.memo-shell,.dashboard-shell{padding:18px 12px 50px}.hero h1{font-size:34px}.drawer{width:100vw}}
    """
