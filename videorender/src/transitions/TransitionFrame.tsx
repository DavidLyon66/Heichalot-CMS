import React from 'react';
import {AbsoluteFill} from 'remotion';

type Props = {
  name: string;
  mode: 'builtin' | 'custom';
  progress: number;
  fromScene: React.ReactNode;
  toScene: React.ReactNode;
};

export const TransitionFrame: React.FC<Props> = ({
  name,
  mode,
  progress,
  fromScene,
  toScene,
}) => {
  if (mode === 'builtin') {
    if (name === 'fade') {
      return (
        <AbsoluteFill>
          <AbsoluteFill style={{opacity: 1 - progress}}>
            {fromScene}
          </AbsoluteFill>
          <AbsoluteFill style={{opacity: progress}}>{toScene}</AbsoluteFill>
        </AbsoluteFill>
      );
    }

    if (name === 'slide-left') {
      return (
        <AbsoluteFill style={{overflow: 'hidden'}}>
          <AbsoluteFill
            style={{
              transform: `translateX(${-progress * 100}%)`,
            }}
          >
            {fromScene}
          </AbsoluteFill>
          <AbsoluteFill
            style={{
              transform: `translateX(${(1 - progress) * 100}%)`,
            }}
          >
            {toScene}
          </AbsoluteFill>
        </AbsoluteFill>
      );
    }

    if (name === 'slide-right') {
      return (
        <AbsoluteFill style={{overflow: 'hidden'}}>
          <AbsoluteFill
            style={{
              transform: `translateX(${progress * 100}%)`,
            }}
          >
            {fromScene}
          </AbsoluteFill>
          <AbsoluteFill
            style={{
              transform: `translateX(${-(1 - progress) * 100}%)`,
            }}
          >
            {toScene}
          </AbsoluteFill>
        </AbsoluteFill>
      );
    }
  }

  if (mode === 'custom') {
    if (name === 'ParticleBlur') {
      const centerBoost = 1 - Math.abs(progress * 2 - 1);
      const blurPx = centerBoost * 18;

      return (
        <AbsoluteFill>
          <AbsoluteFill
            style={{
              opacity: 1 - progress,
              filter: `blur(${blurPx}px)`,
              transform: `scale(${1 + progress * 0.02})`,
            }}
          >
            {fromScene}
          </AbsoluteFill>
          <AbsoluteFill
            style={{
              opacity: progress,
              filter: `blur(${blurPx}px)`,
              transform: `scale(${1.02 - progress * 0.02})`,
            }}
          >
            {toScene}
          </AbsoluteFill>
        </AbsoluteFill>
      );
    }
  }

  throw new Error(`Unknown transition: ${mode}:${name}`);
};