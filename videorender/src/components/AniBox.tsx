import React from 'react';
import {AbsoluteFill, Img, staticFile} from 'remotion';

export const AniBox: React.FC<{file: string}> = ({file}) => {
  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        pointerEvents: 'none',
      }}
    >
      <div
        style={{
          width: '32%',
          height: '32%',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          overflow: 'hidden',
          borderRadius: 12,
          boxShadow: '0 8px 30px rgba(0,0,0,0.35)',
          backgroundColor: 'rgba(0,0,0,0.15)',
        }}
      >
        <Img
          src={staticFile(`images/${file}`)}
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'contain',
          }}
        />
      </div>
    </AbsoluteFill>
  );
};