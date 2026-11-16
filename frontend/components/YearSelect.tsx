"use client";

type Props = {
  value: number | "";
  years: number[];
  onChange: (v: number | "") => void;
  disabled?: number[]; // すでに他の行で選ばれている年
};

export default function YearSelect({ value, years, onChange, disabled = [] }: Props) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
    >
      <option value="">年を選択</option>
      {years.map((y) => (
        <option key={y} value={y} disabled={disabled.includes(y) && y !== value}>
          {y}年
        </option>
      ))}
    </select>
  );
}