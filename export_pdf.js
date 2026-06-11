const puppeteer = require('puppeteer');
const path = require('path');
const fs = require('fs');

const HTML = path.resolve(__dirname, 'static', 'LSAMS_Presentation.html');
const OUT  = path.resolve(__dirname, 'static', 'LSAMS_Presentation.pdf');

const SLIDES = ['s0','s1','s2','s3','s4','s5','s6','s7','s8'];
const W = 1280, H = 720;

(async () => {
  const browser = await puppeteer.launch({
    args: ['--no-sandbox', '--disable-setuid-sandbox', '--font-render-hinting=none'],
    headless: true,
  });
  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 2 });

  const url = 'file:///' + HTML.replace(/\\/g, '/');
  await page.goto(url, { waitUntil: 'networkidle0' });

  const pdfs = [];

  for (let i = 0; i < SLIDES.length; i++) {
    // Navigate to slide
    await page.evaluate((idx) => { window.goTo(idx); }, i);
    await new Promise(r => setTimeout(r, 300));

    const buf = await page.pdf({
      width:  W + 'px',
      height: H + 'px',
      printBackground: true,
      margin: { top: 0, bottom: 0, left: 0, right: 0 },
    });
    pdfs.push(buf);
    console.log('  slide', i + 1, '/', SLIDES.length, 'done');
  }

  await browser.close();

  // Merge PDFs using simple concat approach
  // For proper merge we need pdf-lib
  if (pdfs.length === 1) {
    fs.writeFileSync(OUT, pdfs[0]);
  } else {
    // Save individual slides, then merge
    try {
      const { PDFDocument } = require('pdf-lib');
      const merged = await PDFDocument.create();
      for (const buf of pdfs) {
        const doc = await PDFDocument.load(buf);
        const [pg] = await merged.copyPages(doc, [0]);
        merged.addPage(pg);
      }
      const bytes = await merged.save();
      fs.writeFileSync(OUT, bytes);
    } catch(e) {
      // pdf-lib not available, just write first pdf (all pages if single render)
      // Fallback: render all slides in one page call using CSS
      console.log('pdf-lib not found, using single-render fallback...');
      const browser2 = await puppeteer.launch({
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
        headless: true,
      });
      const p2 = await browser2.newPage();
      await p2.setViewport({ width: W, height: H * SLIDES.length });
      await p2.goto(url, { waitUntil: 'networkidle0' });

      // Inject print CSS to show all slides stacked
      await p2.addStyleTag({ content: `
        .nav, .prog { display: none !important; }
        .deck { position: static !important; }
        .slide {
          display: flex !important;
          opacity: 1 !important;
          position: relative !important;
          width: ${W}px !important;
          height: ${H}px !important;
          page-break-after: always;
          break-after: page;
          overflow: hidden;
        }
      `});

      const buf = await p2.pdf({
        width: W + 'px',
        height: H + 'px',
        printBackground: true,
        margin: { top: 0, bottom: 0, left: 0, right: 0 },
      });
      await browser2.close();
      fs.writeFileSync(OUT, buf);
    }
  }

  const kb = Math.round(fs.statSync(OUT).size / 1024);
  console.log('PDF saved:', OUT);
  console.log('Size:', kb, 'KB', '|', SLIDES.length, 'slides');
})().catch(e => { console.error(e); process.exit(1); });
