import { createClient } from "@supabase/supabase-js";
import Chart from "chart.js/auto";
import brazil from "@svg-maps/brazil";

const $ = (selector) => document.querySelector(selector);

const fmt = new Intl.NumberFormat("pt-BR");

const sum = (rows, field) =>
  rows.reduce((total, row) => total + (+row[field] || 0), 0);

const date = (competence) => new Date(`${competence}T12:00:00`);

const month = (competence) =>
  new Intl.DateTimeFormat("pt-BR", { month: "long" }).format(
    date(competence),
  );

const label = (competence) =>
  new Intl.DateTimeFormat("pt-BR", {
    month: "long",
    year: "numeric",
  }).format(date(competence));

const territory = $("#territory");
const municipalityFilter = $("#municipality");
const sectionFilter = $("#section-filter");
const sexFilter = $("#sex-filter");
const periodSummary = $("#period-summary");
const periodTree = $("#period-tree");
const status = $("#update-status");

const STATE_IDS = {
  11: "ro",
  12: "ac",
  13: "am",
  14: "rr",
  15: "pa",
  16: "ap",
  17: "to",
  21: "ma",
  22: "pi",
  23: "ce",
  24: "rn",
  25: "pb",
  26: "pe",
  27: "al",
  28: "se",
  29: "ba",
  31: "mg",
  32: "es",
  33: "rj",
  35: "sp",
  41: "pr",
  42: "sc",
  43: "rs",
  50: "ms",
  51: "mt",
  52: "go",
  53: "df",
};

let officialRows = [];
let detailRows = [];
let municipalities = [];

let selectedCompetences = new Set();
let selectedMunicipalities = new Set();
let selectedSections = new Set();
let selectedSexes = new Set();

let expandedYear = "";
let sourceNote = "";
let trendChart;
let balanceChart;
let supabase;
let mapRequest = 0;

const values = {
  id: "barValueLabels",

  afterDatasetsDraw(chart) {
    if (chart.config.type !== "bar") return;

    const dataset = chart.data.datasets[0];
    const meta = chart.getDatasetMeta(0);
    const context = chart.ctx;

    context.save();
    context.fillStyle = "#666";
    context.font = "10px Aptos, Arial";
    context.textAlign = "center";

    meta.data.forEach((bar, index) => {
      const value = +dataset.data[index] || 0;
      const point = bar.getProps(["x", "y"], true);

      context.textBaseline = value >= 0 ? "bottom" : "top";

      context.fillText(
        fmt.format(value),
        point.x,
        point.y + (value >= 0 ? -6 : 6),
      );
    });

    context.restore();
  },
};

async function pages(query) {
  const all = [];

  for (let start = 0; ; start += 1000) {
    const { data, error } = await query.range(start, start + 999);

    if (error) throw error;

    all.push(...(data || []));

    if (!data || data.length < 1000) return all;
  }
}

function drawBrazilMap() {
  const paths = brazil.locations
    .map(
      (state) =>
        `<path data-state="${state.id}" d="${state.path}">
          <title>${state.name}</title>
        </path>`,
    )
    .join("");

  $("#brazil-map").innerHTML = `
    <svg viewBox="${brazil.viewBox}" aria-hidden="true">
      ${paths}
    </svg>
  `;
}

function normalizeSex(value) {
  const sex = String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim()
    .toUpperCase();

  if (["F", "FEMININO", "MULHER"].includes(sex)) return "Feminino";
  if (["M", "MASCULINO", "HOMEM"].includes(sex)) return "Masculino";

  return "Não informado";
}

function color(value, maximum) {
  if (!Number.isFinite(value) || value <= 0 || maximum <= 0) {
    return "#e0e0e0";
  }

  const intensity = Math.sqrt(value / maximum);
  const start = [220, 221, 238];
  const end = [27, 35, 112];

  const rgb = start.map((channel, index) =>
    Math.round(channel + (end[index] - channel) * intensity),
  );

  return `rgb(${rgb.join(",")})`;
}

function paintMap(balances) {
  const maximum = Math.max(0, ...balances.values());

  brazil.locations.forEach((state) => {
    const path = document.querySelector(
      `#brazil-map path[data-state="${state.id}"]`,
    );

    if (path) {
      path.style.fill = color(balances.get(state.id), maximum);
    }
  });
}

async function renderMap() {
  if (!supabase) return;

  const request = ++mapRequest;

  const competences = selectedCompetences.size
    ? [...selectedCompetences]
    : months();

  const hasDetailedFilter =
    selectedMunicipalities.size ||
    selectedSections.size ||
    selectedSexes.size;

  if (hasDetailedFilter) {
    const [rows] = filtered(true);
    const balances = new Map();

    rows.forEach((row) => {
      const state = STATE_IDS[String(row.ibge_code).slice(0, 2)];

      balances.set(
        state,
        (balances.get(state) || 0) + (+row.balance || 0),
      );
    });

    paintMap(balances);
    return;
  }

  const { data, error } = await supabase.rpc("caged_state_balance", {
    p_competences: competences,
  });

  if (request !== mapRequest || error) {
    if (error) {
      console.warn("Mapa por UF indisponível:", error.message);
    }

    return;
  }

  const balances = new Map(
    (data || []).map((row) => [
      STATE_IDS[String(row.uf_code)],
      Number(row.balance) || 0,
    ]),
  );

  paintMap(balances);
}

