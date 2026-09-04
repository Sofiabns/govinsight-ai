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
const metricLabels = {
  procurement_count: "Processos analisados",
  row_count: "Linhas retornadas",
  sample_size: "Tamanho da amostra",
  estimated_total: "Total estimado",
  estimated_average: "Média estimada",
  homologated_total: "Total homologado",
  homologated_average: "Média homologada",
  label: "Nome",
  month: "Mês",
  value: "Valor",
  minimum: "Mínimo",
  q1: "1º quartil",
  median: "Mediana",
  q3: "3º quartil",
  maximum: "Máximo",
  mean: "Média",
  numero_controle_pncp: "Processo PNCP",
};
const evidenceLabels = {
  analytics_summary: "Resumo analítico",
  analytics_by_organization: "Ranking por órgão",
  analytics_by_state: "Ranking por estado",
  analytics_by_modality: "Ranking por modalidade",
  analytics_monthly: "Série histórica mensal",
  analytics_procurement_base: "Base analítica consolidada",
};

function formatAgentMetric(label, value) {
  if (value == null) return "—";
  if (["value", "minimum", "q1", "median", "q3", "maximum", "mean"].includes(label)
      || label.endsWith("_total") || label.endsWith("_average")) return formatMoney(value);
  if (label.endsWith("_count") || label === "row_count" || label === "sample_size") {
    return number.format(Number(value));
  }
  return String(value);
}

function renderDataPoints(rows) {
  if (!rows || rows.length <= 1) return null;
  const keys = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const wrapper = make("div", "answer-table-wrap");
  wrapper.append(make("h4", "", "Principais resultados"));
  const table = make("table", "answer-table");
  const head = make("thead", "");
  const headerRow = make("tr", "");
  keys.forEach((key) => headerRow.append(make("th", "", metricLabels[key] || key.replaceAll("_", " "))));
  head.append(headerRow);
  const body = make("tbody", "");
  rows.forEach((row) => {
    const tr = make("tr", "");
    keys.forEach((key) => tr.append(make("td", "", formatAgentMetric(key, row[key]))));
    body.append(tr);
  });
  table.append(head, body);
  wrapper.append(table);
  return wrapper;
}

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
    $("hero-records").textContent = number.format(summary.procurement_count);
    $("hero-period").textContent = `${number.format(trends.length)} meses`;
    if (trends.length) {
      const compactMonth = (value) => new Date(`${value}T12:00:00`).toLocaleDateString(
        "pt-BR", { month: "short", year: "numeric" },
      );
      $("hero-period-note").textContent = `${compactMonth(trends[0].month)} — ${compactMonth(trends.at(-1).month)}`;
    } else {
      $("hero-period-note").textContent = "sem período no recorte";
    }
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
    const readableLabel = metricLabels[label] || label.replaceAll("_", " ");
    tile.append(
      make("span", "", readableLabel),
      make("strong", "", formatAgentMetric(label, value)),
    );
    metrics.append(tile);
  });
  if (metrics.childElementCount) target.append(metrics);
  const dataPoints = renderDataPoints(report.data_points);
  if (dataPoints) target.append(dataPoints);

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
    const card = make("article", "evidence-card");
    const header = make("div", "evidence-header");
    const title = make("div", "");
    title.append(make("span", "evidence-kicker", "FONTE VALIDADA"));
    const sourceKey = item.source.split(".").at(-1);
    title.append(make("strong", "", evidenceLabels[sourceKey] || sourceKey.replaceAll("_", " ")));
    header.append(title, make("span", "evidence-count", `${number.format(item.row_count)} linha(s)`));

    const checks = make("div", "evidence-checks");
    ["Camada Gold", "Somente leitura", "Consulta limitada"].forEach((label) => {
      checks.append(make("span", "evidence-check", `✓ ${label}`));
    });

    const technical = make("details", "query-details");
    technical.append(make("summary", "", "Detalhes técnicos da consulta"));
    technical.append(make("pre", "", item.sql));
    card.append(header, checks, technical);
    evidenceContent.append(card);
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
