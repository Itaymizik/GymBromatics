/* Browser counterpart of comparisons.py. Kept in parity by synthetic tests. */
function compareRepetitions(samples, repetitions, fps) {
  const units = {duration:'s',descent_duration:'s',ascent_duration:'s',min_knee_angle:'deg',
    min_hip_angle:'deg',min_ankle_angle:'deg',bottom_pause:'s',peak_ascent_velocity:'px/s',mean_ascent_velocity:'px/s'};
  if (!Number.isFinite(fps) || fps <= 0) throw new Error('Invalid FPS');
  const ids = new Set(); let previousEnd = -1;
  for (const rep of repetitions) {
    if (!['start','bottom','end'].every(k=>Number.isInteger(rep[k])) ||
        !(0<=rep.start && rep.start<rep.bottom && rep.bottom<rep.end && rep.end<samples.length && rep.start>=previousEnd) ||
        typeof rep.id!=='string' || !rep.id || ids.has(rep.id)) throw new Error('Invalid repetition boundaries/IDs');
    ids.add(rep.id); previousEnd=rep.end;
  }
  const measurement=(value,coverage=1,reason=null)=>({value,coverage,reason});
  const delta=(value,reference,unit,reason=null)=>{
    if(reason || value===null || reference===null) return {delta:null,percent:null,reason:reason||'unavailable_metric',percent_reason:reason||'unavailable_metric'};
    const difference=value-reference;
    const percentReason=unit==='deg'?'angular_metric':Math.abs(reference)<=(unit==='s'?.01:.1)?'near_zero_reference':null;
    return {delta:difference,percent:percentReason?null:difference/Math.abs(reference)*100,reason:null,percent_reason:percentReason};
  };
  const rows=repetitions.map((rep,i)=>{
    const segment=samples.slice(rep.start,rep.end+1), ascent=samples.slice(rep.bottom,rep.end+1);
    const stats=calculateRepStats(samples,rep,fps);
    const metrics={duration:measurement(stats.duration),descent_duration:measurement((rep.bottom-rep.start)/fps),ascent_duration:measurement((rep.end-rep.bottom)/fps)};
    for(const key of ['knee','hip','ankle']) {
      const values=segment.map(s=>s[key]).filter(Number.isFinite),complete=values.length===segment.length;
      metrics['min_'+key+'_angle']=measurement(complete?Math.min(...values):null,values.length/segment.length,complete?null:'missing_samples');
    }
    const speeds=ascent.map(s=>s.velocity).filter(Number.isFinite), complete=speeds.length===ascent.length;
    metrics.peak_ascent_velocity=measurement(complete?stats.peak:null,speeds.length/ascent.length,complete?null:'missing_samples');
    const intervals=[];
    for(let j=1;j<ascent.length;j++) if(Number.isFinite(ascent[j-1].velocity)&&Number.isFinite(ascent[j].velocity)) intervals.push((ascent[j-1].velocity+ascent[j].velocity)/2);
    const coverage=intervals.length/(rep.end-rep.bottom);
    metrics.mean_ascent_velocity=measurement(coverage>=.8?intervals.reduce((a,b)=>a+b,0)/intervals.length:null,coverage,coverage>=.8?null:'insufficient_coverage');
    const valid=segment.filter(s=>Number.isFinite(s.hip_y_smoothed_px)&&Number.isFinite(s.hip_velocity)).length;
    metrics.bottom_pause=measurement(stats.pause,valid/segment.length,stats.pause!==null?null:valid<segment.length?'missing_samples':'no_motion');
    return {id:rep.id,ordinal:i+1,boundaries:{start:rep.start,bottom:rep.bottom,end:rep.end},source:rep.source||'auto',needs_review:!!rep.needs_review,
      interpolated_ascent_fraction:ascent.filter(s=>s.interpolated).length/ascent.length,metrics};
  });
  const references={},trends={};
  for(const [name,unit] of Object.entries(units)) {
    const points=rows.filter(r=>r.metrics[name].value!==null),values=points.map(r=>r.metrics[name].value), sorted=[...values].sort((a,b)=>a-b),n=values.length;
    references[name]={value:n?(sorted[Math.floor((n-1)/2)]+sorted[Math.floor(n/2)])/2:null,valid_repetitions:n};
    const trend={valid_repetitions:n,slope_per_rep:null,first_rep_id:n?points[0].id:null,last_rep_id:n?points[n-1].id:null,
      first_to_last:delta(n?values[n-1]:null,n?values[0]:null,unit,n<2?'insufficient_repetitions':null),reason:n<3?'insufficient_repetitions':null};
    if(n>=3) {
      const mx=points.reduce((sum,p)=>sum+p.ordinal,0)/n,my=values.reduce((a,b)=>a+b,0)/n;
      trend.slope_per_rep=points.reduce((sum,p)=>sum+(p.ordinal-mx)*(p.metrics[name].value-my),0)/points.reduce((sum,p)=>sum+(p.ordinal-mx)**2,0);
    }
    trends[name]=trend;
  }
  rows.forEach((row,i)=>{
    row.previous_rep_id=i?rows[i-1].id:null; row.versus_previous={};row.versus_session_median={};
    for(const [name,unit] of Object.entries(units)) {
      row.versus_previous[name]=delta(row.metrics[name].value,i?rows[i-1].metrics[name].value:null,unit,i?null:'no_previous_rep');
      row.versus_session_median[name]=delta(row.metrics[name].value,references[name].value,unit,references[name].valid_repetitions<2?'insufficient_repetitions':null);
    }
  });
  return {schema_version:1,units,method:{
    delta:'current minus reference; percent uses absolute reference',
    reference:'median of available values, including current rep; not a technique target',
    extrema:'complete finite sample coverage required',
    mean_velocity:'signed trapezoidal mean over valid adjacent ascent intervals; minimum 80% interval coverage',
    velocity:'smoothed shoulder midpoint, positive upward, uncalibrated px/s; interpolated samples included',
    pause:'contiguous bottom region: deepest 5% of hip excursion and <=10% peak absolute hip speed; minimum 0.2s',
    trend:'OLS over original rep ordinals; minimum 3 available reps; descriptive, no fatigue or significance inference',
    percent_reference_minimum:{s:.01,'px/s':.1},
  },session_median:references,repetitions:rows,trends};
}
