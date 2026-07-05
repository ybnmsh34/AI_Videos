/* ============================================================
   מעקב חשבוניות — עוסק פטור
   אפליקציית PWA לניהול חשבוניות וסיווג להוצאות מוכרות למס.
   כל הנתונים נשמרים מקומית בדפדפן (localStorage).
   ============================================================ */

'use strict';

/* ---------- קטגוריות ברירת מחדל + אחוזי הכרה משוערים ----------
   אחוז ההכרה = כמה מההוצאה מוכר לצורך מס הכנסה.
   הערכים הם הערכה נפוצה בלבד ואינם ייעוץ מס. */
const DEFAULT_CATEGORIES = [
  { id: 'office_rent',   name: 'שכירות משרד',                 pct: 100 },
  { id: 'utilities',     name: 'חשמל, מים, ארנונה (עסק)',      pct: 100 },
  { id: 'phone',         name: 'טלפון נייד',                   pct: 50  },
  { id: 'internet',      name: 'אינטרנט ותקשורת',              pct: 50  },
  { id: 'vehicle',       name: 'רכב, דלק ואחזקה',              pct: 45  },
  { id: 'travel',        name: 'נסיעות ותחבורה ציבורית',       pct: 100 },
  { id: 'refreshments',  name: 'כיבוד במקום העסק',             pct: 80  },
  { id: 'prof_services', name: 'שירותים מקצועיים (רו"ח/עו"ד)', pct: 100 },
  { id: 'advertising',   name: 'פרסום ושיווק',                 pct: 100 },
  { id: 'software',      name: 'תוכנה ומנויים דיגיטליים',      pct: 100 },
  { id: 'literature',    name: 'ספרות מקצועית ומנויים',        pct: 100 },
  { id: 'training',      name: 'השתלמויות והדרכות',            pct: 100 },
  { id: 'insurance',     name: 'ביטוחים עסקיים',               pct: 100 },
  { id: 'bank_fees',     name: 'עמלות בנק וסליקה',             pct: 100 },
  { id: 'supplies',      name: 'ציוד מתכלה וחומרים',           pct: 100 },
  { id: 'equipment',     name: 'ריהוט וציוד משרדי',            pct: 100 },
  { id: 'post',          name: 'דואר ומשלוחים',               pct: 100 },
  { id: 'gifts',         name: 'מתנות ללקוחות',                pct: 100 },
  { id: 'other',         name: 'אחר',                          pct: 100 },
];

const STORE_KEY = 'op_invoices_v1';
const CAT_KEY   = 'op_categories_v1';
const CFG_KEY   = 'op_config_v1';

/* ---------- מצב ---------- */
let state = {
  transactions: load(STORE_KEY, []),
  categories:   load(CAT_KEY, null) || DEFAULT_CATEGORIES.map(c => ({ ...c })),
  config:       load(CFG_KEY, null) || { ceiling: 120000 },
  view:         'dashboard',
  year:         new Date().getFullYear(),
  filter:       'all',
  search:       '',
  modalType:    'expense',
};

/* ---------- כלי עזר ---------- */
function load(key, fallback) {
  try { const v = localStorage.getItem(key); return v ? JSON.parse(v) : fallback; }
  catch { return fallback; }
}
function save() {
  localStorage.setItem(STORE_KEY, JSON.stringify(state.transactions));
  localStorage.setItem(CAT_KEY, JSON.stringify(state.categories));
  localStorage.setItem(CFG_KEY, JSON.stringify(state.config));
}
function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
function $(sel) { return document.querySelector(sel); }
function fmt(n) {
  return '₪' + Math.round(n).toLocaleString('he-IL');
}
function fmtDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  return d.toLocaleDateString('he-IL', { day: '2-digit', month: '2-digit', year: '2-digit' });
}
function catName(id) {
  const c = state.categories.find(c => c.id === id);
  return c ? c.name : 'אחר';
}
function catPct(id) {
  const c = state.categories.find(c => c.id === id);
  return c ? c.pct : 100;
}
function toast(msg) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add('hidden'), 2200);
}

