function createChatPanel({data,getReps,getActiveId,chooseRep,selectEvidence}) {
  const $=id=>document.getElementById(id),form=$('chat-form'),input=$('chat-input'),select=$('chat-rep');
  const log=$('chat-log'),status=$('chat-status'),send=$('chat-send');
  const online=!!window.GYM_CHAT_TOKEN&&['http:','https:'].includes(location.protocol);
  let conversation=null,busy=false,signature=null;
  const foot=()=>{const choice=$('near-foot')?.value;return ['left','right'].includes(choice)?choice:null;};
  const snapshot=()=>JSON.stringify({reps:getReps(),foot:foot()});
  const say=text=>{status.textContent=text;};
  const errors={quota_exceeded:'המכסה החינמית הסתיימה. אפשר לנסות שוב מאוחר יותר.',
    missing_api_key:'חסר מפתח Gemini בקובץ ההגדרות של השרת.',free_tier_not_confirmed:'יש לאשר בהגדרות שהפרויקט במסלול החינמי.',
    invalid_chat_response:'התשובה לא עברה את בדיקת הנתונים ולא הוצגה. אפשר לנסח מחדש את השאלה.',
    busy:'השרת מטפל כרגע בשאלה אחרת. נסה שוב בעוד רגע.',network_or_timeout:'החיבור למודל נכשל או ארך יותר מדי זמן.',
    model_unavailable:'המודל אינו זמין כרגע.',invalid_request:'נתוני השאלה או החזרות אינם תקינים.',
    invalid_conversation:'השיחה אינה זמינה בשרת. התחל שיחה חדשה.'};
  function bubble(role,text) {
    const article=document.createElement('article');article.className='chat-message '+role;
    const heading=document.createElement('strong');heading.textContent=role==='user'?'אתה':'GymBromatics';article.append(heading);
    if(text){const p=document.createElement('p');p.textContent=text;article.append(p);}
    log.append(article);return article;
  }
  function render() {
    const previous=signature;signature=snapshot();
    if(previous!==null&&previous!==signature) {
      conversation=null;
      log.querySelectorAll('.chat-evidence button').forEach(button=>button.disabled=true);
      if(log.children.length)say('הסימונים או הרגל הנבחרת השתנו. השאלה הבאה תשתמש בנתונים החדשים; הקישורים הישנים הושבתו.');
    }
    select.replaceChildren();
    const all=document.createElement('option');all.value='';all.textContent='כל הסשן';select.append(all);
    getReps().forEach((r,i)=>{const option=document.createElement('option');option.value=r.id;option.textContent='חזרה '+(i+1);select.append(option);});
    select.value=getActiveId()||'';
  }
  select.addEventListener('change',()=>chooseRep(select.value||null));
  $('near-foot')?.addEventListener('change',render);
  $('chat-clear').addEventListener('click',()=>{if(busy)return;conversation=null;log.replaceChildren();say('שיחה חדשה על הסשן הנוכחי.');});
  document.querySelectorAll('[data-chat-question]').forEach(button=>button.addEventListener('click',()=>{input.value=button.dataset.chatQuestion;input.focus();}));
  form.addEventListener('submit',async event=>{
    event.preventDefault();const message=input.value.trim();if(!online||busy||!message)return;
    render();const startSignature=signature,selected=getActiveId();
    const request={analysis_id:data.analysis_id,repetitions:getReps(),selected_rep_id:selected,foot_side:foot(),message,conversation_id:conversation};
    bubble('user',message+' — '+(select.selectedOptions[0]?.textContent||'כל הסשן'));
    busy=true;send.disabled=true;$('chat-clear').disabled=true;input.value='';say('בודק את נתוני הסשן ומנסח תשובה…');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),110000);
    try {
      const response=await fetch(`/sessions/${encodeURIComponent(data.analysis_id)}/chat`,{method:'POST',headers:{'Content-Type':'application/json','X-Chat-Token':window.GYM_CHAT_TOKEN},body:JSON.stringify(request),signal:controller.signal});
      const result=await response.json();
      if(!response.ok)throw new Error(errors[result.error]||'לא ניתן לקבל תשובה כרגע. נסה שוב מאוחר יותר.');
      if(snapshot()!==startSignature){say('הנתונים השתנו במהלך הבקשה. התשובה הישנה לא הוצגה; שלח שוב לפי הסימונים החדשים.');return;}
      conversation=result.conversation_id;
      const article=bubble('assistant');
      for(const paragraph of result.paragraphs) {
        const p=document.createElement('p');p.textContent=paragraph.text;article.append(p);
        const evidence=document.createElement('div');evidence.className='chat-evidence';
        for(const item of paragraph.evidence) {
          const card=document.createElement('details'),summary=document.createElement('summary');
          summary.textContent=item.label+(item.detail?' · '+item.detail:'');card.append(summary);
          if(item.fact.kind==='definition'){const definition=document.createElement('p');definition.textContent=item.fact.text;card.append(definition);}
          else {
            const fact=item.fact,lines=[];
            const fields={coverage:'שיעור הדגימות הזמינות',angle:'זווית הברך במעלות',leanChange:'שינוי בהטיית הגו במעלות',valid_repetitions:'חזרות עם נתונים זמינים',rep_count:'מספר חזרות',percent:'שינוי ביחס לערך ההשוואה באחוזים',slope_per_rep:'שיפוע המגמה לכל חזרה',interpolated_ascent_fraction:'שיעור הדגימות שהושלמו'};
            for(const [key,label] of Object.entries(fields))if(Number.isFinite(fact[key]))lines.push(label+': '+((key==='coverage'||key==='interpolated_ascent_fraction')?(fact[key]*100).toFixed(1)+'%':fact[key].toFixed(2)));
            if(fact.reason||fact.status==='unavailable')lines.push('אין די נתונים אמינים לחישוב או להשוואה הזו.');
            if(fact.kind==='context')lines.push('ניתוח צילום צד; המהירות נמדדת בפיקסלים לשנייה. אי אפשר להסיק ממנו את סיבת השינוי בביצוע.');
            if(fact.kind==='boundaries')lines.push('התחלה: '+fact.start_seconds.toFixed(2)+' שנ׳; תחתית: '+fact.bottom_seconds.toFixed(2)+' שנ׳; סיום: '+fact.end_seconds.toFixed(2)+' שנ׳.');
            if(fact.status==='clear')lines.push('הבדיקה לא חרגה מהספים שהוגדרו. זה אינו אישור כולל לטכניקה.');
            const detail=document.createElement('p');detail.textContent=lines.join(' · ')||item.detail||'נתון מחושב מתוך הסשן הנוכחי.';card.append(detail);
          }
          evidence.append(card);
          for(const link of item.links){const button=document.createElement('button');button.type='button';button.textContent='צפייה: '+link.label;button.onclick=()=>selectEvidence(link.rep_id,link.frame);evidence.append(button);}
        }
        article.append(evidence);
      }
      say(result.history_reset?'הנתונים עודכנו; השיחה חודשה לפי המדידות הנוכחיות.':'התשובה מבוססת על מדידות הסשן. פתח את הראיות כדי לבדוק אותה.');
      article.scrollIntoView({behavior:'smooth',block:'nearest'});
    } catch(error) {say(error.name==='AbortError'?'זמן ההמתנה הסתיים. לא בוצעה קריאה חוזרת אוטומטית.':error.message);input.value=message;}
    finally {clearTimeout(timer);busy=false;send.disabled=!online;$('chat-clear').disabled=false;}
  });
  input.disabled=!online;send.disabled=!online;
  say(online?'אפשר לשאול על הסשן או לבחור חזרה. ההודעות והמדדים נשלחים ל־Gemini במסגרת המכסה החינמית.':'הצ׳ט זמין דרך השרת המקומי. הפעל python -m gymbromatics.chat_server ופתח http://127.0.0.1:8765');
  render();return {render};
}
