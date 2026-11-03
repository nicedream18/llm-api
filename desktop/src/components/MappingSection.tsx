import { useEffect, useRef } from "react";
import { Plus } from "lucide-react";
import { MappingRow } from "./channel-form/MappingRow";
import { useModelMappings, useGlobalFroms, pairsToMapping, pairsToDisabled, type ModelMapping } from "../hooks/useModelMappings";

interface MappingSectionProps {
  /** Initial mapping value (from channel or auth account) */
  value?: ModelMapping | null;
  /** 被关闭的映射对（渠道映射开关，迁移 041）；不传 = 不启用开关能力 */
  disabledPairs?: string[][] | null;
  /** Available target models for the "to" dropdown */
  availableTargets: string[];
  /** Called on every change with the serialized mapping object */
  onChange: (mapping: ModelMapping) => void;
  /** 开关状态变化时回调（传入后才显示每行的开关按钮） */
  onDisabledChange?: (disabled: string[][]) => void;
  /** Label for the section (default: "模型映射") */
  label?: string;
  /** Hint text shown next to label */
  hint?: string;
}

/**
 * Shared model-mapping editor used by both ChannelForm and Auth EditModal.
 * Manages mapping rows, global-from-name suggestions, and serialization.
 * 传入 onDisabledChange 后，每行映射可单独开启/关闭（仅渠道场景）。
 */
export function MappingSection({
  value,
  disabledPairs,
  availableTargets,
  onChange,
  onDisabledChange,
  label = "模型映射",
  hint = "左侧填映射名（客户端请求用），右侧选实际模型",
}: MappingSectionProps) {
  const { mappings, addMapping, removeMapping, updateMapping, toggleMapping, existingFroms, markSynced } =
    useModelMappings(value, disabledPairs);
  const globalFroms = useGlobalFroms();

  // Merge global + current-session froms for suggestions
  const allFroms = Array.from(new Set([...globalFroms, ...existingFroms])).sort();

  // Serialize and bubble up on every change.
  const serialized = pairsToMapping(mappings);
  const serializedDisabled = onDisabledChange ? pairsToDisabled(mappings) : null;

  // Notify parent whenever mappings change.
  const lastValueRef = useRef<string>(JSON.stringify(serialized));
  const lastDisabledRef = useRef<string>(JSON.stringify(serializedDisabled ?? "null"));
  useEffect(() => {
    const next = JSON.stringify(serialized);
    if (next !== lastValueRef.current) {
      lastValueRef.current = next;
      // Mark as self-produced so useModelMappings ignores the round-trip.
      markSynced();
      onChange(serialized);
    }
  }, [serialized]); // eslint-disable-line react-hooks/exhaustive-deps

  // Notify parent when the disabled-pair set changes (toggle on/off).
  useEffect(() => {
    if (!onDisabledChange || !serializedDisabled) return;
    const next = JSON.stringify(serializedDisabled);
    if (next !== lastDisabledRef.current) {
      lastDisabledRef.current = next;
      markSynced();
      onDisabledChange(serializedDisabled);
    }
  }, [serializedDisabled]); // eslint-disable-line react-hooks/exhaustive-deps

  if (availableTargets.length === 0) {
    return (
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-sm font-medium">{label}</label>
        </div>
        <div className="rounded-2xl border border-dashed border-border bg-background/40 px-4 py-6 text-center">
          <p className="text-sm text-muted-foreground">请先配置可用模型后再设置映射</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label className="text-sm font-medium">{label}</label>
        <span className="text-xs text-muted-foreground">{hint}</span>
      </div>
      {mappings.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border bg-background/40 px-4 py-6 text-center">
          <p className="text-sm text-muted-foreground mb-3">尚未配置模型映射</p>
          <button
            type="button"
            onClick={() => addMapping(availableTargets[0])}
            className="action-secondary inline-flex items-center gap-1.5"
          >
            <Plus size={14} /> 添加映射
          </button>
        </div>
      ) : (
        <div className="space-y-2.5">
          {mappings.map((map, idx) => (
            <MappingRow
              key={idx}
              from={map.from}
              to={map.to}
              enabled={map.enabled}
              showToggle={!!onDisabledChange}
              availableTargets={availableTargets}
              existingFroms={allFroms}
              onRemove={() => removeMapping(idx)}
              onChange={(field, val) => updateMapping(idx, field, val)}
              onToggle={() => toggleMapping(idx)}
            />
          ))}
          <button
            type="button"
            onClick={() => addMapping(availableTargets[0])}
            className="action-secondary inline-flex items-center gap-1.5"
          >
            <Plus size={14} /> 添加映射
          </button>
        </div>
      )}
    </div>
  );
}