/* ---------- נתונים מחושבים ---------- */
function yearTx() {
  return state.transactions.filter(t => new Date(t.date).getFullYear() === state.year);
}
function recognizedAmount(t) {
  if (t.type !== 'expense') return 0;
  const pct = (t.recognition != null) ? t.recognition : catPct(t.category);
  return t.amount * pct / 100;
}
function totals() {
  const tx = yearTx();
  let income = 0, expense = 0, recognized = 0;
  for (const t of tx) {
    if (t.type === 'income') income += t.amount;
    else { expense += t.amount; recognized += recognizedAmount(t); }
  }
  return { income, expense, recognized, profit: Math.max(0, income - recognized) };
}

/* ============================================================
   רינדור
   ============================================================ */
function render() {
  renderYearOptions();
  renderDashboard();
  renderTransactions();
  renderReports();
  renderSettings();
}

function renderYearOptions() {
  const years = new Set(state.transactions.map(t => new Date(t.date).getFullYear()));
  years.add(new Date().getFullYear());
  years.add(state.year);
  const sorted = [...years].sort((a, b) => b - a);
  const sel = $('#yearSelect');
  sel.innerHTML = sorted.map(y => `<option value="${y}" ${y === state.year ? 'selected' : ''}>${y}</option>`).join('');
}

function renderDashboard() {
  const t = totals();
  $('#sumIncome').textContent = fmt(t.income);
  $('#sumExpense').textContent = fmt(t.expense);
  $('#sumRecognized').textContent = fmt(t.recognized);
  $('#sumProfit').textContent = fmt(t.profit);

  // תקרת מחזור
  const ceiling = state.config.ceiling || 120000;
  const pct = Math.min(100, (t.income / ceiling) * 100);
  $('#ceilingFill').style.width = pct + '%';
  $('#ceilingUsed').textContent = fmt(t.income);
  $('#ceilingMax').textContent = '/ ' + fmt(ceiling);

  const fill = $('#ceilingFill');
  const status = $('#ceilingStatus');
  fill.classList.remove('warn', 'over');
  status.classList.remove('ok', 'warn', 'over');
  if (t.income >= ceiling) {
    fill.classList.add('over'); status.classList.add('over');
    status.textContent = 'חריגה מהתקרה!';
  } else if (pct >= 80) {
    fill.classList.add('warn'); status.classList.add('warn');
    status.textContent = 'מתקרב לתקרה';
  } else {
    status.classList.add('ok');
    status.textContent = Math.round(pct) + '% מנוצל';
  }

  // תנועות אחרונות
  const recent = [...yearTx()].sort((a, b) => b.date.localeCompare(a.date) || b.createdAt - a.createdAt).slice(0, 5);
  $('#recentList').innerHTML = recent.length
    ? recent.map(txItemHTML).join('')
    : `<div class="tx-empty">אין תנועות בשנה זו.<br>לחץ על + כדי להוסיף.</div>`;
}

function txItemHTML(t) {
  const sign = t.type === 'income' ? '+' : '−';
  const sub = t.type === 'expense'
    ? `${catName(t.category)} · ${fmtDate(t.date)}`
    : `${fmtDate(t.date)}${t.invoiceNum ? ' · #' + t.invoiceNum : ''}`;
  return `
    <div class="tx-item" data-id="${t.id}">
      <div class="tx-icon ${t.type}">${t.type === 'income' ? '↓' : '↑'}</div>
      <div class="tx-body">
        <div class="tx-supplier">${escapeHtml(t.supplier || (t.type === 'income' ? 'הכנסה' : 'הוצאה'))}</div>
        <div class="tx-meta">${escapeHtml(sub)}</div>
      </div>
      <div class="tx-amount ${t.type}">${sign}${fmt(t.amount)}</div>
    </div>`;
}

function renderTransactions() {
  let tx = yearTx();
  if (state.filter !== 'all') tx = tx.filter(t => t.type === state.filter);
  if (state.search) {
    const q = state.search.toLowerCase();
    tx = tx.filter(t =>
      (t.supplier || '').toLowerCase().includes(q) ||
      (t.notes || '').toLowerCase().includes(q) ||
      (t.invoiceNum || '').toLowerCase().includes(q) ||
      catName(t.category).toLowerCase().includes(q));
  }
  tx.sort((a, b) => b.date.localeCompare(a.date) || b.createdAt - a.createdAt);
  $('#txList').innerHTML = tx.length
    ? tx.map(txItemHTML).join('')
    : `<div class="tx-empty">לא נמצאו תנועות.</div>`;
}

