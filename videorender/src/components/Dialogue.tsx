import React from 'react';
import {
  AbsoluteFill,
  Img,
  interpolate,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

type CurrentWordHighlight = {
  enabled?: boolean;
  color?: string;
  opacity?: number;
  image?: string;
  padLeft?: number;
  padRight?: number;
  padTop?: number;
  padBottom?: number;
};

type BoxBackground = {
  enabled?: boolean;
  color?: string;
  opacity?: number;
  image?: string;
  imageOpacity?: number;
  tintColor?: string;
  tintOpacity?: number;
  padding?: number;
  borderRadius?: number;
};

type BoxEnter = {
  type?: 'fade' | 'fade_up';
  durationFrames?: number;
  offsetY?: number;
};

type DialogueStyle = {
  fontFamily?: string;
  fontSize?: number;
  color?: string;
  opacity?: number;
  align?: 'left' | 'center' | 'right';
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  wordTiming?: number;

  textMaskImage?: string;
  textMaskOpacity?: number;

  currentWordFontSizeAdjust?: number;
  currentWordHighlight?: CurrentWordHighlight;

  boxBackground?: BoxBackground;
  boxEnter?: BoxEnter;
};

type DialogueProps = {
  speaker: string;
  text: string;
  style?: DialogueStyle;
};

const getWordIndex = (
  frame: number,
  fps: number,
  wordTimingSeconds: number,
  totalWords: number
): number => {
  const framesPerWord = Math.max(1, Math.round(wordTimingSeconds * fps));
  const idx = Math.floor(frame / framesPerWord);
  return Math.max(0, Math.min(idx, totalWords - 1));
};

export const Dialogue: React.FC<DialogueProps> = ({speaker, text, style}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const words = text.trim().split(/\s+/).filter(Boolean);
  const totalWords = words.length;

  const fontFamily = style?.fontFamily ?? 'Georgia, serif';
  const fontSize = style?.fontSize ?? 52;
  const color = style?.color ?? '#ffffff';
  const opacity = style?.opacity ?? 1;
  const align = style?.align ?? 'center';

  const x = style?.x ?? 0.1;
  const y = style?.y ?? 0.7;
  const boxWidth = style?.width ?? 0.8;
  const boxHeight = style?.height ?? 0.2;
  const wordTiming = style?.wordTiming ?? 0.22;

  const currentWordFontSizeAdjust = style?.currentWordFontSizeAdjust ?? 0;

  const highlight = style?.currentWordHighlight ?? {};
  const highlightEnabled = highlight.enabled ?? false;
  const highlightColor = highlight.color ?? '#d9a441';
  const highlightOpacity = highlight.opacity ?? 0.35;
  const highlightImage = highlight.image ?? '';
  const padLeft = highlight.padLeft ?? 8;
  const padRight = highlight.padRight ?? 8;
  const padTop = highlight.padTop ?? 4;
  const padBottom = highlight.padBottom ?? 4;

  const background = style?.boxBackground ?? {};
  const bgEnabled = background.enabled ?? false;
  const bgColor = background.color ?? '#000000';
  const bgOpacity = background.opacity ?? 0.35;
  const bgImage = background.image ?? '';
  const bgImageOpacity = background.imageOpacity ?? 0.5;
  const bgTintColor = background.tintColor ?? '';
  const bgTintOpacity = background.tintOpacity ?? 0;
  const bgPadding = background.padding ?? 24;
  const borderRadius = background.borderRadius ?? 8;

  const enter = style?.boxEnter ?? {};
  const enterType = enter.type ?? 'fade_up';
  const enterDuration = enter.durationFrames ?? 18;
  const enterOffsetY = enter.offsetY ?? 24;

  const enterOpacity = interpolate(
    frame,
    [0, enterDuration],
    [0, 1],
    {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
  );

  const enterTranslateY =
    enterType === 'fade_up'
      ? interpolate(
          frame,
          [0, enterDuration],
          [enterOffsetY, 0],
          {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
        )
      : 0;

  const currentWordIndex = getWordIndex(frame, fps, wordTiming, totalWords);
  const visibleWords = words.slice(0, currentWordIndex + 1);

  const alignItems =
    align === 'left' ? 'flex-start' : align === 'right' ? 'flex-end' : 'center';

  const justifyContent =
    align === 'left' ? 'flex-start' : align === 'right' ? 'flex-end' : 'center';

  return (
    <AbsoluteFill style={{backgroundColor: 'transparent', pointerEvents: 'none'}}>
      <div
        style={{
          position: 'absolute',
          left: `${x * 100}%`,
          top: `${y * 100}%`,
          width: `${boxWidth * 100}%`,
          height: `${boxHeight * 100}%`,
          opacity: enterOpacity,
          transform: `translateY(${enterTranslateY}px)`,
        }}
      >
        <div
          style={{
            position: 'relative',
            width: '100%',
            height: '100%',
            padding: bgPadding,
            boxSizing: 'border-box',
            borderRadius,
            overflow: 'hidden',
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'flex-start',
            alignItems,
          }}
        >
          {bgEnabled ? (
            <>
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  backgroundColor: bgColor,
                  opacity: bgOpacity,
                  borderRadius,
                  zIndex: 0,
                }}
              />

              {bgImage ? (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    opacity: bgImageOpacity,
                    borderRadius,
                    overflow: 'hidden',
                    zIndex: 1,
                  }}
                >
                  <Img
                    src={staticFile(bgImage)}
                    style={{
                      width: '100%',
                      height: '100%',
                      objectFit: 'cover',
                    }}
                  />
                </div>
              ) : null}

              {bgTintColor ? (
                <div
                  style={{
                    position: 'absolute',
                    inset: 0,
                    backgroundColor: bgTintColor,
                    opacity: bgTintOpacity,
                    borderRadius,
                    zIndex: 2,
                  }}
                />
              ) : null}
            </>
          ) : null}

          <div
            style={{
              position: 'relative',
              zIndex: 3,
              width: '100%',
              fontFamily: 'Arial, sans-serif',
              fontSize: 24,
              color,
              opacity: 0.7,
              letterSpacing: 2,
              marginBottom: 12,
              textAlign: align,
            }}
          >
            {speaker}
          </div>

          <div
            style={{
              position: 'relative',
              zIndex: 3,
              width: '100%',
            }}
          >
            <div
              style={{
                fontFamily,
                fontSize,
                color,
                lineHeight: 1.35,
                textAlign: align,
                whiteSpace: 'normal',
                textShadow: '0 2px 12px rgba(0,0,0,0.65)',
                display: 'flex',
                flexWrap: 'wrap',
                justifyContent,
                gap: '0.25em',
                position: 'relative',
                zIndex: 1,
                opacity,
              }}
            >
              {visibleWords.map((word, i) => {
                const isCurrent = i === currentWordIndex;

                return (
                  <span
                    key={`${word}-${i}`}
                    style={{
                      position: 'relative',
                      display: 'inline-block',
                      fontSize: isCurrent
                        ? fontSize + currentWordFontSizeAdjust
                        : fontSize,
                      lineHeight: 1.2,
                    }}
                  >
                    {isCurrent && highlightEnabled ? (
                      highlightImage ? (
                        <span
                          style={{
                            position: 'absolute',
                            left: -padLeft,
                            right: -padRight,
                            top: -padTop,
                            bottom: -padBottom,
                            opacity: highlightOpacity,
                            zIndex: 0,
                            overflow: 'hidden',
                            borderRadius: 2,
                          }}
                        >
                          <Img
                            src={staticFile(highlightImage)}
                            style={{
                              width: '100%',
                              height: '100%',
                              objectFit: 'cover',
                            }}
                          />
                        </span>
                      ) : (
                        <span
                          style={{
                            position: 'absolute',
                            left: -padLeft,
                            right: -padRight,
                            top: -padTop,
                            bottom: -padBottom,
                            backgroundColor: highlightColor,
                            opacity: highlightOpacity,
                            zIndex: 0,
                            borderRadius: 2,
                          }}
                        />
                      )
                    ) : null}

                    <span style={{position: 'relative', zIndex: 1}}>{word}</span>
                  </span>
                );
              })}
            </div>

            {style?.textMaskImage ? (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  opacity: style.textMaskOpacity ?? 0.3,
                  zIndex: 4,
                  mixBlendMode: 'multiply',
                }}
              >
                <Img
                  src={staticFile(style.textMaskImage)}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                  }}
                />
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </AbsoluteFill>
  );
};