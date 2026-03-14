import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import json
import geopandas as gpd

st.set_page_config(
    page_title="Chicago Daily Crime Risk Monitor",
    page_icon="🚓",
    layout="wide"
)

# -----------------------------
# Load data
# -----------------------------
@st.cache_data
def load_data():
    history = pd.read_csv("data/history_daily_22_v2.csv", parse_dates=["date"])
    forecast = pd.read_csv("data/forecast_daily_22_sarimax_v2.csv", parse_dates=["date"])
    return history, forecast

history, forecast = load_data()

def add_selected_outline(fig, gdf_selected):
    gdf_selected = gdf_selected.to_crs(epsg=4326)

    for geom in gdf_selected.geometry:
        if geom is None:
            continue

        if geom.geom_type == "Polygon":
            polygons = [geom]
        elif geom.geom_type == "MultiPolygon":
            polygons = list(geom.geoms)
        else:
            polygons = []

        for poly in polygons:
            x, y = poly.exterior.xy
            fig.add_trace(
                go.Scattermapbox(
                    lon=list(x),
                    lat=list(y),
                    mode="lines",
                    line=dict(color="black", width=2),
                    hoverinfo="skip",
                    showlegend=False
                )
            )

# -----------------------------
# Basic cleanup
# -----------------------------

history["district"] = history["district"].astype(str)
forecast["district"] = forecast["district"].astype(str)

trend_forecast_start = pd.Timestamp("2026-03-03")

forecast_page1 = forecast[
    forecast["date"] >= trend_forecast_start
].copy()

forecast_page1["district"] = forecast_page1["district"].astype(str)

# If the source table has duplicate rows for the same district/date,
# keep the last one for page-1 display.
forecast_page1 = (
    forecast_page1
    .sort_values(["district", "date"])
    .drop_duplicates(subset=["district", "date"], keep="last")
)

# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.header("Monitor Controls")

district_list = sorted(
    forecast_page1["district"].astype(str).unique().tolist(),
    key=lambda x: int(x)
)
selected_district = st.sidebar.selectbox("District", district_list)

# Available forecast dates for page-1 monitoring


forecast_date_list = sorted(forecast_page1["date"].dt.date.unique().tolist())
default_forecast_idx = min(len(forecast_date_list) - 1, 6)

selected_forecast_date = st.sidebar.selectbox(
    "Alert Date",
    options=forecast_date_list,
    index=default_forecast_idx
)

display_date_list = sorted(
    pd.concat([history["date"], forecast_page1["date"]]).dt.date.unique().tolist()
)

selected_display_window = st.sidebar.select_slider(
    "Trend Window",
    options=display_date_list,
    value=(display_date_list[0], display_date_list[-1])
)


forecast_date = pd.to_datetime(selected_forecast_date)
display_start = pd.to_datetime(selected_display_window[0])
display_end = pd.to_datetime(selected_display_window[1])

history_district = history[
    (history["district"] == selected_district) &
    (history["date"] >= display_start) &
    (history["date"] < trend_forecast_start) &
    (history["date"] <= display_end)
].copy()

district_forecast = forecast_page1[
    (forecast_page1["district"] == selected_district) &
    (forecast_page1["date"] >= display_start) &
    (forecast_page1["date"] <= display_end)
].copy()

# -----------------------------
# Header
# -----------------------------
st.title("Chicago Daily Crime Risk Monitor")
st.caption("Daily district-level crime forecasting for operational monitoring using SARIMAX.")

# -----------------------------
# Top metrics
# -----------------------------
selected_point = forecast_page1[
    (forecast_page1["district"] == selected_district) &
    (forecast_page1["date"] == forecast_date)
].copy()



if not selected_point.empty:
    predicted_count = selected_point["yhat"].iloc[0]
    selected_risk_level = selected_point["risk_level"].iloc[0]
    selected_point_available = True
else:
    predicted_count = None
    selected_risk_level = "No record"
    selected_point_available = False



col1, col2, col3 = st.columns(3)
col1.metric("Alert Date", forecast_date.strftime("%Y-%m-%d"))
col2.metric("District", selected_district)
col3.metric(
    "Predicted Crime Count",
    f"{predicted_count:,.1f}" if predicted_count is not None else "N/A"
)

