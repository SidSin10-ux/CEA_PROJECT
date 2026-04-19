/* static/fix_ui.js — Self-Healing Assistant UI (additive only) */
// BEGIN SELF-HEAL ADDITION
(function () {
  'use strict';

  const _sh = {
    enabled: false, healData: null, panelOpen: false,
    currentFix: null, currentFixIdx: 0, lastSource: '', lastLang: 'cpp',
  };

  const _css = `
    #sh-panel {
      position:fixed;top:50px;right:0;bottom:24px;width:420px;max-width:90vw;
      background:var(--surf,#f5f7f5);border-left:2px solid var(--accent,#009944);
      box-shadow:-4px 0 24px rgba(0,0,0,.13);display:flex;flex-direction:column;
      z-index:100;transform:translateX(100%);transition:transform .28s cubic-bezier(.4,0,.2,1);
      font-family:var(--sans,'Outfit',sans-serif);
    }
    #sh-panel.sh-open{transform:translateX(0);}
    #sh-header{
      padding:13px 16px 11px;background:linear-gradient(135deg,var(--accent,#009944),var(--accentd,#006628));
      color:#fff;display:flex;align-items:center;gap:10px;flex-shrink:0;
    }
    #sh-header-title{font-weight:700;font-size:14px;letter-spacing:.02em;flex:1;}
    #sh-close-btn{
      background:rgba(255,255,255,.18);border:none;color:#fff;border-radius:6px;
      width:26px;height:26px;cursor:pointer;font-size:16px;display:flex;
      align-items:center;justify-content:center;transition:background .15s;flex-shrink:0;padding:0;
    }
    #sh-close-btn:hover{background:rgba(255,255,255,.32);}
    #sh-body{flex:1;overflow-y:auto;padding:14px;}
    #sh-body::-webkit-scrollbar{width:5px;}
    #sh-body::-webkit-scrollbar-thumb{background:var(--bord2,#aac4aa);border-radius:3px;}
    #sh-nav{display:flex;align-items:center;gap:8px;margin-bottom:12px;}
    .sh-nav-btn{
      background:var(--surf2,#eef2ee);border:1px solid var(--bord,#c8d8c8);
      color:var(--txt,#1a2e1a);border-radius:6px;padding:4px 10px;cursor:pointer;
      font-size:13px;transition:background .15s;
    }
    .sh-nav-btn:hover:not(:disabled){background:var(--bord,#c8d8c8);}
    .sh-nav-btn:disabled{opacity:.4;cursor:not-allowed;}
    #sh-nav-label{font-size:12px;color:var(--txt3,#5a7a5a);flex:1;text-align:center;}
    .sh-card{background:#fff;border:1px solid var(--bord,#c8d8c8);border-radius:8px;margin-bottom:12px;overflow:hidden;}
    .sh-card-head{padding:10px 13px 8px;border-bottom:1px solid var(--bord,#c8d8c8);display:flex;align-items:center;gap:8px;}
    .sh-card-icon{font-size:16px;flex-shrink:0;}
    .sh-card-title{font-weight:700;font-size:13px;color:var(--txt,#1a2e1a);}
    .sh-conf-badge{margin-left:auto;font-size:10px;font-weight:600;padding:2px 7px;border-radius:8px;font-family:var(--mono,monospace);}
    .sh-conf-high{background:#e6f7ee;color:#006628;border:1px solid #a0d8b8;}
    .sh-conf-medium{background:#fff8e0;color:#7a5800;border:1px solid #e0c860;}
    .sh-conf-low{background:#f5f5f5;color:#5a5a5a;border:1px solid #d0d0d0;}
    .sh-card-body{padding:10px 13px 12px;}
    .sh-label{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--txt3,#5a7a5a);margin-bottom:4px;}
    .sh-explanation{font-size:13px;color:var(--txt,#1a2e1a);line-height:1.65;margin-bottom:10px;}
    .sh-fix-text{font-size:13px;color:var(--accent2,#007733);line-height:1.6;margin-bottom:10px;}
    .sh-code-block{
      background:#f4fff8;border:1px solid #b8e8cc;border-radius:6px;padding:10px 12px;
      margin:6px 0 10px;font-family:var(--mono,'JetBrains Mono',monospace);font-size:12px;
      line-height:1.7;overflow-x:auto;white-space:pre;color:#1a2e1a;
    }
    .sh-code-block .sh-del{background:rgba(255,61,61,.12);color:#cc2200;display:block;}
    .sh-code-block .sh-add{background:rgba(0,153,68,.12);color:#006628;display:block;}
    #sh-apply-btn{
      display:block;width:100%;padding:10px;
      background:linear-gradient(135deg,var(--green,#007a2e),#2ab870);
      color:#fff;border:none;border-radius:8px;font-family:var(--display,'Syne',sans-serif);
      font-size:13px;font-weight:700;cursor:pointer;letter-spacing:.04em;
      transition:all .18s;margin-top:4px;text-align:center;box-shadow:0 2px 10px rgba(0,153,68,.2);
    }
    #sh-apply-btn:hover{transform:translateY(-1px);box-shadow:0 4px 16px rgba(0,153,68,.3);}
    #sh-apply-btn:active{transform:none;}
    #sh-apply-btn:disabled{background:var(--surf3,#e4eae4);color:var(--txt3,#5a7a5a);cursor:not-allowed;transform:none;box-shadow:none;}
    #sh-applied-note{text-align:center;font-size:12px;color:var(--green,#007a2e);margin-top:6px;display:none;}
    #sh-trigger-btn{
      padding:7px 16px;background:linear-gradient(135deg,#7b3fe4,#5b21b6);color:#fff;
      border:none;border-radius:8px;font-family:var(--display,'Syne',sans-serif);
      font-size:12px;font-weight:700;cursor:pointer;display:none;align-items:center;
      gap:6px;transition:all .18s;white-space:nowrap;flex-shrink:0;
      box-shadow:0 2px 12px rgba(123,63,228,.25);letter-spacing:.03em;
    }
    #sh-trigger-btn:hover{transform:translateY(-1px);box-shadow:0 4px 18px rgba(123,63,228,.35);}
    #sh-trigger-btn:active{transform:none;}
    #sh-loading{display:none;flex-direction:column;align-items:center;justify-content:center;padding:40px 20px;gap:14px;color:var(--txt3,#5a7a5a);font-size:13px;}
    .sh-spinner{width:32px;height:32px;border:3px solid var(--bord,#c8d8c8);border-top-color:var(--accent,#009944);border-radius:50%;animation:sh-spin .8s linear infinite;}
    @keyframes sh-spin{to{transform:rotate(360deg);}}
    #sh-empty{display:none;text-align:center;padding:40px 20px;color:var(--txt3,#5a7a5a);font-size:13px;}
  `;

  function _injectStyles() {
    const s = document.createElement('style');
    s.id = 'sh-styles';
    s.textContent = _css;
    document.head.appendChild(s);
  }

  function _buildPanel() {
    const p = document.createElement('div');
    p.id = 'sh-panel';
    p.innerHTML = `
      <div id="sh-header">
        <span style="font-size:18px">🔧</span>
        <div id="sh-header-title">Self-Healing Assistant</div>
        <button id="sh-close-btn" title="Close">✕</button>
      </div>
      <div id="sh-loading"><div class="sh-spinner"></div><span>Analysing errors…</span></div>
      <div id="sh-empty">No suggestions yet.<br>Compile your code first.</div>
      <div id="sh-body" style="display:none;">
        <div id="sh-nav">
          <button class="sh-nav-btn" id="sh-prev-btn">◀</button>
          <div id="sh-nav-label">Error 1 of 1</div>
          <button class="sh-nav-btn" id="sh-next-btn">▶</button>
        </div>
        <div id="sh-content"></div>
      </div>`;
    document.body.appendChild(p);
    p.querySelector('#sh-close-btn').addEventListener('click', _closePanel);
    p.querySelector('#sh-prev-btn').addEventListener('click', () => _navigateFix(-1));
    p.querySelector('#sh-next-btn').addEventListener('click', () => _navigateFix(+1));
  }

  function _buildTriggerButton() {
    const topbar = document.getElementById('topbar');
    if (!topbar) return;
    const btn = document.createElement('button');
    btn.id = 'sh-trigger-btn';
    btn.title = 'Self-Healing: suggest fixes for compiler errors';
    btn.innerHTML = '🔧 Suggest Fix';
    btn.addEventListener('click', _onSuggestFix);
    const runBtn = document.getElementById('run-btn');
    topbar.insertBefore(btn, runBtn || null);
  }

  function _openPanel()  { const p = document.getElementById('sh-panel'); if (p) { p.classList.add('sh-open');    _sh.panelOpen = true;  } }
  function _closePanel() { const p = document.getElementById('sh-panel'); if (p) { p.classList.remove('sh-open'); _sh.panelOpen = false; } }

  function _showLoading(yes) {
    document.getElementById('sh-loading').style.display = yes ? 'flex' : 'none';
    document.getElementById('sh-body').style.display    = yes ? 'none' : 'block';
    document.getElementById('sh-empty').style.display   = 'none';
  }
  function _showEmpty() {
    document.getElementById('sh-loading').style.display = 'none';
    document.getElementById('sh-body').style.display    = 'none';
    document.getElementById('sh-empty').style.display   = 'block';
  }

  function _renderFix(idx) {
    if (!_sh.healData) return;
    const { suggestions = [], explanations = [], error_count = 0 } = _sh.healData;
    _sh.currentFixIdx = idx;
    document.getElementById('sh-nav-label').textContent = `Error ${idx + 1} of ${error_count}`;
    document.getElementById('sh-prev-btn').disabled = idx === 0;
    document.getElementById('sh-next-btn').disabled = idx >= error_count - 1;

    const fix = suggestions[idx] || null;
    const exp = explanations[idx] || null;
    _sh.currentFix = fix;

    let html = '';
    if (exp) {
      html += `<div class="sh-card">
        <div class="sh-card-head"><span class="sh-card-icon">💡</span><div class="sh-card-title">${_esc(exp.title || 'Compiler Error')}</div></div>
        <div class="sh-card-body">
          <div class="sh-label">What went wrong</div>
          <div class="sh-explanation">${_esc(exp.explanation || '')}</div>
          ${exp.fix ? `<div class="sh-label">How to fix it</div><div class="sh-fix-text">${_esc(exp.fix)}</div>` : ''}
        </div></div>`;
    }
    if (fix) {
      const confClass = `sh-conf-${fix.confidence || 'low'}`;
      const confLabel = {high:'✓ High',medium:'~ Medium',low:'? Low'}[fix.confidence] || 'Low';
      const orig = exp && exp.fixed_line ? exp.fixed_line : '';
      const fixed = fix.fixed_line || '';
      let codeHtml = '';
      if (orig && orig !== fixed) {
        codeHtml = `<div class="sh-code-block"><span class="sh-del">- ${_esc(orig)}</span><span class="sh-add">+ ${_esc(fixed)}</span></div>`;
      } else if (fixed) {
        codeHtml = `<div class="sh-code-block">${_esc(fixed)}</div>`;
      }
      html += `<div class="sh-card">
        <div class="sh-card-head"><span class="sh-card-icon">🔧</span><div class="sh-card-title">Suggested Fix</div><span class="sh-conf-badge ${confClass}">${confLabel}</span></div>
        <div class="sh-card-body">
          <div class="sh-label">Fix description</div>
          <div class="sh-fix-text">${_esc(fix.description || '')}</div>
          ${codeHtml}
          ${fix.full_fixed_source
            ? `<button id="sh-apply-btn">⚡ Apply Fix to Editor</button><div id="sh-applied-note">✓ Applied! Re-run to verify.</div>`
            : `<div style="font-size:12px;color:var(--txt3)">Apply the line change manually.</div>`}
        </div></div>`;
    }

    document.getElementById('sh-content').innerHTML =
      html || '<div style="color:var(--txt3);font-size:13px">No suggestion for this error.</div>';

    const applyBtn = document.getElementById('sh-apply-btn');
    if (applyBtn) applyBtn.addEventListener('click', _onApplyFix);
  }

  function _navigateFix(delta) {
    if (!_sh.healData) return;
    const next = _sh.currentFixIdx + delta;
    if (next < 0 || next >= _sh.healData.error_count) return;
    _renderFix(next);
  }

  function _onApplyFix() {
    if (!_sh.currentFix || !_sh.currentFix.full_fixed_source) return;
    const src = _sh.currentFix.full_fixed_source;
    if (typeof window.editor !== 'undefined' && window.editor && typeof window.editor.setValue === 'function') {
      window.editor.setValue(src);
    } else {
      const cm = document.querySelector('.CodeMirror');
      if (cm && cm.CodeMirror) cm.CodeMirror.setValue(src);
    }
    const btn  = document.getElementById('sh-apply-btn');
    const note = document.getElementById('sh-applied-note');
    if (btn)  { btn.disabled = true; btn.textContent = '✓ Applied'; }
    if (note)   note.style.display = 'block';
  }

  function _onSuggestFix() {
    _openPanel();
    if (_sh.healData && _sh.healData.enabled) {
      _showLoading(false);
      _renderFix(0);
      return;
    }
    _showLoading(true);
    if (!_sh.lastSource) { _showEmpty(); return; }
    fetch('/api/self-heal', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({code: _sh.lastSource, lang: _sh.lastLang}),
    })
      .then(r => r.json())
      .then(data => {
        _sh.healData = data.self_heal || null;
        _showLoading(false);
        if (_sh.healData && _sh.healData.enabled && _sh.healData.error_count > 0) _renderFix(0);
        else _showEmpty();
      })
      .catch(() => { _showLoading(false); _showEmpty(); });
  }

  function _hookFetch() {
    const _orig = window.fetch.bind(window);
    window.fetch = function (input, init) {
      const url = typeof input === 'string' ? input : (input && input.url) || '';
      const promise = _orig(input, init);
      if (!url.includes('/api/compile')) return promise;

      try {
        const body = init && init.body ? JSON.parse(init.body) : {};
        _sh.lastSource = body.code || '';
        _sh.lastLang   = body.lang || 'cpp';
      } catch (_) {}

      return promise.then(response => {
        response.clone().json().then(data => {
          const triggerBtn = document.getElementById('sh-trigger-btn');
          if (!data.success) {
            if (triggerBtn) triggerBtn.style.display = 'flex';
            _sh.healData = (data.self_heal && data.self_heal.enabled) ? data.self_heal : null;
          } else {
            if (triggerBtn) triggerBtn.style.display = 'none';
            _closePanel();
            _sh.healData = null;
          }
        }).catch(() => {});
        return response;
      });
    };
  }

  function _esc(s) {
    if (typeof s !== 'string') return '';
    return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function init() {
    _injectStyles();
    _buildPanel();
    _buildTriggerButton();
    _hookFetch();
    fetch('/api/self-heal-status').then(r => r.json()).then(d => { _sh.enabled = !!(d && d.enabled); }).catch(() => {});
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && _sh.panelOpen) _closePanel(); });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
// END SELF-HEAL ADDITION
