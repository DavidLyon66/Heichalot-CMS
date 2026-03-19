import React from 'react';
import {AbsoluteFill} from 'remotion';

export const HoldScene: React.FC<{target: string}> = ({target}) => {
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: 'black',
        color: 'white',
        fontSize: 42,
        fontFamily: 'sans-serif',
      }}
    >
      HOLD: {target}
    </AbsoluteFill>
  );
};