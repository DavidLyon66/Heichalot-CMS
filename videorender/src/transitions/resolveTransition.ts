import {linearTiming} from '@remotion/transitions';
import {fade} from '@remotion/transitions/fade';
import {slide} from '@remotion/transitions/slide';
import type {
  TransitionPresentation,
  TransitionTiming,
} from '@remotion/transitions';

import {particleBlur} from './custom/ParticleBlur';

type CompiledTransition = {
  type: 'transition';
  name: string;
  mode: 'builtin' | 'custom';
  durationFrames: number;
};

type ResolvedTransition = {
  presentation: TransitionPresentation<any>;
  timing: TransitionTiming;
};

export const resolveTransition = (
  transition: CompiledTransition,
): ResolvedTransition => {
  const timing = linearTiming({
    durationInFrames: transition.durationFrames,
  });

  if (transition.mode === 'builtin') {
    switch (transition.name) {
      case 'fade':
        return {
          presentation: fade(),
          timing,
        };
      case 'slide-left':
        return {
          presentation: slide({direction: 'from-right'}),
          timing,
        };
      case 'slide-right':
        return {
          presentation: slide({direction: 'from-left'}),
          timing,
        };
      default:
        throw new Error(`Unknown built-in transition: ${transition.name}`);
    }
  }

  switch (transition.name) {
    case 'ParticleBlur':
      return {
        presentation: particleBlur(),
        timing,
      };
    default:
      throw new Error(`Unknown custom transition: ${transition.name}`);
  }
};