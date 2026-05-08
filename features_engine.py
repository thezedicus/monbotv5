#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║  FICHIER 2/4 — features_engine.py                                           ║
║  Moteur de features avancées — ML + Analyse fondamentale + Sentiment        ║
║                                                                              ║
║  Basé sur les 60 thèses PDF :                                               ║
║    • Thèses 1-2  : Feature engineering ML, deep learning                    ║
║    • Thèses 3-4  : Analyse technique avancée, trading algo                  ║
║    • Thèses 7-8  : Séries temporelles, GARCH, portefeuille                  ║
║    • Thèse 13    : Mathématiques financières (Black-Scholes, VaR)           ║
║    • Thèse 24-26 : Économétrie, facteurs de risque, détection fraude        ║
║                                                                              ║
║  INTÉGRATION :                                                               ║
║    from features_engine import FeatureEngine, AnalysisEngine                ║
║    fe = FeatureEngine()                                                      ║
║    features = fe.compute_all(df, macro_data, fundamental_data)             ║
║    analysis = AnalysisEngine().full_analysis("AAPL", df, features)         ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import os, math, logging, warnings
from datetime import datetime, timedelta
from typing   import Optional, Dict, List, Tuple, Any
import numpy  as np
import pandas as pd
from scipy    import stats as sp_stats

warnings.filterwarnings("ignore")
logger = logging.getLogger("MarketBot.Features")


# ══════════════════════════════════════════════════════════════════════════════
# §1  FEATURE ENGINEERING AVANCÉ  (Thèses 1, 4, 7, 8)
# ══════════════════════════════════════════════════════════════════════════════

