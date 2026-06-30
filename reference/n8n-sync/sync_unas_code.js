// ===== unas sync — all Code nodes (wf 48aImzQW4QEncluH) =====
// PARITY = text/payload/hash composition Claude Code must match.
// INFRA  = delta/purge/upsert plumbing (Claude Code already reimplemented).


// ----------------------------------------------------------------------
// [INFRA] NODE: Prep Conn
// ----------------------------------------------------------------------
const cfg = $('Get Sync Config').first().json || {};
let pub = String(cfg.public_url || '').trim();
if (pub && !pub.endsWith('/')) pub += '/';
return [{ json: {
  client_id: String(cfg.client_id || '').trim().toLowerCase(),
  unas_key: String(cfg.api_client_secret || '').trim(),
  public_url: pub,
  sync_ts: Date.now()
} }];

// ----------------------------------------------------------------------
// [INFRA] NODE: UN Token
// ----------------------------------------------------------------------
const r = $('UN Login').first().json;
const raw = (r && typeof r.data === 'string') ? r.data : (typeof r === 'string' ? r : (r && typeof r.body === 'string' ? r.body : JSON.stringify(r||{})));
const m = raw.match(/<Token>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)\s*(?:\]\]>)?\s*<\/Token>/i);
return [{ json: { token: m ? m[1] : '' } }];

