import { queryOptions } from '@tanstack/angular-query-experimental';
import type { ApiClient } from '../api/api-client';

/** Reference data for the place-order form and the list's filters. It changes rarely, hence the long `staleTime`. */
const CATALOG_STALE_MS = 60_000;

export const catalogProductsQuery = (api: ApiClient) =>
  queryOptions({ queryKey: ['catalog', 'products'], queryFn: async () => (await api.catalogProducts()).data.items, staleTime: CATALOG_STALE_MS });

export const catalogRetailersQuery = (api: ApiClient) =>
  queryOptions({ queryKey: ['catalog', 'retailers'], queryFn: async () => (await api.catalogRetailers()).data.items, staleTime: CATALOG_STALE_MS });

export const catalogCompaniesQuery = (api: ApiClient) =>
  queryOptions({ queryKey: ['catalog', 'companies'], queryFn: async () => (await api.catalogCompanies()).data.items, staleTime: CATALOG_STALE_MS });
