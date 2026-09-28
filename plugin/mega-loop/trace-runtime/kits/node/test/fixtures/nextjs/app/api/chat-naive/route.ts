/** The same route without setRequestInput — what a Next app gets from the kit alone. */
export async function POST(request: Request): Promise<Response> {
  const { question } = (await request.json()) as { question: string }
  const response = await fetch(`${process.env.RETRIEVER_URL}/search`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ query: question }),
    cache: 'no-store',
  })
  const { documents } = (await response.json()) as { documents: string[] }
  return Response.json({ answer: `Found ${documents.length} document(s).` })
}
