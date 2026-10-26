'use client';

import Image from 'next/image';
import { useEffect, useState } from 'react';

import { cn } from '@/lib/utils';

export type MotionState = 'loading' | 'executing' | 'approval' | 'correcting' | 'success';

/**
 * One of the coding product's motion pieces, tied to a real state. The GIF only
 * plays while the tab is visible and motion is allowed; otherwise the matching
 * static poster is used, so nothing animates for decoration or in the background.
 */
export function StateMotion({
  state,
  size = 48,
  className,
  alt = '',
}: {
  state: MotionState;
  size?: number;
  className?: string;
  alt?: string;
}) {
  const [animated, setAnimated] = useState(false);

  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setAnimated(!query.matches && document.visibilityState === 'visible');
    update();
    query.addEventListener('change', update);
    document.addEventListener('visibilitychange', update);
    return () => {
      query.removeEventListener('change', update);
      document.removeEventListener('visibilitychange', update);
    };
  }, []);

  return (
    <Image
      src={animated ? `/motion/bridge-${state}.gif` : `/motion/bridge-${state}-poster.png`}
      alt={alt}
      width={size}
      height={size}
      unoptimized
      className={cn('shrink-0 object-contain', className)}
    />
  );
}