function renderReports() {
  const t = totals();
  $('#reportSummary').innerHTML = `
    <div class="report-row"><div class="r-label">הכנסות</div><div class="r-value" style="color:var(--green)">${fmt(t.income)}</div></div>
    <div class="report-row"><div class="r-label">הוצאות (סה"כ)</div><div class="r-value" style="color:var(--red)">${fmt(t.expense)}</div></div>
    <div class="report-row"><div class="r-label">הוצאות מוכרות</div><div class="r-value" style="color:var(--teal)">${fmt(t.recognized)}</div></div>
    <div class="report-row"><div class="r-label">רווח חייב במס (משוער)</div><div class="r-value" style="color:#6366f1">${fmt(t.profit)}</div></div>`;

  // פילוח לפי קטגוריה (מוכר)
  const byCat = {};
  for (const tx of yearTx().filter(t => t.type === 'expense')) {
    if (!byCat[tx.category]) byCat[tx.category] = { full: 0, rec: 0 };
    byCat[tx.category].full += tx.amount;
    byCat[tx.category].rec += recognizedAmount(tx);
  }
  const rows = Object.entries(byCat).sort((a, b) => b[1].rec - a[1].rec);
  const maxRec = rows.length ? Math.max(...rows.map(r => r[1].rec)) : 1;
  $('#categoryBreakdown').innerHTML = rows.length
    ? rows.map(([cid, v]) => `
        <div class="cat-row">
          <div class="cat-top">
            <span class="cat-name">${escapeHtml(catName(cid))}</span>
            <span class="cat-val">${fmt(v.rec)}</span>
          </div>
          <div class="cat-bar"><div style="width:${(v.rec / maxRec) * 100}%"></div></div>
          <div class="cat-sub">מתוך ${fmt(v.full)} · הכרה ${Math.round((v.rec / (v.full || 1)) * 100)}%</div>
        </div>`).join('')
    : `<div class="tx-empty">אין הוצאות בשנה זו.</div>`;

  // סיכום חודשי
  const months = Array.from({ length: 12 }, () => ({ inc: 0, exp: 0 }));
  for (const tx of yearTx()) {
    const m = new Date(tx.date).getMonth();
    if (tx.type === 'income') months[m].inc += tx.amount;
    else months[m].exp += tx.amount;
  }
  const monthNames = ['ינו', 'פבר', 'מרץ', 'אפר', 'מאי', 'יונ', 'יול', 'אוג', 'ספט', 'אוק', 'נוב', 'דצמ'];
  let html = `<div class="month-row head"><span>חודש</span><span>הכנסות</span><span>הוצאות</span></div>`;
  html += months.map((m, i) =>
    (m.inc || m.exp)
      ? `<div class="month-row"><span>${monthNames[i]}</span><span class="m-inc">${fmt(m.inc)}</span><span class="m-exp">${fmt(m.exp)}</span></div>`
      : '').join('');
  $('#monthlyBreakdown').innerHTML = html;
}

function renderSettings() {
  $('#ceilingInput').value = state.config.ceiling || 120000;
  $('#catSettings').innerHTML = state.categories.map(c => `
    <div class="cat-setting-row">
      <span class="cs-name">${escapeHtml(c.name)}</span>
      <span class="cs-pct">
        <input type="number" min="0" max="100" value="${c.pct}" data-cat="${c.id}" />
        <span>%</span>
      </span>
    </div>`).join('');
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
}

/* ============================================================
   ניווט בין מסכים
   ============================================================ */
const VIEW_TITLES = { dashboard: 'סיכום שנתי', transactions: 'תנועות', reports: 'דוחות', settings: 'הגדרות' };
function switchView(v) {
  state.view = v;
  document.querySelectorAll('.view').forEach(el => el.classList.add('hidden'));
  $('#view-' + v).classList.remove('hidden');
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.toggle('active', b.dataset.view === v));
  $('#viewTitle').textContent = VIEW_TITLES[v];
  $('#main').scrollTop = 0;
  window.scrollTo(0, 0);
}

/* ============================================================
   מודל הוספה / עריכה
   ============================================================ */
