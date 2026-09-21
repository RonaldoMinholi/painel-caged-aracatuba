import { createClient } from '@supabase/supabase-js';
import Chart from 'chart.js/auto';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

const territory = document.querySelector('#territory');
const year = document.querySelector('#year');
const competence = document.querySelector('#competence');

let trendChart;
let rows = [];
let municipalityNames = new Map();
let regionalCodes = new Set();

const number = value => new Intl.NumberFormat('pt-BR').format(value || 0);

const monthLabel = value =>
  new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' })
    .format(new Date(`${value}T12:00:00`));

const monthName = value =>
  new Intl.DateTimeFormat('pt-BR', { month: 'long' })
    .format(new Date(`${value}T12:00:00`));

const sum = (items, field) =>
  items.reduce((total, item) => total + (Number(item[field]) || 0), 0);

async function boot() {
  if (!supabaseUrl || !supabaseKey) {
    return showConfigError();
  }

  const supabase = createClient(supabaseUrl, supabaseKey);

  const [
    { data: officialRows, error },
    { data: municipalities, error: municipalitiesError },
    { data: imports }
  ] = await Promise.all([
    supabase
      .from('caged_official_monthly')
      .select('competence,ibge_code,stock,admissions,dismissals,balance')
      .order('competence'),

    supabase
      .from('municipalities')
      .select('ibge_code,name,is_regional')
      .order('name'),

    supabase
      .from('caged_official_imports')
      .select('competence_end,imported_at')
      .order('competence_end', { ascending: false })
      .limit(1)
  ]);

  if (error || municipalitiesError) {
    return showError((error || municipalitiesError).message);
  }

  rows = officialRows || [];
  municipalityNames = new Map(
    (municipalities || []).map(item => [item.ibge_code, item.name])
  );

  regionalCodes = new Set(
    (municipalities || [])
      .filter(item => item.is_regional)
      .map(item => item.ibge_code)
  );

  for (const item of (municipalities || []).filter(item => item.is_regional)) {
    territory.add(new Option(item.name, item.ibge_code));
  }

  const years = [...new Set(
    rows
      .filter(row => regionalCodes.has(row.ibge_code))
      .map(row => row.competence.slice(0, 4))
  )].sort().reverse();

  years.forEach(value => year.add(new Option(value, value)));

  if (imports?.[0]) {
    document.querySelector('#update-status').textContent =
      `Série oficial atualizada até ${monthLabel(imports[0].competence_end)}`;
  }

  territory.addEventListener('change', render);
  year.addEventListener('change', populateMonths);
  competence.addEventListener('change', render);

  populateMonths();
}

function populateMonths() {
  const selectedYear = year.value;

  const months = [...new Set(
    rows
      .filter(row =>
        regionalCodes.has(row.ibge_code) &&
        row.competence.startsWith(selectedYear)
      )
      .map(row => row.competence)
  )].sort().reverse();

  competence.replaceChildren(
    ...months.map(value => new Option(monthName(value), value))
  );

  render();
}

function selectedRows() {
  return rows.filter(row =>
    row.competence <= competence.value &&
    (
      territory.value === 'regional'
        ? regionalCodes.has(row.ibge_code)
        : row.ibge_code === territory.value
    )
  );
}

function render() {
  const selected = selectedRows();
  const current = selected.filter(row => row.competence === competence.value);

  if (!current.length) {
    return empty();
  }

  document.querySelector('#admissions').textContent =
    number(sum(current, 'admissions'));

  document.querySelector('#dismissals').textContent =
    number(sum(current, 'dismissals'));

  const balance = sum(current, 'balance');

  document.querySelector('#balance').textContent =
    `${balance > 0 ? '+' : ''}${number(balance)}`;

  document.querySelector('#stock').textContent =
    number(sum(current, 'stock'));

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
            sum(data.filter(row => row.competence === month), 'admissions')
          ),
          borderColor: '#283b89',
          backgroundColor: '#283b89',
          tension: 0.25
        },
        {
          label: 'Desligamentos',
          data: months.map(month =>
            sum(data.filter(row => row.competence === month), 'dismissals')
          ),
          borderColor: '#7d93d8',
          backgroundColor: '#7d93d8',
          tension: 0.25
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false
    }
  });
}

function renderRanking(current) {
  const rankingRows =
    territory.value === 'regional'
      ? current
      : rows.filter(row =>
          row.competence === competence.value &&
          regionalCodes.has(row.ibge_code)
        );

  document.querySelector('#municipality-table').innerHTML =
    [...rankingRows]
      .sort((a, b) => b.balance - a.balance)
      .map((item, index) => `
        <div class="rank">
          <span>${index + 1}</span>
          <span>${municipalityNames.get(item.ibge_code) || item.ibge_code}</span>
          <strong class="${item.balance >= 0 ? 'positive' : 'negative'}">
            ${item.balance > 0 ? '+' : ''}${number(item.balance)}
          </strong>
        </div>
      `)
      .join('');
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
