/* Rendering/calibration adapter; the rules in technique.js are DOM independent. */
function createTechniquePanel({data,video,seekReference,selectEvidence,getReps}) {
  const $=id=>document.getElementById(id), geo=data.technique;
  const storeKey='gymbromatics-technique-v1-'+data.analysis_id;
  let activeId=null,reps=[],results=[],calibration=null,referenceFrame=null,frozen=null;
  let autoEstimate=null,manual=null,signature=null,headPercent=6;
  const settings={...SquatTechnique.defaults};
  settings.footSide=geo.foot_side;
  const names={depth:'עומק ביחס ליעד',coordination:'תיאום אגן–כתפיים',heel:'הרמת עקב משוערת'};
  const reasons={knee_not_visible:'אין מספיק מדידות אמינות של זווית הברך בחזרה או סביב התחתית',bottom_not_visible:'אין מספיק נקודות אמינות סביב התחתית',ascent_not_visible:'אין מספיק נתונים רציפים בתחילת העלייה',
    foot_not_visible:'העקב או האצבעות מוסתרים בתחילת החזרה',foot_moving_or_hidden:'כף הרגל זזה בפריים או אינה נראית לאורך החזרה',
    foot_too_small:'כף הרגל קטנה מדי בתמונה למדידה',invalid_rep:'גבולות החזרה אינם מתאימים'};
  function cm(px){return calibration && Number.isFinite(px)?' · כ־'+Math.abs(px*calibration.cmPerPixel).toFixed(1)+' ס״מ':'';}
  function text(result) {
    if(result.status==='unavailable')return reasons[result.reason]||'אין מספיק נתונים';
    if(result.key==='depth') {
      return 'זווית הברך המינימלית בחזרה: '+result.angle.toFixed(2)+'°. '+
        (result.status==='review'?'מעל 90° — יעד העומק לא הושג.':'90° ומטה — יעד העומק הושג.')+
        (result.partial?' המדידה מבוססת על הפריימים האמינים הזמינים.':'');
    }
    if(result.key==='coordination')return result.status==='review'?
      'בתחילת העלייה האגן הקדים את הכתפיים, ונטיית הגו גדלה ב־'+result.event.leanChange.toFixed(1)+'°'+cm(result.deltaPx)+'. כדאי לבדוק את הקטע.':
      'לא זוהה שינוי מתמשך שעבר את שני ספי התיאום.';
    return result.status==='review'?'העקב עלה ביחס לאצבעות ולמנח ההתחלתי'+cm(result.deltaPx)+'. חשד להרמת עקב; יש לבדוק בסרטון.':
      'לא זוהתה הרמת עקב מתמשכת מעל הסף ביחס לתחילת החזרה.';
  }
  function exportData(){return {method:'side-view geometry v2',foot_selection:$('near-foot').value,settings:{...settings},calibration:calibration?{...calibration,referenceFrame}:null,
    calibration_estimate:autoEstimate,calibration_manual:manual,
    height_cm:Number($('user-height').value)||null,repetitions:reps.map((rep,i)=>({...rep,assessment:results[i]}))};}
  function download() {
    const link=document.createElement('a');link.href=URL.createObjectURL(new Blob([JSON.stringify(exportData(),null,2)],{type:'application/json'}));
    link.download=data.name.replace(/\.[^.]+$/,'')+'_technique.json';link.click();setTimeout(()=>URL.revokeObjectURL(link.href),1000);
  }
  function persist(){try{localStorage.setItem(storeKey,JSON.stringify({height:$('user-height').value,footChoice:$('near-foot').value,
    segmentCalibrationVersion:1,headPercent,manual}));}catch{}}
  function updateCalibration() {
    render(reps,activeId);persist();
  }
  function syncCalibration() {
    referenceFrame=reps[0]?.start??null;
    const next=referenceFrame===null?null:referenceFrame+':'+settings.footSide;
    if(signature!==next || !autoEstimate){
      signature=next;autoEstimate=BodyCalibration.estimate(geo.frames,referenceFrame,data.fps,settings.footSide);
      if(manual && manual.signature!==signature)manual=null;
      frozen=null;$('cal-preview').hidden=true;
    }
    const segments=manual?.segments??(autoEstimate.available?autoEstimate.segments:null);
    const physical=referenceFrame===null?null:BodyCalibration.scale(Number($('user-height').value),segments,headPercent);
    calibration=physical?{...physical,mode:manual?'manual-segments':'auto-segments',referenceFrame,side:settings.footSide,version:1}:null;
    for(const key of BodyCalibration.keys){const value=segments?.[key];$('cal-'+key).value=Number.isFinite(value)?String(Math.round(value*100)/100):'';}
    $('cal-head').value=Number.isFinite(headPercent)?headPercent:'';
    const estimate=BodyCalibration.scale(180,segments,headPercent);
    $('cal-total').textContent=estimate?'גובה בתמונה: '+estimate.totalPixels.toFixed(1)+' פיקסלים, כולל '+estimate.headPixels.toFixed(1)+' פיקסלים לתוספת הראש.':'אין עדיין סכום מקטעים תקין.';
    $('cal-status').textContent=calibration?'כיול '+(manual?'בתיקון ידני':'אוטומטי')+' משוער פעיל: '+calibration.cmPerPixel.toFixed(3)+' ס״מ לפיקסל · תחילת חזרה ראשונה, פריים '+(referenceFrame+1):
      (autoEstimate.available?'אומדן המקטעים מוכן. הזינו גובה תקין בס״מ להפעלת הכיול. ללא כיול, המדדים היחסיים עדיין זמינים.':
      'ללא כיול בסנטימטרים: '+({no_rep:'אין חזרה ראשונה מסומנת.',insufficient_pose:'אין מספיק פריימים זקופים עם נקודות גוף אמינות בתחילת החזרה.',unstable:'אומדן אורך הגוף אינו יציב סביב תחילת החזרה.'}[autoEstimate.reason]||'יש לבדוק את ערכי המקטעים.'));
    if(manual && !physical)$('cal-status').textContent='ללא כיול פעיל: נדרשים גובה תקין, חמשת אורכי המקטעים ותוספת ראש בטווח 0–20%.';
    if(!Number.isFinite(headPercent)||headPercent<0||headPercent>20)$('cal-status').textContent='ללא כיול בסנטימטרים — תוספת הראש צריכה להיות מספר בטווח 0–20%.';
    $('cal-help').textContent=(autoEstimate.available?'חציון מתוך '+autoEstimate.validFrames+' פריימים זקופים סמוכים לתחילת החזרה. ':'אפשר לתקן את תחילת החזרה או להזין ידנית את אורכי המקטעים. ')+
      (manual?'מופעל תיקון ידני; הקווים בתצוגה מציגים את הזיהוי המקורי.':'התוספת מעל האוזן היא הנחת עבודה ניתנת לתיקון, ולא מדידה של קודקוד הראש.');
    drawCalibration();
  }
  function drawCalibration() {
    if(!frozen)return;const canvas=$('cal-canvas'),ctx=canvas.getContext('2d');ctx.drawImage(frozen,0,0);
    const p=autoEstimate.points;if(!p)return;
    const chain=[[p.ankle[0],autoEstimate.floorY],p.ankle,p.knee,p.hip,p.shoulder,p.ear];
    ctx.strokeStyle='#46d9ed';ctx.lineWidth=Math.max(2,canvas.width/400);ctx.beginPath();chain.forEach((v,i)=>i?ctx.lineTo(...v):ctx.moveTo(...v));ctx.stroke();
    chain.forEach(v=>{ctx.beginPath();ctx.arc(...v,Math.max(3,canvas.width/240),0,Math.PI*2);ctx.fillStyle='#46d9ed';ctx.fill();});
    const head=BodyCalibration.scale(180,autoEstimate.segments,headPercent)?.headPixels;
    if(head){ctx.setLineDash([6,4]);ctx.strokeStyle='#f6c36a';ctx.beginPath();ctx.moveTo(...p.ear);ctx.lineTo(p.ear[0],p.ear[1]-head);ctx.stroke();ctx.setLineDash([]);}
  }
  async function capture() {
    const first=getReps()[0];
    if(!first){$('cal-help').textContent='יש לסמן חזרה ראשונה לפני בחירת פריים הכיול.';return;}
    $('cal-capture').disabled=true;
    try {
      if(!seekReference(autoEstimate.previewFrame??first.start))return;
      // Wait for decoded pixels, not just the requested currentTime.
      await new Promise((resolve,reject)=>{
        const timer=setTimeout(()=>{video.removeEventListener('seeked',done);reject(new Error('הפריים לא נטען. נסו שוב לאחר טעינת הסרטון.'));},5000);
        function done(){clearTimeout(timer);resolve();}
        if(!video.seeking && video.readyState>=2){clearTimeout(timer);resolve();}else video.addEventListener('seeked',done,{once:true});
      });
      const canvas=$('cal-canvas');canvas.width=geo.width;canvas.height=geo.height;
      frozen=document.createElement('canvas');frozen.width=canvas.width;frozen.height=canvas.height;
      frozen.getContext('2d').drawImage(video,0,0,canvas.width,canvas.height);
      $('cal-preview').hidden=false;drawCalibration();
    }catch(error){$('cal-help').textContent=error.message;}finally{$('cal-capture').disabled=false;}
  }
  function render(nextReps,nextActive) {
    reps=nextReps;activeId=nextActive;
    syncCalibration();
    $('foot-side-info').textContent='בדיקת העקב משתמשת רק ברגל '+(settings.footSide==='left'?'שמאל':'ימין')+' של המתאמן, לכל הסרטון. '+
      ($('near-foot').value==='auto'?'הבחירה האוטומטית נעשתה לפי נראות; ודאו שזו הרגל הקרובה למצלמה.':'בחירה ידנית של הרגל הקרובה.');
    results=reps.map(rep=>SquatTechnique.assess(geo.frames,rep,data.fps,settings));
    const counts={};for(const key of Object.keys(names))counts[key]={review:0,available:0};
    results.forEach(result=>Object.entries(result).forEach(([key,v])=>{if(v.status!=='unavailable')counts[key].available++;if(v.status==='review')counts[key].review++;}));
    $('technique-summary').textContent=!reps.length?'אין חזרות להערכה.':Object.keys(names).map(key=>names[key]+': '+counts[key].review+' הערות מתוך '+counts[key].available+' חזרות עם נתונים זמינים').join(' · ');
    $('technique-selection').textContent=activeId?'הערות לחזרה '+(reps.findIndex(r=>r.id===activeId)+1):'הערות לכל החזרות';
    const container=$('technique-cards');container.replaceChildren();
    reps.forEach((rep,i)=>{
      if(activeId && rep.id!==activeId)return;
      const card=document.createElement('details');card.className='technique-rep';card.open=!!activeId;
      const h=document.createElement('summary');
      const reviews=Object.values(results[i]).filter(x=>x.status==='review').length;
      const missing=Object.values(results[i]).filter(x=>x.status==='unavailable').length;
      h.textContent='חזרה '+(i+1)+' · '+(reviews?reviews+' הערות לבדיקה':missing===3?'אין מספיק נתונים להערכה':'לא נמצאה חריגה מהספים')+(missing?' · '+missing+' בדיקות לא זמינות':'');card.append(h);
      for(const [key,result] of Object.entries(results[i])) {
        const row=document.createElement('div');row.className='technique-note';row.dataset.status=result.status;
        const heading=document.createElement('strong');heading.textContent=names[key];row.append(heading);
        const badge=document.createElement('span');badge.className='badge';badge.textContent={review:'לבדיקה',clear:'ללא חריגה מהסף',borderline:'סמוך ליעד',unavailable:'לא ניתן להעריך'}[result.status];row.append(badge);
        const p=document.createElement('p');p.textContent=text(result);row.append(p);
        if((result.status==='review' || key==='depth') && Number.isInteger(result.frame)) {
          const button=document.createElement('button');button.type='button';button.textContent='צפייה ב־'+(result.frame/data.fps).toFixed(2)+' שנ׳';
          button.onclick=()=>selectEvidence(rep.id,result.frame);row.append(button);
        }
        card.append(row);
      }
      container.append(card);
    });
  }
  try {
    const saved=JSON.parse(localStorage.getItem(storeKey));
    if(saved){
      if(Number(saved.height)>=80 && Number(saved.height)<=250)$('user-height').value=saved.height;
      if(['auto','left','right'].includes(saved.footChoice)){$('near-foot').value=saved.footChoice;settings.footSide=saved.footChoice==='auto'?geo.foot_side:saved.footChoice;}
      if(saved.segmentCalibrationVersion===1){
        headPercent=Number.isFinite(saved.headPercent)&&saved.headPercent>=0&&saved.headPercent<=20?saved.headPercent:NaN;
        if(saved.manual && typeof saved.manual.signature==='string' && saved.manual.segments)manual=saved.manual;
      }
    }
  }catch{}
  $('user-height').addEventListener('input',updateCalibration);
  $('near-foot').addEventListener('change',()=>{settings.footSide=$('near-foot').value==='auto'?geo.foot_side:$('near-foot').value;persist();render(reps,activeId);});
  $('cal-capture').addEventListener('click',capture);
  $('cal-clear').addEventListener('click',()=>{manual=null;headPercent=6;updateCalibration();});
  for(const key of BodyCalibration.keys)$('cal-'+key).addEventListener('change',()=>{
    manual={signature,segments:Object.fromEntries(BodyCalibration.keys.map(k=>[k,$('cal-'+k).value===''?null:Number($('cal-'+k).value)]))};updateCalibration();
  });
  $('cal-head').addEventListener('change',()=>{headPercent=$('cal-head').value===''?NaN:Number($('cal-head').value);updateCalibration();});
  $('export-technique').addEventListener('click',download);
  reps=getReps();updateCalibration();
  return {render,exportData};
}
