/* <jarvis-head> — layered animated core.
   Attributes: activity="idle|listening|speaking", preset="classic|reactor|plasma|aurora", accent.
   Method: setLevel(0..1) for real audio amplitude. */
/* <matrix-rain> — subtle digit rain bg. Attributes: opacity. */
(() => {
const TAU = Math.PI * 2;
const C = (rgb, a) => `rgba(${rgb[0] | 0},${rgb[1] | 0},${rgb[2] | 0},${Math.max(0, Math.min(1, a))})`;
const LERP = (a, b, m) => [a[0] + (b[0] - a[0]) * m, a[1] + (b[1] - a[1]) * m, a[2] + (b[2] - a[2]) * m];
const CYAN = [80, 205, 255], ICE = [160, 235, 255], VIOLET = [185, 120, 255], MAGENTA = [255, 120, 220],
      GOLD = [255, 200, 100], WHITE = [255, 248, 235], MINT = [110, 255, 190], TEAL = [70, 230, 235];
function fib(n) {
  const pts = [], ga = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < n; i++) {
    const y = 1 - (i / (n - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i;
    pts.push([Math.cos(th) * r, y, Math.sin(th) * r, (i * 0.618034) % 1]);
  }
  return pts;
}
class JarvisHead extends HTMLElement {
  connectedCallback() {
    this.style.cssText = 'display:block;width:100%;height:100%';
    this.canvas = document.createElement('canvas');
    this.canvas.style.cssText = 'width:100%;height:100%;display:block';
    this.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this.t = 0; this.level = 0; this._extLevel = null;
    this.pts = fib(760);
    this.halo = Array.from({ length: 340 }, () => ({
      a: Math.random() * TAU, r: 0.88 + Math.random() * 0.22,
      s: (Math.random() - 0.5) * 0.0016, p: Math.random() * TAU,
      f: 0.4 + Math.random() * 1.2, sz: Math.random() < 0.85 ? 1 : 2, al: 0.25 + Math.random() * 0.55, m: Math.random()
    }));
    this.arcs = Array.from({ length: 4 }, (_, i) => ({
      r: [0.62, 0.9, 0.97, 1.04][i], a: Math.random() * TAU,
      span: 0.5 + Math.random() * 1.1, s: (i % 2 ? -1 : 1) * (0.002 + Math.random() * 0.003), w: i === 1 ? 2 : 1.2
    }));
    this._resize = () => {
      const dpr = Math.min(devicePixelRatio || 1, 2);
      this.canvas.width = this.clientWidth * dpr; this.canvas.height = this.clientHeight * dpr;
      this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      this.W = this.clientWidth; this.H = this.clientHeight;
    };
    this._resize();
    this._ro = new ResizeObserver(this._resize); this._ro.observe(this);
    this._raf = requestAnimationFrame(this._tick = this._tick.bind(this));
  }
  disconnectedCallback() { cancelAnimationFrame(this._raf); this._ro && this._ro.disconnect(); }
  setLevel(v) { this._extLevel = Math.max(0, Math.min(1, v)); }
  _sim() {
    const act = this.getAttribute('activity') || 'idle', t = this.t;
    if (this._extLevel != null) return this._extLevel;
    if (act === 'speaking') {
      const syll = Math.max(0, Math.sin(t * 9) * Math.sin(t * 2.3 + 1) + Math.sin(t * 17) * 0.3);
      return 0.25 + Math.min(1, syll) * 0.75;
    }
    if (act === 'listening') return 0.2 + 0.12 * Math.sin(t * 1.4) + 0.06 * Math.sin(t * 4.7);
    return 0.12 + 0.07 * Math.sin(t * 0.9) + 0.04 * Math.sin(t * 2.1 + 2);
  }
  _pal() {
    const p = this.getAttribute('preset') || 'classic', t = this.t;
    if (p === 'reactor') return {
      add: true, spd: 1.3, int: 1.45, coreIn: WHITE, core: ICE, ring: [120, 220, 255], sweep: GOLD,
      halo: f => LERP(ICE, GOLD, f * 0.5), tick1: [110, 215, 255], tick2: [255, 228, 170],
      arc: i => (i % 2 ? GOLD : ICE), sph: f => LERP([150, 230, 255], WHITE, f * f),
    };
    if (p === 'plasma') return {
      add: true, spd: 1.2, int: 1.4, coreIn: [235, 200, 255], core: [150, 130, 255], ring: [170, 130, 255], sweep: MAGENTA,
      halo: f => LERP(CYAN, MAGENTA, f), tick1: [120, 160, 255], tick2: [235, 150, 255],
      arc: i => (i % 2 ? [130, 220, 255] : VIOLET), sph: f => LERP(CYAN, VIOLET, f),
    };
    if (p === 'aurora') {
      const m = 0.5 + 0.5 * Math.sin(t * 0.25), g2 = LERP(TEAL, MINT, m);
      return {
        add: true, spd: 1, int: 1.3, coreIn: [220, 255, 240], core: LERP(CYAN, MINT, m), ring: g2, sweep: MINT,
        halo: f => LERP(CYAN, g2, f), tick1: LERP([90, 200, 255], TEAL, m), tick2: LERP(ICE, MINT, m),
        arc: i => (i % 2 ? MINT : ICE), sph: f => LERP(CYAN, LERP(ICE, MINT, m), f),
      };
    }
    return {
      add: true, spd: 1.05, int: 1.15, coreIn: [210, 245, 255], core: CYAN, ring: [110, 215, 255], sweep: ICE,
      halo: () => [140, 225, 255], tick1: [90, 200, 255], tick2: [150, 230, 255],
      arc: () => [160, 230, 255], sph: f => LERP([140, 215, 255], [230, 255, 255], f * f),
    };
  }
  _tick() {
    this._raf = requestAnimationFrame(this._tick);
    if (document.hidden) return;
    const P = this._pal();
    this.t += (1 / 60) * P.spd;
    this.level += (this._sim() - this.level) * 0.18;
    const { ctx, W, H, t } = this, L = this.level, I = P.int;
    if (!W || !H) return;
    ctx.clearRect(0, 0, W, H);
    if (P.add) ctx.globalCompositeOperation = 'lighter';
    const cx = W / 2, cy = H / 2;
    const R = Math.min(W, H) * 0.36 * (1 + L * 0.035);
    // 1. core glow
    let g = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 1.45);
    g.addColorStop(0, C(P.core, (0.26 + L * 0.3) * I));
    g.addColorStop(0.45, C(P.core, (0.10 + L * 0.11) * I));
    g.addColorStop(1, C(P.core, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R * 1.5, 0, TAU); ctx.fill();
    // 2. rotating sweep beam
    const sa = t * 0.5;
    g = ctx.createConicGradient ? ctx.createConicGradient(sa, cx, cy) : null;
    if (g) {
      g.addColorStop(0, C(P.sweep, 0));
      g.addColorStop(0.06, C(P.sweep, (0.10 + L * 0.14) * I));
      g.addColorStop(0.12, C(P.sweep, 0));
      g.addColorStop(1, C(P.sweep, 0));
      ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, R * 1.12, 0, TAU); ctx.fill();
    }
    // 3. wobbling energy rings
    ctx.lineWidth = 1.2;
    for (let k = 0; k < 3; k++) {
      ctx.beginPath();
      const base = R * (0.96 + k * 0.07), amp = R * (0.018 + k * 0.012) * (1 + L * 1.8);
      for (let i = 0; i <= 140; i++) {
        const a = (i / 140) * TAU;
        const n = Math.sin(a * (3 + k) + t * (0.7 + k * 0.3)) + 0.6 * Math.sin(a * (7 + k * 2) - t * (1.1 + k * 0.2));
        const r = base + n * amp;
        i ? ctx.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r) : ctx.moveTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
      }
      ctx.closePath();
      ctx.strokeStyle = C(P.ring, (0.30 - k * 0.06 + L * 0.18) * I);
      ctx.stroke();
    }
    // 4. halo particles
    for (const p of this.halo) {
      p.a += p.s * (1 + L * 1.8) * P.spd;
      const r = R * p.r * (1 + 0.05 * Math.sin(t * p.f + p.p) * (1 + L));
      ctx.fillStyle = C(P.halo(p.m), p.al * (0.55 + L * 0.6) * I);
      ctx.fillRect(cx + Math.cos(p.a) * r, cy + Math.sin(p.a) * r, p.sz, p.sz);
    }
    // 5. segmented tick rings
    this._ticks(cx, cy, R * 0.80, R * 0.87, 96, t * 0.10, C(P.tick1, (0.45 + L * 0.3) * I), 0.6);
    this._ticks(cx, cy, R * 0.70, R * 0.745, 64, -t * 0.16, C(P.tick2, (0.62 + L * 0.3) * I), 0.45);
    ctx.lineWidth = 1;
    for (const rr of [0.795, 0.875, 0.695, 0.75]) {
      ctx.beginPath(); ctx.arc(cx, cy, R * rr, 0, TAU);
      ctx.strokeStyle = C(P.ring, 0.22 * I); ctx.stroke();
    }
    // 6. rotating arcs
    this.arcs.forEach((a, i) => {
      a.a += a.s * (1 + L) * P.spd;
      const col = P.arc(i);
      ctx.beginPath(); ctx.arc(cx, cy, R * a.r, a.a, a.a + a.span);
      ctx.lineWidth = a.w; ctx.strokeStyle = C(col, (0.55 + L * 0.4) * I);
      ctx.shadowColor = C(col, 1); ctx.shadowBlur = 14; ctx.stroke(); ctx.shadowBlur = 0;
    });
    // 7. inner particle sphere
    const SR = R * 0.545, ry = t * 0.22, rx = 0.35 + Math.sin(t * 0.1) * 0.12;
    const sy = Math.sin(ry), cyr = Math.cos(ry), sx = Math.sin(rx), cxr = Math.cos(rx);
    ctx.lineWidth = 1;
    for (let k = 0; k < 4; k++) {
      const ph = ry * 1.4 + (k * Math.PI) / 4, sq = Math.abs(Math.cos(ph));
      ctx.beginPath(); ctx.ellipse(cx, cy, SR * sq, SR, 0, 0, TAU);
      ctx.strokeStyle = C(P.ring, (0.07 + 0.06 * sq) * I); ctx.stroke();
    }
    ctx.beginPath(); ctx.ellipse(cx, cy, SR, SR * Math.abs(sx) * 0.9, 0, 0, TAU);
    ctx.strokeStyle = C(P.ring, 0.12 * I); ctx.stroke();
    for (const [px, py, pz, m] of this.pts) {
      let x = px * cyr + pz * sy, z = -px * sy + pz * cyr, y = py;
      let y2 = y * cxr - z * sx; z = y * sx + z * cxr;
      const persp = 1 / (1 + z * 0.28);
      const front = (1 - z) / 2;
      const col = P.sph(P.add && P.halo ? Math.min(1, front * 0.6 + m * 0.4) : front);
      ctx.fillStyle = C(col, (0.12 + front * front * (0.75 + L * 0.45)) * I);
      ctx.fillRect(cx + x * SR * persp, cy + y2 * SR * persp, front > 0.82 ? 2 : 1, front > 0.82 ? 2 : 1);
    }
    // 8. bright inner core
    g = ctx.createRadialGradient(cx, cy, 0, cx, cy, SR * 0.5);
    g.addColorStop(0, C(P.coreIn, (0.18 + L * 0.32) * I));
    g.addColorStop(1, C(P.core, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, SR * 0.5, 0, TAU); ctx.fill();
    ctx.globalCompositeOperation = 'source-over';
  }
  _ticks(cx, cy, r0, r1, n, rot, color, fill) {
    const { ctx } = this;
    ctx.strokeStyle = color; ctx.lineWidth = ((r1 - r0) * Math.PI * 2) / n * fill * 0.9;
    for (let i = 0; i < n; i++) {
      const a = rot + (i / n) * TAU, ca = Math.cos(a), saa = Math.sin(a);
      ctx.beginPath();
      ctx.moveTo(cx + ca * r0, cy + saa * r0);
      ctx.lineTo(cx + ca * r1, cy + saa * r1);
      ctx.stroke();
    }
  }
}
class MatrixRain extends HTMLElement {
  connectedCallback() {
    this.style.cssText = 'display:block;width:100%;height:100%';
    this.canvas = document.createElement('canvas');
    this.canvas.style.cssText = 'width:100%;height:100%;display:block';
    this.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this._resize = () => {
      this.canvas.width = this.clientWidth; this.canvas.height = this.clientHeight;
      this.cols = Math.ceil(this.clientWidth / 28);
      this.drops = Array.from({ length: this.cols }, () => ({ y: Math.random() * this.clientHeight, s: 0.4 + Math.random() * 1.1 }));
    };
    this._resize();
    this._ro = new ResizeObserver(this._resize); this._ro.observe(this);
    this._frame = 0;
    this._raf = requestAnimationFrame(this._tick = this._tick.bind(this));
  }
  disconnectedCallback() { cancelAnimationFrame(this._raf); this._ro && this._ro.disconnect(); }
  _tick() {
    this._raf = requestAnimationFrame(this._tick);
    if (document.hidden || this._frame++ % 3) return;
    const { ctx, canvas } = this, op = parseFloat(this.getAttribute('opacity') || '0.10');
    ctx.fillStyle = 'rgba(4,8,14,0.22)'; ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.font = '13px ui-monospace,monospace';
    for (let i = 0; i < this.cols; i++) {
      const d = this.drops[i];
      ctx.fillStyle = `rgba(110,205,255,${op * (0.5 + Math.random() * 0.5)})`;
      ctx.fillText(String((Math.random() * 10) | 0), i * 28 + 8, d.y);
      d.y += d.s * 14;
      if (d.y > canvas.height + 20) { d.y = -20; d.s = 0.4 + Math.random() * 1.1; }
    }
  }
}
customElements.define('jarvis-head', JarvisHead);
customElements.define('matrix-rain', MatrixRain);
})();
