// ===== shoprenter sync — all Code nodes (wf GvzOXxllrtuTTPBK) =====
// PARITY = text/payload/hash composition Claude Code must match.
// INFRA  = delta/purge/upsert plumbing (Claude Code already reimplemented).


// ----------------------------------------------------------------------
// [INFRA] NODE: Prep Conn
// ----------------------------------------------------------------------
const cfg = $('Get Sync Config').first().json || {};
const apiBase = String(cfg.api_base || '').trim();
let shop = '';
const m = apiBase.match(/https?:\/\/([^.\/]+)\.api2?\.myshoprenter\.hu/i);
if (m) shop = m[1];
const resourceBase = apiBase.replace(/\/+$/, '');
const tokenUrl = 'https://oauth.app.shoprenter.net/' + shop + '/app/token';
let pub = String(cfg.public_url || '').trim();
if (pub && !/\/$/.test(pub)) pub += '/';
return [{ json: {
  client_id: String(cfg.client_id || '').trim().toLowerCase(),
  shop: shop,
  token_url: tokenUrl,
  resource_base: resourceBase,
  public_url: pub,
  api_cid: String(cfg.api_client_id || ''),
  api_csec: String(cfg.api_client_secret || '')
} }];

// ----------------------------------------------------------------------
// [INFRA] NODE: SR Fetch Products
// ----------------------------------------------------------------------
const conn = $('Prep Conn').first().json;
const base = String(conn.resource_base || '').replace(/\/+$/,'');
let token = '';
try { token = $('SR Get Token').first().json.access_token || ''; } catch (e) {}
const out = [];
const MAXP = 100;
let page = 0;
while (page < MAXP) {
  let resp;
  try {
    resp = await this.helpers.httpRequest({
      method: 'GET',
      url: base + '/productExtend',
      qs: { full: 1, limit: 200, page: page },
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' },
      json: true,
      timeout: 60000
    });
  } catch (e) { break; }
  const body = resp || {};
  const items = body.items || (body.response && body.response.items) || [];
  out.push({ json: { items: items, page: page, pageCount: (body.pageCount != null ? body.pageCount : null) } });
  const hasNext = !!(body && body.next) || (body.pageCount != null && (page + 1) < body.pageCount);
  if (!items.length || !hasNext) break;
  page++;
}
if (!out.length) out.push({ json: { items: [], page: 0, pageCount: 0 } });
return out;