async function boot() {
  try {
    drawBrazilMap();

    if (!import.meta.env.VITE_SUPABASE_URL) {
      throw Error(
        "As credenciais públicas do Supabase não foram configuradas no Vercel.",
      );
    }

    supabase = createClient(
      import.meta.env.VITE_SUPABASE_URL,
      import.meta.env.VITE_SUPABASE_ANON_KEY,
    );

    municipalities = await pages(
      supabase
        .from("municipalities")
        .select("ibge_code,name,is_regional")
        .eq("is_regional", true)
        .order("name"),
    );

    const municipalityCodes = municipalities.map((item) => item.ibge_code);

    const [official, detail, imports] = await Promise.all([
      pages(
        supabase
          .from("caged_official_monthly")
          .select("competence,ibge_code,stock,admissions,dismissals,balance")
          .in("ibge_code", municipalityCodes)
          .order("competence"),
      ),

      pages(
        supabase
          .from("caged_monthly")
          .select(
            "competence,ibge_code,cnae_section,sex,admissions,dismissals,balance",
          )
          .in("ibge_code", municipalityCodes)
          .order("competence"),
      ),

      supabase
        .from("caged_official_imports")
        .select("competence_end")
        .order("competence_end", { ascending: false })
        .limit(1),
    ]);

    officialRows = official;

    detailRows = detail.map((row) => ({
      ...row,
      sex: normalizeSex(row.sex),
    }));

    if (!officialRows.length) {
      throw Error("A Tabela 8.1 ainda não possui dados.");
    }

    selectedCompetences.add(months().at(-1));
    expandedYear = months().at(-1).slice(0, 4);

    multi(
      municipalityFilter,
      municipalities.map((item) => [item.ibge_code, item.name]),
      selectedMunicipalities,
    );

    multi(
      sectionFilter,
      [...new Set(detailRows.map((item) => item.cnae_section).filter(Boolean))]
        .sort()
        .map((item) => [item, item]),
      selectedSections,
    );

    multi(
      sexFilter,
      ["Masculino", "Feminino", "Não informado"].map((item) => [
        item,
        item,
      ]),
      selectedSexes,
    );

    sourceNote = imports.data?.[0]
      ? `Fonte: Novo CAGED — Ministério do Trabalho e Emprego. Série oficial atualizada até ${label(imports.data[0].competence_end)}.`
      : "";

    territory.addEventListener("change", render);

    periodSummary.onclick = () => {
      periodTree.hidden = !periodTree.hidden;
    };

    tree();
    render();
  } catch (error) {
    status.textContent = error.message;
  }
}

function months() {
  return [...new Set(officialRows.map((item) => item.competence))].sort();
}

function multi(element, options, selected) {
  const box = element.querySelector(".multi-options");
  const summary = element.querySelector("summary");

  function draw() {
    box.replaceChildren();

    const all = check(box, "Todos", !selected.size, (checked) => {
      if (checked) selected.clear();

      draw();
      render();
    });

    all.indeterminate = !!selected.size;

    options.forEach(([value, text]) => {
      check(box, text, selected.has(value), (checked) => {
        if (checked) {
          selected.add(value);
        } else {
          selected.delete(value);
        }

        draw();
        render();
      });
    });

    summary.textContent = !selected.size
      ? "Todos"
      : selected.size === 1
        ? options.find((item) => selected.has(item[0]))?.[1] ||
          "1 selecionado"
        : `${selected.size} selecionados`;
  }

  draw();
}

function check(parent, text, checked, onChange) {
  const label = document.createElement("label");
  const input = document.createElement("input");

  label.className = "multi-option";

  input.type = "checkbox";
  input.checked = checked;
  input.onchange = () => onChange(input.checked);

  label.append(input, document.createTextNode(text));
  parent.append(label);

  return input;
}

