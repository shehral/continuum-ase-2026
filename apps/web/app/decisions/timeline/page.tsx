"use client"

import { useMemo } from "react"
import { useQuery } from "@tanstack/react-query"
import Link from "next/link"
import { ArrowLeft, Calendar, Circle, Lightbulb } from "lucide-react"

import { AppShell } from "@/components/layout/app-shell"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ErrorState } from "@/components/ui/error-state"
import { DecisionListSkeleton } from "@/components/ui/skeleton"
import { api, type Decision } from "@/lib/api"
import { getEntityStyle } from "@/lib/constants"

interface MonthGroup {
  label: string
  sortKey: string
  decisions: Decision[]
}

export default function TimelinePage() {
  const { data: allDecisions, isLoading, error, refetch } = useQuery({
    queryKey: ["all-decisions"],
    queryFn: () => api.getDecisions(),
    staleTime: 60 * 1000,
  })

  const monthGroups = useMemo(() => {
    if (!allDecisions?.length) return []

    const groups: Record<string, Decision[]> = {}

    allDecisions.forEach((decision) => {
      const date = new Date(decision.created_at)
      const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`
      const label = date.toLocaleDateString("en-US", { month: "long", year: "numeric" })
      if (!groups[key]) groups[key] = []
      groups[key].push(decision)
    })

    return Object.entries(groups)
      .map(([sortKey, decisions]): MonthGroup => ({
        label: new Date(sortKey + "-01").toLocaleDateString("en-US", { month: "long", year: "numeric" }),
        sortKey,
        decisions: decisions.sort(
          (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        ),
      }))
      .sort((a, b) => b.sortKey.localeCompare(a.sortKey))
  }, [allDecisions])

  return (
    <AppShell>
      <div className="max-w-3xl mx-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <Button variant="ghost" size="sm" asChild className="text-slate-400 hover:text-slate-200 -ml-2">
                <Link href="/decisions" className="flex items-center gap-1">
                  <ArrowLeft className="h-4 w-4" />
                  Decisions
                </Link>
              </Button>
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100 flex items-center gap-2">
              <Calendar className="h-6 w-6 text-violet-400" />
              Decision Timeline
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              {allDecisions?.length ?? 0} decisions across {monthGroups.length} months
            </p>
          </div>
        </div>

        {isLoading && <DecisionListSkeleton />}

        {error && (
          <ErrorState
            title="Failed to load decisions"
            message="Could not fetch your decisions."
            retry={() => refetch()}
          />
        )}

        {!isLoading && !error && monthGroups.length === 0 && (
          <Card variant="glass">
            <CardContent className="flex items-center justify-center py-12">
              <p className="text-muted-foreground">No decisions yet to show on the timeline</p>
            </CardContent>
          </Card>
        )}

        {/* Timeline */}
        <div className="relative">
          {/* Vertical line */}
          <div className="absolute left-4 top-0 bottom-0 w-px bg-gradient-to-b from-violet-500/40 via-fuchsia-500/30 to-transparent" />

          {monthGroups.map((group) => (
            <div key={group.sortKey} className="mb-8">
              {/* Month header */}
              <div className="flex items-center gap-3 mb-4 relative">
                <div className="w-8 h-8 rounded-full bg-violet-500/20 border border-violet-500/30 flex items-center justify-center z-10">
                  <Calendar className="h-4 w-4 text-violet-400" />
                </div>
                <h2 className="text-lg font-semibold text-slate-100">{group.label}</h2>
                <Badge className="bg-white/[0.04] text-slate-400 border-white/[0.08]">
                  {group.decisions.length}
                </Badge>
              </div>

              {/* Decision items */}
              <div className="space-y-3 ml-4 pl-7 border-l border-transparent">
                {group.decisions.map((decision) => (
                  <Link
                    key={decision.id}
                    href={`/decisions?id=${decision.id}`}
                    className="block group"
                  >
                    <div className="relative">
                      {/* Timeline dot */}
                      <div className="absolute -left-[31px] top-3 z-10">
                        <Circle className="h-2.5 w-2.5 text-fuchsia-400 fill-fuchsia-400/50" />
                      </div>

                      <Card className="bg-white/[0.03] border-white/[0.06] hover:bg-white/[0.06] hover:border-violet-500/30 transition-all duration-200 cursor-pointer">
                        <CardContent className="p-4">
                          <div className="flex items-start justify-between gap-3">
                            <div className="flex-1 min-w-0">
                              <p className="text-sm font-medium text-slate-200 group-hover:text-violet-300 transition-colors truncate">
                                {decision.trigger}
                              </p>
                              <p className="text-xs text-slate-500 mt-1 line-clamp-1">
                                {decision.agent_decision}
                              </p>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <Badge className={`text-[10px] px-1.5 py-0 ${
                                decision.confidence >= 0.8 ? "bg-emerald-500/15 text-emerald-400" :
                                decision.confidence >= 0.6 ? "bg-amber-500/15 text-amber-400" :
                                "bg-rose-500/15 text-rose-400"
                              }`}>
                                {Math.round(decision.confidence * 100)}%
                              </Badge>
                              <span className="text-[10px] text-slate-600">
                                {new Date(decision.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                              </span>
                            </div>
                          </div>

                          {decision.entities.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {decision.entities.slice(0, 3).map((entity) => {
                                const style = getEntityStyle(entity.type)
                                return (
                                  <Badge
                                    key={entity.id}
                                    className={`text-[10px] px-1.5 py-0 ${style.bg} ${style.text} ${style.border}`}
                                  >
                                    <style.lucideIcon className="h-2.5 w-2.5 mr-0.5" aria-hidden="true" />
                                    {entity.name}
                                  </Badge>
                                )
                              })}
                              {decision.entities.length > 3 && (
                                <Badge className="text-[10px] px-1.5 py-0 bg-slate-500/15 text-slate-400">
                                  +{decision.entities.length - 3}
                                </Badge>
                              )}
                            </div>
                          )}
                        </CardContent>
                      </Card>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </AppShell>
  )
}
