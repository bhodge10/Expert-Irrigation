/* The zone-dial meter. Five bars; amber instead of green below 80% so a
   shaky call reads as shaky at a glance. */
export default function ConfidenceBars({ confidence }) {
  const filled = Math.max(1, Math.round(confidence / 20));
  return (
    <span className={confidence < 80 ? "eq-bars low" : "eq-bars"}>
      {[0, 1, 2, 3, 4].map((i) => (
        <i key={i} className={i < filled ? "on" : ""} />
      ))}
    </span>
  );
}
