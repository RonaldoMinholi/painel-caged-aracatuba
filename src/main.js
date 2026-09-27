import { createClient } from "@supabase/supabase-js";
import Chart from "chart.js/auto";
import brazil from "@svg-maps/brazil";

const $ = (s) => document.querySelector(s);
const fmt = new Intl.NumberFormat("pt-BR");
const toDate = (v) => new Date(`${v}T12:00:00`);
const monthName = (v) => new Intl.DateTimeFormat("pt-BR", { month: "long" }).format(toDate(v));
const periodName = (v) => new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(toDate(v));
const STATE_IDS = { 11:"ro",12:"ac",13:"am",14:"rr",15:"pa",16:"ap",17:"to",21:"ma",22:"pi",23:"ce",24:"rn",25:"pb",26:"pe",27:"al",28:"se",29:"ba",31:"mg",32:"es",33:"rj",35:"sp",41:"pr",42:"sc",43:"rs",50:"ms",51:"mt",52:"go",53:"df" };
const UF_NAMES = { 11:"Rondônia",12:"Acre",13:"Amazonas",14:"Roraima",15:"Pará",16:"Amapá",17:"Tocantins",21:"Maranhão",22:"Piauí",23:"Ceará",24:"Rio Grande do Norte",25:"Paraíba",26:"Pernambuco",27:"Alagoas",28:"Sergipe",29:"Bahia",31:"Minas Gerais",32:"Espírito Santo",33:"Rio de Janeiro",35:"São Paulo",41:"Paraná",42:"Santa Catarina",43:"Rio Grande do Sul",50:"Mato Grosso do Sul",51:"Mato Grosso",52:"Goiás",53:"Distrito Federal" };

const territory = $("#territory"), periodSummary = $("#period-summary"), periodTree = $("#period-tree"), municipalityFilter = $("#municipality"), municipalitySearch = $("#municipality-search"), ufFilter = $("#uf-filter"), sectionFilter = $("#section-filter"), sexFilter = $("#sex-filter"), status = $("#update-status"), sectorStatus = $("#sector-status");
let supabase, municipalities = [], regionalMunicipalities = [], nationalSeries = [], selectedCompetences = new Set(), selectedMunicipalities = new Set(), selectedUfs = new Set(), selectedSections = new Set(), selectedSexes = new Set(), expandedYear = "", sourceNote = "", trendChart, balanceChart, sectorChart, workerEducationChart, workerAgeChart, workerMetric = "balance", currentPage = "regional", renderRequest = 0, mapRequest = 0, renderTimer;
let redrawUf = () => {}, redrawSections = () => {}, redrawSexes = () => {};

const labelsPlugin = {
  id: "barValueLabels",
  afterDatasetsDraw(chart) {
    if (chart.config.type !== "bar") return;
    const ctx = chart.ctx, data = chart.data.datasets[0], meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.fillStyle = "#666";
    ctx.font = "10px Aptos, Arial";
    const horizontal = chart.options.indexAxis === "y";
    meta.data.forEach((bar, index) => {
      const value = Number(data.data[index]) || 0;
      const point = bar.getProps(["x", "y"], true);
      if (horizontal) {
        ctx.textAlign = value >= 0 ? "left" : "right";
        ctx.textBaseline = "middle";
        ctx.fillText(fmt.format(value), point.x + (value >= 0 ? 8 : -8), point.y);
      } else {
        ctx.textAlign = "center";
        ctx.textBaseline = value >= 0 ? "bottom" : "top";
        ctx.fillText(fmt.format(value), point.x, point.y + (value >= 0 ? -6 : 6));
      }
    });
    ctx.restore();
  }
};

Chart.register(labelsPlugin);

const scheduleRender = () => {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(renderCurrent, 140);
};

const months = () => nationalSeries.map((row) => row.c).sort();
const sum = (rows, key) => rows.reduce((total, row) => total + (Number(row[key]) || 0), 0);

const currentCodes = () =>
  selectedMunicipalities.size
    ? [...selectedMunicipalities]
    : territory.value === "regional"
      ? regionalMunicipalities.map((row) => row.ibge_code)
      : null;

const currentUfs = () =>
  territory.value === "regional"
    ? ["35"]
    : selectedUfs.size
      ? [...selectedUfs]
      : null;

function drawMap(target = "#brazil-map") {
  $(target).innerHTML = `
    <svg viewBox="${brazil.viewBox}">
      ${brazil.locations.map((state) => `
        <path data-state="${state.id}" d="${state.path}">
          <title>${state.name}</title>
        </path>
      `).join("")}
    </svg>
  `;
}

function heat(value, max) {
  if (!Number.isFinite(value) || value <= 0 || max <= 0) return "#e0e0e0";
  const p = Math.sqrt(value / max);
  const a = [220, 221, 238];
  const b = [27, 35, 112];
  return `rgb(${a.map((x, i) => Math.round(x + (b[i] - x) * p)).join(",")})`;
}

