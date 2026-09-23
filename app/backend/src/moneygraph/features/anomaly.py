import numpy as np
import pandas as pd

from .. import config as C

_MAD_TO_SIGMA = 1.4826
_IQR_TO_SIGMA = 1.349


def hop_anomaly(f: pd.DataFrame) -> pd.DataFrame:
    zs = {}
    for col in ("in_kzt", "out_kzt", "in_deg", "out_deg", "in_tx", "out_tx"):
        x = np.log1p(f[col].astype(float))
        med = x.groupby(f.depth).transform("median")
        mad = (x - med).abs().groupby(f.depth).transform("median")
        iqr = x.groupby(f.depth).transform(lambda s: s.quantile(0.75) - s.quantile(0.25))
        # Leaf-heavy hops have MAD = 0; IQR and a floor keep the scale non-degenerate.
        scale = (
            pd.concat([_MAD_TO_SIGMA * mad, iqr / _IQR_TO_SIGMA], axis=1).max(axis=1).clip(lower=C.ROBUST_SCALE_FLOOR)
        )
        zs[col] = ((x - med) / scale).clip(lower=0)
    z = pd.DataFrame(zs)
    res = pd.DataFrame(index=f.index)
    res["hop_z"] = z.max(axis=1).round(2)
    res["hop_z_metric"] = z.idxmax(axis=1)
    res["hop_anomaly"] = res.hop_z >= C.HOP_ANOMALY_MIN_Z
    return res
