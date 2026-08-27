import type { CSSProperties, ReactNode } from "react";
import "./gap-shell.css";

type GapShellProps = {
  width?: number;
  height?: number;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
};

/** Marked presence container — geometry only, no chrome. */
export function GapShell({
  width = 112,
  height = 88,
  children,
  className,
  style,
}: GapShellProps) {
  return (
    <div
      className={["gap-shell", className].filter(Boolean).join(" ")}
      style={{ width, height, ...style }}
    >
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        overflow="visible"
        aria-hidden
      >
        {children}
      </svg>
    </div>
  );
}
