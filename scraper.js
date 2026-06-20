/**
 * CircleFTP TV Series Scraper v2
 * Extension content.js থেকে exact logic port করা
 *
 * Category page key rule (extension line ~310-330):
 *   a[href] → a.querySelector('img') থাকতেই হবে → poster থাকতে হবে → title থাকতে হবে
 *
 * Detail page key rule (cfExtractSeriesFromHTML):
 *   doc.querySelectorAll('a[href]') → isVid(href) → episode parse
 */

const fs   = require('fs');
const path = require('path');
const http  = require('http');
const https = require('https');

// ── Config ────────────────────────────────────────────────────────────────────
const CATEGORIES = [
  {
    name: 'English_Tv_Series',
    urls: [
      'http://main.circleftp.net/category/english-foreign-tv-series/',
      ...Array.from({length: 69}, (_, i) =>
        `http://main.circleftp.net/category/english-foreign-tv-series/page/${i+2}/`)
    ],
    outputFile: 'series/CF/English_Tv_Series.json',
    language: 'English'
  },
  {
    name: 'Dubbed_Tv_Series',
    urls: [
      'http://main.circleftp.net/category/dubbed-tv-series-shows/',
      ...Array.from({length: 24}, (_, i) =>
        `http://main.circleftp.net/category/dubbed-tv-series-shows/page/${i+2}/`)
    ],
    outputFile: 'series/CF/Dubbed_Tv_Series.json',
    language: 'Hindi Dual'
  },
  {
    name: 'Hindi_Tv_Series',
    urls: [
      'http://main.circleftp.net/category/hindi-tv-serials/',
      ...Array.from({length: 24}, (_, i) =>
        `http://main.circleftp.net/category/hindi-tv-serials/page/${i+2}/`)
    ],
    outputFile: 'series/CF/Hindi_Tv_Series.json',
    language: 'Hindi'
  }
];

