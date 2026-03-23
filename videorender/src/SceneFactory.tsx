import React from 'react';
import {AbsoluteFill} from 'remotion';
import {AniBox} from './components/AniBox';
import {Dialogue} from './components/Dialogue';
import {FadeOverlay} from './components/FadeOverlay';
import {HoldScene} from './components/HoldScene';
import {SfxEvent} from './components/SfxEvent';
import {ShowImage} from './components/ShowImage';

type RenderEvent =
  | {
      type: 'show';
      file?: string;
      target?: string;
      enter?: Record<string, unknown>;
      leave?: Record<string, unknown>;
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
  | {type: 'fade'; target: string}
  | {type: 'dialogue'; speaker: string; text: string; style?: Record<string, unknown>}
  | {type: 'sfx'; file: string}
  | {type: 'hold'; target: string}
  | {type: 'anibox'; file: string; enter?: string; leave?: string}
  | {type: 'transition'; name: string; mode?: 'builtin' | 'custom'; durationFrames?: number}
  | {type: string; [key: string]: unknown};

export const SceneFactory: React.FC<{event: RenderEvent}> = ({event}) => {
  switch (event.type) {
    case 'show':
      return (
        <ShowImage
          file={event.file}
          target={event.target}
          motion={event.motion}
          zoomStart={event.zoomStart}
          zoomEnd={event.zoomEnd}
          zoomCurve={event.zoomCurve}
        />
      );

    case 'fade':
      return <FadeOverlay target={event.target} />;

    case 'dialogue':
      return (
        <Dialogue
          speaker={event.speaker}
          text={event.text}
          style={event.style}
        />
      );

    case 'sfx':
      return <SfxEvent file={event.file} />;

    case 'hold':
      return <HoldScene target={event.target} />;

    case 'anibox':
      if (event.enter || event.leave) {
        throw new Error(
          `ANIBOX enter/leave effects not implemented yet (enter=${event.enter ?? 'none'}, leave=${event.leave ?? 'none'})`
        );
      }
      return <AniBox file={event.file} />;

    case 'transition':
      return null;

    default:
      return (
        <AbsoluteFill
          style={{
            justifyContent: 'center',
            alignItems: 'center',
            color: 'white',
            fontSize: 42,
          }}
        >
          Unsupported event: {event.type}
        </AbsoluteFill>
      );
  }
};