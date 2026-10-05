const $ = id => document.getElementById(id);
let selected = null, paragraphs = [], signature = '', requestId = 0;
const statuses = {completed:'Tamamlandı', processing:'İşleniyor / yarım kalmış olabilir', failed:'Başarısız', interrupted:'Kesildi'};
async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) { let body; try { body = await response.json(); } catch {} throw Error(body?.error || 'İstek başarısız.'); }
  return response.json();
}
function renderText() {
  const query = $('search').value.toLocaleLowerCase('tr');
  const matching = paragraphs.filter(p => p.toLocaleLowerCase('tr').includes(query));
  $('transcript').replaceChildren(...matching.map(text => { const p = document.createElement('p'); p.textContent = text; return p; }));
  if (!matching.length) $('transcript').textContent = 'Eşleşen metin bulunamadı.';
}
async function selectJob(job) {
  selected = job.id; const ticket = ++requestId;
  document.querySelectorAll('.job').forEach(el => el.classList.toggle('selected', el.dataset.id === selected));
  $('title').textContent = job.title; $('downloads').replaceChildren(); $('search').value=''; $('search').disabled=true;
  for (const file of job.files) { const a = document.createElement('a'); a.href=`/download/${job.id}/${file}`; a.textContent=file.replace('transcript.','').toUpperCase(); $('downloads').append(a); }
  if (!job.files.includes('transcript.txt')) { paragraphs=[]; $('transcript').textContent='Bu kayıt için tamamlanmış döküm henüz yok.'; return; }
  $('transcript').textContent='Döküm yükleniyor…';
  try { const response=await fetch(`/preview/${job.id}/transcript.txt`); if(!response.ok) throw Error('Döküm okunamadı.'); const text=await response.text(); if(ticket!==requestId)return; paragraphs=text.trim().split(/\n\s*\n/); $('search').disabled=false; renderText(); }
  catch(error){if(ticket===requestId)$('transcript').textContent=error.message;}
}
async function refresh() {
  try {
    const data = await api('/api/state'); $('connection').textContent='● Agora bağlı'; $('start').disabled=data.active;
    $('progress').hidden=!data.log; $('spinner').hidden=!data.active;
    $('progress-title').textContent=data.active?'İşlem sürüyor':data.exit_code===0?'Döküm tamamlandı':'İşlem tamamlanamadı';
    if($('log').textContent!==data.log){$('log').textContent=data.log;$('log').scrollTop=$('log').scrollHeight;}
    $('count').textContent=data.jobs.length;
    const next=JSON.stringify(data.jobs);
    if(next!==signature){signature=next;$('jobs').replaceChildren();
      if(!data.jobs.length)$('jobs').textContent='Henüz döküm yok. İlk kaydını ekle.';
      for(const job of data.jobs){const b=document.createElement('button');b.type='button';b.className='job';b.dataset.id=job.id;b.classList.toggle('selected',selected===job.id);const title=document.createElement('strong');title.textContent=job.title;const meta=document.createElement('small');meta.textContent=(statuses[job.status]||job.status)+' · '+(job.started_at?new Date(job.started_at).toLocaleString('tr-TR'):job.id);b.append(title,meta);b.onclick=()=>selectJob(job);$('jobs').append(b);}
      const current=data.jobs.find(j=>j.id===selected)||data.jobs[0];if(current)await selectJob(current);
    }
  } catch(error){$('connection').textContent='Bağlantı kesildi';$('error').textContent='Agora arayüzü erişilemiyor. Sunucuyu ve SSH tünelini kontrol et.';}
  finally {setTimeout(refresh,2500);}
}
$('search').addEventListener('input',renderText);
$('form').addEventListener('submit',async event=>{event.preventDefault();$('error').textContent='';$('start').disabled=true;
try{await api('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url:$('url').value,mode:$('mode').value,device:$('device').value,language:$('language').value})});}
catch(error){$('error').textContent=error.message;$('start').disabled=false;}});
refresh();