const CF_DOMAIN      = 'circleftp.net';
const PAGE_DELAY_MS  = 1500;
const DETAIL_DELAY_MS = 1000;
const VIDEO_EXT = /\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m3u8|mpg|mpeg|3gp|ogv|rmvb)([\?#]|$)/i;
const SKIP_HOSTS = ['google','gstatic','googleapis','doubleclick','facebook','twitter',
                    'analytics','googlesyndication','wp-login','wp-admin'];

// ── Util ──────────────────────────────────────────────────────────────────────
const today  = () => new Date().toISOString().slice(0,10);
const sleep  = ms => new Promise(r => setTimeout(r, ms));
const clean  = t  => (t||'').replace(/\s+/g,' ').trim();
const isVid  = u  => VIDEO_EXT.test(u);
const skipU  = u  => { try { const h=new URL(u).hostname; return SKIP_HOSTS.some(d=>h.includes(d)); } catch { return true; } };
const fname  = u  => { try { return decodeURIComponent(new URL(u).pathname.split('/').pop()); } catch { return ''; } };

function extractQuality(t) {
  const m = (t||'').match(/\b(2160p?|4K|UHD|1080p?|720p?|480p?|360p?)\b/i);
  return m ? m[1] : '';
}
function extractLanguage(text, url) {
  const c = ((text||'')+' '+(url||'')).toLowerCase();
  if (/hindi.?dual|dual.?hindi|dual.?audio/i.test(c)) return 'Hindi Dual';
  if (/hindi/i.test(c))   return 'Hindi';
  if (/tamil/i.test(c))   return 'Tamil';
  if (/telugu/i.test(c))  return 'Telugu';
  if (/bengali|bangla/i.test(c)) return 'Bengali';
  return 'English';
}
function extractYear(text) {
  const m = (text||'').match(/\b(19|20)\d{2}\b/);
  return m ? m[0] : String(new Date().getFullYear());
}
function parseEpisode(text) {
  let m;
  m = (text||'').match(/[Ss]:?(\d{1,2})\s*[Ee]:?(\d{1,3})/);
  if (m) return { season:+m[1], episode:+m[2] };
  m = (text||'').match(/Season\s*(\d+)\s*Episode\s*(\d+)/i);
  if (m) return { season:+m[1], episode:+m[2] };
  m = (text||'').match(/\bEp\.?\s*(\d+)/i);
  if (m) return { season:1, episode:+m[1] };
  return null;
}
function cfParseSize(text='') {
  const m = String(text).match(/(\d+(?:\.\d+)?)\s*(GB|MB)/i);
  if (!m) return '';
  const n = Number(m[1]);
  if (!isFinite(n)) return '';
  return (/gb/i.test(m[2]) ? n*1024 : n).toFixed(2).replace(/\.00$/,'');
}
function cfEpTitle(ctx, title, s, e) {
  let t = clean(ctx||'');
  if (!t) return `${title}.S:${s}E:${e}`;
  t = t.replace(/https?:\/\/\S+/gi,'')
       .replace(/\b(2160p?|1080p?|720p?|480p?|4K|UHD)\b/gi,'')
       .replace(/\b(Download|Watch|Play|Copy|Server\s*\d+)\b/gi,'')
       .replace(/(\d+(?:\.\d+)?)\s*(GB|MB)/gi,'')
       .replace(/\s+/g,' ').trim();
  return (!t || t.length>140) ? `${title}.S:${s}E:${e}` : t;
}

// ── HTTP fetch with redirect + retry ─────────────────────────────────────────
function fetchHtml(url, retries=3, _redirects=5) {
  return new Promise((resolve,reject) => {
    const mod = url.startsWith('https') ? https : http;
    const req = mod.get(url, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Connection': 'keep-alive',
        'Cache-Control': 'no-cache'
      },
      timeout: 30000
    }, res => {
      // Redirect
      if ([301,302,303,307,308].includes(res.statusCode) && res.headers.location && _redirects>0) {
        res.resume();
        const next = new URL(res.headers.location, url).href;
        return fetchHtml(next, retries, _redirects-1).then(resolve).catch(reject);
      }
      if (res.statusCode !== 200) {
        res.resume();
        if (retries>1) return setTimeout(()=>fetchHtml(url,retries-1,_redirects).then(resolve).catch(reject), 2500);
        return reject(new Error(`HTTP ${res.statusCode}: ${url}`));
      }
      // decompress if gzip/br — Node follows gzip auto via accept-encoding removal
      let body='';
      res.setEncoding('utf8');
      res.on('data', c => body+=c);
      res.on('end', ()=>resolve(body));
    });
    req.on('error', err => {
      if (retries>1) return setTimeout(()=>fetchHtml(url,retries-1,_redirects).then(resolve).catch(reject), 2500);
      reject(err);
    });
    req.on('timeout', ()=>{
      req.destroy();
      if (retries>1) return setTimeout(()=>fetchHtml(url,retries-1,_redirects).then(resolve).catch(reject), 3000);
      reject(new Error(`Timeout: ${url}`));
    });
  });
}

// ── HTML helpers (regex-based DOM simulation) ─────────────────────────────────
/**
 * Extension: a[href] যেগুলোর ভেতরে img আছে সেগুলো খোঁজে
 * → poster (img src) + title (img alt / heading) + detailUrl
 */
