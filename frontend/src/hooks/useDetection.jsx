"use client";
import { useEffect, useState } from "react";

export default function useDetection() {
  const [detections, setDetections] = useState([]);

  useEffect(() => {
    const interval = setInterval(() => {
      fetch("http://127.0.0.1:8000/detect/")
        .then((res) => res.json())
        .then((data) => setDetections(data));
    }, 1000); // every 1 sec

    return () => clearInterval(interval);
  }, []);

  return detections;
}