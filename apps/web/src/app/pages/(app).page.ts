import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { Router, RouterLink, RouterOutlet } from '@angular/router';
import { RouteMeta } from '@analogjs/router';
import { injectMutation, injectQuery, QueryClient } from '@tanstack/angular-query-experimental';
import { HlmAlertImports } from '@spartan-ng/helm/alert';
import { HlmButtonImports } from '@spartan-ng/helm/button';
import { ApiClient } from '../api/api-client';
import { describeError } from '../lib/problem';
import { STACK_LABEL } from '../lib/stack-label';
import { requireSession, SESSION_KEY, sessionQuery } from '../session/session';

/** The signed-in shell: every page under `src/app/pages/(app)/` renders inside it, behind the session guard. */
export const routeMeta: RouteMeta = { canActivate: [requireSession] };

const SESSION_FALLBACK = 'The session could not be checked.';

@Component({
  selector: 'app-shell',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, ...HlmAlertImports, ...HlmButtonImports],
  template: `
    <header class="border-b">
      <div class="mx-auto flex max-w-6xl items-center gap-6 p-4">
        <strong>Order-To-Cash</strong>
        <span class="text-muted-foreground text-sm" data-testid="stack-label">{{ stackLabel }}</span>
        <nav class="flex gap-4 text-sm" aria-label="Main">
          <a routerLink="/orders">Orders</a>
          <a routerLink="/stock">Stock</a>
          <a routerLink="/billing">Billing</a>
        </nav>
        <span class="text-muted-foreground ms-auto text-sm" data-testid="signed-in-as">{{ session.data()?.displayName ?? session.data()?.username }}</span>
        <button hlmBtn variant="outline" size="sm" type="button" (click)="signOut()" [disabled]="logout.isPending()">Log out</button>
      </div>
    </header>
    <div class="mx-auto flex max-w-6xl flex-col gap-4 p-4">
      @if (session.isError()) {
        <div hlmAlert variant="destructive" data-testid="session-error">
          <p hlmAlertDescription>{{ sessionError() }}</p>
        </div>
      }
      @if (logout.isError()) {
        <div hlmAlert variant="destructive" data-testid="logout-error">
          <p hlmAlertDescription>{{ logoutError() }}</p>
        </div>
      }
      <router-outlet />
    </div>
  `,
})
export default class ShellPage {
  protected readonly stackLabel = STACK_LABEL;
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly queryClient = inject(QueryClient);
  protected readonly session = injectQuery(() => sessionQuery(this.api));

  protected readonly logout = injectMutation(() => ({
    mutationFn: () => this.api.logout(),
    onSuccess: async () => {
      this.queryClient.clear();
      this.queryClient.setQueryData(SESSION_KEY, { authenticated: false });
      await this.router.navigateByUrl('/login');
    },
  }));

  protected sessionError(): string {
    return describeError(this.session.error(), SESSION_FALLBACK);
  }

  protected logoutError(): string {
    return describeError(this.logout.error(), 'Sign-out failed.');
  }

  protected signOut(): void {
    this.logout.mutate();
  }
}