function paintMap(balances, target = "#brazil-map") {
  const max = Math.max(0, ...balances.values());

  brazil.locations.forEach((state) => {
    const path = document.querySelector(`${target} path[data-state="${state.id}"]`);
    if (path) path.style.fill = heat(balances.get(state.id), max);
  });
}

async function renderMap(mode = "official") {
  const request = ++mapRequest;
  const competences = selectedCompetences.size ? [...selectedCompetences] : months();
  const detail = mode === "detail";
  const cube = mode === "cube";

  const params = detail
    ? {
        p_competences: competences,
        p_ibge_codes: currentCodes() || regionalMunicipalities.map((row) => row.ibge_code),
        p_sections: selectedSections.size ? [...selectedSections] : null,
        p_sexes: selectedSexes.size ? [...selectedSexes] : null
      }
    : cube
      ? {
          p_competences: competences,
          p_ibge_codes: currentCodes(),
          p_uf_codes: currentUfs(),
          p_sections: selectedSections.size ? [...selectedSections] : null,
          p_sexes: selectedSexes.size ? [...selectedSexes] : null
        }
      : {
          p_competences: competences,
          p_ibge_codes: currentCodes(),
          p_uf_codes: currentUfs()
        };

  const { data, error } = await supabase.rpc(
    detail
      ? "caged_detail_state_balance"
      : cube
        ? "caged_cube_state_balance"
        : "caged_state_balance",
    params
  );

  if (request !== mapRequest || error) return;

  paintMap(
    new Map(
      (data || []).map((row) => [
        STATE_IDS[String(row.uf_code)],
        Number(row.balance) || 0
      ])
    )
  );
}

function check(parent, text, checked, change) {
  const label = document.createElement("label");
  const input = document.createElement("input");

  label.className = "multi-option";
  input.type = "checkbox";
  input.checked = checked;
  input.onclick = (event) => change(input.checked, event);

  label.append(input, document.createTextNode(text));
  parent.append(label);

  return input;
}

function createMulti(element, options, selected, changed) {
  const box = element.querySelector(".multi-options");
  const summary = element.querySelector("summary");

  const draw = () => {
    box.replaceChildren();

    const all = check(box, "Todos", !selected.size, (on) => {
      if (on) selected.clear();
      draw();
      changed();
    });

    all.indeterminate = selected.size > 0;

    options.forEach(([value, label]) => {
      check(box, label, selected.has(value), (on, event) => {
        const addToSelection = event.metaKey || event.ctrlKey || event.shiftKey;

        if (addToSelection) {
          on ? selected.add(value) : selected.delete(value);
        } else {
          selected.clear();
          if (on) selected.add(value);
        }

        draw();
        changed();
      });
    });

    summary.textContent = !selected.size
      ? "Todos"
      : selected.size === 1
        ? (options.find(([value]) => selected.has(value))?.[1] || "1 selecionado")
        : `${selected.size} selecionados`;
  };

  draw();
  return draw;
}

function municipalityScope() {
  const base = territory.value === "regional" ? regionalMunicipalities : municipalities;

  return base.filter(
    (row) => !selectedUfs.size || selectedUfs.has(row.ibge_code.slice(0, 2))
  );
}

function updateSectorUf() {
  const source = selectedMunicipalities.size ? [...selectedMunicipalities] : regionalMunicipalities.map((row) => row.ibge_code);
  const ufs = [...new Set(source.map((code) => code.slice(0, 2)))];
  $("#sector-uf-value").textContent = ufs.length === 1
    ? (UF_NAMES[ufs[0]] || ufs[0])
    : ufs.length ? `${ufs.length} UF(s)` : "Todos";
}

function drawMunicipalityFilter() {
  const box = municipalityFilter.querySelector(".multi-options");
  const summary = municipalityFilter.querySelector("summary");
  const term = municipalitySearch.value
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();

  const options = municipalityScope().filter((row) =>
    row.name
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .toLowerCase()
      .includes(term)
  );

  box.replaceChildren();

  const all = check(box, "Todos", !selectedMunicipalities.size, (on) => {
    if (on) selectedMunicipalities.clear();
    drawMunicipalityFilter();
    scheduleRender();
  });

  all.indeterminate = selectedMunicipalities.size > 0;

  options.forEach((row) => {
    check(box, row.name, selectedMunicipalities.has(row.ibge_code), (on, event) => {
      const addToSelection = event.metaKey || event.ctrlKey || event.shiftKey;

      if (addToSelection) {
        on
          ? selectedMunicipalities.add(row.ibge_code)
          : selectedMunicipalities.delete(row.ibge_code);
      } else {
        selectedMunicipalities.clear();
        if (on) selectedMunicipalities.add(row.ibge_code);
      }

      drawMunicipalityFilter();
      scheduleRender();
    });
  });

  summary.textContent = !selectedMunicipalities.size
    ? "Todos"
    : selectedMunicipalities.size === 1
      ? (municipalities.find((row) => selectedMunicipalities.has(row.ibge_code))?.name || "1 selecionado")
      : `${selectedMunicipalities.size} selecionados`;

  updateSectorUf();
}

