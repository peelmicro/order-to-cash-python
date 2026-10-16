import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { RouteMeta } from '@analogjs/router';
import { injectMutation, QueryClient } from '@tanstack/angular-query-experimental';
import { HlmAlertImports } from '@spartan-ng/helm/alert';
import { HlmButtonImports } from '@spartan-ng/helm/button';
import { HlmCardImports } from '@spartan-ng/helm/card';
import { HlmInputImports } from '@spartan-ng/helm/input';
import { HlmLabelImports } from '@spartan-ng/helm/label';
import { ApiClient } from '../api/api-client';
import { describeError } from '../lib/problem';
import { STACK_LABEL } from '../lib/stack-label';
import { SESSION_KEY } from '../session/session';

export const routeMeta: RouteMeta = { title: 'Sign in' };

/** Shown only when the failure carries no problem document at all (the request never got an answer); a refusal is shown in its own words. */
const SIGN_IN_FALLBACK = 'Sign-in failed.';

@Component({
  selector: 'app-login',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, ...HlmAlertImports, ...HlmButtonImports, ...HlmCardImports, ...HlmInputImports, ...HlmLabelImports],
  template: `
    <main class="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6">
      <p class="text-muted-foreground text-center text-sm" data-testid="stack-label">{{ stackLabel }}</p>
      <section hlmCard>
        <header hlmCardHeader>
          <h1 hlmCardTitle>Order-To-Cash</h1>
          <p hlmCardDescription>Sign in with the operator account.</p>
        </header>
        <div hlmCardContent>
          <form [formGroup]="form" (ngSubmit)="submit()" class="flex flex-col gap-4">
            <div class="flex flex-col gap-2">
              <label hlmLabel for="username">Username</label>
              <input hlmInput id="username" name="username" autocomplete="username" formControlName="username" />
            </div>
            <div class="flex flex-col gap-2">
              <label hlmLabel for="password">Password</label>
              <input hlmInput id="password" name="password" type="password" autocomplete="current-password" formControlName="password" />
            </div>
            @if (login.isError()) {
              <div hlmAlert variant="destructive" data-testid="login-error">
                <p hlmAlertDescription>{{ errorText() }}</p>
              </div>
            }
            <button hlmBtn type="submit" [disabled]="login.isPending()">Sign in</button>
          </form>
        </div>
      </section>
    </main>
  `,
})
export default class LoginPage {
  protected readonly stackLabel = STACK_LABEL;
  private readonly api = inject(ApiClient);
  private readonly router = inject(Router);
  private readonly queryClient = inject(QueryClient);
  protected readonly form = inject(FormBuilder).nonNullable.group({ username: ['operator', Validators.required], password: ['', Validators.required] });

  protected readonly login = injectMutation(() => ({
    mutationFn: () => this.api.login(this.form.getRawValue()),
    onSuccess: async (session) => {
      this.queryClient.setQueryData(SESSION_KEY, session);
      await this.router.navigateByUrl('/orders');
    },
  }));

  protected errorText(): string {
    return describeError(this.login.error(), SIGN_IN_FALLBACK);
  }

  protected submit(): void {
    if (this.form.valid) this.login.mutate();
  }
}
