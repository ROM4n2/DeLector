/* DeLector – frontend logic */
'use strict';

let currentArticle = null;
let selectedToken   = null;
let selectedSent    = null;
let grammarData     = null;

// ── German Audio TTS ─────────────────────────────────────────────────────────
function playGermanAudio(text, rate = 0.88) {
  if (!('speechSynthesis' in window) || !text) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text.trim());
  utterance.lang = 'de-DE';
  utterance.rate = rate; // 略慢于正常语速，便于初学与备考辨音
  
  const voices = window.speechSynthesis.getVoices();
  const deVoice = voices.find(v => v.lang.startsWith('de') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('German') || v.name.includes('Hedda') || v.name.includes('Stefan')));
  if (deVoice) utterance.voice = deVoice;
  
  window.speechSynthesis.speak(utterance);
}

// ── View router ──────────────────────────────────────────────────────────────
function show(view) {
  document.querySelectorAll('.view').forEach(el => el.classList.remove('active'));
  document.getElementById('view-' + view).classList.add('active');
  closeDrawer();
  if (view === 'home')  loadArticles();
  if (view === 'cards') loadCards();
}

// ── Articles ─────────────────────────────────────────────────────────────────
async function loadArticles() {
  const el = document.getElementById('article-list');
  el.innerHTML = '<div class="empty-state">加载中…</div>';
  const data = await api('/api/articles');
  if (!data.length) {
    el.innerHTML = '<div class="empty-state">暂无文稿，点击上方按钮导入德语文章</div>';
    return;
  }
  el.innerHTML = data.map(a => `
    <div class="article-row" onclick="openReader(${a.id})">
      <div>
        <div class="article-row-title">${esc(a.title)}</div>
        <div class="article-row-meta">${a.created_at} · ${a.char_count} 字符</div>
      </div>
      <span class="article-row-arrow">→</span>
    </div>`).join('');
}

async function openReader(id) {
  currentArticle = await api('/api/articles/' + id);
  document.getElementById('reader-title').textContent = currentArticle.title;
  const content = document.getElementById('reader-content');
  content.innerHTML = currentArticle.sentences.map(sent => {
    const tokens = sent.tokens.map(t => {
      if (t.is_space) return ' ';
      if (t.is_punct) return `<span>${esc(t.text)}</span>`;
      const lvl = t.cefr_level || '';
      return `<span id="tok-${t.id}" class="tok ${lvl}" onclick="inspect(${t.id},${sent.id})">${esc(t.text)}</span>`;
    }).join('');
    return `<p>${tokens}</p>`;
  }).join('');
  show('reader');
}

// ── Token inspection ─────────────────────────────────────────────────────────
function inspect(tokenId, sentId) {
  document.querySelectorAll('.tok.sel').forEach(el => el.classList.remove('sel'));
  const el = document.getElementById('tok-' + tokenId);
  if (el) el.classList.add('sel');

  const sent  = currentArticle.sentences.find(s => s.id === sentId);
  const token = sent.tokens.find(t => t.id === tokenId);
  selectedToken = token;
  selectedSent  = sent;
  grammarData   = null;

  const lvl = token.cefr_level || 'A1';
  document.getElementById('d-word').textContent = token.text;
  document.getElementById('d-cefr').textContent = 'CEFR ' + lvl;
  document.getElementById('d-cefr').className = 'cefr-badge badge-' + lvl;

  let genderHtml = '';
  if (token.gender === 'Masc') genderHtml = '<span class="gender-tag gender-der">der 阳性</span>';
  else if (token.gender === 'Fem') genderHtml = '<span class="gender-tag gender-die">die 阴性</span>';
  else if (token.gender === 'Neut') genderHtml = '<span class="gender-tag gender-das">das 中性</span>';

  document.getElementById('d-meta').innerHTML =
    `原型: <strong>${esc(token.lemma)}</strong> · 词性: ${esc(token.pos)} ${genderHtml}` +
    (token.case ? ` · ${esc(token.case)}` : '');
  document.getElementById('d-def').value = '';
  document.getElementById('d-sent').textContent = sent.text;
  document.getElementById('save-vocab-btn').textContent = '+ 加入 Anki 词汇卡';
  document.getElementById('grammar-result').classList.add('hidden');
  openDrawer();
}