function updateScope() {
  const national = territory.value === "national";

  ufFilter.closest(".slicer").hidden = !national;

  if (!national) selectedUfs.clear();

  selectedMunicipalities.clear();
  municipalitySearch.value = "";

  redrawUf();
  redrawSections();
  redrawSexes();
  drawMunicipalityFilter();
}

function drawPeriodTree() {
  const groups = {};

  months().forEach((value) => {
    (groups[value.slice(0, 4)] ??= []).push(value);
  });

  const selected = [...selectedCompetences];

  periodSummary.innerHTML = `
    ${
      selected.length === 1
        ? `${selected[0].slice(0, 4)} (Ano) + ${monthName(selected[0])} (Mês)`
        : selected.length
          ? `${selected.length} meses selecionados`
          : "Todos os meses"
    }
    <span>⌃</span>
  `;

  periodTree.replaceChildren();

  Object.entries(groups).forEach(([year, list]) => {
    const row = document.createElement("div");
    const expand = document.createElement("button");
    const input = document.createElement("input");

    row.className = "period-year";
    expand.className = "tree-arrow";
    expand.type = "button";
    expand.textContent = expandedYear === year ? "⌄" : "›";

    expand.onclick = () => {
      expandedYear = expandedYear === year ? "" : year;
      drawPeriodTree();
    };

    input.type = "checkbox";
    input.checked = list.every((v) => selectedCompetences.has(v));
    input.indeterminate = !input.checked && list.some((v) => selectedCompetences.has(v));

    input.onclick = (event) => {
      event.preventDefault();

      const addToSelection = event.metaKey || event.ctrlKey || event.shiftKey;
      const selectingYear = !list.every((v) => selectedCompetences.has(v));

      if (!addToSelection) selectedCompetences.clear();

      list.forEach((v) => {
        if (addToSelection && !selectingYear) {
          selectedCompetences.delete(v);
        } else {
          selectedCompetences.add(v);
        }
      });

      drawPeriodTree();
      scheduleRender();
    };

    row.append(expand, input, document.createTextNode(year));
    periodTree.append(row);

    if (expandedYear !== year) return;

    const wrap = document.createElement("div");
    wrap.className = "period-months";

    list.forEach((value) => {
      const item = document.createElement("label");
      const inputMonth = document.createElement("input");

      item.className = "period-month";
      inputMonth.type = "checkbox";
      inputMonth.checked = selectedCompetences.has(value);

      inputMonth.onclick = (event) => {
        event.preventDefault();

        const addToSelection = event.metaKey || event.ctrlKey || event.shiftKey;
        const wasSelected = selectedCompetences.has(value);

        if (!addToSelection) {
          selectedCompetences.clear();
          selectedCompetences.add(value);
        } else if (wasSelected) {
          selectedCompetences.delete(value);
        } else {
          selectedCompetences.add(value);
        }

        drawPeriodTree();
        scheduleRender();
      };

      item.append(inputMonth, document.createTextNode(monthName(value)));
      wrap.append(item);
    });

    periodTree.append(wrap);
  });
}

async function officialSeries() {
  const { data, error } = await supabase.rpc("caged_official_series", {
    p_ibge_codes: currentCodes()
  });

  if (error) throw error;

  return (data || []).map((row) => ({
    c: row.competence,
    a: Number(row.admissions) || 0,
    d: Number(row.dismissals) || 0,
    b: Number(row.balance) || 0,
    s: Number(row.stock) || 0
  }));
}

async function detailedSeries() {
  const { data, error } = await supabase.rpc("caged_detail_series", {
    p_ibge_codes: currentCodes(),
    p_sections: selectedSections.size ? [...selectedSections] : null,
    p_sexes: selectedSexes.size ? [...selectedSexes] : null
  });

  if (error) throw error;

  return (data || []).map((row) => ({
    c: row.competence,
    a: Number(row.admissions) || 0,
    d: Number(row.dismissals) || 0,
    b: Number(row.balance) || 0,
    s: 0
  }));
}

function cubeScope() {
  if (currentCodes()) {
    return {
      level: "municipality",
      codes: currentCodes()
    };
  }

  if (currentUfs()) {
    return {
      level: "state",
      codes: currentUfs()
    };
  }

  return {
    level: "country",
    codes: ["BR"]
  };
}

async function cubeSeries() {
  const scope = cubeScope();

  const { data, error } = await supabase.rpc("caged_cube_series", {
    p_geography_level: scope.level,
    p_geography_codes: scope.codes,
    p_sections: selectedSections.size ? [...selectedSections] : null,
    p_sexes: selectedSexes.size ? [...selectedSexes] : null
  });

  if (error) throw error;

  return (data || []).map((row) => ({
    c: row.competence,
    a: Number(row.admissions) || 0,
    d: Number(row.dismissals) || 0,
    b: Number(row.balance) || 0,
    s: 0
  }));
}