st.caption(f"Selected district risk level on {forecast_date.strftime('%Y-%m-%d')}: {selected_risk_level}")
if not selected_point_available:
    st.warning("No forecast record is available for the selected district on the selected forecast date.")

# -----------------------------
# Trend chart
# -----------------------------
st.subheader(f"District {selected_district} Trend")

fig = go.Figure()

fig.add_trace(
    go.Scatter(
        x=history_district["date"],
        y=history_district["actual_crime"],
        mode="lines",
        name="Actual"
    )
)

fig.add_trace(
    go.Scatter(
        x=district_forecast["date"],
        y=district_forecast["yhat"],
        mode="lines+markers",
        name="SARIMAX Forecast"
    )
)

fig.update_layout(
    height=380,
    xaxis_title="Date",
    yaxis_title="Crime Count",
    legend_title="Series",
    xaxis_range=[display_start, display_end]
)


st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# Chicago District Alert Map
# -----------------------------
st.subheader("Chicago District Alert Map")
st.caption(f"District-level alert view for {forecast_date.strftime('%Y-%m-%d')}")
st.caption("Darker color indicates higher predicted risk on the selected forecast date. The selected district is outlined in black.")

map_df = forecast_page1[forecast_page1["date"] == forecast_date].copy()

map_df["district"] = (
    map_df["district"]
    .astype(str)
    .str.extract(r"(\d+)", expand=False)
    .str.lstrip("0")
)

yhat_min = map_df["yhat"].min()
yhat_max = map_df["yhat"].max()

if yhat_max > yhat_min:
    map_df["risk_score_day"] = (map_df["yhat"] - yhat_min) / (yhat_max - yhat_min)
else:
    map_df["risk_score_day"] = 0.5


try:
    gdf = gpd.read_file("data/police_districts_current.zip")

    candidate_cols = [
        "district", "DISTRICT",
        "dist_num", "DIST_NUM",
        "district_num", "DIST_NUMBE",
        "police_district", "DIST",
        "dist", "DIST_NO"
    ]

    district_col = next((c for c in candidate_cols if c in gdf.columns), None)

    if district_col is None:
        st.error(f"Could not find a district column. Available columns: {gdf.columns.tolist()}")
    else:
        gdf["district"] = (
            gdf[district_col]
            .astype(str)
            .str.extract(r"(\d+)", expand=False)
            .str.lstrip("0")
        )

        valid_districts = [str(x) for x in [1,2,3,4,5,6,7,8,9,10,11,12,14,15,16,17,18,19,20,22,24,25]]
        gdf = gdf[gdf["district"].isin(valid_districts)].copy()

        merged = gdf.merge(
    map_df[["district", "yhat", "risk_score", "risk_score_day", "risk_level"]],
    on="district",
    how="left"
)

        matched_n = merged["risk_score_day"].notna().sum()

        merged_plot = merged[["district", "yhat", "risk_score", "risk_score_day", "risk_level", "geometry"]].copy()
        geojson_obj = json.loads(merged_plot.to_json())

        fig_map = px.choropleth_mapbox(
            merged_plot,
            geojson=geojson_obj,
            locations="district",
            featureidkey="properties.district",
            color="risk_score_day",
            hover_data={
    "yhat": ":.1f",
    "risk_score_day": False,
    "risk_score": False,
    "risk_level": True
},

            color_continuous_scale="Reds",
            range_color=(0, 1),
            mapbox_style="carto-positron",
            center={"lat": 41.8781, "lon": -87.6298},
            zoom=9.2,
            opacity=0.7
        )

        # District labels
        label_points = merged_plot.to_crs(epsg=4326).geometry.representative_point()
        fig_map.add_scattermapbox(
            lat=label_points.y,
            lon=label_points.x,
            mode="text",
            text=merged_plot["district"],
            textfont=dict(size=12, color="black"),
            hoverinfo="skip",
            showlegend=False
        )

        # Selected district outline
        selected_geo = merged_plot[merged_plot["district"] == selected_district].copy()
        if not selected_geo.empty:
            add_selected_outline(fig_map, selected_geo)
        
        fig_map.update_coloraxes(colorbar_title="District Risk")

        fig_map.update_layout(
            height=720,
            margin={"r": 0, "t": 0, "l": 0, "b": 0}
        )

        st.plotly_chart(fig_map, use_container_width=True)

except Exception as e:
    st.error(f"Map could not be rendered. Details: {e}")

