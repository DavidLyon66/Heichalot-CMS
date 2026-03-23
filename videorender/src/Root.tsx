import React from 'react';
import {Composition} from 'remotion';
import {HeichalotCMSVideo} from './HeichalotCMSVideo';

type RenderEvent = {
  type: string;
  durationFrames?: number;
};

type Scene = {
  durationFrames: number;
  events?: RenderEvent[];
};

type VideoProps = {
  scenes?: Scene[];
  width?: number;
  height?: number;
  fps?: number;
};

const getDurationInFrames = (scenes: Scene[] = []): number => {
  return scenes.reduce((sum, scene) => sum + (scene.durationFrames ?? 0), 0);
};

export const Root: React.FC = () => {
  return (
    <Composition
      id="VideoFromJSON"
      component={HeichalotCMSVideo}
      width={1920}
      height={1080}
      fps={30}
      durationInFrames={1}
      calculateMetadata={({props}: {props: VideoProps}) => {
        const scenes = props?.scenes ?? [];
        return {
          durationInFrames: Math.max(1, getDurationInFrames(scenes)),
          width: props?.width ?? 1920,
          height: props?.height ?? 1080,
          fps: props?.fps ?? 30,
          props,
        };
      }}
      defaultProps={{}}
    />
  );
};