function paintCards(rows, granular) {
  const selected = selectedCompetences.size
    ? selectedCompetences
    : new Set(months());

  const cards = rows.filter((row) => selected.has(row.c));

  if (!cards.length) {
    ["admissions", "dismissals", "balance", "stock"].forEach((id) => {
      $("#" + id).textContent = "—";
    });

    status.textContent =
      "Não há dados para essa combinação. Reimporte os microdados para preencher filtros por Grande Grupamento e Sexo.";

    return;
  }

  const balance = sum(cards, "b");

  $("#admissions").textContent = fmt.format(sum(cards, "a"));
  $("#dismissals").textContent = fmt.format(sum(cards, "d"));
  $("#balance").textContent = fmt.format(balance);
  const latestStock = [...cards].sort((a, b) => b.c.localeCompare(a.c))[0];

  $("#stock").textContent =
    granular
      ? "—"
      : fmt.format(latestStock.s);

  status.textContent = granular
    ? "Fonte: microdados oficiais CAGEDMOV e CAGEDFOR. Estoque não é desagregado por Sexo."
    : sourceNote;
}

function chart(data) {
  const labels = data.map((row, index) =>
    row.c.slice(0, 4) !== (index ? data[index - 1].c.slice(0, 4) : "")
      ? row.c.slice(0, 4)
      : ""
  );

  const base = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      tooltip: {
        callbacks: {
          title: (items) => periodName(data[items[0].dataIndex].c)
        }
      }
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: { maxRotation: 0, autoSkip: false }
      },
      y: {
        ticks: {
          callback: (v) => fmt.format(v)
        }
      }
    }
  };

  const lineOptions = {
    ...base,
    plugins: {
      ...base.plugins,
      legend: {
        position: "top",
        align: "start",
        labels: {
          usePointStyle: true,
          pointStyle: "circle",
          boxWidth: 9,
          boxHeight: 9,
          padding: 10
        }
      }
    }
  };

  const barOptions = {
    ...base,
    plugins: {
      ...base.plugins,
      legend: {
        display: false
      }
    }
  };

  trendChart?.destroy();
  balanceChart?.destroy();

  trendChart = new Chart($("#trend"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Admitidos",
          data: data.map((r) => r.a),
          borderColor: "#222a80",
          backgroundColor: "#222a80",
          pointBackgroundColor: "#222a80",
          pointStyle: "circle",
          pointRadius: 0,
          borderWidth: 3
        },
        {
          label: "Desligados",
          data: data.map((r) => r.d),
          borderColor: "#2f58a7",
          backgroundColor: "#2f58a7",
          pointBackgroundColor: "#2f58a7",
          pointStyle: "circle",
          pointRadius: 0,
          borderWidth: 3
        }
      ]
    },
    options: lineOptions
  });

  balanceChart = new Chart($("#balance-chart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Saldo",
          data: data.map((r) => r.b),
          backgroundColor: "#222a80",
          maxBarThickness: 16
        }
      ]
    },
    options: barOptions,
    plugins: [labelsPlugin]
  });
}

let expandedSectorGroups = new Set();

function sectorCells(row, label, options = {}) {
  const tr = document.createElement("tr");
  tr.className = options.detail ? "sector-detail-row" : "sector-parent-row";
  const name = document.createElement("td");
  if (options.expandable) {
    const button = document.createElement("button");
    button.className = "sector-expand";
    button.type = "button";
    button.textContent = expandedSectorGroups.has(row.group_name) ? "−" : "+";
    button.setAttribute("aria-label", "Mostrar atividades de " + row.group_name);
    button.onclick = () => { expandedSectorGroups.has(row.group_name) ? expandedSectorGroups.delete(row.group_name) : expandedSectorGroups.add(row.group_name); renderSectorial(); };
    name.append(button);
  } else {
    name.classList.add("sector-detail-name");
  }
  name.append(document.createTextNode(label));
  tr.append(name);
  const values = [row.admissions, row.dismissals, row.balance, row.average_dismissal_tenure == null ? null : Number(row.average_dismissal_tenure).toLocaleString("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 }), row.stock, row.relative_variation == null ? null : Number(row.relative_variation).toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%"];
  values.forEach((value, index) => { const cell = document.createElement("td"); cell.className = "number"; cell.textContent = index < 3 || index === 4 ? (value == null ? "—" : fmt.format(Number(value))) : (value == null ? "—" : value); tr.append(cell); });
  return tr;
}

async function renderSectorial() {
  const selected = selectedCompetences.size ? [...selectedCompetences] : months();
  sectorStatus.textContent = "Carregando dados setoriais…";
  const [summaryResponse, detailResponse] = await Promise.all([
    supabase.rpc("caged_group_summary", { p_competences: selected, p_ibge_codes: currentCodes() }),
    supabase.rpc("caged_group_detail_summary", { p_competences: selected, p_ibge_codes: currentCodes() }),
    supabase.rpc("caged_occupation_summary", { p_competences: selected, p_ibge_codes: currentCodes() })
  ]);
  if (summaryResponse.error) { sectorStatus.textContent = "Não foi possível carregar a página setorial: " + summaryResponse.error.message; return; }
  const rows = (summaryResponse.data || []).sort((a, b) => Number(b.balance) - Number(a.balance));
  const details = detailResponse.error ? [] : detailResponse.data || [];
  const total = (key) => rows.reduce((value, row) => value + (Number(row[key]) || 0), 0);
  $("#sector-admissions").textContent = fmt.format(total("admissions"));
  $("#sector-dismissals").textContent = fmt.format(total("dismissals"));
  $("#sector-balance").textContent = fmt.format(total("balance"));
  const table = $("#sector-table-body"); table.replaceChildren();
  rows.forEach((row) => {
    const children = details.filter((detail) => detail.group_name === row.group_name);
    table.append(sectorCells(row, row.group_name, { expandable: children.length > 0 }));
    if (expandedSectorGroups.has(row.group_name)) children.forEach((detail) => table.append(sectorCells(detail, detail.activity_name, { detail: true })));
  });
  const totalRow = { admissions: total("admissions"), dismissals: total("dismissals"), balance: total("balance"), average_dismissal_tenure: null, stock: null, relative_variation: null };
  table.append(sectorCells(totalRow, "Total"));
  sectorChart?.destroy();
  sectorChart = new Chart($("#sector-balance-chart"), {
    type: "bar",
    data: { labels: rows.map((row) => row.group_name), datasets: [{ label: "Saldo", data: rows.map((row) => Number(row.balance) || 0), backgroundColor: rows.map((row) => Number(row.balance) < 0 ? "#8d8d8d" : "#222a80"), maxBarThickness: 52 }] },
    options: { indexAxis: "y", responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { ticks: { callback: (value) => fmt.format(value) } }, y: { grid: { display: false } } } }
  });
  sectorStatus.textContent = detailResponse.error ? "Fonte: microdados oficiais Novo CAGED. Detalhamento será preenchido após a reimportação." : "Fonte: microdados oficiais Novo CAGED e Estoque de Referência 2026 do Ministério do Trabalho e Emprego.";
}

