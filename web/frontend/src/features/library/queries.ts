"use client";
import { api } from "@/lib/api";
import type { Resource } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
export function useLibrary() {
  return useQuery({ queryKey: ["library"],
    queryFn: () => api<{ resource: Resource; pinnedVersionId: string | null }[]>("/me/library") });
}
