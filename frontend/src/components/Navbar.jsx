"use client";

export default function Navbar() {
  return (
    <div className="bg-white shadow p-4 flex justify-between items-center">
      
      {/* Left */}
      <h1 className="text-lg text-black font-semibold">VMS Dashboard</h1>

      {/* Right */}
      <div className="flex items-center gap-4">
        
        {/* Status */}
        <span className="text-green-600 font-medium">
          ● Live
        </span>

        {/* User */}
        <div className="bg-gray-200 text-red-500 px-3 py-1 rounded">
          User
        </div>

      </div>
    </div>
  );
}