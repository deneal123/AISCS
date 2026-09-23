import { useEffect, useState } from "react";

/** true, когда страница прокручена ниже порога — для уплотнения/блюра шапки. */
export function useHeaderScroll(threshold = 18) {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const handleScroll = () => setScrolled(window.scrollY > threshold);
    window.addEventListener("scroll", handleScroll);
    return () => window.removeEventListener("scroll", handleScroll);
  }, [threshold]);
  return scrolled;
}
