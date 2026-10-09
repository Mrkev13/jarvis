import { Suspense } from 'react';
import MaterialsPage from '@/modules/school/MaterialsPage';
import { LoadingState } from '@/components/ui';

export default function Page() {
  return <Suspense fallback={<LoadingState lines={4} />}><MaterialsPage /></Suspense>;
}