// ----------------------------------------------------------------------
// [INFRA] NODE: UN Get Url
// ----------------------------------------------------------------------
const r = $('UN Get ProductDB').first().json;
const raw = (r && typeof r.data === 'string') ? r.data : (typeof r === 'string' ? r : (r && typeof r.body === 'string' ? r.body : JSON.stringify(r||{})));
const m = raw.match(/<Url>\s*(?:<!\[CDATA\[)?\s*([^<\]\s]+)\s*(?:\]\]>)?\s*<\/Url>/i);
return [{ json: { url: m ? m[1] : '' } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Build Product Texts
// ----------------------------------------------------------------------
const conn = $('Prep Conn').first().json;
const r = $('UN Download CSV').first().json;
let raw = (r && typeof r.data === 'string') ? r.data : (typeof r === 'string' ? r : (r && typeof r.body === 'string' ? r.body : ''));
const empty = { client_id: conn.client_id, filename: '__unas_products__', count: 0, texts: [], meta: [] };
if (!raw) return [{ json: empty }];
raw = raw.replace(/^\uFEFF/, '');
function _fnv32hex(str){ let h=0x811c9dc5>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,0x01000193)>>>0; } return (h>>>0).toString(16); }
function parseCSV(s, delim){
  const rows=[]; let row=[]; let field=''; let i=0; let inQ=false;
  while(i<s.length){ const c=s[i];
    if(inQ){ if(c==='"'){ if(s[i+1]==='"'){ field+='"'; i+=2; continue; } inQ=false; i++; continue; } field+=c; i++; continue; }
    else { if(c==='"'){ inQ=true; i++; continue; }
      if(c===delim){ row.push(field); field=''; i++; continue; }
      if(c==='\r'){ i++; continue; }
      if(c==='\n'){ row.push(field); rows.push(row); row=[]; field=''; i++; continue; }
      field+=c; i++; continue; } }
  if(field!=='' || row.length){ row.push(field); rows.push(row); }
  return rows;
}
const rows = parseCSV(raw, ';');
if(rows.length<2) return [{ json: empty }];
const header = rows[0].map(h=>String(h).replace(/^\uFEFF/,'').trim());
const ix = n => header.indexOf(n);
const iSku=ix('Cikkszám'), iName=ix('Termék Név'), iGross=ix('Bruttó Ár'), iCat=ix('Kategória'), iShort=ix('Rövid Leírás'), iLong=ix('Tulajdonságok'), iUrl=ix('Termék link'), iStock=ix('Raktárkészlet');
const iAttach=ix('Kiegészítő Termékek'), iSimP=ix('Hasonló Termékek');
let iBrand=ix('Gyártó'); if(iBrand<0) iBrand=ix('Márka'); if(iBrand<0) iBrand=ix('Gyártó név'); if(iBrand<0) iBrand=ix('Manufacturer'); if(iBrand<0) iBrand=ix('Brand');
let iBrandParam=-1; for(let h=0;h<header.length;h++){ const hh=String(header[h]||''); if(/^Paraméter:/.test(hh)){ const pn=hh.replace(/^Paraméter:\s*/,'').split('|')[0].trim(); if(pn==='Gyártó'){ iBrandParam=h; break; } } }
function dec(s){ return String(s||'').replace(/&lt;/g,'<').replace(/&gt;/g,'>').replace(/&quot;/g,'"').replace(/&#39;/g,"'").replace(/&amp;/g,'&'); }
function strip(s){ return dec(s).replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim(); }
function huf(v){ const n=parseFloat(String(v).replace(/\s/g,'').replace(',','.')); return isFinite(n)? Math.round(n).toLocaleString('hu-HU') : ''; }
const texts=[]; const meta=[];
for(let r=1;r<rows.length;r++){
  const cols=rows[r]; if(!cols || cols.length<2) continue;
  const name = iName>=0 ? String(cols[iName]||'').trim() : ''; if(!name) continue;
  const sku = iSku>=0 ? String(cols[iSku]||'').trim() : '';
  const gross = iGross>=0 ? cols[iGross] : '';
  const cat = iCat>=0 ? String(cols[iCat]||'').trim() : '';
  let sd = iShort>=0 ? strip(cols[iShort]) : ''; if(sd.length>300) sd = sd.slice(0,300)+'...';
  let ld = iLong>=0 ? strip(cols[iLong]) : ''; if(ld.length>400) ld = ld.slice(0,400)+'...';
  const url = iUrl>=0 ? String(cols[iUrl]||'').trim() : '';
  const stock = iStock>=0 ? String(cols[iStock]||'').trim().replace(/\.0+$/,'') : '';
  const brand = iBrand>=0 ? String(cols[iBrand]||'').trim() : '';
  const brandParam = iBrandParam>=0 ? String(cols[iBrandParam]||'').trim() : '';
  const relAddSkus = iAttach>=0 ? String(cols[iAttach]||'').split('|').map(function(s){return s.trim();}).filter(Boolean) : [];
  const relSimSkus = iSimP>=0 ? String(cols[iSimP]||'').split('|').map(function(s){return s.trim();}).filter(Boolean) : [];
  let line = name; const ph = huf(gross);
  if(ph) line += ' — ' + ph + ' Ft';
  if(cat) line += ' (' + cat + ')';
  if(stock!=='') line += '. Készlet: ' + stock + ' db';
  if(sd) line += '. ' + sd;
  if(ld) line += '. ' + ld;
  if(brand) line += '. Márka: ' + brand;
  texts.push(line);
  meta.push({ name:name, price:(gross!=null?String(gross):''), stock:stock, url:url, sku:sku, brand:(brand||brandParam), relAddSkus:relAddSkus, relSimSkus:relSimSkus, content_hash: _fnv32hex(line) });
}
return [{ json: { client_id: conn.client_id, filename: '__unas_products__', count: texts.length, texts: texts, meta: meta } }];

// ----------------------------------------------------------------------
// [INFRA] NODE: Delta Filter
// ----------------------------------------------------------------------
// Delta Filter: csak a változott/új termékeket adja tovább embedelésre,
// a változatlanok sync_ts-ét frissíti (hogy a purge ne törölje őket).
const src = $('Build Product Texts').first().json;
const texts = src.texts || [];
const meta = src.meta || [];
const client_id = src.client_id;
const sync_ts = ($('Prep Conn').first().json.sync_ts) || Date.now();

function _fnv32(str){ let h=0x811c9dc5>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,0x01000193)>>>0; } return h>>>0; }
function _hx(n){ return ('00000000'+(n>>>0).toString(16)).slice(-8); }
function detUuid(key){ const a=_fnv32(key),b=_fnv32('a:'+key),c=_fnv32('b:'+key),e=_fnv32('c:'+key); let h=_hx(a)+_hx(b)+_hx(c)+_hx(e); const y=(((parseInt(h[16],16)||0)&0x3)|0x8).toString(16); return h.slice(0,8)+'-'+h.slice(8,12)+'-4'+h.slice(13,16)+'-'+y+h.slice(17,20)+'-'+h.slice(20,32); }

const base = 'http://qdrant:6333/collections/cx_chatbot';