// ----------------------------------------------------------------------
// [PARITY] NODE: Build Product Texts
// ----------------------------------------------------------------------
const conn = $('Prep Conn').first().json;
const pub = conn.public_url || '';
const pages = $input.all();
function dec(s){ return String(s||'').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'\"').replace(/&#39;/g,"'").replace(/&amp;/g,'&'); }
function strip(s){ return dec(s).replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim(); }
function huf(v){ const n=parseFloat(v); return isFinite(n)? Math.round(n).toLocaleString('hu-HU') : ''; }
function _fnv32hex(str){ let h=0x811c9dc5>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,0x01000193)>>>0; } return (h>>>0).toString(16); }
function cleanParams(raw){ const s=dec(String(raw||'')); const lines=s.split(/\r?\n/); const out=[]; for(const ln0 of lines){ const ln=ln0.replace(/\t/g,' ').replace(/\s+/g,' ').replace(/\s*:\s*/,': ').trim(); if(ln) out.push(ln); } return out; }
function attrPairs(p){ const out=[]; const pae=Array.isArray(p.productAttributeExtend)?p.productAttributeExtend:[]; for(const a of pae){ const an=String(a.name||'').trim(); let vals=[]; const av=a.value; if(Array.isArray(av)){ for(const x of av){ if(x && typeof x==='object'){ let lid=''; try{ const lh=(x.language&&x.language.id)?x.language.id:''; const dl=Buffer.from(String(lh),'base64').toString('utf8'); const im=dl.match(/=(\d+)/); if(im) lid=im[1]; }catch(e){} if(lid==='1'||lid===''){ if(x.value!=null) vals.push(String(x.value)); } } else if(x!=null){ vals.push(String(x)); } } } else if(av!=null){ vals.push(String(av)); } vals=vals.filter(function(v,i){ return v && vals.indexOf(v)===i; }); if(an && vals.length) out.push(an+': '+vals.join(', ')); } return out; }
const texts=[]; const meta=[];
// --- related products (similar + cross-sell) resolution ---
const allItems=[];
for (const pg2 of pages){ const b2=pg2.json||{}; const it2=b2.items||(b2.response&&b2.response.items)||[]; for(const x of it2) allItems.push(x); }
function nameOf(p){ const ds=Array.isArray(p.productDescriptions)?p.productDescriptions:[]; let d=null; for(const x of ds){ try{ if(Buffer.from(String(x.id),'base64').toString('utf8').indexOf('language_id=1')>=0){ d=x; break; } }catch(e){} } if(!d) d=ds[0]; return d?String(d.name||'').trim():''; }
function urlOf(p){ const ua=Array.isArray(p.urlAliases)?p.urlAliases:[]; if(ua.length && ua[0].urlAlias){ return pub + String(ua[0].urlAlias).replace(/^\/+/,''); } return ''; }
function pidFromHref(href){ try{ const seg=String(href||'').split('?')[0].split('/').pop(); const dd=Buffer.from(seg,'base64').toString('utf8'); const m=dd.match(/product_id=(\d+)/); return m?m[1]:''; }catch(e){ return ''; } }
const byId={};
for(const p of allItems){ const pid=String(p.innerId||''); if(!pid) continue; const nm=nameOf(p); if(!nm) continue; byId[pid]={name:nm,url:urlOf(p)}; }
function buildRel(p, field, refKey){ const arr=Array.isArray(p[field])?p[field]:[]; const out=[]; const seen={}; for(const rel of arr){ const ref=(rel && rel[refKey])?rel[refKey]:null; const href=ref?ref.href:''; const pid=pidFromHref(href); if(!pid) continue; const t=byId[pid]; if(!t||!t.name) continue; if(seen[pid]) continue; seen[pid]=1; let e=t.name; if(t.url) e+=' — '+t.url; out.push(e); } return out.join('; '); }
for (const pg of pages){
  const body = pg.json || {};
  const items = body.items || (body.response && body.response.items) || [];
  for (const p of items){
    const descs = Array.isArray(p.productDescriptions)? p.productDescriptions : [];
    let d = null;
    for (const x of descs){ try{ if(Buffer.from(String(x.id),'base64').toString('utf8').indexOf('language_id=1')>=0){ d=x; break; } }catch(e){} }
    if(!d) d = descs[0];
    let name = d ? String(d.name||'').trim() : '';
    if(!name) continue;
    const prices = Array.isArray(p.productPrices)? p.productPrices : [];
    let gross=null, grossSpecial=null;
    if(prices.length){ gross=prices[0].gross; grossSpecial=prices[0].grossSpecial; }
    const price = (grossSpecial!=null && grossSpecial!=='') ? grossSpecial : gross;
    const stock = (p.stock1!=null)? String(p.stock1).replace(/\.0+$/,'') : '';
    const orderable = String(p.orderable)==='1';
    const active = String(p.status)==='1';
    let url='';
    const ua = Array.isArray(p.urlAliases)? p.urlAliases : [];
    if(ua.length && ua[0].urlAlias){ url = pub + String(ua[0].urlAlias).replace(/^\/+/,''); }
    const sku = String(p.sku||p.modelNumber||'');
    const manu = (p.manufacturer && p.manufacturer.name)? String(p.manufacturer.name) : '';
    let sd = d ? strip(d.shortDescription) : '';
    if(sd.length>600) sd = sd.slice(0,600)+'...';
    let ld = d ? strip(d.description) : '';
    if(ld.length>8000) ld = ld.slice(0,8000)+'...';
    let params = attrPairs(p).concat(cleanParams(d ? d.parameters : ''));
    let paramStr = params.join('; ');
    if(paramStr.length>8000) paramStr = paramStr.slice(0,8000)+'...';
    let line = name;
    const ph = huf(price);
    if(ph) line += ' — ' + ph + ' Ft';
    const avail = (!active)? 'inaktív' : (orderable? 'rendelhető' : 'jelenleg nem rendelhető');
    line += ' (' + avail + (stock!==''? (', készlet: '+stock+' db') : '') + ')';
    if(manu) line += '. Márka: ' + manu;
    if(sd) line += '. ' + sd;
    if(ld) line += '. ' + ld;
    if(paramStr) line += '. Paraméterek: ' + paramStr;
    if(url) line += '. Link: ' + url;
    texts.push(line);
    const relSimilar = buildRel(p,'productRelatedProductRelations','relatedProduct');
    const relAdditional = buildRel(p,'productCollateralProductRelations','collateralProduct');
    const content_hash = _fnv32hex(JSON.stringify([name, manu, url, sku, avail, sd, ld, params.slice().sort(), String(relSimilar).split('; ').filter(Boolean).sort(), String(relAdditional).split('; ').filter(Boolean).sort()]));
    meta.push({ name:name, price:(price!=null?String(price):''), stock:stock, url:url, sku:sku, brand:manu, related_similar:relSimilar, related_additional:relAdditional, content_hash:content_hash });
  }
}
return [{ json: { client_id: conn.client_id, filename: '__shoprenter_products__', count: texts.length, texts: texts, meta: meta } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Chunk Texts
// ----------------------------------------------------------------------
const src = $('Delta Filter').first().json;
const texts = src.texts || [];
const meta = src.meta || [];
const SIZE = 100;
const out = [];
for (let i = 0; i < texts.length; i += SIZE) {
  out.push({ json: { texts: texts.slice(i, i + SIZE), meta: meta.slice(i, i + SIZE), client_id: src.client_id, filename: src.filename, offset: i } });
}
if (!out.length) out.push({ json: { texts: [], meta: [], client_id: src.client_id, filename: src.filename, offset: 0 } });
return out;

// ----------------------------------------------------------------------
// [INFRA] NODE: Delta Filter
// ----------------------------------------------------------------------
const src = $('Build Product Texts').first().json;
const texts = src.texts || [];
const meta = src.meta || [];
const client_id = src.client_id;
function _fnv32(str){ let h=0x811c9dc5>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,0x01000193)>>>0; } return h>>>0; }
function _hx(n){ return ('00000000'+(n>>>0).toString(16)).slice(-8); }
function detUuid(key){ const a=_fnv32(key),b=_fnv32('a:'+key),c=_fnv32('b:'+key),e=_fnv32('c:'+key); let h=_hx(a)+_hx(b)+_hx(c)+_hx(e); const y=(((parseInt(h[16],16)||0)&0x3)|0x8).toString(16); return h.slice(0,8)+'-'+h.slice(8,12)+'-4'+h.slice(13,16)+'-'+y+h.slice(17,20)+'-'+h.slice(20,32); }
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
const chTexts = [], chMeta = []; const allIds = [];
let changed = 0, unchanged = 0;
for (let i = 0; i < meta.length; i++) {
  const m = meta[i];
  const id = detUuid(client_id+':'+(m.sku||m.url||m.name||''));
  allIds.push(id);
  const h = m.content_hash || '';
  const old = existingHash[id];
  if (scrollOk && old !== undefined && old !== '' && old === h) { unchanged++; }
  else { chTexts.push(texts[i]); chMeta.push(m); changed++; }
}
return [{ json: { client_id: client_id, filename: src.filename, texts: chTexts, meta: chMeta, allIds: allIds, changed: changed, unchanged: unchanged, total: meta.length, scrollOk: scrollOk } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Build Product Points
// ----------------------------------------------------------------------
const chunks = $('Chunk Texts').all();
const embs = $('Embed Products').all();
function _fnv32(str){ let h=0x811c9dc5>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,0x01000193)>>>0; } return h>>>0; }
function _hx(n){ return ('00000000'+(n>>>0).toString(16)).slice(-8); }
function detUuid(key){ const a=_fnv32(key),b=_fnv32('a:'+key),c=_fnv32('b:'+key),e=_fnv32('c:'+key); let h=_hx(a)+_hx(b)+_hx(c)+_hx(e); const y=(((parseInt(h[16],16)||0)&0x3)|0x8).toString(16); return h.slice(0,8)+'-'+h.slice(8,12)+'-4'+h.slice(13,16)+'-'+y+h.slice(17,20)+'-'+h.slice(20,32); }

