// ElevenLabs 网页版出图：贴进页面（浏览器面板 javascript_tool）用的辅助函数。
// 配套 el_web_image.py：`python el_web_image.py js` 出 window.__C/__ROWS（提示词），先贴那段、再贴本文件。
//
// 为什么全是 MessageChannel 等待、不用 setTimeout（2026-10-18《海底四十小時》）：
//   浏览器面板被隐藏时，后台标签页的 setTimeout 会被节流到一分钟一次 —— 收图从一张 8 秒变成两分钟，
//   43 张拖了四十分钟。MessageChannel 不被节流，React 的调度也走它，页面照常渲染。
// 为什么「Load 2K」要发完整的指针事件：只调 .click() 有时点到同名的隐藏元素，2K 不加载、也不报错。
// 为什么只认中央那张 content.png 且和上一张不同：查看器换图有延迟，按提示词对上了名字、拿到的却可能是上一张。
//
// 用法（每次调用都是一次 javascript_tool）：
//   1) 先 `python el_web_image.py js 档名...`，把输出贴进去（定义 __C/__ROWS 并展开成 __P）
//   2) 贴本文件
//   3) await __applySettings()            → 按 __WANT 把模型/比例/分辨率/张数/画质全改好并核对；任何 navigate 之后都要重跑
//      （只核不改：await __checkSettings()）
//   4) __runQueue()                       → 后台逐张提交（不 await），进度看 __glog
//   5) 等生成完：await __refresh(); await __harvest(45000)
//                                         → __refresh 走站内路由 Explore→History 重拉列表（隐藏页里新图不会自己出现；
//                                           navigate 也能刷新，但页面里的 JS 全丢、设定被重置）。
//                                           __harvest 逐张打开、Load 2K、按提示词对档名，存进 __R；一次最多跑 45 秒，没收完再调；
//                                           第二个参数 maxCards 限制往下翻几张（只收刚出的几张时填 6，免得翻遍几个月的历史）
//   6) __export()                         → 返回 JSON + 30 万字符填充：工具结果超长会自动存成文件，
//                                           交给 `python el_web_image.py fetch <那个文件>` 下载。链接 2 小时过期，收完马上下。

