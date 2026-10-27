"use client";
import { api } from "@/lib/api";
import type { LibraryEntry } from "@/lib/types";
import { useQuery } from "@tanstack/react-query";
export function useLibrary() {
  return useQuery({
    queryKey: ["library"],
    queryFn: () => api<LibraryEntry[]>("/me/library"),
  });
}
