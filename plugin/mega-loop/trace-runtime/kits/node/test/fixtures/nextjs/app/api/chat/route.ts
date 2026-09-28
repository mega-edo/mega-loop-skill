import { setRequestInput, setRequestOutput } from '../../../tracing/instrument'

export async function POST(request: Request): Promise<Response> {
  const { question } = (await request.json()) as { question: string }
  // Next opened the root span before this handler ran; this reaches it, not a child.
  setRequestInput(question)

  const response = await fetch(`${process.env.RETRIEVER_URL}/search`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: question }),
    cache: 'no-store',
  })
  const { documents } = (await response.json()) as { documents: string[] }
  const answer = `Found ${documents.length} document(s).`

  setRequestOutput(answer)
  return Response.json({ answer })
}
