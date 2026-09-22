import { createClient } from '@supabase/supabase-js';
import Chart from 'chart.js/auto';

const $ = selector => document.querySelector(selector);

const fmt = new Intl.NumberFormat('pt-BR');

const sum = (rows, field) =>
  rows.reduce((total, row) => total + (+row[field] || 0), 0);

const date = value => new Date(`${value}T12:00:00`);

const month = value =>
  new Intl.DateTimeFormat('pt-BR', { month: 'long' }).format(date(value));

const label = value =>
  new Intl.DateTimeFormat('pt-BR', {
    month: 'long',
    year: 'numeric',
  }).format(date(value));

const territory = $('#territory');
const municipalityFilter = $('#municipality');
const sectionFilter = $('#section-filter');
const sexFilter = $('#sex-filter');
const periodSummary = $('#period-summary');
const periodTree = $('#period-tree');
const status = $('#update-status');

let officialRows = [];
let detailRows = [];
let municipalities = [];

let selectedCompetences = new Set();
let selectedMunicipalities = new Set();
let selectedSections = new Set();
let selectedSexes = new Set();

let expandedYear = '';
let sourceNote = '';
let trendChart;
let balanceChart;

const values = {
  id: 'barValueLabels',

  afterDatasetsDraw(chart) {
    if (chart.config.type !== 'bar') return;

    const dataset = chart.data.datasets[0];
    const meta = chart.getDatasetMeta(0);
    const context = chart.ctx;

    context.save();
    context.fillStyle = '#666';
    context.font = '10px Aptos, Arial';
    context.textAlign = 'center';

    meta.data.forEach((bar, index) => {
      const value = +dataset.data[index] || 0;
      const position = bar.getProps(['x', 'y'], true);

      context.textBaseline = value >= 0 ? 'bottom' : 'top';
      context.fillText(
        fmt.format(value),
        position.x,
        position.y + (value >= 0 ? -6 : 6),
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

async function boot() {
  try {
    if (!import.meta.env.VITE_SUPABASE_URL) {
      throw Error(
        'As credenciais públicas do Supabase não foram configuradas no Vercel.',
      );
    }

    const supabase = createClient(
      import.meta.env.VITE_SUPABASE_URL,
      import.meta.env.VITE_SUPABASE_ANON_KEY,
    );

    municipalities = await pages(
      supabase
        .from('municipalities')
        .select('ibge_code,name,is_regional')
        .eq('is_regional', true)
        .order('name'),
    );

    const codes = municipalities.map(item => item.ibge_code);

    const [official, detailed, importInfo] = await Promise.all([
      pages(
        supabase
          .from('caged_official_monthly')
          .select('competence,ibge_code,stock,admissions,dismissals,balance')
          .in('ibge_code', codes)
          .order('competence'),
      ),

      pages(
        supabase
          .from('caged_monthly')
          .select(
            'competence,ibge_code,cnae_section,sex,admissions,dismissals,balance',
          )
          .in('ibge_code', codes)
          .order('competence'),
      ),

      supabase
        .from('caged_official_imports')
        .select('competence_end')
        .order('competence_end', { ascending: false })
        .limit(1),
    ]);

    officialRows = official;
    detailRows = detailed;

    if (!officialRows.length) {
      throw Error('A Tabela 8.1 ainda não possui dados.');
    }

    selectedCompetences.add(months().at(-1));
    expandedYear = months().at(-1).slice(0, 4);

    multi(
      municipalityFilter,
      municipalities.map(item => [item.ibge_code, item.name]),
      selectedMunicipalities,
    );

    multi(
      sectionFilter,
      [...new Set(detailRows.map(item => item.cnae_section).filter(Boolean))]
        .sort()
        .map(item => [item, item]),
      selectedSections,
    );

    multi(
      sexFilter,
      ['Masculino', 'Feminino', 'Não informado'].map(item => [item, item]),
      selectedSexes,
    );

    sourceNote = importInfo.data?.[0]
      ? `Fonte: Novo CAGED — Ministério do Trabalho e Emprego. Série oficial atualizada até ${label(importInfo.data[0].competence_end)}.`
      : '';

    territory.addEventListener('change', render);

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
  return [...new Set(officialRows.map(row => row.competence))].sort();
}

function multi(element, options, selected) {
  const box = element.querySelector('.multi-options');
  const summary = element.querySelector('summary');

  function draw() {
    box.replaceChildren();

    const all = check(box, 'Todos', !selected.size, checked => {
      if (checked) selected.clear();
      draw();
      render();
    });

    all.indeterminate = !!selected.size;

    options.forEach(([value, name]) => {
      check(box, name, selected.has(value), checked => {
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
      ? 'Todos'
      : selected.size === 1
        ? options.find(item => selected.has(item[0]))?.[1] || '1 selecionado'
        : `${selected.size} selecionados`;
  }

  draw();
}

function check(parent, text, checked, onChange) {
  const label = document.createElement('label');
  const input = document.createElement('input');

  label.className = 'multi-option';

  input.type = 'checkbox';
  input.checked = checked;
  input.onchange = () => onChange(input.checked);

  label.append(input, document.createTextNode(text));
  parent.append(label);

  return input;
}

function tree() {
  const groups = {};

  months().forEach(competence => {
    const year = competence.slice(0, 4);
    groups[year] ??= [];
    groups[year].push(competence);
  });

  const chosen = [...selectedCompetences];

  periodSummary.innerHTML =
    chosen.length === 1
      ? `${chosen[0].slice(0, 4)} (Ano) + ${month(chosen[0])} (Mês)<span>⌃</span>`
      : chosen.length
        ? `${chosen.length} meses selecionados<span>⌃</span>`
        : `Todos os meses<span>⌃</span>`;

  periodTree.replaceChildren();

  Object.entries(groups).forEach(([year, list]) => {
    const row = document.createElement('div');
    row.className = 'period-year';

    const expand = document.createElement('button');
    expand.className = 'tree-arrow';
    expand.textContent = expandedYear === year ? '⌄' : '›';

    expand.onclick = () => {
      expandedYear = expandedYear === year ? '' : year;
      tree();
    };

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = list.every(item => selectedCompetences.has(item));
    checkbox.indeterminate =
      !checkbox.checked && list.some(item => selectedCompetences.has(item));

    checkbox.onchange = () => {
      list.forEach(item => {
        if (checkbox.checked) {
          selectedCompetences.add(item);
        } else {
          selectedCompetences.delete(item);
        }
      });

      tree();
      render();
    };

    row.append(expand, checkbox, document.createTextNode(year));
    periodTree.append(row);

    if (expandedYear !== year) return;

    const monthsWrapper = document.createElement('div');
    monthsWrapper.className = 'period-months';

    list.forEach(competence => {
      const item = document.createElement('label');
      const checkbox = document.createElement('input');

      item.className = 'period-month';

      checkbox.type = 'checkbox';
      checkbox.checked = selectedCompetences.has(competence);

      checkbox.onchange = () => {
        if (checkbox.checked) {
          selectedCompetences.add(competence);
        } else {
          selectedCompetences.delete(competence);
        }

        tree();
        render();
      };

      item.append(checkbox, document.createTextNode(month(competence)));
      monthsWrapper.append(item);
    });

    periodTree.append(monthsWrapper);
  });
}

function filtered() {
  const detailedFiltering = selectedSections.size || selectedSexes.size;
  const source = detailedFiltering ? detailRows : officialRows;

  const selectedMonths = selectedCompetences.size
    ? selectedCompetences
    : new Set(months());

  return [
    source.filter(row =>
      selectedMonths.has(row.competence) &&
      (!selectedMunicipalities.size ||
        selectedMunicipalities.has(row.ibge_code)) &&
      (!selectedSections.size ||
        selectedSections.has(row.cnae_section)) &&
      (!selectedSexes.size || selectedSexes.has(row.sex)),
    ),
    detailedFiltering,
  ];
}

function render() {
  const [rows, detailedFiltering] = filtered();

  if (!rows.length) {
    ['admissions', 'dismissals', 'balance', 'stock'].forEach(id => {
      $(`#${id}`).textContent = '—';
    });

    chart([]);
    status.textContent = 'Não há dados para essa combinação.';
    return;
  }

  $('#admissions').textContent = fmt.format(sum(rows, 'admissions'));
  $('#dismissals').textContent = fmt.format(sum(rows, 'dismissals'));

  const balance = sum(rows, 'balance');
  $('#balance').textContent = `${balance > 0 ? '+' : ''}${fmt.format(balance)}`;

  $('#stock').textContent =
    detailedFiltering || selectedCompetences.size !== 1
      ? '—'
      : fmt.format(sum(rows, 'stock'));

  const series = [...new Set(rows.map(row => row.competence))]
    .sort()
    .map(competence => {
      const rowsByMonth = rows.filter(row => row.competence === competence);

      return {
        competence,
        admissions: sum(rowsByMonth, 'admissions'),
        dismissals: sum(rowsByMonth, 'dismissals'),
        balance: sum(rowsByMonth, 'balance'),
      };
    });

  chart(series);

  status.textContent = detailedFiltering
    ? 'Fonte: microdados do Novo CAGED. Estoque só é exibido sem filtros detalhados e para um mês.'
    : sourceNote;
}

function chart(series = []) {
  const labels = series.map((item, index) =>
    item.competence.slice(0, 4) !==
    (index ? series[index - 1].competence.slice(0, 4) : '')
      ? item.competence.slice(0, 4)
      : '',
  );

  const options = {
    responsive: true,
    maintainAspectRatio: false,

    plugins: {
      legend: {
        position: 'top',
      },

      tooltip: {
        callbacks: {
          title: items => label(series[items[0].dataIndex].competence),
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
          callback: value => fmt.format(value),
        },
      },
    },
  };

  trendChart?.destroy();
  balanceChart?.destroy();

  trendChart = new Chart($('#trend'), {
    type: 'line',

    data: {
      labels,

      datasets: [
        {
          label: 'Admitidos',
          data: series.map(item => item.admissions),
          borderColor: '#222a80',
          pointRadius: 0,
          borderWidth: 3,
        },

        {
          label: 'Desligados',
          data: series.map(item => item.dismissals),
          borderColor: '#2f58a7',
          pointRadius: 0,
          borderWidth: 3,
        },
      ],
    },

    options,
  });

  balanceChart = new Chart($('#balance-chart'), {
    type: 'bar',

    data: {
      labels,

      datasets: [
        {
          label: 'Saldo',
          data: series.map(item => item.balance),
          backgroundColor: '#222a80',
          maxBarThickness: 16,
        },
      ],
    },

    options,
    plugins: [values],
  });
}

boot();
