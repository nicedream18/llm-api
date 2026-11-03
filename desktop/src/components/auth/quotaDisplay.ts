export type QuotaTone = "success" | "warning" | "destructive" | "unknown";

export function quotaDisplayState(usedPercent: number | null): { remaining: number | null; tone: QuotaTone } {
  if (usedPercent == null) return { remaining: null, tone: "unknown" };

  const used = Math.max(0, Math.min(100, usedPercent));
  const remaining = 100 - used;
  const tone = remaining === 0 ? "destructive" : remaining <= 30 ? "warning" : "success";
  return { remaining, tone };
}
