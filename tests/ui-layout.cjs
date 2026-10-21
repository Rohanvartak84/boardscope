// Visual QA uses synthetic API fixtures only; every request is intercepted.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.BOARDSCOPE_BROWSER_EXECUTABLE?{executablePath:process.env.BOARDSCOPE_BROWSER_EXECUTABLE}:{}),args:['--no-sandbox','--no-zygote','--disable-dev-shm-usage','--disable-gpu']});
 const page=await browser.newPage({viewport:{width:1774,height:887},deviceScaleFactor:1});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const now=Date.now(),at=s=>new Date(now-s*1000).toISOString();
 const board=(id,name,os,host,connection)=>({id,name,environment:os,host,mode:'ssh',port:22,username:'engineer',auth_method:'password',serial_port:connection==='none'?'':'/dev/fixture-'+id,baud:115200,capabilities:{machine:'RISC-V'},credential_status:{ssh_password:true,uart_password:true},connection_checks:connection==='none'?{ssh:{status:'failed',checked_at:at(10),error:'Connection refused'}}:connection==='uart'?{ssh:{status:'failed',checked_at:at(32),error:'SSH timed out'},uart:{status:'verified',checked_at:at(30)}}:{ssh:{status:'verified',checked_at:at(30)}}});
 const boards=[board('b1','Board-07','Ubuntu','192.0.2.50','ssh'),board('b2','Yocto-dev','Yocto','192.0.2.51','uart'),board('b3','Lab-board','Ubuntu','192.0.2.52','none')];
 const script={id:'s1',name:'Network stability',version:3,sha256:'a'.repeat(64),timeout_s:120};
 const run=(id,b,test,outcome,seconds,secondsAgo)=>({id,board_id:b.id,board_snapshot:b,plan:{test,transport:b.id==='b2'?'auto':'ssh',cycles:10,timeout_s:90,interval_s:1,failure_policy:'pause',args:[]},script_snapshot:test==='custom'?script:null,state:outcome?'completed':'running',outcome,created_at:at(secondsAgo+seconds),started_at:at(secondsAgo+seconds),ended_at:outcome?at(secondsAgo):null,completed_cycles:outcome?10:3,simulated:false,fallback_used:b.id==='b2'});
 const runs=[run('r1',boards[0],'custom',null,134,0),run('r2',boards[1],'custom','fail',3,210),run('r3',boards[0],'inventory','pass',12,300),run('r4',boards[0],'reboot','pass',45,420)];
 const detail=r=>({...r,events:[{time:at(1),level:r.outcome==='fail'?'error':'info',message:r.outcome==='fail'?'sudo: a password is required':'Checking packet loss…'}],cycles:r.outcome==='fail'?[{id:'c2',number:1,outcome:'fail',transport:'uart',duration_ms:3000,checks:[],kernel_log:'UI FIXTURE: sudo: a password is required',failure:{stage:'Script execution',error_type:'Nonzero exit',message:'sudo: a password is required',next_checks:['Check saved sudo settings.'],limitation:'Synthetic visual fixture, not hardware evidence.'}}]:[{id:'c1',number:3,outcome:'pass',transport:'ssh',duration_ms:12000,checks:[],kernel_log:'UI FIXTURE: packet-loss check output'}]});
 const fixture={boards,runs,scripts:[script],ai_enabled:false,database_path:'/fixture/boardscope.sqlite3'};
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());
  if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync('boardscope/static/index.html','utf8').replace('__TOKEN__','fixture-token')});
  if(url.pathname.startsWith('/static/'))return route.fulfill({contentType:url.pathname.endsWith('.css')?'text/css':'text/javascript',body:fs.readFileSync('boardscope'+url.pathname,'utf8')});
  if(url.pathname==='/api/state')return route.fulfill({json:fixture});
  if(url.pathname.startsWith('/api/runs/'))return route.fulfill({json:detail(runs.find(r=>r.id===url.pathname.split('/').at(-1)))});
  return route.abort();
 });
 const out=process.env.BOARDSCOPE_SCREENSHOT_DIR||'/tmp/boardscope-ui-layout';fs.mkdirSync(out,{recursive:true});
 await page.goto('http://boardscope.fixture/');await page.waitForSelector('.board-name');
 // The label is test-only, so screenshots cannot be mistaken for live lab metrics.
 await page.locator('.workspace-tag').evaluate(el=>el.textContent='UI fixture · synthetic data');
 assert(await page.locator('#assistant-panel').isHidden());
 await page.screenshot({path:path.join(out,'overview-desktop.png')});
 await page.locator('[data-assist="error"]').click();await page.waitForSelector('#assistant-panel:not([hidden])');
 assert(await page.locator('.assistant-action').evaluateAll(xs=>xs.every(x=>x.disabled)));
 await page.screenshot({path:path.join(out,'overview-assistant-desktop.png')});
 const overflow=()=>page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 assert(!await overflow(),'Desktop page overflow');
 await page.locator('#assistant-close').click();await page.setViewportSize({width:1280,height:900});assert(!await overflow(),'Laptop page overflow');
 await page.setViewportSize({width:820,height:1180});assert(!await overflow(),'Tablet page overflow');await page.screenshot({path:path.join(out,'overview-tablet.png')});
 await page.setViewportSize({width:390,height:844});assert(!await overflow(),'Mobile page overflow');await page.screenshot({path:path.join(out,'overview-mobile.png'),fullPage:true});
 await page.locator('#menu-toggle').click();await page.locator('#sidebar [data-nav="assistant"]').click();await page.locator('[data-assist="general"]').click();
 assert(await page.locator('#assistant-panel').getAttribute('aria-modal')==='true');
 const box=await page.locator('#assistant-panel').boundingBox();assert.equal(Math.round(box.width),390);
 await page.screenshot({path:path.join(out,'assistant-mobile.png')});await page.keyboard.press('Escape');assert(await page.locator('#assistant-panel').isHidden());
 assert.deepEqual(errors,[]);console.log('Chromium layout checks passed at 1774, 1280, 820 and 390px, including the mobile Assistant drawer. Screenshots: '+out);await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
