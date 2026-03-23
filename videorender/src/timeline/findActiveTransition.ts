import type {TimedScene} from './buildSceneTiming';
import type {TransitionWindow} from './buildTransitionWindows';

export const findActiveTransition = (
  frame: number,
  windows: TransitionWindow[],
): TransitionWindow | null => {
  for (const window of windows) {
    if (frame >= window.windowStart && frame < window.windowEnd) {
      return window;
    }
  }

  return null;
};

export const findOwningScene = (
  frame: number,
  scenes: TimedScene[],
): TimedScene => {
  const found = scenes.find((scene) => {
    return frame >= scene.startFrame && frame < scene.endFrame;
  });

  if (found) {
    return found;
  }

  return scenes[Math.max(0, scenes.length - 1)];
};

export const getTransitionProgress = (
  frame: number,
  window: TransitionWindow,
): number => {
  const span = window.windowEnd - window.windowStart;

  if (span <= 0) {
    return 1;
  }

  const raw = (frame - window.windowStart) / span;
  return Math.max(0, Math.min(1, raw));
};