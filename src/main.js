import { createClient } from "@supabase/supabase-js";
import Chart from "chart.js/auto";
import brazil from "@svg-maps/brazil";

const $ = (s) => document.querySelector(s);
const fmt = new Intl.NumberFormat("pt-BR");
const sum = (rows, key) => rows.reduce((n, row) => n + (+row[key] || 0), 0);
const toDate = (value) => new Date(`${value}T12:00:00`);
const monthName = (value) => new Intl.DateTimeFormat("pt-BR", { month: "long" }).format(toDate(value));
const periodName = (value) => new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric" }).format(toDate(value));
const STATE_IDS = { 11:"ro",12:"ac",13:"am",14:"rr",15:"pa",16:"ap",17:"to",21:"ma",22:"pi",23:"ce",24:"rn",25:"pb",26:"pe",27:"al",28:"se",29:"ba",31:"mg",32:"es",33:"rj",35:"sp",41:"pr",42:"sc",43:"rs",50:"ms",51:"mt",52:"go",53:"df" };

const territory = $("#territory"), municipalityFilter = $("#municipality"), municipalitySearch = $("#municipality-search"), sectionFilter = $("#section-filter"), sexFilter = $("#sex-filter"), periodSummary = $("#period-summary"), periodTree = $("#period-tree"), status = $("#update-status"), ufLabel = $("#uf-label");
let supabase, municipalities = [], regionalMunicipalities = [], officialRows = [], detailRows = [], selectedCompetences = new Set(), selectedMunicipalities = new Set(), selectedSections = new Set(), selectedSexes = new Set(), expandedYear = "", sourceNote = "", trendChart, balanceChart, mapRequest = 0, renderRequest = 0;

const labelsPlugin = { id:"barValueLabels", afterDatasetsDraw(chart) {
  if (chart.config.type !== "bar") return;
  const ctx = chart.ctx, dataset = chart.data.datasets[0], meta = chart.getDatasetMeta(0);
  ctx.save(); ctx.fillStyle = "#666"; ctx.font = "10px Aptos, Arial"; ctx.textAlign = "center";
  meta.data.forEach((bar, index) => { const value = +dataset.data[index] || 0, point = bar.getProps(["x","y"], true); ctx.textBaseline = value >= 0 ? "bottom" : "top"; ctx.fillText(fmt.format(value), point.x, point.y + (value >= 0 ? -6 : 6)); });
  ctx.restore();
}};

async function pages(query) { const all=[]; for(let start=0;;start+=1000) { const {data,error}=await query.range(start,start+999); if(error) throw error; all.push(...(data||[])); if(!data || data.length<1000) return all; } }
function normalizeSex(value) { const v=String(value||"").normalize("NFD").replace(/[\u0300-\u036f]/g,"").trim().toUpperCase(); if(["F","FEMININO","MULHER","2","3"].includes(v)) return "Feminino"; if(["M","MASCULINO","HOMEM","1"].includes(v)) return "Masculino"; return "Não informado"; }
function months() { return [...new Set(officialRows.map((row)=>row.competence))].sort(); }
function drawMap() { $("#brazil-map").innerHTML=`<svg viewBox="${brazil.viewBox}">${brazil.locations.map((s)=>`<path data-state="${s.id}" d="${s.path}"><title>${s.name}</title></path>`).join("")}</svg>`; }
function heat(value,max) { if(!Number.isFinite(value)||value<=0||max<=0) return "#e0e0e0"; const p=Math.sqrt(value/max), a=[220,221,238], b=[27,35,112]; return `rgb(${a.map((x,i)=>Math.round(x+(b[i]-x)*p)).join(",")})`; }
function paintMap(balances) { const max=Math.max(0,...balances.values()); brazil.locations.forEach((state)=>{ const path=document.querySelector(`#brazil-map path[data-state="${state.id}"]`); if(path) path.style.fill=heat(balances.get(state.id),max); }); }
function activeCodes() { if(selectedMunicipalities.size) return [...selectedMunicipalities]; return territory.value === "regional" ? regionalMunicipalities.map((row)=>row.ibge_code) : null; }

