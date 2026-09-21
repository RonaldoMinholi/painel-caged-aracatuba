import { createClient } from '@supabase/supabase-js';
import Chart from 'chart.js/auto';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const territory = document.querySelector('#territory');
const municipality = document.querySelector('#municipality');
const periodSummary = document.querySelector('#period-summary');
const periodTree = document.querySelector('#period-tree');

let rows = [];
let regionalCodes = new Set();
let municipalityNames = new Map();
let selectedCompetence = '';
let expandedYear = '';
let trendChart;
let balanceChart;

const formatter = new Intl.NumberFormat('pt-BR');
const sum = (items, field) =>
  items.reduce((total, item) => total + (Number(item[field]) || 0), 0);

const periodLabel = value =>
  new Intl.DateTimeFormat('pt-BR', {
    month: 'long',
    year: 'numeric'
  }).format(new Date(`${value}T12:00:00`));

const monthName = value =>
  new Intl.DateTimeFormat('pt-BR', {
    month: 'long'
  }).format(new Date(`${value}T12:00:00`));

async function fetchRegionalRows(supabase, codes) {
  const pageSize = 1000;
  const all = [];

  for (let start = 0; ; start += pageSize) {
    const { data, error } = await supabase
      .from('caged_official_monthly')
      .select('competence,ibge_code,stock,admissions,dismissals,balance')
      .in('ibge_code', codes)
      .order('competence')
      .range(start, start + pageSize - 1);

    if (error) throw error;

    all.push(...(data || []));

    if (!data || data.length < pageSize) return all;
  }
}

async function fetchMunicipalities(supabase) {
  const pageSize = 1000;
  const all = [];

  for (let start = 0; ; start += pageSize) {
    const { data, error } = await supabase
      .from('municipalities')
      .select('ibge_code,name,is_regional')
      .order('name')
      .range(start, start + pageSize - 1);

    if (error) throw error;

    all.push(...(data || []));

    if (!data || data.length < pageSize) return all;
  }
}

async function boot() {
  if (!supabaseUrl || !supabaseKey) {
    return fail(
      'As credenciais públicas do Supabase não foram configuradas no Vercel.'
    );
  }

  try {
    const supabase = createClient(supabaseUrl, supabaseKey);

    const [municipalities, importsResult] = await Promise.all([
      fetchMunicipalities(supabase),
      supabase
        .from('caged_official_imports')
        .select('competence_end')
        .order('competence_end', { ascending: false })
        .limit(1)
    ]);

    if (importsResult.error) throw importsResult.error;

    regionalCodes = new Set(
      municipalities
        .filter(item => item.is_regional)
        .map(item => item.ibge_code)
    );

    municipalityNames = new Map(
      municipalities.map(item => [item.ibge_code, item.name])
    );

    if (!regionalCodes.size) {
      throw new Error(
        'Nenhum município da Região Administrativa de Araçatuba foi encontrado.'
      );
    }

    rows = await fetchRegionalRows(supabase, [...regionalCodes]);

    if (!rows.length) {
      throw new Error(
        'A Tabela 8.1 ainda não possui dados para a Região Administrativa de Araçatuba.'
      );
    }

    municipalities
      .filter(item => item.is_regional)
      .forEach(item => {
        municipality.add(new Option(item.name, item.ibge_code));
      });

    const competences = availableCompetences();

    selectedCompetence = competences.at(-1) || '';
    expandedYear = selectedCompetence.slice(0, 4);

    if (importsResult.data?.[0]) {
      document.querySelector('#update-status').textContent =
        `Fonte: Novo CAGED — Ministério do Trabalho e Emprego. ` +
        `Série oficial atualizada até ${periodLabel(
          importsResult.data[0].competence_end
        )}.`;
    }

    territory.addEventListener('change', render);
    municipality.addEventListener('change', render);

    periodSummary.addEventListener('click', () => {
      const isHidden = periodTree.hidden;

      periodTree.hidden = !isHidden;
      periodSummary.setAttribute('aria-expanded', String(isHidden));
    });

    renderPeriodTree();
    render();
  } catch (error) {
    fail(error.message);
  }
}

function availableCompetences() {
  return [
    ...new Set(
      rows
        .filter(row => regionalCodes.has(row.ibge_code))
        .map(row => row.competence)
    )
  ].sort();
}

