from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Tuple

import gspread
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from google.oauth2.service_account import Credentials


# ============================================================
# Page setup
# ============================================================

st.set_page_config(
    page_title="Draft Athletic Dashboard",
    page_icon="⚾",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_TITLE = "Draft Athletic Qualities + Physical Potential"

DEFAULT_GOOGLE_SHEET_ID = "1J27zw_UngoTNdq6VKPF6RhB8aqfmvlpX60GtrXjOsbs"

REQUIRED_TABS = {
    "Sprint": "Sprint",
    "Anthropometrics": "Anthropometrics",
    "Force Plate": "Force Plate",
}


# ============================================================
# Password gate
# ============================================================

def password_gate() -> None:
    password = st.secrets.get("DASHBOARD_PASSWORD", None)

    if not password:
        return

    if st.session_state.get("authenticated", False):
        return

    st.title("Draft Athletic Dashboard")
    entered = st.text_input("Password", type="password")

    if entered == password:
        st.session_state["authenticated"] = True
        st.rerun()

    if entered:
        st.error("Incorrect password.")

    st.stop()


password_gate()


# ============================================================
# Google Sheets helpers
# ============================================================

def get_sheet_id() -> str:
    return st.secrets.get("GOOGLE_SHEET_ID", DEFAULT_GOOGLE_SHEET_ID)


def get_google_credentials_dict() -> dict:
    """
    Supports this Streamlit secrets format:

    GOOGLE_CREDENTIALS = '''{
      "type": "service_account",
      ...
    }'''

    Also supports:
    GOOGLE_SERVICE_ACCOUNT_JSON = '''{...}'''

    Or:
    [gcp_service_account]
    type = "service_account"
    ...
    """
    if "GOOGLE_CREDENTIALS" in st.secrets:
        raw = st.secrets["GOOGLE_CREDENTIALS"]
        return json.loads(raw) if isinstance(raw, str) else dict(raw)

    if "GOOGLE_SERVICE_ACCOUNT_JSON" in st.secrets:
        raw = st.secrets["GOOGLE_SERVICE_ACCOUNT_JSON"]
        return json.loads(raw) if isinstance(raw, str) else dict(raw)

    if "gcp_service_account" in st.secrets:
        return dict(st.secrets["gcp_service_account"])

    raise RuntimeError(
        "Missing Google credentials. Add GOOGLE_CREDENTIALS, "
        "GOOGLE_SERVICE_ACCOUNT_JSON, or [gcp_service_account] to Streamlit secrets."
    )


@st.cache_resource(show_spinner=False)
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    creds_dict = get_google_credentials_dict()

    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=scopes,
    )

    return gspread.authorize(creds)


@st.cache_data(ttl=300, show_spinner=False)
def load_worksheet(sheet_id: str, worksheet_name: str) -> pd.DataFrame:
    client = get_gspread_client()
    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.worksheet(worksheet_name)
    values = worksheet.get_all_records()

    df = pd.DataFrame(values)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")

    return df


# ============================================================
# Column helpers
# ============================================================

