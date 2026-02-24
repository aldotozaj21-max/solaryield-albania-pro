import pandas as pd

def estimate_energy_from_pvgis(monthly_df: pd.DataFrame, system_kwp: float, additional_losses_pct: float = 0.0):
    """
    monthly_df from PVGIS PVcalc with peakpower=1.0.
    E_m is monthly energy for 1 kWp (kWh). Scale by system_kwp and extra losses.
    """
    df = monthly_df.copy()

    if "E_m" not in df.columns:
        raise ValueError("PVGIS response missing 'E_m' monthly energy field.")

    # scale kWh (for 1kWp) -> kWh for system
    df["E_kWh_raw"] = df["E_m"] * system_kwp

    # Apply additional losses as multiplicative factor
    loss_factor = max(0.0, 1.0 - additional_losses_pct / 100.0)
    df["E_kWh"] = df["E_kWh_raw"] * loss_factor

    annual = df["E_kWh"].sum()
    return df[["month", "E_kWh"]], float(annual)