function parseCategoryPage(html, baseUrl) {
  const items = [];
  const seen  = new Set();

  // <a href="..."> ... <img ...> ... </a>  block খোঁজা
  // greedy match এড়াতে প্রতিটা <a> block সীমিত করা হয়েছে
  const aRx = /<a\s[^>]*href=["']([^"'#][^"']*)["'][^>]*>([\s\S]{0,4000}?)<\/a>/gi;
  let am;
  while ((am = aRx.exec(html)) !== null) {
    const rawHref = am[1].trim();
    const inner   = am[2];

    // img আছে কিনা চেক (extension-এর মূল শর্ত)
    const imgM = inner.match(/<img\s([^>]+)>/i);
    if (!imgM) continue;

    // href normalize
    let href='';
    try { href = new URL(rawHref, baseUrl).href; } catch { continue; }
    if (!new URL(href).hostname.includes(CF_DOMAIN)) continue;
    if (/\/(category|cat|tag|page|search|feed|wp-[^/]|#)/i.test(new URL(href).pathname)) continue;
    if (seen.has(href)) continue;
    seen.add(href);

    // poster: src / data-src / data-lazy-src / data-original
    const imgAttrs = imgM[1];
    const srcM = imgAttrs.match(/(?:^|\s)(?:src|data-src|data-lazy-src|data-original)=["']([^"']+)["']/i);
    let poster = '';
    if (srcM) { try { poster = new URL(srcM[1], baseUrl).href; } catch {} }
    if (!poster) continue;  // extension-এ poster না থাকলে skip

    // title: img alt → h1/h2/h3/h4 → a text
    const altM  = imgAttrs.match(/\balt=["']([^"']+)["']/i);
    const hM    = inner.match(/<h[1-4][^>]*>([^<]+)<\/h[1-4]>/i);
    const aText = inner.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ').trim();
    let title = clean(altM?.[1] || hM?.[1] || aText);
    if (!title || title.length<2) {
      // slug থেকে title বের করা
      try {
        const slug = new URL(href).pathname.split('/').filter(Boolean).pop()||'';
        title = slug.replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase()).trim();
      } catch {}
    }
    if (!title || title.length<2) continue;

    items.push({ href, title, poster });
  }

  return items;
}

/**
 * Detail page থেকে episode links বের করা
 * Extension cfExtractSeriesFromHTML() এর exact port
 */
function parseDetailPage(html, baseUrl, fallbackTitle='', fallbackPoster='', fallbackLang='') {
  // Title
  const titleSel = [
    /og:title["'][^>]*content=["']([^"']+)/i,
    /twitter:title["'][^>]*content=["']([^"']+)/i,
    /<h1[^>]*>([^<]+)<\/h1>/i,
    /<h2[^>]*class="[^"]*(?:entry|post|movie)-title[^"]*"[^>]*>([^<]+)<\/h2>/i,
    /<title>([^<]+)<\/title>/i
  ];
  let seriesTitle = '';
  for (const rx of titleSel) {
    const m = html.match(rx);
    if (m) { seriesTitle = clean(m[1]); break; }
  }
  seriesTitle = seriesTitle || fallbackTitle || 'Unknown Series';

  // Poster (og:image best, then score-based img)
  let poster = '';
  const ogM = html.match(/og:image["'][^>]*content=["']([^"']+)/i)
             || html.match(/content=["']([^"']+)["'][^>]*og:image/i);
  if (ogM) { try { poster = new URL(ogM[1], baseUrl).href; } catch {} }
  if (!poster) {
    // score-based: extension cfFindPosterInDoc logic
    const imgRx2 = /<img\s([^>]+)>/gi;
    let im2; let bestScore=-1;
    while ((im2=imgRx2.exec(html))!==null) {
      const attrs = im2[1];
      const srcM2 = attrs.match(/(?:src|data-src|data-lazy-src|data-original)=["']([^"']+)["']/i);
      if (!srcM2) continue;
      let abs=''; try { abs=new URL(srcM2[1],baseUrl).href; } catch { continue; }
      if (skipU(abs)) continue;
      let score=0;
      if (/poster|thumb|cover|featured|attachment|wp-post-image/i.test(attrs+abs)) score+=5;
      const hM2 = attrs.match(/height=["']?(\d+)/i);
      const wM2 = attrs.match(/width=["']?(\d+)/i);
      const h2=Number(hM2?.[1]||0), w2=Number(wM2?.[1]||0);
      if (h2>=180) score+=3; if (w2>=100) score+=2; if (h2>w2) score+=2;
      if (abs.includes('/uploads/')) score+=1;
      if (score>bestScore) { bestScore=score; poster=abs; }
    }
  }
  poster = poster || fallbackPoster || '';

  const pageText = html.replace(/<[^>]+>/g,' ').replace(/\s+/g,' ');
  const year = extractYear(`${seriesTitle} ${pageText.slice(0,1200)} ${baseUrl}`);

  // Episode links
  const episodes=[], seen=new Set();
  let fbS=1, fbE=1;

  const aRx2 = /<a\s[^>]*href=["']([^"']+)["'][^>]*>([\s\S]{0,600}?)<\/a>/gi;
  let am2;
  while ((am2=aRx2.exec(html))!==null) {
    let href='';
    try { href=new URL(am2[1].trim(), baseUrl).href; } catch { continue; }
    if (!href || skipU(href) || !isVid(href)) continue;

    const aText = clean(am2[2].replace(/<[^>]+>/g,' '));

    // context: a text + parent element text (simulate closest('tr,li,div,p'))
    // HTML regex limitation: approximate by grabbing 300 chars before the tag
    const preCtx = pageText.slice(Math.max(0, html.indexOf(am2[0])-200), html.indexOf(am2[0])).replace(/\s+/g,' ').slice(-200);
    const ctx = clean(`${aText} ${preCtx}`);

    let ep = parseEpisode(fname(href)) || parseEpisode(aText) || parseEpisode(ctx) || parseEpisode(href);
    if (!ep) {
      const sM = (ctx+' '+href).match(/(?:season|s)\s*[:._-]?(\d{1,2})/i);
      const eM = (ctx+' '+href).match(/(?:episode|ep|e)\s*[:._-]?(\d{1,3})/i);
      if (sM||eM) ep={ season:Number(sM?.[1]||fbS), episode:Number(eM?.[1]||fbE) };
    }
    if (!ep) ep={ season:fbS, episode:fbE };
    if (!ep.season  || !isFinite(ep.season))  ep.season=fbS;
    if (!ep.episode || !isFinite(ep.episode)) ep.episode=fbE;

    const key=`S${ep.season}E${ep.episode}|${href}`;
    if (seen.has(key)) continue;
    seen.add(key);

    const item = {
      added: today(),
      language: extractLanguage(`${fallbackLang} ${seriesTitle} ${ctx} ${href}`, href),
      season: ep.season,
      episode: ep.episode,
      episode_title: cfEpTitle(ctx||fname(href), seriesTitle, ep.season, ep.episode),
      url: href
    };
    const sz=cfParseSize(ctx); if (sz) item.size=sz;
    const q=extractQuality(ctx+' '+href); if (q) item.quality=q;
    episodes.push(item);

    if (ep.season>fbS||(ep.season===fbS&&ep.episode>=fbE)) { fbS=ep.season; fbE=ep.episode+1; }
    else fbE++;
  }

  // video URL regex fallback (extension cfExtractLinksFromHTML also does this)
  const vidRx = /["'](https?:\/\/[^"'\s]+\.(?:mkv|mp4|avi|webm|m4v|ts|m3u8|mpg|mpeg)[^"'\s]*?)["']/gi;
  let vm;
  while ((vm=vidRx.exec(html))!==null) {
    const href=vm[1];
    if (skipU(href)||!isVid(href)) continue;
    const key=`|${href}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const item={ added:today(), language:extractLanguage(fallbackLang+' '+href,href),
                 season:fbS, episode:fbE,
                 episode_title:`${seriesTitle}.S:${fbS}E:${fbE}`, url:href };
    const q2=extractQuality(href); if (q2) item.quality=q2;
    episodes.push(item);
    fbE++;
  }

  episodes.sort((a,b)=>a.season-b.season||a.episode-b.episode||a.url.localeCompare(b.url));
  if (!episodes.length) return null;
  return { title:seriesTitle, year, tvg_logo:poster, links:episodes };
}

// ── JSON load/save ────────────────────────────────────────────────────────────
function loadExisting(file) {
  try {
    if (fs.existsSync(file)) {
      const arr = JSON.parse(fs.readFileSync(file,'utf8'));
      return Object.fromEntries((Array.isArray(arr)?arr:[]).filter(s=>s.title).map(s=>[s.title,s]));
    }
  } catch {}
  return {};
}
function mergeSeries(existing, fresh) {
  const existUrls = new Set((existing.links||[]).map(l=>l.url));
  let added=0;
  for (const ep of (fresh.links||[])) {
    if (!existUrls.has(ep.url)) { existing.links.push(ep); existUrls.add(ep.url); added++; }
  }
  if (!existing.tvg_logo && fresh.tvg_logo) existing.tvg_logo=fresh.tvg_logo;
  if (!existing.year     && fresh.year)     existing.year=fresh.year;
  existing.links.sort((a,b)=>a.season-b.season||a.episode-b.episode);
  return added;
}

// ── Category scraper ──────────────────────────────────────────────────────────
async function scrapeCategory(cfg) {
  console.log(`\n${'═'.repeat(65)}`);
  console.log(`📺  ${cfg.name}  (${cfg.urls.length} pages)`);
  console.log(`${'═'.repeat(65)}`);

  const outPath = path.resolve(cfg.outputFile);
  fs.mkdirSync(path.dirname(outPath), { recursive:true });
  const map = loadExisting(outPath);

  let nNew=0, nUpd=0, nFail=0;

  for (let pi=0; pi<cfg.urls.length; pi++) {
    const pageUrl = cfg.urls[pi];
    const label   = `Page ${String(pi+1).padStart(3)}/${cfg.urls.length}`;
    process.stdout.write(`  [${label}] `);

    let html;
    try { html = await fetchHtml(pageUrl); }
    catch (err) { console.log(`❌ ${err.message}`); nFail++; await sleep(PAGE_DELAY_MS); continue; }

    const items = parseCategoryPage(html, pageUrl);
    console.log(`${items.length} series found`);

    for (const item of items) {
      process.stdout.write(`       ↳ ${item.title.slice(0,48).padEnd(48)} `);

      let dHtml;
      try { dHtml = await fetchHtml(item.href); await sleep(DETAIL_DELAY_MS); }
      catch { console.log(`❌`); continue; }

      const parsed = parseDetailPage(dHtml, item.href, item.title, item.poster, cfg.language);
      if (!parsed || !parsed.links?.length) { console.log(`⚠ 0 eps`); continue; }

      const key = parsed.title;
      if (!map[key]) {
        map[key] = parsed; nNew++;
        console.log(`🆕 ${parsed.links.length} eps`);
      } else {
        const added = mergeSeries(map[key], parsed);
        if (added>0) { nUpd++; console.log(`🔄 +${added} eps`); }
        else           console.log(`✓`);
      }
    }

    // intermediate save every 5 pages
    if ((pi+1)%5===0 || pi===cfg.urls.length-1) {
      const arr = Object.values(map).sort((a,b)=>a.title.localeCompare(b.title));
      fs.writeFileSync(outPath, JSON.stringify(arr,null,2), 'utf8');
    }

    await sleep(PAGE_DELAY_MS);
  }

  const arr = Object.values(map).sort((a,b)=>a.title.localeCompare(b.title));
  fs.writeFileSync(outPath, JSON.stringify(arr,null,2), 'utf8');
  console.log(`\n  ✅ Done | total=${arr.length} | new=${nNew} | updated=${nUpd} | page-errors=${nFail}`);
  return { total:arr.length, new:nNew, updated:nUpd };
}

// ── Entry ─────────────────────────────────────────────────────────────────────
async function main() {
  console.log('🚀 CircleFTP Scraper v2  –  ' + today());
  const target = process.argv[2];
  const results = {};
  for (const cfg of CATEGORIES) {
    if (target && cfg.name!==target) continue;
    try { results[cfg.name] = await scrapeCategory(cfg); }
    catch(err) { console.error(`\n❌ Fatal [${cfg.name}]:`, err.message); results[cfg.name]={error:err.message}; }
  }
  console.log('\n──────────────────────────────────────────────────────────────');
  for (const [n,r] of Object.entries(results))
    console.log(r.error ? `  ❌ ${n}: ${r.error}` : `  ✅ ${n}: ${r.total} series (${r.new} new, ${r.updated} updated)`);
}

main().catch(e=>{ console.error(e); process.exit(1); });
