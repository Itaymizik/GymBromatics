/* Pure geometry: no pose-provider, DOM, classifier, or centimetre thresholds. */
const SquatTechnique = (() => {
  const defaults = Object.freeze({depthAngleDegrees:90, footSide:'left', leanDegrees:12,
    riseRatio:.08, heelRatio:.06, heelDegrees:8, holdSeconds:.15, minCoverage:.8});
  const finite = Number.isFinite;
  const point = p => Array.isArray(p) && p.length===2 && p.every(finite);
  const length = (a,b) => Math.hypot(a[0]-b[0], a[1]-b[1]);
  const median = xs => {const a=xs.filter(finite).sort((a,b)=>a-b),n=a.length;return n ? (a[Math.floor((n-1)/2)]+a[Math.floor(n/2)])/2 : null;};
  const lean = g => point(g?.hip) && point(g?.shoulder) && g.hip[1]>g.shoulder[1] ?
    Math.atan2(Math.abs(g.shoulder[0]-g.hip[0]),g.hip[1]-g.shoulder[1])*180/Math.PI : null;
  const unknown = (key,reason) => ({key,status:'unavailable',reason,frame:null});
  function sustained(items, predicate, fps, seconds) {
    let first=null,last=null,best=null;
    for(const item of items) {
      if(item && predicate(item)) {
        if(first===null || item.frame!==last+1)first=item.frame;
        last=item.frame;
        if((last-first)/fps>=seconds && !best)best={...item,start:first,end:last};
      } else {first=null;last=null;}
    }
    return best;
  }
  function assess(frames, rep, fps, settings={}) {
    const cfg={...defaults,...settings};
    if(!finite(fps)||fps<=0 || ![rep.start,rep.bottom,rep.end].every(Number.isInteger) ||
       !(0<=rep.start && rep.start<rep.bottom && rep.bottom<rep.end && rep.end<frames.length))
      return {depth:unknown('depth','invalid_rep'),coordination:unknown('coordination','invalid_rep'),heel:unknown('heel','invalid_rep')};
    const around=Math.max(1,Math.round(.12*fps));
    const near=[];
    for(let i=Math.max(rep.start,rep.bottom-around);i<=Math.min(rep.end,rep.bottom+around);i++)near.push(i);
    const validAngle=i=>finite(frames[i]?.knee_angle_deg) && frames[i].knee_angle_deg>=0 && frames[i].knee_angle_deg<=180;
    const depths=[];
    for(let i=rep.start;i<=rep.end;i++)if(validAngle(i))depths.push({frame:i,angle:frames[i].knee_angle_deg});
    let depth=unknown('depth','knee_not_visible');
    const coverage=depths.length/(rep.end-rep.start+1),bottomCoverage=near.filter(validAngle).length/near.length;
    if(coverage>=cfg.minCoverage && bottomCoverage>=cfg.minCoverage) {
      const deepest=depths.reduce((a,b)=>a.angle<=b.angle?a:b);
      depth={key:'depth',status:deepest.angle<=cfg.depthAngleDegrees?'clear':'review',
        angle:deepest.angle,frame:deepest.frame,coverage,bottomCoverage,partial:coverage<1};
    }
    const bottom=frames[rep.bottom],torso=point(bottom?.hip)&&point(bottom?.shoulder)?length(bottom.hip,bottom.shoulder):null;
    let coordination=unknown('coordination','bottom_not_visible');
    if(torso>=8 && finite(lean(bottom))) {
      const last=rep.bottom+Math.floor((rep.end-rep.bottom)*.5),items=[];
      for(let i=rep.bottom;i<=last;i++) {
        const g=frames[i],angle=lean(g);
        if(!finite(angle)||length(g.hip,g.shoulder)/torso<.7||length(g.hip,g.shoulder)/torso>1.3){items.push(null);continue;}
        const hipRise=bottom.hip[1]-g.hip[1],shoulderRise=bottom.shoulder[1]-g.shoulder[1];
        items.push({frame:i,leanChange:angle-lean(bottom),riseRatio:(hipRise-shoulderRise)/torso,
          hipRise:hipRise/torso,deltaPx:hipRise-shoulderRise});
      }
      const coverage=items.filter(Boolean).length/items.length;
      if(coverage>=cfg.minCoverage && (last-rep.bottom)/fps>=cfg.holdSeconds) {
        const event=sustained(items,x=>x.leanChange>=cfg.leanDegrees && x.riseRatio>=cfg.riseRatio && x.hipRise>=.03,fps,cfg.holdSeconds);
        coordination={key:'coordination',status:event?'review':'clear',frame:event?.frame??rep.bottom,
          leanChange:Math.max(...items.filter(Boolean).map(x=>x.leanChange)),coverage,
          ...(event?{event,deltaPx:event.deltaPx}: {})};
      } else coordination=unknown('coordination','ascent_not_visible');
    }
    let heel=unknown('heel','foot_not_visible');
    const foot=i=>frames[i]?.feet ? (frames[i].feet[cfg.footSide]||{}) : frames[i];
    const baseline=[];
    for(let i=rep.start;i<=Math.min(rep.bottom-1,rep.start+around);i++) {
      const g=foot(i);if(point(g?.heel)&&point(g?.toe))baseline.push(g);
    }
    // A visible, sufficiently resolved foot is required even for a "clear" result.
    if(baseline.length>=Math.ceil((Math.min(rep.bottom-1,rep.start+around)-rep.start+1)*cfg.minCoverage)) {
      const heel0=[0,1].map(k=>median(baseline.map(g=>g.heel[k]))),toe0=[0,1].map(k=>median(baseline.map(g=>g.toe[k])));
      const footLength=length(heel0,toe0),horizontal=Math.abs(heel0[0]-toe0[0]);
      const baseAngle=Math.atan2(toe0[1]-heel0[1],horizontal)*180/Math.PI;
      if(footLength>=10 && horizontal>=8) {
        const items=[];
        for(let i=rep.start;i<=rep.end;i++) {
          const g=foot(i);
          if(!point(g?.heel)||!point(g?.toe) || length(g.toe,toe0)>.1*footLength ||
             length(g.heel,g.toe)/footLength<.7 || length(g.heel,g.toe)/footLength>1.3){items.push(null);continue;}
          const deltaPx=(g.toe[1]-g.heel[1])-(toe0[1]-heel0[1]);
          items.push({frame:i,deltaPx,ratio:deltaPx/footLength,
            angle:Math.atan2(g.toe[1]-g.heel[1],Math.abs(g.toe[0]-g.heel[0]))*180/Math.PI-baseAngle});
        }
        const coverage=items.filter(Boolean).length/items.length;
        if(coverage>=cfg.minCoverage) {
          const event=sustained(items,x=>x.ratio>=cfg.heelRatio && x.angle>=cfg.heelDegrees,fps,cfg.holdSeconds);
          heel={key:'heel',status:event?'review':'clear',coverage,frame:event?.frame??rep.start,
            deltaPx:event?.deltaPx??Math.max(0,...items.filter(Boolean).map(x=>x.deltaPx)),...(event?{event}: {})};
        } else heel=unknown('heel','foot_moving_or_hidden');
      } else heel=unknown('heel','foot_too_small');
    }
    return {depth,coordination,heel};
  }
  return {assess,defaults};
})();
