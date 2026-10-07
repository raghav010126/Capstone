// REFERENCE ONLY: needs the Artifact Tool runtime (@oai/artifact-tool), which is not part of this repository.
// docs/MediShield_capstone.pptx is the maintained, finished deck; edit it in PowerPoint.
// Edit the existing branded deck with the supplied Artifact Tool runtime.
// RUNTIME_NODE_MODULES=/absolute/runtime/node_modules node scripts/make_deck.mjs INPUT OUTPUT_DIR
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL, fileURLToPath} from 'node:url';
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const req = createRequire(path.join(process.env.RUNTIME_NODE_MODULES, '__runtime__.cjs'));
const {FileBlob, PresentationFile} = await import(pathToFileURL(req.resolve('@oai/artifact-tool')));
const input = path.resolve(process.argv[2] || path.join(repo, 'docs/MediShield_capstone.pptx'));
const out = path.resolve(process.argv[3] || '/tmp/medishield-deck/build');
await fs.mkdir(out, {recursive:true});
const p = await PresentationFile.importPptx(await FileBlob.load(input));
const anchors = JSON.parse(await fs.readFile(path.join(repo, 'scripts/deck_anchors.json')));
const order=[1,2,3,5,7,8,11,12,4,6,9,10];
// PPTX round-trips can regenerate object anchor IDs. Resolve the preserved shape
// names within the original/current slide order so the delivered deck rebuilds too.
const snapshot=(await p.inspect({kind:'slide,textbox,shape,table',maxChars:200000})).ndjson.split('\n').filter(Boolean).map(JSON.parse);
const alreadyOrdered=snapshot.some(a=>a.text==='Ready for a supervised pilot');
const targets=new Map(anchors.map(a=>{
 const slide=alreadyOrdered?order.indexOf(a.slide)+1:a.slide;
 const found=snapshot.find(s=>s.slide===slide&&s.kind===a.kind&&(a.kind==='slide'||s.name===a.name));
 if(!found) throw new Error(`Template object missing: slide ${slide}, ${a.name||a.kind}`);
 return [a.id,found.id];
}));
const resolve=id=>p.resolve(targets.get(id)||id);
const load = async name => JSON.parse(await fs.readFile(path.join(repo, `docs/eval_results/${name}.json`)));
const held = await load('official-heldout');
const pct = x => `${(100*x).toFixed(1).replace('.0','')}%`;
const colorMap = {
  FFFFFF:'#F8FAFC',F3F8F9:'#0B1220',E1F2F3:'#193344',D8E4E7:'#334155',
  '0F7F8A':'#2DD4BF','12424D':'#F8FAFC','1F2D3D':'#F8FAFC','5B6B7A':'#CBD5E1',
  '2E8B57':'#5EE3A0',C0392B:'#FCA5A5',D68910:'#FBBF24',C9E6E8:'#CBD5E1','9FC9CD':'#CBD5E1',
  F8FAFC:'#F8FAFC',CBD5E1:'#CBD5E1','2DD4BF':'#2DD4BF','5EE3A0':'#5EE3A0',FCA5A5:'#FCA5A5',FBBF24:'#FBBF24',
};
// Keep source geometry, fonts, diagrams and native tables. Only colors and copy change.
for (const slide of p.slides.items) slide.background.fill='#0B1220';
for (const a of anchors.filter(a=>a.kind==='textbox'||a.kind==='shape')) {
  const sh=resolve(a.id), proto=sh.toProto();
  const fill=proto.shape?.fill?.color?.value;
  if(fill) sh.fill=fill==='FFFFFF'?'#142238':fill==='12424D'?'#203A4D':colorMap[fill]||`#${fill}`;
  if(a.kind==='textbox') {
    const c=proto.paragraphs?.[0]?.runs?.[0]?.textStyle?.fill?.color?.value;
    sh.text.style={color:colorMap[c]||'#F8FAFC'};
  }
  sh.shadow='shadow-none';
}
const replacements = {
 'sh/sryl4zqx':'Evidence, live workflow and pilot recommendation',
 'sh/b29kza94':'Ready for a supervised pilot',
 'sh/9wnqhczy':pct(held.decision.accuracy_all), 'sh/mtwrmxg7':'document decisions', 'sh/nu58f2hs':`${held.decision.n_all} labels · all included`,
 'sh/xk7qlczu':pct(held.cases.accuracy), 'sh/ahwrqhgj':'case decisions', 'sh/bip8jmho':`${held.cases.n} complete cases`,
 'sh/do3q9szq':`$${held.ops.cold_cost_per_case_usd.toFixed(2)}`, 'sh/t8byxkn2':'model cost / case', 'sh/s72xofmh':'uncached equivalent',
 'sh/65kfmpor':`${held.ops.case_latency_s.p50}s`, 'sh/hcvy14ne':'graph median', 'sh/gbmxszmt':'cached replay · local',
 'sh/p0vy54na':'Shadow real scans; measure safety, review effort and cost.',
 'sh/298ryl4v':'A large intake cost; savings still need a pilot',
 'sh/e10f2twf':'MEASURED MODEL SPEND',
 'sh/03ix43e5':`${held.ops.case_latency_s.p50}s`, 'sh/14ryd8fq':'cached graph median',
 'sh/rm1k7yt4':'Required scope is implemented',
 'sh/0ba143al':'APPENDIX · SCOPE',
 'sh/jadsz2xk':'✓  Seven agent roles, routed by type\n✓  Intake API and case workflow\n✓  Policy checks with page refs\n✓  Operations and review screens\n✓  Labelled evaluation',
 'sh/v6tsv2xo':'✓  Confidence calibration\n✓  ID tamper signals\n✓  Spanish and Hindi samples\n✓  Audit PDF export\n✓  Optional AI tracing',
 'sh/p0batw72':'Pilot capabilities',
 'sh/oz29krqh':'✓  Assistant with sources\n✓  Email intake\n✓  Policy version updates\n✓  Review quality monitor\n✓  Regression tests in CI',
 'sh/z2tcnm5s':'Read → verify → decide → review',
 'sh/sb6xsvu9':'Rules decide',
 'sh/gfi5grih':'Review missing checks', 'sh/fe94nm1w':'Claims match an active member record',
 'sh/pkr6tgjy':'Live demo · 90 sec', 'sh/4ji5kbid':'Upload → evidence → review → audit PDF',
 'sh/zi98nu94':'APPENDIX · ARCHITECTURE', 'sh/87ipkzal':'AWS components and current boundaries',
 'sh/idk7ehkr':'Current: AgentCore runtime + DynamoDB/S3. Durable AWS graph checkpoints remain future work.',
 'sh/ydkbm5sv':'Measured on the official held-out split',
 'sh/a9ojq5kz':pct(held.classification.accuracy), 'sh/xcz2l03q':`classification · ${held.classification.n} docs`,
 'sh/n6x0fqlo':pct(held.extraction.rubric_claim_completeness), 'sh/25ojml43':`${held.extraction.rubric_n} required claim fields`,
 'sh/o761ov2t':pct(held.retrieval['recall@3']), 'sh/f2d0b6lc':`Recall@3 · ${held.retrieval.queries} expected queries`,
 'sh/id4ju1oz':pct(held.decision.accuracy_all), 'sh/jedkn654':`all ${held.decision.n_all} document labels`,
 'sh/50v2pgna':pct(held.cases.accuracy), 'sh/q143ylov':`${held.cases.n} case decisions`,
 'sh/s3ml0v61':pct(held.decision.accuracy_visible), 'sh/d4f2t0nm':`${held.decision.n_visible} visible-label documents`,
 'sh/e5o32lor':`Synthetic data · offline replay · ${held.ops.cache_hits}/${held.ops.llm_calls} model calls cached · not a production accuracy estimate`,
 'sh/g72x4zyd':'SAFETY AND REVIEW', 'sh/ri9g7uhw':'Controls are implemented; limits are visible',
 'sh/kfixwbe1':'Recorded events hash-chained', 'sh/tw7e9gnq':'Injection tests', 'sh/svydgb65':'0 flips in 7 attack documents',
 'sh/6twve1oz':'Trace redaction', 'sh/5sne5wne':'Privacy review before real data',
 'sh/0b65obm9':'APPENDIX · OPERATIONS', 'sh/nex4jq5k':'Tests separate code safety from model quality',
 'sh/2xsjepgb':'Agent runs, costs and review history', 'sh/cnu1kzyd':'303 SQLite tests passed',
 'sh/do3id4fy':'302 DynamoDB + 2 replay tests',
 'sh/98ji147e':'21 saved-result gates', 'sh/87a18zqt':'Fresh model evaluation is separate',
 'sh/cbu58j2h':'APPENDIX · ENGINEERING', 'sh/zelojyl8':'Tradeoffs have evidence and limits',
 'sh/n69grmpw':'What remains unproven',
 'sh/mps7a5or':'People confirm recommendations',
 'sh/tgrm1wzy':'1.  Name a pilot team and adjudication owner\n2.  Review model-provider and data controls\n3.  Scope SSO and durable AWS checkpoints',
};
for(const [id,text] of Object.entries(replacements)) resolve(id).text=text;
resolve('sh/uh0na1g3').text.style={color:'#2DD4BF'};
for(const id of ['sh/twfux0ne','sh/dcnm98zm']) resolve(id).text.style={color:'#CBD5E1'};
resolve('sh/547294r6').fill='#2DD4BF';
for(const id of ['sh/k3yl0zql','sh/7qp4be9c']) resolve(id).fill='#0B1220';
for(const id of ['sh/w32dkbuh','sh/x4vedgvm','sh/ahkvi1cb','sh/v2twb6dw','sh/k7mxovud','sh/58vehgvy','sh/i54fmlc7'])
 resolve(id).text.style={color:'#0B1220'};
