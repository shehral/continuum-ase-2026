"use client"

import { cn } from "@/lib/utils"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area"
import { FileText, Box } from "lucide-react"
import type { AskSubgraph } from "@/lib/api"

const entityTypeColors: Record<string, string> = {
  technology: "bg-orange-500/10 text-orange-400 border-orange-500/20",
  pattern: "bg-rose-500/10 text-rose-400 border-rose-500/20",
  concept: "bg-violet-500/10 text-violet-400 border-violet-500/20",
  person: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  system: "bg-green-500/10 text-green-400 border-green-500/20",
}

interface SourceCardsProps {
  sources: AskSubgraph
}

export function SourceCards({ sources }: SourceCardsProps) {
  const sortedNodes = [...sources.nodes].sort((a, b) => {
    if (a.is_seed && !b.is_seed) return -1
    if (!a.is_seed && b.is_seed) return 1
    return 0
  })

  const displayNodes = sortedNodes.slice(0, 8)

  return (
    <div className="w-full">
      <p className="text-xs text-muted-foreground mb-2">
        Sources ({sources.nodes.length} nodes)
      </p>
      <ScrollArea className="w-full">
        <div className="flex gap-2 pb-2">
          {displayNodes.map((node) => (
            <Card
              key={node.id}
              className={cn(
                "shrink-0 w-48 p-3 cursor-pointer hover:border-violet-500/30 transition-colors",
                node.is_seed && "border-violet-500/20"
              )}
            >
              <div className="flex items-start gap-2">
                {node.type === "decision" ? (
                  <FileText className="h-4 w-4 text-violet-400 shrink-0 mt-0.5" />
                ) : (
                  <Box className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <p className="text-xs font-medium truncate">
                    {node.type === "decision"
                      ? (node.data.trigger || "Untitled decision")
                      : (node.data.name || "Unnamed entity")}
                  </p>
                  <Badge
                    variant="outline"
                    className={cn(
                      "mt-1 text-[10px] px-1.5 py-0",
                      node.type === "entity"
                        ? entityTypeColors[node.data.entity_type || "concept"]
                        : "bg-violet-500/10 text-violet-400 border-violet-500/20"
                    )}
                  >
                    {node.type === "entity"
                      ? node.data.entity_type
                      : "decision"}
                  </Badge>
                </div>
              </div>
            </Card>
          ))}
        </div>
        <ScrollBar orientation="horizontal" />
      </ScrollArea>
    </div>
  )
}