class FeatureEngine:
    """
    Calcule toutes les features pour le modèle ML :
    • 30+ features techniques enrichies
    • Features fondamentales (P/E, EPS surprise, Beta)
    • Features macro (courbe des taux, VIX, spreads crédit)
    • Features de sentiment (Bull/Bear score, Fear&Greed)
    • Features de régime (HMM-like, clustering)
    • Features de risque (VaR paramétrique, CVaR, Omega)
    • Features de microstructure (bid-ask proxy, volume imbalance)
    """

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _ema(s: pd.Series, n: int) -> pd.Series:
        return s.ewm(span=n, adjust=False, min_periods=n).mean()

    @staticmethod
    def _rma(s: pd.Series, n: int) -> pd.Series:
        """Wilder's smoothing."""
        α   = 1.0 / n
        arr = s.values.astype(float)
        out = np.full(len(arr), np.nan)
        i0  = next((i for i, v in enumerate(arr) if not np.isnan(v)), None)
        if i0 is None: return pd.Series(out, index=s.index)
        out[i0] = arr[i0]
        for i in range(i0 + 1, len(arr)):
            if not np.isnan(arr[i]):
                out[i] = (out[i-1] if not np.isnan(out[i-1]) else arr[i]) * (1-α) + arr[i] * α
        return pd.Series(out, index=s.index)

    # ── Features techniques de base ───────────────────────────────────────────

    @classmethod
    def technical_features(cls, df: pd.DataFrame) -> pd.DataFrame:
        """30+ features techniques sur OHLCV."""
        df = df.copy()
        C, H, L, O, V = (df[c].astype(float) for c in ["Close","High","Low","Open","Volume"])
        pc = C.shift(1)
        tr = pd.concat([H-L, (H-pc).abs(), (L-pc).abs()], axis=1).max(axis=1)

        # ── Retours ──────────────────────────────────────────────────────────
        for n in [1, 3, 5, 10, 20, 60]:
            df[f"ret_{n}d"]     = C.pct_change(n)
            df[f"logret_{n}d"]  = np.log(C / C.shift(n))

        # ── Momentum (Z-score des retours) ───────────────────────────────────
        for n in [5, 20, 60]:
            ret = C.pct_change(n)
            mu  = ret.rolling(252).mean()
            sig = ret.rolling(252).std()
            df[f"mom_zscore_{n}d"] = (ret - mu) / sig.replace(0, np.nan)

        # ── EMAs et croisements ───────────────────────────────────────────────
        for n in [9, 20, 50, 100, 200]:
            df[f"ema{n}"]     = cls._ema(C, n)
            df[f"ema{n}_pct"] = (C - df[f"ema{n}"]) / df[f"ema{n}"].replace(0, np.nan) * 100

        df["ema_cross_20_50"]  = (cls._ema(C,20) > cls._ema(C,50)).astype(int)
        df["ema_cross_50_200"] = (cls._ema(C,50) > cls._ema(C,200)).astype(int)
        df["golden_cross"]     = (
            (cls._ema(C,20).shift(1) <= cls._ema(C,50).shift(1)) &
            (cls._ema(C,20) > cls._ema(C,50))
        ).astype(int)
        df["death_cross"]      = (
            (cls._ema(C,20).shift(1) >= cls._ema(C,50).shift(1)) &
            (cls._ema(C,20) < cls._ema(C,50))
        ).astype(int)

        # ── ATR et volatilité ─────────────────────────────────────────────────
        df["atr14"]      = cls._rma(tr, 14)
        df["atr14_pct"]  = df["atr14"] / C.replace(0, np.nan) * 100
        df["atr_ratio"]  = df["atr14"] / df["atr14"].rolling(63).mean().replace(0, np.nan)

        # Volatilité réalisée (Parkinson)
        df["vol_parkinson"] = np.sqrt(
            1 / (4 * math.log(2)) *
            np.log(H / L.replace(0, np.nan)).pow(2).rolling(20).mean()
        ) * np.sqrt(252) * 100

        # Volatilité réalisée classique
        df["vol_real_5d"]  = np.log(C / pc).rolling(5).std()  * np.sqrt(252) * 100
        df["vol_real_21d"] = np.log(C / pc).rolling(21).std() * np.sqrt(252) * 100

        # ── GARCH (1,1) approximé ─────────────────────────────────────────────
        lr    = np.log(C / pc)
        rv    = lr ** 2
        α, β  = 0.10, 0.85
        ω     = rv.mean() * (1 - α - β)
        garch_var = pd.Series(np.nan, index=df.index)
        valid_idx = lr.dropna().index
        if len(valid_idx) > 30:
            garch_var.loc[valid_idx[29]] = rv.loc[valid_idx[:30]].mean()
            for j in range(30, len(valid_idx)):
                prev_g = garch_var.loc[valid_idx[j-1]]
                prev_r = rv.loc[valid_idx[j-1]]
                if not np.isnan(prev_g):
                    garch_var.loc[valid_idx[j]] = ω + α * prev_r + β * prev_g
        df["garch_vol"] = np.sqrt(garch_var.clip(lower=0)) * np.sqrt(252) * 100

        # ── RSI multi-période ─────────────────────────────────────────────────
        for period in [7, 14, 21]:
            Δ = C.diff()
            ag = cls._rma(Δ.clip(lower=0), period)
            al = cls._rma((-Δ).clip(lower=0), period)
            df[f"rsi{period}"] = 100 - 100 / (1 + ag / al.replace(0, np.nan))

        # RSI divergence (prix monte, RSI baisse ou vice-versa)
        df["rsi14_div_bull"] = ((C < C.shift(5)) & (df["rsi14"] > df["rsi14"].shift(5))).astype(int)
        df["rsi14_div_bear"] = ((C > C.shift(5)) & (df["rsi14"] < df["rsi14"].shift(5))).astype(int)

        # ── ADX ───────────────────────────────────────────────────────────────
        up, dn = H.diff(), -L.diff()
        pdm = np.where((up > dn) & (up > 0), up, 0.0)
        ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
        atr = cls._rma(tr, 14)
        pdi = 100 * cls._rma(pd.Series(pdm, index=C.index), 14) / atr.replace(0, np.nan)
        ndi = 100 * cls._rma(pd.Series(ndm, index=C.index), 14) / atr.replace(0, np.nan)
        dx  = 100 * (pdi - ndi).abs() / (pdi + ndi).replace(0, np.nan)
        df["adx"]       = cls._rma(dx, 14)
        df["pdi"]       = pdi
        df["ndi"]       = ndi
        df["adx_trend"] = (df["adx"] > 25).astype(int)
        df["di_bull"]   = (pdi > ndi).astype(int)

        # ── Bollinger Bands ───────────────────────────────────────────────────
        bm = C.rolling(20).mean()
        bs = C.rolling(20).std(ddof=0)
        df["bb_pct"]    = (C - (bm - 2*bs)) / (4*bs).replace(0, np.nan)
        df["bb_width"]  = 4*bs / bm.replace(0, np.nan)
        df["bb_squeeze"]= (df["bb_width"] < df["bb_width"].rolling(63).mean() * 0.75).astype(int)

        # ── MACD ──────────────────────────────────────────────────────────────
        macd = cls._ema(C, 12) - cls._ema(C, 26)
        sig  = cls._ema(macd, 9)
        df["macd_h"]      = macd - sig
        df["macd_cross_bull"] = ((macd.shift(1) <= sig.shift(1)) & (macd > sig)).astype(int)
        df["macd_cross_bear"] = ((macd.shift(1) >= sig.shift(1)) & (macd < sig)).astype(int)

        # ── CCI, MFI, Williams %R ─────────────────────────────────────────────
        tp  = (H + L + C) / 3
        mad = tp.rolling(20).apply(lambda x: np.mean(np.abs(x - np.mean(x))), raw=True)
        df["cci"]      = (tp - tp.rolling(20).mean()) / (0.015 * mad.replace(0, np.nan))
        df["cci_extreme"] = ((df["cci"].abs() > 100)).astype(int)

        mf_raw = tp * V
        pmf    = mf_raw.where(tp > tp.shift(1), 0)
        nmf    = mf_raw.where(tp < tp.shift(1), 0)
        mfr    = pmf.rolling(14).sum() / nmf.rolling(14).sum().replace(0, np.nan)
        df["mfi"] = 100 - 100 / (1 + mfr)

        hh = H.rolling(14).max()
        ll = L.rolling(14).min()
        df["williams_r"] = -100 * (hh - C) / (hh - ll).replace(0, np.nan)

        # ── Ichimoku ──────────────────────────────────────────────────────────
        tenkan = (H.rolling(9).max() + L.rolling(9).min()) / 2
        kijun  = (H.rolling(26).max() + L.rolling(26).min()) / 2
        spanA  = ((tenkan + kijun) / 2).shift(26)
        spanB  = ((H.rolling(52).max() + L.rolling(52).min()) / 2).shift(26)
        df["ichi_above_cloud"] = ((C > spanA) & (C > spanB)).astype(int)
        df["ichi_below_cloud"] = ((C < spanA) & (C < spanB)).astype(int)
        df["ichi_tk_cross"]    = ((tenkan.shift(1) <= kijun.shift(1)) & (tenkan > kijun)).astype(int)

        # ── SuperTrend ────────────────────────────────────────────────────────
        hl2  = (H + L) / 2
        ast  = cls._rma(tr, 10)
        ub_r = hl2 + 3 * ast
        lb_r = hl2 - 3 * ast
        trend = pd.Series(1, index=C.index, dtype=int)
        ub, lb = ub_r.copy(), lb_r.copy()
        for i in range(1, len(C)):
            ub.iloc[i] = ub_r.iloc[i] if (ub_r.iloc[i] < ub.iloc[i-1] or C.iloc[i-1] > ub.iloc[i-1]) else ub.iloc[i-1]
            lb.iloc[i] = lb_r.iloc[i] if (lb_r.iloc[i] > lb.iloc[i-1] or C.iloc[i-1] < lb.iloc[i-1]) else lb.iloc[i-1]
            if trend.iloc[i-1] == -1 and C.iloc[i] > ub.iloc[i]:   trend.iloc[i] = 1
            elif trend.iloc[i-1] == 1 and C.iloc[i] < lb.iloc[i]:  trend.iloc[i] = -1
            else: trend.iloc[i] = trend.iloc[i-1]
        df["supertrend"] = trend

        # ── VWAP ─────────────────────────────────────────────────────────────
        df["vwap"]     = (tp * V).rolling(20).sum() / V.rolling(20).sum().replace(0, np.nan)
        df["vwap_pct"] = (C - df["vwap"]) / df["vwap"].replace(0, np.nan) * 100

        # ── Volume features ───────────────────────────────────────────────────
        df["vol_ratio"]   = V / V.rolling(20).mean().replace(0, np.nan)
        df["vol_zscore"]  = (V - V.rolling(20).mean()) / V.rolling(20).std(ddof=0).replace(0, np.nan)
        df["obv"]         = (np.sign(C.diff().fillna(0)) * V).cumsum()
        df["obv_slope"]   = df["obv"].diff(5) / (df["obv"].abs().rolling(5).mean().replace(0, np.nan))
        clv               = ((C - L) - (H - C)) / (H - L).replace(0, np.nan)
        df["cmf"]         = (clv * V).rolling(20).sum() / V.rolling(20).sum().replace(0, np.nan)

        # ── Candle patterns ───────────────────────────────────────────────────
        body  = (C - O).abs()
        rng   = H - L
        df["doji"]        = (body / rng.replace(0, np.nan) < 0.1).astype(int)
        df["engulf_bull"] = ((C > O) & (O < C.shift(1)) & (C > O.shift(1))).astype(int)
        df["engulf_bear"] = ((O > C) & (C > C.shift(1)) & (O < O.shift(1))).astype(int)

        # ── Supports / résistances ────────────────────────────────────────────
        pivot = (H.shift(1) + L.shift(1) + C.shift(1)) / 3
        df["dist_pivot"]  = (C - pivot) / pivot.replace(0, np.nan) * 100
        df["dist_52w_hi"] = (C - H.rolling(252).max()) / H.rolling(252).max().replace(0, np.nan) * 100
        df["dist_52w_lo"] = (C - L.rolling(252).min()) / L.rolling(252).min().replace(0, np.nan) * 100

        # ── Microstructure ────────────────────────────────────────────────────
        df["price_impact"]  = (H - L) / (V + 1) * 1e6   # Illiquidité de Amihud
        df["bar_score"]     = (C - L) / (H - L).replace(0, np.nan)  # Effort des acheteurs
        df["volume_imbal"]  = (V * np.sign(C - O)) / V.rolling(5).sum().replace(0, np.nan)

        return df.replace([np.inf, -np.inf], np.nan)

    # ── Features de risque (Thèse 15) ─────────────────────────────────────────

    @staticmethod
    def risk_features(df: pd.DataFrame, window: int = 252) -> Dict:
        """
        VaR, CVaR, Sharpe roulant, Omega ratio, Ulcer Index.
        Basé sur les thèses 15 (VaR/CVaR) et 8 (Gestion portefeuille).
        """
        if df.empty or len(df) < 30:
            return {}

        C    = df["Close"].astype(float)
        rets = C.pct_change().dropna()

        if len(rets) < 10:
            return {}

        last_rets = rets.tail(window)

        # VaR paramétrique (normale)
        mu, sigma = float(last_rets.mean()), float(last_rets.std())
        z_99 = sp_stats.norm.ppf(0.01)
        z_95 = sp_stats.norm.ppf(0.05)
        var_99 = abs(mu + z_99 * sigma)
        var_95 = abs(mu + z_95 * sigma)

        # CVaR (Expected Shortfall)
        sorted_rets = last_rets.sort_values()
        n_99 = max(1, int(len(sorted_rets) * 0.01))
        n_95 = max(1, int(len(sorted_rets) * 0.05))
        cvar_99 = abs(float(sorted_rets.head(n_99).mean()))
        cvar_95 = abs(float(sorted_rets.head(n_95).mean()))

        # Sharpe annualisé
        rf      = 0.04 / 252   # Taux sans risque quotidien (4% annuel)
        excess  = last_rets - rf
        sharpe  = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0

        # Sortino (pénalise seulement la volatilité baissière)
        downside = excess[excess < 0]
        sortino  = (float(excess.mean() / downside.std() * np.sqrt(252))
                    if len(downside) > 0 and downside.std() > 0 else 0)

        # Max Drawdown
        cum_ret  = (1 + last_rets).cumprod()
        rolling_max = cum_ret.cummax()
        drawdowns   = (cum_ret - rolling_max) / rolling_max
        max_dd   = float(drawdowns.min())

        # Calmar Ratio
        annual_ret = float((1 + last_rets.mean()) ** 252 - 1)
        calmar     = annual_ret / abs(max_dd) if max_dd != 0 else 0

        # Omega Ratio
        wins   = last_rets[last_rets > 0].sum()
        losses = abs(last_rets[last_rets < 0].sum())
        omega  = float(wins / losses) if losses > 0 else float("inf")

        # Ulcer Index (profondeur des drawdowns)
        dd_sq    = drawdowns ** 2
        ulcer    = float(np.sqrt(dd_sq.mean())) * 100

        # Beta par rapport au marché (proxy: retours propres vs EMA200)
        rolling_corr = last_rets.rolling(60).corr(last_rets.shift(1)).mean()

        # Skewness et Kurtosis des retours
        skew = float(sp_stats.skew(last_rets.dropna()))
        kurt = float(sp_stats.kurtosis(last_rets.dropna()))

        return {
            "var_95_pct":  round(var_95 * 100, 3),
            "var_99_pct":  round(var_99 * 100, 3),
            "cvar_95_pct": round(cvar_95 * 100, 3),
            "cvar_99_pct": round(cvar_99 * 100, 3),
            "sharpe_1y":   round(sharpe, 3),
            "sortino_1y":  round(sortino, 3),
            "calmar":      round(calmar, 3),
            "omega":       round(omega, 3) if omega != float("inf") else 99,
            "max_dd_pct":  round(max_dd * 100, 3),
            "ulcer_idx":   round(ulcer, 3),
            "annual_ret":  round(annual_ret * 100, 2),
            "skewness":    round(skew, 3),
            "kurtosis":    round(kurt, 3),
            "vol_annual":  round(sigma * np.sqrt(252) * 100, 2),
        }

    # ── Features macro (Thèses 3, 15, 19) ────────────────────────────────────

    @staticmethod
    def macro_features(macro_data: Dict) -> Dict:
        """
        Transforme les données macro en features ML.
        Basé sur Thèse 3 (Marchés financiers) et 19 (Statistiques).
        """
        f = {}
        if not macro_data:
            return f

        # VIX features
        vix = macro_data.get("VIX", {}).get("value") or macro_data.get("VIX_FRED", {}).get("value")
        if vix:
            f["vix"]             = float(vix)
            f["vix_regime"]      = 0 if vix < 15 else 1 if vix < 20 else 2 if vix < 30 else 3
            f["vix_extreme"]     = int(vix > 30)
            f["vix_complacent"]  = int(vix < 15)
            f["expo_multiplier"] = 0.0 if vix >= 40 else 0.5 if vix >= 30 else 0.75 if vix >= 20 else 1.0

        # Taux features
        t10y = macro_data.get("T10Y", {}).get("value")
        t2y  = macro_data.get("T2Y", {}).get("value")
        if t10y:
            f["t10y"]         = float(t10y)
            f["rates_rising"] = int(macro_data.get("T10Y", {}).get("change", 0) > 0)
        if t2y:
            f["t2y"] = float(t2y)
        if t10y and t2y:
            spread = t10y - t2y
            f["spread_10_2"]          = round(spread, 3)
            f["curve_inverted"]       = int(spread < -0.20)
            f["curve_steep"]          = int(spread > 0.50)
            f["curve_signal"]         = (1 if spread > 0.5 else -1 if spread < -0.2 else 0)

        # Spreads crédit (Thèse 5)
        ig = macro_data.get("IG_SPREAD", {}).get("value")
        hy = macro_data.get("HY_SPREAD", {}).get("value")
        if ig:
            f["ig_spread_bps"]   = float(ig) * 100  # FRED donne en %, on convertit en bps
            f["ig_stress"]       = int(float(ig) * 100 > 150)
        if hy:
            f["hy_spread_bps"]   = float(hy) * 100
            f["hy_crisis"]       = int(float(hy) * 100 > 600)

        # Score macro composite
        macro_score = 0.0
        if f.get("curve_signal", 0) > 0:     macro_score += 1.5
        if f.get("vix_complacent", 0):        macro_score += 1.0
        if not f.get("ig_stress", 0):         macro_score += 1.0
        if f.get("expo_multiplier", 1) == 1:  macro_score += 0.5
        f["macro_score"] = round(macro_score, 2)
        f["macro_bias"]  = ("BULLISH" if macro_score >= 3 else
                             "BEARISH" if macro_score <= 1 else "NEUTRAL")
        return f

    # ── Features fondamentales (Thèse 3, 26) ─────────────────────────────────

    @staticmethod
    def fundamental_features(fund_data: Optional[Dict]) -> Dict:
        """
        Transforme les données fondamentales en features ML.
        Basé sur Thèse 3 (Analyse fondamentale) et 26 (Finance factorielle).
        """
        if not fund_data:
            return {}
        f = {}

        pe = fund_data.get("pe_ratio")
        if pe:
            pe_f = float(pe)
            f["pe_ratio"]    = pe_f
            f["pe_value"]    = int(pe_f < 15)   # Sous-évalué
            f["pe_growth"]   = int(pe_f < 25)
            f["pe_expensive"]= int(pe_f > 35)

        # PEG ratio (P/E ajusté par la croissance)
        fwd_pe = fund_data.get("forward_pe")
        if pe and fwd_pe and pe > 0:
            growth_est = (float(pe) - float(fwd_pe)) / float(pe) * 100
            f["earnings_growth_est"] = round(growth_est, 2)
            peg = float(pe) / max(growth_est, 0.1) if growth_est > 0 else None
            if peg: f["peg_ratio"] = round(peg, 2)

        # Rentabilité
        roe = fund_data.get("roe")
        if roe: f["roe"] = round(float(roe), 4)

        # Levier
        de = fund_data.get("debt_equity")
        if de:
            de_f = float(de)
            f["debt_equity"]    = de_f
            f["high_leverage"]  = int(de_f > 2.0)

        # Beta (sensibilité au marché)
        beta = fund_data.get("beta")
        if beta:
            beta_f = float(beta)
            f["beta"]           = beta_f
            f["low_beta"]       = int(beta_f < 0.8)
            f["high_beta"]      = int(beta_f > 1.3)

        # Score valeur (Fama-French inspired — Thèse 26)
        value_score = 0.0
        if f.get("pe_value"):      value_score += 2.0
        if f.get("pe_growth"):     value_score += 1.0
        if roe and float(roe) > 0.15: value_score += 1.5
        if de and float(de) < 1.0:   value_score += 1.0
        f["value_score"] = round(value_score, 2)

        return f

    # ── Features de sentiment ─────────────────────────────────────────────────

    @staticmethod
    def sentiment_features(news_list: List[Dict],
                            crypto_fg: Optional[Dict] = None) -> Dict:
        """
        Analyse de sentiment basique sur les titres des news.
        En production : remplacer par FinBERT (Thèse 9).
        """
        f = {"bull_news": 0, "bear_news": 0, "sentiment_score": 50.0}

        BULL_WORDS = {"bullish","rally","surge","gain","record","high",
                       "rise","strong","beat","exceed","upgrade","buy",
                       "hausse","monte","rebond","croissance","positif"}
        BEAR_WORDS = {"bearish","fall","crash","drop","loss","decline","low",
                       "sell","miss","downgrade","risk","crisis","sell-off",
                       "baisse","chute","recul","négatif","inquiétude"}

        bull_count = bear_count = 0
        for article in news_list:
            text = (article.get("title","") + " " + article.get("description","")).lower()
            words = set(text.split())
            b = len(words & BULL_WORDS)
            k = len(words & BEAR_WORDS)
            bull_count += b; bear_count += k

        total = bull_count + bear_count
        if total > 0:
            score = bull_count / total * 100
            f["bull_news"]       = bull_count
            f["bear_news"]       = bear_count
            f["sentiment_score"] = round(score, 1)
            f["sentiment_bias"]  = ("BULL" if score > 60 else "BEAR" if score < 40 else "NEUTRAL")

        # Fear & Greed crypto (si disponible)
        if crypto_fg:
            fg_val = crypto_fg.get("value", 50)
            f["fear_greed"]      = fg_val
            f["crypto_fearful"]  = int(fg_val < 30)
            f["crypto_greedy"]   = int(fg_val > 70)

        return f

    # ── Feature set complet ────────────────────────────────────────────────────

    @classmethod
    def compute_all(cls, df: pd.DataFrame,
                     macro_data: Optional[Dict] = None,
                     fund_data: Optional[Dict] = None,
                     news_list: Optional[List[Dict]] = None,
                     crypto_fg: Optional[Dict] = None) -> Tuple[pd.DataFrame, Dict]:
        """
        Calcule TOUTES les features.
        Retourne (df_enrichi, dict_features_scalaires)
        """
        df_tech = cls.technical_features(df)
        risk    = cls.risk_features(df)
        macro   = cls.macro_features(macro_data or {})
        fund    = cls.fundamental_features(fund_data)
        sent    = cls.sentiment_features(news_list or [], crypto_fg)

        scalar_features = {**risk, **macro, **fund, **sent}
        return df_tech, scalar_features


