import { Check, Power } from "lucide-react";
import { useState } from "react";
import { writeClipboard } from "../lib/runtime";

type MappingValue = Record<string, string | string[]>;

interface MappingChipsProps {
  mapping: MappingValue;
  /** 被关闭的映射对（迁移 041/042）：[from, to][] */
  disabledPairs?: string[][];
  /** 点击开关按钮回调；currentlyOff = 当前是否处于关闭态 */
  onToggle?: (from: string, to: string, currentlyOff: boolean) => void;
}

/**
 * 渠道 / Auth 账号共用的映射模型 chips：点击映射名复制，
 * 点击电源按钮快捷关闭/开启（渠道迁移 041 / Auth 迁移 042，交互一致）。
 */
export function MappingChips({ mapping, disabledPairs, onToggle }: MappingChipsProps) {
  const [copied, setCopied] = useState<string | null>(null);

  const copy = async (name: string) => {
    try {
      await writeClipboard(name);
      setCopied(name);
      window.setTimeout(() => setCopied(null), 1200);
    } catch {
      // 剪贴板不可用时静默忽略
    }
  };

  return (
    <div className="flex flex-wrap gap-1.5">
      {Object.entries(mapping).flatMap(([name, target]) => {
        const targets = Array.isArray(target) ? target : [target];
        return targets.map((t) => {
          const isOff = (disabledPairs ?? []).some((d) => d[0] === name && d[1] === t);
          return (
            <div
              key={`${name}→${t}`}
              className={`inline-flex items-center gap-1 rounded-full py-0 pl-1.5 pr-1 text-[11px] font-medium leading-5 transition-all ${
                isOff ? "bg-slate-100 text-slate-400" : "bg-violet-50 text-violet-700"
              }`}
            >
              <button
                onClick={() => void copy(name)}
                className={`transition-all active:scale-95 ${isOff ? "line-through decoration-slate-300" : "hover:text-violet-900"}`}
                title="点击复制映射名"
              >
                {name} → {t}
                {copied === name && <Check size={9} className="ml-0.5 inline text-emerald-500" />}
              </button>
              {onToggle && (
                <button
                  onClick={() => onToggle(name, t, isOff)}
                  className={`rounded-full p-0.5 transition-colors ${
                    isOff
                      ? "text-slate-400 hover:bg-slate-200 hover:text-emerald-600"
                      : "text-violet-400 hover:bg-violet-100 hover:text-red-500"
                  }`}
                  title={isOff ? "已关闭，点击开启" : "已开启，点击关闭"}
                  aria-label={isOff ? `开启映射 ${name} → ${t}` : `关闭映射 ${name} → ${t}`}
                >
                  <Power size={10} />
                </button>
              )}
            </div>
          );
        });
      })}
    </div>
  );
}
