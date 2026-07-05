/* ============================================================
   ocr.js — קריאת חשבוניות מקומית (OCR) וחילוץ שדות
   משתמש ב-Tesseract.js (עברית+אנגלית) ו-pdf.js (לרסטור PDF).
   הכל רץ בדפדפן. הפרסור הוריסטי — יש לאשר לפני שמירה.
   ============================================================ */

'use strict';

const OCR = (() => {

  /* ---------- הגדרת worker של pdf.js ---------- */
  function ensurePdfWorker() {
    if (window.pdfjsLib && !window.pdfjsLib.GlobalWorkerOptions.workerSrc) {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc =
        'https://cdn.jsdelivr.net/npm/pdfjs-dist@3.11.174/build/pdf.worker.min.js';
    }
  }

  /* ---------- רסטור עמוד PDF לתמונת canvas ---------- */
  async function pdfToCanvas(file) {
    ensurePdfWorker();
    const buf = await file.arrayBuffer();
    const pdf = await window.pdfjsLib.getDocument({ data: buf }).promise;
    const page = await pdf.getPage(1);
    // סקאלה גבוהה משפרת דיוק OCR
    const viewport = page.getViewport({ scale: 2.2 });
    const canvas = document.createElement('canvas');
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: ctx, viewport }).promise;
    return canvas;
  }

  /* ---------- הרצת OCR על קובץ (תמונה או PDF) ---------- */
  async function readFile(file, onProgress) {
    let image = file;
    if (file.type === 'application/pdf' || /\.pdf$/i.test(file.name)) {
      onProgress && onProgress({ stage: 'pdf', pct: 0, label: 'ממיר PDF…' });
      image = await pdfToCanvas(file);
    }
    // ניתן לארח את קבצי Tesseract מקומית (offline/פרטיות) ע"י הגדרת window.OCR_CONFIG
    const cfg = window.OCR_CONFIG || {};
    const workerOpts = {
      logger: m => {
        if (m.status === 'recognizing text' && onProgress) {
          onProgress({ stage: 'ocr', pct: Math.round(m.progress * 100), label: 'קורא טקסט…' });
        }
      },
    };
    if (cfg.workerPath) workerOpts.workerPath = cfg.workerPath;
    if (cfg.corePath) workerOpts.corePath = cfg.corePath;
    if (cfg.langPath) workerOpts.langPath = cfg.langPath;
    const worker = await window.Tesseract.createWorker('heb+eng', 1, workerOpts);
    try {
      const { data } = await worker.recognize(image);
      return data.text || '';
    } finally {
      await worker.terminate();
    }
  }

  /* ---------- ניקוי טקסט ---------- */
  function clean(t) {
    return t.replace(/[‎‏‪-‮]/g, '').replace(/ /g, ' ');
  }

  /* ---------- נרמול מחרוזת מספר לערך ---------- */
  function toNumber(raw) {
    let s = raw.replace(/\s/g, '');
    const hasDot = s.includes('.'), hasComma = s.includes(',');
    if (hasDot && hasComma) {
      // הפריד האחרון הוא העשרוני
      if (s.lastIndexOf('.') > s.lastIndexOf(',')) s = s.replace(/,/g, '');
      else s = s.replace(/\./g, '').replace(',', '.');
    } else if (hasComma) {
      // פסיק בודד עם 2 ספרות אחריו = עשרוני, אחרת מפריד אלפים
      s = /,\d{2}$/.test(s) ? s.replace(',', '.') : s.replace(/,/g, '');
    }
    const n = parseFloat(s);
    return isNaN(n) ? null : n;
  }

  /* ---------- חילוץ סכום ---------- */
  const TOTAL_KEYS = ['סה"כ', 'סה״כ', 'סהכ', 'לתשלום', 'סך הכל', 'סך הכול', 'סכום כולל',
    'סכום לתשלום', 'total', 'grand total', 'amount due', 'כולל מע"מ', 'כולל מעמ'];
  const NUM_RE = /\d[\d,.]*\d|\d/g;

  function extractAmount(text) {
    const lines = text.split('\n');
    let best = null;
    // 1) שורות עם מילות מפתח של "לתשלום/סה"כ"
    for (const line of lines) {
      const low = line.toLowerCase();
      if (TOTAL_KEYS.some(k => low.includes(k.toLowerCase()))) {
        const nums = (line.match(NUM_RE) || []).map(toNumber).filter(n => n != null && n > 0);
        for (const n of nums) if (best == null || n > best) best = n;
      }
    }
    if (best != null) return best;
    // 2) גיבוי: המספר הגדול ביותר שנראה כמו סכום כסף (עם עשרוני או ליד ₪)
    const all = [];
    for (const line of lines) {
      const near = /₪|ש"ח|ש״ח|שח|nis|ils/i.test(line);
      for (const m of (line.match(NUM_RE) || [])) {
        const n = toNumber(m);
        if (n != null && n > 0 && (near || /[.,]\d{2}\b/.test(m))) all.push(n);
      }
    }
    return all.length ? Math.max(...all) : null;
  }

  /* ---------- חילוץ תאריך ---------- */
  function extractDate(text) {
    const m = text.match(/(\d{1,2})[.\/-](\d{1,2})[.\/-](\d{2,4})/);
    if (!m) return null;
    let [, d, mo, y] = m;
    d = +d; mo = +mo; y = +y;
    if (y < 100) y += 2000;
    if (d > 31 || mo > 12 || mo < 1 || d < 1) return null;
    const iso = `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
    return iso;
  }

  /* ---------- חילוץ מספר חשבונית ---------- */
  function extractInvoiceNum(text) {
    const patterns = [
      /חשבונית\s*מס['׳"]?\s*[:.#]?\s*(\d{2,})/,
      /חשבונית\s*[:.#]?\s*(\d{2,})/,
      /מס['׳]?\s*חשבונית\s*[:.#]?\s*(\d{2,})/,
      /invoice\s*(?:no\.?|number|#)?\s*[:.#]?\s*(\d{2,})/i,
      /(?:מספר|מס['׳]?)\s*[:.#]?\s*(\d{4,})/,
    ];
    for (const re of patterns) {
      const m = text.match(re);
      if (m) return m[1];
    }
    return null;
  }

  /* ---------- ניחוש ספק ---------- */
  function extractSupplier(text) {
    const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
    const skip = /חשבונית|קבלה|תאריך|מספר|סה"כ|לתשלום|עוסק|ח\.פ|ע\.מ|invoice|receipt|date|total|www\.|@/i;
    for (const line of lines.slice(0, 8)) {
      const hebLetters = (line.match(/[א-ת]/g) || []).length;
      if (hebLetters >= 2 && line.length >= 3 && line.length <= 40 &&
          !skip.test(line) && !/^\d/.test(line)) {
        return line;
      }
    }
    return '';
  }

  /* ---------- ניחוש קטגוריה לפי מילות מפתח ---------- */
  const CAT_KEYWORDS = [
    ['vehicle',      ['דלק', 'סונול', 'פז', 'דור אלון', 'תחנת דלק', 'פנגו', 'pango', 'סלופארק', 'cellopark', 'חניון', 'רכב', 'טסט', 'צמיגים', 'מוסך']],
    ['phone',        ['סלולר', 'סלקום', 'cellcom', 'פרטנר', 'partner', 'פלאפון', 'pelephone', 'hot mobile', 'גולן', '019', 'רמי לוי תקשורת']],
    ['internet',     ['בזק', 'bezeq', 'אינטרנט', 'נטויזן', "נטוויז'ן", 'triple', 'hot ', 'yes ', 'סיבים']],
    ['utilities',    ['חשמל', 'חברת החשמל', 'מים', 'תאגיד', 'ארנונה', 'עיריית', 'מועצה']],
    ['office_rent',  ['שכירות', 'שכ"ד', 'דמי שכירות', 'שכר דירה']],
    ['prof_services',['רואה חשבון', 'רואי חשבון', 'רו"ח', 'עו"ד', 'עורך דין', 'יועץ', 'ראיית חשבון', 'ייעוץ', 'הנהלת חשבונות', 'שכר טרחה', 'שכ"ט']],
    ['advertising',  ['פרסום', 'קידום', 'google ads', 'facebook', 'meta', 'שיווק', 'קמפיין']],
    ['software',     ['מנוי', 'subscription', 'adobe', 'microsoft', 'google', 'saas', 'תוכנה', 'רישיון', 'domain', 'אחסון', 'hosting']],
    ['insurance',    ['ביטוח', 'הראל', 'כלל', 'מגדל', 'מנורה', 'הפניקס', 'ayalon']],
    ['bank_fees',    ['עמלה', 'עמלות', 'בנק', 'סליקה', 'עמלת', 'ביט', 'paybox']],
    ['post',         ['דואר', 'שליח', 'משלוח', 'ups', 'fedex', 'דואר ישראל']],
    ['refreshments', ['כיבוד', 'קפה', 'מסעדה', 'קפיטריה', 'ארוחה']],
    ['supplies',     ['ציוד משרדי', 'נייר', 'טונר', 'מחסנית', 'כלי כתיבה', 'office depot']],
  ];

  function guessCategory(text) {
    const low = text.toLowerCase();
    for (const [cat, kws] of CAT_KEYWORDS) {
      if (kws.some(k => low.includes(k.toLowerCase()))) return cat;
    }
    return null;
  }

  /* ---------- פרסור מלא ---------- */
  function parseInvoice(rawText) {
    const text = clean(rawText);
    return {
      amount: extractAmount(text),
      date: extractDate(text),
      invoiceNum: extractInvoiceNum(text),
      supplier: extractSupplier(text),
      category: guessCategory(text),
      rawText: text,
    };
  }

  return { readFile, parseInvoice, _test: { extractAmount, extractDate, extractInvoiceNum, extractSupplier, guessCategory, toNumber } };
})();

if (typeof module !== 'undefined') module.exports = OCR;