function renderPeriodTree() {
  const years = new Map();

  availableCompetences().forEach(value => {
    const year = value.slice(0, 4);

    if (!years.has(year)) years.set(year, []);

    years.get(year).push(value);
  });

  periodSummary.innerHTML =
    `${selectedCompetence.slice(0, 4)} (Ano) + ` +
    `${monthName(selectedCompetence)} (Mês)<span>⌃</span>`;

  periodTree.replaceChildren();

  [...years.entries()].forEach(([year, months]) => {
    const yearRow = document.createElement('button');

    yearRow.type = 'button';
    yearRow.className = 'period-year';

    yearRow.innerHTML =
      `<span class="tree-arrow">${expandedYear === year ? '⌄' : '›'}</span>` +
      `<span class="box${
        selectedCompetence.startsWith(year) ? ' partial' : ''
      }"></span>` +
      `<span>${year}</span>`;

    yearRow.addEventListener('click', () => {
      expandedYear = expandedYear === year ? '' : year;
      renderPeriodTree();
    });

    periodTree.append(yearRow);

    if (expandedYear === year) {
      const monthWrap = document.createElement('div');

      monthWrap.className = 'period-months';

      months.forEach(value => {
        const monthRow = document.createElement('button');

        monthRow.type = 'button';
        monthRow.className =
          `period-month${value === selectedCompetence ? ' selected' : ''}`;

        monthRow.innerHTML =
          `<span class="box${
            value === selectedCompetence ? ' checked' : ''
          }">${value === selectedCompetence ? '✓' : ''}</span>` +
          `<span>${monthName(value)}</span>`;

        monthRow.addEventListener('click', () => {
          selectedCompetence = value;
          periodTree.hidden = true;
          periodSummary.setAttribute('aria-expanded', 'false');
          renderPeriodTree();
          render();
        });

        monthWrap.append(monthRow);
      });

      periodTree.append(monthWrap);
    }
  });
}

function filteredRows() {
  const selectedPlace = municipality.value;

  return rows.filter(row =>
    row.competence <= selectedCompetence &&
    (
      selectedPlace === 'regional'
        ? regionalCodes.has(row.ibge_code)
        : row.ibge_code === selectedPlace
    )
  );
}

function render() {
  const selected = filteredRows();
  const current = selected.filter(
    row => row.competence === selectedCompetence
  );

  if (!current.length) {
    return fail('Não há dados para essa seleção.');
  }

  setText('admissions', formatter.format(sum(current, 'admissions')));
  setText('dismissals', formatter.format(sum(current, 'dismissals')));

  const balance = sum(current, 'balance');

  setText(
    'balance',
    `${balance > 0 ? '+' : ''}${formatter.format(balance)}`
  );

  setText('stock', formatter.format(sum(current, 'stock')));

  const series = aggregateByCompetence(selected);

  renderTrend(series);
  renderBalance(series);
}

function aggregateByCompetence(data) {
  return [...new Set(data.map(row => row.competence))]
    .sort()
    .map(competence => {
      const monthRows = data.filter(row => row.competence === competence);

      return {
        competence,
        admissions: sum(monthRows, 'admissions'),
        dismissals: sum(monthRows, 'dismissals'),
        balance: sum(monthRows, 'balance')
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

  trendChart = new Chart(document.querySelector('#trend'), {
    type: 'line',
    data: {
      labels: chartLabels(series),
      datasets: [
        {
          label: 'Admitidos',
          data: series.map(item => item.admissions),
          borderColor: '#222a80',
          backgroundColor: '#222a80',
          pointRadius: 2.8,
          pointHoverRadius: 4,
          borderWidth: 3,
          tension: 0
        },
        {
          label: 'Desligados',
          data: series.map(item => item.dismissals),
          borderColor: '#2f58a7',
          backgroundColor: '#2f58a7',
          pointRadius: 2.8,
          pointHoverRadius: 4,
          borderWidth: 3,
          tension: 0
        }
      ]
    },
    options: chartOptions('line')
  });
}

function renderBalance(series) {
  balanceChart?.destroy();

  balanceChart = new Chart(document.querySelector('#balance-chart'), {
    type: 'bar',
    data: {
      labels: chartLabels(series),
      datasets: [
        {
          label: 'Saldo',
          data: series.map(item => item.balance),
          backgroundColor: '#222a80',
          borderRadius: 0,
          maxBarThickness: 19
        }
      ]
    },
    options: chartOptions('bar')
  });
}

function chartOptions(type) {
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
          font: { size: 13 }
        }
      },
      tooltip: {
        callbacks: {
          title: items => {
            const series = aggregateByCompetence(filteredRows());

            return periodLabel(series[items[0].dataIndex].competence);
          }
        }
      }
    },
    scales: {
      x: {
        grid: { display: false },
        ticks: {
          color: '#666',
          maxRotation: 0,
          autoSkip: false,
          font: { size: 12 }
        },
        title: {
          display: type === 'line',
          text: 'Ano',
          color: '#4c4c4c'
        }
      },
      y: {
        grid: {
          color: '#e5e5e5',
          borderDash: [2, 4]
        },
        ticks: {
          color: '#666',
          callback: value => formatter.format(value)
        }
      }
    }
  };
}

function setText(id, value) {
  document.querySelector(`#${id}`).textContent = value;
}

function fail(message) {
  document.querySelector('#update-status').textContent = message;
}

boot();