# ══════════════════════════════════════════════════════════════════════════════
# §2  MOTEUR D'ANALYSE COMPLET  (intégration toutes features)
# ══════════════════════════════════════════════════════════════════════════════

class AnalysisEngine:
    """
    Moteur d'analyse qui combine :
    • Features techniques (FeatureEngine)
    • Régime de marché multi-critères
    • Scoring de signal enrichi
    • Évaluation du risque
    • Rapport d'analyse structuré
    """

    # Pondérations des critères (basé sur les thèses 4, 7, 8)
    WEIGHTS = {
        "trend":       3.0,   # Poids fort sur la tendance
        "momentum":    2.0,
        "volume":      1.5,
        "oscillators": 1.5,
        "macro":       2.0,
        "fundamental": 1.0,
        "sentiment":   0.5,
    }

    def score_signal(self, df: pd.DataFrame,
                      scalar: Dict,
                      macro_bias: str = "NEUTRAL") -> Dict:
        """
        Calcule un score de signal composite pondéré.
        Retourne dict avec bull/bear score, signal, confiance.
        """
        if df.empty or len(df) < 5:
            return {"signal": "HOLD", "bull": 0, "bear": 0, "confidence": 0}

        row  = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else row

        def v(k, d=0.0):
            val = row.get(k, d)
            return d if (val is None or (isinstance(val, float) and math.isnan(val))) else float(val)

        bull = 0.0; bear = 0.0; reasons_b = []; reasons_s = []

        # ── TENDANCE (poids 3.0) ──────────────────────────────────────────────
        if v("ema20") > v("ema50") > v("ema200"):
            bull += 3.0; reasons_b.append("EMA 20>50>200 (tendance haussière forte)")
        elif v("ema20") < v("ema50") < v("ema200"):
            bear += 3.0; reasons_s.append("EMA 20<50<200 (tendance baissière forte)")
        elif v("ema20") > v("ema50"):
            bull += 1.5
        else:
            bear += 1.5

        if v("golden_cross"): bull += 2.5; reasons_b.append("Golden Cross EMA 20/50 ✓")
        if v("death_cross"):  bear += 2.5; reasons_s.append("Death Cross EMA 20/50 ✗")
        if v("supertrend") > 0: bull += 1.5; reasons_b.append("SuperTrend haussier ✓")
        elif v("supertrend") < 0: bear += 1.5; reasons_s.append("SuperTrend baissier ✗")
        if v("ichi_above_cloud"): bull += 1.5; reasons_b.append("Au-dessus du nuage Ichimoku ✓")
        elif v("ichi_below_cloud"): bear += 1.5; reasons_s.append("En-dessous du nuage ✗")

        # ── MOMENTUM (poids 2.0) ─────────────────────────────────────────────
        if v("macd_cross_bull"): bull += 2.0; reasons_b.append("MACD cross haussier ✓")
        if v("macd_cross_bear"): bear += 2.0; reasons_s.append("MACD cross baissier ✗")
        mh = v("macd_h", 0)
        if mh > 0:   bull += 0.5
        elif mh < 0: bear += 0.5

        roc20 = v("ret_20d", 0) * 100
        mz20  = v("mom_zscore_20d", 0)
        if mz20 > 1.0: bull += 1.0; reasons_b.append(f"Momentum fort ({roc20:+.1f}%) ✓")
        elif mz20 < -1.0: bear += 1.0; reasons_s.append(f"Momentum faible ({roc20:+.1f}%) ✗")

        # ── VOLUME (poids 1.5) ────────────────────────────────────────────────
        vr = v("vol_ratio", 1.0)
        if vr > 1.5:
            if bull > bear: bull += 1.0; reasons_b.append(f"Volume fort ({vr:.1f}x) ✓")
            else:           bear += 1.0; reasons_s.append(f"Volume fort ({vr:.1f}x) ✗")
        obv_s = v("obv_slope", 0)
        if obv_s > 0: bull += 0.5
        elif obv_s < 0: bear += 0.5
        cmf = v("cmf", 0)
        if cmf > 0.1: bull += 0.5; reasons_b.append(f"CMF positif ({cmf:.2f}) ✓")
        elif cmf < -0.1: bear += 0.5; reasons_s.append(f"CMF négatif ({cmf:.2f}) ✗")

        # ── OSCILLATEURS (poids 1.5) ─────────────────────────────────────────
        rsi = v("rsi14", 50)
        if rsi < 30:   bull += 2.0; reasons_b.append(f"RSI {rsi:.0f} survente ✓")
        elif rsi > 70: bear += 2.0; reasons_s.append(f"RSI {rsi:.0f} surachat ✗")
        elif rsi < 40: bull += 0.5
        elif rsi > 60: bear += 0.5

        bbp = v("bb_pct", 0.5)
        if bbp < 0.1: bull += 1.0; reasons_b.append("Prix sous BB lower ✓")
        elif bbp > 0.9: bear += 1.0; reasons_s.append("Prix sur BB upper ✗")

        adx = v("adx", 20)
        if adx > 25:
            if v("di_bull"): bull += 1.0; reasons_b.append(f"ADX fort haussier ({adx:.0f}) ✓")
            else:            bear += 1.0; reasons_s.append(f"ADX fort baissier ({adx:.0f}) ✗")

        if v("rsi14_div_bull"): bull += 1.5; reasons_b.append("Divergence RSI haussière ✓")
        if v("rsi14_div_bear"): bear += 1.5; reasons_s.append("Divergence RSI baissière ✗")

        # ── MACRO (poids 2.0) ─────────────────────────────────────────────────
        ms = scalar.get("macro_score", 2.0)
        macro_adj = (ms - 2) / 2   # Centré sur 0
        if macro_adj > 0: bull += macro_adj * 2.0; reasons_b.append(f"Macro favorable (score={ms:.1f}) ✓")
        elif macro_adj < 0: bear += abs(macro_adj) * 2.0; reasons_s.append(f"Macro défavorable (score={ms:.1f}) ✗")

        expo = scalar.get("expo_multiplier", 1.0)

        # ── FONDAMENTAUX (poids 1.0) ──────────────────────────────────────────
        vs = scalar.get("value_score", 0)
        if vs >= 3.0: bull += 1.0; reasons_b.append(f"Fondamentaux favorables (score={vs:.1f}) ✓")

        # ── SENTIMENT (poids 0.5) ─────────────────────────────────────────────
        sent = scalar.get("sentiment_score", 50)
        if sent > 65: bull += 0.5; reasons_b.append(f"Sentiment positif ({sent:.0f}%) ✓")
        elif sent < 35: bear += 0.5; reasons_s.append(f"Sentiment négatif ({sent:.0f}%) ✗")

        # ── Signal final ──────────────────────────────────────────────────────
        bull *= expo; bear *= expo

        max_score = 25.0
        if bull >= 8 and bull > bear + 2:
            signal = "STRONG_BUY" if bull >= 12 else "BUY"
            conf   = min(bull / max_score, 1.0)
            reasons = reasons_b[:6]
        elif bear >= 8 and bear > bull + 2:
            signal = "STRONG_SELL" if bear >= 12 else "SELL"
            conf   = min(bear / max_score, 1.0)
            reasons = reasons_s[:6]
        else:
            signal = "HOLD"
            conf   = 0.3
            reasons = ["Pas de signal clair — attente de confirmation"]

        return {
            "signal":     signal,
            "bull_score": round(bull, 2),
            "bear_score": round(bear, 2),
            "bull":       round(bull, 2),
            "bear":       round(bear, 2),
            "confidence": round(conf, 3),
            "expo_mult":  expo,
            "reasons":    reasons,
        }

    def detect_regime(self, df: pd.DataFrame) -> Tuple[str, float]:
        """Détecte le régime de marché (STRONG_BULL/BULL/RANGING/BEAR/STRONG_BEAR)."""
        if df.empty or len(df) < 30:
            return "RANGING", 0.3

        row = df.iloc[-1]
        def v(k, d=0.0):
            val = row.get(k, d)
            return d if (val is None or (isinstance(val, float) and math.isnan(val))) else float(val)

        adx   = v("adx", 20)
        bull  = v("di_bull", 0)
        roc20 = v("ret_20d", 0) * 100
        mz20  = v("mom_zscore_20d", 0)
        ema_a = v("ema_cross_20_50", 0)
        st    = v("supertrend", 0)
        ichi  = v("ichi_above_cloud", 0)

        bull_score = sum([
            2.0 * (adx > 25 and bool(bull)),
            1.5 * bool(ema_a),
            1.0 * (st > 0),
            1.0 * bool(ichi),
            0.5 * (mz20 > 1),
            0.5 * (roc20 > 5),
        ])
        bear_score = sum([
            2.0 * (adx > 25 and not bool(bull) and adx > 0),
            1.5 * (not bool(ema_a)),
            1.0 * (st < 0),
            1.0 * (v("ichi_below_cloud", 0) > 0),
            0.5 * (mz20 < -1),
            0.5 * (roc20 < -5),
        ])
        net = bull_score - bear_score

        if adx < 18 or abs(net) < 1.5:
            return "RANGING",     min(0.5 + (1 - adx/30) * 0.4, 1.0)
        elif net >= 4:
            return "STRONG_BULL", min(net / 7, 1.0)
        elif net >= 1.5:
            return "BULL",        min(net / 5, 1.0)
        elif net <= -4:
            return "STRONG_BEAR", min(abs(net) / 7, 1.0)
        else:
            return "BEAR",        min(abs(net) / 5, 1.0)

    def compute_levels(self, price: float, side: str, atr: float,
                        atr_stop: float = 2.0, atr_tp: float = 4.0
                        ) -> Tuple[float, float, float]:
        """Calcule stop, TP et ratio R:R."""
        stop_d = max(atr * atr_stop, price * 0.005)
        tp_d   = atr * atr_tp
        if side == "long":
            stop = price - stop_d; tp = price + tp_d
        else:
            stop = price + stop_d; tp = price - tp_d
        rr = abs(tp - price) / max(abs(price - stop), 1e-9)
        return round(stop, 4), round(tp, 4), round(rr, 2)

    def full_analysis(self, symbol: str, df: pd.DataFrame,
                       scalar: Dict, macro_data: Optional[Dict] = None) -> Dict:
        """
        Analyse complète d'un actif.
        Retourne un dict structuré prêt pour l'affichage.
        """
        df_tech, _ = FeatureEngine.compute_all(df)
        risk        = FeatureEngine.risk_features(df)
        regime, conf = self.detect_regime(df_tech)
        macro_feats  = FeatureEngine.macro_features(macro_data or {})
        merged_scalar = {**scalar, **macro_feats}
        sig = self.score_signal(df_tech, merged_scalar)

        row = df_tech.iloc[-1] if not df_tech.empty else pd.Series()
        def rv(k, d=None):
            val = row.get(k, d)
            if val is None or (isinstance(val, float) and math.isnan(val)): return d
            return round(float(val), 4)

        price    = rv("Close") or 0.0
        atr      = rv("atr14") or price * 0.01
        stop_l, tp_l, rr_l = self.compute_levels(price, "long",  atr)
        stop_s, tp_s, rr_s = self.compute_levels(price, "short", atr)

        return {
            # ── Identification ────────────────────────────────────────────────
            "symbol":          symbol,
            "timestamp":       datetime.utcnow().isoformat(),

            # ── Prix ──────────────────────────────────────────────────────────
            "price":           price,
            "ret_1d":          rv("ret_1d"),
            "ret_5d":          rv("ret_5d"),
            "ret_20d":         rv("ret_20d"),

            # ── Régime ────────────────────────────────────────────────────────
            "regime":          regime,
            "regime_conf":     round(conf, 2),

            # ── Signal ────────────────────────────────────────────────────────
            "signal":          sig["signal"],
            "bull_score":      sig["bull_score"],
            "bear_score":      sig["bear_score"],
            "confidence":      sig["confidence"],
            "expo_mult":       sig["expo_mult"],
            "reasons":         sig["reasons"],

            # ── Indicateurs clés ──────────────────────────────────────────────
            "rsi14":           rv("rsi14", 2),
            "adx":             rv("adx", 1),
            "atr14":           rv("atr14"),
            "atr14_pct":       rv("atr14_pct", 2),
            "macd_h":          rv("macd_h", 6),
            "bb_pct":          rv("bb_pct", 3),
            "bb_squeeze":      bool(rv("bb_squeeze")),
            "vol_ratio":       rv("vol_ratio", 2),
            "vol_real_21d":    rv("vol_real_21d", 2),
            "garch_vol":       rv("garch_vol", 2),
            "supertrend":      int(rv("supertrend") or 0),
            "above_cloud":     bool(rv("ichi_above_cloud")),
            "vwap_pct":        rv("vwap_pct", 2),
            "dist_52w_hi":     rv("dist_52w_hi", 2),
            "dist_52w_lo":     rv("dist_52w_lo", 2),

            # ── Niveaux de trading ────────────────────────────────────────────
            "stop_long":       stop_l,
            "tp_long":         tp_l,
            "rr_long":         rr_l,
            "stop_short":      stop_s,
            "tp_short":        tp_s,
            "rr_short":        rr_s,

            # ── Risque ────────────────────────────────────────────────────────
            **{f"risk_{k}": v for k, v in risk.items()},

            # ── Macro ─────────────────────────────────────────────────────────
            "macro_bias":      macro_feats.get("macro_bias", "NEUTRAL"),
            "macro_score":     macro_feats.get("macro_score", 2.0),
            "vix":             macro_feats.get("vix"),
            "spread_10_2":     macro_feats.get("spread_10_2"),
        }

    def print_analysis(self, a: Dict) -> None:
        """Affichage terminal structuré d'une analyse."""
        sig_c = {"STRONG_BUY":"🚀","BUY":"📈","HOLD":"⚪","SELL":"📉","STRONG_SELL":"🔻"}.get(a["signal"], "")
        reg_c = {"STRONG_BULL":"🚀","BULL":"📈","RANGING":"↔️","BEAR":"📉","STRONG_BEAR":"🔻"}.get(a["regime"], "")
        print(f"\n{'═'*70}")
        print(f"  {a['symbol']} — Analyse complète | {a.get('timestamp','')[:16]}")
        print(f"{'═'*70}")
        print(f"  Prix          : {a['price']:.4f}   "
              f"Var 1j/5j/20j : {(a.get('ret_1d') or 0)*100:+.2f}% / "
              f"{(a.get('ret_5d') or 0)*100:+.2f}% / "
              f"{(a.get('ret_20d') or 0)*100:+.2f}%")
        print(f"  ATR 14        : {a['atr14']:.4f} ({a['atr14_pct']:.2f}%)   "
              f"GARCH vol : {a.get('garch_vol') or 0:.1f}%")
        print(f"  RSI 14        : {a['rsi14']:.1f}   ADX : {a['adx']:.1f}   "
              f"MACD H : {a.get('macd_h') or 0:.6f}")
        print(f"  BB %B         : {a.get('bb_pct') or 0:.2f}   "
              f"Squeeze : {'⚡ OUI' if a.get('bb_squeeze') else 'Non'}   "
              f"Vol ratio : {a.get('vol_ratio') or 0:.1f}x")
        print(f"  SuperTrend    : {'↑' if (a.get('supertrend') or 0)>0 else '↓'}   "
              f"Ichimoku : {'Au-dessus ✓' if a.get('above_cloud') else 'En-dessous ✗'}   "
              f"VWAP écart : {a.get('vwap_pct') or 0:+.2f}%")
        print(f"  52W High/Low  : {a.get('dist_52w_hi') or 0:+.1f}% / {a.get('dist_52w_lo') or 0:+.1f}%")
        print(f"{'─'*70}")
        print(f"  RÉGIME        : {reg_c} {a['regime']} (conf={a['regime_conf']:.0%})")
        print(f"  MACRO         : {a.get('macro_bias','N/A')} (VIX={a.get('vix') or 'N/A'}  "
              f"Spread 10-2={a.get('spread_10_2') or 'N/A'})  "
              f"Expo={a.get('expo_mult') or 0:.0%}")
        print(f"  SIGNAL        : {sig_c} {a['signal']} (force={a['confidence']:.0%})")
        print(f"  Scores        : Bull={a['bull_score']:.1f}  Bear={a['bear_score']:.1f}")
        for r in a.get("reasons", []):
            print(f"    • {r}")
        print(f"{'─'*70}")
        print(f"  Si LONG       : Stop={a['stop_long']:.4f}  TP={a['tp_long']:.4f}  (R:R={a['rr_long']:.2f}x)")
        print(f"  Si SHORT      : Stop={a['stop_short']:.4f}  TP={a['tp_short']:.4f}  (R:R={a['rr_short']:.2f}x)")
        r = {k.replace("risk_",""):v for k,v in a.items() if k.startswith("risk_")}
        if r.get("var_95_pct"):
            print(f"{'─'*70}")
            print(f"  VaR 95%       : {r.get('var_95_pct',0):.2f}%   "
                  f"CVaR 95%  : {r.get('cvar_95_pct',0):.2f}%")
            print(f"  Sharpe 1Y     : {r.get('sharpe_1y',0):.2f}   "
                  f"Sortino   : {r.get('sortino_1y',0):.2f}   "
                  f"Calmar : {r.get('calmar',0):.2f}")
            print(f"  Max Drawdown  : {r.get('max_dd_pct',0):.2f}%   "
                  f"Skew : {r.get('skewness',0):.2f}   "
                  f"Kurt : {r.get('kurtosis',0):.2f}")
        print(f"{'═'*70}")


