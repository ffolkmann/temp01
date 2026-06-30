// ===== sellvio sync — all Code nodes (wf RMlmusDY3K58gm3N) =====
// PARITY = text/payload/hash composition Claude Code must match.
// INFRA  = delta/purge/upsert plumbing (Claude Code already reimplemented).


// ----------------------------------------------------------------------
// [INFRA] NODE: Prep
// ----------------------------------------------------------------------
const cfg = $('Get Sync Config').first().json || {};
let base = String(cfg.api_base || '').trim().replace(/\/+$/,'');
const cid = String(cfg.api_client_id || '').trim();
const sec = String(cfg.api_client_secret || '').trim();
return [{ json: { client_id: String(cfg.client_id||'').trim().toLowerCase(), base: base, cid: cid, sec: sec } }];

// ----------------------------------------------------------------------
// [INFRA] NODE: Sellvio Fetch Products
// ----------------------------------------------------------------------
const base = String($('Prep').first().json.base || '').replace(/\/+$/,'');
const token = String($('Sellvio Token').first().json.access_token || '');
if(!token){ throw new Error('Sellvio: no access_token'); }
const headers = { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' };
const all = [];
let page = 1, lastPage = 1, breakPage = 0, breakReason = '';
const lastPageSeen = [];
for (let guard = 0; guard < 5000; guard++) {
  let resp = null, ok = false, lastErr = '', st = 0;
  for (let attempt = 0; attempt < 4 && !ok; attempt++) {
    try {
      resp = await this.helpers.httpRequest({ method: 'GET', url: base + '/api/v2/products', qs: { page: page, limit: 100, locale: 'hu' }, headers: headers, json: true, timeout: 60000, returnFullResponse: true });
      st = resp && resp.statusCode;
      const bd = resp && resp.body;
      if (bd && bd.data && Array.isArray(bd.data.items)) { resp = bd; ok = true; }
      else { lastErr = 'shape st=' + st; await new Promise(function(r){ setTimeout(r, 1200 * (attempt + 1)); }); }
    } catch (e) { lastErr = String(e); await new Promise(function(r){ setTimeout(r, 1200 * (attempt + 1)); }); }
  }
  if (!ok) { throw new Error('Sellvio fetch failed at page ' + page + ': ' + lastErr); }
  const data = resp.data;
  const items = data.items || [];
  for (const it of items) all.push(it);
  lastPage = data.last_page || page;
  if (page <= 25) lastPageSeen.push({ p: page, lp: data.last_page, tot: data.total, n: (data.next_page_url === null ? 'null' : 'url'), it: items.length });
  const next = data.next_page_url;
  if (next === null || next === undefined) { breakPage = page; breakReason = 'next_null'; break; }
  if (page >= lastPage) { breakPage = page; breakReason = 'page>=last(' + lastPage + ')'; break; }
  page += 1;
}
return [{ json: { items: all, count: all.length, pages: page, last_page: lastPage, breakPage: breakPage, breakReason: breakReason, lastPageSeen: lastPageSeen } }];

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
// [INFRA] NODE: Delta Filter
// ----------------------------------------------------------------------
const src = $('Build Product Points').first().json;
const texts = src.texts || [];
const items = src.items || [];
const client_id = src.client_id;
const base = 'http://qdrant:6333/collections/cx_chatbot';
const existingHash = {};
let next = null; let scrollOk = true;
const DL = Date.now() + 90000;
for (let i = 0; i < 1000; i++) {
  if (Date.now() > DL) { scrollOk = false; break; }
  const body = { filter: { must: [ { key:'client_id', match:{value:client_id} }, { key:'type', match:{value:'product'} } ] }, limit: 1000, with_payload: ['content_hash'], with_vector: false };
  if (next) body.offset = next;
  let r;
  try { r = await this.helpers.httpRequest({ method:'POST', url: base+'/points/scroll', body: body, json:true, timeout:60000 }); }
  catch (e) { scrollOk = false; break; }
  const res = (r && r.result) ? r.result : {};
  for (const p of (res.points||[])) { existingHash[String(p.id)] = (p.payload && p.payload.content_hash!=null) ? String(p.payload.content_hash) : ''; }
  next = res.next_page_offset;
  if (!next) break;
}
const chTexts = [], chItems = []; const allIds = [];
let changed = 0, unchanged = 0;
for (let i = 0; i < items.length; i++) {
  const it = items[i];
  allIds.push(String(it.id));
  const h = (it.payload && it.payload.content_hash) ? String(it.payload.content_hash) : '';
  const old = existingHash[String(it.id)];
  if (scrollOk && old !== undefined && old !== '' && old === h) { unchanged++; }
  else { chTexts.push(texts[i]); chItems.push(it); changed++; }
}
return [{ json: { client_id: client_id, texts: chTexts, items: chItems, allIds: allIds, changed: changed, unchanged: unchanged, total: items.length, scrollOk: scrollOk } }];

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
function detUuid(key){ const a=fnv32(key),b=fnv32('a:'+key),c=fnv32('b:'+key),e=fnv32('c:'+key); let h=hx(a)+hx(b)+hx(c)+hx(e); const y=(((parseInt(h[16],16)||0)&0x3)|0x8).toString(16); return h.slice(0,8)+'-'+h.slice(8,12)+'-4'+h.slice(13,16)+'-'+y+h.slice(17,20)+'-'+h.slice(20,32); }
const rows=[];
for (const inp of $input.all()){
  const j=inp.json||{};
  let items=null;
  if (j.data && Array.isArray(j.data.items)) items=j.data.items;
  else if (j.body && j.body.data && Array.isArray(j.body.data.items)) items=j.body.data.items;
  else if (Array.isArray(j.items)) items=j.items;
  if (items) for(const x of items) rows.push(x);
}
function purl(p){ return String(p.pretty_url||''); }
const byId={}; const catMembers={}; const catSize={};
for(const p of rows){
  const id=String(p.id!=null?p.id:''); if(!id) continue;
  if(p.is_visible===false) continue;
  byId[id]={name:String(p.name||'').trim(), url:purl(p)};
  const cats=(p.categories&&typeof p.categories==='object')?p.categories:{};
  for(const ck in cats){ catSize[ck]=(catSize[ck]||0)+1; if(!catMembers[ck])catMembers[ck]=[]; if(catMembers[ck].length<40) catMembers[ck].push(id); }
}
function relSimilar(p){
  const id=String(p.id);
  const cats=(p.categories&&typeof p.categories==='object')?Object.keys(p.categories):[];
  cats.sort(function(a,b){return (catSize[a]||0)-(catSize[b]||0);});
  const out=[]; const seen={}; seen[id]=1;
  for(const ck of cats){ const mem=catMembers[ck]||[]; for(const mid of mem){ if(seen[mid])continue; const t=byId[mid]; if(!t||!t.name)continue; seen[mid]=1; let e=t.name; if(t.url)e+=' \u2014 '+t.url; out.push(e); if(out.length>=5) return out.join('; '); } }
  return out.join('; ');
}
const texts=[]; const items=[];
for(const p of rows){
  const id=String(p.id!=null?p.id:''); if(!id) continue;
  if(p.is_visible===false) continue;
  const name=String(p.name||'').trim(); if(!name) continue;
  const url=purl(p); const sku=String(p.code||'');
  const price=(p.price&&p.price.brutto_price!=null)?p.price.brutto_price:'';
  const ph=huf(price);
  let brand=''; if(p.brand&&p.brand.name) brand=String(p.brand.name);
  const cats=(p.categories&&typeof p.categories==='object')?Object.keys(p.categories).map(function(k){return String((p.categories[k]&&p.categories[k].name)||'');}).filter(Boolean):[];
  let lead=strip(p.lead_text||''); if(lead.length>300) lead=lead.slice(0,300)+'...';
  let ld=strip(p.description||''); if(ld.length>800) ld=ld.slice(0,800)+'...';
  let line=name;
  if(ph) line+=' \u2014 '+ph+' Ft';
  if(brand) line+='. M\u00e1rka: '+brand;
  if(cats.length) line+='. Kateg\u00f3ria: '+cats.join(', ');
  if(lead) line+='. '+lead;
  if(ld) line+='. '+ld;
  if(url) line+='. Link: '+url;
  if(line.length>9000) line=line.slice(0,9000)+'...';
  texts.push(line);
  const cHash = (fnv32(name+'|'+brand+'|'+cats.slice().sort().join(',')+'|'+lead+'|'+ld+'|'+url)>>>0).toString(16);
  items.push({ id: detUuid(client_id+':'+id), payload: { client_id: client_id, filename:'__sellvio_products__', type:'product', text: line, name: name, price:(price!=null?String(price):''), url: url, sku: sku, sellvio_id: id, brand: brand, related_similar: relSimilar(p), related_additional: '', content_hash: cHash } });
}
return [{ json: { client_id: client_id, count: texts.length, texts: texts, items: items } }];

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