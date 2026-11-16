import type { Judge } from "@/lib/api";

const LABEL: Record<Judge, string> = {
  red: "RED（要確認）",
  yellow: "YELLOW（注意）",
  blue: "BLUE（良好）",
};

export default function JudgeBadge({ judge }: { judge: Judge | null }) {
  if (!judge) return <span className="badge badge-none">未判定</span>;
  return (
    <span className={`badge badge-${judge}`}>
      {judge === "blue" && <span className="star">★</span>}
      {LABEL[judge]}
    </span>
  );
}