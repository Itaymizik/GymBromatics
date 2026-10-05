/* Reuse the dashboard's geometry rules in the Python feedback stage. */
'use strict';
const fs=require('fs'),path=require('path'),vm=require('vm');
vm.runInThisContext(fs.readFileSync(path.join(__dirname,'technique.js'),'utf8'));
const data=JSON.parse(fs.readFileSync(0,'utf8'));
const settings={...SquatTechnique.defaults,footSide:data.foot_side};
process.stdout.write(JSON.stringify({settings,repetitions:data.repetitions.map(rep=>({
  id:rep.id,assessment:SquatTechnique.assess(data.frames,rep,data.fps,settings)
}))}));
