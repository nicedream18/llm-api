import { useMemo, useState } from "react";

export type EntityOption = { id: string; label: string; detail?: string; disabled?: boolean };

type Props = {
  label: string;
  value: string[];
  options: EntityOption[];
  onChange: (value: string[]) => void;
  multiple?: boolean;
  placeholder?: string;
  helperText?: string;
  emptyText?: string;
  disabled?: boolean;
};

export function EntityPicker({
  label, value, options, onChange, multiple = true,
  placeholder, helperText, emptyText = "没有匹配的项目。", disabled = false,
}: Props) {
  const [query, setQuery] = useState("");
  const optionById = useMemo(() => new Map(options.map(option => [option.id, option])), [options]);
  const normalizedQuery = query.trim().toLocaleLowerCase();
  const filtered = options.filter(option => `${option.label} ${option.detail || ""}`.toLocaleLowerCase().includes(normalizedQuery));

  const toggle = (option: EntityOption, checked: boolean) => {
    if (multiple) {
      onChange(checked ? [...new Set([...value, option.id])] : value.filter(id => id !== option.id));
    } else {
      onChange(checked ? [option.id] : []);
      setQuery("");
    }
  };

  const remove = (id: string) => onChange(value.filter(item => item !== id));
  const selectedLabel = (id: string) => optionById.get(id)?.label || "不可用项目";

  return <fieldset className="entity-picker" disabled={disabled}>
    <legend>{label}</legend>
    {helperText && <p className="entity-picker-help">{helperText}</p>}
    <div className="entity-picker-selected" aria-label={`已选${label}`}>
      {value.length ? value.map(id => <span className="entity-picker-chip" key={id}>
        <span>{selectedLabel(id)}{!optionById.has(id) && <small>已不可用</small>}</span>
        <button type="button" aria-label={`移除${label} ${selectedLabel(id)}`} onClick={() => remove(id)}>×</button>
      </span>) : <span className="entity-picker-empty">不限</span>}
      {value.length > 1 && <button type="button" className="entity-picker-clear" onClick={() => onChange([])}>清除全部</button>}
    </div>
    <label className="entity-picker-search">
      <span className="sr-only">搜索{label}</span>
      <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={placeholder || `搜索${label}`} />
    </label>
    <div className="entity-picker-options" role="group" aria-label={`可选${label}`}>
      {filtered.length ? filtered.map(option => <label className="entity-picker-option" key={option.id}>
        <input
          type={multiple ? "checkbox" : "radio"}
          name={multiple ? undefined : `entity-picker-${label}`}
          checked={value.includes(option.id)}
          disabled={option.disabled}
          onChange={event => toggle(option, event.target.checked)}
        />
        <span className="entity-picker-option-copy">
          <strong>{option.label}</strong>
          {option.detail && <small>{option.detail}</small>}
        </span>
      </label>) : <p className="entity-picker-no-results">{emptyText}</p>}
    </div>
  </fieldset>;
}
