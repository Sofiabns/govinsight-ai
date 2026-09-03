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
loadDashboard();
