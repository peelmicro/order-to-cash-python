import { ApplicationConfig, provideBrowserGlobalErrorListeners, provideZonelessChangeDetection } from '@angular/core';
import { TitleStrategy } from '@angular/router';
import { provideFileRouter } from '@analogjs/router';
import { provideTanStackQuery } from '@tanstack/angular-query-experimental';
import { AppTitleStrategy } from './lib/title-strategy';
import { QUERY_CLIENT } from './session/signed-out';

/**
 * The application's providers. src/app/testing/browser-harness.ts mounts the same ones in the test bed, replacing only
 * the network seam; src/app/app-config.spec.ts fails if this list gains a provider the harness would not have.
 */
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideFileRouter(),
    { provide: TitleStrategy, useClass: AppTitleStrategy },
    provideTanStackQuery(QUERY_CLIENT),
  ],
};
