import { Suspense } from 'react';
import CalendarPage from '@/modules/calendar/CalendarPage';
import { LoadingState } from '@/components/ui';

export default function Page() {
  return <Suspense fallback={<LoadingState lines={4} />}><CalendarPage /></Suspense>;
}
