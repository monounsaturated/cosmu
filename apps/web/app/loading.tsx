// Route-level instant fallback (Iris Bento skeleton). The bento shell paints immediately; while a
// route's server component fetches fresh engine data, this streams in its place so navigation always
// feels instant instead of blocking on a cold/slow engine. Pages also wrap their data region in a
// <Suspense> with a tighter skeleton; this is the outer, whole-page fallback.

export default function Loading() {
  return (
    <div className="page active">
      <div className="skel" style={{ height: 44, marginBottom: "var(--gap)" }} />
      <div className="skel" style={{ height: 33, marginBottom: "var(--gap)" }} />
      <div className="skel" style={{ height: 360 }} />
    </div>
  );
}
