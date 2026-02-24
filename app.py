import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import requests
from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from PIL import Image


# -------------------- App Config --------------------
APP_NAME = "SolarYield Albania PRO"
APP_VERSION = "v1.0.0"
AUTHOR = "Aldo Tozaj"
COPYRIGHT = "© 2026 SolarYield Albania PRO. All rights reserved."

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
EXPORTS_DIR = BASE_DIR / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

LOGO_PATH = ASSETS_DIR / "logo.png"  # opsionale

st.set_page_config(page_title=f"{APP_NAME} {APP_VERSION}", layout="centered")


# -------------------- HEADER --------------------
if LOGO_PATH.exists():
    try:
        logo_bytes = LOGO_PATH.read_bytes()
        col1, col2 = st.columns([1, 3])
        with col1:
            st.image(logo_bytes, width=120)
        with col2:
            st.title(APP_NAME)
            st.caption(f"Version {APP_VERSION} | Developed by {AUTHOR}")
    except Exception as e:
        st.warning(f"Logo nuk u hap: {e}")
        st.title(APP_NAME)
        st.caption(f"Version {APP_VERSION} | Developed by {AUTHOR}")
else:
    st.title(APP_NAME)
    st.caption(f"Version {APP_VERSION} | Developed by {AUTHOR}")


# -------------------- Helpers --------------------
CITY_DB = {
    "Tirana": (41.3275, 19.8187),
    "Vlora": (40.4666, 19.4897),
    "Durres": (41.3231, 19.4414),
    "Shkoder": (42.0683, 19.5126),
    "Elbasan": (41.1125, 20.0828),
    "Korce": (40.6186, 20.7808),
    "Gjirokaster": (40.0758, 20.1389),
    "Fier": (40.7239, 19.5561),
}


