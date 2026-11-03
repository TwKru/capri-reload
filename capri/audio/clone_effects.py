"""The layered voice approved in preview B, with time-aligned pitch layers."""
import os
import subprocess

import numpy as np

SAMPLE_RATE = 24000
EFFECT_VERSION = "layered-b-4-preserve-voice"


def warmup_effects():
    # Keep cache lookups light; scipy is only needed for actual synthesis.
    import scipy.ndimage
    import scipy.signal
    return scipy.ndimage, scipy.signal


def spectral_profile(audio):
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import welch
    _, power = welch(audio, SAMPLE_RATE, nperseg=2048)
    return gaussian_filter1d(power, 14)


def layer_filter():
    filters = ['[0:a]asplit=5[dry][a][b][c][d]']
    layers = ((3., 13, .28), (-4., 21, .24), (.23, 6, .20), (-.19, 28, .18))
    for label, (semitone, delay, gain) in zip('abcd', layers):
        filters.append(f'[{label}]rubberband=tempo=1:pitch={2**(semitone/12):.8f},'
                       f'adelay={delay},volume={gain}[{label}out]')
    filters.append('[dry][aout][bout][cout][dout]amix=inputs=5:normalize=0:duration=first[out]')
    return ';'.join(filters)


def reduce_background(audio):
    """Fade background only outside speech; keep the approved voice spectrum intact."""
    from scipy.ndimage import gaussian_filter1d, maximum_filter1d, uniform_filter1d
    x = np.asarray(audio, dtype=np.float32)
    if len(x) < 1024 or not np.any(x):
        return x.copy()
    envelope = np.sqrt(np.maximum(uniform_filter1d(x*x, size=241, mode='nearest'), 0))
    peak = float(np.max(envelope))
    threshold = min(float(np.quantile(envelope, .2))*3., peak*.04)
    threshold = max(threshold, peak*.01)
    active = envelope > threshold
    # Look ahead/hold for 70 ms to retain breaths, consonants and word endings.
    active = maximum_filter1d(active, size=3361, mode='nearest').astype(np.float32)
    gain = .06 + .94*gaussian_filter1d(active, sigma=96, mode='nearest')
    return (x*gain).astype(np.float32)


def process_layers(audio, target, ffmpeg, cancel=None):
    """Keep timing and the full ending; never stretch one voice over later words."""
    from scipy.ndimage import gaussian_filter1d
    from scipy.signal import fftconvolve, firwin2, welch
    args = [ffmpeg, '-v', 'error', '-f', 'f32le', '-ar', str(SAMPLE_RATE), '-ac', '1',
            '-i', 'pipe:0', '-filter_complex', layer_filter(), '-map', '[out]', '-f', 'f32le', 'pipe:1']
    flags = 0x08004000 if os.name == 'nt' else 0
    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=flags)
    data = np.asarray(audio, dtype='<f4').tobytes()
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Voice interrupted')
            try:
                result, error = process.communicate(input=data, timeout=.1)
                break
            except subprocess.TimeoutExpired:
                data = None
        if process.returncode:
            raise RuntimeError('Voice layers failed: ' + error.decode('utf-8', errors='replace')[-500:])
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate()
    y = np.frombuffer(result, dtype='<f4').copy()[:len(audio)]
    if not len(y) or not np.all(np.isfinite(y)):
        raise ValueError('Invalid cloned audio')
    t = np.arange(len(y), dtype=np.float32) / SAMPLE_RATE
    y *= .96 + .04 * np.sin(2 * np.pi * 63 * t)
    y = np.tanh(y * 1.18)
    freq, current = welch(y, SAMPLE_RATE, nperseg=2048)
    ratio = np.sqrt((np.asarray(target) + 1e-8) / (gaussian_filter1d(current, 14) + 1e-8))
    ratio /= np.median(ratio[(freq > 200) & (freq < 5000)])
    ratio = np.clip(ratio, .55, 1.8)
    ratio[0] = .1
    impulse = firwin2(129, freq / (SAMPLE_RATE / 2), ratio)
    return reduce_background(fftconvolve(y, impulse, mode='same').astype(np.float32))