COLUMN_ALIASES: Dict[str, List[str]] = {
    "player_id": [
        "DPL ID",
        "dpl id",
        "Player ID",
        "player_id",
        "ID",
    ],
    "name": [
        "Full Name",
        "Name",
        "Player",
        "About",
        "Full Name Reverse",
    ],
    "first_name": [
        "First Name",
        "GivenName",
    ],
    "last_name": [
        "Last Name",
        "FamilyName",
    ],
    "position": [
        "Position",
        "position",
        "POS",
    ],
    "school": [
        "School Name",
        "School",
        "school",
    ],
    "year": [
        "Year",
        "year",
        "Draft Year",
    ],
    "height": [
        "Height",
        "Height 2",
        "Stature Calc",
        "Stature Height 1",
        "Stature Height 2",
        "Stature Height 3",
    ],
    "bodyweight": [
        "Body Weight (kg)",
        "Body Weight [kg]",
        "ForceDecks BW",
        "Weight (kg)",
        "Body Weight",
        "Body Weight 2",
        "Stature Body Weight 1",
        "Stature Body Weight 2",
        "Stature Body Weight 3",
    ],
    "wingspan": [
        "Arm Span",
        "Arm Span 2",
        "Stature Arm Span 1",
        "Stature Arm Span 2",
        "Stature Arm Span 3",
        "Wingspan",
        "Wing Span",
    ],
    "ci": [
        "Concentric Impulse [Ns]",
        "Concentric Impulse [N s]",
        "Concentric Impulse",
        "Positive Impulse [Ns]",
    ],
    "mrsi": [
        "RSI-Modified [m/s]",
        "RSI-modified [m/s]",
        "CMJ RSI-Modified [m/s]",
        "Max RSI-Modified [m/s]",
        "Mean RSI-Modified [m/s]",
        "RSI-modified (Imp-Mom) [m/s]",
        "mRSI",
        "MRSI",
    ],
    "rel_peak_power": [
        "Peak Power / BM [W/kg]",
        "Max Peak Power / BM [W/kg]",
        "CMJ Max Peak Power BM wkg",
        "CMJ Max Peak Power [W/kg]",
        "Concentric Peak Power / BM [W/kg]",
        "Takeoff Concentric Peak Power / BM [W/kg]",
    ],
    "peak_power": [
        "Peak Power [W]",
        "Max Peak Power [W]",
        "CMJ Max Peak Power [W]",
        "Concentric Peak Power [W]",
    ],
    "sprint_10yd": [
        "10yd",
        "10 yd",
        "10 Yard",
        "10-yard",
        "10 Yard Split",
    ],
    "sprint_20yd": [
        "20yd",
        "20 yd",
        "20 Yard",
        "20-yard",
        "20 Yard Split",
    ],
    "sprint_30yd": [
        "30yd",
        "30 yd",
        "30 Yard",
        "30-yard",
        "30 Yard Split",
    ],
}


def find_column(df: pd.DataFrame, canonical_name: str) -> Optional[str]:
    aliases = COLUMN_ALIASES.get(canonical_name, [])

    lower_map = {str(c).strip().lower(): c for c in df.columns}

    for alias in aliases:
        key = alias.strip().lower()
        if key in lower_map:
            return lower_map[key]

    return None


def numeric_series(df: pd.DataFrame, canonical_name: str) -> pd.Series:
    col = find_column(df, canonical_name)

    if col is None:
        return pd.Series(np.nan, index=df.index)

    return pd.to_numeric(df[col], errors="coerce")


def text_series(df: pd.DataFrame, canonical_name: str) -> pd.Series:
    col = find_column(df, canonical_name)

    if col is None:
        return pd.Series("", index=df.index)

    return df[col].astype(str).str.strip()


def normalize_position(pos: object) -> str:
    text = str(pos).strip().upper()

    if text in ["RHP", "LHP", "P", "HP", "PITCHER"]:
        return "P"

    if text in ["C", "1B", "2B", "3B", "SS", "OF", "CF", "LF", "RF"]:
        return text

    if "P" == text:
        return "P"

    return text


def is_pitcher(pos: object) -> bool:
    return normalize_position(pos) == "P"


def make_name(df: pd.DataFrame) -> pd.Series:
    name = text_series(df, "name")

    if name.replace("", np.nan).notna().any():
        return name

    first = text_series(df, "first_name")
    last = text_series(df, "last_name")
    full = (first + " " + last).str.strip()

    return full.replace("", "Unknown")


# ============================================================
# Data prep
# ============================================================

