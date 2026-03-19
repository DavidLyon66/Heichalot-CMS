import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';

export const SfxEvent: React.FC<{file: string}> = ({file}) => {
  return (
    <AbsoluteFill>
      <Audio src={staticFile(`sfx/${file}`)} />
    </AbsoluteFill>
  );
};