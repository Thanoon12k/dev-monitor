// Video mode (?v=1): a deterministic timeline. window.seek(t) draws the frame at t seconds,
// so the renderer can capture exact frames. Without ?v the page stays a static poster.
(function () {
  const q = new URLSearchParams(location.search);
  if (!q.get('v')) return;
  const DUR = 14, BEFORE = 47, C = 540.35;
  window.DUR = DUR;

  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  const clamp = x => Math.max(0, Math.min(1, x));
  const lerp = (a, b, p) => a + (b - a) * p;
  const E = {
    lin: x => x,
    out: x => 1 - Math.pow(1 - x, 3),
    inout: x => (x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
    back: x => { const c1 = 1.7, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); },
  };
  const P = (t, start, dur, e = 'out') => E[e](clamp((t - start) / dur));
  const hex = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16));
  const mix = (a, b, p) => `rgb(${hex(a).map((v, i) => Math.round(lerp(v, hex(b)[i], p))).join(',')})`;

  const el = {
    stage: $('#stage'), content: $('.content'), motif: $('.motif'), brand: $('.a-brand'), loc: $('.loc'),
    kicker: $('.a-kicker'), headWrap: $('.head-wrap'), headline: $('.a-headline'), hook: $('.a-hook'), sub: $('.a-sub'),
    gauge: $('.a-gauge'), badge: $('.a-badge'), burst: $('.burst'), num: $('#gnum'), gnum: $('.g-num'),
    red: $('.ring .red'), prog: $('.ring .prog'), svcs: $$('.a-svc'),
    gift: $('.a-gift'), giftIcon: $('.a-gifticon'), cta: $('.a-cta'), btn: $('.a-btn'), shines: $$('.shine'),
  };

  // Intro placement: the gauge starts large, centred in the empty space under the headline,
  // then settles into its poster position. Measured once fonts have loaded, before any transform.
  window.animReady = document.fonts.ready.then(init);
  function init() {
  const W = innerWidth, H = innerHeight;
  const g = el.gauge.getBoundingClientRect();
  const headBottom = el.headWrap.getBoundingClientRect().bottom;
  const contentBottom = H - parseFloat(getComputedStyle(el.content).paddingBottom);
  const introCy = (headBottom + contentBottom) / 2;
  const introScale = Math.min(1.5, ((contentBottom - headBottom) * 0.78) / g.height);
  const dx = W / 2 - (g.left + g.width / 2);
  const dy = introCy - (g.top + g.height / 2);

  const set = (e, o, tf = '') => { e.style.opacity = o; e.style.transform = tf; };

  window.seek = function (t) {
    // ambient motion
    el.motif.style.transform = `translateY(${lerp(40, 0, t / DUR)}px)`;

    // 0.0–1.8  hook: "نسبة الاستلال عالية؟" with a red 47% gauge; the audience line shows from the start
    set(el.kicker, 1);
    const hookIn = P(t, 0, .35, 'out'), hookOut = P(t, 1.45, .4);
    set(el.hook, 1 - hookOut, `translateY(${-30 * hookOut}px) scale(${lerp(1.06, 1, hookIn)})`);
    const hIn = P(t, 1.6, .6, 'back');
    set(el.headline, P(t, 1.6, .35), `translateY(${lerp(40, 0, hIn)}px)`);

    // 1.7–3.3  count down 47% → 0%, then the yellow ring completes
    const down = P(t, 1.7, 1.6, 'inout');
    const v = BEFORE * (1 - down);
    el.num.textContent = Math.round(v);
    el.gnum.style.color = mix('#ff5d5d', '#fddb07', clamp(down * 1.2 - .2));
    el.red.style.strokeDashoffset = C * (1 - v / 100);
    el.red.style.opacity = t < 3.3 ? 1 : 0;
    el.prog.style.strokeDashoffset = C * (1 - P(t, 3.3, .6));
    const breathe = t > 4.6 ? .88 + .12 * Math.sin((t - 4.6) * 3) : 1;
    el.gauge.style.setProperty('--glow', P(t, 3.3, .6) * breathe);
    const b = P(t, 3.7, .45, 'back');
    set(el.badge, clamp(b * 3), `scale(${b})`);
    const bu = P(t, 3.3, .8);
    el.burst.style.opacity = t < 3.3 ? 0 : (1 - bu) * .9;
    el.burst.style.transform = `scale(${lerp(.95, 1.7, bu)})`;

    // gauge: alarm shake, zero pop, then settle into place (4.0–4.75)
    const move = P(t, 4.0, .75, 'inout');
    const shake = t > .2 && t < .9 ? Math.sin(t * 55) * 7 * (1 - (t - .2) / .7) : 0;
    const pop = t > 3.3 && t < 3.75 ? 1 + .1 * Math.sin(Math.PI * (t - 3.3) / .45) : 1;
    el.gauge.style.transform =
      `translate(${lerp(dx, 0, move) + shake}px, ${lerp(dy, 0, move)}px) scale(${lerp(introScale, 1, move) * pop})`;

    // 4.5–6.3  Turnitin line, services
    const s = P(t, 4.5, .5); set(el.sub, s, `translateY(${lerp(24, 0, s)}px)`);
    el.svcs.forEach((li, i) => {
      const p = P(t, 4.9 + i * .28, .5, 'back');
      set(li, clamp(p * 1.5), `translateX(${lerp(60, 0, p)}px)`);
    });

    // 6.4–7.9  free gift
    const gi = P(t, 6.4, .7, 'back');
    set(el.gift, clamp(gi * 1.6), `translateY(${lerp(120, 0, gi)}px) scale(${lerp(.92, 1, gi)})`);
    const w = t > 7.0 && t < 8.0 ? t - 7.0 : 0;
    el.giftIcon.style.transform =
      `rotate(${-6 + Math.sin(w * Math.PI * 4) * 12 * (1 - w)}deg) scale(${1 + .1 * Math.sin(w * Math.PI)})`;

    // 7.6–8.4  call to action, then a gentle pulse until the end
    const c = P(t, 7.6, .6, 'back'); set(el.cta, clamp(c * 1.6), `translateY(${lerp(80, 0, c)}px)`);
    const l = P(t, 7.9, .5); set(el.loc, l, `translateX(${lerp(-30, 0, l)}px)`);
    el.btn.style.transform = `scale(${t > 8.4 ? 1 + .05 * Math.max(0, Math.sin((t - 8.4) * Math.PI * 1.25)) : 1})`;

    // light sweeps across the gift card and the button (right → left, RTL)
    el.shines.forEach((sh, i) => {
      let x = -1;
      for (const s0 of i === 0 ? [7.3, 10.2, 12.6] : [8.9, 11.4, 13.2]) if (t >= s0 && t < s0 + .9) x = (t - s0) / .9;
      sh.style.opacity = x < 0 ? 0 : 1;
      sh.style.transform = `translateX(${lerp(130, -130, E.inout(Math.max(0, x)))}%)`;
    });
  };
  window.seek(0);
  }
})();
