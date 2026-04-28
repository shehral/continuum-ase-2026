"use client"

import { cn } from "@/lib/utils"
import { Card } from "@/components/ui/card"
import { User, Zap } from "lucide-react"
import type { AskMessage } from "@/lib/api"
import { SourceCards } from "./source-cards"

interface MessageBubbleProps {
  message: AskMessage
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user"

  return (
    <div className={cn("flex gap-3", isUser && "flex-row-reverse")}>
      <div
        className={cn(
          "flex h-8 w-8 shrink-0 items-center justify-center rounded-lg",
          isUser
            ? "bg-muted"
            : "bg-gradient-to-br from-violet-500 to-fuchsia-500"
        )}
      >
        {isUser ? (
          <User className="h-4 w-4 text-muted-foreground" />
        ) : (
          <Zap className="h-4 w-4 text-white" />
        )}
      </div>

      <div className={cn("flex flex-col gap-2 max-w-[80%]", isUser && "items-end")}>
        <Card
          className={cn(
            "px-4 py-3 text-sm",
            isUser
              ? "bg-muted border-border"
              : "bg-card/80 backdrop-blur-sm border-border"
          )}
        >
          <div className="prose prose-sm dark:prose-invert max-w-none whitespace-pre-wrap">
            {message.content}
            {!isUser && !message.content && (
              <span className="inline-block h-4 w-1 animate-pulse bg-violet-400 ml-0.5" />
            )}
          </div>
        </Card>

        {!isUser && message.sources && message.sources.nodes.length > 0 && (
          <SourceCards sources={message.sources} />
        )}
      </div>
    </div>
  )
}
