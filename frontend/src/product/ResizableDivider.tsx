import type {
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from "react";
import "./ResizableDivider.css";

type ResizableDividerProps = {
  label: string;
  controls: string;
  size: number;
  defaultSize: number;
  minSize: number;
  maxSize: number;
  minTrailingSize: number;
  onResize: (size: number) => void;
  /**
   * CSS custom property applied on the divider's parent while dragging.
   * When set, React `onResize` runs only on pointer-up (and keyboard /
   * double-click), so layouts that host heavy canvases do not re-render
   * every move frame. Preview still reflows the grid via the variable.
   */
  cssVariable?: string;
  className?: string;
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.round(value)));
}

export function readStoredPanelSize(key: string, fallback: number) {
  try {
    const value = Number(window.localStorage.getItem(key));
    return Number.isFinite(value) && value > 0 ? value : fallback;
  } catch {
    return fallback;
  }
}

export function storePanelSize(key: string, value: number) {
  try {
    window.localStorage.setItem(key, String(Math.round(value)));
  } catch {
    /* Resizing remains useful when storage is unavailable. */
  }
}

export function ResizableDivider({
  label,
  controls,
  size,
  defaultSize,
  minSize,
  maxSize,
  minTrailingSize,
  onResize,
  cssVariable,
  className = "",
}: ResizableDividerProps) {
  const availableMax = (element: HTMLElement) => {
    const width = element.parentElement?.getBoundingClientRect().width ?? 0;
    return Math.max(
      minSize,
      Math.min(maxSize, width ? width - minTrailingSize - 9 : maxSize),
    );
  };

  const paintPreview = (element: HTMLElement, value: number) => {
    if (!cssVariable) return;
    element.parentElement?.style.setProperty(cssVariable, `${value}px`);
  };

  const apply = (
    element: HTMLElement,
    value: number,
    mode: "live" | "commit",
  ) => {
    const next = clamp(value, minSize, availableMax(element));
    element.dataset.currentSize = String(next);
    if (mode === "live" && cssVariable) {
      paintPreview(element, next);
      return next;
    }
    paintPreview(element, next);
    onResize(next);
    return next;
  };

  const finish = (element: HTMLElement, pointerId: number) => {
    if (element.hasPointerCapture(pointerId)) {
      element.releasePointerCapture(pointerId);
    }
    document.documentElement.classList.remove("is-panel-resizing");
    if (!cssVariable) return;
    const current = Number(element.dataset.currentSize);
    if (Number.isFinite(current) && current > 0) {
      onResize(current);
    }
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const element = event.currentTarget;
    const startX = event.clientX;
    const startSize = size;
    element.dataset.startX = String(startX);
    element.dataset.startSize = String(startSize);
    element.dataset.currentSize = String(startSize);
    element.setPointerCapture(event.pointerId);
    document.documentElement.classList.add("is-panel-resizing");
    event.preventDefault();
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const element = event.currentTarget;
    if (!element.hasPointerCapture(event.pointerId)) return;
    const startX = Number(element.dataset.startX ?? event.clientX);
    const startSize = Number(element.dataset.startSize ?? size);
    apply(element, startSize + event.clientX - startX, "live");
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? 48 : 16;
    if (event.key === "ArrowLeft") apply(event.currentTarget, size - step, "commit");
    else if (event.key === "ArrowRight") apply(event.currentTarget, size + step, "commit");
    else if (event.key === "Home") apply(event.currentTarget, minSize, "commit");
    else if (event.key === "End") apply(event.currentTarget, maxSize, "commit");
    else return;
    event.preventDefault();
  };

  return (
    <div
      className={`panel-divider${className ? ` ${className}` : ""}`}
      role="separator"
      aria-label={label}
      aria-controls={controls}
      aria-orientation="vertical"
      aria-valuemin={minSize}
      aria-valuemax={maxSize}
      aria-valuenow={Math.round(size)}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={(event) => finish(event.currentTarget, event.pointerId)}
      onPointerCancel={(event) => finish(event.currentTarget, event.pointerId)}
      onLostPointerCapture={() =>
        document.documentElement.classList.remove("is-panel-resizing")
      }
      onDoubleClick={(event) => apply(event.currentTarget, defaultSize, "commit")}
      onKeyDown={onKeyDown}
      title="Drag to resize · Double-click to reset"
    />
  );
}
