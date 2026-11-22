import { useEffect, useMemo, useRef } from "react";
import { CircleMarker, GeoJSON, LayersControl, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import "@geoman-io/leaflet-geoman-free";
import { useTranslation } from "react-i18next";
import { useNames } from "../lib/reference";

const OSM = { url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attr: "© OpenStreetMap contributors" };
const SAT = { url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", attr: "Imagery © Esri, Maxar, Earthstar Geographics" };

function BaseLayers({ satellite = false }: { satellite?: boolean }) {
  const { t } = useTranslation();
  return (
    <LayersControl position="topright">
      <LayersControl.BaseLayer checked={!satellite} name={t("map.streets")}><TileLayer url={OSM.url} attribution={OSM.attr} /></LayersControl.BaseLayer>
      <LayersControl.BaseLayer checked={satellite} name={t("map.satellite")}><TileLayer url={SAT.url} attribution={SAT.attr} maxZoom={19} /></LayersControl.BaseLayer>
    </LayersControl>
  );
}

function FitBounds({ geo, deps }: { geo: any; deps: any[] }) {
  const map = useMap();
  useEffect(() => {
    if (!geo) return;
    try { const b = L.geoJSON(geo).getBounds(); if (b.isValid()) map.fitBounds(b, { padding: [24, 24] }); } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return null;
}

/** National choropleth: values per governorate ISO code. */
export function TunisiaMap({ values, format, scale = "green", onSelect, height = 460 }: { values: Record<string, number | null | undefined>; format?: (v: number | null | undefined) => string; scale?: "green" | "blue" | "red"; onSelect?: (code: string) => void; height?: number }) {
  const { geo, gov } = useNames();
  const max = Math.max(1, ...Object.values(values).map((v) => (typeof v === "number" ? v : 0)));
  const ramps = { green: ["#eef8f0", "#7cc48e", "#1f7a3d"], blue: ["#eef6fd", "#7cc4ff", "#134c7f"], red: ["#fff4d6", "#f6b93b", "#a32c2c"] };
  const color = (v: number | null | undefined) => {
    if (v === null || v === undefined) return "#e5e7eb";
    const x = v / max; const [a, b, c] = ramps[scale];
    return x < 0.5 ? mix(a, b, x * 2) : mix(b, c, (x - 0.5) * 2);
  };
  const key = useMemo(() => JSON.stringify(values), [values]);
  if (!geo) return <div style={{ height }} className="animate-pulse rounded-2xl bg-brand-50" />;
  return (
    <MapContainer style={{ height }} center={[34.0, 9.6]} zoom={6} scrollWheelZoom={false} className="w-full">
      <TileLayer url={OSM.url} attribution={OSM.attr} opacity={0.5} />
      <GeoJSON key={key} data={geo} style={(f: any) => ({ fillColor: color(values[f.properties.shapeISO]), weight: 1, color: "#fff", fillOpacity: 0.85 })}
        onEachFeature={(f: any, layer) => {
          const code = f.properties.shapeISO; const v = values[code];
          layer.bindTooltip(`<b>${gov(code)}</b><br/>${format ? format(v) : v ?? "—"}`, { sticky: true });
          layer.on("click", () => onSelect?.(code));
        }} />
    </MapContainer>
  );
}

function mix(a: string, b: string, t: number) {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`;
}

type Source = { id?: number; latitude: number; longitude: number; kind: string; flow_m3h?: number; name?: string };

/** Geoman drawing/editing of a single polygon (farm boundary or parcel). */
function DrawControl({ mode, initial, onChange, onPoint }: { mode: "none" | "boundary" | "point"; initial?: any; onChange?: (gj: any) => void; onPoint?: (lat: number, lng: number) => void }) {
  const map = useMap();
  const layerRef = useRef<L.Layer | null>(null);
  const { i18n } = useTranslation();
  const changeRef = useRef(onChange); changeRef.current = onChange;
  const pointRef = useRef(onPoint); pointRef.current = onPoint;
  useEffect(() => {
    const pm = (map as any).pm;
    if (!pm) return;
    pm.setLang(i18n.language === "ar" ? "ar" : "fr");
    if (mode === "boundary") {
      pm.addControls({ position: "topleft", drawMarker: false, drawCircleMarker: false, drawPolyline: false, drawCircle: false, drawText: false, cutPolygon: false, rotateMode: false, drawRectangle: true, drawPolygon: true, editMode: true, dragMode: true, removalMode: true });
      if (initial && !layerRef.current) {
        const lyr = L.geoJSON(initial, { style: { color: "#1f7a3d", weight: 3, fillOpacity: 0.08 } }).getLayers()[0];
        if (lyr) { lyr.addTo(map); layerRef.current = lyr; (lyr as any).pm.enable({ allowSelfIntersection: false }); (lyr as any).on("pm:edit", () => changeRef.current?.((lyr as any).toGeoJSON().geometry)); }
      }
      const onCreate = (e: any) => {
        if (layerRef.current) map.removeLayer(layerRef.current);
        layerRef.current = e.layer;
        e.layer.on("pm:edit", () => changeRef.current?.(e.layer.toGeoJSON().geometry));
        changeRef.current?.(e.layer.toGeoJSON().geometry);
      };
      const onRemove = () => { layerRef.current = null; changeRef.current?.(null); };
      map.on("pm:create", onCreate); map.on("pm:remove", onRemove);
      return () => { map.off("pm:create", onCreate); map.off("pm:remove", onRemove); pm.removeControls(); if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; } };
    }
    if (mode === "point") {
      const onClick = (e: L.LeafletMouseEvent) => pointRef.current?.(e.latlng.lat, e.latlng.lng);
      map.getContainer().style.cursor = "crosshair";
      map.on("click", onClick);
      return () => { map.off("click", onClick); map.getContainer().style.cursor = ""; };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode]);
  return null;
}

export function FarmMap({ boundary, exclusions, sources = [], parcels = [], infrastructure, selected, onSelectParcel, drawMode = "none", onBoundaryChange, onPoint, center, height = 520, satellite = true, cropOf, governorate }: {
  governorate?: string;
  boundary?: any; exclusions?: any; sources?: Source[]; parcels?: any[]; infrastructure?: any; selected?: number | null;
  onSelectParcel?: (p: any) => void; drawMode?: "none" | "boundary" | "point"; onBoundaryChange?: (gj: any) => void; onPoint?: (lat: number, lng: number) => void;
  center?: [number, number]; height?: number; satellite?: boolean; cropOf?: (p: any) => string;
}) {
  const { color, crop, crops, geo } = useNames();
  const govGeo = !boundary && !center && governorate && geo ? { ...geo, features: geo.features.filter((f: any) => f.properties.shapeISO === governorate) } : null;
  const { t } = useTranslation();
  const fitTarget = parcels.length ? { type: "FeatureCollection", features: parcels.map((p) => ({ type: "Feature", geometry: p.geometry, properties: {} })) } : boundary;
  const parcelsKey = Object.keys(crops).length + parcels.map((p) => `${p.id}:${cropOf ? cropOf(p) : p.crop}:${selected === p.id}`).join("|");
  return (
    <MapContainer style={{ height }} center={center || [34.5, 9.8]} zoom={center ? 15 : 6} className="w-full" scrollWheelZoom>
      <BaseLayers satellite={satellite} />
      <FitBounds geo={fitTarget || govGeo} deps={[JSON.stringify(boundary)?.length, parcels.length, !!govGeo]} />
      {boundary && drawMode !== "boundary" && <GeoJSON key={JSON.stringify(boundary).length} data={boundary} style={{ color: "#ffffff", weight: 3, fillOpacity: parcels.length ? 0 : 0.12, fillColor: "#2f9e44", dashArray: parcels.length ? "6 4" : undefined }} />}
      {exclusions && <GeoJSON key={"x" + JSON.stringify(exclusions).length} data={exclusions} style={{ color: "#5b6b61", weight: 1, fillColor: "#5b6b61", fillOpacity: 0.5 }} />}
      {infrastructure && <GeoJSON key={"i" + JSON.stringify(infrastructure).length} data={infrastructure} style={{ color: "#c98a06", weight: 1, fillColor: "#f6b93b", fillOpacity: 0.55 }}>
        <Tooltip sticky>{t("plan.infrastructure")}</Tooltip></GeoJSON>}
      {parcels.map((p) => (
        <GeoJSON key={parcelsKey + p.id} data={p.geometry}
          style={{ color: selected === p.id ? "#16201a" : "#ffffff", weight: selected === p.id ? 3 : 1.5, fillColor: color(cropOf ? cropOf(p) : p.crop), fillOpacity: selected === p.id ? 0.9 : 0.72 }}
          eventHandlers={{ click: () => onSelectParcel?.(p) }}>
          <Tooltip sticky className="parcel-label">{p.label} · {crop(p.crop)}</Tooltip>
        </GeoJSON>
      ))}
      {sources.map((s, i) => (
        <CircleMarker key={s.id ?? i} center={[s.latitude, s.longitude]} radius={9} pathOptions={{ color: "#fff", weight: 3, fillColor: "#1c6fb8", fillOpacity: 1 }}>
          <Tooltip>{t(`source.${s.kind}`)} {s.name || ""}{s.flow_m3h ? ` · ${s.flow_m3h} m³/h` : ""}</Tooltip>
        </CircleMarker>
      ))}
      <DrawControl mode={drawMode} initial={boundary} onChange={onBoundaryChange} onPoint={onPoint} />
    </MapContainer>
  );
}
