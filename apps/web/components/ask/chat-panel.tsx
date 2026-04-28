"use client"

import { useState, useRef, useEffect, useCallback } from "react"
import type { AskMessage, AskSubgraph } from "@/lib/api"
import { MessageBubble } from "./message-bubble"
import { AskInput } from "./ask-input"

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"

export function ChatPanel() {
  const [messages, setMessages] = useState<AskMessage[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const messageIdRef = useRef(0)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages])

  const handleSubmit = useCallback(async (query: string) => {
    const userMsgId = `msg-${++messageIdRef.current}`
    const assistantMsgId = `msg-${++messageIdRef.current}`

    const userMessage: AskMessage = {
      id: userMsgId,
      role: "user",
      content: query,
    }

    const assistantMessage: AskMessage = {
      id: assistantMsgId,
      role: "assistant",
      content: "",
    }

    setMessages((prev) => [...prev, userMessage, assistantMessage])
    setIsLoading(true)

    try {
      const params = new URLSearchParams({ q: query })
      const response = await fetch(`${API_URL}/api/ask?${params}`)

      if (!response.ok) {
        throw new Error(`API error: ${response.status}`)
      }

      const reader = response.body?.getReader()
      if (!reader) throw new Error("No response body")

      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })

        const lines = buffer.split("\n")
        buffer = lines.pop() || ""

        let eventType = ""
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6)
            try {
              const parsed = JSON.parse(data)

              if (eventType === "context") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, sources: parsed as AskSubgraph }
                      : m
                  )
                )
              } else if (eventType === "token") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: m.content + parsed.text }
                      : m
                  )
                )
              } else if (eventType === "error") {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: `Error: ${parsed.detail}` }
                      : m
                  )
                )
              }
            } catch {
              // Skip malformed JSON
            }
          }
        }
      }
    } catch (error) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? {
                ...m,
                content: `Failed to get response: ${error instanceof Error ? error.message : "Unknown error"}`,
              }
            : m
        )
      )
    } finally {
      setIsLoading(false)
    }
  }, [])

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto p-4" ref={scrollRef}>
        <div className="mx-auto max-w-3xl space-y-6">
          {messages.length === 0 && (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <div className="mb-4 h-16 w-16 rounded-2xl bg-gradient-to-br from-violet-500 via-fuchsia-500 to-orange-400 flex items-center justify-center shadow-glow-violet">
                <svg
                  className="h-8 w-8 text-white"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={1.5}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z"
                  />
                </svg>
              </div>
              <h2 className="text-xl font-semibold mb-2">Ask your knowledge graph</h2>
              <p className="text-muted-foreground max-w-md">
                Ask questions about your decisions, technologies, and patterns.
                Answers are grounded in your knowledge graph.
              </p>
            </div>
          )}

          {messages.map((message) => (
            <MessageBubble key={message.id} message={message} />
          ))}
        </div>
      </div>

      <div className="border-t border-border bg-card/50 backdrop-blur-sm p-4">
        <div className="mx-auto max-w-3xl">
          <AskInput onSubmit={handleSubmit} isLoading={isLoading} />
        </div>
      </div>
    </div>
  )
}
