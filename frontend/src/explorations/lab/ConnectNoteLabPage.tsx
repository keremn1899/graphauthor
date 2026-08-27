import { useState } from "react";
import { NoteRingStage } from "./connect-note/NoteRingStage";
import "./ConnectRingLabPage.css";

export function ConnectNoteLabPage() {
  const [log, setLog] = useState(
    "Right-click or long-press a disc → drag from the grey ring annulus.",
  );

  return (
    <div className="connect-ring-lab">
      <header className="connect-ring-lab__chrome">
        <p className="connect-ring-lab__eyebrow">Design lab</p>
        <h1 className="connect-ring-lab__title">Connect note</h1>
        <p className="connect-ring-lab__lede">
          Note Prototype mechanism on React Flow: arm ring → drag from annulus
          Handle → drop on node via onConnectEnd. Graph Frontend discs and
          floating straight edges. No connection animation.
        </p>
        <p className="connect-ring-lab__nav">
          <a href="#/explorations">← Explorations</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/connect-ring">Connect ring</a>
          <span aria-hidden> · </span>
          <a href="#/explorations/lifecycle">Lifecycle</a>
          <span aria-hidden> · </span>
          <a href="#/">Field</a>
        </p>

        <p className="connect-ring-lab__log" role="status">
          {log}
        </p>
      </header>

      <NoteRingStage onLog={setLog} />
    </div>
  );
}
