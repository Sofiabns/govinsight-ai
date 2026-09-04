const $ = (id) => document.getElementById(id);
const money = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1 });
const number = new Intl.NumberFormat("pt-BR");

function query(extra = {}) {
  const form = new FormData($("filters"));
  const values = Object.fromEntries([...form].filter(([, value]) => value));
  delete values.measure;
  return new URLSearchParams({ ...values, ...extra });
}

async function get(path, params) {
  const response = await fetch(`${path}?${params}`);
  if (!response.ok) throw new Error(`A API respondeu com status ${response.status}`);
  return response.json();
}

const formatMoney = (value) => value == null ? "—" : money.format(Number(value));

function renderTrend(rows, measure) {
  const target = $("trend-chart");
  const key = `${measure}_total`;
  const maximum = Math.max(...rows.map((row) => Number(row[key] || 0)), 0);
  if (!rows.length || maximum === 0) {
    target.innerHTML = '<div class="empty">Não há série mensal para os filtros selecionados.</div>';
    return;
  }
  target.innerHTML = rows.map((row) => {
    const height = Math.max(2, (Number(row[key] || 0) / maximum) * 90);
    const label = new Date(`${row.month}T12:00:00`).toLocaleDateString("pt-BR", { month: "short", year: "2-digit" }).replace(" de ", " ");
    return `<div class="bar-wrap" title="${label}: ${formatMoney(row[key])}"><div class="bar" style="height:${height}%"></div><small>${label}</small></div>`;
  }).join("");
}

function renderRanking(rows) {
  const target = $("ranking");
  if (!rows.length) {
    target.innerHTML = '<div class="empty">Nenhum órgão encontrado.</div>';
    return;
  }
  const maximum = Math.max(...rows.map((row) => Number(row.total || 0)), 1);
  target.innerHTML = rows.slice(0, 6).map((row, index) => `<div class="rank-row"><span class="rank-number">${String(index + 1).padStart(2, "0")}</span><span class="rank-name" title="${row.label}">${row.label}</span><span class="rank-value">${formatMoney(row.total)}</span><div class="rank-track"><div class="rank-fill" style="width:${(Number(row.total || 0) / maximum) * 100}%"></div></div></div>`).join("");
}

function renderOutliers(result) {
  const rows = result.outliers || [];
  $("outlier-count").textContent = number.format(rows.length);
  $("outlier-table").innerHTML = rows.length ? rows.slice(0, 8).map((row) => `<tr><td>${row.numero_controle_pncp}</td><td>${formatMoney(row.value)}</td><td><span class="badge">ACIMA DO PADRÃO</span></td></tr>`).join("") : '<tr><td colspan="3">Nenhum valor atípico nos filtros selecionados.</td></tr>';
}

async function loadDashboard() {
  const measure = $("measure").value;
  const base = query();
  $("alert").hidden = true;
  $("status-text").textContent = "Atualizando indicadores";
  document.querySelector(".status").className = "status";
  try {
    const [summary, trends, ranking, outliers] = await Promise.all([
      get("/analytics/summary", base),
      get("/analytics/trends", base),
      get("/analytics/rankings/organization", query({ measure, limit: 6 })),
      get("/analytics/outliers", query({ measure })),
    ]);
    $("procurement-count").textContent = number.format(summary.procurement_count);
    $("coverage-note").textContent = `${number.format(summary[`${measure}_value_count`] || 0)} com valor informado`;
    $("homologated-total").textContent = formatMoney(summary.homologated_total);
    $("homologated-average").textContent = `Média ${formatMoney(summary.homologated_average)}`;
    $("estimated-total").textContent = formatMoney(summary.estimated_total);
    $("estimated-average").textContent = `Média ${formatMoney(summary.estimated_average)}`;
    $("legend-label").textContent = measure === "homologated" ? "Homologado" : "Estimado";
    renderTrend(trends, measure);
    renderRanking(ranking);
    renderOutliers(outliers);
    $("updated-at").textContent = new Date().toLocaleString("pt-BR", { dateStyle: "medium", timeStyle: "short" });
    $("status-text").textContent = "Dados disponíveis";
    document.querySelector(".status").className = "status ready";
  } catch (error) {
    $("alert").textContent = `Não foi possível carregar o painel. ${error.message}. Verifique se o banco está disponível e tente novamente.`;
    $("alert").hidden = false;
    $("status-text").textContent = "Dados indisponíveis";
    document.querySelector(".status").className = "status error";
  }
}

$("filters").addEventListener("submit", (event) => { event.preventDefault(); loadDashboard(); });

const make = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = String(text);
  return node;
};

function renderAgentReport(report) {
  const target = $("agent-result");
  target.replaceChildren();
  target.append(make("h3", "", "Relatório executivo"), make("p", "", report.summary));

  const metrics = make("div", "report-metrics");
  Object.entries(report.key_numbers || {}).forEach(([label, value]) => {
    const tile = make("div", "report-metric");
    tile.append(make("span", "", label.replaceAll("_", " ")), make("strong", "", value ?? "—"));
    metrics.append(tile);
  });
  if (metrics.childElementCount) target.append(metrics);

  const notes = [...(report.trends || []), ...(report.opportunities || [])];
  if (notes.length) {
    const list = make("ul", "report-notes");
    notes.forEach((item) => list.append(make("li", "", item)));
    target.append(list);
  }
  if ((report.attention_points || []).length) {
    const attention = make("ul", "report-notes attention");
    report.attention_points.forEach((item) => attention.append(make("li", "", item)));
    target.append(attention);
  }

  const evidence = $("agent-evidence");
  const evidenceContent = $("evidence-content");
  evidenceContent.replaceChildren();
  (report.evidence || []).forEach((item) => {
    evidenceContent.append(
      make("p", "", `Fonte: ${item.source} · ${item.row_count} linha(s)`),
      make("pre", "", item.sql),
    );
  });
  evidence.hidden = !(report.evidence || []).length;
}

async function askAgent(question) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  const submit = $("agent-submit");
  submit.disabled = true;
  $("agent-loading").hidden = false;
  $("agent-result").replaceChildren();
  $("agent-evidence").hidden = true;
  try {
    const response = await fetch("/agent/report", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}));
      throw new Error(problem.detail || `A API respondeu com status ${response.status}`);
    }
    renderAgentReport(await response.json());
  } catch (error) {
    const message = error.name === "AbortError"
      ? "A análise levou mais de 15 segundos. Tente uma pergunta mais direta."
      : `Não foi possível concluir a análise. ${error.message}`;
    $("agent-result").append(make("p", "agent-placeholder", message));
  } finally {
    clearTimeout(timer);
    submit.disabled = false;
    $("agent-loading").hidden = true;
  }
}

$("agent-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const question = $("agent-question").value.trim();
  if (question) askAgent(question);
});
document.querySelectorAll(".prompt-chip").forEach((button) => {
  button.addEventListener("click", () => {
    $("agent-question").value = button.textContent.trim();
    askAgent($("agent-question").value);
  });
});
loadDashboard();
