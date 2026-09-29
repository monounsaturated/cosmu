import Link from "next/link";
import { CosmuMark } from "@/components/brand/logo";

export default function NotFound() {
  return (
    <div className="page active" style={{ minHeight: "70vh", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 18, textAlign: "center" }}>
      <CosmuMark size={48} />
      <div>
        <div className="page-title" style={{ fontSize: 22 }}>Off the orbit</div>
        <p className="muted" style={{ marginTop: 6, fontSize: 13.5 }}>That page isn&apos;t part of the control plane.</p>
      </div>
      <Link href="/" className="btn btn-iris">Return to Cosmu</Link>
    </div>
  );
}
