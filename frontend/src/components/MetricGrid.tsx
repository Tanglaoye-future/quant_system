import { ReactNode } from 'react';

export default function MetricGrid({ children }: { children: ReactNode }) {
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">{children}</div>
  );
}
