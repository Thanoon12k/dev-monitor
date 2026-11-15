"""Soundtrack for the video: original music + sound effects, synthesised from scratch (no licensed samples).

128 BPM, 8 bars = 15 s. Cue times mirror anim.js:
  bar 1-2  tension (alert, heartbeat, filtered pad, riser, countdown ticks)
  bar 3    drop on the reduced values (impact + success chime), full groove starts
  bar 4    service chips pop on eighth notes      bar 5  gift sparkle
  bar 6    call-to-action notification            bar 8  final chord, fade
Writes a 48 kHz stereo WAV normalised to -14 LUFS with peaks under -1 dBFS.
usage: python3 audio.py out.wav
"""
import sys
import numpy as np
from scipy import signal
import pyloudnorm as pyln

SR = 48000
B = 60 / 128
BAR = 4 * B
DUR = 8 * BAR
N = int(round(DUR * SR))
TAIL = int(2.5 * SR)  # room for reverb/delay tails before the final trim
rng = np.random.default_rng(7)


def bar(k):
    return (k - 1) * BAR


def mtof(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def tt(n):
    return np.arange(n) / SR


# ---------- building blocks ----------
def polyblep(ph, dt):
    y = np.zeros_like(ph)
    m = ph < dt
    x = ph[m] / dt[m]
    y[m] = x + x - x * x - 1
    m = ph > 1 - dt
    x = (ph[m] - 1) / dt[m]
    y[m] = x * x + x + x + 1
    return y


def saw(freq, n, ph0=0.0):
    dt = np.full(n, freq / SR) if np.isscalar(freq) else np.asarray(freq) / SR
    ph = (ph0 + np.cumsum(dt)) % 1.0
    return 2 * ph - 1 - polyblep(ph, dt)


def sine(freq, n, ph0=0.0):
    f = np.full(n, float(freq)) if np.isscalar(freq) else np.asarray(freq, float)
    return np.sin(2 * np.pi * (ph0 + np.cumsum(f) / SR))


def sos(kind, fc, order=2):
    return signal.butter(order, fc, kind, fs=SR, output='sos')


def filt(x, kind, fc, order=2):
    return signal.sosfilt(sos(kind, fc, order), x)


def fade_edges(x, a=0.002, r=0.01):
    n = len(x)
    na, nr = min(n, int(a * SR)), min(n, int(r * SR))
    x = x.copy()
    if na:
        x[:na] *= np.linspace(0, 1, na)
    if nr:
        x[-nr:] *= np.linspace(1, 0, nr)
    return x


def svf_sweep(x, fcs, q=1.2, mode='band'):
    """Zavalishin TPT state-variable filter with a per-sample cutoff (stable at any setting)."""
    k = 1 / q
    g = np.tan(np.pi * np.clip(fcs, 20, SR * 0.45) / SR)
    a1 = 1 / (1 + g * (g + k))
    a2 = g * a1
    a3 = g * a2
    ic1 = ic2 = 0.0
    out = np.empty(len(x))
    for i in range(len(x)):
        v3 = x[i] - ic2
        v1 = a1[i] * ic1 + a2[i] * v3
        v2 = ic2 + a2[i] * ic1 + a3[i] * v3
        ic1 = 2 * v1 - ic1
        ic2 = 2 * v2 - ic2
        out[i] = v1 if mode == 'band' else v2
    return out


class Bus:
    def __init__(self):
        self.x = np.zeros((2, N + TAIL))

    def add(self, sig, t, gain=1.0, pan=0.0):
        i = int(round(t * SR))
        if sig.ndim == 1:
            a = (pan + 1) * np.pi / 4
            sig = np.stack([sig * np.cos(a), sig * np.sin(a)])
        n = min(sig.shape[1], self.x.shape[1] - i)
        if n > 0:
            self.x[:, i:i + n] += gain * sig[:, :n]


def make_ir(sec, pre=0.018, damp=5500, seed=11):
    n = int(sec * SR)
    irs = []
    for s in (seed, seed + 1):
        noise = filt(np.random.default_rng(s).standard_normal(n), 'low', damp)
        ir = np.concatenate([np.zeros(int(pre * SR)), noise * np.exp(-tt(n) / (sec / 6.9))])
        irs.append(ir / np.sqrt(np.sum(ir ** 2)))
    return irs


def reverb(x, ir):
    return np.stack([signal.fftconvolve(x[c], ir[c])[:x.shape[1]] for c in (0, 1)])


# ---------- instruments ----------
def kick(soft=False):
    n = int(0.5 * SR)
    t = tt(n)
    f = 55 + 115 * np.exp(-t / 0.032) + 40 * np.exp(-t / 0.005)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / (0.2 if soft else 0.26))
    body += 0.35 * np.sin(2 * np.pi * 125 * t) * np.exp(-t / 0.06)
    click = filt(rng.standard_normal(n), 'high', 2500) * np.exp(-t / 0.004) * (0.08 if soft else 0.35)
    y = np.tanh(1.8 * (body + click)) / np.tanh(1.8)
    if soft:
        y = filt(y, 'low', 420)
    return fade_edges(y, 0.0005, 0.02)


