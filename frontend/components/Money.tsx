export default function Money({ n, sign = false }: { n: number; sign?: boolean }) {
  const r = Math.round(n);
  const pre = sign && r > 0 ? "+" : "";
  return (
    <>
      <span className="pc-only">{pre}{r.toLocaleString()} 円</span>
      <span className="sp-only">{pre}{Math.round(r / 10000).toLocaleString()}万円</span>
    </>
  );
}