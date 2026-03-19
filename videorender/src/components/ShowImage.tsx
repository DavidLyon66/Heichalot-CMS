import React from 'react';
import {
  AbsoluteFill,
  Easing,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const targetToImagePath = (target: string): string => {
  return `images/${target}.png`;
};

type MotionSpec =
  | {type: 'zoom_in'}
  | {type: 'zoom_out'}
  | {type: 'scroll_up'}
  | {type: 'scroll_down'}
  | Record<string, unknown>
  | undefined;

type ZoomCurve =
  | 'linear'
  | 'ease_in'
  | 'ease_out'
  | 'ease_in_out'
  | 'strong_ease_in'
  | 'strong_ease_out'
  | 'strong_ease_in_out';

const zoomCurveMap: Record<ZoomCurve, (input: number) => number> = {
  linear: Easing.linear,
  ease_in: Easing.in(Easing.quad),
  ease_out: Easing.out(Easing.quad),
  ease_in_out: Easing.inOut(Easing.quad),
  strong_ease_in: Easing.in(Easing.cubic),
  strong_ease_out: Easing.out(Easing.cubic),
  strong_ease_in_out: Easing.inOut(Easing.cubic),
};

export const ShowImage: React.FC<{
  file?: string;
  target?: string;
  motion?: MotionSpec;
  zoomStart?: number;
  zoomEnd?: number;
  zoomCurve?: ZoomCurve;
}> = ({
  file,
  target,
  motion,
  zoomStart,
  zoomEnd,
  zoomCurve,
}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();

  const src = file
    ? staticFile(`images/${file}`)
    : target
    ? staticFile(targetToImagePath(target))
    : null;

  if (!src) {
    return (
      <AbsoluteFill
        style={{
          justifyContent: 'center',
          alignItems: 'center',
          backgroundColor: 'black',
          color: 'white',
          fontSize: 36,
        }}
      >
        SHOW image missing file/target
      </AbsoluteFill>
    );
  }

  let scale = 1;
  let translateY = 0;

  if (zoomStart !== undefined && zoomEnd !== undefined) {
    const easing = zoomCurveMap[zoomCurve ?? 'linear'];
    scale = interpolate(frame, [0, durationInFrames], [zoomStart, zoomEnd], {
      easing,
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
  } else {
    if (motion?.type === 'zoom_in') {
      scale = interpolate(frame, [0, durationInFrames], [1, 1.08], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      });
    }

    if (motion?.type === 'zoom_out') {
      scale = interpolate(frame, [0, durationInFrames], [1.08, 1], {
        extrapolateLeft: 'clamp',
        extrapolateRight: 'clamp',
      });
    }
  }

  if (motion?.type === 'scroll_up') {
    translateY = interpolate(frame, [0, durationInFrames], [0, -60], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
  }

  if (motion?.type === 'scroll_down') {
    translateY = interpolate(frame, [0, durationInFrames], [-60, 0], {
      extrapolateLeft: 'clamp',
      extrapolateRight: 'clamp',
    });
  }

  return (
    <AbsoluteFill
      style={{
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: 'black',
        overflow: 'hidden',
      }}
    >
      <Img
        src={src}
        style={{
          width: '100%',
          height: '100%',
          objectFit: 'contain',
          transform: `translateY(${translateY}px) scale(${scale})`,
          transformOrigin: 'center center',
        }}
      />
    </AbsoluteFill>
  );
};