# ══════════════════════════════════════════════════════════════════════════════
# §3  COMPARATEUR MULTI-ACTIFS
# ══════════════════════════════════════════════════════════════════════════════

class MultiAssetComparator:
    """Compare plusieurs actifs et produit un classement par force du signal."""

    def __init__(self):
        self.engine = AnalysisEngine()

    def rank(self, analyses: List[Dict]) -> List[Dict]:
        """Classe les actifs par score net absolu."""
        ranked = []
        for a in analyses:
            net = a.get("bull_score", 0) - a.get("bear_score", 0)
            ranked.append({**a, "net_score": round(net, 2)})
        ranked.sort(key=lambda x: abs(x["net_score"]), reverse=True)
        return ranked

    def print_scorecard(self, ranked: List[Dict]) -> None:
        """Tableau de bord terminal des actifs classés."""
        print(f"\n{'═'*80}")
        print(f"  SCORECARD MULTI-ACTIFS — {datetime.utcnow():%Y-%m-%d %H:%M UTC}")
        print(f"{'═'*80}")
        print(f"  {'Symbole':10s} {'Prix':10s} {'Régime':14s} {'Signal':14s} "
              f"{'Score':8s} {'RSI':6s} {'ADX':6s} {'Conf':6s}")
        print(f"  {'─'*76}")
        for a in ranked:
            sig_i = {"STRONG_BUY":"🚀","BUY":"↑ ","HOLD":"— ","SELL":"↓ ","STRONG_SELL":"🔻"}.get(a.get("signal",""), "")
            net   = a.get("net_score", 0)
            score_bar = "█" * min(int(abs(net) * 1.5), 8)
            color_prefix = "+" if net > 0 else "-" if net < 0 else " "
            print(f"  {a.get('symbol',''):10s} "
                  f"{a.get('price',0):10.4f} "
                  f"{a.get('regime',''):14s} "
                  f"{sig_i}{a.get('signal',''):12s} "
                  f"{color_prefix}{abs(net):4.1f} {score_bar:8s} "
                  f"{a.get('rsi14') or 0:6.1f} "
                  f"{a.get('adx') or 0:6.1f} "
                  f"{a.get('confidence',0):6.1%}")
        print(f"{'═'*80}")


