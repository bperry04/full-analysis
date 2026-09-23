export const isNum = (x: any): x is number => typeof x === "number" && Number.isFinite(x);
export const unwrap = (x: any) => (x && typeof x === "object" && "v" in x ? x.v : x);

export function num(x: any, d = 2): string {
  const v = unwrap(x);
  if (!isNum(v)) return "—";
  return v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
}
export function pct(x: any, d = 1, sign = true): string {
  const v = unwrap(x);
  if (!isNum(v)) return "—";
  const s = (v * 100).toFixed(d) + "%";
  return sign && v > 0 ? "+" + s : s;
}
export function big(x: any, d = 1): string {
  const v = unwrap(x);
  if (!isNum(v)) return "—";
  const a = Math.abs(v);
  const f = (n: number, s: string) => (v / n).toFixed(d) + s;
  if (a >= 1e12) return f(1e12, "T");
  if (a >= 1e9) return f(1e9, "B");
  if (a >= 1e6) return f(1e6, "M");
  if (a >= 1e3) return f(1e3, "K");
  return v.toFixed(d);
}
export function usd(x: any, d = 2): string {
  const v = unwrap(x);
  return isNum(v) ? "$" + num(v, d) : "—";
}
export function x(x: any, d = 1): string {
  const v = unwrap(x);
  return isNum(v) ? v.toFixed(d) + "x" : "—";
}
export function date(x: any): string {
  const v = unwrap(x);
  if (!v) return "—";
  const s = String(v);
  return s.length >= 10 ? s.slice(0, 10) : s;
}
export const cls = (v: any) => (isNum(unwrap(v)) ? (unwrap(v) > 0 ? "pos" : unwrap(v) < 0 ? "neg" : "") : "");
export function scoreColor(s: number | null | undefined): string {
  if (!isNum(s)) return "var(--dim)";
  if (s >= 65) return "var(--green)";
  if (s >= 55) return "#8bd17c";
  if (s > 45) return "var(--amber)";
  if (s > 35) return "#f0883e";
  return "var(--red)";
}
export const rows = (frame: any): any[] => (Array.isArray(frame) ? frame : []);
