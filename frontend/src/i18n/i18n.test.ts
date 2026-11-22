import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import fr from "./fr";
import ar from "./ar";

function flat(o: any, p = ""): string[] {
  return Object.entries(o).flatMap(([k, v]) => (typeof v === "object" ? flat(v, `${p}${k}.`) : [`${p}${k}`]));
}
function files(dir: string): string[] {
  return readdirSync(dir).flatMap((f) => { const p = join(dir, f); return statSync(p).isDirectory() ? files(p) : p.endsWith(".tsx") || p.endsWith(".ts") ? [p] : []; });
}

describe("i18n", () => {
  const frKeys = new Set(flat(fr));
  const arKeys = new Set(flat(ar));
  it("French and Derja have exactly the same keys", () => {
    expect([...frKeys].filter((k) => !arKeys.has(k))).toEqual([]);
    expect([...arKeys].filter((k) => !frKeys.has(k))).toEqual([]);
  });
  it("every static key used in the UI exists", () => {
    const used = new Set<string>();
    for (const f of files(join(__dirname, ".."))) {
      for (const m of readFileSync(f, "utf8").matchAll(/\bt\("([a-zA-Z0-9_.]+)"/g)) used.add(m[1]);
    }
    expect([...used].filter((k) => !frKeys.has(k))).toEqual([]);
  });
  it("derja strings are written in Arabic script", () => {
    const latinOnly = flat(ar).filter((k) => {
      const v = k.split(".").reduce((o: any, p) => o[p], ar) as string;
      return !/[؀-ۿ]/.test(v);
    });
    expect(latinOnly).toEqual([]);
  });
});