// Metric values in the business-case column stay tied to the same published run.
const business=anchors.filter(a=>a.slide===3&&a.kind==='textbox');
for(const a of business){
 if(a.text.startsWith('≈ $')&&a.text.endsWith('k')) resolve(a.id).text=`≈ $${Math.round(held.ops.cold_cost_per_doc_usd*1020000/1000)}k`;
 if(a.text==='≈ $0.02') resolve(a.id).text=`≈ $${held.ops.cold_cost_per_doc_usd.toFixed(2)}`;
}
const tables=[
 ['tb/fqhg3ixs',[
  ['Change','Evidence','Scope'],
  ['OCR-first routing','Historical A/B: ~25% lower cost','Optional auto mode'],
  ['Smaller model routing','Historical A/B: ~36% lower cost','Earlier evaluation'],
  ['Smaller reranker','Gold-set retrieval comparison','Synthetic policies'],
  ['Text-only extraction','Lower cost; accuracy fell','Not adopted'],
 ]],
 ['tb/rexkf2d4',[
  ['Risk / missing evidence','Next validation'],
  ['Real scans and new policy families','Shadow pilot; independently adjudicated cases'],
  ['Subtle or forged identity documents','Specialist review; broader tamper test set'],
  ['Privacy and external model boundary','Provider review, SSO and retention validation'],
  ['Durable resume across AWS restarts','Persistent graph checkpoint design and tests'],
  ['Cold latency and review effort','Uncached benchmark and timed reviewer study'],
 ]],
];
for(const [id,rows] of tables){
 const t=resolve(id);
 rows.forEach((r,ri)=>r.forEach((value,ci)=>{
  const c=t.getCell(ri,ci);c.value=value;c.fill=ri===0?'#193344':ri%2?'#142238':'#0F1B2D';
  c.text.style={typeface:'Calibri',fontSize:ri===0?23:21,color:ri===0?'#2DD4BF':'#F8FAFC',bold:ri===0||ci===0};
 }));
 t.borders.assign({fill:'#334155',width:1,style:'solid'});
}
const notes = {
 1:'0:00–0:25. Introduce the intake problem and the recommendation: a supervised shadow pilot. The 8 main slides plus a 90-second live demo total about 8 minutes. Four appendix slides support questions.',
 2:`0:25–1:10. Lead with all-label document accuracy ${pct(held.decision.accuracy_all)} and case accuracy ${pct(held.cases.accuracy)}. The visible-label subset is secondary. Model cost is an uncached equivalent calculated from recorded usage, not this replay's spend. Cached graph timing excludes startup and prefetch. Source: docs/eval_results/official-heldout.json; provenance and limitations in docs/IMPLEMENTATION_REVIEW.md.`,
 3:'1:10–1:50. The assignment provides 85,000 documents/month, 120 reviewers, $18.4M/year and 4.2 days per claim. The model-spend projection excludes reviewers, infrastructure and operational costs. Do not compare cached graph latency with end-to-end business turnaround as a proven saving. Source: assignment brief and docs/eval_results/official-heldout.json.',
 5:'1:50–2:30 explanation, then 2:30–4:00 live demo. Show a prepared case, source document and extracted evidence, per-code policy citations, decision rule and a review action. Export the audit PDF. Use a second reviewer for a four-eyes override. Missing required outputs and uncertain membership require review. An active matching member record permits claim-only intake. For recording, run the local verified build; the AWS deployment has not been updated by this change. Fallback: docs/screenshots and docs/manual_testing.md.',
 7:`4:00–5:00. These are fresh graph replays using stored perception/model responses, not new live LLM calls or a new blind benchmark. ${held.decision.n_all} documents in ${held.cases.n} cases. Missing extraction and retrieval outputs now remain in the denominator. Report all-label document and case accuracy first. Three document-label misses remain; see the report rather than removing them from the score. Source: docs/eval_results/official-heldout.json.`,
 8:'5:00–5:45. Explain API role enforcement, four-eyes review and the audit chain. Seven adversarial documents produced zero decision flips in the historical test; this does not establish universal injection resistance. Redaction and spend caps are implemented, but regulated-data deployment still needs review. Sources: backend/tests, docs/redteam.md, docs/chat_redteam.md.',
 11:'5:45–6:45. Explain limits without claiming production readiness. The data are synthetic, subtle forged IDs remain difficult, and cold latency needs separate measurement. The current AWS workflow needs durable graph checkpoint work for reliable cross-restart resume. Provider privacy review and SSO are pilot prerequisites. Source: docs/IMPLEMENTATION_REVIEW.md and docs/EVAL_REPORT.md.',
 12:'6:45–7:45. Propose shadow, assisted and carefully gated straight-through phases. The 95% agreement and 5% override thresholds shown here are proposed pilot criteria, not achieved production results. Also require no unresolved critical safety defects and review of false approvals by scenario. Name the owner, data review and reliability work. Close by asking for the pilot decision.',
 4:'Appendix A. Seven logical agent roles are routed by document type; every document does not run every specialist. Confidence is an evaluation-calibrated estimate, not a guarantee. Tracing is optional. Repository remains private by owner instruction. Demo video remains pending. Sources: README.md; assignment brief.',
 6:'Appendix B. The diagram describes current component choices, not verified production reliability. Bedrock AgentCore hosts runtimes; it does not by itself imply every model call uses the Bedrock model API. Persistent AWS graph checkpoints, SSO and scale validation remain future work. No deployment was performed in this revision. Sources: infra and docs/IMPLEMENTATION_REVIEW.md.',
 9:'Appendix C. Local checks: 303 SQLite tests; 302 DynamoDB tests plus one backend-specific skip; 2 real-stack replay tests. CI runs deterministic graph failure cases and gates over saved evaluation artifacts. CI does not run a fresh live-model benchmark on every change. The local preflight verifies cached OCR/retrieval assets. Sources: docs/IMPLEMENTATION_REVIEW.md and .github/workflows/ci.yml.',
 10:'Appendix D. These optimization comparisons are historical experiments, not newly measured savings in this code revision. The current replay uses always-vision mode by default; auto is optional. Do not mix latency or costs across settings. Sources: docs/eval_results/ab/ and docs/eval_results/reranker.json; docs/EVAL_REPORT.md.',
};
for (const a of anchors.filter(a=>a.kind==='slide')){
 const slide=resolve(a.id);slide.speakerNotes.textFrame.setText(notes[a.slide]);
 for(const text of anchors.filter(t=>t.slide===a.slide&&t.kind==='textbox')){
  if(text.text===String(a.slide)&&a.slide!==1) resolve(text.id).text=String(order.indexOf(a.slide)+1);
  if(text.text==='MediShield Health · Claims intake · Solution review for the CTO')
   resolve(text.id).text=order.indexOf(a.slide)<8?'MediShield Health · Capstone review':'MediShield Health · Appendix';
 }
}
const proto=p.toProto();
p.slides.replace(order.map(n=>proto.slides.find(s=>s.id===resolve(anchors.find(a=>a.kind==='slide'&&a.slide===n).id).id)));
await (await PresentationFile.exportPptx(p)).save(path.join(out,'candidate.pptx'));
for(let i=0;i<p.slides.items.length;i++){
 const slide=p.slides.items[i];
 await fs.writeFile(path.join(out,`slide-${i+1}.png`),new Uint8Array(await(await p.export({slide,format:'png',scale:1})).arrayBuffer()));
 await fs.writeFile(path.join(out,`slide-${i+1}.layout.json`),await(await slide.export({format:'layout'})).text());
}
console.log(`Exported 12 editable slides to ${out}`);
