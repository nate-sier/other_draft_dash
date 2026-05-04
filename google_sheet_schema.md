# Google Sheet Schema

Keep the original workbook tab names and headers. The app is intentionally flexible and can recognize alternate column names, but these are the important fields.

## Sprint

Required:

- `DPL ID`

Recommended:

- `Year`
- `Full Name Reverse`
- `Name`
- `First Name`
- `Last Name`
- `10yd`
- `20yd`
- `30yd`

Notes:

- Pitchers do not need sprint rows.
- Position players can be missing sprint rows, but the app will label them as `Missing / not tested` and re-weight the available scoring components.

## Anthropometrics

Required:

- `DPL ID`

Recommended:

- `Year`
- `Date`
- `Full Name Reverse`
- `Full Name`
- `First Name`
- `Last Name`
- `Position`
- `School Type`
- `Bats`
- `Throws`
- `Height`
- `Body Weight (kg)` or `Body Weight`
- `Arm Span`

Notes:

- `Position` is important because pitchers are always compared only to other pitchers.
- Position players can be compared against all position players or only their own normalized position group.
- Pitcher potential uses `Arm Span` / wingspan when available.

## Force Plate

Required:

- `DPL ID`

Recommended:

- `Year`
- `Date`
- `About`
- `Full Name Reverse`
- `Position`
- `School Name`
- `School Type`
- `Concentric Impulse [Ns]`
- `RSI-Modified [m/s]` or `RSI-modified [m/s]`
- `Peak Power / BM [W/kg]`
- `Peak Power [W]`
