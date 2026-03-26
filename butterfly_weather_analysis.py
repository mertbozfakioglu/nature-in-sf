"""
Callophrys viridis (Western Green Hairstreak) Weather Analysis
Fetches all iNaturalist observations in San Francisco County, retrieves
historical weather data for each observation, and produces analysis graphs.
"""

import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import seaborn as sns
import time
import json
import os
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
TAXON_NAME = "Callophrys viridis"
SF_PLACE_ID = 854           # iNaturalist place_id for San Francisco
CACHE_FILE = "obs_cache.json"
OUTPUT_DIR = "butterfly_analysis_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── 1. Fetch iNaturalist observations ─────────────────────────────────────────

def fetch_observations():
    if os.path.exists(CACHE_FILE):
        print(f"Loading cached observations from {CACHE_FILE}")
        with open(CACHE_FILE) as f:
            return json.load(f)

    print(f"Fetching {TAXON_NAME} observations from iNaturalist...")
    all_obs = []
    page = 1
    per_page = 200
    url = "https://api.inaturalist.org/v1/observations"

    while True:
        params = {
            "taxon_name": TAXON_NAME,
            "place_id": SF_PLACE_ID,
            "per_page": per_page,
            "page": page,
            "order": "asc",
            "order_by": "observed_on",
        }
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        total = data.get("total_results", 0)

        all_obs.extend(results)
        print(f"  Page {page}: fetched {len(all_obs)}/{total}")

        if len(all_obs) >= total or not results:
            break
        page += 1
        time.sleep(0.5)   # be polite to the API

    with open(CACHE_FILE, "w") as f:
        json.dump(all_obs, f)
    print(f"Saved {len(all_obs)} observations to {CACHE_FILE}")
    return all_obs


def parse_observations(raw_obs):
    records = []
    for obs in raw_obs:
        # Location
        geo = obs.get("geojson")
        if not geo or obs.get("obscured"):
            continue   # skip obscured / locationless
        lon, lat = geo["coordinates"]

        # Date + time
        obs_date = obs.get("observed_on")
        if not obs_date:
            continue

        time_str = obs.get("time_observed_at")  # ISO8601 with offset already included
        if time_str:
            try:
                dt_local = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                hour_local = dt_local.hour  # .hour already reflects the local offset
            except Exception:
                hour_local = None
        else:
            hour_local = None

        records.append({
            "id": obs["id"],
            "date": obs_date,
            "hour_local": hour_local,
            "lat": lat,
            "lon": lon,
            "quality_grade": obs.get("quality_grade"),
        })

    df = pd.DataFrame(records)
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.month
    df["year"] = df["date"].dt.year
    df["day_of_year"] = df["date"].dt.day_of_year
    return df


# ── 2. Fetch weather for each observation ─────────────────────────────────────

WEATHER_CACHE = "weather_cache.json"

def load_weather_cache():
    if os.path.exists(WEATHER_CACHE):
        with open(WEATHER_CACHE) as f:
            return json.load(f)
    return {}

def save_weather_cache(cache):
    with open(WEATHER_CACHE, "w") as f:
        json.dump(cache, f)

def get_weather(lat, lon, date_str, hour, cache):
    """Return weather dict for a given location/date/hour using Open-Meteo archive."""
    key = f"{round(lat,3)},{round(lon,3)},{date_str}"
    if key not in cache:
        url = "https://archive-api.open-meteo.com/v1/archive"
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": date_str,
            "end_date": date_str,
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                      "shortwave_radiation,cloud_cover",
            "timezone": "America/Los_Angeles",
            "wind_speed_unit": "mph",
            "temperature_unit": "fahrenheit",
        }
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            cache[key] = resp.json().get("hourly", {})
        except Exception as e:
            print(f"  Weather fetch error for {key}: {e}")
            cache[key] = {}
        time.sleep(0.15)

    hourly = cache[key]
    if not hourly:
        return {}

    # Pick the closest hour (default to 10 AM peak butterfly time if unknown)
    h = int(hour) if (hour is not None and not (isinstance(hour, float) and np.isnan(hour))) else 10
    h = max(0, min(h, 23))

    times = hourly.get("time", [])
    idx = None
    for i, t in enumerate(times):
        if t.endswith(f"T{h:02d}:00"):
            idx = i
            break
    if idx is None:
        idx = h  # fallback

    def safe(key):
        vals = hourly.get(key, [])
        return vals[idx] if idx < len(vals) else None

    return {
        "temp_f": safe("temperature_2m"),
        "humidity": safe("relative_humidity_2m"),
        "wind_mph": safe("wind_speed_10m"),
        "solar_radiation": safe("shortwave_radiation"),
        "cloud_cover": safe("cloud_cover"),
    }