async function renderMap() {
  const request=++mapRequest, selected=selectedCompetences.size?[...selectedCompetences]:months();
  const detailed=territory.value==="regional"&&(selectedMunicipalities.size||selectedSections.size||selectedSexes.size);
  if(detailed) { const [rows]=filtered(true), balances=new Map(); rows.forEach((row)=>{ const id=STATE_IDS[String(row.ibge_code).slice(0,2)]; balances.set(id,(balances.get(id)||0)+(+row.balance||0)); }); paintMap(balances); return; }
  const {data,error}=await supabase.rpc("caged_state_balance",{p_competences:selected,p_ibge_codes:activeCodes()});
  if(request!==mapRequest || error) { if(error) console.warn(error.message); return; }
  paintMap(new Map((data||[]).map((row)=>[STATE_IDS[String(row.uf_code)],Number(row.balance)||0])));
}

function check(parent,text,checked,change) { const label=document.createElement("label"), input=document.createElement("input"); label.className="multi-option"; input.type="checkbox"; input.checked=checked; input.onchange=()=>change(input.checked); label.append(input,document.createTextNode(text)); parent.append(label); return input; }
function multi(element,options,set) { const box=element.querySelector(".multi-options"), summary=element.querySelector("summary"); const draw=()=>{ box.replaceChildren(); const all=check(box,"Todos",!set.size,(on)=>{if(on)set.clear();draw();render();}); all.indeterminate=!!set.size; options.forEach(([value,name])=>check(box,name,set.has(value),(on)=>{on?set.add(value):set.delete(value);draw();render();})); summary.textContent=!set.size?"Todos":set.size===1?(options.find((x)=>set.has(x[0]))?.[1]||"1 selecionado"):`${set.size} selecionados`; }; draw(); }
function scopeMunicipalities() { return territory.value==="regional"?regionalMunicipalities:municipalities; }

function drawMunicipalityFilter() {
  const box=municipalityFilter.querySelector(".multi-options"), summary=municipalityFilter.querySelector("summary"), term=municipalitySearch.value.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();
  const choices=scopeMunicipalities().filter((row)=>row.name.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase().includes(term));
  box.replaceChildren(); const all=check(box,"Todos",!selectedMunicipalities.size,(on)=>{if(on)selectedMunicipalities.clear();drawMunicipalityFilter();render();}); all.indeterminate=!!selectedMunicipalities.size;
  choices.forEach((row)=>check(box,row.name,selectedMunicipalities.has(row.ibge_code),(on)=>{on?selectedMunicipalities.add(row.ibge_code):selectedMunicipalities.delete(row.ibge_code);drawMunicipalityFilter();render();}));
  summary.textContent=!selectedMunicipalities.size?"Todos":selectedMunicipalities.size===1?(municipalities.find((x)=>selectedMunicipalities.has(x.ibge_code))?.name||"1 selecionado"):`${selectedMunicipalities.size} selecionados`;
}

function updateScope() {
  const national=territory.value==="national";
  ufLabel.textContent=national?"Todos":"São Paulo";
  sectionFilter.closest(".slicer").hidden=national;
  sexFilter.closest(".slicer").hidden=national;
  if(national){selectedSections.clear();selectedSexes.clear();}
  selectedMunicipalities.clear();
  municipalitySearch.value="";
  drawMunicipalityFilter();
}

