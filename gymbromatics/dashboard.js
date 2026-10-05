(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('analysis-data').textContent);
  const rows = data.samples;
  const $ = id => document.getElementById(id);
  const video = $('video'), canvas = $('chart'), ctx = canvas.getContext('2d'), scrubber = $('scrubber');
  let selected = 0, hover = null, geometry = null;
  let techniquePanel = null;
  let chatPanel = null;
  const clone = value => JSON.parse(JSON.stringify(value));
  const automatic = clone(data.repetitions || []), storageKey = 'gymbromatics-reps-v1-' + data.analysis_id;
  let reps = clone(automatic), activeId = null, wizard = null, history = [], pendingEdit = null, dragView = null;
  const markerNames = {start:'התחלה',bottom:'תחתית',end:'סיום'};
  const markerColors = {start:'#46d9ed',bottom:'#f6c36a',end:'#cf98fa'};
  const activeRep = () => reps.find(r => r.id === activeId);
  const snapshot = () => ({reps:clone(reps),activeId});
  function status(message, error=false) { $('rep-status').textContent=message; $('rep-status').dataset.error=String(error); }
  function validReps(items) {
    if(!Array.isArray(items) || items.length > rows.length)return false;
    const ids=new Set();let previous=-1;
    for(const rep of items) {
      if(!rep || typeof rep.id!=='string' || !rep.id || ids.has(rep.id))return false;
      ids.add(rep.id);
      if(!['start','bottom','end'].every(k=>Number.isInteger(rep[k])))return false;
      if(!(rep.start>=0 && rep.start<rep.bottom && rep.bottom<rep.end && rep.end<rows.length && rep.start>=previous))return false;
      if(!['auto','manual','edited'].includes(rep.source))return false;
      previous=rep.end;
    }
    return true;
  }
  try {
    const saved=JSON.parse(localStorage.getItem(storageKey));
    if(saved && saved.analysis_id===data.analysis_id && validReps(saved.repetitions)) {
      reps=clone(saved.repetitions);
      // Refresh derived data on load so obsolete metrics cannot persist in storage.
      localStorage.setItem(storageKey,JSON.stringify({analysis_id:data.analysis_id,repetitions:saved.repetitions,repetition_comparisons:compareRepetitions(rows,saved.repetitions,data.fps)}));
      status('התיקונים השמורים נטענו מהדפדפן.');
    } else status('הסימונים האוטומטיים הם הצעה. מומלץ לבדוק את הגבולות מול הסרטון.');
  } catch { status('שמירה בדפדפן אינה זמינה. ניתן לשמור תיקונים באמצעות ייצוא סימונים.'); }
  const currentComparisons = () => compareRepetitions(rows, reps, data.fps);
  const sessionData = () => ({...data,repetitions:reps,repetition_comparisons:currentComparisons()});
  function saveReps() {
    try { localStorage.setItem(storageKey,JSON.stringify({analysis_id:data.analysis_id,repetitions:reps,repetition_comparisons:currentComparisons()}));status('התיקונים נשמרו בדפדפן הזה. לניוד או גיבוי אפשר לייצא סימונים.'); }
    catch { status('לא ניתן לשמור בדפדפן. יש לייצא סימונים כדי לשמור את התיקונים.',true); }
    const previous=$('download').href;
    $('download').href=URL.createObjectURL(new Blob([JSON.stringify(sessionData(),null,2)],{type:'application/json'}));
    if(previous.startsWith('blob:'))URL.revokeObjectURL(previous);
  }
  function pushHistory(before) {history.push(before);if(history.length>100)history.shift();$('undo-rep').disabled=false;}
  function commit(before) {pushHistory(before);saveReps();renderReps();paint();}
  function viewRange() {
    if(dragView)return dragView;
    const rep=activeRep();
    return rep && $('zoom-rep').checked ? [Math.max(0,rep.start-Math.round(.3*data.fps)),Math.min(rows.length-1,rep.end+Math.round(.3*data.fps))] : [0,rows.length-1];
  }
  function renderSessionStats() {
    const body = $('session-stats-body');body.replaceChildren();
    $('session-stats-count').textContent = reps.length + ' חזרות · לחיצה על חזרה בוחרת אותה בסרטון ובגרף';
    reps.forEach((rep, index) => {
      const stats = calculateRepStats(rows, rep, data.fps);
      const tr = document.createElement('tr');tr.dataset.selected=String(rep.id===activeId);
      const heading = document.createElement('th');heading.scope='row';
      const button = document.createElement('button');button.type='button';button.textContent='חזרה '+(index+1);
      button.setAttribute('aria-pressed',String(rep.id===activeId));button.onclick=()=>chooseRep(rep.id);
      heading.append(button);tr.append(heading);
      for (const [value, digits, partial] of [[stats.duration,2,false],[stats.knee,1,stats.kneePartial],[stats.pause,2,false],[stats.peak,1,stats.peakPartial]]) {
        const td=document.createElement('td');td.textContent=value===null?'—':value.toFixed(digits)+(partial?' *':'');
        if(partial)td.title='נתונים חלקיים: הערך חושב רק מהפריימים הזמינים';
        tr.append(td);
      }
      body.append(tr);
    });
    if(!reps.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='אין חזרות להצגה. ניתן להוסיף חזרה באמצעות כלי הסימון.';tr.append(td);body.append(tr);}
  }
  function renderReps() {
    renderSessionStats();
    techniquePanel?.render(reps,activeId);
    chatPanel?.render();
    const list=$('rep-list');list.replaceChildren();
    const all=document.createElement('button');all.type='button';all.id='all-reps';all.textContent='כל הסרטון';
    all.setAttribute('aria-pressed',String(!activeId));all.onclick=()=>chooseRep(null);list.append(all);
    reps.forEach((rep,i)=>{
      const button=document.createElement('button');button.type='button';button.dataset.repId=rep.id;
      button.setAttribute('aria-pressed',String(rep.id===activeId));button.append(document.createTextNode('חזרה '+(i+1)));
      const times=document.createElement('small');times.textContent=(rep.start/data.fps).toFixed(2)+' – '+(rep.end/data.fps).toFixed(2)+' s';button.append(times);
      const origin=document.createElement('small');origin.dir='rtl';origin.textContent=rep.source==='manual'?'סימון ידני':rep.source==='edited'?'תוקן ידנית':rep.needs_review?'אוטומטי · לבדיקה':'זיהוי אוטומטי';button.append(origin);
      button.onclick=()=>chooseRep(rep.id);list.append(button);
    });
    $('rep-count').textContent=reps.length+' חזרות';
    const rep=activeRep(),index=reps.indexOf(rep);
    $('rep-editor').hidden=!rep;$('zoom-rep').disabled=!rep;$('loop-rep').disabled=!rep;
    $('rep-selection').textContent=rep?'חזרה '+(index+1)+' נבחרה':'כל הסרטון';
    $('rep-summary').textContent=rep?'משך: '+((rep.end-rep.start)/data.fps).toFixed(2)+' שנ׳ · ירידה עד התחתית: '+((rep.bottom-rep.start)/data.fps).toFixed(2)+' שנ׳ · עלייה: '+((rep.end-rep.bottom)/data.fps).toFixed(2)+' שנ׳':reps.length?'בחר חזרה כדי להתמקד בה, לנגן אותה או לתקן את הסימונים.':'לא זוהו חזרות מלאות. אפשר לסמן אותן בעזרת ״הוספת חזרה״.';
    for(const key of ['start','bottom','end']) {
      const handle=$('handle-'+key);handle.textContent=markerNames[key];handle.setAttribute('aria-label','גרירת '+markerNames[key]+', אפשר גם להשתמש בחיצים');handle.hidden=!rep;
      if(!rep)continue;
      const slider=$('mark-'+key);
      slider.min=key==='start'?(index>0?reps[index-1].end:0):key==='bottom'?rep.start+1:rep.bottom+1;
      slider.max=key==='end'?(index<reps.length-1?reps[index+1].start:rows.length-1):key==='bottom'?rep.end-1:rep.bottom-1;
      slider.value=rep[key];$('value-'+key).textContent=(rep[key]/data.fps).toFixed(2)+' s · '+(rep[key]+1);
    }
    $('rep-wizard').hidden=!wizard;$('add-rep').disabled=!!wizard;
    $('undo-rep').disabled=!history.length || !!wizard;
    $('reset-reps').disabled=!!wizard;$('import-reps').disabled=!!wizard;
    if(wizard){const stage=wizard.length;$('wizard-help').textContent=['שלב 1 מתוך 3: בחר בגרף או בסרטון את תחילת הירידה ולחץ על סימון.','שלב 2 מתוך 3: עבור לתחתית הסקוואט וסמן אותה.','שלב 3 מתוך 3: עבור לסיום העלייה וסמן אותו.'][stage];$('record-marker').textContent=['סמן התחלה כאן','סמן תחתית כאן','סמן סיום ושמור'][stage];}
  }
  function chooseRep(id) {if(wizard){status('סיים או בטל את הוספת החזרה לפני מעבר לחזרה אחרת.',true);return;}video.pause();activeId=id;hover=null;renderReps();if(activeRep())seek(activeRep().start);else update(selected);}
  function beginEdit(){if(!pendingEdit)pendingEdit=snapshot();}
  function endEdit(){if(pendingEdit){const before=pendingEdit;pendingEdit=null;if(JSON.stringify(before.reps)!==JSON.stringify(reps))commit(before);}dragView=null;paint();}
  function editMarker(key,index) {
    const rep=activeRep();if(!rep)return false;
    const proposal=reps.map(r=>r.id===rep.id?{...r,[key]:index,source:r.source==='manual'?'manual':'edited',needs_review:false}:r);
    if(!validReps(proposal)){status('הסימון חייב לשמור על התחלה < תחתית < סיום, ללא חפיפה עם חזרה אחרת.',true);return false;}
    reps=proposal;renderReps();seek(index);return true;
  }
  const lastTime = rows[rows.length - 1].time;
  const finiteVelocities = rows.filter(r => r.velocity !== null).map(r => Math.abs(r.velocity));
  const rawMaximum = finiteVelocities.reduce((a,b) => Math.max(a,b), 0);
  const magnitude = Math.max(10, Math.ceil(rawMaximum * 1.15 / 10) * 10);
  const colors = {grid:'#293749',text:'#a3b3c6',line:'#46d9ed',zero:'#647d93',cursor:'#e6f1fa'};
  const angleText = value => value === null ? '—' : value.toFixed(1) + '°';
  const velocityText = value => value === null ? '—' : (Math.abs(value) < .05 ? '0.0' : (value > 0 ? '+' : '') + value.toFixed(1));
  $('file-name').textContent = data.name + '  /  ' + data.duration.toFixed(2) + ' s  /  ' + data.fps.toFixed(2) + ' fps';
  $('end-time').textContent = lastTime.toFixed(2) + ' s';
  $('method').textContent = 'מסלול מרכז הכתפיים מוחלק באמצעות Savitzky–Golay, בחלון של עד ' + data.measurement.window_frames + ' פריימים, לפני חישוב הנגזרת לפי הזמן. חוסרים קצרים של עד 0.15 שניות מושלמים באינטרפולציה; חוסרים ארוכים מופיעים כפער בגרף. הזוויות נלקחות מהפריים המקורי ואינן מושלמות. ערכי הקצה עשויים להיות פחות יציבים.';
  scrubber.max = rows.length - 1;
  $('download').href = URL.createObjectURL(new Blob([JSON.stringify(sessionData(),null,2)],{type:'application/json'}));

  function paint() {
    const width = canvas.clientWidth, height = canvas.clientHeight, ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    ctx.setTransform(ratio,0,0,ratio,0,0);
    const left = 58, right = width - 20, top = 28, bottom = height - 34;
    const [first,last]=viewRange(),startTime=rows[first].time,stopTime=Math.max(rows[last].time,startTime+1/data.fps),span=stopTime-startTime;
    const x = t => left + (t-startTime) / span * (right-left), y = v => top + (magnitude-v)/(2*magnitude)*(bottom-top);
    geometry = {left,right,top,bottom,x,y,width,height,startTime,span};
    scrubber.min=first;scrubber.max=last;
    $('begin-time').textContent=startTime.toFixed(2)+' s';$('end-time').textContent=rows[last].time.toFixed(2)+' s';
    ctx.font = '12px Segoe UI, Arial'; ctx.lineWidth = 1;
    for(let i=-2;i<=2;i++) {
      const value = magnitude * i/2, yy = y(value);
      ctx.strokeStyle = i===0 ? colors.zero : colors.grid;
      ctx.beginPath();ctx.moveTo(left,yy);ctx.lineTo(right,yy);ctx.stroke();
      ctx.fillStyle = colors.text;ctx.textAlign='right';ctx.fillText(value.toFixed(0),left-10,yy+4);
    }
    const ticks = width < 450 ? 4 : 8;
    for(let i=0;i<=ticks;i++) {
      const time = startTime + span * i/ticks, xx=x(time);
      ctx.strokeStyle=colors.grid;ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,bottom);ctx.stroke();
      ctx.fillStyle=colors.text;ctx.textAlign='center';ctx.fillText(time.toFixed(1),xx,bottom+20);
    }
    ctx.textAlign='left';ctx.fillStyle=colors.text;ctx.fillText('px/s',8,15);
    ctx.textAlign='right';ctx.fillText('זמן (שניות)',right,height-1);
    ctx.save();ctx.beginPath();ctx.rect(left,top,right-left,bottom-top);ctx.clip();
    for(const rep of reps){ctx.fillStyle=rep.id===activeId?'#46d9ed17':'#cf98fa09';ctx.fillRect(x(rows[rep.start].time),top,x(rows[rep.end].time)-x(rows[rep.start].time),bottom-top);}
    // Draw each finite run separately so missing tracking never looks continuous.
    const segments=[];let segment=[];
    for(const row of rows.slice(first,last+1)) {
      if(row.velocity===null){if(segment.length)segments.push(segment);segment=[];}
      else segment.push(row);
    }
    if(segment.length)segments.push(segment);
    for(const run of segments) {
      ctx.beginPath();ctx.moveTo(x(run[0].time),y(0));
      for(const row of run)ctx.lineTo(x(row.time),y(row.velocity));
      ctx.lineTo(x(run[run.length-1].time),y(0));ctx.closePath();ctx.fillStyle='#46d9ed13';ctx.fill();
      ctx.beginPath();run.forEach((row,i)=>i?ctx.lineTo(x(row.time),y(row.velocity)):ctx.moveTo(x(row.time),y(row.velocity)));
      ctx.lineWidth=2.3;ctx.strokeStyle=colors.line;ctx.stroke();
    }
    if(!finiteVelocities.length){ctx.fillStyle=colors.text;ctx.textAlign='center';ctx.fillText('אין מספיק נתוני כתפיים לחישוב מהירות',width/2,height/2);}
    const row=rows[selected],xx=x(row.time);
    ctx.setLineDash([4,4]);ctx.lineWidth=1;ctx.strokeStyle=colors.cursor;
    ctx.beginPath();ctx.moveTo(xx,top);ctx.lineTo(xx,bottom);ctx.stroke();ctx.setLineDash([]);
    if(row.velocity!==null){ctx.beginPath();ctx.arc(xx,y(row.velocity),5,0,Math.PI*2);ctx.fillStyle=colors.cursor;ctx.fill();ctx.lineWidth=2;ctx.strokeStyle='#132331';ctx.stroke();}
    if(hover!==null && rows[hover].velocity!==null){ctx.beginPath();ctx.arc(x(rows[hover].time),y(rows[hover].velocity),4,0,Math.PI*2);ctx.fillStyle=colors.line;ctx.fill();}
    const rep=activeRep();
    for(const key of ['start','bottom','end']) {
      const handle=$('handle-'+key);handle.hidden=!rep;
      if(!rep)continue;
      const markerX=x(rows[rep[key]].time);handle.style.left=markerX+'px';
      ctx.setLineDash([3,4]);ctx.strokeStyle=markerColors[key];ctx.lineWidth=1.5;
      ctx.beginPath();ctx.moveTo(markerX,top);ctx.lineTo(markerX,bottom);ctx.stroke();ctx.setLineDash([]);
    }
    ctx.restore();
  }

  function update(index, announce=false) {
    selected = Math.max(0,Math.min(rows.length-1,Math.round(index)));
    const row=rows[selected];scrubber.value=selected;
    $('time').textContent=row.time.toFixed(2);
    $('frame-label').textContent='פריים ' + (row.frame+1) + ' מתוך ' + rows.length;
    $('side').textContent=row.side==='left'?'צד שמאל':row.side==='right'?'צד ימין':'אין צד מזוהה';
    for(const name of ['knee','hip','ankle'])$(name).textContent=angleText(row[name]);
    $('velocity').textContent=velocityText(row.velocity);
    $('quality').textContent=row.velocity===null?'מהירות לא זמינה':row.interpolated?'מיקום משוער בפער קצר':'מסלול מוחלק';
    $('direction').textContent=row.velocity===null?'חסרות מדידות אמינות':Math.abs(row.velocity)<.05?'ללא תנועה אנכית מדידה':row.velocity>0?'תנועה כלפי מעלה':'תנועה כלפי מטה';
    const [first,last]=viewRange();$('prev').disabled=selected<=first;$('next').disabled=selected>=last;
    if(announce)$('announcement').textContent=`זמן ${row.time.toFixed(2)} שניות. ברך ${angleText(row.knee)}, אגן ${angleText(row.hip)}, קרסול ${angleText(row.ankle)}.`;
    paint();
  }

  function seek(index) {
    const [first,last]=viewRange();video.pause(); update(Math.max(first,Math.min(last,index)),true);
    // Seek inside the selected frame, not onto a codec boundary rounded backward.
    const time=rows[selected].time + .05/data.fps;
    if(video.readyState>=1)video.currentTime=Math.min(time,video.duration);
  }
  function indexAt(event) {
    const rect=canvas.getBoundingClientRect();
    const fraction=Math.max(0,Math.min(1,(event.clientX-rect.left-geometry.left)/(geometry.right-geometry.left)));
    return Math.max(0,Math.min(rows.length-1,Math.round((geometry.startTime+fraction*geometry.span)*data.fps)));
  }
  canvas.addEventListener('click',event=>seek(indexAt(event)));
  canvas.addEventListener('pointermove',event=>{
    hover=indexAt(event);paint();const row=rows[hover],tip=$('tooltip');
    tip.textContent=row.time.toFixed(2)+' s  ·  '+velocityText(row.velocity)+' px/s';
    tip.style.display='block';tip.style.direction='ltr';
    const x=geometry.x(row.time);
    tip.style.left=Math.max(0,Math.min(canvas.clientWidth-tip.offsetWidth,x-tip.offsetWidth/2))+'px';
    tip.style.top='0px';
  });
  canvas.addEventListener('pointerleave',()=>{hover=null;$('tooltip').style.display='none';paint();});
  scrubber.addEventListener('input',()=>seek(Number(scrubber.value)));
  $('prev').addEventListener('click',()=>seek(selected-1));$('next').addEventListener('click',()=>seek(selected+1));
  $('speed').addEventListener('change',()=>{video.playbackRate=Number($('speed').value);});
  $('play').addEventListener('click',async()=>{
    if(video.paused){const rep=activeRep();if(rep && (selected<rep.start || selected>=rep.end))seek(rep.start);else if(video.ended)seek(0);try{await video.play();}catch(error){$('video-error').hidden=false;}}
    else video.pause();
  });
  video.addEventListener('play',()=>{$('play').textContent='השהיה';$('play').setAttribute('aria-label','השהיית הסרטון');});
  video.addEventListener('pause',()=>{$('play').textContent='ניגון';$('play').setAttribute('aria-label','ניגון הסרטון');});
  video.addEventListener('error',()=>{$('video-error').hidden=false;});
  video.addEventListener('loadedmetadata',()=>{video.currentTime=rows[selected].time+.05/data.fps;});
  let looping=false;
  function followFrame(time) {
    if(looping)return;
    const rep=activeRep(),index=Math.floor(time*data.fps+1e-5);
    if(rep && index>=rep.end){
      if($('loop-rep').checked){looping=true;video.currentTime=rows[rep.start].time+.05/data.fps;update(rep.start);}
      else seek(rep.end);
    }else update(index);
  }
  video.addEventListener('seeked',()=>{looping=false;});
  video.addEventListener('timeupdate',()=>{if(!video.paused && activeRep() && video.currentTime >= rows[activeRep().end].time)followFrame(video.currentTime);});
  if('requestVideoFrameCallback' in video){
    const follow=(now,meta)=>{if(!video.paused)followFrame(meta.mediaTime);video.requestVideoFrameCallback(follow);};
    video.requestVideoFrameCallback(follow);
  }else video.addEventListener('timeupdate',()=>{if(!video.paused)followFrame(video.currentTime);});
  video.addEventListener('ended',()=>{const rep=activeRep();if(rep && $('loop-rep').checked){seek(rep.start);video.play().catch(()=>{$('video-error').hidden=false;});}else update(rep?rep.end:rows.length-1);});
  $('zoom-rep').addEventListener('change',()=>{hover=null;const rep=activeRep();if(rep && $('zoom-rep').checked)seek(Math.max(rep.start,Math.min(rep.end,selected)));else update(selected);});
  for(const key of ['start','bottom','end']) {
    const slider=$('mark-'+key),handle=$('handle-'+key);
    slider.addEventListener('input',()=>{beginEdit();editMarker(key,Number(slider.value));});
    slider.addEventListener('change',endEdit);
    $('set-'+key).addEventListener('click',()=>{beginEdit();editMarker(key,selected);endEdit();});
    handle.addEventListener('pointerdown',event=>{if(event.button!==0)return;video.pause();beginEdit();dragView=viewRange().slice();handle.setPointerCapture(event.pointerId);handle.dataset.dragging='true';});
    handle.addEventListener('pointermove',event=>{if(handle.dataset.dragging!=='true')return;const min=Number(slider.min),max=Number(slider.max);editMarker(key,Math.max(min,Math.min(max,indexAt(event))));});
    const finish=()=>{if(handle.dataset.dragging==='true'){handle.dataset.dragging='false';endEdit();}};
    handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
    handle.addEventListener('keydown',event=>{if(!['ArrowLeft','ArrowRight'].includes(event.key))return;event.preventDefault();beginEdit();editMarker(key,activeRep()[key]+(event.key==='ArrowRight'?1:-1));endEdit();});
  }
  $('add-rep').addEventListener('click',()=>{video.pause();activeId=null;wizard=[];renderReps();update(selected);status('בחר פריים להתחלת החזרה. אפשר לנגן, לעצור ולדייק פריים־פריים.');});
  $('cancel-rep').addEventListener('click',()=>{wizard=null;renderReps();status('הוספת החזרה בוטלה.');});
  $('record-marker').addEventListener('click',()=>{
    if(!wizard)return;video.pause();
    if(wizard.length && selected<=wizard[wizard.length-1]){status('בחר פריים מאוחר יותר מהסימון הקודם.',true);return;}
    if(wizard.length<2){wizard.push(selected);renderReps();return;}
    const rep={id:'manual-'+Date.now()+'-'+Math.random().toString(36).slice(2,7),start:wizard[0],bottom:wizard[1],end:selected,source:'manual',needs_review:false};
    const proposal=[...reps,rep].sort((a,b)=>a.start-b.start);
    if(!validReps(proposal)){status('הטווח חופף לחזרה קיימת. בטל את ההוספה ותקן או מחק את החזרה הקיימת.',true);return;}
    const before=snapshot();reps=proposal;activeId=rep.id;wizard=null;commit(before);seek(rep.start);
  });
  $('delete-rep').addEventListener('click',()=>{if(!activeRep())return;const before=snapshot();video.pause();reps=reps.filter(r=>r.id!==activeId);activeId=null;commit(before);update(selected);});
  $('undo-rep').addEventListener('click',()=>{const previous=history.pop();if(!previous)return;video.pause();reps=previous.reps;activeId=previous.activeId;saveReps();renderReps();if(activeRep())seek(activeRep().start);else update(selected);});
  $('reset-reps').addEventListener('click',()=>{const before=snapshot();video.pause();reps=clone(automatic);activeId=null;commit(before);update(selected);});
  $('export-reps').addEventListener('click',()=>{
    const output={schema_version:1,analysis_id:data.analysis_id,video:data.name,fps:data.fps,frame_count:rows.length,repetition_comparisons:currentComparisons(),repetitions:reps.map(r=>({...r,start_seconds:r.start/data.fps,bottom_seconds:r.bottom/data.fps,end_seconds:r.end/data.fps}))};
    const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(output,null,2)],{type:'application/json'}));link.download=data.name.replace(/\.[^.]+$/,'')+'_repetitions.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  });
  $('import-reps').addEventListener('change',async event=>{
    const file=event.target.files[0];if(!file)return;
    try {
      if(file.size>2000000)throw new Error('קובץ הסימונים גדול מדי.');
      const imported=JSON.parse(await file.text());
      if(imported.schema_version!==1 || imported.analysis_id!==data.analysis_id)throw new Error('הסימונים אינם שייכים לניתוח הסרטון הזה.');
      if(!validReps(imported.repetitions))throw new Error('גבולות החזרות אינם תקינים או שיש חפיפה ביניהם.');
      const before=snapshot();video.pause();reps=imported.repetitions.map(({id,start,bottom,end,source,needs_review})=>({id,start,bottom,end,source,needs_review:!!needs_review}));activeId=null;commit(before);update(selected);
    }catch(error){status('הייבוא לא בוצע: '+error.message,true);}finally{event.target.value='';}
  });
  new ResizeObserver(()=>paint()).observe(canvas);
  techniquePanel = createTechniquePanel({data,video,getReps:()=>reps,
    seekReference:frame=>{if(wizard)return false;chooseRep(null);seek(frame);return true;},
    selectEvidence:(id,frame)=>{if(wizard)return;chooseRep(id);seek(frame);$('video').scrollIntoView({behavior:'smooth',block:'center'});}});
  chatPanel=createChatPanel({data,getReps:()=>reps,getActiveId:()=>activeId,chooseRep,
    selectEvidence:(id,frame)=>{if(wizard)return;chooseRep(id);seek(frame);video.scrollIntoView({behavior:'smooth',block:'center'});}});
  renderReps();
  update(0);
})();
