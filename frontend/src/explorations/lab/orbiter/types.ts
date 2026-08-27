export type OrbiterForm = "crisp" | "wobbly" | "triangle";

export type ClutterMode = "distributed" | "aggregate";

/** Shared equal orbit distance — belonging by proximity, one track. */
export const ORBIT_RADIUS = 88;

/** Degrees per second — slow gravitational drift. */
export const ORBIT_SPEED_DEG = 14;

export const ORBITER_FORM_COPY: Record<
  OrbiterForm,
  { title: string; meaning: string }
> = {
  crisp: {
    title: "Crisp circle",
    meaning: "Calm auxiliary fact — a small still moon",
  },
  wobbly: {
    title: "Wobbly circle",
    meaning: "Pending / uncertain — same wobble as a provisional mass",
  },
  triangle: {
    title: "Triangle",
    meaning: "Directional alert — points toward action",
  },
};

export type OrbiterSpec = {
  id: string;
  form: OrbiterForm;
  /** Starting angle on the shared orbit (degrees) */
  angle: number;
};

/** Three forms, equal radius, evenly spaced. */
export const DEFAULT_ORBITERS: OrbiterSpec[] = [
  { id: "o-crisp", form: "crisp", angle: 20 },
  { id: "o-wobbly", form: "wobbly", angle: 140 },
  { id: "o-tri", form: "triangle", angle: 260 },
];

export const NODE_SIZE = 120;
