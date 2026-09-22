import { createClient } from '@supabase/supabase-js';
import Chart from 'chart.js/auto';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

const territory = document.querySelector('#territory');
const municipality = document.querySelector('#municipality');
const sectionFilter = document.querySelector('#section-filter');
const sexFilter = document.querySelector('#sex-filter');
const periodSummary = document.querySelector('#period-summary');
const periodTree = document.querySelector('#period-tree');
const status = document.querySelector('#update-status');

let officialRows = [];
let detailRows = [];
let regionalCodes = new Set();
let selectedCompetence = '';
let expandedYear = '';
let officialSourceNote = '';
let trendChart;
let balanceChart;

const formatter = new Intl.NumberFormat('pt-BR');

const sum = (items, field) =>
  items.reduce(
    (total, item) => total + (Number(item[field]) || 0),
    0,
  );

const periodLabel = value =>
  new Intl.DateTimeFormat('pt-BR', {
    month: 'long',
    year: 'numeric',
  }).format(new Date(`${value}T12:00:00`));

const monthName = value =>
  new Intl.DateTimeFormat('pt-BR', {
    month: 'long',
  }).format(new Date(`${value}T12:00:00`));

const barValueLabels = {
  id: 'barValueLabels',

  afterDatasetsDraw(chart) {
    if (chart.config.type !== 'bar') return;

    const dataset = chart.data.datasets[0];
    const meta = chart.getDatasetMeta(0);
    const { ctx } = chart;

    ctx.save();
    ctx.fillStyle = '#666';
    ctx.font = '10px Aptos, Arial, sans-serif';
    ctx.textAlign = 'center';

    meta.data.forEach((bar, index) => {
      const value = Number(dataset.data[index]) || 0;
      const position = bar.getProps(['x', 'y'], true);

      ctx.textBaseline = value >= 0 ? 'bottom' : 'top';

      ctx.fillText(
        formatter.format(value),
        position.x,
        position.y + (value >= 0 ? -6 : 6),
      );
    });

    ctx.restore();
  },
};

async function fetchPaged(query) {
  const all = [];

  for (let start = 0; ; start += 1000) {
    const { data, error } = await query.range(start, start + 999);

    if (error) throw error;

    all.push(...(data || []));

    if (!data || data.length < 1000) {
      return all;
    }
  }
}

