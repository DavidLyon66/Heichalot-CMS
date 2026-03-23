import React from 'react';
import type {
  TransitionPresentation,
  TransitionPresentationComponentProps,
} from '@remotion/transitions';
import {AbsoluteFill, interpolate} from 'remotion';

type ParticleBlurProps = {};

const ParticleBlurPresentation: React.FC<
  TransitionPresentationComponentProps<ParticleBlurProps>
> = ({children, presentationDirection, presentationProgress}) => {
  const blurPx = interpolate(presentationProgress, [0, 1], [24, 0]);

  const opacity =
    presentationDirection === 'entering'
      ? presentationProgress
      : 1 - presentationProgress * 0.15;

  const scale =
    presentationDirection === 'entering'
      ? interpolate(presentationProgress, [0, 1], [1.04, 1])
      : interpolate(presentationProgress, [0, 1], [1, 0.985]);

  return (
    <AbsoluteFill
      style={{
        opacity,
        filter: `blur(${blurPx}px)`,
        transform: `scale(${scale})`,
      }}
    >
      {children}
    </AbsoluteFill>
  );
};

export const particleBlur = (): TransitionPresentation<ParticleBlurProps> => {
  return {
    component: ParticleBlurPresentation,
    props: {},
  };
};