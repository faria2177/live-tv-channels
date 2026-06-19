/**
 * CircleFTP TV Series Scraper
 * Extension-এর content.js + background.js logic থেকে port করা
 * Node.js + Cheerio দিয়ে headless scraping
 */

const fs = require('fs');
const path = require('path');
const https = require('https');
const http = require('http');

// ─── Config ───────────────────────────────────────────────────────────────────
const CATEGORIES = [
  {
    name: 'English_Tv_Series',
    baseUrl: 'https://main.circleftp.net/category/english-foreign-tv-series/page/',
    pages: 70,
    outputFile: 'series/CF/English_Tv_Series.json'
  },
  {
    name: 'Dubbed_Tv_Series',
    baseUrl: 'http://main.circleftp.net/category/dubbed-tv-series-shows/page/',
    pages: 25,
    outputFile: 'series/CF/Dubbed_Tv_Series.json'
  },
  {
    name: 'Hindi_Tv_Series',
    baseUrl: 'http://main.circleftp.net/category/hindi-tv-serials/page/',
    pages: 25,
    outputFile: 'series/CF/Hindi_Tv_Series.json'
  }
];

const DELAY_MS = 1200;        // প্রতি request-এর মাঝে বিরতি (rate limiting)
const DETAIL_DELAY_MS = 800;  // detail page fetch বিরতি
const CF_DOMAIN = 'circleftp.net';

