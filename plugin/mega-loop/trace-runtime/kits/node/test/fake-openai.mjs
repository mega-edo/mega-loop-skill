/**
 * An OpenAI-shaped chat-completions endpoint, so a test can prove the instrumentation without a
 * key or a network call.
 *
 * The SDK is the real one and the wire shape is the real one, which is what matters here: the
 * OpenInference instrumentation reads the request it sent and the response it parsed, so a stand-in
 * server exercises exactly the path a provider would.
 */

import { createServer } from 'node:http'

export async function startFakeOpenAI({ reply = 'Fourteen orders shipped late.' } = {}) {
  const requests = []
  const server = createServer((req, res) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      if (!req.url?.endsWith('/chat/completions')) {
        res.writeHead(404).end()
        return
      }
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'))
      requests.push(body)
      res.writeHead(200, { 'content-type': 'application/json' }).end(
        JSON.stringify({
          id: 'chatcmpl-test',
          object: 'chat.completion',
          created: Math.floor(Date.now() / 1000),
          model: body.model,
          choices: [
            { index: 0, message: { role: 'assistant', content: reply }, finish_reason: 'stop' },
          ],
          usage: { prompt_tokens: 11, completion_tokens: 7, total_tokens: 18 },
        }),
      )
    })
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  const { port } = server.address()
  return {
    baseURL: `http://127.0.0.1:${port}/v1`,
    requests,
    close: () => new Promise((resolve) => server.close(resolve)),
  }
}
