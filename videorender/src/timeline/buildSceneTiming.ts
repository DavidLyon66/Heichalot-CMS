export type SceneEvent =
  | {
      type: 'transition';
      name: string;
      mode: 'builtin' | 'custom';
      durationFrames: number;
    }
  | {
      type: string;
      [key: string]: unknown;
    };

export type CompiledScene = {
  sceneIndex: number;
  background: string;
  durationFrames: number;
  events?: SceneEvent[];
};

export type TimedScene = CompiledScene & {
  startFrame: number;
  endFrame: number; // exclusive
};

export const buildSceneTiming = (scenes: CompiledScene[]): TimedScene[] => {
  let cursor = 0;

  return scenes.map((scene) => {
    const timed: TimedScene = {
      ...scene,
      startFrame: cursor,
      endFrame: cursor + scene.durationFrames,
    };

    cursor += scene.durationFrames;
    return timed;
  });
};

export const getTotalDurationInFrames = (scenes: CompiledScene[]): number => {
  return scenes.reduce((sum, scene) => sum + scene.durationFrames, 0);
};