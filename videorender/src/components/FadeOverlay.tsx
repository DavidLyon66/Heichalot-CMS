import React from 'react';
import {AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame} from 'remotion';

const targetToImagePath = (target: string): string => {
  return `images/${target}.png`;
};

export const FadeOverlay: React.FC<{target: string}> = ({target}) => {
  const frame = useCurrentFrame();

  const opacity = interpolate(frame, [0, 20], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  return (
    <AbsoluteFill style={{backgroundColor: 'black'}}>
      <Img
        src={staticFile(targetToImagePath(target))}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          opacity,
        }}
      />
    </AbsoluteFill>
  );
};