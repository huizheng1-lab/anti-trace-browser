"""Conservative, document-local ad skip discovery (no synthetic input)."""

AUTOSKIP_JS = r"""
(function(){
  const ytSelectors = '.ytp-ad-skip-button-modern, .ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-container button, .videoAdUiSkipButton, #skip-button button, [id*="skip-button"] button, button[class*="skip-ad-button"], button[class*="ytp-ad-skip"]';
  const explicit = /^skip\s+(?:this\s+)?(?:ads?|advertisements?)[.!»›>\s]*$/i;
  function parent(el) { return el.parentElement || (el.getRootNode().host || null); }
  function usable(el) {
    if (!el || !el.isConnected || el.matches(':disabled') || el.closest('[inert]')) return false;
    for (let n=el; n; n=parent(n)) {
      const s=n.ownerDocument.defaultView.getComputedStyle(n);
      if (n.hidden || n.inert || n.getAttribute('aria-disabled')==='true' ||
          n.getAttribute('aria-hidden')==='true' || s.display==='none' ||
          s.visibility!=='visible' || Number(s.opacity)<0.05 || s.pointerEvents==='none') return false;
    }
    const r=el.getBoundingClientRect(), w=el.ownerDocument.defaultView;
    return r.width>1 && r.height>1 && r.left>=0 && r.top>=0 && r.right<=w.innerWidth && r.bottom<=w.innerHeight;
  }
  function topAt(root,x,y) {
    let hit=root.elementFromPoint(x,y);
    while(hit && hit.shadowRoot) {
      const next=hit.shadowRoot.elementFromPoint(x,y);
      if (!next || next===hit) break;
      hit=next;
    }
    return hit;
  }
  function contains(el,hit) {
    for(let n=hit;n;n=parent(n)) if(n===el) return true;
    return false;
  }
  function scan(doc, offsetX, offsetY, frameChecks) {
    // Weak state dies on navigation; a lingering control is attempted only once.
    const state=doc.__atbAdSkipState || (doc.__atbAdSkipState={attempted:new WeakSet()});
    const youtube=/(^|\.)youtube(?:-nocookie)?\.com$/i.test(doc.location.hostname);
    const roots=[doc];
    for(let ri=0;ri<roots.length;ri++) {
      const root=roots[ri];
      for(const host of root.querySelectorAll('*')) if(host.shadowRoot) roots.push(host.shadowRoot);
      const selector='button, input[type="button"], [role="button"]'+(youtube?', '+ytSelectors:'');
      for(const el of root.querySelectorAll(selector)) {
        if(!usable(el)) {state.attempted.delete(el); continue;}
        // Never activate links, submit actions, consent/security/payment controls.
        if(el.closest('a, form, [role="link"], [role="dialog"], [aria-modal="true"]') ||
           el.matches('input:not([type="button"]), button[type="submit"]')) continue;
        const text=(el.innerText || el.value || '').trim().replace(/\s+/g,' ');
        const aria=(el.getAttribute('aria-label')||'').trim().replace(/\s+/g,' ');
        const known=youtube && el.matches(ytSelectors);
        if(!explicit.test(text) && !(text==='' && explicit.test(aria)) &&
           !(known && /^skip(?:\s+ads?)?[.!»›>\s]*$/i.test(text || aria))) continue;
        if(state.attempted.has(el)) continue;
        const r=el.getBoundingClientRect(), x=r.left+r.width/2, y=r.top+r.height/2;
        if(!contains(el,topAt(root,x,y))) continue;
        const tx=x+offsetX, ty=y+offsetY;
        if(!frameChecks.every(f=>contains(f.el,topAt(f.root,tx-f.ox,ty-f.oy)))) continue;
        state.attempted.add(el);
        return {found:true,x:tx,y:ty};
      }
      for(const frame of root.querySelectorAll('iframe, frame')) {
        if(!usable(frame)) continue;
        // Transformed/scaled frames require coordinate mapping we cannot trust.
        let transformed=false;
        for(let n=frame;n;n=parent(n)) if(doc.defaultView.getComputedStyle(n).transform!=='none') transformed=true;
        if(transformed) continue;
        try {
          const child=frame.contentDocument;
          if(!child || !child.documentElement) continue; // cross-origin stays inaccessible
          const r=frame.getBoundingClientRect();
          const result=scan(child,offsetX+r.left+frame.clientLeft,offsetY+r.top+frame.clientTop,
            frameChecks.concat([{el:frame,root:root,ox:offsetX,oy:offsetY}]));
          if(result) return result;
        } catch(_) {} // browser origin restrictions are preserved
      }
    }
    return null;
  }
  return JSON.stringify(scan(document,0,0,[]) || {found:false});
})();
"""
