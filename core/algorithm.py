import numpy as np

def hampel_filter(x, window_size=4, n_sigmas=2):
    """
    Remove spikes using Hampel filter (rolling median + MAD).
    x : 1D numpy array
    window_size : odd integer (window length)
    n_sigmas : threshold multiplier (typical 3)
    Returns filtered array (same length).
    """
    x = np.asarray(x, dtype=float)
    k = (window_size - 1) // 2
    n = x.size
    out = x.copy()
    for i in range(n):
        lo = max(0, i - k)
        hi = min(n, i + k + 1)
        window = x[lo:hi]
        med = np.median(window)
        mad = np.median(np.abs(window - med))
        # convert MAD to sigma estimate (for normal approx)
        sigma = 1.4826 * mad if mad > 0 else np.std(window, ddof=1)
        if sigma == 0:
            continue
        if np.abs(x[i] - med) > n_sigmas * sigma:
            out[i] = med
    return out

def moving_average(a, window_size):
    """Simple moving average using convolution, mode='same' keeps length."""
    a = np.asarray(a, dtype=float)
    if window_size <= 1:
        return a.copy()
    kernel = np.ones(window_size) / window_size
    return np.convolve(a, kernel, mode='same')


def format_dose_rate_string(dose_rate_micro_sv_per_hour: float) -> str:
    if dose_rate_micro_sv_per_hour < 1000:
        return f"{dose_rate_micro_sv_per_hour:.3f} µSv/h"
    elif dose_rate_micro_sv_per_hour < 1e6:
        value = dose_rate_micro_sv_per_hour / 1000
        return f"{value:.3f} mSv/h"
    else:
        value = dose_rate_micro_sv_per_hour / 1e6
        return f"{value:.3f} Sv/h"


def get_dead_time_correction(count_rate: float) -> float:
    tau = 10e-6  # seconds, 10 µs dead time
    try:
        correction = 1.0 / (1.0 - count_rate * tau)
        if correction > 0 and correction != float("inf"):
            return correction
        else:
            return 1.0
    except ZeroDivisionError:
        return 1.0


def compute_dose_rate(count_rate: float) -> float:
    dead_time_correction = get_dead_time_correction(count_rate)
    dose_rate = ((count_rate * dead_time_correction) / 3 - 3) * 0.0447

    # simulated correction for very low dose rate
    if dose_rate < 0.1:
        return 0.12 + count_rate * 0.001245

    return dose_rate

def get_dose_str(count_rate):
    rate = compute_dose_rate(count_rate)
    return format_dose_rate_string(rate)
