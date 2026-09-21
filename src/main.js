import { createClient } from '@supabase/supabase-js';
import Chart from 'chart.js/auto';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

const territory = document.querySelector('#territory');
const competence = document.querySelector('#competence');

let trendChart;
let rows = [];
let municipalityNames = new Map();

const number = value =>
  new Intl.NumberFormat('pt-BR').format(value || 0);

const monthLabel = value =>
  new Intl.DateTimeFormat('pt-BR', {
    month: 'long',
    year: 'numeric',
  }).format(new Date(`${value}T12:00:00`));

const sum = (items, field) =>
  items.reduce(
    (total, item) => total + (Number(item[field]) || 0),
    0,
  );

async function boot() {
  if (!supabaseUrl || !supabaseKey) {
    return showConfigError();
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  const [
    { data: officialRows, error },
    { data: municipalities, error: municipalitiesError },
    { data: imports },
  ] = await Promise.all([
    supabase
      .from('caged_official_monthly')
      .select('competence,ibge_code,stock,admissions,dismissals,balance')
      .order('competence'),

    supabase
      .from('municipalities')
      .select('ibge_code,name')
      .order('name'),

    supabase
      .from('caged_official_imports')
      .select('competence_end,imported_at')
      .order('competence_end', { ascending: false })
      .limit(1),
  ]);

  if (error || municipalitiesError) {
    return showError((error || municipalitiesError).message);
  }

  rows = officialRows || [];

  municipalityNames = new Map(
    (municipalities || []).map(item => [item.ibge_code, item.name]),
  );

  for (const [code, name] of municipalityNames) {
    territory.add(new Option(name, code));
  }

  const competencies = [...new Set(rows.map(row => row.competence))]
    .sort()
    .reverse();

  competencies.forEach(value => {
    competence.add(new Option(monthLabel(value), value));
  });

  if (imports?.[0]) {
    document.querySelector('#update-status').textContent =
      `Série oficial atualizada até ${monthLabel(
        imports[0].competence_end,
      )}`;
  }

  territory.addEventListener('change', render);
  competence.addEventListener('change', render);

  render();
}

function selectedRows() {
  return rows.filter(
    row =>
      row.competence <= competence.value &&
      (territory.value === 'regional' ||
        row.ibge_code === territory.value),
  );
}

function render() {
  const selected = selectedRows();

  const current = selected.filter(
    row => row.competence === competence.value,
  );

  if (!current.length) {
    return empty();
  }

  document.querySelector('#admissions').textContent = number(
    sum(current, 'admissions'),
  );

  document.querySelector('#dismissals').textContent = number(
    sum(current, 'dismissals'),
  );

  const balance = sum(current, 'balance');

  document.querySelector('#balance').textContent =
    `${balance > 0 ? '+' : ''}${number(balance)}`;

  document.querySelector('#stock').textContent = number(
    sum(current, 'stock'),
  );

  renderTrend(selected);
  renderRanking(current);
}

function renderTrend(data) {
  const months = [...new Set(data.map(row => row.competence))].sort();

  trendChart?.destroy();

  trendChart = new Chart(document.querySelector('#trend'), {
    type: 'line',

    data: {
      labels: months.map(monthLabel),

      datasets: [
        {
          label: 'Admissões',
          data: months.map(month =>
            sum(
              data.filter(row => row.competence === month),
              'admissions',
            ),
          ),
          borderColor: '#283b89',
          backgroundColor: '#283b89',
          tension: 0.25,
        },

        {
          label: 'Desligamentos',
          data: months.map(month =>
            sum(
              data.filter(row => row.competence === month),
              'dismissals',
            ),
          ),
          borderColor: '#7d93d8',
          backgroundColor: '#7d93d8',
          tension: 0.25,
        },
      ],
    },

    options: {
      responsive: true,
      maintainAspectRatio: false,
    },
  });
}

function renderRanking(current) {
  const rankingRows =
    territory.value === 'regional'
      ? current
      : rows.filter(row => row.competence === competence.value);

  const html = [...rankingRows]
    .sort((a, b) => b.balance - a.balance)
    .map(
      (item, index) => `
        <div class="rank">
          <span>${index + 1}</span>
          <span>${municipalityNames.get(item.ibge_code) || item.ibge_code}</span>
          <strong class="${item.balance >= 0 ? 'positive' : 'negative'}">
            ${item.balance > 0 ? '+' : ''}${number(item.balance)}
          </strong>
        </div>
      `,
    )
    .join('');

  document.querySelector('#municipality-table').innerHTML = html;
}

function empty() {
  document.querySelector('#municipality-table').innerHTML =
    '<p class="empty">Ainda não há dados para esta seleção.</p>';
}

function showError(message) {
  document.querySelector('main').innerHTML =
    `<p class="empty">Não foi possível carregar os dados: ${message}</p>`;
}

function showConfigError() {
  document.querySelector('main').innerHTML =
    '<p class="empty">O painel foi publicado, mas ainda precisa receber as credenciais públicas do Supabase.</p>';
}

boot();
