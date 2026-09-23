import React from 'react';
import { AuthLayout, PublicLayout, ProtectedLayout } from '@shared/ui/layout';
import { ROUTE_LAYOUTS } from './routes';

export const layoutMap = {
  [ROUTE_LAYOUTS.PUBLIC]: <PublicLayout />,
  [ROUTE_LAYOUTS.PROTECTED]: <ProtectedLayout />,
  [ROUTE_LAYOUTS.AUTH]: <AuthLayout />,
};
