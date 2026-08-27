import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  type RefObject,
} from "react";
import type { MotionPlan } from "./motion";

export type PlayMotionOptions = {
  delay?: number;
  direction?: PlaybackDirection;
  fill?: FillMode;
  iterations?: number;
  onFinish?: () => void;
};

export type MotionController<T extends Element> = {
  ref: RefObject<T | null>;
  play: (
    frames: Keyframe[] | PropertyIndexedKeyframes,
    plan: MotionPlan,
    options?: PlayMotionOptions,
  ) => Animation | null;
  cancel: () => void;
  finish: () => void;
};

/**
 * React adapter for the renderer-independent motion kernel.
 *
 * Web Animations is used rather than class toggles for reference interactions:
 * interruption and ownership of the active animation stay explicit, while the
 * browser still performs transform/opacity interpolation off the React render
 * loop.
 */
export function useMotion<T extends Element>(): MotionController<T> {
  const ref = useRef<T | null>(null);
  const animationRef = useRef<Animation | null>(null);

  const cancel = useCallback(() => {
    animationRef.current?.cancel();
    animationRef.current = null;
  }, []);

  const finish = useCallback(() => {
    animationRef.current?.finish();
  }, []);

  const play = useCallback(
    (
      frames: Keyframe[] | PropertyIndexedKeyframes,
      plan: MotionPlan,
      options: PlayMotionOptions = {},
    ) => {
      const element = ref.current;
      if (!element) return null;
      cancel();

      const reducedMotion = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      const animation = element.animate(frames, {
        duration: reducedMotion ? 1 : plan.durationMs,
        delay: reducedMotion ? 0 : options.delay,
        direction: options.direction,
        easing: plan.easing.css,
        fill: options.fill ?? "none",
        iterations: options.iterations,
      });
      animationRef.current = animation;
      animation.finished
        .then(() => {
          if (animationRef.current !== animation) return;
          animationRef.current = null;
          options.onFinish?.();
        })
        .catch(() => {
          // Cancellation is an interaction handoff, not an error.
        });
      return animation;
    },
    [cancel],
  );

  useEffect(() => cancel, [cancel]);

  return useMemo(
    () => ({ ref, play, cancel, finish }),
    [cancel, finish, play],
  );
}
