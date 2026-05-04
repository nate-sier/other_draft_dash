# Draft Athletic Qualities + Physical Potential Dashboard

A Streamlit dashboard for ranking draft players from a Google Sheet that matches the uploaded workbook structure.

The Google Sheet must have these worksheet tabs exactly:

- `Sprint`
- `Anthropometrics`
- `Force Plate`

The app joins tabs by `DPL ID`, then calculates an **Athlete Score**, **Physical Potential Score**, and **Overall Score**.

## Scoring

### Athlete Score
Current athletic qualities:

- Concentric impulse: 40%
- mRSI / RSI-modified: 30%
- Sprint composite: 30%

### Physical Potential Score
For non-pitchers:

- Height: 20%
- Bodyweight: 15%
- mRSI / RSI-modified: 20%
- Relative peak power: 20%
- Sprint composite: 25%

For pitchers, wingspan/arm span is added:

- Height: 18%
- Bodyweight: 12%
- Wingspan / arm span: 20%
- mRSI / RSI-modified: 17%
- Relative peak power: 15%
- Sprint composite: 18%

Sprint times are scored as inverted percentiles, because lower times are better. The sprint composite averages the available `10yd`, `20yd`, and `30yd` split percentiles.

## Google Sheet setup

1. Upload the provided Excel workbook to Google Drive.
2. Open it with Google Sheets.
3. Confirm the tab names are exactly:
   - `Sprint`
   - `Anthropometrics`
   - `Force Plate`
4. Share the Google Sheet with your Google service account email as a viewer or editor.
5. Copy the Google Sheet ID from the URL.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml` with your Google Sheet ID and service account credentials.

Run:

```bash
streamlit run app.py
```

## GitHub + Streamlit Cloud deployment

1. Create a new GitHub repo.
2. Add these files:
   - `app.py`
   - `requirements.txt`
   - `.streamlit/secrets.toml.example`
   - `.gitignore`
   - `README.md`
3. Push to GitHub.
4. In Streamlit Community Cloud, create a new app from the repo.
5. Add your secrets in Streamlit Cloud settings. Do **not** commit your real `secrets.toml`.
6. Deploy.

## Notes

- The app is read-only against the Google Sheet. Coaches/scouts should edit the Google Sheet directly, then click **Refresh Google Sheet data** in the app.
- Best force-plate values and fastest sprint times are used per player.
- Latest available anthropometric profile is used for height, bodyweight, wingspan, position, and school metadata.
- Scores re-weight automatically when a player is missing a metric, but the sidebar has a minimum available component filter so thin profiles do not rank too highly.
