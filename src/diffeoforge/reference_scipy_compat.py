"""Run-local message compatibility for legacy Deformetrica with newer SciPy."""

SOURCE = """
# SciPy message presentation only; objective, gradients and optimizer unchanged.
import scipy.optimize as _df_scipy
_df_minimize = _df_scipy.minimize
def _df_message_compat(*args, **kwargs):
    result = _df_minimize(*args, **kwargs)
    if isinstance(result.message, str):
        result.message = result.message.encode("utf-8")
    return result
_df_scipy.minimize = _df_message_compat
"""
