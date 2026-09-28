import { Body, Controller, Get, Post, UseInterceptors } from '@nestjs/common'
import { trace } from '@opentelemetry/api'
import OpenAI from 'openai'

import { RequestTraceInterceptor } from './request-trace.interceptor'

const tracer = trace.getTracer('chat')

async function lookupOrders(question: string): Promise<number> {
  return tracer.startActiveSpan('lookup_orders', async (span) => {
    span.setAttribute('openinference.span.kind', 'TOOL')
    span.setAttribute('input.value', JSON.stringify({ question }))
    span.setAttribute('output.value', JSON.stringify({ late: 14 }))
    span.end()
    return 14
  })
}

@Controller()
export class ChatController {
  @Get('health')
  health(): string {
    return 'ok'
  }

  @Post('chat')
  @UseInterceptors(RequestTraceInterceptor)
  async chat(@Body() body: { question: string }): Promise<{ answer: string }> {
    return { answer: `${await lookupOrders(body.question)} orders shipped late.` }
  }

  /**
   * A real model call, with no tracing code in the handler at all. The kit installs
   * OpenInference's instrumentation for the SDKs the app has, so the LLM span and its messages
   * are whatever that instrumentation writes — which is what MEGA Loop reads.
   */
  @Post('chat-llm')
  @UseInterceptors(RequestTraceInterceptor)
  async chatLlm(@Body() body: { question: string }): Promise<{ answer: string }> {
    const client = new OpenAI({ apiKey: 'test', baseURL: process.env.FAKE_OPENAI_URL })
    const completion = await client.chat.completions.create({
      model: 'gpt-4o-mini',
      messages: [{ role: 'user', content: body.question }],
    })
    return { answer: completion.choices[0]?.message?.content ?? '' }
  }

  /** The same handler without the interceptor — what a Nest app gets from the kit alone. */
  @Post('chat-naive')
  async chatNaive(@Body() body: { question: string }): Promise<{ answer: string }> {
    return { answer: `${await lookupOrders(body.question)} orders shipped late.` }
  }
}
