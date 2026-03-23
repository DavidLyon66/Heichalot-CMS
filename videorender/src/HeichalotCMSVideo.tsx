import React, {useMemo} from 'react';
import {useCurrentFrame} from 'remotion';
import {
  buildSceneTiming,
  type CompiledScene,
} from './timeline/buildSceneTiming';
import {buildTransitionWindows} from './timeline/buildTransitionWindows';
import {
  findActiveTransition,
  findOwningScene,
  getTransitionProgress,
} from './timeline/findActiveTransition';
import {SceneFrame} from './render/SceneFrame';
import {TransitionFrame} from './transitions/TransitionFrame';

type Props = {
  scenes: CompiledScene[];
};

export const HeichalotCMSVideo: React.FC<Props> = ({scenes}) => {
  const frame = useCurrentFrame();

  const timedScenes = useMemo(() => buildSceneTiming(scenes), [scenes]);
  const transitionWindows = useMemo(
    () => buildTransitionWindows(timedScenes),
    [timedScenes],
  );

  const activeTransition = findActiveTransition(frame, transitionWindows);

  if (!activeTransition) {
    const scene = findOwningScene(frame, timedScenes);

    return <SceneFrame scene={scene} absoluteFrame={frame} />;
  }

  const fromScene = timedScenes[activeTransition.fromSceneIndex];
  const toScene = timedScenes[activeTransition.toSceneIndex];
  const progress = getTransitionProgress(frame, activeTransition);

  return (
    <TransitionFrame
      name={activeTransition.name}
      mode={activeTransition.mode}
      progress={progress}
      fromScene={<SceneFrame scene={fromScene} absoluteFrame={frame} />}
      toScene={<SceneFrame scene={toScene} absoluteFrame={frame} />}
    />
  );
};