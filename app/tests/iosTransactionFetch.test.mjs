import {test} from "node:test";
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import ts from "typescript";
import {IOSRecoveryProtocol} from "../src/util/iosRecoveryProtocol.ts";

function fixture() {
 const listeners={},requests=[];
 globalThis.window={webkit:{messageHandlers:{kernelRecovery:{postMessage(){}}}},siyuan:{dialogs:[]}};
 globalThis.document={body:{append(){}},addEventListener(k,f){listeners[k]=f;},createElement(){return {setAttribute(){},style:{},append(){},replaceChildren(){},remove(){}};}};
 globalThis.sessionStorage={getItem(){return null;}};
 let source=readFileSync(new URL("../src/util/iosKernelRecovery.ts",import.meta.url),"utf8").replace(/^import .*;$/gm,"");
 source=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2020}}).outputText.replace(/export /g,"");
 const api=new Function("IOSRecoveryProtocol",source+";return {iosRecovery,iosTransactionFetch};")(IOSRecoveryProtocol);
 const recovery=api.iosRecovery();const owner={},sockets=[];
 recovery.register(owner,true,()=>{const socket={readyState:0,close(){this.readyState=3;}};sockets.push(socket);recovery.attach(owner,socket);});
 const ready=g=>{recovery.receive({pageID:recovery.pageID,requestID:g,generation:g,state:"TransportAccepting"});recovery.open(owner,sockets.at(-1));};
 return {api,recovery,requests,listeners,ready};
}

test("actual fetch adapter retains lost response, sends queued body once and protects input",async()=>{
 const f=fixture();let prevented=0;
 f.listeners.beforeinput({target:{closest(){return true;}},preventDefault(){prevented++;}});assert.equal(prevented,1);
 globalThis.fetch=async(url,init)=>{f.requests.push(init.body);throw Error("response lost");};
 const init={method:"POST",body:'{"insert":"preserved edit"}'};
 const pending=f.api.iosTransactionFetch("/api/transactions",init);const rejected=assert.rejects(pending,/response lost/);
 init.body="changed caller data";assert.equal(f.requests.length,0);f.ready(1);await rejected;
 assert.deepEqual(f.requests,['{"insert":"preserved edit"}']);assert.equal(f.recovery.writes.size,1);
 f.ready(2);assert.equal(f.requests.length,1);assert.equal(f.recovery.canWrite(),false);
 f.listeners.beforeinput({target:{closest(){return true;}},preventDefault(){prevented++;}});assert.equal(prevented,2);
});
test("actual fetch acknowledgement releases retained data without a reload",async()=>{
 const f=fixture();f.ready(1);globalThis.fetch=async()=>new Response('{"code":0}',{headers:{"content-type":"application/json"}});
 await f.api.iosTransactionFetch("/api/transactions",{method:"POST",body:'{"update":"edit"}'});
 assert.equal(f.recovery.writes.size,0);assert.equal(f.recovery.canWrite(),true);
 assert.equal(f.api.iosTransactionFetch("/api/other",{}),undefined);
});
test("error dialog presence changes only UI cleanup, not connection or write recovery",async()=>{
 for(const present of [false,true]){
  const f=fixture();let destroyed=0;
  window.siyuan.dialogs=present?[{element:{id:"errorLog"},destroy(){destroyed++;}}]:[];
  f.ready(1);assert.equal(f.recovery.canWrite(),true);assert.equal(destroyed,present?1:0);
  globalThis.fetch=async()=>{throw Error("lost");};
  await assert.rejects(f.api.iosTransactionFetch("/api/transactions",{method:"POST",body:"edit"}));
  f.ready(2);assert.equal(f.recovery.writes.size,1);assert.equal(f.recovery.canWrite(),false);
 }
});
