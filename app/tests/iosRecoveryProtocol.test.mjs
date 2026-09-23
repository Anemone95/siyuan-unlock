import {test} from "node:test";
import assert from "node:assert/strict";
import {IOSRecoveryProtocol} from "../src/util/iosRecoveryProtocol.ts";

function fixture() {
 const messages=[], statuses=[], sockets=[];
 const protocol=new IOSRecoveryProtocol("page",m=>messages.push(m),(s,d)=>statuses.push([s,d]));
 const owner={}; let calls=0;
 const register=(o=owner,main=true)=>protocol.register(o,main,()=>{calls++;const s={readyState:0,close(){this.readyState=3;}};sockets.push(s);protocol.attach(o,s);});
 const ready=(generation=1,requestID=generation)=>protocol.receive({pageID:"page",requestID,generation,state:"TransportAccepting"});
 return {protocol,messages,statuses,sockets,owner,register,ready,calls:()=>calls};
}

test("Ready replay and duplicate CONNECTING are idempotent; open is required for completion",()=>{
 const f=fixture();f.register();assert.equal(f.calls(),0);f.protocol.handshake();f.ready();f.ready();assert.equal(f.calls(),1);
 assert.equal(f.messages.filter(m=>m.kind==="recoveryCompleted").length,0);
 f.protocol.open(f.owner,f.sockets[0]);f.ready();assert.equal(f.messages.filter(m=>m.kind==="recoveryCompleted").length,1);
});
test("old socket and old page events cannot affect current generation",()=>{
 const f=fixture();f.register();f.ready();const old=f.sockets[0];f.ready(2);const current=f.sockets[1];
 f.protocol.disconnect(f.owner,old);assert.equal(f.protocol.open(f.owner,old),false);
 f.protocol.receive({pageID:"old",requestID:99,generation:99,state:"Failed"});
 f.protocol.open(f.owner,current);assert.equal(f.protocol.canWrite(),true);
});
test("main and sub sockets are required; destroyed models stay removed",()=>{
 const f=fixture(),child={};f.register();f.register(child,false);f.ready();f.protocol.open(f.owner,f.sockets[0]);
 assert.equal(f.messages.some(m=>m.kind==="recoveryCompleted"),false);assert.equal(f.protocol.canWrite(),false);f.protocol.remove(child);assert.equal(f.protocol.canWrite(),true);
 assert.equal(f.messages.some(m=>m.kind==="recoveryCompleted"),true);f.ready(2);assert.equal(f.calls(),3);
});
test("failures do not retry, authentication and user close are terminal",()=>{
 for(const reason of ["network","unauthenticated","close websocket"]) {
  const f=fixture();f.register();f.ready();f.protocol.disconnect(f.owner,f.sockets[0],reason);f.ready();assert.equal(f.calls(),1);
  f.ready(2);assert.equal(f.calls(),reason==="network"?2:1);
 }
});
test("lost non-idempotent write ACK keeps exact body without resend or completion",()=>{
 const f=fixture();f.register();f.ready();f.protocol.open(f.owner,f.sockets[0]);const body='{"insert":"user text"}';
 const id=f.protocol.beginWrite(body);f.protocol.finishWrite(id,false);f.ready(2);f.protocol.open(f.owner,f.sockets[1]);
 assert.equal(f.protocol.writes.get(id).body,body);assert.equal(f.protocol.canWrite(),false);
 assert.equal(f.messages.filter(m=>m.kind==="recoveryCompleted").length,1);
 assert.equal(f.statuses.at(-1)[0],"UncertainWrites");
});
test("pending writes resolve by response events; background cancels current sockets",()=>{
 const f=fixture();f.register();f.ready();const id=f.protocol.beginWrite("pending");f.protocol.open(f.owner,f.sockets[0]);
 assert.equal(f.messages.some(m=>m.kind==="recoveryCompleted"),false);f.protocol.finishWrite(id,true);
 assert.equal(f.messages.some(m=>m.kind==="recoveryCompleted"),true);
 f.protocol.receive({pageID:"page",requestID:2,generation:1,state:"Paused"});assert.equal(f.protocol.canWrite(),false);
 f.protocol.retry();f.protocol.cancel();assert.deepEqual(f.messages.slice(-2).map(m=>m.kind),["retry","cancel"]);
});
test("late Ready cannot revive a terminal failure in the same request",()=>{
 const f=fixture();f.register();f.protocol.receive({pageID:"page",requestID:1,generation:1,state:"Failed"});
 f.ready();assert.equal(f.calls(),0);f.ready(2);assert.equal(f.calls(),1);
});