function tree() {
  const groups = {};

  months().forEach((competence) => {
    const year = competence.slice(0, 4);

    if (!groups[year]) groups[year] = [];

    groups[year].push(competence);
  });

  const selected = [...selectedCompetences];

  periodSummary.innerHTML = `
    ${
      selected.length === 1
        ? `${selected[0].slice(0, 4)} (Ano) + ${month(selected[0])} (Mês)`
        : selected.length
          ? `${selected.length} meses selecionados`
          : "Todos os meses"
    }
    <span>⌃</span>
  `;

  periodTree.replaceChildren();

  Object.entries(groups).forEach(([year, competences]) => {
    const row = document.createElement("div");
    row.className = "period-year";

    const arrow = document.createElement("button");
    arrow.className = "tree-arrow";
    arrow.textContent = expandedYear === year ? "⌄" : "›";

    arrow.onclick = () => {
      expandedYear = expandedYear === year ? "" : year;
      tree();
    };

    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = competences.every((item) =>
      selectedCompetences.has(item),
    );

    input.indeterminate =
      !input.checked &&
      competences.some((item) => selectedCompetences.has(item));

    input.onchange = () => {
      competences.forEach((item) => {
        if (input.checked) {
          selectedCompetences.add(item);
        } else {
          selectedCompetences.delete(item);
        }
      });

      tree();
      render();
    };

    row.append(arrow, input, document.createTextNode(year));
    periodTree.append(row);

    if (expandedYear !== year) return;

    const monthList = document.createElement("div");
    monthList.className = "period-months";

    competences.forEach((competence) => {
      const label = document.createElement("label");
      const input = document.createElement("input");

      label.className = "period-month";

      input.type = "checkbox";
      input.checked = selectedCompetences.has(competence);

      input.onchange = () => {
        if (input.checked) {
          selectedCompetences.add(competence);
        } else {
          selectedCompetences.delete(competence);
        }

        tree();
        render();
      };

      label.append(input, document.createTextNode(month(competence)));
      monthList.append(label);
    });

    periodTree.append(monthList);
  });
}

function filtered(useSelectedCompetences = true) {
  const detailedFilterActive =
    selectedSections.size > 0 || selectedSexes.size > 0;

  const source = detailedFilterActive ? detailRows : officialRows;

  const selectedMonths =
    useSelectedCompetences && selectedCompetences.size
      ? selectedCompetences
      : new Set(months());

  const rows = source.filter(
    (item) =>
      selectedMonths.has(item.competence) &&
      (!selectedMunicipalities.size ||
        selectedMunicipalities.has(item.ibge_code)) &&
      (!selectedSections.size ||
        selectedSections.has(item.cnae_section)) &&
      (!selectedSexes.size || selectedSexes.has(item.sex)),
  );

  return [rows, detailedFilterActive];
}

function series(rows) {
  return [...new Set(rows.map((item) => item.competence))]
    .sort()
    .map((competence) => {
      const periodRows = rows.filter(
        (item) => item.competence === competence,
      );

      return {
        competence,
        admissions: sum(periodRows, "admissions"),
        dismissals: sum(periodRows, "dismissals"),
        balance: sum(periodRows, "balance"),
      };
    });
}

function render() {
  const [cardRows, detailedFilterActive] = filtered(true);
  const [historyRows] = filtered(false);

  if (!cardRows.length) {
    ["admissions", "dismissals", "balance", "stock"].forEach((id) => {
      $(`#${id}`).textContent = "—";
    });

    chart(series(historyRows));
    renderMap();

    status.textContent = "Não há dados para essa combinação.";
    return;
  }

  $("#admissions").textContent = fmt.format(sum(cardRows, "admissions"));
  $("#dismissals").textContent = fmt.format(sum(cardRows, "dismissals"));

  const balance = sum(cardRows, "balance");

  $("#balance").textContent = `${balance > 0 ? "+" : ""}${fmt.format(balance)}`;

  $("#stock").textContent =
    detailedFilterActive || selectedCompetences.size !== 1
      ? "—"
      : fmt.format(sum(cardRows, "stock"));

  chart(series(historyRows));
  renderMap();

  status.textContent = detailedFilterActive
    ? "Fonte: microdados do Novo CAGED. Os gráficos mostram toda a série; os cartões respeitam Ano, Mês. Estoque só é exibido sem filtros detalhados e para um mês."
    : sourceNote;
}

function chart(seriesData = []) {
  const labels = seriesData.map((item, index) => {
    const previousYear = index
      ? seriesData[index - 1].competence.slice(0, 4)
      : "";

    return item.competence.slice(0, 4) !== previousYear
      ? item.competence.slice(0, 4)
      : "";
  });

  const options = {
    responsive: true,
    maintainAspectRatio: false,

    plugins: {
      legend: {
        position: "top",
      },

      tooltip: {
        callbacks: {
          title: (items) =>
            label(seriesData[items[0].dataIndex].competence),
        },
      },
    },

    scales: {
      x: {
        grid: {
          display: false,
        },

        ticks: {
          maxRotation: 0,
          autoSkip: false,
        },
      },

      y: {
        ticks: {
          callback: (value) => fmt.format(value),
        },
      },
    },
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
          data: seriesData.map((item) => item.admissions),
          borderColor: "#222a80",
          pointRadius: 0,
          borderWidth: 3,
        },

        {
          label: "Desligados",
          data: seriesData.map((item) => item.dismissals),
          borderColor: "#2f58a7",
          pointRadius: 0,
          borderWidth: 3,
        },
      ],
    },

    options,
  });

  balanceChart = new Chart($("#balance-chart"), {
    type: "bar",

    data: {
      labels,

      datasets: [
        {
          label: "Saldo",
          data: seriesData.map((item) => item.balance),
          backgroundColor: "#222a80",
          maxBarThickness: 16,
        },
      ],
    },

    options,
    plugins: [values],
  });
}

boot();
