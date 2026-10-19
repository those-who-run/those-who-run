// The header's live engineer chip (#296 R2): EngineChip over the engineer's status,
// asked every 5 s while the tab is visible, and the pit wall's own version for the
// deploy check (R3). Kept apart from EngineChip so /_kit can show every state
// without asking the API.
import { useEngineStatus, useHealth } from "@/api/hooks";

import { EngineChip } from "./engine-chip";

export function LiveChip() {
  const engine = useEngineStatus();
  const health = useHealth();
  return <EngineChip engine={engine} pitwall={health.data?.version ?? null} />;
}
