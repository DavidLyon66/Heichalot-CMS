import React from 'react';
import {Composition} from 'remotion';
import {VideoFromJSON} from './VideoFromJSON';

export const Root: React.FC = () => {
  return (
    <Composition
      id="VideoFromJSON"
      component={VideoFromJSON}
      width={1920}
      height={1080}
      fps={30}
      durationInFrames={900}
      defaultProps={{}}
    />
  );
};