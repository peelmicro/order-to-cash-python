import { inject, Injectable } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { RouterStateSnapshot, TitleStrategy } from '@angular/router';
import { APP_TITLE } from './stack-label';

/** The browser-tab title of every page: `<page title> · Order-To-Cash · <stack label>`, or the app title alone. The label comes from src/app/lib/stack-label.ts only. */
@Injectable({ providedIn: 'root' })
export class AppTitleStrategy extends TitleStrategy {
  private readonly title = inject(Title);

  override updateTitle(snapshot: RouterStateSnapshot): void {
    const page = this.buildTitle(snapshot);
    this.title.setTitle(page ? `${page} · ${APP_TITLE}` : APP_TITLE);
  }
}