function tree() {
  const groups={}; months().forEach((value)=>(groups[value.slice(0,4)]??=[]).push(value)); const chosen=[...selectedCompetences];
  periodSummary.innerHTML=`${chosen.length===1?`${chosen[0].slice(0,4)} (Ano) + ${monthName(chosen[0])} (Mês)`:chosen.length?`${chosen.length} meses selecionados`:"Todos os meses"}<span>⌃</span>`; periodTree.replaceChildren();
  Object.entries(groups).forEach(([year,list])=>{ const row=document.createElement("div"), expand=document.createElement("button"), input=document.createElement("input"); row.className="period-year"; expand.className="tree-arrow"; expand.textContent=expandedYear===year?"⌄":"›"; expand.onclick=()=>{expandedYear=expandedYear===year?"":year;tree();}; input.type="checkbox"; input.checked=list.every((x)=>selectedCompetences.has(x)); input.indeterminate=!input.checked&&list.some((x)=>selectedCompetences.has(x)); input.onchange=()=>{list.forEach((x)=>input.checked?selectedCompetences.add(x):selectedCompetences.delete(x));tree();render();}; row.append(expand,input,document.createTextNode(year)); periodTree.append(row);
    if(expandedYear!==year)return; const wrap=document.createElement("div"); wrap.className="period-months"; list.forEach((value)=>{const item=document.createElement("label"), box=document.createElement("input"); item.className="period-month";box.type="checkbox";box.checked=selectedCompetences.has(value);box.onchange=()=>{box.checked?selectedCompetences.add(value):selectedCompetences.delete(value);tree();render();};item.append(box,document.createTextNode(monthName(value)));wrap.append(item);});periodTree.append(wrap);
  });
}

function filtered(selected=true) { const detailed=selectedSections.size||selectedSexes.size, source=detailed?detailRows:officialRows, selectedMonths=selected&&selectedCompetences.size?selectedCompetences:new Set(months()); return [source.filter((row)=>selectedMonths.has(row.competence)&&(!selectedMunicipalities.size||selectedMunicipalities.has(row.ibge_code))&&(!selectedSections.size||selectedSections.has(row.cnae_section))&&(!selectedSexes.size||selectedSexes.has(row.sex))),detailed]; }
function series(rows) { return [...new Set(rows.map((row)=>row.competence))].sort().map((competence)=>{const period=rows.filter((row)=>row.competence===competence);return {c:competence,a:sum(period,"admissions"),d:sum(period,"dismissals"),b:sum(period,"balance"),s:sum(period,"stock")};}); }

async function remoteSeries() {
  const {data,error}=await supabase.rpc("caged_official_series",{p_ibge_codes:activeCodes()});
  if(error)throw error;
  return (data||[]).map((row)=>({c:row.competence,a:+row.admissions||0,d:+row.dismissals||0,b:+row.balance||0,s:+row.stock||0}));
}

async function render() {
  const request=++renderRequest;

  try {
    let history, cards, detailed=false;

    if(territory.value==="national") {
      history=await remoteSeries();
      if(request!==renderRequest)return;
      const selected=selectedCompetences.size?selectedCompetences:new Set(months());
      cards=history.filter((row)=>selected.has(row.c));
    } else {
      const [rows,isDetailed]=filtered(true),[allRows]=filtered(false);
      cards=series(rows);
      history=series(allRows);
      detailed=isDetailed;
    }

    if(!cards.length){
      ["admissions","dismissals","balance","stock"].forEach((id)=>$("#"+id).textContent="—");
      chart(history);
      status.textContent="Não há dados para essa combinação.";
    } else {
      $("#admissions").textContent=fmt.format(sum(cards,"a"));
      $("#dismissals").textContent=fmt.format(sum(cards,"d"));

      const balance=sum(cards,"b");

      $("#balance").textContent=`${balance>0?"+":""}${fmt.format(balance)}`;
      $("#stock").textContent=detailed||selectedCompetences.size!==1?"—":fmt.format(sum(cards,"s"));

      chart(history);

      status.textContent=detailed
        ?"Fonte: microdados do Novo CAGED. Cartões respeitam Ano, Mês; gráficos exibem toda a série."
        :sourceNote;
    }

    renderMap();
  } catch(error) {
    if(request===renderRequest){
      status.textContent=`Não foi possível carregar os dados: ${error.message}`;
    }
  }
}

