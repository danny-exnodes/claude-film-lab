#!/usr/bin/env node
// Render frames of tools/toon/page.html in headless Chromium (Playwright, preinstalled). Free; no network.
//   node tools/toon/shoot.cjs --spec spec.json --out DIR [--frames all|0,12,24] [--jpg] [--quality 0.92]
// Writes DIR/NNNNNN.png|jpg and prints one JSON line: { frames, written, ms_per_frame, warnings, webgl }.
// Chromium runs with software WebGL (SwiftShader) so the three.js looks render in a container without a GPU.
'use strict';
const fs = require('node:fs');
const path = require('node:path');

function args() {
  const a = { frames: 'all', jpg: false, quality: 0.92 };
  const v = process.argv.slice(2);
  for (let i = 0; i < v.length; i++) {
    const k = v[i];
    if (k === '--spec') a.spec = v[++i];
    else if (k === '--out') a.out = v[++i];
    else if (k === '--frames') a.frames = v[++i];
    else if (k === '--jpg') a.jpg = true;
    else if (k === '--quality') a.quality = +v[++i];
    else { console.error(`shoot: unknown argument ${k}`); process.exit(2); }
  }
  if (!a.spec || !a.out) { console.error('usage: shoot.cjs --spec spec.json --out DIR [--frames all|0,12] [--jpg]'); process.exit(2); }
  return a;
}

(async () => {
  const a = args();
  let chromium;
  try { ({ chromium } = require('playwright')); } catch (e) { console.error('shoot: playwright is not installed'); process.exit(3); }
  const spec = JSON.parse(fs.readFileSync(a.spec, 'utf8'));
  fs.mkdirSync(a.out, { recursive: true });
  const launch = { args: ['--allow-file-access-from-files', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader',
                          '--ignore-gpu-blocklist', '--disable-background-timer-throttling'] };
  if (process.env.FILM_CHROMIUM) launch.executablePath = process.env.FILM_CHROMIUM;
  const browser = await chromium.launch(launch);
  try {
    const page = await browser.newPage({ viewport: { width: Math.min(spec.w || 1920, 1920), height: Math.min(spec.h || 1080, 1080) } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    await page.addInitScript(`window.SPEC = ${JSON.stringify(spec)};`);
    await page.goto('file://' + path.resolve(__dirname, 'page.html'));
    const info = await page.evaluate(() => window.READY.then((r) => r, (e) => ({ error: String(e) })));
    if (info.error) { console.error('shoot: READY failed: ' + info.error); process.exit(1); }
    const webgl = await page.evaluate(() => { const c = document.createElement('canvas').getContext('webgl2'); return c ? c.getParameter(c.VERSION) : null; });
    const list = a.frames === 'all' ? Array.from({ length: info.frames }, (_, i) => i)
      : a.frames.split(',').filter(Boolean).map(Number).filter((i) => i >= 0 && i < Math.max(1, info.frames));
    const type = a.jpg ? 'image/jpeg' : 'image/png', ext = a.jpg ? 'jpg' : 'png';
    const t0 = Date.now();
    for (const i of list) {
      const url = await page.evaluate(([i, type, q]) => { window.renderFrame(i); return window.grab(type, q); }, [i, type, a.quality]);
      fs.writeFileSync(path.join(a.out, String(i).padStart(6, '0') + '.' + ext), Buffer.from(url.split(',')[1], 'base64'));
    }
    const warnings = await page.evaluate(() => TOON.report());
    if (errors.length) { console.error('shoot: page errors:\n  ' + errors.join('\n  ')); process.exit(1); }
    console.log(JSON.stringify({ frames: info.frames, written: list.length, ms_per_frame: list.length ? Math.round((Date.now() - t0) / list.length) : 0,
                                 warnings, webgl }));
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error('shoot: ' + (e && e.stack || e)); process.exit(1); });
