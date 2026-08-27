import {
  BaseBehavior,
  CanvasEvent,
  ComboEvent,
  CommonEvent,
  EdgeEvent,
  ExtensionCategory,
  NodeEvent,
  register,
  type BaseBehaviorOptions,
  type EdgeData,
  type ID,
  type IPointerEvent,
  type RuntimeContext,
} from "@antv/g6";
import { uniqueId } from "@antv/util";

const ASSIST_EDGE_ID = "g6-right-click-create-edge-assist";
const ASSIST_NODE_ID = "g6-right-click-create-edge-assist-node";
const OVERRIDE_KEY = "__internal_override__";

type AssistEdgeStyle = Record<string, unknown>;

export interface RightClickCreateEdgeOptions extends BaseBehaviorOptions {
  enable?: boolean | ((event: IPointerEvent) => boolean);
  style?: AssistEdgeStyle;
  onCreate?: (edge: EdgeData) => EdgeData | undefined;
  onFinish?: (edge: EdgeData) => void;
  onCancel?: () => void;
}

function targetId(event: IPointerEvent): ID | undefined {
  const target = event.target as { id?: ID } | null;
  return target?.id;
}

class RightClickCreateEdge extends BaseBehavior<RightClickCreateEdgeOptions> {
  static defaultOptions: Partial<RightClickCreateEdgeOptions> = {
    animation: true,
    enable: true,
    style: {},
    onCreate: (data) => data,
    onFinish: () => {},
    onCancel: () => {},
  };

  source?: ID;

  constructor(context: RuntimeContext, options: RightClickCreateEdgeOptions) {
    super(context, { ...RightClickCreateEdge.defaultOptions, ...options });
    this.bindEvents();
  }

  update(options: Partial<RightClickCreateEdgeOptions>) {
    super.update(options);
    this.bindEvents();
  }

  private bindEvents() {
    const { graph } = this.context;
    this.unbindEvents();
    graph.on(NodeEvent.CONTEXT_MENU, this.handleNodeContextMenu);
    graph.on(ComboEvent.CONTEXT_MENU, this.handleNodeContextMenu);
    graph.on(CanvasEvent.CLICK, this.cancelEdge);
    graph.on(CanvasEvent.CONTEXT_MENU, this.cancelEdge);
    graph.on(EdgeEvent.CLICK, this.cancelEdge);
    graph.on(CommonEvent.POINTER_MOVE, this.updateAssistEdge);
    window.addEventListener("keydown", this.handleKeyDown);
  }

  private unbindEvents() {
    const { graph } = this.context;
    graph.off(NodeEvent.CONTEXT_MENU, this.handleNodeContextMenu);
    graph.off(ComboEvent.CONTEXT_MENU, this.handleNodeContextMenu);
    graph.off(CanvasEvent.CLICK, this.cancelEdge);
    graph.off(CanvasEvent.CONTEXT_MENU, this.cancelEdge);
    graph.off(EdgeEvent.CLICK, this.cancelEdge);
    graph.off(CommonEvent.POINTER_MOVE, this.updateAssistEdge);
    window.removeEventListener("keydown", this.handleKeyDown);
  }

  private handleKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      void this.cancelEdge();
    }
  };

  private validate(event: IPointerEvent) {
    if (this.destroyed) return false;
    const { enable } = this.options;
    if (typeof enable === "function") return enable(event);
    return !!enable;
  }

  private handleNodeContextMenu = async (event: IPointerEvent) => {
    event.preventDefault?.();
    if (!this.validate(event)) return;
    const id = targetId(event);
    if (!id) return;

    if (this.source) {
      await this.createEdge(event);
      await this.finishAssist();
      return;
    }

    await this.startAssist(id);
  };

  private startAssist = async (id: ID) => {
    const { graph, canvas, batch, element } = this.context;
    const { style } = this.options;
    if (!batch || !element) return;

    batch.startBatch();
    canvas.setCursor("crosshair");
    this.source = id;
    const sourceNode = graph.getElementData(id);
    const sx = sourceNode.style?.x as number | undefined;
    const sy = sourceNode.style?.y as number | undefined;
    graph.addNodeData([
      {
        id: ASSIST_NODE_ID,
        type: "circle",
        [OVERRIDE_KEY]: false,
        style: {
          size: 1,
          visibility: "hidden",
          ports: [{ key: "port-1", placement: [0.5, 0.5] }],
          x: sx,
          y: sy,
        },
      },
    ]);
    graph.addEdgeData([
      {
        id: ASSIST_EDGE_ID,
        source: id,
        target: ASSIST_NODE_ID,
        style: { pointerEvents: "none", ...style },
      },
    ]);
    await element.draw({ animation: false })?.finished;
  };

  private updateAssistEdge = async (event: IPointerEvent) => {
    if (!this.source) return;
    const { model, element, graph } = this.context;
    if (!element) return;
    const [x, y] = graph.getCanvasByClient([event.client.x, event.client.y]);
    model.translateNodeTo(ASSIST_NODE_ID, [x, y]);
    await element.draw({ animation: false, silence: true })?.finished;
  };

  private createEdge = async (event: IPointerEvent) => {
    const { graph } = this.context;
    const { style, onFinish, onCreate } = this.options;
    const finishId = targetId(event);
    if (!finishId || this.source === undefined) return;
    if (finishId === this.source) return;

    const id = `${this.source}-${finishId}-${uniqueId()}`;
    const edgeData = onCreate({
      id,
      source: this.source,
      target: finishId,
      style,
    });
    if (edgeData) {
      graph.addEdgeData([edgeData]);
      onFinish(edgeData);
      await graph.draw();
    }
  };

  private finishAssist = async () => {
    if (!this.source) return;
    const { graph, element, batch } = this.context;
    if (!element || !batch) return;
    graph.removeNodeData([ASSIST_NODE_ID]);
    this.source = undefined;
    canvasReset(this.context);
    await element.draw({ animation: false })?.finished;
    batch.endBatch();
  };

  private cancelEdge = async () => {
    if (!this.source) return;
    const { onCancel } = this.options;
    await this.finishAssist();
    onCancel();
  };

  destroy() {
    this.unbindEvents();
    super.destroy();
  }
}

function canvasReset(context: RuntimeContext) {
  context.canvas.setCursor("default");
}

let registered = false;

export function ensureRightClickCreateEdgeRegistered() {
  if (registered) return;
  register(ExtensionCategory.BEHAVIOR, "right-click-create-edge", RightClickCreateEdge);
  registered = true;
}

export type { RightClickCreateEdgeOptions as RightClickCreateEdgeBehaviorOptions };
