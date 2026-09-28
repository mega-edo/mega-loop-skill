import {
  type CallHandler,
  type ExecutionContext,
  Injectable,
  type NestInterceptor,
} from '@nestjs/common'
import { type Observable, tap } from 'rxjs'

import { setRequestInput, setRequestOutput } from './tracing/instrument'

/**
 * Puts the user's question and the answer on the trace's root span. The root is the HTTP server
 * span the instrumentation opened before Nest ran, so a span opened here would be a child.
 */
@Injectable()
export class RequestTraceInterceptor implements NestInterceptor {
  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const body = context.switchToHttp().getRequest<{ body?: { question?: unknown } }>().body
    if (typeof body?.question === 'string') setRequestInput(body.question)
    return next.handle().pipe(
      tap((result) => {
        const answer = (result as { answer?: unknown } | undefined)?.answer
        if (typeof answer === 'string') setRequestOutput(answer)
      }),
    )
  }
}
