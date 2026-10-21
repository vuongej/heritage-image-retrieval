'use client';

// "output cũng search được query đấy": mỗi facet là 1 chip bấm lại truy vấn được.
export default function FacetChips({ facets, onPick }:
  { facets: any; onPick: (q: string) => void }) {
  const ents = Object.entries(facets?.entities || {}) as [string, string][];
  const cls = Object.entries(facets?.classes || {}) as [string, number][];
  const qt = Object.entries(facets?.query_types || {}) as [string, number][];
  if (!ents.length && !cls.length && !qt.length) return null;
  return (
    <div className="chips">
      {ents.map(([slug, label]) => (
        <button key={`e-${slug}`} className="chip" onClick={() => onPick(label)}>{label}</button>
      ))}
      {cls.map(([name, n]) => (
        <button key={`c-${name}`} className="chip" onClick={() => onPick(name)}>{name} ({n})</button>
      ))}
      {qt.map(([name, n]) => (
        <button key={`q-${name}`} className="chip" onClick={() => onPick(name)}>{name} ({n})</button>
      ))}
    </div>
  );
}
