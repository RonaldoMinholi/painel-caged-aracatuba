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

const territory = $("#territory"), periodSummary = $("#period-summary"), periodTree = $("#period-tree"), municipalityFilter = $("#municipality"), municipalitySearch = $("#municipality-search"), ufFilter = $("#uf-filter"), sectionFilter = $("#section-filter"), sexFilter = $("#sex-filter"), status = $("#update-status");
let supabase, municipalities = [], regionalMunicipalities = [], nationalSeries = [], selectedCompetences = new Set(), selectedMunicipalities = new Set(), selectedUfs = new Set(), selectedSections = new Set(), selectedSexes = new Set(), expandedYear = "", sourceNote = "", trendChart, balanceChart, renderRequest = 0, mapRequest = 0, renderTimer;
let redrawUf = () => {}, redrawSections = () => {}, redrawSexes = () => {};

const labelsPlugin = {
  id: "barValueLabels",
  afterDatasetsDraw(chart) {
    if (chart.config.type !== "bar") return;
    const ctx = chart.ctx, data = chart.data.datasets[0], meta = chart.getDatasetMeta(0);
    ctx.save();
    ctx.fillStyle = "#666";
    ctx.font = "10px Aptos, Arial";
    ctx.textAlign = "center";
    meta.data.forEach((bar, index) => {
      const value = Number(data.data[index]) || 0;
      const point = bar.getProps(["x", "y"], true);
      ctx.textBaseline = value >= 0 ? "bottom" : "top";
      ctx.fillText(fmt.format(value), point.x, point.y + (value >= 0 ? -6 : 6));
    });
    ctx.restore();
  }
};

const scheduleRender = () => {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(render, 140);
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

function drawMap() {
  $("#brazil-map").innerHTML = `
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

function paintMap(balances) {
  const max = Math.max(0, ...balances.values());

  brazil.locations.forEach((state) => {
    const path = document.querySelector(`#brazil-map path[data-state="${state.id}"]`);
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
  input.onchange = () => change(input.checked);

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
      check(box, label, selected.has(value), (on) => {
        on ? selected.add(value) : selected.delete(value);
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
    check(box, row.name, selectedMunicipalities.has(row.ibge_code), (on) => {
      on ? selectedMunicipalities.add(row.ibge_code) : selectedMunicipalities.delete(row.ibge_code);
      drawMunicipalityFilter();
      scheduleRender();
    });
  });

  summary.textContent = !selectedMunicipalities.size
    ? "Todos"
    : selectedMunicipalities.size === 1
      ? (municipalities.find((row) => selectedMunicipalities.has(row.ibge_code))?.name || "1 selecionado")
      : `${selectedMunicipalities.size} selecionados`;
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

    input.onchange = () => {
      list.forEach((v) => {
        input.checked ? selectedCompetences.add(v) : selectedCompetences.delete(v);
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

      inputMonth.onchange = () => {
        inputMonth.checked
          ? selectedCompetences.add(value)
          : selectedCompetences.delete(value);

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
  if (
    territory.value === "national" &&
    !selectedMunicipalities.size &&
    !selectedUfs.size
  ) {
    return nationalSeries;
  }

  const { data, error } = await supabase.rpc("caged_official_series", {
    p_ibge_codes: currentCodes(),
    p_uf_codes: currentUfs()
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
  $("#balance").textContent = `${balance > 0 ? "+" : ""}${fmt.format(balance)}`;
  $("#stock").textContent =
    granular || selected.size !== 1
      ? "—"
      : fmt.format(sum(cards, "s"));

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
          boxWidth: 34,
          boxHeight: 10,
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
          pointRadius: 0,
          borderWidth: 3
        },
        {
          label: "Desligados",
          data: data.map((r) => r.d),
          borderColor: "#2f58a7",
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

async function render() {
  const request = ++renderRequest;

  try {
    const granular = selectedSections.size > 0 || selectedSexes.size > 0;

    const mode =
      territory.value === "regional" && granular
        ? "detail"
        : territory.value === "national" && granular
          ? "cube"
          : "official";

    const history =
      mode === "detail"
        ? await detailedSeries()
        : mode === "cube"
          ? await cubeSeries()
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
  }
}

async function boot() {
  try {
    drawMap();

    if (!import.meta.env.VITE_SUPABASE_URL) {
      throw Error("As credenciais públicas do Supabase não foram configuradas no Vercel.");
    }

    supabase = createClient(
      import.meta.env.VITE_SUPABASE_URL,
      import.meta.env.VITE_SUPABASE_ANON_KEY
    );

    const [
      municipalityResponse,
      nationalResponse,
      importsResponse
    ] = await Promise.all([
      supabase.rpc("caged_municipalities"),
      supabase.rpc("caged_official_series", {
        p_ibge_codes: null,
        p_uf_codes: null
      }),
      supabase
        .from("caged_official_imports")
        .select("competence_end")
        .order("competence_end", { ascending: false })
        .limit(1)
    ]);

    if (municipalityResponse.error) throw municipalityResponse.error;
    if (nationalResponse.error) throw nationalResponse.error;

    municipalities = municipalityResponse.data || [];
    regionalMunicipalities = municipalities.filter((row) => row.is_regional);

    nationalSeries = (nationalResponse.data || []).map((row) => ({
      c: row.competence,
      a: Number(row.admissions) || 0,
      d: Number(row.dismissals) || 0,
      b: Number(row.balance) || 0,
      s: Number(row.stock) || 0
    }));

    if (!nationalSeries.length) {
      throw Error("A Tabela 8.1 ainda não possui dados.");
    }

    sourceNote = importsResponse.data?.[0]
      ? `Fonte: Novo CAGED — Ministério do Trabalho e Emprego. Série oficial atualizada até ${periodName(importsResponse.data[0].competence_end)}.`
      : "Fonte: Novo CAGED — Ministério do Trabalho e Emprego.";

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
    };

    document.addEventListener("pointerdown", closeFilters);

    updateScope();
    drawPeriodTree();
    render();
  } catch (error) {
    status.textContent = error.message;
  }
}

boot();