function chart(data=[]) {
  const labels=data.map((row,i)=>row.c.slice(0,4)!==(i?data[i-1].c.slice(0,4):"")?row.c.slice(0,4):"");

  const options={
    responsive:true,
    maintainAspectRatio:false,
    plugins:{
      legend:{position:"top"},
      tooltip:{callbacks:{title:(items)=>periodName(data[items[0].dataIndex].c)}}
    },
    scales:{
      x:{grid:{display:false},ticks:{maxRotation:0,autoSkip:false}},
      y:{ticks:{callback:(v)=>fmt.format(v)}}
    }
  };

  trendChart?.destroy();
  balanceChart?.destroy();

  trendChart=new Chart($("#trend"),{
    type:"line",
    data:{
      labels,
      datasets:[
        {label:"Admitidos",data:data.map((x)=>x.a),borderColor:"#222a80",pointRadius:0,borderWidth:3},
        {label:"Desligados",data:data.map((x)=>x.d),borderColor:"#2f58a7",pointRadius:0,borderWidth:3}
      ]
    },
    options
  });

  balanceChart=new Chart($("#balance-chart"),{
    type:"bar",
    data:{
      labels,
      datasets:[
        {label:"Saldo",data:data.map((x)=>x.b),backgroundColor:"#222a80",maxBarThickness:16}
      ]
    },
    options,
    plugins:[labelsPlugin]
  });
}

async function boot() {
  try {
    drawMap();

    if(!import.meta.env.VITE_SUPABASE_URL){
      throw Error("As credenciais públicas do Supabase não foram configuradas no Vercel.");
    }

    supabase=createClient(
      import.meta.env.VITE_SUPABASE_URL,
      import.meta.env.VITE_SUPABASE_ANON_KEY
    );

    municipalities=await pages(
      supabase
        .from("municipalities")
        .select("ibge_code,name,is_regional")
        .order("name")
    );

    regionalMunicipalities=municipalities.filter((row)=>row.is_regional);

    const codes=regionalMunicipalities.map((row)=>row.ibge_code);

    const [official,details,imports]=await Promise.all([
      pages(
        supabase
          .from("caged_official_monthly")
          .select("competence,ibge_code,stock,admissions,dismissals,balance")
          .in("ibge_code",codes)
          .order("competence")
      ),
      pages(
        supabase
          .from("caged_monthly")
          .select("competence,ibge_code,cnae_section,sex,admissions,dismissals,balance")
          .in("ibge_code",codes)
          .order("competence")
      ),
      supabase
        .from("caged_official_imports")
        .select("competence_end")
        .order("competence_end",{ascending:false})
        .limit(1)
    ]);

    officialRows=official;
    detailRows=details.map((row)=>({...row,sex:normalizeSex(row.sex)}));

    if(!officialRows.length){
      throw Error("A Tabela 8.1 ainda não possui dados.");
    }

    selectedCompetences.add(months().at(-1));
    expandedYear=months().at(-1).slice(0,4);

    multi(
      sectionFilter,
      [...new Set(details.map((x)=>x.cnae_section).filter(Boolean))]
        .sort()
        .map((x)=>[x,x]),
      selectedSections
    );

    multi(
      sexFilter,
      ["Masculino","Feminino","Não informado"].map((x)=>[x,x]),
      selectedSexes
    );

    sourceNote=imports.data?.[0]
      ?`Fonte: Novo CAGED — Ministério do Trabalho e Emprego. Série oficial atualizada até ${periodName(imports.data[0].competence_end)}.`
      :"";

    territory.addEventListener("change",()=>{
      updateScope();
      render();
    });

    municipalitySearch.addEventListener("input",drawMunicipalityFilter);

    periodSummary.onclick=()=>{
      periodTree.hidden=!periodTree.hidden;
    };

    updateScope();
    tree();
    render();
  } catch(error) {
    status.textContent=error.message;
  }
}

boot();
