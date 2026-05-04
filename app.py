"""
Draft Athletic Qualities Dashboard

Streamlit app for ranking draft players from a Google Sheet with the same tabs as the
provided workbook:
  - Sprint
  - Anthropometrics
  - Force Plate

Scoring philosophy
------------------
Athlete Score: current athletic qualities from CMJ + sprint outputs.
  - Concentric Impulse
  - mRSI / RSI-modified
  - Sprint times

Physical Potential Score: size + power/reactive qualities + speed.
  - Height
  - Bodyweight
  - mRSI / RSI-modified
  - Relative peak power
  - Sprint times
  - Pitchers only: wingspan / arm span included in potential

The app uses percentile scoring so new draft classes can be added without hard-coded norms.
Higher is always better after direction is handled; sprint times are inverted because faster
means lower time.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials


# -----------------------------
# Streamlit page setup
# -----------------------------
st.set_page_config(
    page_title="Draft Athletic Qualities",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_TITLE = "Draft Athletic Qualities + Physical Potential"
REQUIRED_TABS = ["Sprint", "Anthropometrics", "Force Plate"]


# -----------------------------
# Column aliasing
# -----------------------------
@dataclass(frozen=True)
class MetricSpec:
    canonical: str
    aliases: Tuple[str, ...]
    higher_is_better: bool = True


METRIC_SPECS: Dict[str, MetricSpec] = {
    "player_id": MetricSpec("player_id", ("DPL ID", "dpl id", "Player ID", "player_id", "ID")),
    "name": MetricSpec("name", ("Full Name", "About", "Name", "Player", "Full Name Reverse", "full name reverse")),
    "name_reverse": MetricSpec("name_reverse", ("Full Name Reverse", "full name reverse")),
    "first_name": MetricSpec("first_name", ("First Name", "GivenName", "first_name")),
    "last_name": MetricSpec("last_name", ("Last Name", "FamilyName", "last_name")),
    "year": MetricSpec("year", ("Year", "year")),
    "date": MetricSpec("date", ("Date", "date")),
    "position": MetricSpec("position", ("Position", "position")),
    "school": MetricSpec("school", ("School Name", "School", "school")),
    "school_type": MetricSpec("school_type", ("School Type", "school_type")),
    "bats": MetricSpec("bats", ("Bats", "bats")),
    "throws": MetricSpec("throws", ("Throws", "throws")),
    "height": MetricSpec(
        "height",
        (
            "Height",
            "Height 2",
            "Stature Calc",
            "Stature Height 1",
            "Stature Height 2",
            "Stature Height 3",
        ),
    ),
    "bodyweight": MetricSpec(
        "bodyweight",
        (
            "Body Weight (kg)",
            "Body Weight [kg]",
            "ForceDecks BW",
            "Weight (kg)",
            "Body Weight",
            "Body Weight 2",
            "Stature Body Weight 1",
            "Stature Body Weight 2",
            "Stature Body Weight 3",
        ),
    ),
    "wingspan": MetricSpec(
        "wingspan",
        (
            "Arm Span",
            "Arm Span 2",
            "Stature Arm Span 1",
            "Stature Arm Span 2",
            "Stature Arm Span 3",
            "Wingspan",
            "Wing Span",
        ),
    ),
    "ci": MetricSpec(
        "ci",
        (
            "Concentric Impulse [Ns]",
            "Concentric Impulse [N s]",
            "Concentric Impulse",
            "Positive Impulse [Ns]",
        ),
    ),
    "mrsi": MetricSpec(
        "mrsi",
        (
            "RSI-Modified [m/s]",
            "RSI-modified [m/s]",
            "CMJ RSI-Modified [m/s]",
            "Max RSI-Modified [m/s]",
            "Mean RSI-Modified [m/s]",
            "RSI-modified (Imp-Mom) [m/s]",
            "mRSI",
            "MRSI",
        ),
    ),
    "rel_peak_power": MetricSpec(
        "rel_peak_power",
        (
            "Peak Power / BM [W/kg]",
            "Max Peak Power / BM [W/kg]",
            "CMJ Max Peak Power BM wkg",
            "CMJ Max Peak Power [W/kg]",
            "Concentric Peak Power / BM [W/kg]",
            "Takeoff Concentric Peak Power / BM [W/kg]",
        ),
    ),
    "peak_power": MetricSpec(
        "peak_power",
        (
            "Peak Power [W]",
            "Max Peak Power [W]",
            "CMJ Max Peak Power [W]",
            "Concentric Peak Power [W]",
        ),
    ),
    "sprint_10yd": MetricSpec("sprint_10yd", ("10yd", "10 yd", "10 Yard", "10-yard", "10 Yard Split"), False),
    "sprint_20yd": MetricSpec("sprint_20yd", ("20yd", "20 yd", "20 Yard", "20-yard", "20 Yard Split"), False),
    "sprint_30yd": MetricSpec("sprint_30yd", ("30yd", "30 yd", "30 Yard", "30-yard", "30 Yard Split"), False),
}

PLAYER_ID_COL = "player_id"


# -----------------------------
# Google Sheets connection
# -----------------------------
def _service_account_info_from_secrets() -> dict:
    """Read service account JSON from Streamlit secrets.

    Supports either:
      [gcp_service_account]
      type = "service_account"
      ...

    or:
      GOOGLE_SERVICE_ACCOUNT_JSON = "{...}"
    """
    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])

    if "GOOGLE_SERVICE_ACCOUNT_JSON" in st.secrets:
        raw = st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]
        return json.loads(raw) if isinstance(raw, str) else dict(raw)

    raise RuntimeError(
        "Missing Google credentials. Add a [gcp_service_account] block or "
        "GOOGLE_SERVICE_ACCOUNT_JSON to .streamlit/secrets.toml / Streamlit Cloud secrets."
    )


@st.cache_resource(show_spinner=False)
def get_gspread_client() -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(_service_account_info_from_secrets(), scopes=scopes)
    return gspread.authorize(creds)


@st.cache_data(ttl=300, show_spinner=False)
def load_worksheet(sheet_id_or_url: str, worksheet_name: str) -> pd.DataFrame:
    client = get_gspread_client()
    spreadsheet = client.open_by_url(sheet_id_or_url) if sheet_id_or_url.startswith("http") else client.open_by_key(sheet_id_or_url)
    worksheet = spreadsheet.worksheet(worksheet_name)
    records = worksheet.get_all_records(empty2zero=False, head=1)
    df = pd.DataFrame(records)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    df = df.loc[:, [c for c in df.columns if str(c).strip() != ""]]
    return df


# -----------------------------
# Data cleaning helpers
# -----------------------------
def find_first_existing_column(df: pd.DataFrame, aliases: Sequence[str]) -> Optional[str]:
    exact = {str(c).strip(): c for c in df.columns}
    lower = {str(c).strip().lower(): c for c in df.columns}

    for alias in aliases:
        if alias in exact:
            return exact[alias]
        if alias.lower() in lower:
            return lower[alias.lower()]

    # Fuzzy fallback for punctuation/spacing differences.
    def norm(x: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", x.lower())

    normalized_cols = {norm(str(c)): c for c in df.columns}
    for alias in aliases:
        key = norm(alias)
        if key in normalized_cols:
            return normalized_cols[key]
    return None


def coalesce_columns(df: pd.DataFrame, aliases: Sequence[str]) -> pd.Series:
    output = pd.Series(np.nan, index=df.index, dtype="object")
    for alias in aliases:
        col = find_first_existing_column(df, (alias,))
        if col is not None:
            output = output.where(output.notna() & (output.astype(str).str.strip() != ""), df[col])
    return output


def to_numeric(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
        .replace({"": np.nan, "nan": np.nan, "None": np.nan})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def clean_id(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s = s.str.replace(r"\.0$", "", regex=True)
    s = s.replace({"": np.nan, "nan": np.nan, "None": np.nan})
    return s


def reverse_name_to_normal(name: object) -> object:
    if pd.isna(name):
        return np.nan
    text = str(name).strip()
    if not text:
        return np.nan
    pieces = text.split()
    if len(pieces) == 2:
        return f"{pieces[1]} {pieces[0]}"
    return text


def normalize_height(value: object) -> float:
    """Normalize height-like values to inches.

    Handles:
      - inches: 74, 74.5
      - centimeters: 188, 188.5
      - feet-inches strings: 6'2", 6-2
    """
    if pd.isna(value):
        return np.nan
    text = str(value).strip().lower().replace("\u2019", "'").replace("\u201d", '"')
    if not text or text in {"nan", "none"}:
        return np.nan

    feet_in_match = re.match(r"^(\d+)\s*['-]\s*(\d+(?:\.\d+)?)", text)
    if feet_in_match:
        return float(feet_in_match.group(1)) * 12 + float(feet_in_match.group(2))

    val = pd.to_numeric(text.replace("in", "").replace("cm", ""), errors="coerce")
    if pd.isna(val):
        return np.nan
    val = float(val)
    if val > 100:  # likely cm
        return val / 2.54
    return val


def normalize_bodyweight(value: object) -> float:
    """Normalize bodyweight-like values to pounds.

    Handles kg and pounds. Values under 140 are treated as kg for baseball populations.
    """
    val = pd.to_numeric(str(value).replace(",", "").strip(), errors="coerce")
    if pd.isna(val):
        return np.nan
    val = float(val)
    if val < 140:  # likely kg
        return val * 2.2046226218
    return val


def normalize_anthro_units(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ["height", "wingspan"]:
        if col in out.columns:
            out[col] = out[col].apply(normalize_height)
    if "bodyweight" in out.columns:
        out["bodyweight"] = out["bodyweight"].apply(normalize_bodyweight)
    return out


def select_best_available_name(row: pd.Series) -> str:
    for col in ["name", "name_from_reverse", "full_name_from_first_last", "name_reverse"]:
        if col in row and pd.notna(row[col]) and str(row[col]).strip():
            return str(row[col]).strip()
    return str(row.get("player_id", "Unknown"))


def canonicalize(df: pd.DataFrame, wanted: Sequence[str]) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    for key in wanted:
        spec = METRIC_SPECS[key]
        out[key] = coalesce_columns(df, spec.aliases)

    if "player_id" in out.columns:
        out["player_id"] = clean_id(out["player_id"])

    # Build better display names when source has reverse/first/last columns.
    if "name_reverse" in wanted or "name" in wanted:
        reverse_source = coalesce_columns(df, METRIC_SPECS["name_reverse"].aliases)
        out["name_from_reverse"] = reverse_source.apply(reverse_name_to_normal)

    first = coalesce_columns(df, METRIC_SPECS["first_name"].aliases)
    last = coalesce_columns(df, METRIC_SPECS["last_name"].aliases)
    full = (first.fillna("").astype(str).str.strip() + " " + last.fillna("").astype(str).str.strip()).str.strip()
    out["full_name_from_first_last"] = full.replace({"": np.nan})

    numeric_cols = [
        "year",
        "height",
        "bodyweight",
        "wingspan",
        "ci",
        "mrsi",
        "rel_peak_power",
        "peak_power",
        "sprint_10yd",
        "sprint_20yd",
        "sprint_30yd",
    ]
    for col in numeric_cols:
        if col in out.columns:
            out[col] = to_numeric(out[col])

    if "date" in out.columns:
        out["date"] = pd.to_datetime(out["date"], errors="coerce")

    out = normalize_anthro_units(out)
    return out


def aggregate_best_metrics(df: pd.DataFrame, group_col: str, metrics: Iterable[str]) -> pd.DataFrame:
    agg = {m: "max" for m in metrics if m in df.columns}
    if not agg:
        return pd.DataFrame(columns=[group_col])
    return df.groupby(group_col, dropna=False).agg(agg).reset_index()


def aggregate_fastest_sprints(sprint: pd.DataFrame) -> pd.DataFrame:
    metrics = ["sprint_10yd", "sprint_20yd", "sprint_30yd"]
    existing = [m for m in metrics if m in sprint.columns]
    if not existing:
        return pd.DataFrame(columns=["player_id"])
    return sprint.groupby("player_id", dropna=False)[existing].min().reset_index()


def aggregate_profile_fields(df: pd.DataFrame, fields: Iterable[str]) -> pd.DataFrame:
    fields = [f for f in fields if f in df.columns]
    if not fields:
        return pd.DataFrame(columns=["player_id"])

    work = df.copy()
    # Latest profile row if date exists; otherwise first non-empty values by player.
    sort_cols = [c for c in ["date", "year"] if c in work.columns]
    if sort_cols:
        work = work.sort_values(sort_cols)

    def last_valid(series: pd.Series):
        s = series.dropna()
        s = s[s.astype(str).str.strip() != ""]
        return s.iloc[-1] if len(s) else np.nan

    return work.groupby("player_id", dropna=False)[fields].agg(last_valid).reset_index()


def percentile_score(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    if s.notna().sum() == 0:
        return pd.Series(np.nan, index=s.index)
    ranks = s.rank(pct=True, method="average") * 100
    if not higher_is_better:
        ranks = 101 - ranks
    return ranks.clip(0, 100)


def weighted_mean(row: pd.Series, weights: Dict[str, float]) -> float:
    present = {k: w for k, w in weights.items() if k in row.index and pd.notna(row[k])}
    if not present:
        return np.nan
    total_weight = sum(present.values())
    return sum(row[k] * w for k, w in present.items()) / total_weight


def is_pitcher_position(position: object) -> bool:
    if pd.isna(position):
        return False
    text = str(position).lower()
    pitcher_terms = ["pitcher", "rhp", "lhp", "starter", "reliever", "starting pitcher", "right handed pitcher", "left handed pitcher"]
    return any(term in text for term in pitcher_terms)


def build_model(sprint_df: pd.DataFrame, anthro_df: pd.DataFrame, force_df: pd.DataFrame) -> pd.DataFrame:
    sprint = canonicalize(sprint_df, ["player_id", "name", "name_reverse", "first_name", "last_name", "year", "sprint_10yd", "sprint_20yd", "sprint_30yd"])
    anthro = canonicalize(
        anthro_df,
        [
            "player_id",
            "name",
            "name_reverse",
            "first_name",
            "last_name",
            "year",
            "date",
            "position",
            "school_type",
            "height",
            "bodyweight",
            "wingspan",
            "bats",
            "throws",
        ],
    )
    force = canonicalize(
        force_df,
        [
            "player_id",
            "name",
            "name_reverse",
            "first_name",
            "last_name",
            "year",
            "date",
            "position",
            "school",
            "school_type",
            "ci",
            "mrsi",
            "rel_peak_power",
            "peak_power",
            "bodyweight",
        ],
    )

    for frame_name, frame in [("Sprint", sprint), ("Anthropometrics", anthro), ("Force Plate", force)]:
        if "player_id" not in frame.columns or frame["player_id"].notna().sum() == 0:
            st.warning(f"{frame_name} does not have a usable DPL ID/player ID column.")

    sprint_best = aggregate_fastest_sprints(sprint.dropna(subset=["player_id"]))
    anthro_profile = aggregate_profile_fields(
        anthro.dropna(subset=["player_id"]),
        ["name", "name_from_reverse", "full_name_from_first_last", "year", "position", "school_type", "height", "bodyweight", "wingspan", "bats", "throws"],
    )
    force_best = aggregate_best_metrics(
        force.dropna(subset=["player_id"]),
        "player_id",
        ["ci", "mrsi", "rel_peak_power", "peak_power"],
    )
    force_profile = aggregate_profile_fields(
        force.dropna(subset=["player_id"]),
        ["name", "name_from_reverse", "full_name_from_first_last", "year", "position", "school", "school_type", "bodyweight"],
    )

    player_ids = pd.Series(
        pd.concat(
            [
                sprint.get("player_id", pd.Series(dtype="object")),
                anthro.get("player_id", pd.Series(dtype="object")),
                force.get("player_id", pd.Series(dtype="object")),
            ],
            ignore_index=True,
        ).dropna().unique(),
        name="player_id",
    )
    model = pd.DataFrame({"player_id": player_ids})

    for piece in [anthro_profile, force_profile.add_suffix("_force").rename(columns={"player_id_force": "player_id"}), force_best, sprint_best]:
        if not piece.empty:
            model = model.merge(piece, on="player_id", how="left")

    # Coalesce duplicate profile fields from anthro and force.
    for base in ["name", "name_from_reverse", "full_name_from_first_last", "year", "position", "school_type", "bodyweight"]:
        force_col = f"{base}_force"
        if force_col in model.columns:
            if base in model.columns:
                model[base] = model[base].where(model[base].notna() & (model[base].astype(str).str.strip() != ""), model[force_col])
            else:
                model[base] = model[force_col]

    model["player_name"] = model.apply(select_best_available_name, axis=1)
    model["is_pitcher"] = model.get("position", pd.Series(index=model.index, dtype="object")).apply(is_pitcher_position)

    # Sprint composite uses lower-is-better percentile scoring for each split, then averages available splits.
    for col in ["sprint_10yd", "sprint_20yd", "sprint_30yd"]:
        if col in model.columns:
            model[f"{col}_score"] = percentile_score(model[col], higher_is_better=False)
    sprint_score_cols = [c for c in ["sprint_10yd_score", "sprint_20yd_score", "sprint_30yd_score"] if c in model.columns]
    model["sprint_score"] = model[sprint_score_cols].mean(axis=1, skipna=True) if sprint_score_cols else np.nan

    # Component scores.
    score_specs = {
        "ci_score": ("ci", True),
        "mrsi_score": ("mrsi", True),
        "rel_peak_power_score": ("rel_peak_power", True),
        "height_score": ("height", True),
        "bodyweight_score": ("bodyweight", True),
        "wingspan_score": ("wingspan", True),
    }
    for score_col, (raw_col, hib) in score_specs.items():
        model[score_col] = percentile_score(model[raw_col], higher_is_better=hib) if raw_col in model.columns else np.nan

    athlete_weights = {
        "ci_score": 0.40,
        "mrsi_score": 0.30,
        "sprint_score": 0.30,
    }
    hitter_potential_weights = {
        "height_score": 0.20,
        "bodyweight_score": 0.15,
        "mrsi_score": 0.20,
        "rel_peak_power_score": 0.20,
        "sprint_score": 0.25,
    }
    pitcher_potential_weights = {
        "height_score": 0.18,
        "bodyweight_score": 0.12,
        "wingspan_score": 0.20,
        "mrsi_score": 0.17,
        "rel_peak_power_score": 0.15,
        "sprint_score": 0.18,
    }

    model["athlete_score"] = model.apply(lambda r: weighted_mean(r, athlete_weights), axis=1)
    model["potential_score"] = model.apply(
        lambda r: weighted_mean(r, pitcher_potential_weights if r.get("is_pitcher", False) else hitter_potential_weights),
        axis=1,
    )
    model["overall_score"] = model[["athlete_score", "potential_score"]].mean(axis=1, skipna=True)

    # Rank: 1 is best.
    for score in ["overall_score", "athlete_score", "potential_score"]:
        model[f"{score}_rank"] = model[score].rank(ascending=False, method="min")

    return model.sort_values(["overall_score", "athlete_score"], ascending=False).reset_index(drop=True)


def format_height(inches: object) -> str:
    if pd.isna(inches):
        return "—"
    inches = float(inches)
    ft = int(inches // 12)
    inch = inches - ft * 12
    return f"{ft}'{inch:.1f}\""


def coverage_table(model: pd.DataFrame) -> pd.DataFrame:
    fields = {
        "Concentric Impulse": "ci",
        "mRSI": "mrsi",
        "Relative Peak Power": "rel_peak_power",
        "Sprint": "sprint_score",
        "Height": "height",
        "Bodyweight": "bodyweight",
        "Wingspan": "wingspan",
    }
    rows = []
    n = len(model)
    for label, col in fields.items():
        present = int(model[col].notna().sum()) if col in model.columns else 0
        rows.append({"Metric": label, "Players With Data": present, "Coverage %": present / n * 100 if n else 0})
    return pd.DataFrame(rows)


def display_metric(label: str, value: object, suffix: str = "", digits: int = 1):
    if pd.isna(value):
        st.metric(label, "—")
    else:
        st.metric(label, f"{float(value):.{digits}f}{suffix}")


# -----------------------------
# UI
# -----------------------------
st.title(APP_TITLE)
st.caption("Live draft dashboard powered by Google Sheets tabs matching the original workbook.")

with st.sidebar:
    st.header("Google Sheet")
    default_sheet = st.secrets.get("GOOGLE_SHEET_ID", "") if hasattr(st, "secrets") else ""
    sheet_id_or_url = st.text_input(
        "Sheet ID or URL",
        value=default_sheet,
        placeholder="Paste Google Sheet URL or ID",
        help="The Google Sheet must contain Sprint, Anthropometrics, and Force Plate tabs.",
    )

    st.divider()
    st.header("Filters")
    year_filter_enabled = st.checkbox("Use year filter", value=False)
    min_data_points = st.slider("Minimum available score components", 1, 7, 2)

    st.divider()
    if st.button("Refresh Google Sheet data", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

if not sheet_id_or_url:
    st.info("Paste your Google Sheet ID/URL in the sidebar, or add GOOGLE_SHEET_ID to Streamlit secrets.")
    st.stop()

try:
    with st.spinner("Loading Google Sheet tabs…"):
        sprint_raw = load_worksheet(sheet_id_or_url, "Sprint")
        anthro_raw = load_worksheet(sheet_id_or_url, "Anthropometrics")
        force_raw = load_worksheet(sheet_id_or_url, "Force Plate")
except Exception as exc:
    st.error("Could not load the Google Sheet.")
    st.exception(exc)
    st.stop()

model = build_model(sprint_raw, anthro_raw, force_raw)

if model.empty:
    st.warning("No players were found after joining the source tabs by DPL ID.")
    st.stop()

# Apply optional year filter after model build.
if year_filter_enabled and "year" in model.columns and model["year"].notna().any():
    years = sorted([int(y) for y in pd.to_numeric(model["year"], errors="coerce").dropna().unique()])
    selected_years = st.sidebar.multiselect("Years", years, default=years)
    model = model[pd.to_numeric(model["year"], errors="coerce").isin(selected_years)]

score_component_cols = ["ci_score", "mrsi_score", "rel_peak_power_score", "sprint_score", "height_score", "bodyweight_score", "wingspan_score"]
model["available_score_components"] = model[[c for c in score_component_cols if c in model.columns]].notna().sum(axis=1)
model = model[model["available_score_components"] >= min_data_points].copy()

# Sidebar position filters depend on model values.
with st.sidebar:
    positions = sorted([p for p in model.get("position", pd.Series(dtype="object")).dropna().astype(str).unique() if p.strip()])
    selected_positions = st.multiselect("Positions", positions, default=[])
    only_pitchers = st.checkbox("Pitchers only", value=False)
    search = st.text_input("Search player", value="")

if selected_positions:
    model = model[model["position"].astype(str).isin(selected_positions)]
if only_pitchers:
    model = model[model["is_pitcher"]]
if search.strip():
    model = model[model["player_name"].str.contains(search.strip(), case=False, na=False)]

# KPI row.
col1, col2, col3, col4 = st.columns(4)
col1.metric("Players", f"{len(model):,}")
col2.metric("Median Athlete Score", "—" if model["athlete_score"].dropna().empty else f"{model['athlete_score'].median():.1f}")
col3.metric("Median Potential Score", "—" if model["potential_score"].dropna().empty else f"{model['potential_score'].median():.1f}")
col4.metric("Pitchers", f"{int(model['is_pitcher'].sum()):,}")

# Main tabs.
rankings_tab, player_tab, visuals_tab, coverage_tab, raw_tab, methods_tab = st.tabs(
    ["Rankings", "Player Detail", "Visuals", "Data Coverage", "Raw Sheets", "Methods"]
)

with rankings_tab:
    st.subheader("Draft Board")
    display_cols = [
        "overall_score_rank",
        "player_name",
        "player_id",
        "year",
        "position",
        "school_type",
        "overall_score",
        "athlete_score",
        "potential_score",
        "ci",
        "mrsi",
        "rel_peak_power",
        "sprint_10yd",
        "sprint_20yd",
        "sprint_30yd",
        "height",
        "bodyweight",
        "wingspan",
        "available_score_components",
    ]
    existing_display_cols = [c for c in display_cols if c in model.columns]
    table = model[existing_display_cols].copy()
    rename_map = {
        "overall_score_rank": "Rank",
        "player_name": "Player",
        "player_id": "DPL ID",
        "year": "Year",
        "position": "Position",
        "school_type": "School Type",
        "overall_score": "Overall",
        "athlete_score": "Athlete Score",
        "potential_score": "Potential",
        "ci": "Concentric Impulse",
        "mrsi": "mRSI",
        "rel_peak_power": "Rel Peak Power",
        "sprint_10yd": "10yd",
        "sprint_20yd": "20yd",
        "sprint_30yd": "30yd",
        "height": "Height (in)",
        "bodyweight": "Bodyweight (lb)",
        "wingspan": "Wingspan (in)",
        "available_score_components": "Data Components",
    }
    table = table.rename(columns=rename_map)
    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Rank": st.column_config.NumberColumn(format="%d"),
            "Overall": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
            "Athlete Score": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
            "Potential": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=100),
            "Concentric Impulse": st.column_config.NumberColumn(format="%.1f"),
            "mRSI": st.column_config.NumberColumn(format="%.2f"),
            "Rel Peak Power": st.column_config.NumberColumn(format="%.1f"),
            "10yd": st.column_config.NumberColumn(format="%.3f"),
            "20yd": st.column_config.NumberColumn(format="%.3f"),
            "30yd": st.column_config.NumberColumn(format="%.3f"),
            "Height (in)": st.column_config.NumberColumn(format="%.1f"),
            "Bodyweight (lb)": st.column_config.NumberColumn(format="%.1f"),
            "Wingspan (in)": st.column_config.NumberColumn(format="%.1f"),
        },
    )

    csv = table.to_csv(index=False).encode("utf-8")
    st.download_button("Download current board as CSV", csv, "draft_athletic_board.csv", "text/csv")

with player_tab:
    st.subheader("Player Detail")
    players = model["player_name"].fillna(model["player_id"]).tolist()
    selected_player = st.selectbox("Select player", players)
    player = model.loc[model["player_name"].eq(selected_player)].iloc[0]

    top_cols = st.columns(3)
    with top_cols[0]:
        display_metric("Overall", player.get("overall_score"))
    with top_cols[1]:
        display_metric("Athlete Score", player.get("athlete_score"))
    with top_cols[2]:
        display_metric("Physical Potential", player.get("potential_score"))

    st.markdown(
        f"**Position:** {player.get('position', '—')}  \n"
        f"**DPL ID:** {player.get('player_id', '—')}  \n"
        f"**School Type:** {player.get('school_type', '—')}  \n"
        f"**Pitcher model:** {'Yes' if bool(player.get('is_pitcher', False)) else 'No'}"
    )

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        display_metric("Concentric Impulse", player.get("ci"), digits=1)
        display_metric("mRSI", player.get("mrsi"), digits=2)
    with m2:
        display_metric("Relative Peak Power", player.get("rel_peak_power"), " W/kg", digits=1)
        display_metric("Bodyweight", player.get("bodyweight"), " lb", digits=1)
    with m3:
        st.metric("Height", format_height(player.get("height")))
        st.metric("Wingspan", format_height(player.get("wingspan")))
    with m4:
        display_metric("10yd", player.get("sprint_10yd"), " s", digits=3)
        display_metric("30yd", player.get("sprint_30yd"), " s", digits=3)

    component_cols = [
        "ci_score",
        "mrsi_score",
        "sprint_score",
        "height_score",
        "bodyweight_score",
        "rel_peak_power_score",
        "wingspan_score",
    ]
    component_labels = {
        "ci_score": "Concentric Impulse",
        "mrsi_score": "mRSI",
        "sprint_score": "Sprint Composite",
        "height_score": "Height",
        "bodyweight_score": "Bodyweight",
        "rel_peak_power_score": "Relative Peak Power",
        "wingspan_score": "Wingspan",
    }
    comp = pd.DataFrame(
        {
            "Component": [component_labels[c] for c in component_cols if c in model.columns],
            "Percentile Score": [player.get(c) for c in component_cols if c in model.columns],
        }
    ).dropna()
    if not comp.empty:
        fig = px.bar(comp, x="Component", y="Percentile Score", range_y=[0, 100], text="Percentile Score")
        fig.update_traces(texttemplate="%{text:.0f}", textposition="outside")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

with visuals_tab:
    st.subheader("Score Map")
    plot_df = model.dropna(subset=["athlete_score", "potential_score"]).copy()
    if plot_df.empty:
        st.info("Need athlete and potential scores to draw the map.")
    else:
        fig = px.scatter(
            plot_df,
            x="athlete_score",
            y="potential_score",
            color="is_pitcher",
            size="overall_score",
            hover_name="player_name",
            hover_data=["position", "ci", "mrsi", "rel_peak_power", "sprint_30yd", "height", "bodyweight", "wingspan"],
            labels={"athlete_score": "Athlete Score", "potential_score": "Physical Potential", "is_pitcher": "Pitcher"},
            range_x=[0, 100],
            range_y=[0, 100],
        )
        fig.update_layout(height=600, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Metric Relationships")
    x_metric = st.selectbox("X-axis", ["ci", "mrsi", "rel_peak_power", "sprint_30yd", "height", "bodyweight", "wingspan"], index=0)
    y_metric = st.selectbox("Y-axis", ["athlete_score", "potential_score", "overall_score", "sprint_score"], index=1)
    rel_df = model.dropna(subset=[x_metric, y_metric]).copy()
    if not rel_df.empty:
        fig2 = px.scatter(
            rel_df,
            x=x_metric,
            y=y_metric,
            color="position",
            hover_name="player_name",
            trendline="ols" if len(rel_df) >= 8 else None,
        )
        fig2.update_layout(height=500, margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Not enough data for that metric relationship.")

with coverage_tab:
    st.subheader("Data Coverage")
    cov = coverage_table(model)
    st.dataframe(
        cov,
        use_container_width=True,
        hide_index=True,
        column_config={"Coverage %": st.column_config.ProgressColumn(format="%.1f%%", min_value=0, max_value=100)},
    )

    missing_view = model[
        [
            "player_name",
            "player_id",
            "position",
            "ci",
            "mrsi",
            "rel_peak_power",
            "sprint_10yd",
            "sprint_20yd",
            "sprint_30yd",
            "height",
            "bodyweight",
            "wingspan",
            "available_score_components",
        ]
    ].sort_values("available_score_components")
    st.caption("Players with fewer available components are the first ones to clean up in the Google Sheet.")
    st.dataframe(missing_view, use_container_width=True, hide_index=True)

with raw_tab:
    st.subheader("Raw Google Sheet Tabs")
    st.caption("These are read-only previews. Edit the connected Google Sheet, then click Refresh.")
    raw_choice = st.radio("Tab", REQUIRED_TABS, horizontal=True)
    raw_map = {"Sprint": sprint_raw, "Anthropometrics": anthro_raw, "Force Plate": force_raw}
    st.dataframe(raw_map[raw_choice].head(500), use_container_width=True, hide_index=True)

with methods_tab:
    st.subheader("Scoring Method")
    st.markdown(
        """
**Join key:** all tabs are joined by `DPL ID`.

**Athlete Score** estimates current athletic qualities:

- Concentric impulse percentile: 40%
- mRSI / RSI-modified percentile: 30%
- Sprint composite percentile: 30%

**Physical Potential Score** estimates size/speed/power upside. For non-pitchers:

- Height percentile: 20%
- Bodyweight percentile: 15%
- mRSI percentile: 20%
- Relative peak power percentile: 20%
- Sprint composite percentile: 25%

**Pitcher Physical Potential Score** adds wingspan/arm span:

- Height percentile: 18%
- Bodyweight percentile: 12%
- Wingspan percentile: 20%
- mRSI percentile: 17%
- Relative peak power percentile: 15%
- Sprint composite percentile: 18%

**Sprint scoring:** lower times are better. The app ranks `10yd`, `20yd`, and `30yd` as inverted percentiles and averages the available splits.

**Aggregation:** best force-plate values and fastest sprint splits are used per player; the latest available profile row is used for height, bodyweight, wingspan, position, and school fields.

**Missing values:** scores re-weight automatically using available components, but the minimum component filter lets you prevent thin profiles from ranking too highly.
        """
    )
