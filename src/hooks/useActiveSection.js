import { useEffect, useState } from "react";

/**
 * Scroll-spy: следит, какая из секций (по id) сейчас в поле зрения, и возвращает
 * её id. Для подсветки активного пункта якорной навигации + aria-current.
 * Порог/rootMargin подобраны так, чтобы активной считалась секция в верхней
 * трети вьюпорта (под sticky-хедером).
 */
export function useActiveSection(ids, { enabled = true } = {}) {
  const [active, setActive] = useState(null);

  useEffect(() => {
    if (!enabled || typeof window === "undefined" || !("IntersectionObserver" in window)) {
      return undefined;
    }
    const key = ids.join(",");
    const targetIds = key ? key.split(",") : [];
    const elements = targetIds
      .map((id) => document.getElementById(id))
      .filter(Boolean);
    if (!elements.length) return undefined;

    const visible = new Map();
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) visible.set(entry.target.id, entry.intersectionRatio);
          else visible.delete(entry.target.id);
        });
        // Активной делаем самую «верхнюю» видимую секцию из порядка ids.
        const firstVisible = targetIds.find((id) => visible.has(id));
        if (firstVisible) setActive(firstVisible);
      },
      { rootMargin: "-72px 0px -55% 0px", threshold: [0, 0.25, 0.5, 1] },
    );
    elements.forEach((el) => observer.observe(el));
    return () => observer.disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ids.join(","), enabled]);

  return active;
}
