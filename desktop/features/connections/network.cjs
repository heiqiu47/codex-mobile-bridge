'use strict';
const os=require('node:os');
function interfaces(value=os.networkInterfaces()){
  const rows=new Map();
  for(const [name,addresses] of Object.entries(value))for(const item of addresses||[]){
    if(item.family!=='IPv4'||item.internal||item.address.startsWith('127.'))continue;
    const row=rows.get(name)||{id:name,name,addresses:new Set()};
    row.addresses.add(item.address);
    rows.set(name,row);
  }
  return [...rows.values()].map(row=>({...row,addresses:[...row.addresses].sort()}))
    .sort((a,b)=>a.name.localeCompare(b.name));
}
module.exports={interfaces};
