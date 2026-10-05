/* Segment-based scale estimate. The head allowance is an editable heuristic. */
const BodyCalibration=(()=>{
  const keys=['foot','shank','thigh','torso','neck'];
  const dist=(a,b)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
  const valid=p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite);
  const median=a=>{const x=[...a].sort((a,b)=>a-b);return (x[Math.floor((x.length-1)/2)]+x[Math.floor(x.length/2)])/2;};
  function angle(a,b,c){const u=[a[0]-b[0],a[1]-b[1]],v=[c[0]-b[0],c[1]-b[1]];return Math.acos(Math.max(-1,Math.min(1,(u[0]*v[0]+u[1]*v[1])/(Math.hypot(...u)*Math.hypot(...v)))))*180/Math.PI;}
  function estimate(frames,start,fps,side){
    if(!Number.isInteger(start)||start<0||start>=frames.length||!Number.isFinite(fps)||fps<=0)return {available:false,reason:'no_rep'};
    const radius=Math.max(1,Math.round(fps*.1)),candidates=[];
    for(let i=Math.max(0,start-radius);i<=Math.min(frames.length-1,start+radius);i++){
      const p=frames[i]?.calibration_points?.[side];
      if(!p||!['ear','shoulder','hip','knee','ankle','heel','toe'].every(k=>valid(p[k])))continue;
      if(!(p.ear[1]<p.shoulder[1]&&p.shoulder[1]<p.hip[1]&&p.hip[1]<p.knee[1]&&p.knee[1]<p.ankle[1]))continue;
      if(!(angle(p.hip,p.knee,p.ankle)>=160&&angle(p.shoulder,p.hip,p.knee)>=150))continue;
      const floorY=Math.max(p.heel[1],p.toe[1]);
      const segments={foot:floorY-p.ankle[1],shank:dist(p.ankle,p.knee),thigh:dist(p.knee,p.hip),torso:dist(p.hip,p.shoulder),neck:dist(p.shoulder,p.ear)};
      if(segments.foot<0||segments.foot>.3*segments.shank||['shank','thigh','torso'].some(k=>segments[k]<8)||segments.neck<3)continue;
      candidates.push({frame:i,points:p,floorY,segments,total:keys.reduce((s,k)=>s+segments[k],0)});
    }
    if(candidates.length<3)return {available:false,reason:'insufficient_pose',referenceFrame:start,validFrames:candidates.length};
    const totals=candidates.map(c=>c.total),centre=median(totals);
    if((Math.max(...totals)-Math.min(...totals))/centre>.12)return {available:false,reason:'unstable',referenceFrame:start};
    const segments=Object.fromEntries(keys.map(k=>[k,median(candidates.map(c=>c.segments[k]))]));
    const representative=candidates.reduce((a,b)=>Math.abs(a.total-centre)<=Math.abs(b.total-centre)?a:b);
    return {available:true,referenceFrame:start,previewFrame:representative.frame,side,segments,
      points:representative.points,floorY:representative.floorY,validFrames:candidates.length,
      windowStart:Math.max(0,start-radius),windowEnd:Math.min(frames.length-1,start+radius)};
  }
  function scale(heightCm,segments,headPercent=6){
    if(!Number.isFinite(heightCm)||heightCm<80||heightCm>250||!Number.isFinite(headPercent)||headPercent<0||headPercent>20||
       !segments||!keys.every(k=>Number.isFinite(segments[k])&&segments[k]>=0)||keys.slice(1).some(k=>segments[k]<=0))return null;
    const basePixels=keys.reduce((s,k)=>s+segments[k],0),headPixels=basePixels*headPercent/100,totalPixels=basePixels+headPixels;
    if(basePixels<50)return null;
    return {heightCm,segments:{...segments},headPercent,headPixels,totalPixels,cmPerPixel:heightCm/totalPixels,estimated:true};
  }
  return {estimate,scale,keys};
})();
