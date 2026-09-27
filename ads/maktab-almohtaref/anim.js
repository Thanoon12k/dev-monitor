// Video mode (?v=1): a deterministic timeline. window.seek(t) draws the frame at t seconds,
// so the renderer can capture exact frames. Without ?v the page stays a static poster.
// Timing follows the soundtrack: 128 BPM, 8 bars = 15 s (see audio.py, which uses the same cues).
(function () {
  const q = new URLSearchParams(location.search);
  if (!q.get('v')) return;
  const B = 60 / 128, bar = k => (k - 1) * 4 * B, DUR = bar(9), C = 540.35;
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
  const set = (e, o, tf = '') => { e.style.opacity = o; e.style.transform = tf; };

  const el = {
    content: $('.content'), motif: $('.motif'), loc: $('.loc'), kicker: $('.a-kicker'),
    headWrap: $('.head-wrap'), headline: $('.a-headline'), hook: $('.a-hook'), sub: $('.a-sub'), meters: $('.meters'),
    gauges: $$('.a-gauge').map(g => ({
      root: g, red: g.querySelector('.ring .red'), prog: g.querySelector('.ring .prog'), badge: g.querySelector('.a-badge'),
      burst: g.querySelector('.burst'), before: g.querySelector('.a-before'), num: g.querySelector('.g-num'),
      n: g.querySelector('.n'), from: +g.querySelector('.n').dataset.before, to: +g.querySelector('.n').dataset.after,
    })),
    svcs: $$('.a-svc'), gift: $('.a-gift'), giftIcon: $('.a-gifticon'), cta: $('.a-cta'), btn: $('.a-btn'), shines: $$('.shine'),
  };

  window.animReady = document.fonts.ready.then(init);
  function init() {
    // Intro placement: both meters start large, centred in the space under the hook, then settle
    // into their poster position. Measured once fonts have loaded, before any transform.
    const H = innerHeight, m = el.meters.getBoundingClientRect();
    const hookBottom = Math.max(el.headWrap.getBoundingClientRect().bottom, el.hook.getBoundingClientRect().bottom);
    const contentBottom = H - parseFloat(getComputedStyle(el.content).paddingBottom);
    const introScale = Math.min(1.4, ((contentBottom - hookBottom) * 0.8) / m.height, 940 / m.width);
    const dy = (hookBottom + contentBottom) / 2 - (m.top + m.height / 2);

    window.seek = function (t) {
      el.motif.style.transform = `translateY(${lerp(40, 0, t / DUR)}px)`;
      set(el.kicker, 1);

      // bars 1–2: hook "نسبة الاستلال والذكاء عالية؟" over two red meters, then the headline
      const hookOut = P(t, bar(2) - .1, .35);
      set(el.hook, 1 - hookOut, `translateY(${-30 * hookOut}px) scale(${lerp(1.06, 1, P(t, 0, .3))})`);
      set(el.headline, P(t, bar(2), .3), `translateY(${lerp(40, 0, P(t, bar(2), .5, 'back'))}px)`);

      // countdown to the reduced values, landing on the downbeat of bar 3
      const down = P(t, 2.05, 1.55, 'inout');
      const hit = bar(3);
      el.gauges.forEach((g, i) => {
        const v = lerp(g.from, g.to, down);
        g.n.textContent = Math.round(v);
        g.num.style.color = mix('#ff5d5d', '#fddb07', clamp(down * 1.4 - .4));
        g.red.style.strokeDashoffset = C * (1 - v / 100);
        g.red.style.opacity = t < hit ? 1 : 0;
        g.prog.style.strokeDashoffset = C * (1 - P(t, hit, .55));
        const breathe = t > 5.2 ? .88 + .12 * Math.sin((t - 5.2) * 3 + i) : 1;
        g.root.style.setProperty('--glow', P(t, hit, .6) * breathe);
        const bu = P(t, hit, .8);
        g.burst.style.opacity = t < hit ? 0 : (1 - bu) * .9;
        g.burst.style.transform = `scale(${lerp(.95, 1.6, bu)})`;
        const b = P(t, hit + .2 + i * .12, .4, 'back');
        set(g.badge, clamp(b * 3), `scale(${b})`);
        const bf = P(t, hit + .15, .4);
        set(g.before, bf, `translateY(${lerp(10, 0, bf)}px)`);
        const shake = t > .12 && t < .8 ? Math.sin(t * 55 + i * 2) * 6 * (1 - (t - .12) / .68) : 0;
        const pop = t > hit && t < hit + .45 ? 1 + .1 * Math.sin(Math.PI * (t - hit) / .45) : 1;
        g.root.style.transform = `translateX(${shake}px) scale(${pop})`;
      });
      const move = P(t, 4.45, .75, 'inout');
      el.meters.style.transform = `translateY(${lerp(dy, 0, move)}px) scale(${lerp(introScale, 1, move)})`;

      // bar 3–4: Turnitin line, then the four service chips on eighth notes
      const s = P(t, 4.9, .45); set(el.sub, s, `translateY(${lerp(24, 0, s)}px)`);
      el.svcs.forEach((li, i) => {
        const p = P(t, bar(4) + i * B / 2, .45, 'back');
        set(li, clamp(p * 1.5), `translateY(${lerp(30, 0, p)}px) scale(${lerp(.8, 1, p)})`);
      });

      // bar 5: the free gift
      const gi = P(t, bar(5), .7, 'back');
      set(el.gift, clamp(gi * 1.6), `translateY(${lerp(120, 0, gi)}px) scale(${lerp(.92, 1, gi)})`);
      const w = t > bar(5) + .5 && t < bar(5) + 1.5 ? t - bar(5) - .5 : 0;
      el.giftIcon.style.transform =
        `rotate(${-6 + Math.sin(w * Math.PI * 4) * 12 * (1 - w)}deg) scale(${1 + .1 * Math.sin(w * Math.PI)})`;

      // bar 6: call to action, then the button pulses every second beat
      const c = P(t, bar(6), .6, 'back'); set(el.cta, clamp(c * 1.6), `translateY(${lerp(80, 0, c)}px)`);
      const l = P(t, bar(6) + .25, .5); set(el.loc, l, `translateX(${lerp(-30, 0, l)}px)`);
      const T0 = bar(6) + 2 * B, ph = (t - T0) % (2 * B);
      const bump = t > T0 ? Math.exp(-ph / .18) * (1 - Math.exp(-ph / .02)) : 0;
      el.btn.style.transform = `scale(${1 + .06 * bump})`;

      // light sweeps across the gift card and the button (right → left, RTL)
      el.shines.forEach((sh, i) => {
        let x = -1;
        for (const s0 of i === 0 ? [8.2, bar(7), 13.6] : [10.3, 12.2, 14.1]) if (t >= s0 && t < s0 + .9) x = (t - s0) / .9;
        sh.style.opacity = x < 0 ? 0 : 1;
        sh.style.transform = `translateX(${lerp(130, -130, E.inout(Math.max(0, x)))}%)`;
      });
    };
    window.seek(0);
  }
})();
