"use client";

import LiveStream from "@/components/liveStream";
import DetectionBox from "@/components/detectionBox";
import useDetection from "@/hooks/useDetection";

export default function LivePage() {
  const detections = useDetection();

  return (
    <div className="p-4">
      <h1 className="text-xl font-bold mb-4">Live Detection</h1>

      <div className="relative w-fit">
        <LiveStream />

        {detections.map((box, index) => (
          <DetectionBox key={index} box={box} />
        ))}
      </div>
    </div>
  );
}