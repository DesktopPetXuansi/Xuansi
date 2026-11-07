"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";
import { startAssembly } from "./assembly-controller";
import "./assembly.css";

// 与浏览器可见区域和动态内容同步；减少动态效果时保留完整静态页面。
export function AssemblyMotion() {
  const layer = useRef<HTMLDivElement>(null);
  const pathname = usePathname();

  useEffect(() => {
    const roots = [".site-header", "#main", ".site-footer"]
      .map((selector) => document.querySelector(selector))
      .filter(
        (element): element is HTMLElement => element instanceof HTMLElement,
      );
    const overlay = layer.current;
    if (
      !roots.length ||
      !overlay ||
      typeof IntersectionObserver === "undefined"
    )
      return;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const documentRoot = document.documentElement;
    let stop = () => {};
    function sync() {
      stop();
      if (
        preference.matches ||
        !documentRoot.hasAttribute("data-assembly-pending")
      ) {
        documentRoot.removeAttribute("data-assembly-active");
        stop = () => {};
        return;
      }
      documentRoot.setAttribute("data-assembly-active", "");
      stop = startAssembly(roots, overlay!);
    }
    preference.addEventListener("change", sync);
    sync();
    return () => {
      preference.removeEventListener("change", sync);
      stop();
      documentRoot.removeAttribute("data-assembly-active");
    };
  }, [pathname]);

  return <div ref={layer} className="assembly-layer" aria-hidden="true" />;
}
