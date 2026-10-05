const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
vm.runInThisContext(fs.readFileSync('gymbromatics/technique.js','utf8'));
const rep={start:0,bottom:30,end:60},fps=30;
function clean(){return Array.from({length:61},(_,i)=>{const down=1-Math.abs(i-30)/30;return {
  hip:[100,200+100*down],shoulder:[80,100+100*down],knee:[150,290],heel:[150,400],toe:[200,400],knee_angle_deg:180-90*down};});}
function assess(frames,settings){return SquatTechnique.assess(frames,rep,fps,settings);}
let frames=clean(),result=assess(frames);
assert.equal(result.depth.status,'clear');assert.equal(result.coordination.status,'clear');assert.equal(result.heel.status,'clear');
// Exact angle boundary, independent of hip-centre height.
for(const [angle,status] of [[90,'clear'],[90.01,'review'],[89.99,'clear']]){
 frames=clean();frames[30].knee_angle_deg=angle;assert.equal(assess(frames).depth.status,status);
}
frames=clean();frames.forEach(g=>{g.hip[1]-=45;g.shoulder[1]-=45;});assert.equal(assess(frames).depth.status,'clear');
assert.equal(SquatTechnique.assess(clean(),{start:0,bottom:10,end:20},fps).depth.status,'review');
assert.equal(SquatTechnique.assess(clean(),{...rep,bottom:22},fps).depth.angle,90);
// Clear sustained hip-first ascent plus increased trunk lean.
frames=clean();for(let i=32;i<=45;i++){frames[i].hip[1]-=25;frames[i].shoulder[0]-=40;}
assert.equal(assess(frames).coordination.status,'review');
// A one-frame glitch must not produce a coordination alert.
frames=clean();frames[35].hip[1]-=25;frames[35].shoulder[0]-=40;assert.equal(assess(frames).coordination.status,'clear');
// A constant forward torso is not an error by itself.
frames=clean();frames.forEach(g=>g.shoulder[0]-=90);assert.equal(assess(frames).coordination.status,'clear');
// True relative heel lift, but not common vertical camera/foot translation.
frames=clean();for(let i=20;i<=40;i++)frames[i].heel[1]-=10;assert.equal(assess(frames).heel.status,'review');
frames=clean();for(let i=20;i<=40;i++){frames[i].heel[1]-=10;frames[i].toe[1]-=10;}
assert.equal(assess(frames).heel.status,'unavailable');
frames=clean();for(let i=0;i<61;i++)frames[i].heel=null;assert.equal(assess(frames).heel.status,'unavailable');
frames=clean();for(let i=26;i<=34;i++)frames[i].knee_angle_deg=null;assert.equal(assess(frames).depth.status,'unavailable');
// The far foot is neither averaged nor used as a fallback.
frames=clean();frames.forEach(g=>g.feet={left:{heel:g.heel,toe:g.toe},right:{heel:null,toe:null}});
assert.equal(assess(frames,{footSide:'left'}).heel.status,'clear');
assert.equal(assess(frames,{footSide:'right'}).heel.status,'unavailable');
// Invariance to image scale and left/right facing direction.
frames=clean();for(let i=20;i<=40;i++)frames[i].heel[1]-=10;
const expected=assess(frames);
for(const scale of [.5,2]){const transformed=frames.map(g=>Object.fromEntries(Object.entries(g).map(([k,p])=>[k,Array.isArray(p)?[-p[0]*scale+500,p[1]*scale+20]:p])));
 const actual=assess(transformed);for(const k of ['depth','heel','coordination'])assert.equal(actual[k].status,expected[k].status);}
console.log('Technique math: depth, sustained events, occlusion and scale/mirror passed');
