import { useEffect, useState, useCallback, useRef } from "react";

// ── types ────────────────────────────────────────────────────────────────
export interface MappingPair {
  from: string;
  to: string;
  /** false = 该映射对已关闭（仅渠道映射支持；Auth 账号映射恒为 true）。 */
  enabled: boolean;
}

export type ModelMapping = Record<string, string | string[]>;

// ── serialize / deserialize ──────────────────────────────────────────────
export function mappingToPairs(mapping?: ModelMapping | null, disabled?: string[][] | null): MappingPair[] {
  if (!mapping) return [];
  const disabledSet = new Set((disabled ?? []).map(d => `${d[0] ?? ""}\u0000${d[1] ?? ""}`));
  return Object.entries(mapping).flatMap(([from, to]) => {
    const targets = Array.isArray(to) ? to : [to];
    return targets.map(t => ({
      from,
      to: t,
      enabled: !disabledSet.has(`${from}\u0000${t}`),
    }));
  });
}

export function pairsToMapping(pairs: MappingPair[]): ModelMapping {
  const obj: ModelMapping = {};
  pairs.forEach(m => {
    if (!m.enabled) return; // 已关闭的映射不参与序列化（路由不可达）
    if (m.from.trim() && m.to.trim()) {
      const from = m.from.trim();
      const to = m.to.trim();
      if (obj[from] !== undefined) {
        const existing = obj[from];
        if (Array.isArray(existing)) {
          if (!existing.includes(to)) existing.push(to);
        } else {
          obj[from] = existing !== to ? [existing, to] : existing;
        }
      } else {
        obj[from] = to;
      }
    }
  });
  return obj;
}

/** 收集被关闭的映射对 → model_mapping_disabled 序列化格式（[from, to][]）。 */
export function pairsToDisabled(pairs: MappingPair[]): string[][] {
  return pairs
    .filter(m => !m.enabled && m.from.trim() && m.to.trim())
    .map(m => [m.from.trim(), m.to.trim()]);
}

/** 渠道映射中仍然生效的映射名（剔除被关闭的 [from, to] 对后至少还有一个目标）。
 *  用于「使用 / API 密钥 / 应用接入」等页面的模型列表聚合，与后端路由语义一致。 */
export function activeMappingFroms(
  mapping?: Record<string, string | string[]> | null,
  disabled?: string[][] | null,
): string[] {
  if (!mapping) return [];
  const disabledSet = new Set((disabled ?? []).map(d => `${d[0] ?? ""}\u0000${d[1] ?? ""}`));
  const out: string[] = [];
  for (const [from, to] of Object.entries(mapping)) {
    const targets = Array.isArray(to) ? to : [to];
    if (targets.some(t => !disabledSet.has(`${from}\u0000${t}`))) out.push(from);
  }
  return out;
}

// ── hook: useModelMappings ───────────────────────────────────────────────
// `initial` is used for initialization and external re-initialization
// (e.g. switching editing target). Internal edits are NOT round-tripped
// through the parent to avoid wiping incomplete rows: `pairsToMapping`
// silently drops pairs with empty from/to, which would cascade back via
// `onChange → form update → value prop → useEffect` and destroy the user's
// in-progress input.
//
// Solution: a `skipNextSync` ref. When the parent's `onChange` fires with
// our serialized output, the resulting `initial` prop change is ignored
// once. Genuine external changes (e.g. switching editing target) produce a
// different object that wasn't preceded by a `markSynced` call, so they
// still trigger re-initialization.
export function useModelMappings(initial?: ModelMapping | null, initialDisabled?: string[][] | null) {
  const [mappings, setMappings] = useState<MappingPair[]>(() => mappingToPairs(initial, initialDisabled));
  const skipNextSyncRef = useRef(false);

  useEffect(() => {
    if (skipNextSyncRef.current) {
      skipNextSyncRef.current = false;
      return;
    }
    setMappings(mappingToPairs(initial, initialDisabled));
  }, [initial]); // eslint-disable-line react-hooks/exhaustive-deps

  const markSynced = useCallback(() => {
    skipNextSyncRef.current = true;
  }, []);

  const addMapping = useCallback((defaultTo: string) => {
    setMappings(prev => [...prev, { from: "", to: defaultTo, enabled: true }]);
  }, []);

  const removeMapping = useCallback((idx: number) => {
    setMappings(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const removeByTarget = useCallback((target: string) => {
    setMappings(prev => prev.filter(m => m.to !== target));
  }, []);

  const updateMapping = useCallback((idx: number, field: "from" | "to", value: string) => {
    setMappings(prev => prev.map((m, i) => (i === idx ? { ...m, [field]: value } : m)));
  }, []);

  /** 开/关单条映射对（渠道映射专用）。 */
  const toggleMapping = useCallback((idx: number) => {
    setMappings(prev => prev.map((m, i) => (i === idx ? { ...m, enabled: !m.enabled } : m)));
  }, []);

  const existingFroms = Array.from(new Set(mappings.map(m => m.from).filter(Boolean))).sort();

  return { mappings, addMapping, removeMapping, removeByTarget, updateMapping, toggleMapping, existingFroms, markSynced };
}

// ── hook: useGlobalFroms ─────────────────────────────────────────────────
// Aggregates mapping names from all channels + auth accounts for dropdown suggestions.
import { channelApi } from "../lib/api";
import { authApi } from "../lib/api";

export function useGlobalFroms() {
  const [globalFroms, setGlobalFroms] = useState<string[]>([]);

  useEffect(() => {
    const names = new Set<string>();

    Promise.all([
      channelApi.getAll().catch(() => []),
      authApi.accountsList().catch(() => []),
    ]).then(([channels, accounts]) => {
      for (const ch of channels as { model_mapping?: Record<string, unknown> }[]) {
        if (ch.model_mapping && typeof ch.model_mapping === "object") {
          for (const key of Object.keys(ch.model_mapping)) if (key) names.add(key);
        }
      }
      for (const acc of accounts as { model_mapping?: Record<string, unknown> }[]) {
        if (acc.model_mapping && typeof acc.model_mapping === "object") {
          for (const key of Object.keys(acc.model_mapping)) if (key) names.add(key);
        }
      }
      setGlobalFroms(Array.from(names).sort());
    }).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return globalFroms;
}
