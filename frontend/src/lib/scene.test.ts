import { describe, expect, it } from "vitest";
import { parcelAt, parcelsArea, parseScene, polygonArea, serialize, type Scene } from "./scene";

const scene: Scene = {
  format: "agrosphere.scene", version: 1, units: "m",
  origin: { utm_zone: "32N", easting: 600000, northing: 3900000, location_quality: "governorate_centroid" },
  boundary: [[0, 0], [100, 0], [100, 60], [0, 60]],
  zones: [{ kind: "reservoir", label: "BASSIN", polygon: [[80, 5], [95, 5], [95, 20], [80, 20]] }],
  lines: [], infrastructure: [],
  sources: [{ id: 1, kind: "borehole", name: "F1", xy: [10, 50], flow_m3h: null, daily_volume_m3: 26 }],
  parcels: [
    { id: 11, label: "P1", crop: "tomato", polygon: [[0, 30], [50, 30], [50, 60], [0, 60]], area_m2: 1500, locked: false },
    { id: 12, label: "P2", crop: "wheat", polygon: [[50, 30], [100, 30], [100, 60], [50, 60]], area_m2: 1500, locked: true },
  ],
  pipes: [{ parcel_id: 11, line: [[10, 50], [25, 45]] }],
  meta: { plan_id: 7 },
};

describe("scene model (Phaser editor data)", () => {
  it("save -> re-open is lossless", () => {
    const back = parseScene(serialize(scene));
    expect(back).toEqual(scene);
  });
  it("rejects files that are not plans", () => {
    expect(() => parseScene("not json")).toThrow("scene_not_json");
    expect(() => parseScene(JSON.stringify({ format: "x" }))).toThrow("not_a_scene");
    expect(() => parseScene(JSON.stringify({ ...scene, version: 99 }))).toThrow("scene_version_unsupported");
    expect(() => parseScene(JSON.stringify({ ...scene, boundary: [[0, 0]] }))).toThrow("scene_boundary_invalid");
  });
  it("areas are computed from the real polygons", () => {
    expect(polygonArea(scene.boundary)).toBe(6000);
    expect(parcelsArea(scene)).toBe(3000);
  });
  it("selection by click finds the parcel under the pointer", () => {
    expect(parcelAt(scene, [25, 45])?.id).toBe(11);
    expect(parcelAt(scene, [75, 45])?.id).toBe(12);
    expect(parcelAt(scene, [50, 10])).toBeNull();
  });
});