def clap():
    n = int(0.4 * SR)
    t = tt(n)
    e = np.zeros(n)
    for d in (0.0, 0.010, 0.021):
        i = int(d * SR)
        e[i:] += np.exp(-(t[i:] - d) / 0.007)
    e += 0.55 * np.exp(-np.maximum(0, t - 0.024) / 0.12) * (t >= 0.024)
    y = filt(rng.standard_normal(n), 'bandpass', [950, 5200]) * e
    return fade_edges(y / np.max(np.abs(y)), 0.0005, 0.02)


def hat(open_=False):
    n = int((0.32 if open_ else 0.07) * SR)
    t = tt(n)
    metal = sum(np.sign(np.sin(2 * np.pi * f * t + p)) for f, p in
                zip((205.3, 304.4, 369.6, 522.7, 540.0, 800.0), rng.random(6) * 6))
    y = 0.6 * rng.standard_normal(n) + 0.25 * metal
    y = filt(y, 'high', 7200, 4) * np.exp(-t / (0.11 if open_ else 0.018))
    return fade_edges(y / np.max(np.abs(y)), 0.0005, 0.005)


def bass(midi, dur):
    n = int(dur * SR)
    t = tt(n)
    f = mtof(midi)
    x = 0.55 * sine(f, n) + 0.5 * filt(saw(f, n), 'low', 1400)
    e = np.minimum(1, t / 0.004) * (0.55 + 0.45 * np.exp(-t / 0.12))
    return fade_edges(np.tanh(1.4 * x * e), 0.001, 0.02)


def pad(midis, dur, cutoff):
    n = int((dur + 0.9) * SR)
    t = tt(n)
    out = np.zeros((2, n))
    for m in midis:
        for det, pan in zip((-0.13, -0.06, 0.0, 0.06, 0.13), (-0.8, -0.4, 0.0, 0.4, 0.8)):
            v = saw(mtof(m) * 2 ** (det / 12), n, rng.random())
            a = (pan + 1) * np.pi / 4
            out[0] += v * np.cos(a)
            out[1] += v * np.sin(a)
    out = np.stack([filt(out[c], 'low', cutoff, 2) for c in (0, 1)])
    env = np.minimum(1, t / 0.22) * np.where(t < dur, 1.0, np.exp(-(t - dur) / 0.28))
    return out * env / (len(midis) * 5)


def pluck(midi, dur=0.4, vel=1.0):
    n = int(dur * SR)
    t = tt(n)
    f = mtof(midi)
    y = np.zeros(n)
    for k in range(1, 14):
        if f * k > 14000:
            break
        amp = (1 / k) * (0.55 if k % 2 == 0 else 1.0)
        y += amp * np.sin(2 * np.pi * f * k * t + k) * np.exp(-t / (0.26 / (1 + 0.7 * (k - 1))))
    return fade_edges(y * vel / 2.6, 0.002, 0.03)


def bell(f, dur=1.4, ratio=2.0, index=2.0, tau=0.8):
    n = int(dur * SR)
    t = tt(n)
    mod = index * np.exp(-t / 0.12) * np.sin(2 * np.pi * f * ratio * t)
    y = np.sin(2 * np.pi * f * t + mod) * np.exp(-t / tau)
    return fade_edges(y, 0.001, 0.05)


def marimba(f, dur=0.5):
    n = int(dur * SR)
    t = tt(n)
    y = (np.sin(2 * np.pi * f * t) * np.exp(-t / 0.22)
         + 0.35 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t / 0.03)
         + 0.12 * np.sin(2 * np.pi * 9.9 * f * t) * np.exp(-t / 0.008))
    return fade_edges(y, 0.001, 0.03)


