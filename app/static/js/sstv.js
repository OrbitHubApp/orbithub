/*
 * OrbitHub SSTV-Decoder (laeuft komplett im Browser)
 *
 * Eingang: Audio-Samples (Float32, beliebige Abtastrate, z. B. 48 kHz) vom
 * IC-705-Stream. Ablauf:
 *   1. FM-Demodulation: Mischung auf 1900 Hz, Tiefpass, Dezimierung auf
 *      ca. 12 kHz, Momentanfrequenz aus der Phasendifferenz.
 *   2. VIS-Erkennung (Leader 1900 Hz, Startbit 1200 Hz, 7 Datenbits + Paritaet)
 *      -> Betriebsart.
 *   3. Zeilenweise Dekodierung; jede Zeile sucht ihren Sync-Impuls, eine
 *      Ausgleichsgerade ueber alle gefundenen Syncs korrigiert Versatz und
 *      Schraeglauf (Taktabweichung).
 *
 * Unterstuetzt: Robot 36/72, PD 50/90/120/160/180/240/290, Martin M1/M2,
 * Scottie S1/S2/DX. Kann auch ohne VIS mit fester Betriebsart starten.
 */
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- Modi --
  // Zeiten in Millisekunden. off = Beginn innerhalb der Zeile (ab Zeilenursprung).
  function rgbMartin(name, vis, scan) {
    var g = 4.862 + 0.572, b = g + scan + 0.572, r = b + scan + 0.572;
    return { name: name, vis: vis, w: 320, h: 256, family: "rgb", start: 0,
      period: r + scan + 0.572, sync: { off: 0, len: 4.862 },
      chans: [{ k: "G", off: g, len: scan }, { k: "B", off: b, len: scan }, { k: "R", off: r, len: scan }] };
  }
  function rgbScottie(name, vis, scan) {
    var g = 1.5, b = g + scan + 1.5, s = b + scan, r = s + 9 + 1.5;
    return { name: name, vis: vis, w: 320, h: 256, family: "rgb", start: 9,
      period: r + scan, sync: { off: s, len: 9 },
      chans: [{ k: "G", off: g, len: scan }, { k: "B", off: b, len: scan }, { k: "R", off: r, len: scan }] };
  }
  function pd(name, vis, w, h, t) {
    var o = 20 + 2.08;
    return { name: name, vis: vis, w: w, h: h, family: "pd", start: 0,
      period: o + 4 * t, sync: { off: 0, len: 20 },
      chans: [{ k: "Y0", off: o, len: t }, { k: "V", off: o + t, len: t },
              { k: "U", off: o + 2 * t, len: t }, { k: "Y1", off: o + 3 * t, len: t }] };
  }
  var MODES = [
    { name: "Robot 36", vis: 8, w: 320, h: 240, family: "robot36", start: 0, period: 150,
      sync: { off: 0, len: 9 }, sep: { off: 100, len: 4.5 },
      chans: [{ k: "Y", off: 12, len: 88 }, { k: "C", off: 106, len: 44 }] },
    { name: "Robot 72", vis: 12, w: 320, h: 240, family: "yuv", start: 0, period: 300,
      sync: { off: 0, len: 9 },
      chans: [{ k: "Y", off: 12, len: 138 }, { k: "V", off: 156, len: 69 }, { k: "U", off: 231, len: 69 }] },
    pd("PD 50", 93, 320, 256, 91.52),
    pd("PD 90", 99, 320, 256, 170.24),
    pd("PD 120", 95, 640, 496, 121.6),
    pd("PD 160", 98, 512, 400, 195.584),
    pd("PD 180", 96, 640, 496, 183.04),
    pd("PD 240", 97, 640, 496, 244.48),
    pd("PD 290", 94, 800, 616, 228.8),
    rgbMartin("Martin M1", 44, 146.432),
    rgbMartin("Martin M2", 40, 73.216),
    rgbScottie("Scottie S1", 60, 138.24),
    rgbScottie("Scottie S2", 56, 88.064),
    rgbScottie("Scottie DX", 76, 345.6)
  ];
  MODES.forEach(function (m) { m.scans = m.family === "pd" ? m.h / 2 : m.h; });
  var BY_VIS = {}, BY_NAME = {};
  MODES.forEach(function (m) { BY_VIS[m.vis] = m; BY_NAME[m.name] = m; });

  var SYNC_THRESH = 1350;   // Hz: darunter = Sync (1200), darueber = Bild (>= 1500)

  // ------------------------------------------------------------- Decoder --
  function Decoder(sampleRate, opts) {
    opts = opts || {};
    this.fs = sampleRate;
    this.D = Math.max(1, Math.round(sampleRate / 12000));
    this.R = sampleRate / this.D;                    // Rate des Frequenzstroms
    this.onEvent = opts.onEvent || function () {};
    // Tiefpass (Hamming-gefenstertes sinc), Grenzfrequenz 1100 Hz
    var n = Math.round(sampleRate * 0.0022) | 1, fc = 1100 / sampleRate, taps = new Float32Array(n), sum = 0;
    for (var i = 0; i < n; i++) {
      var x = i - (n - 1) / 2;
      var s = x === 0 ? 2 * fc : Math.sin(2 * Math.PI * fc * x) / (Math.PI * x);
      taps[i] = s * (0.54 - 0.46 * Math.cos(2 * Math.PI * i / (n - 1)));
      sum += taps[i];
    }
    for (i = 0; i < n; i++) { taps[i] /= sum; }
    this.taps = taps; this.nt = n;
    this.bi = new Float32Array(2 * n); this.bq = new Float32Array(2 * n); this.bp = 0;
    this.ph = 0; this.dph = 2 * Math.PI * 1900 / sampleRate;
    this.dc = 0; this.pi = 1; this.pq = 0;
    // Verlauf des Frequenzstroms (fuer VIS-Rueckgriff), 4 s
    this.H = Math.ceil(this.R * 4);
    this.hist = new Float32Array(this.H);
    this.n = 0;                                       // Zaehler Frequenzwerte
    // Millisekunden-Mittel fuer die VIS-Suche
    this.msRing = new Float32Array(2048); this.ms = 0; this.msAcc = 0; this.msCnt = 0;
    this.level = 0;
    this.reset();
  }

  Decoder.prototype.reset = function () {
    this.state = "hunt";
    this.mode = null;
    this.img = null;
  };

  Decoder.prototype.currentTone = function () {
    // mittlere Tonfrequenz der letzten 20 ms
    var a = 0, c = 0;
    for (var i = 1; i <= 20 && i <= this.ms; i++) { a += this.msRing[(this.ms - i) & 2047]; c++; }
    return c ? a / c : 0;
  };

  Decoder.prototype.process = function (x) {
    var nt = this.nt, taps = this.taps, bi = this.bi, bq = this.bq, D = this.D, k2pi = this.R / (2 * Math.PI);
    var lev = this.level;
    for (var j = 0; j < x.length; j++) {
      var v = x[j];
      lev += (v * v - lev) * 0.0005;
      var p = this.bp;
      bi[p] = bi[p + nt] = v * Math.cos(this.ph);
      bq[p] = bq[p + nt] = -v * Math.sin(this.ph);
      this.bp = p + 1 === nt ? 0 : p + 1;
      this.ph += this.dph; if (this.ph > 6.283185307179586) { this.ph -= 6.283185307179586; }
      if (++this.dc < D) { continue; }
      this.dc = 0;
      var I = 0, Q = 0, o = this.bp;
      for (var t = 0; t < nt; t++) { I += taps[t] * bi[o + t]; Q += taps[t] * bq[o + t]; }
      var re = I * this.pi + Q * this.pq, im = Q * this.pi - I * this.pq;
      this.pi = I; this.pq = Q;
      var f = 1900 + Math.atan2(im, re) * k2pi;
      if (f < 1000) { f = 1000; } else if (f > 2600) { f = 2600; }
      this._push(f);
    }
    this.level = lev;
  };

  Decoder.prototype._push = function (f) {
    var n = this.n;
    this.hist[n % this.H] = f;
    this.n = n + 1;
    if (this.img) { this._imgPush(f); }
    this.msAcc += f; this.msCnt++;
    var msNow = Math.floor(this.n * 1000 / this.R);
    if (msNow > this.ms) {
      this.msRing[this.ms & 2047] = this.msAcc / this.msCnt;
      this.ms = msNow; this.msAcc = 0; this.msCnt = 0;
      if (this.state === "hunt") { this._checkVis(); }
      else if (this.state === "decode" && (this.ms % 100) === 0) { this._advance(false); }
    }
  };

  Decoder.prototype._msMean = function (a, b) {
    var s = 0;
    for (var i = a; i < b; i++) { s += this.msRing[i & 2047]; }
    return s / (b - a);
  };

  Decoder.prototype._checkVis = function () {
    var s = this.ms - 301;                 // Kandidat: Beginn des Startbits (ms)
    if (s < 280) { return; }
    var r = this.msRing, i, good = 0;
    var st = this._msMean(s + 4, s + 26);
    if (Math.abs(st - 1200) > 90) { return; }
    var sp = this._msMean(s + 274, s + 296);
    if (Math.abs(sp - 1200) > 90) { return; }
    for (i = s - 260; i < s - 10; i++) { if (Math.abs(r[i & 2047] - 1900) < 110) { good++; } }
    if (good < 160) { return; }
    var code = 0, ones = 0;
    for (var b = 0; b < 8; b++) {
      var m = this._msMean(s + 34 + 30 * b, s + 56 + 30 * b);
      var one;
      if (Math.abs(m - 1100) < 90) { one = 1; } else if (Math.abs(m - 1300) < 90) { one = 0; } else { return; }
      if (b < 7) { code |= one << b; }
      ones += one;
    }
    if (ones % 2 !== 0) { return; }            // gerade Paritaet
    var mode = BY_VIS[code];
    if (!mode) { this.onEvent({ type: "vis-unknown", code: code }); return; }
    // Flanke 1900 -> 1200 Hz am Startbit fein suchen (im Frequenzstrom)
    var R = this.R, w = Math.round(R * 0.002), c0 = Math.round(s * R / 1000), best = -1e9, edge = c0;
    for (var e = c0 - Math.round(R * 0.006); e <= c0 + Math.round(R * 0.006); e++) {
      var d = this._histMean(e - w, e) - this._histMean(e, e + w);
      if (d > best) { best = d; edge = e; }
    }
    this.startDecode(mode, edge + 0.3 * R, true);
  };

  Decoder.prototype._histMean = function (a, b) {
    var s = 0, H = this.H;
    for (var i = a; i < b; i++) { s += this.hist[((i % H) + H) % H]; }
    return s / (b - a);
  };

  // Bild beginnen. t0 = Index im Frequenzstrom, an dem der erste Zeilenblock
  // beginnt (nach dem VIS). Ohne VIS: t0 = jetzt, erste Sync wird breit gesucht.
  Decoder.prototype.startDecode = function (mode, t0, fromVis) {
    if (typeof mode === "string") { mode = BY_NAME[mode]; }
    if (!mode) { return; }
    var R = this.R;
    if (t0 === undefined) { t0 = this.n; }
    var margin = Math.round(R * 0.05);
    var total = Math.ceil((mode.start + mode.period * (mode.scans + 1)) * R / 1000) + 2 * margin;
    var base = Math.max(0, Math.floor(t0) - margin, this.n - this.H + 1);
    var img = {
      base: base, len: 0, cap: total,
      f: new Float32Array(total), pf: new Float64Array(total + 1), ps: new Float64Array(total + 1),
      rgba: new Uint8ClampedArray(mode.w * mode.h * 4),
      syncs: [], next: 0, fitA: 0, fitB: 0, lastSyncScan: -1, wide: !fromVis,
      started: Date.now(), fromVis: !!fromVis
    };
    for (var i = 0; i < img.rgba.length; i += 4) { img.rgba[i + 3] = 255; }
    this.mode = mode;
    this.img = img;
    this.state = "decode";
    this.spms = R / 1000;
    img.nomA = t0 + (mode.start + mode.sync.off) * this.spms;   // Sync-Position Zeile 0
    img.nomB = mode.period * this.spms;
    img.fitA = img.nomA; img.fitB = img.nomB;
    for (var k = base; k < this.n; k++) { this._imgPush(this.hist[k % this.H]); }
    this.onEvent({ type: "start", mode: mode, fromVis: !!fromVis });
  };

  Decoder.prototype._imgPush = function (f) {
    var im = this.img;
    if (im.len >= im.cap) { return; }
    var i = im.len;
    im.f[i] = f;
    im.pf[i + 1] = im.pf[i] + f;
    im.ps[i + 1] = im.ps[i] + (f < SYNC_THRESH ? 1 : 0);
    im.len = i + 1;
  };

  // Mittelwert ueber [a, b) mit gebrochenen Indizes (absolut im Frequenzstrom)
  function prefixAt(im, arr, x) {
    x -= im.base;
    if (x <= 0) { return 0; }
    if (x >= im.len) { return arr[im.len]; }
    var i = Math.floor(x);
    return arr[i] + (arr[i + 1] - arr[i]) * (x - i);
  }
  function meanF(im, a, b) {
    if (b - a < 1e-6) { b = a + 1e-6; }
    return (prefixAt(im, im.pf, b) - prefixAt(im, im.pf, a)) / (b - a);
  }
  function meanS(im, a, b) {
    return (prefixAt(im, im.ps, b) - prefixAt(im, im.ps, a)) / (b - a);
  }

  Decoder.prototype._syncScore = function (p, L) {
    var im = this.img, e = Math.max(this.spms * 1.5, L * 0.3);
    return meanS(im, p, p + L) - 0.5 * (meanS(im, p - e, p) + meanS(im, p + L, p + L + e));
  };

  Decoder.prototype._fit = function () {
    var im = this.img, pts = im.syncs, spms = this.spms;
    if (!pts.length) { return; }
    var A, B = im.nomB, used = pts.slice();
    for (var iter = 0; iter < 3; iter++) {
      if (used.length >= 3 && used[used.length - 1].k - used[0].k >= 4) {
        var n = used.length, sk = 0, sp = 0, skk = 0, skp = 0;
        used.forEach(function (q) { sk += q.k; sp += q.p; skk += q.k * q.k; skp += q.k * q.p; });
        B = (n * skp - sk * sp) / (n * skk - sk * sk);
        if (Math.abs(B / im.nomB - 1) > 0.006) { B = im.nomB; }
        A = (sp - B * sk) / n;
      } else {
        // Median-Versatz bei Nennperiode
        var offs = used.map(function (q) { return q.p - q.k * B; }).sort(function (a, b) { return a - b; });
        A = offs[Math.floor(offs.length / 2)];
      }
      var keep = used.filter(function (q) { return Math.abs(q.p - (A + B * q.k)) < 1.5 * spms; });
      if (keep.length === used.length || keep.length < 2) { break; }
      used = keep;
    }
    im.fitA = A; im.fitB = B;
  };

  // Neue vollstaendige Zeilen verarbeiten. final = Bild abschliessen.
  Decoder.prototype._advance = function (final) {
    var im = this.img, m = this.mode, spms = this.spms;
    if (!im) { return; }
    var L = m.sync.len * spms, end = im.base + im.len, changed = false, from = im.next, full = false;
    while (im.next < m.scans) {
      var k = im.next;
      var pred = im.fitA + im.fitB * k;
      var win = im.wide && !im.syncs.length ? im.nomB : Math.max(6 * spms, 0.004 * im.fitB);
      var scanEnd = pred - m.sync.off * spms + im.fitB + win;
      if (scanEnd > end) { break; }
      var best = -1, bestP = pred, step = Math.max(1, Math.round(spms * 0.25));
      for (var p = pred - win; p <= pred + win; p += (im.wide && !im.syncs.length ? step : 1)) {
        var sc = this._syncScore(p, L);
        if (sc > best) { best = sc; bestP = p; }
      }
      if (best > 0.45) {
        if (im.wide && !im.syncs.length) {
          // erste Sync ohne VIS: Ursprung so legen, dass hier Zeile 0 beginnt
          im.nomA = bestP; im.fitA = bestP;
        }
        im.syncs.push({ k: k, p: bestP, s: best });
        im.lastSyncScan = k;
        this._fit();
        if ([1, 4, 10, 30, 80].indexOf(im.syncs.length) >= 0) { full = true; }
      }
      im.next++;
      changed = true;
    }
    // Signal weg? -> nach >= 8 s / 12 Zeilen ohne Sync abschliessen
    if (!final && im.next > 0) {
      var gap = im.next - 1 - im.lastSyncScan;
      if (gap * m.period > 8000 && gap >= 12) { final = true; this._endReason = "Signal verloren"; }
    }
    if (im.next >= m.scans) { final = true; if (!this._endReason) { this._endReason = "vollständig"; } }
    if (changed && !final) { this.render(full ? 0 : from); }
    if (final) { this.finish(this._endReason || "beendet"); }
    else if (changed) { this.onEvent({ type: "progress", lines: this.linesDone(), total: m.h }); }
  };

  Decoder.prototype.linesDone = function () {
    if (!this.img) { return 0; }
    return Math.min(this.mode.h, this.mode.family === "pd" ? this.img.next * 2 : this.img.next);
  };

  Decoder.prototype.finish = function (reason) {
    if (this.state !== "decode") { return; }
    var im = this.img, m = this.mode;
    this._fit();
    this.render();
    var result = { mode: m, w: m.w, h: m.h, rgba: im.rgba, lines: this.linesDone(),
      syncs: im.syncs.length, scans: im.next, reason: reason, fromVis: im.fromVis,
      slant: im.fitB / im.nomB - 1 };
    this.state = "hunt";
    this.img = null;
    this._endReason = null;
    this.onEvent({ type: "done", result: result });
    return result;
  };

  Decoder.prototype.stop = function () { return this.state === "decode" ? this._advance(true) : null; };

  // Komplettes (bisheriges) Bild mit aktueller Ausgleichsgerade neu zeichnen
  Decoder.prototype.render = function (from) {
    var im = this.img, m = this.mode, spms = this.spms, w = m.w, out = im.rgba;
    var nScans = im.next, chans = m.chans;
    var rows = {}, k0 = Math.max(0, (from || 0) - 2), k1 = Math.max(0, (from || 0) - 1);
    function val(f) { var v = (f - 1500) * 0.31875; return v < 0 ? 0 : v > 255 ? 255 : v; }
    var row = function (o, ch) {
      var arr = new Float32Array(w), a = o + ch.off * spms, px = ch.len * spms / w;
      for (var x = 0; x < w; x++) { arr[x] = val(meanF(im, a + x * px, a + (x + 1) * px)); }
      return arr;
    };
    var chroma = [];   // Robot 36: pro Zeile {kind, data}
    for (var k = k0; k < nScans; k++) {
      var o = im.fitA + im.fitB * k - m.sync.off * spms;
      var d = {};
      for (var c = 0; c < chans.length; c++) { d[chans[c].k] = row(o, chans[c]); }
      if (m.family === "robot36") {
        var sepF = meanF(im, o + m.sep.off * spms, o + (m.sep.off + m.sep.len) * spms);
        var isU = sepF > 1900 ? true : sepF < 1900 ? false : (k % 2 === 1);
        chroma[k] = { u: isU, c: d.C };
      }
      rows[k] = d;
    }
    for (k = k1; k < nScans; k++) {
      d = rows[k];
      if (m.family === "rgb") {
        put(out, k, w, d.R, d.G, d.B);
      } else if (m.family === "pd") {
        if (2 * k + 1 >= m.h) { continue; }
        yuv(out, 2 * k, w, d.Y0, d.U, d.V);
        yuv(out, 2 * k + 1, w, d.Y1, d.U, d.V);
      } else if (m.family === "yuv") {
        yuv(out, k, w, d.Y, d.U, d.V);
      } else {
        var me = chroma[k], other = chroma[me.u ? k - 1 : k + 1] || chroma[me.u ? k + 1 : k - 1];
        var U = me.u ? me.c : other && other.u ? other.c : null;
        var V = !me.u ? me.c : other && !other.u ? other.c : null;
        yuv(out, k, w, d.Y, U, V);
      }
    }
  };

  function put(out, y, w, R, G, B) {
    var o = y * w * 4;
    for (var x = 0; x < w; x++, o += 4) { out[o] = R[x]; out[o + 1] = G[x]; out[o + 2] = B[x]; out[o + 3] = 255; }
  }
  // ITU-R BT.601 (Studio-Bereich), wie MMSSTV/slowrx
  function yuv(out, y, w, Y, U, V) {
    var o = y * w * 4;
    for (var x = 0; x < w; x++, o += 4) {
      var yy = 298.082 * (Y[x] - 16), u = U ? U[x] - 128 : 0, v = V ? V[x] - 128 : 0;
      out[o] = 0.003906 * (yy + 408.583 * v);
      out[o + 1] = 0.003906 * (yy - 100.291 * u - 208.12 * v);
      out[o + 2] = 0.003906 * (yy + 516.411 * u);
      out[o + 3] = 255;
    }
  }

  var api = { Decoder: Decoder, MODES: MODES, byName: BY_NAME, byVis: BY_VIS };
  if (typeof module !== "undefined" && module.exports) { module.exports = api; }
  else { root.OrbitSSTV = api; }
})(this);
