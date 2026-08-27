/**
 * Temporary fixture: every notice slot and kind, without failing the host.
 * Drop this file (and its route) once the real surfaces are judged.
 */
import { useEffect, useState } from "react";
import {
  NoticeCard,
  NoticeSurface,
  useNotice,
  type NoticeKind,
} from "../../product/Notice";
import { OverlayPanel } from "../../product/OverlayPanel";
import {
  Instrument,
  InstrumentGroup,
  ProductShell,
} from "../../product/ProductShell";
import "../../product/NodeReaderPanel.css";
import "./NoticeLabPage.css";

type BlockId = "off" | "host" | "map" | "catalogue" | "review";
type DockId = "off" | "verb" | "act";

const BLOCKS: Record<
  Exclude<BlockId, "off">,
  { kind: NoticeKind; title: string; body: string; action?: string }
> = {
  host: {
    kind: "host",
    title: "The host is not answering",
    body: "Cannot reach the host. Is it running?",
    action: "Open Settings",
  },
  map: {
    kind: "unavailable",
    title: "The map could not be read",
    body: "Could not read the map.",
  },
  catalogue: {
    kind: "unavailable",
    title: "The catalogue could not be read",
    body: "Could not list graphs.",
  },
  review: {
    kind: "unavailable",
    title: "Review could not be read",
    body: "Could not read review activity.",
  },
};

const DOCKS: Record<
  Exclude<DockId, "off">,
  { kind: NoticeKind; title: string; body: string }
> = {
  verb: {
    kind: "fault",
    title: "That did not complete",
    body: "Could not switch workspace.",
  },
  act: {
    kind: "fault",
    title: "That did not complete",
    body: "The confirm did not land.",
  },
};

function NoticeLabBody() {
  const { raise, clear } = useNotice();
  const [blockId, setBlockId] = useState<BlockId>("map");
  const [dockId, setDockId] = useState<DockId>("verb");
  const [cardsOpen, setCardsOpen] = useState(true);
  const [settingsNote, setSettingsNote] = useState("");

  useEffect(() => {
    if (blockId === "off") {
      clear("specimen-block");
      return;
    }
    const spec = BLOCKS[blockId];
    raise({
      id: "specimen-block",
      slot: "block",
      kind: spec.kind,
      title: spec.title,
      body: spec.body,
      action: spec.action
        ? {
            label: spec.action,
            onClick: () => setSettingsNote("Settings would open."),
          }
        : undefined,
    });
    return () => clear("specimen-block");
  }, [blockId, clear, raise]);

  useEffect(() => {
    if (dockId === "off") {
      clear("specimen-dock");
      return;
    }
    const spec = DOCKS[dockId];
    raise({
      id: "specimen-dock",
      slot: "dock",
      kind: spec.kind,
      title: spec.title,
      body: spec.body,
      dismissible: true,
    });
    return () => clear("specimen-dock");
  }, [clear, dockId, raise]);

  return (
    <div className="notice-lab">
      <Instrument>
        <InstrumentGroup label="Block">
          <select
            className="notice-lab__select"
            value={blockId}
            onChange={(event) => {
              setBlockId(event.target.value as BlockId);
              setSettingsNote("");
            }}
          >
            <option value="off">Off</option>
            <option value="host">Host unreachable</option>
            <option value="map">Map unreadable</option>
            <option value="catalogue">Catalogue unreadable</option>
            <option value="review">Review unreadable</option>
          </select>
        </InstrumentGroup>
        <InstrumentGroup label="Dock">
          <select
            className="notice-lab__select"
            value={dockId}
            onChange={(event) => setDockId(event.target.value as DockId)}
          >
            <option value="off">Off</option>
            <option value="verb">Verb failed</option>
            <option value="act">Review act failed</option>
          </select>
        </InstrumentGroup>
        {settingsNote ? (
          <InstrumentGroup label="Action">
            <span className="notice-lab__hint">{settingsNote}</span>
          </InstrumentGroup>
        ) : null}
      </Instrument>

      <div className="notice-lab__stage">
        <p className="notice-lab__map">The map would be here.</p>
        <NoticeSurface />
      </div>

      <OverlayPanel
        id="notice-lab-cards"
        side="right"
        title="Cards"
        open={cardsOpen}
        onToggle={setCardsOpen}
      >
        <div className="notice-lab__cards">
          <p className="notice-lab__lede">
            Inline cards as they ship. Block and dock sit on the stage — pick
            them from the instrument. This drawer stays up so a block does not
            hide the specimens.
          </p>

          <h3>Inline · untitled</h3>
          <p className="notice-lab__note">
            Node reader body, Settings, publish, traversal, Review diff.
          </p>
          <NoticeCard kind="fault" body="Could not load this node." />
          <NoticeCard kind="fault" body="This host did not accept the token." />
          <NoticeCard kind="fault" body="Could not read the map." />

          <h3>Inline · titled, dismissible</h3>
          <p className="notice-lab__note">
            Same object as a dock card, placed next to a control.
          </p>
          <NoticeCard
            kind="fault"
            title="That did not complete"
            body="The traversal could not run."
            dismissible
            onDismiss={() => {}}
          />

          <h3>Not a card yet</h3>
          <p className="notice-lab__note">
            Source sidecar failure still uses a muted status line.
          </p>
          <p className="node-reader__source-error" role="status">
            Could not read this node&apos;s source.
          </p>
        </div>
      </OverlayPanel>
    </div>
  );
}

export function NoticeLabPage() {
  return (
    <ProductShell active="graph">
      <NoticeLabBody />
    </ProductShell>
  );
}
