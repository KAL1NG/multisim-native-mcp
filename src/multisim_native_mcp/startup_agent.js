'use strict';
// Observe after normal GUI startup reaches input idle. DAO's environment is
// repaired before launch; its COM factory does not need interception.
rpc.exports={
  ready(){return Process.enumerateModules().some(m=>m.name.toLowerCase()==='sch_cap.dll');},
  report(){return {passive:true,modules:Process.enumerateModules().length,
    dao_loaded:Process.enumerateModules().some(m=>m.name.toLowerCase()==='dao360.dll')};}
};
