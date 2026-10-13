// Frontend-only fixtures. No physical hardware or external API is contacted.
const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('node:assert/strict');
(async()=>{
 const html=fs.readFileSync('boardscope/static/index.html','utf8').replace('__TOKEN__','test-token');
 const dom=new JSDOM(html,{url:'http://127.0.0.1',runScripts:'outside-only',pretendToBeVisual:true}),w=dom.window,d=w.document;
 let mobile=false,offline=false,sshError='SSH connection timed out',gate=null;
 w.matchMedia=()=>({matches:mobile});w.scrollTo=()=>{};
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};w.HTMLDialogElement.prototype.close=function(){this.open=false};
 const errors=[],calls=[];w.addEventListener('error',e=>errors.push(e.message));
 const now=new Date().toISOString();
 const board={id:'mock-board',name:'Fixture Linux board',mode:'ssh',host:'192.0.2.1',username:'engineer',port:22,environment:'Yocto',serial_port:'/dev/mock-uart',baud:115200,auth_method:'password',credential_status:{ssh_password:true,uart_password:true},connection_checks:{}};
 const noUart={...board,id:'no-uart',name:'Fixture SSH only',serial_port:'',connection_checks:{}};
 const run={id:'mock-run',board_id:board.id,board_snapshot:{...board},plan:{test:'custom',transport:'auto',cycles:1,args:[],timeout_s:90},script_snapshot:{name:'Fixture check',version:3,sha256:'a'.repeat(64),timeout_s:15},state:'completed',outcome:'fail',created_at:now,started_at:now,ended_at:now,completed_cycles:1,simulated:false,fallback_used:true};
 const failure={stage:'Execute custom script',error_type:'CheckMismatch',message:'fixture device unavailable',next_checks:['Review fixture stdout'],limitation:'Fixture evidence only'};
 const full={...run,cycles:[{id:'mock-cycle',number:1,outcome:'fail',transport:'uart',checks:[],failure,kernel_log:'fixture raw evidence',duration_ms:10}],events:[{time:now,level:'error',message:'fixture device unavailable'}]};
 const state={boards:[board,noUart],runs:[run],scripts:[{id:'mock-script',name:'Fixture check',version:3,sha256:'a'.repeat(64),timeout_s:15}],ai_enabled:false,database_path:'/fixture/boardscope.sqlite3'};
 w.fetch=async(url,opts={})=>{
  calls.push({url:String(url),opts});if(offline)throw Error('fixture disconnected');
  if(String(url)==='/api/state')return {ok:true,json:async()=>JSON.parse(JSON.stringify(state))};
  if(String(url).includes('/verify')){
   const t=JSON.parse(opts.body).transport,b=String(url).includes('no-uart')?noUart:board;
   if(t==='ssh'){if(gate)await gate;b.connection_checks.ssh={status:'failed',checked_at:new Date().toISOString(),error:sshError};return {ok:false,json:async()=>({detail:sshError})};}
   b.connection_checks.uart={status:'verified',checked_at:new Date(Date.now()+1).toISOString()};return {ok:true,json:async()=>({machine:'riscv64',os:'Fixture Linux'})};
  }
  if(String(url)==='/api/runs/mock-run')return {ok:true,json:async()=>full};
  throw Error('Unexpected fixture request '+url);
 };
 w.eval(fs.readFileSync('boardscope/static/app.js','utf8')+'\nwindow.uiHooks={refresh,pending:()=>connectionPending.size};');
 const q=s=>d.querySelector(s),wait=async f=>{for(let i=0;i<100;i++){if(f())return;await new Promise(r=>setTimeout(r,15));}throw Error('Fixture wait timed out');};
 await wait(()=>d.querySelectorAll('.stats .stat').length===4);
 assert.equal(d.querySelectorAll('nav [data-nav]').length,6);assert(q('#assistant-panel').hidden);
 assert(q('.attention').textContent.includes('fixture device unavailable'));assert(q('.attention').textContent.includes('Execute custom script'));
 q('[data-select-board="mock-board"]').click();const row=q('[data-key="board-mock-board"]');
 q('#board-search').value='Fixture Linux';q('#board-search').dispatchEvent(new w.Event('input',{bubbles:true}));
 const search=q('#board-search');search.focus();await w.uiHooks.refresh();assert.equal(q('#board-search'),search);assert.equal(d.activeElement,search);assert.equal(q('#board-search').value,'Fixture Linux');assert.equal(q('[data-key="board-mock-board"]'),row);assert(q('[data-select-board="mock-board"]').getAttribute('aria-pressed')==='true');
 q('#board-search').value='';q('#board-search').dispatchEvent(new w.Event('input',{bubbles:true}));
 let release;gate=new Promise(r=>release=r);q('[data-check-policy="mock-board"]').click();await wait(()=>q('[data-key="board-mock-board"]').textContent.includes('Checking SSH'));release();gate=null;
 await wait(()=>q('[data-key="board-mock-board"]').textContent.includes('Ready via UART'));
 assert(q('[data-key="board-mock-board"] .pill.pass'));assert(board.connection_checks.ssh.error==='SSH connection timed out');
 const verify=calls.filter(x=>x.url.includes('/mock-board/verify')).map(x=>JSON.parse(x.opts.body).transport);assert.deepEqual(verify,['ssh','uart']);
 q('[data-check-policy="no-uart"]').click();await wait(()=>q('[data-key="board-no-uart"]').textContent.includes('Unreachable'));assert(q('[data-key="board-no-uart"]').textContent.includes('UART not configured'));assert(!calls.some(x=>x.url.includes('/no-uart/verify')&&JSON.parse(x.opts.body).transport==='uart'));
 const before=calls.length;sshError='SSH host key changed; verify fingerprint';q('[data-check-policy="mock-board"]').click();await wait(()=>!w.uiHooks.pending());assert(!calls.slice(before).some(x=>x.url.includes('/verify')&&JSON.parse(x.opts.body).transport==='uart'));
 q('[data-assist="error"]').click();await wait(()=>!q('#assistant-panel').hidden);assert(q('#assistant-panel').textContent.includes('Assistant not configured'));assert(q('#assistant-panel').textContent.includes('Fixture Linux board'));assert(q('#assistant-panel').textContent.includes('v3'));assert([...d.querySelectorAll('.assistant-action')].every(x=>x.disabled));assert(q('#assistant-panel').textContent.includes('fixture raw evidence'));
 q('#assistant-close').click();assert(q('#assistant-panel').hidden);
 q('[data-start="mock-board"]').click();assert.equal(q('#form').elements.transport.value,'auto');assert(q('#form').elements.allow_fallback.required);q('#cancel').click();
 mobile=true;q('#menu-toggle').click();assert(d.body.classList.contains('nav-open'));q('[data-nav="assistant"]').click();assert(!d.body.classList.contains('nav-open'));q('[data-assist="general"]').click();assert(!q('#assistant-backdrop').hidden);d.dispatchEvent(new w.KeyboardEvent('keydown',{key:'Escape',bubbles:true}));assert(q('#assistant-panel').hidden);
 q('[data-nav="settings"]').click();assert(q('#content').textContent.includes('/fixture/boardscope.sqlite3'));
 offline=true;await w.uiHooks.refresh();assert(q('#agent-status').textContent.includes('disconnected'));assert(!q('#connection-banner').hidden);offline=false;await w.uiHooks.refresh();assert(q('#connection-banner').hidden);
 assert(!calls.some(x=>x.url.includes('/investigate')));assert.equal(errors.length,0,errors.join('\n'));
 dom.window.close();console.log('Frontend fixtures passed: overview, stable refresh/focus, fallback states, no-UART, host trust, assistant, navigation and disconnected recovery.');
})().catch(e=>{console.error(e);process.exit(1)});
