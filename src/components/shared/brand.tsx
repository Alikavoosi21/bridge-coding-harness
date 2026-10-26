import Image from 'next/image';

import { cn } from '@/lib/utils';

/** Independent coding mark. Brand SVGs stay crisp at every size, so they bypass the
 *  image optimizer (which refuses SVG unless explicitly allowed). */
export function BridgeSymbol({ size = 28, className }: { size?: number; className?: string }) {
  return (
    <Image
      src="/brand/approved-bridge.svg"
      alt=""
      width={size}
      height={size}
      unoptimized
      priority
      className={cn('shrink-0 object-contain', className)}
    />
  );
}

/** The approved Bridge symbol with the independent coding product name. */
export function BridgeHorizontal({ height = 28, className }: { height?: number; className?: string }) {
  return <span className={cn('inline-flex items-center gap-2', className)}>
    <BridgeSymbol size={height} />
    <span dir="ltr" className="font-semibold">Bridge Coding</span>
  </span>;
}