def prep_anthro(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["player_id"] = text_series(df, "player_id")
    out["name"] = make_name(df)
    out["position"] = text_series(df, "position").map(normalize_position)
    out["school"] = text_series(df, "school")
    out["year"] = text_series(df, "year")
    out["height"] = numeric_series(df, "height")
    out["bodyweight"] = numeric_series(df, "bodyweight")
    out["wingspan"] = numeric_series(df, "wingspan")

    out = out[out["player_id"].astype(str).str.len() > 0]
    out = out.drop_duplicates(subset=["player_id"], keep="last")

    return out


def prep_force_plate(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["player_id"] = text_series(df, "player_id")
    out["ci"] = numeric_series(df, "ci")
    out["mrsi"] = numeric_series(df, "mrsi")
    out["rel_peak_power"] = numeric_series(df, "rel_peak_power")
    out["peak_power"] = numeric_series(df, "peak_power")

    out = out[out["player_id"].astype(str).str.len() > 0]

    grouped = (
        out.groupby("player_id", as_index=False)
        .agg(
            ci=("ci", "max"),
            mrsi=("mrsi", "max"),
            rel_peak_power=("rel_peak_power", "max"),
            peak_power=("peak_power", "max"),
        )
    )

    return grouped


def prep_sprint(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    out["player_id"] = text_series(df, "player_id")
    out["sprint_10yd"] = numeric_series(df, "sprint_10yd")
    out["sprint_20yd"] = numeric_series(df, "sprint_20yd")
    out["sprint_30yd"] = numeric_series(df, "sprint_30yd")

    out = out[out["player_id"].astype(str).str.len() > 0]

    grouped = (
        out.groupby("player_id", as_index=False)
        .agg(
            sprint_10yd=("sprint_10yd", "min"),
            sprint_20yd=("sprint_20yd", "min"),
            sprint_30yd=("sprint_30yd", "min"),
        )
    )

    return grouped


def combine_data(
    anthro: pd.DataFrame,
    force: pd.DataFrame,
    sprint: pd.DataFrame,
) -> pd.DataFrame:
    df = anthro.merge(force, on="player_id", how="left")
    df = df.merge(sprint, on="player_id", how="left")

    sprint_cols = ["sprint_10yd", "sprint_20yd", "sprint_30yd"]

    df["has_sprint"] = df[sprint_cols].notna().any(axis=1)
    df["player_type"] = np.where(df["position"].map(is_pitcher), "Pitcher", "Position Player")

    df["sprint_status"] = np.select(
        [
            df["player_type"].eq("Pitcher"),
            df["has_sprint"].eq(True),
            df["has_sprint"].eq(False),
        ],
        [
            "Not expected for pitchers",
            "Sprint data available",
            "Missing / not tested",
        ],
        default="Unknown",
    )

    return df


# ============================================================
# Scoring helpers
# ============================================================

def percentile_score(
    values: pd.Series,
    higher_is_better: bool = True,
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")

    if numeric.notna().sum() < 2:
        return pd.Series(np.nan, index=values.index)

    ranks = numeric.rank(pct=True, method="average") * 100

    if not higher_is_better:
        ranks = 101 - ranks

    return ranks.clip(0, 100)


def weighted_score(
    row: pd.Series,
    metric_weights: Dict[str, float],
) -> float:
    available_scores = []
    available_weights = []

    for metric, weight in metric_weights.items():
        value = row.get(metric)

        if pd.notna(value):
            available_scores.append(float(value))
            available_weights.append(float(weight))

    if len(available_scores) == 0:
        return np.nan

    total_weight = sum(available_weights)

    if total_weight <= 0:
        return np.nan

    return float(np.average(available_scores, weights=available_weights))


def sprint_composite_from_percentiles(df: pd.DataFrame) -> pd.Series:
    sprint_percentile_cols = [
        "sprint_10yd_pct",
        "sprint_20yd_pct",
        "sprint_30yd_pct",
    ]

    return df[sprint_percentile_cols].mean(axis=1, skipna=True)


def apply_group_percentiles(df: pd.DataFrame, comparison_mode: str) -> pd.DataFrame:
    """
    Pitchers are always compared only to pitchers.

    Position players can be compared either to:
      - all position players
      - same position only
    """
    scored_parts = []

    pitcher_df = df[df["player_type"] == "Pitcher"].copy()
    pp_df = df[df["player_type"] == "Position Player"].copy()

    metric_directions = {
        "ci": True,
        "mrsi": True,
        "rel_peak_power": True,
        "peak_power": True,
        "height": True,
        "bodyweight": True,
        "wingspan": True,
        "sprint_10yd": False,
        "sprint_20yd": False,
        "sprint_30yd": False,
    }

    def score_within_group(group: pd.DataFrame) -> pd.DataFrame:
        group = group.copy()

        for metric, higher_is_better in metric_directions.items():
            group[f"{metric}_pct"] = percentile_score(
                group[metric],
                higher_is_better=higher_is_better,
            )

        group["sprint_pct"] = sprint_composite_from_percentiles(group)

        return group

    if len(pitcher_df) > 0:
        pitcher_scored = score_within_group(pitcher_df)
        pitcher_scored["comparison_group"] = "Pitchers only"
        scored_parts.append(pitcher_scored)

    if len(pp_df) > 0:
        if comparison_mode == "Same position only":
            position_parts = []

            for _, group in pp_df.groupby("position", dropna=False):
                g = score_within_group(group)
                g["comparison_group"] = "Same position only"
                position_parts.append(g)

            pp_scored = pd.concat(position_parts, ignore_index=True) if position_parts else pp_df

        else:
            pp_scored = score_within_group(pp_df)
            pp_scored["comparison_group"] = "All position players"

        scored_parts.append(pp_scored)

    if not scored_parts:
        return df

    scored = pd.concat(scored_parts, ignore_index=True)

    return scored


def add_scores(df: pd.DataFrame, comparison_mode: str) -> pd.DataFrame:
    df = apply_group_percentiles(df, comparison_mode=comparison_mode)

    position_athlete_weights = {
        "ci_pct": 0.40,
        "mrsi_pct": 0.30,
        "sprint_pct": 0.30,
    }

    pitcher_athlete_weights = {
        "ci_pct": 0.55,
        "mrsi_pct": 0.45,
    }

    position_potential_weights = {
        "height_pct": 0.20,
        "bodyweight_pct": 0.15,
        "mrsi_pct": 0.20,
        "rel_peak_power_pct": 0.20,
        "sprint_pct": 0.25,
    }

    pitcher_potential_weights = {
        "height_pct": 0.22,
        "bodyweight_pct": 0.15,
        "wingspan_pct": 0.25,
        "mrsi_pct": 0.20,
        "rel_peak_power_pct": 0.18,
    }

    athlete_scores = []
    potential_scores = []

    for _, row in df.iterrows():
        if row["player_type"] == "Pitcher":
            athlete_scores.append(weighted_score(row, pitcher_athlete_weights))
            potential_scores.append(weighted_score(row, pitcher_potential_weights))
        else:
            athlete_scores.append(weighted_score(row, position_athlete_weights))
            potential_scores.append(weighted_score(row, position_potential_weights))

    df["athlete_score"] = athlete_scores
    df["physical_potential_score"] = potential_scores

    df["overall_score"] = df[["athlete_score", "physical_potential_score"]].mean(axis=1, skipna=True)

    return df


def grade_from_score(score: float) -> str:
    if pd.isna(score):
        return "Incomplete"

    if score >= 90:
        return "Elite"
    if score >= 75:
        return "Plus"
    if score >= 60:
        return "Above Avg"
    if score >= 45:
        return "Average"
    if score >= 30:
        return "Below Avg"

    return "Low"


def add_labels(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["athlete_grade"] = df["athlete_score"].map(grade_from_score)
    df["potential_grade"] = df["physical_potential_score"].map(grade_from_score)
    df["overall_grade"] = df["overall_score"].map(grade_from_score)

    return df


# ============================================================
# Formatting helpers
# ============================================================

def round_display(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    numeric_cols = df.select_dtypes(include=[np.number]).columns

    for col in numeric_cols:
        df[col] = df[col].round(2)

    return df


def safe_multiselect(label: str, options: List[str], default: Optional[List[str]] = None):
    clean_options = sorted([x for x in options if str(x).strip() != ""])

    if default is None:
        default = clean_options

    return st.sidebar.multiselect(label, clean_options, default=default)


# ============================================================
# App body
# ============================================================

st.title(APP_TITLE)
st.caption("Google Sheets-powered draft athletic qualities and physical potential dashboard.")

sheet_id = get_sheet_id()

with st.spinner("Loading Google Sheet..."):
    try:
        sprint_raw = load_worksheet(sheet_id, REQUIRED_TABS["Sprint"])
        anthro_raw = load_worksheet(sheet_id, REQUIRED_TABS["Anthropometrics"])
        force_raw = load_worksheet(sheet_id, REQUIRED_TABS["Force Plate"])
    except Exception as e:
        st.error("Could not load the Google Sheet.")
        st.exception(e)
        st.stop()


# Sidebar
st.sidebar.header("Settings")

comparison_mode = st.sidebar.radio(
    "Position player comparison baseline",
    options=[
        "All position players",
        "Same position only",
    ],
    index=0,
    help="Pitchers are always compared only to other pitchers.",
)

st.sidebar.markdown("---")
st.sidebar.caption(f"Google Sheet ID: `{sheet_id}`")


# Process data
anthro = prep_anthro(anthro_raw)
force = prep_force_plate(force_raw)
sprint = prep_sprint(sprint_raw)

df = combine_data(anthro, force, sprint)
df = add_scores(df, comparison_mode=comparison_mode)
df = add_labels(df)


# Sidebar filters
positions = safe_multiselect(
    "Positions",
    options=df["position"].dropna().astype(str).unique().tolist(),
)

player_types = safe_multiselect(
    "Player type",
    options=df["player_type"].dropna().astype(str).unique().tolist(),
)

search = st.sidebar.text_input("Search player", value="").strip().lower()

filtered = df.copy()

if positions:
    filtered = filtered[filtered["position"].isin(positions)]

if player_types:
    filtered = filtered[filtered["player_type"].isin(player_types)]

if search:
    filtered = filtered[
        filtered["name"].astype(str).str.lower().str.contains(search, na=False)
        | filtered["player_id"].astype(str).str.lower().str.contains(search, na=False)
        | filtered["school"].astype(str).str.lower().str.contains(search, na=False)
    ]


# KPIs
c1, c2, c3, c4 = st.columns(4)

c1.metric("Players", f"{len(filtered):,}")
c2.metric("Pitchers", f"{(filtered['player_type'] == 'Pitcher').sum():,}")
c3.metric("Position Players", f"{(filtered['player_type'] == 'Position Player').sum():,}")
c4.metric("Players with Sprint", f"{filtered['has_sprint'].sum():,}")


# Tabs
tab_rankings, tab_player, tab_charts, tab_data = st.tabs(
    [
        "Rankings",
        "Player Profile",
        "Charts",
        "Raw Data",
    ]
)


with tab_rankings:
    st.subheader("Draft Rankings")

    ranking_cols = [
        "name",
        "position",
        "school",
        "player_type",
        "comparison_group",
        "sprint_status",
        "athlete_score",
        "athlete_grade",
        "physical_potential_score",
        "potential_grade",
        "overall_score",
        "overall_grade",
        "ci",
        "mrsi",
        "rel_peak_power",
        "height",
        "bodyweight",
        "wingspan",
        "sprint_10yd",
        "sprint_20yd",
        "sprint_30yd",
    ]

    available_ranking_cols = [c for c in ranking_cols if c in filtered.columns]

    ranking_df = (
        filtered[available_ranking_cols]
        .sort_values("overall_score", ascending=False, na_position="last")
        .reset_index(drop=True)
    )

    st.dataframe(
        round_display(ranking_df),
        use_container_width=True,
        hide_index=True,
    )

    csv = ranking_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        "Download filtered rankings CSV",
        data=csv,
        file_name="draft_athletic_rankings.csv",
        mime="text/csv",
    )


with tab_player:
    st.subheader("Player Profile")

    player_options = (
        filtered.sort_values("overall_score", ascending=False, na_position="last")["name"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    if not player_options:
        st.info("No players match the current filters.")
    else:
        selected_player = st.selectbox("Select player", player_options)

        player = filtered[filtered["name"] == selected_player].iloc[0]

        c1, c2, c3 = st.columns(3)

        c1.metric("Athlete Score", f"{player['athlete_score']:.1f}" if pd.notna(player["athlete_score"]) else "NA")
        c2.metric("Physical Potential", f"{player['physical_potential_score']:.1f}" if pd.notna(player["physical_potential_score"]) else "NA")
        c3.metric("Overall", f"{player['overall_score']:.1f}" if pd.notna(player["overall_score"]) else "NA")

        st.markdown("### Player Info")

        info_cols = [
            "name",
            "player_id",
            "position",
            "school",
            "player_type",
            "comparison_group",
            "sprint_status",
        ]

        st.dataframe(
            round_display(pd.DataFrame([player[info_cols]])),
            use_container_width=True,
            hide_index=True,
        )

        st.markdown("### Athletic Profile")

        profile_cols = [
            "ci",
            "ci_pct",
            "mrsi",
            "mrsi_pct",
            "rel_peak_power",
            "rel_peak_power_pct",
            "height",
            "height_pct",
            "bodyweight",
            "bodyweight_pct",
            "wingspan",
            "wingspan_pct",
            "sprint_10yd",
            "sprint_10yd_pct",
            "sprint_20yd",
            "sprint_20yd_pct",
            "sprint_30yd",
            "sprint_30yd_pct",
            "sprint_pct",
        ]

        profile_cols = [c for c in profile_cols if c in filtered.columns]

        profile_table = pd.DataFrame(
            {
                "Metric": profile_cols,
                "Value": [player[c] for c in profile_cols],
            }
        )

        st.dataframe(
            round_display(profile_table),
            use_container_width=True,
            hide_index=True,
        )


with tab_charts:
    st.subheader("Score Visuals")

    chart_df = filtered.copy()

    chart_df = chart_df[
        chart_df["athlete_score"].notna()
        & chart_df["physical_potential_score"].notna()
    ]

    if len(chart_df) == 0:
        st.info("Not enough scored players to chart.")
    else:
        fig = px.scatter(
            chart_df,
            x="athlete_score",
            y="physical_potential_score",
            color="position",
            hover_name="name",
            hover_data=[
                "school",
                "player_type",
                "comparison_group",
                "sprint_status",
                "ci",
                "mrsi",
                "rel_peak_power",
                "height",
                "bodyweight",
                "wingspan",
                "sprint_10yd",
                "sprint_20yd",
                "sprint_30yd",
            ],
            title="Athlete Score vs Physical Potential",
        )

        fig.update_layout(
            xaxis_title="Athlete Score",
            yaxis_title="Physical Potential Score",
            height=650,
        )

        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Overall Score by Position")

        box_df = chart_df[chart_df["overall_score"].notna()]

        fig2 = px.box(
            box_df,
            x="position",
            y="overall_score",
            points="all",
            hover_name="name",
            title="Overall Score Distribution by Position",
        )

        fig2.update_layout(
            xaxis_title="Position",
            yaxis_title="Overall Score",
            height=550,
        )

        st.plotly_chart(fig2, use_container_width=True)


with tab_data:
    st.subheader("Loaded Data Checks")

    st.markdown("### Processed Master Table")
    st.dataframe(
        round_display(df),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("### Raw Sprint")
    st.dataframe(sprint_raw, use_container_width=True, hide_index=True)

    st.markdown("### Raw Anthropometrics")
    st.dataframe(anthro_raw, use_container_width=True, hide_index=True)

    st.markdown("### Raw Force Plate")
    st.dataframe(force_raw, use_container_width=True, hide_index=True)
