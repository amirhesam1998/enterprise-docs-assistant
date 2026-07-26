import { useEffect, useState } from "react";
import { IconMoon, IconSun } from "./icons";

export function ThemeToggle() {
  const [dark, setDark] = useState(() =>
    document.documentElement.classList.contains("dark"),
  );

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("theme", dark ? "dark" : "light");
  }, [dark]);

  return (
    <button
      onClick={() => setDark((d) => !d)}
      className="grid h-9 w-9 place-items-center rounded-md border border-line text-muted
        transition-colors hover:bg-panel-2 hover:text-ink"
      aria-label={dark ? "Switch to light" : "Switch to dark"}
      title={dark ? "Light mode" : "Dark mode"}
    >
      {dark ? <IconSun /> : <IconMoon />}
    </button>
  );
}