// ── Drawer ───────────────────────────────────────────────────────────────────
function openDrawer()  { document.getElementById('drawer').classList.add('open'); }
function closeDrawer() {
  document.getElementById('drawer').classList.remove('open');
  document.querySelectorAll('.tok.sel').forEach(el => el.classList.remove('sel'));
}

// ── Grammar AI ───────────────────────────────────────────────────────────────
async function analyzeGrammar() {
  const btn = document.getElementById('analyze-btn');
  btn.textContent = '分析中…';
  btn.disabled = true;
  try {
    grammarData = await api('/api/lookup/grammar', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ sentence: selectedSent.text, target_phrase: selectedToken.text })
    });
    const lvl = grammarData.cefr_level || 'B1';
    document.getElementById('g-name').textContent    = grammarData.grammar_name;
    document.getElementById('g-formula').textContent = grammarData.rule_formula || '';
    document.getElementById('g-formula').classList.toggle('hidden', !grammarData.rule_formula);
    document.getElementById('g-exp').textContent     = grammarData.explanation_zh;
    document.getElementById('g-badge').textContent   = 'Goethe ' + lvl;
    document.getElementById('g-badge').className     = 'cefr-badge grammar-cefr-badge badge-' + lvl;
    if (!document.getElementById('d-def').value && grammarData.collocations?.length) {
      document.getElementById('d-def').value = grammarData.collocations[0];
    }
    document.getElementById('grammar-result').classList.remove('hidden');
  } catch {
    alert('语法解析失败，请检查 API Key');
  } finally {
    btn.textContent = 'AI 深度剖析';
    btn.disabled = false;
  }
}

// ── Save ─────────────────────────────────────────────────────────────────────
async function saveVocab() {
  const def = document.getElementById('d-def').value.trim();
  if (!def) { alert('请输入中文释义'); return; }
  await api('/api/cards/vocab', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      article_id: currentArticle.id,
      word: selectedToken.text, lemma: selectedToken.lemma,
      pos: selectedToken.pos,   gender: selectedToken.gender,
      cefr_level: selectedToken.cefr_level || 'A1',
      definition_zh: def, sentence_context: selectedSent.text
    })
  });
  document.getElementById('save-vocab-btn').textContent = '✓ 已保存';
  refreshCount();
}

async function saveGrammar() {
  if (!grammarData) return;
  await api('/api/cards/grammar', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      article_id: currentArticle.id,
      sentence_context: selectedSent.text,
      grammar_name: grammarData.grammar_name,
      cefr_level: grammarData.cefr_level || 'B1',
      explanation_zh: grammarData.explanation_zh,
      rule_formula: grammarData.rule_formula
    })
  });
  document.getElementById('save-grammar-btn').textContent = '✓ 已加入语法卡';
  refreshCount();
}

// ── Cards view ────────────────────────────────────────────────────────────────
async function loadCards() {
  const { vocab_cards: vc, grammar_cards: gc } = await api('/api/cards');
  document.getElementById('cards-container').innerHTML = `
    <div class="section-label" style="margin-bottom:0.875rem;">
      <span class="section-title">词汇卡 · VOCABULARY (${vc.length})</span>
    </div>
    <div class="card-grid">${vc.map(c => `
      <div class="memo-card">
        <div class="memo-card-head">
          <span class="memo-word">${esc(c.word)}</span>
          <span class="cefr-badge badge-${c.cefr_level}">${c.cefr_level}</span>
        </div>
        <div class="memo-def">${esc(c.definition_zh)}</div>
        <div class="memo-meta">${esc(c.lemma)} · ${esc(c.pos)}${c.gender ? ' · ' + esc(c.gender) : ''}</div>
        <div class="memo-sent">${esc(c.sentence_context)}</div>
      </div>`).join('')}</div>

    <div class="section-label" style="margin-bottom:0.875rem;">
      <span class="section-title">歌德语法考点卡 · GRAMMAR (${gc.length})</span>
    </div>
    ${gc.map(c => `
      <div class="grammar-memo-card">
        <div class="grammar-memo-head">
          <span class="grammar-memo-name">${esc(c.grammar_name)}</span>
          <span class="cefr-badge badge-${c.cefr_level}">Goethe ${c.cefr_level}</span>
        </div>
        ${c.rule_formula ? `<div class="grammar-memo-formula">${esc(c.rule_formula)}</div>` : ''}
        <div class="grammar-memo-exp">${esc(c.explanation_zh)}</div>
        <div class="memo-sent">${esc(c.sentence_context)}</div>
      </div>`).join('')}
  `;
}

