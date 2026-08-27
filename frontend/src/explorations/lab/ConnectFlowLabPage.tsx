import { useState } from "react";
import { FlowStage } from "./connect-flow/FlowStage";
import "./ConnectRingLabPage.css";

export function ConnectFlowLabPage() {
  const [log, setLog] = useState(
    "Right-click a disc to start — left-click a target, or empty to cancel.",
  );

  return (
    <div className="connect-ring-lab">
      <header className="connect-ring-lab__chrome">
        <p className="connect-ring-lab__eyebrow">Design lab</p>
        <h1 className="connect-ring-lab__title">Connect flow</h1>
        <p className="connect-ring-lab__lede">
          Same click model as Connect drag (RMB start → cursor follow → LMB
          land), on a plain React Flow canvas. Straight floating edges, no taut
          / spring land animation.
        </p>
        <p className="connect-ring-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/connect-drag">Connect drag</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/connect-ring">Connect ring</a>
          <span aria-hidden> · </span>
          <a href="#/">Field</a>
        </p>

        <p className="connect-ring-lab__log" role="status">
          {log}
        </p>
      </header>

      <FlowStage onLog={setLog} />
    </div>
  );
}
