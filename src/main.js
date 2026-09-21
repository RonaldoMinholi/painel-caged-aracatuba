import { createClient } from '@supabase/supabase-js';
import Chart from 'chart.js/auto';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL;
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY;
const territory = document.querySelector('#territory');
const competence = document.querySelector('#competence');
let trendChart, sectorChart, rows = [];

const number = value => new Intl.NumberFormat('pt-BR').format(value || 0);
const monthLabel = value => new Intl.DateTimeFormat('pt-BR', { month:'long', year:'numeric' }).format(new Date(`${value}T12:00:00`));

async function boot() {
  if (!supabaseUrl || !supabaseKey) return showConfigError();
  const supabase = createClient(supabaseUrl, supabaseKey);
  const [{ data: data, error }, { data: imports }] = await Promise.all([
    supabase.from('caged_monthly').select('competence,ibge_code,cnae_section,admissions,dismissals,balance,municipalities(name)').order('competence'),
    supabase.from('caged_imports').select('competence,imported_at').order('competence', { ascending:false }).limit(1)
  ]);
  if (error) return showError(error.message);
  rows = data || [];
  const municipalities = [...new Map(rows.map(r => [r.ibge_code, r.municipalities?.name])).entries()].sort((a,b)=>a[1].localeCompare(b[1]));
  municipalities.forEach(([code,name]) => territory.add(new Option(name, code)));
  const competencies = [...new Set(rows.map(r=>r.competence))].sort().reverse();
  competencies.forEach(value => competence.add(new Option(monthLabel(value), value)));
  if (imports?.[0]) document.querySelector('#update-status').textContent = `Última competência importada: ${monthLabel(imports[0].competence)}`;
  territory.addEventListener('change', render); competence.addEventListener('change', render); render();
}

function filtered() { return rows.filter(r => r.competence <= competence.value && (territory.value === 'regional' || r.ibge_code === territory.value)); }
function sums(group) { return group.reduce((a,r)=>({ admissions:a.admissions+r.admissions, dismissals:a.dismissals+r.dismissals, balance:a.balance+r.balance }), {admissions:0,dismissals:0,balance:0}); }
function grouped(data, key) { return data.reduce((map,row)=>{ const name = row[key] || 'Não informado'; map[name] ||= []; map[name].push(row); return map; }, {}); }
function render() {
  const selected = filtered(); if (!selected.length) return empty();
  const current = selected.filter(r=>r.competence===competence.value); const total=sums(current);
  document.querySelector('#admissions').textContent=number(total.admissions); document.querySelector('#dismissals').textContent=number(total.dismissals); document.querySelector('#balance').textContent=(total.balance>0?'+':'')+number(total.balance);
  renderTrend(selected); renderSector(current); renderRanking(current);
}
function renderTrend(data) { const byMonth=grouped(data,'competence'); const labels=Object.keys(byMonth).sort(); const points=labels.map(k=>sums(byMonth[k])); trendChart?.destroy(); trendChart=new Chart(document.querySelector('#trend'),{type:'line',data:{labels:labels.map(monthLabel),datasets:[{label:'Admissões',data:points.map(p=>p.admissions),borderColor:'#283b89',backgroundColor:'#283b89',tension:.25},{label:'Desligamentos',data:points.map(p=>p.dismissals),borderColor:'#7d93d8',backgroundColor:'#7d93d8',tension:.25}]},options:{responsive:true,maintainAspectRatio:false}}); }
function renderSector(data) { const bySector=grouped(data,'cnae_section'); const values=Object.entries(bySector).map(([name,items])=>[name,sums(items).balance]).sort((a,b)=>b[1]-a[1]); sectorChart?.destroy(); sectorChart=new Chart(document.querySelector('#sector'),{type:'bar',data:{labels:values.map(v=>v[0]),datasets:[{label:'Saldo',data:values.map(v=>v[1]),backgroundColor:values.map(v=>v[1]>=0?'#2d408e':'#c04b57')}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}}}}); }
function renderRanking(data) { const byMunicipality=grouped(data,'ibge_code'); const values=Object.entries(byMunicipality).map(([code,items])=>({name:items[0].municipalities?.name||code,...sums(items)})).sort((a,b)=>b.balance-a.balance); document.querySelector('#municipality-table').innerHTML=values.map((item,index)=>`<div class="rank"><span>${index+1}</span><span>${item.name}</span><strong class="${item.balance>=0?'positive':'negative'}">${item.balance>0?'+':''}${number(item.balance)}</strong></div>`).join(''); }
function empty(){document.querySelector('#municipality-table').innerHTML='<p class="empty">Ainda não há dados para esta seleção.</p>';}
function showError(message){document.querySelector('main').innerHTML=`<p class="empty">Não foi possível carregar os dados: ${message}</p>`;}
function showConfigError(){document.querySelector('main').innerHTML='<p class="empty">O painel foi publicado, mas ainda precisa receber as credenciais públicas do Supabase.</p>';}
boot();
