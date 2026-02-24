import requests
import pandas as pd

PVGIS_BASE = "https://re.jrc.ec.europa.eu/api/v5_2/"

def get_monthly_irradiation(lat: float, lon: float, tilt: float, azimuth: float):
    """
    Returns monthly plane-of-array irradiation (kWh/m²) and PVGIS meta.
    Uses PVGIS 'PVcalc' endpoint with monthly outputs.
    """
    params = {
        "lat": lat,
        "lon": lon,
        "raddatabase": "PVGIS-SARAH2",  # good coverage for Europe
        "peakpower": 1.0,               # 1 kWp, we scale later
        "loss": 14,                     # default loss; we can override in model
        "angle": tilt,
        "aspect": azimuth,              # PVGIS: 0 = South, -90 = East, 90 = West
        "outputformat": "json",
    }

    url = PVGIS_BASE + "PVcalc"
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    monthly = data["outputs"]["monthly"]
    df = pd.DataFrame(monthly)
    # PVGIS monthly has fields like: month, E_m (kWh), H(i)_m (kWh/m2), etc.
    # For 1 kWp, E_m is kWh/kWp per month effectively.
    meta = data.get("meta", {})
    return df, meta