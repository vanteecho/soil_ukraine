# -*- coding: utf-8 -*-
import os
import glob
import zipfile
import tempfile
from html import escape

import streamlit as st
import geopandas as gpd
import pandas as pd
import leafmap.foliumap as leafmap
import folium
from folium.elements import MacroElement
from jinja2 import Template


st.set_page_config(page_title="Карта ґрунтів", layout="wide")

# Прибираємо верхнє меню і зайві відступи
st.markdown("""
<style>
    #MainMenu, header, footer {visibility: hidden;}
    .block-container {padding-top: 0.5rem !important; padding-bottom: 0rem !important;}
</style>
""", unsafe_allow_html=True)

# =========================================================
# АУТЕНТИФІКАЦІЯ
# =========================================================
APP_PASSWORD = "agro2024"   # ← змініть на свій пароль

def check_password():
    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <style>
        .login-box {
            max-width: 380px;
            margin: 10vh auto 0 auto;
            padding: 2.5rem 2rem;
            border-radius: 12px;
            background: #1e1e2e;
            box-shadow: 0 4px 24px rgba(0,0,0,0.4);
            text-align: center;
        }
        .login-box h2 { color: #e0e0e0; margin-bottom: 0.3rem; }
        .login-box p  { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
    </style>
    <div class="login-box">
        <h2>🗺️ Карта ґрунтів</h2>
        <p>Введіть пароль для доступу</p>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        pwd = st.text_input("Пароль", type="password", label_visibility="collapsed",
                            placeholder="Введіть пароль...")
        if st.button("Увійти", use_container_width=True):
            if pwd == APP_PASSWORD:
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("Невірний пароль")
    return False

if not check_password():
    st.stop()

# =========================================================
# ШЛЯХИ ДО ФАЙЛІВ
# =========================================================
CLUSTER_ZIP_PATH = "claster.zip"
BLOCK_ZIP_PATH   = "block.zip"
SOILS_ZIP_PATH   = "Soil.zip"


# =========================================================
# КОЛЬОРИ — 27 типів ґрунтів
# =========================================================
SOIL_TYPE_COLORS = {
    "Болотні й торфовища":                     "#8E7CC3",
    "Буроземно-підзолисті":                    "#C27C0E",
    "Бурі гірсько-лісові":                     "#A65E12",
    "Дерново-підзолистіі оглеєні":             "#F4C48B",
    "Дерново-середньо-та сильно-підзо":        "#FFE87A",
    "Дерново-слабопідзолисті":                 "#FFFACD",
    "Дернові":                                 "#F2C6A0",
    "Дернові опідзолені та оглеєні, ї":        "#E6D38D",
    "Каштанові солонцюваті й солонці":         "#C86DB0",
    "Коричневі гірські":                       "#8B4A57",
    "Лучно чорноземні":                        "#55C667",
    "Лучні й лучно-болотні":                   "#90EE90",
    "Осолоділі грунти подів та запади":        "#F28C99",
    "Сірі опідзолені":                         "#C9D36A",
    "Темно-каштанові":                         "#B97A57",
    "Темно-каштанові солонцюваті":             "#A45F49",
    "Темно-сірі опідзолені й чернозем":        "#8E8A59",
    "Черноземи звичайні":                      "#C8A870",
    "Черноземи звичайні глибокі":              "#B89860",
    "Черноземи звичайні неглибокі":            "#D8B880",
    "Черноземи й дернові щебенюваті н":        "#9A927F",
    "Черноземи на важких глинах":              "#C7C2B8",
    "Черноземи південні":                      "#E6B0C7",
    "Черноземи південні залишково-со":         "#D98FB3",
    "Черноземи типові залишково-соло":         "#A2998D",
    "Черноземи типові малогумусніі":           "#8D7060",
    "Черноземи типові середньогумусн":         "#7A6050",
}


# =========================================================
# UTF-8 ЛЕГЕНДА ЧЕРЕЗ JAVASCRIPT
# =========================================================
class Utf8Legend(MacroElement):
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function() {
            var legendControl = L.control({position: 'bottomleft'});
            legendControl.onAdd = function(map) {
                var div = L.DomUtil.create('div');
                div.style.cssText = [
                    'background:white',
                    'border:2px solid rgba(0,0,0,.2)',
                    'border-radius:8px',
                    'padding:10px 13px',
                    'max-width:380px',
                    'max-height:500px',
                    'overflow-y:auto',
                    'box-shadow:0 2px 8px rgba(0,0,0,.18)',
                    'font-family:Arial,sans-serif',
                    'font-size:11.5px',
                    'line-height:1.4'
                ].join(';');
                var title = {{ this.title|tojson }};
                var items = {{ this.items|tojson }};
                var html = '<div style="font-weight:700;margin-bottom:8px;font-size:12.5px;">'
                         + title + '</div>';
                items.forEach(function(item) {
                    html += '<div style="display:flex;align-items:flex-start;margin-bottom:4px;">'
                          + '<div style="min-width:16px;height:16px;background:' + item[1] + ';'
                          + 'border:1px solid #555;margin-right:7px;flex-shrink:0;'
                          + 'border-radius:2px;margin-top:1px;"></div>'
                          + '<span>' + item[0] + '</span></div>';
                });
                div.innerHTML = html;
                return div;
            };
            legendControl.addTo({{ this._parent.get_name() }});
        })();
        {% endmacro %}
    """)
    def __init__(self, title, items):
        super().__init__()
        self._name = "Utf8Legend"
        self.title = title
        self.items = items


# =========================================================
# ЗАВАНТАЖЕННЯ SHAPEFILE З ZIP
# =========================================================
@st.cache_data
def load_zipped_shapefile(zip_path: str) -> gpd.GeoDataFrame:
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"Не знайдено: {zip_path}")
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(tmpdir)
        shp_files = glob.glob(os.path.join(tmpdir, "**", "*.shp"), recursive=True)
        if not shp_files:
            raise FileNotFoundError(f"Немає .shp у {zip_path}")
        gdf = None
        for enc in ("utf-8", "cp1251", "latin-1"):
            try:
                gdf = gpd.read_file(shp_files[0], encoding=enc)
                break
            except Exception:
                continue
        if gdf is None:
            raise ValueError("Не вдалось прочитати shapefile")
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs("EPSG:4326")
    return gdf


def norm(v):
    if pd.isna(v):
        return None
    t = str(v).strip()
    return t if t and t.lower() not in ("nan", "none", "") else None


# =========================================================
# ЗАВАНТАЖЕННЯ ДАНИХ
# =========================================================
try:
    clusters_gdf = load_zipped_shapefile(CLUSTER_ZIP_PATH)
    clusters_gdf = clusters_gdf[~(clusters_gdf.geometry.is_empty | clusters_gdf.geometry.isna())].copy()
    clusters_gdf["cluster_name"] = clusters_gdf["name"].apply(norm).fillna("Без назви")
except Exception as e:
    st.error(f"Помилка кластерів: {e}"); st.stop()

try:
    blocks_gdf_base = load_zipped_shapefile(BLOCK_ZIP_PATH)
    blocks_gdf_base = blocks_gdf_base[~(blocks_gdf_base.geometry.is_empty | blocks_gdf_base.geometry.isna())].copy()
    blocks_gdf_base["block_name"] = blocks_gdf_base["name"].apply(norm).fillna("Без назви")
except Exception as e:
    st.error(f"Помилка блоків: {e}"); st.stop()

try:
    soils_raw = load_zipped_shapefile(SOILS_ZIP_PATH)
except Exception as e:
    st.error(f"Помилка ґрунтів: {e}"); st.stop()

if "SOIL_TYPE" not in soils_raw.columns:
    st.error(f"Немає SOIL_TYPE. Є: {list(soils_raw.columns)}"); st.stop()

soils_raw = soils_raw.copy()
soils_raw["SOIL_TYPE"] = soils_raw["SOIL_TYPE"].apply(norm)
soils_full = soils_raw[~(soils_raw.geometry.is_empty | soils_raw.geometry.isna())].copy()


# =========================================================
# ПРОСТОРОВИЙ JOIN: блок → кластер (найбільша площа перетину)
# =========================================================
@st.cache_data
def assign_blocks_to_clusters(_blocks, _clusters):
    blocks = _blocks.copy()
    clusters = _clusters[["cluster_name", "geometry"]].copy()
    joined = gpd.overlay(blocks, clusters, how="intersection")
    joined["_area"] = joined.geometry.area
    best = (
        joined.sort_values("_area", ascending=False)
        .drop_duplicates(subset=["block_name"])
        [["block_name", "cluster_name"]]
    )
    blocks = blocks.merge(best, on="block_name", how="left")
    blocks["cluster_name"] = blocks["cluster_name"].fillna("Інші")
    return blocks


blocks_gdf_base = assign_blocks_to_clusters(blocks_gdf_base, clusters_gdf)


# =========================================================
# SIDEBAR — ФІЛЬТРИ + ПІДКЛАДКА
# =========================================================
st.sidebar.header("🗺️ Карта ґрунтів")

ALL_LABEL        = "Вся компанія"
ALL_BLOCKS_LABEL = "Всі блоки"

cluster_values = sorted(blocks_gdf_base["cluster_name"].dropna().unique())
selected_cluster = st.sidebar.selectbox(
    "1️⃣ Кластер",
    [ALL_LABEL] + list(cluster_values)
)

if selected_cluster == ALL_LABEL:
    available_blocks = sorted(blocks_gdf_base["block_name"].dropna().unique())
else:
    available_blocks = sorted(
        blocks_gdf_base[blocks_gdf_base["cluster_name"] == selected_cluster]["block_name"]
        .dropna().unique()
    )

selected_block = st.sidebar.selectbox(
    "2️⃣ Блок",
    [ALL_BLOCKS_LABEL] + list(available_blocks)
)

st.sidebar.markdown("---")

BASEMAPS = {
    "🗺️ CartoDB (світла)":  ("CartoDB positron",  False),
    "🌑 CartoDB (темна)":   ("CartoDB dark_matter", False),
    "🗺️ OpenStreetMap":     ("OpenStreetMap",       False),
    "🛰️ Супутник (Esri)":   (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        True
    ),
    "🏔️ Топографія (Esri)": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        True
    ),
    "🌿 Terrain (Stamen)":  (
        "https://stamen-tiles.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
        True
    ),
}

selected_basemap_label = st.sidebar.selectbox("🛰️ Підкладка карти", list(BASEMAPS.keys()))
basemap_tiles, basemap_is_url = BASEMAPS[selected_basemap_label]

st.sidebar.markdown("---")
show_tooltips = st.sidebar.checkbox("💬 Підписи при наведенні", value=True)


# =========================================================
# ФІЛЬТРАЦІЯ БЛОКІВ ТА ZOOM
# =========================================================
if selected_cluster == ALL_LABEL and selected_block == ALL_BLOCKS_LABEL:
    blocks_filtered = blocks_gdf_base.copy()
    filter_label = ALL_LABEL
elif selected_block != ALL_BLOCKS_LABEL:
    blocks_filtered = blocks_gdf_base[blocks_gdf_base["block_name"] == selected_block].copy()
    filter_label = selected_block
else:
    blocks_filtered = blocks_gdf_base[blocks_gdf_base["cluster_name"] == selected_cluster].copy()
    filter_label = selected_cluster

if blocks_filtered.empty:
    st.warning("Блоків не знайдено."); st.stop()

# Центр і bounds для fit_bounds — по вибраних блоках
b = blocks_filtered.total_bounds   # [minx, miny, maxx, maxy]
center_lat = (b[1] + b[3]) / 2
center_lon = (b[0] + b[2]) / 2
# Leaflet fit_bounds формат: [[miny, minx], [maxy, maxx]]
fit_bounds = [[float(b[1]), float(b[0])], [float(b[3]), float(b[2])]]


# =========================================================
# ҐРУНТИ: на карті всі, легенда — лише по зоні
# =========================================================
soils_display = soils_full.copy()

with st.spinner("Визначення типів ґрунтів..."):
    try:
        zone_union = (
            blocks_filtered.geometry.union_all()
            if hasattr(blocks_filtered.geometry, "union_all")
            else blocks_filtered.geometry.unary_union
        )
        zone_gdf = gpd.GeoDataFrame({"n": [1]}, geometry=[zone_union], crs="EPSG:4326")
        soils_in_zone = gpd.overlay(soils_full, zone_gdf, how="intersection")
        soils_in_zone["SOIL_TYPE"] = soils_in_zone["SOIL_TYPE"].apply(norm)
        types_in_zone = set(soils_in_zone["SOIL_TYPE"].dropna().unique())
    except Exception:
        soils_in_zone = soils_display.copy()
        types_in_zone = set(soils_full["SOIL_TYPE"].dropna().unique())


# =========================================================
# КОЛЬОРИ
# =========================================================
types_present = sorted(t for t in types_in_zone if t and str(t).strip())

fallbacks = ["#1f78b4", "#33a02c", "#e31a1c", "#ff7f00", "#6a3d9a", "#b15928"]
soil_color_map = {}
fi = 0
for t in types_present:
    soil_color_map[t] = SOIL_TYPE_COLORS.get(t, fallbacks[fi % len(fallbacks)])
    if t not in SOIL_TYPE_COLORS:
        fi += 1

# Решта типів для фарбування карти поза зоною
for t in soils_full["SOIL_TYPE"].dropna().unique():
    if t not in soil_color_map:
        soil_color_map[t] = SOIL_TYPE_COLORS.get(t, "#cccccc")

legend_items = [(t, soil_color_map[t]) for t in types_present]


# =========================================================
# СТАТИСТИКА ПЛОЩ (по зоні)
# =========================================================
stats_zone = soils_in_zone.to_crs(3857).copy()
stats_zone["area_ha"] = stats_zone.geometry.area / 10_000.0
soil_stats = (
    stats_zone.groupby("SOIL_TYPE", as_index=False)["area_ha"]
    .sum()
    .sort_values("area_ha", ascending=False)
    .reset_index(drop=True)
)
soil_stats["area_ha"] = soil_stats["area_ha"].round(1)


# =========================================================
# SIDEBAR — ЛЕГЕНДА
# =========================================================
st.sidebar.markdown("---")
st.sidebar.subheader("📋 Легенда ґрунтів")
st.sidebar.markdown(f"**{filter_label}** · {len(types_present)} типів")

for soil_type in types_present:
    color = soil_color_map[soil_type]
    st.sidebar.markdown(
        f'<div style="display:flex;align-items:flex-start;margin-bottom:4px;">'
        f'<div style="min-width:14px;height:14px;background:{color};border:1px solid #444;'
        f'margin-right:7px;flex-shrink:0;border-radius:2px;margin-top:2px;"></div>'
        f'<span style="font-size:11.5px;line-height:1.3;">{escape(soil_type)}</span>'
        f'</div>',
        unsafe_allow_html=True
    )

st.sidebar.markdown("---")
st.sidebar.caption(f"Ґрунтів у базі: **{len(soils_full)}** · Блоків: **{len(blocks_filtered)}**")


# =========================================================
# КАРТА
# =========================================================
is_block_selected   = selected_block != ALL_BLOCKS_LABEL
is_cluster_selected = selected_cluster != ALL_LABEL

if basemap_is_url:
    m = leafmap.Map(
        location=[center_lat, center_lon],
        zoom_start=7,
        tiles=basemap_tiles,
        attr="© Esri / Stamen"
    )
else:
    m = leafmap.Map(
        location=[center_lat, center_lon],
        zoom_start=7,
        tiles=basemap_tiles
    )

# Підганяємо зум точно під межі вибраної зони
m.fit_bounds(fit_bounds)


# --- Ґрунти ---
def soil_style(feature):
    color = soil_color_map.get(feature["properties"].get("SOIL_TYPE"), "#cccccc")
    return {"fillColor": color, "color": color, "weight": 0.3, "fillOpacity": 0.78}

def soil_highlight_fn(_f):
    return {"weight": 2.0, "color": "#111", "fillOpacity": 0.92}

tt_fields  = [c for c in ["SOIL_TYPE", "SOIL_GROUP"] if c in soils_display.columns]
tt_aliases = {"SOIL_TYPE": "Тип ґрунтів:", "SOIL_GROUP": "Група:"}

folium.GeoJson(
    soils_display.__geo_interface__,
    name="Ґрунти",
    style_function=soil_style,
    highlight_function=soil_highlight_fn,
    tooltip=folium.GeoJsonTooltip(
        fields=tt_fields,
        aliases=[tt_aliases[c] for c in tt_fields],
        localize=True, sticky=False, labels=True,
        style="font-family:Arial,sans-serif;font-size:13px;"
    ) if show_tooltips else None,
).add_to(m)


# --- Кластери ---
# Вся компанія:       всі однаково — синя пунктирна лінія
# Кластер вибрано:    вибраний — яскрава синя суцільна, решта — ледь помітні
# Блок вибрано:       всі кластери майже невидимі (сірі тонкі)
def cluster_style(feature):
    name = feature["properties"].get("cluster_name", "")
    if is_block_selected:
        return {"color": "#bbbbbb", "weight": 0.8, "fillOpacity": 0.0, "dashArray": "3,7"}
    elif is_cluster_selected:
        if name == selected_cluster:
            return {"color": "#0044cc", "weight": 2.5, "fillOpacity": 0.0, "dashArray": ""}
        else:
            return {"color": "#aaaaaa", "weight": 0.8, "fillOpacity": 0.0, "dashArray": "4,6"}
    else:
        return {"color": "#0044cc", "weight": 1.5, "fillOpacity": 0.0, "dashArray": "8,5"}

folium.GeoJson(
    clusters_gdf.__geo_interface__,
    name="Межі кластерів",
    style_function=cluster_style,
    highlight_function=lambda _f: {"color": "#0044cc", "weight": 3.0, "fillOpacity": 0.08},
    tooltip=folium.GeoJsonTooltip(
        fields=["cluster_name"],
        aliases=["Кластер:"],
        localize=True, sticky=False, labels=True,
        style="font-family:Arial,sans-serif;font-size:13px;font-weight:bold;"
    ) if show_tooltips else None,
).add_to(m)


# --- Блоки ---
block_fields  = [c for c in ["block_name", "cluster_name"] if c in blocks_filtered.columns]
block_aliases = {"block_name": "Блок:", "cluster_name": "Кластер:"}

folium.GeoJson(
    blocks_filtered.__geo_interface__,
    name="Межі блоків",
    style_function=lambda _f: {
        "color": "#cc0000", "weight": 2.0, "fillOpacity": 0.0, "dashArray": "6,4"
    },
    highlight_function=lambda _f: {
        "color": "#cc0000", "weight": 3.0, "fillOpacity": 0.07
    },
    tooltip=folium.GeoJsonTooltip(
        fields=block_fields,
        aliases=[block_aliases[c] for c in block_fields],
        localize=True, sticky=False, labels=True,
        style="font-family:Arial,sans-serif;font-size:13px;"
    ) if (show_tooltips and block_fields) else None,
).add_to(m)


m.add_child(Utf8Legend(f"Типи ґрунтів — {filter_label}", legend_items))
folium.LayerControl(collapsed=True).add_to(m)


# =========================================================
# ВИВІД
# =========================================================
m.to_streamlit(width=None, height=800)

with st.expander("📊 Площа ґрунтів у вибраній зоні"):
    st.dataframe(soil_stats, use_container_width=True)

with st.expander("🔧 Службова інформація"):
    st.write("Кластер:", selected_cluster, "| Блок:", selected_block)
    st.write("Колонки ґрунтів:", list(soils_raw.columns))
    no_color = [t for t in types_present if t not in SOIL_TYPE_COLORS]
    if no_color:
        st.warning(f"Типи без кольору: {no_color}")
    else:
        st.success("Всі типи мають кольори ✓")