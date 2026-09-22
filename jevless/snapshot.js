// Instinct page snapshot. Evaluated in the page as one expression; returns the observation, or null before <body>.
// Pierces open shadow roots and same-origin frames. Node identity lives in window.__instinct (a WeakMap), so the
// model only ever names observed elements by number and the executor resolves the real node at execution time.
(() => {
  if (!document.body) return null;
  const S = (window.__instinct ||= { ids: new WeakMap(), nodes: new Map(), next: 1 });
  const identity = (e) => {
    if (!S.ids.has(e)) S.ids.set(e, S.next++);
    const id = S.ids.get(e);
    S.nodes.set(id, e);
    return id;
  };
  for (const [id, e] of S.nodes) if (!e.isConnected) S.nodes.delete(id);

  const ROLES = ['button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem', 'menuitemcheckbox', 'menuitemradio',
    'option', 'treeitem', 'gridcell', 'combobox', 'textbox', 'searchbox', 'spinbutton', 'slider'];
  const SELECTOR = 'a[href],button,input,textarea,select,summary,[contenteditable=""],[contenteditable="true"],[role],[tabindex="0"]';
  const safeInput = (e) => e.tagName !== 'INPUT' || !['password', 'file', 'hidden'].includes((e.type || '').toLowerCase());
  const winOf = (e) => e.ownerDocument.defaultView;
  // Offset of an element's document inside the top viewport: (0,0) unless it lives in a same-origin frame.
  const frameOffset = (e) => {
    let d = e.ownerDocument, x = 0, y = 0;
    for (let i = 0; i < 8 && d && d.defaultView && d.defaultView.frameElement; i++) {
      const f = d.defaultView.frameElement, r = f.getBoundingClientRect();
      x += r.x + f.clientLeft; y += r.y + f.clientTop; d = f.ownerDocument;
    }
    return { x, y };
  };
  const visible = (e) => e.isConnected && !e.closest('[aria-hidden="true"],[inert]') &&
    e.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
  const globalRect = (e) => { const r = e.getBoundingClientRect(), o = frameOffset(e); return { x: r.x + o.x, y: r.y + o.y, w: r.width, h: r.height }; };
  const onScreen = (e) => {
    const r = e.getBoundingClientRect(), w = winOf(e);
    if (r.width <= 0 || r.height <= 0) return false;
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    if (cx < 0 || cy < 0 || cx >= w.innerWidth || cy >= w.innerHeight) return false;
    const o = frameOffset(e), gx = cx + o.x, gy = cy + o.y;
    return gx >= 0 && gy >= 0 && gx < innerWidth && gy < innerHeight;
  };
  // Just off screen (within one viewport above or below): listed so the model can pick them; execution scrolls to them.
  const nearScreen = (e) => {
    const g = globalRect(e);
    if (g.w <= 0 || g.h <= 0) return false;
    const cx = g.x + g.w / 2, cy = g.y + g.h / 2;
    return cx >= 0 && cx < innerWidth && cy >= -innerHeight && cy < innerHeight * 2;
  };
  const byId = (e, id) => { const root = e.getRootNode(); return (root.getElementById && root.getElementById(id)) || e.ownerDocument.getElementById(id); };
  const name = (e, seen = new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const ref = (e.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)
      .map((id) => name(byId(e, id), seen)).filter(Boolean).join(' ');
    if (ref) return ref;
    const aria = (e.getAttribute('aria-label') || '').trim();
    if (aria) return aria;
    const labels = [...(e.labels || [])].map((l) => name(l, seen)).filter(Boolean).join(' ');
    if (labels) return labels;
    if (e.tagName === 'INPUT' && ['button', 'submit', 'reset'].includes(e.type) && e.value) return e.value;
    const alt = e.getAttribute('alt');
    if (alt) return alt;
    if (!['INPUT', 'TEXTAREA', 'SELECT'].includes(e.tagName)) {
      const kids = [...e.childNodes, ...(e.shadowRoot ? e.shadowRoot.childNodes : [])];
      const text = kids.map((n) => n.nodeType === 3 ? n.textContent :
        n.nodeType === 1 && n.getAttribute('aria-hidden') !== 'true' ? name(n, seen) : '').join(' ').replace(/\s+/g, ' ').trim();
      if (text) return text;
    }
    return e.getAttribute('title') || e.getAttribute('placeholder') || '';
  };
  const role = (e) => {
    const explicit = (e.getAttribute('role') || '').trim().split(/\s+/)[0];
    if (ROLES.includes(explicit)) return explicit;
    const t = e.tagName;
    if (t === 'BUTTON' || t === 'SUMMARY') return 'button';
    if (t === 'A') return e.hasAttribute('href') ? 'link' : null;
    if (t === 'SELECT') return 'select';
    if (t === 'TEXTAREA' || e.isContentEditable) return 'textbox';
    if (t === 'INPUT') {
      const ty = (e.type || 'text').toLowerCase();
      if (ty === 'checkbox' || ty === 'radio') return ty;
      if (['button', 'submit', 'reset', 'image'].includes(ty)) return 'button';
      if (ty === 'search') return 'searchbox';
      if (ty === 'number') return 'spinbutton';
      if (ty === 'range') return 'slider';
      if (['text', 'email', 'url', 'tel', 'date', 'time', 'datetime-local', 'month', 'week', 'color'].includes(ty)) return 'textbox';
      return null;
    }
    if (explicit) return null;
    if (e.getAttribute('tabindex') === '0' && (e.hasAttribute('onclick') || getComputedStyle(e).cursor === 'pointer')) return 'button';
    return null;
  };

  const roots = [document];
  const actions = [];
  const offscreen = [];
  const collect = (root) => {
    for (const e of root.querySelectorAll('*')) {
      if (e.shadowRoot) { roots.push(e.shadowRoot); collect(e.shadowRoot); }
      if (e.tagName === 'IFRAME' || e.tagName === 'FRAME') {
        let d = null;
        try { d = e.contentDocument; } catch (_) { d = null; }
        if (d && d.body && visible(e)) { roots.push(d); collect(d); }
        continue;
      }
      if (!e.matches(SELECTOR) || !safeInput(e)) continue;
      if (!visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
      const r = role(e);
      if (!r) continue;
      const on = onScreen(e);
      if (!on && !nearScreen(e)) continue;
      if (r === 'gridcell' && e.querySelector('button,[role="button"],a[href]')) continue;
      const a = { node: identity(e), role: r, label: (name(e) || r).slice(0, 200), rect: globalRect(e) };
      if (!on) a.offscreen = a.rect.y + a.rect.h / 2 < 0 ? 'above' : 'below';
      for (const key of ['expanded', 'selected', 'checked', 'pressed']) {
        const v = e.getAttribute('aria-' + key);
        if (v === 'true' || v === 'false') a[key] = v === 'true';
      }
      if (e.tagName === 'INPUT' && (e.type === 'checkbox' || e.type === 'radio')) a.checked = e.checked;
      if (e.tagName === 'SELECT') {
        a.kind = 'select';
        a.value = [...e.selectedOptions].map((o) => o.label || o.text).join(', ').slice(0, 200);
        a.options = [];
        let i = 0;
        for (const o of e.options) {
          i++;
          if (o.disabled || (o.parentElement && o.parentElement.tagName === 'OPTGROUP' && o.parentElement.disabled)) continue;
          a.options.push({ i, label: (o.label || o.text || '').trim().slice(0, 80), value: o.value, selected: o.selected });
        }
      } else {
        const editable = !e.readOnly && e.getAttribute('aria-readonly') !== 'true' &&
          (['textbox', 'searchbox', 'spinbutton'].includes(r) ||
            (r === 'combobox' && (e.tagName === 'INPUT' || e.tagName === 'TEXTAREA')) || e.isContentEditable);
        a.kind = editable ? 'fill' : 'click';
        if (editable) a.editable = true;
        a.value = typeof e.value === 'string' ? e.value.slice(0, 200) :
          (e.isContentEditable || r === 'combobox') ? (e.innerText || '').trim().slice(0, 200) : '';
      }
      (on ? actions : offscreen).push(a);
    }
  };
  collect(document);

  // Visible text only: what is on screen now, across the same roots.
  const parts = [];
  let total = 0;
  for (const root of roots) {
    const doc = root.ownerDocument || root, body = root.body || root;
    const walker = doc.createTreeWalker(body, NodeFilter.SHOW_TEXT), range = doc.createRange();
    let n;
    while ((n = walker.nextNode()) && total < 5000) {
      const v = n.textContent.replace(/\s+/g, ' ').trim(), p = n.parentElement;
      if (!v || !p || p.closest('script,style,noscript,template') || !visible(p)) continue;
      range.selectNodeContents(n);
      const r = range.getBoundingClientRect(), o = frameOffset(p), x = r.x + o.x, y = r.y + o.y;
      if (r.width > 0 && r.height > 0 && y + r.height > 0 && y < innerHeight && x + r.width > 0 && x < innerWidth) {
        parts.push(v);
        total += v.length + 1;
      }
    }
  }
  const text = parts.join('\n').slice(0, 5000);
  const dialogs = [];
  for (const root of roots) for (const d of root.querySelectorAll('dialog[open],[role="dialog"],[role="alertdialog"]')) {
    if (dialogs.length >= 3 || !visible(d)) continue;
    const r = d.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    dialogs.push((name(d) || (d.innerText || '').replace(/\s+/g, ' ').trim()).slice(0, 80));
  }

  const allRoots = () => {
    const out = [document];
    const walk = (root) => {
      for (const e of root.querySelectorAll('*')) {
        if (e.shadowRoot) { out.push(e.shadowRoot); walk(e.shadowRoot); }
        if (e.tagName === 'IFRAME' || e.tagName === 'FRAME') {
          let d = null;
          try { d = e.contentDocument; } catch (_) { d = null; }
          if (d && d.body) { out.push(d); walk(d); }
        }
      }
    };
    walk(document);
    return out;
  };
  const formState = (rs) => {
    const out = [];
    for (const root of rs) for (const e of root.querySelectorAll('input,textarea,select'))
      if (safeInput(e)) out.push([identity(e), e.value, e.checked, e.selectedIndex, e.disabled, e.readOnly]);
    return out;
  };
  S.pageKey = (rs) => [performance.timeOrigin, location.href, scrollX, scrollY, innerWidth, innerHeight, formState(rs || allRoots())];
  // What must still hold for a decision about this element to be executed: identity, meaning, state, and nearby context.
  // "Nearby" for a guard: the largest enclosing block whose text stays under 600 chars, stopping at the form/row/dialog
  // boundary. A price cell updating elsewhere in a big dialog is not a reason to re-decide; a changed total next to the
  // button is.
  const context = (e) => {
    const boundary = e.closest('form,dialog,[role="dialog"],[role="listbox"],[role="menu"],article,li,tr,[role="row"]');
    const doc = e.ownerDocument;
    let best = null, n = e.parentElement;
    while (n && n !== doc.body && n !== doc.documentElement && n.tagName !== 'MAIN') {
      if ((n.innerText || '').length > 600) break;
      best = n;
      if (n === boundary) break;
      n = n.parentElement;
    }
    if (best) return (best.innerText || '').slice(0, 600);
    // Nothing small encloses it (a huge container or <body>): the closest siblings are the neighbourhood.
    const near = [e.previousElementSibling, e.previousElementSibling?.previousElementSibling, e.nextElementSibling,
      e.nextElementSibling?.nextElementSibling];
    return near.map((s) => (s && s.innerText) || '').join('\n').slice(0, 600);
  };
  S.guard = (e) => {
    if (!e || !e.isConnected || !visible(e)) return null;
    return [identity(e), role(e), name(e), e.value ?? null, e.checked ?? null, e.selectedIndex ?? null, e.readOnly ?? null,
      e.matches(':disabled'), e.getAttribute('aria-disabled'), e.getAttribute('aria-expanded'), e.getAttribute('aria-checked'),
      e.getAttribute('aria-selected'), e.getAttribute('href'), context(e)];
  };
  const deepHit = (x, y) => {
    let doc = document, ox = 0, oy = 0, found = null;
    for (let i = 0; i < 8; i++) {
      let e = doc.elementFromPoint(x - ox, y - oy);
      if (!e) return found;
      while (e.shadowRoot) {
        const inner = e.shadowRoot.elementFromPoint(x - ox, y - oy);
        if (!inner || inner === e) break;
        e = inner;
      }
      found = e;
      if (e.tagName === 'IFRAME' || e.tagName === 'FRAME') {
        let d = null;
        try { d = e.contentDocument; } catch (_) { d = null; }
        if (!d) return found;
        const r = e.getBoundingClientRect();
        ox += r.x + e.clientLeft; oy += r.y + e.clientTop; doc = d;
        continue;
      }
      return found;
    }
    return found;
  };
  const within = (hit, e) => {
    let n = hit;
    for (let i = 0; n && i < 500; i++) {
      if (n === e) return true;
      n = n.parentElement || (n.getRootNode && n.getRootNode().host) ||
        (n.ownerDocument && n.ownerDocument.defaultView && n.ownerDocument.defaultView.frameElement) || null;
    }
    return false;
  };
  // Resolve an observed node to a click point right now, or null when it moved off screen, got covered, or changed kind.
  S.point = (node, kind, value, index) => {
    const e = S.nodes.get(node);
    if (!e || !e.isConnected || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]')) return null;
    if (kind === 'fill' && (e.readOnly || e.getAttribute('aria-readonly') === 'true')) return null;
    if (!onScreen(e)) {
      e.scrollIntoView({ block: 'center', inline: 'nearest' });
      if (!onScreen(e)) return null;
    }
    const g = globalRect(e), x = g.x + g.w / 2, y = g.y + g.h / 2;
    const hit = deepHit(x, y);
    if (!hit || !within(hit, e)) return null;
    if (kind === 'select') {
      if (e.tagName !== 'SELECT') return null;
      const o = e.options[index - 1];
      if (!o || o.value !== value || o.disabled) return null;
      e.value = o.value;
      e.dispatchEvent(new Event('input', { bubbles: true }));
      e.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return { x, y };
  };

  const omitted = Math.max(0, actions.length - 200) + Math.max(0, offscreen.length - 40);
  actions.splice(200);
  actions.push(...offscreen.slice(0, 40));
  actions.forEach((a, i) => { a.id = i + 1; });
  const guards = {};
  for (const a of actions) if (!(a.node in guards)) guards[a.node] = S.guard(S.nodes.get(a.node));
  const page_key = S.pageKey(roots);
  const semantics = actions.map(({ rect, ...a }) => a);
  const height = Math.max(document.documentElement.scrollHeight || 0, document.body.scrollHeight || 0);
  const marker = [performance.timeOrigin, location.href, scrollX, scrollY, innerWidth, innerHeight, document.title, text, semantics, page_key[6]];
  return { url: location.href, title: document.title, w: innerWidth, h: innerHeight, text,
    scroll: { y: Math.round(scrollY), height }, actions, marker, page_key, guards, omitted, dialogs };
})()
