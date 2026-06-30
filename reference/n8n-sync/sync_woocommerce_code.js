// ===== woocommerce sync — all Code nodes (wf bnCd9mTgHVMNg8OZ) =====
// PARITY = text/payload/hash composition Claude Code must match.
// INFRA  = delta/purge/upsert plumbing (Claude Code already reimplemented).


// ----------------------------------------------------------------------
// [INFRA] NODE: Prep
// ----------------------------------------------------------------------
const cfg = $('Get Sync Config').first().json || {};
const ck = String(cfg.wc_ck || cfg.api_client_id || '').trim();
const cs = String(cfg.wc_cs || cfg.api_client_secret || '').trim();
let base = String(cfg.api_base || '').trim().replace(/\/+$/,'');
return [{ json: { client_id: String(cfg.client_id || '').trim().toLowerCase(), base: base, ck: ck, cs: cs } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Build Product Points
// ----------------------------------------------------------------------
const conn = $('Prep').first().json;
const client_id = conn.client_id;
function dec(s){ return String(s||'').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#0?39;/g,"'").replace(/&#8217;/g,"'").replace(/&nbsp;/gi,' ').replace(/&amp;/g,'&'); }
function strip(s){ return dec(s).replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim(); }
function huf(v){ const n=parseFloat(v); return isFinite(n)? Math.round(n).toLocaleString('hu-HU'):''; }
function fnv32(str){ let h=0x811c9dc5>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,0x01000193)>>>0; } return h>>>0; }
function hx(n){ return ('00000000'+(n>>>0).toString(16)).slice(-8); }
function detUuid(key){ const a=fnv32(key),b=fnv32('a:'+key),c=fnv32('b:'+key),d=fnv32('c:'+key); let h=hx(a)+hx(b)+hx(c)+hx(d); const y=(((parseInt(h[16],16)||0)&0x3)|0x8).toString(16); return h.slice(0,8)+'-'+h.slice(8,12)+'-4'+h.slice(13,16)+'-'+y+h.slice(17,20)+'-'+h.slice(20,32); }
const rows=[];
for (const inp of $input.all()){
  const r=inp.json;
  if (Array.isArray(r)) { for(const x of r) rows.push(x); }
  else if (r && Array.isArray(r.body)) { for(const x of r.body) rows.push(x); }
  else if (r && r.id!=null) { rows.push(r); }
  else if (r && r.body && r.body.id!=null) { rows.push(r.body); }
}
const byId={}; const catMembers={}; const catSize={};
for(const _p of rows){ const _id=String(_p && _p.id!=null?_p.id:''); if(!_id) continue; byId[_id]={name:String((_p&&_p.name)||'').trim(), url:String((_p&&_p.permalink)||'')}; const _cats=Array.isArray(_p.categories)?_p.categories:[]; for(const _c of _cats){ const ck=String(_c&&_c.id!=null?_c.id:''); if(!ck) continue; catSize[ck]=(catSize[ck]||0)+1; if(!catMembers[ck])catMembers[ck]=[]; if(catMembers[ck].length<40) catMembers[ck].push(_id); } }
function relList(ids){ const arr=Array.isArray(ids)?ids:[]; const out=[]; const seen={}; for(const id of arr){ const k=String(id); if(!k||seen[k]) continue; const t=byId[k]; if(!t||!t.name) continue; seen[k]=1; let e=t.name; if(t.url) e+=' — '+t.url; out.push(e); } return out.join('; '); }
function relSimilarCat(p){ const id=String(p.id); const cats=(Array.isArray(p.categories)?p.categories:[]).map(function(c){return String(c&&c.id!=null?c.id:'');}).filter(Boolean); cats.sort(function(a,b){return (catSize[a]||0)-(catSize[b]||0);}); const out=[]; const seen={}; seen[id]=1; for(const ck of cats){ const mem=catMembers[ck]||[]; for(const mid of mem){ if(seen[mid])continue; const t=byId[mid]; if(!t||!t.name)continue; seen[mid]=1; let e=t.name; if(t.url)e+=' — '+t.url; out.push(e); if(out.length>=8) return out.join('; '); } } return out.join('; '); }
const texts=[]; const items=[];
for (const p of rows){
  const wid=String(p.id!=null?p.id:''); if(!wid) continue;
  const name=String(p.name||'').trim(); if(!name) continue;
  const sku=String(p.sku||''); const url=String(p.permalink||'');
  const eff=(p.on_sale && p.sale_price!=null && p.sale_price!=='')?p.sale_price:p.price;
  const ph=huf(eff);
  let brand=''; if(Array.isArray(p.brands)&&p.brands.length&&p.brands[0]&&p.brands[0].name) brand=String(p.brands[0].name);
  const cats=Array.isArray(p.categories)?p.categories.map(function(c){return String(c.name||'');}).filter(Boolean):[];
  let sd=strip(p.short_description||''); if(sd.length>600) sd=sd.slice(0,600)+'...';
  let ld=strip(p.description||''); if(ld.length>6000) ld=ld.slice(0,6000)+'...';
  const attrs=[];
  if(Array.isArray(p.attributes)){ for(const a of p.attributes){ const an=String(a.name||'').trim(); const ov=Array.isArray(a.options)?a.options.map(function(x){return String(x);}).filter(Boolean):[]; if(an&&ov.length) attrs.push(an+': '+ov.join(', ')); } }
  let stockNote='';
  if(p.manage_stock===true && p.stock_quantity!=null) stockNote='készlet: '+p.stock_quantity+' db';
  else if(p.stock_status==='instock') stockNote='raktáron';
  else if(p.stock_status==='outofstock') stockNote='jelenleg nincs raktáron';
  else if(p.stock_status==='onbackorder') stockNote='elérhető (utánrendelés)';
  let line=name;
  if(ph) line+=' — '+ph+' Ft';
  if(stockNote) line+=' ('+stockNote+')';
  if(brand) line+='. Márka: '+brand;
  if(cats.length) line+='. Kategória: '+cats.join(', ');
  if(sd) line+='. '+sd;
  if(ld) line+='. '+ld;
  if(attrs.length) line+='. Paraméterek: '+attrs.join('; ');
  if(url) line+='. Link: '+url;
  if(line.length>9000) line=line.slice(0,9000)+'...';
  texts.push(line);
  const relSimilar = relSimilarCat(p);
  const relAdditional = relList([].concat(Array.isArray(p.upsell_ids)?p.upsell_ids:[], Array.isArray(p.cross_sell_ids)?p.cross_sell_ids:[]));
  const cHash = (fnv32(name+'|'+brand+'|'+cats.slice().sort().join(',')+'|'+sd+'|'+ld+'|'+attrs.slice().sort().join(';')+'|'+url+'|'+[].concat(Array.isArray(p.upsell_ids)?p.upsell_ids:[],Array.isArray(p.cross_sell_ids)?p.cross_sell_ids:[]).map(String).sort().join(','))>>>0).toString(16);
  items.push({ id: detUuid(client_id+':'+wid), payload: { client_id: client_id, filename:'__woocommerce_products__', type:'product', text: line, name: name, price:(eff!=null?String(eff):''), url: url, sku: sku, wc_id: wid, brand: brand, related_similar: relSimilar, related_additional: relAdditional, content_hash: cHash } });
}
return [{ json: { client_id: client_id, count: texts.length, texts: texts, items: items } }];

// ----------------------------------------------------------------------
// [INFRA] NODE: Delta Filter
// ----------------------------------------------------------------------
const src = $('Build Product Points').first().json;
const texts = src.texts || [];
const items = src.items || [];
const client_id = src.client_id;
const base = 'http://qdrant:6333/collections/cx_chatbot';
// existing wc_id -> content_hash
const existingHash = {};
let next = null; let scrollOk = true;
const DL = Date.now() + 90000;
for (let i = 0; i < 1000; i++) {
  if (Date.now() > DL) { scrollOk = false; break; }
  const body = { filter: { must: [ { key:'client_id', match:{value:client_id} }, { key:'type', match:{value:'product'} } ] }, limit: 1000, with_payload: ['wc_id','content_hash'], with_vector: false };
  if (next) body.offset = next;
  let r;
  try { r = await this.helpers.httpRequest({ method:'POST', url: base+'/points/scroll', body: body, json:true, timeout:60000 }); }
  catch (e) { scrollOk = false; break; }
  const res = (r && r.result) ? r.result : {};
  for (const p of (res.points||[])) { const pl = p.payload||{}; const k = String(pl.wc_id!=null?pl.wc_id:''); if (k) existingHash[k] = (pl.content_hash!=null?String(pl.content_hash):''); }
  next = res.next_page_offset;
  if (!next) break;
}
// split changed vs unchanged; collect ALL current ids for purge
const chTexts = [], chItems = []; const allIds = [];
let changed = 0, unchanged = 0;
for (let i = 0; i < items.length; i++) {
  const it = items[i];
  allIds.push(String(it.id));
  const wid = String(it.payload && it.payload.wc_id!=null ? it.payload.wc_id : '');
  const h = (it.payload && it.payload.content_hash) ? String(it.payload.content_hash) : '';
  const old = existingHash[wid];
  if (scrollOk && old !== undefined && old !== '' && old === h) { unchanged++; }
  else { chTexts.push(texts[i]); chItems.push(it); changed++; }
}
return [{ json: { client_id: client_id, texts: chTexts, items: chItems, allIds: allIds, changed: changed, unchanged: unchanged, total: items.length, scrollOk: scrollOk } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Chunk Texts
// ----------------------------------------------------------------------
const src = $('Delta Filter').first().json;
const texts = src.texts || [];
const KEYARR = src.items || [];
const SIZE = 100;
const out = [];
for (let i = 0; i < texts.length; i += SIZE) {
  out.push({ json: { texts: texts.slice(i, i + SIZE), items: KEYARR.slice(i, i + SIZE), client_id: src.client_id, offset: i } });
}
if (!out.length) out.push({ json: { texts: [], items: [], client_id: src.client_id, offset: 0 } });
return out;

// ----------------------------------------------------------------------
// [PARITY] NODE: Make Point
// ----------------------------------------------------------------------
const chunks = $('Chunk Texts').all();
const embs = $('Embed Products').all();
const points=[]; let client_id='';
for (let ci=0; ci<chunks.length; ci++){
  const c=chunks[ci].json||{}; client_id=c.client_id||client_id;
  const items=c.items||[];
  const e=(embs[ci]&&embs[ci].json)?embs[ci].json:{};
  let data=(e&&e.data)?e.data:((e&&e.body&&e.body.data)?e.body.data:[]);
  if(Array.isArray(data)&&data.length&&data[0]&&data[0].index!=null){ data=data.slice().sort(function(a,b){return a.index-b.index;}); }
  for(let i=0;i<items.length;i++){
    const row=data[i]; const vec=(row&&row.embedding)?row.embedding:null; if(!vec) continue;
    points.push({ id: items[i].id, vector: vec, payload: items[i].payload });
  }
}
return [{ json: { points: points, count: points.length, client_id: client_id } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Upsert Product Points
// ----------------------------------------------------------------------
const src = $('Make Point').first().json;
const points = src.points || [];
const SIZE = 200;
let upserted = 0;
for (let i = 0; i < points.length; i += SIZE){
  const batch = points.slice(i, i + SIZE);
  try {
    await this.helpers.httpRequest({ method:'PUT', url:'http://qdrant:6333/collections/cx_chatbot/points?wait=true', body:{ points: batch }, json:true, timeout:60000 });
    upserted += batch.length;
  } catch (e) {}
}
return [{ json: { upserted: upserted, total: points.length, client_id: src.client_id } }];

// ----------------------------------------------------------------------
// [INFRA] NODE: Purge Stale
// ----------------------------------------------------------------------
const df = $('Delta Filter').first().json || {};
const client_id = df.client_id;
const allIds = df.allIds || [];
const newIds = {}; for (const id of allIds) newIds[String(id)] = 1;
const newCount = allIds.length;
if (!client_id || newCount === 0) { return [{ json: { purged: 0, skipped: 'no_new_points', client_id: client_id || '' } }]; }
const base = 'http://qdrant:6333/collections/cx_chatbot';
const existing = []; let next = null;
for (let i = 0; i < 1000; i++) {
  const body = { filter: { must: [ { key: 'client_id', match: { value: client_id } }, { key: 'type', match: { value: 'product' } } ] }, limit: 1000, with_payload: false, with_vector: false };
  if (next) body.offset = next;
  let r;
  try { r = await this.helpers.httpRequest({ method: 'POST', url: base + '/points/scroll', body: body, json: true, timeout: 60000 }); }
  catch (e) { return [{ json: { purged: 0, skipped: 'scroll_error', error: String(e), client_id: client_id } }]; }
  const res = (r && r.result) ? r.result : {};
  const pts = res.points || [];
  for (const p of pts) existing.push(String(p.id));
  next = res.next_page_offset;
  if (!next) break;
}
const oldCount = existing.length;
if (oldCount > 0 && newCount < oldCount * 0.5) { return [{ json: { purged: 0, skipped: 'suspicious_shrink', newCount: newCount, oldCount: oldCount, client_id: client_id } }]; }
const stale = existing.filter(function (id) { return !newIds[id]; });
let purged = 0; const SIZE = 500;
for (let i = 0; i < stale.length; i += SIZE) {
  const batch = stale.slice(i, i + SIZE);
  try { await this.helpers.httpRequest({ method: 'POST', url: base + '/points/delete?wait=true', body: { points: batch }, json: true, timeout: 60000 }); purged += batch.length; }
  catch (e) {}
}
return [{ json: { purged: purged, stale: stale.length, newCount: newCount, oldCount: oldCount, client_id: client_id } }];