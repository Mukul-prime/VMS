"use client";

export default function LiveStream() {
  return (
    <div className="relative">
      <img
        src="http://127.0.0.1:8000/video/"
        alt="Live"
        className="w-full border"
      />
    </div>
  );
}