// ─── Helpers (extension-এর content.js থেকে direct port) ──────────────────────
const VIDEO_EXT = /\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m3u8|mpg|mpeg|3gp|ogv|m3u|rmvb)([\?#]|$)/i;
const IMG_EXT = /\.(jpg|jpeg|png|webp|gif|bmp|avif)([?#]|$)/i;
const SKIP_HOSTS = ['google', 'gstatic', 'googleapis', 'doubleclick', 'facebook', 'twitter', 'analytics', 'googlesyndication'];

function today() { return new Date().toISOString().slice(0, 10); }
function isVid(u) { return VIDEO_EXT.test(u); }
function isImg(u) { return IMG_EXT.test(u); }
function clean(t) { return (t || '').replace(/\s+/g, ' ').trim(); }
function skipUrl(u) {
  try { const h = new URL(u).hostname; return SKIP_HOSTS.some(d => h.includes(d)); }
  catch { return true; }
}
function getFilename(u) {
  try { return decodeURIComponent(new URL(u).pathname.split('/').pop()); }
  catch { return ''; }
}

function extractQuality(text) {
  const m = (text || '').match(/\b(2160p?|4K|UHD|1080p?|720p?|480p?|360p?)\b/i);
  return m ? m[1] : '';
}
function extractLanguage(text, url) {
  const combined = ((text || '') + ' ' + (url || '')).toLowerCase();
  if (/hindi.?dual|dual.?hindi|dual.?audio/i.test(combined)) return 'Hindi Dual';
  if (/hindi/i.test(combined)) return 'Hindi';
  if (/tamil/i.test(combined)) return 'Tamil';
  if (/telugu/i.test(combined)) return 'Telugu';
  if (/bengali|bangla/i.test(combined)) return 'Bengali';
  return 'English';
}
function extractYear(text) {
  const m = (text || '').match(/\b(19|20)\d{2}\b/);
  return m ? m[0] : new Date().getFullYear().toString();
}
function parseEpisode(text) {
  let m;
  m = (text || '').match(/[Ss][:\.]?(\d{1,2})[\s:\.]?[Ee][:\.]?(\d{1,3})/);
  if (m) return { season: parseInt(m[1]), episode: parseInt(m[2]) };
  m = (text || '').match(/Season\s*(\d+)\s*Episode\s*(\d+)/i);
  if (m) return { season: parseInt(m[1]), episode: parseInt(m[2]) };
  m = (text || '').match(/\bEp\.?\s*(\d+)/i);
  if (m) return { season: 1, episode: parseInt(m[1]) };
  return null;
}
function cfParseSize(text = '') {
  const m = String(text || '').match(/(\d+(?:\.\d+)?)\s*(GB|MB)/i);
  if (!m) return '';
  const num = Number(m[1]);
  if (!Number.isFinite(num)) return '';
  const mb = /gb/i.test(m[2]) ? num * 1024 : num;
  return mb.toFixed(2).replace(/\.00$/, '');
}
function cfExtractEpisodeTitle(rawText, seriesTitle, season, episode) {
  let title = clean(rawText || '');
  if (!title) return `${seriesTitle}.S:${season}E:${episode}`;
  title = title
    .replace(/https?:\/\/\S+/gi, '')
    .replace(/\b(2160p?|1080p?|720p?|480p?|4K|UHD)\b/gi, '')
    .replace(/\b(Download|Watch|Play|Copy|Server\s*\d+)\b/gi, '')
    .replace(/(\d+(?:\.\d+)?)\s*(GB|MB)/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
  if (!title || title.length > 140) return `${seriesTitle}.S:${season}E:${episode}`;
  return title;
}

// ─── HTTP Fetch (Cheerio ছাড়া pure Node.js HTML parsing) ─────────────────────
function fetchHtml(url, retries = 3) {
  return new Promise((resolve, reject) => {
    const attempt = (n) => {
      const mod = url.startsWith('https') ? https : http;
      const options = {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
          'Accept-Language': 'en-US,en;q=0.5',
          'Connection': 'keep-alive'
        },
        timeout: 30000
      };
      const req = mod.get(url, options, (res) => {
        // Handle redirects
        if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
          const redirectUrl = new URL(res.headers.location, url).href;
          return attempt_url(redirectUrl, n);
        }
        if (res.statusCode !== 200) {
          if (n > 1) { setTimeout(() => attempt(n - 1), 2000); return; }
          return reject(new Error(`HTTP ${res.statusCode} for ${url}`));
        }
        let data = '';
        res.setEncoding('utf8');
        res.on('data', chunk => data += chunk);
        res.on('end', () => resolve(data));
      });
      req.on('error', err => {
        if (n > 1) { setTimeout(() => attempt(n - 1), 2000); return; }
        reject(err);
      });
      req.on('timeout', () => {
        req.destroy();
        if (n > 1) { setTimeout(() => attempt(n - 1), 3000); return; }
        reject(new Error(`Timeout: ${url}`));
      });
    };

    const attempt_url = (u, n) => {
      const mod = u.startsWith('https') ? https : http;
      const req = mod.get(u, {
        headers: {
          'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        },
        timeout: 30000
      }, (res) => {
        if (res.statusCode !== 200) {
          if (n > 1) { setTimeout(() => attempt(n - 1), 2000); return; }
          return reject(new Error(`HTTP ${res.statusCode}`));
        }
        let data = '';
        res.setEncoding('utf8');
        res.on('data', chunk => data += chunk);
        res.on('end', () => resolve(data));
      });
      req.on('error', err => {
        if (n > 1) { setTimeout(() => attempt(n - 1), 2000); return; }
        reject(err);
      });
    };
    attempt(retries);
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ─── HTML Parsing (Regex-based, Cheerio-free) ────────────────────────────────
function parseLinks(html, baseUrl) {
  /** সব <a href="..."> tag থেকে link বের করে */
  const results = [];
  const seen = new Set();
  const hrefRx = /<a\s[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let m;
  while ((m = hrefRx.exec(html)) !== null) {
    try {
      const href = new URL(m[1], baseUrl).href;
      const text = clean(m[2].replace(/<[^>]+>/g, ''));
      if (!seen.has(href)) {
        seen.add(href);
        results.push({ href, text });
      }
    } catch {}
  }
  return results;
}

function getMetaContent(html, property) {
  const m = html.match(new RegExp(`<meta[^>]+(?:property|name)=["']${property}["'][^>]+content=["']([^"']+)["']`, 'i'))
    || html.match(new RegExp(`<meta[^>]+content=["']([^"']+)["'][^>]+(?:property|name)=["']${property}["']`, 'i'));
  return m ? clean(m[1]) : '';
}

function getTagContent(html, tag, cls = '') {
  const rx = cls
    ? new RegExp(`<${tag}[^>]*class=["'][^"']*${cls}[^"']*["'][^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i')
    : new RegExp(`<${tag}[^>]*>([\\s\\S]*?)<\\/${tag}>`, 'i');
  const m = html.match(rx);
  return m ? clean(m[1].replace(/<[^>]+>/g, '')) : '';
}

function extractTitle(html) {
  return getMetaContent(html, 'og:title')
    || getTagContent(html, 'h1')
    || getTagContent(html, 'h2')
    || getTagContent(html, 'title')
    || '';
}

function extractPoster(html, baseUrl) {
  // og:image সবচেয়ে reliable
  const ogImg = getMetaContent(html, 'og:image') || getMetaContent(html, 'twitter:image');
  if (ogImg) {
    try { return new URL(ogImg, baseUrl).href; } catch {}
  }
  // img tag থেকে poster/thumb/featured ধরা
  const imgRx = /<img\s[^>]*(?:src|data-src|data-lazy-src|data-original)=["']([^"']+)["'][^>]*/gi;
  let m;
  while ((m = imgRx.exec(html)) !== null) {
    const src = m[1];
    if (!src || skipUrl(src)) continue;
    if (/poster|thumb|cover|featured|attachment|wp-post-image/i.test(m[0])) {
      try { return new URL(src, baseUrl).href; } catch {}
    }
  }
  return '';
}

// ─── Category Page Parser ─────────────────────────────────────────────────────
function parseCategoryPage(html, baseUrl) {
  /**
   * Category page থেকে সব series-এর detail URL + title + poster বের করে
   * Extension-এর detectCFCategoryPage() এর equivalent
   */
  const items = [];
  const seen = new Set();

  // Article/post cards খোঁজা
  // circleftp.net সাধারণত article.type-post বা .post entries ব্যবহার করে
  const cardRx = /<article[^>]*>([\s\S]*?)<\/article>/gi;
  let cardMatch;

  while ((cardMatch = cardRx.exec(html)) !== null) {
    const cardHtml = cardMatch[1];

    // detail URL
    const linkMatch = cardHtml.match(/<a\s[^>]*href=["']([^"']+)["']/i);
    if (!linkMatch) continue;
    let detailUrl = '';
    try { detailUrl = new URL(linkMatch[1], baseUrl).href; } catch { continue; }

    // category/page link skip করা
    if (/\/(category|cat|tag|page|search|feed|wp-|#)/i.test(new URL(detailUrl).pathname)) continue;
    if (seen.has(detailUrl)) continue;
    seen.add(detailUrl);

    // Poster
    const imgMatch = cardHtml.match(/<img\s[^>]*(?:src|data-src|data-lazy-src|data-original)=["']([^"']+)["']/i);
    let poster = '';
    if (imgMatch) {
      try { poster = new URL(imgMatch[1], baseUrl).href; } catch {}
    }

    // Title (img alt বা heading থেকে)
    const altMatch = cardHtml.match(/<img\s[^>]*alt=["']([^"']+)["']/i);
    const h2Match = cardHtml.match(/<h[1-4][^>]*>([^<]+)<\/h[1-4]>/i);
    const title = clean(altMatch?.[1] || h2Match?.[1] || '');

    if (title.length < 2 || !poster) continue;

    items.push({ detailUrl, title, poster });
  }

  // article tag না থাকলে fallback: img থাকা a[href] খোঁজা
  if (items.length === 0) {
    const links = parseLinks(html, baseUrl);
    for (const { href, text } of links) {
      try {
        const u = new URL(href);
        if (!u.hostname.includes(CF_DOMAIN)) continue;
        if (/\/(category|cat|tag|page|search|feed|wp-|#)/i.test(u.pathname)) continue;
        if (seen.has(href)) continue;
        seen.add(href);
        const title = clean(text);
        if (title.length < 2) continue;
        items.push({ detailUrl: href, title, poster: '' });
      } catch {}
    }
  }

  return items;
}

// ─── Detail Page Parser ───────────────────────────────────────────────────────
function parseDetailPage(html, baseUrl, fallbackTitle = '', fallbackPoster = '', fallbackLanguage = '') {
  /**
   * Series detail page থেকে সব episode link বের করে
   * Extension-এর cfExtractSeriesFromHTML() এর equivalent
   */
  const seriesTitle = clean(extractTitle(html)) || fallbackTitle || 'Unknown Series';
  const poster = extractPoster(html, baseUrl) || fallbackPoster || '';
  const pageText = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  const year = extractYear(`${seriesTitle} ${pageText.slice(0, 1200)} ${baseUrl}`);

  const episodes = [];
  const seen = new Set();
  let fallbackSeason = 1;
  let fallbackEpisode = 1;

  const links = parseLinks(html, baseUrl);

  for (const { href, text } of links) {
    if (!href || skipUrl(href) || !isVid(href)) continue;

    const fn = getFilename(href);
    const ctx = clean(text);

    let ep = parseEpisode(fn) || parseEpisode(ctx) || parseEpisode(href);
    if (!ep) {
      const seasonMatch = (ctx + ' ' + href).match(/(?:season|s)\s*[:._-]?(\d{1,2})/i);
      const episodeMatch = (ctx + ' ' + href).match(/(?:episode|ep|e)\s*[:._-]?(\d{1,3})/i);
      if (seasonMatch || episodeMatch) {
        ep = {
          season: Number(seasonMatch?.[1] || fallbackSeason || 1),
          episode: Number(episodeMatch?.[1] || fallbackEpisode)
        };
      }
    }
    if (!ep) ep = { season: fallbackSeason, episode: fallbackEpisode };
    if (!ep.season || !Number.isFinite(ep.season)) ep.season = fallbackSeason;
    if (!ep.episode || !Number.isFinite(ep.episode)) ep.episode = fallbackEpisode;

    const dedupeKey = `S${ep.season}E${ep.episode}|${href}`;
    if (seen.has(dedupeKey)) continue;
    seen.add(dedupeKey);

    const item = {
      added: today(),
      language: extractLanguage(`${fallbackLanguage} ${seriesTitle} ${ctx} ${href}`, href),
      season: ep.season,
      episode: ep.episode,
      episode_title: cfExtractEpisodeTitle(ctx || fn, seriesTitle, ep.season, ep.episode),
      url: href
    };
    const size = cfParseSize(ctx);
    if (size) item.size = size;
    const quality = extractQuality(ctx + ' ' + href);
    if (quality) item.quality = quality;

    episodes.push(item);

    if (ep.season > fallbackSeason || (ep.season === fallbackSeason && ep.episode >= fallbackEpisode)) {
      fallbackSeason = ep.season;
      fallbackEpisode = ep.episode + 1;
    } else {
      fallbackEpisode += 1;
    }
  }

  episodes.sort((a, b) => a.season - b.season || a.episode - b.episode);
  if (!episodes.length) return null;

  return { title: seriesTitle, year, tvg_logo: poster, links: episodes };
}

// ─── Load Existing JSON (incremental update এর জন্য) ─────────────────────────
function loadExisting(filePath) {
  try {
    if (fs.existsSync(filePath)) {
      const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      // title → series object map বানানো
      const map = {};
      for (const s of (Array.isArray(data) ? data : [])) {
        if (s.title) map[s.title] = s;
      }
      return map;
    }
  } catch {}
  return {};
}

// ─── Merge Series (নতুন episode যোগ করা, পুরানো রাখা) ─────────────────────────
function mergeSeries(existing, newSeries) {
  if (!existing) return newSeries;

  const existingUrls = new Set((existing.links || []).map(l => l.url));
  let added = 0;

  for (const ep of (newSeries.links || [])) {
    if (!existingUrls.has(ep.url)) {
      existing.links.push(ep);
      existingUrls.add(ep.url);
      added++;
    }
  }

  // poster আপডেট করা যদি আগে ছিল না
  if (!existing.tvg_logo && newSeries.tvg_logo) existing.tvg_logo = newSeries.tvg_logo;
  if (!existing.year && newSeries.year) existing.year = newSeries.year;

  existing.links.sort((a, b) => a.season - b.season || a.episode - b.episode);
  return { series: existing, added };
}

// ─── Main Scraper ─────────────────────────────────────────────────────────────
async function scrapeCategory(config) {
  console.log(`\n${'═'.repeat(60)}`);
  console.log(`📺 Scraping: ${config.name}`);
  console.log(`📄 Pages: 1 → ${config.pages}`);
  console.log(`${'═'.repeat(60)}`);

  // আগের data লোড করা
  const outputPath = path.resolve(config.outputFile);
  const dir = path.dirname(outputPath);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  const existingMap = loadExisting(outputPath);
  const resultMap = { ...existingMap };

  let totalNew = 0;
  let totalUpdated = 0;
  let pagesFailed = 0;

  // ─── Step 1: Category pages scan করা ────────────────────────────────────
  for (let page = 1; page <= config.pages; page++) {
    const pageUrl = `${config.baseUrl}${page}/`;
    process.stdout.write(`  [Page ${String(page).padStart(3)}/${config.pages}] Fetching... `);

    let html;
    try {
      html = await fetchHtml(pageUrl);
    } catch (err) {
      console.log(`❌ FAILED: ${err.message}`);
      pagesFailed++;
      await sleep(DELAY_MS);
      continue;
    }

    const items = parseCategoryPage(html, pageUrl);
    console.log(`✅ Found ${items.length} series`);

    // ─── Step 2: প্রতিটা series-এর detail page fetch করা ─────────────────
    for (const item of items) {
      // ইতিমধ্যে বিদ্যমান হলে skip (নতুন episode check তাও করবো)
      const alreadyExists = !!resultMap[item.title];
      if (alreadyExists) {
        // existing series: শুধু update check করার জন্য detail page fetch
        // (optional: পুরোনো series স্কিপ করতে চাইলে continue দিন)
      }

      process.stdout.write(`    → ${item.title.slice(0, 50).padEnd(50)} `);

      let detailHtml;
      try {
        detailHtml = await fetchHtml(item.detailUrl);
        await sleep(DETAIL_DELAY_MS);
      } catch (err) {
        console.log(`❌`);
        continue;
      }

      const language = extractLanguage(item.title + ' ' + config.name + ' ' + item.detailUrl, item.detailUrl);
      const parsed = parseDetailPage(detailHtml, item.detailUrl, item.title, item.poster, language);

      if (!parsed || !parsed.links?.length) {
        console.log(`⚠️  No episodes found`);
        continue;
      }

      if (!resultMap[parsed.title]) {
        // নতুন series
        resultMap[parsed.title] = parsed;
        totalNew++;
        console.log(`🆕 NEW  [${parsed.links.length} eps]`);
      } else {
        // বিদ্যমান series: merge করা
        const { series: merged, added } = mergeSeries(resultMap[parsed.title], parsed);
        resultMap[parsed.title] = merged;
        if (added > 0) {
          totalUpdated++;
          console.log(`🔄 +${added} eps`);
        } else {
          console.log(`✓  No change`);
        }
      }
    }

    await sleep(DELAY_MS);
  }

  // ─── Step 3: JSON সংরক্ষণ ─────────────────────────────────────────────
  const output = Object.values(resultMap).sort((a, b) => a.title.localeCompare(b.title));
  fs.writeFileSync(outputPath, JSON.stringify(output, null, 2), 'utf8');

  console.log(`\n✅ Done: ${config.name}`);
  console.log(`   Total series : ${output.length}`);
  console.log(`   New series   : ${totalNew}`);
  console.log(`   Updated      : ${totalUpdated}`);
  console.log(`   Pages failed : ${pagesFailed}`);
  console.log(`   Saved to     : ${outputPath}`);

  return { total: output.length, new: totalNew, updated: totalUpdated };
}

// ─── Entry Point ──────────────────────────────────────────────────────────────
async function main() {
  const startTime = Date.now();
  console.log('🚀 CircleFTP TV Series Scraper Started');
  console.log(`📅 Date: ${today()}`);

  const results = {};

  // নির্দিষ্ট category argument দিয়ে চালানোর সুবিধা
  const targetCategory = process.argv[2];

  for (const config of CATEGORIES) {
    if (targetCategory && config.name !== targetCategory) continue;
    try {
      results[config.name] = await scrapeCategory(config);
    } catch (err) {
      console.error(`\n❌ Fatal error in ${config.name}:`, err.message);
      results[config.name] = { error: err.message };
    }
  }

  const elapsed = ((Date.now() - startTime) / 1000 / 60).toFixed(1);
  console.log(`\n${'═'.repeat(60)}`);
  console.log(`🏁 All done in ${elapsed} minutes`);
  console.log('Summary:');
  for (const [name, r] of Object.entries(results)) {
    if (r.error) {
      console.log(`  ❌ ${name}: ERROR - ${r.error}`);
    } else {
      console.log(`  ✅ ${name}: ${r.total} series (${r.new} new, ${r.updated} updated)`);
    }
  }
}

main().catch(err => {
  console.error('Fatal:', err);
  process.exit(1);
});
