import Link from "next/link";
import { BrandMarkIcon } from "./Icons";

export interface ForecastSessionInfo {
  id: string;
  isExpired: boolean;
  lastActive?: number;
}

interface DemandAIHeaderProps {
  session?: ForecastSessionInfo | null;
}

export default function DemandAIHeader({ session }: DemandAIHeaderProps) {
  return (
    <header className="demand-header">
      <Link href="/" className="demand-brand" aria-label="DemandAI home">
        <span className="brand-mark">
          <BrandMarkIcon size={18} />
        </span>
        <span>
          Demand<span className="brand-ai">AI</span>
        </span>
      </Link>



    </header>
  );
}