function openModal(tx) {
  const modal = $('#txModal');
  const form = $('#txForm');
  form.reset();
  populateCategorySelect();

  if (tx) {
    $('#modalTitle').textContent = 'עריכת תנועה';
    state.modalType = tx.type;
    $('#txId').value = tx.id;
    $('#txAmount').value = tx.amount;
    $('#txSupplier').value = tx.supplier || '';
    $('#txCategory').value = tx.category || 'other';
    $('#txRecognition').value = (tx.recognition != null) ? tx.recognition : catPct(tx.category);
    $('#txDate').value = tx.date;
    $('#txInvoiceNum').value = tx.invoiceNum || '';
    $('#txNotes').value = tx.notes || '';
    $('#deleteTxBtn').classList.remove('hidden');
  } else {
    $('#modalTitle').textContent = 'תנועה חדשה';
    state.modalType = 'expense';
    $('#txId').value = '';
    $('#txDate').value = new Date().toISOString().slice(0, 10);
    $('#txRecognition').value = catPct($('#txCategory').value);
    $('#deleteTxBtn').classList.add('hidden');
  }
  applyModalType();
  updateRecognizedPreview();
  modal.classList.remove('hidden');
}
function closeModal() { $('#txModal').classList.add('hidden'); }

function populateCategorySelect() {
  $('#txCategory').innerHTML = state.categories.map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
}

function applyModalType() {
  const isExpense = state.modalType === 'expense';
  document.querySelectorAll('.type-btn').forEach(b => b.classList.toggle('active', b.dataset.type === state.modalType));
  $('#categoryField').style.display = isExpense ? '' : 'none';
  $('#recognitionRow').style.display = isExpense ? '' : 'none';
  $('#supplierLabel').textContent = isExpense ? 'שם ספק' : 'שם לקוח / מקור';
}

function updateRecognizedPreview() {
  const amount = parseFloat($('#txAmount').value) || 0;
  const pct = parseFloat($('#txRecognition').value) || 0;
  $('#recognizedPreview').textContent = fmt(amount * pct / 100);
}

function saveTx(e) {
  e.preventDefault();
  const amount = parseFloat($('#txAmount').value);
  if (!amount || amount <= 0) { toast('יש להזין סכום תקין'); return; }
  const id = $('#txId').value;
  const data = {
    id: id || uid(),
    type: state.modalType,
    amount,
    supplier: $('#txSupplier').value.trim(),
    date: $('#txDate').value,
    invoiceNum: $('#txInvoiceNum').value.trim(),
    notes: $('#txNotes').value.trim(),
    createdAt: id ? (state.transactions.find(t => t.id === id)?.createdAt || Date.now()) : Date.now(),
  };
  if (state.modalType === 'expense') {
    data.category = $('#txCategory').value;
    data.recognition = parseFloat($('#txRecognition').value);
    if (isNaN(data.recognition)) data.recognition = catPct(data.category);
  }
  if (id) {
    const i = state.transactions.findIndex(t => t.id === id);
    state.transactions[i] = data;
    toast('התנועה עודכנה');
  } else {
    state.transactions.push(data);
    toast('נשמר בהצלחה');
  }
  save();
  render();
  closeModal();
}

function deleteTx() {
  const id = $('#txId').value;
  if (!id) return;
  if (!confirm('למחוק את התנועה?')) return;
  state.transactions = state.transactions.filter(t => t.id !== id);
  save();
  render();
  closeModal();
  toast('התנועה נמחקה');
}

/* ============================================================
   ייצוא / ייבוא
   ============================================================ */
function exportCsv() {
  const tx = [...yearTx()].sort((a, b) => a.date.localeCompare(b.date));
  if (!tx.length) { toast('אין נתונים לייצוא'); return; }
  const header = ['תאריך', 'סוג', 'ספק/לקוח', 'קטגוריה', 'סכום', 'אחוז הכרה', 'סכום מוכר', 'מס חשבונית', 'הערות'];
  const rows = tx.map(t => [
    t.date,
    t.type === 'income' ? 'הכנסה' : 'הוצאה',
    t.supplier || '',
    t.type === 'expense' ? catName(t.category) : '',
    t.amount,
    t.type === 'expense' ? ((t.recognition != null) ? t.recognition : catPct(t.category)) : '',
    t.type === 'expense' ? Math.round(recognizedAmount(t)) : '',
    t.invoiceNum || '',
    (t.notes || '').replace(/\n/g, ' '),
  ]);
  const csv = [header, ...rows].map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\r\n');
  downloadFile('﻿' + csv, `invoices-${state.year}.csv`, 'text/csv;charset=utf-8');
  toast('הקובץ יוצא');
}

