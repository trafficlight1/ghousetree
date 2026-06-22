#!/usr/bin/env python3
"""Render the GeoTIFFs in /new to colorized PNG overlays for the MapLibre map.
Outputs PNG (EPSG:4326, axis-aligned) + prints a JSON manifest of WGS84 bounds.
"""
import json
import numpy as np
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
import matplotlib.cm as cm
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image

OUT = "png"
import os
os.makedirs(OUT, exist_ok=True)

manifest = {}


def load_4326(path):
    """Return (array float64, (w,s,e,n) bounds in EPSG:4326). Reproject if needed."""
    with rasterio.open(path) as ds:
        if ds.crs and ds.crs.to_epsg() == 4326:
            arr = ds.read(1).astype("float64")
            b = ds.bounds
            return arr, (b.left, b.bottom, b.right, b.top), ds.nodata
        # reproject to 4326
        dst_crs = "EPSG:4326"
        transform, width, height = calculate_default_transform(
            ds.crs, dst_crs, ds.width, ds.height, *ds.bounds)
        dst = np.zeros((height, width), dtype="float64")
        reproject(
            source=rasterio.band(ds, 1),
            destination=dst,
            src_transform=ds.transform, src_crs=ds.crs,
            dst_transform=transform, dst_crs=dst_crs,
            resampling=Resampling.nearest)
        w = transform.c
        n = transform.f
        e = w + transform.a * width
        s = n + transform.e * height
        return dst, (w, s, e, n), ds.nodata


def save_rgba(rgba, name, bounds):
    Image.fromarray(rgba, "RGBA").save(f"{OUT}/{name}.png")
    w, s, e, n = bounds
    # MapLibre image source corner order: TL, TR, BR, BL  (lng, lat)
    manifest[name] = {
        "coordinates": [[w, n], [e, n], [e, s], [w, s]],
        "bounds_wsen": [round(w, 6), round(s, 6), round(e, 6), round(n, 6)],
    }


def colorize_continuous(arr, nodata, cmap_name, vmin, vmax, gamma=1.0,
                        alpha_from_value=False, alpha_floor=0.0):
    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= (arr != nodata)
    norm = np.clip((arr - vmin) / (vmax - vmin), 0, 1)
    if gamma != 1.0:
        norm = norm ** gamma
    cmap = cm.get_cmap(cmap_name)
    rgba = (cmap(norm) * 255).astype("uint8")
    if alpha_from_value:
        a = np.clip(norm, alpha_floor, 1.0)
        # below alpha_floor*range fade to transparent
        a = np.where(norm <= 0.001, 0.0, np.clip(norm * 1.4 + alpha_floor, 0, 1))
        rgba[..., 3] = (a * 255).astype("uint8")
    else:
        rgba[..., 3] = 255
    rgba[~valid] = 0
    return rgba


# ── 1. Black Marble nighttime lights (magma) ──
# Shared scale so winter/summer/january are comparable.
NTL_VMAX = 12.0
for f, name in [
    ("blackmarble_lviv_2021_winter.tif", "ntl_winter"),
    ("blackmarble_lviv_2021_summer.tif", "ntl_summer"),
    ("blackmarble_lviv_2013_january.tif", "ntl_2013jan"),
]:
    arr, bounds, nod = load_4326(f)
    rgba = colorize_continuous(arr, nod, "magma", 0.0, NTL_VMAX, gamma=0.55,
                               alpha_from_value=True, alpha_floor=0.15)
    save_rgba(rgba, name, bounds)

# ── 3. GHSL built surface (warm: black→red→yellow) ──
arr, bounds, nod = load_4326("ghsl_built_surface_2020_lviv.tif")
rgba = colorize_continuous(arr, nod, "inferno", 0.0, 8000.0, gamma=0.7,
                           alpha_from_value=True, alpha_floor=0.25)
save_rgba(rgba, "built_surface", bounds)

# ── 4. GHSL SMOD (categorical degree of urbanisation) ──
arr, bounds, nod = load_4326("ghsl_smod_2020_lviv.tif")
SMOD_COLORS = {
    30: (230, 0, 0),      # Urban centre
    23: (255, 110, 0),    # Dense urban cluster
    22: (255, 150, 40),   # Semi-dense urban cluster
    21: (255, 200, 90),   # Suburban / peri-urban
    13: (150, 190, 110),  # Rural cluster
    12: (190, 215, 150),  # Low density rural
    11: (225, 235, 200),  # Very low density rural
    10: (130, 180, 220),  # Water
}
h, w = arr.shape
rgba = np.zeros((h, w, 4), dtype="uint8")
ai = np.rint(arr).astype(int)
for code, (r, g, b) in SMOD_COLORS.items():
    m = ai == code
    rgba[m] = (r, g, b, 230)
save_rgba(rgba, "smod", bounds)

# ── 5. Sentinel-2 NDVI (water→bare→green) ──
arr, bounds, nod = load_4326("sentinel2_lviv_ndvi.tif")
ndvi_cmap = LinearSegmentedColormap.from_list("ndvi", [
    (0.00, "#2c7fb8"),  # water (negative)
    (0.18, "#d9c8a0"),  # bare soil
    (0.32, "#e6e6a0"),  # sparse
    (0.50, "#a6d96a"),  # moderate
    (0.72, "#41ab5d"),  # vegetation
    (1.00, "#0b6b2e"),  # dense forest
])
valid = np.isfinite(arr)
norm = np.clip((arr - (-0.2)) / (0.85 - (-0.2)), 0, 1)
rgba = (ndvi_cmap(norm) * 255).astype("uint8")
rgba[..., 3] = 255
rgba[~valid] = 0
save_rgba(rgba, "ndvi", bounds)

print(json.dumps(manifest, indent=2))
with open(f"{OUT}/manifest.json", "w") as fh:
    json.dump(manifest, fh, indent=2)
