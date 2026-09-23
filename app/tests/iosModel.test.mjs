import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
import {IOSRecoveryProtocol} from "../src/util/iosRecoveryProtocol.ts";
import {iosRegisterModel, iosOpenModel} from "../src/util/iosModelRecovery.ts";

const source=readFileSync(new URL("../src/layout/Model.ts",import.meta.url),"utf8").replace(/^import .*;$/gm,"");
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText.replace("export class Model","class Model");
const buildModel=new Function("iosRegisterModel","iosOpenModel","iosRecovery","Constants","processMessage","kernelError","reloadSync","const require = () => ({processMessage});"+compiled+"; return Model;");
const makeModel=(...args)=>buildModel(iosRegisterModel,iosOpenModel,...args);

test("actual Model hooks preserve first callback, message callback and fence late events",()=>{
 const sockets=[],events=[];let initialized=0,messages=0,reloads=0;
 globalThis.window={location:{protocol:"http:",host:"local"},siyuan:{config:{},isReady:true}};
 globalThis.document={getElementById(){throw Error("recovery must not inspect errorLog");}};
 globalThis.WebSocket=class {readyState=0;constructor(){sockets.push(this);}close(){this.readyState=3;}send(){}};
 const recovery=new IOSRecoveryProtocol("p",e=>events.push(e),()=>{});
 const Model=makeModel(()=>recovery,{SIYUAN_APPID:"app"},x=>x,()=>{throw Error("legacy error");},()=>reloads++);
 const model=new Model({app:{}});model.connect({id:"id",type:"main",callback(){initialized++;},msgCallback(){messages++;}});
 const ready=generation=>recovery.receive({pageID:"p",requestID:generation,generation,state:"TransportAccepting"});
 ready(1);sockets[0].onopen();sockets[0].onmessage({data:"{}"});
 const queued={open:sockets[0].onopen,close:sockets[0].onclose,error:sockets[0].onerror,message:sockets[0].onmessage};ready(2);
 queued.open();queued.close({reason:""});queued.error({});queued.message({data:"{}"});
 sockets[1].onopen();sockets[1].onmessage({data:"{}"});
 assert.equal(initialized,1);assert.equal(messages,2);assert.equal(reloads,0);
 model.send("closews",{});ready(3);assert.equal(sockets.length,2);assert.equal(recovery.entries.size,0);
 model.connect({id:"new-document",type:"main",callback(){initialized++;},msgCallback(){messages++;}});
 assert.equal(sockets.length,3);assert.equal(recovery.entries.size,1);
 sockets[2].onopen();assert.equal(initialized,2);
 queued.open();queued.message({data:"{}"});assert.equal(messages,2);
});
test("feature disabled retains the original 3000 ms retry with one-shot callback",()=>{
 const sockets=[],timers=[];let initialized=0;
 globalThis.window={location:{protocol:"http:",host:"local"},siyuan:{config:{},isReady:true}};globalThis.document={getElementById:()=>null};
 globalThis.WebSocket=class {constructor(){sockets.push(this);}close(){}};
 const original=globalThis.setTimeout;globalThis.setTimeout=(fn,delay)=>{timers.push({fn,delay});};
 try{
  const Model=makeModel(()=>undefined,{SIYUAN_APPID:"app"},x=>x,()=>{},()=>{});
  const model=new Model({app:{}});model.connect({id:"id",callback(){initialized++;},msgCallback(){}});sockets[0].onopen();sockets[0].onclose({reason:""});
  assert.equal(timers[0].delay,3000);timers[0].fn();sockets[1].onopen();assert.equal(initialized,1);
 }finally{globalThis.setTimeout=original;}
});
