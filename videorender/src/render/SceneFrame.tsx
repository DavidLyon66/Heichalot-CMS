import React from 'react';
import {AbsoluteFill} from 'remotion';
import type {TimedScene} from '../timeline/buildSceneTiming';
import {ShowImage} from '../components/ShowImage';
import {SceneFactory} from '../SceneFactory';

type Props = {
  scene: TimedScene;
  absoluteFrame: number;
};

export const SceneFrame: React.FC<Props> = ({scene}) => {
  const bg = scene.background as
    | {
        type?: 'show';
        file?: string;
        target?: string;
        motion?: Record<string, unknown>;
        zoomStart?: number;
        zoomEnd?: number;
        zoomCurve?:
          | 'linear'
          | 'ease_in'
          | 'ease_out'
          | 'ease_in_out'
          | 'strong_ease_in'
          | 'strong_ease_out'
          | 'strong_ease_in_out';
      }
    | undefined;

  return (
    <AbsoluteFill>
      {bg?.file || bg?.target ? (
        <ShowImage
          file={bg.file}
          target={bg.target}
          motion={bg.motion}
          zoomStart={bg.zoomStart}
          zoomEnd={bg.zoomEnd}
          zoomCurve={bg.zoomCurve}
        />
      ) : null}

      {(scene.events ?? []).map((event, index) => (
        <React.Fragment key={index}>
          <SceneFactory event={event} />
        </React.Fragment>
      ))}
    </AbsoluteFill>
  );
};