function uuid(){ return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g,function(c){var r=Math.random()*16|0;var v=c==='x'?r:(r&0x3|0x8);return v.toString(16);}); }
const points = [];
let client_id = '';
for (let ci = 0; ci < chunks.length; ci++){
  const c = chunks[ci].json || {};
  client_id = c.client_id || client_id;
  const texts = c.texts || [];
  const meta = c.meta || [];
  const e = (embs[ci] && embs[ci].json) ? embs[ci].json : {};
  let data = (e && e.data) ? e.data : ((e && e.body && e.body.data) ? e.body.data : []);
  if (Array.isArray(data) && data.length && data[0] && data[0].index != null) { data = data.slice().sort(function(a,b){ return a.index - b.index; }); }
  for (let i = 0; i < texts.length; i++){
    const row = data[i];
    const vec = (row && row.embedding) ? row.embedding : null;
    if (!vec) continue;
    const m = meta[i] || {};
    points.push({ id: detUuid(client_id+':'+(m.sku||m.url||m.name||'')), vector: vec, payload: { client_id: client_id, filename: '__shoprenter_products__', type: 'product', text: texts[i], name: m.name, price: m.price, stock: m.stock, url: m.url, sku: m.sku, brand: m.brand, related_similar: m.related_similar || '', related_additional: m.related_additional || '', content_hash: m.content_hash || '' } });
  }
}
return [{ json: { points: points, count: points.length, client_id: client_id } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Upsert Product Points
// ----------------------------------------------------------------------
const src = $('Build Product Points').first().json;
const points = src.points || [];
const SIZE = 200;
let upserted = 0;
for (let i = 0; i < points.length; i += SIZE){
  const batch = points.slice(i, i + SIZE);
  try {
    await this.helpers.httpRequest({
      method: 'PUT',
      url: 'http://qdrant:6333/collections/cx_chatbot/points?wait=true',
      body: { points: batch },
      json: true,
      timeout: 60000
    });
    upserted += batch.length;
  } catch (e) { /* skip failed batch, continue */ }
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