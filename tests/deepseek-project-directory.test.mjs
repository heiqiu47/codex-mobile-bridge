import assert from 'node:assert/strict';
import {mkdir,mkdtemp,readFile,realpath,rm,stat,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {apply} from '../bridge/clients/deepseek/host.mjs';

await mkdir('.tmp',{recursive:true});
const folder=await mkdtemp(join('.tmp','dsh-project-directory-'));
const endpoint=join(folder,'endpoint.json'),configPath=join(folder,'config.json');
await writeFile(configPath,JSON.stringify({token:'project-fixture',endpoint}));
const calls=[],disposers=[];
const ctx={
  sessionController:{list:async()=>({items:[]}),
    create:async value=>{calls.push(value);return value;},
    rename:async value=>calls.push(value),
    prompt:async()=>{throw Error('Project creation must not call a model');}},
  workspaceRegistry:{list:()=>[]},
  on:()=>{},effect:setup=>disposers.push(setup()),
};
await apply(ctx,{configPath});
const {port}=JSON.parse(await readFile(endpoint,'utf8'));
const request=async(action,body={})=>fetch(`http://127.0.0.1:${port}/mobile`,{
  method:'POST',headers:{Authorization:'Bearer project-fixture','Content-Type':'application/json'},
  body:JSON.stringify({action,body}),
});
try{
  assert.deepEqual((await(await request('projects')).json()).projects,[]);
  assert.equal(calls.length,0);
  const projectPath=join(folder,'new-project');await mkdir(projectPath);
  const cwd=await realpath(projectPath),identity=await stat(cwd);
  const projectDirectory={cwd,device:identity.dev,inode:identity.ino};
  const created=await request('create',{id:'explicit-project',title:'New project',projectDirectory});
  assert.equal(created.status,200);
  assert.deepEqual(calls,[{sessionId:'session-explicit-project',cwd},{sessionId:'session-explicit-project',title:'New project'}]);
  const before=calls.length;
  assert.equal((await request('create',{id:'changed-directory',projectDirectory:{...projectDirectory,inode:identity.ino+1}})).status,400);
  assert.equal((await request('create',{id:'missing-directory',projectDirectory:{...projectDirectory,cwd:join(cwd,'missing')}})).status,400);
  assert.equal(calls.length,before);
}finally{
  for(const dispose of disposers.reverse())await dispose();
  await rm(folder,{recursive:true,force:true});
}