function exportBackup() {
  const data = JSON.stringify({ transactions: state.transactions, categories: state.categories, config: state.config }, null, 2);
  downloadFile(data, `backup-${new Date().toISOString().slice(0, 10)}.json`, 'application/json');
  toast('גיבוי נוצר');
}

function importBackup(file) {
  const reader = new FileReader();
  reader.onload = () => {
    try {
      const data = JSON.parse(reader.result);
      if (!Array.isArray(data.transactions)) throw new Error('bad');
      if (!confirm('ייבוא יחליף את כל הנתונים הקיימים. להמשיך?')) return;
      state.transactions = data.transactions;
      if (Array.isArray(data.categories)) state.categories = data.categories;
      if (data.config) state.config = data.config;
      save();
      render();
      toast('הגיבוי יובא בהצלחה');
    } catch { toast('קובץ לא תקין'); }
  };
  reader.readAsText(file);
}

function downloadFile(content, name, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ============================================================
   אירועים
   ============================================================ */
function bindEvents() {
  // ניווט
  document.querySelectorAll('.nav-btn').forEach(b => b.addEventListener('click', () => switchView(b.dataset.view)));

  // בחירת שנה
  $('#yearSelect').addEventListener('change', e => { state.year = +e.target.value; render(); });

  // FAB
  $('#fabAdd').addEventListener('click', () => openModal(null));

  // מודל
  $('#modalClose').addEventListener('click', closeModal);
  $('#txModal').addEventListener('click', e => { if (e.target.id === 'txModal') closeModal(); });
  $('#txForm').addEventListener('submit', saveTx);
  $('#deleteTxBtn').addEventListener('click', deleteTx);
  document.querySelectorAll('.type-btn').forEach(b => b.addEventListener('click', () => {
    state.modalType = b.dataset.type; applyModalType(); updateRecognizedPreview();
  }));
  $('#txCategory').addEventListener('change', () => {
    $('#txRecognition').value = catPct($('#txCategory').value);
    updateRecognizedPreview();
  });
  $('#txAmount').addEventListener('input', updateRecognizedPreview);
  $('#txRecognition').addEventListener('input', updateRecognizedPreview);

  // לחיצה על תנועה -> עריכה
  document.addEventListener('click', e => {
    const item = e.target.closest('.tx-item');
    if (item) {
      const tx = state.transactions.find(t => t.id === item.dataset.id);
      if (tx) openModal(tx);
    }
  });

  // סינון וחיפוש
  document.querySelectorAll('.chip').forEach(c => c.addEventListener('click', () => {
    document.querySelectorAll('.chip').forEach(x => x.classList.remove('active'));
    c.classList.add('active');
    state.filter = c.dataset.filter;
    renderTransactions();
  }));
  $('#searchInput').addEventListener('input', e => { state.search = e.target.value.trim(); renderTransactions(); });

  // דוחות
  $('#exportCsvBtn').addEventListener('click', exportCsv);

  // הגדרות
  $('#ceilingInput').addEventListener('change', e => {
    state.config.ceiling = parseFloat(e.target.value) || 120000;
    save(); renderDashboard();
  });
  $('#catSettings').addEventListener('change', e => {
    if (e.target.matches('input[data-cat]')) {
      const c = state.categories.find(c => c.id === e.target.dataset.cat);
      if (c) { c.pct = Math.max(0, Math.min(100, parseFloat(e.target.value) || 0)); save(); render(); }
    }
  });
  $('#backupBtn').addEventListener('click', exportBackup);
  $('#restoreBtn').addEventListener('click', () => $('#restoreFile').click());
  $('#restoreFile').addEventListener('change', e => { if (e.target.files[0]) importBackup(e.target.files[0]); });
  $('#resetBtn').addEventListener('click', () => {
    if (confirm('פעולה זו תמחק את כל הנתונים לצמיתות. להמשיך?')) {
      state.transactions = [];
      state.categories = DEFAULT_CATEGORIES.map(c => ({ ...c }));
      state.config = { ceiling: 120000 };
      save(); render(); toast('כל הנתונים נמחקו');
    }
  });
}

/* ============================================================
   אתחול
   ============================================================ */
function init() {
  bindEvents();
  switchView('dashboard');
  render();
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
}
document.addEventListener('DOMContentLoaded', init);