def enrich_with_weather(df):
    cache = load_weather_cache()
    print(f"Fetching weather for {len(df)} observations (cached: {len(cache)} days)...")

    rows = []
    for i, row in df.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        w = get_weather(row["lat"], row["lon"], date_str, row["hour_local"], cache)
        rows.append(w)
        if (i + 1) % 50 == 0:
            save_weather_cache(cache)
            print(f"  Processed {i+1}/{len(df)}...")

    save_weather_cache(cache)

    weather_df = pd.DataFrame(rows, index=df.index)
    return pd.concat([df, weather_df], axis=1)


# ── 3. Background weather distribution ───────────────────────────────────────

SF_LAT = 37.758   # centroid of SF county
SF_LON = -122.453
BACKGROUND_CACHE = "background_weather_cache.json"
DAYLIGHT_HOURS = range(8, 19)   # 8 AM–6 PM inclusive


def build_background_distribution(years):
    """
    Fetch all March–May daylight-hour weather at the SF centroid for every year
    in `years`. Returns a DataFrame with one row per (year, day, hour).
    """
    if os.path.exists(BACKGROUND_CACHE):
        print(f"Loading cached background weather from {BACKGROUND_CACHE}")
        with open(BACKGROUND_CACHE) as f:
            rows = json.load(f)
        return pd.DataFrame(rows)

    print(f"Fetching background weather for {len(years)} years × Mar–May…")
    url = "https://archive-api.open-meteo.com/v1/archive"
    rows = []

    today = datetime.today().strftime("%Y-%m-%d")
    for year in sorted(years):
        start = f"{year}-03-01"
        end   = min(f"{year}-05-31", today)
        if start > today:
            print(f"  {year}: skipping (future)")
            continue
        params = {
            "latitude": SF_LAT,
            "longitude": SF_LON,
            "start_date": start,
            "end_date":   end,
            "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,"
                      "shortwave_radiation,cloud_cover",
            "timezone": "America/Los_Angeles",
            "wind_speed_unit": "mph",
            "temperature_unit": "fahrenheit",
        }
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            hourly = resp.json().get("hourly", {})
        except Exception as e:
            print(f"  Background fetch error for {year}: {e}")
            time.sleep(2)
            continue

        times = hourly.get("time", [])
        for i, t in enumerate(times):
            dt = datetime.fromisoformat(t)
            if dt.hour not in DAYLIGHT_HOURS:
                continue
            rows.append({
                "year":             int(year),
                "month":            int(dt.month),
                "hour":             int(dt.hour),
                "temp_f":           float(hourly["temperature_2m"][i]),
                "humidity":         float(hourly["relative_humidity_2m"][i]),
                "wind_mph":         float(hourly["wind_speed_10m"][i]),
                "solar_radiation":  float(hourly["shortwave_radiation"][i]),
                "cloud_cover":      float(hourly["cloud_cover"][i]),
            })

        print(f"  {year}: {sum(1 for r in rows if r['year']==year)} daylight hours")
        time.sleep(0.3)

    with open(BACKGROUND_CACHE, "w") as f:
        json.dump(rows, f)
    print(f"Saved {len(rows)} background hours to {BACKGROUND_CACHE}")
    return pd.DataFrame(rows)


# ── 4. Plotting ───────────────────────────────────────────────────────────────

BUTTERFLY_COLOR = "#4a9e5c"
PALETTE = "YlGn"

def set_style():
    sns.set_theme(style="whitegrid", font_scale=1.1)
    plt.rcParams["figure.facecolor"] = "#f9f9f6"