def pop(f):
    n = int(0.22 * SR)
    t = tt(n)
    freq = f * (0.55 + 0.45 * (1 - np.exp(-t / 0.018)))
    y = sine(freq, n) * np.minimum(1, t / 0.002) * np.exp(-t / 0.055)
    return fade_edges(y, 0.0005, 0.02)


def tick(f):
    n = int(0.06 * SR)
    t = tt(n)
    y = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.012) + 0.25 * filt(rng.standard_normal(n), 'high', 4000) * np.exp(-t / 0.002)
    return fade_edges(y, 0.0003, 0.005)


def alert():
    """Two-tone 'error' blip for the high percentages."""
    out = np.zeros(int(0.5 * SR))
    for start, f, d in ((0.0, 784.0, 0.11), (0.13, 622.25, 0.22)):
        n = int(d * SR)
        t = tt(n)
        y = sum(np.sin(2 * np.pi * f * k * t) / k for k in (1, 3, 5, 7))  # soft square
        y = filt(y, 'low', 2600) * np.minimum(1, t / 0.004) * np.exp(-t / (d * 0.8))
        i = int(start * SR)
        out[i:i + n] += fade_edges(y, 0.001, 0.02)
    return out


def whoosh(dur=0.55, f0=350, f1=3800, f2=700):
    n = int(dur * SR)
    x = np.linspace(0, 1, n)
    fcs = np.where(x < 0.55, f0 * (f1 / f0) ** (x / 0.55), f1 * (f2 / f1) ** ((x - 0.55) / 0.45))
    y = svf_sweep(rng.standard_normal(n), fcs, q=1.6) * np.sin(np.pi * x) ** 2
    y /= np.max(np.abs(y))
    pan = np.linspace(-0.7, 0.7, n)
    a = (pan + 1) * np.pi / 4
    return np.stack([y * np.cos(a), y * np.sin(a)])


def riser(dur):
    n = int(dur * SR)
    x = np.linspace(0, 1, n)
    y = svf_sweep(rng.standard_normal(n), 300 * (7500 / 300) ** x, q=2.2) * x ** 2.2
    y += 0.25 * sine(180 * (900 / 180) ** x, n) * x ** 3
    y /= np.max(np.abs(y))
    return fade_edges(y, 0.05, 0.004)


def impact():
    n = int(1.6 * SR)
    t = tt(n)
    boom = np.sin(2 * np.pi * np.cumsum(42 + 55 * np.exp(-t / 0.09)) / SR) * np.exp(-t / 0.45)
    crash = filt(rng.standard_normal(n), 'high', 5200, 2) * np.exp(-t / 0.55)
    thwack = filt(rng.standard_normal(n), 'bandpass', [180, 1600]) * np.exp(-t / 0.12)
    return fade_edges(0.8 * np.tanh(1.5 * boom) + 0.22 * crash + 0.3 * thwack, 0.0005, 0.05)


def sparkle():
    out = np.zeros((2, int(1.6 * SR)))
    notes = [2093.0, 2349.3, 2637.0, 3136.0, 3520.0, 4186.0]
    for k in range(12):
        s = k * 0.055 + rng.random() * 0.02
        y = bell(notes[(k * 3 + int(rng.random() * 2)) % len(notes)], dur=0.6, ratio=3.01, index=1.2, tau=0.22)
        a = (rng.uniform(-0.8, 0.8) + 1) * np.pi / 4
        i = int(s * SR)
        out[0, i:i + len(y)] += y * np.cos(a) * (1 - k / 16)
        out[1, i:i + len(y)] += y * np.sin(a) * (1 - k / 16)
    n = int(0.9 * SR)
    shimmer = filt(rng.standard_normal(n), 'high', 8000) * np.sin(np.pi * np.linspace(0, 1, n)) ** 2 * 0.15
    out[:, :n] += shimmer
    return out


# ---------- arrangement ----------
music, drums, sfx = Bus(), Bus(), Bus()  # music is side-chained to the kick; drums are not
send_pad, send_fx = Bus(), Bus()
kick_times = []