// 1. Meglévő pontok sku -> content_hash lekérése (csak payload, vektor nélkül)
const existingHash = {};
let next = null;
const DL = Date.now() + 90000;
let scrollOk = true;
for (let i = 0; i < 100; i++) {
  if (Date.now() > DL) { scrollOk = false; break; }
  const body = { filter: { must: [ { key:'client_id', match:{value:client_id} }, { key:'type', match:{value:'product'} } ] }, limit: 1000, with_payload: ['sku','content_hash'], with_vector: false };
  if (next) body.offset = next;
  let r;
  try { r = await this.helpers.httpRequest({ method:'POST', url: base+'/points/scroll', body: body, json:true, timeout:60000 }); }
  catch (e) { scrollOk = false; break; }  // hiba -> full embed (biztonságos fallback)
  const res = (r && r.result) ? r.result : {};
  for (const p of (res.points||[])) { const pl = p.payload||{}; if (pl.sku) existingHash[pl.sku] = (pl.content_hash != null ? String(pl.content_hash) : ''); }
  next = res.next_page_offset;
  if (!next) break;
}

// 2. Split: changed/new vs unchanged
const chTexts = [], chMeta = []; const unchangedIds = [];
for (let i = 0; i < meta.length; i++) {
  const m = meta[i];
  const h = m.content_hash || '';
  const old = existingHash[m.sku];
  if (scrollOk && old !== undefined && old !== '' && old === h) {
    unchangedIds.push(detUuid(client_id + ':' + (m.sku || m.url || m.name || '')));
  } else {
    chTexts.push(texts[i]); chMeta.push(m);
  }
}

// 3. Unchanged pontok sync_ts touch (olcsó set_payload, vektor nem mozdul)
let touched = 0;
const SIZE = 1000;
for (let i = 0; i < unchangedIds.length; i += SIZE) {
  const batch = unchangedIds.slice(i, i + SIZE);
  try { await this.helpers.httpRequest({ method:'POST', url: base+'/points/payload?wait=true', body: { payload: { sync_ts: sync_ts }, points: batch }, json:true, timeout:60000 }); touched += batch.length; }
  catch (e) {}
}

