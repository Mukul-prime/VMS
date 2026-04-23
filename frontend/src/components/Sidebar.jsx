"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export default function Sidebar() {
  const pathname = usePathname();

  const menu = [
    { name: "Dashboard", path: "/" },
    { name: "Cameras", path: "/cameras" },
    { name: "Live", path: "/live" },
  ];

  return (
    <div className="h-full bg-black text-white p-5">
      {/* Logo */}
      <h2 className="text-2xl font-bold mb-8">VMS</h2>

      {/* Menu */}
      <nav className="flex flex-col gap-3">
        {menu.map((item) => (
          <Link
            key={item.path}
            href={item.path}
            className={`p-2 rounded transition ${
              pathname === item.path
                ? "bg-blue-500"
                : "hover:bg-gray-700"
            }`}
          >
            {item.name}
          </Link>
        ))}
      </nav>
    </div>
  );
}