@st.cache_data(show_spinner=False, ttl=60 * 60)  # 1 hour cache
def pvgis_monthly(lat, lon, peakpower, loss, tilt, azimuth):
    url = "https://re.jrc.ec.europa.eu/api/v5_2/PVcalc"
    params = {
        "lat": float(lat),
        "lon": float(lon),
        "peakpower": float(peakpower),
        "loss": float(loss),
        "angle": float(tilt),
        "aspect": float(azimuth),
        "outputformat": "json",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def extract_monthly_table(pvgis_json: dict) -> pd.DataFrame:
    """
    PVGIS outputs['monthly'] sometimes is:
      - list of dicts (most common)
      - or dict containing 'fixed' / other keys
    We handle both.
    """
    outputs = pvgis_json.get("outputs", {})
    monthly = outputs.get("monthly")

    if monthly is None:
        raise ValueError("PVGIS JSON missing outputs.monthly")

    if isinstance(monthly, list):
        df = pd.DataFrame(monthly)
    elif isinstance(monthly, dict):
        # try common keys
        if "fixed" in monthly:
            df = pd.DataFrame(monthly["fixed"])
        else:
            # fallback: first list-like value inside dict
            list_candidate = None
            for v in monthly.values():
                if isinstance(v, list):
                    list_candidate = v
                    break
            if list_candidate is None:
                raise ValueError(f"PVGIS outputs.monthly has unexpected format: keys={list(monthly.keys())}")
            df = pd.DataFrame(list_candidate)
    else:
        raise ValueError(f"PVGIS outputs.monthly type unexpected: {type(monthly)}")

    # Expect E_m (kWh) and month
    if "month" not in df.columns:
        raise ValueError(f"PVGIS monthly table missing 'month'. Columns: {list(df.columns)}")
    if "E_m" not in df.columns:
        raise ValueError(f"PVGIS monthly table missing 'E_m'. Columns: {list(df.columns)}")

    df["month"] = df["month"].astype(int)
    df["Energy_kWh"] = df["E_m"].astype(float)
    return df[["month", "Energy_kWh"]]


def compute_financials(annual_kwh, price_per_kwh, capex, opex_percent, lifetime_years, degradation_percent):
    """
    Model i thjeshtë:
    - energjia bie çdo vit me degradation_percent
    - savings = energy * price
    - opex = capex * opex_percent
    """
    annual_kwh = float(annual_kwh)
    price_per_kwh = float(price_per_kwh)
    capex = float(capex)
    opex = capex * (float(opex_percent) / 100.0)
    degr = float(degradation_percent) / 100.0

    rows = []
    cumulative = -capex
    for year in range(1, int(lifetime_years) + 1):
        energy_y = annual_kwh * ((1 - degr) ** (year - 1))
        gross = energy_y * price_per_kwh
        net = gross - opex
        cumulative += net
        rows.append({
            "Year": year,
            "Energy_kWh": energy_y,
            "GrossSavings_EUR": gross,
            "OPEX_EUR": opex,
            "NetCashflow_EUR": net,
            "Cumulative_EUR": cumulative
        })

    df = pd.DataFrame(rows)

    payback = None
    hit = df[df["Cumulative_EUR"] >= 0]
    if len(hit) > 0:
        payback = int(hit.iloc[0]["Year"])

    roi = (df["NetCashflow_EUR"].sum() - capex) / capex if capex > 0 else None
    return df, payback, roi


def make_pdf_report(params: dict, df_monthly: pd.DataFrame, summary: dict, df_cashflow: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50

    if LOGO_PATH.exists():
        c.drawImage(str(LOGO_PATH), 50, y - 35, width=80, height=30, mask='auto')
        c.setFont("Helvetica-Bold", 18)
        c.drawString(140, y - 10, f"{APP_NAME} — Report")
    else:
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, y, f"{APP_NAME} — Report")

    y -= 45
    c.setFont("Helvetica", 10)
    c.drawString(50, y, f"Version: {APP_VERSION} | Author: {AUTHOR}")
    y -= 14
    c.drawString(50, y, "PV yield estimate using PVGIS data + financial analysis.")
    y -= 22

    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Inputs")
    y -= 14
    c.setFont("Helvetica", 10)

    input_lines = [
        f"City: {params['city']} | Location (lat, lon): {params['lat']:.6f}, {params['lon']:.6f}",
        f"System size: {params['peakpower']:.2f} kWp | Losses: {params['loss']}%",
        f"Tilt: {params['tilt']}° | Azimuth: {params['azimuth']}°",
        f"Energy price: €{params['price_per_kwh']:.2f}/kWh | CAPEX: €{params['capex']:.0f} | OPEX: {params['opex_percent']:.1f}%/yr",
        f"Lifetime: {params['lifetime_years']} yrs | Degradation: {params['degradation_percent']:.2f}%/yr",
    ]
    for line in input_lines:
        c.drawString(50, y, line)
        y -= 14

    y -= 8
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Results")
    y -= 14
    c.setFont("Helvetica", 10)

    payback_txt = "N/A" if summary["payback_years"] is None else f"{summary['payback_years']} years"
    roi_txt = "N/A" if summary["roi"] is None else f"{summary['roi']*100:.1f}%"

    result_lines = [
        f"Annual energy: {summary['annual_kwh']:.0f} kWh/year",
        f"Specific yield: {summary['specific_yield']:.0f} kWh/kWp/year",
        f"Net savings (Year 1): €{summary['net_savings_y1']:.0f}/year",
        f"Simple payback (year): {payback_txt}",
        f"ROI over lifetime: {roi_txt}",
    ]
    for line in result_lines:
        c.drawString(50, y, line)
        y -= 14

    y -= 6
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Monthly energy (kWh)")
    y -= 16
    c.setFont("Helvetica-Bold", 10)
    c.drawString(50, y, "Month")
    c.drawString(120, y, "Energy (kWh)")
    y -= 12
    c.setFont("Helvetica", 10)

    for _, row in df_monthly.iterrows():
        c.drawString(50, y, str(int(row["month"])))
        c.drawString(120, y, f"{float(row['Energy_kWh']):.0f}")
        y -= 12
        if y < 80:
            c.showPage()
            y = height - 60
            c.setFont("Helvetica", 10)

    c.showPage()
    y = height - 60
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Cashflow (first 10 years)")
    y -= 18

    c.setFont("Helvetica-Bold", 10)
    headers = ["Year", "Energy_kWh", "NetCashflow_EUR", "Cumulative_EUR"]
    x_positions = [50, 110, 230, 360]
    for h, x in zip(headers, x_positions):
        c.drawString(x, y, h)
    y -= 12
    c.setFont("Helvetica", 10)

    for _, r in df_cashflow.head(10).iterrows():
        c.drawString(x_positions[0], y, str(int(r["Year"])))
        c.drawString(x_positions[1], y, f"{r['Energy_kWh']:.0f}")
        c.drawString(x_positions[2], y, f"{r['NetCashflow_EUR']:.0f}")
        c.drawString(x_positions[3], y, f"{r['Cumulative_EUR']:.0f}")
        y -= 12
        if y < 60:
            break

    c.showPage()
    c.save()

    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


# -------------------- UI --------------------
st.subheader("Location")
city = st.selectbox("City (auto lat/lon)", list(CITY_DB.keys()), index=0)
default_lat, default_lon = CITY_DB[city]

col1, col2 = st.columns(2)
with col1:
    lat = st.number_input("Latitude", value=float(default_lat), format="%.6f")
    peakpower = st.number_input("System size (kWp)", value=5.0, min_value=0.1, step=0.1)
    loss = st.slider("Total losses (%)", 0, 30, 14)

with col2:
    lon = st.number_input("Longitude", value=float(default_lon), format="%.6f")
    tilt = st.slider("Tilt (deg)", 0, 90, 30)
    azimuth = st.slider("Azimuth (deg): 0=S, -90=E, +90=W", -180, 180, 0)

st.divider()

st.subheader("Economics")
e1, e2, e3 = st.columns(3)
with e1:
    price_per_kwh = st.number_input("Energy price (€/kWh)", value=0.12, min_value=0.01, step=0.01)
with e2:
    capex = st.number_input("CAPEX (system cost €)", value=4500.0, min_value=0.0, step=100.0)
with e3:
    opex_percent = st.number_input("OPEX (% of CAPEX / year)", value=1.0, min_value=0.0, step=0.5)

l1, l2 = st.columns(2)
with l1:
    lifetime_years = st.number_input("Project lifetime (years)", value=25, min_value=1, step=1)
with l2:
    degradation_percent = st.number_input("Degradation (%/year)", value=0.50, min_value=0.0, step=0.10)

st.divider()

colA, colB = st.columns(2)
calc = colA.button("Calculate", use_container_width=True)
gen_pdf = colB.button("Generate PDF report", use_container_width=True)


# State
if "df_monthly" not in st.session_state:
    st.session_state.df_monthly = None
if "summary" not in st.session_state:
    st.session_state.summary = None
if "df_cashflow" not in st.session_state:
    st.session_state.df_cashflow = None


if calc:
    try:
        with st.spinner("Calling PVGIS..."):
            data = pvgis_monthly(lat, lon, peakpower, loss, tilt, azimuth)

        df_monthly = extract_monthly_table(data)

        annual_kwh = float(df_monthly["Energy_kWh"].sum())
        specific_yield = annual_kwh / float(peakpower)

        gross_y1 = annual_kwh * float(price_per_kwh)
        opex_y1 = float(capex) * (float(opex_percent) / 100.0)
        net_y1 = gross_y1 - opex_y1

        df_cashflow, payback_years, roi = compute_financials(
            annual_kwh=annual_kwh,
            price_per_kwh=price_per_kwh,
            capex=capex,
            opex_percent=opex_percent,
            lifetime_years=lifetime_years,
            degradation_percent=degradation_percent,
        )

        summary = {
            "annual_kwh": annual_kwh,
            "specific_yield": specific_yield,
            "gross_savings_y1": gross_y1,
            "opex_y1": opex_y1,
            "net_savings_y1": net_y1,
            "payback_years": payback_years,
            "roi": roi,
        }

        st.session_state.df_monthly = df_monthly
        st.session_state.summary = summary
        st.session_state.df_cashflow = df_cashflow

    except Exception as e:
        st.error("Gabim gjate llogaritjes.")
        st.exception(e)


df_monthly = st.session_state.df_monthly
summary = st.session_state.summary
df_cashflow = st.session_state.df_cashflow

if df_monthly is not None and summary is not None and df_cashflow is not None:
    st.subheader("Dashboard")

    m1, m2, m3 = st.columns(3)
    m1.metric("Annual energy (kWh/year)", f"{summary['annual_kwh']:,.0f}")
    m2.metric("Specific yield (kWh/kWp/year)", f"{summary['specific_yield']:,.0f}")
    m3.metric("Payback (year)", "N/A" if summary["payback_years"] is None else str(summary["payback_years"]))

    s1, s2, s3 = st.columns(3)
    s1.metric("Gross savings (Year 1) €/yr", f"{summary['gross_savings_y1']:,.0f}")
    s2.metric("OPEX (Year 1) €/yr", f"{summary['opex_y1']:,.0f}")
    s3.metric("Net savings (Year 1) €/yr", f"{summary['net_savings_y1']:,.0f}")

    st.write("Monthly energy:")
    st.dataframe(df_monthly, use_container_width=True)

    fig1, ax1 = plt.subplots()
    ax1.plot(df_monthly["month"], df_monthly["Energy_kWh"], marker="o")
    ax1.set_xlabel("Month")
    ax1.set_ylabel("Energy (kWh)")
    ax1.grid(True)
    st.pyplot(fig1)
    plt.close(fig1)

    st.write("Cashflow (lifetime):")
    st.dataframe(df_cashflow, use_container_width=True)

    fig2, ax2 = plt.subplots()
    ax2.plot(df_cashflow["Year"], df_cashflow["Cumulative_EUR"], marker="o")
    ax2.set_xlabel("Year")
    ax2.set_ylabel("Cumulative (€)")
    ax2.grid(True)
    st.pyplot(fig2)
    plt.close(fig2)

    # Export Excel
    excel_buf = BytesIO()
    with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
        df_monthly.to_excel(writer, index=False, sheet_name="Monthly")
        pd.DataFrame([summary]).to_excel(writer, index=False, sheet_name="Summary")
        df_cashflow.to_excel(writer, index=False, sheet_name="Cashflow")
    excel_bytes = excel_buf.getvalue()

    st.download_button(
        "Download Excel (Monthly + Summary + Cashflow)",
        data=excel_bytes,
        file_name="SolarYield_Albania_PRO.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True
    )

    if gen_pdf:
        params = {
            "city": city,
            "lat": float(lat),
            "lon": float(lon),
            "peakpower": float(peakpower),
            "loss": float(loss),
            "tilt": float(tilt),
            "azimuth": float(azimuth),
            "price_per_kwh": float(price_per_kwh),
            "capex": float(capex),
            "opex_percent": float(opex_percent),
            "lifetime_years": int(lifetime_years),
            "degradation_percent": float(degradation_percent),
        }
        pdf_bytes = make_pdf_report(params, df_monthly, summary, df_cashflow)

        st.download_button(
            label="Download PDF (PRO report)",
            data=pdf_bytes,
            file_name="SolarYield_Albania_PRO_Report.pdf",
            mime="application/pdf",
            use_container_width=True
        )
else:
    st.info("Kliko **Calculate** për të gjeneruar rezultatet.")


# -------------------- FOOTER --------------------
st.divider()
st.markdown(
    f"""
    <div style='text-align: center; font-size: 14px; opacity: 0.7;'>
    © 2026 {AUTHOR} — {APP_NAME} {APP_VERSION}<br>
    Professional PV Yield & Financial Analysis Tool
    </div>
    """,
    unsafe_allow_html=True
)
st.divider()
st.caption(f"{COPYRIGHT} | Version {APP_VERSION}")