let expandedGeographicRows = new Set();

function geographicRow(label, values, level, key, hasChildren) {
  const tr = document.createElement("tr");
  tr.className = "geo-level-" + level;
  const first = document.createElement("td");
  if (hasChildren) {
    const button = document.createElement("button");
    button.className = "geo-expand";
    button.type = "button";
    button.textContent = expandedGeographicRows.has(key) ? "−" : "+";
    button.onclick = () => {
      expandedGeographicRows.has(key) ? expandedGeographicRows.delete(key) : expandedGeographicRows.add(key);
      renderGeographic();
    };
    first.append(button);
  }
  first.append(document.createTextNode(label));
  tr.append(first);
  [values.admissions, values.dismissals, values.balance, values.stock, values.variation].forEach((value, index) => {
    const td = document.createElement("td");
    td.className = "number";
    td.textContent = index === 4 ? (value == null ? "—" : value.toLocaleString("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + "%") : fmt.format(value || 0);
    tr.append(td);
  });
  return tr;
}

async function renderGeographic() {
  drawMap("#geo-brazil-map");
  const selected = selectedCompetences.size ? [...selectedCompetences] : months();
  const codes = currentCodes() || regionalMunicipalities.map((row) => row.ibge_code);
  const { data, error } = await supabase
    .from("caged_official_monthly")
    .select("competence, ibge_code, admissions, dismissals, balance, stock")
    .in("competence", selected)
    .in("ibge_code", codes);

  if (error) { $("#geo-status").textContent = "Não foi possível carregar a página geográfica: " + error.message; return; }

  const rows = data || [];
  const latest = selected.slice().sort().at(-1);
  const summarize = (list) => {
    const admissions = list.reduce((t, row) => t + (Number(row.admissions) || 0), 0);
    const dismissals = list.reduce((t, row) => t + (Number(row.dismissals) || 0), 0);
    const balance = list.reduce((t, row) => t + (Number(row.balance) || 0), 0);
    const stock = list.filter((row) => row.competence === latest).reduce((t, row) => t + (Number(row.stock) || 0), 0);
    return { admissions, dismissals, balance, stock, variation: stock ? balance / stock * 100 : null };
  };
  const regional = summarize(rows);
  $("#geo-admissions").textContent = fmt.format(regional.admissions);
  $("#geo-dismissals").textContent = fmt.format(regional.dismissals);
  $("#geo-balance").textContent = fmt.format(regional.balance);
  paintMap(new Map([["35", regional.variation == null ? 0 : regional.variation]]), "#geo-brazil-map");

  const byMunicipality = new Map();
  rows.forEach((row) => {
    const existing = byMunicipality.get(row.ibge_code) || [];
    existing.push(row);
    byMunicipality.set(row.ibge_code, existing);
  });

  const body = $("#geo-table-body");
  body.replaceChildren();
  const regionalKey = "regional";
  const stateKey = "state-35";
  body.append(geographicRow("Região Administrativa de Araçatuba", regional, 1, regionalKey, true));
  if (expandedGeographicRows.has(regionalKey)) {
    body.append(geographicRow("São Paulo", regional, 2, stateKey, true));
    if (expandedGeographicRows.has(stateKey)) {
      [...byMunicipality.entries()]
        .map(([code, list]) => ({ name: municipalities.find((city) => city.ibge_code === code)?.name || code, values: summarize(list) }))
        .sort((a, b) => b.values.balance - a.values.balance)
        .forEach((city) => body.append(geographicRow(city.name, city.values, 3, "", false)));
    }
  }
  $("#geo-status").textContent = "Fonte: Tabela 8.1 — Novo CAGED. O mapa destaca São Paulo porque esta versão usa exclusivamente a Região Administrativa de Araçatuba.";
}


// Os microdados usam a codificação histórica: 2, 3 e 4 formam o
// Fundamental incompleto; 8 e 9 são, respectivamente, Superior incompleto e completo.
const WORKER_EDUCATION = {
  "1": "Analfabeto", "2": "Fundamental Incompleto", "3": "Fundamental Incompleto",
  "4": "Fundamental Incompleto", "5": "Fundamental Completo", "6": "Médio Incompleto",
  "7": "Médio Completo", "8": "Superior Incompleto", "9": "Superior Completo", "10": "Superior Completo", "11": "Superior Completo",
  "Analfabeto": "Analfabeto", "Fundamental Incompleto": "Fundamental Incompleto",
  "Fundamental Completo": "Fundamental Completo", "Médio Incompleto": "Médio Incompleto",
  "Médio Completo": "Médio Completo", "Superior Incompleto": "Superior Incompleto",
  "Superior Completo": "Superior Completo"
};
const WORKER_EDUCATION_ORDER = ["Analfabeto", "Fundamental Incompleto", "Fundamental Completo", "Médio Incompleto", "Médio Completo", "Superior Incompleto", "Superior Completo"];
const WORKER_AGE_ORDER = ["Até 17 anos", "18 a 24 anos", "25 a 29 anos", "30 a 39 anos", "40 a 49 anos", "50 a 64 anos", "65 anos ou mais"];

function workerValue(row) {
  return workerMetric === "admissions" ? Number(row.admissions) || 0
    : workerMetric === "dismissals" ? Number(row.dismissals) || 0
    : Number(row.balance) || 0;
}

function workerTitle(prefix) {
  return workerMetric === "admissions" ? `Admitidos por ${prefix}`
    : workerMetric === "dismissals" ? `Desligados por ${prefix}`
    : `Saldo por ${prefix}`;
}

function workerBar(canvas, labels, values) {
  return new Chart(canvas, {
    type: "bar",
    data: { labels, datasets: [{ data: values, backgroundColor: values.map((v) => v < 0 ? "#777" : "#222a80"), maxBarThickness: 48 }] },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      layout: { padding: { right: 46 } },
      plugins: { legend: { display: false } },
      scales: {
        x: { ticks: { callback: (value) => fmt.format(value) } },
        y: { grid: { display: false }, ticks: { font: { size: 14 } } }
      }
    }
  });
}

function workerTableCells(row, label, options = {}) {
  const tr = document.createElement("tr");
  if (options.detail) tr.className = "sector-detail-row";
  if (options.total) tr.className = "total-row";
  const labelCell = document.createElement("td");
  if (options.detail) labelCell.className = "sector-detail-name";
  if (options.expandable) {
    const button = document.createElement("button");
    button.className = "sector-expand";
    button.type = "button";
    button.textContent = expandedSectorGroups.has(row.group_name) ? "−" : "+";
    button.onclick = () => {
      expandedSectorGroups.has(row.group_name) ? expandedSectorGroups.delete(row.group_name) : expandedSectorGroups.add(row.group_name);
      renderWorker();
    };
    labelCell.append(button);
  }
  labelCell.append(document.createTextNode(label));
  tr.append(labelCell);
  [row.admissions, row.dismissals, row.balance, row.average_dismissal_tenure == null ? "—" : Number(row.average_dismissal_tenure).toLocaleString("pt-BR", { maximumFractionDigits: 1 })]
    .forEach((value) => {
      const cell = document.createElement("td");
      cell.className = "number";
      cell.textContent = typeof value === "number" ? fmt.format(value) : value;
      tr.append(cell);
    });
  return tr;
}

async function renderWorker() {
  const selected = selectedCompetences.size ? [...selectedCompetences] : months();
  $("#worker-status").textContent = "Carregando características do trabalhador…";
  const [monthlyResponse, summaryResponse, detailResponse, occupationResponse] = await Promise.all([
    supabase.from("caged_monthly").select("education, age_band, sex, admissions, dismissals, balance, competence, ibge_code")
      .in("competence", selected).in("ibge_code", currentCodes() || regionalMunicipalities.map((city) => city.ibge_code)),
    supabase.rpc("caged_group_summary", { p_competences: selected, p_ibge_codes: currentCodes() }),
    supabase.rpc("caged_group_detail_summary", { p_competences: selected, p_ibge_codes: currentCodes() })
  ]);
  if (monthlyResponse.error) {
    $("#worker-status").textContent = "Não foi possível carregar a página: " + monthlyResponse.error.message;
    return;
  }
  const data = monthlyResponse.data || [];
  const totals = (field, order, normalizer = (v) => v) => new Map(order.map((name) => [name, 0]));
  const education = totals("education", WORKER_EDUCATION_ORDER);
  const age = totals("age_band", WORKER_AGE_ORDER);
  let men = 0, women = 0;
  data.forEach((row) => {
    const value = workerValue(row);
    const rawEducation = String(row.education || "").trim();
    const educationCode = Number.isFinite(Number(rawEducation)) ? String(Number(rawEducation)) : rawEducation;
    const educationName = WORKER_EDUCATION[educationCode] || "Não informado";
    if (education.has(educationName)) education.set(educationName, education.get(educationName) + value);
    const ageName = age.has(row.age_band) ? row.age_band : "65 anos ou mais";
    age.set(ageName, age.get(ageName) + value);
    if (row.sex === "Masculino") men += value;
    if (row.sex === "Feminino") women += value;
  });
  $("#worker-education-title").textContent = workerTitle("Grau de Instrução");
  $("#worker-age-title").textContent = workerTitle("Faixa Etária");
  $("#worker-men").textContent = fmt.format(men);
  $("#worker-women").textContent = fmt.format(women);
  workerEducationChart?.destroy();
  workerAgeChart?.destroy();
  workerEducationChart = workerBar($("#worker-education-chart"), WORKER_EDUCATION_ORDER, WORKER_EDUCATION_ORDER.map((key) => education.get(key)));
  workerAgeChart = workerBar($("#worker-age-chart"), WORKER_AGE_ORDER, WORKER_AGE_ORDER.map((key) => age.get(key)));

  const occupationRows = occupationResponse.error ? [] : occupationResponse.data || [];
  const hasOccupations = occupationRows.length > 0;
  const rows = (hasOccupations ? occupationRows : summaryResponse.data || []).sort((a, b) => Number(b.balance) - Number(a.balance));
  const details = detailResponse.error ? [] : detailResponse.data || [];
  $("#worker-table-title").textContent = hasOccupations ? "Grande Grupo Ocupacional" : "Grande Grupamento de Atividade Econômica";
  const table = $("#worker-table-body"); table.replaceChildren();
  rows.forEach((row) => {
    const children = hasOccupations ? [] : details.filter((child) => child.group_name === row.group_name);
    const label = hasOccupations ? row.occupation_group : row.group_name;
    table.append(workerTableCells(row, label, { expandable: children.length > 0 }));
    if (!hasOccupations && expandedSectorGroups.has(row.group_name)) children.forEach((child) => table.append(workerTableCells(child, child.activity_name, { detail: true })));
  });
  const total = (key) => rows.reduce((value, row) => value + (Number(row[key]) || 0), 0);
  table.append(workerTableCells({ admissions: total("admissions"), dismissals: total("dismissals"), balance: total("balance"), average_dismissal_tenure: null }, "Total", { total: true }));
  $("#worker-status").textContent = hasOccupations
    ? "Fonte: microdados oficiais Novo CAGED — classificação ocupacional CBO."
    : "Fonte: microdados oficiais Novo CAGED. A classificação ocupacional será exibida após a reimportação CBO.";
}

function renderCurrent() {
  if (currentPage === "setorial") return renderSectorial();
  if (currentPage === "geographic") return renderGeographic();
  if (currentPage === "worker") return renderWorker();
  return render();
}

function setPage(page) {
  currentPage = page;
  const regional = page === "regional";
  const sectorial = page === "setorial";
  $("#regional-page").hidden = !regional;
  $("#setorial-page").hidden = !sectorial;
  const geographic = page === "geographic";
  const worker = page === "worker";
  $("#geographic-page").hidden = !geographic;
  $("#worker-page").hidden = !worker;
  $("#page-label").textContent = regional ? "Página 1 de 4" : sectorial ? "Página 2 de 4" : geographic ? "Página 3 de 4" : "Página 4 de 4";
  $("#previous-page").disabled = regional;
  $("#next-page").disabled = worker;
  sectionFilter.closest(".slicer").hidden = !(regional || worker);
  sexFilter.closest(".slicer").hidden = !(regional || worker);
  $(".map-section").hidden = !regional;
  $("#sector-uf-slicer").hidden = regional;
  renderCurrent();
}
async function render() {
  const request = ++renderRequest;

  try {
    const granular = selectedSections.size > 0 || selectedSexes.size > 0;

    const mode = granular ? "detail" : "official";

    const history = mode === "detail"
      ? await detailedSeries()
      : await officialSeries();

    if (request !== renderRequest) return;

    paintCards(history, mode !== "official");
    chart(history);
    renderMap(mode);
  } catch (error) {
    if (request === renderRequest) {
      status.textContent = `Não foi possível carregar os dados: ${error.message}`;
    }
  }
}

function closeFilters(event) {
  [ufFilter, municipalityFilter, sectionFilter, sexFilter].forEach((filter) => {
    if (filter.open && !filter.contains(event.target)) {
      filter.open = false;
    }
  });

  if (
    !periodTree.hidden &&
    !periodTree.contains(event.target) &&
    !periodSummary.contains(event.target)
  ) {
    periodTree.hidden = true;
    periodSummary.setAttribute("aria-expanded", "false");
    periodSummary.querySelector("span").textContent = "⌄";
  }
}

async function boot() {
  try {
    drawMap();
    drawMap("#geo-brazil-map");

    if (!import.meta.env.VITE_SUPABASE_URL) {
      throw Error("As credenciais públicas do Supabase não foram configuradas no Vercel.");
    }

    supabase = createClient(
      import.meta.env.VITE_SUPABASE_URL,
      import.meta.env.VITE_SUPABASE_ANON_KEY
    );

    const municipalityResponse = await supabase.rpc("caged_municipalities");

    if (municipalityResponse.error) throw municipalityResponse.error;

    municipalities = municipalityResponse.data || [];
    regionalMunicipalities = municipalities.filter((row) => row.is_regional);

    const [regionalResponse, importsResponse] = await Promise.all([
      supabase.rpc("caged_official_series", {
        p_ibge_codes: regionalMunicipalities.map((row) => row.ibge_code)
      }),
      supabase
        .from("caged_official_imports")
        .select("competence_end")
        .order("imported_at", { ascending: false })
        .limit(1)
    ]);

    if (regionalResponse.error) throw regionalResponse.error;

    nationalSeries = (regionalResponse.data || []).map((row) => ({
      c: row.competence,
      a: Number(row.admissions) || 0,
      d: Number(row.dismissals) || 0,
      b: Number(row.balance) || 0,
      s: Number(row.stock) || 0
    }));

    if (!nationalSeries.length) {
      throw Error("A série oficial da Tabela 8.1 ainda não foi importada.");
    }

    sourceNote = importsResponse.data?.[0]
      ? `Fonte: Tabela 8.1 — Novo CAGED, Ministério do Trabalho e Emprego. Região Administrativa de Araçatuba atualizada até ${periodName(importsResponse.data[0].competence_end)}.`
      : "Fonte: Tabela 8.1 — Novo CAGED, Ministério do Trabalho e Emprego.";

    const latest = months().at(-1);
    selectedCompetences.add(latest);
    expandedYear = latest.slice(0, 4);

    redrawUf = createMulti(
      ufFilter,
      Object.entries(UF_NAMES).map(([code, name]) => [code, name]),
      selectedUfs,
      () => {
        selectedMunicipalities.clear();
        drawMunicipalityFilter();
        scheduleRender();
      }
    );

    redrawSections = createMulti(
      sectionFilter,
      [
        "Agropecuária",
        "Indústrias extrativas",
        "Indústrias de transformação",
        "Eletricidade e gás",
        "Água, esgoto e gestão de resíduos",
        "Construção",
        "Comércio",
        "Transporte, armazenagem e correio",
        "Alojamento e alimentação",
        "Informação e comunicação",
        "Atividades financeiras e seguros",
        "Atividades imobiliárias",
        "Atividades profissionais, científicas e técnicas",
        "Atividades administrativas e serviços complementares",
        "Administração pública, defesa e seguridade social",
        "Educação",
        "Saúde humana e serviços sociais",
        "Artes, cultura, esporte e recreação",
        "Outras atividades de serviços",
        "Serviços domésticos",
        "Organismos internacionais"
      ].map((v) => [v, v]),
      selectedSections,
      scheduleRender
    );

    redrawSexes = createMulti(
      sexFilter,
      ["Masculino", "Feminino", "Não informado"].map((v) => [v, v]),
      selectedSexes,
      scheduleRender
    );

    territory.onchange = () => {
      updateScope();
      scheduleRender();
    };

    municipalitySearch.oninput = drawMunicipalityFilter;

    periodSummary.onclick = () => {
      periodTree.hidden = !periodTree.hidden;
      periodSummary.setAttribute("aria-expanded", String(!periodTree.hidden));
      periodSummary.querySelector("span").textContent = periodTree.hidden ? "⌄" : "⌃";
    };

    document.addEventListener("pointerdown", closeFilters);

    updateScope();
    drawPeriodTree();
    setPage("regional");
    $(".worker-metric-switch").onclick = (event) => {
      const button = event.target.closest("button[data-worker-metric]");
      if (!button) return;
      workerMetric = button.dataset.workerMetric;
      document.querySelectorAll("[data-worker-metric]").forEach((item) => item.classList.toggle("active", item === button));
      renderWorker();
    };
    $("#previous-page").onclick = () => setPage(currentPage === "worker" ? "geographic" : currentPage === "geographic" ? "setorial" : "regional");
    $("#next-page").onclick = () => setPage(currentPage === "regional" ? "setorial" : currentPage === "setorial" ? "geographic" : "worker");
  } catch (error) {
    status.textContent = error.message;
  }
}

boot();