(() => {
  const tick = () => new Promise(r => { const c = new MessageChannel(); c.port1.onmessage = () => r(); c.port2.postMessage(0); });
  const waitFor = async (fn, ms) => { const t0 = performance.now(); while (performance.now() - t0 < ms) { const v = fn(); if (v) return v; await tick(); } return null; };
  window.__tick = tick; window.__waitFor = waitFor;
  window.__R = window.__R || {};
  window.__glog = window.__glog || [];

  // ---- 设定：当前编辑框那一排按钮（模型 / 比例 / 分辨率 / 画质 / 张数 / 自动改写）
  window.__WANT = window.__WANT || { model: "GPT Image 2.5 Flare", ratio: "16:9", res: "2K", quality: "Medium", n: "1", improve: "Off" };
  window.__settings = () => [...document.querySelectorAll('button')]
    .filter(b => { const r = b.getBoundingClientRect(); return r.width > 0 && r.top > window.innerHeight * 0.55; })
    .map(b => b.innerText.trim()).filter(t => t).join(' / ');
  window.__ok = () => {
    const W = window.__WANT;
    return new RegExp([W.model, W.ratio, W.res, W.quality, W.n, W.improve].map(x => x.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join(' / ')).test(window.__settings());
  };
  window.__checkSettings = async () => ({ ok: window.__ok(), now: window.__settings().slice(-80), want: window.__WANT });
  // 改设定（2026-10-19《冷山》）：菜单项的 click / pointer 事件常不生效，computer 工具按方向键又会丢键
  // （连按 5 下只走 1 格）。**在 JS 里对触发按钮发 ArrowDown 打开菜单、对高亮项发方向键/Enter** 最稳：
  // Radix 菜单认 keydown，不认合成的点击。
  const menuItems = () => [...document.querySelectorAll('[role="menuitemradio"],[role="option"],[role="menuitem"]')];
  const itemText = (e) => e.innerText.trim().split('\n')[0].trim();
  window.__menuTo = async (target) => {
    for (let k = 0; k < 40; k++) {
      const items = menuItems(), h = items.find(e => e.getAttribute('data-highlighted') !== null);
      if (!h) return 'no highlight';
      const t = itemText(h);
      if (t === target) { h.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true })); await waitFor(() => false, 500); return 'selected ' + t; }
      const names = items.map(itemText);
      if (names.indexOf(target) < 0) return 'no item ' + target + ' in ' + names.join('|');
      h.dispatchEvent(new KeyboardEvent('keydown', { key: names.indexOf(target) > names.indexOf(t) ? 'ArrowDown' : 'ArrowUp', bubbles: true, cancelable: true }));
      await waitFor(() => false, 150);
    }
    return 'gave up';
  };
  window.__setOpt = async (btn, target) => {
    if (!btn) return 'no button';
    btn.focus();
    btn.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }));
    if (!await waitFor(() => menuItems().find(e => e.getAttribute('data-highlighted') !== null), 2000)) return 'menu did not open';
    return await window.__menuTo(target);
  };
  window.__applySettings = async () => {
    const W = window.__WANT, out = [];
    const bar = () => [...document.querySelectorAll('button')].filter(b => b.getBoundingClientRect().top > window.innerHeight * 0.55);
    const model = bar().find(b => /^(GPT|Nano|FLUX|Recraft|Seedream|Krea|Kling|Gen-4|Wan)/.test(b.innerText.trim()));
    if (model && model.innerText.trim() !== W.model) out.push('model: ' + await window.__setOpt(model, W.model));
    for (const [label, v] of [['Aspect ratio', W.ratio], ['Resolution', W.res], ['Number of generations', W.n], ['Quality', W.quality]]) {
      const b = document.querySelector(`button[aria-label="${label}"]`);     // 画质最后改：切模型会把画质弹回 High
      if (b && b.innerText.trim() !== v) out.push(label + ': ' + await window.__setOpt(b, v));
    }
    return { ok: window.__ok(), now: window.__settings().slice(-80), did: out };
  };
  window.__refresh = async () => {
    const link = (t) => [...document.querySelectorAll('a,button')].find(e => e.innerText.trim() === t);
    const ex = link('Explore'); if (!ex) return 'no Explore tab';
    ex.click(); await waitFor(() => !location.href.includes('history'), 5000); await waitFor(() => false, 1500);
    const hi = link('History'); if (!hi) return 'no History tab';
    hi.click(); await waitFor(() => location.href.includes('history'), 5000);
    await waitFor(() => window.__cards().length > 3, 15000);
    window.__hi = 0;
    return 'cards ' + window.__cards().length;
  };
  // 旧接口留着：只把菜单打开、列出选项
  window.__openMenu = async (label) => {
    const b = document.querySelector(`button[aria-label="${label}"]`);
    if (!b) return 'no button ' + label;
    b.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, button: 0, pointerType: 'mouse' }));
    await waitFor(() => document.querySelector('[role="menuitemradio"],[role="option"],[role="menuitem"]'), 2000);
    return [...document.querySelectorAll('[role="menuitemradio"],[role="option"],[role="menuitem"]')]
      .map(e => e.innerText.trim() + (e.getAttribute('data-highlighted') !== null ? '*' : '')).join(' | ');
  };

  // ---- 提交一张：往 ProseMirror 编辑框塞字，核对，点 Generate（就是正常点按钮；不绕过 hCaptcha、不直调接口）
  window.__gen = async (name) => {
    await waitFor(() => document.querySelector('button[aria-label="Generate"]'), 30000);
    if (!window.__ok()) return name + ': SETTINGS ' + window.__settings().slice(-80);
    const ed = document.querySelector('.ProseMirror[contenteditable="true"]');
    if (!ed) return name + ': NO EDITOR';
    ed.focus(); document.execCommand('selectAll'); document.execCommand('delete');
    document.execCommand('insertText', false, window.__P[name]);
    await waitFor(() => ed.innerText.replace(/\s+/g, '').length >= window.__P[name].replace(/\s+/g, '').length - 2, 3000);
    if (ed.innerText.replace(/\s+/g, '') !== window.__P[name].replace(/\s+/g, '')) return name + ': TEXT MISMATCH';
    const btn = await waitFor(() => { const b = document.querySelector('button[aria-label="Generate"]'); return b && !b.disabled ? b : null; }, 180000);
    if (!btn) return name + ': BUSY';
    btn.click();
    await waitFor(() => false, 2500);
    return name + ': OK';
  };
  // 后台逐张提交；任何一张不是 OK 就停（设定跑掉、文字没塞进去）
  window.__runQueue = (names) => {
    const q = names || Object.keys(window.__P).filter(k => !window.__R[k]);
    window.__running = true;
    (async () => {
      for (const n of q) { if (!window.__running) break; const r = await window.__gen(n); window.__glog.push(r); if (!/OK$/.test(r)) break; }
      window.__running = false;
    })();
    return 'queued ' + q.length;
  };

  // ---- 收图
  window.__viewerPrompt = () => { const p = [...document.querySelectorAll('p')].find(p => p.innerText.trim() === 'Prompt'); return p ? (p.nextElementSibling?.innerText || '').replace(/\s+/g, '') : null; };
  // 按每张**独有的画面句**对档名（__MID，el_web_image.py js 给的）；固定开头/结尾所有提示词都一样，拿它们对会对错
  window.__matchName = (vp) => {
    if (!vp) return null;
    const M = window.__MID || {};
    return Object.keys(window.__P).find(k => vp === window.__P[k].replace(/\s+/g, ''))
        || Object.keys(M).find(k => vp.includes(M[k].replace(/\s+/g, ''))) || null;
  };
  window.__cards = () => { const seen = new Set(), out = []; for (const im of document.querySelectorAll('img')) { const b = im.closest('button'); if (!b || seen.has(b) || b.getBoundingClientRect().width < 100) continue; seen.add(b); out.push(b); } return out; };
  const closeViewer = async () => { const c = [...document.querySelectorAll('button')].find(b => /close/i.test(b.getAttribute('aria-label') || '') && b.getBoundingClientRect().top < 120); if (c) c.click(); await waitFor(() => !window.__viewerPrompt(), 3000); };
  const load2k = () => {
    const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === 'Load 2K' && b.getBoundingClientRect().width > 0);
    if (!b) return false;
    const r = b.getBoundingClientRect(), o = { bubbles: true, cancelable: true, clientX: r.x + r.width / 2, clientY: r.y + r.height / 2, button: 0, pointerType: 'mouse' };
    b.dispatchEvent(new PointerEvent('pointerdown', o)); b.dispatchEvent(new MouseEvent('mousedown', o));
    b.dispatchEvent(new PointerEvent('pointerup', o)); b.dispatchEvent(new MouseEvent('mouseup', o)); b.click();
    return true;
  };
  // 从历史列表第 0 张往下逐张开；只收 __P 里还没收到的。一次调用最多跑 budgetMs，没收完就再调一次。
  window.__harvest = async (budgetMs = 40000, maxCards = 200) => {
    const t0 = performance.now(), log = [];
    if (window.__viewerPrompt()) await closeViewer();
    window.scrollTo(0, 0);
    await waitFor(() => window.__cards().length > 0, 15000);
    for (let i = window.__hi || 0; performance.now() - t0 < budgetMs; i++) {
      if (!Object.keys(window.__P).some(k => !window.__R[k])) { window.__hi = 0; break; }
      if (i >= maxCards) { log.push('翻到第 ' + maxCards + ' 张还没收齐，停（刚交的图可能还在生成：等一会儿 __refresh 再收）'); window.__hi = 0; break; }
      let cs = window.__cards();
      for (let k = 0; k < 8 && i >= cs.length; k++) { window.scrollBy(0, 2000); await waitFor(() => false, 800); cs = window.__cards(); }
      if (i >= cs.length) { log.push(i + ' 没有更多卡片'); window.__hi = 0; break; }
      window.__hi = i + 1;
      cs[i].scrollIntoView({ block: 'center' }); cs[i].click();
      const vp = await waitFor(() => window.__viewerPrompt(), 8000);
      if (!vp) { log.push(i + ' 查看器没开'); continue; }
      const name = window.__matchName(vp);
      if (!name || window.__R[name]) { await closeViewer(); continue; }
      await waitFor(() => load2k(), 8000);
      const im = await waitFor(() => { const x = [...document.querySelectorAll('img')].find(m => m.src.includes('content.png') && m.getBoundingClientRect().x > 150 && m.getBoundingClientRect().width > 150); return x && x.src !== window.__lastUrl ? x : null; }, 15000);
      if (im) { window.__R[name] = im.src; window.__lastUrl = im.src; log.push(i + ' got ' + name); } else log.push(i + ' 没等到 2K：' + name);
      await closeViewer();
    }
    return { log, left: Object.keys(window.__P).filter(k => !window.__R[k]) };
  };
  window.__export = () => JSON.stringify(window.__R) + ' '.repeat(10) + 'PAD'.repeat(100000);
  return 'el_web_image helpers ready';
})();
