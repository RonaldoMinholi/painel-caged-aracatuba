import { createClient } from '@supabase/supabase-js';
import Chart from 'chart.js/auto';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const territory = document.querySelector('#territory');
const competenceToggle = document.querySelector('#competence-toggle');
const competenceMenu = document.querySelector('#competence-menu');

let trendChart;
let rows = [];
let municipalityNames = new Map();
let regionalCodes = new Set();
let selectedCompetence = '';
let openYear = '';

const number = value => new Intl.NumberFormat('pt-BR').format(value || 0);
const monthLabel = value => new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric' }).format(new Date(`${value}T12:00:00`));
const monthName = value => new Intl.DateTimeFormat('pt-BR', { month: 'long' }).format(new Date(`${value}T12:00:00`));
const sum = (items, field) => items.reduce((total, item) => total + (Number(item[field]) || 0), 0);

async function fetchAllOfficialRows(supabase) {
  const pageSize = 1000;
  const allRows = [];

  for (let from = 0; ; from += pageSize) {
    const { data, error } = await supabase
      .from('caged_official_monthly')
      .select('competence,ibge_code,stock,admissions,dismissals,balance')
      .order('competence')
      .range(from, from + pageSize - 1);

    if (error) return { data: [], error };
    allRows.push(...(data || []));
    if (!data || data.length < pageSize) return { data: allRows, error: null };
  }
}

async function boot() {
  if (!supabaseUrl || !supabaseKey) return showConfigError();

  const supabase = createClient(supabaseUrl, supabaseKey);
  const [officialResult, municipalitiesResult, importsResult] = await Promise.all([
    fetchAllOfficialRows(supabase),
    supabase.from('municipalities').select('ibge_code,name,is_regional').order('name'),
    supabase.from('caged_official_imports').select('competence_end,imported_at').order('competence_end', { ascending: false }).limit(1)
  ]);

  if (officialResult.error || municipalitiesResult.error) {
    return showError((officialResult.error || municipalitiesResult.error).message);
  }

  rows = officialResult.data;
  const municipalities = municipalitiesResult.data || [];
  municipalityNames = new Map(municipalities.map(item => [item.ibge_code, item.name]));
  regionalCodes = new Set(municipalities.filter(item => item.is_regional).map(item => item.ibge_code));
  municipalities.filter(item => item.is_regional).forEach(item => territory.add(new Option(item.name, item.ibge_code)));

  const competences = regionalCompetences();
  selectedCompetence = competences[competences.length - 1] || '';
  openYear = selectedCompetence.slice(0, 4);

  if (importsResult.data?.[0]) {
    document.querySelector('#update-status').textContent = `Série oficial atualizada até ${monthLabel(importsResult.data[0].competence_end)}`;
  }

  territory.addEventListener('change', render);

  competenceToggle.addEventListener('click', () => {
    const isOpen = !competenceMenu.hidden;
    competenceMenu.hidden = isOpen;
    competenceToggle.setAttribute('aria-expanded', String(!isOpen));
  });

  document.addEventListener('click', event => {
    if (!event.target.closest('.competence-filter')) {
      competenceMenu.hidden = true;
      competenceToggle.setAttribute('aria-expanded', 'false');
    }
  });

  renderCompetencePicker();
  render();
}

function regionalCompetences() {
  return [...new Set(rows.filter(row => regionalCodes.has(row.ibge_code)).map(row => row.competence))].sort();
}

function renderCompetencePicker() {
  const byYear = new Map();

  for (const value of regionalCompetences()) {
    const year = value.slice(0, 4);
    if (!byYear.has(year)) byYear.set(year, []);
    byYear.get(year).push(value);
  }

  competenceToggle.textContent = selectedCompetence ? monthLabel(selectedCompetence) : 'Nenhuma competência disponível';
  competenceMenu.replaceChildren();

  [...byYear.entries()].sort(([a], [b]) => a.localeCompare(b)).forEach(([year, months]) => {
    const group = document.createElement('div');
    group.className = 'year-group';

    const yearButton = document.createElement('button');
    yearButton.type = 'button';
    yearButton.className = 'year-toggle';
    yearButton.innerHTML = `<span class="year-arrow">${openYear === year ? '⌄' : '›'}</span><span>${year}</span>`;

    yearButton.addEventListener('click', () => {
      openYear = openYear === year ? '' : year;
      renderCompetencePicker();
    });

    group.append(yearButton);

    if (openYear === year) {
      const monthList = document.createElement('div');
      monthList.className = 'month-list';

      months.forEach(value => {
        const monthButton = document.createElement('button');
        monthButton.type = 'button';
        monthButton.className = `month-option${value === selectedCompetence ? ' selected' : ''}`;
        monthButton.innerHTML = `<span class="check">${value === selectedCompetence ? '✓' : ''}</span><span>${monthName(value)}</span>`;

        monthButton.addEventListener('click', () => {
          selectedCompetence = value;
          competenceMenu.hidden = true;
          competenceToggle.setAttribute('aria-expanded', 'false');
          renderCompetencePicker();
          render();
        });

        monthList.append(monthButton);
      });

      group.append(monthList);
    }

    competenceMenu.append(group);
  });
}

function selectedRows() {
  return rows.filter(row =>
    row.competence <= selectedCompetence &&
    (territory.value === 'regional' ? regionalCodes.has(row.ibge_code) : row.ibge_code === territory.value)
  );
}

function render() {
  const selected = selectedRows();
  const current = selected.filter(row => row.competence === selectedCompetence);

  if (!current.length) return empty();

  document.querySelector('#admissions').textContent = number(sum(current, 'admissions'));
  document.querySelector('#dismissals').textContent = number(sum(current, 'dismissals'));

  const balance = sum(current, 'balance');
  document.querySelector('#balance').textContent = `${balance > 0 ? '+' : ''}${number(balance)}`;
  document.querySelector('#stock').textContent = number(sum(current, 'stock'));

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
          data: months.map(month => sum(data.filter(row => row.competence === month), 'admissions')),
          borderColor: '#283b89',
          backgroundColor: '#283b89',
          tension: 0.25
        },
        {
          label: 'Desligamentos',
          data: months.map(month => sum(data.filter(row => row.competence === month), 'dismissals')),
          borderColor: '#7d93d8',
          backgroundColor: '#7d93d8',
          tension: 0.25
        }
      ]
    },
    options: { responsive: true, maintainAspectRatio: false }
  });
}

function renderRanking(current) {
  const rankingRows = territory.value === 'regional'
    ? current
    : rows.filter(row => row.competence === selectedCompetence && regionalCodes.has(row.ibge_code));

  document.querySelector('#municipality-table').innerHTML = [...rankingRows]
    .sort((a, b) => b.balance - a.balance)
    .map((item, index) => `
      <div class="rank">
        <span>${index + 1}</span>
        <span>${municipalityNames.get(item.ibge_code) || item.ibge_code}</span>
        <strong class="${item.balance >= 0 ? 'positive' : 'negative'}">${item.balance > 0 ? '+' : ''}${number(item.balance)}</strong>
      </div>
    `)
    .join('');
}

function empty() {
  document.querySelector('#municipality-table').innerHTML = '<p class="empty">Ainda não há dados para esta seleção.</p>';
}

function showError(message) {
  document.querySelector('main').innerHTML = `<p class="empty">Não foi possível carregar os dados: ${message}</p>`;
}

function showConfigError() {
  document.querySelector('main').innerHTML = '<p class="empty">O painel foi publicado, mas ainda precisa receber as credenciais públicas do Supabase.</p>';
}

boot();
