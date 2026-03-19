import React from 'react';
import {AbsoluteFill, Sequence} from 'remotion';
import {SceneFactory} from './SceneFactory';

type BackgroundSpec = {
  type: 'show';
  file: string;
  enter?: Record<string, unknown>;
  leave?: Record<string, unknown>;
  motion?: Record<string, unknown>;
};

type SceneEvent =
  | {
      type: 'dialogue';
      speaker: string;
      text: string;
      style?: Record<string, unknown>;
      durationFrames?: number;
    }
  | {
      type: 'anibox';
      file: string;
      atFrames?: number;
      durationFrames?: number;
      enter?: string;
      leave?: string;
    }
  | {
      type: 'sfx';
      file: string;
      atFrames?: number;
      durationFrames?: number;
    }
  | {
      type: string;
      [key: string]: unknown;
    };

type SceneSpec = {
  type: 'scene';
  background: BackgroundSpec;
  durationFrames: number;
  events: SceneEvent[];
};

type RenderData = {
  fps?: number;
  duration?: number;
  scenes?: SceneSpec[];
};

const estimateDialogueFrames = (text: string, fps: number): number => {
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const wordsPerMinute = 130;
  const seconds = Math.max(2.5, (words / wordsPerMinute) * 60);
  return Math.max(1, Math.round(seconds * fps));
};

const eventDurationFrames = (event: SceneEvent, fps: number): number => {
  if (typeof event.durationFrames === 'number' && event.durationFrames > 0) {
    return event.durationFrames;
  }

  switch (event.type) {
    case 'dialogue':
      return estimateDialogueFrames(event.text ?? '', fps);
    case 'anibox':
      return Math.round(2 * fps);
    case 'sfx':
      return Math.round(1 * fps);
    default:
      return Math.round(2 * fps);
  }
};

const SceneRenderer: React.FC<{scene: SceneSpec; fps: number}> = ({scene, fps}) => {
  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      <SceneFactory event={scene.background} />

       {scene.events.map((event, index) => {
        const from =
          typeof (event as {atFrames?: number}).atFrames === 'number'
            ? (event as {atFrames?: number}).atFrames!
            : 0;

        const durationInFrames = eventDurationFrames(event, fps);

        return (
          <Sequence
            key={index}
            from={from}
            durationInFrames={durationInFrames}
          >
            <SceneFactory event={event} />
          </Sequence>
        );
      })}   </AbsoluteFill>
  );
};

export const VideoFromJSON: React.FC<RenderData> = (data) => {
  const fps = typeof data.fps === 'number' ? data.fps : 30;
  const scenes = Array.isArray(data.scenes) ? data.scenes : [];

  let currentFrom = 0;

  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      {scenes.map((scene, index) => {
        const from = currentFrom;
        currentFrom += scene.durationFrames;

        return (
          <Sequence
            key={index}
            from={from}
            durationInFrames={scene.durationFrames}
          >
            <SceneRenderer scene={scene} fps={fps} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};