import re
import streamlit as st
import pandas as pd
from tvDatafeed import TvDatafeed, Interval

st.set_page_config(page_title="Tüm BIST Tarama: Tepe + Hacim", layout="wide")
st.title("Tüm BIST Taraması: Kapanış Tepeye Yakın (+ Hacim)")

BIST_ALL_URL = "https://www.borsaistanbul.com/files/Shares-Market-Segments.xlsx"

BIST100_FALLBACK = [
    "AEFES","AGHOL","AKBNK","AKSA","AKSEN","ALARK","ALTNY","ANSGR","ARCLK","ASELS",
    "ASTOR","BALSU","BIMAS","BRSAN","BRYAT","BSOKE","BTCIM","CANTE","CCOLA","CIMSA",
    "CWENE","DAPGM","DOAS","DOHOL","DSTKF","ECILC","EFOR","EGEEN","EKGYO","ENERY",
    "ENJSA","ENKAI","EREGL","EUPWR","FENER","FROTO","GARAN","GENIL","GESAN","GLRMK",
    "GRSEL","GRTHO","GSRAY","GUBRF","HALKB","HEKTS","ISCTR","ISMEN","IZENR","KCAER",
    "KCHOL","KLRHO","KONTR","KRDMD","KTLEV","KUYAS","MAGEN","MAVI","MGROS","MIATK",
    "MPARK","OBAMS","ODAS","OTKAR","OYAKC","PASEU","PATEK","PETKM","PGSUS","QUAGR",
    "RALYH","REEDR","SAHOL","SASA","SISE","SKBNK","SOKM","TABGD","TAVHL","TCELL",
    "THYAO","TKFEN","TOASO","TRALT","TRENJ","TRMET","TSKB","TSPOR","TTKOM","TTRAK",
    "TUKAS","TUPRS","TUREX","TURSG","ULKER","VAKBN","VESTL","YEOTK","YKBNK","ZOREN"
]

TF_MAP = {
    "Günlük (1D)": Interval.in_daily,
    "4 Saat (4H)": Interval.in_4_hour,
    "1 Saat (1H)": Interval.in_1_hour,
}

# TvDatafeed (girişsiz). Giriş gerektiren durumda veri gelmeyebilir.
tv = TvDatafeed()


def safe_float(x):
    try:
        if x is None:
            return None
        return float(x)
    except Exception:
        return None


@st.cache_data(ttl=60 * 60 * 24, show_spinner=False)
def fetch_all_bist_symbols() -> list[str]:
    """
    Borsa İstanbul excel dosyasından mümkün olduğunca doğru şekilde sembolleri çeker.
    Eğer 200'den az sembol çıkarsa BIST100 fallback kullanır.
    """
    df = pd.read_excel(BIST_ALL_URL)

    preferred_names = [
        "CODE", "Code", "code",
        "SYMBOL", "Symbol", "symbol",
        "INSTRUMENT CODE", "Instrument Code", "instrument code",
        "SERMAYE PİYASASI ARACI KODU", "Sermaye Piyasası Aracı Kodu",
        "PAY KODU", "Pay Kodu",
        "KOD", "Kod",
    ]

    def extract_codes_from_series(s: pd.Series) -> list[str]:
        s = (
            s.dropna()
             .astype(str)
             .str.strip()
             .str.upper()
             .str.replace(".E", "", regex=False)
             .str.replace("BIST:", "", regex=False)
        )
        out = []
        for v in s.tolist():
            out.extend(re.findall(r"\b[A-Z0-9]{2,8}\b", v))
        return out

    # 1) Önce tercih edilen kolon adlarından çekmeyi dene
    for name in preferred_names:
        if name in df.columns:
            syms = sorted(set(extract_codes_from_series(df[name])))
            if len(syms) >= 200:
                return syms

    # 2) Bulamazsak tüm object kolonlarını tara
    obj_cols = [c for c in df.columns if df[c].dtype == "object"]
    all_syms = []
    for c in obj_cols:
        all_syms.extend(extract_codes_from_series(df[c]))

    all_syms = sorted(set(all_syms))
    return all_syms if len(all_syms) >= 200 else BIST100_FALLBACK


@st.cache_data(ttl=60 * 10, show_spinner=False)
def get_hist(symbol: str, interval, n_bars: int) -> pd.DataFrame:
    """
    tvDatafeed bazı ortamlarda exchange olarak BIST yerine BORSA isteyebiliyor.
    Bu yüzden 3 farklı format dener.
    """
    tries = [
        dict(symbol=symbol, exchange="BIST"),
        dict(symbol=symbol, exchange="BORSA"),
        dict(symbol=f"BIST:{symbol}", exchange=None),
    ]
    for t in tries:
        try:
            df = tv.get_hist(symbol=t["symbol"], exchange=t["exchange"], interval=interval, n_bars=n_bars)
            if df is not None and not df.empty:
                return df
        except Exception:
            pass
    return pd.DataFrame()


# ---------- UI ----------
col1, col2, col3 = st.columns([2, 1, 1])

with col1:
    use_all = st.checkbox("Tüm BIST (otomatik güncel)", value=True)

    if use_all:
        try:
            default_syms = fetch_all_bist_symbols()
        except Exception:
            default_syms = BIST100_FALLBACK
    else:
        default_syms = BIST100_FALLBACK

    symbols_text = st.text_area("Sembol listesi (her satır bir sembol)", "\n".join(default_syms), height=260)

