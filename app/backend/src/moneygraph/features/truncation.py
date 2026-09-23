from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .. import config as C
from ..collection import Collection


@dataclass(frozen=True)
class ContinuationModel:
    status: str
    n_train: int
    base_rate: float | None = None
    auc_cv: float | None = None
    auc_transfer: float | None = None
    transfer_mean_pred: float | None = None
    transfer_actual_rate: float | None = None
    coefs: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _inflow_profile(f: pd.DataFrame, tx: pd.DataFrame, collection: Collection) -> pd.DataFrame:
    incoming = tx.groupby("dst")
    X = pd.DataFrame(index=f.index)
    X["log_in_kzt"] = np.log1p(f.in_kzt)
    X["in_deg"] = f.in_deg
    X["log_in_tx"] = np.log1p(f.in_tx)
    X["log_max_tx"] = np.log1p(incoming.sum_kzt.max()).reindex(f.index).fillna(0)
    X["round_share"] = incoming.sum_kzt.apply(lambda s: float((s % 10_000 == 0).mean())).reindex(f.index).fillna(0)
    X["days_before_end"] = (
        (collection.end - incoming.date.max()).dt.days.reindex(f.index).fillna(collection.observation_days)
    )
    X["seed_payer"] = (f.seed_payers > 0).astype(int)
    fanout = tx.groupby("src").dst.nunique()
    main_payer = tx.sort_values(["dst", "sum_kzt", "src"], ascending=[True, False, True]).drop_duplicates("dst")
    X["log_payer_fanout"] = np.log1p(main_payer.set_index("dst").src.map(fanout)).reindex(f.index).fillna(0)
    return X


def _forwards_after_receiving(f: pd.DataFrame, tx: pd.DataFrame) -> pd.Series:
    first_in = tx.groupby("dst").day.min().reindex(f.index)
    last_out = tx.groupby("src").day.max().reindex(f.index)
    return (last_out >= first_in).fillna(False)


def _new_model():
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))


def _transfer_check(X: pd.DataFrame, y: pd.Series, depth: pd.Series, collection: Collection) -> dict:
    # Nodes on the last hop were never expanded; the closest honest test is to train on earlier expanded
    # hops and evaluate on the last expanded one.
    near, far = depth < collection.expanded_depth, depth == collection.expanded_depth
    if (
        near.sum() < C.TRANSFER_CHECK_MIN_NODES
        or far.sum() < C.TRANSFER_CHECK_MIN_NODES
        or y[near].nunique() < 2
        or y[far].nunique() < 2
    ):
        return {}
    pred = _new_model().fit(X[near], y[near]).predict_proba(X[far])[:, 1]
    return {
        "auc_transfer": round(float(roc_auc_score(y[far], pred)), 3),
        "transfer_mean_pred": round(float(pred.mean()), 3),
        "transfer_actual_rate": round(float(y[far].mean()), 3),
    }


def continuation_model(
    f: pd.DataFrame, tx: pd.DataFrame, collection: Collection
) -> tuple[pd.Series, ContinuationModel]:
    X = _inflow_profile(f, tx, collection)
    train = f[f.depth.between(1, collection.expanded_depth) & ~f.is_seed & (f.in_deg > 0)]
    Xt, y = X.loc[train.index], _forwards_after_receiving(f, tx).loc[train.index].astype(int)
    n_pos, n_neg = int(y.sum()), int(len(y) - y.sum())
    if len(y) < C.TRUNCATION_MODEL_MIN_TRAIN or min(n_pos, n_neg) < C.TRUNCATION_MODEL_MIN_CLASS:
        return pd.Series(np.nan, index=f.index), ContinuationModel(
            status="insufficient_data", n_train=int(len(y)), base_rate=round(float(y.mean()), 3) if len(y) else None
        )
    folds = StratifiedKFold(n_splits=min(5, n_pos, n_neg), shuffle=True, random_state=C.RANDOM_SEED)
    out_of_fold = cross_val_predict(_new_model(), Xt, y, cv=folds, method="predict_proba")[:, 1]
    model = _new_model().fit(Xt, y)
    return (
        pd.Series(model.predict_proba(X)[:, 1], index=f.index).round(3),
        ContinuationModel(
            status="ok",
            n_train=int(len(y)),
            base_rate=round(float(y.mean()), 3),
            auc_cv=round(float(roc_auc_score(y, out_of_fold)), 3),
            coefs={k: round(float(v), 3) for k, v in zip(X.columns, model[-1].coef_[0], strict=True)},
            **_transfer_check(Xt, y, train.depth, collection),
        ),
    )
