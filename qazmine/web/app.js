const $=id=>document.getElementById(id);
const scenarioNames=['road_closed','excavator_failure','crusher_reduced'];
let lastActive=[];
function fmt(n, digits=1){let x=Number(n);return Number.isFinite(x)?x.toLocaleString('ru-RU',{maximumFractionDigits:digits,minimumFractionDigits:digits}):'—'}
function setStatus(ok,msg){$('conn').textContent=msg;$('conn').className='pill '+(ok?'ok':'error')}
function makeTruck(name,t){
 const ns='http://www.w3.org/2000/svg'; const g=document.createElementNS(ns,'g');g.setAttribute('transform',`translate(${Number(t.x)||0}, ${Number(t.y)||0})`);
 const moving=t.state==='hauling'||t.state==='travel_to_face';const clr=moving?'#f8b947':'#39e7c6';
 const halo=document.createElementNS(ns,'circle');halo.setAttribute('r','19');halo.setAttribute('fill',clr);halo.setAttribute('opacity','.14');g.appendChild(halo);
 const box=document.createElementNS(ns,'rect');Object.entries({x:-15,y:-10,width:30,height:20,rx:5,fill:clr,stroke:'#edf3f6','stroke-width':2}).forEach(([k,v])=>box.setAttribute(k,v));g.appendChild(box);
 const cabin=document.createElementNS(ns,'rect');Object.entries({x:1,y:-7,width:10,height:14,rx:2,fill:'#184257'}).forEach(([k,v])=>cabin.setAttribute(k,v));g.appendChild(cabin);
 const text=document.createElementNS(ns,'text');text.setAttribute('y','-21');text.setAttribute('text-anchor','middle');text.setAttribute('font-size','11');text.setAttribute('font-weight','bold');text.setAttribute('fill','#fff');text.textContent=name.toUpperCase();g.appendChild(text);return g;
}
function render(data){
 const a=data.twins,m=a.mine||{},c=a.crusher||{};
 $('tonnes').textContent=fmt(m.ore_delivered,0);$('grade').textContent=fmt(m.feed_grade,3)+'%';
 $('throughput').textContent=fmt(c.throughput,0);$('waiting').textContent=fmt(m.average_wait,1);
 const s=Number(m.time_minutes||0)*60;$('simtime').textContent=`${String(Math.floor(s/3600)).padStart(2,'0')}:${String(Math.floor(s%3600/60)).padStart(2,'0')}`;
 const els=$('units'); els.replaceChildren();
 for(const key of ['haul-01','haul-02','haul-03'])if(a[key])els.appendChild(makeTruck(key,a[key]));
 const fleet=$('fleet');fleet.replaceChildren();
 for(const key of ['haul-01','haul-02','haul-03']){
  const t=a[key]||{};const p=document.createElement('div');p.className='item';
  const left=document.createElement('span');left.textContent=key.toUpperCase()+' · '+(t.state||'—');
  const right=document.createElement('b');right.textContent=fmt(t.payload,0)+' т';p.append(left,right);fleet.appendChild(p);
 }
 for (let r of Object.keys(data.roads||{})) {let node=$(r);if(node)node.setAttribute('class','road '+(a[r]?.state==='closed'?'closed':'open'))}
 lastActive=(m.scenarios||'').split(',').filter(Boolean);
 scenarioNames.forEach(x=>{if(document.activeElement!==$(x))$(x).checked=lastActive.includes(x)});
 $('btnAdaptive').classList.toggle('active',m.mode==='adaptive');$('btnBasic').classList.toggle('active',m.mode==='basic');
 $('map-status').textContent='LIVE · Ditto '+(m.mode==='adaptive'?'АДАПТИВНЫЙ':'БАЗОВЫЙ')+' диспетчер';
}
async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw Error('Ditto не отвечает ('+r.status+')'); const data=await r.json();render(data);setStatus(true,'● LIVE · ECLIPSE DITTO');}catch(e){setStatus(false,'● ОШИБКА · '+e.message);$('map-status').textContent='Нет актуальных данных Ditto';}}
async function action(url, body){$('feedback').textContent='Отправляем команду...';try{const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});if(!r.ok)throw Error('HTTP '+r.status);$('feedback').textContent='Команда принята. Ожидаем подтверждение через Eclipse Ditto.';await new Promise(x=>setTimeout(x,700));await refresh()}catch(e){$('feedback').textContent='Команда не выполнена: '+e.message;await refresh()}}
scenarioNames.forEach(name=>$(name).addEventListener('change',ev=>action('/api/scenario',{name,enabled:ev.target.checked})));
$('reset').addEventListener('click',()=>action('/api/reset'));
$('btnAdaptive').addEventListener('click',()=>action('/api/mode/adaptive'));
$('btnBasic').addEventListener('click',()=>action('/api/mode/basic'));
(async()=>{try{const r=await fetch('/api/benchmark');if(!r.ok)throw Error();const data=await r.json();const rows=[['Масса руды (т)','tonnes'],['Среднее Cu (%)','grade'],['Отклонение от 0,78%','grade_error'],['Ожидание (мин)','avg_wait_minutes']];
let html='<table><thead><tr><th>Показатель</th><th>Базовый</th><th>Адаптивный</th></tr></thead><tbody>';for(const [name,k] of rows){html+=`<tr><td>${name}</td><td>${fmt(data.results.basic[k],k==='grade'||k==='grade_error'?3:1)}</td><td>${fmt(data.results.adaptive[k],k==='grade'||k==='grade_error'?3:1)}</td></tr>`;}html+='</tbody></table>';$('benchmark').innerHTML=html;
}catch(e){$('benchmark').textContent='Эксперимент недоступен'}})();
refresh();setInterval(refresh,2500);