chords = [  # (start bar, beats, pad notes, bass root, arp notes)
    (3, 4, (57, 60, 65), 41, (77, 81, 84, 89)),   # F
    (4, 4, (59, 62, 67), 43, (79, 83, 86, 91)),   # G
    (5, 4, (59, 64, 67), 40, (76, 79, 83, 88)),   # Em
    (6, 4, (57, 60, 64), 45, (76, 81, 84, 88)),   # Am
    (7, 2, (57, 60, 65), 41, (77, 81, 84, 89)),   # F
    (7.5, 2, (59, 62, 67), 43, (79, 83, 86, 91)), # G
    (8, 4, (60, 64, 67, 72), 36, (84, 88, 91, 96)),  # C
]

# bars 1-2: tension on A minor
p = pad((57, 60, 64), 2 * BAR, 900)
music.add(p, 0, 1.4)
send_pad.add(p, 0, 1.2)
for b in (0, 2, 4, 6):  # heartbeat on beats 1 and 3
    t0 = b * B
    drums.add(kick(soft=True), t0, 0.55)
    drums.add(kick(soft=True), t0 + 0.2, 0.35)
for q in range(8):
    music.add(bass(45, B * 0.9), q * B, 0.42)
for e in range(16):
    drums.add(hat(), e * B / 2, 0.05 + 0.03 * (e % 2 == 1), pan=0.3)
music.add(riser(BAR), bar(2), 0.28)

# bars 3-8: groove
arp_pat = (0, 1, 2, 3, 2, 1, 2, 3, 0, 1, 2, 3, 2, 3, 2, 1)
for start, beats, pn, root, arp in chords:
    t0 = bar(1) + (start - 1) * BAR
    last = start == 8
    dur = beats * B
    p = pad(pn, dur if not last else DUR - t0, 3200)
    music.add(p, t0, 1.5)
    send_pad.add(p, t0, 1.3)
    for e in range(beats * 2):  # eighth-note bass: root / octave
        if last and e > 0:
            break
        m = root + (12 if e % 2 else 0)
        music.add(bass(m, B / 2 * 0.92 if not last else 1.6), t0 + e * B / 2, 0.55)
    steps = beats * 4 if not last else 4
    for s in range(steps):
        m = arp[arp_pat[s % 16]] if not last else arp[s]
        vel = 1.0 if s % 4 == 0 else 0.7
        y = pluck(m, 0.45 if not last else 1.4, vel)
        pan = -0.35 if s % 2 else 0.35
        music.add(y, t0 + s * B / 4, 0.42, pan)
        send_fx.add(y, t0 + s * B / 4, 0.18, pan)
        # ping-pong echoes (dotted eighth)
        music.add(filt(y, 'low', 3500), t0 + s * B / 4 + 0.75 * B, 0.12, -pan)
    for beat in range(beats):
        tb = t0 + beat * B
        if last and beat > 0:
            break
        drums.add(kick(), tb, 0.8)
        kick_times.append(tb)
        if not last:
            gb = int(round((tb - bar(3)) / B))
            if gb % 2 == 1:
                drums.add(clap(), tb, 0.32)
                send_fx.add(clap(), tb, 0.12)
            drums.add(hat(open_=True), tb + B / 2, 0.1, pan=-0.2)
            for sub in (1, 3):
                drums.add(hat(), tb + sub * B / 4, 0.045, pan=0.35)

# sidechain: duck the music bus after every groove kick
duck = np.ones(N + TAIL)
for tk in kick_times:
    i = int(tk * SR)
    n = min(int(0.35 * SR), len(duck) - i)
    duck[i:i + n] = np.minimum(duck[i:i + n], 1 - 0.45 * np.exp(-tt(n) / 0.09))

# ---------- sound effects (cues match anim.js) ----------
sfx.add(alert(), 0.03, 0.42)
send_fx.add(alert(), 0.03, 0.12)
sfx.add(whoosh(), bar(2) - 0.2, 0.28)
countdown = [bar(2) + k * B / 4 for k in range(16) if 2.05 <= bar(2) + k * B / 4 <= 3.64]
for j, t0 in enumerate(countdown):
    sfx.add(tick(1700 + 1500 * j / max(1, len(countdown) - 1)), t0, 0.16, pan=(-0.25 if j % 2 else 0.25))
sfx.add(impact(), bar(3), 0.55)
for k, f in enumerate((1046.5, 1318.5, 1568.0, 2093.0)):  # success arpeggio
    y = bell(f, 1.5, 2.0, 1.8, 0.7)
    sfx.add(y, bar(3) + 0.05 + k * 0.06, 0.2, pan=(-0.3 + 0.2 * k))
    send_fx.add(y, bar(3) + 0.05 + k * 0.06, 0.2)
