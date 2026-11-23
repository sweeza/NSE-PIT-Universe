"""The deterministic build: raw/ + curated/ -> build/. Offline, no timestamps in outputs."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

from . import actions, adjust, bhavcopy, identity, indices, market, membership, paths

from .series import EQUITY_SERIES, PRIMARY_SERIES  # noqa: E402


def primary_close(t: pd.DataFrame, equity_only: bool = True) -> pd.DataFrame:
    """One row per (sec_id, date): the highest-priority equity series (equity series only by default)."""
    prio = {s: i for i, s in enumerate(PRIMARY_SERIES)}
    x = t[["sec_id", "date", "series", "close", "open", "volume"]]
    if equity_only:
        x = x[x["series"].isin(EQUITY_SERIES)]
    x = x.copy()
    x["_p"] = x["series"].map(prio).fillna(99)
    x = x.sort_values(["sec_id", "date", "_p", "series"], kind="mergesort")
    return x.drop_duplicates(["sec_id", "date"], keep="first").drop(columns="_p").reset_index(drop=True)


def build_all(out: Path | None = None, with_indices: bool = True) -> dict:
    out = out or paths.BUILD
    paths_before = paths.BUILD
    t = bhavcopy.read_all()
    sec, sh, links, seg_map = identity.build(t)
    t = identity.attach(t, seg_map)
    eq_ids = set(t.loc[t["series"].isin(EQUITY_SERIES), "sec_id"].unique())
    sec["is_equity"] = sec["sec_id"].isin(eq_ids)
    t = t.sort_values(["date", "symbol", "series"], kind="mergesort").reset_index(drop=True)
    info = {"bhavcopy": bhavcopy.write(t, out / "bhavcopy")}
    ident = out / "identity"
    ident.mkdir(parents=True, exist_ok=True)
    for name, df in (("securities", sec), ("symbol_history", sh), ("links", links), ("segments", seg_map)):
        df.to_parquet(ident / f"{name}.parquet", index=False, compression="zstd", compression_level=9)
    info["securities"] = len(sec)

    info.update(build_actions(out, t, seg_map, sh, sec))
    info["market"] = market.build(out / "market", t[["date", "symbol", "series", "sec_id", "volume"]])

    if with_indices:
        info["indices"] = indices.build(out / "indices")
        info["membership"] = membership.build(out)
    write_checksums(out)
    return info


def build_actions(out: Path, t: pd.DataFrame | None = None, seg_map=None, sh=None, sec=None) -> dict:
    """Corporate actions -> events + adjustments. Can run alone from an existing build."""
    if t is None:
        from . import bhavcopy
        t = bhavcopy.load()
        ident = out / "identity"
        seg_map = pd.read_parquet(ident / "segments.parquet")
        sh = pd.read_parquet(ident / "symbol_history.parquet")
        sec = pd.read_parquet(ident / "securities.parquet")
    ev = actions.build_events()
    pc = primary_close(t)
    days_by_sec = {sid: g["date"].values for sid, g in pc.groupby("sec_id")}
    close_by_sec = {sid: g.set_index("date")["close"] for sid, g in pc.groupby("sec_id")}
    ev = adjust.attach_events(ev, seg_map, days_by_sec, sh, sec)
    adj = adjust.build_adjustments(ev, close_by_sec)
    pcg = pc.sort_values(["sec_id", "date"]).copy()
    pcg["prev_close_obs"] = pcg.groupby("sec_id")["close"].shift(1)
    adj, glog = adjust.gate(adj, pcg, override=adjust.gate_override_keys(ev))
    ca = out / "actions"
    ca.mkdir(parents=True, exist_ok=True)
    ev.to_parquet(ca / "events.parquet", index=False, compression="zstd", compression_level=9)
    adj.to_parquet(ca / "adjustments.parquet", index=False, compression="zstd", compression_level=9)
    glog.to_parquet(ca / "gate_log.parquet", index=False, compression="zstd", compression_level=9)
    return {"events": len(ev), "adjustments": len(adj), "gate": glog.decision.value_counts().to_dict()}


def write_checksums(out: Path) -> Path:
    lines = []
    for p in sorted(out.rglob("*.parquet")):
        lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out).as_posix()}")
    f = out / "checksums.txt"
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f