# ══════════════════════════════════════════════════════════════════════════════
# TEST AUTONOME
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO,
                         format="%(asctime)s | %(levelname)-8s | %(message)s")

    parser = argparse.ArgumentParser(description="features_engine.py — Test")
    parser.add_argument("--symbol", type=str, default="SPY")
    parser.add_argument("--demo",   action="store_true", help="Démo avec données synthétiques")
    args = parser.parse_args()

    # Données de test (synthétiques si pas d'internet)
    try:
        import yfinance as yf
        df = yf.download(args.symbol, period="2y", interval="1d",
                          progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df.columns = [c.title() for c in df.columns]
        print(f"✅ Données réelles : {args.symbol} ({len(df)} jours)")
    except:
        # Données synthétiques
        np.random.seed(42)
        n    = 504
        lr   = np.random.normal(0.0003, 0.010, n)
        prices = 460 * np.exp(np.cumsum(lr))
        dr   = prices * 0.010
        dates = pd.bdate_range(end=pd.Timestamp("2026-05-01"), periods=n)
        df = pd.DataFrame({
            "Open":  prices * np.exp(np.random.normal(0, 0.003, n)),
            "High":  prices + np.abs(dr) * 0.4,
            "Low":   prices - np.abs(dr) * 0.4,
            "Close": prices, "Volume": np.random.randint(60e6, 120e6, n)
        }, index=dates[-n:])
        print(f"⚠️  Données synthétiques ({args.symbol})")

    macro_sim = {
        "VIX_FRED": {"value": 17.5}, "T10Y": {"value": 4.35, "change": 0.02},
        "T2Y": {"value": 4.20, "change": -0.01}, "IG_SPREAD": {"value": 0.85},
    }

    engine = AnalysisEngine()
    fe     = FeatureEngine()
    if df.empty:
        print("DataFrame vide — génération données synthétiques")
        import numpy as np
        n=504; lr=np.random.normal(0.0003,0.010,n); prices=460*np.exp(np.cumsum(lr))
        dr=prices*0.010; dates=pd.bdate_range(end=pd.Timestamp("2026-05-01"),periods=n)
        df=pd.DataFrame({"Open":prices*np.exp(np.random.normal(0,0.003,n)),"High":prices+np.abs(dr)*0.4,"Low":prices-np.abs(dr)*0.4,"Close":prices,"Volume":np.random.randint(60000000,120000000,n)},index=dates[-n:])
    df_t, scalar = fe.compute_all(df, macro_data=macro_sim)
    analysis = engine.full_analysis(args.symbol, df, scalar, macro_sim)
    engine.print_analysis(analysis)
    print(f"\n  Features calculées : {len(df_t.columns)} colonnes")
    print(f"  Features scalaires : {len(scalar)} valeurs")