def fig1_seasonal_overview(df):
    """Monthly observation counts + year-over-year heatmap."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Callophrys viridis — Seasonal Overview (San Francisco)",
                 fontsize=14, fontweight="bold", y=1.01)

    # Monthly bar chart
    ax = axes[0]
    month_counts = df.groupby("month").size().reindex(range(1, 13), fill_value=0)
    month_names = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    bars = ax.bar(month_names, month_counts, color=BUTTERFLY_COLOR, edgecolor="white", linewidth=0.5)
    ax.set_title("Observations by Month")
    ax.set_xlabel("Month")
    ax.set_ylabel("Number of Observations")
    ax.tick_params(axis="x", rotation=45)
    for bar, count in zip(bars, month_counts):
        if count > 0:
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                    str(count), ha="center", va="bottom", fontsize=8)

    # Year × Month heatmap
    ax = axes[1]
    pivot = df.groupby(["year", "month"]).size().unstack(fill_value=0)
    pivot.columns = [month_names[m-1] for m in pivot.columns]
    sns.heatmap(pivot, ax=ax, cmap=PALETTE, linewidths=0.5,
                linecolor="white", annot=True, fmt="d", cbar_kws={"label": "Obs count"})
    ax.set_title("Observations by Year & Month")
    ax.set_xlabel("Month")
    ax.set_ylabel("Year")

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "fig1_seasonal_overview.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig2_time_of_day(df):
    """Hour-of-day distribution for observations with known time."""
    timed = df.dropna(subset=["hour_local"])
    if len(timed) < 5:
        print("Skipping time-of-day plot (not enough timed observations)")
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    hour_counts = timed["hour_local"].value_counts().sort_index()
    all_hours = pd.Series(0, index=range(24))
    all_hours.update(hour_counts)

    colors = [BUTTERFLY_COLOR if 8 <= h <= 17 else "#cccccc" for h in all_hours.index]
    bars = ax.bar(all_hours.index, all_hours.values, color=colors, edgecolor="white")
    ax.set_title("Time of Day — When Are Butterflies Observed?\n"
                 "(green = daylight hours 8 AM–5 PM)", fontsize=13, fontweight="bold")
    ax.set_xlabel("Hour of Day (local time, PST)")
    ax.set_ylabel("Number of Observations")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h}:00" for h in range(0, 24, 2)], rotation=45)
    ax.axvspan(8, 17, alpha=0.07, color=BUTTERFLY_COLOR, label="Peak activity window")
    ax.legend()

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "fig2_time_of_day.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig3_weather_distributions(df):
    """Violin + box plots for each weather variable."""
    weather_vars = {
        "temp_f": ("Temperature (°F)", "#e07b39"),
        "humidity": ("Relative Humidity (%)", "#5b9bd5"),
        "wind_mph": ("Wind Speed (mph)", "#8e6bbf"),
        "solar_radiation": ("Solar Radiation (W/m²)", "#f0c428"),
        "cloud_cover": ("Cloud Cover (%)", "#888888"),
    }

    fig, axes = plt.subplots(1, len(weather_vars), figsize=(18, 6))
    fig.suptitle("Weather Conditions at Time of Observation",
                 fontsize=14, fontweight="bold")

    for ax, (var, (label, color)) in zip(axes, weather_vars.items()):
        data = df[var].dropna()
        if len(data) < 3:
            ax.set_visible(False)
            continue
        ax.violinplot(data, positions=[0], showmedians=True,
                      widths=0.6)
        parts = ax.violinplot(data, positions=[0], showmedians=True, widths=0.6)
        for pc in parts["bodies"]:
            pc.set_facecolor(color)
            pc.set_alpha(0.7)
        parts["cmedians"].set_color("black")
        parts["cmedians"].set_linewidth(2)

        # Overlay a strip
        jitter = np.random.uniform(-0.05, 0.05, len(data))
        ax.scatter(jitter, data, alpha=0.25, s=10, color=color, zorder=2)

        median_val = data.median()
        ax.set_title(f"{label}\nMedian: {median_val:.1f}", fontsize=10)
        ax.set_xticks([])
        ax.set_ylabel(label, fontsize=9)

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "fig3_weather_distributions.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig4_temp_bins(df):
    """Histogram of temperatures with observation density."""
    data = df["temp_f"].dropna()
    if len(data) < 5:
        return

    fig, ax = plt.subplots(figsize=(9, 5))
    n, bins, patches = ax.hist(data, bins=20, color=BUTTERFLY_COLOR,
                                edgecolor="white", linewidth=0.5)
    # Color-code by temperature feel
    for patch, left in zip(patches, bins[:-1]):
        if left < 50:
            patch.set_facecolor("#5b9bd5")
        elif left < 65:
            patch.set_facecolor(BUTTERFLY_COLOR)
        elif left < 78:
            patch.set_facecolor("#f0c428")
        else:
            patch.set_facecolor("#e07b39")

    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#5b9bd5", label="Cold (<50°F)"),
        Patch(facecolor=BUTTERFLY_COLOR, label="Cool (50–65°F)"),
        Patch(facecolor="#f0c428", label="Warm (65–78°F)"),
        Patch(facecolor="#e07b39", label="Hot (>78°F)"),
    ]
    ax.legend(handles=legend_elements, loc="upper right")
    ax.set_title("Temperature Distribution at Observation Times", fontsize=13, fontweight="bold")
    ax.set_xlabel("Temperature (°F)")
    ax.set_ylabel("Number of Observations")
    ax.axvline(data.median(), color="black", linestyle="--", linewidth=1.5,
               label=f"Median: {data.median():.1f}°F")
    ax.legend(handles=legend_elements + [
        plt.Line2D([0], [0], color="black", linestyle="--", label=f"Median: {data.median():.1f}°F")
    ])

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "fig4_temperature_histogram.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig5_solar_vs_cloud(df):
    """Solar radiation vs cloud cover scatter + marginal histograms."""
    sub = df.dropna(subset=["solar_radiation", "cloud_cover"])
    if len(sub) < 5:
        return

    g = sns.JointGrid(data=sub, x="cloud_cover", y="solar_radiation",
                      height=7, ratio=5)
    g.plot_joint(sns.scatterplot, alpha=0.4, color=BUTTERFLY_COLOR, s=30)
    g.plot_marginals(sns.histplot, color=BUTTERFLY_COLOR, bins=20)
    g.set_axis_labels("Cloud Cover (%)", "Solar Radiation (W/m²)")
    g.figure.suptitle("Solar Radiation vs Cloud Cover at Observation Times",
                      fontsize=12, fontweight="bold", y=1.01)

    path = os.path.join(OUTPUT_DIR, "fig5_solar_vs_cloud.png")
    g.figure.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig6_wind_vs_temp(df):
    """2D hexbin: temperature vs wind speed."""
    sub = df.dropna(subset=["temp_f", "wind_mph"])
    if len(sub) < 5:
        return

    fig, ax = plt.subplots(figsize=(9, 6))
    hb = ax.hexbin(sub["temp_f"], sub["wind_mph"], gridsize=20,
                   cmap="YlGn", mincnt=1, linewidths=0.2)
    cb = fig.colorbar(hb, ax=ax, label="Number of Observations")
    ax.set_xlabel("Temperature (°F)")
    ax.set_ylabel("Wind Speed (mph)")
    ax.set_title("Temperature vs Wind Speed — Observation Density",
                 fontsize=13, fontweight="bold")

    # Annotate sweet spot
    sweet = sub[(sub["temp_f"].between(55, 75)) & (sub["wind_mph"] < 10)]
    pct = len(sweet) / len(sub) * 100
    ax.axvspan(55, 75, alpha=0.08, color="gold")
    ax.axhspan(0, 10, alpha=0.08, color="gold")
    ax.text(0.02, 0.97, f"{pct:.0f}% of obs in sweet spot\n(55–75°F, <10 mph wind)",
            transform=ax.transAxes, va="top", fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor="lightyellow", alpha=0.8))

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "fig6_wind_vs_temp.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig7_humidity_buckets(df):
    """Observations bucketed by humidity range."""
    data = df["humidity"].dropna()
    if len(data) < 5:
        return

    bins = [0, 40, 55, 70, 85, 101]
    labels = ["<40%\n(Very dry)", "40–55%\n(Dry)", "55–70%\n(Moderate)",
              "70–85%\n(Humid)", ">85%\n(Very humid)"]
    df2 = df.copy()
    df2["humidity_bucket"] = pd.cut(df2["humidity"], bins=bins, labels=labels)
    counts = df2["humidity_bucket"].value_counts().reindex(labels, fill_value=0)

    fig, ax = plt.subplots(figsize=(9, 5))
    colors = ["#e07b39", "#f0c428", BUTTERFLY_COLOR, "#5b9bd5", "#3a6ea5"]
    bars = ax.bar(counts.index, counts.values, color=colors, edgecolor="white", linewidth=0.5)
    for bar, count in zip(bars, counts.values):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
                str(count), ha="center", va="bottom", fontsize=9)
    ax.set_title("Observations by Humidity Range", fontsize=13, fontweight="bold")
    ax.set_xlabel("Relative Humidity")
    ax.set_ylabel("Number of Observations")

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "fig7_humidity_buckets.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig8_summary_dashboard(df):
    """One-page dashboard with key stats and optimal conditions summary."""
    weather_vars = ["temp_f", "humidity", "wind_mph", "solar_radiation", "cloud_cover"]
    complete = df.dropna(subset=weather_vars)

    if len(complete) < 5:
        print("Not enough complete weather data for dashboard")
        return

    fig = plt.figure(figsize=(16, 10))
    fig.patch.set_facecolor("#f9f9f6")
    fig.suptitle("Callophrys viridis — Optimal Viewing Conditions Dashboard\n"
                 "San Francisco County · iNaturalist Observations",
                 fontsize=15, fontweight="bold", y=0.98)

    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.45, wspace=0.35)

    var_info = [
        ("temp_f",          "Temperature (°F)",     "#e07b39"),
        ("humidity",        "Humidity (%)",          "#5b9bd5"),
        ("wind_mph",        "Wind Speed (mph)",      "#8e6bbf"),
        ("solar_radiation", "Solar Radiation (W/m²)","#f0c428"),
        ("cloud_cover",     "Cloud Cover (%)",       "#888888"),
    ]

    for i, (var, label, color) in enumerate(var_info):
        row, col = divmod(i, 3)
        ax = fig.add_subplot(gs[row, col])
        data = complete[var].dropna()
        ax.hist(data, bins=15, color=color, alpha=0.8, edgecolor="white", linewidth=0.4)
        q25, q75 = data.quantile(0.25), data.quantile(0.75)
        ax.axvspan(q25, q75, alpha=0.25, color=color,
                   label=f"IQR: {q25:.0f}–{q75:.0f}")
        ax.axvline(data.median(), color="black", linestyle="--", linewidth=1.5)
        ax.set_title(f"{label}\nMedian {data.median():.1f}  |  IQR {q25:.0f}–{q75:.0f}",
                     fontsize=9, fontweight="bold")
        ax.set_xlabel(label, fontsize=8)
        ax.set_ylabel("Obs", fontsize=8)
        ax.tick_params(labelsize=7)

    # Sixth panel: text summary
    ax_txt = fig.add_subplot(gs[1, 2])
    ax_txt.axis("off")

    t = complete["temp_f"]
    h = complete["humidity"]
    w = complete["wind_mph"]
    s = complete["solar_radiation"]
    c = complete["cloud_cover"]

    summary = (
        f"OPTIMAL VIEWING CONDITIONS\n"
        f"Based on {len(complete)} observations\n\n"
        f"Temperature:  {t.quantile(0.25):.0f}–{t.quantile(0.75):.0f}°F\n"
        f"  (median {t.median():.0f}°F)\n\n"
        f"Humidity:     {h.quantile(0.25):.0f}–{h.quantile(0.75):.0f}%\n"
        f"  (median {h.median():.0f}%)\n\n"
        f"Wind speed:   <{w.quantile(0.75):.0f} mph\n"
        f"  (median {w.median():.0f} mph)\n\n"
        f"Solar rad:    >{s.quantile(0.25):.0f} W/m²\n"
        f"  (median {s.median():.0f} W/m²)\n\n"
        f"Cloud cover:  <{c.quantile(0.75):.0f}%\n"
        f"  (median {c.median():.0f}%)\n\n"
        f"Peak months:  March – May\n"
        f"Peak hours:   10 AM – 2 PM"
    )

    ax_txt.text(0.05, 0.97, summary, transform=ax_txt.transAxes,
                fontsize=10, va="top", fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.6", facecolor="#eaf4ec",
                          edgecolor=BUTTERFLY_COLOR, linewidth=2))

    path = os.path.join(OUTPUT_DIR, "fig8_summary_dashboard.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig9_sightability(obs_df, bg_df):
    """
    Sightability index: how much more (or less) likely are butterflies to be
    observed at a given condition compared to that condition simply being common?

    Index = (obs_fraction_in_bin) / (background_fraction_in_bin)
    > 1.0  → genuinely preferred condition
    = 1.0  → observed exactly as often as base rate predicts
    < 1.0  → avoided / less active under these conditions
    """
    var_cfg = [
        ("temp_f",          "Temperature (°F)",      "#e07b39", np.arange(44, 82, 4)),
        ("humidity",        "Relative Humidity (%)", "#5b9bd5", np.arange(30, 101, 10)),
        ("wind_mph",        "Wind Speed (mph)",      "#8e6bbf", np.arange(0, 32, 4)),
        ("solar_radiation", "Solar Radiation (W/m²)","#c8a800", np.arange(0, 1100, 100)),
        ("cloud_cover",     "Cloud Cover (%)",       "#666666", np.arange(0, 101, 10)),
    ]

    fig, axes = plt.subplots(1, 5, figsize=(22, 6))
    fig.patch.set_facecolor("#f9f9f6")
    fig.suptitle(
        "Callophrys viridis — Sightability Index\n"
        "How much more likely are butterflies observed under each condition\n"
        "vs. how common that condition is in SF during spring (Mar–May)?",
        fontsize=13, fontweight="bold", y=1.02,
    )

    for ax, (var, label, color, bins) in zip(axes, var_cfg):
        obs_vals = obs_df[var].dropna()
        bg_vals  = bg_df[var].dropna()

        if len(obs_vals) < 5 or len(bg_vals) < 5:
            ax.set_visible(False)
            continue

        obs_counts, _ = np.histogram(obs_vals, bins=bins)
        bg_counts,  _ = np.histogram(bg_vals,  bins=bins)

        obs_frac = obs_counts / obs_counts.sum()
        bg_frac  = bg_counts  / bg_counts.sum()

        # Sightability: avoid div-by-zero for empty background bins
        with np.errstate(divide="ignore", invalid="ignore"):
            index = np.where(bg_frac > 0, obs_frac / bg_frac, np.nan)

        centers = (bins[:-1] + bins[1:]) / 2
        width   = (bins[1] - bins[0]) * 0.8

        # Background bars (grey, light)
        ax.bar(centers, bg_frac * 100, width=width,
               color="#cccccc", alpha=0.6, label="Background (% of spring hours)", zorder=1)
        # Observation bars (colored, semi-transparent)
        ax.bar(centers, obs_frac * 100, width=width,
               color=color, alpha=0.55, label="Observations (% of obs)", zorder=2)

        ax.set_xlabel(label, fontsize=9)
        ax.set_ylabel("% frequency", fontsize=9)
        ax.tick_params(labelsize=8)

        # Sightability line on twin axis
        ax2 = ax.twinx()
        valid = ~np.isnan(index)
        ax2.plot(centers[valid], index[valid], color="black", linewidth=2,
                 marker="o", markersize=4, zorder=5, label="Sightability index")
        ax2.axhline(1.0, color="red", linestyle="--", linewidth=1, alpha=0.7)
        ax2.set_ylabel("Sightability index\n(1.0 = base rate)", fontsize=8)
        ax2.tick_params(labelsize=8)

        # Find peak bin
        peak_idx = np.nanargmax(index)
        ax2.annotate(
            f"Peak:\n{centers[peak_idx]:.0f}",
            xy=(centers[peak_idx], index[peak_idx]),
            xytext=(5, 5), textcoords="offset points",
            fontsize=7, color="darkgreen", fontweight="bold",
        )

        ax.set_title(label, fontsize=10, fontweight="bold")

        # Combined legend on first panel only
        if ax == axes[0]:
            handles1, labels1 = ax.get_legend_handles_labels()
            handles2, labels2 = ax2.get_legend_handles_labels()
            ax.legend(handles1 + handles2, labels1 + labels2,
                      fontsize=7, loc="upper right")

    plt.tight_layout()
    path = os.path.join(OUTPUT_DIR, "fig9_sightability_index.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def fig10_sightability_dashboard(obs_df, bg_df):
    """
    Summary dashboard using the sightability index to report optimal ranges
    (the bin with highest index for each variable).
    """
    var_cfg = [
        ("temp_f",          "Temperature (°F)",      "#e07b39", np.arange(44, 82, 4)),
        ("humidity",        "Relative Humidity (%)", "#5b9bd5", np.arange(30, 101, 10)),
        ("wind_mph",        "Wind Speed (mph)",      "#8e6bbf", np.arange(0, 32, 4)),
        ("solar_radiation", "Solar Radiation (W/m²)","#c8a800", np.arange(0, 1100, 100)),
        ("cloud_cover",     "Cloud Cover (%)",       "#666666", np.arange(0, 101, 10)),
    ]

    fig = plt.figure(figsize=(16, 10))
    fig.patch.set_facecolor("#f9f9f6")
    fig.suptitle(
        "Callophrys viridis — Sightability Index Dashboard\n"
        "San Francisco County · Normalized for background weather conditions",
        fontsize=14, fontweight="bold", y=0.99,
    )
    gs = gridspec.GridSpec(2, 3, figure=fig, hspace=0.5, wspace=0.38)

    summary_lines = ["BEST CONDITIONS TO FIND THEM\n(by sightability index)\n"]
    opt_ranges = {}

    for i, (var, label, color, bins) in enumerate(var_cfg):
        row, col = divmod(i, 3)
        ax = fig.add_subplot(gs[row, col])

        obs_vals = obs_df[var].dropna()
        bg_vals  = bg_df[var].dropna()
        obs_counts, _ = np.histogram(obs_vals, bins=bins)
        bg_counts,  _ = np.histogram(bg_vals,  bins=bins)
        obs_frac = obs_counts / obs_counts.sum()
        bg_frac  = bg_counts  / bg_counts.sum()
        with np.errstate(divide="ignore", invalid="ignore"):
            index = np.where(bg_frac > 0, obs_frac / bg_frac, np.nan)

        centers = (bins[:-1] + bins[1:]) / 2
        width   = (bins[1] - bins[0]) * 0.75

        bar_colors = [color if (not np.isnan(v) and v >= 1.0) else "#dddddd"
                      for v in index]
        bars = ax.bar(centers, index, width=width, color=bar_colors,
                      edgecolor="white", linewidth=0.4)
        ax.axhline(1.0, color="red", linestyle="--", linewidth=1.2, alpha=0.8,
                   label="Base rate (1.0)")
        ax.set_title(label, fontsize=9, fontweight="bold")
        ax.set_xlabel(label, fontsize=8)
        ax.set_ylabel("Sightability index", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7)

        # Mark peak
        peak_idx = int(np.nanargmax(index))
        ax.bar(centers[peak_idx], index[peak_idx], width=width,
               color=color, edgecolor="black", linewidth=1.5)

        # Top third of bins by sightability → "optimal range"
        valid_idx = np.where(~np.isnan(index))[0]
        if len(valid_idx):
            threshold = np.nanpercentile(index, 67)
            good = [centers[j] for j in valid_idx if index[j] >= threshold]
            if good:
                opt_ranges[label] = (min(good) - (bins[1]-bins[0])/2,
                                     max(good) + (bins[1]-bins[0])/2,
                                     index[peak_idx])

        summary_lines.append(
            f"{label}:\n  peak {centers[peak_idx]:.0f}  "
            f"(index {index[peak_idx]:.2f}x)\n"
        )

    # Text panel
    ax_txt = fig.add_subplot(gs[1, 2])
    ax_txt.axis("off")
    text = "\n".join(summary_lines)
    text += "\nIndex > 1.0 = more likely than\nbackground rate alone predicts.\n"
    text += "Grey bars = below base rate."
    ax_txt.text(0.05, 0.97, text, transform=ax_txt.transAxes,
                fontsize=9, va="top", fontfamily="monospace",
                bbox=dict(boxstyle="round,pad=0.5", facecolor="#eaf4ec",
                          edgecolor=BUTTERFLY_COLOR, linewidth=2))

    path = os.path.join(OUTPUT_DIR, "fig10_sightability_dashboard.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"Saved {path}")


def print_text_summary(df):
    weather_vars = ["temp_f", "humidity", "wind_mph", "solar_radiation", "cloud_cover"]
    complete = df.dropna(subset=weather_vars)
    print("\n" + "="*60)
    print(f"CALLOPHRYS VIRIDIS — SF COUNTY ANALYSIS SUMMARY")
    print("="*60)
    print(f"Total observations: {len(df)}")
    print(f"  With location:    {len(df)}")
    print(f"  With weather:     {len(complete)}")
    print(f"  With time of day: {df['hour_local'].notna().sum()}")
    if len(df):
        print(f"\nDate range:  {df['date'].min().date()} to {df['date'].max().date()}")
        mc = df.groupby('month').size()
        top_months = mc.nlargest(3)
        month_names = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',
                       7:'Jul',8:'Aug',9:'Sep',10:'Oct',11:'Nov',12:'Dec'}
        print(f"Peak months: {', '.join(month_names[m] for m in top_months.index)}")
    if len(complete):
        print(f"\nMedian conditions at observations:")
        print(f"  Temperature:      {complete['temp_f'].median():.1f}°F")
        print(f"  Humidity:         {complete['humidity'].median():.0f}%")
        print(f"  Wind speed:       {complete['wind_mph'].median():.1f} mph")
        print(f"  Solar radiation:  {complete['solar_radiation'].median():.0f} W/m²")
        print(f"  Cloud cover:      {complete['cloud_cover'].median():.0f}%")
        print(f"\nIQR (25th–75th percentile) — the sweet spot:")
        for var, label, fmt in [
            ("temp_f","Temperature",".0f"),
            ("humidity","Humidity",".0f"),
            ("wind_mph","Wind speed",".1f"),
            ("solar_radiation","Solar rad",".0f"),
            ("cloud_cover","Cloud cover",".0f"),
        ]:
            q25 = complete[var].quantile(0.25)
            q75 = complete[var].quantile(0.75)
            print(f"  {label:18s}: {q25:{fmt}} – {q75:{fmt}}")
    print("="*60)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    set_style()

    # 1. Fetch observations
    raw = fetch_observations()
    df = parse_observations(raw)
    print(f"\nParsed {len(df)} mappable observations")

    # 2. Enrich with weather
    df = enrich_with_weather(df)

    # Save enriched data
    csv_path = os.path.join(OUTPUT_DIR, "observations_with_weather.csv")
    df.to_csv(csv_path, index=False)
    print(f"Saved enriched data to {csv_path}")

    # 3. Build background distribution
    years = sorted(df["year"].unique())
    bg_df = build_background_distribution(years)
    print(f"Background: {len(bg_df)} daylight hours across {len(years)} years")

    # 4. Generate plots
    print("\nGenerating plots...")
    fig1_seasonal_overview(df)
    fig2_time_of_day(df)
    fig3_weather_distributions(df)
    fig4_temp_bins(df)
    fig5_solar_vs_cloud(df)
    fig6_wind_vs_temp(df)
    fig7_humidity_buckets(df)
    fig8_summary_dashboard(df)
    fig9_sightability(df, bg_df)
    fig10_sightability_dashboard(df, bg_df)

    # 5. Print text summary
    print_text_summary(df)

    print(f"\nAll outputs saved to: {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