sfx.add(whoosh(0.6, 500, 2600, 900), 4.4, 0.2)
sfx.add(pop(784.0), 4.9, 0.3)
for i, f in enumerate((1046.5, 1174.7, 1318.5, 1568.0)):
    y = pop(f)
    sfx.add(y, bar(4) + i * B / 2, 0.32, pan=(0.4 - 0.27 * i))
    send_fx.add(y, bar(4) + i * B / 2, 0.08)
sp = sparkle()
sfx.add(sp, bar(5), 0.3)
send_fx.add(sp, bar(5), 0.25)
sfx.add(whoosh(0.45, 600, 3000, 1200), bar(5) - 0.15, 0.14)
for k, f in enumerate((1318.5, 1760.0)):  # message notification
    y = marimba(f)
    sfx.add(y, bar(6) + k * 0.085, 0.42)
    send_fx.add(y, bar(6) + k * 0.085, 0.12)
y = bell(1046.5, 1.8, 2.0, 1.2, 0.9)
sfx.add(y, bar(8), 0.18)
send_fx.add(y, bar(8), 0.2)

# ---------- mix & master ----------
ir_pad, ir_fx = make_ir(1.8, damp=4500), make_ir(1.3, damp=6500, seed=21)
mix = music.x * duck + drums.x + 1.15 * sfx.x
mix += 0.22 * reverb(send_pad.x * duck, ir_pad) + 0.3 * reverb(send_fx.x, ir_fx)
def biquad(x, kind, f0, gain_db, q=0.8):
    A, w0 = 10 ** (gain_db / 40), 2 * np.pi * f0 / SR
    cw, alpha = np.cos(w0), np.sin(w0) / (2 * q)
    if kind == 'lowshelf':
        sq = 2 * np.sqrt(A) * alpha
        b = [A * ((A + 1) - (A - 1) * cw + sq), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - sq)]
        a = [(A + 1) + (A - 1) * cw + sq, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - sq]
    else:  # peaking
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]
        a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    return signal.lfilter(np.array(b) / a[0], np.array(a) / a[0], x)


mix = np.stack([biquad(biquad(filt(mix[c], 'high', 38, 2), 'lowshelf', 100, -6, 0.7), 'peak', 2800, 2.5, 0.9) for c in (0, 1)])
mix = mix[:, :N]
mix[:, :int(0.005 * SR)] *= np.linspace(0, 1, int(0.005 * SR))
fade = int(0.45 * SR)
mix[:, -fade:] *= np.linspace(1, 0, fade) ** 1.5

# gentle glue compression on the stereo envelope, then loudness + peak control
env = signal.sosfilt(sos('low', 12), np.max(np.abs(mix), axis=0))
thr = np.max(env) * 0.45
gain = np.where(env > thr, (thr + (env - thr) / 2.5) / np.maximum(env, 1e-9), 1.0)
mix *= gain
meter = pyln.Meter(SR)
mix *= 10 ** ((-14.0 - meter.integrated_loudness(mix.T)) / 20)

def limit(x, ceiling, look=0.004, rel=0.08):
    """Look-ahead peak limiter on the 4x-oversampled peak (true-peak safe)."""
    from scipy.ndimage import minimum_filter1d
    pk = np.max(np.abs(signal.resample_poly(x, 4, 1, axis=1)), axis=0).reshape(-1, 4).max(axis=1)[:x.shape[1]]
    g = minimum_filter1d(np.minimum(1.0, ceiling / np.maximum(pk, 1e-9)), size=2 * int(look * SR) + 1, mode='nearest')
    a, cur, out = np.exp(-1 / (rel * SR)), 1.0, np.empty_like(g)
    for i in range(len(g)):
        cur = min(g[i], a * cur + (1 - a) * g[i])
        out[i] = cur
    return x * out


mix = limit(mix, 10 ** (-1.2 / 20))
out = sys.argv[1] if len(sys.argv) > 1 else 'soundtrack.wav'
from scipy.io import wavfile
wavfile.write(out, SR, (np.clip(mix.T, -1, 1) * 32767).astype(np.int16))
over = signal.resample_poly(mix, 4, 1, axis=1)
print(f"wrote {out}: {mix.shape[1] / SR:.3f}s, {meter.integrated_loudness(mix.T):.1f} LUFS, "
      f"true peak {20 * np.log10(np.max(np.abs(over))):.1f} dBFS")
