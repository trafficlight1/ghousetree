/* Build a Mapbox vector-tile pyramid (PBF) from worldcover_lviv.geojson.
   Output: ../tiles/worldcover/{z}/{x}/{y}.pbf  (source-layer: "worldcover") */
const fs = require('fs');
const path = require('path');
const geojsonvt = require('geojson-vt').default || require('geojson-vt');
const vtpbf = require('vt-pbf');

const SRC = path.join(__dirname, '..', 'google engine', 'worldcover_lviv.geojson');
const OUT = path.join(__dirname, '..', 'tiles', 'worldcover');

const MINZOOM = 10;
const MAXZOOM = 14;            // generated; client overzooms above this
const BBOX = [23.90, 49.74, 24.14, 49.92]; // [w,s,e,n] Lviv + margin

function lon2x(lon, z) { return Math.floor((lon + 180) / 360 * Math.pow(2, z)); }
function lat2y(lat, z) {
  const r = lat * Math.PI / 180;
  return Math.floor((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2 * Math.pow(2, z));
}

console.log('Reading', SRC);
const data = JSON.parse(fs.readFileSync(SRC, 'utf8'));
console.log('Features:', data.features.length);

// Keep only the props we render to shrink tiles.
for (const f of data.features) {
  const p = f.properties || {};
  f.properties = { class_id: p.class_id, class_name: p.class_name };
}

console.log('Tiling...');
const tileindex = geojsonvt(data, {
  maxZoom: MAXZOOM,
  indexMaxZoom: MAXZOOM,
  indexMaxPoints: 0,
  tolerance: 3,
  extent: 4096,
  buffer: 64,
});

let written = 0;
for (let z = MINZOOM; z <= MAXZOOM; z++) {
  const x0 = lon2x(BBOX[0], z), x1 = lon2x(BBOX[2], z);
  const y0 = lat2y(BBOX[3], z), y1 = lat2y(BBOX[1], z); // note: north -> smaller y
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      const tile = tileindex.getTile(z, x, y);
      if (!tile || !tile.features.length) continue;
      const buff = vtpbf.fromGeojsonVt({ worldcover: tile }, { version: 2 });
      const dir = path.join(OUT, String(z), String(x));
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(path.join(dir, y + '.pbf'), Buffer.from(buff));
      written++;
    }
  }
}
console.log('Done. Tiles written:', written, '->', OUT);
