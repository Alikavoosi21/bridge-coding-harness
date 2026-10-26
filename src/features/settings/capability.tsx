'use client';

import { Badge } from '@/components/ui/primitives';
import type { Model } from '@/lib/api';
import { capabilityOf } from '@/lib/harness/setup-flow';

/** The one place a model's ability to call tools is shown as a short badge. */
export function CapabilityBadge({ model }: { model: Model }) {
  const view = capabilityOf(model);
  return (
    <Badge tone={view.tone} title={view.detail}>
      {view.label}
    </Badge>
  );
}

/** A sentence under the badge for screens where there is room to explain it. */
export function CapabilityNote({ model }: { model: Model }) {
  const view = capabilityOf(model);
  return (
    <p className="text-muted-foreground text-xs leading-6">
      <span className="text-foreground font-medium">{view.label}:</span> {view.detail}
    </p>
  );
}