return [{ json: { client_id: client_id, filename: '__unas_products__', count: chTexts.length, texts: chTexts, meta: chMeta, unchanged: unchangedIds.length, touched: touched, total: meta.length, scrollOk: scrollOk } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Fetch Relations
// ----------------------------------------------------------------------
const bpt = $('Build Product Texts').first().json;
const allMeta = bpt.meta || [];
const nameBySku = {}; const urlBySku = {};
for (const m of allMeta) { if (m.sku) { nameBySku[m.sku] = m.name || ''; urlBySku[m.sku] = m.url || ''; } }
const relMap = {};
for (const m of allMeta) {
  if (!m.sku) continue;
  const addS = m.relAddSkus || [];
  const simS = m.relSimSkus || [];
  const additional = addS.filter(function(s){ return nameBySku[s]; }).map(function(s){ return { sku: s, name: nameBySku[s] }; }).slice(0, 12);
  const similar = simS.filter(function(s){ return nameBySku[s]; }).map(function(s){ return { sku: s, name: nameBySku[s] }; }).slice(0, 12);
  if (additional.length || similar.length) { relMap[m.sku] = { additional: additional, similar: similar }; }
}
return [{ json: { relMap: relMap, urlBySku: urlBySku, fetched: Object.keys(relMap).length, total: allMeta.length } }];

// ----------------------------------------------------------------------
// [PARITY] NODE: Chunk Texts
// ----------------------------------------------------------------------
const src = $('Delta Filter').first().json;
const texts = src.texts || [];
const KEYARR = src.meta || [];
const SIZE = 250;
const out = [];
for (let i = 0; i < texts.length; i += SIZE) {
  out.push({ json: { texts: texts.slice(i, i + SIZE), meta: KEYARR.slice(i, i + SIZE), client_id: src.client_id, filename: src.filename, offset: i } });
}
if (!out.length) out.push({ json: { texts: [], meta: [], client_id: src.client_id, filename: src.filename, offset: 0 } });
return out;

// ----------------------------------------------------------------------
// [PARITY] NODE: Build Product Points
// ----------------------------------------------------------------------
const chunks = $('Chunk Texts').all();
const embs = $('Embed Products').all();
function _fnv32(str){ let h=0x811c9dc5>>>0; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,0x01000193)>>>0; } return h>>>0; }
function _hx(n){ return ('00000000'+(n>>>0).toString(16)).slice(-8); }
function detUuid(key){ const a=_fnv32(key),b=_fnv32('a:'+key),c=_fnv32('b:'+key),e=_fnv32('c:'+key); let h=_hx(a)+_hx(b)+_hx(c)+_hx(e); const y=(((parseInt(h[16],16)||0)&0x3)|0x8).toString(16); return h.slice(0,8)+'-'+h.slice(8,12)+'-4'+h.slice(13,16)+'-'+y+h.slice(17,20)+'-'+h.slice(20,32); }
const sync_ts = ($('Prep Conn').first().json.sync_ts) || Date.now();
const rel = ($('Fetch Relations').first().json.relMap) || {};
const urlBySku = ($('Fetch Relations').first().json.urlBySku) || {};
function fmtRel(arr){ return (arr||[]).map(function(x){ var u=urlBySku[x.sku]; return u ? (x.name+' — '+u) : x.name; }).join('; '); }
const base = 'http://qdrant:6333/collections/cx_chatbot';
const FLUSH = 200;
let client_id = ''; let built = 0; let upserted = 0;
let buffer = [];
const flush = async () => {
  if (!buffer.length) return;
  const batch = buffer; buffer = [];
  try {
    await this.helpers.httpRequest({ method:'PUT', url: base+'/points?wait=true', body:{ points: batch }, json:true, timeout:60000 });
    upserted += batch.length;
  } catch (e) {}
};
for (let ci = 0; ci < chunks.length; ci++) {
  const c = chunks[ci].json || {}; client_id = c.client_id || client_id;
  const texts = c.texts || []; const meta = c.meta || [];
  const e = (embs[ci] && embs[ci].json) ? embs[ci].json : {};
  let data = (e && e.data) ? e.data : ((e && e.body && e.body.data) ? e.body.data : []);
  if (Array.isArray(data) && data.length && data[0] && data[0].index != null) { data = data.slice().sort(function(a,b){return a.index-b.index;}); }
  for (let i = 0; i < texts.length; i++) {
    const row = data[i]; const vec = (row && row.embedding) ? row.embedding : null; if (!vec) continue;
    const m = meta[i] || {}; const r = rel[m.sku] || {};
    buffer.push({ id: detUuid(client_id+':'+(m.sku||m.url||m.name||'')), vector: vec, payload: { client_id: client_id, filename:'__unas_products__', type:'product', sync_ts: sync_ts, content_hash: (m.content_hash||''), text: texts[i], name: m.name, price: m.price, stock: m.stock, url: m.url, sku: m.sku, brand: m.brand, related_similar: fmtRel(r.similar), related_additional: fmtRel(r.additional) } });
    built++;
    if (buffer.length >= FLUSH) { await flush(); }
  }
}
await flush();
return [{ json: { upserted: upserted, count: built, client_id: client_id, sync_ts: sync_ts } }];

// ----------------------------------------------------------------------
// [INFRA] NODE: Purge Stale
// ----------------------------------------------------------------------
const src = $('Build Product Points').first().json || {};
const df = $('Delta Filter').first().json || {};
const client_id = src.client_id;
const sync_ts = src.sync_ts;
const total = df.total || 0;
const processed = (df.touched || 0) + (src.upserted || 0);  // unchanged touch + changed upsert
if (!client_id || !sync_ts) {
  return [{ json: { purged: 0, skipped: 'no_ctx', client_id: client_id || '' } }];
}
// Biztonsági fék: csak akkor purge, ha a katalógus nagy része friss ts-t kapott
if (total > 0 && processed < total * 0.5) {
  return [{ json: { purged: 0, skipped: 'low_processed', processed: processed, total: total, client_id: client_id } }];
}
const base = 'http://qdrant:6333/collections/cx_chatbot';
let r;
try {
  r = await this.helpers.httpRequest({
    method: 'POST',
    url: base + '/points/delete?wait=true',
    body: { filter: { must: [
      { key: 'client_id', match: { value: client_id } },
      { key: 'type', match: { value: 'product' } },
      { key: 'sync_ts', range: { lt: sync_ts } }
    ] } },
    json: true, timeout: 60000
  });
} catch (e) {
  return [{ json: { purged: 0, skipped: 'delete_error', error: String(e), client_id: client_id } }];
}
const status = (r && r.result && r.result.status) ? r.result.status : 'unknown';
return [{ json: { purged_filter: true, status: status, sync_ts: sync_ts, processed: processed, total: total, client_id: client_id } }];