// ── Import modal ──────────────────────────────────────────────────────────────
function openModal()  { document.getElementById('modal-overlay').classList.add('open'); }
function closeModal() { document.getElementById('modal-overlay').classList.remove('open'); }

async function submitImport() {
  const text  = document.getElementById('imp-text').value.trim();
  const title = document.getElementById('imp-title').value.trim() || '未命名文稿';
  if (!text) { alert('请输入德语文本'); return; }
  const btn = document.getElementById('import-btn');
  btn.textContent = '处理中…'; btn.disabled = true;
  try {
    const data = await api('/api/articles/ingest', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ title, raw_text: text })
    });
    closeModal();
    document.getElementById('imp-text').value  = '';
    document.getElementById('imp-title').value = '';
    openReader(data.article_id);
  } catch { alert('导入失败'); }
  finally { btn.textContent = '开始阅读'; btn.disabled = false; }
}

// ── Helpers ───────────────────────────────────────────────────────────────────
async function api(url, opts) {
  const r = await fetch(url, opts);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}
function esc(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
async function refreshCount() {
  const { vocab_cards: vc, grammar_cards: gc } = await api('/api/cards');
  document.getElementById('card-count').textContent = vc.length + gc.length;
}

// ── Multi-Token Phrase Selection ─────────────────────────────────────────────
document.getElementById('reader-content')?.addEventListener('mouseup', () => {
  const sel = window.getSelection();
  const text = sel ? sel.toString().trim() : '';
  if (text && text.includes(' ') && text.length > 2) {
    inspectPhrase(text);
  }
});

function inspectPhrase(phraseText) {
  if (!currentArticle) return;
  const matchedSent = currentArticle.sentences.find(s => s.text.includes(phraseText)) || currentArticle.sentences[0];
  selectedToken = { text: phraseText, lemma: phraseText, pos: 'PHRASE', cefr_level: 'B1', gender: '', case: '' };
  selectedSent = matchedSent;
  grammarData = null;

  document.getElementById('d-word').textContent = phraseText;
  document.getElementById('d-cefr').textContent = 'CEFR Phrase';
  document.getElementById('d-cefr').className = 'cefr-badge badge-B1';
  document.getElementById('d-meta').innerHTML = '固定搭配 / 短语短句';
  document.getElementById('d-def').value = '';
  document.getElementById('d-sent').textContent = matchedSent ? matchedSent.text : '';
  document.getElementById('grammar-result').classList.add('hidden');
  document.getElementById('save-vocab-btn').textContent = '+ 加入 Anki 短语卡';
  openDrawer();
}

// ── Global Keyboard Shortcuts ────────────────────────────────────────────────
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeDrawer();
    closeModal();
    return;
  }

  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    const drawer = document.getElementById('drawer');
    if (drawer.classList.contains('open')) {
      e.preventDefault();
      saveVocab();
      return;
    }
  }

  if (!['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
    if (e.key === 'j' || e.key === 'k') {
      const tokens = Array.from(document.querySelectorAll('.tok'));
      if (!tokens.length) return;
      const curIndex = tokens.findIndex(el => el.classList.contains('sel'));
      let nextIndex = 0;
      if (e.key === 'j') {
        nextIndex = curIndex < tokens.length - 1 ? curIndex + 1 : 0;
      } else {
        nextIndex = curIndex > 0 ? curIndex - 1 : tokens.length - 1;
      }
      tokens[nextIndex]?.click();
      tokens[nextIndex]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }
});

// ── Init ──────────────────────────────────────────────────────────────────────
loadArticles();
refreshCount();
