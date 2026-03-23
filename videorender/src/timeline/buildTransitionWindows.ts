import type {SceneEvent, TimedScene} from './buildSceneTiming';

export type TransitionWindow = {
  fromSceneIndex: number;
  toSceneIndex: number;
  name: string;
  mode: 'builtin' | 'custom';
  durationFrames: number;
  beforeFrames: number;
  afterFrames: number;
  windowStart: number;
  cutFrame: number;
  windowEnd: number; // exclusive
};

const getOutgoingTransition = (
  scene: TimedScene,
): Extract<SceneEvent, {type: 'transition'}> | null => {
  const events = scene.events ?? [];
  const transition = events.find(
    (e): e is Extract<SceneEvent, {type: 'transition'}> =>
      e.type === 'transition',
  );

  return transition ?? null;
};

export const buildTransitionWindows = (
  scenes: TimedScene[],
): TransitionWindow[] => {
  const out: TransitionWindow[] = [];

  for (let i = 0; i < scenes.length - 1; i++) {
    const fromScene = scenes[i];
    const toScene = scenes[i + 1];
    const transition = getOutgoingTransition(fromScene);

    if (!transition) {
      continue;
    }

    const beforeFrames = Math.floor(transition.durationFrames / 2);
    const afterFrames = transition.durationFrames - beforeFrames;
    const cutFrame = fromScene.endFrame;

    if (beforeFrames > fromScene.durationFrames) {
      throw new Error(
        `Transition "${transition.name}" consumes ${beforeFrames}f before the cut, but scene ${fromScene.sceneIndex} only has ${fromScene.durationFrames}f`,
      );
    }

    if (afterFrames > toScene.durationFrames) {
      throw new Error(
        `Transition "${transition.name}" consumes ${afterFrames}f after the cut, but scene ${toScene.sceneIndex} only has ${toScene.durationFrames}f`,
      );
    }

    out.push({
      fromSceneIndex: i,
      toSceneIndex: i + 1,
      name: transition.name,
      mode: transition.mode,
      durationFrames: transition.durationFrames,
      beforeFrames,
      afterFrames,
      windowStart: cutFrame - beforeFrames,
      cutFrame,
      windowEnd: cutFrame + afterFrames,
    });
  }

  return out;
};