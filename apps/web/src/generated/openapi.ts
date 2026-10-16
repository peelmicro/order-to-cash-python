// GENERATED FILE — do not edit by hand.
// Source: specs/shared/openapi.yaml, via `pnpm run types:generate` (scripts/openapi-types.mjs).
// `pnpm run types:check` fails ./quality.sh when this file is stale against the spec.
// Only src/shared/api-types.ts may import it (guarded by src/shared/generated-types.spec.ts).

export interface paths {
    "/auth/login": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Issue a bearer token.
         * @description Exchanges operator credentials for a bearer token. A single operator
         *     identity is assumed — the model is deliberately not multi-tenant
         *     (`domain-model.md` §9).
         */
        post: operations["login"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/auth/me": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Describe the authenticated operator. */
        get: operations["getCurrentUser"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/orders": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List orders from the read model.
         * @description Served **exclusively** from the projected read model (R54) — never by
         *     reading a write model and never by joining across bounded contexts.
         *     Ordering is by `orderDate` descending.
         */
        get: operations["listOrders"];
        put?: never;
        /**
         * Place an order.
         * @description Translates to the `orders.create` command. The Orders context validates
         *     the lines, performs a **non-locking** availability check, computes the
         *     totals inside the aggregate, and persists the order together with its
         *     `order.placed.v1` outbox record in **one transaction** (R13). The saga
         *     then advances on facts.
         *
         *     **201 means the order was accepted, not that it will complete.** The
         *     response carries the order id — which is also the `correlationId` of
         *     every fact this order will produce — and the caller subscribes to
         *     `GET /orders/stream?orderId=…` to watch the saga.
         *
         *     **409** is returned when the availability check fails at acceptance;
         *     the body names the short lines. Stock that disappears *after* a
         *     successful check is not an error but the designed race: the order is
         *     placed, `stock.rejected.v1` follows, and the saga cancels it (R26).
         *
         *     Idempotency: supply `Idempotency-Key`. A repeat with the same key
         *     returns the original order instead of placing a second one.
         */
        post: operations["placeOrder"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/orders/{id}": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description The order identifier — also the `correlationId` of every fact in this order's saga. */
                id: components["parameters"]["OrderId"];
            };
            cookie?: never;
        };
        /**
         * Fetch one order with its full timeline.
         * @description Returns the read-model document: header, totals, lines, the references
         *     picked up along the way, and the **complete event timeline** ordered by
         *     `occurredAt` (R50) — which is where a reviewer sees both compensation
         *     steps of a cancelled order, separately and in causal order (R28).
         *
         *     **202 Accepted** is returned while the projection has not yet produced a
         *     document for an order id the caller has just been given. That is an
         *     explicit *projection pending* answer, not a `404` (R55). A genuine
         *     `404` means the identifier is unknown to the system.
         */
        get: operations["getOrder"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/orders/{id}/cancel": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description The order identifier — also the `correlationId` of every fact in this order's saga. */
                id: components["parameters"]["OrderId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Operator cancellation, pre-despatched only.
         * @description Translates to the `orders.cancel` command. Legal only while the order is
         *     `placed`, `stock_reserved`, `credit_approved` or `confirmed` (R8); from
         *     `despatched` onwards the answer is `409` — goods have left, and
         *     unwinding is a commercial matter that is out of scope.
         *
         *     **202, not 200.** Cancellation may require compensation — releasing what
         *     the order had acquired (`saga.md` §4.3) — and those steps complete when
         *     their **facts** arrive, not when this call returns. The response names the
         *     compensation that was planned so a client can show it; the timeline is
         *     the record of it actually happening.
         *
         *     **A `credit_approved` or `confirmed` order may still despatch.** Its
         *     despatch was requested when it was confirmed, so the cancellation
         *     releases the stock reservation first and Fulfillment decides between the
         *     two. If the despatch consumed the stock first, the cancellation is
         *     overtaken: nothing is released, no `order.cancelled.v1` follows, and the
         *     timeline shows the despatch (`saga.md` §4.3).
         */
        post: operations["cancelOrder"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/orders/stream": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Live saga progress as server-sent events.
         * @description A **server-sent event stream** (`text/event-stream`), fed by the
         *     projector's read-model update signal (R55). One-directional by design:
         *     the client never sends anything back on it, which is why an SSE stream
         *     rather than a bidirectional socket.
         *
         *     ### Frame format
         *
         *     Each frame is a standard SSE block:
         *
         *     ```
         *     id: 1755511234567-17
         *     event: order.updated
         *     data: {"orderId":"…","status":"confirmed", …}
         *
         *     ```
         *
         *     - `event` names the event type. The types emitted are listed below.
         *     - `data` is a single-line JSON document whose schema depends on `event`.
         *     - `id` is an opaque, monotonically increasing cursor **on `order.updated`
         *       and `timeline.appended` only** — the two event types the replay buffer
         *       stores. **`ping` deliberately carries no `id` line.**
         *
         *       This is not an oversight: a browser's `EventSource` updates its
         *       internal `lastEventId` from *any* dispatched event that carries one,
         *       heartbeat or not. `ping` fires on a fixed interval and real content
         *       fires rarely, so if `ping` carried an id, the client's remembered
         *       resume point would almost always be a heartbeat's — and a heartbeat's
         *       id is never in the replay buffer (there is nothing to replay), so
         *       `Last-Event-ID` would name it and reconnection would answer
         *       `resumed: false` on nearly every disconnect, forcing a re-fetch even
         *       when nothing was actually missed. Omitting `id` from `ping` keeps a
         *       client's remembered cursor pointed at real content, so reconnection
         *       `resumed: false` means what §2 below says it means: the buffer
         *       genuinely could not find that cursor, not "you happened to disconnect
         *       between two heartbeats." `ping` still carries its documented `event`
         *       and `data` (`StreamPing`) — only the `id` line is absent. Found by
         *       hand-testing after feature 26 landed; `stream.ready`'s cursor has the
         *       identical property (minted, never stored) for the same reason, but is
         *       sent only once per connection so the interaction is not observable in
         *       practice the way `ping`'s is.
         *
         *     ### Event types
         *
         *     | `event` | `data` schema | Carries `id`? | Meaning |
         *     |---|---|---|---|
         *     | `order.updated` | `OrderStreamUpdate` | Yes — resumable | A read-model document changed — status, references or totals |
         *     | `timeline.appended` | `TimelineStreamEntry` | Yes — resumable | One fact was appended to an order's timeline |
         *     | `stream.ready` | `StreamReady` | No | Sent once on connect, carrying the cursor the stream resumed from |
         *     | `ping` | `StreamPing` | No | Keep-alive, sent on an idle interval so proxies do not close the connection |
         *
         *     ### Reconnection
         *
         *     On reconnect the client sends the id of the last frame it processed in
         *     the `Last-Event-ID` request header (browsers do this automatically), and
         *     the stream **resumes after that cursor** from a bounded replay buffer.
         *     Two honest limitations, stated rather than hidden:
         *
         *     1. The buffer is bounded. If the client was away longer than the buffer
         *        holds, the stream replies `stream.ready` with `resumed: false` and
         *        the client must re-fetch `GET /orders/{id}` (or `GET /orders`) to
         *        resynchronise. The stream is a *notification* channel; the read model
         *        is the source of truth.
         *     2. Delivery is at-least-once. A frame may repeat after a reconnect, so
         *        clients deduplicate on the `eventId` inside `data` — the same
         *        discipline every fact consumer applies (R51).
         */
        get: operations["streamOrderEvents"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/stock": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * On-hand and reserved units.
         * @description Translates to the `fulfillment.stock.list` query — a live read of the
         *     Fulfillment write model, not the read model: stock is not part of an
         *     order's timeline. `availableUnits` is `units − reservedUnits`, which
         *     invariant F1 guarantees is never negative.
         *
         *     `belowThreshold=true` is the query the demo replenishment workflow runs.
         */
        get: operations["listStock"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/stock/replenish": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Add on-hand units.
         * @description Translates to the `fulfillment.stock.replenish` command. It adds to
         *     `units` only: reservations and `reservedUnits` are untouched, so
         *     invariant F1 cannot be broken by a replenishment, and **no fact is
         *     emitted** — a stock top-up is an operational act outside any order's
         *     saga and belongs in no order timeline.
         *
         *     `units` is a **delta**, not a target level, so repeating this call adds
         *     again. It is deliberately **not** idempotent: "top up by 100" is the
         *     operation the demo needs, and pretending otherwise would silently drop
         *     legitimate repeats. A `503` after a timeout does not mean the top-up was
         *     not applied: re-read `GET /stock` before retrying.
         */
        post: operations["replenishStock"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/invoices": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * List invoices.
         * @description Translates to the `billing.invoice.list` query. Each row links back to
         *     its order by `orderReference` — the inter-context vocabulary — never by
         *     another context's internal id.
         *
         *     `issuedBeforeMinutes` is how the demo payment robot selects invoices to
         *     pay "within terms".
         */
        get: operations["listInvoices"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/invoices/{id}/payments": {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description The invoice identifier. */
                id: components["parameters"]["InvoiceId"];
            };
            cookie?: never;
        };
        get?: never;
        put?: never;
        /**
         * Register a remittance against an invoice.
         * @description Translates to the `billing.payment.register` command. **This is the only
         *     way an invoice becomes `paid`** — there is no internal payment timer;
         *     payment always arrives from the outside world, whether that is the
         *     operator's button, an API test or the demo payment robot.
         *
         *     On acceptance Billing records the payment, moves the invoice
         *     `issued → paid`, appends a `release` ledger entry and emits
         *     `payment.received.v1` **followed by** `credit.released.v1` in that order
         *     and in the same transaction (R47). The saga then moves the order
         *     `invoiced → paid → completed`.
         *
         *     ## Idempotency semantics — by `paymentReference`
         *
         *     `paymentReference` in the request body **is** the idempotency key
         *     (invariant B10, R48). It is a property of the remittance itself — the
         *     bank's reference — not a transport header, which is why it lives in the
         *     body and why it works identically for the operator, a test and a robot.
         *
         *     | Situation | Status | Body |
         *     |---|---|---|
         *     | Unseen `paymentReference`, amount and currency match the invoice total | `201` | `outcome: accepted` |
         *     | **Same** `paymentReference` replayed against the **same** invoice with the **same** amount | `200` | `outcome: duplicate` — the **original** outcome, byte-for-byte; no second payment recorded, **no second fact emitted** |
         *     | Same `paymentReference` reused for a **different** invoice or a different amount | `409` | `PAYMENT_REFERENCE_REUSED` — the key is being used to mean two different things |
         *     | Invoice already `paid`, remittance arrives under a **different** `paymentReference` | `409` | `INVOICE_ALREADY_PAID` — nothing changes (R49) |
         *     | Amount or currency differs from the invoice total | `422` | `PAYMENT_MISMATCH` — partial and over-payment are out of scope; nothing changes (R49) |
         *
         *     A `200` and a `201` therefore differ only in whether *this* call was the
         *     one that changed the world. Clients must treat both as success — a
         *     retrying robot that saw a dropped connection will legitimately get
         *     `200` for a payment it made itself.
         */
        post: operations["registerPayment"];
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/credits": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Credit limits and current exposure per retailer.
         * @description Translates to the `billing.credit.list` query. Shows the limit, the sum
         *     of active holds, the open invoice exposure and what is left —
         *     `availableCredit = creditLimit − activeHolds − openExposure`, which
         *     invariant B1 keeps non-negative. This is the view that makes a genuine
         *     over-limit rejection legible in a demo, as opposed to the simulator's
         *     `.99` affordance.
         */
        get: operations["listCredits"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/catalog/products": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Catalogue products for the place-order form. */
        get: operations["listProducts"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/catalog/retailers": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Retailers (buyers) for the place-order form. */
        get: operations["listRetailers"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/catalog/companies": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /** Companies (suppliers) for the place-order form. */
        get: operations["listCompanies"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/live": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Liveness probe.
         * @description Answers whether the process is running and able to serve. It is
         *     **deliberately independent of dependencies** (R60): a gateway whose
         *     broker is unreachable is *not ready*, but it is alive, and restarting it
         *     would fix nothing.
         */
        get: operations["healthLive"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/health/ready": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Readiness probe.
         * @description Answers whether this service can currently do its job — its write model,
         *     the fact stream and the RPC transport are reachable. When any of them is
         *     not, readiness reports `503` and the instance is withdrawn from traffic
         *     **without being restarted** (R60).
         */
        get: operations["healthReady"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
    "/docs": {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        /**
         * Interactive API documentation.
         * @description Human-facing rendering of this document. Unauthenticated so a reviewer
         *     can read the contract before obtaining a token.
         */
        get: operations["apiDocs"];
        put?: never;
        post?: never;
        delete?: never;
        options?: never;
        head?: never;
        patch?: never;
        trace?: never;
    };
}
export type webhooks = Record<string, never>;
export interface components {
    schemas: {
        /**
         * Format: uuid
         * @description An opaque, globally unique identifier generated inside the domain, never by a store.
         * @example 9f1e2d3c-4b5a-4c6d-8e7f-0a1b2c3d4e5f
         */
        UniqueId: string;
        /**
         * Format: date-time
         * @description A UTC instant, ISO-8601.
         * @example 2026-08-18T10:15:00.000Z
         */
        Instant: string;
        /**
         * @description ISO 4217 alpha-3 code.
         * @example EUR
         */
        CurrencyCode: string;
        /**
         * Format: int64
         * @description An amount as a whole count of the currency's smallest denomination.
         *     **Never** a decimal, float or major-unit value (R1) — `€1,242.50` is
         *     `124250`. Used where the enclosing object already declares its
         *     `currency`; where an amount travels alone, use `Money`.
         * @example 124250
         */
        MinorUnits: number;
        /**
         * @description An amount that travels alone — integer minor units plus its currency.
         * @example {
         *       "amount": 124250,
         *       "currency": "EUR"
         *     }
         */
        Money: {
            amount: components["schemas"]["MinorUnits"];
            currency: components["schemas"]["CurrencyCode"];
        };
        /**
         * @description Global Location Number — 13 digits whose last is the GS1 mod-10 check digit (R4).
         * @example 8412345000013
         */
        Gln: string;
        /** @description A strictly positive whole count of units (R3). */
        Quantity: number;
        /** @description A non-negative whole count of units. */
        UnitCount: number;
        /** @example CarrefourEs */
        PartyCode: string;
        /** @example PRD-0001 */
        ProductCode: string;
        /** @example ORD-000042 */
        OrderReference: string;
        /** @example DES-000031 */
        DespatchReference: string;
        /** @example INV-000027 */
        InvoiceReference: string;
        CreditCode: string;
        /**
         * @description The remittance's own reference — **the idempotency key** of `POST /invoices/{id}/payments` (R48).
         * @example PAY-2026-08-18-000019
         */
        PaymentReference: string;
        /**
         * @description The order state machine, which is also the saga state. `completed` and `cancelled` are terminal.
         * @enum {string}
         */
        OrderStatus: "placed" | "stock_reserved" | "credit_approved" | "confirmed" | "despatched" | "invoiced" | "paid" | "completed" | "cancelled";
        /** @enum {string} */
        CancellationReason: "stock_rejected" | "credit_rejected" | "operator_cancelled";
        /** @enum {string} */
        InvoiceStatus: "issued" | "paid";
        /**
         * @description Provenance of the remittance — an operator click, an external payment robot, or a test.
         * @enum {string}
         */
        PaymentSource: "operator" | "robot" | "test";
        Party: {
            code: components["schemas"]["PartyCode"];
            name: string;
            country: string;
            vat?: string;
            gln: components["schemas"]["Gln"];
            currency: components["schemas"]["CurrencyCode"];
            enabled: boolean;
        };
        Product: {
            code: components["schemas"]["ProductCode"];
            ean?: string;
            name: string;
            description?: string;
            price: components["schemas"]["MinorUnits"];
            currency: components["schemas"]["CurrencyCode"];
            enabled: boolean;
        };
        PageInfo: {
            page: number;
            pageSize: number;
            total: number;
        };
        LoginRequest: {
            username: string;
            /** Format: password */
            password: string;
        };
        LoginResponse: {
            accessToken: string;
            /** @constant */
            tokenType: "Bearer";
            /** @description Lifetime of the token in seconds. */
            expiresIn: number;
        };
        CurrentUser: {
            username: string;
            displayName?: string;
            roles: string[];
        };
        PlaceOrderRequest: {
            retailerCode: components["schemas"]["PartyCode"];
            companyCode: components["schemas"]["PartyCode"];
            /** @description Every line price and discount is expressed in this currency. Mixing currencies inside one order is a domain error (invariant O2, R2). */
            currency: components["schemas"]["CurrencyCode"];
            /** @description At least one line — an order with none cannot exist (invariant O1, R5). */
            lines: components["schemas"]["PlaceOrderLine"][];
            orderDiscount?: components["schemas"]["MinorUnits"];
            notes?: string;
        };
        PlaceOrderLine: {
            productCode: components["schemas"]["ProductCode"];
            quantity: components["schemas"]["Quantity"];
            /**
             * @description Optional. Omitted, the catalogue price is snapshotted onto the line
             *     at order time. Supplied, it is used as given — which is how a demo
             *     engineers a total ending in `99` to trigger the compensation path
             *     (R42).
             */
            unitPrice?: components["schemas"]["MinorUnits"];
            lineDiscount?: components["schemas"]["MinorUnits"];
        };
        PlaceOrderResponse: {
            /** @description Also the `correlationId` of every fact this order will produce, and the key to subscribe with on the event stream. */
            orderId: components["schemas"]["UniqueId"];
            orderReference: components["schemas"]["OrderReference"];
            /** @constant */
            status: "placed";
            currency: components["schemas"]["CurrencyCode"];
            initialAmount?: components["schemas"]["MinorUnits"];
            initialDiscount?: components["schemas"]["MinorUnits"];
            /** @description `initialAmount − initialDiscount`, computed inside the aggregate and never assigned by a caller (invariant O3, R6). */
            totalAmount: components["schemas"]["MinorUnits"];
            orderDate: components["schemas"]["Instant"];
            /** @description Always true at creation — the read model has not seen this order yet (R55). */
            projectionPending?: boolean;
        };
        CancelOrderRequest: {
            /** @description Free-text operator note recorded on the timeline entry. */
            note?: string;
        };
        CancelOrderResponse: {
            orderId: components["schemas"]["UniqueId"];
            orderReference: components["schemas"]["OrderReference"];
            /**
             * @description The status **at the moment the command was accepted**. It is not
             *     necessarily `cancelled` yet: when compensation is required the
             *     order stays in its current status until the compensating facts
             *     arrive (R27, R28).
             */
            status: components["schemas"]["OrderStatus"];
            /** @constant */
            cancellationReason?: "operator_cancelled";
            /** @description The acquisitions that will be unwound, in the order they are released (`saga.md` §4.3) — `stock_release` then `credit_release` from `credit_approved` or `confirmed`. Empty when nothing had been acquired. */
            compensationPlanned: ("credit_release" | "stock_release")[];
        };
        /** @description One row of the order list, projected from the read model. */
        OrderSummary: {
            orderId: components["schemas"]["UniqueId"];
            orderReference: components["schemas"]["OrderReference"];
            orderDate: components["schemas"]["Instant"];
            retailer: components["schemas"]["PartyRef"];
            company: components["schemas"]["PartyRef"];
            status: components["schemas"]["OrderStatus"];
            cancellationReason?: components["schemas"]["CancellationReason"] | null;
            currency: components["schemas"]["CurrencyCode"];
            totals: components["schemas"]["OrderTotals"];
            updatedAt: components["schemas"]["Instant"];
        };
        OrderSummaryPage: {
            items: components["schemas"]["OrderSummary"][];
            page: components["schemas"]["PageInfo"];
        };
        PartyRef: {
            code: components["schemas"]["PartyCode"];
            name?: string;
            gln: components["schemas"]["Gln"];
        };
        /** @description All three values are minor units in the order's `currency`, derived by the aggregate. */
        OrderTotals: {
            initialAmount: components["schemas"]["MinorUnits"];
            initialDiscount: components["schemas"]["MinorUnits"];
            totalAmount: components["schemas"]["MinorUnits"];
        };
        OrderItem: {
            productCode: components["schemas"]["ProductCode"];
            name?: string;
            quantity: components["schemas"]["Quantity"];
            /** @description Snapshotted at order time — a later catalogue price change never rewrites an order. */
            unitPrice: components["schemas"]["MinorUnits"];
            lineDiscount: components["schemas"]["MinorUnits"];
        };
        /** @description Business references picked up as the saga progressed. Null until the corresponding fact has been projected. */
        OrderReferences: {
            despatchReference?: components["schemas"]["DespatchReference"] | null;
            invoiceReference?: components["schemas"]["InvoiceReference"] | null;
            paymentReference?: components["schemas"]["PaymentReference"] | null;
        };
        /**
         * @description One projected fact. The timeline is ordered by `occurredAt` ascending, never by
         *     arrival order (R50). Two entries sharing one identical `occurredAt` (a tie group)
         *     are then ordered so that a fact always follows the fact that caused it: within the
         *     tie group, entry `p` is the cause of entry `c` exactly when `c.causationId` equals
         *     `p.eventId`; where no such recorded edge exists between two tied entries (including
         *     every document projected before this ordering existed), they fall back to `eventId`
         *     ascending — a deterministic but causally arbitrary order (amendment A1).
         */
        TimelineEntry: {
            /** @description The idempotency key — an entry with this id is never appended twice (R51). */
            eventId: components["schemas"]["UniqueId"];
            /** @description The `eventId` of the fact — or the identifier of the command — that caused this one (R12). Only a fact's `eventId` can name another entry of the timeline: a fact produced by an RPC responder names the command that requested it, which is never an entry. Ties on `occurredAt` are ordered so that a fact follows a cause it names. Absent on an entry projected before this field existed. */
            causationId?: components["schemas"]["UniqueId"];
            /** @example stock.released.v1 */
            eventType: string;
            occurredAt: components["schemas"]["Instant"];
            /** @description Human-readable one-liner, e.g. "5 units released back to stock". */
            summary: string;
            /** @description Optional structured extract of the fact payload for the UI — shortages, amounts, references. */
            detail?: Record<string, never>;
        };
        /**
         * @description The read-model document for one order: the answer to "what happened to
         *     order X and when". It is written **only** by the projector (R54).
         */
        OrderDetail: {
            orderId: components["schemas"]["UniqueId"];
            orderReference?: components["schemas"]["OrderReference"];
            orderDate?: components["schemas"]["Instant"];
            retailer?: components["schemas"]["PartyRef"];
            company?: components["schemas"]["PartyRef"];
            status: components["schemas"]["OrderStatus"];
            cancellationReason?: components["schemas"]["CancellationReason"] | null;
            currency?: components["schemas"]["CurrencyCode"];
            totals?: components["schemas"]["OrderTotals"];
            items?: components["schemas"]["OrderItem"][];
            references?: components["schemas"]["OrderReferences"];
            /**
             * @description Every fact projected for this order, in `occurredAt` order. A
             *     cancelled order shows its compensation steps here separately and in
             *     causal order — `credit.rejected.v1`, then `stock.released.v1`, then
             *     `order.cancelled.v1` (R28).
             */
            events: components["schemas"]["TimelineEntry"][];
            /**
             * @description False while the document is a placeholder created by a fact that
             *     outran `order.placed.v1` (R53) — the timeline is real, the header
             *     fields are not filled in yet.
             */
            headerComplete?: boolean;
            updatedAt: components["schemas"]["Instant"];
        };
        /** @description Returned by `GET /orders/{id}` with `202` while no read-model document exists yet (R55). */
        ProjectionPending: {
            orderId: components["schemas"]["UniqueId"];
            /** @constant */
            status: "projection_pending";
            /** @example The order was accepted and is not projected yet. Subscribe to /orders/stream or retry. */
            message?: string;
            retryAfterMs?: number;
        };
        /** @description `data` of an `order.updated` frame — a read-model document changed. */
        OrderStreamUpdate: {
            /** @description The fact that caused the update. Clients deduplicate on it, because stream delivery is at-least-once. */
            eventId: components["schemas"]["UniqueId"];
            orderId: components["schemas"]["UniqueId"];
            orderReference?: components["schemas"]["OrderReference"];
            status: components["schemas"]["OrderStatus"];
            cancellationReason?: components["schemas"]["CancellationReason"] | null;
            references?: components["schemas"]["OrderReferences"];
            totals?: components["schemas"]["OrderTotals"];
            occurredAt: components["schemas"]["Instant"];
        };
        /** @description `data` of a `timeline.appended` frame — one fact was appended to an order timeline. */
        TimelineStreamEntry: {
            eventId: components["schemas"]["UniqueId"];
            /** @description Same field as `TimelineEntry.causationId`, carried onto the stream frame. */
            causationId?: components["schemas"]["UniqueId"];
            orderId: components["schemas"]["UniqueId"];
            orderReference?: components["schemas"]["OrderReference"];
            eventType: string;
            occurredAt: components["schemas"]["Instant"];
            summary: string;
        };
        /** @description `data` of the `stream.ready` frame sent once on connect. */
        StreamReady: {
            /** @description The cursor the stream is resuming from. */
            cursor: string;
            /**
             * @description True when a `Last-Event-ID` was honoured from the replay buffer.
             *     **False** when it was too old — the client must re-fetch the
             *     affected orders to resynchronise; the stream is a notification
             *     channel, the read model is the source of truth.
             */
            resumed: boolean;
            /** @description Present when the subscription is restricted to one order. */
            orderId?: components["schemas"]["UniqueId"] | null;
        };
        /** @description `data` of a `ping` keep-alive frame. */
        StreamPing: {
            at: components["schemas"]["Instant"];
        };
        StockItem: {
            companyCode: components["schemas"]["PartyCode"];
            productCode: components["schemas"]["ProductCode"];
            productName?: string;
            units: components["schemas"]["UnitCount"];
            reservedUnits: components["schemas"]["UnitCount"];
            /** @description `units − reservedUnits`. Derived, never stored; invariant F1 keeps it non-negative. */
            availableUnits: components["schemas"]["UnitCount"];
            lowStockThreshold: components["schemas"]["UnitCount"];
        };
        StockPage: {
            items: components["schemas"]["StockItem"][];
            page: components["schemas"]["PageInfo"];
        };
        ReplenishStockRequest: {
            companyCode: components["schemas"]["PartyCode"];
            lines: {
                productCode: components["schemas"]["ProductCode"];
                /** @description Units to **add** to on-hand stock — a delta, not a target level. */
                units: components["schemas"]["Quantity"];
            }[];
        };
        ReplenishStockResponse: {
            items: components["schemas"]["StockItem"][];
        };
        Invoice: {
            invoiceId: components["schemas"]["UniqueId"];
            invoiceReference: components["schemas"]["InvoiceReference"];
            invoiceDate: components["schemas"]["Instant"];
            /** @description The link back to the order — a business reference, never another context's internal id. */
            orderReference: components["schemas"]["OrderReference"];
            retailerCode: components["schemas"]["PartyCode"];
            companyCode: components["schemas"]["PartyCode"];
            currency: components["schemas"]["CurrencyCode"];
            amount: components["schemas"]["MinorUnits"];
            discount: components["schemas"]["MinorUnits"];
            totalAmount: components["schemas"]["MinorUnits"];
            status: components["schemas"]["InvoiceStatus"];
            /** @description Set exactly when the status becomes `paid`, null while `issued` (invariant B9). */
            paidAt?: components["schemas"]["Instant"] | null;
            lines?: {
                productCode: components["schemas"]["ProductCode"];
                units: components["schemas"]["Quantity"];
                unitPrice: components["schemas"]["MinorUnits"];
            }[];
        };
        InvoicePage: {
            items: components["schemas"]["Invoice"][];
            page: components["schemas"]["PageInfo"];
        };
        RegisterPaymentRequest: {
            /** @description **The idempotency key** (R48). It is the remittance's own reference, so a replay is recognisable no matter who sends it. */
            paymentReference: components["schemas"]["PaymentReference"];
            /** @description Must equal the invoice `totalAmount` and currency exactly — partial and over-payment are out of scope (invariant B10, R49). */
            amount: components["schemas"]["Money"];
            valueDate: components["schemas"]["Instant"];
            source: components["schemas"]["PaymentSource"];
        };
        RegisterPaymentResponse: {
            /**
             * @description `duplicate` accompanies `200` — the original outcome replayed; no second payment, no second fact.
             * @enum {string}
             */
            outcome: "accepted" | "duplicate";
            paymentReference: components["schemas"]["PaymentReference"];
            invoiceReference: components["schemas"]["InvoiceReference"];
            orderReference?: components["schemas"]["OrderReference"];
            invoiceStatus: components["schemas"]["InvoiceStatus"];
            paidAt?: components["schemas"]["Instant"];
        };
        Credit: {
            creditCode: components["schemas"]["CreditCode"];
            retailerCode: components["schemas"]["PartyCode"];
            companyCode: components["schemas"]["PartyCode"];
            currency: components["schemas"]["CurrencyCode"];
            creditLimit: components["schemas"]["MinorUnits"];
            activeHolds: components["schemas"]["MinorUnits"];
            /** @description Invoices issued and not yet paid. A hold becomes exposure at invoice issue, which leaves `availableCredit` numerically unchanged (R40). */
            openExposure: components["schemas"]["MinorUnits"];
            /** @description `creditLimit − activeHolds − openExposure`, never negative (invariant B1). */
            availableCredit: components["schemas"]["MinorUnits"];
        };
        CreditPage: {
            items: components["schemas"]["Credit"][];
            page: components["schemas"]["PageInfo"];
        };
        HealthResponse: {
            /** @enum {string} */
            status: "up" | "down";
            /** @description Per-dependency result — write model, fact stream, RPC transport, read model. Present on the readiness probe. */
            checks?: {
                [key: string]: {
                    /** @enum {string} */
                    status: "up" | "down";
                    detail?: string;
                };
            };
        };
        /**
         * @description RFC 9457 problem document. `code` is stable and machine-readable and is
         *     what tests assert on; `title` and `detail` are for humans and must never
         *     be parsed.
         */
        Problem: {
            /**
             * Format: uri
             * @default about:blank
             */
            type: string;
            title: string;
            status: number;
            detail?: string;
            instance?: string;
            /**
             * @description Stable machine-readable error code.
             * @example ORDER_NOT_CANCELLABLE
             * @example INVOICE_ALREADY_PAID
             * @example PAYMENT_MISMATCH
             * @example PAYMENT_REFERENCE_REUSED
             * @example STOCK_UNAVAILABLE
             * @example VALIDATION_FAILED
             * @example DOMAIN_ERROR
             * @example UPSTREAM_TIMEOUT
             */
            code: string;
            /** @description The id this failure was logged under (R58). */
            correlationId?: components["schemas"]["UniqueId"];
            occurredAt?: components["schemas"]["Instant"];
        };
        ValidationProblem: components["schemas"]["Problem"] & {
            errors?: {
                field: string;
                message: string;
            }[];
        };
        StockUnavailableProblem: components["schemas"]["Problem"] & {
            shortages?: {
                productCode: components["schemas"]["ProductCode"];
                requested: components["schemas"]["Quantity"];
                available: components["schemas"]["UnitCount"];
            }[];
        };
    };
    responses: {
        /** @description The request was malformed or failed schema validation. */
        BadRequest: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["ValidationProblem"];
            };
        };
        /** @description Missing, expired or invalid bearer token. */
        Unauthorized: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /** @description No such resource. */
        NotFound: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /**
         * @description A domain rule refused the request — an invariant of `domain-model.md`.
         *     Nothing changed and no fact was emitted.
         */
        DomainError: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /**
         * @description The client exceeded the rate limit of the endpoint it called. The
         *     request was **not** applied and no fact was emitted; the client may
         *     retry once the interval named by `Retry-After` has elapsed.
         */
        TooManyRequests: {
            headers: {
                /**
                 * @description How long the client must wait before retrying, as a whole number of
                 *     **seconds**. Delta-seconds only: the HTTP-date form RFC 9110 also
                 *     permits is deliberately **not** used by this API, so a client may
                 *     parse this header as an integer without branching on its form. The
                 *     value is the remaining lifetime of the limiter's current window;
                 *     the window length itself is per-assessment configuration and is
                 *     deliberately not fixed by this contract.
                 */
                "Retry-After": number;
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /**
         * @description The owning context could not be reached, did not answer within the
         *     deadline, or answered with a reply the Gateway could not read. When no
         *     responder was reachable the command was not applied; after a timeout
         *     or an unreadable reply it may have been. A client may retry an
         *     idempotent operation (one with an `Idempotency-Key` or a natural key
         *     such as `paymentReference`); before retrying any other it should
         *     re-read the resource.
         */
        UpstreamUnavailable: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
        /**
         * @description Any status this operation does not list. The body is always a
         *     `Problem`. A 4xx is a request the Gateway or the owning context refused
         *     (an unknown reference, a malformed parameter, a domain rule); a 5xx is
         *     a failure in the Gateway or upstream. The listed statuses are the ones
         *     a client is expected to handle by name; this one exists so that no
         *     status the system can answer is outside the contract.
         */
        UnlistedProblem: {
            headers: {
                [name: string]: unknown;
            };
            content: {
                "application/problem+json": components["schemas"]["Problem"];
            };
        };
    };
    parameters: {
        /** @description The order identifier — also the `correlationId` of every fact in this order's saga. */
        OrderId: components["schemas"]["UniqueId"];
        /** @description The invoice identifier. */
        InvoiceId: components["schemas"]["UniqueId"];
        Page: number;
        PageSize: number;
        /** @description Include soft-disabled reference records. */
        IncludeDisabled: boolean;
        /**
         * @description Client-supplied key. A repeat with the same key returns the original
         *     result instead of performing the operation twice.
         */
        IdempotencyKey: components["schemas"]["UniqueId"];
    };
    requestBodies: never;
    headers: {
        /** @description The correlation id under which this request was handled, and — for order commands — the order id itself. It appears on every log line produced while handling the request (R58). */
        XCorrelationId: components["schemas"]["UniqueId"];
    };
    pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
    login: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["LoginRequest"];
            };
        };
        responses: {
            /** @description Authenticated. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["LoginResponse"];
                };
            };
            400: components["responses"]["BadRequest"];
            /** @description Bad credentials. */
            401: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            429: components["responses"]["TooManyRequests"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    getCurrentUser: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The current operator. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CurrentUser"];
                };
            };
            401: components["responses"]["Unauthorized"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    listOrders: {
        parameters: {
            query?: {
                /** @description Filter by order status. Repeat the parameter to accept several. */
                status?: components["schemas"]["OrderStatus"][];
                retailerCode?: components["schemas"]["PartyCode"];
                companyCode?: components["schemas"]["PartyCode"];
                orderReference?: components["schemas"]["OrderReference"];
                page?: components["parameters"]["Page"];
                pageSize?: components["parameters"]["PageSize"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description A page of order summaries. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrderSummaryPage"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    placeOrder: {
        parameters: {
            query?: never;
            header?: {
                /**
                 * @description Client-supplied key. A repeat with the same key returns the original
                 *     result instead of performing the operation twice.
                 */
                "Idempotency-Key"?: components["parameters"]["IdempotencyKey"];
            };
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["PlaceOrderRequest"];
            };
        };
        responses: {
            /**
             * @description Order accepted and persisted in status `placed`. It is **not yet
             *     queryable** — see `GET /orders/{id}` (R55).
             */
            201: {
                headers: {
                    /** @description Canonical URL of the new order. */
                    Location?: string;
                    "X-Correlation-Id": components["headers"]["XCorrelationId"];
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["PlaceOrderResponse"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            /** @description The availability check failed at acceptance; no order was created. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["StockUnavailableProblem"];
                };
            };
            422: components["responses"]["DomainError"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    getOrder: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description The order identifier — also the `correlationId` of every fact in this order's saga. */
                id: components["parameters"]["OrderId"];
            };
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The projected order document. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["OrderDetail"];
                };
            };
            /**
             * @description The order exists but has not been projected yet. Retry, or subscribe
             *     to the event stream and let it fill in.
             */
            202: {
                headers: {
                    /** @description Suggested seconds to wait before retrying. */
                    "Retry-After"?: number;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ProjectionPending"];
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    cancelOrder: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description The order identifier — also the `correlationId` of every fact in this order's saga. */
                id: components["parameters"]["OrderId"];
            };
            cookie?: never;
        };
        requestBody?: {
            content: {
                "application/json": components["schemas"]["CancelOrderRequest"];
            };
        };
        responses: {
            /** @description Cancellation accepted; compensation, if any, is under way. From `credit_approved` or `confirmed` it can still be overtaken by the despatch already requested. */
            202: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CancelOrderResponse"];
                };
            };
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            /** @description The order is `despatched` or later, or is already terminal. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    streamOrderEvents: {
        parameters: {
            query?: {
                /** @description Restrict the stream to one order. Omit to receive updates for every order. */
                orderId?: components["schemas"]["UniqueId"];
            };
            header?: {
                /** @description Cursor of the last frame the client processed. Sent automatically by browser EventSource implementations on reconnect. */
                "Last-Event-ID"?: string;
            };
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /**
             * @description The event stream. It stays open until the client disconnects; there
             *     is no terminal frame.
             */
            200: {
                headers: {
                    "Cache-Control"?: "no-cache";
                    Connection?: "keep-alive";
                    [name: string]: unknown;
                };
                content: {
                    "text/event-stream": string;
                };
            };
            401: components["responses"]["Unauthorized"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    listStock: {
        parameters: {
            query?: {
                companyCode?: components["schemas"]["PartyCode"];
                productCode?: components["schemas"]["ProductCode"];
                /** @description Return only items whose available units are below `lowStockThreshold`. */
                belowThreshold?: boolean;
                page?: components["parameters"]["Page"];
                pageSize?: components["parameters"]["PageSize"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description A page of stock items. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["StockPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    replenishStock: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["ReplenishStockRequest"];
            };
        };
        responses: {
            /** @description The affected stock items after replenishment. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["ReplenishStockResponse"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    listInvoices: {
        parameters: {
            query?: {
                status?: components["schemas"]["InvoiceStatus"];
                retailerCode?: components["schemas"]["PartyCode"];
                companyCode?: components["schemas"]["PartyCode"];
                orderReference?: components["schemas"]["OrderReference"];
                /** @description Return only invoices issued at least this many minutes ago. */
                issuedBeforeMinutes?: number;
                page?: components["parameters"]["Page"];
                pageSize?: components["parameters"]["PageSize"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description A page of invoices. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["InvoicePage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    registerPayment: {
        parameters: {
            query?: never;
            header?: never;
            path: {
                /** @description The invoice identifier. */
                id: components["parameters"]["InvoiceId"];
            };
            cookie?: never;
        };
        requestBody: {
            content: {
                "application/json": components["schemas"]["RegisterPaymentRequest"];
            };
        };
        responses: {
            /**
             * @description Idempotent replay of an already-recorded `paymentReference`. The
             *     body is the original outcome; nothing changed and no fact was
             *     emitted.
             */
            200: {
                headers: {
                    /** @description Present and `true` on a replayed remittance. */
                    "Idempotent-Replay"?: boolean;
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RegisterPaymentResponse"];
                };
            };
            /** @description Remittance accepted; the invoice is now `paid`. */
            201: {
                headers: {
                    "X-Correlation-Id": components["headers"]["XCorrelationId"];
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["RegisterPaymentResponse"];
                };
            };
            400: components["responses"]["BadRequest"];
            401: components["responses"]["Unauthorized"];
            404: components["responses"]["NotFound"];
            /** @description The invoice is already paid under a different reference, or the reference is being reused for a different remittance. */
            409: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            /** @description The remittance amount or currency does not equal the invoice total. */
            422: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/problem+json": components["schemas"]["Problem"];
                };
            };
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    listCredits: {
        parameters: {
            query?: {
                retailerCode?: components["schemas"]["PartyCode"];
                companyCode?: components["schemas"]["PartyCode"];
                page?: components["parameters"]["Page"];
                pageSize?: components["parameters"]["PageSize"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description A page of credit lines. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["CreditPage"];
                };
            };
            401: components["responses"]["Unauthorized"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    listProducts: {
        parameters: {
            query?: {
                /** @description Include soft-disabled reference records. */
                includeDisabled?: components["parameters"]["IncludeDisabled"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The product catalogue. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Product"][];
                    };
                };
            };
            401: components["responses"]["Unauthorized"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    listRetailers: {
        parameters: {
            query?: {
                /** @description Include soft-disabled reference records. */
                includeDisabled?: components["parameters"]["IncludeDisabled"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The retailer list. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Party"][];
                    };
                };
            };
            401: components["responses"]["Unauthorized"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    listCompanies: {
        parameters: {
            query?: {
                /** @description Include soft-disabled reference records. */
                includeDisabled?: components["parameters"]["IncludeDisabled"];
            };
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The company list. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": {
                        items: components["schemas"]["Party"][];
                    };
                };
            };
            401: components["responses"]["Unauthorized"];
            503: components["responses"]["UpstreamUnavailable"];
            default: components["responses"]["UnlistedProblem"];
        };
    };
    healthLive: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The process is alive. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            default: components["responses"]["UnlistedProblem"];
        };
    };
    healthReady: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description Ready to serve. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            /** @description Not ready — at least one dependency is unreachable. The body names which. */
            503: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "application/json": components["schemas"]["HealthResponse"];
                };
            };
            default: components["responses"]["UnlistedProblem"];
        };
    };
    apiDocs: {
        parameters: {
            query?: never;
            header?: never;
            path?: never;
            cookie?: never;
        };
        requestBody?: never;
        responses: {
            /** @description The documentation page. */
            200: {
                headers: {
                    [name: string]: unknown;
                };
                content: {
                    "text/html": string;
                };
            };
            default: components["responses"]["UnlistedProblem"];
        };
    };
}
