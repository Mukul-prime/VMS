export default function DetectionBox({ box }) {
  return (
    <div
      className="absolute border-2 border-red-500"
      style={{
        top: box.y,
        left: box.x,
        width: box.width,
        height: box.height,
      }}
    >
      <span className="bg-red-500 text-white text-xs px-1">
        {box.label}
      </span>
    </div>
  );
}