async function boot() {
  if (!supabaseUrl || !supabaseKey) {
    fail(
      'As credenciais públicas do Supabase não foram configuradas no Vercel.',
    );
    return;
  }

  try {
    const supabase = createClient(supabaseUrl, supabaseKey);

    const municipalities = await fetchPaged(
      supabase
        .from('municipalities')
        .select('ibge_code,name,is_regional')
        .eq('is_regional', true)
        .order('name'),
    );

    regionalCodes = new Set(
      municipalities.map(item => item.ibge_code),
    );

    if (!regionalCodes.size) {
      throw new Error(
        'Nenhum município da Região Administrativa de Araçatuba foi encontrado.',
      );
    }

    const codes = [...regionalCodes];

    const [official, detailed, imports] = await Promise.all([
      fetchPaged(
        supabase
          .from('caged_official_monthly')
          .select('competence,ibge_code,stock,admissions,dismissals,balance')
          .in('ibge_code', codes)
          .order('competence'),
      ),

      fetchPaged(
        supabase
          .from('caged_monthly')
          .select(
            'competence,ibge_code,cnae_section,sex,age_band,education,admissions,dismissals,balance',
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
      throw new Error(
        'A Tabela 8.1 ainda não possui dados para a Região Administrativa de Araçatuba.',
      );
    }

    municipalities.forEach(item => {
      municipality.add(
        new Option(item.name, item.ibge_code),
      );
    });

    populateDetailFilters();

    selectedCompetence =
      availableCompetences().at(-1) || '';

    expandedYear = selectedCompetence.slice(0, 4);

    if (imports.data?.[0]) {
      officialSourceNote =
        'Fonte: Novo CAGED — Ministério do Trabalho e Emprego. ' +
        `Série oficial atualizada até ${periodLabel(
          imports.data[0].competence_end,
        )}.`;
    }

    [
      territory,
      municipality,
      sectionFilter,
      sexFilter,
    ].forEach(control => {
      control.addEventListener('change', render);
    });

    periodSummary.addEventListener('click', () => {
      const hidden = periodTree.hidden;

      periodTree.hidden = !hidden;

      periodSummary.setAttribute(
        'aria-expanded',
        String(hidden),
      );
    });

    renderPeriodTree();
    render();
  } catch (error) {
    fail(error.message);
  }
}

function populateDetailFilters() {
  const sections = [
    ...new Set(
      detailRows
        .map(row => row.cnae_section)
        .filter(Boolean),
    ),
  ].sort((a, b) => a.localeCompare(b, 'pt-BR'));

  sections.forEach(value => {
    sectionFilter.add(new Option(value, value));
  });

  const sexes = [
    'Masculino',
    'Feminino',
    'Não informado',
  ].filter(value =>
    detailRows.some(row => row.sex === value),
  );

  sexes.forEach(value => {
    sexFilter.add(new Option(value, value));
  });
}

function availableCompetences() {
  return [
    ...new Set(
      officialRows.map(row => row.competence),
    ),
  ].sort();
}

function renderPeriodTree() {
  const years = new Map();

  availableCompetences().forEach(value => {
    const year = value.slice(0, 4);

    if (!years.has(year)) {
      years.set(year, []);
    }

    years.get(year).push(value);
  });

  periodSummary.innerHTML =
    `${selectedCompetence.slice(0, 4)} (Ano) + ` +
    `${monthName(selectedCompetence)} (Mês)` +
    '<span>⌃</span>';

  periodTree.replaceChildren();

  [...years.entries()].forEach(([year, months]) => {
    const yearRow = document.createElement('button');

    yearRow.type = 'button';
    yearRow.className = 'period-year';

    yearRow.innerHTML =
      `<span class="tree-arrow">${
        expandedYear === year ? '⌄' : '›'
      }</span>` +
      `<span class="box${
        selectedCompetence.startsWith(year)
          ? ' partial'
          : ''
      }"></span>` +
      `<span>${year}</span>`;

    yearRow.addEventListener('click', () => {
      expandedYear =
        expandedYear === year ? '' : year;

      renderPeriodTree();
    });

    periodTree.append(yearRow);

    if (expandedYear !== year) return;

    const monthWrap = document.createElement('div');

    monthWrap.className = 'period-months';

    months.forEach(value => {
      const monthRow = document.createElement('button');

      monthRow.type = 'button';

      monthRow.className =
        `period-month${
          value === selectedCompetence
            ? ' selected'
            : ''
        }`;

      monthRow.innerHTML =
        `<span class="box${
          value === selectedCompetence
            ? ' checked'
            : ''
        }">${
          value === selectedCompetence
            ? '✓'
            : ''
        }</span>` +
        `<span>${monthName(value)}</span>`;

      monthRow.addEventListener('click', () => {
        selectedCompetence = value;

        periodTree.hidden = true;

        periodSummary.setAttribute(
          'aria-expanded',
          'false',
        );

        renderPeriodTree();
        render();
      });

      monthWrap.append(monthRow);
    });

    periodTree.append(monthWrap);
  });
}

function hasDetailFilters() {
  return (
    sectionFilter.value !== 'all' ||
    sexFilter.value !== 'all'
  );
}

function filteredRows() {
  const source = hasDetailFilters()
    ? detailRows
    : officialRows;

  return source.filter(row => {
    const placeMatches =
      municipality.value === 'regional'
        ? regionalCodes.has(row.ibge_code)
        : row.ibge_code === municipality.value;

    const sectionMatches =
      sectionFilter.value === 'all' ||
      row.cnae_section === sectionFilter.value;

    const sexMatches =
      sexFilter.value === 'all' ||
      row.sex === sexFilter.value;

    return (
      row.competence <= selectedCompetence &&
      placeMatches &&
      sectionMatches &&
      sexMatches
    );
  });
}

function render() {
  const selected = filteredRows();

  const current = selected.filter(
    row => row.competence === selectedCompetence,
  );

  if (!current.length) {
    ['admissions', 'dismissals', 'balance', 'stock']
      .forEach(id => setText(id, '—'));

    renderTrend([]);
    renderBalance([]);

    status.textContent = hasDetailFilters()
      ? 'Não há microdados importados para esta competência com os filtros escolhidos. Grande Grupamento e Sexo dependem dos microdados de cada mês.'
      : 'Não há dados para essa seleção.';

    return;
  }

  setText(
    'admissions',
    formatter.format(sum(current, 'admissions')),
  );

  setText(
    'dismissals',
    formatter.format(sum(current, 'dismissals')),
  );

  const balance = sum(current, 'balance');

  setText(
    'balance',
    `${balance > 0 ? '+' : ''}${formatter.format(balance)}`,
  );

  setText(
    'stock',
    hasDetailFilters()
      ? '—'
      : formatter.format(sum(current, 'stock')),
  );

  const series = aggregateByCompetence(selected);

  renderTrend(series);
  renderBalance(series);

  status.textContent = hasDetailFilters()
    ? 'Fonte dos filtros detalhados: microdados do Novo CAGED. Estoque não é calculável a partir de movimentações mensais isoladas.'
    : officialSourceNote;
}

function aggregateByCompetence(data) {
  return [
    ...new Set(data.map(row => row.competence)),
  ]
    .sort()
    .map(competence => {
      const monthRows = data.filter(
        row => row.competence === competence,
      );

      return {
        competence,
        admissions: sum(monthRows, 'admissions'),
        dismissals: sum(monthRows, 'dismissals'),
        balance: sum(monthRows, 'balance'),
      };
    });
}

function chartLabels(series) {
  return series.map((item, index) => {
    const year = item.competence.slice(0, 4);

    const priorYear = index
      ? series[index - 1].competence.slice(0, 4)
      : '';

    return year !== priorYear ? year : '';
  });
}

function renderTrend(series) {
  trendChart?.destroy();

  trendChart = new Chart(
    document.querySelector('#trend'),
    {
      type: 'line',

      data: {
        labels: chartLabels(series),

        datasets: [
          {
            label: 'Admitidos',
            data: series.map(item => item.admissions),
            borderColor: '#222a80',
            backgroundColor: '#222a80',
            pointRadius: 0,
            pointHoverRadius: 0,
            borderWidth: 3,
            tension: 0,
          },
          {
            label: 'Desligados',
            data: series.map(item => item.dismissals),
            borderColor: '#2f58a7',
            backgroundColor: '#2f58a7',
            pointRadius: 0,
            pointHoverRadius: 0,
            borderWidth: 3,
            tension: 0,
          },
        ],
      },

      options: chartOptions('line', series),
    },
  );
}

function renderBalance(series) {
  balanceChart?.destroy();

  balanceChart = new Chart(
    document.querySelector('#balance-chart'),
    {
      type: 'bar',

      data: {
        labels: chartLabels(series),

        datasets: [
          {
            label: 'Saldo',
            data: series.map(item => item.balance),
            backgroundColor: '#222a80',
            borderRadius: 0,
            maxBarThickness: 16,
          },
        ],
      },

      options: chartOptions('bar', series),

      plugins: [barValueLabels],
    },
  );
}

function chartOptions(type, series) {
  return {
    responsive: true,
    maintainAspectRatio: false,

    plugins: {
      legend: {
        position: 'top',

        labels: {
          usePointStyle: true,
          pointStyle: 'circle',
          boxWidth: 8,
          color: '#4c4c4c',
          font: { size: 13 },
        },
      },

      tooltip: {
        callbacks: {
          title: items =>
            periodLabel(
              series[items[0].dataIndex].competence,
            ),
        },
      },
    },

    scales: {
      x: {
        grid: { display: false },

        ticks: {
          color: '#666',
          maxRotation: 0,
          autoSkip: false,
          font: { size: 12 },
        },

        title: {
          display: type === 'line',
          text: 'Ano',
          color: '#4c4c4c',
        },
      },

      y: {
        grid: {
          color: '#e5e5e5',
          borderDash: [2, 4],
        },

        ticks: {
          color: '#666',
          callback: value => formatter.format(value),
        },
      },
    },
  };
}

function setText(id, value) {
  document.querySelector(`#${id}`).textContent = value;
}

function fail(message) {
  status.textContent = message;
}

boot();