with col2:
    tf_label = st.selectbox("Zaman dilimi", list(TF_MAP.keys()), index=0)
    n_bars = st.slider("Bar sayısı (hız için düşük tut)", 15, 300, 80, step=5)

with col3:
    tol_pct = st.slider("Tepeye yakınlık toleransı (%)", 0.00, 1.00, 0.10, step=0.05)
    bar_mode = st.selectbox("Hangi bar?", ["Son bar", "Son kapanmış bar"], index=0)
    vol_lookback = st.slider("Ortalama hacim periyodu", 5, 50, 20, step=1)

interval = TF_MAP[tf_label]
use_closed_bar = (bar_mode == "Son kapanmış bar")
avg_col = f"Ort. Hacim({vol_lookback})"

run = st.button("Taramayı Başlat")


def analyze(symbol: str) -> dict:
    base = {
        "Sembol": symbol,
        "Veri": False,
        "Bar": "",
        "Kapanış": None,
        "Günlük Tepe": None,
        "Tepeye Uzaklık %": None,
        "Hacim": None,
        avg_col: None,
        "Hacim Katsayısı": None,
        "Seçildi": False,
    }

    df = get_hist(symbol, interval, n_bars)
    if df is None or df.empty or len(df) < max(3, vol_lookback + 2):
        return base

    i = -2 if use_closed_bar else -1
    if len(df) < abs(i):
        return base

    row = df.iloc[i]
    close_ = safe_float(row.get("close", None))
    high_ = safe_float(row.get("high", None))
    dt = str(df.index[i])

    if close_ is None or high_ is None or high_ <= 0:
        return base

    vol_today = safe_float(row.get("volume", None))

    dist_to_high_pct = (high_ - close_) / high_ * 100.0
    hit = close_ >= high_ * (1.0 - tol_pct / 100.0)

    vol_avg = None
    vol_ratio = None
    if "volume" in df.columns:
        vol_slice = pd.to_numeric(df["volume"].iloc[i - vol_lookback + 1 : i + 1], errors="coerce").dropna()
        if len(vol_slice) > 0:
            vol_avg = float(vol_slice.mean())
            if vol_today is not None and vol_avg > 0:
                vol_ratio = float(vol_today / vol_avg)

    base.update({
        "Veri": True,
        "Bar": dt,
        "Kapanış": round(close_, 4),
        "Günlük Tepe": round(high_, 4),
        "Tepeye Uzaklık %": round(float(dist_to_high_pct), 3),
        "Hacim": int(vol_today) if vol_today is not None else None,
        avg_col: int(vol_avg) if vol_avg is not None else None,
        "Hacim Katsayısı": round(vol_ratio, 2) if vol_ratio is not None else None,
        "Seçildi": bool(hit),
    })
    return base


if run:
    symbols = [s.strip().upper() for s in symbols_text.splitlines() if s.strip()]
    st.write(
        f"Toplam: **{len(symbols)}** | TF: **{tf_label}** | Bar: **{n_bars}** | Tol: **%{tol_pct:.2f}** | Mod: **{bar_mode}** | Ort.Hacim: **{vol_lookback}**"
    )

    results = []
    p = st.progress(0)

    for idx, sym in enumerate(symbols, start=1):
        try:
            results.append(analyze(sym))
        except Exception:
            results.append({
                "Sembol": sym, "Veri": False, "Bar": "", "Kapanış": None, "Günlük Tepe": None,
                "Tepeye Uzaklık %": None, "Hacim": None, avg_col: None, "Hacim Katsayısı": None,
                "Seçildi": False
            })
        p.progress(idx / max(len(symbols), 1))

    df_res = pd.DataFrame(results)
    ok = df_res[df_res["Veri"] == True].copy()

    st.divider()
    st.subheader("Seçilenler ✅ (Kapanış tepeye çok yakın/eşit)")

    picked = ok[ok["Seçildi"] == True].copy()

    picked["Hacim Katsayısı_Sort"] = pd.to_numeric(picked["Hacim Katsayısı"], errors="coerce").fillna(0)
    picked["Hacim_Sort"] = pd.to_numeric(picked["Hacim"], errors="coerce").fillna(0)
    picked["Tepeye Uzaklık %"] = pd.to_numeric(picked["Tepeye Uzaklık %"], errors="coerce")

    picked = picked.sort_values(
        by=["Tepeye Uzaklık %", "Hacim Katsayısı_Sort", "Hacim_Sort"],
        ascending=[True, False, False]
    )

    cols = ["Sembol", "Kapanış", "Günlük Tepe", "Tepeye Uzaklık %", "Hacim", avg_col, "Hacim Katsayısı", "Bar"]
    st.dataframe(picked[cols], use_container_width=True)

    st.subheader("Tüm sonuçlar (Tepeye uzaklığa göre)")
    ok["Hacim Katsayısı_Sort"] = pd.to_numeric(ok["Hacim Katsayısı"], errors="coerce").fillna(0)
    ok["Hacim_Sort"] = pd.to_numeric(ok["Hacim"], errors="coerce").fillna(0)
    ok["Tepeye Uzaklık %"] = pd.to_numeric(ok["Tepeye Uzaklık %"], errors="coerce")
    all_sorted = ok.sort_values(by=["Tepeye Uzaklık %", "Hacim Katsayısı_Sort", "Hacim_Sort"], ascending=[True, False, False])
    st.dataframe(all_sorted[cols], use_container_width=True)

    with st.expander("Ham tablo (debug)"):
        st.dataframe(df_res, use_container_width=True)