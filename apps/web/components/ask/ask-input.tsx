"use client"

import { useState, useRef } from "react"
import { Send } from "lucide-react"

import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

interface AskInputProps {
  onSubmit: (query: string) => void
  isLoading: boolean
}

export function AskInput({ onSubmit, isLoading }: AskInputProps) {
  const [value, setValue] = useState("")
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = value.trim()
    if (trimmed && !isLoading) {
      onSubmit(trimmed)
      setValue("")
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2">
      <Input
        ref={inputRef}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Ask your knowledge graph..."
        disabled={isLoading}
        className="flex-1 bg-muted/50 border-border focus-visible:ring-violet-500"
        autoFocus
      />
      <Button
        type="submit"
        disabled={isLoading || !value.trim()}
        className={cn(
          "shrink-0",
          isLoading && "animate-pulse-glow"
        )}
      >
        <Send className="h-4 w-4" />
        <span className="sr-only">Send</span>
      </Button>
    </form>
  )
}
