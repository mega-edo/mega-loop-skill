// First line, before Nest or Express load: instrumentations patch modules as they are required.
import './tracing/register'

import { NestFactory } from '@nestjs/core'

import { AppModule } from './app.module'

async function bootstrap(): Promise<void> {
  const app = await NestFactory.create(AppModule, { logger: ['error', 'warn'] })
  await app.listen(Number(process.env.PORT), '127.0.0.1')
}

void bootstrap()
